import json, sys
sys.path.insert(0, ".")
from jsonschema import Draft202012Validator
from mojo_v2.pack.migrate import migrate_0_1_to_0_2
az = json.load(open("../../../examples/azrael.mjo", encoding="utf-8"))
new = migrate_0_1_to_0_2(az)
ws = json.load(open("../schema/mojo-world-0.2.schema.json", encoding="utf-8"))
errs = [e.message for e in Draft202012Validator(ws).iter_errors(new)]
assert not errs, errs
assert az["schema_version"] == "0.1.0", "entrada não pode ser mutada"
assert {k: v for k, v in new.items() if k not in ("schema_version", "kind", "engine")} == {k: v for k, v in az.items() if k != "schema_version"}
print("azrael.mjo v0.1 -> v0.2: manifesto válido no schema 0.2; conteúdo preservado; entrada intacta; campos acrescentados:", sorted(set(new) - set(az)))
