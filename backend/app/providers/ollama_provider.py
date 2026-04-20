from __future__ import annotations

import httpx

from app.core.config import Settings
from app.providers.base import ProviderSnapshot


class OllamaProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.ollama_base_url and self.settings.ollama_model)

    def build_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.settings.ollama_base_url, timeout=30.0)

    def snapshot(self) -> ProviderSnapshot:
        return ProviderSnapshot(
            name="ollama",
            configured=self.configured,
            mode="fallback",
            details={
                "base_url": self.settings.ollama_base_url,
                "model": self.settings.ollama_model,
            },
        )
