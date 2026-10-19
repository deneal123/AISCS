"""Workspace-private review proposals, outside source, tree, Git and artifacts."""

from __future__ import annotations

import json
import secrets
import shlex

from domain.files import safe_path

from application.documents.projects import DocumentProjectError

MAX_PROPOSAL_BYTES = 512_000


async def store_proposal(projects, item, path: str, proposal: dict) -> dict:
    await projects.manifest(item, path)
    state = await projects.authoring_state(item, path)
    if (
        proposal.get("base_version") != state["authoring_version"]
        or proposal.get("draft_digest") != state["draft_digest"]
    ):
        raise DocumentProjectError("source_changed")
    known = {block["block_id"] for block in state["draft"]["blocks"]}
    replacements = proposal.get("replacements")
    if not isinstance(replacements, list) or not 1 <= len(replacements) <= 32:
        raise DocumentProjectError("authoring_invalid")
    ids = [block.get("block_id") for block in replacements if isinstance(block, dict)]
    if len(ids) != len(replacements) or len(ids) != len(set(ids)) or not set(ids) <= known:
        raise DocumentProjectError("authoring_invalid")
    proposal_id = secrets.token_hex(16)
    value = {"path": path, "proposal_id": proposal_id, "proposal": proposal}
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_PROPOSAL_BYTES:
        raise DocumentProjectError("source_too_large")
    # Root is trusted and lexical policy remains the canonical path boundary.
    directory = safe_path(item.policy.root, ".gpthub-document/proposals")
    script = (
        "import os,sys; from pathlib import Path; "
        "root=Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True); "
        "assert not root.is_symlink() and not root.parent.is_symlink(); "
        "assert len(list(root.glob('*.json')))<64; "
        "dest=root/(sys.argv[2]+'.json'); "
        "fd=os.open(str(dest),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); "
        "data=sys.stdin.buffer.read(); "
        "f=os.fdopen(fd,'wb'); f.write(data); f.flush(); os.fsync(f.fileno()); f.close(); "
        "print('stored')"
    )
    result = await projects._run(
        item,
        f"python -c {shlex.quote(script)} {shlex.quote(directory)} {proposal_id}",
        stdin_payload=encoded,
    )
    if str(result.stdout or "").strip() != "stored":
        raise DocumentProjectError("authoring_checkpoint_failed")
    return {"proposal_id": proposal_id}


async def read_proposal(projects, item, proposal_id: str) -> dict:
    import re

    if re.fullmatch(r"[a-f0-9]{32}", proposal_id) is None:
        raise DocumentProjectError("authoring_invalid")
    destination = safe_path(item.policy.root, f".gpthub-document/proposals/{proposal_id}.json")
    script = (
        "import os,sys; fd=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW); "
        "f=os.fdopen(fd,'rb'); data=f.read(512001); "
        "assert len(data)<=512000; sys.stdout.buffer.write(data)"
    )
    result = await projects._run(
        item, f"python -c {shlex.quote(script)} {shlex.quote(destination)}"
    )
    try:
        value = json.loads(str(result.stdout or "null"))
        if not isinstance(value, dict) or value.get("proposal_id") != proposal_id:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise DocumentProjectError("authoring_missing") from None
