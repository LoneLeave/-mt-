"""地精宝藏：先统计第 1~10 层的物资，再统一决定占领哪些矿（2026-10-30 改版）。

用户规则（本轮更新）：
- 只看第 1~10 层；
- **先把前十层的物资统计完，再判断去占领哪些**（原来是一边扫一边占，先占到的
  低价值矿会占掉名额）；
- 占领前要判断当前剩余队伍（顶部「空闲中」气泡），没有空闲队伍就收手；
- 层级优先级：进阶石（等级高优先）> 钻石（等级高优先）> 其他；
- 能不能占只看面板按钮：有「掠夺」= 别的玩家占着，不抢；没有「占领」= 同公会占着；
  只有「占领」= 系统守军/空矿，可以占（要打一场）。

新矿洞界面（实测）：
- 一屏两列、每列 5 格，格子由「资源气泡图标 + 等级徽章 + 资源堆」组成；
- 等级徽章颜色：金/橙=5、紫=4、蓝=3/2/1；资源气泡按颜色区分 进阶石(紫)/钻石(蓝)/金币/火；
- 左下「第N层」标签要 400ms 长按才展开层列表（250ms 点不开——旧版层数切换失效的原因）；
- 顶部四个队伍位（4 队要特权解锁），空闲的显示米色「空闲中」气泡。
"""

from __future__ import annotations

import re
import time

from .. import layout as L
from .. import log, vision
from .. import template as T
from ..pages import MainCity
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult

HEADER = "标题_地精宝藏.png"
ADV_STONE = "地精_进阶石.png"
DIAMOND = "地精_钻石.png"
GUARD = "地精_守军.png"
OCCUPY = "地精_占领.png"
ROB = "地精_掠夺.png"
NO_TEAM = "地精_无空闲队伍.png"
BACK_PLAY = "返回玩法.png"

PANEL_CLOSE = (650, 208)
OCCUPY_FALLBACK = (352, 1024)
MAX_LAYERS = 10
PROBE_LIMIT = 10

_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_layer(text: str) -> int:
    """从「第六层 …」里取层号；「第十层」按两字处理。读不到返回 -1。"""
    m = re.search(r"第\s*([一二三四五六七八九十]+)\s*层", text or "")
    if not m:
        return -1
    word = m.group(1)
    if word.startswith("十"):
        rest = word[1:]
        return 10 + _CN_DIGITS.get(rest, 0) if rest else 10
    return _CN_DIGITS.get(word[:1], -1)


