param(
    [ValidateSet("status", "restart", "open")]
    [string]$Action = "status",

    [string]$HmlDir = "C:\Sentinel\hml",
    [int]$Port = 5001,
    [string]$PublicBase = "C:\Users\Public\Automacao-HML"
)

$ErrorActionPreference = "Stop"

function Test-HmlHealth {
    try {
        $response = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/test" -f $Port) -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        return $response.StatusCode
    } catch {
        return $null
    }
}

function Show-HmlStatus {
    $statusCode = Test-HmlHealth
    Write-Host "Homologacao"
    Write-Host ("- Pasta: {0}" -f $HmlDir)
    Write-Host ("- Porta: {0}" -f $Port)
    Write-Host ("- Base publica: {0}" -f $PublicBase)
    if ($statusCode) {
        Write-Host ("- Healthcheck: HTTP {0}" -f $statusCode)
        Write-Host ("- URL: http://localhost:{0}" -f $Port)
    } else {
        Write-Host "- Healthcheck: indisponivel"
    }
}

if (-not (Test-Path $HmlDir)) {
    throw "Pasta da homologacao nao encontrada: $HmlDir"
}

switch ($Action) {
    "status" {
        Show-HmlStatus
    }
    "restart" {
        Push-Location $HmlDir
        try {
            powershell -ExecutionPolicy Bypass -File .\restart_web_service.ps1 -Port $Port -PublicBase $PublicBase
        } finally {
            Pop-Location
        }
        Show-HmlStatus
    }
    "open" {
        Start-Process ("http://localhost:{0}" -f $Port)
        Show-HmlStatus
    }
}