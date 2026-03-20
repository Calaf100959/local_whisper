from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class RealtimePanel(QGroupBox):
    refresh_devices_requested = Signal()
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__("リアルタイム入力")
        self._build_ui()
        self._wire_events()
        self.set_devices(["デバイスを読み込んでください"])
        self.set_running_state(is_running=False, is_paused=False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.refresh_button = QPushButton("デバイス更新")
        device_row.addWidget(QLabel("入力デバイス"))
        device_row.addWidget(self.device_combo, stretch=1)
        device_row.addWidget(self.refresh_button)
        layout.addLayout(device_row)

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        model_row.addWidget(QLabel("モデル"))
        model_row.addWidget(self.model_combo, stretch=1)
        layout.addLayout(model_row)

        info_grid = QGridLayout()
        info_grid.addWidget(QLabel("状態"), 0, 0)
        self.session_status_value = QLabel("未開始")
        info_grid.addWidget(self.session_status_value, 0, 1)

        info_grid.addWidget(QLabel("録音時間"), 0, 2)
        self.elapsed_value = QLabel("00:00:00")
        info_grid.addWidget(self.elapsed_value, 0, 3)

        info_grid.addWidget(QLabel("入力レベル"), 1, 0)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        info_grid.addWidget(self.level_bar, 1, 1, 1, 3)
        layout.addLayout(info_grid)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("録音開始")
        self.pause_button = QPushButton("一時停止")
        self.resume_button = QPushButton("再開")
        self.stop_button = QPushButton("停止")
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.pause_button)
        button_row.addWidget(self.resume_button)
        button_row.addWidget(self.stop_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.note_label = QLabel(
            "v0.2.0 ではマイク入力のリアルタイム文字起こしを追加予定です。"
            " この画面は先行して UI の土台を分離したものです。"
        )
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #5f6c66;")
        layout.addWidget(self.note_label)

    def _wire_events(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_devices_requested.emit)
        self.start_button.clicked.connect(self.start_requested.emit)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)

    def set_devices(self, device_names: list[str], *, selected_name: str | None = None) -> None:
        self.device_combo.clear()
        self.device_combo.addItems(device_names or ["利用可能な入力デバイスがありません"])

        if selected_name:
            index = self.device_combo.findText(selected_name)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)

    def selected_device_name(self) -> str:
        return self.device_combo.currentText().strip()

    def set_models(self, models: list[tuple[str, str]], *, selected_value: str | None = None) -> None:
        self.model_combo.clear()
        for label, value in models:
            self.model_combo.addItem(label, value)

        if selected_value:
            index = self.model_combo.findData(selected_value)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)

    def selected_model_size(self) -> str | None:
        value = self.model_combo.currentData()
        return str(value) if value is not None else None

    def set_session_state(self, status_text: str) -> None:
        self.session_status_value.setText(status_text)

    def set_elapsed_seconds(self, elapsed_seconds: int) -> None:
        bounded = max(0, int(elapsed_seconds))
        hours, remainder = divmod(bounded, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.elapsed_value.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def set_level(self, level: int) -> None:
        self.level_bar.setValue(max(0, min(int(level), 100)))

    def set_running_state(self, *, is_running: bool, is_paused: bool) -> None:
        self.start_button.setEnabled(not is_running)
        self.pause_button.setEnabled(is_running and not is_paused)
        self.resume_button.setEnabled(is_running and is_paused)
        self.stop_button.setEnabled(is_running)
