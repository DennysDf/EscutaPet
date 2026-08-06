from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_zapi_test_", suffix=".sqlite3")
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
from app.models import (
    ConversationMessage,
    Lead,
    MessageQueue,
    Question,
    Questionnaire,
    SurveyAnswer,
    WebhookEvent,
    ZapiConfig,
)
from app.services.engine import create_execution, start_whatsapp_execution
from app.services.zapi import (
    configure_remote_webhooks,
    get_contact_metadata,
    get_qr_code_image,
    run_diagnostics,
    send_interactive,
    webhook_urls,
    webhook_urls_from_base,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeClient:
    calls: list[tuple[str, str, dict | None]] = []
    connected_status = True
    expected_me: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @classmethod
    def reset(cls) -> None:
        cls.calls.clear()

    def get(self, url: str, *, headers=None):
        self.calls.append(("GET", url, None))
        if "/zapi/webhook/receber/" in url:
            return httpx.Response(200, json={"ok": True, "endpoint": "received"})
        if url.endswith("/status"):
            return httpx.Response(200, json={"connected": self.connected_status})
        if url.endswith("/device"):
            return httpx.Response(200, json={"phone": "5562999990000", "name": "Aparelho de teste", "isBusiness": True})
        if url.endswith("/me"):
            return httpx.Response(200, json=self.expected_me)
        if url.endswith("/qr-code/image"):
            return httpx.Response(200, json={"value": "data:image/png;base64,ZmFrZS1xci1jb2Rl"})
        if "/contacts/" in url:
            return httpx.Response(
                200,
                json={
                    "name": "Contato",
                    "phone": "5562999988776",
                    "notify": "Contato WA",
                    "short": "Contato",
                    "imgUrl": "https://example.com/avatar.jpg",
                    "about": "Teste",
                },
            )
        return httpx.Response(404, json={"error": "not mocked"})

    def put(self, url: str, *, headers=None, json=None):
        self.calls.append(("PUT", url, json))
        return httpx.Response(200, json={"ok": True})

    def post(self, url: str, *, headers=None, json=None):
        self.calls.append(("POST", url, json))
        action = url.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"messageId": f"mock-{action}"})


