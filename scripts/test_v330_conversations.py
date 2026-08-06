from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, path = tempfile.mkstemp(prefix="escutapet_v330_", suffix=".sqlite3")
os.close(handle); os.unlink(path)
os.environ.update(DATABASE_URL=f"sqlite:///{path}", AUTO_SEED_DEMO="1", REDIS_ENABLED="0", SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Conversation, ConversationDraft, ConversationMessage, Lead, MessageQueue, SystemSetting, User
from app.services.engine import add_conversation_message
from app.services.worker import process_once


def check(value, message):
    if not value: raise AssertionError(message)


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False).status_code == 303, "login falhou")
    client.get("/")
    csrf = client.cookies.get("escutapet_v2_csrf")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "admin")); user.chat_signature_enabled = True; user.chat_signature = "*Equipe EscutaPet*"
        system = db.get(SystemSetting, 1); system.quiet_start_hour = 0; system.quiet_end_hour = 0
        lead = Lead(name="Contato longo", phone="5562999999999", phone_normalized="5562999999999", consent_research=True)
        conversation = Conversation(identity_key="5562999999999", phone_normalized="5562999999999", lead=lead)
        db.add_all([lead, conversation]); db.flush()
        for position in range(75):
            add_conversation_message(db, conversation, direction="in" if position % 2 else "out", content=f"mensagem-{position}", external_id=f"m-{position}", status="received" if position % 2 else "sent")
        db.commit(); conversation_id = conversation.id

    page = client.get(f"/conversas/{conversation_id}")
    check(page.status_code == 200 and "data-chat-history" in page.text and "conversations.js?v=3.6.0" in page.text, "tela profissional não renderizou")
    check("mensagem-0" not in page.text and "mensagem-74" in page.text, "a página carregou o histórico completo em vez das últimas mensagens")
    latest = client.get(f"/api/conversas/{conversation_id}/mensagens?limit=50").json()
    check(len(latest["items"]) == 50 and latest["has_more"], "paginação inicial não retornou cursor")
    older = client.get(f"/api/conversas/{conversation_id}/mensagens?before={latest['next_before']}&limit=50").json()
    check(len(older["items"]) == 25 and not older["has_more"], "carregamento de mensagens anteriores incorreto")
    draft = client.put(f"/api/conversas/{conversation_id}/rascunho", json={"content": "rascunho seguro", "reply_to_message_id": latest["items"][-1]["id"]}, headers={"X-CSRF-Token": csrf})
    check(draft.status_code == 200, "rascunho recusado")
    check(client.get(f"/api/conversas/{conversation_id}/rascunho").json()["content"] == "rascunho seguro", "rascunho não persistiu")
    sent = client.post(f"/conversas/{conversation_id}/responder", data={"text": "Olá, tudo bem?", "use_signature": "on", "reply_to_message_id": latest["items"][-1]["id"]}, headers={"X-CSRF-Token": csrf}, follow_redirects=False)
    check(sent.status_code == 303, "envio humano não entrou na fila")
    with SessionLocal() as db:
        queued = db.scalar(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.id.desc()))
        check(queued.status == "queued" and "*Equipe EscutaPet*" in queued.content and queued.reply_to_message_id, "assinatura, status pendente ou resposta vinculada ausentes")
    process_once()
    with SessionLocal() as db:
        queued = db.scalar(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.id.desc()))
        check(queued.status == "simulated" and queued.external_id, "worker não atualizou a bolha humana enviada")

print("OK - EscutaPet 3.3.3: paginação, rascunho, assinatura, resposta vinculada e fila da conversa validados.")
