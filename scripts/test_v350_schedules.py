from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, database_path = tempfile.mkstemp(prefix="escutapet_v350_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ.update(
    DATABASE_URL=f"sqlite:///{database_path}",
    AUTO_SEED_DEMO="1",
    REDIS_ENABLED="0",
    SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters",
)

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AuditLog, City, Lead, MessageQueue, Questionnaire, SurveyExecution, User, utcnow
from app.services.engine import channels, create_execution
from app.services.scheduling import create_whatsapp_test_execution
from app.services.security import hash_password
from app.services.versioning import latest_published_version, version_config


def check(value, message):
    if not value:
        raise AssertionError(message)


with TestClient(app) as client:
    with SessionLocal() as db:
        questionnaire = next(
            item
            for item in db.scalars(select(Questionnaire).where(Questionnaire.status == "active")).all()
            if (version := latest_published_version(db, item))
            and version_config(version).response_mode == "identified"
            and "whatsapp" in channels(version_config(version))
        )
        version = latest_published_version(db, questionnaire)
        city_a = City(name="Agenda permitida", state="GO")
        city_b = City(name="Agenda restrita", state="SP")
        db.add_all([city_a, city_b])
        db.flush()
        operator = User(
            name="Operador da agenda",
            username="agenda",
            password_hash=hash_password("agenda123"),
            role="operator",
            all_cities=False,
            city_ids_json=json.dumps([city_a.id]),
            timezone_name="America/Sao_Paulo",
        )
        lead_a = Lead(name="Lead da agenda", phone="5562999999701", phone_normalized="5562999999701", city_id=city_a.id, consent_research=True)
        lead_b = Lead(name="Lead sigiloso", phone="5562999999702", phone_normalized="5562999999702", city_id=city_b.id, consent_research=True)
        db.add_all([operator, lead_a, lead_b])
        db.flush()
        scheduled = create_execution(db, questionnaire, lead=lead_a, source="manual", scheduled_at=utcnow() + timedelta(days=2), questionnaire_version=version)
        blocked = create_execution(db, questionnaire, lead=lead_a, source="registration", scheduled_at=utcnow() + timedelta(days=7), questionnaire_version=version)
        blocked.status = "blocked"
        blocked.test_label = "Aguardando confirmação"
        active = create_execution(db, questionnaire, lead=lead_a, source="lead_detail", questionnaire_version=version)
        active.status = "active"
        active.started_at = utcnow()
        failed = MessageQueue(execution_id=active.id, lead_id=lead_a.id, phone=lead_a.phone_normalized, payload_text="Pergunta", status="failed", attempt=3, error_message="Falha simulada")
        restricted = create_execution(db, questionnaire, lead=lead_b, source="manual", scheduled_at=utcnow() + timedelta(days=3), questionnaire_version=version)
        test_execution, error = create_whatsapp_test_execution(db, questionnaire, "(62) 99999-9703")
        check(not error and test_execution and test_execution.is_test, "teste isolado não foi criado")
        db.add(failed)
        db.commit()
        scheduled_id, blocked_id, active_id, restricted_id, test_id = scheduled.id, blocked.id, active.id, restricted.id, test_execution.id
        frozen_version_id = scheduled.questionnaire_version_id

    check(client.post("/login", data={"username": "agenda", "password": "agenda123"}, follow_redirects=False).status_code == 303, "login do operador falhou")
    page = client.get("/agendamentos")
    check(page.status_code == 200, f"central não abriu: {page.status_code}")
    for marker in ("Central operacional", "Próximos sete dias", "Reagendar", "Falha simulada", "schedules.js?v=3.6.0"):
        check(marker.lower() in page.text.lower(), f"recurso visual ausente: {marker}")
    check(f"#{scheduled_id}" in page.text and f"#{restricted_id}" not in page.text, "escopo por cidade não foi respeitado")
    check(f"#{test_id}" not in page.text, "teste apareceu na visão de produção")
    test_page = client.get("/agendamentos?scope=tests")
    check(f"#{test_id}" in test_page.text and "TESTE" in test_page.text, "visão isolada de testes falhou")
    check(f"#{test_id}" in client.get("/agendamentos?origin=test").text, "filtro de origem não mudou automaticamente para testes")

    response = client.post(f"/agendamentos/{blocked_id}/enviar-agora", follow_redirects=False)
    check(response.status_code == 303, "envio imediato falhou")
    response = client.post(f"/agendamentos/{scheduled_id}/reagendar", data={"scheduled_at": "2026-08-12T10:30"}, follow_redirects=False)
    check(response.status_code == 303, "reagendamento falhou")
    response = client.post(f"/agendamentos/{active_id}/repetir-falha", follow_redirects=False)
    check(response.status_code == 303, "repetição de falha não foi aceita")
    response = client.post(f"/agendamentos/{scheduled_id}/cancelar", data={"reason": "Solicitação do responsável"}, follow_redirects=False)
    check(response.status_code == 303, "cancelamento falhou")
    check(client.post(f"/agendamentos/{restricted_id}/enviar-agora", follow_redirects=False).status_code == 403, "ação fora da cidade foi permitida")

    with SessionLocal() as db:
        scheduled = db.get(SurveyExecution, scheduled_id)
        blocked = db.get(SurveyExecution, blocked_id)
        failed = db.scalar(select(MessageQueue).where(MessageQueue.execution_id == active_id))
        check(scheduled.status == "cancelled", "execução não foi cancelada")
        check(blocked.status == "scheduled" and blocked.scheduled_at <= utcnow(), "envio imediato não liberou a execução")
        check(failed.status == "pending" and failed.attempt == 0 and not failed.error_message, "mensagem falha não voltou à fila")
        check(scheduled.questionnaire_version_id == frozen_version_id, "ação operacional trocou a versão congelada")
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id.in_([scheduled_id, blocked_id, active_id]))).all())
        check({"schedule_send_now", "schedule_reschedule", "schedule_retry_failed_message", "schedule_cancel"}.issubset(actions), "auditoria operacional incompleta")

    routed_test = client.post(
        "/agendamentos/testar",
        data={"questionnaire_id": questionnaire.id, "phone": "(62) 99999-9704"},
        follow_redirects=False,
    )
    check(routed_test.status_code == 303 and "/questionarios/testes/" in routed_test.headers["location"], "atalho de teste real falhou")
    with SessionLocal() as db:
        routed_execution = db.scalar(select(SurveyExecution).where(SurveyExecution.source == "whatsapp_laboratory", SurveyExecution.lead.has(Lead.phone_normalized == "5562999999704")))
        check(routed_execution and routed_execution.is_test and routed_execution.questionnaire_version_id, "rota não preservou isolamento e versão do teste")

css = (ROOT / "app/static/css/visual-v3.css").read_text(encoding="utf-8")
check("central de agendamentos e execuções" in css and ".schedule-week-grid" in css and ".schedule-row" in css, "refinamento visual da central ausente")
base = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
check('href="/agendamentos"' in base and 'data-label="Agendamentos"' in base, "atalho da navegação ausente")

print("OK - EscutaPet 3.5.7: central, filtros, cidades, testes isolados, ações, auditoria e versão congelada validados.")
