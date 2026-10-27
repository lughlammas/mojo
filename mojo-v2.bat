@echo off
rem MOJO V2: roda qualquer comando do MOJO a partir deste checkout (sem "pip install" do pacote).
rem Exemplos:   mojo-v2.bat serve packs\poc-mini --open
rem             mojo-v2.bat pack-validate packs\elemental-proto
rem             mojo-v2.bat simulate packs\poc-mini --scenario ai_duel --ticks 600
rem Usa o venv do v0.1 (C:\MOJO\mojo\.venv) se existir. NAO TESTADO no Windows (a box e Linux).
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%src;%PYTHONPATH%"
set "PYTHONUTF8=1"
if exist "%HERE%.venv\Scripts\python.exe" (
  "%HERE%.venv\Scripts\python.exe" -m mojo %*
) else (
  py -3 -m mojo %*
)
endlocal
