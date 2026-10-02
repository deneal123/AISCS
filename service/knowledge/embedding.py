"""Pinned embeddings and persistent content-addressed cache; never change providers."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3

import httpx

from ..core import DataError
from .settings import KnowledgeSettings

QUERY_PREFIX = "Find a passage answering the research question. Question: "
FORMAT_VERSION = "retrieval-v1"


class Embedder:
    def __init__(self, settings: KnowledgeSettings):
        self.settings = settings
        settings.validate()

    def request(self, route: str, payload: dict) -> dict | list:
        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.post(
                    self.settings.gateway_url.rstrip("/") + route,
                    headers={"Authorization": "Bearer " + self.settings.gateway_key},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataError("embedding gateway unavailable or invalid response") from exc

    def token_count(self, text: str) -> int:
        return self.count_many([text])[0]

    def embed(self, text: str, *, query: bool = False) -> list[float]:
        value = QUERY_PREFIX + text if query else text
        key = hashlib.sha256(
            (self.settings.model + "\0" + FORMAT_VERSION + "\0" + value).encode()
        ).hexdigest()
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.settings.state_dir / "embeddings.sqlite3") as cache:
            cache.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, data TEXT)")
            hit = cache.execute("SELECT data FROM embeddings WHERE key=?", (key,)).fetchone()
            if hit:
                return self.validate_vector(json.loads(hit[0]))
            tokens = self.token_count(value)
            if tokens > self.settings.context_tokens:
                raise DataError("embedding input exceeds model context; split before indexing")
            response = self.request(
                "/v1/embeddings", {"model": self.settings.model, "input": [value]}
            )
            if not isinstance(response, dict) or response.get("model") != "EmbeddingsGigaR":
                raise DataError("embedding model mismatch")
            items = response.get("data", [])
            if (
                len(items) != 1
                or not isinstance(items[0], dict)
                or type(items[0].get("index")) is not int
                or items[0]["index"] != 0
            ):
                raise DataError("embedding indices are inconsistent")
            vector = self.validate_vector(items[0].get("embedding"))
            cache.execute(
                "CREATE TABLE IF NOT EXISTS usage (tokens INTEGER, inputs INTEGER, kind TEXT)"
            )
            cache.execute(
                "INSERT INTO usage VALUES (?,?,?)", (tokens, 1, "queries" if query else "documents")
            )
            cache.execute("INSERT INTO embeddings VALUES (?,?)", (key, json.dumps(vector)))
            return vector

    def validate_vector(self, value: object) -> list[float]:
        if not isinstance(value, list) or len(value) != self.settings.dimension:
            raise DataError("embedding dimension mismatch")
        if any(
            isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
            for x in value
        ):
            raise DataError("embedding contains non-finite values")
        if not any(value):
            raise DataError("embedding is a zero vector")
        return value

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Bounded batches; validate every complete input and each returned index."""
        if not texts or len(texts) > 16:
            raise DataError("embedding batch must contain 1..16 inputs")
        keys = [
            hashlib.sha256(
                (self.settings.model + "\0" + FORMAT_VERSION + "\0" + t).encode()
            ).hexdigest()
            for t in texts
        ]
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.state_dir / "embeddings.sqlite3"
        with sqlite3.connect(path, timeout=30) as cache:
            cache.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, data TEXT)")
            hits = [
                cache.execute("SELECT data FROM embeddings WHERE key=?", (k,)).fetchone()
                for k in keys
            ]
        missing = [i for i, hit in enumerate(hits) if hit is None]
        output = [self.validate_vector(json.loads(h[0])) if h else None for h in hits]
        if missing:
            inputs = [texts[i] for i in missing]
            counts = self.count_many(inputs)
            if any(c > self.settings.context_tokens for c in counts):
                raise DataError("invalid token counts or embedding input exceeds model context")
            response = self.request(
                "/v1/embeddings", {"model": self.settings.model, "input": inputs}
            )
            if not isinstance(response, dict) or response.get("model") != "EmbeddingsGigaR":
                raise DataError("embedding model mismatch")
            items = response.get("data", [])
            if (
                len(items) != len(inputs)
                or any(
                    not isinstance(item, dict) or type(item.get("index")) is not int
                    for item in items
                )
                or sorted(i["index"] for i in items) != list(range(len(inputs)))
            ):
                raise DataError("embedding indices are inconsistent")
            vectors = {item["index"]: self.validate_vector(item.get("embedding")) for item in items}
            with sqlite3.connect(path, timeout=30) as cache:
                cache.execute(
                    "CREATE TABLE IF NOT EXISTS usage (tokens INTEGER, inputs INTEGER, kind TEXT)"
                )
                cache.execute(
                    "INSERT INTO usage VALUES (?,?,?)",
                    (sum(counts), len(inputs), "documents"),
                )
                for j, i in enumerate(missing):
                    output[i] = vectors[j]
                    cache.execute(
                        "INSERT OR IGNORE INTO embeddings VALUES (?,?)",
                        (keys[i], json.dumps(vectors[j])),
                    )
        return output

    def count_many(self, inputs: list[str]) -> list[int]:
        keys = [
            hashlib.sha256((self.settings.model + "\0" + t).encode()).hexdigest() for t in inputs
        ]
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.state_dir / "embeddings.sqlite3"
        with sqlite3.connect(path, timeout=30) as cache:
            cache.execute(
                "CREATE TABLE IF NOT EXISTS token_counts (key TEXT PRIMARY KEY, tokens INTEGER)"
            )
            hits = [
                cache.execute("SELECT tokens FROM token_counts WHERE key=?", (k,)).fetchone()
                for k in keys
            ]
        missing = [i for i, h in enumerate(hits) if h is None]
        output = [h[0] if h else None for h in hits]
        if missing:
            value = self.request(
                "/v1/tokens/count",
                {"model": self.settings.model, "input": [inputs[i] for i in missing]},
            )
            entries = value if isinstance(value, list) else value.get("data", [])
            if len(entries) != len(missing) or any(
                not isinstance(c, dict) or type(c.get("tokens")) is not int or c["tokens"] < 0
                for c in entries
            ):
                raise DataError("invalid token count response")
            with sqlite3.connect(path, timeout=30) as cache:
                for i, c in zip(missing, entries, strict=True):
                    output[i] = c["tokens"]
                    cache.execute(
                        "INSERT OR REPLACE INTO token_counts VALUES (?,?)", (keys[i], output[i])
                    )
        return output
