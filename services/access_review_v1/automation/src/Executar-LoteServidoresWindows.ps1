[CmdletBinding()]
param([Parameter(Mandatory)][string]$Plano)

$ErrorActionPreference = 'Stop'
$raiz = $env:SENTINEL_ACCESS_REVIEW_HOME
$CodeRoot = $env:SENTINEL_ACCESS_REVIEW_CODE
$Plano = (Resolve-Path -LiteralPath $Plano).Path
$dados = Get-Content -Raw -Encoding UTF8 -LiteralPath $Plano | ConvertFrom-Json
$modo = [string]$dados.modo
$pasta = Join-Path $raiz 'dados\execucoes\ServidoresWindows'
$prefixoExecucao = if ($dados.retomar_falhas) { 'Retomada' } else { 'Teste' }
$log = Join-Path $pasta ("{0}-{1}-log.txt" -f $prefixoExecucao, $modo)
$resultado = Join-Path $pasta ("Resultado-{0}-{1}.json" -f $prefixoExecucao, $modo)
$erro = Join-Path $pasta ("{0}-{1}-erro.txt" -f $prefixoExecucao, $modo)
$aduc = $null
$etapas = [ordered]@{}
$falhas = 0

function Set-ReviewProgress {
    param(
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][int]$Percent,
        [int]$Current = 0,
        [int]$Total = 0
    )
    $target = $env:SENTINEL_ACCESS_REVIEW_PROGRESS_FILE
    if (-not $target) { return }
    try {
        $runtime = [System.IO.Path]::GetFullPath((Join-Path $raiz 'runtime'))
        $resolved = [System.IO.Path]::GetFullPath($target)
        if (-not $resolved.StartsWith($runtime, [System.StringComparison]::OrdinalIgnoreCase)) { return }
        $payload = @{stage=$Stage;percent=[Math]::Max(0,[Math]::Min(100,$Percent))}
        if ($Total -gt 0 -and $Current -ge 0 -and $Current -le $Total) { $payload['current']=$Current; $payload['total']=$Total }
        $temporary = "$resolved.$PID.tmp"
        $payload | ConvertTo-Json -Compress | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $resolved -Force
    } catch { }
}

function Executar-Python {
    param([Parameter(Mandatory)][string]$Nome, [Parameter(Mandatory)][string[]]$Argumentos)
    $ErrorActionPreference = 'Continue'
    & $script:python (Join-Path $PSScriptRoot 'access_review_progress.py') 'Captura AD' $Nome 'running'
    $saida = & $script:python @Argumentos 2>&1
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $saida | ForEach-Object { $_.ToString() } | Add-Content -LiteralPath $script:log -Encoding UTF8
    if ($codigo -eq 0) {
        & $script:python (Join-Path $PSScriptRoot 'access_review_progress.py') 'Captura AD concluida' $Nome 'completed'
        $script:etapas[$Nome] = 'OK'
    }
    else {
        & $script:python (Join-Path $PSScriptRoot 'access_review_progress.py') "Captura AD falhou (codigo $codigo)" $Nome 'warning'
        $script:etapas[$Nome] = "FALHA ($codigo)"
        $script:falhas++
    }
}

function Executar-PowerShell {
    param([Parameter(Mandatory)][string]$Nome, [Parameter(Mandatory)][string]$Script, [Parameter(Mandatory)][string[]]$Argumentos)
    try {
        & $env:SENTINEL_ACCESS_REVIEW_PYTHON (Join-Path $PSScriptRoot 'access_review_progress.py') 'Captura Windows' $Nome 'running'
        $saida = & $Script @Argumentos 2>&1
        $saida | ForEach-Object { $_.ToString() } | Add-Content -LiteralPath $script:log -Encoding UTF8
        $script:etapas[$Nome] = 'OK'
        & $env:SENTINEL_ACCESS_REVIEW_PYTHON (Join-Path $PSScriptRoot 'access_review_progress.py') 'Captura Windows concluida' $Nome 'completed'
    }
    catch {
        & $env:SENTINEL_ACCESS_REVIEW_PYTHON (Join-Path $PSScriptRoot 'access_review_progress.py') 'Captura Windows falhou' $Nome 'warning'
        ($_ | Out-String) | Add-Content -LiteralPath $script:log -Encoding UTF8
        $script:etapas[$Nome] = "FALHA: $($_.Exception.Message)"
        $script:falhas++
    }
}

