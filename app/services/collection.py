from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..models import (
    CollectionPet,
    CollectionSession,
    ConsentReceipt,
    EntryFlow,
    EntryFlowAction,
    Lead,
    MessageQueue,
    Pet,
    PhoneVerification,
    Questionnaire,
    QuestionnaireVersion,
    SurveyExecution,
    SurveyAnswer,
    SystemSetting,
    utcnow,
)
from .engine import create_execution, due_from_delay
from .security import normalize_phone, normalize_text
from .timezone import DEFAULT_TIMEZONE, local_datetime, valid_timezone
from .versioning import resolve_action_version


def json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def profiles(flow: EntryFlow) -> list[str]:
    return [str(item) for item in json_list(flow.profiles_json)]


def service_options(flow: EntryFlow) -> list[str]:
    return [str(item) for item in json_list(flow.service_options_json)]


def service_status_options(flow: EntryFlow) -> list[str]:
    return [str(item) for item in json_list(flow.service_status_options_json)]


def find_or_create_lead(
    db: Session,
    *,
    name: str,
    phone: str,
    default_country_code: str,
    source: str,
    city: str | None,
    city_id: int | None = None,
    neighborhood: str | None,
    consent_research: bool,
    consent_marketing: bool,
) -> tuple[Lead, bool]:
    normalized = normalize_phone(phone, default_country_code)
    lead = db.scalar(
        select(Lead).options(selectinload(Lead.pets)).where(Lead.phone_normalized == normalized)
    ) if normalized else None
    created = False
    if not lead:
        lead = Lead(
            name=name.strip() or "Participante",
            phone=phone.strip() or None,
            phone_normalized=normalized,
            source=source,
            city=city or None,
            city_id=city_id,
            neighborhood=neighborhood or None,
            consent_research=consent_research,
            consent_marketing=consent_marketing,
        )
        db.add(lead)
        db.flush()
        created = True
    else:
        if name.strip():
            lead.name = name.strip()
        lead.phone = phone.strip() or lead.phone
        lead.phone_normalized = normalized or lead.phone_normalized
        lead.city = city or lead.city
        lead.city_id = city_id or lead.city_id
        lead.neighborhood = neighborhood or lead.neighborhood
        lead.consent_research = consent_research
        lead.consent_marketing = consent_marketing
        if lead.opted_out_at and consent_research:
            lead.opted_out_at = None
            lead.status = "active"
    return lead, created


def _pet_for_lead(db: Session, lead: Lead, name: str, species: str | None) -> Pet:
    normalized_name = normalize_text(name)
    for pet in lead.pets:
        if normalize_text(pet.name) == normalized_name:
            if species:
                pet.species = species
            return pet
    pet = Pet(name=name.strip(), species=species or None)
    lead.pets.append(pet)
    db.flush()
    return pet


def build_collection(
    db: Session,
    *,
    flow: EntryFlow,
    lead: Lead,
    device_id: int | None,
    operator_user_id: int | None,
    mode: str,
    pets_data: list[dict[str, str]],
    notes: str | None = None,
    is_test: bool = False,
) -> CollectionSession:
    session = CollectionSession(
        public_token=secrets.token_urlsafe(28),
        flow_id=flow.id,
        lead_id=lead.id,
        device_id=device_id,
        city_id=lead.city_id,
        operator_user_id=operator_user_id,
        mode=mode,
        status="registered",
        current_stage="phone_verification",
        notes=notes or None,
        is_test=is_test,
    )
    db.add(session)
    db.flush()
    for item in pets_data[: max(1, flow.max_pets or 10)]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        pet = _pet_for_lead(db, lead, name, str(item.get("species") or "").strip() or None)
        db.add(CollectionPet(
            collection_session_id=session.id,
            pet_id=pet.id,
            reason=str(item.get("reason") or "").strip() or None,
            service_type=str(item.get("service_type") or "").strip() or None,
            service_status=str(item.get("service_status") or "").strip() or None,
            description=str(item.get("description") or "").strip() or None,
        ))
    db.flush()
    return session


