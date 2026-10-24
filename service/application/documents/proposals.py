"""Workspace-private review proposals, outside source, tree, Git and artifacts."""

from __future__ import annotations

import json
import shlex

from domain.documents.block_patch import BlockPatchError, apply_block_patch
from domain.documents.document_review import review_proposal_id
from domain.files import safe_path

from application.documents.projects import DocumentProjectError
from application.documents.proposal_storage import STORE_SCRIPT

MAX_PROPOSAL_BYTES = 512_000


async def store_proposal(projects, item, path: str, proposal: dict) -> dict:
    await projects.manifest(item, path)
    state = await projects.authoring_state(item, path)
    if (
        type(proposal.get("base_version")) is not int
        or proposal.get("base_version") != state["authoring_version"]
        or proposal.get("draft_digest") != state["draft_digest"]
    ):
        raise DocumentProjectError("source_changed")
    try:
        apply_block_patch(
            state["draft"]["blocks"], proposal, selected_ids=proposal.get("selected_block_ids")
        )
    except BlockPatchError:
        raise DocumentProjectError("authoring_invalid") from None
    proposal_id = review_proposal_id(path, proposal)
    value = {"path": path, "proposal_id": proposal_id, "proposal": proposal}
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(encoded) > MAX_PROPOSAL_BYTES:
        raise DocumentProjectError("source_too_large")
    # Root is trusted and lexical policy remains the canonical path boundary.
    directory = safe_path(item.policy.root, ".gpthub-document/proposals")
    result = await projects._run(
        item,
        f"python -c {shlex.quote(STORE_SCRIPT)} {shlex.quote(directory)} {proposal_id}",
        stdin_payload=encoded,
    )
    status = str(result.stdout or "").strip()
    if status not in {"stored", "reused"}:
        raise DocumentProjectError("authoring_checkpoint_failed")
    return {"proposal_id": proposal_id, "reused": status == "reused"}


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
