"""Empacota o MOJO V2: /workspace/mojo/mojo-v2-0.2.zip (fonte, sem venv) e /workspace/mojo-dist/MOJO-V2-Windows.zip (instalador).
Uso: python tools/package_v2.py [--wheels /caminho/com/rodas-windows]"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT.parent / "mojo-dist"
EXCLUDE_DIRS = {".venv", ".mojo", "__pycache__", ".git", ".pytest_cache", "dist", "build", "node_modules"}
EXCLUDE_FILES = {"mojo-0.1.zip", "mojo-v2-0.2.zip"}
EXCLUDE_SUFFIX = (".pyc", ".tmp", ".egg-info")
CRLF = (".bat", ".txt")


def keep(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS or part.endswith(".egg-info") for part in rel.parts):
        return False
    return p.is_file() and p.name not in EXCLUDE_FILES and not p.name.endswith(EXCLUDE_SUFFIX)


def files():
    return sorted(p for p in ROOT.rglob("*") if keep(p))


def data(p: Path) -> bytes:
    b = p.read_bytes()
    if p.suffix in CRLF:
        b = b.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return b


def zinfo(name: str) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, date_time=(2026, 10, 27, 20, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    return zi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheels", default=None)
    a = ap.parse_args()
    fs = files()

    src_zip = ROOT / "mojo-v2-0.2.zip"
    with zipfile.ZipFile(src_zip, "w") as z:
        for p in fs:
            z.writestr(zinfo("mojo-v2-0.2/" + p.relative_to(ROOT).as_posix()), data(p))
    print(src_zip, src_zip.stat().st_size, "bytes,", len(fs), "arquivos")

    DIST.mkdir(exist_ok=True)
    out = DIST / "MOJO-V2-Windows.zip"
    top = "MOJO-V2-Windows/"
    leia = (ROOT / "tools" / "LEIA-ME-V2.txt").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zinfo(top + "INSTALAR-V2.bat"), data(ROOT / "INSTALAR-V2.bat"))
        z.writestr(zinfo(top + "LEIA-ME-V2.txt"), leia)
        for p in fs:
            if p.name == "INSTALAR-V2.bat":
                continue
            z.writestr(zinfo(top + "app/" + p.relative_to(ROOT).as_posix()), data(p))
        n = 0
        if a.wheels:
            for w in sorted(Path(a.wheels).glob("*.whl")):
                z.writestr(zinfo(top + "wheels/" + w.name), w.read_bytes())
                n += 1
    print(out, out.stat().st_size, "bytes,", len(fs), "arquivos do app,", n, "rodas")


if __name__ == "__main__":
    sys.exit(main())
