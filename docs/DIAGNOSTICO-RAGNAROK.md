# Diagnóstico do Ragnarok real (para o MOJO / Dream Fabrics)

Data: 27/10/2026 (horário de Brasília). Escopo: **só leitura**; o Ragnarok não foi alterado.
Fonte: código em `/workspace/ragnarok/app/` (versão 0.1.0, zip `ragnarok-0.1.zip`, SHA-256
`64409dbf968cdcd0a1c39ff0772b7fabc694dc90921922a72130d6c27de0e36f`) e medições feitas hoje na **box** (Linux).
Convenções: **[medido]** = número obtido na box; **[lido]** = visto no código; **[inferência]** = raciocínio, não medido;
**[não validado]** = nunca executado no ambiente citado.

## 1. O que o Ragnarok é (e não é)
- Módulo de **síntese de voz (TTS) local, só CPU**, uso pessoal. Escrito do zero em **Python 3.11–3.13** [lido]
  (~1.500 linhas de Python + 1 página HTML; 9 testes unitários, só de processamento de texto).
- Engines: Kokoro (ONNX, sempre fp32) e Supertonic-3 (ONNX). Um engine carregado por vez; um trabalho por vez [lido].
- **Não faz** efeitos sonoros, trilha, ambiência nem mixagem multi-faixa. O brief fala em "síntese de voz e sonorização": hoje
  o Ragnarok cobre só a **voz** [lido]. Sonorização seria trabalho novo.
- **Sem clonagem**, sem SSML, sem controle de emoção; pausas só por pontuação [lido].

## 2. Interfaces reais
| Interface | Detalhe verificado |
|---|---|
| CLI `python -m ragnarok` (`ragnarok.bat` / `run.sh`) | `say`, `book`, `web`, `voices`, `models`, `doctor`. Códigos de saída: 0 ok, 2 erro de uso/valor, 1 erro de execução, 130 Ctrl+C [lido]. Cada `say` sobe o processo e carrega o modelo: ~3 s só de carga [medido, 1ª chamada] |
| Servidor web `127.0.0.1:8765` (`web --host --port --no-browser`) | FastAPI + uvicorn. Escuta só em loopback por padrão; rejeita Host e Origin não locais; **sem chave de API** (qualquer processo local pode chamar) [lido, testado] |
| `POST /v1/audio/speech` | Corpo JSON `{model(ignorado), input, voice, response_format, speed}`. Formatos `mp3 wav opus aac flac pcm`. **Síncrono**: devolve o arquivo inteiro só quando terminou; sem streaming. Limite 20.000 caracteres [lido]. `voice` aceita id do catálogo, prefixo único (`alex`) ou nomes da OpenAI (`alloy`, `nova`...→ voz padrão `michael-en`) [lido, testado] |
| `GET /v1/audio/voices`, `GET /v1/models`, `GET /api/voices` | Lista de vozes (id, rótulo, engine, idioma, velocidade base) [lido, testado] |
| `GET /api/status` | `{version, loaded_engine, ram_peak_mb, ram_now_mb, models:{kokoro,supertonic}, queue}`. **É o único "health check" existente**; não há `/health` [lido, testado] |
| `/api/jobs*` (fila) | `POST /api/jobs`, `POST /api/jobs/upload`, `GET/DELETE /api/jobs/{id}`, `GET .../audio`, `POST .../retry`. Para textos longos/livros; histórico em `data/history.json` [lido, testado] |

**Nada no Ragnarok é um "tocador"**: ele gera arquivo/bytes. `play()` do `RagnarokAdapter` terá de ser feito pelo cliente do MOJO.

## 3. Vozes e formatos
- Catálogo em `config/voices.json` (7 vozes aprovadas pelo Gui): `michael-en`, `onyx-en`, `sabio-en`, `alex-pt`, `sabio-pt`,
  `dora-pt`, `heart-en`. Não existe conceito de "voice_profile" além do **id da voz** + multiplicador de velocidade [lido].
  O `narrator_default` do exemplo do brief **não existe** no Ragnarok: o MOJO precisará de uma tabela própria `perfil → voz`.
- Taxa de amostragem: Kokoro 24 kHz, Supertonic 44,1 kHz, mono, PCM16 [lido, conferido por tamanhos de wav]. O formato `pcm` da API
  vem **sem cabeçalho e sem informar a taxa**; para o MOJO use `wav` (autodescritivo).
