param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$specPath = Join-Path $repoRoot "packaging\local-whisper.spec"
$distributionReadmePath = Join-Path $repoRoot "packaging\README.txt"
$eulaPath = Join-Path $repoRoot "packaging\EULA.txt"
$thirdPartyNoticesPath = Join-Path $repoRoot "packaging\THIRD_PARTY_LICENSES.txt"
$licenseDirectoryPath = Join-Path $repoRoot "packaging\licenses"

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment was not found: $pythonExe"
}

if (-not (Test-Path $specPath)) {
    throw "PyInstaller spec was not found: $specPath"
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

$requiredAssets = @(
    (Join-Path $repoRoot "resources\bin\ffmpeg.exe"),
    (Join-Path $repoRoot "resources\bin\ffprobe.exe"),
    (Join-Path $repoRoot "resources\bin\yt-dlp.exe"),
    (Join-Path $repoRoot "resources\models\base\model.bin"),
    (Join-Path $repoRoot "resources\models\small\model.bin"),
    (Join-Path $repoRoot "resources\models\speechbrain-spkrec-ecapa-voxceleb\hyperparams.yaml")
)

foreach ($assetPath in $requiredAssets) {
    if (-not (Test-Path $assetPath)) {
        throw "Required bundled asset was not found: $assetPath"
    }
}

Set-Location $repoRoot

if (-not $SkipTests) {
    & $pythonExe -m unittest discover -s tests -p "*_unittest.py" -v
}

& $pythonExe -m PyInstaller $specPath --noconfirm --clean

$distRoot = Join-Path $repoRoot "dist\LocalWhisperTranscriber"
$distLicenseDirectoryPath = Join-Path $distRoot "licenses"
$distPyAvDirectoryPath = Join-Path $distRoot "_internal\av"
$distPyAvLibsDirectoryPath = Join-Path $distRoot "_internal\av.libs"
Copy-Item -Path $distributionReadmePath -Destination (Join-Path $distRoot "README.txt") -Force
Copy-Item -Path $eulaPath -Destination (Join-Path $distRoot "EULA.txt") -Force
Copy-Item -Path $thirdPartyNoticesPath -Destination (Join-Path $distRoot "THIRD_PARTY_LICENSES.txt") -Force
if (Test-Path $distLicenseDirectoryPath) {
    Remove-Item -Path $distLicenseDirectoryPath -Recurse -Force
}
Copy-Item -Path $licenseDirectoryPath -Destination $distLicenseDirectoryPath -Recurse -Force

if (-not (Test-Path $distPyAvLibsDirectoryPath)) {
    throw "PyAV runtime libraries were not bundled: $distPyAvLibsDirectoryPath"
}

$pyAvCoreModule = @(
    Get-ChildItem -Path $distPyAvDirectoryPath -Filter "_core*.pyd" -ErrorAction SilentlyContinue
)
if ($pyAvCoreModule.Count -eq 0) {
    throw "PyAV core extension module was not bundled under: $distPyAvDirectoryPath"
}

Write-Host ""
Write-Host "Desktop build completed."
Write-Host "Output: $repoRoot\dist\LocalWhisperTranscriber"
