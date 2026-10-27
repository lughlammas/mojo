"""Verificador DESCARTÁVEL do exemplo da proposta V2: schemas (jsonschema) + paths do v0.1 + referências cruzadas + whitelist de expressões.
Uso (da raiz do repo):  PYTHONPATH=src:docs/v2/bench python docs/v2/bench/check_example.py [--self-test]
Não faz parte do MOJO v0.1; é o protótipo do que seria `mojo validate` na V2."""
from __future__ import annotations

import copy, json, sys
from pathlib import Path

from jsonschema import Draft202012Validator

from expr_proto import Env, ExprError, check_rule
from mojo.world.paths import PathError, resolve_inside

ROOT = Path(__file__).resolve().parents[1]
EX = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else ROOT / "example" / "elemental-proto")
WS = json.loads((ROOT / "schema" / "mojo-world-0.2.schema.json").read_text(encoding="utf-8"))
PS = json.loads((ROOT / "schema" / "mojo-part-0.2.schema.json").read_text(encoding="utf-8"))


def strict_json(path: Path):
    def hook(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError(f"chave duplicada {k!r} em {path.name}")
            d[k] = v
        return d
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook,
                      parse_constant=lambda n: (_ for _ in ()).throw(ValueError(f"constante proibida {n}")))


def schema_errs(schema, doc, name):
    return [f"{name}: {'.'.join(map(str, e.absolute_path)) or '(raiz)'}: {e.message[:140]}"
            for e in Draft202012Validator(schema).iter_errors(doc)]


def load_pack(root: Path, manifest_override=None, part_override=None):
    errs = []
    man = manifest_override or strict_json(root / "world.mjo")
    errs += schema_errs(WS, man, "world.mjo")
    if errs:
        return errs, None
    parts = {k: [] for k in ("resources", "factions", "rules", "scenarios")}
    for kind, paths in man.get("includes", {}).items():
        for rel in paths:
            try:
                p = resolve_inside(root, rel)
            except PathError as exc:
                errs.append(f"includes.{kind}: {rel!r}: caminho inseguro ({exc})")
                continue
            if not p.is_file() or p.stat().st_size > 256_000:
                errs.append(f"includes.{kind}: {rel!r}: arquivo ausente ou grande demais")
                continue
            doc = (part_override or {}).get(rel) or strict_json(p)
            errs += schema_errs(PS, doc, rel)
            parts[kind].append((rel, doc))
    if errs:
        return errs, None
    # --- referências cruzadas ---
    res_ids = {r["id"] for _, d in parts["resources"] for r in d["resources"]}
    facs = {d["id"]: d for _, d in parts["factions"]}
    ctx = {"factions": set(facs), "unit_types": {u["id"] for f in facs.values() for u in f["units"]},
           "all_types": {x["id"] for f in facs.values() for x in f["units"] + f["structures"]},
           "statuses": {s["id"] for f in facs.values() for s in f.get("statuses", [])}}
    vars_, streams = set(), set()
    for _, d in parts["rules"]:
        vars_ |= set(d.get("vars", {}))
        streams |= set(d.get("rng_streams", []))
    for rel, f in parts["factions"]:
        types = {x["id"] for x in f["units"] + f["structures"]}
        for s in f["start"]["structures"] + f["start"]["units"]:
            if s["type"] not in types:
                errs.append(f"{rel}: start referencia tipo inexistente {s['type']!r}")
        for st in f["structures"]:
            for u in st.get("produces", []):
                if u not in {x["id"] for x in f["units"]}:
                    errs.append(f"{rel}: {st['id']}.produces referencia unidade inexistente {u!r}")
        for x in f["units"] + f["structures"]:
            for r in list(x.get("cost", {})) + ([x["gather"]["resource"]] if "gather" in x else []):
                if r not in res_ids:
                    errs.append(f"{rel}: {x['id']}: recurso inexistente {r!r}")
        if not any("core" in s["tags"] for s in f["structures"]):
            errs.append(f"{rel}: facção sem estrutura com tag 'core' (derrota impossível)")
    if len({d["id"] for _, d in parts["factions"]}) != len(parts["factions"]):
        errs.append("ids de facção duplicados")
    for rel, sc in parts["scenarios"]:
        g = sc["grid"]
        if len(g["layout"]) != g["height"] or any(len(r) != g["width"] for r in g["layout"]):
            errs.append(f"{rel}: layout não bate com width/height")
        used = set("".join(g["layout"]))
        if used - set(g["legend"]):
            errs.append(f"{rel}: caracteres sem legenda: {sorted(used - set(g['legend']))}")
        spawns = {v.split(":")[1] for v in g["legend"].values() if v.startswith("spawn:")}
        teams = {t["id"] for t in sc["teams"]}
        for p in sc["players"]:
            if p["faction"] not in facs:
                errs.append(f"{rel}: jogador {p['slot']}: facção {p['faction']!r} inexistente")
            if p["team"] not in teams:
                errs.append(f"{rel}: jogador {p['slot']}: time inexistente")
            if p["spawn"] not in spawns:
                errs.append(f"{rel}: jogador {p['slot']}: spawn {p['spawn']!r} sem legenda")
        if sc["mode"] not in man.get("modes", {}):
            errs.append(f"{rel}: mode {sc['mode']!r} não declarado em world.modes")
        mm = man["modes"].get(sc["mode"], {})
        if not (mm.get("min_players", 1) <= len(sc["players"]) <= mm.get("max_players", 8)):
            errs.append(f"{rel}: nº de jogadores fora dos limites do modo")
    # --- regras / expressões ---
    for sc_rel, sc in parts["scenarios"]:
        base = dict(vars=vars_, params=set(sc["params"]), resources=res_ids, streams=streams)
        rules = [(rel, r) for rel, d in parts["rules"] for r in d["rules"]] + \
                [(rel, r) for rel, f in parts["factions"] for r in f.get("rules", [])]
        for rel, r in rules:
            try:
                check_rule(r, base, ctx)
            except ExprError as exc:
                errs.append(f"{rel} (cenário {sc['id']}): {exc}")
        for rel, f in parts["factions"]:
            for u in f["units"]:
                for ab in u.get("abilities", []):
                    for ef in ab["do"]:
                        try:
                            from expr_proto import check_effect
                            check_effect(ef, Env(scope="entity", **base), ctx)
                        except ExprError as exc:
                            errs.append(f"{rel}: habilidade {ab['id']}: {exc}")
    errs = sorted(set(errs))
    return errs, (man, parts)


