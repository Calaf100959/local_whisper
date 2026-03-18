from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.core.settings import Settings
from app.models.job import JobStatus
from app.services.chunk_service import ChunkService
from app.services.diarization_service import DiarizationService, DiarizedSegment
from app.services.ffmpeg_service import FFmpegService
from app.services.job_service import JobService
from app.services.media_service import InputType, MediaService
from app.services.result_service import OutputFormat, ResultService
from app.services.speaker_assignment_service import SpeakerAssignmentService
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
        downloaded_models_dir=root / "data" / "models",
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

        job = service.create_job(
            input_type="audio",
            source_name="sample.wav",
            diarization_enabled=True,
            diarization_num_speakers=2,
        )
        saved_path = self.settings.jobs_dir / f"{job.job_id}.json"

        self.assertTrue(saved_path.exists())
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertTrue(job.diarization_enabled)
        self.assertEqual(job.diarization_num_speakers, 2)

        updated = service.update_status(job.job_id, JobStatus.TRANSCRIBING)
        progressed = service.update_progress(
            job.job_id,
            progress_percent=50,
            current_chunk=1,
            total_chunks=2,
            processed_seconds=30.0,
            total_seconds=60.0,
        )
        result_set = service.set_result_path(job.job_id, "data/outputs/sample.txt")
        errored = service.set_error(job.job_id, "error text")

        self.assertEqual(updated.status, JobStatus.TRANSCRIBING)
        self.assertIsNotNone(updated.transcription_started_at)
        self.assertEqual(progressed.progress_percent, 50)
        self.assertEqual(progressed.current_chunk, 1)
        self.assertEqual(progressed.total_chunks, 2)
        self.assertEqual(progressed.processed_seconds, 30.0)
        self.assertEqual(progressed.total_seconds, 60.0)
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
                TranscribedSegment(start_seconds=0.0, end_seconds=1.25, text="1行目", speaker="SPEAKER_00"),
                TranscribedSegment(start_seconds=1.5, end_seconds=3.0, text="2行目", speaker="SPEAKER_01"),
            ],
        )

        saved_paths = service.save_all_results(
            job_id="job_123",
            source_name="sample.wav",
            result=result,
        )

        self.assertEqual(set(saved_paths.keys()), {OutputFormat.TXT, OutputFormat.SRT, OutputFormat.JSON})
        output_dir = saved_paths[OutputFormat.TXT].parent
        self.assertTrue(output_dir.is_dir())
        self.assertEqual(output_dir.name, "sample_job_123")
        self.assertEqual(
            saved_paths[OutputFormat.TXT].read_text(encoding="utf-8"),
            "[SPEAKER_00] 1行目\n[SPEAKER_01] 2行目",
        )
        self.assertEqual(saved_paths[OutputFormat.TXT].name, "sample_job_123.txt")
        srt_text = saved_paths[OutputFormat.SRT].read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:01,250", srt_text)
        self.assertIn("[SPEAKER_00] 1行目", srt_text)
        self.assertEqual(saved_paths[OutputFormat.SRT].name, "sample_job_123.srt")
        json_text = saved_paths[OutputFormat.JSON].read_text(encoding="utf-8")
        self.assertIn('"language": "ja"', json_text)
        self.assertIn('"start_seconds": 1.5', json_text)
        self.assertIn('"speaker": "SPEAKER_01"', json_text)
        self.assertEqual(saved_paths[OutputFormat.JSON].name, "sample_job_123.json")

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

    def test_transcription_service_updates_progress_for_single_file(self) -> None:
        source_path = self.root / "sample.wav"
        source_path.write_bytes(b"audio")
        job_service = JobService(self.settings)
        service = TranscriptionService(self.settings, job_service=job_service)
        job = job_service.create_job(input_type="audio", source_name=source_path.name)

        fake_segments = [
            SimpleNamespace(start=0.0, end=4.0, text="前半"),
            SimpleNamespace(start=4.0, end=8.0, text="後半"),
        ]
        fake_info = SimpleNamespace(language="ja", duration=12.0)

        class FakeModel:
            def transcribe(self, audio: str, language: str | None = None):
                return iter(fake_segments), fake_info

        with patch.object(service, "load_model", return_value=FakeModel()):
            result = service.transcribe_file(
                source_path,
                model_size="small",
                language="ja",
                job_id=job.job_id,
                total_duration_seconds=12.0,
            )

        updated_job = job_service.get_job(job.job_id)
        self.assertEqual(result.text, "前半\n後半")
        self.assertEqual(updated_job.status, JobStatus.TRANSCRIBING)
        self.assertEqual(updated_job.progress_percent, 66)
        self.assertEqual(updated_job.current_chunk, 1)
        self.assertEqual(updated_job.total_chunks, 1)
        self.assertEqual(updated_job.processed_seconds, 8.0)
        self.assertEqual(updated_job.total_seconds, 12.0)
        self.assertIsNotNone(updated_job.transcription_started_at)

    def test_speaker_assignment_service_assigns_max_overlap_speaker(self) -> None:
        service = SpeakerAssignmentService()
        result = TranscriptionResult(
            text="",
            language="ja",
            segments=[
                TranscribedSegment(start_seconds=0.0, end_seconds=1.0, text="A"),
                TranscribedSegment(start_seconds=1.0, end_seconds=3.0, text="B"),
            ],
        )
        diarized_segments = [
            DiarizedSegment(start_seconds=0.0, end_seconds=1.5, speaker="SPEAKER_00"),
            DiarizedSegment(start_seconds=1.5, end_seconds=3.0, speaker="SPEAKER_01"),
        ]

        assigned = service.assign_speakers(result, diarized_segments)

        self.assertEqual(assigned.segments[0].speaker, "SPEAKER_00")
        self.assertEqual(assigned.segments[1].speaker, "SPEAKER_01")
        self.assertEqual(assigned.render_text(include_speakers=True), "[SPEAKER_00] A\n[SPEAKER_01] B")

    def test_diarization_service_prefers_downloaded_model_when_bundled_model_is_incomplete(self) -> None:
        service = DiarizationService(self.settings)
        bundled_dir = self.settings.bundled_diarization_model_path()
        bundled_dir.mkdir(parents=True, exist_ok=True)
        downloaded_dir = self.settings.downloaded_diarization_model_path()
        downloaded_dir.mkdir(parents=True, exist_ok=True)
        (downloaded_dir / "hyperparams.yaml").write_text("modules: {}", encoding="utf-8")
        (downloaded_dir / "embedding_model.ckpt").write_bytes(b"weights")

        model_source, savedir = service._resolve_embedding_model_source()

        self.assertEqual(model_source, str(downloaded_dir))
        self.assertEqual(savedir, str(downloaded_dir))

    def test_diarization_service_uses_public_model_when_local_model_is_missing(self) -> None:
        service = DiarizationService(self.settings)

        def fake_download(target_dir: Path) -> None:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "hyperparams.yaml").write_text("modules: {}", encoding="utf-8")
            (target_dir / "embedding_model.ckpt").write_bytes(b"weights")

        with patch.object(service, "_download_embedding_model_snapshot", side_effect=fake_download):
            model_source, savedir = service._resolve_embedding_model_source()

        self.assertEqual(model_source, str(self.settings.downloaded_diarization_model_path()))
        self.assertEqual(savedir, str(self.settings.downloaded_diarization_model_path()))

    def test_diarization_service_normalizes_cluster_labels_by_first_appearance(self) -> None:
        service = DiarizationService(self.settings)

        normalized = service._normalize_cluster_labels([4, 4, 1, 7, 1])

        self.assertEqual(normalized, [0, 0, 1, 2, 1])


if __name__ == "__main__":
    unittest.main()
