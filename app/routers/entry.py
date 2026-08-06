from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import (
    AuditLog,
    City,
    CollectionPet,
    CollectionSession,
    Device,
    EntryFlow,
    EntryFlowAction,
    Lead,
    PhoneVerification,
    Question,
    Questionnaire,
    QuestionnaireVersion,
    SurveyAnswer,
    SurveyExecution,
    SystemSetting,
    User,
    utcnow,
)
from ..services.collection import (
    advance_after_pre_confirmation,
    build_collection,
    complete_phone_verification,
    find_or_create_lead,
    json_list,
    launch_immediate_action,
    profiles,
    record_consents,
    request_phone_verification,
    run_flow_actions,
    schedule_followup,
    screen_action_after_confirmation,
    service_options,
    service_status_options,
)
from ..services.security import normalize_phone, normalize_text
from ..services.engine import active_questions, options
from ..services.versioning import VersionConsistencyError, latest_published_version, resolve_action_version, version_config
from ..services.timezone import DEFAULT_TIMEZONE, local_datetime, valid_timezone
from ..services.editor_reliability import add_submission_claim, completed_submission, error, new_editor_key, new_submission_token, persisted_submission, remember_submission, stable_editor_key
from .web import _bool, _cities_for_user, _int, _require_city_access, ctx, current_user, flash, redirect, require_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _flow_query():
    return select(EntryFlow).options(
        selectinload(EntryFlow.immediate_questionnaire),
        selectinload(EntryFlow.confirmed_questionnaire),
        selectinload(EntryFlow.followup_questionnaire),
        selectinload(EntryFlow.registration_questionnaire).selectinload(Questionnaire.questions),
        selectinload(EntryFlow.actions).selectinload(EntryFlowAction.questionnaire).selectinload(Questionnaire.questions),
    )


def _flow_matches_device(flow: EntryFlow, device: Device) -> bool:
    city_ids = {_int(value, 0) for value in json_list(flow.city_ids_json)}
    device_ids = {_int(value, 0) for value in json_list(flow.device_ids_json)}
    return (not city_ids or device.city_id in city_ids) and (not device_ids or device.id in device_ids)


def _flow_matches_user(db: Session, flow: EntryFlow, user: User) -> bool:
    city_ids = {_int(value, 0) for value in json_list(flow.city_ids_json)}
    allowed = {city.id for city in _cities_for_user(db, user)}
    return not city_ids or bool(city_ids.intersection(allowed))


def _default_flow_actions() -> list[dict]:
    items = [
        {"id": "", "item_key": new_editor_key("action"), "name": "Pesquisa imediata na tela", "trigger": "after_registration", "questionnaire_id": "", "version_mode": "latest_published", "fixed_version_id": "", "channel": "screen_identified", "delay_value": 0, "delay_unit": "minutes", "schedule_mode": "exact_interval", "send_hour": 10, "require_confirmation": False, "per_pet": False, "active": True, "depends_on_key": "", "depends_on_action_id": "", "condition_question_id": "", "condition_operator": "", "condition_value": ""},
        {"id": "", "item_key": new_editor_key("action"), "name": "Satisfação após o atendimento", "trigger": "after_registration", "questionnaire_id": "", "version_mode": "latest_published", "fixed_version_id": "", "channel": "whatsapp", "delay_value": 2, "delay_unit": "hours", "schedule_mode": "exact_interval", "send_hour": 10, "require_confirmation": True, "per_pet": False, "active": True, "depends_on_key": "", "depends_on_action_id": "", "condition_question_id": "", "condition_operator": "", "condition_value": ""},
        {"id": "", "item_key": new_editor_key("action"), "name": "Evolução dos pets", "trigger": "after_registration", "questionnaire_id": "", "version_mode": "latest_published", "fixed_version_id": "", "channel": "whatsapp", "delay_value": 10, "delay_unit": "days", "schedule_mode": "day_hour", "send_hour": 10, "require_confirmation": True, "per_pet": True, "active": True, "depends_on_key": "", "depends_on_action_id": "", "condition_question_id": "", "condition_operator": "", "condition_value": ""},
    ]
    for item in items:
        item.update({"conditions_json": "[]", "condition_logic": "and", "random_group": "", "random_weight": 1})
    return items


def _flow_state(flow: EntryFlow | None) -> dict:
    return {
        "name": flow.name if flow else "Cadastro completo e avaliação",
        "description": flow.description or "" if flow else "Coleta os dados do responsável, vários pets, o motivo de cada visita e inicia pesquisas posteriores.",
        "status": flow.status if flow else "active",
        "profiles": profiles(flow) if flow else ["kiosk", "interviewer"],
        "welcome_title": flow.welcome_title if flow else "Conte sobre você e seus pets",
        "welcome_text": flow.welcome_text if flow else "O cadastro leva poucos minutos. Ao final, enviaremos uma confirmação para seu WhatsApp.",
        "registration_questionnaire_id": flow.registration_questionnaire_id or "" if flow else "",
        "allow_existing_lookup": flow.allow_existing_lookup if flow else True,
        "collect_city": flow.collect_city if flow else True,
        "collect_neighborhood": flow.collect_neighborhood if flow else True,
        "allow_no_pet": flow.allow_no_pet if flow else True,
        "max_pets": flow.max_pets if flow else 10,
        "service_options": "\n".join(json_list(flow.service_options_json)) if flow else "Consulta\nExame\nVacinação\nCirurgia\nCastração\nRetorno\nMedicação\nOrientação\nOutro",
        "service_status_options": "\n".join(json_list(flow.service_status_options_json)) if flow else "Já foi realizado\nEstá aguardando\nSerá realizado\nApenas buscando informações",
        "phone_verification_mode": flow.phone_verification_mode if flow else "send_continue",
        "phone_verification_timeout": flow.phone_verification_timeout if flow else 180,
        "allow_manual_confirmation": flow.allow_manual_confirmation if flow else True,
        "consent_research_enabled": flow.consent_research_enabled if flow else True,
        "consent_marketing_enabled": flow.consent_marketing_enabled if flow else True,
        "consent_terms_enabled": flow.consent_terms_enabled if flow else True,
        "city_ids": json_list(flow.city_ids_json) if flow else [],
        "device_ids": json_list(flow.device_ids_json) if flow else [],
        "consent_terms_version": flow.consent_terms_version if flow else "1.0",
        "consent_research_text": flow.consent_research_text if flow else "Aceito participar de pesquisas relacionadas ao atendimento.",
        "consent_marketing_text": flow.consent_marketing_text if flow else "Aceito receber conteúdos e campanhas.",
        "closing_title": flow.closing_title if flow else "Obrigado!",
        "closing_text": flow.closing_text if flow else "Cadastro concluído com sucesso.",
    }


def _actions_from_flow(flow: EntryFlow | None, timezone_name: str = DEFAULT_TIMEZONE) -> list[dict]:
    if not flow or not flow.actions:
        return _default_flow_actions()
    key_by_id = {action.id: f"action:{action.id}" for action in flow.actions}
    result = []
    for action in flow.actions:
        conditions = []
        for condition in json_list(getattr(action, "conditions_json", "[]")):
            if not isinstance(condition, dict):
                continue
            source_id = _int(condition.get("source_action_id"), 0)
            conditions.append({
                "source_key": key_by_id.get(source_id, f"action:missing:{source_id}") if source_id else "registration",
                "question_id": _int(condition.get("question_id"), 0),
                "operator": str(condition.get("operator") or "answered"),
                "value": str(condition.get("value") or ""),
            })
        result.append({
            "id": action.id,
            "item_key": f"action:{action.id}",
            "name": action.name,
            "trigger": action.trigger,
            "questionnaire_id": action.questionnaire_id,
            "version_mode": action.version_mode or "latest_published",
            "fixed_version_id": action.fixed_version_id or "",
            "channel": action.channel,
            "delay_value": action.delay_value,
            "delay_unit": action.delay_unit,
            "schedule_mode": action.schedule_mode,
            "fixed_scheduled_at": local_datetime(action.fixed_scheduled_at, timezone_name).strftime("%Y-%m-%dT%H:%M") if action.fixed_scheduled_at else "",
            "send_hour": action.send_hour if action.send_hour is not None else 10,
            "require_confirmation": action.require_confirmation,
            "per_pet": action.per_pet,
            "active": action.active,
            "depends_on_key": key_by_id.get(action.depends_on_action_id, ""),
            "depends_on_action_id": action.depends_on_action_id or "",
            "condition_question_id": "" if conditions else (action.condition_question_id or ""),
            "condition_operator": "" if conditions else (action.condition_operator or ""),
            "condition_value": "" if conditions else (action.condition_value or ""),
            "conditions_json": json.dumps(conditions, ensure_ascii=False),
            "condition_logic": getattr(action, "condition_logic", "and") or "and",
            "random_group": getattr(action, "random_group", "") or "",
            "random_weight": getattr(action, "random_weight", 1) or 1,
        })
    return result


