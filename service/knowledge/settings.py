"""Knowledge settings: separate storage, namespaces and embedding identity."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..core import DataError


@dataclass(frozen=True)
class KnowledgeSettings:
    state_dir: Path
    gateway_url: str = "http://127.0.0.1:8092"
    gateway_key: str = ""
    qdrant_url: str = "http://127.0.0.1:6335"
    neo4j_url: str = "bolt://127.0.0.1:7689"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    model: str = "gigachat:EmbeddingsGigaR"
    dimension: int = 2560
    context_tokens: int = 4096
    timeout: float = 30

    @classmethod
    def from_env(cls, project: Path) -> KnowledgeSettings:
        values = {}
        env_file = Path(
            os.environ.get("RESEARCH_KNOWLEDGE_ENV_FILE", project / ".knowledge" / "runtime.env")
        )
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep and key in {"RESEARCH_EMBEDDING_KEY", "RESEARCH_NEO4J_PASSWORD"}:
                    values[key] = value

        def setting(key: str, default: str = "") -> str:
            return os.environ.get(key, values.get(key, default))

        return cls(
            state_dir=Path(os.environ.get("RESEARCH_KNOWLEDGE_DIR", project / ".knowledge")),
            gateway_url=os.environ.get("RESEARCH_EMBEDDING_URL", "http://127.0.0.1:8092"),
            gateway_key=setting("RESEARCH_EMBEDDING_KEY"),
            qdrant_url=os.environ.get("RESEARCH_QDRANT_URL", "http://127.0.0.1:6335"),
            neo4j_url=os.environ.get("RESEARCH_NEO4J_URL", "bolt://127.0.0.1:7689"),
            neo4j_user=os.environ.get("RESEARCH_NEO4J_USER", "neo4j"),
            neo4j_password=setting("RESEARCH_NEO4J_PASSWORD"),
        )

    def validate(self) -> None:
        if self.model != "gigachat:EmbeddingsGigaR" or self.dimension != 2560:
            raise DataError("unsupported knowledge embedding identity")
