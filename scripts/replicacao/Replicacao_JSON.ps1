# Script para capturar a saída do repadmin /replsummary e converter para JSON
# Autor: Assistente IA
# Data: 24/07/2025

# Define o caminho do arquivo JSON
$jsonPath = "$env:USERPROFILE\Desktop\Automação\data\replicacao.json"

# Cria o diretório data se não existir
$dataDir = "$env:USERPROFILE\Desktop\Automação\data"
if (-not (Test-Path -Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
}

# Executa o comando repadmin e captura a saída completa
Write-Host "Executando repadmin /replsummary..."
$output = repadmin /replsummary | Out-String

# Salva a saída bruta para debug
$rawOutputPath = "$dataDir\repadmin_raw.txt"
$output | Out-File -FilePath $rawOutputPath -Encoding utf8
Write-Host "Saída bruta salva em: $rawOutputPath"

# Processa a saída
Write-Host "Processando saída..."

# Lista para armazenar os dados
$servidores = @()
$errosOperacionais = @()
$linhasProcessadas = 0
$servidoresEncontrados = 0

# Divide a saída em linhas
$linhas = $output -split "`r`n"

# Flags para indicar qual seção estamos processando
$processandoOrigem = $false
$processandoDestino = $false

foreach ($linha in $linhas) {
    $linhasProcessadas++
    
    # Captura os erros operacionais
    if ($linha -match "^\s*(\d+)\s+-\s+(.+)") {
        $codigo = $matches[1]
        $servidor = $matches[2]
        $errosOperacionais += "$codigo - $servidor"
        continue
    }
    
    # Identifica o início da seção de origem
    if ($linha -match "DSA Origem\s+.*") {
        $processandoOrigem = $true
        $processandoDestino = $false
        continue
    }
    
    # Identifica o início da seção de destino
    if ($linha -match "DSA Destino\s+.*") {
        $processandoOrigem = $false
        $processandoDestino = $true
        continue
    }
    
    # Processa servidores de origem
    if ($processandoOrigem -and $linha -match "^\s*(\S+)\s+(\S+)\s+(\d+)\s+\/\s+(\d+)\s+(\d+)(?:\s+(.+))?") {
        $servidoresEncontrados++
        $dsa = $matches[1]
        $delta = $matches[2]
        $falhas = [int]$matches[3]
        $total = [int]$matches[4]
        $porcentagem = [int]$matches[5]
        $erro = if ($matches.Count -gt 6) { $matches[6] } else { "" }
        
        # Determina o status
        $status = if ($falhas -eq 0) { "OK" } elseif ($falhas -lt 3) { "Warning" } else { "Error" }
        
        # Cria detalhes
        $detalhes = if ($erro) { $erro } else { "" }
        
        # Adiciona à lista de servidores
        $servidores += [PSCustomObject]@{
            nome = "$dsa.Galaxia.local"
            status = $status
            parceiros = $total
            falhas = $falhas
            erros = $falhas
            replicacoes = $total
            ultima_replicacao = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            detalhes = $detalhes
            delta = $delta
            tipo = "Origem"
        }
    }
    
    # Processa servidores de destino
    if ($processandoDestino -and $linha -match "^\s*(\S+)\s+(\S+)\s+(\d+)\s+\/\s+(\d+)\s+(\d+)(?:\s+(.+))?") {
        $servidoresEncontrados++
        $dsa = $matches[1]
        $delta = $matches[2]
        $falhas = [int]$matches[3]
        $total = [int]$matches[4]
        $porcentagem = [int]$matches[5]
        $erro = if ($matches.Count -gt 6) { $matches[6] } else { "" }
        
        # Determina o status
        $status = if ($falhas -eq 0) { "OK" } elseif ($falhas -lt 3) { "Warning" } else { "Error" }
        
        # Cria detalhes
        $detalhes = if ($erro) { $erro } else { "" }
        
        # Adiciona à lista de servidores
        $servidores += [PSCustomObject]@{
            nome = "$dsa.Galaxia.local"
            status = $status
            parceiros = $total
            falhas = $falhas
            erros = $falhas
            replicacoes = $total
            ultima_replicacao = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            detalhes = $detalhes
            delta = $delta
            tipo = "Destino"
        }
    }
}

Write-Host "Linhas processadas: $linhasProcessadas"
Write-Host "Servidores encontrados: $servidoresEncontrados"
Write-Host "Erros operacionais encontrados: $($errosOperacionais.Count)"

# Se não encontrou servidores, adiciona um servidor de exemplo
if ($servidores.Count -eq 0) {
    Write-Host "AVISO: Nenhum servidor encontrado. Adicionando servidor de exemplo."
    $servidores += [PSCustomObject]@{
        nome = "EXEMPLO.GALAXIA.LOCAL"
        status = "Warning"
        parceiros = 0
        falhas = 0
        erros = 0
        replicacoes = 0
        ultima_replicacao = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
        detalhes = "Não foi possível obter dados reais dos servidores. Verifique os erros operacionais."
        delta = "00m:00s"
        tipo = "Exemplo"
    }
}

# Cria o objeto de dados
$replicacaoData = @{
    timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
    total_servidores = $servidores.Count
    servidores_saudaveis = ($servidores | Where-Object { $_.status -eq "OK" }).Count
    servidores_problemas = ($servidores | Where-Object { $_.status -ne "OK" }).Count
    servidores = $servidores
    erros_operacionais = $errosOperacionais
}

# Converte para JSON e salva
$jsonContent = $replicacaoData | ConvertTo-Json -Depth 4
$jsonContent | Out-File -FilePath $jsonPath -Encoding utf8
Write-Host "Dados JSON salvos em: $jsonPath"

# Retorna sucesso
exit 0