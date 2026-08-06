from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v311_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.main import app
from app.models import EditorSubmission, EntryFlow, Question, Questionnaire
from app.routers import entry, web
from app.services.engine import active_questions, channels


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def questionnaire_form(name: str, questions: list[dict], token: str = "") -> dict:
    return {
        "submission_token": token,
        "name": name,
        "description": "Teste confiável",
        "objective": "satisfaction",
        "status": "active",
        "channels": "kiosk",
        "response_mode": "identified",
        "trigger_type": "manual",
        "delay_value": "0",
        "delay_unit": "days",
        "audience_type": "all",
        "random_percent": "100",
        "opening_message": "Abertura",
        "closing_message": "Encerramento",
        "send_hour": "10",
        "max_attempts": "2",
        "retry_hours": "24",
        "alert_threshold": "6",
        "alert_severity": "high",
        "stop_after_response": "on",
        "questions_json": json.dumps(questions, ensure_ascii=False),
    }


def flow_form(registration_id: int, questionnaire_id: int, token: str = "", *, name: str = "Fluxo 3.1.1") -> dict:
    return {
        "submission_token": token,
        "name": name,
        "description": "Fluxo confiável",
        "status": "active",
        "profile_kiosk": "on",
        "profile_interviewer": "on",
        "welcome_title": "Bem-vindo",
        "welcome_text": "Vamos começar.",
        "registration_questionnaire_id": str(registration_id),
        "allow_existing_lookup": "on",
        "allow_no_pet": "on",
        "max_pets": "10",
        "phone_verification_mode": "send_continue",
        "phone_verification_timeout": "180",
        "allow_manual_confirmation": "on",
        "consent_terms_version": "1.0",
        "consent_research_text": "Aceito participar das pesquisas.",
        "consent_marketing_text": "Aceito receber campanhas.",
        "closing_title": "Obrigado!",
        "closing_text": "Cadastro concluído.",
        "actions_count": "1",
        "action_0_item_key": "action:new:test",
        "action_0_name": "Pesquisa posterior",
        "action_0_trigger": "after_registration",
        "action_0_questionnaire_id": str(questionnaire_id),
        "action_0_channel": "whatsapp",
        "action_0_delay_value": "2",
        "action_0_delay_unit": "hours",
        "action_0_schedule_mode": "exact_interval",
        "action_0_send_hour": "10",
        "action_0_require_confirmation": "on",
        "action_0_active": "on",
    }


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False).status_code == 303, "login falhou")

    # Pergunta vazia não pode desaparecer e precisa apontar para o cartão correto.
    empty_questions = [
        {"item_key": "question:new:kept", "text": "Pergunta válida", "type": "text", "required": True, "options": []},
        {"item_key": "question:new:empty", "text": "", "type": "text", "required": True, "options": []},
    ]
    response = client.post("/questionarios/novo", data=questionnaire_form("Preservar tudo", empty_questions), follow_redirects=False)
    check(response.status_code == 400, "pergunta vazia não bloqueou o salvamento")
    check("A pergunta 2 está sem texto." in response.text, "erro da pergunta vazia não foi identificado")
    check("Pergunta v\\u00e1lida" in response.text and "Preservar tudo" in response.text, "formulário não foi reconstruído")
    with SessionLocal() as db:
        check(not db.scalar(select(Questionnaire).where(Questionnaire.name == "Preservar tudo")), "questionário inválido foi gravado parcialmente")

    duplicate_options = [{"item_key": "question:new:choice", "text": "Escolha", "type": "choice", "required": True, "options": [{"label": "Sim", "value": "sim"}, {"label": " sim ", "value": "SIM"}]}]
    response = client.post("/questionarios/novo", data=questionnaire_form("Opções duplicadas", duplicate_options), follow_redirects=False)
    check(response.status_code == 400 and "duplicad" in response.text, "opções duplicadas não foram bloqueadas")

    # Criação válida e idempotência: o mesmo token não cria duas linhas.
    valid_questions = [{"item_key": "question:new:valid", "text": "Como foi?", "type": "score", "required": True, "options": [], "min_score": 0, "max_score": 10, "low_score_threshold": 6}]
    token = "questionnaire-double-click-token"
    response = client.post("/questionarios/novo", data=questionnaire_form("Criado uma vez", valid_questions, token), follow_redirects=False)
    check(response.status_code == 303 and "saved=1" in response.headers["location"], "questionário válido não foi criado")
    questionnaire_id = int(response.headers["location"].split("/")[2])
    duplicate = client.post("/questionarios/novo", data=questionnaire_form("Criado uma vez", valid_questions, token), follow_redirects=False)
    check(duplicate.status_code == 303 and duplicate.headers["location"] == response.headers["location"], "token idempotente não reutilizou o resultado")
    with SessionLocal() as db:
        check(db.scalar(select(func.count(Questionnaire.id)).where(Questionnaire.name == "Criado uma vez")) == 1, "duplo clique criou questionário duplicado")
        check(db.scalar(select(func.count(EditorSubmission.id)).where(EditorSubmission.token == token)) == 1, "trava persistente do questionário não foi registrada")
        original = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        original_name = original.name
        original_text = active_questions(original)[0].text
        original_question_id = active_questions(original)[0].id

    # Erro depois de reordenar preserva a ordem enviada e não altera o banco.
    reordered_invalid = [
        {"item_key": "question:new:second", "text": "Nova primeira", "type": "text", "required": False, "options": []},
        {"id": original_question_id, "item_key": f"question:{original_question_id}", "text": "", "type": "score", "required": True, "options": [], "min_score": 0, "max_score": 10},
    ]
    response = client.post(f"/questionarios/{questionnaire_id}/editar", data=questionnaire_form("Nome não persistido", reordered_invalid), follow_redirects=False)
    check(response.status_code == 400 and response.text.index("Nova primeira") < response.text.index(f'\"id\": {original_question_id}'), "ordem submetida não foi preservada")
    with SessionLocal() as db:
        original = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        check(original.name == original_name and active_questions(original)[0].text == original_text, "erro de edição alterou a versão persistida")

    # Falha após o início da mutação deve executar rollback explícito.
    original_sync = web._sync_questionnaire_questions
    def fail_after_question_sync(db, row, data):
        original_sync(db, row, data)
        raise RuntimeError("falha simulada")
    web._sync_questionnaire_questions = fail_after_question_sync
    try:
        response = client.post(f"/questionarios/{questionnaire_id}/editar", data=questionnaire_form("Rollback questionário", valid_questions), follow_redirects=False)
        check(response.status_code == 400 and "versão anterior" in response.text, "falha transacional do questionário não foi tratada")
    finally:
        web._sync_questionnaire_questions = original_sync
    with SessionLocal() as db:
        check(db.get(Questionnaire, questionnaire_id).name == original_name, "rollback do questionário falhou")

    with SessionLocal() as db:
        registration = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.seed_key == "structured-registration-v1"))
        target = db.scalar(select(Questionnaire).where(Questionnaire.status == "active", Questionnaire.response_mode == "identified", Questionnaire.id != registration.id))
        check(registration is not None and target is not None and "whatsapp" in channels(target), "catálogo necessário ao teste não existe")
        registration_id, target_id = registration.id, target.id

    # Erro de ação e condição conserva todos os campos e não cria fluxo.
    invalid_flow = flow_form(registration_id, target_id, name="Fluxo inválido preservado")
    invalid_flow.update({"action_0_trigger": "after_action", "action_0_depends_on_position": "0", "action_0_condition_operator": "equals", "action_0_condition_value": "Sim"})
    response = client.post("/fluxos/novo", data=invalid_flow, follow_redirects=False)
    check(response.status_code == 400 and "Escolha uma ação anterior" in response.text and "Fluxo inválido preservado" in response.text, "erro de dependência não preservou o fluxo")
    with SessionLocal() as db:
        check(not db.scalar(select(EntryFlow).where(EntryFlow.name == "Fluxo inválido preservado")), "fluxo inválido foi gravado")

    flow_token = "flow-double-click-token"
    response = client.post("/fluxos/novo", data=flow_form(registration_id, target_id, flow_token), follow_redirects=False)
    check(response.status_code == 303 and "saved=1" in response.headers["location"], "fluxo válido não foi criado")
    flow_id = int(response.headers["location"].split("/")[2])
    duplicate = client.post("/fluxos/novo", data=flow_form(registration_id, target_id, flow_token), follow_redirects=False)
    check(duplicate.status_code == 303 and duplicate.headers["location"] == response.headers["location"], "duplo clique criou outro fluxo")
    with SessionLocal() as db:
        check(db.scalar(select(func.count(EntryFlow.id)).where(EntryFlow.name == "Fluxo 3.1.1")) == 1, "idempotência do fluxo falhou")
        check(db.scalar(select(func.count(EditorSubmission.id)).where(EditorSubmission.token == flow_token)) == 1, "trava persistente do fluxo não foi registrada")
        original_flow_name = db.get(EntryFlow, flow_id).name

    original_action_sync = entry._sync_flow_action_data
    def fail_after_action_sync(db, row, data):
        original_action_sync(db, row, data)
        raise RuntimeError("falha simulada")
    entry._sync_flow_action_data = fail_after_action_sync
    try:
        response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, target_id, name="Rollback fluxo"), follow_redirects=False)
        check(response.status_code == 400 and "versão anterior" in response.text, "falha transacional do fluxo não foi tratada")
    finally:
        entry._sync_flow_action_data = original_action_sync
    with SessionLocal() as db:
        check(db.get(EntryFlow, flow_id).name == original_flow_name, "rollback do fluxo falhou")

    # Guardas do navegador exigidas pela 3.1.1 permanecem verificáveis no artefato.
    questionnaire_js = (PROJECT_DIR / "app/static/js/questionnaire-editor.js").read_text(encoding="utf-8")
    flow_js = (PROJECT_DIR / "app/static/js/flow-actions.js").read_text(encoding="utf-8")
    check(".filter(item => item.text)" not in questionnaire_js, "filtro silencioso de perguntas voltou")
    for source in (questionnaire_js, flow_js):
        check("beforeunload" in source and "submitting" in source and "Alterações não salvas" in source, "proteções locais do editor estão incompletas")

Path(database_path).unlink(missing_ok=True)
print("OK - EscutaPet 3.1.1 preservação, validação, idempotência e rollback validados.")
