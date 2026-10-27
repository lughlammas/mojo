"""F2 — mecânicas genéricas do núcleo de ticks: ordens, coleta, produção, construção, combate, limites, IA."""
import pytest

from mojo.pack import load_pack
from mojo.sim.loop import TickEngine
from .conftest import edit_json
from .simhelp import cmd, ents, first, run


def mk(poc, scenario="coop2"):
    return TickEngine(poc, scenario)


@pytest.fixture
def duel(poc, monkeypatch):
    """Versus sem IA ativa: permite testar combate de forma isolada (times inimigos)."""
    from mojo.sim import systems
    monkeypatch.setitem(systems.RUN, "ai", lambda eng, due: None)
    return TickEngine(poc, "duel")


def test_initial_state(poc):
    e = mk(poc)
    assert {x.type for x in ents(e, kind="s")} == {"forge_core", "bedrock_hall"}
    assert len(ents(e, kind="u")) == 4 and len(ents(e, kind="n")) == 4
    assert e.state.res["fire"]["essence"] == 90 and e.state.vars["entropy"] == 10
    cells = [(u.x, u.y) for u in ents(e, kind="u")]
    assert len(set(cells)) == len(cells)                  # unidades iniciais não empilham


def test_move_follows_speed_and_arrives(poc):
    e = mk(poc)
    u = first(e, owner="p1", kind="u")                    # ember_runner, speed_ticks=2
    x0, y0 = u.x, u.y
    assert cmd(e, "p1", "move", ids=[u.id], x=x0 + 6, y=y0) == []
    run(e, 6)
    assert 2 <= u.x - x0 <= 4                             # ~1 célula a cada 2 ticks (speed_ticks=2)
    run(e, 30)
    assert (u.x, u.y) == (x0 + 6, y0) and u.order is None


def test_move_to_rock_goes_to_nearest_free_cell(poc):
    e = mk(poc)
    u = first(e, owner="p1", kind="u")
    cmd(e, "p1", "move", ids=[u.id], x=0, y=0)           # (0,0) é rocha
    run(e, 80)
    assert (u.x, u.y) not in e.cs.rock and abs(u.x) <= 2 and abs(u.y) <= 2


def test_unreachable_target_emits_no_path(poc):
    e = mk(poc)
    u = first(e, owner="p1", kind="u")
    # fecha completamente a célula (14,10) com rocha adicionada em runtime (white-box)
    for c in [(13, 9), (14, 9), (15, 9), (13, 10), (15, 10), (13, 11), (14, 11), (15, 11)]:
        e.blocked.add(c)
    e.blocked.discard((14, 10))
    cmd(e, "p1", "move", ids=[u.id], x=14, y=10)
    evs = list(cmd.events)
    for _ in range(4):
        evs += e.step().events
    assert any(v["e"] == "no_path" and v.get("id") == u.id for v in evs)
    assert u.order is None and u.path is None            # nenhum caminho: ordem descartada


def test_gather_yields_resource_on_cooldown_and_depletes_node(poc):
    e = mk(poc)
    u = first(e, owner="p1", kind="u")
    node = min(ents(e, kind="n"), key=lambda n: (n.x - u.x) ** 2 + (n.y - u.y) ** 2)
    ctl = mk(poc)                                          # controle: mesma partida sem a ordem (renda passiva da regra)
    assert cmd(e, "p1", "gather", ids=[u.id], node=node.id) == []
    run(e, 120)
    run(ctl, 121)
    gained = e.state.res["fire"]["essence"] - ctl.state.res["fire"]["essence"]
    assert gained >= 8 and gained % 4 == 0               # 4 por coleta (dados do pacote)
    node.hp = 6
    run(e, 200)
    assert node.id not in e.state.ents and (node.x, node.y) not in e.blocked   # nó esgotado some e libera a célula


def test_train_cost_queue_and_supply(poc):
    e = mk(poc)
    core = first(e, owner="p1", kind="s")
    assert cmd(e, "p1", "train", structure=core.id, type="ember_runner") == []
    assert e.state.res["fire"]["essence"] == 60
    run(e, 40)
    assert len(ents(e, owner="p1", kind="u")) == 3 and not core.queue
    # suprimento: 10 de capacidade (2 iniciais + 1 treinado = 3); força até o teto
    e.state.res["fire"]["essence"] = 5000
    n = 0
    while True:
        rej = cmd(e, "p1", "train", structure=core.id, type="ember_runner")
        if rej:
            assert rej[0]["why"] in ("no_supply", "queue_full")
            if rej[0]["why"] == "no_supply":
                break
            run(e, 45)
        n += 1
        assert n < 30
    used, cap = e.supply("fire", "supply")
    assert used <= cap == 10


