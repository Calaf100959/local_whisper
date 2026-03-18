# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all


project_root = Path.cwd()

datas = [
    (str(project_root / "resources" / "bin"), "resources/bin"),
    (str(project_root / "resources" / "models" / "README.md"), "resources/models"),
    (str(project_root / "resources" / "models" / "small"), "resources/models/small"),
    (
        str(project_root / "resources" / "models" / "speechbrain-spkrec-ecapa-voxceleb"),
        "resources/models/speechbrain-spkrec-ecapa-voxceleb",
    ),
]
binaries = []
hiddenimports = [
    "logging.config",
    "logging.handlers",
]

try:
    import torchaudio

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["ffmpeg"]
except Exception:
    pass

conda_library_bin = Path(sys.base_prefix) / "Library" / "bin"
for dll_name in (
    "ffi.dll",
    "libbz2.dll",
    "libcrypto-3-x64.dll",
    "libexpat.dll",
    "liblzma.dll",
    "libmpdec-4.dll",
    "libssl-3-x64.dll",
    "sqlite3.dll",
):
    dll_path = conda_library_bin / dll_name
    if dll_path.exists():
        binaries.append((str(dll_path), "."))

for package_name in (
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "huggingface_hub",
    "hyperpyyaml",
    "ruamel.yaml",
    "sentencepiece",
    "silero_vad",
    "sklearn",
    "speechbrain",
    "torch",
    "torchaudio",
):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hiddenimports
    except Exception:
        continue


a = Analysis(
    [str(project_root / "app" / "desktop" / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Local Whisper Transcriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LocalWhisperTranscriber",
)
