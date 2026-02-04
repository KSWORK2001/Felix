import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass(unsafe_hash=True)
class AppSettings:
    provider: str = "openai"
    gemma_model_id: str = "google/gemma-3-4b-it"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    google_client_secrets_path: str = ""
    ics_url: str = ""


class SettingsStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def _path(self) -> str:
        return os.path.join(self.base_dir, "data", "settings.json")

    def load(self) -> AppSettings:
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            s = AppSettings()
            self.save(s)
            return s

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}

        s = AppSettings()
        for k, v in raw.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

    def save(self, settings: AppSettings) -> None:
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)

    def update(self, patch: Dict[str, Any]) -> AppSettings:
        s = self.load()
        for k, v in patch.items():
            if hasattr(s, k):
                setattr(s, k, v)
        self.save(s)
        return s