- Supertonic **não é determinístico** (mesma frase → mesmo tamanho, amostras diferentes); Kokoro é idêntico bit a bit [medido].
  Cache de áudio por hash (texto+voz+velocidade) é seguro e recomendado no MOJO, mas não dá "o mesmo áudio" ao regenerar com Supertonic.

## 4. Latência e RTF medidos na box (CPU Xeon 8 vCPU; NÃO é a máquina do Gui)
Servidor já ligado, `curl` local, frases em PT-BR, n pequeno (1–3 repetições; variação típica ~20%):

| Situação | Texto | Áudio gerado | Latência até o arquivo |
|---|---|---|---|
| 1ª chamada após iniciar o servidor (carrega Kokoro) | 32 car. | ~3,0 s | **2,99 s** |
| Kokoro `alex-pt`, quente | 32 car. | ~3,0 s | 0,34 – 0,55 s |
| Kokoro `alex-pt`, quente | 126 car. | 8,44 s | 1,14 – 1,20 s |
| Supertonic `sabio-pt`, quente | 32 car. | ~4,3 s | 0,80 s |
| Supertonic `sabio-pt`, quente | 126 car. | ~12,4 s | 1,65 s |
| Troca de engine (descarrega um, carrega outro) | 32 car. | – | Kokoro→Supertonic **2,24 s**; Supertonic→Kokoro **1,06 s** |
| Mesma frase de 126 car. em `mp3` / `opus` (inclui ffmpeg) | 126 car. | ~8,4 s | 1,44 s / 2,27 s |
| 3 pedidos simultâneos (126 car.) | – | – | 1,1 s, 2,3 s, 4,6 s (**serializados**: um por vez) |
- RTF em livros (544–563 palavras, 3 capítulos): **0,12 – 0,16** (tempo total ÷ áudio, inclui carga e codificação) [medido].
- RAM: processo CLI 0,55–0,70 GB; servidor chegou a **0,80–0,83 GB** após alternar engines [medido]. Alternar engines não acumula [medido].
- **Primeiro áudio = latência total** (sem streaming): uma narração de ~125 caracteres leva ~1,2–1,7 s depois de quente, em CPU de servidor.
- **[inferência] Na i5-12450H com 7,7 GB:** a ordem de grandeza deve ser a mesma, mas **não foi medida**; ainda não há RTF do Ragnarok naquela máquina.
  Não prometa "tempo real" no MOJO antes de medir lá.

## 5. Tratamento de erros (como o Ragnarok realmente falha)
| Situação | Resposta real | Observação para o adaptador |
|---|---|---|
| Voz inválida / `response_format` inválido / `input` vazio ou sem texto legível | 400 JSON `{"detail": "..."}` [testado] | tratar como erro de uso |
| Corpo sem `input` | **422** (formato padrão do FastAPI, `detail` é uma lista) [testado] | `detail` pode ser string ou lista |
| `input` > 20.000 car. | 413 [lido] | |
| **Modelos ausentes** (`RAGNAROK_MODELS` vazio) | **500 com corpo de texto puro "Internal Server Error"**; traceback só no log do servidor [testado] | **Lacuna**: deveria ser 503 JSON. O adaptador deve tratar qualquer não-200 / corpo não JSON como "áudio indisponível" |
| Engine falha no meio | 500 genérico [lido]; `/api/jobs` marca `error` com mensagem [lido] | |
| Bloco com áudio anômalo (duração suspeita) | regenera 1 vez e conta "anomalia"; não falha o pedido [lido, `MIN_CPS`] | |
| Trabalho longo ocupando o motor | `/v1` **espera a vez** sem timeout (19,6 s num teste) [medido] | o MOJO precisa de **timeout próprio** (ex.: 10–30 s) |
| Processo do servidor caiu | conexão recusada | o MOJO precisa de circuit breaker; o Ragnarok não reinicia sozinho |
| Servidor fechado durante um trabalho da fila | no próximo start vira `interrupted`; `retry` retoma [testado] | só vale para `/api/jobs`, não para `/v1` |
Sem autenticação, sem limite de taxa, sem tamanho máximo de resposta. Sem endpoint de saúde dedicado.

