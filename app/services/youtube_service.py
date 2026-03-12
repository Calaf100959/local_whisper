from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.core.runtime import is_frozen_app
from app.core.settings import Settings, get_settings
from app.services.media_service import MediaService


class YouTubeDownloadError(RuntimeError):
    """Raised when yt-dlp based downloads fail."""


logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class YouTubeDownloadResult:
    source_url: str
    local_path: Path
    network_required: bool
    user_message: str


class YouTubeService:
    NETWORK_REQUIRED_MESSAGE = "YouTube URL processing requires an active network connection."

    def __init__(
        self,
        settings: Settings | None = None,
        media_service: MediaService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.media_service = media_service or MediaService(self.settings)
        self.settings.ensure_directories()

    def check_availability(self) -> None:
        if self._resolve_binary_path(self.settings.ytdlp_binary_name) is None:
            raise YouTubeDownloadError("yt-dlp is not installed or not available on PATH.")

    def get_network_requirement_message(self) -> str:
        return self.NETWORK_REQUIRED_MESSAGE

    def download_audio(self, url: str, output_dir: Path | None = None) -> YouTubeDownloadResult:
        normalized_url = self.media_service.validate_youtube_url(url)
        self.check_availability()

        target_directory = output_dir or self.settings.temp_dir
        target_directory.mkdir(parents=True, exist_ok=True)

        command = [
            self._require_binary_path(self.settings.ytdlp_binary_name),
            "--no-playlist",
            "--restrict-filenames",
            "-f",
            "bestaudio/best",
            "-P",
            str(target_directory),
            "-o",
            "%(id)s.%(ext)s",
            "--print",
            "after_move:filepath",
            normalized_url,
        ]
        result = self._run_command(command)
        local_path = self._extract_download_path(result.stdout, target_directory)

        return YouTubeDownloadResult(
            source_url=normalized_url,
            local_path=local_path,
            network_required=True,
            user_message=self.NETWORK_REQUIRED_MESSAGE,
        )

    def _extract_download_path(self, stdout: str, target_directory: Path) -> Path:
        candidates = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not candidates:
            raise YouTubeDownloadError("yt-dlp did not return a download path.")

        local_path = Path(candidates[-1])
        if local_path.is_absolute():
            return local_path
        if len(local_path.parts) > 1:
            return local_path
        if not local_path.is_absolute():
            local_path = target_directory / local_path
        return local_path

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=False,
            )
            return self._decode_completed_process(completed)
        except subprocess.CalledProcessError as exc:
            stderr = self._decode_output(exc.stderr)
            logger.exception(
                "yt-dlp command failed: command=%s stderr=%s",
                command,
                stderr.strip(),
            )
            raise YouTubeDownloadError(self._map_download_error(stderr)) from exc

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
            raise YouTubeDownloadError(f"{binary_name} is not installed or not available.")
        return resolved

    def _map_download_error(self, stderr: str | None) -> str:
        details = (stderr or "").lower()

        if "http error 403" in details or "forbidden" in details:
            return "YouTube access was denied for this video."
        if "private video" in details:
            return "The specified YouTube video is private."
        if "video unavailable" in details:
            return "The specified YouTube video is unavailable."
        if "sign in to confirm your age" in details or "age-restricted" in details:
            return "The specified YouTube video is age-restricted."
        if "unable to download" in details or "failed to extract" in details:
            return "Failed to download audio from the specified YouTube URL."
        if "timed out" in details or "temporary failure in name resolution" in details:
            return self.NETWORK_REQUIRED_MESSAGE
        return "yt-dlp failed to download the requested YouTube media."
