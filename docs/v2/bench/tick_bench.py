"""Micro-benchmark do NÚCLEO DE TICKS em Python puro (protótipo descartável, NÃO é código do MOJO v0.1/v2).

Mede custo por tick de um núcleo determinístico plausível para um RTS pequeno: grid 64x64 inteiro, spatial hash,
sistemas em ordem fixa, RNG por sistema (SplitMix64 próprio), ondas de entropia, snapshot/hash.
Uso: python tick_bench.py [--ticks 300] [--sizes 50,200,500,1000,2000]
"""
from __future__ import annotations

import argparse, hashlib, heapq, json, platform, statistics, sys, time

M64 = (1 << 64) - 1


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

    def below(self, n: int) -> int:           # inteiro em [0, n) sem float
        return (self.next() >> 11) % n


def derive_seed(master: int, name: str) -> int:
    return int.from_bytes(hashlib.blake2b(f"{master}:{name}".encode(), digest_size=8).digest(), "little")


W = H = 64
BUCKET = 8
DIRS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


class Ent:
    __slots__ = ("id", "f", "x", "y", "hp", "tgt", "cd", "kind")

    def __init__(self, id, f, x, y, hp, kind):
        self.id, self.f, self.x, self.y, self.hp, self.tgt, self.cd, self.kind = id, f, x, y, hp, 0, 0, kind


