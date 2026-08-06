from __future__ import annotations

import base64
import ipaddress
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from ..models import ZapiConfig
from .security import normalize_phone


@dataclass
class ZapiResult:
    ok: bool
    message: str
    external_id: str | None = None
    payload: dict[str, Any] | None = None


def _endpoint(config: ZapiConfig, action: str) -> str:
    return (
        f"https://api.z-api.io/instances/{(config.instance_id or '').strip()}"
        f"/token/{(config.token or '').strip()}/{action}"
    )


SEND_ACTIONS = {
    "send-text",
    "send-button-list",
    "send-option-list",
    "send-image",
    "send-audio",
    "send-video",
    "send-document",
    "send-location",
    "send-contact",
}


def normalize_manual_send_endpoint(value: str | None) -> tuple[str | None, str | None]:
    """Validate a manual send URL or template without making a network request."""
    raw = (value or "").strip()
    if not raw:
        return None, "Informe o endpoint manual ou selecione a geração automática."
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None, "Informe um endpoint manual válido."
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        return None, "O endpoint manual precisa ser uma URL HTTP ou HTTPS completa."
    if parsed.username or parsed.password or parsed.fragment:
        return None, "O endpoint manual não pode conter usuário, senha ou fragmento (#)."
    path_tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if "{action}" not in raw and path_tail not in SEND_ACTIONS:
        return None, "O endpoint manual deve terminar em /send-text ou usar o marcador {action}."
    return raw, None


def _manual_endpoint(config: ZapiConfig, action: str) -> str:
    template = (config.manual_send_endpoint or "").strip()
    replacements = {
        "{instance_id}": quote((config.instance_id or "").strip(), safe=""),
        "{token}": quote((config.token or "").strip(), safe=""),
        "{action}": action,
    }
    for marker, replacement in replacements.items():
        template = template.replace(marker, replacement)
    if "{action}" in (config.manual_send_endpoint or ""):
        return template
    parsed = urlsplit(template)
    parts = parsed.path.rstrip("/").split("/")
    parts[-1] = action
    return urlunsplit((parsed.scheme, parsed.netloc, "/".join(parts), parsed.query, ""))


def _send_endpoint(config: ZapiConfig, action: str) -> str:
    if config.send_endpoint_mode == "manual" and config.manual_send_endpoint:
        return _manual_endpoint(config, action)
    return _endpoint(config, action)


def send_endpoint_preview(config: ZapiConfig) -> str:
    """Return a safe preview of the Z-API send endpoint without exposing the token."""
    if config.send_endpoint_mode == "manual" and config.manual_send_endpoint:
        preview = _manual_endpoint(config, "send-text")
        if config.token:
            preview = preview.replace(config.token.strip(), "••••••••")
        return preview
    instance_id = (config.instance_id or "SUA_INSTANCIA").strip()
    token = "••••••••" if config.token else "SEU_TOKEN"
    return f"https://api.z-api.io/instances/{instance_id}/token/{token}/send-text"


def _headers(config: ZapiConfig, *, json_content: bool = True) -> dict[str, str]:
    output: dict[str, str] = {}
    if json_content:
        output["Content-Type"] = "application/json"
    if config.client_token:
        output["Client-Token"] = config.client_token.strip()
    return output


