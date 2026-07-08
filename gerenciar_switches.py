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
import re
import sys
import builtins
import unicodedata
import time
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from utils_paths import get_file_path


_ORIGINAL_PRINT = builtins.print
_PRINT_REPLACEMENTS = {
    "✅": "[OK]",
    "❌": "[ERRO]",
    "⚠️": "[AVISO]",
    "⚠": "[AVISO]",
    "📊": "[INFO]",
    "📡": "[API]",
    "🔍": "[CHECK]",
    "🟢": "[ONLINE]",
    "🟡": "[WARN]",
    "🔴": "[OFFLINE]",
    "ℹ️": "[INFO]",
    "ℹ": "[INFO]",
}


def _sanitize_console_text(value):
    text = str(value)
    for old_value, new_value in _PRINT_REPLACEMENTS.items():
        text = text.replace(old_value, new_value)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def print(*args, **kwargs):
    try:
        _ORIGINAL_PRINT(*args, **kwargs)
    except UnicodeEncodeError:
        _ORIGINAL_PRINT(*(_sanitize_console_text(arg) for arg in args), **kwargs)

# Importa o módulo de credenciais
try:
    from credentials import get_credentials
except ImportError:
    # Fallback para caso o módulo não esteja disponível
    def get_credentials(service, prompt_if_missing=False):
        if service == 'zabbix':
            return {
                'url': 'https://zabbix.example.local/zabbix/api_jsonrpc.php',
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
                    zabbix_url_env = zabbix_config.get('url')
                    zabbix_username_env = zabbix_config.get('username')
                    zabbix_password_env = zabbix_config.get('password')
            else:
                ENV_CONFIG = {}
                zabbix_config = {}
                arquivo_excel_env = None
                zabbix_url_env = None
                zabbix_username_env = None
                zabbix_password_env = None
        except Exception as e:
            print(f"⚠️ Erro ao carregar environment.json: {e}")
            ENV_CONFIG = {}
            zabbix_config = {}
            arquivo_excel_env = None
            zabbix_url_env = None
            zabbix_username_env = None
            zabbix_password_env = None
        
        # Define o arquivo Excel (prioridade: parâmetro > environment.json > padrão)
        self.arquivo_excel = arquivo_excel or arquivo_excel_env or "switches_zabbix.xlsx"
        self.config_file = config_file
        self.zabbix_url = None
        self.username = None
        self.password = None
        self.auth_token = None
        self.switches = []
        self.regionais = {}
        self.zabbix_url_env = zabbix_url_env
        self.zabbix_username_env = zabbix_username_env
        self.zabbix_password_env = zabbix_password_env
        self.status_cache_file = Path("output") / "switches_status_cache.json"
        self.status_cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Carrega configurações
        self._carregar_config()

        # Tenta carregar dados dos switches pela API (mais atualizado)
        # Se falhar, volta para XLSX (fallback automático)
        sucesso_api = self._carregar_switches_api()

        if not sucesso_api:
            print("\n⚠️ Carregamento pela API falhou. Usando fallback XLSX...")
            self._carregar_switches()

        # Atualiza todos os IPs para o formato correto
        self.atualizar_ips()

    def _carregar_status_cache(self):
        try:
            if self.status_cache_file.exists():
                with open(self.status_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"⚠️ Erro ao carregar cache de status dos switches: {e}")
        return {}

    def _salvar_status_cache(self, cache):
        try:
            with open(self.status_cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Erro ao salvar cache de status dos switches: {e}")

    def _persistir_status_switch(self, switch_info):
        if not switch_info or not switch_info.get("host"):
            return

        cache = self._carregar_status_cache()
        cache[switch_info["host"]] = {
            "status": switch_info.get("status", "desconhecido"),
            "ultima_verificacao": switch_info.get("ultima_verificacao"),
            "ip": switch_info.get("ip"),
            "zabbix_name": switch_info.get("zabbix_name"),
            "status_reason": switch_info.get("status_reason"),
            "status_details": switch_info.get("status_details"),
            "warning_problemas": switch_info.get("warning_problemas") or [],
            "warning_resumo": switch_info.get("warning_resumo")
        }
        self._salvar_status_cache(cache)
        
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

    def _normalizar_texto_host(self, texto):
        """Normaliza texto para comparações conservadoras de host"""
        texto_normalizado = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
        texto_normalizado = texto_normalizado.upper().replace("_", "-")
        return re.sub(r"[^A-Z0-9]", "", texto_normalizado)

    def _extrair_identificadores_host(self, host_name):
        """Extrai identificadores técnicos do nome do switch"""
        padrao = re.compile(r"(SWT[A-Z0-9_-]+(?:-\d+|_\d+|CORE|WAN)?)", re.IGNORECASE)
        identificadores = []

        for valor in padrao.findall(str(host_name or "")):
            identificador = valor.upper().replace("_", "-").strip("-")
            if identificador and identificador not in identificadores:
                identificadores.append(identificador)

        return identificadores

    def _buscar_host_por_identificador(self, host_name):
        """Busca host no Zabbix por identificador único do switch"""
        identificadores = self._extrair_identificadores_host(host_name)

        if not identificadores:
            return {"result": []}

        host_resp = self._call_api("host.get", {
            "output": ["hostid", "name", "status"],
            "limit": 5000,
            "sortfield": "name"
        })

        hosts_zabbix = host_resp.get("result", [])

        for identificador in identificadores:
            print(f"⚠️ Tentando buscar por identificador do switch: {identificador}")

            candidatos = []
            identificador_normalizado = self._normalizar_texto_host(identificador)

            for host in hosts_zabbix:
                nome_normalizado = self._normalizar_texto_host(host.get("name"))
                if identificador_normalizado and identificador_normalizado in nome_normalizado:
                    candidatos.append(host)

            candidatos_unicos = []
            hostids_vistos = set()
            for host in candidatos:
                host_id = host.get("hostid")
                if host_id and host_id not in hostids_vistos:
                    candidatos_unicos.append(host)
                    hostids_vistos.add(host_id)

            if len(candidatos_unicos) == 1:
                print(f"✅ Encontrado host por identificador: {candidatos_unicos[0]['name']}")
                return {"result": candidatos_unicos}

            if len(candidatos_unicos) > 1:
                print(f"⚠️ Identificador ambíguo no Zabbix: {identificador} ({len(candidatos_unicos)} candidatos)")

        return {"result": []}
    
    def _carregar_config(self):
        """Carrega configurações do Zabbix"""
        try:
            # Primeiro tenta carregar do environment.json
            self.zabbix_url = self.zabbix_url_env or self.zabbix_url
            self.username = self.zabbix_username_env or self.username
            self.password = self.zabbix_password_env or self.password

            # Depois tenta carregar do arquivo de configuração legado
            if (not self.zabbix_url or not self.username or not self.password) and os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.zabbix_url = self.zabbix_url or config.get('zabbix_url')
                    self.username = self.username or config.get('username')
                    self.password = self.password or config.get('password')
            
            # Se não encontrou no arquivo ou se algum valor estiver faltando,
            # tenta obter do módulo de credenciais
            if not self.zabbix_url or not self.username or not self.password:
                creds = get_credentials('zabbix')
                self.zabbix_url = self.zabbix_url or creds.get('url')
                self.username = self.username or creds.get('username')
                self.password = self.password or creds.get('password')
                
                if self.zabbix_url and self.username and self.password:
                    self.salvar_config()
            
            # Se ainda estiver faltando algum valor, usa valores padrão
            if not self.zabbix_url:
                self.zabbix_url = "https://zabbix.example.local/zabbix/api_jsonrpc.php"
            if not self.username:
                self.username = "admin"
            if not self.password:
                print("⚠️ Senha do Zabbix não configurada. A autenticação pode falhar.")
                self.password = ""
                
        except Exception as e:
            print(f"Erro ao carregar configurações: {str(e)}")
            # Configurações padrão em caso de erro
            self.zabbix_url = "https://zabbix.example.local/zabbix/api_jsonrpc.php"
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
            status_cache = self._carregar_status_cache()

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

                status_salvo = status_cache.get(host_name, {}) if isinstance(status_cache, dict) else {}
                if status_salvo:
                    switch["status"] = status_salvo.get("status") or switch["status"]
                    switch["ultima_verificacao"] = status_salvo.get("ultima_verificacao")
                    if status_salvo.get("ip"):
                        switch["ip"] = status_salvo.get("ip")
                    if status_salvo.get("zabbix_name"):
                        switch["zabbix_name"] = status_salvo.get("zabbix_name")
                    switch["status_reason"] = status_salvo.get("status_reason")
                    switch["status_details"] = status_salvo.get("status_details")
                    switch["warning_problemas"] = status_salvo.get("warning_problemas") or []
                    switch["warning_resumo"] = status_salvo.get("warning_resumo")

                self.switches.append(switch)
                                
                # Agrupa por regional
                if regional not in self.regionais:
                    self.regionais[regional] = []
                self.regionais[regional].append(switch)
            
            print(f"✅ Carregados {len(self.switches)} switches de {len(self.regionais)} regionais")

        except Exception as e:
            print(f"Erro ao carregar switches: {str(e)}")

    def _carregar_switches_api(self):
        """Carrega switches diretamente da API Zabbix (sem XLSX)"""
        try:
            print("📡 Carregando switches da API Zabbix...")

            if not self.auth_token:
                if not self.autenticar():
                    print("❌ Falha ao autenticar. Retornando para fallback XLSX...")
                    return False

            self.switches = []
            self.regionais = {}

            hostgroup_resp = self._call_api("hostgroup.get", {
                "output": ["groupid", "name"],
                "sortfield": "name"
            })
            hostgroups = hostgroup_resp.get("result", []) or []
            print(f"📊 Encontrados {len(hostgroups)} host groups")

            hosts_por_id = {}
            for hostgroup in hostgroups:
                groupid = hostgroup.get("groupid")
                if not groupid:
                    continue

                hosts_resp = self._call_api("host.get", {
                    "groupids": [groupid],
                    "output": [
                        "hostid", "host", "name", "status",
                        "maintenance_status", "maintenance_type", "maintenanceid"
                    ],
                    "selectInterfaces": ["ip", "type", "main", "useip", "dns"],
                    "selectGroups": ["groupid", "name"],
                    "selectInventory": ["type", "location", "site_notes"],
                    "sortfield": "name",
                    "limit": 10000,
                })

                for host in hosts_resp.get("result", []) or []:
                    host_id = str(host.get("hostid") or "").strip()
                    nome = str(host.get("name") or host.get("host") or "").strip()
                    if not host_id or "SWITCH" not in nome.upper():
                        continue
                    if not host.get("groups"):
                        host["groups"] = [{"groupid": groupid, "name": hostgroup.get("name", "")}]
                    hosts_por_id[host_id] = host

            hosts = sorted(hosts_por_id.values(), key=lambda item: str(item.get("name") or item.get("host") or ""))
            if not hosts:
                print("⚠️ Nenhum host de switch retornado pela API Zabbix.")
                return False

            hostids = [host["hostid"] for host in hosts]
            problemas_por_host = self._carregar_problemas_ativos_por_host(hostids)
            hostids_com_alerta_uplink = [
                str(hostid)
                for hostid, problemas_host in problemas_por_host.items()
                if any(self._eh_alerta_speed_uplink(problema.get("name")) for problema in problemas_host)
            ]
            itens_uplink_por_host = self._carregar_itens_speed_uplink_por_host(hostids_com_alerta_uplink)
            agora = datetime.now().isoformat()

            for host in hosts:
                host_id = str(host.get("hostid") or "").strip()
                nome_host = str(host.get("name") or host.get("host") or host_id).strip()
                zabbix_host = str(host.get("host") or nome_host).strip()
                regional_name = self._selecionar_regional_zabbix(host.get("groups") or [])
                interface = self._selecionar_interface_principal(host.get("interfaces") or [])
                ip = interface.get("ip") or interface.get("dns") or ""
                inventory = host.get("inventory") or {}
                problemas = problemas_por_host.get(host_id, [])
                problemas_filtrados, nomes_problemas = self._filtrar_problemas_por_estado_atual(
                    problemas,
                    itens_uplink_por_host.get(host_id, [])
                )
                em_manutencao = str(host.get("maintenance_status") or "0") == "1"

                status = "online"
                status_reason = None
                status_details = None
                if str(host.get("status") or "0") != "0":
                    status = "inativo"
                    status_reason = "Host encontrado no Zabbix, mas está marcado como inativo/desabilitado."
                    status_details = f"Host Zabbix: {nome_host} | Status do host: inativo"
                elif nomes_problemas:
                    status = "warning"

                switch = {
                    "host": nome_host,
                    "regional": regional_name,
                    "ip": ip,
                    "ip_numerico": ip,
                    "modelo": inventory.get("type") or "Não informado",
                    "local": inventory.get("location") or "Não informado",
                    "status": status,
                    "ultima_verificacao": agora,
                    "hostid": host_id,
                    "zabbix_host": zabbix_host,
                    "zabbix_name": nome_host,
                    "zabbix_status": host.get("status", "0"),
                    "maintenance_status": host.get("maintenance_status"),
                    "maintenance_type": host.get("maintenance_type"),
                    "maintenanceid": host.get("maintenanceid"),
                    "em_manutencao": em_manutencao,
                    "status_reason": status_reason,
                    "status_details": status_details,
                    "warning_problemas": nomes_problemas if status == "warning" else [],
                    "warning_resumo": nomes_problemas[0] if status == "warning" and nomes_problemas else None,
                }

                self.switches.append(switch)
                self.regionais.setdefault(regional_name, []).append(switch)
                self._persistir_status_switch(switch)

            print(f"✅ Carregados {len(self.switches)} switches de {len(self.regionais)} regionais (via API)")
            return True

        except Exception as e:
            print(f"❌ Erro ao carregar switches da API: {str(e)}")
            print("⚠️  Retornando para fallback XLSX...")
            return False

    def _selecionar_regional_zabbix(self, groups):
        """Escolhe o host group que representa a regional do switch."""
        grupos = [str(group.get("name") or "").strip() for group in groups if group.get("name")]
        if not grupos:
            return "SEM_REGIONAL"

        genericos = {
            "SWITCH", "SWITCHES", "NETWORK", "NETWORKS", "INFRA",
            "INFRAESTRUTURA", "FIREWALLS", "SERVERS", "SERVIDORES"
        }
        candidatos_regionais = [
            grupo for grupo in grupos
            if "REGIONAL" in grupo.upper() or grupo.upper().startswith(("REG_", "RG_"))
        ]
        if candidatos_regionais:
            return sorted(candidatos_regionais)[0]

        candidatos = [grupo for grupo in grupos if grupo.upper() not in genericos]
        return sorted(candidatos or grupos)[0]

    def _selecionar_interface_principal(self, interfaces):
        """Seleciona a interface principal, preferindo SNMP e marcada como main."""
        if not interfaces:
            return {}

        def score(interface):
            interface_type = str(interface.get("type") or "")
            main = str(interface.get("main") or "")
            ip = str(interface.get("ip") or "").strip()
            return (
                1 if interface_type == "2" else 0,  # SNMP
                1 if main == "1" else 0,
                1 if ip else 0,
            )

        return sorted(interfaces, key=score, reverse=True)[0]

    def _janela_problemas_zabbix_inicio(self):
        """Inicio da janela operacional usada para espelhar Problems do Zabbix."""
        try:
            segundos = int(os.getenv("ZABBIX_PROBLEM_WINDOW_SECONDS", "86400"))
        except ValueError:
            segundos = 86400
        return int(time.time()) - max(segundos, 60)

    def _problema_zabbix_aberto_e_recente(self, problema, janela_inicio=None):
        """Mantem somente problemas abertos e dentro da janela recente do Zabbix."""
        if not problema:
            return False

        r_eventid = str(problema.get("r_eventid", "0") or "0")
        r_clock = str(problema.get("r_clock", "0") or "0")
        if r_eventid not in {"", "0"} or r_clock not in {"", "0"}:
            return False

        if janela_inicio is None:
            janela_inicio = self._janela_problemas_zabbix_inicio()

        clock = problema.get("clock")
        if clock in (None, ""):
            return True

        try:
            return int(clock) >= int(janela_inicio)
        except (TypeError, ValueError):
            return True

    def _normalizar_texto_alerta(self, texto):
        """Normaliza texto para comparar nomes de alertas e itens do Zabbix."""
        texto_normalizado = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
        return texto_normalizado.lower()

    def _eh_alerta_speed_uplink(self, nome_alerta):
        """Identifica alertas de negociacao de speed inferior no UPLINK."""
        texto = self._normalizar_texto_alerta(nome_alerta)
        if "uplink" not in texto:
            return False
        return any(termo in texto for termo in ("speed", "velocidade"))

    def _valor_speed_em_bps(self, valor, unidade=""):
        texto_valor = self._normalizar_texto_alerta(valor).replace(",", ".").strip()
        texto_unidade = self._normalizar_texto_alerta(unidade)

        if "1000000000" in texto_valor or "1 gbps" in texto_valor or "1gbps" in texto_valor:
            return 1_000_000_000
        if "1000 mbps" in texto_valor or "1000mbps" in texto_valor:
            return 1_000_000_000

        match = re.search(r"[-+]?\d+(?:\.\d+)?", texto_valor)
        if not match:
            return None

        try:
            numero = float(match.group(0))
        except ValueError:
            return None

        texto_completo = f"{texto_valor} {texto_unidade}"
        if "gbps" in texto_completo or "gbit" in texto_completo:
            return numero * 1_000_000_000
        if "mbps" in texto_completo or "mbit" in texto_completo:
            return numero * 1_000_000
        if "kbps" in texto_completo or "kbit" in texto_completo:
            return numero * 1_000

        return numero

    def _uplink_speed_normalizado(self, itens):
        """Retorna True quando algum item de speed do UPLINK mostra 1Gbps ou mais."""
        for item in itens or []:
            nome_item = self._normalizar_texto_alerta(item.get("name") or item.get("key_"))
            if "uplink" not in nome_item or not any(termo in nome_item for termo in ("speed", "velocidade")):
                continue

            speed_bps = self._valor_speed_em_bps(item.get("lastvalue"), item.get("units"))
            if speed_bps is not None and speed_bps >= 1_000_000_000:
                return True

        return False

    def _filtrar_problemas_por_estado_atual(self, problemas, itens=None):
        """Remove alertas historicos de UPLINK quando o speed atual ja voltou ao normal."""
        janela_inicio = self._janela_problemas_zabbix_inicio()
        problemas_ativos = [
            problema for problema in (problemas or [])
            if self._problema_zabbix_aberto_e_recente(problema, janela_inicio)
        ]

        uplink_normal = self._uplink_speed_normalizado(itens)
        problemas_filtrados = []
        nomes_problemas = []

        for problema in problemas_ativos:
            nome = problema.get("name") or ""
            if uplink_normal and self._eh_alerta_speed_uplink(nome):
                print(f"⚠️ Ignorando warning de UPLINK ja normalizado: {nome}")
                continue

            problemas_filtrados.append(problema)
            if nome:
                nomes_problemas.append(nome)

        return problemas_filtrados, nomes_problemas

    def _carregar_itens_speed_uplink_por_host(self, hostids):
        """Carrega itens de speed do UPLINK para hosts com alerta relacionado."""
        itens_por_host = {str(hostid): [] for hostid in hostids}
        hostids = [str(hostid) for hostid in hostids if hostid]
        if not hostids:
            return itens_por_host

        try:
            for i in range(0, len(hostids), 100):
                lote = hostids[i:i + 100]
                items_resp = self._call_api("item.get", {
                    "hostids": lote,
                    "output": ["hostid", "name", "lastvalue", "units", "key_"],
                    "sortfield": "name",
                    "limit": 10000,
                })

                for item in items_resp.get("result", []) or []:
                    host_id = str(item.get("hostid") or "").strip()
                    nome_item = self._normalizar_texto_alerta(item.get("name") or item.get("key_"))
                    if "uplink" in nome_item and any(termo in nome_item for termo in ("speed", "velocidade")):
                        itens_por_host.setdefault(host_id, []).append(item)
        except Exception as e:
            print(f"⚠️ Erro ao carregar itens de speed UPLINK: {e}")

        return itens_por_host

    def _carregar_problemas_ativos_por_host(self, hostids):
        """Retorna problemas ativos por hostid usando problem.get + trigger.get."""
        problemas_por_host = {str(hostid): [] for hostid in hostids}
        if not hostids:
            return problemas_por_host

        try:
            janela_inicio = self._janela_problemas_zabbix_inicio()
            problems_resp = self._call_api("problem.get", {
                "hostids": list(hostids),
                "output": "extend",
                "time_from": janela_inicio,
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": 10000,
            })
            problemas = [
                problema for problema in (problems_resp.get("result", []) or [])
                if self._problema_zabbix_aberto_e_recente(problema, janela_inicio)
            ]
            trigger_ids = sorted({
                str(problema.get("objectid") or "").strip()
                for problema in problemas
                if str(problema.get("object") or "0") == "0" and problema.get("objectid")
            })
            if not trigger_ids:
                return problemas_por_host

            trigger_hosts = {}
            for i in range(0, len(trigger_ids), 500):
                lote = trigger_ids[i:i + 500]
                triggers_resp = self._call_api("trigger.get", {
                    "triggerids": lote,
                    "output": ["triggerid", "description", "priority"],
                    "selectHosts": ["hostid", "name"],
                })

                for trigger in triggers_resp.get("result", []) or []:
                    trigger_id = str(trigger.get("triggerid") or "").strip()
                    trigger_hosts[trigger_id] = [
                        str(host.get("hostid") or "").strip()
                        for host in trigger.get("hosts", []) or []
                        if host.get("hostid")
                    ]

            for problema in problemas:
                trigger_id = str(problema.get("objectid") or "").strip()
                nome = problema.get("name") or "Alerta identificado no Zabbix"
                problema = {
                    "name": nome,
                    "triggerid": trigger_id,
                    "eventid": problema.get("eventid"),
                    "clock": problema.get("clock"),
                    "r_eventid": problema.get("r_eventid"),
                    "r_clock": problema.get("r_clock"),
                    "priority": problema.get("severity"),
                }
                for host_id in trigger_hosts.get(trigger_id, []):
                    problemas_por_host.setdefault(host_id, []).append(problema)
        except Exception as e:
            print(f"⚠️ Erro ao carregar warnings dos switches via problem.get: {e}")

        return problemas_por_host

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
                return {
                    "status": "não encontrado",
                    "detalhes": None,
                    "status_reason": "Switch não encontrado na lista local carregada da planilha.",
                    "ultima_verificacao": datetime.now().isoformat()
                }
            
            # Quando a lista vem da API, ja temos o hostid e evitamos depender de buscas por nome.
            if switch_info.get("hostid"):
                host_resp = self._call_api("host.get", {
                    "hostids": [switch_info["hostid"]],
                    "output": ["hostid", "host", "name", "status"],
                    "selectInterfaces": ["ip", "type", "main", "useip", "dns"]
                })
            else:
                # Tenta buscar o host no Zabbix pelo nome
                host_resp = self._call_api("host.get", {
                    "filter": {"name": host_name},
                    "output": ["hostid", "host", "name", "status"]
                })

            # Se não encontrou pelo nome exato, tenta usar um identificador técnico único do switch
            if not host_resp.get("result"):
                host_resp = self._buscar_host_por_identificador(host_name)
            
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
                switch_info["status_reason"] = "Não localizado no Zabbix pelo nome, identificador técnico, IP ou interface."
                switch_info["status_details"] = f"Host Excel: {host_name} | IP: {switch_info.get('ip') or 'N/A'}"
                switch_info["warning_problemas"] = []
                switch_info["warning_resumo"] = None
                self._persistir_status_switch(switch_info)
                
                return {
                    "status": "não encontrado",
                    "detalhes": None,
                    "status_reason": switch_info["status_reason"],
                    "status_details": switch_info["status_details"],
                    "ultima_verificacao": switch_info["ultima_verificacao"]
                }
            
            host_id = host_resp["result"][0]["hostid"]
            host_status = "ativo" if host_resp["result"][0]["status"] == "0" else "inativo"
            zabbix_name = host_resp["result"][0]["name"]
            
            print(f"✅ Switch encontrado no Zabbix: {zabbix_name} (ID: {host_id}, Status: {host_status})")
            
            # Se o nome no Zabbix for diferente, mostra a correspondência
            if zabbix_name != host_name:
                print(f"ℹ️ Nome no Excel: {host_name} | Nome no Zabbix: {zabbix_name}")
            
            # Busca itens PRIMEIRO (precisa verificar uplink speed antes de processar problemas)
            print(f"🔍 Buscando itens de monitoramento para o switch: {host_name}")
            items_resp = self._call_api("item.get", {
                "hostids": host_id,
                "output": ["hostid", "name", "lastvalue", "units", "key_"],
                "sortfield": "name"
            })

            # Busca problemas (API retorna todos, filtraremos no código)
            print(f"🔍 Buscando problemas para o switch: {host_name}")
            janela_inicio = self._janela_problemas_zabbix_inicio()
            problems_resp = self._call_api("problem.get", {
                "hostids": [host_id],
                "output": "extend",
                "time_from": janela_inicio,
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": 5
            })

            problemas = problems_resp.get("result", [])
            print(f"✅ Encontrados {len(problemas)} problemas para o switch: {host_name}")

            problemas_filtrados, nomes_problemas = self._filtrar_problemas_por_estado_atual(
                problemas,
                items_resp.get("result", [])
            )

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
                status = "inativo"
            elif problemas_filtrados:
                status = "warning"
            
            print(f"📊 Status final do switch {host_name}: {status}")

            switch_info["warning_problemas"] = nomes_problemas if status == "warning" else []
            switch_info["warning_resumo"] = nomes_problemas[0] if status == "warning" and nomes_problemas else None
            if status == "inativo":
                switch_info["status_reason"] = "Host encontrado no Zabbix, mas está marcado como inativo/desabilitado."
                switch_info["status_details"] = f"Host Zabbix: {zabbix_name} | Status do host: {host_status}"
            else:
                switch_info["status_reason"] = None
                switch_info["status_details"] = None
            
            # Atualiza o switch na lista
            switch_info["status"] = status
            switch_info["ultima_verificacao"] = datetime.now().isoformat()
            
            # Se o nome no Zabbix for diferente, armazena para referência
            if zabbix_name != host_name:
                switch_info["zabbix_name"] = zabbix_name

            self._persistir_status_switch(switch_info)
            
            return {
                "status": status,
                "ultima_verificacao": switch_info["ultima_verificacao"],
                "status_reason": switch_info.get("status_reason"),
                "status_details": switch_info.get("status_details"),
                "warning_problemas": switch_info.get("warning_problemas", []),
                "warning_resumo": switch_info.get("warning_resumo"),
                "detalhes": {
                    "host_id": host_id,
                    "host_status": host_status,
                    "problemas": problemas_filtrados,
                    "itens": items
                }
            }
            
        except Exception as e:
            print(f"❌ Erro ao verificar switch {host_name}: {str(e)}")
            if 'switch_info' in locals() and switch_info:
                switch_info["status"] = "erro"
                switch_info["ultima_verificacao"] = datetime.now().isoformat()
                switch_info["status_reason"] = "Falha ao consultar o Zabbix para este switch."
                switch_info["status_details"] = str(e)
                switch_info["warning_problemas"] = []
                switch_info["warning_resumo"] = None
                self._persistir_status_switch(switch_info)

            return {
                "status": "erro",
                "detalhes": str(e),
                "status_reason": "Falha ao consultar o Zabbix para este switch.",
                "status_details": str(e),
                "ultima_verificacao": datetime.now().isoformat()
            }
    
    def verificar_todos_switches(self, max_switches=None, progress_callback=None):
        """Verifica o status de todos os switches
        
        Args:
            max_switches: Número máximo de switches a verificar (None = todos)
            progress_callback: Callback opcional chamado a cada switch concluído
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
        total_switches = len(switches_ordenados)

        for indice, switch in enumerate(switches_ordenados, start=1):
            host_name = switch["host"]
            resultado = self.verificar_switch(host_name)
            resultados[host_name] = resultado

            if callable(progress_callback):
                try:
                    progress_callback(indice, total_switches, host_name, resultado)
                except Exception as exc:
                    print(f"⚠️ Erro ao reportar progresso do switch {host_name}: {exc}")
        
        return resultados
    
    def verificar_regional(self, regional, progress_callback=None):
        """Verifica o status de todos os switches de uma regional"""
        if regional not in self.regionais:
            return {"error": f"Regional {regional} não encontrada"}
        
        resultados = {}
        switches_regional = self.regionais[regional]
        total_switches = len(switches_regional)

        for indice, switch in enumerate(switches_regional, start=1):
            host_name = switch["host"]
            resultado = self.verificar_switch(host_name)
            resultados[host_name] = resultado

            if callable(progress_callback):
                try:
                    progress_callback(indice, total_switches, host_name, resultado)
                except Exception as exc:
                    print(f"⚠️ Erro ao reportar progresso da regional {regional} para o switch {host_name}: {exc}")
        
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
                    background: linear-gradient(135deg, #012E40, #0A4A63, #0F6C8C);
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
