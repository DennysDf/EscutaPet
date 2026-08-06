@echo off
setlocal
cd /d "%~dp0"
if exist "EscutaPet_Gerenciador.exe" (
  start "" "EscutaPet_Gerenciador.exe"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "tools\server_manager\escutapet_server_manager.py"
  exit /b 0
)
echo O gerenciador ainda não foi compilado e o ambiente do sistema não existe.
echo Execute primeiro INSTALAR.bat e depois BUILD_GERENCIADOR_EXE.bat.
pause
exit /b 1
