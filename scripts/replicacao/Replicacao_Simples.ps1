# Script para capturar a saída do repadmin /replsummary e salvar em um arquivo
# Autor: Assistente IA
# Data: 24/07/2025

# Define o caminho do arquivo de saída
$outputPath = "$env:USERPROFILE\Desktop\Automação\data\repadmin_output.txt"

# Cria o diretório data se não existir
$dataDir = "$env:USERPROFILE\Desktop\Automação\data"
if (-not (Test-Path -Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
}

# Executa o comando repadmin e captura a saída completa
Write-Host "Executando repadmin /replsummary..."
$output = repadmin /replsummary | Out-String

# Salva a saída em um arquivo
$output | Out-File -FilePath $outputPath -Encoding utf8
Write-Host "Saída salva em: $outputPath"

# Retorna sucesso
exit 0