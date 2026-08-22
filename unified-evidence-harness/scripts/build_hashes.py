#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
ROOT = args.root.resolve()
EXCLUDED = {".git", "__pycache__", "trust"}
rows = {}
for path in sorted(ROOT.rglob("*")):
    if not path.is_file() or any(part in EXCLUDED for part in path.parts):
        continue
    rows[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
target = ROOT / "trust" / "hashes.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({"algorithm": "sha256", "files": rows}, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"files": len(rows), "output": str(target)}, ensure_ascii=False))
