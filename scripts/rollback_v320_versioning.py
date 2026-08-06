from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import update

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app.config import settings
from app.database import SessionLocal
from app.models import EntryFlowAction


parser = argparse.ArgumentParser(description="Prepara rollback lógico da 3.2.0 sem apagar snapshots históricos.")
parser.add_argument("--confirm", action="store_true", help="Confirma a alteração das ações para 'mais recente'.")
args = parser.parse_args()
if not args.confirm:
    print("Nada alterado. Execute novamente com --confirm.")
    raise SystemExit(2)

database_url = settings.database_url
if database_url.startswith("sqlite:///"):
    database_path = Path(database_url.removeprefix("sqlite:///")).resolve()
    if database_path.exists():
        backup = database_path.with_name(f"{database_path.stem}.antes_rollback_320_{datetime.now():%Y%m%d_%H%M%S}{database_path.suffix}")
        shutil.copy2(database_path, backup)
        print(f"Backup criado: {backup}")

with SessionLocal() as db:
    db.execute(update(EntryFlowAction).values(version_mode="latest_published", fixed_version_id=None))
    db.commit()

print("Rollback lógico preparado. Snapshots e vínculos das execuções foram preservados para uma volta segura à 3.2.0.")
