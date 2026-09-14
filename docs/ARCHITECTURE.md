# Arquitetura V1-B.2

Monólito modular local-first, separado em dois processos de desenvolvimento: React/Vite no navegador e FastAPI como API REST versionada em `/api/v1`. A UI nunca acessa SQLite diretamente; regras críticas ficam no backend.

## Frontend

React, TypeScript strict, React Router e uma camada central em `src/api/client.ts`. As rotas ativas incluem Radar, Dashboard, Aprovações, Tarefas, Registro de decisões, Notificações, Configurações, Sistema e Roadmap. A interface usa pt-BR e apresenta a infraestrutura como Executor local. O sistema visual é CSS próprio único, responsivo e sem biblioteca concorrente.

## Backend

FastAPI, Pydantic e SQLAlchemy 2. Rotas HTTP coordenam serviços de domínio pequenos: transições de tarefas, decisões de aprovação, notificações e auditoria. Logs são JSON. CORS aceita somente origens locais configuradas.

O provider `integrations/mercado_livre` concentra cliente HTTP, classificação de erros e diagnóstico. Rotas não fazem chamadas HTTP diretamente. O provider usa timeout explícito, não faz retries agressivos e nunca persiste credenciais.

`MercadoLivreRadar` usa somente capabilities persistidas como `AVAILABLE`. Ele consulta trends e highlights diretamente, sem busca geral, detalhes de item ou enriquecimento. Cada execução preserva um snapshot temporal independente; falha de uma fonte não desfaz sinais obtidos das demais.

## Banco

SQLite por padrão em `data/affiliate_engine.db`, criado por Alembic. SQLAlchemy permanece portável. WAL melhora convivência entre leituras e escritas locais; foreign keys e busy timeout são ativados por conexão.

Além da migration diagnóstica `0002`, a migration `0003_radar_data_foundation` acrescenta categorias sincronizadas, runs e sinais. ITEM, PRODUCT, USER_PRODUCT e QUERY permanecem tipos externos distintos.

## Scheduler

Loop assíncrono único e idempotente dentro do processo FastAPI. A cada ciclo, verifica o Kill Switch e inicia no máximo uma tarefa automática pendente. Executa apenas `SYSTEM_HEARTBEAT` e falha controlada demonstrativa; não existe worker, broker nem ação externa.

## Execução local

Backend e frontend fazem bind em `127.0.0.1`. Não há autenticação porque esta versão não deve ser exposta à rede. Antes de cloud, autenticação e autorização serão obrigatórias.
