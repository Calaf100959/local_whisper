param(
    [string]$IsccPath
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$issPath = Join-Path $repoRoot "packaging\local-whisper.iss"
$distDir = Join-Path $repoRoot "dist\LocalWhisperTranscriber"
$distributionReadmePath = Join-Path $repoRoot "packaging\README.txt"
$eulaPath = Join-Path $repoRoot "packaging\EULA.txt"
$thirdPartyNoticesPath = Join-Path $repoRoot "packaging\THIRD_PARTY_LICENSES.txt"
$licenseDirectoryPath = Join-Path $repoRoot "packaging\licenses"

if (-not (Test-Path $distDir)) {
    throw "Desktop build output was not found: $distDir`nRun scripts\build_desktop.ps1 first."
}

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment was not found: $pythonExe"
}

if (-not (Test-Path $distributionReadmePath)) {
    throw "Distribution README was not found: $distributionReadmePath"
}

if (-not (Test-Path $eulaPath)) {
    throw "Installer EULA was not found: $eulaPath"
}

if (-not (Test-Path $thirdPartyNoticesPath)) {
    throw "Third-party notices file was not found: $thirdPartyNoticesPath"
}

if (-not (Test-Path $licenseDirectoryPath)) {
    throw "License directory was not found: $licenseDirectoryPath"
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
$distLicenseDirectoryPath = Join-Path $distDir "licenses"
Copy-Item -Path $distributionReadmePath -Destination (Join-Path $distDir "README.txt") -Force
Copy-Item -Path $eulaPath -Destination (Join-Path $distDir "EULA.txt") -Force
Copy-Item -Path $thirdPartyNoticesPath -Destination (Join-Path $distDir "THIRD_PARTY_LICENSES.txt") -Force
if (Test-Path $distLicenseDirectoryPath) {
    Remove-Item -Path $distLicenseDirectoryPath -Recurse -Force
}
Copy-Item -Path $licenseDirectoryPath -Destination $distLicenseDirectoryPath -Recurse -Force
$env:APP_VERSION = $version
& $IsccPath $issPath

Write-Host ""
Write-Host "Installer build completed."
Write-Host "Output: $repoRoot\dist\installer"
