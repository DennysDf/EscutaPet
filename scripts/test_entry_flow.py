from __future__ import annotations

import os
import json
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
handle, database_path = tempfile.mkstemp(prefix="escutapet_entry_test_", suffix=".sqlite3")
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
from app.models import CollectionPet, CollectionSession, ConversationMessage, Device, EntryFlow, Lead, MessageQueue, PhoneVerification, SurveyExecution, WebhookEvent, ZapiConfig
from app.services.bootstrap import recover_received_callbacks


def check(value, message):
    if not value:
        raise AssertionError(message)


with TestClient(app) as client:
    login = client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False)
    check(login.status_code == 303, "login falhou")
    check(client.get("/fluxos/novo").status_code == 200, "editor de fluxo não abriu")

    with SessionLocal() as db:
        flow = db.scalar(select(EntryFlow).where(EntryFlow.status == "active").order_by(EntryFlow.id))
        device = db.scalar(select(Device).order_by(Device.id))
        check(flow and device, "demonstração não criou fluxo e dispositivo")
        flow_id, device_token = flow.id, device.token

    page = client.get(f"/coleta/{device_token}/fluxo/{flow_id}")
    check(page.status_code == 200 and "Adicionar outro pet" in page.text, "formulário completo não abriu")
    response = client.post(
        f"/coleta/{device_token}/fluxo/{flow_id}",
        data={
            "name": "Guilherme Teste",
            "phone": "(62) 99911-2233",
            "city": "Alto Horizonte",
            "neighborhood": "Centro",
            "consent_research": "on",
            "consent_marketing": "on",
            "pet_name": ["Thor", "Luna"],
            "pet_species": ["Cachorro", "Gato"],
            "pet_reason": ["Consulta anual", "Vacinação"],
            "pet_service_type": ["Consulta", "Vacinação"],
            "pet_service_status": ["Já foi realizado", "Será realizado"],
            "pet_description": ["Tudo bem", "Dose anual"],
        },
        follow_redirects=False,
    )
    check(response.status_code == 303 and response.headers["location"].startswith("/aplicar/"), "ação imediata na tela não iniciou")
    survey_url = response.headers["location"]

    with SessionLocal() as db:
        lead = db.scalar(select(Lead).options(selectinload(Lead.pets)).where(Lead.phone_normalized == "5562999112233"))
        check(lead and len(lead.pets) == 2, "múltiplos pets não foram persistidos")
        session = db.scalar(select(CollectionSession).where(CollectionSession.lead_id == lead.id))
        check(session and db.scalar(select(func.count(CollectionPet.id)).where(CollectionPet.collection_session_id == session.id)) == 2, "visita por pet não foi persistida")
        verification = db.scalar(select(PhoneVerification).where(PhoneVerification.collection_session_id == session.id))
        check(verification and verification.message_queue_id, "confirmação do WhatsApp não foi enfileirada")
        queue = db.get(MessageQueue, verification.message_queue_id)
        check(queue.message_type == "buttons" and "verify_phone:" in queue.buttons_json, "botão de confirmação não foi criado")
        secret = db.get(ZapiConfig, 1).webhook_secret
        verification_token = verification.token
        session_token = session.public_token

    # Responde o questionário imediato demonstrativo.
    check(client.post(survey_url, data={"answer": "8"}, follow_redirects=False).status_code == 303, "nota não foi salva")
    check(client.post(survey_url, data={"answer": "atendimento"}, follow_redirects=False).status_code == 303, "opção não foi salva")
    check(client.post(survey_url, data={"answer": "Muito bom"}, follow_redirects=False).status_code == 303, "texto não foi salvo")
    completed = client.get(survey_url)
    check("Continuar" in completed.text, "questionário não retornou ao fluxo")

    payload = {
        "phone": "5562999112233",
        "messageId": "verify-click-1",
        "type": "ReceivedCallback",
        "buttonsResponseMessage": {"buttonId": f"verify_phone:{verification_token}", "message": "Confirmar meu WhatsApp"},
    }
    confirmed = client.post(f"/zapi/webhook/receber/{secret}", json=payload)
    check(confirmed.status_code == 200 and confirmed.json().get("action") == "phone_confirmed", "clique de confirmação não foi processado")
    status = client.get(f"/coleta/sessao/{session_token}/status").json()
    check(status["lead_validated"] is True, "lead não ficou validado")

    with SessionLocal() as db:
        lead = db.scalar(select(Lead).where(Lead.phone_normalized == "5562999112233"))
        check(lead.number_validated is True, "validação não persistiu")
        incoming = db.scalar(select(ConversationMessage).where(ConversationMessage.external_id == "verify-click-1"))
        check(incoming and incoming.direction == "in" and incoming.interaction_id.startswith("verify_phone:"), "clique recebido não apareceu na conversa")
        followups = db.scalars(select(SurveyExecution).where(SurveyExecution.lead_id == lead.id, SurveyExecution.source == "entry_flow_followup")).all()
        check(len(followups) == 1, "acompanhamento posterior não foi agendado uma única vez")

        legacy_payload = {
            "instanceId": "instance-test",
            "phone": "5562999112233",
            "messageId": "legacy-received-1",
            "type": "ReceivedCallback",
            "fromMe": False,
            "text": {"message": "Mensagem recuperada"},
        }
        db.add(WebhookEvent(
            event_key="received:legacy-received-1:ReceivedCallback",
            event_type="received",
            payload_json=json.dumps(legacy_payload),
            processed=True,
            ignored_reason="evento_tecnico_ignorado",
        ))
        db.commit()
        check(recover_received_callbacks(db) == 1, "callback descartado pela versão anterior não foi recuperado")
        recovered = db.scalar(select(ConversationMessage).where(ConversationMessage.external_id == "legacy-received-1"))
        check(recovered and recovered.content == "Mensagem recuperada", "mensagem antiga não voltou para a conversa")

Path(database_path).unlink(missing_ok=True)
print("OK - EscutaPet 3.1.2 fluxo de entrada completo.")
