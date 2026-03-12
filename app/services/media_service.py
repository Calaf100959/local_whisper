from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from app.core.settings import Settings, get_settings


class UploadFileLike(Protocol):
    filename: str | None

    async def read(self) -> bytes: ...

    async def close(self) -> None: ...


class InputType(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"
    YOUTUBE_URL = "youtube_url"


class MediaService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def get_extension(self, file_name: str | Path) -> str:
        return Path(file_name).suffix.lower()

    def is_supported_audio(self, file_name: str | Path) -> bool:
        return self.get_extension(file_name) in self.settings.supported_audio_extensions

    def is_supported_video(self, file_name: str | Path) -> bool:
        return self.get_extension(file_name) in self.settings.supported_video_extensions

    def classify_file_type(self, file_name: str | Path) -> InputType:
        if self.is_supported_audio(file_name):
            return InputType.AUDIO
        if self.is_supported_video(file_name):
            return InputType.VIDEO
        raise ValueError(f"Unsupported file extension: {self.get_extension(file_name)}")

    def validate_local_file(self, file_path: str | Path) -> tuple[InputType, Path]:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {path}")
        return self.classify_file_type(path.name), path

    def validate_youtube_url(self, url: str) -> str:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower()

        if parsed.scheme not in {"http", "https"}:
            raise ValueError("URL must start with http or https.")
        if host not in self.settings.supported_youtube_hosts:
            raise ValueError("Only YouTube URLs are supported.")

        if host == "youtu.be":
            if not parsed.path.strip("/"):
                raise ValueError("Short YouTube URL is missing a video id.")
            return url.strip()

        if parsed.path == "/watch":
            query = parse_qs(parsed.query)
            if not query.get("v", [""])[0]:
                raise ValueError("YouTube watch URL is missing a video id.")
            return url.strip()

        if parsed.path.startswith(("/shorts/", "/live/")):
            if len(parsed.path.strip("/").split("/")) < 2:
                raise ValueError("YouTube URL is missing a video id.")
            return url.strip()

        raise ValueError("Unsupported YouTube URL format.")

    def classify_input(self, source: str | Path) -> InputType:
        source_str = str(source).strip()
        if source_str.startswith(("http://", "https://")):
            self.validate_youtube_url(source_str)
            return InputType.YOUTUBE_URL
        return self.classify_file_type(source_str)

    async def save_upload_file(self, upload_file: UploadFileLike, destination_dir: Path | None = None) -> Path:
        if not upload_file.filename:
            raise ValueError("Uploaded file name is missing.")

        input_type = self.classify_file_type(upload_file.filename)
        target_directory = destination_dir or self.settings.temp_dir
        target_directory.mkdir(parents=True, exist_ok=True)

        safe_name = Path(upload_file.filename).name
        destination = self._create_unique_destination(target_directory, safe_name)
        contents = await upload_file.read()
        destination.write_bytes(contents)
        await upload_file.close()

        if input_type not in {InputType.AUDIO, InputType.VIDEO}:
            raise ValueError("Unsupported uploaded file type.")

        return destination

    def _create_unique_destination(self, directory: Path, file_name: str) -> Path:
        candidate = directory / file_name
        if not candidate.exists():
            return candidate

        stem = Path(file_name).stem
        suffix = Path(file_name).suffix
        index = 1
        while True:
            candidate = directory / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1
