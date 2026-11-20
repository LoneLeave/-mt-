# -*- coding: utf-8 -*-
"""静态检查：仓库里不许有「引用了不存在的名字」（NameError 隐患）。

2026-11-20 第 68 轮实机教训：`mtbot/tasks/tianshen.py` 里 `_swap()` 引用了一个
不存在的 `txt`，结果整个天神任务在真机上 FAIL（`异常: name 'txt' is not defined`）。
这类错误用 pyflakes 一条命令就能在离线阶段全部抓出来（全库当时只有这一处），
所以固化成测试：mtbot/ 和 tests/ 里 undefined name 必须为 0。
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _pyflakes_undefined(paths: list[str]) -> list[str]:
    try:
        p = subprocess.run([sys.executable, "-m", "pyflakes", *paths],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=180)
    except (OSError, subprocess.SubprocessError):
        raise unittest.SkipTest("没有 pyflakes，跳过静态检查")
    out = (p.stdout or "") + (p.stderr or "")
    if "No module named pyflakes" in out:
        raise unittest.SkipTest("没有 pyflakes，跳过静态检查")
    return [ln for ln in out.splitlines() if "undefined name" in ln]


class UndefinedNameTests(unittest.TestCase):
    def test_mtbot_has_no_undefined_names(self):
        bad = _pyflakes_undefined(["mtbot"])
        self.assertEqual(bad, [], "mtbot 里有引用了不存在的名字（真机会 NameError）：\n"
                                  + "\n".join(bad))

    def test_tests_have_no_undefined_names(self):
        bad = _pyflakes_undefined(["tests"])
        self.assertEqual(bad, [], "tests 里有引用了不存在的名字：\n" + "\n".join(bad))
