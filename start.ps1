$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $env:LOCALAPPDATA 'TapoDesk\python-runtime\Scripts\pythonw.exe'
if (Test-Path '.windows-runtime') {
    $python = Join-Path ((Get-Content -LiteralPath '.windows-runtime' -Raw).Trim()) 'Scripts\pythonw.exe'
}
if (!(Test-Path $python)) { $python = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe' }
if (!(Test-Path $python)) { throw 'Run .\setup.ps1 first.' }
Start-Process -FilePath $python -ArgumentList (@('run.py') + $args) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
