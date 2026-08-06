from __future__ import annotations

import json
import os
import tempfile
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v3_test_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import Lead, LeadSegment, Questionnaire, Segment, SurveyExecution, ZapiConfig
from app.services.worker import process_once


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with TestClient(app) as client:
    check(client.get("/login").status_code == 200, "login não abriu")
    response = client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False)
    check(response.status_code == 303, "login falhou")
    for path in ["/", "/leads", "/questionarios", "/questionarios/novo", "/segmentos", "/alertas", "/conversas", "/relatorios", "/dispositivos", "/configuracoes", "/entrevistador", "/usuarios", "/conta"]:
        check(client.get(path).status_code == 200, f"página falhou: {path}")

    client.get("/leads/novo")
    response = client.post("/leads/novo", data={
        "name": "Pessoa de Teste",
        "phone": "(62) 99988-7766",
        "city": "Alto Horizonte",
        "consent_research": "on",
        "pet_name": "Thor",
        "pet_species": "Cachorro",
    }, follow_redirects=False)
    check(response.status_code == 303, "cadastro de lead falhou")

    questions = [{"text": "Qual sua nota?", "type": "score", "required": True, "options": [], "min_score": 0, "max_score": 10, "low_score_threshold": 6, "segment_low_id": None, "segment_high_id": None}]
    client.get("/questionarios/novo")
    response = client.post("/questionarios/novo", data={
        "name": "Questionário do teste", "description": "Teste", "objective": "satisfaction", "status": "active",
        "channels": "kiosk", "response_mode": "identified", "trigger_type": "manual", "audience_type": "all",
        "random_percent": "100", "opening_message": "Olá", "closing_message": "Obrigado", "send_hour": "10",
        "max_attempts": "2", "retry_hours": "24", "alert_enabled": "on", "alert_threshold": "6",
        "alert_severity": "high", "auto_segment": "on", "stop_after_response": "on", "questions_json": json.dumps(questions),
    }, follow_redirects=False)
    check(response.status_code == 303, "criação de questionário falhou")
    questionnaire_id = int(response.headers["location"].split("/")[2])
    response = client.get(f"/questionarios/{questionnaire_id}/testar", follow_redirects=False)
    check(response.status_code == 303, "laboratório não iniciou")
    apply_url = response.headers["location"]
    check(client.get(apply_url).status_code == 200, "questionário de teste não abriu")
    check(client.post(apply_url, data={"answer": "5"}, follow_redirects=False).status_code == 303, "resposta não foi salva")

    with SessionLocal() as db:
        secret = db.get(ZapiConfig, 1).webhook_secret
    response = client.post(f"/zapi/webhook/receber/{secret}", json={"phone": "5562999776655", "text": {"message": "oi"}, "messageId": "unknown-1"})
    check(response.status_code == 200 and response.json().get("action") == "consent_requested", "pedido de consentimento ao desconhecido falhou")
    with SessionLocal() as db:
        unknown = db.scalar(select(Lead).where(Lead.phone_normalized == "5562999776655"))
        check(unknown is not None and unknown.consent_research is False and unknown.status == "onboarding", "desconhecido recebeu consentimento presumido")
    process_once()
    response = client.post(f"/zapi/webhook/receber/{secret}", json={"phone": "5562999776655", "buttonsResponseMessage": {"buttonId": "consent:accept", "message": "Aceito participar"}, "messageId": "unknown-consent"})
    check(response.status_code == 200 and response.json().get("action") == "consent_accepted", "aceite explícito não iniciou o onboarding")
    response = client.post(f"/zapi/webhook/receber/{secret}", json={"phone": "5562999776655", "text": {"message": "Carlos"}, "messageId": "unknown-2"})
    check(response.status_code == 200, "resposta do onboarding falhou")
    process_once()
    response = client.post(f"/zapi/webhook/receber/{secret}", json={"phone": "5562999776655", "buttonsResponseMessage": {"buttonId": "dog", "message": "Cachorro"}, "messageId": "unknown-3"})
    check(response.status_code == 200, "classificação pelo webhook falhou")

with SessionLocal() as db:
    lead = db.scalar(select(Lead).where(Lead.phone_normalized == "5562999776655"))
    check(lead is not None and lead.name == "Carlos", "nome do onboarding não foi atualizado")
    dog = db.scalar(select(Segment).where(Segment.name == "Donos de cachorros"))
    check(db.scalar(select(func.count(LeadSegment.id)).where(LeadSegment.lead_id == lead.id, LeadSegment.segment_id == dog.id)) == 1, "segmentação automática falhou")
    check(db.scalar(select(func.count(Questionnaire.id))) >= 5, "questionários de demonstração ausentes")

Path(database_path).unlink(missing_ok=True)
print("OK - EscutaPet Inteligente 3.1.2 passou no teste de fumaça.")
