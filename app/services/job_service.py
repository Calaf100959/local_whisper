from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.core.settings import Settings, get_settings
from app.models.job import Job, JobStatus


class JobService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def generate_job_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        suffix = uuid4().hex[:8]
        return f"job_{timestamp}_{suffix}"

    def create_job(
        self,
        *,
        input_type: str,
        source_name: str,
        model_size: str | None = None,
        language: str | None = None,
    ) -> Job:
        job = Job(
            job_id=self.generate_job_id(),
            input_type=input_type,
            source_name=source_name,
            model_size=self.settings.normalize_model_size(model_size),
            language=language or self.settings.default_language,
        )
        self._save_job(job)
        return job

    def get_job(self, job_id: str) -> Job:
        job_path = self._get_job_path(job_id)
        if not job_path.exists():
            raise FileNotFoundError(f"Job not found: {job_id}")
        return Job.model_validate_json(job_path.read_text(encoding="utf-8"))

    def update_status(self, job_id: str, status: JobStatus) -> Job:
        job = self.get_job(job_id)
        now = self._utc_now()
        started_at = job.started_at
        transcription_started_at = job.transcription_started_at
        finished_at = job.finished_at
        estimated_completion_at = job.estimated_completion_at

        if status not in {JobStatus.QUEUED} and started_at is None:
            started_at = now
        if status == JobStatus.TRANSCRIBING and transcription_started_at is None:
            transcription_started_at = now
        if status != JobStatus.TRANSCRIBING:
            estimated_completion_at = None
        if status in self._terminal_statuses():
            finished_at = now
            estimated_completion_at = None

        updated_job = job.model_copy(
            update={
                "status": status,
                "started_at": started_at,
                "transcription_started_at": transcription_started_at,
                "finished_at": finished_at,
                "estimated_completion_at": estimated_completion_at,
                "updated_at": now,
            }
        )
        self._save_job(updated_job)
        return updated_job

    def update_progress(
        self,
        job_id: str,
        *,
        progress_percent: int,
        current_chunk: int | None = None,
        total_chunks: int | None = None,
        processed_seconds: float | None = None,
        total_seconds: float | None = None,
    ) -> Job:
        job = self.get_job(job_id)
        now = self._utc_now()
        started_at = job.started_at or now
        transcription_started_at = job.transcription_started_at or now
        next_processed_seconds = max(0.0, processed_seconds if processed_seconds is not None else job.processed_seconds)
        next_total_seconds = total_seconds if total_seconds is not None else job.total_seconds
        estimated_completion_at = self._estimate_completion_at(
            started_at=transcription_started_at,
            updated_at=now,
            progress_percent=progress_percent,
        )
        updated_job = job.model_copy(
            update={
                "progress_percent": progress_percent,
                "current_chunk": current_chunk,
                "total_chunks": total_chunks,
                "started_at": started_at,
                "transcription_started_at": transcription_started_at,
                "processed_seconds": next_processed_seconds,
                "total_seconds": next_total_seconds,
                "estimated_completion_at": estimated_completion_at,
                "updated_at": now,
            }
        )
        self._save_job(updated_job)
        return updated_job

    def set_result_path(self, job_id: str, result_path: str | Path) -> Job:
        job = self.get_job(job_id)
        updated_job = job.model_copy(
            update={
                "result_path": str(result_path),
                "estimated_completion_at": None,
                "updated_at": self._utc_now(),
            }
        )
        self._save_job(updated_job)
        return updated_job

    def set_error(self, job_id: str, error_message: str, *, error_detail: str | None = None) -> Job:
        job = self.get_job(job_id)
        now = self._utc_now()
        updated_job = job.model_copy(
            update={
                "status": JobStatus.FAILED,
                "error_message": error_message,
                "error_detail": error_detail,
                "finished_at": now,
                "estimated_completion_at": None,
                "updated_at": now,
            }
        )
        self._save_job(updated_job)
        return updated_job

    def request_cancel(self, job_id: str) -> Job:
        job = self.get_job(job_id)
        if job.status in self._terminal_statuses():
            return job

        next_status = JobStatus.CANCELLING if job.status != JobStatus.QUEUED else JobStatus.CANCELLED
        now = self._utc_now()
        updated_job = job.model_copy(
            update={
                "status": next_status,
                "cancellation_requested": True,
                "finished_at": now if next_status == JobStatus.CANCELLED else None,
                "estimated_completion_at": None,
                "updated_at": now,
            }
        )
        self._save_job(updated_job)
        return updated_job

    def is_cancellation_requested(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return job.cancellation_requested or job.status in {JobStatus.CANCELLING, JobStatus.CANCELLED}

    def _get_job_path(self, job_id: str) -> Path:
        return self.settings.jobs_dir / f"{job_id}.json"

    def _save_job(self, job: Job) -> None:
        job_path = self._get_job_path(job.job_id)
        job_path.write_text(job.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _estimate_completion_at(
        *,
        started_at: datetime,
        updated_at: datetime,
        progress_percent: int,
    ) -> datetime | None:
        if progress_percent <= 0 or progress_percent >= 100:
            return None

        elapsed_seconds = (updated_at - started_at).total_seconds()
        if elapsed_seconds <= 0:
            return None

        remaining_seconds = elapsed_seconds * (100 - progress_percent) / progress_percent
        return updated_at + timedelta(seconds=remaining_seconds)

    @staticmethod
    def _terminal_statuses() -> set[JobStatus]:
        return {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
