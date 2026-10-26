[CmdletBinding()]
param([Parameter(Mandatory)][string]$Saida,[string]$TituloJanela='')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class AuditEvidenceWindow {
  public delegate bool EnumWindowsProc(IntPtr hWnd,IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback,IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd,StringBuilder text,int count);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd,int command);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd,int x,int y,int width,int height,bool repaint);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern void keybd_event(byte key,byte scan,uint flags,UIntPtr extra);
  [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr hWnd,bool altTab);
  public static IntPtr FindByTitle(string expected) {
    IntPtr found=IntPtr.Zero;
    EnumWindows((h,p)=>{if(!IsWindowVisible(h))return true;var b=new StringBuilder(1024);GetWindowText(h,b,b.Capacity);if(b.ToString().IndexOf(expected,StringComparison.OrdinalIgnoreCase)>=0){found=h;return false;}return true;},IntPtr.Zero);
    return found;
  }
}
'@
$monitor=[System.Windows.Forms.Screen]::AllScreens|Sort-Object {$_.Bounds.Width*$_.Bounds.Height} -Descending|Select-Object -First 1
if(-not $monitor){throw 'Nenhum monitor foi detectado.'}
$b=$monitor.Bounds;$w=$monitor.WorkingArea
if($w.Width -eq $b.Width -and $w.Height -eq $b.Height){throw 'A barra de tarefas está oculta; data e horário não ficariam visíveis na evidência.'}
if($TituloJanela){
  $janela=[AuditEvidenceWindow]::FindByTitle($TituloJanela)
  if($janela -eq [IntPtr]::Zero){throw "Janela do navegador não localizada pelo título: $TituloJanela"}
  $null=[AuditEvidenceWindow]::ShowWindow($janela,9)
  $null=[AuditEvidenceWindow]::MoveWindow($janela,$w.Left,$w.Top,$w.Width,$w.Height,$true)
  $null=[AuditEvidenceWindow]::ShowWindow($janela,3)
  [AuditEvidenceWindow]::keybd_event(0x12,0,0,[UIntPtr]::Zero)
  [AuditEvidenceWindow]::keybd_event(0x12,0,2,[UIntPtr]::Zero)
  $null=[AuditEvidenceWindow]::SetForegroundWindow($janela)
  [AuditEvidenceWindow]::SwitchToThisWindow($janela,$true)
  Start-Sleep -Milliseconds 600
  if([AuditEvidenceWindow]::GetForegroundWindow() -ne $janela){throw "A janela correta não ficou em primeiro plano: $TituloJanela"}
}
$Saida=[IO.Path]::GetFullPath($Saida);New-Item -ItemType Directory -Path (Split-Path -Parent $Saida) -Force|Out-Null
$bitmap=[Drawing.Bitmap]::new($b.Width,$b.Height);$graphics=[Drawing.Graphics]::FromImage($bitmap)
try{$graphics.CopyFromScreen([Drawing.Point]::new($b.Left,$b.Top),[Drawing.Point]::Empty,$bitmap.Size);$bitmap.Save($Saida,[Drawing.Imaging.ImageFormat]::Png)}finally{$graphics.Dispose();$bitmap.Dispose()}
[pscustomobject]@{Arquivo=$Saida;Monitor=$monitor.DeviceName;Dimensoes="$($b.Width)x$($b.Height)";BarraDeTarefasVisivel=$true;CapturadoEm=(Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')}
