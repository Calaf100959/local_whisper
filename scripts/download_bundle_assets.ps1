$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$resourcesBinDir = Join-Path $repoRoot "resources\bin"
$resourcesModelsDir = Join-Path $repoRoot "resources\models"
$tempDir = Join-Path $repoRoot ".tmp\bundle-assets"

$ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$ytDlpUrl = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

New-Item -ItemType Directory -Force -Path $resourcesBinDir | Out-Null
New-Item -ItemType Directory -Force -Path $resourcesModelsDir | Out-Null
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

$ffmpegZipPath = Join-Path $tempDir "ffmpeg-release-essentials.zip"
$ffmpegExtractDir = Join-Path $tempDir "ffmpeg"
$ytDlpPath = Join-Path $resourcesBinDir "yt-dlp.exe"
$modelTargetDir = Join-Path $resourcesModelsDir "small"
New-Item -ItemType Directory -Force -Path $modelTargetDir | Out-Null

Invoke-WebRequest -Uri $ffmpegUrl -OutFile $ffmpegZipPath
if (Test-Path $ffmpegExtractDir) {
    Remove-Item -Recurse -Force $ffmpegExtractDir
}
Expand-Archive -Path $ffmpegZipPath -DestinationPath $ffmpegExtractDir -Force

$ffmpegRoot = Get-ChildItem -Path $ffmpegExtractDir -Directory | Select-Object -First 1
if (-not $ffmpegRoot) {
    throw "Could not find extracted ffmpeg directory."
}

Copy-Item -Force (Join-Path $ffmpegRoot.FullName "bin\ffmpeg.exe") (Join-Path $resourcesBinDir "ffmpeg.exe")
Copy-Item -Force (Join-Path $ffmpegRoot.FullName "bin\ffprobe.exe") (Join-Path $resourcesBinDir "ffprobe.exe")

Invoke-WebRequest -Uri $ytDlpUrl -OutFile $ytDlpPath

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment was not found: $pythonExe"
}

if (-not (Test-Path (Join-Path $modelTargetDir "model.bin"))) {
    & $pythonExe -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Systran/faster-whisper-small', local_dir=r'$modelTargetDir')"
}

Write-Host ""
Write-Host "Bundled assets are ready."
Write-Host "FFmpeg binaries: $resourcesBinDir"
Write-Host "Whisper model:  $modelTargetDir"
