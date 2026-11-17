"""设备层：只管 adb（连接、截图、点击、按键、前后台），不认识游戏内容。"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from PIL import Image

from . import log
from .config import ROOT, Config


class DeviceError(RuntimeError):
    pass


class Device:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.adb_path = cfg.device.adb
        self.serial = cfg.device.serial
        self.pkg = cfg.device.package
        self.activity = cfg.device.activity
        self.tap_ms = cfg.runtime.tap_ms
        self.shot_dir = ROOT / cfg.runtime.screenshot_dir
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        self._shot_n = 0
        self._cache: tuple[float, Image.Image] | None = None
        self._cache_ttl = 0.35

    # ---------- adb 基础 ----------
    def adb(self, *args: str, timeout: int = 25) -> str:
        cmd = [self.adb_path, "-s", self.serial, *args]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="ignore", timeout=timeout)
        except FileNotFoundError as e:
            raise DeviceError(f"adb 不存在: {self.adb_path}") from e
        except subprocess.TimeoutExpired as e:
            raise DeviceError(f"adb 超时: {' '.join(args)}") from e
        if p.returncode != 0:
            raise DeviceError(f"adb 失败: {' '.join(args)}\n{(p.stderr or '').strip()}")
        return p.stdout or ""

    def shell(self, cmd: str, timeout: int = 25) -> str:
        return self.adb("shell", cmd, timeout=timeout)

    def connect(self) -> bool:
        try:
            self.adb("connect", self.serial, timeout=10)
            return self.shell("getprop sys.boot_completed").strip() == "1"
        except DeviceError:
            return False

    def wait_ready(self, timeout: int = 240) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.connect():
                return True
            time.sleep(4)
        return False

    # ---------- 输入 ----------
    # 2026-11-11：模拟器前台切换的瞬间会拒绝注入触摸事件
    # （`SecurityException: Injecting to another application requires INJECT_EVENTS permission`），
    # 属可重试的瞬时错误；以前会直接把整轮任务打成 FAIL。
    _INJECT_HINTS = ("INJECT_EVENTS", "SecurityException")

    def _input(self, cmd: str, x: int, y: int, tries: int = 4) -> None:
        last: Exception | None = None
        for i in range(max(1, int(tries))):
            try:
                self.shell(cmd)
                return
            except DeviceError as exc:
                last = exc
                text = str(exc)
                if not any(h in text for h in self._INJECT_HINTS):
                    raise
                time.sleep(0.4 * (i + 1))
                try:
                    self.shell(f"input tap {int(x)} {int(y)}")
                    return
                except DeviceError as exc2:
                    last = exc2
                    if not any(h in str(exc2) for h in self._INJECT_HINTS):
                        raise
                    time.sleep(0.5)
        raise DeviceError(f"设备拒绝注入触摸事件（INJECT_EVENTS），重试 {tries} 次仍失败：{last}")

    def press(self, x: int, y: int, ms: int | None = None) -> None:
        """长按式点击：本作 50ms tap 经常不响应，默认 220ms 的零距离 swipe。"""
        ms = ms or self.tap_ms
        self._input(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(ms)}", int(x), int(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 500) -> None:
        self._input(
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}",
            int(x2), int(y2),
        )

    def scroll_up(self, x: int = 360, y1: int = 1000, y2: int = 250, ms: int = 600) -> None:
        """内容往上滚（看下面的条目）。"""
        self.swipe(x, y1, x, y2, ms)

    def scroll_down(self, x: int = 360, y1: int = 250, y2: int = 1000, ms: int = 600) -> None:
        """内容往下滚（看上面的条目）。"""
        self.swipe(x, y1, x, y2, ms)

    def key(self, code: str) -> None:
        self.shell(f"input keyevent {code}")

    def back(self) -> None:
        self.key("4")

    # ---------- 截图 ----------
    def screenshot(self, name: str = "shot", fresh: bool = True, tries: int = 4) -> Image.Image:
        """抓一帧。

        2026-11-07 加固：screencap / pull 偶发「文件没写出来」或「png 截断」，
        以前直接抛 DeviceError 会把整轮任务打成 FAIL（实测 artifact 因此从 106s 成功
        变成 `adb 失败: pull /sdcard/_mt_26.png No such file or directory`，
        另一个探针抛 `OSError: image file is truncated`）。现在每次重试用新的
        远端文件名重抓，校验「文件存在 + 大小 > 0 + 能被 PIL 完整解码」，
        全失败时退回 8 秒内的缓存帧（只打 WARN），仍没有才抛错。
        """
        now = time.time()
        if not fresh and self._cache and now - self._cache[0] < self._cache_ttl:
            return self._cache[1]
        err = ""
        for attempt in range(1, max(1, tries) + 1):
            self._shot_n += 1
            remote = f"/sdcard/_mt_{self._shot_n}.png"
            local = self.shot_dir / f"{name}_{self._shot_n}.png"
            try:
                self.shell(f"screencap -p {remote}")
                self.adb("pull", remote, str(local))
                size = local.stat().st_size if local.exists() else 0
                if size <= 0:
                    err = f"{local.name} 大小 {size}"
                else:
                    im = Image.open(local)          # 截断的 png 在这里（或 convert 时）抛 OSError
                    im.load()
                    im = im.convert("RGB")
                    self._cache = (now, im)
                    self._trim()
                    return im
            except (DeviceError, OSError) as e:     # OSError 含 PIL 的 truncated
                err = str(e)
            finally:
                try:
                    self.shell(f"rm -f {remote}")
                except DeviceError:
                    pass
            log.warn(f"  截图失败（第 {attempt}/{tries} 次）：{err}")
            time.sleep(0.6)
        if self._cache and time.time() - self._cache[0] < 8.0:
            log.warn("  截图连续失败，临时复用 %.1fs 前的画面继续（可能略旧）"
                     % (time.time() - self._cache[0]))
            return self._cache[1]
        raise DeviceError(f"截图连续 {tries} 次失败：{err}")

    def _trim(self) -> None:
        keep = self.cfg.runtime.keep_screenshots

        def _mtime(p):          # 文件可能在 glob 与 stat 之间被删掉（Windows 上实测会抛 WinError 2）
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        files = sorted(self.shot_dir.glob("*.png"), key=_mtime)
        for p in files[:-keep]:
            try:
                p.unlink()
            except OSError:
                pass

    # ---------- 应用/前台 ----------
    def focus_pkg(self) -> str:
        out = self.shell("dumpsys window | grep mCurrentFocus")
        m = re.search(r"u0 ([\w.]+)/", out)
        return m.group(1) if m else ""

    def launch(self) -> None:
        self.shell(f"am start -n {self.pkg}/{self.activity}")
        time.sleep(3)

    def stop(self) -> None:
        self.shell(f"am force-stop {self.pkg}")
        time.sleep(2)

    def is_landscape(self, im: Image.Image | None = None) -> bool:
        im = im or self.screenshot("orient")
        return im.width > im.height


def open_device(cfg: Config, connect: bool = True) -> Device:
    dev = Device(cfg)
    if connect and not dev.wait_ready(timeout=15):
        log.warn("adb 未就绪，继续尝试（模拟器可能没开）")
    return dev
