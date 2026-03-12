Place bundled Windows command-line tools here before building the installer.

Required files:
- ffmpeg.exe
- ffprobe.exe
- yt-dlp.exe

These binaries are intentionally excluded from GitHub. Download them with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download_bundle_assets.ps1
```
