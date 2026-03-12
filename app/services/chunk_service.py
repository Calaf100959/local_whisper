from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from app.core.settings import Settings, get_settings


@dataclass(slots=True, frozen=True)
class ChunkSegment:
    index: int
    start_time_seconds: float
    end_time_seconds: float
    offset_seconds: float
    overlap_before_seconds: float
    overlap_after_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_time_seconds - self.start_time_seconds


class ChunkService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def is_long_form(self, total_duration_seconds: float) -> bool:
        self._validate_duration(total_duration_seconds)
        return total_duration_seconds >= self.settings.long_form_threshold_seconds

    def create_chunks(self, total_duration_seconds: float) -> list[ChunkSegment]:
        self._validate_duration(total_duration_seconds)

        if not self.is_long_form(total_duration_seconds):
            return [
                ChunkSegment(
                    index=1,
                    start_time_seconds=0.0,
                    end_time_seconds=total_duration_seconds,
                    offset_seconds=0.0,
                    overlap_before_seconds=0.0,
                    overlap_after_seconds=0.0,
                )
            ]

        chunk_size = float(self.settings.chunk_duration_seconds)
        overlap = float(self.settings.chunk_overlap_seconds)
        chunk_count = math.ceil(total_duration_seconds / chunk_size)
        chunks: list[ChunkSegment] = []

        for chunk_index in range(chunk_count):
            base_start = chunk_index * chunk_size
            base_end = min((chunk_index + 1) * chunk_size, total_duration_seconds)
            actual_start = max(0.0, base_start - overlap)
            actual_end = min(total_duration_seconds, base_end + overlap)

            chunks.append(
                ChunkSegment(
                    index=chunk_index + 1,
                    start_time_seconds=actual_start,
                    end_time_seconds=actual_end,
                    offset_seconds=base_start,
                    overlap_before_seconds=base_start - actual_start,
                    overlap_after_seconds=actual_end - base_end,
                )
            )

        return chunks

    def build_chunk_path(
        self,
        source_path: str | Path,
        *,
        chunk_index: int,
        output_dir: Path | None = None,
    ) -> Path:
        source = Path(source_path)
        target_directory = output_dir or self.settings.temp_dir
        target_directory.mkdir(parents=True, exist_ok=True)
        return target_directory / f"{source.stem}_chunk_{chunk_index:04d}{source.suffix}"

    @staticmethod
    def _validate_duration(total_duration_seconds: float) -> None:
        if total_duration_seconds <= 0:
            raise ValueError("Duration must be greater than zero.")
