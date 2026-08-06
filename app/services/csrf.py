from __future__ import annotations

import hmac
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
EXEMPT_PREFIXES = ("/zapi/webhook/",)
EXEMPT_PATHS = {"/login"}


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = ensure_csrf_token(request)
        if request.method not in SAFE_METHODS and not request.url.path.startswith(EXEMPT_PREFIXES) and request.url.path not in EXEMPT_PATHS:
            supplied = request.headers.get("x-csrf-token") or request.cookies.get("escutapet_v2_csrf")
            if not supplied or not hmac.compare_digest(str(supplied), str(token)):
                if request.url.path.startswith("/api/"):
                    return JSONResponse({"ok": False, "error": "Token de segurança inválido."}, status_code=403)
                return PlainTextResponse("Token de segurança inválido. Atualize a página.", status_code=403)
        response = await call_next(request)
        response.set_cookie(
            "escutapet_v2_csrf",
            token,
            max_age=60 * 60 * settings.session_hours,
            samesite="strict",
            secure=settings.session_https_only,
            httponly=False,
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        permissions = "camera=(), microphone=(self), geolocation=()" if request.url.path.startswith("/conversas") else "camera=(), microphone=(), geolocation=()"
        response.headers.setdefault("Permissions-Policy", permissions)
        return response
