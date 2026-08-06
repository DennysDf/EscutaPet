from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, path = tempfile.mkstemp(prefix="escutapet_v325_", suffix=".sqlite3")
os.close(handle); os.unlink(path)
os.environ.update(DATABASE_URL=f"sqlite:///{path}", AUTO_SEED_DEMO="1", REDIS_ENABLED="0", SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Lead, LeadSegment, Pet, Question, Questionnaire, Segment, SegmentAutomation, SegmentEvent, SegmentRule, SurveyExecution, User, utcnow
from app.services.segment_automation import automation_candidates, run_segment_automation
from app.services.segmentation import refresh_rule_segment
from app.services.versioning import publish_questionnaire_version


def check(value, message):
    if not value: raise AssertionError(message)


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False).status_code == 303, "login falhou")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        segment = Segment(name="Donos de cachorro", kind="automatic", description="Pessoas com cachorro")
        db.add(segment); db.flush()
        db.add(SegmentRule(segment_id=segment.id, position=1, field="pet_species", operator="equals", value="cachorro", group_mode="all"))
        lead = Lead(name="Ana", phone="5562999999999", phone_normalized="5562999999999", source="manual", consent_research=True, number_validated=True)
        lead.pets.append(Pet(name="Mel", species="Cachorro")); db.add(lead); db.flush()
        result = refresh_rule_segment(db, segment); db.commit()
        check(result["matched"] >= 1 and db.scalar(select(LeadSegment).where(LeadSegment.lead_id == lead.id, LeadSegment.segment_id == segment.id)), "regra não formou o público")
        check(db.scalar(select(SegmentEvent).where(SegmentEvent.event_type == "entered")), "entrada não foi registrada no histórico")

        questionnaire = Questionnaire(name="Pesquisa do segmento", status="active", response_mode="identified", channels_json='["whatsapp"]', opening_message="Olá!", closing_message="Obrigado", created_by_id=admin.id)
        questionnaire.questions = [Question(position=1, text="Como foi o atendimento?", type="yes_no", required=True)]
        db.add(questionnaire); db.flush(); publish_questionnaire_version(db, questionnaire, user_id=admin.id)
        automation = SegmentAutomation(segment_id=segment.id, questionnaire_id=questionnaire.id, name="Envio para donos", schedule_type="once", next_run_at=utcnow(), sample_percent=100, exclude_previous=True, require_confirmed=True, created_by_id=admin.id)
        db.add(automation); db.flush()
        candidates, stats = automation_candidates(db, automation)
        check(len(candidates) == 1 and stats["eligible"] == 1, "prévia de elegibilidade incorreta")
        sent = run_segment_automation(db, automation); db.commit()
        check(sent["created"] == 1 and db.scalar(select(SurveyExecution).where(SurveyExecution.source == f"segment_automation:{automation.id}")), "automação não criou execução")
        lead.pets[0].species = "Gato"; db.flush(); removed = refresh_rule_segment(db, segment); db.commit()
        check(removed["left"] == 1 and db.scalar(select(SegmentEvent).where(SegmentEvent.event_type == "left")), "saída do público não foi preservada")

    page = client.get(f"/segmentos?segment_id={segment.id}&tab=evolucao")
    check(page.status_code == 200 and "Central de segmentos" in page.text and "Evolução do público" in page.text and "segments.js?v=3.6.0" in page.text, "central visual não renderizou")

print("OK - EscutaPet 3.2.5: regras, histórico, prévia, automação e central visual validados.")
