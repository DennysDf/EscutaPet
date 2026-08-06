from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Lead,
    LeadSegment,
    Questionnaire,
    Segment,
    SegmentAutomation,
    SegmentAutomationEnrollment,
    SegmentAutomationQuestionnaire,
    SurveyExecution,
    utcnow,
)
from .engine import channels, create_execution
from .segmentation import refresh_rule_segment
from .timezone import DEFAULT_TIMEZONE, valid_timezone
from .versioning import latest_published_version, version_config

ACTIVE_EXECUTION_STATUSES = {"scheduled", "active"}

def _hash_int(*parts: object) -> int:
    payload = ":".join(str(part) for part in parts)
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12], 16)


def _questionnaire_pool(db: Session, automation: SegmentAutomation) -> list[tuple[Questionnaire, object]]:
    links = db.scalars(
        select(SegmentAutomationQuestionnaire)
        .where(
            SegmentAutomationQuestionnaire.automation_id == automation.id,
            SegmentAutomationQuestionnaire.active.is_(True),
        )
        .order_by(SegmentAutomationQuestionnaire.position, SegmentAutomationQuestionnaire.id)
    ).all() if automation.id else []
    questionnaire_ids = [item.questionnaire_id for item in links]
    if automation.questionnaire_id and automation.questionnaire_id not in questionnaire_ids:
        questionnaire_ids.insert(0, automation.questionnaire_id)

    pool: list[tuple[Questionnaire, object]] = []
    for questionnaire_id in questionnaire_ids:
        questionnaire = db.get(Questionnaire, questionnaire_id)
        version = latest_published_version(db, questionnaire) if questionnaire else None
        config = version_config(version) if version else None
        if (
            questionnaire
            and questionnaire.status == "active"
            and version
            and config
            and "whatsapp" in channels(config)
            and config.response_mode == "identified"
        ):
            pool.append((questionnaire, version))
    return pool


def _history(enrollment: SegmentAutomationEnrollment | None) -> list[int]:
    if not enrollment:
        return []
    try:
        values = json.loads(enrollment.history_json or "[]")
        return [int(value) for value in values if str(value).isdigit()]
    except (TypeError, ValueError):
        return []


def _choose_questionnaire(
    automation: SegmentAutomation,
    pool: list[tuple[Questionnaire, object]],
    lead_id: int,
    cycle: int,
    enrollment: SegmentAutomationEnrollment | None = None,
) -> tuple[Questionnaire, object] | None:
    if not pool:
        return None
    strategy = automation.selection_strategy or "single"
    if strategy == "round_robin":
        return pool[(max(1, cycle) - 1) % len(pool)]
    if strategy == "random_no_repeat":
        used = set(_history(enrollment))
        available = [item for item in pool if item[0].id not in used]
        if not available:
            if enrollment:
                enrollment.history_json = "[]"
            available = pool
        return available[_hash_int(automation.id, lead_id, cycle, "questionnaire") % len(available)]
    if strategy == "random":
        return pool[_hash_int(automation.id, lead_id, cycle, "questionnaire") % len(pool)]
    return pool[0]


def _sampled(automation: SegmentAutomation, lead_id: int, cycle: int) -> bool:
    percent = max(1, min(100, automation.sample_percent or 100))
    sample_cycle = cycle if (automation.sample_mode or "per_cycle") == "per_cycle" else 0
    marker = _hash_int(automation.id or "preview", lead_id, sample_cycle, "sample") % 100 + 1
    return marker <= percent


def _minutes(value: int | None, fallback: int) -> int:
    return max(0, min(1439, int(value if value is not None else fallback)))


