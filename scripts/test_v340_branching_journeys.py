from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
handle, database_path = tempfile.mkstemp(prefix="escutapet_v340_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["REDIS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.database import SessionLocal, engine
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
    SurveyAnswer,
    SurveyExecution,
    User,
    utcnow,
)
from app.services.collection import complete_phone_verification, run_flow_actions
from app.services.engine import complete_execution
from app.services.versioning import publish_questionnaire_version
from app.routers.entry import _actions_from_flow, _flow_form_actions, _flow_state, _validate_flow_submission


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def questionnaire(db, admin, name: str, question_text: str, *, objective="profile", qtype="yes_no", options_json="[]"):
    item = Questionnaire(
        name=name, objective=objective, status="active", channels_json='["kiosk","interviewer"]',
        response_mode="identified", opening_message=name, closing_message="Concluído.", created_by_id=admin.id,
    )
    item.questions = [Question(position=1, text=question_text, type=qtype, required=True, options_json=options_json)]
    db.add(item)
    db.flush()
    publish_questionnaire_version(db, item, user_id=admin.id)
    return item


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False).status_code == 303, "login falhou")
    columns = {column["name"] for column in inspect(engine).get_columns("entry_flow_actions")}
    check({"conditions_json", "condition_logic", "random_group", "random_weight"}.issubset(columns), "migração das ações 3.4.1 ausente")
    session_columns = {column["name"] for column in inspect(engine).get_columns("collection_sessions")}
    check("decisions_json" in session_columns, "migração das decisões da sessão ausente")
    recovered = _flow_form_actions({
        "actions_count": "1",
        "action_0_item_key": "action:legacy-draft",
        "action_0_schedule_mode": "",
    })
    check(recovered[0]["schedule_mode"] == "exact_interval", "rascunho 3.4.0 com agendamento vazio não foi recuperado")

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        registration = Questionnaire(
            name="Cadastro com preferência", objective="registration", status="active",
            channels_json='["kiosk","interviewer"]', response_mode="identified",
            opening_message="Cadastro", closing_message="Cadastro salvo.", created_by_id=admin.id,
        )
        registration.questions = [
            Question(position=1, text="Nome completo", type="text", required=True, data_binding="lead.name"),
            Question(position=2, text="WhatsApp", type="text", required=True, data_binding="lead.phone"),
            Question(position=3, text="Qual animal prefere?", type="choice", required=True,
                     options_json='[{"label":"Cachorro","value":"cachorro"},{"label":"Gato","value":"gato"}]'),
        ]
        db.add(registration)
        db.flush()
        registration_version, _ = publish_questionnaire_version(db, registration, user_id=admin.id)
        pre = questionnaire(db, admin, "Aceite antes da confirmação", "Deseja participar da pesquisa?")
        pre_extra = questionnaire(db, admin, "Triagem antes da confirmação", "O atendimento já foi realizado?")
        path_a = questionnaire(db, admin, "Caminho sorteado A", "Avaliação A", objective="satisfaction", qtype="score")
        path_b = questionnaire(db, admin, "Caminho sorteado B", "Avaliação B", objective="satisfaction", qtype="score")

        flow = EntryFlow(
            name="Jornada ramificada 3.4", status="active", registration_questionnaire_id=registration.id,
            phone_verification_mode="required", consent_research_enabled=True,
        )
        db.add(flow)
        db.flush()
        pre_action = EntryFlowAction(
            flow_id=flow.id, position=1, name="Informativo inicial", trigger="before_confirmation",
            questionnaire_id=pre.id, channel="screen_identified", delay_value=0, delay_unit="minutes",
            schedule_mode="exact_interval", active=True,
        )
        db.add(pre_action)
        db.flush()
        pre_extra_action = EntryFlowAction(
            flow_id=flow.id, position=2, name="Triagem inicial", trigger="before_confirmation",
            questionnaire_id=pre_extra.id, channel="screen_identified", delay_value=0, delay_unit="minutes",
            schedule_mode="exact_interval", active=True,
        )
        db.add(pre_extra_action)
        db.flush()
        conditions = json.dumps([
            {"source_action_id": pre_action.id, "question_id": pre.questions[0].id, "operator": "equals", "value": "sim"},
            {"source_action_id": None, "question_id": registration.questions[2].id, "operator": "equals", "value": "cachorro"},
        ], ensure_ascii=False)
        for position, target in enumerate((path_a, path_b), start=3):
            db.add(EntryFlowAction(
                flow_id=flow.id, position=position, name=f"Opção aleatória {position - 1}", trigger="after_confirmation",
                questionnaire_id=target.id, channel="screen_identified", delay_value=0, delay_unit="minutes",
                schedule_mode="exact_interval", active=True, conditions_json=conditions, condition_logic="and",
                random_group="pesquisa-pos-aceite", random_weight=1,
            ))
        db.flush()
        validation_errors = _validate_flow_submission(db, _flow_state(flow), _actions_from_flow(flow), flow)
        check(not validation_errors, f"editor rejeitou a jornada ramificada válida: {validation_errors}")

        lead = Lead(name="Pessoa teste", phone="5562999999999", phone_normalized="5562999999999", source="interviewer", consent_research=True)
        db.add(lead)
        db.flush()
        collection = CollectionSession(
            public_token="v340-branch-session", flow_id=flow.id, lead_id=lead.id, mode="interviewer",
            status="started", confirmation_status="not_requested",
        )
        db.add(collection)
        db.flush()
        registration_execution = SurveyExecution(
            questionnaire_id=registration.id, questionnaire_version_id=registration_version.id, lead_id=lead.id,
            public_token=secrets.token_urlsafe(20), channel="interviewer", source="entry_registration", status="completed",
            scheduled_at=utcnow(), started_at=utcnow(), completed_at=utcnow(), collection_session_id=collection.id,
        )
        db.add(registration_execution)
        db.flush()
        db.add(SurveyAnswer(
            execution_id=registration_execution.id, question_id=registration.questions[2].id,
            answer_text="Cachorro", answer_value="cachorro", content_type="text", source="interviewer",
        ))
        db.flush()

        pre_url = run_flow_actions(db, collection, "before_confirmation")
        pre_execution = db.scalar(select(SurveyExecution).where(SurveyExecution.flow_action_id == pre_action.id, SurveyExecution.collection_session_id == collection.id))
        check(pre_url == f"/aplicar/{pre_execution.public_token}", "etapa inicial não abriu antes da confirmação")
        check(collection.verification is None, "confirmação foi enviada antes da etapa inicial")
        db.add(SurveyAnswer(
            execution_id=pre_execution.id, question_id=pre.questions[0].id,
            answer_text="Sim", answer_value="sim", content_type="text", source="interviewer",
        ))
        next_pre_url = complete_execution(db, pre_execution)
        db.flush()
        second_pre = db.scalar(select(SurveyExecution).where(SurveyExecution.flow_action_id == pre_extra_action.id, SurveyExecution.collection_session_id == collection.id))
        check(next_pre_url == f"/aplicar/{second_pre.public_token}", "a segunda etapa inicial não foi encadeada")
        check(db.scalar(select(PhoneVerification).where(PhoneVerification.collection_session_id == collection.id)) is None, "confirmação foi enviada antes de terminar todas as etapas iniciais")
        db.add(SurveyAnswer(
            execution_id=second_pre.id, question_id=pre_extra.questions[0].id,
            answer_text="Sim", answer_value="sim", content_type="text", source="interviewer",
        ))
        complete_execution(db, second_pre)
        db.flush()
        verification = db.scalar(select(PhoneVerification).where(PhoneVerification.collection_session_id == collection.id))
        check(verification is not None and collection.confirmation_status == "pending", "confirmação não foi solicitada ao terminar as etapas iniciais")
        check(db.scalar(select(func.count(MessageQueue.id)).where(MessageQueue.kind == "phone_verification")) == 1, "fila de confirmação incorreta")

        complete_phone_verification(db, verification)
        db.flush()
        selected = db.scalars(select(SurveyExecution).where(
            SurveyExecution.collection_session_id == collection.id,
            SurveyExecution.flow_action_id.in_([action.id for action in flow.actions if action.random_group]),
        )).all()
        check(len(selected) == 1, "sorteio não escolheu exatamente um questionário")
        decisions = json.loads(collection.decisions_json)
        check(len(decisions) == 1 and next(iter(decisions.values())) == selected[0].flow_action_id, "decisão aleatória não foi persistida")
        check(db.scalar(select(func.count(MessageQueue.id)).where(MessageQueue.kind == "phone_verification_thanks")) == 1, "agradecimento não foi criado")
        complete_phone_verification(db, verification)
        check(db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.collection_session_id == collection.id, SurveyExecution.flow_action_id.is_not(None))) == 3, "retomada duplicou a jornada")
        db.commit()
        flow_id = flow.id

    editor = client.get(f"/fluxos/{flow_id}/editar")
    check(editor.status_code == 200, "editor 3.4.1 não abriu")
    for marker in ("data-add-pre-confirmation", "data-condition-list", "data-add-condition", "random_group", "Cachorro", 'value="immediate">Agora, imediatamente', "flow-actions.js?v=3.6.0"):
        check(marker in editor.text, f"recurso visual ausente: {marker}")

print("OK - EscutaPet 3.4.1: pré-confirmação, condições E com opções reais, sorteio persistente e migração validados.")
