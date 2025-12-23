# === CONFIGURAÇÕES INICIAIS ===
# Suprime o warning PSAvoidUsingPlainTextForPassword pois precisamos manter compatibilidade
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', '')]
param(
    [string]$servidor,
    [string]$username,
    [Parameter(Mandatory=$true)]
    [string]$password  # Mantido como string para compatibilidade, mas será convertido imediatamente
)

# Cria credencial de forma mais segura
# Converte a senha para SecureString imediatamente após receber
$secpasswd = ConvertTo-SecureString $password -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ($username, $secpasswd)

# Limpa a variável de senha da memória por segurança
$password = $null
$data = Get-Date -Format "dd/MM/yyyy HH:mm:ss"

# === COLETA DE DADOS ===

# 1. ROLES E FEATURES INSTALADOS
try {
    $features = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-WindowsFeature | Where-Object { $_.Installed } |
        Select-Object DisplayName, Name, @{
            Name = 'InstallState';
            Expression = {$_.InstallState.ToString()}
        }
    } -ErrorAction Stop
    $featuresJson = $features | ConvertTo-Json -Depth 1
}
catch {
    $featuresJson = "[]"
}

# 2. SERVIÇOS RELACIONADOS A ROLES
try {
    $servicos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-Service | Where-Object {
            $_.Name -match "dns|dhcp|ntds|file|netlogon|w32time"
        } | Select-Object Name, DisplayName, @{
            Name = 'Status';
            Expression = {$_.Status.ToString()}
        }, @{
            Name = 'StartType';
            Expression = {
                try {
                    $svc = Get-WmiObject -Class Win32_Service -Filter "Name='$($_.Name)'"
                    $svc.StartMode
                }
                catch {
                    "Unknown"
                }
            }
        }
    } -ErrorAction Stop
    $servicosJson = $servicos | ConvertTo-Json -Depth 1
}
catch {
    $servicosJson = "[]"
}

# 3. ÚLTIMOS 20 LOGS DO SISTEMA
try {
    $eventos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        # Coleta os últimos 20 eventos do sistema (Error, Warning, Information importantes)
        $allEvents = @()
        
        # Eventos de erro (mais críticos)
        $errorEvents = Get-EventLog -LogName System -EntryType Error -Newest 10 -ErrorAction SilentlyContinue
        if ($errorEvents) {
            $allEvents += $errorEvents | Select-Object @{
                Name = 'TimeGenerated';
                Expression = {$_.TimeGenerated.ToString("dd/MM/yyyy HH:mm:ss")}
            }, Source, EventID, @{
                Name = 'EntryType';
                Expression = {'Error'}
            }, @{
                Name = 'Message';
                Expression = {
                    $msg = $_.Message -replace '[\r\n]', ' ' -replace '"', "'"
                    if ($msg.Length -gt 200) { $msg.Substring(0, 200) + "..." } else { $msg }
                }
            }
        }
        
        # Eventos de aviso importantes
        $warningEvents = Get-EventLog -LogName System -EntryType Warning -Newest 5 -ErrorAction SilentlyContinue
        if ($warningEvents) {
            $allEvents += $warningEvents | Select-Object @{
                Name = 'TimeGenerated';
                Expression = {$_.TimeGenerated.ToString("dd/MM/yyyy HH:mm:ss")}
            }, Source, EventID, @{
                Name = 'EntryType';
                Expression = {'Warning'}
            }, @{
                Name = 'Message';
                Expression = {
                    $msg = $_.Message -replace '[\r\n]', ' ' -replace '"', "'"
                    if ($msg.Length -gt 200) { $msg.Substring(0, 200) + "..." } else { $msg }
                }
            }
        }
        
        # Eventos informativos importantes (relacionados a serviços críticos)
        $infoEvents = Get-EventLog -LogName System -EntryType Information -Newest 20 -ErrorAction SilentlyContinue | 
            Where-Object { 
                $_.Source -match "Service Control Manager|DNS|DHCP|Netlogon|NTDS|Time-Service" 
            } | Select-Object -First 5
        
        if ($infoEvents) {
            $allEvents += $infoEvents | Select-Object @{
                Name = 'TimeGenerated';
                Expression = {$_.TimeGenerated.ToString("dd/MM/yyyy HH:mm:ss")}
            }, Source, EventID, @{
                Name = 'EntryType';
                Expression = {'Information'}
            }, @{
                Name = 'Message';
                Expression = {
                    $msg = $_.Message -replace '[\r\n]', ' ' -replace '"', "'"
                    if ($msg.Length -gt 200) { $msg.Substring(0, 200) + "..." } else { $msg }
                }
            }
        }
        
        # Ordena por data (mais recente primeiro) e pega os 20 mais recentes
        $allEvents | Sort-Object TimeGenerated -Descending | Select-Object -First 20
        
    } -ErrorAction Stop
    $eventosJson = $eventos | ConvertTo-Json -Depth 1
}
catch {
    $eventosJson = "[]"
}