def _flow_context(
    request: Request,
    db: Session,
    flow: EntryFlow | None = None,
    *,
    editor_state: dict | None = None,
    editor_actions: list[dict] | None = None,
    editor_errors: list[dict] | None = None,
    submission_token: str | None = None,
    editor_conflict: dict | None = None,
):
    system = db.get(SystemSetting, 1)
    timezone_name = valid_timezone(system.timezone_name if system else DEFAULT_TIMEZONE)
    state = editor_state or _flow_state(flow)
    actions = editor_actions if editor_actions is not None else _actions_from_flow(flow, timezone_name)
    referenced_ids = {_int(item.get("questionnaire_id"), 0) for item in actions if isinstance(item, dict)}
    referenced_ids.add(_int(state.get("registration_questionnaire_id"), 0))
    referenced_ids.discard(0)
    questionnaires = db.scalars(
        select(Questionnaire)
        .where(or_(Questionnaire.status == "active", Questionnaire.id.in_(referenced_ids)) if referenced_ids else Questionnaire.status == "active")
        .order_by(Questionnaire.name)
    ).all()
    registration_questionnaires = []
    for item in questionnaires:
        published = latest_published_version(db, item)
        if item.objective == "registration" and item.response_mode == "identified":
            registration_questionnaires.append(item)
        elif published:
            published_config = version_config(published)
            if published_config.objective == "registration" and published_config.response_mode == "identified":
                registration_questionnaires.append(item)
    view = SimpleNamespace(id=flow.id if flow else None, **{key: value for key, value in state.items() if key not in {"profiles", "service_options", "service_status_options"}})
    action_views = [SimpleNamespace(**item) for item in actions]
    versions_by_questionnaire: dict[str, list[dict]] = {}
    version_definitions: dict[str, list[dict]] = {}
    questionnaire_definitions: dict[str, list[dict]] = {}
    questionnaire_meta: dict[str, dict] = {}
    registration_summaries: dict[str, dict] = {}
    for questionnaire in questionnaires:
        versions = db.scalars(select(QuestionnaireVersion).options(
            selectinload(QuestionnaireVersion.questions)
        ).where(
            QuestionnaireVersion.questionnaire_id == questionnaire.id,
            QuestionnaireVersion.status == "published",
        ).order_by(QuestionnaireVersion.version_number.desc())).all()
        versions_by_questionnaire[str(questionnaire.id)] = [
            {"id": version.id, "number": version.version_number, "published_at": version.published_at.isoformat()}
            for version in versions
        ]
        for version in versions:
            version_definitions[str(version.id)] = [
                {"id": question.original_question_id, "text": question.text, "type": question.type, "binding": question.data_binding or "", "options": json_list(question.options_json)}
                for question in version.questions
            ]
        questionnaire_definitions[str(questionnaire.id)] = version_definitions.get(str(versions[0].id), []) if versions else []
        questionnaire_meta[str(questionnaire.id)] = {
            "name": questionnaire.name,
            "status": questionnaire.status,
            "published": bool(versions),
            "response_mode": questionnaire.response_mode,
            "opening_message": questionnaire.opening_message or "",
            "max_attempts": questionnaire.max_attempts or 1,
            "retry_hours": questionnaire.retry_hours or 24,
        }
        definitions = questionnaire_definitions[str(questionnaire.id)]
        binding_counts: dict[str, int] = {}
        incompatible: list[str] = []
        compatible_types = {
            "lead.name": {"text"}, "lead.phone": {"text"}, "lead.city": {"text", "choice"},
            "pet.name": {"text"}, "pet.species": {"text", "choice"},
            "visit.service_type": {"text", "choice"}, "visit.reason": {"text", "choice"},
        }
        for definition in definitions:
            binding = definition.get("binding") or ""
            if not binding:
                continue
            binding_counts[binding] = binding_counts.get(binding, 0) + 1
            if binding in compatible_types and definition.get("type") not in compatible_types[binding]:
                incompatible.append(binding)
        registration_summaries[str(questionnaire.id)] = {
            "published": bool(versions),
            "bindings": binding_counts,
            "duplicates": sorted(binding for binding, amount in binding_counts.items() if amount > 1),
            "incompatible": sorted(set(incompatible)),
        }

    user = current_user(request, db)
    cities = _cities_for_user(db, user) if user else []
    city_ids_allowed = {city.id for city in cities}
    devices = db.scalars(
        select(Device).where(Device.city_id.in_(city_ids_allowed)).order_by(Device.name)
    ).all() if city_ids_allowed else []
    if editor_state is not None:
        selected_device_ids = {_int(value, 0) for value in state.get("device_ids", [])}
    elif flow and flow.id:
        saved_device_ids = {_int(value, 0) for value in state.get("device_ids", [])}
        selected_device_ids = saved_device_ids or {device.id for device in devices if device.default_entry_flow_id == flow.id}
    else:
        selected_device_ids = set()
    last_editor = db.get(User, flow.last_edited_by_id) if flow and flow.last_edited_by_id else None
    effective_token = submission_token or new_submission_token()
    return ctx(
        request,
        db,
        flow=view,
        persisted_flow=flow,
        questionnaires=questionnaires,
        registration_questionnaires=registration_questionnaires,
        flow_actions=action_views,
        questionnaire_definitions=questionnaire_definitions,
        questionnaire_versions=versions_by_questionnaire,
        questionnaire_version_definitions=version_definitions,
        questionnaire_meta=questionnaire_meta,
        registration_summaries=registration_summaries,
        flow_cities=cities,
        flow_devices=devices,
        selected_device_ids=selected_device_ids,
        editor_timezone=timezone_name,
        flow_profiles=list(state.get("profiles") or []),
        service_options=[line for line in str(state.get("service_options") or "").splitlines()],
        service_status_options=[line for line in str(state.get("service_status_options") or "").splitlines()],
        editor_errors=editor_errors or [],
        editor_submission_token=effective_token,
        editor_had_error=bool(editor_errors),
        editor_saved=request.query_params.get("saved") == "1",
        editor_entity_key=str(flow.id) if flow else f"new:{effective_token.replace('.', '_')}",
        editor_revision=int(flow.revision or 1) if flow else 0,
        editor_updated_at=flow.updated_at.isoformat() if flow and flow.updated_at else "",
        editor_last_user=last_editor.name if last_editor else "Sistema",
        editor_conflict=editor_conflict,
    )


def _flow_form_state(form, flow: EntryFlow | None = None) -> dict:
    previous = _flow_state(flow)
    visual_editor = str(form.get("flow_schema") or "") in {"3.2.2", "3.2.4", "3.2.5", "3.3.0", "3.3.1", "3.3.2", "3.3.3", "3.3.4", "3.4.0", "3.4.1", "3.5.0", "3.5.1", "3.5.2", "3.5.3", "3.5.4", "3.5.5", "3.5.6", "3.5.7", "3.6.0"}
    return {
        "name": str(form.get("name") or ""),
        "description": str(form.get("description") or ""),
        "status": str(form.get("status") or "draft"),
        "profiles": [value for value in ("kiosk", "interviewer") if _bool(form, f"profile_{value}")],
        "welcome_title": str(form.get("welcome_title") or ""),
        "welcome_text": str(form.get("welcome_text") or ""),
        "registration_questionnaire_id": str(form.get("registration_questionnaire_id") or ""),
        "allow_existing_lookup": _bool(form, "allow_existing_lookup"),
        "collect_city": _bool(form, "collect_city") if "collect_city" in form else previous["collect_city"],
        "collect_neighborhood": _bool(form, "collect_neighborhood") if "collect_neighborhood" in form else previous["collect_neighborhood"],
        "allow_no_pet": _bool(form, "allow_no_pet"),
        "max_pets": str(form.get("max_pets") or ""),
        "service_options": str(form.get("service_options")) if "service_options" in form else previous["service_options"],
        "service_status_options": str(form.get("service_status_options")) if "service_status_options" in form else previous["service_status_options"],
        "phone_verification_mode": str(form.get("phone_verification_mode") or ""),
        "phone_verification_timeout": str(form.get("phone_verification_timeout") or ""),
        "allow_manual_confirmation": _bool(form, "allow_manual_confirmation"),
        "consent_research_enabled": _bool(form, "consent_research_enabled") if visual_editor or "consent_research_enabled" in form else previous["consent_research_enabled"],
        "consent_marketing_enabled": _bool(form, "consent_marketing_enabled") if visual_editor or "consent_marketing_enabled" in form else previous["consent_marketing_enabled"],
        "consent_terms_enabled": _bool(form, "consent_terms_enabled") if visual_editor or "consent_terms_enabled" in form else previous["consent_terms_enabled"],
        "city_ids": [str(value) for value in form.getlist("city_ids")] if visual_editor else previous["city_ids"],
        "device_ids": [str(value) for value in form.getlist("device_ids")] if visual_editor else previous["device_ids"],
        "consent_terms_version": str(form.get("consent_terms_version") or ""),
        "consent_research_text": str(form.get("consent_research_text") or ""),
        "consent_marketing_text": str(form.get("consent_marketing_text") or ""),
        "closing_title": str(form.get("closing_title") or ""),
        "closing_text": str(form.get("closing_text") or ""),
    }


