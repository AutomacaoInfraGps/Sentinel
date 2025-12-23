"""
Sistema de Templates de Configuração
Fornece configurações pré-definidas para diferentes tipos de ambiente
"""

import json
from pathlib import Path
from typing import Dict, List
from config import PROJECT_ROOT

class TemplatesConfiguracao:
    """Gerenciador de templates de configuração"""
    
    def __init__(self):
        self.templates_dir = PROJECT_ROOT / "templates"
        self.templates_dir.mkdir(exist_ok=True)
        self._criar_templates_padrao()
    
    def _criar_templates_padrao(self):
        """Cria templates padrão se não existirem"""
        templates = {
            "empresa_pequena": self._template_empresa_pequena(),
            "empresa_media": self._template_empresa_media(),
            "empresa_grande": self._template_empresa_grande(),
            "desenvolvimento": self._template_desenvolvimento(),
            "producao": self._template_producao()
        }
        
        for nome, template in templates.items():
            arquivo = self.templates_dir / f"{nome}.json"
            if not arquivo.exists():
                self._salvar_template(nome, template)
    
    def _template_empresa_pequena(self) -> Dict:
        """Template para empresa pequena (1-3 servidores)"""
        return {
            "nome": "Empresa Pequena",
            "descricao": "Configuração para empresas pequenas com poucos servidores",
            "ambiente": "pequeno",
            "configuracao": {
                "naos_server": {
                    "ip": "192.168.1.10",
                    "usuario": "admin",
                    "senha": "ALTERE_AQUI"
                },
                "unifi_controller": {
                    "host": "192.168.1.20",
                    "port": 8443,
                    "username": "admin",
                    "password": "ALTERE_AQUI"
                },
                "gps_amigo": {
                    "url": "https://gpsamigo.com.br/login.php"
                },
                "timeouts": {
                    "connection_timeout": 15,
                    "max_retries": 2
                },
                "cleanup": {
                    "remove_temp_files": True,
                    "keep_logs": False
                }
            },
            "servidores_exemplo": [
                {
                    "nome": "Servidor Principal",
                    "tipo": "idrac",
                    "ip": "192.168.1.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "principal",
                    "descricao": "Servidor principal da empresa"
                }
            ]
        }
    
    def _template_empresa_media(self) -> Dict:
        """Template para empresa média (4-10 servidores)"""
        return {
            "nome": "Empresa Média",
            "descricao": "Configuração para empresas médias com múltiplas regionais",
            "ambiente": "medio",
            "configuracao": {
                "naos_server": {
                    "ip": "10.0.1.10",
                    "usuario": "domain\\admin",
                    "senha": "ALTERE_AQUI"
                },
                "unifi_controller": {
                    "host": "10.0.1.20",
                    "port": 8443,
                    "username": "admin",
                    "password": "ALTERE_AQUI"
                },
                "gps_amigo": {
                    "url": "https://gpsamigo.com.br/login.php"
                },
                "timeouts": {
                    "connection_timeout": 10,
                    "max_retries": 3
                },
                "cleanup": {
                    "remove_temp_files": True,
                    "keep_logs": True
                }
            },
            "servidores_exemplo": [
                {
                    "nome": "Matriz Principal",
                    "tipo": "idrac",
                    "ip": "10.0.1.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "matriz",
                    "descricao": "Servidor principal da matriz"
                },
                {
                    "nome": "Regional SP",
                    "tipo": "idrac",
                    "ip": "10.1.1.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "regionais",
                    "descricao": "Servidor regional São Paulo"
                },
                {
                    "nome": "Regional RJ",
                    "tipo": "ilo",
                    "ip": "10.2.1.100",
                    "usuario": "administrator",
                    "senha": "ALTERE_AQUI",
                    "grupo": "regionais",
                    "descricao": "Servidor regional Rio de Janeiro"
                }
            ]
        }
    
    def _template_empresa_grande(self) -> Dict:
        """Template para empresa grande (10+ servidores)"""
        return {
            "nome": "Empresa Grande",
            "descricao": "Configuração para empresas grandes com múltiplas regionais e filiais",
            "ambiente": "grande",
            "configuracao": {
                "naos_server": {
                    "ip": "172.16.1.10",
                    "usuario": "empresa\\admin.sistema",
                    "senha": "ALTERE_AQUI"
                },
                "unifi_controller": {
                    "host": "172.16.1.20",
                    "port": 8443,
                    "username": "admin.rede",
                    "password": "ALTERE_AQUI"
                },
                "gps_amigo": {
                    "url": "https://gpsamigo.com.br/login.php"
                },
                "timeouts": {
                    "connection_timeout": 8,
                    "max_retries": 5
                },
                "cleanup": {
                    "remove_temp_files": True,
                    "keep_logs": True
                }
            },
            "servidores_exemplo": [
                {
                    "nome": "Datacenter Principal",
                    "tipo": "idrac",
                    "ip": "172.16.1.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "datacenter",
                    "descricao": "Servidor principal do datacenter"
                },
                {
                    "nome": "Regional Norte",
                    "tipo": "idrac",
                    "ip": "172.16.10.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "regionais",
                    "descricao": "Servidor regional Norte"
                },
                {
                    "nome": "Regional Sul",
                    "tipo": "ilo",
                    "ip": "172.16.20.100",
                    "usuario": "administrator",
                    "senha": "ALTERE_AQUI",
                    "grupo": "regionais",
                    "descricao": "Servidor regional Sul"
                },
                {
                    "nome": "Filial SP Capital",
                    "tipo": "idrac",
                    "ip": "172.16.30.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "filiais",
                    "descricao": "Servidor filial São Paulo Capital"
                }
            ]
        }
    
    def _template_desenvolvimento(self) -> Dict:
        """Template para ambiente de desenvolvimento"""
        return {
            "nome": "Desenvolvimento",
            "descricao": "Configuração para ambiente de desenvolvimento e testes",
            "ambiente": "desenvolvimento",
            "configuracao": {
                "naos_server": {
                    "ip": "192.168.100.10",
                    "usuario": "dev\\admin",
                    "senha": "ALTERE_AQUI"
                },
                "unifi_controller": {
                    "host": "192.168.100.20",
                    "port": 8443,
                    "username": "admin",
                    "password": "ALTERE_AQUI"
                },
                "gps_amigo": {
                    "url": "https://gpsamigo.com.br/login.php"
                },
                "timeouts": {
                    "connection_timeout": 20,
                    "max_retries": 1
                },
                "cleanup": {
                    "remove_temp_files": False,
                    "keep_logs": True
                }
            },
            "servidores_exemplo": [
                {
                    "nome": "Servidor Dev",
                    "tipo": "idrac",
                    "ip": "192.168.100.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "desenvolvimento",
                    "descricao": "Servidor de desenvolvimento"
                },
                {
                    "nome": "Servidor Teste",
                    "tipo": "ilo",
                    "ip": "192.168.100.101",
                    "usuario": "administrator",
                    "senha": "ALTERE_AQUI",
                    "grupo": "teste",
                    "descricao": "Servidor de testes"
                }
            ]
        }
    
    def _template_producao(self) -> Dict:
        """Template para ambiente de produção"""
        return {
            "nome": "Produção",
            "descricao": "Configuração otimizada para ambiente de produção",
            "ambiente": "producao",
            "configuracao": {
                "naos_server": {
                    "ip": "10.0.0.10",
                    "usuario": "prod\\admin.sistema",
                    "senha": "ALTERE_AQUI"
                },
                "unifi_controller": {
                    "host": "10.0.0.20",
                    "port": 8443,
                    "username": "admin.rede",
                    "password": "ALTERE_AQUI"
                },
                "gps_amigo": {
                    "url": "https://gpsamigo.com.br/login.php"
                },
                "timeouts": {
                    "connection_timeout": 5,
                    "max_retries": 3
                },
                "cleanup": {
                    "remove_temp_files": True,
                    "keep_logs": True
                }
            },
            "servidores_exemplo": [
                {
                    "nome": "Prod Primary",
                    "tipo": "idrac",
                    "ip": "10.0.0.100",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "producao",
                    "descricao": "Servidor primário de produção"
                },
                {
                    "nome": "Prod Secondary",
                    "tipo": "idrac",
                    "ip": "10.0.0.101",
                    "usuario": "root",
                    "senha": "ALTERE_AQUI",
                    "grupo": "producao",
                    "descricao": "Servidor secundário de produção"
                }
            ]
        }
    
    def listar_templates(self) -> List[str]:
        """Lista todos os templates disponíveis"""
        templates = []
        for arquivo in self.templates_dir.glob("*.json"):
            templates.append(arquivo.stem)
        return sorted(templates)
    
    def carregar_template(self, nome: str) -> Dict:
        """Carrega um template específico"""
        arquivo = self.templates_dir / f"{nome}.json"
        if not arquivo.exists():
            raise FileNotFoundError(f"Template '{nome}' não encontrado")
        
        try:
            with open(arquivo, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Template '{nome}' tem formato inválido: {e}")
    
    def _salvar_template(self, nome: str, template: Dict):
        """Salva um template"""
        arquivo = self.templates_dir / f"{nome}.json"
        try:
            with open(arquivo, 'w', encoding='utf-8') as f:
                json.dump(template, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Erro ao salvar template '{nome}': {e}")
    
    def aplicar_template(self, nome: str) -> bool:
        """Aplica um template ao sistema"""
        try:
            template = self.carregar_template(nome)
            
            # Aplica configuração do environment.json
            env_file = PROJECT_ROOT / "environment.json"
            with open(env_file, 'w', encoding='utf-8') as f:
                json.dump(template['configuracao'], f, indent=2, ensure_ascii=False)
            
            print(f"✅ Template '{nome}' aplicado com sucesso!")
            print(f"📝 Descrição: {template.get('descricao', 'N/A')}")
            
            # Mostra servidores de exemplo
            servidores_exemplo = template.get('servidores_exemplo', [])
            if servidores_exemplo:
                print(f"\n📋 Servidores de exemplo ({len(servidores_exemplo)}):")
                for servidor in servidores_exemplo:
                    print(f"   • {servidor['nome']} ({servidor['tipo'].upper()}) - {servidor['ip']}")
                print("\n💡 Use 'python manage.py add' para adicionar servidores reais")
            
            return True
            
        except Exception as e:
            print(f"❌ Erro ao aplicar template: {e}")
            return False
    
    def criar_template_personalizado(self, nome: str, descricao: str = "") -> bool:
        """Cria um template personalizado baseado na configuração atual"""
        try:
            # Carrega configuração atual
            env_file = PROJECT_ROOT / "environment.json"
            if not env_file.exists():
                print("❌ Nenhuma configuração atual encontrada")
                return False
            
            with open(env_file, 'r', encoding='utf-8') as f:
                configuracao_atual = json.load(f)
            
            # Carrega servidores atuais
            from gerenciar_servidores import GerenciadorServidores
            gerenciador = GerenciadorServidores()
            servidores_atuais = gerenciador.listar_servidores()
            
            # Cria template
            template = {
                "nome": nome,
                "descricao": descricao or f"Template personalizado criado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                "ambiente": "personalizado",
                "configuracao": configuracao_atual,
                "servidores_exemplo": servidores_atuais
            }
            
            self._salvar_template(nome, template)
            print(f"✅ Template personalizado '{nome}' criado com sucesso!")
            return True
            
        except Exception as e:
            print(f"❌ Erro ao criar template personalizado: {e}")
            return False


def main():
    """Função principal para demonstração"""
    templates = TemplatesConfiguracao()
    
    print("📋 Templates de Configuração Disponíveis")
    print("=" * 45)
    
    for nome in templates.listar_templates():
        try:
            template = templates.carregar_template(nome)
            print(f"\n🔧 {template['nome']}")
            print(f"   Descrição: {template['descricao']}")
            print(f"   Ambiente: {template['ambiente']}")
            
            servidores = template.get('servidores_exemplo', [])
            print(f"   Servidores exemplo: {len(servidores)}")
            
        except Exception as e:
            print(f"\n❌ Erro ao carregar template '{nome}': {e}")


if __name__ == "__main__":
    main()