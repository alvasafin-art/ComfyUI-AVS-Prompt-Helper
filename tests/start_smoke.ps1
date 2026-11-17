param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$ComfyRoot
)

$ErrorActionPreference = 'Stop'
$pythonExe = (Resolve-Path -LiteralPath $Python).Path
$main = (Resolve-Path -LiteralPath (Join-Path $ComfyRoot 'main.py')).Path
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtime = Join-Path $projectRoot 'test-results\runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $runtime 'custom_nodes') | Out-Null
$config = Join-Path $runtime 'paths.yaml'
$parent = (Split-Path $projectRoot -Parent).Replace('\', '/')
"avs_smoke:`n  base_path: $parent`n  custom_nodes: .`n" | Set-Content -LiteralPath $config
$nodeFolder = Split-Path $projectRoot -Leaf
$arguments = @('"' + $main + '"', '--cpu', '--listen', '127.0.0.1', '--port', '8199', '--disable-auto-launch', '--disable-all-custom-nodes', '--whitelist-custom-nodes', '"' + $nodeFolder + '"', '--base-directory', '"' + $runtime + '"', '--extra-model-paths-config', '"' + $config + '"')
$process = Start-Process -FilePath $pythonExe -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log') -PassThru
$process.Id | Set-Content (Join-Path $runtime 'server.pid')
Write-Output "Isolated smoke server PID: $($process.Id); http://127.0.0.1:8199"
