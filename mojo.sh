#!/usr/bin/env bash
# Atalho: roda o MOJO a partir do checkout (sem instalar o pacote). Requer: pip install jsonschema
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/.venv/bin/python"; [ -x "$PY" ] || PY=python3
PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}" PYTHONUTF8=1 exec "$PY" -m mojo "$@"
