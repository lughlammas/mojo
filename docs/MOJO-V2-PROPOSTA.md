# MOJO V2 — Proposta técnica de reestruturação (fábrica modular de jogos de prototipagem rápida)

**Projeto:** Dream Fabrics · **Componente:** MOJO · **Formato:** `.mjo` · **Data:** 27/10/2026 · **Estado: PROPOSTA — nada do V2 foi implementado no MOJO v0.1.**
Esta proposta não altera o MOJO v0.1 (`src/`, `tests/`, `examples/` intactos; 200 testes coletados: 196 passed + 4 skipped, reexecutados ao final desta tarefa) nem o Ragnarok. Os artefatos novos desta proposta ficam só em `docs/v2/` (exemplos, schemas, protótipos descartáveis e medições).

## 0. Como ler este documento

Cada afirmação importante traz um rótulo:

| Rótulo | Significado |
|---|---|
| **[V]** | **Verificado** no código real de `/workspace/mojo` (ou do Ragnarok), com arquivo/função citados. |
| **[M]** | **Medido na box** (Linux, Xeon 8 vCPU de nuvem, Python 3.12.15 e 3.13.5). **Não é o PC do Gui** (i5-12450H, 7,7 GB, Windows 11, Python 3.12). |
| **[T]** | **Testado por um protótipo descartável** em `docs/v2/` (schema + verificador, esqueleto de ticks/replay, handshake WebSocket). Prova a ideia, não é o código final. |
| **[I]** | **Inferência** minha (conhecimento geral ou extrapolação). Não verificada. |
| **[P]** | **Projeto/proposta**: decisão de desenho que ainda não existe em código. |

**Nomes, unidades, custos e números do jogo de exemplo (4 facções Ar/Água/Fogo/Terra) são EXEMPLO de balanceamento, marcados como tal nos arquivos. Não são canon de Azrael nem de nenhuma obra.** As 4 facções elementais são pedido do Gui.

### Resumo executivo
1. **Reaproveita** quase toda a "casca" do v0.1: carregador estrito (`world/loader.py`), caminhos seguros (`world/paths.py`), versionamento (`world/migrations.py`), adaptador do Ragnarok com cache/timeout/disjuntor (`audio/ragnarok.py`), adaptador semântico (`semantic/base.py`), saves atômicos (`store/saves.py`), config (`config.py`). **[V]**
2. **Refatora** o que é "uma ação = um turno": `engine/loop.py::Game.step` vira o perfil `turn-text-v0` (continua funcionando como hoje); um novo perfil `tick-grid-v0` roda um **núcleo de ticks determinísticos** com comandos enfileirados, ordem fixa de sistemas, RNG por sistema, snapshots e replay.
3. **Descarta** (no perfil RTS): `engine/actions.py` (parser de verbos), `engine/events.py::requires_met/validate_event` como estão (viram um *registro de efeitos* e uma *mini-linguagem de expressões*), `store/logs.py::SessionLog.write` por tick (fsync por registro) e o modelo de "cena" para jogos de grid.
4. **DSL modular**: `world.mjo` (manifesto) + `factions/`, `resources/`, `rules/`, `scenarios/`, `assets/`, todos em **JSON** estrito. Regras = condições/efeitos **declarativos** com whitelist de operadores, só inteiros, compilados para *closures* no carregamento. **Sem `eval`, sem código.**
5. **Arquitetura**: backend Python local (FastAPI + uvicorn + `websockets`) em `127.0.0.1`, **servidor autoritativo**, cliente web com **canvas 2D** em módulos ES, sem CDN e sem build. **[T]** Handshake com Origin/Host/token e limites testado na box.
6. **Atenção, achado real:** o venv do Ragnarok **não tem biblioteca de WebSocket** (`uvicorn` sem `[standard]`/`websockets`); sem ela o uvicorn responde 404 ao upgrade. O MOJO V2 precisa do **seu próprio venv** com `websockets`. **[V][T]**
7. **Desempenho (estimativa, não promessa):** núcleo de ticks em Python puro é viável para um RTS **pequeno/médio**: ~400 entidades confortáveis, ~800 com otimizações, ≥1.500 é projeto. Os números de base são **[M]** na box; a extrapolação para o PC do Gui é **[I]**.
8. **Prova de conceito do mesmo dia:** `docs/v2/example/poc-mini/` (grid 16×12, Fogo + Terra, 1 recurso, 1 onda de entropia) — já **válido** pelo verificador **[T]**; o motor que o executa é o que falta escrever (§5.6).

---

## 1. Diagnóstico do v0.1 → o que reaproveita, refatora, descarta

Medida de tamanho **[V]**: `engine/loop.py` 269 linhas, `state.py` 90, `actions.py` 82, `events.py` 102, `world/loader.py` 213 (total do pacote ≈ 1.920 linhas).

