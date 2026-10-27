"""Cálculo de REFERÊNCIA das ondas de entropia do exemplo (rules/entropy.json) para uma seed — sem motor, só as regras à mão.
Convenções propostas: ordem das regras = ordem de declaração; argumentos avaliados da esquerda p/ direita; uniform_cell sorteia x=below(width) e depois y=below(height).
Serve de teste dourado futuro (fase F3). NÃO é execução do motor; sem estabilizadores da Terra e sem unidades."""
import sys
sys.path.insert(0, "../skeleton")
from mojo_v2.core.rng import SplitMix64, derive_seed

def preview(seed, width, height, until=2400, entropy_init=10, next_init=300):
    rng = SplitMix64(derive_seed(seed, "entropy"))
    entropy, wave_i, nxt, out = entropy_init, 0, next_init, []
    for t in range(1, until + 1):
        if t % 20 == 0:
            entropy = min(100, entropy + 1)                    # entropy_rise
        if t >= nxt:                                            # wave_spawn
            e0 = entropy
            cx, cy = rng.below(width), rng.below(height)
            radius, power = 3 + e0 // 20, 4 + e0 // 10
            wave_i += 1
            nxt = t + 200 + rng.below(120)
            entropy = max(0, entropy - 15)
            out.append((wave_i, t, cx, cy, radius, power, e0))
    return out

if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 777
    print(f"seed={seed} grid 24x16 — onda | tick | centro | raio | poder | entropia antes")
    for w in preview(seed, 24, 16):
        print("  ", w)
    a, b = preview(777, 24, 16), preview(777, 24, 16)
    c = preview(778, 24, 16)
    print("repetível (mesma seed):", a == b, "| seed 778 difere:", a != c)
