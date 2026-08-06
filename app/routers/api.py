from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Alert, Conversation, ConversationDraft, ConversationMessage, ConversationReaction, Lead, MediaAsset, MessageQueue, Questionnaire, QuestionnaireVersionMigrationIssue, Segment, SurveyExecution, TranscriptionConfig, TranscriptionJob, User, utcnow
from ..services.engine import dashboard_metrics
from ..services.security import normalize_text
from ..services.segmentation import _score
from ..services.worker import process_once
from ..services.cache import redis_status
from ..services.transcription import transcription_diagnostics
from ..services.conversations import authorized_conversations, status_label

router = APIRouter(prefix="/api", tags=["api"])


def _authenticated(request: Request) -> None:
    if not request.session.get("user_id"):
        raise HTTPException(401, "Autenticação necessária.")


def _conversation(request: Request, db: Session, conversation_id: int) -> Conversation:
    _authenticated(request)
    user = db.get(User, request.session.get("user_id"))
    if not user or not user.active:
        raise HTTPException(401)
    row = db.scalar(authorized_conversations(user, include_lead=False).where(Conversation.id == conversation_id))
    if not row:
        raise HTTPException(404)
    return row


def _message_payloads(db: Session, messages: list[ConversationMessage], current_user_id: int | None = None) -> list[dict]:
    """Serializa um lote inteiro sem consultas repetidas por mensagem."""
    if not messages:
        return []
    message_ids = [message.id for message in messages]
    assets: dict[int, MediaAsset] = {}
    for asset in db.scalars(
        select(MediaAsset)
        .where(MediaAsset.conversation_message_id.in_(message_ids))
        .order_by(MediaAsset.conversation_message_id, MediaAsset.id)
    ).all():
        assets[asset.conversation_message_id] = asset
    grouped_reactions: dict[int, dict[str, dict]] = {}
    for reaction in db.scalars(
        select(ConversationReaction).where(ConversationReaction.conversation_message_id.in_(message_ids))
    ).all():
        grouped = grouped_reactions.setdefault(reaction.conversation_message_id, {})
        item = grouped.setdefault(reaction.emoji, {"count": 0, "mine": False})
        item["count"] += 1
        item["mine"] = item["mine"] or bool(reaction.actor_type == "user" and reaction.user_id == current_user_id)
    user_ids = {message.sender_user_id for message in messages if message.sender_user_id}
    sender_names = {
        user.id: user.name for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    payloads = []
    for message in messages:
        asset = assets.get(message.id)
        reactions = grouped_reactions.get(message.id, {})
        payloads.append({
            "id": message.id, "direction": message.direction, "content_type": message.content_type, "content": message.content or "",
            "occurred_at": message.occurred_at.isoformat(), "status": message.status, "error": message.error_message,
            "external_id": message.external_id, "reply_to_message_id": message.reply_to_message_id,
            "quoted_content": message.quoted_content, "is_internal": message.is_internal,
            "sender": sender_names.get(message.sender_user_id),
            "media": ({
                "id": asset.id, "type": asset.type, "mime": asset.mime_type, "name": asset.file_name,
                "caption": asset.caption, "size": asset.size_bytes, "url": f"/midias/{asset.id}",
                "ready": bool(asset.local_path), "download_status": asset.download_status,
                "transcription_status": asset.transcription_status,
                "transcript": asset.transcript_text,
            } if asset else None),
            "reactions": [{"emoji": emoji, **reaction} for emoji, reaction in reactions.items()],
        })
    return payloads


def _conversation_cursor(value: str | None) -> tuple[bool, datetime, int] | None:
    """Cursor estável: fixado, instante da última mensagem e identificador."""
    try:
        pinned, stamp, row_id = (value or "").split("|", 2)
        return pinned == "1", datetime.fromisoformat(stamp), int(row_id)
    except (TypeError, ValueError):
        return None


@router.get("/conversas")
def conversations_api(request: Request, q: str = "", before: str | None = None, limit: int = 40, status: str = "all", unread: bool = False, assigned: str = "all", db: Session = Depends(get_db)):
    _authenticated(request); limit = max(10, min(80, limit))
    user = db.get(User, request.session.get("user_id"))
    if not user or not user.active:
        raise HTTPException(401)
    query = authorized_conversations(user).where(Conversation.last_message_at.is_not(None))
    if status in {"open", "pending", "closed", "archived", "onboarding"}:
        query = query.where(Conversation.internal_status == status)
    if unread:
        query = query.where(Conversation.unread_count > 0)
    if assigned == "me":
        query = query.where(Conversation.assigned_user_id == user.id)
    elif assigned == "unassigned":
        query = query.where(Conversation.assigned_user_id.is_(None))
    cursor = _conversation_cursor(before)
    if cursor:
        pinned, stamp, row_id = cursor
        same_section_before = or_(
            Conversation.last_message_at < stamp,
            and_(Conversation.last_message_at == stamp, Conversation.id < row_id),
        )
        query = query.where(
            or_(
                and_(Conversation.pinned.is_(True), same_section_before) if pinned else False,
                Conversation.pinned.is_(False) if pinned else and_(Conversation.pinned.is_(False), same_section_before),
            )
        )
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Conversation.lead.has(Lead.name.ilike(term)), Conversation.phone_normalized.ilike(term), Conversation.last_message_preview.ilike(term)))
    rows = db.scalars(query.order_by(Conversation.pinned.desc(), Conversation.last_message_at.desc(), Conversation.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit; rows = rows[:limit]
    next_before = None
    if has_more and rows:
        last = rows[-1]
        next_before = f"{1 if last.pinned else 0}|{last.last_message_at.isoformat()}|{last.id}"
    assignee_ids = {row.assigned_user_id for row in rows if row.assigned_user_id}
    assignees = {item.id: item.name for item in db.scalars(select(User).where(User.id.in_(assignee_ids))).all()} if assignee_ids else {}
    return {"ok": True, "items": [{
        "id": row.id, "name": row.lead.name if row.lead else (row.phone_normalized or "Contato WhatsApp"),
        "phone": row.phone_normalized or row.whatsapp_lid, "preview": row.last_message_preview or "",
        "when": row.last_message_at.isoformat() if row.last_message_at else None, "unread": row.unread_count,
        "status": row.internal_status, "status_label": status_label(row.internal_status), "pinned": row.pinned,
        "assigned_user_id": row.assigned_user_id, "assigned_name": assignees.get(row.assigned_user_id),
    } for row in rows], "next_before": next_before}


@router.get("/conversas/{conversation_id}/mensagens")
def conversation_messages_api(request: Request, conversation_id: int, before: int | None = None, after: int | None = None, limit: int = 40, db: Session = Depends(get_db)):
    _conversation(request, db, conversation_id); limit = max(12, min(80, limit))
    current_user_id = int(request.session["user_id"])
    query = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
    if after:
        rows = db.scalars(query.where(ConversationMessage.id > after).order_by(ConversationMessage.id.asc()).limit(limit)).all()
        return {"ok": True, "items": _message_payloads(db, rows, current_user_id), "has_more": len(rows) == limit}
    if before: query = query.where(ConversationMessage.id < before)
    rows = db.scalars(query.order_by(ConversationMessage.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit; rows = list(reversed(rows[:limit]))
    return {"ok": True, "items": _message_payloads(db, rows, current_user_id), "has_more": has_more, "next_before": rows[0].id if has_more and rows else None}


@router.get("/conversas/{conversation_id}/atualizacoes")
def conversation_updates_api(request: Request, conversation_id: int, after: int = 0, since: str = "", db: Session = Depends(get_db)):
    _conversation(request, db, conversation_id)
    new_rows = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id, ConversationMessage.id > after).order_by(ConversationMessage.id).limit(80)).all()
    try:
        stamp = datetime.fromisoformat(since) if since else utcnow()
    except ValueError:
        stamp = utcnow()
    changed = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id, ConversationMessage.id <= after, ConversationMessage.status_at.is_not(None), ConversationMessage.status_at > stamp).order_by(ConversationMessage.id).limit(80)).all()
    combined = _message_payloads(db, [*new_rows, *changed], int(request.session["user_id"]))
    split_at = len(new_rows)
    return {"ok": True, "new": combined[:split_at], "changed": combined[split_at:], "server_time": utcnow().isoformat()}


