from __future__ import annotations

import json
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Alert,
    Conversation,
    ConversationMessage,
    Lead,
    LeadSegment,
    MessageQueue,
    Question,
    Questionnaire,
    QuestionnaireVersion,
    QuestionnaireVersionQuestion,
    SurveyAnswer,
    SurveyExecution,
    SystemSetting,
    utcnow,
)
from .segmentation import segment_from_answer
from .security import normalize_phone, normalize_text
from .timezone import DEFAULT_TIMEZONE, local_datetime, valid_timezone
from .versioning import (
    VersionConsistencyError,
    execution_config,
    execution_questions,
    latest_published_version,
    version_config,
)


def channels(questionnaire: Questionnaire) -> list[str]:
    try:
        values = json.loads(questionnaire.channels_json or "[]")
        return [str(item) for item in values]
    except (TypeError, ValueError):
        return ["whatsapp"]


def options(question: Question | QuestionnaireVersionQuestion) -> list[dict]:
    try:
        value = json.loads(question.options_json or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def active_questions(questionnaire: Questionnaire) -> list[Question]:
    """Return only questions currently published by the questionnaire.

    Archived questions stay in the database so historical answers keep a valid
    foreign key and continue displaying the original wording.
    """
    return sorted(
        [question for question in questionnaire.questions if getattr(question, "active", True)],
        key=lambda question: (question.position, question.id or 0),
    )


def render_message(
    text: str,
    lead: Lead | None,
    execution: SurveyExecution | None = None,
    system: SystemSetting | None = None,
) -> str:
    first_name = lead.name.split()[0] if lead and lead.name else ""
    session = execution.collection_session if execution else None
    collection_pets = list(session.pets) if session else []
    pets = [item.pet for item in collection_pets]
    selected_pet = execution.pet if execution and execution.pet else (pets[0] if len(pets) == 1 else None)
    pet_item = next((item for item in collection_pets if selected_pet and item.pet_id == selected_pet.id), None)
    pets_names = [pet.name for pet in pets if pet and pet.name]
    services = [f"• {item.pet.name} — {item.service_type}" for item in collection_pets if item.pet and item.service_type]
    service_names = [item.service_type for item in collection_pets if item.service_type]
    reasons = [item.reason for item in collection_pets if item.reason]
    statuses = [item.service_status for item in collection_pets if item.service_status]
    timezone_name = valid_timezone(system.timezone_name if system else DEFAULT_TIMEZONE)
    local_started = local_datetime(session.started_at, timezone_name) if session else None
    now_local = datetime.now(ZoneInfo(timezone_name))
    values = {
        "nome": first_name,
        "primeiro_nome": first_name,
        "nome_completo": lead.name if lead else "",
        "telefone": lead.phone_normalized if lead else "",
        "cidade": lead.city if lead else "",
        "bairro": lead.neighborhood if lead else "",
        "pets_nomes": ", ".join(pets_names[:-1]) + (" e " if len(pets_names) > 1 else "") + (pets_names[-1] if pets_names else ""),
        "quantidade_pets": len(pets_names),
        "pet_nome": selected_pet.name if selected_pet else "",
        "pet_especie": selected_pet.species if selected_pet else "",
        "pet_servico": pet_item.service_type if pet_item else "",
        "pet_motivo": pet_item.reason if pet_item else "",
        "pet_status_servico": pet_item.service_status if pet_item else "",
        "pets_servicos_lista": "\n".join(services),
        "servicos_resumo": ", ".join(dict.fromkeys(service_names)),
        "motivos_resumo": ", ".join(dict.fromkeys(reasons)),
        "status_servicos": ", ".join(dict.fromkeys(statuses)),
        "data_atendimento": local_started.strftime("%d/%m/%Y") if local_started else "",
        "unidade": session.device.name if session and session.device else "",
        "nome_empresa": system.organization_name if system else "",
        "nome_fluxo": session.flow.name if session and session.flow else "",
        "nome_questionario": execution_config(execution).name if execution else "",
        "data_atual": now_local.strftime("%d/%m/%Y"),
    }
    output = text or ""
    for key, value in values.items():
        output = output.replace("{{" + key + "}}", str(value or ""))
    return output


def due_from_delay(
    value: int,
    unit: str,
    *,
    schedule_mode: str = "exact_interval",
    send_hour: int | None = None,
    timezone_name: str = "America/Sao_Paulo",
) -> datetime:
    value = max(0, value or 0)
    if schedule_mode in {"day_hour", "next_allowed"}:
        zone = ZoneInfo(valid_timezone(timezone_name))
        now_local = datetime.now(zone)
        target = now_local + timedelta(days=value)
        if schedule_mode == "next_allowed":
            while target.weekday() >= 5:
                target += timedelta(days=1)
        target = target.replace(hour=max(0, min(23, send_hour if send_hour is not None else 8)), minute=0, second=0, microsecond=0)
        if target <= now_local:
            target += timedelta(days=1)
            while schedule_mode == "next_allowed" and target.weekday() >= 5:
                target += timedelta(days=1)
        return target.astimezone(timezone.utc).replace(tzinfo=None)
    if unit == "minutes":
        return utcnow() + timedelta(minutes=value)
    if unit == "hours":
        return utcnow() + timedelta(hours=value)
    return utcnow() + timedelta(days=value)


def create_execution(
    db: Session,
    questionnaire: Questionnaire,
    *,
    lead: Lead | None = None,
    channel: str = "whatsapp",
    source: str = "manual",
    scheduled_at: datetime | None = None,
    is_test: bool = False,
    test_label: str | None = None,
    idempotency_key: str | None = None,
    collection_session_id: int | None = None,
    flow_action_id: int | None = None,
    pet_id: int | None = None,
    city_id: int | None = None,
    device_id: int | None = None,
    context: dict | None = None,
    questionnaire_version: QuestionnaireVersion | None = None,
) -> SurveyExecution:
    version = questionnaire_version or latest_published_version(db, questionnaire)
    if not version:
        raise VersionConsistencyError(f"Questionário {questionnaire.id} não possui versão publicada.")
    if version.questionnaire_id != questionnaire.id:
        raise VersionConsistencyError("A versão escolhida não pertence ao questionário da execução.")
    config = version_config(version)
    if config.response_mode == "anonymous" and channel == "whatsapp":
        raise ValueError("Pesquisas anônimas não podem ser aplicadas pelo WhatsApp.")
    if idempotency_key:
        duplicate = db.scalar(select(SurveyExecution).where(SurveyExecution.idempotency_key == idempotency_key).limit(1))
        if duplicate:
            return duplicate
    row = SurveyExecution(
        questionnaire_id=questionnaire.id,
        questionnaire_version_id=version.id,
        lead_id=lead.id if lead else None,
        public_token=secrets.token_urlsafe(28),
        anonymous_token=secrets.token_urlsafe(28) if config.response_mode == "anonymous" else None,
        channel=channel,
        source=source,
        status="scheduled" if channel == "whatsapp" else "active",
        scheduled_at=scheduled_at or utcnow(),
        started_at=utcnow() if channel != "whatsapp" else None,
        is_test=is_test,
        idempotency_key=idempotency_key,
        collection_session_id=collection_session_id,
        flow_action_id=flow_action_id,
        pet_id=pet_id,
        city_id=city_id,
        device_id=device_id,
        context_json=json.dumps(context or {}, ensure_ascii=False, default=str),
        test_label=test_label,
    )
    db.add(row)
    db.flush()
    return row


def schedule_for_new_lead(db: Session, lead: Lead) -> list[SurveyExecution]:
    created: list[SurveyExecution] = []
    if not lead.consent_research or lead.opted_out_at or lead.status != "active":
        return created
    active = db.scalars(select(Questionnaire).where(Questionnaire.status == "active")).all()
    for questionnaire in active:
        version = latest_published_version(db, questionnaire)
        if not version:
            continue
        config = version_config(version)
        if config.trigger_type not in {"immediate_registration", "after_registration"}:
            continue
        if "whatsapp" not in channels(config) or not lead.phone_normalized or config.response_mode == "anonymous":
            continue
        if config.random_percent < 100 and random.randint(1, 100) > config.random_percent:
            continue
        due = utcnow() if config.trigger_type == "immediate_registration" else due_from_delay(config.delay_value, config.delay_unit)
        created.append(create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="registration", scheduled_at=due, questionnaire_version=version))
    return created


