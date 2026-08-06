from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..database import get_db
from ..models import (
    Alert,
    AuditLog,
    City,
    Conversation,
    ConversationDraft,
    ConversationMessage,
    ConversationNote,
    ConversationReaction,
    CollectionPet,
    CollectionSession,
    Device,
    EntryFlow,
    EntryFlowAction,
    Lead,
    LeadSegment,
    MediaAsset,
    MessageQueue,
    Pet,
    Question,
    Questionnaire,
    QuestionnaireVersion,
    QuestionnaireVersionQuestion,
    Segment,
    SegmentAutomation,
    SegmentAutomationEnrollment,
    SegmentAutomationQuestionnaire,
    SegmentEvent,
    SegmentRule,
    SurveyAnswer,
    SurveyExecution,
    SystemSetting,
    TranscriptionConfig,
    TranscriptionJob,
    User,
    WebhookEvent,
    WorkerState,
    ZapiConfig,
    utcnow,
)
from ..services.engine import (
    add_conversation_message,
    advance_to_visible_question,
    active_questions,
    anonymous_aggregate,
    channels,
    create_execution,
    dashboard_metrics,
    display_options,
    ensure_conversation,
    eligible_leads,
    launch_questionnaire,
    options,
    QUESTION_CONDITION_OPERATORS,
    QUESTION_NUMERIC_CONDITION_OPERATORS,
    question_prompt,
    record_answer,
    render_message,
    schedule_for_new_lead,
)
from ..services.editor_reliability import add_submission_claim, completed_submission, error, new_editor_key, new_submission_token, persisted_submission, remember_submission, stable_editor_key
from ..services.security import hash_password, normalize_phone, verify_password
from ..services.branding import remove_logo, save_logo
from ..services.cache import redis_status
from ..services.collection import json_list
from ..services.timezone import BRAZIL_TIMEZONES, DEFAULT_TIMEZONE, local_datetime, valid_timezone
from ..services.media import local_media_path
from ..services.media import store_outbound_media
from ..services.worker import process_once
from ..services.segmentation import attach_segment, detach_segment, refresh_rule_segment
from ..services.segment_automation import automation_candidates, run_segment_automation, sync_segment_enrollments
from ..services.transcription import transcription_diagnostics
from ..services.scheduling import cancel_execution, create_whatsapp_test_execution, release_execution_now, reschedule_execution, retry_failed_delivery
from ..services.versioning import (
    execution_config,
    execution_questions,
    latest_published_version,
    publish_questionnaire_version,
    version_config,
    version_impact,
)
from ..services.conversations import authorized_conversations, quiet_window, status_label
from ..services.zapi import (
    configure_remote_webhooks,
    get_chats,
    get_contact_metadata,
    get_contacts,
    get_qr_code_image,
    is_public_https_origin,
    normalize_manual_send_endpoint,
    normalize_public_base_url,
    run_diagnostics,
    send_endpoint_preview,
    send_reaction,
    webhook_urls_from_base,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def flash(request: Request, message: str, category: str = "success") -> None:
    items = request.session.setdefault("flashes", [])
    items.append({"message": message, "category": category})
    request.session["flashes"] = items[-5:]


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, int(user_id)) if user_id else None


def require_user(request: Request, db: Session, roles: set[str] | None = None) -> User:
    user = current_user(request, db)
    if not user or not user.active:
        raise HTTPException(401)
    if roles and user.role not in roles:
        raise HTTPException(403, "Seu perfil não possui acesso a esta função.")
    return user


def ctx(request: Request, db: Session, **extra):
    setting = db.get(SystemSetting, 1)
    data = {
        "request": request,
        "user": current_user(request, db),
        "system": setting,
        "flashes": request.session.pop("flashes", []),
        "path": request.url.path,
        "timezone_options": BRAZIL_TIMEZONES,
    }
    data.update(extra)
    return data


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _hex_color(value, fallback: str) -> str:
    value = str(value or "").strip()
    return value.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def _bool(form, key: str) -> bool:
    return str(form.get(key, "")).lower() in {"1", "on", "true", "yes", "sim"}


def _user_city_ids(user: User | None) -> list[int] | None:
    if not user or user.role == "admin" or user.all_cities:
        return None
    try:
        return [int(value) for value in json.loads(user.city_ids_json or "[]")]
    except (TypeError, ValueError):
        return []


def _require_city_access(user: User, city_id: int | None) -> None:
    allowed = _user_city_ids(user)
    if allowed is not None and city_id not in allowed:
        raise HTTPException(403, "Seu acesso não inclui a cidade deste cadastro.")


def _cities_for_user(db: Session, user: User, *, active_only: bool = True) -> list[City]:
    query = select(City)
    if active_only:
        query = query.where(City.active.is_(True))
    allowed = _user_city_ids(user)
    if allowed is not None:
        query = query.where(City.id.in_(allowed))
    return db.scalars(query.order_by(City.name)).all()


def _execution_access(user: User, execution: SurveyExecution) -> None:
    if execution.is_test:
        return
    if execution.lead:
        _require_city_access(user, execution.lead.city_id)
    elif user.role != "admin":
        raise HTTPException(403, "Esta execução não possui cidade identificada.")


def _schedule_timezone(db: Session, user: User) -> str:
    system = db.get(SystemSetting, 1)
    return valid_timezone(user.timezone_name or (system.timezone_name if system else DEFAULT_TIMEZONE))


def _local_input_utc(value: str, timezone_name: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
        return parsed.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _local_day_bounds(value: str, timezone_name: str) -> tuple[datetime, datetime] | None:
    try:
        day = datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None
    start_local = datetime.combine(day, datetime.min.time(), ZoneInfo(timezone_name))
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _schedule_return(request: Request) -> str:
    destination = str(request.query_params.get("next") or "/agendamentos")
    return destination if destination.startswith("/agendamentos") else "/agendamentos"


def _audit_schedule(db: Session, user: User, execution: SurveyExecution, action: str, details: dict) -> None:
    db.add(AuditLog(
        user_id=user.id,
        action=action,
        entity="survey_execution",
        entity_id=execution.id,
        details=json.dumps(details, ensure_ascii=False, default=str),
    ))


def _request_public_origin(request: Request) -> str | None:
    """Resolve the public application origin, including common reverse-proxy headers."""
    forwarded_proto = request.headers.get("x-forwarded-proto")
    proto = (forwarded_proto or request.url.scheme).split(",", 1)[0].strip().lower()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    ).split(",", 1)[0].strip()

    forwarded = request.headers.get("forwarded") or ""
    forwarded_has_proto = False
    if forwarded:
        first = forwarded.split(",", 1)[0]
        values: dict[str, str] = {}
        for item in first.split(";"):
            key, _, value = item.strip().partition("=")
            if key and value:
                values[key.lower()] = value.strip().strip('"')
        forwarded_has_proto = "proto" in values
        proto = values.get("proto", proto).lower()
        host = values.get("host", host)

    # Cloudflare normally sends X-Forwarded-Proto, but CF-Visitor is a useful fallback.
    if not forwarded_proto and not forwarded_has_proto:
        try:
            visitor = json.loads(request.headers.get("cf-visitor") or "{}")
            if visitor.get("scheme"):
                proto = str(visitor["scheme"]).lower()
        except (TypeError, ValueError):
            pass

    if proto not in {"http", "https"} or not host:
        return None
    normalized, error = normalize_public_base_url(f"{proto}://{host}")
    return None if error else normalized


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return redirect("/")
    return request.app.state.templates.TemplateResponse(request, "login.html", ctx(request, db, next=request.query_params.get("next", "/")))


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username.strip()))
    if not user or not user.active or not verify_password(password, user.password_hash):
        flash(request, "Usuário ou senha inválidos.", "danger")
        return redirect("/login")
    request.session["user_id"] = user.id
    user.last_login_at = utcnow()
    db.commit()
    return redirect(next if next.startswith("/") else "/")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    city_ids = _user_city_ids(user)
    if city_ids is None:
        metrics = dashboard_metrics(db)
        execution_query = select(SurveyExecution).where(SurveyExecution.is_test.is_(False))
        alert_query = select(Alert).where(Alert.status == "open")
        segment_query = select(Segment, func.count(LeadSegment.id)).outerjoin(LeadSegment)
    else:
        metrics = {
            "leads": db.scalar(select(func.count(Lead.id)).where(Lead.city_id.in_(city_ids), Lead.source != "laboratory")) or 0,
            "questionnaires": db.scalar(select(func.count(Questionnaire.id)).where(Questionnaire.status == "active")) or 0,
            "pending": db.scalar(select(func.count(SurveyExecution.id)).join(Lead).where(Lead.city_id.in_(city_ids), SurveyExecution.status.in_(["scheduled", "active"]), SurveyExecution.is_test.is_(False))) or 0,
            "alerts": db.scalar(select(func.count(Alert.id)).join(Lead).where(Lead.city_id.in_(city_ids), Alert.status == "open")) or 0,
            "response_rate": 0.0,
        }
        scoped_total = db.scalar(select(func.count(SurveyExecution.id)).join(Lead).where(Lead.city_id.in_(city_ids), SurveyExecution.status.in_(["active", "completed", "abandoned"]), SurveyExecution.is_test.is_(False))) or 0
        scoped_completed = db.scalar(select(func.count(SurveyExecution.id)).join(Lead).where(Lead.city_id.in_(city_ids), SurveyExecution.status == "completed", SurveyExecution.is_test.is_(False))) or 0
        metrics["response_rate"] = round(scoped_completed / scoped_total * 100, 1) if scoped_total else 0.0
        execution_query = select(SurveyExecution).join(Lead).where(Lead.city_id.in_(city_ids), SurveyExecution.is_test.is_(False))
        alert_query = select(Alert).join(Lead).where(Lead.city_id.in_(city_ids), Alert.status == "open")
        segment_query = (
            select(Segment, func.count(LeadSegment.id))
            .outerjoin(LeadSegment)
            .outerjoin(Lead, Lead.id == LeadSegment.lead_id)
            .where(or_(Lead.city_id.in_(city_ids), Lead.id.is_(None)))
        )
    recent_executions = db.scalars(
        execution_query.options(selectinload(SurveyExecution.lead), selectinload(SurveyExecution.questionnaire))
        .order_by(SurveyExecution.created_at.desc()).limit(8)
    ).all()
    recent_alerts = db.scalars(
        alert_query.options(selectinload(Alert.lead), selectinload(Alert.questionnaire))
        .order_by(Alert.created_at.desc()).limit(6)
    ).all()
    segments = db.execute(
        segment_query.group_by(Segment.id).order_by(func.count(LeadSegment.id).desc()).limit(6)
    ).all()
    worker_state = db.get(WorkerState, 1)
    worker_online = bool(
        worker_state
        and worker_state.status == "running"
        and worker_state.heartbeat_at
        and worker_state.heartbeat_at >= utcnow() - timedelta(seconds=max(20, settings.worker_poll_seconds * 5))
    )
    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        ctx(
            request,
            db,
            metrics=metrics,
            recent_executions=recent_executions,
            recent_alerts=recent_alerts,
            segments=segments,
            worker_state=worker_state,
            worker_online=worker_online,
        ),
    )


