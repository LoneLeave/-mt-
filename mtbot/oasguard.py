"""阴阳师（OAS）优先：MT 只在 OAS 不用模拟器时干活，OAS 一要用就立刻停手。

用户 2026-11-07 的规矩：「你等着阴阳师不用的时候你再开始，等阴阳师要用的时候你就停止」。

模拟器只有一台，两边同时点就把彼此都按乱（2026-10-30 实测：OAS 抢走前台后
mtbot 仍在阴阳师画面上按竖屏坐标，白等 50 秒返回键）。所以这里的判据只有一个：
**前台包名**。阴阳师在前台 = OAS 正在用，MT 一行字都不许按。

两层防线：
  1. 起跑前 wait_free()：轮询等 OAS 让出（可设上限），等不到就不跑；
  2. 运行中 OasGuard 看门狗：后台线程每 poll 秒看一眼前台，被抢就把 yielding
     置位，UI.press/wait/screen 看到就抛 OasYield，调度器立刻收摊走人。
"""
from __future__ import annotations

import threading
import time

from . import log

# 阴阳师的两个常见包名（国服 / 其它渠道）
OAS_PKGS = (
    "com.netease.onmyoji.wyzymnqsd_cps",
    "com.netease.onmyoji",
)


class OasYield(RuntimeError):
    """OAS 抢到模拟器，本轮必须立刻停止点击（不是脚本出错）。"""


def is_oas_pkg(pkg: str) -> bool:
    pkg = (pkg or "").strip()
    return any(pkg == p or pkg.startswith(p + "/") or pkg.startswith(p + ":")
               for p in OAS_PKGS)


def foreign_pkg(dev) -> str:
    """当前前台包名；读不到返回空串（读不到不当成占用）。"""
    try:
        return (dev.focus_pkg() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def oas_foreground(dev) -> str:
    """OAS 在前台就返回包名，否则空串。"""
    pkg = foreign_pkg(dev)
    return pkg if is_oas_pkg(pkg) else ""


def stop_oas(dev, pkg: str = "") -> bool:
    """把阴阳师从模拟器里按掉（2026-11-08 用户改规矩：完成 MT 全部脚本，停掉阴阳师）。

    只 `am force-stop` 游戏本体，不动模拟器、不动别的应用。返回是否确实
    清干净了（再读一眼前台，已经不是阴阳师就算成功）。前台包名一直读不到
    （adb 抽风）时也返回 False，让调用方自己决定要不要继续。
    """
    targets = [pkg] if pkg else list(OAS_PKGS)
    for p in targets:
        try:
            dev.shell(f"am force-stop {p}")
        except Exception:  # noqa: BLE001
            pass
    time.sleep(1.5)
    left = oas_foreground(dev)
    if left:
        log.warn(f"  阴阳师还在前台（{left}），按掉没成功")
        return False
    log.info(f"  已把阴阳师按掉（{'/'.join(targets)}），模拟器让给 MT")
    return True


def wait_free(dev, minutes: float = 30.0, poll: float = 20.0,
              on_wait=None, kill: bool = False) -> bool:
    """等 OAS 让出模拟器。minutes<=0 表示只看一眼不等待。返回是否已空闲。

    kill=True：不去等，直接把阴阳师按掉再跑（goal「停掉阴阳师」用）。
    """
    t0 = time.time()
    limit = t0 + max(0.0, minutes) * 60
    said = False
    while True:
        pkg = oas_foreground(dev)
        if pkg and kill:
            log.warn(f"  阴阳师正在占用模拟器（前台 {pkg}）：按规矩直接停掉它")
            if stop_oas(dev, pkg):
                return True
        if not pkg:
            if said:
                log.info(f"  阴阳师已让出模拟器（等了 {time.time() - t0:.0f}s），开始跑 MT")
            return True
        if not said:
            log.warn(f"  阴阳师正在占用模拟器（前台 {pkg}）：等它不用了再跑"
                     f"（最多 {minutes:.0f} 分钟）")
            said = True
        if on_wait is not None:
            try:
                on_wait(pkg)
            except Exception:  # noqa: BLE001
                pass
        if time.time() >= limit:
            log.error(f"  等阴阳师等了 {minutes:.0f} 分钟还在占用（前台 {pkg}），"
                      f"这次不跑 MT 了")
            return False
        time.sleep(max(1.0, poll))


class OasGuard:
    """后台看门狗：前台一变成阴阳师就把 yielding 置位。

    只读 adb 的当前焦点，不截图、不点击，成本约一次 `dumpsys window | grep`。
    """

    def __init__(self, dev, poll: float = 15.0, kill: bool = False):
        self.dev = dev
        self.poll = max(2.0, float(poll))
        self.kill = bool(kill)
        self._stop = threading.Event()
        self._th: threading.Thread | None = None
        self.yielding = ""          # 非空 = 被 OAS 抢了，值是它的包名
        self.checks = 0
        self.kills = 0              # 按掉阴阳师的次数（kill 模式）

    # ---------- 生命周期 ----------
    def start(self) -> "OasGuard":
        if self._th is not None:
            return self
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, name="oas-guard", daemon=True)
        self._th.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        th, self._th = self._th, None
        if th is not None:
            th.join(timeout=3.0)

    def __enter__(self) -> "OasGuard":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---------- 探测 ----------
    def check_once(self) -> str:
        """看一眼前台。被 OAS 占了就置 yielding 并返回包名。

        kill=True（2026-11-08 新规矩「停掉阴阳师」）：不置 yielding，直接把
        阴阳师按掉继续干活；只有按不掉时才退回让位。
        """
        self.checks += 1
        pkg = oas_foreground(self.dev)
        if pkg and self.kill:
            if stop_oas(self.dev, pkg):
                self.kills += 1
                # 把 MT 拉回前台，任务才能接着按（否则截图全是桌面）
                try:
                    self.dev.launch()
                    time.sleep(1.5)
                except Exception:  # noqa: BLE001
                    pass
                return ""
            log.warn(f"  阴阳师（{pkg}）按不掉：这次只能让位")
        if pkg and not self.yielding:
            self.yielding = pkg
            log.warn(f"  阴阳师到前台了（{pkg}）：本轮立刻让出模拟器")
        return pkg

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:  # noqa: BLE001
                pass
            if self._stop.wait(self.poll):
                break

    def raise_if_yielded(self) -> None:
        if self.yielding:
            raise OasYield(f"阴阳师占用模拟器（{self.yielding}）")
