from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env(PROJECT_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").lower() in {"1", "true", "yes", "sim", "on"}


def _secret_key() -> str:
    value = os.getenv("SECRET_KEY", "").strip()
    if value and value != "troque-por-uma-chave-com-pelo-menos-32-caracteres" and len(value) >= 32:
        return value
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / ".session_secret"
    if key_file.exists():
        current = key_file.read_text(encoding="utf-8").strip()
        if len(current) >= 32:
            return current
    generated = secrets.token_urlsafe(48)
    key_file.write_text(generated, encoding="utf-8")
    return generated


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "EscutaPet Inteligente")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8040"))
    secret_key: str = _secret_key()
    session_hours: int = int(os.getenv("SESSION_HOURS", "12"))
    session_https_only: bool = _bool("SESSION_HTTPS_ONLY", False)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    database_url: str = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{(BASE_DIR / 'data' / 'escutapet_v2.sqlite3').as_posix()}"
    auto_seed_demo: bool = _bool("AUTO_SEED_DEMO", True)
    worker_poll_seconds: int = max(1, int(os.getenv("WORKER_POLL_SECONDS", "3")))
    redis_enabled: bool = _bool("REDIS_ENABLED", True)
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0").strip()
    redis_prefix: str = os.getenv("REDIS_PREFIX", "escutapet").strip() or "escutapet"


settings = Settings()
