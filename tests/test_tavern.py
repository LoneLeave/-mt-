"""英雄酒馆任务的静态约束测试（不连设备）。"""
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class TavernTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.SRC = (HERE.parent / "mtbot" / "tasks" / "tavern.py").read_text(encoding="utf-8")

    def test_registered_and_enabled(self):
        from mtbot import config, tasks

        self.assertIn("tavern", tasks.names())
        self.assertTrue(config.load().task("tavern").enabled)

    def test_only_presses_within_daily_quota(self):
        self.assertIn("m = self._read(im, left_box)", self.SRC)
        self.assertIn("if not m:", self.SRC)
        self.assertIn("used, limit = int(m.group(1)), int(m.group(2))", self.SRC)
        self.assertIn("avail = max(0, limit - used)", self.SRC)
        self.assertIn("for i in range(min(avail, 4)):", self.SRC)

    def test_buy_attempts_is_attempt_kind_and_evidence_gated(self):
        # 买次数属于 attempt 类（用户规则允许），且必须：弹窗读到金额 + may_spend + 次数增加
        self.assertIn('kind="attempt"', self.SRC)
        self.assertIn("cost = self._dialog_cost(im)", self.SRC)
        self.assertIn("if cost is None:", self.SRC)
        self.assertIn("may_spend(ctx, ", self.SRC)
        self.assertIn("after_left is not None and after_left > 0", self.SRC)
        # 必须从主城读钻石做前后对比
        self.assertIn('d0 = self.diamonds_stable(ui, "tavern_d0")', self.SRC)


if __name__ == "__main__":
    unittest.main()