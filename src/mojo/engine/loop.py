"""Core loop (ADR-001): jogador -> permissão -> contexto -> proposta -> validação -> estado -> resposta -> log.

O modelo (adaptador semântico) PROPÕE narração e eventos; só o núcleo muda o estado.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from ..audio.base import AudioAdapter, AudioRef, NullAudio
from ..semantic.base import AdapterError, Context, Proposal, SemanticAdapter
from ..semantic.mock import baseline_narration
from ..store.logs import SessionLog
from .actions import Command, parse_command, resolve_entity, resolve_exit
from .events import apply_event, requires_met, validate_event
from .state import MAX_HISTORY, GameState, initial_state

MAX_NARRATION = 1200
MAX_EVENTS = 5


def clean_text(s: str, limit: int) -> str:
    s = "".join(c for c in s if c in "\n" or (ord(c) >= 32 and ord(c) != 127))
    return s.strip()[:limit]


@dataclass
class TurnResult:
    kind: str                  # ok | refused | invalid | unknown | empty
    text: str
    notes: list = field(default_factory=list)       # linhas curtas p/ o jogador (mudanças de estado, avisos)
    applied: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    hash_before: str = ""
    hash_after: str = ""
    audio: "Future[AudioRef] | None" = None
    audio_text: str = ""
    turn: int = 0

    @property
    def changed(self) -> bool:
        return self.hash_before != self.hash_after


class Game:
    def __init__(self, world, adapter: SemanticAdapter, audio: AudioAdapter | None = None, log: SessionLog | None = None,
                 state: GameState | None = None, audio_enabled: bool = True, audio_sync: bool = False,
                 language: str = "pt-BR", max_audio_chars: int = 2000):
        self.world = world
        self.adapter = adapter
        self.audio = audio or NullAudio()
        self.log = log or SessionLog(None)
        self.state = state or initial_state(world)
        self.audio_enabled = audio_enabled and bool(world.data["audio"]["enabled"])
        self.audio_sync = audio_sync
        self.language = language
        self.max_audio_chars = max_audio_chars
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mojo-audio")

    # ----- ciclo de vida -----
    def close(self) -> None:
        self._pool.shutdown(wait=True)

    def start_session(self, audio_status: str = "") -> None:
        w = self.world
        self.log.write("session_start", mojo_version=_ver(), world={"id": w.id, "title": w.title,
                       "schema_version": w.data["schema_version"], "sha256": w.sha256, "canon": w.canon},
                       adapter=self.adapter.describe(), audio={"adapter": self.audio.name, "enabled": self.audio_enabled,
                                                               "status": audio_status},
                       state_hash=self.state.hash())

    # ----- contexto -----
    def _scene_view(self, scene_id: str) -> dict:
        sc = self.world.scenes[scene_id]
        exits = [{"id": x["id"], "label": x["label"], "available": requires_met(x.get("requires"), self.state)}
                 for x in sc.get("exits", [])]
        return {"id": sc["id"], "title": sc.get("title", sc["id"]), "description": sc["description"],
                "exits": exits, "entities": [dict(e) for e in sc.get("entities", [])]}

    def _context(self, action: str, target, text: str, destination) -> Context:
        d, s = self.world.data, self.state
        return Context(
            world_id=self.world.id, title=self.world.title, narration_style=d["semantics"]["narration_style"],
            constraints=list(d["semantics"]["generation_constraints"]), language=self.language,
            scene=self._scene_view(s.scene), action=action, target=target, text=text, destination=destination,
            player={"hp": s.hp, "max_hp": s.max_hp, "inventory": list(s.inventory)}, flags=dict(s.flags),
            recent=[dict(h) for h in s.history[-3:]], allowed_events=list(self.world.allowed_events))

    # ----- apresentação inicial (não consome turno) -----
    def intro(self) -> TurnResult:
        ctx = self._context("look", None, "", None)
        text = baseline_narration(ctx)
        h = self.state.hash()
        self.log.write("intro", scene=self.state.scene, state_hash=h)
        return TurnResult("ok", text, hash_before=h, hash_after=h, turn=self.state.turn,
                          audio=self._request_audio(text, 0))

    # ----- turno -----
    def step(self, line: str) -> TurnResult:
        cmd = parse_command(line)
        before = self.state.hash()

        def done(kind, text, **kw):
            res = TurnResult(kind, text, hash_before=before, hash_after=self.state.hash(), turn=self.state.turn, **kw)
            return res

        if cmd.kind == "empty":
            return done("empty", "")
        if cmd.kind in ("unknown", "meta"):
            msg = f"Comando desconhecido: {cmd.verb!r}. Digite 'help'." if cmd.kind == "unknown" else \
                f"'{cmd.verb}' é um comando do console, não uma ação do mundo."
            self.log.write("turn", turn=self.state.turn, input=cmd.raw, outcome="unknown", allowed=False,
                           state_hash_before=before, state_hash_after=before)
            return done("unknown", msg)
        verb = cmd.verb
        if verb not in self.world.allowed_actions:
            self.log.write("turn", turn=self.state.turn, input=cmd.raw, verb=verb, outcome="refused", allowed=False,
                           reason="ação não permitida pelo mundo", state_hash_before=before, state_hash_after=before)
            return done("refused", f"Ação não permitida neste mundo: '{verb}'. "
                                   f"Permitidas: {', '.join(self.world.allowed_actions)}.")

        scene = self.world.scenes[self.state.scene]
        target, text, destination, engine_events = None, "", None, []
        if verb == "inspect":
            if not cmd.arg:
                names = ", ".join(e["name"] for e in scene.get("entities", [])) or "nada de especial"
                return self._invalid(cmd, before, f"Inspecionar o quê? Aqui: {names}.", done)
            target, err = resolve_entity(scene.get("entities", []), cmd.arg)
            if err:
                return self._invalid(cmd, before, f"Não há '{cmd.arg}' para inspecionar aqui." if err == "unknown"
                                     else f"'{cmd.arg}' é ambíguo; seja mais específico.", done)
            engine_events.append({"type": "set_flag", "flag": f"inspected:{target['id']}", "value": True})
        elif verb == "speak":
            if not cmd.arg:
                return self._invalid(cmd, before, "Falar o quê? Use: speak <texto>.", done)
            text = cmd.arg
        elif verb == "go":
            if not cmd.arg:
                return self._invalid(cmd, before, "Ir para onde? Use: go <saída>.", done)
            target, err = resolve_exit(scene.get("exits", []), cmd.arg)
            if err:
                return self._invalid(cmd, before, f"Não há saída '{cmd.arg}' aqui." if err == "unknown"
                                     else f"'{cmd.arg}' é ambíguo; seja mais específico.", done)
            if not requires_met(target.get("requires"), self.state):
                return self._invalid(cmd, before, target.get("blocked_text", "O caminho está bloqueado."), done)
            engine_events.append({"type": "move", "exit": target["id"]})
            destination = self._scene_view(target["to"])

        ctx = self._context(verb, target, text, destination)
        fallback_reason, proposal = None, None
        try:
            proposal = self.adapter.propose(ctx)
            if not isinstance(proposal, Proposal):
                raise AdapterError("adaptador devolveu tipo inesperado")
        except AdapterError as exc:
            fallback_reason = f"adaptador falhou: {exc}"
        except Exception as exc:  # adaptador de terceiros nunca derruba o jogo
            fallback_reason = f"adaptador falhou inesperadamente: {type(exc).__name__}"

        narration = None
        if proposal is not None:
            if isinstance(proposal.narration, str):
                narration = clean_text(proposal.narration, MAX_NARRATION)
            if not narration:
                fallback_reason = "narração inválida ou vazia"
                narration = None
        if narration is None:
            narration = baseline_narration(ctx)

        # --- validação: eventos do núcleo (sempre) + propostos (filtrados) ---
        new = self.state.copy()
        applied, rejected = [], []
        allowed = set(self.world.allowed_events)
        for ev in engine_events:
            ok, why = validate_event(ev, new, self.world, allowed=None, engine=True)
            if ok is None:  # não deveria ocorrer; aborta o turno sem mudar nada
                return self._invalid(cmd, before, f"erro interno de regra: {why}", done)
            apply_event(ok, new, self.world)
            applied.append({**ok, "source": "engine"})
        proposed = proposal.proposed_events if proposal is not None else []
        if not isinstance(proposed, list):
            rejected.append({"event": str(proposed)[:80], "reason": "proposed_events não é lista"})
            proposed = []
        for i, ev in enumerate(proposed):
            if i >= MAX_EVENTS:
                rejected.append({"event": _brief(ev), "reason": f"mais de {MAX_EVENTS} eventos na proposta"})
                continue
            ok, why = validate_event(ev, new, self.world, allowed=allowed)
            if ok is None:
                rejected.append({"event": _brief(ev), "reason": why})
            else:
                apply_event(ok, new, self.world)
                applied.append({**ok, "source": "model"})
        new.turn += 1
        new.history.append({"turn": new.turn, "action": verb, "input": cmd.raw[:200], "narration": narration[:300]})
        del new.history[:-MAX_HISTORY]
        self.state = new  # commit atômico do turno
        after = new.hash()

        audio_text = narration
        if proposal is not None and isinstance(proposal.audio_request, dict) and \
                proposal.audio_request.get("kind") == "speech" and isinstance(proposal.audio_request.get("text"), str):
            alt = clean_text(proposal.audio_request["text"], self.max_audio_chars)
            if alt:
                audio_text = alt
        notes = [f"[estado] {_fmt_event(e)}" for e in applied] + \
                [f"[rejeitado] {r['reason']}" for r in rejected]
        if fallback_reason:
            notes.append(f"[fallback] {fallback_reason}")
        fut = self._request_audio(audio_text, new.turn)
        self.log.write("turn", turn=new.turn, input=cmd.raw, verb=verb, outcome="ok", allowed=True,
                       state_hash_before=before, state_hash_after=after,
                       proposal=None if proposal is None else {"narration": proposal.narration,
                                                              "proposed_events": proposed,
                                                              "audio_request": proposal.audio_request},
                       applied_events=applied, rejected_events=rejected, fallback=fallback_reason,
                       narration=narration, audio_requested=fut is not None)
        res = TurnResult("ok", narration, notes, applied, rejected, before, after, fut, audio_text, new.turn)
        return res

    def _invalid(self, cmd: Command, before: str, msg: str, done) -> TurnResult:
        self.log.write("turn", turn=self.state.turn, input=cmd.raw, verb=cmd.verb, outcome="invalid", allowed=True,
                       reason=msg, state_hash_before=before, state_hash_after=self.state.hash())
        return done("invalid", msg)

    # ----- áudio -----
    def _request_audio(self, text: str, turn: int) -> "Future[AudioRef] | None":
        if not self.audio_enabled or not text:
            return None
        profile = self.world.data["audio"]["voice_profile"]

        def job() -> AudioRef:
            try:
                ref = self.audio.synthesize(text, profile)
            except Exception as exc:  # adaptador de terceiros: nunca derruba o jogo
                ref = AudioRef("unavailable", detail=f"falha inesperada no áudio: {type(exc).__name__}")
            self.log.write("audio", turn=turn, **ref.to_dict(), chars=len(text))
            return ref

        if self.audio_sync:
            f: Future = Future()
            f.set_result(job())
            return f
        return self._pool.submit(job)


def _brief(ev) -> str:
    try:
        return str(ev)[:80]
    except Exception:
        return "?"


def _fmt_event(e: dict) -> str:
    t = e["type"]
    if t == "set_flag":
        return f"flag {e['flag']} = {e['value']}"
    if t == "give_item":
        return f"+item {e['item']}"
    if t == "remove_item":
        return f"-item {e['item']}"
    if t == "hp_delta":
        return f"hp {e['amount']:+d}"
    return f"mover via {e['exit']}"


def _ver() -> str:
    from .. import __version__
    return __version__
