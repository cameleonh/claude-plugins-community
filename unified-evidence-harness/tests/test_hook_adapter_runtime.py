from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_scholar_bridge import create_project


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "core" / "hook_adapter.py"


def run_hook(
    event: str,
    payload: str,
    environment: dict[str, str],
    adapter: Path = ADAPTER,
    platform: str = "codex",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(adapter), "--platform", platform, "--event", event],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


class HookAdapterRuntimeTests(unittest.TestCase):
    def test_real_stop_uses_scholar_registry_and_current_read_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            project = temporary / "project"
            project.mkdir()
            result = create_project(project)
            data = temporary / "harness-data"
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(data)}
            session_id = "scholar-positive"

            prompt = run_hook(
                "user-prompt",
                json.dumps(
                    {
                        "session_id": session_id,
                        "cwd": str(project),
                        "prompt": "Prepare final submission",
                    }
                ),
                environment,
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)
            tool = run_hook(
                "post-tool",
                json.dumps(
                    {
                        "session_id": session_id,
                        "cwd": str(project),
                        "tool_use_id": "T1",
                        "tool_name": "read",
                        "tool_input": {"file_path": str(result)},
                        "tool_response": {"path": str(result), "status": "inspected"},
                    }
                ),
                environment,
            )
            self.assertEqual(tool.returncode, 0, tool.stderr)
            rows = [
                json.loads(line)
                for line in (data / f"{session_id}.events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn(str(result), rows[0]["artifacts"])

            stop = run_hook(
                "stop",
                json.dumps(
                    {
                        "session_id": session_id,
                        "cwd": str(project),
                        "last_assistant_message": "The verified result was confirmed.",
                    }
                ),
                environment,
            )
            self.assertEqual(stop.returncode, 0, stop.stderr)
            self.assertEqual(json.loads(stop.stdout), {})

    def test_real_stop_blocks_scholar_claim_without_current_read_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            project = temporary / "project"
            project.mkdir()
            create_project(project)
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(temporary / "harness-data")}
            session_id = "scholar-negative"

            run_hook(
                "user-prompt",
                json.dumps(
                    {
                        "session_id": session_id,
                        "cwd": str(project),
                        "prompt": "Prepare final submission",
                    }
                ),
                environment,
            )
            stop = run_hook(
                "stop",
                json.dumps(
                    {
                        "session_id": session_id,
                        "cwd": str(project),
                        "last_assistant_message": "The verified result was confirmed.",
                    }
                ),
                environment,
            )
            output = json.loads(stop.stdout)

            self.assertEqual(stop.returncode, 0, stop.stderr)
            self.assertEqual(output["decision"], "block")
            self.assertIn("P014_MISSING_CLAIM_SUPPORT", output["reason"])

    def test_malformed_payload_fails_closed_without_unbound_local_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": tmp}
            stop = run_hook("stop", "{", environment)
            output = json.loads(stop.stdout)

            self.assertEqual(stop.returncode, 0, stop.stderr)
            self.assertEqual(output["decision"], "block")
            self.assertIn("JSONDecodeError", output["reason"])
            self.assertNotIn("UnboundLocalError", output["reason"])

    def test_corrupt_prompt_state_is_quarantined_and_blocks_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(data)}
            session_id = "corrupt-state"
            prompt_path = data / f"{session_id}.prompt.json"
            prompt_path.write_bytes(b'{"profile":')

            stop = run_hook(
                "stop",
                json.dumps(
                    {
                        "session_id": session_id,
                        "last_assistant_message": "Done.",
                    }
                ),
                environment,
            )
            output = json.loads(stop.stdout)
            quarantines = list(data.glob(f"{prompt_path.name}.corrupt.*"))
            regenerated = json.loads(prompt_path.read_text(encoding="utf-8"))

            self.assertEqual(stop.returncode, 0, stop.stderr)
            self.assertEqual(output["decision"], "block")
            self.assertIn("quarantined", output["reason"])
            self.assertNotIn("JSONDecodeError", output["reason"])
            self.assertEqual(len(quarantines), 1)
            self.assertEqual(quarantines[0].read_bytes(), b'{"profile":')
            self.assertIs(regenerated["recovered_corrupt_state"], True)

    def test_scholar_bridge_hash_mismatch_blocks_stop_and_pretool(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            core = temporary / "core"
            trust = temporary / "trust"
            core.mkdir()
            trust.mkdir()
            for name in (
                "hook_adapter.py",
                "evidence_core.py",
                "scholar_bridge.py",
                "antigravity_transcript.py",
            ):
                shutil.copy2(ROOT / "core" / name, core / name)
            shutil.copy2(ROOT / "trust" / "hashes.json", trust / "hashes.json")
            with (core / "scholar_bridge.py").open("a", encoding="utf-8") as stream:
                stream.write("\nTAMPERED = True\n")
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(temporary / "data")}

            stop = run_hook("stop", "{}", environment, core / "hook_adapter.py")
            pretool = run_hook(
                "pre-tool",
                json.dumps({"tool_name": "write", "tool_input": {"file_path": "outside.txt"}}),
                environment,
                core / "hook_adapter.py",
            )
            stop_output = json.loads(stop.stdout)
            pretool_output = json.loads(pretool.stdout)

            self.assertEqual(stop_output["decision"], "block")
            self.assertIn("runtime trust hash mismatch", stop_output["reason"])
            self.assertEqual(
                pretool_output["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )


if __name__ == "__main__":
    unittest.main()
