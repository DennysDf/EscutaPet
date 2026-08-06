@echo off
setlocal EnableExtensions
title EscutaPet - Gerar Gerenciador EXE
cd /d "%~dp0"

echo =====================================================
echo  ESCUTAPET - GERAR GERENCIADOR.EXE
echo =====================================================
echo.
echo A compilacao sera executada pelo PowerShell.
echo Esta janela permanecera aberta ao terminar.
echo.

if not exist "%~dp0build_exe.ps1" goto :missing_script

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
set "BUILD_RESULT=%ERRORLEVEL%"
goto :finish

:missing_script
echo ERRO: tools\server_manager\build_exe.ps1 nao foi encontrado.
set "BUILD_RESULT=2"

:finish
echo.
if "%BUILD_RESULT%"=="0" (
  echo BUILD CONCLUIDO COM SUCESSO.
) else (
  echo BUILD NAO CONCLUIDO. Codigo: %BUILD_RESULT%
  echo Consulte o arquivo build\ultimo_build.log.
)
echo.
if not defined ESCUTAPET_BUILD_PARENT pause
exit /b %BUILD_RESULT%
