"""
Sistema de Gerenciamento de Servidores
Interface amigável para adicionar, remover e configurar servidores iDRAC/iLO
"""

import json
import socket
import requests
import urllib3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

# Importa configurações
from config import PROJECT_ROOT, CONEXOES_FILE

# Desabilita warnings SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class GerenciadorServidores:
    """Classe para gerenciar servidores iDRAC/iLO"""
    
    def __init__(self):
        self.arquivo_servidores = PROJECT_ROOT / "servidores.json"
        self.arquivo_conexoes_legado = CONEXOES_FILE
        self.servidores = self._carregar_servidores()
    
    def _carregar_servidores(self) -> Dict:
        """Carrega a lista de servidores do arquivo JSON"""
        if self.arquivo_servidores.exists():
            try:
                with open(self.arquivo_servidores, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"⚠️ Erro ao carregar servidores.json: {e}")
                return self._criar_estrutura_inicial()
        else:
            # Migra do formato antigo se existir
            return self._migrar_do_formato_antigo()
    
    def _criar_estrutura_inicial(self) -> Dict:
        """Cria a estrutura inicial do arquivo de servidores"""
        return {
            "servidores": [],
            "configuracao": {
                "versao": "1.0",
                "ultima_atualizacao": datetime.now().isoformat(),
                "backup_automatico": True,
                "validacao_automatica": True
            }
        }
    
    def _migrar_do_formato_antigo(self) -> Dict:
        """Migra do formato antigo (Conexoes.txt) para o novo formato JSON"""
        print("🔄 Migrando configurações do formato antigo...")
        
        estrutura = self._criar_estrutura_inicial()
        
        if not self.arquivo_conexoes_legado.exists():
            print("📝 Nenhum arquivo de configuração encontrado. Criando estrutura nova.")
            return estrutura
        
        try:
            conteudo = self.arquivo_conexoes_legado.read_text(encoding="utf-8")
            blocos = re.split(r"\n\s*\n", conteudo.strip())
            
            for i, bloco in enumerate(blocos):
                servidor = self._extrair_servidor_do_bloco(bloco, i)
                if servidor:
                    estrutura["servidores"].append(servidor)
            
            # Salva a migração
            self._salvar_servidores(estrutura)
            print(f"✅ Migração concluída! {len(estrutura['servidores'])} servidores migrados.")
            
            # Cria backup do arquivo antigo
            backup_path = self.arquivo_conexoes_legado.with_suffix('.txt.backup')
            self.arquivo_conexoes_legado.rename(backup_path)
            print(f"📦 Backup criado: {backup_path.name}")
            
        except Exception as e:
            print(f"❌ Erro durante migração: {e}")
        
        return estrutura
    
    def _extrair_servidor_do_bloco(self, bloco: str, index: int) -> Optional[Dict]:
        """Extrai informações de servidor de um bloco de texto"""
        nome_match = re.search(r"Nome:\s*(.+)", bloco, re.IGNORECASE)
        tipo_match = re.search(r"Tipo:\s*(\w+)", bloco, re.IGNORECASE)
        ip_match = re.search(r"IP:\s*([\d\.]+)", bloco, re.IGNORECASE)
        user_match = re.search(r"Usuario:\s*(\S+)", bloco, re.IGNORECASE)
        pass_match = re.search(r"Senha:\s*(\S+)", bloco, re.IGNORECASE)
        
        if not all([nome_match, tipo_match, ip_match, user_match, pass_match]):
            return None
        
        nome = nome_match.group(1).strip()
        servidor_id = self._gerar_id_servidor(nome)
        
        return {
            "id": servidor_id,
            "nome": nome,
            "tipo": tipo_match.group(1).strip().lower(),
            "ip": ip_match.group(1).strip(),
            "usuario": user_match.group(1).strip(),
            "senha": pass_match.group(1).strip(),
            "ativo": True,
            "grupo": "regionais",
            "descricao": f"Servidor migrado automaticamente",
            "porta": 443,
            "timeout": 10
        }
    
    def _gerar_id_servidor(self, nome: str) -> str:
        """Gera um ID único para o servidor baseado no nome"""
        # Remove caracteres especiais e converte para minúsculas
        id_base = re.sub(r'[^a-zA-Z0-9\s]', '', nome.lower())
        id_base = re.sub(r'\s+', '_', id_base.strip())
        
        # Verifica se já existe
        contador = 1
        id_final = id_base
        ids_existentes = [s["id"] for s in self.servidores.get("servidores", [])]
        
        while id_final in ids_existentes:
            id_final = f"{id_base}_{contador}"
            contador += 1
        
        return id_final
    
    def _salvar_servidores(self, dados: Optional[Dict] = None):
        """Salva a lista de servidores no arquivo JSON"""
        if dados is None:
            dados = self.servidores
        
        dados["configuracao"]["ultima_atualizacao"] = datetime.now().isoformat()
        
        try:
            with open(self.arquivo_servidores, 'w', encoding='utf-8') as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)
            print(f"💾 Configurações salvas em: {self.arquivo_servidores.name}")
        except Exception as e:
            print(f"❌ Erro ao salvar: {e}")
    
    def listar_servidores(self, mostrar_inativos: bool = False) -> List[Dict]:
        """Lista todos os servidores configurados"""
        servidores = self.servidores.get("servidores", [])
        
        if not mostrar_inativos:
            servidores = [s for s in servidores if s.get("ativo", True)]
        
        return servidores
    
    def adicionar_servidor(self, nome: str, tipo: str, ip: str, usuario: str, 
                          senha: str, grupo: str = "regionais", 
                          descricao: str = "", porta: int = 443, 
                          timeout: int = 10, ativo: bool = True) -> bool:
        """Adiciona um novo servidor"""
        
        # Validações básicas
        if not self._validar_ip(ip):
            print(f"❌ IP inválido: {ip}")
            return False
        
        if tipo.lower() not in ["idrac", "ilo"]:
            print(f"❌ Tipo inválido: {tipo}. Use 'idrac' ou 'ilo'")
            return False
        
        # Verifica se IP já existe
        if self._ip_ja_existe(ip):
            print(f"❌ IP {ip} já está cadastrado")
            return False
        
        # Gera ID único
        servidor_id = self._gerar_id_servidor(nome)
        
        # Cria o servidor
        novo_servidor = {
            "id": servidor_id,
            "nome": nome,
            "tipo": tipo.lower(),
            "ip": ip,
            "usuario": usuario,
            "senha": senha,
            "ativo": ativo,
            "grupo": grupo,
            "descricao": descricao,
            "porta": porta,
            "timeout": timeout
        }
        
        # Adiciona à lista
        self.servidores["servidores"].append(novo_servidor)
        self._salvar_servidores()
        
        print(f"✅ Servidor '{nome}' adicionado com sucesso!")
        print(f"   ID: {servidor_id}")
        print(f"   Tipo: {tipo}")
        print(f"   IP: {ip}")
        
        return True
    
    def remover_servidor(self, identificador: str) -> bool:
        """Remove um servidor por ID ou nome"""
        servidores = self.servidores["servidores"]
        
        # Procura por ID ou nome
        for i, servidor in enumerate(servidores):
            if servidor["id"] == identificador or servidor["nome"] == identificador:
                servidor_removido = servidores.pop(i)
                self._salvar_servidores()
                print(f"✅ Servidor '{servidor_removido['nome']}' removido com sucesso!")
                return True
        
        print(f"❌ Servidor '{identificador}' não encontrado")
        return False
    
    def editar_servidor(self, identificador: str, **kwargs) -> bool:
        """Edita um servidor existente"""
        servidores = self.servidores["servidores"]
        
        for servidor in servidores:
            if servidor["id"] == identificador or servidor["nome"] == identificador:
                # Atualiza apenas os campos fornecidos
                for campo, valor in kwargs.items():
                    if campo in servidor:
                        servidor[campo] = valor
                
                self._salvar_servidores()
                print(f"✅ Servidor '{servidor['nome']}' atualizado com sucesso!")
                return True
        
        print(f"❌ Servidor '{identificador}' não encontrado")
        return False
    
    def testar_conectividade(self, identificador: str) -> Tuple[bool, str]:
        """Testa a conectividade com um servidor"""
        servidores = self.servidores["servidores"]
        
        for servidor in servidores:
            if servidor["id"] == identificador or servidor["nome"] == identificador:
                return self._testar_servidor(servidor)
        
        return False, f"Servidor '{identificador}' não encontrado"
    
    def _testar_servidor(self, servidor: Dict) -> Tuple[bool, str]:
        """Testa conectividade com um servidor específico"""
        ip = servidor["ip"]
        porta = servidor.get("porta", 443)
        timeout = servidor.get("timeout", 10)
        tipo = servidor["tipo"]
        usuario = servidor["usuario"]
        senha = servidor["senha"]
        
        # Teste 1: Ping básico
        if not self._testar_ping(ip):
            return False, f"Host {ip} não responde ao ping"
        
        # Teste 2: Porta aberta
        if not self._testar_porta(ip, porta, timeout):
            return False, f"Porta {porta} não está acessível em {ip}"
        
        # Teste 3: Autenticação
        sucesso_auth, msg_auth = self._testar_autenticacao(ip, tipo, usuario, senha, timeout)
        if not sucesso_auth:
            return False, f"Falha na autenticação: {msg_auth}"
        
        return True, "Conectividade OK - Todos os testes passaram"
    
    def _testar_ping(self, ip: str) -> bool:
        """Testa se o host responde"""
        try:
            import subprocess
            import platform
            
            param = "-n" if platform.system().lower() == "windows" else "-c"
            comando = ["ping", param, "1", ip]
            
            resultado = subprocess.run(comando, capture_output=True, timeout=5)
            return resultado.returncode == 0
        except:
            return False
    
    def _testar_porta(self, ip: str, porta: int, timeout: int) -> bool:
        """Testa se a porta está aberta"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            resultado = sock.connect_ex((ip, porta))
            sock.close()
            return resultado == 0
        except:
            return False
    
    def _testar_autenticacao(self, ip: str, tipo: str, usuario: str, 
                           senha: str, timeout: int) -> Tuple[bool, str]:
        """Testa autenticação no servidor"""
        try:
            if tipo.lower() == "idrac":
                url = f"https://{ip}/redfish/v1/Systems/System.Embedded.1"
            else:  # ilo
                url = f"https://{ip}/redfish/v1/Systems/1"
            
            response = requests.get(
                url, 
                auth=(usuario, senha), 
                verify=False,  # TODO: Implementar verificação de certificado adequada
                timeout=timeout
            )
            
            if response.status_code == 200:
                return True, "Autenticação bem-sucedida"
            elif response.status_code == 401:
                return False, "Credenciais inválidas"
            else:
                return False, f"Erro HTTP {response.status_code}"
                
        except requests.exceptions.Timeout:
            return False, "Timeout na conexão"
        except requests.exceptions.ConnectionError:
            return False, "Erro de conexão"
        except Exception as e:
            return False, f"Erro inesperado: {str(e)}"
    
    def _validar_ip(self, ip: str) -> bool:
        """Valida formato do IP"""
        try:
            socket.inet_aton(ip)
            return True
        except socket.error:
            return False
    
    def _ip_ja_existe(self, ip: str) -> bool:
        """Verifica se o IP já está cadastrado"""
        for servidor in self.servidores.get("servidores", []):
            if servidor["ip"] == ip:
                return True
        return False
    
    def gerar_arquivo_conexoes_legado(self):
        """Gera o arquivo Conexoes.txt no formato antigo para compatibilidade"""
        servidores_ativos = [s for s in self.servidores.get("servidores", []) if s.get("ativo", True)]
        
        conteudo = []
        for servidor in servidores_ativos:
            bloco = f"""Nome: {servidor['nome']}
