"""Configuração do MOJO — separada do arquivo de mundo (ADR-010).

Sem segredos: chaves de API só por variável de ambiente (nome indicado em
`api_key_env`). Campos desconhecidos ou que pareçam segredo literal são recusados.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ADAPTER_KINDS = ("mock", "local", "remote")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class ConfigError(ValueError):
    pass


@dataclass
class AdapterConfig:
    kind: str = "mock"
    enabled: bool = False          # local/remote só funcionam com enabled=true
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    timeout_s: float = 30.0
    consent_remote: bool = False   # remoto exige consentimento explícito (texto sai da máquina)


@dataclass
class RagnarokConfig:
    enabled: bool = True
    base_url: str = "http://127.0.0.1:8765"
    timeout_s: float = 20.0
    health_timeout_s: float = 1.5
    fmt: str = "wav"
    max_chars: int = 2000
    failures_to_open: int = 3
    open_seconds: float = 60.0
    allow_non_loopback: bool = False
    # perfil lógico (usado no .mjo) -> voz real do Ragnarok. Decisão pendente nº 5 do Gui.
    voice_profiles: dict = field(default_factory=lambda: {"narrator_default": {"voice": "alex-pt", "speed": 1.0}})


@dataclass
class Config:
    adapter: AdapterConfig = field(default_factory=AdapterConfig)
    ragnarok: RagnarokConfig = field(default_factory=RagnarokConfig)
    home: Path = field(default_factory=lambda: Path(".mojo"))
    language: str = "pt-BR"

    @property
    def saves_dir(self) -> Path:
        return self.home / "saves"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache" / "audio"


def _check_url(url: str, *, what: str, loopback_only: bool, https_only: bool = False) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ConfigError(f"{what}: URL inválida {url!r}")
    if u.username or u.password:
        raise ConfigError(f"{what}: credenciais na URL não são permitidas")
    if loopback_only and u.hostname not in LOOPBACK:
        raise ConfigError(f"{what}: apenas loopback (127.0.0.1/localhost) é permitido, recebido {u.hostname!r}")
    if https_only and u.scheme != "https":
        raise ConfigError(f"{what}: endpoint remoto exige https")


def _take(d: dict, cls, name: str):
    if not isinstance(d, dict):
        raise ConfigError(f"{name}: deve ser um objeto")
    allowed = set(cls.__dataclass_fields__)
    for k in d:
        if k not in allowed:
            hint = " (segredos não vão no arquivo; use api_key_env)" if "key" in k.lower() or "secret" in k.lower() else ""
            raise ConfigError(f"{name}: campo desconhecido {k!r}{hint}")
    return cls(**d)


def validate_config(cfg: Config) -> Config:
    a, r = cfg.adapter, cfg.ragnarok
    if a.kind not in ADAPTER_KINDS:
        raise ConfigError(f"adapter.kind: use um de {ADAPTER_KINDS}")
    if a.kind == "local" and a.enabled:
        _check_url(a.base_url, what="adapter.base_url", loopback_only=True)
    if a.kind == "remote" and a.enabled:
        _check_url(a.base_url, what="adapter.base_url", loopback_only=False, https_only=True)
        if not a.consent_remote:
            raise ConfigError("adapter remoto exige consent_remote=true (o texto do jogo sai da máquina)")
        if not a.api_key_env:
            raise ConfigError("adapter remoto exige api_key_env (nome da variável de ambiente)")
    if a.kind in ("local", "remote") and a.enabled and not a.model:
        raise ConfigError("adapter.model é obrigatório quando local/remote está habilitado")
    _check_url(r.base_url, what="ragnarok.base_url", loopback_only=not r.allow_non_loopback)
    if r.fmt != "wav":
        raise ConfigError("ragnarok.fmt: v0.1 suporta apenas 'wav'")
    if not (0.1 <= r.timeout_s <= 300) or not (0.1 <= a.timeout_s <= 300):
        raise ConfigError("timeouts devem estar entre 0.1 e 300 segundos")
    if not isinstance(r.voice_profiles, dict) or "narrator_default" not in r.voice_profiles:
        raise ConfigError("ragnarok.voice_profiles deve conter 'narrator_default'")
    for k, v in r.voice_profiles.items():
        if not isinstance(v, dict) or not isinstance(v.get("voice"), str):
            raise ConfigError(f"ragnarok.voice_profiles.{k}: esperado {{'voice': str, 'speed': float}}")
    return cfg


def load_config(path: str | Path | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    data: dict = {}
    if path is None and Path("mojo.config.json").is_file():
        path = "mojo.config.json"
    if path is not None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise ConfigError(f"não foi possível ler a configuração: {exc.strerror or exc}") from None
        except json.JSONDecodeError as exc:
            raise ConfigError(f"configuração malformada (linha {exc.lineno}, coluna {exc.colno}): {exc.msg}") from None
        if not isinstance(data, dict):
            raise ConfigError("a configuração deve ser um objeto JSON")
    extra = set(data) - {"adapter", "ragnarok", "home", "language"}
    if extra:
        raise ConfigError(f"campos desconhecidos na raiz: {sorted(extra)}")
    cfg = Config(
        adapter=_take(data.get("adapter", {}), AdapterConfig, "adapter"),
        ragnarok=_take(data.get("ragnarok", {}), RagnarokConfig, "ragnarok"),
        language=str(data.get("language", "pt-BR")),
    )
    home = env.get("MOJO_HOME") or data.get("home") or ".mojo"
    cfg.home = Path(home)
    return validate_config(cfg)