## 6. O que o `RagnarokAdapter` pode reaproveitar (e como)
Mapa das três operações conceituais do brief:
| Operação do brief | Implementação real possível | Situação |
|---|---|---|
| `synthesize(text, voice_profile, options) -> audio_reference` | `POST /v1/audio/speech` com `response_format="wav"`, gravar em cache do MOJO e devolver o **caminho** como referência | Viável; testado com `curl`, cliente `openai` e navegador. Não testado a partir do MOJO (não existe ainda) |
| `play(audio_reference)` | **Não existe no Ragnarok.** Cabe ao cliente do MOJO (player do SO ou navegador) | Projeto novo |
| `health_check() -> status` | `GET /api/status` com timeout curto; considerar saudável se HTTP 200 e `models.<engine>` verdadeiro | Viável (não é um `/health` de verdade) |
Alternativas avaliadas:
1. **HTTP para o servidor local (recomendada)**: processos independentes, fronteira clara, sem acoplar ambientes Python. Custo: precisa de servidor ligado; o MOJO pode (opcional) iniciá-lo como processo filho com `ragnarok.bat web --no-browser --port N`.
2. **CLI por chamada** (`ragnarok say ... --out x.wav`): simples e sem servidor, mas **~3 s de carga a cada fala** [medido] → só serve como reserva.
3. **Importar `ragnarok.synth` em Python**: funciona, mas acopla o venv do MOJO ao do Ragnarok (numpy/onnxruntime/kokoro) e quebra a ideia de módulo independente. Não recomendo.
Reaproveitável: `voices.json` (ids/rótulos), `GET /api/voices` para validar perfis em tempo de execução, o cache de áudio por hash (a ser feito no MOJO), a ideia de **retomada/trava por pasta** e o `doctor` como diagnóstico.
Não reaproveitável como está: o tocador, a mixagem/SFX, streaming, perfis de narrador, resposta de erro uniforme.

## 7. Segurança relevante para o MOJO
- A API **não recebe caminhos** (só texto e upload `.md/.txt` ≤ 3 MB): bom, o MOJO nunca passa um caminho do `.mjo` ao Ragnarok [lido].
- Qualquer processo local pode chamar o servidor (sem chave): aceitável para uso pessoal; se o MOJO suportar adaptadores remotos, não exponha o Ragnarok fora de 127.0.0.1.
- A CLI `--out` escreve onde mandarem: o MOJO nunca deve montar esse caminho a partir de conteúdo do `.mjo`.
- Binários de terceiros: ffmpeg do `imageio-ffmpeg` (GPL no build Linux conferido), espeak-ng/phonemizer (GPL-3.0) embutidos via dependências; Supertonic com pesos OpenRAIL-M. Uso pessoal ok; redistribuição exige revisão (ver README do Ragnarok).

## 8. O que funciona só na box / o que não foi validado no Windows
**Validado apenas na box (Linux, Python 3.13.5):** instalação limpa a partir do zip (16,8 s com cache do pip), CLI `say`/`book`, retomada
(`kill -9` e Ctrl+C), interface no Chrome headless, `/v1/audio/speech` nos 6 formatos, cliente `openai`, trava entre processos, medidas das seções 4–5.
**Não validado no Windows 11 (máquina do Gui, i5-12450H, 7,7 GB):**
- `install.ps1`/`install.bat`/`ragnarok.bat` (só sintaxe no PowerShell 7 e funções auxiliares), PowerShell 5.1;
- travas `msvcrt`, medição de RAM via `psapi`, DLL do espeak-ng, binário ffmpeg do Windows, antivírus, caminhos com espaços/acentos;
- **qualquer** RTF, latência ou RAM na máquina do Gui; Python 3.11/3.12.
**Estado informado agora:** a instalação no Windows do Gui está em andamento e o download do Supertonic falhou uma vez por erro de rede.
Eu **não mexi nisso**. Observação só de leitura do código: `ensure_supertonic()` chama o download do Hugging Face **uma única vez, sem as 3 tentativas
que o Kokoro tem** [lido], o que é consistente com a falha ter ficado visível; registro como lacuna do Ragnarok a tratar **só com autorização**.
O MOJO deve tratar "Ragnarok parcialmente instalado" (um engine ok, outro não) como estado normal: `GET /api/status` mostra `models` por engine.

## 9. Conclusão do diagnóstico
O Ragnarok serve como **serviço de voz por HTTP local** para o MOJO sem nenhuma alteração: um pedido `wav` por fala, com timeout próprio, cache por hash e
queda para modo texto. Limitações a assumir no desenho: sem streaming (~1–2 s de espera por fala em CPU de servidor), um pedido por vez, sem SFX, sem perfis de narrador,
erro 500 em texto puro quando faltam modelos, e **nenhum número medido na máquina do Gui**.
