$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = @(
    (Join-Path $projectDir ".venv31410\Scripts\python.exe"),
    (Join-Path $projectDir ".venv\Scripts\python.exe"),
    (Join-Path $projectDir "venv\Scripts\python.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$runner = Join-Path $projectDir "run_web_service.py"
$logDir = Join-Path $projectDir "logs"
$stdoutLog = Join-Path $logDir "web_task_stdout.log"
$stderrLog = Join-Path $logDir "web_task_stderr.log"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not $pythonExe) {
    throw "Python não encontrado em .venv31410, .venv ou venv."
}

if (-not (Test-Path $runner)) {
    throw "Runner não encontrado em $runner"
}

$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $runner `
    -WorkingDirectory $projectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru `
    -Wait

exit $process.ExitCode
