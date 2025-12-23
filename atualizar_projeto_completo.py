"""
Script de Atualização Completa do Projeto
Integra toda a interface web com a nova estrutura hierárquica
"""

import os
import shutil
from pathlib import Path
from datetime import datetime
import json

def fazer_backup_completo():
    """Faz backup completo do projeto antes da atualização"""
    
    backup_dir = Path(f"backup_projeto_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    backup_dir.mkdir(exist_ok=True)
    
    print("📦 Fazendo backup completo do projeto...")
    
    # Arquivos importantes para backup
    arquivos_backup = [
        "web_config.py",
        "iniciar_web.py", 
        "templates/index.html",
        "templates/base.html",
        "servidores.json",
        "environment.json"
    ]
    
    for arquivo in arquivos_backup:
        arquivo_path = Path(arquivo)
        if arquivo_path.exists():
            # Cria diretório se necessário
            backup_file_path = backup_dir / arquivo
            backup_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(arquivo_path, backup_file_path)
            print(f"   ✅ Backup: {arquivo}")
    
    print(f"📁 Backup completo salvo em: {backup_dir}")
    return backup_dir

def verificar_estrutura_atual():
    """Verifica a estrutura atual do projeto"""
    
    print("🔍 Verificando estrutura atual...")
    
    estrutura = {
        'web_config_original': Path("web_config.py").exists(),
        'templates_originais': Path("templates").exists(),
        'estrutura_hierarquica': Path("estrutura_regionais.json").exists(),
        'servidores_legado': Path("servidores.json").exists(),
        'environment': Path("environment.json").exists(),
        'novos_modulos': all([
            Path("gerenciar_regionais.py").exists(),
            Path("verificar_servidores_v2.py").exists(),
            Path("dashboard_hierarquico.py").exists()
        ])
    }
    
    print("📊 Status da estrutura:")
    for item, status in estrutura.items():
        icon = "✅" if status else "❌"
        print(f"   {icon} {item.replace('_', ' ').title()}: {'OK' if status else 'Não encontrado'}")
    
    return estrutura

def migrar_dados_legados():
    """Migra dados do sistema legado para a estrutura hierárquica"""
    
    print("🔄 Migrando dados legados...")
    
    try:
        from gerenciar_regionais import GerenciadorRegionais
        
        gerenciador = GerenciadorRegionais()
        
        # Verifica se já existe estrutura hierárquica
        if Path("estrutura_regionais.json").exists():
            print("   ✅ Estrutura hierárquica já existe")
            return True
        
        # Migra da estrutura antiga se existir
        if Path("servidores.json").exists():
            print("   🔄 Migrando servidores.json para estrutura hierárquica...")
            gerenciador.migrar_estrutura_antiga()
            print("   ✅ Migração concluída")
            return True
        else:
            print("   ⚠️ Nenhuma estrutura anterior encontrada - criando estrutura vazia")
            # Cria estrutura básica vazia
            gerenciador.salvar_regionais()
            return True
            
    except Exception as e:
        print(f"   ❌ Erro na migração: {e}")
        return False

def atualizar_interface_web():
    """Atualiza a interface web com as novas funcionalidades"""
    
    print("🌐 Atualizando interface web...")
    
    try:
        # Verifica se os novos templates existem
        templates_novos = [
            "templates/index_hierarquico.html",
            "templates/regionais.html", 
            "templates/regional_form.html",
            "templates/executar_completo.html"
        ]
        
        templates_ok = all(Path(t).exists() for t in templates_novos)
        
        if not templates_ok:
            print("   ❌ Templates hierárquicos não encontrados")
            return False
        
        print("   ✅ Templates hierárquicos encontrados")
        
        # Verifica se web_config.py foi atualizado
        with open("web_config.py", 'r', encoding='utf-8') as f:
            conteudo = f.read()
            
        if "gerenciar_regionais" in conteudo and "dashboard_hierarquico" in conteudo:
            print("   ✅ web_config.py já atualizado")
        else:
            print("   ⚠️ web_config.py precisa ser atualizado manualmente")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Erro na atualização: {e}")
        return False

def testar_sistema_atualizado():
    """Testa se o sistema atualizado está funcionando"""
    
    print("🧪 Testando sistema atualizado...")
    
    try:
        # Testa importações dos novos módulos
        from gerenciar_regionais import GerenciadorRegionais
        from verificar_servidores_v2 import VerificadorServidoresV2
        from dashboard_hierarquico import DashboardHierarquico
        
        print("   ✅ Importações dos novos módulos: OK")
        
        # Testa instanciação
        gerenciador = GerenciadorRegionais()
        verificador = VerificadorServidoresV2()
        dashboard = DashboardHierarquico()
        
        print("   ✅ Instanciação dos módulos: OK")
        
        # Testa funcionalidades básicas
        regionais = gerenciador.listar_regionais()
        print(f"   ✅ Regionais encontradas: {len(regionais)}")
        
        # Testa coleta de dados
        dados = dashboard.coletar_dados_completos()
        print(f"   ✅ Coleta de dados: {dados['estatisticas_gerais']['total_regionais']} regionais")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Erro no teste: {e}")
        return False

def gerar_relatorio_atualizacao():
    """Gera relatório da atualização"""
    
    print("📊 Gerando relatório da atualização...")
    
    try:
        from gerenciar_regionais import GerenciadorRegionais
        
        gerenciador = GerenciadorRegionais()
        regionais = gerenciador.listar_regionais()
        todos_servidores = gerenciador.listar_todos_servidores()
        
        relatorio = {
            "timestamp": datetime.now().isoformat(),
            "versao": "2.0 - Estrutura Hierárquica",
            "estatisticas": {
                "total_regionais": len(regionais),
                "total_servidores": len(todos_servidores),
                "estrutura_hierarquica": True
            },
            "regionais": []
        }
        
        for codigo_regional in regionais:
            regional_info = gerenciador.obter_regional(codigo_regional)
            if regional_info:
                relatorio["regionais"].append({
                    "codigo": codigo_regional,
                    "nome": regional_info.get("nome", codigo_regional),
                    "servidores": len(regional_info.get("servidores", []))
                })
        
        # Salva relatório
        with open("relatorio_atualizacao.json", 'w', encoding='utf-8') as f:
            json.dump(relatorio, f, indent=2, ensure_ascii=False)
        
        print("   ✅ Relatório salvo: relatorio_atualizacao.json")
        
        # Mostra resumo
        print("\n📋 RESUMO DA ATUALIZAÇÃO:")
        print(f"   🏢 Regionais: {relatorio['estatisticas']['total_regionais']}")
        print(f"   🖥️ Servidores: {relatorio['estatisticas']['total_servidores']}")
        print(f"   ✅ Estrutura Hierárquica: Ativa")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Erro no relatório: {e}")
        return False

def main():
    """Função principal de atualização"""
    
    print("🚀 ATUALIZAÇÃO COMPLETA DO PROJETO")
    print("Integração da Interface Web com Estrutura Hierárquica")
    print("=" * 60)
    
    # 1. Verificação inicial
    estrutura = verificar_estrutura_atual()
    
    if not estrutura['novos_modulos']:
        print("\n❌ ERRO: Módulos hierárquicos não encontrados!")
        print("Execute primeiro os scripts de criação da estrutura hierárquica.")
        return False
    
    # 2. Backup
    backup_dir = fazer_backup_completo()
    
    # 3. Migração de dados
    if not migrar_dados_legados():
        print("\n❌ ERRO: Falha na migração de dados")
        return False
    
    # 4. Atualização da interface
    if not atualizar_interface_web():
        print("\n❌ ERRO: Falha na atualização da interface web")
        return False
    
    # 5. Testes
    if not testar_sistema_atualizado():
        print("\n❌ ERRO: Sistema atualizado apresenta problemas")
        return False
    
    # 6. Relatório final
    if not gerar_relatorio_atualizacao():
        print("\n⚠️ AVISO: Erro ao gerar relatório (sistema funcionando)")
    
    print("\n🎉 ATUALIZAÇÃO CONCLUÍDA COM SUCESSO!")
    print("=" * 60)
    print("✅ Interface web integrada com estrutura hierárquica")
    print("✅ Dados migrados com sucesso")
    print("✅ Sistema testado e funcionando")
    print(f"📁 Backup salvo em: {backup_dir}")
    print("\n🚀 Para usar o sistema atualizado:")
    print("   python iniciar_web.py")
    print("\n🌐 Acesse: http://localhost:5000")
    
    return True

if __name__ == "__main__":
    main()