@router.get("/conversas/{conversation_id}/rascunho")
def conversation_draft_get(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    _conversation(request, db, conversation_id); user_id = int(request.session["user_id"])
    row = db.scalar(select(ConversationDraft).where(ConversationDraft.conversation_id == conversation_id, ConversationDraft.user_id == user_id))
    return {"ok": True, "content": row.content if row else "", "reply_to_message_id": row.reply_to_message_id if row else None}


@router.put("/conversas/{conversation_id}/rascunho")
async def conversation_draft_put(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    _conversation(request, db, conversation_id); user_id = int(request.session["user_id"]); data = await request.json()
    row = db.scalar(select(ConversationDraft).where(ConversationDraft.conversation_id == conversation_id, ConversationDraft.user_id == user_id))
    if not row:
        row = ConversationDraft(conversation_id=conversation_id, user_id=user_id); db.add(row)
    row.content = str(data.get("content") or "")[:5000]; row.reply_to_message_id = int(data["reply_to_message_id"]) if str(data.get("reply_to_message_id") or "").isdigit() else None
    db.commit(); return {"ok": True}


@router.delete("/conversas/{conversation_id}/rascunho")
def conversation_draft_delete(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    _conversation(request, db, conversation_id); user_id = int(request.session["user_id"])
    row = db.scalar(select(ConversationDraft).where(ConversationDraft.conversation_id == conversation_id, ConversationDraft.user_id == user_id))
    if row:
        db.delete(row); db.commit()
    return {"ok": True}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    transcription = db.get(TranscriptionConfig, 1)
    transcription_info = transcription_diagnostics(transcription)
    return {
        "ok": True,
        "version": "3.6.0",
        "database": "online",
        "redis": redis_status(),
        "transcription": {
            "enabled": bool(transcription and transcription.enabled),
            "ready": transcription_info["ready"],
            "pending": db.scalar(select(func.count(TranscriptionJob.id)).where(TranscriptionJob.status == "pending")) or 0,
            "failed": db.scalar(select(func.count(TranscriptionJob.id)).where(TranscriptionJob.status == "failed")) or 0,
        },
        "queue_pending": db.scalar(select(func.count(MessageQueue.id)).where(MessageQueue.status == "pending")) or 0,
        "executions_pending": db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.status.in_(["scheduled", "active"]))) or 0,
        "executions_without_version": db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.questionnaire_version_id.is_(None))) or 0,
        "versioning_issues": db.scalar(select(func.count(QuestionnaireVersionMigrationIssue.id)).where(QuestionnaireVersionMigrationIssue.resolved.is_(False))) or 0,
    }


@router.get("/dashboard")
def dashboard_api(request: Request, db: Session = Depends(get_db)):
    _authenticated(request)
    return {"ok": True, "metrics": dashboard_metrics(db)}


@router.get("/segmentos/sugerir")
def segment_suggest(request: Request, text: str, db: Session = Depends(get_db)):
    _authenticated(request)
    output = []
    for segment in db.scalars(select(Segment).where(Segment.active.is_(True), Segment.kind == "smart")).all():
        import json
        keywords = json.loads(segment.keywords_json or "[]")
        confidence = max((_score(text, keyword) for keyword in keywords), default=0.0)
        if confidence >= 0.45:
            output.append({"id": segment.id, "name": segment.name, "confidence": round(confidence, 3), "automatic": confidence >= segment.min_confidence})
    output.sort(key=lambda item: item["confidence"], reverse=True)
    return {"ok": True, "normalized": normalize_text(text), "suggestions": output}


@router.post("/worker/run")
def run_worker_cycle(request: Request):
    _authenticated(request)
    return {"ok": True, "stats": process_once()}