def record_consents(
    db: Session,
    *,
    flow: EntryFlow,
    session: CollectionSession,
    lead: Lead,
    research: bool,
    marketing: bool,
    source: str,
) -> None:
    lead.consent_research = research
    lead.consent_marketing = marketing
    for scope, accepted in (("research", research), ("marketing", marketing)):
        db.add(ConsentReceipt(
            lead_id=lead.id,
            collection_session_id=session.id,
            scope=scope,
            terms_version=flow.consent_terms_version or "1.0",
            accepted=accepted,
            source=source,
        ))


def _cancel_old_verification_queue(db: Session, verification: PhoneVerification | None) -> None:
    if verification and verification.message_queue_id:
        db.execute(
            update(MessageQueue)
            .where(MessageQueue.id == verification.message_queue_id, MessageQueue.status.in_(["pending", "sending"]))
            .values(status="cancelled", error_message="Substituída por nova tentativa de confirmação.")
        )


def _session_verification(db: Session, session: CollectionSession) -> PhoneVerification | None:
    """Consulta a confirmação diretamente para não depender do cache da relação ORM."""
    return db.scalar(
        select(PhoneVerification)
        .where(PhoneVerification.collection_session_id == session.id)
        .limit(1)
    )


def request_phone_verification(
    db: Session,
    *,
    flow: EntryFlow,
    session: CollectionSession,
    phone: str,
) -> PhoneVerification:
    existing = _session_verification(db, session)
    _cancel_old_verification_queue(db, existing)
    token = secrets.token_urlsafe(24)
    if existing:
        verification = existing
        verification.phone = phone
        verification.token = token
        verification.status = "pending"
        verification.confirmed_at = None
        verification.failure_reason = None
        verification.attempts = (verification.attempts or 0) + 1
        verification.expires_at = utcnow() + timedelta(seconds=max(30, flow.phone_verification_timeout or 180))
    else:
        verification = PhoneVerification(
            lead_id=session.lead_id,
            collection_session_id=session.id,
            phone=phone,
            token=token,
            status="pending",
            attempts=1,
            expires_at=utcnow() + timedelta(seconds=max(30, flow.phone_verification_timeout or 180)),
        )
        db.add(verification)
        db.flush()
    item = MessageQueue(
        lead_id=session.lead_id,
        kind="phone_verification",
        phone=phone,
        payload_text=f"Olá, {session.lead.name.split()[0]}! Confirme que este WhatsApp está correto para receber suas pesquisas.",
        message_type="buttons",
        buttons_json=json.dumps([
            {"id": f"verify_phone:{token}", "label": "Confirmar meu WhatsApp", "value": "confirmar"}
        ], ensure_ascii=False),
        status="pending",
        available_at=utcnow(),
    )
    db.add(item)
    db.flush()
    verification.message_queue_id = item.id
    session.confirmation_status = "pending"
    return verification


def _shift_for_hour(hour: int) -> str:
    if 5 <= hour <= 11:
        return "manha"
    if 12 <= hour <= 17:
        return "tarde"
    return "noite"


def _anonymous_context(db: Session, session: CollectionSession) -> dict:
    """Monta o contexto de lugar de uma execução anônima — nunca dado de pessoa (I1)."""
    system = db.get(SystemSetting, 1)
    timezone_name = valid_timezone(system.timezone_name if system else DEFAULT_TIMEZONE)
    local_now = local_datetime(utcnow(), timezone_name)
    is_return = bool(session.lead_id and db.scalar(
        select(CollectionSession.id).where(
            CollectionSession.lead_id == session.lead_id,
            CollectionSession.id != session.id,
            CollectionSession.started_at < session.started_at,
        ).limit(1)
    ))
    return {
        "anonymous_context": {
            "flow_id": session.flow_id,
            "mode": session.mode,
            "is_return": is_return,
            "collected_date": local_now.strftime("%Y-%m-%d") if local_now else None,
            "shift": _shift_for_hour(local_now.hour) if local_now else None,
        }
    }


