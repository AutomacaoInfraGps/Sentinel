param(
    [int]$Port = $(if ($env:AUTOMACAO_WEB_PORT) { [int]$env:AUTOMACAO_WEB_PORT } else { 5000 }),
    [string]$PublicBase = $env:AUTOMACAO_PUBLIC_BASE
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$runner = Join-Path $projectDir "run_web_service.py"
$monitorScript = Join-Path $projectDir "monitor_web_background.ps1"
$port = $Port
$env:AUTOMACAO_WEB_PORT = [string]$port
if ($PublicBase) {
    $env:AUTOMACAO_PUBLIC_BASE = $PublicBase
}

function Get-WebMonitorProcess {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "powershell.exe" -and $_.CommandLine -like "*$monitorScript*"
    }
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

$monitorProcesses = @(Get-WebMonitorProcess)
foreach ($monitorProcess in $monitorProcesses) {
    if (-not $monitorProcess.ProcessId) {
        continue
    }

    try {
        Stop-Process -Id $monitorProcess.ProcessId -Force -ErrorAction Stop
        Write-Host "Monitor encerrado: $($monitorProcess.ProcessId)"
    } catch {
        Write-Host ("Falha ao encerrar monitor {0}: {1}" -f $monitorProcess.ProcessId, $_.Exception.Message)
    }
}

$listenerPids = @(Get-WebListeners)
$processes = @(Get-WebProcess)
$allPids = @($listenerPids + ($processes | Select-Object -ExpandProperty ProcessId)) | Sort-Object -Unique

foreach ($processId in $allPids) {
    if (-not $processId) {
        continue
    }

    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Processo encerrado: $processId"
    } catch {
        Write-Host ("Falha ao encerrar processo {0}: {1}" -f $processId, $_.Exception.Message)
    }
}

Start-Sleep -Seconds 1
Start-Process -FilePath $pythonExe -ArgumentList $runner -WorkingDirectory $projectDir

$healthy = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Test-WebHealth) {
        $healthy = $true
        break
    }

    Start-Sleep -Seconds 1
}

$monitorArgs = @(
    "-WindowStyle", "Hidden",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $monitorScript,
    "-Port", $port
)
if ($PublicBase) {
    $monitorArgs += @("-PublicBase", $PublicBase)
}
Start-Process -FilePath "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList $monitorArgs

if (-not $healthy) {
    Write-Host "Serviço web reiniciado, mas ainda não respondeu ao healthcheck dentro do tempo esperado."
    exit 1
}

Write-Host "Serviço web reiniciado."