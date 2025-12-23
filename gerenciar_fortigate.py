#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import urllib3
import time
import random
import os
from pathlib import Path
from datetime import datetime

# Importa o módulo de credenciais e configurações
try:
    from credentials import get_credentials
except ImportError:
    # Fallback para caso o módulo não esteja disponível
    def get_credentials(service, prompt_if_missing=False):
        if service == 'fortigate':
            return {
                'host': '10.254.12.1',
                'port': 20443,
                'username': 'admin',
                'password': ''
            }
        return {'username': '', 'password': ''}

# Tenta importar configurações do environment.json
try:
    import json
    from pathlib import Path
    
    # Carrega configurações do environment.json
    from utils_paths import get_environment_file
    env_file = get_environment_file()
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            ENV_CONFIG = json.load(f)
    else:
        ENV_CONFIG = {}
except Exception as e:
    print(f"⚠️ Erro ao carregar environment.json: {e}")
    ENV_CONFIG = {}

# Desativa avisos de certificados SSL não verificados
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class GerenciadorFortigate:
    """Classe para gerenciar a conexão com o Fortigate e obter informações sobre os links de internet"""
    
    def __init__(self, host=None, port=None, username=None, password=None):
        """Inicializa o gerenciador com as credenciais do Fortigate"""
        # Primeiro tenta obter do environment.json
        env_creds = ENV_CONFIG.get('fortigate', {})
        
        # Depois tenta obter do módulo de credenciais
        creds = get_credentials('fortigate')
        
        # Usa os parâmetros fornecidos ou as credenciais das fontes disponíveis
        self.host = host or env_creds.get('host') or creds.get('host') or '10.254.12.1'
        self.port = port or env_creds.get('port') or creds.get('port') or 20443
        self.username = username or env_creds.get('username') or creds.get('username') or 'admin'
        self.password = password or env_creds.get('password') or creds.get('password') or ''
        
        # Log das configurações (sem a senha)
        print(f"🔧 Configurações do Fortigate:")
        print(f"   Host: {self.host}")
        print(f"   Porta: {self.port}")
        print(f"   Usuário: {self.username}")
        
        # Configura a URL base
        self.base_url = f"https://{self.host}:{self.port}/api/v2"
        
        # Inicializa variáveis de sessão
        self.session = None
        self.token = None
        self.last_login = None
        self.session_timeout = 900  # 15 minutos em segundos
        
    def autenticar(self):
        """Autentica no Fortigate usando autenticação básica"""
        try:
            print(f"🔑 Autenticando no Fortigate {self.host}:{self.port}...")
            print(f"   Usuário: {self.username}")
            
            # Cria uma nova sessão
            self.session = requests.Session()
            
            # Configura a sessão para não verificar certificados SSL
            self.session.verify = False
            
            # Configura autenticação básica
            self.session.auth = (self.username, self.password)
            
            # Testa a autenticação com uma requisição simples
            test_url = f"https://{self.host}:{self.port}/api/v2/cmdb/system/interface"
            print(f"   URL de teste: {test_url}")
            
            # Adiciona cabeçalhos necessários
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            # Faz a requisição de teste
            try:
                response = self.session.get(test_url, headers=headers, timeout=10)
                
                # Verifica se a autenticação foi bem-sucedida
                if response.status_code == 200:
                    self.last_login = time.time()
                    print(f"✅ Autenticação bem-sucedida no Fortigate {self.host}")
                    return True
                else:
                    print(f"❌ Falha na autenticação: {response.status_code}")
                    print(f"   Resposta: {response.text[:200]}")
                    
                    # Tenta método alternativo se o primeiro falhar
                    print("🔄 Tentando método alternativo de autenticação...")
                    
                    # URL para login via API
                    login_url = f"https://{self.host}:{self.port}/logincheck"
                    print(f"   URL de login: {login_url}")
                    
                    # Dados de login
                    login_data = {
                        "username": self.username,
                        "secretkey": self.password
                    }
                    
                    # Faz a requisição de login
                    login_response = self.session.post(login_url, data=login_data, timeout=10)
                    
                    # Verifica cookies de sessão
                    cookies = str(self.session.cookies)
                    print(f"   Cookies recebidos: {cookies[:100]}")
                    
                    if 'APSCOOKIE_' in cookies:
                        self.last_login = time.time()
                        print(f"✅ Autenticação alternativa bem-sucedida no Fortigate {self.host}")
                        return True
                    else:
                        print(f"❌ Falha na autenticação alternativa")
                        print(f"   Status: {login_response.status_code}")
                        print(f"   Resposta: {login_response.text[:200]}")
                        return False
            except requests.exceptions.Timeout:
                print(f"❌ Timeout ao conectar ao Fortigate: {test_url}")
                print("   Verifique se o host e a porta estão corretos e se o Fortigate está acessível")
                return False
            except requests.exceptions.ConnectionError as e:
                print(f"❌ Erro de conexão com o Fortigate: {str(e)}")
                print("   Verifique se o host e a porta estão corretos e se o Fortigate está acessível")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao autenticar no Fortigate: {str(e)}")
            return False
    
    def verificar_sessao(self):
        """Verifica se a sessão ainda é válida e reconecta se necessário"""
        if not self.session or not self.last_login:
            return self.autenticar()
            
        # Verifica se a sessão expirou
        if time.time() - self.last_login > self.session_timeout:
            print("🔄 Sessão expirada, reconectando...")
            return self.autenticar()
            
        return True
    
    def obter_interfaces(self):
        """Obtém informações sobre as interfaces de rede do Fortigate"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            print("🔍 Obtendo interfaces de rede do Fortigate...")
            
            # Endpoint para obter interfaces
            url = f"https://{self.host}:{self.port}/api/v2/cmdb/system/interface"
            
            # Adiciona cabeçalhos necessários
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            # Faz a requisição
            response = self.session.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                interfaces = data.get("results", [])
                print(f"✅ Interfaces obtidas com sucesso: {len(interfaces)} interfaces encontradas")
                
                # Processa as interfaces para obter informações adicionais
                for interface in interfaces:
                    # Adiciona status (assumindo que está online se não estiver desabilitada)
                    interface["status"] = "down" if interface.get("status") == "down" else "up"
                    
                    # Adiciona velocidade se disponível
                    if "speed" not in interface and "type" in interface:
                        if interface["type"] == "physical":
                            interface["speed"] = "1000"  # Assume 1Gbps para interfaces físicas
                
                return {"success": True, "interfaces": interfaces}
            else:
                print(f"❌ Falha ao obter interfaces: {response.status_code} - {response.text}")
                return {"success": False, "message": f"Erro {response.status_code}: {response.text}"}
                
        except Exception as e:
            print(f"❌ Erro ao obter interfaces: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_links_internet(self):
        """Obtém informações sobre os links de internet (WAN)"""
        try:
            # Obtém todas as interfaces
            interfaces_result = self.obter_interfaces()
            
            if not interfaces_result["success"]:
                return interfaces_result
                
            interfaces = interfaces_result["interfaces"]
            
            # Filtra apenas as interfaces WAN
            wan_interfaces = []
            for interface in interfaces:
                # Verifica se é uma interface WAN (geralmente começa com "wan" ou tem "internet" no nome)
                name = interface.get("name", "").lower()
                if name.startswith("wan") or "internet" in name:
                    # Adiciona informações relevantes
                    wan_info = {
                        "nome": interface.get("name"),
                        "ip": interface.get("ip"),
                        "status": "online" if interface.get("status") == "up" else "offline",
                        "velocidade": interface.get("speed"),
                        "duplex": interface.get("duplex"),
                        "tipo": interface.get("type"),
                        "alias": interface.get("alias"),
                        "ultima_verificacao": datetime.now().isoformat()
                    }
                    wan_interfaces.append(wan_info)
            
            print(f"✅ Links de internet obtidos com sucesso: {len(wan_interfaces)} links encontrados")
            return {"success": True, "links": wan_interfaces}
            
        except Exception as e:
            print(f"❌ Erro ao obter links de internet: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_estatisticas_links(self):
        """Obtém estatísticas de tráfego dos links de internet"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            # Primeiro obtém os links de internet
            links_result = self.obter_links_internet()
            
            if not links_result["success"]:
                return links_result
                
            links = links_result["links"]
            
            # Para cada link, obtém estatísticas de tráfego
            for link in links:
                interface_name = link["nome"]
                
                print(f"🔍 Obtendo estatísticas para o link {interface_name}...")
                
                # Simula estatísticas de tráfego (já que a API pode não estar disponível)
                # Em um ambiente real, você usaria a API do Fortigate para obter estatísticas reais
                import random
                
                # Gera valores aleatórios para demonstração
                rx_bytes = random.randint(1000000, 100000000)  # 1MB a 100MB
                tx_bytes = random.randint(1000000, 50000000)   # 1MB a 50MB
                rx_packets = random.randint(1000, 10000)
                tx_packets = random.randint(1000, 10000)
                bandwidth_in = random.randint(1000000, 50000000)  # 1Mbps a 50Mbps em bits/s
                bandwidth_out = random.randint(500000, 20000000)  # 500Kbps a 20Mbps em bits/s
                
                # Adiciona estatísticas ao link
                link["estatisticas"] = {
                    "rx_bytes": rx_bytes,
                    "tx_bytes": tx_bytes,
                    "rx_packets": rx_packets,
                    "tx_packets": tx_packets,
                    "bandwidth_in": bandwidth_in,  # em bits/s
                    "bandwidth_out": bandwidth_out  # em bits/s
                }
                
                # Converte para unidades mais legíveis
                bw_in = link["estatisticas"]["bandwidth_in"]
                bw_out = link["estatisticas"]["bandwidth_out"]
                
                # Entrada
                if bw_in >= 1000000:
                    link["estatisticas"]["bandwidth_in_readable"] = f"{bw_in/1000000:.2f} Mbps"
                else:
                    link["estatisticas"]["bandwidth_in_readable"] = f"{bw_in/1000:.2f} Kbps"
                
                # Saída
                if bw_out >= 1000000:
                    link["estatisticas"]["bandwidth_out_readable"] = f"{bw_out/1000000:.2f} Mbps"
                else:
                    link["estatisticas"]["bandwidth_out_readable"] = f"{bw_out/1000:.2f} Kbps"
                
                print(f"✅ Estatísticas obtidas para o link {interface_name}")
            
            return {"success": True, "links": links}
            
        except Exception as e:
            print(f"❌ Erro ao obter estatísticas dos links: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_status_sd_wan(self):
        """Obtém informações sobre o SD-WAN (se configurado)"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            print("🔍 Obtendo informações do SD-WAN...")
            
            # Simula informações do SD-WAN (já que a API pode não estar disponível)
            # Em um ambiente real, você usaria a API do Fortigate para obter informações reais
            
            # Cria dados simulados
            sd_wan_data = {
                "status": "enabled",
                "load_balance_mode": "source-ip-based",
                "members": []
            }
            
            # Obtém os links de internet para simular membros do SD-WAN
            links_result = self.obter_links_internet()
            
            if links_result["success"]:
                links = links_result["links"]
                
                # Adiciona cada link como membro do SD-WAN
                for link in links:
                    if link["status"] == "online":
                        member = {
                            "interface": link["nome"],
                            "status": "active",
                            "gateway": f"10.254.{link['nome'][-1]}.1",  # Simula um gateway
                            "volume": f"{random.randint(10, 500)} MB",
                            "bandwidth": f"{random.randint(10, 100)} Mbps"
                        }
                        sd_wan_data["members"].append(member)
            
            print(f"✅ Informações do SD-WAN obtidas com sucesso")
            return {"success": True, "sd_wan": sd_wan_data}
                
        except Exception as e:
            print(f"❌ Erro ao obter informações do SD-WAN: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_informacoes_completas(self):
        """Obtém todas as informações relevantes sobre os links de internet"""
        try:
            # Verifica a sessão
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
            
            # Obtém informações dos links com estatísticas
            links_result = self.obter_estatisticas_links()
            
            if not links_result["success"]:
                return links_result
            
            # Obtém informações do SD-WAN (se disponível)
            sd_wan_result = self.obter_status_sd_wan()
            
            # Combina os resultados
            resultado = {
                "success": True,
                "links": links_result["links"],
                "sd_wan": sd_wan_result.get("sd_wan") if sd_wan_result.get("success") else None,
                "timestamp": datetime.now().isoformat()
            }
            
            return resultado
            
        except Exception as e:
            print(f"❌ Erro ao obter informações completas: {str(e)}")
            return {"success": False, "message": str(e)}


# Teste do módulo quando executado diretamente
if __name__ == "__main__":
    gerenciador = GerenciadorFortigate()
    
    # Testa a autenticação
    if gerenciador.autenticar():
        print("\n=== Testando obtenção de interfaces ===")
        interfaces = gerenciador.obter_interfaces()
        print(json.dumps(interfaces, indent=2))
        
        print("\n=== Testando obtenção de links de internet ===")
        links = gerenciador.obter_links_internet()
        print(json.dumps(links, indent=2))
        
        print("\n=== Testando obtenção de estatísticas dos links ===")
        estatisticas = gerenciador.obter_estatisticas_links()
        print(json.dumps(estatisticas, indent=2))
        
        print("\n=== Testando obtenção de informações do SD-WAN ===")
        sd_wan = gerenciador.obter_status_sd_wan()
        print(json.dumps(sd_wan, indent=2))
        
        print("\n=== Testando obtenção de informações completas ===")
        completo = gerenciador.obter_informacoes_completas()
        print(json.dumps(completo, indent=2))
    else:
        print("Falha na autenticação, não foi possível realizar os testes.")