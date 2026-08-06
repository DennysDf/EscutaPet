from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
handle, database_path = tempfile.mkstemp(prefix="escutapet_conditional_screen_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["REDIS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.main import app
from app.models import CollectionSession, EntryFlow, EntryFlowAction, Lead, Question, Questionnaire, SurveyExecution, User
from app.routers.entry import _actions_from_flow, _flow_state, _validate_flow_submission
from app.services.collection import run_flow_actions
from app.services.versioning import publish_questionnaire_version


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False).status_code == 303, "login falhou")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        registration = db.scalar(select(Questionnaire).where(Questionnaire.seed_key == "structured-registration-v1"))
        informative = Questionnaire(
            name="Informativo de aceite", objective="profile", status="active",
            channels_json='["kiosk","interviewer"]', response_mode="identified",
            opening_message="Leia o informativo.", closing_message="Resposta registrada.", created_by_id=admin.id,
        )
        informative.questions = [Question(position=1, text="Aceita responder a pesquisa anônima?", type="yes_no", required=True, options_json='[{"label":"Sim","value":"sim"},{"label":"Não","value":"nao"}]')]
        anonymous = Questionnaire(
            name="Satisfação anônima", objective="satisfaction", status="active",
            channels_json='["kiosk","interviewer"]', response_mode="anonymous",
            opening_message="Avaliação anônima.", closing_message="Obrigado!", created_by_id=admin.id,
        )
        anonymous.questions = [Question(position=1, text="Qual sua satisfação?", type="score", required=True, min_score=0, max_score=10)]
        db.add_all([informative, anonymous]); db.flush()
        publish_questionnaire_version(db, informative, user_id=admin.id)
        publish_questionnaire_version(db, anonymous, user_id=admin.id)
        flow = EntryFlow(name="Aceite seguido de satisfação anônima", status="active", registration_questionnaire_id=registration.id, phone_verification_mode="send_continue")
        db.add(flow); db.flush()
        first = EntryFlowAction(flow_id=flow.id, position=1, name="Informativo", trigger="after_registration", questionnaire_id=informative.id, channel="screen_identified", delay_value=0, delay_unit="minutes", schedule_mode="exact_interval", active=True)
        db.add(first); db.flush()
        second = EntryFlowAction(flow_id=flow.id, position=2, name="Satisfação anônima", trigger="after_action", questionnaire_id=anonymous.id, channel="screen_anonymous", delay_value=0, delay_unit="minutes", schedule_mode="exact_interval", active=True, depends_on_action_id=first.id, condition_question_id=informative.questions[0].id, condition_operator="equals", condition_value="sim")
        db.add(second); db.commit()

        flow = db.scalar(select(EntryFlow).options(selectinload(EntryFlow.actions).selectinload(EntryFlowAction.questionnaire)).where(EntryFlow.id == flow.id))
        errors = _validate_flow_submission(db, _flow_state(flow), _actions_from_flow(flow), flow)
        check(not [item for item in errors if item["field"] == "channel"], f"validação ainda bloqueia tela condicional: {errors}")

        lead = Lead(name="Pessoa teste", phone="5562999999999", phone_normalized="5562999999999", source="interviewer", consent_research=True)
        db.add(lead); db.flush()
        session = CollectionSession(public_token="conditional-screen-session", flow_id=flow.id, lead_id=lead.id, mode="interviewer", status="started", confirmation_status="not_required")
        db.add(session); db.flush()
        first_url = run_flow_actions(db, session, "after_registration")
        db.commit()
        first_token = first_url.rsplit("/", 1)[-1]

    first_answer = client.post(f"/aplicar/{first_token}", data={"answer": "sim"}, follow_redirects=False)
    check(first_answer.status_code == 303 and first_answer.headers["location"].startswith("/aplicar/"), "aceite não abriu automaticamente a pesquisa seguinte")
    second_token = first_answer.headers["location"].rsplit("/", 1)[-1]
    check(second_token != first_token, "jornada permaneceu no questionário informativo")
    with SessionLocal() as db:
        child = db.scalar(select(SurveyExecution).where(SurveyExecution.public_token == second_token))
        session = db.scalar(select(CollectionSession).where(CollectionSession.public_token == "conditional-screen-session"))
        check(child is not None and child.questionnaire_id == anonymous.id and child.anonymous_token, "pesquisa seguinte não foi criada como anônima")
        check(child.lead_id is None, "pesquisa anônima foi vinculada ao lead")
        check(session.status == "started" and session.current_stage == "dependent_screen", "sessão foi encerrada antes da pesquisa anônima")

        lead_no = Lead(name="Pessoa sem aceite", phone="5562888888888", phone_normalized="5562888888888", source="interviewer", consent_research=True)
        db.add(lead_no); db.flush()
        session_no = CollectionSession(public_token="conditional-screen-session-no", flow_id=flow.id, lead_id=lead_no.id, mode="interviewer", status="started", confirmation_status="not_required")
        db.add(session_no); db.flush()
        first_no_url = run_flow_actions(db, session_no, "after_registration")
        db.commit()
        first_no_token = first_no_url.rsplit("/", 1)[-1]

    no_answer = client.post(f"/aplicar/{first_no_token}", data={"answer": "nao"}, follow_redirects=False)
    check(no_answer.status_code == 303 and no_answer.headers["location"] == f"/aplicar/{first_no_token}", "resposta 'não' abriu indevidamente a pesquisa condicionada")
    with SessionLocal() as db:
        anonymous_children = db.scalars(select(SurveyExecution).where(SurveyExecution.questionnaire_id == anonymous.id)).all()
        check(len(anonymous_children) == 1, "resposta 'não' criou uma execução anônima indevida")

print("OK - 'sim' abre a pesquisa anônima sem vínculo com o lead e 'não' não dispara a ação.")
