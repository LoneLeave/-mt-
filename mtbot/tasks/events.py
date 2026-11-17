"""历练里只能实打的两个玩法：巨龙牢窟 / 阵营挑战（2026-10-29 实现）。

规则沿用 E:/DailyIdea 的 `tasks/lishi.py` + `tasks/_battle.py`：
- 两个玩法都没有「一键扫荡」（也是用户强调的“没办法跳过，只能手动打”）；
- 卡片位置随滚动变化，进玩法靠卡片标题模板匹配（`TrialsHub.enter_tile`）；
- 巨龙牢窟：点档位行右侧金色「挑战」→ 布阵（一键上阵/战斗）→ 战斗（有跳过）→ 结算确定；
  次数为 0 时点挑战只弹提示框，关掉收手。
- 阵营挑战：点层行的「开始挑战」→ 布阵（一键上阵/继续）→ 增益三选一（用户要求选最左）→
  连续 30 波战斗（**没有跳过键**，只有暂停/自动/倍速）→ 回到页面再来一轮；
  脚本负责把倍速切到 ×4，否则 30 波要打半小时。
"""
from __future__ import annotations

import time

from .. import layout as L
from .. import log, template as T, vision
from ..pages import DragonPage, FactionPage, MainCity
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult


class DragonTask(BaseTask):
    name = "dragon"
    title = "巨龙牢窟"
    category = "combat"

    def _confirm(self, ui) -> None:
        """结算页点确定，直到回到巨龙牢窟页（模板优先，坐标兜底）。

        胜利流程是：MVP 胜利页（确定）→「获得奖励」黑底弹窗 → 页面。
        弹窗还在时标题模板也能命中，所以要先识别并关掉它，不能只看标题就认为回页面了。
        """
        page = DragonPage(ui)
        for _ in range(6):
            im = ui.screen("dragon_res")
            if page.reward_popup(im):
                page.dismiss_rewards()
                continue
            if page.at_page(im):
                return
            # 2026-11-08：「获得奖励」弹窗上的「确定按钮.png」实测 0.993，比结算页
            # 的「结算确定.png」0.934 更可靠，先试它；点击不做变化校验——结算页按钮
            # 只切页、局部变化很小，实测 diff=0.000 会先判空点再赔 4 个补偿点。
            m = None
            for tpl in ("确定按钮.png", "结算确定.png"):
                m = T.VI.find(im, tpl, 0.85)
                if m:
                    break
            if m:
                ui.press(m.center, 220, label="dragon_confirm", expect="none")
                ui.wait(2.2)
                continue
            for pos in ((370, 1130), (465, 1075), (360, 1100)):
                if vision.is_gold(im, *pos, r=18):
                    ui.press(pos, 220, label="dragon_confirm_gold", expect="none")
                    ui.wait(2.2)
                    break
            else:
                ui.press(L.BLANK, 150, expect="none")
                ui.wait(1.2)

    def _fight(self, ui) -> str:
        """一场巨龙牢窟：布阵 → 战斗 → 跳过 → 结算。返回 win / lose / back / timeout。"""
        im = ui.screen("dragon_dep")
        if vision.is_green(im, *L.DEPLOY, r=18):
            ui.press(L.DEPLOY, 200, expect="none")
            ui.wait(1.0)
        im = ui.screen("dragon_fight")
        cont = T.VI.find(im, "继续按钮.png", 0.85, roi=(460, 1155, 710, 1260))
        if cont:
            ui.press(cont.center, 250)          # 有的玩法布阵页是「继续」而不是「战斗」
            ui.wait(2.8)
        else:
            m = T.VI.find(im, "战斗按钮.png", 0.85, roi=(460, 1155, 710, 1260))
            ui.press(m.center if m else L.FIGHT, 200, label="fight", expect="none")
            ui.wait(6)
        page = DragonPage(ui)
        t0 = time.time()
        while time.time() - t0 < 300:
            im = ui.screen("dragon_battle")
            # 2026-11-08：胜利后的「获得奖励」黑底弹窗 classify=unknown，
            # 胜利.png 只有 0.52、结算界面.png 0.65（阈值 0.85）都不命中，
            # 旧循环只能空等 300s 超时（实测 01:47~01:52 卡了 5 分钟，
            # 整场 417s、第二场记成「没打完」）。这里先认弹窗，认到就是赢了。
            if page.reward_popup(im):
                m = T.VI.find(im, "确定按钮.png", 0.85)
                if m:
                    ui.press(m.center, 220, label="dragon_reward_ok", expect="none")
                    ui.wait(1.6)
                page.dismiss_rewards()
                return "win"
            if page.at_page(im):
                return "back"
            if T.VI.find(im, "胜利.png", 0.85) or T.VI.find(im, "结算界面.png", 0.85):
                self._confirm(ui)
                return "win"
            if T.VI.find(im, "失败.png", 0.85):
                self._confirm(ui)
                return "lose"
            if vision.classify(im) == State.BATTLE:
                ui.battle_skip(im)
                ui.wait(2.5)
                continue
            ui.wait(1.5)
        return "timeout"

    def _buy_attempt(self, ui, page, ctx) -> int:
        """次数为 0 时点「挑战」→ 读购买框 → 白名单放行 → 买 1 次并复核次数增加。

        2026-11-11：用户要求「巨龙洞窟的购买次数与购买后继续挑战」；实测购买框是
        预制款「是否花费 100（拥有 1518) 购买1次挑战次数？今日可购买次数（1/2）」。
        三重自证：弹窗金额 + 挑战次数增加 + （收尾）主城钻石差额。
        """
        opened, cost = page.buy_attempt(ui)
        if not opened:
            log.info("  巨龙牢窟：点「挑战」没弹出购买框（今天也许不能买），不买次数")
            return 0
        if cost <= 0:
            log.info("  巨龙牢窟：购买框里读不到「花费 N」，不买次数")
            page.close_buy_dialog()
            return 0
        if not self.may_spend(ctx, "巨龙牢窟·挑战次数", cost, kind="attempt"):
            page.close_buy_dialog()
            return 0
        before = page.attempts()
        ui.press(L.DRAGON_BUY_OK, 220, label="drg_buy_ok", expect="none")
        ui.wait(1.7)
        after = page.attempts()
        if before is not None and after is not None and after <= before:
            log.info(f"  巨龙牢窟：点了「购买」但挑战次数没增加（{before}→{after}），不认这次购买")
            return 0
        log.info(f"  巨龙牢窟：买到 1 次挑战次数（弹窗写花费 {cost}，挑战次数 {before}→{after}）")
        return int(cost)

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_fights = int(p.get("max_fights", 6))
        max_lose = int(p.get("max_lose", 2))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = DragonPage(ui)
        if not page.enter():
            MainCity(ui).ensure()
            return TaskResult.fail("进不去巨龙牢窟")
        claimed = page.claim_progress()      # 2026-11-03 #9：先补领上次没领的进度奖励
        d0 = self.diamonds_stable(ui, "drg_d0") if int(p.get("buy_attempts", 2) or 0) > 0 else None

        wins = loses = 0
        fights = 0
        bought = 0
        spent_popup = 0
        buys = max(0, int(p.get("buy_attempts", 2)))
        reason = ""
        deadline = time.time() + 60 * ctx.cfg.runtime.max_task_minutes
        while fights < max_fights and loses < max_lose and time.time() < deadline:
            if ui.handle_interruptions():
                continue
            # 2026-11-07：次数为 0 时「挑战」仍是金色、点下去只飘一行 toast 页面不变，
            # 白等 2.6s + 4 个补偿点；先读底部「挑战次数：N」，为 0 直接收手并说明原因。
            att = page.attempts()
            if att == 0:
                if bought < buys:
                    spent = self._buy_attempt(ui, page, ctx)
                    if spent:
                        bought += 1
                        spent_popup += spent
                        continue
                reason = "今日挑战次数已用尽"
                log.info("  巨龙牢窟今日挑战次数已用尽（底部「挑战次数：0」），收手")
                break
            r = page.challenge()
            if r == "none":
                reason = "没有可挑战的档位"
                log.info("  巨龙牢窟没有可挑战的档位")
                break
            if r == "popup":
                reason = "挑战次数不足（点挑战只弹了提示框）"
                log.info("  挑战次数不足（点挑战只弹了提示框），收手")
                break
            fights += 1
            res = self._fight(ui)
            if res == "win":
                wins += 1
                loses = 0
            elif res == "lose":
                loses += 1
            elif res == "back":
                log.info("  没有进入战斗（可能次数用完了）")
                fights -= 1
                break
            else:
                log.info("  这一场没打完，收手")
                break
            log.info(f"  巨龙牢窟：胜 {wins} 负 {loses}")
            page.dismiss_rewards()          # 胜利后的「获得奖励」弹窗可能还挂着
            if not page.at_page():
                if not page.enter():
                    break

        # 打完再进「进度奖励」补领一次（首通/进度奖励不会自动发，必须手动领）
        if page.at_page():
            claimed += page.claim_progress()
        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        spent_txt = ""
        if bought:
            if d0 is None:
                ui.wait(0.8)
                d0 = self.diamonds_stable(ui, "drg_d0b")
            d1 = self.diamonds_stable(ui, "drg_d1", tries=4)
            if d0 is not None and d1 is not None:
                spent = d0 - d1
                spent_txt = f"，买次数花钻 {spent}（主城 {d0}→{d1}）"
                if spent != spent_popup:
                    log.warn(f"  巨龙牢窟：买了 {bought} 次（弹窗合计 {spent_popup}），主城钻石 {d0}→{d1}（差 {spent}），与预期对不上，请核对")
            else:
                # 2026-11-15：主城钻石读数会因为 HUD 还没画出来而失败；改成用购买弹窗金额
                # 记账（每次购买都有「花费 N」自证），不再把它当 WARN 噪音。
                spent_txt = f"，买次数花钻 {spent_popup}（{bought} 次弹窗自证；主城读数失败未能对账）"
                log.info(f"  巨龙牢窟：主城钻石读数失败，按购买弹窗金额记账 {spent_popup}")
        msg = f"巨龙牢窟 胜 {wins} 负 {loses} 领奖 {claimed}{spent_txt}"
        if reason and fights == 0:
            msg += f"（{reason}）"      # 一场没打起来时把原因写进结果，便于一眼看出「0 胜」不是判据坏了
        return TaskResult(True, msg,
                          {"wins": wins, "loses": loses, "fights": fights,
                           "claimed": claimed, "reason": reason})


