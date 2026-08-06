from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
handle, database_path = tempfile.mkstemp(prefix="escutapet_v324_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["REDIS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.database import SessionLocal, engine
from app.main import app
from app.models import AuditLog, EditorDraft, EntryFlow, MessageQueue, Questionnaire, SurveyExecution
from app.services.versioning import latest_published_version, version_config


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def flow_form(registration_id: int, survey_id: int, *, name: str, revision: int | None = None) -> dict:
    data = {
        "submission_token": str(uuid.uuid4()), "flow_schema": "3.2.5", "name": name, "description": "Jornada recuperável", "status": "draft",
        "profile_kiosk": "on", "profile_interviewer": "on", "welcome_title": "Bem-vindo", "welcome_text": "Vamos começar.",
        "registration_questionnaire_id": str(registration_id), "allow_existing_lookup": "on", "allow_no_pet": "on", "max_pets": "10",
        "consent_research_enabled": "on", "consent_terms_enabled": "on", "consent_terms_version": "1.0", "consent_research_text": "Aceito pesquisas.",
        "phone_verification_mode": "future_only", "phone_verification_timeout": "180", "allow_manual_confirmation": "on",
        "closing_title": "Obrigado!", "closing_text": "Concluído.", "actions_count": "1",
        "action_0_id": "", "action_0_item_key": f"action:new:{uuid.uuid4()}", "action_0_name": "Pesquisa em duas horas",
        "action_0_questionnaire_id": str(survey_id), "action_0_version_mode": "latest_published", "action_0_trigger": "after_registration",
        "action_0_delay_value": "2", "action_0_delay_unit": "hours", "action_0_schedule_mode": "exact_interval", "action_0_send_hour": "10",
        "action_0_channel": "whatsapp", "action_0_require_confirmation": "on", "action_0_active": "on",
    }
    if revision is not None:
        data["base_revision"] = str(revision)
    return data


def questionnaire_form(row: Questionnaire, questions: list[dict], *, name: str, revision: int) -> dict:
    return {
        "submission_token": str(uuid.uuid4()), "base_revision": str(revision), "editor_action": "draft",
        "name": name, "description": row.description or "Teste de conflito", "objective": row.objective, "status": "draft",
        "channels": "whatsapp", "response_mode": "identified", "trigger_type": "manual", "delay_value": "0", "delay_unit": "days",
        "audience_type": "all", "random_percent": "100", "opening_message": row.opening_message or "Olá!", "closing_message": row.closing_message or "Obrigado!",
        "send_hour": "10", "max_attempts": "2", "retry_hours": "24", "alert_threshold": "6", "alert_severity": "high",
        "stop_after_response": "on", "questions_json": json.dumps(questions, ensure_ascii=False),
    }


with TestClient(app) as client:
    check(client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False).status_code == 303, "login falhou")
    tables = set(inspect(engine).get_table_names())
    check("editor_drafts" in tables, "tabela de rascunhos ausente")
    with SessionLocal() as db:
        registration = db.scalar(select(Questionnaire).where(Questionnaire.seed_key == "structured-registration-v1"))
        surveys = db.scalars(select(Questionnaire).where(Questionnaire.status == "active")).all()
        survey = next(item for item in surveys if item.id != registration.id and latest_published_version(db, item) and version_config(latest_published_version(db, item)).response_mode == "identified")
        registration_id, survey_id = registration.id, survey.id
        survey_questions = [{"id": item.id, "item_key": f"question:{item.id}", "text": item.text, "type": item.type, "required": item.required, "help_text": item.help_text or "", "options": json.loads(item.options_json or "[]"), "min_score": item.min_score, "max_score": item.max_score, "low_score_threshold": item.low_score_threshold, "segment_low_id": item.segment_low_id, "segment_high_id": item.segment_high_id, "whatsapp_response_mode": item.whatsapp_response_mode or "auto", "data_binding": item.data_binding or "", "settings": json.loads(item.settings_json or "{}")} for item in survey.questions if item.active]

    created = client.post("/fluxos/novo", data=flow_form(registration_id, survey_id, name="Jornada 3.2.5"), follow_redirects=False)
    check(created.status_code == 303, f"criação do fluxo falhou: {created.status_code}")
    flow_id = int(created.headers["location"].split("/")[2])
    editor = client.get(f"/fluxos/{flow_id}/editar")
    check(editor.status_code == 200 and "data-editor-recovery" in editor.text and "editor-recovery.js?v=3.6.0" in editor.text, "proteção de rascunho não foi carregada")
    check('class="journey-action-drawer journey-action-modal"' in editor.text and 'role="dialog"' in editor.text and 'aria-modal="true"' in editor.text, "editor de ação não foi convertido em modal acessível")

    draft_payload = {"schema": 1, "base_revision": 1, "saved_at": "2026-08-01T12:00:00", "data": {"fields": {"name": "Recuperado"}, "actions": []}}
    saved = client.post(f"/api/editor-drafts/flow/{flow_id}", json=draft_payload)
    check(saved.status_code == 200 and saved.json()["ok"], "rascunho não foi salvo")
    recovered = client.get(f"/api/editor-drafts/flow/{flow_id}").json()["draft"]
    check(recovered and recovered["payload"]["data"]["fields"]["name"] == "Recuperado", "rascunho não foi recuperado")
    check(client.post(f"/api/editor-drafts/flow/{flow_id}/restore").status_code == 200, "auditoria de restauração falhou")

    first = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, survey_id, name="Primeiro salvamento", revision=1), follow_redirects=False)
    check(first.status_code == 303, "primeiro salvamento concorrente falhou")
    stale = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, survey_id, name="Sobrescrita indevida", revision=1), follow_redirects=False)
    check(stale.status_code == 409 and 'id="editor-conflict-data"' in stale.text and '"current_revision": 2' in stale.text, f"conflito otimista não bloqueou a sobrescrita: HTTP {stale.status_code}")
    with SessionLocal() as db:
        flow = db.get(EntryFlow, flow_id)
        action_id = flow.actions[0].id
        check(flow.name == "Primeiro salvamento" and flow.revision == 2, "edição obsoleta alterou o fluxo")
        before_queue = db.scalar(select(func.count(MessageQueue.id))) or 0
        before_exec = db.scalar(select(func.count(SurveyExecution.id))) or 0
        check(db.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity == "entry_flow", AuditLog.entity_id == flow_id)) >= 2, "auditoria de criação/edição ausente")
        check(db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "editor_draft_restore")) >= 1, "auditoria de restauração ausente")

    simulation = client.post(f"/api/fluxos/{flow_id}/laboratorio/simular", json={"elapsed_minutes": 120, "confirmed": True, "condition_matches": True, "pets": 2})
    check(simulation.status_code == 200 and simulation.json()["safe"] and simulation.json()["writes"] == 0, "laboratório completo falhou")
    check(simulation.json()["actions"][0]["ready"], "passagem de tempo não liberou a ação")
    isolated = client.post(f"/api/fluxos/{flow_id}/laboratorio/acoes/{action_id}/simular", json={"elapsed_minutes": 0, "confirmed": False, "pets": 1})
    check(isolated.status_code == 200 and isolated.json()["isolated_action_id"] == action_id and len(isolated.json()["actions"]) == 1, "teste isolado falhou")
    with SessionLocal() as db:
        check((db.scalar(select(func.count(MessageQueue.id))) or 0) == before_queue, "laboratório escreveu na fila")
        check((db.scalar(select(func.count(SurveyExecution.id))) or 0) == before_exec, "laboratório criou execução")
    check(client.delete(f"/api/editor-drafts/flow/{flow_id}").status_code == 200, "descarte do rascunho falhou")
    with SessionLocal() as db:
        check(not db.scalar(select(EditorDraft).where(EditorDraft.entity_type == "flow", EditorDraft.entity_key == str(flow_id))), "rascunho não foi descartado")

    question_draft = client.post(f"/api/editor-drafts/questionnaire/{survey_id}", json={"schema": 1, "base_revision": 1, "saved_at": "2026-08-01T13:00:00", "data": {"fields": {"name": "Pesquisa recuperada"}, "questions": survey_questions}})
    check(question_draft.status_code == 200, "rascunho de questionário não foi salvo")
    with SessionLocal() as db:
        survey_row = db.get(Questionnaire, survey_id)
        first_questionnaire = questionnaire_form(survey_row, survey_questions, name="Questionário revisão 2", revision=1)
    check(client.post(f"/questionarios/{survey_id}/editar", data=first_questionnaire, follow_redirects=False).status_code == 303, "primeira revisão do questionário falhou")
    with SessionLocal() as db:
        survey_row = db.get(Questionnaire, survey_id)
        stale_questionnaire = questionnaire_form(survey_row, survey_questions, name="Sobrescrita de questionário", revision=1)
    questionnaire_conflict = client.post(f"/questionarios/{survey_id}/editar", data=stale_questionnaire, follow_redirects=False)
    check(questionnaire_conflict.status_code == 409 and 'id="editor-conflict-data"' in questionnaire_conflict.text, "conflito do questionário não foi bloqueado")
    with SessionLocal() as db:
        check(db.get(Questionnaire, survey_id).name == "Questionário revisão 2", "conflito alterou o questionário")

js = (PROJECT_DIR / "app/static/js/editor-recovery.js").read_text(encoding="utf-8")
for marker in ("localStorage", "Comparar", "Duplicar como rascunho", "editor:submitting", "base_revision"):
    check(marker in js, f"recurso de recuperação ausente: {marker}")
css = (PROJECT_DIR / "app/static/css/visual-v3.css").read_text(encoding="utf-8")
modal_rule = css.rfind("/* 3.2.5 · alinhamento dos cartões")
legacy_drawer_rule = css.rfind(".journey-action-drawer{")
check(modal_rule > legacy_drawer_rule and "translate(-50%,-50%)" in css[modal_rule:], "regra final do modal central está ausente ou foi sobrescrita")
check(".journey-action-card>.timeline-connector{position:absolute" in css and "grid-template-columns:30px 42px minmax(0,1fr) auto" in css, "alinhamento compacto dos cartões está ausente")

print("OK - EscutaPet 3.2.5: rascunhos, recuperação, conflitos, auditoria, passagem do tempo e ações isoladas validados.")
