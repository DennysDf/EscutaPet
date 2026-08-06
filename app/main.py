from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.middleware.sessions import SessionMiddleware

from .config import BASE_DIR, settings
from .database import SessionLocal
from .models import SystemSetting
from .routers import api, editor, entry, web, webhooks
from .services.bootstrap import initialize_database
from .services.csrf import CSRFMiddleware
from .services.branding import safe_branding_path
from .services.timezone import DEFAULT_TIMEZONE, format_local

app = FastAPI(title=settings.app_name, version="3.6.0", docs_url="/api/docs", redoc_url=None)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="escutapet_v2_session",
    max_age=60 * 60 * settings.session_hours,
    same_site="lax",
    https_only=settings.session_https_only,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.state.templates.env.filters["from_json"] = lambda value: json.loads(value or "[]")
@pass_context
def _datebr(context, value, fmt="%d/%m/%Y %H:%M"):
    user = context.get("user")
    system = context.get("system")
    timezone_name = (
        getattr(user, "timezone_name", None)
        or getattr(system, "timezone_name", None)
        or DEFAULT_TIMEZONE
    )
    return format_local(value, timezone_name, fmt)


app.state.templates.env.filters["datebr"] = _datebr
app.include_router(entry.router)
app.include_router(web.router)
app.include_router(api.router)
app.include_router(webhooks.router)
app.include_router(editor.router)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    with SessionLocal() as db:
        system = db.get(SystemSetting, 1)
        name = system.product_name if system else settings.app_name
        theme = system.primary_color if system else "#0f766e"
        version = system.branding_version if system else 1
        custom_icon = bool(system and system.logo_icon_file and safe_branding_path("pwa-192.png") and safe_branding_path("pwa-192.png").exists())
    icon_base = "/branding" if custom_icon else "/static/img"
    suffix = f"?v={version}" if custom_icon else ""
    return JSONResponse({
        "name": name,
        "short_name": name[:24],
        "description": "Questionários inteligentes por WhatsApp, quiosque e entrevistador.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f7fb",
        "theme_color": theme,
        "lang": "pt-BR",
        "icons": [
            {"src": f"{icon_base}/pwa-192.png{suffix}", "sizes": "192x192", "type": "image/png"},
            {"src": f"{icon_base}/pwa-512.png{suffix}", "sizes": "512x512", "type": "image/png"},
        ],
    }, media_type="application/manifest+json")


@app.get("/branding/{filename}", include_in_schema=False)
def branding_asset(filename: str):
    path = safe_branding_path(filename)
    if not path or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/service-worker.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE_DIR / "static" / "js" / "service-worker.js", media_type="application/javascript")


@app.exception_handler(401)
async def unauthorized(request: Request, _exc):
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "error": "Recurso não encontrado."}, status_code=404)
    return app.state.templates.TemplateResponse(request, "error.html", {"request": request, "status": 404, "message": "Página não encontrada."}, status_code=404)


@app.get("/offline", include_in_schema=False)
def offline():
    return HTMLResponse("""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Sem conexão</title><link rel='stylesheet' href='/static/css/app.css'></head><body class='public-bg'><main class='center-card'><h1>Sem conexão</h1><p>Verifique a internet e tente novamente.</p><button class='btn primary' onclick='location.reload()'>Tentar novamente</button></main></body></html>""")
