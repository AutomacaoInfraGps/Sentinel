<##
.SYNOPSIS
    Captura uma imagem PNG real de uma janela visível do Windows.
.EXAMPLE
    .\Capturar-Janela.ps1 -IdProcesso 1234 -Saida .\dados\execucoes\ADUC.png
##>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][int]$IdProcesso,
    [Parameter(Mandatory)][string]$Saida,
    [switch]$Maximizar,
    [switch]$MonitorMaior,
    [long]$JanelaEmPrimeiroPlano = 0,
    [switch]$AreaJanelaPrincipal
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AuditWindow {
    [StructLayout(LayoutKind.Sequential)]
    public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr hWnd, bool altTab);
    [DllImport("user32.dll")] public static extern void keybd_event(byte virtualKey, byte scan, uint flags, UIntPtr extraInfo);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr insertAfter, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int x, int y, int width, int height, bool repaint);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out Rect rect);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
'@

$processo = Get-Process -Id $IdProcesso -ErrorAction Stop
if ($processo.MainWindowHandle -eq [IntPtr]::Zero -and -not $JanelaEmPrimeiroPlano) {
    throw "O processo $IdProcesso não possui janela principal visível."
}
if ($AreaJanelaPrincipal -and $processo.MainWindowHandle -eq [IntPtr]::Zero) {
    throw "O processo $IdProcesso não possui janela principal para capturar."
}
$janelaAlvo = if ($JanelaEmPrimeiroPlano) { [IntPtr]$JanelaEmPrimeiroPlano } else { $processo.MainWindowHandle }
$donoAlvo = [uint32]0
$null = [AuditWindow]::GetWindowThreadProcessId($janelaAlvo, [ref]$donoAlvo)
if ($donoAlvo -ne $IdProcesso) { throw "A janela $JanelaEmPrimeiroPlano não pertence ao processo $IdProcesso." }

if ($MonitorMaior) {
    $destino = [System.Windows.Forms.Screen]::AllScreens |
        Sort-Object { $_.Bounds.Width * $_.Bounds.Height } -Descending |
        Select-Object -First 1
    $null = [AuditWindow]::ShowWindow($janelaAlvo, 9)
    $null = [AuditWindow]::MoveWindow($janelaAlvo,
        ($destino.WorkingArea.Left + 80), ($destino.WorkingArea.Top + 60),
        ($destino.WorkingArea.Width - 160), ($destino.WorkingArea.Height - 120), $true)
    Start-Sleep -Milliseconds 300
}
if ($Maximizar) {
    $null = [AuditWindow]::ShowWindow($janelaAlvo, 3)
    Start-Sleep -Milliseconds 500
}
$ativa = [AuditWindow]::GetForegroundWindow()
$dono = [uint32]0
$null = [AuditWindow]::GetWindowThreadProcessId($ativa, [ref]$dono)
if (($JanelaEmPrimeiroPlano -and $ativa -ne $janelaAlvo) -or $dono -ne $IdProcesso) {
    [AuditWindow]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
    [AuditWindow]::keybd_event(0x12, 0, 0x0002, [UIntPtr]::Zero)
    $null = [AuditWindow]::ShowWindow($janelaAlvo, 9)
    $null = [AuditWindow]::SetForegroundWindow($janelaAlvo)
    [AuditWindow]::SwitchToThisWindow($janelaAlvo, $true)
    Start-Sleep -Milliseconds 600
    $ativa = [AuditWindow]::GetForegroundWindow()
    $null = [AuditWindow]::GetWindowThreadProcessId($ativa, [ref]$dono)
}
if ($JanelaEmPrimeiroPlano) {
    # Mantém o diálogo solicitado acima da janela principal durante a captura,
    # inclusive quando ambas pertencem ao mesmo processo mmc.exe.
    $null = [AuditWindow]::ShowWindow($janelaAlvo, 9)
    $null = [AuditWindow]::SetWindowPos($janelaAlvo, [IntPtr](-1), 0, 0, 0, 0, 0x0043)
    $null = [AuditWindow]::SetForegroundWindow($janelaAlvo)
    [AuditWindow]::SwitchToThisWindow($janelaAlvo, $true)
    Start-Sleep -Milliseconds 500
    $ativa = [AuditWindow]::GetForegroundWindow()
    $null = [AuditWindow]::GetWindowThreadProcessId($ativa, [ref]$dono)
}
if ($dono -ne $IdProcesso) {
    throw "A janela do processo $IdProcesso não está em primeiro plano; captura cancelada."
}

$tela = [System.Windows.Forms.Screen]::FromHandle($ativa).Bounds
$areaUtil = [System.Windows.Forms.Screen]::FromHandle($ativa).WorkingArea
if ($areaUtil.Width -eq $tela.Width -and $areaUtil.Height -eq $tela.Height) {
    throw 'A barra de tarefas está oculta; data e horário não ficariam visíveis na evidência.'
}
$retangulo = New-Object AuditWindow+Rect
$retangulo.Left = $tela.Left; $retangulo.Top = $tela.Top
$retangulo.Right = $tela.Right; $retangulo.Bottom = $tela.Bottom
$largura = $tela.Width; $altura = $tela.Height

$Saida = [System.IO.Path]::GetFullPath($Saida)
New-Item -ItemType Directory -Path (Split-Path -Parent $Saida) -Force | Out-Null
$null = [AuditWindow]::SetCursorPos(($retangulo.Left + 70), ($retangulo.Top + 14))
Start-Sleep -Milliseconds 350
$bitmap = New-Object System.Drawing.Bitmap($largura, $altura)
$grafico = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $origem = New-Object System.Drawing.Point($retangulo.Left, $retangulo.Top)
    $grafico.CopyFromScreen($origem, [System.Drawing.Point]::Empty, $bitmap.Size)
    $bitmap.Save($Saida, [System.Drawing.Imaging.ImageFormat]::Png)
}
finally {
    $grafico.Dispose()
    $bitmap.Dispose()
    if ($JanelaEmPrimeiroPlano) {
        $null = [AuditWindow]::SetWindowPos($janelaAlvo, [IntPtr](-2), 0, 0, 0, 0, 0x0043)
    }
}

Write-Output ([pscustomobject]@{
    Arquivo = $Saida
    Processo = $IdProcesso
    Titulo = $processo.MainWindowTitle
    Dimensoes = "${largura}x${altura}"
    BarraDeTarefasVisivel = $true
    CapturadoEm = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
})
