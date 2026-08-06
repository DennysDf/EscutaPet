from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import func, select

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_catalog_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from app.database import SessionLocal
from app.models import EntryFlow, EntryFlowAction, Question, Questionnaire
from app.services.bootstrap import LEGACY_QUESTIONNAIRES, initialize_database


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


initialize_database()
initialize_database()

with SessionLocal() as db:
    keys = [item["key"] for item in LEGACY_QUESTIONNAIRES]
    questionnaires = db.scalars(select(Questionnaire).where(Questionnaire.seed_key.in_(keys))).all()
    check(len(questionnaires) == len(keys) == 9, "catálogo legado duplicou ou ficou incompleto")
    check(len({row.seed_key for row in questionnaires}) == 9, "chaves do catálogo não são únicas")
    question_count = db.scalar(
        select(func.count(Question.id)).join(Questionnaire).where(Questionnaire.seed_key.in_(keys))
    )
    check(question_count == 34, f"esperadas 34 perguntas do catálogo, encontradas {question_count}")

    quick = db.scalar(select(Questionnaire).where(Questionnaire.seed_key == "legacy13-quick"))
    flow = db.scalar(select(EntryFlow).where(EntryFlow.name == "Coleta rápida · legado 1.3"))
    check(flow is not None and flow.phone_verification_mode == "required", "fluxo rápido 1.3 não foi criado")
    action = db.scalar(select(EntryFlowAction).where(EntryFlowAction.flow_id == flow.id))
    check(
        action is not None
        and action.questionnaire_id == quick.id
        and action.trigger == "after_confirmation"
        and action.channel == "whatsapp"
        and action.require_confirmation,
        "ação do fluxo rápido 1.3 não preservou confirmação e continuidade pelo WhatsApp",
    )

Path(database_path).unlink(missing_ok=True)
print("OK - catálogo 1.6 e fluxo de coleta rápida 1.3 instalados sem duplicação.")
