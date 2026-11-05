[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateRange(1, 2)][int]$Parte,
    [Parameter(Mandatory)][string]$SinalConclusao
)

$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory -ErrorAction Stop
try { $Host.UI.RawUI.WindowTitle = "Auditoria Usuarios Apoio - Parte $Parte" } catch {}
Clear-Host

try {
    $usuarios = @(Get-ADGroupMember -Identity 'GGS_Computadores_Dominio' -Recursive -ErrorAction Stop |
        Where-Object { $_.ObjectClass -eq 'user' } |
        Sort-Object SamAccountName -Unique)
    $metade = [Math]::Ceiling($usuarios.Count / 2)
    $inicio = if ($Parte -eq 1) { 0 } else { $metade }
    $fim = if ($Parte -eq 1) { $metade } else { $usuarios.Count }
    Write-Host "GGS_Computadores_Dominio | Parte ${Parte}/2 | total: $($usuarios.Count) | exibidos: $($fim - $inicio)" -ForegroundColor Yellow
    for ($indice = $inicio; $indice -lt $fim; $indice++) {
        $usuario = $usuarios[$indice]
        Write-Host ('{0,3}. {1} | Login: {2}' -f ($indice + 1), $usuario.Name, $usuario.SamAccountName)
    }
    if ($fim -eq $inicio) { Write-Host 'Nenhum usuario nesta parte.' -ForegroundColor Yellow }
    Write-Host 'Consulta concluida.' -ForegroundColor Green
    Set-Content -LiteralPath $SinalConclusao -Value 'CONCLUIDO' -Encoding ASCII
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Set-Content -LiteralPath $SinalConclusao -Value 'ERRO' -Encoding ASCII
}
