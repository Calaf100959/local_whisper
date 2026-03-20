from __future__ import annotations

from queue import Empty, Queue

from PySide6.QtCore import QThread, Signal

from app.models.realtime_session import RealtimeSession
from app.models.realtime_session import RealtimeSessionStatus
from app.workers.realtime_worker import RealtimeWorker, RealtimeWorkerResult


class RealtimeWorkerThread(QThread):
    status_changed = Signal(str)
    partial_result_updated = Signal(str)
    level_updated = Signal(float)
    finished_with_result = Signal(object)
    failed_with_error = Signal(str)

    def __init__(
        self,
        *,
        worker: RealtimeWorker,
        session: RealtimeSession,
        language: str | None = None,
        model_size: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.worker = worker
        self.session = session
        self.language = language
        self.model_size = model_size
        self._commands: Queue[tuple[str, dict[str, object]]] = Queue()
        self._stop_requested = False

    def run(self) -> None:
        try:
            self._stop_requested = False
            self._emit_update(self.worker.start(self.session))
            while True:
                try:
                    command, payload = self._commands.get(timeout=0.1)
                except Empty:
                    continue
                if command == "audio":
                    if self._stop_requested:
                        continue
                    result = self.worker.append_audio_chunk(
                        payload["chunk"],
                        sample_rate=int(payload["sample_rate"]),
                        channel_count=int(payload["channel_count"]),
                        sample_format=str(payload["sample_format"]),
                        language=self.language,
                        model_size=self.model_size,
                    )
                    if result is not None:
                        self._emit_update(result)
                    continue
                if command == "pause":
                    self._emit_update(self.worker.pause())
                    continue
                if command == "resume":
                    self._emit_update(self.worker.resume())
                    continue
                if command == "stop":
                    result = self.worker.stop(language=self.language, model_size=self.model_size)
                    self._emit_update(result)
                    self.finished_with_result.emit(result)
                    return
        except Exception as exc:
            self.failed_with_error.emit(str(exc))
            return

    def enqueue_audio_chunk(
        self,
        chunk: bytes,
        *,
        sample_rate: int,
        channel_count: int,
        sample_format: str,
    ) -> None:
        if self._stop_requested:
            return
        self._commands.put(
            (
                "audio",
                {
                    "chunk": chunk,
                    "sample_rate": sample_rate,
                    "channel_count": channel_count,
                    "sample_format": sample_format,
                },
            )
        )

    def pause_session(self) -> None:
        self._commands.put(("pause", {}))

    def resume_session(self) -> None:
        self._commands.put(("resume", {}))

    def stop_session(self) -> None:
        self._stop_requested = True
        self.status_changed.emit(RealtimeSessionStatus.FINALIZING.value)
        self._commands.put(("stop", {}))

    def _emit_update(self, result: RealtimeWorkerResult) -> None:
        status_value = result.session.status.value
        if self._stop_requested and status_value in {
            RealtimeSessionStatus.LISTENING.value,
            RealtimeSessionStatus.PAUSED.value,
            RealtimeSessionStatus.TRANSCRIBING.value,
        }:
            status_value = RealtimeSessionStatus.FINALIZING.value
        self.status_changed.emit(status_value)
        self.partial_result_updated.emit(str(result.metadata.get("display_text", result.partial_text)))
        self.level_updated.emit(0.0)
