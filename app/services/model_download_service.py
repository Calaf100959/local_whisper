from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.models.whisper_model import WhisperModelSpec


logger = get_logger(__name__)


class ModelDownloadError(RuntimeError):
    """Raised when an optional Whisper model download fails."""


class ModelDownloadService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def get_model_spec(self, model_id: str | None) -> WhisperModelSpec:
        return self.settings.get_whisper_model_spec(model_id)

    def get_download_target(self, model_id: str | None) -> Path:
        return self.settings.downloaded_model_path(self.get_model_spec(model_id).model_id)

    def is_model_downloaded(self, model_id: str | None) -> bool:
        model_spec = self.get_model_spec(model_id)
        return self._is_ready_model_directory(self.settings.downloaded_model_path(model_spec.model_id), model_spec)

    def download_model(self, model_id: str | None) -> Path:
        model_spec = self.get_model_spec(model_id)
        if not model_spec.downloadable or not model_spec.repo_id:
            raise ModelDownloadError(f"Model '{model_spec.model_id}' is not available for download.")

        target_dir = self.settings.downloaded_model_path(model_spec.model_id)
        if self._is_ready_model_directory(target_dir, model_spec):
            return target_dir

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        self.settings.huggingface_home_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(self.settings.huggingface_home_dir))
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        self._disable_huggingface_progress_bars()

        try:
            huggingface_hub = import_module("huggingface_hub")
            huggingface_hub.snapshot_download(
                repo_id=model_spec.repo_id,
                local_dir=str(target_dir),
                cache_dir=str(self.settings.huggingface_cache_dir()),
            )
        except Exception as exc:  # pragma: no cover - backend specific
            logger.exception(
                "Failed to download optional Whisper model: model_id=%s repo_id=%s target_dir=%s",
                model_spec.model_id,
                model_spec.repo_id,
                target_dir,
            )
            detail = str(exc).strip()
            if detail:
                raise ModelDownloadError(f"モデル '{model_spec.label}' のダウンロードに失敗しました: {detail}") from exc
            raise ModelDownloadError(f"モデル '{model_spec.label}' のダウンロードに失敗しました。") from exc

        if not self._is_ready_model_directory(target_dir, model_spec):
            raise ModelDownloadError(f"モデル '{model_spec.label}' のダウンロードが完了しませんでした。")

        return target_dir

    @staticmethod
    def _disable_huggingface_progress_bars() -> None:
        try:
            huggingface_hub_utils = import_module("huggingface_hub.utils")
            disable_progress_bars = getattr(huggingface_hub_utils, "disable_progress_bars", None)
            if callable(disable_progress_bars):
                disable_progress_bars()
        except Exception:
            logger.debug("Failed to disable Hugging Face progress bars before model download.", exc_info=True)

    @staticmethod
    def _is_ready_model_directory(path: Path, model_spec: WhisperModelSpec) -> bool:
        if not path.is_dir():
            return False
        return all((path / required_file).exists() for required_file in model_spec.required_files)
