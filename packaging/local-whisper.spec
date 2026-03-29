# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys
import tomllib

from PyInstaller.utils.hooks import collect_all, collect_delvewheel_libs_directory
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo,
    FixedFileInfo,
    StringFileInfo,
    StringTable,
    StringStruct,
    VarFileInfo,
    VarStruct,
)


project_root = Path.cwd()
project_version = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _normalize_windows_version(version_text: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version_text.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def _build_version_info(version_text: str):
    normalized_version = _normalize_windows_version(version_text)
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=normalized_version,
            prodvers=normalized_version,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "041104B0",
                        [
                            StringStruct("CompanyName", "ローカル文字起こしデスクトップアプリ"),
                            StringStruct("FileDescription", "Local Whisper Transcriber"),
                            StringStruct("FileVersion", version_text),
                            StringStruct("InternalName", "Local Whisper Transcriber"),
                            StringStruct("OriginalFilename", "Local Whisper Transcriber.exe"),
                            StringStruct("ProductName", "ローカル文字起こしデスクトップアプリ"),
                            StringStruct("ProductVersion", version_text),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1041, 1200])]),
        ],
    )


def _collect_pyav_extension_modules():
    try:
        import av
    except Exception:
        return []

    package_root = Path(av.__file__).resolve().parent
    collected = []
    for extension_module in package_root.rglob("*.pyd"):
        destination = Path("av") / extension_module.relative_to(package_root).parent
        collected.append((str(extension_module), str(destination)))
    return collected


def _dedupe_pairs(items):
    return list(dict.fromkeys(items))


def _dedupe_strings(items):
    return list(dict.fromkeys(items))

datas = [
    (str(project_root / "resources" / "bin"), "resources/bin"),
    (str(project_root / "resources" / "models" / "README.md"), "resources/models"),
    (str(project_root / "resources" / "models" / "base"), "resources/models/base"),
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
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
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

try:
    pyav_delvewheel_datas, pyav_delvewheel_binaries = collect_delvewheel_libs_directory("av")
    datas += pyav_delvewheel_datas
    binaries += pyav_delvewheel_binaries
except Exception:
    pass

binaries += _collect_pyav_extension_modules()
datas = _dedupe_pairs(datas)
binaries = _dedupe_pairs(binaries)
hiddenimports = _dedupe_strings(hiddenimports)


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
    version=_build_version_info(project_version),
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
