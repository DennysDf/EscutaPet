from __future__ import annotations

import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from app.config import settings
from app.services.bootstrap import initialize_database

PROJECT_DIR = Path(__file__).resolve().parent
STOPPING = False
REDIS_PROCESS: subprocess.Popen | None = None
TRANSCRIPTION_PROCESS: subprocess.Popen | None = None


def _command(script: str) -> list[str]:
    return [sys.executable, str(PROJECT_DIR / script)]


def _start(script: str) -> subprocess.Popen:
    return subprocess.Popen(_command(script), cwd=PROJECT_DIR)


def _stop(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()


def _signal_handler(_signum, _frame) -> None:
    global STOPPING
    STOPPING = True


def _redis_ping() -> bool:
    if not settings.redis_enabled:
        return False
    try:
        import redis

        return bool(redis.Redis.from_url(settings.redis_url, socket_connect_timeout=.35, socket_timeout=.5).ping())
    except Exception:
        return False


def _start_optional_redis() -> subprocess.Popen | None:
    if not settings.redis_enabled:
        print("Redis opcional desativado por REDIS_ENABLED=0.")
        return None
    if _redis_ping():
        print("Redis online; usando a instancia que ja estava em execucao.")
        return None
    redis_dir = PROJECT_DIR / "tools" / "redis"
    candidates = list(redis_dir.rglob("redis-server.exe")) if redis_dir.exists() else []
    if not candidates:
        print("Redis opcional nao encontrado em tools\\redis; iniciando sem cache.")
        return None
    executable = candidates[0]
    config = redis_dir / "escutapet.conf"
    command = [str(executable), str(config)] if config.exists() else [str(executable), "--bind", "127.0.0.1", "--port", "6379", "--save", ""]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(command, cwd=executable.parent, creationflags=flags)
        for _ in range(20):
            if process.poll() is not None:
                break
            if _redis_ping():
                print("Redis 8.10.0 online em 127.0.0.1:6379 (cache opcional).")
                return process
            time.sleep(.15)
    except Exception as exc:
        print(f"Redis opcional indisponivel ({exc}); iniciando sem cache.")
        return None
    _stop(process)
    print("Redis nao respondeu a tempo; iniciando sem cache.")
    return None


def main() -> int:
    global STOPPING, REDIS_PROCESS, TRANSCRIPTION_PROCESS
    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    REDIS_PROCESS = _start_optional_redis()
    initialize_database()
    server = _start("run.py")
    worker = _start("worker.py")
    TRANSCRIPTION_PROCESS = _start("transcription_worker.py")
    address = f"http://127.0.0.1:{settings.port}"
    print(f"EscutaPet 3.6.0 iniciado em {address}")
    print("Servidor, worker principal e transcrição estão sendo monitorados. Pressione Ctrl+C para encerrar.")
    if "--no-browser" not in sys.argv:
        time.sleep(1.5)
        webbrowser.open(address)

    try:
        while not STOPPING:
            if server.poll() is not None:
                print("O servidor parou; reiniciando em 2 segundos...")
                time.sleep(2)
                server = _start("run.py")
            if worker.poll() is not None:
                print("O worker parou; reiniciando em 2 segundos...")
                time.sleep(2)
                worker = _start("worker.py")
            if TRANSCRIPTION_PROCESS.poll() is not None:
                print("O worker de transcricao parou; reiniciando em 2 segundos...")
                time.sleep(2)
                TRANSCRIPTION_PROCESS = _start("transcription_worker.py")
            time.sleep(1)
    finally:
        STOPPING = True
        _stop(worker)
        _stop(TRANSCRIPTION_PROCESS)
        _stop(server)
        _stop(REDIS_PROCESS)
        print("EscutaPet encerrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