with TestClient(app) as client:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123", "next": "/"},
        follow_redirects=False,
    )
    check(response.status_code == 303, "login falhou")
    check(client.get("/configuracoes").status_code == 200, "configuração Z-API não abriu")

    questions = [
        {
            "text": "Qual animal você possui?",
            "type": "choice",
            "required": True,
            "options": [
                {"id": "dog", "label": "Cachorro", "value": "cachorro"},
                {"id": "cat", "label": "Gato", "value": "gato"},
                {"id": "other", "label": "Outro", "value": "outro"},
            ],
            "whatsapp_response_mode": "buttons",
        },
        {
            "text": "Qual assunto interessa?",
            "type": "choice",
            "required": True,
            "options": [
                {"id": "a", "label": "Vacinação", "value": "vacinação"},
                {"id": "b", "label": "Castração", "value": "castração"},
                {"id": "c", "label": "Adoção", "value": "adoção"},
                {"id": "d", "label": "Cuidados", "value": "cuidados"},
            ],
            "whatsapp_response_mode": "option_list",
        },
    ]
    response = client.post(
        "/questionarios/novo",
        data={
            "name": "Interativo Z-API",
            "description": "Teste de botões e lista",
            "objective": "profile",
            "status": "active",
            "channels": "whatsapp",
            "response_mode": "identified",
            "trigger_type": "manual",
            "audience_type": "all",
            "random_percent": "100",
            "opening_message": "Olá",
            "closing_message": "Obrigado",
            "send_hour": "10",
            "max_attempts": "2",
            "retry_hours": "24",
            "auto_segment": "on",
            "stop_after_response": "on",
            "questions_json": json.dumps(questions, ensure_ascii=False),
        },
        follow_redirects=False,
    )
    check(response.status_code == 303, "questionário interativo não foi criado")
    questionnaire_id = int(response.headers["location"].split("/")[2])

    with SessionLocal() as db:
        questionnaire = db.scalar(
            select(Questionnaire)
            .options(selectinload(Questionnaire.questions))
            .where(Questionnaire.id == questionnaire_id)
        )
        check([q.whatsapp_response_mode for q in questionnaire.questions] == ["buttons", "option_list"], "modo Z-API por pergunta não persistiu")
        lead = Lead(
            name="Contato Interativo",
            phone="5562999988776",
            phone_normalized="5562999988776",
            source="test",
            consent_research=True,
        )
        db.add(lead)
        db.flush()
        execution = create_execution(db, questionnaire, lead=lead, channel="whatsapp", source="test")
        start_whatsapp_execution(db, execution)
        db.commit()
        execution_id = execution.id
        first_question_id = questionnaire.questions[0].id
        queue = db.scalar(
            select(MessageQueue)
            .where(MessageQueue.execution_id == execution_id, MessageQueue.question_id == first_question_id)
        )
        check(queue is not None and queue.message_type == "buttons", "primeira pergunta não entrou na fila como botões")

        config = db.get(ZapiConfig, 1)
        config.enabled = True
        config.instance_id = "instance-test"
        config.token = "token-test"
        config.client_token = "client-test"
        config.public_base_url = "https://survey.example.com/app/path"
        config.use_buttons = True
        config.button_terms_accepted = True
        config.notify_sent_by_me = True
        config.auto_read_message = True
        db.commit()
        secret = config.webhook_secret

    # Resposta clicada em botão: deve resolver pelo buttonId e enfileirar a próxima pergunta como lista.
    clicked = {
        "instanceId": "instance-test",
        "phone": "5562999988776",
        "messageId": "incoming-button-1",
        "type": "ReceivedCallback",
        "buttonsResponseMessage": {"buttonId": "dog", "message": "Cachorro"},
    }
    response = client.post(f"/zapi/webhook/receber/{secret}", json=clicked)
    check(response.status_code == 200 and response.json().get("action") == "answer_recorded", "clique em botão não foi processado")
    duplicate = client.post(f"/zapi/webhook/receber/{secret}", json=clicked)
    check(duplicate.json().get("duplicate") is True, "webhook recebido duplicado não foi detectado")

    with SessionLocal() as db:
        questionnaire = db.scalar(
            select(Questionnaire)
            .options(selectinload(Questionnaire.questions))
            .where(Questionnaire.id == questionnaire_id)
        )
        second = questionnaire.questions[1]
        queue = db.scalar(
            select(MessageQueue)
            .where(MessageQueue.execution_id == execution_id, MessageQueue.question_id == second.id)
        )
        check(queue is not None and queue.message_type == "option_list", "segunda pergunta não entrou como lista de opções")
        check(db.scalar(select(func.count(SurveyAnswer.id)).where(SurveyAnswer.execution_id == execution_id)) == 1, "resposta de botão não foi salva")
        queue.external_id = "outgoing-status-1"
        queue.status = "sent"
        db.commit()

    delivery_payload = {"instanceId": "instance-test", "messageId": "outgoing-status-1", "status": "RECEIVED"}
    response = client.post(f"/zapi/webhook/envio/{secret}", json=delivery_payload)
    check(response.json().get("state") == "delivered", "webhook de entrega não atualizou o estado")
    duplicate = client.post(f"/zapi/webhook/envio/{secret}", json=delivery_payload)
    check(duplicate.json().get("duplicate") is True, "entrega duplicada não foi detectada")
    response = client.post(
        f"/zapi/webhook/status/{secret}",
        json={"instanceId": "instance-test", "messageId": "outgoing-status-1", "status": "READ"},
    )
    check(response.json().get("state") == "read", "webhook de leitura não atualizou o estado")

    # GET/HEAD dos callbacks servem somente para saúde e não podem alterar a conexão.
    with SessionLocal() as db:
        config = db.get(ZapiConfig, 1)
        config.connected = False
        db.commit()
    check(client.get(f"/zapi/webhook/conectado/{secret}").json().get("endpoint") == "connected", "health do webhook conectado falhou")
    with SessionLocal() as db:
        check(db.get(ZapiConfig, 1).connected is False, "GET do webhook conectado alterou o estado")
    response = client.post(f"/zapi/webhook/conectado/{secret}", json={"instanceId": "instance-test", "phone": "5562999990000", "event": "connected-1"})
    check(response.json().get("connected") is True, "callback de conexão falhou")
    check(client.get(f"/zapi/webhook/desconectado/{secret}").json().get("endpoint") == "disconnected", "health do webhook desconectado falhou")
    with SessionLocal() as db:
        check(db.get(ZapiConfig, 1).connected is True, "GET do webhook desconectado alterou o estado")
    response = client.post(f"/zapi/webhook/desconectado/{secret}", json={"instanceId": "instance-test", "error": "logout", "event": "disconnected-1"})
    check(response.json().get("connected") is False, "callback de desconexão falhou")

    # Espelhamento de mensagens próprias não duplica uma mensagem já registrada pelo worker.
    with SessionLocal() as db:
        from app.services.engine import add_conversation_message, ensure_conversation
        lead = db.scalar(select(Lead).where(Lead.phone_normalized == "5562999988776"))
        conversation = ensure_conversation(db, lead.phone_normalized, lead)
        add_conversation_message(db, conversation, direction="out", content="Mensagem já enviada", external_id="mirror-1")
        db.commit()
    response = client.post(
        f"/zapi/webhook/receber/{secret}",
        json={"instanceId": "instance-test", "phone": "5562999988776", "messageId": "mirror-1", "fromMe": True, "text": {"message": "Mensagem já enviada"}},
    )
    check(response.json().get("action") == "outgoing_mirrored", "mensagem própria não foi reconhecida")
    with SessionLocal() as db:
        check(db.scalar(select(func.count(ConversationMessage.id)).where(ConversationMessage.external_id == "mirror-1")) == 1, "mensagem própria foi duplicada")
        event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_type == "delivery", WebhookEvent.event_key.contains("outgoing-status-1")))
        check(event is not None and event.duplicate_count == 1, "contador de duplicidade não foi atualizado")

    # Cliente HTTP simulado valida a configuração remota, QR e corpos interativos sem credenciais reais.
    with SessionLocal() as db:
        config = db.get(ZapiConfig, 1)
        config.public_base_url = "https://api.z-api.io/instances/wrong/token/secret/send-text"
        secret = config.webhook_secret
        db.commit()

    detected_origin = "https://escuta.exemplo.com"
    detected_urls = webhook_urls_from_base(detected_origin, secret)
    FakeClient.expected_me = {
        "receivedCallbackUrl": detected_urls["received"],
        "deliveryCallbackUrl": detected_urls["delivery"],
        "messageStatusCallbackUrl": detected_urls["status"],
        "connectedCallbackUrl": detected_urls["connected"],
        "disconnectedCallbackUrl": detected_urls["disconnected"],
        "receiveCallbackSentByMe": True,
        "autoReadMessage": True,
    }
    FakeClient.reset()
    with patch("app.services.zapi.httpx.Client", FakeClient):
        response = client.post(
            "/configuracoes/zapi/webhook",
            headers={"x-forwarded-proto": "https", "x-forwarded-host": "escuta.exemplo.com"},
            follow_redirects=False,
        )
    check(response.status_code == 303, "rota de configuração automática não redirecionou")
    with SessionLocal() as db:
        config = db.get(ZapiConfig, 1)
        check(config.public_base_url == detected_origin, "domínio público atual não reparou a URL de envio colada por engano")
        check(config.remote_webhooks_ok is True, "webhooks automáticos não foram conferidos")

    page = client.get(
        "/configuracoes",
        headers={"forwarded": 'for=192.0.2.10;proto=https;host="escuta.exemplo.com"'},
    )
    check(page.status_code == 200 and detected_origin in page.text, "domínio público não foi exibido na configuração")
    check("send-text" in page.text and "Endpoint de envio da Z-API" in page.text, "endpoint de envio não foi diferenciado dos webhooks")
    check('value="manual"' in page.text and "{action}" in page.text, "opção de endpoint manual não foi exibida")

    invalid = client.post(
        "/configuracoes/zapi",
        data={"send_endpoint_mode": "manual", "manual_send_endpoint": "endereco-invalido"},
        follow_redirects=False,
    )
    check(invalid.status_code == 303, "endpoint manual inválido não redirecionou")
    with SessionLocal() as db:
        check(db.get(ZapiConfig, 1).send_endpoint_mode == "automatic", "endpoint manual inválido foi salvo")

    manual_template = "https://gateway.example.com/zapi/{instance_id}/{token}/{action}"
    saved = client.post(
        "/configuracoes/zapi",
        data={
            "enabled": "on",
            "send_endpoint_mode": "manual",
            "manual_send_endpoint": manual_template,
            "instance_id": "instance-test",
            "public_base_url": detected_origin,
            "use_buttons": "on",
            "button_terms_accepted": "on",
            "notify_sent_by_me": "on",
            "auto_read_message": "on",
            "download_received_media": "on",
            "max_media_mb": "50",
            "media_retention_days": "365",
        },
        follow_redirects=False,
    )
    check(saved.status_code == 303, "endpoint manual válido não foi salvo")
    with SessionLocal() as db:
        saved_config = db.get(ZapiConfig, 1)
        check(saved_config.send_endpoint_mode == "manual", "modo manual não persistiu")
        check(saved_config.manual_send_endpoint == manual_template, "modelo manual não persistiu")

    with SessionLocal() as db:
        config = db.get(ZapiConfig, 1)
        expected = webhook_urls(config)
        FakeClient.expected_me = {
            "receivedCallbackUrl": expected["received"],
            "deliveryCallbackUrl": expected["delivery"],
            "messageStatusCallbackUrl": expected["status"],
            "connectedCallbackUrl": expected["connected"],
            "disconnectedCallbackUrl": expected["disconnected"],
            "receiveCallbackSentByMe": True,
            "autoReadMessage": True,
        }
        FakeClient.connected_status = True
        FakeClient.reset()
        with patch("app.services.zapi.httpx.Client", FakeClient):
            result = configure_remote_webhooks(config)
            check(result.ok and result.payload.get("verified"), "configuração remota dos webhooks não foi validada")
            put_actions = [url.rsplit("/", 1)[-1] for method, url, body in FakeClient.calls if method == "PUT"]
            check(put_actions == [
                "update-webhook-received",
                "update-webhook-delivery",
                "update-webhook-message-status",
                "update-notify-sent-by-me",
                "update-auto-read-message",
                "update-webhook-connected",
                "update-webhook-disconnected",
            ], "sequência de configuração remota incompleta")
            diagnostics = run_diagnostics(config)
            check(diagnostics.ok, "diagnóstico remoto simulado apresentou divergência")
            buttons_result = send_interactive(
                config,
                "5562999988776",
                "Escolha",
                message_type="buttons",
                options=[{"id": "yes", "label": "Sim"}, {"id": "no", "label": "Não"}],
            )
            check(buttons_result.ok, "envio simulado por botões falhou")
            option_result = send_interactive(
                config,
                "5562999988776",
                "Escolha uma opção",
                message_type="option_list",
                options=[{"id": str(i), "label": f"Opção {i}"} for i in range(1, 5)],
            )
            check(option_result.ok, "envio simulado por lista falhou")
            for media_type, payload in [
                ("image", {"url": "https://files.example.com/pet.jpg"}),
                ("audio", {"url": "https://files.example.com/audio.ogg"}),
                ("video", {"url": "https://files.example.com/video.mp4"}),
                ("document", {"url": "https://files.example.com/guia.pdf", "file_name": "guia.pdf"}),
                ("location", {"latitude": -16.7, "longitude": -49.2, "address": "Unidade Centro"}),
                ("contact", {"name": "Clínica", "phone": "556299990000"}),
            ]:
                check(
                    send_interactive(
                        config,
                        "5562999988776",
                        "Conteúdo de teste",
                        message_type=media_type,
                        media_payload=payload,
                    ).ok,
                    f"envio simulado de {media_type} falhou",
                )
            check(get_contact_metadata(config, "5562999988776").ok, "consulta simulada de metadados falhou")
        post_calls = [(url.rsplit("/", 1)[-1], body) for method, url, body in FakeClient.calls if method == "POST"]
        send_urls = [url for method, url, _body in FakeClient.calls if method == "POST"]
        check(
            send_urls and all(url.startswith("https://gateway.example.com/zapi/instance-test/token-test/") for url in send_urls),
            "os envios não respeitaram o endpoint manual",
        )
        get_urls = [url for method, url, _body in FakeClient.calls if method == "GET"]
        check(
            any(url.startswith("https://api.z-api.io/instances/instance-test/token/token-test/") for url in get_urls),
            "diagnósticos deixaram de usar o endpoint oficial",
        )
        check(any(action == "send-button-list" and len(body["buttonList"]["buttons"]) == 2 for action, body in post_calls), "payload de botões incorreto")
        check(any(action == "send-option-list" and len(body["optionList"]["options"]) == 4 for action, body in post_calls), "payload da lista incorreto")
        for action in ("send-image", "send-audio", "send-video", "send-document", "send-location", "send-contact"):
            check(any(item_action == action for item_action, _body in post_calls), f"endpoint {action} não foi chamado")

        FakeClient.connected_status = False
        FakeClient.reset()
        with patch("app.services.zapi.httpx.Client", FakeClient):
            qr = get_qr_code_image(config)
        check(qr.ok and str(qr.payload.get("image", "")).startswith("data:image/"), "QR Code Base64 não foi interpretado")

Path(database_path).unlink(missing_ok=True)
print("OK - integração Z-API, QR Code, webhooks e respostas interativas validadas.")
