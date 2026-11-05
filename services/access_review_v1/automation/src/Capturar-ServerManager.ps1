[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SaidaDashboard,
    [Parameter(Mandatory)][string]$SaidaLocalServer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ServerManagerMouse {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
}
'@

$serverManager = Join-Path $env:WINDIR 'System32\ServerManager.exe'
$capturar = Join-Path $PSScriptRoot '..\auditorias\servidores-windows\scripts\Capturar-Janela.ps1'
if (-not (Test-Path -LiteralPath $serverManager)) { throw "Server Manager não encontrado: $serverManager" }
if (-not (Test-Path -LiteralPath $capturar)) { throw "Capturador não encontrado: $capturar" }
Remove-Item -LiteralPath $SaidaDashboard, $SaidaLocalServer -Force -ErrorAction SilentlyContinue

function Obter-JanelaServerManager {
    Get-Process -Name ServerManager -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
        Sort-Object StartTime -Descending |
        Select-Object -First 1
}

function Aguardar-JanelaServerManager {
    param([datetime]$Limite, [int[]]$IdsExistentes)
    $inicio = Get-Date
    do {
        $janelas = @(Get-Process -Name ServerManager -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
            Sort-Object StartTime -Descending)
        $nova = $janelas | Where-Object { $_.Id -notin $IdsExistentes } | Select-Object -First 1
        if ($nova) { return $nova }
        if (((Get-Date) - $inicio).TotalSeconds -ge 5 -and $janelas.Count -gt 0) { return $janelas[0] }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $Limite)
    throw 'A janela do Server Manager não ficou disponível em 45 segundos.'
}

function Localizar-Elemento {
    param(
        [Parameter(Mandatory)][System.Windows.Automation.AutomationElement]$Raiz,
        [Parameter(Mandatory)][string[]]$Nomes
    )
    $itens = $Raiz.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition
    )
    foreach ($nome in $Nomes) {
        foreach ($item in $itens) {
            try {
                if ($item.Current.Name.Trim() -ieq $nome) { return $item }
            }
            catch {}
        }
    }
    return $null
}

