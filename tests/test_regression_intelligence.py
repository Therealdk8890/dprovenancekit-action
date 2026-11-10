from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pr_comment  # noqa: E402
import regression_intelligence  # noqa: E402
import run_gate  # noqa: E402


def sample_report(**overrides):
    value = {
        "passed": False,
        "regression_level": "high",
        "max_regression_level": "none",
        "allow_divergent_steps": False,
        "fingerprint_match": False,
        "golden_fingerprint": "a" * 40,
        "candidate_fingerprint": "b" * 40,
        "steps_by_change": {
            "removed": ["verify"],
            "added": ["debug"],
            "reordered": ["authorize"],
            "ambiguous": ["query"],
            "semanticMatch": ["normalize"],
        },
        "reasoning": "Critical reasoning steps removed: verify",
    }
    value.update(overrides)
    return value


class TestRegressionIntelligence(unittest.TestCase):
    def test_builds_stable_reason_codes_from_engine_output(self):
        result = regression_intelligence.build_intelligence(sample_report())
        self.assertEqual(result["schema_version"], "dpk.regression-intelligence.v1")
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["severity"], "high")
        self.assertEqual(result["counts"]["total"], 5)
        self.assertEqual(result["counts"]["divergence"], 4)
        self.assertEqual(result["counts"]["informational"], 1)
        self.assertEqual(
            [item["reason_code"] for item in result["findings"]],
            [
                "STEP_REMOVED",
                "STEP_ADDED",
                "STEP_REORDERED",
                "AMBIGUOUS_ALIGNMENT",
                "SEMANTIC_EQUIVALENCE_ACCEPTED",
            ],
        )
        self.assertEqual(result["findings"][0]["step_identifier"], "verify")

    def test_finding_ids_and_order_are_independent_of_mapping_order(self):
        first = sample_report()
        second = sample_report(
            steps_by_change={
                "semanticMatch": ["normalize"],
                "ambiguous": ["query"],
                "reordered": ["authorize"],
                "added": ["debug"],
                "removed": ["verify"],
            }
        )
        self.assertEqual(
            regression_intelligence.build_intelligence(first),
            regression_intelligence.build_intelligence(second),
        )

    def test_duplicate_steps_are_preserved_with_distinct_stable_ids(self):
        result = regression_intelligence.build_intelligence(
            sample_report(steps_by_change={"removed": ["verify", "verify"]})
        )
        self.assertEqual(result["counts"]["divergence"], 2)
        self.assertNotEqual(
            result["findings"][0]["finding_id"],
            result["findings"][1]["finding_id"],
        )

    def test_unknown_engine_change_is_not_silently_dropped(self):
        result = regression_intelligence.build_intelligence(
            sample_report(steps_by_change={"futureChange": ["new-step"]})
        )
        self.assertTrue(result["review_required"])
        self.assertEqual(result["findings"][0]["reason_code"], "UNCLASSIFIED_CHANGE")
        self.assertEqual(result["counts"]["divergence"], 1)

    def test_malformed_engine_report_fails_closed(self):
        malformed = [
            {"passed": "false"},
            {"steps_by_change": "verify"},
            {"steps_by_change": None},
            {"steps_by_change": []},
            {"steps_by_change": {"removed": "verify"}},
            {"regression_level": "unknown"},
        ]
        for override in malformed:
            with self.subTest(override=override), self.assertRaises(ValueError):
                regression_intelligence.build_intelligence(sample_report(**override))
        missing = sample_report()
        del missing["steps_by_change"]
        with self.assertRaises(ValueError):
            regression_intelligence.build_intelligence(missing)

    def test_summary_escapes_trace_derived_markdown_cells(self):
        hostile = "<img src=x onerror=alert(1)> | `<script>`\nforged"
        result = regression_intelligence.build_intelligence(
            sample_report(steps_by_change={"removed": [hostile]})
        )
        summary = regression_intelligence.render_summary(result)
        self.assertIn("&lt;img", summary)
        self.assertIn("&#124;", summary)
        self.assertIn("&#96;", summary)
        self.assertNotIn("<script>", summary)
        self.assertNotIn("\nforged", summary)

    def test_pr_comment_escapes_trace_derived_prose_and_table_cells(self):
        intelligence = regression_intelligence.build_intelligence(sample_report(
            steps_by_change={"removed": ["<svg onload=alert(1)> | `x`"]}
        ))
        body = pr_comment.render_comment(sample_report(
            regression_intelligence=intelligence,
            reasoning="look <img src=x> `*not formatting*`\nforged",
            viewer_url="https://example.test/)(<script>",
        ))
        self.assertIn("&lt;svg", body)
        self.assertIn("&lt;img", body)
        self.assertIn("&#96;", body)
        self.assertNotIn("<script>", body)
        self.assertNotIn("\nforged", body)
        self.assertNotIn("](https://example.test", body)

    def test_action_outputs_include_versioned_intelligence(self):
        result = regression_intelligence.build_intelligence(sample_report())
        gate_report = sample_report(regression_intelligence=result)
        pairs = dict(run_gate.render_outputs(gate_report))
        self.assertEqual(pairs["finding-count"], "4")
        self.assertEqual(
            json.loads(pairs["findings-json"])["schema_version"],
            "dpk.regression-intelligence.v1",
        )

    def test_output_delimiter_cannot_be_forged_by_trace_content(self):
        payload = "first line\n__DPROV_OUTPUT_EOF__\nforged<<value"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "github_output"
            run_gate.write_outputs([("findings-json", payload)], str(path))
            written = path.read_text(encoding="utf-8")
        delimiter = written.split("<<", 1)[1].split("\n", 1)[0]
        self.assertNotEqual(delimiter, "__DPROV_OUTPUT_EOF__")
        self.assertNotIn(delimiter, payload)
        self.assertIn(payload, written)

    def test_pr_comment_surfaces_reason_codes_and_counts(self):
        intelligence = regression_intelligence.build_intelligence(sample_report())
        body = pr_comment.render_comment(
            sample_report(regression_intelligence=intelligence)
        )
        self.assertIn("Regression Intelligence v1", body)
        self.assertIn("STEP_REMOVED", body)
        self.assertIn("verify", body)
        self.assertIn("Divergences:** 4", body)


if __name__ == "__main__":
    unittest.main()
