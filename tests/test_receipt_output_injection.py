from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import receipt_gate


class TestReceiptOutputDelimiter(unittest.TestCase):
    def test_untrusted_multiline_reason_cannot_forge_passed_output(self) -> None:
        payload = (
            "ordinary reason\n"
            "__DPROV_RECEIPT_EOF__\n"
            "passed<<__DPROV_RECEIPT_EOF__\n"
            "true\n"
            "__DPROV_RECEIPT_EOF__"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github_output"
            receipt_gate.write_outputs(
                [("passed", "false"), ("receipt-reason", payload)],
                str(output),
            )
            lines = output.read_text(encoding="utf-8").splitlines()

        # Parse the GitHub multiline-output format exactly as a runner does:
        # a value ends only when a line equals its active delimiter.
        records: list[tuple[str, str]] = []
        index = 0
        while index < len(lines):
            key, delimiter = lines[index].split("<<", 1)
            index += 1
            value_lines = []
            while index < len(lines) and lines[index] != delimiter:
                value_lines.append(lines[index])
                index += 1
            self.assertLess(index, len(lines), f"unterminated output {key}")
            records.append((key, "\n".join(value_lines)))
            index += 1

        passed_values = [value for key, value in records if key == "passed"]
        reason_values = [value for key, value in records if key == "receipt-reason"]
        self.assertEqual(passed_values, ["false"])
        self.assertEqual(reason_values, [payload])
        self.assertEqual(len(passed_values), 1)


if __name__ == "__main__":
    unittest.main()
