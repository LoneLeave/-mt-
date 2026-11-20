"""启动/登录阶段的分步进度输出。

用户要求：不要再让 adb/设备异常刷屏，改成
    [OK] / [RETRY n/max] / [FAIL] 原因
每步一行；失败给「下一步怎么办」；traceback 只写日志文件。

用法（run.py --boot 调用）：
    ok = bootstrap(cfg, ui, cold=args.cold, use_emulator=args.emulator)
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from . import log, vision
from .config import ROOT, Config
from .device import DeviceError
from .emulator import Emulator

_TB_FILE = ROOT / "logs" / "boot_traceback.log"


def _out(tag: str, msg: str) -> None:
    line = f"{tag} {msg}"
    print(line, flush=True)
    try:
        with (ROOT / "logs" / "boot.log").open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def ok(msg: str) -> None:
    _out("[OK]", msg)


def retry(i: int, n: int, msg: str) -> None:
    _out(f"[RETRY {i}/{n}]", msg)


def fail(msg: str, hint: str = "") -> None:
    _out("[FAIL]", msg + (f"｜下一步：{hint}" if hint else ""))


def _dump_tb() -> None:
    try:
        with _TB_FILE.open("a", encoding="utf-8") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            f.write(traceback.format_exc())
    except OSError:
        pass


def bootstrap(cfg: Config, ui, cold: bool = False, use_emulator: bool = False,
              max_retry: int = 3) -> bool:
    """返回 True=已在主城。任何异常都只输出一行 [FAIL]，栈写 logs/boot_traceback.log。"""
    t0 = time.time()
    try:
        # 1. 选实例
        ok(f"实例 {cfg.device.serial}（包 {cfg.device.package}）")

        # 2. 先确保模拟器实例在跑
        # 2026-11-20：以前这一步失败就直接 return，根本没机会执行后面第 5 步的
        # `Emulator.start()`（它在 adb 连上之后才跑）—— 于是「--boot 拉不起模拟器」。
        # 现在先看实例死活，没起来就先拉，最多等 240s。
        dev = ui.dev
        em = None
        if use_emulator and cfg.emulator.start:
            em = Emulator(cfg)
            if not em.is_running():
                ok("模拟器没在跑，先启动实例")
                em.start()
                if em.wait_android(240):
                    ok("模拟器实例已启动")
                else:
                    retry(max_retry, max_retry, "模拟器实例 240s 没起来，继续试着连 adb")

        # 2b. adb connect
        connected = False
        for i in range(1, max_retry + 1):
            try:
                dev.adb("connect", cfg.device.serial, timeout=10)
                if dev.shell("getprop sys.boot_completed").strip() == "1":
                    connected = True
                    ok(f"adb 已连接 {cfg.device.serial}")
                    break
                retry(i, max_retry, "adb 连上了，但系统还没启动完")
            except DeviceError as e:
                retry(i, max_retry, f"{e}")
                if i < max_retry:
                    time.sleep(4)
        if not connected and em is not None:
            # 实例刚拉起来时 adb 端口往往还没就绪，再给一次机会
            retry(max_retry, max_retry, "adb 还是连不上，把模拟器实例重新拉一次再等 180s")
            em.start()
            em.wait_android(180)
            for i in range(1, max_retry + 1):
                try:
                    dev.adb("connect", cfg.device.serial, timeout=10)
                    if dev.shell("getprop sys.boot_completed").strip() == "1":
                        connected = True
                        ok(f"adb 已连接 {cfg.device.serial}")
                        break
                except DeviceError as e:
                    retry(i, max_retry, f"{e}")
                    time.sleep(4)
        if not connected:
            fail(f"adb 连不上 {cfg.device.serial}",
                 "先打开 MuMu 模拟器；确认 5037 端口没被 OAS 等其它脚本占用")
            return False

        # 3. 等 boot_completed=1
        deadline = time.time() + 240
        i = 0
        while time.time() < deadline:
            try:
                if dev.shell("getprop sys.boot_completed").strip() == "1":
                    ok("系统已启动（sys.boot_completed=1）")
                    break
            except DeviceError:
                pass
            i += 1
            retry(i, 30, "等待系统启动完成…")
            time.sleep(8)
        else:
            fail("等待系统启动超时（240s）", "模拟器卡启动时在 MuMu 里重启实例")
            return False

        # 4. 校验游戏包
        try:
            path = dev.shell(f"pm path {cfg.device.package}").strip()
        except DeviceError as e:
            fail(f"查询安装包失败：{e}", "adb shell pm 不可用，重启 adb 连接（不要 kill-server）")
            return False
        if not path:
            fail(f"模拟器里没装 {cfg.device.package}", "先在模拟器安装游戏并登录一次")
            return False
        ok(f"游戏包存在（{path.splitlines()[0]}）")

        # 5. 启动/切前台
        if use_emulator and cfg.emulator.start and em is not None:
            em.start()          # 幂等：已在跑就直接返回
        if cold:
            dev.stop()
        for i in range(1, max_retry + 1):
            dev.launch()
            time.sleep(2)
            if dev.focus_pkg() == cfg.device.package:
                ok("游戏已切到前台")
                break
            retry(i, max_retry, f"启动后前台是 {dev.focus_pkg() or '未知'}")
        else:
            fail("游戏起不来/前台不是本游戏",
                 "手动点一下游戏图标；若前台是 com.netease.onmyoji 说明模拟器被 OAS 占用")
            return False

        # 6. 检测登录态
        im = ui.screen("boot_state")
        st = vision.classify(im)
        _out("[..]", f"检测登录态：当前界面={st.value}")
        old_verify = ui.click_verify
        ui.click_verify = False
        try:
            login_ok = ui.login(timeout=300)
        finally:
            ui.click_verify = old_verify
        if not login_ok:
            fail("登录超时（300s）", "看 logs/mtbot_*.log 里的最后一次界面状态；必要时手动登录一次")
            return False
        ok("已进入主城")

        # 7. 主城确认
        st = ui.state()
        if st != vision.State.MAIN_CITY:
            fail(f"主城确认失败（当前={st.value}）", "检查是否有公告/活动弹窗挡着")
            return False
        ok(f"主城已确认｜总耗时 {time.time() - t0:.1f}s")
        return True
    except KeyboardInterrupt:
        raise
    except Exception as e:  # noqa: BLE001
        _dump_tb()
        fail(f"{type(e).__name__}: {e}", "详细栈已写入 logs/boot_traceback.log")
        return False
