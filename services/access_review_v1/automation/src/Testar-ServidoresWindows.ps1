[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Reduzido', 'Completo')][string]$Modo,
    [switch]$SomenteMontagem,
    [switch]$RetomarFalhas
)

$ErrorActionPreference = 'Stop'
$raiz = $env:SENTINEL_ACCESS_REVIEW_HOME
$CodeRoot = $env:SENTINEL_ACCESS_REVIEW_CODE
$pasta = Join-Path $raiz 'dados\execucoes\ServidoresWindows'
$inventario = Join-Path $raiz 'dados\execucoes\Inventario-Evidencias-ServidoresWindows.json'
$modelo = Join-Path $raiz 'modelos\Auditoria Galaxia Servidores Windows - Exemplo.docx'

function Set-ReviewProgress {
    param([Parameter(Mandatory)][string]$Stage, [Parameter(Mandatory)][int]$Percent)
    $target = $env:SENTINEL_ACCESS_REVIEW_PROGRESS_FILE
    if (-not $target) { return }
    try {
        $runtime = [System.IO.Path]::GetFullPath((Join-Path $raiz 'runtime'))
        $resolved = [System.IO.Path]::GetFullPath($target)
        if (-not $resolved.StartsWith($runtime, [System.StringComparison]::OrdinalIgnoreCase)) { return }
        $temporary = "$resolved.$PID.tmp"
        @{stage=$Stage;percent=[Math]::Max(0,[Math]::Min(100,$Percent))} | ConvertTo-Json -Compress | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $resolved -Force
    } catch { }
}

Set-ReviewProgress -Stage 'windows_plan' -Percent 5
if (-not (Test-Path -LiteralPath $modelo)) {
    $modelo = (Get-ChildItem -LiteralPath (Join-Path $raiz 'modelos') -Filter 'Auditoria Gal*xia Servidores Windows - Exemplo.docx' -File | Select-Object -First 1).FullName
}

if (-not $SomenteMontagem) {
    Set-ReviewProgress -Stage 'windows_inventory' -Percent 8
    & (Join-Path $CodeRoot 'auditorias\servidores-windows\scripts\Coletar-AD.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao atualizar a coleta do Active Directory.' }
}
if (-not (Test-Path -LiteralPath $inventario)) { throw 'Inventario de Servidores Windows nao encontrado.' }

$dados = Get-Content -Raw -Encoding UTF8 -LiteralPath $inventario | ConvertFrom-Json
$regionaisPadrao = [System.Collections.Generic.List[string]]::new()
$matriz = $null
foreach ($secao in @($dados.secoes)) {
    $quantidade = @($dados.slots | Where-Object secao -eq $secao.secao).Count
    if ($quantidade -eq 5) { $regionaisPadrao.Add([string]$secao.secao) }
    elseif ($quantidade -eq 7 -and ([string]$secao.secao) -like '*Matriz*') { $matriz = [string]$secao.secao }
}
if (-not $matriz) { throw 'A seção especial de São Paulo Matriz não foi localizada no inventário.' }
$regionaisSelecionadas = if ($Modo -eq 'Reduzido') { @($regionaisPadrao | Select-Object -First 5) } else { @($regionaisPadrao) }
$secoes = @($regionaisSelecionadas + @($matriz))
$slotsIniciais = @($dados.slots | Where-Object {
    $_.secao -eq 'Rede Galaxia e grupos principais'
} | Select-Object -ExpandProperty slot)
$slotsRegionais = @($dados.slots | Where-Object { $_.secao -in $secoes } | Select-Object -ExpandProperty slot)
$secoesCaptura = @($secoes)
$slotsCaptura = @($slotsIniciais + $slotsRegionais)
$executarBlocoInicial = $true
$executarServerManager = $true
if ($RetomarFalhas) {
    $resultadoAnterior = Join-Path $pasta ("Resultado-Teste-{0}.json" -f $Modo)
    if (-not (Test-Path -LiteralPath $resultadoAnterior)) {
        throw "Resultado anterior não encontrado para retomada: $resultadoAnterior"
    }
    $anterior = Get-Content -Raw -Encoding UTF8 -LiteralPath $resultadoAnterior | ConvertFrom-Json
    $falhasAnteriores = @($anterior.etapas.psobject.Properties | Where-Object { [string]$_.Value -like 'FALHA*' } | Select-Object -ExpandProperty Name)
    $executarBlocoInicial = 'Bloco inicial' -in $falhasAnteriores
    $executarServerManager = 'Server Manager' -in $falhasAnteriores
    $secoesCaptura = @($secoes | Where-Object { $_ -in $falhasAnteriores })
    $slotsCaptura = @($dados.slots | Where-Object { $_.secao -in $secoesCaptura } | Select-Object -ExpandProperty slot)
    if ($executarBlocoInicial) {
        $slotsCaptura = @($slotsIniciais | Where-Object { $_ -notin @('p007_1', 'p008_1') }) + $slotsCaptura
    }
    if ($executarServerManager) { $slotsCaptura = @('p007_1', 'p008_1') + $slotsCaptura }
    if (-not $executarBlocoInicial -and -not $executarServerManager -and $secoesCaptura.Count -eq 0) {
        throw 'O resultado anterior não possui etapas com falha para retomar.'
    }
}
$plano = [ordered]@{
    auditoria = 'Servidores Windows'
    modo = $Modo
    criado_em = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
    secoes = $secoes
    slots = @($slotsIniciais + $slotsRegionais)
    retomar_falhas = [bool]$RetomarFalhas
    preservar_evidencias_existentes = [bool]$RetomarFalhas
    executar_bloco_inicial = [bool]$executarBlocoInicial
    executar_server_manager = [bool]$executarServerManager
    secoes_captura = $secoesCaptura
    slots_captura = $slotsCaptura
    slots_obsoletos = @($dados.slots_omitidos)
    exclusoes_atuais = @()
}
New-Item -ItemType Directory -Path $pasta -Force | Out-Null
$planoPath = Join-Path $pasta ("Plano-Teste-{0}.json" -f $Modo)
$plano | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $planoPath -Encoding UTF8

