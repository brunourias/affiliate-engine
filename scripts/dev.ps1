$ErrorActionPreference = "Stop"
$Python = if ($env:AFFILIATE_PYTHON) { $env:AFFILIATE_PYTHON } else { "python" }
Write-Host "Iniciando Affiliate Engine em modo local..."
Start-Process -FilePath $Python -ArgumentList "-m","uvicorn","apps.api.app.main:app","--host","127.0.0.1","--port","8000","--reload" -WindowStyle Hidden
& pnpm --filter @affiliate-engine/web dev
