\# Juanzito Trader — Contexto do Projeto



\## Seu papel

Você é o executor. Constrói, modifica e automatiza.

Decisões arquiteturais vêm de um arquiteto externo (Claude.ai).

Regras inegociáveis:

\- Não invente funcionalidades

\- Não desvie da essência do projeto

\- Não assuma o que não foi confirmado

\- Se tiver dúvida, pergunte antes de executar



\## Filosofia do sistema

\- Sistema faz 80%: scanner, filtro, score, risco

\- Juan faz 20%: nível de preço, padrão de candle, contexto macro

\- Score é pré-filtro — NUNCA sinal de entrada isolado

\- Juan usa TradingView Premium diariamente e acompanha macro ativamente



\## Operação atual

\- Opera APENAS em spot

\- Intenção futura (não implementar ainda):

&#x20; futuros para alavancagem, opções para proteção (hedge)

\- Só adicionar futuros/opções após Fases 3 e 4 concluídas

&#x20; com histórico de acerto real



\## Estrutura do repositório

\- main.py — scanner principal (Python)

\- requirements — dependências Python

\- scanner/ — pasta do scanner

\- Juanzito\_Trader\_v1\_8.html — painel principal

\- README.md



\## Infraestrutura

\- Scanner rodando no Railway (Python)

\- Painel HTML local, abre direto no browser

\- TradingView como fonte de dados (Premium)

\- Notificações via Discord (score ≥ 7)

\- GitHub: jgustavo1312/Juanzito-Trader



\## Roadmap

✅ Fase 1 — Motor de sinal — concluído

✅ Fase 2 — Scanner automático (Railway, Discord) — concluído

⏳ Fase 3 — Os 20% de Juan

&#x20;  - Checklist no painel: suporte/resistência,

&#x20;    padrão de candle (engolfo, martelo, pino),

&#x20;    contexto macro (dominância BTC, risk-on/off)

&#x20;  - Gestão ativa: mover stop, parcial no alvo

⏳ Fase 4 — Painel de decisão unificado

&#x20;  - Integrar resultados do scanner no painel

&#x20;  - Lista de candidatos vivos, operar/descartar, log

⏳ Fase 5 — Medição e melhoria contínua

&#x20;  - Taxa de acerto, R/R médio, refinar critérios



\## Início de cada sessão

Leia todos os arquivos do repositório antes de tocar em qualquer coisa.

Confirme o estado atual antes de executar qualquer tarefa.

