from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..database import SessionLocal
from ..models import (
    ConversationMessage,
    ConversationReaction,
    CollectionPet,
    CollectionSession,
    EntryFlow,
    Lead,
    MediaAsset,
    MessageQueue,
    PhoneVerification,
    Questionnaire,
    SurveyExecution,
    SystemSetting,
    TranscriptionConfig,
    WebhookEvent,
    ZapiConfig,
    utcnow,
)
from ..services.collection import complete_phone_verification, verification_by_interaction
from ..services.engine import (
    add_conversation_message,
    create_execution,
    ensure_conversation,
    get_active_whatsapp_execution,
    queue_invalid_response,
    record_answer,
    start_whatsapp_execution,
)
from ..services.security import normalize_phone, normalize_text
from ..services.media import register_media
from ..services.segmentation import segment_from_conversation
from ..services.zapi import compact_payload, payload_value, received_contact, received_content
from ..services.versioning import latest_published_version, version_config

router = APIRouter(prefix="/zapi/webhook", tags=["zapi-webhooks"])


def _verify(db, secret: str) -> ZapiConfig:
    config = db.get(ZapiConfig, 1)
    if not config or not secrets.compare_digest(secret or "", config.webhook_secret or ""):
        raise HTTPException(403, "Segredo de webhook inválido.")
    return config