class FactionTask(BaseTask):
    name = "faction"
    title = "阵营挑战"
    category = "combat"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_runs = int(p.get("max_runs", 1))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = FactionPage(ui)
        if not page.enter():
            MainCity(ui).ensure()
            return TaskResult.fail("进不去阵营挑战")

        deadline = time.time() + 60 * ctx.cfg.runtime.max_task_minutes
        runs = 0
        resumed = False
        aborted = False
        retried = False
        reason = ""
        if page.at_page():
            # 底部三个阵营只有「开启中」的那个能打，先把它点选上
            page.ensure_active_faction()
        while time.time() < deadline:
            if ui.handle_interruptions():
                continue
            if not page.at_page():
                # 进页面时游戏可能自动续上一场没打完的战斗，先把它打完
                out = page.run_battle(max(60, deadline - time.time()))
                log.info(f"  续上的阵营战斗结束：{out}")
                resumed = True
                if out != "done":
                    aborted = True
                    break
                continue
            if runs >= max_runs:
                break
            page.ensure_active_faction()
            r = page.start_run()
            if r == "popup" and not retried:
                # 2026-11-07 03:13 全量实测：紧接上一个任务后偶发一次提示框，
                # 关掉后重试一次就能正常进布阵页（同一坐标 03:19 手动复现是好的）。
                retried = True
                log.info("  阵营挑战：提示框已关掉，等画面稳定后再试一次「开始挑战」")
                ui.wait(1.8)
                page.ensure_active_faction()
                r = page.start_run()
            if r == "none":
                reason = "没有可挑战的层（或今日已打完）"
                log.info(f"  阵营挑战{reason}，收手")
                break
            if r == "popup":
                reason = page.popup_text or "点「开始挑战」只弹了提示框"
                log.info(f"  阵营挑战：开始挑战只弹提示框（{reason}），收手")
                break
            runs += 1
            log.info(f"  阵营挑战第 {runs} 轮开始（一层 30 波，无跳过键，切 ×4 倍速）")
            out = page.run_battle(max(60, deadline - time.time()))
            log.info(f"  阵营挑战第 {runs} 轮结束：{out}")
            if out != "done":
                aborted = True
                break

        rewards = 0
        if page.at_page():
            rewards = page.claim_rewards()
            if rewards:
                log.info(f"  阵营挑战：领通关奖励 {rewards} 个")
            else:
                log.info("  阵营挑战：通关奖励箱子上没有红角标（都领过或波数未达成）")
        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        msg = f"阵营挑战 {runs} 轮"
        if reason:
            msg += f"（{reason}）"
        if resumed:
            msg += "（含进页续上的战斗）"
        if aborted:
            msg += "，最后一轮被切走/超时提前收手"
        return TaskResult(True, msg, {"runs": runs, "resumed": resumed,
                                      "aborted": aborted, "reason": reason,
                                      "rewards": rewards})
