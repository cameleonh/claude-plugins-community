from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from evidence_core import evaluate
from scholar_bridge import merge_project_evidence


def observed_event(artifact: Path) -> dict[str, object]:
    return {
        "id": "T1",
        "tool": "read",
        "ok": True,
        "scope": "inspected",
        "observed_text": str(artifact),
        "observed_urls": [],
        "observed_dois": [],
        "artifacts": [str(artifact)],
        "requested_inputs": {"file_path": str(artifact)},
    }


def create_project(root: Path, value: int = 7) -> Path:
    (root / "SCHOLAR_PROFILE.json").write_text(
        json.dumps({"profile": "empirical-policy", "contract_id": "scholar2agent-project-v2"}),
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("policy", encoding="utf-8")
    (root / "START_HERE.md").write_text("next", encoding="utf-8")
    analysis = root / "03_analysis"
    analysis.mkdir()
    result = root / "04_results" / "result.json"
    result.parent.mkdir()
    result.write_text(json.dumps({"metrics": {"central": value}}), encoding="utf-8")
    sentence = f"The verified central result is {value} ({result.relative_to(root).as_posix()})."
    (root / "manuscript.md").write_text(sentence, encoding="utf-8")
    registry = {
        "case_id": "bridge-case",
        "profile": "empirical-policy",
        "readiness_status": "evidence-backed draft",
        "citations": [],
        "claims": [
            {
                "id": "C1",
                "manuscript_quote": sentence,
                "artifact": result.relative_to(root).as_posix(),
                "json_pointer": "/metrics/central",
                "value": value,
                "source_ids": [],
            }
        ],
    }
    (analysis / "claims_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    return result


def worker_receipt(worker: str, verdict: str = "supported") -> dict[str, object]:
    return {
        "schema_version": 1,
        "receipt_id": worker,
        "worker_id": worker,
        "role": "reviewer",
        "task_scope": "claim C1",
        "status": "completed",
        "fresh_context": True,
        "input_artifacts": [],
        "inspected_artifacts": [],
        "findings": [
            {
                "claim_id": "C1",
                "verdict": verdict,
                "severity": "must-fix",
                "evidence_event_ids": ["T1"],
                "limitation": "",
            }
        ],
        "uninspected_scope": [],
    }


class ScholarBridgeTests(unittest.TestCase):
    def test_valid_registry_becomes_supported_harness_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_project(root)
            ledger = merge_project_evidence(
                root,
                {"events": [observed_event(result)], "claims": [], "worker_receipts": []},
            )

            self.assertEqual(
                ledger["claims"],
                [{"id": "C1", "verdict": "supported", "support_event_ids": ["T1"]}],
            )
            self.assertTrue(evaluate("The verified result was confirmed.", ledger, "submission")["allow"])

    def test_registry_without_current_event_remains_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_project(root)
            ledger = merge_project_evidence(
                root,
                {"events": [], "claims": [], "worker_receipts": []},
            )

            report = evaluate("The verified result was confirmed.", ledger, "submission")
            self.assertIn("P014_MISSING_CLAIM_SUPPORT", {item["code"] for item in report["findings"]})

    def test_registry_pointer_mismatch_remains_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_project(root)
            claims_path = root / "03_analysis" / "claims_registry.json"
            registry = json.loads(claims_path.read_text(encoding="utf-8"))
            registry["claims"][0]["value"] = 999
            claims_path.write_text(json.dumps(registry), encoding="utf-8")
            ledger = merge_project_evidence(
                root,
                {"events": [observed_event(result)], "claims": [], "worker_receipts": []},
            )

            report = evaluate("The verified result was confirmed.", ledger, "submission")
            self.assertIn("P014_MISSING_CLAIM_SUPPORT", {item["code"] for item in report["findings"]})

    def test_write_event_cannot_support_a_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_project(root)
            unrelated = observed_event(root / "unrelated.json")
            write = {
                **observed_event(result),
                "id": "W1",
                "tool": "write",
                "scope": "written",
            }
            ledger = merge_project_evidence(
                root,
                {"events": [unrelated, write], "claims": [], "worker_receipts": []},
            )

            report = evaluate("The verified result was confirmed.", ledger, "submission")
            self.assertIn("P014_MISSING_CLAIM_SUPPORT", {item["code"] for item in report["findings"]})

    def test_artifact_path_substring_does_not_support_a_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_project(root)
            collision = observed_event(Path(f"{result}.backup"))
            ledger = merge_project_evidence(
                root,
                {"events": [collision], "claims": [], "worker_receipts": []},
            )

            report = evaluate("The verified result was confirmed.", ledger, "submission")
            self.assertIn("P014_MISSING_CLAIM_SUPPORT", {item["code"] for item in report["findings"]})

    @unittest.skipUnless(hasattr(Path, "is_junction"), "junction detection is unavailable")
    def test_registry_under_junction_is_not_adapted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_project(root)
            original = Path.is_junction

            def flagged(path: Path) -> bool:
                return path == root / "03_analysis" or original(path)

            with patch.object(Path, "is_junction", flagged):
                ledger = merge_project_evidence(
                    root,
                    {"events": [observed_event(result)], "claims": [], "worker_receipts": []},
                )

            self.assertEqual(ledger["claims"], [])

    def test_project_worker_receipt_conflict_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_project(root)
            receipts = root / "summaries" / "reviewer_reports"
            receipts.mkdir(parents=True)
            for worker, verdict in (("w1", "supported"), ("w2", "refuted")):
                receipt = worker_receipt(worker, verdict)
                (receipts / f"{worker}.json").write_text(json.dumps(receipt), encoding="utf-8")
            ledger = merge_project_evidence(
                root,
                {"events": [observed_event(result)], "claims": [], "worker_receipts": []},
            )

            report = evaluate("The verified result was confirmed.", ledger, "submission")
            self.assertIn("P023_UNRESOLVED_WORKER_CONFLICT", {item["code"] for item in report["findings"]})

    def test_receipt_overflow_blocks_instead_of_dropping_late_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_project(root)
            receipts = root / "summaries" / "reviewer_reports"
            receipts.mkdir(parents=True)
            for index in range(64):
                worker = f"worker-{index:02d}"
                (receipts / f"{index:02d}.json").write_text(
                    json.dumps(worker_receipt(worker)),
                    encoding="utf-8",
                )
            (receipts / "99-conflict.json").write_text(
                json.dumps(worker_receipt("late-conflict", "refuted")),
                encoding="utf-8",
            )
            ledger = merge_project_evidence(
                root,
                {"events": [observed_event(result)], "claims": [], "worker_receipts": []},
            )

            report = evaluate("The verified result was confirmed.", ledger, "submission")
            self.assertFalse(report["allow"])
            self.assertIn("P020_INVALID_WORKER_RECEIPT", {item["code"] for item in report["findings"]})


if __name__ == "__main__":
    unittest.main()
