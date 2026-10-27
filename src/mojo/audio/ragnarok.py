"""RagnarokAdapter — fala com o Ragnarok REAL por HTTP (ADR-005).

Contrato usado (verificado no código do Ragnarok, ver docs/DIAGNOSTICO-RAGNAROK.md):
  GET  /api/status            -> JSON {"version", "models": {...}, ...}
  POST /v1/audio/speech       -> corpo WAV (200) | JSON {"detail"} (400/413/422) | texto "Internal Server Error" (500)
Nunca importa código do Ragnarok. Timeout próprio, cache por hash, disjuntor (circuit breaker).
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

from .base import AudioAdapter, AudioRef, Health
from .player import play_file

MAX_WAV_BYTES = 50_000_000


class _Fail(Exception):
    pass


class RagnarokAdapter(AudioAdapter):
    name = "ragnarok"

    def __init__(self, cfg, cache_dir: Path, clock=time.monotonic):
        self.cfg = cfg
        self.base = cfg.base_url.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self._clock = clock
        self._fails = 0
        self._open_until = 0.0

    # ---------- util ----------
    def _profile(self, voice_profile: str) -> tuple[str, dict]:
        vp = self.cfg.voice_profiles
        name = voice_profile if voice_profile in vp else "narrator_default"
        return name, vp[name]

    def cache_key(self, text: str, voice: str, speed: float) -> str:
        blob = json.dumps({"v": 1, "text": text, "voice": voice, "speed": speed, "fmt": self.cfg.fmt},
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.wav"

    @staticmethod
    def _wav_duration(data: bytes) -> float:
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise _Fail("resposta não é um WAV válido")
        try:
            with wave.open(io.BytesIO(data)) as w:
                frames, rate = w.getnframes(), w.getframerate()
        except (wave.Error, EOFError):
            raise _Fail("WAV corrompido") from None
        if rate <= 0 or frames <= 0:
            raise _Fail("WAV vazio")
        return round(frames / rate, 3)

    def _http(self, method: str, path: str, body: bytes | None, timeout: float, max_bytes: int):
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={"Content-Type": "application/json"} if body else {})
        deadline = self._clock() + timeout
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                buf = bytearray()
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > max_bytes:
                        raise _Fail("resposta grande demais")
                    if self._clock() > deadline:
                        raise _Fail(f"timeout total de {timeout:g}s excedido")
                return resp.status, bytes(buf)
        except urllib.error.HTTPError as exc:
            raw = exc.read(2000)
            try:
                detail = json.loads(raw).get("detail", "")
                if isinstance(detail, list):
                    detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
            except (ValueError, AttributeError):
                detail = raw.decode("utf-8", "replace")[:120]  # 500 do Ragnarok é texto puro
            raise _Fail(f"HTTP {exc.code} do Ragnarok: {str(detail)[:160]}") from None
        except urllib.error.URLError as exc:
            r = exc.reason
            if isinstance(r, TimeoutError) or "timed out" in str(r):
                raise _Fail(f"timeout de {timeout:g}s") from None
            raise _Fail(f"Ragnarok indisponível ({r})") from None
        except TimeoutError:
            raise _Fail(f"timeout de {timeout:g}s") from None
        except (OSError, http.client.HTTPException) as exc:
            raise _Fail(f"erro de rede: {exc}") from None

    # ---------- API ----------
    def health_check(self) -> Health:
        t0 = self._clock()
        try:
            status, raw = self._http("GET", "/api/status", None, self.cfg.health_timeout_s, 100_000)
            info = json.loads(raw)
            if not isinstance(info, dict) or "version" not in info:
                raise _Fail("resposta de /api/status inesperada")
        except _Fail as exc:
            return Health("unreachable" if "indispon" in str(exc) or "timeout" in str(exc) else "bad_response", str(exc))
        except ValueError:
            return Health("bad_response", "/api/status não devolveu JSON")
        ms = int((self._clock() - t0) * 1000)
        models = info.get("models") or {}
        self._fails, self._open_until = 0, 0.0
        if isinstance(models, dict) and models and not any(models.values()):
            return Health("degraded", f"Ragnarok {info['version']} no ar, mas sem modelos instalados", ms)
        return Health("ok", f"Ragnarok {info['version']}; engine carregado: {info.get('loaded_engine')}", ms)

    def synthesize(self, text: str, voice_profile: str, options: dict | None = None) -> AudioRef:
        t0 = self._clock()
        text = (text or "").strip()
        _, prof = self._profile(voice_profile)
        voice = prof["voice"]
        speed = float((options or {}).get("speed", prof.get("speed", 1.0)))
        ms = lambda: int((self._clock() - t0) * 1000)
        if not text:
            return AudioRef("unavailable", detail="texto vazio", voice=voice)
        if len(text) > self.cfg.max_chars:
            return AudioRef("unavailable", detail=f"texto acima de {self.cfg.max_chars} caracteres", voice=voice)
        if not (0.5 <= speed <= 2.0):
            speed = 1.0
        key = self.cache_key(text, voice, speed)
        cp = self._cache_path(key)
        if cp.is_file():
            try:
                dur = self._wav_duration(cp.read_bytes())
                return AudioRef("cache", str(cp), dur, ms(), voice, "cache por hash")
            except (_Fail, OSError):
                cp.unlink(missing_ok=True)  # cache corrompido: descarta e regenera
        if self._clock() < self._open_until:
            return AudioRef("unavailable", detail="disjuntor aberto: Ragnarok falhou repetidamente; "
                            "nova tentativa em breve", voice=voice, latency_ms=ms())
        body = json.dumps({"model": "ragnarok", "input": text, "voice": voice, "response_format": self.cfg.fmt,
                           "speed": speed}).encode("utf-8")
        try:
            _, data = self._http("POST", "/v1/audio/speech", body, self.cfg.timeout_s, MAX_WAV_BYTES)
            dur = self._wav_duration(data)
        except _Fail as exc:
            self._fails += 1
            if self._fails >= self.cfg.failures_to_open:
                self._open_until = self._clock() + self.cfg.open_seconds
            return AudioRef("unavailable", detail=str(exc), voice=voice, latency_ms=ms())
        self._fails = 0
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, cp)
        except OSError as exc:
            return AudioRef("unavailable", detail=f"não foi possível gravar o cache: {exc.strerror}", voice=voice,
                            latency_ms=ms())
        return AudioRef("ok", str(cp), dur, ms(), voice, "sintetizado pelo Ragnarok")

    def play(self, ref: AudioRef) -> tuple[bool, str]:
        if not ref.usable:
            return False, "sem áudio para reproduzir"
        return play_file(ref.path, self.cache_dir)


def build_audio(cfg_ragnarok, cache_dir, enabled: bool) -> AudioAdapter:
    from .base import NullAudio

    if not enabled or not cfg_ragnarok.enabled:
        return NullAudio()
    return RagnarokAdapter(cfg_ragnarok, Path(cache_dir))
