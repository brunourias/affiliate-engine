param([Parameter(Mandatory=$true)][string]$Backup)
$ErrorActionPreference = "Stop"
$resolved = Resolve-Path -LiteralPath $Backup
if ((Get-Process -Name python -ErrorAction SilentlyContinue)) { throw "Pare o backend antes de restaurar." }
Copy-Item -LiteralPath $resolved -Destination "data/affiliate_engine.db" -Force
Write-Host "Banco restaurado de $resolved"
