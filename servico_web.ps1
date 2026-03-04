param(
    [ValidateSet("install", "start", "stop", "restart", "status", "uninstall")]
    [string]$Action = "status",

    [string]$ServiceName = "AutomacaoWeb",
    [string]$DisplayName = "Automacao Web",
    [string]$Description = "Sistema de Automacao Web (Flask + Waitress)",
    [string]$PythonPath = "C:\Automacao\.venv\Scripts\python.exe",
    [string]$RunnerPath = "C:\Automacao\run_web_service.py"
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-Exists([string]$Path, [string]$Label) {
    if (-not (Test-Path $Path)) {
        throw "$Label não encontrado: $Path"
    }
}

function Install-Service {
    if (-not (Test-Admin)) {
        throw "Execute o PowerShell como Administrador para instalar o serviço."
    }

    Ensure-Exists $PythonPath "Python do venv"
    Ensure-Exists $RunnerPath "Runner do serviço"

    & $PythonPath -m pip install --disable-pip-version-check waitress | Out-Null

    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $binPath = '"' + $PythonPath + '" "' + $RunnerPath + '"'
    if ($existing) {
        Write-Host "Serviço '$ServiceName' já existe. Atualizando configuração..."
    } else {
        sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= $DisplayName | Out-Null
    }

    sc.exe config $ServiceName binPath= $binPath | Out-Null
    sc.exe description $ServiceName $Description | Out-Null
    sc.exe config $ServiceName start= auto | Out-Null
    sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/5000/restart/5000 | Out-Null
    sc.exe failureflag $ServiceName 1 | Out-Null

    Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
    Write-Host "Serviço '$ServiceName' instalado/configurado e iniciado."
}

function Start-WebService {
    Start-Service -Name $ServiceName
    Write-Host "Serviço '$ServiceName' iniciado."
}

function Stop-WebService {
    Stop-Service -Name $ServiceName -Force
    Write-Host "Serviço '$ServiceName' parado."
}

function Restart-WebService {
    Restart-Service -Name $ServiceName -Force
    Write-Host "Serviço '$ServiceName' reiniciado."
}

function Show-Status {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Host "Serviço '$ServiceName' não encontrado."
        return
    }
    Write-Host "Nome: $($svc.Name)"
    Write-Host "Status: $($svc.Status)"
    Write-Host "Tipo de inicialização: $(Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" | Select-Object -ExpandProperty StartMode)"
}

function Uninstall-Service {
    if (-not (Test-Admin)) {
        throw "Execute o PowerShell como Administrador para remover o serviço."
    }

    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -ne 'Stopped') {
            Stop-Service -Name $ServiceName -Force
        }
        sc.exe delete $ServiceName | Out-Null
        Write-Host "Serviço '$ServiceName' removido."
    } else {
        Write-Host "Serviço '$ServiceName' não existe."
    }
}

switch ($Action) {
    "install"   { Install-Service }
    "start"     { Start-WebService }
    "stop"      { Stop-WebService }
    "restart"   { Restart-WebService }
    "status"    { Show-Status }
    "uninstall" { Uninstall-Service }
}
