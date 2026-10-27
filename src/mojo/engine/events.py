"""Validação e aplicação de eventos de estado (lista fechada — ADR-011)."""
from __future__ import annotations

from .state import FLAG_RE, ID_RE, MAX_FLAGS, GameState

EVENT_TYPES = ("set_flag", "give_item", "remove_item", "hp_delta", "move")
_FIELDS = {
    "set_flag": {"type", "flag", "value"},
    "give_item": {"type", "item"},
    "remove_item": {"type", "item"},
    "hp_delta": {"type", "amount"},
    "move": {"type", "exit"},
}
RESERVED_FLAG_PREFIXES = ("inspected:",)  # só o núcleo escreve


def requires_met(req: dict | None, state: GameState) -> bool:
    if not req:
        return True
    if "flag" in req and not state.flags.get(req["flag"]):
        return False
    if "item" in req and req["item"] not in state.inventory:
        return False
    return True


def validate_event(ev: object, state: GameState, world, *, allowed: set | None, engine: bool = False):
    """Devolve (evento_normalizado, None) ou (None, motivo). Não muta o estado."""
    if not isinstance(ev, dict):
        return None, "evento deve ser objeto"
    t = ev.get("type")
    if t not in EVENT_TYPES:
        return None, f"tipo de evento desconhecido: {str(t)[:40]!r}"
    if not engine and (allowed is None or t not in allowed):
        return None, f"evento '{t}' não permitido por este mundo"
    extra = set(ev) - _FIELDS[t]
    if extra:
        return None, f"campos desconhecidos em {t}: {sorted(map(str, extra))}"
    if t == "set_flag":
        flag = ev.get("flag")
        val = ev.get("value", True)
        if not isinstance(flag, str) or not FLAG_RE.match(flag):
            return None, "nome de flag inválido"
        if not engine and flag.startswith(RESERVED_FLAG_PREFIXES):
            return None, "prefixo de flag reservado ao núcleo"
        if isinstance(val, bool):
            pass
        elif isinstance(val, int):
            if abs(val) > 1_000_000:
                return None, "valor inteiro fora do limite"
        elif isinstance(val, str):
            if len(val) > 64:
                return None, "valor de texto longo demais"
        else:
            return None, "valor de flag deve ser bool, inteiro ou texto curto"
        if flag not in state.flags and len(state.flags) >= MAX_FLAGS:
            return None, "limite de flags atingido"
        return {"type": t, "flag": flag, "value": val}, None
    if t in ("give_item", "remove_item"):
        item = ev.get("item")
        if not isinstance(item, str) or not ID_RE.match(item):
            return None, "id de item inválido"
        if t == "give_item":
            if item in state.inventory:
                return None, "item já está no inventário"
            if len(state.inventory) >= 64:
                return None, "inventário cheio"
        elif item not in state.inventory:
            return None, "item não está no inventário"
        return {"type": t, "item": item}, None
    if t == "hp_delta":
        amt = ev.get("amount")
        if not isinstance(amt, int) or isinstance(amt, bool):
            return None, "amount deve ser inteiro"
        if abs(amt) > state.max_hp:
            return None, "variação de hp maior que max_hp"
        return {"type": t, "amount": amt}, None
    # move
    xid = ev.get("exit")
    scene = world.scenes[state.scene]
    ex = next((x for x in scene.get("exits", []) if x["id"] == xid), None) if isinstance(xid, str) else None
    if ex is None:
        return None, "saída inexistente na cena atual"
    if not requires_met(ex.get("requires"), state):
        return None, "pré-condição da saída não cumprida"
    return {"type": t, "exit": xid}, None


def apply_event(ev: dict, state: GameState, world) -> None:
    """Aplica um evento JÁ validado (muta `state`)."""
    t = ev["type"]
    if t == "set_flag":
        state.flags[ev["flag"]] = ev["value"]
    elif t == "give_item":
        state.inventory.append(ev["item"])
    elif t == "remove_item":
        state.inventory.remove(ev["item"])
    elif t == "hp_delta":
        state.hp = max(0, min(state.max_hp, state.hp + ev["amount"]))
    elif t == "move":
        ex = next(x for x in world.scenes[state.scene]["exits"] if x["id"] == ev["exit"])
        state.scene = ex["to"]