async def _payload(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
        return value if isinstance(value, dict) else {"items": value}
    except Exception:
        try:
            return dict(await request.form())
        except Exception:
            return {}


def _identifiers(payload: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for key in ("messageId", "message_id", "id", "zaapId", "referenceMessageId", "quotedMsgId"):
        value = payload_value(payload, key, default=None)
        if value not in (None, ""):
            output.append(str(value))
    ids = payload.get("ids")
    if isinstance(ids, list):
        for value in ids:
            if isinstance(value, dict):
                for key in ("id", "messageId", "zaapId"):
                    if value.get(key):
                        output.append(str(value[key]))
            elif value not in (None, ""):
                output.append(str(value))
    return list(dict.fromkeys(item[:160] for item in output if item))


def _event_key(kind: str, payload: dict[str, Any]) -> str:
    identifiers = _identifiers(payload)
    status = str(payload_value(payload, "status", "type", "event", default="") or "")
    if identifiers:
        return f"{kind}:{','.join(identifiers[:3])}:{status}"[:190]
    digest = hashlib.sha256(compact_payload(payload).encode("utf-8")).hexdigest()
    return f"{kind}:{digest}"[:190]


def _register_event(db, kind: str, payload: dict[str, Any]) -> tuple[WebhookEvent, bool]:
    key = _event_key(kind, payload)
    existing = db.scalar(select(WebhookEvent).where(WebhookEvent.event_key == key))
    if existing:
        existing.duplicate_count = (existing.duplicate_count or 0) + 1
        return existing, True
    row = WebhookEvent(event_key=key, event_type=kind, payload_json=compact_payload(payload))
    db.add(row)
    db.flush()
    return row, False


def _instance_matches(config: ZapiConfig, payload: dict[str, Any]) -> bool:
    received = str(payload_value(payload, "instanceId", "instance_id", default="") or "").strip()
    return not received or not config.instance_id or secrets.compare_digest(received, config.instance_id.strip())


def _find_queue_item(db, payload: dict[str, Any]) -> MessageQueue | None:
    for identifier in _identifiers(payload):
        row = db.scalar(
            select(MessageQueue)
            .where(MessageQueue.external_id == identifier)
            .order_by(MessageQueue.id.desc())
            .limit(1)
        )
        if row:
            return row
    return None


def _status_to_state(raw: str, *, has_error: bool = False) -> str | None:
    if has_error:
        return "failed"
    value = raw.casefold()
    if "played" in value or "reproduz" in value:
        return "played"
    if any(word in value for word in ("read", "lida")):
        return "read"
    if any(word in value for word in ("received", "delivered", "entregue", "recebida")):
        return "delivered"
    if any(word in value for word in ("sent", "success", "enviada")):
        return "sent"
    if any(word in value for word in ("failed", "error", "erro")):
        return "failed"
    return None


def _ignored_message_reason(payload: dict[str, Any], content: dict[str, Any]) -> str | None:
    checks = (
        ("isGroup", "grupo"),
        ("isStatusReply", "status"),
        ("isNewsletter", "newsletter"),
        ("broadcast", "broadcast"),
        ("isEdit", "mensagem_editada"),
    )
    for key, reason in checks:
        if bool(payload_value(payload, key, default=False)):
            return reason
    event_type = str(payload_value(payload, "type", "event", default="") or "").casefold().strip()
    # `ReceivedCallback` is the standard Z-API type for text, media and button
    # replies. Never search for the substring `call`: it also exists inside
    # `callback` and previously caused every received message to be discarded.
    technical_prefixes = ("call", "notification", "newsletter", "status")
    if event_type and event_type != "receivedcallback" and event_type.startswith(technical_prefixes):
        return "evento_tecnico"
    if content.get("content_type") == "poll":
        return "poll"
    return None


def _execution_from_reference(db, reference_id: str | None, phone: str | None, lid: str | None) -> SurveyExecution | None:
    if not reference_id:
        return None
    item = db.scalar(
        select(MessageQueue)
        .where(MessageQueue.external_id == reference_id, MessageQueue.execution_id.is_not(None))
        .order_by(MessageQueue.id.desc())
        .limit(1)
    )
    if not item or not item.execution_id:
        return None
    execution = db.scalar(
        select(SurveyExecution)
        .options(
            selectinload(SurveyExecution.questionnaire).selectinload(Questionnaire.questions),
            selectinload(SurveyExecution.lead),
            selectinload(SurveyExecution.collection_session)
            .selectinload(CollectionSession.pets)
            .selectinload(CollectionPet.pet),
        )
        .where(SurveyExecution.id == item.execution_id, SurveyExecution.status == "active")
    )
    if not execution or not execution.lead:
        return None
    if phone and execution.lead.phone_normalized == phone:
        return execution
    if lid and execution.lead.whatsapp_lid == lid:
        return execution
    return None


def _start_onboarding(db, lead: Lead) -> SurveyExecution | None:
    onboarding = None
    for candidate in db.scalars(select(Questionnaire).where(
        Questionnaire.status == "active"
    ).order_by(Questionnaire.id)).all():
        published = latest_published_version(db, candidate)
        if published and version_config(published).trigger_type == "whatsapp_onboarding":
            onboarding = candidate
            break
    if not onboarding:
        return None
    execution = create_execution(db, onboarding, lead=lead, channel="whatsapp", source="unknown_whatsapp")
    start_whatsapp_execution(db, execution)
    return execution


@router.api_route("/receber/{secret}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def received(secret: str, request: Request):
    if request.method != "POST":
        with SessionLocal() as db:
            _verify(db, secret)
        return {"ok": True, "endpoint": "received"}

    payload = await _payload(request)
    with SessionLocal() as db:
        config = _verify(db, secret)
        event, duplicate = _register_event(db, "received", payload)
        if duplicate:
            db.commit()
            return {"ok": True, "duplicate": True}
        if not _instance_matches(config, payload):
            event.ignored_reason = "instancia_divergente"
            event.processed = True
            db.commit()
            return {"ok": True, "ignored": "instancia_divergente"}
        contact = received_contact(payload)
        content = received_content(payload)
        ignored_reason = _ignored_message_reason(payload, content)
        if ignored_reason:
            event.ignored_reason = f"{ignored_reason}_ignorado"
            event.processed = True
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "ignored": ignored_reason}

        phone_raw = contact.get("phone") or str(payload_value(payload, "phone", "from", default="") or "")
        setting = db.get(SystemSetting, 1)
        phone = normalize_phone(phone_raw, setting.default_country_code) if phone_raw else None
        lid = contact.get("lid") or None
        text = str(content.get("text") or "").strip()
        interaction_id = str(content.get("interaction_id") or "").strip() or None
        content_type = str(content.get("content_type") or "text")
        media = content.get("media") if isinstance(content.get("media"), dict) else {}
        reference_message_id = str(content.get("reference_message_id") or "").strip() or None
        external_id = (_identifiers(payload) or [None])[0]
        from_me = bool(payload_value(payload, "fromMe", "from_me", default=False))
        if not phone and not lid:
            event.ignored_reason = "identidade_ausente"
            event.processed = True
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "ignored": "identidade ausente"}

        lead = db.scalar(
            select(Lead).where(
                (Lead.phone_normalized == phone) if phone else (Lead.whatsapp_lid == lid)
            )
        )
        if not lead and phone and lid:
            lead = db.scalar(select(Lead).where(Lead.whatsapp_lid == lid))
        if lead:
            if phone and not lead.phone_normalized:
                lead.phone = phone
                lead.phone_normalized = phone
            if lid:
                lead.whatsapp_lid = lid
            lead.whatsapp_display_name = contact.get("sender_name") or lead.whatsapp_display_name
            lead.whatsapp_chat_name = contact.get("chat_name") or lead.whatsapp_chat_name
            lead.whatsapp_profile_photo_url = contact.get("sender_photo") or lead.whatsapp_profile_photo_url
            lead.whatsapp_identity_updated_at = utcnow()
            lead.whatsapp_identity_source = "webhook"
        conversation = ensure_conversation(db, phone, lead, lid)
        if content_type == "reaction":
            target = db.scalar(select(ConversationMessage).where(ConversationMessage.external_id == reference_message_id).order_by(ConversationMessage.id.desc()).limit(1))
            reaction_data = media.get("metadata") or {}
            emoji = str(reaction_data.get("emoji") or reaction_data.get("reaction") or text or "").strip()[:24]
            if target and emoji:
                existing = db.scalar(select(ConversationReaction).where(ConversationReaction.conversation_message_id == target.id, ConversationReaction.emoji == emoji, ConversationReaction.actor_type == ("user" if from_me else "contact"), ConversationReaction.external_id == (external_id or None)))
                if not existing:
                    db.add(ConversationReaction(conversation_message_id=target.id, emoji=emoji, actor_type="user" if from_me else "contact", external_id=external_id or None))
                event.processed = True; config.last_webhook_at = utcnow(); db.commit()
                return {"ok": True, "action": "reaction"}
        mirrored = None
        if external_id:
            mirrored = db.scalar(
                select(ConversationMessage)
                .where(ConversationMessage.external_id == external_id)
                .order_by(ConversationMessage.id.desc())
                .limit(1)
            )
        message_row = mirrored
        if not message_row:
            message_row = add_conversation_message(
                db,
                conversation,
                direction="out" if from_me else "in",
                content=text or f"[{content_type}]",
                interaction_id=interaction_id,
                external_id=external_id,
                reference_external_id=reference_message_id,
                content_type=content_type,
            )
            db.flush()
            if media:
                register_media(
                    db,
                    media,
                    media_type=content_type,
                    conversation_message_id=message_row.id,
                )

        if from_me:
            event.processed = True
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "action": "outgoing_mirrored"}

        recipient_key = phone or lid or ""
        verification = verification_by_interaction(db, recipient_key, interaction_id, text)
        if verification:
            complete_phone_verification(db, verification)
            event.processed = True
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "action": "phone_confirmed", "lead_id": verification.lead_id}

        if interaction_id == "consent:reject" or normalize_text(text) in {"sair", "parar", "cancelar", "nao quero", "não quero", "nao aceito", "não aceito"}:
            if lead:
                lead.opted_out_at = utcnow()
                lead.status = "opted_out"
                db.execute(
                    update(MessageQueue)
                    .where(MessageQueue.lead_id == lead.id, MessageQueue.status == "pending")
                    .values(status="cancelled", error_message="Cancelado por opt-out.")
                )
            event.processed = True
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "action": "opt_out"}

        if not lead and setting.allow_unknown_whatsapp_onboarding:
            lead = Lead(
                name=contact.get("sender_name") or contact.get("chat_name") or "Novo contato",
                phone=phone or None,
                phone_normalized=phone,
                whatsapp_lid=lid,
                whatsapp_display_name=contact.get("sender_name") or None,
                whatsapp_chat_name=contact.get("chat_name") or None,
                whatsapp_profile_photo_url=contact.get("sender_photo") or None,
                whatsapp_identity_updated_at=utcnow(),
                whatsapp_identity_source="webhook",
                source="whatsapp",
                status="onboarding",
                consent_research=False,
            )
            db.add(lead)
            db.flush()
            conversation.lead_id = lead.id
            db.add(MessageQueue(
                lead_id=lead.id,
                kind="research_consent",
                phone=recipient_key,
                payload_text=(
                    f"Olá, {lead.name.split()[0]}! Este canal realiza pesquisas para melhorar o atendimento.\n\n"
                    "Você aceita participar?"
                ),
                message_type="buttons",
                buttons_json=json.dumps([
                    {"id": "consent:accept", "label": "Aceito participar", "value": "aceito"},
                    {"id": "consent:reject", "label": "Não quero participar", "value": "não aceito"},
                ], ensure_ascii=False),
                status="pending",
                available_at=utcnow(),
            ))
            event.processed = True
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "action": "consent_requested", "lead_id": lead.id}

        consent_text = normalize_text(text)
        if lead and (
            interaction_id == "consent:accept"
            or consent_text in {"aceito", "aceito participar", "sim", "quero participar", "concordo"}
        ):
            lead.consent_research = True
            lead.status = "active"
            lead.opted_out_at = None
            _start_onboarding(db, lead)
            event.processed = True
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "action": "consent_accepted", "lead_id": lead.id}

        if lead and (lead.status == "onboarding" or not lead.consent_research):
            event.processed = True
            event.ignored_reason = "aguardando_consentimento"
            config.last_webhook_at = utcnow()
            db.commit()
            return {"ok": True, "action": "awaiting_consent"}

        execution = _execution_from_reference(db, reference_message_id, phone, lid)
        if not execution:
            execution = get_active_whatsapp_execution(db, phone, lid)
        action = "conversation_only"
        answer_id = None
        if execution and (text or interaction_id or media):
            if not execution.questionnaire or not execution.lead:
                execution = db.scalar(
                    select(SurveyExecution)
                    .options(
                        selectinload(SurveyExecution.questionnaire).selectinload(Questionnaire.questions),
                        selectinload(SurveyExecution.lead),
                    )
                    .where(SurveyExecution.id == execution.id)
                )
            try:
                answer = record_answer(
                    db,
                    execution,
                    raw_text=text or interaction_id or "",
                    interaction_id=interaction_id,
                    source="whatsapp",
                    content_type=content_type,
                )
                action = "answer_recorded"
                answer_id = answer.id
                if media:
                    asset = db.scalar(
                        select(MediaAsset)
                        .where(MediaAsset.conversation_message_id == message_row.id)
                        .order_by(MediaAsset.id.desc())
                        .limit(1)
                    )
                    if asset:
                        asset.survey_answer_id = answer.id
            except ValueError as exc:
                action = "invalid_answer"
                event.ignored_reason = str(exc)[:160]
                queue_invalid_response(db, execution, str(exc))

        transcription_config = db.get(TranscriptionConfig, 1)
        if action == "conversation_only" and lead and text and transcription_config and transcription_config.segment_received_text:
            segment_from_conversation(
                db, lead.id, text,
                origin="conversation_text", reason_label=f"Mensagem recebida no WhatsApp #{message_row.id}",
            )

        event.processed = True
        config.last_webhook_at = utcnow()
        db.commit()
        response = {"ok": True, "action": action}
        if answer_id:
            response["answer_id"] = answer_id
        if action == "invalid_answer":
            response["message"] = event.ignored_reason
        return response


