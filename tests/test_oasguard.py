"""离线单元测试：阴阳师优先（OAS 一要用模拟器，MT 立刻让出）。

不碰 adb、不碰模拟器：用假的 dev 提供 focus_pkg()，其余全部是纯逻辑。
运行：python -X utf8 -m pytest -q tests/test_oasguard.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from mtbot import oasguard  # noqa: E402


class _Dev:
    """最小设备替身：只实现 focus_pkg()。"""

    pkg = "com.wjmtjq.ma.android"

    def __init__(self, *seq):
        self.seq = list(seq)
        self.calls = 0

    def focus_pkg(self) -> str:
        self.calls += 1
        if not self.seq:
            return self.pkg
        if len(self.seq) == 1:
            return self.seq[0]
        return self.seq.pop(0)


class IsOasPkgTests(unittest.TestCase):
    def test_matches_known_oas_packages(self):
        self.assertTrue(oasguard.is_oas_pkg("com.netease.onmyoji.wyzymnqsd_cps"))
        self.assertTrue(oasguard.is_oas_pkg("com.netease.onmyoji"))
        # dumpsys 有时带 activity 后缀
        self.assertTrue(oasguard.is_oas_pkg(
            "com.netease.onmyoji.wyzymnqsd_cps/com.netease.onmyoji.Client"))

    def test_does_not_match_game_or_empty(self):
        self.assertFalse(oasguard.is_oas_pkg("com.wjmtjq.ma.android"))
        self.assertFalse(oasguard.is_oas_pkg(""))
        self.assertFalse(oasguard.is_oas_pkg(None))
        # 「onmyoji」只是前缀近似，不能把别的阴阳师工具算进来
        self.assertFalse(oasguard.is_oas_pkg("com.netease.onmyojix"))


class ForeignTests(unittest.TestCase):
    def test_oas_foreground(self):
        dev = _Dev("com.netease.onmyoji.wyzymnqsd_cps")
        self.assertEqual(oasguard.oas_foreground(dev),
                         "com.netease.onmyoji.wyzymnqsd_cps")
        dev = _Dev("com.wjmtjq.ma.android")
        self.assertEqual(oasguard.oas_foreground(dev), "")

    def test_unreadable_focus_is_not_busy(self):
        class Boom:
            pkg = "com.wjmtjq.ma.android"

            def focus_pkg(self):
                raise OSError("adb 掉了")

        self.assertEqual(oasguard.foreign_pkg(Boom()), "")
        self.assertEqual(oasguard.oas_foreground(Boom()), "")


class WaitFreeTests(unittest.TestCase):
    def test_returns_true_when_oas_leaves(self):
        dev = _Dev("com.netease.onmyoji.wyzymnqsd_cps",
                   "com.netease.onmyoji.wyzymnqsd_cps",
                   "com.wjmtjq.ma.android")
        ok = oasguard.wait_free(dev, minutes=1, poll=0.01)
        self.assertTrue(ok)
        self.assertGreaterEqual(dev.calls, 3)

    def test_returns_false_without_waiting_when_oas_keeps_it(self):
        dev = _Dev("com.netease.onmyoji.wyzymnqsd_cps")
        ok = oasguard.wait_free(dev, minutes=0, poll=0.01)
        self.assertFalse(ok)
        self.assertEqual(dev.calls, 1)      # 只看一眼，不空转


class GuardTests(unittest.TestCase):
    def test_yields_when_oas_comes_to_front(self):
        dev = _Dev("com.wjmtjq.ma.android", "com.netease.onmyoji.wyzymnqsd_cps")
        g = oasguard.OasGuard(dev)
        self.assertEqual(g.check_once(), "")            # 先在本游戏里
        self.assertFalse(g.yielding)
        g.raise_if_yielded()                            # 不该抛
        self.assertEqual(g.check_once(), "com.netease.onmyoji.wyzymnqsd_cps")
        self.assertTrue(g.yielding)
        with self.assertRaises(oasguard.OasYield):
            g.raise_if_yielded()

    def test_thread_watchdog_sets_flag(self):
        dev = _Dev("com.wjmtjq.ma.android", "com.netease.onmyoji.wyzymnqsd_cps")
        with oasguard.OasGuard(dev, poll=0.01) as g:
            for _ in range(200):
                if g.yielding:
                    break
                import time
                time.sleep(0.01)
        self.assertTrue(g.yielding)


class UiGuardTests(unittest.TestCase):
    """UI.press/wait/screen 是一切的必经之路，被抢时必须从这里抛出来。"""

    @classmethod
    def setUpClass(cls):
        from mtbot.config import load
        cls.cfg = load(None)

    def _ui(self):
        from mtbot.ui import UI
        ui = UI(_Dev("com.wjmtjq.ma.android"), self.cfg)
        ui.click_verify = False     # 别去写点击日志
        return ui

    def test_press_and_wait_raise_when_yielded(self):
        ui = self._ui()
        g = oasguard.OasGuard(_Dev("com.netease.onmyoji.wyzymnqsd_cps"))
        ui.guard = g
        g.check_once()
        self.assertTrue(g.yielding)
        with self.assertRaises(oasguard.OasYield):
            ui.press((360, 640))
        with self.assertRaises(oasguard.OasYield):
            ui.wait(1.0)

    def test_normal_press_is_not_affected(self):
        ui = self._ui()
        ui.guard = oasguard.OasGuard(_Dev("com.wjmtjq.ma.android"))
        self.assertIsNone(ui._check_guard())     # 没被抢就不抛


class SchedulerYieldTests(unittest.TestCase):
    def test_oas_yield_becomes_abort_not_crash(self):
        from mtbot.config import load
        from mtbot.scheduler import Scheduler
        from mtbot.ui import UI

        cfg = load(None)
        ui = UI(_Dev("com.netease.onmyoji.wyzymnqsd_cps"), cfg)
        ui.click_verify = False
        sched = Scheduler(cfg, ui)

        class _Task:
            name = "demo"

            def run(self, ctx):
                raise oasguard.OasYield("阴阳师占用模拟器（com.netease.onmyoji）")

        res = sched._run_once(_Task(), "demo")
        self.assertFalse(res.ok)
        self.assertIn("让位给阴阳师", res.message)
        self.assertIn("运行已中止", res.message)
        self.assertTrue(sched.yielded)


class StopOasTests(unittest.TestCase):
    """2026-11-08 用户改规矩：「完成这个游戏所需要的全部高效运行脚本，停掉阴阳师」。

    于是多了一条 kill 路线：见到阴阳师不再干等，直接 am force-stop 掉再干活。
    用户 2026-11-07 的「让位」仍然是默认行为（kill 默认 False）。
    """

    def setUp(self):
        self._sleep = oasguard.time.sleep
        oasguard.time.sleep = lambda *_a, **_k: None      # 别真等 1.5 秒

    def tearDown(self):
        oasguard.time.sleep = self._sleep

    class _Dev2(_Dev):
        def __init__(self, *seq):
            super().__init__(*seq)
            self.shells = []

        def shell(self, cmd, timeout=30):
            self.shells.append(cmd)
            return ""

    def test_stop_oas_force_stops_both_packages(self):
        # stop_oas 只在按完之后读一次前台：那时应该已经是本游戏了
        dev = self._Dev2("com.wjmtjq.ma.android")
        self.assertTrue(oasguard.stop_oas(dev))
        self.assertTrue(any("force-stop com.netease.onmyoji.wyzymnqsd_cps" in c
                            for c in dev.shells))
        self.assertTrue(any("force-stop com.netease.onmyoji" in c
                            for c in dev.shells))
        self.assertEqual(len(dev.shells), 2)

    def test_stop_oas_reports_failure_when_still_in_front(self):
        dev = self._Dev2("com.netease.onmyoji.wyzymnqsd_cps")
        self.assertFalse(oasguard.stop_oas(dev))

    def test_wait_free_kill_mode_stops_instead_of_waiting(self):
        dev = self._Dev2("com.netease.onmyoji.wyzymnqsd_cps",
                         "com.wjmtjq.ma.android")
        ok = oasguard.wait_free(dev, minutes=0, poll=0.01, kill=True)
        self.assertTrue(ok)
        self.assertTrue(dev.shells)

    def test_guard_kill_mode_does_not_yield(self):
        dev = self._Dev2("com.netease.onmyoji.wyzymnqsd_cps",
                         "com.wjmtjq.ma.android")
        g = oasguard.OasGuard(dev, kill=True)
        self.assertEqual(g.check_once(), "")
        self.assertFalse(g.yielding)
        self.assertEqual(g.kills, 1)
        g.raise_if_yielded()                              # 不该抛


class SchedulerClearOasTests(unittest.TestCase):
    """--oas-stop：调度器见到阴阳师不再整轮中止，而是按掉它继续跑。

    2026-11-08 20:22 实测：阴阳师被外部反复拉起，按旧「让位」逻辑 36 个任务
    只跑完 3 个就中止，永远跑不完。
    """

    def setUp(self):
        self._sleep = oasguard.time.sleep
        oasguard.time.sleep = lambda *_a, **_k: None

    def tearDown(self):
        oasguard.time.sleep = self._sleep

    class _Dev3(StopOasTests._Dev2):
        launched = 0

        def launch(self):
            type(self).launched += 1

    class _Ui:
        def __init__(self, dev, oas_stop=True):
            self.dev = dev
            self.oas_stop = oas_stop
            self.waits = []
            self.actions = 0
            self.deadline = None

        def wait(self, sec=1.0, **_kw):
            self.waits.append(sec)

        def foreign_app(self):
            return ""

    def _sched(self, ui):
        from mtbot.config import load
        from mtbot.scheduler import Scheduler
        return Scheduler(load(None), ui)

    def test_off_by_default(self):
        ui = self._Ui(self._Dev3("com.wjmtjq.ma.android"), oas_stop=False)
        self.assertFalse(self._sched(ui)._clear_oas("com.netease.onmyoji"))
        self.assertEqual(ui.dev.shells, [])

    def test_stops_oas_and_relaunches_game(self):
        dev = self._Dev3("com.wjmtjq.ma.android")
        ui = self._Ui(dev)
        self.assertTrue(self._sched(ui)._clear_oas(
            "com.netease.onmyoji.wyzymnqsd_cps"))
        self.assertTrue(any("force-stop" in c for c in dev.shells))
        self.assertEqual(dev.launched, 1)

    def test_ignores_other_apps(self):
        dev = self._Dev3("com.wjmtjq.ma.android")
        ui = self._Ui(dev)
        self.assertFalse(self._sched(ui)._clear_oas("com.tencent.mm"))
        self.assertEqual(dev.shells, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
