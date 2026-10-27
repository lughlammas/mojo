"""Carregador e validador de arquivos .mjo (JSON UTF-8, somente dados)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .migrations import VersionError, ensure_supported, parse_version
from .paths import PathError, check_relative_path

MAX_FILE_BYTES = 1_000_000
MAX_DEPTH = 24
EXPECTED_FORMAT = "dream-fabrics/mojo-world"


class WorldError(Exception):
    """Mundo .mjo inválido. `errors` traz todas as mensagens (legíveis)."""

    def __init__(self, source: str, errors: list[str]):
        self.source = source
        self.errors = errors
        super().__init__(self.format())

    def format(self) -> str:
        head = f"Mundo inválido ({self.source}):"
        return head + "".join(f"\n  - {e}" for e in self.errors)


@dataclass
class World:
    data: dict
    sha256: str
    source: str
    root: Path | None = None
    scenes: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def title(self) -> str:
        return self.data["title"]

    @property
    def allowed_actions(self) -> list[str]:
        return self.data["rules"]["allowed_actions"]

    @property
    def allowed_events(self) -> list[str]:
        return self.data["rules"].get("allowed_events", ["set_flag"])

    @property
    def canon(self) -> bool:
        # Ausência de meta.canon => tratado como não declarado (não canônico por segurança).
        return bool(self.data.get("meta", {}).get("canon", False))


@lru_cache(maxsize=1)
def load_schema() -> dict:
    text = resources.files("mojo.world").joinpath("mojo-world-0.1.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def _reject_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"chave duplicada {k!r}")
        out[k] = v
    return out


def _reject_const(name):
    raise ValueError(f"valor não permitido em JSON: {name}")


def _depth(obj, limit=MAX_DEPTH) -> int:
    stack = [(obj, 1)]
    mx = 1
    while stack:
        cur, d = stack.pop()
        mx = max(mx, d)
        if mx > limit:
            return mx
        if isinstance(cur, dict):
            stack.extend((v, d + 1) for v in cur.values())
        elif isinstance(cur, list):
            stack.extend((v, d + 1) for v in cur)
    return mx


def _jpath(err) -> str:
    parts = ""
    for p in err.absolute_path:
        parts += f"[{p}]" if isinstance(p, int) else f".{p}"
    return parts.lstrip(".") or "(raiz)"


def _schema_errors(doc: dict) -> list[str]:
    from jsonschema import Draft202012Validator

    v = Draft202012Validator(load_schema())
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path]):
        msg = e.message
        if e.validator == "additionalProperties":
            extra = sorted(set(e.instance) - set(e.schema.get("properties", {})))
            msg = "campo desconhecido: " + ", ".join(repr(x) for x in extra)
        elif e.validator == "required":
            msg = "campo obrigatório ausente: " + msg.split(" is a required")[0]
        elif e.validator == "pattern":
            msg = f"formato inválido ({msg[:80]})"
        elif len(msg) > 160:
            msg = msg[:157] + "..."
        out.append(f"{_jpath(e)}: {msg}")
    return out


def _semantic_errors(doc: dict) -> list[str]:
    errs: list[str] = []
    w = doc["world"]
    scenes = w["scenes"]
    ids = [s["id"] for s in scenes]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errs.append(f"world.scenes: id de cena duplicado {dup!r}")
    idset = set(ids)
    if w["starting_scene"] not in idset:
        errs.append(f"world.starting_scene: cena {w['starting_scene']!r} não existe")
    for si, s in enumerate(scenes):
        base = f"world.scenes[{si}]"
        exit_ids = [x["id"] for x in s.get("exits", [])]
        for dup in sorted({i for i in exit_ids if exit_ids.count(i) > 1}):
            errs.append(f"{base}.exits: id de saída duplicado {dup!r}")
        for xi, x in enumerate(s.get("exits", [])):
            if x["to"] not in idset:
                errs.append(f"{base}.exits[{xi}].to: cena {x['to']!r} não existe")
        ent_ids = [e["id"] for e in s.get("entities", [])]
        for dup in sorted({i for i in ent_ids if ent_ids.count(i) > 1}):
            errs.append(f"{base}.entities: id de entidade duplicado {dup!r}")
        for ei, e in enumerate(s.get("entities", [])):
            if e.get("speak_reply") and not e.get("speakable"):
                errs.append(f"{base}.entities[{ei}].speak_reply: exige speakable=true")
    p = doc["rules"]["player"]
    if p["hp"] > p["max_hp"]:
        errs.append("rules.player.hp: não pode exceder max_hp")
    for ri, r in enumerate(doc.get("resources", [])):
        try:
            check_relative_path(r["path"])
        except PathError as exc:
            errs.append(f"resources[{ri}].path: caminho inseguro ({exc})")
    rid = [r["id"] for r in doc.get("resources", [])]
    for dup in sorted({i for i in rid if rid.count(i) > 1}):
        errs.append(f"resources: id duplicado {dup!r}")
    return errs


def validate_document(doc: object, source: str = "<memória>", *, sha256: str = "", root: Path | None = None,
                      migrations: dict | None = None) -> World:
    """Valida um documento já decodificado. Levanta WorldError com todas as mensagens."""
    if not isinstance(doc, dict):
        raise WorldError(source, ["a raiz do arquivo deve ser um objeto JSON"])
    if _depth(doc) > MAX_DEPTH:
        raise WorldError(source, [f"JSON aninhado demais (máximo {MAX_DEPTH} níveis)"])
    if doc.get("format") != EXPECTED_FORMAT:
        raise WorldError(source, [f"format: esperado {EXPECTED_FORMAT!r}, encontrado {doc.get('format')!r} "
                                  "(isto não é um mundo MOJO .mjo)"])
    try:
        parse_version(doc.get("schema_version"))
        doc = ensure_supported(doc, migrations)
    except VersionError as exc:
        raise WorldError(source, [f"schema_version: {exc}"]) from None
    errs = _schema_errors(doc)
    if not errs:
        errs = _semantic_errors(doc)
    if errs:
        raise WorldError(source, errs)
    if not sha256:
        sha256 = hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    scenes = {s["id"]: s for s in doc["world"]["scenes"]}
    return World(data=doc, sha256=sha256, source=source, root=root, scenes=scenes)


def load_world(path: str | Path, *, migrations: dict | None = None) -> World:
    """Lê, decodifica e valida um arquivo .mjo."""
    p = Path(path)
    src = p.name
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise WorldError(src, [f"não foi possível abrir o arquivo: {exc.strerror or exc}"]) from None
    if not p.is_file():
        raise WorldError(src, ["o caminho não é um arquivo"])
    if size > MAX_FILE_BYTES:
        raise WorldError(src, [f"arquivo grande demais ({size} bytes; máximo {MAX_FILE_BYTES})"])
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorldError(src, [f"o arquivo não é UTF-8 válido (byte {exc.start})"]) from None
    try:
        doc = json.loads(text, object_pairs_hook=_reject_dupes, parse_constant=_reject_const)
    except json.JSONDecodeError as exc:
        raise WorldError(src, [f"JSON malformado na linha {exc.lineno}, coluna {exc.colno}: {exc.msg}"]) from None
    except RecursionError:
        raise WorldError(src, ["JSON aninhado demais"]) from None
    except ValueError as exc:
        raise WorldError(src, [f"JSON inválido: {exc}"]) from None
    return validate_document(doc, src, sha256=hashlib.sha256(raw).hexdigest(), root=p.resolve().parent,
                             migrations=migrations)