async def _process_status(secret: str, request: Request, kind: str):
    if request.method != "POST":
        with SessionLocal() as db:
            _verify(db, secret)
        return {"ok": True, "endpoint": kind}
    payload = await _payload(request)
    with SessionLocal() as db:
        config = _verify(db, secret)
        event, duplicate = _register_event(db, kind, payload)
        if duplicate:
            db.commit()
            return {"ok": True, "duplicate": True}
        if not _instance_matches(config, payload):
            event.ignored_reason = "instancia_divergente"
            event.processed = True
            db.commit()
            return {"ok": True, "ignored": "instancia_divergente"}

        item = _find_queue_item(db, payload)
        error = str(payload_value(payload, "error", "message", default="") or "")
        raw_status = str(payload_value(payload, "status", "event", "type", default="") or "")
        state = _status_to_state(raw_status, has_error=bool(error))
        if kind == "delivery" and not state:
            state = "failed" if error else "sent"
        if item and state:
            item.status = state
            if state == "failed":
                item.error_message = (error or raw_status or "Falha informada pelo webhook")[:1000]
            if state in {"sent", "delivered", "read", "played"} and not item.sent_at:
                item.sent_at = utcnow()
            if item.conversation_message_id:
                message = db.get(ConversationMessage, item.conversation_message_id)
                if message:
                    message.status = state
                    message.status_at = utcnow()
                    if state == "failed": message.error_message = item.error_message
            verification = db.scalar(select(PhoneVerification).where(PhoneVerification.message_queue_id == item.id))
            if verification and verification.status != "confirmed":
                verification.status = state
                if state == "sent":
                    verification.sent_at = verification.sent_at or utcnow()
                elif state == "delivered":
                    verification.sent_at = verification.sent_at or utcnow()
                    verification.delivered_at = utcnow()
                elif state in {"read", "played"}:
                    verification.sent_at = verification.sent_at or utcnow()
                    verification.delivered_at = verification.delivered_at or utcnow()
                    verification.read_at = utcnow()
                elif state == "failed":
                    verification.failure_reason = item.error_message
        else:
            event.ignored_reason = "mensagem_ou_estado_nao_encontrado"
        event.processed = True
        config.last_webhook_at = utcnow()
        db.commit()
        return {"ok": True, "updated": bool(item and state), "state": state}


