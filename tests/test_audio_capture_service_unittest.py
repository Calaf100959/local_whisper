from __future__ import annotations

from dataclasses import dataclass
import unittest

import numpy as np
from PySide6.QtMultimedia import QAudioFormat

from app.services.audio_capture_service import (
    AudioCaptureService,
    AudioCaptureStatus,
)


class FakeSignal:
    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()


@dataclass
class FakeFormat:
    sample_rate: int
    channel_count: int
    sample_format: QAudioFormat.SampleFormat

    def sampleRate(self) -> int:  # noqa: N802
        return self.sample_rate

    def channelCount(self) -> int:  # noqa: N802
        return self.channel_count

    def sampleFormat(self) -> QAudioFormat.SampleFormat:  # noqa: N802
        return self.sample_format


class FakeIODevice:
    def __init__(self) -> None:
        self.readyRead = FakeSignal()
        self._pending = bytearray()

    def queue_bytes(self, payload: bytes) -> None:
        self._pending.extend(payload)

    def bytesAvailable(self) -> int:  # noqa: N802
        return len(self._pending)

    def readAll(self) -> bytes:  # noqa: N802
        payload = bytes(self._pending)
        self._pending.clear()
        return payload


class FakeAudioDevice:
    def __init__(
        self,
        description: str,
        *,
        preferred_format: FakeFormat,
        supported_sample_formats: list[QAudioFormat.SampleFormat],
        supports_requested_format: bool = True,
    ) -> None:
        self._description = description
        self._preferred_format = preferred_format
        self._supported_sample_formats = supported_sample_formats
        self._supports_requested_format = supports_requested_format
        self.io_device = FakeIODevice()

    def description(self) -> str:  # noqa: N802
        return self._description

    def preferredFormat(self) -> FakeFormat:  # noqa: N802
        return self._preferred_format

    def supportedSampleFormats(self) -> list[QAudioFormat.SampleFormat]:  # noqa: N802
        return self._supported_sample_formats

    def isFormatSupported(self, qt_format: QAudioFormat) -> bool:  # noqa: N802
        return self._supports_requested_format and qt_format.sampleFormat() in self._supported_sample_formats


class FakeAudioSource:
    def __init__(self, device: FakeAudioDevice, qt_format: QAudioFormat, parent=None) -> None:
        self.device = device
        self.qt_format = qt_format
        self.parent = parent
        self.buffer_size = None
        self.start_calls = 0
        self.suspend_calls = 0
        self.resume_calls = 0
        self.stop_calls = 0
        self.reset_calls = 0

    def setBufferSize(self, size: int) -> None:  # noqa: N802
        self.buffer_size = size

    def start(self) -> FakeIODevice:
        self.start_calls += 1
        return self.device.io_device

    def suspend(self) -> None:
        self.suspend_calls += 1

    def resume(self) -> None:
        self.resume_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def reset(self) -> None:
        self.reset_calls += 1


class FakeMediaDevices:
    def __init__(self, devices: list[FakeAudioDevice]) -> None:
        self._devices = devices

    def audioInputs(self) -> list[FakeAudioDevice]:
        return self._devices

    def defaultAudioInput(self) -> FakeAudioDevice:
        return self._devices[0]


class AudioCaptureServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.primary_device = FakeAudioDevice(
            "Primary Mic",
            preferred_format=FakeFormat(48000, 1, QAudioFormat.SampleFormat.Float),
            supported_sample_formats=[
                QAudioFormat.SampleFormat.Float,
                QAudioFormat.SampleFormat.Int16,
            ],
        )
        self.secondary_device = FakeAudioDevice(
            "Backup Mic",
            preferred_format=FakeFormat(44100, 2, QAudioFormat.SampleFormat.Int16),
            supported_sample_formats=[QAudioFormat.SampleFormat.Int16],
        )
        self.provider = FakeMediaDevices([self.primary_device, self.secondary_device])
        self.source_factory = FakeAudioSource

    def test_refresh_devices_returns_metadata(self) -> None:
        service = AudioCaptureService(
            device_provider=self.provider,
            source_factory=self.source_factory,
        )

        devices = service.refresh_devices()

        self.assertEqual([device.description for device in devices], ["Primary Mic", "Backup Mic"])
        self.assertTrue(devices[0].is_default)
        self.assertEqual(devices[0].preferred_sample_rate, 48000)
        self.assertIn("Float", devices[0].supported_sample_formats)

    def test_start_pause_resume_stop_and_level_updates(self) -> None:
        service = AudioCaptureService(
            device_provider=self.provider,
            source_factory=self.source_factory,
        )

        started = service.start("Primary Mic")
        self.assertEqual(started.status, AudioCaptureStatus.CAPTURING)
        self.assertEqual(started.requested_format.sample_rate, 16000)
        self.assertEqual(started.actual_format.sample_rate, 16000)
        self.assertFalse(started.actual_format.is_fallback)
        self.assertTrue(service.is_active)

        payload = np.array([0.0, 0.5, -0.5], dtype=np.float32).tobytes()
        self.primary_device.io_device.queue_bytes(payload)
        self.primary_device.io_device.readyRead.emit()

        self.assertGreaterEqual(service.level_percent, 95)
        self.assertEqual(service.buffered_bytes, len(payload))
        self.assertEqual(service.drain_audio_bytes(), payload)
        self.assertEqual(service.buffered_bytes, 0)

        paused = service.pause()
        self.assertEqual(paused.status, AudioCaptureStatus.PAUSED)
        self.assertEqual(service._source.suspend_calls, 1)  # noqa: SLF001

        resumed = service.resume()
        self.assertEqual(resumed.status, AudioCaptureStatus.CAPTURING)
        self.assertEqual(service._source.resume_calls, 1)  # noqa: SLF001

        fake_source = service._source
        stopped = service.stop()
        self.assertEqual(stopped.status, AudioCaptureStatus.STOPPED)
        self.assertEqual(fake_source.stop_calls, 1)
        self.assertEqual(fake_source.reset_calls, 1)

    def test_start_falls_back_to_preferred_format_when_requested_unsupported(self) -> None:
        unsupported_device = FakeAudioDevice(
            "Fallback Mic",
            preferred_format=FakeFormat(44100, 2, QAudioFormat.SampleFormat.Int16),
            supported_sample_formats=[QAudioFormat.SampleFormat.Int16],
            supports_requested_format=False,
        )
        provider = FakeMediaDevices([unsupported_device])
        service = AudioCaptureService(device_provider=provider, source_factory=self.source_factory)

        started = service.start(0)

        self.assertTrue(started.actual_format.is_fallback)
        self.assertEqual(started.actual_format.sample_rate, 44100)
        self.assertEqual(started.actual_format.channel_count, 2)
        self.assertEqual(started.actual_format.sample_format, "Int16")
        self.assertEqual(service._source.qt_format.sampleRate(), 44100)  # noqa: SLF001
        self.assertEqual(service._source.qt_format.channelCount(), 2)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
