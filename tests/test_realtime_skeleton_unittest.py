from __future__ import annotations

import unittest

from app.desktop.realtime_worker_thread import RealtimeWorkerThread
from app.models.realtime_session import RealtimeSession, RealtimeSessionStatus
from app.services.realtime_transcription_service import RealtimeTranscriptionSnapshot
from app.services.transcription_service import TranscribedSegment
from app.workers.realtime_worker import RealtimeWorker, RealtimeWorkerResult


class RealtimeSkeletonTests(unittest.TestCase):
    def test_realtime_session_defaults_and_transitions(self) -> None:
        session = RealtimeSession(session_id="session_001")

        self.assertEqual(session.status, RealtimeSessionStatus.IDLE)
        self.assertEqual(session.source_name, "microphone")

        armed = session.with_status(RealtimeSessionStatus.ARMING)
        self.assertEqual(armed.status, RealtimeSessionStatus.ARMING)
        self.assertIsNotNone(armed.started_at)

        partial = armed.with_partial_text("hello")
        self.assertEqual(partial.partial_text, "hello")

        committed = partial.with_committed_text("hello world")
        self.assertEqual(committed.committed_text, "hello world")

        failed = committed.with_error("boom", error_detail="detail")
        self.assertEqual(failed.status, RealtimeSessionStatus.FAILED)
        self.assertEqual(failed.error_message, "boom")
        self.assertEqual(failed.error_detail, "detail")

    def test_realtime_worker_manages_session_state(self) -> None:
        class FakeRealtimeTranscriptionService:
            def reset(self) -> None:
                return None

            def append_audio_chunk(self, *args, **kwargs):
                return RealtimeTranscriptionSnapshot(
                    committed_segments=[TranscribedSegment(start_seconds=0.0, end_seconds=1.0, text="hello")],
                    partial_segments=[TranscribedSegment(start_seconds=1.0, end_seconds=2.0, text="world")],
                    committed_text="hello",
                    partial_text="world",
                    text="hello\nworld",
                    language="ja",
                    buffered_seconds=2.0,
                    committed_until_seconds=1.0,
                    is_final=False,
                )

            def finalize(self, *args, **kwargs):
                return RealtimeTranscriptionSnapshot(
                    committed_segments=[
                        TranscribedSegment(start_seconds=0.0, end_seconds=1.0, text="hello"),
                        TranscribedSegment(start_seconds=1.0, end_seconds=2.0, text="world"),
                    ],
                    partial_segments=[],
                    committed_text="hello\nworld",
                    partial_text="",
                    text="hello\nworld",
                    language="ja",
                    buffered_seconds=0.0,
                    committed_until_seconds=2.0,
                    is_final=True,
                )

        worker = RealtimeWorker(transcription_service=FakeRealtimeTranscriptionService())
        session = RealtimeSession(session_id="session_002")

        with self.assertRaises(NotImplementedError):
            worker.run(session)

        started = worker.start(session)
        self.assertEqual(started.session.status, RealtimeSessionStatus.LISTENING)

        updated = worker.append_audio_chunk(
            b"bytes",
            sample_rate=16000,
            channel_count=1,
            sample_format="Float",
            language="ja",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.session.committed_text, "hello")
        self.assertEqual(updated.session.partial_text, "world")
        self.assertEqual(updated.partial_text, "hello\nworld")

        paused = worker.pause()
        self.assertEqual(paused.session.status, RealtimeSessionStatus.PAUSED)

        resumed = worker.resume()
        self.assertEqual(resumed.session.status, RealtimeSessionStatus.LISTENING)

        stopped = worker.stop(language="ja")
        self.assertEqual(stopped.session.status, RealtimeSessionStatus.COMPLETED)
        self.assertEqual(stopped.final_text, "hello\nworld")

    def test_realtime_worker_thread_exposes_expected_signals(self) -> None:
        self.assertTrue(hasattr(RealtimeWorkerThread, "status_changed"))
        self.assertTrue(hasattr(RealtimeWorkerThread, "partial_result_updated"))
        self.assertTrue(hasattr(RealtimeWorkerThread, "level_updated"))
        self.assertTrue(hasattr(RealtimeWorkerThread, "finished_with_result"))
        self.assertTrue(hasattr(RealtimeWorkerThread, "failed_with_error"))

    def test_realtime_worker_result_structure(self) -> None:
        session = RealtimeSession(session_id="session_003")
        result = RealtimeWorkerResult(session=session, final_text="final", partial_text="partial")

        self.assertIs(result.session, session)
        self.assertEqual(result.final_text, "final")
        self.assertEqual(result.partial_text, "partial")


if __name__ == "__main__":
    unittest.main()
