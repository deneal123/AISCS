"""Cleanup is constrained to disposable owned state and must retain evidence."""

import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cleanup


def test_docker_cleanup_keeps_referenced_volume_and_removes_only_owned_unused(
    monkeypatch,
):
    removed = []

    def docker(*args):
        if args[:2] == ("volume", "ls"):
            return "aspa-sim-unused\naspa-sim-used"
        if args[:2] == ("volume", "inspect"):
            return json.dumps(
                [{"Name": args[-1], "Labels": {"aspa.simulation.owner": "simctl"}}]
            )
        if args[:2] == ("volume", "rm"):
            removed.append(args[-1])
            return args[-1]
        if args[:2] == ("ps", "-aq") and args[-1] == "volume=aspa-sim-used":
            return "foreign-running-container"
        return ""

    monkeypatch.setattr(cleanup, "docker", docker)
    result = cleanup.cleanup_docker(apply=True)
    assert removed == ["aspa-sim-unused"]
    assert (
        next(x for x in result if x.get("volume") == "aspa-sim-used")["status"]
        == "kept_container_reference"
    )


def test_cleanup_refuses_root_and_outside_workspace(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(cleanup, "WORK", work)
    for target in (work, tmp_path / "other", work / "../other"):
        with pytest.raises(ValueError, match="unsafe cleanup"):
            cleanup.checked_target(target)


def test_cleanup_plan_preserves_files_then_apply_removes_only_disposable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", tmp_path / "work")
    env = tmp_path / "work/SIM-001/run/env"
    env.mkdir(parents=True)
    (env / "package.py").write_bytes(b"temporary dependency")
    proof = env.parent / "result.json"
    proof.write_bytes(b"proof")
    plan = cleanup.remove_targets([env], {proof.resolve()}, [], apply=False)
    assert plan[0]["status"] == "planned"
    assert env.is_dir()
    result = cleanup.remove_targets([env], {proof.resolve()}, [], apply=True)
    assert result[0]["status"] == "removed"
    assert not env.exists()
    assert proof.read_bytes() == b"proof"


def test_cleanup_preserves_receipt_ancestors_and_active_mounts(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", tmp_path / "work")
    target = tmp_path / "work/SIM-001/run/env"
    target.mkdir(parents=True)
    proof = target / "result.json"
    proof.write_bytes(b"protected")
    assert (
        cleanup.remove_targets([target], {proof}, [], apply=True)[0]["status"]
        == "kept_proof"
    )
    assert (
        cleanup.remove_targets([target], set(), [target.parent], apply=True)[0][
            "status"
        ]
        == "kept_active_mount"
    )
    assert target.is_dir()


def test_cleanup_can_remove_readonly_dependency_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", tmp_path / "work")
    target = tmp_path / "work/SIM-010/run/home"
    target.mkdir(parents=True)
    readonly = target / "package-binary"
    readonly.write_bytes(b"disposable artifact")
    readonly.chmod(stat.S_IREAD)
    result = cleanup.remove_targets([target], set(), [], apply=True)
    assert result[0]["status"] == "removed"
    assert not target.exists()


def test_cleanup_handles_long_readonly_dependency_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", tmp_path / "work")
    target = tmp_path / "work/SIM-013/run/home"
    leaf = target.joinpath(*(["long_julia_dependency_directory"] * 6), "header.h")
    native = cleanup.io_path(leaf)
    native.parent.mkdir(parents=True)
    native.write_bytes(b"long disposable header")
    native.chmod(stat.S_IREAD)
    assert len(str(leaf.absolute())) > 260
    assert cleanup.size_of(target) == len(b"long disposable header")
    result = cleanup.remove_targets([target], set(), [], apply=True)
    assert result[0]["status"] == "removed" and not target.exists()


def test_cleanup_does_not_modify_registry_while_collecting_proofs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    registry = {"candidates": [{"launch_review": {"receipts": ["result.json"]}}]}
    cleanup.protected_paths(registry)
    assert registry["candidates"][0]["launch_review"]["receipts"] == ["result.json"]


def test_build_cache_detection_preserves_pinned_build_sources(tmp_path):
    for name in ("build", "dist", "example.egg-info"):
        (tmp_path / name).mkdir()
    targets = cleanup.build_cache_targets(
        tmp_path, ["build/CMakeLists.txt", "src/main.py"]
    )
    assert tmp_path / "build" not in targets
    assert set(targets) == {tmp_path / "dist", tmp_path / "example.egg-info"}


def test_generated_wasm_is_disposable_but_tracked_package_is_kept(tmp_path):
    pkg = tmp_path / "web/wasm/pkg"
    pkg.mkdir(parents=True)
    assert cleanup.build_cache_targets(tmp_path, []) == [pkg]
    assert cleanup.build_cache_targets(tmp_path, ["web/wasm/pkg/authored.js"]) == []


def test_doom_generated_builds_do_not_remove_any_tracked_subtree(tmp_path):
    paths = ["doom-ui/dist", "doom-ui/.wrangler", "tools/vizdoom-observer"]
    for name in paths:
        (tmp_path / name).mkdir(parents=True)
    assert set(cleanup.build_cache_targets(tmp_path, [])) == {
        tmp_path / name for name in paths
    }
    assert (
        cleanup.build_cache_targets(
            tmp_path, [name + "/authored.txt" for name in paths]
        )
        == []
    )


def test_soup_input_cleanup_requires_the_unchanged_retained_primary(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    run = work / "SIM-016/20261025T000000Z-case"
    primary = work / "SIM-001/primary.feather"
    primary.parent.mkdir(parents=True)
    primary.write_bytes(b"registered input")
    copy = run / "assets/malecns/connectome-weights.feather"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(primary.read_bytes())
    (run / "result.json").write_text(
        json.dumps(
            {
                "commit": "pin",
                "profile": {
                    "assets": [
                        {
                            "source": primary.relative_to(work).as_posix(),
                            "destination": "malecns/connectome-weights.feather",
                            "sha256": cleanup.digest(primary),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    registry = {"candidates": [{"id": "SIM-016", "commit": "pin"}]}
    assert cleanup.duplicate_targets("SIM-016", registry) == [(copy, primary)]
    primary.write_bytes(b"changed")
    assert cleanup.duplicate_targets("SIM-016", registry) == []
    assert copy.read_bytes() == b"registered input"


def test_v630_cleanup_keeps_changed_primary_and_rejects_wrong_location(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    base = work / "SIM-017"
    run = base / "20261026T000000Z-case"
    primary = base / "assets/connections.csv.gz"
    copy = run / "source/v630_data/connections.csv.gz"
    for file in (primary, copy):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"registered gzip fixture")
    item = {
        "file": "connections.csv.gz",
        "primary": primary.relative_to(tmp_path).as_posix(),
        "sha256": cleanup.digest(primary),
    }
    manifest = {"commit": "pin", "files": [item]}
    receipt = run / "v630-inputs.json"
    receipt.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    registry = {"candidates": [{"id": "SIM-017", "commit": "pin"}]}
    assert cleanup.duplicate_targets("SIM-017", registry) == [(copy, primary)]
    primary.write_bytes(b"changed primary")
    assert cleanup.duplicate_targets("SIM-017", registry) == []
    item["primary"] = copy.relative_to(tmp_path).as_posix()
    receipt.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="retained primary"):
        cleanup.duplicate_targets("SIM-017", registry)


def test_pretrained_duplicates_keep_one_verified_model_copy(tmp_path, monkeypatch):
    import zipfile

    from probes import scalebreak_assets

    work = tmp_path / "work"
    base = work / "SIM-019"
    archive = base / "assets/results_pretrained_models.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in scalebreak_assets.FILES:
            bundle.writestr(scalebreak_assets.PREFIX + name, name.encode())
    expected = cleanup.digest(archive)
    monkeypatch.setattr(scalebreak_assets, "SHA256", expected)
    runs = [base / "20261026T000000Z-first", base / "20261026T000001Z-second"]
    for run in runs:
        files = []
        for name in scalebreak_assets.FILES:
            member = scalebreak_assets.PREFIX + name
            path = run / "assets/pretrained" / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            files.append(
                {
                    "member": member,
                    "destination": path.relative_to(run).as_posix(),
                    "sha256": cleanup.digest(path),
                }
            )
        (run / "pretrained-inputs.json").write_text(
            json.dumps({"model": "flow/0000/000", "sha256": expected, "files": files}),
            encoding="utf-8",
        )
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    registry = {"candidates": [{"id": "SIM-019", "commit": "pin"}]}
    pairs = cleanup.duplicate_targets("SIM-019", registry)
    assert len(pairs) == len(scalebreak_assets.FILES)
    assert all(
        left.is_relative_to(runs[1]) and right.is_relative_to(runs[0])
        for left, right in pairs
    )
    changed = runs[0] / "assets/pretrained" / scalebreak_assets.PREFIX / "best_chkpt"
    changed.write_bytes(b"changed primary")
    assert all(
        left.name != "best_chkpt"
        for left, _ in cleanup.duplicate_targets("SIM-019", registry)
    )
    archive.write_bytes(b"changed archive")
    with pytest.raises(ValueError, match="archive changed"):
        cleanup.duplicate_targets("SIM-019", registry)
    assert all(left.exists() and right.exists() for left, right in pairs)


def test_claude_cleanup_keeps_tracked_data_and_collects_only_generated_weight_cache(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    source = work / "SIM-015/20261025T000000Z-case/source"
    data = source / "data"
    data.mkdir(parents=True)
    for name in ("weight_coo.pkl", "weight_csr.pkl", "2025_Connectivity_783.parquet"):
        (data / name).write_bytes(b"fixture")
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    monkeypatch.setattr(
        cleanup.subprocess,
        "check_output",
        lambda *args, **kwargs: (
            "data/weight_coo.pkl\0data/2025_Connectivity_783.parquet\0"
        ),
    )
    targets = cleanup.disposable_targets(
        {"candidates": [{"id": "SIM-015", "path": "upstream"}]}, "SIM-015"
    )
    assert targets == [data / "weight_csr.pkl"]


def test_claude_duplicates_keep_one_lf_derivative_and_the_distinct_crlf_primary(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    base = work / "SIM-015"
    first = base / "20261025T000000Z-first"
    second = base / "20261025T000001Z-second"
    original = work / "SIM-006/primary"
    original.mkdir(parents=True)
    parquet = original / "conn.parquet"
    parquet.write_bytes(b"exact parquet")
    crlf = original / "comp.csv"
    crlf.write_bytes(b"a\r\n1\r\n")
    inputs = []
    for name, primary, content in (
        ("2025_Connectivity_783.parquet", parquet, parquet.read_bytes()),
        ("2025_Completeness_783.csv", crlf, b"a\n1\n"),
    ):
        for run in (first, second):
            p = run / "source/data" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        inputs.append(
            {
                "path": "data/" + name,
                "primary": primary.relative_to(tmp_path).as_posix(),
                "sha256": cleanup.digest(first / "source/data" / name),
            }
        )
    manifest = {"commit": "pinned", "inputs": inputs}
    for run in (first, second):
        (run / "claude-inputs.json").write_text(json.dumps(manifest), encoding="utf-8")
    reference = first / "claude-inputs.json"
    registry = {
        "candidates": [
            {
                "id": "SIM-015",
                "commit": "pinned",
                "frozen_inputs": {
                    "path": reference.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(reference),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    pairs = cleanup.duplicate_targets("SIM-015", registry)
    assert len(pairs) == 3  # Both parquet copies, only the second LF copy.
    assert (
        second / "source/data/2025_Completeness_783.csv",
        first / "source/data/2025_Completeness_783.csv",
    ) in pairs
    assert all(right != crlf for _, right in pairs)
    assert crlf.read_bytes() == b"a\r\n1\r\n"
    parquet.write_bytes(b"changed primary")
    assert all(
        not str(left).endswith(".parquet")
        for left, _ in cleanup.duplicate_targets("SIM-015", registry)
    )


def test_scoped_cleanup_collects_owned_pip_cache_but_preserves_live_mount(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    (work / "SIM-014").mkdir(parents=True)
    cache = work / "pip-cache"
    cache.mkdir()
    (cache / "wheel").write_bytes(b"temporary")
    foreign = tmp_path / "other-project-cache"
    foreign.mkdir()
    (foreign / "wheel").write_bytes(b"keep")
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    registry = {"candidates": [{"id": "SIM-014"}]}
    targets = cleanup.disposable_targets(registry, "SIM-014")
    assert targets == [cache]
    assert (
        cleanup.remove_targets(targets, set(), [cache], apply=True)[0]["status"]
        == "kept_active_mount"
    )
    assert (cache / "wheel").is_file()
    assert (
        cleanup.remove_targets(targets, set(), [], apply=True)[0]["status"] == "removed"
    )
    assert (foreign / "wheel").read_bytes() == b"keep"


def test_desktop_bind_spellings_preserve_the_windows_drive():
    for prefix in ("/run/desktop/mnt/host", "/host_mnt", "/mnt"):
        assert cleanup.windows_bind_source(prefix + "/r/Aspa/work") == "R:/Aspa/work"
    assert cleanup.windows_bind_source("R:\\Aspa\\work") == "R:\\Aspa\\work"
    assert (
        cleanup.windows_bind_source("/var/lib/docker/volumes/x")
        == "/var/lib/docker/volumes/x"
    )


def test_snntorch_duplicate_inputs_keep_one_verified_primary(tmp_path, monkeypatch):
    import hashlib
    import zipfile

    from probes.snntorch_assets import COMMIT, FILES

    work = tmp_path / "work"
    base = work / "SIM-022"
    assets = base / "assets"
    assets.mkdir(parents=True)
    archive = assets / (COMMIT + ".zip")
    payloads = {name: ("verified " + name).encode() for name in FILES}
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, body in payloads.items():
            bundle.writestr("fly-brain-snntorch-" + COMMIT + "/" + name, body)
    archive_sha = cleanup.digest(archive)
    for label in ("20261026T000000Z-first", "20261026T000001Z-second"):
        run = base / label
        entries = []
        for name, body in payloads.items():
            p = run / "source" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body)
            entries.append({"file": name, "sha256": hashlib.sha256(body).hexdigest()})
        (run / "pinned-assets.json").write_text(
            json.dumps(
                {"commit": COMMIT, "archive_sha256": archive_sha, "files": entries}
            )
        )
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    monkeypatch.setattr(cleanup, "SNNTORCH_ARCHIVE_SHA256", archive_sha)
    registry = {"candidates": [{"id": "SIM-022"}]}
    copies = cleanup.duplicate_targets("SIM-022", registry)
    assert len(copies) == 2
    assert all(
        "second" in str(left) and "first" in str(right) for left, right in copies
    )
    archive.write_bytes(b"changed primary")
    with pytest.raises(ValueError, match="archive changed"):
        cleanup.duplicate_targets("SIM-022", registry)


def test_doom_cleanup_requires_frozen_identity_and_unchanged_primary(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    primary = work / "SIM-001/registered/raw.feather"
    primary.parent.mkdir(parents=True)
    primary.write_bytes(b"registered MaleCNS input")
    run = work / "SIM-023/20261026T000000Z-check"
    copy = run / "source/connectome_data/malecns_v1/edges.feather"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(primary.read_bytes())
    manifest = run / "input-identity.json"
    manifest.write_text(
        json.dumps(
            {
                "commit": "pinned",
                "inputs": [
                    {
                        "name": "edges.feather",
                        "sha256": cleanup.digest(primary),
                        "reused_from": primary.relative_to(tmp_path).as_posix(),
                    }
                ],
            }
        )
    )
    registry = {
        "candidates": [
            {
                "id": "SIM-023",
                "commit": "pinned",
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    assert cleanup.duplicate_targets("SIM-023", registry) == [(copy, primary)]
    primary.write_bytes(b"changed origin")
    assert cleanup.duplicate_targets("SIM-023", registry) == []
    assert copy.read_bytes() == b"registered MaleCNS input"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="frozen input identity changed"):
        cleanup.duplicate_targets("SIM-023", registry)


def test_shiu_copies_are_removed_only_against_frozen_primary(tmp_path, monkeypatch):
    from probes.shiu_assets import COMMIT, FILES

    work = tmp_path / "work"
    name, oid = next(iter(FILES.items()))
    primary = work / "SIM-022/retained/data" / name
    primary.parent.mkdir(parents=True)
    primary.write_bytes(b"trusted original v630 data")
    run = work / "SIM-024/20261026T000000Z-check"
    copy = run / "source" / name
    copy.parent.mkdir(parents=True)
    copy.write_bytes(primary.read_bytes())
    manifest = run / "shiu-inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "commit": COMMIT,
                "inputs": [
                    {
                        "file": name,
                        "git_blob": oid,
                        "sha256": cleanup.digest(primary),
                        "primary": primary.relative_to(tmp_path).as_posix(),
                    }
                ],
            }
        )
    )
    registry = {
        "candidates": [
            {
                "id": "SIM-024",
                "commit": COMMIT,
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    assert cleanup.duplicate_targets("SIM-024", registry) == [(copy, primary)]
    primary.write_bytes(b"changed original")
    assert cleanup.duplicate_targets("SIM-024", registry) == []
    assert copy.read_bytes() == b"trusted original v630 data"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="frozen input identity changed"):
        cleanup.duplicate_targets("SIM-024", registry)


def test_mbi_recording_cleanup_requires_frozen_release_and_unchanged_primary(
    tmp_path, monkeypatch
):
    from probes import mbi_download

    work = tmp_path / "work"
    primary = work / "SIM-025/assets/data/session/recording.parquet"
    primary.parent.mkdir(parents=True)
    primary.write_bytes(b"verified OSF recording")
    run = work / "SIM-025/20261026T000000Z-check"
    copy = run / "source/data/session/recording.parquet"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(primary.read_bytes())
    item = {
        "id": "osf-file",
        "path": "session/recording.parquet",
        "bytes": primary.stat().st_size,
        "version": 1,
        "sha256": cleanup.digest(primary),
        "primary": primary.relative_to(tmp_path).as_posix(),
    }
    manifest = run / "mbi-inputs.json"
    manifest.write_text(json.dumps({"project": "9hxwe", "files": [item]}))
    registry = {
        "candidates": [
            {
                "id": "SIM-025",
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    monkeypatch.setattr(mbi_download, "IDENTITY", mbi_download.catalog_identity([item]))
    assert cleanup.duplicate_targets("SIM-025", registry) == [(copy, primary)]
    primary.write_bytes(b"changed release")
    assert cleanup.duplicate_targets("SIM-025", registry) == []
    assert copy.read_bytes() == b"verified OSF recording"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="MBI frozen input identity changed"):
        cleanup.duplicate_targets("SIM-025", registry)


def test_flyconnectome_export_repeats_require_same_version_and_retained_hash(
    tmp_path, monkeypatch
):
    from probes.flyconnectome_assets import COMMIT

    work = tmp_path / "work"
    run = work / "SIM-026/20261026T000000Z-check"
    primary, duplicate = run / "exports/neuron.npz", run / "review/native/neuron.npz"
    for path in [primary, duplicate]:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"same verified normalized mesh")
    retained, replica = [
        p.relative_to(tmp_path).as_posix() for p in [primary, duplicate]
    ]
    manifest = run / "export-identity.json"
    manifest.write_text(
        json.dumps(
            {
                "commit": COMMIT,
                "normalized_exports": [
                    {"path": retained, "sha256": cleanup.digest(primary)}
                ],
                "verified_replicas": [
                    {
                        "duplicate": replica,
                        "retained": retained,
                        "sha256": cleanup.digest(primary),
                    }
                ],
            }
        )
    )
    registry = {
        "candidates": [
            {
                "id": "SIM-026",
                "commit": COMMIT,
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    assert cleanup.duplicate_targets("SIM-026", registry) == [(duplicate, primary)]
    primary.write_bytes(b"changed release")
    assert cleanup.duplicate_targets("SIM-026", registry) == []
    assert duplicate.read_bytes() == b"same verified normalized mesh"
    manifest.write_text("{}")
    with pytest.raises(
        ValueError, match="FlyConnectome frozen export identity changed"
    ):
        cleanup.duplicate_targets("SIM-026", registry)


def test_nested_review_probe_cache_is_disposable_but_results_are_not(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    run = work / "SIM-026/20261026T000000Z-check"
    cache = run / "review-test/probes-v1/__pycache__"
    output = run / "review-test/exports/result.json"
    cache.mkdir(parents=True)
    (cache / "probe.pyc").write_bytes(b"generated bytecode")
    output.parent.mkdir()
    output.write_text("{}")
    monkeypatch.setattr(cleanup, "WORK", work)
    registry = {"candidates": [{"id": "SIM-026", "path": "unused-sidecar"}]}
    targets = cleanup.disposable_targets(registry, "SIM-026")
    assert cache in targets and output not in targets and output.parent not in targets


def test_pugliese_input_copies_require_frozen_blob_and_retained_primary(
    tmp_path, monkeypatch
):
    from probes import pugliese_assets

    work = tmp_path / "work"
    run = work / "SIM-027/20261026T000000Z-check"
    name = "data/manc t1 connectome data/test.csv"
    primary = work / "SIM-027/assets/test.csv"
    duplicate = run / "source" / name
    for path in [primary, duplicate]:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"registered MANC fixture")
    item = {
        "file": name,
        "git_blob": "a" * 40,
        "bytes": primary.stat().st_size,
        "primary": primary.relative_to(tmp_path).as_posix(),
        "sha256": cleanup.digest(primary),
    }
    monkeypatch.setattr(
        pugliese_assets, "FILES", {name: (item["git_blob"], item["bytes"])}
    )
    manifest = run / "input-and-export-identity.json"
    manifest.write_text(
        json.dumps({"commit": pugliese_assets.COMMIT, "inputs": [item]})
    )
    registry = {
        "candidates": [
            {
                "id": "SIM-027",
                "commit": pugliese_assets.COMMIT,
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    assert cleanup.duplicate_targets("SIM-027", registry) == [(duplicate, primary)]
    primary.write_bytes(b"changed retained data")
    assert cleanup.duplicate_targets("SIM-027", registry) == []
    assert duplicate.read_bytes() == b"registered MANC fixture"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="Pugliese frozen input identity changed"):
        cleanup.duplicate_targets("SIM-027", registry)


def test_browser_profile_variants_are_disposable_but_browser_exports_are_not(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    run = work / "SIM-029/20261026T000000Z-check"
    profile = run / "browser-profile-unique"
    output = run / "exports/browser-unique"
    for path in [profile, output]:
        path.mkdir(parents=True)
        (path / "keep-or-delete.json").write_text("{}")
    monkeypatch.setattr(cleanup, "WORK", work)
    registry = {"candidates": [{"id": "SIM-029", "path": "unused"}]}
    targets = cleanup.disposable_targets(registry, "SIM-029")
    assert profile in targets
    assert output not in targets and output.parent not in targets


def test_snedea_input_cleanup_keeps_changed_or_only_copy(tmp_path, monkeypatch):
    from probes import snedea_assets

    work = tmp_path / "work"
    run = work / "SIM-029/20261026T000000Z-check"
    primary = work / "SIM-029/assets/connectome.bin.gz"
    source_copy = run / "source/data/connectome.bin.gz"
    asset_copy = run / "assets/connectome.bin.gz"
    for path in [primary, source_copy, asset_copy]:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"pinned author binary")
    oid = "b" * 40
    monkeypatch.setattr(snedea_assets, "FILES", {"connectome.bin.gz": oid})
    item = {
        "file": "data/connectome.bin.gz",
        "git_blob": oid,
        "bytes": primary.stat().st_size,
        "primary": primary.relative_to(tmp_path).as_posix(),
        "sha256": cleanup.digest(primary),
    }
    manifest = run / "input-and-export-identity.json"
    manifest.write_text(json.dumps({"commit": snedea_assets.COMMIT, "inputs": [item]}))
    registry = {
        "candidates": [
            {
                "id": "SIM-029",
                "commit": snedea_assets.COMMIT,
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    assert cleanup.duplicate_targets("SIM-029", registry) == [
        (source_copy, primary),
        (asset_copy, primary),
    ]
    primary.write_bytes(b"changed retained file")
    assert cleanup.duplicate_targets("SIM-029", registry) == []
    assert source_copy.read_bytes() == b"pinned author binary"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="Snedea frozen input identity changed"):
        cleanup.duplicate_targets("SIM-029", registry)


def test_fcta_bundle_cleanup_preserves_unmatched_originals(tmp_path, monkeypatch):
    from probes import fcta_assets

    work = tmp_path / "work"
    run = work / "SIM-030/20261026T000000Z-check"
    primary = work / "SIM-030/assets/bundle/figures/figure1.pdf"
    duplicate = run / "source/figures/figure1.pdf"
    for path in [primary, duplicate]:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"same verified author figure")
    item = {
        "file": "figures/figure1.pdf",
        "git_blob": "c" * 40,
        "sha256": cleanup.digest(primary),
        "primary": primary.relative_to(tmp_path).as_posix(),
    }
    manifest = run / "frozen-inputs.json"
    manifest.write_text(json.dumps({"commit": fcta_assets.COMMIT, "inputs": [item]}))
    registry = {
        "candidates": [
            {
                "id": "SIM-030",
                "commit": fcta_assets.COMMIT,
                "path": "unused",
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    monkeypatch.setattr(
        fcta_assets, "pinned_tree", lambda path: {item["file"]: item["git_blob"]}
    )
    assert cleanup.duplicate_targets("SIM-030", registry) == [(duplicate, primary)]
    primary.write_bytes(b"different retained figure")
    assert cleanup.duplicate_targets("SIM-030", registry) == []
    assert duplicate.read_bytes() == b"same verified author figure"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="FCTA frozen input identity changed"):
        cleanup.duplicate_targets("SIM-030", registry)


@pytest.mark.parametrize("leaf_only", [False, True])
def test_pinned_input_cleanup_requires_retained_identity(
    tmp_path, monkeypatch, leaf_only
):
    work = tmp_path / "work"
    base = work / "SIM-032"
    run = base / "20261026T000000Z-check"
    name = "data/recording.mat"
    primary = base / "assets" / ("recording.mat" if leaf_only else name)
    duplicate = run / "source" / name
    export = run / "exports/recording.mat"
    for path in [primary, duplicate, export]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"same author input")
    manifest = run / "frozen.json"
    item = {
        "file": name,
        "git_blob": "a" * 40,
        "sha256": cleanup.digest(primary),
        "primary": primary.relative_to(tmp_path).as_posix(),
    }
    manifest.write_text(json.dumps({"commit": "b" * 40, "inputs": [item]}))
    row = {
        "id": "SIM-032",
        "commit": "b" * 40,
        "frozen_inputs": {
            "path": manifest.relative_to(tmp_path).as_posix(),
            "sha256": cleanup.digest(manifest),
        },
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    args = (row, row["commit"], {name: item["git_blob"]}, leaf_only)
    assert cleanup.pinned_input_pairs(*args) == [(duplicate, primary)]
    primary.write_bytes(b"changed primary")
    assert cleanup.pinned_input_pairs(*args) == []
    assert export.read_bytes() == duplicate.read_bytes() == b"same author input"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="manifest changed"):
        cleanup.pinned_input_pairs(*args)


def test_fitting_cleanup_requires_archive_and_retained_input_identity(
    tmp_path, monkeypatch
):
    from probes import fitting_assets

    work = tmp_path / "work"
    base = work / "SIM-002"
    archive = base / "assets/author-data.rar"
    primary = base / "assets/author/recording.csv"
    duplicate = base / "20261026T000000Z-check/source/data/recording.csv"
    export = base / "20261026T000000Z-check/exports/recording.csv"
    for path in (archive, primary, duplicate, export):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"qualified input")
    monkeypatch.setattr(fitting_assets, "ARCHIVE_SHA256", cleanup.digest(archive))
    monkeypatch.setattr(
        fitting_assets, "FILES", {"recording.csv": primary.stat().st_size}
    )
    manifest = base / "frozen.json"
    manifest.write_text(
        json.dumps(
            {
                "commit": "a" * 40,
                "archive": archive.relative_to(tmp_path).as_posix(),
                "archive_sha256": cleanup.digest(archive),
                "inputs": [
                    {
                        "member": "recording.csv",
                        "primary": primary.relative_to(tmp_path).as_posix(),
                        "bytes": primary.stat().st_size,
                        "sha256": cleanup.digest(primary),
                    }
                ],
            }
        )
    )
    registry = {
        "candidates": [
            {
                "id": "SIM-002",
                "commit": "a" * 40,
                "frozen_inputs": {
                    "path": manifest.relative_to(tmp_path).as_posix(),
                    "sha256": cleanup.digest(manifest),
                },
            }
        ]
    }
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    assert cleanup.duplicate_targets("SIM-002", registry) == [(duplicate, primary)]
    archive.write_bytes(b"changed archive")
    assert cleanup.duplicate_targets("SIM-002", registry) == []
    archive.write_bytes(b"qualified input")
    primary.write_bytes(b"changed primary")
    assert cleanup.duplicate_targets("SIM-002", registry) == []
    assert duplicate.read_bytes() == export.read_bytes() == b"qualified input"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="Fitting frozen input identity changed"):
        cleanup.duplicate_targets("SIM-002", registry)


def test_auxiliary_environment_cleanup_requires_preserved_outputs(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    base = work / "SIM-007"
    auxiliary = base / "visual-followup"
    environment = auxiliary / "env"
    environment.mkdir(parents=True)
    output = base / "20261026T000000Z-check/exports/plot.svg"
    output.parent.mkdir(parents=True)
    output.write_text("actual saved output")
    manifest = auxiliary / "runtime.json"
    identity = {
        "owner": "simctl",
        "id": "SIM-007",
        "status": "completed",
        "disposable": ["env"],
        "outputs": [
            {
                "path": output.relative_to(tmp_path).as_posix(),
                "sha256": cleanup.digest(output),
            }
        ],
    }
    registry = {"candidates": [{"id": "SIM-007", "path": "unused"}]}
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", work)
    assert cleanup.disposable_targets(registry, "SIM-007") == []
    manifest.write_text(json.dumps(identity))
    assert cleanup.disposable_targets(registry, "SIM-007") == [environment]
    identity["disposable"] = ["../../elsewhere"]
    manifest.write_text(json.dumps(identity))
    with pytest.raises(ValueError, match="Unqualified auxiliary"):
        cleanup.disposable_targets(registry, "SIM-007")
    identity["disposable"] = ["env"]
    manifest.write_text(json.dumps(identity))
    output.write_text("changed output")
    with pytest.raises(ValueError, match="output changed"):
        cleanup.disposable_targets(registry, "SIM-007")
