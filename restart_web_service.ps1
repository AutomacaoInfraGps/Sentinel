$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$runner = Join-Path $projectDir "run_web_service.py"
$port = 5000

function Get-WebProcess {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -like "*run_web_service.py*"
    }
}

function Get-WebListeners {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
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
Write-Host "Serviço web reiniciado."