$codigoCaptura = 0
if (-not $SomenteMontagem) {
    $worker = Join-Path $PSScriptRoot 'Executar-LoteServidoresWindows.ps1'
    Set-ReviewProgress -Stage 'windows_capture' -Percent 12
    $argumentos = "-NoProfile -ExecutionPolicy Bypass -File `"$worker`" -Plano `"$planoPath`""
    $processo = Start-Process -FilePath "$PSHOME\powershell.exe" -ArgumentList $argumentos -WindowStyle Hidden -Wait -PassThru
    $codigoCaptura = $processo.ExitCode
    if ($codigoCaptura -eq 25) { throw 'Revisao AD encerrada por cinco regionais consecutivas com falha.' }

    if ($RetomarFalhas) {
        $resultadoBasePath = Join-Path $pasta ("Resultado-Teste-{0}.json" -f $Modo)
        $resultadoRetomadaPath = Join-Path $pasta ("Resultado-Retomada-{0}.json" -f $Modo)
        if (Test-Path -LiteralPath $resultadoRetomadaPath) {
            $resultadoBase = Get-Content -Raw -Encoding UTF8 -LiteralPath $resultadoBasePath | ConvertFrom-Json
            $resultadoRetomada = Get-Content -Raw -Encoding UTF8 -LiteralPath $resultadoRetomadaPath | ConvertFrom-Json
            foreach ($etapa in $resultadoRetomada.etapas.psobject.Properties) {
                $existente = $resultadoBase.etapas.psobject.Properties[$etapa.Name]
                if ($null -ne $existente) { $existente.Value = $etapa.Value }
                else { $resultadoBase.etapas | Add-Member -NotePropertyName $etapa.Name -NotePropertyValue $etapa.Value }
            }
            $resultadoBase.falhas = @($resultadoBase.etapas.psobject.Properties | Where-Object { [string]$_.Value -like 'FALHA*' }).Count
            $resultadoBase.concluido_em = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
            $resultadoBase | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultadoBasePath -Encoding UTF8
        }
    }

    $python = $env:SENTINEL_ACCESS_REVIEW_PYTHON
    Set-ReviewProgress -Stage 'windows_inventory' -Percent 80
    & $python (Join-Path $PSScriptRoot 'gerar_inventario_evidencias.py') $modelo (Join-Path $pasta 'Coleta-ServidoresWindows.json')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao atualizar o inventario depois das capturas.' }
}

$saida = Join-Path $pasta ("Auditoria Galaxia Servidores Windows - Teste {0}.docx" -f $Modo)
if (-not $SomenteMontagem -and $codigoCaptura -eq 0 -and $env:SENTINEL_ACCESS_REVIEW_PROGRESS_FILE) {
    Set-Content -LiteralPath ($env:SENTINEL_ACCESS_REVIEW_PROGRESS_FILE + '.collected') -Value 'OK' -Encoding ASCII
}
$python = $env:SENTINEL_ACCESS_REVIEW_PYTHON
Set-ReviewProgress -Stage 'assembling' -Percent 86
& $python (Join-Path $CodeRoot 'src\render_servidores_windows_template.py') $modelo $inventario $saida --sections-file $planoPath
if ($LASTEXITCODE -ne 0) { throw 'Falha ao montar o documento de teste.' }
Set-ReviewProgress -Stage 'assembled' -Percent 96

$resumo = [ordered]@{
    auditoria = 'Servidores Windows'
    modo = $Modo
    somente_montagem = [bool]$SomenteMontagem
    documento = $saida
    plano = $planoPath
    secoes_testadas = $secoes.Count
    regionais_padrao_testadas = $regionaisSelecionadas.Count
    sao_paulo_matriz_testada = $true
    slots_planejados = @($plano.slots).Count
    secoes_capturadas_nesta_execucao = $secoesCaptura.Count
    slots_capturados_nesta_execucao = $slotsCaptura.Count
    retomada_de_falhas = [bool]$RetomarFalhas
    codigo_captura = $codigoCaptura
    concluido_em = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
}
$tipoResumo = if ($SomenteMontagem -and $RetomarFalhas) { 'Montagem-Retomada' } elseif ($SomenteMontagem) { 'Montagem' } elseif ($RetomarFalhas) { 'Retomada' } else { 'Teste' }
$resumoPath = Join-Path $pasta ("Resumo-{0}-{1}.json" -f $tipoResumo, $Modo)
$resumo | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resumoPath -Encoding UTF8
$resumo
if ($codigoCaptura -ne 0) {
    $arquivoResultado = if ($RetomarFalhas) { "Resultado-Retomada-$Modo.json" } else { "Resultado-Teste-$Modo.json" }
    throw "O documento foi montado, mas houve falhas na captura. Consulte $arquivoResultado."
}
