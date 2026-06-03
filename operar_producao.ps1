param(
    [ValidateSet("status", "restart", "open")]
    [string]$Action = "status",

    [string]$ProdDir = "C:\Automacao",
    [int]$Port = 5000,
    [string]$PublicBase = "C:\Users\Public\Automacao"
)

$ErrorActionPreference = "Stop"

function Test-ProdHealth {
    try {
        $response = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/test" -f $Port) -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        return $response.StatusCode
    } catch {
        return $null
    }
}

function Show-ProdStatus {
    $statusCode = Test-ProdHealth
    Write-Host "Producao"
    Write-Host ("- Pasta: {0}" -f $ProdDir)
    Write-Host ("- Porta: {0}" -f $Port)
    Write-Host ("- Base publica: {0}" -f $PublicBase)
    if ($statusCode) {
        Write-Host ("- Healthcheck: HTTP {0}" -f $statusCode)
        Write-Host ("- URL: http://localhost:{0}" -f $Port)
    } else {
        Write-Host "- Healthcheck: indisponivel"
    }
}

if (-not (Test-Path $ProdDir)) {
    throw "Pasta da producao nao encontrada: $ProdDir"
}

switch ($Action) {
    "status" {
        Show-ProdStatus
    }
    "restart" {
        Push-Location $ProdDir
        try {
            powershell -ExecutionPolicy Bypass -File .\restart_web_service.ps1 -Port $Port -PublicBase $PublicBase
        } finally {
            Pop-Location
        }
        Show-ProdStatus
    }
    "open" {
        Start-Process ("http://localhost:{0}" -f $Port)
        Show-ProdStatus
    }
}