"""Subcomandos do MOJO V2 (aditivos): serve | pack-validate | simulate | replay. Registrados por cli.build_parser()."""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

from .core.version import V2_VERSION


def register(sub) -> None:
    sv = sub.add_parser("serve", help="V2: servir um pacote de jogo (pasta com world.mjo) no navegador em 127.0.0.1")
    sv.add_argument("pack", help="pasta do pacote (ex.: packs/poc-mini)")
    sv.add_argument("--scenario", help="id do cenário (padrão: default_scenario do manifesto)")
    sv.add_argument("--seed", type=int, help="força a seed mestre (padrão: a do cenário)")
    sv.add_argument("--port", type=int, default=8770)
    sv.add_argument("--open", action="store_true", help="abre o navegador padrão")
    sv.add_argument("--lan", action="store_true", help="PERIGO: aceita Host/Origin de IP privado e escuta em 0.0.0.0 (só com esta flag)")
    sv.add_argument("--audio", choices=["auto", "off"], default="auto", help="narração por voz via Ragnarok (opcional)")
    sv.add_argument("--config")
    sv.add_argument("--home", help="pasta de replays/snapshots/cache (padrão ./.mojo ou $MOJO_HOME)")
    sv.add_argument("--no-record", action="store_true", help="não grava replay")
    sv.add_argument("--resume", metavar="SNAPSHOT.json", help="retoma de um snapshot (sem gravação de replay)")
    sv.set_defaults(fn=cmd_serve)
    pv = sub.add_parser("pack-validate", help="V2: valida um pacote (pasta) ou migra/valida um .mjo v0.1 no schema 0.2")
    pv.add_argument("path")
    pv.set_defaults(fn=cmd_pack_validate)
    si = sub.add_parser("simulate", help="V2: roda um cenário sem interface (determinismo, tempos, hash final)")
    si.add_argument("pack")
    si.add_argument("--scenario")
    si.add_argument("--seed", type=int)
    si.add_argument("--ticks", type=int, default=3000)
    si.set_defaults(fn=cmd_simulate)
    rp = sub.add_parser("replay", help="V2: reexecuta um replay (.jsonl) e verifica os hashes de checkpoint")
    rp.add_argument("file")
    rp.add_argument("--pack", help="pasta do pacote (padrão: packs/<pack_id do replay>)")
    rp.add_argument("--force", action="store_true", help="ignora diferença de sha256 do pacote")
    rp.set_defaults(fn=cmd_replay)


def cmd_pack_validate(a, path=None) -> int:
    from .pack.loader import PackError, load_pack, read_json_strict, schema_errors
    from .pack.migrate import downgrade_to_0_1, migrate_0_1_to_0_2
    from .world.loader import validate_document

    p = Path(path or a.path)
    if p.is_file() and p.suffix == ".mjo":
        doc, _ = read_json_strict(p, p.name)
        if str(doc.get("schema_version", "")).startswith("0.1."):
            new = migrate_0_1_to_0_2(doc)
            errs = schema_errors(new, "mojo-world-0.2.schema.json")
            validate_document(downgrade_to_0_1(new), p.name)       # conteúdo continua válido no motor v0.1
            if errs:
                raise PackError(p.name, errs)
            print(f"OK: {new['id']} · mundo v0.1 migrado para 0.2 (kind=text-adventure) · conteúdo preservado · jogue com `mojo play`")
            return 0
    pk = load_pack(p)
    sc = ", ".join(pk.scenarios)
    print(f"OK: {pk.id} · '{pk.title}' · schema {pk.manifest['schema_version']} · facções={len(pk.factions)} · tipos={len(pk.types)} "
          f"· regras={len(pk.rules)} · cenários=[{sc}] · arquivos={len(pk.files)} · sha256={pk.sha256[:12]}")
    return 0


def cmd_simulate(a) -> int:
    from .pack.loader import load_pack
    from .sim.loop import TickEngine

    pk = load_pack(a.pack)
    eng = TickEngine(pk, a.scenario, a.seed)
    t0 = time.perf_counter()
    for _ in range(a.ticks):
        if eng.step().finished:
            break
    dt = time.perf_counter() - t0
    st = eng.state
    print(json.dumps({"scenario": eng.cs.scenario_id, "seed": eng.seed, "ticks": st.tick, "result": st.result,
                      "hash": eng.hash(), "entities": eng.n_alive, "ms_per_tick": round(dt / max(1, st.tick) * 1000, 4),
                      "vars": st.vars}, ensure_ascii=False))
    return 0


def cmd_replay(a) -> int:
    from .pack.loader import load_pack
    from .sim.replay import read_replay, verify_replay

    rep = read_replay(Path(a.file))
    pdir = a.pack or str(Path("packs") / rep["header"]["pack_id"])
    pk = load_pack(pdir)
    v = verify_replay(pk, rep, force=a.force)
    print(json.dumps(v, ensure_ascii=False))
    return 0 if v["ok"] else 1


def _port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def cmd_serve(a) -> int:
    try:
        import fastapi  # noqa: F401
        import uvicorn
        import websockets  # noqa: F401
    except ImportError:
        print('Faltam dependências do V2. Instale com:  pip install -e ".[serve]"   (ou rode INSTALAR-V2.bat)', file=sys.stderr)
        return 2
    from .audio import NullAudio, build_audio
    from .config import load_config
    from .pack.loader import load_pack
    from .server.app import create_app
    from .server.security import new_token
    from .server.session import GameSession

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    cfg = load_config(a.config)
    if a.home:
        cfg.home = Path(a.home)
    pk = load_pack(a.pack)                                  # valida TUDO antes de abrir porta ou rodar um tick
    audio = None
    ac = pk.manifest.get("audio", {})
    if a.audio != "off" and ac.get("enabled") and ac.get("provider") == "ragnarok" and cfg.ragnarok.enabled:
        audio = build_audio(cfg.ragnarok, cfg.cache_dir, True)
        hs = audio.health_check()
        print(f"[áudio] {audio.name}: {hs.status}" + (f" ({hs.detail})" if hs.detail else "")
              + ("" if hs.ok else " — seguirei só com texto e tentarei de novo nas próximas narrações"))
    resume = json.loads(Path(a.resume).read_text(encoding="utf-8")) if a.resume else None
    sess = GameSession(pk, a.scenario, seed=a.seed, home=cfg.home, audio=audio,
                       voice_profile=ac.get("voice_profile", "narrator_default"), record=not a.no_record, resume=resume)
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    if not _port_free(host, a.port):
        print(f"A porta {a.port} já está em uso. Use --port <outra> (a do Ragnarok é 8765).", file=sys.stderr)
        return 2
    token = new_token()
    app = create_app(sess, port=a.port, token=token, lan=a.lan, audio_dir=cfg.cache_dir)
    url = f"http://127.0.0.1:{a.port}/?t={token}"
    print(f"MOJO V2 {V2_VERSION} · {pk.title} · cenário {sess.eng.cs.scenario_id} · seed {sess.eng.seed}")
    print(f"Abra no navegador: {url}")
    if a.lan:
        print("ATENÇÃO: --lan expõe o jogo na rede local (token continua obrigatório). Use só em rede confiável.")
    if sess.replay_path:
        print(f"Replay desta partida: {sess.replay_path}")
    print("Ctrl+C para encerrar.")
    if a.open:
        import webbrowser
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.run(app, host=host, port=a.port, log_level="warning", ws="auto", ws_max_size=16384, lifespan="on")
    except KeyboardInterrupt:
        pass
    print("Encerrado.", json.dumps(sess.summary()))
    return 0
