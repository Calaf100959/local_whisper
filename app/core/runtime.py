from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Local Whisper Transcriber"
APP_SLUG = "local-whisper-transcriber"


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_bundle_root() -> Path:
    if is_frozen_app():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return get_project_root()


def get_install_root() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return get_project_root()


def get_resource_root() -> Path:
    return get_bundle_root() / "resources"


def get_user_data_root() -> Path:
    if not is_frozen_app():
        return get_project_root() / "data"

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_SLUG / "data"

    return Path.home() / "AppData" / "Local" / APP_SLUG / "data"