def _windowed_time(automation: SegmentAutomation, due_at: datetime, lead_id: int, cycle: int) -> datetime:
    """Ajusta o horário para a janela local e o distribui de modo estável por lead/ciclo."""
    zone = ZoneInfo(valid_timezone(automation.timezone_name or DEFAULT_TIMEZONE))
    local_due = due_at.replace(tzinfo=timezone.utc).astimezone(zone)
    start = _minutes(automation.send_window_start, 540)
    end = _minutes(automation.send_window_end, 1020)
    if end <= start:
        end = min(1439, start + 60)

    due_minute = local_due.hour * 60 + local_due.minute
    day = local_due.date()
    lower = start
    if due_minute > end:
        day += timedelta(days=1)
    elif due_minute >= start:
        lower = due_minute

    mode = automation.distribution_mode or "fixed"
    if mode in {"random", "uniform"}:
        span = max(1, end - lower + 1)
        minute = lower + (_hash_int(automation.id, lead_id, cycle, "window") % span)
    else:
        minute = lower

    target_local = datetime.combine(day, datetime.min.time(), tzinfo=zone).replace(
        hour=minute // 60,
        minute=minute % 60,
    )
    return target_local.astimezone(timezone.utc).replace(tzinfo=None)


def _entry_due(automation: SegmentAutomation, entered_at: datetime) -> datetime:
    value = max(0, automation.entry_delay_value or 0)
    unit = automation.entry_delay_unit or "hours"
    if unit == "minutes":
        return entered_at + timedelta(minutes=value)
    if unit == "days":
        return entered_at + timedelta(days=value)
    return entered_at + timedelta(hours=value)


def _lead_block_reason(
    db: Session,
    automation: SegmentAutomation,
    lead: Lead,
    questionnaire: Questionnaire,
) -> tuple[str | None, datetime | None]:
    now = utcnow()
    if lead.status != "active" or lead.opted_out_at or not lead.consent_research:
        return "without_consent", now + timedelta(days=1)
    if not (lead.phone_normalized or lead.whatsapp_lid):
        return "without_whatsapp", now + timedelta(days=1)
    if automation.require_confirmed and not lead.number_validated:
        return "unconfirmed", now + timedelta(days=1)

    if automation.block_while_active:
        active = db.scalar(
            select(SurveyExecution.id).where(
                SurveyExecution.lead_id == lead.id,
                SurveyExecution.is_test.is_(False),
                SurveyExecution.status.in_(ACTIVE_EXECUTION_STATUSES),
            ).limit(1)
        )
        if active:
            return "active_execution", now + timedelta(days=1)

    # Automações 3.5.x usavam apenas exclude_previous; preserva esse contrato.
    policy = "never" if automation.exclude_previous else (automation.repeat_policy or "allow")
    previous = db.scalar(
        select(SurveyExecution)
        .where(
            SurveyExecution.lead_id == lead.id,
            SurveyExecution.questionnaire_id == questionnaire.id,
            SurveyExecution.is_test.is_(False),
            SurveyExecution.status != "cancelled",
        )
        .order_by(SurveyExecution.scheduled_at.desc(), SurveyExecution.id.desc())
        .limit(1)
    )
    if previous and policy == "never":
        return "already_received", None
    if previous and policy == "cooldown":
        release_at = previous.scheduled_at + timedelta(days=max(1, automation.cooldown_days or 1))
        if release_at > now:
            return "cooldown", release_at
    return None, None


def _base_stats(segment_count: int = 0) -> dict[str, int]:
    return {
        "segment": segment_count,
        "eligible": 0,
        "without_whatsapp": 0,
        "without_consent": 0,
        "already_received": 0,
        "unconfirmed": 0,
        "active_execution": 0,
        "cooldown": 0,
        "outside_sample": 0,
    }


def automation_candidates(db: Session, automation: SegmentAutomation) -> tuple[list[Lead], dict[str, int]]:
    pool = _questionnaire_pool(db, automation)
    if not pool:
        return [], _base_stats()
    leads = db.scalars(
        select(Lead)
        .join(LeadSegment)
        .where(LeadSegment.segment_id == automation.segment_id, Lead.source != "laboratory")
        .order_by(Lead.id)
    ).unique().all()
    stats = _base_stats(len(leads))
    eligible: list[Lead] = []
    for lead in leads:
        cycle = 1
        if not _sampled(automation, lead.id, cycle):
            stats["outside_sample"] += 1
            continue
        selected = _choose_questionnaire(automation, pool, lead.id, cycle)
        if not selected:
            continue
        reason, _ = _lead_block_reason(db, automation, lead, selected[0])
        if reason:
            stats[reason] = stats.get(reason, 0) + 1
            continue
        eligible.append(lead)
    stats["eligible"] = len(eligible)
    return eligible, stats


