from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProviderSnapshot:
    name: str
    configured: bool
    enabled: bool = True
    mode: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "configured": self.configured,
            "enabled": self.enabled,
            "mode": self.mode,
            "details": self.details,
        }
