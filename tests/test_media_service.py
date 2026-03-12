from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.services.media_service import InputType, MediaService


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content

    async def close(self) -> None:
        return None


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "data" / "jobs",
        outputs_dir=tmp_path / "data" / "outputs",
        temp_dir=tmp_path / "data" / "temp",
    )


def test_media_service_classifies_file_types_and_url(tmp_path: Path) -> None:
    service = MediaService(build_settings(tmp_path))

    assert service.classify_file_type("sample.mp3") == InputType.AUDIO
    assert service.classify_file_type("movie.mp4") == InputType.VIDEO
    assert service.classify_input("https://www.youtube.com/watch?v=abc123") == InputType.YOUTUBE_URL

    with pytest.raises(ValueError):
        service.classify_file_type("notes.txt")

    with pytest.raises(ValueError):
        service.validate_youtube_url("https://example.com/watch?v=abc123")


def test_media_service_validates_local_file_and_saves_upload(tmp_path: Path) -> None:
    service = MediaService(build_settings(tmp_path))
    local_file = tmp_path / "sample.wav"
    local_file.write_bytes(b"audio")

    input_type, resolved_path = service.validate_local_file(local_file)

    assert input_type == InputType.AUDIO
    assert resolved_path == local_file

    upload = FakeUploadFile(filename="upload.wav", content=b"hello")
    saved_path = asyncio.run(service.save_upload_file(upload))

    assert saved_path.exists()
    assert saved_path.read_bytes() == b"hello"


def test_media_service_missing_local_file_raises(tmp_path: Path) -> None:
    service = MediaService(build_settings(tmp_path))

    with pytest.raises(FileNotFoundError):
        service.validate_local_file(tmp_path / "missing.wav")
