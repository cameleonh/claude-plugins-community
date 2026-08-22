#!/usr/bin/env python3
"""Shared lifecycle adapter for Codex, Antigravity, and ZCode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evidence_core import classify_profile, digest, evaluate, extract_dois, extract_urls, load_jsonl
from scholar_bridge import find_project_root, harness_profile, project_snapshot

SECRET_RE = re.compile(r"token|secret|password|cookie|authorization|api.?key", re.I)
MUTATION_RE = re.compile(r"remove-item|rmdir|set-content|out-file|write_text|unlink\(|rmtree|apply_patch", re.I)
PROTECTED_RE = re.compile(r"evidence[-_ ]harness|evidence-bound|hashes\.json", re.I)


def verify_runtime_hashes() -> bool:
    script = Path(__file__).resolve()
    root = script.parent.parent
    manifest = root / "trust" / "hashes.json"
    if not manifest.exists():
        return False
    try:
        expected = json.loads(manifest.read_text(encoding="utf-8")).get("files", {})
        for path in (script, script.with_name("evidence_core.py")):
            relative = path.relative_to(root).as_posix()
            if expected.get(relative) != hashlib.sha256(path.read_bytes()).hexdigest():
                return False
        return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False))


def read_payload() -> dict[str, Any]:
    value = json.loads(sys.stdin.read() or "{}")
    return value if isinstance(value, dict) else {}


def flatten(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [part for item in value.values() for part in flatten(item)]
    if isinstance(value, list):
        return [part for item in value for part in flatten(item)]
    return []


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): "<redacted>" if SECRET_RE.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(x) for x in value]
    return value


def session_id(data: dict[str, Any]) -> str:
    raw = str(data.get("session_id") or data.get("sessionId") or data.get("conversationId") or "unknown")
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)[:160]


def data_root(platform: str, data: dict[str, Any]) -> Path:
    configured = os.environ.get("EVIDENCE_HARNESS_DATA")
    if configured:
        root = Path(configured)
    elif platform == "antigravity":
        base = data.get("artifactDirectoryPath") or Path.home() / ".gemini" / "antigravity" / "hook-data"
        root = Path(str(base)) / "evidence_harness"
    else:
        root = Path.home() / (".zcode" if platform == "zcode" else ".codex") / "evidence_harness_data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def paths(platform: str, data: dict[str, Any]) -> tuple[Path, Path, Path]:
    root = data_root(platform, data)
    key = session_id(data)
    return root / f"{key}.events.jsonl", root / f"{key}.prompt.json", root / f"{key}.checkpoint.json"


def tool_fields(platform: str, data: dict[str, Any]) -> tuple[str, Any, Any, str]:
    if platform == "antigravity":
        call = data.get("toolCall") if isinstance(data.get("toolCall"), dict) else {}
        return str(call.get("name", "")), call.get("args", {}), data.get("toolResult") or data.get("toolResponse") or data.get("result") or data.get("output") or {}, str(data.get("error", ""))
    return (
        str(data.get("tool_name") or data.get("toolName") or data.get("tool") or ""),
        data.get("tool_input") or data.get("toolInput") or data.get("input") or {},
        data.get("tool_response") or data.get("toolResponse") or data.get("output") or {},
        str(data.get("error", "")),
    )


def map_tool(name: str, input_text: str, output_text: str) -> str:
    probe = f"{name}\n{input_text[:8000]}".casefold()
    if any(x in probe for x in ("search_query", "web_search", "search")):
        return "search"
    if any(x in probe for x in ("web__run", "web.run", "browser", "fetch", "open_url", "read_url")):
        return "fetch"
    if any(x in probe for x in ("read", "view", "open", "grep", "glob", "rg ")):
        return "read"
    if any(x in probe for x in ("write", "edit", "patch", "replace")):
        return "write"
    if any(x in probe for x in ("test", "pytest", "benchmark")):
        return "test"
    if any(x in probe for x in ("exec", "shell", "command", "terminal", "bash", "powershell")):
        return "command"
    if extract_urls(output_text):
        return "fetch"
    return name.casefold()


def append_event(platform: str, data: dict[str, Any], forced_ok: bool | None = None) -> None:
    name, tool_input, tool_output, error = tool_fields(platform, data)
    input_text = "\n".join(flatten(tool_input))
    output_text = json.dumps(tool_output, ensure_ascii=False, default=str)
    ok = forced_ok if forced_ok is not None else not bool(error)
    mapped = map_tool(name, input_text, output_text)
    artifacts = []
    if ok and mapped == "write" and isinstance(tool_input, dict):
        for key in ("file_path", "filePath", "path", "TargetFile", "targetFile"):
            if tool_input.get(key):
                artifacts.append(str(tool_input[key]))
    record = {
        "id": str(data.get("tool_use_id") or data.get("toolUseId") or data.get("stepIdx") or datetime.now(timezone.utc).timestamp()),
        "time": datetime.now(timezone.utc).isoformat(), "tool": mapped, "original_tool": name,
        "ok": ok, "scope": "written" if mapped == "write" else "executed" if mapped in {"command", "test"} else "inspected",
        "observed_text": output_text if ok else "", "observed_urls": sorted(extract_urls(output_text)) if ok else [],
        "observed_dois": sorted(extract_dois(output_text)) if ok else [], "artifacts": artifacts,
        "requested_inputs": redact(tool_input), "error": error if not ok else "",
    }
    event_path, _, _ = paths(platform, data)
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def output_context(platform: str, event: str, context: str) -> None:
    if platform == "antigravity":
        emit({"injectSteps": [{"ephemeralMessage": context}]})
    else:
        emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}})


def output_pretool(platform: str, allow: bool, reason: str) -> None:
    if platform == "antigravity":
        emit({"decision": "allow" if allow else "deny", "reason": reason})
    else:
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow" if allow else "deny", "permissionDecisionReason": reason}})


def output_stop(platform: str, allow: bool, reason: str = "") -> None:
    if allow:
        emit({"decision": "stop"} if platform == "antigravity" else {})
    elif platform == "antigravity":
        emit({"decision": "continue", "reason": reason})
    else:
        emit({"decision": "block", "reason": reason})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("codex", "antigravity", "zcode"), required=True)
    parser.add_argument("--event", required=True)
    args = parser.parse_args()
    data = read_payload()
    platform, event = args.platform, args.event
    try:
        if not verify_runtime_hashes():
            if event == "stop":
                output_stop(platform, False, "Unified evidence gate: runtime trust hash mismatch or missing registration.")
            elif event == "pre-tool":
                output_pretool(platform, False, "Unified evidence gate: runtime trust hash mismatch or missing registration.")
            else:
                emit({})
            return 0
        event_path, prompt_path, checkpoint_path = paths(platform, data)
        if event in {"session-start", "pre-invocation"}:
            output_context(platform, "SessionStart", "Unified Evidence Harness v4 is active. Enforcement is proportional: routine work checks actions; research and academic work also require inspected source evidence.")
        elif event == "user-prompt":
            prompt = str(data.get("prompt", ""))
            configured = os.environ.get("EVIDENCE_HARNESS_PROFILE", "routine")
            cwd = Path(str(data.get("cwd") or os.getcwd()))
            project_root = find_project_root(cwd)
            if project_root is not None:
                configured = harness_profile(project_root, prompt)
            state = {"prompt": prompt, "profile": classify_profile(prompt, configured), "time": datetime.now(timezone.utc).isoformat()}
            if project_root is not None:
                state["scholar_project"] = project_snapshot(project_root)
            prompt_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            output_context(platform, "UserPromptSubmit", f"Evidence profile: {state['profile']}.")
        elif event == "pre-tool":
            name, tool_input, _, _ = tool_fields(platform, data)
            text = "\n".join(flatten(tool_input))
            mutation = bool(MUTATION_RE.search(text)) or any(x in name.casefold() for x in ("write", "edit", "patch", "replace"))
            output_pretool(platform, not (mutation and PROTECTED_RE.search(text)), "Harness integrity check.")
        elif event in {"post-tool", "post-tool-failure"}:
            append_event(platform, data, event == "post-tool")
            emit({})
        elif event in {"pre-compact", "compact"}:
            state = json.loads(prompt_path.read_text(encoding="utf-8")) if prompt_path.exists() else {"profile": "routine"}
            checkpoint = {"schema_version": "4.0", "profile": state.get("profile", "routine"), "event_ids": [x.get("id") for x in load_jsonl(event_path)], "scholar_project": state.get("scholar_project"), "time": datetime.now(timezone.utc).isoformat()}
            checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
            output_context(platform, "PreCompact", "Evidence checkpoint preserved outside conversation history; compaction does not promote remembered content into evidence.")
        elif event == "stop":
            answer = str(data.get("last_assistant_message") or data.get("lastAssistantMessage") or data.get("assistant_message") or "")
            state = json.loads(prompt_path.read_text(encoding="utf-8")) if prompt_path.exists() else {"profile": "routine"}
            report = evaluate(answer, {"events": load_jsonl(event_path), "claims": data.get("claims", []), "worker_receipts": data.get("worker_receipts", [])}, str(state.get("profile", "routine")))
            codes = sorted({x["code"] for x in report["findings"]})
            reason = f"Unified evidence gate [{digest(answer)}]: {', '.join(codes)}. Gather inspected evidence or state uncertainty."
            output_stop(platform, bool(report["allow"]), reason)
        else:
            emit({})
        return 0
    except Exception as exc:
        if event == "stop":
            output_stop(platform, False, f"Unified evidence gate failed closed: {type(exc).__name__}.")
        elif event == "pre-tool":
            output_pretool(platform, False, "Evidence hook could not safely assess this call.")
        else:
            emit({})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
