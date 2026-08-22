from __future__ import annotations

import sys
import unittest
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from evidence_core import (
    NO_VERIFIABLE_EXTERNAL_QUOTES,
    QUOTE_RE,
    classify_profile,
    evaluate,
    has_external_citation_context,
    is_user_example_quote,
    is_verifiable_external_quote,
)
from hook_adapter import atomic_write_json, integrity_decision, load_json_object
from scholar_bridge import find_project_root, harness_profile, project_snapshot


def event(tool="fetch", text="", ok=True, event_id="T1"):
    return {"id": event_id, "tool": tool, "ok": ok, "scope": "inspected" if tool in {"fetch", "read", "search"} else "executed", "observed_text": text, "observed_urls": [], "observed_dois": [], "artifacts": []}


class HarnessTests(unittest.TestCase):
    def test_corrupt_prompt_state_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt.json"
            path.write_bytes(b"")
            self.assertEqual(load_json_object(path, {"profile": "routine"}), {"profile": "routine"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"profile": "routine"})

    def test_atomic_json_write_never_leaves_partial_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt.json"
            atomic_write_json(path, {"prompt": "verified", "profile": "academic"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["profile"], "academic")

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

    def test_slash_tokens_in_explanatory_prose_are_not_artifacts(self):
        answer = "I wrote that prose token /보류 and /hash is not an artifact."
        report = evaluate(answer, {"events": []}, "routine")
        codes = {finding["code"] for finding in report["findings"]}
        self.assertNotIn("P007_MISSING_ARTIFACT", codes)

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

    def test_matching_inspected_url_with_json_escape_does_not_block(self):
        source = r'{"url":"https://arxiv.org/abs/2606.22563"}'
        report = evaluate(
            "출처: https://arxiv.org/abs/2606.22563",
            {"events": [event(tool="fetch", text=source)]},
            "academic",
        )
        self.assertNotIn("P001_UNOBSERVED_URL", {x["code"] for x in report["findings"]})

    def test_quoted_paper_title_is_explanatory_not_source_quote(self):
        report = evaluate(
            '논문 제목은 "A DDSP Framework for Adaptive Room Equalization"이다.',
            {"events": [event(tool="read", text="unrelated tool output")]},
            "research",
        )
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", {x["code"] for x in report["findings"]})

    def test_unsupported_attributed_quote_still_blocks(self):
        report = evaluate(
            '저자는 "the measured effect was 12.3 percent"라고 주장했다.',
            {"events": [event(tool="read", text="other text")]},
            "research",
        )
        self.assertIn("P003_UNSUPPORTED_QUOTE", {x["code"] for x in report["findings"]})


class ArtifactClaimTests(unittest.TestCase):
    """P007 must judge path-shaped tokens only, never prose."""

    def run_eval(self, response, ledger_events):
        return evaluate(response, {"events": ledger_events, "claims": []}, "routine")

    def test_korean_prose_slash_does_not_trigger_p007(self):
        report = self.run_eval("보고서 원고를 저장/정리했습니다.", [event(tool="command", text="ok")])
        self.assertNotIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})

    def test_backtick_descriptive_sentence_does_not_trigger_p007(self):
        report = self.run_eval(
            "요약하자면, `이 지표는 A/B 테스트 범위입니다`라고 작성했습니다.",
            [event(tool="command", text="ok")],
        )
        self.assertNotIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})

    def test_url_mention_with_action_word_does_not_trigger_p007(self):
        ledger = [event(tool="fetch", text="opened https://example.org/reports/2026.html")]
        report = self.run_eval("자료를 https://example.org/reports/2026.html 에서 다운로드했습니다.", ledger)
        self.assertNotIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})

    def test_missing_drive_path_claim_still_blocks(self):
        report = self.run_eval(
            "분석 결과를 C:\\Users\\hh\\missing_dir\\result.csv 파일로 저장했습니다.",
            [event(tool="command", text="ok")],
        )
        self.assertIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})

    def test_missing_unc_path_claim_still_blocks(self):
        report = self.run_eval(
            "\\\\fileserver\\share\\out\\summary.csv 로 저장했습니다.",
            [event(tool="command", text="ok")],
        )
        self.assertIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})

    def test_missing_relative_path_claim_still_blocks(self):
        report = self.run_eval(
            "outputs/summary_table.csv 파일을 생성했습니다.",
            [event(tool="command", text="ok")],
        )
        self.assertIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})

    def test_existing_project_file_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "result.csv"
            target.write_text("x", encoding="utf-8")
            report = self.run_eval(f"분석 결과를 {target} 파일로 저장했습니다.", [event(tool="command", text="ok")])
        self.assertTrue(report["allow"])

    def test_ledger_registered_relative_artifact_is_allowed(self):
        write_event = event(tool="write", text="write ok")
        write_event["scope"] = "written"
        write_event["artifacts"] = ["outputs/summary_table.csv"]
        report = self.run_eval("outputs/summary_table.csv 파일을 생성했습니다.", [write_event])
        self.assertTrue(report["allow"])

    def test_typographic_quotation_slash_text_is_not_artifact_claim(self):
        report = self.run_eval(
            "요약하면 “요율이 a/b/c 구간으로 적용된다”는 해석을 작성했습니다.",
            [event(tool="command", text="ok")],
        )
        self.assertNotIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})

    def test_url_and_path_punctuation_normalize_without_false_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.csv"
            target.write_text("x", encoding="utf-8")
            response = (
                "참고자료(https://example.org/a/b.html)를 다운로드했고\n"
                f"결과는 {target}. 파일로 저장했습니다."
            )
            report = self.run_eval(response, [event(tool="command", text="ok")])
        self.assertTrue(report["allow"])

    def test_existing_folder_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.run_eval(f"중간 결과물을 {tmp} 폴더에 저장했습니다.", [event(tool="command", text="ok")])
        self.assertTrue(report["allow"])

    def test_missing_folder_path_claim_still_blocks(self):
        report = self.run_eval(
            "중간 결과물을 C:\\no\\such\\dir\\results 폴더에 저장했습니다.",
            [event(tool="command", text="ok")],
        )
        self.assertIn("P007_MISSING_ARTIFACT", {x["code"] for x in report["findings"]})


