[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ArquivoRelatorio,
    [Parameter(Mandatory)][string]$SinalConclusao
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$grupo = 'GGS_Suporte_Corporativo'
$comando = 'dsacls "OU=Regionais,DC=galaxia,DC=local" | findstr /i "GGS_Suporte_Corporativo"'
$Host.UI.RawUI.WindowTitle = "Auditoria DSACLS - $grupo"

Write-Host "PS $((Get-Location).Path)> $comando" -ForegroundColor Cyan
Write-Host ''

$resultado = @(dsacls "OU=Regionais,DC=galaxia,DC=local" 2>&1 |
    findstr /i "GGS_Suporte_Corporativo" |
    ForEach-Object { $_.ToString() })
$codigo = $LASTEXITCODE

foreach ($linha in $resultado) {
    Write-Host $linha
}

$pastaRelatorio = Split-Path -Parent $ArquivoRelatorio
if ($pastaRelatorio) {
    New-Item -ItemType Directory -Path $pastaRelatorio -Force | Out-Null
}
@($comando, '') + $resultado | Set-Content -LiteralPath $ArquivoRelatorio -Encoding UTF8

if ($codigo -ne 0 -or $resultado.Count -eq 0) {
    $mensagem = "FALHA: dsacls/findstr retornou código $codigo e $($resultado.Count) linha(s)."
    Write-Host ''
    Write-Host $mensagem -ForegroundColor Red
    Set-Content -LiteralPath $SinalConclusao -Value $mensagem -Encoding ASCII
}
else {
    Set-Content -LiteralPath $SinalConclusao -Value 'CONCLUIDO' -Encoding ASCII
}
