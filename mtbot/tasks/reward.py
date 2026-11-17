"""奖励与提升类任务：邮件 / 军衔 / 好友 / 福利 / 战令 / 圣物 / 升星 /
装备 / 英雄 / 争霸赛。

这些界面大多没有独立的“页面类”，统一在主城里按图标进入、按金色扫描领奖；
进入/退出全部走 MainCity，失败也不影响下一个任务。
"""
from __future__ import annotations

import re
from collections import deque

from .. import layout as L
from .. import log, ocr, textocr, titles, vision
from ..pages import MainCity
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult


class _RewardTask(BaseTask):
    category = "reward"

    def enter(self, ctx: TaskContext, pos, wait: float = 1.6, page: str = ""):
        """点主城图标进入界面；如果画面还是主城（图标换位/活动下架）就放弃。

        给了 page（标题键，见 titles.TITLES）时还校验「真的进了目标页」：
        2026-11-07 实测主城「升星」老坐标 (190,770) 点到当期「累充」付费横幅上，
        进了活动面板；旧逻辑只判「不是主城」就当成功，于是整段在活动页上空跑
        （日志里表现为「批量升星 0 次」）。
        """
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return None
        ui.press(pos, 250)
        ui.wait(wait)
        im = ui.screen(self.name)
        if vision.classify(im) == State.MAIN_CITY:
            log.warn(f"  {self.name}: 入口没打开（图标可能换位），跳过本任务")
            return None
        if page and not titles.on_page(im, page):
            got = titles.identify(im) or "没认出来"
            log.warn(f"  {self.name}: 入口 {pos} 进的不是「{page}」页（标题识别：{got}），"
                     f"退回主城跳过本任务")
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.0)
            MainCity(ui).ensure()
            return None
        return im

    def back(self, ctx: TaskContext):
        ui = ctx.ui
        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()


class MailTask(_RewardTask):
    name = "mail"
    title = "邮件"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        im = self.enter(ctx, L.ICON_MAIL, 1.4)
        if im is None:
            return TaskResult.fail("回不到主城")
        claimed = 0
        stale = 0
        for _ in range(8):
            im = ui.screen("mail")
            if vision.is_gold(im, *L.MAIL_DETAIL, r=18):
                ui.press(L.MAIL_DETAIL, 220)
                ui.wait(1.2)
                continue
            # 2026-11-08：按钮中心随列表条数变化（实测 y=1044，旧常量 1015 落在上沿外，
            # 点下去整屏不动、4 个补偿点也够不到，白赔 8s）。改成按金色带质心点。
            bands = vision.gold_button_bands(im, L.MAIL_CLAIM_BOX)
            if not bands:
                break
            cx, cy, _w = bands[0]
            # expect="none"：这个按钮点完画面只换列表内容，diff 校验看不出、
            # 反而会白赔 8s；下面自己抓一帧复检按钮还在不在。
            ui.press((cx, cy), 220, label=f"mail_claim{claimed + 1}", expect="none")
            ui.wait(1.2)
            after = ui.screen("mail_after")
            toast = ""
            try:
                toast = textocr.read_text(after, L.MAIL_TOAST_BOX).strip()
            except Exception:  # noqa: BLE001
                toast = ""
            if any(k in toast for k in ("已无可领取", "没有可领取", "无可领取")):
                # 2026-11-09：「全部领取」是常驻金钮（没有可领邮件时也是金色），
                # 点完只会飘一句「已无可领取的邮件」。以前靠「按钮还在」猜，
                # 日志写「可能没有可领邮件」，容易被误读成脚本没点到。
                log.info(f"  邮件：游戏提示「{toast[:16]}」→ 现在没有可领的邮件（按钮是常驻金钮）")
                break
            if vision.gold_button_bands(after, L.MAIL_CLAIM_BOX):
                stale += 1
                if stale >= 2:
                    log.info("  邮件：「全部领取」点了两次都还在（可能没有可领邮件），停手")
                    break
                continue
            stale = 0
            claimed += 1
        ui.press(L.MAIL_CLOSE, 200, expect="none")
        ui.wait(0.9)
        MainCity(ui).ensure()
        return TaskResult(True, f"邮件领取 {claimed} 轮", {"rounds": claimed})


class RankTask(_RewardTask):
    name = "rank"
    title = "军衔"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = MainCity(ui).open_rank()
        rows = 0
        promoted = 0
        # 2026-11-03：原来的顺序是「先领奖再晋升」——晋升解锁的新奖励永远领不到。
        # 改成「晋升 → 领奖」循环，每次升阶后立刻回收官阶奖励。
        for _ in range(3):
            if not page.promote():
                break
            promoted += 1
            rows += page.claim_rows()
        rows += page.claim_rows()
        self.back(ctx)
        return TaskResult(True, f"军衔领奖 {rows} 行，晋升 {promoted} 次",
                          {"rows": rows, "promoted": promoted})


class FriendTask(_RewardTask):
    name = "friend"
    title = "好友送礼"

    @staticmethod
    def _claimed(im):
        """读「今日领取：N/M」；读不到返回 (-1, -1)。"""
        if not textocr.available():
            return (-1, -1)
        try:
            txt = textocr.read_text(im, L.FRIEND_CLAIM_BOX)
        except Exception as e:  # OCR 挂了不要影响任务
            log.warn(f"  好友送礼：读「今日领取」失败（{e}）")
            return (-1, -1)
        m = re.search(r"今日领取[:：]\s*(\d+)\s*/\s*(\d+)", txt)
        if not m:
            return (-1, -1)
        return (int(m.group(1)), int(m.group(2)))

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        im = self.enter(ctx, L.ICON_FRIEND, 1.4)
        if im is None:
            return TaskResult.fail("回不到主城")
        # 2026-11-08：「赠送领取」是一键的（点一次 0/20 → 18/20），旧版盲点 3 次里
        # 有 2 次是纯空点（4 个补偿点都没反应，白赔 8s），而且结果串骗人。
        prev = self._claimed(im)
        got = prev[0] if prev[0] >= 0 else 0
        total = prev[1] if prev[1] >= 0 else 0
        tries = 0
        if total and got >= total:
            # 2026-11-08 实测：送满后「赠送领取」仍然是金色，旧码照点一次，
            # 按钮毫无反应 → press 的 diff 校验白赔 8s（4 个补偿点全不中）。
            log.info(f"  好友送礼：今日领取已满 {got}/{total}，不用再点")
            ui.press(L.FRIEND_CLOSE, 200, expect="none")
            ui.wait(0.9)
            MainCity(ui).ensure()
            return TaskResult(True, f"好友送礼：今日领取已满 {got}/{total}",
                              {"claimed": got, "total": total, "taps": 0})
        for i in range(3):
            im = ui.screen(f"friend_gift{i}") if i else im
            if not vision.is_gold(im, *L.FRIEND_GIFT, r=16):
                log.info("  好友送礼：「赠送领取」不是金色（今天的送完了）")
                break
            tries += 1
            # 下面的 OCR 会复核「今日领取」有没有变大，所以这里不做 diff 校验，
            # 点一次就够（expect="change" 在按钮无反应时会白赔 8s）。
            ui.press(L.FRIEND_GIFT, 220, label=f"friend_gift{i + 1}", expect="none")
            ui.wait(1.8)
            im = ui.screen(f"friend_after{i + 1}")
            now = self._claimed(im)
            if prev[0] >= 0 and now[0] >= 0:
                if now[0] <= prev[0]:
                    log.info(f"  好友送礼：点了但「今日领取」没变（{prev[0]}→{now[0]}），停手")
                    break
                got, total = now
                prev = now
            else:
                got = max(got, i + 1)
        ui.press(L.FRIEND_CLOSE, 200, expect="none")
        ui.wait(0.9)
        MainCity(ui).ensure()
        if total:
            return TaskResult(True, f"好友送礼：今日领取 {got}/{total}（点 {tries} 次）",
                              {"claimed": got, "total": total, "taps": tries})
        return TaskResult(True, f"好友赠送/领取 {got} 次（点 {tries} 次）",
                          {"claimed": got, "taps": tries})


