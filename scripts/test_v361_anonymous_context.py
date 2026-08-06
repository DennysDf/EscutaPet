from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, path = tempfile.mkstemp(prefix="escutapet_v361_anonymous_", suffix=".sqlite3")
os.close(handle); os.unlink(path)
os.environ.update(DATABASE_URL=f"sqlite:///{path}", AUTO_SEED_DEMO="1", REDIS_ENABLED="0", SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import City, CollectionSession, Device, EntryFlow, EntryFlowAction, Lead, Question, Questionnaire, SurveyAnswer, SurveyExecution, User
from app.services.collection import build_collection, launch_immediate_action, run_flow_actions, screen_action_after_confirmation
from app.services.engine import anonymous_aggregate
from app.services.versioning import publish_questionnaire_version


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False).status_code == 303, "login falhou")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        registration = db.scalar(select(Questionnaire).where(Questionnaire.seed_key == "structured-registration-v1"))

        anon_q = Questionnaire(
            name="Estrutura anônima", objective="satisfaction", status="active",
            channels_json='["kiosk","interviewer"]', response_mode="anonymous",
            opening_message="Avaliação anônima.", closing_message="Obrigado!", created_by_id=admin.id,
        )
        anon_q.questions = [Question(position=1, text="Como está a limpeza?", type="score", required=True, min_score=0, max_score=10)]
        db.add(anon_q); db.flush()
        publish_questionnaire_version(db, anon_q, user_id=admin.id)

        city = City(name="Canil Centro", state="GO", active=True)
        db.add(city); db.flush()
        device = Device(city_id=city.id, name="Totem 1", token="totem-token-v361", mode="kiosk", allow_anonymous=True)
        db.add(device); db.flush()

        # --- Caminho 1: run_flow_actions (fluxo com ações). ---
        flow_actions = EntryFlow(name="Fluxo com ações anônimas", status="active", registration_questionnaire_id=registration.id, phone_verification_mode="none")
        db.add(flow_actions); db.flush()
        action = EntryFlowAction(flow_id=flow_actions.id, position=1, name="Estrutura", trigger="after_registration", questionnaire_id=anon_q.id, channel="screen_anonymous", delay_value=0, delay_unit="minutes", schedule_mode="exact_interval", active=True)
        db.add(action); db.commit()

        lead1 = Lead(name="Tutor 1", phone="5562990000001", phone_normalized="5562990000001", source="kiosk", city_id=city.id, consent_research=True)
        db.add(lead1); db.flush()
        session1 = build_collection(db, flow=flow_actions, lead=lead1, device_id=device.id, operator_user_id=None, mode="kiosk", pets_data=[{"name": "Rex"}])
        db.commit()
        url1 = run_flow_actions(db, session1, "after_registration")
        db.commit()
        check(url1 is not None, "caminho 1 (run_flow_actions) não abriu a etapa anônima")
        execution1 = db.scalar(select(SurveyExecution).where(SurveyExecution.public_token == url1.rsplit("/", 1)[-1]))

        # --- Caminho 2: launch_immediate_action (fluxo legado sem ações). ---
        flow_immediate = EntryFlow(name="Fluxo imediato anônimo", status="active", registration_questionnaire_id=registration.id, phone_verification_mode="none", immediate_questionnaire_id=anon_q.id, immediate_channel="screen_anonymous")
        db.add(flow_immediate); db.commit()
        lead2 = Lead(name="Tutor 2", phone="5562990000002", phone_normalized="5562990000002", source="kiosk", city_id=city.id, consent_research=True)
        db.add(lead2); db.flush()
        session2 = build_collection(db, flow=flow_immediate, lead=lead2, device_id=device.id, operator_user_id=None, mode="kiosk", pets_data=[{"name": "Mel"}])
        db.commit()
        url2 = launch_immediate_action(db, session2)
        db.commit()
        check(url2 is not None, "caminho 2 (launch_immediate_action) não abriu a etapa anônima")
        execution2 = db.scalar(select(SurveyExecution).where(SurveyExecution.public_token == url2.rsplit("/", 1)[-1]))

        # --- Caminho 3: screen_action_after_confirmation (fluxo legado, etapa liberada após confirmação). ---
        flow_confirmed = EntryFlow(name="Fluxo confirmado anônimo", status="active", registration_questionnaire_id=registration.id, phone_verification_mode="none", confirmed_questionnaire_id=anon_q.id, confirmed_channel="screen_anonymous")
        db.add(flow_confirmed); db.commit()
        lead3 = Lead(name="Tutor 3", phone="5562990000003", phone_normalized="5562990000003", source="kiosk", city_id=city.id, consent_research=True)
        db.add(lead3); db.flush()
        session3 = build_collection(db, flow=flow_confirmed, lead=lead3, device_id=device.id, operator_user_id=None, mode="kiosk", pets_data=[{"name": "Thor"}])
        session3.current_stage = "confirmed_screen_available"
        db.commit()
        url3 = screen_action_after_confirmation(db, session3)
        db.commit()
        check(url3 is not None, "caminho 3 (screen_action_after_confirmation) não abriu a etapa anônima")
        execution3 = db.scalar(select(SurveyExecution).where(SurveyExecution.public_token == url3.rsplit("/", 1)[-1]))

        for label, execution, session in (("1", execution1, session1), ("2", execution2, session2), ("3", execution3, session3)):
            check(execution is not None, f"caminho {label} não criou execução anônima")
            check(execution.lead_id is None, f"caminho {label}: lead_id vazou na execução anônima (viola I1)")
            check(execution.collection_session_id is None, f"caminho {label}: collection_session_id vazou na execução anônima (viola I1)")
            check(execution.flow_action_id is None, f"caminho {label}: flow_action_id vazou na execução anônima (viola I1)")
            check(execution.pet_id is None, f"caminho {label}: pet_id vazou na execução anônima (viola I1)")
            check(execution.city_id == session.city_id, f"caminho {label}: city_id não foi propagado")
            check(execution.device_id == session.device_id, f"caminho {label}: device_id não foi propagado")
            context = json.loads(execution.context_json or "{}")
            anonymous_context = context.get("anonymous_context")
            check(isinstance(anonymous_context, dict), f"caminho {label}: anonymous_context ausente")
            check(anonymous_context.get("mode") == session.mode, f"caminho {label}: modo não gravado no contexto")
            check(anonymous_context.get("collected_date"), f"caminho {label}: collected_date ausente")
            check(anonymous_context.get("shift") in {"manha", "tarde", "noite"}, f"caminho {label}: turno inválido")
            check("is_return" in anonymous_context, f"caminho {label}: is_return ausente")

        # --- I4: piso de anonimato aplicado por recorte (cidade/unidade), não só no alerta agregado. ---
        below_minimum = anonymous_aggregate(db, city_id=city.id, device_id=device.id)
        check(below_minimum is None, "recorte com poucas respostas deveria vir suprimido (I4)")

        for index in range(10):
            extra_execution = SurveyExecution(
                questionnaire_id=anon_q.id, questionnaire_version_id=execution1.questionnaire_version_id,
                public_token=f"extra-anon-{index}", channel="kiosk", source="test", status="completed",
                city_id=city.id, device_id=device.id, context_json="{}",
            )
            db.add(extra_execution); db.flush()
            db.add(SurveyAnswer(execution_id=extra_execution.id, question_id=anon_q.questions[0].id, answer_text=str(8), answer_value="8", numeric_value=8.0, source="kiosk"))
        db.commit()
        above_minimum = anonymous_aggregate(db, city_id=city.id, device_id=device.id)
        check(above_minimum is not None and above_minimum["count"] >= 7, "recorte com respostas suficientes deveria ficar visível (I4)")

        other_city = City(name="Canil Norte", state="GO", active=True)
        db.add(other_city); db.commit()
        different_city_result = anonymous_aggregate(db, city_id=other_city.id)
        check(different_city_result is None, "recorte de outra cidade sem respostas não deveria vazar dados de Canil Centro")

print("OK - EscutaPet 3.6.1 C2: contexto de unidade nos três caminhos anônimos, sem vazar identidade (I1), com piso de anonimato por recorte (I4).")
