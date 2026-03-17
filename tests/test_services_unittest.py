from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
import shutil
from unittest.mock import patch
from uuid import uuid4

from app.core.settings import Settings
from app.models.job import JobStatus
from app.services.chunk_service import ChunkService
from app.services.ffmpeg_service import FFmpegService
from app.services.job_service import JobService
from app.services.media_service import InputType, MediaService
from app.services.result_service import OutputFormat, ResultService
from app.services.transcription_service import TranscriptionError, TranscriptionService
from app.services.transcription_service import TranscribedSegment, TranscriptionResult
from app.services.youtube_service import YouTubeService


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content

    async def close(self) -> None:
        return None


def build_settings(root: Path) -> Settings:
    return Settings(
        data_dir=root / "data",
        jobs_dir=root / "data" / "jobs",
        outputs_dir=root / "data" / "outputs",
        temp_dir=root / "data" / "temp",
        bundled_bin_dir=root / "resources" / "bin",
        bundled_models_dir=root / "resources" / "models",
    )


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        base_dir = Path.cwd() / "test_artifacts"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.root = base_dir / f"services_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = build_settings(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_job_service_create_and_update(self) -> None:
        service = JobService(self.settings)

        job = service.create_job(input_type="audio", source_name="sample.wav")
        saved_path = self.settings.jobs_dir / f"{job.job_id}.json"

        self.assertTrue(saved_path.exists())
        self.assertEqual(job.status, JobStatus.QUEUED)

        updated = service.update_status(job.job_id, JobStatus.TRANSCRIBING)
        progressed = service.update_progress(job.job_id, progress_percent=50, current_chunk=1, total_chunks=2)
        result_set = service.set_result_path(job.job_id, "data/outputs/sample.txt")
        errored = service.set_error(job.job_id, "error text")

        self.assertEqual(updated.status, JobStatus.TRANSCRIBING)
        self.assertEqual(progressed.progress_percent, 50)
        self.assertEqual(progressed.current_chunk, 1)
        self.assertEqual(progressed.total_chunks, 2)
        self.assertEqual(result_set.result_path, "data/outputs/sample.txt")
        self.assertEqual(errored.status, JobStatus.FAILED)

    def test_job_service_rejects_unsupported_model_size(self) -> None:
        service = JobService(self.settings)

        with self.assertRaises(ValueError):
            service.create_job(input_type="audio", source_name="sample.wav", model_size="base")

    def test_media_service_validation_and_save(self) -> None:
        service = MediaService(self.settings)
        local_file = self.root / "sample.wav"
        local_file.write_bytes(b"audio")

        input_type, resolved = service.validate_local_file(local_file)
        self.assertEqual(input_type, InputType.AUDIO)
        self.assertEqual(resolved, local_file)
        self.assertEqual(service.classify_file_type("movie.mp4"), InputType.VIDEO)
        self.assertEqual(
            service.classify_input("https://www.youtube.com/watch?v=abc123"),
            InputType.YOUTUBE_URL,
        )

        upload = FakeUploadFile(filename="upload.wav", content=b"hello")
        saved_path = asyncio.run(service.save_upload_file(upload))

        self.assertTrue(saved_path.exists())
        self.assertEqual(saved_path.read_bytes(), b"hello")

    def test_result_service_saves_txt_srt_and_json(self) -> None:
        service = ResultService(self.settings)
        result = TranscriptionResult(
            text="1行目\n2行目",
            language="ja",
            segments=[
                TranscribedSegment(start_seconds=0.0, end_seconds=1.25, text="1行目"),
                TranscribedSegment(start_seconds=1.5, end_seconds=3.0, text="2行目"),
            ],
        )

        saved_paths = service.save_all_results(
            job_id="job_123",
            source_name="sample.wav",
            result=result,
        )

        self.assertEqual(set(saved_paths.keys()), {OutputFormat.TXT, OutputFormat.SRT, OutputFormat.JSON})
        self.assertEqual(saved_paths[OutputFormat.TXT].read_text(encoding="utf-8"), "1行目\n2行目")
        srt_text = saved_paths[OutputFormat.SRT].read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:01,250", srt_text)
        self.assertIn("1行目", srt_text)
        json_text = saved_paths[OutputFormat.JSON].read_text(encoding="utf-8")
        self.assertIn('"language": "ja"', json_text)
        self.assertIn('"start_seconds": 1.5', json_text)

    def test_chunk_service_generates_expected_chunks(self) -> None:
        service = ChunkService(self.settings)

        short_chunks = service.create_chunks(120.0)
        long_chunks = service.create_chunks(18000.0)

        self.assertEqual(len(short_chunks), 1)
        self.assertEqual(len(long_chunks), 30)
        self.assertEqual(long_chunks[0].end_time_seconds, 602.0)
        self.assertEqual(long_chunks[1].start_time_seconds, 598.0)
        self.assertEqual(long_chunks[-1].end_time_seconds, 18000.0)
        self.assertEqual(
            service.build_chunk_path("meeting.wav", chunk_index=3).name,
            "meeting_chunk_0003.wav",
        )

    def test_frozen_build_requires_bundled_binaries(self) -> None:
        ffmpeg_service = FFmpegService(self.settings)
        youtube_service = YouTubeService(self.settings)

        with patch("app.services.ffmpeg_service.is_frozen_app", return_value=True):
            self.assertIsNone(ffmpeg_service._resolve_binary_path("ffmpeg.exe"))

        with patch("app.services.youtube_service.is_frozen_app", return_value=True):
            self.assertIsNone(youtube_service._resolve_binary_path("yt-dlp.exe"))

    def test_frozen_build_requires_bundled_model(self) -> None:
        service = TranscriptionService(self.settings)

        with patch("app.services.transcription_service.is_frozen_app", return_value=True):
            with self.assertRaises(TranscriptionError):
                service._resolve_model_source("small")


if __name__ == "__main__":
    unittest.main()
