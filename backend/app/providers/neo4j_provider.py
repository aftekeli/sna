from __future__ import annotations

from neo4j import GraphDatabase

from app.core.config import Settings
from app.providers.base import ProviderSnapshot


class Neo4jProvider:
    """Thin Neo4j Aura client wrapper used by routes and KG-RAG graph traversal."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return all(
            [
                self.settings.neo4j_uri,
                self.settings.neo4j_username,
                self.settings.neo4j_password,
            ]
        )

    def build_driver(self):
        if not self.configured:
            raise ValueError("Neo4j provider is not configured.")
        return GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_username, self.settings.neo4j_password),
        )

    def run_query(
        self,
        query: str,
        *,
        parameters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        if not self.configured:
            raise ValueError("Neo4j provider is not configured.")
        with self.build_driver() as driver:
            with driver.session(database=self.settings.neo4j_database) as session:
                return session.run(query, parameters or {}).data()

    def snapshot(self, probe: bool = False) -> ProviderSnapshot:
        details: dict[str, object] = {
            "uri": self.settings.neo4j_uri,
            "database": self.settings.neo4j_database,
        }
        if probe and self.configured:
            try:
                with self.build_driver() as driver:
                    driver.verify_connectivity()
                details["connectivity"] = "ok"
            except Exception as exc:  # pragma: no cover - network dependent
                details["connectivity"] = f"error: {exc}"
        return ProviderSnapshot(
            name="neo4j",
            configured=self.configured,
            mode="aura",
            details=details,
        )
