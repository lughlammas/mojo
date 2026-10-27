"""Interpretação determinística de comandos do jogador (sem modelo)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

GAME_VERBS = {
    "look": ("look", "l", "olhar", "ver"),
    "inspect": ("inspect", "examine", "x", "inspecionar", "examinar"),
    "speak": ("speak", "say", "talk", "falar", "dizer"),
    "go": ("go", "ir", "mover"),
}
META_VERBS = {
    "help": ("help", "?", "ajuda"),
    "state": ("state", "estado"),
    "log": ("log",),
    "save": ("save", "salvar"),
    "load": ("load", "carregar"),
    "audio": ("audio", "áudio"),
    "quit": ("quit", "exit", "sair"),
}
_ALIAS = {a: ("game", v) for v, al in GAME_VERBS.items() for a in al}
_ALIAS.update({a: ("meta", v) for v, al in META_VERBS.items() for a in al})
MAX_INPUT = 500


@dataclass
class Command:
    kind: str      # game | meta | unknown | empty
    verb: str
    arg: str
    raw: str


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.casefold()).strip()


def parse_command(line: str) -> Command:
    raw = "".join(c for c in line if c == "\t" or ord(c) >= 32 and ord(c) != 127).strip()[:MAX_INPUT]
    if not raw:
        return Command("empty", "", "", raw)
    head, _, rest = raw.partition(" ")
    kind_verb = _ALIAS.get(head.casefold())
    if not kind_verb:
        return Command("unknown", head, rest.strip(), raw)
    arg = rest.strip()
    if kind_verb[1] == "speak" and len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'":
        arg = arg[1:-1].strip()
    return Command(kind_verb[0], kind_verb[1], arg, raw)


def resolve_entity(entities: list, query: str):
    """Devolve (entidade|None, erro|None). Compara por id, nome e aliases, sem acentos."""
    q = norm(query)
    if not q:
        return None, "empty"
    keys = lambda e: [norm(e["id"]), norm(e["name"])] + [norm(a) for a in e.get("aliases", [])]
    exact = [e for e in entities if q in keys(e)]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, "ambiguous"
    part = [e for e in entities if any(re.search(rf"\b{re.escape(q)}\b", k) for k in keys(e))]
    if len(part) == 1:
        return part[0], None
    return None, ("ambiguous" if part else "unknown")


def resolve_exit(exits: list, query: str):
    q = norm(query)
    if not q:
        return None, "empty"
    ex = [x for x in exits if q in (norm(x["id"]), norm(x["label"]))]
    if not ex:
        ex = [x for x in exits if re.search(rf"\b{re.escape(q)}\b", norm(x["label"]))]
    if len(ex) == 1:
        return ex[0], None
    return None, ("ambiguous" if ex else "unknown")
