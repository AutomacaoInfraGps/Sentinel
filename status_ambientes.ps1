param(
    [int]$ProdPort = 5000,
    [int]$HmlPort = 5001
)

$ErrorActionPreference = "Stop"

function Get-HealthStatus([int]$Port) {
    try {
        $response = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/test" -f $Port) -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        return "HTTP $($response.StatusCode)"
    } catch {
        return "offline"
    }
}

Write-Host "Ambientes Sentinel"
Write-Host ("- Producao  : porta {0} -> {1}" -f $ProdPort, (Get-HealthStatus -Port $ProdPort))
Write-Host ("- Homologacao: porta {0} -> {1}" -f $HmlPort, (Get-HealthStatus -Port $HmlPort))