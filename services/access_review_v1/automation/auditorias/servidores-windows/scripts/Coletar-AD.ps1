<##
.SYNOPSIS
    Coleta dados de leitura do AD e gera um rascunho da auditoria de servidores Windows.
.DESCRIPTION
    O documento gerado distingue dados consultados no AD das capturas de tela pendentes.
    Nenhuma configuração do domínio é alterada. Requer RSAT ActiveDirectory e Python 3.
.EXAMPLE
    .\Gerar-AuditoriaServidoresWindows.ps1
.EXAMPLE
    .\Gerar-AuditoriaServidoresWindows.ps1 -PastaSaida .\Autodados\evidencias\2026\Out\ANTES\Redes
##>
[CmdletBinding()]
param(
    [string]$PastaSaida = '',
    [string]$OuRegionais = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory -ErrorAction Stop

$ProjectRoot = $env:SENTINEL_ACCESS_REVIEW_HOME
$CodeRoot = $env:SENTINEL_ACCESS_REVIEW_CODE
if (-not $PastaSaida) { $PastaSaida = Join-Path $ProjectRoot 'dados\execucoes\ServidoresWindows' }

$dominio = Get-ADDomain -ErrorAction Stop
if (-not $OuRegionais) {
    $OuRegionais = 'OU=Regionais,' + $dominio.DistinguishedName
}
$null = Get-ADOrganizationalUnit -Identity $OuRegionais -ErrorAction Stop
$PastaSaida = [System.IO.Path]::GetFullPath($PastaSaida)
New-Item -ItemType Directory -Path $PastaSaida -Force | Out-Null
$instante = Get-Date
$falhas = [System.Collections.Generic.List[string]]::new()
$usuariosPorDn = @{}

function Consultar-Grupo {
    param([Microsoft.ActiveDirectory.Management.ADGroup]$Grupo)
    $diretos = @()
    $ativos = @()
    try {
        $diretos = @(Get-ADGroupMember -Identity $Grupo.DistinguishedName -ErrorAction Stop |
            Sort-Object ObjectClass, Name |
            ForEach-Object {
                [pscustomobject]@{ Nome = $_.Name; Login = $_.SamAccountName; Tipo = $_.ObjectClass }
            })
        # Grupos de bloqueio são compostos por grupos de suporte; seus membros
        # diretos já são a evidência relevante e evitam expansão redundante.
        if ($Grupo.Name -notlike 'GGS_Bloqueio_*') {
            $usuarios = @(Get-ADGroupMember -Identity $Grupo.DistinguishedName -Recursive -ErrorAction Stop |
                Where-Object ObjectClass -eq 'user' | Sort-Object DistinguishedName -Unique)
            foreach ($item in $usuarios) {
                if (-not $usuariosPorDn.ContainsKey($item.DistinguishedName)) {
                    $usuariosPorDn[$item.DistinguishedName] = Get-ADUser -Identity $item.DistinguishedName -Properties DisplayName, Enabled -ErrorAction Stop
                }
                $usuario = $usuariosPorDn[$item.DistinguishedName]
                if ($usuario.Enabled) {
                    $ativos += [pscustomobject]@{
                        Nome = if ($usuario.DisplayName) { $usuario.DisplayName } else { $usuario.Name }
                        Login = $usuario.SamAccountName
                    }
                }
            }
        }
        $ativos = @($ativos | Sort-Object Login)
    }
    catch {
        $falhas.Add("Grupo $($Grupo.Name): $($_.Exception.Message)")
    }
    [pscustomobject]@{
        Nome = $Grupo.Name
        DN = $Grupo.DistinguishedName
        MembrosDiretos = $diretos
        UsuariosAtivos = $ativos
    }
}

$nomesPrincipais = @('Domain Admins', 'Administrators', 'Account Operators',
    'GGS_Suporte_Corporativo', 'GGS_Computadores_Dominio')
$gruposPorDn = @{}
foreach ($nome in $nomesPrincipais) {
    try {
        $grupo = Get-ADGroup -Identity $nome -ErrorAction Stop
        $gruposPorDn[$grupo.DistinguishedName] = $grupo
    }
    catch { $falhas.Add("Grupo principal ${nome}: $($_.Exception.Message)") }
}
try {
    $regionais = @(Get-ADGroup -LDAPFilter '(|(cn=GGS_Suporte_*)(cn=GGS_Bloqueio_*))' -ErrorAction Stop)
    foreach ($grupo in $regionais) { $gruposPorDn[$grupo.DistinguishedName] = $grupo }
}
catch { $falhas.Add("Busca de grupos regionais: $($_.Exception.Message)") }

$grupos = @($gruposPorDn.Values | Sort-Object Name | ForEach-Object { Consultar-Grupo $_ })
Write-Output "Grupos consultados: $($grupos.Count)"
$gruposPorNome = @{}
foreach ($grupo in $grupos) { $gruposPorNome[$grupo.Nome.ToLowerInvariant()] = $grupo }

$ous = @()
try {
    # Consulta toda a subárvore. A identificação de uma filial é feita depois
    # pelas ACLs e grupos GGS explícitos, sem lista fixa de estados ou cidades.
    $ous = @(Get-ADOrganizationalUnit -SearchBase $OuRegionais -SearchScope Subtree -Filter * -ErrorAction Stop |
        Where-Object { $_.Name -notin @('Block_Rev_Acesso', 'Computadores', 'Demitidos') } |
        Sort-Object DistinguishedName)
}
catch { $falhas.Add("Inventário de OUs: $($_.Exception.Message)") }

$dadosOus = @()
foreach ($ou in $ous) {
    $regras = @()
    try {
        $acl = Get-Acl -Path ('AD:\' + $ou.DistinguishedName) -ErrorAction Stop
        $regras = @($acl.Access | Where-Object {
            $_.IdentityReference.Value -match '(?i)GGS_|Domain Admins'
        } | ForEach-Object {
            [pscustomobject]@{
                Principal = $_.IdentityReference.Value
                Tipo = [string]$_.AccessControlType
                Direitos = [string]$_.ActiveDirectoryRights
                Herdada = [bool]$_.IsInherited
                Abrangencia = [string]$_.InheritanceType
            }
        } | Sort-Object Principal, Direitos -Unique)
    }
    catch { $falhas.Add("ACL da OU $($ou.DistinguishedName): $($_.Exception.Message)") }
    $associados = @($regras | Where-Object { -not $_.Herdada } | ForEach-Object {
        ($_.Principal -split '\\')[-1].ToLowerInvariant()
    } | Sort-Object -Unique | Where-Object {
        $gruposPorNome.ContainsKey($_) -and $_ -match '^ggs_' -and
        $_ -notin @('ggs_suporte_corporativo', 'ggs_computadores_dominio')
    })
    $dadosOus += [pscustomobject]@{
        Nome = $ou.Name
        DN = $ou.DistinguishedName
        Regras = $regras
        GruposAssociados = @($associados | ForEach-Object { $gruposPorNome[$_].Nome })
    }
}
Write-Output "OUs consultadas: $($dadosOus.Count)"

$dados = [pscustomobject]@{
    ColetadoEm = $instante.ToString('yyyy-MM-dd HH:mm:ss zzz')
    Dominio = $dominio.DNSRoot
    OuRegionais = $OuRegionais
    Grupos = $grupos
    OUs = $dadosOus
    Falhas = @($falhas)
}
$json = Join-Path $PastaSaida 'Coleta-ServidoresWindows.json'
$dados | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $json -Encoding UTF8

$python = [pscustomobject]@{Source=$env:SENTINEL_ACCESS_REVIEW_PYTHON}
$modelo = Join-Path $ProjectRoot 'modelos\Auditoria Galaxia Servidores Windows - Exemplo.docx'
$inventario = Join-Path $ProjectRoot 'dados\execucoes\Inventario-Evidencias-ServidoresWindows.json'
& $python.Source (Join-Path $CodeRoot 'src\gerar_inventario_evidencias.py') $modelo $json
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o inventário de evidências.' }
$docx = Join-Path $PastaSaida 'Auditoria Galaxia Servidores Windows - Rascunho Visual.docx'
& $python.Source (Join-Path $CodeRoot 'src\render_servidores_windows_template.py') $modelo $inventario $docx
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o DOCX.' }

Write-Output ([pscustomobject]@{
    Documento = $docx
    Dados = $json
    Grupos = $grupos.Count
    OUs = $dadosOus.Count
    Falhas = $falhas.Count
})
