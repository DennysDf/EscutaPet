from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..config import settings
from ..database import SessionLocal
from ..models import ConversationMessage, MediaAsset, MessageQueue, SurveyExecution, SystemSetting, WorkerState, ZapiConfig, utcnow
from .engine import add_conversation_message, ensure_conversation, schedule_recurrences, start_whatsapp_execution
from .media import download_pending_media, media_as_data_url, prune_old_media
from .zapi import send_interactive
from .timezone import valid_timezone
from .versioning import VersionConsistencyError
from .segment_automation import process_segment_automations
from .segmentation import refresh_all_rule_segments

logger = logging.getLogger(__name__)


def _next_allowed_utc(system: SystemSetting) -> datetime | None:
    zone = ZoneInfo(valid_timezone(system.timezone_name))
    now_local = datetime.now(zone)
    start = system.quiet_start_hour
    end = system.quiet_end_hour
    quiet = (start < end and start <= now_local.hour < end) or (start > end and (now_local.hour >= start or now_local.hour < end))
    if not quiet:
        return None
    target = now_local.replace(hour=end, minute=0, second=0, microsecond=0)
    if start > end and now_local.hour >= start:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc).replace(tzinfo=None)


def _execution_block_reason(db, execution: SurveyExecution, system: SystemSetting) -> str | None:
    lead = execution.lead
    if not lead or not (lead.phone_normalized or lead.whatsapp_lid):
        return "Lead sem identidade WhatsApp válida."
    if execution.is_test:
        return None
    if lead.opted_out_at or not lead.consent_research or lead.status != "active":
        return "Lead sem consentimento ativo para pesquisas."
    since = utcnow() - timedelta(days=max(1, system.contact_cap_days))
    recent = db.scalar(
        select(func.count(SurveyExecution.id)).where(
            SurveyExecution.lead_id == lead.id,
            SurveyExecution.id != execution.id,
            SurveyExecution.started_at >= since,
            SurveyExecution.is_test.is_(False),
        )
    ) or 0
    if recent >= max(1, system.contact_cap_count):
        return f"Limite de {system.contact_cap_count} pesquisa(s) em {system.contact_cap_days} dias atingido."
    return None


