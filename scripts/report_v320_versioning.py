from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import func, select

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app.database import SessionLocal
from app.models import (
    MessageQueue,
    QuestionnaireVersionMigrationIssue,
    SurveyAnswer,
    SurveyExecution,
)


with SessionLocal() as db:
    result = {
        "executions_without_version": db.scalar(select(func.count(SurveyExecution.id)).where(SurveyExecution.questionnaire_version_id.is_(None))) or 0,
        "answers_without_version_question": db.scalar(select(func.count(SurveyAnswer.id)).where(SurveyAnswer.version_question_id.is_(None))) or 0,
        "queued_questions_without_version": db.scalar(select(func.count(MessageQueue.id)).where(MessageQueue.execution_id.is_not(None), MessageQueue.question_id.is_not(None), MessageQueue.version_question_id.is_(None))) or 0,
        "open_migration_issues": db.scalar(select(func.count(QuestionnaireVersionMigrationIssue.id)).where(QuestionnaireVersionMigrationIssue.resolved.is_(False))) or 0,
    }
    result["issues"] = [{
        "entity": item.entity,
        "entity_id": item.entity_id,
        "code": item.code,
        "details": item.details,
    } for item in db.scalars(select(QuestionnaireVersionMigrationIssue).where(
        QuestionnaireVersionMigrationIssue.resolved.is_(False)
    ).order_by(QuestionnaireVersionMigrationIssue.id)).all()]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if any(result[key] for key in (
        "executions_without_version", "answers_without_version_question",
        "queued_questions_without_version", "open_migration_issues",
    )) else 0)
