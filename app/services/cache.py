from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

from ..config import settings

_client = None
_client_lock = threading.Lock()
_last_error: str | None = None
_last_attempt = 0.0


def _redis_client():
    global _client, _last_error, _last_attempt
    if not settings.redis_enabled:
        return None
    if _client is not None:
        return _client
    if time.monotonic() - _last_attempt < 10:
        return None
    with _client_lock:
        if _client is not None:
            return _client
        try:
            _last_attempt = time.monotonic()
            import redis

            candidate = redis.Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=0.35,
                socket_timeout=0.5,
                health_check_interval=30,
                decode_responses=True,
            )
            candidate.ping()
            _client = candidate
            _last_error = None
        except Exception as exc:
            _last_error = str(exc)[:240]
            return None
    return _client


def redis_status() -> dict[str, Any]:
    global _client, _last_error
    client = _redis_client()
    if not client:
        return {"enabled": settings.redis_enabled, "online": False, "error": _last_error}
    try:
        return {"enabled": True, "online": bool(client.ping()), "error": None}
    except Exception as exc:
        _client = None
        _last_error = str(exc)[:240]
        return {"enabled": True, "online": False, "error": _last_error}


def cache_json(key: str, producer: Callable[[], Any], ttl: int = 8) -> Any:
    client = _redis_client()
    namespaced = f"{settings.redis_prefix}:{key}"
    if client:
        try:
            cached = client.get(namespaced)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            pass
    value = producer()
    if client:
        try:
            client.setex(namespaced, max(1, ttl), json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            pass
    return value


def invalidate(*keys: str) -> None:
    client = _redis_client()
    if not client:
        return
    try:
        if keys:
            client.delete(*(f"{settings.redis_prefix}:{key}" for key in keys))
        else:
            cursor = 0
            while True:
                cursor, found = client.scan(cursor=cursor, match=f"{settings.redis_prefix}:*", count=100)
                if found:
                    client.delete(*found)
                if cursor == 0:
                    break
    except Exception:
        pass
