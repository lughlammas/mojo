# MOJO V2 (0.2.0) — jogo de grade em tempo real, 100% local

> **Estado: protótipo funcional, não pronto para produção.** Números dos pacotes de exemplo são **ilustrativos** (não são canon). Testado na box (Linux); **não testado no Windows nem no navegador do Gui** — os `.bat` seguem o mesmo padrão do v0.1 (que o Gui já usa), mas ainda não foram executados lá.

O V2 é um núcleo **aditivo** ao MOJO v0.1: um motor de ticks fixos (`tick-grid-v0`) que lê **pacotes de jogo em JSON** (pastas com um manifesto `world.mjo`), serve uma interface web **só em `127.0.0.1`** (FastAPI + WebSocket) e desenha em Canvas 2D (ES Modules, sem CDN, sem build). O modo texto/CLI do v0.1 continua **idêntico** (`mojo play`, `mojo validate`).

Princípios (diretriz do Gui): comportamento, mundos, regras, facções e cenários **só em JSON local**; nada hardcoded no núcleo, nada na nuvem; tudo validado por schema (`additionalProperties:false`) **antes** do primeiro tick; sem `eval`; limites duros; caminhos seguros.

## Instalar (Windows) — quando o Gui quiser

1. Extraia `MOJO-V2-Windows.zip`.
2. Duplo clique em **`INSTALAR-V2.bat`**. Ele copia o app para `C:\MOJO\mojo`, **reutiliza** o venv `C:\MOJO\mojo\.venv` se existir (senão cria), instala `fastapi`, `uvicorn`, `websockets`, `jsonschema` (primeiro das rodas offline da pasta `wheels`, se compatíveis; senão pela internet) e valida os pacotes de exemplo.
3. Para jogar: **`C:\MOJO\mojo\SERVIR.bat`** (abre o navegador em `http://127.0.0.1:8770/?t=<token>`).

Linux/macOS (como foi testado): `python -m venv .venv && .venv/bin/pip install -e ".[serve]"` e depois `mojo serve packs/poc-mini --open`.

## Comandos

```text
mojo serve <pasta-do-pacote> [--scenario ID] [--seed N] [--port 8770] [--open] [--lan] [--audio auto|off]
                             [--home PASTA] [--no-record] [--resume snapshot.json]
mojo pack-validate <pasta | arquivo.mjo>     valida (e, para .mjo v0.1, migra para 0.2 em memória)
mojo validate <pasta | arquivo.mjo>          igual ao v0.1 para .mjo; pasta → validador V2
mojo simulate <pasta> --scenario ID --ticks N    roda sem interface; imprime JSON com o hash final
mojo replay <arquivo.jsonl> [--pack pasta] [--force]   reexecuta e verifica hashes (sai com 1 se divergir)
mojo play <arquivo.mjo>                      v0.1, texto (inalterado)
```

No Windows use `mojo-v2.bat <mesmos argumentos>` (ex.: `mojo-v2.bat serve packs\elemental-proto --scenario quarteto --open`).

## Pacotes incluídos (`packs/`)

| pacote | o que é | cenários |
|---|---|---|
| `poc-mini` | Fogo + Terra, grade 16×12, 1 recurso (`essence`) | `mini` (você = Fogo, coop contra a entropia, vence ao sobreviver à onda do tick 300), `duel` (Fogo humano × Terra IA), `coop2` (2 humanos), `ai_duel` (IA × IA) |
| `elemental-proto` | **Ar / Água / Fogo / Terra** + entropia, 24×16 e 32×24 | `coop_vs_entropy` (seed 777), `duel_fire_water`, `coop2`, `quarteto` (4 times; você = Ar), `quarteto_ai` |

Assimetria **por dados**: Fogo é alimentado pela onda (cura + status `inflamed`); Terra resiste e tem o `stabilizer` (reduz a entropia); Ar é empurrado pela onda (e tem a habilidade `gust`); Água regenera e tem `mist_healer` (habilidade `mend`) mas **erode** as estruturas. Tudo isso são regras JSON em `factions/*.json` e `rules/*.json`.

## Jogando

* **Botão esquerdo**: selecionar (clique/arrastar; Shift acumula). **Botão direito**: mover / coletar (nó de recurso) / atacar (inimigo). **Espaço**: pausa. **1/2/3**: velocidade 1×/2×/4×. **S**: parar. **Esc**: cancelar modo/seleção.
* Selecionou uma estrutura: botões **Treinar …** (fila de até 5) e **Cancelar último**. Selecionou operários: **Construir …** (clique na grade; o fantasma verde/vermelho mostra se cabe) e **habilidades**.
* Painéis: Recursos (inclui suprimento), Entropia (variáveis do pacote + próxima onda), Seleção, Comandos, Registro.
* **Coop na mesma máquina**: abra uma segunda aba na mesma URL — ela assume o próximo slot humano livre; a terceira vira espectadora. A partida só avança quando há um humano conectado e **pausa sozinha** quando o último sai.
* `--lan` (perigoso, só se você quiser jogar em outra máquina da rede): escuta em `0.0.0.0`, aceita Host/Origin de IP privado; o token continua obrigatório.

