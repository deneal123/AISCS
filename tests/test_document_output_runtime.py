"""Compiler artifacts are fixed flat regular files, never tar filesystem state."""

import tarfile

import pytest
from infrastructure.document_output_runtime import member_name, visual_member_name


def test_visual_page_name_matches_protected_endpoint():
    member = tarfile.TarInfo("page-001.png")
    member.size = 16
    assert visual_member_name(member, 1) == "page-1.png"
    member.name = "page-200.png"
    assert visual_member_name(member, 200) == "page-200.png"


@pytest.mark.parametrize(
    "name",
    [
        "../page-001.png",
        "/page-001.png",
        "page-1.png",
        "page-002.png",
        "page-000.png",
        "page-201.png",
    ],
)
def test_visual_page_rejects_paths_gaps_and_noncanonical_names(name):
    member = tarfile.TarInfo(name)
    member.size = 16
    with pytest.raises(ValueError, match="^artifact_invalid$"):
        visual_member_name(member, 1)


@pytest.mark.parametrize(
    "kind",
    [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME],
)
def test_visual_page_rejects_links_and_extended_headers(kind):
    member = tarfile.TarInfo("page-001.png")
    member.size = 16
    member.type = kind
    with pytest.raises(ValueError, match="^artifact_invalid$"):
        visual_member_name(member, 1)


@pytest.mark.parametrize("size", [0, 7, 16 * 1024 * 1024 + 1])
def test_visual_page_rejects_unbounded_size(size):
    member = tarfile.TarInfo("page-001.png")
    member.size = size
    with pytest.raises(ValueError, match="^artifact_too_large$"):
        visual_member_name(member, 1)


@pytest.mark.parametrize("name", ["../escape", "/document.pdf", "nested/a", "unexpected", "."])
def test_non_artifact_names_are_rejected(name):
    with pytest.raises(ValueError, match="^artifact_invalid$"):
        member_name(tarfile.TarInfo(name), set(), 1024, 4096)


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.DIRTYPE,
        tarfile.FIFOTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
    ],
)
def test_non_regular_artifacts_are_rejected(kind):
    member = tarfile.TarInfo("document.pdf")
    member.type = kind
    member.linkname = "../private-source"
    with pytest.raises(ValueError, match="^artifact_invalid$"):
        member_name(member, set(), 1024, 4096)


def test_duplicate_artifact_is_rejected():
    with pytest.raises(ValueError, match="^artifact_invalid$"):
        member_name(tarfile.TarInfo("./document.pdf"), {"document.pdf"}, 1024, 4096)


@pytest.mark.parametrize(
    "name,limit", [("document.pdf", 1024), ("report.json", 262144), ("visual-pages.tar", 4096)]
)
def test_exact_size_allowed_but_over_budget_rejected(name, limit):
    member = tarfile.TarInfo(name)
    member.size = limit
    assert member_name(member, set(), 1024, 4096) == name
    member.size += 1
    with pytest.raises(ValueError, match="^artifact_too_large$"):
        member_name(member, set(), 1024, 4096)