def _flow_form_actions(form) -> list[dict]:
    count = max(0, min(30, _int(form.get("actions_count"), 0)))
    result: list[dict] = []
    for index in range(count):
        prefix = f"action_{index}_"
        action_id = _int(form.get(prefix + "id"), 0)
        result.append({
            "id": action_id or "",
            "item_key": stable_editor_key("action", form.get(prefix + "item_key"), action_id or None),
            "name": str(form.get(prefix + "name") or ""),
            "trigger": str(form.get(prefix + "trigger") or ""),
            "questionnaire_id": str(form.get(prefix + "questionnaire_id") or ""),
            "version_mode": str(form.get(prefix + "version_mode") or "latest_published"),
            "fixed_version_id": str(form.get(prefix + "fixed_version_id") or ""),
            "channel": str(form.get(prefix + "channel") or ""),
            "delay_value": str(form.get(prefix + "delay_value") or ""),
            "delay_unit": str(form.get(prefix + "delay_unit") or ""),
            # Rascunhos produzidos pelo seletor 3.4.0 podiam enviar este campo
            # vazio ao representar uma ação imediata. Intervalo zero é o
            # equivalente persistido e mantém compatibilidade com esses dados.
            "schedule_mode": str(form.get(prefix + "schedule_mode") or "exact_interval"),
            "fixed_scheduled_at": str(form.get(prefix + "fixed_scheduled_at") or ""),
            "send_hour": str(form.get(prefix + "send_hour") or ""),
            "require_confirmation": _bool(form, prefix + "require_confirmation"),
            "per_pet": _bool(form, prefix + "per_pet"),
            "active": _bool(form, prefix + "active"),
            "depends_on_key": str(form.get(prefix + "depends_on_key") or "").strip(),
            "legacy_depends_on_position": _int(form.get(prefix + "depends_on_position"), 0),
            "depends_on_action_id": "",
            "condition_question_id": str(form.get(prefix + "condition_question_id") or ""),
            "condition_operator": str(form.get(prefix + "condition_operator") or ""),
            "condition_value": str(form.get(prefix + "condition_value") or ""),
            "conditions_json": str(form.get(prefix + "conditions_json") or "[]"),
            "condition_logic": str(form.get(prefix + "condition_logic") or "and"),
            "random_group": str(form.get(prefix + "random_group") or "").strip(),
            "random_weight": str(form.get(prefix + "random_weight") or "1"),
        })
    # Compatibilidade apenas para formulários antigos: a partir da 3.1.2 o
    # navegador e o backend trabalham exclusivamente com a chave estável.
    for item in result:
        legacy_position = _int(item.pop("legacy_depends_on_position", 0), 0)
        if not item["depends_on_key"] and 0 < legacy_position <= len(result):
            item["depends_on_key"] = result[legacy_position - 1]["item_key"]
    return result