def _execution_for(
    db: Session,
    session: CollectionSession,
    questionnaire: Questionnaire,
    channel: str,
    *,
    scheduled_at=None,
    source: str,
    anonymous: bool = False,
    action: EntryFlowAction | None = None,
    pet_id: int | None = None,
    idempotency_key: str | None = None,
    questionnaire_version: QuestionnaireVersion | None = None,
) -> SurveyExecution:
    execution = create_execution(
        db,
        questionnaire,
        lead=None if anonymous else session.lead,
        channel=channel,
        source=source,
        scheduled_at=scheduled_at,
        idempotency_key=idempotency_key,
        collection_session_id=None if anonymous else session.id,
        flow_action_id=None if anonymous else (action.id if action else None),
        pet_id=None if anonymous else pet_id,
        city_id=session.city_id if anonymous else None,
        device_id=session.device_id if anonymous else None,
        context=_anonymous_context(db, session) if anonymous else None,
        is_test=session.is_test,
        test_label="Teste de fluxo de entrada" if session.is_test else None,
        questionnaire_version=questionnaire_version,
    )
    return execution


def _action_due(db: Session, action: EntryFlowAction):
    if action.schedule_mode == "fixed_datetime" and action.fixed_scheduled_at:
        return max(action.fixed_scheduled_at, utcnow())
    system = db.get(SystemSetting, 1)
    return due_from_delay(
        action.delay_value,
        action.delay_unit,
        schedule_mode=action.schedule_mode or "exact_interval",
        send_hour=action.send_hour,
        timezone_name=system.timezone_name if system else "America/Sao_Paulo",
    )


def run_flow_actions(
    db: Session,
    session: CollectionSession,
    trigger: str,
    *,
    action_ids: set[int] | None = None,
    source_execution: SurveyExecution | None = None,
) -> str | None:
    """Executa as ações configuradas sem confundir visitas diferentes do mesmo lead."""
    screen_url = None
    actions = [
        action for action in session.flow.actions
        if action.active
        and action.questionnaire
        and action.questionnaire.status == "active"
        and action.trigger == trigger
        and (action_ids is None or action.id in action_ids)
        and _conditions_match(db, session, action, source_execution)
    ]
    actions = _random_branch_actions(session, trigger, actions, source_execution)
    for action in actions:
        action_version = resolve_action_version(db, action)
        if action.require_confirmation and not session.lead.number_validated:
            continue
        if action.channel == "whatsapp" and not session.lead.phone_normalized:
            continue
        if action.per_pet and source_execution and source_execution.pet_id:
            collection_pets = [item for item in session.pets if item.pet_id == source_execution.pet_id]
        else:
            collection_pets = list(session.pets) if action.per_pet else [None]
        if action.per_pet and not collection_pets:
            continue
        for collection_pet in collection_pets:
            pet_id = collection_pet.pet_id if collection_pet else None
            suffix = f":pet:{pet_id}" if pet_id else ""
            key = f"collection:{session.id}:action:{action.id}:questionnaire:{action.questionnaire_id}{suffix}"
            channel = action.channel
            anonymous = channel == "screen_anonymous"
            execution_channel = (
                "kiosk" if session.mode == "kiosk" else "interviewer"
            ) if channel.startswith("screen_") else "whatsapp"
            due = _action_due(db, action) if execution_channel == "whatsapp" else utcnow()
            execution = _execution_for(
                db,
                session,
                action.questionnaire,
                execution_channel,
                source=(
                    "entry_flow_followup"
                    if action.name == "Acompanhamento"
                    else f"entry_action_{trigger}"
                ),
                scheduled_at=due,
                anonymous=anonymous,
                action=action,
                pet_id=pet_id,
                idempotency_key=None if anonymous else key,
                questionnaire_version=action_version,
            )
            if channel.startswith("screen_") and not screen_url:
                screen_url = f"/aplicar/{execution.public_token}"
    return screen_url


def _action_conditions(action: EntryFlowAction) -> list[dict]:
    conditions = json_list(getattr(action, "conditions_json", "[]"))
    valid = [item for item in conditions if isinstance(item, dict) and item.get("question_id")]
    if valid:
        return valid
    if action.condition_question_id:
        return [{
            "source_action_id": action.depends_on_action_id,
            "question_id": action.condition_question_id,
            "operator": action.condition_operator or "answered",
            "value": action.condition_value or "",
        }]
    return []


