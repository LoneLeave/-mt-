"""日志格式回归：OAS 风格 + 来源定位。"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from mtbot import log  # noqa: E402

PATTERN = re.compile(r"^INFO\s+\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} │ \[.*\.py:\d+\] 测试消息$")


class LogFormatTests(unittest.TestCase):
    def test_format_and_source(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log.info("测试消息")
        line = buf.getvalue().strip()
        self.assertRegex(line, PATTERN)

    def test_ui_tags(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log.goto("tower")
            log.ui("result_tree")
            log.arrived("main", 3.94)
        out = buf.getvalue()
        self.assertIn("<<< UI GOTO PAGE_TOWER >>>", out)
        self.assertIn("[UI] result_tree", out)
        self.assertIn("[3.9s] Page arrived page_main", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
