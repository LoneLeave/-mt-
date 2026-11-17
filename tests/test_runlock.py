# -*- coding: utf-8 -*-
"""runlock（带心跳的单实例锁）回归测试。

覆盖 2026-11-15 的事故：进程僵死后锁被永久占住，之后每次启动都 exit 4。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from mtbot import runlock  # noqa: E402


class _TempLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = Path(self.tmp.name) / ".mtbot.run.lock"
        self._patch = mock.patch.object(runlock, "LOCK_FILE", self.lock)
        self._patch.start()
        runlock._owned = False

    def tearDown(self):
        runlock._owned = False
        self._patch.stop()
        self.tmp.cleanup()

    def _spawn_sleeper(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        time.sleep(0.4)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        return p

    def _write_json(self, pid, hb):
        self.lock.write_text(json.dumps({"pid": pid, "start": hb, "hb": hb}),
                             encoding="utf-8")


class AcquireTests(_TempLock):
    def test_no_lock_acquires_and_writes_json(self):
        ok, pid, note = runlock.acquire()
        self.assertTrue(ok)
        self.assertEqual(note, "")
        data = json.loads(self.lock.read_text(encoding="utf-8"))
        self.assertEqual(data["pid"], os.getpid())
        self.assertIn("hb", data)

    def test_live_fresh_lock_refused(self):
        other = self._spawn_sleeper()
        self._write_json(other.pid, time.time())
        ok, pid, note = runlock.acquire()
        self.assertFalse(ok)
        self.assertEqual(pid, other.pid)
        self.assertIn("正在跑", note)

    def test_stale_heartbeat_takes_over_and_kills(self):
        """核心回归：心跳过期 → 判僵死 → 杀旧进程 → 接管锁。"""
        other = self._spawn_sleeper()
        self._write_json(other.pid, time.time() - 3600)
        ok, pid, note = runlock.acquire(stale_seconds=600)
        self.assertTrue(ok)
        self.assertIn("僵死", note)
        try:
            other.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.fail("僵死进程没被杀掉")
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["pid"],
                         os.getpid())

    def test_dead_pid_takes_over(self):
        p = self._spawn_sleeper()
        p.kill()
        p.wait(timeout=5)
        self._write_json(p.pid, time.time())
        ok, _, _ = runlock.acquire()
        self.assertTrue(ok)

    def test_legacy_plain_pid_is_respected_when_alive(self):
        """老版本写的纯 PID 没有心跳，不能因为 mtime 旧就误杀。"""
        other = self._spawn_sleeper()
        self.lock.write_text(str(other.pid), encoding="utf-8")
        old = time.time() - 7200
        os.utime(self.lock, (old, old))
        ok, pid, note = runlock.acquire()
        self.assertFalse(ok)
        self.assertEqual(pid, other.pid)
        self.assertIn("旧版锁", note)

    def test_release_only_removes_own_lock(self):
        other = self._spawn_sleeper()
        self._write_json(other.pid, time.time())
        runlock._owned = True
        runlock.release()
        self.assertTrue(self.lock.exists(), "不该删别人的锁")
        self._write_json(os.getpid(), time.time())
        runlock._owned = True
        runlock.release()
        self.assertFalse(self.lock.exists())


class TouchTests(_TempLock):
    def test_touch_updates_heartbeat(self):
        ok, _, _ = runlock.acquire()
        self.assertTrue(ok)
        self._write_json(os.getpid(), time.time() - 900)
        runlock.touch(force=True)
        hb = json.loads(self.lock.read_text(encoding="utf-8"))["hb"]
        self.assertGreater(hb, time.time() - 30)

    def test_touch_is_noop_when_lock_not_owned(self):
        runlock._owned = False
        runlock.touch(force=True)
        self.assertFalse(self.lock.exists())

    def test_touch_is_throttled(self):
        runlock.acquire()
        runlock._last_touch = time.time() - 900
        runlock._write(os.getpid(), 1.0)
        runlock.touch()                       # 未到间隔也允许补一次（因为 last 很旧）
        hb = json.loads(self.lock.read_text(encoding="utf-8"))["hb"]
        self.assertGreater(hb, 1000.0)
        before = self.lock.read_text(encoding="utf-8")
        runlock.touch()                       # 刚写过，应被节流
        self.assertEqual(before, self.lock.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