| Arquivo / função real | O que faz hoje **[V]** | Destino no V2 | Por quê |
|---|---|---|---|
| `world/paths.py::check_relative_path`, `resolve_inside` | Valida caminho relativo (sem `..`, drive, UNC, `\`, nomes reservados Windows, symlink) | **REAPROVEITA sem mudar** | É exatamente o que `includes`, `mods` e `assets` precisam. 35 casos de teste já cobrem. |
| `world/loader.py::_reject_dupes`, `_reject_const`, `_depth`, `load_world` (limite `MAX_FILE_BYTES=1_000_000`, UTF-8, JSON estrito) | Pipeline seguro de leitura de **um** arquivo | **REFATORA → `pack/loader.py`** | Mesma disciplina, mas para **N arquivos** (manifesto + partes), com limite por arquivo e total do pacote; seleção de schema por `kind`. |
| `world/loader.py::_schema_errors`, `_jpath`, `WorldError.format` | Erros legíveis com caminho JSON | **REAPROVEITA** | Mesma UX de erro para partes (`factions/fire.json: units[1].hp: ...`). |
| `world/loader.py::_semantic_errors` | Referências cruzadas de cenas/saídas/entidades | **MOVE** para `profiles/turn_text/` | É específica de aventura textual. O RTS tem outro conjunto de checagens (ver `docs/v2/bench/check_example.py`). |
| `world/migrations.py::SUPPORTED=(0,1)`, `MIGRATIONS={}`, `ensure_supported` | Aceita só 0.1.x; migra se houver função registrada (testado) | **REAPROVEITA + usa de verdade** | `SUPPORTED=(0,2)` e `MIGRATIONS[(0,1)]=migrate_0_1_to_0_2` (função em `docs/v2/skeleton/mojo_v2/pack/migrate.py`, **[T]** testada com o `azrael.mjo` real). Primeiro uso real do mecanismo. |
| `engine/loop.py::Game.step` (l. 99–219) | 1 ação do jogador → proposta do adaptador → validação → novo estado (`self.state = new`, l. 197) → log | **MANTÉM como perfil `turn-text-v0`** | Não quebrar o modo texto. É por turno, síncrono, centrado em `parse_command`; não serve de base para tick. |
| `engine/loop.py::Game._request_audio` (l. 227–245) + `ThreadPoolExecutor(max_workers=1)` (l. 58) | Áudio em thread, nunca levanta, loga | **EXTRAI → `audio/dispatch.py::AudioDispatcher`** | O RTS precisa do mesmo padrão (narração de ondas sem bloquear o tick). |
| `engine/state.py::GameState` (`to_dict`, `copy`, `hash` l. 38, `validate_state_dict`) | Estado serializável + hash canônico | **MANTÉM p/ texto; PADRÃO reaproveitado** em `sim/state.py::SimState` | Mesma ideia: JSON canônico → hash. No V2 usa `blake2b` (mais rápido) e inclui o estado dos RNGs. |
| `engine/actions.py::parse_command`, `resolve_entity`, `resolve_exit`, `norm` | Interpreta linha de texto (verbos PT/EN) | **MANTÉM p/ texto; DESCARTADO no RTS** | Comando do RTS é um objeto JSON estruturado vindo do navegador (`sim/commands.py`). |
| `engine/events.py::validate_event`, `apply_event`, `requires_met`, lista fechada `EVENT_TYPES` | Whitelist de 5 eventos + condição `requires` declarativa | **GENERALIZA → `sim/effects.py` + `pack/expr.py`** | A ideia (lista fechada, validar antes de aplicar, `requires` sem código) é a semente da mini-linguagem V2. O protótipo `docs/v2/bench/expr_proto.py` é o primeiro rascunho. |
| `semantic/base.py::SemanticAdapter`, `Context`, `Proposal`, `proposal_from_obj`, `semantic/mock.py`, `semantic/openai_compat.py` | Interface modelo-propõe/núcleo-decide, mock sem rede, local/remoto desligados | **REAPROVEITA** | No RTS o adaptador **não fica no caminho do tick** (ver §3.7): narra eventos e ajuda na autoria offline. |
| `audio/ragnarok.py::RagnarokAdapter.synthesize/health_check`, cache por hash, disjuntor, `_http` com timeout total | Fala com `GET /api/status` e `POST /v1/audio/speech` | **REAPROVEITA sem mudar** (+ rota de entrega do WAV, §3.6) | Já tem timeout próprio (20 s), cache e degradação. **Bloqueante** ⇒ sempre em thread. |
| `store/saves.py::save_state/load_state` (tmp+fsync+`os.replace`+`.bak`) | Save atômico validado | **REAPROVEITA** p/ snapshots de partida | Mesmo padrão; payload passa a ser `SimState`. |
| `store/logs.py::SessionLog.write` (abre, escreve, `flush`, `os.fsync` **por registro**, l. 56) | Log JSONL | **MANTÉM p/ texto; NÃO usar por tick** | **[M]** custo na box: 0,178 ms/registro com fsync vs 1,13 ms para 300 registros com 1 fsync. No Windows tende a ser pior **[I]**. RTS grava **comandos + checkpoints em lote** (`sim/replay.py`). |
| `config.py::RagnarokConfig`, `_take`, `_check_url`, `load_config` | Config estrita, só loopback, sem segredo no arquivo | **REAPROVEITA + `ServerConfig`** | Acrescenta `host/port/allowed_origins`; mesma regra de loopback. |
| `cli.py::build_parser`, `repl`, `cmd_play`, `cmd_validate`, `cmd_audio_check` | CLI textual | **MANTÉM + novos subcomandos** `serve`, `validate` (pacotes), `replay` | `mojo play` não muda. |
| `render/text.py` | Renderização textual | **MANTÉM** | Só o perfil texto usa. |
| `world/mojo-world-0.1.schema.json` | Schema v0.1 (`additionalProperties:false`) | **MANTÉM** (carregado para `kind="text-adventure"`) | Compatibilidade. Os schemas v0.2 são novos. |

Fatos do Ragnarok relevantes **[V]**: `ragnarok/server.py` tem o middleware `@app.middleware("http")` `guard` (Host local sempre; Origin só em métodos que alteram) — **middleware HTTP não cobre o handshake WebSocket**, então o MOJO V2 precisa da própria checagem (já escrita e testada em `docs/v2/skeleton/mojo_v2/server/security.py`). `requirements.txt` do Ragnarok lista `fastapi>=0.110`, `uvicorn>=0.30` (sem `websockets`). Verifiquei no venv do Ragnarok: `fastapi 0.162.0`, `uvicorn 0.54.0`, `starlette 1.10.0`, **sem `websockets` nem `wsproto`**; um app de teste com rota `@app.websocket` respondeu **HTTP 404** ao upgrade com o aviso *"No supported WebSocket library detected"* **[T]**.

---

## 2. Pilar 1 — DSL / manifesto modular `.mjo`

### 2.1 Decisão de formato: JSON (e por quê não YAML/TOML)

**Decisão [P]: JSON estrito UTF-8 em runtime, para o manifesto (`world.mjo`) e para todas as partes.**

| Critério | JSON | YAML | TOML |
|---|---|---|---|
| Parser na stdlib do Python 3.12 | **sim** (`json`) **[V]** o v0.1 já usa | não (PyYAML = dependência extra) | só leitura (`tomllib`); escrita exige lib |
| Segurança do parser | simples; já tratamos duplicatas/NaN/profundidade em `loader.py` **[V]** | tipos implícitos (`no`→`false`, `1e3`), âncoras/aliases (explosão), tags (`!!python/...` em loaders inseguros) **[I]** | seguro, mas sem nulos e com arrays de tabelas pouco ergonômicos |
| Árvores de expressão aninhadas (regras) | natural | natural | **ruim** (tabelas inline aninhadas) |
| Comentários | **não** | sim | sim |
| Compatibilidade com v0.1 e com `jsonschema` | total | converte | converte |

Contra: JSON não tem comentários e é verboso. **Mitigações [P]:** (a) campo `note`/`meta.note` (já existe no v0.1) e um `"$comment"` ignorado pelo carregador nas partes; (b) formatação "compacta-legível" (os exemplos abaixo usam objetos curtos em uma linha); (c) **opcional e fora do runtime:** um utilitário `mojo fmt` e, se o Gui quiser, autoria em YAML convertida para JSON por uma ferramenta de desenvolvimento — o motor **nunca** lê YAML. Isso mantém a superfície de ataque do carregador igual à do v0.1.

### 2.2 Estrutura de arquivos de um pacote de jogo

```text
packs/elemental-proto/          # "pacote" = pasta; futuro: .mjopack (zip assinado)  [P]
  world.mjo                     # MANIFESTO (ponto de entrada; extensão .mjo preservada)
  resources/core.json           # kind=resources : recursos do jogo
  factions/air.json water.json fire.json earth.json    # kind=faction : unidades, estruturas, regras próprias
  rules/economy.json entropy.json victory.json         # kind=rules   : variáveis, streams de RNG, regras globais
  scenarios/coop_vs_entropy.json duel_fire_water.json  # kind=scenario: mapa, times, jogadores, parâmetros
  assets/theme.json             # kind=theme   : cores/tamanho de célula (dados; sem imagens obrigatórias)
```

Regras do pacote **[P]** (validáveis, e já aplicadas pelo verificador **[T]**):
- Só `world.mjo` é lido pelo nome; **tudo mais entra por `includes`** (lista explícita por tipo). Nada de glob/diretório implícito.
- **Cada caminho** passa por `world/paths.py::check_relative_path` + `resolve_inside(root, rel)` **[V]** (sem `..`, absoluto, drive, UNC, `\`, symlink que escapa).
- Limites: 1 MB por arquivo (`MAX_FILE_BYTES` já existe **[V]**), 256 KB por parte (proposto), ≤ 64 partes, ≤ 8 MB no pacote.
- Cada parte declara `format: "dream-fabrics/mojo-part"`, `schema_version`, `kind`, `id`; `id` único por tipo.
- `pack_sha256` = hash ordenado de (caminho, sha256 do arquivo) — vai no cabeçalho do replay e dos saves (reprodutibilidade).
- Ordem de carga **determinística**: ordem das listas em `includes`; dentro do arquivo, ordem de declaração. A ordem das regras é a ordem de execução.

### 2.3 O manifesto `world.mjo` (exemplo válido) **[T]**

Mudanças em relação ao v0.1 `world.mjo`/`azrael.mjo`: novos `kind`, `engine`, `sim`, `includes`, `mods`, `ui`, `modes`; `semantics` e `audio` **iguais** ao v0.1 (o Ragnarok e o adaptador semântico continuam funcionando).

```json
{
  "format": "dream-fabrics/mojo-world",
  "schema_version": "0.2.0",
  "id": "elemental-proto",
  "title": "Protótipo Elemental (exemplo, não canônico)",
  "kind": "rts-grid",
  "meta": {
    "canon": false,
    "author": "Dream Fabrics — proposta MOJO V2",
    "note": "Exemplo técnico. As 4 facções elementais são pedido do Gui; nomes, unidades e números são EXEMPLO de balanceamento, não canon."
  },
  "engine": {"profile": "tick-grid-v0", "min_mojo": "2.0.0"},
  "sim": {
    "tick_hz": 10,
    "seed": 20261027,
    "max_entities": 600,
    "max_effects_per_tick": 4000,
    "max_rule_nodes": 64,
    "max_wave_radius": 12
  },
  "includes": {
    "resources": ["resources/core.json"],
    "factions": ["factions/air.json", "factions/water.json", "factions/fire.json", "factions/earth.json"],
    "rules": ["rules/economy.json", "rules/entropy.json", "rules/victory.json"],
    "scenarios": ["scenarios/coop_vs_entropy.json", "scenarios/duel_fire_water.json"]
  },
  "mods": [],
  "ui": {
    "theme": "assets/theme.json",
    "panels": ["resources", "selection", "commands", "wave_forecast", "log"]
  },
  "modes": {
    "coop_vs_entropy": {"min_players": 1, "max_players": 4, "friendly_fire": false, "shared_victory": true},
    "versus": {"min_players": 2, "max_players": 4, "friendly_fire": false, "shared_victory": false}
  },
  "semantics": {
    "narration_style": "épica sóbria e concisa",
    "model_adapter": "configurable",
    "generation_constraints": ["respect_world_rules", "do_not_mutate_state_directly"]
  },
  "audio": {"provider": "ragnarok", "enabled": true, "voice_profile": "narrator_default"}
}
```

Campos novos (todos validados pelo schema `docs/v2/schema/mojo-world-0.2.schema.json`, `additionalProperties:false`):

| Campo | Significado | Limite proposto |
|---|---|---|
| `kind` | `text-adventure` (v0.1 migrado) ou `rts-grid` | enum fechado |
| `engine.profile` / `min_mojo` | perfil de execução (`turn-text-v0`, `tick-grid-v0`) e versão mínima do motor | enum fechado |
| `sim.tick_hz` | ticks por segundo da simulação | 1–30 (padrão 10) |
| `sim.seed` | seed mestre padrão (o cenário pode sobrepor) | inteiro |
| `sim.max_entities`, `max_effects_per_tick`, `max_rule_nodes`, `max_wave_radius` | **orçamentos** que o motor faz cumprir (§3.5) | ≤ 5000 / 100000 / 256 / 64 |
| `includes` | listas de caminhos por tipo | ≤ 64 por tipo |
| `mods[]` | extensão futura (§2.8) | ≤ 16 |
| `modes` | `coop_vs_entropy`, `versus`: jogadores mín/máx, fogo amigo, vitória compartilhada | — |
| `ui.panels` | painéis do cliente web (enum fechado) | — |

### 2.4 Recursos, facções e unidades (exemplo) **[T]**

`resources/core.json` (2 recursos: `essence` coletável e `supply` derivado) e `assets/theme.json` (cores por facção) estão em `docs/v2/example/elemental-proto/`. As **4 facções assimétricas** (números = EXEMPLO de balanceamento):

**Assimetria por dados, não por código:** cada facção tem `tags` nas unidades (`wave_pushed`, `regen`, `wave_fed`, …), `traits` descritivos e **regras próprias** (`rules[]`) filtradas por facção/tag. A regra padrão de dano da onda (`wave_hit_default`, em `rules/entropy.json`) **exclui** quem tem as tags `wave_pushed`/`wave_fed`/`wave_immune`; a facção então trata a onda do seu jeito:

| Facção | Identidade (exemplo) | Reação à entropia | Custo/risco |
|---|---|---|---|
| **Ar** | rápida (`speed_ticks:1`), frágil (HP 12–16), `gust` empurra inimigos | onda **empurra** as unidades (`push` em vez de dano) | HP baixo; estruturas fracas |
| **Água** | economia forte (`gather` 5), regeneração (+1 HP/30 ticks), cura em área | onda **erode estruturas** (dano extra) | estruturas vulneráveis à entropia |
| **Fogo** | dano alto (7–9), alcance 3 | onda **alimenta** (cura 2 + status `inflamed` +30% dano) | **definha quando entropia < 10** (−1 HP/20 ticks) |
| **Terra** | lenta (`speed_ticks:4`), muito durável, `entropy_resist` 60 | onda quase irrelevante | `stabilizer` **reduz a entropia global** (−3/50 ticks) — tensão cooperativa com o Fogo, que a quer alta |

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "faction",
  "id": "fire",
  "name": "Fogo",
  "element": "fire",
  "traits": ["aggressive", "entropy_feeding", "starves_when_calm"],
  "start": {
    "resources": {"essence": 90},
    "structures": [{"type": "forge_core", "at": "spawn"}],
    "units": [{"type": "ember_runner", "count": 2}]
  },
  "structures": [
    {
      "id": "forge_core",
      "name": "Núcleo-Forja",
      "tags": ["structure", "core"],
      "hp": 300,
      "size": 2,
      "cost": {},
      "build_ticks": 0,
      "produces": ["ember_runner", "cinder_guard", "pyre_thrower"],
      "provides": {"supply": 10},
      "entropy_resist": 20
    }
  ],
  "units": [
    {
      "id": "ember_runner",
      "name": "Corredor de Brasa",
      "tags": ["unit", "worker", "wave_fed"],
      "hp": 24,
      "speed_ticks": 2,
      "cost": {"essence": 30},
      "build_ticks": 40,
      "entropy_resist": 0,
      "gather": {"resource": "essence", "amount": 4, "cooldown_ticks": 20}
    },
    {
      "id": "cinder_guard",
      "name": "Guarda de Cinza",
      "tags": ["unit", "wave_fed"],
      "hp": 34,
      "speed_ticks": 3,
      "cost": {"essence": 50},
      "build_ticks": 70,
      "entropy_resist": 0,
      "attack": {"damage": 7, "range": 1, "cooldown_ticks": 8, "damage_kind": "fire"}
    },
    {
      "id": "pyre_thrower",
      "name": "Lança-Pira",
      "tags": ["unit", "wave_fed"],
      "hp": 20,
      "speed_ticks": 3,
      "cost": {"essence": 70},
      "build_ticks": 90,
      "entropy_resist": 0,
      "attack": {"damage": 9, "range": 3, "cooldown_ticks": 14, "damage_kind": "fire"}
    }
  ],
  "statuses": [{"id": "inflamed", "ticks": 50, "modifiers": {"damage_permille": 300}}],
  "rules": [
    {
      "id": "fire_fed_by_wave",
      "on": {"event": "wave_hit_entity"},
      "for": "entity",
      "filter": {"faction": "fire", "tag": "wave_fed"},
      "do": [
        {"op": "heal", "to": "self", "amount": 2},
        {"op": "status", "to": "self", "status": "inflamed", "ticks": 50}
      ]
    },
    {
      "id": "fire_starves_when_calm",
      "on": {"every_ticks": 20},
      "for": "entity",
      "filter": {"faction": "fire", "tag": "wave_fed"},
      "when": {"lt": [{"ref": "var.entropy"}, 10]},
      "do": [{"op": "damage", "to": "self", "amount": 1, "kind": "entropy"}]
    }
  ]
}
```

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "faction",
  "id": "earth",
  "name": "Terra",
  "element": "earth",
  "traits": ["slow", "durable", "entropy_stabilizing"],
  "start": {
    "resources": {"essence": 110},
    "structures": [{"type": "bedrock_hall", "at": "spawn"}],
    "units": [{"type": "stone_hauler", "count": 2}]
  },
  "structures": [
    {
      "id": "bedrock_hall",
      "name": "Salão de Rocha",
      "tags": ["structure", "core"],
      "hp": 400,
      "size": 2,
      "cost": {},
      "build_ticks": 0,
      "produces": ["stone_hauler", "basalt_warden"],
      "provides": {"supply": 10},
      "entropy_resist": 20
    },
    {
      "id": "stabilizer",
      "name": "Estabilizador",
      "tags": ["structure"],
      "hp": 140,
      "size": 1,
      "cost": {"essence": 80},
      "build_ticks": 100,
      "provides": {"supply": 0},
      "entropy_resist": 60
    }
  ],
  "units": [
    {
      "id": "stone_hauler",
      "name": "Carregador de Pedra",
      "tags": ["unit", "worker"],
      "hp": 40,
      "speed_ticks": 4,
      "cost": {"essence": 35},
      "build_ticks": 50,
      "entropy_resist": 60,
      "gather": {"resource": "essence", "amount": 5, "cooldown_ticks": 24}
    },
    {
      "id": "basalt_warden",
      "name": "Guardião de Basalto",
      "tags": ["unit"],
      "hp": 60,
      "speed_ticks": 4,
      "cost": {"essence": 60},
      "build_ticks": 90,
      "entropy_resist": 60,
      "attack": {"damage": 7, "range": 1, "cooldown_ticks": 10, "damage_kind": "physical"}
    }
  ],
  "rules": [
    {
      "id": "earth_stabilize",
      "on": {"every_ticks": 50},
      "for": "entity",
      "filter": {"faction": "earth", "type": "stabilizer"},
      "do": [{"op": "var_add", "var": "entropy", "amount": -3}]
    }
  ]
}
```

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "faction",
  "id": "air",
  "name": "Ar",
  "element": "air",
  "traits": ["fast", "fragile", "entropy_displaced"],
  "start": {
    "resources": {"essence": 100},
    "structures": [{"type": "sky_spire", "at": "spawn"}],
    "units": [{"type": "gale_scout", "count": 2}]
  },
  "structures": [
    {
      "id": "sky_spire",
      "name": "Pináculo",
      "tags": ["structure", "core"],
      "hp": 220,
      "size": 2,
      "cost": {},
      "build_ticks": 0,
      "produces": ["gale_scout", "zephyr_lancer", "storm_caller"],
      "provides": {"supply": 10},
      "entropy_resist": 20
    },
    {
      "id": "wind_perch",
      "name": "Poleiro",
      "tags": ["structure", "wave_immune"],
      "hp": 60,
      "size": 1,
      "cost": {"essence": 40},
      "build_ticks": 60,
      "provides": {"supply": 4},
      "entropy_resist": 0
    }
  ],
  "units": [
    {
      "id": "gale_scout",
      "name": "Batedor de Rajada",
      "tags": ["unit", "worker", "wave_pushed"],
      "hp": 14,
      "speed_ticks": 1,
      "cost": {"essence": 25},
      "build_ticks": 40,
      "entropy_resist": 0,
      "gather": {"resource": "essence", "amount": 3, "cooldown_ticks": 20}
    },
    {
      "id": "zephyr_lancer",
      "name": "Lanceiro do Zéfiro",
      "tags": ["unit", "wave_pushed"],
      "hp": 16,
      "speed_ticks": 1,
      "cost": {"essence": 40},
      "build_ticks": 60,
      "entropy_resist": 0,
      "attack": {"damage": 4, "range": 2, "cooldown_ticks": 8, "damage_kind": "physical"}
    },
    {
      "id": "storm_caller",
      "name": "Evocador de Tempestade",
      "tags": ["unit", "wave_pushed"],
      "hp": 12,
      "speed_ticks": 2,
      "cost": {"essence": 60},
      "build_ticks": 80,
      "entropy_resist": 0,
      "attack": null,
      "abilities": [
        {
          "id": "gust",
          "cooldown_ticks": 100,
          "cost": {"essence": 10},
          "range": 4,
          "do": [
            {
              "op": "push",
              "to": {
                "entities": {"within": {"of": "target", "radius": 2}, "relation": "enemy", "limit": 16}
              },
              "away_from": "target",
              "cells": 2
            }
          ]
        }
      ]
    }
  ],
  "rules": [
    {
      "id": "air_wave_push",
      "on": {"event": "wave_hit_entity"},
      "for": "entity",
      "filter": {"faction": "air", "tag": "wave_pushed"},
      "do": [
        {
          "op": "push",
          "to": "self",
          "away_from": "wave_center",
          "cells": {"max": [1, {"div": [{"ref": "wave.power"}, 3]}]}
        }
      ]
    }
  ]
}
```

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "faction",
  "id": "water",
  "name": "Água",
  "element": "water",
  "traits": ["regenerating", "economic", "erodible_structures"],
  "start": {
    "resources": {"essence": 120},
    "structures": [{"type": "tide_basin", "at": "spawn"}],
    "units": [{"type": "tide_worker", "count": 3}]
  },
  "structures": [
    {
      "id": "tide_basin",
      "name": "Bacia da Maré",
      "tags": ["structure", "core"],
      "hp": 280,
      "size": 2,
      "cost": {},
      "build_ticks": 0,
      "produces": ["tide_worker", "brine_guard", "mist_healer"],
      "provides": {"supply": 10},
      "entropy_resist": 20
    }
  ],
  "units": [
    {
      "id": "tide_worker",
      "name": "Trabalhador da Maré",
      "tags": ["unit", "worker", "regen"],
      "hp": 22,
      "speed_ticks": 3,
      "cost": {"essence": 30},
      "build_ticks": 40,
      "entropy_resist": 0,
      "gather": {"resource": "essence", "amount": 5, "cooldown_ticks": 20}
    },
    {
      "id": "brine_guard",
      "name": "Guarda da Salmoura",
      "tags": ["unit", "regen"],
      "hp": 30,
      "speed_ticks": 3,
      "cost": {"essence": 45},
      "build_ticks": 70,
      "entropy_resist": 0,
      "attack": {"damage": 5, "range": 1, "cooldown_ticks": 9, "damage_kind": "physical"}
    },
    {
      "id": "mist_healer",
      "name": "Curandeira da Névoa",
      "tags": ["unit", "regen"],
      "hp": 18,
      "speed_ticks": 3,
      "cost": {"essence": 55},
      "build_ticks": 80,
      "entropy_resist": 0,
      "attack": null,
      "abilities": [
        {
          "id": "mend",
          "cooldown_ticks": 60,
          "cost": {"essence": 5},
          "range": 3,
          "do": [
            {
              "op": "heal",
              "to": {
                "entities": {
                  "within": {"of": "self", "radius": 3},
                  "relation": "ally",
                  "tag": "unit",
                  "limit": 12
                }
              },
              "amount": 6
            }
          ]
        }
      ]
    }
  ],
  "rules": [
    {
      "id": "water_regen",
      "on": {"every_ticks": 30},
      "for": "entity",
      "filter": {"faction": "water", "tag": "regen"},
      "do": [{"op": "heal", "to": "self", "amount": 1}]
    },
    {
      "id": "water_erosion",
      "on": {"event": "wave_hit_entity"},
      "for": "entity",
      "filter": {"faction": "water", "tag": "structure"},
      "do": [{"op": "damage", "to": "self", "amount": {"ref": "wave.power"}, "kind": "entropy"}]
    }
  ]
}
```

Nota: `air.json` e `water.json` ficam com campos longos; todos os quatro arquivos passam no schema e nas referências cruzadas (`start` → tipos existentes, `produces` → unidades existentes, `cost`/`gather` → recursos existentes, ao menos uma estrutura `core`) **[T]**.

### 2.5 Entropia, vitória/derrota e modo cooperativo (exemplo) **[T]**

**Mecânica de entropia (estocástica determinística por seed):** variável global `entropy` (0–100) sobe 1 a cada 20 ticks; a variável `next_wave_tick` marca a próxima **onda**; quando `world.tick >= next_wave_tick`, a regra `wave_spawn` dispara o efeito `wave` — centro (`uniform_cell`), raio e poder dependem da entropia (`raio = 3 + entropy/20`, `poder = 4 + entropy/10`); o próximo intervalo é `200 + rand_below(120)` ticks, sorteado do **stream de RNG `entropy`**; depois a entropia cai 15. Cada entidade atingida gera o evento `wave_hit_entity`, tratado pela regra padrão **ou** pela regra da facção. "Estocástico" = intervalos e centros variam; "determinístico" = o stream `entropy` é derivado da seed (`blake2b(f"{seed}:entropy")`) e só é consumido por essas regras, então **mesma seed + mesmos comandos ⇒ mesmas ondas**.

Tabela de **referência** calculada à mão por `docs/v2/bench/wave_preview.py` (seed 777, grid 24×16, sem unidades nem estabilizadores; *não* é execução do motor — será o teste dourado da fase F3) **[T]**:

| Onda | Tick | Centro (x,y) | Raio | Poder | Entropia antes |
|---|---|---|---|---|---|
| 1 | 300 | (11,15) | 4 | 6 | 25 |
| 2 | 516 | (10,4) | 4 | 6 | 20 |
| 3 | 753 | (1,9) | 3 | 5 | 17 |
| 4 | 997 | (20,9) | 3 | 5 | 14 |
| 5 | 1286 | (7,15) | 3 | 5 | 15 |
| 6 | 1511 | (21,10) | 3 | 5 | 11 |

(Repetível: duas execuções dão a mesma tabela; seed 778 dá outra.) A 10 ticks/s, 6 ondas ≈ 2,5 min — **é exemplo de ritmo**, não balanceamento recomendado.

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "rules",
  "id": "entropy",
  "vars": {
    "entropy": {"min": 0, "max": 100, "init": 10},
    "wave_index": {"min": 0, "max": 9999, "init": 0},
    "next_wave_tick": {"min": 0, "max": 1000000, "init": 300}
  },
  "rng_streams": ["entropy"],
  "rules": [
    {
      "id": "entropy_rise",
      "on": {"every_ticks": 20},
      "for": "world",
      "do": [{"op": "var_add", "var": "entropy", "amount": 1}]
    },
    {
      "id": "wave_spawn",
      "on": {"every_ticks": 1},
      "for": "world",
      "when": {"gte": [{"ref": "world.tick"}, {"ref": "var.next_wave_tick"}]},
      "do": [
        {
          "op": "wave",
          "rng": "entropy",
          "center": "uniform_cell",
          "radius": {"add": [3, {"div": [{"ref": "var.entropy"}, 20]}]},
          "power": {"add": [4, {"div": [{"ref": "var.entropy"}, 10]}]}
        },
        {"op": "var_add", "var": "wave_index", "amount": 1},
        {
          "op": "var_set",
          "var": "next_wave_tick",
          "value": {"add": [{"ref": "world.tick"}, 200, {"rand_below": ["entropy", 120]}]}
        },
        {"op": "var_add", "var": "entropy", "amount": -15},
        {"op": "emit", "event": "wave_started"}
      ]
    },
    {
      "id": "wave_hit_default",
      "on": {"event": "wave_hit_entity"},
      "for": "entity",
      "when": {
        "not": {
          "any": [
            {"has_tag": ["self", "wave_immune"]},
            {"has_tag": ["self", "wave_pushed"]},
            {"has_tag": ["self", "wave_fed"]}
          ]
        }
      },
      "do": [
        {
          "op": "damage",
          "to": "self",
          "amount": {
            "max": [1, {"sub": [{"ref": "wave.power"}, {"div": [{"ref": "self.entropy_resist"}, 10]}]}]
          },
          "kind": "entropy"
        }
      ]
    }
  ]
}
```

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "rules",
  "id": "victory",
  "rules": [
    {
      "id": "core_lost",
      "on": {"event": "structure_destroyed"},
      "for": "entity",
      "when": {"has_tag": ["self", "core"]},
      "do": [{"op": "eliminate_faction", "faction": "self_faction"}]
    },
    {
      "id": "team_defeat",
      "on": {"every_ticks": 10},
      "for": "team",
      "when": {"eq": [{"count": {"scope": "team", "tag": "core"}}, 0]},
      "do": [{"op": "end", "result": "defeat", "who": "team"}]
    },
    {
      "id": "coop_survive",
      "on": {"every_ticks": 10},
      "for": "world",
      "when": {
        "all": [
          {"eq": [{"ref": "param.mode"}, "coop_vs_entropy"]},
          {"gte": [{"ref": "var.wave_index"}, {"ref": "param.waves_to_survive"}]}
        ]
      },
      "do": [{"op": "end", "result": "victory", "who": "all_players"}]
    },
    {
      "id": "last_team",
      "on": {"every_ticks": 10},
      "for": "world",
      "when": {
        "all": [{"eq": [{"ref": "param.mode"}, "versus"]}, {"eq": [{"ref": "world.teams_alive"}, 1]}]
      },
      "do": [{"op": "end", "result": "victory", "who": "last_team"}]
    }
  ]
}
```

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "rules",
  "id": "economy",
  "rules": [
    {
      "id": "base_income",
      "on": {"every_ticks": 100},
      "for": "faction",
      "do": [{"op": "add_resource", "faction": "self_faction", "resource": "essence", "amount": 2}]
    }
  ]
}
```