# 4. USO DE CPU/MEMÓRIA DOS PROCESSOS
try {
    $processos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 Name, Id, @{
            Name = 'CPU';
            Expression = {
                if ($_.CPU -ne $null) {
                    [math]::Round($_.CPU, 2)
                } else {
                    0
                }
            }
        }, @{
            Name = 'Memory';
            Expression = {
                if ($_.WorkingSet -ne $null) {
                    [math]::Round($_.WorkingSet / 1MB, 2)
                } else {
                    0
                }
            }
        }, @{
            Name = 'PrivateMemory';
            Expression = {
                if ($_.PrivateMemorySize -ne $null) {
                    [math]::Round($_.PrivateMemorySize / 1MB, 2)
                } else {
                    0
                }
            }
        }, @{
            Name = 'Handles';
            Expression = {$_.Handles}
        }, @{
            Name = 'Threads';
            Expression = {$_.Threads.Count}
        }
    } -ErrorAction Stop
    $processosJson = $processos | ConvertTo-Json -Depth 1
}
catch {
    $processosJson = "[]"
}

# 5. RESULTADOS BPA (Active Directory)
try {
    $bpa = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        try {
            Invoke-BpaModel -ModelId Microsoft/Windows/DirectoryServices -ErrorAction Stop | Out-Null
            Get-BpaResult -ModelId Microsoft/Windows/DirectoryServices |
            Where-Object { $_.Severity -ne "Information" } |
            Select-Object Severity, Title, @{
                Name = 'Compliance';
                Expression = {$_.Compliance.ToString()}
            }, Problem, Impact, Resolution
        }
        catch {
            return "BPA não disponível ou erro ao executar."
        }
    } -ErrorAction Stop
    
    if ($bpa -is [string]) {
        $bpaJson = "{ ""message"": ""$bpa"" }"
    }
    else {
        $bpaJson = $bpa | ConvertTo-Json -Depth 2
    }
}
catch {
    $bpaJson = "{ ""message"": ""Erro ao executar BPA"" }"
}

# 6. INFORMAÇÕES DO SISTEMA
try {
    $sistema = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        $os = Get-CimInstance Win32_OperatingSystem
        $cs = Get-CimInstance Win32_ComputerSystem
        $proc = Get-CimInstance Win32_Processor
        
        # Informações de disco
        $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
        $diskInfo = @()
        foreach ($d in $disks) {
            $freeGB = [math]::Round($d.FreeSpace / 1GB, 2)
            $totalGB = [math]::Round($d.Size / 1GB, 2)
            $percentFree = [math]::Round(($d.FreeSpace / $d.Size) * 100, 2)
            
            $diskInfo += [PSCustomObject]@{
                Drive = $d.DeviceID
                FreeGB = $freeGB
                TotalGB = $totalGB
                PercentFree = $percentFree
            }
        }
        
        # Informações do sistema
        $info = [PSCustomObject]@{
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
        }
        
        return $info
    } -ErrorAction Stop
    
    # Converte para JSON
    $sistemaJson = $sistema | ConvertTo-Json -Depth 3
}
catch {
    $sistemaJson = "{ ""error"": ""$($_.Exception.Message)"" }"
}

# === SAÍDA DOS RESULTADOS ===
try {
    $resultado = @{
        Data = $data
        Servidor = $servidor
        Sistema = $sistemaJson
        Features = $featuresJson
        Servicos = $servicosJson
        Eventos = $eventosJson
        Processos = $processosJson
        BPA = $bpaJson
    } | ConvertTo-Json -Depth 6 -Compress
    
    Write-Output $resultado
}
catch {
    # Garante que sempre retornamos um JSON válido, mesmo em caso de erro
    $errorJson = @{
        success = $false
        message = "Erro ao gerar relatório: $($_.Exception.Message)"
        error = $_.Exception.Message
        errorType = $_.Exception.GetType().Name
        stackTrace = $_.ScriptStackTrace
    } | ConvertTo-Json -Compress
    
    Write-Output $errorJson
}