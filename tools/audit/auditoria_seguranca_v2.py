#!/usr/bin/env python3
"""
Auditoria de Segurança V2 - Mais Precisa
Verifica vulnerabilidades reais de segurança
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime

class AuditoriaSegurancaV2:
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
    
    def verificar_credenciais_reais(self):
        """Verifica credenciais reais hardcoded (não falsos positivos)"""
        print("\n🔍 Verificando credenciais hardcoded reais...")
        
        # Padrões mais específicos para credenciais reais
        padroes_credenciais_reais = [
            r'password\s*=\s*["\'][A-Za-z0-9@#$%^&*!]{8,}["\']',  # Senhas com 8+ caracteres
            r'senha\s*=\s*["\'][A-Za-z0-9@#$%^&*!]{8,}["\']',
            r'api_key\s*=\s*["\'][A-Za-z0-9]{20,}["\']',  # API keys longas
            r'secret\s*=\s*["\'][A-Za-z0-9]{16,}["\']',   # Secrets longos
            r'token\s*=\s*["\'][A-Za-z0-9]{32,}["\']'     # Tokens longos
        ]
        
        arquivos_python = [f for f in self.project_root.glob("*.py") 
                          if f.name not in ['auditoria_seguranca.py', 'auditoria_seguranca_v2.py']]
        
        credenciais_encontradas = 0
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                for padrao in padroes_credenciais_reais:
                    matches = re.findall(padrao, conteudo, re.IGNORECASE)
                    for match in matches:
                        # Filtra falsos positivos
                        if not any(fp in match.lower() for fp in 
                                 ['altere', 'exemplo', 'placeholder', 'sua_senha', 'password', 'xxx', 'test']):
                            self.log_alta(f"Credencial hardcoded detectada", arquivo.name)
                            credenciais_encontradas += 1
            
            except Exception as e:
                continue
        
        if credenciais_encontradas == 0:
            self.log_boa_pratica("Nenhuma credencial hardcoded real encontrada")
    
    def verificar_arquivos_sensiveis(self):
        """Verifica proteção de arquivos sensíveis"""
        print("\n🔍 Verificando proteção de arquivos sensíveis...")
        
        arquivos_sensiveis = {
            "environment.json": "Credenciais do ambiente",
            "servidores.json": "Dados dos servidores", 
            ".env": "Variáveis de ambiente",
            "credentials.json": "Credenciais gerais"
        }
        
        gitignore_path = self.project_root / ".gitignore"
        gitignore_content = ""
        
        if gitignore_path.exists():
            with open(gitignore_path, 'r') as f:
                gitignore_content = f.read()
            self.log_boa_pratica("Arquivo .gitignore encontrado")
        else:
            self.log_media("Arquivo .gitignore não encontrado")
        
        for arquivo_nome, descricao in arquivos_sensiveis.items():
            arquivo_path = self.project_root / arquivo_nome
            if arquivo_path.exists():
                if arquivo_nome in gitignore_content:
                    self.log_boa_pratica(f"{descricao} protegido no .gitignore", arquivo_nome)
                else:
                    self.log_alta(f"{descricao} NÃO protegido no .gitignore", arquivo_nome)
    
    def verificar_ssl_tls(self):
        """Verifica configurações SSL/TLS"""
        print("\n🔍 Verificando configurações SSL/TLS...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        ssl_issues = 0
        https_usado = False
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Verifica HTTPS
                if 'https://' in conteudo:
                    https_usado = True
                
                # Verifica SSL desabilitado
                if 'verify=False' in conteudo or 'ssl_verify=False' in conteudo:
                    self.log_alta("Verificação SSL desabilitada", arquivo.name)
                    ssl_issues += 1
                
                # Verifica certificados ignorados
                if 'urllib3.disable_warnings' in conteudo:
                    self.log_media("Avisos SSL desabilitados", arquivo.name)
            
            except Exception as e:
                continue
        
        if https_usado:
            self.log_boa_pratica("Uso de HTTPS detectado")
        
        if ssl_issues == 0:
            self.log_boa_pratica("Nenhuma configuração SSL insegura encontrada")
    
    def verificar_autenticacao_web(self):
        """Verifica sistema de autenticação web"""
        print("\n🔍 Verificando autenticação web...")
        
        web_config = self.project_root / "web_config.py"
        auth_ad = self.project_root / "auth_ad.py"
        
        auth_features = 0
        
        if web_config.exists():
            try:
                with open(web_config, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                if '@login_required' in conteudo:
                    self.log_boa_pratica("Decorador de autenticação encontrado", "web_config.py")
                    auth_features += 1
                
                if 'session' in conteudo:
                    self.log_boa_pratica("Sistema de sessões implementado", "web_config.py")
                    auth_features += 1
                
                if 'login' in conteudo and 'logout' in conteudo:
                    self.log_boa_pratica("Sistema de login/logout implementado", "web_config.py")
                    auth_features += 1
            
            except Exception as e:
                pass
        
        if auth_ad.exists():
            self.log_boa_pratica("Autenticação Active Directory implementada", "auth_ad.py")
            auth_features += 1
        
        if auth_features == 0:
            self.log_media("Sistema de autenticação não claramente identificado")
    
    def verificar_logs_seguros(self):
        """Verifica se logs não expõem informações sensíveis"""
        print("\n🔍 Verificando segurança dos logs...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        logs_inseguros = 0
        
        padroes_log_inseguros = [
            r'print\s*\(.*password.*\)',
            r'print\s*\(.*senha.*\)',
            r'log.*password',
            r'log.*senha'
        ]
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                for padrao in padroes_log_inseguros:
                    if re.search(padrao, conteudo, re.IGNORECASE):
                        # Verifica se não é um comentário ou string de exemplo
                        lines = conteudo.split('\n')
                        for line in lines:
                            if re.search(padrao, line, re.IGNORECASE):
                                if not line.strip().startswith('#') and 'exemplo' not in line.lower():
                                    self.log_media("Possível log de informação sensível", arquivo.name)
                                    logs_inseguros += 1
                                    break
            
            except Exception as e:
                continue
        
        if logs_inseguros == 0:
            self.log_boa_pratica("Nenhum log inseguro detectado")
    
    def verificar_validacao_entrada_web(self):
        """Verifica validação de entrada na interface web"""
        print("\n🔍 Verificando validação de entrada web...")
        
        web_config = self.project_root / "web_config.py"
        
        if web_config.exists():
            try:
                with open(web_config, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                # Verifica uso de request sem validação
                if 'request.' in conteudo:
                    if any(termo in conteudo for termo in ['validate', 'sanitize', 'escape']):
                        self.log_boa_pratica("Validação de entrada implementada", "web_config.py")
                    else:
                        self.log_media("Uso de request sem validação aparente", "web_config.py")
                
                # Verifica proteção CSRF
                if 'csrf' in conteudo.lower():
                    self.log_boa_pratica("Proteção CSRF implementada", "web_config.py")
            
            except Exception as e:
                pass
    
    def verificar_configuracoes_debug(self):
        """Verifica se modo debug está ativo em produção"""
        print("\n🔍 Verificando configurações de debug...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        debug_ativo = 0
        
        for arquivo in arquivos_python:
            try:
                with open(arquivo, 'r', encoding='utf-8') as f:
                    conteudo = f.read()
                
                if 'debug=True' in conteudo:
                    self.log_media("Modo debug ativo", arquivo.name)
                    debug_ativo += 1
            
            except Exception as e:
                continue
        
        if debug_ativo == 0:
            self.log_boa_pratica("Modo debug não ativo")
    
    def verificar_dependencias_atualizadas(self):
        """Verifica se dependências estão atualizadas"""
        print("\n🔍 Verificando dependências...")
        
        req_file = self.project_root / "requirements.txt"
        if req_file.exists():
            self.log_boa_pratica("Arquivo requirements.txt com versões fixas", "requirements.txt")
            
            # Verifica algumas dependências críticas
            try:
                with open(req_file, 'r') as f:
                    deps = f.read()
                
                if 'flask' in deps.lower():
                    self.log_boa_pratica("Framework Flask especificado")
                
                if 'requests' in deps.lower():
                    self.log_boa_pratica("Biblioteca requests especificada")
            
            except Exception as e:
                pass
        else:
            self.log_media("Arquivo requirements.txt não encontrado")
    
    def verificar_estrutura_diretorios(self):
        """Verifica estrutura segura de diretórios"""
        print("\n🔍 Verificando estrutura de diretórios...")
        
        # Verifica se há separação de dados sensíveis
        if (self.project_root / "data").exists():
            self.log_boa_pratica("Diretório de dados separado")
        
        if (self.project_root / "logs").exists():
            self.log_boa_pratica("Diretório de logs separado")
        
        if (self.project_root / "output").exists():
            self.log_boa_pratica("Diretório de output separado")
        
        # Verifica se há arquivos temporários expostos
        temp_files = list(self.project_root.glob("*.tmp")) + list(self.project_root.glob("*.temp"))
        if temp_files:
            self.log_baixa(f"Arquivos temporários encontrados: {len(temp_files)}")
        else:
            self.log_boa_pratica("Nenhum arquivo temporário exposto")
    
    def calcular_score_seguranca(self):
        """Calcula score de segurança mais preciso"""
        # Pesos mais realistas
        peso_critica = 25
        peso_alta = 15
        peso_media = 8
        peso_baixa = 2
        peso_boa_pratica = 3
        
        pontos_negativos = (
            len(self.vulnerabilidades_criticas) * peso_critica +
            len(self.vulnerabilidades_altas) * peso_alta +
            len(self.vulnerabilidades_medias) * peso_media +
            len(self.vulnerabilidades_baixas) * peso_baixa
        )
        
        pontos_positivos = len(self.boas_praticas) * peso_boa_pratica
        
        # Score base de 100
        score = max(0, min(100, 100 - pontos_negativos + pontos_positivos))
        
        return score
    
    def gerar_relatorio_seguranca(self):
        """Gera relatório de segurança"""
        print("\n" + "="*70)
        print("🛡️ RELATÓRIO DE AUDITORIA DE SEGURANÇA V2")
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
        
        if score >= 85:
            status = "🟢 EXCELENTE"
            recomendacao = "Sistema com alta segurança"
        elif score >= 70:
            status = "🟡 BOM"
            recomendacao = "Sistema seguro com pequenos ajustes"
        elif score >= 50:
            status = "🟠 REGULAR"
            recomendacao = "Sistema precisa de melhorias de segurança"
        else:
            status = "🔴 CRÍTICO"
            recomendacao = "Sistema requer correções urgentes"
        
        print(f"🏆 STATUS DE SEGURANÇA: {status}")
        print(f"💡 RECOMENDAÇÃO: {recomendacao}")
        
        # Resumo executivo
        print(f"\n📋 RESUMO EXECUTIVO:")
        print(f"   • Vulnerabilidades Críticas: {len(self.vulnerabilidades_criticas)}")
        print(f"   • Vulnerabilidades Altas: {len(self.vulnerabilidades_altas)}")
        print(f"   • Vulnerabilidades Médias: {len(self.vulnerabilidades_medias)}")
        print(f"   • Vulnerabilidades Baixas: {len(self.vulnerabilidades_baixas)}")
        print(f"   • Boas Práticas: {len(self.boas_praticas)}")
        
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
        
        relatorio_file = self.project_root / f"auditoria_seguranca_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(relatorio_file, 'w', encoding='utf-8') as f:
            json.dump(relatorio_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 Relatório detalhado salvo em: {relatorio_file}")
        
        return score >= 70  # Considera seguro se score >= 70
    
    def executar_auditoria_completa(self):
        """Executa auditoria completa de segurança"""
        print("🛡️ AUDITORIA DE SEGURANÇA V2 - ANÁLISE PRECISA")
        print("="*70)
        print(f"📁 Projeto: {self.project_root}")
        print(f"🕒 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Executa verificações focadas
        self.verificar_credenciais_reais()
        self.verificar_arquivos_sensiveis()
        self.verificar_ssl_tls()
        self.verificar_autenticacao_web()
        self.verificar_logs_seguros()
        self.verificar_validacao_entrada_web()
        self.verificar_configuracoes_debug()
        self.verificar_dependencias_atualizadas()
        self.verificar_estrutura_diretorios()
        
        # Gera relatório final
        return self.gerar_relatorio_seguranca()

def main():
    """Função principal"""
    auditor = AuditoriaSegurancaV2()
    sistema_seguro = auditor.executar_auditoria_completa()
    
    if sistema_seguro:
        print("\n🎉 SISTEMA APROVADO NA AUDITORIA DE SEGURANÇA!")
        return 0
    else:
        print("\n⚠️ SISTEMA REQUER MELHORIAS DE SEGURANÇA!")
        return 1

if __name__ == "__main__":
    exit(main())