def _get_or_create_enrollment(
    db: Session,
    automation: SegmentAutomation,
    lead: Lead,
    entered_at: datetime,
    *,
    schedule_entry: bool,
) -> SegmentAutomationEnrollment:
    enrollment = db.scalar(
        select(SegmentAutomationEnrollment).where(
            SegmentAutomationEnrollment.automation_id == automation.id,
            SegmentAutomationEnrollment.lead_id == lead.id,
        )
    )
    if enrollment:
        if enrollment.status == "cancelled" and schedule_entry:
            enrollment.status = "active"
            enrollment.entered_at = entered_at
            enrollment.next_due_at = _entry_due(automation, max(entered_at, automation.created_at or entered_at))
            enrollment.blocked_reason = None
        return enrollment
    enrollment = SegmentAutomationEnrollment(
        automation_id=automation.id,
        lead_id=lead.id,
        entered_at=entered_at,
        next_due_at=_entry_due(automation, max(entered_at, automation.created_at or entered_at)) if schedule_entry else None,
        status="active",
    )
    db.add(enrollment)
    db.flush()
    return enrollment


def sync_segment_enrollments(db: Session, automation: SegmentAutomation) -> dict[str, int]:
    if automation.trigger_type not in {"on_entry", "hybrid"}:
        return {"enrolled": 0, "cancelled": 0}
    links = db.scalars(
        select(LeadSegment).where(LeadSegment.segment_id == automation.segment_id)
    ).all()
    current_ids = {link.lead_id for link in links}
    enrolled = 0
    for link in links:
        lead = db.get(Lead, link.lead_id)
        if not lead or lead.source == "laboratory":
            continue
        existing = db.scalar(
            select(SegmentAutomationEnrollment.id).where(
                SegmentAutomationEnrollment.automation_id == automation.id,
                SegmentAutomationEnrollment.lead_id == lead.id,
            )
        )
        _get_or_create_enrollment(db, automation, lead, link.created_at, schedule_entry=True)
        if not existing:
            enrolled += 1

    cancelled = 0
    if automation.cancel_on_exit:
        active_rows = db.scalars(
            select(SegmentAutomationEnrollment).where(
                SegmentAutomationEnrollment.automation_id == automation.id,
                SegmentAutomationEnrollment.status.in_(["active", "blocked"]),
            )
        ).all()
        for enrollment in active_rows:
            if enrollment.lead_id not in current_ids:
                enrollment.status = "cancelled"
                enrollment.next_due_at = None
                enrollment.blocked_reason = "Saiu do segmento antes do próximo envio."
                future_executions = db.scalars(select(SurveyExecution).where(
                    SurveyExecution.lead_id == enrollment.lead_id,
                    SurveyExecution.source == f"segment_automation:{automation.id}",
                    SurveyExecution.status == "scheduled",
                )).all()
                for execution in future_executions:
                    execution.status = "cancelled"
                    execution.test_label = "Cancelada porque o lead saiu do segmento."
                cancelled += 1
    return {"enrolled": enrolled, "cancelled": cancelled}


def _record_enrollment_schedule(
    enrollment: SegmentAutomationEnrollment,
    questionnaire_id: int,
    scheduled_at: datetime,
    automation: SegmentAutomation,
) -> None:
    history = _history(enrollment)
    if questionnaire_id not in history:
        history.append(questionnaire_id)
    # Mantém histórico compacto; o modo sem repetição reinicia a lista ao completar o conjunto.
    enrollment.history_json = json.dumps(history[-20:])
    enrollment.last_questionnaire_id = questionnaire_id
    enrollment.last_scheduled_at = scheduled_at
    enrollment.cycle_number += 1
    enrollment.sent_count += 1
    enrollment.blocked_reason = None
    if automation.recurrence_days and automation.trigger_type in {"on_entry", "hybrid"}:
        if automation.max_cycles and enrollment.cycle_number >= automation.max_cycles:
            enrollment.status = "completed"
            enrollment.next_due_at = None
        else:
            enrollment.status = "active"
            enrollment.next_due_at = scheduled_at + timedelta(days=max(1, automation.recurrence_days))
    else:
        enrollment.status = "completed"
        enrollment.next_due_at = None