@router.api_route("/envio/{secret}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def delivery(secret: str, request: Request):
    return await _process_status(secret, request, "delivery")


@router.api_route("/status/{secret}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def status(secret: str, request: Request):
    return await _process_status(secret, request, "status")


@router.api_route("/conectado/{secret}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def connected(secret: str, request: Request):
    if request.method != "POST":
        with SessionLocal() as db:
            _verify(db, secret)
        return {"ok": True, "endpoint": "connected"}
    payload = await _payload(request)
    with SessionLocal() as db:
        config = _verify(db, secret)
        if request.method == "POST":
            event, duplicate = _register_event(db, "connected", payload)
            if duplicate:
                db.commit()
                return {"ok": True, "duplicate": True}
            if not _instance_matches(config, payload):
                event.ignored_reason = "instancia_divergente"
                event.processed = True
                db.commit()
                return {"ok": True, "ignored": "instancia_divergente"}
            event.processed = True
            config.last_webhook_at = utcnow()
            phone = str(payload_value(payload, "phone", default="") or "")
            if phone:
                config.device_phone = phone[:40]
        config.connected = True
        config.last_check_at = utcnow()
        config.last_error = None
        db.commit()
    return {"ok": True, "connected": True}


@router.api_route("/desconectado/{secret}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def disconnected(secret: str, request: Request):
    if request.method != "POST":
        with SessionLocal() as db:
            _verify(db, secret)
        return {"ok": True, "endpoint": "disconnected"}
    payload = await _payload(request)
    with SessionLocal() as db:
        config = _verify(db, secret)
        if request.method == "POST":
            event, duplicate = _register_event(db, "disconnected", payload)
            if duplicate:
                db.commit()
                return {"ok": True, "duplicate": True}
            if not _instance_matches(config, payload):
                event.ignored_reason = "instancia_divergente"
                event.processed = True
                db.commit()
                return {"ok": True, "ignored": "instancia_divergente"}
            event.processed = True
            config.last_webhook_at = utcnow()
            error = str(payload_value(payload, "error", default="") or "")
            config.last_error = error[:1000] or "WhatsApp desconectado da instância."
        config.connected = False
        config.last_check_at = utcnow()
        db.commit()
    return {"ok": True, "connected": False}
