# Decisões arquiteturais

## ADR-001 — Monólito modular

FastAPI concentra API, scheduler e regras atuais. Evita worker, broker e abstrações de providers antes de haver um caso real.

## ADR-002 — CSS próprio único

A V1-A usa um pequeno sistema visual próprio em vez de adicionar um kit de UI. Isso mantém uma linguagem consistente e reduz dependências sem misturar sistemas.

## ADR-003 — Scheduler conservador

O scheduler processa no máximo uma tarefa automática por ciclo e consulta o Kill Switch imediatamente antes da execução. Ao reativar, não há disparo em massa.

## ADR-004 — SQLite WAL e backup seguro

WAL atende concorrência local simples. O backup usa a SQLite Backup API, portanto não depende de uma cópia insegura do arquivo aberto.

## ADR-005 — Demo opt-in

Migration cria somente configuração padrão. Seed precisa ser executado explicitamente e todos os registros demo têm marcação própria para limpeza seletiva.

## ADR-006 — Sem autenticação na V1-A

Processos fazem bind somente em loopback e CORS é explícito. Exposição em LAN/cloud é proibida sem autenticação e autorização.
