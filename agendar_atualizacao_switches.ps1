param(
    [ValidateSet('install', 'run', 'status', 'remove')]
    [string]$Action = 'status',

    [string]$TaskName = 'SentinelSwitchUpdateWorker'
)

$batPath = Join-Path $PSScriptRoot 'executar_switch_update_worker.bat'

if (-not (Test-Path -LiteralPath $batPath)) {
    throw "Arquivo nao encontrado: $batPath"
}

$taskCommand = "cmd.exe /c `"$batPath`""

function Test-IsAdministrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

switch ($Action) {
    'install' {
        if (-not (Test-IsAdministrator)) {
            throw 'Abra o PowerShell como administrador para instalar a tarefa como SYSTEM.'
        }

        $createArgs = @(
            '/Create', '/SC', 'MINUTE', '/MO', '1',
            '/TN', $TaskName,
            '/TR', $taskCommand,
            '/RU', 'SYSTEM', '/RL', 'HIGHEST', '/F'
        )
        schtasks.exe @createArgs | Out-Host
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        Write-Host 'Tarefa do worker criada com sucesso.' -ForegroundColor Green
        Write-Host "Tarefa: $TaskName" -ForegroundColor Cyan
        Write-Host 'Frequencia: a cada 1 minuto e sob demanda' -ForegroundColor Cyan
        Write-Host 'Execucao: SYSTEM (mesma identidade da tarefa web atual)' -ForegroundColor Cyan
    }

    'run' {
        schtasks.exe /Run /TN $TaskName | Out-Host
        exit $LASTEXITCODE
    }

    'status' {
        schtasks.exe /Query /TN $TaskName /V /FO LIST | Out-Host
        exit $LASTEXITCODE
    }

    'remove' {
        schtasks.exe /Delete /TN $TaskName /F | Out-Host
        exit $LASTEXITCODE
    }
}