class GoblinTask(BaseTask):
    name = "goblin"
    title = "地精宝藏"
    category = "combat"

    # ---------- 识别小工具 ----------
    @staticmethod
    def _find(im, name, threshold=0.85, roi=None):
        return T.VI.find(im, name, threshold=threshold, roi=roi)

    def _at_goblin(self, ui) -> bool:
        return self._find(ui.screen("gob_at"), HEADER, 0.90) is not None

    @staticmethod
    def _idle_teams(im) -> int:
        """顶部「空闲中」气泡数量（米色圆角气泡，实测 (195~201, 171~177, 135~140)）。"""
        n = 0
        for pos in L.GOB_TEAMS:
            R, G, B = vision.avg(im, *pos, r=12)
            if R > 170 and G > 148 and B > 118:
                n += 1
        return n

    # ---------- 开战时间窗 ----------
    # 2026-11-06 实测（23:02）：面板顶部写着「开战时间：10点-22点」，此时点「占领」
    # 按钮照样有按下动画（diff 0.0298 后回落），但 0.3 秒后弹一个 toast
    # 「当前处于休赛期，无法占领」（中心 (352,349)，约 0.7 秒消失），战斗根本不开始。
    # 旧逻辑把「按钮还在」当成「点了没生效」，连按 4 次白等 8 秒再换下一个矿，
    # 十层 162 个候选全走一遍要 20 分钟，最后还报「占领 0 个」的成功结果。
    @staticmethod
    def _time_window(im):
        """读「开战时间：10点-22点」→ (10, 22)；读不到返回 None。"""
        from .. import textocr
        if not textocr.available():
            return None
        return textocr.read_time_window(textocr.read_text(im, L.GOB_WINDOW_TEXT))

    @staticmethod
    def _closed_toast(im) -> bool:
        """画面上有没有「休赛期 / 无法占领」这类拒绝提示。"""
        from .. import textocr
        if not textocr.available():
            return False
        text = textocr.read_text(im, L.GOB_TOAST_ROI)
        return any(k in text for k in L.GOB_CLOSED_KEYS)

    @staticmethod
    def _hour(ui) -> int:
        """设备当前小时（0~23）：窗口判断必须用设备时间，不是本机时间。"""
        try:
            h = int(ui.dev.shell("date +%H").strip())
            if 0 <= h <= 23:
                return h
        except Exception:
            pass
        return time.localtime().tm_hour

    def _window_closed(self, ui, im=None, log_it: bool = True) -> bool:
        """当前是否在休赛期（开战窗口外）。读不到时间窗时按「开着」处理。"""
        im = im or ui.screen("gob_window")
        win = self._time_window(im)
        if not win:
            return False
        start, end = win
        hour = self._hour(ui)
        if start <= end:
            inside = start <= hour < end
        else:                     # 跨零点（如 22点-2点）
            inside = hour >= start or hour < end
        if not inside and log_it:
            log.info(f"  地精宝藏：当前 {hour} 点，不在开战时间（{start}点-{end}点），"
                     f"此时点「占领」只会弹「休赛期」提示")
        return not inside

    def _close_report(self, ui) -> bool:
        """关掉进入时弹出的「防守失败」战报弹窗。

        2026-11-04 实测（f0005）：一进地精宝藏就弹这块无 X 的战报面板，整屏被压暗 60%，
        顶部「空闲中」气泡从 (195,171,138) 降到 (59,52,41) → `_idle_teams` 读成 0，
        任务直接「没有空闲队伍」提前收手。弹窗右侧是空白地图，点那里即可关闭。
        """
        for _ in range(3):
            im = ui.screen("gob_report")
            if self._find(im, "地精_战报弹窗.png", 0.88) is None:
                return True
            log.info("  地精宝藏：关掉「防守失败」战报弹窗")
            ui.press((690, 470), 150, expect="none")
            ui.wait(1.4)
        return self._find(ui.screen("gob_report2"), "地精_战报弹窗.png", 0.88) is None

    # ---------- 进出 ----------
    def _enter(self, ui) -> bool:
        for attempt in range(2):
            if self._at_goblin(ui):
                self._close_report(ui)
                return True
            MainCity(ui).tab(L.TAB_TRIAL)
            for _ in range(3):
                ui.dev.scroll_down(360, 250, 1000, 500)
                ui.wait(0.5)
            for _ in range(6):
                im = ui.screen("gob_hub")
                m = self._find(im, "历练_地精宝藏.png", 0.88)
                if m:
                    ui.press(m.center, 250)
                    ui.wait(2.8)
                    if self._at_goblin(ui):
                        self._close_report(ui)
                        log.info("  已进入地精宝藏")
                        return True
                ui.dev.scroll_up(360, 1000, 250, 600)
                ui.wait(0.8)
            if attempt == 0:
                log.warn("  没看到地精宝藏入口，回主城后重试一次")
                MainCity(ui).ensure()
                ui.wait(0.6)
        log.warn("  在历练页没找到地精宝藏入口")
        return False

    # ---------- 层数 ----------
    @staticmethod
    def _layer_tpls() -> list[str]:
        return [f"层名_{i}.png" for i in range(1, MAX_LAYERS + 1)
                if (T.ROOT / "templates" / f"层名_{i}.png").exists()]

    def _layer_list_open(self, ui, tag="gob_list") -> bool:
        im = ui.screen(tag)
        return any(self._find(im, t, 0.85, roi=L.GOB_LAYER_LIST_ROI)
                   for t in self._layer_tpls())

    def _open_layer_list(self, ui, tpls=None) -> bool:
        for _ in range(3):
            if self._layer_list_open(ui):
                return True
            # 250ms 点不开（实测），必须 400ms；这个标签是开关，按一次就翻转
            ui.press(L.GOB_LAYER_LABEL, 420, expect="none")
            ui.wait(1.4)
        return self._layer_list_open(ui, "gob_list2")

    def _close_layer_list(self, ui) -> bool:
        if self._layer_list_open(ui, "gob_list_close"):
            ui.press(L.GOB_LAYER_LABEL, 420, expect="none")
            ui.wait(1.1)
        return not self._layer_list_open(ui, "gob_list_closed")

    def _goto_layer(self, ui, n: int) -> bool:
        """切到第 n 层，并复核真的切过去了。

        2026-11-07 实测（探针 `logs\\_gob_layer2.py` / `_gob_layer3.py`）：
        ① 旧版 n<=6 走固定行坐标 `GOB_LAYER_ROWS[n-1]`，列表位置差几像素就点错
           相邻行——`goto_layer(3)` 实际停在「第二层」，直接点第 2/6 行分别落在
           第 1/5 层。后果是十层扫描里有层扫两遍、有层从没扫到，日志照样报
           「第 N 层 16 个点」，占领时 `_goto_cell` 用同一个函数也同样跑偏。
        ② 也不能只靠模板：列表里同时出现 6 行，`层名_1.png` 峰值只有 0.808
           （低于 0.88 阈值）→ `goto_layer(1)` 一路滚到底再失败；`层名_7~10` 在
           列表没滚到时还会拿 0.82 的假峰。
        现在：**先用 OCR 读列表里的「第N层」文字**（实测 1.00 置信度、行中心
        810/862/915/967/1019/1067），点该行；点完用左下角「第N层」标签复核，
        不匹配就重开列表重试。

        2026-11-07 15:40 再实测（探针 `logs\\_gob_scrolleffect.py` /
        `_gob_scrollsafe.py` / `_gob_swipesem.py`）：层列表是**滚动视图**（共 21+ 层，
        一屏只显示 6 行），且
        ① 只要列表已到顶，「向下拖」（`swipe(150,850,150,1060)`）就退化成一次
           点击，会**把层切到第二层并把列表关掉**。旧版点行前先跑 4 次这种下滑，
           于是每次切层都先把自己切走、列表关掉，随后 OCR 在地图上找不到行、
           复核永远失败 → 3 次重试 ×「重开列表再滚」→ 19:59 那次空转 33 分钟只占领 2 个。
        ② 真正能翻页的是「向上拖」`swipe(150,1060,150,850)`（手指上滑 = 看更后面的层），
           且**重开列表不会回到顶部**（滚动位置保留）。
        所以现在：不预滚动；目标行就在当前六行里就点它，不在且目标号更大才上滑翻页，
        翻页丢帧/翻不动就立刻收手，全程 24 秒额度。
        """
        tpls = self._layer_tpls()
        t0 = time.time()
        budget = 24.0
        pages = 0
        for attempt in range(4):
            if time.time() - t0 > budget:
                log.info(f"  切第 {n} 层超时（{budget:.0f}s），先不切了")
                break
            if not self._open_layer_list(ui, tpls):
                log.warn("  层级下拉列表打不开")
                return False
            rows = self._layer_rows(ui)
            hit = [r for r in rows if r[0] == n]
            if not hit:
                # 目标不在这六行里：只在「目标号更大」时上滑翻页；
                # 反方向的下滑在列表到顶时会变成「点第二层」，会把层切走并关掉列表。
                if rows and n > max(r[0] for r in rows) and pages < 6:
                    pages += 1
                    before = [r[0] for r in rows]
                    ui.dev.swipe(150, 1060, 150, 850, 450)
                    ui.wait(0.9)
                    after = [r[0] for r in self._layer_rows(ui, "gob_layer_pg")]
                    if not after or after == before:
                        log.info(f"  层列表翻不动了（可见 {before}），没有第 {n} 层")
                        break
                    continue
                # 目标比当前可见的还小：列表没在顶部时，向下拖才等于往回翻
                # （已在顶部时向下拖 = 点第二层，所以必须先判 min > 1）。
                if rows and n < min(r[0] for r in rows) and min(r[0] for r in rows) > 1 and pages < 6:
                    pages += 1
                    before = [r[0] for r in rows]
                    ui.dev.swipe(150, 850, 150, 1060, 450)
                    ui.wait(0.9)
                    after = [r[0] for r in self._layer_rows(ui, "gob_layer_bk")]
                    if not after or after == before:
                        log.info(f"  层列表翻不动了（可见 {before}），没有第 {n} 层")
                        break
                    continue
                log.info(f"  层列表里没有第 {n} 层（可见 {[r[0] for r in rows]}）")
                break
            _num, x, y = hit[0]
            ui.press((x, y), 240, expect="none")
            ui.wait(1.5)
            now = self._layer_now(ui)
            if now in (-1, n):
                return True
            log.info(f"  点 ({x},{y}) 想切第 {n} 层，左下读到第 {now} 层，重试")
            pages = 0
        self._close_layer_list(ui)
        log.warn(f"  列表里没切换到第 {n} 层")
        return False

    def _layer_rows(self, ui, tag="gob_layer_rows") -> list:
        """读已展开的层列表 → [(层号, x, y)]（实测一屏 6 行、文字置信度 1.0）。"""
        from .. import textocr
        if not textocr.available():
            return []
        im = ui.screen(tag)
        rows = []
        for text, center, _bb, _sc in textocr.read_lines(
                im, L.GOB_LAYER_LIST_ROI, min_score=0.5):
            num = _cn_layer(text)
            if num > 0:
                rows.append((num, int(center[0]), int(center[1])))
        return rows

    @staticmethod
    def _layer_now(ui) -> int:
        """读左下「第N层」标签 → N（读不到返回 -1，不参与判断）。"""
        from .. import textocr
        if not textocr.available():
            return -1
        text = textocr.read_text(ui.screen("gob_cur_layer"), (60, 1060, 430, 1160))
        return _cn_layer(text)

    # ---------- 物资统计 ----------
    # 矿格布局（2026-10-30 实测）：资源气泡 + 等级徽章在格子上半部，
    # 可点的资源堆在格子左下/右下；徽章颜色 = 资源等级档（橙>紫>蓝）。
    ROW_SCAN_X = (270, 455)          # 左右两列等级徽章的中心 x
    BUBBLE_X = (150, 545)            # 左右两列资源气泡中心 x
    PILE_X = (95, 640)               # 左右两列资源堆的点击 x（相对徽章行 +90px）

    @classmethod
    def _badge_rows(cls, im) -> list[int]:
        """找等级徽章所在的行（一屏 4~5 行，滚动后位置会变）。"""
        hits = []
        for y in range(340, 1110, 6):
            for x in cls.ROW_SCAN_X:
                R, G, B = vision.avg(im, x, y, r=8, step=2)
                if (R + G + B) > 260 and (B > 115 or (R > 150 and G > 85)):
                    hits.append(y)
                    break
        rows: list[int] = []
        for y in hits:
            if rows and y - rows[-1] <= 30:
                continue
            rows.append(y + 14)      # 命中在徽章上沿，往回收一点
        return rows

    @staticmethod
    def _kind(im, x: int, y: int) -> int:
        """资源气泡颜色：2=进阶石(紫) 1=钻石(蓝) 0=金币/火焰/药水等其它。"""
        R, G, B = vision.avg(im, x, y, r=14, step=2)
        if B > 150 and (B - G) > 12 and R > 128 and (R - G) > 0:   # 紫
            return 2
        if B > 150 and (B - R) > 50 and R < 130:                    # 蓝
            return 1
        return 0

    @staticmethod
    def _level(im, x: int, y: int) -> int:
        """徽章颜色：金/橙=3、紫=2、蓝=1。"""
        R, G, B = vision.avg(im, x, y, r=8, step=2)
        if R > 170 and G > 100 and B < 110:
            return 3
        if R > 110 and B > 150 and (B - G) > 15:
            return 2
        return 1

    @classmethod
    def _scan_screen(cls, im) -> list[tuple[int, int, int, int]]:
        """返回当前画面 [(kind, level, x, y)]，坐标是资源堆的点击点。"""
        out = []
        for y in cls._badge_rows(im):
            if not (360 <= y <= 1140):
                continue
            for i in (0, 1):
                bx = cls.BUBBLE_X[i]
                k = cls._kind(im, bx, y)
                lv = cls._level(im, cls.ROW_SCAN_X[i], y)
                out.append((k, lv, cls.PILE_X[i], min(y + 90, 1150)))
        return out

    def _scan_layer(self, ui, n: int) -> list[tuple[int, int, int, int, int]]:
        """扫一层的两屏，返回 [(kind, level, page, x, y)]（page=0 顶屏 / 1 下翻一屏）。"""
        if not self._goto_layer(ui, n):
            return []
        for _ in range(3):           # 层内滚回顶部
            ui.dev.scroll_down(360, 300, 900, 500)
            ui.wait(0.4)
        cands = []
        for page in (0, 1):
            im = ui.screen("gob_scan")
            for k, lv, x, y in self._scan_screen(im):
                cands.append((k, lv, page, x, y))
            if page == 0:
                ui.dev.scroll_up(360, 1000, 700, 500)
                ui.wait(0.6)
        return cands

    # ---------- 占领 ----------
    def _battle(self, ui) -> str:
        pressed_auto = False
        started = False
        t0 = time.time()
        while time.time() - t0 < 300:
            im = ui.screen("gob_battle")
            if self._find(im, "胜利.png", 0.85) or self._find(im, "结算界面.png", 0.85):
                return "win"
            if self._find(im, "失败.png", 0.85):
                return "lose"
            if not pressed_auto:
                m = self._find(im, "一键上阵.png", 0.85, roi=(180, 1155, 420, 1260))
                if m:
                    started = True
                    # 「一键上阵」点了不改变画面（只是把英雄摆上去）：
                    # 2026-11-07 实测用变化校验会连续 3 次 MISS、白做 4 个补偿点、
                    # 最后还被登记成死点（把后面两次占领的布阵也带成空点）。
                    ui.press(m.center, 200, expect="none")
                    pressed_auto = True
                    ui.wait(1.0)
                    continue
            m = self._find(im, "战斗按钮.png", 0.85, roi=(460, 1155, 710, 1260))
            if m:
                started = True
                # 2026-11-08 16:32 实机（logs\_full6_153708.log）：(567,1204) 点「战斗」
                # 时这局其实已经开打（上一帧的模板命中的是旧帧按钮位置），
                # 默认校验 → diff=0.000 → 4 个补偿点全空 → 白等 8 秒还记空点。
                # 开打是状态迁移，一律幂等点击。
                ui.press(m.center, 200, label="gob_fight", expect="none")
                ui.wait(4.0)
                continue
            m = self._find(im, OCCUPY, 0.88, roi=(400, 1140, 710, 1265))
            if m:
                started = True
                ui.press(m.center, 250)
                ui.wait(4.0)
                continue
            if self._find(im, NO_TEAM, 0.85):
                log.info("  暂无空闲队伍，无法占领 —— 收手")
                ui.press(PANEL_CLOSE, 150, expect="none")
                ui.wait(1.0)
                return "nofree"
            st = vision.classify(im)
            if st == State.BATTLE:
                started = True
                ui.battle_skip(im)      # 模板定位 + 阈值 0.60，未命中不盲点
                ui.wait(2.5)
                continue
            if st == State.DEPLOY:
                started = True
            if not started and time.time() - t0 > 20:
                log.info("  没进入战斗（占领可能没生效）")
                return "none"
            ui.wait(1.6)
        return "none"

    def _press_occupy(self, ui, pos, ms: int = 350) -> None:
        # 2026-11-08 实测（22:00 撞上休赛期）：占领按钮在休赛期照样是亮的、按下去
        # 也有按下动画，但整屏 diff 恒为 0.000 → 默认校验会白做 4 个补偿点、刷出
        # 9 条「空点」告警，还把坐标登记成死点。是否真的开打由后面的
        # _closed_toast / DEPLOY / 模板判据决定，所以这里只点不校验。
        ui.press(pos, ms, label="gob_occupy", expect="none")
        ui.wait(1.8)

    def _try_occupy(self, ui, x: int, y: int) -> str:
        # 2026-11-07 实测：矿点本身点了**就是不改变画面**（面板盖上来时整屏 diff
        # 只有 0.010~0.012），用默认校验会白做 4 个补偿点、刷「空点」告警，
        # 还把这个格子的坐标登记成死点。矿点是否有效由后面的模板判断。
        ui.press((x, y), 200, label=f"gob_cell:{x},{y}", expect="none")
        ui.wait(2.0)
        im = ui.screen("gob_panel")
        if self._find(im, ROB, 0.88):
            log.info("  有「掠夺」= 玩家占着的，不打")
            ui.press(PANEL_CLOSE, 150, expect="none")
            ui.wait(1.0)
            return "skip"
        m = self._find(im, OCCUPY, 0.88)
        if not m:
            log.info("  没有「占领」（同公会已占 / 已挖完），跳过")
            ui.press(PANEL_CLOSE, 150, expect="none")
            ui.wait(1.0)
            return "skip"
        has_guard = self._find(im, GUARD, 0.88) is not None
        log.info("  可以占（%s）" % ("有系统守军，要打一场" if has_guard else "空地"))

        self._press_occupy(ui, m.center)
        occupied = False
        for i in range(3):
            im2 = ui.screen("gob_occupy")
            if self._find(im2, NO_TEAM, 0.85):
                log.info("  暂无空闲队伍，无法占领 —— 收手")
                ui.press(PANEL_CLOSE, 150, expect="none")
                ui.wait(1.0)
                return "nofree"
            # 休赛期：按钮有按下动画，但游戏只弹 toast，战斗永远不开始。
            # 必须先判这条，否则会被当成「点了没生效」连按 4 次白等 8 秒。
            if self._closed_toast(im2):
                log.info("  休赛期：游戏拒绝占领（弹「当前处于休赛期，无法占领」），收手")
                ui.press(PANEL_CLOSE, 150, expect="none")
                ui.wait(1.0)
                return "closed"
            if vision.is_green(im2, *L.DEPLOY, r=18) or \
                    vision.classify(im2) == State.BATTLE:
                occupied = True
                break
            if not self._find(im2, OCCUPY, 0.88):
                occupied = True
                break
            log.info(f"  占领按钮没生效，重按（第 {i + 1} 次）")
            pos = (m.center if i == 0 else
                   OCCUPY_FALLBACK if i == 1 else (m.center[0], m.center[1] + 20))
            self._press_occupy(ui, pos)
        if not occupied:
            im3 = ui.screen("gob_occupy_stuck")
            if self._find(im3, NO_TEAM, 0.85):
                log.info("  暂无空闲队伍，无法占领 —— 收手")
                return "nofree"
            if self._closed_toast(im3):
                log.info("  休赛期：游戏拒绝占领，收手")
                return "closed"
            # 2026-11-08 实测（22:00）：跨过开战时间那一刻起，点「占领」只会让
            # 按钮闪一下（toast 只活 0.7 秒，OCR 常抓不到），于是逐个矿白试。
            # 这里用「设备时间 + 面板上的开战时间」再判一次，过了就整任务收手。
            if self._window_closed(ui, im3, log_it=False):
                log.info("  占领按钮连按 4 次都没反应，且已过开战时间（休赛期），收手")
                ui.press(PANEL_CLOSE, 150, expect="none")
                ui.wait(1.0)
                return "closed"
            log.info("  占领按钮连按 4 次都没反应，关掉换下一个矿")
            ui.press(PANEL_CLOSE, 150, expect="none")
            ui.wait(1.0)
            return "skip"

        result = self._battle(ui)
        log.info(f"  占领战斗：{result}")
        im_end = ui.screen("gob_end")
        m = self._find(im_end, BACK_PLAY, 0.85)
        if m:
            ui.press(m.center, 220)
            ui.wait(1.8)
        return result

    def _goto_cell(self, ui, layer: int, page: int) -> bool:
        """回到指定层的指定屏（0=顶部，1=下翻一屏）。"""
        if not self._goto_layer(ui, layer):
            log.info(f"  跳过第 {layer} 层：切不过去（占领名额留给别的层）")
            return False
        for _ in range(3):
            ui.dev.scroll_down(360, 300, 900, 500)
            ui.wait(0.4)
        if page == 1:
            ui.dev.scroll_up(360, 1000, 700, 500)
            ui.wait(0.7)
        return True

    def _count_idle(self, ui) -> int:
        """数顶部空闲队伍：像素判据 + OCR 交叉校验。

        2026-11-06 实测（22:37 那次）：刚进页面就取帧，像素判据读成「空闲 0」→
        任务直接「今天不占」收手；一分钟后同一页面 OCR 明明读到 3 个「空闲中」
        （(198,175)/(515,176)/(633,175)），像素 avg 也回到 (203,180,144)。
        所以：① 重试几次等画面画完；② OCR 说有几个就按几个算（像素只是兜底）。
        """
        from .. import textocr
        n = 0
        for i in range(3):
            im = ui.screen("gob_idle" if i else "gob_start")
            n = self._idle_teams(im)
            if n:
                return n
            if textocr.available():
                cnt = textocr.read_text(im, L.GOB_TEAM_BAR).count("空闲中")
                if cnt:
                    log.info(f"  地精宝藏：像素判空闲 0，OCR 读到 {cnt} 个「空闲中」，按 OCR 算")
                    return cnt
            if i < 2:
                ui.wait(1.2)
        return n

    # ---------- 主流程 ----------
    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        # 2026-11-11 用户 m19571「优先钻石和进阶石」：上限取「有多少空闲队伍就占多少」
        max_occupy = int(p.get("max_occupy", 9))
        layers = int(p.get("layers", MAX_LAYERS))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        if not self._enter(ui):
            MainCity(ui).ensure()
            return TaskResult.fail("进不去地精宝藏")

        idle = self._count_idle(ui)
        log.info(f"  地精宝藏：空闲队伍 {idle}")
        if idle <= 0:
            MainCity(ui).ensure()
            return TaskResult.skip("没有空闲队伍，今天不占")

        # 0) 休赛期直接收手：窗口外「占领」按钮是亮的、点下去有按下动画，
        #    但游戏只弹「当前处于休赛期，无法占领」，战斗永远不开始。
        #    这条判断必须放在十层扫描之前 —— 旧版先扫 3.5 分钟再逐个点空，
        #    每个矿白等 8 秒，最后还报「占领 0 个」的成功。
        win = self._time_window(ui.screen("gob_window"))
        if win and self._window_closed(ui, log_it=True):
            MainCity(ui).ensure()
            return TaskResult.skip(
                f"休赛期，开战时间 {win[0]}点-{win[1]}点（当前 {self._hour(ui)} 点）")

        # 1) 先统计前十层的物资
        found = []
        for layer in range(1, layers + 1):
            cands = self._scan_layer(ui, layer)
            found.extend((k, lv, layer, page, x, y) for k, lv, page, x, y in cands)
            log.info(f"  地精宝藏：第 {layer} 层统计到 {len(cands)} 个资源点")
        found.sort(key=lambda c: (-c[0], -c[1], c[2], c[3], c[4]))
        top = found[:10]
        names = {2: "进阶石", 1: "钻石"}
        log.info("  候选前 10（进阶石>钻石，同档按等级降序）：" + "，".join(
            f"第{c[2]}层{names.get(c[0], '其他')}Lv{c[1]}" for c in top))
        log.info(f"  地精宝藏：十层共 {len(found)} 个候选，按 进阶石>钻石>等级 依次尝试")

        # 2026-11-11 用户 m19571：只优先占「钻石 / 进阶石」两类；两类都没有才用其他
        prio = [c for c in found if c[0] in (1, 2)]
        others = [c for c in found if c[0] not in (1, 2)]
        if prio:
            log.info(f"  地精宝藏：钻石/进阶石候选 {len(prio)} 个（优先占这些；"
                     f"其他 {len(others)} 个只在没得占时兜底）")
            order = prio + others
        else:
            log.info("  地精宝藏：十层里没有钻石/进阶石矿，退而占其他资源")
            order = found

        # 2) 再按优先级占领
        occupied = 0
        idle = self._count_idle(ui)
        tried = 0
        deadline = time.time() + 40 * 60
        for k, lv, layer, page, x, y in order:
            if occupied >= min(max_occupy, idle):
                break
            if tried >= PROBE_LIMIT * 3 or time.time() > deadline:
                break
            tried += 1
            if not self._at_goblin(ui):
                self._enter(ui)
            if idle <= occupied:
                log.info("  空闲队伍用完了，停止占领")
                break
            if not self._goto_cell(ui, layer, page):
                continue
            kind_name = {2: "进阶石", 1: "钻石"}.get(k, "其他")
            log.info(f"  尝试：第 {layer} 层 {kind_name}（等级档 {lv}）({x},{y})")
            outcome = self._try_occupy(ui, x, y)
            if outcome == "closed":
                MainCity(ui).ensure()
                win = self._time_window(ui.screen("gob_win3")) or (10, 22)
                return TaskResult.skip(
                    f"休赛期，开战时间 {win[0]}点-{win[1]}点（当前 {self._hour(ui)} 点）")
            if outcome == "nofree":
                MainCity(ui).ensure()
                if occupied:
                    return TaskResult(True, f"地精宝藏：占领 {occupied} 个（队伍用完提前收手）",
                                      {"occupied": occupied})
                return TaskResult.fail("地精宝藏：一个矿都没占下来（空闲队伍在过程中用完）")
            if outcome in ("win", "lose"):
                # 打赢才算占下；打输这一队也派出去了，名额会从空闲队伍里扣
                if outcome == "win":
                    occupied += 1
                    log.info(f"  已占领 {occupied}/{max_occupy}")
                else:
                    log.info("  占领战斗失败")
                if not self._at_goblin(ui):
                    self._enter(ui)

        MainCity(ui).ensure()
        if occupied == 0:
            return TaskResult.fail(
                f"地精宝藏：扫了 {len(found)} 个点但一个都没占下来（{tried} 次尝试）")
        return TaskResult(True, f"地精宝藏：统计 {len(found)} 个点，占领 {occupied} 个",
                          {"occupied": occupied, "scanned": len(found)})
