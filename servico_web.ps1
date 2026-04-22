param(
    [ValidateSet("install", "start", "stop", "restart", "status", "uninstall")]
    [string]$Action = "status",

    [string]$ServiceName = "AutomacaoWeb",
    [string]$TaskName = "AutomacaoWebStartup",
    [string]$DisplayName = "Automacao Web",
    [string]$Description = "Sistema de Automacao Web (Flask + Waitress)",
    [string]$PythonPath = "C:\Automacao\.venv\Scripts\python.exe",
    [string]$RunnerPath = "C:\Automacao\run_web_service.py",
    [string]$StarterPath = "C:\Automacao\start_web_background.ps1",
    [string]$MonitorPath = "C:\Automacao\monitor_web_background.ps1"
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-PathExists([string]$Path, [string]$Label) {
    if (-not (Test-Path $Path)) {
        throw "$Label não encontrado: $Path"
    }
}

function Invoke-RequiringAdmin([string]$InnerAction) {
    if (Test-Admin) {
        return $false
    }

    $scriptPath = $MyInvocation.MyCommand.Path
    $escapedAction = $InnerAction.Replace("'", "''")
    Start-Process PowerShell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File '$scriptPath' -Action '$escapedAction'"
    Write-Host "Solicitação elevada aberta. Confirme o UAC para concluir '$InnerAction'."
    return $true
}

function Stop-WebProcesses {
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -like '*run_web_service.py*'
    }

    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            Write-Host "Processo web encerrado: $($process.ProcessId)"
        } catch {
            Write-Host "Falha ao encerrar processo $($process.ProcessId): $($_.Exception.Message)"
        }
    }
}

function Install-Service {
    if (Invoke-RequiringAdmin 'install') {
        return
    }

    Assert-PathExists $PythonPath "Python do venv"
    Assert-PathExists $RunnerPath "Runner do serviço"
    Assert-PathExists $StarterPath "Starter do processo em background"
    Assert-PathExists $MonitorPath "Monitor da aplicação web"

    & $PythonPath -m pip install --disable-pip-version-check waitress | Out-Null

    schtasks /delete /tn $TaskName /f 2>$null | Out-Null
    schtasks /create /tn $TaskName /sc onstart /ru SYSTEM /rl HIGHEST /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $MonitorPath" /f | Out-Null

    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        sc.exe config $ServiceName start= demand | Out-Null
    }

    Write-Host "Tarefa '$TaskName' instalada para manter a automação web ativa no boot."
    Start-WebService
}

function Start-WebService {
    if (Invoke-RequiringAdmin 'start') {
        return
    }

    schtasks /run /tn $TaskName | Out-Null
    Write-Host "Tarefa '$TaskName' acionada."
}

function Stop-WebService {
    if (Invoke-RequiringAdmin 'stop') {
        return
    }

    schtasks /end /tn $TaskName 2>$null | Out-Null
    Stop-WebProcesses
    Write-Host "Automação web parada."
}

function Restart-WebService {
    if (Invoke-RequiringAdmin 'restart') {
        return
    }

    Stop-WebService
    Start-WebService
}

function Show-Status {
    $taskOutput = cmd /c "schtasks /query /tn $TaskName /fo LIST /v 2>nul"
    if ($LASTEXITCODE -ne 0) {
        $taskOutput = $null
    }
    $listener = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

    if ($taskOutput) {
        Write-Host "Tarefa: $TaskName"
        ($taskOutput | Select-String 'Status:|Task To Run:|Last Run Time:|Last Result:') | ForEach-Object { Write-Host $_.Line }
    } else {
        Write-Host "Tarefa '$TaskName' não encontrada."
    }

    if ($svc) {
        Write-Host "Serviço legado '$ServiceName': $($svc.Status) / $($svc.StartType)"
    }

    if ($listener) {
        Write-Host "Porta 5000 ativa no PID $($listener.OwningProcess)"
    } else {
        Write-Host "Porta 5000 sem listener."
    }
}

function Uninstall-Service {
    if (Invoke-RequiringAdmin 'uninstall') {
        return
    }

    Stop-WebProcesses
    schtasks /delete /tn $TaskName /f 2>$null | Out-Null
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        sc.exe config $ServiceName start= demand | Out-Null
    }
    Write-Host "Automação automática removida."
}

switch ($Action) {
    "install"   { Install-Service }
    "start"     { Start-WebService }
    "stop"      { Stop-WebService }
    "restart"   { Restart-WebService }
    "status"    { Show-Status }
    "uninstall" { Uninstall-Service }
}