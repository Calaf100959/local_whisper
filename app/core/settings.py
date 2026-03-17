from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from os import name as os_name
from pathlib import Path

from app.core.runtime import (
    get_install_root,
    get_project_root,
    get_resource_root,
    get_user_data_root,
)


@dataclass(slots=True, frozen=True)
class Settings:
    project_root: Path = field(default_factory=get_project_root)
    install_dir: Path = field(default_factory=get_install_root)
    resource_dir: Path = field(default_factory=get_resource_root)
    data_dir: Path = field(default_factory=get_user_data_root)
    jobs_dir: Path = field(default_factory=lambda: get_user_data_root() / "jobs")
    outputs_dir: Path = field(default_factory=lambda: get_user_data_root() / "outputs")
    temp_dir: Path = field(default_factory=lambda: get_user_data_root() / "temp")
    bundled_bin_dir: Path = field(default_factory=lambda: get_resource_root() / "bin")
    bundled_models_dir: Path = field(default_factory=lambda: get_resource_root() / "models")
    supported_audio_extensions: tuple[str, ...] = (".mp3", ".wav", ".m4a")
    supported_video_extensions: tuple[str, ...] = (".mp4", ".mov", ".mkv")
    supported_youtube_hosts: tuple[str, ...] = (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
    )
    supported_model_sizes: tuple[str, ...] = ("small",)
    default_model_size: str = "small"
    default_language: str = "ja"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    chunk_duration_seconds: int = 600
    chunk_overlap_seconds: int = 2
    long_form_threshold_seconds: int = 1800
    ffmpeg_binary_name: str = "ffmpeg.exe" if os_name == "nt" else "ffmpeg"
    ffprobe_binary_name: str = "ffprobe.exe" if os_name == "nt" else "ffprobe"
    ytdlp_binary_name: str = "yt-dlp.exe" if os_name == "nt" else "yt-dlp"
    required_directories: tuple[Path, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_directories",
            (
                self.data_dir,
                self.jobs_dir,
                self.outputs_dir,
                self.temp_dir,
            ),
        )

    def ensure_directories(self) -> None:
        for directory in self.required_directories:
            directory.mkdir(parents=True, exist_ok=True)

    def bundled_binary_path(self, binary_name: str) -> Path:
        return self.bundled_bin_dir / binary_name

    def bundled_model_path(self, model_size: str) -> Path:
        return self.bundled_models_dir / self.normalize_model_size(model_size)

    def normalize_model_size(self, model_size: str | None) -> str:
        requested = (model_size or self.default_model_size).strip().lower()
        if requested not in self.supported_model_sizes:
            supported = ", ".join(self.supported_model_sizes)
            raise ValueError(f"Unsupported model size: {requested}. Supported values: {supported}")
        return requested


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
