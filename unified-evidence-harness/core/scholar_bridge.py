#!/usr/bin/env python3
"""Read-only Scholar2Agent project discovery for the unified harness."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

CANONICAL_STATE = (
    "AGENTS.md", "START_HERE.md", "WBS.md", "FILES.md", "DECISIONS.md",
    "RESEARCH_LOG.md", "RESEARCH_ROADMAP.md",
)
SUBMISSION_RE = re.compile(r"submission|submit|final manuscript|투고|제출|최종 원고", re.I)
ACADEMIC_RE = re.compile(r"draft|revise|manuscript|citation|reference|result|초안|개정|원고|인용|참고문헌|결과", re.I)


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "SCHOLAR_PROFILE.json").is_file() and sum((candidate / name).is_file() for name in CANONICAL_STATE) >= 2:
            return candidate
    return None


def _read_profile(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / "SCHOLAR_PROFILE.json").read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def harness_profile(root: Path, prompt: str) -> str:
    if SUBMISSION_RE.search(prompt):
        return "submission"
    if ACADEMIC_RE.search(prompt):
        return "academic"
    return "research"


def project_snapshot(root: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for name in ("SCHOLAR_PROFILE.json", *CANONICAL_STATE):
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    profile = _read_profile(root)
    return {
        "kind": "scholar2agent-project",
        "root": str(root),
        "scholar_profile": profile.get("profile", "unknown"),
        "contract_id": profile.get("contract_id"),
        "files": files,
    }

