from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSource, QMediaDevices


class AudioCaptureError(RuntimeError):
    """Raised when microphone capture cannot be started or controlled."""


class AudioCaptureStatus(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    CAPTURING = "capturing"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class AudioDeviceInfo:
    index: int
    description: str
    is_default: bool
    preferred_sample_rate: int
    preferred_channel_count: int
    supported_sample_formats: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class AudioCaptureFormat:
    sample_rate: int
    channel_count: int
    sample_format: str
    is_fallback: bool = False


@dataclass(slots=True, frozen=True)
class AudioCaptureSnapshot:
    device: AudioDeviceInfo
    requested_format: AudioCaptureFormat
    actual_format: AudioCaptureFormat
    status: AudioCaptureStatus
    buffered_bytes: int
    level_percent: int
    elapsed_seconds: int


class AudioCaptureService(QObject):
    devices_changed = Signal(object)
    status_changed = Signal(object)
    level_changed = Signal(int)
    chunk_captured = Signal(bytes)
    capture_started = Signal(object)
    capture_stopped = Signal(object)

    def __init__(
        self,
        *,
        device_provider: Any = QMediaDevices,
        source_factory: Any = QAudioSource,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_provider = device_provider
        self._source_factory = source_factory
        self._devices_cache: list[QAudioDevice] = []
        self._source: Any | None = None
        self._io_device: Any | None = None
        self._buffer = bytearray()
        self._buffer_lock = Lock()
        self._device_info: AudioDeviceInfo | None = None
        self._requested_format: AudioCaptureFormat | None = None
        self._actual_format: AudioCaptureFormat | None = None
        self._status = AudioCaptureStatus.IDLE
        self._level_percent = 0

    def refresh_devices(self) -> list[AudioDeviceInfo]:
        devices = self._fetch_devices()
        metadata = self._build_device_info_list(devices)
        self.devices_changed.emit(metadata)
        return metadata

    def list_devices(self) -> list[AudioDeviceInfo]:
        if not self._devices_cache:
            return self.refresh_devices()
        return self._build_device_info_list(self._devices_cache)

    def start(
        self,
        device_identifier: int | str | None = None,
        *,
        sample_rate: int = 16000,
        channel_count: int = 1,
        sample_format: QAudioFormat.SampleFormat = QAudioFormat.SampleFormat.Float,
    ) -> AudioCaptureSnapshot:
        self._set_status(AudioCaptureStatus.STARTING)

        device = self._resolve_device(device_identifier)
        requested_format = AudioCaptureFormat(
            sample_rate=sample_rate,
            channel_count=channel_count,
            sample_format=sample_format.name,
        )
        actual_format = self._resolve_capture_format(
            device,
            requested_format=requested_format,
            sample_format=sample_format,
        )

        self._clear_buffer()
        default_device = self._default_device()
        default_description = default_device.description() if default_device is not None else None
        self._device_info = self._device_info_from_device(
            device,
            self._device_index(device),
            default_description=default_description,
        )
        self._requested_format = requested_format
        self._actual_format = actual_format

        try:
            qt_format = self._build_qt_audio_format(actual_format)
            self._source = self._source_factory(device, qt_format, self)
            self._configure_source(self._source, qt_format)
            self._io_device = self._source.start()
            if self._io_device is None:
                raise AudioCaptureError("Failed to start audio input stream.")
            ready_read = getattr(self._io_device, "readyRead", None)
            if ready_read is not None and hasattr(ready_read, "connect"):
                ready_read.connect(self._consume_ready_read)
        except Exception as exc:
            self._set_status(AudioCaptureStatus.FAILED)
            raise AudioCaptureError("Failed to start microphone capture.") from exc

        self._set_status(AudioCaptureStatus.CAPTURING)
        snapshot = self.snapshot()
        self.capture_started.emit(snapshot)
        return snapshot

    def pause(self) -> AudioCaptureSnapshot:
        self._require_active_capture()
        if hasattr(self._source, "suspend"):
            self._source.suspend()
        self._set_status(AudioCaptureStatus.PAUSED)
        snapshot = self.snapshot()
        self.status_changed.emit(snapshot.status)
        return snapshot

    def resume(self) -> AudioCaptureSnapshot:
        self._require_paused_capture()
        if hasattr(self._source, "resume"):
            self._source.resume()
        self._set_status(AudioCaptureStatus.CAPTURING)
        snapshot = self.snapshot()
        self.status_changed.emit(snapshot.status)
        return snapshot

    def stop(self) -> AudioCaptureSnapshot:
        self._consume_ready_read()
        if self._source is not None and hasattr(self._source, "stop"):
            self._source.stop()
        if self._source is not None and hasattr(self._source, "reset"):
            self._source.reset()
        self._io_device = None
        self._source = None
        self._set_status(AudioCaptureStatus.STOPPED)
        snapshot = self.snapshot()
        self.capture_stopped.emit(snapshot)
        return snapshot

    def drain_audio_bytes(self) -> bytes:
        with self._buffer_lock:
            data = bytes(self._buffer)
            self._buffer.clear()
            return data

    def snapshot(self) -> AudioCaptureSnapshot:
        device = self._device_info or self._unknown_device_info()
        requested_format = self._requested_format or self._default_format()
        actual_format = self._actual_format or requested_format
        return AudioCaptureSnapshot(
            device=device,
            requested_format=requested_format,
            actual_format=actual_format,
            status=self._status,
            buffered_bytes=self.buffered_bytes,
            level_percent=self._level_percent,
            elapsed_seconds=self.elapsed_seconds,
        )

    @property
    def buffered_bytes(self) -> int:
        with self._buffer_lock:
            return len(self._buffer)

    @property
    def level_percent(self) -> int:
        return self._level_percent

    @property
    def elapsed_seconds(self) -> int:
        if self._source is None or not hasattr(self._source, "processedUSecs"):
            return 0
        try:
            return max(0, int(round(float(self._source.processedUSecs()) / 1_000_000.0)))
        except Exception:
            return 0

    @property
    def is_active(self) -> bool:
        return self._status == AudioCaptureStatus.CAPTURING

    @property
    def is_paused(self) -> bool:
        return self._status == AudioCaptureStatus.PAUSED

    def _consume_ready_read(self) -> None:
        if self._io_device is None or self._status not in {
            AudioCaptureStatus.CAPTURING,
            AudioCaptureStatus.PAUSED,
        }:
            return

        available = getattr(self._io_device, "bytesAvailable", None)
        read_all = getattr(self._io_device, "readAll", None)
        if read_all is None:
            return

        while True:
            if callable(available) and int(available()) <= 0:
                break
            chunk = bytes(read_all())
            if not chunk:
                break
            if self._status == AudioCaptureStatus.CAPTURING:
                self._append_chunk(chunk)
            if not callable(available):
                break

    def _append_chunk(self, chunk: bytes) -> None:
        with self._buffer_lock:
            self._buffer.extend(chunk)
        self.chunk_captured.emit(chunk)
        self._update_level(chunk)

    def _update_level(self, chunk: bytes) -> None:
        actual_format = self._actual_format or self._default_format()
        level = self._compute_level_percent(chunk, actual_format.sample_format)
        self._level_percent = level
        self.level_changed.emit(level)

    def _resolve_device(self, device_identifier: int | str | None) -> QAudioDevice:
        devices = self._fetch_devices()
        if not devices:
            raise AudioCaptureError("No audio input devices were found.")

        if device_identifier is None:
            default_device = getattr(self._device_provider, "defaultAudioInput", None)
            if callable(default_device):
                return default_device()
            return devices[0]

        if isinstance(device_identifier, int):
            try:
                return devices[device_identifier]
            except IndexError as exc:
                raise AudioCaptureError(f"Audio input device index out of range: {device_identifier}") from exc

        for device in devices:
            if device.description() == device_identifier:
                return device

        raise AudioCaptureError(f"Audio input device not found: {device_identifier}")

    def _resolve_capture_format(
        self,
        device: QAudioDevice,
        *,
        requested_format: AudioCaptureFormat,
        sample_format: QAudioFormat.SampleFormat,
    ) -> AudioCaptureFormat:
        desired_qt_format = self._build_qt_audio_format(requested_format)
        if device.isFormatSupported(desired_qt_format):
            return requested_format

        preferred = device.preferredFormat()
        preferred_sample_format = self._sample_format_name(preferred.sampleFormat())
        return AudioCaptureFormat(
            sample_rate=preferred.sampleRate(),
            channel_count=preferred.channelCount(),
            sample_format=preferred_sample_format,
            is_fallback=True,
        )

    def _build_qt_audio_format(self, capture_format: AudioCaptureFormat) -> QAudioFormat:
        qt_format = QAudioFormat()
        qt_format.setSampleRate(capture_format.sample_rate)
        qt_format.setChannelCount(capture_format.channel_count)
        qt_format.setSampleFormat(self._sample_format_from_name(capture_format.sample_format))
        return qt_format

    def _configure_source(self, source: Any, qt_format: QAudioFormat) -> None:
        buffer_size = self._estimated_buffer_size(qt_format)
        if hasattr(source, "setBufferSize"):
            source.setBufferSize(buffer_size)

    def _fetch_devices(self) -> list[QAudioDevice]:
        devices = list(self._device_provider.audioInputs())
        self._devices_cache = devices
        return devices

    def _device_index(self, device: QAudioDevice) -> int:
        for index, known_device in enumerate(self._devices_cache):
            if known_device.description() == device.description():
                return index
        return 0

    def _build_device_info_list(self, devices: list[QAudioDevice]) -> list[AudioDeviceInfo]:
        default_device = self._default_device()
        default_description = default_device.description() if default_device is not None else None
        return [
            self._device_info_from_device(device, index, default_description=default_description)
            for index, device in enumerate(devices)
        ]

    def _device_info_from_device(
        self,
        device: QAudioDevice,
        index: int,
        *,
        default_description: str | None = None,
    ) -> AudioDeviceInfo:
        preferred = device.preferredFormat()
        return AudioDeviceInfo(
            index=index,
            description=device.description(),
            is_default=default_description is not None and device.description() == default_description,
            preferred_sample_rate=preferred.sampleRate(),
            preferred_channel_count=preferred.channelCount(),
            supported_sample_formats=tuple(
                self._sample_format_name(sample_format) for sample_format in device.supportedSampleFormats()
            ),
        )

    def _default_device(self) -> QAudioDevice | None:
        default_device = getattr(self._device_provider, "defaultAudioInput", None)
        if callable(default_device):
            try:
                return default_device()
            except Exception:
                return None
        return None

    def _unknown_device_info(self) -> AudioDeviceInfo:
        return AudioDeviceInfo(
            index=-1,
            description="unknown",
            is_default=False,
            preferred_sample_rate=0,
            preferred_channel_count=0,
            supported_sample_formats=(),
        )

    def _default_format(self) -> AudioCaptureFormat:
        return AudioCaptureFormat(
            sample_rate=16000,
            channel_count=1,
            sample_format=QAudioFormat.SampleFormat.Float.name,
        )

    def _set_status(self, status: AudioCaptureStatus) -> None:
        self._status = status
        self.status_changed.emit(status)

    def _require_active_capture(self) -> None:
        if self._source is None or self._status != AudioCaptureStatus.CAPTURING:
            raise AudioCaptureError("Microphone capture is not running.")

    def _require_paused_capture(self) -> None:
        if self._source is None or self._status != AudioCaptureStatus.PAUSED:
            raise AudioCaptureError("Microphone capture is not paused.")

    def _clear_buffer(self) -> None:
        with self._buffer_lock:
            self._buffer.clear()
        self._level_percent = 0

    @staticmethod
    def _sample_format_name(sample_format: QAudioFormat.SampleFormat) -> str:
        return sample_format.name

    @staticmethod
    def _sample_format_from_name(name: str) -> QAudioFormat.SampleFormat:
        try:
            return QAudioFormat.SampleFormat[name]
        except KeyError as exc:
            raise AudioCaptureError(f"Unsupported audio sample format: {name}") from exc

    @staticmethod
    def _estimated_buffer_size(qt_format: QAudioFormat) -> int:
        bytes_per_frame = max(1, qt_format.bytesPerFrame())
        return max(4096, bytes_per_frame * max(1, qt_format.sampleRate()) // 4)

    @staticmethod
    def _compute_level_percent(chunk: bytes, sample_format: str) -> int:
        if not chunk:
            return 0

        try:
            if sample_format == QAudioFormat.SampleFormat.Float.name:
                samples = np.frombuffer(chunk, dtype=np.float32)
                if samples.size == 0:
                    return 0
                normalized = np.clip(samples, -1.0, 1.0)
            elif sample_format == QAudioFormat.SampleFormat.Int16.name:
                samples = np.frombuffer(chunk, dtype=np.int16)
                if samples.size == 0:
                    return 0
                normalized = samples.astype(np.float32) / 32768.0
            elif sample_format == QAudioFormat.SampleFormat.Int32.name:
                samples = np.frombuffer(chunk, dtype=np.int32)
                if samples.size == 0:
                    return 0
                normalized = samples.astype(np.float32) / 2_147_483_648.0
            elif sample_format == QAudioFormat.SampleFormat.UInt8.name:
                samples = np.frombuffer(chunk, dtype=np.uint8)
                if samples.size == 0:
                    return 0
                normalized = (samples.astype(np.float32) - 128.0) / 128.0
            else:
                return 0
        except ValueError:
            return 0

        magnitude = np.abs(normalized)
        if magnitude.size == 0:
            return 0
        signal_floor = float(np.percentile(magnitude, 95))
        if signal_floor <= 1e-6:
            return 0

        decibels = 20.0 * float(np.log10(signal_floor))
        min_db = -45.0
        max_db = -8.0
        scaled = (decibels - min_db) / (max_db - min_db)
        return int(round(max(0.0, min(scaled, 1.0)) * 100))
