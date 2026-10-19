"""Portable capsule format checks; no Docker, user files or model requests."""

import hashlib
import io
import json
import struct
import zipfile
from contextlib import contextmanager
from dataclasses import replace

import pytest
from infrastructure.ide_bundle_format import (
    BundleFailure,
    BundleLimits,
    copy_payload,
    link_target,
    parts,
    payload_name,
    read_bundle,
    validate_entries,
    write_bundle,
)

LIMITS = BundleLimits(100, 1024, 4096, 16384, 8192, 10)
BODY = b"\x00\xffrepository\n"


def entry(path="main.py", body=BODY, **fields):
    return dict(
        path=path,
        kind="file",
        mode=0o755,
        mtime_ns=123456789000,
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        **fields,
    )


@contextmanager
def source(_entry):
    yield io.BytesIO(BODY)


def capsule(entries=None, limits=LIMITS):
    output = io.BytesIO()
    size = write_bundle([entry()] if entries is None else entries, source, output, limits)
    assert size == len(output.getvalue())
    output.seek(0)
    return output


def test_binary_and_empty_repository_roundtrip_is_canonical():
    for entries in ([], [entry()]):
        raw = capsule(entries)
        assert raw.getvalue() == capsule(entries).getvalue()
        with read_bundle(raw, LIMITS) as (restored, archive):
            assert restored == entries
            if entries:
                assert archive.read(payload_name(0)) == BODY
    assert BODY not in json.dumps(entry()).encode()


@pytest.mark.parametrize(
    "path",
    ["", "/etc/passwd", "../outside", "a/../b", "a//b", "a\\b", "a\x00b", "a/", "a/./b", "\ud800"],
)
def test_invalid_paths_are_closed_failures(path):
    with pytest.raises(BundleFailure):
        parts(path)


@pytest.mark.parametrize("target", ["/etc/passwd", "../../outside", "..\\outside", "\x00", ""])
def test_links_cannot_escape_the_repository(target):
    with pytest.raises(BundleFailure):
        link_target("src/link", target)
    assert link_target("src/link", "../main.py") == "main.py"


def test_directories_internal_symlinks_and_hardlinks_have_explicit_structure():
    entries = [
        entry("a"),
        dict(path="b", kind="hardlink", mode=0o755, mtime_ns=123456789000, target="a"),
        dict(path="src", kind="directory", mode=0o750, mtime_ns=0),
        dict(path="src/link", kind="symlink", mode=0o777, mtime_ns=0, target="../a"),
    ]
    with read_bundle(capsule(entries), LIMITS) as (restored, archive):
        assert restored == entries
        assert archive.namelist() == ["manifest.json", "data/00000000"]


@pytest.mark.parametrize(
    "edit",
    [
        lambda e: e.update(mode=0o4755),
        lambda e: e.update(mode=True),
        lambda e: e.update(size=-1),
        lambda e: e.update(size=True),
        lambda e: e.update(mtime_ns=True),
        lambda e: e.update(mtime_ns=2**63),
        lambda e: e.update(sha256="PRIVATE"),
        lambda e: e.update(extra="ignored"),
        lambda e: e.update(kind="fifo"),
        lambda e: e.update(kind=[]),
    ],
)
def test_manifest_rejects_unsafe_or_ambiguous_metadata(edit):
    invalid = entry()
    edit(invalid)
    with pytest.raises(BundleFailure):
        validate_entries([invalid], LIMITS)


def test_parent_order_link_identity_duplicates_and_limits():
    invalids = [
        [entry("missing/file")],
        [entry(), entry()],
        [entry("z"), entry("a")],
        [entry("a"), dict(path="b", kind="hardlink", target=[], mode=0o755, mtime_ns=0)],
        [entry("a"), dict(path="b", kind="hardlink", target="a", mode=0o600, mtime_ns=0)],
    ]
    for entries in invalids:
        with pytest.raises(BundleFailure):
            validate_entries(entries, LIMITS)
    for limits in [
        replace(LIMITS, entries=1),
        replace(LIMITS, total_bytes=1),
        replace(LIMITS, file_bytes=1),
    ]:
        with pytest.raises(BundleFailure):
            validate_entries([entry("a"), entry("b")], limits)


@pytest.mark.parametrize(
    "fields",
    [
        {"entries": 0},
        {"entries": True},
        {"entries": 65534},
        {"depth": 65},
        {"archive_bytes": 2**31},
        {"manifest_bytes": 16385},
    ],
)
def test_invalid_limits_fail_closed(fields):
    with pytest.raises(BundleFailure):
        replace(LIMITS, **fields)