def test_train_validation_errors(poc):
    e = mk(poc)
    core = first(e, owner="p1", kind="s")
    assert cmd(e, "p1", "train", structure=core.id, type="stone_hauler")[0]["why"] == "cannot_produce"
    e.state.res["fire"]["essence"] = 0
    assert cmd(e, "p1", "train", structure=core.id, type="ember_runner")[0]["why"] == "no_resources"
    other = first(e, owner="p2", kind="s")
    assert cmd(e, "p1", "train", structure=other.id, type="basalt_warden")[0]["why"] == "not_owner"


def test_cancel_train_refunds(poc):
    e = mk(poc)
    core = first(e, owner="p1", kind="s")
    cmd(e, "p1", "train", structure=core.id, type="cinder_guard")
    assert e.state.res["fire"]["essence"] == 40
    assert cmd(e, "p1", "cancel_train", structure=core.id, index=0) == []
    assert e.state.res["fire"]["essence"] == 90 and not core.queue


def test_build_flow_and_supply_increase(poc):
    e = mk(poc)
    w = first(e, owner="p1", kind="u")
    sx, sy = w.x + 2, w.y + 2
    assert cmd(e, "p1", "build", id=w.id, type="ash_hut", x=sx, y=sy) == []
    site = first(e, type="ash_hut")
    assert site.bl == 60 and e.state.res["fire"]["essence"] == 50
    assert e.supply("fire", "supply")[1] == 10            # em obras não conta
    run(e, 30)
    assert 0 < site.bl < 60                               # construtor chegou e avança a obra
    run(e, 100)
    assert site.bl == 0 and e.supply("fire", "supply")[1] == 16 and w.order is None


def test_build_validation(poc):
    e = mk(poc)
    w = first(e, owner="p1", kind="u")
    assert cmd(e, "p1", "build", id=w.id, type="ash_hut", x=0, y=0)[0]["why"] == "bad_placement"      # rocha
    assert cmd(e, "p1", "build", id=w.id, type="ash_hut", x=w.x, y=w.y)[0]["why"] == "bad_placement"   # em cima de unidade
    assert cmd(e, "p1", "build", id=w.id, type="stabilizer", x=5, y=5)[0]["why"] == "cannot_build"
    e.state.res["fire"]["essence"] = 10
    assert cmd(e, "p1", "build", id=w.id, type="ash_hut", x=5, y=5)[0]["why"] == "no_resources"


def test_command_validation_rejects_bad_input(poc):
    e = mk(poc)
    u = first(e, owner="p1", kind="u")
    foe = first(e, owner="p2", kind="u")
    for args, why in [({"ids": [foe.id], "x": 3, "y": 3}, "not_owner"), ({"ids": [99999], "x": 3, "y": 3}, "no_such_entity"),
                      ({"ids": [u.id], "x": 999, "y": 3}, "out_of_grid"), ({"ids": [u.id], "x": 3}, "bad_args"),
                      ({"ids": [u.id], "x": 3, "y": 3, "z": 1}, "bad_args"), ({"ids": [], "x": 3, "y": 3}, "bad_args"),
                      ({"ids": list(range(1, 100)), "x": 3, "y": 3}, "bad_args"), ({"ids": [True], "x": 3, "y": 3}, "bad_args"),
                      ({"ids": [u.id], "x": 1.5, "y": 3}, "bad_args"), ({"ids": [u.id], "x": 3, "y": 3 * 10**9}, "bad_args"),
                      ({"ids": [u.id], "x": 40, "y": 3}, "out_of_grid")]:
        assert cmd(e, "p1", "move", **args)[0]["why"] == why, (args, why)
    assert cmd(e, "p1", "teleport", ids=[u.id])[0]["why"] == "unknown_command"
    assert cmd(e, "p9", "move", ids=[u.id], x=3, y=3)[0]["why"] == "unknown_slot"
    assert cmd(e, "p1", "gather", ids=[u.id], node=first(e, kind="s").id)[0]["why"] == "bad_target"


