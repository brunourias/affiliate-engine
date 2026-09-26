[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$ValidateOnly,
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envPath = Join-Path $projectRoot ".env"
$webPath = Join-Path $projectRoot "apps\web"
$backendUrl = "http://127.0.0.1:8000"
$frontendUrl = "http://127.0.0.1:5173"
$healthUrl = "$backendUrl/api/v1/health"
$workPath = Join-Path ([System.IO.Path]::GetTempPath()) ("affiliate-engine-start-" + [guid]::NewGuid().ToString("N"))
$processes = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$jobHandle = [IntPtr]::Zero

function Stop-WithError([string]$Message) {
    throw $Message
}

function Test-PortAvailable([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $listener.Start(); return $true } catch { return $false } finally { try { $listener.Stop() } catch {} }
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds, [string]$Name) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
        } catch {}
        Start-Sleep -Milliseconds 350
    }
    Stop-WithError "$Name não respondeu dentro de $TimeoutSeconds segundos."
}

function Update-EnvSetting([string]$Path, [string]$Name, [string]$Url) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $preambleLength = 0
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $encoding = [System.Text.UTF8Encoding]::new($true); $preambleLength = 3
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $encoding = [System.Text.UnicodeEncoding]::new($false, $true); $preambleLength = 2
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        $encoding = [System.Text.UnicodeEncoding]::new($true, $true); $preambleLength = 2
    } else {
        $encoding = [System.Text.UTF8Encoding]::new($false)
    }
    $text = $encoding.GetString($bytes, $preambleLength, $bytes.Length - $preambleLength)
    $newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $pattern = '(?m)^(?!\s*#)\s*' + [regex]::Escape($Name) + '=.*$'
    $replacement = "$Name=$Url"
    if ([regex]::IsMatch($text, $pattern)) {
        $text = [regex]::Replace($text, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $replacement }, 1)
    } else {
        if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += $newline }
        $text += $replacement + $newline
    }
    $body = $encoding.GetBytes($text)
    if ($preambleLength -gt 0) {
        $preamble = $encoding.GetPreamble(); $output = [byte[]]::new($preamble.Length + $body.Length)
        [Array]::Copy($preamble, 0, $output, 0, $preamble.Length); [Array]::Copy($body, 0, $output, $preamble.Length, $body.Length)
        [System.IO.File]::WriteAllBytes($Path, $output)
    } else { [System.IO.File]::WriteAllBytes($Path, $body) }
}

function Register-Child([System.Diagnostics.Process]$Process) {
    $script:processes.Add($Process)
    if ($script:jobHandle -ne [IntPtr]::Zero) { [void][AffiliateEngine.NativeMethods]::AssignProcessToJobObject($script:jobHandle, $Process.Handle) }
    return $Process
}

function Start-ManagedProcess([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [string]$LogName) {
    $stdout = Join-Path $script:workPath "$LogName.out.log"; $stderr = Join-Path $script:workPath "$LogName.err.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Register-Child $process
}

function Stop-ManagedProcess([System.Diagnostics.Process]$Process) {
    try {
        if (-not $Process.HasExited) {
            & taskkill.exe /PID $Process.Id /T /F *> $null
            $Process.WaitForExit(5000) | Out-Null
        }
    } catch {}
}

function Read-SharedText([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return "" }
    $stream = $null; $reader = $null
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true)
        return $reader.ReadToEnd()
    } catch [System.IO.IOException] {
        return ""
    } catch [System.UnauthorizedAccessException] {
        return ""
    } finally {
        if ($null -ne $reader) { $reader.Dispose() }
        elseif ($null -ne $stream) { $stream.Dispose() }
    }
}

