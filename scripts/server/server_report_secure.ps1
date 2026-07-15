# === CONFIGURAÇÕES INICIAIS (VERSÃO SEGURA) ===
param(
    [string]$servidor,
    [string]$username,
    [SecureString]$password
)

# Cria credencial usando SecureString
$cred = New-Object System.Management.Automation.PSCredential ($username, $password)
$data = Get-Date -Format "dd/MM/yyyy HH:mm:ss"

# === COLETA DE DADOS ===

# 1. ROLES E FEATURES INSTALADOS
try {
    $features = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-WindowsFeature | Where-Object { $_.Installed } |
        Select-Object DisplayName, Name, @{
            Name = 'InstallState';
            Expression = { $_.InstallState.ToString() }
        } | Sort-Object DisplayName
    } -ErrorAction Stop
    
    $featuresJson = $features | ConvertTo-Json -Depth 2
} catch {
    $featuresJson = @"
[{"error": "Erro ao obter roles e features: $($_.Exception.Message)"}]
"@
}

# 2. INFORMAÇÕES DO SISTEMA
try {
    $sistema = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        $os = Get-WmiObject -Class Win32_OperatingSystem
        $cs = Get-WmiObject -Class Win32_ComputerSystem
        $proc = Get-WmiObject -Class Win32_Processor | Select-Object -First 1
        
        $uptime = (Get-Date) - $os.ConvertToDateTime($os.LastBootUpTime)
        $uptimeString = "{0} dias, {1} horas, {2} minutos" -f $uptime.Days, $uptime.Hours, $uptime.Minutes
        
        [PSCustomObject]@{
            OperatingSystem = $os.Caption
            OSVersion = $os.Version
            Uptime = $uptimeString
            LastBoot = $os.ConvertToDateTime($os.LastBootUpTime).ToString("dd/MM/yyyy HH:mm:ss")
            Processors = "$($cs.NumberOfProcessors) x $($proc.Name)"
            Memory = "{0:N2} GB" -f ($cs.TotalPhysicalMemory / 1GB)
            Manufacturer = $cs.Manufacturer
            Model = $cs.Model
            SerialNumber = $cs.SerialNumber
        }
    } -ErrorAction Stop
    
    $sistemaJson = $sistema | ConvertTo-Json -Depth 2
} catch {
    $sistemaJson = @"
{"error": "Erro ao obter informações do sistema: $($_.Exception.Message)"}
"@
}

# 3. INFORMAÇÕES DE DISCOS
try {
    $discos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-WmiObject -Class Win32_LogicalDisk -Filter "DriveType=3" |
        ForEach-Object {
            $totalGB = [math]::Round($_.Size / 1GB, 2)
            $freeGB = [math]::Round($_.FreeSpace / 1GB, 2)
            $usedGB = [math]::Round(($_.Size - $_.FreeSpace) / 1GB, 2)
            $percentUsed = if ($_.Size -gt 0) { [math]::Round((($_.Size - $_.FreeSpace) / $_.Size) * 100, 1) } else { 0 }
            
            [PSCustomObject]@{
                Drive = $_.DeviceID
                VolumeName = if ($_.VolumeName) { $_.VolumeName } else { "Sem nome" }
                TotalSpace = "$totalGB GB"
                FreeSpace = "$freeGB GB"
                UsedSpace = "$usedGB GB"
                PercentUsed = $percentUsed
            }
        }
    } -ErrorAction Stop
    
    $discosJson = $discos | ConvertTo-Json -Depth 2
} catch {
    $discosJson = @"
[{"error": "Erro ao obter informações de discos: $($_.Exception.Message)"}]
"@
}

