param(
    [ValidateSet('install', 'run', 'status', 'remove')]
    [string]$Action = 'install',

    [string]$Time = '08:00',

    [string]$TaskName = 'Automacao - Check-in Diario'
)

$batPath = Join-Path $PSScriptRoot 'executar_checkin_diario.bat'

if (-not (Test-Path $batPath)) {
    throw "Arquivo não encontrado: $batPath"
}

$taskCommand = "cmd.exe /c `"$batPath`""

switch ($Action) {
    'install' {
        schtasks.exe /Create /SC DAILY /TN $TaskName /TR $taskCommand /ST $Time /F | Out-Host

        if ($LASTEXITCODE -eq 0) {
            Write-Host "Agendamento criado com sucesso." -ForegroundColor Green
            Write-Host "Tarefa: $TaskName" -ForegroundColor Cyan
            Write-Host "Horário: $Time" -ForegroundColor Cyan
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
