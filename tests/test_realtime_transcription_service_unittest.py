from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from app.services.realtime_transcription_service import (
    RealtimeTranscriptionError,
    RealtimeTranscriptionService,
)
from app.core.settings import Settings


def make_float32_bytes(seconds: float, sample_rate: int = 16000, value: float = 0.0) -> bytes:
    sample_count = int(round(seconds * sample_rate))
    return np.full(sample_count, value, dtype=np.float32).tobytes()


def make_stereo_int16_bytes(seconds: float, sample_rate: int = 48000) -> bytes:
    sample_count = int(round(seconds * sample_rate))
    left = np.linspace(-12000, 12000, num=sample_count, dtype=np.int16)
    right = -left
    interleaved = np.column_stack([left, right]).reshape(-1)
    return interleaved.astype(np.int16, copy=False).tobytes()


class RealtimeTranscriptionServiceTests(unittest.TestCase):
    def test_append_audio_chunk_waits_until_threshold_then_emits_partial_snapshot(self) -> None:
        loaded_models: list[str | None] = []

        def model_loader(model_size: str | None) -> object:
            loaded_models.append(model_size)
            return object()

        calls: list[np.ndarray] = []

        def transcribe_runner(model: object, audio: np.ndarray, language: str | None):
            calls.append(audio)
            duration_seconds = len(audio) / 16000.0
            if duration_seconds < 4.0:
                segments = [SimpleNamespace(start=0.0, end=duration_seconds, text="hello")]
            else:
                segments = [
                    SimpleNamespace(start=0.0, end=2.0, text="hello"),
                    SimpleNamespace(start=2.0, end=4.0, text="world"),
                ]
            return segments, SimpleNamespace(language="ja", duration=duration_seconds)

        service = RealtimeTranscriptionService(
            model_loader=model_loader,
            transcribe_runner=transcribe_runner,
            window_seconds=4.0,
            lookback_seconds=1.0,
            min_chunk_seconds=2.0,
            max_buffer_seconds=8.0,
        )

        first = service.append_audio_chunk(
            make_float32_bytes(1.0),
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
        )
        self.assertIsNone(first)
        self.assertEqual(calls, [])

        second = service.append_audio_chunk(
            make_float32_bytes(1.0),
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
        )

        self.assertIsNotNone(second)
        self.assertEqual(loaded_models, [None])
        self.assertEqual(len(calls), 1)
        self.assertEqual(second.language, "ja")
        self.assertEqual([segment.text for segment in second.committed_segments], [])
        self.assertEqual([segment.text for segment in second.partial_segments], ["hello"])
        self.assertEqual(second.partial_text, "hello")
        self.assertEqual(second.committed_text, "")

        third = service.append_audio_chunk(
            make_float32_bytes(2.0),
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
        )

        self.assertIsNotNone(third)
        self.assertEqual(len(calls), 2)
        self.assertEqual([segment.text for segment in third.committed_segments], ["hello"])
        self.assertEqual([segment.text for segment in third.partial_segments], ["world"])
        self.assertEqual(third.committed_text, "hello")
        self.assertEqual(third.partial_text, "world")
        self.assertEqual(third.text, "hello\nworld")

        final = service.finalize()
        self.assertTrue(final.is_final)
        self.assertEqual([segment.text for segment in final.committed_segments], ["hello", "world"])
        self.assertEqual(final.partial_text, "")
        self.assertEqual(final.text, "hello\nworld")

    def test_append_audio_chunk_resamples_stereo_int16_to_mono_target_rate(self) -> None:
        captured_audio: list[np.ndarray] = []

        def transcribe_runner(model: object, audio: np.ndarray, language: str | None):
            captured_audio.append(audio)
            return [SimpleNamespace(start=0.0, end=0.5, text="ok")], SimpleNamespace(language=None, duration=0.5)

        service = RealtimeTranscriptionService(
            model_loader=lambda model_size: object(),
            transcribe_runner=transcribe_runner,
            window_seconds=1.0,
            lookback_seconds=0.0,
            min_chunk_seconds=0.25,
            max_buffer_seconds=2.0,
        )

        snapshot = service.append_audio_chunk(
            make_stereo_int16_bytes(0.5),
            sample_rate=48000,
            channel_count=2,
            sample_format="Int16",
            force_transcribe=True,
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(len(captured_audio), 1)
        audio = captured_audio[0]
        self.assertTrue(7900 <= len(audio) <= 8100)
        self.assertAlmostEqual(float(np.mean(audio)), 0.0, places=3)
        self.assertEqual(snapshot.committed_text, "ok")
        self.assertEqual(snapshot.partial_text, "")

    def test_unsupported_sample_format_raises_clear_error(self) -> None:
        service = RealtimeTranscriptionService(
            model_loader=lambda model_size: object(),
            transcribe_runner=lambda model, audio, language: [],
        )

        with self.assertRaises(RealtimeTranscriptionError):
            service.append_audio_chunk(
                b"payload",
                sample_rate=16000,
                channel_count=1,
                sample_format="BadFormat",
                force_transcribe=True,
            )

    def test_transcription_is_throttled_between_small_chunks(self) -> None:
        calls: list[np.ndarray] = []

        def transcribe_runner(model: object, audio: np.ndarray, language: str | None):
            calls.append(audio)
            return [SimpleNamespace(start=0.0, end=0.5, text="ok")], SimpleNamespace(language="ja")

        service = RealtimeTranscriptionService(
            model_loader=lambda model_size: object(),
            transcribe_runner=transcribe_runner,
            min_chunk_seconds=0.5,
            transcription_interval_seconds=1.0,
        )

        first = service.append_audio_chunk(
            make_float32_bytes(0.5, value=0.01),
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
        )
        self.assertIsNotNone(first)
        self.assertEqual(len(calls), 1)

        second = service.append_audio_chunk(
            make_float32_bytes(0.25, value=0.01),
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
        )
        self.assertIsNone(second)
        self.assertEqual(len(calls), 1)

        third = service.append_audio_chunk(
            make_float32_bytes(0.75, value=0.01),
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
        )
        self.assertIsNotNone(third)
        self.assertEqual(len(calls), 2)
        self.assertGreater(float(np.max(np.abs(calls[0]))), 0.01)

    def test_default_runner_uses_model_specific_decode_options(self) -> None:
        captured_kwargs: dict[str, object] = {}

        class FakeModel:
            def transcribe(self, audio: np.ndarray, **kwargs):
                captured_kwargs.update(kwargs)
                return [SimpleNamespace(start=0.0, end=0.5, text="ok")], SimpleNamespace(language="ja")

        service = RealtimeTranscriptionService(
            settings=Settings(),
            model_loader=lambda model_size: FakeModel(),
            min_chunk_seconds=0.25,
        )

        snapshot = service.append_audio_chunk(
            make_float32_bytes(0.5, value=0.01),
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
            language="ja",
            model_size="kotoba-whisper-v2.0-faster",
            force_transcribe=True,
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(
            captured_kwargs,
            {
                "language": "ja",
                "vad_filter": False,
                "word_timestamps": False,
                "condition_on_previous_text": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
