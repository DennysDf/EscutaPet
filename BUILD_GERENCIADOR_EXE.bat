@echo off
setlocal EnableExtensions
title EscutaPet - Gerar Gerenciador EXE
cd /d "%~dp0"
set "BUILD_SCRIPT=%~dp0tools\server_manager\BUILD_EXE.bat"

echo Abrindo o compilador do Gerenciador EscutaPet...
echo.
if not exist "%BUILD_SCRIPT%" goto :missing

set "ESCUTAPET_BUILD_PARENT=1"
call "%BUILD_SCRIPT%"
set "BUILD_RESULT=%ERRORLEVEL%"
goto :finish

:missing
echo ERRO: %BUILD_SCRIPT% nao foi encontrado.
set "BUILD_RESULT=2"

:finish
echo.
if "%BUILD_RESULT%"=="0" (
  echo O executavel foi gerado na pasta principal.
) else (
  echo A compilacao terminou com erro %BUILD_RESULT%.
  echo Veja tools\server_manager\build\ultimo_build.log.
)
echo.
echo Pressione qualquer tecla para fechar esta janela.
pause >nul
exit /b %BUILD_RESULT%
