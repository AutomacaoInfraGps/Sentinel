[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Grupo,
    [string]$PastaRelatorio = '',
    [switch]$Compacto,
    [string]$SinalConclusao = ''
)

Import-Module ActiveDirectory -ErrorAction Stop
try { $Host.UI.RawUI.WindowTitle = "Auditoria Deny - $Grupo" } catch {}

# ============================================================
# 1. CONFIGURAÇÕES
# ============================================================

if (-not $PastaRelatorio) {
    $PastaRelatorio = Join-Path $PSScriptRoot 'dados\execucoes\ServidoresWindows\Deny'
}
$PastaRelatorio = [System.IO.Path]::GetFullPath($PastaRelatorio)
$ArquivoRelatorio = Join-Path $PastaRelatorio "Membros_$Grupo.txt"

# Cria a pasta, caso não exista
if (-not (Test-Path -LiteralPath $PastaRelatorio)) {
    New-Item `
        -ItemType Directory `
        -Path $PastaRelatorio `
        -Force |
        Out-Null
}

Clear-Host
$ConsultaBemSucedida = $true

Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "MEMBROS DO GRUPO (USUARIOS E SUBGRUPOS): $Grupo" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""

try {
    # Sem -Recursive: consulta todos os membros diretos, tanto usuários quanto
    # subgrupos, preservando o tipo exibido na evidência.
    $Membros = Get-ADGroupMember `
        -Identity $Grupo `
        -ErrorAction Stop |
        Sort-Object Name

    $Linhas = @()

    if ($Membros) {
        foreach ($Membro in $Membros) {

            $Linha = "Nome: $($Membro.Name) | Login: $($Membro.SamAccountName) | Tipo: $($Membro.ObjectClass)"

            if (-not $Compacto) { Write-Host $Linha -ForegroundColor Gray }
            $Linhas += $Linha
        }
        if ($Compacto) {
            Write-Host 'Membros diretos (nomes em duas colunas):' -ForegroundColor Cyan
            for ($i = 0; $i -lt $Membros.Count; $i += 2) {
                $primeiro = $Membros[$i].Name
                $segundo = if ($i + 1 -lt $Membros.Count) { $Membros[$i + 1].Name } else { '' }
                Write-Host ('{0,-52} {1}' -f $primeiro, $segundo) -ForegroundColor Gray
            }
        }
    }
    else {
        $Linha = "Nenhum usuário ou subgrupo encontrado como membro direto de $Grupo."

        Write-Host $Linha -ForegroundColor Yellow
        $Linhas += $Linha
    }

    $Linhas |
        Set-Content `
            -Path $ArquivoRelatorio `
            -Encoding UTF8

    Write-Host ""
    Write-Host "[OK] Relatório salvo em: $ArquivoRelatorio" -ForegroundColor Green
    Write-Host "Quantidade de membros: $($Membros.Count)" -ForegroundColor Green
}
catch {
    $ConsultaBemSucedida = $false
    Write-Host "Erro ao consultar o grupo $Grupo." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}
if ($SinalConclusao) {
    Set-Content -LiteralPath $SinalConclusao -Value $(if ($ConsultaBemSucedida) { 'CONCLUIDO' } else { 'ERRO' }) -Encoding ASCII
}
