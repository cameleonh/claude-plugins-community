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
CLAIMS_REGISTRY = Path("03_analysis/claims_registry.json")
REVIEWER_REPORTS = Path("summaries/reviewer_reports")
WORKER_RECEIPT_REQUIRED = {
    "schema_version", "receipt_id", "worker_id", "role", "task_scope", "status",
    "fresh_context", "input_artifacts", "inspected_artifacts", "findings",
    "uninspected_scope",
}
SHA256_RE = re.compile(r"[a-fA-F0-9]{64}\Z")
SUBMISSION_RE = re.compile(r"submission|submit|final manuscript|투고|제출|최종 원고", re.I)
ACADEMIC_RE = re.compile(r"draft|revise|manuscript|citation|reference|result|초안|개정|원고|인용|참고문헌|결과", re.I)


def _is_redirect(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _safe_descendant(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    current = root
    if _is_redirect(current):
        return False
    for part in relative.parts:
        current /= part
        if _is_redirect(current):
            return False
    return True


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        profile = candidate / "SCHOLAR_PROFILE.json"
        state_files = [candidate / name for name in CANONICAL_STATE]
        if (
            profile.is_file()
            and _safe_descendant(candidate, profile)
            and sum(path.is_file() and _safe_descendant(candidate, path) for path in state_files) >= 2
        ):
            return candidate
    return None


def _read_profile(root: Path) -> dict[str, Any]:
    path = _safe_project_file(root, "SCHOLAR_PROFILE.json")
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
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
        path = _safe_project_file(root, name)
        if path is None:
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


def _load_json(path: Path, max_bytes: int = 2_000_000) -> Any:
    if not path.is_file() or _is_redirect(path) or path.stat().st_size > max_bytes:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _safe_project_file(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = root.joinpath(relative)
    return candidate if candidate.is_file() and _safe_descendant(root, candidate) else None


def _safe_project_directory(root: Path, relative: Path) -> Path | None:
    candidate = root / relative
    return candidate if candidate.is_dir() and _safe_descendant(root, candidate) else None


def _json_pointer(document: Any, pointer: Any) -> tuple[bool, Any]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return False, None
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        match current:
            case dict():
                if token not in current:
                    return False, None
                current = current[token]
            case list():
                if not token.isdigit() or int(token) >= len(current):
                    return False, None
                current = current[int(token)]
            case _:
                return False, None
    return True, current


def _normalized_path_text(value: str) -> str:
    return re.sub(r"/+", "/", value.casefold().replace("\\", "/"))


def _inspected_artifact_events(events: list[dict[str, Any]]) -> list[tuple[str, set[str]]]:
    observed: list[tuple[str, set[str]]] = []
    for event in events:
        event_id = event.get("id")
        scope = str(event.get("scope", "")).casefold()
        tool = str(event.get("tool", "")).casefold()
        if not event_id or not event.get("ok") or scope != "inspected" or tool != "read":
            continue
        artifacts = {
            _normalized_path_text(str(path))
            for path in event.get("artifacts", [])
            if isinstance(path, str) and path
        }
        observed.append((str(event_id), artifacts))
    return observed


def _support_event_ids(
    root: Path,
    artifact: Path,
    observed_events: list[tuple[str, set[str]]],
) -> list[str]:
    forms = {
        _normalized_path_text(str(artifact)),
        _normalized_path_text(artifact.relative_to(root).as_posix()),
    }
    return [event_id for event_id, artifacts in observed_events if forms & artifacts]


def _project_claims(root: Path, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry_path = _safe_project_file(root, CLAIMS_REGISTRY.as_posix())
    registry = _load_json(registry_path) if registry_path is not None else None
    if not isinstance(registry, dict) or not isinstance(registry.get("claims"), list):
        return []
    observed_events = _inspected_artifact_events(events)
    manuscripts = [
        text
        for relative in ("manuscript.md", "06_manuscript/manuscript.md")
        if (path := _safe_project_file(root, relative)) is not None
        if isinstance((text := _load_text(path)), str)
    ]
    adapted: list[dict[str, Any]] = []
    for index, claim in enumerate(registry["claims"][:256]):
        claim_id = str(claim.get("id", f"<missing:{index}>") if isinstance(claim, dict) else f"<missing:{index}>")
        support: list[str] = []
        if isinstance(claim, dict):
            artifact = _safe_project_file(root, claim.get("artifact"))
            quote = claim.get("manuscript_quote")
            document = _load_json(artifact) if artifact is not None else None
            resolved, value = _json_pointer(document, claim.get("json_pointer"))
            quote_ok = isinstance(quote, str) and bool(quote) and any(quote in manuscript for manuscript in manuscripts)
            value_ok = "value" in claim and resolved and value == claim["value"]
            if artifact is not None and quote_ok and value_ok:
                support = _support_event_ids(root, artifact, observed_events)
        adapted.append({"id": claim_id, "verdict": "supported", "support_event_ids": support})
    return adapted


def _load_text(path: Path, max_bytes: int = 4_000_000) -> str | None:
    if not path.is_file() or _is_redirect(path) or path.stat().st_size > max_bytes:
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _valid_artifacts(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and bool(item["path"])
        and isinstance(item.get("sha256"), str)
        and bool(SHA256_RE.fullmatch(item["sha256"]))
        for item in value
    )


def _valid_worker_receipt(value: Any) -> bool:
    if not isinstance(value, dict) or not WORKER_RECEIPT_REQUIRED.issubset(value):
        return False
    if value.get("schema_version") != 1 or value.get("status") not in {"completed", "blocked", "failed"}:
        return False
    if not isinstance(value.get("fresh_context"), bool):
        return False
    if not _valid_artifacts(value.get("input_artifacts")) or not _valid_artifacts(value.get("inspected_artifacts")):
        return False
    findings = value.get("findings")
    return isinstance(findings, list) and all(
        isinstance(item, dict)
        and {"claim_id", "verdict", "severity", "evidence_event_ids", "limitation"}.issubset(item)
        for item in findings
    )


def _project_receipts(root: Path) -> list[dict[str, Any]]:
    directory = _safe_project_directory(root, REVIEWER_REPORTS)
    if directory is None:
        return []
    receipts: list[dict[str, Any]] = []
    paths = sorted(directory.glob("*.json"))
    for path in paths[:64]:
        value = _load_json(path)
        if _valid_worker_receipt(value):
            receipts.append(value)
        else:
            receipts.append({"receipt_id": f"scholar:{path.name}"})
    if len(paths) > 64:
        receipts.append({"receipt_id": f"scholar:overflow:{len(paths)}"})
    return receipts


def merge_project_evidence(root: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    resolved = root.resolve()
    if find_project_root(resolved) != resolved:
        return ledger
    events = [item for item in ledger.get("events", []) if isinstance(item, dict)]
    claims = [item for item in ledger.get("claims", []) if isinstance(item, dict)]
    receipts = [item for item in ledger.get("worker_receipts", []) if isinstance(item, dict)]
    return {
        **ledger,
        "events": events,
        "claims": [*claims, *_project_claims(resolved, events)],
        "worker_receipts": [*receipts, *_project_receipts(resolved)],
    }
