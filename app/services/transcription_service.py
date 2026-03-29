from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Iterable

from app.core.logging import get_logger
from app.core.runtime import is_frozen_app
from app.core.settings import Settings, get_settings
from app.models.job import JobStatus
from app.models.whisper_model import WhisperModelSpec
from app.services.chunk_service import ChunkSegment
from app.services.job_service import JobService


class TranscriptionError(RuntimeError):
    """Raised when Whisper transcription fails."""


class TranscriptionCancelled(RuntimeError):
    def __init__(self, partial_result: "TranscriptionResult") -> None:
        super().__init__("Transcription was cancelled.")
        self.partial_result = partial_result


class ModelDownloadRequired(TranscriptionError):
    def __init__(self, model_spec: WhisperModelSpec) -> None:
        super().__init__(f"Download required for model '{model_spec.model_id}'.")
        self.model_spec = model_spec


logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class TranscribedSegment:
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None


@dataclass(slots=True, frozen=True)
class TranscriptionResult:
    text: str
    segments: list[TranscribedSegment]
    language: str | None = None

    def render_text(self, *, include_speakers: bool = False) -> str:
        lines: list[str] = []
        for segment in self.segments:
            text = segment.text.strip()
            if not text:
                continue
            if include_speakers and segment.speaker:
                lines.append(f"[{segment.speaker}] {text}")
            else:
                lines.append(text)
        return "\n".join(lines)


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
        requested_model_size = self.settings.normalize_model_size(model_size)
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
        except ModelDownloadRequired:
            raise
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
        total_duration_seconds: float | None = None,
    ) -> TranscriptionResult:
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"Source audio file not found: {path}")

        if job_id:
            self.job_service.update_status(job_id, JobStatus.TRANSCRIBING)
            self._raise_if_cancel_requested(job_id)

        model = self.load_model(model_size)
        raw_segments, info = self._collect_segments(
            model,
            path,
            model_size=model_size,
            language=language,
            job_id=job_id,
            total_duration_seconds=total_duration_seconds,
            current_chunk=1,
            total_chunks=1,
            offset_seconds=0.0,
            overlap_before_seconds=0.0,
            max_processed_seconds=total_duration_seconds,
            check_cancel_during_collection=True,
        )
        result = self._build_result(raw_segments, language=getattr(info, "language", None))

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
        total_duration_seconds: float | None = None,
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

            raw_segments, info = self._collect_segments(
                model,
                chunk_input.path,
                model_size=model_size,
                language=language,
                job_id=job_id,
                total_duration_seconds=total_duration_seconds,
                current_chunk=index,
                total_chunks=total_chunks,
                offset_seconds=chunk_input.chunk.offset_seconds,
                overlap_before_seconds=chunk_input.chunk.overlap_before_seconds,
                max_processed_seconds=chunk_input.chunk.offset_seconds
                + (
                    chunk_input.chunk.duration_seconds
                    - chunk_input.chunk.overlap_before_seconds
                    - chunk_input.chunk.overlap_after_seconds
                ),
                check_cancel_during_collection=False,
            )
            detected_language = detected_language or getattr(info, "language", None)
            adjusted_segments = self._adjust_segments(raw_segments, chunk_input.chunk.offset_seconds)
            merged_segments.extend(adjusted_segments)
            if job_id:
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
        text = TranscriptionResult(text="", segments=ordered_segments, language=language).render_text()
        return TranscriptionResult(text=text, segments=ordered_segments, language=language)

    def _run_transcription(
        self,
        model: Any,
        source_path: Path,
        *,
        model_size: str | None = None,
        language: str | None = None,
    ) -> tuple[Iterable[Any], Any]:
        model_spec = self.settings.get_whisper_model_spec(model_size)
        try:
            segments, info = model.transcribe(
                str(source_path),
                language=language,
                condition_on_previous_text=model_spec.condition_on_previous_text,
            )
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Transcription failed: source=%s language=%s", source_path, language)
            raise TranscriptionError(f"Transcription failed for '{source_path.name}'.") from exc

        return segments, info

    def _collect_segments(
        self,
        model: Any,
        source_path: Path,
        *,
        model_size: str | None = None,
        language: str | None = None,
        job_id: str | None = None,
        total_duration_seconds: float | None = None,
        current_chunk: int | None = None,
        total_chunks: int | None = None,
        offset_seconds: float = 0.0,
        overlap_before_seconds: float = 0.0,
        max_processed_seconds: float | None = None,
        check_cancel_during_collection: bool = True,
    ) -> tuple[list[Any], Any]:
        raw_segments_iterable, info = self._run_transcription(
            model,
            source_path,
            model_size=model_size,
            language=language,
        )
        effective_total_seconds = self._resolve_total_duration_seconds(total_duration_seconds, info)
        raw_segments: list[Any] = []

        if job_id and effective_total_seconds:
            self.job_service.update_progress(
                job_id,
                progress_percent=0,
                current_chunk=current_chunk,
                total_chunks=total_chunks,
                processed_seconds=min(offset_seconds, effective_total_seconds),
                total_seconds=effective_total_seconds,
            )

        for segment in raw_segments_iterable:
            raw_segments.append(segment)

            if not job_id or not effective_total_seconds:
                continue

            processed_seconds = self._calculate_processed_seconds(
                segment_end_seconds=float(getattr(segment, "end", 0.0)),
                offset_seconds=offset_seconds,
                overlap_before_seconds=overlap_before_seconds,
                effective_total_seconds=effective_total_seconds,
                max_processed_seconds=max_processed_seconds,
            )
            progress_percent = self._calculate_progress_percent(processed_seconds, effective_total_seconds)
            self.job_service.update_progress(
                job_id,
                progress_percent=progress_percent,
                current_chunk=current_chunk,
                total_chunks=total_chunks,
                processed_seconds=processed_seconds,
                total_seconds=effective_total_seconds,
            )
            if check_cancel_during_collection:
                self._raise_if_cancel_requested(
                    job_id,
                    partial_result=self._build_result(raw_segments, language=getattr(info, "language", None)),
                )

        if job_id and effective_total_seconds and raw_segments:
            final_processed_seconds = self._calculate_processed_seconds(
                segment_end_seconds=float(getattr(raw_segments[-1], "end", 0.0)),
                offset_seconds=offset_seconds,
                overlap_before_seconds=overlap_before_seconds,
                effective_total_seconds=effective_total_seconds,
                max_processed_seconds=max_processed_seconds,
            )
            self.job_service.update_progress(
                job_id,
                progress_percent=self._calculate_progress_percent(final_processed_seconds, effective_total_seconds),
                current_chunk=current_chunk,
                total_chunks=total_chunks,
                processed_seconds=final_processed_seconds,
                total_seconds=effective_total_seconds,
            )

        return raw_segments, info

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

    @staticmethod
    def _resolve_total_duration_seconds(total_duration_seconds: float | None, info: Any) -> float | None:
        if total_duration_seconds and total_duration_seconds > 0:
            return float(total_duration_seconds)

        info_duration = getattr(info, "duration", None)
        if info_duration and float(info_duration) > 0:
            return float(info_duration)

        return None

    @staticmethod
    def _calculate_progress_percent(processed_seconds: float, total_seconds: float) -> int:
        if total_seconds <= 0:
            return 0
        ratio = min(max(processed_seconds / total_seconds, 0.0), 1.0)
        return int(ratio * 100)

    @staticmethod
    def _calculate_processed_seconds(
        *,
        segment_end_seconds: float,
        offset_seconds: float,
        overlap_before_seconds: float,
        effective_total_seconds: float,
        max_processed_seconds: float | None,
    ) -> float:
        non_overlap_seconds = max(0.0, segment_end_seconds - overlap_before_seconds)
        processed_seconds = max(offset_seconds, offset_seconds + non_overlap_seconds)
        if max_processed_seconds is not None:
            processed_seconds = min(processed_seconds, max_processed_seconds)
        return min(processed_seconds, effective_total_seconds)

    def _raise_if_cancel_requested(
        self,
        job_id: str,
        *,
        partial_result: TranscriptionResult | None = None,
    ) -> None:
        if not self.job_service.is_cancellation_requested(job_id):
            return

        raise TranscriptionCancelled(partial_result or TranscriptionResult(text="", segments=[]))

    def resolve_model_source(self, model_size: str | None) -> str:
        return self._resolve_model_source(model_size)

    def _resolve_model_source(self, model_size: str | None) -> str:
        model_spec = self.settings.get_whisper_model_spec(model_size)
        bundled_model_path = self.settings.bundled_model_path(model_spec.model_id)
        if self._is_ready_model_directory(bundled_model_path, model_spec):
            return str(bundled_model_path)
        downloaded_model_path = self.settings.downloaded_model_path(model_spec.model_id)
        if self._is_ready_model_directory(downloaded_model_path, model_spec):
            return str(downloaded_model_path)
        if model_spec.downloadable:
            raise ModelDownloadRequired(model_spec)
        if is_frozen_app():
            raise TranscriptionError(f"Bundled Whisper model '{model_spec.model_id}' was not found.")
        return model_spec.model_id

    @staticmethod
    def _is_ready_model_directory(path: Path, model_spec: WhisperModelSpec) -> bool:
        if not path.is_dir():
            return False
        return all((path / required_file).exists() for required_file in model_spec.required_files)