def _payload(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        value = response.json()
        return value if isinstance(value, dict) else {"items": value}
    except ValueError:
        return {"raw": response.text[:4000]}


def _external_id(payload: dict[str, Any]) -> str | None:
    for key in ("messageId", "message_id", "id", "zaapId"):
        if payload.get(key):
            return str(payload[key])
    return None


def _failure(response: httpx.Response, payload: dict[str, Any]) -> str:
    detail = payload.get("error") or payload.get("message") or payload.get("raw") or "resposta não detalhada"
    return f"Z-API respondeu HTTP {response.status_code}: {str(detail)[:500]}"


def _safe_failure_detail(config: ZapiConfig, response: httpx.Response, payload: dict[str, Any]) -> str:
    """Expose the provider's useful error while masking locally stored credentials."""
    detail = str(payload.get("error") or payload.get("message") or payload.get("raw") or "resposta não detalhada")
    for secret in (config.token, config.client_token, config.webhook_secret):
        if secret:
            detail = detail.replace(secret.strip(), "••••••••")
    return f"HTTP {response.status_code}: {detail[:500]}"


def _ready(config: ZapiConfig, *, for_send: bool = False) -> str | None:
    if not config.enabled:
        return "Integração Z-API desativada."
    if for_send and config.send_endpoint_mode == "manual":
        normalized, error = normalize_manual_send_endpoint(config.manual_send_endpoint)
        if error:
            return error
        if normalized and "{instance_id}" in normalized and not config.instance_id:
            return "O endpoint manual usa {instance_id}, mas o ID da instância não foi informado."
        if normalized and "{token}" in normalized and not config.token:
            return "O endpoint manual usa {token}, mas o token da instância não foi informado."
        return None
    if not config.instance_id or not config.token:
        return "ID e token da instância não configurados."
    return None


def _canonical_recipient(phone: str | None) -> str:
    raw = str(phone or "").strip()
    return raw if raw.casefold().endswith("@lid") else (normalize_phone(raw) or raw)


def send_text(config: ZapiConfig, phone: str, text: str, *, reply_external_id: str | None = None) -> ZapiResult:
    phone = _canonical_recipient(phone)
    error = _ready(config, for_send=True)
    if error:
        return ZapiResult(False, error)
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = client.post(
                _send_endpoint(config, "send-text"),
                headers=_headers(config),
                json={"phone": phone, "message": text, **({"messageId": reply_external_id} if reply_external_id else {})},
            )
        payload = _payload(response)
        if response.is_success and not payload.get("error"):
            return ZapiResult(True, "Mensagem aceita pela Z-API.", _external_id(payload), payload)
        return ZapiResult(False, _failure(response, payload), payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha de rede ao acessar a Z-API: {exc}")


def _send_payload(config: ZapiConfig, action: str, body: dict[str, Any], success_message: str) -> ZapiResult:
    if "phone" in body:
        body["phone"] = _canonical_recipient(body.get("phone"))
    if action == "send-contact" and body.get("contactPhone"):
        body["contactPhone"] = _canonical_recipient(body.get("contactPhone"))
    error = _ready(config, for_send=True)
    if error:
        return ZapiResult(False, error)
    try:
        with httpx.Client(timeout=httpx.Timeout(40.0, connect=10.0)) as client:
            response = client.post(_send_endpoint(config, action), headers=_headers(config), json=body)
        payload = _payload(response)
        if response.is_success and not payload.get("error"):
            return ZapiResult(True, success_message, _external_id(payload), payload)
        return ZapiResult(False, _failure(response, payload), payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha de rede ao acessar a Z-API: {exc}")


def _clean_options(items: list[dict[str, Any]], limit: int = 10) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for index, item in enumerate(items[:limit], start=1):
        label = str(item.get("label") or item.get("value") or "").strip()
        identifier = str(item.get("id") or item.get("value") or index).strip()
        if not label:
            continue
        output.append({
            "id": identifier[:80],
            "label": label[:100],
            "description": str(item.get("description") or "").strip()[:200],
        })
    return output


def _numbered_fallback(text: str, items: list[dict[str, Any]]) -> str:
    clean = _clean_options(items)
    if not clean:
        return text
    return text + "\n\n" + "\n".join(f"{index + 1}. {item['label']}" for index, item in enumerate(clean))


def send_buttons(config: ZapiConfig, phone: str, text: str, buttons: list[dict[str, Any]]) -> ZapiResult:
    phone = _canonical_recipient(phone)
    clean = _clean_options(buttons, limit=3)
    if not clean:
        return send_text(config, phone, text)
    if not config.use_buttons or not config.button_terms_accepted:
        result = send_text(config, phone, _numbered_fallback(text, clean))
        if result.ok:
            result.message = "Mensagem enviada como lista numerada porque os botões estão desativados ou sem aceite dos termos."
        return result
    error = _ready(config, for_send=True)
    if error:
        return ZapiResult(False, error)
    body = {
        "phone": phone,
        "message": text,
        "buttonList": {"buttons": [{"id": item["id"], "label": item["label"][:25]} for item in clean]},
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = client.post(_send_endpoint(config, "send-button-list"), headers=_headers(config), json=body)
        payload = _payload(response)
        if response.is_success and not payload.get("error"):
            return ZapiResult(True, "Mensagem com botões aceita pela Z-API.", _external_id(payload), payload)
        return ZapiResult(False, _failure(response, payload), payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha de rede ao acessar a Z-API: {exc}")


def send_option_list(config: ZapiConfig, phone: str, text: str, items: list[dict[str, Any]]) -> ZapiResult:
    phone = _canonical_recipient(phone)
    clean = _clean_options(items, limit=10)
    if not clean:
        return send_text(config, phone, text)
    if not config.use_buttons or not config.button_terms_accepted:
        return send_text(config, phone, _numbered_fallback(text, clean))
    error = _ready(config, for_send=True)
    if error:
        return ZapiResult(False, error)
    body = {
        "phone": phone,
        "message": text,
        "optionList": {
            "title": "Escolha uma resposta",
            "buttonLabel": "Ver opções",
            "options": [
                {"id": item["id"], "title": item["label"], "description": item["description"]}
                for item in clean
            ],
        },
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = client.post(_send_endpoint(config, "send-option-list"), headers=_headers(config), json=body)
        payload = _payload(response)
        if response.is_success and not payload.get("error"):
            return ZapiResult(True, "Lista de opções aceita pela Z-API.", _external_id(payload), payload)
        return ZapiResult(False, _failure(response, payload), payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha de rede ao acessar a Z-API: {exc}")


def send_interactive(
    config: ZapiConfig,
    phone: str,
    text: str,
    *,
    message_type: str = "text",
    options: list[dict[str, Any]] | None = None,
    media_payload: dict[str, Any] | None = None,
    reply_external_id: str | None = None,
) -> ZapiResult:
    items = options or []
    media = media_payload or {}
    if message_type == "buttons":
        return send_buttons(config, phone, text, items)
    if message_type == "option_list":
        return send_option_list(config, phone, text, items)
    if message_type == "numbered_text":
        return send_text(config, phone, _numbered_fallback(text, items), reply_external_id=reply_external_id)
    reply = {"messageId": reply_external_id} if reply_external_id else {}
    if message_type == "image":
        return _send_payload(config, "send-image", {"phone": phone, "image": media.get("url"), "caption": text, **reply}, "Imagem aceita pela Z-API.")
    if message_type == "audio":
        return _send_payload(config, "send-audio", {"phone": phone, "audio": media.get("url"), **reply}, "Áudio aceito pela Z-API.")
    if message_type == "video":
        return _send_payload(config, "send-video", {"phone": phone, "video": media.get("url"), "caption": text, **reply}, "Vídeo aceito pela Z-API.")
    if message_type == "document":
        return _send_payload(config, "send-document", {"phone": phone, "document": media.get("url"), "fileName": media.get("file_name") or "documento", "caption": text, **reply}, "Documento aceito pela Z-API.")
    if message_type == "location":
        return _send_payload(config, "send-location", {
            "phone": phone,
            "latitude": media.get("latitude"),
            "longitude": media.get("longitude"),
            "title": media.get("title") or text,
            "address": media.get("address") or "",
            **reply,
        }, "Localização aceita pela Z-API.")
    if message_type == "contact":
        return _send_payload(config, "send-contact", {
            "phone": phone,
            "contactName": media.get("name") or text,
            "contactPhone": media.get("phone"),
            **reply,
        }, "Contato aceito pela Z-API.")
    return send_text(config, phone, text, reply_external_id=reply_external_id)


def send_reaction(config: ZapiConfig, phone: str, message_id: str, emoji: str) -> ZapiResult:
    return _send_payload(config, "send-reaction", {"phone": phone, "messageId": message_id, "reaction": emoji}, "Reação aceita pela Z-API.")


def get_contacts(config: ZapiConfig, *, page: int = 1, page_size: int = 100) -> ZapiResult:
    error = _ready(config)
    if error:
        return ZapiResult(False, error)
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                _endpoint(config, "contacts"),
                headers=_headers(config, json_content=False),
                params={"page": max(1, page), "pageSize": max(1, min(500, page_size))},
            )
        payload = _payload(response)
        items = payload.get("items") if isinstance(payload, dict) else []
        if response.is_success:
            return ZapiResult(True, f"{len(items or [])} contato(s) consultado(s).", payload={"items": items or []})
        return ZapiResult(False, _failure(response, payload), payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha ao consultar contatos: {exc}")


def get_chats(config: ZapiConfig, *, page: int = 1, page_size: int = 100) -> ZapiResult:
    error = _ready(config)
    if error:
        return ZapiResult(False, error)
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                _endpoint(config, "chats"),
                headers=_headers(config, json_content=False),
                params={"page": max(1, page), "pageSize": max(1, min(500, page_size))},
            )
        payload = _payload(response)
        items = payload.get("items") if isinstance(payload, dict) else []
        if response.is_success:
            return ZapiResult(True, f"{len(items or [])} conversa(s) consultada(s).", payload={"items": items or []})
        return ZapiResult(False, _failure(response, payload), payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha ao consultar conversas: {exc}")


def get_contact_metadata(config: ZapiConfig, phone: str) -> ZapiResult:
    phone = _canonical_recipient(phone)
    """Fetch the current WhatsApp display name, picture and about text."""
    error = _ready(config)
    if error:
        return ZapiResult(False, error)
    clean_phone = "".join(char for char in str(phone) if char.isdigit())
    if not clean_phone:
        return ZapiResult(False, "Telefone inválido para consulta de metadados.")
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                _endpoint(config, f"contacts/{clean_phone}"),
                headers=_headers(config, json_content=False),
            )
        payload = _payload(response)
        if response.is_success and not payload.get("error"):
            return ZapiResult(True, "Perfil do WhatsApp sincronizado.", payload=payload)
        return ZapiResult(False, _failure(response, payload), payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha ao consultar o perfil do contato: {exc}")


def check_connection(config: ZapiConfig) -> ZapiResult:
    if not config.instance_id or not config.token:
        return ZapiResult(False, "Informe ID e token da instância.")
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(_endpoint(config, "status"), headers=_headers(config, json_content=False))
        payload = _payload(response)
        if not response.is_success:
            return ZapiResult(False, _failure(response, payload), payload=payload)
        connected = bool(payload.get("connected") or payload.get("status") == "connected")
        return ZapiResult(connected, "Instância conectada." if connected else "Instância respondeu, mas não está conectada.", payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha de rede ao consultar a instância: {exc}")


def normalize_public_base_url(value: str | None) -> tuple[str | None, str | None]:
    raw = (value or "").strip()
    if not raw:
        return None, None
    try:
        parsed = urlsplit(raw)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None, "Informe uma URL pública válida, como https://pesquisa.seudominio.com."
    if parsed.scheme not in {"http", "https"} or not hostname or not parsed.netloc:
        return None, "Informe uma URL pública válida, como https://pesquisa.seudominio.com."
    if parsed.username or parsed.password:
        return None, "A URL pública não pode conter usuário, senha ou tokens."
    if hostname == "z-api.io" or hostname.endswith(".z-api.io"):
        return None, "Use o endereço público desta aplicação, não uma URL de envio da Z-API."
    is_local = hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not is_local:
        return None, "A URL pública da aplicação precisa usar HTTPS."
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    netloc = display_host if port is None or default_port else f"{display_host}:{port}"
    return f"{parsed.scheme}://{netloc}", None


def is_public_https_origin(value: str | None) -> bool:
    """Validate whether an origin is suitable for callbacks from the public internet."""
    normalized, error = normalize_public_base_url(value)
    if error or not normalized or not normalized.startswith("https://"):
        return False
    hostname = (urlsplit(normalized).hostname or "").lower().rstrip(".")
    if hostname in {"localhost", "::1"} or hostname.endswith((".localhost", ".local", ".lan", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def webhook_urls_from_base(base_url: str, secret: str) -> dict[str, str]:
    base = base_url.rstrip("/")
    return {
        "received": f"{base}/zapi/webhook/receber/{secret}",
        "delivery": f"{base}/zapi/webhook/envio/{secret}",
        "status": f"{base}/zapi/webhook/status/{secret}",
        "connected": f"{base}/zapi/webhook/conectado/{secret}",
        "disconnected": f"{base}/zapi/webhook/desconectado/{secret}",
    }


def webhook_urls(config: ZapiConfig) -> dict[str, str]:
    base, error = normalize_public_base_url(config.public_base_url)
    if error or not base:
        return {}
    return webhook_urls_from_base(base, config.webhook_secret)


def run_diagnostics(config: ZapiConfig) -> ZapiResult:
    if not config.instance_id or not config.token or not config.client_token:
        return ZapiResult(False, "Informe ID, token da instância e Client-Token.")
    expected = webhook_urls(config)
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"checks": checks, "webhooks": {}, "device": {}}
    try:
        with httpx.Client(timeout=httpx.Timeout(18.0, connect=8.0)) as client:
            status_response = client.get(_endpoint(config, "status"), headers=_headers(config, json_content=False))
            status_payload = _payload(status_response)
            connected = status_response.is_success and bool(status_payload.get("connected") or status_payload.get("status") == "connected")
            status_detail = (
                "Conectada"
                if connected
                else ("Instância respondeu, mas o WhatsApp está desconectado." if status_response.is_success else _safe_failure_detail(config, status_response, status_payload))
            )
            checks.append({"code": "status", "label": "Conexão da instância", "ok": connected, "detail": status_detail})

            device_response = client.get(_endpoint(config, "device"), headers=_headers(config, json_content=False))
            device_payload = _payload(device_response)
            summary["device"] = {
                "phone": device_payload.get("phone"),
                "name": device_payload.get("name"),
                "isBusiness": device_payload.get("isBusiness"),
            }
            checks.append({
                "code": "device",
                "label": "Dados do aparelho",
                "ok": device_response.is_success,
                "detail": f"{device_payload.get('name') or 'WhatsApp'} · {device_payload.get('phone') or 'telefone não informado'}" if device_response.is_success else _safe_failure_detail(config, device_response, device_payload),
            })

            me_response = client.get(_endpoint(config, "me"), headers=_headers(config, json_content=False))
            me_payload = _payload(me_response)
            remote = {
                "received": me_payload.get("receivedCallbackUrl"),
                "delivery": me_payload.get("deliveryCallbackUrl"),
                "status": me_payload.get("messageStatusCallbackUrl"),
                "connected": me_payload.get("connectedCallbackUrl"),
                "disconnected": me_payload.get("disconnectedCallbackUrl"),
            }
            summary["webhooks"] = {
                name: {"url": value, "configured": bool(value), "matches": bool(expected and value == expected.get(name))}
                for name, value in remote.items()
            }
            webhook_ok = bool(me_response.is_success and expected and all(value == expected.get(name) for name, value in remote.items()))
            webhook_detail = (
                "Todos conferem."
                if webhook_ok
                else ("Há URLs ausentes ou divergentes." if me_response.is_success else _safe_failure_detail(config, me_response, me_payload))
            )
            checks.append({"code": "webhooks", "label": "Cinco webhooks remotos", "ok": webhook_ok, "detail": webhook_detail})
            notify_ok = bool(me_response.is_success and bool(me_payload.get("receiveCallbackSentByMe")) == bool(config.notify_sent_by_me))
            checks.append({"code": "sent_by_me", "label": "Mensagens enviadas por mim", "ok": notify_ok, "detail": "Configuração conferida." if notify_ok else "Configuração remota diferente."})
            auto_read_ok = bool(me_response.is_success and bool(me_payload.get("autoReadMessage")) == bool(config.auto_read_message))
            checks.append({"code": "auto_read", "label": "Leitura automática", "ok": auto_read_ok, "detail": "Configuração conferida." if auto_read_ok else "Configuração remota diferente."})
    except httpx.HTTPError as exc:
        checks.append({"code": "network", "label": "Acesso à Z-API", "ok": False, "detail": str(exc)[:300]})
    all_ok = bool(checks and all(item["ok"] for item in checks))
    summary["ok"] = all_ok
    summary["connected"] = any(item["code"] == "status" and item["ok"] for item in checks)
    if all_ok:
        message = "Diagnóstico concluído sem divergências."
    else:
        first_failure = next((item for item in checks if not item["ok"]), None)
        message = (
            f"{first_failure['label']}: {first_failure['detail']}"
            if first_failure
            else "Diagnóstico concluído com itens que exigem atenção."
        )
    return ZapiResult(all_ok, message, payload=summary)


def configure_remote_webhooks(config: ZapiConfig) -> ZapiResult:
    if not config.instance_id or not config.token or not config.client_token:
        return ZapiResult(False, "Informe ID, token e Client-Token para configurar webhooks.")
    base, error = normalize_public_base_url(config.public_base_url)
    if error:
        return ZapiResult(False, error)
    if not is_public_https_origin(base):
        return ZapiResult(False, "A URL dos webhooks precisa ser um endereço HTTPS público acessível pela Z-API.")
    config.public_base_url = base
    urls = webhook_urls_from_base(base, config.webhook_secret)
    try:
        with httpx.Client(timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=True) as client:
            public_check = client.get(urls["received"], headers={"Accept": "application/json"})
        if not public_check.is_success:
            return ZapiResult(
                False,
                (
                    f"O webhook público respondeu HTTP {public_check.status_code}. "
                    "Verifique se o túnel Cloudflare aponta para http://127.0.0.1:8040 e tente novamente."
                ),
                payload={"public_check_status": public_check.status_code},
            )
    except httpx.HTTPError as exc:
        return ZapiResult(
            False,
            f"O webhook público não está acessível: {str(exc)[:300]}. Verifique o túnel Cloudflare.",
            payload={"public_check_error": str(exc)[:500]},
        )
    calls = [
        ("update-webhook-received", {"value": urls["received"]}),
        ("update-webhook-delivery", {"value": urls["delivery"]}),
        ("update-webhook-message-status", {"value": urls["status"]}),
        ("update-notify-sent-by-me", {"notifySentByMe": bool(config.notify_sent_by_me)}),
        ("update-auto-read-message", {"value": bool(config.auto_read_message)}),
        ("update-webhook-connected", {"value": urls["connected"]}),
        ("update-webhook-disconnected", {"value": urls["disconnected"]}),
    ]
    results: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=20.0) as client:
            for action, body in calls:
                response = client.put(_endpoint(config, action), headers=_headers(config), json=body)
                payload = _payload(response)
                results.append({"action": action, "status": response.status_code, "ok": response.is_success, "response": payload})
                if not response.is_success:
                    detail = _safe_failure_detail(config, response, payload)
                    return ZapiResult(False, f"Falha ao configurar {action}: {detail}", payload={"results": results})
            verification = client.get(_endpoint(config, "me"), headers=_headers(config, json_content=False))
            verification_payload = _payload(verification)
            remote = {
                "received": verification_payload.get("receivedCallbackUrl"),
                "delivery": verification_payload.get("deliveryCallbackUrl"),
                "status": verification_payload.get("messageStatusCallbackUrl"),
                "connected": verification_payload.get("connectedCallbackUrl"),
                "disconnected": verification_payload.get("disconnectedCallbackUrl"),
            }
            verified = bool(
                verification.is_success
                and all(remote.get(name) == value for name, value in urls.items())
                and bool(verification_payload.get("receiveCallbackSentByMe")) == bool(config.notify_sent_by_me)
                and bool(verification_payload.get("autoReadMessage")) == bool(config.auto_read_message)
            )
            results.append({"action": "verify-instance-data", "status": verification.status_code, "ok": verified})
            if not verified:
                return ZapiResult(False, "A Z-API aceitou as alterações, mas a conferência final encontrou divergências.", payload={"results": results, "verified": False})
        return ZapiResult(True, "Os cinco webhooks foram configurados e conferidos na Z-API.", payload={"results": results, "verified": True, "urls": urls})
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha de rede ao configurar webhooks: {exc}", payload={"results": results})


def _find_base64_image(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip().strip('"')
        if stripped.startswith("data:image/"):
            return stripped
        compact = "".join(stripped.split())
        if len(compact) > 500 and all(char.isalnum() or char in "+/=_-" for char in compact[:500]):
            return f"data:image/png;base64,{compact}"
        return None
    if isinstance(value, dict):
        for key in ("value", "image", "qrcode", "qrCode", "base64", "data"):
            if key in value:
                found = _find_base64_image(value[key])
                if found:
                    return found
        for nested in value.values():
            found = _find_base64_image(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _find_base64_image(nested)
            if found:
                return found
    return None


def get_qr_code_image(config: ZapiConfig) -> ZapiResult:
    if not config.instance_id or not config.token or not config.client_token:
        return ZapiResult(False, "Informe ID, token da instância e Client-Token antes de gerar o QR Code.")
    status = check_connection(config)
    if status.ok:
        return ZapiResult(True, "A instância já está conectada.", payload={"connected": True})
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            response = client.get(_endpoint(config, "qr-code/image"), headers=_headers(config, json_content=False))
        content_type = response.headers.get("content-type", "")
        if response.is_success and content_type.startswith("image/"):
            encoded = base64.b64encode(response.content).decode("ascii")
            return ZapiResult(True, "QR Code gerado.", payload={"connected": False, "image": f"data:{content_type.split(';')[0]};base64,{encoded}"})
        payload = _payload(response)
        if not response.is_success:
            return ZapiResult(False, _failure(response, payload), payload=payload)
        if payload.get("challenge"):
            return ZapiResult(False, "Este aparelho exige autenticação Passkey. Conclua o desafio no painel da Z-API.", payload={"challenge_required": True})
        image = _find_base64_image(payload)
        if image:
            return ZapiResult(True, "QR Code gerado.", payload={"connected": False, "image": image})
        return ZapiResult(False, "A Z-API respondeu sem uma imagem de QR Code reconhecível.", payload=payload)
    except httpx.HTTPError as exc:
        return ZapiResult(False, f"Falha de rede ao gerar QR Code: {exc}")


def compact_payload(payload: Any, limit: int = 25000) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)[:limit]


def payload_value(payload: Any, *keys: str, default=None):
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    for nested_key in ("data", "message", "event", "payload"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            value = payload_value(nested, *keys, default=None)
            if value not in (None, ""):
                return value
    return default


def received_contact(payload: dict[str, Any]) -> dict[str, str]:
    raw = str(payload.get("phone") or payload.get("from") or payload.get("senderPhone") or "").strip()
    lid = str(payload.get("chatLid") or payload.get("senderLid") or "").strip()
    if raw.casefold().endswith("@lid"):
        lid = lid or raw
        phone = ""
    else:
        phone = normalize_phone(raw) or ""
    return {
        "phone": phone,
        "lid": lid if lid.casefold().endswith("@lid") else "",
        "key": lid or phone,
        "sender_name": str(payload.get("senderName") or "").strip(),
        "chat_name": str(payload.get("chatName") or "").strip(),
        "sender_photo": str(payload.get("senderPhoto") or payload.get("photo") or "").strip(),
    }


def received_content(payload: dict[str, Any]) -> dict[str, Any]:
    text = ""
    interaction_id = None
    interaction_type = None
    button = payload_value(payload, "buttonsResponseMessage", default={})
    if isinstance(button, dict) and button:
        interaction_type = "button"
        interaction_id = str(button.get("buttonId") or button.get("selectedButtonId") or "")
        text = str(button.get("message") or button.get("selectedDisplayText") or interaction_id)
    listing = payload_value(payload, "listResponseMessage", default={})
    if isinstance(listing, dict) and listing:
        interaction_type = "list"
        interaction_id = str(listing.get("selectedRowId") or "")
        text = str(listing.get("title") or listing.get("message") or interaction_id)
    raw_text = payload_value(payload, "text", default="")
    if not text and isinstance(raw_text, dict):
        text = str(raw_text.get("message") or raw_text.get("text") or raw_text.get("body") or "")
    elif not text and isinstance(raw_text, str):
        text = raw_text
    if not text:
        raw_message = payload.get("message")
        if isinstance(raw_message, dict):
            text = str(raw_message.get("message") or raw_message.get("text") or raw_message.get("body") or "")
        elif isinstance(raw_message, str):
            text = raw_message
    media: dict[str, Any] = {}
    content_type = interaction_type or "text"
    media_specs = (
        ("image", "imageUrl", "image"),
        ("audio", "audioUrl", "audio"),
        ("video", "videoUrl", "video"),
        ("document", "documentUrl", "document"),
        ("sticker", "stickerUrl", "sticker"),
    )
    for key, url_key, kind in media_specs:
        value = payload_value(payload, key, default={})
        if not isinstance(value, dict) or not value:
            continue
        content_type = kind
        media = {
            "source_url": value.get(url_key) or value.get("url"),
            "mime_type": value.get("mimeType"),
            "file_name": value.get("fileName") or value.get("title"),
            "caption": value.get("caption") or "",
            "duration_seconds": value.get("seconds"),
            "metadata": value,
        }
        text = text or str(media.get("caption") or f"[{kind}]")
        break
    location = payload_value(payload, "location", default={})
    if isinstance(location, dict) and location:
        content_type = "location"
        media = {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "address": location.get("address") or location.get("name") or "",
            "source_url": location.get("url"),
            "metadata": location,
        }
        text = text or str(media["address"] or "[localização]")
    contact = payload_value(payload, "contact", default={})
    if isinstance(contact, dict) and contact:
        content_type = "contact"
        media = {
            "file_name": contact.get("displayName"),
            "caption": contact.get("vCard"),
            "metadata": contact,
        }
        text = text or str(contact.get("displayName") or "[contato]")
    for ignored_key, kind in (("reaction", "reaction"), ("poll", "poll"), ("pollVote", "poll")):
        value = payload_value(payload, ignored_key, default={})
        if isinstance(value, dict) and value:
            content_type = kind
            media = {"metadata": value}
            break
    return {
        "text": text.strip(),
        "interaction_id": interaction_id,
        "interaction_type": interaction_type,
        "content_type": content_type,
        "reference_message_id": str(payload_value(payload, "referenceMessageId", "quotedMsgId", default="") or "") or None,
        "media": media,
    }
