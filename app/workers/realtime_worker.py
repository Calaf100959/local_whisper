from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.realtime_session import RealtimeSession, RealtimeSessionStatus
from app.services.realtime_transcription_service import (
    RealtimeTranscriptionService,
    RealtimeTranscriptionSnapshot,
)
from app.services.transcription_service import TranscriptionResult


@dataclass(slots=True)
class RealtimeWorkerResult:
    session: RealtimeSession
    final_text: str = ""
    partial_text: str = ""
    transcription_result: TranscriptionResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RealtimeWorker:
    def __init__(
        self,
        *,
        transcription_service: RealtimeTranscriptionService | None = None,
    ) -> None:
        self.transcription_service = transcription_service or RealtimeTranscriptionService()
        self._session: RealtimeSession | None = None

    def run(self, session: RealtimeSession) -> RealtimeWorkerResult:
        raise NotImplementedError("Realtime transcription is not implemented yet.")

    def start(self, session: RealtimeSession) -> RealtimeWorkerResult:
        self.transcription_service.reset()
        self._session = session.with_status(RealtimeSessionStatus.LISTENING)
        return self._build_result(None)

    def append_audio_chunk(
        self,
        payload: bytes,
        *,
        sample_rate: int,
        channel_count: int,
        sample_format: str,
        language: str | None = None,
        model_size: str | None = None,
    ) -> RealtimeWorkerResult | None:
        if self._session is None:
            raise RuntimeError("Realtime session has not been started.")
        if self._session.status == RealtimeSessionStatus.PAUSED:
            return None

        snapshot = self.transcription_service.append_audio_chunk(
            payload,
            sample_rate=sample_rate,
            channel_count=channel_count,
            sample_format=sample_format,
            language=language,
            model_size=model_size,
        )
        if snapshot is None:
            return None

        self._session = self._session.with_status(RealtimeSessionStatus.LISTENING)
        return self._build_result(snapshot)

    def pause(self) -> RealtimeWorkerResult:
        if self._session is None:
            raise RuntimeError("Realtime session has not been started.")
        self._session = self._session.with_status(RealtimeSessionStatus.PAUSED)
        return self._build_result(None)

    def resume(self) -> RealtimeWorkerResult:
        if self._session is None:
            raise RuntimeError("Realtime session has not been started.")
        self._session = self._session.with_status(RealtimeSessionStatus.LISTENING)
        return self._build_result(None)

    def stop(
        self,
        *,
        language: str | None = None,
        model_size: str | None = None,
    ) -> RealtimeWorkerResult:
        if self._session is None:
            raise RuntimeError("Realtime session has not been started.")
        self._session = self._session.with_status(RealtimeSessionStatus.FINALIZING)
        snapshot = self.transcription_service.finalize(language=language, model_size=model_size)
        self._session = self._session.with_status(RealtimeSessionStatus.COMPLETED)
        return self._build_result(snapshot)

    def fail(self, error_message: str, *, error_detail: str | None = None) -> RealtimeWorkerResult:
        if self._session is None:
            raise RuntimeError("Realtime session has not been started.")
        self._session = self._session.with_error(error_message, error_detail=error_detail)
        return self._build_result(None)

    def _build_result(self, snapshot: RealtimeTranscriptionSnapshot | None) -> RealtimeWorkerResult:
        if self._session is None:
            raise RuntimeError("Realtime session has not been started.")

        if snapshot is not None:
            transcription_result = TranscriptionResult(
                text=snapshot.text,
                segments=list(snapshot.committed_segments) + list(snapshot.partial_segments),
                language=snapshot.language,
            )
            self._session = self._session.model_copy(
                update={
                    "language": snapshot.language or self._session.language,
                    "committed_text": snapshot.committed_text,
                    "partial_text": snapshot.partial_text,
                }
            )
        else:
            transcription_result = None

        display_text = self._session.committed_text
        if self._session.partial_text:
            display_text = "\n".join(filter(None, [display_text, self._session.partial_text]))

        return RealtimeWorkerResult(
            session=self._session,
            final_text=display_text if self._session.status == RealtimeSessionStatus.COMPLETED else "",
            partial_text=display_text,
            transcription_result=transcription_result,
            metadata={
                "display_text": display_text,
                "committed_text": self._session.committed_text,
                "partial_text": self._session.partial_text,
            },
        )
