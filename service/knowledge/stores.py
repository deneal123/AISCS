"""Independent graph generations and Qdrant collections; no destructive recreation."""

from __future__ import annotations

import json
import uuid

import httpx
from neo4j import GraphDatabase, Query

from ..core import DataError
from .settings import KnowledgeSettings
from .terminology import STOPWORDS


class GraphStore:
    def __init__(self, settings: KnowledgeSettings):
        self.settings = settings

    def query(self, cypher: str, **parameters: object) -> list[dict]:
        try:
            with (
                GraphDatabase.driver(
                    self.settings.neo4j_url,
                    auth=(self.settings.neo4j_user, self.settings.neo4j_password),
                    connection_timeout=3,
                ) as driver,
                driver.session(database="neo4j") as session,
            ):
                return session.run(Query(cypher, timeout=self.settings.timeout), parameters).data()
        except Exception as exc:
            raise DataError("knowledge graph unavailable") from exc

    def import_graph(self, generation: str, projection: dict) -> None:
        self.query(
            "CREATE CONSTRAINT knowledge_key IF NOT EXISTS "
            "FOR (n:Knowledge) REQUIRE n.key IS UNIQUE"
        )
        self.query(
            "CREATE FULLTEXT INDEX knowledge_text IF NOT EXISTS "
            "FOR (n:Knowledge) ON EACH [n.text] "
            "OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-no-stop-words'}}"
        )
        nodes = [
            {
                "key": generation + ":" + n["id"],
                "id": n["id"],
                "generation": generation,
                "kind": n["type"],
                "text": n["text"],
                "document": json.dumps(n, ensure_ascii=False),
            }
            for n in projection["nodes"]
        ]
        for start in range(0, len(nodes), 100):
            self.query(
                "UNWIND $rows AS row MERGE (n:Knowledge {key:row.key}) SET n += row",
                rows=nodes[start : start + 100],
            )
        for start in range(0, len(projection["edges"]), 200):
            self.query(
                "UNWIND $rows AS row "
                "MATCH (a:Knowledge {key:$generation+':'+row.source}) "
                "MATCH (b:Knowledge {key:$generation+':'+row.target}) "
                "MERGE (a)-[r:LINK {id:row.id}]->(b) "
                "SET r.kind=row.type, r.status=row.status, r.document=row.document",
                generation=generation,
                rows=[
                    {**e, "document": json.dumps(e, ensure_ascii=False)}
                    for e in projection["edges"][start : start + 200]
                ],
            )
        self.query("CALL db.awaitIndexes(120)")

    def search(
        self, generation: str, query: str, limit: int = 50, *, allowed: list[str] | None = None
    ) -> list[str]:
        # Escape Lucene operators: user text is never interpreted as a graph query.
        words = [
            '"' + w.replace('"', "").replace("\\", "") + '"'
            for w in query.split()
            if w.replace('"', "").replace("\\", "") and w.casefold() not in STOPWORDS
        ]
        if not words:
            return []
        rows = self.query(
            "CALL db.index.fulltext.queryNodes('knowledge_text',$query) "
            "YIELD node,score WHERE node.generation=$generation "
            "AND ($allowed IS NULL OR node.id IN $allowed) "
            "RETURN node.id AS id ORDER BY score DESC, id LIMIT $limit",
            query=" OR ".join(words),
            generation=generation,
            limit=limit,
            allowed=allowed,
        )
        return [row["id"] for row in rows]

    def counts(self, generation: str) -> dict:
        nodes = self.query(
            "MATCH (n:Knowledge {generation:$generation}) RETURN count(n) AS count",
            generation=generation,
        )[0]["count"]
        edges = self.query(
            "MATCH (n:Knowledge {generation:$generation})-[r:LINK]->() RETURN count(r) AS count",
            generation=generation,
        )[0]["count"]
        return {"nodes": nodes, "edges": edges}


class VectorStore:
    def __init__(self, settings: KnowledgeSettings):
        self.settings = settings

    def request(self, method: str, route: str, **kwargs: object) -> dict:
        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.request(
                    method, self.settings.qdrant_url.rstrip("/") + route, **kwargs
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataError("knowledge vector store unavailable") from exc

    def ensure(self, collection: str) -> None:
        try:
            data = self.request("GET", "/collections/" + collection)
        except DataError as exc:
            if (
                isinstance(exc.__cause__, httpx.HTTPStatusError)
                and exc.__cause__.response.status_code == 404
            ):
                self.request(
                    "PUT",
                    "/collections/" + collection,
                    json={
                        "vectors": {
                            "size": self.settings.dimension,
                            "distance": "Cosine",
                            "on_disk": True,
                        }
                    },
                )
                return
            raise
        vectors = data["result"]["config"]["params"]["vectors"]
        if vectors.get("size") != self.settings.dimension:
            raise DataError("existing vector collection has incompatible dimension")

    def upsert(self, collection: str, node_id: str, vector: list[float]) -> None:
        self.request(
            "PUT",
            "/collections/" + collection + "/points?wait=true",
            json={
                "points": [
                    {
                        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, node_id)),
                        "vector": vector,
                        "payload": {"node_id": node_id},
                    }
                ]
            },
        )

    def upsert_many(self, collection: str, rows: list[tuple[str, list[float]]]) -> None:
        self.request(
            "PUT",
            "/collections/" + collection + "/points?wait=true",
            json={
                "points": [
                    {
                        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, node_id)),
                        "vector": vector,
                        "payload": {"node_id": node_id},
                    }
                    for node_id, vector in rows
                ]
            },
        )

    def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 50,
        *,
        allowed: list[str] | None = None,
    ) -> list[str]:
        payload = {"query": vector, "limit": limit, "with_payload": True}
        if allowed is not None:
            payload["filter"] = {"must": [{"key": "node_id", "match": {"any": allowed}}]}
        result = self.request(
            "POST",
            "/collections/" + collection + "/points/query",
            json=payload,
        )
        return [p["payload"]["node_id"] for p in result["result"]["points"]]

    def count(self, collection: str) -> int:
        return self.request(
            "POST", "/collections/" + collection + "/points/count", json={"exact": True}
        )["result"]["count"]
