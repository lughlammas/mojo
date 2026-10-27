# MOJO — ADRs curtos (Dream Fabrics) — 27/10/2026

Status possíveis: **Proposto** (minha recomendação, ainda sem aval), **Aguarda Gui** (precisa de decisão dele). Atualização: a v0.1 foi implementada com os padrões propostos (ver `docs/IMPLEMENTACAO.md`); o status "Aguarda Gui" permanece nos itens que ele ainda não confirmou.

---
## ADR-001 — Núcleo determinístico; o modelo propõe, o motor decide
**Status:** Proposto (é o princípio do brief §1).
**Contexto:** LLMs variam e alucinam; mundos precisam ser reproduzíveis, auditáveis e testáveis.
**Decisão:** Estado, regras, permissões e transições vivem no núcleo. O modelo devolve só uma *proposta estruturada*; o núcleo a valida, corrige ou descarta e aplica de forma atômica.
**Consequências:** + testes e replay sem modelo; + segurança. − narração livre ainda pode inventar fatos (o estado nunca é afetado); − mais código de validação.

## ADR-002 — `.mjo` v0.1 = JSON UTF-8 com schema versionado
**Status:** Proposto (brief §3.1).
**Decisão:** Arquivo de texto JSON, `format="dream-fabrics/mojo-world"`, `schema_version` semver, validado por JSON Schema (2020-12) em `schema/mojo-world-0.1.schema.json`. Sem código embutido; chaves desconhecidas rejeitadas no modo estrito. Campos adicionais propostos: `entities[]`, `exits` estruturados, `meta.canon`, `resources[]` (ver ARQUITETURA §5).
**Consequências:** + legível/diffável/testável; futuro contêiner compactado/assinado envolve o mesmo JSON sem mudar a semântica. − sem comentários nativos; arquivos grandes são verbosos.

## ADR-003 — Stack do MOJO: Python ≥ 3.11, stdlib primeiro
**Status:** **Aguarda Gui.** Recomendação: Python.
**Contexto:** o Ragnarok é Python; a máquina do Gui é Windows 11 com 7,7 GB; precisamos testar na box (Linux) e no Windows.
**Decisão proposta:** Python, `jsonschema` como única dependência obrigatória (opcional: validador próprio), HTTP por `urllib`.
**Alternativas:** TypeScript/Node (UI web mais fácil, outro ecossistema para manter), Rust (binário único, mais lento para prototipar), Godot/C# (renderização futura, pesado para o protótipo textual).
**Consequências:** + um só ambiente de desenvolvimento e testes; − distribuição para terceiros exigirá empacotamento; trocar de stack depois não altera `.mjo` nem o contrato HTTP com o Ragnarok.

## ADR-004 — Adaptador semântico: interface + `mock`, `local`, `remoto`
**Status:** Proposto; escolha do modelo **Aguarda Gui**.
**Decisão:** Interface `SemanticAdapter` (`propose`, `interpret` opcional, `describe`). `mock` determinístico (padrão em testes, sem rede). `local` e `remoto` usam o **mesmo protocolo OpenAI-compatível**; o local aponta para um servidor já instalado em 127.0.0.1; o remoto fica **desligado por padrão**, com chave por variável de ambiente e consentimento explícito. O MOJO não embute nem baixa modelos.
**Consequências:** + testável offline e sem custo; + trocar de modelo é configuração. − qualidade/latência do modelo local em CPU com 7,7 GB é **desconhecida** (inferência no ARQUITETURA §7.1); decidir após benchmark autorizado.

## ADR-005 — Ragnarok como serviço HTTP local separado; nunca importado
**Status:** Proposto.
**Contexto (diagnóstico real):** o Ragnarok expõe `POST /v1/audio/speech` (síncrono, sem streaming, um pedido por vez) e `GET /api/status`; a CLI recarrega o modelo a cada chamada (~3 s); não há `/health`, tocador, perfis nem SFX.
**Decisão:** `RagnarokAdapter` fala HTTP em `127.0.0.1:8765` (configurável), pede `wav`, guarda em cache por hash e devolve caminho. Timeout próprio, circuit breaker e queda para texto. A CLI do Ragnarok fica só como reserva. O Ragnarok não é modificado nesta fase.
**Consequências:** + módulos independentes, sem acoplar ambientes Python. − precisa do servidor ligado; primeira fala após um período parado paga a carga do modelo (~3 s medido na box); `play()` é responsabilidade do MOJO.

