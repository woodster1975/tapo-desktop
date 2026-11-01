$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$runtime = Join-Path $env:LOCALAPPDATA 'TapoDesk\python-runtime'
if (Test-Path '.windows-runtime') { $runtime = (Get-Content '.windows-runtime' -Raw).Trim() }
$python = Join-Path $runtime 'Scripts\python.exe'
if (!(Test-Path $python)) { throw 'Run setup.ps1 first.' }
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
& $python packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon conversion failed.' }
& $python packaging\fetch_ffmpeg.py
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg download verification failed.' }
& $python build.py --installer
if ($LASTEXITCODE -ne 0) { throw 'Windows package build failed.' }
