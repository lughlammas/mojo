"""Versionamento e migrações explícitas do schema .mjo (ADR-009).

Política v0.x: a série 0.x ainda pode quebrar entre minors, então só aceitamos
exatamente major.minor == SUPPORTED, qualquer patch. Versões mais antigas só são
aceitas se houver uma migração registrada; mais novas são rejeitadas.
"""
from __future__ import annotations

import re
from typing import Callable

SUPPORTED = (0, 1)
_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# (major, minor) de origem -> função(doc)->doc na versão (major, minor+1) ou destino.
# Vazio de propósito: não existe versão anterior publicada do formato.
MIGRATIONS: dict[tuple[int, int], Callable[[dict], dict]] = {}


class VersionError(ValueError):
    pass


def parse_version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not (m := _VER_RE.match(value)):
        raise VersionError(f"schema_version inválida: {value!r} (esperado 'MAJOR.MINOR.PATCH')")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def ensure_supported(doc: dict, migrations: dict | None = None) -> dict:
    """Devolve o doc na versão suportada (migrando se houver caminho) ou levanta VersionError."""
    migs = MIGRATIONS if migrations is None else migrations
    major, minor, _ = parse_version(doc.get("schema_version"))
    cur = (major, minor)
    seen = 0
    while cur != SUPPORTED:
        if cur > SUPPORTED:
            raise VersionError(
                f"arquivo na versão {doc['schema_version']} é mais novo que o suportado "
                f"({SUPPORTED[0]}.{SUPPORTED[1]}.x); atualize o MOJO")
        fn = migs.get(cur)
        if fn is None:
            raise VersionError(
                f"versão {doc['schema_version']} incompatível: não há migração de "
                f"{cur[0]}.{cur[1]}.x para {SUPPORTED[0]}.{SUPPORTED[1]}.x")
        doc = fn(dict(doc))
        major, minor, _ = parse_version(doc.get("schema_version"))
        if (major, minor) == cur:
            raise VersionError("migração não avançou a versão")
        cur = (major, minor)
        seen += 1
        if seen > 20:
            raise VersionError("cadeia de migração longa demais")
    return doc
