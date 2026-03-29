from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib import resources as importlib_resources
from io import BytesIO
import os
from pathlib import Path
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings


logger = get_logger(__name__)


class DiarizationError(RuntimeError):
    """Raised when speaker diarization fails."""


@dataclass(slots=True, frozen=True)
class DiarizedSegment:
    start_seconds: float
    end_seconds: float
    speaker: str


@dataclass(slots=True, frozen=True)
class SpeechWindow:
    start_seconds: float
    end_seconds: float


class DiarizationService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._vad_model: Any | None = None
        self._encoder_cache: dict[str, Any] = {}

    def diarize(
        self,
        source_path: str | Path,
        *,
        num_speakers: int | None = None,
    ) -> list[DiarizedSegment]:
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"Source audio file not found: {path}")

        waveform = self._load_audio(path)
        speech_windows = self._detect_speech_windows(waveform)
        if not speech_windows:
            return []

        embeddings = self._extract_embeddings(waveform, speech_windows)
        speaker_indexes = self._cluster_embeddings(embeddings, num_speakers=num_speakers)
        return self._build_diarized_segments(speech_windows, speaker_indexes)

    def _load_audio(self, source_path: Path) -> Any:
        try:
            av = import_module("av")
            torch = import_module("torch")
        except ModuleNotFoundError as exc:
            logger.exception("Audio decoding dependency import failed")
            raise DiarizationError("Speaker diarization dependencies are not installed.") from exc

        try:
            container = av.open(str(source_path))
            audio_stream = next((stream for stream in container.streams if stream.type == "audio"), None)
            if audio_stream is None:
                raise DiarizationError(f"音声ストリームが見つかりません: {source_path.name}")

            resampler = av.audio.resampler.AudioResampler(
                format="fltp",
                layout="mono",
                rate=self.settings.diarization_sample_rate,
            )
            waveform_chunks: list[np.ndarray] = []
            for frame in container.decode(audio_stream):
                for resampled_frame in resampler.resample(frame):
                    chunk = resampled_frame.to_ndarray()
                    if chunk.ndim == 1:
                        chunk = chunk[np.newaxis, :]
                    waveform_chunks.append(chunk.astype(np.float32, copy=False))
        except Exception as exc:  # pragma: no cover - backend specific
            logger.exception("Failed to load audio for diarization: source=%s", source_path)
            raise DiarizationError(f"話者分離用の音声読み込みに失敗しました: {source_path.name}") from exc

        if not waveform_chunks:
            raise DiarizationError(f"話者分離用の音声データが空です: {source_path.name}")

        waveform = np.concatenate(waveform_chunks, axis=1)
        mono_waveform = torch.from_numpy(waveform.squeeze(0)).to(torch.float32).contiguous()
        if mono_waveform.ndim != 1:
            raise DiarizationError("話者分離用の音声をモノラル化できませんでした。")
        return mono_waveform

    def _detect_speech_windows(self, waveform: Any) -> list[SpeechWindow]:
        vad_model = self._load_vad_model()

        try:
            silero_vad = import_module("silero_vad")
            raw_windows = silero_vad.get_speech_timestamps(
                waveform,
                vad_model,
                sampling_rate=self.settings.diarization_sample_rate,
                min_speech_duration_ms=int(self.settings.diarization_min_segment_seconds * 1000),
                return_seconds=True,
            )
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Silero VAD failed")
            raise DiarizationError("話者分離用の発話区間検出に失敗しました。") from exc

        speech_windows = [
            SpeechWindow(
                start_seconds=float(window["start"]),
                end_seconds=float(window["end"]),
            )
            for window in raw_windows
            if float(window["end"]) - float(window["start"]) >= self.settings.diarization_min_segment_seconds
        ]
        merged_windows = self._merge_adjacent_windows(speech_windows)
        return self._split_long_windows(merged_windows)

    def _load_vad_model(self) -> Any:
        if self._vad_model is not None:
            return self._vad_model

        try:
            torch = import_module("torch")
            model_bytes = self._read_vad_model_bytes()
            self._vad_model = torch.jit.load(BytesIO(model_bytes), map_location=torch.device("cpu"))
            self._vad_model.eval()
        except ModuleNotFoundError as exc:
            logger.exception("Silero VAD dependencies are unavailable")
            raise DiarizationError("Speaker diarization dependencies are not installed.") from exc
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Failed to load Silero VAD model")
            raise DiarizationError("話者分離用の VAD モデル読み込みに失敗しました。") from exc

        return self._vad_model

    @staticmethod
    def _read_vad_model_bytes() -> bytes:
        resource = importlib_resources.files("silero_vad.data").joinpath("silero_vad.jit")
        with resource.open("rb") as stream:
            return stream.read()

    def _extract_embeddings(
        self,
        waveform: Any,
        speech_windows: list[SpeechWindow],
    ) -> list[np.ndarray]:
        classifier = self._load_embedding_classifier()
        sample_rate = self.settings.diarization_sample_rate
        embeddings: list[np.ndarray] = []

        for window in speech_windows:
            start_index = int(window.start_seconds * sample_rate)
            end_index = int(window.end_seconds * sample_rate)
            speech_waveform = waveform[start_index:end_index]
            if speech_waveform.numel() == 0:
                continue

            try:
                embedding = classifier.encode_batch(speech_waveform.unsqueeze(0))
            except Exception as exc:  # pragma: no cover - external library errors vary
                logger.exception(
                    "Failed to extract speaker embedding: start=%s end=%s",
                    window.start_seconds,
                    window.end_seconds,
                )
                raise DiarizationError("話者分離用の話者埋め込み抽出に失敗しました。") from exc

            embeddings.append(embedding.detach().cpu().numpy().reshape(-1))

        if not embeddings:
            raise DiarizationError("話者分離に必要な発話区間が取得できませんでした。")

        return embeddings

    def _load_embedding_classifier(self) -> Any:
        model_source, savedir = self._resolve_embedding_model_source()
        cache_key = f"{model_source}|{savedir}"
        if cache_key in self._encoder_cache:
            return self._encoder_cache[cache_key]

        try:
            torchaudio = import_module("torchaudio")
            self._patch_torchaudio_for_speechbrain(torchaudio)
            speaker_module = import_module("speechbrain.inference.speaker")
            fetching_module = import_module("speechbrain.utils.fetching")
        except ModuleNotFoundError as exc:
            logger.exception("speechbrain import failed")
            raise DiarizationError("Speaker diarization dependencies are not installed.") from exc
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Failed to prepare speechbrain imports")
            raise DiarizationError("話者分離用の SpeechBrain 初期化に失敗しました。") from exc

        try:
            classifier = speaker_module.EncoderClassifier.from_hparams(
                source=model_source,
                savedir=savedir,
                overrides={"pretrained_path": model_source},
                run_opts={"device": "cpu"},
                local_strategy=fetching_module.LocalStrategy.NO_LINK,
            )
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Failed to load speaker embedding model: source=%s savedir=%s", model_source, savedir)
            raise DiarizationError("話者分離用の埋め込みモデル読み込みに失敗しました。") from exc

        self._encoder_cache[cache_key] = classifier
        return classifier

    def _resolve_embedding_model_source(self) -> tuple[str, str]:
        bundled_model_path = self.settings.bundled_diarization_model_path()
        if self._is_ready_model_directory(bundled_model_path):
            return str(bundled_model_path), str(bundled_model_path)

        downloaded_model_path = self.settings.downloaded_diarization_model_path()
        if self._is_ready_model_directory(downloaded_model_path):
            return str(downloaded_model_path), str(downloaded_model_path)

        self._download_embedding_model_snapshot(downloaded_model_path)
        return str(downloaded_model_path), str(downloaded_model_path)

    def _download_embedding_model_snapshot(self, target_dir: Path) -> None:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        self.settings.huggingface_home_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(self.settings.huggingface_home_dir))
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        self._disable_huggingface_progress_bars()

        try:
            huggingface_hub = import_module("huggingface_hub")
            huggingface_hub.snapshot_download(
                repo_id=self.settings.diarization_embedding_model_repo_id,
                local_dir=str(target_dir),
            )
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception(
                "Failed to download speaker embedding model: repo_id=%s target_dir=%s",
                self.settings.diarization_embedding_model_repo_id,
                target_dir,
            )
            raise DiarizationError("話者分離用の埋め込みモデル取得に失敗しました。") from exc

        if not self._is_ready_model_directory(target_dir):
            raise DiarizationError("話者分離用の埋め込みモデル取得が完了しませんでした。")

    @staticmethod
    def _disable_huggingface_progress_bars() -> None:
        try:
            huggingface_hub_utils = import_module("huggingface_hub.utils")
            disable_progress_bars = getattr(huggingface_hub_utils, "disable_progress_bars", None)
            if callable(disable_progress_bars):
                disable_progress_bars()
        except Exception:
            logger.debug("Failed to disable Hugging Face progress bars before diarization model download.", exc_info=True)

    def _cluster_embeddings(
        self,
        embeddings: list[np.ndarray],
        *,
        num_speakers: int | None = None,
    ) -> list[int]:
        if len(embeddings) == 1:
            return [0]

        try:
            cluster_module = import_module("sklearn.cluster")
        except ModuleNotFoundError as exc:
            logger.exception("scikit-learn import failed")
            raise DiarizationError("Speaker diarization dependencies are not installed.") from exc

        embedding_matrix = np.stack(embeddings, axis=0)
        if num_speakers:
            clusterer = cluster_module.AgglomerativeClustering(
                n_clusters=min(num_speakers, len(embeddings)),
                metric="cosine",
                linkage="average",
            )
        else:
            clusterer = cluster_module.AgglomerativeClustering(
                n_clusters=None,
                metric="cosine",
                linkage="average",
                distance_threshold=self.settings.diarization_clustering_distance_threshold,
            )

        try:
            labels = clusterer.fit_predict(embedding_matrix)
        except Exception as exc:  # pragma: no cover - external library errors vary
            logger.exception("Speaker clustering failed")
            raise DiarizationError("話者分離用のクラスタリングに失敗しました。") from exc

        return self._normalize_cluster_labels(labels.tolist())

    def _build_diarized_segments(
        self,
        speech_windows: list[SpeechWindow],
        speaker_indexes: list[int],
    ) -> list[DiarizedSegment]:
        diarized_segments = [
            DiarizedSegment(
                start_seconds=window.start_seconds,
                end_seconds=window.end_seconds,
                speaker=f"SPEAKER_{speaker_index:02d}",
            )
            for window, speaker_index in zip(speech_windows, speaker_indexes, strict=False)
        ]
        return self._merge_adjacent_diarized_segments(diarized_segments)

    def _merge_adjacent_windows(self, windows: list[SpeechWindow]) -> list[SpeechWindow]:
        if not windows:
            return []

        merged_windows: list[SpeechWindow] = [windows[0]]
        for window in windows[1:]:
            previous = merged_windows[-1]
            if window.start_seconds - previous.end_seconds <= self.settings.diarization_merge_gap_seconds:
                merged_windows[-1] = SpeechWindow(
                    start_seconds=previous.start_seconds,
                    end_seconds=window.end_seconds,
                )
                continue
            merged_windows.append(window)
        return merged_windows

    def _split_long_windows(self, windows: list[SpeechWindow]) -> list[SpeechWindow]:
        max_segment_seconds = self.settings.diarization_max_segment_seconds
        split_windows: list[SpeechWindow] = []

        for window in windows:
            current_start = window.start_seconds
            while current_start < window.end_seconds:
                current_end = min(window.end_seconds, current_start + max_segment_seconds)
                if current_end - current_start >= self.settings.diarization_min_segment_seconds:
                    split_windows.append(
                        SpeechWindow(
                            start_seconds=current_start,
                            end_seconds=current_end,
                        )
                    )
                current_start = current_end
        return split_windows

    @staticmethod
    def _normalize_cluster_labels(labels: list[int]) -> list[int]:
        mapping: dict[int, int] = {}
        normalized: list[int] = []
        next_label = 0

        for label in labels:
            if label not in mapping:
                mapping[label] = next_label
                next_label += 1
            normalized.append(mapping[label])

        return normalized

    def _merge_adjacent_diarized_segments(
        self,
        diarized_segments: list[DiarizedSegment],
    ) -> list[DiarizedSegment]:
        if not diarized_segments:
            return []

        merged_segments: list[DiarizedSegment] = [diarized_segments[0]]
        for segment in diarized_segments[1:]:
            previous = merged_segments[-1]
            if (
                segment.speaker == previous.speaker
                and segment.start_seconds - previous.end_seconds <= self.settings.diarization_merge_gap_seconds
            ):
                merged_segments[-1] = DiarizedSegment(
                    start_seconds=previous.start_seconds,
                    end_seconds=segment.end_seconds,
                    speaker=previous.speaker,
                )
                continue
            merged_segments.append(segment)
        return merged_segments

    @staticmethod
    def _patch_torchaudio_for_speechbrain(torchaudio: Any) -> None:
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["ffmpeg"]

    @staticmethod
    def _is_ready_model_directory(path: Path) -> bool:
        return path.is_dir() and (path / "hyperparams.yaml").exists() and (path / "embedding_model.ckpt").exists()