def test_combat_damage_cooldown_and_status_modifier(poc, duel):
    e = duel
    g = e._make(poc.types["cinder_guard"], "p1", 8, 6)
    t = e._make(poc.types["basalt_warden"], "p2", 9, 6)
    hp0 = t.hp
    cmd(e, "p1", "attack", ids=[g.id], target=t.id)       # em alcance: golpeia no próprio tick
    assert t.hp == hp0 - 7                                # dano 7 (dados do pacote)
    run(e, 7)
    assert t.hp == hp0 - 7                                # recarga de 8 ticks
    run(e, 1)
    assert t.hp == hp0 - 14
    e.set_status(g, "inflamed", 100)                      # +300 permille de dano
    run(e, 8)
    assert t.hp == hp0 - 14 - 7 * 1300 // 1000


def test_idle_attackers_acquire_enemies_in_aggro_range(poc, duel):
    e = duel
    g = e._make(poc.types["cinder_guard"], "p1", 8, 6)
    t = e._make(poc.types["basalt_warden"], "p2", 10, 6)
    run(e, 40)
    assert t.hp < t.maxhp or t.dead


def test_dead_entities_are_removed_and_events_fire(poc, duel):
    e = duel
    g = e._make(poc.types["cinder_guard"], "p1", 8, 6)
    t = e._make(poc.types["basalt_warden"], "p2", 9, 6)
    t.hp = 1
    n0 = e.n_alive
    cmd(e, "p1", "attack", ids=[g.id], target=t.id)
    evs = list(cmd.events)
    for _ in range(5):
        evs += e.step().events
    assert any(v["e"] == "unit_died" and v["id"] == t.id for v in evs)
    assert t.id not in e.state.ents and e.n_alive == n0 - 1


def test_structure_destruction_blocks_and_unblocks_cells(poc, duel):
    e = duel
    s = first(e, owner="p2", kind="s")
    cells = {(s.x + dx, s.y + dy) for dx in range(s.size) for dy in range(s.size)}
    assert cells <= e.blocked
    s.hp = 0
    run(e, 2)
    assert not (cells & e.blocked)


def test_max_entities_limit_enforced(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d["sim"].update(max_entities=10))
    p = load_pack(pack_copy)
    e = TickEngine(p, "coop2")
    core = first(e, owner="p1", kind="s")
    e.state.res["fire"]["essence"] = 5000
    why = None
    for _ in range(12):
        r = cmd(e, "p1", "train", structure=core.id, type="ember_runner")
        run(e, 45)
        if r:
            why = r[0]["why"]
            break
    assert why == "limit_entities" and e.n_alive <= 10


def test_max_paths_per_tick_is_respected(poc):
    e = mk(poc)
    ids = []
    for i in range(20):
        ids.append(e._make(poc.types["ember_runner"], "p1", 3 + i % 8, 1 + i // 8).id)
    e.stats["paths"] = 0
    for chunk in (ids[:10], ids[10:20]):
        e.submit(e.state.tick + 1, "p1", len(e.cmd_log) + len(e._pending) + 1, "move", {"ids": chunk, "x": 12, "y": 9})
    e.step()
    assert e.stats["paths"] <= e.limits["max_paths_per_tick"]
    run(e, 5)
    assert e.stats["paths"] >= 20                         # todos acabam atendidos (fila FIFO)
    assert all(first_.path is not None for first_ in [e.state.ents[i] for i in ids])


def test_game_over_freezes_simulation(poc):
    e = mk(poc, "mini")
    r = run(e, 400)
    assert e.state.result and r.finished
    t = e.state.tick
    assert e.step().finished and e.state.tick == t
    u = first(e, owner="p1", kind="u")
    e.submit(t + 1, "p1", 1, "move", {"ids": [u.id], "x": 3, "y": 3})
    assert e.step().finished


def test_scripted_ai_builds_trains_gathers_and_attacks(poc):
    e = TickEngine(poc, "ai_duel")
    seen = {"trained": 0, "built": 0, "faction_eliminated": 0}
    min_res = 10**9
    for _ in range(1500):
        r = e.step()
        for ev in r.events:
            if ev["e"] in seen:
                seen[ev["e"]] += 1
        min_res = min(min_res, *(v for f in e.state.res.values() for v in f.values()))
        if r.finished:
            break
    assert seen["trained"] >= 15 and seen["built"] >= 2          # economia e construção
    assert e.state.result is not None                            # a IA atacou e a partida terminou
    assert min_res >= 0                                          # IA não trapaceia: recursos nunca negativos
    assert e.cmd_log == []                                       # IA não entra no log de comandos humanos


def test_four_faction_scenario_runs_with_all_ai(elem):
    e = TickEngine(elem, "quarteto_ai")
    r = run(e, 3000)
    assert e.state.result and e.state.result["who"] == "last_team" and len(e.state.result["won"]) == 1
