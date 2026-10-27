# MOJO V2 — medições na box (NÃO é o PC do Gui)

> **Medição na box** — 2026-10-27 19:58:35 (America/Sao_Paulo). CPU: Intel(R) Xeon(R) Processor (8 vCPU, nuvem), Linux-6.12.94+-x86_64-with-glibc2.41, Python 3.13.5.
> Gerado por `tools/bench_v2.py` (reproduza com `python tools/bench_v2.py`). **Nada foi medido no Windows nem no navegador do Gui**: no PC dele os números serão diferentes (provavelmente do mesmo nível de grandeza no motor, mas isso é inferência, não medição).

## 1. Tempo do tick do motor (sem rede), cenários reais dos packs — ms/tick

| cenário | ticks rodados | entidades | média | p50 | p99 | máx | resultado |
|---|---|---|---|---|---|---|---|
| poc-mini/mini | 300 | 10 | 0.0217 | 0.0087 | 0.1156 | 2.3795 | victory |
| poc-mini/duel | 1100 | 13 | 0.0162 | 0.0131 | 0.0771 | 0.371 | victory |
| poc-mini/ai_duel | 1100 | 13 | 0.0249 | 0.0201 | 0.118 | 0.5289 | victory |
| elemental-proto/coop_vs_entropy | 1520 | 16 | 0.0193 | 0.0166 | 0.0864 | 0.1698 | victory |
| elemental-proto/quarteto_ai | 1160 | 14 | 0.0577 | 0.0445 | 0.2503 | 2.5146 | victory |

Orçamento a 10 Hz = **100 ms/tick**. Cenários pequenos (10–16 entidades, IA ligada) usam ≲0,3 ms no p99.

## 2. Estresse do motor: 400 e 800 entidades (pacote elemental, mapa 32×24, IA desligada, população mantida constante)

Unidades de combate das 4 facções em posições aleatórias, 24 ordens de movimento novas a cada 40 ticks (pathfinding contínuo), combate e regras de onda ativos; o hp é reabastecido após o sistema `combat` (a população não diminui — o custo desse laço entra na medição). 1200 ticks cada.

| entidades | média | p50 | p99 | máx | folga no p99 vs 100 ms |
|---|---|---|---|---|---|
| 400 (fim: 400) | 0.6346 | 0.4658 | 4.3989 | 11.2337 | 22.7× |
| 800 (fim: 800) | 0.9368 | 0.7431 | 4.9731 | 6.468 | 20.1× |

**O que a carga exercita (amostrado a cada 10 ticks, caso de 400):** em média ~360 das 400 unidades com ordem de ataque, ~300 em recarga de golpe (ou seja, combatendo de fato) e ~62 com caminho ativo — o mapa 32×24 fica denso, então é combate pesado, não unidades paradas.
**Limites honestos:** é uma carga sintética de um único padrão (sem IA, sem construção, sem produção simultânea em massa); o tick é CPython puro; e a folga de >20× no p99 vale **para esta carga, nesta máquina**. Partidas reais com muita produção/IA podem custar mais; o orçamento é configurável (`max_effects_per_tick`, `max_paths_per_tick`).

## 3. WebSocket real (uvicorn + cliente `websockets`, loopback) — poc-mini, 10 Hz, 20 s

| métrica (ms) | média | p50 | p99 | máx |
|---|---|---|---|---|
| ping → pong (RTT) | 0.7267 | 0.6862 | 1.804 | 2.8365 |
| comando → ack | 0.4686 | 0.4348 | 1.0102 | 1.0102 |
| intervalo entre mensagens `tick` (alvo 100) | 99.8128 | 101.7228 | 103.4183 | 103.9913 |

Servidor: tick p99 = 0.272 ms; tick+serialização+envio p99 = 3.567 ms; ticks atrasados = 0; tráfego ≈ 966 B/s.

## 4. WebSocket com 400 entidades em movimento (elemental, quarteto, 10 Hz, 20 s)

| métrica (ms) | média | p50 | p99 | máx |
|---|---|---|---|---|
| ping → pong (RTT) | 0.9412 | 0.8451 | 5.5169 | 7.5887 |
| intervalo entre mensagens `tick` | 100.0775 | 100.98 | 108.4765 | 109.3027 |

Servidor: tick médio = 1.145 ms, p99 = 12.52 ms (inclui diff para o cliente); tick+envio p99 = 12.889 ms; ticks atrasados = 0; tráfego do cliente ≈ 20636 B/s (~20.2 KiB/s).

## 5. Como ler
- RTT e latência de comando são de **loopback na mesma máquina**: não incluem rede, navegador nem renderização.
- Cada comando entra com atraso de 1 tick (`INPUT_DELAY_TICKS=1` = 100 ms a 10 Hz) — é o desenho, não latência de rede.
- FPS do Canvas 2D e custo do navegador **não foram medidos** (só o headless Chrome rodou, para teste funcional).
