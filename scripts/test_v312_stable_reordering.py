from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

handle, database_path = tempfile.mkstemp(prefix="escutapet_v312_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.main import app
from app.models import EntryFlow, EntryFlowAction, Question, Questionnaire
from app.services.engine import active_questions, options


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def question_key() -> str:
    return f"question:new:{uuid.uuid4()}"


def action_key() -> str:
    return f"action:new:{uuid.uuid4()}"


def option_key() -> str:
    return f"option:{uuid.uuid4()}"


def questionnaire_form(name: str, questions: list[dict]) -> dict:
    return {
        "name": name,
        "description": "Teste da ordenação estável 3.1.2",
        "objective": "satisfaction",
        "status": "active",
        "channels": "kiosk",
        "response_mode": "identified",
        "trigger_type": "manual",
        "delay_value": "0",
        "delay_unit": "days",
        "audience_type": "all",
        "random_percent": "100",
        "opening_message": "Abertura",
        "closing_message": "Encerramento",
        "send_hour": "10",
        "max_attempts": "2",
        "retry_hours": "24",
        "alert_threshold": "6",
        "alert_severity": "high",
        "stop_after_response": "on",
        "questions_json": json.dumps(questions, ensure_ascii=False),
    }


def question_payload(question: Question) -> dict:
    return {
        "id": question.id,
        "item_key": f"question:{question.id}",
        "archived": False,
        "text": question.text,
        "type": question.type,
        "required": question.required,
        "help_text": question.help_text or "",
        "options": options(question),
        "min_score": question.min_score,
        "max_score": question.max_score,
        "low_score_threshold": question.low_score_threshold,
        "segment_low_id": question.segment_low_id,
        "segment_high_id": question.segment_high_id,
        "whatsapp_response_mode": question.whatsapp_response_mode or "auto",
        "data_binding": question.data_binding or "",
    }


def flow_form(registration_id: int, actions: list[dict], name: str = "Fluxo estável 3.1.2") -> dict:
    data = {
        "name": name,
        "description": "Dependências por chave permanente",
        "status": "active",
        "profile_kiosk": "on",
        "profile_interviewer": "on",
        "welcome_title": "Bem-vindo",
        "welcome_text": "Vamos começar.",
        "registration_questionnaire_id": str(registration_id),
        "allow_existing_lookup": "on",
        "allow_no_pet": "on",
        "max_pets": "10",
        "phone_verification_mode": "send_continue",
        "phone_verification_timeout": "180",
        "allow_manual_confirmation": "on",
        "consent_terms_version": "1.0",
        "consent_research_text": "Aceito participar das pesquisas.",
        "consent_marketing_text": "Aceito receber campanhas.",
        "closing_title": "Obrigado!",
        "closing_text": "Cadastro concluído.",
        "actions_count": str(len(actions)),
    }
    for index, item in enumerate(actions):
        prefix = f"action_{index}_"
        for field in (
            "id", "item_key", "name", "trigger", "questionnaire_id", "channel",
            "delay_value", "delay_unit", "schedule_mode", "send_hour",
            "depends_on_key", "condition_question_id", "condition_operator", "condition_value",
        ):
            value = item.get(field)
            data[prefix + field] = str(value if value is not None else "")
        for field in ("require_confirmation", "per_pet", "active"):
            if item.get(field):
                data[prefix + field] = "on"
    return data


def action_payload(action: EntryFlowAction) -> dict:
    return {
        "id": action.id,
        "item_key": f"action:{action.id}",
        "name": action.name,
        "trigger": action.trigger,
        "questionnaire_id": action.questionnaire_id,
        "channel": action.channel,
        "delay_value": action.delay_value,
        "delay_unit": action.delay_unit,
        "schedule_mode": action.schedule_mode,
        "send_hour": action.send_hour if action.send_hour is not None else 10,
        "require_confirmation": action.require_confirmation,
        "per_pet": action.per_pet,
        "active": action.active,
        "depends_on_key": f"action:{action.depends_on_action_id}" if action.depends_on_action_id else "",
        "condition_question_id": action.condition_question_id or "",
        "condition_operator": action.condition_operator or "",
        "condition_value": action.condition_value or "",
    }


with TestClient(app) as client:
    login = client.post("/login", data={"username": "admin", "password": "admin123", "next": "/"}, follow_redirects=False)
    check(login.status_code == 303, "login falhou")

    first_option_ids = [option_key(), option_key(), option_key()]
    questions = [{
        "item_key": question_key(),
        "text": "Pergunta 01",
        "type": "choice",
        "required": True,
        "options": [
            {"id": first_option_ids[0], "label": "Primeira", "value": "valor_a", "history": {"origin": "seed"}},
            {"id": first_option_ids[1], "label": "Segunda", "value": "valor_b", "rule": {"kind": "keep"}},
            {"id": first_option_ids[2], "label": "Terceira", "value": "valor_c"},
        ],
    }]
    questions.extend({"item_key": question_key(), "text": f"Pergunta {index:02d}", "type": "text", "required": index % 2 == 0, "options": []} for index in range(2, 21))
    response = client.post("/questionarios/novo", data=questionnaire_form("Vinte perguntas estáveis", questions), follow_redirects=False)
    check(response.status_code == 303, "questionário com 20 perguntas não foi criado")
    questionnaire_id = int(response.headers["location"].split("/")[2])

    with SessionLocal() as db:
        row = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        original = active_questions(row)
        check(len(original) == 20, "não foram persistidas 20 perguntas")
        original_ids = [question.id for question in original]
        first_question_id = original[0].id
        replacement_question_id = original[1].id
        payloads = [question_payload(question) for question in original]

    # Reordena vinte perguntas e as opções sem mudar nenhuma identidade.
    reordered = list(reversed(payloads))
    choice = next(item for item in reordered if item["id"] == first_question_id)
    choice["options"] = list(reversed(choice["options"]))
    response = client.post(f"/questionarios/{questionnaire_id}/editar", data=questionnaire_form("Vinte perguntas estáveis", reordered), follow_redirects=False)
    check(response.status_code == 303, "reordenação das 20 perguntas falhou")
    with SessionLocal() as db:
        row = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        current = active_questions(row)
        check([question.id for question in current] == list(reversed(original_ids)), "identidades ou ordem das perguntas mudaram")
        choice_row = db.get(Question, first_question_id)
        current_options = options(choice_row)
        check([item["id"] for item in current_options] == list(reversed(first_option_ids)), "identidades das opções mudaram ao reordenar")
        check(current_options[-1]["history"]["origin"] == "seed" and current_options[1]["rule"]["kind"] == "keep", "histórico ou regra da opção foi perdido")
        payloads = [question_payload(question) for question in current]

    # Mistura pergunta nova e antigas, remove uma intermediária e recarrega na ordem exata.
    removed_id = payloads[8]["id"]
    mixed = payloads[:4] + [{"item_key": question_key(), "text": "Pergunta nova entre antigas", "type": "text", "required": False, "options": []}] + payloads[4:8] + payloads[9:]
    response = client.post(f"/questionarios/{questionnaire_id}/editar", data=questionnaire_form("Vinte perguntas estáveis", mixed), follow_redirects=False)
    check(response.status_code == 303, "mistura de perguntas novas e antigas falhou")
    with SessionLocal() as db:
        row = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        current = active_questions(row)
        expected_texts = [item["text"] for item in mixed]
        check([question.text for question in current] == expected_texts, "ordem exata não sobreviveu ao reload")
        check(db.get(Question, removed_id) is None or not db.get(Question, removed_id).active, "pergunta intermediária não foi removida/arquivada")
    page = client.get(f"/questionarios/{questionnaire_id}/editar")
    check(page.status_code == 200 and page.text.index(expected_texts[0]) < page.text.index(expected_texts[1]), "editor não recarregou a ordem persistida")

    with SessionLocal() as db:
        registration = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.seed_key == "structured-registration-v1"))
        survey = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        survey_questions = active_questions(survey)
        condition_question_id = first_question_id
        check(db.get(Question, condition_question_id) is not None, "pergunta usada na condição desapareceu")
        registration_id = registration.id

    parent_key, child_one_key, child_two_key = action_key(), action_key(), action_key()
    base_actions = [
        {"item_key": parent_key, "name": "Pai", "trigger": "after_registration", "questionnaire_id": questionnaire_id, "channel": "whatsapp", "delay_value": 0, "delay_unit": "minutes", "schedule_mode": "exact_interval", "send_hour": 10, "active": True},
        {"item_key": child_one_key, "name": "Filha um", "trigger": "after_action", "questionnaire_id": questionnaire_id, "channel": "whatsapp", "delay_value": 1, "delay_unit": "hours", "schedule_mode": "exact_interval", "send_hour": 11, "depends_on_key": parent_key, "condition_question_id": condition_question_id, "condition_operator": "equals", "condition_value": "valor_a", "active": True},
        {"item_key": child_two_key, "name": "Filha dois", "trigger": "after_action", "questionnaire_id": questionnaire_id, "channel": "whatsapp", "delay_value": 2, "delay_unit": "days", "schedule_mode": "day_hour", "send_hour": 12, "depends_on_key": parent_key, "condition_question_id": condition_question_id, "condition_operator": "answered", "active": True},
    ]
    response = client.post("/fluxos/novo", data=flow_form(registration_id, base_actions), follow_redirects=False)
    error_excerpt = response.text[response.text.find("editor-error-summary"):response.text.find("editor-error-summary") + 1800]
    check(response.status_code == 303, f"fluxo com dois filhos do mesmo pai não foi criado: HTTP {response.status_code} {error_excerpt}")
    flow_id = int(response.headers["location"].split("/")[2])
    with SessionLocal() as db:
        flow = db.scalar(select(EntryFlow).options(selectinload(EntryFlow.actions)).where(EntryFlow.id == flow_id))
        persisted = list(flow.actions)
        check(persisted[1].depends_on_action_id == persisted[0].id and persisted[2].depends_on_action_id == persisted[0].id, "dois filhos não mantiveram o mesmo pai")
        parent_id, child_one_id, child_two_id = [item.id for item in persisted]
        stored = [action_payload(item) for item in persisted]

    # Ação nova entre antigas e reordenação de duas filhas preservam condição, agenda e mensagens/campos.
    inserted_key = action_key()
    inserted = {"item_key": inserted_key, "name": "Intermediária nova", "trigger": "after_registration", "questionnaire_id": questionnaire_id, "channel": "whatsapp", "delay_value": 30, "delay_unit": "minutes", "schedule_mode": "next_allowed", "send_hour": 9, "require_confirmation": True, "active": True}
    reordered_actions = [stored[0], inserted, stored[2], stored[1]]
    response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, reordered_actions), follow_redirects=False)
    check(response.status_code == 303, "reordenação com ação nova e antigas falhou")
    with SessionLocal() as db:
        flow = db.scalar(select(EntryFlow).options(selectinload(EntryFlow.actions)).where(EntryFlow.id == flow_id))
        current = list(flow.actions)
        check([item.name for item in current] == ["Pai", "Intermediária nova", "Filha dois", "Filha um"], "ordem das ações não foi preservada")
        check(current[2].depends_on_action_id == parent_id and current[3].depends_on_action_id == parent_id, "dependência mudou ao reordenar")
        check(current[3].condition_question_id == condition_question_id and current[3].condition_operator == "equals" and current[3].condition_value == "valor_a", "condição mudou ao reordenar")
        check(current[2].delay_value == 2 and current[2].schedule_mode == "day_hour" and current[2].send_hour == 12, "agendamento mudou ao reordenar")
        current_payloads = [action_payload(item) for item in current]
        inserted_id = current[1].id

    # Dependência removida deve bloquear e manter a versão anterior.
    depends_on_intermediate = [dict(item) for item in current_payloads]
    depends_on_intermediate[3]["depends_on_key"] = f"action:{inserted_id}"
    response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, depends_on_intermediate), follow_redirects=False)
    check(response.status_code == 303, "não foi possível preparar dependência intermediária")
    without_intermediate = [depends_on_intermediate[0], depends_on_intermediate[2], depends_on_intermediate[3]]
    response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, without_intermediate), follow_redirects=False)
    check(response.status_code == 400 and "removida ou não existe" in response.text, "exclusão da ação intermediária não sinalizou dependência")
    with SessionLocal() as db:
        check(db.get(EntryFlowAction, child_one_id).depends_on_action_id == inserted_id, "erro de exclusão alterou o banco")

    # Dependente antes do pai, questionário trocado, pergunta arquivada e ciclo são inválidos.
    moved_before_parent = [depends_on_intermediate[3], depends_on_intermediate[0], depends_on_intermediate[1], depends_on_intermediate[2]]
    response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, moved_before_parent), follow_redirects=False)
    check(response.status_code == 400 and "precisa estar antes" in response.text, "dependência futura não foi bloqueada")

    wrong_questionnaire = [dict(item) for item in depends_on_intermediate]
    wrong_questionnaire[1]["questionnaire_id"] = registration_id
    wrong_questionnaire[3]["depends_on_key"] = wrong_questionnaire[1]["item_key"]
    response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, wrong_questionnaire), follow_redirects=False)
    check(response.status_code == 400 and "pertencer à ação anterior" in response.text, "troca de questionário deixou condição apontar para pergunta errada")

    cycle_actions = [dict(depends_on_intermediate[0]), dict(depends_on_intermediate[1])]
    cycle_actions[0].update({"trigger": "after_action", "depends_on_key": cycle_actions[1]["item_key"], "condition_question_id": "", "condition_operator": "", "condition_value": ""})
    cycle_actions[1].update({"trigger": "after_action", "depends_on_key": cycle_actions[0]["item_key"], "condition_question_id": "", "condition_operator": "", "condition_value": ""})
    response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, cycle_actions), follow_redirects=False)
    check(response.status_code == 400 and "formam um ciclo" in response.text, "ciclo direto/indireto não foi bloqueado")

    with SessionLocal() as db:
        condition_question = db.get(Question, condition_question_id)
        condition_question.active = False
        db.commit()
    response = client.post(f"/fluxos/{flow_id}/editar", data=flow_form(registration_id, depends_on_intermediate), follow_redirects=False)
    check(response.status_code == 303, "a condição da versão publicada foi invalidada por uma alteração ainda não publicada")
    with SessionLocal() as db:
        db.get(Question, condition_question_id).active = True
        db.commit()

    # Impacto: remoção sem substituta bloqueia; com substituta atualiza a ação antes de arquivar.
    with SessionLocal() as db:
        survey = db.scalar(select(Questionnaire).options(selectinload(Questionnaire.questions)).where(Questionnaire.id == questionnaire_id))
        impact_payloads = [question_payload(question) for question in active_questions(survey)]
    impacted = next(item for item in impact_payloads if item["id"] == condition_question_id)
    impacted["archived"] = True
    response = client.post(f"/questionarios/{questionnaire_id}/editar", data=questionnaire_form("Vinte perguntas estáveis", impact_payloads), follow_redirects=False)
    check(response.status_code == 400 and "não pode ser removida sem substituição" in response.text or "Escolha outra pergunta ativa" in response.text, "impacto sem substituição não foi bloqueado")
    impacted["replacement_question_id"] = replacement_question_id
    response = client.post(f"/questionarios/{questionnaire_id}/editar", data=questionnaire_form("Vinte perguntas estáveis", impact_payloads), follow_redirects=False)
    check(response.status_code == 303, "substituição de pergunta impactada falhou")
    with SessionLocal() as db:
        affected = db.scalars(select(EntryFlowAction).where(EntryFlowAction.flow_id == flow_id, EntryFlowAction.condition_question_id == replacement_question_id)).all()
        check(affected, "condições não foram redirecionadas para a pergunta substituta")
        old_question = db.get(Question, condition_question_id)
        check(old_question is None or not old_question.active, "pergunta impactada não foi arquivada")

    questionnaire_js = (PROJECT_DIR / "app/static/js/questionnaire-editor.js").read_text(encoding="utf-8")
    flow_js = (PROJECT_DIR / "app/static/js/flow-actions.js").read_text(encoding="utf-8")
    flow_template = (PROJECT_DIR / "app/templates/entry_flow_editor.html").read_text(encoding="utf-8")
    check("depends_on_position" not in flow_js and "depends_on_position" not in flow_template, "navegador ainda envia dependências por posição")
    for marker in ("data-question-drag-handle", "data-option-up", "data-duplicate-option", "ArrowUp", "replacement_question_id"):
        check(marker in questionnaire_js, f"controle obrigatório ausente: {marker}")
    for marker in ("data-action-drag-handle", "depends_on_key", "formam um ciclo", "ArrowDown"):
        check(marker in flow_js, f"controle de fluxo ausente: {marker}")

Path(database_path).unlink(missing_ok=True)
print("OK - EscutaPet 3.1.2 identidades, reordenação, dependências, impactos e reload validados.")
