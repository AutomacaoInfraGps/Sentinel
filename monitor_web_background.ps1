$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$runner = Join-Path $projectDir "run_web_service.py"
$logDir = Join-Path $projectDir "logs"
$monitorLog = Join-Path $logDir "web_monitor.log"
$stdoutLog = Join-Path $logDir "web_task_stdout.log"
$stderrLog = Join-Path $logDir "web_task_stderr.log"
$port = 5000
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-MonitorLog([string]$message) {
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    Add-Content -Path $monitorLog -Value "[$timestamp] $message"
}

function Get-WebProcess {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -like "*run_web_service.py*"
    }
}

function Ensure-WebRunning {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    $processes = Get-WebProcess

    if ($listener -and $processes) {
        return
    }

    if ($processes) {
        foreach ($process in $processes) {
            try {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            } catch {
                Write-MonitorLog "Falha ao encerrar processo residual $($process.ProcessId): $($_.Exception.Message)"
            }
        }
    }

    Write-MonitorLog "Iniciando run_web_service.py"
    Start-Process -FilePath $pythonExe -ArgumentList $runner -WorkingDirectory $projectDir -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null
}

Write-MonitorLog "Monitor web iniciado"

while ($true) {
    try {
        Ensure-WebRunning
    } catch {
        Write-MonitorLog "Erro no monitor: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds 15
}