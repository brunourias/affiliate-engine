# Affiliate Engine — V1-E

Centro de Controle local com V1-A até V1-E homologadas. A versão atual inclui Radar, Curadoria, Campaign Engine e Creative Studio textual, com decisões determinísticas, rastreabilidade e aprovação humana. A próxima fase é a **V1-F — Local Media Engine**, ainda não implementada.

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

## Mercado Livre

O painel Sistema permite testar capacidades oficiais em modo anônimo ou com `MELI_ACCESS_TOKEN` fornecido no ambiente. Tokens e secrets nunca são persistidos. Consulte [a documentação da integração](docs/MERCADO_LIVRE_INTEGRATION.md).
# Local Media Engine (V1-F.1c)

O pipeline local não baixa nem instala ferramentas. Configure `AFFILIATE_MEDIA_PIPELINE_MODE=LOCAL`, `AFFILIATE_FFMPEG_PATH` e `AFFILIATE_FFPROBE_PATH`. Para voz, configure `AFFILIATE_TTS_PROVIDER=PIPER`, `AFFILIATE_TTS_EXECUTABLE_PATH` e os modelos `AFFILIATE_TTS_MODEL_BRUNO`, `AFFILIATE_TTS_MODEL_CAROL` e `AFFILIATE_TTS_MODEL_NARRATOR`. Caminhos de binários/modelos são configuração local e nunca são persistidos no banco. O modo `FAKE` serve exclusivamente a testes explícitos e não produz mídia.

No Windows, os paths podem apontar diretamente para `C:\ferramentas\ffmpeg\bin\ffmpeg.exe` e `ffprobe.exe`, ou os executáveis podem estar no `PATH`. Piper aceita `AFFILIATE_TTS_INVOCATION_MODE=CLI` com `AFFILIATE_TTS_EXECUTABLE_PATH`, ou `MODULE` com `AFFILIATE_TTS_PYTHON_PATH` e `AFFILIATE_TTS_PYTHON_MODULE=piper`. Cada `.onnx` precisa do respectivo `.onnx.json`, detectado ao lado do modelo ou informado por `AFFILIATE_TTS_MODEL_CONFIG_BRUNO`, `..._CAROL` e `..._NARRATOR`.

Validação manual sem UI: inicie o backend, consulte `GET /api/v1/media/diagnostics`, crie um job Preview com `POST /media-jobs/from-creative/{creative_id}`, inicie com `POST /media-jobs/{id}/start` e acompanhe `GET /media-jobs/{id}`. Ao concluir, resolva `previewRelativePath` sob `data/media` e confirme o arquivo com `ffprobe`. O comando opcional `\.venv\Scripts\python.exe scripts\media_smoke_test.py` testa apenas ferramentas/voz configuradas, usa arquivo temporário e o remove.
