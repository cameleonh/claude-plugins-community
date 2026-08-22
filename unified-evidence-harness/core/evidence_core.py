#!/usr/bin/env python3
"""Canonical evaluator for Unified Evidence Harness v4."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

URL_RE = re.compile(r"https?://[^\s<>\"'\\]+", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
QUOTE_RE = re.compile(r'(?<!\w)[\"“]([^\"”\n]{12,500})[\"”]')
DRIVE_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/][^\s<>|*?\"'`]+")
UNC_PATH_RE = re.compile(r"\\\\[A-Za-z0-9_.\-]+\\[^\s<>|*?\"'`]+")
RELATIVE_PATH_RE = re.compile(
    r"(?<![\w./\\-])(?:\.{1,2}[\\/])?(?:[A-Za-z0-9_][A-Za-z0-9_.\-]*[\\/])+"
    r"[A-Za-z0-9_][A-Za-z0-9_.\-]*\.[A-Za-z][A-Za-z0-9]{0,11}(?![\w.])"
)
PROSE_QUOTE_RE = re.compile(r"“[^”\n]+”")
EXAMPLE_CONTEXT_RE = re.compile(
    r"예시|예문|예제|예를 들어|샘플|템플릿|프롬프트|지시문|지시어|지침|요청문|용어집|문구|표현|"
    r"for example|e\.g\.|such as|example|template|prompt|instruction|glossary",
    re.I,
)
CITATION_CONTEXT_RE = re.compile(
    r"10\.\d{4,9}/|https?://|www\.|arxiv|doi|"
    r"et\s+al\.?|according\s+to|"
    r"[A-Za-z][A-Za-z'’\-]*\s*\(\s*(?:19|20)\d{2}\s*\)|"
    r"[A-Za-z][A-Za-z'’\-]*,\s*(?:19|20)\d{2}|"
    r"[가-힣]{1,4}\s*\(\s*(?:19|20)\d{2}\s*\)|"
    r"저자|연구자|출처|인용|참고문헌|각주|재인용|주장했|주장한|말했|강조했|지적했|"
    r"citation|reference|bibliography|source:|"
    r"\"(?:citation|source|evidence|quote)\"\s*:",
    re.I,
)
NO_VERIFIABLE_EXTERNAL_QUOTES = "외부 출처가 연결된 검증 대상 인용문 없음"
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
    value = value.replace("\\r", "").replace("\\n", "").replace("\\t", "")
    return value.rstrip("\\.,;:!?)]}")


def is_explanatory_quote(response: str, start: int, end: int) -> bool:
    window = response[max(0, start - 80): end + 40]
    return bool(re.search(
        r"제목|논문명|용어|표현|라벨|이름|상태|표시|문구|코드|label|title|term|status",
        window,
        re.I,
    ))


def quote_window(response: str, start: int, end: int) -> str:
    return response[max(0, start - 120): end + 120]


def plain_window(response: str, start: int, end: int) -> str:
    """Window with URLs removed, so domain tokens (example.org) cannot
    masquerade as example-context markers."""
    return URL_RE.sub(" ", quote_window(response, start, end))


def has_external_citation_context(response: str, start: int, end: int) -> bool:
    """True when an external source is linked near the quoted span."""
    return bool(CITATION_CONTEXT_RE.search(quote_window(response, start, end)))


def is_user_example_quote(response: str, start: int, end: int) -> bool:
    """True for example/instructional quotes with no external source claim.

    User-request examples, prompt templates, glossary entries, and other
    didactic quoting are not external citations. An explicit example marker
    wins over stray citation tokens nearby; without one, a quote is an
    example unless external citation context is attached.
    """
    if EXAMPLE_CONTEXT_RE.search(plain_window(response, start, end)):
        return True
    return not has_external_citation_context(response, start, end)


def is_verifiable_external_quote(response: str, start: int, end: int) -> bool:
    """True for quotes attributed to an external source that must be verified."""
    if is_explanatory_quote(response, start, end) or is_user_example_quote(response, start, end):
        return False
    return has_external_citation_context(response, start, end)


def clean_doi(value: str) -> str:
    return value.rstrip(".,;:!?)]}").casefold()


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def extract_urls(value: str) -> set[str]:
    return {clean_url(x) for x in URL_RE.findall(value)}


def extract_dois(value: str) -> set[str]:
    return {clean_doi(x) for x in DOI_RE.findall(value)}


def extract_artifact_candidates(value: str) -> set[str]:
    """Return path-shaped artifact candidates from prose.

    Only drive paths, UNC paths, and project-relative file paths count as
    artifact references. Prose separators (Korean phrases, markdown emphasis,
    backtick descriptions, typographic quotations, URLs, DOIs) are never
    artifact claims.
    """
    stripped = PROSE_QUOTE_RE.sub(" ", DOI_RE.sub(" ", URL_RE.sub(" ", value)))
    found: set[str] = set()
    for regex in (DRIVE_PATH_RE, UNC_PATH_RE, RELATIVE_PATH_RE):
        for raw in regex.findall(stripped):
            candidate = raw.strip().strip("\"'`").rstrip(".,;:!?)").rstrip("\\/")
            if len(candidate) > 1:
                found.add(candidate)
    return found


def artifact_path_exists(path: str) -> bool:
    candidates = [Path(path)]
    mapped = re.fullmatch(r"/([A-Za-z])/(.+)", path)
    if mapped:
        candidates.append(Path(f"{mapped.group(1).upper()}:/{mapped.group(2)}"))
    return any(candidate.exists() for candidate in candidates)


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

    quote_gate: str | None = None
    level = PROFILES.get(profile, 0)
    if level >= 1:
        for url in sorted(extract_urls(response) - observed_urls):
            block("P001_UNOBSERVED_URL", f"URL lacks successful inspected output: {url}")
        for doi in sorted(extract_dois(response) - observed_dois):
            block("P002_UNOBSERVED_DOI", f"DOI lacks successful inspected output: {doi}")
        quotes = list(QUOTE_RE.finditer(response))
        verifiable_quotes = 0
        for match in quotes:
            if not is_verifiable_external_quote(response, match.start(), match.end()):
                continue
            verifiable_quotes += 1
            quote = match.group(1)
            if normalized(quote) not in normalized(source_text):
                block("P003_UNSUPPORTED_QUOTE", "Quotation was not found in inspected output.")
        if quotes and verifiable_quotes == 0:
            quote_gate = NO_VERIFIABLE_EXTERNAL_QUOTES
        if RESEARCH_RE.search(response) and not any(_observed(x) and x.get("tool") in RESEARCH_TOOLS for x in events):
            block("P004_UNEVIDENCED_RESEARCH", "Research claim lacks a successful research event.")

    if ACTION_RE.search(response):
        has_run = any(_observed(x) and x.get("tool") in RUN_TOOLS | WRITE_TOOLS for x in events)
        if not has_run and not UNCERTAINTY_RE.search(response):
            block("P005_UNEVIDENCED_ACTION", "Completion claim lacks a successful action event.")
        for path in sorted(extract_artifact_candidates(response)):
            if normalized(path) not in artifacts and not artifact_path_exists(path):
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
        "quote_gate": quote_gate,
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
