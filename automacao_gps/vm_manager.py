"""
Módulo para gerenciar máquinas virtuais e obter informações detalhadas
usando PowerShell remoto.
"""
import os
import json
import subprocess
import tempfile
from datetime import datetime

# Caminho raiz do projeto
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

def verificar_vm_online(ip):
    """Verifica se uma VM está online usando ping"""
    try:
        # Tenta fazer ping na VM
        ping_result = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", ip],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Verifica se o ping foi bem-sucedido (suporta respostas em inglês e português)
        if "Reply from" in ping_result.stdout or "Resposta de" in ping_result.stdout:
            print(f"VM {ip} está online!")
            return True
        else:
            print(f"VM {ip} não respondeu ao ping. Saída: {ping_result.stdout}")
            return False
    except Exception as ping_error:
        print(f"Erro ao verificar conectividade: {str(ping_error)}")
        return False

def obter_servicos_vm(ip, username, password):
    """Obtém os serviços de uma VM usando PowerShell remoto"""
    try:
        # Verifica se a VM está online
        if not verificar_vm_online(ip):
            return {
                "success": False, 
                "message": "VM não está acessível no momento",
                "services": []
            }
        
        # Cria um arquivo temporário para o script PowerShell
        with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w') as ps_file:
            ps_script = f'''
            $secpasswd = ConvertTo-SecureString "{password}" -AsPlainText -Force
            $cred = New-Object System.Management.Automation.PSCredential ("{username}", $secpasswd)
            
            try {{
                $services = Invoke-Command -ComputerName {ip} -Credential $cred -ScriptBlock {{
                    Get-Service | Select-Object DisplayName, Name, @{{
                        Name = 'Status';
                        Expression = {{$_.Status.ToString()}}
                    }}, @{{
                        Name = 'StartType';
                        Expression = {{
                            try {{
                                $svc = Get-WmiObject -Class Win32_Service -Filter "Name='$($_.Name)'"
                                switch($svc.StartMode) {{
                                    "Auto" {{ "Automático" }}
                                    "Manual" {{ "Manual" }}
                                    "Disabled" {{ "Desabilitado" }}
                                    default {{ $svc.StartMode }}
                                }}
                            }} catch {{
                                "Desconhecido"
                            }}
                        }}
                    }} | 
                    Sort-Object Status, DisplayName | 
                    ConvertTo-Json -Depth 1
                }} -ErrorAction Stop
                
                $services
            }} catch {{
                "{{ ""error"": ""$($_.Exception.Message)"" }}"
            }}
            '''
            ps_file.write(ps_script)
            ps_script_path = ps_file.name
        
        # Executa o script PowerShell
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_script_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Remove o arquivo temporário
        os.unlink(ps_script_path)
        
        # Verifica se houve erro
        if "error" in result.stdout:
            error_data = json.loads(result.stdout)
            return {
                "success": False,
                "message": f"Erro ao obter serviços: {error_data.get('error', 'Erro desconhecido')}",
                "services": []
            }
        
        # Processa os resultados
        try:
            services_data = json.loads(result.stdout)
            
            # Converte o formato dos serviços
            services = []
            for service in services_data:
                services.append({
                    "displayName": service.get("DisplayName", ""),
                    "name": service.get("Name", ""),
                    "status": str(service.get("Status", "")),
                    "startMode": str(service.get("StartType", "")),
                    "account": "N/A"  # Não disponível nesta consulta
                })
            
            return {
                "success": True,
                "message": "Serviços obtidos com sucesso",
                "services": services
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "message": "Erro ao processar resposta do servidor",
                "services": []
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Erro ao obter serviços: {str(e)}",
            "services": []
        }