**Condições de vitória/derrota:** `core_lost` (estrutura com tag `core` destruída ⇒ a facção é eliminada), `team_defeat` (time sem `core` ⇒ derrota do time), `coop_survive` (cooperativo: `wave_index ≥ param.waves_to_survive` ⇒ vitória de todos), `last_team` (versus: um só time vivo). **Modo cooperativo:** o cenário define `teams` com vários jogadores no mesmo time; `modes.coop_vs_entropy` fixa `friendly_fire:false` e `shared_victory:true`; a "oposição" é a própria entropia. **[P]** futuro: `modes.<m>.shared_resources`.

Cenário cooperativo (2 jogadores humanos, Ar + Terra, mapa 24×16 com paredes, 6 nós de essência, spawns `1` e `2`):

```json
{
  "format": "dream-fabrics/mojo-part",
  "schema_version": "0.2.0",
  "kind": "scenario",
  "id": "coop_vs_entropy",
  "name": "Cooperativo contra a Entropia",
  "mode": "coop_vs_entropy",
  "seed": 777,
  "params": {"mode": "coop_vs_entropy", "waves_to_survive": 6},
  "grid": {
    "width": 24,
    "height": 16,
    "legend": {".": "floor", "#": "rock", "E": "essence_node", "1": "spawn:1", "2": "spawn:2"},
    "layout": [
      "########################",
      "#......................#",
      "#......................#",
      "#...E..............E...#",
      "#......................#",
      "#..........##..........#",
      "#..........##..........#",
      "#...........#..........#",
      "#..1....E..#...E....2..#",
      "#..........##..........#",
      "#..........##..........#",
      "#......................#",
      "#...E..............E...#",
      "#......................#",
      "#......................#",
      "########################"
    ]
  },
  "teams": [{"id": "alliance", "name": "Aliança"}],
  "players": [
    {"slot": "p1", "faction": "air", "team": "alliance", "spawn": "1", "controller": "human"},
    {"slot": "p2", "faction": "earth", "team": "alliance", "spawn": "2", "controller": "human"}
  ],
  "objectives": [{"id": "survive", "text": "Sobreviver a 6 ondas de entropia."}]
}
```

