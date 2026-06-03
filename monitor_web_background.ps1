param(
    [int]$Port = $(if ($env:AUTOMACAO_WEB_PORT) { [int]$env:AUTOMACAO_WEB_PORT } else { 5000 }),
    [string]$PublicBase = $env:AUTOMACAO_PUBLIC_BASE
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$runner = Join-Path $projectDir "run_web_service.py"
$logDir = Join-Path $projectDir "logs"
$monitorLog = Join-Path $logDir "web_monitor.log"
$stdoutLog = Join-Path $logDir "web_task_stdout.log"
$stderrLog = Join-Path $logDir "web_task_stderr.log"
$port = $Port
$startupGraceSeconds = 45
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:AUTOMACAO_WEB_PORT = [string]$port
if ($PublicBase) {
    $env:AUTOMACAO_PUBLIC_BASE = $PublicBase
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-MonitorLog([string]$message) {
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    Add-Content -Path $monitorLog -Value "[$timestamp] $message"
}

function Get-WebProcess {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -like "*$runner*"
    }
}

function Get-WebListeners {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Test-WebHealth {
    try {
        $response = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/test" -f $port) -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Stop-WebProcesses {
    $listenerPids = @(Get-WebListeners)
    $processes = @(Get-WebProcess)
    $allPids = @($listenerPids + ($processes | Select-Object -ExpandProperty ProcessId)) | Sort-Object -Unique

    foreach ($processId in $allPids) {
        if (-not $processId) {
            continue
        }

        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-MonitorLog "Processo web encerrado: $processId"
        } catch {
            Write-MonitorLog ("Falha ao encerrar processo {0}: {1}" -f $processId, $_.Exception.Message)
        }
    }
}

function Ensure-WebRunning {
    $listeners = @(Get-WebListeners)
    $processes = @(Get-WebProcess)
    $serviceHealthy = Test-WebHealth

    if ($serviceHealthy) {
        return
    }

    if ($processes.Count -gt 0) {
        $newestProcess = $processes | Sort-Object CreationDate -Descending | Select-Object -First 1
        if ($newestProcess -and $newestProcess.CreationDate) {
            $processAge = (Get-Date) - $newestProcess.CreationDate
            if ($processAge.TotalSeconds -lt $startupGraceSeconds) {
                return
            }
        }
    }

    Stop-WebProcesses

    Write-MonitorLog "Iniciando run_web_service.py"
    Start-Process -FilePath $pythonExe -ArgumentList $runner -WorkingDirectory $projectDir -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null
}

Write-MonitorLog "Monitor web iniciado na porta $port"

while ($true) {
    try {
        Ensure-WebRunning
    } catch {
        Write-MonitorLog "Erro no monitor: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds 15
}