"""Match staged physical artifacts to their admitted compiler facts before rename."""

from __future__ import annotations

import posixpath

from infrastructure.document_compiler import CompilerFailure, DockerDocumentCompiler

from drivers import ContainerRef

_ROLES = (
    ("artifact", "document.pdf"),
    ("preview", "preview.png"),
    ("source_bundle", "source.zip"),
    ("visual_bundle", "visual-pages.tar"),
)


async def verify_staged_artifacts(
    compiler: DockerDocumentCompiler,
    reference: ContainerRef,
    staging: str,
    report: dict[str, object],
) -> None:
    for role, filename in _ROLES:
        expected = report.get(role)
        if expected is None and role != "artifact":
            continue
        if not isinstance(expected, dict):
            raise CompilerFailure("artifact_invalid")
        size = expected.get("size")
        digest = expected.get("sha256")
        if type(size) is not int or size < 1 or not isinstance(digest, str):
            raise CompilerFailure("artifact_invalid")
        actual = await compiler.artifact_facts(
            reference, posixpath.join(staging, filename), max_bytes=size
        )
        if actual != (digest, size):
            raise CompilerFailure("artifact_invalid")
