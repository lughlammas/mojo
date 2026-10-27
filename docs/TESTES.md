# MOJO v0.1 — resultados de testes (medidos na box, 27/10/2026)

**Ambiente:** box Linux (Xeon 8 vCPU, 16 GB — **não é a máquina do Gui**), Python 3.13.5 e 3.11.17, `jsonschema` 4.26, pytest 9.1. Ragnarok 0.1.0 real (Kokoro fp32 pm_alex = voz `alex-pt`), iniciado com `RAGNAROK_DATA=/tmp/ragnarok-data` (o código/arquivos em `/workspace/ragnarok/app` não foram alterados). **Windows não testado.**

## pytest
| Execução | Resultado |
|---|---|
| `pytest -q tests` (Python 3.13.5, Ragnarok real no ar) | **200 passed** em ~6–8 s |
| `pytest -q tests -m "not ragnarok"` (Python 3.11.17) | **196 passed**, 4 deselected em ~3 s |

Por arquivo: `test_world_loader` 37 · `test_paths` 35 · `test_engine` 52 · `test_store` 26 · `test_audio` 21 · `test_adapters_config` 16 · `test_cli` 9 · `test_ragnarok_real` 4.

Cobertura pedida no brief (§7.9):
- **Arquivo válido:** `azrael.mjo` e fixture rica (`test_valid_*`).
- **Inválido:** 16 mutações parametrizadas, JSON malformado (linha/coluna), chaves duplicadas, NaN, UTF-8 inválido, arquivo > 1 MB, aninhamento profundo, vários erros reportados juntos, CLI sem `Traceback`.
- **Versão incompatível:** `1.0.0`, `0.2.0` (mais novo), `0.0.9` (sem migração), `banana`/`0.1` (formato); patch `0.1.7` aceito; migração injetada aplicada; migração que não avança é rejeitada.
- **Ação proibida:** `go`/`ir` no `azrael.mjo` → estado e hash idênticos, adaptador nunca chamado, log `refused`. Também entradas inválidas/desconhecidas/ vazias não mudam o estado.
- **Transição de estado:** `go` com/sem `requires`, `inspect` gravando flag, eventos do modelo (aceitos e 18 casos ruins rejeitados individualmente), clamp de HP, replay determinístico (mesmos hashes a partir do log), saves atômicos/backup/adulteração.
- **Falha de áudio:** Ragnarok falso com HTTP 500 texto puro, 400 JSON, WAV inválido, não-WAV, timeout próprio, desligado (porta fechada), disjuntor abre/fecha, cache serve sem Ragnarok, exceção do adaptador contida, texto não espera o áudio.
- **Segurança:** 35 casos de caminho (`..`, absolutos, UNC, drive, `CON`, `:`, Unicode, symlink), slots, config com segredo, loopback, injeção de prompt tratada como dado, mock sem rede (socket bloqueado).

## O que é simulado nos testes
- `FakeRagnarok` e `FakeLLM` (servidores HTTP locais em `conftest.py`/`test_adapters_config.py`) imitam o **contrato observado** do Ragnarok e do protocolo OpenAI. O adaptador `local`/`remote` **nunca falou com um modelo real**.
- Os 4 testes de `test_ragnarok_real.py` usam o Ragnarok real.

## Sessão completa com o mock + Ragnarok REAL (via CLI, cache vazio, Ragnarok recém-reiniciado)
Roteiro: `look, inspect marco, inspect cidadela, speak ..., go norte, look, state, quit`.

| Turno | Ação | Resultado de áudio | Latência medida | Duração do áudio |
|---|---|---|---|---|
| 0 | cena inicial (99 car.) | ok (síntese; inclui carga do modelo) | **2380 ms** | 7,71 s |
| 1 | `look` (mesmo texto) | cache | 0 ms | 7,71 s |
| 2 | `inspect marco` (81 car.) | ok | 1196 ms | 5,75 s |
| 3 | `inspect cidadela` (82 car.) | ok | 790 ms | 5,64 s |
| 4 | `speak ...` (98 car.) | ok | 919 ms | 6,54 s |
| 5 | `go norte` | recusada (sem áudio, estado intacto) | — | — |

- Latência de síntese **a quente**: 0,6–1,6 s para 80–100 caracteres (RTF ≈ 0,14–0,21); **a frio** ~2,4 s (primeira chamada). Na CPU do Gui o número será outro e **não foi medido**. Não é "tempo real": a narração chega ~1 s depois do texto.
- Texto: o turno devolve o texto em **0,2–2,4 ms** (em processo), independente do áudio (áudio roda em thread).
- RAM do servidor Ragnarok (`/api/status`) após as sessões: 606–664 MB de pico.
- Contrato real confirmado: voz inexistente → `HTTP 400` JSON → MOJO degrada sem exceção (`test_real_error_contract_unknown_voice`).

## Sessão com o Ragnarok DESLIGADO e queda no meio da sessão
1. Porta fechada desde o início (`test_play_full_session_text_mode`, CLI): sessão completa em texto, aviso `[áudio indisponível]` **uma vez**, log com 5 turnos, `state` correto.
2. Queda no meio da sessão (Ragnarok real morto com `pkill` após 2 turnos; `failures_to_open=2`, `open_seconds=3`):
```
look / inspect marco               texto 1,8 / 0,8 ms | áudio ok 1085 / 619 ms
-- Ragnarok MORTO --
speak ninguém responde             texto 1,4 ms | áudio unavailable (Connection refused)
inspect cidadela                   texto 0,8 ms | áudio unavailable (Connection refused)
look                               texto 0,4 ms | áudio cache (0 ms)  <- texto já sintetizado antes
speak outra fala                   texto 0,4 ms | áudio unavailable (disjuntor aberto, sem chamada de rede)
go norte                           recusada; estado: turno 6 inalterado
-- Ragnarok REINICIADO --
speak voltou?                      áudio ok 1636 ms (disjuntor fechou após os 3 s)
speak voltou mesmo?                áudio ok 691 ms
```
O loop textual nunca parou.

## Critérios de aceite (brief §8)
| Critério | Resultado |
|---|---|
| Comando abre `azrael.mjo` e mostra a cena inicial | `mojo play examples/azrael.mjo` — verificado (CLI e teste) |
| `look`, `inspect`, `speak` coerentes | verificado (mock; coerência = texto do próprio `.mjo`) |
| Ação não permitida não muda o estado | verificado (hash antes = depois) |
| `.mjo` malformado → erro legível | verificado (linha/coluna; sem Traceback) |
| Registra transições e permite examinar estado | `state`, `log`, JSONL com hashes antes/depois |
| Mock sem serviços pagos | verificado (teste bloqueia sockets) |
| Sem Ragnarok não interrompe o loop | verificado (porta fechada, queda no meio) |
| Testes documentados e repetíveis | README + `pytest` |

## Não testado
Windows (incl. `mojo.bat`, `os.startfile`, `os.replace` com antivírus/arquivo aberto), reprodução local de áudio (`--play-audio`; a box não tem player), qualquer modelo de linguagem real, Python 3.12, execução prolongada/concorrência de várias sessões no mesmo save, carga (milhares de turnos), `.mjo` grandes reais, Supertonic via MOJO.
