@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" call INSTALAR.bat
if not exist ".env" copy /Y ".env.example" ".env" >nul
.venv\Scripts\python.exe launcher.py
