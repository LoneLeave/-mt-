"""竞技 → 荣耀竞技场（2026-11-09 新增，用户同意恢复角斗场类任务后）。

**为什么需要它**：竞技页「荣耀竞技场」每天有 10 次挑战（2026-11-09 实测剩余 5/10），
但脚本此前只做「角斗场」——每天白丢 10 次 PVP 进度与赛季奖励。竞技类在 2026-10-30
被整体删除，恢复时只补了角斗场；这一条把剩下的次数也用掉。

**实测流程（2026-11-09 20:31~20:35，logs/screens/p4~p8*）**：
- 主城底栏「竞技」(555,1225) → 竞技一级页；
- 这一页「荣耀竞技场」那一行文字中心 **(190,677)**（点 (190,737) 会落到下一行的
  钻石说明浮层，别按行高 +60 去点）→ 荣耀竞技场页；
- 页内：钻石/排名/「挑战次数：5/10」/「阵容防守」「开始匹配」「战报」；
- 金色「开始匹配」(361,1086) → VS 对比页（2V2/3V3/5V5 三段数据）→ 金色「开始挑战」(496,1214)；
- 点「开始挑战」进自动战斗，战斗页有「跳过」(652,899)——本任务用 `ui.battle_finish`
  轮询跳过；结算页出现「挑战成功/挑战失败」+「确定」，随后自动回竞技页（次数 -1、排名上升）。

**永不点**：右上「商城」「奖励」「排行榜」（消费/广告入口，奖励页还会引导充值）、
「阵容防守」（会改防守阵）、底部「竞猜」。
"""
from __future__ import annotations

import re
import time

from .. import layout as L
from .. import log, textocr, vision
from ..pages import MainCity
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult


