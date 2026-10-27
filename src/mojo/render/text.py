"""Renderização textual (protótipo): quebra de linha simples e formatação de estado/log."""
from __future__ import annotations

import json
import textwrap


def wrap(text: str, width: int = 78) -> str:
    return "\n".join(textwrap.fill(p, width) if p.strip() else "" for p in text.split("\n"))


def render_state(game) -> str:
    s = game.state
    sc = game.world.scenes[s.scene]
    lines = [
        f"Mundo: {game.world.title}  (id={game.world.id}, canon={'sim' if game.world.canon else 'não'})",
        f"Cena: {sc.get('title', sc['id'])} [{s.scene}]   Turno: {s.turn}",
        f"HP: {s.hp}/{s.max_hp}   Inventário: {', '.join(s.inventory) or '(vazio)'}",
        "Flags: " + (json.dumps(s.flags, ensure_ascii=False, sort_keys=True) if s.flags else "(nenhuma)"),
        f"Hash do estado: {s.hash()[:16]}…",
    ]
    return "\n".join(lines)


def render_log_line(rec: dict) -> str:
    t = rec.get("type")
    hh = rec.get("t", "")[11:19] + "Z"
    if t == "turn":
        ev = rec.get("applied_events") or []
        return (f"{hh} turno {rec.get('turn')} {rec.get('outcome')}: {rec.get('input')!r}"
                f" eventos={len(ev)} hash={str(rec.get('state_hash_after', ''))[:8]}")
    if t == "audio":
        return f"{hh} áudio turno {rec.get('turn')}: {rec.get('status')} {rec.get('latency_ms')}ms {rec.get('detail', '')[:60]}"
    return f"{hh} {t}"