def obter_logs_vm(ip, username, password):
    """Obtém os logs de uma VM usando PowerShell remoto"""
    try:
        # Verifica se a VM está online
        if not verificar_vm_online(ip):
            return {
                "success": False, 
                "message": "VM não está acessível no momento",
                "events": []
            }
        
        # Cria um arquivo temporário para o script PowerShell
        with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w') as ps_file:
            ps_script = f'''
            $secpasswd = ConvertTo-SecureString "{password}" -AsPlainText -Force
            $cred = New-Object System.Management.Automation.PSCredential ("{username}", $secpasswd)
            
            try {{
                $events = Invoke-Command -ComputerName {ip} -Credential $cred -ScriptBlock {{
                    Get-EventLog -LogName System -Newest 10 | 
                    Select-Object EventID, EntryType, Source, Message, @{{
                        Name = 'TimeGenerated';
                        Expression = {{$_.TimeGenerated.ToString("yyyy-MM-ddTHH:mm:ss")}}
                    }} | 
                    ConvertTo-Json -Depth 1
                }} -ErrorAction Stop
                
                $events
            }} catch {{
                "{{ ""error"": ""$($_.Exception.Message)"" }}"
            }}
            '''
            ps_file.write(ps_script)
            ps_script_path = ps_file.name
        
        # Executa o script PowerShell
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_script_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Remove o arquivo temporário
        os.unlink(ps_script_path)
        
        # Verifica se houve erro
        if "error" in result.stdout:
            error_data = json.loads(result.stdout)
            return {
                "success": False,
                "message": f"Erro ao obter logs: {error_data.get('error', 'Erro desconhecido')}",
                "events": []
            }
        
        # Processa os resultados
        try:
            events_data = json.loads(result.stdout)
            
            # Converte o formato dos eventos
            events = []
            for event in events_data:
                # Processa a data para um formato consistente
                try:
                    time_generated = event.get("TimeGenerated", "")
                    # Converte para um formato de data consistente
                    if time_generated:
                        # O PowerShell retorna datas em um formato específico
                        # Vamos tentar extrair a data e formatá-la corretamente
                        formatted_date = datetime.strptime(
                            time_generated.split(".")[0],  # Remove milissegundos se houver
                            "%Y-%m-%dT%H:%M:%S"
                        ).strftime("%d/%m/%Y %H:%M:%S")
                    else:
                        formatted_date = "N/A"
                except Exception as date_error:
                    print(f"Erro ao formatar data: {str(date_error)}")
                    formatted_date = "N/A"
                
                # Limpa a mensagem (pega apenas a primeira linha e limita o tamanho)
                message = event.get("Message", "")
                if message:
                    # Pega apenas a primeira linha
                    message = message.split('\r\n')[0]
                    # Limita o tamanho da mensagem
                    if len(message) > 100:
                        message = message[:97] + "..."
                
                events.append({
                    "id": str(event.get("EventID", "")),
                    "level": str(event.get("EntryType", "")),
                    "source": event.get("Source", ""),
                    "message": message,
                    "timeCreated": formatted_date
                })
            
            return {
                "success": True,
                "message": "Logs obtidos com sucesso",
                "events": events
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "message": "Erro ao processar resposta do servidor",
                "events": []
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Erro ao obter logs: {str(e)}",
            "events": []
        }

