"""Knowledge safeguards: generations, model identity, grounding and fallback."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from service.core import DataError, ResearchRepository
from service.knowledge.embedding import Embedder
from service.knowledge.engine import KnowledgeEngine, validate_projection, writer_lock
from service.knowledge.extraction import integrate_extractions
from service.knowledge.settings import KnowledgeSettings


@pytest.fixture
def engine(tmp_path):
    value = KnowledgeEngine(
        ResearchRepository(Path(__file__).parents[1] / "data"), KnowledgeSettings(tmp_path)
    )
    value.project = tmp_path
    return value


def test_projection_integrity_and_source_coverage(engine):
    projection = engine._projection()
    assert validate_projection(projection)["ok"]
    sources = {n["id"] for n in projection["nodes"] if n["type"].lower() == "source"}
    canonical = {s["id"] for s in engine.repository.bundle().records["sources"]}
    assert canonical <= sources
    assert len(canonical) == 318


def test_alias_search_and_explicit_fallback(engine):
    result = engine.search("S002")
    assert result["items"][0]["id"] == "S105"
    assert result["mode"] == "canonical_lexical"
    assert "dense_index_not_ready" in result["errors"]
    assert result["items"][0]["locators"]


def test_failed_build_does_not_publish_and_offline_is_explicit(engine):
    candidate = engine.build(offline=True)
    assert engine.status()["generation"] is None
    with pytest.raises(DataError, match="must be ready"):
        engine.publish(candidate["generation"])
    engine.publish(candidate["generation"], allow_offline=True)
    assert engine.status()["generation"] == candidate["generation"]
    directory = engine._generation(candidate["generation"])
    (directory / "projection.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DataError, match="hash mismatch"):
        engine.status()


def test_generation_paths_and_lock(engine):
    for invalid in ("../../data", "..", ".", "g-name:stream"):
        with pytest.raises(DataError):
            engine._generation(invalid)
    with writer_lock(engine.state), pytest.raises(DataError, match="already active"):
        with writer_lock(engine.state):
            pass
    assert not (engine.state / "writer.lock").exists()


def test_embedding_pin_and_no_truncation(tmp_path, monkeypatch):
    embedder = Embedder(KnowledgeSettings(tmp_path))
    monkeypatch.setattr(embedder, "token_count", lambda text: 5000)
    with pytest.raises(DataError, match="exceeds model context"):
        embedder.embed("oversized")
    with pytest.raises(DataError, match="dimension mismatch"):
        embedder.validate_vector([1.0] * 1024)
    with pytest.raises(DataError, match="non-finite"):
        embedder.validate_vector([float("nan")] * 2560)


def test_graph_bounds_and_filter(engine):
    with pytest.raises(DataError, match="depth"):
        engine.graph("S740", depth=3)
    graph = engine.graph("S740", depth=1)
    assert "S740" in {n["id"] for n in graph["nodes"]}
    result = engine.search("connectome", filters={"source_id": "S740"})
    assert all("S740" in n["source_ids"] for n in result["items"])
    with pytest.raises(DataError, match="unsupported knowledge filter"):
        engine.search("anything", filters={"arbitrary": "x"})


def test_extraction_grounding_and_unreviewed_boundary(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    text = "The model uses calcium imaging."
    doc = {"sha256": "a" * 64, "source_id": "S1", "text": text}
    (corpus / "documents.jsonl").write_text(json.dumps(doc) + "\n", encoding="utf-8")
    projection = {
        "nodes": [
            {
                "id": "S1",
                "validation_status": "verified_primary",
                "limitations": "not human pain",
                "permitted_conclusion": "imaging",
            }
        ],
        "edges": [],
    }
    proposal = {
        "source_id": "S1",
        "document_sha256": "a" * 64,
        "quote": "calcium imaging",
        "start": 20,
        "end": 35,
        "relation": "uses_method",
        "claim_type": "methodological",
        "entity": {"type": "Method", "name": "imaging"},
        "review": {"status": "unreviewed"},
    }
    proposal["start"] = text.index(proposal["quote"])
    proposal["end"] = proposal["start"] + len(proposal["quote"])
    path = tmp_path / "proposals.jsonl"
    path.write_text(json.dumps(proposal), encoding="utf-8")
    integrate_extractions(projection, path, tmp_path)
    assert projection["edges"][0]["status"] == "unreviewed"
    proposal["quote"] = "invented"
    path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(DataError, match="quote"):
        integrate_extractions(projection, path, tmp_path)


def test_http_knowledge_surfaces(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_KNOWLEDGE_DIR", str(tmp_path))
    client = TestClient(create_app())
    assert client.get("/v1/knowledge/status").status_code == 200
    result = client.get("/v1/knowledge/search", params={"q": "S740"}).json()
    assert result["items"][0]["id"] == "S740"
    assert client.get("/v1/knowledge/evidence/S740").status_code == 200
    assert client.get("/v1/knowledge/graph/S740", params={"depth": 3}).status_code == 422


def test_rollback_preserves_prior_projection(engine, monkeypatch):
    original = engine._projection()
    first = engine.build(offline=True)
    engine.publish(first["generation"], allow_offline=True)
    changed = deepcopy(original)
    changed["nodes"][0]["text"] += " amended"
    monkeypatch.setattr(engine, "_projection", lambda: changed)
    second = engine.build(offline=True)
    assert second["generation"] != first["generation"]
    engine.publish(second["generation"], allow_offline=True)
    engine.publish(second["generation"], allow_offline=True)
    assert engine._active()["previous_generation"] == first["generation"]
    assert engine.rollback()["generation"] == first["generation"]
    assert engine._read()[0] == original


def test_provider_outage_keeps_lexical_search(engine, monkeypatch):
    from service.knowledge.stores import GraphStore

    projection = engine._projection()
    monkeypatch.setattr(
        engine,
        "_read",
        lambda: (projection, {"generation": "test", "ready": True, "collection": "test"}),
    )
    monkeypatch.setattr(GraphStore, "search", lambda *args, **kwargs: ["S740"])

    def unavailable(*args, **kwargs):
        raise DataError("provider unavailable")

    monkeypatch.setattr(Embedder, "embed", unavailable)
    result = engine.search("connectome")
    assert result["mode"] == "neo4j_lexical"
    assert result["errors"] == ["dense_unavailable"]
    assert result["items"][0]["id"] == "S740"


def test_adaptive_split_preserves_exact_offsets_and_header(engine, monkeypatch):
    body = "x" * 5000
    source = {
        "id": "S1",
        "type": "Source",
        "text": "paper",
        "source_ids": ["S1"],
        "metadata": {"title": "Header"},
        "locators": [],
    }
    chunk = {
        "id": "c1",
        "type": "Chunk",
        "text": body,
        "source_ids": ["S1"],
        "metadata": {"char_start": 100, "char_end": 5100, "doc_sha256": "a" * 64},
        "locators": [],
    }
    projection = {"nodes": [source, chunk], "edges": []}
    monkeypatch.setattr(Embedder, "count_many", lambda self, inputs: [len(t) for t in inputs])
    monkeypatch.setattr(Embedder, "token_count", lambda self, text: len(text))
    engine._fit_inputs(projection)
    children = sorted(
        [n for n in projection["nodes"] if n["id"].startswith("segment:")],
        key=lambda n: n["metadata"]["char_start"],
    )
    assert chunk["metadata"]["embedding_excluded"]
    assert "".join(n["text"] for n in children) == body
    assert children[0]["metadata"]["char_start"] == 100
    assert children[-1]["metadata"]["char_end"] == 5100
    assert all(len("Header\n" + n["text"]) <= 4096 for n in children)


def test_batch_rejects_wrong_model_and_noninteger_indices(tmp_path, monkeypatch):
    embedder = Embedder(KnowledgeSettings(tmp_path))
    monkeypatch.setattr(embedder, "count_many", lambda inputs: [1] * len(inputs))
    monkeypatch.setattr(embedder, "request", lambda *args: {"model": "Embeddings-2", "data": []})
    with pytest.raises(DataError, match="model mismatch"):
        embedder.embed_many(["one", "two"])
    monkeypatch.setattr(
        embedder,
        "request",
        lambda *args: {
            "model": "EmbeddingsGigaR",
            "data": [{"index": 0.0, "embedding": [1.0] * 2560}],
        },
    )
    with pytest.raises(DataError, match="indices"):
        embedder.embed_many(["one"])


def test_fixed_benchmark_contains_intact_russian_inputs():
    suite = json.loads(
        (Path(__file__).parents[1] / "knowledge" / "evaluation.json").read_text(encoding="utf-8")
    )
    assert len(suite["cases"]) == 40
    assert len({c["id"] for c in suite["cases"]}) == 40
    russian = [c["query"] for c in suite["cases"] if c["id"].startswith("ru-")]
    assert len(russian) == 10
    assert all(any("\u0400" <= ch <= "\u04ff" for ch in q) and "?" not in q for q in russian)


def test_source_rrf_does_not_crowd_out_other_papers(engine, monkeypatch):
    from service.knowledge.stores import GraphStore

    def node(identity, kind, source):
        return {
            "id": identity,
            "type": kind,
            "text": "signal",
            "source_ids": [source],
            "metadata": {},
            "locators": [],
            "validation_status": "verified",
        }

    projection = {
        "nodes": [
            node("SA", "Source", "SA"),
            node("SB", "Source", "SB"),
            node("a1", "Chunk", "SA"),
            node("a2", "Chunk", "SA"),
            node("b1", "Chunk", "SB"),
        ],
        "edges": [],
    }
    monkeypatch.setattr(
        engine, "_read", lambda: (projection, {"ready": True, "generation": "test"})
    )
    monkeypatch.setattr(GraphStore, "search", lambda *args, **kwargs: ["a1", "a2", "b1"])
    result = engine.search("signal", mode="lexical", limit=2)
    assert [n["id"] for n in result["items"]] == ["SA", "SB"]
    assert result["items"][0]["matched_evidence"]["id"] == "a1"


def test_interrupted_live_build_resumes_and_preserves_active_pointer(engine, monkeypatch):
    import service.knowledge.engine as module

    nodes = [
        {
            "id": f"S{i}",
            "type": "Source",
            "text": "paper",
            "source_ids": [f"S{i}"],
            "metadata": {},
            "locators": [],
        }
        for i in range(18)
    ]
    projection = {"nodes": nodes, "edges": []}
    monkeypatch.setattr(engine, "_projection", lambda: deepcopy(projection))
    original = engine.build(offline=True)
    engine.publish(original["generation"], allow_offline=True)
    projection["nodes"][0]["text"] = "revised paper"
    points, batches = set(), []

    class Graph:
        def __init__(self, settings):
            pass

        def import_graph(self, *args):
            pass

        def counts(self, *args):
            return {"nodes": 18, "edges": 0}

        def query(self, statement, **params):
            return [] if "r.id" in statement else [{"id": n["id"]} for n in nodes]

    class Vector:
        fail = True

        def __init__(self, settings):
            pass

        def ensure(self, *args):
            pass

        def upsert_many(self, collection, rows):
            if self.fail and len(points) == 16:
                raise DataError("injected vector outage")
            points.update(key for key, _ in rows)

        def count(self, *args):
            return len(points)

        def request(self, method, route, **kwargs):
            if method == "GET":
                return {"result": {"config": {"params": {"vectors": {"size": 2560}}}}}
            return {
                "result": {
                    "points": [{"payload": {"node_id": key}} for key in points],
                    "next_page_offset": None,
                }
            }

    def embeds(self, inputs):
        batches.append(len(inputs))
        return [[1.0] * 2560 for _ in inputs]

    monkeypatch.setattr(module, "GraphStore", Graph)
    monkeypatch.setattr(module, "VectorStore", Vector)
    monkeypatch.setattr("service.knowledge.verification.GraphStore", Graph)
    monkeypatch.setattr("service.knowledge.verification.VectorStore", Vector)
    monkeypatch.setattr(Embedder, "count_many", lambda self, inputs: [1] * len(inputs))
    monkeypatch.setattr(Embedder, "embed_many", embeds)
    with pytest.raises(DataError, match="injected"):
        engine.build()
    assert engine._active()["generation"] == original["generation"]
    Vector.fail = False
    resumed = engine.build()
    assert resumed["ready"]
    assert batches == [16, 2, 2]
    engine.publish(resumed["generation"])
    assert engine._active()["generation"] == resumed["generation"]


def test_registered_document_is_the_fragment_parent(engine):
    from service.knowledge.corpus import chunk_documents

    source = {
        "id": "S1",
        "type": "Source",
        "text": "Study",
        "source_ids": ["S1"],
        "metadata": {"title": "Study"},
        "locators": [],
        "validation_status": "verified_primary",
        "limitations": "No clinical transfer",
        "permitted_conclusion": "Source-reported result only",
    }
    doc = {
        "source_id": "S1",
        "sha256": "a" * 64,
        "text_sha256": "b" * 64,
        "text": "One paragraph of registered text.",
        "primary_url": "https://primary.example/paper",
    }
    projection = {"nodes": [source], "edges": []}
    engine._attach_documents(projection, [doc])
    engine._attach_chunks(projection, chunk_documents([doc]))
    document = next(n for n in projection["nodes"] if n["type"] == "Document")
    chunk = next(n for n in projection["nodes"] if n["type"] == "Chunk")
    assert any(
        e["source"] == chunk["id"] and e["target"] == document["id"] for e in projection["edges"]
    )
    assert any(e["source"] == document["id"] and e["target"] == "S1" for e in projection["edges"])
    assert "text" not in chunk["metadata"]
    assert "text" not in chunk["locators"][0]
    assert validate_projection(projection)["ok"]


def test_glossary_keeps_scientific_constructs_distinct():
    from service.knowledge.terminology import expand

    assert "nociception" in expand("\u043d\u043e\u0446\u0438\u0446\u0435\u043f\u0446\u0438\u044f")
    assert "pain" not in expand("\u043d\u043e\u0446\u0438\u0446\u0435\u043f\u0446\u0438\u044f ECAP")
    assert "brain" not in expand(
        "\u0441\u043f\u0438\u043d\u043d\u043e\u0433\u043e \u043c\u043e\u0437\u0433\u0430"
    )


@pytest.mark.parametrize("field,value", [("model", "wrong"), ("dimension", 128)])
def test_publish_rejects_changed_model_before_switch(engine, field, value):
    candidate = engine.build(offline=True)
    path = engine._generation(candidate["generation"]) / "generation.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info[field] = value
    path.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(DataError, match="model/dimension"):
        engine.publish(candidate["generation"], allow_offline=True)
    assert engine._active() is None


def test_backend_identity_check_detects_equal_count_replacement(engine, monkeypatch):
    from service.knowledge.verification import verify_backend_ids

    class Graph:
        def __init__(self, settings):
            pass

        def query(self, statement, **params):
            return [{"id": "E-wrong"}] if "r.id" in statement else [{"id": "S-wrong"}]

    class Vector:
        def __init__(self, settings):
            pass

        def request(self, method, route, **kwargs):
            if method == "GET":
                return {"result": {"config": {"params": {"vectors": {"size": 2560}}}}}
            return {"result": {"points": [{"payload": {"node_id": "S-wrong"}}]}}

    monkeypatch.setattr("service.knowledge.verification.GraphStore", Graph)
    monkeypatch.setattr("service.knowledge.verification.VectorStore", Vector)
    errors = verify_backend_ids(
        engine.settings,
        {"nodes": [{"id": "S1"}], "edges": [{"id": "E1"}]},
        {"generation": "test", "collection": "test"},
        lambda n: True,
    )
    assert len(errors) == 3
    assert all("IDs differ" in e for e in errors)


@pytest.mark.parametrize("index", [False, 0.0, "0"])
@pytest.mark.parametrize("batched", [False, True])
def test_embedding_indices_are_strict_for_single_and_batch(engine, monkeypatch, index, batched):
    e = Embedder(engine.settings)

    def response(route, payload):
        if route.endswith("tokens/count"):
            return {"data": [{"tokens": 1}]}
        return {"model": "EmbeddingsGigaR", "data": [{"index": index, "embedding": [1.0] * 2560}]}

    monkeypatch.setattr(e, "request", response)
    with pytest.raises(DataError, match="indices"):
        e.embed_many(["new text"]) if batched else e.embed("new text")


@pytest.mark.parametrize("count", [True, -1, 1.5, "1"])
@pytest.mark.parametrize("batched", [False, True])
def test_token_counts_are_strict_for_single_and_batch(engine, monkeypatch, count, batched):
    e = Embedder(engine.settings)
    monkeypatch.setattr(e, "request", lambda *args: {"data": [{"tokens": count}]})
    with pytest.raises(DataError, match="token count"):
        e.count_many(["input"]) if batched else e.token_count("input")


def test_rejected_and_unreviewed_evidence_hidden_in_graph(engine, monkeypatch):
    nodes = [
        {
            "id": k,
            "type": "Source",
            "source_ids": [k],
            "text": k,
            "metadata": {},
            "locators": [],
            "validation_status": status,
        }
        for k, status in [("S1", "verified"), ("S2", "rejected"), ("S3", "unreviewed")]
    ]
    projection = {
        "nodes": nodes,
        "edges": [
            {
                "id": k,
                "source": "S1",
                "target": k,
                "type": "cites",
                "status": "verified",
                "provenance": {},
            }
            for k in ["S2", "S3"]
        ],
    }
    monkeypatch.setattr(engine, "_read", lambda: (projection, None))
    assert len(engine.graph("S1")["nodes"]) == 1
    assert len(engine.graph("S1", include_unreviewed=True)["nodes"]) == 3
    for key in ["S2", "S3"]:
        with pytest.raises(DataError, match="not found"):
            engine.evidence(key)
        with pytest.raises(DataError, match="not found"):
            engine.graph(key)
        assert engine.evidence(key, include_unreviewed=True)["node"]["id"] == key


def test_status_keeps_published_and_prepared_corpus_separate(engine):
    path = engine.state / "corpus" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"entries": [{"source_id": "S1", "status": "missing"}]}), encoding="utf-8"
    )
    candidate = engine.build(offline=True)
    engine.publish(candidate["generation"], allow_offline=True)
    path.write_text(
        json.dumps({"entries": [{"source_id": "S1", "status": "available"}]}), encoding="utf-8"
    )
    status = engine.status()
    assert status["published_corpus"]["statuses"] == {"missing": 1}
    assert status["prepared_corpus"]["statuses"] == {"available": 1}
    assert status["corpus"] == status["published_corpus"]
    assert (
        status["unreviewed_edges"]
        == status["unreviewed_canonical_edges"] + status["unreviewed_pi_edges"]
    )
