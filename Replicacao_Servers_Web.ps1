# Define o caminho do relatório usando caminho fixo para evitar problemas de encoding
$caminhoRelatorio = "$env:USERPROFILE\Desktop\Automação\output\replsummary.html"
$caminhoJson = "$env:USERPROFILE\Desktop\Automação\data\replicacao_ad.json"
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
    if ($linha -match "^\s*\d+\s+-\s+.+\.[A-Za-z0-9-]+\.local") {
        $errosOperacionais += $linha.Trim()
        continue
    }

    # Captura as linhas de dados dos servidores
    if ($linha -match "^\s*(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)") {
        $dsa = $matches[1]
        $parceiros = [int]$matches[2]
        $falhas = [int]$matches[3]
        $erros = [int]$matches[4]
        $replicacoes = [int]$matches[5]

        $dados += [PSCustomObject]@{
            DSA = $dsa
            Parceiros = $parceiros
            Falhas = $falhas
            Erros = $erros
            Replicacoes = $replicacoes
        }
    }
}

# Cria o HTML
$estiloCSS = @"
<style>
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    margin: 20px;
    background-color: #f5f5f5;
}
h1, h2 {
    color: #0066cc;
}
.container {
    max-width: 1200px;
    margin: 0 auto;
    background-color: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.summary {
    display: flex;
    justify-content: space-between;
    margin-bottom: 20px;
}
.summary-box {
    background-color: #f0f8ff;
    border: 1px solid #d0e4fe;
    border-radius: 5px;
    padding: 15px;
    width: 23%;
    text-align: center;
}
.summary-box.error {
    background-color: #fff0f0;
    border-color: #ffd0d0;
}
.summary-box h3 {
    margin-top: 0;
    color: #333;
}
.summary-box p {
    font-size: 24px;
    font-weight: bold;
    margin: 10px 0 0 0;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 20px;
}
th, td {
    padding: 12px 15px;
    text-align: left;
    border-bottom: 1px solid #ddd;
}
th {
    background-color: #0066cc;
    color: white;
}
tr:nth-child(even) {
    background-color: #f2f2f2;
}
tr:hover {
    background-color: #e6f2ff;
}
.status-ok {
    color: green;
    font-weight: bold;
}
.status-warning {
    color: orange;
    font-weight: bold;
}
.status-error {
    color: red;
    font-weight: bold;
}
.timestamp {
    text-align: right;
    color: #666;
    font-style: italic;
    margin-top: 20px;
}
.error-list {
    background-color: #fff0f0;
    border: 1px solid #ffd0d0;
    border-radius: 5px;
    padding: 15px;
    margin-top: 20px;
}
.error-list h3 {
    color: #cc0000;
    margin-top: 0;
}
.error-list ul {
    margin-bottom: 0;
}
</style>
"@

$htmlConteudo = @"
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Relatório de Replicação do Active Directory</title>
    $estiloCSS
</head>
<body>
    <div class="container">
        <h1>Relatório de Replicação do Active Directory</h1>
        
        <div class="summary">
            <div class="summary-box">
                <h3>Controladores</h3>
                <p>$($dados.Count)</p>
            </div>
            <div class="summary-box">
                <h3>Replicação OK</h3>
                <p>$($dados | Where-Object { $_.Erros -eq 0 }).Count</p>
            </div>
            <div class="summary-box error">
                <h3>Replicação com Erro</h3>
                <p>$($dados | Where-Object { $_.Erros -gt 0 }).Count</p>
            </div>
            <div class="summary-box error">
                <h3>Erros Operacionais</h3>
                <p>$($errosOperacionais.Count)</p>
            </div>
        </div>
        
        <h2>Status dos Controladores de Domínio</h2>
        <table>
            <tr>
                <th>Servidor</th>
                <th>Parceiros</th>
                <th>Falhas</th>
                <th>Erros</th>
                <th>Replicações</th>
                <th>Status</th>
            </tr>
"@

foreach ($servidor in $dados) {
    $statusClass = if ($servidor.Erros -eq 0) { "status-ok" } elseif ($servidor.Erros -lt 3) { "status-warning" } else { "status-error" }
    $statusText = if ($servidor.Erros -eq 0) { "OK" } elseif ($servidor.Erros -lt 3) { "Atenção" } else { "Erro" }
    
    $htmlConteudo += @"
            <tr>
                <td>$($servidor.DSA)</td>
                <td>$($servidor.Parceiros)</td>
                <td>$($servidor.Falhas)</td>
                <td>$($servidor.Erros)</td>
                <td>$($servidor.Replicacoes)</td>
                <td class="$statusClass">$statusText</td>
            </tr>
"@
}

$htmlConteudo += @"
        </table>
"@

if ($errosOperacionais.Count -gt 0) {
    $htmlConteudo += @"
        <div class="error-list">
            <h3>Erros Operacionais Detectados</h3>
            <ul>
"@

    foreach ($erro in $errosOperacionais) {
        $htmlConteudo += @"
                <li>$erro</li>
"@
    }

    $htmlConteudo += @"
            </ul>
        </div>
"@
}

$htmlConteudo += @"
        <div class="timestamp">
            Relatório gerado em: $(Get-Date -Format "dd/MM/yyyy HH:mm:ss")
        </div>
    </div>
</body>
</html>
"@

# Salva o HTML
$htmlConteudo | Out-File -FilePath $caminhoRelatorio -Encoding UTF8
Write-Host "Relatório HTML salvo em: $caminhoRelatorio"

# Prepara os dados para o JSON
$jsonData = @{
    timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    total_servidores = $dados.Count
    servidores_saudaveis = ($dados | Where-Object { $_.Erros -eq 0 }).Count
    servidores_problemas = ($dados | Where-Object { $_.Erros -gt 0 }).Count
    servidores = @()
}

# Adiciona os dados de cada servidor
foreach ($servidor in $dados) {
    $status = if ($servidor.Erros -eq 0) { "OK" } elseif ($servidor.Erros -lt 3) { "Warning" } else { "Error" }
    
    $jsonData.servidores += @{
        nome = $servidor.DSA
        status = $status
        parceiros = $servidor.Parceiros
        falhas = $servidor.Falhas
        erros = $servidor.Erros
        replicacoes = $servidor.Replicacoes
        ultima_replicacao = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
        detalhes = if ($servidor.Erros -gt 0) { "Detectados $($servidor.Erros) erros de replicação" } else { "" }
    }
}

# Exporta o JSON
$jsonData | ConvertTo-Json -Depth 4 | Out-File -FilePath $caminhoJson -Encoding UTF8
Write-Host "Dados JSON salvos em: $caminhoJson"

# NÃO abre o relatório HTML automaticamente
# Removido: Start-Process $caminhoRelatorio

# Retorna sucesso
exit 0