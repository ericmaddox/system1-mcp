"""Regression tests for option IDs that collide after whitespace trimming."""

import unittest
from unittest.mock import patch

from system1_mcp.tools import judge_impl


class JudgeOptionIdTests(unittest.TestCase):
    def test_colliding_normalized_ids_are_rejected_before_dispatch(self):
        for duplicate in (" keep ", "\tkeep\n", "\u00a0keep\u00a0"):
            with self.subTest(duplicate=duplicate):
                # Keep a third option so the overwritten mapping would still be
                # valid for the SDK and could silently reach the model.
                options = {"keep": "Keep the original", duplicate: "Replace it", "review": "Ask for review"}
                with patch("system1_mcp.tools.execute_system_one") as execute:
                    execute.return_value = {"error": True, "error_type": "unexpected_dispatch"}
                    result = judge_impl(question="Which action?", options=options)

                self.assertEqual(result.get("error_type"), "validation_error")
                self.assertEqual(result.get("fallback_action"), "escalate")
                execute.assert_not_called()

    def test_distinct_padded_ids_keep_existing_normalization(self):
        with patch("system1_mcp.tools.execute_system_one") as execute:
            execute.return_value = {"error": True, "error_type": "synthetic_response"}
            result = judge_impl(
                question="Which action?",
                options={" keep ": " Keep the original ", " review ": None},
            )

        execute.assert_called_once()
        selection = execute.call_args.kwargs["questions"]["selection"]
        self.assertEqual(selection.criteria, {"keep": "Keep the original", "review": None})
        self.assertEqual(result, execute.return_value)

    def test_distinct_case_sensitive_ids_remain_distinct(self):
        with patch("system1_mcp.tools.execute_system_one") as execute:
            execute.return_value = {"error": True, "error_type": "synthetic_response"}
            judge_impl(question="Which file?", options={"Config": "Uppercase", "config": "Lowercase"})

        execute.assert_called_once()
        selection = execute.call_args.kwargs["questions"]["selection"]
        self.assertEqual(selection.criteria, {"Config": "Uppercase", "config": "Lowercase"})


if __name__ == "__main__":
    unittest.main()
