"""Validação de caminhos relativos vindos de .mjo (dados NÃO confiáveis).

Regras (ADR-008): somente caminho relativo, separador '/', sem '..', sem drive,
sem UNC, sem nomes reservados do Windows, sem bytes de controle, sem streams
alternativos (':'), tamanho limitado e, ao resolver, o resultado deve ficar
dentro da raiz (inclusive após seguir symlinks).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

MAX_PATH_LEN = 200
MAX_PARTS = 12
_WIN_RESERVED = {
    "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
}
_PART_RE = re.compile(r"^[A-Za-z0-9._-][A-Za-z0-9._ -]*$")


class PathError(ValueError):
    """Caminho inseguro ou inválido."""


def check_relative_path(rel: object) -> str:
    """Valida estaticamente e devolve o caminho normalizado (com '/')."""
    if not isinstance(rel, str):
        raise PathError("caminho deve ser texto")
    if not rel or len(rel) > MAX_PATH_LEN:
        raise PathError(f"tamanho inválido (1..{MAX_PATH_LEN})")
    if unicodedata.normalize("NFC", rel) != rel:
        raise PathError("use texto Unicode normalizado (NFC)")
    if any(ord(c) < 32 or ord(c) == 127 for c in rel):
        raise PathError("caracteres de controle não permitidos")
    if "\\" in rel:
        raise PathError("use '/' como separador; '\\' não é permitido")
    if rel.startswith("/") or rel.startswith("~"):
        raise PathError("caminho absoluto não permitido")
    if ":" in rel:
        raise PathError("':' não permitido (drive/stream alternativo)")
    parts = rel.split("/")
    if len(parts) > MAX_PARTS:
        raise PathError("caminho profundo demais")
    for part in parts:
        if part in ("", ".", ".."):
            raise PathError(f"segmento não permitido: {part!r}")
        if part.endswith((".", " ")):
            raise PathError(f"segmento não permitido no Windows: {part!r}")
        if not _PART_RE.match(part):
            raise PathError(f"caracteres não permitidos em {part!r}")
        if part.split(".")[0].lower() in _WIN_RESERVED:
            raise PathError(f"nome reservado do Windows: {part!r}")
    return "/".join(parts)


def resolve_inside(root: Path, rel: object) -> Path:
    """Valida e resolve `rel` sob `root`; recusa fugas (inclusive via symlink)."""
    norm = check_relative_path(rel)
    root_r = root.resolve()
    target = (root_r / norm).resolve()
    try:
        target.relative_to(root_r)
    except ValueError as exc:
        raise PathError("caminho resolve para fora da raiz do mundo") from exc
    return target