class Sim:
    def __init__(self, n_units: int, seed: int = 1234, ai_stagger: int = 1, chase: bool = False):
        self.ai_stagger = ai_stagger
        self.chase = chase
        self.tick = 0
        self.seed = seed
        self.rng = {k: SplitMix64(derive_seed(seed, k)) for k in ("ai", "combat", "entropy", "econ")}
        self.ents: dict[int, Ent] = {}
        self.res = [0, 0]
        self.next_id = 1
        self.walls = set()
        r = self.rng["entropy"]
        for _ in range(W * H // 12):
            self.walls.add((r.below(W), r.below(H)))
        self.occ: dict[tuple, int] = {}
        for i in range(n_units):
            f = i % 2
            for _ in range(50):
                x = r.below(W // 2) + (W // 2 if f else 0)
                y = r.below(H)
                if (x, y) not in self.walls and (x, y) not in self.occ:
                    break
            e = Ent(self.next_id, f, x, y, 30, "unit")
            self.next_id += 1
            self.ents[e.id] = e
            self.occ[(x, y)] = e.id
        self.next_wave = 50
        self.entropy_cells: dict[tuple, int] = {}
        self.cmds: list = []
        self.events: list = []

    # ---- sistemas, ordem fixa ----
    def sys_ai(self):
        buckets: dict[tuple, list] = {}
        for e in self.ents.values():          # dict preserva ordem de inserção => determinístico
            buckets.setdefault((e.x // BUCKET, e.y // BUCKET), []).append(e)
        self._buckets = buckets
        k, tk = self.ai_stagger, self.tick
        if self.chase:   # carga PESADA: toda unidade persegue um inimigo qualquer (global) => todas andam e lutam
            lists = ([], [])
            for e in self.ents.values():
                lists[e.f].append(e.id)
            r = self.rng["ai"]
            for e in self.ents.values():
                t = self.ents.get(e.tgt)
                if t is None or t.hp <= 0:
                    foes = lists[1 - e.f]
                    e.tgt = foes[r.below(len(foes))] if foes else 0
            return
        for e in self.ents.values():
            if k > 1 and (e.id + tk) % k:       # reavalia alvo só a cada k ticks, escalonado por id
                continue
            t = self.ents.get(e.tgt)
            if t is not None and t.hp > 0 and abs(t.x - e.x) <= 12 and abs(t.y - e.y) <= 12:
                continue
            best, bd = 0, 1 << 30
            bx, by = e.x // BUCKET, e.y // BUCKET
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for o in buckets.get((bx + dx, by + dy), ()):
                        if o.f != e.f:
                            d = max(abs(o.x - e.x), abs(o.y - e.y))
                            if d < bd or (d == bd and o.id < best):
                                best, bd = o.id, d
            e.tgt = best

    def sys_move(self):
        occ = self.occ
        for e in self.ents.values():
            if e.cd > 0:
                e.cd -= 1
                continue
            t = self.ents.get(e.tgt)
            if t is None:
                continue
            dx, dy = t.x - e.x, t.y - e.y
            if max(abs(dx), abs(dy)) <= 1:
                continue
            sx = (dx > 0) - (dx < 0)
            sy = (dy > 0) - (dy < 0)
            for cx, cy in ((sx, sy), (sx, 0), (0, sy)):
                nx, ny = e.x + cx, e.y + cy
                if (cx or cy) and 0 <= nx < W and 0 <= ny < H and (nx, ny) not in self.walls and (nx, ny) not in occ:
                    del occ[(e.x, e.y)]
                    e.x, e.y = nx, ny
                    occ[(nx, ny)] = e.id
                    e.cd = 1
                    break

    def sys_combat(self):
        r = self.rng["combat"]
        for e in self.ents.values():
            t = self.ents.get(e.tgt)
            if t is not None and max(abs(t.x - e.x), abs(t.y - e.y)) <= 1 and r.below(100) < 60:
                t.hp -= 2 + r.below(3)

    def sys_entropy(self):
        r = self.rng["entropy"]
        if self.tick >= self.next_wave:
            cx, cy, rad = r.below(W), r.below(H), 4 + r.below(5)
            dmg = 3 + r.below(5)
            for e in self.ents.values():
                if (e.x - cx) ** 2 + (e.y - cy) ** 2 <= rad * rad:
                    e.hp -= dmg
            for x in range(max(0, cx - rad), min(W, cx + rad + 1)):
                for y in range(max(0, cy - rad), min(H, cy + rad + 1)):
                    self.entropy_cells[(x, y)] = self.tick + 100
            self.events.append(("wave", self.tick, cx, cy, rad))
            self.next_wave = self.tick + 40 + r.below(60)
        if self.tick % 20 == 0:
            for k in [k for k, v in self.entropy_cells.items() if v <= self.tick]:
                del self.entropy_cells[k]

    def sys_econ(self):
        if self.tick % 10 == 0:
            for e in self.ents.values():
                if e.kind == "unit" and (e.id % 5 == 0):
                    self.res[e.f] += 1

    def sys_cleanup(self):
        dead = [i for i, e in self.ents.items() if e.hp <= 0]
        for i in dead:                          # ordem de id => determinístico
            e = self.ents.pop(i)
            self.occ.pop((e.x, e.y), None)
        # reposição simples para manter carga constante no benchmark
        if dead:
            r = self.rng["econ"]
            for _ in dead:
                for _ in range(20):
                    f = r.below(2)
                    x = r.below(W // 2) + (W // 2 if f else 0)
                    y = r.below(H)
                    if (x, y) not in self.walls and (x, y) not in self.occ:
                        e = Ent(self.next_id, f, x, y, 30, "unit")
                        self.next_id += 1
                        self.ents[e.id] = e
                        self.occ[(x, y)] = e.id
                        break

    SYSTEMS = ("sys_ai", "sys_move", "sys_combat", "sys_entropy", "sys_econ", "sys_cleanup")

    def step(self, order=None):
        self.tick += 1
        self.events = []
        for name in (order or self.SYSTEMS):
            getattr(self, name)()

    # ---- serialização ----
    def snapshot(self) -> dict:
        return {"tick": self.tick, "res": self.res, "next_id": self.next_id,
                "ents": [[e.id, e.f, e.x, e.y, e.hp, e.tgt, e.cd] for e in self.ents.values()],
                "entropy": sorted([x, y, v] for (x, y), v in self.entropy_cells.items()),
                "rng": {k: v.s for k, v in self.rng.items()}, "next_wave": self.next_wave}

    def state_hash(self) -> str:
        return hashlib.blake2b(json.dumps(self.snapshot(), separators=(",", ":")).encode(), digest_size=16).hexdigest()


def astar(start, goal, walls):
    openh = [(0, start)]
    g = {start: 0}
    while openh:
        _, cur = heapq.heappop(openh)
        if cur == goal:
            return g[cur]
        for dx, dy in DIRS:
            n = (cur[0] + dx, cur[1] + dy)
            if not (0 <= n[0] < W and 0 <= n[1] < H) or n in walls:
                continue
            ng = g[cur] + 1
            if ng < g.get(n, 1 << 30):
                g[n] = ng
                heapq.heappush(openh, (ng + max(abs(goal[0] - n[0]), abs(goal[1] - n[1])), n))
    return -1


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=300)
    ap.add_argument("--sizes", default="50,200,500,1000,2000")
    ap.add_argument("--ai-stagger", type=int, default=1)
    ap.add_argument("--chase", action="store_true", help="carga pesada: todos perseguem e lutam")
    ap.add_argument("--out", default="tick_bench_result.json")
    a = ap.parse_args()
    print(f"python {platform.python_version()} {platform.machine()} | {platform.processor() or 'cpu?'}")
    out = {"python": platform.python_version(), "rows": []}
    for n in [int(x) for x in a.sizes.split(",")]:
        s = Sim(n, ai_stagger=a.ai_stagger, chase=a.chase)
        times = []
        last = {}
        dl_ms, dl_b = [], []
        per_sys = {k: 0.0 for k in Sim.SYSTEMS}
        for _ in range(a.ticks):
            t0 = time.perf_counter()
            s.tick += 1
            s.events = []
            for name in Sim.SYSTEMS:
                ts = time.perf_counter()
                getattr(s, name)()
                per_sys[name] += time.perf_counter() - ts
            times.append((time.perf_counter() - t0) * 1000)
            td = time.perf_counter()                      # delta por tick: só entidades cujo (x,y,hp,tgt) mudou desde o último envio
            ch = [[e.id, e.x, e.y, e.hp] for e in s.ents.values() if last.get(e.id) != (e.x, e.y, e.hp)]
            for r in ch:
                last[r[0]] = (r[1], r[2], r[3])
            gone = [i for i in last if i not in s.ents]
            for i in gone:
                del last[i]
            msg = json.dumps({"t": "d", "k": s.tick, "u": ch, "r": gone}, separators=(",", ":"))
            dl_ms.append((time.perf_counter() - td) * 1000); dl_b.append(len(msg))
        t0 = time.perf_counter(); snap = json.dumps(s.snapshot(), separators=(",", ":")); t_snap = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter(); s.state_hash(); t_hash = (time.perf_counter() - t0) * 1000
        row = {"units": n, "alive": len(s.ents), "tick_ms_mean": round(statistics.mean(times), 3), "tick_ms_p99": round(pct(times, .99), 3),
               "tick_ms_max": round(max(times), 3), "snapshot_ms": round(t_snap, 2), "snapshot_kb": round(len(snap) / 1024, 1),
               "hash_ms": round(t_hash, 2), "delta_ms_mean": round(statistics.mean(dl_ms), 3), "delta_kb_mean": round(statistics.mean(dl_b) / 1024, 2), "sys_ms": {k: round(v / a.ticks * 1000, 3) for k, v in per_sys.items()}}
        out["rows"].append(row)
        print(json.dumps(row))
    # determinismo
    h = []
    for _ in range(2):
        s = Sim(300, seed=99)
        for _ in range(200):
            s.step()
        h.append(s.state_hash())
    s = Sim(300, seed=99)
    order = list(Sim.SYSTEMS); order[1], order[2] = order[2], order[1]
    for _ in range(200):
        s.step(order)
    s2 = Sim(300, seed=100)
    for _ in range(200):
        s2.step()
    print("determinismo: mesma seed/ordem =>", h[0] == h[1], "| ordem trocada =>", s.state_hash() == h[0], "| seed diferente =>", s2.state_hash() == h[0])
    # RNG
    import random
    r = SplitMix64(1); t0 = time.perf_counter()
    for _ in range(1_000_000):
        r.below(100)
    t_sm = time.perf_counter() - t0
    rr = random.Random(1); t0 = time.perf_counter()
    for _ in range(1_000_000):
        rr.random()
    t_mt = time.perf_counter() - t0
    print(f"RNG: SplitMix64.below {t_sm*1000:.0f} ms/1M | random.Random.random {t_mt*1000:.0f} ms/1M")
    # A*
    s = Sim(0)
    rg = SplitMix64(5); t0 = time.perf_counter(); n = 0; ok = 0
    for _ in range(300):
        st = (rg.below(W), rg.below(H)); go = (rg.below(W), rg.below(H))
        if st in s.walls or go in s.walls:
            continue
        n += 1; ok += astar(st, go, s.walls) >= 0
    t_a = (time.perf_counter() - t0) / max(n, 1) * 1000
    print(f"A* 64x64 (8-dir, ~8% paredes): {t_a:.2f} ms/caminho ({n} caminhos, {ok} encontrados)")
    # flow field (BFS 8-dir a partir do destino): 1 por destino, serve a todo o grupo
    from collections import deque
    t0 = time.perf_counter(); nb = 40
    for i in range(nb):
        goal = (i * 7 % W, i * 11 % H); dist = {goal: 0}; dq = deque([goal])
        while dq:
            c = dq.popleft()
            for dx, dy in DIRS:
                n2 = (c[0] + dx, c[1] + dy)
                if 0 <= n2[0] < W and 0 <= n2[1] < H and n2 not in s.walls and n2 not in dist:
                    dist[n2] = dist[c] + 1; dq.append(n2)
    t_bfs = (time.perf_counter() - t0) / nb * 1000
    print(f"flow field BFS 64x64: {t_bfs:.2f} ms/destino")
    out["bfs_ms"] = round(t_bfs, 2)
    out["astar_ms"] = round(t_a, 2); out["rng_ms_per_1M"] = {"splitmix": round(t_sm*1000), "mt_random": round(t_mt*1000)}
    json.dump(out, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
