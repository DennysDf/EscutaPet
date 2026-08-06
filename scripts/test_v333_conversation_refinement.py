from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, database_path = tempfile.mkstemp(prefix="escutapet_v333_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ.update(DATABASE_URL=f"sqlite:///{database_path}", AUTO_SEED_DEMO="1", REDIS_ENABLED="0", SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters")

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import City, Conversation, Lead, MediaAsset, User
from app.services.engine import add_conversation_message
from app.services.security import hash_password


def check(value, message):
    if not value:
        raise AssertionError(message)


with TestClient(app) as client:
    with SessionLocal() as db:
        city_a = City(name="Cidade permitida", state="GO")
        city_b = City(name="Cidade restrita", state="SP")
        db.add_all([city_a, city_b]); db.flush()
        operator = User(name="Operador local", username="local", password_hash=hash_password("local123"), role="operator", all_cities=False, city_ids_json=json.dumps([city_a.id]))
        lead_a = Lead(name="Lead permitido", phone="5562999999801", phone_normalized="5562999999801", city_id=city_a.id)
        lead_b = Lead(name="Lead proibido", phone="5562999999802", phone_normalized="5562999999802", city_id=city_b.id)
        conversation_a = Conversation(identity_key="v333-a", phone_normalized=lead_a.phone_normalized, lead=lead_a, unread_count=2)
        conversation_b = Conversation(identity_key="v333-b", phone_normalized=lead_b.phone_normalized, lead=lead_b, unread_count=4)
        db.add_all([operator, lead_a, lead_b, conversation_a, conversation_b]); db.flush()
        message_a = add_conversation_message(db, conversation_a, direction="in", content="mensagem autorizada", external_id="v333-message-a")
        message_b = add_conversation_message(db, conversation_b, direction="in", content="mensagem sigilosa", external_id="v333-message-b")
        media_b = MediaAsset(conversation_message_id=message_b.id, type="image", mime_type="image/png", file_name="restrita.png", download_status="pending")
        db.add(media_b); db.commit()
        allowed_id, denied_id, denied_media_id = conversation_a.id, conversation_b.id, media_b.id

    check(client.post("/login", data={"username":"local", "password":"local123"}, follow_redirects=False).status_code == 303, "login local falhou")
    csrf = client.cookies.get("escutapet_v2_csrf")
    listing = client.get("/api/conversas").json()
    check([item["id"] for item in listing["items"]] == [allowed_id], "listagem expôs conversa fora das cidades permitidas")
    check(client.get(f"/conversas/{denied_id}").status_code == 404, "acesso direto expôs conversa restrita")
    check(client.get(f"/api/conversas/{denied_id}/mensagens").status_code == 404, "API expôs mensagens restritas")
    check(client.get(f"/midias/{denied_media_id}").status_code == 404, "mídia restrita ficou acessível")

    page = client.get(f"/conversas/{allowed_id}")
    for marker in ("conversations.css?v=3.6.0", "message-circle", "data-conversation-action", "data-conversation-assignee", "data-recording-preview"):
        check(marker in page.text, f"refinamento visual ausente: {marker}")
    action = client.post(f"/conversas/{allowed_id}/acao", data={"action":"pin"}, headers={"X-CSRF-Token":csrf, "X-Requested-With":"fetch"})
    check(action.status_code == 200 and action.json()["pinned"], "ação de fixar falhou")
    close = client.post(f"/conversas/{allowed_id}/acao", data={"action":"close"}, headers={"X-CSRF-Token":csrf, "X-Requested-With":"fetch"})
    check(close.json()["status"] == "closed" and close.json()["status_label"] == "Encerrada", "estado amigável não foi atualizado")
    check(client.put(f"/api/conversas/{allowed_id}/rascunho", json={"content":"rascunho"}, headers={"X-CSRF-Token":csrf}).status_code == 200, "rascunho não foi salvo")
    check(client.delete(f"/api/conversas/{allowed_id}/rascunho", headers={"X-CSRF-Token":csrf}).json()["ok"], "rascunho não foi removido após envio")
    check(client.get(f"/api/conversas/{allowed_id}/rascunho").json()["content"] == "", "rascunho reapareceu")

print("OK - EscutaPet 3.3.3: escopo por cidade, mídias, ações, estados e rascunho validados.")
