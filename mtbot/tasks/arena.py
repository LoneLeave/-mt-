"""竞技 → 角斗场（2026-11-09 按用户同意恢复）。

**为什么需要它**：主线（campaign）会被游戏用「温馨提示：当前角斗券已达上限，
请前往角斗场挑战」挡住；竞技类任务在 2026-10-30 被整体删除后，没有任何脚本
去消耗角斗券，于是主线长期停在 0 次。这个任务只做一件事：把角斗券打掉。

**实测流程（2026-11-09 09:39，logs/_probe_arena.png / _probe_glad*.png）**：
- 主城底栏「竞技」=(555,1225) → 竞技页（荣耀巅峰赛 / 角斗场 / 荣耀竞技场 / 争霸赛）；
- 第一张大卡「角斗场」中心 (360,570) → 角斗场页，首次进入先弹「防守纪录」
  浮层（点空白关不掉，按左下 BACK 关掉）；
- 对手列表在下方，每行右侧是金色「挑战」（最上面一行约 (573,944)）；
- 底部一行写「跳过战斗 / 02:02:27后恢复1次 / 9/12」——「跳过战斗」是游戏里的
  勾选项（默认勾上），所以点「挑战」约 2 秒直接出结算页：
  「挑战成功」/「挑战失败」+ 奖励 + 「确定」(250,819) / 「返回玩法」；
- 底部「+」是**钻石买次数**，右上「角斗商店」「角斗限购」也是消费入口，
  脚本永不点它们（只点对手行的金色「挑战」和结算页的「确定」）。
"""
from __future__ import annotations

import re
import time

from .. import layout as L
from .. import log, textocr, vision
from ..pages import MainCity
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult


