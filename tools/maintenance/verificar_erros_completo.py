#!/usr/bin/env python3
"""
Verificação Completa de Erros do Projeto
Analisa todos os tipos de erros possíveis no sistema
"""

import os
import sys
import json
import ast
import re
import subprocess
from pathlib import Path
from datetime import datetime
import importlib.util

class VerificadorErros:
    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        self.erros_sintaxe = []
        self.erros_importacao = []
        self.erros_configuracao = []
        self.erros_dependencias = []
        self.erros_logicos = []
        self.avisos = []
        self.arquivos_problematicos = []
        
    def log_erro(self, categoria, mensagem, arquivo=None, linha=None):
        """Registra um erro encontrado"""
        erro = {
            "categoria": categoria,
            "mensagem": mensagem,
            "arquivo": arquivo,
            "linha": linha,
            "timestamp": datetime.now().isoformat()
        }
        
        if categoria == "SINTAXE":
            self.erros_sintaxe.append(erro)
        elif categoria == "IMPORTAÇÃO":
            self.erros_importacao.append(erro)
        elif categoria == "CONFIGURAÇÃO":
            self.erros_configuracao.append(erro)
        elif categoria == "DEPENDÊNCIA":
            self.erros_dependencias.append(erro)
        elif categoria == "LÓGICO":
            self.erros_logicos.append(erro)
        else:
            self.avisos.append(erro)
        
        print(f"❌ {categoria}: {mensagem}" + (f" ({arquivo}:{linha})" if arquivo and linha else f" ({arquivo})" if arquivo else ""))
    
    def log_aviso(self, mensagem, arquivo=None):
        """Registra um aviso"""
        self.avisos.append({
            "mensagem": mensagem,
            "arquivo": arquivo,
            "timestamp": datetime.now().isoformat()
        })
        print(f"⚠️ AVISO: {mensagem}" + (f" ({arquivo})" if arquivo else ""))
    
    def verificar_sintaxe_python(self):
        """Verifica erros de sintaxe em arquivos Python"""
        print("\n🔍 Verificando sintaxe Python...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        arquivos_python.extend(list(self.project_root.glob("**/*.py")))
        
        for arquivo in arquivos_python:
            if arquivo.name.startswith('verificar_erros_completo'):
                continue
                
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    codigo = f.read()
                
                # Verifica sintaxe
                try:
                    ast.parse(codigo)
                except SyntaxError as e:
                    self.log_erro("SINTAXE", f"Erro de sintaxe: {e.msg}", arquivo.name, e.lineno)
                    self.arquivos_problematicos.append(arquivo.name)
                
            except Exception as e:
                self.log_erro("SINTAXE", f"Erro ao ler arquivo: {e}", arquivo.name)
    
    def verificar_importacoes(self):
        """Verifica erros de importação"""
        print("\n🔍 Verificando importações...")
        
        arquivos_python = [f for f in self.project_root.glob("*.py") 
                          if not f.name.startswith('verificar_erros_completo')]
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    codigo = f.read()
                
                # Encontra imports
                imports = re.findall(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', codigo, re.MULTILINE)
                
                for from_module, import_items in imports:
                    if from_module:
                        # from X import Y
                        modulo = from_module
                    else:
                        # import X
                        modulo = import_items.split(',')[0].strip()
                    
                    # Verifica se é módulo local
                    if modulo.startswith('.') or modulo in ['config', 'credentials', 'auth_ad']:
                        continue
                    
                    # Tenta importar
                    try:
                        if modulo not in sys.modules:
                            importlib.import_module(modulo)
                    except ImportError as e:
                        self.log_erro("IMPORTAÇÃO", f"Módulo não encontrado: {modulo}", arquivo.name)
                    except Exception as e:
                        self.log_erro("IMPORTAÇÃO", f"Erro ao importar {modulo}: {e}", arquivo.name)
            
            except Exception as e:
                self.log_erro("IMPORTAÇÃO", f"Erro ao verificar imports: {e}", arquivo.name)
    
    def verificar_arquivos_configuracao(self):
        """Verifica arquivos de configuração"""
        print("\n🔍 Verificando arquivos de configuração...")
        
        # Verifica arquivos JSON
        arquivos_json = [
            "environment.json",
            "servidores.json", 
            "estrutura_regionais.json",
            "zabbix_config.json"
        ]
        
        for arquivo_nome in arquivos_json:
            arquivo_path = self.project_root / arquivo_nome
            
            if arquivo_path.exists():
                try:
                    with open(arquivo_path, 'r', encoding='utf-8') as f:
                        json.load(f)
                    print(f"✅ {arquivo_nome} - JSON válido")
                except json.JSONDecodeError as e:
                    self.log_erro("CONFIGURAÇÃO", f"JSON inválido: {e}", arquivo_nome)
                except Exception as e:
                    self.log_erro("CONFIGURAÇÃO", f"Erro ao ler JSON: {e}", arquivo_nome)
            else:
                if arquivo_nome in ["environment.json", "servidores.json"]:
                    self.log_erro("CONFIGURAÇÃO", f"Arquivo obrigatório não encontrado", arquivo_nome)
                else:
                    self.log_aviso(f"Arquivo opcional não encontrado", arquivo_nome)
        
        # Verifica requirements.txt
        req_file = self.project_root / "requirements.txt"
        if req_file.exists():
            try:
                with open(req_file, 'r', encoding='utf-8') as f:
                    linhas = f.readlines()
                
                for i, linha in enumerate(linhas, 1):
                    linha = linha.strip()
                    if linha and not linha.startswith('#'):
                        if '==' not in linha and '>=' not in linha:
                            self.log_aviso(f"Dependência sem versão específica: {linha}", f"requirements.txt:{i}")
                
                print(f"✅ requirements.txt - {len(linhas)} dependências")
            except Exception as e:
                self.log_erro("CONFIGURAÇÃO", f"Erro ao ler requirements.txt: {e}")
        else:
            self.log_erro("CONFIGURAÇÃO", "requirements.txt não encontrado")
    
    def verificar_dependencias_instaladas(self):
        """Verifica se dependências estão instaladas"""
        print("\n🔍 Verificando dependências instaladas...")
        
        req_file = self.project_root / "requirements.txt"
        if not req_file.exists():
            return
        
        try:
            with open(req_file, 'r', encoding='utf-8') as f:
                linhas = f.readlines()
            
            for linha in linhas:
                linha = linha.strip()
                if linha and not linha.startswith('#'):
                    # Extrai nome do pacote
                    pacote = linha.split('==')[0].split('>=')[0].split('<=')[0]
                    
                    try:
                        importlib.import_module(pacote)
                        print(f"✅ {pacote} - Instalado")
                    except ImportError:
                        # Tenta nomes alternativos comuns
                        nomes_alternativos = {
                            'Pillow': 'PIL',
                            'beautifulsoup4': 'bs4',
                            'python-dateutil': 'dateutil'
                        }
                        
                        nome_alt = nomes_alternativos.get(pacote)
                        if nome_alt:
                            try:
                                importlib.import_module(nome_alt)
                                print(f"✅ {pacote} ({nome_alt}) - Instalado")
                                continue
                            except ImportError:
                                pass
                        
                        self.log_erro("DEPENDÊNCIA", f"Pacote não instalado: {pacote}")
        
        except Exception as e:
            self.log_erro("DEPENDÊNCIA", f"Erro ao verificar dependências: {e}")
    
    def verificar_estrutura_diretorios(self):
        """Verifica estrutura de diretórios"""
        print("\n🔍 Verificando estrutura de diretórios...")
        
        diretorios_esperados = [
            "templates",
            "output", 
            "logs",
            "data"
        ]
        
        for diretorio in diretorios_esperados:
            dir_path = self.project_root / diretorio
            if dir_path.exists():
                print(f"✅ {diretorio}/ - Existe")
            else:
                self.log_aviso(f"Diretório não encontrado: {diretorio}/")
        
        # Verifica permissões de escrita
        for diretorio in ["output", "logs"]:
            dir_path = self.project_root / diretorio
            if dir_path.exists():
                try:
                    test_file = dir_path / "test_write.tmp"
                    test_file.write_text("test")
                    test_file.unlink()
                    print(f"✅ {diretorio}/ - Permissão de escrita OK")
                except Exception as e:
                    self.log_erro("CONFIGURAÇÃO", f"Sem permissão de escrita em {diretorio}/: {e}")
    
    def verificar_erros_logicos(self):
        """Verifica erros lógicos comuns"""
        print("\n🔍 Verificando erros lógicos...")
        
        arquivos_python = [f for f in self.project_root.glob("*.py") 
                          if not f.name.startswith('verificar_erros_completo')]
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    codigo = f.read()
                
                # Verifica divisão por zero
                if re.search(r'/\s*0\b', codigo):
                    self.log_erro("LÓGICO", "Possível divisão por zero", arquivo.name)
                
                # Verifica variáveis não definidas (padrões comuns)
                if re.search(r'\bundefined\b', codigo):
                    self.log_erro("LÓGICO", "Variável 'undefined' encontrada", arquivo.name)
                
                # Verifica prints de debug esquecidos
                debug_prints = re.findall(r'print\s*\(\s*["\'](?:DEBUG|debug|Debug)', codigo)
                if debug_prints:
                    self.log_aviso(f"Prints de debug encontrados: {len(debug_prints)}", arquivo.name)
                
                # Verifica TODO/FIXME
                todos = re.findall(r'#\s*(?:TODO|FIXME|XXX)', codigo, re.IGNORECASE)
                if todos:
                    self.log_aviso(f"TODOs/FIXMEs encontrados: {len(todos)}", arquivo.name)
                
                # Verifica except genérico
                if re.search(r'except\s*:', codigo):
                    self.log_aviso("Except genérico encontrado (pode mascarar erros)", arquivo.name)
            
            except Exception as e:
                continue
    
    def verificar_configuracao_sistema(self):
        """Verifica configuração específica do sistema"""
        print("\n🔍 Verificando configuração do sistema...")
        
        # Verifica config.py
        config_file = self.project_root / "config.py"
        if config_file.exists():
            try:
                # Importa config para verificar
                spec = importlib.util.spec_from_file_location("config", config_file)
                config = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config)
                
                # Verifica variáveis essenciais
                vars_essenciais = [
                    'PROJECT_ROOT',
                    'ENVIRONMENT_FILE', 
                    'SERVIDORES_FILE',
                    'OUTPUT_DIR',
                    'LOGS_DIR'
                ]
                
                for var in vars_essenciais:
                    if hasattr(config, var):
                        print(f"✅ {var} - Definido")
                    else:
                        self.log_erro("CONFIGURAÇÃO", f"Variável não definida: {var}", "config.py")
                
            except Exception as e:
                self.log_erro("CONFIGURAÇÃO", f"Erro ao importar config.py: {e}")
        else:
            self.log_erro("CONFIGURAÇÃO", "config.py não encontrado")
    
    def executar_testes_basicos(self):
        """Executa testes básicos de funcionamento"""
        print("\n🔍 Executando testes básicos...")
        
        # Testa importação dos módulos principais
        modulos_principais = [
            "config",
            "credentials", 
            "gerenciar_servidores",
            "web_config"
        ]
        
        for modulo in modulos_principais:
            arquivo = self.project_root / f"{modulo}.py"
            if arquivo.exists():
                try:
                    spec = importlib.util.spec_from_file_location(modulo, arquivo)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    print(f"✅ {modulo}.py - Importação OK")
                except Exception as e:
                    self.log_erro("IMPORTAÇÃO", f"Erro ao importar {modulo}.py: {e}")
            else:
                self.log_erro("CONFIGURAÇÃO", f"Módulo principal não encontrado: {modulo}.py")
    
    def gerar_relatorio_completo(self):
        """Gera relatório completo de erros"""
        print("\n" + "="*70)
        print("📋 RELATÓRIO COMPLETO DE ERROS")
        print("="*70)
        
        total_erros = (len(self.erros_sintaxe) + len(self.erros_importacao) + 
                      len(self.erros_configuracao) + len(self.erros_dependencias) + 
                      len(self.erros_logicos))
        
        print(f"\n📊 RESUMO:")
        print(f"   • Erros de Sintaxe: {len(self.erros_sintaxe)}")
        print(f"   • Erros de Importação: {len(self.erros_importacao)}")
        print(f"   • Erros de Configuração: {len(self.erros_configuracao)}")
        print(f"   • Erros de Dependências: {len(self.erros_dependencias)}")
        print(f"   • Erros Lógicos: {len(self.erros_logicos)}")
        print(f"   • Avisos: {len(self.avisos)}")
        print(f"   • TOTAL DE ERROS: {total_erros}")
        
        # Detalhes por categoria
        categorias = [
            ("ERROS DE SINTAXE", self.erros_sintaxe, "🔴"),
            ("ERROS DE IMPORTAÇÃO", self.erros_importacao, "🟠"),
            ("ERROS DE CONFIGURAÇÃO", self.erros_configuracao, "🟡"),
            ("ERROS DE DEPENDÊNCIAS", self.erros_dependencias, "🔵"),
            ("ERROS LÓGICOS", self.erros_logicos, "🟣"),
            ("AVISOS", self.avisos, "⚠️")
        ]
        
        for nome, lista, emoji in categorias:
            if lista:
                print(f"\n{emoji} {nome} ({len(lista)}):")
                for erro in lista:
                    arquivo_info = f" ({erro.get('arquivo', 'N/A')})" if erro.get('arquivo') else ""
                    linha_info = f":{erro.get('linha')}" if erro.get('linha') else ""
                    print(f"   {emoji} {erro['mensagem']}{arquivo_info}{linha_info}")
        
        # Arquivos mais problemáticos
        if self.arquivos_problematicos:
            print(f"\n🚨 ARQUIVOS MAIS PROBLEMÁTICOS:")
            from collections import Counter
            contador = Counter(self.arquivos_problematicos)
            for arquivo, count in contador.most_common(5):
                print(f"   🚨 {arquivo}: {count} erro(s)")
        
        # Status geral
        if total_erros == 0:
            status = "🟢 EXCELENTE - Nenhum erro encontrado!"
            recomendacao = "Sistema está funcionando corretamente"
        elif total_erros <= 5:
            status = "🟡 BOM - Poucos erros encontrados"
            recomendacao = "Corrigir erros menores para otimizar"
        elif total_erros <= 15:
            status = "🟠 REGULAR - Vários erros encontrados"
            recomendacao = "Correções necessárias para estabilidade"
        else:
            status = "🔴 CRÍTICO - Muitos erros encontrados"
            recomendacao = "Correções urgentes necessárias"
        
        print(f"\n🏆 STATUS GERAL: {status}")
        print(f"💡 RECOMENDAÇÃO: {recomendacao}")
        
        # Salva relatório detalhado
        relatorio_data = {
            "data_verificacao": datetime.now().isoformat(),
            "total_erros": total_erros,
            "status": status,
            "erros_sintaxe": self.erros_sintaxe,
            "erros_importacao": self.erros_importacao,
            "erros_configuracao": self.erros_configuracao,
            "erros_dependencias": self.erros_dependencias,
            "erros_logicos": self.erros_logicos,
            "avisos": self.avisos,
            "arquivos_problematicos": list(set(self.arquivos_problematicos)),
            "recomendacao": recomendacao
        }
        
        relatorio_file = self.project_root / f"relatorio_erros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(relatorio_file, 'w', encoding='utf-8') as f:
            json.dump(relatorio_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 Relatório detalhado salvo em: {relatorio_file}")
        
        return total_erros == 0
    
    def executar_verificacao_completa(self):
        """Executa verificação completa de erros"""
        print("🔍 VERIFICAÇÃO COMPLETA DE ERROS DO PROJETO")
        print("="*70)
        print(f"📁 Projeto: {self.project_root}")
        print(f"🕒 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Executa todas as verificações
        self.verificar_sintaxe_python()
        self.verificar_importacoes()
        self.verificar_arquivos_configuracao()
        self.verificar_dependencias_instaladas()
        self.verificar_estrutura_diretorios()
        self.verificar_configuracao_sistema()
        self.executar_testes_basicos()
        self.verificar_erros_logicos()
        
        # Gera relatório final
        return self.gerar_relatorio_completo()

def main():
    """Função principal"""
    verificador = VerificadorErros()
    sistema_ok = verificador.executar_verificacao_completa()
    
    if sistema_ok:
        print("\n🎉 SISTEMA SEM ERROS CRÍTICOS!")
        return 0
    else:
        print("\n⚠️ ERROS ENCONTRADOS - VERIFIQUE O RELATÓRIO!")
        return 1

if __name__ == "__main__":
    exit(main())