from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.providers.groq_provider import GroqProvider
from app.providers.neo4j_provider import Neo4jProvider
from app.providers.ollama_provider import OllamaProvider


@dataclass(slots=True)
class ProviderRegistry:
    groq: GroqProvider
    neo4j: Neo4jProvider
    ollama: OllamaProvider

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProviderRegistry":
        return cls(
            groq=GroqProvider(settings),
            neo4j=Neo4jProvider(settings),
            ollama=OllamaProvider(settings),
        )

    def snapshot(self, probe_neo4j: bool = False) -> dict[str, dict[str, object]]:
        return {
            "groq": self.groq.snapshot().to_dict(),
            "neo4j": self.neo4j.snapshot(probe=probe_neo4j).to_dict(),
            "ollama": self.ollama.snapshot().to_dict(),
        }
