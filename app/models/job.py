from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    EXTRACTING = "extracting"
    SPLITTING = "splitting"
    TRANSCRIBING = "transcribing"
    MERGING = "merging"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    job_id: str
    input_type: str
    source_name: str
    status: JobStatus = JobStatus.QUEUED
    progress_percent: int = Field(default=0, ge=0, le=100)
    current_chunk: int | None = Field(default=None, ge=1)
    total_chunks: int | None = Field(default=None, ge=1)
    model_size: str
    language: str
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    transcription_started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    processed_seconds: float = Field(default=0.0, ge=0.0)
    total_seconds: float | None = Field(default=None, gt=0.0)
    estimated_completion_at: datetime | None = None
    cancellation_requested: bool = False
    error_message: str | None = None
    error_detail: str | None = None
    result_path: str | None = None
