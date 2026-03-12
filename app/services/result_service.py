from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from app.core.settings import Settings, get_settings
from app.services.transcription_service import TranscriptionResult


class OutputFormat(StrEnum):
    TXT = "txt"
    SRT = "srt"
    JSON = "json"


class ResultService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def save_text_result(
        self,
        *,
        job_id: str,
        source_name: str,
        result: TranscriptionResult,
    ) -> Path:
        output_path = self.build_output_path(
            job_id=job_id,
            source_name=source_name,
            output_format=OutputFormat.TXT,
        )
        output_path.write_text(result.text, encoding="utf-8")
        return output_path

    def build_output_path(
        self,
        *,
        job_id: str,
        source_name: str,
        output_format: OutputFormat,
    ) -> Path:
        safe_stem = self._sanitize_file_stem(source_name)
        file_name = f"{safe_stem}_{job_id}.{output_format.value}"
        return self.settings.outputs_dir / file_name

    def _sanitize_file_stem(self, source_name: str) -> str:
        raw_stem = Path(source_name).stem.strip() or "transcript"
        normalized = re.sub(r"[^\w\-]+", "_", raw_stem, flags=re.ASCII)
        normalized = re.sub(r"_+", "_", normalized).strip("._")
        return normalized or "transcript"
