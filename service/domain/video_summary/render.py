"""Trusted Markdown and private workspace checkpoint projections."""

from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from service.domain.video_summary.evidence import VideoNotesDraft, digest, plain_markdown
from service.domain.video_summary.source import timestamp


def time_link(url: str, second: float) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k not in {"t", "start"}]
    query.append(("t", str(int(second))))
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def render_part(draft: VideoNotesDraft, url: str) -> str:
    lines = [f"## {timestamp(draft.start)}–{timestamp(draft.end)}", ""]
    for section in draft.sections:
        lines.extend([f"### {plain_markdown(section.title)}", ""])
        for point in section.points:
            lines.append(f"- {plain_markdown(point.text)}")
            for evidence in point.evidence:
                label = f"{timestamp(evidence.start)}–{timestamp(evidence.end)}"
                lines.append(f"  - Источник [{label}]({time_link(url, evidence.start)}):")
                lines.append(f"    > {plain_markdown(evidence.context)}")
            lines.append("")
    return "\n".join(lines)


def checkpoint(drafts: list[VideoNotesDraft]) -> str:
    body = {"schema_version": 1, "accepted_parts": [draft.payload() for draft in drafts]}
    return json.dumps({"body": body, "sha256": digest(body)}, ensure_ascii=False, indent=2)
