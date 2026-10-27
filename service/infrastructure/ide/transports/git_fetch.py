"""Bounded public GitHub smart-HTTP clone input, pinned DNS/TLS, no redirects.

Git protocol v0: request one advertised branch and all its reachable history.
Never fetch a user URL directly, run Git, use credentials, or import an archive.
"""

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import httpx

from service.services.chat.domain.ide.edits import IdeEditError

MAX_PACK = 20 * 1024 * 1024


def parse_origin(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", parsed.path)
        ):
            raise ValueError
        parts = parsed.path.strip("/").split("/")
        parts[1] = parts[1].removesuffix(".git")
        if any(part in {"", ".", ".."} or part.startswith("-") for part in parts):
            raise ValueError
        return "https://github.com/" + "/".join(parts) + ".git"
    except (ValueError, AttributeError):
        raise IdeEditError("ide_git_url_invalid") from None


def branch_name(value: str) -> bool:
    return bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", value)
        and ".." not in value
        and all(
            part and not part.startswith(".") and not part.endswith((".lock", "."))
            for part in value.split("/")
        )
    )


def packets(raw: bytes) -> list[bytes]:
    rows = []
    while raw:
        if len(raw) < 4:
            raise ValueError
        size = int(raw[:4], 16)
        if size == 0:
            rows.append(b"")
            raw = raw[4:]
        elif 4 <= size <= len(raw):
            rows.append(raw[4:size].rstrip(b"\n"))
            raw = raw[size:]
        else:
            raise ValueError
    return rows


def advertised(raw: bytes, requested: str) -> tuple[str, str, bool]:
    rows = packets(raw)
    if rows[:2] != [b"# service=git-upload-pack", b""]:
        raise ValueError
    refs, default, progress = {}, "", False
    for row in rows[2:]:
        if not row:
            continue
        item, _, capabilities = row.partition(b"\0")
        for capability in capabilities.split():
            if capability.startswith(b"symref=HEAD:refs/heads/"):
                default = capability.removeprefix(b"symref=HEAD:refs/heads/").decode("ascii")
            progress |= capability == b"no-progress"
        sha, _, ref = item.partition(b" ")
        if re.fullmatch(b"[a-f0-9]{40}", sha) and ref.startswith(b"refs/heads/"):
            refs[ref.removeprefix(b"refs/heads/").decode("ascii")] = sha.decode("ascii")
    branch = requested or default
    if not branch_name(branch) or branch not in refs:
        raise IdeEditError("ide_git_branch_missing")
    return branch, refs[branch], progress


async def public_address() -> str:
    infos = await asyncio.get_running_loop().getaddrinfo("github.com", 443, type=socket.SOCK_STREAM)
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses or any(not item.is_global for item in addresses):
        raise IdeEditError("ide_git_fetch_failed")
    # Resolve once. All requests connect to the checked numeric address while
    # certificate validation and SNI remain github.com; no proxy/DNS second hop.
    return str(addresses[0])


async def fetch_pack(origin: str, branch: str = "") -> tuple[bytes, str, str]:
    origin = parse_origin(origin)
    if branch and not branch_name(branch):
        raise IdeEditError("ide_git_branch_missing")
    try:
        async with asyncio.timeout(35):
            address = await public_address()
            host = f"[{address}]" if ":" in address else address
            path = urlsplit(origin).path
            async with httpx.AsyncClient(
                timeout=15, trust_env=False, follow_redirects=False
            ) as client:

                async def request(method, suffix, content, limit, media):
                    async with client.stream(
                        method,
                        f"https://{host}{path}{suffix}",
                        content=content,
                        headers={
                            "Host": "github.com",
                            "User-Agent": "GPTHub-IDE/1",
                            "Accept": media,
                            "Content-Type": "application/x-git-upload-pack-request",
                            "Accept-Encoding": "identity",
                        },
                        extensions={"sni_hostname": "github.com"},
                    ) as response:
                        if (
                            response.status_code != 200
                            or response.headers.get("content-type", "").split(";")[0] != media
                        ):
                            raise IdeEditError("ide_git_fetch_failed")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > limit:
                                raise IdeEditError("ide_git_limit")
                            body.extend(chunk)
                        return bytes(body)

                refs = await request(
                    "GET",
                    "/info/refs?service=git-upload-pack",
                    None,
                    1024 * 1024,
                    "application/x-git-upload-pack-advertisement",
                )
                selected, sha, progress = advertised(refs, branch)
                line = f"want {sha}" + (" no-progress" if progress else "") + "\n"
                payload = (
                    f"{len(line.encode()) + 4:04x}".encode() + line.encode() + b"00000009done\n"
                )
                body = await request(
                    "POST",
                    "/git-upload-pack",
                    payload,
                    MAX_PACK + 1024,
                    "application/x-git-upload-pack-result",
                )
                if not body.startswith(b"0008NAK\nPACK") or len(body) - 8 > MAX_PACK:
                    raise IdeEditError("ide_git_fetch_failed")
                return body[8:], selected, sha
    except (TimeoutError, OSError, httpx.HTTPError, ValueError, UnicodeError):
        raise IdeEditError("ide_git_fetch_failed") from None
