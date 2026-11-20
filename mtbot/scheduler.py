"""调度器：按配置挑任务、按优先级执行、逐任务隔离错误并记录状态。"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from . import log, tasks
from .config import PROFILES, ROOT, Config
from .oasguard import OasYield
from .tasks.base import TaskContext, TaskResult
from .ui import TaskTimeout, UI


class Scheduler:
    def __init__(self, cfg: Config, ui: UI, dry_run: bool = False):
        self.cfg = cfg
        self.ui = ui
        self.ctx = TaskContext(ui=ui, cfg=cfg, dry_run=dry_run)
        self.state_path = ROOT / cfg.runtime.state_file
        # 2026-11-07 用户要求「阴阳师优先」：OAS 抢到模拟器就整轮收摊，不是这个任务的错。
        self.yielded = ""

    def _clear_oas(self, other: str) -> bool:
        """--oas-stop 模式：前台是阴阳师就直接按掉并把游戏拉回前台。

        2026-11-08 用户改规矩「完成这个游戏所需要的全部高效运行脚本，停掉阴阳师」。
        实测（20:22）阴阳师被外部反复拉起，若仍按 2026-11-07 的「让位」逻辑整轮
        中止，36 个任务永远跑不完；所以 kill 模式下这里只花 2~4 秒清理，然后继续。
        返回 True 表示已经处理过（调用方应重读一次前台）。
        """
        if not getattr(self.ui, "oas_stop", False):
            return False
        from . import oasguard

        if not oasguard.is_oas_pkg(other):
            return False
        log.warn(f"  前台是阴阳师（{other}）：按 --oas-stop 直接停掉它，继续跑 MT")
        if not oasguard.stop_oas(self.ui.dev, other):
            return False
        try:
            self.ui.dev.launch()          # 把 MT 拉回前台
        except Exception:  # noqa: BLE001
            pass
        self.ui.wait(2.0)
        return True

    # ---------- 任务选择 ----------
    def select(self, profile: str | None, only: str | None) -> list[str]:
        if only:
            wanted = [x.strip() for x in only.split(",") if x.strip()]
        elif profile:
            wanted = list(PROFILES.get(profile) or tasks.names())
        else:
            wanted = [n for n, t in self.cfg.tasks.items() if t.enabled]
        picked = []
        for n in wanted:
            if n not in tasks.TASK_CLASSES:
                log.warn(f"未知任务: {n}")
                continue
            if not self.cfg.task(n).enabled and not only:
                log.info(f"跳过已禁用任务: {n}")
                continue
            picked.append(n)
        picked.sort(key=lambda n: self.cfg.task(n).priority)
        return picked

    # ---------- 状态 ----------
    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_once(self, task, name: str) -> TaskResult:
        """跑一次任务，带单任务超时看门狗；异常都在这里收口成 TaskResult。"""
        import traceback

        # 2026-11-19 用户反馈「全部任务一起跑会在某一个任务卡住」：
        # ① 单任务默认 20 分钟（原来 40 分钟），② 塔这种天然一场接一场的
        #    任务用自己的 params.timeout_minutes 覆盖，③ 超时的任务不再重试
        #    （重试只会再卡 20 分钟），④ 另有「卡死看门狗」见 Scheduler.run。
        minutes = int(getattr(task, "p", {}).get("timeout_minutes",
                                                  self.cfg.runtime.max_task_minutes)
                      or self.cfg.runtime.max_task_minutes)
        self.ui.deadline = time.time() + minutes * 60 if minutes > 0 else None
        self._task_minutes = minutes
        try:
            return task.run(self.ctx)
        except OasYield as e:
            # 阴阳师到前台了：立刻停手，别在别人的画面上继续点。
            self.yielded = str(e)
            log.warn(f"  {name} 让位给阴阳师（{e}）")
            return TaskResult.fail(f"运行已中止：让位给阴阳师（{e}）")
        except TaskTimeout as e:
            log.error(f"  {name} 超时（>{self._task_minutes} 分钟）: {e}")
            return TaskResult.fail(f"超时: {e}")
        except Exception as e:  # noqa: BLE001
            log.error(f"  {name} 异常: {e}")
            log.error(traceback.format_exc())
            try:
                im = self.ui.dev.screenshot(f"error_{name}")
                log.error(f"  现场截图: {im.filename if hasattr(im, 'filename') else ''}")
            except Exception:  # noqa: BLE001
                pass
            return TaskResult.fail(f"异常: {e}")
        finally:
            self.ui.deadline = None

    def _revive_device(self) -> bool:
        """设备挂了就把它救回来（2026-11-20）。

        以前模拟器整机挂掉（第 64 轮）后，`ensure_main_city()` 一直抛错，
        连续两个任务回不到主城就整轮中止，后面十几个任务白丢。现在先救设备。
        """
        try:
            dev = getattr(self.ui, "dev", None)
            if dev is None or not hasattr(dev, "recover"):
                return False
            if dev.alive():
                return True
            return bool(dev.recover())
        except Exception as e:  # noqa: BLE001
            log.warn(f"  救设备出错（{e}）")
            return False

    def _recover(self) -> None:
        """失败自愈：尽量回到主城，避免一个任务失败后后续任务全部跑偏。"""
        try:
            ok = self.ui.ensure_main_city()
            log.info(f"  自愈：{'已回到主城' if ok else '未确认回到主城'}")
            return
        except Exception as e:  # noqa: BLE001
            log.warn(f"  自愈失败（{e}）")
        if self._revive_device():
            try:
                ok = self.ui.ensure_main_city()
                log.info(f"  自愈：设备已救回，{'已回到主城' if ok else '仍未确认回到主城'}")
                return
            except Exception as e:  # noqa: BLE001
                log.warn(f"  自愈仍失败（{e}），继续下一个任务")
        log.warn("  自愈结束，继续下一个任务")

    # ---------- 执行 ----------
    # 2026-11-19：任务里完全没有点击动作超过这个秒数，就判卡死。
    STALL_SECONDS = 480.0
    WATCHDOG_TICK = 15.0

    def _start_watchdog(self):
        """卡死看门狗（2026-11-19，用户反馈「全部任务一起跑会在某一个任务卡住」）。

        任务卡死的典型形态是「不再发出任何点击」（等一个永远不来的页面、
        在 while 循环里只截图）。ui.deadline 的 20 分钟兜底太晚，
        这里用独立线程每 15s 看一次 `ui.actions`：8 分钟不动就把
        `ui.deadline` 直接设成过去时间 —— 主线程下一次 screen/press/wait
        进 `_check_deadline()` 就会抛 TaskTimeout，整个任务被立刻收口。
        线程只改这个时间戳，不碰设备，避免和主线程的操作打架。
        """
        import threading

        stop = threading.Event()

        def _loop():
            last = self.ui.actions
            ts = time.time()
            while not stop.wait(self.WATCHDOG_TICK):
                cur = self.ui.actions
                if cur != last:
                    last, ts = cur, time.time()
                    continue
                idle = time.time() - ts
                if idle < self.STALL_SECONDS or self.ui.deadline is None:
                    continue
                log.warn(f"  看门狗：{idle:.0f}s 内一次点击都没有（{self.ui.task_name}），"
                         f"判定卡住，立即中止本任务")
                self.ui.stall_note = f"卡死看门狗：{idle:.0f} 秒没有任何点击动作"
                self.ui.deadline = time.time() - 1
                ts = time.time()
        t = threading.Thread(target=_loop, name="mtbot-watchdog", daemon=True)
        t.start()
        return stop

    def run(self, names: list[str]) -> dict[str, TaskResult]:
        import inspect
        import traceback

        state = self._load_state()
        results: dict[str, TaskResult] = {}
        log.info(f"共 {len(names)} 个任务: {', '.join(names)}")
        wd_stop = self._start_watchdog()
        aborted = ""
        stuck_backs = 0        # 连续多少个任务结束后回不到主城
        for i, name in enumerate(names, 1):
            task = tasks.make(name, self.cfg)
            tc = self.cfg.task(name)
            cls = type(task)
            # 2026-11-06：换任务时重置死点表的作用域（键 = 任务名:调用点:坐标），
            # 并放行本任务上一轮登记的死点——一个任务卡过的坐标不该拖累下一轮重试。
            self.ui.begin_task(name)
            log.task(name, f"{name} (Enable, {tc.priority}, {datetime.now():%Y-%m-%d %H:%M:%S})")
            log.info(f"Current task: {name}", with_source=False)
            log.info(f"module_path: {Path(inspect.getfile(cls)).as_posix()}, "
                     f"module_name: {cls.__name__}", with_source=False)
            if self.ctx.dry_run:
                log.info("  (dry-run)")
                results[name] = TaskResult(True, "dry-run")
                continue
            if not self.ctx.dry_run and getattr(self.ui, "foreign_app", None):
                other = self.ui.foreign_app()
                if other and self._clear_oas(other):
                    other = self.ui.foreign_app()
                if other:
                    # 前台被别的应用占着（最常见：OAS 把模拟器切去阴阳师）。
                    # 再往下跑只会在别人的画面上乱按，直接中止本次运行。
                    aborted = f"前台是 {other}（模拟器被其它脚本占用）"
                    log.error(f"  中止运行：{aborted}。其余任务不再执行；"
                              f"等 {other} 空闲后重跑，或在命令后面加 --boot 让脚本自己拉起游戏")
                    results[name] = TaskResult.fail(aborted)
                    for rest in names[i:]:
                        results.setdefault(rest, TaskResult.fail("运行已中止：" + aborted))
                    break
            # 2026-11-03 稳定性：失败重试 + 失败后自愈（参考 OAS）
            attempts = 1 + max(0, int(self.cfg.runtime.task_retries))
            t0 = time.time()
            act0 = self.ui.actions
            hit0 = self.ui.hits
            for attempt in range(attempts):
                res = self._run_once(task, name)
                if res.ok or attempt + 1 >= attempts:
                    break
                if str(res.message).startswith("超时"):
                    # 2026-11-19：卡住超时的任务立刻放弃，重试只会再卡一遍
                    log.warn(f"  {name} 是卡住超时，不再重试（重试只会再卡一遍）")
                    break
                log.warn(f"  {name} 失败（{res.message}），自愈后重试 "
                         f"{attempt + 1}/{attempts - 1}")
                self._recover()
            if not res.ok and self.cfg.runtime.auto_recover:
                self._recover()
            # 0 次动作不算 OK（用户 2026-11-03 要求）：只有任务显式声明 noop_ok 的
            # 已验证空操作（如「今天已购买过」）才允许无点击通过。
            acts = self.ui.actions - act0
            res.stats["actions"] = acts
            # 2026-11-09 假成功审计：actions 包含 expect="none" 的盲点，hits 只包含
            # 变化校验真的命中。这里先只记录+提示（不改判），等全量数据再决定闸门。
            res.stats["hits"] = self.ui.hits - hit0
            if res.ok and acts > 0 and res.stats.get("hits", 0) <= 0:
                # 灰度：先只打标记 + 日志，不改判（2026-11-09 第 25 轮实测，
                # hits=0 的 4 个任务都是「今天真没事可做、只做了导航」的合法情形）。
                res.stats["suspect_nohit"] = True
                log.info("  提示：本任务有点击但没有任何「变化校验命中」（全是盲点/导航），"
                         "结论主要依赖日志判据，见 hits=0")
            if res.ok and acts <= 0 and not res.stats.get("noop_ok"):
                res = TaskResult.fail(f"0 次动作（未确认执行）：{res.message}")
                res.stats["actions"] = 0
                log.warn("  任务没有任何实际动作，按未执行处理（不计 OK）")
            dt = time.time() - t0
            log.info(f"  {'OK' if res.ok else 'FAIL'} {res.message} ({dt:.0f}s)")
            if res.stats:
                log.info(f"  stats: {res.stats}")
            results[name] = res
            state[name] = {
                "last_run": datetime.now().isoformat(timespec="seconds"),
                "ok": res.ok,
                "message": res.message,
                "seconds": round(dt),
                **res.stats,
            }
            self._save_state(state)
            if self.yielded:
                # 让位时不做回主城自愈：屏幕已经不归我们了，再点只会和 OAS 打架。
                aborted = self.yielded
                log.error(f"  中止运行：{aborted}；其余任务不再执行"
                          f"（等阴阳师不用模拟器了再跑）")
                for rest in names[i:]:
                    results.setdefault(rest, TaskResult.fail("运行已中止：" + aborted))
                break
            # 任务之间保证回到主城，避免前一个任务把界面留在奇怪的位置
            try:
                back_ok = self.ui.ensure_main_city()
            except Exception as e:  # noqa: BLE001
                back_ok = False
                log.warn(f"回主城出错（{e}）")
                # 2026-11-20：先判是不是设备挂了，救回来再试一次，别急着中止整轮
                if self._revive_device():
                    try:
                        back_ok = self.ui.ensure_main_city()
                    except Exception as e2:  # noqa: BLE001
                        back_ok = False
                        log.warn(f"  设备救回后仍回不了主城（{e2}）")
            stuck_backs = 0 if back_ok else stuck_backs + 1
            if stuck_backs >= 2:
                # 2026-11-05：连续两个任务都回不到主城 = 界面卡在无法退出的硬页面，
                # 再跑只会在错误页面上乱点，直接中止整轮并记录原因。
                aborted = "连续 2 个任务结束后都回不到主城（疑似卡在无法退出的页面）"
                log.error(f"  中止运行：{aborted}；其余任务不再执行")
                for rest in names[i:]:
                    results.setdefault(rest, TaskResult.fail("运行已中止：" + aborted))
                break
        wd_stop.set()
        ok = sum(1 for r in results.values() if r.ok)
        if aborted:
            log.error(f"本次运行被中止：{aborted}")
        # 2026-11-19 审计：`跳过：…` 也是一种「OK」（今天确实没事可做），但它没有干活，
        # 全算在一起会让人以为整轮都真跑了。这里把两者拆开报。
        skipped = sum(1 for r in results.values()
                      if r.ok and (r.message or "").startswith("跳过"))
        if skipped:
            log.info(f"完成 {ok}/{len(results)} 个任务"
                     f"（真干活 {ok - skipped} 个，真状态跳过 {skipped} 个）")
        else:
            log.info(f"完成 {ok}/{len(results)} 个任务")
        return results
