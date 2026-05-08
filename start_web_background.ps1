$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$runner = Join-Path $projectDir "run_web_service.py"
$logDir = Join-Path $projectDir "logs"
$stdoutLog = Join-Path $logDir "web_task_stdout.log"
$stderrLog = Join-Path $logDir "web_task_stderr.log"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $pythonExe)) {
    throw "Python não encontrado em $pythonExe"
}

if (-not (Test-Path $runner)) {
    throw "Runner não encontrado em $runner"
}

Start-Process -FilePath $pythonExe -ArgumentList $runner -WorkingDirectory $projectDir -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog