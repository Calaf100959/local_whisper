from __future__ import annotations

from app.services.diarization_service import DiarizedSegment
from app.services.transcription_service import TranscribedSegment, TranscriptionResult


class SpeakerAssignmentService:
    def assign_speakers(
        self,
        result: TranscriptionResult,
        diarized_segments: list[DiarizedSegment],
    ) -> TranscriptionResult:
        if not diarized_segments:
            return result

        updated_segments = [
            TranscribedSegment(
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=segment.text,
                speaker=self._pick_speaker(segment, diarized_segments),
            )
            for segment in result.segments
        ]
        return TranscriptionResult(
            text=TranscriptionResult(text="", segments=updated_segments, language=result.language).render_text(),
            segments=updated_segments,
            language=result.language,
        )

    @staticmethod
    def _pick_speaker(
        segment: TranscribedSegment,
        diarized_segments: list[DiarizedSegment],
    ) -> str | None:
        best_speaker: str | None = None
        best_overlap = 0.0

        for diarized_segment in diarized_segments:
            overlap = SpeakerAssignmentService._calculate_overlap_seconds(segment, diarized_segment)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = diarized_segment.speaker

        return best_speaker

    @staticmethod
    def _calculate_overlap_seconds(
        segment: TranscribedSegment,
        diarized_segment: DiarizedSegment,
    ) -> float:
        start = max(segment.start_seconds, diarized_segment.start_seconds)
        end = min(segment.end_seconds, diarized_segment.end_seconds)
        return max(0.0, end - start)