class WelfareTask(_RewardTask):
    """福利：把免费页签里能领的都领掉（2026-10-31 重做）。

    福利页是活动合集，底部页签条可以横向滑动（集结/限时累充/上古宝库/双倍签到/
    周末补给/连续充值/终身福利/萌新指南）。旧版只点两个固定坐标，窗口一滑就
    “找不到终身福利页签”、什么都领不到，而且到了周末补给/双倍签到也只看看。

    现在：先把页签条滑到最左，按槽位逐个点过去，用标题模板认出当前页；
    只对免费页操作——英雄集结（集结达标）、双倍签到（每日签到）、周末补给、
    终身福利；其余充值/兑换页一律不碰。
    """

    name = "welfare"
    title = "福利"

    BANNERS = {
        "assembly": "福利_英雄集结.png",
        "signin": "福利_每日签到.png",
        "weekend": "福利_周末补给.png",
        "lifetime": "福利_终身福利.png",
    }
    SIGNIN_STAMP = "福利_签到领取.png"
    # 2026-11-04 实测：页签条会随选中项自动横移，固定槽位 x 会点空/点错页。
    # 改成「页签文字模板」定位：先找字（阈值 0.93，跨页误配最高 0.79），
    # 再点文字正上方的图标（y=1198）。
    # 同一页签在「选中/未选中」两种状态下字色不同，模板要各存一份取最高分
    TAB_LABELS = {
        "assembly": ("页签_英雄集结.png",),
        "signin": ("页签_双倍签到_未选.png", "页签_双倍签到.png"),
        "weekend": ("页签_周末补给.png",),
        "lifetime": ("页签_终身福利.png",),
    }
    TAB_ROI = (0, 1150, 720, 1280)
    TAB_ICON_Y = 1198
    # 2026-11-07：页签模板是按「当时那一屏」截的，活动换期就缺（实测 `页签_周末补给.png`
    # 从来没进过 templates/，周末补给那一页永远领不到，日志只写「没有可用模板，跳过」）。
    # 页签条上本来就是中文文字，改成**先用 OCR 找字**，模板只作兜底。
    TAB_TEXT = {
        "assembly": ("集结",),
        "signin": ("签到", "双倍"),
        "weekend": ("周末",),
        "lifetime": ("终身",),
    }

    def _tab_x_by_text(self, im, key: str):
        """在底部页签条里按 OCR 文字定位页签，返回文字中心 x（找不到 None）。"""
        from .. import textocr

        keys = self.TAB_TEXT.get(key, ())
        if not keys or not textocr.available():
            return None
        try:
            lines = textocr.read_lines(im, self.TAB_ROI, min_score=0.55)
        except Exception:                     # noqa: BLE001 - OCR 失败就当没读到
            return None
        for text, center, _bbox, _score in lines:
            flat = text.replace(" ", "")
            if any(k in flat for k in keys):
                return int(center[0])
        return None

    def _survey_tabs(self, ui) -> set:
        """先滑到页签条左端，OCR 一次，返回**本期真实存在**的页签 key 集合。

        2026-11-08：`_select_tab` 每找一个页签都要「抓帧 + OCR + 左右滑 6 次」，
        一个本期不存在的页签（如英雄集结活动下架）白烧 74 秒（实测
        logs\_full4_131014.log 13:11:02→13:12:16）。改成先普查一遍：条上读到
        哪些字就只处理哪些页签，缺的直接记一行「本期没有」，不再逐个滑。
        """
        from .. import textocr

        if not textocr.available():
            return set()
        ui.dev.swipe(*L.WELFARE_STRIP_RIGHT, 500)     # 手指右滑 = 回到左端
        ui.wait(1.0)
        try:
            lines = textocr.read_lines(ui.screen("welfare_survey"), self.TAB_ROI,
                                       min_score=0.55)
        except Exception:                             # noqa: BLE001
            return set()
        # 2026-11-09：顺便把每个页签文字的 x 缓存下来。此刻页签条就在左端，
        # 所以这些 x 对「刚滑回左端」的 `_select_tab` 直接可用，能省掉一次 OCR（≈3s），
        # 更重要的是不用再靠 6 次「滑动+试探」去摸页签位置（实测那一段每次空转 7s）。
        # 注意：`TAB_TEXT["signin"] = ("签到", "双倍")` 会同时命中「签到」和「双倍签到」
        # 两个页签，只取第一个匹配会缓存到错的那个（实测缓存 x=458，真正的签到页在 195）。
        # 所以按「完全相等」优先、包含次之打分，取最像的那一行。
        xmap, xscore = {}, {}
        for text, center, _bbox, _score in lines:
            flat_t = text.replace(" ", "")
            for k, keys in self.TAB_TEXT.items():
                sc = 2 if flat_t in keys else (1 if any(w in flat_t for w in keys) else 0)
                if sc and sc > xscore.get(k, 0):
                    xscore[k] = sc
                    xmap[k] = int(center[0])
        flat = " ".join(t.replace(" ", "") for t, _c, _bb, _s in lines)
        present = {k for k, keys in self.TAB_TEXT.items()
                   if any(w in flat for w in keys)}
        if not present:
            return set()
        # 页签多时右侧可能还有一屏没露出来：左滑一次再补读一遍
        ui.dev.swipe(*L.WELFARE_STRIP_LEFT, 500)
        ui.wait(1.0)
        try:
            lines2 = textocr.read_lines(ui.screen("welfare_survey2"), self.TAB_ROI,
                                        min_score=0.55)
        except Exception:                             # noqa: BLE001
            lines2 = []
        flat2 = " ".join(t.replace(" ", "") for t, _c, _bb, _s in lines2)
        xmap2, xscore2 = {}, {}
        for text, center, _bbox, _score in lines2:
            flat_t = text.replace(" ", "")
            for k, keys in self.TAB_TEXT.items():
                sc = 2 if flat_t in keys else (1 if any(w in flat_t for w in keys) else 0)
                if sc and sc > xscore2.get(k, 0):
                    xscore2[k] = sc
                    xmap2[k] = int(center[0])
        present |= {k for k, keys in self.TAB_TEXT.items()
                    if any(w in flat2 for w in keys)}
        ui.dev.swipe(*L.WELFARE_STRIP_RIGHT, 500)
        ui.wait(0.8)
        # 两屏的坐标不能混用：左端那屏归「左端」，左滑之后那屏归「右端」。
        # `_select_tab` 会把页签条先滑回对应的一端再点，所以这两份缓存都能直接用。
        self._tab_x_left = {k: v for k, v in xmap.items() if k in present}
        self._tab_x_right = {k: v for k, v in xmap2.items() if k in present}
        return present

    @staticmethod
    def _banner(im):
        from .. import template as T

        for key, tpl in WelfareTask.BANNERS.items():
            if T.VI.find(im, tpl, 0.85):
                return key
        return None

    @staticmethod
    def _tapped(ui, before, name="welfare_after") -> bool:
        """按完一次领取：如果弹出「获得奖励」浮层（整屏变暗）就点空白关掉。"""
        after = ui.screen(name)
        if vision.darkened(before, after):
            ui.press(L.BLANK, 150, expect="none")
            ui.wait(0.8)
            return True
        return not vision.similar(before, after)

    def _claim_gold_column(self, ui, label: str, limit: int = 6) -> int:
        """在右侧按钮列里找金色「领取」逐个点（标签「前往」是土黄色，不会误点）。"""
        n = 0
        for _ in range(limit):
            im = ui.screen("welfare_rows")
            bands = vision.gold_button_bands(im, L.WELFARE_CLAIM_SCAN)
            if not bands:
                break
            cx, cy, _ = bands[0]
            if not ui.press((cx, cy), 220):
                break                       # 2026-11-05：金色按钮已失效，别在原点空点
            ui.wait(1.5)
            if self._tapped(ui, im):
                n += 1
                log.info(f"  福利·{label}领取 ×{n}")
            else:
                break
        return n

    def _claim_assembly(self, ui) -> int:
        from .. import template as T

        im = ui.screen("welfare_asm")
        if T.VI.find(im, "福利_特惠礼包.png", 0.85):
            ui.press(L.WELFARE_ASSEMBLY_SUBTAB, 220)
            ui.wait(1.4)
        n = self._claim_gold_column(ui, "集结达标")
        if n == 0:
            # 列表可能往下还有达标的档位
            ui.dev.swipe(360, 1000, 360, 700, 500)
            ui.wait(1.0)
            n += self._claim_gold_column(ui, "集结达标")
        return n

    def _signin_claims(self, im, claimed: set) -> list:
        """签到页上还没点过的「领取」按钮中心（OCR 精确匹配）。

        2026-11-07 实测：按钮早就是深色胶囊 + 绿字（本体 (56,101,53)、文字
        (92,208,97)），一个红像素都没有，`vision.signin_claim` 永远判 False；
        而且日历随已签到天数整体上移一行，固定格坐标也对不上。所以改成用 OCR
        直接找「领取」二字（bbox 中心 (113,801) 那次 score 0.99）。
        付费的「再领一次」、横幅「充值任意金额可再领一次」都在 ROI 之外，不会被点。
        """
        out = []
        try:
            lines = textocr.read_lines(im, L.WELFARE_SIGNIN_ROI, min_score=0.55)
        except Exception as exc:                      # OCR 不可用 → 交给固定格兜底
            log.info(f"  福利·每日签到：OCR 不可用（{exc}），改用固定格 + 飘带判据")
            return out
        for text, center, _bbox, _score in lines:
            if text.replace(" ", "") != "领取":
                continue
            if (center[0], center[1]) in claimed:
                continue
            out.append((int(center[0]), int(center[1])))
        return out

    def _claim_signin(self, ui) -> int:
        """每日签到：优先 OCR 找「领取」，OCR 不可用时退回固定格 + 飘带判据。

        历史：2026-11-03 用「固定 5×3 格 + 红色飘带形状 + 绿字宽度」替代失效的模板
        （真机最佳分只有 0.743）。2026-11-07 实测该判据也已失效：按钮变成深色胶囊 +
        绿字，红像素为 0，且日历上移后固定格对不上 → 一律 WARN「没找到红色领取飘带」。
        现在主判据是 OCR 精确匹配「领取」（见 `_signin_claims`），固定格只在 OCR
        不可用时兜底。
        """
        n = 0
        # 2026-11-07 修 NameError：这里原来写 `done.add((x, y))`，但 `done` 是 run() 的
        # 局部变量、本方法里既不是参数也不是局部名 —— 只要真的领到一次就会崩。
        claimed: set[tuple[int, int]] = set()
        for _ in range(4):
            im = ui.screen("welfare_cal")
            targets = self._signin_claims(im, claimed)
            if not targets and n == 0 and not claimed:
                targets = self._signin_fixed_cells(im, claimed)
            if not targets:
                break
            for pos in targets:
                if not ui.press(pos, 220, label=f"signin:{pos[0]}", expect="none"):
                    claimed.add(pos)
                    continue
                ui.wait(1.6)
                if self._tapped(ui, im):
                    n += 1
                    log.info(f"  福利·每日签到领取 ×{n}（{pos[0]},{pos[1]}）")
                claimed.add(pos)
        if n == 0:
            log.info("  福利·每日签到：这一屏没有可点的「领取」（今天已签或还没到时间）")
        return n

    def _signin_fixed_cells(self, im, claimed: set) -> list:
        """兜底：固定格 + 红飘带/绿字宽度判据（仅 OCR 不可用时使用）。"""
        out = []
        dx0, dy0, dx1, dy1 = L.WELFARE_SIGNIN_CELL
        for y in L.WELFARE_SIGNIN_YS:
            for x in L.WELFARE_SIGNIN_XS:
                if (x, y) in claimed:
                    continue
                if vision.signin_claim(im, (x + dx0, y + dy0, x + dx1, y + dy1)):
                    out.append((x, y))
        return out

    def _weekend_claims(self, im) -> list:
        """周末补给页上可点的「领取」按钮中心（OCR 精确匹配）。

        2026-11-07 实测：三个礼包按钮文字是「领取 / 待领取 / 待领取」，中心在
        y≈1031（旧常量写的 1075 已在按钮下方），按钮也不是金色 —— `is_gold` 三个
        全 False，所以旧版 `_claim_weekend` 永远领不到东西。这里用 OCR 精确匹配
        「领取」（`待领取` 是另一个字符串，不会被当成可领）。
        """
        out = []
        try:
            lines = textocr.read_lines(im, L.WELFARE_WEEKEND_ROI, min_score=0.55)
        except Exception as exc:
            log.info(f"  福利·周末补给：OCR 不可用（{exc}），改用金色判据兜底")
            return out
        for text, center, _bbox, _score in lines:
            if text.replace(" ", "") != "领取":
                continue
            out.append((int(center[0]), int(center[1])))
        return out

    def _claim_weekend(self, ui) -> int:
        n = 0
        for _ in range(3):
            im = ui.screen("welfare_weekend")
            targets = self._weekend_claims(im)
            if not targets:                      # OCR 不可用才走金色兜底
                targets = [p for p in L.WELFARE_WEEKEND_BTNS if vision.is_gold(im, *p, r=16)]
            if not targets:
                break
            pos = targets[0]
            if not ui.press(pos, 220, label=f"weekend:{pos[0]}", expect="none"):
                break                       # 2026-11-05：按钮点击无反应即停
            ui.wait(1.5)
            if not self._tapped(ui, im):
                log.info(f"  福利·周末补给：点了「领取」({pos[0]},{pos[1]}) 但画面没变，"
                         f"可能这档还没到时间，停手")
                break
            n += 1
            log.info(f"  福利·周末补给领取 ×{n}（{pos[0]},{pos[1]}）")
        if n == 0:
            log.info("  福利·周末补给：三档都显示「待领取」，今天没有可领的")
        return n

    def _lifetime_claim_pos(self, im):
        """终身福利底部「领取」按钮中心；已领过时写「已领取」→ 返回 None。

        2026-11-07 实测：按钮文字中心 (565,1084)；可领时是「领取」，领完变绿色
        「已领取」（`is_gold` 判 False 本身没错，但旧版因此从不点击，也没法区分
        「已领」和「活动没开」）。这里用 OCR 精确匹配「领取」。
        """
        try:
            lines = textocr.read_lines(im, L.WELFARE_LIFETIME_ROI, min_score=0.55)
        except Exception:
            return None
        for text, center, _bbox, _score in lines:
            if text.replace(" ", "") == "领取":
                return (int(center[0]), int(center[1]))
        return None

    def _claim_lifetime(self, ui) -> int:
        im = ui.screen("welfare_lifetime")
        pos = self._lifetime_claim_pos(im)
        if pos is None:
            if vision.is_gold(im, *L.WELFARE_LIFETIME_CLAIM, r=16):
                pos = L.WELFARE_LIFETIME_CLAIM        # OCR 不可用时按旧金色判据兜底
            else:
                log.info("  福利·终身福利：底部写着「已领取」，今天没有可领的")
                return 0
        if not ui.press(pos, 220, label="welfare_lifetime", expect="none"):
            log.warn("  福利·终身福利：按钮点击无反应，停手")
            return 0
        ui.wait(1.5)
        if not self._tapped(ui, im):
            # 2026-11-09 假成功审计：旧码把 _tapped 的返回值丢掉、恒返回 1
            log.info(f"  福利·终身福利：点 ({pos[0]},{pos[1]}) 后画面没变化，本次不计入领取")
            return 0
        log.info(f"  福利·终身福利领取 ×1（{pos[0]},{pos[1]}）")
        return 1

    def _claim_page(self, ui, key: str | None) -> int:
        if key == "assembly":
            return self._claim_assembly(ui)
        if key == "signin":
            return self._claim_signin(ui)
        if key == "weekend":
            return self._claim_weekend(ui)
        if key == "lifetime":
            return self._claim_lifetime(ui)
        return 0

    def _find_tab(self, im, key: str):
        """在底部页签条里找「页签文字」模板；多个模板取最高分，缺失写警告。"""
        from .. import template as T

        best = None
        missing = []
        for tpl in self.TAB_LABELS.get(key, ()):
            try:
                m = T.VI.find(im, tpl, 0.93, roi=self.TAB_ROI)
            except FileNotFoundError:
                missing.append(tpl)
                continue
            if m is not None and (best is None or m.score > best.score):
                best = m
        if best is None and missing:
            log.info(f"  福利：页签模板缺失 {', '.join(missing)}（{key} 改用 OCR 找字）")
        return best

    def _select_tab(self, ui, key: str) -> bool:
        """按「页签文字」定位并点击其正上方图标，用页面横幅确认切换成功。

        页签条会随选中项自动横移，所以每次点前都重新找字；找不到就左右滑一屏。
        2026-11-07：定位优先走 OCR（`_tab_x_by_text`），模板匹配只作兜底——
        模板是按单张截图截的，缺一张就整页跳过（周末补给就是这样丢的）。
        """
        from .. import template as T

        # 0) 已经停在目标页？直接过。实测：进福利时本来就在「英雄集结」页，
        #    老逻辑还会再找 6 次、每次「抓帧+OCR+点击+2.6s+滑屏」≈ 7s，白烧 17s。
        if self._banner(ui.screen("welfare_cur")) == key:
            log.info(f"  福利：已经停在 {key} 页，不用切")
            return True

        # 1) 用普查缓存的位置点：先把页签条归位到对应的那一端，再点那一端的坐标。
        #    实测（run22）只靠一份缓存会出现「x 是左端的、条却停在右边」→ 点空 3 次
        #    再退回 OCR 重找，一个页签烧 25s。分端缓存后每个页签约 4s。
        ends = (("左端", getattr(self, "_tab_x_left", {}), L.WELFARE_STRIP_RIGHT),
                ("右端", getattr(self, "_tab_x_right", {}), L.WELFARE_STRIP_LEFT))
        # 2026-11-09：先试「这个页签上次成功的那一端」（比「上次成功的那一端」更准：
        # signin/weekend 永远在右端，lifetime 也在右端；不分页签时会对左端白试 3 次）。
        key_end = getattr(self, "_tab_key_end", None)
        if key_end is None:
            key_end = self._tab_key_end = {}
        if key in key_end:
            ends = tuple(sorted(ends, key=lambda e: 0 if e[0] == key_end[key] else 1))
        else:
            last_end = getattr(self, "_tab_end_pref", "")
            if last_end:
                ends = tuple(sorted(ends, key=lambda e: 0 if e[0] == last_end else 1))
        for tag, xmap, swipe in ends:
            xc = xmap.get(key)
            if xc is None:
                continue
            ui.dev.swipe(*swipe, 500)          # 归位：手指右滑=回左端 / 左滑=露右端
            ui.wait(1.1)
            # 上一次在这个页签/这一端命中的 dx 先试，省掉「0 → -24 → 24」的试探
            dmap = getattr(self, "_tab_dx", None)
            if dmap is None:
                dmap = self._tab_dx = {}
            cands: list[int] = []
            for d in (dmap.get((key, tag)), 0, -24, 24):
                if d is not None and d not in cands:
                    cands.append(d)
            for dx in cands:
                ui.press((xc + dx, self.TAB_ICON_Y), 220,
                         label=f"welfare_tab:{key}", expect="none")
                ui.wait(1.8)
                if self._banner(ui.screen("welfare_tab")) == key:
                    self._tab_end_pref = tag          # 下次先试这一端
                    key_end[key] = tag                # 这个页签就住在这儿
                    xmap[key] = xc + dx               # 命中坐标回写，下次一次到位
                    dmap[(key, tag)] = dx
                    log.info(f"  福利：切到 {key}（{tag}缓存 x={xc + dx}）")
                    return True
            log.debug(f"  福利：{tag}缓存 x={xc} 没切到 {key}，试另一端/OCR")

        have_tpl = any(T.VI.path(t).exists() for t in self.TAB_LABELS.get(key, ()))
        # 2026-11-08：页签条会记住上次位置（实测停在「终身福利」时集结已在屏幕左外），
        # 先右滑回最左端再左滑；原来「左、右、左、右」4 次跨不过 2 个页签。
        dirs = ("right", "left", "right", "left")
        for attempt in range(len(dirs)):
            im = ui.screen("welfare_tabs")
            x = self._tab_x_by_text(im, key)
            if x is None and have_tpl:
                m = self._find_tab(im, key)
                if m is not None:
                    x = int(m.center[0])
            if x is not None:
                for dx in (0, -24, 24):
                    # expect="none"：切页动画 >1s，用横幅判定，不走「空点」误报
                    ui.press((x + dx, self.TAB_ICON_Y), 220,
                             label=f"welfare_tab:{key}", expect="none")
                    ui.wait(2.6)
                    got = self._banner(ui.screen("welfare_tab"))
                    if got == key:
                        log.info(f"  福利：切到 {key}（点 x={x + dx}）")
                        return True
                    if got is not None:
                        # 点到相邻页签，继续尝试偏移，不再滑动
                        continue
                log.warn(f"  福利：点 x={x} 后横幅不是 {key}，本页签按未命中处理")
            if dirs[attempt] == "right":
                ui.dev.swipe(*L.WELFARE_STRIP_RIGHT, 500)   # 手指右滑 = 回到左端
            else:
                ui.dev.swipe(*L.WELFARE_STRIP_LEFT, 500)    # 露出右侧页签
            ui.wait(1.2)
        log.debug(f"  福利：{key} 页签没定位到（底部条既没读到文字、模板也没命中）")
        return False

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        im = self.enter(ctx, L.ICON_WELFARE, 1.8)
        if im is None:
            return TaskResult.fail("回不到主城")
        claimed = 0
        done: set[str] = set()

        # 进福利默认就在「英雄集结」，先核对再领（避免进错页时误操作）
        first = self._banner(ui.screen("welfare_first"))
        if first == "assembly":
            claimed += self._claim_assembly(ui)
            done.add("assembly")
        elif first is not None:
            done.add(first)
            claimed += self._claim_page(ui, first)

        # 逐个目标页签：先按文字定位切页，确认横幅后再领
        # 2026-11-07：assembly 也放进循环——进福利页时若横幅模板没命中（活动换期/换图），
        # 旧代码直接把它算作「没点到」，那一页的达标奖励就永远领不到。
        # 2026-11-08：先普查页签条，只处理本期真实存在的页签（缺席的不再逐个滑动）
        present = self._survey_tabs(ui)
        for key in ("assembly", "signin", "lifetime", "weekend"):
            if key in done:
                continue
            if present and key not in present:
                log.info(f"  福利：本期页签条里没有 {key}（活动没开或已下架），跳过")
                continue
            if not self._select_tab(ui, key):
                continue
            claimed += self._claim_page(ui, key)
            done.add(key)

        missing = [k for k in self.BANNERS if k not in done]
        if missing:
            # 2026-11-07：本期福利页只有 宝库/签到/周末补给/连续充值/终身福利/萌新指南，
            # 没有「英雄集结」——所以 assembly 缺失是活动排期问题，不是脚本故障。
            # 2026-11-08：顺手把「当前看到哪些页签」打出来；真帧实测（logs\_welfare_swipe_check.py）
            # 页签条今天只有 签到/周末补给/连续充值/终身福利/萌新指南，且在条上横滑也不动
            # → 说明条本身不可滚动，缺的页签是真没有，不是脚本没滑到。
            # 复用 `_survey_tabs` 的普查结果；只有普查什么都没读到时才补一次 OCR
            seen = sorted(present) if present else [
                k for k in self.TAB_TEXT
                if self._tab_x_by_text(ui.screen("welfare_seen"), k) is not None]
            log.info(f"  福利：本期页签条里没有 {', '.join(missing)}（活动没开或已下架）；"
                     f"当前看到 {', '.join(seen) if seen else '（一个都没认出来）'}，"
                     f"其余页签已处理")
        self.back(ctx)
        return TaskResult(True, f"福利领取 {claimed} 项（{len(done)} 个页签）",
                          {"claimed": claimed, "tabs": sorted(done)})