def _fixed_schedule_utc(db: Session, value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    system = db.get(SystemSetting, 1)
    zone = ZoneInfo(valid_timezone(system.timezone_name if system else DEFAULT_TIMEZONE))
    localized = parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
    return localized.astimezone(timezone.utc).replace(tzinfo=None)


def _validate_flow_submission(db: Session, state: dict, actions: list[dict], flow: EntryFlow | None) -> list[dict]:
    errors: list[dict] = []
    if not state["name"].strip():
        errors.append(error("identificacao", "name", "Informe o nome do fluxo."))
    if state["status"] not in {"draft", "active", "paused"}:
        errors.append(error("identificacao", "status", "Escolha um status válido."))
    if not state["profiles"]:
        errors.append(error("identificacao", "profiles", "Selecione Quiosque ou Entrevistador."))
    if not state["welcome_title"].strip():
        errors.append(error("identificacao", "welcome_title", "Informe o título de boas-vindas."))
    if not state["welcome_text"].strip():
        errors.append(error("identificacao", "welcome_text", "Informe o texto de apresentação."))
    max_pets = _int(state["max_pets"], 0)
    if not 1 <= max_pets <= 20:
        errors.append(error("coleta", "max_pets", "O máximo de pets deve ficar entre 1 e 20."))
    if state["phone_verification_mode"] not in {"required", "send_continue", "future_only", "none"}:
        errors.append(error("confirmacao", "phone_verification_mode", "Escolha um comportamento de confirmação válido."))
    timeout = _int(state["phone_verification_timeout"], 0)
    if state["phone_verification_mode"] != "none" and not 30 <= timeout <= 1800:
        errors.append(error("confirmacao", "phone_verification_timeout", "O tempo de espera deve ficar entre 30 e 1800 segundos."))
    consent_requirements = []
    if state["consent_terms_enabled"]:
        consent_requirements.append(("consent_terms_version", "Informe a versão dos termos."))
    if state["consent_research_enabled"]:
        consent_requirements.append(("consent_research_text", "Informe o texto de consentimento para pesquisas."))
    if state["consent_marketing_enabled"]:
        consent_requirements.append(("consent_marketing_text", "Informe o texto de consentimento para campanhas."))
    for field, message in consent_requirements:
        if not state[field].strip():
            errors.append(error("consentimento", field, message))
    for field, message in (("closing_title", "Informe o título de encerramento."), ("closing_text", "Informe a mensagem de encerramento.")):
        if not state[field].strip():
            errors.append(error("identificacao", field, message))

    registration_id = _int(state["registration_questionnaire_id"], 0)
    registration = db.get(Questionnaire, registration_id) if registration_id else None
    registration_version = latest_published_version(db, registration) if registration else None
    registration_config = version_config(registration_version) if registration_version else None
    if not registration or not registration_config or registration_config.objective != "registration" or registration_config.response_mode != "identified":
        errors.append(error("coleta", "registration_questionnaire_id", "Selecione um questionário identificado de Cadastro estruturado."))
    else:
        if state["status"] == "active" and registration.status != "active":
            errors.append(error("coleta", "registration_questionnaire_id", "Ative o Cadastro estruturado antes de ativar o fluxo."))
        bindings = {question.data_binding for question in registration_version.questions}
        if not {"lead.name", "lead.phone"}.issubset(bindings):
            errors.append(error("coleta", "registration_questionnaire_id", "O Cadastro estruturado precisa conter Nome completo e WhatsApp."))
        binding_counts: dict[str, int] = {}
        compatible_types = {
            "lead.name": {"text"}, "lead.phone": {"text"}, "lead.city": {"text", "choice"},
            "pet.name": {"text"}, "pet.species": {"text", "choice"},
            "visit.service_type": {"text", "choice"}, "visit.reason": {"text", "choice"},
        }
        incompatible = []
        for question in registration_version.questions:
            binding = question.data_binding or ""
            if not binding:
                continue
            binding_counts[binding] = binding_counts.get(binding, 0) + 1
            if binding in compatible_types and question.type not in compatible_types[binding]:
                incompatible.append(binding)
        if any(amount > 1 for amount in binding_counts.values()):
            errors.append(error("coleta", "registration_questionnaire_id", "O Cadastro estruturado possui bindings duplicados."))
        if incompatible:
            errors.append(error("coleta", "registration_questionnaire_id", "O Cadastro estruturado possui pergunta incompatível com o binding."))

    if not actions:
        errors.append(error("acoes", "actions_count", "Adicione pelo menos uma ação ao fluxo."))
    existing_ids = {action.id for action in flow.actions} if flow else set()
    submitted_ids: set[int] = set()
    submitted_keys: set[str] = set()
    questionnaires: dict[int, Questionnaire | None] = {}
    action_versions: dict[str, QuestionnaireVersion | None] = {}
    by_key = {str(item["item_key"]): (index, item) for index, item in enumerate(actions, start=1)}
    for index, item in enumerate(actions, start=1):
        item_key = str(item["item_key"])
        if item_key in submitted_keys:
            errors.append(error("acoes", "item_key", f"A ação {index} repetiu uma identidade interna.", item_key))
        submitted_keys.add(item_key)
        action_id = _int(item["id"], 0)
        if action_id:
            if action_id not in existing_ids or action_id in submitted_ids:
                errors.append(error("acoes", "id", f"A ação {index} não pertence a este fluxo ou foi repetida.", item_key))
            submitted_ids.add(action_id)
        if not item["name"].strip():
            errors.append(error("acoes", "name", f"Informe o nome da ação {index}.", item_key))
        if item["trigger"] not in {"before_confirmation", "after_registration", "after_confirmation", "after_action"}:
            errors.append(error("acoes", "trigger", "Escolha quando a ação acontece.", item_key))
        if item["channel"] not in {"whatsapp", "screen_identified", "screen_anonymous"}:
            errors.append(error("acoes", "channel", "Escolha um canal válido.", item_key))
        questionnaire_id = _int(item["questionnaire_id"], 0)
        questionnaire = questionnaires.setdefault(questionnaire_id, db.get(Questionnaire, questionnaire_id) if questionnaire_id else None)
        if not questionnaire:
            errors.append(error("acoes", "questionnaire_id", f"Selecione o questionário da ação {index}.", item_key))
            action_versions[item_key] = None
        else:
            latest = latest_published_version(db, questionnaire)
            selected_version = latest
            if not latest:
                errors.append(error("acoes", "questionnaire_id", "Publique uma versão deste questionário antes de usá-lo no fluxo.", item_key))
            if item["version_mode"] not in {"latest_published", "fixed"}:
                errors.append(error("acoes", "version_mode", "Escolha a política de versão da ação.", item_key))
            if item["version_mode"] == "fixed":
                fixed = db.get(QuestionnaireVersion, _int(item["fixed_version_id"], 0))
                if not fixed or fixed.questionnaire_id != questionnaire.id or fixed.status != "published":
                    errors.append(error("acoes", "fixed_version_id", "Escolha uma versão publicada deste questionário.", item_key))
                else:
                    selected_version = fixed
            selected_config = version_config(selected_version) if selected_version else None
            action_versions[item_key] = selected_version
            if state["status"] == "active" and questionnaire.status != "active":
                errors.append(error("acoes", "questionnaire_id", "Ative este questionário antes de ativar o fluxo.", item_key))
            if selected_config and item["channel"] == "whatsapp" and selected_config.response_mode == "anonymous":
                errors.append(error("acoes", "channel", "Pesquisas anônimas não podem ser enviadas pelo WhatsApp.", item_key))
            if selected_config and item["channel"] == "screen_anonymous" and selected_config.response_mode != "anonymous":
                errors.append(error("acoes", "channel", "Escolha um questionário anônimo para este canal.", item_key))
            if selected_config and item["channel"] == "screen_identified" and selected_config.response_mode == "anonymous":
                errors.append(error("acoes", "channel", "Escolha um questionário identificado para este canal.", item_key))
        delay = _int(item["delay_value"], -1)
        if delay < 0:
            errors.append(error("acoes", "delay_value", "O atraso não pode ser negativo.", item_key))
        if item["delay_unit"] not in {"minutes", "hours", "days"}:
            errors.append(error("acoes", "delay_unit", "Escolha uma unidade válida.", item_key))
        if item["schedule_mode"] not in {"exact_interval", "day_hour", "next_allowed", "fixed_datetime"}:
            errors.append(error("acoes", "schedule_mode", "Escolha uma forma de agendamento válida.", item_key))
        if item["schedule_mode"] == "fixed_datetime":
            fixed_at = _fixed_schedule_utc(db, item["fixed_scheduled_at"])
            if not fixed_at:
                errors.append(error("acoes", "fixed_scheduled_at", "Informe uma data e hora válidas.", item_key))
            elif fixed_at <= utcnow():
                errors.append(error("acoes", "fixed_scheduled_at", "A data e hora precisam estar no futuro.", item_key))
        send_hour = _int(item["send_hour"], -1)
        if not 0 <= send_hour <= 23:
            errors.append(error("acoes", "send_hour", "A hora preferencial deve ficar entre 0 e 23.", item_key))
        if item["per_pet"] and str(item["channel"]).startswith("screen_"):
            errors.append(error("acoes", "per_pet", "Ações por pet devem usar o WhatsApp.", item_key))
        if item["trigger"] == "before_confirmation":
            if item["channel"] != "screen_identified":
                errors.append(error("acoes", "channel", "Etapas antes da confirmação devem usar Tela identificada.", item_key))
            if delay > 0 or item["schedule_mode"] == "fixed_datetime":
                errors.append(error("acoes", "delay_value", "Etapas antes da confirmação precisam acontecer imediatamente.", item_key))
            if item["require_confirmation"]:
                errors.append(error("acoes", "require_confirmation", "Uma etapa anterior à confirmação não pode exigir WhatsApp confirmado.", item_key))
        if item["trigger"] == "after_action":
            parent_key = str(item["depends_on_key"] or "")
            parent_entry = by_key.get(parent_key)
            if not parent_key:
                errors.append(error("acoes", "depends_on_key", "Escolha uma ação anterior como dependência.", item_key))
                continue
            if parent_key == item_key:
                errors.append(error("acoes", "depends_on_key", "Uma ação não pode depender dela mesma.", item_key))
                continue
            if not parent_entry:
                errors.append(error("acoes", "depends_on_key", "A ação usada como dependência foi removida ou não existe.", item_key))
                continue
            parent_position, parent = parent_entry
            if parent_position >= index:
                errors.append(error("acoes", "depends_on_key", "A dependência precisa estar antes desta ação no fluxo.", item_key))
            if str(item["channel"]).startswith("screen_") and not str(parent["channel"]).startswith("screen_"):
                errors.append(error("acoes", "channel", "Uma ação condicional na tela precisa depender de outra ação exibida na tela.", item_key))
            if str(item["channel"]).startswith("screen_") and (delay > 0 or item["schedule_mode"] == "fixed_datetime"):
                errors.append(error("acoes", "delay_value", "A continuação condicional na tela precisa acontecer imediatamente.", item_key))
            if parent["per_pet"] and not item["per_pet"]:
                errors.append(error("acoes", "per_pet", "Uma ação geral não pode depender de uma ação executada uma vez por pet.", item_key))
            question_id = _int(item["condition_question_id"], 0)
            operator = item["condition_operator"]
            if question_id:
                parent_questionnaire_id = _int(parent["questionnaire_id"], 0)
                parent_version = (
                    db.get(QuestionnaireVersion, _int(parent.get("fixed_version_id"), 0))
                    if parent.get("version_mode") == "fixed"
                    else latest_published_version(db, parent_questionnaire_id)
                )
                valid_question_ids = {
                    question.original_question_id for question in (parent_version.questions if parent_version else [])
                }
                if not parent_version or parent_version.questionnaire_id != parent_questionnaire_id or question_id not in valid_question_ids:
                    errors.append(error("acoes", "condition_question_id", "A pergunta da condição precisa pertencer à ação anterior.", item_key))
                if operator not in {"equals", "not_equals", "contains", "not_contains", "gte", "lte", "answered", "not_answered"}:
                    errors.append(error("acoes", "condition_operator", "Escolha como avaliar esta resposta.", item_key))
                elif operator not in {"answered", "not_answered"} and not item["condition_value"].strip():
                    errors.append(error("acoes", "condition_value", "Informe o valor esperado da condição.", item_key))
            elif operator or item["condition_value"].strip():
                errors.append(error("acoes", "condition_question_id", "Selecione a pergunta usada pela condição.", item_key))

    allowed_operators = {"equals", "not_equals", "contains", "not_contains", "gte", "lte", "answered", "not_answered"}
    for index, item in enumerate(actions, start=1):
        item_key = str(item["item_key"])
        if item.get("condition_logic") not in {"and", "or"}:
            errors.append(error("acoes", "condition_logic", "Escolha se todas ou qualquer condição deve ser atendida.", item_key))
        try:
            conditions = json.loads(str(item.get("conditions_json") or "[]"))
        except (TypeError, ValueError):
            conditions = None
        if not isinstance(conditions, list) or len(conditions) > 10:
            errors.append(error("acoes", "conditions_json", "As condições desta ação estão inválidas ou excedem o limite de 10.", item_key))
            conditions = []
        for condition in conditions:
            if not isinstance(condition, dict):
                errors.append(error("acoes", "conditions_json", "Remova a condição inválida e adicione-a novamente.", item_key))
                continue
            source_key = str(condition.get("source_key") or "")
            question_id = _int(condition.get("question_id"), 0)
            operator = str(condition.get("operator") or "")
            expected = str(condition.get("value") or "").strip()
            source_version = None
            if source_key == "registration":
                source_version = registration_version
            else:
                source_entry = by_key.get(source_key)
                if not source_entry:
                    errors.append(error("acoes", "conditions_json", "A origem de uma condição foi removida.", item_key))
                    continue
                source_position, source_action = source_entry
                if source_position >= index:
                    errors.append(error("acoes", "conditions_json", "A condição só pode usar respostas já coletadas anteriormente.", item_key))
                if source_action["channel"] == "screen_anonymous":
                    errors.append(error("acoes", "conditions_json", "Respostas anônimas não podem decidir uma ação identificada.", item_key))
                source_version = action_versions.get(source_key)
            question = next((q for q in (source_version.questions if source_version else []) if q.original_question_id == question_id), None)
            if not question:
                errors.append(error("acoes", "conditions_json", "Selecione uma pergunta publicada da origem escolhida.", item_key))
                continue
            if operator not in allowed_operators:
                errors.append(error("acoes", "conditions_json", "Escolha um operador válido para a condição.", item_key))
            elif operator not in {"answered", "not_answered"} and not expected:
                errors.append(error("acoes", "conditions_json", "Selecione ou informe o valor esperado da condição.", item_key))
            if operator in {"equals", "not_equals"} and question.type in {"choice", "multiple_choice", "yes_no"} and expected:
                choices = json_list(question.options_json)
                if question.type == "yes_no" and not choices:
                    choices = [{"label": "Sim", "value": "sim"}, {"label": "Não", "value": "nao"}]
                accepted = {normalize_text(str(option.get("value") or option.get("label") or "")) for option in choices if isinstance(option, dict)}
                accepted.update(normalize_text(str(option.get("label") or "")) for option in choices if isinstance(option, dict))
                if accepted and normalize_text(expected) not in accepted:
                    errors.append(error("acoes", "conditions_json", "O valor escolhido não pertence às opções publicadas da pergunta.", item_key))
        random_group = str(item.get("random_group") or "").strip()
        if random_group and not 1 <= _int(item.get("random_weight"), 0) <= 100:
            errors.append(error("acoes", "random_weight", "O peso do sorteio deve ficar entre 1 e 100.", item_key))

    def is_pre_confirmation(item_key: str, trail: set[str] | None = None) -> bool:
        entry = by_key.get(item_key)
        if not entry:
            return False
        item = entry[1]
        if item["trigger"] == "before_confirmation":
            return True
        if item["trigger"] != "after_action":
            return False
        trail = set(trail or set())
        if item_key in trail:
            return False
        trail.add(item_key)
        return is_pre_confirmation(str(item.get("depends_on_key") or ""), trail)

    for item in actions:
        item_key = str(item["item_key"])
        if is_pre_confirmation(item_key):
            if item["channel"] != "screen_identified":
                errors.append(error("acoes", "channel", "Todo o caminho anterior à confirmação precisa usar Tela identificada.", item_key))
            if item["require_confirmation"]:
                errors.append(error("acoes", "require_confirmation", "Este caminho acontece antes da confirmação do WhatsApp.", item_key))
            if _int(item["delay_value"], 0) > 0 or item["schedule_mode"] == "fixed_datetime":
                errors.append(error("acoes", "delay_value", "Todo o caminho anterior à confirmação precisa acontecer imediatamente.", item_key))

    random_groups: dict[str, list[dict]] = {}
    for item in actions:
        group = str(item.get("random_group") or "").strip()
        if group:
            random_groups.setdefault(group, []).append(item)
    for group, members in random_groups.items():
        signatures = {(item["trigger"], str(item.get("depends_on_key") or "")) for item in members}
        if len(signatures) > 1:
            for item in members:
                errors.append(error("acoes", "random_group", f"As ações do sorteio “{group}” precisam ter o mesmo gatilho e a mesma ação anterior.", str(item["item_key"])))

    dependencies = {
        str(item["item_key"]): str(item["depends_on_key"] or "")
        for item in actions
        if item["trigger"] == "after_action" and str(item["depends_on_key"] or "") in by_key
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_keys: set[str] = set()

    def visit(key: str, path: list[str]) -> None:
        if key in visited:
            return
        if key in visiting:
            start = path.index(key) if key in path else 0
            cycle_keys.update(path[start:])
            return
        visiting.add(key)
        parent_key = dependencies.get(key)
        if parent_key:
            visit(parent_key, [*path, key])
        visiting.discard(key)
        visited.add(key)

    for dependency_key in dependencies:
        visit(dependency_key, [])
    for cycle_key in cycle_keys:
        errors.append(error("acoes", "depends_on_key", "As dependências formam um ciclo. Escolha outra ação anterior.", cycle_key))
    if not state["consent_research_enabled"] and any(item["active"] and item["channel"] == "whatsapp" for item in actions):
        errors.append(error("consentimento", "consent_research_enabled", "Ative o consentimento para pesquisas ou remova as ações de WhatsApp."))
    return errors


def _apply_flow_state(flow: EntryFlow, state: dict) -> None:
    flow.name = state["name"].strip()
    flow.description = state["description"].strip() or None
    flow.status = state["status"]
    flow.profiles_json = json.dumps(state["profiles"], ensure_ascii=False)
    flow.welcome_title = state["welcome_title"].strip()
    flow.welcome_text = state["welcome_text"].strip()
    flow.registration_questionnaire_id = _int(state["registration_questionnaire_id"], 0) or None
    flow.allow_existing_lookup = state["allow_existing_lookup"]
    flow.collect_city = state["collect_city"]
    flow.collect_neighborhood = state["collect_neighborhood"]
    flow.allow_no_pet = state["allow_no_pet"]
    flow.max_pets = _int(state["max_pets"], 10)
    flow.service_options_json = json.dumps([line.strip() for line in state["service_options"].splitlines() if line.strip()], ensure_ascii=False)
    flow.service_status_options_json = json.dumps([line.strip() for line in state["service_status_options"].splitlines() if line.strip()], ensure_ascii=False)
    flow.phone_verification_mode = state["phone_verification_mode"]
    flow.phone_verification_timeout = _int(state["phone_verification_timeout"], 180)
    flow.allow_manual_confirmation = state["allow_manual_confirmation"]
    flow.consent_research_enabled = state["consent_research_enabled"]
    flow.consent_marketing_enabled = state["consent_marketing_enabled"]
    flow.consent_terms_enabled = state["consent_terms_enabled"]
    flow.consent_terms_version = state["consent_terms_version"].strip()
    flow.consent_research_text = state["consent_research_text"].strip()
    flow.consent_marketing_text = state["consent_marketing_text"].strip()
    flow.closing_title = state["closing_title"].strip()
    flow.closing_text = state["closing_text"].strip()


def _sync_flow_action_data(db: Session, flow: EntryFlow, actions: list[dict]) -> None:
    existing = {action.id: action for action in flow.actions if action.id}
    for action in existing.values():
        action.depends_on_action_id = None
    db.flush()
    retained: set[int] = set()
    ordered: list[EntryFlowAction] = []
    action_by_key: dict[str, EntryFlowAction] = {}
    for index, item in enumerate(actions, start=1):
        action_id = _int(item["id"], 0)
        action = existing.get(action_id)
        if action is None:
            action = EntryFlowAction()
            flow.actions.append(action)
        elif action_id:
            retained.add(action_id)
        action.position = index
        action.name = item["name"].strip()[:160]
        action.trigger = item["trigger"]
        action.questionnaire_id = _int(item["questionnaire_id"], 0)
        action.version_mode = item["version_mode"] if item["version_mode"] in {"latest_published", "fixed"} else "latest_published"
        action.fixed_version_id = _int(item["fixed_version_id"], 0) if action.version_mode == "fixed" else None
        action.channel = item["channel"]
        action.delay_value = _int(item["delay_value"], 0)
        action.delay_unit = item["delay_unit"]
        action.schedule_mode = item["schedule_mode"]
        action.fixed_scheduled_at = _fixed_schedule_utc(db, item.get("fixed_scheduled_at", "")) if action.schedule_mode == "fixed_datetime" else None
        action.send_hour = _int(item["send_hour"], 10)
        action.require_confirmation = item["require_confirmation"]
        action.per_pet = item["per_pet"]
        action.active = item["active"]
        action.condition_question_id = _int(item["condition_question_id"], 0) or None
        action.condition_operator = item["condition_operator"] or None
        action.condition_value = item["condition_value"].strip()[:300] or None
        action.conditions_json = "[]"
        action.condition_logic = item.get("condition_logic") if item.get("condition_logic") in {"and", "or"} else "and"
        action.random_group = str(item.get("random_group") or "").strip()[:80] or None
        action.random_weight = max(1, min(_int(item.get("random_weight"), 1), 100))
        ordered.append(action)
        action_by_key[str(item["item_key"])] = action
    for action_id, action in existing.items():
        if action_id not in retained:
            flow.actions.remove(action)
    db.flush()
    for action, item in zip(ordered, actions):
        parent = action_by_key.get(str(item["depends_on_key"] or "")) if item["trigger"] == "after_action" else None
        action.depends_on_action_id = parent.id if parent else None
        saved_conditions = []
        try:
            raw_conditions = json.loads(str(item.get("conditions_json") or "[]"))
        except (TypeError, ValueError):
            raw_conditions = []
        for condition in raw_conditions if isinstance(raw_conditions, list) else []:
            if not isinstance(condition, dict):
                continue
            source_key = str(condition.get("source_key") or "registration")
            source = action_by_key.get(source_key) if source_key != "registration" else None
            question_id = _int(condition.get("question_id"), 0)
            if not question_id:
                continue
            saved_conditions.append({
                "source_action_id": source.id if source else None,
                "question_id": question_id,
                "operator": str(condition.get("operator") or "answered")[:30],
                "value": str(condition.get("value") or "")[:300],
            })
        action.conditions_json = json.dumps(saved_conditions, ensure_ascii=False)
        if saved_conditions:
            first = saved_conditions[0]
            action.condition_question_id = first["question_id"]
            action.condition_operator = first["operator"]
            action.condition_value = first["value"] or None
        elif not parent:
            action.condition_question_id = None
            action.condition_operator = None
            action.condition_value = None
    logger.info("Fluxo %s salvo com %s ações e dependências resolvidas por chave estável.", flow.id, len(ordered))


def _sync_flow_devices(db: Session, flow: EntryFlow, state: dict, user: User) -> None:
    allowed_cities = {city.id for city in _cities_for_user(db, user)}
    allowed_devices = db.scalars(select(Device).where(Device.city_id.in_(allowed_cities))).all() if allowed_cities else []
    requested_cities = {_int(value, 0) for value in state.get("city_ids", [])}
    selected = {_int(value, 0) for value in state.get("device_ids", [])}
    selected.intersection_update({device.id for device in allowed_devices})
    flow.city_ids_json = json.dumps(sorted(requested_cities.intersection(allowed_cities)), ensure_ascii=False)
    flow.device_ids_json = json.dumps(sorted(selected), ensure_ascii=False)
    for device in allowed_devices:
        if device.id in selected:
            device.default_entry_flow_id = flow.id
        elif device.default_entry_flow_id == flow.id:
            device.default_entry_flow_id = None


def _flow_error_response(request: Request, db: Session, flow: EntryFlow | None, state: dict, actions: list[dict], errors: list[dict], token: str):
    db.rollback()
    return request.app.state.templates.TemplateResponse(
        request,
        "entry_flow_editor.html",
        _flow_context(request, db, flow, editor_state=state, editor_actions=actions, editor_errors=errors, submission_token=token or new_submission_token()),
        status_code=400,
    )


def _flow_conflict_response(request: Request, db: Session, flow: EntryFlow, state: dict, actions: list[dict], token: str, submitted_revision: int):
    last_editor = db.get(User, flow.last_edited_by_id) if flow.last_edited_by_id else None
    conflict = {
        "submitted_revision": submitted_revision,
        "current_revision": int(flow.revision or 1),
        "updated_at": flow.updated_at.isoformat() if flow.updated_at else "",
        "last_user": last_editor.name if last_editor else "outro usuário",
    }
    return request.app.state.templates.TemplateResponse(
        request,
        "entry_flow_editor.html",
        _flow_context(request, db, flow, editor_state=state, editor_actions=actions, submission_token=token or new_submission_token(), editor_conflict=conflict),
        status_code=409,
    )


def _laboratory_result(db: Session, flow: EntryFlow, scenario: dict, isolated_action_id: int | None = None) -> dict:
    elapsed = max(0, min(_int(scenario.get("elapsed_minutes"), 0), 2_628_000))
    confirmed = bool(scenario.get("confirmed"))
    condition_matches = bool(scenario.get("condition_matches"))
    pets = max(0, min(_int(scenario.get("pets"), 1), 20))
    simulated_at = utcnow() + timedelta(minutes=elapsed)
    completed: set[int] = set()
    due_by_id: dict[int, int] = {}
    rows: list[dict] = []
    ordered_actions = sorted(flow.actions, key=lambda item: (item.position, item.id))
    random_choices: dict[tuple[str, str, int], int] = {}
    for action in ordered_actions:
        group = str(getattr(action, "random_group", "") or "").strip()
        if group:
            random_choices.setdefault((action.trigger, group, action.depends_on_action_id or 0), action.id)
    for action in ordered_actions:
        delay = max(0, action.delay_value or 0) * ({"minutes": 1, "hours": 60, "days": 1440}.get(action.delay_unit, 1440))
        parent_due = due_by_id.get(action.depends_on_action_id or 0, 0)
        due_minutes = parent_due + delay if action.trigger == "after_action" else delay
        if action.schedule_mode == "fixed_datetime" and action.fixed_scheduled_at:
            due_minutes = max(0, int((action.fixed_scheduled_at - utcnow()).total_seconds() // 60))
        due_by_id[action.id] = due_minutes
        ready, reason = True, "liberada"
        version = None
        try:
            version = resolve_action_version(db, action)
        except VersionConsistencyError as exc:
            ready, reason = False, str(exc)
        if ready and not action.active:
            ready, reason = False, "ação pausada"
        if ready and (action.require_confirmation or action.trigger == "after_confirmation") and not confirmed:
            ready, reason = False, "aguardando confirmação do WhatsApp"
        if ready and action.trigger == "after_action" and action.depends_on_action_id not in completed:
            ready, reason = False, "aguardando conclusão da ação anterior"
        if ready and action.condition_question_id and not condition_matches:
            ready, reason = False, "resposta não atende à condição"
        conditions_count = len(json_list(getattr(action, "conditions_json", "[]")))
        if ready and conditions_count and not condition_matches:
            ready, reason = False, "respostas não atendem ao grupo de condições"
        random_group = str(getattr(action, "random_group", "") or "").strip()
        if ready and random_group and random_choices.get((action.trigger, random_group, action.depends_on_action_id or 0)) != action.id:
            ready, reason = False, f"outro caminho do sorteio “{random_group}” foi selecionado"
        if ready and due_minutes > elapsed:
            ready, reason = False, f"libera após {due_minutes} minuto(s)"
        if ready and action.per_pet and pets == 0:
            ready, reason = False, "nenhum pet no cenário"
        config = version_config(version) if version else None
        channels = list(getattr(config, "channels", []) or []) if config else []
        expected_channel = "whatsapp" if action.channel == "whatsapp" else ("kiosk" if action.channel.startswith("screen_") else action.channel)
        if ready and channels and expected_channel not in channels and not (expected_channel == "kiosk" and "interviewer" in channels):
            ready, reason = False, "canal não publicado no questionário"
        if ready:
            completed.add(action.id)
        rows.append({
            "action_id": action.id, "position": action.position, "name": action.name, "ready": ready,
            "reason": reason, "execution_count": (pets if action.per_pet else 1) if ready else 0,
            "due_minutes": due_minutes, "channel": action.channel, "per_pet": bool(action.per_pet),
            "questionnaire_id": action.questionnaire_id,
            "version_id": version.id if version else None, "version_number": version.version_number if version else None,
            "question_count": len(version.questions) if version else 0,
            "conditions_count": conditions_count, "condition_logic": getattr(action, "condition_logic", "and"),
            "random_group": random_group, "random_weight": getattr(action, "random_weight", 1),
            "opening_message": str(getattr(config, "opening_message", "") or "") if config else "",
            "isolated": action.id == isolated_action_id,
        })
    visible = [item for item in rows if item["action_id"] == isolated_action_id] if isolated_action_id else rows
    return {"ok": True, "safe": True, "writes": 0, "flow_id": flow.id, "flow_revision": flow.revision, "simulated_at": simulated_at.isoformat(), "scenario": {"elapsed_minutes": elapsed, "confirmed": confirmed, "condition_matches": condition_matches, "pets": pets}, "isolated_action_id": isolated_action_id, "actions": visible, "trace": rows if isolated_action_id else []}


@router.post("/api/fluxos/{flow_id}/laboratorio/simular")
async def flow_laboratory(request: Request, flow_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator", "interviewer"})
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id))
    if not flow:
        raise HTTPException(404)
    payload = await request.json()
    return JSONResponse(_laboratory_result(db, flow, payload if isinstance(payload, dict) else {}))


@router.post("/api/fluxos/{flow_id}/laboratorio/acoes/{action_id}/simular")
async def flow_action_laboratory(request: Request, flow_id: int, action_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator", "interviewer"})
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id))
    if not flow or not any(item.id == action_id for item in flow.actions):
        raise HTTPException(404)
    payload = await request.json()
    return JSONResponse(_laboratory_result(db, flow, payload if isinstance(payload, dict) else {}, isolated_action_id=action_id))


@router.get("/fluxos/novo")
def flow_new(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    return request.app.state.templates.TemplateResponse(request, "entry_flow_editor.html", _flow_context(request, db))


@router.post("/fluxos/novo")
async def flow_create(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    form = await request.form()
    token = str(form.get("submission_token") or "")
    duplicate = completed_submission(request, token) or persisted_submission(db, token)
    if duplicate:
        return redirect(duplicate)
    state = _flow_form_state(form)
    actions = _flow_form_actions(form)
    errors = _validate_flow_submission(db, state, actions, None)
    if errors:
        return _flow_error_response(request, db, None, state, actions, errors, token)
    flow = EntryFlow()
    try:
        claim = add_submission_claim(db, token, "flow:create")
        _apply_flow_state(flow, state)
        flow.revision = 1
        flow.last_edited_by_id = user.id
        db.add(flow)
        db.flush()
        _sync_flow_devices(db, flow, state, user)
        _sync_flow_action_data(db, flow, actions)
        db.add(AuditLog(user_id=user.id, action="flow_create", entity="entry_flow", entity_id=flow.id, details=json.dumps({"revision": 1, "name": flow.name, "recovery_source": str(form.get("editor_recovery_source") or "direct")}, ensure_ascii=False)))
        destination = f"/fluxos/{flow.id}/editar?saved=1"
        if claim:
            claim.destination = destination
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = persisted_submission(db, token)
        if duplicate:
            return redirect(duplicate)
        return _flow_error_response(request, db, None, state, actions, [error("identificacao", "name", "Não foi possível salvar. Nenhuma parte do fluxo foi gravada.")], token)
    except Exception:
        return _flow_error_response(request, db, None, state, actions, [error("identificacao", "name", "Não foi possível salvar. Nenhuma parte do fluxo foi gravada.")], token)
    remember_submission(request, token, destination)
    flash(request, "Fluxo de entrada criado.")
    return redirect(destination)


@router.get("/fluxos/{flow_id}/editar")
def flow_edit(request: Request, flow_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id))
    if not flow:
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse(request, "entry_flow_editor.html", _flow_context(request, db, flow))


@router.post("/fluxos/{flow_id}/editar")
async def flow_update(request: Request, flow_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator"})
    flow = db.get(EntryFlow, flow_id)
    if not flow:
        raise HTTPException(404)
    form = await request.form()
    token = str(form.get("submission_token") or "")
    duplicate = completed_submission(request, token) or persisted_submission(db, token)
    if duplicate:
        return redirect(duplicate)
    state = _flow_form_state(form, flow)
    actions = _flow_form_actions(form)
    submitted_revision = _int(form.get("base_revision"), 0)
    if "base_revision" in form and submitted_revision != int(flow.revision or 1):
        return _flow_conflict_response(request, db, flow, state, actions, token, submitted_revision)
    errors = _validate_flow_submission(db, state, actions, flow)
    if errors:
        return _flow_error_response(request, db, flow, state, actions, errors, token)
    try:
        claim = add_submission_claim(db, token, "flow:update")
        old_revision = int(flow.revision or 1)
        old_snapshot = {"name": flow.name, "status": flow.status, "actions": len(flow.actions)}
        _apply_flow_state(flow, state)
        _sync_flow_devices(db, flow, state, user)
        _sync_flow_action_data(db, flow, actions)
        flow.revision = old_revision + 1
        flow.last_edited_by_id = user.id
        db.add(AuditLog(user_id=user.id, action="flow_update", entity="entry_flow", entity_id=flow.id, details=json.dumps({"old_revision": old_revision, "new_revision": flow.revision, "old": old_snapshot, "new": {"name": flow.name, "status": flow.status, "actions": len(actions)}, "recovery_source": str(form.get("editor_recovery_source") or "direct")}, ensure_ascii=False)))
        destination = f"/fluxos/{flow.id}/editar?saved=1"
        if claim:
            claim.destination = destination
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = persisted_submission(db, token)
        if duplicate:
            return redirect(duplicate)
        return _flow_error_response(request, db, flow, state, actions, [error("identificacao", "name", "Não foi possível salvar. A versão anterior do fluxo foi preservada.")], token)
    except Exception:
        return _flow_error_response(request, db, flow, state, actions, [error("identificacao", "name", "Não foi possível salvar. A versão anterior do fluxo foi preservada.")], token)
    remember_submission(request, token, destination)
    flash(request, "Fluxo de entrada atualizado.")
    return redirect(destination)


@router.post("/fluxos/{flow_id}/duplicar")
def flow_duplicate(request: Request, flow_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    source = db.get(EntryFlow, flow_id)
    if not source:
        raise HTTPException(404)
    values = {column.name: getattr(source, column.name) for column in EntryFlow.__table__.columns if column.name not in {"id", "created_at", "updated_at"}}
    values["name"] = f"Cópia de {source.name}"
    values["status"] = "draft"
    values["revision"] = 1
    values["last_edited_by_id"] = None
    row = EntryFlow(**values)
    db.add(row)
    db.flush()
    copied_by_source_id: dict[int, EntryFlowAction] = {}
    for action in source.actions:
        action_values = {
            column.name: getattr(action, column.name)
            for column in EntryFlowAction.__table__.columns
            if column.name not in {"id", "flow_id", "depends_on_action_id", "created_at", "updated_at"}
        }
        copied = EntryFlowAction(**action_values)
        row.actions.append(copied)
        copied_by_source_id[action.id] = copied
    db.flush()
    for action in source.actions:
        copied = copied_by_source_id[action.id]
        copied.depends_on_action_id = copied_by_source_id[action.depends_on_action_id].id if action.depends_on_action_id in copied_by_source_id else None
    db.commit()
    flash(request, "Fluxo duplicado como rascunho.")
    return redirect(f"/fluxos/{row.id}/editar")


@router.post("/fluxos/{flow_id}/status")
async def flow_status(request: Request, flow_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator"})
    row = db.get(EntryFlow, flow_id)
    if not row:
        raise HTTPException(404)
    form = await request.form()
    target = str(form.get("status") or "").strip()
    if target not in {"draft", "active", "paused", "archived"}:
        raise HTTPException(400, "Status inválido.")
    row.status = target
    db.commit()
    flash(request, {"archived": "Fluxo arquivado sem apagar o histórico.", "paused": "Fluxo pausado.", "active": "Fluxo ativado.", "draft": "Fluxo movido para rascunho."}[target])
    return redirect("/questionarios?arquivados=1" if target == "archived" else "/questionarios")


@router.get("/api/leads/buscar")
def lookup_lead(request: Request, phone: str = "", db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator", "interviewer"})
    setting = db.get(SystemSetting, 1)
    normalized = normalize_phone(phone, setting.default_country_code)
    lead = db.scalar(select(Lead).options(selectinload(Lead.pets)).where(Lead.phone_normalized == normalized)) if normalized else None
    if not lead:
        return {"ok": True, "found": False}
    return {
        "ok": True,
        "found": True,
        "lead": {
            "name": lead.name,
            "city": lead.city or "",
            "city_id": lead.city_id,
            "neighborhood": lead.neighborhood or "",
            "pets": [{"name": pet.name, "species": pet.species or ""} for pet in lead.pets],
            "number_validated": lead.number_validated,
        },
    }


def _collection_form_context(request: Request, db: Session, *, device: Device | None, flow: EntryFlow, mode: str, form_action: str, test_scope: str = ""):
    user = current_user(request, db)
    cities = (
        _cities_for_user(db, user)
        if user and mode == "interviewer"
        else db.scalars(select(City).where(City.active.is_(True)).order_by(City.name)).all()
    )
    registration = flow.registration_questionnaire
    registration_version = latest_published_version(db, registration) if registration else None
    questions = list(registration_version.questions) if registration_version else []
    return ctx(
        request,
        db,
        device=device,
        flow=flow,
        mode=mode,
        form_action=form_action,
        service_options=service_options(flow),
        service_status_options=service_status_options(flow),
        cities=cities,
        registration=registration,
        registration_version=registration_version,
        registration_questions=questions,
        lead_questions=[question for question in questions if not (question.data_binding or "").startswith(("pet.", "visit."))],
        pet_questions=[question for question in questions if (question.data_binding or "").startswith(("pet.", "visit."))],
        question_options={question.id: options(question) for question in questions},
        test_scope=test_scope,
    )


@router.get("/coleta/{device_token}/fluxo/{flow_id}")
def public_flow_form(request: Request, device_token: str, flow_id: int, db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.token == device_token, Device.active.is_(True)))
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id, EntryFlow.status == "active"))
    if not device or not flow or "kiosk" not in profiles(flow) or not _flow_matches_device(flow, device):
        raise HTTPException(404)
    device.last_seen_at = utcnow()
    db.commit()
    return request.app.state.templates.TemplateResponse(
        request,
        "entry_collection.html",
        _collection_form_context(request, db, device=device, flow=flow, mode="kiosk", form_action=f"/coleta/{device.token}/fluxo/{flow.id}"),
    )


@router.get("/entrevistador/fluxo/{flow_id}")
def interviewer_flow_form(request: Request, flow_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator", "interviewer"})
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id, EntryFlow.status == "active"))
    if not flow or "interviewer" not in profiles(flow) or not _flow_matches_user(db, flow, user):
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse(
        request,
        "entry_collection.html",
        _collection_form_context(request, db, device=None, flow=flow, mode="interviewer", form_action=f"/entrevistador/fluxo/{flow.id}"),
    )


async def _submit_collection(request: Request, db: Session, *, flow: EntryFlow, device: Device | None, mode: str, user: User | None, is_test: bool = False):
    form = await request.form()
    registration = flow.registration_questionnaire
    registration_version = None
    requested_version_id = _int(form.get("registration_version_id"), 0)
    if registration and requested_version_id:
        candidate = db.get(QuestionnaireVersion, requested_version_id)
        if candidate and candidate.questionnaire_id == registration.id and candidate.status == "published":
            registration_version = candidate
    if registration and not registration_version:
        registration_version = latest_published_version(db, registration)
    if registration and not registration_version:
        flash(request, "O questionário de cadastro ainda não possui uma versão publicada.", "danger")
        return None
    questions = list(registration_version.questions) if registration_version else []
    by_binding = {question.data_binding: question for question in questions if question.data_binding}

    def single(binding: str, fallback: str = "") -> str:
        question = by_binding.get(binding)
        return str(
            form.get(f"registration_vq_{question.id}")
            or form.get(f"registration_q_{question.original_question_id}")
            or fallback
        ).strip() if question else str(fallback).strip()

    name = single("lead.name", form.get("name") or "")
    phone = single("lead.phone", form.get("phone") or "")
    research = _bool(form, "consent_research") if flow.consent_research_enabled else False
    marketing = _bool(form, "consent_marketing") if flow.consent_marketing_enabled else False
    if not name or not phone:
        flash(request, "Informe nome e WhatsApp.", "danger")
        return None
    if flow.consent_terms_enabled and str(form.get("consent_schema") or "") in {"3.2.2", "3.2.4", "3.2.5", "3.3.0", "3.3.1", "3.3.2", "3.3.3", "3.3.4", "3.4.0", "3.4.1", "3.5.0", "3.5.1", "3.5.2", "3.5.3", "3.5.4", "3.5.5", "3.5.6", "3.5.7", "3.6.0"} and not _bool(form, "consent_terms"):
        flash(request, "O aceite dos termos é obrigatório neste fluxo.", "danger")
        return None
    if flow.consent_research_enabled and not research:
        flash(request, "O aceite para pesquisas relacionadas ao atendimento é obrigatório neste fluxo.", "danger")
        return None
    setting = db.get(SystemSetting, 1)
    city_id = _int(single("lead.city", form.get("city_id") or ""), 0) or (device.city_id if device else None)
    if user:
        _require_city_access(user, city_id)
    city_record = db.get(City, city_id) if city_id else None
    lead, _created = find_or_create_lead(
        db,
        name=name,
        phone=phone,
        default_country_code=setting.default_country_code,
        source="laboratory" if is_test else mode,
        city=city_record.name if city_record else str(form.get("city") or "").strip() or None,
        city_id=city_id,
        neighborhood=single("lead.neighborhood", form.get("neighborhood") or "") or None,
        consent_research=research,
        consent_marketing=marketing,
    )
    def repeated(binding: str, legacy_name: str) -> list[str]:
        question = by_binding.get(binding)
        values = form.getlist(f"pet_vq_{question.id}") if question else []
        if question and not values:
            values = form.getlist(f"pet_q_{question.original_question_id}")
        return [str(value) for value in (values or form.getlist(legacy_name))]

    names = repeated("pet.name", "pet_name")
    species = repeated("pet.species", "pet_species")
    reasons = repeated("visit.reason", "pet_reason")
    services = repeated("visit.service_type", "pet_service_type")
    statuses = repeated("visit.service_status", "pet_service_status")
    descriptions = repeated("visit.description", "pet_description")
    pets_data = []
    for index, pet_name in enumerate(names):
        if not str(pet_name).strip():
            continue
        def item(values):
            return str(values[index]).strip() if index < len(values) else ""
        pets_data.append({
            "name": str(pet_name).strip(),
            "species": item(species),
            "reason": item(reasons),
            "service_type": item(services),
            "service_status": item(statuses),
            "description": item(descriptions),
        })
    if not pets_data and not flow.allow_no_pet:
        flash(request, "Adicione pelo menos um pet.", "danger")
        return None
    session = build_collection(
        db,
        flow=flow,
        lead=lead,
        device_id=device.id if device else None,
        operator_user_id=user.id if user else None,
        mode=mode,
        pets_data=pets_data,
        notes=str(form.get("operator_notes") or "").strip() or None,
        is_test=is_test,
    )
    if registration:
        execution = SurveyExecution(
            questionnaire_id=registration.id,
            questionnaire_version_id=registration_version.id,
            lead_id=lead.id,
            public_token=secrets.token_urlsafe(28),
            channel=mode,
            source="entry_registration",
            status="completed",
            scheduled_at=utcnow(),
            started_at=utcnow(),
            completed_at=utcnow(),
            current_position=len(questions),
            collection_session_id=session.id,
            last_interaction_at=utcnow(),
            is_test=is_test,
            test_label="Cadastro estruturado de teste" if is_test else None,
            context_json=json.dumps({"flow_id": flow.id, "structured_registration": True}, ensure_ascii=False),
        )
        db.add(execution)
        db.flush()
        for question in questions:
            binding = question.data_binding or ""
            if binding.startswith(("pet.", "visit.")):
                raw_values = [value.strip() for value in form.getlist(f"pet_vq_{question.id}") if str(value).strip()]
                if not raw_values:
                    raw_values = [value.strip() for value in form.getlist(f"pet_q_{question.original_question_id}") if str(value).strip()]
                answer_text = " | ".join(raw_values)
            elif binding == "lead.city" and city_record:
                answer_text = f"{city_record.name}/{city_record.state}"
            else:
                answer_text = str(form.get(f"registration_vq_{question.id}") or form.get(f"registration_q_{question.original_question_id}") or "").strip()
            if not answer_text:
                continue
            numeric = None
            if question.type in {"score", "stars"}:
                try:
                    numeric = float(answer_text.replace(",", "."))
                except ValueError:
                    numeric = None
            db.add(SurveyAnswer(
                execution_id=execution.id,
                question_id=question.original_question_id,
                version_question_id=question.id,
                answer_text=answer_text,
                answer_value=answer_text,
                numeric_value=numeric,
                content_type="text",
                source=mode,
            ))
    record_consents(db, flow=flow, session=session, lead=lead, research=research, marketing=marketing, source=mode)
    if is_test and str(form.get("test_scope") or "") == "registration":
        session.confirmation_status = "test_registration_only"
        session.current_stage = "completed"
        session.status = "completed"
        db.commit()
        flash(request, "Cadastro de laboratório concluído. Nenhuma ação ou mensagem foi disparada.")
        return redirect(f"/coleta/sessao/{session.public_token}")
    next_url = run_flow_actions(db, session, "before_confirmation") if flow.actions else None
    if next_url:
        session.confirmation_status = "awaiting_pre_confirmation"
        session.current_stage = "pre_confirmation_screen"
    else:
        next_url = advance_after_pre_confirmation(db, session)
    db.commit()
    finish_url = f"/coleta/sessao/{session.public_token}"
    if next_url:
        request.session[f"survey_return:{next_url.rsplit('/', 1)[-1]}"] = finish_url
        return redirect(next_url)
    return redirect(finish_url)


@router.post("/coleta/{device_token}/fluxo/{flow_id}")
async def public_flow_submit(request: Request, device_token: str, flow_id: int, db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.token == device_token, Device.active.is_(True)))
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id, EntryFlow.status == "active"))
    if not device or not flow or not _flow_matches_device(flow, device):
        raise HTTPException(404)
    result = await _submit_collection(request, db, flow=flow, device=device, mode="kiosk", user=None)
    return result or redirect(f"/coleta/{device_token}/fluxo/{flow_id}")