def _condition_answer(
    db: Session,
    session: CollectionSession,
    condition: dict,
    source_execution: SurveyExecution | None,
) -> tuple[bool, SurveyAnswer | None]:
    source_action_id = int(condition.get("source_action_id") or 0)
    execution = None
    if source_execution and source_action_id and source_execution.flow_action_id == source_action_id:
        execution = source_execution
    elif source_action_id:
        execution = db.scalar(
            select(SurveyExecution)
            .where(
                SurveyExecution.collection_session_id == session.id,
                SurveyExecution.flow_action_id == source_action_id,
                SurveyExecution.status == "completed",
            )
            .order_by(SurveyExecution.completed_at.desc(), SurveyExecution.id.desc())
            .limit(1)
        )
    else:
        execution = db.scalar(
            select(SurveyExecution)
            .where(
                SurveyExecution.collection_session_id == session.id,
                SurveyExecution.source == "entry_registration",
                SurveyExecution.status == "completed",
            )
            .order_by(SurveyExecution.id.desc())
            .limit(1)
        )
    if not execution:
        return False, None
    answer = db.scalar(
        select(SurveyAnswer).where(
            SurveyAnswer.execution_id == execution.id,
            SurveyAnswer.question_id == int(condition.get("question_id") or 0),
        ).limit(1)
    )
    return True, answer


def _condition_row_matches(db: Session, session: CollectionSession, condition: dict, source_execution: SurveyExecution | None) -> bool:
    source_completed, answer = _condition_answer(db, session, condition, source_execution)
    if not source_completed:
        return False
    operator = str(condition.get("operator") or "answered")
    if operator == "answered":
        return answer is not None
    if operator == "not_answered":
        return answer is None
    if not answer:
        return False
    actual = str(answer.answer_text or answer.answer_value or "").strip()
    internal_value = str(answer.answer_value or "").strip()
    expected = str(condition.get("value") or "").strip()
    actual_normalized = normalize_text(actual)
    expected_normalized = normalize_text(expected)
    if operator == "equals":
        return actual_normalized == expected_normalized or normalize_text(internal_value) == expected_normalized
    if operator == "not_equals":
        return actual_normalized != expected_normalized and normalize_text(internal_value) != expected_normalized
    if operator == "contains":
        return expected_normalized in actual_normalized
    if operator == "not_contains":
        return expected_normalized not in actual_normalized
    if operator in {"gte", "lte"}:
        try:
            actual_number = answer.numeric_value if answer.numeric_value is not None else float(actual.replace(",", "."))
            expected_number = float(expected.replace(",", "."))
        except (TypeError, ValueError):
            return False
        return actual_number >= expected_number if operator == "gte" else actual_number <= expected_number
    return False


def _conditions_match(
    db: Session,
    session: CollectionSession,
    action: EntryFlowAction,
    source_execution: SurveyExecution | None = None,
) -> bool:
    conditions = _action_conditions(action)
    if not conditions:
        return True
    results = [_condition_row_matches(db, session, item, source_execution) for item in conditions]
    return any(results) if getattr(action, "condition_logic", "and") == "or" else all(results)


def _random_branch_actions(
    session: CollectionSession,
    trigger: str,
    actions: list[EntryFlowAction],
    source_execution: SurveyExecution | None,
) -> list[EntryFlowAction]:
    """Escolhe uma única ação de cada grupo e mantém a escolha ao retomar a sessão."""
    decisions = {}
    try:
        parsed = json.loads(session.decisions_json or "{}")
        decisions = parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        decisions = {}
    selected: list[EntryFlowAction] = []
    grouped: dict[str, list[EntryFlowAction]] = {}
    for action in actions:
        group = str(getattr(action, "random_group", "") or "").strip()
        if group:
            grouped.setdefault(group, []).append(action)
        else:
            selected.append(action)
    source_key = source_execution.id if source_execution else "root"
    for group, candidates in grouped.items():
        decision_key = f"{trigger}:{group}:{source_key}"
        chosen_id = int(decisions.get(decision_key) or 0)
        chosen = next((item for item in candidates if item.id == chosen_id), None)
        if not chosen:
            total = sum(max(1, int(getattr(item, "random_weight", 1) or 1)) for item in candidates)
            draw = secrets.randbelow(total)
            chosen = candidates[-1]
            cursor = 0
            for item in candidates:
                cursor += max(1, int(getattr(item, "random_weight", 1) or 1))
                if draw < cursor:
                    chosen = item
                    break
            decisions[decision_key] = chosen.id
        selected.append(chosen)
    session.decisions_json = json.dumps(decisions, ensure_ascii=False, sort_keys=True)
    return sorted(selected, key=lambda item: (item.position, item.id))


