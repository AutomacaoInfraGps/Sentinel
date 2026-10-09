param(
    [string]$RemoteHost = "10.254.12.66",
    [string]$RemoteUser = "administrador",
    [int]$LocalPort = 15678,
    [int]$RemotePort = 5678,
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\sofia_celeno_ed25519"
)

$ErrorActionPreference = "Stop"
$ssh = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"

if (-not (Test-Path -LiteralPath $ssh -PathType Leaf)) {
    throw "OpenSSH client not found."
}
if (-not (Test-Path -LiteralPath $IdentityFile -PathType Leaf)) {
    throw "SofIA tunnel identity file not found."
}

while ($true) {
    & $ssh `
        -N `
        -T `
        -i $IdentityFile `
        -o BatchMode=yes `
        -o ExitOnForwardFailure=yes `
        -o ServerAliveInterval=30 `
        -o ServerAliveCountMax=3 `
        -L "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}" `
        "${RemoteUser}@${RemoteHost}"

    Start-Sleep -Seconds 5
}
