"""Renderização de textos de log/narração a partir de modelos do tema (assets/theme.json). Substituição segura de {campo}."""
from __future__ import annotations

import re

_PH = re.compile(r"\{([a-z_]+)\}")


def render(template: str, ev: dict, pack, vars: dict) -> str:
    def sub(m):
        k = m.group(1)
        if k == "type_name":
            td = pack.types.get(ev.get("type", ""))
            return td.name if td else str(ev.get("type", ""))
        if k == "faction_name":
            f = pack.factions.get(ev.get("faction", ""))
            return f["name"] if f else str(ev.get("faction", ""))
        if k in ev:
            return str(ev[k])
        if k in vars:
            return str(vars[k])
        return ""
    return _PH.sub(sub, template)[:300]