def main():
    errs, pack = load_pack(EX)
    for e in errs:
        print("ERRO:", e)
    if errs:
        return 1
    man, parts = pack
    n_rules = sum(len(d["rules"]) for _, d in parts["rules"]) + sum(len(f.get("rules", [])) for _, f in parts["factions"])
    print(f"OK: {man['id']} v{man['schema_version']} | partes={sum(len(v) for v in parts.values())} | facções={[d['id'] for _, d in parts['factions']]} "
          f"| cenários={[d['id'] for _, d in parts['scenarios']]} | regras compiladas={n_rules}")
    if "--self-test" not in sys.argv:
        return 0
    man0 = strict_json(EX / "world.mjo")
    def part_of(rel): return copy.deepcopy(strict_json(EX / rel))
    cases = {}
    m = copy.deepcopy(man0); m["includes"]["rules"].append("../../etc/passwd"); cases["include com .."] = (m, None)
    m = copy.deepcopy(man0); m["includes"]["rules"].append("C:/Windows/x.json"); cases["include absoluto/drive"] = (m, None)
    m = copy.deepcopy(man0); m["includes"]["rules"].append("rules\\x.json"); cases["include com barra invertida"] = (m, None)
    m = copy.deepcopy(man0); m["includes"]["rules"].append("rules/ausente.json"); cases["include inexistente"] = (m, None)
    m = copy.deepcopy(man0); m["schema_version"] = "0.3.0"; cases["versão futura"] = (m, None)
    def bad_rule(mut):
        d = part_of("rules/entropy.json"); mut(d); return {"rules/entropy.json": d}
    cases["operador fora da whitelist (eval)"] = (None, bad_rule(lambda d: d["rules"][0]["do"][0].update(amount={"eval": "__import__('os')"})))
    cases["float proibido"] = (None, bad_rule(lambda d: d["rules"][0]["do"][0].update(amount=1.5)))
    cases["var não declarada"] = (None, bad_rule(lambda d: d["rules"][0]["do"][0].update(var="gold")))
    cases["op de efeito inexistente"] = (None, bad_rule(lambda d: d["rules"][0]["do"].append({"op": "exec", "cmd": "calc"})))
    def deep(d):
        e = 1
        for _ in range(12): e = {"add": [e, 1]}
        d["rules"][0]["do"][0]["amount"] = e
    cases["expressão profunda (bomba)"] = (None, bad_rule(deep))
    cases["rand_below sem stream"] = (None, bad_rule(lambda d: d["rules"][1]["do"][2].update(value={"rand_below": ["ghost", 5]})))
    cases["self.* fora de for=entity"] = (None, bad_rule(lambda d: d["rules"][0].update(when={"gt": [{"ref": "self.hp"}, 1]})))
    cases["campo desconhecido no manifesto"] = ({**copy.deepcopy(man0), "script": "rm -rf /"}, None)
    ok = True
    for name, (mo, po) in cases.items():
        e, _ = load_pack(EX, manifest_override=mo, part_override=po)
        print(f"  [{'rejeitado' if e else 'ACEITO (BUG)'}] {name}" + (f" -> {e[0][:110]}" if e else ""))
        ok &= bool(e)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
