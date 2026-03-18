from __future__ import annotations

from dataclasses import dataclass

from app.services.diarization_service import DiarizationError
from app.services.ffmpeg_service import FFmpegError
from app.services.transcription_service import TranscriptionError
from app.services.youtube_service import YouTubeDownloadError


@dataclass(slots=True)
class AppError(Exception):
    user_message: str
    status_code: int = 500

    def __str__(self) -> str:
        return self.user_message


class BadRequestError(AppError):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message=user_message, status_code=400)


class NotFoundError(AppError):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message=user_message, status_code=404)


class ConflictError(AppError):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message=user_message, status_code=409)


class DependencyError(AppError):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message=user_message, status_code=503)


def to_user_message(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "対象ファイルが見つかりません。パスを確認してください。"
    if isinstance(exc, FFmpegError):
        return "音声・動画の前処理に失敗しました。ffmpeg の設定を確認してください。"
    if isinstance(exc, YouTubeDownloadError):
        return "YouTube 動画の取得に失敗しました。URL または接続状況を確認してください。"
    if isinstance(exc, TranscriptionError):
        return "文字起こしに失敗しました。モデル設定や依存関係を確認してください。"
    if isinstance(exc, DiarizationError):
        return "話者分離に失敗しました。話者分離モデルや依存関係を確認してください。"
    if isinstance(exc, ValueError):
        return "入力内容が正しくありません。内容を確認してください。"
    return "処理中にエラーが発生しました。設定や入力内容を確認してください。"
