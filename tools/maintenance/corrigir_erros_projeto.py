#!/usr/bin/env python3
"""
Script para corrigir erros identificados no projeto
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime

class CorretorErros:
    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        self.erros_corrigidos = []
        
    def log_correcao(self, arquivo, descricao):
        """Registra uma correção realizada"""
        self.erros_corrigidos.append({
            "arquivo": arquivo,
            "descricao": descricao,
            "timestamp": datetime.now().isoformat()
        })
        print(f"✅ {arquivo}: {descricao}")
    
    def corrigir_imports_pandas(self):
        """Corrige imports do pandas em arquivos que precisam"""
        print("\n🔧 Corrigindo imports do pandas...")
        
        arquivos_pandas = [
            "cadastrar_switch.py",
            "corrigir_ips_excel.py", 
            "gerenciar_switches.py",
            "gerenciar_vms.py",
            "InfSwitches.py",
            "testar_ip.py"
        ]
        
        for arquivo_nome in arquivos_pandas:
            arquivo_path = self.project_root / arquivo_nome
            
            if not arquivo_path.exists():
                continue
                
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Verifica se já tem import do pandas
                if 'import pandas as pd' in conteudo and 'try:' not in conteudo.split('import pandas')[0]:
                    # Adiciona try/except para pandas
                    conteudo_corrigido = re.sub(
                        r'import pandas as pd',
                        '''try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas não instalado. Funcionalidades limitadas.")
    PANDAS_AVAILABLE = False
    pd = None''',
                        conteudo,
                        count=1
                    )
                    
                    with open(arquivo_path, 'w', encoding='utf-8') as f:
                        f.write(conteudo_corrigido)
                    
                    self.log_correcao(arquivo_nome, "Import do pandas corrigido com try/except")
            
            except Exception as e:
                print(f"❌ Erro ao corrigir {arquivo_nome}: {e}")
    
    def corrigir_imports_urllib3(self):
        """Corrige imports do urllib3 que mudaram de localização"""
        print("\n🔧 Corrigindo imports do urllib3...")
        
        arquivos = list(self.project_root.glob("*.py"))
        
        for arquivo_path in arquivos:
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Corrige import antigo do urllib3
                if 'requests.packages.urllib3.exceptions' in conteudo:
                    conteudo_corrigido = conteudo.replace(
                        'from requests.packages.urllib3.exceptions import InsecureRequestWarning',
                        '''try:
    from urllib3.exceptions import InsecureRequestWarning
except ImportError:
    try:
        from requests.packages.urllib3.exceptions import InsecureRequestWarning
    except ImportError:
        # Fallback se nenhum funcionar
        class InsecureRequestWarning(Warning):
            pass'''
                    )
                    
                    if conteudo_corrigido != conteudo:
                        with open(arquivo_path, 'w', encoding='utf-8') as f:
                            f.write(conteudo_corrigido)
                        
                        self.log_correcao(arquivo_path.name, "Import do urllib3 corrigido")
            
            except Exception as e:
                continue
    
    def adicionar_verificacoes_pandas(self):
        """Adiciona verificações para uso do pandas"""
        print("\n🔧 Adicionando verificações para pandas...")
        
        arquivos_com_pandas = []
        
        # Encontra arquivos que usam pandas
        for arquivo_path in self.project_root.glob("*.py"):
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                if 'pd.' in conteudo and 'PANDAS_AVAILABLE' not in conteudo:
                    arquivos_com_pandas.append(arquivo_path)
            except Exception as e:
                print(f"Erro ignorado em {__file__}: {e}")
                continue
        
        for arquivo_path in arquivos_com_pandas:
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Adiciona verificações antes do uso do pandas
                linhas = conteudo.split('\n')
                linhas_corrigidas = []
                
                for linha in linhas:
                    if 'pd.' in linha and 'if PANDAS_AVAILABLE' not in linha:
                        # Adiciona verificação antes da linha
                        indent = len(linha) - len(linha.lstrip())
                        verificacao = ' ' * indent + 'if not PANDAS_AVAILABLE:'
                        retorno = ' ' * (indent + 4) + 'return {"erro": "Pandas não disponível"}'
                        
                        linhas_corrigidas.append(verificacao)
                        linhas_corrigidas.append(retorno)
                    
                    linhas_corrigidas.append(linha)
                
                conteudo_corrigido = '\n'.join(linhas_corrigidas)
                
                if conteudo_corrigido != conteudo:
                    with open(arquivo_path, 'w', encoding='utf-8') as f:
                        f.write(conteudo_corrigido)
                    
                    self.log_correcao(arquivo_path.name, "Verificações do pandas adicionadas")
            
            except Exception as e:
                continue
    
    def corrigir_excepts_genericos(self):
        """Melhora excepts genéricos adicionando logging"""
        print("\n🔧 Melhorando excepts genéricos...")
        
        for arquivo_path in self.project_root.glob("*.py"):
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Procura por except: genéricos
                if re.search(r'except\s*:', conteudo):
                    # Adiciona logging aos excepts genéricos
                    conteudo_corrigido = re.sub(
                        r'except\s*:\s*\n(\s+)pass',
                        r'except Exception as e:\n\1print(f"Erro em {}: {{e}}".format(__file__))',
                        conteudo
                    )
                    
                    conteudo_corrigido = re.sub(
                        r'except\s*:\s*\n(\s+)continue',
                        r'except Exception as e:\n\1print(f"Erro ignorado em {}: {{e}}".format(__file__))\n\1continue',
                        conteudo_corrigido
                    )
                    
                    if conteudo_corrigido != conteudo:
                        with open(arquivo_path, 'w', encoding='utf-8') as f:
                            f.write(conteudo_corrigido)
                        
                        self.log_correcao(arquivo_path.name, "Excepts genéricos melhorados")
            
            except Exception as e:
                continue
    
    def instalar_dependencias_faltantes(self):
        """Instala dependências que estão faltando"""
        print("\n🔧 Instalando dependências faltantes...")
        
        dependencias_criticas = [
            "pandas",
            "openpyxl",
            "opencv-python",
            "scikit-image"
        ]
        
        for dep in dependencias_criticas:
            try:
                import subprocess
                import sys
                
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", dep],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    self.log_correcao("pip", f"Dependência {dep} instalada")
                else:
                    print(f"⚠️ Falha ao instalar {dep}: {result.stderr}")
            
            except Exception as e:
                print(f"❌ Erro ao instalar {dep}: {e}")
    
    def criar_arquivos_faltantes(self):
        """Cria arquivos que estão faltando"""
        print("\n🔧 Criando arquivos faltantes...")
        
        # Cria backup_sistema.py se não existir
        backup_file = self.project_root / "backup_sistema.py"
        if not backup_file.exists():
            backup_content = '''"""
