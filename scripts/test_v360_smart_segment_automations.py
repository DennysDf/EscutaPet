from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, path = tempfile.mkstemp(prefix="escutapet_v360_", suffix=".sqlite3")
os.close(handle)
os.unlink(path)
os.environ.update(
    DATABASE_URL=f"sqlite:///{path}",
    AUTO_SEED_DEMO="0",
    REDIS_ENABLED="0",
    SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters",
)

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import (
    Lead,
    Questionnaire,
    Question,
    Segment,
    SegmentAutomation,
    SegmentAutomationEnrollment,
    SegmentAutomationQuestionnaire,
    SurveyExecution,
    User,
    utcnow,
)
from app.services.segmentation import attach_segment, detach_segment
from app.services.segment_automation import process_segment_automations
from app.services.versioning import publish_questionnaire_version


def check(value, message):
    if not value:
        raise AssertionError(message)


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False).status_code == 303, "login falhou")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        segment = Segment(name="Pós-atendimento", kind="manual")
        db.add(segment)
        db.flush()

        questionnaires = []
        for name in ("Satisfação", "Acompanhamento"):
            questionnaire = Questionnaire(
                name=name,
                status="active",
                response_mode="identified",
                channels_json='["whatsapp"]',
                opening_message="Olá!",
                closing_message="Obrigado!",
                created_by_id=admin.id,
            )
            questionnaire.questions = [Question(position=1, text=f"Pergunta {name}", type="yes_no", required=True)]
            db.add(questionnaire)
            db.flush()
            publish_questionnaire_version(db, questionnaire, user_id=admin.id)
            questionnaires.append(questionnaire)

        lead = Lead(
            name="Ana",
            phone="5562999998801",
            phone_normalized="5562999998801",
            source="manual",
            consent_research=True,
            number_validated=True,
        )
        db.add(lead)
        db.flush()
        attach_segment(db, lead.id, segment.id, origin="manual", confidence=1.0, reason="Teste")

        automation = SegmentAutomation(
            segment_id=segment.id,
            questionnaire_id=questionnaires[0].id,
            name="Jornada pós-atendimento",
            trigger_type="hybrid",
            schedule_type="recurring",
            recurrence_days=1,
            entry_delay_value=0,
            entry_delay_unit="minutes",
            selection_strategy="round_robin",
            distribution_mode="fixed",
            send_window_start=0,
            send_window_end=1439,
            sample_percent=100,
            sample_mode="per_cycle",
            repeat_policy="allow",
            exclude_previous=False,
            cooldown_days=1,
            cancel_on_exit=True,
            block_while_active=True,
            status="active",
            created_by_id=admin.id,
        )
        db.add(automation)
        db.flush()
        for position, questionnaire in enumerate(questionnaires, start=1):
            db.add(SegmentAutomationQuestionnaire(automation_id=automation.id, questionnaire_id=questionnaire.id, position=position))
        db.commit()
        automation_id, lead_id, segment_id = automation.id, lead.id, segment.id

        first = process_segment_automations(db)
        db.commit()
        check(first["segment_enrollments"] == 1 and first["segment_enrollments_processed"] == 1, "entrada não criou/processou inscrição")
        enrollment = db.scalar(select(SegmentAutomationEnrollment).where(SegmentAutomationEnrollment.automation_id == automation_id, SegmentAutomationEnrollment.lead_id == lead_id))
        executions = db.scalars(select(SurveyExecution).where(SurveyExecution.lead_id == lead_id, SurveyExecution.source == f"segment_automation:{automation_id}").order_by(SurveyExecution.id)).all()
        check(enrollment and enrollment.cycle_number == 1 and len(executions) == 1, "primeiro ciclo não foi gravado")
        check(executions[0].questionnaire_id == questionnaires[0].id and executions[0].idempotency_key, "primeira pesquisa/idempendência incorreta")

        executions[0].status = "completed"
        enrollment.next_due_at = utcnow()
        db.flush()
        second = process_segment_automations(db)
        db.commit()
        executions = db.scalars(select(SurveyExecution).where(SurveyExecution.lead_id == lead_id, SurveyExecution.source == f"segment_automation:{automation_id}").order_by(SurveyExecution.id)).all()
        check(second["segment_enrollments_processed"] == 1 and len(executions) == 2, "recorrência individual não criou segundo ciclo")
        check(executions[1].questionnaire_id == questionnaires[1].id, "rodízio não alternou o questionário")

        detach_segment(db, lead_id, segment_id, origin="manual", reason="Saiu do público")
        db.flush()
        process_segment_automations(db)
        db.commit()
        enrollment = db.scalar(select(SegmentAutomationEnrollment).where(SegmentAutomationEnrollment.automation_id == automation_id, SegmentAutomationEnrollment.lead_id == lead_id))
        cancelled_execution = db.scalar(select(SurveyExecution).where(
            SurveyExecution.lead_id == lead_id,
            SurveyExecution.source == f"segment_automation:{automation_id}",
            SurveyExecution.status == "cancelled",
        ).order_by(SurveyExecution.id.desc()))
        check(enrollment.status == "cancelled" and enrollment.next_due_at is None, "saída do segmento não cancelou a jornada")
        check(cancelled_execution is not None, "execução futura não foi cancelada ao sair do segmento")

        new_lead = Lead(
            name="Bruno",
            phone="5562999998802",
            phone_normalized="5562999998802",
            source="manual",
            consent_research=True,
            number_validated=True,
        )
        db.add(new_lead)
        db.flush()
        attach_segment(db, new_lead.id, segment_id, origin="manual", confidence=1.0, reason="Entrou depois")
        db.commit()
        new_lead_id = new_lead.id
        later = process_segment_automations(db)
        db.commit()
        check(later["segment_enrollments"] == 1, "novo segmentado não foi inscrito automaticamente")
        check(db.scalar(select(SurveyExecution.id).where(SurveyExecution.lead_id == new_lead_id, SurveyExecution.source == f"segment_automation:{automation_id}")), "novo segmentado não recebeu agendamento")

    page = client.get(f"/segmentos?segment_id={segment_id}&tab=automacoes")
    check(page.status_code == 200, "página de segmentos não abriu")
    for marker in ("Jornadas inteligentes", "Ao entrar no segmento", "Aleatória sem repetir", "segments.js?v=3.6.0"):
        check(marker in page.text, f"interface 3.6.0 ausente: {marker}")

    response = client.post(
        f"/segmentos/{segment_id}/automacoes",
        data={
            "trigger_type": "on_entry",
            "questionnaire_ids": [str(questionnaires[0].id), str(questionnaires[1].id)],
            "selection_strategy": "random_no_repeat",
            "entry_delay_value": "2",
            "entry_delay_unit": "hours",
            "distribution_mode": "random",
            "send_window_start": "09:00",
            "send_window_end": "17:00",
            "sample_percent": "100",
            "sample_mode": "per_cycle",
            "repeat_policy": "cooldown",
            "cooldown_days": "14",
            "block_while_active": "on",
            "cancel_on_exit": "on",
            "name": "Nova jornada pela rota",
        },
        follow_redirects=False,
    )
    check(response.status_code == 303, "rota de criação da automação inteligente falhou")
    with SessionLocal() as db:
        route_automation = db.scalar(select(SegmentAutomation).where(SegmentAutomation.name == "Nova jornada pela rota"))
        check(route_automation and route_automation.trigger_type == "on_entry", "gatilho da rota não foi persistido")
        links = db.scalars(select(SegmentAutomationQuestionnaire).where(SegmentAutomationQuestionnaire.automation_id == route_automation.id)).all()
        check(len(links) == 2, "seleção múltipla de questionários não foi persistida")

print("OK - EscutaPet 3.6.0: inscrição por entrada, recorrência individual, rodízio, cancelamento e seleção múltipla validados.")
