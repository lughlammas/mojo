# MOJO v0.1 — o que foi implementado e onde diverge do documento de arquitetura

**Estado:** protótipo funcional, **não pronto para produção**. Decisões abertas usaram os padrões de `DECISOES-PENDENTES.md`.

## Padrões adotados (decisões do Gui ainda em aberto)
| # | Decisão | Padrão usado na v0.1 |
|---|---|---|
| 1 | Stack | Python ≥ 3.11 (testado em 3.11.17 e 3.13.5 na box); única dependência: `jsonschema` |
| 3 | Modelo de linguagem | Adaptador `mock` (padrão, sem rede). `local`/`remote` são só interface, desligados |
| 4 | Canon de Azrael | `examples/azrael.mjo` com `meta.canon=false`; nenhum canon inventado |
| 5 | Voz do narrador | `narrator_default` → `alex-pt` (Kokoro pm_alex), configurável em `mojo.config.json` |
| 6 | Idioma | PT-BR |
| 7 | Cliente | CLI textual |
| 8 | Ragnarok | HTTP em `127.0.0.1:8765`, iniciado à mão; fallback para modo texto |
| 11 | `rpg-minimal-v0` | Conteúdo mínimo proposto abaixo |
| 12 | Saves/logs | `./.mojo/{saves,logs,cache}` (ou `$MOJO_HOME`), sem envio externo |

## Lacunas do brief preenchidas (PROPOSTAS, não canon)
- **Entidades inspecionáveis:** `world.scenes[].entities[] = {id, name, aliases?, description, inspect_text?, speakable?, speak_reply?}`.
- **Saídas:** `exits[] = {id, to, label, requires?{flag?|item?}, blocked_text?}`; `requires` é declarativo, nunca expressão.
- **Ação extra `go`:** existe no motor, mas só vale se o mundo a listar em `allowed_actions` (o `azrael.mjo` não lista; por isso `go` é "ação proibida" nele).
- **`rpg-minimal-v0`:** estado = `scene`, `hp`/`max_hp` (0..max_hp, limitado), `inventory` (ids únicos), `flags` (bool/int/texto curto), `turn`, `history` (últimos 10). Eventos (lista fechada, ADR-011): `set_flag`, `give_item`, `remove_item`, `hp_delta`, `move`. `rules.allowed_events` define quais o **modelo pode propor** (padrão: só `set_flag`). `inspect` grava a flag `inspected:<id>` (prefixo reservado ao núcleo); `go` executa `move`. Não há combate, dano, morte nem registro de itens — mundos futuros precisarão disso.
- **`meta`** `{canon, author, note}` e **`resources[]`** (apenas validados; nenhum recurso é carregado na v0.1).

## Desvios em relação a ARQUITETURA.md
- Limites do loader: arquivo ≤ 1 MB, ≤ 256 cenas, profundidade JSON ≤ 24, textos ≤ 2.000 caracteres (doc dizia 500 cenas/16/8.000). Validação sempre estrita (sem "modo permissivo").
- Política de versão na série 0.x: só aceita `0.1.x`; `0.2+`/`1+` é rejeitado como "mais novo"; `0.0.x` só com migração registrada. O registro `MIGRATIONS` está **vazio** (não existe versão anterior); o mecanismo é testado com migração injetada.
- `mojo state` e `mojo log` são comandos **dentro da sessão** (`state`, `log [n]`), não subcomandos de topo. Subcomandos: `play`, `validate`, `audio-check`.
- `interpret()` de texto livre e "semente do jogo" **não** foram implementados: o analisador de comandos é determinístico (verbos PT/EN) e o mock não usa aleatoriedade.
- Config de exemplo: `mojo.config.example.json` na raiz. Schema canônico em `schema/` com cópia empacotada em `src/mojo/world/` (um teste garante que são idênticos).
- `RagnarokAdapter`: usa `GET /api/status` e `POST /v1/audio/speech` (`wav`); o 500 do Ragnarok em texto puro é tratado como falha sem tentar interpretar JSON. Não há uso de `/api/jobs`, streaming nem início automático do Ragnarok.
