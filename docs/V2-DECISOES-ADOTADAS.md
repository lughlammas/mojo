# MOJO V2 — decisões adotadas (padrões da proposta)

Em 27/10/2026 o Gui aprovou a proposta (`docs/MOJO-V2-PROPOSTA.md`) e mandou **implementar sem entrevistas**, preservando o que é urgente para a produção. Cada decisão em aberto da §6 da proposta recebeu o **padrão recomendado** ali. Tudo abaixo é **reversível** pelo Gui: basta dizer.

| # | Pergunta (§6) | Decisão adotada | Onde está no código/doc | Como reverter |
|---|---|---|---|---|
| 1 | Formato em runtime | **JSON estrito** (UTF-8, sem chaves duplicadas, sem `NaN`, **sem floats**, ≤1 MB/arquivo, profundidade ≤24, ≤200 arquivos, ≤8 MB). YAML só como autoria fora do motor. | `pack/loader.py::read_json_strict` | — (YAML exigiria conversor externo) |
| 2 | Taxa de tick | **10 Hz** (`sim.tick_hz`, 1–30; o pacote pode mudar) | `pack/model.py::DEFAULT_SIM` | editar `sim.tick_hz` no `world.mjo` |
| 3 | Escala | **400 entidades confortáveis / 800 estendido**, mapas pequenos/médios (testado 32×24); acima disso → núcleo nativo (fora do escopo) | `sim.max_entities` (padrão 400; teto 5000) | `sim.max_entities` |
| 4 | Cooperativo | **Mesma máquina (abas)**. Rede local **só** com `--lan` explícito (aviso impresso; token continua obrigatório; Host/Origin aceitam IP privado literal) | `server/security.py::Policy` | `mojo serve --lan` |
| 5 | Instalação no Windows | **Nada foi instalado no PC do Gui.** O `INSTALAR-V2.bat` faz isso quando **ele** rodar: reutiliza `C:\MOJO\mojo\.venv` se existir; senão cria | `INSTALAR-V2.bat` | — |
| 6 | Local do projeto | `C:\MOJO\mojo` (igual ao v0.1); packs em `packs\` | `INSTALAR-V2.bat` | editar `DEST` no .bat |
| 7 | Refatorar v0.1 para `profiles/` | **Não.** Lado a lado: v0.1 intacto; V2 é um núcleo **aditivo** `sim/` com perfil `tick-grid-v0` | `src/mojo/{core,pack,sim,server}/` | — |
| 8 | PWA | **Não** (abrir no navegador). Fora do escopo | — | futuro |
| 9 | Narração por voz | **Opcional**, fora do tick, via o `RagnarokAdapter` do v0.1; sem Ragnarok → só texto. Perfil de voz `narrator_default` | `server/narration.py` | `--audio off` |
| 10 | IA | **IA scriptada declarativa** (objetivos `train/build/gather_idle/attack` em `ai_scripts` da facção) já na primeira versão | `sim/ai.py` | cenário `controller: human` |
| 11 | Mods | **Fora da v2.0**: `mods` não vazio → erro explícito "mods ainda não são suportados" | `pack/loader.py` | futuro |
| 12 | Jogo oficial | **Não inventei canon.** `poc-mini` e `elemental-proto` são exemplos técnicos; **todos os números são ilustrativos** | `packs/*/` | substituir os JSON |
| 13 | Python | **≥ 3.11** (o v0.1 declara ≥ 3.11). Medido na box só com 3.13 | `pyproject.toml` | — |
| 14 | Balanceamento | Fica com o Gui; nada foi balanceado | — | — |

## Decisões técnicas tomadas durante a implementação (não estavam em §6)

| Tema | Decisão | Motivo |
|---|---|---|
| Dependências | `fastapi`, `uvicorn`, `websockets` como extra `serve`; `jsonschema` já usado. Sem CDN, sem serviço externo/pago, sem build de frontend (ES Modules + Canvas 2D puros) | Diretriz do Gui |
| Soberania do texto | Comportamento, mundos, regras, facções, cenários e IA **só** em JSON local; o núcleo genérico não tem regra de domínio (nenhuma palavra "fogo/terra/onda" no `sim/`) | Diretriz do Gui |
| Expressões | Mini-linguagem fechada em JSON (lista branca de operadores), tipada, com limite de profundidade (8) e nós (`max_rule_nodes`); compila para closures; **sem `eval`/`exec`** | Segurança + determinismo |
| Inteiros | Todo o estado é inteiro (`div` por piso; divisor 0 → 0; `|x| ≤ 1e9`) | Hash idêntico entre máquinas |
| RNG | SplitMix64 por subsistema, derivado de `blake2b(f"{seed}:{stream}")`; fluxos internos `ai` e `engine` + os `rng_streams` do pacote | Isolamento: sortear mais em um sistema não desloca as ondas |
| Ordem dos sistemas | `commands → ai → rules_every → production → economy → status → movement → combat → rules_events → cleanup` (fixa; testada) | Determinismo |
| Comandos | Ordenados por `(tick, slot, seq)`; entram com atraso de **1 tick** (`INPUT_DELAY_TICKS=1`); pausa/velocidade são do servidor e **não** vão ao log | Base para lockstep futuro |
| IA no replay | Comandos da IA **não** são gravados: ela é função determinística do estado e é reexecutada | Log menor; replay prova a IA |
| Replay | JSONL: cabeçalho (engine, `pack_sha256`, cenário, seed), comandos, checkpoints (hash a cada 50 ticks), fim. `pack_sha256` diferente → recusa (a menos de `--force`) | Detectar divergência no tick certo |
| Snapshots | Atômicos (`tmp` na mesma pasta + `fsync` + `os.replace`); a cada `sim.snapshot_every_ticks` (100) e sob demanda (botão Salvar) | Diretriz do Gui |
| Segurança do servidor | `127.0.0.1`; Host e Origin estritos também no WebSocket; token por execução (`hmac.compare_digest`); CSP `default-src 'none'` sem inline; estáticos por lista branca; áudio só por `^[0-9a-f]{64}\.wav$`; limite de 4096 B e 120 msg/s por cliente; `/docs` e `/openapi.json` desligados | Diretriz do Gui + proposta §4 |
| Porta | **8770** (Ragnarok usa 8765) | Evitar conflito |
| Migração 0.1 → 0.2 | Função pura (`pack/migrate.py`): adiciona `kind: text-adventure` e `engine.profile: turn-text-v0`; `downgrade_to_0_1` serve de prova de que o conteúdo é preservado | Compatibilidade |
| `mojo validate` | Arquivo `.mjo` v0.1 → comportamento antigo; **pasta** → validador de pacote V2 | Sem quebrar o v0.1 |
| Fim de jogo | Regras `end` / `eliminate_faction` do próprio pacote; o motor para de avançar e recusa comandos depois do fim | Dados, não código |
| Texto/log da UI | Modelos `{campo}` no `assets/theme.json` (`texts`, `narration`, `hud`), renderizados por substituição segura (sem formatação arbitrária) | Soberania do texto |
| Versão do pacote Python | `pyproject` passa a `0.2.0`; `mojo.__version__` do v0.1 continua `0.1.0`; versão do V2 em `mojo/core/version.py` | Não alterar o v0.1 |
