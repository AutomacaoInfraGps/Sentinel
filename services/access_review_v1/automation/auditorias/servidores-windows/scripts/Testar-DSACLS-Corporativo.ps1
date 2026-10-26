[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot
$CodeRoot = $env:SENTINEL_ACCESS_REVIEW_CODE
$python = $env:SENTINEL_ACCESS_REVIEW_PYTHON
$bot = Join-Path $CodeRoot 'src\console_bot.py'

foreach ($slot in @('p040_1', 'p541_1')) {
    & $python $bot DSACLS GGS_Suporte_Corporativo $slot
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao gerar a evidência DSACLS $slot."
    }
}
