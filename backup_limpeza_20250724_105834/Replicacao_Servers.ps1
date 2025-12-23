# Define o caminho do relatório usando caminho fixo para evitar problemas de encoding
$caminhoRelatorio = "$env:USERPROFILE\Desktop\Automação\output\replsummary.html"
$caminhoJson = "$env:USERPROFILE\Desktop\Automação\data\replicacao.json"
Write-Host "Caminho do relatório: $caminhoRelatorio"
Write-Host "Caminho do JSON: $caminhoJson"

# Garante que os diretórios existem
$diretorioRelatorio = Split-Path -Parent $caminhoRelatorio
$diretorioJson = Split-Path -Parent $caminhoJson
if (!(Test-Path $diretorioRelatorio)) {
    New-Item -ItemType Directory -Path $diretorioRelatorio -Force
    Write-Host "Diretório criado: $diretorioRelatorio"
}
if (!(Test-Path $diretorioJson)) {
    New-Item -ItemType Directory -Path $diretorioJson -Force
    Write-Host "Diretório criado: $diretorioJson"
}

# Executa o comando e captura a saída
$saida = repadmin /replsummary 2>&1

# Lista para armazenar os dados
$dados = @()
$errosOperacionais = @()

foreach ($linha in $saida) {
    # Captura os erros operacionais
    if ($linha -match "^\s*\d+\s+-\s+.+\.Galaxia\.local") {
        $errosOperacionais += $linha.Trim()
        continue
    }

    # Ignora cabeçalhos ou linhas em branco
    if ($linha -match "^\s*$" -or $linha -match "^\s*Source DSA") {
        continue
    }

    # Tenta capturar a linha de dados
    if ($linha -match "^\s*(\S+)\s+([\d\.:hms]+)\s+(\d+\s*/\s*\d+)?\s+(\d+)\s*$") {
        $servidor = $matches[1]
        $latencia = $matches[2]
        $sucesso = if ($matches[3]) { $matches[3] } else { "0 / 0" }
        $erros = $matches[4]

        $dados += [PSCustomObject]@{
            Servidor     = $servidor
            Latência     = $latencia
            SucessoTotal = $sucesso
            Erros        = $erros
        }
    }
}

# Estilo CSS
$estilo = @"
<style>
body {
    font-family: Arial, sans-serif;
}
h2 {
    color: #0078D7;
}
table {
    border-collapse: collapse;
    width: 100%;
}
th, td {
    border: 1px solid #ccc;
    padding: 8px;
    text-align: left;
}
th {
    background-color: #0078D7;
    color: white;
}
tr:nth-child(even) {
    background-color: #f2f2f2;
}
.erros-operacionais {
    margin-top: 30px;
    font-family: monospace;
    color: red;
}
</style>
"@

# Gera HTML da tabela principal
$htmlTabela = $dados | ConvertTo-Html -Property Servidor, Latência, SucessoTotal, Erros -Fragment

# Gera bloco de erros operacionais
$htmlErros = ""
if ($errosOperacionais.Count -gt 0) {
    $htmlErros = "<div class='erros-operacionais'><h3>Erros operacionais ao tentar recuperar informações de replicação:</h3><pre>" +
        ($errosOperacionais -join "`r`n") +
        "</pre></div>"
}

# HTML completo
$htmlCompleto = @"
<html>
<head>
    <meta charset="UTF-8">
    <title>Resumo de Replicação AD</title>
    $estilo
</head>
<body>
    <h2>Resumo de Replicação AD (repadmin /replsummary)</h2>
    $htmlTabela
    $htmlErros
</body>
</html>
"@

# Exporta o HTML
$htmlCompleto | Out-File -FilePath $caminhoRelatorio -Encoding UTF8

# Cria objeto JSON com os dados
$jsonData = @{
    timestamp = (Get-Date).ToString("o")
    controladores = $dados.Count
    replicacao_ok = ($dados | Where-Object { $_.Erros -eq 0 }).Count
    replicacao_erro = ($dados | Where-Object { $_.Erros -gt 0 }).Count
    erros_operacionais = $errosOperacionais.Count
    status = if (($dados | Where-Object { $_.Erros -gt 0 }).Count -eq 0 -and $errosOperacionais.Count -eq 0) { "ok" } else { "erro" }
    detalhes = @{
        controladores = $dados | ForEach-Object {
            @{
                nome = $_.DSA
                parceiros = $_.Parceiros
                falhas = $_.Falhas
                erros = $_.Erros
            }
        }
        erros_operacionais = $errosOperacionais
    }
}

# Exporta o JSON
$jsonData | ConvertTo-Json -Depth 4 | Out-File -FilePath $caminhoJson -Encoding UTF8
Write-Host "Dados JSON salvos em: $caminhoJson"

# Abre o relatório HTML
Start-Process $caminhoRelatorio
