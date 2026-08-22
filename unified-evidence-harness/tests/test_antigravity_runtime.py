from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.test_hook_adapter_runtime import run_hook
from tests.test_scholar_bridge import create_project


def write_transcript(path: Path, prompt: str, answer: str | None) -> None:
    rows = [
        {
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "content": prompt,
        }
    ]
    if answer is not None:
        rows.append(
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "content": answer,
            }
        )
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class AntigravityRuntimeTests(unittest.TestCase):
    def test_transcript_and_view_file_support_scholar_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            project = temporary / "project"
            project.mkdir()
            result = create_project(project)
            transcript = temporary / "transcript.jsonl"
            write_transcript(
                transcript,
                "Prepare final submission",
                "The verified result was confirmed.",
            )
            data = temporary / "harness-data"
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(data)}
            common = {
                "conversationId": "antigravity-scholar",
                "workspacePaths": [str(project)],
                "transcriptPath": str(transcript),
                "artifactDirectoryPath": str(temporary),
            }

            start = run_hook(
                "pre-invocation",
                json.dumps(common),
                environment,
                platform="antigravity",
            )
            self.assertEqual(start.returncode, 0, start.stderr)
            state = json.loads(
                (data / "antigravity-scholar.prompt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["profile"], "submission")
            self.assertEqual(state["scholar_project"]["root"], str(project))

            tool = run_hook(
                "post-tool",
                json.dumps(
                    {
                        **common,
                        "toolCall": {
                            "name": "view_file",
                            "args": {"AbsolutePath": str(result)},
                        },
                        "toolResult": {"path": str(result), "status": "inspected"},
                    }
                ),
                environment,
                platform="antigravity",
            )
            self.assertEqual(tool.returncode, 0, tool.stderr)
            event = json.loads(
                (data / "antigravity-scholar.events.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(event["artifacts"], [str(result)])

            stop = run_hook(
                "stop",
                json.dumps({**common, "fullyIdle": True}),
                environment,
                platform="antigravity",
            )
            self.assertEqual(stop.returncode, 0, stop.stderr)
            self.assertEqual(json.loads(stop.stdout), {"decision": "stop"})

    def test_missing_transcript_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(temporary / "data")}
            payload = {
                "conversationId": "missing-transcript",
                "workspacePaths": [str(temporary)],
                "transcriptPath": str(temporary / "missing.jsonl"),
                "fullyIdle": True,
            }

            stop = run_hook(
                "stop",
                json.dumps(payload),
                environment,
                platform="antigravity",
            )
            output = json.loads(stop.stdout)

            self.assertEqual(output["decision"], "continue")
            self.assertIn("transcript", output["reason"].casefold())

    def test_non_idle_stop_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            transcript = temporary / "transcript.jsonl"
            write_transcript(transcript, "Explain this", "Done")
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(temporary / "data")}
            payload = {
                "conversationId": "not-idle",
                "workspacePaths": [str(temporary)],
                "transcriptPath": str(transcript),
                "fullyIdle": False,
            }

            stop = run_hook(
                "stop",
                json.dumps(payload),
                environment,
                platform="antigravity",
            )
            output = json.loads(stop.stdout)

            self.assertEqual(output["decision"], "continue")
            self.assertIn("fully idle", output["reason"].casefold())

    def test_transcript_outside_artifact_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            artifacts = temporary / "artifacts"
            artifacts.mkdir()
            transcript = temporary / "transcript.jsonl"
            write_transcript(transcript, "Explain this", "Done")
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(temporary / "data")}
            payload = {
                "conversationId": "outside-transcript",
                "workspacePaths": [str(temporary)],
                "artifactDirectoryPath": str(artifacts),
                "transcriptPath": str(transcript),
                "fullyIdle": True,
            }

            stop = run_hook(
                "stop",
                json.dumps(payload),
                environment,
                platform="antigravity",
            )
            output = json.loads(stop.stdout)

            self.assertEqual(output["decision"], "continue")
            self.assertIn("transcript", output["reason"].casefold())

    def test_historical_malformed_record_before_current_turn_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            transcript = temporary / "transcript.jsonl"
            transcript.write_text(
                '{"broken"\n'
                + json.dumps(
                    {
                        "source": "USER_EXPLICIT",
                        "type": "USER_INPUT",
                        "status": "DONE",
                        "content": "Explain a simple concept",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "source": "MODEL",
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "content": "A concise explanation.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(temporary / "data")}
            payload = {
                "conversationId": "historical-corruption",
                "workspacePaths": [str(temporary)],
                "artifactDirectoryPath": str(temporary),
                "transcriptPath": str(transcript),
                "fullyIdle": True,
            }

            stop = run_hook(
                "stop",
                json.dumps(payload),
                environment,
                platform="antigravity",
            )

            self.assertEqual(json.loads(stop.stdout), {"decision": "stop"})

    def test_malformed_record_after_current_prompt_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            transcript = temporary / "transcript.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "source": "USER_EXPLICIT",
                        "type": "USER_INPUT",
                        "status": "DONE",
                        "content": "Explain a simple concept",
                    }
                )
                + '\n{"broken"\n',
                encoding="utf-8",
            )
            environment = {**os.environ, "EVIDENCE_HARNESS_DATA": str(temporary / "data")}
            payload = {
                "conversationId": "current-corruption",
                "workspacePaths": [str(temporary)],
                "artifactDirectoryPath": str(temporary),
                "transcriptPath": str(transcript),
                "fullyIdle": True,
            }

            stop = run_hook(
                "stop",
                json.dumps(payload),
                environment,
                platform="antigravity",
            )
            output = json.loads(stop.stdout)

            self.assertEqual(output["decision"], "continue")
            self.assertIn("transcript", output["reason"].casefold())


if __name__ == "__main__":
    unittest.main()
