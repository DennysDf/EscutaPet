@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" call INSTALAR.bat
.venv\Scripts\python.exe worker.py
pause