class QuoteClassificationTests(unittest.TestCase):
    """P003 must fire only for quotes with external citation context."""

    def codes(self, response, ledger_events):
        report = evaluate(response, {"events": ledger_events, "claims": []}, "research")
        return report, {x["code"] for x in report["findings"]}

    def test_user_request_example_quote_is_not_external_citation(self):
        _, codes = self.codes('요청문에 "이 문장을 예시로 사용"이라고 적으면 그대로 반영한다.', [])
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_korean_example_request_is_not_external_citation(self):
        _, codes = self.codes('사용자가 "결과를 요약해서 표로 정리해줘"라고 요청한 경우를 처리했습니다.', [])
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_short_quote_in_explanation_is_ignored(self):
        _, codes = self.codes('"짧은 표기"라는 문구는 길이 제한 미달이라 검사 대상이 아니다.', [])
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_prompt_template_example_with_url_is_not_external_citation(self):
        ledger = [event(tool="fetch", text="opened https://example.org/paper")]
        _, codes = self.codes(
            '프롬프트 템플릿 예시: "https://example.org/paper 를 요약해줘" 같은 지시문을 넣었습니다.',
            ledger,
        )
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_markdown_glossary_content_quote_is_not_external_citation(self):
        _, codes = self.codes('용어집에 "evidence-bound 표기는 근거 구속을 뜻한다" 항목을 추가했습니다.', [])
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_scholar_workfile_example_sentence_is_not_external_citation(self):
        ledger = [event(tool="command", text="ok")]
        _, codes = self.codes('AGENTS.md에 "매일 연구 로그를 남긴다" 지침을 작성했습니다.', ledger)
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_unsourced_quote_alone_is_not_external_citation(self):
        _, codes = self.codes('문서에 "이 문장은 표기 예시로만 사용된다"라고 적었다.', [])
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_author_year_external_quote_still_blocks(self):
        _, codes = self.codes('Smith (2020)는 "the effect was significant across regions"라고 주장했다.', [])
        self.assertIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_doi_external_quote_still_blocks(self):
        _, codes = self.codes('보고된 바에 따르면 "the measured gain was 15 percent"(doi:10.1234/abcd5678)이다.', [])
        self.assertIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_paper_url_external_quote_still_blocks(self):
        ledger = [event(tool="fetch", text="opened https://journal.example.org/article1")]
        _, codes = self.codes('"the result was robust"라는 구절이 https://journal.example.org/article1 에 인용되어 있다.', ledger)
        self.assertIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_reference_linked_quote_still_blocks(self):
        _, codes = self.codes('참고문헌 [3]에 따르면 "the estimate was biased upward"라고 지적했다.', [])
        self.assertIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_evidence_field_external_quote_still_blocks(self):
        _, codes = self.codes('evidence 필드에 외부 인용으로 "the pooled effect was positive" 문장을 명시했다.', [])
        self.assertIn("P003_UNSUPPORTED_QUOTE", codes)

    def test_verified_external_quote_is_allowed(self):
        ledger = [event(tool="read", text='Smith (2020) reported "the effect was significant across regions" in the study.')]
        report, codes = self.codes('Smith (2020)는 "the effect was significant across regions"라고 주장했다.', ledger)
        self.assertNotIn("P003_UNSUPPORTED_QUOTE", codes)
        self.assertTrue(report["allow"])

    def test_example_only_response_reports_no_verifiable_external_quotes(self):
        report = evaluate('요청문에 "이 문장을 예시로 사용"이라고 적으면 그대로 반영한다.', {"events": [], "claims": []}, "research")
        self.assertTrue(report["allow"])
        self.assertEqual(report["quote_gate"], NO_VERIFIABLE_EXTERNAL_QUOTES)

    def test_response_without_quotes_has_null_quote_gate(self):
        report = evaluate("검증 없이 평범한 문장만 있다.", {"events": [], "claims": []}, "research")
        self.assertIsNone(report["quote_gate"])

    def test_quote_classifiers_directly(self):
        example = QUOTE_RE.search('요청문에 "이 문장을 예시로 사용"이라고 적으면 그대로 반영한다.')
        self.assertIsNotNone(example)
        self.assertTrue(is_user_example_quote('요청문에 "이 문장을 예시로 사용"이라고 적으면', example.start(), example.end()))
        self.assertFalse(has_external_citation_context('요청문에 "이 문장을 예시로 사용"이라고 적으면', example.start(), example.end()))
        self.assertFalse(is_verifiable_external_quote('요청문에 "이 문장을 예시로 사용"이라고 적으면', example.start(), example.end()))
        external = QUOTE_RE.search('Smith (2020)는 "the effect was significant across regions"라고 주장했다.')
        self.assertIsNotNone(external)
        self.assertTrue(has_external_citation_context('Smith (2020)는 "the effect was significant across regions"라고 주장했다.', external.start(), external.end()))
        self.assertTrue(is_verifiable_external_quote('Smith (2020)는 "the effect was significant across regions"라고 주장했다.', external.start(), external.end()))
        self.assertFalse(is_user_example_quote('Smith (2020)는 "the effect was significant across regions"라고 주장했다.', external.start(), external.end()))


