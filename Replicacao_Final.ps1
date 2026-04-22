# Script para processar a saída do repadmin /replsummary e gerar JSON
# Autor: Assistente IA
# Data: 24/07/2025

# Define o caminho do arquivo JSON (usando ~ para o perfil do usuário)
$jsonPath = "$env:USERPROFILE\Desktop\replicacao.json"

# Executa o comando repadmin e captura a saída
$output = repadmin /replsummary
$domainSuffix = if ($env:AD_DOMAIN_DNS) { $env:AD_DOMAIN_DNS.ToLower() } else { "dominio.local" }
$domainSuffixPattern = [regex]::Escape($domainSuffix)

# Cria listas para armazenar os dados
$servidores = @()
$errosOperacionais = @()

# Flags para controlar o processamento
$processandoOrigem = $false
$processandoDestino = $false
$processandoErros = $false

# Processa cada linha da saída
foreach ($linha in $output) {
    # Detecta o início da seção de origem
    if ($linha -match "DSA Origem") {
        $processandoOrigem = $true
        $processandoDestino = $false
        $processandoErros = $false
        continue
    }
    
    # Detecta o início da seção de destino
    if ($linha -match "DSA Destino") {
        $processandoOrigem = $false
        $processandoDestino = $true
        $processandoErros = $false
        continue
    }
    
    # Detecta o início da seção de erros operacionais
    if ($linha -match "Erros operacionais") {
        $processandoOrigem = $false
        $processandoDestino = $false
        $processandoErros = $true
        continue
    }
    
    # Processa servidores de origem
    if ($processandoOrigem -and $linha -match "^\s*(\S+)\s+(\S+)\s+(\d+)\s+\/\s+(\d+)\s+(\d+)(?:\s+(.+))?") {
        $dsa = $matches[1]
        $delta = $matches[2]
        $falhas = [int]$matches[3]
        $total = [int]$matches[4]
        $porcentagem = [int]$matches[5]
        $erro = if ($matches.Count -gt 6) { $matches[6] } else { "" }
        
        # Determina o status
        $status = if ($falhas -eq 0) { "OK" } elseif ($falhas -lt 3) { "Warning" } else { "Error" }
        
        # Adiciona à lista de servidores
        $servidores += [PSCustomObject]@{
            nome = "$dsa.$domainSuffix"
            status = $status
            parceiros = $total
            falhas = $falhas
            erros = $falhas
            replicacoes = $total
            ultima_replicacao = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            detalhes = $erro
            delta = $delta
            tipo = "Origem"
        }
    }
    
    # Processa servidores de destino
    if ($processandoDestino -and $linha -match "^\s*(\S+)\s+(\S+)\s+(\d+)\s+\/\s+(\d+)\s+(\d+)(?:\s+(.+))?") {
        $dsa = $matches[1]
        $delta = $matches[2]
        $falhas = [int]$matches[3]
        $total = [int]$matches[4]
        $porcentagem = [int]$matches[5]
        $erro = if ($matches.Count -gt 6) { $matches[6] } else { "" }
        
        # Determina o status
        $status = if ($falhas -eq 0) { "OK" } elseif ($falhas -lt 3) { "Warning" } else { "Error" }
        
        # Adiciona à lista de servidores
        $servidores += [PSCustomObject]@{
            nome = "$dsa.$domainSuffix"
            status = $status
            parceiros = $total
            falhas = $falhas
            erros = $falhas
            replicacoes = $total
            ultima_replicacao = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            detalhes = $erro
            delta = $delta
            tipo = "Destino"
        }
    }
    
    # Processa erros operacionais
    if ($processandoErros -and $linha -match "^\s*(\d+)\s+-\s+(.+)") {
        $codigo = $matches[1]
        $servidor = $matches[2]
        $errosOperacionais += "$codigo - $servidor"
    }
}

# Cria uma lista de servidores com erros operacionais
$servidoresComErrosOperacionais = @()
foreach ($erro in $errosOperacionais) {
    if ($erro -match "(\S+)\.$domainSuffixPattern") {
        $nomeServidor = "$($matches[1]).$domainSuffix"
        $servidoresComErrosOperacionais += $nomeServidor
    } elseif ($erro -match "(\S+)$") {
        $nomeServidor = "$($matches[1]).$domainSuffix"
        $servidoresComErrosOperacionais += $nomeServidor
    }
}

# Marca servidores com erros operacionais como problemáticos
foreach ($servidor in $servidores) {
    if ($servidoresComErrosOperacionais -contains $servidor.nome) {
        $servidor.status = "Error"
        $servidor.detalhes = "Erro operacional detectado"
    }
}

# Adiciona servidores com erros operacionais que não estão na lista
foreach ($nomeServidor in $servidoresComErrosOperacionais) {
    $servidorExistente = $servidores | Where-Object { $_.nome -eq $nomeServidor }
    if (-not $servidorExistente) {
        # Adiciona o servidor à lista
        $servidores += [PSCustomObject]@{
            nome = $nomeServidor
            status = "Error"
            parceiros = 0
            falhas = 1
            erros = 1
            replicacoes = 0
            ultima_replicacao = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            detalhes = "Erro operacional detectado"
            delta = "N/A"
            tipo = "Problema"
        }
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
# Usa ASCII para evitar problemas com BOM
$jsonContent | Out-File -FilePath $jsonPath -Encoding ascii

# Exibe informações
Write-Host "Servidores encontrados: $($servidores.Count)"
Write-Host "Erros operacionais: $($errosOperacionais.Count)"
Write-Host "Arquivo JSON salvo em: $jsonPath"