(`scenarios/duel_fire_water.json` é o modo `versus`, Fogo × Água, com o adversário `controller:"idle"`; IA scriptada é projeto — ver §3.6.)

### 2.6 A mini-linguagem de regras (condições e efeitos) — sem execução arbitrária

**Princípio [P]:** regra = dado. Nunca há `eval`, `exec`, import, acesso a atributos Python, nem strings avaliadas. O carregador **compila** cada expressão para uma *closure* Python (fechada sobre a whitelist) e rejeita o pacote inteiro se algo estiver fora dela. O protótipo executável é `docs/v2/bench/expr_proto.py` **[T]**.

**Regra** = `{id, on, for, filter?, when?, do[]}`:
- `on`: `{"every_ticks": N}` ou `{"event": "wave_hit_entity" | "structure_destroyed" | "unit_died"}`.
- `for` (contexto): `world` · `team` · `faction` · `entity` (`self` é a entidade; `filter` por `faction/tag/type/state`).
- `when`: expressão booleana opcional. `do`: 1–16 efeitos.

**Expressões** — literal inteiro/bool/texto curto (≤64) ou objeto com **um** operador:

| Grupo | Operadores (whitelist) | Observações |
|---|---|---|
| Lógica | `all[]`, `any[]` (1–16), `not` | |
| Comparação | `eq ne lt lte gt gte` (2 args) | |
| Aritmética | `add min max` (2–8), `sub mul div mod` (2), `neg abs` (1) | **só inteiros**; `div` = divisão inteira (piso); divisor 0 ⇒ 0 (definido, sem exceção); **float proibido** (use permille) |
| Referências | `{"ref":"<ns>.<campo>"}` | `self.{hp,max_hp,x,y,entropy_resist,faction,type}` (só `for=entity`), `world.{tick,teams_alive}`, `var.<declarada>`, `param.<do cenário>`, `faction.res.<recurso>`, `wave.{power,radius,dist}` (só no evento `wave_hit_entity`) |
| Tags | `has_tag:[self|target, tag]` | |
| Aleatório | `rand_below:[stream, n]` | **stream precisa estar declarado** em `rng_streams`; consome o RNG daquele stream |
| Contagem | `count:{scope: team|faction|world, tag?, type?, faction?}` | O(n); `scope=team` só em `for=team`; o *lint* avisa uso em `every_ticks:1` |

Limites **[T]** (rejeitados no verificador): profundidade ≤ 8, ≤ 64 nós por expressão, inteiros |v| ≤ 10⁹ nos literais; **[P]** resultado intermediário fora de ±10¹² aborta a regra e registra `rule_overflow`.

**Efeitos** — `{"op": ..., ...}` com campos obrigatórios/opcionais fixos (tabela `OPS` do protótipo — **fonte única** que, no código final, gera também o schema):

| `op` | Campos | Efeito |
|---|---|---|
| `var_add` / `var_set` | `var`, `amount`/`value` | altera variável **declarada** (com `min/max`, sempre limitada: mesmo princípio do `hp_delta` do v0.1) |
| `add_resource` | `faction`(`self_faction`\|id), `resource`, `amount` | |
| `damage` / `heal` | `to`, `amount` (+`kind` no dano) | |
| `push` | `to`, `away_from` (`target`\|`self`\|`wave_center`), `cells` | desloca respeitando paredes/ocupação |
| `spawn` | `type`, `at`, `count?` | respeita `max_entities` |
| `status` | `to`, `status`, `ticks` | status declarado na facção; modificadores numéricos fechados |
| `wave` | `rng`, `center:"uniform_cell"`, `radius`, `power` | cria a onda; despacha `wave_hit_entity` em ordem de id |
| `eliminate_faction` / `end` | `faction` / `result`, `who` | derrota/vitória |
| `emit` / `schedule` | `event` / `rule`, `in_ticks` | evento narrável / reagendar regra (com teto) |

Seletores: `"self"`, `"target"` ou `{"entities": {"within": {"of": "self|target", "radius": 1..12}, "relation": "enemy|ally|any", "tag"?, "limit": 1..64}}`.

**Semântica de execução [P]** (o que torna as regras reprodutíveis): regras rodam na ordem *(ordem de `includes`, ordem de declaração)*; entidades sempre em ordem crescente de `id`; argumentos avaliados da esquerda para a direita; eventos emitidos entram numa fila FIFO despachada em até 3 passadas por tick; teto `sim.max_effects_per_tick` — ao estourar, os efeitos restantes são **descartados deterministicamente** e registrados (`budget_exceeded`). Sem laços, sem recursão (`schedule` é adiado e limitado).

**Custo [M]:** avaliar uma condição de ~10 nós leva **2,53 µs interpretando a árvore** e **0,80 µs compilada em closures** (Python 3.13.5, box; ganho 3,2×; `docs/v2/bench/dsl_bench.py`). Conclusão: **compilar no carregamento** é obrigatório; regras `every_ticks:N` com `for=entity` são baratas; evitar `every_ticks:1` por entidade.

Prova de segurança **[T]** (`check_example.py --self-test`): 13 pacotes maliciosos/defeituosos são todos **rejeitados** — include com `..`, absoluto/drive, barra invertida, arquivo inexistente, versão futura, operador `eval`, float, variável não declarada, `op` inexistente (`exec`), expressão profunda (bomba), `rand_below` sem stream, `self.*` fora de `for=entity`, campo desconhecido no manifesto.

### 2.7 Schema JSON v0.2 e migração da v0.1

Arquivos **[T]**: `docs/v2/schema/mojo-world-0.2.schema.json` (manifesto, `additionalProperties:false`, `if/then` por `kind`) e `docs/v2/schema/mojo-part-0.2.schema.json` (partes: `faction | resources | rules | scenario | theme`, `$defs` para `expr`, `effect`, `rule`, `unit`, `structure`). O schema valida **estrutura e whitelist de nomes**; aridade/tipos/limites/referências cruzadas ficam no compilador (mesmo arranjo do v0.1: `_schema_errors` + `_semantic_errors` **[V]**).

**Migração v0.1 → v0.2 [T]** (função pura; testada com o `azrael.mjo` real: resultado válido no schema 0.2, conteúdo idêntico, entrada não mutada):

```python
# docs/v2/skeleton/mojo_v2/pack/migrate.py  → vira mojo/world/migrations.py
def migrate_0_1_to_0_2(doc: dict) -> dict:
    out = dict(doc)
    out["schema_version"] = "0.2.0"
    out.setdefault("kind", "text-adventure")
    out.setdefault("engine", {"profile": "turn-text-v0", "min_mojo": "2.0.0"})
    return out
# registro:  SUPPORTED = (0, 2);  MIGRATIONS[(0, 1)] = migrate_0_1_to_0_2
```
`ensure_supported` (`world/migrations.py`, **[V]**) já encadeia migrações e rejeita versões mais novas; o V2 só preenche o registro. Para `kind="text-adventure"`, os blocos `world`/`rules` continuam validados pelo **schema v0.1 existente** (inalterado) — **[P]** a conectar na fase F1. Política 0.x mantida: `0.2.x` aceito, `0.3+`/`1+` rejeitado como "mais novo", `0.1.x` migrado.

### 2.8 Modularidade: includes e mods **[P]**

- **Includes** (já no exemplo): por tipo, caminhos validados; ids únicos; erro aponta `arquivo: caminho.json: mensagem` (formato do `WorldError`).
- **Mods** (`mods:[{id,path}]`): um mod é uma pasta com seu próprio `world.mjo` de `kind:"mod"` que pode **adicionar** partes (novas facções/unidades/regras) e aplicar **patches restritos** (só estatísticas numéricas por caminho da whitelist, ex.: `factions.fire.units.cinder_guard.hp`). Regras: ids novos com prefixo `<mod_id>_`; **colisão de id = erro** (sobrescrever só com `"override":true` explícito e registrado no log); ordem de carga explícita; **todos os caminhos** passam por `resolve_inside` relativo à pasta do mod; o hash do mod entra no `pack_sha256` (replay/saves).
- Ainda **não** existe: assinatura/criptografia, empacotamento `.mjopack`, marketplace — decisão adiada (como no brief original, §6 "Licenciamento/IP").

---

## 3. Pilar 2 — Desacoplamento: backend local + WebSocket + frontend web/PWA

### 3.1 Visão geral **[P]**

```text
Navegador (Edge/Chrome) em http://127.0.0.1:8770/?t=<token>
  ├─ index.html + app.js (módulos ES) ── canvas 2D (grid tático) + painéis DOM
  └─ WebSocket ws://127.0.0.1:8770/ws?t=<token>          (JSON; comandos ↑, deltas/snapshots ↓)
                │
                ▼
mojo serve  (FastAPI + uvicorn + websockets, UM processo Python, asyncio)
  ├─ server/   app.py  protocol.py  session.py  security.py  static/
  ├─ Session (um por partida) ── Profile  ┬─ tick-grid-v0 : SimEngine (ticks determinísticos, sim/)
  │                                       └─ turn-text-v0 : Game (engine/loop.py do v0.1, sem mudanças)
  ├─ pack/  loader + compilador de regras (world.mjo + partes)
  ├─ NarrationService ─► SemanticAdapter (mock por padrão) ─► AudioDispatcher ─► RagnarokAdapter ─HTTP─► Ragnarok (127.0.0.1:8765, processo separado, opcional)
  └─ store/ saves atômicos · replay (comandos + checkpoints, em lote)
```

Princípios: **servidor autoritativo** (o navegador só manda *intenções* e desenha o que o servidor diz); **o tick nunca espera** áudio, modelo de linguagem nem disco; **modo texto intacto** (`mojo play` não muda; o mesmo servidor também pode servir `turn-text-v0`, fase F7).

### 3.2 Dependências e processo

