from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.models.job import JobStatus
from app.services.chunk_service import ChunkSegment
from app.services.job_service import JobService


class TranscriptionError(RuntimeError):
    """Raised when Whisper transcription fails."""


class TranscriptionCancelled(RuntimeError):
    def __init__(self, partial_result: "TranscriptionResult") -> None:
        super().__init__("Transcription was cancelled.")
        self.partial_result = partial_result


logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class TranscribedSegment:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(slots=True, frozen=True)
class TranscriptionResult:
    text: str
    segments: list[TranscribedSegment]
    language: str | None = None


@dataclass(slots=True, frozen=True)
class ChunkTranscriptionInput:
    path: Path
    chunk: ChunkSegment


class TranscriptionService:
    def __init__(
        self,
        settings: Settings | None = None,
        job_service: JobService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.job_service = job_service or JobService(self.settings)
        self._model_cache: dict[str, Any] = {}

    def load_model(self, model_size: str | None = None) -> Any:
        requested_model_size = model_size or self.settings.default_model_size
        if requested_model_size in self._model_cache:
            return self._model_cache[requested_model_size]

        try:
            faster_whisper = import_module("faster_whisper")
        except ModuleNotFoundError as exc:
            logger.exception("faster-whisper import failed")
            raise TranscriptionError(
                "faster-whisper is not installed. Install dependencies before running transcription."
            ) from exc

        try:
            model = faster_whisper.WhisperModel(
                self._resolve_model_source(requested_model_size),
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute_type,
            )
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Whisper model load failed: model_size=%s", requested_model_size)
            raise TranscriptionError(f"Failed to load Whisper model '{requested_model_size}'.") from exc

        self._model_cache[requested_model_size] = model
        return model

    def transcribe_file(
        self,
        source_path: str | Path,
        *,
        model_size: str | None = None,
        language: str | None = None,
        job_id: str | None = None,
    ) -> TranscriptionResult:
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"Source audio file not found: {path}")

        if job_id:
            self.job_service.update_status(job_id, JobStatus.TRANSCRIBING)
            self._raise_if_cancel_requested(job_id)

        model = self.load_model(model_size)
        segments, info = self._run_transcription(model, path, language=language)
        result = self._build_result(segments, language=getattr(info, "language", None))

        if job_id:
            self._raise_if_cancel_requested(job_id, partial_result=result)

        return result

    def transcribe_chunks(
        self,
        chunks: list[ChunkTranscriptionInput],
        *,
        model_size: str | None = None,
        language: str | None = None,
        job_id: str | None = None,
    ) -> TranscriptionResult:
        if not chunks:
            raise ValueError("At least one chunk is required for transcription.")

        model = self.load_model(model_size)
        merged_segments: list[TranscribedSegment] = []
        detected_language: str | None = None
        total_chunks = len(chunks)

        if job_id:
            self.job_service.update_status(job_id, JobStatus.TRANSCRIBING)
            self._raise_if_cancel_requested(job_id)

        for index, chunk_input in enumerate(chunks, start=1):
            if job_id:
                self._raise_if_cancel_requested(
                    job_id,
                    partial_result=self.merge_transcriptions(merged_segments, language=detected_language),
                )
            if not chunk_input.path.exists():
                raise FileNotFoundError(f"Chunk audio file not found: {chunk_input.path}")

            raw_segments, info = self._run_transcription(model, chunk_input.path, language=language)
            detected_language = detected_language or getattr(info, "language", None)
            adjusted_segments = self._adjust_segments(raw_segments, chunk_input.chunk.offset_seconds)
            merged_segments.extend(adjusted_segments)

            if job_id:
                progress_percent = int(index / total_chunks * 100)
                self.job_service.update_progress(
                    job_id,
                    progress_percent=progress_percent,
                    current_chunk=index,
                    total_chunks=total_chunks,
                )
                self._raise_if_cancel_requested(
                    job_id,
                    partial_result=self.merge_transcriptions(merged_segments, language=detected_language),
                )

        return self.merge_transcriptions(merged_segments, language=detected_language)

    def merge_transcriptions(
        self,
        segments: list[TranscribedSegment],
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        ordered_segments = sorted(segments, key=lambda item: (item.start_seconds, item.end_seconds))
        text = "\n".join(segment.text.strip() for segment in ordered_segments if segment.text.strip())
        return TranscriptionResult(text=text, segments=ordered_segments, language=language)

    def _run_transcription(
        self,
        model: Any,
        source_path: Path,
        *,
        language: str | None = None,
    ) -> tuple[list[Any], Any]:
        try:
            segments, info = model.transcribe(
                str(source_path),
                language=language,
            )
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Transcription failed: source=%s language=%s", source_path, language)
            raise TranscriptionError(f"Transcription failed for '{source_path.name}'.") from exc

        return list(segments), info

    def _build_result(
        self,
        raw_segments: list[Any],
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        segments = self._adjust_segments(raw_segments, offset_seconds=0.0)
        return self.merge_transcriptions(segments, language=language)

    @staticmethod
    def _adjust_segments(raw_segments: list[Any], offset_seconds: float) -> list[TranscribedSegment]:
        adjusted_segments: list[TranscribedSegment] = []

        for segment in raw_segments:
            adjusted_segments.append(
                TranscribedSegment(
                    start_seconds=float(getattr(segment, "start", 0.0)) + offset_seconds,
                    end_seconds=float(getattr(segment, "end", 0.0)) + offset_seconds,
                    text=str(getattr(segment, "text", "")).strip(),
                )
            )

        return adjusted_segments

    def _raise_if_cancel_requested(
        self,
        job_id: str,
        *,
        partial_result: TranscriptionResult | None = None,
    ) -> None:
        if not self.job_service.is_cancellation_requested(job_id):
            return

        raise TranscriptionCancelled(partial_result or TranscriptionResult(text="", segments=[]))

    def _resolve_model_source(self, model_size: str) -> str:
        bundled_model_path = self.settings.bundled_model_path(model_size)
        if bundled_model_path.exists():
            return str(bundled_model_path)
        return model_size