@router.post("/entrevistador/fluxo/{flow_id}")
async def interviewer_flow_submit(request: Request, flow_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator", "interviewer"})
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id, EntryFlow.status == "active"))
    if not flow or not _flow_matches_user(db, flow, user):
        raise HTTPException(404)
    result = await _submit_collection(request, db, flow=flow, device=None, mode="interviewer", user=user)
    return result or redirect(f"/entrevistador/fluxo/{flow_id}")


@router.get("/fluxos/{flow_id}/testar")
def flow_test_form(request: Request, flow_id: int, db: Session = Depends(get_db)):
    require_user(request, db, {"admin", "operator", "interviewer"})
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id))
    if not flow or flow.status == "archived":
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse(
        request,
        "entry_collection.html",
        _collection_form_context(request, db, device=None, flow=flow, mode="interviewer", form_action=f"/fluxos/{flow.id}/testar", test_scope="registration" if request.query_params.get("scope") == "registration" else ""),
    )


@router.post("/fluxos/{flow_id}/testar")
async def flow_test_submit(request: Request, flow_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator", "interviewer"})
    flow = db.scalar(_flow_query().where(EntryFlow.id == flow_id))
    if not flow or flow.status == "archived":
        raise HTTPException(404)
    result = await _submit_collection(request, db, flow=flow, device=None, mode="interviewer", user=user, is_test=True)
    return result or redirect(f"/fluxos/{flow_id}/testar")


def _load_session(db: Session, token: str) -> CollectionSession | None:
    return db.scalar(
        select(CollectionSession)
        .options(
            selectinload(CollectionSession.flow).selectinload(EntryFlow.immediate_questionnaire),
            selectinload(CollectionSession.flow).selectinload(EntryFlow.confirmed_questionnaire),
            selectinload(CollectionSession.flow).selectinload(EntryFlow.followup_questionnaire),
            selectinload(CollectionSession.flow).selectinload(EntryFlow.actions).selectinload(EntryFlowAction.questionnaire),
            selectinload(CollectionSession.lead),
            selectinload(CollectionSession.verification).selectinload(PhoneVerification.message_queue),
            selectinload(CollectionSession.pets).selectinload(CollectionPet.pet),
        )
        .where(CollectionSession.public_token == token)
    )


@router.get("/coleta/sessao/{token}")
def collection_status_page(request: Request, token: str, db: Session = Depends(get_db)):
    session = _load_session(db, token)
    if not session:
        raise HTTPException(404)
    verification = session.verification
    return request.app.state.templates.TemplateResponse(
        request,
        "entry_status.html",
        ctx(request, db, collection=session, verification=verification, flow=session.flow),
    )


@router.get("/coleta/sessao/{token}/status")
def collection_status_api(request: Request, token: str, db: Session = Depends(get_db)):
    session = _load_session(db, token)
    if not session:
        raise HTTPException(404)
    verification = session.verification
    next_url = None
    if verification and verification.status not in {"confirmed", "failed", "expired"} and verification.expires_at and verification.expires_at < utcnow():
        verification.status = "expired"
        verification.failure_reason = "Tempo de confirmação expirado. Reenvie para gerar um novo botão."
        session.confirmation_status = "expired"
        db.commit()
    if session.confirmation_status.startswith("confirmed"):
        next_url = screen_action_after_confirmation(db, session)
        if next_url:
            request.session[f"survey_return:{next_url.rsplit('/', 1)[-1]}"] = f"/coleta/sessao/{session.public_token}"
            db.commit()
    queue_status = verification.message_queue.status if verification and verification.message_queue else None
    if verification and verification.status != "confirmed" and queue_status in {"sent", "simulated", "delivered", "read", "failed"}:
        verification.status = "sent" if queue_status == "simulated" else queue_status
        if queue_status == "failed":
            verification.failure_reason = verification.message_queue.error_message
        db.commit()
    return {
        "ok": True,
        "confirmation_status": session.confirmation_status,
        "verification_status": verification.status if verification else "not_requested",
        "queue_status": queue_status,
        "next_url": next_url,
        "lead_validated": bool(session.lead and session.lead.number_validated),
    }


@router.post("/coleta/sessao/{token}/reenviar")
async def collection_resend(request: Request, token: str, db: Session = Depends(get_db)):
    session = _load_session(db, token)
    if not session:
        raise HTTPException(404)
    form = await request.form()
    setting = db.get(SystemSetting, 1)
    new_phone = str(form.get("phone") or session.lead.phone or "").strip()
    normalized = normalize_phone(new_phone, setting.default_country_code)
    if not normalized:
        flash(request, "Informe um WhatsApp válido.", "danger")
        return redirect(f"/coleta/sessao/{token}")
    duplicate = db.scalar(select(Lead).where(Lead.phone_normalized == normalized, Lead.id != session.lead_id))
    if duplicate:
        flash(request, "Este WhatsApp já está vinculado a outro cadastro.", "danger")
        return redirect(f"/coleta/sessao/{token}")
    session.lead.phone = new_phone
    session.lead.phone_normalized = normalized
    session.lead.number_validated = False
    request_phone_verification(db, flow=session.flow, session=session, phone=normalized)
    db.commit()
    flash(request, "Confirmação reenviada.")
    return redirect(f"/coleta/sessao/{token}")


@router.post("/coleta/sessao/{token}/confirmar-manualmente")
def collection_manual_confirm(request: Request, token: str, db: Session = Depends(get_db)):
    user = require_user(request, db, {"admin", "operator", "interviewer"})
    session = _load_session(db, token)
    if not session or not session.verification or not session.flow.allow_manual_confirmation:
        raise HTTPException(404)
    complete_phone_verification(db, session.verification, manual=True)
    db.commit()
    flash(request, "WhatsApp confirmado manualmente e ações posteriores liberadas.")
    return redirect(f"/coleta/sessao/{token}")
