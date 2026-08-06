from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
handle, database_path = tempfile.mkstemp(prefix="escutapet_confirmation_resume_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["REDIS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import (
    CollectionSession,
    EntryFlow,
    EntryFlowAction,
    Lead,
    MessageQueue,
    PhoneVerification,
    Question,
    Questionnaire,
    SurveyExecution,
    User,
    utcnow,
)
from app.services.collection import complete_phone_verification, screen_action_after_confirmation
from app.services.versioning import publish_questionnaire_version


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    check(
        client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False).status_code == 303,
        "login falhou",
    )
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        registration = db.scalar(select(Questionnaire).where(Questionnaire.seed_key == "structured-registration-v1"))
        informative = Questionnaire(
            name="Informativo após confirmação", objective="profile", status="active",
            channels_json='["kiosk","interviewer"]', response_mode="identified",
            opening_message="Leia o informativo.", closing_message="Resposta registrada.", created_by_id=admin.id,
        )
        informative.questions = [
            Question(position=1, text="Aceita responder a pesquisa anônima?", type="yes_no", required=True,
                     options_json='[{"label":"Sim","value":"sim"},{"label":"Não","value":"nao"}]')
        ]
        anonymous = Questionnaire(
            name="Satisfação anônima após aceite", objective="satisfaction", status="active",
            channels_json='["kiosk","interviewer"]', response_mode="anonymous",
            opening_message="Avaliação anônima.", closing_message="Obrigado!", created_by_id=admin.id,
        )
        anonymous.questions = [Question(position=1, text="Qual sua satisfação?", type="score", required=True, min_score=0, max_score=10)]
        db.add_all([informative, anonymous])
        db.flush()
        publish_questionnaire_version(db, informative, user_id=admin.id)
        publish_questionnaire_version(db, anonymous, user_id=admin.id)

        flow = EntryFlow(
            name="Confirmação antes do tablet", status="active", registration_questionnaire_id=registration.id,
            phone_verification_mode="required",
        )
        db.add(flow)
        db.flush()
        first = EntryFlowAction(
            flow_id=flow.id, position=1, name="Informativo", trigger="after_confirmation",
            questionnaire_id=informative.id, channel="screen_identified", delay_value=0, delay_unit="minutes",
            schedule_mode="exact_interval", active=True,
        )
        db.add(first)
        db.flush()
        second = EntryFlowAction(
            flow_id=flow.id, position=2, name="Satisfação anônima", trigger="after_action",
            questionnaire_id=anonymous.id, channel="screen_anonymous", delay_value=0, delay_unit="minutes",
            schedule_mode="exact_interval", active=True, depends_on_action_id=first.id,
            condition_question_id=informative.questions[0].id, condition_operator="equals", condition_value="sim",
        )
        db.add(second)
        lead = Lead(name="Pessoa confirmada", phone="5562999999999", phone_normalized="5562999999999", source="interviewer", consent_research=True)
        db.add(lead)
        db.flush()
        session = CollectionSession(
            public_token="confirmation-resume-session", flow_id=flow.id, lead_id=lead.id,
            mode="interviewer", status="started", confirmation_status="pending",
        )
        db.add(session)
        db.flush()
        verification = PhoneVerification(
            lead_id=lead.id, collection_session_id=session.id, phone=lead.phone_normalized,
            token="confirmation-resume-token", status="read", expires_at=utcnow(), attempts=1,
        )
        db.add(verification)
        db.flush()

        complete_phone_verification(db, verification)
        db.flush()
        first_execution = db.scalar(
            select(SurveyExecution).where(SurveyExecution.collection_session_id == session.id, SurveyExecution.flow_action_id == first.id)
        )
        thanks = db.scalar(
            select(MessageQueue).where(MessageQueue.lead_id == lead.id, MessageQueue.kind == "phone_verification_thanks")
        )
        check(first_execution is not None and first_execution.status == "active", "confirmação não criou a primeira etapa de tela")
        check(session.status == "started" and session.completed_at is None, "sessão foi encerrada antes da etapa de tela")
        check(thanks is not None and thanks.status == "pending" and "Obrigado por confirmar" in thanks.payload_text, "agradecimento não foi colocado na fila")
        first_url = screen_action_after_confirmation(db, session)
        check(first_url == f"/aplicar/{first_execution.public_token}", "polling não recuperou a etapa após confirmação")
        check(screen_action_after_confirmation(db, session) == first_url, "polling criou ou abriu uma etapa diferente")
        complete_phone_verification(db, verification)
        check(
            len(db.scalars(select(MessageQueue).where(MessageQueue.lead_id == lead.id, MessageQueue.kind == "phone_verification_thanks")).all()) == 1,
            "reconfirmação criou agradecimento duplicado",
        )
        db.commit()
        first_token = first_execution.public_token

    answered = client.post(f"/aplicar/{first_token}", data={"answer": "sim"}, follow_redirects=False)
    check(answered.status_code == 303 and answered.headers["location"].startswith("/aplicar/"), "aceite não abriu a satisfação anônima")
    second_token = answered.headers["location"].rsplit("/", 1)[-1]
    with SessionLocal() as db:
        anonymous_execution = db.scalar(select(SurveyExecution).where(SurveyExecution.public_token == second_token))
        session = db.scalar(select(CollectionSession).where(CollectionSession.public_token == "confirmation-resume-session"))
        check(anonymous_execution is not None and anonymous_execution.questionnaire_id == anonymous.id, "pesquisa anônima não foi criada")
        check(anonymous_execution.lead_id is None and anonymous_execution.anonymous_token, "pesquisa anônima manteve vínculo com o lead")
        check(session.status == "started" and session.current_stage == "dependent_screen", "fluxo foi encerrado antes da pesquisa anônima")

print("OK - EscutaPet 3.3.4: confirmação retoma a jornada, agradece uma vez e preserva a pesquisa anônima condicional.")
