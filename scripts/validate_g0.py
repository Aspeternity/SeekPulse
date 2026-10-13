#!/usr/bin/env python3
"""Fast offline safety/manifest check for the G0 overlay."""

from __future__ import annotations

import sys
from pathlib import Path

from bootstrap_issues import load_seed

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/01-task.yml",
    ".github/ISSUE_TEMPLATE/02-bug.yml",
    ".github/workflows/g0-ci.yml",
    "docs/PLAN.md",
    "docs/APPROVALS.md",
    "docs/APPROVALS.json",
    "docs/G0_HANDOFF.md",
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "docs/PROJECT_STATE.md",
    "docs/TEST_MATRIX.md",
    "docs/UPSTREAM.md",
    "docs/COLLABORATION.md",
    "docs/ISSUE_SEED.json",
    "scripts/context_report.py",
    "scripts/bootstrap_issues.py",
)


def validate() -> list[str]:
    errors = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            errors.append(f"missing {rel}")
    approvals = (ROOT / "docs/APPROVALS.md").read_text(encoding="utf-8") if (ROOT / "docs/APPROVALS.md").exists() else ""
    if "当前执行范围：仅 G0" not in approvals:
        errors.append("current authorization boundary missing")
    for path in ("CLAUDE.md", "GEMINI.md"):
        if (ROOT / path).exists() and "AGENTS.md" not in (ROOT / path).read_text(encoding="utf-8"):
            errors.append(f"{path} does not reference AGENTS.md")
    try:
        tasks = load_seed()
        if not any(task["key"].startswith("G0-") for task in tasks):
            errors.append("issue seed has no G0 tasks")
    except Exception as exc:
        errors.append(f"issue seed error: {type(exc).__name__}: {exc}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print("G0 FAIL:", error, file=sys.stderr)
        return 1
    print("G0 PASS: required governance files, approval boundary, and issue seed verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
