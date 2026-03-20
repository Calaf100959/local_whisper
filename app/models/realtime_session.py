from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RealtimeSessionStatus(StrEnum):
    IDLE = "idle"
    ARMING = "arming"
    LISTENING = "listening"
    PAUSED = "paused"
    TRANSCRIBING = "transcribing"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class RealtimeSession(BaseModel):
    session_id: str
    source_name: str = "microphone"
    status: RealtimeSessionStatus = RealtimeSessionStatus.IDLE
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    language: str | None = None
    partial_text: str = ""
    committed_text: str = ""
    error_message: str | None = None
    error_detail: str | None = None

    def with_status(self, status: RealtimeSessionStatus) -> "RealtimeSession":
        now = utc_now()
        finished_at = self.finished_at
        started_at = self.started_at

        if status != RealtimeSessionStatus.IDLE and started_at is None:
            started_at = now
        if status in {RealtimeSessionStatus.COMPLETED, RealtimeSessionStatus.FAILED}:
            finished_at = now

        return self.model_copy(
            update={
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "updated_at": now,
            }
        )

    def with_partial_text(self, partial_text: str) -> "RealtimeSession":
        return self.model_copy(
            update={
                "partial_text": partial_text,
                "updated_at": utc_now(),
            }
        )

    def with_committed_text(self, committed_text: str) -> "RealtimeSession":
        return self.model_copy(
            update={
                "committed_text": committed_text,
                "updated_at": utc_now(),
            }
        )

    def with_error(self, error_message: str, *, error_detail: str | None = None) -> "RealtimeSession":
        now = utc_now()
        return self.model_copy(
            update={
                "status": RealtimeSessionStatus.FAILED,
                "error_message": error_message,
                "error_detail": error_detail,
                "finished_at": now,
                "updated_at": now,
            }
        )
