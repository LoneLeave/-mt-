"""战斗类任务：守护者之塔 / 传奇试炼 / 时光之树 / 邪能神殿 / 角斗场 / 荣耀竞技场。

共同思路（和 OAS 的“页面状态机”一致）：
  每轮只做一次“看状态 → 做一个动作”，不假设上一步一定成功；
  超过时间或连败阈值立刻退出，交给调度器继续下一个任务。
"""
from __future__ import annotations

import time

from .. import layout as L
from .. import log, template, textocr, vision
from ..pages import (BattleResult, DemonPage, LegendPage, MainCity,
                     TowerPage, TreePage, TrialsHub)
from ..ui import UI
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult


class TowerTask(BaseTask):
    name = "tower"
    title = "守护者之塔"
    category = "combat"

    @staticmethod
    def _progress_undone(im) -> int:
        """进度面板里写着「未达成」的行数（用来说清「没得领」的真因）。"""
        if not textocr.available():
            return 0
        try:
            lines = textocr.read_lines(im, L.TOWER_FRAME_BOX, min_score=0.6)
        except Exception:  # noqa: BLE001
            return 0
        return sum(1 for t, _c, _bb, _s in lines if "未达成" in t)

    @staticmethod
    def _progress_claimed(im) -> int:
        """进度面板里写着「已领取」的行数（和「未达成」一起说明「没得领」的真因）。"""
        if not textocr.available():
            return 0
        try:
            lines = textocr.read_lines(im, L.TOWER_FRAME_BOX, min_score=0.6)
        except Exception:  # noqa: BLE001
            return 0
        return sum(1 for t, _c, _bb, _s in lines if "已领取" in t)

    def _claim_rewards(self, ui) -> int:
        """塔页的「进度奖励」+「每日奖励」（2026-10-30 实测）。

        进度奖励面板每行一个金色「领取」，领完列表会上移；往下滚还能看到后面的里程碑。
        每日奖励页今天已领时是绿色「已领取」，没领时下半屏有金色按钮。
        """
        n = 0
        ui.press(L.TOWER_PROGRESS, 250)
        ui.wait(1.7)
        for _ in range(12):
            im = ui.screen("tower_prog")
            target = None
            for y in L.TOWER_CLAIM_YS:
                if vision.is_gold(im, L.TOWER_CLAIM_X, y, r=16):
                    target = y
                    break
            if target is None:
                first = im
                ui.dev.swipe(360, 950, 360, 650, 400)   # 往下翻里程碑
                ui.wait(0.9)
                im = ui.screen("tower_prog2")
                for y in L.TOWER_CLAIM_YS:
                    if vision.is_gold(im, L.TOWER_CLAIM_X, y, r=16):
                        target = y
                        break
                if target is None:
                    # 真帧里四行都写着「通关…999/1010层 未达成」→ 没得领是里程碑没到，
                    # 不是脚本没翻到（2026-11-08 09:53 tests/fixtures/tower_prog_page.png）。
                    # 2026-11-18 第 49 轮：只读滑动后那一帧，OCR 偶尔把「未达成」扫没了
                    # （滑动中抓帧）→ 明明没得领却报 WARN。现在两帧都看，且把
                    # 「已领取」也算作「没得领」的真因。
                    done = max(self._progress_undone(first), self._progress_undone(im))
                    claimed = max(self._progress_claimed(first), self._progress_claimed(im))
                    if done or claimed:
                        log.info(f"  塔进度奖励：里程碑 {done} 条未达成、{claimed} 条已领取，"
                                 f"没有可领的（本次已领 {n} 个）")
                    else:
                        log.warn(f"  塔进度奖励：翻到底仍没找到金色「领取」（x={L.TOWER_CLAIM_X}，"
                                 f"候选 y={L.TOWER_CLAIM_YS}），已领 {n} 个")
                    break
            before = im
            ui.press((L.TOWER_CLAIM_X, target), 220)
            ui.wait(1.5)
            after = ui.screen("tower_prog3")
            ui.press(L.BLANK, 120, expect="none")
            ui.wait(0.6)
            # 2026-11-09 假成功审计：点完必须看见变化才计数。
            # 领奖后该行按钮变灰/整列上移 → 同一点不再金，或整屏 diff 明显。
            still = vision.is_gold(after, L.TOWER_CLAIM_X, target, r=16)
            changed = not still or vision.diff_ratio(before, after,
                                                      (300, 300, 700, 1000)) >= 0.05
            if not changed:
                log.info(f"  塔进度奖励：点 (x={L.TOWER_CLAIM_X}, y={target}) 后画面没变化，"
                         f"停止领取（已领 {n} 个）")
                break
            n += 1
            log.info(f"  塔进度奖励领取 ×{n}")
        ui.press(L.TOWER_PROG_CLOSE, 200, expect="none")
        ui.wait(1.0)

        # 2026-11-08 16:59 实机：面板是「叠在塔页上的侧栏」，底下的「挑战」金钮
        # 依然可见可判金 → 旧闸门 `is_gold(TOWER_GO)` 会把「面板已开」误判成
        # 「没打开」并放弃。改成先 OCR 面板文字认门，再找金钮。
        # 2026-11-18 第 49 轮：刚关掉进度奖励面板就点「每日奖励」，1.7s 后抓帧还是
        # 关面板的过渡画面 → OCR 读不到「每日奖励」→ 报 WARN 白丢一次领取。
        # 现在按完轮询 3 次（每次 0.9s），还读不到就再按一次再看。
        im = None
        txt, opened = "", False
        for round_i in range(2):
            ui.press(L.TOWER_DAILY, 250, label="tower_daily_tab", expect="none")
            ui.wait(1.7)
            for _ in range(3):
                im = ui.screen("tower_daily")
                txt = ""
                if textocr.available():
                    try:
                        txt = textocr.read_text(im, L.TOWER_DAILY_BOX) or ""
                    except Exception:  # noqa: BLE001
                        txt = ""
                opened = any(k in txt for k in ("每日奖励", "明日可领取", "已领取"))
                if opened:
                    break
                ui.wait(0.9)
            if opened:
                break
        if not opened:
            log.warn("  塔每日奖励：点了两次 (645,1207) 面板都没打开（页面上读不到「每日奖励」字样），不乱点")
            ui.press(L.TOWER_DAILY_CLOSE, 200, expect="none")
            ui.wait(0.9)
            return n
        # 2026-11-18 第 49 轮假成功审计：真帧 `logs/_twd0.png` 里 (360,678) 的
        # `is_gold` 是 True（那是面板上的金色描边/数字，不是按钮），按下去
        # `diff_ratio=0.0` 什么都没发生，旧码照样 `n += 1` + 打「塔每日奖励已领取」
        # → 每轮都虚报「领奖励 1」。现在：
        #   ① 面板 OCR 已经写「今日奖励…已领取」就直接如实说明、一个都不算；
        #   ② 否则点完必须看到画面变化才计数。
        flat = txt.replace(" ", "")
        found = False
        if "已领取" in flat:
            log.info("  塔每日奖励：面板写着「今日奖励…已领取」，今天已经领过了（不计入领取数）")
        else:
            for y in (1000, 930, 860, 678):
                if not vision.is_gold(im, 360, y, r=16):
                    continue
                before = im
                ui.press((360, y), 220, label=f"tower_daily_claim:{y}", expect="none")
                ui.wait(1.6)
                after = ui.screen("tower_daily2")
                if vision.diff_ratio(before, after, (0, 150, 720, 1200)) < 0.02:
                    log.info(f"  塔每日奖励：点 (360,{y}) 后画面没变化（那里不是领取钮），不计入")
                    im = after
                    continue
                n += 1
                found = True
                log.info(f"  塔每日奖励领取 ×1（点 (360,{y})，画面已变化）")
                im = after
                break
        if not found and "已领取" not in flat:
            log.warn(f"  塔每日奖励：面板里没有金色「领取」（OCR：{txt[:60]}）")
        ui.press(L.TOWER_DAILY_CLOSE, 200, expect="none")
        ui.wait(0.9)
        return n

    @staticmethod
    def _result_ok(im) -> tuple[int, int] | None:
        """结算页左侧「确定」按钮中心（OCR）。

        2026-11-08 真帧定案：塔结算页左侧「确定」填充是 (194,165,129) 的浅土黄，
        `vision.is_gold` 恒 False（右侧「再次挑战/下一关」才是金色），
        旧码用 `is_gold(*L.TOWER_RESULT_OK)` 当闸门 → 永远不成立 → 收尾等 60s 超时。
        实测 OCR 在 (140,1020,680,1130) 内能 1.00 读出「确定」，中心 (233,1062)。
        """
        if not textocr.available():
            return None
        try:
            lines = textocr.read_lines(im, L.RESULT_OK_ZONE, min_score=0.6)
        except Exception:  # noqa: BLE001
            return None
        cands = [c for t, c, _bb, _s in lines if "确定" in t]
        return min(cands, key=lambda c: c[0]) if cands else None

    def _settle(self, ui, page, res, timeout: float = 60.0) -> bool:
        """收尾只在战斗/结算态等待并处理结算，战斗中绝不点 UI。

        2026-11-04 实测（f0040~f0042）：主循环因 max_wins / 超时退出时画面还停在战斗里，
        旧收尾直接 MainCity.ensure() + page.enter() + _claim_rewards，
        (95,150) 正好落在战斗页的「状态信息」按钮上（f0041 打开的是状态面板），
        领奖因此恒为 0，还多了一次战斗态误点。
        """
        end = time.time() + timeout
        while time.time() < end:
            im = ui.screen("tower_settle")
            st = vision.classify(im)
            if st == State.BATTLE or st == State.DEPLOY:
                # 2026-11-08：收尾阶段还在战斗时也点跳过（模板命中才点），
                # 否则等满 60s 超时 → 放弃领奖（旧版就是这么丢奖励的）。
                if st == State.BATTLE and ui.battle_skip(im, label="tower_settle_skip"):
                    ui.wait(1.2)
                else:
                    ui.wait(2.0)
                continue
            if st == State.CONFIRM_DIALOG:
                ui.press(L.CONFIRM_CANCEL, 180, expect="none")
                ui.wait(1.0)
                continue
            if st == State.RESULT_TOWER:
                # 走左侧「确定」回塔页，不点右侧「下一关」再开一局
                pos = self._result_ok(im)
                if pos:
                    ui.press(pos, 220, label=f"tower_ok:{pos[0]},{pos[1]}", expect="none")
                    ui.wait(1.9)
                else:
                    res.ok("tower")
                continue
            if st == State.RESULT_DEFEAT:
                # 2026-11-08：左侧「确定」不是金色（(194,165,129)），旧的 is_gold 闸门
                # 永远不成立 → 收尾等 60s 超时、放弃领奖，整点任务被记 FAIL。
                pos = self._result_ok(im)
                if pos:
                    ui.press(pos, 220, label=f"tower_defeat_ok:{pos[0]},{pos[1]}",
                             expect="none")
                    ui.wait(1.9)
                    continue
                if vision.is_gold(im, *L.TOWER_RESULT_OK, r=18):
                    res.ok("tower")
                else:
                    ui.wait(1.2)
                continue
            if st == State.RESULT_GENERIC:
                ui.press(L.BLANK, 150, expect="none")
                ui.wait(1.4)
                continue
            return True                     # 塔页 / 主城 / 历练页：可以安全收尾
        log.warn("  塔：收尾等结算超时，仍停在战斗/布阵画面（不点 UI，放弃领奖）")
        return False

    @staticmethod
    def _deploy_and_fight(ui) -> None:
        """布阵 → 开战。开战后不再点任何东西（战斗态纪律，2026-11-04）。

        旧实现复用 FightMixin.deploy_and_skip，开战 8 秒后按 (655,900)「跳过」；
        实测那一点在塔战里落在 ×2 / ▶ 之间，补偿后还会漂到 892，
        既是战斗态误点，也是此前「暂停 → 退出战斗 → 判负」的来源之一。
        """
        im = ui.screen("tower_deploy")
        if vision.is_green(im, *L.DEPLOY, r=18):
            ui.press(L.DEPLOY, 200, label="deploy", expect="none")
            ui.wait(1.0)
        ui.press(L.FIGHT, 200, label="fight", expect="none")
        ui.wait(1.2)

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_wins = int(p.get("max_wins", 100))
        max_lose = int(p.get("max_lose", 10))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = TowerPage(ui)
        if not page.enter():
            return TaskResult.fail("进不去守护者之塔（历练列表里没找到塔入口）")
        res = BattleResult(ui)

        wins = loses = streak = 0
        unknown = 0
        # 2026-11-05：收尾预算按 max_task_minutes 比例留（短配置 6min 也要够一场战斗+等结算）。
        # 旧版固定 100s：6 分钟配置下 deadline 正好落在战斗中间，等结算超时 → 白跑一趟。
        total = 60 * ctx.cfg.runtime.max_task_minutes
        reserve = max(150, int(total * 0.35))
        budget = total - reserve
        log.info(f"  塔：总预算 {total}s，收尾预留 {reserve}s，打塔预算 {max(60, budget)}s")
        deadline = time.time() + max(60, budget)
        while time.time() < deadline and wins < max_wins and streak < max_lose:
            if ui.handle_interruptions():
                continue
            im = ui.screen("tower")
            st = vision.classify(im)
            if st != State.UNKNOWN:
                unknown = 0
            if st == State.RESULT_TOWER:
                wins += 1
                streak = 0
                log.info(f"  塔胜利 {wins}")
                res.next_floor()
                continue
            if st == State.RESULT_DEFEAT:
                loses += 1
                streak += 1
                log.info(f"  塔失败 (连续 {streak}/{max_lose})——可能是该层战力不足")
                if streak >= max_lose:
                    log.info(f"  塔：连败 {max_lose} 次仍打不过，换任务（不是点击失败）")
                    break
                im2 = ui.screen("tower_retry")
                if vision.is_gold(im2, *L.TOWER_RESULT_RETRY, r=18):
                    # expect="none"：这是幂等的「再开一局」，不要走坐标补偿
                    # （补偿会把点击漂到下沿之外，白等 ~8s）。
                    ui.press(L.TOWER_RESULT_RETRY, 220, label="tower_retry",
                             expect="none")
                    ui.wait(2.2)
                else:
                    ui.press(L.BLANK, 150, expect="none")
                    ui.wait(1.2)
                continue
            if st == State.RESULT_GENERIC:
                ui.press(L.TREE_RESULT_OK_FINAL, 220, label="tower_final_ok",
                         expect="none")
                ui.wait(1.6)
                ui.press(L.BLANK, 150, expect="none")
                ui.wait(1.0)
                continue
            if st == State.DEPLOY:
                self._deploy_and_fight(ui)
                continue
            if st == State.BATTLE:
                # 2026-11-08 全库复核（1800 帧）：跳过键 ▶| 恒在 (652,899)，暂停在
                # (669,781)、自动在 y≈775，ROI (600,850,720,950)+阈值 0.60 已把它们
                # 分开，classify!=battle 的帧零误命中 → 命中模板才点，未命中不盲点。
                # 旧注释「战斗态一律不点 UI」是 2026-11-04 用固定坐标 (655,900) 被
                # 坐标补偿漂到 860 误触暂停造成的；那是坐标问题，不是没有跳过键。
                if ui.battle_skip(im, label="tower_skip"):
                    ui.wait(1.2)
                else:
                    ui.wait(1.5)
                continue
            if st == State.CONFIRM_DIALOG:
                # 战斗/结算中偶发的确认框：点左侧「取消」关闭，绝不点右侧确定（避免退出战斗）
                log.warn(f"  战斗：出现确认弹窗（{L.CONFIRM_CANCEL}），点「取消」关闭")
                ui.press(L.CONFIRM_CANCEL, 180, expect="none")
                ui.wait(1.0)
                continue
            if vision.is_gold(im, *L.TOWER_GO, r=18):
                page.challenge()
                continue
            if page.at_page(im):
                # 标题在 = 确实是塔页面；按钮暂时不亮（动画/刷新）就等一拍，别回主城
                unknown = 0
                ui.wait(1.2)
                continue
            if st == State.UNKNOWN and unknown < 12:
                # 胜利动画、下一关过场、战斗加载这类画面会短暂没有按钮，
                # 等它演完再看；以前一帧不认识就回主城重进，看起来像“老是回主界面”。
                unknown += 1
                ui.wait(1.4)
                continue
            # 不是塔的任何已知界面：先确认不是「战斗还没收尾」
            # 2026-11-08 02:45 实测：失败后先弹「点击空白处关闭」提示层（UNKNOWN，
            # 约 3s）再出结算页；旧逻辑 UNKNOWN 只容忍 4 帧就回主城，结果把还没
            # 收尾的战斗拉回前台，重进塔页必然失败。
            if page.busy(im):
                unknown = 0
                ui.wait(1.6)
                continue
            unknown = 0
            if not MainCity(ui).ensure():
                break
            page.enter()
        # 用户规则：先爬完再去看奖励（进度奖励里可能有刚打出来的新档位）
        claimed = 0
        if self._settle(ui, page, res):
            # 2026-11-08：旧版只重进一次 + 固定 wait(1.6)，塔页 1.3~2.0s 才画完，
            # 一帧没等到就跳过领奖（v13 那次 `领奖励 0` 就是这个）。
            for attempt in range(3):
                if page.at_page(ui.screen(f"tower_claim_pre{attempt or ''}")):
                    break
                if not MainCity(ui).ensure():
                    break
                if not page.enter():
                    log.info(f"  塔：收尾第 {attempt + 1}/3 次没进到塔页")
                    continue
                for _ in range(8):
                    if page.at_page():
                        break
                    ui.wait(0.5)
            im = ui.screen("tower_claim_pre")
            if page.at_page(im):
                claimed = self._claim_rewards(ui)
            else:
                log.warn("  塔：收尾没回到塔页，跳过领奖（不在非塔页面点按钮）")
            MainCity(ui).ensure()
        # 2026-11-08：连败打满 max_lose 是「这一层战力不足」的真状态，不是脚本故障，
        # 记 OK 并写清楚，避免 scheduler 自愈重试白跑一遍（每轮 ~20 分钟）。
        beaten = loses >= max_lose and wins == 0
        msg = f"塔: 胜 {wins} 负 {loses}，领奖励 {claimed}"
        if beaten:
            msg += f"（连败 {loses} 次，该层战力不足，今天打不动；收尾已安全退出）"
        stats = {"wins": wins, "loses": loses, "rewards": claimed}
        if wins == 0 and loses == 0 and not beaten:
            # 2026-11-09 假成功审计 m5：一次都没打成（挑战钮不可用/次数为 0）
            # 不该与「连败打满」混在同一个 OK 里
            stats["noop_ok"] = True
            return TaskResult(True, "跳过：塔今天一次都没打成（挑战钮不可用或次数为 0）", stats)
        return TaskResult(wins > 0 or streak == 0 or beaten, msg, stats)



