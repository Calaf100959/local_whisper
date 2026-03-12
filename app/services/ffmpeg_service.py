from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.logging import get_logger
from app.core.runtime import is_frozen_app
from app.core.settings import Settings, get_settings


class FFmpegError(RuntimeError):
    """Raised when ffmpeg or ffprobe operations fail."""


logger = get_logger(__name__)


class FFmpegService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def check_availability(self) -> None:
        if self._resolve_binary_path(self.settings.ffmpeg_binary_name) is None:
            raise FFmpegError("ffmpeg is not installed or not available on PATH.")
        if self._resolve_binary_path(self.settings.ffprobe_binary_name) is None:
            raise FFmpegError("ffprobe is not installed or not available on PATH.")

    def extract_audio(
        self,
        source_path: str | Path,
        destination_path: str | Path | None = None,
        *,
        overwrite: bool = True,
    ) -> Path:
        self.check_availability()

        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source media file not found: {source}")

        destination = Path(destination_path) if destination_path else self._build_output_path(source)
        destination.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self._require_binary_path(self.settings.ffmpeg_binary_name),
            "-y" if overwrite else "-n",
            "-i",
            str(source),
            "-vn",
            "-acodec",
            self._get_audio_codec(destination.suffix.lower()),
            str(destination),
        ]
        self._run_command(command, "Audio extraction failed.")
        return destination

    def get_media_duration(self, source_path: str | Path) -> float:
        self.check_availability()

        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source media file not found: {source}")

        command = [
            self._require_binary_path(self.settings.ffprobe_binary_name),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ]
        result = self._run_command(command, "Media duration lookup failed.")

        try:
            return float(result.stdout.strip())
        except ValueError as exc:
            raise FFmpegError("ffprobe did not return a valid duration.") from exc

    def create_audio_chunk(
        self,
        source_path: str | Path,
        destination_path: str | Path,
        *,
        start_seconds: float,
        end_seconds: float,
        overwrite: bool = True,
    ) -> Path:
        self.check_availability()

        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source media file not found: {source}")
        if end_seconds <= start_seconds:
            raise ValueError("Chunk end time must be greater than start time.")

        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self._require_binary_path(self.settings.ffmpeg_binary_name),
            "-y" if overwrite else "-n",
            "-ss",
            str(start_seconds),
            "-to",
            str(end_seconds),
            "-i",
            str(source),
            "-vn",
            "-acodec",
            self._get_audio_codec(destination.suffix.lower()),
            str(destination),
        ]
        self._run_command(command, "Audio chunk extraction failed.")
        return destination

    def _build_output_path(self, source_path: Path) -> Path:
        return self.settings.temp_dir / f"{source_path.stem}.wav"

    def _get_audio_codec(self, suffix: str) -> str:
        codec_map = {
            ".wav": "pcm_s16le",
            ".m4a": "aac",
            ".mp3": "libmp3lame",
        }
        if suffix not in codec_map:
            raise FFmpegError(f"Unsupported audio output format: {suffix}")
        return codec_map[suffix]

    def _run_command(self, command: list[str], error_message: str) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=False,
            )
            return self._decode_completed_process(completed)
        except subprocess.CalledProcessError as exc:
            stderr = self._decode_output(exc.stderr).strip()
            logger.exception("ffmpeg command failed: command=%s stderr=%s", command, stderr)
            suffix = f" Details: {stderr}" if stderr else ""
            raise FFmpegError(f"{error_message}{suffix}") from exc

    def _decode_completed_process(self, result: subprocess.CompletedProcess[bytes]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=self._decode_output(result.stdout),
            stderr=self._decode_output(result.stderr),
        )

    @staticmethod
    def _decode_output(output: bytes | str | None) -> str:
        if output is None:
            return ""
        if isinstance(output, str):
            return output

        for encoding in ("utf-8", "cp932"):
            try:
                return output.decode(encoding)
            except UnicodeDecodeError:
                continue

        return output.decode("utf-8", errors="replace")

    def _resolve_binary_path(self, binary_name: str) -> str | None:
        bundled_path = self.settings.bundled_binary_path(binary_name)
        if bundled_path.exists():
            return str(bundled_path)

        if is_frozen_app():
            return None

        fallback_name = Path(binary_name).stem if binary_name.endswith(".exe") else binary_name
        return shutil.which(binary_name) or shutil.which(fallback_name)

    def _require_binary_path(self, binary_name: str) -> str:
        resolved = self._resolve_binary_path(binary_name)
        if resolved is None:
            raise FFmpegError(f"{binary_name} is not installed or not available.")
        return resolved