def process_once(*, worker_heartbeat: bool = False) -> dict[str, int]:
    stats = {
        "executions": 0, "messages": 0, "failed": 0, "simulated": 0,
        "postponed": 0, "blocked": 0, "media_saved": 0, "media_failed": 0, "media_pruned": 0,
        "segment_automations": 0, "segment_executions": 0,
        "segment_rules_checked": 0, "segment_entries": 0, "segment_exits": 0,
    }
    with SessionLocal() as db:
        state = db.get(WorkerState, 1)
        if worker_heartbeat and state:
            state.status = "running"
            state.heartbeat_at = utcnow()
            state.last_error = None
        system = db.get(SystemSetting, 1)
        # Atualiza os segmentos e suas jornadas antes de consumir execuções. Assim,
        # uma saída do segmento cancela o envio pendente antes que ele seja iniciado.
        stats.update(refresh_all_rule_segments(db))
        stats.update(process_segment_automations(db))
        next_allowed = _next_allowed_utc(system)
        for execution in db.scalars(
            select(SurveyExecution)
            .where(
                SurveyExecution.status == "scheduled",
                SurveyExecution.channel == "whatsapp",
                SurveyExecution.scheduled_at <= utcnow(),
            )
            .order_by(SurveyExecution.scheduled_at, SurveyExecution.id)
            .limit(30)
        ).all():
            if next_allowed:
                execution.scheduled_at = next_allowed
                stats["postponed"] += 1
                continue
            reason = _execution_block_reason(db, execution, system)
            if reason:
                execution.status = "blocked"
                execution.test_label = reason[:120]
                stats["blocked"] += 1
                continue
            try:
                start_whatsapp_execution(db, execution)
                stats["executions"] += 1
            except VersionConsistencyError as exc:
                execution.status = "blocked"
                execution.test_label = f"Erro de versão: {exc}"[:120]
                if state:
                    state.status = "degraded"
                    state.last_error = str(exc)[:1000]
                logger.error("Execução %s bloqueada por inconsistência de versão: %s", execution.id, exc)
                stats["blocked"] += 1
            except Exception as exc:
                execution.status = "blocked"
                execution.test_label = str(exc)[:120]
                logger.exception("Falha ao iniciar execução %s", execution.id)
                stats["blocked"] += 1
        schedule_recurrences(db)
        db.commit()

        config = db.get(ZapiConfig, 1)
        queue = db.scalars(
            select(MessageQueue)
            .where(MessageQueue.status == "pending", MessageQueue.available_at <= utcnow())
            .order_by(MessageQueue.available_at, MessageQueue.id)
            .limit(40)
        ).all()
        for item in queue:
            next_allowed = _next_allowed_utc(system)
            if next_allowed:
                item.available_at = next_allowed
                stats["postponed"] += 1
                continue
            item.status = "sending"
            item.attempt += 1
            db.commit()
            try:
                buttons = json.loads(item.buttons_json or "[]")
                media_payload = json.loads(item.media_payload_json or "{}")
                if item.media_asset_id:
                    asset = db.get(MediaAsset, item.media_asset_id)
                    if not asset:
                        raise ValueError("Anexo local não encontrado.")
                    payload_data = media_as_data_url(asset)
                    if not payload_data:
                        raise ValueError("Não foi possível ler o anexo local.")
                    media_payload["url"] = payload_data
                    media_payload["file_name"] = asset.file_name or media_payload.get("file_name")
                if config and not config.enabled and config.simulate_when_disabled:
                    item.status = "simulated"
                    item.sent_at = utcnow()
                    stats["simulated"] += 1
                    result_ok = True
                    result_message = "Envio simulado porque a Z-API está desativada."
                    external_id = f"sim-{item.id}"
                else:
                    result = send_interactive(
                        config, item.phone, item.payload_text,
                        message_type=item.message_type or ("buttons" if buttons else "text"),
                        options=buttons,
                        media_payload=media_payload,
                        reply_external_id=item.reply_external_id,
                    )
                    result_ok = result.ok
                    result_message = result.message
                    external_id = result.external_id
                if result_ok:
                    item.status = "sent" if not str(external_id).startswith("sim-") else "simulated"
                    item.external_id = external_id
                    item.sent_at = utcnow()
                    if item.conversation_message_id:
                        chat_message = db.get(ConversationMessage, item.conversation_message_id)
                        if chat_message:
                            chat_message.status = item.status
                            chat_message.status_at = utcnow()
                            chat_message.external_id = external_id or chat_message.external_id
                    lead = item.execution.lead if item.execution_id and item.execution else item.lead
                    phone = lead.phone_normalized if lead and lead.phone_normalized else (None if item.phone.endswith("@lid") else item.phone)
                    lid = lead.whatsapp_lid if lead and lead.whatsapp_lid else (item.phone if item.phone.endswith("@lid") else None)
                    conversation = ensure_conversation(db, phone, lead, lid)
                    if not item.conversation_message_id:
                        add_conversation_message(
                            db, conversation, direction="out", content=item.payload_text, external_id=external_id,
                            content_type=item.message_type if item.message_type in {"image", "audio", "video", "document", "location", "contact"} else "text", status=item.status,
                        )
                    stats["messages"] += 1
                else:
                    item.error_message = result_message
                    if item.attempt < 3:
                        item.status = "pending"
                        item.available_at = utcnow() + timedelta(minutes=5 * item.attempt)
                    else:
                        item.status = "failed"
                        stats["failed"] += 1
                    if item.conversation_message_id and item.status == "failed":
                        chat_message = db.get(ConversationMessage, item.conversation_message_id)
                        if chat_message:
                            chat_message.status = "failed"
                            chat_message.status_at = utcnow()
                            chat_message.error_message = result_message[:1000]
            except Exception as exc:
                item.error_message = str(exc)[:1000]
                item.status = "failed" if item.attempt >= 3 else "pending"
                item.available_at = utcnow() + timedelta(minutes=5)
                stats["failed"] += 1
                if item.conversation_message_id and item.attempt >= 3:
                    chat_message = db.get(ConversationMessage, item.conversation_message_id)
                    if chat_message:
                        chat_message.status = "failed"
                        chat_message.error_message = str(exc)[:1000]
            db.commit()
        media_stats = download_pending_media(db)
        stats.update({key: stats.get(key, 0) + value for key, value in media_stats.items()})
        prune_stats = prune_old_media(db)
        stats.update({key: stats.get(key, 0) + value for key, value in prune_stats.items()})
        if worker_heartbeat and state:
            state.status = "degraded" if state.last_error else "running"
            state.heartbeat_at = utcnow()
            state.last_cycle_at = utcnow()
            state.last_stats_json = json.dumps(stats, ensure_ascii=False)
            db.commit()
    return stats


def run_worker() -> None:
    print("EscutaPet Inteligente Worker iniciado. Pressione Ctrl+C para parar.")
    with SessionLocal() as db:
        state = db.get(WorkerState, 1)
        if state:
            state.status = "running"
            state.heartbeat_at = utcnow()
            state.last_error = None
            db.commit()
    while True:
        try:
            stats = process_once(worker_heartbeat=True)
            if any(stats.values()):
                print(stats)
        except KeyboardInterrupt:
            with SessionLocal() as db:
                state = db.get(WorkerState, 1)
                if state:
                    state.status = "stopped"
                    state.heartbeat_at = utcnow()
                    db.commit()
            break
        except Exception as exc:
            print(f"Falha no ciclo do worker: {exc}")
            with SessionLocal() as db:
                state = db.get(WorkerState, 1)
                if state:
                    state.status = "error"
                    state.heartbeat_at = utcnow()
                    state.last_error = str(exc)[:1000]
                    db.commit()
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run_worker()
