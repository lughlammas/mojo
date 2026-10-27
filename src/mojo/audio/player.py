"""Reprodução local opcional de um arquivo do cache do MOJO (nunca de caminho vindo de .mjo)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def play_file(path: str | Path, cache_dir: str | Path) -> tuple[bool, str]:
    p = Path(path).resolve()
    root = Path(cache_dir).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return False, "recusado: arquivo fora do cache de áudio"
    if not p.is_file() or p.suffix.lower() != ".wav":
        return False, "arquivo de áudio inexistente"
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]  # NÃO testado (sem Windows na box)
            return True, "enviado ao player padrão do Windows"
        cands = (["afplay"] if sys.platform == "darwin" else []) + ["paplay", "aplay", "ffplay", "xdg-open"]
        for exe in cands:
            full = shutil.which(exe)
            if full:
                args = [full] + (["-nodisp", "-autoexit", "-loglevel", "quiet"] if exe == "ffplay" else []) + [str(p)]
                subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"reproduzindo via {exe}"
    except OSError as exc:
        return False, f"falha ao reproduzir: {exc}"
    return False, "nenhum player de áudio encontrado"