function Wait-TunnelUrl([string[]]$LogPaths, [int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $pattern = 'https://[a-zA-Z0-9-]+\.trycloudflare\.com'
    while ([DateTime]::UtcNow -lt $deadline) {
        foreach ($path in $LogPaths) {
            $match = [regex]::Match((Read-SharedText $path), $pattern)
            if ($match.Success) { return $match.Value.TrimEnd('/') }
        }
        Start-Sleep -Milliseconds 400
    }
    Stop-WithError "O Cloudflare Tunnel não forneceu uma URL pública dentro de $TimeoutSeconds segundos."
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { Stop-WithError "Ambiente Python não encontrado em .venv. Crie o ambiente antes de iniciar." }
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) { Stop-WithError "Arquivo .env não encontrado na raiz do projeto." }
    if (-not (Test-Path -LiteralPath $webPath -PathType Container)) { Stop-WithError "Frontend não encontrado em apps/web." }
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npm) { Stop-WithError "npm não foi encontrado no PATH." }
    $cloudflared = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $cloudflared) { $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue }
    if (-not $cloudflared) { Stop-WithError "cloudflared não foi encontrado no PATH." }
    & $pythonPath --version *> $null
    & $npm.Source --version *> $null
    & $cloudflared.Source --version *> $null
    if ($ValidateOnly) { Write-Host "Pré-requisitos do Affiliate Engine validados." -ForegroundColor Green; return }
    if ($SelfTest) {
        $testPath = Join-Path ([System.IO.Path]::GetTempPath()) ("affiliate-engine-self-test-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $testPath | Out-Null
        try {
            $testEnv = Join-Path $testPath ".env"
            $original = "# comentário`r`nPRESERVED_SETTING=preservar`r`nAFFILIATE_PUBLIC_MEDIA_BASE_URL=https://old.trycloudflare.com`r`nAFFILIATE_INSTAGRAM_REDIRECT_URI=https://old.trycloudflare.com/api/v1/connections/instagram/callback`r`nOUTRA=linha`r`n"
            [System.IO.File]::WriteAllText($testEnv, $original, [System.Text.UTF8Encoding]::new($false))
            Update-EnvSetting $testEnv "AFFILIATE_PUBLIC_MEDIA_BASE_URL" "https://new-test.trycloudflare.com"
            Update-EnvSetting $testEnv "AFFILIATE_INSTAGRAM_REDIRECT_URI" "https://new-test.trycloudflare.com/api/v1/connections/instagram/callback"
            $updated = [System.IO.File]::ReadAllText($testEnv, [System.Text.UTF8Encoding]::new($false))
            if (-not $updated.Contains("# comentário") -or -not $updated.Contains("PRESERVED_SETTING=preservar") -or -not $updated.Contains("AFFILIATE_PUBLIC_MEDIA_BASE_URL=https://new-test.trycloudflare.com") -or -not $updated.Contains("AFFILIATE_INSTAGRAM_REDIRECT_URI=https://new-test.trycloudflare.com/api/v1/connections/instagram/callback") -or $updated.Contains("old.trycloudflare")) { Stop-WithError "A atualização isolada do .env falhou." }
            $testLog = Join-Path $testPath "tunnel.log"; $writer = $null
            try {
                $writer = [System.IO.File]::Open($testLog, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
                $logBytes = [System.Text.Encoding]::UTF8.GetBytes("Quick Tunnel: https://sample-safe.trycloudflare.com")
                $writer.Write($logBytes, 0, $logBytes.Length); $writer.Flush()
                if ((Wait-TunnelUrl @($testLog) 2) -ne "https://sample-safe.trycloudflare.com") { Stop-WithError "A detecção isolada do túnel com escrita concorrente falhou." }
            } finally { if ($null -ne $writer) { $writer.Dispose() } }
            Write-Host "Testes isolados de atualização das URLs no .env e detecção do túnel passaram." -ForegroundColor Green
            return
        } finally { Remove-Item -LiteralPath $testPath -Recurse -Force -ErrorAction SilentlyContinue }
    }
    if (-not (Test-PortAvailable 8000)) { Stop-WithError "A porta 8000 já está em uso. Encerre o processo existente e tente novamente." }
    if (-not (Test-PortAvailable 5173)) { Stop-WithError "A porta 5173 já está em uso. Encerre o processo existente e tente novamente." }

    New-Item -ItemType Directory -Path $workPath | Out-Null
    if (-not ('AffiliateEngine.NativeMethods' -as [type])) {
        Add-Type @'
using System;
using System.Runtime.InteropServices;
namespace AffiliateEngine {
  public static class NativeMethods {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll")] public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] public static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
  }
}
'@
    }
    $jobHandle = [AffiliateEngine.NativeMethods]::CreateJobObject([IntPtr]::Zero, $null)
    $info = [Runtime.InteropServices.Marshal]::AllocHGlobal(144)
    try {
        for ($offset = 0; $offset -lt 144; $offset += 4) { [Runtime.InteropServices.Marshal]::WriteInt32($info, $offset, 0) }
        [Runtime.InteropServices.Marshal]::WriteInt32($info, 16, 0x2000)
        [void][AffiliateEngine.NativeMethods]::SetInformationJobObject($jobHandle, 9, $info, 144)
    } finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($info) }

    $backend = Start-ManagedProcess $pythonPath @('-m','uvicorn','apps.api.app.main:app','--host','127.0.0.1','--port','8000') $projectRoot 'backend-initial'
    Wait-Http $healthUrl 45 "Backend"
    $tunnel = Start-ManagedProcess $cloudflared.Source @('tunnel','--url',$backendUrl,'--no-autoupdate') $projectRoot 'cloudflared'
    $tunnelUrl = Wait-TunnelUrl @((Join-Path $workPath 'cloudflared.out.log'),(Join-Path $workPath 'cloudflared.err.log')) 60
    $instagramRedirectUri = "$tunnelUrl/api/v1/connections/instagram/callback"
    Update-EnvSetting $envPath "AFFILIATE_PUBLIC_MEDIA_BASE_URL" $tunnelUrl
    Update-EnvSetting $envPath "AFFILIATE_INSTAGRAM_REDIRECT_URI" $instagramRedirectUri

    Stop-ManagedProcess $backend
    $backend = Start-ManagedProcess $pythonPath @('-m','uvicorn','apps.api.app.main:app','--host','127.0.0.1','--port','8000') $projectRoot 'backend-final'
    Wait-Http $healthUrl 45 "Backend reiniciado"
    $frontend = Start-ManagedProcess $npm.Source @('run','dev','--','--host','127.0.0.1','--port','5173','--strictPort') $webPath 'frontend'
    Wait-Http $frontendUrl 60 "Frontend"
    if (-not $NoBrowser) { Start-Process $frontendUrl | Out-Null }

    Write-Host ""
    Write-Host "Affiliate Engine iniciado" -ForegroundColor Green
    Write-Host ""
    Write-Host "Backend:     $backendUrl"
    Write-Host "Frontend:    $frontendUrl"
    Write-Host "Media Tunnel: $tunnelUrl"
    Write-Host "Instagram Redirect URI: $instagramRedirectUri"
    Write-Host "Cadastre essa URL no app Meta antes de reconectar o Instagram." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Mantenha esta janela aberta enquanto estiver usando o sistema." -ForegroundColor Yellow
    Write-Host "Pressione Ctrl+C para encerrar."
    while ($true) {
        foreach ($process in @($backend, $frontend, $tunnel)) { if ($process.HasExited) { Stop-WithError "Um serviço local foi encerrado inesperadamente." } }
        Start-Sleep -Seconds 1
    }
} catch {
    Write-Host ""
    Write-Host ("Não foi possível iniciar o Affiliate Engine: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    foreach ($process in $processes) { Stop-ManagedProcess $process }
    if ($jobHandle -ne [IntPtr]::Zero -and ('AffiliateEngine.NativeMethods' -as [type])) { [void][AffiliateEngine.NativeMethods]::CloseHandle($jobHandle) }
    if (Test-Path -LiteralPath $workPath) { Remove-Item -LiteralPath $workPath -Recurse -Force -ErrorAction SilentlyContinue }
}
