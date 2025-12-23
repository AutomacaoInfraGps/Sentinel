"""
Script para testar a nova estrutura de pastas do Relatório Preventiva
"""
from config import (
    get_relatorio_preventiva_path, 
    DASHBOARD_FINAL, 
    DASHBOARD_FINAL_ORIGINAL,
    RELATORIO_PREVENTIVA_DIR,
    ensure_directories,
    get_dashboard_filename
)
from datetime import datetime

def testar_estrutura():
    """Testa a criação da estrutura de pastas"""
    print("🧪 TESTE DA ESTRUTURA DE RELATÓRIO PREVENTIVA")
    print("=" * 60)
    
    # Testa a função de criação de pastas
    print("\n📁 Testando criação de estrutura de pastas...")
    pasta_relatorio = get_relatorio_preventiva_path()
    print(f"✅ Pasta criada/verificada: {pasta_relatorio}")
    
    # Testa a função ensure_directories
    print("\n📂 Testando ensure_directories...")
    ensure_directories()
    
    # Mostra informações sobre os caminhos
    print(f"\n📋 INFORMAÇÕES DOS CAMINHOS:")
    print(f"   - Pasta do relatório: {RELATORIO_PREVENTIVA_DIR}")
    print(f"   - Arquivo principal: {DASHBOARD_FINAL}")
    print(f"   - Arquivo original: {DASHBOARD_FINAL_ORIGINAL}")
    print(f"   - Nome do arquivo: {get_dashboard_filename()}")
    
    # Verifica se as pastas existem
    print(f"\n✅ VERIFICAÇÃO DE EXISTÊNCIA:")
    print(f"   - Pasta relatório existe: {RELATORIO_PREVENTIVA_DIR.exists()}")
    print(f"   - Pasta pai (dia) existe: {RELATORIO_PREVENTIVA_DIR.parent.exists()}")
    print(f"   - Pasta avô (mês) existe: {RELATORIO_PREVENTIVA_DIR.parent.parent.exists()}")
    print(f"   - Pasta bisavô (ano) existe: {RELATORIO_PREVENTIVA_DIR.parent.parent.parent.exists()}")
    
    # Mostra a estrutura completa
    print(f"\n🏗️ ESTRUTURA COMPLETA:")
    now = datetime.now()
    desktop = RELATORIO_PREVENTIVA_DIR.parent.parent.parent.parent
    print(f"   Desktop: {desktop}")
    print(f"   └── Relatório Preventiva/")
    print(f"       └── {now.year}/")
    print(f"           └── {now.month:02d}/")
    print(f"               └── {now.day:02d}/")
    print(f"                   └── {get_dashboard_filename()}")
    
    # Cria um arquivo de teste
    print(f"\n📝 Criando arquivo de teste...")
    arquivo_teste = RELATORIO_PREVENTIVA_DIR / "teste_estrutura.txt"
    with open(arquivo_teste, 'w', encoding='utf-8') as f:
        f.write(f"Teste da estrutura de pastas\n")
        f.write(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write(f"Pasta: {RELATORIO_PREVENTIVA_DIR}\n")
    
    print(f"✅ Arquivo de teste criado: {arquivo_teste}")
    print(f"✅ Arquivo existe: {arquivo_teste.exists()}")
    
    print(f"\n🎉 TESTE CONCLUÍDO COM SUCESSO!")
    print(f"📂 Acesse a pasta: {RELATORIO_PREVENTIVA_DIR}")

if __name__ == "__main__":
    testar_estrutura()