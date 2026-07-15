# Define o caminho do JSON
$caminhoJson = "$env:USERPROFILE\Desktop\Automação\data\replicacao_ad.json"
Write-Host "Caminho do JSON: $caminhoJson"

# Garante que o diretório existe
$diretorioJson = Split-Path -Parent $caminhoJson
if (!(Test-Path $diretorioJson)) {
    New-Item -ItemType Directory -Path $diretorioJson -Force
    Write-Host "Diretório criado: $diretorioJson"
}

# Cria dados simples para teste
$jsonData = @{
    timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    total_servidores = 5
    servidores_saudaveis = 4
    servidores_problemas = 1
    servidores = @(
        @{
            nome = "SERVIDOR1"
            status = "OK"
            parceiros = 4
            falhas = 0
            erros = 0
            replicacoes = 10
            ultima_replicacao = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
            detalhes = ""
        },
        @{
            nome = "SERVIDOR2"
            status = "OK"
            parceiros = 4
            falhas = 0
            erros = 0
            replicacoes = 10
            ultima_replicacao = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
            detalhes = ""
        },
        @{
            nome = "SERVIDOR3"
            status = "OK"
            parceiros = 4
            falhas = 0
            erros = 0
            replicacoes = 10
            ultima_replicacao = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
            detalhes = ""
        },
        @{
            nome = "SERVIDOR4"
            status = "OK"
            parceiros = 4
            falhas = 0
            erros = 0
            replicacoes = 10
            ultima_replicacao = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
            detalhes = ""
        },
        @{
            nome = "SERVIDOR5"
            status = "Error"
            parceiros = 4
            falhas = 2
            erros = 3
            replicacoes = 10
            ultima_replicacao = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
            detalhes = "Detectados 3 erros de replicação"
        }
    )
}

# Exporta o JSON
$jsonData | ConvertTo-Json -Depth 4 | Out-File -FilePath $caminhoJson -Encoding UTF8
Write-Host "Dados JSON salvos em: $caminhoJson"

# Verifica se o arquivo foi criado
if (Test-Path $caminhoJson) {
    Write-Host "Arquivo JSON criado com sucesso: $caminhoJson"
    Write-Host "Tamanho do arquivo: $((Get-Item $caminhoJson).Length) bytes"
} else {
    Write-Host "ERRO: Arquivo JSON não foi criado: $caminhoJson"
}

# Retorna sucesso
exit 0