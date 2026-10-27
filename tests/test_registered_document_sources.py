import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.evidence.registered_sources import registered_sources
from service.domain.documents.semantic.editor import ExistingCitations
from service.domain.subagents.research.sources import ResearchArtifact, SourceRecord
from service.presentation.routers.capabilities.document_editor import router


def entry(source=1, title="Actual title", suffix="a" * 10):
    return f"@misc{{src{source}_{suffix}, title = {{{title}}}, year = {{2024}}\n}}"


def test_sources_decode_producer_escapes_without_interpreting_commands():
    text = r"Title \& 50\% \_ \{literal\} \textbackslash{} \textasciitilde{}"
    result = registered_sources(entry(title=text))
    assert result["sources"][0]["title"] == "Title & 50% _ {literal} \\ ~"
    assert result["sources"][0]["year"] == "2024"
    assert "title" not in registered_sources(entry(title=r"\input{secret}"))["sources"][0]


def test_inventory_round_trips_the_actual_evidence_producer_without_inventing_metadata():
    record = SourceRecord(
        1,
        "https://example.test/a_b?q=1&v=2#part",
        "Study & 50% results",
        "private evidence",
        "html",
        "a" * 64,
        authors=("Автор А.",),
        year=2024,
        doi="10.1234/a_b",
    )
    bib = CitationRegistry(ResearchArtifact(1, (record,))).bibliography()
    result = registered_sources(bib)["sources"][0]
    assert result == {
        "source_id": 1,
        "key": "src1_aaaaaaaaaa",
        "title": record.title,
        "author": "Автор А.",
        "year": "2024",
        "url": record.canonical_url,
        "doi": record.doi,
    }
    assert "private evidence" not in str(result)


def test_long_metadata_is_omitted_not_truncated_into_a_different_url():
    assert (
        "url"
        not in registered_sources(
            "@misc{src1_aaaaaaaaaa, url={https://example.test/" + "a" * 2000 + "}} "
        )["sources"][0]
    )


def test_raw_percent_urls_are_literal_inside_values_and_not_fake_comments():
    bib = "@misc{src1_aaaaaaaaaa, url={https://example.test/a%20b}, title={Actual}}"
    assert registered_sources(bib)["sources"][0]["url"] == "https://example.test/a%20b"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "//host/path",
        "https://user:private@host/path",
        "https://host/a b",
    ],
)
def test_unusable_or_credential_bearing_urls_are_not_projected(url):
    item = registered_sources(f"@misc{{src1_aaaaaaaaaa, url={{{url}}}, title={{Actual}}}} ")[
        "sources"
    ][0]
    assert "url" not in item
    assert item["title"] == "Actual"


def test_comments_nested_entries_and_preambles_do_not_register_sources():
    fake = entry(2)
    bib = f"% {fake}\n@comment{{{fake}}}\n@comment({fake})\n@preamble{{{{{fake}}}}}\n" + entry(
        title=fake
    )
    assert [item["source_id"] for item in registered_sources(bib)["sources"]] == [1]
    assert ExistingCitations(bib).key_for(2) is None


@pytest.mark.parametrize("suffix", ["a" * 10, "b" * 10])
def test_duplicate_ids_are_ambiguous_even_with_identical_keys(suffix):
    bib = entry() + " " + entry(suffix=suffix)
    assert registered_sources(bib)["sources"] == []
    assert ExistingCitations(bib).key_for(1) is None


def test_no_metadata_is_inferred_and_foreign_keys_are_not_registered():
    bib = "@article{foreign, title={Not registered}}\n@misc{src3_aaaaaaaaaa, note={No title}}"
    result = registered_sources(bib)
    assert result == {
        "sources": [{"source_id": 3, "key": "src3_aaaaaaaaaa"}],
        "unresolved_count": 1,
    }


@pytest.mark.parametrize(
    "bib",
    ["@misc{src1_aaaaaaaaaa, title={Unclosed}", "x" * 750001, "\x00"],
    ids=["unclosed", "oversized", "nul"],
)
def test_malformed_or_oversized_input_is_rejected(bib):
    with pytest.raises(ValueError, match="bibliography_invalid"):
        registered_sources(bib)


def test_private_read_rpc_requires_auth_and_only_returns_metadata(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", "synthetic-source-key")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        body = {"bibliography": entry()}
        assert client.post("/document-editor/sources", json=body).status_code == 401
        response = client.post(
            "/document-editor/sources",
            json=body,
            headers={"Authorization": "Bearer synthetic-source-key"},
        )
        assert response.status_code == 200
        assert response.json()["sources"][0]["title"] == "Actual title"