# 注：达标返利（rebate）已按需求移除 —— 它是限时活动，图标会在主城顶部网格里换位置，
# 用固定坐标点会点错，得不偿失。


class BattlePassTask(_RewardTask):
    """勇者计划（战令）：**只做免费动作**。

    2026-11-04 用户反馈「一直在乱用钻石，执行的完全不是我要求执行的任务」：
    - 旧坐标 ICON_HERO_PLAN=(280,290) 实际点到的是「千抽福利」，后面所有点击全错位；
    - 旧逻辑在奖励轨道上扫金色按钮，命中的是 68 元「继续领取/解锁高级战令」付费入口。

    新流程（全部有标题模板或颜色证据才点）：
    1) 主城图标候选坐标逐个试，必须标题识别出「勇者计划」才算进入；
    2) 战令任务 → 每日/每周/挑战三页签，只点金色「领取」（is_gold 明确排除土黄「前往」）；
    3) 战令奖励 → 只点左列「免费奖励」带红点的图标，绝不碰右列「高级专属」；
    4) 回主城 → 召唤页每日免费一抽：倒计时条没有数字、且只有短短「免费」两字才抽；
    5) 任何一步出现橙色付费 CTA → 立刻返回并停止，本轮 BP 记为失败；
    6) 全程前后读主城钻石数，必须 0 变化，否则显式失败。
    """

    name = "bp"
    title = "勇者计划"

    @staticmethod
    def _purchase_dialog(im, before=None) -> bool:
        """疑似付费确认窗。

        2026-11-07 实测：旧判据 `orange_button_bands(im,(180,700,540,1010))` 会误报 ——
        主城常驻的橙色按钮（「超值首充」「达标返利」）也会被扫出来，
        所以那一版在奖励轨道上「点免费格 → 判成付费 → 退回」，白跑。
        改成两层：① 若给了点击前的帧，先看整屏是否被压暗；② OCR 只在正文区找付费关键词。
        奖励页常驻的「解锁高级战令」在顶栏 y≈443，不在弹层正文区内，不会误命中。
        """
        if before is not None and not vision.darkened(before, im, box=(0, 120, 200, 320)):
            return False
        try:
            text = textocr.read_text(im, L.BP_PAY_TEXT_BOX)
        except Exception:  # noqa: BLE001 - OCR 不可用时退回橙色判据之外的安全默认
            return False
        keys = ("解锁战令可获得", "是否花费", "立即购买", "确认购买", "前往购买")
        return any(k in text for k in keys)

    @staticmethod
    def _overlay_open(im) -> bool:
        """领奖浮层：OCR 里有「获得奖励」或「快速点击空白处关闭」。"""
        try:
            text = textocr.read_text(im, L.BP_OVERLAY_TITLE) + " " + textocr.read_text(
                im, (120, 860, 620, 960))
        except Exception:  # noqa: BLE001
            return False
        return ("获得奖励" in text) or ("点击空白处关闭" in text)

    @classmethod
    def _close_overlay(cls, ui, before) -> bool:
        """关「获得奖励」浮层。

        2026-11-07 实测：该浮层**点面板内部关不掉**（L.BLANK=(200,700) diff=0.001），
        而误把下一次点击落到浮层里的「前往」上会直接跳到角斗场战报页，任务从此走偏。
        安全点是面板上方的压暗区（L.BP_OVERLAY_CLOSE），逐个试并复核浮层是否消失。
        """
        im = ui.screen("bp_overlay")
        if not cls._overlay_open(im) and not vision.darkened(before, im, box=(0, 120, 200, 320)):
            return True
        for pos in L.BP_OVERLAY_CLOSE:
            ui.press(pos, 160, label=f"bp_overlay_close:{pos[0]},{pos[1]}", expect="none")
            ui.wait(0.9)
            im = ui.screen("bp_overlay_after")
            if not cls._overlay_open(im):
                return True
        log.warn("  勇者计划：领奖浮层关不掉（点了 5 个压暗区都没消失）")
        return False

    @staticmethod
    def _diamonds(im):
        """读主城顶栏钻石。

        2026-11-10 第 40 轮实测：这里原来用 `MerchantPage.read_diamonds`
        （模板 OCR + mask），与 `BaseTask.diamonds`（textocr read_lines）两套读数器
        结果不一致 —— 同一个任务里报出了 `钻石 363→303`（实际一分没花）。
        现在统一走 BaseTask.diamonds。
        """
        from .base import BaseTask
        val = BaseTask.diamonds(im)
        return val, (1.0 if val is not None else 0.0)

    def _diamonds_retry(self, ui, tag: str, tries: int = 4):
        """读主城顶栏钻石：要求连续两帧读到同一个数（单帧会误读）。

        2026-11-09 假成功审计 C1：收尾那一帧还盖着召唤结果浮层时顶栏被遮 → None；
        2026-11-10 第 40 轮：单帧读数不一致，报出 `钻石 363→303` 这种假变化。
        现在用 `diamonds_stable`（相邻两帧一致才采纳），读不到就先回主城再试。
        返回 (值或 None, 分数, 最后一帧)。
        """
        from ..pages import MainCity

        val = self.diamonds_stable(ui, f"bp_dia_{tag}", tries=max(2, tries))
        if val is not None:
            return val, 1.0, None
        if ui.state() != vision.State.MAIN_CITY:
            MainCity(ui).ensure()
            ui.wait(0.8)
            val = self.diamonds_stable(ui, f"bp_dia_{tag}_city", tries=2)
        return val, (1.0 if val is not None else 0.0), None

    # ---------- 进入 ----------
    @staticmethod
    def _slot_cache_path():
        from pathlib import Path

        return Path(__file__).resolve().parents[2] / "logs" / "bp_slot.json"

    @classmethod
    def _load_slot(cls) -> dict:
        import json

        try:
            return json.loads(cls._slot_cache_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    @classmethod
    def _save_slot(cls, data: dict) -> None:
        import json

        try:
            p = cls._slot_cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _enter_page(self, ui) -> bool:
        """进战令页。

        2026-11-10：主城左上「限时活动」是 4×2 网格、内容每天轮换，战令图标可能不在其中。
        所以改成：先试上次成功的槽位 → 再逐个试网格槽位 → 全靠标题模板确认（不看「画面变了没有」，
        因为点开别的活动页也会变，以前会误以为进页成功）。命中后记住槽位，下次先试它。
        """
        from .. import titles

        im = ui.screen("bp_before")
        if titles.on_page(im, "hero_plan"):
            return True
        if ui.state() != vision.State.MAIN_CITY:
            ui.press(L.BP_BACK, 220, expect="none")
            ui.wait(1.4)

        import datetime

        today = datetime.date.today().isoformat()
        cache = self._load_slot()
        cached = ((int(cache["x"]), int(cache["y"])) if "x" in cache else None)
        if cache.get("miss_date") == today and not cached:
            # 今天已经扫过一遍、主城限时图标里没有战令入口 → 别再每轮白探 ~54s。
            log.info("  勇者计划：今天已经探过一轮（主城限时图标里没有战令入口），跳过")
            return False
        grid = list(getattr(L, "BP_ICON_GRID", ()))
        # 有槽位网格时不再用旧的 4 个硬编码点（它们本来就落在网格里，重复探一次白花 ~18s）。
        legacy = () if grid else tuple(L.BP_ICON_CANDIDATES)
        tries = ([cached] if cached else []) + [p for p in grid if p != cached] + \
                [p for p in legacy if p != cached and p not in grid]

        for pos in tries:
            before = ui.screen("bp_icon_before")
            ui.press(pos, 220, label="bp_icon", expect="none")
            ui.wait(1.8)
            im = ui.screen("bp_icon_after")
            if titles.on_page(im, "hero_plan"):
                log.info(f"  勇者计划：主城图标实测可用 {pos}")
                self._save_slot({"x": pos[0], "y": pos[1], "date": today})
                return True
            if not vision.similar(before, im):
                log.info(f"  勇者计划：点 {pos} 打开了别的页面（不是战令），返回主城")
                ui.press(L.BP_BACK, 220, expect="none")
                ui.wait(1.4)
        log.info(f"  勇者计划：{len(tries)} 个候选槽位都没进战令页（限时图标今天没放战令入口）")
        self._save_slot({"miss_date": today})
        return False

    # ---------- 任务页 ----------
    @staticmethod
    def _task_buttons(im) -> list:
        """任务页右侧按钮里哪些是「领取」（金色可点）。

        2026-11-07 实测：任务行按钮文字是 `前往 / 领取 / 已领取`，
        `前往` 是浅土黄（is_gold=False）、`已领取` 是灰绿 —— 旧代码只看 is_gold 且 y 偏了 50px，
        所以一个都认不出。这里用 OCR 读文字 + 固定行中心双保险：只有读到的按钮文字是
        「领取」、并且该点像素确实是金色，才返回。
        """
        out = []
        lines = None
        if textocr.available():
            try:
                lines = textocr.read_lines(im, L.BP_CLAIM_ZONE, min_score=0.5)
            except Exception:  # noqa: BLE001
                lines = []
            for text, center, _bb, _sc in lines:
                if "领取" not in text or "已领取" in text:
                    continue
                x, y = center
                if not vision.is_gold(im, x, y, r=18):
                    continue
                out.append((x, y))
            if out:
                return out
            if lines:
                # 2026-11-08 实测：领完之后同一批行会变成「前往」（浅土黄，也有金色
                # 像素带）。OCR 明确读到了按钮文字却没有「领取」→ 这就是「没有可领的」，
                # 绝不能再退回金色兜底去点「前往」（点下去会跳到角斗场/挂机页）。
                log.info(f"  勇者计划：本轮 {len(lines)} 个按钮里没有「领取」"
                         f"（都是前往/已领取，说明这些任务还没做完或已领）")
                return []
        # 只有 OCR 不可用（或框里一个字都没读到）才用固定行中心 + 金色判据兜底
        for y in L.BP_TASK_YS:
            if vision.is_gold(im, L.BP_TASK_BTN_X, y, r=18):
                out.append((L.BP_TASK_BTN_X, y))
        return out

    def _bp_recover(self, ui) -> bool:
        """画面跑偏（误点「前往」跳到角斗场/挂机页等）后回到战令任务页。

        2026-11-08 实测：任务行的「前往」把画面带去角斗场，之后整段 bp 都在
        角斗场页按战令坐标乱走。这里统一自愈：退回主城 → 重进战令 → 点回任务页。
        """
        from .. import titles

        for _ in range(3):
            if ui.state() == vision.State.MAIN_CITY:
                break
            ui.press(L.BP_BACK, 220, expect="none")
            ui.wait(1.2)
        if ui.state() != vision.State.MAIN_CITY and not MainCity(ui).ensure():
            return False
        if not self._enter_page(ui):
            return False
        ui.press(L.BP_TASK_VIEW, 220, expect="none")
        ui.wait(1.5)
        im = ui.screen("bp_row_recovered")
        ok = titles.on_page(im, "hero_plan")
        if ok:
            log.info("  勇者计划：已回到战令任务页（跑偏自愈成功）")
        return ok

    @staticmethod
    def _bp_bottom_tab(im, want: str):
        """在底部页签条里找 want（如「任务」）文字的中心点；读不到返回 None。

        2026-11-08：`L.BP_TASK_VIEW=(626,1261)` 是照真帧改过一次的常量，但底部
        页签会随版本左右挪，所以再补一层按文字的定位（和福利页的做法一致）。
        """
        try:
            lines = textocr.read_lines(im, L.BP_BOTTOM_STRIP, min_score=0.5)
        except Exception:  # noqa: BLE001
            return None
        for text, center, _bb, _sc in lines:
            if want in text.replace(" ", ""):
                return (int(center[0]), int(center[1]))
        return None

    def _claim_tasks(self, ui) -> int:
        from .. import titles

        before = ui.screen("bp_tasks_pre")
        ui.press(L.BP_TASK_VIEW, 220, label="bp_task_view", expect="none")
        ui.wait(1.5)
        after = ui.screen("bp_tasks")
        if vision.similar(before, after):
            # 画面没变有两种情况：(a) 本来就已经在任务页；(b) 页签位置又变了。
            # 旧代码一律 return 0，于是 (a) 会把当天所有任务奖励白丢。
            early = textocr.read_text(before, L.BP_TASK_TAB_ZONE)
            if early and any(k in early for k in ("任务", "领取", "前往", "完成")):
                log.info("  勇者计划：点「战令任务」后画面没变——本来就是任务页，直接开始领")
            else:
                pos = self._bp_bottom_tab(after, "任务")
                if pos is None:
                    log.warn(f"  勇者计划：点「战令任务」{L.BP_TASK_VIEW} 后画面没变，"
                             f"底部条里也没读到「任务」页签"
                             f"（其 OCR：{textocr.read_text(after, L.BP_BOTTOM_STRIP)[:40]}）")
                    return 0
                log.info(f"  勇者计划：底部「任务」页签 OCR 在 {pos}（常量 {L.BP_TASK_VIEW} 偏了），改用它")
                ui.press(pos, 220, label="bp_task_view_ocr", expect="none")
                ui.wait(1.5)
                again = ui.screen("bp_tasks2")
                if vision.similar(before, again):
                    log.warn("  勇者计划：按 OCR 位置再点一次「任务」，画面还是没变，跳过任务页")
                    return 0
        n = 0
        for ti, tab in enumerate(L.BP_TABS):
            ui.press(tab, 220, label=f"bp_tab:{ti}", expect="none")
            ui.wait(1.2)
            im = ui.screen("bp_row")
            labels = textocr.read_text(im, L.BP_TASK_TAB_ZONE)
            if labels and not any(k in labels for k in ("任务", "领取", "前往", "完成")):
                log.info(f"  勇者计划：页签 {ti} 没切过去（顶部读不到任务文字：{labels[:40]}）")
                continue
            for _page in range(2):
                if not titles.on_page(im, "hero_plan"):
                    # 上一轮点到「前往」跳走了（角斗场/挂机页…），先自愈再继续
                    log.warn(f"  勇者计划：任务页签 {ti} 现在不在战令页（画面被点跑了），"
                             f"退回战令任务页重来")
                    if not self._bp_recover(ui):
                        return n
                    ui.press(tab, 220, expect="none")
                    ui.wait(1.1)
                    im = ui.screen("bp_row")
                for pos in self._task_buttons(im):
                    # 2026-11-08 07:51 实测：领奖/切页签后列表会重渲染（「领取」→「前往」），
                    # 用旧帧算出的坐标点下去会落到「前往」上（=跳到角斗场，整段 bp 走偏）。
                    # 所以点的前一刻抓一帧、只读该按钮那一小块，确认还写着「领取」才点。
                    fresh = ui.screen("bp_row_check")
                    near = (pos[0] - 90, pos[1] - 26, pos[0] + 60, pos[1] + 26)
                    if textocr.available():
                        txt = textocr.read_text(fresh, near)
                        if "领取" not in txt or "已领取" in txt:
                            log.info(f"  勇者计划：页签 {ti} y={pos[1]} 点前复看是"
                                     f"「{txt.strip()[:12]}」（不是「领取」）→ 跳过，防跳到「前往」")
                            continue
                        if not vision.is_gold(fresh, pos[0], pos[1], r=18):
                            log.info(f"  勇者计划：页签 {ti} y={pos[1]} 点前复看已不是金色 → 跳过")
                            continue
                    ui.press(pos, 220, label=f"bp_claim_task:{ti}:{pos[1]}", expect="none")
                    ui.wait(1.3)
                    aft = ui.screen("bp_row_after")
                    if self._purchase_dialog(aft, im):
                        log.warn(f"  勇者计划：任务页签 {ti} y={pos[1]} 弹出付费确认，"
                                 f"立刻返回并停止 BP")
                        ui.press(L.BP_BACK, 250, expect="none")
                        ui.wait(1.5)
                        return -1
                    if self._overlay_open(aft) or vision.darkened(im, aft):
                        if self._close_overlay(ui, im):
                            n += 1
                        im = ui.screen("bp_row")
                    elif vision.similar(im, aft):
                        log.info(f"  勇者计划：任务页签 {ti} y={pos[1]} 按钮点了无变化（可能已领完）")
                    else:
                        log.warn(f"  勇者计划：任务页签 {ti} y={pos[1]} 点后跳页（不是领奖浮层），"
                                 f"退回战令任务页")
                        if not self._bp_recover(ui):
                            return n
                        ui.press(tab, 220, expect="none")
                        ui.wait(1.0)
                        im = ui.screen("bp_row")
                ui.dev.swipe(360, 1000, 360, 720, 500)
                ui.wait(0.8)
                im = ui.screen("bp_row")
        if n == 0:
            log.info("  勇者计划：每日/每周/挑战三页签没有可领的任务奖励（都已完成或未达标）")
        return n

    # ---------- 奖励轨道（只碰左列免费） ----------
    def _claim_free_track(self, ui) -> int:
        before = ui.screen("bp_reward_pre")
        ui.press(L.BP_REWARD_VIEW, 220, label="bp_reward_view", expect="none")
        ui.wait(1.5)
        after = ui.screen("bp_rewards")
        if vision.similar(before, after):
            log.warn("  勇者计划：点「战令奖励」后画面没变，奖励轨道没打开")
            return 0
        n = 0
        for _page in range(2):
            im = ui.screen("bp_rewards")
            for y in L.BP_REWARD_YS:
                if not vision.red_badge(im, L.BP_FREE_ICON_X, y, r=18):
                    continue
                ui.press((L.BP_FREE_ICON_X, y), 220,
                         label=f"bp_free_reward:{y}", expect="none")
                ui.wait(1.2)
                aft = ui.screen("bp_free_after")
                if self._purchase_dialog(aft, im):
                    log.warn(f"  勇者计划：免费奖励 y={y} 竟弹出付费确认，立刻返回并停止")
                    ui.press(L.BP_BACK, 250, expect="none")
                    ui.wait(1.5)
                    return -1
                if self._overlay_open(aft) or vision.darkened(im, aft):
                    if self._close_overlay(ui, im):
                        n += 1
                elif not vision.similar(im, aft):
                    log.info(f"  勇者计划：免费奖励 y={y} 点后换了页面（不是领奖浮层），跳过")
            ui.dev.swipe(360, 1050, 360, 760, 500)
            ui.wait(0.8)
        if n == 0:
            log.info("  勇者计划：左列免费奖励没有红点可领（已领完，或等级未到新档位）")
        return n

    # ---------- 每日免费一抽 ----------
    def _daily_free_draw(self, ui) -> bool:
        from .. import ocr
        im = ui.screen("bp_summon_pre")
        ui.press(L.SUMMON_ENTRY, 220, label="bp_summon_entry", expect="none")
        ui.wait(2.0)
        im = ui.screen("bp_summon")
        # 用「召唤十次」的亮金色按钮确认确实进了召唤页（单抽按钮是米色，不适合做金色判据）
        if not vision.is_gold(im, *L.SUMMON_TEN, r=22):
            log.warn("  战令·每日免费一抽：没进召唤页（十连按钮不是金色），跳过")
            ui.press(L.BACK, 220, expect="none")
            ui.wait(1.2)
            return False
        # 倒计时条：有数字 = 还没到免费时间；只有短短「免费」两字才允许点
        nums = ocr.read_all_numbers(im, L.SUMMON_FREE_BOX, mask="green_loose", digits=(1, 2))
        segs = ocr._segments(ocr._mask(im, L.SUMMON_FREE_BOX, "green_loose"))
        width = (max(s[2] for s in segs) - min(s[0] for s in segs)) if segs else 0
        if nums or width >= 110 or width < 20:
            log.info(f"  战令·每日免费一抽：当前不是免费次数（倒计时数字={nums} 文本宽={width}px），"
                     f"不抽，钻石不变")
            ui.press(L.BACK, 220, expect="none")
            ui.wait(1.2)
            return False
        ui.press(L.SUMMON_ONE, 220, label="bp_free_draw", expect="none")
        ui.wait(2.6)
        res = ui.screen("bp_summon_result")
        if vision.similar(im, res):
            log.warn("  战令·每日免费一抽：点了单抽画面没变（可能并不是免费次数），不重试")
            ui.press(L.BACK, 220, expect="none")
            ui.wait(1.2)
            return False
        log.info("  战令·每日免费一抽：已抽 1 次（免费），结果帧已留证")
        ui.press(L.BLANK, 150, expect="none")
        ui.wait(0.8)
        ui.press(L.BACK, 220, expect="none")
        ui.wait(1.2)
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        # 可能停在召唤/其它页：先退回主城，否则钻石读数取错位置
        for _ in range(3):
            if ui.state() == vision.State.MAIN_CITY:
                break
            ui.press(L.BACK, 220, expect="none")
            ui.wait(1.4)
        d0, s0, _city = self._diamonds_retry(ui, "start")
        if d0 is None:
            # 2026-11-09：没有基线就不进战令页——里面的「免费」动作在某些状态下
            # 会变成付费（解锁高级战令/非免费抽），没有前后对比就无法证明没花钻。
            log.warn(f"  勇者计划：主城钻石数读不到（score={s0:.2f}，已重试并回主城）"
                     f"，没有基线就不做有付费风险的动作")
            return TaskResult.fail(
                "战令：主城钻石读数失败，无法建立「未花钻」基线，本轮不进页面",
                {"diamonds_before": None})
        log.info(f"  勇者计划：开始前钻石={d0}")

        entered = self._enter_page(ui)
        if not entered:
            ui.press(L.BP_BACK, 220, expect="none")
            ui.wait(1.2)
            d1 = self.diamonds_stable(ui, "bp_city_recheck", tries=2)
            # 2026-11-10：主城限时图标轮换后可能整天都没有战令入口 → 这是「今天没得做」，
            # 不是脚本坏了：跳过（带 noop_ok），别让整轮 FAIL 掩盖真正的问题。
            return TaskResult(True,
                              f"跳过：今天主城没有「勇者计划」入口（候选槽位都没进战令页）；"
                              f"钻石 {d0}→{d1}",
                              {"diamonds_before": d0, "diamonds_after": d1,
                               "noop_ok": True})

        claimed_tasks = self._claim_tasks(ui)
        if claimed_tasks < 0:
            return TaskResult.fail("点到了付费确认（橙色 CTA），已返回；钻石必须人工复核",
                                   {"diamonds_before": d0})

        free_track = self._claim_free_track(ui)
        if free_track < 0:
            return TaskResult.fail("免费奖励列弹出了付费确认（橙色 CTA），已返回",
                                   {"diamonds_before": d0})

        ui.press(L.BP_BACK, 220, label="bp_back", expect="none")
        ui.wait(1.5)
        drew = self._daily_free_draw(ui)
        # 召唤结果页可能要按两次返回才回主城；浮层/战报页残留会让钻石读成 None（2026-11-07 实测）
        for _ in range(3):
            if ui.state() == vision.State.MAIN_CITY:
                break
            ui.press(L.BACK, 220, expect="none")
            ui.wait(1.2)
        if ui.state() != vision.State.MAIN_CITY:
            if not MainCity(ui).ensure():
                log.warn("  勇者计划：收尾回不到主城，钻石读数只能标记为未知")
        ui.wait(0.6)

        d1, s1, _end = self._diamonds_retry(ui, "end")
        consumed = (d0 - d1) if (d0 is not None and d1 is not None) else None
        log.info(f"  勇者计划：结束后钻石={d1}（变化={consumed}）；"
                 f"任务领取 {claimed_tasks}，免费等级奖励 {free_track}，免费一抽={drew}")
        stats = {"claimed_tasks": claimed_tasks, "free_track": free_track,
                 "free_draw": drew, "diamonds_before": d0, "diamonds_after": d1,
                 "diamonds_consumed": consumed}
        if consumed is not None and consumed > 0:
            log.error(f"  勇者计划：钻石减少了 {consumed}！按钮证据不足，BP 判定失败")
            return TaskResult.fail(f"钻石减少 {consumed}，不符合「只做免费」", stats)
        if consumed is None:
            # 2026-11-09 假成功审计 C1：缺证不能报 OK。已重试 4 次并回主城，仍读不到
            # 只可能是画面被别的东西遮住——这时的「0 变化」是猜的，只能记失败。
            return TaskResult.fail(
                "战令：结束后钻石读数失败（已重试并回主城，前后对比仍缺证），"
                "无法确认未花钻", stats)
        return TaskResult(True, f"战令免费：任务 {claimed_tasks}，等级奖励 {free_track}，"
                                f"免费一抽 {drew}，钻石 0 变化", stats)



class RelicTask(_RewardTask):
    """圣物：升级页「一键升级」→ 升星页大按钮 → 羁绊页逐行升级 → 圣物祝福。"""

    name = "relic"
    title = "圣物"
    category = "upgrade"

    @staticmethod
    def _relic_confirm_open(im) -> bool:
        """圣物确认框是否开着：居中弹窗，左「取消」右「确定」。

        2026-11-08 实测（真帧 tests/fixtures/relic_confirm_open.png）：这类弹窗的
        「取消」是暗红 (197,126,104)，`vision.confirm_dialog` 的 (235,700) 红点判据
        要求 G<120 → 恒 False；全库 167 张帧上 confirm_dialog **一次都没 True**。
        于是「一键升级」弹了确认框也被当成没弹 → 白点 3 次、记 0 次升级。
        """
        if not textocr.available():
            return False
        try:
            txt = textocr.read_text(im, L.RELIC_CONFIRM_ROW)
        except Exception:  # noqa: BLE001
            return False
        return all(k in txt for k in L.RELIC_CONFIRM_KEYS)

    @staticmethod
    def _confirm(ui) -> bool:
        """升级/升星/羁绊点了以后如果弹了确认框，点金色「确定」。

        必须先确认弹窗真的存在，否则盲点会点到面板上的圣物图标、弹出详情页。
        """
        im = ui.screen("relic_ok")
        if not RelicTask._relic_confirm_open(im):
            return False
        for pos in L.RELIC_CONFIRM_FALLBACKS:
            if vision.is_gold(im, *pos, r=16):
                ui.press(pos, 220)
                ui.wait(1.6)
                return True
        # 认到「取消/确定」但金钮没认到（字压在上面）：用实测中心兜底
        ui.press(L.RELIC_CONFIRM, 220)
        ui.wait(1.6)
        return True

    @staticmethod
    def _relic_res(im) -> tuple[int, int] | None:
        """升级页的材料进度（实测「690/800」在 (300,1020,470,1075)）。

        2026-11-07 复核：旧的红点判据扫 (560..670, 1010..1100) 在真页红像素恒 0，
        `L.RELIC_ONEKEY` 也落在米色空白上——「一键升级」其实是**文字链接**，
        有没有可升级的圣物只能靠点完之后游戏自己给的信（toast / 确认框 / 材料变化）。
        """
        try:
            text = textocr.read_text(im, L.RELIC_PROGRESS_BOX)
            res = textocr.read_fraction(text)
            if res:
                return res
            # 2026-11-08：实测偶发整框读空（before/after 都 None → 「材料仍 None」
            # 判据空转，真有可升级的圣物也会被当成没有）。先用更宽的框重读，
            # 再在合并文本里按「数字/数字」形状捞一次。
            wide = textocr.read_text(im, L.RELIC_PROGRESS_BOX_WIDE)
            res = textocr.read_fraction(wide)
            if res:
                return res
            m = re.search(r"(\d{1,4})\s*[/|lI]\s*(\d{1,4})", f"{text} {wide}")
            if m and int(m.group(2)) > 0:
                return (int(m.group(1)), int(m.group(2)))
            log.info("  圣物：材料进度框读不到内容（OCR 没认出「N/M」），本次按读不到处理")
            return None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _relic_toast(im) -> str:
        """点「一键升级」后 0.7s 顶部那条 toast（实测「暂无可升级圣物」，1.7s 后消失）。"""
        try:
            return textocr.read_text(im, L.RELIC_TOAST_BOX)
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _relic_head(im) -> str:
        """圣物页页头 OCR（圣物祝福 / 属性总览 / 圣物总等级）。该页没有标题模板。"""
        try:
            return textocr.read_text(im, L.RELIC_PAGE_HEAD)
        except Exception:  # noqa: BLE001
            return ""

    OUTSIDE = (700, 640)   # 居中弹窗外的空白处（点它可以关闭）

    # 羁绊页右侧「升级」按钮列（设备坐标 x0,x1,y0,y1）
    BOND_SCAN = (480, 700, 250, 960)

    @staticmethod
    def _bond_buttons(im) -> list[tuple[int, int]]:
        """动态找羁绊页每行右侧的「升级」按钮（实测填充色 222,180,99，R−B≈123）。

        固定 y 会因为页面滚动位置不同而整体偏上（2026-10-29 实测偏了约 40px），
        所以按颜色聚类找，按钮中心直接当点击点。
        """
        x0, x1, y0, y1 = RelicTask.BOND_SCAN
        pts: set[tuple[int, int]] = set()
        for y in range(y0, min(y1, im.height), 2):
            for x in range(x0, min(x1, im.width), 2):
                R, G, B = im.getpixel((x, y))
                if R >= 195 and G >= 135 and (R - B) >= 120 and (G - B) >= 60:
                    pts.add((x, y))
        out: list[tuple[int, int]] = []
        while pts:
            seed = pts.pop()
            q = deque([seed])
            xs = [seed[0]]
            ys = [seed[1]]
            while q:
                cx, cy = q.popleft()
                for dx in (-2, 0, 2):
                    for dy in (-2, 0, 2):
                        np_ = (cx + dx, cy + dy)
                        if np_ in pts:
                            pts.discard(np_)
                            q.append(np_)
                            xs.append(np_[0])
                            ys.append(np_[1])
            if len(xs) < 120:                 # 太小 = 文字/图标碎片
                continue
            bw, bh = max(xs) - min(xs), max(ys) - min(ys)
            if bw < 60 or bh > 90:            # 按钮是扁长条，方形/竖条都是图标
                continue
            out.append((round(sum(xs) / len(xs)), round(sum(ys) / len(ys))))
        return sorted(out, key=lambda p: p[1])

    @staticmethod
    def _guard(ui) -> bool:
        """误触打开的道具/详情弹窗：点弹窗外关闭。"""
        if not vision.tooltip_open(ui.screen("guard")):
            return False
        for pos in ((700, 640), (60, 950), (700, 250)):
            ui.press(pos, 150, expect="none")   # 2026-11-04：关弹窗是导航类点击，不做空点补偿（每次白等 8s）
            ui.wait(0.9)
            if not vision.tooltip_open(ui.screen("guard2")):
                return True
        ui.press(L.BACK, 220, expect="none")
        ui.wait(1.2)
        return True

    def _page_kind(self, im) -> str:
        """当前在哪一页（up/star/bond/空）。亮度判据不够时就靠它兜底。"""
        head = self._relic_head(im)
        if "圣物总等级" in head:
            return "up"
        if len(self._bond_buttons(im)) >= 2:
            return "bond"
        try:
            f = textocr.read_fraction(textocr.read_text(im, (160, 1120, 300, 1180)))
        except Exception:  # noqa: BLE001
            f = None
        if f:
            return "star"
        return ""

    def _switch_tab(self, ui, pos, kind: str = "") -> bool:
        """切页签并确认真的切过去了（底部页签选中时更亮；亮度不够再用 OCR 兜底）。

        升星/升级完常有「获得奖励」弹窗，第一次点击会被弹窗吃掉，所以要重试。
        2026-11-08：页签坐标从 y=1215 修正到 y=1260，并补 kind 兜底——羁绊页的
        选中亮度没有实测样本，只靠 R>170 有可能把「已在羁绊页」误判成切换失败。
        """
        for _ in range(3):
            # expect="none"：点「已经选中的页签」画面必然不动，用默认的「变化」
            # 校验只会白等 4 个补偿点约 8 秒，还把它记成「空点」误报（实测
            # logs\_full5_142032.log 14:26:26 点已经在的「升级」页签）。
            # 切页成功与否由下面的亮度 / OCR 判据自己认。
            ui.press(pos, 220, label="relic_tab", expect="none")
            ui.wait(1.2)
            im = ui.screen("tab")
            R, G, B = vision.avg(im, *pos, r=8)
            if R > 170 and (R - B) > 60:
                return True
            if kind and self._page_kind(im) == kind:
                return True
        return False

    @classmethod
    def _act(cls, ui, pos) -> bool:
        """点一下升级类按钮并判断是否真的生效。

        生效的三种表现：弹确认框（点掉）、直接生效（画面变化无弹窗）、
        材料不足（弹出紫色「获取途径」说明 → 关掉且不算成功）。
        """
        ui.press(pos, 220)
        ui.wait(2.2)
        im = ui.screen("act_after")
        if vision.tooltip_open(im):
            cls._guard(ui)          # 材料不足 → 弹「获取途径」，不算成功
            return False
        return cls._confirm(ui)     # 只有真的弹出确认框并点掉才算成功

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        im = self.enter(ctx, L.BLD_RELIC, 1.8)
        if im is None:
            return TaskResult.fail("回不到主城")
        if textocr.available():
            head = self._relic_head(im)
            if head and not any(k in head for k in L.RELIC_PAGE_ANCHORS):
                log.warn(f"  圣物：入口 {L.BLD_RELIC} 进的不是圣物页（页头 OCR：{head[:40]}），"
                         f"退回主城跳过本任务")
                ui.press(L.BACK, 250, expect="none")
                ui.wait(1.0)
                MainCity(ui).ensure()
                return TaskResult.fail("进不去圣物页（入口被活动横幅挡住或图标换位）")

        ups = stars = bonds = bless = 0

        # 1) 升级页：一键升级（红点=有可升级的）；成功后红点会消失
        if not self._switch_tab(ui, L.RELIC_TAB_UP, "up"):
            log.warn(f"  圣物：升级页签 {L.RELIC_TAB_UP} 连点 3 次都没切换成功，后面按当前页继续")
        for i in range(3):
            im = ui.screen("relic_up")
            before = self._relic_res(im)
            ui.press(L.RELIC_ONEKEY, 200, label="relic_onekey", expect="none")
            ui.wait(0.7)                 # toast 只在 ~0.7s 那一帧可见，1.7s 就消失
            fast = ui.screen("relic_onekey_fast")
            toast = self._relic_toast(fast)
            if "暂无可升级" in toast:
                log.info(f"  一键升级：游戏提示「暂无可升级圣物」→ 现在没有可升级的圣物"
                         f"（真状态，材料 {before}）")
                break
            if vision.tooltip_open(fast):
                self._guard(ui)          # 材料不足，弹了获取途径
                log.info("  一键升级：弹「材料不足/获取途径」，本页不再点")
                break
            if self._confirm(ui):        # 有确认框，点掉了
                ups += 1
                log.info(f"  一键升级：确认框已点掉，算 1 次（材料 {before}）")
                continue
            ui.wait(1.3)
            after = self._relic_res(ui.screen("relic_up2"))
            if before and after and after != before:
                ups += 1
                log.info(f"  一键升级：材料进度 {before} → {after}，算 1 次")
                continue
            # 2026-11-08 真帧：材料行写 "560/900" 时点下去游戏什么也不弹，
            # "4万/800" 时才弹确认框 → 左小右大就是材料不够，直接这么写结论。
            if after and after[1] > 0 and after[0] < after[1]:
                log.info(f"  一键升级：材料不足（有 {after[0]}，一次一键升级要 {after[1]}），"
                         f"点了也不会有确认框，本页收手")
            else:
                log.warn(f"  一键升级：点 {L.RELIC_ONEKEY} 后既没有提示也没确认框、"
                         f"材料仍 {after}，收手")
            break

        # 2) 升星页：有大金色「升星」就点
        if self._switch_tab(ui, L.RELIC_TAB_STAR, "star"):
            im = ui.screen("relic_star")
            if vision.is_gold(im, *L.RELIC_STAR_ONE, r=16):
                log.info("  升星：按钮可点，尝试升星")
                if self._act(ui, L.RELIC_STAR_ONE):
                    stars += 1
                self._guard(ui)
                ui.press(RelicTask.OUTSIDE, 150, expect="none")
                ui.wait(0.6)
            else:
                R, G, B = vision.avg(im, *L.RELIC_STAR_ONE, r=16)
                log.warn(f"  升星：按钮 {L.RELIC_STAR_ONE} 不是金色（采样 RGB={R},{G},{B}），"
                         f"无法升星——不是点击失败")

        # 3) 羁绊页：逐行点「升级」（按行内按钮颜色动态定位）
        if self._switch_tab(ui, L.RELIC_TAB_BOND, "bond"):
            tried: set[int] = set()
            rescanned = False
            inactive = 0     # 2026-11-04：羁绊按钮常是「金色但未激活」（右侧写全部达到神话N星 1/2）
            for _ in range(8):
                self._guard(ui)
                im = ui.screen("relic_bond")
                btns = [p for p in self._bond_buttons(im)
                        if (p[1] // 40) not in tried]
                if not btns:
                    if not rescanned:
                        # 升级成功后的奖励弹窗会盖住按钮列：点空白关掉再扫一次
                        rescanned = True
                        ui.press(RelicTask.OUTSIDE, 150, expect="none")
                        ui.wait(1.2)
                        continue
                    # 仍检测不到按钮时退回固定行高（本页常见 348/532/715/898）
                    for y in L.RELIC_BOND_YS:
                        if (y // 40) in tried:
                            continue
                        if not vision.is_gold(im, L.RELIC_BOND_X, y, r=14):
                            continue
                        tried.add(y // 40)
                        log.info(f"  羁绊固定行 y={y}：点击升级")
                        if self._act(ui, (L.RELIC_BOND_X, y)):
                            bonds += 1
                    break
                pos = btns[0]
                tried.add(pos[1] // 40)
                log.info(f"  羁绊按钮 {pos}：点击升级")
                # 2026-11-04：不用 _act（它带 ±8/±16 补偿，未激活按钮每次白等 8s）。
                # 单次点击 → 画面完全没变 = 该行条件未达成；连续 2 行无反应就整页停手。
                ui.press(pos, 220, expect="none")
                ui.wait(1.6)
                after = ui.screen("bond_after")
                if vision.similar(im, after):
                    inactive += 1
                    log.info(f"  羁绊按钮 {pos}：点击后画面无变化（该行条件未达成，"
                             f"右侧「全部达到神话N星」未满），跳过")
                    if inactive >= 2:
                        log.info("  羁绊：连续 2 行按钮无反应 → 条件未达成，停止本页")
                        break
                    continue
                inactive = 0
                if vision.tooltip_open(after):
                    self._guard(ui)
                    log.info(f"  羁绊按钮 {pos}：材料不足（弹获取途径），不算成功")
                elif self._confirm(ui):
                    bonds += 1
                self._guard(ui)

        # 4) 圣物祝福（右上角图标只在升星/升级页有；羁绊页没有这颗，2026-11-04 实测）
        self._guard(ui)
        if not self._switch_tab(ui, L.RELIC_TAB_STAR, "star"):
            log.warn(f"  圣物祝福：切回升星页 {L.RELIC_TAB_STAR} 失败，祝福可能点不到")
        ui.press(L.RELIC_BLESS, 220)
        ui.wait(2.2)
        im = ui.screen("bless")
        if vision.is_gold(im, *L.RELIC_BLESS_UP, r=16):
            # 2026-11-04：弹窗顶部写着「材料不足」(113/170) 时按钮仍是金色但点击无反应；
            # 单次点击 + 对比画面即可判定，不再走 _act 的 ±8/±16 补偿（白等 8s）。
            log.info("  圣物祝福：升阶按钮是金色，单次点击并核对画面")
            ui.press(L.RELIC_BLESS_UP, 220, expect="none")
            ui.wait(1.8)
            after = ui.screen("bless_after")
            if vision.similar(im, after):
                log.info(f"  圣物祝福：点击 {L.RELIC_BLESS_UP} 后画面无变化"
                         f"（弹窗顶部「材料不足」/条件未达成），不算成功")
            elif vision.tooltip_open(after):
                self._guard(ui)
            elif self._confirm(ui):
                bless = 1
        else:
            R, G, B = vision.avg(im, *L.RELIC_BLESS_UP, r=16)
            log.warn(f"  圣物祝福：弹窗没出现或按钮 {L.RELIC_BLESS_UP} 不是金色"
                     f"（采样 RGB={R},{G},{B}）")
        if bonds == 0:
            log.info("  羁绊：本页 0 次升级（每行都无确认框=属性未达成或材料不足）")
        ui.press(RelicTask.OUTSIDE, 150, expect="none")
        ui.wait(0.6)

        self.back(ctx)
        return TaskResult(True,
                          f"圣物：升级 {ups} / 升星 {stars} / 羁绊 {bonds} / 祝福 {bless}",
                          {"ups": ups, "stars": stars, "bonds": bonds, "bless": bless})


class StarUpTask(_RewardTask):
    name = "star"
    title = "英雄升星"
    category = "upgrade"

    @staticmethod
    def _hint(im) -> str:
        """材料区 OCR（抓「请选择升星材料」「1/1」「5/7」这类提示与数字）。"""
        try:
            # 2026-11-08：「请选择升星材料」在页面顶部 bbox(278,333)-(427,356)，
            # 旧框从 y=520 起，永远读不到这句话。
            return textocr.read_text(im, (60, 290, 700, 1060))[:120]
        except Exception:  # noqa: BLE001
            return ""

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        im = self.enter(ctx, L.BLD_STAR, 1.6, page="hero_star")
        if im is None:
            return TaskResult.fail("进不去英雄升星页（入口被活动横幅挡住或图标换位）")
        n = 0
        for _ in range(3):
            im = ui.screen("star")
            if not vision.is_gold(im, *L.STAR_BATCH, r=16):
                break
            ui.press(L.STAR_BATCH, 220)
            ui.wait(1.5)
            ui.press(L.STAR_CONFIRM, 220)
            ui.wait(2.0)
            ui.press(L.BLANK, 150, expect="none")
            # 2026-11-09 假成功审计：点完要复核 —— 批量按钮仍是金色且画面没变
            # 说明确认框没生效（材料/条件不满足），不能算一次。
            after = ui.screen("star_batch_after")
            if vision.is_gold(after, *L.STAR_BATCH, r=16) and vision.similar(im, after):
                log.info(f"  英雄升星：点了批量升星+确认后画面没变化（批量钮仍金色），"
                         f"本次不计入（已 {n} 次）")
                break
            n += 1
        if n == 0:
            # 2026-11-04：批量按钮是灰的（没有符合条件的英雄）时，再单体试一次：
            # 选第 1 个英雄 → 点金色「升星」；若弹「材料不足/获取途径」就 warn 停手
            # （用户口径：资源不足导致无动作，只要脚本正确识别并停止 = 通过）。
            # 2026-11-04 复跑修正：材料格必须点「卡面头像区」并校验高亮/勾选态真的变了，
            # 不变化就不点升星；升星后必须校验画面变化才算 1 次（旧版盲点 (200,734) 落在
            # 卡片下缘的数字条上，点不出选中态，却照样去点升星）。
            im = ui.screen("star")
            if not vision.is_gold(im, *L.STAR_ONE, r=16):
                R, G, B = vision.avg(im, *L.STAR_ONE, r=16)
                log.warn(f"  英雄升星：批量与单体按钮都不是金色（单体采样 RGB={R},{G},{B}），跳过")
            else:
                log.info("  英雄升星：批量按钮是灰的，改为单体试第 1 个英雄")
                ui.press(L.STAR_HERO1, 200, expect="none")
                ui.wait(1.2)
                ui.press(L.STAR_ONE, 220, expect="none")
                ui.wait(1.8)
                after = ui.screen("star_one")
                if vision.tooltip_open(after):
                    log.warn(f"  英雄升星：单体升星弹「材料不足/获取途径」（{L.STAR_ONE}），"
                             f"无可用碎片，停止（资源不足按通过口径）")
                    ui.press(L.BLANK, 150, expect="none")
                elif vision.similar(im, after):
                    log.warn(f"  英雄升星：点「升星」{L.STAR_ONE} 后画面无变化"
                             f"（按钮未激活/材料不足），停止")
                else:
                    # 实测：点升星先进入「请选择升星材料」界面（同英雄副本 1/1、其它材料 1/7）。
                    # 材料卡实图量测：卡面 x150~234 / y618~745（头像是可点区），
                    # 下缘 730+ 是星级与「1/1」数字条，点那里不会切换选中态。
                    # 2026-11-04 第 4 轮实测：点头像会弹出「选择英雄」窗（已选择 1/1 + 绿勾），
                    # 必须先按该窗的金色「确定」把材料放进槽位，否则后面升星按钮不响应。
                    log.info("  英雄升星：进入选材料界面，点材料格并确认「选择英雄」窗")
                    mat0 = ui.screen("star_mat_before")
                    picker = None
                    for k, pos in ((1, L.STAR_MAT1), (2, L.STAR_MAT1B)):
                        ui.press(pos, 200, expect="none")
                        ui.wait(1.5)
                        cur = ui.screen(f"star_mat_tap{k}")
                        if vision.star_material_picker(cur):
                            log.info(f"  英雄升星：点材料格 {pos} 弹出「选择英雄」窗，材料槽已选 1/1")
                            picker = cur
                            break
                        dr = vision.diff_ratio(mat0, cur, L.STAR_MAT1_BOX)
                        log.info(f"  英雄升星：点材料格 {pos} 后卡面差异 {dr:.3f}，未弹选择窗")
                    if picker is None:
                        log.warn(f"  英雄升星：材料格 {L.STAR_MAT1} / {L.STAR_MAT1B} 点击后"
                                 f"既未弹「选择英雄」也无选中变化，停止，不盲点升星")
                        ui.press(L.BLANK, 150, expect="none")
                    else:
                        ui.press(L.STAR_MAT_CONFIRM, 220, expect="none")
                        ui.wait(1.6)
                        picked = ui.screen("star_mat_picked")
                        if vision.star_material_picker(picked):
                            log.warn("  英雄升星：点「确定」后选择窗仍在，材料未确认，停止")
                            ui.press(L.BLANK, 150, expect="none")
                        else:
                            dr = vision.diff_ratio(mat0, picked, L.STAR_MAT1_BOX)
                            log.info(f"  英雄升星：材料确认后回到材料页（卡面差异 {dr:.3f}），点升星")
                            ui.press(L.STAR_ONE, 220, expect="none")
                            # 2026-11-04 第 5 轮：补一次 0.5s 快速帧，抓「材料不足/已满星」这类短提示
                            ui.wait(0.5)
                            fast = ui.screen("star_apply_fast")
                            ui.wait(1.3)
                            apply = ui.screen("star_apply")
                            log.info(f"  英雄升星：点升星后 0.5s 差异 "
                                     f"{vision.diff_ratio(picked, fast):.3f}，"
                                     f"1.8s 差异 {vision.diff_ratio(picked, apply):.3f}")
                            fast_hint = self._hint(fast)
                            if "请选择升星材料" in fast_hint:
                                # 2026-11-07 实测：材料槽已选 1/1、按了「确定」，
                                # 再点升星时游戏仍闪一条「请选择升星材料」（1.3s 后消失）。
                                # 说明材料没真正进槽位（或星级/数量不满足）→ 按资源不足收手。
                                log.info(f"  英雄升星：点「升星」后游戏又提示「请选择升星材料」"
                                         f"（材料没进槽位或条件不满足），停止（界面：{fast_hint}）")
                                ui.press(L.BLANK, 150, expect="none")
                            elif vision.tooltip_open(apply):
                                log.warn("  英雄升星：材料已选中但点升星弹「材料不足/获取途径」，停止")
                                ui.press(L.BLANK, 150, expect="none")
                            elif vision.similar(picked, apply):
                                log.warn("  英雄升星：材料已选中但点升星画面无变化（按钮不可用），停止")
                            else:
                                log.info(f"  英雄升星：点升星后画面变化，点确认 {L.STAR_CONFIRM}")
                                ui.press(L.STAR_CONFIRM, 220, expect="none")
                                ui.wait(2.2)
                                done = ui.screen("star_done")
                                if vision.similar(apply, done):
                                    log.warn("  英雄升星：点确认后画面无变化，未完成升星")
                                else:
                                    # 星级变化的证据：回到英雄页后英雄格区域与进材料前不同
                                    dr = vision.diff_ratio(im, done, (60, 840, 660, 1200))
                                    log.info(f"  英雄升星：完成 1 次（英雄格区域差异 {dr:.3f}）")
                                    n += 1
        self.back(ctx)
        return TaskResult(True, f"批量升星 {n} 次", {"times": n})


class EquipmentTask(_RewardTask):
    """装备强化/升星：强化「一键50级」⇄ 升星「一键升星」交替，直到金币不足且没有可升星。

    2026-10-29 真机流程：
      1. 进铁匠铺时若装备可升星，游戏会自动弹「一键升星」批量窗；
      2. 没有自动弹的话：强化页点「一键50级」→ 升星页点「一键升星」→ 回强化页再点，
         循环到「一键50级」价格变红（金币不足）且升星窗显示「没有符合条件的装备」。
    """

    name = "equipment"
    title = "装备强化/升星"
    category = "upgrade"

    @staticmethod
    def _tab(ui, pos, label: str) -> bool:
        """切页签并确认选中（选中的图标更亮：R>170 且 R−B>45；未选中约 (124,99,76)）。"""
        for _ in range(3):
            ui.press(pos, 220)
            ui.wait(1.4)
            R, G, B = vision.avg(ui.screen("forge_tab"), *pos, r=10)
            if R > 170 and (R - B) > 45:
                return True
        log.warn(f"  {label}页签没切过去")
        return False

    @staticmethod
    def _close_dialog(ui) -> bool:
        """关掉「一键升星」批量弹窗（右上角红 X；找不到就点固定点）。"""
        for _ in range(2):
            im = ui.screen("forge_dlg")
            if vision.forge_star_dialog(im) == "none":
                return False
            pts = ui._find_close_buttons(im)
            pos = (int(pts[0][0]), int(pts[0][1])) if pts else L.FORGE_STAR_POPUP_X
            for dx, dy in ((0, 0), (-12, 6), (10, 8)):
                ui.press((pos[0] + dx, pos[1] + dy), 150)
                ui.wait(0.8)
                if vision.forge_star_dialog(ui.screen("forge_dlg2")) == "none":
                    return True
        return False

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        im = self.enter(ctx, L.BLD_FORGE, 2.0)
        if im is None:
            return TaskResult.fail("回不到主城")

        enh = stars = 0

        # 1) 进入时游戏可能自动弹「一键升星」批量窗（可升星时才会弹）
        st = vision.forge_star_dialog(im)
        if st != "none":
            log.info(f"  进入铁匠铺自动弹出升星窗（{'有可升星' if st == 'ready' else '没有符合条件的装备'}）")
            if st == "ready":
                before = ui.screen("forge_star_before")
                ui.press(L.FORGE_STAR_POPUP, 250)
                ui.wait(2.6)
                # 2026-11-09 假成功审计 M16：点完要复核 —— 弹窗老板样（按钮还金、
                # 画面几乎没变）说明这一下没升成，不能计数
                after = ui.screen("forge_star_after")
                still = (vision.forge_star_dialog(after) == "ready"
                         and vision.is_gold(after, *L.FORGE_STAR_POPUP, r=16))
                if still and vision.similar(before, after):
                    log.info("  进店升星窗：点了「升星」但弹窗没变（按钮仍金），不计入")
                else:
                    stars += 1
            self._close_dialog(ui)

        # 2) 强化 ⇄ 升星 交替，直到两头都到上限
        gold_out = star_out = False
        for cycle in range(1, 5):
            # --- 强化页：一键50级 一直点到金币不足 ---
            if self._tab(ui, L.FORGE_TAB_ENHANCE, "强化"):
                for _ in range(15):
                    im = ui.screen("forge_enh")
                    if not vision.forge_cost_affordable(im, L.FORGE_COST_BOX):
                        gold_out = True
                        log.info(f"  第 {cycle} 轮强化：一键50级价格变红（金币不足），停")
                        break
                    # 2026-11-08：一键50级只改几行小字，实测 diff 0.017（阈值 0.02）
                    # 被判空点 → 赔 4 个补偿点 ≈8s，还把 (360,1095) 记成怪状态。
                    # 改成点击数不校验，「这次强化真发生了没」看价格文字变没变。
                    cost0 = textocr.read_text(im, L.FORGE_COST_BOX) if textocr.available() else ""
                    ui.press(L.FORGE_ENHANCE_50, 250, label="forge_enhance_50", expect="none")
                    ui.wait(2.2)
                    im = ui.screen("forge_enh2")
                    if vision.confirm_dialog(im):          # 万一弹了确认框
                        if vision.is_gold(im, 360, 760, r=16):
                            ui.press((360, 760), 220)
                            ui.wait(1.6)
                            im = ui.screen("forge_enh3")
                        else:
                            ui.press(L.BLANK, 150, expect="none")
                    self._guard_tooltip(ui)
                    cost1 = textocr.read_text(im, L.FORGE_COST_BOX) if textocr.available() else ""
                    if cost0 and cost1 and cost0 == cost1:
                        log.warn(f"  第 {cycle} 轮强化：点了一键50级但价格没变（{cost0}），停")
                        gold_out = True
                        break
                    enh += 1
                else:
                    log.info(f"  第 {cycle} 轮强化：点到 {enh} 次仍未耗尽，先转升星")

            # --- 升星页：一键升星 ---
            if self._tab(ui, L.FORGE_TAB_STAR, "升星"):
                ui.press(L.FORGE_STAR_ONEKEY, 250)
                ui.wait(1.8)
                st = vision.forge_star_dialog(ui.screen("forge_star"))
                if st == "ready":
                    before = ui.screen("forge_star_before2")
                    ui.press(L.FORGE_STAR_POPUP, 250)
                    ui.wait(2.6)
                    # 2026-11-09 假成功审计 M16：同 M15，点完必须有证据
                    after = ui.screen("forge_star_after2")
                    still = (vision.forge_star_dialog(after) == "ready"
                             and vision.is_gold(after, *L.FORGE_STAR_POPUP, r=16))
                    if still and vision.similar(before, after):
                        log.info(f"  第 {cycle} 轮升星：点了「升星」但弹窗没变"
                                 f"（按钮仍金），不计入")
                        star_out = True
                    else:
                        stars += 1
                        star_out = False
                        log.info(f"  第 {cycle} 轮升星：一键升星成功 ×1")
                    self._close_dialog(ui)
                else:
                    star_out = True
                    log.info(f"  第 {cycle} 轮升星：没有符合条件的装备")
                    if st == "locked":
                        self._close_dialog(ui)

            if gold_out and star_out:
                log.info(f"  强化金币不足且无可升星（共 {cycle} 轮），结束")
                break

        self.back(ctx)
        return TaskResult(True, f"装备：一键50级 {enh} 次 / 一键升星 {stars} 次",
                          {"enhance": enh, "star": stars})

    @staticmethod
    def _guard_tooltip(ui) -> None:
        """强化后偶尔弹道具提示窗，点弹窗外关掉。"""
        im = ui.screen("forge_tip")
        if vision.tooltip_open(im):
            for pos in ((700, 640), (60, 950)):
                ui.press(pos, 150)
                ui.wait(0.7)
                if not vision.tooltip_open(ui.screen("forge_tip2")):
                    return


# 注：共鸣（resonance）已按需求移除 —— 2026-10-29，功能不再需要，坐标也不再维护。


class HeroLevelTask(_RewardTask):
    """英雄升级：只升「实际培养」（白色等级）里等级最低的那个，保持队伍等级均衡。

    2026-10-29 真机规则：
      - 英雄页卡片的等级文字：白色 = 实际培养的；蓝色 = 共鸣带出来的（不用管）；
      - 升级动作是详情页的「进阶」，消耗进阶石，需求随等级涨（700 级要 3200、800 级要 3500）；
        不够时会弹「进阶石」获取途径窗；
      - 共鸣支柱 = 队伍里等级最低的英雄（共鸣页会写「共鸣支柱：剁椒牛头(700级)」），
        把最低的升上去，全队共鸣等级才会跟着涨。
    """

    name = "hero_level"
    title = "英雄升级/进阶"
    category = "upgrade"

    @staticmethod
    def _scan_used(ui) -> list[tuple[int, int]]:
        """英雄页上等级是白色（非蓝色共鸣）的卡片位置。"""
        im = ui.screen("hero_grid")
        used = []
        for cy, y0, y1 in L.HERO_CARD_ROWS:
            for cx in L.HERO_CARD_XS:
                if not vision.hero_level_is_resonance(im, cx, y0, y1):
                    used.append((cx, cy))
        return used

    _DETAIL_BOX = (555, 165, 720, 245)     # 详情页右上「无损继承」，列表页这里是空白

    @classmethod
    def _detail_open(cls, im) -> bool:
        """英雄详情页是否真的打开了。

        2026-11-07 实测：列表页该框为空，详情页稳定读到「无损继承」（6/6 帧命中）。
        比看 diff 可靠——点「锁定/未解锁」卡片也会有大 diff，但页面不是等级详情。
        """
        try:
            return "无损继承" in textocr.read_text(im, cls._DETAIL_BOX)
        except Exception:
            return False

    _DETAIL_POLL = 0.25      # 详情页上屏实测 1.32~1.91s，用轮询而不是固定等待
    _DETAIL_POLLS = 14       # 0.25 × 14 ≈ 3.5s

    @classmethod
    def _wait_detail(cls, ui, tag: str = "hero_chk") -> bool:
        """轮询等详情页出现。

        2026-11-07 实测：点卡片后详情页要 1.32~1.91s 才画出来，旧的固定
        `ui.wait(1.5)` 正好卡在临界值上，于是间歇性读到空文本、把卡片
        误判成「点不开」而整张跳过（一轮 4 张卡全废）。
        """
        for i in range(cls._DETAIL_POLLS):
            ui.wait(cls._DETAIL_POLL)
            if cls._detail_open(ui.screen(f"{tag}_{i}")):
                return True
        return False

    @classmethod
    def _open_card(cls, ui, pos) -> bool:
        """点英雄卡片进详情页，返回是否真的进去了。

        2026-11-07：卡片可能压在半屏位置（列表刚滚动过），点了不弹详情。
        以前不校验，接着按 BACK 会把「英雄页」直接退到主城，再读等级拿到 0.00 分；
        现在先确认详情页开了，没开就不 BACK（避免误退），由调用方跳过这张卡。
        """
        for i, (dx, dy) in enumerate(((0, 0), (0, -8), (0, 8), (-16, 0))):
            pt = (pos[0] + dx, pos[1] + dy)
            # 2026-11-07：卡片被半屏挡住时点了画面几乎不变（diff 0.005），
            # 这里用 expect="none"（进没进详情页由下面的 _detail_open 判定），
            # 否则会白做 4 个补偿点、还会把坐标登记成死点。
            ui.press(pt, 250, label="hero_open" if i == 0 else f"hero_open:{pos}",
                     expect="none")
            if cls._wait_detail(ui):
                return True
        return False

    @staticmethod
    def _back_to_grid(ui) -> None:
        ui.press(L.BACK, 220, expect="none")
        ui.wait(1.3)

    @staticmethod
    def _level(im):
        """读详情页等级：先试模板 OCR（青色数字），不中再用中文 OCR 读「等级NNN」。"""
        lv, score = ocr.read_level(im)
        if lv is not None:
            return lv, score
        try:
            line = textocr.find_line(im, ("等级",), box=(60, 800, 400, 900))
            if line:
                frac = textocr.read_remain(line[0], key="等级")
                if frac is not None:
                    return int(frac), 1.0
        except Exception:
            pass
        return None, score

    def _read_level(self, ui, pos):
        """打开英雄详情读等级（青色数字），然后返回列表。"""
        if not self._open_card(ui, pos):
            log.warn(f"  卡片 {pos} 点不开详情页（可能压在屏幕边上），跳过这张")
            return None, 0.0
        lv, score = self._level(ui.screen("hero_detail"))
        self._back_to_grid(ui)
        return lv, score

    def _advance(self, ui, pos, target) -> int:
        """打开英雄详情，交替「进阶 / 升50级」直到追平 target 或材料不足。

        2026-10-30 实测：
          - 大按钮的视觉中心 (360,1060) 点不动——当时的真实命中点在 (470,1060)；
            2026-11-07 界面改版后反过来：(470,1060) 与 (500,1060) 都落在右侧
            米色空白（diff 0.012/0.007），而底部「进阶」二字中心 (359,1099)
            diff 0.900 —— 现在 L.HERO_ADVANCE = (360, 1100)；
          - 「进阶」会先弹属性加成预览框，要点框里的 (360,917)，再点空白关掉「进阶成功」；
          - 进阶成功后按钮变成「升50级」，按一次 +50 级（消耗金币/英雄经验）；
          - 进阶石不够时按钮是禁用的，按了没有任何反应（不会弹获取途径窗）。
        """
        if not self._open_card(ui, pos):
            log.warn(f"  卡片 {pos} 点不开详情页，本次不进阶")
            return 0
        im = ui.screen("hero_adv")
        lv, _ = self._level(im)
        if lv is None:
            log.warn("  详情页没读到等级，跳过")
            self._back_to_grid(ui)
            return 0
        gained = 0
        stalls = 0
        for _ in range(20):
            if target is not None and lv >= target:
                break
            before = lv
            acted = False
            for pt in (L.HERO_ADVANCE, L.HERO_ADVANCE_ALT):
                # 2026-11-07：进阶石不足 / 已满级时按钮点了毫无变化（diff 0.000），
                # 用 expect="change" 会白做 8 个补偿点；是否有反应由下面的
                # hero_break_dialog / item_popup / _level 三个判据决定，
                # 而且两个候选点本来就会依次试。
                ui.press(pt, 260, expect="none")
                ui.wait(1.4)
                im = ui.screen("hero_adv2")
                if vision.hero_break_dialog(im):
                    ui.press(L.HERO_BREAK_CONFIRM, 260)
                    ui.wait(2.1)
                    ui.press(L.HERO_AFTER_BLANK, 180, expect="none")     # 关「进阶成功」浮层
                    ui.wait(0.9)
                    acted = True
                    log.info(f"  进阶成功（{before} 级，上限提升）")
                    break
                if vision.item_popup(im):
                    log.info(f"  进阶材料不足（当前 {lv} 级），关闭获取途径窗")
                    ui.press(L.HERO_BLANK, 150, expect="none")
                    ui.wait(0.9)
                    self._back_to_grid(ui)
                    return gained
                new_lv, _ = self._level(im)
                if new_lv is not None and new_lv != before:
                    lv = new_lv
                    acted = True
                    break
            if acted:
                stalls = 0
                if lv > before:
                    gained += lv - before
                    log.info(f"  升级成功：{lv} 级")
                continue
            stalls += 1
            if stalls >= 2:
                log.info(f"  按钮没反应（进阶石不足或已满级，当前 {lv} 级），停止")
                break
        self._back_to_grid(ui)
        return gained

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        MainCity(ui).tab(L.TAB_HERO)
        ui.wait(1.8)

        total_gain = 0
        for rnd in range(1, 4):
            used = self._scan_used(ui)
            levels = []
            for pos in used:
                lv, score = self._read_level(ui, pos)
                if lv is None:
                    log.warn(f"  卡片 {pos} 等级识别失败（得分 {score:.2f}），跳过")
                    continue
                levels.append((lv, pos))
            if not levels:
                log.warn("  没读到任何培养英雄的等级")
                break
            log.info(f"  已扫描英雄页可见的 {len(used)} 张培养卡片（更靠下的英雄需要先滚动页面）")
            levels.sort()
            log.info("  英雄等级：" + "，".join(f"{pos}={lv}" for lv, pos in levels))
            low_lv, low_pos = levels[0]
            second = levels[1][0] if len(levels) > 1 else None
            if second is None or low_lv >= second:
                # 等级已经均衡：仍然把最低的那个往上推（共鸣等级跟着涨），推到没材料为止
                log.info(f"  等级已均衡（{low_lv} 级），继续提升最低的 {low_pos} 直到材料不足")
                target = None
            else:
                log.info(f"  最低的是 {low_pos}（{low_lv} 级），目标追平 {second} 级")
                target = second
            gain = self._advance(ui, low_pos, target)
            total_gain += gain
            if gain == 0:
                log.info("  最低英雄这次升不动（进阶石不足），结束")
                break
            # 往下滚一屏，下一轮把后面的英雄也扫进来（英雄页一屏只显示 3 行）
            ui.dev.swipe(360, 1000, 360, 680, 500)
            ui.wait(1.0)

        self.back(ctx)
        return TaskResult(True, f"英雄升级：共提升 {total_gain} 级", {"gain": total_gain})