def eligible_leads(db: Session, questionnaire: Questionnaire, config=None) -> list[Lead]:
    config = config or version_config(latest_published_version(db, questionnaire))
    query = select(Lead).where(
        Lead.status == "active",
        Lead.source != "laboratory",
        Lead.opted_out_at.is_(None),
        Lead.consent_research.is_(True),
    )
    if config.audience_type == "segment" and config.target_segment_id:
        query = query.join(LeadSegment).where(LeadSegment.segment_id == config.target_segment_id)
    if config.audience_type == "new_leads":
        query = query.where(Lead.created_at >= utcnow() - timedelta(days=30))
    leads = db.scalars(query.order_by(Lead.id.desc())).unique().all()
    if config.audience_type == "no_response":
        answered_ids = db.scalars(
            select(SurveyExecution.lead_id).where(
                SurveyExecution.questionnaire_id == questionnaire.id,
                SurveyExecution.status == "completed",
                SurveyExecution.lead_id.is_not(None),
            )
        ).all()
        answered = set(answered_ids)
        leads = [lead for lead in leads if lead.id not in answered]
    return [lead for lead in leads if lead.phone_normalized]


def launch_questionnaire(db: Session, questionnaire: Questionnaire, *, source: str = "manual") -> int:
    version = latest_published_version(db, questionnaire)
    if not version:
        raise VersionConsistencyError("Publique o questionário antes do disparo.")
    config = version_config(version)
    count = 0
    for lead in eligible_leads(db, questionnaire, config):
        if config.random_percent < 100 and random.randint(1, 100) > config.random_percent:
            continue
        create_execution(db, questionnaire, lead=lead, channel="whatsapp", source=source, scheduled_at=utcnow(), questionnaire_version=version)
        count += 1
    return count


