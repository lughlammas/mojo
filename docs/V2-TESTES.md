# MOJO V2 — testes (o que roda de verdade)

Rodados na **box** (Linux, Python 3.13.5, Chrome headless). **Não** foram rodados no Windows do Gui.

## Resumo (27/10/2026, America/Sao_Paulo)

| conjunto | resultado |
|---|---|
| v0.1 **antes** (checkout limpo do `HEAD`, `git archive`) | **196 passaram, 4 pulados** (os 4 exigem o Ragnarok real em 127.0.0.1:8765) |
| v0.1 **depois** das mudanças do V2 (`pytest tests --ignore=tests/v2`) | **196 passaram, 4 pulados** — idêntico |
| V2 (`tests/v2`) | **204 passaram** |
| tudo junto (`pytest tests`) | **400 passaram, 4 pulados** |

## Por fase / tema (arquivo → o que prova)

| arquivo | testes | cobre |
|---|---|---|
| `test_f1_pack_schema.py` | 53 | schemas (lint), campo desconhecido, floats/duplicatas/UTF-8/tamanho, caminhos inseguros e symlink, include ausente, tipo×pasta, `mods`, mundo v0.1 e versão futura, referências cruzadas, limites (`max_entities`, nós, bounds), mini-linguagem (rejeições, limites, semântica), lista branca de efeitos, regras duplicadas |
| `test_f1_migration.py` | 5 | migração 0.1→0.2 valida no schema 0.2, preserva conteúdo, não muta a entrada, *downgrade* idêntico e válido no motor v0.1, CLI `validate`/`pack-validate` |
| `test_f2_determinism.py` | 11 | vetores do RNG, isolamento de streams, **mesma seed → mesmo hash em 2 execuções** (4 cenários), seed diferente → resultado diferente, ordem dos sistemas é contrato, ordem de chegada dos comandos irrelevante, **hash igual em 2 processos com `PYTHONHASHSEED` diferentes**, estado só com inteiros |
| `test_f2_sim.py` | 20 | estado inicial, movimento/velocidade, destino em rocha, sem caminho, coleta e esgotamento do nó, treino/fila/suprimento/cancelamento, construção, validação de comandos (dono, args, limites), combate/recarga/status, auto-aquisição, mortes e eventos, estruturas bloqueiam/liberam células, `max_entities`, `max_paths_per_tick`, fim de jogo congela, IA scriptada (constrói/treina/ataca, nunca recurso negativo, não vai ao log), 4 facções com IA |
| `test_f3_rules.py` | 22 | **tabela dourada de ondas (seed 777: ticks 300/516/753/997/1286/1511, centros e poderes) = referência independente**; outras 4 seeds; efeitos por facção (Fogo cura+inflamado, Terra mínimo 1, Água erode, Ar empurra, imune), estabilizador, regeneração, habilidades `mend`/`gust`, **orçamento de efeitos** (determinístico), `schedule`, `spawn` com limite, clamp de variáveis, eliminação/vitória/derrota |
| `test_f4_replay_snapshot.py` | 12 | snapshot→restaurar→continuar com hash idêntico, snapshot de outro pacote/cenário recusado, escrita atômica (falha no meio não deixa lixo nem corrompe), replay verifica, **adulteração detectada no checkpoint certo**, comando removido detectado, `pack_sha256` diferente recusado, lixo recusado, CLI `simulate`/`replay` |
| `test_security.py` | 51 | Host/Origin (matriz com 18+16 casos, `--lan`), token, forja de Host em HTTP, cabeçalhos/CSP, lista branca de estáticos e travessia (`..`, `%2e`, NUL, regex do áudio), `/api/stats` exige token, `/docs` desligado, **handshake WebSocket com Origin/Host/token falsos rejeitado** (socket cru) |
| `test_f5_server.py` | 13 | servidor real (uvicorn) + cliente WebSocket: welcome/snap, ping/pong, JSON inválido, grande demais, limite de taxa, ack/erros e posse de unidades, pausa/velocidade, 2 humanos + espectador, auto-pausa/retomada, servidor ocioso não avança, **partida completa do poc-mini até a vitória** (espelho reconstruído só de deltas = estado do motor; replay verificado), **partida até a derrota** (IA vence humano ocioso), salvar/retomar, snapshot periódico, latência |
| `test_f6_narration.py` | 8 | texto sem áudio, áudio assíncrono + rota `/audio`, **síntese lenta (2 s/frase) não atrasa o tick**, falha/inutilizável → só texto, fila limitada, renderizador seguro |
| `test_f6_browser_e2e.py` | 3 | **Chrome headless**: conecta, seleciona estrutura, treina pela UI, move com botão direito, constrói (modo + fantasma), pausa/retoma, acelera até o banner final, **screenshots**, **todas as requisições são same-origin 127.0.0.1 e zero erros/avisos de console**; 2 abas coop; token errado não conecta |
| `test_cli_serve.py` | 4 | `mojo serve` como processo (URL com token, HTTP+WS, SIGINT limpo), pacote inválido não abre porta, porta ocupada → código 2, `validate` do v0.1 e de pasta |
| `test_text_only_extension.py` | 2 | nova facção + cenário + regra **só editando JSON** |

## Screenshots (`docs/v2/screenshots/`)

* `01-partida-pausada.png`, `02-modo-construcao.png` (fantasma de construção), `03-fim-de-jogo.png` (banner DERROTA + registro), `04-coop-aba-p2.png` (aba do 2º jogador).

## Reproduzir

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q tests                 # ~50 s (inclui o E2E, ~20 s)
git archive HEAD | tar -x -C /tmp/before && (cd /tmp/before && /caminho/.venv/bin/python -m pytest -q)   # v0.1 "antes"
```
Variável `MOJO_CHROME=/caminho/chrome` escolhe o navegador; sem Chrome o E2E é pulado.

## O que **não** é coberto

Windows (`.bat` e `pip` offline/online), fps/uso de CPU do navegador, partidas longas de verdade (>10 min), balanceamento, Ragnarok real com voz (só adaptador falso), rede local (`--lan`) além da política de Host/Origin.
