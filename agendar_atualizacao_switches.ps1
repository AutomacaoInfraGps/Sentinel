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

        # /RL HIGHEST define privilegios, nao prioridade de desempenho. Sem
        # esta configuracao o Agendador usa prioridade 7 (processo e I/O de
        # segundo plano), que tambem e herdada pelo Chrome do worker.
        $taskService = New-Object -ComObject 'Schedule.Service'
        $taskService.Connect()
        $taskFolder = $taskService.GetFolder('\')
        $registeredTask = $taskFolder.GetTask($TaskName)
        $taskDefinition = $registeredTask.Definition
        $taskDefinition.Settings.Priority = 4
        # A tarefa deve continuar independente da sessao interativa e nao pode
        # ser interrompida quando o notebook alternar para bateria. O worker
        # faz sua propria trava, portanto novas instancias podem ser ignoradas.
        $taskDefinition.Settings.DisallowStartIfOnBatteries = $false
        $taskDefinition.Settings.StopIfGoingOnBatteries = $false
        $taskDefinition.Settings.StartWhenAvailable = $true
        $taskDefinition.Settings.WakeToRun = $true
        $taskDefinition.Settings.MultipleInstances = 2
        $taskDefinition.Settings.ExecutionTimeLimit = 'PT0S'
        $taskCreateOrUpdate = 6
        $taskLogonServiceAccount = 5
        $null = $taskFolder.RegisterTaskDefinition(
            $TaskName,
            $taskDefinition,
            $taskCreateOrUpdate,
            'SYSTEM',
            $null,
            $taskLogonServiceAccount,
            $null
        )

        Write-Host 'Tarefa do worker criada com sucesso.' -ForegroundColor Green
        Write-Host "Tarefa: $TaskName" -ForegroundColor Cyan
        Write-Host 'Frequencia: a cada 1 minuto e sob demanda' -ForegroundColor Cyan
        Write-Host 'Execucao: SYSTEM (pode ser diferente da conta do backend)' -ForegroundColor Cyan
        Write-Host 'Prioridade: normal (4)' -ForegroundColor Cyan
        Write-Host 'Sessao: independente de usuario conectado ou tela bloqueada' -ForegroundColor Cyan
        Write-Host 'Energia: continua em bateria e acorda para executar' -ForegroundColor Cyan
        Write-Host 'Duracao maxima: sem limite do Agendador' -ForegroundColor Cyan
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
