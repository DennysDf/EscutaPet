from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from ..models import Conversation, Lead, SystemSetting, User
from .timezone import valid_timezone


STATUS_LABELS = {
    "open": "Em atendimento",
    "pending": "Pendente",
    "closed": "Encerrada",
    "archived": "Arquivada",
    "onboarding": "Novo contato",
}


def user_city_ids(user: User | None) -> list[int] | None:
    if not user or user.role == "admin" or user.all_cities:
        return None
    try:
        return [int(value) for value in json.loads(user.city_ids_json or "[]")]
    except (TypeError, ValueError):
        return []


def authorized_conversations(user: User, *, include_lead: bool = True) -> Select:
    """Consulta única usada por página, busca, paginação e acesso direto."""
    query = select(Conversation)
    if include_lead:
        query = query.options(selectinload(Conversation.lead))
    allowed = user_city_ids(user)
    if allowed is not None:
        query = query.join(Lead, Conversation.lead_id == Lead.id).where(Lead.city_id.in_(allowed))
    return query


def status_label(value: str | None) -> str:
    return STATUS_LABELS.get(value or "open", (value or "Em atendimento").replace("_", " ").capitalize())


def quiet_window(system: SystemSetting | None) -> dict:
    if not system:
        return {"active": False, "label": "", "next_allowed": None}
    start = int(system.quiet_start_hour or 0)
    end = int(system.quiet_end_hour or 0)
    if start == end:
        return {"active": False, "label": "", "next_allowed": None}
    zone = ZoneInfo(valid_timezone(system.timezone_name))
    now = datetime.now(zone)
    active = (start < end and start <= now.hour < end) or (start > end and (now.hour >= start or now.hour < end))
    if not active:
        return {"active": False, "label": f"Silêncio das {start:02d}:00 às {end:02d}:00", "next_allowed": None}
    target = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if start > end and now.hour >= start:
        target += timedelta(days=1)
    return {
        "active": True,
        "label": f"Mensagens na fila serão enviadas a partir das {end:02d}:00",
        "next_allowed": target.isoformat(),
    }