def obter_detalhes_vm(ip, username, password):
    """Obtém detalhes de uma VM usando PowerShell remoto"""
    try:
        # Verifica se a VM está online
        if not verificar_vm_online(ip):
            return {
                "success": False, 
                "message": "VM não está acessível no momento"
            }
        
        # Cria um arquivo temporário para o script PowerShell
        with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w') as ps_file:
            ps_script = f'''
            $secpasswd = ConvertTo-SecureString "{password}" -AsPlainText -Force
            $cred = New-Object System.Management.Automation.PSCredential ("{username}", $secpasswd)
            
            try {{
                $info = Invoke-Command -ComputerName {ip} -Credential $cred -ScriptBlock {{
                    $os = Get-CimInstance Win32_OperatingSystem
                    $cs = Get-CimInstance Win32_ComputerSystem
                    $proc = Get-CimInstance Win32_Processor
                    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
                    
                    $diskInfo = @()
                    foreach ($d in $disk) {{
                        $freeGB = [math]::Round($d.FreeSpace / 1GB, 2)
                        $totalGB = [math]::Round($d.Size / 1GB, 2)
                        $percentFree = [math]::Round(($d.FreeSpace / $d.Size) * 100, 2)
                        
                        $diskInfo += [PSCustomObject]@{{
                            Drive = $d.DeviceID
                            FreeGB = $freeGB
                            TotalGB = $totalGB
                            PercentFree = $percentFree
                        }}
                    }}
                    
                    $info = [PSCustomObject]@{{
                        ComputerName = $env:COMPUTERNAME
                        OperatingSystem = $os.Caption
                        OSVersion = $os.Version
                        Manufacturer = $cs.Manufacturer
                        Model = $cs.Model
                        Processors = $proc.Count
                        ProcessorName = $proc[0].Name
                        Memory = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
                        LastBoot = $os.LastBootUpTime
                        Uptime = (Get-Date) - $os.LastBootUpTime
                        Disks = $diskInfo
                    }}
                    
                    $info | ConvertTo-Json -Depth 3
                }} -ErrorAction Stop
                
                $info
            }} catch {{
                "{{ ""error"": ""$($_.Exception.Message)"" }}"
            }}
            '''
            ps_file.write(ps_script)
            ps_script_path = ps_file.name
        
        # Executa o script PowerShell
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_script_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Remove o arquivo temporário
        os.unlink(ps_script_path)
        
        # Verifica se houve erro
        if "error" in result.stdout:
            error_data = json.loads(result.stdout)
            return {
                "success": False,
                "message": f"Erro ao obter detalhes: {error_data.get('error', 'Erro desconhecido')}"
            }
        
        # Processa os resultados
        try:
            vm_info = json.loads(result.stdout)
            
            # Formata os detalhes da VM
            details = {
                "computerName": vm_info.get("ComputerName", ""),
                "operatingSystem": vm_info.get("OperatingSystem", ""),
                "osVersion": vm_info.get("OSVersion", ""),
                "manufacturer": vm_info.get("Manufacturer", ""),
                "model": vm_info.get("Model", ""),
                "processors": vm_info.get("Processors", 0),
                "processorName": vm_info.get("ProcessorName", ""),
                "memory": vm_info.get("Memory", 0),
                "lastBoot": vm_info.get("LastBoot", ""),
                "uptime": str(vm_info.get("Uptime", "")),
                "disks": []
            }
            
            # Adiciona informações de disco
            for disk in vm_info.get("Disks", []):
                details["disks"].append({
                    "drive": disk.get("Drive", ""),
                    "freeGB": disk.get("FreeGB", 0),
                    "totalGB": disk.get("TotalGB", 0),
                    "percentFree": disk.get("PercentFree", 0)
                })
            
            return {
                "success": True,
                "message": "Detalhes obtidos com sucesso",
                "details": details
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "message": "Erro ao processar resposta do servidor"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Erro ao obter detalhes: {str(e)}"
        }