## Estrutura de um pacote (tudo texto)

```text
meu-jogo/
  world.mjo                 manifesto: sim{tick_hz,max_entities,...}, includes{resources,factions,rules,scenarios}, ui.theme, audio, mods:[]
  resources/*.json          recursos (derivados como `supply`, nós com `node_amount`)
  factions/*.json           unidades, estruturas, status, habilidades, regras próprias, ai_scripts
  rules/*.json              variáveis, rng_streams, regras (on every_ticks | event → for world|team|faction|entity → when → do[])
  scenarios/*.json          grade (legenda floor|rock|node:<rec>|spawn:<id>), times, jogadores (human|scripted), objetivos
  assets/theme.json         cores, textos do registro (`texts`), narração (`narration`), HUD
```

Expressões (`when`, valores) são JSON numa lista branca: `all/any/not`, `eq/ne/lt/lte/gt/gte`, `add/sub/mul/div/mod/min/max/neg/abs`, `ref`, `has_tag`, `rand_below`, `count`. Efeitos: `var_add var_set add_resource damage heal push spawn status wave eliminate_faction end emit schedule`. Os schemas estão em `src/mojo/pack/schemas/` (e a explicação completa na proposta, `docs/MOJO-V2-PROPOSTA.md`).

**Adicionar uma facção ou mecânica sem tocar em Python:** copie `factions/fire.json`, troque ids/nomes/números, liste-a em `includes.factions`, dê uma cor em `assets/theme.json` e referencie-a num cenário. Há um teste que faz exatamente isso (`tests/v2/test_text_only_extension.py`: clona o Fogo como "plasma", cria o cenário `plasma_vs_terra` e roda IA × IA até o fim, de forma determinística).

## Determinismo, replay e snapshots

* Mesma seed + mesmos comandos ⇒ **mesmo hash** (testado em 2 execuções e em processos com `PYTHONHASHSEED` diferentes). Todo o estado é inteiro; RNG SplitMix64 isolado por subsistema, derivado da seed mestra.
* Cada partida grava `…/.mojo/replays/<pacote>-<cenário>-<data>.jsonl` (comandos + hash a cada 50 ticks). `mojo replay <arquivo> --pack packs/poc-mini` reexecuta e acusa o **primeiro tick divergente**. A IA não é gravada: é reexecutada.
* Snapshots atômicos (`.mojo/snapshots/<partida>/latest.json` a cada 100 ticks; botão **Salvar** grava `manual-<tick>.json`). Retomar: `mojo serve <pacote> --scenario <o mesmo> --resume <snapshot.json>` (sem gravação de replay).
* A pasta de dados é `./.mojo` (ou `$MOJO_HOME` / `--home`).

## Segurança (modelo: página web maliciosa / DNS rebinding — não malware local)

Servidor em `127.0.0.1`; **Host e Origin estritos** em HTTP e WebSocket; token aleatório por execução (impresso no terminal; vai na URL); CSP `default-src 'none'` + `script-src 'self'` (sem inline, sem CDN); estáticos por lista branca; áudio só por `/audio/<sha256>.wav`; mensagens ≤ 4096 B e ≤ 120/s por cliente; nenhum upload; o pacote é escolhido na linha de comando, nunca pelo navegador; `/docs` desligado. Pacotes: JSON estrito sem floats/duplicatas, tamanhos/profundidade limitados, `resolve_inside` (sem `..` nem symlink para fora), `mods` rejeitado.

## Narração (opcional)

Eventos do pacote geram texto de narração (`assets/theme.json → narration`) **imediatamente**; se o Ragnarok (127.0.0.1:8765) estiver ligado e `audio.enabled` no manifesto, a síntese roda **fora do tick**, numa thread, e o áudio chega depois (`narration_audio`). Sem Ragnarok: só texto, sem erro. `--audio off` desliga.

## Testes e medições

```bash
.venv/bin/python -m pytest -q tests            # v0.1 (196 + 4 pulados que exigem o Ragnarok real) + V2 (204)
.venv/bin/python -m pytest -q tests/v2         # só V2 (inclui E2E em Chrome headless; pula se não houver Chrome)
.venv/bin/python tools/bench_v2.py             # medições (grava docs/v2/MEDICOES-BOX.json)
```
Resultados e rótulos: `docs/V2-TESTES.md`, `docs/v2/MEDICOES-BOX.md`, screenshots em `docs/v2/screenshots/`.

## Limitações conhecidas

* Não testado no Windows nem no navegador do Gui; fps do Canvas não medido.
* Mods (`mods[]`), lockstep em rede, núcleo nativo e PWA **não** estão implementados (ficam para depois).
* Aventura de texto (v0.1) **não** roda sobre o WebSocket (continua no CLI).
* Pathfinding A* simples (8 direções, teto de expansão 6000, fila `max_paths_per_tick`); unidades podem sobrepor células; sem fog of war.
* `Origin` é forjável por outro processo local; o token na URL protege contra páginas web, não contra malware na sua conta.
* Números e nomes dos pacotes de exemplo **não são canon** nem balanceados.

Decisões adotadas sem entrevista: `docs/V2-DECISOES-ADOTADAS.md`.
