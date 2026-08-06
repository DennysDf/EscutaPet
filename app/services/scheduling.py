from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Lead, MessageQueue, Questionnaire, SurveyExecution, SystemSetting, utcnow
from .engine import channels, create_execution
from .security import normalize_phone
from .versioning import latest_published_version, version_config


OPERABLE_STATUSES = {"scheduled", "blocked", "active"}


def create_whatsapp_test_execution(
    db: Session,
    questionnaire: Questionnaire,
    phone_raw: str,
) -> tuple[SurveyExecution | None, str | None]:
    """Cria teste real isolado das métricas, segmentos e limites de produção."""
    published = latest_published_version(db, questionnaire)
    config = version_config(published) if published else None
    if not config or config.response_mode == "anonymous" or "whatsapp" not in channels(config):
        return None, "Este questionário não é compatível com teste identificado pelo WhatsApp."
    setting = db.get(SystemSetting, 1)
    phone = normalize_phone(phone_raw, setting.default_country_code if setting else "55")
    if not phone:
        return None, "Informe um número de WhatsApp válido para o teste."
    lead = db.scalar(select(Lead).where(Lead.phone_normalized == phone))
    if not lead:
        lead = Lead(
            name="Contato de teste",
            phone=phone_raw,
            phone_normalized=phone,
            source="laboratory",
            status="active",
            consent_research=True,
        )
        db.add(lead)
        db.flush()
    execution = create_execution(
        db,
        questionnaire,
        lead=lead,
        channel="whatsapp",
        source="whatsapp_laboratory",
        scheduled_at=utcnow(),
        is_test=True,
        test_label=f"Teste enviado para {phone}",
        questionnaire_version=published,
    )
    return execution, None


def reschedule_execution(db: Session, execution: SurveyExecution, scheduled_at: datetime) -> str | None:
    if execution.status not in {"scheduled", "blocked"}:
        return "Somente pesquisas ainda não iniciadas podem ser reagendadas."
    execution.status = "scheduled"
    execution.scheduled_at = scheduled_at
    if not execution.is_test:
        execution.test_label = None
    return None


def release_execution_now(db: Session, execution: SurveyExecution) -> str | None:
    if execution.status not in {"scheduled", "blocked"}:
        return "Esta pesquisa já foi iniciada ou encerrada."
    execution.status = "scheduled"
    execution.scheduled_at = utcnow()
    if not execution.is_test:
        execution.test_label = None
    return None


def cancel_execution(db: Session, execution: SurveyExecution) -> str | None:
    if execution.status not in OPERABLE_STATUSES:
        return "Esta execução já foi encerrada e não pode ser cancelada."
    execution.status = "cancelled"
    execution.completed_at = utcnow()
    db.execute(
        update(MessageQueue)
        .where(
            MessageQueue.execution_id == execution.id,
            MessageQueue.status.in_(["pending", "sending"]),
        )
        .values(status="cancelled", error_message="Cancelada pela Central de Agendamentos.")
    )
    return None


def retry_failed_delivery(db: Session, execution: SurveyExecution) -> str | None:
    if execution.status != "active":
        return "A repetição de mensagem está disponível somente em pesquisas em andamento."
    item = db.scalar(
        select(MessageQueue)
        .where(MessageQueue.execution_id == execution.id, MessageQueue.status == "failed")
        .order_by(MessageQueue.id.desc())
        .limit(1)
    )
    if not item:
        return "Não existe mensagem com falha para repetir nesta execução."
    item.status = "pending"
    item.attempt = 0
    item.available_at = utcnow()
    item.error_message = None
    return None
