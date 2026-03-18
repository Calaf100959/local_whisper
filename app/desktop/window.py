from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QProgressBar,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import to_user_message
from app.models.job import Job, JobStatus
from app.services.job_service import JobService
from app.services.media_service import InputType, MediaService
from app.services.result_service import OutputFormat
from app.workers.transcription_worker import TranscriptionWorker
from app.desktop.worker_thread import DesktopWorkerThread


class MainWindow(QMainWindow):
    STATUS_LABELS = {
        JobStatus.QUEUED: "待機中",
        JobStatus.PREPARING: "準備中",
        JobStatus.EXTRACTING: "音声抽出中",
        JobStatus.SPLITTING: "分割中",
        JobStatus.TRANSCRIBING: "文字起こし中",
        JobStatus.MERGING: "結果出力中",
        JobStatus.CANCELLING: "停止要求中",
        JobStatus.CANCELLED: "停止済み",
        JobStatus.COMPLETED: "完了",
        JobStatus.FAILED: "失敗",
    }

    def __init__(self) -> None:
        super().__init__()
        self.job_service = JobService()
        self.media_service = MediaService()
        self.transcription_worker = TranscriptionWorker(job_service=self.job_service)
        self.outputs_dir = self.job_service.settings.outputs_dir
        self.worker_thread: DesktopWorkerThread | None = None
        self.current_job_id: str | None = None
        self.current_result_path: str | None = None
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(700)
        self.poll_timer.timeout.connect(self.refresh_job_status)

        self.setWindowTitle("ローカル文字起こしデスクトップアプリ")
        self.resize(980, 760)
        self.setAcceptDrops(True)
        self._build_ui()
        self._wire_events()
        self._set_mode("audio")

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel("ローカル文字起こしデスクトップアプリ")
        title.setStyleSheet("font-size: 26px; font-weight: 700;")
        subtitle = QLabel("Whisper を使って音声・動画・YouTube URL をローカルで文字起こしします。")
        subtitle.setStyleSheet("color: #5f6c66;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addWidget(self._build_input_group())
        layout.addWidget(self._build_status_group())
        layout.addWidget(self._build_result_group(), stretch=1)

    def _build_input_group(self) -> QGroupBox:
        group = QGroupBox("入力と設定")
        layout = QVBoxLayout(group)

        mode_row = QHBoxLayout()
        self.audio_mode = QRadioButton("音声ファイル")
        self.video_mode = QRadioButton("動画ファイル")
        self.youtube_mode = QRadioButton("YouTube URL")
        self.audio_mode.setChecked(True)
        mode_row.addWidget(self.audio_mode)
        mode_row.addWidget(self.video_mode)
        mode_row.addWidget(self.youtube_mode)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.file_row_widget = QWidget()
        file_row = QHBoxLayout(self.file_row_widget)
        file_row.setContentsMargins(0, 0, 0, 0)
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("ファイルを選択してください")
        self.file_browse_button = QPushButton("参照...")
        file_row.addWidget(self.file_path_edit, stretch=1)
        file_row.addWidget(self.file_browse_button)
        layout.addWidget(self.file_row_widget)

        self.url_row_widget = QWidget()
        url_row = QHBoxLayout(self.url_row_widget)
        url_row.setContentsMargins(0, 0, 0, 0)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        url_row.addWidget(self.url_edit)
        layout.addWidget(self.url_row_widget)

        settings_grid = QGridLayout()
        settings_grid.addWidget(QLabel("モデル"), 0, 0)
        self.model_value = QLabel("small（固定）")
        settings_grid.addWidget(self.model_value, 0, 1)

        settings_grid.addWidget(QLabel("言語"), 0, 2)
        self.language_combo = QComboBox()
        self.language_combo.addItem("日本語", "ja")
        self.language_combo.addItem("英語", "en")
        self.language_combo.addItem("自動検出", None)
        self.language_combo.setCurrentIndex(0)
        settings_grid.addWidget(self.language_combo, 0, 3)

        self.diarization_checkbox = QCheckBox("話者分離を有効化")
        settings_grid.addWidget(self.diarization_checkbox, 1, 0, 1, 2)

        settings_grid.addWidget(QLabel("話者数"), 1, 2)
        self.speaker_count_combo = QComboBox()
        self.speaker_count_combo.addItem("自動", None)
        for speaker_count in range(2, 6):
            self.speaker_count_combo.addItem(f"{speaker_count}人", speaker_count)
        self.speaker_count_combo.setEnabled(False)
        settings_grid.addWidget(self.speaker_count_combo, 1, 3)
        layout.addLayout(settings_grid)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("文字起こし開始")
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.export_result_button = QPushButton("結果ファイルを出力する")
        self.export_result_button.setEnabled(False)
        self.open_output_dir_button = QPushButton("ファイルを確認する")
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.export_result_button)
        action_row.addWidget(self.open_output_dir_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        return group

    def _build_status_group(self) -> QGroupBox:
        group = QGroupBox("処理状況")
        layout = QGridLayout(group)

        layout.addWidget(QLabel("状態"), 0, 0)
        self.status_value = QLabel("待機中")
        layout.addWidget(self.status_value, 0, 1)

        layout.addWidget(QLabel("入力"), 1, 0)
        self.source_value = QLabel("-")
        layout.addWidget(self.source_value, 1, 1)

        layout.addWidget(QLabel("チャンク"), 2, 0)
        self.chunk_value = QLabel("-")
        layout.addWidget(self.chunk_value, 2, 1)

        layout.addWidget(QLabel("推定残り時間"), 3, 0)
        self.eta_value = QLabel("-")
        layout.addWidget(self.eta_value, 3, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar, 4, 0, 1, 2)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b42318; font-weight: 700;")
        layout.addWidget(self.error_label, 5, 0, 1, 2)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #b54708; font-weight: 700;")
        layout.addWidget(self.warning_label, 6, 0, 1, 2)

        return group

    def _build_result_group(self) -> QGroupBox:
        group = QGroupBox("文字起こし結果")
        layout = QVBoxLayout(group)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        layout.addWidget(self.result_text)
        return group

    def _wire_events(self) -> None:
        self.audio_mode.toggled.connect(lambda checked: checked and self._set_mode("audio"))
        self.video_mode.toggled.connect(lambda checked: checked and self._set_mode("video"))
        self.youtube_mode.toggled.connect(lambda checked: checked and self._set_mode("youtube"))
        self.file_browse_button.clicked.connect(self.choose_file)
        self.diarization_checkbox.toggled.connect(self.speaker_count_combo.setEnabled)
        self.start_button.clicked.connect(self.start_transcription)
        self.stop_button.clicked.connect(self.stop_transcription)
        self.export_result_button.clicked.connect(self.export_result_file)
        self.open_output_dir_button.clicked.connect(self.open_output_directory)

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        is_url = mode == "youtube"
        self.file_row_widget.setVisible(not is_url)
        self.url_row_widget.setVisible(is_url)
        placeholder = "音声ファイルを選択してください" if mode == "audio" else "動画ファイルを選択してください"
        self.file_path_edit.setPlaceholderText(placeholder)

    def choose_file(self) -> None:
        if self.mode == "audio":
            file_filter = "Audio Files (*.mp3 *.wav *.m4a)"
        else:
            file_filter = "Video Files (*.mp4 *.mov *.mkv)"

        file_path, _ = QFileDialog.getOpenFileName(self, "ファイルを選択", "", file_filter)
        if file_path:
            self.file_path_edit.setText(file_path)
            self.error_label.setText("")
            self.warning_label.setText("")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._extract_supported_drop_path(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        dropped_path = self._extract_supported_drop_path(event)
        if not dropped_path:
            event.ignore()
            return

        try:
            input_type, resolved = self.media_service.validate_local_file(dropped_path)
        except Exception as exc:
            self.show_error(to_user_message(exc))
            event.ignore()
            return

        if input_type == InputType.AUDIO:
            self.audio_mode.setChecked(True)
        elif input_type == InputType.VIDEO:
            self.video_mode.setChecked(True)

        self.file_path_edit.setText(str(resolved))
        self.error_label.setText("")
        self.warning_label.setText("")
        event.acceptProposedAction()

    def start_transcription(self) -> None:
        try:
            source, input_type = self._resolve_source()
        except Exception as exc:
            self.show_error(to_user_message(exc))
            return

        if not self._confirm_start():
            return

        self._reset_status()

        job = self.job_service.create_job(
            input_type=input_type.value,
            source_name=Path(source).name if input_type != InputType.YOUTUBE_URL else str(source),
            model_size=self.job_service.settings.default_model_size,
            language=self.language_combo.currentData(),
            diarization_enabled=self.diarization_checkbox.isChecked(),
            diarization_num_speakers=(
                self.speaker_count_combo.currentData() if self.diarization_checkbox.isChecked() else None
            ),
        )
        self.current_job_id = job.job_id
        self.source_value.setText(job.source_name)
        self.status_value.setText(self._status_text(job.status))
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.worker_thread = DesktopWorkerThread(
            worker=self.transcription_worker,
            job_id=job.job_id,
            source=source,
            parent=self,
        )
        self.worker_thread.finished_with_result.connect(self.on_job_finished)
        self.worker_thread.failed_with_error.connect(self.on_job_failed)
        self.worker_thread.start()
        self.poll_timer.start()

    def _resolve_source(self) -> tuple[str, InputType]:
        if self.mode == "youtube":
            url = self.url_edit.text().strip()
            validated = self.media_service.validate_youtube_url(url)
            return validated, InputType.YOUTUBE_URL

        file_path = self.file_path_edit.text().strip()
        input_type, resolved = self.media_service.validate_local_file(file_path)
        if self.mode == "audio" and input_type != InputType.AUDIO:
            raise ValueError("音声ファイルを選択してください。")
        if self.mode == "video" and input_type != InputType.VIDEO:
            raise ValueError("動画ファイルを選択してください。")
        return str(resolved), input_type

    def refresh_job_status(self) -> None:
        if not self.current_job_id:
            return

        try:
            job = self.job_service.get_job(self.current_job_id)
        except FileNotFoundError:
            return

        self.status_value.setText(self._status_text(job.status))
        self.progress_bar.setValue(job.progress_percent)
        self.eta_value.setText(self._format_eta(job))
        if job.total_chunks:
            self.chunk_value.setText(f"{job.current_chunk or 0} / {job.total_chunks}")
        else:
            self.chunk_value.setText("-")
        if job.error_message:
            self.show_error(job.error_message)
        elif job.warning_message:
            self.show_warning(job.warning_message)
        if job.result_path:
            self.current_result_path = job.result_path
            self.export_result_button.setEnabled(True)
        if job.status in {JobStatus.CANCELLING, JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED}:
            self.stop_button.setEnabled(False)

    def on_job_finished(self, result_text: str, result_path: str) -> None:
        self.poll_timer.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.current_result_path = result_path
        self.result_text.setPlainText(result_text)
        self.export_result_button.setEnabled(bool(result_path))
        self.refresh_job_status()

        if not self.current_job_id:
            return

        try:
            job = self.job_service.get_job(self.current_job_id)
        except FileNotFoundError:
            return

        self._prompt_review_result(job.status)

    def on_job_failed(self, user_message: str) -> None:
        self.poll_timer.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.show_error(user_message)
        self.refresh_job_status()

    def stop_transcription(self) -> None:
        if not self.current_job_id:
            return
        self.job_service.request_cancel(self.current_job_id)
        self.status_value.setText(self._status_text(JobStatus.CANCELLING))
        self.eta_value.setText("-")
        self.stop_button.setEnabled(False)

    def export_result_file(self) -> None:
        if not self.current_result_path:
            QMessageBox.warning(self, "結果未作成", "出力できる結果ファイルがありません。")
            return
        text_result_path = Path(self.current_result_path)
        if not text_result_path.exists():
            QMessageBox.warning(self, "結果ファイル未検出", "結果ファイルが見つかりません。")
            return

        destination_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "結果ファイルを出力する",
            str(text_result_path),
            "Text Files (*.txt);;SubRip Files (*.srt);;JSON Files (*.json)",
        )
        if not destination_path:
            return

        output_format = OutputFormat.from_file_name(destination_path, selected_filter)
        destination = Path(destination_path)
        if destination.suffix.lower() != f".{output_format.value}":
            destination = destination.with_suffix(f".{output_format.value}")

        source_path = text_result_path.with_suffix(f".{output_format.value}")
        if not source_path.exists():
            QMessageBox.warning(self, "結果ファイル未検出", "結果ファイルが見つかりません。")
            return
        destination.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        QMessageBox.information(self, "出力完了", f"{output_format.value.upper()} ファイルを出力しました。")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination)))

    def open_output_directory(self) -> None:
        directory = self._get_current_result_directory()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _reset_status(self) -> None:
        self.error_label.setText("")
        self.warning_label.setText("")
        self.result_text.clear()
        self.progress_bar.setValue(0)
        self.chunk_value.setText("-")
        self.eta_value.setText("-")
        self.current_result_path = None
        self.export_result_button.setEnabled(False)

    def show_error(self, message: str) -> None:
        self.warning_label.setText("")
        self.error_label.setText(message)

    def show_warning(self, message: str) -> None:
        self.error_label.setText("")
        self.warning_label.setText(message)

    def _status_text(self, status: JobStatus) -> str:
        return self.STATUS_LABELS.get(status, status.value)

    def _format_eta(self, job: Job) -> str:
        if job.status == JobStatus.TRANSCRIBING:
            if job.estimated_completion_at:
                estimated = self._parse_datetime(job.estimated_completion_at).astimezone()
                now = datetime.now().astimezone()
                remaining_seconds = max(0, int((estimated - now).total_seconds()))
                estimated_text = estimated.strftime("%H:%M:%S")
                if estimated.date() != now.date():
                    estimated_text = estimated.strftime("%Y-%m-%d %H:%M:%S")
                return f"約 {self._format_duration(remaining_seconds)} ({estimated_text} 頃)"
            return "推定中"
        return "-"

    @staticmethod
    def _format_duration(total_seconds: int) -> str:
        hours, remainder = divmod(max(0, total_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}時間{minutes:02d}分{seconds:02d}秒"
        if minutes:
            return f"{minutes}分{seconds:02d}秒"
        return f"{seconds}秒"

    def _confirm_start(self) -> bool:
        response = QMessageBox.question(
            self,
            "開始確認",
            "文字起こしを開始します。OK を押すと処理を開始します。",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        return response == QMessageBox.StandardButton.Ok

    def _prompt_review_result(self, status: JobStatus) -> None:
        if not self.current_result_path:
            return

        if status == JobStatus.COMPLETED:
            message = "文字起こしが完了しました。文字起こし結果を確認しますか？"
        elif status == JobStatus.CANCELLED:
            message = "文字起こしを停止しました。保存済みの文字起こし結果を確認しますか？"
        else:
            return

        response = QMessageBox.question(
            self,
            "確認",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.open_output_directory()

    def _get_current_result_directory(self) -> Path:
        if self.current_result_path:
            return Path(self.current_result_path).parent
        return self.outputs_dir

    def _extract_supported_drop_path(self, event: QDragEnterEvent | QDropEvent) -> str | None:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return None

        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            try:
                self.media_service.validate_local_file(local_path)
            except Exception:
                continue
            return local_path

        return None

    @staticmethod
    def _parse_datetime(value: datetime) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