def gerar_relatorio_completo(ip, username, password):
    """Gera um relatório completo da VM no estilo Server Manager"""
    try:
        # Verifica se a VM está online
        if not verificar_vm_online(ip):
            return {
                "success": False, 
                "message": "VM não está acessível no momento"
            }
        
        # Cria um arquivo temporário para o script PowerShell
        with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w') as ps_file:
            ps_script = f'''
            # === CONFIGURAÇÕES INICIAIS ===
            $servidor = "{ip}"
            $secpasswd = ConvertTo-SecureString "{password}" -AsPlainText -Force
            $cred = New-Object System.Management.Automation.PSCredential ("{username}", $secpasswd)
            $data = Get-Date -Format "dd/MM/yyyy HH:mm:ss"
            
            # === COLETA DE DADOS ===
            
            # 1. ROLES E FEATURES INSTALADOS
            try {{
                $features = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {{
                    Get-WindowsFeature | Where-Object {{ $_.Installed }} |
                    Select-Object DisplayName, Name, @{{
                        Name = 'InstallState';
                        Expression = {{$_.InstallState.ToString()}}
                    }}
                }} -ErrorAction Stop
                $featuresJson = $features | ConvertTo-Json -Depth 1
            }} catch {{
                $featuresJson = "[]"
            }}
            
            # 2. SERVIÇOS RELACIONADOS A ROLES
            try {{
                $servicos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {{
                    Get-Service | Where-Object {{
                        $_.Name -match "dns|dhcp|ntds|file|netlogon|w32time"
                    }} | Select-Object Name, DisplayName, @{{
                        Name = 'Status';
                        Expression = {{$_.Status.ToString()}}
                    }}, @{{
                        Name = 'StartType';
                        Expression = {{
                            try {{
                                $svc = Get-WmiObject -Class Win32_Service -Filter "Name='$($_.Name)'"
                                $svc.StartMode
                            }} catch {{
                                "Unknown"
                            }}
                        }}
                    }}
                }} -ErrorAction Stop
                $servicosJson = $servicos | ConvertTo-Json -Depth 1
            }} catch {{
                $servicosJson = "[]"
            }}
            
            # 3. EVENTOS DE ERRO RECENTES
            try {{
                $eventos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {{
                    Get-EventLog -LogName System -EntryType Error -Newest 10 |
                    Select-Object @{{
                        Name = 'TimeGenerated';
                        Expression = {{$_.TimeGenerated.ToString("dd/MM/yyyy HH:mm:ss")}}
                    }}, Source, EventID, @{{
                        Name = 'Message';
                        Expression = {{$_.Message -replace '[\r\n]', ' ' -replace '"', "'"}}
                    }}
                }} -ErrorAction Stop
                $eventosJson = $eventos | ConvertTo-Json -Depth 1
            }} catch {{
                $eventosJson = "[]"
            }}
            
            # 4. USO DE CPU/MEMÓRIA DOS PROCESSOS
            try {{
                $processos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {{
                    Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name, @{{
                        Name = 'CPU';
                        Expression = {{[math]::Round($_.CPU, 2)}}
                    }}, @{{
                        Name = 'WorkingSet';
                        Expression = {{[math]::Round($_.WorkingSet / 1MB, 2)}}
                    }}
                }} -ErrorAction Stop
                $processosJson = $processos | ConvertTo-Json -Depth 1
            }} catch {{
                $processosJson = "[]"
            }}
            
            # 5. RESULTADOS BPA (Active Directory)
            try {{
                $bpa = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {{
                    try {{
                        Invoke-BpaModel -ModelId Microsoft/Windows/DirectoryServices -ErrorAction Stop | Out-Null
                        Get-BpaResult -ModelId Microsoft/Windows/DirectoryServices |
                        Where-Object {{ $_.Severity -ne "Information" }} |
                        Select-Object Severity, Title, @{{
                            Name = 'Compliance';
                            Expression = {{$_.Compliance.ToString()}}
                        }}, Problem, Impact, Resolution
                    }} catch {{
                        return "BPA não disponível ou erro ao executar."
                    }}
                }} -ErrorAction Stop
                
                if ($bpa -is [string]) {{
                    $bpaJson = "{{ ""message"": ""$bpa"" }}"
                }} else {{
                    $bpaJson = $bpa | ConvertTo-Json -Depth 2
                }}
            }} catch {{
                $bpaJson = "{{ ""message"": ""Erro ao executar BPA"" }}"
            }}
            
            # 6. INFORMAÇÕES DO SISTEMA
            try {{
                $sistema = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {{
                    $os = Get-CimInstance Win32_OperatingSystem
                    $cs = Get-CimInstance Win32_ComputerSystem
                    $proc = Get-CimInstance Win32_Processor
                    
                    # Informações de disco
                    $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
                    $diskInfo = @()
                    foreach ($d in $disks) {{
                        $freeGB = [math]::Round($d.FreeSpace / 1GB, 2)
                        $totalGB = [math]::Round($d.Size / 1GB, 2)
                        $percentFree = [math]::Round(($d.FreeSpace / $d.Size) * 100, 2)
                        
                        $diskInfo += [PSCustomObject]@{{
                            Drive = $d.DeviceID
                            FreeGB = $freeGB
                            TotalGB = $totalGB
                            PercentFree = $percentFree
                        }}
                    }}
                    
                    # Informações do sistema
                    $info = [PSCustomObject]@{{
                        ComputerName = $env:COMPUTERNAME
                        OperatingSystem = $os.Caption
                        OSVersion = $os.Version
                        Manufacturer = $cs.Manufacturer
                        Model = $cs.Model
                        Processors = $proc.Count
                        ProcessorName = $proc[0].Name
                        Memory = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
                        LastBoot = $os.LastBootUpTime.ToString("dd/MM/yyyy HH:mm:ss")
                        Uptime = (New-TimeSpan -Start $os.LastBootUpTime -End (Get-Date)).ToString()
                        Disks = $diskInfo
                    }}
                    
                    $info | ConvertTo-Json -Depth 3
                }} -ErrorAction Stop
                # Converte explicitamente para JSON
                $sistemaJson = $sistema | ConvertTo-Json -Depth 3
            }} catch {{
                $sistemaJson = "{{ ""error"": ""$($_.Exception.Message)"" }}"
            }}
            
            # === SAÍDA DOS RESULTADOS ===
            try {{
                $resultado = @{{
                    Data = $data
                    Servidor = $servidor
                    Sistema = $sistemaJson
                    Features = $featuresJson
                    Servicos = $servicosJson
                    Eventos = $eventosJson
                    Processos = $processosJson
                    BPA = $bpaJson
                }} | ConvertTo-Json -Depth 6 -Compress
                
                Write-Output $resultado
            }} catch {{
                # Garante que sempre retornamos um JSON válido, mesmo em caso de erro
                $errorJson = @{{
                    success = $false
                    message = "Erro ao gerar relatório: $($_.Exception.Message)"
                    error = $_.Exception.Message
                    errorType = $_.Exception.GetType().Name
                    stackTrace = $_.ScriptStackTrace
                }} | ConvertTo-Json -Compress
                
                Write-Output $errorJson
            }}
            '''
            ps_file.write(ps_script)
            ps_script_path = ps_file.name
        
        # Executa o script PowerShell
        print(f"Executando script PowerShell para {ip}...")
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_script_path],
                capture_output=True,
                text=True,
                timeout=180  # Aumenta o timeout para 180 segundos
            )
            print(f"Script PowerShell concluído. Código de saída: {result.returncode}")
            if result.returncode != 0:
                print(f"ERRO no script PowerShell: {result.stderr}")
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT ao executar script PowerShell para {ip}")
            return {
                "success": False,
                "message": "Tempo limite excedido ao executar o script PowerShell"
            }
        except Exception as e:
            print(f"ERRO ao executar script PowerShell: {str(e)}")
            return {
                "success": False,
                "message": f"Erro ao executar script PowerShell: {str(e)}"
            }
        
        # Remove o arquivo temporário
        os.unlink(ps_script_path)
        
        # Processa os resultados
        try:
            # Adiciona informações de depuração
            print(f"Saída do PowerShell: {result.stdout[:500]}...")
            
            # Verifica se a saída está vazia
            if not result.stdout.strip():
                print("ERRO: Saída do PowerShell está vazia")
                print(f"Erro do PowerShell: {result.stderr}")
                return {
                    "success": False,
                    "message": "O script PowerShell não retornou dados",
                    "stderr": result.stderr
                }
            
            # Tenta limpar a saída para garantir que é um JSON válido
            output_lines = result.stdout.strip().split('\n')
            json_output = output_lines[-1]  # Pega a última linha, que deve ser o JSON
            
            try:
                relatorio = json.loads(json_output)
            except json.JSONDecodeError:
                # Se falhar, tenta encontrar um JSON válido na saída
                print("Erro ao decodificar JSON, tentando encontrar JSON válido na saída...")
                for line in output_lines:
                    line = line.strip()
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            relatorio = json.loads(line)
                            print("JSON válido encontrado!")
                            break
                        except Exception as e:
                            print(f"Erro ignorado em {__file__}: {e}")
                            continue
                else:
                    # Se não encontrar JSON válido, retorna erro
                    print("Nenhum JSON válido encontrado na saída")
                    return {
                        "success": False,
                        "message": "Não foi possível encontrar um JSON válido na saída do script",
                        "raw_output": result.stdout
                    }
            
            # Processa cada seção do relatório
            dados_processados = {
                "success": True,
                "data": relatorio.get("Data", ""),
                "servidor": relatorio.get("Servidor", ""),
                "sistema": {},
                "features": [],
                "servicos": [],
                "eventos": [],
                "processos": [],
                "bpa": []
            }
            
            # Função auxiliar para processar cada seção
            def processar_secao(nome_secao, secao_padrao="[]"):
                try:
                    # Obtém a seção do relatório
                    secao_raw = relatorio.get(nome_secao)
                    
                    # Se a seção já for um dicionário ou lista, usa diretamente
                    if isinstance(secao_raw, (dict, list)):
                        if isinstance(secao_raw, dict) and "error" in secao_raw:
                            return [{"error": secao_raw.get("error")}]
                        return secao_raw
                    
                    # Se for string, tenta converter para JSON
                    if isinstance(secao_raw, str):
                        secao_json = json.loads(secao_raw)
                        if isinstance(secao_json, dict) and "error" in secao_json:
                            return [{"error": secao_json.get("error")}]
                        return secao_json
                    
                    # Se não for string nem objeto, usa o padrão
                    if secao_raw is None:
                        return json.loads(secao_padrao)
                    
                    # Caso não consiga processar, retorna erro
                    return [{"error": f"Formato inesperado para {nome_secao}"}]
                except Exception as e:
                    return [{"error": f"Erro ao processar dados de {nome_secao}: {str(e)}"}]
            
            # Processa informações do sistema
            try:
                sistema_raw = relatorio.get("Sistema", "{}")
                
                # Verifica se já é um dicionário
                if isinstance(sistema_raw, dict):
                    sistema = sistema_raw
                else:
                    # Se for string, tenta converter para JSON
                    sistema = json.loads(sistema_raw)
                
                if isinstance(sistema, dict) and "error" in sistema:
                    dados_processados["sistema"] = {"error": sistema.get("error")}
                else:
                    dados_processados["sistema"] = sistema
            except Exception as e:
                print(f"Erro ao processar dados do sistema: {str(e)}")
                print(f"Tipo de Sistema: {type(relatorio.get('Sistema'))}")
                print(f"Conteúdo de Sistema: {relatorio.get('Sistema')}")
                dados_processados["sistema"] = {"error": f"Erro ao processar dados do sistema: {str(e)}"}
            
            # Processa cada seção
            dados_processados["features"] = processar_secao("Features")
            dados_processados["servicos"] = processar_secao("Servicos")
            dados_processados["eventos"] = processar_secao("Eventos")
            dados_processados["processos"] = processar_secao("Processos")
            dados_processados["bpa"] = processar_secao("BPA")
            
            return dados_processados
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "message": f"Erro ao processar resposta do servidor: {str(e)}",
                "raw_output": result.stdout
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Erro ao gerar relatório: {str(e)}"
        }

