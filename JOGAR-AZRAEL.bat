@echo off
rem Joga o v0.1 (texto) sem precisar do mojo.exe do venv. NAO TESTADO no Windows.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call "%~dp0mojo-v2.bat" play examples\azrael.mjo %*
pause