class LegendTask(BaseTask):
    name = "legend"
    title = "传奇试炼"
    category = "combat"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_fights = int(p.get("max_fights", 8))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = LegendPage(ui)
        if not page.enter():
            return TaskResult.fail("进不去传奇试炼（历练列表里没找到入口）")
        done = 0
        no_att = False          # 「确实没次数了」才是允许 0 次也算 OK 的理由
        deadline = time.time() + 30 * 60
        while done < max_fights and time.time() < deadline:
            if ui.handle_interruptions():
                continue
            im = ui.screen("legend")
            st = vision.classify(im)
            if st == State.RESULT_LEGEND:
                ui.press(L.LEGEND_RESULT_OK, 220)
                ui.wait(2.0)
                continue
            if st == State.DEPLOY:
                page.deploy_and_skip(skip_delay=7.0)
                continue
            if st == State.BATTLE:
                # 2026-11-08 全库复核（1800 帧）：跳过键 ▶| 恒在 (652,899)，暂停在
                # (669,781)、自动在 y≈775，ROI (600,850,720,950)+阈值 0.60 已把它们
                # 分开，classify!=battle 的帧零误命中 → 命中模板才点，未命中不盲点。
                # 旧注释「战斗态一律不点 UI」是 2026-11-04 用固定坐标 (655,900) 被
                # 坐标补偿漂到 860 误触暂停造成的；那是坐标问题，不是没有跳过键。
                if ui.battle_skip(im, label="legend_skip"):
                    ui.wait(1.2)
                else:
                    ui.wait(1.5)
                continue
            if st == State.CONFIRM_DIALOG:
                # 战斗/结算中偶发的确认框：点左侧「取消」关闭，绝不点右侧确定（避免退出战斗）
                log.warn(f"  战斗：出现确认弹窗（{L.CONFIRM_CANCEL}），点「取消」关闭")
                ui.press(L.CONFIRM_CANCEL, 180, expect="none")
                ui.wait(1.0)
                continue
            if st in (State.RESULT_TREE, State.RESULT_GENERIC, State.RESULT_TOWER,
                      State.RESULT_DEFEAT):
                ui.press(L.BLANK, 150, expect="none")
                ui.wait(1.0)
                continue
            if not vision.is_gold(im, *L.LEGEND_GO, r=18):
                if not page.at_page(im):
                    log.info("  不在传奇试炼页（被弹窗/其他页面顶掉），重新进入")
                    if not page.enter():
                        break
                    continue
                log.info("  传奇试炼没有次数了")
                no_att = True
                break
            # 2026-11-08：次数为 0 时「挑战」仍是金色、点下去只飘一行 toast，
            # 先读底部「剩余挑战次数：N」，为 0 直接收手并说明原因（少赔一次空点）。
            att = page.attempts(im)
            if att == 0:
                log.info("  传奇试炼：剩余挑战次数 0，今天打完了")
                no_att = True
                break
            if not page.challenge():
                log.info(f"  传奇试炼没有次数了（挑战未进入布阵{'' if att is None else f'，读到剩余 {att}'}）")
                no_att = True
                break
            done += 1
            log.info(f"  传奇试炼 {done}")
            page.deploy_and_skip(skip_delay=7.0)
        # 2026-11-18（用户第 12 项）：打完补领「首通奖励」——它不会自动发，必须手动领。
        claimed = 0
        if page.at_page() or page.enter():
            claimed = page.claim_rewards()
        MainCity(ui).ensure()
        if done <= 0 and not no_att:
            # 2026-11-09 假成功审计：一次都没打成、又不是「没次数」→ 不能报 OK
            return TaskResult.fail("传奇试炼：一次都没打（入口/挑战钮/次数都没走通）",
                                   {"fights": done, "claimed": claimed})
        msg = f"传奇试炼 {done} 次"
        if claimed:
            msg += f"，领首通奖励 {claimed}"
        return TaskResult(True, msg, {"fights": done, "claimed": claimed})


