from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.core.exceptions import to_user_message
from app.services.job_service import JobService
from app.workers.transcription_worker import TranscriptionWorker


class DesktopWorkerThread(QThread):
    finished_with_result = Signal(str, str)
    failed_with_error = Signal(str)

    def __init__(self, *, worker: TranscriptionWorker, job_id: str, source: str | Path, parent=None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.job_id = job_id
        self.source = source

    def run(self) -> None:
        try:
            result = self.worker.run(self.job_id, self.source)
            job = JobService().get_job(self.job_id)
            self.finished_with_result.emit(result.text, job.result_path or "")
        except Exception as exc:
            self.failed_with_error.emit(to_user_message(exc))
