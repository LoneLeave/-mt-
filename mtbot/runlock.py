# -*- coding: utf-8 -*-
"""单实例运行锁（带心跳），2026-11-15。

背景：老实现只在锁文件里写一个 PID，判活全靠 `tasklist`。进程一旦「僵死但没退出」
（PID 59096：控制台被误点进标记模式 → print 阻塞 → 主线程卡死，22 个线程全 Wait），
锁就被永久占住，之后每一次启动都是 `exit 4 已经有一个 mtbot 在跑`，只能人工杀进程。

现在锁文件是 JSON：{"pid": ..., "start": ..., "hb": ...}。
- 主流程每碰一次鼠标/截图就 `touch()` 一次心跳（`ui.press`/`ui.screen` 会调）。
- 新进程启动时：PID 活着且心跳在 STALE 秒内 → 拒绝；心跳过期 → 判定为僵死，回收锁
  并把旧 PID 杀掉（同一时刻只能有一个 mtbot 抢模拟器）。
- 兼容旧格式（纯数字）：把文件 mtime 当心跳。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / "logs" / ".mtbot.run.lock"
STALE_SECONDS = 600.0        # 10 分钟没有任何点击/截图 = 僵死
TOUCH_INTERVAL = 5.0         # 心跳最多 5s 写一次，避免频繁磁盘 IO

_last_touch = 0.0
_owned = False


def _pid_alive(pid: int) -> bool:
    try:
        # 中文 Windows 上 tasklist 输出是 GBK，而 `python -X utf8` 把默认解码改成
        # UTF-8，不指定 encoding 时读取线程直接抛 UnicodeDecodeError。
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="ignore", timeout=10).stdout
        return str(pid) in out
    except Exception:  # noqa: BLE001
        return False


def _kill(pid: int) -> bool:
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=15)
        return not _pid_alive(pid)
    except Exception:  # noqa: BLE001
        return False


def read() -> dict:
    """读锁：返回 {"pid": int, "hb": float}；没有锁返回 {}。"""
    try:
        txt = LOCK_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not txt:
        return {}
    if txt.startswith("{"):
        try:
            data = json.loads(txt)
            return {"pid": int(data.get("pid") or 0),
                    "hb": float(data.get("hb") or 0.0)}
        except (ValueError, TypeError):
            return {}
    if txt.isdigit():
        # 旧格式（老版本写的纯 PID）：没有心跳，只能保守判活 —— 绝不因为
        # mtime 旧就杀掉一个可能正在干活的进程。新版本一律写 JSON。
        try:
            hb = LOCK_FILE.stat().st_mtime
        except OSError:
            hb = 0.0
        return {"pid": int(txt), "hb": hb, "legacy": True}
    return {}


def _write(pid: int, hb: float) -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": pid, "start": time.time(), "hb": hb})
    for attempt in range(6):
        try:
            LOCK_FILE.write_text(payload, encoding="utf-8")
            return True
        except OSError:
            if attempt >= 5:
                return False
            time.sleep(0.3)
    return False


def touch(force: bool = False) -> None:
    """心跳：主流程活着就调一下。写失败不影响运行。"""
    global _last_touch
    if not _owned:
        return
    now = time.time()
    if not force and now - _last_touch < TOUCH_INTERVAL:
        return
    _last_touch = now
    _write(os.getpid(), now)


def acquire(stale_seconds: float = STALE_SECONDS) -> tuple[bool, int, str]:
    """抢锁。返回 (拿到没, 对方 PID, 说明)。"""
    global _owned, _last_touch
    info = read()
    pid = int(info.get("pid") or 0)
    hb = float(info.get("hb") or 0.0)
    note = ""
    if pid and pid != os.getpid() and _pid_alive(pid):
        age = time.time() - hb if hb else 0.0
        if info.get("legacy") or not hb:
            return False, pid, f"另一个 mtbot 正在跑（PID {pid}，旧版锁没有心跳，保守按「还在跑」处理）"
        if age <= stale_seconds:
            return False, pid, f"另一个 mtbot 正在跑（PID {pid}，{age:.0f}s 前还在动）"
        # 心跳过期：判定僵死，回收锁并杀掉旧进程，否则两个进程会抢同一台模拟器
        killed = _kill(pid)
        note = (f"发现僵死进程 PID {pid}（{age:.0f}s 没有心跳），"
                f"{'已强制结束' if killed else '结束失败（可能已自行退出）'}并接管锁")
    now = time.time()
    if not _write(os.getpid(), now):
        _owned = True
        return True, 0, (note + "；" if note else "") + "锁文件写不进去（杀软占用），本次不写锁继续运行"
    _owned = True
    _last_touch = now
    return True, 0, note


def release() -> None:
    global _owned
    try:
        info = read()
        if int(info.get("pid") or 0) == os.getpid():
            LOCK_FILE.unlink()
    except OSError:
        pass
    _owned = False