class GloryTask(BaseTask):
    name = "glory"
    title = "荣耀竞技场（把每日 10 次挑战打掉，别白丢）"
    category = "pvp"

    # ---------- 判据 ----------
    @staticmethod
    def _attempts(im):
        """页内「5/10」→ 剩余 5。读不到返回 None（不是 0，别误判成打完）。"""
        try:
            txt = textocr.read_text(im, L.GLORY_ATTEMPT_BOX)
        except Exception:
            return None
        m = re.search(L.GLORY_ATTEMPT_RE, txt or "")
        if not m:
            return None
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _at_page(im) -> bool:
        """在荣耀竞技场页：有「挑战次数」那一行，或底部有「开始匹配」。"""
        try:
            txt = textocr.read_text(im, L.GLORY_PAGE_BOX) or ""
        except Exception:
            txt = ""
        if "挑战次数" in txt:
            return True
        try:
            foot = textocr.read_text(im, (200, 1050, 520, 1120)) or ""
        except Exception:
            foot = ""
        return "开始匹配" in foot

    @staticmethod
    def _match_pos(im):
        """金色「开始匹配」按钮中心。"""
        return vision.gold_band_point(im, L.GLORY_MATCH_BOX, min_px=600, r=18)

    @staticmethod
    def _start_pos(im):
        """VS 对比页的「开始挑战」：先 OCR 找字，再退回金色兜底。"""
        try:
            for t, c, _bb, _s in textocr.read_lines(im, L.GLORY_START_BOX, min_score=0.5):
                if "开始挑战" in t:
                    return c
        except Exception:
            pass
        return vision.gold_band_point(im, L.GLORY_START_BOX, min_px=700, r=16)

    @staticmethod
    def _result(im):
        """结算页 OCR：True=胜 / False=负 / None=没认出来。"""
        try:
            txt = textocr.read_text(im, L.GLORY_RESULT_BOX) or ""
        except Exception:
            return None
        if "挑战成功" in txt:
            return True
        if "挑战失败" in txt:
            return False
        return None

    # ---------- 进入 ----------
    def _enter(self, ui) -> bool:
        im = ui.screen("glory_before")
        if self._at_page(im):
            return True
        for attempt in range(2):
            ui.press(L.TAB_ARENA, 250, label=f"glory_tab{attempt + 1}", expect="none")
            ui.wait(2.4)
            hub = ui.screen(f"glory_hub{attempt + 1}")
            pos = None
            try:
                for t, c, _bb, _s in textocr.read_lines(hub, L.GLORY_ENTRY_TEXT_BOX, min_score=0.5):
                    if "荣耀竞技场" in t:
                        pos = c
                        break
            except Exception:
                pos = None
            if pos is None:
                log.info("  荣耀竞技场：竞技页上没读到「荣耀竞技场」这一行，再试一次")
                continue
            ui.press(pos, 250, label="glory_entry", expect="none")
            ui.wait(3.0)
            im = ui.screen("glory_open")
            if self._at_page(im):
                return True
            log.info("  荣耀竞技场：点了「荣耀竞技场」但没进页（可能被浮层挡住），再试一次")
        log.warn("  荣耀竞技场：进不去（竞技页/入口可能又改了），本次跳过")
        return False

    # ---------- 一把 ----------
    @staticmethod
    def _promo_open(im) -> bool:
        """浮层判定：只认底部那行「点击空白处关闭」。

        晋级浮层会一直浮在竞技页上（实测 logs/screens/glory_left3_55.png：
        晋级成功 @(362,749)、点击空白处关闭 @(360,1220)），把金色「开始匹配」盖住；
        而「晋级成功」四个字在结算页里也会出现，不能单独当判据。
        """
        try:
            txt = textocr.read_text(im, L.GLORY_PROMO_BOX) or ""
        except Exception:
            return False
        return any(k in txt for k in L.GLORY_PROMO_KEYS)

    def _dismiss_promo(self, ui, im=None, tries: int = 3):
        """关掉压在竞技页上的浮层，返回关完之后（或原来）的画面。"""
        cur = im if im is not None else ui.screen("glory_promo_chk")
        for i in range(tries):
            if not self._promo_open(cur):
                return cur
            ui.press(L.GLORY_PROMO_BLANK, 200, label=f"glory_promo_blank{i + 1}", expect="none")
            ui.wait(1.2)
            cur = ui.screen(f"glory_promo_after{i + 1}")
        return cur

    def _one_fight(self, ui, idx: int):
        """打一把。返回 "win"/"lose"/"done"（打了没看清胜负）/None（没打起来）。

        时序（2026-11-09 实测）：开始匹配 → ~6s VS 页（开始挑战 y≈1215）→ 战斗 ~25s
        → 结算页（**只存在 2 秒**）→ 回本页；晋级时多一层「晋级成功」浮层。
        """
        im = self._dismiss_promo(ui, ui.screen(f"glory_pre{idx}"))
        if self._promo_open(im):
            log.info("  荣耀竞技场：「点击空白处关闭」的浮层关不掉，本次收手")
            return None
        before = self._attempts(im)
        pos = self._match_pos(im)
        if pos is None:
            log.info("  荣耀竞技场：没找到金色「开始匹配」（次数已用尽或界面未加载）")
            return None
        ui.press(pos, 250, label=f"glory_match{idx}", expect="none")

        start = None
        for _ in range(6):
            ui.wait(2.0)
            start = self._start_pos(ui.screen(f"glory_vs{idx}"))
            if start is not None:
                break
        if start is None:
            log.info("  荣耀竞技场：匹配后没出现「开始挑战」，本次收手")
            return None
        ui.press(start, 250, label=f"glory_start{idx}", expect="none")

        # 结算页只显示 2 秒，必须 1.2s 一轮；没看到也算打完（次数会 -1）
        for i in range(50):
            ui.wait(1.2)
            im = ui.screen(f"glory_battle{idx}_{i}")
            if self._promo_open(im):
                ui.press(L.GLORY_PROMO_BLANK, 200, label=f"glory_promo{idx}", expect="none")
                ui.wait(1.0)
                continue
            win = self._result(im)
            if win is not None:
                ui.press(L.GLORY_RESULT_OK, 200, label=f"glory_ok{idx}", expect="none")
                ui.wait(2.0)
                return "win" if win else "lose"
            now = self._attempts(im)
            if before is not None and now is not None and now < before:
                log.info(f"  荣耀竞技场：第 {idx} 把打完了（次数 {before}→{now}，结算页太快没读到胜负）")
                return "done"
            if self._at_page(im) and i > 6:
                log.info("  荣耀竞技场：回到竞技页但次数没变，可能没匹配上")
                return None
        log.info("  荣耀竞技场：等结算超时（50×1.2s），本次收手")
        return None

    def _buy_one(self, ui, before_att: int | None = None, d0: int | None = None,
                 ctx: TaskContext | None = None):
        """买 1 次挑战次数（钻石）。返回 (成功?, 花费钻石, 说明)。

        用户规则（2026-11-10）：钻石只允许用来买挑战次数 —— 这条路允许走，
        但必须有自证：弹窗里读出「花费 N」，点「购买」后要求挑战次数真的 +1；
        花掉多少由 run() 在主城顶栏前后对比给出（竞技页顶栏不是钻石）。
        绝不点「最大」（一次买满 = 大额花钻）。
        """
        im = ui.screen("glory_buy_open")
        cost = None
        daily = ""
        try:
            txt = textocr.read_text(im, L.ARENA_BUY_DIALOG_BOX) or ""
        except Exception:
            txt = ""
        if "购买" not in txt:
            return False, 0, "没弹出购买弹窗"
        m = re.search(L.ARENA_BUY_COST_RE, txt.replace(" ", ""))
        if m:
            cost = int(m.group(1))
        md = re.search(L.ARENA_BUY_DAILY_RE, txt.replace(" ", ""))
        if md:
            daily = f"{md.group(1)}/{md.group(2)}"      # 只作日志备注，不当闸门
        if cost is None:
            ui.press(L.ARENA_BUY_CANCEL, 200, label="glory_buy_cancel", expect="none")
            ui.wait(1.0)
            return False, 0, "弹窗里读不到「花费 N」，不敢点购买"
        if d0 is not None and cost > d0:
            ui.press(L.ARENA_BUY_CANCEL, 200, label="glory_buy_cancel_poor", expect="none")
            ui.wait(1.0)
            return False, 0, f"主城钻石 {d0} < 花费 {cost}，买不起，不点购买"
        # 2026-11-20 审计 C6：调用方原来在弹窗还没开的时候就
        # may_spend(ctx, ..., None) —— 传 None 等于预算闸形同虚设。
        # 现在等弹出框里真读到「花费 N」再走闸门，金额是真的。
        if ctx is not None and not self.may_spend(ctx, "荣耀竞技场买 1 次挑战次数",
                                                  cost, kind="attempt"):
            ui.press(L.ARENA_BUY_CANCEL, 200, label="glory_buy_cancel_gate", expect="none")
            ui.wait(1.0)
            return False, 0, f"花费 {cost} 钻，被预算/保护策略拦下，不点购买"
        if before_att is None:
            before_att = self._attempts(im)
        ui.press(L.ARENA_BUY_CONFIRM, 220, label="glory_buy_confirm", expect="none")
        ui.wait(2.2)
        after = ui.screen("glory_buy_done")
        after_att = self._attempts(after)
        if after_att is None:
            return False, 0, "点「购买」后读不到挑战次数（缺证），不认这次购买"
        if before_att is not None and after_att <= before_att:
            return False, 0, f"点了「购买」但挑战次数没增加（{before_att}→{after_att}），不认这次购买"
        return True, cost, f"买到 1 次挑战次数（弹窗写花费 {cost}" + (f"，今日可购买 {daily}" if daily else "") + ")"

    def _leave(self, ui) -> None:
        """退出本页：BACK 会退回登录页（实测），所以点底栏「主城」页签。"""
        im = ui.screen("glory_exit")
        if self._at_page(im):
            ui.press(L.GLORY_EXIT_TAB, 250, label="glory_exit_tab", expect="none")
            ui.wait(2.0)
        MainCity(ui).ensure()

    # ---------- 主流程 ----------
    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        p = self.p or {}
        max_fights = int(p.get("max_fights", 10))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        # 2026-11-10 用户新规则：钻石只用来买挑战次数。自证必须用**主城**顶栏 ——
        # 竞技/荣耀页顶栏换成了别的货币，CITY_DIAMOND_BOX 在那里读不到钻石。
        d0 = self.diamonds_stable(ui, "glory_d0")
        if not self._enter(ui):
            return TaskResult.fail("进不去荣耀竞技场（竞技页/入口没走通）")

        fights = 0
        wins = 0
        left = self._attempts(ui.screen("glory_chk"))
        buy_left = int(p.get("buy_attempts", 0))
        bought = 0
        while left == 0 and buy_left > 0:
            if d0 is None:
                log.info("  荣耀竞技场：主城钻石读数失败 → 不做任何买次数动作（无自证不花钻）")
                break
            ui.press(L.GLORY_BUY_PLUS, 200, label="glory_buy_plus", expect="none")
            ui.wait(1.8)
            ok, spent, why = self._buy_one(ui, before_att=left, d0=d0, ctx=ctx)
            log.info(f"  荣耀竞技场买次数：{why}")
            if not ok:
                break
            bought += spent
            buy_left -= 1
            left = self._attempts(ui.screen(f"glory_after_buy{bought}"))
        if left == 0:
            self._leave(ui)
            d1 = self.diamonds_stable(ui, "glory_d1")
            if bought:
                spent = None if (d0 is None or d1 is None) else d0 - d1
                if spent is None or spent < bought:
                    log.warn(f"  荣耀竞技场：买次数花了 {bought} 钻，但主城钻石前后对比缺证（{d0}→{d1}）")
                else:
                    log.info(f"  荣耀竞技场：买次数花钻 {spent}（主城 {d0}→{d1}），挑战次数已到账")
            msg = "跳过：荣耀竞技场今天的挑战次数已用尽（0/10）"
            stats = {"fights": 0, "left": 0, "noop_ok": True,
                     "diamonds_before": d0, "diamonds_after": d1}
            if bought:
                msg += f"，买次数花钻 {bought}"
                stats["diamonds_spent_nominal"] = bought
            return TaskResult(True, msg, stats)

        deadline = time.time() + 20 * 60
        noop = 0
        att_unread = False
        while fights < max_fights and time.time() < deadline:
            res = self._one_fight(ui, fights + 1)
            if res is None:            # 没打起来：先看次数，再决定是「打完了」还是真卡住
                now_left = self._attempts(ui.screen(f"glory_noop{fights}{noop}"))
                if now_left == 0:
                    log.info("  荣耀竞技场：次数已打空（0/10），收手")
                    left = now_left
                    break
                noop += 1
                if noop >= 2:
                    log.info("  荣耀竞技场：连续 2 把没打起来，收手")
                    break
                ui.wait(1.2)
                continue
            fights += 1
            noop = 0
            if res == "win":
                wins += 1
            ui.wait(1.2)
            left = self._attempts(ui.screen(f"glory_left{fights}"))
            if left == 0:
                log.info("  荣耀竞技场：次数打完了")
                break
        if fights == 0:
            # 2026-11-10：一把都没打起来时，先再确认一次次数与「开始匹配」是否可点。
            #   次数读得到且 > 0 → 有次数却打不起来，是脚本问题，保持 FAIL 让 scheduler 自愈；
            #   次数读不到 + 没有金色「开始匹配」 → 「今天没得打」的真状态，记跳过（别白跑自愈）。
            chk = ui.screen("glory_no_battle")
            att = self._attempts(chk)
            if att is not None:
                left = att
            if left is None and self._match_pos(chk) is None:
                # 2026-11-20 审计 MAJOR：旧码这里直接 left = 0，于是
                # ok = fights > 0 or left == 0 恒真 → 缺证也报成功。
                # 现在只记「次数读不到」，由收尾分支如实跳过，不冒充「已打空」。
                log.info("  荣耀竞技场：次数读不到，页面上也没有可点的「开始匹配」 → 按今天没得打处理（缺证）")
                att_unread = True
        self._leave(ui)
        d1 = self.diamonds_stable(ui, "glory_d1")
        if bought:
            spent = None if (d0 is None or d1 is None) else d0 - d1
            if spent is None or spent < bought:
                log.warn(f"  荣耀竞技场：买次数花了 {bought} 钻，但主城钻石前后对比缺证（{d0}→{d1}）")
            else:
                log.info(f"  荣耀竞技场：买次数花钻 {spent}（主城 {d0}→{d1}），挑战次数已到账")
        stats = {"fights": fights, "wins": wins, "left": left,
                 "diamonds_before": d0, "diamonds_after": d1}
        if bought:
            stats["diamonds_spent_nominal"] = bought
        if fights == 0 and left is None and att_unread:
            stats["noop_ok"] = True
            stats["attempts_unreadable"] = True
            return TaskResult(
                True,
                "跳过：荣耀竞技场次数读不到、也没有「开始匹配」按钮"
                "（缺证，按今天没得打处理）" + (f"，买次数花钻 {bought}" if bought else ""),
                stats)
        msg = f"荣耀竞技场：挑战 {fights} 次（胜 {wins}" + (f"，余 {left}" if left is not None else "") + "）"
        if bought:
            msg += f"，买次数花钻 {bought}"
        ok = fights > 0 or left == 0
        if fights == 0:
            stats["noop_ok"] = True
        return TaskResult(ok, msg, stats)
