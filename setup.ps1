$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$runtime = Join-Path $env:LOCALAPPDATA 'TapoDesk\python-runtime'
$runtimePython = Join-Path $runtime 'Scripts\python.exe'
if (!(Test-Path $runtimePython)) {
    $python = $null
    foreach ($candidate in @('python', 'python3', 'py')) {
        if (!(Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        $candidateArgs = @()
        if ($candidate -eq 'py') { $candidateArgs = @('-3.12') }
        & $candidate @candidateArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) and sys.maxsize > 2**32 else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
    }
    if (!$python) { throw 'Install 64-bit Python 3.12 from python.org, then retry.' }
    & $python @candidateArgs -m venv $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& $runtimePython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not update pip.' }
& $runtimePython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$actualRuntime = & $runtimePython -c 'import sys; from pathlib import Path; print(Path(sys.executable).resolve().parent.parent)'
Set-Content -LiteralPath '.windows-runtime' -Value $actualRuntime -Encoding ascii
if ((Test-Path 'tools\ffmpeg\ffmpeg.exe') -and (Test-Path 'tools\ffmpeg\ffprobe.exe')) {
    $mediaTools = Join-Path $runtime 'tools\ffmpeg'
    New-Item -ItemType Directory -Force $mediaTools | Out-Null
    foreach ($name in @('ffmpeg.exe','ffprobe.exe','LICENSE.txt')) {
        if ((Test-Path "tools\ffmpeg\$name") -and !(Test-Path (Join-Path $mediaTools $name))) {
            Copy-Item -LiteralPath "tools\ffmpeg\$name" -Destination $mediaTools
        }
    }
}
Write-Host 'Ready. Run .\start.ps1'
if ((!(Test-Path 'tools\ffmpeg\ffmpeg.exe') -or !(Test-Path 'tools\ffmpeg\ffprobe.exe')) -and
    (!(Get-Command ffmpeg -ErrorAction SilentlyContinue) -or !(Get-Command ffprobe -ErrorAction SilentlyContinue))) {
    Write-Warning 'Recording playback and downloads require FFmpeg and ffprobe on PATH. Install FFmpeg, then open a new terminal.'
}
