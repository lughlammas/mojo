# MOJO — motor semântico de mundos interativos (Dream Fabrics)

Protótipo **v0.1** do **MOJO**: carrega um mundo `.mjo` (JSON UTF-8), valida, executa um loop textual (`look`, `inspect`, `speak`) com regras determinísticas, registra tudo em log JSONL e, se o **Ragnarok** estiver no ar, pede a narração em áudio.

> **Não está pronto para produção.** É um protótipo para provar o ciclo de ponta a ponta. Veja "Limitações" e `docs/IMPLEMENTACAO.md`.

Princípio: **o modelo de linguagem propõe, o núcleo decide.** O estado só muda pelo núcleo, depois de validar a proposta. Sem modelo, o jogo roda com o adaptador `mock`; sem Ragnarok, roda em texto.

## Instalação (Python ≥ 3.11)
```bash
cd mojo
python3 -m venv .venv && source .venv/bin/activate      # Windows: py -3 -m venv .venv ; .venv\Scripts\activate
pip install -e ".[dev]"                                  # instala jsonschema (única dependência) e pytest
```
Sem instalar o pacote: `pip install jsonschema` e use `./mojo.sh` (Linux/macOS) ou `mojo.bat` (Windows, **não testado**).

## Execução
```bash
mojo play examples/azrael.mjo            # abre o mundo de demonstração e mostra a cena inicial
mojo play examples/azrael.mjo --audio off
mojo validate examples/azrael.mjo        # só valida (código de saída 2 se inválido)
mojo audio-check [--say "texto"]         # health_check do Ragnarok (e síntese opcional)
python -m mojo ...                       # equivalente (com PYTHONPATH=src)
```
Comandos na sessão: ações do mundo `look`, `inspect <alvo>`, `speak <texto>`, `go <saída>` (só se o mundo permitir) — também em PT: `olhar`, `inspecionar`, `falar`, `ir`. Console: `state`, `log [n]`, `save [slot]`, `load [slot]`, `audio`, `help`, `quit`.

### Exemplo de sessão (mock, Ragnarok real no ar; saída real da box, resumida)
```
[mojo 0.1.0] adaptador semântico: mock · áudio: ragnarok (ok: Ragnarok 0.1.0; engine carregado: None)
== Azrael (demonstração, não canônico) ==
(mundo de demonstração, NÃO canônico)
Um limiar silencioso diante de uma cidadela distante. Você nota: marco de pedra, cidadela distante.
[áudio] ok · voz alex-pt · 7.707s · 2380 ms
> inspect marco
O marco de pedra tem uma face lisa e gasta; nenhuma inscrição legível resta nela.
[estado] flag inspected:marco = True
[áudio] ok · voz alex-pt · 5.749s · 1196 ms
> speak Quem guarda este limiar?
Você diz: "Quem guarda este limiar?". O silêncio devolve apenas o final da sua frase, muito baixo.
> go norte
Ação não permitida neste mundo: 'go'. Permitidas: look, speak, inspect.
> state
Cena: Limiar [threshold]   Turno: 5 ... Flags: {"inspected:marco": true}
```
Com o Ragnarok desligado a mesma sessão aparece como `[áudio indisponível] Ragnarok indisponível (...) — continuando em modo texto` (aviso uma única vez).

## Ragnarok (áudio)
O MOJO fala com o Ragnarok **por HTTP** (`127.0.0.1:8765`), sem importar código dele. Suba-o à parte: `cd ragnarok/app && ./run.sh web --no-browser` (Windows: `ragnarok.bat web`). O MOJO usa `GET /api/status` (health) e `POST /v1/audio/speech` (WAV), com timeout próprio, **cache por hash** (`.mojo/cache/audio/`) e disjuntor. O perfil lógico `narrator_default` do `.mjo` vira uma voz real na configuração (`mojo.config.example.json`). Só loopback é aceito, a menos que a config diga o contrário.

## Configuração
`mojo.config.json` (opcional; modelo em `mojo.config.example.json`) ou `--config`. Pasta de dados: `./.mojo` ou `$MOJO_HOME`. **Sem segredos no arquivo:** chaves só por variável de ambiente (`api_key_env`); campo `api_key` é recusado. Adaptadores `local`/`remote` (API compatível com OpenAI) estão **desligados por padrão** (`enabled:false`); o remoto ainda exige `https`, `consent_remote:true` e a variável de ambiente.

## Estrutura
```
schema/mojo-world-0.1.schema.json   contrato do .mjo (cópia empacotada em src/mojo/world/)
examples/azrael.mjo                 mundo de demonstração, NÃO canônico
src/mojo/
  world/    loader (valida), paths (anti-travessia), migrations (versões)
  engine/   state, actions, events, loop (core loop)
  semantic/ base, mock (padrão), openai_compat (interface local/remoto)
  audio/    base, ragnarok (RagnarokAdapter), player
  store/    saves (atômicos), logs (JSONL)
  render/   text      config.py   cli.py
tests/      pytest (200 testes; 4 exigem o Ragnarok real e são pulados sem ele)
docs/       DIAGNOSTICO-RAGNAROK, ARQUITETURA, ADRs, DECISOES-PENDENTES, IMPLEMENTACAO, TESTES
```

## Testes
```bash
pytest -q                      # tudo (os 4 testes do Ragnarok real são pulados se ele não estiver no ar)
pytest -q -m "not ragnarok"    # só os testes sem Ragnarok real
pytest -q -m ragnarok          # só a integração real (suba o Ragnarok antes)
```
Resultados medidos: `docs/TESTES.md`.

## Segurança (resumo)
`.mjo` é **dado**: nada é executado, `eval`/shell inexistentes; chaves desconhecidas rejeitadas; textos do mundo e do jogador vão ao modelo como dados e o modelo só **propõe** eventos de uma lista fechada, validados pelo núcleo; caminhos de `resources[]`, nomes de slot e ids de sessão são validados contra `..`, absolutos, UNC, drive, nomes reservados do Windows e symlinks. Logs e saves ficam locais.

## Limitações (honestas)
- **Simulado/limitado:** o `mock` não "entende" nada: devolve texto do próprio `.mjo`. O adaptador `local`/`remote` foi testado **somente contra um servidor falso local** que imita o protocolo; nenhum modelo real (local ou remoto) foi avaliado, e a utilidade de LLM local na máquina do Gui (7,7 GB, sem GPU) é **inferência**, não medida.
- **Windows não testado.** Tudo foi testado em Linux (Python 3.11.17 e 3.13.5). `mojo.bat`, `os.startfile` (`--play-audio`) e a rotina de arquivo atômico no Windows são **não testados**. `--play-audio` não foi exercido nem no Linux (a box não tem player de áudio).
- Ainda é projeto: `.mjo` assinado/compactado, sonorização/SFX, interpretação de texto livre, combate/itens/regras além do mínimo, renderização além de texto, multiusuário, migração de saves entre versões.
- O áudio exige o Ragnarok real em execução e com modelos instalados; latência medida na CPU da box (não a do Gui): ~0,6–2,4 s por frase curta (ver `docs/TESTES.md`).
- O conteúdo de `azrael.mjo` (entidades, textos, saídas) é **proposta de demonstração, não canon**.
- Licença do código MOJO: **a definir pelo Gui** (decisão 2). Dependência: `jsonschema` (MIT).
