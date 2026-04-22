# Replicacao_Servers.ps1
# Gera JSON + HTML completo + HTML fragmento (para o dashboard) em C:\Users\Public\Automacao

param(
  [string]$BasePublic        = (Join-Path $env:PUBLIC 'Automacao'),
  [string]$JsonPath          = $null,
  [string]$HtmlPath          = $null,
  [string]$HtmlFragmentPath  = $null,
  [switch]$DestOnly          = $true,   # evita duplicidade (usa só a seção Destination DSA)
  [switch]$NoRaw             = $false   # não incluir “Saída bruta” no HTML
)

# [REMOVER]
# Saída bruta (sempre útil para diagnóstico)
# $replRaw = "<h3>Saída bruta (repadmin /replsummary)</h3><pre>" + ($saida -join "`r`n") + "</pre>"


# Caminhos padrão
if (-not $JsonPath)         { $JsonPath         = Join-Path $BasePublic 'data\replicacao.json' }
if (-not $HtmlPath)         { $HtmlPath         = Join-Path $BasePublic 'output\replsummary.html' }
if (-not $HtmlFragmentPath) { $HtmlFragmentPath = Join-Path $BasePublic 'output\replsummary_fragment.html' }

# Cria pastas
$JsonDir = Split-Path -Parent $JsonPath
$HtmlDir = Split-Path -Parent $HtmlPath
$FragDir = Split-Path -Parent $HtmlFragmentPath
New-Item -ItemType Directory -Force -Path $JsonDir | Out-Null
New-Item -ItemType Directory -Force -Path $HtmlDir | Out-Null
New-Item -ItemType Directory -Force -Path $FragDir | Out-Null

Write-Host "JSON:        $JsonPath"
Write-Host "HTML:        $HtmlPath"
Write-Host "HTML (frag): $HtmlFragmentPath"

# Executa repadmin /replsummary
$saida = & repadmin /replsummary 2>&1
if ($null -eq $saida) { $saida = @() }

# Parse
$dados = @()
$errosOperacionais = @()
$secao = ""   # "", "source", "dest"

foreach ($linha in $saida) {

    # Marca seções (para evitar duplicidade)
    if ($linha -match "^\s*Source DSA")      { $secao = "source"; continue }
    if ($linha -match "^\s*Destination DSA") { $secao = "dest";   continue }

    # Erros operacionais (cód. 58 – ajuste se precisar)
    if ($linha -match "^\s*\d+\s+-\s+.+\.[A-Za-z0-9-]+\.local") {
        $errosOperacionais += $linha.Trim()
        continue
    }

    # Ignora linhas vazias
    if ($linha -match "^\s*$") { continue }

    # Se só queremos Destination, pule Source
    if ($DestOnly -and $secao -ne "dest") { continue }

    # Captura: Servidor | Latência | SucessoTotal | Erros
    if ($linha -match "^\s*(\S+)\s+([\d\.:hms]+)\s+(\d+\s*/\s*\d+)?\s+(\d+)\s*$") {
        $servidor = $matches[1]
        $latencia = $matches[2]
        $sucesso  = if ($matches[3]) { $matches[3] } else { "0 / 0" }
        $erros    = [int]$matches[4]

        $dados += [PSCustomObject]@{
            Servidor     = $servidor
            'Latência'   = $latencia
            SucessoTotal = $sucesso
            Erros        = $erros
        }
    }
}

# CSS básico (apenas no HTML completo)
$estilo = @"
<style>
body { font-family: Segoe UI, Arial, sans-serif; margin: 16px; }
h2   { color: #0078D7; margin-bottom: 8px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
th { background-color: #dbeafe; color: #000; font-weight: 700; }
tr:nth-child(even) { background-color: #f7f7f7; }
pre { background:#f7f7f7; padding:12px; overflow:auto; }
.erros-operacionais { margin-top: 18px; font-family: monospace; color: #b00; }
.small { color:#666; font-size:12px; margin-bottom:10px; }
</style>
"@

# Table fragment
if ($dados.Count -gt 0) {
    $htmlTabela = $dados | ConvertTo-Html -Property Servidor, 'Latência', SucessoTotal, Erros -Fragment
    # O campo retornado pelo repadmin aqui representa "Falhas/Total".
    $htmlTabela = $htmlTabela -replace '>SucessoTotal<', '>Falhas/Total<'
} else {
    $htmlTabela = "<div class='small'>Nenhuma linha parseada. Verifique permissões/firewall do repadmin.</div>"
}

# Bloco de erros
$htmlErros = ""
if ($errosOperacionais.Count -gt 0) {
    $htmlErros = "<div class='erros-operacionais'><h3>Erros operacionais:</h3><pre>" +
                 ($errosOperacionais -join "`r`n") + "</pre></div>"
}

# Saída bruta (opcional)
$replRaw = ""
if (-not $NoRaw) {
    $replRaw = "<h3>Saída bruta (repadmin /replsummary)</h3><pre>" + ($saida -join "`r`n") + "</pre>"
}

# Fragmento (para o dashboard): só conteúdo, sem <html> nem CSS
$fragmento = ($htmlTabela + $htmlErros)

# HTML completo (se precisar abrir fora do dashboard)
# Substitua o SEU bloco atual de HTML completo por este (sem $replRaw):
$timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$htmlCompleto = @"
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>Resumo de Replicação AD</title>
$estilo
</head>
<body>
  <h2>Resumo de Replicação AD (repadmin /replsummary)</h2>
  <div class="small">Gerado em: $timestamp</div>
        <div class="small"><strong>Falhas/Total</strong>: número de falhas de replicação sobre o total de parceiros para cada servidor.</div>
  $htmlTabela
  $htmlErros
</body>
</html>
"@


# JSON
$replicacao_ok   = ($dados | Where-Object { $_.Erros -eq 0 }).Count
$replicacao_erro = ($dados | Where-Object { $_.Erros -gt 0 }).Count

$jsonData = [ordered]@{
    timestamp          = (Get-Date).ToString("o")
    controladores      = [int]$dados.Count
    replicacao_ok      = [int]$replicacao_ok
    replicacao_erro    = [int]$replicacao_erro
    erros_operacionais = [int]$errosOperacionais.Count
    status             = if (($replicacao_erro -eq 0) -and ($errosOperacionais.Count -eq 0)) { "ok" } else { "erro" }
    detalhes = @{
        controladores = @(
            $dados | ForEach-Object {
                [ordered]@{
                    nome          = $_.Servidor
                    latencia      = $_.'Latência'
                    sucesso_total = $_.SucessoTotal
                    erros         = $_.Erros
                }
            }
        )
        erros_operacionais = $errosOperacionais
    }
}

# Grava
$jsonData       | ConvertTo-Json -Depth 6 | Out-File -FilePath $JsonPath -Encoding UTF8
$htmlCompleto   | Out-File -FilePath $HtmlPath -Encoding UTF8
$fragmento      | Out-File -FilePath $HtmlFragmentPath -Encoding UTF8

Write-Host "✅ JSON salvo em: $JsonPath"
Write-Host "✅ HTML salvo em: $HtmlPath"
Write-Host "✅ Fragmento salvo em: $HtmlFragmentPath"

# Não abrir navegador se rodando como serviço
if ([Environment]::UserInteractive -and -not $env:AUTOMACAO_SKIP_REPL_BROWSER) {
    Start-Process $HtmlPath
}
