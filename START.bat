@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" call INSTALAR.bat
if errorlevel 1 exit /b 1
if not exist ".env" copy /Y ".env.example" ".env" >nul
set "REDIS_FOUND="
for /r "tools\redis" %%F in (redis-server.exe) do if exist "%%F" set "REDIS_FOUND=1"
if not defined REDIS_FOUND call "tools\redis\INSTALAR_REDIS.bat"
echo Iniciando EscutaPet 3.6.0...
echo Esta janela monitora o servidor, a fila e a transcricao.
.venv\Scripts\python.exe launcher.py
