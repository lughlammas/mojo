"""Narração opcional (texto imediato + áudio assíncrono via Ragnarok) FORA do tick. Sem áudio => só texto."""
from __future__ import annotations

import queue
import re
import threading
from pathlib import Path

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class Narrator:
    """Fila limitada + 1 thread de síntese. Nunca bloqueia o laço de ticks; falhas viram silêncio (já registradas no adaptador)."""

    def __init__(self, audio, voice_profile: str, on_audio, *, maxq: int = 8):
        self.audio, self.voice, self.on_audio = audio, voice_profile, on_audio
        self.q: queue.Queue = queue.Queue(maxsize=maxq)
        self.dropped = 0
        self.synthesized = 0
        self.failed = 0
        self._stop = threading.Event()
        self._t = None
        if audio is not None and getattr(audio, "name", "none") != "none":
            self._t = threading.Thread(target=self._run, name="mojo-narrator", daemon=True)
            self._t.start()

    @property
    def audio_enabled(self) -> bool:
        return self._t is not None

    def say(self, text: str, tick: int) -> None:
        if self._t is None:
            return
        try:
            self.q.put_nowait((text, tick))
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                text, tick = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                ref = self.audio.synthesize(text, self.voice)
            except Exception:  # o adaptador não deve levantar, mas a thread nunca morre
                self.failed += 1
                continue
            if ref.usable and ref.path:
                h = Path(ref.path).stem
                if HASH_RE.match(h):
                    self.synthesized += 1
                    self.on_audio(h, tick)
                    continue
            self.failed += 1

    def close(self) -> None:
        self._stop.set()
