import pytest

from service.infrastructure.ide.transports.git_fetch import advertised, branch_name, parse_origin
from service.services.chat.domain.ide.edits import IdeEditError


def pkt(raw):
    return f"{len(raw) + 4:04x}".encode() + raw


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://127.0.0.1/a/b",
        "https://github.com:443/a/b",
        "https://user@github.com/a/b",
        "https://github.com/a/b?token=x",
        "https://github.com/a/b#x",
        "https://github.com/a/../b",
        "https://github.com/a/%2e%2e",
    ],
)
def test_url_rejects_noncanonical_or_sensitive_input(url):
    with pytest.raises(IdeEditError, match="ide_git_url_invalid"):
        parse_origin(url)


def test_canonical_origin_and_advertised_default_branch():
    assert parse_origin("https://github.com/owner/repo.git") == "https://github.com/owner/repo.git"
    sha = b"a" * 40
    raw = (
        pkt(b"# service=git-upload-pack\n")
        + b"0000"
        + pkt(sha + b" HEAD\0no-progress symref=HEAD:refs/heads/main\n")
        + pkt(sha + b" refs/heads/main\n")
        + b"0000"
    )
    assert advertised(raw, "") == ("main", "a" * 40, True)
    with pytest.raises(IdeEditError, match="ide_git_branch_missing"):
        advertised(raw, "missing")
    assert not branch_name("a/../b")
    assert not branch_name("-unsafe")
    assert not branch_name("foo.lock")
