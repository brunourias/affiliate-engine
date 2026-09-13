param([string]$Source = "data/affiliate_engine.db", [string]$Destination = "data/backups")
$ErrorActionPreference = "Stop"
$Python = if ($env:AFFILIATE_PYTHON) { $env:AFFILIATE_PYTHON } else { "python" }
& $Python "scripts/backup.py" --source $Source --destination $Destination
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
