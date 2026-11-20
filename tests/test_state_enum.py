# -*- coding: utf-8 -*-
"""静态检查：源码里 `State.XXX` 引用的成员必须真的存在。

2026-11-20 08:13 事故：`mtbot/pages.py::trial_save` 里写了 `State.RESULT_MAIN`、
`State.RESULT_TRIAL`、`State.RESULT_GUILD` 三个**不存在的枚举**，只有点击走到那一行
才抛 AttributeError —— 真机直接把 guild_trial 记成 FAIL。pyflakes 查不出属性名错，
所以用 AST 把所有 `State.X` 属性访问与枚举成员对一遍（注释里的字样不算）。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "mtbot"


def _enum_members() -> set:
    import sys

    sys.path.insert(0, str(ROOT))
    from mtbot.vision import State

    return {s.name for s in State}


class StateEnumReferenceTests(unittest.TestCase):
    def test_all_state_members_exist(self):
        names = _enum_members()
        bad = []
        for path in sorted(SRC.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:      # pragma: no cover
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "State"
                        and node.attr not in names):
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.attr}")
        self.assertEqual(bad, [], "引用了不存在的 State 成员：\n" + "\n".join(bad[:20]))




class ModuleAttributeReferenceTests(unittest.TestCase):
    """`L.XXX` / `vision.XXX` / `textocr.XXX` 引用的成员也必须真的存在。

    和 State 那条一个道理：写错的常量名只在使用到的那一刻才炸，
    而这类代码路径常常一天只走一次（比如某档活动开启时）。
    """

    def _bad_refs(self, mod_name: str, module) -> list:
        bad = []
        for path in sorted(SRC.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:      # pragma: no cover
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == mod_name
                        and not hasattr(module, node.attr)):
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno}:{mod_name}.{node.attr}")
        return bad

    def test_layout_constants_exist(self):
        import sys

        sys.path.insert(0, str(ROOT))
        from mtbot import layout

        bad = self._bad_refs("L", layout)
        self.assertEqual(bad, [], "引用了不存在的 layout 常量：\n" + "\n".join(bad[:20]))

    def test_vision_and_textocr_members_exist(self):
        import sys

        sys.path.insert(0, str(ROOT))
        from mtbot import textocr, vision

        bad = self._bad_refs("vision", vision) + self._bad_refs("textocr", textocr)
        self.assertEqual(bad, [], "引用了不存在的 vision/textocr 成员：\n" + "\n".join(bad[:20]))
if __name__ == "__main__":
    unittest.main()