- **Extra novo `[serve]` [P]:** `fastapi>=0.110`, `uvicorn>=0.30`, `websockets>=12`. **[T]** funcionou na box, Python 3.12.15, com `fastapi 0.162.0`, `uvicorn 0.54.0`, `websockets 17.3`, `starlette 1.10.0`, `pydantic 2.14.1`.
- **Venv próprio do MOJO.** O venv do Ragnarok **não serve** (sem `websockets`) **[V][T]** e não deve ser alterado. Dois venvs lado a lado: `…\ragnarok\app\.venv` (8765) e `C:\MOJO\mojo\.venv` (8770) **[P]**.
- **Um processo, um laço `asyncio`:** o tick roda no laço (síncrono, orçamento ≪ 100 ms), difusão aos clientes `await ws.send_text(...)`. **[T]** Spike com 1 cliente, 10 Hz, snapshot completo por tick, 8 s, loopback, Python 3.12.15 (`docs/v2/bench/wsspike.py` + `wsclient.py`): com 500 unidades, intervalo entre mensagens média **100,0 ms**, p99 104 ms; passo 1,1 ms, codificação 0,35 ms, envio 0,49 ms, ≈111 KB/s; com 2000 unidades, passo médio 8,6 ms (máx 20 ms), p99 do intervalo 119 ms, ≈440 KB/s; RSS do processo uvicorn ≈ **45 MB** **[M]** (box, 1 cliente, sem Ragnarok).
- Porta padrão **8770** (Ragnarok usa 8765). O MOJO V2 **não** inicia o Ragnarok na primeira versão (decisão nº 8 do Gui, v0.1: manual).

### 3.3 Protocolo de mensagens (v1) **[P]**

JSON em texto, uma mensagem por frame WebSocket; campo `t` = tipo; **compressão por mensagem desligada** (loopback; poupa CPU **[I]**). Tamanho máximo 8 KB do cliente (esqueleto **[T]**).

**Cliente → servidor**

| `t` | Campos | Observações |
|---|---|---|
| `hello` | `protocol:1`, `slot?` | escolhe vaga; o servidor responde `welcome` |
| `cmd` | `seq`, `type`, `args` | tipos: `move{ids,x,y}`, `attack{ids,target}`, `gather{ids,node}`, `build{unit,structure,x,y}`, `train{structure,unit}`, `ability{unit,id,target}`, `stop{ids}` |
| `ctl` | `action: pause\|resume\|speed`, `value?` | só o anfitrião (slot de host) |
| `snapshot_req` | — | pedido de ressincronização |
| `ping` | `n` | latência |

**Servidor → cliente**

| `t` | Conteúdo | Frequência |
|---|---|---|
| `welcome` | `protocol`, `session`, `tick_hz`, `pack:{id,sha256}`, `you:{slot,faction,team}`, `map:{w,h,layout,legend}`, `defs` (unidades/estruturas reduzidas p/ UI), `snapshot` | 1× ao entrar |
| `delta` | `k` (tick), `u` (entidades alteradas: `[id,x,y,hp,state?]`), `r` (ids removidos), `v` (variáveis/recursos que mudaram), `ev` (eventos) | **todo tick (10 Hz)** |
| `snapshot` | estado completo (+ `hash`) | a cada 50 ticks e sob pedido |
| `ack` | `seq`, `tick` em que o comando vale, ou `{ok:false, reason}` | por comando |
| `forecast` | `wave_in_ticks` (só o *quando*; centro/raio só conhecidos no disparo) | quando muda |
| `narration` / `narration_audio` | `id`, `text` / `id`, `url:"/audio/<sha256>.wav"` | por evento narrado, com limite de taxa |
| `end` | `result`, `who` | 1× |
| `error` | `code` (`bad_message`, `rate_limited`, `not_owner`, `out_of_bounds`, …) | — |

Exemplo de `delta` (compacto): `{"t":"delta","k":412,"u":[[7,13,5,22],[9,13,6,18]],"r":[11],"v":{"entropy":19,"res.fire.essence":134},"ev":[{"k":"wave_started"}]}`.
**[M]** Tamanhos medidos no benchmark (§4.7): delta médio **0,2–2,0 KB/tick** para 200–2000 unidades (≤ 20 KB/s por cliente a 10 Hz); snapshot completo 7,8–45 KB.
**Latência do comando:** cada `cmd` é carimbado com `tick_atual + INPUT_DELAY_TICKS` (2 ⇒ ~200 ms a 10 Hz) — o mesmo atraso serve depois para *lockstep* (§4.5). Sem predição no cliente na v2; só **interpolação visual** de posições entre ticks.

**Validação de comando no servidor [P]** (`sim/commands.py`, a escrever): tipo na whitelist; `ids` pertencem ao slot; alvo existe e é válido; coordenadas dentro do grid e transitáveis; custo/produção permitidos pela facção; no máximo 64 ids por comando; limite 60 cmd/s por cliente **[T]** (rajada de 80 ⇒ `rate_limited`). Entrada inválida ⇒ `ack{ok:false}`/`error`, **estado intacto** (mesma garantia dos testes de "ação proibida" do v0.1 **[V]**).

### 3.4 Frontend (HTML/CSS/JS, módulos ES, sem build, sem CDN) **[P]**

```text
src/mojo/server/static/
  index.html          # <canvas id="map"> + painéis; CSP sem 'unsafe-inline'
  app.js              # bootstrap: lê ?t=, abre o WebSocket, liga módulos
  net.js              # WebSocket com reconexão e ressincronização (snapshot_req)
  state.js            # aplica delta/snapshot; guarda posição anterior p/ interpolar
  render.js           # canvas 2D: tiles pré-renderizados em canvas offscreen, entidades, entropia, seleção
  input.js            # seleção (clique/caixa), botão direito = mover/atacar, atalhos
  ui.js               # painéis DOM: recursos, seleção, comandos, previsão de onda, log/narração
  style.css  theme.js # cores vêm de assets/theme.json (via welcome.defs)
  sw.js  manifest.webmanifest   # PWA opcional: cache só dos estáticos
```
- **Desenho:** tiles em um canvas offscreen desenhado **uma vez**; por quadro, só entidades (`fillRect`/círculos), sobreposição de entropia e UI. Centenas de formas simples em canvas 2D é carga baixa para um iGPU/CPU atual **[I]** — **não medido** (sem navegador no PC do Gui aqui).
- **Interpolação:** `requestAnimationFrame` (≈60 fps) interpola entre o tick anterior e o atual; a simulação segue a 10 Hz.
- **PWA:** `http://127.0.0.1` é contexto "potencialmente confiável", logo service worker deve funcionar **[I]**; o SW só cacheia estáticos (nunca `/ws`, `/audio`). É opcional; o jogo roda sem instalar nada.
- **Áudio no navegador:** navegadores exigem gesto do usuário para tocar som **[I]** ⇒ botão "Ativar som" no primeiro clique.
- **Teste automatizado:** Playwright headless (já usei no Ragnarok, na box) para smoke/captura de tela **[P]**; fluidez real (fps) só o Gui mede no Windows.

### 3.5 Segurança local **[T]**

Esqueleto `docs/v2/skeleton/mojo_v2/server/{security.py,app.py}` rodou na box (Python 3.12.15) e `ws_handshake_test.py` produziu:

| Tentativa | Resultado medido |
|---|---|
| Origin `http://127.0.0.1:8770` + token | **aceito** (`welcome`, `ack`, ticks) |
| Origin `http://localhost:8770` + token | **aceito** |
| Origin de outro site (`http://evil.example`) | **rejeitado, HTTP 403** |
| Sem cabeçalho Origin | **rejeitado, HTTP 403** |
| Token errado / sem token | **rejeitado, HTTP 403** |
| `Host` forjado (`evil.example:8770`) | **rejeitado, HTTP 400** (barrado já na camada de protocolo, antes de `host_ok`) |
| Mensagem que não é JSON | `error: bad_message`, conexão mantida |
| 80 comandos em rajada | `error: rate_limited` |
| `GET /docs` | **404** (docs/openapi desligados) |

Regras **[P]**: bind **somente** `127.0.0.1` (o `--lan` para coop em outra máquina é **decisão do Gui**, exigiria token e aviso; não faz parte da v2 inicial); token aleatório por execução (`secrets.token_urlsafe(24)`, `hmac.compare_digest`), impresso no terminal e embutido na URL aberta por `--open`; **Origin exigido e igual ao do servidor** (anti página maliciosa) + **Host** loopback (anti DNS-rebinding), como o middleware do Ragnarok **[V]** mas **também no WebSocket**; CSP `default-src 'self'; connect-src 'self'; img-src 'self' data:` sem inline; estáticos só do diretório empacotado; áudio servido **apenas** por rota com regex `^[0-9a-f]{64}\.wav$` (travessia impossível); nenhum upload; o pacote a executar é escolhido **na linha de comando**, nunca pelo navegador; sem `eval`/`exec` em nenhum ponto. **Limite honesto:** Origin é forjável por qualquer processo local; o modelo de ameaça é página web maliciosa/DNS rebinding, **não** malware na conta do usuário.

### 3.6 Integração com Ragnarok e com o adaptador semântico (sem quebrar o modo texto) **[P]**

- **Narração:** regras `emit` (ex.: `wave_started`) viram `NarrationRequest(kind, facts)`; o `SemanticAdapter` (`mock` por padrão — gera frase a partir de modelos de texto do pacote, sem rede) devolve o texto; o servidor envia `narration` **na hora**; **em paralelo** `AudioDispatcher` (extraído de `Game._request_audio` **[V]**) chama `RagnarokAdapter.synthesize` numa thread e, ao concluir, envia `narration_audio{url}`. Limite de taxa (ex.: 1 narração/15 s, fila descartando a mais antiga) **[P]**.
- **Latência esperada [M, medida no v0.1]:** síntese de 80–100 caracteres 0,6–1,6 s a quente, ~2,4 s a frio (box). A narração em voz chega **depois** do texto; isso é compatível porque o tick não espera.
- **Falhas:** Ragnarok fora do ar ⇒ `AudioRef(status="unavailable")`, disjuntor aberto, **apenas texto** (comportamento já testado no v0.1 **[V]**); `RagnarokAdapter` tem timeout próprio de 20 s **[V]** mas é bloqueante ⇒ **nunca no laço do tick**.
- **Adaptador semântico NÃO fica no caminho do tick [I/P]:** LLM local no hardware do Gui leva segundos por resposta (inferência, não medida), então ele (1) narra eventos já ocorridos, (2) ajuda na **autoria offline** — propõe partes `.json` que passam pelo **mesmo carregador/compilador**, gravadas só em `drafts/`, nunca incluídas automaticamente, (3) futuramente *aconselha* IA em intervalos longos. A regra do v0.1 permanece: **o modelo propõe, o núcleo decide**.
- **Modo texto:** `mojo play examples/azrael.mjo` continua igual (200 testes do v0.1 são o contrato de regressão). O perfil `turn-text-v0` pode ser servido no navegador (mensagem `cmd{type:"text",line}` → `Game.step`) — **[P]** fase F7, opcional.

---

## 4. Pilar 3 — Ciclo de vida e simulação

### 4.1 Laço de ticks determinísticos **[P]** (esqueleto executável **[T]**: `docs/v2/skeleton/mojo_v2/sim/engine.py`)

Ordem **fixa** por tick `N` (a lista de sistemas é o contrato; mudar a ordem muda o jogo e exige nova versão do `engine.profile`):

1. `tick += 1`; retirar da fila os comandos com `cmd.tick <= tick`, **ordenados por `(tick, slot, seq)`**.
2. `commands` — validar e aplicar (ordens: mover, atacar, produzir, construir…).
3. `ai` — controladores de IA (cada um emite comandos como se fosse jogador; orçamento por agente).
4. `rules_every` — regras `every_ticks` (ordem de declaração).
5. `production` e `economy` (coleta).
6. `movement` (caminhos; cap de pathfinding por tick).
7. `combat`.
8. `rules_events` — despacha a fila de eventos (FIFO, ≤ 3 passadas, teto de efeitos).
9. `cleanup` — remove mortos **em ordem de id**, gera `unit_died/structure_destroyed`.
10. `victory` — regras de vitória/derrota.
11. `snapshot/delta` e, a cada 50 ticks, **checkpoint de hash**.

