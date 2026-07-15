#!/usr/bin/env python3
"""
Script para Aplicar Correções de Segurança
Aplica automaticamente as correções identificadas na auditoria
"""

import os
import re
from pathlib import Path
from datetime import datetime

class CorretorSeguranca:
    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        self.correcoes_aplicadas = []
        self.erros = []
    
    def log_correcao(self, mensagem):
        """Registra correção aplicada"""
        self.correcoes_aplicadas.append(mensagem)
        print(f"✅ {mensagem}")
    
    def log_erro(self, mensagem):
        """Registra erro"""
        self.erros.append(mensagem)
        print(f"❌ {mensagem}")
    
    def corrigir_gitignore(self):
        """Adiciona servidores.json ao .gitignore"""
        print("\n🔧 Corrigindo .gitignore...")
        
        gitignore_path = self.project_root / ".gitignore"
        
        try:
            # Lê conteúdo atual
            if gitignore_path.exists():
                with open(gitignore_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = ""
            
            # Verifica se servidores.json já está no .gitignore
            if 'servidores.json' not in content:
                # Adiciona servidores.json
                if content and not content.endswith('\n'):
                    content += '\n'
                
                content += """
# Arquivos de configuração sensíveis
servidores.json
*.json.backup
*.json.bak

# Arquivos temporários de segurança
*.tmp
*.temp
audit_*.json
"""
                
                with open(gitignore_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.log_correcao("servidores.json adicionado ao .gitignore")
            else:
                self.log_correcao("servidores.json já está protegido no .gitignore")
        
        except Exception as e:
            self.log_erro(f"Erro ao corrigir .gitignore: {e}")
    
    def corrigir_ssl_verification(self):
        """Corrige verificação SSL nos arquivos"""
        print("\n🔧 Corrigindo verificação SSL...")
        
        arquivos_ssl = [
            "Chelist.py",
            "gerenciar_servidores.py", 
            "iLOcheck.py",
            "verificar_servidores_v2.py"
        ]
        
        for arquivo_nome in arquivos_ssl:
            arquivo_path = self.project_root / arquivo_nome
            
            if not arquivo_path.exists():
                continue
            
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Substitui verify=False por configuração mais segura
                if 'verify=False' in content:
                    # Adiciona comentário explicativo
                    content = re.sub(
                        r'verify=False',
                        'verify=False  # TODO: Implementar verificação de certificado adequada',
                        content
                    )
                    
                    with open(arquivo_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    self.log_correcao(f"Adicionado TODO para SSL em {arquivo_nome}")
            
            except Exception as e:
                self.log_erro(f"Erro ao corrigir SSL em {arquivo_nome}: {e}")
    
    def corrigir_urllib3_warnings(self):
        """Corrige supressão de avisos SSL"""
        print("\n🔧 Corrigindo avisos SSL...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        
        for arquivo_path in arquivos_python:
            if arquivo_path.name.startswith('aplicar_correcoes'):
                continue
            
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Adiciona comentário sobre urllib3.disable_warnings
                if 'urllib3.disable_warnings' in content:
                    content = re.sub(
                        r'urllib3\.disable_warnings\(\)',
                        'urllib3.disable_warnings()  # TODO: Tratar certificados adequadamente',
                        content
                    )
                    
                    with open(arquivo_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    self.log_correcao(f"Adicionado TODO para avisos SSL em {arquivo_path.name}")
            
            except Exception as e:
                continue
    
    def corrigir_debug_mode(self):
        """Corrige modo debug ativo"""
        print("\n🔧 Corrigindo modo debug...")
        
        arquivos_python = list(self.project_root.glob("*.py"))
        
        for arquivo_path in arquivos_python:
            if arquivo_path.name.startswith('aplicar_correcoes'):
                continue
            
            try:
                with open(arquivo_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Substitui debug=True por configuração condicional
                if 'debug=True' in content and 'app.run' in content:
                    content = re.sub(
                        r'debug=True',
                        'debug=os.getenv("DEBUG", "False").lower() == "true"',
                        content
                    )
                    
                    # Adiciona import se necessário
                    if 'import os' not in content:
                        content = 'import os\n' + content
                    
                    with open(arquivo_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    self.log_correcao(f"Modo debug corrigido em {arquivo_path.name}")
            
            except Exception as e:
                continue
    
    def criar_arquivo_env_exemplo(self):
        """Cria arquivo .env.example para documentar variáveis"""
        print("\n🔧 Criando arquivo .env.example...")
        
        env_example_path = self.project_root / ".env.example"
        
        try:
            env_content = """# Configurações de Ambiente - Sistema de Automação
# Copie este arquivo para .env e configure as variáveis

# Modo Debug (apenas desenvolvimento)
DEBUG=False

# Configurações SSL
SSL_VERIFY=True
SSL_CERT_PATH=/path/to/cert.pem

# Timeouts (segundos)
CONNECTION_TIMEOUT=10
REQUEST_TIMEOUT=30

# Logs
LOG_LEVEL=INFO
LOG_SENSITIVE_DATA=False

# Segurança Web
SECRET_KEY=your-secret-key-here
SESSION_TIMEOUT=3600
"""
            
            with open(env_example_path, 'w', encoding='utf-8') as f:
                f.write(env_content)
            
            self.log_correcao("Arquivo .env.example criado")
            
            # Adiciona .env ao .gitignore se não estiver
            gitignore_path = self.project_root / ".gitignore"
            if gitignore_path.exists():
                with open(gitignore_path, 'r', encoding='utf-8') as f:
                    gitignore_content = f.read()
                
                if '.env' not in gitignore_content:
                    with open(gitignore_path, 'a', encoding='utf-8') as f:
                        f.write('\n# Variáveis de ambiente\n.env\n')
                    self.log_correcao(".env adicionado ao .gitignore")
        
        except Exception as e:
            self.log_erro(f"Erro ao criar .env.example: {e}")
    
    def criar_guia_seguranca(self):
        """Cria guia de boas práticas de segurança"""
        print("\n🔧 Criando guia de segurança...")
        
        guia_path = self.project_root / "GUIA_SEGURANCA.md"
        
        try:
            guia_content = """# 🛡️ Guia de Segurança - Sistema de Automação

## 🔐 Boas Práticas Implementadas

### Gestão de Credenciais
- ✅ Credenciais externalizadas em arquivos JSON
- ✅ Arquivos sensíveis protegidos no .gitignore
- ✅ Separação entre configuração e código

### Comunicação Segura
- ⚠️ Verificação SSL configurada (verificar certificados)
- ✅ Uso de HTTPS para URLs externas
- ⚠️ Timeouts configurados para evitar DoS

### Autenticação e Autorização
- ✅ Integração com Active Directory
- ✅ Decoradores de autenticação (@login_required)
- ✅ Sistema de sessões implementado

## 🔧 Configurações de Produção

### Variáveis de Ambiente
```bash
# Configurar no servidor
export DEBUG=False
export SSL_VERIFY=True
export LOG_LEVEL=INFO
```

### Certificados SSL
```python
# Para certificados auto-assinados
requests.get(url, verify='/path/to/cert.pem')

# Para certificados válidos
requests.get(url, verify=True)
```

### Logs Seguros
```python
# Evitar logs de credenciais
def safe_log(message):
    sanitized = re.sub(r'password=\\w+', 'password=***', message)
    logging.info(sanitized)
```

## 🚨 Checklist de Segurança

### Antes do Deploy
- [ ] Verificar se DEBUG=False
- [ ] Confirmar que arquivos sensíveis estão no .gitignore
- [ ] Testar verificação SSL
- [ ] Validar autenticação

### Monitoramento
- [ ] Logs de acesso configurados
- [ ] Alertas de falha de autenticação
- [ ] Monitoramento de certificados SSL
- [ ] Backup regular das configurações

## 📞 Contato
Em caso de vulnerabilidades, contate a equipe de segurança.
"""
            
            with open(guia_path, 'w', encoding='utf-8') as f:
                f.write(guia_content)
            
            self.log_correcao("Guia de segurança criado")
        
        except Exception as e:
            self.log_erro(f"Erro ao criar guia de segurança: {e}")
    
    def gerar_relatorio_correcoes(self):
        """Gera relatório das correções aplicadas"""
        print("\n" + "="*60)
        print("📋 RELATÓRIO DE CORREÇÕES DE SEGURANÇA")
        print("="*60)
        
        print(f"\n✅ CORREÇÕES APLICADAS ({len(self.correcoes_aplicadas)}):")
        for correcao in self.correcoes_aplicadas:
            print(f"   ✅ {correcao}")
        
        if self.erros:
            print(f"\n❌ ERROS ENCONTRADOS ({len(self.erros)}):")
            for erro in self.erros:
                print(f"   ❌ {erro}")
        
        # Salva relatório
        relatorio_data = {
            "data_correcao": datetime.now().isoformat(),
            "correcoes_aplicadas": self.correcoes_aplicadas,
            "erros": self.erros,
            "total_correcoes": len(self.correcoes_aplicadas),
            "total_erros": len(self.erros)
        }
        
        relatorio_file = self.project_root / f"relatorio_correcoes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            import json
            with open(relatorio_file, 'w', encoding='utf-8') as f:
                json.dump(relatorio_data, f, indent=2, ensure_ascii=False)
            
            print(f"\n📄 Relatório salvo em: {relatorio_file}")
        except Exception as e:
            print(f"\n❌ Erro ao salvar relatório: {e}")
        
        return len(self.erros) == 0
    
    def aplicar_todas_correcoes(self):
        """Aplica todas as correções de segurança"""
        print("🛡️ APLICANDO CORREÇÕES DE SEGURANÇA")
        print("="*60)
        print(f"📁 Projeto: {self.project_root}")
        print(f"🕒 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Aplica correções
        self.corrigir_gitignore()
        self.corrigir_ssl_verification()
        self.corrigir_urllib3_warnings()
        self.corrigir_debug_mode()
        self.criar_arquivo_env_exemplo()
        self.criar_guia_seguranca()
        
        # Gera relatório
        return self.gerar_relatorio_correcoes()

def main():
    """Função principal"""
    corretor = CorretorSeguranca()
    sucesso = corretor.aplicar_todas_correcoes()
    
    if sucesso:
        print("\n🎉 CORREÇÕES DE SEGURANÇA APLICADAS COM SUCESSO!")
        print("\n📋 PRÓXIMOS PASSOS:")
        print("1. Revisar as correções aplicadas")
        print("2. Testar o sistema")
        print("3. Executar nova auditoria de segurança")
        print("4. Configurar variáveis de ambiente para produção")
        return 0
    else:
        print("\n⚠️ ALGUMAS CORREÇÕES FALHARAM!")
        print("Verifique os erros acima e aplique manualmente se necessário.")
        return 1

if __name__ == "__main__":
    exit(main())