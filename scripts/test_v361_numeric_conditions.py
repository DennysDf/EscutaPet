from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, path = tempfile.mkstemp(prefix="escutapet_v361_numeric_", suffix=".sqlite3")
os.close(handle); os.unlink(path)
os.environ.update(DATABASE_URL=f"sqlite:///{path}", AUTO_SEED_DEMO="1", REDIS_ENABLED="0", SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Lead, MessageQueue, Question, Questionnaire, SurveyAnswer, User
from app.services.engine import advance_to_visible_question, create_execution, question_is_visible, record_answer
from app.services.versioning import latest_published_version, publish_questionnaire_version


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False).status_code == 303, "login falhou")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        questionnaire = Questionnaire(
            name="D+2 consolidado", objective="followup", status="active",
            channels_json='["whatsapp","kiosk"]', response_mode="identified",
            opening_message="Como foi a evolução?", closing_message="Obrigado!", created_by_id=admin.id,
        )
        score = Question(position=1, text="De 0 a 10, como está a evolução?", type="score", required=True, min_score=0, max_score=10)
        detractor = Question(position=2, text="O que podemos melhorar?", type="text", required=False)
        neutral = Question(position=3, text="O que faltou para nota máxima?", type="text", required=False)
        promoter = Question(position=4, text="Podemos usar seu depoimento?", type="yes_no", required=False)
        questionnaire.questions = [score, detractor, neutral, promoter]
        db.add(questionnaire); db.flush()

        detractor.settings_json = json.dumps({"visibility": {"enabled": True, "source_question_id": score.id, "operator": "lte", "value": "6"}})
        neutral.settings_json = json.dumps({"visibility": {"enabled": True, "source_question_id": score.id, "operator": "between", "value": "7", "value_max": "8"}})
        promoter.settings_json = json.dumps({"visibility": {"enabled": True, "source_question_id": score.id, "operator": "gte", "value": "9"}})
        db.flush()
        version, _ = publish_questionnaire_version(db, questionnaire, user_id=admin.id)
        check(version is not None, "publicação da versão falhou")
        db.commit()
        questionnaire_id = questionnaire.id

    def score_and_check(value: str) -> str | None:
        with SessionLocal() as db:
            q = db.get(Questionnaire, questionnaire_id)
            execution = create_execution(db, q, lead=None, channel="kiosk", source="test")
            db.flush()
            record_answer(db, execution, raw_text=value, source="web")
            db.commit()
            db.refresh(execution)
            question = advance_to_visible_question(db, execution)
            return question.text if question else None

    check(score_and_check("4") == detractor.text, "nota 4 deveria abrir a pergunta do detrator (lte 6)")
    check(score_and_check("6") == detractor.text, "nota 6 é a borda superior de lte 6 e deveria abrir a pergunta do detrator")
    check(score_and_check("7") == neutral.text, "nota 7 deveria abrir a pergunta neutra (between 7,8)")
    check(score_and_check("8") == neutral.text, "nota 8 é a borda superior de between 7,8 e deveria abrir a pergunta neutra")
    check(score_and_check("9") == promoter.text, "nota 9 deveria abrir a pergunta do promotor (gte 9)")
    check(score_and_check("10") == promoter.text, "nota 10 deveria abrir a pergunta do promotor (gte 9)")

    # Nota digitada como texto livre no canal WhatsApp aciona a mesma regra numérica.
    with SessionLocal() as db:
        q = db.get(Questionnaire, questionnaire_id)
        lead = Lead(name="Tutor WhatsApp", phone="5562997777777", phone_normalized="5562997777777", source="manual", consent_research=True)
        db.add(lead); db.flush()
        execution = create_execution(db, q, lead=lead, channel="whatsapp", source="test", scheduled_at=None)
        db.flush()
        record_answer(db, execution, raw_text="9", source="whatsapp")
        db.commit()
        last_message = db.scalar(select(MessageQueue).where(MessageQueue.execution_id == execution.id).order_by(MessageQueue.id.desc()))
        check(last_message is not None and "depoimento" in (last_message.payload_text or ""), "nota '9' via WhatsApp não abriu a pergunta do promotor")

    # Resposta não numérica na origem não derruba a execução: a pergunta condicional só some.
    with SessionLocal() as db:
        q = db.get(Questionnaire, questionnaire_id)
        version = latest_published_version(db, q)
        detractor_vq = next(item for item in version.questions if item.original_question_id == detractor.id)
        broken_execution = create_execution(db, q, lead=None, channel="kiosk", source="test")
        db.flush()
        broken_execution.current_position = 1
        db.add(SurveyAnswer(execution_id=broken_execution.id, question_id=score.id, answer_text="não sei", answer_value="não sei", numeric_value=None, source="web"))
        db.flush()
        visible = question_is_visible(db, broken_execution, detractor_vq)
        check(visible is False, "resposta não numérica na origem deveria apenas ocultar a pergunta condicional, não quebrar a execução")

print("OK - EscutaPet 3.6.1 C1: operadores numéricos gte/lte/between cobrem as três faixas do D+2 em um questionário só.")