def run_dependent_flow_actions(db: Session, source_execution: SurveyExecution) -> str | None:
    """Libera as próximas ações e devolve a próxima tela quando a jornada continua no dispositivo."""
    session = source_execution.collection_session
    if not session or not source_execution.flow_action_id:
        return None
    matching = {
        action.id
        for action in session.flow.actions
        if action.active
        and action.trigger == "after_action"
        and action.depends_on_action_id == source_execution.flow_action_id
    }
    if matching:
        return run_flow_actions(
            db,
            session,
            "after_action",
            action_ids=matching,
            source_execution=source_execution,
        )
    return None


def _is_pre_confirmation_action(action: EntryFlowAction, by_id: dict[int, EntryFlowAction]) -> bool:
    current = action
    visited: set[int] = set()
    while current and current.id not in visited:
        visited.add(current.id)
        if current.trigger == "before_confirmation":
            return True
        if current.trigger != "after_action" or not current.depends_on_action_id:
            return False
        current = by_id.get(current.depends_on_action_id)
    return False


def _pending_pre_confirmation_screen(db: Session, session: CollectionSession) -> bool:
    by_id = {action.id: action for action in session.flow.actions}
    pre_ids = {action.id for action in session.flow.actions if _is_pre_confirmation_action(action, by_id)}
    if not pre_ids:
        return False
    return bool(db.scalar(
        select(SurveyExecution.id).where(
            SurveyExecution.collection_session_id == session.id,
            SurveyExecution.flow_action_id.in_(pre_ids),
            SurveyExecution.status.in_(["active", "scheduled"]),
        ).limit(1)
    ))


def advance_after_pre_confirmation(db: Session, session: CollectionSession) -> str | None:
    """Solicita a confirmação somente depois das etapas iniciais e libera o restante da jornada."""
    flow = session.flow
    mode = flow.phone_verification_mode or "none"
    if mode != "none" and session.lead and session.lead.phone_normalized:
        verification = _session_verification(db, session)
        if not verification or verification.status in {"failed", "expired", "cancelled"}:
            request_phone_verification(db, flow=flow, session=session, phone=session.lead.phone_normalized)
        session.current_stage = "verification_pending"
    else:
        session.confirmation_status = "not_required"
        session.current_stage = "post_registration"
    next_url = None
    if mode != "required":
        next_url = launch_immediate_action(db, session)
        if not flow.actions and not flow.followup_requires_confirmation:
            schedule_followup(db, session)
    return next_url


def advance_after_flow_action(db: Session, source_execution: SurveyExecution) -> str | None:
    db.flush()
    next_url = run_dependent_flow_actions(db, source_execution)
    if next_url:
        return next_url
    session = source_execution.collection_session
    action = db.get(EntryFlowAction, source_execution.flow_action_id) if source_execution.flow_action_id else None
    if not session or not action:
        return None
    by_id = {item.id: item for item in session.flow.actions}
    if _is_pre_confirmation_action(action, by_id):
        pending = _next_screen_action_execution(db, session) if _pending_pre_confirmation_screen(db, session) else None
        if pending:
            session.status = "started"
            session.current_stage = "pre_confirmation_screen"
            session.completed_at = None
            return f"/aplicar/{pending.public_token}"
        return advance_after_pre_confirmation(db, session)
    return None


