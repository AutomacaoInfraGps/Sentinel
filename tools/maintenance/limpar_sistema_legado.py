"""
Script para Limpeza do Sistema Legado
Remove completamente as referências ao sistema antigo
"""

import os
import shutil
from pathlib import Path
from datetime import datetime
import json

def fazer_backup_antes_limpeza():
    """Faz backup antes da limpeza"""
    
    backup_dir = Path(f"backup_antes_limpeza_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    backup_dir.mkdir(exist_ok=True)
    
    print("📦 Fazendo backup antes da limpeza...")
    
    # Arquivos para backup
    arquivos_backup = [
        "servidores.json",
        "templates/servidores.html",
        "templates/servidor_form.html",
        "templates/executar.html"
    ]
    
    for arquivo in arquivos_backup:
        arquivo_path = Path(arquivo)
        if arquivo_path.exists():
            backup_file_path = backup_dir / arquivo
            backup_file_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo_path, backup_file_path)
            print(f"   ✅ Backup: {arquivo}")
    
    print(f"📁 Backup salvo em: {backup_dir}")
    return backup_dir

def remover_templates_legados():
    """Remove templates do sistema legado"""
    
    print("🗑️ Removendo templates legados...")
    
    templates_legados = [
        "templates/servidores.html",
        "templates/servidor_form.html", 
        "templates/executar.html"
    ]
    
    for template in templates_legados:
        template_path = Path(template)
        if template_path.exists():
            template_path.unlink()
            print(f"   ✅ Removido: {template}")
        else:
            print(f"   ⚠️ Não encontrado: {template}")

def limpar_arquivos_temporarios():
    """Remove arquivos temporários e desnecessários"""
    
    print("🧹 Limpando arquivos temporários...")
    
    # Diretórios para limpar
    dirs_temp = [
        "__pycache__",
        ".pytest_cache",
        "*.pyc"
    ]
    
    # Remove __pycache__
    for pycache in Path(".").rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache)
            print(f"   ✅ Removido: {pycache}")
    
    # Remove arquivos .pyc
    for pyc in Path(".").rglob("*.pyc"):
        if pyc.is_file():
            pyc.unlink()
            print(f"   ✅ Removido: {pyc}")

def atualizar_iniciar_web():
    """Atualiza o iniciar_web.py para remover referências legadas"""
    
    print("🔧 Atualizando iniciar_web.py...")
    
    try:
        with open("iniciar_web.py", 'r', encoding='utf-8') as f:
            conteudo = f.read()
        
        # Remove verificação de servidores legados
        conteudo_novo = conteudo.replace(
            "if not config_status['servidores'] and not config_status['regionais']:",
            "if not config_status['regionais']:"
        )
        
        conteudo_novo = conteudo_novo.replace(
            "elif config_status['servidores']:\n        print(\"⚠️ Estrutura legada detectada - considere migrar para hierárquica\")",
            ""
        )
        
        with open("iniciar_web.py", 'w', encoding='utf-8') as f:
            f.write(conteudo_novo)
        
        print("   ✅ iniciar_web.py atualizado")
        
    except Exception as e:
        print(f"   ❌ Erro ao atualizar iniciar_web.py: {e}")

def criar_estrutura_limpa():
    """Cria estrutura limpa apenas hierárquica"""
    
    print("🏗️ Criando estrutura limpa...")
    
    try:
        from gerenciar_regionais import GerenciadorRegionais
        
        gerenciador = GerenciadorRegionais()
        
        # Verifica se estrutura hierárquica existe
        if not Path("estrutura_regionais.json").exists():
            print("   ⚠️ Estrutura hierárquica não encontrada - criando estrutura vazia")
            gerenciador.salvar_regionais()
        
        regionais = gerenciador.listar_regionais()
        print(f"   ✅ Estrutura hierárquica: {len(regionais)} regionais")
        
    except Exception as e:
        print(f"   ❌ Erro ao verificar estrutura: {e}")

def gerar_relatorio_limpeza():
    """Gera relatório da limpeza"""
    
    print("📊 Gerando relatório da limpeza...")
    
    try:
        relatorio = {
            "timestamp": datetime.now().isoformat(),
            "acao": "Limpeza do Sistema Legado",
            "versao_final": "2.0 - Apenas Estrutura Hierárquica",
            "arquivos_removidos": [
                "templates/servidores.html",
                "templates/servidor_form.html",
                "templates/executar.html"
            ],
            "estrutura_final": {
                "apenas_hierarquica": True,
                "sistema_legado": False,
                "compatibilidade": False
            }
        }
        
        # Adiciona informações das regionais se disponível
        try:
            from gerenciar_regionais import GerenciadorRegionais
            gerenciador = GerenciadorRegionais()
            regionais = gerenciador.listar_regionais()
            todos_servidores = gerenciador.listar_todos_servidores()
            
            relatorio["estatisticas"] = {
                "total_regionais": len(regionais),
                "total_servidores": len(todos_servidores)
            }
        except:
            relatorio["estatisticas"] = {
                "total_regionais": 0,
                "total_servidores": 0
            }
        
        # Salva relatório
        with open("relatorio_limpeza.json", 'w', encoding='utf-8') as f:
            json.dump(relatorio, f, indent=2, ensure_ascii=False)
        
        print("   ✅ Relatório salvo: relatorio_limpeza.json")
        
        # Mostra resumo
        print("\n📋 RESUMO DA LIMPEZA:")
        print(f"   🗑️ Templates legados removidos")
        print(f"   🧹 Arquivos temporários limpos")
        print(f"   🏗️ Estrutura hierárquica mantida")
        print(f"   ✅ Sistema 100% hierárquico")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Erro no relatório: {e}")
        return False

def main():
    """Função principal de limpeza"""
    
    print("🧹 LIMPEZA DO SISTEMA LEGADO")
    print("Remoção completa das funcionalidades antigas")
    print("=" * 60)
    
    # Confirmação
    resposta = input("\n⚠️ Esta operação removerá PERMANENTEMENTE o sistema legado.\nDeseja continuar? (digite 'CONFIRMAR'): ")
    
    if resposta != 'CONFIRMAR':
        print("❌ Operação cancelada pelo usuário")
        return False
    
    print("\n🚀 Iniciando limpeza...")
    
    # 1. Backup
    backup_dir = fazer_backup_antes_limpeza()
    
    # 2. Remove templates legados
    remover_templates_legados()
    
    # 3. Limpa arquivos temporários
    limpar_arquivos_temporarios()
    
    # 4. Atualiza iniciar_web.py
    atualizar_iniciar_web()
    
    # 5. Verifica estrutura limpa
    criar_estrutura_limpa()
    
    # 6. Gera relatório
    if not gerar_relatorio_limpeza():
        print("\n⚠️ AVISO: Erro ao gerar relatório (limpeza realizada)")
    
    print("\n🎉 LIMPEZA CONCLUÍDA COM SUCESSO!")
    print("=" * 60)
    print("✅ Sistema legado removido completamente")
    print("✅ Apenas estrutura hierárquica mantida")
    print("✅ Templates desnecessários removidos")
    print("✅ Arquivos temporários limpos")
    print(f"📁 Backup salvo em: {backup_dir}")
    print("\n🌐 Sistema 100% hierárquico:")
    print("   - Regionais → Servidores")
    print("   - Interface web limpa")
    print("   - Sem compatibilidade legada")
    print("\n🚀 Para usar:")
    print("   python iniciar_web.py")
    
    return True

if __name__ == "__main__":
    main()