from scripts.refresh_crossref_metadata import format_authors


def test_format_authors_preserves_order_and_omits_empty_entries() -> None:
    assert format_authors([{"given": "Ada", "family": "Lovelace"}, {}]) == (
        "Ada Lovelace"
    )