class ArenaTask(BaseTask):
    name = "arena"
    title = "角斗场（打掉角斗券，别让它顶满挡住主线）"
    category = "pvp"

    # ---------- 判据 ----------
    @staticmethod
    def _attempts(im):
        """底部「9/12」→ 剩余次数 9。读不到返回 None（不是 0，别误判成打完）。"""
        try:
            txt = textocr.read_text(im, L.ARENA_ATTEMPT_BOX)
        except Exception:
            return None
        m = re.search(L.ARENA_ATTEMPT_RE, txt or "")
        if not m:
            return None
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _at_hub(im) -> bool:
        """在竞技一级页（三张大卡）。"""
        try:
            txt = textocr.read_text(im, L.ARENA_HEAD_BOX)
        except Exception:
            return False
        txt = txt or ""
        return "角斗场" in txt and ("荣耀竞技场" in txt or "争霸赛" in txt)

    @staticmethod
    def _record_open(im) -> bool:
        """是不是「防守纪录」浮层（首次进入必弹，会盖住对手列表）。"""
        try:
            txt = textocr.read_text(im, L.ARENA_RECORD_BOX) or ""
        except Exception:
            return False
        return any(k in txt for k in L.ARENA_RECORD_KEYS)

    def _close_record(self, ui, tries: int = 3) -> bool:
        """按左下 BACK 关掉「防守纪录」。返回关掉/本来就没有。"""
        for i in range(tries):
            im = ui.screen(f"arena_rec{i}")
            if not self._record_open(im):
                return True
            log.info("  角斗场：关掉「防守纪录」浮层")
            ui.press(L.BACK, 250, label="arena_close_record", expect="none")
            ui.wait(1.5)
        return not self._record_open(ui.screen("arena_rec_end"))

    @staticmethod
    def _at_page(im) -> bool:
        """在角斗场挑战页：底部有「跳过战斗 / 后恢复」。"""
        try:
            foot = textocr.read_text(im, L.ARENA_FOOT_BOX)
        except Exception:
            foot = ""
        return "跳过战斗" in (foot or "") or "后恢复" in (foot or "")

    @staticmethod
    def _challenge_pos(im):
        """对手列表里最上面那个金色「挑战」按钮中心。"""
        bands = vision.gold_bands_any(im, L.ARENA_ROWS_ROI)
        if not bands:
            return None
        cand = [b for b in bands if 500 <= b[0] <= 660 and 760 <= b[1] <= 1120]
        if not cand:
            return None
        cand.sort(key=lambda b: b[1])
        return (cand[0][0], cand[0][1])

    # ---------- 进入 ----------
    def _enter(self, ui) -> bool:
        im = ui.screen("arena_before")
        if self._at_page(im):
            return True
        if self._at_hub(im):
            pass
        else:
            # 2026-11-09：「竞技」页签在主城底栏，与「公会」相邻，坐标随版本动过，
            # 所以点完要复核是不是真的进了竞技页。
            ui.press(L.TAB_ARENA, 250, label="arena_tab", expect="none")
            ui.wait(2.4)
            im = ui.screen("arena_hub")
            if not self._at_hub(im):
                log.warn("  角斗场：点「竞技」后没进竞技页（页签坐标可能又挪了），本次跳过")
                return False
        ui.press(L.ARENA_GLAD_CARD, 250, label="arena_card", expect="none")
        ui.wait(2.6)
        # 2026-11-09 修：浮层盖住列表时底部「跳过战斗 … 9/12」照样可见，所以不能只靠
        # `_at_page` 判断要不要按 BACK —— 必须显式认「防守纪录」再关。
        self._close_record(ui)
        im = ui.screen("arena_open")
        if not self._at_page(im):
            ui.press(L.BACK, 250, label="arena_close_record_end", expect="none")
            ui.wait(1.4)
            im = ui.screen("arena_open2")
        return self._at_page(im)

    # ---------- 一轮挑战 ----------
    def _settle(self, ui, label: str = "arena_res"):
        """等结算页出现并点「确定」。返回 True=胜 / False=负 / None=没认出来。"""
        for _ in range(6):
            im = ui.screen(label)
            try:
                txt = textocr.read_text(im, L.ARENA_RESULT_BOX) or ""
            except Exception:
                txt = ""
            if "挑战成功" in txt or "挑战失败" in txt:
                win = "挑战成功" in txt
                ui.press(L.ARENA_RESULT_OK, 220, label="arena_ok", expect="none")
                ui.wait(1.6)
                return win
            # 2026-11-09：真帧里「防守纪录」浮层的识别特征是整块战报面板，
            # 而 (60,240,660,800) 这一带日常就有个「战报」字样（页面右上角的常驻入口），
            # 单独命中「战报」会误按 BACK 退出角斗场。这里只认完整短语。
            if "防守纪录" in txt:
                ui.press(L.BACK, 250, label="arena_close_record2", expect="none")
                ui.wait(1.2)
                continue
            if vision.classify(im) == State.CONFIRM_DIALOG:
                # 只关不确认：确认框在竞技里通常是「花钻石再来一次」
                ui.press(L.CONFIRM_CANCEL, 180, expect="none")
                ui.wait(1.0)
                continue
            ui.wait(1.2)
        return None


    def _buy_one(self, ui, before_att: int | None = None, d0: int | None = None,
                 ctx: TaskContext | None = None):
        """买 1 次挑战次数（钻石）。返回 (成功?, 花费钻石, 说明)。

        用户规则（2026-11-10）：钻石只允许用来买挑战次数 —— 这条路是允许的，
        但必须有前后钻石自证：先读弹窗里的「花费 N」，点「购买」后要求
        钻石确实少了 N、且挑战次数 +1；任一不满足就按失败处理（不计数）。
        绝不点「最大」（一次买满 = 大额花钻）。
        """
        # 2026-11-10 实机：点「+」时页面刚切换，弹窗偶尔晚到（第 35 轮 04:40 那次
        # 点了没弹窗就直接收手）。这里最多补点 2 次，每次都重新抓帧确认。
        im = None
        txt = ""
        for attempt in range(3):
            im = ui.screen(f"arena_buy_open{attempt}")
            try:
                txt = textocr.read_text(im, L.ARENA_BUY_DIALOG_BOX) or ""
            except Exception:
                txt = ""
            if "购买" in txt:
                break
            if attempt < 2:
                ui.press(L.ARENA_BUY_PLUS, 200, label=f"arena_buy_plus_retry{attempt + 2}",
                         expect="none")
                ui.wait(1.8)
        cost = None
        daily = ""
        if "购买" not in txt:
            return False, 0, "没弹出购买弹窗（补点 2 次仍未出现）"
        m = re.search(L.ARENA_BUY_COST_RE, txt.replace(" ", ""))
        if m:
            cost = int(m.group(1))
        md = re.search(L.ARENA_BUY_DAILY_RE, txt.replace(" ", ""))
        if md:
            # 只作日志备注：游戏写的是「今日可购买次数（14/14）」，a/b 到底是
            # 「剩余/上限」还是「已买/上限」无法从一帧断定 —— 买没买到由后面的
            # 钻石差值 + 挑战次数增量自证，不拿这个数字当闸门（拿错就会永远不买）。
            daily = f"{md.group(1)}/{md.group(2)}"
        if cost is None:
            ui.press(L.ARENA_BUY_CANCEL, 200, label="arena_buy_cancel", expect="none")
            ui.wait(1.0)
            return False, 0, "弹窗里读不到「花费 N」，不敢点购买"
        if ctx is not None and not self.may_spend(ctx, "角斗场买 1 次挑战次数", cost,
                                                  kind="attempt"):
            ui.press(L.ARENA_BUY_CANCEL, 200, label="arena_buy_cancel_gate", expect="none")
            ui.wait(1.0)
            return False, 0, f"弹窗写 {cost} 钻，预算/授权闸拒绝"
        if d0 is not None and cost > d0:
            # 2026-11-10：钻石不够时游戏只弹提示、按钮点了没反应，脚本却按买到了记账。
            ui.press(L.ARENA_BUY_CANCEL, 200, label="arena_buy_cancel_poor", expect="none")
            ui.wait(1.0)
            return False, 0, f"主城钻石 {d0} < 花费 {cost}，买不起，不点购买"
        if before_att is None:
            before_att = self._attempts(im)
        ui.press(L.ARENA_BUY_CONFIRM, 220, label="arena_buy_confirm", expect="none")
        ui.wait(2.2)
        after = ui.screen("arena_buy_done")
        after_att = self._attempts(after)
        if after_att is None:
            # 购买后读不到次数 = 缺证，不能当买到了（2026-11-10 第 39 轮就是这么假账的）
            return False, 0, "点「购买」后读不到挑战次数（缺证），不认这次购买"
        if before_att is not None and after_att <= before_att:
            return False, 0, f"点了「购买」但挑战次数没增加（{before_att}→{after_att}），不认这次购买"
        return True, cost, f"买到 1 次挑战次数（弹窗写花费 {cost}" + (f"，今日可购买 {daily}" if daily else "") + ")"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_fights = int(p.get("max_fights", 10))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        # 钻石自证用主城顶栏（竞技页顶栏换成了别的货币，CITY_DIAMOND_BOX 在那里读不到）
        d0 = self.diamonds_stable(ui, "arena_d0")
        if not self._enter(ui):
            return TaskResult.fail("进不去角斗场（竞技页签或角斗场卡片没打开）")
        fights = wins = 0
        left = None
        noops = 0
        exhausted = False
        # 用户规则：钻石只用来买挑战次数 —— 角斗场允许买到上限，但每日最多买几次可配
        buy_left = int(p.get("buy_attempts", 0))
        bought = 0
        deadline = time.time() + 20 * 60
        while fights < max_fights and time.time() < deadline:
            if ui.handle_interruptions():
                continue
            im = ui.screen("arena")
            left = self._attempts(im)
            if left == 0:
                if buy_left > 0 and d0 is None:
                    log.info("  角斗场：主城钻石读数失败 → 不做任何买次数动作（无自证不花钻）")
                elif buy_left > 0:
                    ui.press(L.ARENA_BUY_PLUS, 200, label="arena_buy_plus", expect="none")
                    ui.wait(1.8)
                    # 2026-11-20 审计 MAJOR：原来 may_spend 传 cost=None，预算闸永远放行。
                    # 现在先把弹窗打开读到实价，在 _buy_one 里拿实价过闸。
                    ok, spent, why = self._buy_one(ui, before_att=left, d0=d0, ctx=ctx)
                    log.info(f"  角斗场买次数：{why}")
                    if ok:
                        bought += spent
                        buy_left -= 1
                        left = self._attempts(ui.screen("arena_after_buy"))
                        continue
                log.info("  角斗场：挑战次数 0，今天的角斗券打完了")
                break
            pos = self._challenge_pos(im)
            if pos is None and self._record_open(im):
                self._close_record(ui)
                continue
            if pos is None:
                if noops == 0:
                    # 列表可能滑到别处了：往上滚一点再看一次
                    ui.dev.swipe(360, 900, 360, 1100, 380)
                    ui.wait(1.2)
                    noops += 1
                    continue
                log.info("  角斗场：对手列表里没找到可点的「挑战」")
                break
            ui.press(pos, 220, label="arena_fight", expect="none")
            ui.wait(2.2)
            res = self._settle(ui, f"arena_res{fights}")
            if res is None:
                # 2026-11-10 实测：挑战次数为 0 时游戏对「挑战」完全无反应（无弹窗、无结算页），
                # 屏幕停在对手列表。这时再重试两轮只会白烧 40s 并让调度器判 FAIL 自愈；
                # 用「点了之后次数没变」来断定券已打完。
                after_att = self._attempts(ui.screen(f"arena_after{fights}"))
                if after_att == 0 or (after_att is not None and after_att == left):
                    log.info(f"  角斗场：点「挑战」后画面没反应，挑战次数仍是 {after_att} → 今天的角斗券已经打完，收手")
                    left = after_att
                    exhausted = True
                    break
                noops += 1
                if noops >= 2:
                    log.warn("  角斗场：点「挑战」后没等到结算页（可能被弹窗挡住），收手")
                    break
                continue
            noops = 0
            fights += 1
            if res:
                wins += 1
            ui.wait(0.6)
        MainCity(ui).ensure()
        d1 = self.diamonds_stable(ui, "arena_d1")
        if bought:
            spent = None if (d0 is None or d1 is None) else d0 - d1
            if spent is None or spent < bought:
                log.warn(f"  角斗场：买次数花了 {bought} 钻，但主城钻石前后对比缺证（{d0}→{d1}）")
            else:
                log.info(f"  角斗场：买次数花钻 {spent}（主城 {d0}→{d1}），挑战次数已到账")
        stats_extra = {"diamonds_before": d0, "diamonds_after": d1}
        msg = f"角斗场：挑战 {fights} 次（胜 {wins}"
        msg += f"，余 {left}" if left is not None else ""
        msg += "）"
        if bought:
            msg += f"，买次数花钻 {bought}"
        stats = {"fights": fights, "wins": wins, "left": left, **stats_extra}
        if bought:
            stats["diamonds_spent_nominal"] = bought
        if exhausted:
            stats["noop_ok"] = True
        return TaskResult(fights > 0 or left == 0 or exhausted, msg, stats)
