@echo off
rem Abre o MOJO V2 no navegador (servidor local em 127.0.0.1:8770).
rem Uso: duplo clique (abre o poc-mini) ou   SERVIR.bat packs\elemental-proto [--scenario quarteto]
rem NAO TESTADO no Windows (a box e Linux).
setlocal
set "HERE=%~dp0"
cd /d "%HERE%"
if "%~1"=="" (
  call "%HERE%mojo-v2.bat" serve "%HERE%packs\poc-mini" --open
) else (
  call "%HERE%mojo-v2.bat" serve %* --open
)
if errorlevel 1 pause
endlocal
