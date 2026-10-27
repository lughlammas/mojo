"""Migração v0.1 -> v0.2 (função pura; entra em mojo/world/migrations.py: MIGRATIONS[(0, 1)] = migrate_0_1_to_0_2)."""
from __future__ import annotations


def migrate_0_1_to_0_2(doc: dict) -> dict:
    """Um .mjo v0.1 (aventura textual) vira um manifesto v0.2 kind='text-adventure'. Nada é perdido; só se acrescenta.
    Regras: não muda ids, cenas, regras nem textos; só rotula o perfil de execução e a versão mínima do motor."""
    out = dict(doc)
    out["schema_version"] = "0.2.0"
    out.setdefault("kind", "text-adventure")
    out.setdefault("engine", {"profile": "turn-text-v0", "min_mojo": "2.0.0"})
    return out
