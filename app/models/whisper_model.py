from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class WhisperModelSpec:
    model_id: str
    label: str
    repo_id: str | None
    local_dir_name: str
    bundled: bool
    downloadable: bool
    requires_notice: bool
    batch_supported: bool
    realtime_supported: bool
    model_card_url: str | None = None
    required_files: tuple[str, ...] = ("model.bin", "config.json")
    condition_on_previous_text: bool = True
