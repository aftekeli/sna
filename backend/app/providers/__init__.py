from __future__ import annotations

from app.core.config import Settings
from app.providers.registry import ProviderRegistry


def get_provider_registry(settings: Settings) -> ProviderRegistry:
    return ProviderRegistry.from_settings(settings)
