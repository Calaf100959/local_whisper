from __future__ import annotations

from pathlib import Path

import pytest

from app.core.settings import Settings
from app.models.job import JobStatus
from app.services.job_service import JobService


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        jobs_dir=tmp_path / "data" / "jobs",
        outputs_dir=tmp_path / "data" / "outputs",
        temp_dir=tmp_path / "data" / "temp",
    )


def test_job_service_creates_and_updates_job(tmp_path: Path) -> None:
    service = JobService(build_settings(tmp_path))

    job = service.create_job(input_type="audio", source_name="sample.wav")
    saved_path = tmp_path / "data" / "jobs" / f"{job.job_id}.json"

    assert saved_path.exists()
    assert job.status == JobStatus.QUEUED
    assert job.model_size == "small"
    assert job.language == "ja"

    updated = service.update_status(job.job_id, JobStatus.TRANSCRIBING)
    progressed = service.update_progress(job.job_id, progress_percent=50, current_chunk=1, total_chunks=2)
    result_set = service.set_result_path(job.job_id, "data/outputs/sample.txt")
    errored = service.set_error(job.job_id, "error text")

    assert updated.status == JobStatus.TRANSCRIBING
    assert progressed.progress_percent == 50
    assert progressed.current_chunk == 1
    assert progressed.total_chunks == 2
    assert result_set.result_path == "data/outputs/sample.txt"
    assert errored.status == JobStatus.FAILED
    assert errored.error_message == "error text"


def test_job_service_get_missing_job_raises(tmp_path: Path) -> None:
    service = JobService(build_settings(tmp_path))

    with pytest.raises(FileNotFoundError):
        service.get_job("missing-job")
