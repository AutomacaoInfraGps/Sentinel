param(
    [Parameter(Mandatory = $true)]
    [string]$Database,

    [Parameter(Mandatory = $true)]
    [string]$Settings,

    [string]$EnvironmentFile,

    [string]$LogFile = "logs\alertad.jsonl",
    [switch]$DryRun,
    [switch]$Once,
    [switch]$InitializeAtEnd
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$launcher = Join-Path $projectRoot "alertad.py"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python do ambiente virtual não encontrado: $python"
}

$workerArguments = @(
    $launcher,
    "worker",
    $Database,
    "--settings", $Settings,
    "--log-file", $LogFile
)

if ($EnvironmentFile) {
    $workerArguments += @("--env-file", $EnvironmentFile)
}

if ($DryRun) { $workerArguments += "--dry-run" }
if ($Once) { $workerArguments += "--once" }
if ($InitializeAtEnd) { $workerArguments += "--initialize-at-end" }

& $python @workerArguments
exit $LASTEXITCODE
