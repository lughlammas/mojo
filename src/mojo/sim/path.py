"""Pathfinding A* inteiro, 8 direções sem cortar quina. Determinístico (desempate por contador de inserção)."""
from __future__ import annotations

import heapq

DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))
MAX_EXPANSIONS = 6000


def nearest_free(eng, x: int, y: int, maxr: int = 12, avoid_units: bool = False):
    """Célula livre mais próxima de (x,y) (varredura em anéis, ordem fixa) ou None. `avoid_units` evita empilhar unidades."""
    w, h, blocked = eng.cs.width, eng.cs.height, eng.blocked
    taken = {(e.x, e.y) for e in eng.state.ents.values() if e.kind == "u" and not e.dead} if avoid_units else ()
    for r in range(0, maxr + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                cx, cy = x + dx, y + dy
                if 0 <= cx < w and 0 <= cy < h and (cx, cy) not in blocked and (cx, cy) not in taken:
                    return cx, cy
    return None


def find_path(eng, sx: int, sy: int, tx: int, ty: int, tsize: int, reach: int):
    """Caminho (lista de células, sem a inicial) até uma célula livre a distância (Chebyshev) <= reach do retângulo alvo.
    Devolve [] se já está no alvo e None se não há caminho (ou o orçamento de expansões acabou)."""
    w, h, blocked = eng.cs.width, eng.cs.height, eng.blocked
    x1, y1 = tx + tsize - 1, ty + tsize - 1

    def goal(x, y):
        dx = tx - x if x < tx else x - x1 if x > x1 else 0
        dy = ty - y if y < ty else y - y1 if y > y1 else 0
        return max(dx, dy) <= reach and (x, y) not in blocked

    def heur(x, y):
        dx = tx - x if x < tx else x - x1 if x > x1 else 0
        dy = ty - y if y < ty else y - y1 if y > y1 else 0
        o = 10 * max(dx, dy) + 4 * min(dx, dy) - 10 * reach
        return o if o > 0 else 0

    if goal(sx, sy):
        return []
    g = {(sx, sy): 0}
    parent = {}
    cnt = 0
    heap = [(heur(sx, sy), 0, (sx, sy))]
    closed = set()
    exp = 0
    while heap:
        _, _, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        closed.add(cur)
        x, y = cur
        if goal(x, y):
            out = []
            while cur != (sx, sy):
                out.append([cur[0], cur[1]])
                cur = parent[cur]
            out.reverse()
            return out
        exp += 1
        if exp > MAX_EXPANSIONS:
            return None
        gc = g[cur]
        for i, (dx, dy) in enumerate(DIRS):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or (nx, ny) in blocked:
                continue
            if i >= 4 and ((x + dx, y) in blocked or (x, y + dy) in blocked):
                continue
            ng = gc + (10 if i < 4 else 14)
            n = (nx, ny)
            if ng < g.get(n, 1 << 30):
                g[n] = ng
                parent[n] = cur
                cnt += 1
                heapq.heappush(heap, (ng + heur(nx, ny), cnt, n))
    return None