def _schedule_for_enrollment(
    db: Session,
    automation: SegmentAutomation,
    enrollment: SegmentAutomationEnrollment,
    pool: list[tuple[Questionnaire, object]],
    due_at: datetime,
) -> tuple[bool, str | None]:
    lead = db.get(Lead, enrollment.lead_id)
    if not lead:
        enrollment.status = "cancelled"
        enrollment.next_due_at = None
        enrollment.blocked_reason = "Lead removido."
        return False, "without_lead"
    cycle = enrollment.cycle_number + 1
    if automation.max_cycles and cycle > automation.max_cycles:
        enrollment.status = "completed"
        enrollment.next_due_at = None
        return False, "max_cycles"
    if not _sampled(automation, lead.id, cycle):
        # A rodada conta mesmo sem envio; assim a amostra por ciclo é realmente renovada.
        if (automation.sample_mode or "per_cycle") == "per_cycle":
            enrollment.cycle_number += 1
        if automation.max_cycles and enrollment.cycle_number >= automation.max_cycles:
            enrollment.status = "completed"
            enrollment.next_due_at = None
        elif automation.recurrence_days:
            enrollment.status = "active"
            enrollment.next_due_at = due_at + timedelta(days=max(1, automation.recurrence_days))
        else:
            enrollment.status = "completed"
            enrollment.next_due_at = None
        enrollment.blocked_reason = "Fora da amostra deste ciclo."
        return False, "outside_sample"

    selected = _choose_questionnaire(automation, pool, lead.id, cycle, enrollment)
    if not selected:
        enrollment.status = "blocked"
        enrollment.blocked_reason = "Nenhum questionário publicado disponível."
        return False, "no_questionnaire"
    questionnaire, version = selected
    reason, retry_at = _lead_block_reason(db, automation, lead, questionnaire)

    # No rodízio sem repetição, tenta outra pesquisa antes de bloquear por repetição.
    if reason == "already_received" and len(pool) > 1:
        for candidate, candidate_version in pool:
            if candidate.id == questionnaire.id:
                continue
            alt_reason, alt_retry = _lead_block_reason(db, automation, lead, candidate)
            if not alt_reason:
                questionnaire, version, reason, retry_at = candidate, candidate_version, None, None
                break

    if reason:
        enrollment.blocked_reason = {
            "without_consent": "Sem consentimento ativo.",
            "without_whatsapp": "Sem identidade WhatsApp válida.",
            "unconfirmed": "WhatsApp ainda não confirmado.",
            "active_execution": "Já existe outra pesquisa pendente ou em andamento.",
            "already_received": "A política impede repetir esta pesquisa.",
            "cooldown": "Ainda está no intervalo mínimo entre pesquisas.",
        }.get(reason, reason)
        if retry_at:
            enrollment.status = "active"
            enrollment.next_due_at = retry_at
        else:
            enrollment.status = "completed" if reason == "already_received" else "blocked"
            enrollment.next_due_at = None
        return False, reason

    scheduled_at = _windowed_time(automation, max(due_at, utcnow()), lead.id, cycle)
    key = f"segment-auto:{automation.id}:{lead.id}:{cycle}:{questionnaire.id}"
    existing = db.scalar(select(SurveyExecution).where(SurveyExecution.idempotency_key == key).limit(1))
    if not existing:
        create_execution(
            db,
            questionnaire,
            lead=lead,
            channel="whatsapp",
            source=f"segment_automation:{automation.id}",
            scheduled_at=scheduled_at,
            idempotency_key=key,
            context={
                "segment_automation_id": automation.id,
                "segment_enrollment_id": enrollment.id,
                "segment_id": automation.segment_id,
                "cycle": cycle,
                "selection_strategy": automation.selection_strategy,
            },
            questionnaire_version=version,
        )
    _record_enrollment_schedule(enrollment, questionnaire.id, scheduled_at, automation)
    return True, None


