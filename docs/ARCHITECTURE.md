# Arquitetura V1-A

Monólito modular local-first, separado em dois processos de desenvolvimento: React/Vite no navegador e FastAPI como API REST versionada em `/api/v1`. A UI nunca acessa SQLite diretamente; regras críticas ficam no backend.

## Frontend

React, TypeScript strict, React Router e uma camada central em `src/api/client.ts`. As rotas ativas são Dashboard, Aprovações, Tarefas, Decision Log, Notificações, Configurações, Sistema e Roadmap. O sistema visual é CSS próprio único, responsivo e sem biblioteca concorrente.

## Backend

FastAPI, Pydantic e SQLAlchemy 2. Rotas HTTP coordenam serviços de domínio pequenos: transições de tarefas, decisões de aprovação, notificações e auditoria. Logs são JSON. CORS aceita somente origens locais configuradas.

## Banco

SQLite por padrão em `data/affiliate_engine.db`, criado por Alembic. SQLAlchemy permanece portável. WAL melhora convivência entre leituras e escritas locais; foreign keys e busy timeout são ativados por conexão.

## Scheduler

Loop assíncrono dentro do processo FastAPI. A cada ciclo, verifica o Kill Switch e inicia no máximo uma tarefa automática pendente. Executa apenas `SYSTEM_HEARTBEAT` e falha controlada demonstrativa; não existe worker, broker nem ação externa.

## Execução local

Backend e frontend fazem bind em `127.0.0.1`. Não há autenticação porque esta versão não deve ser exposta à rede. Antes de cloud, autenticação e autorização serão obrigatórias.
