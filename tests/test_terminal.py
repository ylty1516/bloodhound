import unittest
from prospect.terminal import render, width, fit

class TerminalTests(unittest.TestCase):
    def test_wide_names_and_control_text_fit_columns(self):
        state = {"candidates": [{"name": "测试项目" * 80 + "\x1b[2J", "classification": "unknown", "assessment": {"status": "unknown"}}]}
        for size in (40, 80, 120):
            text = render(state, size)
            self.assertNotIn("\x1b", text)
            self.assertTrue(all(width(line) <= size for line in text.splitlines()))
    def test_empty_state(self):
        self.assertIn("暂无线索", render({}))
    def test_noninteractive_dashboard_has_no_ansi(self):
        self.assertNotIn("\x1b", render({"usage": {"background_model_calls": 0}}))

if __name__ == "__main__": unittest.main()
