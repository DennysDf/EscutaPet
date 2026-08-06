from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v322_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["REDIS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal, engine
from app.main import app
from app.models import Device, EntryFlow, Questionnaire, SystemSetting
from app.services.versioning import latest_published_version, version_config


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    login = client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False)
    check(login.status_code == 303, "login falhou")

    inspector = inspect(engine)
    flow_columns = {item["name"] for item in inspector.get_columns("entry_flows")}
    action_columns = {item["name"] for item in inspector.get_columns("entry_flow_actions")}
    check({"consent_research_enabled", "consent_marketing_enabled", "consent_terms_enabled", "city_ids_json", "device_ids_json"}.issubset(flow_columns), "migração dos consentimentos/escopo ausente")
    check("fixed_scheduled_at" in action_columns, "migração da data fixa ausente")

    with SessionLocal() as db:
        registration = db.scalar(select(Questionnaire).where(Questionnaire.seed_key == "structured-registration-v1"))
        survey = next(
            item for item in db.scalars(select(Questionnaire).where(Questionnaire.status == "active").order_by(Questionnaire.id)).all()
            if item.id != registration.id and latest_published_version(db, item) and version_config(latest_published_version(db, item)).response_mode == "identified"
        )
        device = db.scalar(select(Device).order_by(Device.id))
        system = db.get(SystemSetting, 1)
        registration_id, survey_id, device_id, city_id = registration.id, survey.id, device.id, device.city_id
        timezone_name = system.timezone_name

    page = client.get("/fluxos/novo")
    check(page.status_code == 200, "editor visual não abriu")
    for text in ("Identificação", "Cadastro", "Consentimentos", "WhatsApp", "Jornada", "Revisão", "Jornada em linha do tempo", "Laboratório integrado"):
        check(text in page.text, f"etapa visual ausente: {text}")
    for marker in ("data-action-drawer", "data-action-drag-handle", "data-registration-summary", "data-run-simulation", "data-flow-tab=\"revisao\""):
        check(marker in page.text, f"marcador funcional ausente: {marker}")

    fixed_local = (datetime.now() + timedelta(days=2)).replace(hour=15, minute=30, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    key = f"action:new:{uuid.uuid4()}"
    data = {
        "name": "Jornada visual 3.2.2", "description": "Editor por etapas e linha do tempo", "status": "draft",
        "flow_schema": "3.2.2",
        "profile_kiosk": "on", "profile_interviewer": "on", "welcome_title": "Bem-vindo", "welcome_text": "Vamos começar.",
        "closing_title": "Obrigado!", "closing_text": "Jornada concluída.",
        "city_ids": str(city_id), "device_ids": str(device_id),
        "registration_questionnaire_id": str(registration_id), "allow_existing_lookup": "on", "allow_no_pet": "on", "max_pets": "10",
        "consent_research_enabled": "on", "consent_terms_enabled": "on", "consent_research_text": "Aceito participar das pesquisas.",
        "consent_marketing_text": "", "consent_terms_version": "2.0",
        "phone_verification_mode": "future_only", "phone_verification_timeout": "240", "allow_manual_confirmation": "on",
        "actions_count": "1", "action_0_id": "", "action_0_item_key": key, "action_0_name": "Retorno com data fixa",
        "action_0_questionnaire_id": str(survey_id), "action_0_version_mode": "latest_published", "action_0_fixed_version_id": "",
        "action_0_trigger": "after_registration", "action_0_depends_on_key": "", "action_0_delay_value": "0", "action_0_delay_unit": "minutes",
        "action_0_schedule_mode": "fixed_datetime", "action_0_fixed_scheduled_at": fixed_local, "action_0_send_hour": "15",
        "action_0_condition_question_id": "", "action_0_condition_operator": "", "action_0_condition_value": "",
        "action_0_channel": "whatsapp", "action_0_require_confirmation": "on", "action_0_active": "on",
    }
    response = client.post("/fluxos/novo", data=data, follow_redirects=False)
    excerpt = response.text[response.text.find("editor-error-summary"):response.text.find("editor-error-summary") + 1200]
    check(response.status_code == 303, f"jornada visual não foi salva: HTTP {response.status_code} {excerpt}")
    flow_id = int(response.headers["location"].split("/")[2])

    with SessionLocal() as db:
        flow = db.scalar(select(EntryFlow).options(selectinload(EntryFlow.actions)).where(EntryFlow.id == flow_id))
        check(flow.consent_research_enabled and flow.consent_terms_enabled and not flow.consent_marketing_enabled, "seletores de consentimento não foram persistidos")
        check(str(city_id) in flow.city_ids_json, "cidade da jornada não foi persistida")
        check(str(device_id) in flow.device_ids_json, "ponto da jornada não foi persistido")
        check(len(flow.actions) == 1 and flow.actions[0].schedule_mode == "fixed_datetime" and flow.actions[0].fixed_scheduled_at is not None, "agendamento fixo não foi persistido")
        check(db.get(Device, device_id).default_entry_flow_id == flow_id, "ponto não recebeu a jornada padrão")

    saved = client.get(f"/fluxos/{flow_id}/editar")
    check(saved.status_code == 200 and "Retorno com data fixa" in saved.text and fixed_local[:10] in saved.text, "reload perdeu a ação ou a data fixa")
    registration_lab = client.get(f"/fluxos/{flow_id}/testar?scope=registration")
    check(registration_lab.status_code == 200 and 'name="test_scope" value="registration"' in registration_lab.text, "laboratório somente cadastro não foi ativado")

    js = (PROJECT_DIR / "app/static/js/flow-actions.js").read_text(encoding="utf-8")
    for marker in ("depends_on_key", "formam um ciclo", "ArrowDown", "beforeunload", "runSimulation", "fixed_datetime"):
        check(marker in js, f"proteção do editor ausente: {marker}")
    check("depends_on_position" not in js, "editor voltou a depender de posição instável")

print(f"OK - EscutaPet 3.2.2 editor visual, escopo, consentimentos, data fixa e laboratório validados em {timezone_name}.")
