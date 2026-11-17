"""单任务调试取证：每 2–3 秒抓一帧 + 全程日志落到 artifacts/debug/<task>/<ts>/。

用户要求（2026-11-04）：
- 过程留证：frames/ 下按时间编号保存截图；debug.log 单独写结构化日志；
- 不许用 TaskResult.ok 自称成功，最终判定要看帧序列 + debug.log。

实现要点：
- 截图用独立的 adb 进程（exec-out screencap -p），不和 UI 主线程的 screenshot 抢缓存；
- 日志用 stdout tee，不改动 log.py 的既有行为。
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from PIL import Image

from . import vision
from .config import ROOT, Config


class _Tee:
    def __init__(self, *streams):
        self._streams = streams

    def write(self, s):
        for st in self._streams:
            try:
                st.write(s)
            except Exception:  # noqa: BLE001
                pass

    def flush(self):
        for st in self._streams:
            try:
                st.flush()
            except Exception:  # noqa: BLE001
                pass

    def reconfigure(self, **kw):
        for st in self._streams:
            fn = getattr(st, "reconfigure", None)
            if fn:
                try:
                    fn(**kw)
                except Exception:  # noqa: BLE001
                    pass


class DebugRecorder:
    def __init__(self, task: str, cfg: Config, interval: float = 2.5):
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.task = task
        self.interval = max(1.5, float(interval))
        self.dir = ROOT / "artifacts" / "debug" / task / ts
        self.frames_dir = self.dir / "frames"
        self.log_path = self.dir / "debug.log"
        self.index_path = self.dir / "frames.jsonl"
        self.adb = cfg.device.adb
        self.serial = cfg.device.serial
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._n = 0
        self._old_stdout = None
        self._log_fh = None

    # ---------- 生命周期 ----------
    def start(self) -> "DebugRecorder":
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self._log_fh = self.log_path.open("a", encoding="utf-8")
        self._old_stdout = sys.stdout
        sys.stdout = _Tee(self._old_stdout, self._log_fh)
        self._thread = threading.Thread(target=self._loop, name="mtbot-debug", daemon=True)
        self._thread.start()
        self._note(f"取证开始：task={self.task} interval={self.interval}s dir={self.dir}")
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._old_stdout is not None:
            sys.stdout = self._old_stdout
            self._old_stdout = None
        self._note("取证结束")
        if self._log_fh:
            try:
                self._log_fh.close()
            except OSError:
                pass
            self._log_fh = None

    # ---------- 内部 ----------
    def _note(self, msg: str) -> None:
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(f"[debug] {time.strftime('%H:%M:%S')} {msg}\n")
        except OSError:
            pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._capture()
            self._stop.wait(self.interval)

    def _capture(self) -> None:
        try:
            p = subprocess.run(
                [self.adb, "-s", self.serial, "exec-out", "screencap -p"],
                capture_output=True, timeout=25,
            )
            data = p.stdout or b""
            if not data.startswith(b"\x89PNG"):
                return
            self._n += 1
            ts = time.strftime("%H%M%S")
            name = f"f{self._n:04d}_{ts}.png"
            (self.frames_dir / name).write_bytes(data)
            state = "?"
            try:
                # screencap -p 得到的是 RGBA，classify/avg 里 R,G,B 解包会抛
                # ValueError（被下面的 except 吞掉后 state 恒为 "?"），必须先转 RGB。
                state = vision.classify(Image.open(io.BytesIO(data)).convert("RGB")).value
            except Exception:  # noqa: BLE001
                pass
            with self.index_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"n": self._n, "ts": ts, "frame": name,
                                    "state": state}, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001
            self._note(f"抓帧失败：{type(e).__name__}: {e}")
