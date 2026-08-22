from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from hook_adapter import atomic_write_json, load_json_object


mode, path_text, start_text, identity_text, iterations_text = sys.argv[1:]
path = Path(path_text)
start = Path(start_text)
identity = int(identity_text)
iterations = int(iterations_text)

while not start.exists():
    time.sleep(0.001)

if mode == "writer":
    for iteration in range(iterations):
        atomic_write_json(path, {"writer": identity, "iteration": iteration})
elif mode == "reader":
    for _ in range(iterations):
        value = load_json_object(path, {"writer": -2, "iteration": -2})
        if not isinstance(value, dict):
            raise RuntimeError("state is not an object")
else:
    raise ValueError(mode)