class IntegrityDecisionTests(unittest.TestCase):
    """PreToolUse integrity must judge the operation TARGET PATH, never payload content."""

    SCHOLAR_DIR = r"C:\Users\hh\Documents\research_projects\ltrr_study"
    HARNESS_CACHE = r"C:\Users\hh\.agents\plugins\plugins\unified-evidence-harness"

    def test_external_scholar_write_with_harness_vocabulary_in_content_is_allowed(self):
        payload = {
            "file_path": self.SCHOLAR_DIR + r"\status\worker_notes.md",
            "content": "이 노트는 evidence-bound 정책과 unified-evidence-harness 표기, trust/hashes.json 언급을 포함한다.",
        }
        self.assertFalse(integrity_decision("write", payload, json.dumps(payload, ensure_ascii=False), self.SCHOLAR_DIR))

    def test_scholar_agents_md_creation_is_allowed(self):
        payload = {
            "file_path": self.SCHOLAR_DIR + r"\AGENTS.md",
            "content": "# AGENTS\n이 프로젝트는 evidence-bound 원칙을 따른다. START_HERE.md와 WBS.md를 참조.",
        }
        self.assertFalse(integrity_decision("write", payload, json.dumps(payload, ensure_ascii=False), self.SCHOLAR_DIR))

    def test_plain_markdown_glossary_creation_is_allowed(self):
        payload = {
            "file_path": self.SCHOLAR_DIR + r"\glossary.md",
            "content": "# 용어집\n- evidence-bound: 근거 구속 표기\n- hashes: 해시 목록",
        }
        self.assertFalse(integrity_decision("write", payload, json.dumps(payload, ensure_ascii=False), self.SCHOLAR_DIR))

    def test_install_registration_files_still_block(self):
        for relative in (r"\hooks\hooks.json", r"\.codex-plugin\plugin.json"):
            payload = {"file_path": self.HARNESS_CACHE + relative, "content": "{}"}
            self.assertTrue(integrity_decision("write", payload, json.dumps(payload), self.HARNESS_CACHE), relative)

    def test_external_edit_mentioning_trust_manifest_is_allowed(self):
        payload = {"file_path": self.SCHOLAR_DIR + r"\RESEARCH_LOG.md", "old_string": "a", "new_string": "trust/hashes.json 재생성 언급"}
        self.assertFalse(integrity_decision("edit", payload, json.dumps(payload, ensure_ascii=False), self.SCHOLAR_DIR))

    def test_harness_source_write_still_blocks(self):
        payload = {"file_path": self.HARNESS_CACHE + r"\scripts\hook_adapter.py", "content": "import os"}
        self.assertTrue(integrity_decision("write", payload, json.dumps(payload), self.HARNESS_CACHE))

    def test_relative_harness_source_write_still_blocks_via_cwd(self):
        payload = {"file_path": "core/evidence_core.py", "content": "x = 1"}
        self.assertTrue(integrity_decision("write", payload, json.dumps(payload), r"C:\Users\hh\Documents\Codex\2026-08-18\s\unified-evidence-harness"))

    def test_trust_manifest_write_still_blocks(self):
        payload = {"file_path": self.HARNESS_CACHE + r"\trust\hashes.json", "content": "{}"}
        self.assertTrue(integrity_decision("write", payload, json.dumps(payload), self.HARNESS_CACHE))

    def test_relative_trust_manifest_write_still_blocks(self):
        payload = {"file_path": "trust/hashes.json", "content": "{}"}
        self.assertTrue(integrity_decision("write", payload, json.dumps(payload), self.HARNESS_CACHE))

    def test_bash_mutation_on_harness_path_still_blocks(self):
        command = "set-content -path " + self.HARNESS_CACHE + r"\trust\hashes.json" + " -value x"
        self.assertTrue(integrity_decision("Bash", {"command": command}, command, r"C:\Users\hh"))

    def test_apply_patch_on_harness_source_still_blocks(self):
        patch = "*** Begin Patch\n*** Update File: core/hook_adapter.py\n@@\n-x\n+y\n*** End Patch"
        payload = {"input": patch}
        repo = r"C:\Users\hh\Documents\Codex\2026-08-18\s\unified-evidence-harness"
        self.assertTrue(integrity_decision("apply_patch", payload, patch, repo))

    def test_official_manifest_build_command_is_allowed(self):
        repo = r"C:\Users\hh\Documents\Codex\2026-08-18\s\unified-evidence-harness"
        command = "python " + repo + r"\scripts\build_hashes.py --root C:\tmp\target"
        self.assertFalse(integrity_decision("Bash", {"command": command}, command, repo))

if __name__ == "__main__":
    unittest.main()