class TreeTask(BaseTask):
    """时光之树：分「补星」与「主线」两个阶段，打完领每日奖励（2026-10-30）。

    用户规则：
      - 每次运行先补星，再推主线；
      - 打完记得领取地图右下「奖励」里的每日奖励。

    补星的正确入口（2026-10-30 用户指正）：地图右下「章节」图标打开「章节 / 补星」
    面板 → 切到「补星」页签 → 每章列出没打满 3 星的关卡（关卡 26-4 ★★☆…）+
    金色「前往」→ 点前往会跳到该关并选中 → 按右下「挑战」开打 →
    结算页按左侧「确定」回地图。打完后看结算页的三个条件星：
    全部达成才会涨到 3 星；只达成 1~2 个的话这关还会留在补星列表里。
    """

    name = "tree"
    title = "时光之树（补星 + 主线）"
    category = "combat"

    def _fight_once(self, ui, page) -> str:
        """打一场并把结算页处理掉，返回 win / final / lose / none。"""
        if vision.classify(ui.screen("tree_f")) == State.DEPLOY:
            page.deploy_and_skip()
        for _ in range(10):
            im = ui.screen("tree_fr")
            st = vision.classify(im)
            if st == State.RESULT_TREE:
                return "win"
            if st == State.RESULT_GENERIC:
                return "final"
            if st == State.DEPLOY:
                page.deploy_and_skip()
                continue
            if st == State.BATTLE:
                ui.battle_skip(im)
                ui.wait(2.0)
                continue
            if st == State.RESULT_DEFEAT:
                ui.press((360, 1060), 220)      # 树失败页的确定在正中
                ui.wait(1.8)
                return "lose"
            # 2026-11-10 事故：精英关结算面板「挑战成功 / 当前战斗：… / 本次造成伤害 /
            # 作战奖励 ×N」的 classify 是 UNKNOWN（modal_dim=True），旧代码当「动画」空转 10 轮
            # 就 return "none"，面板留在屏上；回到地图的 BACK 对这层也无效 → 后面连续两个任务
            # 「回不到主城」，scheduler 直接中止整轮。这里必须按面板出口点掉它。
            panel = ui._result_panel_ok(im)
            if panel is not None:
                from .. import textocr as _ocr

                try:
                    txt = _ocr.read_text(im, L.RESULT_PANEL_MID)
                except Exception:  # noqa: BLE001
                    txt = ""
                ui.press(panel, 220, label="tree_result_panel", expect="none")
                ui.wait(1.6)
                log.info(f"  树：整屏结算面板已关掉（{'失败' if '挑战失败' in txt else '成功'}）")
                return "lose" if "挑战失败" in txt else "win"
            ui.wait(1.5)
        return "none"

    def _star_phase(self, ui, page, rounds: int) -> int:
        """补星：地图右下「章节」→「补星」页签 → 逐行点金色「前往」重打。

        2026-10-30 用户指正：补星不是在地图上找星星，而是游戏自带的补星列表——
        每章列出没打满 3 星的关卡（关卡 26-4 ★★☆ …）+ 金色「前往」；
        点前往会跳到该关并选中，再按右下「挑战」开打；结算页按左侧「确定」返回地图。
        """
        done = 0
        stale = 0
        last_pos = None
        for _ in range(rounds):
            if ui.handle_interruptions():
                continue
            if not page.open_star_panel():
                log.info("  补星：补星面板打不开（可能不在树页），停止")
                break
            pos = page.find_star_go()
            if pos is None:
                log.info("  补星：补星列表里没有缺星关卡了")
                page.close_chapter_panel()
                break
            # 2026-11-03 修复 #10：同一关被再次选中说明没涨星，补星列表没变化；
            # 旧代码会照打 N 次（用户看到的就是「把补星当正式关卡一直重复打」）。
            if last_pos is not None and abs(pos[0] - last_pos[0]) <= 10 \
                    and abs(pos[1] - last_pos[1]) <= 14:
                log.info("  补星：同一关再次被选中（条件没达成），停止补星，回到地图")
                break
            last_pos = pos
            log.info(f"  补星：前往补星关卡 {pos}")
            ui.press(pos, 220)
            ui.wait(2.4)
            im = ui.screen("star_map")
            if not vision.is_gold(im, *L.TREE_STAR_CHALLENGE, r=18):
                log.info("  补星：前往后「挑战」不亮（次数限制），停止")
                break
            ui.press(L.TREE_STAR_CHALLENGE, 250)
            ui.wait(2.6)
            im = ui.screen("star_dep")
            st = vision.classify(im)
            if st == State.DIALOG:
                ui.close_popup()
                im = ui.screen("star_dep2")
                st = vision.classify(im)
            if st != State.DEPLOY:
                log.info("  补星：挑战没进布阵页，停止")
                break
            # 2026-11-04：布阵页的绿色按钮实测点了 3 次都 diff=0（游戏已自动布阵），
            # 默认点校验会触发 4 个补偿点、每次白等 ~20s。这里单次点击，不做重试。
            ui.press(L.DEPLOY, 200, expect="none")
            ui.wait(1.0)
            ui.press(L.FIGHT, 200, label="fight", expect="none")
            # 2026-11-08：不再死等 8 秒再点一次跳过，改成轮询（见 UI.battle_finish）
            ui.battle_finish(im, label="tree_star_skip", timeout=14.0)
            ui.wait(1.6)
            r, conds = self._star_result(ui)
            if r == "win" and conds >= 3:
                done += 1
                stale = 0
                # 2026-11-04：三星达成后该关会从补星列表消失，下一关顺移到同一坐标，
                # 旧逻辑拿屏幕坐标当关卡身份 → 误判「同一关没涨星」提前收手（只补了 1 场）。
                last_pos = None
                log.info(f"  补星：完成第 {done} 场（三星条件全部达成）")
            elif r == "win":
                # 条件没达成 → 这一关不会涨到 3 星，补星列表里还会排在前面。
                # 连续两次都是这种情况就不再空耗挑战次数。
                stale += 1
                log.info(f"  补星：打完了但只达成 {conds}/3 个条件（不会涨星）")
                if stale >= 2:
                    log.info("  补星：连续两关条件达不成，停止（需要换阵容再补）")
                    break
            elif r == "lose":
                log.info("  补星：这一场打输了")
            else:
                log.info("  补星：没看到结算页，停止")
                break
        # 2026-11-03：补星阶段不管正常结束还是中途 break，都必须回到树地图。
        # 否则人还站在补星关卡上，主循环会把这关当成正式关卡反复打（#10 卡住）。
        if page.chapter_panel_open():
            page.close_chapter_panel()
        for _ in range(2):
            if page.at_page():
                break
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.4)
        return done

    @staticmethod
    def _cond_stars(im) -> int:
        """结算页「当前战斗」下面的三个三星条件，金星 = 达成。

        2026-11-04 实测（f0021_142226 46-7）：星心 x≈268，三行 y≈692/745/790，
        旧实现取 (272,697/737/777) 单点均值 → 只要有一颗金星就够不着阈值，
        又会把「通关奖励」的金色误算成条件，结果时 0 时 3（补星重复打同一关）。
        改成按三条横带统计金星像素（星面 R>200,G>155,B<120），≥25px 记达成。
        """
        n = 0
        for y0, y1 in ((675, 712), (726, 764), (770, 810)):
            px = 0
            for x in range(248, 293):
                for y in range(y0, y1):
                    R, G, B = im.getpixel((x, y))
                    if R > 200 and G > 155 and B < 120:
                        px += 1
            if px >= 25:
                n += 1
        return n

    def _star_result(self, ui):
        """补星回放的结算页：左侧灰「确定」返回地图，右侧「下一关」不要点。

        返回 (结果, 达成的三星条件数)。
        """
        for _ in range(10):
            im = ui.screen("star_res")
            if vision.victory_banner(im):
                # 2026-11-04：胜利页入场时三颗条件星会先整体亮一遍（动画），
                # 立刻读会把 1/3 读成 3/3（补星就会对着同一关重复打）。等动画落定再读。
                ui.wait(1.2)
                im2 = ui.screen("star_res_settled")
                conds = self._cond_stars(im2)
                log.debug(f"  补星结算：三星条件达成 {conds}/3")
                ui.press((240, 1105), 220)
                ui.wait(2.2)
                return "win", conds
            if vision.defeat_page(im):
                pos = (360, 1060) if vision.is_gold(im, 360, 1060, r=16) else (235, 1055)
                ui.press(pos, 220)
                ui.wait(2.0)
                return "lose", 0
            if vision.classify(im) == State.DEPLOY:
                return "none", 0
            ui.wait(1.5)
        return "none", 0

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_stages = int(p.get("max_stages", 12))
        max_lose = int(p.get("max_lose", 10))
        star_fights = int(p.get("star_fights", 3))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = TreePage(ui)
        if not page.enter():
            return TaskResult.fail("进不去时光之树（历练列表滚到底也没找到入口）")
        for _ in range(6):                  # 树页加载慢，等标题出来再开始
            if page.at_page():
                break
            ui.wait(0.9)
        res = BattleResult(ui)
        rewards = page.claim_rewards()

        stars = self._star_phase(ui, page, star_fights) if star_fights > 0 else 0

        wins = losses = streak = 0
        arrow_tries = 0
        blanks = 0
        deadline = time.time() + int(45 * 60)
        while time.time() < deadline and wins < max_stages and streak < max_lose:
            if ui.handle_interruptions():
                continue
            im = ui.screen("tree")
            st = vision.classify(im)
            if st == State.RESULT_TREE:
                # 2026-11-19 假成功审计（audit2 TOP9）：以前先 wins += 1 再推结算页，
                # 结算页推不走时同一张页会被反复计数。现在先推页，确认离开了才计数。
                arrow_tries = blanks = 0
                res.next_tree()
                ui.wait(1.8)
                if vision.classify(ui.screen("tree_next_chk")) == State.RESULT_TREE:
                    log.info("  时光之树：点「下一关」后还停在结算页（按钮没响应），这次不计数，重试")
                    continue
                wins += 1
                streak = 0
                log.info(f"  时光之树通关 {wins}")
                continue
            if st == State.RESULT_GENERIC:
                # 章节最后一关的胜利页
                arrow_tries = blanks = 0
                ui.press(L.TREE_RESULT_OK_FINAL, 220)
                ui.wait(2.6)
                if vision.classify(ui.screen("tree_ok_chk")) in (State.RESULT_TREE, State.RESULT_GENERIC):
                    log.info("  时光之树：点「确定」后还停在结算页，这次不计数，重试")
                    continue
                wins += 1
                streak = 0
                log.info(f"  时光之树枝章节通关 {wins}")
                continue
            if st == State.DEPLOY:
                page.deploy_and_skip()
                continue
            # 2026-11-04 实测：章节打完会弹两种全屏浮层（都没有 X/确定，提示「点击空白处关闭」）：
            #   ①「获得奖励」奖励清单  ②「新章节开启 第N章」
            # 地图判定仍能命中，代码会去点翻页箭头 → diff=0 空耗 3×20s 后误判「没关卡可打」。
            if any(template.VI.find(im, n, 0.88)
                   for n in ("时光之树_获得奖励.png", "时光之树_新章节开启.png")):
                log.info("  时光之树：关掉章节浮层（获得奖励 / 新章节开启）")
                ui.press((360, 1060), 150, expect="none")
                ui.wait(1.4)
                continue
            # 树地图（蓝紫星图）会被误判成 BATTLE，所以挑战按钮要排在 BATTLE 之前判断
            if page.at_page(im):
                if vision.is_gold(im, *L.TREE_GO, r=18):
                    if not page.challenge():
                        log.info("  时光之树没有次数或被挡住")
                        break
                    arrow_tries = blanks = 0
                    continue
                # 2026-10-31 实测：整章都三星后地图上没有「挑战」，底部是「完美通关」，
                # 旧代码在这里一直点空白卡死。点左右箭头会翻到下一章（第29章全完美 →
                # 第30章 30-2 直接有挑战）。翻三章都没有就收手。
                if arrow_tries >= 3:
                    log.info("  时光之树：翻了几章都没有可挑战的关卡，收手")
                    break
                arrow_tries += 1
                # 翻页箭头很小、命中反馈弱：单次点击，靠下一轮重新判页，不做 4 点补偿（每次白等 ~20s）
                ui.press(L.TREE_NEXT_STAGE, 250, expect="none")
                ui.wait(2.2)
                continue
            if st == State.BATTLE:
                # 2026-11-08 全库复核（1800 帧）：跳过键 ▶| 恒在 (652,899)，暂停在
                # (669,781)、自动在 y≈775，ROI (600,850,720,950)+阈值 0.60 已把它们
                # 分开，classify!=battle 的帧零误命中 → 命中模板才点，未命中不盲点。
                # 旧注释「战斗态一律不点 UI」是 2026-11-04 用固定坐标 (655,900) 被
                # 坐标补偿漂到 860 误触暂停造成的；那是坐标问题，不是没有跳过键。
                if ui.battle_skip(im, label="tree_skip"):
                    ui.wait(1.2)
                else:
                    ui.wait(1.5)
                continue
            if st == State.CONFIRM_DIALOG:
                # 战斗/结算中偶发的确认框：点左侧「取消」关闭，绝不点右侧确定（避免退出战斗）
                log.warn(f"  战斗：出现确认弹窗（{L.CONFIRM_CANCEL}），点「取消」关闭")
                ui.press(L.CONFIRM_CANCEL, 180, expect="none")
                ui.wait(1.0)
                continue
            if st == State.RESULT_DEFEAT:
                losses += 1
                streak += 1
                arrow_tries = blanks = 0
                log.info(f"  时光之树失败 (连续 {streak})")
                # 树失败页的「确定」在正中 (360,1060)，点空白关不掉
                ui.press((360, 1060), 220)
                ui.wait(1.6)
                continue
            # 其他未知画面：兜底点空白；连续 5 次还认不出就尝试退回并重进树页
            # （2026-11-03：#10 用户手动切章节后脚本停在奇怪页面空转，旧阈值 25 太钝）
            # 2026-11-09 实测：8 次 × (press 0.15 + wait 1.4 + 抓帧 0.4) ≈ 30s 空转，
            # 收敛到 5 次 × wait 1.0（典型场景是结算/换章的过场动画，5 次足够跨过去）。
            blanks += 1
            if blanks >= 5:
                # 2026-11-09 第 27 轮：这是自愈动作（随后成功重进并继续打），
                # 按「WARN 只放真问题」的约定记 info。
                log.info("  时光之树：连续认不出画面，退回并重新进入树页（自愈）")
                ui.press(L.BACK, 250, expect="none")
                ui.wait(1.6)
                page.enter()
                ui.wait(2.2)
                if page.at_page():
                    blanks = 0
                    continue
                log.info("  时光之树：重进失败，收手")
                break
            ui.press(L.BLANK, 150, expect="none")
            ui.wait(1.0)
        # 打完再领一次奖励（补星/通关可能刚好推满新档位）
        rewards += page.claim_rewards()
        page.leave()
        MainCity(ui).ensure()
        # 2026-11-10：和塔一样的口径 —— 主线连败打满 max_lose 且一场没赢，
        # 是「这一章战力不足」的真状态，不是脚本故障（旧版记 FAIL 会让 scheduler
        # 自愈重跑一整轮，实测 305s×2 + 邪能 91s 全白跑）。
        beaten = losses >= max_lose and wins == 0
        stats = {"stars": stars, "wins": wins, "losses": losses, "rewards": rewards}
        msg = f"时光之树: 补星 {stars} 场 / 主线胜 {wins} 败 {losses} / 领奖 {rewards}"
        if beaten:
            msg += f"（主线连败 {losses} 次，该章战力不足，今天打不动）"
        if wins == 0 and stars == 0 and losses == 0:
            # 一次都没打成（挑战钮不可用 / 没次数），与「连败打满」区分开
            stats["noop_ok"] = True
            return TaskResult(True, f"跳过：{msg}（今天没有能推进的关卡或次数为 0）", stats)
        return TaskResult(wins > 0 or stars > 0 or beaten, msg, stats)