# 4. SERVIÇOS (apenas os mais importantes)
try {
    $servicos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-Service | Where-Object { 
            $_.Status -eq 'Running' -or ($_.Status -eq 'Stopped' -and $_.StartType -eq 'Automatic')
        } | Select-Object DisplayName, Name, @{
            Name = 'Status';
            Expression = { $_.Status.ToString() }
        }, @{
            Name = 'StartMode';
            Expression = { 
                try {
                    $svc = Get-WmiObject -Class Win32_Service -Filter "Name='$($_.Name)'"
                    switch($svc.StartMode) {
                        "Auto" { "Auto" }
                        "Manual" { "Manual" }
                        "Disabled" { "Disabled" }
                        default { $svc.StartMode }
                    }
                } catch {
                    "Unknown"
                }
            }
        } | Sort-Object Status, DisplayName
    } -ErrorAction Stop
    
    $servicosJson = $servicos | ConvertTo-Json -Depth 2
} catch {
    $servicosJson = @"
[{"error": "Erro ao obter informações de serviços: $($_.Exception.Message)"}]
"@
}

# 5. INFORMAÇÕES DE REDE
try {
    $rede = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-WmiObject -Class Win32_NetworkAdapterConfiguration | Where-Object { 
            $_.IPEnabled -eq $true -and $_.IPAddress -ne $null 
        } | ForEach-Object {
            [PSCustomObject]@{
                Name = $_.Description
                Status = if ($_.IPEnabled) { "Up" } else { "Down" }
                IPAddress = ($_.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' }) -join ', '
                MACAddress = $_.MACAddress
                DefaultGateway = ($_.DefaultIPGateway | Where-Object { $_ }) -join ', '
            }
        }
    } -ErrorAction Stop
    
    $redeJson = $rede | ConvertTo-Json -Depth 2
} catch {
    $redeJson = @"
[{"error": "Erro ao obter informações de rede: $($_.Exception.Message)"}]
"@
}

# 6. PROCESSOS (Top 15 por CPU)
try {
    $processos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-Process | Where-Object { $_.CPU -gt 0 } | 
        Sort-Object CPU -Descending | Select-Object -First 15 |
        ForEach-Object {
            [PSCustomObject]@{
                Name = $_.ProcessName
                Id = $_.Id
                CPU = [math]::Round($_.CPU, 2)
                Memory = [math]::Round($_.WorkingSet / 1MB, 2)
            }
        }
    } -ErrorAction Stop
    
    $processosJson = $processos | ConvertTo-Json -Depth 2
} catch {
    $processosJson = @"
[{"error": "Erro ao obter informações de processos: $($_.Exception.Message)"}]
"@
}

# 7. EVENTOS DO SISTEMA (Últimos 20)
try {
    $eventos = Invoke-Command -ComputerName $servidor -Credential $cred -ScriptBlock {
        Get-EventLog -LogName System -Newest 20 | ForEach-Object {
            [PSCustomObject]@{
                TimeGenerated = $_.TimeGenerated.ToString("dd/MM/yyyy HH:mm:ss")
                EntryType = $_.EntryType.ToString()
                Source = $_.Source
                EventID = $_.EventID
                Message = if ($_.Message.Length -gt 100) { $_.Message.Substring(0, 100) + "..." } else { $_.Message }
            }
        }
    } -ErrorAction Stop
    
    $eventosJson = $eventos | ConvertTo-Json -Depth 2
} catch {
    $eventosJson = @"
[{"error": "Erro ao obter logs do sistema: $($_.Exception.Message)"}]
"@
}

# === SAÍDA JSON CONSOLIDADA ===
$relatorioCompleto = @{
    servidor = $servidor
    data_coleta = $data
    features = $featuresJson | ConvertFrom-Json
    sistema = $sistemaJson | ConvertFrom-Json
    discos = $discosJson | ConvertFrom-Json
    servicos = $servicosJson | ConvertFrom-Json
    rede = $redeJson | ConvertFrom-Json
    processos = $processosJson | ConvertFrom-Json
    eventos = $eventosJson | ConvertFrom-Json
}

# Converte para JSON e exibe
$relatorioCompleto | ConvertTo-Json -Depth 3 -Compress