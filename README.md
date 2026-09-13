# Affiliate Engine — V1-A

Centro de Controle local para governar automações, aprovações, tarefas, notificações e decisões. Esta entrega implementa somente **V1-A — Foundation + Control Center**. Não há integração com marketplace, coleta de comissão, publicação ou agente de IA.

## Requisitos (Windows)

- Node.js 20+ e pnpm 10+
- Python 3.11+
- PowerShell 7 recomendado

## Instalação

```powershell
pnpm install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r apps/api/requirements.txt
Copy-Item .env.example .env
python -m alembic -c apps/api/alembic.ini upgrade head
```

Dados demonstrativos são opcionais:

```powershell
pnpm seed
# remove somente registros marcados como demo
pnpm seed:clear
```

## Iniciar

Em dois terminais, com o ambiente Python ativado:

```powershell
python -m uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000 --reload
pnpm dev:web
```

Abra `http://127.0.0.1:5173`. A documentação OpenAPI fica em `http://127.0.0.1:8000/docs`.

O atalho `scripts/dev.ps1` inicia ambos quando `python` e `pnpm` estão no PATH. O backend e frontend escutam somente em `127.0.0.1`; CORS não usa curinga.

## Testes e qualidade

```powershell
python -m pytest apps/api/tests
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

## Backup e restauração

O backup usa a SQLite Backup API e é consistente mesmo com o banco aberto:

```powershell
.\scripts\backup.ps1
```

Arquivos são gravados em `data/backups` com timestamp UTC. Para restaurar, pare o backend e execute:

```powershell
.\scripts\restore.ps1 -Backup data\backups\affiliate_engine_YYYYMMDDTHHMMSSZ.db
```

Se o Python não estiver no PATH, defina `AFFILIATE_PYTHON` para o executável antes dos scripts.

## Persistência

O banco padrão é `data/affiliate_engine.db` e não entra no Git. SQLite usa foreign keys, WAL e busy timeout. Timestamps são persistidos em UTC; a UI usa o timezone configurado pelo Operator.

Veja [arquitetura](docs/ARCHITECTURE.md), [modelo de dados](docs/DATA_MODEL.md), [decisões](docs/DECISIONS.md) e [roadmap](docs/ROADMAP.md).
