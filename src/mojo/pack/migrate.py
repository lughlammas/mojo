"""Migração explícita v0.1 -> v0.2 do manifesto (função pura, não muta a entrada)."""
from __future__ import annotations

import copy


def migrate_0_1_to_0_2(doc: dict) -> dict:
    """Um .mjo v0.1 (aventura textual) vira um manifesto v0.2 kind='text-adventure'.

    Nada é perdido: só se acrescenta `kind`, `engine` e troca `schema_version`. Cenas, regras e textos ficam intactos.
    O mundo continua jogável pelo motor v0.1 (`mojo play`), que valida o conteúdo com o schema 0.1 original.
    """
    out = copy.deepcopy(doc)
    out["schema_version"] = "0.2.0"
    out.setdefault("kind", "text-adventure")
    out.setdefault("engine", {"profile": "turn-text-v0", "min_mojo": "0.2.0"})
    return out


def downgrade_to_0_1(doc: dict) -> dict:
    """Inverso (usado só em testes/validação): remove o que a migração acrescentou."""
    out = copy.deepcopy(doc)
    out["schema_version"] = "0.1.0"
    out.pop("kind", None)
    out.pop("engine", None)
    return out
