[CmdletBinding()]
param([Parameter(Mandatory)][ValidateSet('windows','linux','admanager','firewalls')][string]$Area,[switch]$SomenteMontagem)
$ErrorActionPreference = 'Stop'
$Root = $env:SENTINEL_ACCESS_REVIEW_HOME
$CodeRoot = $env:SENTINEL_ACCESS_REVIEW_CODE
$Python = $env:SENTINEL_ACCESS_REVIEW_PYTHON
if (-not $Root -or -not $CodeRoot -or -not $Python) { throw 'Contexto da Revisao de Acessos ausente.' }

function Set-ReviewProgress {
    param([Parameter(Mandatory)][string]$Stage, [Parameter(Mandatory)][int]$Percent)
    $target = $env:SENTINEL_ACCESS_REVIEW_PROGRESS_FILE
    if (-not $target) { return }
    try {
        $runtime = [System.IO.Path]::GetFullPath((Join-Path $Root 'runtime'))
        $resolved = [System.IO.Path]::GetFullPath($target)
        if (-not $resolved.StartsWith($runtime, [System.StringComparison]::OrdinalIgnoreCase)) { return }
        $temporary = "$resolved.$PID.tmp"
        @{stage=$Stage;percent=[Math]::Max(0,[Math]::Min(100,$Percent))} | ConvertTo-Json -Compress | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $resolved -Force
    } catch { }
}

Set-ReviewProgress -Stage 'preparing' -Percent 3
if ($Area -eq 'windows') {
    & (Join-Path $CodeRoot 'src\Testar-ServidoresWindows.ps1') -Modo Completo -SomenteMontagem:$SomenteMontagem
    return
}
$Names = @{linux='Linux';admanager='ADManager';firewalls='Firewalls'}
$Name = $Names[$Area]
$Evidence = Join-Path $Root "dados\evidencias\$Name"
$OutputDir = Join-Path $Root "dados\execucoes\$Name"
New-Item -ItemType Directory -Path $Evidence,$OutputDir -Force | Out-Null
if (-not $SomenteMontagem) {
    Set-ReviewProgress -Stage 'collecting' -Percent 12
    & $Python (Join-Path $CodeRoot "src\auditoria_${Area}_web.py") '--config' (Join-Path $Root "config\$Area.json") '--credentials' (Join-Path $Root 'credentials\credentials.json') '--output' $Evidence
    if ($LASTEXITCODE -ne 0) { throw 'A coleta de evidencias falhou.' }
    Set-ReviewProgress -Stage 'collected' -Percent 78
    if ($env:SENTINEL_ACCESS_REVIEW_PROGRESS_FILE) { Set-Content -LiteralPath ($env:SENTINEL_ACCESS_REVIEW_PROGRESS_FILE + '.collected') -Value 'OK' -Encoding ASCII }
}
$ModelName = @{linux='Auditoria Galaxia Linux - Exemplo.docx';admanager='Auditoria Galaxia ADManager - Exemplo.docx';firewalls='Auditoria Galaxia Firewalls - Exemplo.docx'}[$Area]
$Model = Join-Path $Root "modelos\$ModelName"
$Output = Join-Path $OutputDir ("Revisao-$Area-" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.docx')
$RenderArgs = @((Join-Path $CodeRoot "src\render_auditoria_$Area.py"),$Model,$Evidence,$Output)
if ($Area -eq 'firewalls') { $RenderArgs += @('--result',(Join-Path $OutputDir 'Resultado-AuditoriaFirewalls.json')) }
Set-ReviewProgress -Stage 'assembling' -Percent 84
& $Python @RenderArgs
if ($LASTEXITCODE -ne 0) { throw 'A montagem do documento falhou.' }
Set-ReviewProgress -Stage 'assembled' -Percent 96
