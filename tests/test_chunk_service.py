from __future__ import annotations

from pathlib import Path

import pytest

from app.core.settings import Settings
from app.services.chunk_service import ChunkService


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "data" / "jobs",
        outputs_dir=tmp_path / "data" / "outputs",
        temp_dir=tmp_path / "data" / "temp",
    )


def test_chunk_service_short_media_returns_single_chunk(tmp_path: Path) -> None:
    service = ChunkService(build_settings(tmp_path))

    chunks = service.create_chunks(120.0)

    assert len(chunks) == 1
    assert chunks[0].start_time_seconds == 0.0
    assert chunks[0].end_time_seconds == 120.0
    assert chunks[0].duration_seconds == 120.0


def test_chunk_service_long_media_returns_overlapping_chunks(tmp_path: Path) -> None:
    service = ChunkService(build_settings(tmp_path))

    chunks = service.create_chunks(18000.0)

    assert len(chunks) == 30
    assert chunks[0].end_time_seconds == 602.0
    assert chunks[1].start_time_seconds == 598.0
    assert chunks[1].offset_seconds == 600.0
    assert chunks[-1].end_time_seconds == 18000.0

    chunk_path = service.build_chunk_path("meeting.wav", chunk_index=3)
    assert chunk_path.name == "meeting_chunk_0003.wav"


def test_chunk_service_invalid_duration_raises(tmp_path: Path) -> None:
    service = ChunkService(build_settings(tmp_path))

    with pytest.raises(ValueError):
        service.create_chunks(0.0)
