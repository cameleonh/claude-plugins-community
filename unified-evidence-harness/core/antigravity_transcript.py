from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MAX_TRANSCRIPT_BYTES = 16_000_000


def _is_redirect(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _inside_artifact_directory(data: dict[str, Any], path: Path) -> bool:
    raw_root = data.get("artifactDirectoryPath")
    if not isinstance(raw_root, str) or not raw_root:
        return False
    root = Path(raw_root)
    if not root.is_absolute() or not root.is_dir() or _is_redirect(root):
        return False
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        if part == "..":
            return False
        current /= part
        if _is_redirect(current):
            return False
    return True


def _records(data: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw_path = data.get("transcriptPath")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    if (
        not path.is_absolute()
        or not path.is_file()
        or _is_redirect(path)
        or not _inside_artifact_directory(data, path)
    ):
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            offset = max(0, size - MAX_TRANSCRIPT_BYTES)
            stream.seek(offset)
            raw = stream.read(MAX_TRANSCRIPT_BYTES)
        if offset:
            _, separator, raw = raw.partition(b"\n")
            if not separator:
                return None
        lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError):
        return None
    indexed_rows: list[tuple[int, dict[str, Any]]] = []
    malformed: list[int] = []
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(index)
            continue
        if isinstance(row, dict):
            indexed_rows.append((index, row))
        else:
            malformed.append(index)
    latest_prompt_line = next(
        (
            index
            for index, row in reversed(indexed_rows)
            if row.get("source") == "USER_EXPLICIT"
            and row.get("type") == "USER_INPUT"
            and row.get("status") == "DONE"
            and isinstance(row.get("content"), str)
            and bool(row["content"].strip())
        ),
        None,
    )
    if latest_prompt_line is None or any(index >= latest_prompt_line for index in malformed):
        return None
    return [row for index, row in indexed_rows if index >= latest_prompt_line]


def transcript_context(data: dict[str, Any]) -> tuple[str | None, str | None]:
    rows = _records(data)
    if rows is None:
        return None, None
    prompt_index = next(
        (
            index
            for index in range(len(rows) - 1, -1, -1)
            if rows[index].get("source") == "USER_EXPLICIT"
            and rows[index].get("type") == "USER_INPUT"
            and rows[index].get("status") == "DONE"
            and isinstance(rows[index].get("content"), str)
            and bool(rows[index]["content"].strip())
        ),
        None,
    )
    if prompt_index is None:
        return None, None
    prompt = rows[prompt_index]["content"]
    answer = next(
        (
            row["content"]
            for row in reversed(rows[prompt_index + 1 :])
            if row.get("source") == "MODEL"
            and row.get("type") == "PLANNER_RESPONSE"
            and row.get("status") == "DONE"
            and isinstance(row.get("content"), str)
            and bool(row["content"].strip())
        ),
        None,
    )
    return prompt, answer


def workspace_paths(data: dict[str, Any]) -> list[Path]:
    raw_paths = data.get("workspacePaths")
    if not isinstance(raw_paths, list):
        return []
    return [
        path
        for raw in raw_paths
        if isinstance(raw, str) and raw
        if (path := Path(raw)).is_absolute() and path.is_dir() and not _is_redirect(path)
    ]
