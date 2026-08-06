@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" goto :dependencias
where py >nul 2>&1
if errorlevel 1 (
  echo Python nao encontrado. Instale Python 3.11 ou superior e marque Add Python to PATH.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual...
  py -3 -m venv .venv
  if errorlevel 1 goto :erro
)
:dependencias
echo Atualizando instalador de pacotes...
.venv\Scripts\python.exe -m pip install --upgrade pip
echo Instalando dependencias...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :erro
echo Preparando Redis opcional...
call "tools\redis\INSTALAR_REDIS.bat"
echo.
echo Instalacao concluida.
exit /b 0
:erro
echo.
echo Falha na instalacao. Verifique a conexao e a versao do Python.
pause
exit /b 1
