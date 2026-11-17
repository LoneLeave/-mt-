from __future__ import annotations

import time

import cv2
import numpy as np

from .adb import Adb


class AdbDevice:
    """把 adb 的 PNG 截图转换成 OpenCV BGR 数组。"""

    def __init__(self, adb: Adb):
        self.adb = adb
        self._last: np.ndarray | None = None

    def screencap(self) -> np.ndarray:
        png = self.adb.screencap()
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("截图解码失败，adb 返回的不是有效 PNG")
        self._last = img
        return img

    def size(self) -> tuple[int, int]:
        if self._last is not None:
            h, w = self._last.shape[:2]
            return w, h
        h, w = self.screencap().shape[:2]
        return w, h

    def tap(self, x: int, y: int) -> None:
        self.adb.tap(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.adb.swipe(x1, y1, x2, y2, duration_ms)

    def keyevent(self, code: str | int) -> None:
        self.adb.keyevent(code)

    def back(self) -> None:
        self.adb.back()

    def launch(self, package: str) -> bool:
        return self.adb.launch(package)

    def force_stop(self, package: str) -> None:
        self.adb.force_stop(package)

    def foreground(self) -> str:
        return self.adb.foreground()


class MockDevice:
    """离线测试用：按顺序返回预置画面，点击只记录不执行。"""

    def __init__(self, frames: list[np.ndarray], advance_on_tap: bool = True):
        if not frames:
            raise ValueError("MockDevice 至少需要一帧画面")
        self.frames = [np.asarray(f) for f in frames]
        self.index = 0
        self.advance_on_tap = advance_on_tap
        self.taps: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int]] = []
        self.keys: list[str | int] = []
        self.launches: list[str] = []

    def screencap(self) -> np.ndarray:
        return self.frames[min(self.index, len(self.frames) - 1)]

    def size(self) -> tuple[int, int]:
        h, w = self.frames[0].shape[:2]
        return w, h

    def _advance(self) -> None:
        if self.advance_on_tap and self.index < len(self.frames) - 1:
            self.index += 1

    def tap(self, x: int, y: int) -> None:
        self.taps.append((int(x), int(y)))
        self._advance()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipes.append((int(x1), int(y1), int(x2), int(y2)))
        self._advance()

    def keyevent(self, code: str | int) -> None:
        self.keys.append(code)
        self._advance()

    def back(self) -> None:
        self.keyevent(4)

    def launch(self, package: str) -> bool:
        self.launches.append(package)
        return True

    def force_stop(self, package: str) -> None:
        pass

    def foreground(self) -> str:
        return "mock"
