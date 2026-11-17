"""命令行入口。

常用：
  python -m mtbot.run --list
  python -m mtbot.run --profile daily            # 每日任务
  python -m mtbot.run --profile reward           # 领奖励/提升
  python -m mtbot.run --profile combat           # 塔/试炼/神殿/竞技
  python -m mtbot.run --profile full --boot      # 全套，先开模拟器登录
  python -m mtbot.run --task tower,tree,demon    # 指定任务
  python -m mtbot.run --dry-run --profile full   # 只看计划
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
import time

from . import log, oasguard, runlock, tasks
from .boot import bootstrap
from .config import PROFILES, ROOT, dump_sample, load
from .debug import DebugRecorder
from .device import open_device
from .scheduler import Scheduler
from .ui import UI

def _acquire_run_lock():
    """单实例锁：两个 mtbot 同时跑会互相抢模拟器（2026-10-30 实测把两边都按乱）。

    2026-11-15：换到 mtbot/runlock.py（JSON + 心跳）。老实现只看 PID 活不活，
    进程僵死后锁会被永久占住 —— 用户从控制台启动一律 exit 4。
    """
    ok, pid, note = runlock.acquire()
    if note:
        log.warn(f"  {note}")
    return ok, pid


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mtbot", description="《我叫MT：崛起》自动化")
    ap.add_argument("--config", default=None, help="配置文件路径（默认 config.json）")
    ap.add_argument("--profile", default=None, choices=sorted(PROFILES))
    ap.add_argument("--task", default=None, help="逗号分隔的任务名，优先级高于 --profile")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    ap.add_argument("--list", action="store_true", help="列出任务与预设")
    ap.add_argument("--dump-config", action="store_true", help="生成/覆盖示例 config.json")
    ap.add_argument("--status", action="store_true", help="打印上次运行状态")
    ap.add_argument("--boot", action="store_true", help="先启动游戏并登录到主城")
    ap.add_argument("--cold", action="store_true", help="--boot 时强制杀进程冷启动")
    ap.add_argument("--emulator", action="store_true", help="--boot 时先拉起模拟器")
    ap.add_argument("--rounds", type=int, default=1,
                    help="整套任务重复跑几轮（默认 1；GUI 的「轮次」用的就是它）")
    ap.add_argument("--gui", action="store_true", help="打开图形界面")
    ap.add_argument("--debug", action="store_true",
                    help="单任务取证：每 2–3s 抓帧到 artifacts/debug/<task>/<ts>/，日志另写 debug.log")
    ap.add_argument("--debug-interval", type=float, default=2.5,
                    help="取证抓帧间隔秒数（默认 2.5）")
    ap.add_argument("--oas-wait", type=float, default=30.0,
                    help="阴阳师占着模拟器时最多等多少分钟（默认 30；0=不等待，直接退出）")
    ap.add_argument("--oas-stop", action="store_true",
                    help="阴阳师占着模拟器时直接把它按掉（am force-stop）继续跑，而不是等它")
    args = ap.parse_args(argv)

    if args.gui:
        from .gui import main as gui_main
        return gui_main()

    cfg = load(args.config)

    if args.dump_config:
        p = dump_sample(args.config)
        log.info(f"已写入示例配置: {p}")
        return 0

    if args.list:
        print("任务（名字 · 说明 · 分类 · 默认优先级）:")
        for name in sorted(tasks.names(), key=lambda n: cfg.task(n).priority):
            t = tasks.TASK_CLASSES[name]
            tc = cfg.task(name)
            flag = "on " if tc.enabled else "off"
            print(f"  {flag} {name:<12} {t.title:<12} {t.category:<7} p={tc.priority:<3} {tc.params}")
        print("\n预设:")
        for k, v in PROFILES.items():
            print(f"  {k:<7} {', '.join(v) if v else '(全部)'}")
        print(f"\n配置文件: {args.config or ROOT / 'config.json'}")
        return 0

    if args.status:
        p = ROOT / cfg.runtime.state_file
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for name, info in sorted(data.items()):
                print(f"{name:<12} {info.get('last_run', '?')} "
                      f"{'OK' if info.get('ok') else 'FAIL'}  {info.get('message', '')}")
        else:
            print("还没有运行记录")
        return 0

    # ---------- 运行 ----------
    if not args.dry_run:
        ok, other = _acquire_run_lock()
        if not ok:
            log.error(f"已经有一个 mtbot 在跑（PID {other}）：同时跑两个会互相抢模拟器，"
                      f"先停掉那个。锁文件：{runlock.LOCK_FILE}")
            return 4
        atexit.register(runlock.release)
    sched_names = None
    if args.task:
        sched_names = [x.strip() for x in args.task.split(",") if x.strip()]
    elif args.profile:
        sched_names = list(PROFILES[args.profile] or [])
    if not sched_names:
        sched_names = [n for n, t in cfg.tasks.items() if t.enabled]

    if args.boot and not args.dry_run:
        dev = open_device(cfg, connect=False)
        ui = UI(dev, cfg)
        if not bootstrap(cfg, ui, cold=args.cold, use_emulator=args.emulator):
            return 3
    else:
        dev = open_device(cfg, connect=not args.dry_run)
        ui = UI(dev, cfg)

    guard = None
    if not args.dry_run:
        # 用户 2026-11-07：阴阳师优先——它要用模拟器就先让它用完。
        # 用户 2026-11-08（goal rev4）：改成「完成 MT 全部脚本，停掉阴阳师」——
        # 这时加 --oas-stop，见到阴阳师直接按掉，不再干等。
        if not oasguard.wait_free(dev, minutes=args.oas_wait, poll=20.0,
                                  kill=args.oas_stop):
            return 6
        guard = oasguard.OasGuard(dev, kill=args.oas_stop).start()
        ui.guard = guard
        ui.oas_stop = bool(args.oas_stop)

    sched = Scheduler(cfg, ui, dry_run=args.dry_run)
    names = sched.select(args.profile if not args.task else None, args.task)
    rounds = max(1, int(args.rounds or 1))
    rec = None
    if args.debug and not args.dry_run:
        rec = DebugRecorder(",".join(names) or "multi", cfg, args.debug_interval).start()
        log.info(f"取证目录: {rec.dir}")
    results: dict = {}
    t0 = time.time()
    try:
        for r in range(1, rounds + 1):
            if rounds > 1:
                log.info(f"===== 第 {r}/{rounds} 轮 =====", with_source=False)
            res = sched.run(names)
            results = res
            if rounds > 1:
                ok = sum(1 for x in res.values() if x.ok)
                log.info(f"—— 第 {r}/{rounds} 轮结束：{ok}/{len(res)} 个任务 OK ——",
                         with_source=False)
            # 模拟器被别的脚本占用 / 中止运行时，继续下一轮没有意义
            if any("运行已中止" in (x.message or "") or "模拟器被其它脚本占用" in (x.message or "")
                   for x in res.values()):
                break
    except Exception as e:  # noqa: BLE001
        # 用户要求：控制台只留一句人类可读原因，完整栈写日志文件
        import traceback
        tb_path = ROOT / "logs" / "run_traceback.log"
        try:
            with tb_path.open("a", encoding="utf-8") as f:
                f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
                f.write(traceback.format_exc())
        except OSError:
            pass
        log.error(f"运行中断：{type(e).__name__}: {e}（详细栈见 logs/run_traceback.log）")
        return 5
    finally:
        if guard is not None:
            guard.stop()
            ui.guard = None
        if rec is not None:
            summary = {
                "task": names,
                "dir": str(rec.dir),
                "elapsed_s": round(time.time() - t0, 1),
                "frames": rec._n,
                "results": {n: {"ok": getattr(x, "ok", None),
                                "message": getattr(x, "message", ""),
                                "stats": getattr(x, "stats", {})}
                            for n, x in results.items()},
            }
            try:
                (rec.dir / "run.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
            log.info(f"取证汇总: {rec.dir / 'run.json'}（{rec._n} 帧）")
            rec.stop()
    fails = [n for n, r in results.items() if not r.ok]
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
