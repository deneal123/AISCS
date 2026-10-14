"""Standalone streamed compiler-output admission inside the workspace container."""

import os
import re
import sys
import tarfile

ARTIFACT_NAMES = frozenset(
    {"document.pdf", "report.json", "preview.png", "source.zip", "visual-pages.tar"}
)


def visual_member_name(member, index):
    if (
        not member.isreg()
        or re.fullmatch(r"page-[0-9]{3}\.png", member.name) is None
        or member.name != f"page-{index:03d}.png"
        or not 1 <= index <= 200
    ):
        raise ValueError("artifact_invalid")
    if not 8 <= member.size <= 16 * 1024 * 1024:
        raise ValueError("artifact_too_large")
    return f"page-{index}.png"


def archive_end(source):
    if any(read_exact(source, 512)):
        raise ValueError("artifact_invalid")
    padding = 0
    while chunk := source.read(65536):
        padding += len(chunk)
        if any(chunk) or padding > 10240:
            raise ValueError("artifact_invalid")


def extract_visual(anchor):
    """Expand only the compiler's numbered regular PNGs inside private staging.

    Interpret no PAX/GNU extensions, paths or links. Canonical unpadded names
    match the protected single-page endpoint; the original tar remains intact.
    """
    os.mkdir("visual-pages", mode=0o700, dir_fd=anchor)
    pages = os.open("visual-pages", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=anchor)
    try:
        bundle = os.open("visual-pages.tar", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=anchor)
        with os.fdopen(bundle, "rb") as source:
            index = 1
            while True:
                header = read_exact(source, 512)
                if not any(header):
                    archive_end(source)
                    if index == 1:
                        raise ValueError("artifact_invalid")
                    break
                member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
                name = visual_member_name(member, index)
                signature = read_exact(source, 8)
                if signature != b"\x89PNG\r\n\x1a\n":
                    raise ValueError("artifact_invalid")
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=pages,
                )
                with os.fdopen(fd, "wb") as output:
                    output.write(signature)
                    remaining = member.size - 8
                    while remaining:
                        chunk = read_exact(source, min(65536, remaining))
                        output.write(chunk)
                        remaining -= len(chunk)
                if member.size % 512:
                    read_exact(source, 512 - member.size % 512)
                index += 1
    finally:
        os.close(pages)


def member_name(member, seen, artifact_limit, visual_limit):
    name = member.name.removeprefix("./")
    if name not in ARTIFACT_NAMES or name in seen or not member.isreg():
        raise ValueError("artifact_invalid")
    limit = (
        262144
        if name == "report.json"
        else visual_limit
        if name == "visual-pages.tar"
        else artifact_limit
    )
    if member.size < 0 or member.size > limit:
        raise ValueError("artifact_too_large")
    return name


def target_directory(path):
    if not path.startswith("/") or any(part in ("", ".", "..") for part in path[1:].split("/")):
        raise ValueError("artifact_invalid")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path[1:].split("/"):
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def extract(source, destination, artifact_limit, visual_limit):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("artifact_invalid")
    anchor = target_directory(destination)
    seen = set()
    try:
        # Fixed USTAR headers only. Do not let tarfile consume unbounded PAX/GNU
        # extension bodies before member admission or interpret path overrides.
        while True:
            header = read_exact(source, 512)
            if not any(header):
                archive_end(source)
                break
            member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
            name = member_name(member, seen, artifact_limit, visual_limit)
            seen.add(name)
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=anchor,
            )
            with os.fdopen(fd, "wb") as output:
                remaining = member.size
                while remaining:
                    chunk = read_exact(source, min(65536, remaining))
                    output.write(chunk)
                    remaining -= len(chunk)
            if member.size % 512:
                read_exact(source, 512 - member.size % 512)
        if not {"document.pdf", "report.json"}.issubset(seen):
            raise ValueError("artifact_invalid")
        if "visual-pages.tar" in seen:
            extract_visual(anchor)
    finally:
        os.close(anchor)


def read_exact(source, size):
    value = bytearray()
    while len(value) < size:
        chunk = source.read(size - len(value))
        if not chunk:
            raise ValueError("artifact_invalid")
        value.extend(chunk)
    return bytes(value)


if __name__ == "__main__":
    try:
        extract(sys.stdin.buffer, sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
    except (OSError, ValueError, tarfile.TarError):
        # No paths, archive member names or compiler bodies in diagnostics.
        raise SystemExit(1) from None
