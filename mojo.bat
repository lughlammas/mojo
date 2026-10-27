@echo off
rem Atalho: roda o MOJO a partir do checkout (sem instalar o pacote). Requer: pip install jsonschema
rem NAO TESTADO no Windows (a box e Linux).
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%src;%PYTHONPATH%"
set "PYTHONUTF8=1"
if exist "%HERE%.venv\Scripts\python.exe" ( "%HERE%.venv\Scripts\python.exe" -m mojo %* ) else ( py -3 -m mojo %* )
