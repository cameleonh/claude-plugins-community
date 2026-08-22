from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_hashes.py"


class BuildHashesTests(unittest.TestCase):
    def test_runtime_and_review_artifacts_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "keep.txt").write_text("trusted", encoding="utf-8")
            for relative in (
                ".omo/evidence/review.md",
                ".pytest_cache/result",
                ".mypy_cache/result",
                ".ruff_cache/result",
                "__pycache__/module.pyc",
                ".coverage",
            ):
                artifact = target / relative
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("ephemeral", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(BUILDER), "--root", str(target)],
                text=True,
                capture_output=True,
                check=False,
            )
            manifest = json.loads(
                (target / "trust" / "hashes.json").read_text(encoding="utf-8")
            )["files"]

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(set(manifest), {"keep.txt"})


if __name__ == "__main__":
    unittest.main()
