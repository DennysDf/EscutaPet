from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import event, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, database_path = tempfile.mkstemp(prefix="escutapet_v332_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ.update(
    DATABASE_URL=f"sqlite:///{database_path}",
    AUTO_SEED_DEMO="1",
    REDIS_ENABLED="0",
    SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters",
)

from fastapi.testclient import TestClient

from app.database import SessionLocal, engine
from app.main import app
from app.models import Conversation, ConversationReaction, Lead, MediaAsset, SystemSetting, User
from app.services.engine import add_conversation_message


def check(value, message):
    if not value:
        raise AssertionError(message)


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False).status_code == 303, "login falhou")
    client.get("/")
    csrf = client.cookies.get("escutapet_v2_csrf")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        system = db.get(SystemSetting, 1)
        system.quiet_start_hour = system.quiet_end_hour = 0
        lead = Lead(name="Marina e Pipoca", phone="5562999999911", phone_normalized="5562999999911", consent_research=True)
        conversation = Conversation(identity_key="5562999999911", phone_normalized="5562999999911", lead=lead)
        db.add_all([lead, conversation])
        db.flush()
        messages = []
        for position in range(95):
            messages.append(add_conversation_message(
                db,
                conversation,
                direction="in" if position % 2 else "out",
                content=f"mensagem-{position} *teste* 😊",
                external_id=f"v332-{position}",
                status="received" if position % 2 else "sent",
                sender_user_id=user.id if position % 2 == 0 else None,
            ))
        db.flush()
        db.add(MediaAsset(
            conversation_message_id=messages[-1].id,
            type="document",
            mime_type="application/pdf",
            file_name="orientacoes.pdf",
            size_bytes=2048,
            download_status="saved",
        ))
        db.add_all([
            ConversationReaction(conversation_message_id=messages[-2].id, emoji="❤️", actor_type="contact"),
            ConversationReaction(conversation_message_id=messages[-2].id, emoji="👍", actor_type="contact"),
        ])
        db.commit()
        conversation_id = conversation.id

    page = client.get(f"/conversas/{conversation_id}")
    check(page.status_code == 200, "tela de conversa não abriu")
    check("mensagem-64" not in page.text and "mensagem-65" in page.text and "mensagem-94" in page.text, "carga inicial não ficou limitada às 30 mensagens recentes")
    for marker in ("data-emoji-dialog", "data-media-dialog", "data-history-loader", "data-scroll-latest", "conversations.js?v=3.6.0"):
        check(marker in page.text, f"recurso visual ausente: {marker}")

    statements = []
    def count_query(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine, "before_cursor_execute", count_query)
    try:
        latest = client.get(f"/api/conversas/{conversation_id}/mensagens?limit=40")
    finally:
        event.remove(engine, "before_cursor_execute", count_query)
    payload = latest.json()
    check(latest.status_code == 200 and len(payload["items"]) == 40 and payload["has_more"], "lote do histórico incorreto")
    check(len(statements) <= 6, f"serialização voltou a consultar por mensagem: {len(statements)} SELECTs")
    check(payload["items"][-1]["media"]["mime"] == "application/pdf", "metadados do visualizador de PDF ausentes")
    check(len(payload["items"][-2]["reactions"]) == 2, "reações não foram agrupadas no lote")
    older = client.get(f"/api/conversas/{conversation_id}/mensagens?before={payload['next_before']}&limit=40").json()
    check(len(older["items"]) == 40 and older["has_more"], "segundo lote do scroll incorreto")

    sent = client.post(
        f"/conversas/{conversation_id}/responder",
        data={"text": "*Olá* 😊"},
        headers={"X-CSRF-Token": csrf, "X-Requested-With": "fetch"},
    )
    check(sent.status_code == 200 and sent.json()["ok"] and sent.json()["status"] == "queued", "envio assíncrono não confirmou a fila")

print("OK - EscutaPet 3.3.3: lote eficiente, scroll progressivo, emojis, mídias e confirmação de envio validados.")