**Regras de determinismo [P]:** estado **só com inteiros** (nada de float; velocidade = "ticks por célula"; proporções em permille); iteração só em ordem de inserção/ordenada por id (nunca `set` sem ordenar); nunca `hash()`/`id()`/relógio de parede dentro da simulação; JSON canônico (`sort_keys`) para hash; RNG próprio (abaixo). `dict` preserva ordem de inserção na linguagem **[I]** (garantia da linguagem desde 3.7).

### 4.2 RNG com seed por sistema **[T]**

`core/rng.py`: `derive_seed(master, stream) = blake2b(f"{master}:{stream}")` e `SplitMix64` (inteiros puros). Streams padrão: `ai`, `combat`, `entropy`, `spawn` + os declarados em `rng_streams`; um sistema **só** consome o seu stream, então adicionar um sorteio em `combat` não desloca a sequência das ondas. O estado de cada stream entra no snapshot e no hash. Vetores de teste **[T]**: `SplitMix64(1).next() = 10451216379200822465` (valor de referência conhecido do algoritmo), `below(100)` ×5 com seed 1 = `[51, 29, 42, 41, 2]`, `derive_seed(777,"entropy") = 11712351061285931308`.
Por que não `random.Random`: só `random()` tem sequência garantida entre versões do Python (documentação do `random`) **[I]**; `randrange/choice` podem mudar. **Custo [M]:** `SplitMix64.below` ≈ 315–390 ns/chamada vs `random.Random.random` ≈ 30–54 ns (1 M de chamadas). Com dezenas/centenas de sorteios por tick, é desprezível.

### 4.3 Fila de comandos e ordem **[T]**

`Cmd(tick, slot, seq, type, args)` com ordenação por `(tick, slot, seq)`. Teste do esqueleto: o **mesmo conjunto de comandos entregue em ordens de chegada diferentes produz o mesmo hash** (c81b7a05…) — a rede não decide a ordem, o carimbo decide.

### 4.4 Estado, snapshots, hash **[T]/[M]**

`SimState` (tick, entidades em `dict[id → Entity]` com `__slots__`, `vars`, `res`, `next_id`) + estados dos RNGs. `hash()` = `blake2b` do JSON canônico — mesma ideia de `GameState.hash()` **[V]** (`engine/state.py` l. 38). Custos **[M]**: snapshot completo 13,8 KB em 0,4 ms (500 unidades) a 45 KB em 1,4 ms (2000); hash 0,2–1,1 ms; delta 0,03–0,27 ms. Snapshots de **partida salva** reaproveitam `store/saves.py` (tmp+fsync+`os.replace`+`.bak`) **[V]**.

### 4.5 Replay e lockstep futuro **[T] replay; [P] lockstep**

- **Replay:** `ReplayLog{header, cmds[[tick,slot,seq,type,args]], checkpoints{tick:hash}}`; `header` = `{engine, pack_sha256, scenario, seed}`. `replay(make_engine, log, until)` reexecuta do zero e devolve o **primeiro tick que diverge**. **[T]** No esqueleto: 200 ticks reproduzem os 4 checkpoints; adulterar 1 comando do log é detectado no tick 50 (primeiro checkpoint após a mudança). Gravação **em lote** (flush ~1×/s e no fim), não `fsync` por registro **[M]** (§1).
- **Lockstep (cooperativo, futuro):** como todos os clientes usam o mesmo servidor, a v2 **não precisa** de lockstep (servidor autoritativo). Para jogar com **servidores/PCs distintos**, o mesmo núcleo serve: cada instância roda a simulação, trocam-se apenas `Cmd` com `tick = atual + INPUT_DELAY_TICKS` e comparam-se hashes de checkpoint a cada 50 ticks; divergência ⇒ `desync` (já detectável pelo replay). Pré-requisitos já cobertos pelo desenho: inteiros, ordem fixa, RNG por stream. **Risco [I]:** a mesma versão de Python/pacote nos dois lados; `pack_sha256` no `hello` evita pacotes diferentes.

### 4.6 Simulação concorrente: múltiplos agentes e eventos estocásticos **[P]**

"Concorrente" aqui = **lógica concorrente, execução sequencial determinística**:
- **Agentes (IA/unidades):** cada controlador de IA é um **sistema** que emite `Cmd` (como um jogador) com seu **stream próprio** (`ai:<slot>`) e **orçamento por tick** (ex.: reavaliar alvos só a cada k ticks, escalonado por `(id + tick) % k`). **[M]** Escalonar a IA em k=5 reduz o tick de 3,8→1,4 ms (1000 unid., Py 3.13) e 11,0→3,5 ms (2000 unid.).
- **Eventos estocásticos (ondas):** são regras que consomem o stream `entropy`; o *quando* e o *onde* variam por seed, nunca por relógio.
- **Threads:** só para E/S que bloqueia (Ragnarok, disco). A simulação roda **no laço asyncio** (um núcleo; o GIL impediria ganho real de threads para código Python puro **[I]**). Se o orçamento estourar: (1) otimizar/escalonar, (2) mover a simulação para um **processo separado** (`multiprocessing`) que envia deltas por pipe — **[P]** só se medido necessário.
- **Atraso de laço:** o `ticker` usa agenda com correção de deriva (`nxt += período`) **[T]**; se atrasar > 1 período, política **[P]**: executar até 3 ticks de recuperação, depois desacelerar (nunca pular tick, nunca alterar a ordem).
- **GC do Python [I]:** milhares de objetos com `__slots__`; chamar `gc.freeze()` após carregar o pacote e medir pausas antes de mexer em `gc.disable()`.

### 4.7 Orçamento de performance (números marcados)

**Medição [M]** — `docs/v2/bench/tick_bench.py` (Python puro, grid 64×64 inteiro, hash espacial, 6 sistemas em ordem fixa, RNG por sistema, ondas de entropia, 300 ticks por tamanho; box Linux Xeon 8 vCPU, **uma thread**; resultados completos em `docs/v2/bench/result_py31{2,3}_*.json`). **Carga simplificada:** sem pathfinding por unidade, construção/produção nem regras DSL; serve para custo *relativo* e como piso, **não** como previsão de um RTS completo.

| Unidades | Tick médio (p99) Py 3.13 | Tick médio (p99) Py 3.12 | IA escalonada k=5 (3.13 / 3.12) | Snapshot completo | Delta médio | Hash |
|---|---|---|---|---|---|---|
| 200 | 0,32 (0,48) ms | 0,27 (0,45) ms | 0,16 / 0,15 ms | 7,8 KB · 0,26 ms | 0,20 KB · 0,03 ms | 0,23 ms |
| 500 | 1,25 (1,88) ms | 0,90 (1,43) ms | 0,56 / 0,45 ms | 13,8 KB · 0,44 ms | 0,57 KB · 0,07 ms | 0,39 ms |
| 1000 | 3,85 (5,41) ms | 2,66 (4,25) ms | 1,37 / 1,12 ms | 22,1 KB · 0,58 ms | 1,16 KB · 0,15 ms | 0,55 ms |
| 2000 | 10,98 (13,87) ms | 7,78 (11,48) ms | 3,50 / 2,95 ms | 45,1 KB · 1,43 ms | 1,97 KB · 0,27 ms | 1,09 ms |

Outras medições **[M]**: A\* 64×64 8 direções com ~8% de paredes: **0,44–0,55 ms/caminho** (239 caminhos); *flow field* (BFS a partir do destino): **3,9–6,2 ms/destino** (serve a um grupo inteiro); condição DSL compilada: 0,80 µs (§2.6); `fsync` por registro de log 0,178 ms (§1). Determinismo do benchmark: mesma seed/ordem ⇒ mesmo hash; ordem de sistemas trocada ⇒ hash diferente; seed diferente ⇒ hash diferente (3 verificações **[T]**). Variação entre execuções é visível (3.12 saiu ~25–30% mais rápido que 3.13 nesta box; **não** tire conclusão sobre versões do Python).

**Limitação do benchmark (importante):** uma variante "todos perseguem" (`--chase`) deu tempos *menores* (1000 unid. ≈ 1,0 ms) porque as unidades se bloqueiam sem pathfinding — ela **não** é um pior caso confiável e não deve ser usada como estimativa.

**Extrapolação para o PC do Gui [I] (não medida):** i5-12450H (8 núcleos, 4 de desempenho) tende a ter desempenho de 1 thread da mesma ordem de grandeza ou melhor que um vCPU de nuvem, mas notebook sofre com plano de energia, temperatura, antivírus e segundo plano. Regra proposta: **tempo no Gui = 1× a 2× o da box**, e **um RTS completo custa de 5× a 10× a carga simplificada**.

| Item do orçamento por tick (100 ms a 10 Hz) | Alocação **[P]** | Base |
|---|---|---|
| Sistemas do núcleo + regras | ≤ 25 ms | extrapolação [I] |
| Pathfinding | ≤ 8 A\* **ou** ≤ 2 *flow fields* por tick (fila para o resto) | A\* 0,5 ms, BFS 4–6 ms [M] ⇒ ≤ ~8 ms no PC [I] |
| Delta + envio | ≤ 3 ms | 0,03–0,27 ms + ~0,5–1,5 ms [M] |
| Hash (1 a cada 50 ticks) | ≤ 2 ms | 0,2–1,1 ms [M] |
| Margem (GC, Windows, narração, navegador) | ≥ 60 ms | [I] |

| Entidades por partida (unidades + estruturas) | Avaliação **[I]** |
|---|---|
| **≤ 400** | **confortável**: ≈0,5–1,3 ms na carga leve × 10 × 2 ≈ 10–26 ms no pior caso |
| **≤ 800** | **possível com otimizações** (IA escalonada, *flow fields* compartilhados, teto de caminhos, índice espacial); sem elas o pior caso passa de 50 ms |
| **≥ 1.500** | **projeto**: exige núcleo vetorizado/nativo (numpy, mypyc/Cython, PyPy ou Rust/PyO3) — **não avaliados aqui** |

Rede: ≤ ~20 KB/s por cliente (delta a 10 Hz) **[M]**. RAM: processo MOJO na casa de dezenas de MB **[M]: 45 MB RSS** + Ragnarok (0,6–0,8 GB quando sintetiza **[M]**, v0.1) + navegador (centenas de MB **[I]**) — cabe nos 7,7 GB **[I]**.

### 4.8 Como adaptar `loop.py` / `state.py` / `actions.py` — interfaces propostas **[P]**

Estratégia: **não mexer** nos três arquivos no começo; acrescentar uma camada de perfis e um núcleo novo ao lado, mantendo `Game` e os 200 testes verdes.

```python
# mojo/profiles/base.py  (novo)
class Session(Protocol):
    profile: str
    def hello(self, slot: str | None) -> list[dict]: ...      # mensagens iniciais (welcome + snapshot)
    def handle(self, slot: str, msg: dict) -> list[dict]: ... # comando do cliente -> acks/erros (nunca levanta)
    def tick(self) -> list[dict] | None: ...                  # deltas/eventos; None = perfil por turno
    def snapshot(self) -> dict: ...
    def close(self) -> None: ...

# mojo/profiles/turn_text.py  (novo; casca fina)
class TextSession:                                            # envolve engine.loop.Game SEM alterá-lo
    def __init__(self, game: Game): ...
    def handle(self, slot, msg):                              # {"t":"cmd","type":"text","line":"look"}
        res = self.game.step(msg["line"])                     # TurnResult -> {"t":"text","text":..., "notes":[...]}
```