def gerar_relatorio_simples(ip, username, password):
    """Gera um relatório simplificado da VM usando o script server_report.ps1"""
    try:
        # Verifica se a VM está online
        if not verificar_vm_online(ip):
            return {
                "success": False, 
                "message": "VM não está acessível no momento"
            }
        
        # Caminho para o script PowerShell (usa versão original por compatibilidade)
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server_report.ps1")
        
        # Executa o script PowerShell de forma mais segura
        print(f"Executando script PowerShell para {ip}...")
        try:
            # Cria um comando PowerShell que trata a senha de forma mais segura
            # Escapa caracteres especiais na senha
            password_escaped = password.replace("'", "''").replace('"', '""')
            
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path, 
                 "-servidor", ip, "-username", username, "-password", password_escaped],
                capture_output=True,
                text=True,
                timeout=180  # Aumenta o timeout para 180 segundos
            )
            print(f"Script PowerShell concluído. Código de saída: {result.returncode}")
            if result.returncode != 0:
                print(f"ERRO no script PowerShell: {result.stderr}")
                return {
                    "success": False,
                    "message": f"Erro no script PowerShell: {result.stderr}"
                }
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT ao executar script PowerShell para {ip}")
            return {
                "success": False,
                "message": "Tempo limite excedido ao executar o script PowerShell"
            }
        except Exception as e:
            print(f"ERRO ao executar script PowerShell: {str(e)}")
            return {
                "success": False,
                "message": f"Erro ao executar script PowerShell: {str(e)}"
            }
        
        # Processa os resultados
        try:
            # Adiciona informações de depuração
            print(f"Saída do PowerShell: {result.stdout[:500]}...")
            
            # Verifica se a saída está vazia
            if not result.stdout.strip():
                print("ERRO: Saída do PowerShell está vazia")
                print(f"Erro do PowerShell: {result.stderr}")
                return {
                    "success": False,
                    "message": "O script PowerShell não retornou dados",
                    "stderr": result.stderr
                }
            
            # Tenta limpar a saída para garantir que é um JSON válido
            output_lines = result.stdout.strip().split('\n')
            json_output = output_lines[-1]  # Pega a última linha, que deve ser o JSON
            
            try:
                relatorio = json.loads(json_output)
            except json.JSONDecodeError:
                # Se falhar, tenta encontrar um JSON válido na saída
                print("Erro ao decodificar JSON, tentando encontrar JSON válido na saída...")
                for line in output_lines:
                    line = line.strip()
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            relatorio = json.loads(line)
                            print("JSON válido encontrado!")
                            break
                        except Exception as e:
                            print(f"Erro ignorado em {__file__}: {e}")
                            continue
                else:
                    # Se não encontrar JSON válido, retorna erro
                    print("Nenhum JSON válido encontrado na saída")
                    return {
                        "success": False,
                        "message": "Não foi possível encontrar um JSON válido na saída do script",
                        "raw_output": result.stdout
                    }
            
            # Processa cada seção do relatório
            dados_processados = {
                "success": True,
                "data": relatorio.get("Data", ""),
                "servidor": relatorio.get("Servidor", ""),
                "sistema": {},
                "features": [],
                "servicos": [],
                "eventos": [],
                "processos": [],
                "bpa": []
            }
            
            # Processa informações do sistema
            try:
                sistema_raw = relatorio.get("Sistema", "{}")
                
                # Verifica se já é um dicionário
                if isinstance(sistema_raw, dict):
                    sistema = sistema_raw
                else:
                    # Se for string, tenta converter para JSON
                    sistema = json.loads(sistema_raw)
                
                if isinstance(sistema, dict) and "error" in sistema:
                    dados_processados["sistema"] = {"error": sistema.get("error")}
                else:
                    dados_processados["sistema"] = sistema
            except Exception as e:
                print(f"Erro ao processar dados do sistema: {str(e)}")
                print(f"Tipo de Sistema: {type(relatorio.get('Sistema'))}")
                print(f"Conteúdo de Sistema: {relatorio.get('Sistema')}")
                dados_processados["sistema"] = {"error": f"Erro ao processar dados do sistema: {str(e)}"}
            
            # Função auxiliar para processar cada seção
            def processar_secao(nome_secao, secao_padrao="[]"):
                try:
                    # Obtém a seção do relatório
                    secao_raw = relatorio.get(nome_secao)
                    
                    # Se a seção já for um dicionário ou lista, usa diretamente
                    if isinstance(secao_raw, (dict, list)):
                        if isinstance(secao_raw, dict) and "error" in secao_raw:
                            return [{"error": secao_raw.get("error")}]
                        return secao_raw
                    
                    # Se for string, tenta converter para JSON
                    if isinstance(secao_raw, str):
                        secao_json = json.loads(secao_raw)
                        if isinstance(secao_json, dict) and "error" in secao_json:
                            return [{"error": secao_json.get("error")}]
                        return secao_json
                    
                    # Se não for string nem objeto, usa o padrão
                    if secao_raw is None:
                        return json.loads(secao_padrao)
                    
                    # Caso não consiga processar, retorna erro
                    return [{"error": f"Formato inesperado para {nome_secao}"}]
                except Exception as e:
                    return [{"error": f"Erro ao processar dados de {nome_secao}: {str(e)}"}]
            
            # Processa cada seção
            dados_processados["features"] = processar_secao("Features")
            dados_processados["servicos"] = processar_secao("Servicos")
            dados_processados["eventos"] = processar_secao("Eventos")
            dados_processados["processos"] = processar_secao("Processos")
            dados_processados["bpa"] = processar_secao("BPA")
            
            return dados_processados
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "message": f"Erro ao processar resposta do servidor: {str(e)}",
                "raw_output": result.stdout
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Erro ao gerar relatório: {str(e)}"
        }

