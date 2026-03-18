from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path

from app.core.settings import Settings, get_settings
from app.services.transcription_service import TranscriptionResult


class OutputFormat(StrEnum):
    TXT = "txt"
    SRT = "srt"
    JSON = "json"

    @classmethod
    def from_file_name(cls, file_name: str, selected_filter: str | None = None) -> "OutputFormat":
        suffix = Path(file_name).suffix.lower().lstrip(".")
        if suffix in {member.value for member in cls}:
            return cls(suffix)
        if selected_filter:
            if "*.srt" in selected_filter:
                return cls.SRT
            if "*.json" in selected_filter:
                return cls.JSON
        return cls.TXT


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
        output_path.write_text(result.render_text(include_speakers=True), encoding="utf-8")
        return output_path

    def save_srt_result(
        self,
        *,
        job_id: str,
        source_name: str,
        result: TranscriptionResult,
    ) -> Path:
        output_path = self.build_output_path(
            job_id=job_id,
            source_name=source_name,
            output_format=OutputFormat.SRT,
        )
        output_path.write_text(self._build_srt_text(result), encoding="utf-8")
        return output_path

    def save_json_result(
        self,
        *,
        job_id: str,
        source_name: str,
        result: TranscriptionResult,
    ) -> Path:
        output_path = self.build_output_path(
            job_id=job_id,
            source_name=source_name,
            output_format=OutputFormat.JSON,
        )
        payload = {
            "text": result.text,
            "language": result.language,
            "segments": [
                {
                    "start_seconds": segment.start_seconds,
                    "end_seconds": segment.end_seconds,
                    "speaker": segment.speaker,
                    "text": segment.text,
                }
                for segment in result.segments
            ],
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def save_all_results(
        self,
        *,
        job_id: str,
        source_name: str,
        result: TranscriptionResult,
    ) -> dict[OutputFormat, Path]:
        return {
            OutputFormat.TXT: self.save_text_result(job_id=job_id, source_name=source_name, result=result),
            OutputFormat.SRT: self.save_srt_result(job_id=job_id, source_name=source_name, result=result),
            OutputFormat.JSON: self.save_json_result(job_id=job_id, source_name=source_name, result=result),
        }

    def build_output_path(
        self,
        *,
        job_id: str,
        source_name: str,
        output_format: OutputFormat,
    ) -> Path:
        output_dir = self.build_output_directory(job_id=job_id, source_name=source_name)
        file_name = f"{output_dir.name}.{output_format.value}"
        return output_dir / file_name

    def build_output_directory(self, *, job_id: str, source_name: str) -> Path:
        safe_stem = self._sanitize_file_stem(source_name)
        output_dir = self.settings.outputs_dir / f"{safe_stem}_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _sanitize_file_stem(self, source_name: str) -> str:
        raw_stem = Path(source_name).stem.strip() or "transcript"
        normalized = re.sub(r"[^\w\-]+", "_", raw_stem, flags=re.ASCII)
        normalized = re.sub(r"_+", "_", normalized).strip("._")
        return normalized or "transcript"

    def _build_srt_text(self, result: TranscriptionResult) -> str:
        lines: list[str] = []
        for index, segment in enumerate(result.segments, start=1):
            text = segment.text.strip()
            if not text:
                continue
            if segment.speaker:
                text = f"[{segment.speaker}] {text}"
            lines.extend(
                [
                    str(index),
                    f"{self._format_srt_timestamp(segment.start_seconds)} --> {self._format_srt_timestamp(segment.end_seconds)}",
                    text,
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + ("\n" if lines else "")

    @staticmethod
    def _format_srt_timestamp(total_seconds: float) -> str:
        bounded = max(0.0, total_seconds)
        total_milliseconds = round(bounded * 1000)
        hours, remainder = divmod(total_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