```python
# mojo/sim/state.py   (novo; mesmo espírito de engine/state.py::GameState)
@dataclass
class SimState:
    tick: int; next_id: int
    ents: dict[int, Entity]; vars: dict[str, int]; res: dict[str, dict[str, int]]
    def to_dict(self, rng_state: dict) -> dict: ...
    def hash(self, rng_state: dict) -> str: ...               # blake2b do JSON canônico
def initial_state(pack: "CompiledPack", scenario_id: str) -> SimState: ...
def validate_state_dict(pack, d: object) -> SimState: ...     # saves não confiáveis, como engine/state.py::validate_state_dict

# mojo/sim/commands.py   (novo; substitui engine/actions.py no RTS)
@dataclass(order=True)
class Cmd: tick: int; slot: str; seq: int; type: str = field(compare=False); args: dict = field(compare=False)
def parse_client_command(raw: object, ctx: "CmdCtx") -> Cmd | CmdError: ...   # whitelist de type, posse, limites do mapa

# mojo/sim/engine.py  (esqueleto em docs/v2/skeleton)
class SimEngine(TickEngine):
    def __init__(self, pack: "CompiledPack", scenario_id: str, *, seed: int | None = None): ...
    def submit(self, cmd: Cmd) -> None
    def step(self) -> TickReport                              # ordem fixa de §4.1
    def snapshot(self) -> dict
    def delta_since(self, last_sent: dict[int, tuple]) -> dict
    def export_replay(self) -> ReplayLog

# mojo/sim/effects.py   (generaliza engine/events.py::validate_event/apply_event)
@dataclass(frozen=True)
class EffectSpec: required: frozenset; optional: frozenset; compile: Callable; # compile(effect_json, env) -> Callable[[ExecCtx], None]
EFFECTS: dict[str, EffectSpec]                                 # fonte única: gera também o schema
```
O que cada arquivo atual vira: **`loop.py`** — intocado; ganha `AudioDispatcher` extraído; **`state.py`** — intocado; `SimState` é irmão; **`actions.py`** — intocado; texto continua usando; RTS usa `sim/commands.py`.

---

## 5. Pilar 4 — Plano de implementação (fases pequenas e verificáveis)

Estimativas de esforço abaixo são **[I]** (palpite de engenharia para uma pessoa focada; não compromisso). Cada fase termina com testes automatizados e **não pode quebrar** os 200 testes do v0.1 (`pytest -q` continua verde).

### 5.1 Estrutura de diretórios recomendada (aditiva; o v0.1 não é movido)

```text
C:\MOJO\mojo\                         (pasta onde o Gui já tem o Python 3.12 — inferido do pedido [I])
  pyproject.toml                      # + extras:  serve = [fastapi, uvicorn, websockets]
  mojo.config.json                    # opcional (porta, origins extras, Ragnarok, adaptador)
  packs\                              # jogos (pacotes): elemental-proto\  poc-mini\   (copiados de docs\v2\example)
  examples\azrael.mjo                 # v0.1, inalterado
  schema\                             # + mojo-world-0.2.schema.json  mojo-part-0.2.schema.json  (cópia empacotada em src\mojo\pack\)
  src\mojo\
    cli.py  config.py  __main__.py    # + subcomandos: serve, validate (pacotes), replay
    core\      rng.py  clock.py                         # novo   (esqueleto: docs\v2\skeleton\mojo_v2\core)
    pack\      loader.py  migrate.py  expr.py  effects.py  compile.py  lint.py   # novo
    world\     (v0.1: paths.py  loader.py  migrations.py  ...)                    # reaproveitado; migrations.py ganha 0.1→0.2
    engine\    (v0.1: loop.py  state.py  actions.py  events.py)                   # vira perfil turn-text-v0, sem mudanças
    profiles\  base.py  turn_text.py  tick_grid.py                                # novo
    sim\       state.py  commands.py  engine.py  replay.py  snapshot.py
               systems\ movement.py combat.py economy.py production.py rules.py victory.py   # novo
    semantic\  (v0.1)                                                             # reaproveitado
    audio\     ragnarok.py (v0.1) + dispatch.py                                    # dispatch.py extraído de loop.py
    server\    app.py  protocol.py  session.py  security.py  narration.py  static\ (index.html app.js net.js state.js render.js input.js ui.js style.css sw.js manifest.webmanifest)
    store\     saves.py  logs.py (v0.1) + replay_store.py                          # replay em lote
  tests\       (v0.1)  + tests\v2\ (pack, sim, server, e2e)
  docs\        MOJO-V2-PROPOSTA.md  v2\ (exemplos, schemas, bench, skeleton)
  .mojo\       saves\ logs\ replays\ cache\audio\
```

### 5.2 Fases

| Fase | Entrega | Critério de aceite (verificável) | Testes |
|---|---|---|---|
| **F0** (0,5 d) Fundação | `core/rng.py`, extra `[serve]` no `pyproject.toml`, `tests/v2/` vazio, `mojo --version` | `pytest -q` do v0.1 = **196 passed + 4 skipped (200 coletados)** sem alteração, verificado nesta box; `pip install -e ".[serve]"` ok no Windows | vetores do RNG (os 3 valores de §4.2); `smoke.py` do esqueleto como teste |
| **F1** (1–1,5 d) Pacote v0.2 | `pack/loader.py` (`load_pack`), schemas 0.2 empacotados, `MIGRATIONS[(0,1)]`, compilador de expressões (`pack/expr.py`), `mojo validate packs\…` | `elemental-proto` e `poc-mini` validam; **os 13 casos maliciosos** de `check_example.py --self-test` viram testes e são rejeitados; `azrael.mjo` v0.1 carrega via migração **e** ainda via `mojo play` | pacote válido/ inválido/ versão futura/ include inseguro/ expressão (profundidade, float, op fora da whitelist)/ migração (conteúdo preservado, entrada intacta)/ erro legível com `arquivo: caminho` |
| **F2** (1–2 d) Núcleo de ticks | `sim/state.py`, `sim/engine.py` (ordem fixa), `sim/commands.py`, sistemas `commands`, `movement` (greedy + cap de A\*), `economy`, `combat`, `cleanup` | mesma seed + mesmos comandos ⇒ **mesmo hash** em 2 execuções **e** em Python 3.12 vs 3.13; replay reproduz checkpoints; adulteração do log ⇒ desync no tick certo; `bench` de 500 unidades **≤ 5 ms/tick na box** (meta de regressão, não promessa para o PC do Gui) | determinismo, ordem de chegada de comandos, replay/desync, limites (`max_entities`), comando inválido não muda hash |
| **F3** (1 d) Regras e entropia | `pack/compile.py` (regras → closures), `sim/systems/rules.py`, efeito `wave`, `var_*`, `damage/heal/push/status`, vitória/derrota | tabela de ondas da **seed 777** (§2.5) reproduzida **exatamente** pelo motor; estabilizador da Terra reduz entropia; Fogo cura na onda; Ar é empurrado; `coop_survive` encerra com vitória | golden das ondas; um teste por facção; teto `max_effects_per_tick` (descarte determinístico); `rule_overflow` |
| **F4** (1–1,5 d) Servidor | `server/app.py`, `protocol.py`, `session.py`, `security.py`; `mojo serve` | handshake da §3.5 (9 casos) como testes; cliente Python headless joga `poc-mini` até a vitória; rajada ⇒ `rate_limited`; **instalação no Windows aprovada pelo Gui** | origem/host/token, mensagem inválida, posse de unidades, limites do mapa, desconexão/reconexão com `snapshot_req` |
| **F5** (1–2 d) Cliente web | `static/*` (canvas, seleção, painéis, interpolação) | no Windows: grid 16×12 e 24×16 desenhados, seleção + botão direito movem, recursos e previsão de onda visíveis; Playwright headless gera captura **sem erro de console**; fps medido **pelo Gui** com o navegador dele | smoke Playwright (carrega, conecta, recebe `welcome`, aplica `delta`); teste de CSP (nenhum recurso externo) |
| **F6** (1 d) Narração e Ragnarok | `server/narration.py`, `audio/dispatch.py`, rota `/audio/<sha256>.wav` | eventos de onda geram `narration` imediata e `narration_audio` quando o Ragnarok está no ar; Ragnarok desligado ⇒ só texto, **p99 do tick não piora** (medir com/sem narração) | rota de áudio só aceita `^[0-9a-f]{64}\.wav$`; Ragnarok falso 500/timeout; limite de taxa |
| **F7** (1–2 d) Coop e extras | 2+ clientes, `controller:"idle"` e primeira IA scriptada simples, export/import de replay, (opcional) `TextSession` servindo `azrael.mjo` | 2 abas = `p1`/`p2` cooperando na mesma partida; `mojo replay arquivo.replay` verifica hashes; modo texto no navegador igual ao CLI | dois clientes, ordem estável, replay de partida cooperativa |
| **Depois** [P] | `.mjopack` assinado, mods com patches, lockstep entre PCs, editor visual, SFX/ambiência, IA avançada, fog of war, regras de construção/projéteis | — | — |

### 5.3 Passos exatos de código (esqueletos e trechos)

**(a) `pyproject.toml`** — acrescentar (sem remover nada):
```toml
[project.optional-dependencies]
dev = ["pytest>=8"]
serve = ["fastapi>=0.110", "uvicorn>=0.30", "websockets>=12"]

[tool.setuptools.package-data]
"mojo.world" = ["*.json"]
"mojo.pack" = ["*.json"]
"mojo.server" = ["static/*", "static/**/*"]
```

**(b) `pack/loader.py`** — generaliza `world/loader.py::load_world` (mesmo pipeline por arquivo):
```python
@dataclass(frozen=True)
class Pack:
    root: Path
    manifest: dict
    parts: dict[str, list[tuple[str, dict]]]     # kind -> [(caminho_relativo, doc)]
    file_sha256: dict[str, str]
    @property
    def sha256(self) -> str: ...                  # hash ordenado de (caminho, sha) — vai em replay e saves

def load_pack(root: Path, *, migrations: dict | None = None, limits: PackLimits = PackLimits()) -> Pack:
    """1) world.mjo via _read_json_strict (tamanho, UTF-8, duplicatas, NaN, profundidade)  [reuso de world/loader.py]
       2) ensure_supported(doc)  [world/migrations.py]  3) schema 0.2 do manifesto
       4) para cada include: resolve_inside(root, rel) [world/paths.py] -> leitura estrita -> schema da parte
       5) referências cruzadas e compilação das regras (pack/compile.py). Levanta WorldError(source, errors) com TODOS os erros."""
```

**(c) `pack/compile.py`** — da mini-linguagem às closures (base: `docs/v2/bench/expr_proto.py`):
```python
@dataclass
class CompiledRule:
    id: str; trigger: Trigger; scope: str; filter: Filter | None
    when: Callable[[ExecCtx], bool] | None; effects: list[Callable[[ExecCtx], None]]; cost_nodes: int

def compile_pack(pack: Pack, scenario_id: str) -> CompiledPack: ...   # rejeita tudo que não está na whitelist
```

**(d) `sim/systems/` e registro de ordem fixa** (a lista é o contrato; `engine.profile` versiona a ordem):
```python
SYSTEMS_TICK_GRID_V0: tuple[tuple[str, System], ...] = (
    ("commands", commands.run), ("ai", ai.run), ("rules_every", rules.run_every),
    ("production", production.run), ("economy", economy.run), ("movement", movement.run),
    ("combat", combat.run), ("rules_events", rules.run_events), ("cleanup", cleanup.run), ("victory", victory.run),
)
```

**(e) `cli.py`** — novo subcomando (o `play` não muda):
```python
sv = sub.add_parser("serve", help="servir um pacote no navegador (127.0.0.1)")
sv.add_argument("pack"); sv.add_argument("--scenario"); sv.add_argument("--seed", type=int)
sv.add_argument("--port", type=int, default=8770); sv.add_argument("--open", action="store_true")
sv.add_argument("--config"); sv.set_defaults(fn=cmd_serve)

def cmd_serve(a) -> int:
    try:
        import uvicorn                                   # extra [serve]
    except ImportError:
        print('Falta o extra: pip install -e ".[serve]"', file=sys.stderr); return 2
    cfg = load_config(a.config)
    pack = load_pack(Path(a.pack))                        # WorldError -> mensagem legível (main já trata)
    token = new_token()
    session = make_session(pack, a.scenario, cfg, seed=a.seed)      # profiles/tick_grid.py ou turn_text.py
    app = create_app(session, port=a.port, token=token, tick_hz=pack.manifest.get("sim", {}).get("tick_hz", 10))
    url = f"http://127.0.0.1:{a.port}/?t={token}"
    print(f"MOJO V2 em {url}   (Ctrl+C para parar)")
    if a.open: threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    return 0
```