try {
    New-Item -ItemType Directory -Path $pasta -Force | Out-Null
    "Inicio: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) | modo: $modo" | Set-Content -LiteralPath $log -Encoding UTF8

    $slotsCaptura = if ($null -ne $dados.slots_captura) { @($dados.slots_captura) } else { @($dados.slots) }
    $secoesCaptura = if ($null -ne $dados.secoes_captura) { @($dados.secoes_captura) } else { @($dados.secoes) }

    # Preserva as evidencias anteriores antes de produzir um teste novo.
    $carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
    $arquivo = Join-Path $pasta ("prints_substituidos\teste-{0}-{1}" -f $modo, $carimbo)
    $movidos = 0
    foreach ($slot in $slotsCaptura) {
        if ($dados.preservar_evidencias_existentes) { continue }
        $prefixo = ([string]$slot) -replace '_1$', ''
        $arquivos = @(Get-ChildItem -LiteralPath (Join-Path $raiz 'dados\evidencias\ServidoresWindows') -Filter ($prefixo + '_*.png') -File -ErrorAction SilentlyContinue)
        foreach ($item in $arquivos) {
            if ($item.FullName.StartsWith($raiz, [System.StringComparison]::OrdinalIgnoreCase)) {
                New-Item -ItemType Directory -Path $arquivo -Force | Out-Null
                Move-Item -LiteralPath $item.FullName -Destination $arquivo
                $movidos++
            }
        }
    }
    foreach ($slot in @($dados.slots_obsoletos)) {
        $item = Join-Path $raiz ("dados\evidencias\ServidoresWindows\{0}.png" -f [string]$slot)
        if (Test-Path -LiteralPath $item) {
            $resolvido = (Resolve-Path -LiteralPath $item).Path
            if ($resolvido.StartsWith($raiz, [System.StringComparison]::OrdinalIgnoreCase)) {
                New-Item -ItemType Directory -Path $arquivo -Force | Out-Null
                Move-Item -LiteralPath $resolvido -Destination $arquivo
                $movidos++
            }
        }
    }
    "Evidencias anteriores arquivadas: $movidos" | Add-Content -LiteralPath $log -Encoding UTF8
    Set-ReviewProgress -Stage 'windows_archive' -Percent 16

    if ($null -eq $dados.executar_server_manager -or $dados.executar_server_manager) {
        Set-ReviewProgress -Stage 'windows_server_manager' -Percent 20
        Executar-PowerShell -Nome 'Server Manager' -Script (Join-Path $PSScriptRoot 'Capturar-ServerManager.ps1') -Argumentos @(
            '-SaidaDashboard', (Join-Path $raiz 'dados\evidencias\ServidoresWindows\p007_1.png'),
            '-SaidaLocalServer', (Join-Path $raiz 'dados\evidencias\ServidoresWindows\p008_1.png')
        )
    }

    $python = $env:SENTINEL_ACCESS_REVIEW_PYTHON
    $env:PYTHONIOENCODING = 'utf-8'
    $precisaAduc = ($null -eq $dados.executar_bloco_inicial -or $dados.executar_bloco_inicial) -or $secoesCaptura.Count -gt 0
    if ($precisaAduc) {
        Set-ReviewProgress -Stage 'windows_aduc' -Percent 30
        $compatibilidadeAnterior = $env:__COMPAT_LAYER
        try {
            # Impede a autoelevação do MMC. O acesso usado pela auditoria é somente leitura.
            $env:__COMPAT_LAYER = 'RunAsInvoker'
            $aduc = Start-Process -FilePath "$env:WINDIR\System32\mmc.exe" -ArgumentList 'dsa.msc' -PassThru
        }
        finally {
            $env:__COMPAT_LAYER = $compatibilidadeAnterior
        }
        $limite = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 250
            $aduc.Refresh()
        } until ($aduc.MainWindowHandle -ne [IntPtr]::Zero -or $aduc.HasExited -or (Get-Date) -gt $limite)
        if ($aduc.HasExited -or $aduc.MainWindowHandle -eq [IntPtr]::Zero) { throw 'O ADUC nao abriu.' }

        if ($null -eq $dados.executar_bloco_inicial -or $dados.executar_bloco_inicial) {
            Set-ReviewProgress -Stage 'windows_initial' -Percent 38
            Executar-Python -Nome 'Bloco inicial' -Argumentos @((Join-Path $PSScriptRoot 'prefix_bot.py'), '--pid', [string]$aduc.Id)
        }
        $indiceSecao = 0
        $falhasConsecutivas = 0
        foreach ($secao in $secoesCaptura) {
            $indiceSecao++
            $percentualSecao = 44 + [int](($indiceSecao / [Math]::Max($secoesCaptura.Count, 1)) * 30)
            Set-ReviewProgress -Stage 'windows_sections' -Percent $percentualSecao -Current $indiceSecao -Total $secoesCaptura.Count
            Executar-Python -Nome ([string]$secao) -Argumentos @(
                (Join-Path $PSScriptRoot 'aduc_bot.py'), '--pid', [string]$aduc.Id, '--secao', [string]$secao
            )
            if ([string]$etapas[[string]$secao] -like 'FALHA*') { $falhasConsecutivas++ } else { $falhasConsecutivas = 0 }
            if ($falhasConsecutivas -ge 5) {
                Set-ReviewProgress -Stage 'windows_aborted' -Percent $percentualSecao
                & $python (Join-Path $PSScriptRoot 'access_review_progress.py') 'Cinco regionais consecutivas com falha; encerrando revisão AD' ([string]$secao) 'failed'
                exit 25
            }
        }
    }

    [ordered]@{
        modo = $modo
        concluido_em = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
        secoes = $secoesCaptura
        total_etapas = $etapas.Count
        falhas = $falhas
        etapas = $etapas
        log = $log
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultado -Encoding UTF8
    if (Test-Path -LiteralPath $erro) { Remove-Item -LiteralPath $erro -Force }
    if ($falhas -gt 0) { exit 1 }
}
catch {
    ($_ | Out-String) | Set-Content -LiteralPath $erro -Encoding UTF8
    exit 1
}
finally {
    if ($aduc -and -not $aduc.HasExited) {
        Stop-Process -Id $aduc.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        if (Get-Process -Id $aduc.Id -ErrorAction SilentlyContinue) {
            & "$env:WINDIR\System32\taskkill.exe" /PID $aduc.Id /T /F 2>$null | Out-Null
        }
    }
}
