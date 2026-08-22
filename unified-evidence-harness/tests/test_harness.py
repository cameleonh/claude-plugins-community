from __future__ import annotations

import sys
import unittest
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from evidence_core import classify_profile, evaluate
from scholar_bridge import find_project_root, harness_profile, project_snapshot


def event(tool="fetch", text="", ok=True, event_id="T1"):
    return {"id": event_id, "tool": tool, "ok": ok, "scope": "inspected" if tool in {"fetch", "read", "search"} else "executed", "observed_text": text, "observed_urls": [], "observed_dois": [], "artifacts": []}


class HarnessTests(unittest.TestCase):
    def test_routine_functional_comparison_does_not_require_research(self):
        self.assertTrue(evaluate("A manages context; B manages workflow.", {"events": [], "claims": []}, "routine")["allow"])

    def test_research_blocks_unobserved_url(self):
        self.assertFalse(evaluate("Source: https://example.org/x", {"events": [], "claims": []}, "research")["allow"])

    def test_research_allows_url_from_successful_output(self):
        ledger = {"events": [event(text="opened https://example.org/x")], "claims": []}
        self.assertTrue(evaluate("Source: https://example.org/x", ledger, "research")["allow"])

    def test_failed_output_is_not_evidence(self):
        ledger = {"events": [event(text="https://example.org/x", ok=False)], "claims": []}
        self.assertFalse(evaluate("Source: https://example.org/x", ledger, "research")["allow"])

    def test_submission_requires_claim_ledger(self):
        ledger = {"events": [event(tool="read", text="verified study")], "claims": []}
        self.assertFalse(evaluate("The verified study was confirmed.", ledger, "submission")["allow"])

    def test_profile_classifier_is_proportional(self):
        self.assertEqual(classify_profile("Compare these functions"), "routine")
        self.assertEqual(classify_profile("Verify this paper citation"), "academic")

    def test_scholar_project_detection_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SCHOLAR_PROFILE.json").write_text(json.dumps({"profile": "empirical-policy", "contract_id": "scholar2agent-project-v2"}), encoding="utf-8")
            (root / "AGENTS.md").write_text("policy", encoding="utf-8")
            (root / "START_HERE.md").write_text("next", encoding="utf-8")
            nested = root / "03_analysis"
            nested.mkdir()
            self.assertEqual(find_project_root(nested), root)
            self.assertEqual(harness_profile(root, "Revise manuscript"), "academic")
            self.assertEqual(harness_profile(root, "Prepare final submission"), "submission")
            self.assertEqual(project_snapshot(root)["scholar_profile"], "empirical-policy")

    def test_submission_blocks_conflicting_worker_receipts(self):
        receipts = []
        for worker, verdict in (("w1", "supported"), ("w2", "refuted")):
            receipts.append({"receipt_id": worker, "worker_id": worker, "role": "reviewer", "task_scope": "claim C1", "status": "completed", "fresh_context": True, "findings": [{"claim_id": "C1", "verdict": verdict, "evidence_event_ids": []}], "uninspected_scope": []})
        ledger = {"events": [event(tool="read", text="verified study")], "claims": [{"id": "C1", "verdict": "supported", "support_event_ids": ["T1"]}], "worker_receipts": receipts}
        report = evaluate("The verified study was confirmed.", ledger, "submission")
        self.assertIn("P023_UNRESOLVED_WORKER_CONFLICT", {x["code"] for x in report["findings"]})


if __name__ == "__main__":
    unittest.main()