**(f) Servidor** — o esqueleto testado está em `docs/v2/skeleton/mojo_v2/server/app.py` (WebSocket `/ws`, Origin/Host/token, limite de tamanho e de taxa, `ack`, ticker com correção de deriva). Falta: difusão de `delta`, validação real de comando, `welcome` com mapa/defs, rota `/audio/{hash}.wav`, estáticos.

**(g) Cliente** — `net.js` (conexão + reconexão), `state.js` (aplica `delta`), `render.js` (tiles offscreen + entidades + interpolação):
```js
// state.js (trecho)
export function applyDelta(world, d) {
  for (const [id, x, y, hp] of d.u) { const e = world.ents.get(id) ?? {px: x, py: y}; e.px = e.x ?? x; e.py = e.y ?? y; Object.assign(e, {x, y, hp}); world.ents.set(id, e); }
  for (const id of d.r) world.ents.delete(id);
  Object.assign(world.vars, d.v ?? {}); world.tick = d.k;
}
```

### 5.4 Instalação e execução no Windows (para o Gui — **só depois da autorização dele; nada foi instalado**)

Pré-requisito: Python 3.12 já instalado (pedido do Gui). Comandos (PowerShell ou `cmd`), assumindo o projeto em `C:\MOJO\mojo` **[I]**:
```bat
cd C:\MOJO\mojo
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[serve,dev]"
.venv\Scripts\mojo validate packs\poc-mini
.venv\Scripts\mojo serve packs\poc-mini --open
```
Atalho `C:\MOJO\mojo\mojo-serve.bat` **[P]**:
```bat
@echo off
cd /d C:\MOJO\mojo
".venv\Scripts\mojo.exe" serve packs\poc-mini --open
pause
```
(Crie um atalho para esse `.bat` na Área de Trabalho.) Ragnarok, **opcional e separado**: `ragnarok.bat web` (porta 8765) antes ou depois; sem ele o jogo narra só em texto. Observações **[I]**: tráfego só em `127.0.0.1` normalmente não dispara o aviso do Firewall; o `pip install` precisa de internet uma vez; o venv do MOJO é independente do do Ragnarok. **Nada disto foi testado no Windows** (a box é Linux); o que foi exercitado na box: Python 3.12.15 + `fastapi/uvicorn/websockets` + esqueleto + handshake **[T]**.

### 5.5 Riscos e limitações

| # | Risco / limitação | Impacto | Mitigação |
|---|---|---|---|
| 1 | **Python puro para RTS pesado** | teto de entidades (§4.7); ≥1.500 é projeto | orçamentos no manifesto (`max_entities`), IA escalonada, *flow fields*, depois núcleo nativo/PyPy (não avaliados) |
| 2 | Rajadas de pathfinding (A\* 0,5 ms; BFS 4–6 ms **[M]**) | picos de tick quando muitas ordens chegam juntas | fila + teto por tick; *flow field* por grupo; cache por destino |
| 3 | Laço único `asyncio`: um tick lento atrasa envio | jitter/lag visual | política de recuperação (≤3 ticks) e desaceleração; medir p99 no Windows |
| 4 | Resolução de timer do Windows (≈15,6 ms por padrão **[I]**) | jitter de ±16 ms em 10 Hz | agenda com correção de deriva **[T]**; 10 Hz tolera |
| 5 | Dessincronização por float/ordem/RNG | replay e coop quebram | só inteiros, ordem fixa, RNG próprio, hashes de checkpoint **[T]** |
| 6 | DSL crescendo demais ("linguagem proprietária complexa") | manutenção e segurança | lista fechada versionada por `engine.profile`; extensões novas = novo perfil, não flags livres |
| 7 | Mecânicas que dados não expressam (construção com restrições, projéteis, fog of war) | jogo não cabe na DSL | pontos de extensão como **sistemas** nativos selecionados por `engine.profile` (não por código do pacote) |
| 8 | Fluidez do canvas no PC do Gui **não medida** | UI pode engasgar | medir na F5; reduzir resolução/entidades; evitar relayout DOM por quadro |
| 9 | Ragnarok serializa pedidos `/v1` e leva ~0,6–2,4 s **[M]** | voz atrasada | narração assíncrona com fila e descarte; tick nunca espera |
| 10 | Segurança local: Origin forjável por processo local; token na URL | malware local não é coberto | modelo de ameaça declarado; sem upload, sem eval, estáticos fixos; LAN só com decisão do Gui |
| 11 | Dependências novas (`fastapi`, `uvicorn`, `websockets`) e venv separado | mais superfície e manutenção | versões mínimas fixadas; pacote de rodas offline opcional |
| 12 | Autoria em JSON (sem comentários) | fricção do designer | `$comment`, formatador, (opcional) conversor YAML→JSON **fora** do runtime |
| 13 | Nenhum teste no Windows nem no navegador do Gui | surpresas de instalação/UX | F4/F5 incluem verificação manual guiada e logs de diagnóstico (`mojo doctor`) |
| 14 | O jogo de exemplo é **só exemplo** | números sem teste de jogo | balanceamento é decisão/iteração do Gui; nenhuma afirmação de equilíbrio |

**Não está pronto para produção.** Tudo em §2–§5 além do que está rotulado **[V]/[M]/[T]** é **projeto**.

### 5.6 Primeiro jogo-protótipo (prova de conceito do mesmo dia): `poc-mini`

**Escopo mínimo [P]:** grid **16×12**, **2 facções** (Fogo e Terra, cooperando — o jogo mais curto que exercita a tensão entropia alta × baixa), **1 recurso** (`essence`, 4 nós), **1 onda de entropia** (disparo no tick 300 por padrão; vitória ao sobreviver a ela com os dois `core` vivos). Já existe e valida **[T]**: `docs/v2/example/poc-mini/` (manifesto + `factions/{fire,earth}.json` + `rules/{economy,entropy,victory}.json` + `scenarios/mini.json` + tema + recursos; 11 regras compiladas pelo protótipo).

Roteiro de um dia (**estimativa [I]: 6–10 h focadas; "mesmo dia" é otimista**):
1. **(1–2 h)** `pack/loader.py` mínimo (reusar `world/paths.py`, leitura estrita) + `mojo validate packs\poc-mini` — critério: `OK: poc-mini …` e os casos maliciosos rejeitados.
2. **(2–3 h)** `sim/` mínimo: `SimState`, `TickEngine` (copiar o esqueleto), sistemas `commands`, `movement` (greedy), `economy` (coleta), regras `wave`/`var_*`/`damage`/`heal`/`end` — critério: seed 1, 300 ticks ⇒ hash estável (golden) e onda no tick 300.
3. **(2 h)** `mojo serve` + cliente mínimo: desenhar grid e entidades, clicar para selecionar, botão direito mover, contador de essência, contagem regressiva da onda — critério: abrir `http://127.0.0.1:8770/?t=…` e ver a onda ferir/curar.
4. **(1 h)** testes: replay golden, handshake, comando inválido; verificação manual no Windows.

**Fora do mesmo dia:** IA, construção, produção em fila, narração/voz, PWA, os 4 elementos e o cenário 24×16.

---

## 6. Decisões que dependem do Gui

1. **JSON em runtime** (recomendado) — aceita YAML apenas como ferramenta de autoria fora do motor, ou prefere só JSON?
2. **Taxa de tick:** 10 Hz (proposto) ou 20 Hz (custo ~2×).
3. **Metas de escala:** ≤ 400 entidades confortáveis / ≤ 800 estendido, mapas até 64×64 — está de acordo, ou o RTS desejado é maior (o que muda o plano para núcleo nativo)?
4. **Cooperativo:** só na mesma máquina (abas) ou **também em rede local** (exige `--lan`, token e aviso de segurança)?
5. **Instalação no Windows:** autoriza criar o venv e instalar `fastapi`, `uvicorn`, `websockets` em `C:\MOJO\mojo\.venv`? (nada foi instalado; exigido antes da F4)
6. **Localização do projeto e pasta `packs\`** (confirmar `C:\MOJO\mojo`), repositório/licença.
7. **Refatorar o v0.1 para `profiles/`** agora ou manter lado a lado (recomendado: lado a lado até a F7).
8. **PWA** (instalável) é desejado, ou basta abrir no navegador?
9. **Narração por voz** (Ragnarok) já na primeira versão do RTS (F6) ou depois? Qual perfil de voz para eventos (`narrator_default` = `alex-pt` hoje)?
10. **IA:** só `idle` e controle humano na primeira versão, ou IA scriptada simples já na F7?
11. **Mods** (`mods[]` com patches) entram na v2.0 ou ficam para depois?
12. **Jogo real:** o exemplo das 4 facções é só técnico — qual é o **design oficial** (nomes, unidades, números, objetivo)? Eu não invento canon.
13. **Versão mínima do Python:** fixar 3.12 (Windows do Gui) ou manter ≥ 3.11 (o v0.1 declara ≥ 3.11; medições e esqueleto foram rodados na box só com 3.12 e 3.13).
14. **Quem balanceia** os números (fica com o Gui; os do exemplo são ilustrativos).

---

## 7. Anexo — artefatos desta proposta e como reproduzir (tudo na box)

| Artefato | Caminho | O que prova |
|---|---|---|
| Exemplo completo (4 facções) | `docs/v2/example/elemental-proto/` | JSON válido; 12 arquivos; 14 regras compiladas |
| PoC mínimo | `docs/v2/example/poc-mini/` | 9 arquivos; 11 regras compiladas |
| Schemas v0.2 | `docs/v2/schema/mojo-world-0.2.schema.json`, `mojo-part-0.2.schema.json` | validam os exemplos; rejeitam mutações |
| Protótipo da mini-linguagem | `docs/v2/bench/expr_proto.py` | whitelist, limites, closures |
| Verificador | `docs/v2/bench/check_example.py` | schema + paths v0.1 + referências + 13 casos maliciosos |
| Onda de referência | `docs/v2/bench/wave_preview.py` | tabela da §2.5 (seed 777) |
| Benchmarks | `docs/v2/bench/tick_bench.py`, `dsl_bench.py`, `wsspike.py`+`wsclient.py`, `result_*.json` | números da §4.7 e §3.2 |
| Esqueleto executável | `docs/v2/skeleton/mojo_v2/` (`core/rng.py`, `sim/engine.py`, `server/{security,app}.py`, `pack/migrate.py`) | determinismo, replay, desync, Origin/Host/token, migração |
| Fumaça / handshake / migração | `skeleton/smoke.py`, `ws_handshake_test.py` (+`run_spike.py`), `test_migrate.py` | resultados citados nas §3.5, §4.2–4.5, §2.7 |

Reproduzir (da raiz do repo, venv do v0.1 com `jsonschema`):
```bash
PYTHONPATH=src:docs/v2/bench .venv/bin/python docs/v2/bench/check_example.py docs/v2/example/elemental-proto --self-test
PYTHONPATH=src:docs/v2/bench .venv/bin/python docs/v2/bench/check_example.py docs/v2/example/poc-mini
python3 docs/v2/bench/tick_bench.py --sizes 200,500,1000,2000 [--ai-stagger 5]
python3 docs/v2/bench/dsl_bench.py ;  python3 docs/v2/bench/wave_preview.py 777
cd docs/v2/skeleton && python3 smoke.py && ../../../.venv/bin/python test_migrate.py
# WebSocket (precisa de venv com fastapi uvicorn websockets):  python run_spike.py &  python ws_handshake_test.py
```
**Ambiente das medições [M]:** box Linux, Intel Xeon 8 vCPU (nuvem), 16 GB, Python 3.13.5 (venv do v0.1) e 3.12.15 (venv temporário com `fastapi 0.162.0`, `uvicorn 0.54.0`, `websockets 17.3`). **Não é a máquina do Gui.** Nada foi medido no Windows, no navegador nem com LLM real.
