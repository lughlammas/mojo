"""Carregador estrito de pacotes MOJO V2: world.mjo + partes JSON em pastas locais (resources/ factions/ rules/ scenarios/ assets/).

Pipeline (tudo ANTES do primeiro tick): leitura estrita (UTF-8, sem duplicatas, sem NaN/float, profundidade e tamanho
limitados) -> schema JSON (additionalProperties:false) -> caminhos seguros (resolve_inside) -> referências cruzadas ->
compilação das regras de cada cenário (whitelist de operadores, tipos, limites).
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib import resources as _res
from pathlib import Path

from ..world.loader import MAX_DEPTH, MAX_FILE_BYTES, WorldError, _depth, _reject_const, _reject_dupes
from ..world.paths import PathError, resolve_inside
from .compile import CompileError, compile_scenario
from .migrate import migrate_0_1_to_0_2  # noqa: F401  (reexport)
from .model import INTERNAL_STREAMS, Pack, TypeDef

MAX_FILES = 200
MAX_PACK_BYTES = 8_000_000
GROUPS = ("resources", "factions", "rules", "scenarios")
PART_KIND = {"resources": "resources", "factions": "faction", "rules": "rules", "scenarios": "scenario"}


class PackError(WorldError):
    """Pacote inválido (mesma classe-base do v0.1: o CLI já sabe imprimir)."""

    def format(self) -> str:
        return f"Pacote inválido ({self.source}):" + "".join(f"\n  - {e}" for e in self.errors)


@lru_cache(maxsize=4)
def _schema(name: str) -> dict:
    return json.loads(_res.files("mojo.pack").joinpath("schemas", name).read_text(encoding="utf-8"))


def _reject_float(s):
    raise ValueError(f"número não inteiro não permitido ({s}); use inteiros (permille, ticks)")


def read_json_strict(path: Path, src: str) -> tuple[dict, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PackError(src, [f"não foi possível abrir: {exc.strerror or exc}"]) from None
    if not path.is_file():
        raise PackError(src, ["o caminho não é um arquivo"])
    if size > MAX_FILE_BYTES:
        raise PackError(src, [f"arquivo grande demais ({size} bytes; máximo {MAX_FILE_BYTES})"])
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PackError(src, [f"não é UTF-8 válido (byte {exc.start})"]) from None
    try:
        doc = json.loads(text, object_pairs_hook=_reject_dupes, parse_constant=_reject_const, parse_float=_reject_float)
    except json.JSONDecodeError as exc:
        raise PackError(src, [f"JSON malformado na linha {exc.lineno}, coluna {exc.colno}: {exc.msg}"]) from None
    except RecursionError:
        raise PackError(src, ["JSON aninhado demais"]) from None
    except ValueError as exc:
        raise PackError(src, [f"JSON inválido: {exc}"]) from None
    if not isinstance(doc, dict):
        raise PackError(src, ["a raiz deve ser um objeto JSON"])
    if _depth(doc) > MAX_DEPTH:
        raise PackError(src, [f"JSON aninhado demais (máximo {MAX_DEPTH} níveis)"])
    return doc, hashlib.sha256(raw).hexdigest()


def _jpath(err) -> str:
    out = ""
    for p in err.absolute_path:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out.lstrip(".") or "(raiz)"


def schema_errors(doc: dict, schema_name: str) -> list[str]:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import best_match

    v = Draft202012Validator(_schema(schema_name))
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path]):
        if e.context:
            e = best_match(e.context) or e
        msg = e.message
        if e.validator == "additionalProperties":
            extra = sorted(set(e.instance) - set(e.schema.get("properties", {})))
            msg = "campo desconhecido: " + ", ".join(repr(x) for x in extra)
        elif e.validator == "required":
            msg = "campo obrigatório ausente: " + msg.split(" is a required")[0]
        elif len(msg) > 160:
            msg = msg[:157] + "..."
        out.append(f"{_jpath(e)}: {msg}")
    return out


def _td(fid: str, kind: str, d: dict) -> TypeDef:
    atk = d.get("attack")
    g = d.get("gather")
    return TypeDef(
        id=d["id"], kind=kind, faction=fid, name=d["name"], tags=frozenset(d["tags"]), hp=d["hp"],
        size=d.get("size", 1) if kind == "s" else 1, speed_ticks=d.get("speed_ticks", 1),
        cost=tuple(sorted(d["cost"].items())), build_ticks=d["build_ticks"], er=d.get("entropy_resist", 0),
        gather=(g["resource"], g["amount"], g["cooldown_ticks"]) if g else None,
        attack=(atk["damage"], atk["range"], atk["cooldown_ticks"], atk["damage_kind"]) if atk else None,
        abilities=tuple(d.get("abilities", ())), produces=tuple(d.get("produces", ())),
        provides=tuple(sorted(d.get("provides", {}).items())), builds=tuple(d.get("builds", ())),
        upkeep=tuple(sorted(d.get("upkeep", {}).items())))


def load_pack(path: str | Path) -> Pack:
    p = Path(path)
    root = p.parent if p.is_file() else p
    manifest_path = p if p.is_file() else p / "world.mjo"
    src = str(root.name or root)
    doc, sha0 = read_json_strict(manifest_path, f"{src}/world.mjo")
    if doc.get("format") != "dream-fabrics/mojo-world":
        raise PackError(src, [f"format: esperado 'dream-fabrics/mojo-world', encontrado {doc.get('format')!r}"])
    ver = str(doc.get("schema_version", ""))
    if ver.startswith("0.1."):
        raise PackError(src, ["mundo v0.1 (aventura textual): use `mojo play <arquivo.mjo>`; "
                              "a migração para 0.2 está em mojo.pack.migrate.migrate_0_1_to_0_2"])
    errs = schema_errors(doc, "mojo-world-0.2.schema.json")
    if errs:
        raise PackError(f"{src}/world.mjo", errs)
    if doc["kind"] != "rts-grid":
        raise PackError(src, [f"kind {doc['kind']!r} não é servível pelo perfil tick-grid-v0 (use `mojo play`)"])
    if doc["engine"]["profile"] != "tick-grid-v0":
        raise PackError(src, [f"engine.profile {doc['engine']['profile']!r} não suportado (tick-grid-v0)"])
    if doc.get("mods"):
        raise PackError(src, ["mods ainda não são suportados nesta versão (previsto para fase futura); deixe `mods` vazio"])

    errs = []
    files: dict[str, str] = {"world.mjo": sha0}
    total = 0
    parts: dict[str, list] = {g: [] for g in GROUPS}
    n_files = 0

    def load_part(rel: str, kind: str):
        nonlocal total, n_files
        try:
            fp = resolve_inside(root, rel)
        except PathError as e:
            errs.append(f"{rel}: caminho inseguro ({e})")
            return None
        n_files += 1
        if n_files > MAX_FILES:
            errs.append("arquivos demais no pacote"); return None
        d, sha = read_json_strict(fp, rel)
        total += fp.stat().st_size
        files[rel] = sha
        e2 = schema_errors(d, "mojo-part-0.2.schema.json")
        if e2:
            errs.extend(f"{rel}: {m}" for m in e2)
            return None
        if d["kind"] != kind:
            errs.append(f"{rel}: kind {d['kind']!r} não confere com o grupo ({kind!r})")
            return None
        return d

    for g in GROUPS:
        seen = set()
        for rel in doc.get("includes", {}).get(g, []):
            try:
                d = load_part(rel, PART_KIND[g])
            except PackError as e:
                errs.extend(e.errors and [f"{rel}: {m}" for m in e.errors]); d = None
            if d is None:
                continue
            if d["id"] in seen:
                errs.append(f"{rel}: id {d['id']!r} duplicado no grupo {g}")
            seen.add(d["id"])
            parts[g].append((rel, d))
    theme = {}
    if doc.get("ui", {}).get("theme"):
        try:
            d = load_part(doc["ui"]["theme"], "theme")
            theme = d or {}
        except PackError as e:
            errs.extend(e.errors)
    if total > MAX_PACK_BYTES:
        errs.append(f"pacote grande demais ({total} bytes)")
    if errs:
        raise PackError(src, errs)

    # ---- recursos ----
    resources: dict = {}
    for rel, d in parts["resources"]:
        for r in d["resources"]:
            if r["id"] in resources:
                errs.append(f"{rel}: recurso {r['id']!r} duplicado")
            resources[r["id"]] = r
    plain = {r for r, d in resources.items() if not d.get("derived")}
    derived = set(resources) - plain
    # ---- facções/tipos ----
    factions, types, statuses = {}, {}, {}
    for rel, d in parts["factions"]:
        fid = d["id"]
        factions[fid] = d
        for kind, key in (("u", "units"), ("s", "structures")):
            for t in d[key]:
                if t["id"] in types or t["id"] in resources:
                    errs.append(f"{rel}: id de tipo {t['id']!r} duplicado")
                types[t["id"]] = _td(fid, kind, t)
        for s in d.get("statuses", []):
            if s["id"] in statuses:
                errs.append(f"{rel}: status {s['id']!r} duplicado")
            statuses[s["id"]] = {"ticks": s["ticks"], "modifiers": s["modifiers"]}
    for fid, d in factions.items():
        base = f"faction {fid}"
        for k in d["start"]["resources"]:
            if k not in plain:
                errs.append(f"{base}: start.resources usa recurso inexistente/derivado {k!r}")
    for t in types.values():
        base = f"{t.faction}.{t.id}"
        for k, _ in t.cost:
            if k not in plain:
                errs.append(f"{base}: cost usa recurso inexistente/derivado {k!r}")
        for k, _ in t.provides:
            if k not in resources:
                errs.append(f"{base}: provides usa recurso inexistente {k!r}")
        for k, _ in t.upkeep:
            if k not in derived:
                errs.append(f"{base}: upkeep exige recurso derivado, recebido {k!r}")
        if t.gather and (t.gather[0] not in plain or not resources[t.gather[0]].get("gatherable")):
            errs.append(f"{base}: gather.resource {t.gather[0]!r} não é coletável")
        if t.kind == "s" and (t.speed_ticks or t.gather or t.attack):
            pass
        for u in t.produces:
            ut = types.get(u)
            if ut is None or ut.kind != "u" or ut.faction != t.faction:
                errs.append(f"{base}: produces {u!r} não é unidade da mesma facção")
        for s in t.builds:
            st = types.get(s)
            if st is None or st.kind != "s" or st.faction != t.faction:
                errs.append(f"{base}: builds {s!r} não é estrutura da mesma facção")
        if t.kind == "u" and t.builds and not t.gather and False:
            pass
        for ab in t.abilities:
            if t.kind != "u":
                errs.append(f"{base}: habilidades só em unidades")
    for fid, d in factions.items():
        ids = [s["id"] for s in d.get("ai_scripts", [])]
        if len(set(ids)) != len(ids):
            errs.append(f"faction {fid}: ai_scripts com ids repetidos")
    # ---- regras / vars ----
    pvars, streams = {}, set(INTERNAL_STREAMS)
    rules = []
    for rel, d in parts["rules"]:
        for n, v in d.get("vars", {}).items():
            if n in pvars:
                errs.append(f"{rel}: var {n!r} duplicada")
            if not (v["min"] <= v["init"] <= v["max"]):
                errs.append(f"{rel}: var {n!r} init fora de [min,max]")
            pvars[n] = v
        streams |= set(d.get("rng_streams", []))
        rules.extend((rel, r) for r in d["rules"])
    for fid, d in factions.items():
        rules.extend((f"factions/{fid}", r) for r in d.get("rules", []))
    scenarios = {d["id"]: d for _, d in parts["scenarios"]}
    if not scenarios:
        errs.append("includes.scenarios: o pacote precisa de ao menos um cenário")
    if doc.get("default_scenario") and doc["default_scenario"] not in scenarios:
        errs.append(f"default_scenario {doc['default_scenario']!r} inexistente")
    if errs:
        raise PackError(src, errs)
    h = hashlib.sha256()
    for k in sorted(files):
        h.update(f"{k}:{files[k]}\n".encode())
    pack = Pack(root=root.resolve(), manifest=doc, resources=resources, factions=factions, types=types,
                statuses=statuses, rules=rules, vars=pvars, streams=sorted(streams), scenarios=scenarios,
                theme=theme, sha256=h.hexdigest(), files=files)
    all_errs = []
    for sid in scenarios:
        try:
            pack.compiled[sid] = compile_scenario(pack, sid)
        except CompileError as e:
            all_errs.extend(e.errors)
    if all_errs:
        raise PackError(src, all_errs)
    return pack
