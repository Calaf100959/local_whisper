from __future__ import annotations

from pathlib import Path

from app.core.exceptions import to_user_message
from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.models.job import JobStatus
from app.services.chunk_service import ChunkService
from app.services.diarization_service import DiarizationService
from app.services.ffmpeg_service import FFmpegService
from app.services.job_service import JobService
from app.services.media_service import InputType
from app.services.result_service import OutputFormat, ResultService
from app.services.speaker_assignment_service import SpeakerAssignmentService
from app.services.transcription_service import (
    ChunkTranscriptionInput,
    TranscriptionCancelled,
    TranscriptionResult,
    TranscriptionService,
)
from app.services.youtube_service import YouTubeService


logger = get_logger(__name__)


class TranscriptionWorker:
    def __init__(
        self,
        settings: Settings | None = None,
        job_service: JobService | None = None,
        ffmpeg_service: FFmpegService | None = None,
        chunk_service: ChunkService | None = None,
        result_service: ResultService | None = None,
        transcription_service: TranscriptionService | None = None,
        diarization_service: DiarizationService | None = None,
        speaker_assignment_service: SpeakerAssignmentService | None = None,
        youtube_service: YouTubeService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.job_service = job_service or JobService(self.settings)
        self.ffmpeg_service = ffmpeg_service or FFmpegService(self.settings)
        self.chunk_service = chunk_service or ChunkService(self.settings)
        self.result_service = result_service or ResultService(self.settings)
        self.transcription_service = transcription_service or TranscriptionService(
            self.settings,
            self.job_service,
        )
        self.diarization_service = diarization_service or DiarizationService(self.settings)
        self.speaker_assignment_service = speaker_assignment_service or SpeakerAssignmentService()
        self.youtube_service = youtube_service or YouTubeService(self.settings)

    def run(self, job_id: str, source: str | Path) -> TranscriptionResult:
        job = self.job_service.get_job(job_id)
        cleanup_paths: set[Path] = set()

        try:
            logger.info("Transcription job started: job_id=%s input_type=%s source=%s", job_id, job.input_type, source)
            self.job_service.update_status(job_id, JobStatus.PREPARING)
            self.job_service.set_warning(job_id, None)

            prepared_audio_path = self._prepare_source(job_id, job.input_type, source, cleanup_paths)
            self._raise_if_cancel_requested(job_id)
            duration_seconds = self.ffmpeg_service.get_media_duration(prepared_audio_path)
            self._raise_if_cancel_requested(job_id)

            if self.chunk_service.is_long_form(duration_seconds):
                result = self._transcribe_long_form(
                    job_id,
                    prepared_audio_path,
                    duration_seconds,
                    job.model_size,
                    job.language,
                    cleanup_paths,
                )
            else:
                result = self.transcription_service.transcribe_file(
                    prepared_audio_path,
                    model_size=job.model_size,
                    language=job.language,
                    job_id=job_id,
                    total_duration_seconds=duration_seconds,
                )
                self.job_service.update_progress(
                    job_id,
                    progress_percent=100,
                    current_chunk=1,
                    total_chunks=1,
                    processed_seconds=duration_seconds,
                    total_seconds=duration_seconds,
                )

            self.job_service.update_status(job_id, JobStatus.MERGING)
            result = self._apply_speaker_diarization(job, prepared_audio_path, result)
            result_path = self._save_result(job.job_id, job.source_name, result)
            self.job_service.set_result_path(job_id, result_path)
            self.job_service.update_status(job_id, JobStatus.COMPLETED)
            logger.info("Transcription job completed: job_id=%s result_path=%s", job_id, result_path)
            return result
        except TranscriptionCancelled as exc:
            result = exc.partial_result
            logger.info("Transcription job cancelled: job_id=%s", job_id)
            self.job_service.update_status(job_id, JobStatus.MERGING)
            result_path = self._save_result(job.job_id, job.source_name, result)
            self.job_service.set_result_path(job_id, result_path)
            self.job_service.update_status(job_id, JobStatus.CANCELLED)
            return result
        except Exception as exc:
            logger.exception("Transcription job failed: job_id=%s", job_id)
            self.job_service.set_error(
                job_id,
                to_user_message(exc),
                error_detail=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            self._cleanup_paths(cleanup_paths)

    def _prepare_source(self, job_id: str, input_type: str, source: str | Path, cleanup_paths: set[Path]) -> Path:
        if input_type == InputType.YOUTUBE_URL.value:
            download_result = self.youtube_service.download_audio(str(source))
            cleanup_paths.add(download_result.local_path)
            return download_result.local_path

        source_path = Path(source)
        if input_type == InputType.VIDEO.value:
            self.job_service.update_status(job_id, JobStatus.EXTRACTING)
            audio_path = self.ffmpeg_service.extract_audio(source_path)
            cleanup_paths.add(audio_path)
            return audio_path

        return source_path

    def _transcribe_long_form(
        self,
        job_id: str,
        source_path: Path,
        duration_seconds: float,
        model_size: str,
        language: str,
        cleanup_paths: set[Path],
    ) -> TranscriptionResult:
        self.job_service.update_status(job_id, JobStatus.SPLITTING)
        chunk_segments = self.chunk_service.create_chunks(duration_seconds)
        chunk_inputs: list[ChunkTranscriptionInput] = []

        for chunk in chunk_segments:
            self._raise_if_cancel_requested(job_id)
            chunk_path = self.chunk_service.build_chunk_path(
                source_path.with_suffix(".wav"),
                chunk_index=chunk.index,
            )
            self.ffmpeg_service.create_audio_chunk(
                source_path,
                chunk_path,
                start_seconds=chunk.start_time_seconds,
                end_seconds=chunk.end_time_seconds,
            )
            cleanup_paths.add(chunk_path)
            chunk_inputs.append(ChunkTranscriptionInput(path=chunk_path, chunk=chunk))

        return self.transcription_service.transcribe_chunks(
            chunk_inputs,
            model_size=model_size,
            language=language,
            job_id=job_id,
            total_duration_seconds=duration_seconds,
        )

    def _save_result(self, job_id: str, source_name: str, result: TranscriptionResult) -> Path:
        saved_paths = self.result_service.save_all_results(
            job_id=job_id,
            source_name=source_name,
            result=result,
        )
        return saved_paths[OutputFormat.TXT]

    def _apply_speaker_diarization(
        self,
        job,
        prepared_audio_path: Path,
        result: TranscriptionResult,
    ) -> TranscriptionResult:
        if not job.diarization_enabled or not result.segments:
            return result

        try:
            diarized_segments = self.diarization_service.diarize(
                prepared_audio_path,
                num_speakers=job.diarization_num_speakers,
            )
            return self.speaker_assignment_service.assign_speakers(result, diarized_segments)
        except Exception as exc:
            logger.exception("Speaker diarization failed: job_id=%s", job.job_id)
            self.job_service.set_warning(
                job.job_id,
                f"文字起こしは完了しましたが、話者分離に失敗しました。{to_user_message(exc)}",
            )
            return result

    def _cleanup_paths(self, cleanup_paths: set[Path]) -> None:
        for path in sorted(cleanup_paths):
            try:
                if path.exists() and self._is_temp_path(path):
                    path.unlink()
            except OSError:
                continue

    def _is_temp_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.settings.temp_dir.resolve())
            return True
        except ValueError:
            return False

    def _raise_if_cancel_requested(self, job_id: str) -> None:
        if self.job_service.is_cancellation_requested(job_id):
            raise TranscriptionCancelled(TranscriptionResult(text="", segments=[]))