def launch_immediate_action(db: Session, session: CollectionSession) -> str | None:
    flow = session.flow
    if flow.actions:
        return run_flow_actions(db, session, "after_registration")
    questionnaire = flow.immediate_questionnaire
    channel = flow.immediate_channel or "none"
    if not questionnaire or channel == "none":
        return None
    if channel == "screen_anonymous":
        execution = _execution_for(db, session, questionnaire, "kiosk" if session.mode == "kiosk" else "interviewer", source="entry_flow_anonymous", anonymous=True)
        return f"/aplicar/{execution.public_token}"
    if channel == "screen_identified":
        execution = _execution_for(db, session, questionnaire, session.mode, source="entry_flow_screen")
        return f"/aplicar/{execution.public_token}"
    if channel == "whatsapp":
        if not session.lead.phone_normalized:
            return None
        if flow.phone_verification_mode in {"required", "future_only", "send_continue"} and not session.lead.number_validated:
            return None
        _execution_for(db, session, questionnaire, "whatsapp", source="entry_flow_immediate_whatsapp", scheduled_at=utcnow())
    return None


def launch_confirmed_action(db: Session, session: CollectionSession) -> None:
    flow = session.flow
    if flow.actions:
        run_flow_actions(db, session, "after_confirmation")
        return
    questionnaire = flow.confirmed_questionnaire
    channel = flow.confirmed_channel or "none"
    if not questionnaire or channel == "none":
        return
    if channel == "whatsapp":
        _execution_for(db, session, questionnaire, "whatsapp", source="entry_flow_confirmed", scheduled_at=utcnow())
    # Tela após a confirmação é oferecida no status do quiosque, pois o clique ocorre no WhatsApp.
    elif channel in {"screen_identified", "screen_anonymous"}:
        session.current_stage = "confirmed_screen_available"


def schedule_followup(db: Session, session: CollectionSession) -> SurveyExecution | None:
    flow = session.flow
    if flow.actions:
        run_flow_actions(db, session, "after_registration")
        return None
    questionnaire = flow.followup_questionnaire
    if not questionnaire or not session.lead.phone_normalized:
        return None
    if flow.followup_requires_confirmation and not session.lead.number_validated:
        return None
    due = due_from_delay(flow.followup_delay_value, flow.followup_delay_unit)
    return _execution_for(db, session, questionnaire, "whatsapp", source="entry_flow_followup", scheduled_at=due)


def _next_screen_action_execution(db: Session, session: CollectionSession) -> SurveyExecution | None:
    """Localiza a primeira etapa de tela já criada e ainda não respondida.

    A confirmação acontece fora do navegador (no WhatsApp). Por isso a etapa
    seguinte precisa ser recuperável pelo polling da tela de status, em vez de
    depender do retorno da chamada do webhook.
    """
    return db.scalar(
        select(SurveyExecution)
        .join(EntryFlowAction, SurveyExecution.flow_action_id == EntryFlowAction.id)
        .where(
            SurveyExecution.collection_session_id == session.id,
            SurveyExecution.flow_action_id.is_not(None),
            SurveyExecution.status == "active",
            SurveyExecution.channel.in_(["kiosk", "interviewer"]),
        )
        .order_by(EntryFlowAction.position, SurveyExecution.id)
        .limit(1)
    )


def _queue_phone_confirmation_thanks(db: Session, verification: PhoneVerification) -> None:
    """Agradece uma única vez, inclusive quando o entrevistador confirma manualmente."""
    lead = verification.lead
    first_name = lead.name.split()[0] if lead and lead.name else ""
    greeting = f"Obrigado por confirmar seu WhatsApp{', ' + first_name if first_name else ''}!"
    db.add(MessageQueue(
        lead_id=verification.lead_id,
        kind="phone_verification_thanks",
        phone=verification.phone,
        payload_text=f"{greeting} Seu número foi confirmado com sucesso.",
        message_type="text",
        buttons_json="[]",
        status="pending",
        available_at=utcnow(),
    ))


