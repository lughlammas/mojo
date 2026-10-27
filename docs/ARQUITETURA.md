> **Atualização 27/10/2026:** a v0.1 foi implementada seguindo este documento; os desvios estão em `docs/IMPLEMENTACAO.md`.

# MOJO — arquitetura mínima (Dream Fabrics) — proposta v0.1

Estado: **proposta de projeto**. Nada do MOJO está implementado; nada aqui foi executado exceto as medições do Ragnarok citadas em
`DIAGNOSTICO-RAGNAROK.md`. Itens marcados **[Gui]** dependem de decisão dele (ver `DECISOES-PENDENTES.md`). **[inferência]** = não medido.
Nomes preservados: Dream Fabrics, MOJO, Ragnarok, `.mjo`.

## 1. Escopo da primeira iteração
Provar o ciclo ponta a ponta: carregar `azrael.mjo` → validar → estado inicial → ação (`look`, `inspect`, `speak`) → resposta validada →
persistência/log → áudio opcional via Ragnarok. **Fora do escopo:** renderização gráfica, contêiner assinado/compactado, geração em tempo real,
modelos embarcados, SFX/ambiência, multijogador, linguagem de script própria.

## 2. Visão geral
```text
azrael.mjo ─▶ [Loader/Validador] ─▶ Mundo (somente leitura)
                                         │
 jogador ─▶ [Cliente textual] ─▶ [Core loop] ◀─▶ [Estado + Regras]  (fonte de verdade, determinístico)
                                    │  ▲
                 proposta estruturada│  │validada/corrigida
                                    ▼  │
                          [Adaptador semântico]  mock │ local │ remoto
                                    │
                    texto final ────┼────▶ [Renderizador textual]
                                    └────▶ [RagnarokAdapter] ──HTTP loopback──▶ Ragnarok (processo separado)
                          [Persistência: saves JSON + log JSONL]   [Config separada do mundo]
```
O **núcleo é determinístico**; o modelo só *interpreta e propõe*. Remover o modelo (ou o Ragnarok) nunca impede o loop textual.

