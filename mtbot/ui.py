"""UI 层：页面根节点的到达与保障（回主城、关弹窗、断线重连、登录流程）。

这一层不写业务；tasks 只通过它和 pages 完成操作。
"""
from __future__ import annotations

import json
import sys
import time
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops

from . import runlock
from . import layout as L
from . import log, oasguard, textocr, vision
from .config import ROOT, Config
from .device import Device
from .vision import State


class TaskTimeout(RuntimeError):
    """单个任务超过 max_task_minutes，由调度器捕获并继续下一个任务。"""


class UI:
    def __init__(self, dev: Device, cfg: Config):
        self.dev = dev
        self.cfg = cfg
        self.tap_ms = cfg.runtime.tap_ms
        self._last_state: State | None = None
        # 2026-11-03：调度器每个任务前设置绝对时间戳，任务里任何 press/screen/wait
        # 一旦超时都会抛 TaskTimeout，由调度器兜底，避免死循环把整轮拖死。
        self.deadline: float | None = None
        # 调度器用它判断「任务 0 次动作却自报 OK」——2026-11-03 用户要求收紧语义。
        self.actions = 0
        # 2026-11-09：只在「变化校验真的命中」时 +1，用来区分「点到了」和「点空了」。
        # actions 包盲点（expect="none"），hits 只包可验证的命中。
        self.hits = 0
        # ---------- 2026-11-04 点击量化（用户要求：不许「点了就算」） ----------
        self.task_name = "?"
        self._page = "?"
        # 点击校验：每次点击后等 click_verify_wait 秒抓一帧，比较点击点 ±120px
        self.click_verify = bool(cfg.runtime.click_verify)
        self.click_wait = float(cfg.runtime.click_verify_wait)
        self.click_retry = int(cfg.runtime.click_retry)
        self.click_thresh = 0.02          # 区域内变化像素占比低于 2% 判「空点」
        self._frame_cache: tuple[float, Image.Image] | None = None
        self._click_n = 0
        self._click_log: Path | None = None
        self._issues_dir: Path | None = None
        self._learned: dict[str, tuple[int, int]] = {}
        self._calib = dict(getattr(L, "CLICK_CALIB", {}))
        # ---------- 2026-11-05 死点表（用户要求：控件消失后不要原地空点） ----------
        self._miss_streak: dict[str, int] = {}
        self._dead_noticed: set[str] = set()      # 「死点降级」只提示一次
        self._dead: dict[str, int] = self._load_dead()
        self._seed_dead_from_clicks()
        if self._dead:
            self._persist_dead()
        if self.click_verify:
            self._start_click_log()
        # ---------- 2026-11-07 阴阳师优先（用户要求：OAS 一要用就立刻停手） ----------
        # 模拟器只有一台，OAS 抢走前台后这里仍旧会按竖屏坐标乱点，所以由调度器挂一个
        # 后台看门狗；press/wait/screen 是一切的必经之路，在这里统一拦。
        self.guard: "oasguard.OasGuard | None" = None
        # 2026-11-08 用户改规矩「停掉阴阳师」：run.py --oas-stop 会把这里置 True，
        # 调度器见到阴阳师就按掉它继续跑，而不是整轮中止（见 Scheduler._clear_oas）。
        self.oas_stop: bool = False

    def _check_deadline(self) -> None:
        if self.deadline is not None and time.time() > self.deadline:
            self.deadline = None
            raise TaskTimeout("任务超过 max_task_minutes，已强制中止")

    def _check_guard(self) -> None:
        """阴阳师到前台了没？到了就抛 OasYield，让调度器立刻收摊。"""
        if self.guard is not None:
            self.guard.raise_if_yielded()

    # ---------- 基础 ----------
    def screen(self, name: str = "ui", fresh: bool = True) -> Image.Image:
        self._check_deadline()
        self._check_guard()
        im = self.dev.screenshot(name, fresh=fresh)
        runlock.touch()                      # 心跳：主流程还在动
        self._frame_cache = (time.time(), im)
        if im.width > im.height and not getattr(self, "_warned_landscape", False):
            self._warned_landscape = True
            log.warn("  截图是横屏：模拟器可能被其它脚本（OAS）切走了，结果不可信")
        return im

    # ---------- 点击量化（2026-11-04） ----------
    def _start_click_log(self) -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        run_dir = ROOT / "artifacts" / "run" / ts
        # 2026-11-05：杀软扫描期 mkdir 偶发 WinError 5，重试几次；仍失败就不记流水，别拦住整轮
        for attempt in range(6):
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
                self._issues_dir = run_dir / "issues"
                self._issues_dir.mkdir(parents=True, exist_ok=True)
                break
            except OSError:
                if attempt >= 5:
                    log.warn("  点击流水目录建不了（杀软占用），本轮不记录点击流水")
                    self._issues_dir = None
                    self._click_log = None
                    return
                time.sleep(0.3)
        self._click_log = run_dir / "clicks.jsonl"
        log.info(f"  点击流水：{self._click_log}")

    def _caller(self) -> str:
        """用调用栈位置当「按钮名」，不依赖调用方额外传 label。"""
        try:
            f = sys._getframe(2)
            return f"{Path(f.f_code.co_filename).stem}:{f.f_lineno}:{f.f_code.co_name}"
        except Exception:  # noqa: BLE001
            return "?"

    def set_page(self, name: str) -> None:
        """页面对象抓图时调用，让点击流水里的 page 是「页面名」而不是状态名。"""
        self._page = name

    def _persist_calib(self) -> None:
        if not self._click_log:
            return
        p = self._click_log.parent / "calib_learned.json"
        try:
            with p.open("w", encoding="utf-8") as f:
                json.dump(self._learned, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # ---------- 2026-11-05 死点表 ----------
    # 2026-11-06 修根因：旧键是 f"{self._page}|{label}"，而 _page 只在 Page 对象抓图时
    # 才更新——assist / combat 这些任务根本不设页面名，键前缀会一直停在上一个任务的
    # 页面名上（日志里出现 tower|assist:130:_upgrade_loop 就是这种污染）。后果是：
    # 一个任务里点空的坐标，会把另一个任务同一调用点的有效点击永久跳过
    # （02:26 起「死点跳过 tower|ui:484:ensure_main_city」连打 130 条、一次真点击都没发）。
    # 现在键 = 任务名 + 调用点 + 坐标，跨任务不可能再撞；并加上版本号，旧表自动作废。
    DEAD_VERSION = 2

    def _calib_path(self) -> Path:
        return ROOT / "logs" / "calib.json"

    def _load_dead(self) -> dict[str, int]:
        p = self._calib_path()
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if int(data.get("version", 1)) != self.DEAD_VERSION:
                    log.info("  死点表版本升级，忽略旧的（键含页面名，会跨任务污染）")
                    return {}
                return {k: int(v) for k, v in (data.get("dead") or {}).items()}
        except (OSError, ValueError):
            pass
        return {}

    def _seed_dead_from_clicks(self, runs: int = 3) -> None:
        """用最近几轮的 clicks.jsonl 回填死点：样本 ≥3 且一次都没命中。

        2026-11-05 实测：召唤结果页上 (88,1205) 连按 484 次全部 diff=0.000，
        每次还跟 4 个 ±120 补偿点击——这类坐标以后直接判死，不再发点击。
        2026-11-06：只认新格式里的 key（含任务名+坐标）；老流水没有 key 字段，
        其 page 前缀不可信，一律不采信。
        """
        base = ROOT / "artifacts" / "run"
        if not base.exists():
            return
        try:
            dirs = sorted([p for p in base.iterdir() if p.is_dir()], reverse=True)[:runs]
        except OSError:
            return
        for d in dirs:
            f = d / "clicks.jsonl"
            if not f.exists():
                continue
            seen: dict[str, list[int]] = {}
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    k = rec.get("key")
                    if not k or rec.get("hit") is None:
                        continue          # 老格式 / 不校验的导航点击，不参与判死
                    seen.setdefault(k, [0, 0])
                    seen[k][0] += 1
                    seen[k][1] += 1 if rec.get("hit") else 0
            except (OSError, ValueError):
                continue
            for k, (total, hits) in seen.items():
                if total >= 3 and hits == 0:
                    self._dead.setdefault(k, total)

    def _persist_dead(self) -> None:
        p = self._calib_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"version": self.DEAD_VERSION, "dead": self._dead},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def begin_task(self, name: str) -> None:
        """调度器在每个任务开始前调用：换任务名、清页面名、放行本任务的旧死点。"""
        self.task_name = name
        self._page = name
        self._miss_streak.clear()
        self._dead_noticed.clear()
        stale = [k for k in self._dead if k.startswith(f"{name}:")]
        for k in stale:
            self._dead.pop(k, None)
        if stale:
            self._persist_dead()
        self._dead_ts = time.time()

    def _offset(self, key: str) -> tuple[int, int]:
        return self._learned.get(key) or self._calib.get(key, (0, 0))

    def _frame(self) -> Image.Image:
        """校验用「改前帧」：2.5 秒内的缓存帧直接用，避免每次点击都多抓一张。"""
        if self._frame_cache and time.time() - self._frame_cache[0] <= 2.5:
            return self._frame_cache[1]
        return self.screen("click_pre")

    @staticmethod
    def _region_diff(a: Image.Image, b: Image.Image, pos, r: int = 120) -> float:
        """点击点周围 ±r 区域里「灰度差 > 20」的像素占比。"""
        if a.size != b.size:
            return 1.0
        x0, y0 = max(0, pos[0] - r), max(0, pos[1] - r)
        x1, y1 = min(a.width, pos[0] + r), min(a.height, pos[1] + r)
        if x1 <= x0 or y1 <= y0:
            return 1.0
        pa = a.convert("L").crop((x0, y0, x1, y1))
        pb = b.convert("L").crop((x0, y0, x1, y1))
        hist = ImageChops.difference(pa, pb).histogram()
        total = pa.width * pa.height
        return sum(hist[20:]) / total if total else 0.0

    def _log_click(self, key: str, raw, used, ms, hit, diff: float, attempt: int) -> None:
        if not self._click_log:
            return
        rec = {"ts": round(time.time(), 3), "task": self.task_name, "page": self._page,
               "key": key, "btn": key, "raw": list(raw), "used": list(used),
               "ms": ms, "hit": hit, "diff": round(diff, 4), "attempt": attempt}
        try:
            with self._click_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _save_click_issue(self, key: str, before: Image.Image, after: Image.Image,
                          used, diff: float) -> None:
        if not self._issues_dir:
            return
        safe = "".join(c if c.isalnum() else "_" for c in key)[:80]
        d = self._issues_dir / f"click_{self._click_n}_{safe}"
        d.mkdir(parents=True, exist_ok=True)
        before.save(d / "before.png")
        after.save(d / "after.png")
        with (d / "info.txt").open("w", encoding="utf-8") as f:
            f.write(f"key={key}\nused={used}\ndiff={diff:.4f}\n"
                    f"task={self.task_name}\npage={self._page}\n")

    def press(self, pos: tuple[int, int], ms: int | None = None,
              label: str | None = None, expect: str = "change") -> bool:
        """点击（长按式）。2026-11-04：默认会校验点击点周围是否真的变了。

        expect="change"：必须观测到区域变化，空点会按 ±8/±16px 重试；
        expect="none"：导航类点击（点空白/返回/关弹窗），不校验也不重试。
        返回是否确认「点到了」（expect="none" 时恒为 True，只代表已发出）。
        """
        self._check_deadline()
        self._check_guard()
        ms = ms or self.tap_ms
        x0, y0 = int(pos[0]), int(pos[1])
        # 键 = 任务名 + 调用点 + 坐标：任务名界定生命周期，坐标保证同一调用点里的
        # 循环点击（页签、列表行）互不串味。
        key = f"{self.task_name}:{label or self._caller()}:{x0},{y0}"
        # 2026-11-06：死点 ≠ 不要点。
        # 旧实现直接 return False 让点击彻底不发出，于是「一键上阵 / 已选中的页签 /
        # 点空白 / 左下返回」这类本来就不改变画面的点击一旦被登记成死点，真正该执行的
        # 动作也再也不会发生（凌晨 equipment/inherit 就是靠这条一路空转到 FAIL）。
        # 现在死点只表示「这个点用变化校验看不出效果」，照常单击一次，不校验也不补偿。
        if expect == "change" and key in self._dead:
            if key not in self._dead_noticed:
                self._dead_noticed.add(key)
                log.info(f"  死点降级：{key} 在 ({x0},{y0}) 连续 {self._dead[key]} 次无变化，"
                         f"之后只点击不校验（动作照常发出）")
            expect = "none"
        dx, dy = self._offset(key)
        x, y = x0 + dx, y0 + dy
        self.actions += 1
        self._click_n += 1
        runlock.touch()                      # 心跳：主流程还在动
        if not self.click_verify or expect == "none":
            log.debug(f"press {pos} ms={ms}")
            self.dev.press(x, y, ms)
            # 导航类点击也进流水（hit=None 表示不参与判死），否则复盘时看不到它们
            self._log_click(key, (x0, y0), (x, y), ms, None, 0.0, 0)
            return True
        before = self._frame()
        self.dev.press(x, y, ms)
        time.sleep(self.click_wait)
        after = self.screen("click")
        diff = self._region_diff(before, after, (x, y))
        hit = diff >= self.click_thresh
        self._log_click(key, (x0, y0), (x, y), ms, hit, diff, 0)
        log.debug(f"press {pos} ms={ms} -> ({x},{y}) diff={diff:.3f} {'hit' if hit else 'MISS'}")
        if hit:
            self.hits += 1
            self._miss_streak.pop(key, None)
            return True
        self._save_click_issue(key, before, after, (x, y), diff)
        streak = self._miss_streak.get(key, 0) + 1
        self._miss_streak[key] = streak
        log.warn(f"  空点：{key} 在 ({x},{y}) 点击后 ±120px 无变化（diff={diff:.3f}，连续 {streak} 次）")
        if streak >= 3:
            # 连续 3 次 MISS：判为死点，登记后立即放弃，不再做 4 个补偿点
            self._dead[key] = streak
            self._persist_dead()
            log.warn(f"  死点登记：{key} 连续 {streak} 次 MISS，跳过补偿并停止后续点击")
            return False
        # 逐级放大偏移重试（上下各 8/16px），成功即把该偏移记进学习表
        tries = ((0, -8), (0, 8), (0, -16), (0, 16))
        for i, (ox, oy) in enumerate(tries[:max(0, self.click_retry * 2)]):
            px, py = x + ox, y + oy
            self.dev.press(px, py, ms)
            time.sleep(self.click_wait)
            after = self.screen("click")
            diff = self._region_diff(before, after, (px, py))
            hit = diff >= self.click_thresh
            self._log_click(key, (x0, y0), (px, py), ms, hit, diff, i + 1)
            if hit:
                self.hits += 1
                self._learned[key] = (dx + ox, dy + oy)
                self._miss_streak.pop(key, None)
                log.info(f"  空点补偿：{key} 改用 ({px},{py}) 后命中（diff={diff:.3f}）")
                self._persist_calib()
                return True
        log.warn(f"  空点：{key} 在 ({x},{y}) 附近 4 个补偿点都没反应，放弃本次点击")
        return False



    def battle_skip(self, im: Image.Image | None = None, ms: int = 300,
                    label: str = "battle_skip",
                    quiet: bool = False) -> bool:
        """点战斗页右下的「跳过」（立即结算）。

        2026-11-07：固定坐标 (655,900) 落在按钮边缘——模板 跳过.png 命中 0.993、
        中心 (652,899)；实测有一次 MISS diff=0.003、靠 ±8px 补偿到 (655,892) 才中，
        白等 4 个补偿点（每个约 2s）。这里改成「先模板定位」，并且不校验：跳过是
        300ms 长按的半透明按钮，整屏 diff 取决于结算页切换时机，用变化校验只会把
        正常的跳过判成空点。调用方本来就会再抓帧判结算页。

        2026-11-07 二次修正：模板找不到时**不再盲点回退坐标**。实测 470 张真机帧里，
        有「跳过」的战斗页最低 0.662（亮背景），没「跳过」的阵营挑战战斗页最高 0.409，
        阈值 0.60 能把两档分开；而分数 <0.60 的那些帧（如 0.000）其实已经是结算页/
        切场中，盲点 (652,899) 只会点到不相干的控件。
        """
        if im is None:
            im = self.screen("battle_skip")
        try:
            from . import template as _T
            m = _T.VI.find(im, "跳过.png", L.BATTLE_SKIP_THRESHOLD, roi=L.BATTLE_SKIP_ROI)
        except Exception:      # noqa: BLE001 - cv2/模板缺失：退化成旧的固定坐标
            log.warn("  「跳过」模板匹配不可用，按固定坐标点一次")
            return self.press(L.BATTLE_SKIP, ms, label=label, expect="none")
        if m is None:
            # quiet：调用方自己在 1.2s 轮询里反复调用，未命中不必每次刷一行日志
            if quiet:
                log.debug("  这一页没有「跳过」按钮（模板未命中），等结算，不盲点")
            else:
                log.info("  这一页没有「跳过」按钮（模板未命中），等结算，不盲点")
            return False
        log.debug(f"battle_skip 在 {m.center}（模板 {m.score:.3f}）")
        return self.press(m.center, ms, label=label, expect="none")

    def battle_finish(self, im: Image.Image | None = None, ms: int = 300,
                      timeout: float = 12.0, label: str = "battle_skip",
                      grace: float = 4.0) -> bool:
        """开打后把这一场推到结算：每 1.2s 试一次「跳过」，离开战斗就返回。

        2026-11-08：旧写法是 `ui.wait(8)` 再点一次跳过——前 8 秒白等，而且只点
        一次；没点中就一直等到战斗自然结束（45s+）。实测跳过键在开打约 1s 就
        出现（模板 0.997~1.000，中心恒 (652,899)），轮询 2~4 秒就能进结算页。

        2026-11-08 二次修正（`logs\_verify_bf_123225.log` 12:34:46 那一场）：
        点完「战斗」立刻抓到的第一帧还是进场过渡（classify 不是 battle），旧码
        直接 `return True` 当成「已经打完了」→ 一次跳过都没点，后面 26 秒全在
        战斗画面上空转，`_result` 判 none，任务继续按「列表页」去扫荡/点宝箱，
        一路点到公会页（那 2 次空点的根因）。现在用 `grace` 区分两种「不是战斗」：
        还没进战斗（进场中，继续等）vs 打过之后离开（真结算）。

        返回 True = 已经离开战斗态（进结算/回页），False = 到点还在打。
        """
        start = time.time()
        end = start + timeout
        started = False
        first = im
        while time.time() < end:
            cur = first if first is not None else self.screen(label)
            first = None
            st = self.state(cur)
            if st == State.BATTLE:
                started = True
                self.battle_skip(cur, ms=ms, label=label, quiet=True)
                self.wait(1.2)
                continue
            if started:
                return True          # 打过再离开 = 真的结算了
            if time.time() - start >= grace:
                # 宽限期内一直没见到战斗态：这场压根没打起来（次数/等级限制等），
                # 交给调用方自己判，别在这儿死等。
                return True
            self.wait(0.6)
        return self.state() != State.BATTLE

    def state(self, im: Image.Image | None = None) -> State:
        st = vision.classify(im or self.screen())
        if st != self._last_state:
            self._last_state = st
            log.ui(st.value)          # OAS 风格:  INFO ... │ [UI] result_tree
        return st

    def wait(self, sec: float) -> None:
        # deadline 已在 __init__ 初始化；这里先做一次检查，再把 sleep 截断到剩余时间。
        self._check_deadline()
        self._check_guard()
        if self.deadline is not None:
            sec = max(0.0, min(sec, self.deadline - time.time()))
        time.sleep(sec)

    # ---------- 弹窗 ----------
    def close_popup(self, im: Image.Image | None = None) -> bool:
        """点空白 + 找右上角红 X。返回是否已离开“被压暗/弹窗”状态。"""
        blocked = (State.MAIN_CITY_DIM, State.DIALOG)
        shot0 = im if im is not None else self.screen("popblanks")
        for pos in L.POPUP_BLANKS:
            # 2026-11-09：再排一层保险 —— 那一点当前是金色的话就是「确定/购买」，
            # 跳过它（`CONFIRM_DIALOG` 判据万一漏了，这里也不会替玩家花钱）。
            if vision.is_gold(shot0, pos[0], pos[1], r=18):
                log.debug(f"  空白点 {pos} 当前是金色按钮，跳过（不误点确定/购买）")
                continue
            # 2026-11-06：点空白之前先确认不是「左取消/右确定」的确认框——
            # 那种框点空白等于替玩家按「确定」，遇上花钻石的购买确认就会真扣钻石。
            if self.state() == State.CONFIRM_DIALOG:
                log.warn("  点空白前发现确认弹窗，改点「取消」")
                self.press(L.CONFIRM_CANCEL, 180)
                time.sleep(0.9)
                return self.state() not in blocked
            self.press(pos, 150, label="popup_blank", expect="none")
            time.sleep(1.0)
            st = self.state()
            if st not in blocked:
                return True
            shot0 = self.screen("popblanks2")   # 画面变了，后面的空白点按新帧重判
        im = im or self.screen("popx")
        for cx, cy in self._find_close_buttons(im):
            for dx, dy in ((0, 0), (-20, 10), (-20, 0), (-10, 12), (8, 8)):
                self.press((int(cx + dx), int(cy + dy)), 90, label="popup_x", expect="none")
                time.sleep(0.8)
                if self.state() not in blocked:
                    return True
        for pos in L.POPUP_X_GUESSES:
            self.press(pos, 120, label="popup_guess", expect="none")
            time.sleep(0.9)
            if self.state() not in blocked:
                return True
        return False

    @staticmethod
    def _find_close_buttons(im: Image.Image) -> list[tuple[float, float]]:
        """右上角红色圆形关闭按钮：命中点在图标左下约 (-20, +10)。

        只在右上角找（x≥540, y≤380）：英雄卡上的红色「战」角标、铁匠铺槽位红点
        都在更靠内/靠下的位置，不收紧范围会被当成关闭钮乱点。
        """
        pts: set[tuple[int, int]] = set()
        for y in range(60, 380, 2):
            for x in range(540, im.width - 16, 2):
                R, G, B = im.getpixel((x, y))
                if R > 165 and G < 100 and B < 100 and (R - G) > 75 and (R - B) > 75:
                    pts.add((x, y))
        out: list[tuple[float, float]] = []
        while pts:
            seed = pts.pop()
            q = deque([seed])
            comp = [seed]
            while q:
                cx, cy = q.popleft()
                for dx in (-2, 0, 2):
                    for dy in (-2, 0, 2):
                        np_ = (cx + dx, cy + dy)
                        if np_ in pts:
                            pts.discard(np_)
                            q.append(np_)
                            comp.append(np_)
            xs = [p[0] for p in comp]
            ys = [p[1] for p in comp]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            if len(comp) >= 40 and 12 <= w <= 70 and 12 <= h <= 70 and abs(w - h) <= 22:
                out.append((sum(xs) / len(comp), sum(ys) / len(comp)))
        return out

    def close_promo(self) -> bool:
        """关闭全屏促销页（累充/首充/活动）：这类页面没有遮罩，点空白无效。

        顺序：找右上角红 X（命中点偏移 -20,+10）→ 猜测点 → 左下返回箭头。
        关掉一个就算成功，调用方应循环直到回到主城。
        """
        before = self.state()
        im = self.screen("promo")
        for cx, cy in self._find_close_buttons(im):
            for dx, dy in ((0, 0), (-20, 10), (-20, 0), (-10, 12), (8, 8)):
                self.press((int(cx + dx), int(cy + dy)), 120, label="promo_x", expect="none")
                time.sleep(0.8)
                st = self.state()
                if st != before or st == State.MAIN_CITY:
                    log.info("  关闭促销页（红 X）")
                    return True
        # 全屏活动页：左下返回箭头
        self.press(L.BACK, 220, label="promo_back", expect="none")
        time.sleep(1.4)
        st = self.state()
        if st == State.QUIT_DIALOG:
            self.press(L.QUIT_CANCEL, 180)
            time.sleep(0.8)
            return False
        if st != before or st == State.MAIN_CITY:
            log.info("  关闭促销页（返回箭头）")
            return True
        return False

    # ---------- 干扰处理 ----------
    def _reconnect_ok(self, im: Image.Image):
        """在断线弹窗里用 OCR 找「重新登录 / 确定 / 登录」按钮中心。

        2026-11-10：固定坐标 (360,748) 在真机上点不动（diff=0.000）。
        """
        try:
            if not textocr.available():
                return None
            lines = textocr.read_lines(im, L.RECONNECT_LOGIN_BOX, min_score=0.5)
        except Exception:  # noqa: BLE001
            return None
        cands = [c for t, c, _bb, _s in lines
                 if ("重新登录" in t or "确定" in t or t.strip() == "登录")]
        return max(cands, key=lambda c: c[1]) if cands else None

    def _title_start_text(self, im: Image.Image) -> str:
        """读标题页按钮文字（用于防误判）。

        2026-11-10 实测：「我要变强」引导页因为 (360,1000) 是金色「前往」
        而 (150,1000) 不是金色，被 `vision.title_screen` 误判成标题页 →
        `ensure_main_city` 会去点「开始游戏」。这里先读一眼按钮文字，
        不是「开始游戏/进入游戏/开始」就不点。OCR 不可用时返回空串（保持旧行为）。
        """
        try:
            if not textocr.available():
                return ""
            lines = textocr.read_lines(im, L.TITLE_START_BOX, min_score=0.5)
        except Exception:  # noqa: BLE001
            return ""
        return " ".join(t for t, _c, _bb, _s in lines)

    def _looks_like_title_start(self, im: Image.Image) -> bool:
        txt = self._title_start_text(im)
        if not txt:
            return True          # OCR 不可用：保持旧行为（直接点）
        return ("开始游戏" in txt) or ("进入游戏" in txt) or ("开始" in txt)

    def handle_interruptions(self) -> bool:
        """退出确认 / 断线弹窗 / 布阵保存提示 / 结算页的确定。返回 True 表示处理过。"""
        st = self.state()
        if st == State.QUIT_DIALOG:
            self.press(L.QUIT_CANCEL, 180)
            time.sleep(0.9)
            return True
        # 2026-11-06：通用确认框（左红「取消」+ 右金「确定」）之前没有分支，
        # 掉进 close_popup() 的「点空白」里——那四个空白点里有 (360,1190) 这种
        # 可能落在金色「确定」上的位置，一旦是「花钻石购买」的确认框就会真扣钻石。
        # 回主城的路上遇到确认框一律取消，绝不替玩家花钱。
        if st == State.CONFIRM_DIALOG:
            log.warn("  回主城路上遇到确认弹窗，点「取消」（不替玩家花钻石）")
            self.press(L.CONFIRM_CANCEL, 180)
            time.sleep(0.9)
            return True
        im = self.screen()
        # 2026-11-08：「挑战失败 / 通过以上途径增强实力」这类居中模态弹窗。
        # 它 classify=UNKNOWN、点 BACK 整屏 diff≈0.004，旧的 _escape_unknown 五个出口
        # 全都点不到「确定」——2026-11-07 因此让 relic 整轮卡在弹窗里（13 次 back_probe）。
        # 只点左「确定」；右侧「再次挑战」是金钮，点了会真的再打一场，绝不点。
        if vision.modal_dim(im):
            txt = ""
            try:
                txt = textocr.read_text(im, L.FAIL_DIALOG_ROI)
            except Exception:  # noqa: BLE001
                txt = ""
            if any(k in txt for k in L.FAIL_DIALOG_KEYS):
                log.info("  结算/失败弹窗：点「确定」关掉（不碰「再次挑战」）")
                self.press(L.FAIL_DIALOG_OK, 200)
                time.sleep(1.4)
                return True
            # 2026-11-10：整屏结算面板（「当前战斗 / 作战奖励」+ 底部确定·返回玩法）。
            pos = self._result_panel_ok(im)
            if pos is not None:
                log.info(f"  结算面板：点 {pos} 关掉（这层压着活动页，BACK 关不掉）")
                self.press(pos, 220, label="result_panel_ok", expect="none")
                time.sleep(1.5)
                return True
        if vision.lineup_save_dialog(im):
            log.info("  布阵未保存提示：点「保存」退出布阵页")
            self.press(L.LINEUP_SAVE, 220)
            time.sleep(1.6)
            return True
        if st == State.RECONNECT:
            log.warn("断线：继续重连")
            self.press(L.RECONNECT, 200)
            time.sleep(3.0)
            if self.state() == State.RECONNECT:
                log.warn("  重连没反应，停止连点")
                return False
            return True
        if st == State.RECONNECT_LOGIN:
            log.warn("断线：需要重新登录")
            # 2026-11-10 第 41 轮 10:54:53：固定点 (360,748) 点下去 diff=0.000，
            # 4 个补偿点也没反应，弹窗根本没被关掉。
            # 现在先用 OCR 找「重新登录 / 确定 / 登录」那一行，再点它的中心。
            pos = self._reconnect_ok(self.screen("reconnect_login"))
            if pos:
                log.info(f"  重连弹窗：按文字定位到按钮 {pos}，点它")
                self.press(pos, 200, label="reconnect_login_ok_ocr", expect="none")
            else:
                self.press(L.RECONNECT_LOGIN_OK, 200)
            time.sleep(2.5)
            if self.state() == State.RECONNECT_LOGIN:
                log.warn("  断线弹窗没关掉，停止连点")
                return False
            self.login()
            return True
        return False

    # ---------- 页面根节点 ----------
    def foreign_app(self) -> str:
        """前台是不是别的应用（最常见是 OAS 把模拟器切去阴阳师）。

        返回前台包名；是本游戏或读不到时返回空串。2026-10-30 的日志里，
        OAS 抢走模拟器后每个任务都在阴阳师画面上白按 50 秒返回键——现在
        调度器看到它会直接中止本次运行，而不是和 OAS 抢。
        """
        try:
            f = self.dev.focus_pkg()
        except Exception:  # noqa: BLE001
            return ""
        return f if f and f != self.dev.pkg else ""

    def _landscape(self) -> bool:
        """最近一帧是不是横屏（本游戏恒为 720×1280 竖屏）。

        2026-11-06 20:00 实录：OAS 的 Restart 任务把模拟器切到阴阳师后，MT 这边
        拿到 1280×720 横屏，却仍按竖屏坐标连点 (_escape_unknown 的红 X/空白点)，
        直到 adb 中途返回非 0 才崩。横屏一律当成「模拟器被别人占着」，不再点击。
        """
        cached = self._frame_cache[1] if self._frame_cache else None
        return cached is not None and cached.width > cached.height

    def ensure_main_city(self, tries: int = 14) -> bool:
        """回主城。主城根节点按返回会弹「确认要退出游戏吗」，以此作为判据。"""
        other = self.foreign_app()
        if other:
            log.warn(f"  前台是 {other}（不是本游戏，可能被 OAS 占用），不回主城")
            return False
        t0 = time.time()
        self._unknown_backs = 0
        self._stuck_backs = 0
        if self.state() == State.MAIN_CITY:
            return True
        log.goto("main")
        for i in range(tries):
            if self.handle_interruptions():
                continue
            # 2026-11-05：OAS 可能在任务执行中途抢前台（凌晨 relic/star 因此空转 735s）。
            # 进入时已查过一次 foreign_app，但中途切走就查不到了；每 4 步复检一次，
            # 一旦前台是别的应用就立刻放弃，不要把点击浪费在阴阳师上。
            if i and i % 4 == 0:
                other = self.foreign_app()
                if other:
                    log.warn(f"  回主城中途：前台切到 {other}（OAS？），停止空转")
                    return False
            st = self.state()
            if st == State.MAIN_CITY:
                log.arrived("main", time.time() - t0)
                return True
            if self._landscape():
                log.warn("  画面变成横屏（模拟器被其它脚本切走），停止点击")
                return False
            if st == State.MAIN_CITY_DIM:
                self.close_popup()
                continue
            if st == State.DIALOG:
                self.close_popup()
                continue
            if st == State.TITLE:
                # 2026-11-09 00:03 实测（logs/_full18_000401.log）：被踢回登录页
                # （左上版本号 + 金色「开始游戏」）时，这里原先没有 TITLE 分支，
                # 只会按左下 BACK（88,1205）空转到 tries 用完 → 「没能回到主城」，
                # 一天的第一个任务直接失败。登录页的出口只有两条：
                # 勾选《用户协议》+ 点「开始游戏」（boot 里是同一套动作）。
                shot = self.screen("title_ensure")
                if not self._looks_like_title_start(shot):
                    log.info(f"  画面被误判成标题页（按钮文字是「{self._title_start_text(shot)[:16]}」），"
                             f"改按返回钮，不点「开始游戏」")
                    self.press(L.BACK, 220, label="title_misjudge_back", expect="none")
                    time.sleep(1.6)
                    continue
                R, G, B = vision.avg(shot, *L.TITLE_AGREE, r=12)
                if not (G > 110 and G - R > 45 and G - B > 35):
                    self.press(L.TITLE_AGREE, 180, label="title_agree", expect="none")
                    time.sleep(0.8)
                self.press(L.TITLE_START, 220, label="title_start", expect="none")
                time.sleep(6.0)
                continue
            if st == State.SUMMON_RESULT:
                # 2026-11-05：bp 免费一抽后的召唤结果页，返回键无效，只能点左「返回」
                shot = self.screen("summon")
                if self._try_tap(L.SUMMON_BACK, 260, "summon_back"):
                    self._unknown_backs = 0
                    continue
                self._save_stuck(shot)
                log.warn("  召唤结果页点「返回」后画面无变化，停止回主城")
                return False
            if st == State.NAV_PAGE:
                # 2026-11-06：主城体系一级页（英雄/助阵/战役地图/历练 hub…）底部有导航条，
                # 左下角没有返回箭头——那个位置被导航条占着，按 BACK 实测整屏 diff≈0.0016
                # 空转，一直耗到 tries 用完（02:26~02:33 的 assist 就卡在这里）。
                # 一级页一律点「主城」页签脱身。
                shot = self.screen("nav_page")
                if self._try_tap(L.TAB_MAIN, 220, "nav_home"):
                    self._unknown_backs = 0
                    self._stuck_backs = 0
                    if self.state() == State.MAIN_CITY:
                        log.info(f"  从一级页点「主城」页签回到主城（{i + 1} 步）")
                        log.arrived("main", time.time() - t0)
                        return True
                    continue
                if self._escape_unknown():
                    self._unknown_backs = 0
                    continue
                self._save_stuck(shot)
                log.warn("  一级页点「主城」页签也没反应，放弃回主城（不再耗完 tries）")
                return False
            if st == State.UNKNOWN:
                if self._reconnect_lost(self.screen("main_lost_conn")):
                    continue
                # 先按左下返回箭头：绝大多数子页面（铁匠铺/圣物/英雄详情/活动详情）都能一步步退。
                # 2026-11-06：改用 _try_tap（expect="none"），保证点击真的发出去——
                # 旧代码走 press(expect="change")，一旦该键被死点表拦住就一次点击都不发，
                # 后面的 diff 比较自然全是 0，误判成「BACK 无效」。
                before = self._frame()
                moved = self._try_tap(L.BACK, 250, "back_probe")
                shot = self.screen("hard_post")
                st2 = self.state(shot)
                diff = vision.diff_ratio(before, shot)
                if not moved:
                    # 整屏几乎没动：BACK 对这个页面无效。可能只是加载中，先等一拍再看。
                    time.sleep(1.4)
                    shot = self.screen("hard_post2")
                    st2 = self.state(shot)
                    moved = st2 != st or vision.diff_ratio(before, shot) >= 0.002
                if not moved:
                    self._stuck_backs = getattr(self, "_stuck_backs", 0) + 1
                    log.warn(f"  BACK 无效：整屏 diff={diff:.4f}（第 {self._stuck_backs} 次）")
                    # 一次就够——别把 14 次 tries 全耗在同一个死页面上。
                    if self._escape_unknown():
                        self._stuck_backs = 0
                        self._unknown_backs = 0
                        continue
                    self._save_stuck(shot)
                    log.warn("  该页面没有可用出口，立即放弃回主城（不再耗完 tries）")
                    return False
                self._stuck_backs = 0
                if st2 == State.MAIN_CITY:
                    log.arrived("main", time.time() - t0)
                    return True
                if st2 == State.QUIT_DIALOG:
                    self.press(L.QUIT_CANCEL, 180)
                    time.sleep(0.9)
                    log.info(f"  已在主城根节点（{i + 1} 步）")
                    log.arrived("main", time.time() - t0)
                    return True
                if st2 == st:
                    self._unknown_backs = getattr(self, "_unknown_backs", 0) + 1
                    if self._unknown_backs >= 2 and self._find_close_buttons(self.screen("unknown")):
                        self.close_promo()
                        self._unknown_backs = 0
                else:
                    self._unknown_backs = 0
                continue
            # 结算页先点掉
            if st in (State.RESULT_TOWER, State.RESULT_TREE, State.RESULT_LEGEND,
                      State.RESULT_GENERIC, State.RESULT_DEFEAT):
                pos = {
                    State.RESULT_TOWER: L.TOWER_RESULT_OK,
                    State.RESULT_TREE: L.TREE_RESULT_OK,
                    State.RESULT_LEGEND: L.LEGEND_RESULT_OK,
                    State.RESULT_GENERIC: (370, 1130),
                    State.RESULT_DEFEAT: (235, 1055),   # 失败页的「确定」，点空白关不掉
                }[st]
                if st == State.RESULT_DEFEAT:
                    # 塔失败页「确定」在左 (235,1055)，时光之树失败页「确定」在正中 (360,1060)
                    shot = self.screen("defeat")
                    pos = (360, 1060) if vision.is_gold(shot, 360, 1060, r=16) else pos
                self.press(pos, 220)
                time.sleep(1.6)
                continue
            if st == State.UNKNOWN:
                # 2026-11-10：结算面板压在活动页上时 BACK 完全无效，先按面板出口走。
                pos = self._result_panel_ok(self.screen("main_result_panel"))
                if pos is not None:
                    log.info(f"  结算面板：点 {pos} 关掉，继续回主城")
                    self.press(pos, 220, label="main_result_panel_ok", expect="none")
                    time.sleep(1.5)
                    continue
                        # 兜底：其它状态（部署/战斗/各种子页面）——按左下返回箭头，下一轮再判状态。
            # 用 expect="none"：这里不校验单点命中，靠随后的 state() 判断有没有退出去，
            # 免得 BACK 在某个页面上无效时被登记成死点、之后连点都不发了。
            self.press(L.BACK, 250, label="back", expect="none")
            time.sleep(1.3)
            st = self.state()
            if st == State.QUIT_DIALOG:
                self.press(L.QUIT_CANCEL, 180)
                time.sleep(0.9)
                log.info(f"  已在主城根节点（{i + 1} 步）")
                log.arrived("main", time.time() - t0)
                return True
            if st == State.MAIN_CITY:
                log.info(f"  回到主城（{i + 1} 步）")
                log.arrived("main", time.time() - t0)
                return True
        log.warn("没能回到主城")
        return False

    # ---------- 硬页面出口（2026-11-05） ----------
    def _try_tap(self, pos, ms: int = 260, label: str = "hard") -> bool:
        """硬页面单点试探：不看预期状态，只看整屏 diff 有没有动。"""
        before = self.screen(f"{label}_pre")
        self.press((int(pos[0]), int(pos[1])), ms, label, expect="none")
        time.sleep(1.2)
        after = self.screen(f"{label}_post")
        diff = vision.diff_ratio(before, after)
        log.info(f"  硬页面试探 {label} ({int(pos[0])},{int(pos[1])}) diff={diff:.4f} "
                 f"{'动了' if diff >= 0.002 else '没动'}")
        return diff >= 0.002

    def _result_panel_ok(self, im):
        """战斗结算面板的出口：返回左侧「确定」的坐标，判不出来返回 None。

        2026-11-10：树的「挑战成功 / 当前战斗：… / 本次造成伤害 / 作战奖励 ×N」面板压在
        活动页上，classify=UNKNOWN、modal_dim=True，BACK 整屏 diff≈0.002 关不掉 —— 那一次
        连续两个任务「回不到主城」，scheduler 直接中止整轮（22/39）。
        出口取法：先 OCR 找左「确定」（塔 235 / 竞技 250 / 树 224 / 副本 360，位置各不相同，
        绝不能硬编码 x）；面板里没有「确定」时退而点行内金色钮（「返回玩法 / 下一关」是安全出口，
        绝不点「再次挑战」——那种钮不会出现在这种结算面板里，真出现也已被关键字拦住）。
        """
        if not vision.modal_dim(im):
            return None
        try:
            txt = textocr.read_text(im, L.RESULT_PANEL_MID)
        except Exception:  # noqa: BLE001
            return None
        if not any(k in txt for k in L.RESULT_PANEL_KEYS):
            return None
        try:
            for t, c, _bb, _s in textocr.read_lines(im, L.RESULT_PANEL_BTN_ROW, min_score=0.5):
                if "确定" in t:
                    return tuple(c)
        except Exception:  # noqa: BLE001
            pass
        bands = vision.gold_bands_any(im, L.RESULT_PANEL_BTN_ROW)
        return tuple(bands[0][:2]) if bands else None

    def _reconnect_lost(self, im=None, tries: int = 2) -> bool:
        """战中断线弹窗：「您与游戏世界已失去连接」→ 点「继续重连」留在战斗里。"""
        if not textocr.available():
            return False
        shot = im if im is not None else self.screen("lost_conn")
        try:
            txt = textocr.read_text(shot, L.RECONNECT_LOST_BOX)
        except Exception:
            return False
        if not any(k in txt for k in L.RECONNECT_LOST_KEYS):
            return False
        pos = None
        try:
            for t, c, _bb, _s in textocr.read_lines(
                    shot, L.RECONNECT_LOST_BTN_ROW, min_score=0.4):
                if "继续重连" in t or "重连" in t:
                    pos = c
                    break
        except Exception:
            pos = None
        if pos is None:
            pos = L.RECONNECT_LOST_RETRY
        log.info(f"  战中断线：点「继续重连」{pos}，不回登录页")
        self.press(pos, 220, label="lost_conn_retry", expect="none")
        time.sleep(4.0)
        return True

    def _escape_unknown(self) -> bool:
        if self._reconnect_lost():
            return True
        """UNKNOWN 页面的多出口脱困链（2026-11-06 重写，替代旧的 _exit_hard_page）。

        顺序按「命中率高、代价小」排：
          1. 召唤结果页的「返回」；
          2. 底部米色大按钮（公告/结算类全屏页）；
          3. 右上红 X（促销/活动弹窗）；
          4. 底部导航条的「主城」页签（一级页被更早的判据漏掉时）；
          5. 点几个空白处（教遮罩层）。
        一律用 expect="none" 单点试探，靠整屏 diff 判断动没动；任一出口让画面变化
        就返回 True，交给调用方重新判状态。
        """
        shot = self.screen("escape_pre")
        if shot.width > shot.height:
            log.warn("  横屏画面：不按竖屏坐标乱点（模拟器被其它脚本占用）")
            return False
        if self._codex_open(shot) and self._try_tap(L.SOUL_CODEX_EXIT, 260, "esc_codex"):
            return True
        pos = self._result_panel_ok(shot)
        if pos is not None and self._try_tap(pos, 220, "esc_result_panel"):
            return True
        if vision.summon_result(shot) and self._try_tap(L.SUMMON_BACK, 260, "esc_summon"):
            return True
        if self._rank_page_open(shot) and self._try_tap(L.TAB_MAIN, 220, "esc_rank_tab"):
            return True
        if self._detail_page_open(shot) and self._try_tap(L.BACK, 240, "esc_subpage_back"):
            return True
        beige = vision.find_beige_button(shot)
        if beige and self._try_tap(beige, 260, "esc_beige"):
            return True
        for cx, cy in self._find_close_buttons(shot)[:2]:
            if self._try_tap((cx, cy), 160, "esc_redx"):
                return True
        if vision.navigation_bar(shot) and self._try_tap(L.TAB_MAIN, 220, "esc_nav"):
            return True
        for pos in L.POPUP_BLANKS[:4]:
            # 2026-11-09：先确认那一点当前不是金色按钮 —— 弹窗的「确定 / 购买」
            # 经常正压在这些空白点上，误击会真扣钻石。
            if vision.is_gold(shot, pos[0], pos[1], r=18):
                log.debug(f"  空白点 {pos} 当前是金色按钮，跳过（不误点确定/购买）")
                continue
            if self._try_tap(pos, 200, "esc_blank"):
                return True
        # 2026-11-11：最后退路 —— 底部「主城」页签。它不花钻石、不改数据，
        # 是一级/详情页被上面所有判据漏掉时唯一真正的出口（实测神器详情页就是它救回来的）。
        if self._try_tap(L.TAB_MAIN, 240, "esc_tab_main"):
            return True
        return False

    def _detail_page_open(self, im) -> bool:
        """是不是「详情/子页」整屏（不是弹窗、也不是一级页）。

        2026-11-11：神器详情页会写「重置预览 / 专武共鸣中，无法重置 / 神器共鸣中，无法升级 / 设为支柱」，
        classify 认成 UNKNOWN；这类页的出口是返回键（点一下先关掉叠在上面的子面板）。
        """
        try:
            from . import textocr
            if not textocr.available():
                return False
            txt = textocr.read_text(im, L.DETAIL_PAGE_OCR_BOX)
        except Exception:      # noqa: BLE001
            return False
        return any(k in txt for k in L.DETAIL_PAGE_KEYS)

    def _rank_page_open(self, im) -> bool:
        """是不是排行榜整页（列表页或某个榜单页）。

        2026-11-11 第 49 轮：启动时停在「排行榜·跨服」整屏页，classify 认成 UNKNOWN，
        脱困链的「米色大按钮」在那里点一下（diff 0.57 假装动了）却没有出口 →
        连点 50 多次后登录超时、整轮 0 任务。这页的真出口是底部「主城」页签。
        """
        try:
            from . import textocr
            if not textocr.available():
                return False
            txt = textocr.read_text(im, L.RANK_PAGE_OCR_BOX)
        except Exception:      # noqa: BLE001
            return False
        return any(k in txt for k in L.RANK_PAGE_KEYS)

    def _codex_open(self, im) -> bool:
        """是不是罪魂之域的「秘典」页（2026-11-10：这页会卡死启动流程）。"""
        try:
            from . import textocr
            if not textocr.available():
                return False
            txt = textocr.read_text(im, L.SOUL_CODEX_HEAD_BOX)
        except Exception:      # noqa: BLE001
            return False
        return any(k in txt for k in L.SOUL_CODEX_KEYS)

    @staticmethod
    def _save_stuck(im: Image.Image) -> str:
        p = ROOT / "logs" / f"stuck_{time.strftime('%Y%m%d_%H%M%S')}.png"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            im.save(p)
            log.warn(f"  卡死证据已存：{p}")
        except OSError:
            pass
        return str(p)

    def goto_tab(self, tab: tuple[int, int], splash: State | None = None) -> bool:
        self.press(tab, 250)
        time.sleep(1.8)
        if splash is not None:
            return self.state() == splash
        return True

    # ---------- 登录流程 ----------
    def login(self, timeout: int = 300) -> bool:
        """从任意/登录页进入主城：处理公告、标题页、登录弹窗、活动页。"""
        t0 = time.time()
        log.goto("boot")
        deadline = time.time() + timeout
        claimed = 0
        while time.time() < deadline:
            if self.dev.focus_pkg() != self.dev.pkg:
                log.warn(f"前台是 {self.dev.focus_pkg() or '未知'}，重新拉起游戏")
                self.dev.launch()
                time.sleep(3)
                continue
            im = self.screen("boot")
            if im.width > im.height:            # 被别的应用（比如阴阳师）占用
                self.dev.launch()
                time.sleep(4)
                continue
            st = vision.classify(im)
            if st != self._last_state:
                self._last_state = st
                log.ui(st.value)
            if st != State.UNKNOWN:
                self._boot_unknown = 0
            if st == State.MAIN_CITY:
                log.arrived("main", time.time() - t0)
                return True
            if st == State.NAV_PAGE:
                # 启动后停在一级页（英雄/助阵/战役…）：点「主城」页签即可，别按 BACK
                self.press(L.TAB_MAIN, 220, label="boot_nav_home", expect="none")
                time.sleep(1.6)
                continue
            if st == State.QUIT_DIALOG:
                self.press(L.QUIT_CANCEL, 180)
                time.sleep(0.9)
                continue
            if st == State.RECONNECT:
                self.press(L.RECONNECT, 200)
                time.sleep(3)
                continue
            if st == State.RECONNECT_LOGIN:
                self.press(L.RECONNECT_LOGIN_OK, 200)
                time.sleep(2.5)
                continue
            if st == State.TITLE:
                if not self._looks_like_title_start(im):
                    log.info(f"  画面被误判成标题页（按钮文字是「{self._title_start_text(im)[:16]}」），"
                             f"改按返回钮，不点「开始游戏」")
                    self.press(L.BACK, 220, label="title_misjudge_back", expect="none")
                    time.sleep(1.6)
                    continue
                R, G, B = vision.avg(im, *L.TITLE_AGREE, r=12)
                if not (G > 110 and G - R > 45 and G - B > 35):
                    self.press(L.TITLE_AGREE, 180)
                    time.sleep(0.8)
                self.press(L.TITLE_START, 220)
                time.sleep(3)
                continue
            if st in (State.DEPLOY, State.BATTLE):
                # 2026-11-10：上一轮如果停在布阵/战斗页（例如邪能失败后退回布阵），
                # 启动时这里既不是主城也不是「未知画面」，旧兜底只在 (60,150)/(670,150)
                # 两个促销关闭点上循环，5 分钟都出不来（真实案例：02:33 卡到「登录超时」）。
                back_n = getattr(self, "_boot_back", 0) + 1
                self._boot_back = back_n
                if back_n <= 2:
                    log.info(f"  启动时游戏停在{st.value}（上一轮残留的战斗页面），按返回键退出")
                    self.press(L.BACK, 220, expect="none")
                else:
                    # 2026-11-10 实测：角斗场「阵容/布阵」页对左下返回箭头和系统返回键都无反应
                    # （(88,1205) diff=0.001、keyevent 4 无效），只有底部「主城」页签能离开。
                    log.info(f"  启动时游戏停在{st.value}，返回键点不动，改点底部「主城」页签")
                    self.press(L.TAB_MAIN, 220, expect="none")
                time.sleep(2.0)
                continue
            if st in (State.RESULT_TOWER, State.RESULT_TREE, State.RESULT_LEGEND,
                      State.RESULT_GENERIC, State.RESULT_DEFEAT, State.SUMMON_RESULT):
                log.info(f"  启动时游戏停在结算页（{st.value}），先关掉它")
                if not self.handle_interruptions():
                    self._escape_unknown()
                time.sleep(1.6)
                continue
            if st == State.MAIN_CITY_DIM or st == State.DIALOG:
                if claimed < 2 and vision.is_gold(im, *L.LOGIN_CLAIM, r=16):
                    self.press(L.LOGIN_CLAIM, 220)
                    claimed += 1
                    time.sleep(2)
                    continue
                self.close_popup(im)
                continue
            # 全屏活动页：底部亮米色栏，用左下返回箭头退出
            R, G, B = vision.avg(im, 110, 1225, r=8)
            if R > 200 and G > 180:
                self.press(L.BACK, 220, expect="none")
                time.sleep(1.5)
                continue
            # 兜底：未知画面（全屏促销/广告/加载）——红 X、猜测点、返回箭头都试
            unknown = getattr(self, "_boot_unknown", 0) + 1
            self._boot_unknown = unknown
            if unknown % 2 == 1 and self._escape_unknown():
                # 2026-11-10：秘典/秘典类整屏页只有专门出口能退，促销兜底点不出来
                log.info("  启动时停在未知整屏页，已用脱困链退出")
                time.sleep(1.2)
                continue
            if unknown % 2 == 0:
                log.warn(f"未知画面（第 {unknown} 次），尝试关闭促销页")
                self.close_promo()
            else:
                for pos in L.POPUP_BLANKS[:2]:
                    self.press(pos, 150, label="boot_blank", expect="none")
                    time.sleep(0.6)
            time.sleep(1.5)
        log.warn("登录超时")
        return False

    def start_app(self, cold: bool = False) -> bool:
        if cold:
            self.dev.stop()
        self.dev.launch()
        return self.login()
