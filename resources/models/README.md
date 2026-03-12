Place bundled Whisper model directories here before building the installer.

Required directory for the current default configuration:
- small

The model files are intentionally excluded from GitHub. Download them with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download_bundle_assets.ps1
```

After download, `resources/models/small` must contain the Faster-Whisper
model files, including `model.bin`.
