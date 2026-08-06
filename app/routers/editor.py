from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, EditorDraft, EntryFlow, Questionnaire, utcnow
from .web import require_user

router = APIRouter()
ENTITY_TYPES = {"flow": EntryFlow, "questionnaire": Questionnaire}
ENTITY_KEY_RE = re.compile(r"^(?:new:[a-zA-Z0-9_-]{6,80}|[1-9][0-9]{0,12})$")
MAX_DRAFT_BYTES = 1_500_000


def _entity_id(entity_key: str) -> int | None:
    return int(entity_key) if entity_key.isdigit() else None


def _validated_target(db: Session, entity_type: str, entity_key: str):
    model = ENTITY_TYPES.get(entity_type)
    if not model or not ENTITY_KEY_RE.fullmatch(entity_key):
        raise HTTPException(400, "Editor ou item inválido.")
    entity_id = _entity_id(entity_key)
    row = db.get(model, entity_id) if entity_id else None
    if entity_id and not row:
        raise HTTPException(404)
    return row


def _draft(db: Session, user_id: int, entity_type: str, entity_key: str) -> EditorDraft | None:
    return db.scalar(select(EditorDraft).where(
        EditorDraft.user_id == user_id,
        EditorDraft.entity_type == entity_type,
        EditorDraft.entity_key == entity_key,
    ))


@router.get("/api/editor-drafts/{entity_type}/{entity_key}")
def editor_draft_get(request: Request, entity_type: str, entity_key: str, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = _validated_target(db, entity_type, entity_key)
    draft = _draft(db, user.id, entity_type, entity_key)
    if not draft:
        return {"ok": True, "draft": None, "server": {
            "revision": getattr(row, "revision", 0) if row else 0,
            "updated_at": row.updated_at.isoformat() if row else None,
        }}
    return {
        "ok": True,
        "draft": {
            "id": draft.id,
            "base_revision": draft.base_revision,
            "client_updated_at": draft.client_updated_at,
            "server_saved_at": draft.updated_at.isoformat(),
            "payload": json.loads(draft.payload_json or "{}"),
        },
        "server": {
            "revision": getattr(row, "revision", 0) if row else 0,
            "updated_at": row.updated_at.isoformat() if row else None,
        },
    }


@router.post("/api/editor-drafts/{entity_type}/{entity_key}")
async def editor_draft_save(request: Request, entity_type: str, entity_key: str, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = _validated_target(db, entity_type, entity_key)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, "Rascunho inválido.")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise HTTPException(413, "Rascunho excede o limite de segurança.")
    base_revision = int(payload.get("base_revision") or 0)
    current_revision = getattr(row, "revision", 0) if row else 0
    draft = _draft(db, user.id, entity_type, entity_key)
    if not draft:
        draft = EditorDraft(
            user_id=user.id,
            entity_type=entity_type,
            entity_key=entity_key,
            entity_id=_entity_id(entity_key),
        )
        db.add(draft)
    draft.base_revision = base_revision
    draft.client_updated_at = str(payload.get("saved_at") or "")[:50] or None
    draft.payload_json = encoded
    db.commit()
    return {
        "ok": True,
        "draft_id": draft.id,
        "saved_at": draft.updated_at.isoformat(),
        "current_revision": current_revision,
        "conflict": bool(row and base_revision and base_revision != current_revision),
    }


@router.post("/api/editor-drafts/{entity_type}/{entity_key}/restore")
def editor_draft_restore(request: Request, entity_type: str, entity_key: str, db: Session = Depends(get_db)):
    user = require_user(request, db)
    _validated_target(db, entity_type, entity_key)
    draft = _draft(db, user.id, entity_type, entity_key)
    if not draft:
        raise HTTPException(404)
    db.add(AuditLog(
        user_id=user.id,
        action="editor_draft_restore",
        entity=entity_type,
        entity_id=draft.entity_id,
        details=json.dumps({"draft_id": draft.id, "base_revision": draft.base_revision}, ensure_ascii=False),
    ))
    db.commit()
    return {"ok": True}


@router.delete("/api/editor-drafts/{entity_type}/{entity_key}")
def editor_draft_delete(request: Request, entity_type: str, entity_key: str, db: Session = Depends(get_db)):
    user = require_user(request, db)
    _validated_target(db, entity_type, entity_key)
    draft = _draft(db, user.id, entity_type, entity_key)
    if draft:
        db.delete(draft)
        db.commit()
    return {"ok": True}
