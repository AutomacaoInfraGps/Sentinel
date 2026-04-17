#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gerenciador de Máquinas Virtuais - Integração com Server Manager
Este módulo permite obter informações sobre máquinas virtuais, serviços e logs
de servidores Hyper-V gerenciados pelo Server Manager.

Funcionalidades:
- Obtenção de informações sobre hosts Hyper-V
- Obtenção de informações sobre máquinas virtuais
- Obtenção de informações sobre serviços em execução nas VMs
- Obtenção dos últimos logs das VMs
- Geração de relatórios em Excel
"""

import os
import sys
import json
import time
import logging
import requests
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas não instalado. Funcionalidades limitadas.")
    PANDAS_AVAILABLE = False
    pd = None
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
try:
    from urllib3.exceptions import InsecureRequestWarning
except ImportError:
    try:
        from requests.packages.urllib3.exceptions import InsecureRequestWarning
    except ImportError:
        # Fallback se nenhum funcionar
        class InsecureRequestWarning(Warning):
            pass

# Desativa avisos de certificado SSL inválido
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Importa o módulo de credenciais
try:
    from credentials import get_credentials
except ImportError:
    # Fallback para caso o módulo não esteja disponível
    def get_credentials(service, prompt_if_missing=False):
        if service == 'server_manager':
            return {
                'host': '203.0.113.20',
                'username': 'admin',
                'password': '',
                'regional': 'Regional Exemplo'
            }
        return {'username': '', 'password': ''}

# Tenta importar configurações do environment.json
try:
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

class GerenciadorVMs:
    """Classe para gerenciar máquinas virtuais via Server Manager"""
    
    def __init__(self, host=None, username=None, password=None, regional=None):
        """Inicializa o gerenciador com as credenciais do Server Manager"""
        # Primeiro tenta obter do environment.json
        env_creds = ENV_CONFIG.get('server_manager', {})
        
        # Depois tenta obter do módulo de credenciais
        creds = get_credentials('server_manager')
        
        # Usa os parâmetros fornecidos ou as credenciais das fontes disponíveis
        self.host = host or env_creds.get('host') or creds.get('host') or '203.0.113.20'
        self.username = username or env_creds.get('username') or creds.get('username') or 'admin'
        self.password = password or env_creds.get('password') or creds.get('password') or ''
        self.regional = regional or env_creds.get('regional') or creds.get('regional') or 'Regional Exemplo'
        
        # Log das configurações (sem a senha)
        print(f"🔧 Configurações do Server Manager:")
        print(f"   Host: {self.host}")
        print(f"   Usuário: {self.username}")
        print(f"   Regional: {self.regional}")
        
        # Configura a URL base
        self.base_url = f"https://{self.host}/api"
        
        # Inicializa variáveis de sessão
        self.session = None
        self.token = None
        self.last_login = None
        self.session_timeout = 900  # 15 minutos em segundos
        
        # Armazena dados das VMs
        self.vms = []
        self.hosts = []
        
    def autenticar(self):
        """Autentica no Server Manager"""
        try:
            print(f"🔑 Autenticando no Server Manager {self.host}...")
            print(f"   Usuário: {self.username}")
            
            # Cria uma nova sessão
            self.session = requests.Session()
            
            # Configura a sessão para não verificar certificados SSL
            self.session.verify = False
            
            # Configura autenticação básica
            self.session.auth = (self.username, self.password)
            
            # Testa a autenticação com uma requisição simples
            test_url = f"https://{self.host}/api/servers"
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
                    print(f"✅ Autenticação bem-sucedida no Server Manager {self.host}")
                    return True
                else:
                    print(f"❌ Falha na autenticação: {response.status_code}")
                    print(f"   Resposta: {response.text[:200]}")
                    
                    # Tenta método alternativo se o primeiro falhar
                    print("🔄 Tentando método alternativo de autenticação...")
                    
                    # URL para login via API
                    login_url = f"https://{self.host}/api/auth/login"
                    print(f"   URL de login: {login_url}")
                    
                    # Dados de login
                    login_data = {
                        "username": self.username,
                        "password": self.password
                    }
                    
                    # Faz a requisição de login
                    login_response = self.session.post(login_url, json=login_data, timeout=10)
                    
                    if login_response.status_code == 200:
                        try:
                            token_data = login_response.json()
                            if "token" in token_data:
                                self.token = token_data["token"]
                                self.session.headers.update({
                                    "Authorization": f"Bearer {self.token}"
                                })
                                self.last_login = time.time()
                                print(f"✅ Autenticação alternativa bem-sucedida no Server Manager {self.host}")
                                return True
                        except Exception as e:
                            print(f"Erro em {__file__}: {e}")
                    
                    print(f"❌ Falha na autenticação alternativa")
                    print(f"   Status: {login_response.status_code}")
                    print(f"   Resposta: {login_response.text[:200]}")
                    return False
            except requests.exceptions.Timeout:
                print(f"❌ Timeout ao conectar ao Server Manager: {test_url}")
                print("   Verifique se o host está correto e se o Server Manager está acessível")
                return False
            except requests.exceptions.ConnectionError as e:
                print(f"❌ Erro de conexão com o Server Manager: {str(e)}")
                print("   Verifique se o host está correto e se o Server Manager está acessível")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao autenticar no Server Manager: {str(e)}")
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
    
    def obter_hosts(self):
        """Obtém informações sobre os hosts Hyper-V"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            print("🔍 Obtendo hosts Hyper-V...")
            
            # Endpoint para obter hosts
            url = f"https://{self.host}/api/servers"
            
            # Adiciona cabeçalhos necessários
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            try:
                # Faz a requisição com timeout
                response = self.session.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    hosts = data.get("servers", [])
                    print(f"✅ Hosts obtidos com sucesso: {len(hosts)} hosts encontrados")
                    
                    # Filtra apenas hosts Hyper-V
                    hyperv_hosts = []
                    for host in hosts:
                        if "Hyper-V" in host.get("roles", []):
                            # Adiciona a regional ao host
                            host["regional"] = self.regional
                            hyperv_hosts.append(host)
                    
                    self.hosts = hyperv_hosts
                    print(f"✅ Hosts Hyper-V: {len(hyperv_hosts)} hosts encontrados")
                    
                    return {"success": True, "hosts": hyperv_hosts}
                else:
                    print(f"❌ Falha ao obter hosts: {response.status_code} - {response.text}")
                    return {"success": False, "message": f"Erro {response.status_code}: {response.text}"}
            except requests.exceptions.RequestException as e:
                print(f"❌ Erro na requisição de hosts: {str(e)}")
                return {"success": False, "message": f"Erro de conexão: {str(e)}"}
                
        except Exception as e:
            print(f"❌ Erro ao obter hosts: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_vms(self, host_id=None):
        """Obtém informações sobre as máquinas virtuais"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            # Se não tiver hosts, obtém primeiro
            if not self.hosts:
                hosts_result = self.obter_hosts()
                if not hosts_result["success"]:
                    return hosts_result
            
            # Se um host específico foi solicitado, filtra apenas ele
            hosts_to_query = []
            if host_id:
                for host in self.hosts:
                    if host.get("id") == host_id:
                        hosts_to_query.append(host)
                        break
            else:
                hosts_to_query = self.hosts
            
            if not hosts_to_query:
                return {"success": False, "message": "Host não encontrado"}
            
            all_vms = []
            
            for host in hosts_to_query:
                host_id = host.get("id")
                host_name = host.get("name")
                print(f"🔍 Obtendo VMs do host {host_name}...")
                
                # Endpoint para obter VMs
                url = f"https://{self.host}/api/servers/{host_id}/virtualmachines"
                
                # Adiciona cabeçalhos necessários
                headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
                
                try:
                    # Faz a requisição com timeout
                    response = self.session.get(url, headers=headers, timeout=15)
                    
                    if response.status_code == 200:
                        data = response.json()
                        vms = data.get("virtualmachines", [])
                        print(f"✅ VMs obtidas com sucesso: {len(vms)} VMs encontradas no host {host_name}")
                        
                        # Adiciona informações do host às VMs
                        for vm in vms:
                            vm["host_id"] = host_id
                            vm["host_name"] = host_name
                            vm["regional"] = host.get("regional", self.regional)
                            all_vms.append(vm)
                    else:
                        print(f"❌ Falha ao obter VMs do host {host_name}: {response.status_code} - {response.text}")
                except requests.exceptions.RequestException as e:
                    print(f"❌ Erro na requisição de VMs do host {host_name}: {str(e)}")
            
            # Atualiza a lista de VMs
            self.vms = all_vms
            
            return {"success": True, "vms": all_vms}
                
        except Exception as e:
            print(f"❌ Erro ao obter VMs: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_servicos(self, vm_id):
        """Obtém informações sobre os serviços de uma VM"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            # Encontra a VM na lista
            vm = None
            host_id = None
            for v in self.vms:
                if v.get("id") == vm_id:
                    vm = v
                    host_id = v.get("host_id")
                    break
            
            if not vm or not host_id:
                return {"success": False, "message": "VM não encontrada"}
            
            print(f"🔍 Obtendo serviços da VM {vm.get('name')}...")
            
            # Endpoint para obter serviços
            url = f"https://{self.host}/api/servers/{host_id}/virtualmachines/{vm_id}/services"
            
            # Adiciona cabeçalhos necessários
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            try:
                # Faz a requisição com timeout
                response = self.session.get(url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    services = data.get("services", [])
                    print(f"✅ Serviços obtidos com sucesso: {len(services)} serviços encontrados na VM {vm.get('name')}")
                    
                    return {"success": True, "services": services, "vm": vm}
                else:
                    print(f"❌ Falha ao obter serviços da VM {vm.get('name')}: {response.status_code} - {response.text}")
                    return {"success": False, "message": f"Erro {response.status_code}: {response.text}"}
            except requests.exceptions.RequestException as e:
                print(f"❌ Erro na requisição de serviços da VM {vm.get('name')}: {str(e)}")
                return {"success": False, "message": f"Erro de conexão: {str(e)}"}
                
        except Exception as e:
            print(f"❌ Erro ao obter serviços: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_logs(self, vm_id, max_logs=10):
        """Obtém os últimos logs de uma VM"""
        try:
            if not self.verificar_sessao():
                return {"success": False, "message": "Falha na autenticação"}
                
            # Encontra a VM na lista
            vm = None
            host_id = None
            for v in self.vms:
                if v.get("id") == vm_id:
                    vm = v
                    host_id = v.get("host_id")
                    break
            
            if not vm or not host_id:
                return {"success": False, "message": "VM não encontrada"}
            
            print(f"🔍 Obtendo logs da VM {vm.get('name')}...")
            
            # Endpoint para obter logs
            url = f"https://{self.host}/api/servers/{host_id}/virtualmachines/{vm_id}/events"
            
            # Adiciona cabeçalhos necessários
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            # Parâmetros para limitar o número de logs
            params = {
                "limit": max_logs
            }
            
            try:
                # Faz a requisição com timeout
                response = self.session.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    events = data.get("events", [])
                    print(f"✅ Logs obtidos com sucesso: {len(events)} logs encontrados na VM {vm.get('name')}")
                    
                    return {"success": True, "events": events, "vm": vm}
                else:
                    print(f"❌ Falha ao obter logs da VM {vm.get('name')}: {response.status_code} - {response.text}")
                    return {"success": False, "message": f"Erro {response.status_code}: {response.text}"}
            except requests.exceptions.RequestException as e:
                print(f"❌ Erro na requisição de logs da VM {vm.get('name')}: {str(e)}")
                return {"success": False, "message": f"Erro de conexão: {str(e)}"}
                
        except Exception as e:
            print(f"❌ Erro ao obter logs: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def obter_vms_por_regional(self, regional=None):
        """Obtém as VMs de uma regional específica ou de todas as regionais"""
        try:
            # Se não tiver VMs, obtém primeiro
            if not self.vms:
                vms_result = self.obter_vms()
                if not vms_result["success"]:
                    return vms_result
            
            # Se uma regional específica foi solicitada, filtra apenas ela
            if regional:
                filtered_vms = [vm for vm in self.vms if vm.get("regional", "").lower() == regional.lower()]
                return {"success": True, "vms": filtered_vms, "regional": regional}
            else:
                # Agrupa as VMs por regional
                vms_by_regional = {}
                for vm in self.vms:
                    reg = vm.get("regional", "Desconhecida")
                    if reg not in vms_by_regional:
                        vms_by_regional[reg] = []
                    vms_by_regional[reg].append(vm)
                
                return {"success": True, "vms_by_regional": vms_by_regional}
                
        except Exception as e:
            print(f"❌ Erro ao obter VMs por regional: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def gerar_relatorio_vms(self, output_file=None):
        """Gera um relatório com informações das VMs"""
        try:
            # Se não tiver VMs, obtém primeiro
            if not self.vms:
                vms_result = self.obter_vms()
                if not vms_result["success"]:
                    return vms_result
            
            # Prepara os dados para o relatório
            report_data = []
            for vm in self.vms:
                vm_data = {
                    "Nome": vm.get("name", ""),
                    "Status": vm.get("status", ""),
                    "Host": vm.get("host_name", ""),
                    "Regional": vm.get("regional", ""),
                    "CPUs": vm.get("processors", 0),
                    "Memória (GB)": round(vm.get("memory", 0) / 1024, 2),
                    "Uptime": vm.get("uptime", ""),
                    "Sistema Operacional": vm.get("operatingSystem", ""),
                    "IP": vm.get("ipAddresses", [""])[0] if vm.get("ipAddresses") else ""
                }
                report_data.append(vm_data)
            
            # Cria um DataFrame com os dados
            df = pd.DataFrame(report_data)
            
            # Define o nome do arquivo de saída
            if not output_file:
                from utils_paths import get_file_path
                output_dir = get_file_path("output")
                output_dir.mkdir(exist_ok=True)
                output_file = output_dir / f"relatorio_vms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            # Salva o relatório
            df.to_excel(output_file, index=False)
            
            print(f"✅ Relatório gerado com sucesso: {output_file}")
            
            return {"success": True, "file": str(output_file), "data": report_data}
                
        except Exception as e:
            print(f"❌ Erro ao gerar relatório: {str(e)}")
            return {"success": False, "message": str(e)}

# Função para testar o módulo
def teste_modulo():
    """Função para testar o módulo"""
    gerenciador = GerenciadorVMs()
    
    # Testa autenticação
    if not gerenciador.autenticar():
        print("❌ Falha na autenticação. Verifique as credenciais.")
        return
    
    # Obtém hosts
    hosts_result = gerenciador.obter_hosts()
    if not hosts_result["success"]:
        print(f"❌ Falha ao obter hosts: {hosts_result['message']}")
        return
    
    # Obtém VMs
    vms_result = gerenciador.obter_vms()
    if not vms_result["success"]:
        print(f"❌ Falha ao obter VMs: {vms_result['message']}")
        return
    
    # Exibe informações das VMs
    vms = vms_result["vms"]
    print(f"\n=== Máquinas Virtuais ({len(vms)}) ===")
    for i, vm in enumerate(vms[:5], 1):  # Mostra apenas as 5 primeiras
        print(f"{i}. {vm.get('name')} - Status: {vm.get('status')} - Host: {vm.get('host_name')}")
    
    if len(vms) > 5:
        print(f"... e mais {len(vms) - 5} VMs")
    
    # Se houver VMs, obtém serviços e logs da primeira
    if vms:
        vm = vms[0]
        vm_id = vm.get("id")
        
        # Obtém serviços
        services_result = gerenciador.obter_servicos(vm_id)
        if services_result["success"]:
            services = services_result["services"]
            print(f"\n=== Serviços da VM {vm.get('name')} ({len(services)}) ===")
            for i, service in enumerate(services[:5], 1):  # Mostra apenas os 5 primeiros
                print(f"{i}. {service.get('displayName')} - Status: {service.get('status')}")
            
            if len(services) > 5:
                print(f"... e mais {len(services) - 5} serviços")
        
        # Obtém logs
        logs_result = gerenciador.obter_logs(vm_id, 5)
        if logs_result["success"]:
            events = logs_result["events"]
            print(f"\n=== Logs da VM {vm.get('name')} ({len(events)}) ===")
            for i, event in enumerate(events, 1):
                print(f"{i}. {event.get('timeCreated')}: {event.get('message')}")
    
    # Gera relatório
    report_result = gerenciador.gerar_relatorio_vms()
    if report_result["success"]:
        print(f"\n✅ Relatório gerado: {report_result['file']}")

class GerenciadorVMsLocal:
    """Classe para gerenciar VMs locais (arquivo JSON) seguindo padrão dos servidores"""
    
    def __init__(self, arquivo_vms="data/vms.json"):
        """Inicializa o gerenciador com o arquivo de VMs"""
        self.arquivo_vms = Path(arquivo_vms)
        self.vms = self._carregar_vms()
    
    def _carregar_vms(self):
        """Carrega VMs do arquivo JSON"""
        try:
            if self.arquivo_vms.exists():
                with open(self.arquivo_vms, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return []
        except Exception as e:
            print(f"❌ Erro ao carregar VMs: {e}")
            return []
    
    def _salvar_vms(self):
        """Salva VMs no arquivo JSON"""
        try:
            # Cria diretório se não existir
            self.arquivo_vms.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.arquivo_vms, 'w', encoding='utf-8') as f:
                json.dump(self.vms, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"❌ Erro ao salvar VMs: {e}")
            return False
    
    def listar_vms(self):
        """Lista todas as VMs cadastradas"""
        print(f"\n📱 VMs Cadastradas ({len(self.vms)}):")
        print("=" * 50)
        
        if not self.vms:
            print("Nenhuma VM cadastrada.")
            return
        
        for i, vm in enumerate(self.vms, 1):
            print(f"{i}. {vm['name']} ({vm['ip']})")
            print(f"   Regional: {vm.get('regional', 'N/A')}")
            print(f"   Usuário: {vm.get('username', 'N/A')}")
            print(f"   Status: {vm.get('status', 'Unknown')}")
            print(f"   Descrição: {vm.get('description', 'N/A')}")
            print()
    
    def adicionar_vm(self, name, ip, username, password, regional, description=""):
        """Adiciona uma nova VM seguindo o padrão dos servidores"""
        
        # Valida se a regional segue o padrão RG_*
        if not regional.startswith('RG_'):
            print("⚠️ Aviso: A regional deve seguir o padrão 'RG_NOME' (ex: RG_PARANA, RG_SAO_PAULO)")
            regional = f"RG_{regional.upper().replace(' ', '_')}"
            print(f"   Ajustado para: {regional}")
        
        # Gera ID único
        vm_id = f"vm-{int(datetime.now().timestamp())}"
        
        nova_vm = {
            "id": vm_id,
            "name": name,
            "ip": ip,
            "username": username,
            "password": password,
            "regional": regional,
            "description": description,
            "status": "Unknown",
            "last_check": None,
            "grupo": "regionais",
            "tipo": "vm"
        }
        
        self.vms.append(nova_vm)
        
        if self._salvar_vms():
            print(f"✅ VM '{name}' adicionada com sucesso!")
            print(f"   ID: {vm_id}")
            print(f"   Regional: {regional}")
            return True
        else:
            print(f"❌ Erro ao salvar VM '{name}'")
            return False
    
    def remover_vm(self, vm_id_ou_nome):
        """Remove uma VM pelo ID ou nome"""
        vm_encontrada = None
        indice = -1
        
        for i, vm in enumerate(self.vms):
            if vm['id'] == vm_id_ou_nome or vm['name'] == vm_id_ou_nome:
                vm_encontrada = vm
                indice = i
                break
        
        if vm_encontrada:
            self.vms.pop(indice)
            if self._salvar_vms():
                print(f"✅ VM '{vm_encontrada['name']}' removida com sucesso!")
                return True
            else:
                print(f"❌ Erro ao salvar após remoção da VM")
                return False
        else:
            print(f"❌ VM '{vm_id_ou_nome}' não encontrada")
            return False
    
    def atualizar_regional_vm(self, vm_id_ou_nome, nova_regional):
        """Atualiza a regional de uma VM"""
        
        # Valida se a regional segue o padrão RG_*
        if not nova_regional.startswith('RG_'):
            print("⚠️ Aviso: A regional deve seguir o padrão 'RG_NOME' (ex: RG_PARANA, RG_SAO_PAULO)")
            nova_regional = f"RG_{nova_regional.upper().replace(' ', '_')}"
            print(f"   Ajustado para: {nova_regional}")
        
        for vm in self.vms:
            if vm['id'] == vm_id_ou_nome or vm['name'] == vm_id_ou_nome:
                regional_antiga = vm.get('regional', 'N/A')
                vm['regional'] = nova_regional
                
                if self._salvar_vms():
                    print(f"✅ Regional da VM '{vm['name']}' atualizada!")
                    print(f"   De: {regional_antiga}")
                    print(f"   Para: {nova_regional}")
                    return True
                else:
                    print(f"❌ Erro ao salvar alteração da regional")
                    return False
        
        print(f"❌ VM '{vm_id_ou_nome}' não encontrada")
        return False

def gerenciar_vms_cli():
    """Interface de linha de comando para gerenciar VMs"""
    gerenciador = GerenciadorVMsLocal()
    
    while True:
        print("\n" + "="*50)
        print("🖥️  GERENCIADOR DE VMs")
        print("="*50)
        print("1. Listar VMs")
        print("2. Adicionar VM")
        print("3. Remover VM")
        print("4. Atualizar Regional")
        print("5. Sair")
        print("="*50)
        
        opcao = input("Escolha uma opção: ").strip()
        
        if opcao == "1":
            gerenciador.listar_vms()
        
        elif opcao == "2":
            print("\n📝 Adicionar Nova VM:")
            name = input("Nome da VM: ").strip()
            ip = input("IP da VM: ").strip()
            username = input("Usuário: ").strip()
            password = input("Senha: ").strip()
            regional = input("Regional (ex: PARANA, SAO_PAULO): ").strip()
            description = input("Descrição (opcional): ").strip()
            
            if name and ip and username and password and regional:
                gerenciador.adicionar_vm(name, ip, username, password, regional, description)
            else:
                print("❌ Todos os campos obrigatórios devem ser preenchidos!")
        
        elif opcao == "3":
            gerenciador.listar_vms()
            if gerenciador.vms:
                vm_id = input("\nDigite o ID ou nome da VM para remover: ").strip()
                if vm_id:
                    gerenciador.remover_vm(vm_id)
        
        elif opcao == "4":
            gerenciador.listar_vms()
            if gerenciador.vms:
                vm_id = input("\nDigite o ID ou nome da VM: ").strip()
                nova_regional = input("Nova regional (ex: PARANA, SAO_PAULO): ").strip()
                if vm_id and nova_regional:
                    gerenciador.atualizar_regional_vm(vm_id, nova_regional)
        
        elif opcao == "5":
            print("👋 Saindo...")
            break
        
        else:
            print("❌ Opção inválida!")

# Executa o teste se o script for executado diretamente
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        gerenciar_vms_cli()
    else:
        teste_modulo()