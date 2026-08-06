from __future__ import annotations

import hashlib
import json
import logging
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    EntryFlowAction,
    MessageQueue,
    Question,
    Questionnaire,
    QuestionnaireVersion,
    QuestionnaireVersionMigrationIssue,
    QuestionnaireVersionMigrationState,
    QuestionnaireVersionOption,
    QuestionnaireVersionQuestion,
    SurveyAnswer,
    SurveyExecution,
    utcnow,
)

logger = logging.getLogger(__name__)


class VersionConsistencyError(RuntimeError):
    """Erro operacional: uma execução não possui snapshot confiável."""


CONFIG_FIELDS = (
    "name", "description", "objective", "status", "channels_json", "response_mode",
    "trigger_type", "delay_value", "delay_unit", "recurrence_days", "random_percent",
    "audience_type", "target_segment_id", "opening_message", "closing_message",
    "send_hour", "max_attempts", "retry_hours", "stop_after_response", "alert_enabled",
    "alert_threshold", "alert_severity", "auto_segment",
)

QUESTION_FIELDS = (
    "text", "type", "required", "help_text", "options_json", "min_score", "max_score",
    "low_score_threshold", "segment_low_id", "segment_high_id", "whatsapp_response_mode",
    "data_binding", "settings_json",
)


def _json(value: str | None, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, ValueError):
        return fallback


def questionnaire_config(questionnaire: Questionnaire) -> dict:
    return {field: getattr(questionnaire, field) for field in CONFIG_FIELDS}


def _active_live_questions(questionnaire: Questionnaire) -> list[Question]:
    return sorted(
        [item for item in questionnaire.questions if getattr(item, "active", True)],
        key=lambda item: (item.position, item.id or 0),
    )


def _option_key(item: dict, index: int) -> str:
    return str(item.get("item_key") or item.get("stable_key") or item.get("id") or f"option:{index}")


def snapshot_payload(questionnaire: Questionnaire) -> dict:
    questions = []
    for position, question in enumerate(_active_live_questions(questionnaire), start=1):
        data = {field: getattr(question, field) for field in QUESTION_FIELDS}
        data.update({
            "original_question_id": question.id,
            "stable_key": f"question:{question.id}",
            "position": position,
            "options": _json(question.options_json, []),
        })
        questions.append(data)
    return {"config": questionnaire_config(questionnaire), "questions": questions}


def _signature(payload: dict) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def latest_published_version(db: Session, questionnaire_or_id: Questionnaire | int) -> QuestionnaireVersion | None:
    questionnaire_id = questionnaire_or_id.id if isinstance(questionnaire_or_id, Questionnaire) else int(questionnaire_or_id)
    return db.scalar(
        select(QuestionnaireVersion)
        .options(selectinload(QuestionnaireVersion.questions))
        .where(
            QuestionnaireVersion.questionnaire_id == questionnaire_id,
            QuestionnaireVersion.status == "published",
        )
        .order_by(QuestionnaireVersion.version_number.desc())
        .limit(1)
    )


def version_config(version: QuestionnaireVersion) -> SimpleNamespace:
    data = _json(version.config_json, {})
    data.setdefault("name", version.name)
    data["version_number"] = version.version_number
    data["version_id"] = version.id
    return SimpleNamespace(**data)


def execution_config(execution: SurveyExecution) -> SimpleNamespace:
    if not execution.questionnaire_version:
        raise VersionConsistencyError(
            f"Execução {execution.id} sem questionnaire_version_id; operação interrompida para preservar o histórico."
        )
    return version_config(execution.questionnaire_version)


def execution_questions(execution: SurveyExecution) -> list[QuestionnaireVersionQuestion]:
    version = execution.questionnaire_version
    if not version:
        raise VersionConsistencyError(
            f"Execução {execution.id} sem versão publicada; não é seguro usar o questionário editável."
        )
    questions = sorted(version.questions, key=lambda item: (item.position, item.id))
    if not questions:
        raise VersionConsistencyError(f"Versão {version.id} da execução {execution.id} não possui perguntas congeladas.")
    return questions


