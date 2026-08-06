from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v357_", suffix=".sqlite3")
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
from app.models import Lead, MessageQueue, Questionnaire, QuestionnaireVersion
from app.services.engine import active_questions, create_execution, record_answer, start_whatsapp_execution


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def form_data(name: str, questions: list[dict]) -> dict:
    return {
        "name": name, "description": "Condições 3.5.7", "objective": "satisfaction",
        "status": "active", "channels": "kiosk", "response_mode": "identified",
        "trigger_type": "manual", "delay_value": "0", "delay_unit": "days",
        "recurrence_days": "", "random_percent": "100", "audience_type": "all",
        "target_segment_id": "", "opening_message": "Olá, {{nome}}", "closing_message": "Obrigado, {{nome}}",
        "send_hour": "10", "max_attempts": "2", "retry_hours": "24", "stop_after_response": "on",
        "alert_threshold": "6", "alert_severity": "high", "questions_json": json.dumps(questions, ensure_ascii=False),
        "editor_action": "publish",
    }


CONSENT_KEY = "question:new:11111111-1111-4111-8111-111111111111"
CONDITIONAL_KEY = "question:new:22222222-2222-4222-8222-222222222222"
ALWAYS_KEY = "question:new:33333333-3333-4333-8333-333333333333"

choice = {
    "item_key": CONSENT_KEY, "text": "Deseja responder?", "type": "choice", "required": True,
    "options": [
        {"id": "option:yes", "label": "Sim, quero", "value": "accept"},
        {"id": "option:no", "label": "Agora não", "value": "decline"},
    ], "settings": {},
}
conditional = {
    "item_key": CONDITIONAL_KEY, "text": "Conte para {{nome_questionario}}", "type": "text", "required": True,
    "options": [], "settings": {"visibility": {
        "enabled": True, "source_item_key": CONSENT_KEY, "operator": "equals", "value": "accept",
    }},
}
always = {
    "item_key": ALWAYS_KEY, "text": "Última pergunta", "type": "yes_no", "required": True,
    "options": [], "settings": {},
}


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False).status_code == 303, "login falhou")
    page = client.get("/questionarios/novo")
    for marker in ("data-placeholder-dialog", "data-placeholder-value", "data-open-placeholder", "Inserir informação automática"):
        check(marker in page.text, f"catálogo de variáveis ausente: {marker}")

    response = client.post("/questionarios/novo", data=form_data("Condições 3.5.7", [choice, conditional, always]), follow_redirects=False)
    response_errors = re.findall(r'<li><a[^>]*>(.*?)</a>', response.text)
    check(response.status_code == 303, f"questionário condicional não foi criado: {response_errors}")
    questionnaire_id = int(response.headers["location"].split("/")[2])

    with SessionLocal() as db:
        questionnaire = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        questions = active_questions(questionnaire)
        rule = json.loads(questions[1].settings_json)["visibility"]
        check(rule["source_question_id"] == questions[0].id, "dependência nova não foi convertida para ID permanente")
        check(rule["source_item_key"] == f"question:{questions[0].id}", "chave estável da dependência não foi persistida")
        version = db.scalar(select(QuestionnaireVersion).options(selectinload(QuestionnaireVersion.questions)).where(QuestionnaireVersion.questionnaire_id == questionnaire_id, QuestionnaireVersion.status == "published"))
        check(json.loads(version.questions[1].settings_json)["visibility"]["value"] == "accept", "snapshot não congelou a condição")

        lead = Lead(name="Maria Teste", phone="5511999999999", phone_normalized="5511999999999", consent_research=True)
        db.add(lead); db.flush()
        whatsapp_execution = create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="test")
        start_whatsapp_execution(db, whatsapp_execution)
        record_answer(db, whatsapp_execution, raw_text="decline", source="whatsapp")
        queued_questions = db.scalars(select(MessageQueue).where(MessageQueue.execution_id == whatsapp_execution.id, MessageQueue.kind == "question").order_by(MessageQueue.id)).all()
        check(len(queued_questions) == 2 and "Última pergunta" in queued_questions[-1].payload_text, "WhatsApp não pulou a pergunta condicional")
        check(whatsapp_execution.current_position == 2, "posição do WhatsApp ficou presa na pergunta oculta")
        db.rollback()

    test_start = client.get(f"/questionarios/{questionnaire_id}/testar", follow_redirects=False)
    apply_url = test_start.headers["location"]
    check("Deseja responder?" in client.get(apply_url).text, "primeira pergunta não apareceu")
    client.post(apply_url, data={"answer": "decline"}, follow_redirects=False)
    skipped_page = client.get(apply_url)
    check("Última pergunta" in skipped_page.text and "Conte para" not in skipped_page.text, "resposta falsa não pulou a pergunta condicional")

    test_start = client.get(f"/questionarios/{questionnaire_id}/testar", follow_redirects=False)
    apply_url = test_start.headers["location"]
    client.post(apply_url, data={"answer": "accept"}, follow_redirects=False)
    visible_page = client.get(apply_url)
    check("Conte para Condições 3.5.7" in visible_page.text, "condição verdadeira ou variável no texto não foi aplicada")

    duplicated = client.post(f"/questionarios/{questionnaire_id}/duplicar", follow_redirects=False)
    check(duplicated.status_code == 303, "questionário condicional não foi duplicado")
    duplicate_id = int(duplicated.headers["location"].split("/")[2])
    with SessionLocal() as db:
        duplicate = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == duplicate_id))
        duplicate_questions = active_questions(duplicate)
        duplicate_rule = json.loads(duplicate_questions[1].settings_json)["visibility"]
        check(duplicate_rule["source_question_id"] == duplicate_questions[0].id, "duplicação manteve dependência apontando para o questionário original")

    invalid_second = dict(conditional)
    invalid_second["settings"] = {"visibility": {"enabled": True, "source_item_key": ALWAYS_KEY, "operator": "equals", "value": "sim"}}
    invalid = client.post("/questionarios/novo", data=form_data("Dependência futura", [choice, invalid_second, always]), follow_redirects=False)
    check(invalid.status_code == 400 and "pergunta anterior" in invalid.text, "dependência futura não foi bloqueada pelo servidor")

javascript = (PROJECT_DIR / "app/static/js/questionnaire-editor.js").read_text(encoding="utf-8")
for marker in ("conditionValueMarkup", "previousQuestionCards", "source_item_key", "setRangeText", "data-placeholder-identified"):
    check(marker in javascript, f"comportamento visual ausente: {marker}")

Path(database_path).unlink(missing_ok=True)
print("OK - EscutaPet 3.5.7: variáveis, condições anteriores, snapshot, tela e WhatsApp validados.")
