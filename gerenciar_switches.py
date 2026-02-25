"""
Gerenciador de Switches - Integração com Zabbix
"""

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas não instalado. Funcionalidades limitadas.")
    PANDAS_AVAILABLE = False
    pd = None
import requests
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from utils_paths import get_file_path

# Importa o módulo de credenciais
try:
    from credentials import get_credentials
except ImportError:
    # Fallback para caso o módulo não esteja disponível
    def get_credentials(service, prompt_if_missing=False):
        if service == 'zabbix':
            return {
                'url': 'http://10.254.12.15/zabbix/api_jsonrpc.php',
                'username': 'admin',
                'password': ''
            }
        return {'username': '', 'password': ''}

class GerenciadorSwitches:
    """Gerencia informações de switches via Zabbix"""
    
    def __init__(self, arquivo_excel=None, config_file="zabbix_config.json"):
        # Tenta obter configurações do environment.json
        try:
            import json
            from pathlib import Path
            from utils_paths import get_environment_file
            
            # Carrega configurações do environment.json
            env_file = get_environment_file()
            if env_file.exists():
                with open(env_file, 'r', encoding='utf-8') as f:
                    ENV_CONFIG = json.load(f)
                    zabbix_config = ENV_CONFIG.get('zabbix', {})
                    arquivo_excel_env = zabbix_config.get('excel_file')
            else:
                ENV_CONFIG = {}
                zabbix_config = {}
                arquivo_excel_env = None
        except Exception as e:
            print(f"⚠️ Erro ao carregar environment.json: {e}")
            ENV_CONFIG = {}
            zabbix_config = {}
            arquivo_excel_env = None
        
        # Define o arquivo Excel (prioridade: parâmetro > environment.json > padrão)
        self.arquivo_excel = arquivo_excel or arquivo_excel_env or "switches_zabbix.xlsx"
        self.config_file = config_file
        self.zabbix_url = None
        self.username = None
        self.password = None
        self.auth_token = None
        self.switches = []
        self.regionais = {}
        
        # Carrega configurações
        self._carregar_config()
        
        # Carrega dados dos switches
        self._carregar_switches()
        
        # Atualiza todos os IPs para o formato correto
        self.atualizar_ips()
        
    def _converter_ip_numerico(self, ip_numerico):
        """Converte IP numérico para formato padrão (ex: 192.168.1.1)"""
        try:
            # Se for NaN ou vazio, retorna string vazia
            if pd.isna(ip_numerico) or ip_numerico == "":
                return ""
                
            # Converte para string e remove espaços
            ip_str = str(ip_numerico).strip()
            
            # Se já estiver no formato padrão (com pontos), retorna como está
            if "." in ip_str:
                return ip_str
                
            # Primeiro, verifica se é um número válido
            try:
                ip_int = int(ip_str)
            except ValueError:
                return ip_str  # Se não for um número, retorna como está
            
            # Casos especiais conhecidos
            casos_especiais = {
                # SWITCH GALAXIA - 01
                "102541220": "10.254.12.20",
                
                # V001_REG_PARANA - SWTGPSPR-02
                "192168416": "192.168.41.6",
                
                # V001_REG_PARANA - SWTGPSPR-04
                "1921684129": "192.168.41.29",
                
                # V001_REG_PARANA - SWTGPSPR-03
                "192168419": "192.168.41.9",
                
                # V001_REG_PARANA - SWTGPSPR-07
                "1921684132": "192.168.41.32",
                
                # V001_REG_PARANA - SWTGPSPR-08
                "1921684133": "192.168.41.33",
                
                # V001_REG_PARANA - SWTGPSPR-05
                "1921684117": "192.168.41.17",
                
                # V001_REG_PARANA - SWTGPSPR-06
                "1921684118": "192.168.41.18",
                
                # V001_REG_PARANA - SWTGPSPR-01
                "1921684114": "192.168.41.14",
                
                # V008_REG_BH - SWTGPS-BH-06
                "1031025": "10.3.10.25"
            }
            
            # Verifica se é um caso especial conhecido
            if ip_str in casos_especiais:
                return casos_especiais[ip_str]
            
            # Tenta converter usando o método padrão
            try:
                # Método padrão: converte o número para os 4 octetos
                octetos = []
                for _ in range(4):
                    octeto = ip_int % 256
                    octetos.insert(0, str(octeto))
                    ip_int //= 256
                
                ip_padrao = ".".join(octetos)
                
                # Verifica se o IP parece válido (primeiro octeto entre 1 e 223)
                if 1 <= int(octetos[0]) <= 223:
                    return ip_padrao
                else:
                    # Se não parece válido, tenta outro método
                    pass
            except Exception as e:
                print(f"Erro em {__file__}: {e}")
            
            # Tenta o método de divisão de string
            try:
                # Preenche com zeros à esquerda até 12 dígitos
                ip_str_padded = ip_str.zfill(12)
                
                # Tenta diferentes formatos de divisão
                formatos = [
                    # Formato: AAA.BBB.CC.DD
                    (3, 3, 2, 2),
                    # Formato: AA.BBB.CCC.DD
                    (2, 3, 3, 2),
                    # Formato: AAA.BB.CC.DDD
                    (3, 2, 2, 3)
                ]
                
                for formato in formatos:
                    a, b, c, d = formato
                    octeto1 = int(ip_str_padded[:a])
                    octeto2 = int(ip_str_padded[a:a+b])
                    octeto3 = int(ip_str_padded[a+b:a+b+c])
                    octeto4 = int(ip_str_padded[a+b+c:a+b+c+d])
                    
                    # Verifica se os octetos são válidos (0-255)
                    if all(0 <= octeto <= 255 for octeto in [octeto1, octeto2, octeto3, octeto4]):
                        # Verifica se o primeiro octeto é válido (1-223)
                        if 1 <= octeto1 <= 223:
                            return f"{octeto1}.{octeto2}.{octeto3}.{octeto4}"
            except Exception as e:
                print(f"Erro em {__file__}: {e}")
            
            # Se tudo falhar, retorna o IP original
            return ip_str
            
        except Exception as e:
            print(f"Erro ao converter IP {ip_numerico}: {str(e)}")
            return str(ip_numerico)
    
    def _carregar_config(self):
        """Carrega configurações do Zabbix"""
        try:
            # Primeiro tenta carregar do arquivo de configuração
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.zabbix_url = config.get('zabbix_url')
                    self.username = config.get('username')
                    self.password = config.get('password')
            
            # Se não encontrou no arquivo ou se algum valor estiver faltando,
            # tenta obter do módulo de credenciais
            if not self.zabbix_url or not self.username or not self.password:
                creds = get_credentials('zabbix')
                self.zabbix_url = self.zabbix_url or creds.get('url')
                self.username = self.username or creds.get('username')
                self.password = self.password or creds.get('password')
                
                # Salva as configurações no arquivo
                self.salvar_config()
            
            # Se ainda estiver faltando algum valor, usa valores padrão
            if not self.zabbix_url:
                self.zabbix_url = "http://10.254.12.15/zabbix/api_jsonrpc.php"
            if not self.username:
                self.username = "admin"
            if not self.password:
                print("⚠️ Senha do Zabbix não configurada. A autenticação pode falhar.")
                self.password = ""
                
        except Exception as e:
            print(f"Erro ao carregar configurações: {str(e)}")
            # Configurações padrão em caso de erro
            self.zabbix_url = "http://10.254.12.15/zabbix/api_jsonrpc.php"
            self.username = "admin"
            self.password = ""
    
    def salvar_config(self):
        """Salva configurações do Zabbix"""
        try:
            # Cria o diretório se não existir
            config_dir = os.path.dirname(os.path.abspath(self.config_file))
            os.makedirs(config_dir, exist_ok=True)
            
            config = {
                'zabbix_url': self.zabbix_url,
                'username': self.username,
                'password': self.password
            }
            
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
            print(f"✅ Configurações do Zabbix salvas em {self.config_file}")
        except Exception as e:
            print(f"❌ Erro ao salvar configurações: {str(e)}")
    
    def autenticar(self):
        """Autentica na API do Zabbix"""
        try:
            # Verifica se temos as configurações necessárias
            if not self.zabbix_url or not self.username or not self.password:
                print("⚠️ Configurações do Zabbix incompletas. Verifique o arquivo zabbix_config.json")
                return False
                
            print(f"🔑 Autenticando no Zabbix: {self.zabbix_url}")
            print(f"👤 Usuário: {self.username}")
            
            def _post_auth(params_key):
                payload = {
                    "jsonrpc": "2.0",
                    "method": "user.login",
                    "params": {params_key: self.username, "password": self.password},
                    "id": 1
                }
                headers = {"Content-Type": "application/json-rpc"}
                return requests.post(self.zabbix_url, headers=headers, json=payload, timeout=10)

            # Primeiro tenta com "user" (compatibilidade), e faz fallback para "username" se necessário
            response = _post_auth("user")

            if response.status_code == 200:
                result = response.json()
                if "result" in result:
                    self.auth_token = result["result"]
                    print("✅ Autenticação no Zabbix bem-sucedida!")
                    return True

                error_msg = result.get('error', {}).get('message', 'Desconhecido')
                error_data = result.get('error', {}).get('data', '')

                if "unexpected parameter \"user\"" in str(error_data):
                    response = _post_auth("username")
                    if response.status_code == 200:
                        result = response.json()
                        if "result" in result:
                            self.auth_token = result["result"]
                            print("✅ Autenticação no Zabbix bem-sucedida!")
                            return True
                        error_msg = result.get('error', {}).get('message', 'Desconhecido')
                        error_data = result.get('error', {}).get('data', '')

                print(f"❌ Erro de autenticação: {error_msg}")
                print(f"   Detalhes: {error_data}")
            else:
                print(f"❌ Erro HTTP: {response.status_code}")
                print(f"   Resposta: {response.text}")

            return False
        except requests.exceptions.ConnectTimeout:
            print(f"❌ Timeout ao conectar ao Zabbix: {self.zabbix_url}")
            print("   Verifique se o servidor está acessível e se a URL está correta")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Erro de conexão com o Zabbix: {str(e)}")
            print("   Verifique se o servidor está acessível e se a URL está correta")
            return False
        except Exception as e:
            print(f"❌ Erro ao autenticar: {str(e)}")
            return False
    
    def _call_api(self, method, params):
        """Faz chamadas à API do Zabbix"""
        if not self.auth_token:
            print(f"🔄 Autenticando para chamar método: {method}")
            if not self.autenticar():
                print(f"❌ Falha na autenticação para método: {method}")
                return {"error": "Não foi possível autenticar no Zabbix"}
        
        print(f"📡 Chamando API Zabbix: {method}")
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "auth": self.auth_token,
            "id": 1
        }
        headers = {"Content-Type": "application/json-rpc"}
        
        try:
            # Aumenta o timeout para 15 segundos
            response = requests.post(self.zabbix_url, headers=headers, json=payload, timeout=15)
            
            if response.status_code != 200:
                print(f"❌ Erro HTTP {response.status_code} ao chamar {method}")
                print(f"   Resposta: {response.text}")
                return {"error": f"Erro HTTP: {response.status_code}"}
            
            result = response.json()
            
            if "error" in result:
                error_msg = result["error"].get("message", "Desconhecido")
                error_data = result["error"].get("data", "")
                print(f"❌ Erro na API ao chamar {method}: {error_msg}")
                print(f"   Detalhes: {error_data}")
                return result
            
            print(f"✅ Chamada API {method} bem-sucedida")
            return result
            
        except requests.exceptions.Timeout:
            print(f"❌ Timeout ao chamar {method}")
            return {"error": "Timeout na conexão com o Zabbix"}
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Erro de conexão ao chamar {method}: {str(e)}")
            return {"error": f"Erro de conexão: {str(e)}"}
        except Exception as e:
            print(f"❌ Erro ao chamar {method}: {str(e)}")
            return {"error": str(e)}
    
    def _carregar_switches(self):
        """Carrega dados dos switches do Excel"""
        try:
            # Verifica se o arquivo existe no caminho atual
            if not os.path.exists(self.arquivo_excel):
                print(f"⚠️ Arquivo {self.arquivo_excel} não encontrado no diretório atual")
                
                # Tenta encontrar o arquivo em caminhos alternativos
                alt_paths = [
                    "switches_zabbix.xlsx",
                    os.path.join("data", "switches_zabbix.xlsx"),
                    os.path.join("..", "switches_zabbix.xlsx"),
                    str(get_file_path("switches_zabbix.xlsx")),
                    "C:/Users/m.vbatista/Desktop/Projetos Automação/ChekList - Copia/switches_zabbix.xlsx",
                    "C:/Users/m.vbatista/Desktop/Automação/switches_zabbix.xlsx"
                ]
                
                for path in alt_paths:
                    if os.path.exists(path):
                        self.arquivo_excel = path
                        print(f"✅ Arquivo encontrado em: {path}")
                        break
                else:
                    print("❌ Arquivo não encontrado em nenhum caminho alternativo")
                    return
            
            print(f"📊 Carregando switches do arquivo: {self.arquivo_excel}")
            
            # Lê a planilha
            df = pd.read_excel(self.arquivo_excel, sheet_name="Switches", header=2)
            df.columns = df.columns.str.strip()
            
            # Processa os dados
            self.switches = []
            self.regionais = {}
            
            for _, row in df.iterrows():
                host_name = str(row["Host"]).strip()
                regional = str(row["Regional"]).strip().upper()
                
                # Converte o IP numérico para formato padrão (ex: 192.168.1.1)
                ip_numerico = row.get("IP", "")
                ip_formatado = self._converter_ip_numerico(ip_numerico)
                
                # Garante que o IP está no formato correto
                if ip_formatado and "." not in ip_formatado:
                    # Tenta novamente com casos especiais
                    ip_str = str(ip_numerico).strip()
                    
                    # Casos especiais para IPs problemáticos
                    if ip_str == "10161021":
                        ip_formatado = "10.16.10.21"
                    elif ip_str == "10161022":
                        ip_formatado = "10.16.10.22"
                    elif ip_str == "10161023":
                        ip_formatado = "10.16.10.23"
                    elif ip_str == "10161024":
                        ip_formatado = "10.16.10.24"
                    elif ip_str == "10161025":
                        ip_formatado = "10.16.10.25"
                    elif ip_str == "10161026":
                        ip_formatado = "10.16.10.26"
                    elif ip_str == "10161027":
                        ip_formatado = "10.16.10.27"
                    elif ip_str == "10161028":
                        ip_formatado = "10.16.10.28"
                    elif ip_str == "10161029":
                        ip_formatado = "10.16.10.29"
                    elif ip_str == "10161030":
                        ip_formatado = "10.16.10.30"
                    # Adiciona casos especiais para os IPs com problemas
                    elif ip_str == "1031020":
                        ip_formatado = "10.3.10.20"
                    elif ip_str == "1031021":
                        ip_formatado = "10.3.10.21"
                    elif ip_str == "1031022":
                        ip_formatado = "10.3.10.22"
                    elif ip_str == "1031023":
                        ip_formatado = "10.3.10.23"
                    elif ip_str == "1031024":
                        ip_formatado = "10.3.10.24"
                    elif ip_str == "1031025":
                        ip_formatado = "10.3.10.25"
                    elif ip_str == "1031026":
                        ip_formatado = "10.3.10.26"
                    elif ip_str == "1031027":
                        ip_formatado = "10.3.10.27"
                    elif ip_str == "1031028":
                        ip_formatado = "10.3.10.28"
                    elif ip_str == "1031029":
                        ip_formatado = "10.3.10.29"
                    elif ip_str == "1031030":
                        ip_formatado = "10.3.10.30"
                    elif ip_str == "1031031":
                        ip_formatado = "10.3.10.31"
                    elif ip_str == "1031032":
                        ip_formatado = "10.3.10.32"
                    elif ip_str == "1031033":
                        ip_formatado = "10.3.10.33"
                    elif ip_str == "1031034":
                        ip_formatado = "10.3.10.34"
                    elif ip_str == "1031035":
                        ip_formatado = "10.3.10.35"
                    elif len(ip_str) == 8:
                        # Formato típico: 10161021 -> 10.16.10.21
                        try:
                            ip_formatado = f"{ip_str[0:2]}.{ip_str[2:4]}.{ip_str[4:6]}.{ip_str[6:8]}"
                        except Exception as e:
                            print(f"Erro em {__file__}: {e}")


                # --- MODELO / LOCAL (FORA DO IF) ---
                modelo_raw = row.get("Modelo", "")
                local_raw = row.get("Local", "")

                modelo = "" if pd.isna(modelo_raw) else str(modelo_raw).strip()
                local = "" if pd.isna(local_raw) else str(local_raw).strip()

                switch = {
                    "host": host_name,
                    "regional": regional,
                    "ip": ip_formatado,
                    "ip_numerico": str(ip_numerico).strip(),
                    "modelo": modelo or "Não informado",
                    "local": local or "Não informado",
                    "status": "desconhecido",
                    "ultima_verificacao": None
                }

                self.switches.append(switch)
                                
                # Agrupa por regional
                if regional not in self.regionais:
                    self.regionais[regional] = []
                self.regionais[regional].append(switch)
            
            print(f"✅ Carregados {len(self.switches)} switches de {len(self.regionais)} regionais")
            
        except Exception as e:
            print(f"Erro ao carregar switches: {str(e)}")
    
    def verificar_switch(self, host_name):
        """Verifica o status de um switch específico"""
        try:
            print(f"🔍 Verificando switch: {host_name}")
            
            # Encontra o switch na lista pelo nome
            switch_info = None
            for switch in self.switches:
                if switch["host"] == host_name:
                    switch_info = switch
                    break
            
            if not switch_info:
                print(f"❌ Switch {host_name} não encontrado na lista local")
                return {"status": "não encontrado", "detalhes": None}
            
            # Tenta buscar o host no Zabbix pelo nome
            host_resp = self._call_api("host.get", {
                "filter": {"name": host_name},
                "output": ["hostid", "name", "status"]
            })
            
            # Se não encontrou pelo nome, tenta pelo IP
            if not host_resp.get("result") and switch_info["ip"]:
                print(f"⚠️ Switch não encontrado pelo nome, tentando pelo IP: {switch_info['ip']}")
                
                # Busca hosts que contenham o IP no nome
                host_resp = self._call_api("host.get", {
                    "search": {"name": switch_info["ip"]},
                    "searchWildcardsEnabled": True,
                    "output": ["hostid", "name", "status"]
                })
                
                # Se ainda não encontrou, tenta buscar pelo IP numérico no nome
                if not host_resp.get("result") and "ip_numerico" in switch_info:
                    print(f"⚠️ Tentando buscar pelo IP numérico no nome: {switch_info['ip_numerico']}")
                    host_resp = self._call_api("host.get", {
                        "search": {"name": switch_info["ip_numerico"]},
                        "searchWildcardsEnabled": True,
                        "output": ["hostid", "name", "status"]
                    })
                
                # Se ainda não encontrou, tenta buscar por interfaces com esse IP
                if not host_resp.get("result"):
                    print(f"⚠️ Tentando buscar por interfaces com IP: {switch_info['ip']}")
                    interface_resp = self._call_api("hostinterface.get", {
                        "filter": {"ip": switch_info["ip"]},
                        "output": ["hostid", "ip"],
                        "selectHosts": ["hostid", "name", "status"]
                    })
                    
                    if interface_resp.get("result"):
                        # Converte o resultado para o formato esperado
                        host_resp = {
                            "result": [interface["hosts"][0] for interface in interface_resp["result"]]
                        }
                        
                        # Atualiza o IP do switch com o IP real da interface
                        real_ip = interface_resp["result"][0]["ip"]
                        if real_ip and real_ip != switch_info["ip"]:
                            print(f"ℹ️ Atualizando IP do switch: {switch_info['ip']} -> {real_ip}")
                            switch_info["ip"] = real_ip
                            
                        print(f"✅ Encontrado host pela interface IP: {switch_info['ip']}")
                
                # Se ainda não encontrou, tenta buscar por interfaces com esse IP
                if not host_resp.get("result"):
                    print(f"⚠️ Tentando buscar por interfaces com IP: {switch_info['ip']}")
                    host_resp = self._call_api("hostinterface.get", {
                        "filter": {"ip": switch_info["ip"]},
                        "output": ["hostid"],
                        "selectHosts": ["hostid", "name", "status"]
                    })
                    
                    if host_resp.get("result"):
                        # Converte o resultado para o formato esperado
                        host_resp = {
                            "result": [host["hosts"][0] for host in host_resp["result"]]
                        }
            
            if not host_resp.get("result"):
                print(f"❌ Switch não encontrado no Zabbix: {host_name} (IP: {switch_info['ip']})")
                
                # Atualiza o status na lista
                switch_info["status"] = "não encontrado"
                switch_info["ultima_verificacao"] = datetime.now().isoformat()
                
                return {"status": "não encontrado", "detalhes": None}
            
            host_id = host_resp["result"][0]["hostid"]
            host_status = "ativo" if host_resp["result"][0]["status"] == "0" else "inativo"
            zabbix_name = host_resp["result"][0]["name"]
            
            print(f"✅ Switch encontrado no Zabbix: {zabbix_name} (ID: {host_id}, Status: {host_status})")
            
            # Se o nome no Zabbix for diferente, mostra a correspondência
            if zabbix_name != host_name:
                print(f"ℹ️ Nome no Excel: {host_name} | Nome no Zabbix: {zabbix_name}")
            
            # Busca problemas
            print(f"🔍 Buscando problemas para o switch: {host_name}")
            problems_resp = self._call_api("problem.get", {
                "hostids": [host_id],
                "output": "extend",
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": 5
            })
            
            problemas = problems_resp.get("result", [])
            print(f"✅ Encontrados {len(problemas)} problemas para o switch: {host_name}")
            
            # Busca itens
            print(f"🔍 Buscando itens de monitoramento para o switch: {host_name}")
            items_resp = self._call_api("item.get", {
                "hostids": host_id,
                "output": ["name", "lastvalue", "units", "key_"],
                "sortfield": "name"
            })
            
            # Processa itens
            items = []
            
            # Itens importantes para mostrar
            itens_importantes = {
                "cpu": [],
                "memoria": [],
                "uptime": [],
                "interfaces": []
            }
            
            # Primeiro, filtra e categoriza os itens
            for item in items_resp.get("result", []):
                item_name = item["name"].lower()
                
                # CPU
                if "cpu utilization" in item_name:
                    itens_importantes["cpu"].append({
                        "nome": item["name"],
                        "valor": item["lastvalue"],
                        "unidade": item["units"]
                    })
                
                # Memória
                elif "memory" in item_name or "memória" in item_name:
                    itens_importantes["memoria"].append({
                        "nome": item["name"],
                        "valor": item["lastvalue"],
                        "unidade": item["units"]
                    })
                
                # Uptime
                elif "uptime" in item_name:
                    # Converte uptime para formato legível
                    uptime_seconds = int(float(item["lastvalue"]))
                    days = uptime_seconds // 86400
                    hours = (uptime_seconds % 86400) // 3600
                    minutes = (uptime_seconds % 3600) // 60
                    
                    itens_importantes["uptime"].append({
                        "nome": "Tempo de atividade",
                        "valor": f"{days} dias, {hours} horas, {minutes} minutos",
                        "unidade": ""
                    })
                
                # Interfaces (apenas as com tráfego significativo)
                elif "interface" in item_name and "bits" in item_name:
                    # Verifica se é uma interface com tráfego significativo
                    try:
                        bits = float(item["lastvalue"])
                        if bits > 100000:  # Mais de 100 Kbps
                            # Simplifica o nome da interface
                            interface_name = item["name"]
                            if "(" in interface_name:
                                interface_name = interface_name.split("(")[0].strip()
                            
                            # Determina se é recebido ou enviado
                            direction = "recebido" if "received" in item_name else "enviado"
                            
                            # Converte para unidade mais legível
                            if bits >= 1000000:
                                valor = f"{bits/1000000:.2f}"
                                unidade = "Mbps"
                            else:
                                valor = f"{bits/1000:.2f}"
                                unidade = "Kbps"
                                
                            itens_importantes["interfaces"].append({
                                "nome": f"{interface_name} - Tráfego {direction}",
                                "valor": valor,
                                "unidade": unidade
                            })
                    except Exception as e:
                        print(f"Erro em {__file__}: {e}")
            
            # Adiciona os itens importantes na ordem correta
            # 1. CPU e Memória
            items.extend(itens_importantes["cpu"])
            items.extend(itens_importantes["memoria"])
            
            # 2. Uptime
            items.extend(itens_importantes["uptime"])
            
            # 3. Interfaces com mais tráfego (limitado a 10)
            # Ordena por valor numérico (tráfego)
            interfaces_ordenadas = sorted(
                itens_importantes["interfaces"], 
                key=lambda x: float(x["valor"]), 
                reverse=True
            )
            items.extend(interfaces_ordenadas[:10])
            
            print(f"✅ Encontrados {len(items)} itens relevantes para o switch: {host_name}")
            
            # Determina status
            status = "online"
            if host_status == "inativo":
                status = "offline"
            elif problemas:
                status = "warning"
            
            print(f"📊 Status final do switch {host_name}: {status}")
            
            # Atualiza o switch na lista
            switch_info["status"] = status
            switch_info["ultima_verificacao"] = datetime.now().isoformat()
            
            # Se o nome no Zabbix for diferente, armazena para referência
            if zabbix_name != host_name:
                switch_info["zabbix_name"] = zabbix_name
            
            return {
                "status": status,
                "detalhes": {
                    "host_id": host_id,
                    "host_status": host_status,
                    "problemas": problemas,
                    "itens": items
                }
            }
            
        except Exception as e:
            print(f"❌ Erro ao verificar switch {host_name}: {str(e)}")
            return {"status": "erro", "detalhes": str(e)}
    
    def verificar_todos_switches(self, max_switches=None):
        """Verifica o status de todos os switches
        
        Args:
            max_switches: Número máximo de switches a verificar (None = todos)
        """
        resultados = {}
        
        # Filtra switches desconhecidos primeiro
        switches_desconhecidos = [s for s in self.switches if s.get('status') == 'desconhecido']
        switches_conhecidos = [s for s in self.switches if s.get('status') != 'desconhecido']
        
        # Prioriza verificar switches desconhecidos
        switches_ordenados = switches_desconhecidos + switches_conhecidos
        
        # Limita o número de switches se necessário
        if max_switches is not None:
            switches_ordenados = switches_ordenados[:max_switches]
        
        # Verifica os switches
        for switch in switches_ordenados:
            host_name = switch["host"]
            resultado = self.verificar_switch(host_name)
            resultados[host_name] = resultado
        
        return resultados
    
    def verificar_regional(self, regional):
        """Verifica o status de todos os switches de uma regional"""
        if regional not in self.regionais:
            return {"error": f"Regional {regional} não encontrada"}
        
        resultados = {}
        for switch in self.regionais[regional]:
            host_name = switch["host"]
            resultado = self.verificar_switch(host_name)
            resultados[host_name] = resultado
        
        return resultados
    
    def listar_regionais(self):
        """Lista todas as regionais com switches"""
        return list(self.regionais.keys())
    
    def obter_switches_regional(self, regional):
        """Obtém todos os switches de uma regional"""
        switches = self.regionais.get(regional, [])
        
        # Garante que todos os IPs estão convertidos corretamente
        for switch in switches:
            # Se o IP não parece estar no formato correto (sem pontos), converte
            if switch.get("ip") and "." not in switch.get("ip", ""):
                switch["ip"] = self._converter_ip_numerico(switch["ip"])
                
        return switches
        
    def atualizar_ips(self):
        """Atualiza todos os IPs para o formato correto"""
        for switch in self.switches:
            # Se o IP não parece estar no formato correto (sem pontos), converte
            if switch.get("ip") and "." not in switch.get("ip", ""):
                switch["ip"] = self._converter_ip_numerico(switch["ip"])
    
    def gerar_relatorio_html(self, arquivo_saida="status_switches.html"):
        """Gera relatório HTML com status dos switches"""
        # Verifica todos os switches
        self.verificar_todos_switches()
        
        # Monta HTML
        html_sections = {}
        for regional, switches in self.regionais.items():
            switches_html = ""
            for switch in switches:
                status_class = "success" if switch["status"] == "online" else "danger" if switch["status"] == "offline" else "warning"
                status_icon = "✅" if switch["status"] == "online" else "❌" if switch["status"] == "offline" else "⚠️"
                
                switches_html += f"""
                <div class="card mb-2">
                    <div class="card-header bg-{status_class} text-white d-flex justify-content-between align-items-center">
                        <h6 class="mb-0">{switch["host"]}</h6>
                        <span>{status_icon}</span>
                    </div>
                    <div class="card-body">
                        <p class="mb-1"><strong>IP:</strong> {switch["ip"]}</p>
                        <p class="mb-1"><strong>Modelo:</strong> {switch["modelo"]}</p>
                        <p class="mb-1"><strong>Local:</strong> {switch["local"]}</p>
                        <p class="mb-0"><strong>Status:</strong> {switch["status"].capitalize()}</p>
                    </div>
                </div>
                """
            
            html_sections[regional] = switches_html
        
        # Monta HTML final
        agora = datetime.now()
        html_content = f"""
        <!DOCTYPE html>
        <html lang="pt-br">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Status dos Switches - Zabbix</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                .regional-header {{
                    background: linear-gradient(135deg, #003366, #0066cc);
                    color: white;
                    padding: 10px 15px;
                    margin-bottom: 15px;
                    border-radius: 5px;
                }}
            </style>
        </head>
        <body>
            <div class="container py-4">
                <h1 class="text-center mb-4">Status dos Switches por Regional</h1>
                <div class="alert alert-info text-center mb-4">
                    <strong>📅 Última atualização:</strong> {agora.strftime('%d/%m/%Y às %H:%M:%S')}
                </div>
        """
        
        for regional, content in html_sections.items():
            html_content += f"""
                <div class="mb-4">
                    <div class="regional-header">
                        <h3 class="mb-0">{regional}</h3>
                    </div>
                    <div class="row">
                        <div class="col-12">
                            {content}
                        </div>
                    </div>
                </div>
            """
        
        html_content += """
            </div>
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        </body>
        </html>
        """
        
        # Salva o HTML
        with open(arquivo_saida, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return arquivo_saida

# Exemplo de uso
if __name__ == "__main__":
    gerenciador = GerenciadorSwitches()
    
    print("🔄 Autenticando no Zabbix...")
    if gerenciador.autenticar():
        print("✅ Autenticado com sucesso!")
        
        print("\n📋 Regionais com switches:")
        for regional in gerenciador.listar_regionais():
            switches = gerenciador.obter_switches_regional(regional)
            print(f"  • {regional}: {len(switches)} switches")
        
        print("\n🔍 Verificando switches...")
        for i, switch in enumerate(gerenciador.switches[:3], 1):  # Verifica apenas os 3 primeiros para exemplo
            resultado = gerenciador.verificar_switch(switch["host"])
            status = resultado["status"]
            print(f"  {i}. {switch['host']} - {status}")
        
        print("\n📊 Gerando relatório HTML...")
        arquivo_html = gerenciador.gerar_relatorio_html()
        print(f"✅ Relatório salvo em: {arquivo_html}")
    else:
        print("❌ Falha na autenticação")