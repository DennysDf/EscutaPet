@echo off
setlocal EnableExtensions
title EscutaPet - Preparar banco para producao
cd /d "%~dp0"

echo =====================================================
echo  ESCUTAPET - LIMPEZA SEGURA PARA PRODUCAO
echo =====================================================
echo.
echo Antes de continuar, feche o START.bat, o worker e o
echo Gerenciador EscutaPet. Isso evita que novas mensagens
echo sejam gravadas enquanto a limpeza e executada.
echo.
echo Serao apagados: leads, pets, conversas, mensagens,
echo respostas, agendamentos, filas, alertas, webhooks,
echo sessoes de coleta e midias baixadas.
echo.
echo Serao preservados: usuarios, configuracoes, logos,
echo Z-API, cidades, dispositivos, segmentos, questionarios
echo e fluxos/jornadas.
echo.
echo Um backup do banco e das midias sera criado em backups\.
echo.
set /p CONFIRMACAO=Digite APAGAR para confirmar a limpeza: 
if /I not "%CONFIRMACAO%"=="APAGAR" goto :cancelado

if not exist "%~dp0tools\production_clean.ps1" goto :script_missing

echo.
echo Executando limpeza com backup...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\production_clean.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
  echo SISTEMA PREPARADO PARA PRODUCAO.
) else (
  echo A limpeza nao foi concluida. Nenhum arquivo de midia foi apagado se o banco falhou.
)
goto :finish

:script_missing
echo ERRO: tools\production_clean.ps1 nao foi encontrado.
set "RESULT=2"
goto :finish

:cancelado
echo.
echo Limpeza cancelada. Nenhum dado foi alterado.
set "RESULT=0"

:finish
echo.
pause
exit /b %RESULT%
