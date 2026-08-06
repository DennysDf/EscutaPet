from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v321_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal, engine
from app.main import app
from app.models import Question, Questionnaire, QuestionnaireVersion
from app.services.engine import active_questions


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def form_data(name: str, questions: list[dict], action: str = "publish") -> dict:
    return {
        "name": name,
        "description": "Editor progressivo 3.2.1",
        "objective": "satisfaction",
        "status": "active",
        "channels": "kiosk",
        "response_mode": "identified",
        "trigger_type": "manual",
        "delay_value": "0",
        "delay_unit": "days",
        "recurrence_days": "",
        "random_percent": "100",
        "audience_type": "all",
        "target_segment_id": "",
        "opening_message": "Olá",
        "closing_message": "Obrigado",
        "send_hour": "10",
        "max_attempts": "2",
        "retry_hours": "24",
        "stop_after_response": "on",
        "alert_threshold": "6",
        "alert_severity": "high",
        "questions_json": json.dumps(questions, ensure_ascii=False),
        "editor_action": action,
    }


multiple = {
    "item_key": "question:new:multiple",
    "text": "Quais pontos foram positivos?",
    "type": "multiple_choice",
    "required": True,
    "options": [
        {"id": "option:team", "label": "Equipe", "value": "team"},
        {"id": "option:speed", "label": "Agilidade", "value": "speed"},
        {"id": "option:place", "label": "Estrutura", "value": "place"},
    ],
    "settings": {
        "min_selections": "1",
        "max_selections": "2",
        "presentation": "buttons",
        "allow_other": True,
        "shuffle_options": True,
        "metadata": "origem: teste 3.2.1",
    },
}
text_question = {
    "item_key": "question:new:text",
    "text": "Deixe um comentário",
    "type": "text",
    "required": False,
    "options": [],
    "settings": {"text_format": "long", "max_length": "240", "placeholder": "Escreva aqui"},
}

with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False).status_code == 303, "login falhou")
    page = client.get("/questionarios/novo")
    check(page.status_code == 200, "novo editor não abriu")
    for marker in (
        "questionnaire-commandbar", "data-editor-mode=\"simple\"", "data-editor-mode=\"advanced\"",
        "data-editor-tab=\"general\"", "data-editor-tab=\"questions\"", "data-editor-tab=\"logic\"",
        "data-editor-tab=\"channels\"", "data-editor-tab=\"segments\"", "data-editor-tab=\"publication\"",
        "data-questionnaire-template=\"satisfaction\"", "data-preview-mode=\"whatsapp\"",
    ):
        check(marker in page.text, f"marcador do editor ausente: {marker}")

    response = client.post("/questionarios/novo", data=form_data("Editor 3.2.1", [multiple, text_question]), follow_redirects=False)
    check(response.status_code == 303, f"questionário com múltipla escolha não foi criado: {response.text[:500]}")
    questionnaire_id = int(response.headers["location"].split("/")[2])

    with SessionLocal() as db:
        questionnaire = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        questions = active_questions(questionnaire)
        check([item.type for item in questions] == ["multiple_choice", "text"], "tipos não foram persistidos")
        settings = json.loads(questions[0].settings_json)
        check(settings["min_selections"] == "1" and settings["max_selections"] == "2", "configurações específicas foram perdidas")
        version = db.scalar(select(QuestionnaireVersion).where(QuestionnaireVersion.questionnaire_id == questionnaire_id, QuestionnaireVersion.status == "published"))
        check(version is not None and json.loads(version.questions[0].settings_json)["presentation"] == "buttons", "snapshot não congelou as configurações")

    edit = client.get(f"/questionarios/{questionnaire_id}/editar")
    check(edit.status_code == 200 and "multiple_choice" in edit.text and "Quais pontos foram positivos?" in edit.text, "editor não recarregou os dados")

    start = client.get(f"/questionarios/{questionnaire_id}/testar", follow_redirects=False)
    check(start.status_code == 303, "teste real não iniciou")
    apply_url = start.headers["location"]
    apply_page = client.get(apply_url)
    check("answer-checkboxes" in apply_page.text and "Equipe" in apply_page.text, "múltipla escolha não foi renderizada na aplicação")
    answered = client.post(apply_url, data={"answer": ["team", "speed"]}, follow_redirects=False)
    check(answered.status_code == 303, "múltipla escolha válida não foi aceita")
    check("Deixe um comentário" in client.get(apply_url).text, "execução não avançou depois da múltipla escolha")

    custom_start = client.get(f"/questionarios/{questionnaire_id}/testar", follow_redirects=False)
    custom_url = custom_start.headers["location"]
    custom_answer = client.post(custom_url, data={"answer": ["team", "Acolhimento"]}, follow_redirects=False)
    check(custom_answer.status_code == 303 and "Deixe um comentário" in client.get(custom_url).text, "opção Outro não funcionou")

    invalid = dict(multiple)
    invalid["settings"] = {"min_selections": "3", "max_selections": "1"}
    response = client.post("/questionarios/novo", data=form_data("Inválido 3.2.1", [invalid]), follow_redirects=False)
    check(response.status_code == 400 and "máximo de escolhas" in response.text.lower(), "limites inválidos não foram bloqueados")

columns = {item["name"] for item in inspect(engine).get_columns("questions")}
version_columns = {item["name"] for item in inspect(engine).get_columns("questionnaire_version_questions")}
check("settings_json" in columns and "settings_json" in version_columns, "migração compatível de configurações não foi criada")

javascript = (PROJECT_DIR / "app/static/js/questionnaire-editor.js").read_text(encoding="utf-8")
stylesheet = (PROJECT_DIR / "app/static/css/visual-v3.css").read_text(encoding="utf-8")
for marker in ("beforeunload", "submitting", "data-question-drag-handle", "data-option-up", "data-duplicate-option", "replacement_question_id"):
    check(marker in javascript, f"proteção anterior ausente: {marker}")
for marker in ("questions-workspace", "data-edit-mode=\"simple\"", "@media(max-width:760px)"):
    check(marker in stylesheet, f"regra responsiva ausente: {marker}")

Path(database_path).unlink(missing_ok=True)
print("OK - EscutaPet 3.2.1 editor progressivo, tipos condicionais, prévias e snapshot validados.")
