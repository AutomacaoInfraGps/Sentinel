param(
    [ValidateSet('install', 'run', 'status', 'remove')]
    [string]$Action = 'install',

    [string]$Time = '08:00',

    [string]$TaskName = 'Automacao - Envio Dashboard Consolidado',

    [switch]$AsSystem
)

$batPath = Join-Path $PSScriptRoot 'executar_envio_dashboard_consolidado.bat'

if (-not (Test-Path $batPath)) {
    throw "Arquivo não encontrado: $batPath"
}

$taskCommand = "cmd.exe /c `"$batPath`""

function Test-IsAdministrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

switch ($Action) {
    'install' {
        $useSystem = $AsSystem.IsPresent -or (Test-IsAdministrator)
        $createArgs = @('/Create', '/SC', 'DAILY', '/TN', $TaskName, '/TR', $taskCommand, '/ST', $Time, '/F')

        if ($useSystem) {
            $createArgs += @('/RU', 'SYSTEM', '/RL', 'HIGHEST')
        }

        schtasks.exe @createArgs | Out-Host

        if ($LASTEXITCODE -eq 0) {
            Write-Host "Agendamento criado com sucesso." -ForegroundColor Green
            Write-Host "Tarefa: $TaskName" -ForegroundColor Cyan
            Write-Host "Horário: $Time" -ForegroundColor Cyan
            if ($useSystem) {
                Write-Host "Execução: SYSTEM" -ForegroundColor Cyan
            } else {
                Write-Host "Execução: usuário atual (sem elevação)" -ForegroundColor Yellow
                Write-Host "Para recriar como SYSTEM, abra o PowerShell como administrador e rode o mesmo comando com -AsSystem." -ForegroundColor Yellow
            }
        } else {
            exit $LASTEXITCODE
        }
    }

    'run' {
        schtasks.exe /Run /TN $TaskName | Out-Host
    }

    'status' {
        schtasks.exe /Query /TN $TaskName /V /FO LIST | Out-Host
    }

    'remove' {
        schtasks.exe /Delete /TN $TaskName /F | Out-Host
    }
}