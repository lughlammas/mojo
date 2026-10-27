@echo off
setlocal enableextensions
chcp 65001 >nul
rem ============================================================================
rem  Instalador do MOJO V2 (Dream Fabrics) -- NAO TESTADO no Windows (a box e Linux).
rem  - Reutiliza o venv do v0.1 em C:\MOJO\mojo\.venv se existir; senao cria um.
rem  - Instala so: fastapi, uvicorn, websockets, jsonschema (nada de servico externo).
rem  - Tenta primeiro as rodas offline da pasta "wheels" ao lado deste arquivo; se falhar, usa a internet (pip).
rem  - Nao mexe em mojo.config.json, saves nem na pasta .mojo existentes.
rem ============================================================================
set "DEST=C:\MOJO\mojo"
set "HERE=%~dp0"
echo === Instalador do MOJO V2 (Dream Fabrics) ===
echo Destino: %DEST%
echo.

if not exist "%HERE%app\src\mojo\cli_v2.py" (
  echo ERRO: pasta "app" nao encontrada ao lado do instalador. Extraia o ZIP inteiro antes de rodar.
  goto erro
)

if not exist "%DEST%" mkdir "%DEST%"
echo Copiando arquivos para %DEST% (o venv e seus saves nao sao apagados)...
xcopy /E /I /Y "%HERE%app" "%DEST%" >nul
if errorlevel 1 goto erro

set "VPY=%DEST%\.venv\Scripts\python.exe"
if exist "%VPY%" (
  echo Venv existente encontrado: %DEST%\.venv  ^(sera reutilizado^)
  goto deps
)

echo Criando venv...
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY ( where py >nul 2>nul && set "PY=py -3" )
if not defined PY (
  echo Python 3.11+ nao encontrado. Instalando Python 3.12 para o seu usuario via winget...
  winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
%PY% -m venv "%DEST%\.venv"
if errorlevel 1 goto erro

:deps
echo.
echo Instalando dependencias do V2...
set "OFFLINE_OK="
if exist "%HERE%wheels" (
  "%VPY%" -m pip install --no-index --find-links "%HERE%wheels" fastapi uvicorn websockets jsonschema colorama
  if not errorlevel 1 set "OFFLINE_OK=1"
)
if not defined OFFLINE_OK (
  echo Rodas offline indisponiveis ou incompativeis com este Python; usando a internet ^(pip^)...
  "%VPY%" -m pip install --upgrade fastapi uvicorn websockets jsonschema
  if errorlevel 1 goto erro
)

rem Registra o pacote (opcional: o mojo-v2.bat funciona mesmo sem isso, via PYTHONPATH).
"%VPY%" -m pip install -q -e "%DEST%" --no-deps >nul 2>nul

echo.
echo Verificando a instalacao...
set "PYTHONPATH=%DEST%\src"
set "PYTHONUTF8=1"
"%VPY%" -m mojo validate "%DEST%\examples\azrael.mjo" || goto erro
"%VPY%" -m mojo pack-validate "%DEST%\packs\poc-mini" || goto erro
"%VPY%" -m mojo pack-validate "%DEST%\packs\elemental-proto" || goto erro
"%VPY%" -m mojo simulate "%DEST%\packs\poc-mini" --scenario mini --ticks 400 || goto erro

echo.
echo ============================================================
echo  MOJO V2 instalado em %DEST%
echo  Para jogar (abre o navegador):  %DEST%\SERVIR.bat
echo  Outro pacote:  %DEST%\SERVIR.bat packs\elemental-proto
echo  v0.1 (texto):  %DEST%\JOGAR-AZRAEL.bat   ^(continua igual^)
echo  Leia: %DEST%\README-V2.md
echo ============================================================
pause
exit /b 0

:erro
echo.
echo ERRO na instalacao. Veja as mensagens acima. Nada foi apagado em %DEST%.
pause
exit /b 1
