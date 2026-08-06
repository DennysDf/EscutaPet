from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v310_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.main import app
from app.models import (
    CollectionSession,
    EntryFlow,
    EntryFlowAction,
    Lead,
    Question,
    Questionnaire,
    SurveyAnswer,
    SurveyExecution,
)
from app.services.collection import build_collection, run_flow_actions
from app.services.engine import record_answer
from app.services.versioning import publish_questionnaire_version


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    login = client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False)
    check(login.status_code == 303, "login falhou")

    with SessionLocal() as db:
        registration = db.scalar(
            select(Questionnaire)
            .options(selectinload(Questionnaire.questions))
            .where(Questionnaire.seed_key == "structured-registration-v1")
        )
        check(registration is not None, "cadastro estruturado padrão não foi criado")
        bindings = {question.data_binding: question for question in registration.questions if question.active}
        check({"lead.name", "lead.phone", "pet.name"}.issubset(bindings), "vínculos mínimos não foram criados")
        registration.questions.append(Question(position=20, text="Como conheceu o serviço?", type="text", required=False))
        db.flush()
        publish_questionnaire_version(db, registration, user_id=1)
        flow = db.scalar(select(EntryFlow).where(EntryFlow.registration_questionnaire_id == registration.id).limit(1))
        db.commit()
        flow_id = flow.id
        name_id = bindings["lead.name"].id
        phone_id = bindings["lead.phone"].id
        city_id = bindings["lead.city"].id
        pet_name_id = bindings["pet.name"].id
        species_id = bindings["pet.species"].id
        reason_id = bindings["visit.reason"].id
        service_id = bindings["visit.service_type"].id
        custom_id = registration.questions[-1].id

    page = client.get(f"/fluxos/{flow_id}/testar")
    check(page.status_code == 200 and "Cadastro essencial de responsável e pet" in page.text, "laboratório do fluxo não abriu")
    response = client.post(
        f"/fluxos/{flow_id}/testar",
        data={
            f"registration_q_{name_id}": "Cadastro Teste 3.1",
            f"registration_q_{phone_id}": "(62) 99888-7766",
            f"registration_q_{city_id}": "",
            f"registration_q_{custom_id}": "Indicação",
            f"pet_q_{pet_name_id}": "Nina",
            f"pet_q_{species_id}": "Gato",
            f"pet_q_{reason_id}": "Vacina",
            f"pet_q_{service_id}": "Vacinação",
            "consent_research": "on",
        },
        follow_redirects=False,
    )
    check(response.status_code == 303, "cadastro estruturado de teste não foi salvo")

    with SessionLocal() as db:
        lead = db.scalar(select(Lead).where(Lead.phone_normalized == "5562998887766"))
        check(lead and lead.name == "Cadastro Teste 3.1" and lead.pets[0].name == "Nina", "vínculos do cadastro não alimentaram lead/pet")
        session = db.scalar(select(CollectionSession).where(CollectionSession.lead_id == lead.id))
        check(session and session.is_test, "sessão do laboratório não foi isolada")
        registration_execution = db.scalar(
            select(SurveyExecution).where(
                SurveyExecution.collection_session_id == session.id,
                SurveyExecution.source == "entry_registration",
            )
        )
        answer = db.scalar(
            select(SurveyAnswer).where(
                SurveyAnswer.execution_id == registration_execution.id,
                SurveyAnswer.question_id == custom_id,
            )
        )
        check(answer and answer.answer_text == "Indicação", "pesquisa complementar do cadastro não ficou no histórico")

        parent_q = Questionnaire(
            name="Condição principal",
            status="active",
            objective="followup",
            channels_json='["whatsapp"]',
            response_mode="identified",
            opening_message="",
        )
        parent_q.questions = [Question(position=1, text="Melhorou?", type="yes_no")]
        child_q = Questionnaire(
            name="Condição liberada",
            status="active",
            objective="followup",
            channels_json='["whatsapp"]',
            response_mode="identified",
            opening_message="",
        )
        child_q.questions = [Question(position=1, text="Conte mais", type="text")]
        conditional_flow = EntryFlow(
            name="Fluxo condicional",
            status="active",
            registration_questionnaire_id=registration.id,
        )
        db.add_all([parent_q, child_q, conditional_flow])
        db.flush()
        publish_questionnaire_version(db, parent_q, user_id=1)
        publish_questionnaire_version(db, child_q, user_id=1)
        parent_action = EntryFlowAction(
            flow_id=conditional_flow.id,
            position=1,
            name="Pergunta principal",
            trigger="after_registration",
            questionnaire_id=parent_q.id,
            channel="whatsapp",
        )
        db.add(parent_action)
        db.flush()
        child_action = EntryFlowAction(
            flow_id=conditional_flow.id,
            position=2,
            name="Aprofundamento",
            trigger="after_action",
            questionnaire_id=child_q.id,
            channel="whatsapp",
            depends_on_action_id=parent_action.id,
            condition_question_id=parent_q.questions[0].id,
            condition_operator="equals",
            condition_value="sim",
        )
        db.add(child_action)
        db.flush()
        real_lead = Lead(
            name="Condição",
            phone="5562997776655",
            phone_normalized="5562997776655",
            source="test",
            status="active",
            consent_research=True,
            number_validated=True,
        )
        db.add(real_lead)
        db.flush()
        conditional_session = build_collection(
            db,
            flow=conditional_flow,
            lead=real_lead,
            device_id=None,
            operator_user_id=None,
            mode="interviewer",
            pets_data=[],
        )
        run_flow_actions(db, conditional_session, "after_registration")
        db.flush()
        parent_execution = db.scalar(
            select(SurveyExecution).where(
                SurveyExecution.collection_session_id == conditional_session.id,
                SurveyExecution.flow_action_id == parent_action.id,
            )
        )
        parent_execution.status = "active"
        record_answer(db, parent_execution, raw_text="sim", source="whatsapp")
        db.commit()
        child_execution = db.scalar(
            select(SurveyExecution).where(
                SurveyExecution.collection_session_id == conditional_session.id,
                SurveyExecution.flow_action_id == child_action.id,
            )
        )
        check(child_execution is not None, "condição verdadeira não liberou a próxima ação")
        parent_q_id = parent_q.id
        conditional_flow_id = conditional_flow.id
        archive_q = Questionnaire(
            name="Questionário arquivável",
            status="paused",
            objective="followup",
            channels_json='["kiosk"]',
            response_mode="identified",
        )
        archive_q.questions = [Question(position=1, text="Pergunta preservada", type="text")]
        db.add(archive_q)
        db.commit()
        archive_q_id = archive_q.id

    detail = client.get(f"/leads/{lead.id}")
    check(detail.status_code == 200 and "Como conheceu o serviço?" not in detail.text, "execução de teste vazou para o histórico real")
    list_page = client.get("/questionarios")
    check(list_page.status_code == 200 and "Testar fluxo" in list_page.text and "Testar WhatsApp" in list_page.text, "ações de laboratório não aparecem")
    whatsapp_test = client.post(
        f"/questionarios/{parent_q_id}/testar-whatsapp",
        data={"phone": "(62) 99666-5544"},
        follow_redirects=False,
    )
    check(whatsapp_test.status_code == 303 and whatsapp_test.headers["location"].startswith("/questionarios/testes/"), "laboratório do WhatsApp não iniciou")
    progress = client.get(whatsapp_test.headers["location"])
    check(progress.status_code == 200 and "EXECUÇÃO DE TESTE" in progress.text and "Aguardando resposta" in progress.text, "andamento do teste WhatsApp não abriu")
    check(client.post(f"/fluxos/{conditional_flow_id}/status", data={"status": "archived"}, follow_redirects=False).status_code == 303, "fluxo não foi arquivado")
    check(client.post(f"/questionarios/{archive_q_id}/status", data={"status": "archived"}, follow_redirects=False).status_code == 303, "questionário não foi arquivado")
    archived = client.get("/questionarios?arquivados=1")
    check(archived.status_code == 200 and "Fluxo condicional" in archived.text and "Questionário arquivável" in archived.text, "área de arquivados não preservou os itens")

Path(database_path).unlink(missing_ok=True)
print("OK - EscutaPet 3.1.2 cadastro estruturado, condições, isolamento e laboratórios validados.")
