from __future__ import annotations

import os
import re
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_visual_test_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["SECRET_KEY"] = "visual-test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient

from app.main import app


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class IconControlAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inaccessible: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "button"}:
            return
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if "icon-button" not in classes:
            return
        if not (values.get("aria-label") or values.get("title")):
            self.inaccessible.append(self.get_starttag_text())


with TestClient(app) as client:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123", "next": "/"},
        follow_redirects=False,
    )
    check(response.status_code == 303, "login visual falhou")

    paths = [
        "/",
        "/leads",
        "/leads/novo",
        "/leads/importar-whatsapp",
        "/questionarios",
        "/questionarios/novo",
        "/fluxos/novo",
        "/segmentos",
        "/alertas",
        "/conversas",
        "/relatorios",
        "/dispositivos",
        "/configuracoes",
        "/entrevistador",
        "/usuarios",
        "/conta",
    ]
    for path in paths:
        page = client.get(path)
        check(page.status_code == 200, f"página visual falhou: {path}")
        check("v=3.0.1" not in page.text, f"cache visual antigo em {path}")
        check("v=3.6.0" in page.text, f"versão dos ativos ausente em {path}")
        audit = IconControlAudit()
        audit.feed(page.text)
        check(not audit.inaccessible, f"controle somente ícone sem nome acessível em {path}: {audit.inaccessible}")

    settings_html = client.get("/configuracoes").text
    check("settings-grid" in settings_html, "grade de configurações ausente")
    check(settings_html.count("class=\"button-row\"") >= 2, "grupos de ações das configurações ausentes")

base_template = (PROJECT_DIR / "app/templates/base.html").read_text(encoding="utf-8")
nav_labels = re.findall(r'<nav class="nav-list">(.+?)</nav>', base_template, re.S)
check(nav_labels and "Configurações e Z-API" in nav_labels[0], "rótulo completo das configurações ausente")

visual_css = (PROJECT_DIR / "app/static/css/visual-v3.css").read_text(encoding="utf-8")
check("width:auto!important" in visual_css, "largura dos nomes da navegação não foi corrigida")
check("@media(min-width:768px) and (max-width:860px)" in visual_css, "faixa de notebook não foi tratada")
check(".menu-toggle{display:none!important}" in visual_css, "hambúrguer não foi ocultado no desktop")
check(".settings-grid .button-row .btn{width:100%;height:100%}" in visual_css, "botões das configurações não foram uniformizados")

Path(database_path).unlink(missing_ok=True)
print("OK - auditoria visual e responsiva da versão 3.1.2 validada.")
