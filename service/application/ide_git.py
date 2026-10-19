"""One bounded Git RPC; payload is an already acquired pack, not a network URL."""

import hashlib
import io
import json
import time

from infrastructure import ide_git_runtime

from application.ide_bundles import program_source
from drivers.binary_exec import BinaryExecFailure


class IdeGitFailure(Exception):
    def __init__(self, code="ide_git_unconfirmed"):
        self.code = (
            code
            if code
            in {
                "ide_git_conflict",
                "ide_git_not_empty",
                "ide_git_invalid",
                "ide_git_limit",
                "ide_runtime_expired",
                "ide_git_failed",
            }
            else "ide_git_unconfirmed"
        )
        super().__init__(self.code)


async def run_git(
    driver,
    item,
    *,
    operation,
    branch="main",
    origin="",
    commit="",
    pack=b"",
    replace_pristine_starter=False,
):
    header = dict(
        root=item.policy.root,
        operation=operation,
        branch=branch,
        origin=origin,
        commit=commit,
        deadline=item.expires_at,
        input_size=len(pack),
        input_sha256=hashlib.sha256(pack).hexdigest(),
        replace_pristine_starter=replace_pristine_starter,
    )
    program = program_source(
        extra_modules=(ide_git_runtime,), entrypoint="infrastructure.ide_git_runtime"
    )
    try:
        with io.BytesIO(pack) as source:
            async with driver.exec_binary(
                item.ref,
                program,
                header=json.dumps(header).encode() + b"\n",
                source=source,
                input_size=len(pack),
                output_limit=4096,
                timeout=max(0.1, min(30, item.expires_at - time.time())),
            ) as reply:
                if reply.exit_code or reply.diagnostic != b'{"status":"ok","operation":"git"}':
                    raise IdeGitFailure()
                result = json.loads(reply.source.read(4097))
                if type(result) is not dict:
                    raise IdeGitFailure()
                if "error" in result:
                    raise IdeGitFailure(result["error"])
                if (
                    set(result) != {"initialized", "branch"}
                    or type(result["initialized"]) is not bool
                    or (
                        result["branch"] is not None
                        and not ide_git_runtime.branch_name(result["branch"])
                    )
                ):
                    raise IdeGitFailure()
                return result
    except (BinaryExecFailure, ValueError, TypeError):
        raise IdeGitFailure() from None