def verificar_vm_completo(vm_id):
    """Verifica uma VM específica e atualiza suas informações"""
    try:
        # Carrega as VMs cadastradas
        vms_file = os.path.join(PROJECT_ROOT, 'data', 'vms.json')
        if not os.path.exists(vms_file):
            return {"success": False, "message": "Arquivo de VMs não encontrado"}
        
        with open(vms_file, 'r', encoding='utf-8') as f:
            vms = json.load(f)
        
        # Procura a VM específica
        vm = None
        vm_index = -1
        for i, v in enumerate(vms):
            if v.get("id") == vm_id:
                vm = v
                vm_index = i
                break
        
        if not vm:
            return {"success": False, "message": "VM não encontrada"}
        
        # Obtém as credenciais da VM
        ip = vm.get("ip")
        username = vm.get("username")
        password = vm.get("password")
        
        if not ip or not username or not password:
            return {"success": False, "message": "Credenciais incompletas para a VM"}
        
        # Verifica se a VM está online
        vm_online = verificar_vm_online(ip)
        
        # Atualiza o status da VM
        if vm_online:
            vm["status"] = "Running"
            
            # Obtém detalhes da VM
            detalhes = obter_detalhes_vm(ip, username, password)
            
            if detalhes["success"]:
                vm["operatingSystem"] = detalhes["details"]["operatingSystem"]
                vm["processors"] = detalhes["details"]["processors"]
                vm["memory"] = detalhes["details"]["memory"]
                vm["details"] = detalhes["details"]
        else:
            vm["status"] = "Unreachable"
        
        # Atualiza a data da última verificação
        vm["last_check"] = datetime.now().isoformat()
        
        # Salva as alterações
        vms[vm_index] = vm
        with open(vms_file, 'w', encoding='utf-8') as f:
            json.dump(vms, f, indent=4)
        
        return {"success": True, "message": f"VM {vm.get('name')} verificada com sucesso", "vm": vm}
    except Exception as e:
        return {"success": False, "message": f"Erro ao verificar VM: {str(e)}"}