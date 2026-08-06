from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MANAGER_DIR = ROOT / "tools" / "server_manager"


def check(value, message):
    if not value:
        raise AssertionError(message)


spec = importlib.util.spec_from_file_location("escutapet_server_manager", MANAGER_DIR / "escutapet_server_manager.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)

check(module.APP_VERSION == "3.6.0", "versão do gerenciador incorreta")
check(module.is_project_root(ROOT), "raiz do EscutaPet não foi reconhecida")
check(module.candidate_root() == ROOT, "descoberta automática da raiz falhou")
check(module.current_icon(ROOT) == ROOT / "app" / "static" / "img" / "pwa-512.png", "fallback do ícone padrão falhou")

with tempfile.TemporaryDirectory(prefix="escutapet_manager_") as directory:
    project = Path(directory)
    (project / "app" / "data" / "branding").mkdir(parents=True)
    (project / "app" / "static" / "img").mkdir(parents=True)
    for name in ("launcher.py", "run.py", "worker.py", "requirements.txt"):
        (project / name).write_text("", encoding="utf-8")
    custom = project / "app" / "data" / "branding" / "pwa-512.png"
    fallback = project / "app" / "static" / "img" / "pwa-512.png"
    Image.new("RGBA", (512, 512), "#0f766e").save(custom)
    Image.new("RGBA", (512, 512), "#2563eb").save(fallback)
    check(module.current_icon(project) == custom, "ícone configurado não teve prioridade")
    manager = module.ServerManager(project)
    manager.config["port"] = 8123
    manager.config["redis_enabled"] = False
    manager.save_config()
    restored = module.ServerManager(project)
    check(restored.config["port"] == 8123 and not restored.config["redis_enabled"], "configuração persistente falhou")
    check(restored.environment()["PORT"] == "8123" and restored.environment()["REDIS_ENABLED"] == "0", "ambiente do launcher incorreto")

source = (MANAGER_DIR / "escutapet_server_manager.py").read_text(encoding="utf-8")
for marker in ("launcher.py", "--no-browser", "/api/health", "taskkill", '"/T"', '"/F"', "pystray", "EscutaPet_Gerenciador"):
    check(marker in source, f"recurso do gerenciador ausente: {marker}")
check("netstat" not in source and "_pids_by_port" not in source, "gerenciador ainda pode encerrar processo desconhecido pela porta")

build = (MANAGER_DIR / "BUILD_EXE.bat").read_text(encoding="utf-8")
powershell = (MANAGER_DIR / "build_exe.ps1").read_text(encoding="utf-8")
for marker in ("powershell.exe", "build_exe.ps1", "BUILD_RESULT", "pause"):
    check(marker in build, f"lançador de build ausente: {marker}")
for marker in (".build-venv", "ultimo_build.log", "Start-Transcript", "prepare_windows_icon.py", "--onefile", "--windowed", "--icon", "--version-file", "EscutaPet_Gerenciador"):
    check(marker in powershell, f"configuração de build ausente: {marker}")
check((ROOT / "BUILD_GERENCIADOR_EXE.bat").is_file() and (ROOT / "ABRIR_GERENCIADOR.bat").is_file(), "atalhos principais ausentes")

print("OK - EscutaPet 3.5.7: gerenciador, segurança por PID, build isolado e ícone configurável validados.")