def change_summary(questionnaire: Questionnaire, previous: QuestionnaireVersion | None = None) -> dict:
    payload = snapshot_payload(questionnaire)
    current = {item["stable_key"]: item for item in payload["questions"]}
    previous_items = {}
    if previous:
        previous_items = {
            item.stable_key: {
                **{field: getattr(item, field) for field in QUESTION_FIELDS},
                "position": item.position,
            }
            for item in previous.questions
        }
    added = sorted(set(current) - set(previous_items))
    removed = sorted(set(previous_items) - set(current))
    changed = []
    options_changed = []
    for key in sorted(set(current) & set(previous_items)):
        now = current[key]
        old = previous_items[key]
        if any(now.get(field) != old.get(field) for field in QUESTION_FIELDS if field != "options_json") or now["position"] != old["position"]:
            changed.append(key)
        if now.get("options_json") != old.get("options_json"):
            options_changed.append(key)
    config_changed = []
    if previous:
        old_config = _json(previous.config_json, {})
        config_changed = [field for field in CONFIG_FIELDS if payload["config"].get(field) != old_config.get(field)]
    elif payload["config"]:
        config_changed = list(CONFIG_FIELDS)
    return {
        "questions_before": len(previous_items),
        "questions_after": len(current),
        "added": added,
        "removed": removed,
        "changed": changed,
        "options_changed": options_changed,
        "config_changed": config_changed,
    }


def publish_questionnaire_version(
    db: Session,
    questionnaire: Questionnaire,
    *,
    user_id: int | None = None,
    force_initial: bool = False,
) -> tuple[QuestionnaireVersion, bool]:
    previous = latest_published_version(db, questionnaire)
    payload = snapshot_payload(questionnaire)
    signature = _signature(payload)
    if previous and previous.content_signature == signature and not force_initial:
        return previous, False
    version_number = (previous.version_number if previous else 0) + 1
    summary = change_summary(questionnaire, previous)
    version = QuestionnaireVersion(
        questionnaire_id=questionnaire.id,
        version_number=version_number,
        status="published",
        name=questionnaire.name,
        config_json=json.dumps(payload["config"], ensure_ascii=False, default=str),
        content_signature=signature,
        change_summary_json=json.dumps(summary, ensure_ascii=False),
        published_at=utcnow(),
        published_by_id=user_id,
    )
    db.add(version)
    db.flush()
    for item in payload["questions"]:
        question = QuestionnaireVersionQuestion(
            version_id=version.id,
            original_question_id=item["original_question_id"],
            stable_key=item["stable_key"],
            position=item["position"],
            **{field: item.get(field) for field in QUESTION_FIELDS},
            metadata_json=json.dumps({"presentation": {}, "rules": {}}, ensure_ascii=False),
        )
        db.add(question)
        db.flush()
        for option_position, option_data in enumerate(item.get("options") or [], start=1):
            if not isinstance(option_data, dict):
                option_data = {"label": str(option_data), "value": str(option_data)}
            db.add(QuestionnaireVersionOption(
                version_question_id=question.id,
                stable_key=_option_key(option_data, option_position),
                position=option_position,
                label=str(option_data.get("label") or option_data.get("value") or "Opção"),
                value=str(option_data.get("value") or option_data.get("label") or ""),
                segment_id=option_data.get("segment_id"),
                creates_alert=bool(option_data.get("creates_alert")),
                metadata_json=json.dumps(option_data, ensure_ascii=False, default=str),
            ))
    questionnaire.published_at = version.published_at
    db.flush()
    return version, True


