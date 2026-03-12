param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$specPath = Join-Path $repoRoot "packaging\local-whisper.spec"
$distributionReadmePath = Join-Path $repoRoot "packaging\README.txt"

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment was not found: $pythonExe"
}

if (-not (Test-Path $specPath)) {
    throw "PyInstaller spec was not found: $specPath"
}

if (-not (Test-Path $distributionReadmePath)) {
    throw "Distribution README was not found: $distributionReadmePath"
}

$requiredAssets = @(
    (Join-Path $repoRoot "resources\bin\ffmpeg.exe"),
    (Join-Path $repoRoot "resources\bin\ffprobe.exe"),
    (Join-Path $repoRoot "resources\bin\yt-dlp.exe"),
    (Join-Path $repoRoot "resources\models\small\model.bin")
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
Copy-Item -Path $distributionReadmePath -Destination (Join-Path $distRoot "README.txt") -Force

Write-Host ""
Write-Host "Desktop build completed."
Write-Host "Output: $repoRoot\dist\LocalWhisperTranscriber"