class DemonTask(BaseTask):
    """邪能神殿（2026-10-29 实测）。

    每日第一次进入：底部大按钮先是一键扫荡，再连续变成选择加成（符文自动选择，约十来个），
    全部选完后才变成挑战开打；战斗里有两支队伍，要按 2~3 次跳过才结束；每 10 关又弹一次符文选择。
    底部大按钮的可靠命中点在按钮下沿 (360,1198)，布阵页的按钮在 y≈1230
    （2026-11-08 实测：旧注释写的 y≈1253 已在按钮下沿之外，会触发坐标补偿漂到竞技页）。
    """

    name = "demon"
    title = "邪能神殿"
    category = "combat"

    SKIP_POINT = (655, 910)

    def _deploy_and_fight(self, ui) -> str:
        """布阵页：填队 → 开打。返回 "battle" / "gave_up"。

        2026-11-08 07:28 真帧定案（tests/fixtures/demon_run2_*、demon_deploy）：
        两支队伍的关卡（如 49-10），底部右侧大金钮第一次是「下一队」
        （rgb≈(214,176,119)，底部条带 OCR 读得到「下一队」），切到二队并一键上阵后
        才变成「战斗」（rgb≈(241,234,200)，OCR 认不出字）；单队关卡直接就是「战斗」。
        旧代码认到金钮就点一次 → 实际点了「下一队」→ 切到二队后没人再点「战斗」
        → 13s 停在布阵页收手，整段记「通关 0 关」。
        """
        for step in range(4):
            im = ui.screen(f"demon_dep{step}")
            row = textocr.read_text(im, L.DEMON_DEP_ROW) if textocr.available() else ""
            if vision.is_green(im, *L.DEMON_DEPLOY, r=18) or vision.is_gold(
                    im, *L.DEMON_DEPLOY, r=18):
                ui.press(L.DEMON_DEPLOY, 200, label=f"demon_deploy{step}", expect="none")
                ui.wait(1.2)
                im = ui.screen(f"demon_dep_after{step}")
                row = textocr.read_text(im, L.DEMON_DEP_ROW) if textocr.available() else row
            if "下一队" in row:
                log.info(f"  邪能布阵页：右钮是「下一队」（第 {step + 1} 队要填），先切队再上阵")
                ui.press(L.DEMON_FIGHT, 220, label=f"demon_next_team{step + 1}", expect="none")
                ui.wait(1.4)
                continue
            if not vision.is_gold(im, *L.DEMON_FIGHT, r=16) and not vision.is_gold(
                    im, *L.DEMON_FIGHT_ALT, r=16):
                # 2026-11-08 15:52：这一帧可能正好卡在上阵动画/按钮高亮过渡里
                # （logs\_full5_142032.log 14:52:54 就是这样放弃的，整段记「0 关」）。
                # 等一拍再看一眼，并补读一次按钮条文字，才判「真的没有战斗钮」。
                ui.wait(1.4)
                im = ui.screen(f"demon_dep_retry{step}")
                if textocr.available():
                    row = textocr.read_text(im, L.DEMON_DEP_ROW) or row
                if "下一队" in row:
                    continue
                if not vision.is_gold(im, *L.DEMON_FIGHT, r=16) and not vision.is_gold(
                        im, *L.DEMON_FIGHT_ALT, r=16):
                    log.warn("  邪能布阵页：右钮不是金色（上阵可能没生效），收手")
                    return "gave_up"
            ui.press(L.DEMON_FIGHT, 220, label=f"demon_fight{step}", expect="none")
            for _ in range(8):
                ui.wait(1.6)
                st = vision.classify(ui.screen(f"demon_dep2_{step}"))
                if st in (State.BATTLE, State.RESULT_TREE,
                          State.RESULT_GENERIC, State.RESULT_DEFEAT):
                    return "battle"
            log.warn("  邪能布阵页：点了「战斗」13s 还停在布阵页，收手（不乱点）")
            return "gave_up"
        log.warn("  邪能布阵页：切队/上阵来回 4 次仍没到「战斗」，收手")
        return "gave_up"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_stages = int(p.get("max_stages", 20))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = DemonPage(ui)
        if not page.enter():
            return TaskResult.fail("进不去邪能神殿（历练列表里没找到入口）")

        wins = picks = 0
        att = 0                # 2026-11-09 假成功审计 M6：真正进入战斗的次数
        armed = False          # 2026-11-19 审计 C5：本轮按过挑战/进入过战斗
        lost = False           # 真打过但输了（真状态，不算脚本故障）
        noop = False           # 今天已完成/没有可点按钮（真状态，不是脚本故障）
        unknown = 0
        same = 0
        transient = 0          # 结算/换场时认不出画面的连续帧数（2026-11-08）
        deadline = time.time() + 40 * 60
        while wins < max_stages and time.time() < deadline:
            if ui.handle_interruptions():
                continue
            im = ui.screen("demon")
            if page.maybe_reward_popup(im):
                # 2026-11-08：快速挑战瞬间结算后会弹「获得奖励 … 点击空白处关闭」，
                # 浮层盖住底部按钮；旧版这里认不出按钮 → 记「通关 0 关」直接收手。
                page.dismiss_rewards(im)
                same = 0
                # 2026-11-19 审计 C5：以前「看到浮层就 +1」，任务刚进来时上一轮残留的
                # 浮层也会被算成一次通关。现在要求本轮按过挑战/进过战斗。
                if armed:
                    armed = False
                    wins += 1
                    log.info(f"  邪能通关 {wins}（快速挑战结算，已关掉奖励浮层）")
                else:
                    log.info("  邪能神殿：看到奖励浮层，但本轮还没按过挑战，"
                             "当残留浮层关掉（不计入通关）")
                continue
            if page.buff_dialog(im):
                if page.pick_buff():
                    picks += 1
                    log.info(f"  选择加成 ×{picks}")
                else:
                    noop = True
                    break
                continue
            st = vision.classify(im)
            if st == State.RESULT_TREE:
                # 按实测金带中心点「下一关」（固定 (495,1130) 压在按钮下沿，
                # 偶尔 MISS 后靠 -8 补偿才命中，白花 2s）
                nxt = vision.gold_band_center(im, L.RESULT_BTN_ZONE)
                if nxt is None:
                    # 2026-11-20 审计 MAJOR：金带读不到时不再按写死坐标点，
                    # 等一下重抓帧（结算页偶有淡入动画）。
                    log.info("  邪能神殿：结算页读不到「下一关」金钮，等 1.5s 再看（不按死坐标）")
                    ui.wait(1.5)
                    continue
                ui.press(nxt, 220, label=f"demon_next:{nxt[1]}", expect="none")
                ui.wait(2.2)
                # 2026-11-19 假成功审计（audit2 TOP2）：结算页分支以前既没有 armed 门
                # 也不复核翻页 —— 结算页推不走时同一张页会反复 +1。
                if not armed:
                    log.info("  邪能神殿：结算页出现时本轮还没按过挑战（上一轮的残留页），不计入")
                    continue
                if vision.classify(ui.screen("demon_next_chk")) == State.RESULT_TREE:
                    log.info("  邪能神殿：点「下一关」后还停在结算页（按钮没响应），这次不计数，重试")
                    continue
                armed = False
                wins += 1
                same = 0
                log.info(f"  邪能通关 {wins}")
                continue
            if st == State.RESULT_GENERIC:
                # 章节最后一关：结算页只有「确定」，同样按金带中心点
                ok = vision.gold_band_center(im, L.RESULT_BTN_ZONE)
                if ok is None:
                    log.info("  邪能神殿：结算页读不到「确定」金钮，等 1.5s 再看（不按死坐标）")
                    ui.wait(1.5)
                    continue
                ui.press(ok, 220, label=f"demon_final:{ok[1]}", expect="none")
                ui.wait(2.4)
                if not armed:
                    log.info("  邪能神殿：结算页出现时本轮还没按过挑战（上一轮的残留页），不计入")
                    continue
                if vision.classify(ui.screen("demon_final_chk")) in (State.RESULT_TREE, State.RESULT_GENERIC):
                    log.info("  邪能神殿：点「确定」后还停在结算页，这次不计数，重试")
                    continue
                armed = False
                wins += 1
                same = 0
                log.info(f"  邪能通关 {wins}（本章完成）")
                continue
            if st == State.RESULT_DEFEAT:
                shot = ui.screen("demon_defeat")
                # 实测战败页「确定」金带 (363,1088)；旧码试 (360,1060)/(235,1055) 都偏
                pos = vision.gold_band_center(shot, L.RESULT_BTN_ZONE)
                if pos is None:
                    # 战败页读不到「确定」就不按死坐标（会把流程带偏），最多重试 3 次
                    defeat_none = getattr(self, "_defeat_none", 0) + 1
                    self._defeat_none = defeat_none
                    if defeat_none >= 3:
                        lost = True
                        log.info("  邪能神殿：战败页连着 3 次读不到「确定」金钮，收手（不按死坐标）")
                        break
                    log.info("  邪能神殿：战败页读不到「确定」金钮，等 1.5s 再看（不按死坐标）")
                    ui.wait(1.5)
                    continue
                ui.press(pos, 220, label=f"demon_defeat_ok:{pos[1]}", expect="none")
                ui.wait(1.6)
                lost = True
                log.info("  邪能战斗失败，停止")
                break
            if st == State.DEPLOY:
                # 2026-11-08 06:21 真帧定案：布阵页两个按钮都在 y≈1229
                # （一键上阵绿 (296,1229)、战斗金 (528,1228)）。旧代码点 (525,1225)
                # 的死点，会触发坐标补偿 (0,-8/8/16) 一路漂到主城底栏「竞技」，
                # 直接跳到争霸赛页，把整段邪能流程带跑偏（通关记 0 关）。
                # 现在：先金/绿判据确认，再 expect="none" 点死点，最后轮询等真进战斗。
                # 2026-11-08 07:28：两支队伍的关卡，右钮先写「下一队」（rgb≈(214,176,119)），
                # 切队并一键上阵后才变「战斗」（rgb≈(241,234,200)，OCR 认不出字）。
                # 交给 _deploy_and_fight 按条带文字决定切队还是开打。
                if self._deploy_and_fight(ui) == "gave_up":
                    break
                att += 1
                armed = True
                continue
            if st == State.BATTLE:
                # 2026-11-08 真帧纠正（tests/fixtures/demon_*）：邪能战斗页右侧是
                # 「暂停 / 自动 / ×2 / ▶|」四键，▶| 就在 (652,899)，模板 0.82 稳定命中。
                # 旧注释「没有跳过键」是错的（当时用固定 (655,910) 盲点，落在按钮
                # 下沿外，diff=0.000 白赔 8s 补偿）。仍不点暂停/自动/×2，只点跳过。
                if ui.battle_skip(im, label="demon_skip"):
                    ui.wait(1.6)
                else:
                    ui.wait(2.0)
                continue

            if st == State.UNKNOWN:
                # 战斗过场/结算动画会被判成 UNKNOWN。旧版这里落到 press_main →
                # 认不出按钮 →「不在邪能神殿页，重新进入」，把正在跑的战斗打断。
                # 2026-11-08 07:27:31 真帧（demon_1523）：邪能主页面本身 classify=UNKNOWN，
                # 底部大按钮却是金的 → 这种情况直接走 press_main，别白等 7s。
                if (vision.is_gold(im, *L.DEMON_CHALLENGE, r=16)
                        or vision.is_gold(im, *L.DEMON_CHALLENGE_ALT, r=16)):
                    unknown = 0
                else:
                    unknown += 1
                    if unknown <= 5:
                        ui.wait(1.4)
                        continue
                    log.warn("  邪能神殿：连续认不出画面（约 7s），按老路继续")
            else:
                unknown = 0

            r = page.press_main()
            if r in ("deploy", "battle"):
                armed = True
                same = 0
                continue
            if r == "same":
                # 一键扫荡/符文自动选择阶段：按一下画面不变但流程在推进。
                # 2026-11-20 审计 MAJOR：这里原来也把 armed 置真，等于让残留的
                # 结算/奖励浮层也能被算成一次通关 —— armed 只在 r 为 deploy/battle
                # （真进过布阵或战斗）时才置真，无变化分支保持原值。
                same += 1
                if same >= 4:
                    log.info("  邪能神殿连续点击无变化，停止（今日大概已完成/次数为 0）")
                    noop = True
                    break
                ui.wait(1.0)
                continue
            on_page = page.at_page()
            if on_page:
                transient = 0
            else:
                # 重进前再确认一次：可能只是过场帧，别打断正在跑的战斗。
                again = vision.classify(ui.screen("demon_recheck"))
                if again in (State.BATTLE, State.DEPLOY, State.RESULT_TREE,
                             State.RESULT_GENERIC, State.RESULT_DEFEAT):
                    log.info(f"  邪能神殿：再确认是 {again.value}，继续等（不重进）")
                    same = 0
                    continue
                # 2026-11-08：换场/结算会出现 nav_page / title 这类瞬时帧
                # （真帧序列：nav_page → title → nav_page → 主城 → 重进 → battle，
                # 战斗其实没断）。连认不出 2 帧就先等一等，别急着退出重进（每次 ~25s）。
                if transient < 2:
                    transient += 1
                    log.info(f"  邪能神殿：画面瞬时认不出（{again.value}，第 {transient}/2 帧），"
                             f"等一等（不重进）")
                    ui.wait(1.8)
                    continue
            log.info("  邪能神殿没有可点的按钮（今日可能已完成）" if on_page else
                     "  不在邪能神殿页，重新进入")
            if on_page:
                noop = True
            if not on_page:
                if page.busy():
                    # 2026-11-08：画面其实是战斗/布阵（只是没认出按钮），别重进。
                    log.info("  邪能神殿：画面其实是战斗/布阵，继续等（不重进）")
                    ui.wait(1.8)
                    continue
                if page.enter():
                    transient = 0
                    continue
            break

        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        stats = {"wins": wins, "picks": picks, "starts": att}
        if wins == 0 and picks == 0 and att == 0 and not lost and not noop:
            # 2026-11-09 假成功审计 M6：入口/大按钮/加成一条都没走通，不能报 OK
            return TaskResult(False, "邪能神殿：一关都没打成、加成也没选到"
                                     "（入口/挑战钮都没走通）", stats)
        if wins == 0 and picks == 0:
            stats["noop_ok"] = True
            return TaskResult(True, f"跳过：邪能神殿今天没进展"
                                     f"（开打 {att} 次，加成 {picks} 次，今日已通关/次数为 0）",
                              stats)
        return TaskResult(True, f"邪能神殿: 通关 {wins} 关，加成 {picks} 次", stats)
