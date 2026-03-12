# Windows Distribution Guide

## Goal
Windows 用 installer に以下を同梱して配布します。
- デスクトップアプリ本体
- Python runtime
- `ffmpeg.exe`
- `ffprobe.exe`
- `yt-dlp.exe`
- Whisper `small` モデル

## Repository policy
GitHub には以下の実体を含めません。
- `dist/`
- `build/`
- `data/`
- `resources/bin/*.exe`
- `resources/models/small/*`

必要な外部資材はビルド前に取得します。

## Asset preparation
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -e .[dev]
powershell -ExecutionPolicy Bypass -File scripts\download_bundle_assets.ps1
```

取得後の配置:
- `resources/bin/ffmpeg.exe`
- `resources/bin/ffprobe.exe`
- `resources/bin/yt-dlp.exe`
- `resources/models/small/model.bin`

## Build steps
デスクトップ配布物の作成:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
```

installer の作成:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
```

出力:
- `dist/LocalWhisperTranscriber`
- `dist/installer/LocalWhisperSetup-<version>-x64.exe`

## Runtime paths after install
- アプリ本体と同梱バイナリ: インストール先
- ジョブ情報、一時ファイル、出力、ログ:
  `%LOCALAPPDATA%\local-whisper-transcriber`
