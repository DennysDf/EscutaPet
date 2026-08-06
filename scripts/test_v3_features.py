from __future__ import annotations

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v3_features_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import (
    EntryFlow,
    EntryFlowAction,
    Lead,
    MediaAsset,
    MessageQueue,
    Question,
    Questionnaire,
    SurveyAnswer,
    SurveyExecution,
    ZapiConfig,
    utcnow,
)
from app.services.collection import build_collection, run_flow_actions
from app.services.engine import create_execution, start_whatsapp_execution
from app.services.versioning import publish_questionnaire_version


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    login = client.post(
        "/login",
        data={"username": "admin", "password": "admin123", "next": "/"},
        follow_redirects=False,
    )
    check(login.status_code == 303, "login falhou")

    with SessionLocal() as db:
        secret = db.get(ZapiConfig, 1).webhook_secret

    # Identidade LID funciona mesmo quando a Z-API ainda não entrega um telefone.
    lid = "123456789012345@lid"
    first = client.post(
        f"/zapi/webhook/receber/{secret}",
        json={
            "senderLid": lid,
            "senderName": "Lia",
            "messageId": "lid-first",
            "text": {"message": "Olá"},
        },
    )
    check(first.json().get("action") == "consent_requested", "LID desconhecido não recebeu pedido de consentimento")
    accepted = client.post(
        f"/zapi/webhook/receber/{secret}",
        json={
            "senderLid": lid,
            "senderName": "Lia",
            "messageId": "lid-consent",
            "text": {"message": "Aceito participar"},
        },
    )
    check(accepted.json().get("action") == "consent_accepted", "aceite por texto e LID não foi processado")
    with SessionLocal() as db:
        lead_lid = db.scalar(select(Lead).where(Lead.whatsapp_lid == lid))
        check(lead_lid and lead_lid.consent_research and lead_lid.status == "active", "identidade LID não ficou ativa")
        check(db.scalar(select(MessageQueue).where(MessageQueue.lead_id == lead_lid.id, MessageQueue.phone == lid)) is not None, "fila não preservou o LID")

    # referenceMessageId escolhe a execução correta mesmo com outra pesquisa ativa.
    with SessionLocal() as db:
        lead = Lead(
            name="Referência Segura",
            phone="5562999001122",
            phone_normalized="5562999001122",
            source="test",
            status="active",
            consent_research=True,
        )
        photo = Questionnaire(
            name="Foto segura",
            status="active",
            objective="followup",
            channels_json='["whatsapp"]',
            response_mode="identified",
            opening_message="",
            closing_message="Obrigado",
        )
        photo.questions = [Question(position=1, text="Envie uma foto", type="photo")]
        other = Questionnaire(
            name="Outra pesquisa",
            status="active",
            objective="followup",
            channels_json='["whatsapp"]',
            response_mode="identified",
            opening_message="",
        )
        other.questions = [Question(position=1, text="Diga algo", type="text")]
        db.add_all([lead, photo, other])
        db.flush()
        publish_questionnaire_version(db, photo, user_id=1)
        publish_questionnaire_version(db, other, user_id=1)
        photo_execution = create_execution(db, photo, lead=lead, channel="whatsapp", source="reference_test")
        start_whatsapp_execution(db, photo_execution)
        photo_queue = db.scalar(select(MessageQueue).where(MessageQueue.execution_id == photo_execution.id))
        photo_queue.external_id = "question-photo-reference"
        other_execution = create_execution(db, other, lead=lead, channel="whatsapp", source="reference_test")
        start_whatsapp_execution(db, other_execution)
        db.commit()
        photo_execution_id = photo_execution.id
        other_execution_id = other_execution.id

    media_response = client.post(
        f"/zapi/webhook/receber/{secret}",
        json={
            "phone": "5562999001122",
            "messageId": "photo-answer-1",
            "referenceMessageId": "question-photo-reference",
            "image": {
                "imageUrl": "https://files.example.com/pet.jpg",
                "mimeType": "image/jpeg",
                "caption": "Ferida na pata",
            },
        },
    )
    check(media_response.json().get("action") == "answer_recorded", "foto referenciada não foi registrada")
    with SessionLocal() as db:
        answer = db.scalar(select(SurveyAnswer).where(SurveyAnswer.execution_id == photo_execution_id))
        check(answer and answer.content_type == "image", "tipo da resposta de mídia não foi preservado")
        check(db.scalar(select(SurveyAnswer).where(SurveyAnswer.execution_id == other_execution_id)) is None, "mídia caiu na execução ativa errada")
        asset = db.scalar(select(MediaAsset).where(MediaAsset.survey_answer_id == answer.id))
        check(asset and asset.download_status == "pending" and asset.expires_at, "mídia não foi registrada para download antes da expiração")

    # Duas ações podem usar o mesmo questionário, e uma delas pode gerar uma execução por pet.
    with SessionLocal() as db:
        questionnaire = db.scalar(select(Questionnaire).where(Questionnaire.name == "Perfil e interesses"))
        lead = Lead(
            name="Família Multipet",
            phone="5562999332211",
            phone_normalized="5562999332211",
            source="test",
            status="active",
            consent_research=True,
            number_validated=True,
        )
        flow = EntryFlow(name="Fluxo múltiplo V3", status="active")
        flow.actions = [
            EntryFlowAction(
                position=1,
                name="Satisfação em 2 horas",
                trigger="after_registration",
                questionnaire_id=questionnaire.id,
                channel="whatsapp",
                delay_value=2,
                delay_unit="hours",
            ),
            EntryFlowAction(
                position=2,
                name="Evolução em 10 dias por pet",
                trigger="after_registration",
                questionnaire_id=questionnaire.id,
                channel="whatsapp",
                delay_value=10,
                delay_unit="days",
                per_pet=True,
            ),
        ]
        db.add_all([lead, flow])
        db.flush()
        session = build_collection(
            db,
            flow=flow,
            lead=lead,
            device_id=None,
            operator_user_id=None,
            mode="interviewer",
            pets_data=[
                {"name": "Sol", "species": "Cachorro", "service_type": "Consulta"},
                {"name": "Lua", "species": "Gato", "service_type": "Vacinação"},
            ],
        )
        run_flow_actions(db, session, "after_registration")
        db.commit()
        executions = db.scalars(
            select(SurveyExecution)
            .where(SurveyExecution.collection_session_id == session.id)
            .order_by(SurveyExecution.scheduled_at)
        ).all()
        check(len(executions) == 3, "ações múltiplas/per-pet não geraram três execuções")
        check(len({item.idempotency_key for item in executions}) == 3, "chaves por ação/pet não são únicas")
        check(sum(item.pet_id is not None for item in executions) == 2, "ação por pet não preservou os dois pets")
        check(executions[0].scheduled_at <= utcnow() + timedelta(hours=3), "ação de duas horas foi agendada incorretamente")
        check(executions[-1].scheduled_at >= utcnow() + timedelta(days=9), "ação de dez dias foi agendada incorretamente")

Path(database_path).unlink(missing_ok=True)
print("OK - recursos centrais da versão 3.1.2 validados.")