def _legacy_execution_version(
    db: Session,
    questionnaire: Questionnaire,
    base: QuestionnaireVersion,
    execution_id: int,
    referenced_question_ids: set[int],
) -> QuestionnaireVersion:
    """Cria snapshot histórico isolado quando o banco antigo tinha respostas de pergunta arquivada."""
    base_ids = {item.original_question_id for item in base.questions}
    missing_ids = referenced_question_ids - base_ids
    existing = db.scalar(select(QuestionnaireVersion).where(
        QuestionnaireVersion.questionnaire_id == questionnaire.id,
        QuestionnaireVersion.version_number == -execution_id,
    ))
    if existing:
        return existing
    live_missing = {
        item.id: item for item in db.scalars(select(Question).where(Question.id.in_(missing_ids))).all()
    }
    if set(live_missing) != missing_ids:
        raise VersionConsistencyError(
            f"Execução histórica {execution_id} referencia perguntas inexistentes: {sorted(missing_ids - set(live_missing))}."
        )
    version = QuestionnaireVersion(
        questionnaire_id=questionnaire.id,
        version_number=-execution_id,
        status="historical",
        name=base.name,
        config_json=base.config_json,
        content_signature=hashlib.sha256(f"{base.content_signature}:legacy:{execution_id}:{sorted(missing_ids)}".encode()).hexdigest(),
        change_summary_json=json.dumps({"migration": True, "legacy_execution_id": execution_id, "recovered_questions": sorted(missing_ids)}, ensure_ascii=False),
        published_at=base.published_at,
        published_by_id=base.published_by_id,
    )
    db.add(version)
    db.flush()
    rows: list[dict] = []
    for item in base.questions:
        rows.append({
            "original_question_id": item.original_question_id,
            "stable_key": item.stable_key,
            "position": item.position,
            **{field: getattr(item, field) for field in QUESTION_FIELDS},
            "metadata_json": item.metadata_json,
        })
    for item in live_missing.values():
        rows.append({
            "original_question_id": item.id,
            "stable_key": f"question:{item.id}",
            "position": item.position,
            **{field: getattr(item, field) for field in QUESTION_FIELDS},
            "metadata_json": json.dumps({"migration": True, "recovered_archived_question": True}, ensure_ascii=False),
        })
    for position, data in enumerate(sorted(rows, key=lambda item: (item["position"], item["original_question_id"] or 0)), start=1):
        snapshot = QuestionnaireVersionQuestion(
            version_id=version.id,
            original_question_id=data["original_question_id"],
            stable_key=data["stable_key"],
            position=position,
            **{field: data.get(field) for field in QUESTION_FIELDS},
            metadata_json=data["metadata_json"],
        )
        db.add(snapshot)
        db.flush()
        for option_position, option_data in enumerate(_json(snapshot.options_json, []), start=1):
            if not isinstance(option_data, dict):
                option_data = {"label": str(option_data), "value": str(option_data)}
            db.add(QuestionnaireVersionOption(
                version_question_id=snapshot.id,
                stable_key=_option_key(option_data, option_position),
                position=option_position,
                label=str(option_data.get("label") or option_data.get("value") or "Opção"),
                value=str(option_data.get("value") or option_data.get("label") or ""),
                segment_id=option_data.get("segment_id"),
                creates_alert=bool(option_data.get("creates_alert")),
                metadata_json=json.dumps(option_data, ensure_ascii=False, default=str),
            ))
    db.flush()
    return version


def resolve_action_version(db: Session, action: EntryFlowAction) -> QuestionnaireVersion:
    if action.version_mode == "fixed":
        version = db.get(QuestionnaireVersion, action.fixed_version_id) if action.fixed_version_id else None
        if not version or version.questionnaire_id != action.questionnaire_id or version.status != "published":
            raise VersionConsistencyError(f"Ação {action.id} aponta para uma versão fixa inválida.")
        return version
    version = latest_published_version(db, action.questionnaire_id)
    if not version:
        raise VersionConsistencyError(f"Questionário {action.questionnaire_id} da ação {action.id} não possui versão publicada.")
    return version


def _issue(db: Session, entity: str, entity_id: int | None, code: str, details: str) -> None:
    exists = db.scalar(select(QuestionnaireVersionMigrationIssue).where(
        QuestionnaireVersionMigrationIssue.entity == entity,
        QuestionnaireVersionMigrationIssue.entity_id == entity_id,
        QuestionnaireVersionMigrationIssue.code == code,
        QuestionnaireVersionMigrationIssue.resolved.is_(False),
    ).limit(1))
    if not exists:
        db.add(QuestionnaireVersionMigrationIssue(entity=entity, entity_id=entity_id, code=code, details=details))
    logger.error("Migração 3.2.0 [%s:%s] %s: %s", entity, entity_id, code, details)


