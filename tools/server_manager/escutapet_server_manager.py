# -*- coding: utf-8 -*-
"""Gerenciador gráfico do EscutaPet para Windows.

Controla o launcher oficial, que por sua vez supervisiona FastAPI/Uvicorn,
worker principal, transcrição e Redis opcional. O processo só encerra a árvore
iniciada por este gerenciador; nunca mata outro programa apenas pela porta.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from tkinter import filedialog, messagebox, ttk
from typing import Callable

try:
    import winreg
except Exception:
    winreg = None


APP_TITLE = "EscutaPet · Gerenciador do Servidor"
APP_VERSION = "3.6.0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8040
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
SW_HIDE = 0


def hidden_startupinfo():
    if os.name != "nt":
        return None
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= STARTF_USESHOWWINDOW
    startup.wShowWindow = SW_HIDE
    return startup


def is_project_root(path: pathlib.Path) -> bool:
    return (
        (path / "launcher.py").is_file()
        and (path / "run.py").is_file()
        and (path / "worker.py").is_file()
        and (path / "requirements.txt").is_file()
        and (path / "app").is_dir()
    )


def candidate_root() -> pathlib.Path:
    here = pathlib.Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    candidates = [here, *list(here.parents)[:5], pathlib.Path.cwd()]
    for candidate in candidates:
        if is_project_root(candidate):
            return candidate.resolve()
    return pathlib.Path.cwd().resolve()


def icon_candidates(root: pathlib.Path) -> list[pathlib.Path]:
    branding = root / "app" / "data" / "branding"
    candidates = [
        branding / "pwa-512.png",
        branding / "icon-preview.png",
        branding / "favicon.png",
    ]
    for extension in (".png", ".jpg", ".jpeg", ".webp"):
        candidates.append(branding / f"icon{extension}")
    candidates.append(root / "app" / "static" / "img" / "pwa-512.png")
    return candidates


def current_icon(root: pathlib.Path) -> pathlib.Path | None:
    return next((item for item in icon_candidates(root) if item.is_file()), None)


def local_ipv4() -> str:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
        probe.close()
        return address
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


class ServerManager:
    def __init__(self, root: pathlib.Path):
        self.root = root.resolve()
        self.state_dir = self.root / "app" / "data" / "server_manager"
        self.logs_dir = self.root / "app" / "data" / "logs"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.state_dir / "config.json"
        self.pid_file = self.state_dir / "launcher.pid"
        self.server_log = self.logs_dir / "escutapet_manager.log"
        self.config = self.load_config()

    @property
    def venv_python(self) -> pathlib.Path:
        return self.root / ".venv" / "Scripts" / "python.exe"

    def load_config(self) -> dict:
        config = {
            "host": DEFAULT_HOST,
            "port": DEFAULT_PORT,
            "auto_open_browser": True,
            "auto_start_on_open": False,
            "auto_start_with_windows": False,
            "redis_enabled": True,
        }
        try:
            if self.config_file.is_file():
                loaded = json.loads(self.config_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config.update(loaded)
        except (OSError, ValueError, TypeError):
            pass
        return config

    def save_config(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")

    def environment(self) -> dict:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["HOST"] = str(self.config.get("host") or DEFAULT_HOST)
        env["PORT"] = str(int(self.config.get("port") or DEFAULT_PORT))
        env["REDIS_ENABLED"] = "1" if self.config.get("redis_enabled", True) else "0"
        return env

    def run_stream(self, command: list[str], callback: Callable[[str], None]) -> int:
        callback("\n> " + " ".join(f'"{part}"' if " " in part else part for part in command) + "\n")
        process = subprocess.Popen(
            command,
            cwd=str(self.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            startupinfo=hidden_startupinfo(),
            env=self.environment(),
        )
        assert process.stdout is not None
        for line in process.stdout:
            callback(line)
        return process.wait()

    def prepare_environment(self, callback: Callable[[str], None]) -> tuple[bool, str]:
        if not is_project_root(self.root):
            return False, "Selecione a pasta que contém launcher.py, app e requirements.txt."
        installer = self.root / "INSTALAR.bat"
        if os.name == "nt" and installer.is_file():
            command = ["cmd.exe", "/d", "/s", "/c", f'call "{installer}"']
        else:
            command = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
        if self.run_stream(command, callback) != 0:
            return False, "A instalação não terminou corretamente. Confira o log acima."
        if not self.venv_python.is_file():
            return False, "O ambiente .venv não foi encontrado após a instalação."
        check = [
            str(self.venv_python),
            "-c",
            "from app.services.bootstrap import initialize_database; initialize_database(); print('Banco verificado e atualizado.')",
        ]
        if self.run_stream(check, callback) != 0:
            return False, "As dependências foram instaladas, mas a preparação do banco falhou."
        return True, "Ambiente, dependências e banco preparados."

    def health(self, timeout: float = 1.2) -> dict | None:
        port = int(self.config.get("port") or DEFAULT_PORT)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) and payload.get("ok") else None
        except (OSError, ValueError, urllib.error.URLError):
            return None

    def port_open(self, timeout: float = 0.4) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", int(self.config.get("port") or DEFAULT_PORT)), timeout=timeout):
                return True
        except OSError:
            return False

    def read_pid(self) -> int | None:
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip()) if self.pid_file.is_file() else None
        except (OSError, ValueError):
            return None

    def write_pid(self, pid: int) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(pid), encoding="utf-8")

    def remove_pid(self) -> None:
        try:
            self.pid_file.unlink(missing_ok=True)
        except OSError:
            pass

    def pid_running(self, pid: int | None = None) -> bool:
        pid = pid or self.read_pid()
        if not pid:
            return False
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=hidden_startupinfo(),
            )
            return result.returncode == 0 and str(pid) in result.stdout
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def start_server(self) -> tuple[bool, str]:
        port = int(self.config.get("port") or DEFAULT_PORT)
        if self.health():
            return True, f"EscutaPet já está respondendo na porta {port}."
        if self.port_open():
            return False, f"A porta {port} está ocupada por outro serviço. Nada foi encerrado."
        existing_pid = self.read_pid()
        if self.pid_running(existing_pid):
            return False, f"O launcher PID {existing_pid} existe, mas a aplicação ainda não respondeu. Confira o log."
        self.remove_pid()
        if not self.venv_python.is_file():
            return False, "Ambiente não preparado. Clique primeiro em Preparar/atualizar."
        if not (self.root / ".env").exists() and (self.root / ".env.example").is_file():
            (self.root / ".env").write_bytes((self.root / ".env.example").read_bytes())
        log_handle = self.server_log.open("a", encoding="utf-8", errors="replace")
        log_handle.write(f"\n\n===== EscutaPet {APP_VERSION} · iniciando {time.strftime('%d/%m/%Y %H:%M:%S')} =====\n")
        log_handle.flush()
        process = subprocess.Popen(
            [str(self.venv_python), str(self.root / "launcher.py"), "--no-browser"],
            cwd=str(self.root),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=hidden_startupinfo(),
            env=self.environment(),
        )
        log_handle.close()
        self.write_pid(process.pid)
        for _ in range(30):
            if process.poll() is not None:
                self.remove_pid()
                return False, "O launcher encerrou durante a inicialização. Confira os logs."
            if self.health(timeout=.5):
                return True, f"Servidor iniciado. PID {process.pid} · http://127.0.0.1:{port}"
            time.sleep(.5)
        return False, "O processo foi iniciado, mas a aplicação não respondeu em 15 segundos. Confira os logs."

    def stop_server(self) -> tuple[bool, str]:
        pid = self.read_pid()
        if not pid:
            if self.health():
                return False, "O servidor está online, mas não foi iniciado por este gerenciador; ele não será encerrado."
            return True, "O servidor já está parado."
        if not self.pid_running(pid):
            self.remove_pid()
            return True, "O processo registrado já estava encerrado."
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    creationflags=CREATE_NO_WINDOW,
                    startupinfo=hidden_startupinfo(),
                )
                if result.returncode != 0:
                    return False, result.stderr.strip() or "O Windows não permitiu encerrar o processo."
            else:
                os.kill(pid, 15)
            self.remove_pid()
            for _ in range(12):
                if not self.health(timeout=.25):
                    return True, "Servidor, fila, transcrição e Redis supervisionado foram encerrados."
                time.sleep(.25)
            return False, "O comando foi enviado, mas a aplicação ainda responde."
        except OSError as exc:
            return False, f"Falha ao encerrar o processo: {exc}"

    def tail_logs(self, max_chars: int = 50000) -> str:
        try:
            if not self.server_log.is_file():
                return "O log será criado quando o servidor for iniciado.\n"
            return self.server_log.read_text(encoding="utf-8", errors="replace")[-max_chars:]
        except OSError as exc:
            return f"Não foi possível ler o log: {exc}\n"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1080x760")
        self.minsize(900, 640)
        self.root_dir = tk.StringVar(value=str(candidate_root()))
        self.manager = ServerManager(pathlib.Path(self.root_dir.get()))
        self.host = tk.StringVar()
        self.port = tk.IntVar()
        self.auto_open_browser = tk.BooleanVar()
        self.auto_start_on_open = tk.BooleanVar()
        self.auto_start_with_windows = tk.BooleanVar()
        self.redis_enabled = tk.BooleanVar()
        self.server_status = tk.StringVar(value="Verificando...")
        self.database_status = tk.StringVar(value="—")
        self.redis_status = tk.StringVar(value="—")
        self.queue_status = tk.StringVar(value="—")
        self.status_detail = tk.StringVar(value="Inicializando o gerenciador...")
        self._status_after = None
        self._tray_icon = None
        self._header_image = None
        self._load_config_vars()
        self._configure_style()
        self._apply_window_icon()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_status()
        if "--minimized" in sys.argv:
            self.after(350, self.start_minimized)
        if self.auto_start_on_open.get():
            self.after(900, self.start_server)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#071a2b")
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground="#526173")
        style.configure("CardValue.TLabel", font=("Segoe UI", 14, "bold"), foreground="#0f766e")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 9))
        style.configure("Action.TButton", padding=(12, 8))

    def _load_config_vars(self) -> None:
        cfg = self.manager.config
        self.host.set(str(cfg.get("host") or DEFAULT_HOST))
        self.port.set(int(cfg.get("port") or DEFAULT_PORT))
        self.auto_open_browser.set(bool(cfg.get("auto_open_browser", True)))
        self.auto_start_on_open.set(bool(cfg.get("auto_start_on_open", False)))
        self.auto_start_with_windows.set(bool(cfg.get("auto_start_with_windows", False)))
        self.redis_enabled.set(bool(cfg.get("redis_enabled", True)))

    def _apply_window_icon(self) -> None:
        icon = current_icon(self.manager.root)
        if not icon:
            return
        try:
            from PIL import Image, ImageTk

            image = Image.open(icon).convert("RGBA")
            image.thumbnail((128, 128))
            self._header_image = ImageTk.PhotoImage(image)
            self.iconphoto(True, self._header_image)
        except Exception:
            try:
                photo = tk.PhotoImage(file=str(icon))
                self._header_image = photo
                self.iconphoto(True, photo)
            except tk.TclError:
                pass

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        if self._header_image:
            ttk.Label(header, image=self._header_image).pack(side="left", padx=(0, 12))
        copy = ttk.Frame(header)
        copy.pack(side="left", fill="x", expand=True)
        ttk.Label(copy, text="EscutaPet · Gerenciador do Servidor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(copy, text="Servidor, fila, transcrição e Redis opcional em uma única janela.", style="Subtitle.TLabel").pack(anchor="w")
        ttk.Label(header, text=f"v{APP_VERSION}", style="CardValue.TLabel").pack(side="right")

        config = ttk.LabelFrame(outer, text="Aplicação", padding=10)
        config.pack(fill="x", pady=(0, 10))
        ttk.Label(config, text="Pasta do EscutaPet").grid(row=0, column=0, sticky="w", padx=6, pady=5)
        ttk.Entry(config, textvariable=self.root_dir).grid(row=0, column=1, columnspan=4, sticky="ew", padx=6, pady=5)
        ttk.Button(config, text="Selecionar", command=self.choose_root).grid(row=0, column=5, padx=6, pady=5)
        ttk.Label(config, text="Host").grid(row=1, column=0, sticky="w", padx=6, pady=5)
        ttk.Combobox(config, textvariable=self.host, values=("0.0.0.0", "127.0.0.1"), width=14).grid(row=1, column=1, sticky="w", padx=6, pady=5)
        ttk.Label(config, text="Porta").grid(row=1, column=2, sticky="e", padx=6, pady=5)
        ttk.Spinbox(config, textvariable=self.port, from_=1024, to=65535, width=9).grid(row=1, column=3, sticky="w", padx=6, pady=5)
        ttk.Checkbutton(config, text="Usar Redis quando disponível", variable=self.redis_enabled).grid(row=1, column=4, columnspan=2, sticky="w", padx=6, pady=5)
        config.columnconfigure(1, weight=1)

        options = ttk.Frame(config)
        options.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(4, 0))
        ttk.Checkbutton(options, text="Abrir navegador ao iniciar", variable=self.auto_open_browser).pack(side="left", padx=6)
        ttk.Checkbutton(options, text="Iniciar servidor ao abrir", variable=self.auto_start_on_open).pack(side="left", padx=6)
        ttk.Checkbutton(options, text="Abrir gerenciador com o Windows", variable=self.auto_start_with_windows, command=self.toggle_windows_startup).pack(side="left", padx=6)

        cards = ttk.Frame(outer)
        cards.pack(fill="x", pady=(0, 10))
        for index, (title, variable) in enumerate((
            ("Servidor", self.server_status),
            ("Banco", self.database_status),
            ("Redis", self.redis_status),
            ("Fila", self.queue_status),
        )):
            card = ttk.LabelFrame(cards, text=title, padding=10)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0))
            ttk.Label(card, textvariable=variable, style="CardValue.TLabel").pack(anchor="w")
            cards.columnconfigure(index, weight=1)

        actions = ttk.LabelFrame(outer, text="Ações", padding=10)
        actions.pack(fill="x", pady=(0, 10))
        for index, (label, command, style) in enumerate((
            ("Preparar/atualizar", self.prepare_environment, "Primary.TButton"),
            ("Iniciar", self.start_server, "Primary.TButton"),
            ("Parar", self.stop_server, "Action.TButton"),
            ("Reiniciar", self.restart_server, "Action.TButton"),
            ("Abrir sistema", self.open_system, "Action.TButton"),
            ("Abrir na rede", self.open_network, "Action.TButton"),
            ("Atualizar logs", self.update_logs, "Action.TButton"),
            ("Abrir pasta de logs", self.open_logs_folder, "Action.TButton"),
        )):
            ttk.Button(actions, text=label, command=command, style=style).grid(row=index // 4, column=index % 4, sticky="ew", padx=5, pady=5)
        for column in range(4):
            actions.columnconfigure(column, weight=1)

        status_line = ttk.Frame(outer)
        status_line.pack(fill="x", pady=(0, 7))
        ttk.Label(status_line, textvariable=self.status_detail, style="Subtitle.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(status_line, text="Salvar configurações", command=self.save_config).pack(side="right")

        logs_frame = ttk.LabelFrame(outer, text="Logs do launcher e dos workers", padding=6)
        logs_frame.pack(fill="both", expand=True)
        self.logs = tk.Text(logs_frame, wrap="none", height=18, bg="#071a2b", fg="#dceaf2", insertbackground="white", font=("Consolas", 9), relief="flat")
        self.logs.pack(side="left", fill="both", expand=True)
        scroll_y = ttk.Scrollbar(logs_frame, orient="vertical", command=self.logs.yview)
        scroll_y.pack(side="right", fill="y")
        self.logs.configure(yscrollcommand=scroll_y.set)
        self.update_logs()

    def sync_manager(self) -> bool:
        try:
            port = int(self.port.get())
            if not 1024 <= port <= 65535:
                raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showerror(APP_TITLE, "Informe uma porta entre 1024 e 65535.")
            return False
        root = pathlib.Path(self.root_dir.get()).expanduser()
        self.manager = ServerManager(root)
        self.manager.config.update({
            "host": self.host.get().strip() or DEFAULT_HOST,
            "port": port,
            "auto_open_browser": bool(self.auto_open_browser.get()),
            "auto_start_on_open": bool(self.auto_start_on_open.get()),
            "auto_start_with_windows": bool(self.auto_start_with_windows.get()),
            "redis_enabled": bool(self.redis_enabled.get()),
        })
        self.manager.save_config()
        return True

    def append_log(self, text: str) -> None:
        def write():
            self.logs.insert(tk.END, text)
            self.logs.see(tk.END)
        self.after(0, write)

    def set_log(self, text: str) -> None:
        self.logs.delete("1.0", tk.END)
        self.logs.insert(tk.END, text)
        self.logs.see(tk.END)

    def run_background(self, function: Callable[[], tuple[bool, str]]) -> None:
        def worker():
            try:
                ok, message = function()
            except Exception as exc:
                ok, message = False, f"Erro inesperado: {exc}"
            self.append_log(("\nOK: " if ok else "\nATENÇÃO: ") + message + "\n")
            self.after(0, self.refresh_status)
        threading.Thread(target=worker, daemon=True).start()

    def prepare_environment(self) -> None:
        if not self.sync_manager():
            return
        self.set_log("Preparando o EscutaPet...\n")
        self.run_background(lambda: self.manager.prepare_environment(self.append_log))

    def start_server(self) -> None:
        if not self.sync_manager():
            return
        def start():
            result = self.manager.start_server()
            if result[0] and self.auto_open_browser.get():
                self.after(0, self.open_system)
            return result
        self.run_background(start)

    def stop_server(self) -> None:
        if self.sync_manager():
            self.run_background(self.manager.stop_server)

    def restart_server(self) -> None:
        if not self.sync_manager():
            return
        def restart():
            stopped, message = self.manager.stop_server()
            self.append_log(("\nOK: " if stopped else "\nATENÇÃO: ") + message + "\n")
            if not stopped:
                return False, "Reinício interrompido porque o servidor não pôde ser parado com segurança."
            time.sleep(.8)
            return self.manager.start_server()
        self.run_background(restart)

    def save_config(self) -> None:
        if self.sync_manager():
            self.apply_windows_startup(bool(self.auto_start_with_windows.get()))
            messagebox.showinfo(APP_TITLE, "Configurações salvas.")

    def choose_root(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta raiz do EscutaPet")
        if not selected:
            return
        self.root_dir.set(selected)
        self.manager = ServerManager(pathlib.Path(selected))
        self._load_config_vars()
        self._apply_window_icon()
        self.update_logs()
        self.refresh_status()

    def refresh_status(self) -> None:
        if self._status_after:
            try:
                self.after_cancel(self._status_after)
            except tk.TclError:
                pass
        if not self.sync_manager():
            return
        health = self.manager.health()
        port = int(self.manager.config.get("port") or DEFAULT_PORT)
        if health:
            self.server_status.set(f"Online · {health.get('version', APP_VERSION)}")
            self.database_status.set(str(health.get("database") or "online").capitalize())
            redis_data = health.get("redis") or {}
            self.redis_status.set("Online" if redis_data.get("online") else ("Opcional/offline" if self.redis_enabled.get() else "Desativado"))
            pending = int(health.get("queue_pending") or 0)
            executions = int(health.get("executions_pending") or 0)
            self.queue_status.set(f"{pending} msg · {executions} pesquisas")
            self.status_detail.set(f"Local: http://127.0.0.1:{port}  ·  Rede: http://{local_ipv4()}:{port}")
        else:
            self.server_status.set("Parado" if not self.manager.port_open() else "Porta ocupada")
            self.database_status.set("—")
            self.redis_status.set("—")
            self.queue_status.set("—")
            self.status_detail.set(f"EscutaPet não respondeu em http://127.0.0.1:{port}")
        self._status_after = self.after(5000, self.refresh_status)

    def update_logs(self) -> None:
        self.set_log(self.manager.tail_logs())

    def open_system(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{int(self.port.get())}")

    def open_network(self) -> None:
        webbrowser.open(f"http://{local_ipv4()}:{int(self.port.get())}")

    def open_logs_folder(self) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(self.manager.logs_dir))
            else:
                webbrowser.open(self.manager.logs_dir.as_uri())
        except OSError as exc:
            self.append_log(f"\nNão foi possível abrir a pasta de logs: {exc}\n")

    def startup_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        pythonw = self.manager.venv_python.with_name("pythonw.exe")
        executable = pythonw if pythonw.is_file() else pathlib.Path(sys.executable)
        return f'"{executable}" "{pathlib.Path(__file__).resolve()}" --minimized'

    def apply_windows_startup(self, enable: bool) -> None:
        if os.name != "nt" or winreg is None:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, "EscutaPet_Gerenciador", 0, winreg.REG_SZ, self.startup_command())
                else:
                    try:
                        winreg.DeleteValue(key, "EscutaPet_Gerenciador")
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            self.append_log(f"\nNão foi possível alterar a inicialização do Windows: {exc}\n")

    def toggle_windows_startup(self) -> None:
        if self.sync_manager():
            self.apply_windows_startup(bool(self.auto_start_with_windows.get()))

    def tray_image(self):
        try:
            from PIL import Image, ImageOps

            icon = current_icon(self.manager.root)
            if icon:
                image = Image.open(icon).convert("RGBA")
                return ImageOps.contain(image, (64, 64))
        except Exception:
            pass
        return None

    def try_tray(self) -> bool:
        if self._tray_icon is not None:
            return True
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return False
        image = self.tray_image()
        if image is None:
            image = Image.new("RGBA", (64, 64), "#071a2b")
            draw = ImageDraw.Draw(image)
            draw.ellipse((9, 9, 55, 55), fill="#0f766e")
            draw.text((22, 18), "E", fill="white")

        menu = pystray.Menu(
            pystray.MenuItem("Abrir gerenciador", lambda _i, _m: self.after(0, self.deiconify)),
            pystray.MenuItem("Abrir EscutaPet", lambda _i, _m: self.after(0, self.open_system)),
            pystray.MenuItem("Iniciar servidor", lambda _i, _m: self.after(0, self.start_server)),
            pystray.MenuItem("Parar servidor", lambda _i, _m: self.after(0, self.stop_server)),
            pystray.MenuItem("Sair do gerenciador", self.quit_from_tray),
        )
        self._tray_icon = pystray.Icon("escutapet_manager", image, "EscutaPet", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()
        return True

    def quit_from_tray(self, _icon=None, _item=None) -> None:
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    def start_minimized(self) -> None:
        if self.try_tray():
            self.withdraw()
        else:
            self.iconify()

    def on_close(self) -> None:
        if self.try_tray():
            self.withdraw()
            return
        if messagebox.askyesno(APP_TITLE, "Fechar o gerenciador?\n\nO servidor continuará funcionando em segundo plano."):
            self.destroy()


if __name__ == "__main__":
    App().mainloop()
