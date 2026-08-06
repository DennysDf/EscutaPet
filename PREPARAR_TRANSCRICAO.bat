@echo off
setlocal
cd /d "%~dp0"
echo =====================================================
echo  ESCUTAPET 3.6.0 - PREPARAR TRANSCRICAO LOCAL
echo =====================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\transcription\install.ps1"
if errorlevel 1 (
  echo.
  echo A preparacao falhou. Confira a internet e a mensagem acima.
  pause
  exit /b 1
)
echo.
echo Preparacao concluida. Reinicie o EscutaPet e habilite a transcricao em Configuracoes.
pause
