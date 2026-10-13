[CmdletBinding()]
param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
)

$ErrorActionPreference = "Stop"

$projectPath = [IO.Path]::GetFullPath($ProjectDir)
$vaultPath = [IO.Path]::GetFullPath((Join-Path $projectPath ".credentials"))
$expectedPrefix = $projectPath.TrimEnd('\') + '\'
if (-not $vaultPath.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "O caminho do cofre precisa permanecer dentro do projeto."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.User) {
    throw "Nao foi possivel identificar a conta Windows atual."
}

New-Item -ItemType Directory -Force -Path $vaultPath | Out-Null

$inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
$propagation = [Security.AccessControl.PropagationFlags]::None
$allow = [Security.AccessControl.AccessControlType]::Allow
$fullControl = [Security.AccessControl.FileSystemRights]::FullControl

$security = New-Object Security.AccessControl.DirectorySecurity
$security.SetAccessRuleProtection($true, $false)

$allowedSids = @(
    $identity.User,
    (New-Object Security.Principal.SecurityIdentifier("S-1-5-18")),
    (New-Object Security.Principal.SecurityIdentifier("S-1-5-32-544"))
)

foreach ($sid in $allowedSids) {
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        $sid,
        $fullControl,
        $inheritance,
        $propagation,
        $allow
    )
    $security.AddAccessRule($rule)
}

Set-Acl -LiteralPath $vaultPath -AclObject $security

$effectiveRules = (Get-Acl -LiteralPath $vaultPath).Access |
    Select-Object IdentityReference, FileSystemRights, AccessControlType, IsInherited

Write-Host "Cofre preparado em: $vaultPath"
Write-Host "Conta DPAPI atual: $($identity.Name)"
$effectiveRules | Format-Table -AutoSize
