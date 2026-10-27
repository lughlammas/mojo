# MOJO — decisões que dependem do Gui (27/10/2026)

> **Atualização:** o Gui mandou implementar o MOJO sem responder a estas decisões. A v0.1 usa os **padrões propostos** abaixo (marcados em `docs/IMPLEMENTACAO.md`). Eles continuam **abertos**: o Gui pode mudar qualquer um.

Ordem aproximada de urgência. "Padrão proposto" = o que eu faria se ele disser "pode seguir"; nada é executado sem o aval.

| # | Decisão | Por que importa | Padrão proposto |
|---|---|---|---|
| 1 | **Linguagem/stack do MOJO** | Define todo o código e o empacotamento | Python ≥ 3.11 (stdlib + `jsonschema`), como o Ragnarok (ADR-003) |
| 2 | **Onde fica o repositório** (nome, local, GitHub ou só local, visibilidade, licença) | Hoje só existe `/workspace/mojo/docs/` na box, sem git | Repositório git privado `mojo` (ou dentro de Dream Fabrics); licença a definir — **não publico nem faço push sem aval** |
| 3 | **Modelo de linguagem: local, remoto ou só `mock` por enquanto** | Com 7,7 GB e sem GPU, um LLM local útil é limitado (ARQUITETURA §7.1, tudo inferência); remoto envia texto para fora e pode custar | Começar com `mock` + interface; **benchmark curto na máquina do Gui** para decidir; remoto só com consentimento e sem serviço pago sem autorização |
| 3a | Se for local: qual servidor/modelo e quem instala | Instalar algo na máquina dele exige autorização; licenças de modelos não verificadas | Avaliar 1–2 modelos pequenos quantizados; escolher após medir RAM, tokens/s e qualidade em PT-BR |
| 3b | Se for remoto: qual provedor, orçamento, privacidade | Custo e vazamento do conteúdo do mundo | Nenhum por padrão |
| 4 | **Canon real de Azrael** | Não invento canon; o exemplo do brief é ilustrativo (paleta, "fantasia", cena `threshold`) | Entregar `azrael.mjo` demo genérico com `meta.canon=false`; **o Gui envia o material oficial** (ou diz que quer manter só o demo) |
| 5 | **Narrador: qual voz do Ragnarok** para `narrator_default` (e idioma do mundo) | O Ragnarok não tem perfis; MOJO precisa de tabela perfil→voz | `alex-pt` (maduro) ou `sabio-pt` para PT-BR; `onyx-en`/`sabio-en` para EN — escolha dele |
| 6 | **Idioma do jogo e dos prompts** (PT-BR, EN ou ambos) | Afeta mundo demo, mock e modelo | PT-BR com suporte a EN depois |
| 7 | **Cliente da v0.1**: só CLI textual ou também web local | O critério de aceite pede só textual | CLI textual; áudio por player do SO (opcional) |
| 8 | **Ragnarok: iniciar à mão ou pelo MOJO** (e porta) | Afeta robustez e UX | Manual; opção futura de processo filho configurável |
| 9 | **Posso corrigir lacunas do Ragnarok?** (500 em texto puro quando faltam modelos → 503 JSON; `/health`; nova tentativa no download do Supertonic; streaming por frase) | O brief diz para não alterar sem necessidade demonstrada; o download do Supertonic falhou uma vez na instalação dele (**não mexi**) | Só após a instalação no Windows terminar e ele autorizar; começando pelo erro 503 e pelo retry |
| 10 | **"Sonorização"** (SFX/ambiência/trilha) está no escopo? | O Ragnarok só faz voz; seria módulo novo | Fora da v0.1 |
| 11 | **Regras do `rpg-minimal-v0`** (o brief só cita o nome) | Preciso do conteúdo para o motor | HP, inventário e flags mínimos (ADR-011); ele ajusta |
| 12 | **Local, retenção e privacidade de saves/logs** | Logs guardam o texto do jogador | Pasta do projeto, sem envio externo, rotação simples |
| 13 | **Licenciamento/IP/assinatura de `.mjo`** | A extensão não garante exclusividade; GPL em dependências do Ragnarok afeta redistribuição | Adiar; v0.1 aberto e em JSON |
| 14 | **Autorização para qualquer instalação na máquina do Gui** (Python, modelo, benchmark) | Nada foi instalado e nada será sem aval explícito | — |
| 15 | **Quando validar o adaptador no Windows** | O Ragnarok ainda não está validado lá (instalação em andamento) | Depois que a instalação dele terminar e `doctor --full` rodar |

## O que eu NÃO fiz e NÃO farei sem decisão
Implementar o motor (passos 3–5 do brief), criar repositório/push, instalar qualquer coisa no computador do Gui, alterar o Ragnarok, escolher modelo de linguagem, fixar canon de Azrael.

## Itens de risco para ele saber
- Latência de voz sem streaming (~1–2 s por fala numa CPU de servidor; **na máquina dele não medida**).
- Um LLM local concorrendo por CPU/RAM com o Ragnarok pode deixar cada turno lento [inferência].
- A narração livre do modelo pode contradizer o mundo, embora nunca altere o estado (ADR-001).