def schedule_recurrences(db: Session) -> int:
    created = 0
    questionnaires = db.scalars(select(Questionnaire).where(Questionnaire.status == "active")).all()
    for questionnaire in questionnaires:
        version = latest_published_version(db, questionnaire)
        if not version:
            continue
        config = version_config(version)
        if not config.recurrence_days or config.recurrence_days <= 0:
            continue
        for lead in eligible_leads(db, questionnaire, config):
            last = db.scalar(
                select(SurveyExecution)
                .where(
                    SurveyExecution.questionnaire_id == questionnaire.id,
                    SurveyExecution.lead_id == lead.id,
                    SurveyExecution.is_test.is_(False),
                )
                .order_by(SurveyExecution.created_at.desc())
                .limit(1)
            )
            if not last:
                if config.trigger_type == "recurring":
                    create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="recurrence", scheduled_at=utcnow(), questionnaire_version=version)
                    created += 1
                continue
            reference = last.completed_at or last.created_at
            if last.status == "completed" and reference <= utcnow() - timedelta(days=config.recurrence_days or 0):
                create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="recurrence", scheduled_at=utcnow(), questionnaire_version=version)
                created += 1
    return created


def _queue(
    db: Session, execution: SurveyExecution, kind: str, text: str,
    question: Question | QuestionnaireVersionQuestion | None = None, button_items: list[dict] | None = None,
    message_type: str = "text",
    available_at: datetime | None = None,
    media_payload: dict | None = None,
) -> MessageQueue:
    recipient = (
        execution.lead.phone_normalized or execution.lead.whatsapp_lid
        if execution.lead
        else None
    )
    if not execution.lead or not recipient:
        raise ValueError("Execução pelo WhatsApp sem identidade de destinatário.")
    row = MessageQueue(
        execution_id=execution.id,
        lead_id=execution.lead_id,
        question_id=(question.original_question_id if isinstance(question, QuestionnaireVersionQuestion) else question.id) if question else None,
        version_question_id=question.id if isinstance(question, QuestionnaireVersionQuestion) else None,
        kind=kind,
        phone=recipient,
        payload_text=render_message(text, execution.lead, execution, db.get(SystemSetting, 1)),
        message_type=message_type,
        buttons_json=json.dumps(button_items or [], ensure_ascii=False),
        media_payload_json=json.dumps(media_payload or {}, ensure_ascii=False),
        status="pending",
        available_at=available_at or utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _question_buttons(question: Question | QuestionnaireVersionQuestion) -> list[dict]:
    if question.type == "yes_no":
        return [{"id": "yes", "label": "Sim", "value": "sim"}, {"id": "no", "label": "Não", "value": "não"}]
    if question.type in {"choice", "multiple_choice"}:
        items = list(options(question))
        if _question_settings(question).get("shuffle_options"):
            random.Random(f"escutapet-question:{question.id}").shuffle(items)
        return items
    return []


def display_options(question: Question | QuestionnaireVersionQuestion) -> list[dict]:
    """Opções na mesma ordem para Web, quiosque, entrevistador e WhatsApp."""
    return _question_buttons(question)


def whatsapp_message_type(question: Question | QuestionnaireVersionQuestion) -> str:
    items = _question_buttons(question)
    if question.type == "multiple_choice":
        return "numbered_text"
    mode = (question.whatsapp_response_mode or "auto").strip()
    if not items:
        return "text"
    if mode == "numbered_text":
        return "numbered_text"
    if mode == "text":
        return "text"
    if mode == "option_list":
        return "option_list"
    if mode == "buttons":
        return "buttons" if len(items) <= 3 else "option_list"
    return "buttons" if len(items) <= 3 else "option_list"


def question_prompt(question: Question | QuestionnaireVersionQuestion) -> str:
    text = question.text
    if question.type == "score":
        text += f"\n\nResponda com uma nota de {question.min_score} a {question.max_score}."
    elif question.type == "stars":
        text += f"\n\nResponda com uma nota de {question.min_score} a {question.max_score}."
    elif question.type == "audio":
        text += "\n\nEnvie um áudio para continuar."
    elif question.type == "photo":
        text += "\n\nEnvie uma foto para continuar."
    elif question.type == "video":
        text += "\n\nEnvie um vídeo para continuar."
    elif question.type == "document":
        text += "\n\nEnvie um documento para continuar."
    elif question.type == "location":
        text += "\n\nUse o botão de localização do WhatsApp para continuar."
    elif question.type == "contact":
        text += "\n\nCompartilhe um contato para continuar."
    elif question.type == "multiple_files":
        text += "\n\nEnvie o arquivo ou mídia solicitado."
    elif question.type == "multiple_choice":
        text += "\n\nEscolha uma ou mais opções. No texto numerado, separe os números por vírgula."
    if question.help_text:
        text += f"\n\n{question.help_text}"
    return text


QUESTION_CONDITION_OPERATORS = {
    "answered", "not_answered", "equals", "not_equals", "contains", "not_contains",
    "gte", "lte", "between",
}
QUESTION_NUMERIC_CONDITION_OPERATORS = {"gte", "lte", "between"}


def _question_visibility(question: Question | QuestionnaireVersionQuestion) -> dict:
    value = _question_settings(question).get("visibility")
    return value if isinstance(value, dict) else {}


def _condition_answer(db: Session, execution: SurveyExecution, source_question_id: int) -> SurveyAnswer | None:
    return db.scalar(
        select(SurveyAnswer)
        .where(
            SurveyAnswer.execution_id == execution.id,
            SurveyAnswer.question_id == source_question_id,
        )
        .order_by(SurveyAnswer.id.desc())
        .limit(1)
    )


def question_is_visible(
    db: Session,
    execution: SurveyExecution,
    question: Question | QuestionnaireVersionQuestion,
) -> bool:
    """Avalia a regra congelada da pergunta usando somente respostas da execução atual."""
    rule = _question_visibility(question)
    if not rule.get("enabled"):
        return True
    try:
        source_question_id = int(rule.get("source_question_id") or 0)
    except (TypeError, ValueError):
        return False
    if not source_question_id:
        return False
    answer = _condition_answer(db, execution, source_question_id)
    operator = str(rule.get("operator") or "equals")
    if operator not in QUESTION_CONDITION_OPERATORS:
        return False
    if operator == "answered":
        return answer is not None
    if operator == "not_answered":
        return answer is None
    if answer is None:
        return False
    if operator in QUESTION_NUMERIC_CONDITION_OPERATORS:
        try:
            actual_number = (
                answer.numeric_value
                if answer.numeric_value is not None
                else float(str(answer.answer_text or "").replace(",", "."))
            )
            expected_number = float(rule.get("value"))
        except (TypeError, ValueError):
            return False
        if operator == "gte":
            return actual_number >= expected_number
        if operator == "lte":
            return actual_number <= expected_number
        try:
            expected_max = float(rule.get("value_max"))
        except (TypeError, ValueError):
            return False
        return expected_number <= actual_number <= expected_max
    expected = normalize_text(str(rule.get("value") or ""))
    actual_text = normalize_text(str(answer.answer_text or ""))
    actual_value = normalize_text(str(answer.answer_value or ""))
    candidates = {actual_text, actual_value}
    try:
        selected_values = json.loads(answer.answer_value or "")
        if isinstance(selected_values, list):
            candidates.update(normalize_text(str(item)) for item in selected_values)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    if operator == "equals":
        return expected in candidates
    if operator == "not_equals":
        return expected not in candidates
    if operator == "contains":
        return any(expected in item for item in candidates)
    if operator == "not_contains":
        return all(expected not in item for item in candidates)
    return False


def advance_to_visible_question(
    db: Session,
    execution: SurveyExecution,
) -> QuestionnaireVersionQuestion | None:
    """Pula perguntas ocultas sem criar respostas artificiais ou quebrar a posição histórica."""
    questions = execution_questions(execution)
    while execution.current_position < len(questions):
        question = questions[execution.current_position]
        if question_is_visible(db, execution, question):
            return question
        execution.current_position += 1
    complete_execution(db, execution)
    return None


def start_whatsapp_execution(db: Session, execution: SurveyExecution) -> None:
    if execution.status != "scheduled":
        return
    execution.status = "active"
    execution.started_at = utcnow()
    execution.last_interaction_at = utcnow()
    config = execution_config(execution)
    if config.opening_message:
        _queue(db, execution, "opening", config.opening_message)
        queue_current_question(db, execution, available_at=utcnow() + timedelta(seconds=2))
    else:
        queue_current_question(db, execution)


def queue_current_question(db: Session, execution: SurveyExecution, *, available_at: datetime | None = None) -> None:
    question = advance_to_visible_question(db, execution)
    if question is None:
        return
    items = _question_buttons(question)
    message_type = whatsapp_message_type(question)
    _queue(db, execution, "question", question_prompt(question), question, items, message_type, available_at)


def queue_invalid_response(db: Session, execution: SurveyExecution, message: str) -> None:
    execution.invalid_attempts = (execution.invalid_attempts or 0) + 1
    correction = message.strip()
    if not correction:
        correction = "Não consegui identificar sua resposta."
    _queue(db, execution, "validation", correction)
    queue_current_question(db, execution, available_at=utcnow() + timedelta(seconds=2))


def anonymous_aggregate(
    db: Session,
    *,
    questionnaire_id: int | None = None,
    city_id: int | None = None,
    device_id: int | None = None,
    shift: str | None = None,
    date_range: tuple[str | None, str | None] | None = None,
) -> dict | None:
    """Agrega notas de respostas anônimas aplicando o piso de anonimato (I4).

    Devolve ``None`` quando o recorte reúne menos que ``anonymous_minimum``
    respostas — nenhuma tela ou exportação pode ler um grupo pequeno o
    bastante para ser identificável. Todo consumidor de dado anônimo
    (alerta, relatório, exportação) deve passar por aqui em vez de montar
    a própria consulta.
    """
    conditions = [
        SurveyExecution.is_test.is_(False),
        SurveyExecution.lead_id.is_(None),
        SurveyAnswer.numeric_value.is_not(None),
    ]
    if questionnaire_id:
        conditions.append(SurveyExecution.questionnaire_id == questionnaire_id)
    if city_id:
        conditions.append(SurveyExecution.city_id == city_id)
    if device_id:
        conditions.append(SurveyExecution.device_id == device_id)
    if shift:
        conditions.append(func.json_extract(SurveyExecution.context_json, "$.anonymous_context.shift") == shift)
    if date_range:
        start, end = date_range
        collected = func.json_extract(SurveyExecution.context_json, "$.anonymous_context.collected_date")
        if start:
            conditions.append(collected >= start)
        if end:
            conditions.append(collected <= end)
    setting = db.get(SystemSetting, 1)
    minimum = setting.anonymous_minimum if setting else 7
    stats = db.execute(
        select(func.count(SurveyAnswer.id), func.avg(SurveyAnswer.numeric_value))
        .join(SurveyExecution, SurveyExecution.id == SurveyAnswer.execution_id)
        .where(*conditions)
    ).one()
    total = int(stats[0] or 0)
    if total < minimum:
        return None
    average = stats[1]
    return {"count": total, "average": float(average) if average is not None else None}


def evaluate_anonymous_alert(db: Session, execution: SurveyExecution) -> None:
    config = execution_config(execution)
    if config.response_mode != "anonymous" or not config.alert_enabled:
        return
    result = anonymous_aggregate(db, questionnaire_id=execution.questionnaire_id)
    if not result or result["average"] is None or result["average"] > config.alert_threshold:
        return
    total, average = result["count"], result["average"]
    existing = db.scalar(
        select(Alert).where(
            Alert.questionnaire_id == execution.questionnaire_id,
            Alert.lead_id.is_(None),
            Alert.status == "open",
            Alert.title == "Queda na satisfação anônima",
        ).limit(1)
    )
    description = f"A média das últimas respostas anônimas está em {average:.1f}, com {total} avaliações acumuladas."
    if existing:
        existing.description = description
        existing.score = average
        existing.updated_at = utcnow()
        return
    db.add(Alert(
        questionnaire_id=execution.questionnaire_id,
        execution_id=None,
        answer_id=None,
        lead_id=None,
        title="Queda na satisfação anônima",
        description=description,
        severity=config.alert_severity,
        status="open",
        score=average,
        due_at=utcnow() + timedelta(hours=48),
    ))


def complete_execution(db: Session, execution: SurveyExecution) -> str | None:
    if execution.status == "completed":
        return getattr(execution, "_next_screen_url", None)
    execution.status = "completed"
    execution.completed_at = utcnow()
    execution.last_interaction_at = utcnow()
    evaluate_anonymous_alert(db, execution)
    if execution.collection_session:
        execution.collection_session.current_stage = "survey_completed"
        if execution.collection_session.confirmation_status in {"not_required", "confirmed", "confirmed_manual"}:
            execution.collection_session.status = "completed"
            execution.collection_session.completed_at = utcnow()
    config = execution_config(execution)
    if config.objective == "registration" and execution.lead:
        schedule_for_new_lead(db, execution.lead)
    if execution.flow_action_id and execution.collection_session_id:
        from .collection import advance_after_flow_action
        next_screen_url = advance_after_flow_action(db, execution)
        if next_screen_url:
            execution._next_screen_url = next_screen_url
            execution.collection_session.status = "started"
            execution.collection_session.current_stage = "dependent_screen"
            execution.collection_session.completed_at = None
    if execution.channel == "whatsapp" and config.closing_message:
        _queue(db, execution, "closing", config.closing_message)
    return getattr(execution, "_next_screen_url", None)


def _resolve_choice(question: Question | QuestionnaireVersionQuestion, raw_text: str, interaction_id: str | None) -> tuple[str, str]:
    items = _question_buttons(question)
    candidate = normalize_text(interaction_id or raw_text)
    if raw_text.strip().isdigit():
        index = int(raw_text.strip()) - 1
        if 0 <= index < len(items):
            item = items[index]
            return str(item.get("value") or item.get("label")), str(item.get("id") or index + 1)
    for item in items:
        possible = [item.get("id"), item.get("value"), item.get("label")]
        if any(normalize_text(str(value)) == candidate for value in possible if value is not None):
            return str(item.get("value") or item.get("label")), str(item.get("id") or item.get("value"))
    return raw_text.strip(), interaction_id or raw_text.strip()


def _question_settings(question: Question | QuestionnaireVersionQuestion) -> dict:
    try:
        parsed = json.loads(getattr(question, "settings_json", "{}") or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _setting_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_multiple_choice(question: Question | QuestionnaireVersionQuestion, raw_text: str) -> tuple[str, str, list[dict]]:
    items = _question_buttons(question)
    try:
        parsed_tokens = json.loads(raw_text) if raw_text.startswith("[") else None
    except (TypeError, ValueError):
        parsed_tokens = None
    tokens = [str(part).strip() for part in parsed_tokens if str(part).strip()] if isinstance(parsed_tokens, list) else [part.strip() for part in raw_text.replace(";", ",").split(",") if part.strip()]
    selected: list[dict] = []
    settings = _question_settings(question)
    for token in tokens:
        candidate = normalize_text(token)
        match = None
        if token.isdigit() and 0 < int(token) <= len(items):
            match = items[int(token) - 1]
        if not match:
            match = next((item for item in items if any(
                normalize_text(str(value)) == candidate
                for value in (item.get("id"), item.get("value"), item.get("label"))
                if value is not None
            )), None)
        if not match and settings.get("allow_other"):
            match = {"id": f"other:{normalize_text(token)}", "label": token, "value": token, "custom": True}
        if not match:
            raise ValueError(f'Não foi possível reconhecer a opção "{token}".')
        if match not in selected:
            selected.append(match)
    minimum = max(0, _setting_int(settings.get("min_selections"), 1 if question.required else 0))
    maximum = _setting_int(settings.get("max_selections"), len(items))
    if len(selected) < minimum:
        raise ValueError(f"Escolha pelo menos {minimum} opção(ões).")
    if len(selected) > maximum:
        raise ValueError(f"Escolha no máximo {maximum} opção(ões).")
    labels = [str(item.get("label") or item.get("value")) for item in selected]
    values = [str(item.get("value") or item.get("label")) for item in selected]
    return ", ".join(labels), json.dumps(values, ensure_ascii=False), selected


def record_answer(
    db: Session,
    execution: SurveyExecution,
    *,
    raw_text: str,
    interaction_id: str | None = None,
    source: str = "web",
    content_type: str = "text",
) -> SurveyAnswer:
    if execution.status not in {"active", "scheduled"}:
        raise ValueError("Esta pesquisa não aceita novas respostas.")
    if execution.status == "scheduled":
        execution.status = "active"
        execution.started_at = utcnow()
    config = execution_config(execution)
    question = advance_to_visible_question(db, execution)
    if question is None:
        raise ValueError("Questionário já concluído.")
    text = raw_text.strip()
    answer_value: str | None = interaction_id or text
    numeric: float | None = None
    selected_items: list[dict] = []
    if question.type in {"choice", "yes_no"}:
        text, answer_value = _resolve_choice(question, text, interaction_id)
        valid_values = {
            normalize_text(str(value))
            for item in _question_buttons(question)
            for value in (item.get("id"), item.get("value"), item.get("label"))
            if value is not None
        }
        allow_other = question.type == "choice" and bool(_question_settings(question).get("allow_other"))
        if not allow_other and normalize_text(str(answer_value)) not in valid_values and normalize_text(text) not in valid_values:
            raise ValueError("Escolha uma das opções apresentadas para continuarmos.")
    elif question.type == "multiple_choice":
        text, answer_value, selected_items = _resolve_multiple_choice(question, text)
    elif question.type in {"score", "stars"}:
        try:
            numeric = float(text.replace(",", "."))
        except ValueError as exc:
            raise ValueError("Informe uma nota válida.") from exc
        if numeric < question.min_score or numeric > question.max_score:
            raise ValueError(f"A nota deve estar entre {question.min_score} e {question.max_score}.")
        answer_value = str(numeric)
    elif question.type in {"audio", "photo", "video", "document", "location", "contact", "multiple_files"}:
        expected = {
            "audio": {"audio"},
            "photo": {"image"},
            "video": {"video"},
            "document": {"document"},
            "location": {"location"},
            "contact": {"contact"},
            "multiple_files": {"image", "audio", "video", "document", "location", "contact"},
        }[question.type]
        if content_type not in expected:
            labels = {
                "audio": "um áudio", "photo": "uma foto", "video": "um vídeo",
                "document": "um documento", "location": "uma localização",
                "contact": "um contato", "multiple_files": "uma mídia ou arquivo",
            }
            raise ValueError(f"Envie {labels[question.type]} para continuarmos.")
        answer_value = content_type
    else:
        settings = _question_settings(question)
        if question.required and not text:
            raise ValueError("Esta resposta é obrigatória.")
        maximum_length = _setting_int(settings.get("max_length"), 0)
        if maximum_length and len(text) > maximum_length:
            raise ValueError(f"A resposta deve ter no máximo {maximum_length} caracteres.")
        validation = str(settings.get("validation") or "none")
        if text and validation == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text):
            raise ValueError("Informe um e-mail válido.")
        if text and validation == "phone" and len(re.sub(r"\D", "", text)) < 10:
            raise ValueError("Informe um telefone válido com DDD.")
        if text and validation == "number":
            try:
                float(text.replace(",", "."))
            except ValueError as exc:
                raise ValueError("Informe um número válido.") from exc

    answer = SurveyAnswer(
        execution_id=execution.id,
        question_id=question.original_question_id,
        version_question_id=question.id,
        answer_text=text,
        answer_value=answer_value,
        numeric_value=numeric,
        content_type=content_type,
        source=source,
    )
    db.add(answer)
    db.flush()

    if execution.lead_id and config.objective == "registration" and execution.current_position == 0 and question.type == "text" and text:
        execution.lead.name = text[:160]
    if config.auto_segment:
        segment_from_answer(db, execution.lead_id, question, text, answer_value, numeric)

    selected = selected_items[0] if selected_items else next((item for item in options(question) if str(item.get("id")) == str(answer_value) or normalize_text(str(item.get("value"))) == normalize_text(text)), None)
    threshold = question.low_score_threshold if question.low_score_threshold is not None else config.alert_threshold
    should_alert = bool(config.response_mode != "anonymous" and config.alert_enabled and numeric is not None and numeric <= threshold)
    should_alert = should_alert or bool(config.response_mode != "anonymous" and (selected and selected.get("creates_alert") or any(item.get("creates_alert") for item in selected_items)))
    if should_alert:
        label = execution.lead.name if execution.lead else "Resposta anônima"
        alert = Alert(
            questionnaire_id=execution.questionnaire_id,
            execution_id=execution.id,
            answer_id=answer.id,
            lead_id=execution.lead_id,
            title=f"Atenção em {config.name}",
            description=f'{label} respondeu "{text}" à pergunta "{question.text}".',
            severity=config.alert_severity,
            status="open",
            score=numeric,
            due_at=utcnow() + timedelta(hours=48),
        )
        db.add(alert)

    execution.current_position += 1
    execution.invalid_attempts = 0
    execution.last_interaction_at = utcnow()
    if execution.channel == "whatsapp":
        queue_current_question(db, execution)
    else:
        advance_to_visible_question(db, execution)
    return answer


def get_active_whatsapp_execution(
    db: Session,
    phone: str | None = None,
    whatsapp_lid: str | None = None,
) -> SurveyExecution | None:
    phone = normalize_phone(phone) if phone else None
    if not phone and not whatsapp_lid:
        return None
    return db.scalar(
        select(SurveyExecution)
        .join(Lead, Lead.id == SurveyExecution.lead_id)
        .where(
            (Lead.phone_normalized == phone) if phone else (Lead.whatsapp_lid == whatsapp_lid),
            SurveyExecution.channel == "whatsapp",
            SurveyExecution.status == "active",
        )
        .order_by(SurveyExecution.started_at.desc(), SurveyExecution.id.desc())
        .limit(1)
    )


def ensure_conversation(
    db: Session,
    phone: str | None,
    lead: Lead | None = None,
    whatsapp_lid: str | None = None,
) -> Conversation:
    phone = normalize_phone(phone) if phone else None
    identity_key = phone or whatsapp_lid
    if not identity_key:
        raise ValueError("A conversa precisa de telefone ou LID.")
    conversation = db.scalar(select(Conversation).where(Conversation.identity_key == identity_key))
    if not conversation and phone:
        conversation = db.scalar(select(Conversation).where(Conversation.phone_normalized == phone))
    if not conversation and whatsapp_lid:
        conversation = db.scalar(select(Conversation).where(Conversation.whatsapp_lid == whatsapp_lid))
    if not conversation:
        conversation = Conversation(
            identity_key=identity_key,
            phone_normalized=phone,
            whatsapp_lid=whatsapp_lid,
            lead_id=lead.id if lead else None,
        )
        db.add(conversation)
        db.flush()
    elif lead and not conversation.lead_id:
        conversation.lead_id = lead.id
    if phone and not conversation.phone_normalized:
        conversation.phone_normalized = phone
    if whatsapp_lid and not conversation.whatsapp_lid:
        conversation.whatsapp_lid = whatsapp_lid
    return conversation


def add_conversation_message(
    db: Session,
    conversation: Conversation,
    *,
    direction: str,
    content: str,
    interaction_id: str | None = None,
    external_id: str | None = None,
    reference_external_id: str | None = None,
    content_type: str = "text",
    status: str | None = None,
    sender_user_id: int | None = None,
    reply_to_message_id: int | None = None,
    quoted_content: str | None = None,
    is_internal: bool = False,
) -> ConversationMessage:
    row = ConversationMessage(
        conversation_id=conversation.id,
        direction=direction,
        content_type=content_type,
        content=content[:5000],
        interaction_id=interaction_id,
        external_id=external_id,
        reference_external_id=reference_external_id,
        status=status or ("received" if direction == "in" else "queued"),
        status_at=utcnow() if status in {"received", "sent", "delivered", "read", "played"} else None,
        sender_user_id=sender_user_id,
        reply_to_message_id=reply_to_message_id,
        quoted_content=(quoted_content or "")[:500] or None,
        is_internal=is_internal,
    )
    db.add(row)
    conversation.last_message_at = utcnow()
    conversation.last_message_preview = content[:240]
    if direction == "in":
        conversation.unread_count += 1
    return row


def dashboard_metrics(db: Session) -> dict[str, int | float]:
    from .cache import cache_json

    return cache_json("dashboard:metrics", lambda: _dashboard_metrics_uncached(db), ttl=6)


def _dashboard_metrics_uncached(db: Session) -> dict[str, int | float]:
    leads = db.scalar(select(func.count(Lead.id)).where(Lead.source != "laboratory")) or 0
    active_questionnaires = db.scalar(select(func.count(Questionnaire.id)).where(Questionnaire.status == "active")) or 0
    pending = db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.status.in_(["scheduled", "active"]), SurveyExecution.is_test.is_(False))) or 0
    alerts = db.scalar(select(func.count(Alert.id)).where(Alert.status == "open")) or 0
    completed = db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.status == "completed", SurveyExecution.is_test.is_(False))) or 0
    total = db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.status.in_(["active", "completed", "abandoned"]), SurveyExecution.is_test.is_(False))) or 0
    response_rate = round((completed / total * 100), 1) if total else 0.0
    return {"leads": leads, "questionnaires": active_questionnaires, "pending": pending, "alerts": alerts, "completed": completed, "response_rate": response_rate}