@router.get("/agendamentos")
def schedules_center(
    request: Request,
    q: str = "",
    status: str = "",
    origin: str = "",
    questionnaire_id: int = 0,
    segment_id: int = 0,
    channel: str = "",
    scope: str = "production",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
):
    user = require_user(request, db, {"admin", "operator"})
    timezone_name = _schedule_timezone(db, user)
    city_ids = _user_city_ids(user)
    now = utcnow()
    now_local = local_datetime(now, timezone_name)

    if origin == "test" and scope == "production":
        scope = "tests"
    scope_criteria = []
    if city_ids is not None:
        city_scope = SurveyExecution.lead_id.in_(select(Lead.id).where(Lead.city_id.in_(city_ids)))
        # Testes são isolados da produção e seguem a mesma permissão das telas
        # de laboratório: operadores podem acompanhar o teste que acabaram de criar.
        scope_criteria.append(or_(SurveyExecution.is_test.is_(True), city_scope))
    if scope == "tests":
        scope_criteria.append(SurveyExecution.is_test.is_(True))
    elif scope != "all":
        scope = "production"
        scope_criteria.append(SurveyExecution.is_test.is_(False))

    criteria = list(scope_criteria)
    term = q.strip()
    if term:
        like = f"%{term}%"
        criteria.append(or_(
            SurveyExecution.lead.has(or_(Lead.name.ilike(like), Lead.phone.ilike(like), Lead.phone_normalized.ilike(like))),
            SurveyExecution.questionnaire.has(Questionnaire.name.ilike(like)),
        ))
    if questionnaire_id:
        criteria.append(SurveyExecution.questionnaire_id == questionnaire_id)
    if channel in {"whatsapp", "interviewer", "kiosk"}:
        criteria.append(SurveyExecution.channel == channel)
    if segment_id:
        automation_ids = db.scalars(select(SegmentAutomation.id).where(SegmentAutomation.segment_id == segment_id)).all()
        criteria.append(SurveyExecution.source.in_([f"segment_automation:{item}" for item in automation_ids] or ["segment_automation:none"]))
    if origin == "flow":
        criteria.append(or_(SurveyExecution.flow_action_id.is_not(None), SurveyExecution.collection_session_id.is_not(None)))
    elif origin == "campaign":
        criteria.append(SurveyExecution.source.like("segment_automation:%"))
    elif origin == "manual":
        criteria.append(SurveyExecution.source.in_(["lead_detail", "manual", "questionnaire_launch", "interviewer", "kiosk", "kiosk_anonymous"]))
    elif origin == "automatic":
        criteria.append(SurveyExecution.source.in_(["registration", "recurrence", "unknown_whatsapp"]))
    elif origin == "test":
        criteria.append(SurveyExecution.is_test.is_(True))

    failed_ids = select(MessageQueue.execution_id).where(
        MessageQueue.execution_id.is_not(None), MessageQueue.status == "failed"
    )
    if status == "pending":
        criteria.append(SurveyExecution.status == "scheduled")
    elif status == "active":
        criteria.append(SurveyExecution.status == "active")
    elif status == "completed":
        criteria.append(SurveyExecution.status == "completed")
    elif status == "cancelled":
        criteria.append(SurveyExecution.status == "cancelled")
    elif status == "attention":
        criteria.append(or_(SurveyExecution.status.in_(["blocked", "abandoned"]), SurveyExecution.id.in_(failed_ids)))

    from_bounds = _local_day_bounds(date_from, timezone_name) if date_from else None
    to_bounds = _local_day_bounds(date_to, timezone_name) if date_to else None
    if from_bounds:
        criteria.append(SurveyExecution.scheduled_at >= from_bounds[0])
    if to_bounds:
        criteria.append(SurveyExecution.scheduled_at < to_bounds[1])

    total = db.scalar(select(func.count(SurveyExecution.id)).where(*criteria)) or 0
    page = max(1, page)
    page_size = 50
    page_count = max(1, (total + page_size - 1) // page_size)
    page = min(page, page_count)
    executions = db.scalars(
        select(SurveyExecution)
        .options(
            selectinload(SurveyExecution.lead),
            selectinload(SurveyExecution.pet),
            selectinload(SurveyExecution.questionnaire),
            selectinload(SurveyExecution.questionnaire_version).selectinload(QuestionnaireVersion.questions),
            selectinload(SurveyExecution.flow_action).selectinload(EntryFlowAction.flow),
            selectinload(SurveyExecution.collection_session).selectinload(CollectionSession.flow),
        )
        .where(*criteria)
        .order_by(
            case((SurveyExecution.status == "scheduled", 0), (SurveyExecution.status == "blocked", 1), (SurveyExecution.status == "active", 2), else_=3),
            SurveyExecution.scheduled_at.asc(),
            SurveyExecution.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    execution_ids = [item.id for item in executions]
    queue_by_execution: dict[int, MessageQueue] = {}
    if execution_ids:
        for item in db.scalars(
            select(MessageQueue)
            .where(MessageQueue.execution_id.in_(execution_ids))
            .order_by(MessageQueue.execution_id, MessageQueue.id.desc())
        ).all():
            queue_by_execution.setdefault(item.execution_id, item)

    automation_ids = {
        _int(item.source.split(":", 1)[1], 0)
        for item in executions
        if item.source.startswith("segment_automation:")
    }
    automations = {
        item.id: item
        for item in db.scalars(
            select(SegmentAutomation)
            .options(selectinload(SegmentAutomation.segment), selectinload(SegmentAutomation.questionnaire))
            .where(SegmentAutomation.id.in_(automation_ids or {0}))
        ).all()
    }
    source_labels = {
        "registration": ("Automação", "Cadastro de lead"),
        "recurrence": ("Automação", "Recorrência do questionário"),
        "lead_detail": ("Manual", "Perfil do lead"),
        "manual": ("Manual", "Agendamento manual"),
        "questionnaire_launch": ("Disparo", "Público do questionário"),
        "entry_registration": ("Fluxo", "Cadastro estruturado"),
        "entry_flow_screen": ("Fluxo", "Etapa na tela"),
        "entry_flow_anonymous": ("Fluxo", "Pesquisa anônima na tela"),
        "entry_flow_immediate_whatsapp": ("Fluxo", "Ação imediata no WhatsApp"),
        "entry_flow_confirmed": ("Fluxo", "Após confirmação do WhatsApp"),
        "entry_flow_required_confirmed": ("Fluxo", "Confirmação obrigatória"),
        "entry_flow_followup": ("Fluxo", "Acompanhamento futuro"),
        "interviewer": ("Manual", "Aplicação pelo entrevistador"),
        "kiosk": ("Manual", "Aplicação no totem"),
        "kiosk_anonymous": ("Manual", "Totem anônimo"),
        "unknown_whatsapp": ("Automação", "Entrada pelo WhatsApp"),
        "whatsapp_laboratory": ("Teste", "Laboratório do WhatsApp"),
        "laboratory": ("Teste", "Laboratório na tela"),
    }
    rows = []
    for execution in executions:
        origin_kind, origin_label = source_labels.get(execution.source, ("Automação", execution.source.replace("_", " ").strip().title()))
        origin_url = None
        if execution.flow_action:
            origin_kind = "Fluxo"
            origin_label = f"{execution.flow_action.flow.name} · {execution.flow_action.name}"
            origin_url = f"/fluxos/{execution.flow_action.flow_id}/editar"
        elif execution.collection_session:
            origin_kind = "Fluxo"
            origin_label = execution.collection_session.flow.name
            origin_url = f"/fluxos/{execution.collection_session.flow_id}/editar"
        elif execution.source.startswith("segment_automation:"):
            automation = automations.get(_int(execution.source.split(":", 1)[1], 0))
            origin_kind = "Campanha"
            if automation:
                origin_label = f"{automation.name} · {automation.segment.name}"
                origin_url = f"/segmentos?segment_id={automation.segment_id}&tab=automacoes"
            else:
                origin_label = "Campanha removida"
        latest_queue = queue_by_execution.get(execution.id)
        rows.append(SimpleNamespace(
            execution=execution,
            queue=latest_queue,
            origin_kind=origin_kind,
            origin_label=origin_label,
            origin_url=origin_url,
            question_count=len(execution.questionnaire_version.questions) if execution.questionnaire_version else 0,
            can_reschedule=execution.status in {"scheduled", "blocked"},
            can_cancel=execution.status in {"scheduled", "blocked", "active"},
            can_retry=bool(execution.status == "active" and latest_queue and latest_queue.status == "failed"),
        ))

    today_start = datetime.combine(now_local.date(), datetime.min.time(), ZoneInfo(timezone_name)).astimezone(timezone.utc).replace(tzinfo=None)
    tomorrow_start = (datetime.combine(now_local.date(), datetime.min.time(), ZoneInfo(timezone_name)) + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
    week_end = today_start + timedelta(days=7)
    summary_row = db.execute(select(
        func.count(SurveyExecution.id),
        func.sum(case((SurveyExecution.status == "scheduled", 1), else_=0)),
        func.sum(case(((SurveyExecution.status == "scheduled") & (SurveyExecution.scheduled_at < now), 1), else_=0)),
        func.sum(case(((SurveyExecution.status == "scheduled") & (SurveyExecution.scheduled_at >= today_start) & (SurveyExecution.scheduled_at < tomorrow_start), 1), else_=0)),
        func.sum(case(((SurveyExecution.status == "scheduled") & (SurveyExecution.scheduled_at >= today_start) & (SurveyExecution.scheduled_at < week_end), 1), else_=0)),
        func.sum(case((SurveyExecution.status == "active", 1), else_=0)),
        func.sum(case((or_(SurveyExecution.status.in_(["blocked", "abandoned"]), SurveyExecution.id.in_(failed_ids)), 1), else_=0)),
    ).where(*scope_criteria)).one()
    summary = SimpleNamespace(
        total=summary_row[0] or 0,
        scheduled=summary_row[1] or 0,
        overdue=summary_row[2] or 0,
        today=summary_row[3] or 0,
        week=summary_row[4] or 0,
        active=summary_row[5] or 0,
        attention=summary_row[6] or 0,
    )

    scheduled_dates = db.scalars(select(SurveyExecution.scheduled_at).where(
        *scope_criteria,
        SurveyExecution.status == "scheduled",
        SurveyExecution.scheduled_at >= today_start,
        SurveyExecution.scheduled_at < week_end,
    )).all()
    calendar_counts: dict[str, int] = {}
    for value in scheduled_dates:
        key = local_datetime(value, timezone_name).date().isoformat()
        calendar_counts[key] = calendar_counts.get(key, 0) + 1
    calendar_days = []
    for offset in range(7):
        day = now_local.date() + timedelta(days=offset)
        calendar_days.append(SimpleNamespace(date=day.isoformat(), label=day.strftime("%d/%m"), weekday=("seg", "ter", "qua", "qui", "sex", "sáb", "dom")[day.weekday()], count=calendar_counts.get(day.isoformat(), 0)))

    questionnaire_summary = db.execute(
        select(
            Questionnaire,
            func.count(SurveyExecution.id),
            func.sum(case((SurveyExecution.status == "scheduled", 1), else_=0)),
            func.sum(case((SurveyExecution.status == "active", 1), else_=0)),
            func.sum(case((SurveyExecution.status == "completed", 1), else_=0)),
        )
        .join(SurveyExecution, SurveyExecution.questionnaire_id == Questionnaire.id)
        .where(*scope_criteria)
        .group_by(Questionnaire.id)
        .order_by(func.count(SurveyExecution.id).desc(), Questionnaire.name)
        .limit(12)
    ).all()
    questionnaires = db.scalars(select(Questionnaire).where(Questionnaire.status == "active").order_by(Questionnaire.name)).all()
    whatsapp_questionnaires = []
    for item in questionnaires:
        published = latest_published_version(db, item)
        config = version_config(published) if published else None
        if config and config.response_mode != "anonymous" and "whatsapp" in channels(config):
            whatsapp_questionnaires.append(item)
    segments = db.scalars(select(Segment).where(Segment.active.is_(True)).order_by(Segment.name)).all()
    campaign_query = select(SegmentAutomation).options(selectinload(SegmentAutomation.segment), selectinload(SegmentAutomation.questionnaire))
    if segment_id:
        campaign_query = campaign_query.where(SegmentAutomation.segment_id == segment_id)
    campaigns = db.scalars(campaign_query.order_by(SegmentAutomation.created_at.desc()).limit(20)).all()
    worker_state = db.get(WorkerState, 1)
    worker_online = bool(worker_state and worker_state.status == "running" and worker_state.heartbeat_at and worker_state.heartbeat_at >= now - timedelta(seconds=max(20, settings.worker_poll_seconds * 5)))

    filters = {"q": q, "status": status, "origin": origin, "questionnaire_id": questionnaire_id, "segment_id": segment_id, "channel": channel, "scope": scope, "date_from": date_from, "date_to": date_to}
    return request.app.state.templates.TemplateResponse(
        request,
        "schedules.html",
        ctx(request, db, rows=rows, total=total, page=page, page_count=page_count, summary=summary, calendar_days=calendar_days, questionnaire_summary=questionnaire_summary, questionnaires=questionnaires, whatsapp_questionnaires=whatsapp_questionnaires, segments=segments, campaigns=campaigns, filters=filters, timezone_name=timezone_name, worker_state=worker_state, worker_online=worker_online),
    )


@router.post("/agendamentos/testar")
async def schedules_test_whatsapp(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    form = await request.form()
    questionnaire = db.get(Questionnaire, _int(form.get("questionnaire_id"), 0))
    if not questionnaire:
        flash(request, "Selecione um questionário válido.", "danger")
        return redirect("/agendamentos")
    execution, error_message = create_whatsapp_test_execution(db, questionnaire, str(form.get("phone") or ""))
    if error_message or not execution:
        flash(request, error_message or "Não foi possível criar o teste.", "danger")
        return redirect("/agendamentos")
    db.commit()
    process_once()
    return redirect(f"/questionarios/testes/{execution.id}")


@router.post("/agendamentos/{execution_id}/enviar-agora")
def schedules_send_now(request: Request, execution_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    execution = db.get(SurveyExecution, execution_id)
    if not execution:
        raise HTTPException(404)
    _execution_access(user, execution)
    old_status, old_date = execution.status, execution.scheduled_at
    error_message = release_execution_now(db, execution)
    if error_message:
        flash(request, error_message, "danger")
    else:
        _audit_schedule(db, user, execution, "schedule_send_now", {"old_status": old_status, "old_scheduled_at": old_date})
        db.commit()
        flash(request, "Pesquisa liberada para o próximo ciclo do worker.")
    return redirect(_schedule_return(request))


@router.post("/agendamentos/{execution_id}/reagendar")
async def schedules_reschedule(request: Request, execution_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    execution = db.get(SurveyExecution, execution_id)
    if not execution:
        raise HTTPException(404)
    _execution_access(user, execution)
    form = await request.form()
    scheduled_at = _local_input_utc(str(form.get("scheduled_at") or ""), _schedule_timezone(db, user))
    if not scheduled_at:
        flash(request, "Informe uma data e hora válidas.", "danger")
        return redirect(_schedule_return(request))
    old_status, old_date = execution.status, execution.scheduled_at
    error_message = reschedule_execution(db, execution, scheduled_at)
    if error_message:
        flash(request, error_message, "danger")
    else:
        _audit_schedule(db, user, execution, "schedule_reschedule", {"old_status": old_status, "old_scheduled_at": old_date, "new_scheduled_at": scheduled_at})
        db.commit()
        flash(request, "Pesquisa reagendada.")
    return redirect(_schedule_return(request))


@router.post("/agendamentos/{execution_id}/cancelar")
async def schedules_cancel(request: Request, execution_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    execution = db.get(SurveyExecution, execution_id)
    if not execution:
        raise HTTPException(404)
    _execution_access(user, execution)
    form = await request.form()
    reason = str(form.get("reason") or "").strip()
    if len(reason) < 3:
        flash(request, "Informe o motivo do cancelamento.", "danger")
        return redirect(_schedule_return(request))
    old_status = execution.status
    error_message = cancel_execution(db, execution)
    if error_message:
        flash(request, error_message, "danger")
    else:
        _audit_schedule(db, user, execution, "schedule_cancel", {"old_status": old_status, "reason": reason})
        db.commit()
        flash(request, "Execução cancelada e mensagens pendentes interrompidas.")
    return redirect(_schedule_return(request))


@router.post("/agendamentos/{execution_id}/repetir-falha")
def schedules_retry(request: Request, execution_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    execution = db.get(SurveyExecution, execution_id)
    if not execution:
        raise HTTPException(404)
    _execution_access(user, execution)
    error_message = retry_failed_delivery(db, execution)
    if error_message:
        flash(request, error_message, "danger")
    else:
        _audit_schedule(db, user, execution, "schedule_retry_failed_message", {})
        db.commit()
        flash(request, "Mensagem devolvida à fila para nova tentativa.")
    return redirect(_schedule_return(request))


@router.get("/leads")
def leads(request: Request, q: str = "", segment_id: int | None = None, db: Session = Depends(get_db)):
    user = require_user(request, db)
    query = select(Lead).options(selectinload(Lead.pets), selectinload(Lead.segment_links).selectinload(LeadSegment.segment)).where(Lead.source != "laboratory")
    city_ids = _user_city_ids(user)
    if city_ids is not None:
        query = query.where(Lead.city_id.in_(city_ids))
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Lead.name.ilike(term), Lead.phone.ilike(term), Lead.city.ilike(term), Lead.neighborhood.ilike(term)))
    if segment_id:
        query = query.join(LeadSegment).where(LeadSegment.segment_id == segment_id)
    rows = db.scalars(query.order_by(Lead.created_at.desc())).unique().all()
    segments = db.scalars(select(Segment).where(Segment.active.is_(True)).order_by(Segment.name)).all()
    return request.app.state.templates.TemplateResponse(request, "leads.html", ctx(request, db, leads=rows, segments=segments, q=q, segment_id=segment_id))


@router.get("/leads/novo")
def lead_new(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    cities = _cities_for_user(db, user)
    return request.app.state.templates.TemplateResponse(request, "lead_form.html", ctx(request, db, lead=None, cities=cities, form_action="/leads/novo"))


@router.post("/leads/novo")
async def lead_create(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    setting = db.get(SystemSetting, 1)
    normalized = normalize_phone(form.get("phone"), setting.default_country_code)
    if normalized and db.scalar(select(Lead).where(Lead.phone_normalized == normalized)):
        flash(request, "Já existe um lead com esse WhatsApp.", "warning")
        return redirect("/leads")
    city_id = _int(form.get("city_id"), 0) or None
    _require_city_access(user, city_id)
    city = db.get(City, city_id) if city_id else None
    lead = Lead(
        name=str(form.get("name") or "").strip(),
        phone=str(form.get("phone") or "").strip() or None,
        phone_normalized=normalized,
        city_id=city_id,
        city=city.name if city else None,
        neighborhood=str(form.get("neighborhood") or "").strip() or None,
        source="manual",
        consent_research=_bool(form, "consent_research"),
        consent_marketing=_bool(form, "consent_marketing"),
        notes=str(form.get("notes") or "").strip() or None,
    )
    if not lead.name:
        flash(request, "Informe o nome.", "danger")
        return redirect("/leads/novo")
    pet_name = str(form.get("pet_name") or "").strip()
    if pet_name:
        lead.pets.append(Pet(name=pet_name, species=str(form.get("pet_species") or "").strip() or None, breed=str(form.get("pet_breed") or "").strip() or None))
    db.add(lead)
    db.flush()
    schedule_for_new_lead(db, lead)
    db.commit()
    flash(request, "Lead cadastrado e automações de cadastro avaliadas.")
    return redirect(f"/leads/{lead.id}")


@router.get("/leads/{lead_id}/editar")
def lead_edit(request: Request, lead_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    lead = db.scalar(select(Lead).options(selectinload(Lead.pets)).where(Lead.id == lead_id))
    if not lead:
        raise HTTPException(404)
    _require_city_access(user, lead.city_id)
    cities = _cities_for_user(db, user)
    return request.app.state.templates.TemplateResponse(request, "lead_form.html", ctx(request, db, lead=lead, cities=cities, form_action=f"/leads/{lead.id}/editar"))


@router.post("/leads/{lead_id}/editar")
async def lead_update(request: Request, lead_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    lead = db.scalar(select(Lead).options(selectinload(Lead.pets)).where(Lead.id == lead_id))
    if not lead:
        raise HTTPException(404)
    _require_city_access(user, lead.city_id)
    form = await request.form()
    setting = db.get(SystemSetting, 1)
    normalized = normalize_phone(form.get("phone"), setting.default_country_code)
    duplicate = db.scalar(select(Lead).where(Lead.phone_normalized == normalized, Lead.id != lead.id)) if normalized else None
    if duplicate:
        flash(request, "Este WhatsApp já pertence a outro lead.", "danger")
        return redirect(f"/leads/{lead.id}/editar")
    had_phone = bool(lead.phone_normalized)
    had_consent = lead.consent_research
    lead.name = str(form.get("name") or lead.name).strip()
    lead.phone = str(form.get("phone") or "").strip() or None
    lead.phone_normalized = normalized
    lead.city_id = _int(form.get("city_id"), 0) or None
    _require_city_access(user, lead.city_id)
    city = db.get(City, lead.city_id) if lead.city_id else None
    lead.city = city.name if city else str(form.get("city") or "").strip() or None
    lead.neighborhood = str(form.get("neighborhood") or "").strip() or None
    lead.consent_research = _bool(form, "consent_research")
    lead.consent_marketing = _bool(form, "consent_marketing")
    lead.notes = str(form.get("notes") or "").strip() or None
    pet_name = str(form.get("pet_name") or "").strip()
    pet = lead.pets[0] if lead.pets else None
    if pet_name and not pet:
        pet = Pet(lead_id=lead.id, name=pet_name)
        db.add(pet)
    if pet:
        pet.name = pet_name or pet.name
        pet.species = str(form.get("pet_species") or "").strip() or None
        pet.breed = str(form.get("pet_breed") or "").strip() or None
    if (not had_phone and lead.phone_normalized) or (not had_consent and lead.consent_research):
        schedule_for_new_lead(db, lead)
    db.commit()
    flash(request, "Lead atualizado.")
    return redirect(f"/leads/{lead.id}")


@router.get("/leads/importar-whatsapp")
def leads_import_whatsapp(
    request: Request,
    source: str = "contacts",
    page: int = 1,
    db: Session = Depends(get_db),
):
    user = require_user(request, db, {"admin", "operator"})
    config = db.get(ZapiConfig, 1)
    system = db.get(SystemSetting, 1)
    source = source if source in {"contacts", "chats", "recent"} else "contacts"
    result = get_chats(config, page=page, page_size=100) if source in {"chats", "recent"} else get_contacts(config, page=page, page_size=100)
    candidates = []
    for item in (result.payload or {}).get("items", []):
        if not isinstance(item, dict) or item.get("isGroup") or item.get("isNewsletter"):
            continue
        if source == "recent":
            try:
                timestamp = float(item.get("lastMessageTime") or 0)
                if timestamp > 10_000_000_000:
                    timestamp /= 1000
                if not timestamp or datetime.fromtimestamp(timestamp, tz=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=30):
                    continue
            except (TypeError, ValueError, OSError):
                continue
        phone = normalize_phone(item.get("phone"), system.default_country_code)
        if not phone:
            continue
        name = str(
            item.get("name") or item.get("notify") or item.get("short") or item.get("vname") or "Contato do WhatsApp"
        ).strip()
        existing = db.scalar(select(Lead.id).where(Lead.phone_normalized == phone))
        candidates.append({
            "phone": phone,
            "name": name[:160],
            "source": source,
            "existing": bool(existing),
            "last_message_time": item.get("lastMessageTime"),
            "photo": item.get("imgUrl") or item.get("photo"),
            "about": item.get("about"),
        })
    return request.app.state.templates.TemplateResponse(
        request,
        "lead_import_whatsapp.html",
        ctx(
            request,
            db,
            candidates=candidates,
            source=source,
            page=max(1, page),
            integration_result=result,
            cities=_cities_for_user(db, user),
        ),
    )


@router.post("/leads/importar-whatsapp")
async def leads_import_whatsapp_save(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    form = await request.form()
    system = db.get(SystemSetting, 1)
    imported = 0
    updated = 0
    city_id = _int(form.get("city_id"), 0) or None
    _require_city_access(user, city_id)
    city = db.get(City, city_id) if city_id else None
    for raw in form.getlist("candidate")[:500]:
        try:
            item = json.loads(str(raw))
        except (TypeError, ValueError):
            continue
        phone = normalize_phone(item.get("phone"), system.default_country_code)
        if not phone:
            continue
        lead = db.scalar(select(Lead).where(Lead.phone_normalized == phone))
        name = str(item.get("name") or "Contato do WhatsApp").strip()[:160]
        if lead:
            if name and (lead.name == "Novo contato" or not lead.whatsapp_display_name):
                lead.whatsapp_display_name = name
            if item.get("photo"):
                lead.whatsapp_profile_photo_url = str(item["photo"]).strip() or lead.whatsapp_profile_photo_url
            if item.get("about"):
                lead.whatsapp_about = str(item["about"]).strip() or lead.whatsapp_about
            lead.whatsapp_identity_updated_at = utcnow()
            lead.whatsapp_identity_source = "import"
            updated += 1
        else:
            lead = Lead(
                name=name,
                phone=phone,
                phone_normalized=phone,
                source="whatsapp_import",
                city_id=city_id,
                city=city.name if city else None,
                status="onboarding",
                consent_research=False,
                consent_marketing=False,
                whatsapp_display_name=name,
                whatsapp_profile_photo_url=str(item.get("photo") or "").strip() or None,
                whatsapp_about=str(item.get("about") or "").strip() or None,
                whatsapp_identity_updated_at=utcnow(),
                whatsapp_identity_source="import",
            )
            db.add(lead)
            db.flush()
            imported += 1
        if item.get("source") == "chats":
            ensure_conversation(db, phone, lead)
    db.commit()
    flash(request, f"Importação concluída: {imported} novo(s) lead(s) e {updated} cadastro(s) conciliado(s).")
    return redirect("/leads")


@router.post("/leads/{lead_id}/sincronizar-whatsapp")
def lead_sync_whatsapp(request: Request, lead_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404)
    _require_city_access(user, lead.city_id)
    if not lead.phone_normalized:
        flash(request, "Este lead não possui telefone para consulta.", "danger")
        return redirect(f"/leads/{lead.id}")
    result = get_contact_metadata(db.get(ZapiConfig, 1), lead.phone_normalized)
    if not result.ok:
        flash(request, result.message, "danger")
        return redirect(f"/leads/{lead.id}")
    payload = result.payload or {}
    lead.whatsapp_display_name = str(payload.get("notify") or payload.get("name") or lead.whatsapp_display_name or "").strip() or None
    lead.whatsapp_chat_name = str(payload.get("short") or lead.whatsapp_chat_name or "").strip() or None
    lead.whatsapp_profile_photo_url = str(payload.get("imgUrl") or lead.whatsapp_profile_photo_url or "").strip() or None
    lead.whatsapp_about = str(payload.get("about") or "").strip() or None
    lead.whatsapp_identity_updated_at = utcnow()
    lead.whatsapp_identity_source = "metadata"
    db.commit()
    flash(request, "Nome, foto e recado do perfil foram sincronizados.")
    return redirect(f"/leads/{lead.id}")


@router.get("/leads/{lead_id}")
def lead_detail(request: Request, lead_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    lead = db.scalar(select(Lead).options(selectinload(Lead.pets), selectinload(Lead.segment_links).selectinload(LeadSegment.segment)).where(Lead.id == lead_id))
    if not lead:
        raise HTTPException(404)
    _require_city_access(user, lead.city_id)
    executions = db.scalars(
        select(SurveyExecution)
        .options(
            selectinload(SurveyExecution.questionnaire_version).selectinload(QuestionnaireVersion.questions),
            selectinload(SurveyExecution.answers).selectinload(SurveyAnswer.version_question),
        )
        .where(SurveyExecution.lead_id == lead.id, SurveyExecution.is_test.is_(False))
        .order_by(SurveyExecution.created_at.desc())
    ).all()
    execution_details = {}
    for execution in executions:
        answers = {answer.version_question_id: answer for answer in execution.answers}
        questions = execution_questions(execution)
        execution_details[execution.id] = [
            {"question": question, "answer": answers.get(question.id)}
            for question in questions
        ]
    segments = db.scalars(select(Segment).where(Segment.active.is_(True)).order_by(Segment.name)).all()
    questionnaires = db.scalars(select(Questionnaire).where(Questionnaire.status == "active").order_by(Questionnaire.name)).all()
    collections = db.scalars(
        select(CollectionSession)
        .options(
            selectinload(CollectionSession.flow),
            selectinload(CollectionSession.verification),
            selectinload(CollectionSession.pets).selectinload(CollectionPet.pet),
        )
        .where(CollectionSession.lead_id == lead.id, CollectionSession.is_test.is_(False))
        .order_by(CollectionSession.created_at.desc())
    ).all()
    return request.app.state.templates.TemplateResponse(request, "lead_detail.html", ctx(request, db, lead=lead, executions=executions, execution_details=execution_details, segments=segments, questionnaires=questionnaires, collections=collections))


@router.post("/leads/{lead_id}/segmentos")
def lead_add_segment(request: Request, lead_id: int, segment_id: int = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404)
    _require_city_access(user, lead.city_id)
    attach_segment(db, lead_id, segment_id, origin="manual", confidence=1.0, reason="Adicionado manualmente.")
    db.commit()
    return redirect(f"/leads/{lead_id}")


@router.post("/leads/{lead_id}/segmentos/{segment_id}/remover")
def lead_remove_segment(request: Request, lead_id: int, segment_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404)
    _require_city_access(user, lead.city_id)
    detach_segment(db, lead_id, segment_id, origin="manual", reason="Removido manualmente.")
    db.commit()
    return redirect(f"/leads/{lead_id}")


@router.post("/leads/{lead_id}/questionarios")
def lead_schedule_questionnaire(request: Request, lead_id: int, questionnaire_id: int = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    lead = db.get(Lead, lead_id)
    questionnaire = db.get(Questionnaire, questionnaire_id)
    if not lead or not questionnaire:
        raise HTTPException(404)
    _require_city_access(user, lead.city_id)
    if not (lead.phone_normalized or lead.whatsapp_lid):
        flash(request, "O lead não possui identidade WhatsApp válida.", "danger")
    elif not lead.consent_research or lead.opted_out_at or lead.status != "active":
        flash(request, "O lead ainda não possui consentimento ativo para pesquisas.", "danger")
    elif not latest_published_version(db, questionnaire) or "whatsapp" not in channels(version_config(latest_published_version(db, questionnaire))):
        flash(request, "Este questionário não está habilitado para WhatsApp.", "danger")
    else:
        create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="lead_detail", scheduled_at=utcnow())
        db.commit()
        flash(request, "Questionário agendado para envio.")
    return redirect(f"/leads/{lead_id}")


@router.get("/questionarios")
def questionnaires(request: Request, arquivados: bool = False, db: Session = Depends(get_db)):
    require_user(request, db)
    questionnaire_filter = Questionnaire.status == "archived" if arquivados else Questionnaire.status != "archived"
    flow_filter = EntryFlow.status == "archived" if arquivados else EntryFlow.status != "archived"
    rows = db.execute(
        select(
            Questionnaire,
            func.sum(case((SurveyExecution.is_test.is_(False), 1), else_=0)).label("executions"),
            func.sum(case((((SurveyExecution.status == "completed") & SurveyExecution.is_test.is_(False)), 1), else_=0)).label("completed"),
        )
        .outerjoin(SurveyExecution)
        .where(questionnaire_filter)
        .group_by(Questionnaire.id)
        .order_by(Questionnaire.updated_at.desc())
    ).all()
    flow_rows = db.execute(
        select(EntryFlow, func.sum(case((CollectionSession.is_test.is_(False), 1), else_=0)).label("sessions"))
        .outerjoin(CollectionSession)
        .where(flow_filter)
        .group_by(EntryFlow.id)
        .order_by(EntryFlow.updated_at.desc())
    ).all()
    archived_count = (db.scalar(select(func.count(Questionnaire.id)).where(Questionnaire.status == "archived")) or 0) + (db.scalar(select(func.count(EntryFlow.id)).where(EntryFlow.status == "archived")) or 0)
    return request.app.state.templates.TemplateResponse(request, "questionnaires.html", ctx(request, db, rows=rows, flow_rows=flow_rows, showing_archived=arquivados, archived_count=archived_count))


QUESTION_TYPES = {
    "choice", "multiple_choice", "score", "yes_no", "stars", "text", "photo", "audio",
    "video", "document", "location", "contact", "multiple_files",
}
QUESTION_BINDINGS = {
    "", "lead.name", "lead.phone", "lead.city", "lead.neighborhood", "pet.name",
    "pet.species", "visit.reason", "visit.service_type", "visit.service_status",
    "visit.description",
}


def _questionnaire_state(questionnaire: Questionnaire | None, default_objective: str = "satisfaction") -> dict:
    registration = default_objective == "registration"
    return {
        "name": questionnaire.name if questionnaire else "",
        "description": questionnaire.description or "" if questionnaire else "",
        "objective": questionnaire.objective if questionnaire else default_objective,
        "status": questionnaire.status if questionnaire else "draft",
        "channels": channels(questionnaire) if questionnaire else (["kiosk", "interviewer"] if registration else ["whatsapp"]),
        "response_mode": questionnaire.response_mode if questionnaire else "identified",
        "trigger_type": questionnaire.trigger_type if questionnaire else "manual",
        "delay_value": questionnaire.delay_value if questionnaire else 0,
        "delay_unit": questionnaire.delay_unit if questionnaire else "days",
        "recurrence_days": questionnaire.recurrence_days or "" if questionnaire else "",
        "random_percent": questionnaire.random_percent if questionnaire else 100,
        "audience_type": questionnaire.audience_type if questionnaire else "all",
        "target_segment_id": questionnaire.target_segment_id or "" if questionnaire else "",
        "opening_message": questionnaire.opening_message if questionnaire else ("" if registration else "Olá, {{nome}}! Podemos fazer algumas perguntas rápidas?"),
        "closing_message": questionnaire.closing_message if questionnaire else "Obrigado pela participação!",
        "send_hour": questionnaire.send_hour if questionnaire else 10,
        "max_attempts": questionnaire.max_attempts if questionnaire else 2,
        "retry_hours": questionnaire.retry_hours if questionnaire else 24,
        "stop_after_response": questionnaire.stop_after_response if questionnaire else True,
        "alert_enabled": questionnaire.alert_enabled if questionnaire else True,
        "alert_threshold": questionnaire.alert_threshold if questionnaire else 6,
        "alert_severity": questionnaire.alert_severity if questionnaire else "high",
        "auto_segment": questionnaire.auto_segment if questionnaire else True,
    }


def _stable_options_data(raw_options) -> list[dict]:
    result: list[dict] = []
    for raw in raw_options if isinstance(raw_options, list) else []:
        item = dict(raw) if isinstance(raw, dict) else {}
        key = stable_editor_key("option", item.get("id"))
        item["id"] = key
        result.append(item)
    return result


def _normalize_question_editor_data(questions_data: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for raw in questions_data:
        if not isinstance(raw, dict):
            normalized.append(raw)
            continue
        item = dict(raw)
        question_id = _int(item.get("id"), 0)
        key = stable_editor_key("question", item.get("item_key"), question_id or None)
        item["item_key"] = key
        item["options"] = _stable_options_data(item.get("options"))
        item["replacement_question_id"] = _int(item.get("replacement_question_id"), 0) or None
        normalized.append(item)
    return normalized


def _question_settings_json(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _question_impacts(db: Session, questionnaire: Questionnaire | None) -> dict[str, list[dict]]:
    if not questionnaire or not questionnaire.id:
        return {}
    question_ids = [question.id for question in questionnaire.questions if question.id]
    if not question_ids:
        return {}
    rows = db.execute(
        select(EntryFlowAction, EntryFlow)
        .join(EntryFlow, EntryFlow.id == EntryFlowAction.flow_id)
        .where(EntryFlowAction.condition_question_id.in_(question_ids))
        .order_by(EntryFlow.name, EntryFlowAction.position)
    ).all()
    result: dict[str, list[dict]] = {}
    for action, flow in rows:
        result.setdefault(str(action.condition_question_id), []).append({
            "flow_id": flow.id,
            "flow_name": flow.name,
            "action_id": action.id,
            "action_name": action.name,
            "operator": action.condition_operator or "answered",
        })
    return result


def _questions_from_row(questionnaire: Questionnaire | None) -> list[dict]:
    if not questionnaire:
        return []
    return [
        {
            "id": question.id,
            "item_key": f"question:{question.id}",
            "archived": False,
            "text": question.text,
            "type": question.type,
            "required": question.required,
            "help_text": question.help_text or "",
            "options": _stable_options_data(options(question)),
            "min_score": question.min_score,
            "max_score": question.max_score,
            "low_score_threshold": question.low_score_threshold,
            "segment_low_id": question.segment_low_id,
            "segment_high_id": question.segment_high_id,
            "whatsapp_response_mode": question.whatsapp_response_mode or "auto",
            "data_binding": question.data_binding or "",
            "settings": _question_settings_json(question.settings_json),
        }
        for question in active_questions(questionnaire)
    ]


def _editor_context(
    request: Request,
    db: Session,
    questionnaire: Questionnaire | None = None,
    default_objective: str = "satisfaction",
    *,
    editor_state: dict | None = None,
    initial_questions: list[dict] | None = None,
    editor_errors: list[dict] | None = None,
    submission_token: str | None = None,
    editor_conflict: dict | None = None,
):
    segments = db.scalars(select(Segment).where(Segment.active.is_(True)).order_by(Segment.name)).all()
    state = editor_state or _questionnaire_state(questionnaire, default_objective)
    view = SimpleNamespace(id=questionnaire.id if questionnaire else None, **{key: value for key, value in state.items() if key != "channels"})
    versions = []
    impact = {}
    if questionnaire:
        raw_versions = db.scalars(select(QuestionnaireVersion).where(
            QuestionnaireVersion.questionnaire_id == questionnaire.id,
        ).order_by(QuestionnaireVersion.version_number.desc())).all()
        author_ids = {item.published_by_id for item in raw_versions if item.published_by_id}
        authors = {item.id: item.name for item in db.scalars(select(User).where(User.id.in_(author_ids))).all()} if author_ids else {}
        versions = [{
            "id": item.id,
            "number": item.version_number,
            "status": item.status,
            "published_at": item.published_at,
            "author": authors.get(item.published_by_id, "Sistema"),
            "question_count": db.scalar(select(func.count(QuestionnaireVersionQuestion.id)).where(QuestionnaireVersionQuestion.version_id == item.id)) or 0,
            "execution_count": db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.questionnaire_version_id == item.id)) or 0,
            "summary": json.loads(item.change_summary_json or "{}"),
        } for item in raw_versions]
        impact = version_impact(db, questionnaire)
    last_editor = db.get(User, questionnaire.last_edited_by_id) if questionnaire and questionnaire.last_edited_by_id else None
    effective_token = submission_token or new_submission_token()
    return ctx(
        request,
        db,
        questionnaire=view,
        persisted_questionnaire=questionnaire,
        segments=segments,
        segment_options=[{"id": item.id, "name": item.name} for item in segments],
        initial_questions=initial_questions if initial_questions is not None else _questions_from_row(questionnaire),
        questionnaire_channels=list(state.get("channels") or []),
        default_objective=state.get("objective") or default_objective,
        editor_errors=editor_errors or [],
        editor_submission_token=effective_token,
        editor_had_error=bool(editor_errors),
        editor_saved=request.query_params.get("saved") == "1",
        question_impacts=_question_impacts(db, questionnaire),
        questionnaire_versions=versions,
        version_impact=impact,
        editor_entity_key=str(questionnaire.id) if questionnaire else f"new:{effective_token.replace('.', '_')}",
        editor_revision=int(questionnaire.revision or 1) if questionnaire else 0,
        editor_updated_at=questionnaire.updated_at.isoformat() if questionnaire and questionnaire.updated_at else "",
        editor_last_user=last_editor.name if last_editor else "Sistema",
        editor_conflict=editor_conflict,
    )


@router.get("/questionarios/novo")
def questionnaire_new(request: Request, objective: str = "satisfaction", db: Session = Depends(get_db)):
    require_user(request, db)
    objective = objective if objective in {"satisfaction", "registration", "profile", "followup", "campaign"} else "satisfaction"
    return request.app.state.templates.TemplateResponse(request, "questionnaire_editor.html", _editor_context(request, db, default_objective=objective))


def _question_values(data: dict, position: int) -> dict:
    mode = str(data.get("whatsapp_response_mode") or "auto")
    if mode not in {"auto", "buttons", "option_list", "numbered_text", "text"}:
        mode = "auto"
    question_type = str(data.get("type") or "choice")
    allowed_types = {
        "choice", "multiple_choice", "score", "yes_no", "stars", "text", "photo", "audio",
        "video", "document", "location", "contact", "multiple_files",
    }
    if question_type not in allowed_types:
        question_type = "text"
    return {
        "position": position,
        "text": str(data.get("text") or "").strip(),
        "type": question_type,
        "required": bool(data.get("required", True)),
        "help_text": str(data.get("help_text") or "").strip() or None,
        "options_json": json.dumps(data.get("options") or [], ensure_ascii=False),
        "min_score": _int(data.get("min_score"), 0),
        "max_score": _int(data.get("max_score"), 10),
        "low_score_threshold": _float(data.get("low_score_threshold"), 0) if data.get("low_score_threshold") not in (None, "") else None,
        "segment_low_id": _int(data.get("segment_low_id"), 0) or None,
        "segment_high_id": _int(data.get("segment_high_id"), 0) or None,
        "whatsapp_response_mode": mode,
        "data_binding": str(data.get("data_binding") or "").strip() or None,
        "settings_json": json.dumps(data.get("settings") if isinstance(data.get("settings"), dict) else {}, ensure_ascii=False),
    }


def _apply_question_values(question: Question, values: dict) -> None:
    for field, value in values.items():
        setattr(question, field, value)
    question.active = True
    question.archived_at = None


def _question_has_history(db: Session, question_id: int) -> bool:
    answer_count = db.scalar(select(func.count(SurveyAnswer.id)).where(SurveyAnswer.question_id == question_id)) or 0
    queue_count = db.scalar(select(func.count(MessageQueue.id)).where(MessageQueue.question_id == question_id)) or 0
    version_count = db.scalar(select(func.count(QuestionnaireVersionQuestion.id)).where(
        QuestionnaireVersionQuestion.original_question_id == question_id
    )) or 0
    return bool(answer_count or queue_count or version_count)


def _sync_questionnaire_questions(db: Session, row: Questionnaire, questions_data: list[dict]) -> None:
    existing = {question.id: question for question in row.questions if question.id and getattr(question, "active", True)}
    submitted_ids: set[int] = set()
    saved_questions: list[tuple[dict, Question]] = []
    questions_by_key: dict[str, Question] = {}
    replacements = {
        _int(data.get("id"), 0): _int(data.get("replacement_question_id"), 0)
        for data in questions_data
        if isinstance(data, dict) and data.get("archived") and _int(data.get("id"), 0) and _int(data.get("replacement_question_id"), 0)
    }

    for position, data in enumerate(questions_data, start=1):
        if not isinstance(data, dict):
            continue
        if bool(data.get("archived")):
            continue
        values = _question_values(data, position)
        question_id = _int(data.get("id"), 0)
        if question_id:
            question = existing.get(question_id)
            if not question:
                raise ValueError("Uma das perguntas não pertence a este questionário ou já foi arquivada. Recarregue a página.")
            submitted_ids.add(question_id)
            _apply_question_values(question, values)
        else:
            question = Question(active=True, **values)
            row.questions.append(question)
        item_key = str(data.get("item_key") or (f"question:{question_id}" if question_id else ""))
        if item_key:
            questions_by_key[item_key] = question
        saved_questions.append((data, question))

    db.flush()
    for data, question in saved_questions:
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        settings = dict(settings)
        visibility = settings.get("visibility") if isinstance(settings.get("visibility"), dict) else {}
        visibility = dict(visibility)
        if visibility.get("enabled"):
            source_key = str(visibility.get("source_item_key") or "")
            if not source_key and _int(visibility.get("source_question_id"), 0):
                source_key = f"question:{_int(visibility.get('source_question_id'), 0)}"
            source_question = questions_by_key.get(source_key)
            if not source_question:
                raise ValueError("A condição de uma pergunta aponta para uma pergunta anterior inválida.")
            visibility["source_question_id"] = source_question.id
            visibility["source_item_key"] = f"question:{source_question.id}"
            visibility["operator"] = str(visibility.get("operator") or "equals")
            visibility["value"] = str(visibility.get("value") or "")
            if visibility["operator"] == "between":
                visibility["value_max"] = str(visibility.get("value_max") or "")
            else:
                visibility.pop("value_max", None)
            settings["visibility"] = visibility
        else:
            settings.pop("visibility", None)
        question.settings_json = json.dumps(settings, ensure_ascii=False)

    for old_question_id, replacement_question_id in replacements.items():
        logger.info(
            "Substituindo pergunta %s por %s nas condições de fluxo antes do arquivamento.",
            old_question_id,
            replacement_question_id,
        )
        db.execute(
            update(EntryFlowAction)
            .where(EntryFlowAction.condition_question_id == old_question_id)
            .values(condition_question_id=replacement_question_id)
        )

    for question_id, question in existing.items():
        if question_id in submitted_ids:
            continue
        if _question_has_history(db, question_id):
            question.active = False
            question.archived_at = utcnow()
        else:
            db.delete(question)

    db.flush()
    active_count = db.scalar(
        select(func.count(Question.id)).where(Question.questionnaire_id == row.id, Question.active.is_(True))
    ) or 0
    if not active_count:
        raise ValueError("Adicione pelo menos uma pergunta válida.")


def _questionnaire_form_state(form) -> dict:
    return {
        "name": str(form.get("name") or ""),
        "description": str(form.get("description") or ""),
        "objective": str(form.get("objective") or "satisfaction"),
        "status": str(form.get("status") or "draft"),
        "channels": [str(value) for value in form.getlist("channels")],
        "response_mode": str(form.get("response_mode") or "identified"),
        "trigger_type": str(form.get("trigger_type") or "manual"),
        "delay_value": str(form.get("delay_value") or "0"),
        "delay_unit": str(form.get("delay_unit") or "days"),
        "recurrence_days": str(form.get("recurrence_days") or ""),
        "random_percent": str(form.get("random_percent") or "100"),
        "audience_type": str(form.get("audience_type") or "all"),
        "target_segment_id": str(form.get("target_segment_id") or ""),
        "opening_message": str(form.get("opening_message") or ""),
        "closing_message": str(form.get("closing_message") or ""),
        "send_hour": str(form.get("send_hour") or ""),
        "max_attempts": str(form.get("max_attempts") or ""),
        "retry_hours": str(form.get("retry_hours") or ""),
        "stop_after_response": _bool(form, "stop_after_response"),
        "alert_enabled": _bool(form, "alert_enabled"),
        "alert_threshold": str(form.get("alert_threshold") or ""),
        "alert_severity": str(form.get("alert_severity") or "high"),
        "auto_segment": _bool(form, "auto_segment"),
    }


def _number(value, *, integer: bool = False):
    try:
        return int(value) if integer else float(value)
    except (TypeError, ValueError):
        return None


def _normalized_duplicate(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _validate_questionnaire_submission(
    db: Session,
    state: dict,
    questions_data: list[dict],
    questionnaire: Questionnaire | None,
) -> list[dict]:
    errors: list[dict] = []
    if not state["name"].strip():
        errors.append(error("identity", "name", "Informe o nome do questionário."))
    if state["objective"] not in {"satisfaction", "registration", "profile", "followup", "campaign"}:
        errors.append(error("identity", "objective", "Escolha um objetivo válido."))
    if state["status"] not in {"draft", "active", "paused", "archived"}:
        errors.append(error("identity", "status", "Escolha um status válido."))
    if state["trigger_type"] not in {"manual", "immediate_registration", "after_registration", "whatsapp_onboarding", "recurring", "random"}:
        errors.append(error("trigger", "trigger_type", "Escolha uma forma de início válida."))
    if state["delay_unit"] not in {"minutes", "hours", "days"}:
        errors.append(error("trigger", "delay_unit", "Escolha uma unidade de espera válida."))
    if state["response_mode"] not in {"identified", "anonymous"}:
        errors.append(error("audience", "response_mode", "Escolha uma forma de identificação válida."))
    allowed_channels = {"whatsapp", "kiosk", "interviewer"}
    if not state["channels"]:
        errors.append(error("audience", "channels", "Selecione pelo menos um canal."))
    elif any(channel not in allowed_channels for channel in state["channels"]):
        errors.append(error("audience", "channels", "Há um canal inválido na seleção."))
    if state["response_mode"] == "anonymous" and "whatsapp" in state["channels"]:
        errors.append(error("audience", "channels", "Pesquisas anônimas não podem usar WhatsApp."))
    if "whatsapp" in state["channels"] and not state["opening_message"].strip():
        errors.append(error("audience", "opening_message", "Informe a mensagem de abertura do WhatsApp."))
    if not state["closing_message"].strip():
        errors.append(error("audience", "closing_message", "Informe a mensagem de encerramento."))
    if state["audience_type"] not in {"all", "segment", "new_leads", "no_response"}:
        errors.append(error("audience", "audience_type", "Escolha um público válido."))
    if state["audience_type"] == "segment":
        segment_id = _int(state["target_segment_id"], 0)
        segment = db.get(Segment, segment_id) if segment_id else None
        if not segment or not segment.active:
            errors.append(error("audience", "target_segment_id", "Selecione um segmento ativo para esta pesquisa."))
    send_hour = _number(state["send_hour"], integer=True)
    if send_hour is None or not 0 <= send_hour <= 23:
        errors.append(error("trigger", "send_hour", "A hora preferencial deve ficar entre 0 e 23."))
    delay = _number(state["delay_value"], integer=True)
    if delay is None or delay < 0:
        errors.append(error("trigger", "delay_value", "O tempo de espera não pode ser negativo."))
    random_percent = _number(state["random_percent"], integer=True)
    if random_percent is None or not 1 <= random_percent <= 100:
        errors.append(error("audience", "random_percent", "A amostra deve ficar entre 1% e 100%."))
    if (_number(state["max_attempts"], integer=True) or 0) < 1:
        errors.append(error("actions", "max_attempts", "Informe pelo menos uma tentativa."))
    if (_number(state["retry_hours"], integer=True) or 0) < 1:
        errors.append(error("actions", "retry_hours", "O intervalo deve ser de pelo menos uma hora."))
    if state["recurrence_days"] not in (None, "") and (_number(state["recurrence_days"], integer=True) or 0) < 1:
        errors.append(error("actions", "recurrence_days", "A recorrência deve ser de pelo menos um dia."))
    if state["alert_severity"] not in {"medium", "high", "critical"}:
        errors.append(error("actions", "alert_severity", "Escolha uma prioridade de alerta válida."))
    if state["alert_enabled"] and _number(state["alert_threshold"]) is None:
        errors.append(error("actions", "alert_threshold", "Informe uma nota de alerta válida."))

    existing_ids = {question.id for question in questionnaire.questions if getattr(question, "active", True)} if questionnaire else set()
    submitted_ids: set[int] = set()
    question_keys: set[str] = set()
    option_keys: set[str] = set()
    active_items = [item for item in questions_data if isinstance(item, dict) and not item.get("archived")]
    if not active_items:
        errors.append(error("questions", "questions_json", "Adicione pelo menos uma pergunta ativa."))
    bindings: list[tuple[str, str]] = []
    score_ranges: list[tuple[float, float]] = []
    prior_questions: dict[str, dict] = {}
    for index, item in enumerate(questions_data, start=1):
        if not isinstance(item, dict):
            errors.append(error("questions", "questions_json", f"A pergunta {index} possui dados inválidos.", f"question:{index}"))
            continue
        item_key = str(item.get("item_key") or (f"question:{item.get('id')}" if item.get("id") else f"question:new:{index}"))
        if item_key in question_keys:
            errors.append(error("questions", "item_key", "Duas perguntas estão usando a mesma identidade interna.", item_key))
        question_keys.add(item_key)
        question_id = _int(item.get("id"), 0)
        if question_id:
            if question_id not in existing_ids or question_id in submitted_ids:
                errors.append(error("questions", "id", f"A pergunta {index} não pertence a este questionário ou foi repetida.", item_key))
            submitted_ids.add(question_id)
        if item.get("archived"):
            continue
        text_value = str(item.get("text") or "").strip()
        if not text_value:
            errors.append(error("questions", "text", f"A pergunta {index} está sem texto.", item_key))
        question_type = str(item.get("type") or "")
        if question_type not in QUESTION_TYPES:
            errors.append(error("questions", "type", f"Escolha um tipo válido para a pergunta {index}.", item_key))
        settings_data = item.get("settings") if isinstance(item.get("settings"), dict) else {}
        visibility = settings_data.get("visibility") if isinstance(settings_data.get("visibility"), dict) else {}
        if visibility.get("enabled"):
            source_key = str(visibility.get("source_item_key") or "")
            if not source_key and _int(visibility.get("source_question_id"), 0):
                source_key = f"question:{_int(visibility.get('source_question_id'), 0)}"
            source = prior_questions.get(source_key)
            operator = str(visibility.get("operator") or "equals")
            expected = str(visibility.get("value") or "").strip()
            if not source:
                errors.append(error("questions", "condition_source", "Escolha uma pergunta anterior do mesmo questionário para a condição.", item_key))
            if operator not in QUESTION_CONDITION_OPERATORS:
                errors.append(error("questions", "condition_operator", "Escolha um operador válido para a condição.", item_key))
            elif operator in QUESTION_NUMERIC_CONDITION_OPERATORS:
                if source and source.get("type") not in {"score", "stars"}:
                    errors.append(error("questions", "condition_source", "Condições numéricas só podem usar uma pergunta de nota ou estrelas como origem.", item_key))
                if _number(expected) is None:
                    errors.append(error("questions", "condition_value", "Informe um número para esta condição.", item_key))
                if operator == "between":
                    value_max = _number(str(visibility.get("value_max") or "").strip())
                    if value_max is None:
                        errors.append(error("questions", "condition_value", "Informe o valor máximo da faixa.", item_key))
                    elif _number(expected) is not None and value_max < _number(expected):
                        errors.append(error("questions", "condition_value", "O valor máximo deve ser maior ou igual ao mínimo.", item_key))
            elif operator not in {"answered", "not_answered"} and not expected:
                errors.append(error("questions", "condition_value", "Informe a resposta que libera esta pergunta.", item_key))
            if source and operator in {"equals", "not_equals"} and source.get("type") in {"choice", "multiple_choice", "yes_no"}:
                if source.get("type") == "yes_no":
                    allowed_values = {"sim", "não", "nao"}
                else:
                    allowed_values = {
                        _normalized_duplicate(option.get("value") or option.get("label"))
                        for option in source.get("options", []) if isinstance(option, dict)
                    }
                if _normalized_duplicate(expected) not in allowed_values:
                    errors.append(error("questions", "condition_value", "Selecione uma das respostas disponíveis na pergunta anterior.", item_key))
        binding = str(item.get("data_binding") or "").strip()
        if binding not in QUESTION_BINDINGS:
            errors.append(error("questions", "data_binding", "Escolha um vínculo cadastral válido.", item_key))
        elif binding:
            bindings.append((binding, item_key))
        response_mode = str(item.get("whatsapp_response_mode") or "auto")
        if response_mode not in {"auto", "buttons", "option_list", "numbered_text", "text"}:
            errors.append(error("questions", "whatsapp_response_mode", "Escolha um formato de resposta válido.", item_key))
        for segment_field in ("segment_low_id", "segment_high_id"):
            segment_id = _int(item.get(segment_field), 0)
            if segment_id and not db.get(Segment, segment_id):
                errors.append(error("questions", segment_field, "O segmento selecionado não existe.", item_key))
        if question_type in {"choice", "multiple_choice"}:
            option_rows = item.get("options") if isinstance(item.get("options"), list) else []
            labels: dict[str, int] = {}
            values: dict[str, int] = {}
            valid_options = 0
            for option_index, option in enumerate(option_rows, start=1):
                option = option if isinstance(option, dict) else {}
                option_key = str(option.get("id") or "")
                if option_key in option_keys:
                    errors.append(error("questions", f"option_label_{option_index - 1}", "Duas opções estão usando a mesma identidade interna.", item_key))
                option_keys.add(option_key)
                label = str(option.get("label") or "").strip()
                value = str(option.get("value") or "").strip()
                option_segment_id = _int(option.get("segment_id"), 0)
                if option_segment_id and not db.get(Segment, option_segment_id):
                    errors.append(error("questions", f"option_segment_{option_index - 1}", "O segmento desta opção não existe.", item_key))
                if not label:
                    errors.append(error("questions", f"option_label_{option_index - 1}", f"Preencha o texto da opção {option_index}.", item_key))
                    continue
                valid_options += 1
                label_key = _normalized_duplicate(label)
                value_key = _normalized_duplicate(value or label)
                if label_key in labels:
                    errors.append(error("questions", f"option_label_{option_index - 1}", f'A opção "{label}" está duplicada.', item_key))
                if value_key in values:
                    errors.append(error("questions", f"option_value_{option_index - 1}", f'O valor interno "{value or label}" está duplicado.', item_key))
                labels[label_key] = option_index
                values[value_key] = option_index
            if valid_options < 2:
                errors.append(error("questions", "options", f"A pergunta {index} precisa de pelo menos duas opções preenchidas.", item_key))
            if question_type == "multiple_choice":
                settings_data = item.get("settings") if isinstance(item.get("settings"), dict) else {}
                minimum_selections = _number(settings_data.get("min_selections"), integer=True)
                maximum_selections = _number(settings_data.get("max_selections"), integer=True)
                if minimum_selections is None or minimum_selections < 0:
                    errors.append(error("questions", "min_selections", "O mínimo de escolhas não pode ser negativo.", item_key))
                if maximum_selections is not None and maximum_selections < 1:
                    errors.append(error("questions", "max_selections", "O máximo de escolhas deve ser pelo menos 1.", item_key))
                if minimum_selections is not None and maximum_selections is not None and minimum_selections > maximum_selections:
                    errors.append(error("questions", "max_selections", "O máximo de escolhas precisa ser maior ou igual ao mínimo.", item_key))
        if question_type in {"score", "stars"}:
            minimum = _number(item.get("min_score"))
            maximum = _number(item.get("max_score"))
            if minimum is None:
                errors.append(error("questions", "min_score", "Informe o início da escala.", item_key))
            if maximum is None:
                errors.append(error("questions", "max_score", "Informe o fim da escala.", item_key))
            if minimum is not None and maximum is not None:
                if minimum >= maximum:
                    errors.append(error("questions", "max_score", "O máximo precisa ser maior que o mínimo.", item_key))
                else:
                    score_ranges.append((minimum, maximum))
                    threshold = item.get("low_score_threshold")
                    if threshold not in (None, ""):
                        threshold_number = _number(threshold)
                        if threshold_number is None or not minimum <= threshold_number <= maximum:
                            errors.append(error("questions", "low_score_threshold", "A nota baixa precisa ficar dentro da escala.", item_key))
        prior_questions[item_key] = item
        if question_id:
            prior_questions[f"question:{question_id}"] = item

    active_submitted_ids = {
        _int(item.get("id"), 0)
        for item in active_items
        if isinstance(item, dict) and _int(item.get("id"), 0)
    }
    impact_counts = dict(db.execute(
        select(EntryFlowAction.condition_question_id, func.count(EntryFlowAction.id))
        .where(EntryFlowAction.condition_question_id.in_(existing_ids))
        .group_by(EntryFlowAction.condition_question_id)
    ).all()) if existing_ids else {}
    submitted_by_id = {
        _int(item.get("id"), 0): item
        for item in questions_data
        if isinstance(item, dict) and _int(item.get("id"), 0)
    }
    for question_id, impact_count in impact_counts.items():
        item = submitted_by_id.get(question_id)
        if item is None:
            errors.append(error("questions", "replacement_question_id", f"Esta pergunta é utilizada em {impact_count} ações e não pode ser removida sem substituição.", f"question:{question_id}"))
            continue
        if not item.get("archived"):
            continue
        replacement_id = _int(item.get("replacement_question_id"), 0)
        if replacement_id == question_id or replacement_id not in active_submitted_ids:
            errors.append(error("questions", "replacement_question_id", f"Esta pergunta é utilizada em {impact_count} ações. Escolha outra pergunta ativa para substituí-la.", str(item.get("item_key") or f"question:{question_id}")))

    duplicate_bindings = {value for value, _ in bindings if [item[0] for item in bindings].count(value) > 1}
    for binding, item_key in bindings:
        if binding in duplicate_bindings:
            errors.append(error("questions", "data_binding", "Cada campo do cadastro pode ser usado apenas uma vez.", item_key))
    if state["objective"] == "registration":
        if state["response_mode"] != "identified":
            errors.append(error("audience", "response_mode", "O Cadastro estruturado precisa ser identificado."))
        for index, item in enumerate(active_items, start=1):
            if str(item.get("type") or "") in {"photo", "audio", "video", "document", "location", "contact", "multiple_files"}:
                item_key = str(item.get("item_key") or f"question:new:{index}")
                errors.append(error("questions", "type", "O Cadastro estruturado na tela ainda não aceita perguntas de mídia.", item_key))
        if state["status"] == "active":
            found = {value for value, _ in bindings}
            for required_binding, label in (("lead.name", "Nome completo"), ("lead.phone", "WhatsApp")):
                if required_binding not in found:
                    errors.append(error("questions", "data_binding", f'O cadastro ativo precisa conter o vínculo "{label}".'))
    if state["alert_enabled"] and score_ranges:
        alert_threshold = _number(state["alert_threshold"])
        scale_min = min(item[0] for item in score_ranges)
        scale_max = max(item[1] for item in score_ranges)
        if alert_threshold is None or not scale_min <= alert_threshold <= scale_max:
            errors.append(error("actions", "alert_threshold", "A nota de alerta precisa ficar dentro da escala das perguntas."))
    return errors


def _validate_registration_questionnaire(row: Questionnaire) -> None:
    """Validação curta usada ao ativar pela listagem, fora do editor completo."""
    if row.objective != "registration":
        return
    if row.response_mode != "identified":
        raise ValueError("Questionários de cadastro estruturado precisam ser identificados.")
    current = active_questions(row)
    bindings = [question.data_binding for question in current if question.data_binding]
    if any(question.type in {"photo", "audio", "video", "document", "location", "contact", "multiple_files"} for question in current):
        raise ValueError("O Cadastro estruturado na tela ainda não aceita perguntas de mídia.")
    if len(bindings) != len(set(bindings)):
        raise ValueError("Cada campo do cadastro pode ser usado apenas uma vez.")
    missing = [binding for binding in ("lead.name", "lead.phone") if binding not in bindings]
    if missing:
        raise ValueError("O cadastro ativo precisa conter Nome completo e WhatsApp.")


def _apply_questionnaire_state(row: Questionnaire, state: dict) -> None:
    row.name = state["name"].strip()
    row.description = state["description"].strip() or None
    row.objective = state["objective"]
    row.status = state["status"]
    row.channels_json = json.dumps(state["channels"], ensure_ascii=False)
    row.response_mode = state["response_mode"]
    row.trigger_type = state["trigger_type"]
    row.delay_value = _int(state["delay_value"], 0)
    row.delay_unit = state["delay_unit"]
    row.recurrence_days = _int(state["recurrence_days"], 0) or None
    row.random_percent = _int(state["random_percent"], 100)
    row.audience_type = state["audience_type"]
    row.target_segment_id = _int(state["target_segment_id"], 0) or None
    row.opening_message = state["opening_message"].strip()
    row.closing_message = state["closing_message"].strip()
    row.send_hour = _int(state["send_hour"], 10)
    row.max_attempts = _int(state["max_attempts"], 2)
    row.retry_hours = _int(state["retry_hours"], 24)
    row.stop_after_response = state["stop_after_response"]
    row.alert_enabled = state["alert_enabled"]
    row.alert_threshold = _float(state["alert_threshold"], 6)
    row.alert_severity = state["alert_severity"]
    row.auto_segment = state["auto_segment"]
    if row.status == "active" and not row.published_at:
        row.published_at = utcnow()


def _persist_questionnaire(db: Session, user: User, state: dict, questions_data: list[dict], questionnaire: Questionnaire | None, token: str, *, publish: bool = True, recovery_source: str = "direct") -> tuple[Questionnaire, str, bool]:
    claim = add_submission_claim(db, token, "questionnaire:update" if questionnaire else "questionnaire:create")
    row = questionnaire or Questionnaire(created_by_id=user.id)
    old_revision = int(row.revision or 1) if questionnaire else 0
    old_snapshot = {"name": row.name, "status": row.status, "questions": len(active_questions(row))} if questionnaire else None
    _apply_questionnaire_state(row, state)
    if questionnaire is None:
        row.revision = 1
        db.add(row)
    else:
        row.revision = old_revision + 1
    row.last_edited_by_id = user.id
    db.flush()
    _sync_questionnaire_questions(db, row, questions_data)
    published = False
    if publish:
        published_version, published = publish_questionnaire_version(db, row, user_id=user.id)
        if published:
            db.add(AuditLog(
                user_id=user.id,
                action="questionnaire_version_publish",
                entity="questionnaire",
                entity_id=row.id,
                details=json.dumps({"version_id": published_version.id, "version_number": published_version.version_number}, ensure_ascii=False),
            ))
    db.add(AuditLog(
        user_id=user.id,
        action="questionnaire_create" if questionnaire is None else "questionnaire_update",
        entity="questionnaire",
        entity_id=row.id,
        details=json.dumps({"old_revision": old_revision, "new_revision": row.revision, "old": old_snapshot, "new": {"name": row.name, "status": row.status, "questions": len([item for item in questions_data if not item.get("archived")])}, "published": published, "recovery_source": recovery_source}, ensure_ascii=False),
    ))
    destination = f"/questionarios/{row.id}/editar?saved=1"
    if claim:
        claim.destination = destination
    db.commit()
    db.refresh(row)
    return row, destination, published


def _questionnaire_error_response(request: Request, db: Session, row: Questionnaire | None, state: dict, questions_data: list[dict], errors: list[dict], token: str):
    db.rollback()
    return request.app.state.templates.TemplateResponse(
        request,
        "questionnaire_editor.html",
        _editor_context(
            request,
            db,
            row,
            default_objective=state.get("objective") or "satisfaction",
            editor_state=state,
            initial_questions=questions_data,
            editor_errors=errors,
            submission_token=token or new_submission_token(),
        ),
        status_code=400,
    )


def _questionnaire_conflict_response(request: Request, db: Session, row: Questionnaire, state: dict, questions_data: list[dict], token: str, submitted_revision: int):
    last_editor = db.get(User, row.last_edited_by_id) if row.last_edited_by_id else None
    conflict = {"submitted_revision": submitted_revision, "current_revision": int(row.revision or 1), "updated_at": row.updated_at.isoformat() if row.updated_at else "", "last_user": last_editor.name if last_editor else "outro usuário"}
    return request.app.state.templates.TemplateResponse(
        request,
        "questionnaire_editor.html",
        _editor_context(request, db, row, default_objective=state.get("objective") or "satisfaction", editor_state=state, initial_questions=questions_data, submission_token=token or new_submission_token(), editor_conflict=conflict),
        status_code=409,
    )


@router.post("/questionarios/novo")
async def questionnaire_create(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    publish = str(form.get("editor_action") or "publish") == "publish"
    token = str(form.get("submission_token") or "")
    duplicate = completed_submission(request, token) or persisted_submission(db, token)
    if duplicate:
        return redirect(duplicate)
    state = _questionnaire_form_state(form)
    parse_errors: list[dict] = []
    try:
        questions_data = json.loads(str(form.get("questions_json") or "[]"))
        if not isinstance(questions_data, list):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError):
        questions_data = []
        parse_errors.append(error("questions", "questions_json", "Não foi possível interpretar as perguntas. Refaça a última alteração."))
    questions_data = _normalize_question_editor_data(questions_data)
    errors = parse_errors + _validate_questionnaire_submission(db, state, questions_data, None)
    if errors:
        return _questionnaire_error_response(request, db, None, state, questions_data, errors, token)
    try:
        row, destination, published = _persist_questionnaire(db, user, state, questions_data, None, token, publish=publish, recovery_source=str(form.get("editor_recovery_source") or "direct"))
    except IntegrityError:
        db.rollback()
        duplicate = persisted_submission(db, token)
        if duplicate:
            return redirect(duplicate)
        return _questionnaire_error_response(request, db, None, state, questions_data, [error("identity", "name", "Não foi possível salvar. Nenhuma alteração foi gravada; revise os campos e tente novamente.")], token)
    except Exception:
        return _questionnaire_error_response(request, db, None, state, questions_data, [error("identity", "name", "Não foi possível salvar. Nenhuma alteração foi gravada; revise os campos e tente novamente.")], token)
    remember_submission(request, token, destination)
    flash(request, "Questionário criado e versão 1 publicada." if published else "Questionário criado como rascunho. Nenhuma execução foi alterada.")
    return redirect(destination)


@router.get("/questionarios/{questionnaire_id}/editar")
def questionnaire_edit(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    row = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
    if not row:
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse(request, "questionnaire_editor.html", _editor_context(request, db, row))


@router.get("/questionarios/{questionnaire_id}/versoes/{version_id}")
def questionnaire_version_view(request: Request, questionnaire_id: int, version_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    version = db.scalar(select(QuestionnaireVersion).options(
        selectinload(QuestionnaireVersion.questions)
    ).where(
        QuestionnaireVersion.id == version_id,
        QuestionnaireVersion.questionnaire_id == questionnaire_id,
    ))
    if not version:
        raise HTTPException(404)
    author = db.get(User, version.published_by_id) if version.published_by_id else None
    executions = db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.questionnaire_version_id == version.id)) or 0
    return request.app.state.templates.TemplateResponse(request, "questionnaire_version.html", ctx(
        request,
        db,
        version=version,
        version_config=version_config(version),
        questions=version.questions,
        author=author,
        execution_count=executions,
        change_summary=json.loads(version.change_summary_json or "{}"),
    ))


@router.post("/questionarios/{questionnaire_id}/editar")
async def questionnaire_update(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
    if not row:
        raise HTTPException(404)
    form = await request.form()
    publish = str(form.get("editor_action") or "publish") == "publish"
    token = str(form.get("submission_token") or "")
    duplicate = completed_submission(request, token) or persisted_submission(db, token)
    if duplicate:
        return redirect(duplicate)
    state = _questionnaire_form_state(form)
    parse_errors: list[dict] = []
    try:
        questions_data = json.loads(str(form.get("questions_json") or "[]"))
        if not isinstance(questions_data, list):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError):
        questions_data = []
        parse_errors.append(error("questions", "questions_json", "Não foi possível interpretar as perguntas. Refaça a última alteração."))
    questions_data = _normalize_question_editor_data(questions_data)
    submitted_revision = _int(form.get("base_revision"), 0)
    if "base_revision" in form and submitted_revision != int(row.revision or 1):
        return _questionnaire_conflict_response(request, db, row, state, questions_data, token, submitted_revision)
    errors = parse_errors + _validate_questionnaire_submission(db, state, questions_data, row)
    if errors:
        return _questionnaire_error_response(request, db, row, state, questions_data, errors, token)
    try:
        row, destination, published = _persist_questionnaire(db, user, state, questions_data, row, token, publish=publish, recovery_source=str(form.get("editor_recovery_source") or "direct"))
    except IntegrityError:
        db.rollback()
        duplicate = persisted_submission(db, token)
        if duplicate:
            return redirect(duplicate)
        return _questionnaire_error_response(request, db, row, state, questions_data, [error("identity", "name", "Não foi possível salvar. A versão anterior e o histórico foram preservados.")], token)
    except Exception:
        return _questionnaire_error_response(request, db, row, state, questions_data, [error("identity", "name", "Não foi possível salvar. A versão anterior e o histórico foram preservados.")], token)
    remember_submission(request, token, destination)
    flash(request, "Nova versão publicada. Execuções já criadas continuam na versão anterior." if published else ("Nenhuma mudança nova para publicar." if publish else "Rascunho salvo. Pesquisas novas e em andamento continuam na versão publicada."))
    return redirect(destination)


@router.post("/questionarios/{questionnaire_id}/duplicar")
def questionnaire_duplicate(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    source = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
    if not source:
        raise HTTPException(404)
    target = Questionnaire(
        name=f"Cópia de {source.name}", description=source.description, objective=source.objective, status="draft",
        channels_json=source.channels_json, response_mode=source.response_mode, trigger_type="manual", delay_value=source.delay_value,
        delay_unit=source.delay_unit, recurrence_days=source.recurrence_days, random_percent=source.random_percent,
        audience_type=source.audience_type, target_segment_id=source.target_segment_id, opening_message=source.opening_message,
        closing_message=source.closing_message, send_hour=source.send_hour, max_attempts=source.max_attempts,
        retry_hours=source.retry_hours, stop_after_response=source.stop_after_response, alert_enabled=source.alert_enabled,
        alert_threshold=source.alert_threshold, alert_severity=source.alert_severity, auto_segment=source.auto_segment, created_by_id=user.id,
    )
    duplicated_questions: list[tuple[Question, Question]] = []
    for q in active_questions(source):
        copy = Question(position=q.position, text=q.text, type=q.type, required=q.required, help_text=q.help_text, options_json=json.dumps(_stable_options_data(options(q)), ensure_ascii=False), min_score=q.min_score, max_score=q.max_score, low_score_threshold=q.low_score_threshold, segment_low_id=q.segment_low_id, segment_high_id=q.segment_high_id, whatsapp_response_mode=q.whatsapp_response_mode or "auto", data_binding=q.data_binding, settings_json=q.settings_json or "{}")
        target.questions.append(copy)
        duplicated_questions.append((q, copy))
    db.add(target)
    db.flush()
    remapped_ids = {source_question.id: copy.id for source_question, copy in duplicated_questions}
    for _, copy in duplicated_questions:
        settings = _question_settings_json(copy.settings_json)
        visibility = settings.get("visibility") if isinstance(settings.get("visibility"), dict) else {}
        source_id = _int(visibility.get("source_question_id"), 0)
        if visibility.get("enabled") and source_id in remapped_ids:
            visibility = dict(visibility)
            visibility["source_question_id"] = remapped_ids[source_id]
            visibility["source_item_key"] = f"question:{remapped_ids[source_id]}"
            settings["visibility"] = visibility
            copy.settings_json = json.dumps(settings, ensure_ascii=False)
    db.commit()
    flash(request, "Questionário duplicado como rascunho.")
    return redirect(f"/questionarios/{target.id}/editar")


@router.post("/questionarios/{questionnaire_id}/status")
async def questionnaire_status(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    row = db.get(Questionnaire, questionnaire_id)
    if not row:
        raise HTTPException(404)
    form = await request.form()
    target = str(form.get("status") or "").strip()
    if target not in {"draft", "active", "paused", "archived"}:
        raise HTTPException(400, "Status inválido.")
    if target == "archived":
        used_as_registration = db.scalar(
            select(func.count(EntryFlow.id)).where(
                EntryFlow.registration_questionnaire_id == row.id,
                EntryFlow.status == "active",
            )
        ) or 0
        used_as_action = db.scalar(
            select(func.count(EntryFlowAction.id))
            .join(EntryFlow, EntryFlow.id == EntryFlowAction.flow_id)
            .where(
                EntryFlowAction.questionnaire_id == row.id,
                EntryFlowAction.active.is_(True),
                EntryFlow.status == "active",
            )
        ) or 0
        if used_as_registration or used_as_action:
            flash(request, "Este questionário está em um fluxo ativo. Pause ou edite o fluxo antes de arquivá-lo.", "danger")
            return redirect("/questionarios")
        # Arquivar impede novas seleções, mas não altera execuções já criadas:
        # cada uma continua usando sua versão publicada congelada.
    row.status = target
    if target == "active" and not row.published_at:
        row.published_at = utcnow()
    if target == "active":
        try:
            _validate_registration_questionnaire(row)
        except ValueError as exc:
            flash(request, str(exc), "danger")
            return redirect("/questionarios")
        if not latest_published_version(db, row):
            publish_questionnaire_version(db, row, user_id=current_user(request, db).id)
    db.commit()
    flash(request, {"archived": "Questionário arquivado.", "paused": "Questionário pausado.", "active": "Questionário ativado.", "draft": "Questionário movido para rascunho."}[target])
    return redirect("/questionarios?arquivados=1" if target == "archived" else "/questionarios")


@router.post("/questionarios/{questionnaire_id}/disparar")
def questionnaire_launch(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    row = db.get(Questionnaire, questionnaire_id)
    if not row:
        raise HTTPException(404)
    published = latest_published_version(db, row)
    config = version_config(published) if published else None
    if not config or "whatsapp" not in channels(config) or config.response_mode == "anonymous":
        flash(request, "O disparo em massa exige um questionário identificado habilitado para WhatsApp.", "danger")
    else:
        count = launch_questionnaire(db, row)
        db.commit()
        flash(request, f"{count} execução(ões) foram agendadas.")
    return redirect("/questionarios")


@router.get("/questionarios/{questionnaire_id}/testar")
def questionnaire_test(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    row = db.get(Questionnaire, questionnaire_id)
    if not row:
        raise HTTPException(404)
    execution = create_execution(db, row, channel="interviewer", source="laboratory", is_test=True, test_label="Simulação pelo editor")
    db.commit()
    return redirect(f"/aplicar/{execution.public_token}?test=1")


@router.post("/questionarios/{questionnaire_id}/testar-whatsapp")
async def questionnaire_test_whatsapp(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    questionnaire = db.get(Questionnaire, questionnaire_id)
    if not questionnaire:
        raise HTTPException(404)
    form = await request.form()
    execution, error_message = create_whatsapp_test_execution(db, questionnaire, str(form.get("phone") or ""))
    if error_message or not execution:
        flash(request, error_message or "Não foi possível criar o teste.", "danger")
        return redirect("/questionarios")
    db.commit()
    process_once()
    return redirect(f"/questionarios/testes/{execution.id}")


@router.get("/questionarios/testes/{execution_id}")
def questionnaire_test_progress(request: Request, execution_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    execution = db.scalar(
        select(SurveyExecution)
        .options(
            selectinload(SurveyExecution.questionnaire_version).selectinload(QuestionnaireVersion.questions),
            selectinload(SurveyExecution.lead),
            selectinload(SurveyExecution.answers).selectinload(SurveyAnswer.version_question),
        )
        .where(SurveyExecution.id == execution_id, SurveyExecution.is_test.is_(True))
    )
    if not execution:
        raise HTTPException(404)
    queue = db.scalars(select(MessageQueue).where(MessageQueue.execution_id == execution.id).order_by(MessageQueue.id)).all()
    answers_by_question = {answer.version_question_id: answer for answer in execution.answers}
    return request.app.state.templates.TemplateResponse(
        request,
        "questionnaire_test_progress.html",
        ctx(request, db, execution=execution, queue=queue, answers_by_question=answers_by_question, questions=execution_questions(execution)),
    )


@router.post("/questionarios/testes/{execution_id}/processar")
def questionnaire_test_process(request: Request, execution_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    execution = db.get(SurveyExecution, execution_id)
    if not execution or not execution.is_test:
        raise HTTPException(404)
    process_once()
    flash(request, "Fila processada e andamento atualizado.")
    return redirect(f"/questionarios/testes/{execution_id}")


@router.get("/segmentos")
def segments_page(request: Request, segment_id: int | None = None, tab: str = "publico", db: Session = Depends(get_db)):
    user = require_user(request, db)
    rows = db.execute(select(Segment, func.count(LeadSegment.id)).outerjoin(LeadSegment).group_by(Segment.id).order_by(Segment.active.desc(), Segment.name)).all()
    selected = db.get(Segment, segment_id) if segment_id else (rows[0][0] if rows else None)
    details = None
    questionnaires = []
    if selected:
        links = db.scalars(select(LeadSegment).options(selectinload(LeadSegment.lead).selectinload(Lead.pets)).where(LeadSegment.segment_id == selected.id).order_by(LeadSegment.created_at.desc()).limit(250)).all()
        city_ids = _user_city_ids(user)
        if city_ids is not None: links = [link for link in links if link.lead and link.lead.city_id in city_ids]
        since_30 = utcnow() - timedelta(days=30)
        events = db.scalars(select(SegmentEvent).where(SegmentEvent.segment_id == selected.id, SegmentEvent.occurred_at >= utcnow() - timedelta(days=370)).order_by(SegmentEvent.occurred_at)).all()
        month_map: dict[str, dict[str, int]] = {}
        for event in events:
            key = event.occurred_at.strftime("%Y-%m"); item = month_map.setdefault(key, {"entered": 0, "left": 0})
            if event.event_type in item: item[event.event_type] += 1
        months = [{"key": key, "label": datetime.strptime(key, "%Y-%m").strftime("%m/%Y"), **value} for key, value in sorted(month_map.items())[-12:]]
        rules = db.scalars(select(SegmentRule).where(SegmentRule.segment_id == selected.id).order_by(SegmentRule.position)).all()
        automations = db.scalars(
            select(SegmentAutomation)
            .options(selectinload(SegmentAutomation.questionnaires).selectinload(SegmentAutomationQuestionnaire.questionnaire))
            .where(SegmentAutomation.segment_id == selected.id)
            .order_by(SegmentAutomation.created_at.desc())
        ).all()
        automation_ids = [item.id for item in automations]
        automation_enrollment_counts = dict(db.execute(
            select(SegmentAutomationEnrollment.automation_id, func.count(SegmentAutomationEnrollment.id))
            .where(SegmentAutomationEnrollment.automation_id.in_(automation_ids or [0]))
            .group_by(SegmentAutomationEnrollment.automation_id)
        ).all())
        confirmed = sum(1 for link in links if link.lead and link.lead.number_validated)
        eligible = sum(1 for link in links if link.lead and link.lead.status == "active" and link.lead.consent_research and not link.lead.opted_out_at and (link.lead.phone_normalized or link.lead.whatsapp_lid))
        details = {"links": links, "rules": rules, "automations": automations, "automation_enrollment_counts": automation_enrollment_counts, "months": months, "confirmed": confirmed, "eligible": eligible, "entered_30": sum(1 for event in events if event.event_type == "entered" and event.occurred_at >= since_30)}
        for questionnaire in db.scalars(select(Questionnaire).where(Questionnaire.status == "active").order_by(Questionnaire.name)).all():
            version = latest_published_version(db, questionnaire); config = version_config(version) if version else None
            if config and "whatsapp" in channels(config) and config.response_mode == "identified": questionnaires.append(questionnaire)
    return request.app.state.templates.TemplateResponse(request, "segments.html", ctx(request, db, rows=rows, selected=selected, details=details, questionnaires=questionnaires, tab=tab))


@router.post("/segmentos")
async def segment_create(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    form = await request.form()
    name = str(form.get("name") or "").strip()
    if not name:
        flash(request, "Informe o nome do segmento.", "danger")
        return redirect("/segmentos")
    keywords = [item.strip() for item in str(form.get("keywords") or "").split(",") if item.strip()]
    row = Segment(name=name, description=str(form.get("description") or "").strip() or None, kind=str(form.get("kind") or "manual"), color=str(form.get("color") or "#0f766e"), keywords_json=json.dumps(keywords, ensure_ascii=False), min_confidence=_float(form.get("min_confidence"), 0.82))
    db.add(row)
    try:
        db.commit()
        flash(request, "Segmento criado.")
    except Exception:
        db.rollback()
        flash(request, "Já existe um segmento com esse nome.", "danger")
    return redirect(f"/segmentos?segment_id={row.id}" if row.id else "/segmentos")


@router.post("/segmentos/{segment_id}/regras")
async def segment_rules_save(request: Request, segment_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    segment = db.get(Segment, segment_id)
    if not segment: raise HTTPException(404)
    form = await request.form()
    fields, operators, values = form.getlist("rule_field"), form.getlist("rule_operator"), form.getlist("rule_value")
    db.execute(delete(SegmentRule).where(SegmentRule.segment_id == segment.id))
    mode = "any" if str(form.get("group_mode")) == "any" else "all"
    valid_fields = {"city", "neighborhood", "source", "name", "pet_species", "pet_breed", "whatsapp_confirmed", "consent_research"}
    for index, field in enumerate(fields):
        if field not in valid_fields: continue
        operator = operators[index] if index < len(operators) else "equals"
        value = values[index] if index < len(values) else ""
        db.add(SegmentRule(segment_id=segment.id, position=index + 1, field=field, operator=operator, value=str(value).strip(), group_mode=mode))
    db.flush(); result = refresh_rule_segment(db, segment); db.commit()
    flash(request, f"Regras salvas: {result['matched']} correspondência(s), {result['entered']} entrada(s) e {result['left']} saída(s).")
    return redirect(f"/segmentos?segment_id={segment.id}&tab=regras")


@router.post("/segmentos/{segment_id}/atualizar-publico")
def segment_refresh(request: Request, segment_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    segment = db.get(Segment, segment_id)
    if not segment: raise HTTPException(404)
    result = refresh_rule_segment(db, segment); db.commit()
    flash(request, f"Público atualizado: {result['matched']} lead(s) atendem às regras.")
    return redirect(f"/segmentos?segment_id={segment.id}&tab=publico")


def _clock_minutes(value: object, fallback: int) -> int:
    raw = str(value or "").strip()
    try:
        hour, minute = [int(part) for part in raw.split(":", 1)]
        return max(0, min(1439, hour * 60 + minute))
    except (TypeError, ValueError):
        return fallback


@router.post("/segmentos/{segment_id}/automacoes/prever")
async def segment_automation_preview(request: Request, segment_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    form = await request.form()
    questionnaire_ids = [_int(value, 0) for value in form.getlist("questionnaire_ids") if _int(value, 0)]
    if not questionnaire_ids:
        questionnaire_ids = [_int(form.get("questionnaire_id"), 0)]
    repeat_policy = str(form.get("repeat_policy") or "cooldown")
    automation = SegmentAutomation(
        id=0,
        segment_id=segment_id,
        questionnaire_id=questionnaire_ids[0] if questionnaire_ids else 0,
        name="Prévia",
        sample_percent=max(1, min(100, _int(form.get("sample_percent"), 100))),
        sample_mode=str(form.get("sample_mode") or "per_cycle"),
        exclude_previous=repeat_policy == "never",
        repeat_policy=repeat_policy,
        cooldown_days=max(1, _int(form.get("cooldown_days"), 14)),
        block_while_active=_bool(form, "block_while_active"),
        require_confirmed=_bool(form, "require_confirmed"),
        selection_strategy=str(form.get("selection_strategy") or "single"),
    )
    leads, stats = automation_candidates(db, automation)
    return JSONResponse({
        "ok": True,
        "stats": stats,
        "selected_questionnaires": len(questionnaire_ids),
        "examples": [{"name": lead.name, "phone": lead.phone_normalized or "WhatsApp via LID"} for lead in leads[:5]],
    })


@router.post("/segmentos/{segment_id}/automacoes")
async def segment_automation_create(request: Request, segment_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    segment = db.get(Segment, segment_id)
    if not segment:
        raise HTTPException(404)
    form = await request.form()
    questionnaire_ids = list(dict.fromkeys(_int(value, 0) for value in form.getlist("questionnaire_ids") if _int(value, 0)))
    if not questionnaire_ids:
        legacy_id = _int(form.get("questionnaire_id"), 0)
        questionnaire_ids = [legacy_id] if legacy_id else []
    valid_questionnaires: list[Questionnaire] = []
    for questionnaire_id in questionnaire_ids:
        questionnaire = db.get(Questionnaire, questionnaire_id)
        version = latest_published_version(db, questionnaire) if questionnaire else None
        config = version_config(version) if version else None
        if questionnaire and config and questionnaire.status == "active" and "whatsapp" in channels(config) and config.response_mode == "identified":
            valid_questionnaires.append(questionnaire)
    if not valid_questionnaires or len(valid_questionnaires) != len(questionnaire_ids):
        flash(request, "Selecione somente questionários identificados, publicados e disponíveis no WhatsApp.", "danger")
        return redirect(f"/segmentos?segment_id={segment.id}&tab=automacoes")

    system = db.get(SystemSetting, 1)
    zone_name = valid_timezone(user.timezone_name or (system.timezone_name if system else DEFAULT_TIMEZONE))
    trigger_type = str(form.get("trigger_type") or "campaign")
    if trigger_type not in {"campaign", "on_entry", "hybrid"}:
        trigger_type = "campaign"
    schedule_type = str(form.get("schedule_type") or "now")
    raw_date = str(form.get("scheduled_at") or "").strip()
    next_run = utcnow()
    if trigger_type == "campaign" and schedule_type in {"once", "recurring"} and raw_date:
        try:
            next_run = datetime.fromisoformat(raw_date).replace(tzinfo=ZoneInfo(zone_name)).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            flash(request, "Informe uma data e hora válidas.", "danger")
            return redirect(f"/segmentos?segment_id={segment.id}&tab=automacoes")

    recurring = schedule_type == "recurring" or trigger_type == "hybrid"
    recurrence_raw = form.get("recurrence_days_entry") if trigger_type == "hybrid" else form.get("recurrence_days")
    recurrence_days = max(1, _int(recurrence_raw, 30)) if recurring else None
    repeat_policy = str(form.get("repeat_policy") or "cooldown")
    if repeat_policy not in {"never", "cooldown", "allow"}:
        repeat_policy = "cooldown"
    selection_strategy = str(form.get("selection_strategy") or ("single" if len(valid_questionnaires) == 1 else "random_no_repeat"))
    if selection_strategy not in {"single", "random", "random_no_repeat", "round_robin"}:
        selection_strategy = "single"
    distribution_mode = str(form.get("distribution_mode") or "fixed")
    if distribution_mode not in {"fixed", "random", "uniform"}:
        distribution_mode = "fixed"

    automation = SegmentAutomation(
        segment_id=segment.id,
        questionnaire_id=valid_questionnaires[0].id,
        name=str(form.get("name") or f"{valid_questionnaires[0].name} · {segment.name}").strip(),
        trigger_type=trigger_type,
        schedule_type="recurring" if recurring else "once",
        scheduled_at=next_run if trigger_type == "campaign" else None,
        next_run_at=next_run if trigger_type == "campaign" else None,
        recurrence_days=recurrence_days,
        entry_delay_value=max(0, _int(form.get("entry_delay_value"), 0)),
        entry_delay_unit=str(form.get("entry_delay_unit") or "hours") if str(form.get("entry_delay_unit") or "hours") in {"minutes", "hours", "days"} else "hours",
        selection_strategy=selection_strategy,
        distribution_mode=distribution_mode,
        send_window_start=_clock_minutes(form.get("send_window_start"), 540),
        send_window_end=_clock_minutes(form.get("send_window_end"), 1020),
        timezone_name=zone_name,
        cooldown_days=max(1, _int(form.get("cooldown_days"), 14)),
        max_cycles=_int(form.get("max_cycles"), 0) if _int(form.get("max_cycles"), 0) > 0 else None,
        cancel_on_exit=_bool(form, "cancel_on_exit"),
        block_while_active=_bool(form, "block_while_active"),
        sample_percent=max(1, min(100, _int(form.get("sample_percent"), 100))),
        sample_mode=str(form.get("sample_mode") or "per_cycle") if str(form.get("sample_mode") or "per_cycle") in {"fixed", "per_cycle"} else "per_cycle",
        exclude_previous=repeat_policy == "never",
        repeat_policy=repeat_policy,
        require_confirmed=_bool(form, "require_confirmed"),
        created_by_id=user.id,
    )
    db.add(automation)
    db.flush()
    for position, questionnaire in enumerate(valid_questionnaires, start=1):
        db.add(SegmentAutomationQuestionnaire(
            automation_id=automation.id,
            questionnaire_id=questionnaire.id,
            position=position,
            weight=1,
        ))
    db.flush()

    if trigger_type == "campaign" and next_run <= utcnow():
        result = run_segment_automation(db, automation)
        flash(request, f"Automação criada e {result['created']} pesquisa(s) agendada(s).")
    elif trigger_type in {"on_entry", "hybrid"}:
        result = sync_segment_enrollments(db, automation)
        flash(request, f"Automação inteligente ativada para {result['enrolled']} lead(s). Novas entradas serão inscritas automaticamente pelo worker.")
    else:
        flash(request, "Automação programada. O worker fará o disparo no horário configurado.")
    db.commit()
    return redirect(f"/segmentos?segment_id={segment.id}&tab=automacoes")


@router.post("/segmentos/automacoes/{automation_id}/status")
async def segment_automation_status(request: Request, automation_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    row = db.get(SegmentAutomation, automation_id)
    if not row: raise HTTPException(404)
    form = await request.form(); target = str(form.get("status") or "paused")
    if target not in {"active", "paused", "cancelled"}: target = "paused"
    row.status = target
    if target == "active" and row.trigger_type == "campaign" and not row.next_run_at:
        row.next_run_at = utcnow()
    if target == "cancelled":
        db.execute(
            update(SegmentAutomationEnrollment)
            .where(
                SegmentAutomationEnrollment.automation_id == row.id,
                SegmentAutomationEnrollment.status.in_(["active", "blocked"]),
            )
            .values(status="cancelled", next_due_at=None, blocked_reason="Automação cancelada pelo operador.")
        )
        scheduled = db.scalars(select(SurveyExecution).where(
            SurveyExecution.source == f"segment_automation:{row.id}",
            SurveyExecution.status == "scheduled",
        )).all()
        for execution in scheduled:
            execution.status = "cancelled"
            execution.test_label = "Automação de segmento cancelada pelo operador."
    db.commit(); flash(request, "Automação atualizada.")
    return redirect(f"/segmentos?segment_id={row.segment_id}&tab=automacoes")


@router.post("/segmentos/{segment_id}/editar")
async def segment_update(request: Request, segment_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    row = db.get(Segment, segment_id)
    if not row:
        raise HTTPException(404)
    form = await request.form()
    row.name = str(form.get("name") or row.name).strip()
    row.description = str(form.get("description") or "").strip() or None
    row.kind = str(form.get("kind") or "manual")
    row.color = str(form.get("color") or "#0f766e")
    row.keywords_json = json.dumps([item.strip() for item in str(form.get("keywords") or "").split(",") if item.strip()], ensure_ascii=False)
    row.min_confidence = _float(form.get("min_confidence"), 0.82)
    row.active = _bool(form, "active")
    db.commit()
    flash(request, "Segmento atualizado.")
    return redirect(f"/segmentos?segment_id={segment_id}&tab=regras")


@router.get("/alertas")
def alerts_page(request: Request, status: str = "open", db: Session = Depends(get_db)):
    user = require_user(request, db)
    query = select(Alert).options(selectinload(Alert.lead), selectinload(Alert.questionnaire))
    city_ids = _user_city_ids(user)
    if city_ids is not None:
        query = query.join(Lead).where(Lead.city_id.in_(city_ids))
    if status:
        query = query.where(Alert.status == status)
    rows = db.scalars(query.order_by(Alert.created_at.desc())).all()
    return request.app.state.templates.TemplateResponse(request, "alerts.html", ctx(request, db, alerts=rows, status=status))


@router.get("/alertas/{alert_id}")
def alert_detail(request: Request, alert_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = db.scalar(select(Alert).options(selectinload(Alert.lead), selectinload(Alert.questionnaire)).where(Alert.id == alert_id))
    if not row:
        raise HTTPException(404)
    if row.lead:
        _require_city_access(user, row.lead.city_id)
    elif _user_city_ids(user) is not None:
        raise HTTPException(403, "Alertas anônimos agregados não pertencem a uma cidade específica.")
    return request.app.state.templates.TemplateResponse(request, "alert_detail.html", ctx(request, db, alert=row))


@router.post("/alertas/{alert_id}/encerrar")
async def alert_close(request: Request, alert_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = db.get(Alert, alert_id)
    if not row:
        raise HTTPException(404)
    lead = db.get(Lead, row.lead_id) if row.lead_id else None
    if lead:
        _require_city_access(user, lead.city_id)
    elif _user_city_ids(user) is not None:
        raise HTTPException(403)
    form = await request.form()
    row.status = "closed"
    row.closed_at = utcnow()
    row.closing_note = str(form.get("closing_note") or "").strip() or None
    db.commit()
    flash(request, "Alerta encerrado.")
    return redirect("/alertas")


@router.get("/conversas")
def conversations_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    query = authorized_conversations(user).where(Conversation.last_message_at.is_not(None))
    candidates = db.scalars(query.order_by(Conversation.pinned.desc(), Conversation.last_message_at.desc().nullslast(), Conversation.id.desc()).limit(41)).all()
    rows = candidates[:40]
    initial_next_before = None
    if len(candidates) > 40 and rows[-1].last_message_at:
        last = rows[-1]
        initial_next_before = f"{1 if last.pinned else 0}|{last.last_message_at.isoformat()}|{last.id}"
    assignee_ids = {row.assigned_user_id for row in rows if row.assigned_user_id}
    assignees = {item.id: item.name for item in db.scalars(select(User).where(User.id.in_(assignee_ids))).all()} if assignee_ids else {}
    return request.app.state.templates.TemplateResponse(request, "conversations.html", ctx(
        request, db, conversations=rows, initial_next_before=initial_next_before, assignees=assignees,
        status_label=status_label, selected_conversation=None,
    ))


@router.get("/conversas/{conversation_id}")
def conversation_detail(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = db.scalar(authorized_conversations(user).where(Conversation.id == conversation_id))
    if not row:
        raise HTTPException(404)
    list_candidates = db.scalars(authorized_conversations(user).where(Conversation.last_message_at.is_not(None)).order_by(Conversation.pinned.desc(), Conversation.last_message_at.desc().nullslast(), Conversation.id.desc()).limit(41)).all()
    conversation_rows = list_candidates[:40]
    initial_next_before = None
    if len(list_candidates) > 40 and conversation_rows[-1].last_message_at:
        last_row = conversation_rows[-1]
        initial_next_before = f"{1 if last_row.pinned else 0}|{last_row.last_message_at.isoformat()}|{last_row.id}"
    initial_message_limit = 30
    messages = list(reversed(db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == row.id).order_by(ConversationMessage.id.desc()).limit(initial_message_limit + 1)).all()))
    initial_has_more = len(messages) > initial_message_limit
    if initial_has_more:
        messages = messages[-initial_message_limit:]
    row.unread_count = 0
    row.last_read_message_id = messages[-1].id if messages else row.last_read_message_id
    db.commit()
    message_ids = [message.id for message in messages]
    media_rows = db.scalars(select(MediaAsset).where(MediaAsset.conversation_message_id.in_(message_ids))).all() if message_ids else []
    media_by_message = {asset.conversation_message_id: asset for asset in media_rows}
    reaction_rows = db.scalars(select(ConversationReaction).where(ConversationReaction.conversation_message_id.in_(message_ids))).all() if message_ids else []
    reactions_by_message: dict[int, dict[str, dict]] = {}
    for reaction in reaction_rows:
        grouped = reactions_by_message.setdefault(reaction.conversation_message_id, {})
        item = grouped.setdefault(reaction.emoji, {"count": 0, "mine": False})
        item["count"] += 1
        item["mine"] = item["mine"] or bool(reaction.actor_type == "user" and reaction.user_id == user.id)
    notes = db.scalars(select(ConversationNote).where(ConversationNote.conversation_id == row.id).order_by(ConversationNote.created_at.desc()).limit(8)).all()
    user_ids = {message.sender_user_id for message in messages if message.sender_user_id} | {item.assigned_user_id for item in conversation_rows if item.assigned_user_id}
    user_names = {item.id: item.name for item in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    active_users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
    return request.app.state.templates.TemplateResponse(
        request,
        "conversation_detail.html",
        ctx(request, db, conversation=row, selected_conversation=row, conversations=conversation_rows,
            initial_next_before=initial_next_before, messages=messages, media_by_message=media_by_message,
            reactions_by_message=reactions_by_message, notes=notes, initial_has_more=initial_has_more,
            user_names=user_names, assignees=user_names, active_users=active_users,
            status_label=status_label, quiet=quiet_window(db.get(SystemSetting, 1))),
    )


@router.post("/conversas/{conversation_id}/acao")
async def conversation_action(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = db.scalar(authorized_conversations(user).where(Conversation.id == conversation_id))
    if not row:
        raise HTTPException(404)
    form = await request.form()
    action = str(form.get("action") or "").strip()
    if action == "pin":
        row.pinned = True
    elif action == "unpin":
        row.pinned = False
    elif action == "mark_unread":
        row.unread_count = max(1, row.unread_count or 0)
    elif action == "mark_read":
        row.unread_count = 0
        latest_id = db.scalar(select(func.max(ConversationMessage.id)).where(ConversationMessage.conversation_id == row.id))
        row.last_read_message_id = latest_id or row.last_read_message_id
    elif action in {"close", "open", "archive"}:
        row.internal_status = {"close": "closed", "open": "open", "archive": "archived"}[action]
        row.status = "closed" if action in {"close", "archive"} else "open"
    elif action == "assign":
        assigned_id = _int(form.get("assigned_user_id"), 0) or None
        if assigned_id:
            target = db.get(User, assigned_id)
            if not target or not target.active:
                return JSONResponse({"ok": False, "error": "Usuário responsável inválido."}, status_code=422)
        row.assigned_user_id = assigned_id
    else:
        return JSONResponse({"ok": False, "error": "Ação de conversa inválida."}, status_code=422)
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        assigned = db.get(User, row.assigned_user_id) if row.assigned_user_id else None
        return JSONResponse({"ok": True, "pinned": row.pinned, "unread": row.unread_count,
                             "status": row.internal_status, "status_label": status_label(row.internal_status),
                             "assigned_user_id": row.assigned_user_id, "assigned_name": assigned.name if assigned else None})
    return redirect(f"/conversas/{conversation_id}")


@router.post("/conversas/{conversation_id}/responder")
async def conversation_reply(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = db.scalar(authorized_conversations(user).where(Conversation.id == conversation_id))
    if not row:
        raise HTTPException(404)
    form = await request.form()
    text = str(form.get("text") or "").strip()
    message_type = str(form.get("message_type") or "text")
    recipient = row.phone_normalized or row.whatsapp_lid
    wants_json = request.headers.get("X-Requested-With") == "fetch"
    if not recipient:
        if wants_json:
            return JSONResponse({"ok": False, "error": "A conversa não possui telefone ou identificador WhatsApp válido."}, status_code=422)
        flash(request, "A conversa não possui telefone ou identificador WhatsApp válido.", "danger")
        return redirect(f"/conversas/{conversation_id}")
    reply_to_id = _int(form.get("reply_to_message_id"), 0) or None
    reply_to = db.get(ConversationMessage, reply_to_id) if reply_to_id else None
    if reply_to and reply_to.conversation_id != row.id: reply_to = None
    if _bool(form, "use_signature") and user.chat_signature_enabled and user.chat_signature:
        signature = user.chat_signature.strip()
        if signature and signature not in text: text = (text.rstrip() + "\n\n" + signature).strip()
    media_payload = {}
    if message_type in {"image", "audio", "video", "document"}:
        media_payload = {
            "url": str(form.get("media_url") or "").strip(),
            "file_name": str(form.get("file_name") or "").strip(),
        }
    elif message_type == "location":
        latitude_raw = str(form.get("latitude") or "").strip()
        longitude_raw = str(form.get("longitude") or "").strip()
        if not latitude_raw or not longitude_raw:
            flash(request, "Informe latitude e longitude.", "danger")
            return redirect(f"/conversas/{conversation_id}")
        media_payload = {
            "latitude": _float(latitude_raw, 0),
            "longitude": _float(longitude_raw, 0),
            "address": str(form.get("address") or "").strip(),
            "title": text or "Localização",
        }
        if not (-90 <= media_payload["latitude"] <= 90 and -180 <= media_payload["longitude"] <= 180):
            flash(request, "Informe latitude e longitude válidas.", "danger")
            return redirect(f"/conversas/{conversation_id}")
    elif message_type == "contact":
        media_payload = {
            "name": str(form.get("contact_name") or text or "").strip(),
            "phone": str(form.get("contact_phone") or "").strip(),
        }
        if not media_payload["name"] or not normalize_phone(media_payload["phone"]):
            flash(request, "Informe nome e telefone válidos para o contato.", "danger")
            return redirect(f"/conversas/{conversation_id}")
    upload = form.get("attachment")
    if upload and getattr(upload, "filename", ""):
        mime = str(getattr(upload, "content_type", "") or "")
        if mime.startswith("image/"): message_type = "image"
        elif mime.startswith("audio/"): message_type = "audio"
        elif mime.startswith("video/"): message_type = "video"
        else: message_type = "document"
    if recipient and (text or media_payload.get("url") or message_type in {"location", "contact"} or (upload and getattr(upload, "filename", ""))):
        message = add_conversation_message(db, row, direction="out", content=text or f"[{message_type}]", content_type=message_type, status="queued", sender_user_id=user.id, reply_to_message_id=reply_to.id if reply_to else None, quoted_content=(reply_to.content if reply_to else None), reference_external_id=(reply_to.external_id if reply_to else None))
        asset = None
        if upload and getattr(upload, "filename", ""):
            try:
                asset = store_outbound_media(db, await upload.read(), file_name=upload.filename, mime_type=getattr(upload, "content_type", None), media_type=message_type, conversation_message_id=message.id, caption=text)
            except ValueError as exc:
                db.rollback()
                if wants_json:
                    return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
                flash(request, str(exc), "danger")
                return redirect(f"/conversas/{conversation_id}")
        db.add(MessageQueue(
            lead_id=row.lead_id,
            kind="human",
            phone=recipient,
            payload_text=text or f"[{message_type}]",
            message_type=message_type,
            buttons_json="[]",
            media_payload_json=json.dumps(media_payload, ensure_ascii=False),
            status="pending",
            available_at=utcnow(),
            conversation_message_id=message.id,
            media_asset_id=asset.id if asset else None,
            reply_external_id=reply_to.external_id if reply_to else None,
        ))
        db.commit()
        flash(request, "Mensagem colocada na fila de envio.")
        if wants_json:
            return JSONResponse({"ok": True, "message_id": message.id, "status": message.status})
    elif wants_json:
        return JSONResponse({"ok": False, "error": "Digite uma mensagem ou escolha um arquivo."}, status_code=422)
    return redirect(f"/conversas/{conversation_id}")


@router.post("/conversas/{conversation_id}/reagir")
async def conversation_react(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db); row = db.scalar(authorized_conversations(user).where(Conversation.id == conversation_id))
    if not row: raise HTTPException(404)
    form = await request.form(); message = db.get(ConversationMessage, _int(form.get("message_id"), 0)); emoji = str(form.get("emoji") or "").strip()[:24]
    remove_reaction = _bool(form, "remove")
    if not message or message.conversation_id != row.id or not message.external_id or (not emoji and not remove_reaction):
        return JSONResponse({"ok": False, "error": "Mensagem ou emoji inválido."}, status_code=422)
    existing = db.scalars(select(ConversationReaction).where(ConversationReaction.conversation_message_id == message.id, ConversationReaction.actor_type == "user", ConversationReaction.user_id == user.id)).all()
    config = db.get(ZapiConfig, 1); result = send_reaction(config, row.phone_normalized or row.whatsapp_lid or "", message.external_id, "" if remove_reaction else emoji)
    if not result.ok: return JSONResponse({"ok": False, "error": result.message}, status_code=422)
    for item in existing:
        db.delete(item)
    if not remove_reaction:
        db.add(ConversationReaction(conversation_message_id=message.id, emoji=emoji, actor_type="user", user_id=user.id, external_id=result.external_id))
    db.commit(); return JSONResponse({"ok": True, "emoji": None if remove_reaction else emoji})


@router.post("/conversas/{conversation_id}/mensagens/{message_id}/tentar-novamente")
def conversation_message_retry(request: Request, conversation_id: int, message_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    row = db.scalar(authorized_conversations(user).where(Conversation.id == conversation_id))
    if not row:
        raise HTTPException(404)
    message = db.scalar(select(ConversationMessage).where(ConversationMessage.id == message_id, ConversationMessage.conversation_id == row.id))
    queue = db.scalar(select(MessageQueue).where(MessageQueue.conversation_message_id == message_id).order_by(MessageQueue.id.desc()))
    if not message or not queue or message.direction != "out" or message.status != "failed":
        return JSONResponse({"ok": False, "error": "Esta mensagem não pode ser reenviada."}, status_code=422)
    queue.status = "pending"; queue.attempt = 0; queue.available_at = utcnow(); queue.error_message = None
    message.status = "queued"; message.status_at = utcnow(); message.error_message = None
    db.commit()
    return JSONResponse({"ok": True, "status": "queued"})


@router.post("/conversas/{conversation_id}/nota")
async def conversation_note(request: Request, conversation_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db); row = db.scalar(authorized_conversations(user).where(Conversation.id == conversation_id))
    if not row: raise HTTPException(404)
    form = await request.form(); content = str(form.get("content") or "").strip()
    if content: db.add(ConversationNote(conversation_id=row.id, user_id=user.id, content=content[:5000])); db.commit()
    return redirect(f"/conversas/{conversation_id}")


@router.get("/midias/{media_id}")
def media_file(request: Request, media_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    asset = db.get(MediaAsset, media_id)
    if asset and asset.conversation_message_id:
        conversation_id = db.scalar(select(ConversationMessage.conversation_id).where(ConversationMessage.id == asset.conversation_message_id))
        if not conversation_id or not db.scalar(authorized_conversations(user).where(Conversation.id == conversation_id)):
            raise HTTPException(404)
    path = local_media_path(asset) if asset else None
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=asset.mime_type, filename=asset.file_name or path.name, content_disposition_type="inline")


def _anonymous_structure_rows(db: Session) -> list[dict]:
    """Agrupa respostas anônimas por cidade/unidade, sempre pelo piso de anonimato (I4)."""
    combos = db.execute(
        select(SurveyExecution.city_id, SurveyExecution.device_id)
        .where(SurveyExecution.lead_id.is_(None), SurveyExecution.is_test.is_(False))
        .distinct()
    ).all()
    rows = []
    for city_id, device_id in combos:
        city = db.get(City, city_id) if city_id else None
        device = db.get(Device, device_id) if device_id else None
        label = city.name if city else "Sem unidade"
        if device:
            label = f"{label} · {device.name}"
        rows.append({"label": label, "result": anonymous_aggregate(db, city_id=city_id, device_id=device_id)})
    return sorted(rows, key=lambda item: item["label"])


@router.get("/relatorios")
def reports(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    questionnaire_rows = db.execute(
        select(
            Questionnaire.name,
            func.sum(case((SurveyExecution.is_test.is_(False), 1), else_=0)),
            func.sum(case((((SurveyExecution.status == "completed") & SurveyExecution.is_test.is_(False)), 1), else_=0)),
        )
        .outerjoin(SurveyExecution).group_by(Questionnaire.id).order_by(Questionnaire.name)
    ).all()
    score_rows = db.execute(
        select(Questionnaire.name, func.avg(SurveyAnswer.numeric_value))
        .join(SurveyExecution, SurveyExecution.questionnaire_id == Questionnaire.id)
        .join(SurveyAnswer, SurveyAnswer.execution_id == SurveyExecution.id)
        .where(SurveyAnswer.numeric_value.is_not(None), SurveyExecution.is_test.is_(False))
        .group_by(Questionnaire.id)
    ).all()
    source_rows = db.execute(select(Lead.source, func.count(Lead.id)).where(Lead.source != "laboratory").group_by(Lead.source)).all()
    structure_rows = _anonymous_structure_rows(db)
    return request.app.state.templates.TemplateResponse(request, "reports.html", ctx(request, db, questionnaire_rows=questionnaire_rows, score_rows=score_rows, source_rows=source_rows, structure_rows=structure_rows))


@router.get("/dispositivos")
def devices_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    query = select(Device).options(selectinload(Device.city)).order_by(Device.name)
    city_ids = _user_city_ids(user)
    if city_ids is not None:
        query = query.where(Device.city_id.in_(city_ids))
    rows = db.scalars(query).all()
    questionnaires = db.scalars(select(Questionnaire).where(Questionnaire.status == "active").order_by(Questionnaire.name)).all()
    entry_flows = db.scalars(select(EntryFlow).where(EntryFlow.status == "active").order_by(EntryFlow.name)).all()
    cities = db.scalars(select(City).order_by(City.name)).all()
    return request.app.state.templates.TemplateResponse(request, "devices.html", ctx(request, db, devices=rows, questionnaires=questionnaires, entry_flows=entry_flows, cities=cities))


@router.post("/dispositivos")
async def device_create(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    form = await request.form()
    row = Device(
        name=str(form.get("name") or "Novo ponto de coleta").strip(),
        city_id=_int(form.get("city_id"), 0) or None,
        token=secrets.token_urlsafe(24),
        mode=str(form.get("mode") or "kiosk"),
        allow_anonymous=_bool(form, "allow_anonymous"),
        default_questionnaire_id=_int(form.get("default_questionnaire_id"), 0) or None,
        default_entry_flow_id=_int(form.get("default_entry_flow_id"), 0) or None,
        address=str(form.get("address") or "").strip() or None,
        latitude=_float(form.get("latitude"), 0) or None,
        longitude=_float(form.get("longitude"), 0) or None,
    )
    db.add(row)
    db.commit()
    flash(request, "Ponto de coleta criado.")
    return redirect("/dispositivos")

@router.post("/dispositivos/{device_id}/editar")
async def device_update(request: Request, device_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    row = db.get(Device, device_id)
    if not row:
        raise HTTPException(404)
    form = await request.form()
    row.name = str(form.get("name") or row.name).strip()
    row.mode = str(form.get("mode") or row.mode)
    row.city_id = _int(form.get("city_id"), 0) or None
    row.default_questionnaire_id = _int(form.get("default_questionnaire_id"), 0) or None
    row.default_entry_flow_id = _int(form.get("default_entry_flow_id"), 0) or None
    row.allow_anonymous = _bool(form, "allow_anonymous")
    row.active = _bool(form, "active")
    row.hero_title = str(form.get("hero_title") or row.hero_title).strip()
    row.hero_text = str(form.get("hero_text") or row.hero_text).strip()
    row.primary_color = str(form.get("primary_color") or row.primary_color)
    row.address = str(form.get("address") or "").strip() or None
    row.latitude = _float(form.get("latitude"), 0) or None
    row.longitude = _float(form.get("longitude"), 0) or None
    if _bool(form, "rotate_token"):
        row.token = secrets.token_urlsafe(24)
    db.commit()
    flash(request, "Ponto de coleta atualizado.")
    return redirect("/dispositivos")


@router.post("/cidades")
async def city_create(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    form = await request.form()
    name = str(form.get("name") or "").strip()
    state = str(form.get("state") or "GO").strip().upper()[:2]
    if not name:
        flash(request, "Informe o nome da cidade.", "danger")
        return redirect("/dispositivos")
    existing = db.scalar(select(City).where(func.lower(City.name) == name.casefold(), City.state == state))
    if existing:
        existing.active = True
        flash(request, "A cidade já existia e foi reativada.")
    else:
        db.add(City(name=name, state=state, active=True))
        flash(request, "Cidade adicionada.")
    db.commit()
    return redirect("/dispositivos")


@router.post("/cidades/{city_id}/editar")
async def city_update(request: Request, city_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    row = db.get(City, city_id)
    if not row:
        raise HTTPException(404)
    form = await request.form()
    row.name = str(form.get("name") or row.name).strip()
    row.state = str(form.get("state") or row.state).strip().upper()[:2]
    row.active = _bool(form, "active")
    db.commit()
    flash(request, "Cidade atualizada.")
    return redirect("/dispositivos")


@router.get("/configuracoes")
def settings_page(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    zapi = db.get(ZapiConfig, 1)
    transcription = db.get(TranscriptionConfig, 1)
    detected_base_url = _request_public_origin(request)
    saved_base_url, public_base_error = normalize_public_base_url(zapi.public_base_url)
    environment_base_url, _ = normalize_public_base_url(settings.public_base_url)
    detected_is_public = is_public_https_origin(detected_base_url)
    public_base_form_value = detected_base_url if detected_is_public else (saved_base_url or environment_base_url or detected_base_url or "")
    preview_base_url = public_base_form_value if is_public_https_origin(public_base_form_value) else None
    preview_urls = (
        webhook_urls_from_base(preview_base_url, zapi.webhook_secret)
        if preview_base_url
        else {}
    )
    return request.app.state.templates.TemplateResponse(
        request,
        "settings.html",
        ctx(
            request,
            db,
            zapi=zapi,
            webhook_urls=preview_urls,
            detected_base_url=detected_base_url,
            detected_is_public=detected_is_public,
            public_base_form_value=public_base_form_value,
            public_base_error=public_base_error,
            public_origin_changed=bool(detected_is_public and saved_base_url and saved_base_url != detected_base_url),
            zapi_send_endpoint=send_endpoint_preview(zapi),
            redis_info=redis_status(),
            transcription=transcription,
            transcription_info=transcription_diagnostics(transcription),
            transcription_stats={
                status: db.scalar(select(func.count(TranscriptionJob.id)).where(TranscriptionJob.status == status)) or 0
                for status in ("pending", "processing", "completed", "failed")
            },
            webhook_stats=db.execute(
                select(WebhookEvent.event_type, func.count(WebhookEvent.id))
                .group_by(WebhookEvent.event_type)
                .order_by(WebhookEvent.event_type)
            ).all(),
            ignored_webhooks=db.scalar(
                select(func.count(WebhookEvent.id)).where(WebhookEvent.ignored_reason.is_not(None))
            ) or 0,
        ),
    )


@router.post("/configuracoes/geral")
async def settings_general(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    form = await request.form()
    row = db.get(SystemSetting, 1)
    row.organization_name = str(form.get("organization_name") or row.organization_name).strip()
    row.product_name = str(form.get("product_name") or row.product_name).strip()
    row.default_country_code = str(form.get("default_country_code") or "55").strip()
    row.quiet_start_hour = _int(form.get("quiet_start_hour"), 20)
    row.quiet_end_hour = _int(form.get("quiet_end_hour"), 8)
    row.contact_cap_count = _int(form.get("contact_cap_count"), 3)
    row.contact_cap_days = _int(form.get("contact_cap_days"), 14)
    row.anonymous_minimum = _int(form.get("anonymous_minimum"), 7)
    row.allow_unknown_whatsapp_onboarding = _bool(form, "allow_unknown_whatsapp_onboarding")
    row.primary_color = _hex_color(form.get("primary_color"), row.primary_color or "#0f766e")
    row.secondary_color = _hex_color(form.get("secondary_color"), row.secondary_color or "#2563eb")
    row.sidebar_color = _hex_color(form.get("sidebar_color"), row.sidebar_color or "#071a2b")
    row.footer_text = str(form.get("footer_text") or "").strip() or None
    row.timezone_name = valid_timezone(form.get("timezone_name"), row.timezone_name or DEFAULT_TIMEZONE)
    db.commit()
    flash(request, "Configurações gerais atualizadas.")
    return redirect("/configuracoes")


@router.post("/configuracoes/transcricao")
async def settings_transcription(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    form = await request.form()
    row = db.get(TranscriptionConfig, 1)
    if not row:
        row = TranscriptionConfig(id=1)
        db.add(row)
    row.enabled = _bool(form, "enabled")
    row.transcribe_received = _bool(form, "transcribe_received")
    row.transcribe_sent = _bool(form, "transcribe_sent")
    row.segment_received_text = _bool(form, "segment_received_text")
    row.segment_transcripts = _bool(form, "segment_transcripts")
    row.language = str(form.get("language") or "pt").strip()[:12] or "pt"
    row.threads = max(1, min(8, _int(form.get("threads"), 2)))
    row.max_duration_seconds = max(30, min(3600, _int(form.get("max_duration_seconds"), 600)))
    row.executable_path = str(form.get("executable_path") or "").strip() or None
    row.model_path = str(form.get("model_path") or "").strip() or None
    row.ffmpeg_path = str(form.get("ffmpeg_path") or "").strip() or None
    if row.transcribe_received or row.transcribe_sent:
        db.execute(update(MediaAsset).where(MediaAsset.type == "audio", MediaAsset.transcription_status == "skipped").values(transcription_status="not_requested"))
    db.commit()
    diagnostic = transcription_diagnostics(row)
    flash(request, "Configuração de transcrição salva. " + diagnostic["message"], "success" if diagnostic["ready"] or not row.enabled else "warning")
    return redirect("/configuracoes")


@router.post("/configuracoes/transcricao/reprocessar-falhas")
def transcription_retry_failed(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    rows = db.scalars(select(TranscriptionJob).where(TranscriptionJob.status == "failed")).all()
    for row in rows:
        row.status = "pending"; row.attempt = 0; row.available_at = utcnow(); row.error_message = None
        asset = db.get(MediaAsset, row.media_asset_id)
        if asset: asset.transcription_status = "pending"
    db.commit()
    flash(request, f"{len(rows)} transcrição(ões) devolvida(s) à fila.")
    return redirect("/configuracoes")


@router.post("/configuracoes/marca")
async def settings_branding(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    form = await request.form()
    row = db.get(SystemSetting, 1)
    changed = False
    try:
        for role in ("horizontal", "vertical", "icon"):
            if form.get(f"remove_{role}"):
                remove_logo(role)
                setattr(row, f"logo_{role}_file", None)
                changed = True
            upload = form.get(f"logo_{role}")
            if upload and getattr(upload, "filename", ""):
                preview = form.get(f"logo_{role}_preview")
                preview_data = await preview.read() if preview and getattr(preview, "filename", "") else None
                stored = save_logo(role, upload.filename, await upload.read(), preview_data)
                setattr(row, f"logo_{role}_file", stored)
                changed = True
    except ValueError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
        return redirect("/configuracoes")
    if changed:
        row.branding_version = (row.branding_version or 0) + 1
        db.commit()
        flash(request, "Identidade visual atualizada. O ícone do PWA e o favicon também foram preparados.")
    else:
        flash(request, "Selecione ao menos uma logo ou marque uma remoção.", "warning")
    return redirect("/configuracoes")


@router.post("/configuracoes/zapi")
async def settings_zapi(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    form = await request.form()
    row = db.get(ZapiConfig, 1)
    endpoint_mode = str(form.get("send_endpoint_mode") or "automatic").strip()
    if endpoint_mode not in {"automatic", "manual"}:
        endpoint_mode = "automatic"
    manual_endpoint = str(form.get("manual_send_endpoint") or "").strip()
    if endpoint_mode == "manual":
        manual_endpoint, endpoint_error = normalize_manual_send_endpoint(manual_endpoint)
        if endpoint_error:
            flash(request, endpoint_error, "danger")
            return redirect("/configuracoes")
    row.send_endpoint_mode = endpoint_mode
    if endpoint_mode == "manual" or manual_endpoint:
        row.manual_send_endpoint = manual_endpoint or None
    row.enabled = _bool(form, "enabled")
    if str(form.get("instance_id") or "").strip(): row.instance_id = str(form.get("instance_id")).strip()
    if str(form.get("token") or "").strip(): row.token = str(form.get("token")).strip()
    if str(form.get("client_token") or "").strip(): row.client_token = str(form.get("client_token")).strip()
    row.use_buttons = _bool(form, "use_buttons")
    row.button_terms_accepted = _bool(form, "button_terms_accepted")
    row.simulate_when_disabled = _bool(form, "simulate_when_disabled")
    row.notify_sent_by_me = _bool(form, "notify_sent_by_me")
    row.auto_read_message = _bool(form, "auto_read_message")
    row.download_received_media = _bool(form, "download_received_media")
    row.max_media_mb = max(1, min(200, _int(form.get("max_media_mb"), 50)))
    row.media_retention_days = max(30, min(3650, _int(form.get("media_retention_days"), 365)))
    submitted_base_url = str(form.get("public_base_url") or "").strip()
    detected_base_url = _request_public_origin(request)
    environment_base_url, _ = normalize_public_base_url(settings.public_base_url)
    normalized_base_url, public_base_error = normalize_public_base_url(submitted_base_url)
    repaired_from_current_domain = False
    if public_base_error or not normalized_base_url:
        normalized_base_url = detected_base_url or environment_base_url
        repaired_from_current_domain = bool(normalized_base_url)
    if public_base_error and not normalized_base_url:
        flash(request, public_base_error, "danger")
        return redirect("/configuracoes")
    row.public_base_url = normalized_base_url
    db.commit()
    if repaired_from_current_domain:
        flash(request, "Configuração salva. O endereço dos webhooks foi ajustado automaticamente para o domínio atual desta aplicação.")
    else:
        flash(request, "Configuração Z-API salva. Campos secretos vazios preservam os valores atuais.")
    return redirect("/configuracoes")


@router.post("/configuracoes/zapi/testar")
def settings_zapi_test(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    row = db.get(ZapiConfig, 1)
    result = run_diagnostics(row)
    payload = result.payload or {}
    row.connected = bool(payload.get("connected"))
    row.remote_webhooks_ok = bool(next((item.get("ok") for item in payload.get("checks", []) if item.get("code") == "webhooks"), False))
    device = payload.get("device") or {}
    row.device_name = str(device.get("name") or "")[:160] or None
    row.device_phone = str(device.get("phone") or "")[:40] or None
    row.last_check_at = utcnow()
    row.last_error = None if result.ok else result.message
    db.commit()
    flash(request, result.message, "success" if result.ok else "warning")
    return redirect("/configuracoes")


@router.post("/configuracoes/zapi/webhook")
def settings_zapi_webhook(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    row = db.get(ZapiConfig, 1)
    saved_base_url, public_base_error = normalize_public_base_url(row.public_base_url)
    detected_base_url = _request_public_origin(request)
    environment_base_url, _ = normalize_public_base_url(settings.public_base_url)
    repaired_base_url = saved_base_url or environment_base_url

    # Prefer the domain currently used to access the system when it is HTTPS.
    if is_public_https_origin(detected_base_url):
        repaired_base_url = detected_base_url
    elif public_base_error or not repaired_base_url:
        repaired_base_url = detected_base_url

    if not is_public_https_origin(repaired_base_url):
        message = (
            "Não foi possível detectar um endereço HTTPS público para esta aplicação. "
            "Abra o sistema pelo domínio público HTTPS ou informe esse domínio manualmente."
        )
        row.remote_webhooks_ok = False
        row.last_check_at = utcnow()
        row.last_error = message
        db.commit()
        flash(request, message, "danger")
        return redirect("/configuracoes")

    row.public_base_url = repaired_base_url
    result = configure_remote_webhooks(row)
    row.remote_webhooks_ok = bool(result.ok and (result.payload or {}).get("verified"))
    row.last_check_at = utcnow()
    row.last_error = None if result.ok else result.message
    db.commit()
    flash(request, result.message, "success" if result.ok else "danger")
    return redirect("/configuracoes")


@router.get("/configuracoes/zapi/qrcode")
def settings_zapi_qrcode(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    row = db.get(ZapiConfig, 1)
    result = get_qr_code_image(row)
    payload = result.payload or {}
    if payload.get("connected"):
        row.connected = True
        row.last_error = None
    elif not result.ok:
        row.last_error = result.message
    row.last_check_at = utcnow()
    db.commit()
    return JSONResponse({"ok": result.ok, "message": result.message, **payload}, status_code=200 if result.ok else 400)


@router.post("/operacao/processar")
def operation_run(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    stats = process_once()
    flash(request, f"Ciclo executado: {stats['executions']} pesquisas iniciadas, {stats['messages']} mensagens processadas, {stats['simulated']} simuladas.")
    return redirect("/")


@router.get("/entrevistador")
def interviewer_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator", "interviewer"})
    rows = []
    for questionnaire in db.scalars(select(Questionnaire).where(Questionnaire.status == "active").order_by(Questionnaire.name)).all():
        published = latest_published_version(db, questionnaire)
        if not published:
            continue
        published_config = version_config(published)
        if "interviewer" in channels(published_config):
            rows.append(SimpleNamespace(id=questionnaire.id, name=published_config.name, response_mode=published_config.response_mode))
    allowed_cities = {city.id for city in _cities_for_user(db, user)}
    entry_flows = [
        flow for flow in db.scalars(select(EntryFlow).where(EntryFlow.status == "active").order_by(EntryFlow.name)).all()
        if not json_list(flow.city_ids_json) or bool(allowed_cities.intersection({_int(value) for value in json_list(flow.city_ids_json)}))
    ]
    return request.app.state.templates.TemplateResponse(request, "interviewer.html", ctx(request, db, questionnaires=rows, entry_flows=entry_flows))


@router.post("/entrevistador/iniciar")
async def interviewer_start(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator", "interviewer"})
    form = await request.form()
    questionnaire = db.get(Questionnaire, _int(form.get("questionnaire_id")))
    if not questionnaire:
        raise HTTPException(404)
    published = latest_published_version(db, questionnaire)
    if not published:
        raise HTTPException(409, "Publique o questionário antes de aplicá-lo.")
    published_config = version_config(published)
    anonymous = _bool(form, "anonymous") or published_config.response_mode == "anonymous"
    lead = None
    if not anonymous:
        setting = db.get(SystemSetting, 1)
        normalized = normalize_phone(form.get("phone"), setting.default_country_code)
        lead = db.scalar(select(Lead).where(Lead.phone_normalized == normalized)) if normalized else None
        if not _bool(form, "consent_research"):
            flash(request, "Confirme o aceite para aplicar uma pesquisa identificada.", "danger")
            return redirect("/entrevistador")
        if not lead:
            lead = Lead(name=str(form.get("name") or "Entrevistado").strip(), phone=str(form.get("phone") or "").strip() or None, phone_normalized=normalized, source="interviewer", consent_research=True)
            db.add(lead)
            db.flush()
            schedule_for_new_lead(db, lead)
    execution = create_execution(db, questionnaire, lead=lead, channel="interviewer", source="interviewer")
    db.commit()
    return redirect(f"/aplicar/{execution.public_token}")


@router.get("/aplicar/{token}")
def apply_survey(request: Request, token: str, db: Session = Depends(get_db)):
    execution = db.scalar(select(SurveyExecution).options(selectinload(SurveyExecution.questionnaire_version).selectinload(QuestionnaireVersion.questions), selectinload(SurveyExecution.lead)).where(SurveyExecution.public_token == token))
    if not execution:
        raise HTTPException(404)
    questions = execution_questions(execution)
    question = advance_to_visible_question(db, execution)
    db.commit()
    return_url = request.session.get(f"survey_return:{execution.public_token}")
    if not return_url and execution.collection_session:
        return_url = f"/coleta/sessao/{execution.collection_session.public_token}"
    system = db.get(SystemSetting, 1)
    question_settings = _question_settings_json(question.settings_json) if question else {}
    if question_settings.get("placeholder"):
        question_settings["placeholder"] = render_message(str(question_settings["placeholder"]), execution.lead, execution, system)
    return request.app.state.templates.TemplateResponse(request, "apply_survey.html", ctx(request, db, execution=execution, survey_config=execution_config(execution), question=question, question_count=len(questions), question_options=display_options(question) if question else [], question_settings=question_settings, prompt=render_message(question_prompt(question), execution.lead, execution, system) if question else "", rendered_closing=render_message(execution_config(execution).closing_message, execution.lead, execution, system), return_url=return_url))


@router.post("/aplicar/{token}")
async def apply_survey_answer(request: Request, token: str, db: Session = Depends(get_db)):
    execution = db.scalar(select(SurveyExecution).options(selectinload(SurveyExecution.questionnaire_version).selectinload(QuestionnaireVersion.questions), selectinload(SurveyExecution.lead)).where(SurveyExecution.public_token == token))
    if not execution:
        raise HTTPException(404)
    form = await request.form()
    next_screen_url = None
    try:
        answers = [str(value) for value in form.getlist("answer") if str(value).strip()]
        current = advance_to_visible_question(db, execution)
        raw_answer = json.dumps(answers, ensure_ascii=False) if current and current.type == "multiple_choice" else ", ".join(answers)
        record_answer(db, execution, raw_text=raw_answer, interaction_id=str(form.get("interaction_id") or "") or None, source=execution.channel)
        next_screen_url = getattr(execution, "_next_screen_url", None)
        if next_screen_url:
            next_token = next_screen_url.rsplit("/", 1)[-1]
            return_url = request.session.get(f"survey_return:{execution.public_token}")
            if not return_url and execution.collection_session:
                return_url = f"/coleta/sessao/{execution.collection_session.public_token}"
            if return_url:
                request.session[f"survey_return:{next_token}"] = return_url
        db.commit()
    except ValueError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
    if next_screen_url:
        return redirect(next_screen_url)
    return redirect(f"/aplicar/{token}")


@router.get("/coleta/{token}")
def kiosk_home(request: Request, token: str, db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.token == token, Device.active.is_(True)))
    if not device:
        raise HTTPException(404)
    device.last_seen_at = utcnow()
    db.commit()
    identified, anonymous = [], []
    for questionnaire in db.scalars(select(Questionnaire).where(Questionnaire.status == "active").order_by(Questionnaire.name)).all():
        published = latest_published_version(db, questionnaire)
        if not published:
            continue
        published_config = version_config(published)
        if "kiosk" not in channels(published_config):
            continue
        view = SimpleNamespace(id=questionnaire.id, name=published_config.name, description=published_config.description, response_mode=published_config.response_mode)
        (anonymous if published_config.response_mode == "anonymous" else identified).append(view)
    entry_flows = [
        flow for flow in db.scalars(select(EntryFlow).where(EntryFlow.status == "active").order_by(EntryFlow.name)).all()
        if (not json_list(flow.city_ids_json) or device.city_id in {_int(value) for value in json_list(flow.city_ids_json)})
        and (not json_list(flow.device_ids_json) or device.id in {_int(value) for value in json_list(flow.device_ids_json)})
    ]
    return request.app.state.templates.TemplateResponse(request, "kiosk_home.html", ctx(request, db, device=device, identified=identified, anonymous=anonymous, entry_flows=entry_flows))


@router.post("/coleta/{token}/cadastro")
async def kiosk_register(request: Request, token: str, db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.token == token, Device.active.is_(True)))
    if not device:
        raise HTTPException(404)
    form = await request.form()
    setting = db.get(SystemSetting, 1)
    normalized = normalize_phone(form.get("phone"), setting.default_country_code)
    lead = db.scalar(select(Lead).where(Lead.phone_normalized == normalized)) if normalized else None
    if not lead:
        lead = Lead(name=str(form.get("name") or "").strip(), phone=str(form.get("phone") or "").strip() or None, phone_normalized=normalized, source="kiosk", city=str(form.get("city") or "").strip() or None, neighborhood=str(form.get("neighborhood") or "").strip() or None, consent_research=_bool(form, "consent_research"), consent_marketing=_bool(form, "consent_marketing"))
        pet_name = str(form.get("pet_name") or "").strip()
        if pet_name:
            lead.pets.append(Pet(name=pet_name, species=str(form.get("pet_species") or "").strip() or None))
        db.add(lead)
        db.flush()
        schedule_for_new_lead(db, lead)
    questionnaire = db.get(Questionnaire, _int(form.get("questionnaire_id")))
    if questionnaire:
        execution = create_execution(db, questionnaire, lead=lead, channel="kiosk", source="kiosk")
        db.commit()
        return redirect(f"/aplicar/{execution.public_token}")
    db.commit()
    return redirect(f"/coleta/{token}?ok=1")


@router.post("/coleta/{token}/anonima/{questionnaire_id}")
def kiosk_anonymous(request: Request, token: str, questionnaire_id: int, db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.token == token, Device.active.is_(True), Device.allow_anonymous.is_(True)))
    questionnaire = db.get(Questionnaire, questionnaire_id)
    published = latest_published_version(db, questionnaire) if questionnaire else None
    published_config = version_config(published) if published else None
    if not device or not questionnaire or not published_config or published_config.response_mode != "anonymous" or "kiosk" not in channels(published_config):
        raise HTTPException(404)
    execution = create_execution(db, questionnaire, channel="kiosk", source="kiosk_anonymous")
    db.commit()
    return redirect(f"/aplicar/{execution.public_token}")


@router.get("/conta")
def account_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return request.app.state.templates.TemplateResponse(request, "account.html", ctx(request, db, account=user))


@router.post("/conta")
async def account_update(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    user.name = str(form.get("name") or user.name).strip()
    user.email = str(form.get("email") or "").strip() or None
    user.phone = str(form.get("phone") or "").strip() or None
    avatar_color = str(form.get("avatar_color") or user.avatar_color)
    if len(avatar_color) == 7 and avatar_color.startswith("#"):
        user.avatar_color = avatar_color
    theme = str(form.get("preferred_theme") or "system")
    user.preferred_theme = theme if theme in {"system", "light", "dark"} else "system"
    user.navigation_compact = _bool(form, "navigation_compact")
    requested_timezone = str(form.get("timezone_name") or "").strip()
    user.timezone_name = valid_timezone(requested_timezone) if requested_timezone else None
    user.chat_signature = str(form.get("chat_signature") or "").strip()[:1000] or None
    user.chat_signature_enabled = _bool(form, "chat_signature_enabled")
    current_password = str(form.get("current_password") or "")
    new_password = str(form.get("new_password") or "")
    if new_password:
        if not verify_password(current_password, user.password_hash):
            flash(request, "A senha atual não confere.", "danger")
            return redirect("/conta")
        if len(new_password) < 8:
            flash(request, "A nova senha deve ter pelo menos 8 caracteres.", "danger")
            return redirect("/conta")
        user.password_hash = hash_password(new_password)
    db.commit()
    flash(request, "Conta atualizada.")
    return redirect("/conta")


@router.get("/usuarios")
def users_page(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    rows = db.scalars(select(User).order_by(User.name)).all()
    cities = db.scalars(select(City).where(City.active.is_(True)).order_by(City.name)).all()
    return request.app.state.templates.TemplateResponse(request, "users.html", ctx(request, db, users=rows, cities=cities))


@router.post("/usuarios")
async def user_create(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    form = await request.form()
    name = str(form.get("name") or "").strip()
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    if not name or not username or len(password) < 8:
        flash(request, "Informe nome, usuário e uma senha com pelo menos oito caracteres.", "danger")
        return redirect("/usuarios")
    role = str(form.get("role") or "operator")
    if role not in {"admin", "operator", "interviewer"}:
        role = "operator"
    row = User(
        name=name,
        username=username,
        email=str(form.get("email") or "").strip() or None,
        phone=str(form.get("phone") or "").strip() or None,
        password_hash=hash_password(password),
        role=role,
        active=True,
        timezone_name=valid_timezone(form.get("timezone_name")) if form.get("timezone_name") else None,
        all_cities=_bool(form, "all_cities"),
        city_ids_json=json.dumps([_int(value) for value in form.getlist("city_ids") if _int(value)], ensure_ascii=False),
    )
    db.add(row)
    try:
        db.commit()
        flash(request, "Usuário criado.")
    except Exception:
        db.rollback()
        flash(request, "Nome de usuário já utilizado.", "danger")
    return redirect("/usuarios")


@router.post("/usuarios/{user_id}/editar")
async def user_update(request: Request, user_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin"})
    row = db.get(User, user_id)
    if not row:
        raise HTTPException(404)
    form = await request.form()
    new_role = str(form.get("role") or row.role)
    if new_role not in {"admin", "operator", "interviewer"}:
        new_role = row.role
    new_active = _bool(form, "active")
    active_admins = db.scalar(select(func.count(User.id)).where(User.role == "admin", User.active.is_(True))) or 0
    if row.role == "admin" and row.active and (new_role != "admin" or not new_active) and active_admins <= 1:
        flash(request, "O último administrador ativo não pode ser suspenso nem perder o perfil.", "danger")
        return redirect("/usuarios")
    row.name = str(form.get("name") or row.name).strip()
    row.email = str(form.get("email") or "").strip() or None
    row.phone = str(form.get("phone") or "").strip() or None
    row.role = new_role
    row.active = new_active
    row.all_cities = _bool(form, "all_cities")
    row.timezone_name = valid_timezone(form.get("timezone_name")) if form.get("timezone_name") else None
    row.city_ids_json = json.dumps([_int(value) for value in form.getlist("city_ids") if _int(value)], ensure_ascii=False)
    password = str(form.get("password") or "")
    if password:
        if len(password) < 8:
            flash(request, "A nova senha precisa ter pelo menos oito caracteres.", "danger")
            return redirect("/usuarios")
        row.password_hash = hash_password(password)
    db.commit()
    flash(request, "Usuário atualizado.")
    return redirect("/usuarios")
