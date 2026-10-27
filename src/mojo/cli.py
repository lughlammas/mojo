"""CLI do MOJO: `mojo play <mundo.mjo>`, `mojo validate <mundo.mjo>`, `mojo audio-check`."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .audio import build_audio
from .config import ConfigError, load_config
from .engine import Game
from .engine.state import StateError
from .render import render_log_line, render_state, wrap
from .semantic import AdapterError, MockAdapter, build_adapter
from .store import SaveError, SessionLog, load_state, save_state
from .world import WorldError, load_world

HELP = """Ações do mundo (as permitidas variam por mundo): look | inspect <alvo> | speak <texto> | go <saída>
Console: state | log [n] | save [slot] | load [slot] | audio | help | quit"""


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_WARNED = {"audio": False}


def _print_audio(game: Game, fut, out, play: bool) -> None:
    if fut is None:
        return
    ref = fut.result()
    if ref.usable:
        _WARNED["audio"] = False
        out(f"[áudio] {ref.status} · voz {ref.voice} · {ref.duration_s}s · {ref.latency_ms} ms")
        if play:
            ok, detail = game.audio.play(ref)
            out(f"[áudio] reprodução: {detail}")
    elif ref.status != "disabled" and not _WARNED["audio"]:
        _WARNED["audio"] = True  # avisa uma vez; novas tentativas seguem em silêncio até voltar
        out(f"[áudio indisponível] {ref.detail} — continuando em modo texto (novas falhas não serão repetidas)")


def repl(game: Game, cfg, input_fn=input, out=print, play_audio: bool = False) -> int:
    _WARNED["audio"] = False
    out(f"== {game.world.title} ==")
    if not game.world.canon:
        out("(mundo de demonstração, NÃO canônico)")
    out(wrap(game.world.data["world"]["description"]))
    out("")
    first = game.intro()
    out(wrap(first.text))
    _print_audio(game, first.audio, out, play_audio)
    while True:
        try:
            line = input_fn("> ")
        except (EOFError, KeyboardInterrupt):
            out("")
            line = "quit"
        cmd = line.strip()
        head, _, arg = cmd.partition(" ")
        h = head.lower()
        if h in ("quit", "exit", "sair"):
            game.log.write("session_end", turn=game.state.turn, state_hash=game.state.hash())
            out("Até logo.")
            return 0
        if h in ("help", "?", "ajuda"):
            out(HELP)
        elif h in ("state", "estado"):
            out(render_state(game))
        elif h == "log":
            n = int(arg) if arg.strip().isdigit() else 8
            for rec in game.log.tail(max(1, min(n, 50))):
                out(render_log_line(rec))
            if game.log.path:
                out(f"(log completo: {game.log.path})")
        elif h in ("save", "salvar"):
            try:
                p = save_state(cfg.saves_dir, game.world, game.state, arg.strip() or "auto", game.log.session_id)
                game.log.write("save", slot=arg.strip() or "auto", state_hash=game.state.hash())
                out(f"Salvo em {p}")
            except SaveError as exc:
                out(f"Erro ao salvar: {exc}")
        elif h in ("load", "carregar"):
            try:
                st, warns = load_state(cfg.saves_dir, game.world, arg.strip() or "auto")
                game.state = st
                game.log.write("load", slot=arg.strip() or "auto", state_hash=st.hash(), warnings=warns)
                for w in warns:
                    out(f"[aviso] {w}")
                out("Estado carregado.\n" + render_state(game))
            except SaveError as exc:
                out(f"Erro ao carregar: {exc}")
        elif h in ("audio", "áudio"):
            hs = game.audio.health_check()
            out(f"Áudio ({game.audio.name}): {hs.status} — {hs.detail}")
        elif not cmd:
            continue
        else:
            res = game.step(cmd)
            if res.text:
                out(wrap(res.text))
            for n in res.notes:
                out(n)
            _print_audio(game, res.audio, out, play_audio)


def cmd_play(a) -> int:
    cfg = load_config(a.config)
    if a.home:
        from pathlib import Path
        cfg.home = Path(a.home)
    world = load_world(a.world)
    adapter = MockAdapter() if a.mock else None
    if adapter is None:
        try:
            adapter = build_adapter(cfg.adapter)
        except AdapterError as exc:
            print(f"Aviso: {exc}; usando o adaptador mock.", file=sys.stderr)
            adapter = MockAdapter()
    audio_on = a.audio != "off"
    audio = build_audio(cfg.ragnarok, cfg.cache_dir, audio_on and world.data["audio"]["enabled"])
    hs = audio.health_check()
    log = SessionLog(cfg.logs_dir)
    state = None
    if a.load:
        try:
            state, warns = load_state(cfg.saves_dir, world, a.load)
            for w in warns:
                print(f"[aviso] {w}")
        except (SaveError, StateError) as exc:
            print(f"Não foi possível carregar o save: {exc}", file=sys.stderr)
            return 2
    game = Game(world, adapter, audio, log, state=state, audio_enabled=audio_on, language=cfg.language,
                max_audio_chars=cfg.ragnarok.max_chars)
    print(f"[mojo {__version__}] adaptador semântico: {adapter.name} · áudio: {audio.name} ({hs.status}"
          f"{': ' + hs.detail if hs.detail else ''})")
    if audio.name != "none" and not hs.ok:
        print("[aviso] Ragnarok não está pronto; a sessão segue em modo texto e tentará o áudio de novo.")
    game.start_session(hs.status)
    try:
        return repl(game, cfg, play_audio=a.play_audio)
    finally:
        game.close()


def cmd_validate(a) -> int:
    from pathlib import Path as _P
    if _P(a.world).is_dir():  # V2: pasta de pacote (aditivo; o caminho .mjo do v0.1 abaixo não muda)
        from .cli_v2 import cmd_pack_validate
        return cmd_pack_validate(a, a.world)
    w = load_world(a.world)
    print(f"OK: {w.id} · '{w.title}' · schema {w.data['schema_version']} · cenas={len(w.scenes)} · "
          f"canon={'sim' if w.canon else 'não'} · sha256={w.sha256[:12]}")
    return 0


def cmd_audio_check(a) -> int:
    cfg = load_config(a.config)
    ad = build_audio(cfg.ragnarok, cfg.cache_dir, True)
    h = ad.health_check()
    print(f"{ad.name}: {h.status} — {h.detail}" + (f" ({h.latency_ms} ms)" if h.latency_ms is not None else ""))
    if a.say:
        ref = ad.synthesize(a.say, "narrator_default")
        print(f"síntese: {ref.status} · {ref.detail} · {ref.latency_ms} ms · {ref.duration_s}s · {ref.path}")
        return 0 if ref.usable else 1
    return 0 if h.ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mojo", description="MOJO (Dream Fabrics) — protótipo v0.1, não pronto para produção.")
    p.add_argument("--version", action="version", version=f"mojo {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("play", help="jogar um mundo .mjo")
    pl.add_argument("world")
    pl.add_argument("--config")
    pl.add_argument("--home", help="pasta de saves/logs/cache (padrão ./.mojo ou $MOJO_HOME)")
    pl.add_argument("--mock", action="store_true", help="força o adaptador mock (sem rede)")
    pl.add_argument("--audio", choices=["auto", "off"], default="auto")
    pl.add_argument("--play-audio", action="store_true", help="tenta tocar o áudio localmente (não testado no Windows)")
    pl.add_argument("--load", metavar="SLOT")
    pl.set_defaults(fn=cmd_play)
    va = sub.add_parser("validate", help="validar um .mjo")
    va.add_argument("world")
    va.set_defaults(fn=cmd_validate)
    ac = sub.add_parser("audio-check", help="health_check do Ragnarok (e síntese opcional)")
    ac.add_argument("--config")
    ac.add_argument("--say", help="sintetiza este texto com narrator_default")
    ac.set_defaults(fn=cmd_audio_check)
    from .cli_v2 import register as _register_v2  # V2 (aditivo)
    _register_v2(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8()
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except WorldError as exc:
        print(exc.format(), file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"Configuração inválida: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