def migrate_questionnaire_versions(db: Session) -> dict[str, int]:
    """Backfill idempotente. Preserva IDs históricos e só acrescenta vínculos."""
    stats = {"versions": 0, "executions": 0, "answers": 0, "queue": 0, "issues": 0}
    migration_state = db.get(QuestionnaireVersionMigrationState, 1)
    initial_migration = migration_state is None
    questionnaires = db.scalars(
        select(Questionnaire).options(selectinload(Questionnaire.questions)).order_by(Questionnaire.id)
    ).all()
    for questionnaire in questionnaires:
        version = latest_published_version(db, questionnaire)
        if not version:
            version, created = publish_questionnaire_version(
                db, questionnaire, user_id=questionnaire.created_by_id, force_initial=True
            )
            stats["versions"] += int(created)
        executions = db.scalars(select(SurveyExecution).where(
            SurveyExecution.questionnaire_id == questionnaire.id,
        )).all()
        for execution in executions:
            answers = db.scalars(select(SurveyAnswer).where(SurveyAnswer.execution_id == execution.id)).all()
            queued_questions = db.scalars(select(MessageQueue).where(
                MessageQueue.execution_id == execution.id,
                MessageQueue.question_id.is_not(None),
            )).all()
            execution_version = db.get(QuestionnaireVersion, execution.questionnaire_version_id) if execution.questionnaire_version_id else None
            if not execution_version or execution_version.questionnaire_id != questionnaire.id:
                if initial_migration:
                    execution.questionnaire_version_id = version.id
                    execution_version = version
                    stats["executions"] += 1
                else:
                    _issue(db, "execution", execution.id, "missing_or_invalid_version", "Execução criada após a migração sem uma versão publicada válida; vínculo não foi reparado silenciosamente.")
                    stats["issues"] += 1
                    continue
            referenced_ids = {item.question_id for item in answers} | {item.question_id for item in queued_questions if item.question_id}
            snapshot_ids = {item.original_question_id for item in execution_version.questions}
            if initial_migration and referenced_ids - snapshot_ids:
                try:
                    execution_version = _legacy_execution_version(
                        db, questionnaire, execution_version, execution.id, referenced_ids
                    )
                    execution.questionnaire_version_id = execution_version.id
                    stats["versions"] += 1
                except VersionConsistencyError as exc:
                    _issue(db, "execution", execution.id, "legacy_snapshot_incomplete", str(exc))
                    stats["issues"] += 1
            question_map = {item.original_question_id: item for item in execution_version.questions if item.original_question_id}
            for answer in [item for item in answers if item.version_question_id is None]:
                version_question = question_map.get(answer.question_id)
                if version_question:
                    answer.version_question_id = version_question.id
                    stats["answers"] += 1
                else:
                    _issue(db, "answer", answer.id, "question_not_in_snapshot", f"Pergunta histórica {answer.question_id} não existe na versão {execution_version.id}.")
                    stats["issues"] += 1
            for queued in [item for item in queued_questions if item.version_question_id is None]:
                version_question = question_map.get(queued.question_id)
                if version_question:
                    queued.version_question_id = version_question.id
                    stats["queue"] += 1
                else:
                    _issue(db, "queue", queued.id, "question_not_in_snapshot", f"Pergunta {queued.question_id} não existe na versão {execution_version.id}.")
                    stats["issues"] += 1
    if initial_migration:
        db.add(QuestionnaireVersionMigrationState(id=1, completed_at=utcnow(), stats_json=json.dumps(stats, ensure_ascii=False)))
    else:
        migration_state.stats_json = json.dumps(stats, ensure_ascii=False)
    db.commit()
    logger.info("Migração de versões 3.2.0 concluída: %s", stats)
    return stats


def version_impact(db: Session, questionnaire: Questionnaire) -> dict:
    latest = latest_published_version(db, questionnaire)
    summary = change_summary(questionnaire, latest)
    summary.update({
        "current_version": latest.version_number if latest else 0,
        "next_version": (latest.version_number if latest else 0) + 1,
        "active_executions": db.scalar(select(func.count(SurveyExecution.id)).where(
            SurveyExecution.questionnaire_id == questionnaire.id,
            SurveyExecution.status.in_(("scheduled", "active")),
        )) or 0,
        "flows": db.scalar(select(func.count(EntryFlowAction.id)).where(
            EntryFlowAction.questionnaire_id == questionnaire.id,
            EntryFlowAction.active.is_(True),
        )) or 0,
        "fixed_actions": db.scalar(select(func.count(EntryFlowAction.id)).where(
            EntryFlowAction.questionnaire_id == questionnaire.id,
            EntryFlowAction.active.is_(True),
            EntryFlowAction.version_mode == "fixed",
        )) or 0,
    })
    return summary