Módulo de backup do sistema
"""

import os
import shutil
import zipfile
from pathlib import Path
from datetime import datetime

def criar_backup_completo():
    """Cria backup completo do sistema"""
    try:
        project_root = Path(__file__).parent
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_sistema_{timestamp}.zip"
        backup_path = project_root / backup_name
        
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Adiciona arquivos importantes
            for arquivo in ["*.py", "*.json", "*.txt", "*.md"]:
                for file_path in project_root.glob(arquivo):
                    if not file_path.name.startswith('backup_'):
                        zipf.write(file_path, file_path.name)
        
        return str(backup_path)
    
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None
'''
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                f.write(backup_content)
            
            self.log_correcao("backup_sistema.py", "Arquivo criado")
    
    def gerar_relatorio_final(self):
        """Gera relatório final das correções"""
        print("\n" + "="*70)
        print("📋 RELATÓRIO DE CORREÇÕES APLICADAS")
        print("="*70)
        
        if not self.erros_corrigidos:
            print("ℹ️ Nenhuma correção foi necessária.")
            return
        
        print(f"\n✅ TOTAL DE CORREÇÕES: {len(self.erros_corrigidos)}")
        
        # Agrupa por arquivo
        por_arquivo = {}
        for correcao in self.erros_corrigidos:
            arquivo = correcao['arquivo']
            if arquivo not in por_arquivo:
                por_arquivo[arquivo] = []
            por_arquivo[arquivo].append(correcao['descricao'])
        
        for arquivo, correcoes in por_arquivo.items():
            print(f"\n📄 {arquivo}:")
            for correcao in correcoes:
                print(f"   ✅ {correcao}")
        
        # Salva relatório
        relatorio_data = {
            "data_correcao": datetime.now().isoformat(),
            "total_correcoes": len(self.erros_corrigidos),
            "correcoes": self.erros_corrigidos
        }
        
        import json
        relatorio_file = self.project_root / f"relatorio_correcoes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(relatorio_file, 'w', encoding='utf-8') as f:
            json.dump(relatorio_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 Relatório salvo em: {relatorio_file}")
        print("\n🎉 CORREÇÕES CONCLUÍDAS!")
    
    def executar_todas_correcoes(self):
        """Executa todas as correções"""
        print("🔧 CORREÇÃO AUTOMÁTICA DE ERROS DO PROJETO")
        print("="*70)
        print(f"📁 Projeto: {self.project_root}")
        print(f"🕒 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Executa todas as correções
        self.corrigir_imports_pandas()
        self.corrigir_imports_urllib3()
        self.adicionar_verificacoes_pandas()
        self.corrigir_excepts_genericos()
        self.instalar_dependencias_faltantes()
        self.criar_arquivos_faltantes()
        
        # Gera relatório final
        self.gerar_relatorio_final()

def main():
    """Função principal"""
    corretor = CorretorErros()
    corretor.executar_todas_correcoes()
    return 0

if __name__ == "__main__":
    exit(main())