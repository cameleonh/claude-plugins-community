#!/usr/bin/env python3
"""Canonical evaluator for Unified Evidence Harness v4."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
QUOTE_RE = re.compile(r'(?<!\w)[\"“]([^\"”\n]{12,500})[\"”]')
PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/)[^\r\n<>|*?\"]+")
MATERIAL_RE = re.compile(
    r"verified|confirmed|research shows|study found|according to|current|latest|tested|saved|written|downloaded|"
    r"검증|확인|연구에 따르면|논문|인용|최신|테스트|저장|작성|다운로드",
    re.I,
)
ACADEMIC_RE = re.compile(r"doi|citation|reference|journal|paper|manuscript|논문|인용|참고문헌|학술지|투고", re.I)
ACTION_RE = re.compile(r"ran|executed|tested|saved|wrote|created|downloaded|uploaded|실행|테스트|저장|작성|생성|다운로드|업로드", re.I)
RESEARCH_RE = re.compile(r"searched|researched|verified|confirmed|inspected source|검색|조사|검증|확인", re.I)
UNCERTAINTY_RE = re.compile(r"insufficient|unverified|not verified|could not verify|근거 부족|미검증|확인하지 못", re.I)
PROFILES = {"routine": 0, "research": 1, "academic": 2, "submission": 3}
OBSERVED_SCOPES = {"inspected", "read", "fetched", "executed", "tested", "written", "saved", "downloaded", "uploaded"}
RESEARCH_TOOLS = {"search", "fetch", "read"}
RUN_TOOLS = {"command", "test", "python"}
WRITE_TOOLS = {"write", "download", "upload", "command"}


def clean_url(value: str) -> str:
    return value.rstrip(".,;:!?)]}")


def clean_doi(value: str) -> str:
    return value.rstrip(".,;:!?)]}").casefold()


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def extract_urls(value: str) -> set[str]:
    return {clean_url(x) for x in URL_RE.findall(value)}


def extract_dois(value: str) -> set[str]:
    return {clean_doi(x) for x in DOI_RE.findall(value)}


def classify_profile(prompt: str, configured: str = "routine") -> str:
    configured = configured if configured in PROFILES else "routine"
    inferred = "academic" if ACADEMIC_RE.search(prompt) else "research" if MATERIAL_RE.search(prompt) else "routine"
    return max((configured, inferred), key=lambda item: PROFILES[item])


def _observed(event: dict[str, Any]) -> bool:
    return bool(event.get("ok")) and str(event.get("scope", "")).casefold() in OBSERVED_SCOPES


def evaluate(response: str, ledger: dict[str, Any], profile: str = "routine") -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    events = [x for x in ledger.get("events", []) if isinstance(x, dict)]
    observed = [x for x in events if _observed(x)]
    claims = [x for x in ledger.get("claims", []) if isinstance(x, dict)]
    receipts = [x for x in ledger.get("worker_receipts", []) if isinstance(x, dict)]
    event_by_id = {str(x.get("id")): x for x in events if x.get("id")}
    source_text = "\n".join(str(x.get("observed_text", "")) for x in observed)
    observed_urls: set[str] = set()
    observed_dois: set[str] = set()
    artifacts: set[str] = set()
    for event in observed:
        observed_urls.update(extract_urls(str(event.get("observed_text", ""))))
        observed_urls.update(clean_url(str(x)) for x in event.get("observed_urls", []) if x)
        observed_dois.update(extract_dois(str(event.get("observed_text", ""))))
        observed_dois.update(clean_doi(str(x)) for x in event.get("observed_dois", []) if x)
        artifacts.update(normalized(str(x)) for x in event.get("artifacts", []) if x)

    def block(code: str, message: str) -> None:
        findings.append({"severity": "blocking", "code": code, "message": message})

    level = PROFILES.get(profile, 0)
    if level >= 1:
        for url in sorted(extract_urls(response) - observed_urls):
            block("P001_UNOBSERVED_URL", f"URL lacks successful inspected output: {url}")
        for doi in sorted(extract_dois(response) - observed_dois):
            block("P002_UNOBSERVED_DOI", f"DOI lacks successful inspected output: {doi}")
        for quote in QUOTE_RE.findall(response):
            if normalized(quote) not in normalized(source_text):
                block("P003_UNSUPPORTED_QUOTE", "Quotation was not found in inspected output.")
        if RESEARCH_RE.search(response) and not any(_observed(x) and x.get("tool") in RESEARCH_TOOLS for x in events):
            block("P004_UNEVIDENCED_RESEARCH", "Research claim lacks a successful research event.")

    if ACTION_RE.search(response):
        has_run = any(_observed(x) and x.get("tool") in RUN_TOOLS | WRITE_TOOLS for x in events)
        if not has_run and not UNCERTAINTY_RE.search(response):
            block("P005_UNEVIDENCED_ACTION", "Completion claim lacks a successful action event.")
        for raw in PATH_RE.findall(response):
            path = raw.strip().rstrip(".,;:!?) ]")
            if normalized(path) not in artifacts and not Path(path).exists():
                block("P007_MISSING_ARTIFACT", f"Claimed artifact does not exist: {path}")

    if level >= 2 and MATERIAL_RE.search(response) and not UNCERTAINTY_RE.search(response):
        research_ok = any(_observed(x) and x.get("tool") in RESEARCH_TOOLS for x in events)
        if not research_ok:
            block("P017_NO_ACADEMIC_EVIDENCE", "Academic material claim lacks current-session inspected evidence.")

    if level >= 3 and MATERIAL_RE.search(response):
        if not claims:
            block("P011_NO_CLAIM_LEDGER", "Submission profile requires a material claim ledger.")
        for claim in claims:
            claim_id = str(claim.get("id", "<missing>"))
            verdict = str(claim.get("verdict", "")).casefold()
            support = [str(x) for x in claim.get("support_event_ids", [])]
            if verdict not in {"supported", "refuted", "insufficient", "conflicting"}:
                block("P012_INVALID_CLAIM_VERDICT", f"Invalid verdict for {claim_id}.")
            if verdict in {"supported", "refuted"} and not support:
                block("P014_MISSING_CLAIM_SUPPORT", f"Claim {claim_id} has no support events.")
            for event_id in support:
                if event_id not in event_by_id or not _observed(event_by_id[event_id]):
                    block("P015_INVALID_SUPPORT_EVENT", f"Claim {claim_id} cites invalid event {event_id}.")

    receipt_verdicts: dict[str, set[str]] = {}
    for receipt in receipts:
        receipt_id = str(receipt.get("receipt_id", "<missing>"))
        required = ("worker_id", "role", "task_scope", "status", "fresh_context", "findings", "uninspected_scope")
        if any(field not in receipt for field in required):
            block("P020_INVALID_WORKER_RECEIPT", f"Worker receipt {receipt_id} is missing required fields.")
            continue
        if receipt.get("status") not in {"completed", "blocked", "failed"}:
            block("P021_INVALID_WORKER_STATUS", f"Worker receipt {receipt_id} has an invalid status.")
        for finding in receipt.get("findings", []):
            if not isinstance(finding, dict):
                block("P020_INVALID_WORKER_RECEIPT", f"Worker receipt {receipt_id} has a malformed finding.")
                continue
            claim_id = str(finding.get("claim_id", "<missing>"))
            verdict = str(finding.get("verdict", "")).casefold()
            if verdict not in {"supported", "refuted", "insufficient", "conflicting"}:
                block("P022_INVALID_WORKER_VERDICT", f"Worker receipt {receipt_id} has an invalid verdict.")
            receipt_verdicts.setdefault(claim_id, set()).add(verdict)
            for event_id in finding.get("evidence_event_ids", []):
                event = event_by_id.get(str(event_id))
                if event is None or not _observed(event):
                    block("P015_INVALID_SUPPORT_EVENT", f"Worker receipt {receipt_id} cites invalid event {event_id}.")
    if level >= 3:
        for claim_id, verdicts in receipt_verdicts.items():
            if "supported" in verdicts and "refuted" in verdicts:
                block("P023_UNRESOLVED_WORKER_CONFLICT", f"Worker verdict conflict remains unresolved for {claim_id}.")

    return {
        "schema_version": "4.0",
        "profile": profile,
        "allow": not findings,
        "counts": {"events": len(events), "observed": len(observed), "claims": len(claims), "worker_receipts": len(receipts), "blocking": len(findings)},
        "findings": findings,
    }


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def load_jsonl(path: Path, max_bytes: int = 8_000_000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_bytes()[-max_bytes:].decode("utf-8", errors="replace")
    rows = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except json.JSONDecodeError:
            continue
    return rows
