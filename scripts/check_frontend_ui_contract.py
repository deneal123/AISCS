#!/usr/bin/env python3
"""Deterministic S27 UI ownership and Workbench composition gate."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SOURCE = FRONTEND / "src"

REQUIRED_FILES = (
    FRONTEND / "DESIGN.md",
    FRONTEND / "premium-ui.json",
    SOURCE / "shared" / "controls" / "ActionLink.jsx",
    SOURCE / "shared" / "controls" / "AppSelect.jsx",
    SOURCE / "shared" / "controls" / "AppTextarea.jsx",
    SOURCE / "shared" / "hooks" / "useAppToast.js",
)
CANONICAL_CAPABILITIES = {"Select/Listbox", "Form", "Scrollbar", "Toast", "CRUD"}
COMMANDS = {"unit", "lint", "build", "accessibility", "e2e", "premium"}
CHAKRA_IMPORT = re.compile(
    r"import\s*\{(?P<names>.*?)\}\s*from\s*['\"]@chakra-ui/react['\"]",
    re.DOTALL,
)
BUTTON_LINK = re.compile(
    r"<Button\b[^>]{0,500}\bas=\{(?:Link|RouterLink)\}",
    re.DOTALL,
)
NATIVE_SELECT = re.compile(r"<select\b", re.IGNORECASE)


def _failures() -> list[str]:
    failures: list[str] = []
    for path in REQUIRED_FILES:
        if not path.is_file():
            failures.append(f"missing:{path.relative_to(ROOT).as_posix()}")

    if failures:
        return failures

    config = json.loads((FRONTEND / "premium-ui.json").read_text(encoding="utf-8"))
    if config.get("canonicalMap") != "DESIGN.md":
        failures.append("premium:canonical_source")
    required = set(config.get("requiredCapabilities", []))
    if required != CANONICAL_CAPABILITIES:
        failures.append("premium:capabilities")
    commands = set(config.get("commands", {}))
    if not COMMANDS.issubset(commands):
        failures.append("premium:commands")

    contract = (FRONTEND / "DESIGN.md").read_text(encoding="utf-8")
    header = (
        "| Capability | Canonical owner | Source of truth | "
        "Allowed variants | Verification |"
    )
    if header not in contract:
        failures.append("contract:canonical_header")
    for capability in CANONICAL_CAPABILITIES:
        if f"| {capability} |" not in contract:
            failures.append(f"contract:capability:{capability}")

    for path in SOURCE.rglob("*.jsx"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(FRONTEND).as_posix()
        if BUTTON_LINK.search(text):
            failures.append(f"navigation:button_link:{relative}")
        if NATIVE_SELECT.search(text):
            failures.append(f"select:native:{relative}")
        for match in CHAKRA_IMPORT.finditer(text):
            names = set(re.findall(r"\b[A-Za-z][A-Za-z0-9]*\b", match.group("names")))
            if "Select" in names:
                failures.append(f"select:chakra:{relative}")
            if (
                "Textarea" in names
                and relative != "src/shared/controls/AppTextarea.jsx"
            ):
                failures.append(f"textarea:chakra:{relative}")
            if "useToast" in names and relative != "src/shared/hooks/useAppToast.js":
                failures.append(f"toast:owner:{relative}")

    for relative in (
        "src/features/chat/constants/theme.js",
        "src/features/workspace-room/model/theme.js",
    ):
        text = (FRONTEND / relative).read_text(encoding="utf-8")
        if "scrollbarColor" in text or "::-webkit-scrollbar" in text:
            failures.append(f"scrollbar:local_palette:{relative}")

    line_limits = {
        "src/features/chat/page/ChatPageContainer.jsx": 700,
        "src/features/workspace-room/components/WorkHub.jsx": 320,
        "src/features/workspace-room/components/WorkContextPanel.jsx": 220,
    }
    for relative, limit in line_limits.items():
        count = len((FRONTEND / relative).read_text(encoding="utf-8").splitlines())
        if count > limit:
            failures.append(f"composition:size:{relative}:{count}>{limit}")

    routes = (SOURCE / "app" / "router" / "routes.js").read_text(encoding="utf-8")
    route_entries = re.findall(r"\{\s*path:\s*APP_ROUTES\.[A-Z_]+,(.*?)\}", routes)
    if not route_entries or any("title:" not in entry for entry in route_entries):
        failures.append("routes:title")
    app = (SOURCE / "App.js").read_text(encoding="utf-8")
    chat = (SOURCE / "features" / "chat" / "page" / "ChatPageContainer.jsx").read_text(
        encoding="utf-8"
    )
    if "RouteDocumentTitle" not in app or "useDocumentTitle(activeSurface" not in chat:
        failures.append("routes:dynamic_title")
    return sorted(set(failures))


def main() -> int:
    failures = _failures()
    if failures:
        print("frontend UI contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(
        "frontend UI contract passed: canonical owners, route titles, "
        "Workbench composition"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
