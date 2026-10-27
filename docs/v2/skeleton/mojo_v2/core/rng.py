"""RNG determinístico por sistema (V2). Inteiros puros: o mesmo seed gera a mesma sequência em qualquer Python/OS."""
from __future__ import annotations

import hashlib

M64 = (1 << 64) - 1


def derive_seed(master: int, stream: str) -> int:
    """Seed independente por stream: blake2b(f"{master}:{stream}")."""
    return int.from_bytes(hashlib.blake2b(f"{master}:{stream}".encode(), digest_size=8).digest(), "little")


class SplitMix64:
    __slots__ = ("s",)

    def __init__(self, seed: int):
        self.s = seed & M64

    def next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & M64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        """Inteiro em [0, n). Viés de módulo desprezível para n << 2**53 (aceitável em jogo; documentado)."""
        if n <= 0:
            raise ValueError("n deve ser >= 1")
        return (self.next() >> 11) % n


class RngStreams:
    """Um SplitMix64 por nome declarado (rng_streams do pacote + streams internos: ai, combat, entropy, spawn)."""

    def __init__(self, master_seed: int, names):
        self.master = master_seed
        self._s = {n: SplitMix64(derive_seed(master_seed, n)) for n in sorted(names)}

    def __getitem__(self, name: str) -> SplitMix64:
        return self._s[name]                      # KeyError => stream não declarado (a validação do pacote já impede)

    def state(self) -> dict[str, int]:
        return {n: r.s for n, r in sorted(self._s.items())}   # entra no hash/snapshot

    def restore(self, st: dict[str, int]) -> None:
        for n, v in st.items():
            self._s[n].s = v
