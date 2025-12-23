#!/usr/bin/env python3
"""
Script de Validação de Escalabilidade
Verifica se o sistema está pronto para ser implantado em qualquer servidor
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

class ValidadorEscalabilidade:
    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        self.erros = []
        self.avisos = []
        self.sucessos = []
    
    def log_sucesso(self, mensagem):
        """Registra um sucesso"""
        self.sucessos.append(mensagem)
        print(f"✅ {mensagem}")
    
    def log_aviso(self, mensagem):
        """Registra um aviso"""
        self.avisos.append(mensagem)
        print(f"⚠️ {mensagem}")
    
    def log_erro(self, mensagem):
        """Registra um erro"""
        self.erros.append(mensagem)
        print(f"❌ {mensagem}")
    
    def verificar_estrutura_arquivos(self):
        """Verifica se todos os arquivos essenciais existem"""
        print("\n🔍 Verificando estrutura de arquivos...")
        
        arquivos_essenciais = [
            "config.py",
            "setup.py", 
            "iniciar_web.py",
            "executar_tudo.py",
            "requirements.txt",
            "GUIA_CONFIGURACAO.md"
        ]
        
        for arquivo in arquivos_essenciais:
            caminho = self.project_root / arquivo
            if caminho.exists():
                self.log_sucesso(f"Arquivo essencial encontrado: {arquivo}")
            else:
                self.log_erro(f"Arquivo essencial faltando: {arquivo}")
    
    def verificar_caminhos_dinamicos(self):
        """Verifica se não há caminhos hardcoded"""
        print("\n🔍 Verificando caminhos dinâmicos...")
        
        # Verifica config.py
        config_file = self.project_root / "config.py"
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if "Path(__file__).parent" in content:
                self.log_sucesso("config.py usa caminhos dinâmicos")
            else:
                self.log_erro("config.py não usa caminhos dinâmicos")
                
            if "getattr(sys, 'frozen', False)" in content:
                self.log_sucesso("config.py suporta executável compilado")
            else:
                self.log_aviso("config.py pode não suportar executável compilado")
    
    def verificar_configuracao_flexivel(self):
        """Verifica se a configuração é flexível"""
        print("\n🔍 Verificando flexibilidade de configuração...")
        
        # Verifica environment.json
        env_file = self.project_root / "environment.json"
        if env_file.exists():
            try:
                with open(env_file, 'r', encoding='utf-8') as f:
                    env_config = json.load(f)
                
                if "naos_server" in env_config:
                    self.log_sucesso("Configuração de servidor NAOS encontrada")
                
                if "timeouts" in env_config:
                    self.log_sucesso("Configurações de timeout encontradas")
                
                if "unifi_controller" in env_config:
                    self.log_sucesso("Configuração UniFi encontrada")
                    
            except json.JSONDecodeError:
                self.log_erro("environment.json tem formato inválido")
        else:
            self.log_aviso("environment.json não encontrado (será criado no setup)")
    
    def verificar_templates(self):
        """Verifica se os templates estão disponíveis"""
        print("\n🔍 Verificando templates de configuração...")
        
        templates_file = self.project_root / "templates_configuracao.py"
        if templates_file.exists():
            try:
                # Importa dinamicamente
                sys.path.insert(0, str(self.project_root))
                from templates_configuracao import TemplatesConfiguracao
                
                tc = TemplatesConfiguracao()
                templates = tc.listar_templates()
                
                if len(templates) >= 3:
                    self.log_sucesso(f"Templates disponíveis: {len(templates)}")
                    for template in templates:
                        print(f"   - {template}")
                else:
                    self.log_aviso("Poucos templates disponíveis")
                    
            except ImportError as e:
                self.log_erro(f"Erro ao importar templates: {e}")
        else:
            self.log_erro("Arquivo de templates não encontrado")
    
    def verificar_dependencias(self):
        """Verifica se as dependências estão documentadas"""
        print("\n🔍 Verificando dependências...")
        
        req_file = self.project_root / "requirements.txt"
        if req_file.exists():
            with open(req_file, 'r', encoding='utf-8') as f:
                deps = f.readlines()
            
            deps_essenciais = ['flask', 'requests', 'playwright']
            deps_encontradas = []
            
            for dep in deps:
                dep_name = dep.split('==')[0].strip().lower()
                if dep_name in deps_essenciais:
                    deps_encontradas.append(dep_name)
            
            if len(deps_encontradas) >= 2:
                self.log_sucesso(f"Dependências essenciais documentadas: {deps_encontradas}")
            else:
                self.log_aviso("Algumas dependências essenciais podem estar faltando")
        else:
            self.log_erro("requirements.txt não encontrado")
    
    def verificar_setup_automatizado(self):
        """Verifica se o setup é automatizado"""
        print("\n🔍 Verificando setup automatizado...")
        
        setup_file = self.project_root / "setup.py"
        if setup_file.exists():
            with open(setup_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if "create_environment_template" in content:
                self.log_sucesso("Setup cria template de environment")
            
            if "check_dependencies" in content:
                self.log_sucesso("Setup verifica dependências")
            
            if "ensure_directories" in content:
                self.log_sucesso("Setup cria diretórios necessários")
        else:
            self.log_erro("setup.py não encontrado")
    
    def verificar_interface_web(self):
        """Verifica se a interface web está disponível"""
        print("\n🔍 Verificando interface web...")
        
        web_file = self.project_root / "iniciar_web.py"
        if web_file.exists():
            self.log_sucesso("Interface web disponível")
            
            # Verifica se tem configuração web
            web_config = self.project_root / "web_config.py"
            if web_config.exists():
                self.log_sucesso("Configuração web encontrada")
            else:
                self.log_aviso("Configuração web pode estar faltando")
        else:
            self.log_erro("Interface web não encontrada")
    
    def verificar_logs_organizados(self):
        """Verifica se o sistema de logs está organizado"""
        print("\n🔍 Verificando sistema de logs...")
        
        # Verifica se config.py tem função de logs
        config_file = self.project_root / "config.py"
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if "LOGS_DIR" in content:
                self.log_sucesso("Diretório de logs configurado")
            
            if "get_log_file" in content:
                self.log_sucesso("Função de logs encontrada")
    
    def verificar_backup_sistema(self):
        """Verifica se há sistema de backup"""
        print("\n🔍 Verificando sistema de backup...")
        
        # Procura por funcionalidades de backup
        arquivos_backup = [
            "manage.py",
            "gerenciar_servidores.py"
        ]
        
        backup_encontrado = False
        for arquivo in arquivos_backup:
            caminho = self.project_root / arquivo
            if caminho.exists():
                with open(caminho, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if "export" in content or "backup" in content:
                    backup_encontrado = True
                    break
        
        if backup_encontrado:
            self.log_sucesso("Sistema de backup encontrado")
        else:
            self.log_aviso("Sistema de backup não encontrado")
    
    def verificar_compatibilidade_executavel(self):
        """Verifica se é compatível com executável"""
        print("\n🔍 Verificando compatibilidade com executável...")
        
        compile_file = self.project_root / "compile_to_exe.py"
        if compile_file.exists():
            self.log_sucesso("Script de compilação encontrado")
        else:
            self.log_aviso("Script de compilação não encontrado")
        
        # Verifica se há arquivo .bat
        bat_files = list(self.project_root.glob("*.bat"))
        if bat_files:
            self.log_sucesso(f"Arquivo de execução encontrado: {bat_files[0].name}")
        else:
            self.log_aviso("Arquivo .bat de execução não encontrado")
    
    def gerar_relatorio(self):
        """Gera relatório final"""
        print("\n" + "="*60)
        print("📊 RELATÓRIO DE ESCALABILIDADE")
        print("="*60)
        
        print(f"\n✅ SUCESSOS ({len(self.sucessos)}):")
        for sucesso in self.sucessos:
            print(f"   ✅ {sucesso}")
        
        if self.avisos:
            print(f"\n⚠️ AVISOS ({len(self.avisos)}):")
            for aviso in self.avisos:
                print(f"   ⚠️ {aviso}")
        
        if self.erros:
            print(f"\n❌ ERROS ({len(self.erros)}):")
            for erro in self.erros:
                print(f"   ❌ {erro}")
        
        # Calcula pontuação
        total_verificacoes = len(self.sucessos) + len(self.avisos) + len(self.erros)
        pontuacao = (len(self.sucessos) / total_verificacoes * 100) if total_verificacoes > 0 else 0
        
        print(f"\n📊 PONTUAÇÃO DE ESCALABILIDADE: {pontuacao:.1f}%")
        
        if pontuacao >= 90:
            print("🎉 EXCELENTE! Sistema totalmente pronto para escalabilidade")
            status = "APROVADO"
        elif pontuacao >= 75:
            print("👍 BOM! Sistema quase pronto, alguns ajustes menores")
            status = "APROVADO COM RESSALVAS"
        elif pontuacao >= 60:
            print("⚠️ REGULAR! Sistema precisa de alguns ajustes")
            status = "REQUER AJUSTES"
        else:
            print("❌ CRÍTICO! Sistema precisa de grandes modificações")
            status = "NÃO APROVADO"
        
        print(f"\n🏆 STATUS FINAL: {status}")
        
        # Salva relatório
        relatorio_file = self.project_root / f"relatorio_escalabilidade_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(relatorio_file, 'w', encoding='utf-8') as f:
            f.write(f"RELATÓRIO DE ESCALABILIDADE - {datetime.now()}\n")
            f.write("="*60 + "\n\n")
            f.write(f"SUCESSOS ({len(self.sucessos)}):\n")
            for sucesso in self.sucessos:
                f.write(f"✅ {sucesso}\n")
            f.write(f"\nAVISOS ({len(self.avisos)}):\n")
            for aviso in self.avisos:
                f.write(f"⚠️ {aviso}\n")
            f.write(f"\nERROS ({len(self.erros)}):\n")
            for erro in self.erros:
                f.write(f"❌ {erro}\n")
            f.write(f"\nPONTUAÇÃO: {pontuacao:.1f}%\n")
            f.write(f"STATUS: {status}\n")
        
        print(f"\n📄 Relatório salvo em: {relatorio_file}")
        
        return len(self.erros) == 0
    
    def executar_validacao_completa(self):
        """Executa todas as validações"""
        print("🚀 VALIDADOR DE ESCALABILIDADE")
        print("="*60)
        print(f"📁 Projeto: {self.project_root}")
        print(f"🕒 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Executa todas as verificações
        self.verificar_estrutura_arquivos()
        self.verificar_caminhos_dinamicos()
        self.verificar_configuracao_flexivel()
        self.verificar_templates()
        self.verificar_dependencias()
        self.verificar_setup_automatizado()
        self.verificar_interface_web()
        self.verificar_logs_organizados()
        self.verificar_backup_sistema()
        self.verificar_compatibilidade_executavel()
        
        # Gera relatório final
        return self.gerar_relatorio()

def main():
    """Função principal"""
    validador = ValidadorEscalabilidade()
    sucesso = validador.executar_validacao_completa()
    
    if sucesso:
        print("\n🎉 SISTEMA APROVADO PARA ESCALABILIDADE!")
        return 0
    else:
        print("\n⚠️ SISTEMA REQUER AJUSTES ANTES DA ESCALABILIDADE!")
        return 1

if __name__ == "__main__":
    sys.exit(main())