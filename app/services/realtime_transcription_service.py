from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.services.transcription_service import TranscribedSegment, TranscriptionResult, TranscriptionService


logger = get_logger(__name__)


class RealtimeTranscriptionError(RuntimeError):
    """Raised when realtime transcription cannot continue."""


@dataclass(slots=True, frozen=True)
class RealtimeAudioFormat:
    sample_rate: int
    channel_count: int
    sample_format: str


@dataclass(slots=True, frozen=True)
class RealtimeAudioChunk:
    payload: bytes
    format: RealtimeAudioFormat


@dataclass(slots=True, frozen=True)
class RealtimeTranscriptionSnapshot:
    committed_segments: list[TranscribedSegment]
    partial_segments: list[TranscribedSegment]
    committed_text: str
    partial_text: str
    text: str
    language: str | None
    buffered_seconds: float
    committed_until_seconds: float
    is_final: bool = False


@dataclass(slots=True)
class _BufferChunk:
    samples: np.ndarray
    duration_seconds: float


@dataclass(slots=True)
class _TranscriptionOutput:
    segments: list[TranscribedSegment]
    language: str | None


class RealtimeTranscriptionService:
    def __init__(
        self,
        settings: Settings | None = None,
        transcription_service: TranscriptionService | None = None,
        *,
        model_loader: Callable[[str | None], Any] | None = None,
        transcribe_runner: Callable[[Any, np.ndarray, str | None], Any] | None = None,
        target_sample_rate: int | None = None,
        window_seconds: float = 12.0,
        lookback_seconds: float = 2.0,
        min_chunk_seconds: float = 1.5,
        transcription_interval_seconds: float = 1.0,
        max_buffer_seconds: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transcription_service = transcription_service or TranscriptionService(self.settings)
        self._model_loader = model_loader or self.transcription_service.load_model
        self._transcribe_runner = transcribe_runner or self._default_transcribe_runner
        self.target_sample_rate = target_sample_rate or self.settings.diarization_sample_rate
        self.window_seconds = max(1.0, float(window_seconds))
        self.lookback_seconds = max(0.0, float(lookback_seconds))
        self.min_chunk_seconds = max(0.0, float(min_chunk_seconds))
        self.transcription_interval_seconds = max(0.1, float(transcription_interval_seconds))
        self.max_buffer_seconds = max(
            float(max_buffer_seconds) if max_buffer_seconds is not None else self.window_seconds * 2,
            self.window_seconds,
        )
        self._model_cache: dict[str | None, Any] = {}
        self._stream_position_seconds = 0.0
        self._committed_until_seconds = 0.0
        self._buffer: list[_BufferChunk] = []
        self._buffer_duration_seconds = 0.0
        self._committed_segments: list[TranscribedSegment] = []
        self._partial_segments: list[TranscribedSegment] = []
        self._language: str | None = None
        self._last_snapshot: RealtimeTranscriptionSnapshot | None = None
        self._last_transcription_at_seconds = 0.0

    def reset(self) -> None:
        self._stream_position_seconds = 0.0
        self._committed_until_seconds = 0.0
        self._buffer.clear()
        self._buffer_duration_seconds = 0.0
        self._committed_segments.clear()
        self._partial_segments.clear()
        self._language = None
        self._last_snapshot = None
        self._last_transcription_at_seconds = 0.0

    def append_audio_chunk(
        self,
        payload: bytes,
        *,
        sample_rate: int,
        channel_count: int,
        sample_format: str | Any,
        language: str | None = None,
        model_size: str | None = None,
        force_transcribe: bool = False,
    ) -> RealtimeTranscriptionSnapshot | None:
        chunk = RealtimeAudioChunk(
            payload=payload,
            format=RealtimeAudioFormat(
                sample_rate=int(sample_rate),
                channel_count=max(1, int(channel_count)),
                sample_format=self._sample_format_name(sample_format),
            ),
        )
        self._append_chunk(chunk)

        buffered_enough = self._buffer_duration_seconds >= self.min_chunk_seconds
        reached_transcription_interval = (
            self._last_snapshot is None
            or (self._stream_position_seconds - self._last_transcription_at_seconds)
            >= self.transcription_interval_seconds
        )
        should_transcribe = force_transcribe or (buffered_enough and reached_transcription_interval)
        if not should_transcribe:
            return None

        return self.transcribe_available_audio(
            language=language,
            model_size=model_size,
            force_final=False,
        )

    def transcribe_available_audio(
        self,
        *,
        language: str | None = None,
        model_size: str | None = None,
        force_final: bool = False,
    ) -> RealtimeTranscriptionSnapshot:
        if self._buffer_duration_seconds <= 0:
            return self._build_snapshot(language=language, is_final=force_final)

        model = self._load_model(model_size)
        window_audio, window_start_seconds = self._build_transcription_window()
        if window_audio.size == 0:
            return self._build_snapshot(language=language, is_final=force_final)
        prepared_audio = self._prepare_audio_for_transcription(window_audio)

        output = self._run_transcription(model, prepared_audio, language=language)
        current_language = output.language or language or self._language
        commit_cutoff_seconds = self._stream_position_seconds if force_final else max(
            self._committed_until_seconds,
            self._stream_position_seconds - self.lookback_seconds,
        )

        committed_segments = list(self._committed_segments)
        partial_segments: list[TranscribedSegment] = []
        for segment in output.segments:
            absolute_segment = TranscribedSegment(
                start_seconds=segment.start_seconds + window_start_seconds,
                end_seconds=segment.end_seconds + window_start_seconds,
                text=segment.text,
                speaker=segment.speaker,
            )
            if absolute_segment.end_seconds <= self._committed_until_seconds:
                continue
            if force_final or absolute_segment.end_seconds <= commit_cutoff_seconds:
                committed_segments.append(absolute_segment)
                continue
            partial_segments.append(absolute_segment)

        self._committed_segments = self._merge_segments(committed_segments)
        self._partial_segments = self._merge_segments(partial_segments)
        self._committed_until_seconds = max(self._committed_until_seconds, commit_cutoff_seconds)
        self._language = current_language
        self._last_transcription_at_seconds = self._stream_position_seconds
        snapshot = self._build_snapshot(language=current_language, is_final=force_final)
        self._last_snapshot = snapshot
        return snapshot

    def finalize(
        self,
        *,
        language: str | None = None,
        model_size: str | None = None,
    ) -> RealtimeTranscriptionSnapshot:
        return self.transcribe_available_audio(language=language, model_size=model_size, force_final=True)

    def snapshot(self) -> RealtimeTranscriptionSnapshot:
        if self._last_snapshot is not None:
            return self._last_snapshot
        return self._build_snapshot(language=self._language, is_final=False)

    def _append_chunk(self, chunk: RealtimeAudioChunk) -> None:
        samples = self._decode_audio_bytes(chunk.payload, chunk.format)
        if samples.size == 0:
            return

        resampled = self._resample_mono(samples, chunk.format.sample_rate, self.target_sample_rate)
        if resampled.size == 0:
            return

        self._buffer.append(
            _BufferChunk(
                samples=resampled,
                duration_seconds=float(resampled.size) / float(self.target_sample_rate),
            )
        )
        self._buffer_duration_seconds += float(resampled.size) / float(self.target_sample_rate)
        self._stream_position_seconds += float(resampled.size) / float(self.target_sample_rate)
        self._trim_buffer()

    def _build_transcription_window(self) -> tuple[np.ndarray, float]:
        if not self._buffer:
            return np.array([], dtype=np.float32), max(0.0, self._stream_position_seconds)

        audio = np.concatenate([chunk.samples for chunk in self._buffer]).astype(np.float32, copy=False)
        window_samples = int(round(self.window_seconds * self.target_sample_rate))
        if audio.size > window_samples:
            audio = audio[-window_samples:]
        window_start_seconds = self._stream_position_seconds - (audio.size / float(self.target_sample_rate))
        return audio, max(0.0, window_start_seconds)

    def _build_snapshot(self, *, language: str | None, is_final: bool) -> RealtimeTranscriptionSnapshot:
        committed_text = self._render_segments(self._committed_segments)
        partial_text = self._render_segments(self._partial_segments)
        if is_final and self._partial_segments:
            committed_segments = self._merge_segments(self._committed_segments + self._partial_segments)
            committed_text = self._render_segments(committed_segments)
            partial_text = ""
        else:
            committed_segments = list(self._committed_segments)

        text = committed_text if not partial_text else "\n".join([committed_text, partial_text]).strip()
        return RealtimeTranscriptionSnapshot(
            committed_segments=committed_segments,
            partial_segments=list(self._partial_segments if not is_final else []),
            committed_text=committed_text,
            partial_text=partial_text,
            text=text,
            language=language or self._language,
            buffered_seconds=self._buffer_duration_seconds,
            committed_until_seconds=self._committed_until_seconds,
            is_final=is_final,
        )

    def _load_model(self, model_size: str | None) -> Any:
        cache_key = self.settings.normalize_model_size(model_size) if model_size is not None else None
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]

        try:
            model = self._model_loader(model_size)
        except Exception as exc:  # pragma: no cover - dependency specific
            logger.exception("Failed to load realtime transcription model")
            raise RealtimeTranscriptionError("Failed to load realtime transcription model.") from exc

        self._model_cache[cache_key] = model
        return model

    def _run_transcription(self, model: Any, audio: np.ndarray, *, language: str | None) -> _TranscriptionOutput:
        try:
            raw_result = self._transcribe_runner(model, audio, language)
        except Exception as exc:  # pragma: no cover - dependency specific
            logger.exception("Realtime transcription failed")
            raise RealtimeTranscriptionError("Realtime transcription failed.") from exc

        return self._normalize_transcription_output(raw_result)

    def _normalize_transcription_output(self, raw_result: Any) -> _TranscriptionOutput:
        if isinstance(raw_result, TranscriptionResult):
            return _TranscriptionOutput(
                segments=list(raw_result.segments),
                language=raw_result.language,
            )

        if isinstance(raw_result, tuple) and len(raw_result) == 2:
            segments, info = raw_result
            normalized_segments = self._normalize_segments(segments)
            return _TranscriptionOutput(
                segments=normalized_segments,
                language=getattr(info, "language", None),
            )

        if isinstance(raw_result, Iterable) and not isinstance(raw_result, (str, bytes)):
            return _TranscriptionOutput(segments=self._normalize_segments(raw_result), language=None)

        raise RealtimeTranscriptionError(f"Unsupported realtime transcription output: {type(raw_result)!r}")

    def _normalize_segments(self, segments: Iterable[Any]) -> list[TranscribedSegment]:
        normalized: list[TranscribedSegment] = []
        for segment in segments:
            normalized.append(
                TranscribedSegment(
                    start_seconds=float(getattr(segment, "start_seconds", getattr(segment, "start", 0.0))),
                    end_seconds=float(getattr(segment, "end_seconds", getattr(segment, "end", 0.0))),
                    text=str(getattr(segment, "text", "")).strip(),
                    speaker=getattr(segment, "speaker", None),
                )
            )
        return normalized

    @staticmethod
    def _merge_segments(segments: list[TranscribedSegment]) -> list[TranscribedSegment]:
        if not segments:
            return []

        ordered = sorted(segments, key=lambda item: (item.start_seconds, item.end_seconds))
        merged: list[TranscribedSegment] = [ordered[0]]
        for segment in ordered[1:]:
            previous = merged[-1]
            if (
                segment.speaker == previous.speaker
                and segment.start_seconds <= previous.end_seconds
                and segment.text == previous.text
            ):
                merged[-1] = TranscribedSegment(
                    start_seconds=previous.start_seconds,
                    end_seconds=max(previous.end_seconds, segment.end_seconds),
                    text=previous.text,
                    speaker=previous.speaker,
                )
                continue
            merged.append(segment)
        return merged

    @staticmethod
    def _render_segments(segments: list[TranscribedSegment]) -> str:
        return TranscriptionResult(text="", segments=segments).render_text()

    def _trim_buffer(self) -> None:
        max_samples = int(round(self.max_buffer_seconds * self.target_sample_rate))
        while self._buffer and self._total_buffer_samples() > max_samples:
            overflow = self._total_buffer_samples() - max_samples
            first = self._buffer[0]
            if overflow >= first.samples.size:
                self._buffer.pop(0)
                self._buffer_duration_seconds -= first.duration_seconds
                continue

            trimmed = first.samples[overflow:]
            self._buffer[0] = _BufferChunk(
                samples=trimmed,
                duration_seconds=float(trimmed.size) / float(self.target_sample_rate),
            )
            self._buffer_duration_seconds -= float(overflow) / float(self.target_sample_rate)
            break

    def _total_buffer_samples(self) -> int:
        return sum(chunk.samples.size for chunk in self._buffer)

    @staticmethod
    def _sample_format_name(sample_format: str | Any) -> str:
        if hasattr(sample_format, "name"):
            return str(sample_format.name)
        return str(sample_format)

    @staticmethod
    def _decode_audio_bytes(payload: bytes, audio_format: RealtimeAudioFormat) -> np.ndarray:
        if not payload:
            return np.array([], dtype=np.float32)

        sample_format = audio_format.sample_format
        if sample_format == "Float":
            samples = np.frombuffer(payload, dtype=np.float32)
        elif sample_format == "Int16":
            samples = np.frombuffer(payload, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_format == "Int32":
            samples = np.frombuffer(payload, dtype=np.int32).astype(np.float32) / 2_147_483_648.0
        elif sample_format == "UInt8":
            samples = (np.frombuffer(payload, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            raise RealtimeTranscriptionError(f"Unsupported sample format: {sample_format}")

        if samples.size == 0:
            return np.array([], dtype=np.float32)

        if audio_format.channel_count > 1:
            usable = (samples.size // audio_format.channel_count) * audio_format.channel_count
            if usable == 0:
                return np.array([], dtype=np.float32)
            samples = samples[:usable].reshape(-1, audio_format.channel_count).mean(axis=1)

        return samples.astype(np.float32, copy=False).reshape(-1)

    @staticmethod
    def _resample_mono(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        if samples.size == 0:
            return np.array([], dtype=np.float32)
        if source_rate <= 0 or target_rate <= 0 or source_rate == target_rate:
            return samples.astype(np.float32, copy=False)
        if samples.size == 1:
            target_length = max(1, int(round(target_rate / float(source_rate))))
            return np.repeat(samples.astype(np.float32, copy=False), target_length)

        source_positions = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
        target_length = max(1, int(round(samples.size * float(target_rate) / float(source_rate))))
        target_positions = np.linspace(0.0, 1.0, num=target_length, endpoint=False)
        resampled = np.interp(target_positions, source_positions, samples.astype(np.float32, copy=False))
        return resampled.astype(np.float32, copy=False)

    @staticmethod
    def _prepare_audio_for_transcription(samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return np.array([], dtype=np.float32)

        prepared = samples.astype(np.float32, copy=True)
        peak = float(np.max(np.abs(prepared)))
        if peak <= 1e-6:
            return prepared

        rms = float(np.sqrt(np.mean(np.square(prepared))))
        if rms <= 1e-4:
            return prepared

        target_rms = 0.12
        max_gain = 8.0
        gain_from_rms = target_rms / rms
        gain_from_peak = 0.98 / peak
        gain = min(max_gain, gain_from_rms, gain_from_peak)
        if gain <= 1.0:
            return prepared
        return np.clip(prepared * gain, -0.98, 0.98).astype(np.float32, copy=False)

    @staticmethod
    def _default_transcribe_runner(model: Any, audio: np.ndarray, language: str | None) -> Any:
        return model.transcribe(
            audio,
            language=language,
            vad_filter=False,
            word_timestamps=False,
        )