Tipo: {servidor['tipo']}
IP: {servidor['ip']}
Usuario: {servidor['usuario']}
Senha: {servidor['senha']}"""
            conteudo.append(bloco)
        
        # Salva o arquivo
        self.arquivo_conexoes_legado.write_text("\n\n".join(conteudo), encoding="utf-8")
        print(f"📄 Arquivo {self.arquivo_conexoes_legado.name} atualizado para compatibilidade")
    
    def exportar_configuracao(self, arquivo: str):
        """Exporta configuração para backup"""
        try:
            caminho = Path(arquivo)
            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(self.servidores, f, indent=2, ensure_ascii=False)
            print(f"📤 Configuração exportada para: {caminho}")
        except Exception as e:
            print(f"❌ Erro ao exportar: {e}")
    
    def importar_configuracao(self, arquivo: str):
        """Importa configuração de backup"""
        try:
            caminho = Path(arquivo)
            with open(caminho, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            
            # Valida estrutura básica
            if "servidores" not in dados:
                print("❌ Arquivo de configuração inválido")
                return False
            
            self.servidores = dados
            self._salvar_servidores()
            print(f"📥 Configuração importada de: {caminho}")
            return True
            
        except Exception as e:
            print(f"❌ Erro ao importar: {e}")
            return False
    
    def verificar_status_real_servidores(self):
        """Verifica o status real de conectividade de todos os servidores"""
        servidores = self.listar_servidores(mostrar_inativos=True)
        status_real = {}
        
        print("🔍 Verificando status real dos servidores...")
        
        for servidor in servidores:
            if not servidor.get('ativo', True):
                status_real[servidor['id']] = {
                    'status': 'inativo',
                    'online': False,
                    'mensagem': 'Servidor desabilitado'
                }
                continue
            
            print(f"   🔍 Testando {servidor['nome']} ({servidor['ip']})...")
            online, mensagem = self._testar_servidor_simples(servidor)
            status_real[servidor['id']] = {
                'status': 'online' if online else 'offline',
                'online': online,
                'mensagem': mensagem
            }
        
        return status_real
    
    def _testar_servidor_simples(self, servidor: Dict) -> Tuple[bool, str]:
        """Teste simples de conectividade (apenas porta TCP)"""
        try:
            import socket
            
            ip = servidor['ip']
            porta = servidor.get('porta', 443)
            timeout = 5  # Timeout mais rápido para verificação de status
            
            # Testa conexão TCP
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            resultado = sock.connect_ex((ip, porta))
            sock.close()
            
            if resultado == 0:
                return True, f"Online - Porta {porta} acessível"
            else:
                return False, f"Offline - Porta {porta} não acessível"
                
        except socket.timeout:
            return False, f"Timeout - Sem resposta em {timeout}s"
        except socket.gaierror:
            return False, f"Erro DNS - IP inválido"
        except Exception as e:
            return False, f"Erro: {str(e)}"
    
    def obter_estatisticas_reais(self):
        """Obtém estatísticas baseadas no status real dos servidores"""
        servidores = self.listar_servidores(mostrar_inativos=True)
        status_real = self.verificar_status_real_servidores()
        
        stats = {
            'total_servidores': len(servidores),
            'servidores_configurados': len([s for s in servidores if s.get('ativo', True)]),
            'servidores_inativos': len([s for s in servidores if not s.get('ativo', True)]),
            'servidores_online': 0,
            'servidores_offline': 0,
            'tipos': {},
            'grupos': {},
            'status_detalhado': status_real
        }
        
        for servidor in servidores:
            # Contagem por tipo
            tipo = servidor['tipo'].upper()
            stats['tipos'][tipo] = stats['tipos'].get(tipo, 0) + 1
            
            # Contagem por grupo
            grupo = servidor.get('grupo', 'N/A')
            stats['grupos'][grupo] = stats['grupos'].get(grupo, 0) + 1
            
            # Status real
            if servidor.get('ativo', True):
                servidor_status = status_real.get(servidor['id'], {})
                if servidor_status.get('online', False):
                    stats['servidores_online'] += 1
                else:
                    stats['servidores_offline'] += 1
        
        return stats


def main():
    """Função principal para testes"""
    gerenciador = GerenciadorServidores()
    
    print("🖥️ Sistema de Gerenciamento de Servidores")
    print("=" * 50)
    
    # Lista servidores atuais
    servidores = gerenciador.listar_servidores()
    print(f"\n📋 Servidores configurados: {len(servidores)}")
    
    for servidor in servidores:
        status = "🟢 ATIVO" if servidor.get("ativo", True) else "🔴 INATIVO"
        print(f"   {status} {servidor['nome']} ({servidor['tipo'].upper()}) - {servidor['ip']}")


if __name__ == "__main__":
    main()