def test_changed_payload_and_nonempty_output_never_succeed():
    with pytest.raises(BundleFailure, match="ide_bundle_changed"):
        write_bundle([entry(body=b"different")], source, io.BytesIO(), LIMITS)
    with pytest.raises(BundleFailure):
        write_bundle([entry()], source, io.BytesIO(b"old archive tail"), LIMITS)
    with pytest.raises(BundleFailure, match="ide_bundle_limit"):
        write_bundle(
            [entry()], source, io.BytesIO(), replace(LIMITS, archive_bytes=150, manifest_bytes=100)
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "trailing",
        "truncate",
        "local_extra",
        "local_flags",
        "local_size",
        "payload",
        "central_offset",
    ],
)
def test_corrupted_envelope_is_rejected_before_any_restore_input(mutation):
    raw = bytearray(capsule().getvalue())
    if mutation == "trailing":
        raw.extend(b"junk")
    elif mutation == "truncate":
        del raw[-1:]
    elif mutation == "local_extra":
        struct.pack_into("<H", raw, 28, 1)
    elif mutation == "local_flags":
        struct.pack_into("<H", raw, 6, 8)
    elif mutation == "local_size":
        struct.pack_into("<I", raw, 22, 1)
    elif mutation == "payload":
        raw[raw.index(BODY)] ^= 1
    elif mutation == "central_offset":
        struct.pack_into("<I", raw, len(raw) - 6, 1)
    with pytest.raises(BundleFailure):
        with read_bundle(io.BytesIO(raw), LIMITS):
            pytest.fail("unvalidated restore input exposed")


def test_forged_digest_and_duplicate_json_keys_are_rejected():
    for manifest in [
        b'{"format":"gpthub-repository","version":1,"version":1,"entries":[]}',
        json.dumps(
            dict(format="gpthub-repository", version=1, entries=[{**entry(), "sha256": "0" * 64}])
        ).encode(),
    ]:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, body in [("manifest.json", manifest), (payload_name(0), BODY)]:
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.create_system, info.external_attr = 3, 0o100600 << 16
                archive.writestr(info, body)
        with pytest.raises(BundleFailure):
            with read_bundle(output, LIMITS):
                pytest.fail("invalid manifest exposed")


def test_payload_copy_checks_underflow_overflow_digest_and_short_writes():
    class ShortOutput(io.BytesIO):
        def write(self, data):
            return len(data) - 1

    for body in [BODY[:-1], BODY + b"x", b"x" * len(BODY)]:
        with pytest.raises(BundleFailure):
            copy_payload(io.BytesIO(body), None, entry())
    with pytest.raises(BundleFailure, match="ide_bundle_unavailable"):
        copy_payload(io.BytesIO(BODY), ShortOutput(), entry())
    assert str(BundleFailure("PRIVATE")) == "ide_bundle_invalid"


def test_virtual_symlink_resolution_rejects_composed_escape_and_cycles():
    def link(path, target):
        return dict(path=path, kind="symlink", mode=0o777, mtime_ns=0, target=target)

    for entries in ([link("a", "."), link("b", "a/../outside")], [link("a", "b"), link("b", "a")]):
        with pytest.raises(BundleFailure, match="ide_bundle_unsupported"):
            validate_entries(entries, LIMITS)


def test_output_failure_is_not_reclassified_as_invalid_input():
    failure = OSError("fixture output failure")
    with pytest.raises(OSError) as caught:
        with read_bundle(capsule(), LIMITS):
            raise failure
    assert caught.value is failure


@pytest.mark.parametrize(
    "path,kind",
    [
        (".git", "file"),
        (".git/commondir", "file"),
        (".git/objects/info/alternates", "file"),
        (".git/objects/info/http-alternates", "file"),
        (".git/worktrees", "directory"),
        (".git/index.lock", "file"),
    ],
)
def test_restore_manifest_rejects_git_indirection_and_lock_files(path, kind):
    components = path.split("/")
    entries = [
        dict(path="/".join(components[:depth]), kind="directory", mode=0o700, mtime_ns=0)
        for depth in range(1, len(components))
    ]
    entries.append(
        entry(path) if kind == "file" else dict(path=path, kind=kind, mode=0o700, mtime_ns=0)
    )
    with pytest.raises(BundleFailure):
        validate_entries(entries, LIMITS)


@pytest.mark.parametrize("change", ["compression", "zip_extra", "zip_comment", "zip_flags"])
def test_noncanonical_zip_features_are_rejected_without_extracting(change):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("manifest.json", (1980, 1, 1, 0, 0, 0))
        info.create_system, info.external_attr = 3, 0o100600 << 16
        if change == "compression":
            info.compress_type = zipfile.ZIP_DEFLATED
        elif change == "zip_extra":
            info.extra = b"\x00\x00\x00\x00"
        elif change == "zip_comment":
            info.comment = b"not canonical"
        archive.writestr(info, b'{"format":"gpthub-repository","version":1,"entries":[]}')
    raw = bytearray(output.getvalue())
    if change == "zip_flags":
        central = raw.index(b"PK\x01\x02")
        struct.pack_into("<H", raw, central + 8, 1)
    with pytest.raises(BundleFailure):
        with read_bundle(io.BytesIO(raw), LIMITS):
            pytest.fail("noncanonical archive exposed")
