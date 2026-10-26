[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OU,
    [Parameter(Mandatory)][string]$Grupo,
    [string]$PastaRelatorio = '',
    [string]$SinalConclusao = ''
)

Import-Module ActiveDirectory -ErrorAction Stop
try { $Host.UI.RawUI.WindowTitle = "Auditoria Allow - $Grupo" } catch {}

# ============================================================
# PARÂMETROS E SAÍDA
# ============================================================

if (-not $PastaRelatorio) {
    $PastaRelatorio = Join-Path $PSScriptRoot 'dados\execucoes\ServidoresWindows\Allow'
}
$PastaRelatorio = [System.IO.Path]::GetFullPath($PastaRelatorio)
New-Item -ItemType Directory -Path $PastaRelatorio -Force | Out-Null
$NomeOu = (($OU -split ',')[0] -replace '^OU=', '') -replace '[\\/:*?"<>|]', '_'
$NomeGrupo = $Grupo -replace '[\\/:*?"<>|]', '_'
$ArquivoRelatorio = Join-Path $PastaRelatorio "Permissoes_${NomeOu}_${NomeGrupo}.txt"
Start-Transcript -Path $ArquivoRelatorio -Force | Out-Null

# ============================================================
# LIMPA A TELA
# ============================================================

Clear-Host

# ============================================================
# CABEÇALHO
# ============================================================

Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host "RELATÓRIO DE DELEGAÇÃO E MEMBROS - $($Grupo.ToUpper())" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host ""

# ============================================================
# PERMISSÕES DELEGADAS
# ============================================================

Write-Host "Permissões delegadas ao grupo $Grupo na OU:" -ForegroundColor Cyan

try {
    $ResultadoDSACLS = dsacls "$OU" 2>&1

    $PermissoesFiltradas = $ResultadoDSACLS |
        Where-Object {
            $_ -match [regex]::Escape($Grupo)
        }

    if ($PermissoesFiltradas) {
        foreach ($Permissao in $PermissoesFiltradas) {
            Write-Host $Permissao
        }
    }
    else {
        Write-Host "Nenhuma permissão encontrada para este grupo nesta OU." `
            -ForegroundColor Red
    }
}
catch {
    Write-Host "Erro ao consultar as permissões da OU." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

# ============================================================
# MEMBROS DO GRUPO
# ============================================================

Write-Host ""
Write-Host "[Membros do Grupo: $Grupo]" -ForegroundColor Cyan

try {
    $Membros = Get-ADGroupMember `
        -Identity $Grupo `
        -Recursive `
        -ErrorAction Stop |
        Where-Object {
            $_.ObjectClass -eq "user"
        } |
        Sort-Object Name

    if ($Membros) {
        foreach ($Membro in $Membros) {

            $Nome = $Membro.Name
            $Login = $Membro.SamAccountName
            $Tipo = $Membro.ObjectClass

            try {
                $Usuario = Get-ADUser `
                    -Identity $Membro.DistinguishedName `
                    -Properties DisplayName `
                    -ErrorAction Stop

                if (-not [string]::IsNullOrWhiteSpace($Usuario.DisplayName)) {
                    $Nome = $Usuario.DisplayName
                }
            }
            catch {
                $Nome = $Membro.Name
            }

            Write-Host "Nome: $Nome | Login: $Login | Tipo: $Tipo"
        }
    }
    else {
        Write-Host "O grupo não possui usuários." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "Erro ao listar membros do grupo $Grupo." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Yellow
Stop-Transcript | Out-Null
Write-Host "Relatório salvo em: $ArquivoRelatorio" -ForegroundColor Green
if ($SinalConclusao) {
    Set-Content -LiteralPath $SinalConclusao -Value 'CONCLUIDO' -Encoding ASCII
}
