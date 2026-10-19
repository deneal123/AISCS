"""Same stdlib POSIX suite runs natively or in a source-injected Linux child."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from infrastructure import ide_bundle_files as files
from infrastructure.ide_bundle_format import BundleFailure, BundleLimits, read_bundle, write_bundle

LIMITS = BundleLimits(256, 1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024, 256 * 1024, 16)
BODY = b"\x00\xff\x80binary\r\n"


@unittest.skipUnless(os.name == "posix", "POSIX descriptor and filesystem semantics required")
class CapsuleFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gpthub-ide-capsule-fixture-")
        self.base = Path(self.temporary.name)
        self.repo, self.dest = self.base / "repo", self.base / "restored"
        self.repo.mkdir()
        self.dest.mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "src/main.py").write_text("print('hello')\n")
        (self.repo / "binary").write_bytes(BODY)

    def tearDown(self):
        self.temporary.cleanup()
        self.assertFalse(self.base.exists())

    def capture(self, limits=LIMITS):
        output = io.BytesIO()
        count = files.capture_bundle(str(self.repo), output, limits)
        self.assertEqual(count, len(output.getvalue()))
        output.seek(0)
        return output

    def reject_capture(self, code="ide_bundle_unsupported", limits=LIMITS):
        with self.assertRaises(BundleFailure) as caught:
            self.capture(limits)
        self.assertEqual(str(caught.exception), code)

    def test_binary_modes_timestamps_empty_directories_and_links(self):
        (self.repo / "empty").mkdir()
        (self.repo / "src/link").symlink_to("../binary")
        os.link(self.repo / "binary", self.repo / "copy")
        os.chmod(self.repo / "binary", 0o640)
        os.chmod(self.repo / "src/main.py", 0o751)
        os.chmod(self.repo / "empty", 0o750)
        stamp = 1_700_000_000_123_456_789
        for path in self.repo.rglob("*"):
            os.utime(path, ns=(stamp, stamp), follow_symlinks=False)
        snapshot = self.capture()
        with read_bundle(snapshot, LIMITS) as (entries, _archive):
            expected = {entry["path"]: entry for entry in entries}
        self.assertEqual(files.restore_empty(str(self.dest), snapshot, LIMITS), len(expected))
        for name, entry in expected.items():
            actual = os.lstat(self.dest / name)
            self.assertEqual(stat.S_IMODE(actual.st_mode), entry["mode"])
            self.assertEqual(actual.st_mtime_ns, entry["mtime_ns"])
        self.assertEqual((self.dest / "binary").read_bytes(), BODY)
        self.assertEqual((self.dest / "copy").stat().st_ino, (self.dest / "binary").stat().st_ino)
        self.assertEqual(os.readlink(self.dest / "src/link"), "../binary")
        self.assertEqual(list((self.dest / "empty").iterdir()), [])

    def test_empty_repository_and_reproducible_capture(self):
        first, second = self.capture(), self.capture()
        self.assertEqual(first.getvalue(), second.getvalue())
        empty = self.base / "empty"
        empty.mkdir()
        output = io.BytesIO()
        files.capture_bundle(str(empty), output, LIMITS)
        self.assertEqual(files.restore_empty(str(self.dest), output, LIMITS), 0)

    def test_global_path_order_handles_directory_before_hyphenated_sibling(self):
        (self.repo / "src-extra").write_text("sibling")
        with read_bundle(self.capture(), LIMITS) as (entries, _archive):
            self.assertEqual(
                [entry["path"] for entry in entries], sorted(entry["path"] for entry in entries)
            )

    def test_foreign_hardlink_is_not_captured(self):
        outside = self.base / "private"
        outside.write_text("PRIVATE_OUTSIDE")
        os.link(outside, self.repo / "alias")
        self.reject_capture()

    def test_external_and_composed_symlink_escape_are_rejected(self):
        link = self.repo / "alias"
        for target in ("/etc/passwd", "../private"):
            link.symlink_to(target)
            self.reject_capture()
            link.unlink()
        (self.repo / "rootlink").symlink_to(".")
        link.symlink_to("rootlink/../private")
        self.reject_capture()

    def test_symlink_cycle_is_an_explicit_unsupported_state(self):
        (self.repo / "a").symlink_to("b")
        (self.repo / "b").symlink_to("a")
        self.reject_capture()

    def test_fifo_and_socket_never_block_capture(self):
        fifo = self.repo / "fifo"
        os.mkfifo(fifo)
        self.reject_capture()
        fifo.unlink()
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(self.repo / "socket"))
            self.reject_capture()

    def test_privileged_modes_are_not_silently_stripped(self):
        os.chmod(self.repo / "binary", 0o4640)
        self.reject_capture()

    def test_limits_never_produce_a_truncated_success(self):
        for limits in (
            replace(LIMITS, entries=1),
            replace(LIMITS, file_bytes=1),
            replace(LIMITS, total_bytes=1),
            replace(LIMITS, depth=1),
        ):
            self.reject_capture("ide_bundle_limit", limits)

    def test_git_indirection_and_in_progress_lock_are_explicit_failures(self):
        git = self.repo / ".git"
        git.write_text("gitdir: /outside")
        self.reject_capture()
        git.unlink()
        git.mkdir()
        (git / "index.lock").touch()
        self.reject_capture("ide_bundle_busy")
        (git / "index.lock").unlink()
        (git / "commondir").write_text("../outside")
        self.reject_capture()

    def test_real_git_history_staged_dirty_and_untracked_state_survive(self):
        executable = shutil.which("git")
        if not executable:
            self.skipTest("Git executable unavailable for this fixture")
        environment = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }

        def git(root, *arguments):
            result = subprocess.run(
                [
                    executable,
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "user.name=Capsule fixture",
                    "-c",
                    "user.email=capsule@example.test",
                    "-C",
                    str(root),
                    *arguments,
                ],
                env=environment,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, "fixture Git operation failed")
            return result.stdout

        git(self.repo, "init", "-b", "feature/capsule")
        git(self.repo, "add", "src/main.py", "binary")
        git(self.repo, "commit", "-m", "Initial fixture")
        (self.repo / "src/main.py").write_text("print('second commit')\n")
        git(self.repo, "add", "src/main.py")
        git(self.repo, "commit", "-m", "Second fixture")
        (self.repo / "src/main.py").write_text("print('staged')\n")
        git(self.repo, "add", "src/main.py")
        (self.repo / "src/main.py").write_text("print('working copy')\n")
        (self.repo / "untracked").write_text("not committed")
        expected = [
            git(self.repo, *command)
            for command in [
                ("rev-parse", "HEAD"),
                ("symbolic-ref", "HEAD"),
                ("status", "--porcelain"),
                ("diff",),
                ("diff", "--cached"),
                ("log", "--format=%s"),
            ]
        ]
        files.restore_empty(str(self.dest), self.capture(), LIMITS)
        actual = [
            git(self.dest, *command)
            for command in [
                ("rev-parse", "HEAD"),
                ("symbolic-ref", "HEAD"),
                ("status", "--porcelain"),
                ("diff",),
                ("diff", "--cached"),
                ("log", "--format=%s"),
            ]
        ]
        self.assertEqual(actual, expected)
        self.assertIn(b"MM src/main.py", actual[2])
        self.assertIn(b"?? untracked", actual[2])

    def test_repo_import_hooks_are_only_bytes(self):
        for name in ("sitecustomize.py", "json.py"):
            (self.repo / name).write_text("raise RuntimeError('REPO_IMPORT')")
        files.restore_empty(str(self.dest), self.capture(), LIMITS)
        self.assertEqual((self.dest / "json.py").read_text(), "raise RuntimeError('REPO_IMPORT')")

    def test_change_after_archive_write_is_not_a_success(self):
        original = files.write_bundle
        for change in (
            lambda: (self.repo / "new").touch(),
            lambda: os.chmod(self.repo / "binary", 0o600),
            lambda: (self.repo / "binary").write_bytes(b"changed"),
        ):

            def racing(*args, change=change, **kwargs):
                result = original(*args, **kwargs)
                change()
                return result

            with patch.object(files, "write_bundle", racing):
                self.reject_capture("ide_bundle_changed")

    def test_fifo_replacement_during_capture_cannot_block_or_escape(self):
        original = files._manifest

        def replace_after_scan(*args):
            result = original(*args)
            (self.repo / "binary").unlink()
            os.mkfifo(self.repo / "binary")
            return result

        with patch.object(files, "_manifest", replace_after_scan):
            self.reject_capture("ide_bundle_changed")

    def test_capture_and_restore_reject_root_or_intermediate_symlinks(self):
        alias = self.base / "alias"
        alias.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(BundleFailure):
            files.capture_bundle(str(alias / "repo"), io.BytesIO(), LIMITS)
        with self.assertRaises(BundleFailure):
            files.restore_empty(str(alias / "restored"), self.capture(), LIMITS)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_nonempty_restore_does_not_overwrite_or_remove_anything(self):
        keep = self.dest / "keep"
        keep.write_bytes(b"original")
        with self.assertRaisesRegex(BundleFailure, "ide_bundle_target_not_empty"):
            files.restore_empty(str(self.dest), self.capture(), LIMITS)
        self.assertEqual(list(self.dest.iterdir()), [keep])
        self.assertEqual(keep.read_bytes(), b"original")

    def test_corrupt_payload_is_rejected_before_any_target_write(self):
        raw = bytearray(self.capture().getvalue())
        raw[raw.index(BODY)] ^= 1
        with self.assertRaises(BundleFailure):
            files.restore_empty(str(self.dest), io.BytesIO(raw), LIMITS)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_failed_materialization_never_reports_saved_or_removes_partial_files(self):
        with patch.object(files, "_metadata", side_effect=OSError("PRIVATE_OUTPUT_FAILURE")):
            with self.assertRaisesRegex(BundleFailure, "^ide_bundle_unavailable$"):
                files.restore_empty(str(self.dest), self.capture(), LIMITS)
        self.assertEqual((self.dest / "binary").read_bytes(), BODY)
        with self.assertRaisesRegex(BundleFailure, "ide_bundle_target_not_empty"):
            files.restore_empty(str(self.dest), self.capture(), LIMITS)

    def test_restrictive_directory_and_file_modes_apply_after_content(self):
        body = b"private"
        entries = [
            dict(path="dir", kind="directory", mode=0, mtime_ns=0),
            dict(
                path="dir/file",
                kind="file",
                mode=0,
                mtime_ns=0,
                size=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
            ),
        ]

        @contextmanager
        def payload(_entry):
            yield io.BytesIO(body)

        output = io.BytesIO()
        write_bundle(entries, payload, output, LIMITS)
        files.restore_empty(str(self.dest), output, LIMITS)
        self.assertEqual(stat.S_IMODE((self.dest / "dir").stat().st_mode), 0)
        os.chmod(self.dest / "dir", 0o700)
        self.assertEqual(stat.S_IMODE((self.dest / "dir/file").stat().st_mode), 0)

    def test_filesystem_metadata_loss_is_not_silently_accepted(self):
        os.utime(self.repo / "binary", ns=(0, 0))
        snapshot = self.capture()
        with patch.object(files.os, "utime", lambda *args, **kwargs: None):
            with self.assertRaisesRegex(BundleFailure, "ide_bundle_unsupported"):
                files.restore_empty(str(self.dest), snapshot, LIMITS)
