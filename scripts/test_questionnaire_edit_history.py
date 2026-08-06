from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_edit_history_", suffix=".sqlite3")
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
from app.models import Question, Questionnaire, SurveyAnswer
from app.services.engine import active_questions


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def form_data(name: str, questions: list[dict]) -> dict:
    return {
        "name": name,
        "description": "Regressão do editor",
        "objective": "satisfaction",
        "status": "active",
        "channels": "kiosk",
        "response_mode": "identified",
        "trigger_type": "manual",
        "audience_type": "all",
        "random_percent": "100",
        "opening_message": "Olá",
        "closing_message": "Obrigado",
        "send_hour": "10",
        "max_attempts": "2",
        "retry_hours": "24",
        "alert_threshold": "6",
        "alert_severity": "high",
        "stop_after_response": "on",
        "questions_json": json.dumps(questions, ensure_ascii=False),
    }


with TestClient(app) as client:
    client.get("/login")
    response = client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False)
    check(response.status_code == 303, "login falhou")

    initial = [
        {"text": "Pergunta respondida", "type": "score", "required": True, "options": [], "min_score": 0, "max_score": 10},
        {"text": "Pergunta ainda sem resposta", "type": "text", "required": False, "options": [], "min_score": 0, "max_score": 10},
    ]
    client.get("/questionarios/novo")
    response = client.post("/questionarios/novo", data=form_data("Teste de histórico", initial), follow_redirects=False)
    check(response.status_code == 303, "questionário não foi criado")
    questionnaire_id = int(response.headers["location"].split("/")[2])

    response = client.get(f"/questionarios/{questionnaire_id}/testar", follow_redirects=False)
    check(response.status_code == 303, "execução de teste não iniciou")
    apply_url = response.headers["location"]
    check(client.post(apply_url, data={"answer": "7"}, follow_redirects=False).status_code == 303, "resposta não foi registrada")

    with SessionLocal() as db:
        questionnaire = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        current = active_questions(questionnaire)
        first_id, second_id = current[0].id, current[1].id
        check(db.scalar(select(func.count(SurveyAnswer.id)).where(SurveyAnswer.question_id == first_id)) == 1, "histórico de resposta ausente")

    edited = [
        {"id": first_id, "text": "Pergunta respondida e editada", "type": "score", "required": True, "options": [], "min_score": 0, "max_score": 10},
        {"text": "Nova pergunta", "type": "text", "required": False, "options": [], "min_score": 0, "max_score": 10},
    ]
    client.get(f"/questionarios/{questionnaire_id}/editar")
    response = client.post(f"/questionarios/{questionnaire_id}/editar", data=form_data("Teste de histórico", edited), follow_redirects=False)
    check(response.status_code == 303, "edição com histórico retornou erro")

    with SessionLocal() as db:
        questionnaire = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        current = active_questions(questionnaire)
        check(len(current) == 2, "quantidade ativa incorreta após edição")
        check(current[0].id == first_id, "pergunta respondida perdeu sua identidade")
        check(current[0].text == "Pergunta respondida e editada", "alteração não foi persistida")
        removed = db.get(Question, second_id)
        check(removed is not None and removed.active is False, "pergunta publicada deveria ter sido arquivada")
        check(db.scalar(select(func.count(SurveyAnswer.id)).where(SurveyAnswer.question_id == first_id)) == 1, "resposta histórica foi perdida")

    # Agora remove também a pergunta que possui resposta: deve arquivar, não excluir.
    with SessionLocal() as db:
        questionnaire = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        new_question = active_questions(questionnaire)[1]
        remaining = [{
            "id": new_question.id,
            "text": new_question.text,
            "type": new_question.type,
            "required": new_question.required,
            "options": [],
            "min_score": new_question.min_score,
            "max_score": new_question.max_score,
        }]

    client.get(f"/questionarios/{questionnaire_id}/editar")
    response = client.post(f"/questionarios/{questionnaire_id}/editar", data=form_data("Teste de histórico", remaining), follow_redirects=False)
    check(response.status_code == 303, "remoção de pergunta respondida retornou erro")

    with SessionLocal() as db:
        archived = db.get(Question, first_id)
        check(archived is not None, "pergunta respondida foi excluída")
        check(archived.active is False and archived.archived_at is not None, "pergunta respondida não foi arquivada")
        check(db.scalar(select(func.count(SurveyAnswer.id)).where(SurveyAnswer.question_id == first_id)) == 1, "resposta perdeu a chave estrangeira")
        questionnaire = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        check(all(question.id != first_id for question in active_questions(questionnaire)), "pergunta arquivada ainda aparece no fluxo")

Path(database_path).unlink(missing_ok=True)
print("OK - edição preserva respostas e arquiva perguntas com histórico.")
