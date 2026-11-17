"""模拟器层：MuMuManager 的启动/状态查询（设备以外的宿主侧控制）。"""
from __future__ import annotations

import json
import subprocess
import time

from . import log
from .config import Config


class Emulator:
    def __init__(self, cfg: Config):
        self.manager = cfg.emulator.manager
        self.vm = str(cfg.emulator.vm)

    def info(self) -> dict:
        try:
            out = subprocess.run([self.manager, "info", "-v", self.vm],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="ignore", timeout=20).stdout
            return json.loads(out[out.index("{"):])
        except Exception:  # noqa: BLE001
            return {}

    def is_running(self) -> bool:
        i = self.info()
        return bool(i.get("is_process_started") and i.get("is_android_started"))

    def start(self) -> None:
        if self.is_running():
            log.info("模拟器已在运行")
            return
        log.info("启动模拟器…")
        subprocess.run([self.manager, "control", "-v", self.vm, "launch"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", timeout=60)

    def shutdown(self) -> None:
        subprocess.run([self.manager, "control", "-v", self.vm, "shutdown"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", timeout=60)

    def wait_android(self, timeout: int = 240) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_running():
                return True
            time.sleep(5)
        return False
