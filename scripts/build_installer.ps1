param(
    [string]$IsccPath
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$issPath = Join-Path $repoRoot "packaging\local-whisper.iss"
$distDir = Join-Path $repoRoot "dist\LocalWhisperTranscriber"
$distributionReadmePath = Join-Path $repoRoot "packaging\README.txt"

if (-not (Test-Path $distDir)) {
    throw "Desktop build output was not found: $distDir`nRun scripts\build_desktop.ps1 first."
}

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment was not found: $pythonExe"
}

if (-not (Test-Path $distributionReadmePath)) {
    throw "Distribution README was not found: $distributionReadmePath"
}

if (-not $IsccPath) {
    $candidates = @(
        (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    $IsccPath = $candidates | Select-Object -First 1
}

if (-not $IsccPath) {
    throw "Inno Setup compiler (ISCC.exe) was not found."
}

$version = (& $pythonExe -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()

Set-Location $repoRoot
Copy-Item -Path $distributionReadmePath -Destination (Join-Path $distDir "README.txt") -Force
$env:APP_VERSION = $version
& $IsccPath $issPath

Write-Host ""
Write-Host "Installer build completed."
Write-Host "Output: $repoRoot\dist\installer"