def complete_phone_verification(db: Session, verification: PhoneVerification, *, manual: bool = False) -> None:
    if verification.status == "confirmed":
        return
    verification.status = "confirmed"
    verification.confirmed_at = utcnow()
    verification.failure_reason = "Confirmado manualmente pelo entrevistador." if manual else None
    verification.lead.number_validated = True
    verification.session.confirmation_status = "confirmed_manual" if manual else "confirmed"
    verification.session.current_stage = "post_confirmation"
    _queue_phone_confirmation_thanks(db, verification)
    flow = verification.session.flow
    if flow.phone_verification_mode == "required" and flow.immediate_questionnaire:
        if flow.immediate_channel == "whatsapp":
            _execution_for(db, verification.session, flow.immediate_questionnaire, "whatsapp", source="entry_flow_required_confirmed", scheduled_at=utcnow())
        elif flow.immediate_channel in {"screen_identified", "screen_anonymous"}:
            verification.session.current_stage = "required_screen_available"
    if flow.actions:
        run_flow_actions(db, verification.session, "after_confirmation")
        # No modo obrigatório, todas as ações "Após cadastro" começam agora.
        # Nos demais modos, reavaliamos somente as etapas que estavam bloqueadas
        # pela confirmação; as demais já foram criadas e não podem ser duplicadas.
        if flow.phone_verification_mode == "required":
            run_flow_actions(db, verification.session, "after_registration")
        else:
            gated_action_ids = {
                action.id
                for action in flow.actions
                if action.active
                and action.trigger == "after_registration"
                and action.require_confirmation
            }
            if gated_action_ids:
                run_flow_actions(
                    db,
                    verification.session,
                    "after_registration",
                    action_ids=gated_action_ids,
                )
        if _next_screen_action_execution(db, verification.session):
            verification.session.status = "started"
            verification.session.current_stage = "confirmation_screen_available"
            verification.session.completed_at = None
    else:
        launch_confirmed_action(db, verification.session)
        schedule_followup(db, verification.session)
    if (
        flow.confirmed_channel == "none"
        and verification.session.current_stage == "post_confirmation"
        and not _next_screen_action_execution(db, verification.session)
    ):
        verification.session.status = "completed"
        verification.session.completed_at = utcnow()


def verification_by_interaction(db: Session, phone: str, interaction_id: str | None, text: str) -> PhoneVerification | None:
    phone = normalize_phone(phone) or phone
    token = None
    if interaction_id and interaction_id.startswith("verify_phone:"):
        token = interaction_id.split(":", 1)[1]
    query = (
        select(PhoneVerification)
        .options(
            selectinload(PhoneVerification.lead),
            selectinload(PhoneVerification.session).selectinload(CollectionSession.flow).selectinload(EntryFlow.confirmed_questionnaire),
            selectinload(PhoneVerification.session).selectinload(CollectionSession.flow).selectinload(EntryFlow.followup_questionnaire),
        )
        .where(PhoneVerification.phone == phone, PhoneVerification.status.in_(["pending", "sent", "delivered", "read"]))
        .order_by(PhoneVerification.id.desc())
    )
    if token:
        query = query.where(PhoneVerification.token == token)
    elif normalize_text(text) not in {"confirmar", "confirmar meu whatsapp", "sim"}:
        return None
    return db.scalar(query.limit(1))


def screen_action_after_confirmation(db: Session, session: CollectionSession) -> str | None:
    flow = session.flow
    pending_action = _next_screen_action_execution(db, session)
    if pending_action:
        session.status = "started"
        session.current_stage = "confirmation_screen_available"
        session.completed_at = None
        return f"/aplicar/{pending_action.public_token}"
    if session.current_stage == "required_screen_available":
        questionnaire = flow.immediate_questionnaire
        channel = flow.immediate_channel
        source = "entry_flow_required_screen"
        next_stage = "required_screen_started"
    elif session.current_stage == "confirmed_screen_available":
        questionnaire = flow.confirmed_questionnaire
        channel = flow.confirmed_channel
        source = "entry_flow_confirmed_screen"
        next_stage = "confirmed_screen_started"
    else:
        return None
    if not questionnaire:
        return None
    if channel == "screen_anonymous":
        execution = _execution_for(db, session, questionnaire, session.mode, source=source + "_anonymous", anonymous=True)
    elif channel == "screen_identified":
        execution = _execution_for(db, session, questionnaire, session.mode, source=source)
    else:
        return None
    session.current_stage = next_stage
    return f"/aplicar/{execution.public_token}"
