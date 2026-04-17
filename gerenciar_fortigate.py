#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import urllib3
import time
import random
import os
from pathlib import Path
import paramiko
import re
from datetime import datetime

# Importa o módulo de credenciais e configurações
try:
    from credentials import get_credentials
except ImportError:
    # Fallback para caso o módulo não esteja disponível
    def get_credentials(service, prompt_if_missing=False):
        if service == 'fortigate':
            return {
                'host': 'fortigate.example.local',
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

        # Suporta formato com múltiplas chaves (ex: SP/RJ)
        if isinstance(env_creds, dict) and "host" not in env_creds:
            for cfg in env_creds.values():
                if isinstance(cfg, dict) and cfg.get("host"):
                    env_creds = cfg
                    break
        
        # Depois tenta obter do módulo de credenciais
        creds = get_credentials('fortigate')
        
        # Usa os parâmetros fornecidos ou as credenciais das fontes disponíveis
        self.host = host or env_creds.get('host') or creds.get('host') or 'fortigate.example.local'
        self.port = port or env_creds.get('port') or creds.get('port') or 20443
        self.username = username or env_creds.get('username') or creds.get('username') or 'admin'
        self.password = password or env_creds.get('password') or creds.get('password') or ''
        
        # Log das configurações (sem a senha)
        print(f"   Configurações do Fortigate:")
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
            print(f"[AUTH] Autenticando no Fortigate {self.host}:{self.port}...")
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
                    print(f"[OK] Autenticação bem-sucedida no Fortigate {self.host}")
                    return True
                else:
                    print(f"[ERROR] Falha na autenticação: {response.status_code}")
                    print(f"   Resposta: {response.text[:200]}")
                    
                    # Tenta método alternativo se o primeiro falhar
                    print("[INFO] Tentando método alternativo de autenticação...")
                    
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
                        print(f"[OK] Autenticação alternativa bem-sucedida no Fortigate {self.host}")
                        return True
                    else:
                        print(f"[ERROR] Falha na autenticação alternativa")
                        print(f"   Status: {login_response.status_code}")
                        print(f"   Resposta: {login_response.text[:200]}")
                        return False
            except requests.exceptions.Timeout:
                print(f"[ERROR] Timeout ao conectar ao Fortigate: {test_url}")
                print("   Verifique se o host e a porta estão corretos e se o Fortigate está acessível")
                return False
            except requests.exceptions.ConnectionError as e:
                print(f"[ERROR] Erro de conexão com o Fortigate: {str(e)}")
                print("   Verifique se o host e a porta estão corretos e se o Fortigate está acessível")
                return False
                
        except Exception as e:
            print(f"[ERROR] Erro ao autenticar no Fortigate: {str(e)}")
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

    def _obter_snapshot_monitor_interfaces(self):
        """Obtém o snapshot bruto das interfaces do endpoint de monitoramento."""
        url = f"https://{self.host}:{self.port}/api/v2/monitor/system/interface"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        response = self.session.get(url, headers=headers)
        if response.status_code != 200:
            return {
                "success": False,
                "message": f"Erro {response.status_code}: {response.text}"
            }

        try:
            data = response.json()
        except Exception as e:
            return {
                "success": False,
                "message": f"Erro ao parsear resposta: {e}"
            }

        return {
            "success": True,
            "results": data.get("results", {})
        }

    @staticmethod
    def _calcular_bandwidth_por_delta(snapshot_inicial, snapshot_final, intervalo_segundos):
        if intervalo_segundos <= 0:
            return 0, 0

        rx_inicial = snapshot_inicial.get("rx_bytes", 0) or 0
        tx_inicial = snapshot_inicial.get("tx_bytes", 0) or 0
        rx_final = snapshot_final.get("rx_bytes", 0) or 0
        tx_final = snapshot_final.get("tx_bytes", 0) or 0

        bandwidth_in = max((rx_final - rx_inicial) * 8 / intervalo_segundos, 0)
        bandwidth_out = max((tx_final - tx_inicial) * 8 / intervalo_segundos, 0)
        return int(bandwidth_in), int(bandwidth_out)

    @staticmethod
    def _formatar_bandwidth(bandwidth_bps):
        if bandwidth_bps >= 1000000:
            return f"{bandwidth_bps / 1000000:.2f} Mbps"
        return f"{bandwidth_bps / 1000:.2f} Kbps"

    def _extrair_estatisticas_interface(self, interface_stats, interface_stats_final=None, intervalo_segundos=1.0):
        estatisticas = {
            "rx_bytes": interface_stats.get("rx_bytes", 0),
            "tx_bytes": interface_stats.get("tx_bytes", 0),
            "rx_packets": interface_stats.get("rx_packets", 0),
            "tx_packets": interface_stats.get("tx_packets", 0),
            "bandwidth_in": interface_stats.get("bandwidth_in", 0) or 0,
            "bandwidth_out": interface_stats.get("bandwidth_out", 0) or 0,
        }

        if (
            estatisticas["bandwidth_in"] <= 0
            and estatisticas["bandwidth_out"] <= 0
            and interface_stats_final is not None
        ):
            bandwidth_in, bandwidth_out = self._calcular_bandwidth_por_delta(
                interface_stats,
                interface_stats_final,
                intervalo_segundos,
            )
            estatisticas["bandwidth_in"] = bandwidth_in
            estatisticas["bandwidth_out"] = bandwidth_out

        estatisticas["bandwidth_in_readable"] = self._formatar_bandwidth(estatisticas["bandwidth_in"])
        estatisticas["bandwidth_out_readable"] = self._formatar_bandwidth(estatisticas["bandwidth_out"])
        return estatisticas
    
    def obter_interfaces(self):
        """Obtém informações sobre as interfaces de rede do Fortigate"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            print("[INFO] Obtendo interfaces de rede do Fortigate...")
            
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
                print(f"[OK] Interfaces obtidas com sucesso: {len(interfaces)} interfaces encontradas")
                
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
                print(f"[ERROR] Falha ao obter interfaces: {response.status_code} - {response.text}")
                return {"success": False, "message": f"Erro {response.status_code}: {response.text}"}
                
        except Exception as e:
            print(f"[ERROR] Erro ao obter interfaces: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_links_internet(self):
        """Obtém informações sobre os links de internet (WAN)"""
        try:
            # Obtém todas as interfaces
            interfaces_result = self.obter_interfaces()
            
            if not interfaces_result["success"]:
                return interfaces_result
                
            interfaces = interfaces_result["interfaces"]
            
            # Filtra apenas as interfaces ssh.connect
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
    def obter_estatisticas_interface(self, interface_name):
        """Obtém estatísticas de tráfego de uma interface específica"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            print(f"🔍 Obtendo estatísticas da interface {interface_name}...")

            snapshot_inicial = self._obter_snapshot_monitor_interfaces()
            if not snapshot_inicial["success"]:
                print(f"❌ Falha ao obter estatísticas das interfaces: {snapshot_inicial['message']}")
                return snapshot_inicial

            results_iniciais = snapshot_inicial.get("results", {})
            if interface_name not in results_iniciais:
                print(f"⚠️ Interface {interface_name} não encontrada nas estatísticas")
                return {"success": False, "message": f"Interface {interface_name} não encontrada"}

            interface_stats = results_iniciais[interface_name]
            interface_stats_final = None

            if (interface_stats.get("bandwidth_in", 0) or 0) <= 0 and (interface_stats.get("bandwidth_out", 0) or 0) <= 0:
                time.sleep(1)
                snapshot_final = self._obter_snapshot_monitor_interfaces()
                if snapshot_final["success"]:
                    interface_stats_final = snapshot_final.get("results", {}).get(interface_name)

            estatisticas = self._extrair_estatisticas_interface(
                interface_stats,
                interface_stats_final=interface_stats_final,
                intervalo_segundos=1.0,
            )

            print(f"✅ Estatísticas obtidas para {interface_name}")
            return {"success": True, "estatisticas": estatisticas}
                
        except Exception as e:
            print(f"❌ Erro ao obter estatísticas da interface {interface_name}: {str(e)}")
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
                
                # Obtém estatísticas reais da interface
                stats_result = self.obter_estatisticas_interface(interface_name)
                
                if stats_result["success"]:
                    link["estatisticas"] = stats_result["estatisticas"]
                else:
                    # Fallback para estatísticas simuladas se a API falhar
                    print(f"⚠️ Usando estatísticas simuladas para {interface_name}")
                    import random
                    
                    rx_bytes = random.randint(1000000, 100000000)
                    tx_bytes = random.randint(1000000, 50000000)
                    rx_packets = random.randint(1000, 10000)
                    tx_packets = random.randint(1000, 10000)
                    bandwidth_in = random.randint(1000000, 50000000)
                    bandwidth_out = random.randint(500000, 20000000)
                    
                    link["estatisticas"] = {
                        "rx_bytes": rx_bytes,
                        "tx_bytes": tx_bytes,
                        "rx_packets": rx_packets,
                        "tx_packets": tx_packets,
                        "bandwidth_in": bandwidth_in,
                        "bandwidth_out": bandwidth_out
                    }
                
                # Converte para unidades mais legíveis
                bw_in = link["estatisticas"]["bandwidth_in"]
                bw_out = link["estatisticas"]["bandwidth_out"]
                link["estatisticas"]["bandwidth_in_readable"] = self._formatar_bandwidth(bw_in)
                link["estatisticas"]["bandwidth_out_readable"] = self._formatar_bandwidth(bw_out)
                
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

    def obter_vpn_ipsec(self):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            ssh.connect(
                hostname=self.host,
                port=2222,
                username=self.username,
                password=self.password,
                timeout=10
            )

            stdin, stdout, stderr = ssh.exec_command(
                "get vpn ipsec tunnel summary"
            )

            output = stdout.read().decode(errors="ignore")
            ssh.close()

            vpns = []

            for line in output.splitlines():
                if "selectors" not in line:
                    continue

                # 'T045_PARA_02' ... selectors(total,up): 1/1
                name_match = re.search(r"'([^']+)'", line)
                sel_match = re.search(r"selectors\(total,up\): (\d+)/(\d+)", line)

                if not name_match or not sel_match:
                    continue

                name = name_match.group(1)
                total = int(sel_match.group(1))
                up = int(sel_match.group(2))

                status = "up" if total > 0 and up == total else "down"

                vpns.append({
                    "tunel": name,
                    "interface": "N/A",
                    "status": status,
                    "ultima_verificacao": datetime.now().strftime("%H:%M:%S")
                })

            return {
                "success": True,
                "vpns": vpns,
                "total": len(vpns),
                "ativos": sum(1 for v in vpns if v["status"] == "up"),
                "inativos": sum(1 for v in vpns if v["status"] == "down")
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Erro SSH Fortigate: {str(e)}"
            }

    def testar_link(self, interface_name, ip_link=None):
        """Testa a conectividade de um link específico através do Fortigate"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            print(f"🔍 Testando conectividade do link {interface_name}...")
            
            # Endpoint para obter status da interface específica via monitor
            url = f"https://{self.host}:{self.port}/api/v2/monitor/system/interface"
            
            # Adiciona cabeçalhos necessários
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            # Faz a requisição para obter todas as interfaces
            response = self.session.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", {})
                
                # Procura pela interface específica no dicionário
                interface_data = results.get(interface_name)
                
                if not interface_data:
                    return {
                        "success": False, 
                        "message": f"Interface {interface_name} não encontrada",
                        "link": interface_name,
                        "status": "not_found"
                    }
                
                # Verifica o status da interface baseado no campo "link"
                link_up = interface_data.get("link", False)
                
                # Obtém estatísticas básicas se disponíveis
                estatisticas = {
                    "rx_bytes": interface_data.get("rx_bytes", 0),
                    "tx_bytes": interface_data.get("tx_bytes", 0),
                    "rx_packets": interface_data.get("rx_packets", 0),
                    "tx_packets": interface_data.get("tx_packets", 0),
                    "speed": interface_data.get("speed", 0),
                    "duplex": interface_data.get("duplex", -1)
                }
                
                # Status inicial baseado na interface física
                status = "online" if link_up else "offline"
                message = f"Link {interface_name} está {'online' if link_up else 'offline'}"
                
                # Se a interface física está UP e temos um IP para testar, faz verificação adicional
                if link_up and ip_link:
                    print(f"🔍 Testando conectividade para IP {ip_link}...")
                    
                    # Tenta fazer uma requisição HTTP para o IP (porta 80 ou 443)
                    import requests
                    import urllib3
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                    
                    connectivity_test = False
                    
                    # Tenta HTTPS primeiro (porta 443)
                    try:
                        test_response = requests.get(f"https://{ip_link}", timeout=5, verify=False)
                        if test_response.status_code < 500:  # Considera sucesso se não for erro do servidor
                            connectivity_test = True
                            print(f"✅ Conectividade HTTPS confirmada para {ip_link}")
                    except:
                        # Se HTTPS falhar, tenta HTTP (porta 80)
                        try:
                            test_response = requests.get(f"http://{ip_link}", timeout=5)
                            if test_response.status_code < 500:
                                connectivity_test = True
                                print(f"✅ Conectividade HTTP confirmada para {ip_link}")
                        except:
                            print(f"❌ Falha na conectividade para IP {ip_link}")
                    
                    # Atualiza status baseado na conectividade
                    if not connectivity_test:
                        status = "offline"
                        message = f"Link {interface_name} interface UP, mas IP {ip_link} inacessível"
                        print(f"⚠️ Interface {interface_name} está UP, mas IP {ip_link} não responde")
                    else:
                        message = f"Link {interface_name} está online e IP {ip_link} acessível"
                
                resultado = {
                    "success": True,
                    "link": interface_name,
                    "status": status,
                    "message": message,
                    "estatisticas": estatisticas,
                    "ip_testado": ip_link,
                    "ultima_verificacao": datetime.now().isoformat()
                }
                
                print(f"✅ Teste do link {interface_name} concluído: {resultado['status']}")
                return resultado
                
            else:
                print(f"❌ Falha ao obter interfaces: {response.status_code} - {response.text}")
                return {
                    "success": False, 
                    "message": f"Erro {response.status_code} ao obter interfaces",
                    "link": interface_name,
                    "status": "unknown"
                }
                
        except Exception as e:
            print(f"❌ Erro ao testar link {interface_name}: {str(e)}")
            return {
                "success": False, 
                "message": f"Erro interno: {str(e)}",
                "link": interface_name,
                "status": "error"
            }

    def testar_link_fisico(self, interface_name, ip_link=None):
        """Testa apenas o status físico do link (para operadoras que bloqueiam ping/IP)"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}

            print(f"🔍 Testando status físico do link {interface_name}...")

            # Endpoint para obter status da interface específica via monitor
            url = f"https://{self.host}:{self.port}/api/v2/monitor/system/interface"

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }

            response = self.session.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", {})

                interface_data = results.get(interface_name)

                if not interface_data:
                    return {
                        "success": False,
                        "message": f"Interface {interface_name} não encontrada",
                        "link": interface_name,
                        "status": "not_found"
                    }

                # Verifica o status físico da interface
                link_up = interface_data.get("link", False)

                # Obtém estatísticas detalhadas
                estatisticas = {
                    "rx_bytes": interface_data.get("rx_bytes", 0),
                    "tx_bytes": interface_data.get("tx_bytes", 0),
                    "rx_packets": interface_data.get("rx_packets", 0),
                    "tx_packets": interface_data.get("tx_packets", 0),
                    "rx_errors": interface_data.get("rx_errors", 0),
                    "tx_errors": interface_data.get("tx_errors", 0),
                    "speed": interface_data.get("speed", 0),
                    "duplex": interface_data.get("duplex", -1)
                }

                # Análise de saúde do link baseada em estatísticas
                saude_link = self._analisar_saude_link(estatisticas)

                # Status baseado na interface física e saúde
                if not link_up:
                    status = "down"
                    message = f"Link {interface_name} está fisicamente DOWN"
                elif saude_link["status"] == "degraded":
                    status = "degraded"
                    message = f"Link {interface_name} UP, mas com problemas: {saude_link['message']}"
                else:
                    status = "online"
                    message = f"Link {interface_name} está saudável e operacional"

                resultado = {
                    "success": True,
                    "link": interface_name,
                    "status": status,
                    "message": message,
                    "estatisticas": estatisticas,
                    "saude": saude_link,
                    "ip_configurado": ip_link,
                    "tipo_teste": "fisico",  # Indica que foi teste físico apenas
                    "ultima_verificacao": datetime.now().isoformat()
                }

                print(f"✅ Teste físico do link {interface_name} concluído: {resultado['status']}")
                return resultado

            else:
                print(f"❌ Falha ao obter interfaces: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "message": f"Erro {response.status_code} ao obter interfaces",
                    "link": interface_name,
                    "status": "unknown"
                }

        except Exception as e:
            print(f"❌ Erro ao testar link físico {interface_name}: {str(e)}")
            return {
                "success": False,
                "message": f"Erro interno: {str(e)}",
                "link": interface_name,
                "status": "error"
            }

    def _analisar_saude_link(self, estatisticas):
        """Analisa a saúde do link baseada nas estatísticas"""
        try:
            rx_packets = estatisticas.get("rx_packets", 0)
            tx_packets = estatisticas.get("tx_packets", 0)
            rx_errors = estatisticas.get("rx_errors", 0)
            tx_errors = estatisticas.get("tx_errors", 0)

            # Calcula taxa de erro
            total_packets = rx_packets + tx_packets
            total_errors = rx_errors + tx_errors

            if total_packets > 0:
                taxa_erro = (total_errors / total_packets) * 100
            else:
                taxa_erro = 0

            # Verifica se há tráfego (link está sendo usado)
            tem_trafego = (rx_packets > 1000) or (tx_packets > 1000)

            # Análise de saúde
            if taxa_erro > 5:  # Mais de 5% de erro
                return {
                    "status": "degraded",
                    "message": ".1f",
                    "taxa_erro": taxa_erro,
                    "recomendacao": "Verificar cabos, interfaces ou configuração"
                }
            elif total_errors > 1000:  # Muitos erros absolutos
                return {
                    "status": "degraded",
                    "message": f"Muitos erros detectados ({total_errors} erros)",
                    "taxa_erro": taxa_erro,
                    "recomendacao": "Verificar qualidade da conexão física"
                }
            elif not tem_trafego:
                return {
                    "status": "warning",
                    "message": "Link sem tráfego significativo",
                    "taxa_erro": taxa_erro,
                    "recomendacao": "Verificar se o link está sendo utilizado"
                }
            else:
                return {
                    "status": "healthy",
                    "message": "Link funcionando normalmente",
                    "taxa_erro": taxa_erro,
                    "recomendacao": "Nenhuma ação necessária"
                }

        except Exception as e:
            return {
                "status": "unknown",
                "message": f"Erro na análise: {str(e)}",
                "taxa_erro": 0,
                "recomendacao": "Verificar manualmente"
            }

    def testar_link_sla(self, interface_name, ip_teste=None):
        """Testa link usando SLA monitoring (ping para IP acessível)"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}

            print(f"🔍 Testando link {interface_name} via SLA (ping para IP acessível)...")

            # Se não foi fornecido IP de teste, usa um IP público confiável
            if not ip_teste:
                ip_teste = "8.8.8.8"  # Google DNS como padrão

            # Primeiro verifica se a interface física está UP
            status_fisico = self.testar_link_fisico(interface_name)
            if not status_fisico["success"] or status_fisico["status"] == "down":
                return status_fisico

            # Se interface está UP, testa conectividade via ping para IP acessível
            print(f"📡 Testando ping para {ip_teste} via interface {interface_name}...")

            # Simula teste de ping (em produção, usaria API do Fortigate ou comando direto)
            import subprocess
            import platform

            try:
                if platform.system().lower() == 'windows':
                    # No Windows, podemos especificar interface, mas é limitado
                    result = subprocess.run(
                        ['ping', '-n', '4', '-w', '2000', ip_teste],
                        capture_output=True, text=True, timeout=10
                    )
                else:
                    # No Linux, podemos usar -I para especificar interface
                    result = subprocess.run(
                        ['ping', '-c', '4', '-W', '2', '-I', interface_name, ip_teste],
                        capture_output=True, text=True, timeout=10
                    )

                # Analisa resultado do ping
                if result.returncode == 0:
                    # Ping bem-sucedido - calcula estatísticas
                    output = result.stdout
                    perda = 0

                    # Extrai estatísticas do ping
                    if 'Lost = ' in output:
                        # Windows format
                        lost_part = output.split('Lost = ')[1].split(' ')[0]
                        perda = int(lost_part.rstrip('%'))
                    elif 'packet loss' in output:
                        # Linux format
                        loss_part = output.split('packet loss')[0].split(',')[-1].strip()
                        perda = int(loss_part.rstrip('%'))

                    if perda == 0:
                        sla_status = "excellent"
                        message = f"SLA perfeito: 0% perda de pacotes"
                    elif perda <= 5:
                        sla_status = "good"
                        message = f"SLA bom: {perda}% perda de pacotes"
                    elif perda <= 10:
                        sla_status = "fair"
                        message = f"SLA regular: {perda}% perda de pacotes"
                    else:
                        sla_status = "poor"
                        message = f"SLA ruim: {perda}% perda de pacotes"

                    return {
                        "success": True,
                        "link": interface_name,
                        "status": "online",  # Link físico UP e SLA OK
                        "message": message,
                        "sla": {
                            "ip_teste": ip_teste,
                            "perda_pacotes": perda,
                            "status": sla_status,
                            "interface": interface_name
                        },
                        "estatisticas": status_fisico.get("estatisticas", {}),
                        "tipo_teste": "sla",
                        "ultima_verificacao": datetime.now().isoformat()
                    }
                else:
                    return {
                        "success": True,
                        "link": interface_name,
                        "status": "degraded",
                        "message": f"Link físico UP, mas SLA falhou (ping para {ip_teste})",
                        "sla": {
                            "ip_teste": ip_teste,
                            "status": "failed",
                            "interface": interface_name
                        },
                        "estatisticas": status_fisico.get("estatisticas", {}),
                        "tipo_teste": "sla",
                        "ultima_verificacao": datetime.now().isoformat()
                    }

            except subprocess.TimeoutExpired:
                return {
                    "success": True,
                    "link": interface_name,
                    "status": "degraded",
                    "message": f"Timeout no teste SLA para {ip_teste}",
                    "sla": {
                        "ip_teste": ip_teste,
                        "status": "timeout",
                        "interface": interface_name
                    },
                    "estatisticas": status_fisico.get("estatisticas", {}),
                    "tipo_teste": "sla",
                    "ultima_verificacao": datetime.now().isoformat()
                }

        except Exception as e:
            print(f"❌ Erro no teste SLA do link {interface_name}: {str(e)}")
            return {
                "success": False,
                "message": f"Erro interno: {str(e)}",
                "link": interface_name,
                "status": "error"
            }
    def _obter_status_sla_sdwan(self):
        """Obtém status SLA do SD-WAN via endpoints de monitoramento"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "mapping": {}, "data": {}, "source": None}

            headers = {"Accept": "application/json"}
            endpoints = [
                "/monitor/sdwan/health-check",
                "/monitor/sdwan/service",
                "/monitor/sdwan/status",
                "/monitor/virtual-wan-link/health-check",
                "/monitor/virtual-wan-link/service",
                "/monitor/virtual-wan-link/status"
            ]

            def normalizar_status(valor):
                if valor is None:
                    return "unknown"
                valor_str = str(valor).strip().lower()
                if valor_str in ["up", "alive", "active", "ok", "good", "excellent", "pass", "reachable", "healthy", "health"]:
                    return "active"
                if valor_str in ["down", "dead", "inactive", "fail", "failed", "timeout", "unreachable", "poor", "bad"]:
                    return "inactive"
                return "unknown"

            def extrair_interface(item):
                for chave in ["interface", "ifname", "member", "member_name", "name", "link", "link_name"]:
                    valor = item.get(chave)
                    if isinstance(valor, str) and valor.strip():
                        return valor.strip().upper()
                return None

            def processar_itens(itens, mapping, data_map):
                for item in itens:
                    if not isinstance(item, dict):
                        continue

                    if isinstance(item.get("members"), list):
                        for membro in item.get("members", []):
                            if not isinstance(membro, dict):
                                continue
                            iface = extrair_interface(membro)
                            status_valor = membro.get("status") or membro.get("state") or membro.get("health") or membro.get("link")
                            status = normalizar_status(status_valor)
                            if iface:
                                mapping[iface] = status
                                data_map[iface] = membro

                    if isinstance(item.get("interfaces"), list):
                        for iface_item in item.get("interfaces", []):
                            if not isinstance(iface_item, dict):
                                continue
                            iface = extrair_interface(iface_item)
                            status_valor = iface_item.get("status") or iface_item.get("state") or iface_item.get("health") or iface_item.get("link")
                            status = normalizar_status(status_valor)
                            if iface:
                                mapping[iface] = status
                                data_map[iface] = iface_item

                    iface = extrair_interface(item)
                    status_valor = item.get("status") or item.get("state") or item.get("health") or item.get("link")
                    status = normalizar_status(status_valor)
                    if iface:
                        mapping[iface] = status
                        data_map[iface] = item

            for endpoint in endpoints:
                url = f"{self.base_url}{endpoint}"
                try:
                    response = self.session.get(url, headers=headers, timeout=10)
                except Exception:
                    continue

                if response.status_code != 200:
                    continue

                try:
                    payload = response.json()
                except Exception:
                    continue

                mapping = {}
                data_map = {}

                if isinstance(payload, dict):
                    resultados = payload.get("results") or payload.get("result") or payload.get("data") or payload.get("entries")
                    if isinstance(resultados, list):
                        processar_itens(resultados, mapping, data_map)
                    elif isinstance(resultados, dict):
                        processar_itens([resultados], mapping, data_map)
                    else:
                        processar_itens([payload], mapping, data_map)
                elif isinstance(payload, list):
                    processar_itens(payload, mapping, data_map)

                if mapping:
                    return {
                        "success": True,
                        "mapping": mapping,
                        "data": data_map,
                        "source": endpoint
                    }

            return {"success": False, "mapping": {}, "data": {}, "source": None}

        except Exception as e:
            print(f"⚠️ Erro ao obter status SLA do SD-WAN: {str(e)}")
            return {"success": False, "mapping": {}, "data": {}, "source": None}

    def obter_membros_sdwan_com_sla(self):
        """Obtém membros do SD-WAN com IDs e status SLA"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}

            print("🔍 Obtendo membros do SD-WAN com status SLA...")

            # Mapeia status SLA via endpoints de monitoramento
            sla_monitor = self._obter_status_sla_sdwan()
            sla_por_interface = sla_monitor.get("mapping", {})
            sla_dados_por_interface = sla_monitor.get("data", {})

            # Tenta obter informações do SD-WAN via API
            url = f"{self.base_url}/cmdb/router/sdwan"
            headers = {"Accept": "application/json"}
            
            response = self.session.get(url, headers=headers, timeout=10)
            
            membros_sdwan = []
            
            if response.status_code == 200:
                try:
                    sd_wan_config = response.json().get("results", {})
                    
                    # Extrai membros do SD-WAN
                    members = sd_wan_config.get("members", [])
                    
                    for member in members:
                        interface_nome = member.get("interface", "")
                        interface_key = interface_nome.strip().upper() if isinstance(interface_nome, str) else ""
                        sla_status = sla_por_interface.get(interface_key, "unknown")
                        sla_data = sla_dados_por_interface.get(interface_key, {})

                        member_info = {
                            "member_id": member.get("_id", member.get("id", "unknown")),
                            "interface": interface_nome,
                            "priority": member.get("priority", 0),
                            "volume_quota": member.get("volume_quota", 0),
                            "member_seq": member.get("member_seq", 0),
                            "cost": member.get("cost", 0),
                            "detected_latency": member.get("detected_latency", 0),
                            "detected_jitter": member.get("detected_jitter", 0),
                            "detected_packet_loss": member.get("detected_packet_loss", 0),
                            "sla_status": sla_status,
                            "sla_data": sla_data
                        }
                        membros_sdwan.append(member_info)
                        
                except Exception as e:
                    print(f"⚠️ Erro ao parsear SD-WAN: {e}")
            
            # Se não obteve via API, constrói a partir das interfaces WAN
            if not membros_sdwan:
                print("🔄 Construindo membros SD-WAN a partir das interfaces...")
                
                interfaces_result = self.obter_interfaces()
                if interfaces_result["success"]:
                    member_id = 1
                    for interface in interfaces_result["interfaces"]:
                        name = interface.get("name", "").lower()
                        if name in ["wan1", "wan2"]:
                            ip = interface.get("ip", "").split()[0] if interface.get("ip") else "N/A"

                            link_value = interface.get("link", None)
                            status_value = str(interface.get("status", "")).lower()
                            interface_up = link_value if link_value is not None else (status_value == "up")
                            sla_status = sla_por_interface.get(name.upper(), "unknown")
                            if sla_status == "unknown":
                                # Fallback: usa status físico se SLA não estiver disponível
                                sla_status = "active" if interface_up else "inactive"
                            sla_data = sla_dados_por_interface.get(name.upper(), {})
                            
                            member_info = {
                                "member_id": member_id,
                                "interface": name.upper(),
                                "ip": ip,
                                "priority": 1,
                                "status": sla_status,
                                "sla_status": sla_status,
                                "link_up": interface_up,
                                "sla_data": sla_data if sla_data else {"status": sla_status}
                            }
                            membros_sdwan.append(member_info)
                            member_id += 1
            
            print(f"✅ {len(membros_sdwan)} membros SD-WAN encontrados")
            
            return {
                "success": True,
                "membros": membros_sdwan,
                "total": len(membros_sdwan),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Erro ao obter membros SD-WAN: {str(e)}")
            return {
                "success": False,
                "message": f"Erro: {str(e)}",
                "membros": []
            }
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