## 3. Stack proposta [Gui]
- **Python ≥ 3.11, biblioteca padrão primeiro** (mesma linguagem do Ragnarok; roda na box e no Windows do Gui; testes com `unittest`/`pytest`).
- Dependências externas mínimas: **`jsonschema`** (MIT) para validar o schema (ou validador próprio pequeno se ele preferir zero dependências); HTTP via `urllib` da stdlib.
- Alternativas (TypeScript/Node, Rust, Godot/C#) ficam para decisão do Gui; ver ADR-003. Trocar de stack depois **não** muda o `.mjo` nem o contrato com o Ragnarok.

## 4. Estrutura de diretórios proposta (repositório MOJO) [Gui: onde fica]
```text
mojo/
  README.md  pyproject.toml  LICENSE(?)
  docs/                      (estes documentos)
  schema/mojo-world-0.1.schema.json
  examples/azrael.mjo        (demonstração, NÃO canônica)  [implementado aqui; antes: worlds/]
  src/mojo/
    cli.py                   (mojo play|validate|state|log)
    world/   loader.py validator.py paths.py migrations.py
    engine/  state.py rules.py actions.py loop.py events.py
    semantic/ base.py mock.py openai_compat.py   (local e remoto usam o mesmo protocolo)
    audio/   base.py null.py ragnarok.py
    store/   saves.py logs.py
    render/  text.py
    config.py
  tests/
  mojo.config.example.json   [implementado na raiz]
```

## 5. Formato `.mjo` v0.1 (JSON UTF-8)
Mantém o exemplo do brief (§3.1) como base. Campos obrigatórios: `format` = `"dream-fabrics/mojo-world"`, `schema_version` (semver `0.1.x`), `id`, `title`,
`world.starting_scene`, `world.scenes[]`, `rules.system`, `rules.player`, `rules.allowed_actions`. Campos opcionais: `semantics`, `audio`, `meta`.

**Lacunas do exemplo do brief que a v0.1 precisa fechar (propostas minhas, a confirmar [Gui]):**
1. `inspect` exige algo a inspecionar: acrescentar `world.scenes[].entities[] = {id, name, description, inspect_text?, speakable?}`.
2. `exits` do exemplo é uma lista vazia e sem formato: definir `{id, to, label, requires?}`; `requires` só aceita **condições declarativas** (ex.: `{"flag":"x"}`), nunca expressões.
3. `audio.voice_profile = "narrator_default"` é um **nome lógico**: quem o resolve para uma voz do Ragnarok é a **configuração do MOJO**, não o arquivo de mundo (ADR-010).
4. `rules.system = "rpg-minimal-v0"` é um **identificador** resolvido num registro interno do MOJO; o arquivo não carrega regras executáveis (ADR-008).
5. `meta`: `{"canon": false, "author": "...", "note": "..."}`; o `azrael.mjo` de demonstração deve trazer `canon:false` e o aviso do brief.
Limites de validação propostos: arquivo ≤ 1 MB, ≤ 500 cenas, ≤ 2.000 entidades, profundidade JSON ≤ 16, strings ≤ 8.000 car., chaves desconhecidas **rejeitadas** no modo estrito (padrão) para evitar dados fantasma.
**Os valores do exemplo (paleta, descrição "fantasia", cena "threshold") são ilustrativos; não são canon de Azrael.**

### 5.1 Recursos externos e caminhos
Um `.mjo` só pode referenciar recursos por **id** declarado em `resources[]` ou por **caminho relativo** dentro da pasta do mundo. Regras do `paths.py` (ADR-008):
rejeitar caminho absoluto, letra de unidade, UNC (`\\`), `..`, byte nulo, nomes reservados do Windows (`CON`, `NUL`, ...), fluxos alternativos (`:`), barras invertidas
misturadas; normalizar, `resolve()` e exigir `is_relative_to(raiz_do_mundo)`; recusar links simbólicos que saiam da raiz; whitelist de extensões; limite de tamanho. Na v0.1 nenhum recurso externo é obrigatório.

## 6. Core loop (refinado do brief §4)
1. **Carregar/validar** (`schema_version` major igual; minor maior → aviso; major diferente → recusa com mensagem e dica de migração).
2. **Estado inicial** = cópia de `rules.player` + cena inicial + `flags={}` + `turn=0` + semente do jogo.
3. **Entrada**: texto do jogador → **analisador determinístico** (`look`, `inspect <alvo>`, `speak <texto>`). Texto livre só passa por `adapter.interpret()` se o Gui habilitar; o resultado é validado contra `allowed_actions`.
4. **Permissão**: ação fora de `allowed_actions`, alvo inexistente ou fora da cena atual → resposta de recusa, **estado intacto** (testável: hash do estado antes = depois).
5. **Contexto mínimo** (cena atual, entidades visíveis, últimos N turnos, estilo de narração) montado pelo MOJO, com texto do mundo como **dado** delimitado.
6. **Proposta** do adaptador: `{narration, proposed_events[], audio_request?}` (formato do brief §4).
7. **Validação**: schema da proposta; cada evento deve ser de um tipo da lista fechada da v0.1 e ter alvos/intervalos válidos; evento inválido é **descartado e registrado**, a narração só passa por limites de tamanho/forma (ver riscos).
8. **Aplicação**: efeitos **determinísticos do motor** primeiro (ex.: `inspect` marca `inspected:<id>`), depois eventos propostos aprovados; transação atômica (aplica tudo ou nada) e `state_hash` novo.
9. **Saída**: renderizador textual imprime; se áudio habilitado, `RagnarokAdapter.synthesize` roda **em paralelo** (thread) para o texto aparecer antes (a fala leva ~1–2 s em servidor, [medido no Ragnarok]; na máquina do Gui [inferência] pode ser maior).
10. **Registro**: uma linha JSONL por turno (§8). Repetir.
Eventos v0.1 (lista fechada, proposta): `set_flag`, `give_item`, `remove_item`, `hp_delta` (limitado a `[−max_hp, +max_hp]`), `move` (só por saída declarada). Para o critério de aceite mínimo
(`look`/`inspect`/`speak`), os únicos efeitos reais são `inspected:<id>`, histórico de diálogo e `turn`; os demais tipos existem para os testes de transição.

## 7. Adaptador semântico
Interface (Python): `SemanticAdapter.propose(ctx) -> Proposal` e `SemanticAdapter.interpret(text, ctx) -> ActionCandidate | None` (opcional), mais `describe() -> {name, version, model_id}` para auditoria.
| Adaptador | O que faz | Observações |
|---|---|---|
| `mock` (padrão em testes) | Respostas determinísticas por modelo de texto a partir da cena/entidade; sem rede | Obrigatório pelo critério de aceite; sem custo; base dos testes de replay |
| `local` | Fala o protocolo **OpenAI-compatível** (`/v1/chat/completions`) com um servidor local já instalado pelo usuário (ex.: llama.cpp `llama-server`, Ollama) em `127.0.0.1` | O MOJO **não embute** o modelo nem o instala. Saída em JSON; usar saída restrita por gramática/JSON mode se o servidor suportar (a verificar) |
| `remote` | Mesmo protocolo, `base_url` e chave por variável de ambiente | **Desligado por padrão**; exige consentimento explícito (envia texto do mundo e do jogador para fora); sem serviço pago sem autorização do Gui |
Política de falha comum: timeout, 1 nova tentativa se o JSON vier inválido, depois **fallback** (resposta-modelo do `mock`/texto fixo da cena) e registro do motivo.

### 7.1 Realismo de LLM local em 7,7 GB de RAM, sem GPU [inferência — nada disto foi medido nesta máquina]
- O Windows, o navegador e o Ragnarok (medido 0,55–0,83 GB) já consomem parte dos 7,7 GB. Sobra algo como 4–5 GB para um modelo [inferência].
- Ordens de grandeza usuais para pesos quantizados em 4 bits: modelos de ~1–3 B de parâmetros ocupam ~1–2,5 GB; de ~7–8 B, ~4,5–5,5 GB (quase todo o orçamento) [inferência de conhecimento geral, não verificada aqui].
- Em CPU de notebook a geração costuma ficar entre alguns e poucas dezenas de tokens/s para modelos pequenos [inferência]; uma narração de ~60 tokens pode levar de alguns segundos a >10 s, e **compete por núcleos com o Ragnarok**, somando latência.
- Modelos pequenos em PT-BR tendem a seguir mal formato JSON estrito e coerência de mundo [inferência]; por isso o motor valida tudo e tem fallback.
- **Plano realista:** iniciar com `mock` + interface do adaptador; decidir local × remoto **depois de um benchmark curto na máquina do Gui** (requer autorização para instalar/rodar algo lá; nada foi instalado). Licenças dos modelos candidatos **não foram verificadas**.

## 8. Persistência, logs e auditoria
- **Saves:** `saves/<world_id>/<slot>.json` com `{save_version, world_id, world_sha256, state, state_hash, turn, rng_seed, created, updated}`; escrita atômica (`.tmp` + rename) e `.bak` do anterior; recusar save cujo `world_sha256` não bate (ou carregar com aviso explícito).
- **Logs:** `logs/<session>.jsonl`, uma linha por turno, só adição: `ts, session, turn, input, action, allowed, adapter{name,version,model_id}, raw_proposal(truncado), decisions[{event,accepted,reason}], state_diff, state_hash_before/after, narration, audio{status,voice,ms,cache_hit}, errors[]`. JSON escapado (sem injeção de log), **sem segredos nem caminhos absolutos**.
- **Replay:** com `mock` (ou com propostas gravadas), reexecutar o log reproduz os mesmos `state_hash` — base dos testes de regressão. Com LLM, a geração varia, mas o estado é auditável turno a turno.
- Local padrão dos dados e retenção: [Gui] (pasta do projeto × pasta do usuário).

## 9. `RagnarokAdapter` (baseado no código real)
- `synthesize(text, voice_profile, options)`: resolve `voice_profile` → `{ragnarok_voice_id, speed}` pela configuração do MOJO; `POST http://127.0.0.1:8765/v1/audio/speech` com `response_format:"wav"`; grava em `cache/audio/<sha256(texto|voz|vel)>.wav`; devolve `AudioRef{path, duration_s, status}`. Timeout próprio (proposta: 20 s), texto ≤ 20.000 car.
- `health_check()`: `GET /api/status` (timeout 1,5 s): `ok` se 200 e engine da voz com `models.<engine> == true`; senão `degraded`/`down` com motivo.
- `play(ref)`: **não existe no Ragnarok**; o cliente textual pode abrir com o player do SO (Windows `os.startfile`, Linux `xdg-open`), **apenas em caminhos que o MOJO mesmo gerou** no cache; opcional e desligável.
- Qualquer falha (conexão recusada, 4xx/5xx, corpo não-JSON/500 em texto puro, wav inválido, timeout) → `AudioRef(status="unavailable")`, log, e **circuit breaker** (ex.: 3 falhas seguidas → pausa 60 s). O loop textual continua.
- Início do servidor: padrão **manual** (usuário abre `ragnarok.bat web --no-browser`); opção de o MOJO lançá-lo como processo filho, com caminho vindo da configuração (nunca do `.mjo`) [Gui].
- Voz padrão sugerida do narrador: decisão do Gui (as aprovadas: `alex-pt`, `sabio-pt`, `onyx-en`, `sabio-en`...).

## 10. Degradação graciosa
| Falha | Comportamento |
|---|---|
| Sem modelo de linguagem / adaptador off | `mock` ou fallback textual por cena; aviso uma vez |
| Modelo devolve JSON inválido / evento proibido | 1 retentativa; depois fallback; evento descartado e logado |
| Ragnarok indisponível / lento / 500 | modo texto; circuit breaker; nunca bloqueia o turno |
| `.mjo` malformado | recusa com erro legível (arquivo, caminho JSON, regra violada) |
| `schema_version` incompatível | recusa com versão encontrada × suportada e dica de migração |
| Save corrompido | tenta `.bak`; senão pergunta se inicia novo |
| Disco cheio / sem permissão de log | continua em memória, avisa; ação não é perdida em silêncio |

## 11. Segurança (resumo; detalhes em ADR-008)
- `.mjo` é **dado**, nunca código: sem `eval`, `exec`, `pickle`, YAML com tags, plugins, `import` dinâmico, nem comandos de shell vindos do arquivo.
- Travessia de caminho: regras da §5.1; testes com `..`, caminho absoluto, UNC, links simbólicos, nomes reservados, Unicode normalizado.
- **Injeção via texto do mundo/jogador (prompt injection):** o prompt separa instruções do MOJO de conteúdo do mundo (delimitado e marcado como dados); a saída do modelo só é aceita pelo schema de proposta; o modelo **não** tem ferramentas, rede nem acesso a arquivos. Risco residual: a narração livre pode inventar fatos (item que não existe) — mitigação parcial: limites de tamanho, filtros de formato e o estado ser sempre a verdade.
- Limites de tamanho/quantidade; erros sem vazar caminhos absolutos; logs sem segredos; adaptador remoto desligado por padrão e com consentimento.
- Ragnarok só em loopback; resposta de áudio com limite de bytes e checagem de cabeçalho WAV antes de tocar.
- **Extensão `.mjo` não dá exclusividade jurídica nem segurança** (brief §6); assinatura/IP ficam para depois.

## 12. Testes previstos (critérios do brief §7–8)
Arquivo válido; inválido (mensagem legível); versão incompatível; ação proibida deixa o `state_hash` igual; transição de estado; falha de áudio (Ragnarok fora do ar e 500 texto puro simulados por um servidor falso local);
travessia de caminho; limites de tamanho; replay determinístico com `mock`; migração minor; save corrompido. Execução documentada por um único comando.

## 13. Passos seguintes (só depois do aval do Gui)
3) schema + loader/validador + `azrael.mjo` demo + testes; 4) core loop textual + `mock` + saves/logs; 5) `RagnarokAdapter` (contra o Ragnarok real na box; no Windows só com a instalação do Gui concluída) + README. Estimativa [inferência]: passos 3–4 em poucos dias de trabalho; 5 depende da validação do Ragnarok no Windows.
