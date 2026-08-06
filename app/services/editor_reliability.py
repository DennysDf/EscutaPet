from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EditorSubmission


@dataclass(frozen=True)
class EditorError:
    section: str
    item_key: str
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "section": self.section,
            "item_key": self.item_key,
            "field": self.field,
            "message": self.message,
        }


def error(section: str, field: str, message: str, item_key: str = "") -> dict[str, str]:
    return EditorError(section, item_key, field, message).as_dict()


def new_submission_token() -> str:
    return secrets.token_urlsafe(24)


def new_editor_key(kind: str) -> str:
    if kind not in {"question", "action", "option"}:
        raise ValueError("Tipo de chave do editor inválido.")
    prefix = f"{kind}:new:" if kind in {"question", "action"} else "option:"
    return prefix + str(uuid.uuid4())


def stable_editor_key(kind: str, value: object = "", database_id: int | None = None) -> str:
    if database_id and kind in {"question", "action"}:
        return f"{kind}:{int(database_id)}"
    candidate = str(value or "").strip()
    prefix = f"{kind}:new:" if kind in {"question", "action"} else "option:"
    if candidate.startswith(prefix):
        try:
            uuid.UUID(candidate[len(prefix):])
            return candidate
        except (ValueError, AttributeError):
            pass
    return new_editor_key(kind)


def completed_submission(request: Request, token: str) -> str | None:
    if not token:
        return None
    completed = request.session.get("editor_completed_submissions") or {}
    return completed.get(token)


def remember_submission(request: Request, token: str, destination: str) -> None:
    if not token:
        return
    completed = dict(request.session.get("editor_completed_submissions") or {})
    completed[token] = destination
    # A sessão fica pequena mesmo depois de muitas edições no mesmo navegador.
    request.session["editor_completed_submissions"] = dict(list(completed.items())[-12:])


def persisted_submission(db: Session, token: str) -> str | None:
    if not token:
        return None
    row = db.scalar(select(EditorSubmission).where(EditorSubmission.token == token))
    return row.destination if row and row.destination else None


def add_submission_claim(db: Session, token: str, scope: str) -> EditorSubmission | None:
    if not token:
        return None
    row = EditorSubmission(token=token, scope=scope, destination="")
    db.add(row)
    db.flush()
    return row