function Acionar-Elemento {
    param(
        [Parameter(Mandatory)][System.Windows.Automation.AutomationElement]$Elemento,
        [Parameter(Mandatory)][string]$Descricao
    )
    foreach ($pattern in @(
        [System.Windows.Automation.SelectionItemPattern]::Pattern,
        [System.Windows.Automation.InvokePattern]::Pattern,
        [System.Windows.Automation.LegacyIAccessiblePattern]::Pattern
    )) {
        try {
            $controle = $Elemento.GetCurrentPattern($pattern)
            if ($controle -is [System.Windows.Automation.SelectionItemPattern]) { $controle.Select(); return }
            if ($controle -is [System.Windows.Automation.InvokePattern]) { $controle.Invoke(); return }
            if ($controle -is [System.Windows.Automation.LegacyIAccessiblePattern]) { $controle.DoDefaultAction(); return }
        }
        catch {}
    }
    $area = $Elemento.Current.BoundingRectangle
    if ($area.IsEmpty -or $area.Width -lt 2 -or $area.Height -lt 2) {
        throw "O item '$Descricao' foi localizado, mas não pode ser acionado."
    }
    $x = [int]($area.Left + ($area.Width / 2))
    $y = [int]($area.Top + ($area.Height / 2))
    $null = [ServerManagerMouse]::SetCursorPos($x, $y)
    [ServerManagerMouse]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [ServerManagerMouse]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

function Abrir-Pagina {
    param(
        [Parameter(Mandatory)][System.Windows.Automation.AutomationElement]$Raiz,
        [Parameter(Mandatory)][string[]]$Nomes,
        [Parameter(Mandatory)][string]$Descricao,
        [Parameter(Mandatory)][int]$DeslocamentoVertical
    )
    $elemento = Localizar-Elemento -Raiz $Raiz -Nomes $Nomes
    if (-not $elemento) {
        $area = $Raiz.Current.BoundingRectangle
        if ($area.IsEmpty -or $area.Width -lt 300 -or $area.Height -lt 300) {
            throw "Item '$Descricao' não encontrado e a área da janela não permite navegação alternativa."
        }
        $x = [int]($area.Left + 105)
        $y = [int]($area.Top + $DeslocamentoVertical)
        $null = [ServerManagerMouse]::SetCursorPos($x, $y)
        [ServerManagerMouse]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
        [ServerManagerMouse]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
        Write-Output "Item '$Descricao' acionado pela posição relativa da navegação lateral."
        return
    }
    Acionar-Elemento -Elemento $elemento -Descricao $Descricao
}

function Obter-RaizComNavegacao {
    param(
        [Parameter(Mandatory)][int]$IdProcesso,
        [Parameter(Mandatory)][string[]]$NomesDashboard
    )
    $limite = (Get-Date).AddSeconds(30)
    $escapeEnviado = $false
    do {
        $processoAtual = Get-Process -Id $IdProcesso -ErrorAction Stop
        $raizAtual = [System.Windows.Automation.AutomationElement]::FromHandle($processoAtual.MainWindowHandle)
        if ($raizAtual -and (Localizar-Elemento -Raiz $raizAtual -Nomes $NomesDashboard)) { return $raizAtual }
        if (-not $escapeEnviado) {
            [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
            $escapeEnviado = $true
        }
        if ($raizAtual -and $escapeEnviado -and ((Get-Date) - $inicio).TotalSeconds -ge 8) {
            # Algumas versões do Server Manager não expõem a navegação WPF ao UI Automation.
            # A função Abrir-Pagina usará a posição relativa da barra lateral nesse caso.
            return $raizAtual
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $limite)
    throw 'A navegação do Server Manager não apareceu após fechar os avisos iniciais.'
}

$existentes = @(Get-Process -Name ServerManager -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$iniciado = $null
$processo = $null
try {
    $compatibilidadeAnterior = $env:__COMPAT_LAYER
    try {
        # Primeiro tenta executar no mesmo nível do bot. A necessidade de
        # elevação será validada somente dentro do Rigel.
        $env:__COMPAT_LAYER = 'RunAsInvoker'
        $iniciado = Start-Process -FilePath $serverManager -PassThru
    }
    finally {
        $env:__COMPAT_LAYER = $compatibilidadeAnterior
    }
    $processo = Aguardar-JanelaServerManager -Limite (Get-Date).AddSeconds(45) -IdsExistentes $existentes
    Write-Output "Server Manager aberto: PID $($processo.Id)"

    # A primeira captura também posiciona e maximiza a janela no maior monitor.
    $preparacao = Join-Path $env:TEMP ("server-manager-preparacao-{0}.png" -f $PID)
    & $capturar -IdProcesso $processo.Id -Saida $preparacao -MonitorMaior -Maximizar
    if (-not (Test-Path -LiteralPath $preparacao)) { throw 'Falha ao preparar a janela do Server Manager.' }
    Remove-Item -LiteralPath $preparacao -Force -ErrorAction SilentlyContinue
    Write-Output 'Janela posicionada no maior monitor.'

    $raiz = Obter-RaizComNavegacao -IdProcesso $processo.Id -NomesDashboard @('Dashboard', 'Painel')
    Write-Output 'Navegação do Server Manager disponível.'

    Abrir-Pagina -Raiz $raiz -Nomes @('Dashboard', 'Painel') -Descricao 'Dashboard' -DeslocamentoVertical 90
    Write-Output 'Dashboard selecionado.'
    Start-Sleep -Seconds 3
    & $capturar -IdProcesso $processo.Id -Saida $SaidaDashboard -MonitorMaior -Maximizar
    if (-not (Test-Path -LiteralPath $SaidaDashboard)) {
        throw 'Falha ao capturar o Dashboard do Server Manager.'
    }
    Write-Output 'Dashboard capturado.'

    Abrir-Pagina -Raiz $raiz -Nomes @('Local Server', 'Servidor Local') -Descricao 'Local Server' -DeslocamentoVertical 130
    Write-Output 'Local Server selecionado; aguardando atualização por 5 segundos.'
    Start-Sleep -Seconds 5
    & $capturar -IdProcesso $processo.Id -Saida $SaidaLocalServer -MonitorMaior -Maximizar
    if (-not (Test-Path -LiteralPath $SaidaLocalServer)) {
        throw 'Falha ao capturar o Local Server do Server Manager.'
    }

    [pscustomobject]@{
        Dashboard = [IO.Path]::GetFullPath($SaidaDashboard)
        LocalServer = [IO.Path]::GetFullPath($SaidaLocalServer)
        EsperaLocalServerSegundos = 5
        CapturadoEm = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
    }
}
finally {
    Remove-Item -LiteralPath (Join-Path $env:TEMP ("server-manager-preparacao-{0}.png" -f $PID)) -Force -ErrorAction SilentlyContinue
    Get-Process -Name ServerManager -ErrorAction SilentlyContinue |
        Where-Object { $_.Id -notin $existentes } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    if ($iniciado -and -not $iniciado.HasExited -and $iniciado.Id -notin $existentes) {
        Stop-Process -Id $iniciado.Id -Force -ErrorAction SilentlyContinue
    }
}
