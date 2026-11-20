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
        # 2026-11-20：卡片上「今日可请：A/2」的 A 就是**还能请几次**（真帧确认），
        # `_read` 改成返回 (A, B) 元组，请客次数直接取 A。
        self.assertIn("v0 = self._read(im, left_box)", self.SRC)
        self.assertIn("if not v0:", self.SRC)
        self.assertIn("used, limit = v0[0], v0[1]", self.SRC)
        self.assertIn("avail = max(0, used)", self.SRC)
        self.assertIn("for k in range(min(avail, 4)):", self.SRC)

    def test_buy_attempts_is_attempt_kind_and_evidence_gated(self):
        # 买次数属于 attempt 类（用户规则允许），且必须：弹窗读到金额 + may_spend + 次数增加
        self.assertIn('kind="attempt"', self.SRC)
        self.assertIn("cost = self._dialog_cost(im)", self.SRC)
        self.assertIn("if cost is None:", self.SRC)
        self.assertIn("may_spend(ctx, ", self.SRC)
        # 2026-11-20：买次数走顶部「+」，成功判据是「请客次数真的变多」
        self.assertIn("if after is None or (pool is not None and after <= pool):", self.SRC)
        self.assertIn("TAVERN_POOL_PLUS", self.SRC)
        # 必须从主城读钻石做前后对比
        self.assertIn('d0 = self.diamonds_stable(ui, "tavern_d0")', self.SRC)


if __name__ == "__main__":
    unittest.main()