## ADR-006 — Persistência: saves JSON atômicos + log JSONL só de adição
**Status:** Proposto; local dos dados **Aguarda Gui**.
**Decisão:** `saves/<world_id>/<slot>.json` (com `world_sha256`, `state_hash`, semente) e `logs/<sessão>.jsonl` (um registro por turno: entrada, proposta bruta truncada, decisões de validação, diff de estado, narração, status do áudio, versão/modelo do adaptador). Escrita atômica + `.bak`. Sem segredos nem caminhos absolutos nos logs.
**Consequências:** + auditoria e replay. − crescimento dos logs (rotação/retensão a definir); dados de jogo ficam em texto claro.

## ADR-007 — Degradação graciosa em camadas
**Status:** Proposto (brief §6).
**Decisão:** sem modelo → `mock`/fallback textual; JSON inválido → 1 retentativa e fallback; sem Ragnarok → modo texto com circuit breaker; `.mjo` inválido/versão incompatível → recusa com erro legível; save corrompido → `.bak`.
**Consequências:** o loop nunca trava por dependência opcional; custo: caminhos de fallback precisam de testes próprios (falha de áudio é critério de aceite).

## ADR-008 — Segurança: `.mjo` é dado; sandbox de caminhos; sem execução arbitrária
**Status:** Proposto (brief §6).
**Decisão:** proibido `eval/exec/pickle/importação dinâmica/YAML com tags/plugins/shell` a partir do arquivo. `rules.system` e tipos de evento são **identificadores** resolvidos em registros internos, nunca código. Caminhos: só relativos à raiz do mundo; rejeitar absolutos, `..`, UNC, letra de unidade, `:`/ADS, nomes reservados do Windows, byte nulo e symlinks que escapem; normalizar + `resolve()` + `is_relative_to`. Limites de tamanho/quantidade/profundidade. Texto do mundo e do jogador entra no prompt como dado delimitado; a saída do modelo só passa pelo schema de proposta; o modelo não tem ferramentas. Respostas HTTP do Ragnarok são tratadas como não confiáveis (limite de bytes, checagem de cabeçalho WAV).
**Consequências:** + superfície de ataque pequena. − não elimina alucinação narrativa nem prompt injection que só altere o texto da narração; assinatura/IP e proteção comercial ficam para depois (a extensão `.mjo` não dá exclusividade jurídica).

## ADR-009 — Versionamento e migração explícitos
**Status:** Proposto.
**Decisão:** `schema_version` semver. Major diferente → recusa com mensagem; minor maior que o suportado → aviso e modo estrito de campos; migrações como funções puras e testadas (`migrations.py`), nunca implícitas. Saves têm `save_version` própria.
**Consequências:** + previsibilidade. − cada mudança de schema exige migração e teste.

## ADR-010 — Configuração separada do mundo
**Status:** Proposto (brief §6).
**Decisão:** `mojo.config.json` (fora do `.mjo`) define adaptador/modelo, URL e timeout do Ragnarok, tabela `voice_profile → {voz do Ragnarok, velocidade}`, pastas de saves/logs/cache e flags de consentimento. O `.mjo` só cita nomes lógicos (`narrator_default`). Sem segredos no repositório; chaves por variável de ambiente.
**Consequências:** + portabilidade e mundos sem caminhos absolutos. − precisa de configuração mínima antes de ouvir áudio.

## ADR-011 — Eventos de estado: lista fechada na v0.1
**Status:** Proposto.
**Decisão:** `set_flag`, `give_item`, `remove_item`, `hp_delta` (com limites) e `move` (só por saída declarada). `look`, `inspect`, `speak` têm efeitos determinísticos mínimos do próprio motor (`inspected:<id>`, histórico de diálogo, contador de turno). Qualquer outro tipo é descartado e logado.
**Consequências:** + validação simples. − expressividade baixa até a v0.2; o conteúdo do sistema `rpg-minimal-v0` precisa ser definido (hoje o brief só cita o nome).

## ADR-012 — Conteúdo de exemplo não é canon
**Status:** Proposto (brief §3.1, nota).
**Decisão:** o `azrael.mjo` de demonstração leva `meta.canon=false` e aviso explícito; cores, cenário e regras do brief são tratados como valores ilustrativos. Nenhum nome, lore, significado ou direção artística de Azrael é inventado; o canon real só entra com material oficial fornecido pelo Gui.
**Consequências:** + evita fixar criação sem fonte. − o mundo demo é deliberadamente genérico.
