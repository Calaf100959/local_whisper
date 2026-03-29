from __future__ import annotations

import shutil
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtWidgets import QApplication

from app.core.settings import Settings
from app.desktop.window import MainWindow
from app.services.job_service import JobService
from app.services.model_download_service import ModelDownloadService
from app.services.transcription_service import ModelDownloadRequired, TranscriptionService


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


class OptionalModelDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        base_dir = Path.cwd() / "test_artifacts"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.root = base_dir / f"optional_models_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = build_settings(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_settings_expose_kotoba_for_batch_and_realtime(self) -> None:
        batch_model_ids = [model.model_id for model in self.settings.list_batch_model_specs()]
        realtime_model_ids = [model.model_id for model in self.settings.list_realtime_model_specs()]

        self.assertIn("kotoba-whisper-v2.0-faster", batch_model_ids)
        self.assertIn("kotoba-whisper-v2.0-faster", realtime_model_ids)

    def test_job_service_accepts_optional_download_model_id(self) -> None:
        service = JobService(self.settings)

        job = service.create_job(
            input_type="audio",
            source_name="sample.wav",
            model_size="kotoba-whisper-v2.0-faster",
        )

        self.assertEqual(job.model_size, "kotoba-whisper-v2.0-faster")

    def test_transcription_service_prefers_downloaded_optional_model(self) -> None:
        service = TranscriptionService(self.settings)
        model_dir = self.settings.downloaded_model_path("kotoba-whisper-v2.0-faster")
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "model.bin").write_bytes(b"weights")
        (model_dir / "config.json").write_text("{}", encoding="utf-8")

        resolved = service._resolve_model_source("kotoba-whisper-v2.0-faster")

        self.assertEqual(resolved, str(model_dir))

    def test_transcription_service_requires_download_for_missing_optional_model(self) -> None:
        service = TranscriptionService(self.settings)

        with self.assertRaises(ModelDownloadRequired) as captured:
            service._resolve_model_source("kotoba-whisper-v2.0-faster")

        self.assertEqual(captured.exception.model_spec.model_id, "kotoba-whisper-v2.0-faster")

    def test_model_download_service_downloads_optional_model_snapshot(self) -> None:
        service = ModelDownloadService(self.settings)
        captured: dict[str, str] = {}
        progress_bar_calls: list[str] = []
        captured_env: dict[str, str] = {}

        def fake_snapshot_download(*, repo_id: str, local_dir: str, cache_dir: str) -> None:
            captured["repo_id"] = repo_id
            captured["local_dir"] = local_dir
            captured["cache_dir"] = cache_dir
            captured_env["HF_HUB_DISABLE_PROGRESS_BARS"] = os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS", "")
            captured_env["HF_HOME"] = os.environ.get("HF_HOME", "")
            captured_env["HF_HUB_DISABLE_XET"] = os.environ.get("HF_HUB_DISABLE_XET", "")
            target_dir = Path(local_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "model.bin").write_bytes(b"weights")
            (target_dir / "config.json").write_text("{}", encoding="utf-8")

        fake_hub = SimpleNamespace(snapshot_download=fake_snapshot_download)
        fake_hub_utils = SimpleNamespace(disable_progress_bars=lambda: progress_bar_calls.append("disabled"))

        def fake_import_module(name: str):
            if name == "huggingface_hub":
                return fake_hub
            if name == "huggingface_hub.utils":
                return fake_hub_utils
            raise ModuleNotFoundError(name)

        with patch.dict(os.environ, {}, clear=False):
            with patch("app.services.model_download_service.import_module", side_effect=fake_import_module):
                target_dir = service.download_model("kotoba-whisper-v2.0-faster")

        self.assertEqual(progress_bar_calls, ["disabled"])
        self.assertEqual(captured_env["HF_HUB_DISABLE_PROGRESS_BARS"], "1")
        self.assertEqual(captured_env["HF_HOME"], str(self.settings.huggingface_home_dir))
        self.assertEqual(captured_env["HF_HUB_DISABLE_XET"], "1")
        self.assertEqual(captured["repo_id"], "kotoba-tech/kotoba-whisper-v2.0-faster")
        self.assertEqual(target_dir, self.settings.downloaded_model_path("kotoba-whisper-v2.0-faster"))
        self.assertEqual(captured["cache_dir"], str(self.settings.huggingface_cache_dir()))
        self.assertTrue(service.is_model_downloaded("kotoba-whisper-v2.0-faster"))

    def test_model_download_service_downloads_optional_model_snapshot_when_progress_util_missing(self) -> None:
        service = ModelDownloadService(self.settings)
        captured: dict[str, str] = {}

        def fake_snapshot_download(*, repo_id: str, local_dir: str, cache_dir: str) -> None:
            captured["repo_id"] = repo_id
            captured["local_dir"] = local_dir
            captured["cache_dir"] = cache_dir
            target_dir = Path(local_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "model.bin").write_bytes(b"weights")
            (target_dir / "config.json").write_text("{}", encoding="utf-8")

        fake_hub = SimpleNamespace(snapshot_download=fake_snapshot_download)

        def fake_import_module(name: str):
            if name == "huggingface_hub":
                return fake_hub
            if name == "huggingface_hub.utils":
                raise ModuleNotFoundError(name)
            raise ModuleNotFoundError(name)

        with patch.dict(os.environ, {}, clear=False):
            with patch("app.services.model_download_service.import_module", side_effect=fake_import_module):
                target_dir = service.download_model("kotoba-whisper-v2.0-faster")

        self.assertEqual(captured["repo_id"], "kotoba-tech/kotoba-whisper-v2.0-faster")
        self.assertEqual(target_dir, self.settings.downloaded_model_path("kotoba-whisper-v2.0-faster"))
        self.assertEqual(captured["cache_dir"], str(self.settings.huggingface_cache_dir()))
        self.assertTrue(service.is_model_downloaded("kotoba-whisper-v2.0-faster"))

    def test_start_transcription_prompts_for_optional_model_when_selected(self) -> None:
        with patch("app.desktop.window.JobService", side_effect=lambda: JobService(self.settings)):
            window = MainWindow()

        try:
            kotoba_index = window.batch_model_combo.findData("kotoba-whisper-v2.0-faster")
            self.assertGreaterEqual(kotoba_index, 0)
            window.batch_model_combo.setCurrentIndex(kotoba_index)

            source_path = self.root / "sample.wav"
            source_path.write_bytes(b"audio")
            window.file_path_edit.setText(str(source_path))

            with patch.object(window, "_prompt_optional_model_download", return_value=False) as prompt_mock:
                window.start_transcription()

            prompt_mock.assert_called_once_with("kotoba-whisper-v2.0-faster")
        finally:
            window.close()

    def test_start_realtime_transcription_prompts_for_optional_model_when_selected(self) -> None:
        with patch("app.desktop.window.JobService", side_effect=lambda: JobService(self.settings)):
            window = MainWindow()

        try:
            kotoba_index = window.realtime_panel.model_combo.findData("kotoba-whisper-v2.0-faster")
            self.assertGreaterEqual(kotoba_index, 0)
            window.realtime_panel.model_combo.setCurrentIndex(kotoba_index)

            with patch.object(window, "_prompt_optional_model_download", return_value=False) as prompt_mock:
                window.start_realtime_transcription()

            prompt_mock.assert_called_once_with("kotoba-whisper-v2.0-faster")
            self.assertIsNone(window.realtime_worker_thread)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