def run_segment_automation(db: Session, automation: SegmentAutomation) -> dict[str, int]:
    """Executa um lote por calendário; automações por entrada usam inscrições individuais."""
    segment = db.get(Segment, automation.segment_id)
    if segment:
        refresh_rule_segment(db, segment)
    pool = _questionnaire_pool(db, automation)
    if not pool:
        automation.status = "error"
        return {"eligible": 0, "created": 0}

    links = db.scalars(
        select(LeadSegment).where(LeadSegment.segment_id == automation.segment_id).order_by(LeadSegment.lead_id)
    ).all()
    stats = _base_stats(len(links))
    created = 0
    batch_due = automation.next_run_at or automation.scheduled_at or utcnow()
    for link in links:
        lead = db.get(Lead, link.lead_id)
        if not lead or lead.source == "laboratory":
            continue
        enrollment = _get_or_create_enrollment(db, automation, lead, link.created_at, schedule_entry=False)
        ok, reason = _schedule_for_enrollment(db, automation, enrollment, pool, batch_due)
        if ok:
            created += 1
            stats["eligible"] += 1
        elif reason in stats:
            stats[reason] += 1

    automation.last_run_at = utcnow()
    automation.last_audience_count = stats["segment"]
    automation.last_created_count = created
    if automation.schedule_type == "recurring" and automation.recurrence_days and automation.trigger_type == "campaign":
        next_run = batch_due + timedelta(days=max(1, automation.recurrence_days))
        while next_run <= utcnow():
            next_run += timedelta(days=max(1, automation.recurrence_days))
        automation.next_run_at = next_run
    elif automation.trigger_type == "campaign":
        automation.next_run_at = None
        automation.status = "completed"
    return {"eligible": stats["eligible"], "created": created, **stats}


def process_segment_automations(db: Session) -> dict[str, int]:
    now = utcnow()
    campaign_rows = db.scalars(
        select(SegmentAutomation).where(
            SegmentAutomation.status == "active",
            SegmentAutomation.trigger_type == "campaign",
            SegmentAutomation.next_run_at.is_not(None),
            SegmentAutomation.next_run_at <= now,
        ).order_by(SegmentAutomation.next_run_at, SegmentAutomation.id).limit(20)
    ).all()
    created = 0
    for row in campaign_rows:
        created += run_segment_automation(db, row)["created"]

    entry_rows = db.scalars(
        select(SegmentAutomation).where(
            SegmentAutomation.status == "active",
            SegmentAutomation.trigger_type.in_(["on_entry", "hybrid"]),
        ).order_by(SegmentAutomation.id).limit(100)
    ).all()
    enrolled = cancelled = 0
    for row in entry_rows:
        result = sync_segment_enrollments(db, row)
        enrolled += result["enrolled"]
        cancelled += result["cancelled"]

    due_enrollments = db.scalars(
        select(SegmentAutomationEnrollment)
        .join(SegmentAutomation, SegmentAutomation.id == SegmentAutomationEnrollment.automation_id)
        .where(
            SegmentAutomation.status == "active",
            SegmentAutomation.trigger_type.in_(["on_entry", "hybrid"]),
            SegmentAutomationEnrollment.status == "active",
            SegmentAutomationEnrollment.next_due_at.is_not(None),
            SegmentAutomationEnrollment.next_due_at <= now,
        )
        .order_by(SegmentAutomationEnrollment.next_due_at, SegmentAutomationEnrollment.id)
        .limit(100)
    ).all()
    processed = 0
    for enrollment in due_enrollments:
        automation = db.get(SegmentAutomation, enrollment.automation_id)
        if not automation:
            continue
        pool = _questionnaire_pool(db, automation)
        if not pool:
            automation.status = "error"
            continue
        ok, _ = _schedule_for_enrollment(db, automation, enrollment, pool, enrollment.next_due_at or now)
        if ok:
            processed += 1
            created += 1
            automation.last_run_at = now
            automation.last_created_count = (automation.last_created_count or 0) + 1

    return {
        "segment_automations": len(campaign_rows) + len(entry_rows),
        "segment_executions": created,
        "segment_enrollments": enrolled,
        "segment_enrollment_cancellations": cancelled,
        "segment_enrollments_processed": processed,
    }
