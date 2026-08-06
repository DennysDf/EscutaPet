"""Preparação segura do EscutaPet para o primeiro uso em produção.

O script preserva configurações, usuários, cidades, dispositivos, segmentos,
questionários e jornadas. Ele remove somente os registros operacionais já
coletados e cria um backup antes de qualquer alteração.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import PROJECT_DIR, settings
from app.database import SessionLocal, engine
from app.models import (
    Alert,
    AuditLog,
    CollectionPet,
    CollectionSession,
    ConsentReceipt,
    Conversation,
    ConversationDraft,
    ConversationMessage,
    ConversationNote,
    ConversationReaction,
    EditorDraft,
    EditorSubmission,
    Lead,
    LeadSegment,
    MediaAsset,
    MessageQueue,
    Pet,
    PhoneVerification,
    SegmentEvent,
    SurveyAnswer,
    SurveyExecution,
    TranscriptionJob,
    WebhookEvent,
    WorkerState,
)


OPERATIONAL_MODELS = (
    EditorSubmission,
    EditorDraft,
    TranscriptionJob,
    ConversationReaction,
    ConversationDraft,
    ConversationNote,
    PhoneVerification,
    MessageQueue,
    MediaAsset,
    ConversationMessage,
    Conversation,
    Alert,
    SurveyAnswer,
    SurveyExecution,
    ConsentReceipt,
    CollectionPet,
    CollectionSession,
    SegmentEvent,
    LeadSegment,
    Pet,
    WebhookEvent,
    AuditLog,
    WorkerState,
    Lead,
)


def _sqlite_database_path() -> Path | None:
    if not settings.database_url.startswith("sqlite:///"):
        return None
    return Path(settings.database_url.removeprefix("sqlite:///"))


def _backup_database(destination: Path) -> Path:
    sqlite_path = _sqlite_database_path()
    if sqlite_path is not None:
        if not sqlite_path.exists():
            raise RuntimeError(f"Banco SQLite não encontrado: {sqlite_path}")
        target = destination / sqlite_path.name
        with engine.connect() as connection:
            connection.execute(text("PRAGMA wal_checkpoint(FULL)"))
        shutil.copy2(sqlite_path, target)
        return target

    url = make_url(settings.database_url)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("A limpeza segura suporta SQLite e PostgreSQL.")
    target = destination / "escutapet_antes_limpeza.dump"
    pg_url = url.set(drivername="postgresql", password=None).render_as_string(hide_password=False)
    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    try:
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(target), pg_url],
            check=True,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("pg_dump não foi encontrado. Instale o PostgreSQL Client ou ajuste o PATH antes de limpar.") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or "").strip().splitlines()[-1:] or ["falha desconhecida"]
        raise RuntimeError(f"Não foi possível criar o backup PostgreSQL: {message[0]}") from exc
    return target


def _backup_media(destination: Path) -> int:
    media_dir = PROJECT_DIR / "app" / "data" / "media"
    if not media_dir.exists():
        return 0
    media_backup = destination / "media"
    shutil.copytree(media_dir, media_backup)
    return sum(1 for item in media_backup.rglob("*") if item.is_file())


def _clear_media() -> int:
    media_dir = PROJECT_DIR / "app" / "data" / "media"
    if not media_dir.exists():
        return 0
    removed = 0
    for item in media_dir.iterdir():
        if item.is_dir():
            removed += sum(1 for child in item.rglob("*") if child.is_file())
            shutil.rmtree(item)
        elif item.is_file():
            item.unlink()
            removed += 1
    return removed


def _counts(db) -> dict[str, int]:
    rows = {
        "Leads": Lead,
        "Pets": Pet,
        "Conversas": Conversation,
        "Mensagens": ConversationMessage,
        "Respostas": SurveyAnswer,
        "Pesquisas/agendamentos": SurveyExecution,
        "Fila de mensagens": MessageQueue,
        "Sessões de coleta": CollectionSession,
        "Mídias": MediaAsset,
    }
    return {label: int(db.scalar(select(func.count()).select_from(model)) or 0) for label, model in rows.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove dados operacionais do EscutaPet, preservando a configuração.")
    parser.add_argument("--confirm", default="", help="Use APAGAR para liberar a limpeza.")
    args = parser.parse_args()
    if args.confirm != "APAGAR":
        print("Proteção ativa: nada foi alterado. Use --confirm APAGAR somente pelo BAT oficial.")
        return 2

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT_DIR / "backups" / f"antes_limpeza_producao_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    db = SessionLocal()
    try:
        before = _counts(db)
        backup_database = _backup_database(backup_dir)
        backup_media_count = _backup_media(backup_dir)
        print(f"Backup do banco criado: {backup_database}")
        print(f"Backup de mídias criado: {backup_media_count} arquivo(s)")

        removed: dict[str, int] = {}
        for model in OPERATIONAL_MODELS:
            result = db.execute(delete(model))
            removed[model.__tablename__] = max(0, int(result.rowcount or 0))
        db.commit()
        media_removed = _clear_media()

        after = _counts(db)
        print("\nLIMPEZA CONCLUÍDA COM SUCESSO")
        print(f"Backup completo: {backup_dir}")
        print(f"Linhas operacionais removidas: {sum(removed.values())}")
        print(f"Arquivos de mídia removidos: {media_removed}")
        for label, amount in before.items():
            print(f"- {label}: {amount} -> {after[label]}")
        print("\nPreservados: usuários, configurações, logos, Z-API, cidades, pontos/dispositivos,")
        print("segmentos e regras, questionários, versões, perguntas, fluxos e jornadas.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERRO: a limpeza não foi concluída: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
