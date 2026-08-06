from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

handle, database_path = tempfile.mkstemp(prefix="escutapet_production_clean_", suffix=".sqlite3")
os.close(handle)
os.environ.update(
    DATABASE_URL=f"sqlite:///{database_path}",
    AUTO_SEED_DEMO="1",
    REDIS_ENABLED="0",
    SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters",
)

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    Conversation,
    ConversationMessage,
    Lead,
    Pet,
    Question,
    Questionnaire,
    SurveyAnswer,
    SurveyExecution,
    User,
)
from app.services.bootstrap import initialize_database


def check(value, message):
    if not value:
        raise AssertionError(message)


initialize_database()
db = SessionLocal()
try:
    user = db.scalar(select(User).limit(1))
    questionnaire = db.scalar(select(Questionnaire).limit(1))
    question = db.scalar(select(Question).where(Question.questionnaire_id == questionnaire.id).limit(1))
    lead = Lead(name="Lead de teste", phone_normalized="5562999990000")
    db.add(lead)
    db.flush()
    pet = Pet(lead_id=lead.id, name="Bidu", species="Cão")
    conversation = Conversation(identity_key="test-clean", phone_normalized="5562999990000", lead_id=lead.id)
    db.add_all((pet, conversation))
    db.flush()
    message = ConversationMessage(conversation_id=conversation.id, direction="in", content="Teste")
    execution = SurveyExecution(questionnaire_id=questionnaire.id, lead_id=lead.id, public_token="clean-test-token")
    db.add_all((message, execution))
    db.flush()
    db.add(ConversationMessage(conversation_id=conversation.id, direction="out", content="Resposta", reply_to_message_id=message.id))
    db.add(SurveyAnswer(execution_id=execution.id, question_id=question.id, answer_text="Boa"))
    db.commit()
finally:
    db.close()

result = subprocess.run(
    [sys.executable, "tools/production_clean.py", "--confirm", "APAGAR"],
    cwd=ROOT,
    env=os.environ.copy(),
    capture_output=True,
    text=True,
)
check(result.returncode == 0, f"limpeza falhou: {result.stderr}\n{result.stdout}")

db = SessionLocal()
try:
    check(db.scalar(select(func.count()).select_from(Lead)) == 0, "lead não foi removido")
    check(db.scalar(select(func.count()).select_from(Pet)) == 0, "pet não foi removido")
    check(db.scalar(select(func.count()).select_from(Conversation)) == 0, "conversa não foi removida")
    check(db.scalar(select(func.count()).select_from(ConversationMessage)) == 0, "mensagem não foi removida")
    check(db.scalar(select(func.count()).select_from(SurveyExecution)) == 0, "execução não foi removida")
    check(db.scalar(select(func.count()).select_from(SurveyAnswer)) == 0, "resposta não foi removida")
    check(db.scalar(select(func.count()).select_from(User)) >= 1, "usuário foi removido")
    check(db.scalar(select(func.count()).select_from(Questionnaire)) >= 1, "questionário foi removido")
    check(db.scalar(select(func.count()).select_from(Question)) >= 1, "pergunta foi removida")
finally:
    db.close()

backups = list((ROOT / "backups").glob("antes_limpeza_producao_*"))
check(backups and any(item.suffix == ".sqlite3" for item in backups[-1].iterdir()), "backup SQLite não foi criado")
bat = (ROOT / "LIMPAR_PARA_PRODUCAO.bat").read_text(encoding="utf-8")
powershell = (ROOT / "tools" / "production_clean.ps1").read_text(encoding="utf-8")
check("production_clean.ps1" in bat and "powershell.exe" in bat, "BAT não usa o inicializador compatível")
for marker in ('"3.15"', '$ErrorActionPreference = "Continue"', ".venv\\Scripts\\python.exe", "import sqlalchemy", "production_clean.py"):
    check(marker in powershell, f"detecção de Python incompleta: {marker}")
print("OK - limpeza de produção remove operações, preserva configuração e cria backup.")
