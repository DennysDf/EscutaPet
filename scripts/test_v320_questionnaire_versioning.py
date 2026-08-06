from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v320_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import EntryFlow, EntryFlowAction, Lead, MessageQueue, Question, Questionnaire, QuestionnaireVersion, SurveyAnswer, SurveyExecution, SystemSetting
from app.services.bootstrap import initialize_database
from app.services.collection import resolve_action_version
from app.services.engine import create_execution, record_answer, start_whatsapp_execution
from app.services.versioning import execution_questions, publish_questionnaire_version
from app.services.worker import process_once


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


initialize_database()
with SessionLocal() as db:
    lead = Lead(name="Versão Teste", phone="5562999999999", phone_normalized="5562999999999", source="manual", status="active", consent_research=True)
    questionnaire = Questionnaire(
        name="Pesquisa versionada", status="active", channels_json='["whatsapp"]', response_mode="identified",
        opening_message="Abertura v1", closing_message="Fechamento v1", alert_enabled=False,
    )
    questionnaire.questions = [
        Question(position=1, text="Pergunta de escolha v1", type="choice", options_json=json.dumps([
            {"id": "sim", "label": "Sim", "value": "sim"}, {"id": "nao", "label": "Não", "value": "não"}
        ], ensure_ascii=False), whatsapp_response_mode="buttons"),
        Question(position=2, text="Pergunta aberta v1", type="text"),
    ]
    db.add_all([lead, questionnaire])
    db.flush()
    version1, created = publish_questionnaire_version(db, questionnaire, user_id=1)
    check(created and version1.version_number == 1, "a versão 1 não foi publicada")
    old_execution = create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="test")
    old_id, questionnaire_id, lead_id, first_original_id = old_execution.id, questionnaire.id, lead.id, questionnaire.questions[0].id
    start_whatsapp_execution(db, old_execution)
    first_queue = db.scalar(select(MessageQueue).where(
        MessageQueue.execution_id == old_execution.id,
        MessageQueue.kind == "question",
    ))
    check(first_queue and first_queue.message_type == "buttons" and first_queue.version_question_id, "botões/fila não foram ligados à pergunta da v1")
    record_answer(db, old_execution, raw_text="Sim", interaction_id="sim", source="whatsapp")
    check(old_execution.current_position == 1, "a execução v1 não avançou para a segunda pergunta")
    db.commit()

with SessionLocal() as db:
    questionnaire = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
    current = [item for item in questionnaire.questions if item.active]
    current[0].text = "Pergunta de escolha editada v2"
    current[0].position = 2
    current[1].text = "Pergunta aberta editada v2"
    current[1].position = 1
    questionnaire.opening_message = "Abertura v2"
    questionnaire.questions.append(Question(position=3, text="Pergunta nova v2", type="text"))
    version2, created = publish_questionnaire_version(db, questionnaire, user_id=1)
    check(created and version2.version_number == 2, "a versão 2 não foi publicada")
    db.commit()

with SessionLocal() as db:
    old = db.scalar(select(SurveyExecution).options(
        selectinload(SurveyExecution.questionnaire_version).selectinload(QuestionnaireVersion.questions),
        selectinload(SurveyExecution.lead),
    ).where(SurveyExecution.id == old_id))
    frozen = execution_questions(old)
    check(old.questionnaire_version.version_number == 1, "a execução iniciada mudou para a versão 2")
    check([item.text for item in frozen] == ["Pergunta de escolha v1", "Pergunta aberta v1"], "ordem ou textos da v1 foram alterados")
    record_answer(db, old, raw_text="Resposta final antiga", source="whatsapp")
    check(old.status == "completed", "a execução antiga não concluiu na v1")
    lead = db.get(Lead, lead_id)
    questionnaire = db.get(Questionnaire, questionnaire_id)
    new_execution = create_execution(db, questionnaire, lead=lead, channel="interviewer", source="test")
    check(new_execution.questionnaire_version.version_number == 2, "a execução nova não recebeu a v2")
    check(execution_questions(new_execution)[0].text == "Pergunta aberta editada v2", "a execução v2 não recebeu a ordem nova")
    new_id = new_execution.id
    db.commit()

with SessionLocal() as db:
    questionnaire = db.get(Questionnaire, questionnaire_id)
    # Uma edição salva como rascunho é apenas alteração dos registros vivos.
    questionnaire.name = "Nome ainda em rascunho"
    db.commit()
    lead = db.get(Lead, lead_id)
    draft_safe = create_execution(db, questionnaire, lead=lead, channel="interviewer", source="draft-check")
    check(draft_safe.questionnaire_version.version_number == 2, "salvar rascunho alterou a versão usada por novas execuções")
    scheduled = create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="scheduled-check", is_test=True)
    scheduled_id = scheduled.id
    system = db.get(SystemSetting, 1)
    system.quiet_start_hour = 0
    system.quiet_end_hour = 0
    questionnaire.closing_message = "Fechamento v3"
    version3, created = publish_questionnaire_version(db, questionnaire, user_id=1)
    check(created and version3.version_number == 3, "a versão 3 de controle não foi publicada")
    check(scheduled.questionnaire_version_id != version3.id, "execução já agendada foi migrada silenciosamente")
    fresh = create_execution(db, questionnaire, lead=lead, channel="interviewer", source="fresh-check")
    check(fresh.questionnaire_version_id == version3.id, "execução posterior à publicação não recebeu a v3")
    flow = EntryFlow(name="Fluxo fixo", status="active")
    action = EntryFlowAction(name="Ação fixa", questionnaire_id=questionnaire.id, version_mode="fixed", fixed_version_id=version2.id)
    flow.actions.append(action)
    db.add(flow)
    db.flush()
    check(resolve_action_version(db, action).id == version2.id, "ação fixa não resolveu a versão escolhida")
    broken = SurveyExecution(
        questionnaire_id=questionnaire.id,
        questionnaire_version_id=None,
        lead_id=lead.id,
        public_token=secrets.token_urlsafe(20),
        channel="whatsapp",
        source="broken-version-check",
        status="scheduled",
        scheduled_at=scheduled.scheduled_at,
        is_test=True,
    )
    db.add(broken)
    db.flush()
    broken_id = broken.id
    db.commit()

# Simula reinício: um novo ciclo abre outra sessão e deve respeitar a versão
# já gravada, além de processar a fila pendente idempotentemente.
stats = process_once()
with SessionLocal() as db:
    scheduled = db.get(SurveyExecution, scheduled_id)
    check(scheduled.questionnaire_version.version_number == 2, "worker trocou a versão da execução agendada")
    check(scheduled.status == "active", "worker não iniciou a execução agendada")
    broken = db.get(SurveyExecution, broken_id)
    check(broken.status == "blocked" and "versão" in (broken.test_label or "").lower(), "worker não bloqueou a execução sem versão")
    check(db.scalar(select(func.count(MessageQueue.id)).where(MessageQueue.execution_id == scheduled_id)) >= 1, "worker não preservou/processou a fila da versão")
    old_answers = db.scalars(select(SurveyAnswer).where(SurveyAnswer.execution_id == old_id).order_by(SurveyAnswer.id)).all()
    check([answer.version_question.version.version_number for answer in old_answers] == [1, 1], "respostas antigas perderam a versão")
    check(db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.questionnaire_version_id.is_(None))) == 1, "a inconsistência operacional de controle foi alterada silenciosamente")

Path(database_path).unlink(missing_ok=True)
print("OK - 3.2.0 congela versões em execução, fila, respostas, agendamento e ações fixas.")
