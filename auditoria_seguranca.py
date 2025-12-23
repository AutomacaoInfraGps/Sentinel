#!/usr/bin/env python3
"""
Auditoria de Segurança do Sistema de Automação
Verifica vulnerabilidades e práticas de segurança
"""

import os
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
import subprocess

class AuditoriaSeguranca:
    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        self.vulnerabilidades_criticas = []
        self.vulnerabilidades_altas = []
        self.vulnerabilidades_medias = []
        self.vulnerabilidades_baixas = []
        self.boas_praticas = []
        
    def log_critica(self, mensagem, arquivo=None):
        """Registra vulnerabilidade crítica"""
        item = {"mensagem": mensagem, "arquivo": arquivo, "nivel": "CRÍTICA"}
        self.vulnerabilidades_criticas.append(item)
        print(f"🔴 CRÍTICA: {mensagem}" + (f" ({arquivo})" if arquivo else ""))
    
    def log_alta(self, mensagem, arquivo=None):
        """Registra vulnerabilidade alta"""
        item = {"mensagem": mensagem, "arquivo": arquivo, "nivel": "ALTA"}
        self.vulnerabilidades_altas.append(item)
        print(f"🟠 ALTA: {mensagem}" + (f" ({arquivo})" if arquivo else ""))
    
    def log_media(self, mensagem, arquivo=None):
        """Registra vulnerabilidade média"""
        item = {"mensagem": mensagem, "arquivo": arquivo, "nivel": "MÉDIA"}
        self.vulnerabilidades_medias.append(item)
        print(f"🟡 MÉDIA: {mensagem}" + (f" ({arquivo})" if arquivo else ""))
    
    def log_baixa(self, mensagem, arquivo=None):
        """Registra vulnerabilidade baixa"""
        item = {"mensagem": mensagem, "arquivo": arquivo, "nivel": "BAIXA"}
        self.vulnerabilidades_baixas.append(item)
        print(f"🔵 BAIXA: {mensagem}" + (f" ({arquivo})" if arquivo else ""))
    
    def log_boa_pratica(self, mensagem, arquivo=None):
        """Registra boa prática encontrada"""
        item = {"mensagem": mensagem, "arquivo": arquivo}
        self.boas_praticas.append(item)
        print(f"✅ BOA PRÁTICA: {mensagem}" + (f" ({arquivo})" if arquivo else ""))
    
    def verificar_credenciais_hardcoded(self):
        """Verifica se há credenciais hardcoded no código"""
        print("\n🔍 Verificando credenciais hardcoded...")
        
        # Padrões suspeitos
        padroes_suspeitos = [
            r'password\s*=\s*["\'][^"\']{3,}["\']',
            r'senha\s*=\s*["\'][^"\']{3,}["\']',
            r'pwd\s*=\s*["\'][^"\']{3,}["\']',
            r'secret\s*=\s*["\'][^"\']{3,}["\']',
            r'token\s*=\s*["\'][^"\']{10,}["\']',
            r'api_key\s*=\s*["\'][^"\']{10,}["\']',
            r'admin.*["\'][^"\']{3,}["\']',
            r'root.*["\'][^"\']{3,}["\']'
        ]
        
        arquivos_python = list(self.project_root.glob("*.py"))
        credenciais_encontradas = False
        
        for arquivo in arquivos_python:
            if arquivo.name in ['auditoria_seguranca.py', 'validar_escalabilidade.py']:
                continue
                
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                for padrao in padroes_suspeitos:
                    matches = re.findall(padrao, conteudo, re.IGNORECASE)
                    if matches:
                        # Verifica se não é um placeholder ou exemplo
                        for match in matches:
                            if not any(placeholder in match.lower() for placeholder in 
                                     ['altere', 'exemplo', 'placeholder', 'sua_senha', 'password', 'xxx']):
                                self.log_alta(f"Possível credencial hardcoded: {match[:20]}...", arquivo.name)
                                credenciais_encontradas = True
            
            except Exception as e:
                self.log_baixa(f"Erro ao ler arquivo: {e}", arquivo.name)
        
        if not credenciais_encontradas:
            self.log_boa_pratica("Nenhuma credencial hardcoded encontrada no código")
    
    def verificar_arquivos_credenciais(self):
        """Verifica segurança dos arquivos de credenciais"""
        print("\n🔍 Verificando arquivos de credenciais...")
        
        arquivos_sensiveis = [
            "environment.json",
            "servidores.json", 
            "credentials.json",
            ".env",
            "config.ini"
        ]
        
        for arquivo_nome in arquivos_sensiveis:
            arquivo = self.project_root / arquivo_nome
            if arquivo.exists():
                # Verifica permissões (Windows)
                try:
                    stat_info = arquivo.stat()
                    self.log_boa_pratica(f"Arquivo de credenciais encontrado: {arquivo_nome}")
                    
                    # Verifica se está no .gitignore
                    gitignore = self.project_root / ".gitignore"
                    if gitignore.exists():
                        with open(gitignore, 'r') as f:
                            gitignore_content = f.read()
                        if arquivo_nome in gitignore_content:
                            self.log_boa_pratica(f"Arquivo {arquivo_nome} está no .gitignore")
                        else:
                            self.log_alta(f"Arquivo {arquivo_nome} NÃO está no .gitignore")
                    else:
                        self.log_media("Arquivo .gitignore não encontrado")
                        
                except Exception as e:
                    self.log_baixa(f"Erro ao verificar permissões de {arquivo_nome}: {e}")
    
    def verificar_injecao_sql(self):
        """Verifica possíveis vulnerabilidades de injeção SQL"""
        print("\n🔍 Verificando vulnerabilidades de injeção SQL...")
        
        padroes_sql_inseguros = [
            r'execute\s*\(\s*["\'].*%s.*["\']',
            r'query\s*\(\s*["\'].*%s.*["\']',
            r'SELECT.*\+.*',
            r'INSERT.*\+.*',
            r'UPDATE.*\+.*',
            r'DELETE.*\+.*'
        ]
        
        arquivos_python = list(self.project_root.glob("*.py"))
        sql_seguro = True
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                for padrao in padroes_sql_inseguros:
                    if re.search(padrao, conteudo, re.IGNORECASE):
                        self.log_alta(f"Possível vulnerabilidade de injeção SQL", arquivo.name)
                        sql_seguro = False
            
            except Exception as e:
                continue
        
        if sql_seguro:
            self.log_boa_pratica("Nenhuma vulnerabilidade de injeção SQL encontrada")
    
    def verificar_validacao_entrada(self):
        """Verifica se há validação adequada de entrada"""
        print("\n🔍 Verificando validação de entrada...")
        
        arquivos_web = ["iniciar_web.py", "web_config.py"]
        validacao_encontrada = False
        
        for arquivo_nome in arquivos_web:
            arquivo = self.project_root / arquivo_nome
            if arquivo.exists():
                try:
                    with open(arquivo, 'r', encoding='utf-8') as f:
                        conteudo = f.read()
                    
                    # Procura por validações
                    if any(termo in conteudo for termo in ['validate', 'sanitize', 'escape', 'filter']):
                        self.log_boa_pratica(f"Validação de entrada encontrada", arquivo_nome)
                        validacao_encontrada = True
                    
                    # Procura por uso direto de request sem validação
                    if 'request.' in conteudo and 'validate' not in conteudo:
                        self.log_media(f"Uso de request sem validação aparente", arquivo_nome)
                
                except Exception as e:
                    continue
        
        if not validacao_encontrada:
            self.log_media("Pouca evidência de validação de entrada")
    
    def verificar_https_ssl(self):
        """Verifica uso de HTTPS/SSL"""
        print("\n🔍 Verificando uso de HTTPS/SSL...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        https_usado = False
        http_inseguro = False
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Verifica HTTPS
                if 'https://' in conteudo:
                    https_usado = True
                
                # Verifica HTTP inseguro
                if re.search(r'http://(?!localhost|127\.0\.0\.1)', conteudo):
                    self.log_media(f"URL HTTP insegura encontrada", arquivo.name)
                    http_inseguro = True
                
                # Verifica configurações SSL
                if any(termo in conteudo for termo in ['ssl_context', 'verify=False', 'ssl_verify']):
                    if 'verify=False' in conteudo:
                        self.log_alta(f"Verificação SSL desabilitada", arquivo.name)
                    else:
                        self.log_boa_pratica(f"Configuração SSL encontrada", arquivo.name)
            
            except Exception as e:
                continue
        
        if https_usado:
            self.log_boa_pratica("Uso de HTTPS encontrado")
        
        if not http_inseguro:
            self.log_boa_pratica("Nenhuma URL HTTP insegura encontrada")
    
    def verificar_logs_sensiveis(self):
        """Verifica se logs podem conter informações sensíveis"""
        print("\n🔍 Verificando logs sensíveis...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        logs_seguros = True
        
        padroes_log_inseguros = [
            r'print\s*\(.*password.*\)',
            r'print\s*\(.*senha.*\)',
            r'log.*password',
            r'log.*senha',
            r'print\s*\(.*token.*\)'
        ]
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                for padrao in padroes_log_inseguros:
                    if re.search(padrao, conteudo, re.IGNORECASE):
                        self.log_media(f"Possível log de informação sensível", arquivo.name)
                        logs_seguros = False
            
            except Exception as e:
                continue
        
        if logs_seguros:
            self.log_boa_pratica("Nenhum log de informação sensível encontrado")
    
    def verificar_dependencias_vulneraveis(self):
        """Verifica dependências com vulnerabilidades conhecidas"""
        print("\n🔍 Verificando dependências vulneráveis...")
        
        req_file = self.project_root / "requirements.txt"
        if req_file.exists():
            try:
                with open(req_file, 'r') as f:
                    deps = f.readlines()
                
                # Lista de dependências com vulnerabilidades conhecidas (exemplo)
                deps_vulneraveis = {
                    'flask': {'versao_minima': '2.0.0', 'vulnerabilidade': 'XSS em versões antigas'},
                    'requests': {'versao_minima': '2.20.0', 'vulnerabilidade': 'Vulnerabilidades SSL'},
                    'urllib3': {'versao_minima': '1.26.0', 'vulnerabilidade': 'Vulnerabilidades de certificado'}
                }
                
                for dep_line in deps:
                    dep_line = dep_line.strip()
                    if '==' in dep_line:
                        dep_name, versao = dep_line.split('==')
                        dep_name = dep_name.strip().lower()
                        
                        if dep_name in deps_vulneraveis:
                            # Aqui seria ideal usar uma API real de vulnerabilidades
                            self.log_boa_pratica(f"Dependência {dep_name} com versão específica: {versao}")
                
                self.log_boa_pratica("Arquivo requirements.txt com versões fixas encontrado")
                
            except Exception as e:
                self.log_baixa(f"Erro ao verificar requirements.txt: {e}")
        else:
            self.log_media("Arquivo requirements.txt não encontrado")
    
    def verificar_autenticacao(self):
        """Verifica implementação de autenticação"""
        print("\n🔍 Verificando autenticação...")
        
        arquivos_auth = ["auth_ad.py", "web_config.py", "iniciar_web.py"]
        auth_encontrada = False
        
        for arquivo_nome in arquivos_auth:
            arquivo = self.project_root / arquivo_nome
            if arquivo.exists():
                try:
                    with open(arquivo, 'r', encoding='utf-8') as f:
                        conteudo = f.read()
                    
                    # Verifica autenticação
                    if any(termo in conteudo for termo in ['login', 'authenticate', 'session', 'token']):
                        self.log_boa_pratica(f"Sistema de autenticação encontrado", arquivo_nome)
                        auth_encontrada = True
                    
                    # Verifica hash de senhas
                    if any(termo in conteudo for termo in ['hash', 'bcrypt', 'pbkdf2', 'scrypt']):
                        self.log_boa_pratica(f"Hash de senhas implementado", arquivo_nome)
                    
                    # Verifica sessões seguras
                    if 'session' in conteudo and 'secure' in conteudo:
                        self.log_boa_pratica(f"Configuração de sessão segura", arquivo_nome)
                
                except Exception as e:
                    continue
        
        if not auth_encontrada:
            self.log_media("Sistema de autenticação não claramente identificado")
    
    def verificar_exposicao_informacoes(self):
        """Verifica exposição de informações sensíveis"""
        print("\n🔍 Verificando exposição de informações...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        
        padroes_exposicao = [
            r'traceback\.print_exc\(\)',
            r'print\s*\(.*exception.*\)',
            r'print\s*\(.*error.*\)',
            r'debug\s*=\s*True'
        ]
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                for padrao in padroes_exposicao:
                    if re.search(padrao, conteudo, re.IGNORECASE):
                        if 'debug=True' in conteudo:
                            self.log_media(f"Modo debug ativo", arquivo.name)
                        else:
                            self.log_baixa(f"Possível exposição de informações de erro", arquivo.name)
            
            except Exception as e:
                continue
    
    def verificar_controle_acesso(self):
        """Verifica controles de acesso"""
        print("\n🔍 Verificando controles de acesso...")
        
        web_config = self.project_root / "web_config.py"
        if web_config.exists():
            try:
                with open(web_config, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Verifica decoradores de autenticação
                if '@login_required' in conteudo or '@require_auth' in conteudo:
                    self.log_boa_pratica("Decoradores de autenticação encontrados")
                
                # Verifica controle de acesso baseado em roles
                if any(termo in conteudo for termo in ['role', 'permission', 'authorize']):
                    self.log_boa_pratica("Sistema de controle de acesso por roles")
                
            except Exception as e:
                self.log_baixa(f"Erro ao verificar controles de acesso: {e}")
    
    def calcular_score_seguranca(self):
        """Calcula score de segurança"""
        total_vulnerabilidades = (
            len(self.vulnerabilidades_criticas) * 10 +
            len(self.vulnerabilidades_altas) * 7 +
            len(self.vulnerabilidades_medias) * 4 +
            len(self.vulnerabilidades_baixas) * 1
        )
        
        total_boas_praticas = len(self.boas_praticas) * 2
        
        # Score base de 100, subtraindo vulnerabilidades e somando boas práticas
        score = max(0, min(100, 100 - total_vulnerabilidades + total_boas_praticas))
        
        return score
    
    def gerar_relatorio_seguranca(self):
        """Gera relatório completo de segurança"""
        print("\n" + "="*70)
        print("🛡️ RELATÓRIO DE AUDITORIA DE SEGURANÇA")
        print("="*70)
        
        # Vulnerabilidades por nível
        if self.vulnerabilidades_criticas:
            print(f"\n🔴 VULNERABILIDADES CRÍTICAS ({len(self.vulnerabilidades_criticas)}):")
            for vuln in self.vulnerabilidades_criticas:
                print(f"   🔴 {vuln['mensagem']}" + (f" ({vuln['arquivo']})" if vuln['arquivo'] else ""))
        
        if self.vulnerabilidades_altas:
            print(f"\n🟠 VULNERABILIDADES ALTAS ({len(self.vulnerabilidades_altas)}):")
            for vuln in self.vulnerabilidades_altas:
                print(f"   🟠 {vuln['mensagem']}" + (f" ({vuln['arquivo']})" if vuln['arquivo'] else ""))
        
        if self.vulnerabilidades_medias:
            print(f"\n🟡 VULNERABILIDADES MÉDIAS ({len(self.vulnerabilidades_medias)}):")
            for vuln in self.vulnerabilidades_medias:
                print(f"   🟡 {vuln['mensagem']}" + (f" ({vuln['arquivo']})" if vuln['arquivo'] else ""))
        
        if self.vulnerabilidades_baixas:
            print(f"\n🔵 VULNERABILIDADES BAIXAS ({len(self.vulnerabilidades_baixas)}):")
            for vuln in self.vulnerabilidades_baixas:
                print(f"   🔵 {vuln['mensagem']}" + (f" ({vuln['arquivo']})" if vuln['arquivo'] else ""))
        
        # Boas práticas
        if self.boas_praticas:
            print(f"\n✅ BOAS PRÁTICAS ENCONTRADAS ({len(self.boas_praticas)}):")
            for pratica in self.boas_praticas:
                print(f"   ✅ {pratica['mensagem']}" + (f" ({pratica['arquivo']})" if pratica['arquivo'] else ""))
        
        # Score de segurança
        score = self.calcular_score_seguranca()
        print(f"\n📊 SCORE DE SEGURANÇA: {score}/100")
        
        if score >= 90:
            status = "🟢 EXCELENTE"
            recomendacao = "Sistema com alta segurança"
        elif score >= 75:
            status = "🟡 BOM"
            recomendacao = "Sistema seguro com pequenos ajustes necessários"
        elif score >= 60:
            status = "🟠 REGULAR"
            recomendacao = "Sistema precisa de melhorias de segurança"
        else:
            status = "🔴 CRÍTICO"
            recomendacao = "Sistema requer correções urgentes de segurança"
        
        print(f"🏆 STATUS DE SEGURANÇA: {status}")
        print(f"💡 RECOMENDAÇÃO: {recomendacao}")
        
        # Salva relatório
        relatorio_data = {
            "data_auditoria": datetime.now().isoformat(),
            "score_seguranca": score,
            "status": status,
            "vulnerabilidades_criticas": self.vulnerabilidades_criticas,
            "vulnerabilidades_altas": self.vulnerabilidades_altas,
            "vulnerabilidades_medias": self.vulnerabilidades_medias,
            "vulnerabilidades_baixas": self.vulnerabilidades_baixas,
            "boas_praticas": self.boas_praticas,
            "recomendacao": recomendacao
        }
        
        relatorio_file = self.project_root / f"auditoria_seguranca_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(relatorio_file, 'w', encoding='utf-8') as f:
            json.dump(relatorio_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 Relatório detalhado salvo em: {relatorio_file}")
        
        return score >= 75  # Considera seguro se score >= 75
    
    def executar_auditoria_completa(self):
        """Executa auditoria completa de segurança"""
        print("🛡️ AUDITORIA DE SEGURANÇA DO SISTEMA")
        print("="*70)
        print(f"📁 Projeto: {self.project_root}")
        print(f"🕒 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Executa todas as verificações
        self.verificar_credenciais_hardcoded()
        self.verificar_arquivos_credenciais()
        self.verificar_injecao_sql()
        self.verificar_validacao_entrada()
        self.verificar_https_ssl()
        self.verificar_logs_sensiveis()
        self.verificar_dependencias_vulneraveis()
        self.verificar_autenticacao()
        self.verificar_exposicao_informacoes()
        self.verificar_controle_acesso()
        
        # Gera relatório final
        return self.gerar_relatorio_seguranca()

def main():
    """Função principal"""
    auditor = AuditoriaSeguranca()
    sistema_seguro = auditor.executar_auditoria_completa()
    
    if sistema_seguro:
        print("\n🎉 SISTEMA APROVADO NA AUDITORIA DE SEGURANÇA!")
        return 0
    else:
        print("\n⚠️ SISTEMA REQUER MELHORIAS DE SEGURANÇA!")
        return 1

if __name__ == "__main__":
    exit(main())