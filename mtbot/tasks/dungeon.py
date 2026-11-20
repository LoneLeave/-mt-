"""日常副本（历练页顶部「海量资源」，2026-10-30 实测）。

四个子副本共用一套页面：经验 / 金币 / 进阶 / 装备。
用户规则：**先推进，打不过再扫荡，打完记得领取宝箱奖励**。

- 每列关卡里只有一个金色「挑战」（下一层）；已通关那层是灰绿「已通过」印章（不是按钮）；
- 2026-11-07 实测：页面已不再渲染绿色「免费扫荡」钮，行内只剩 `💎20/30/50扫荡`（付费），
  所以「扫荡 0 次」是当前版本的真值（详见 `DungeonTask._sweep` 注释）；
- 底部大按钮「一键扫荡」带钻石扫荡（默认勾选钻石，共 350 钻），脚本永不点它；
- 右上角宝箱是「通关奖励」里程碑，进度达标后行内出现金色「领取」。
"""
from __future__ import annotations

import re
import time

from .. import layout as L
from .. import log, textocr, vision
from ..pages import DungeonPage, MainCity, TrialsHub
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult


def _sweep_hint(ui) -> str:
    """列表页上「今日扫荡：N/6」和行内「20扫荡」之类的提示（只为日志说明）。"""
    try:
        return textocr.read_text(ui.screen("dun_hint"), (430, 520, 700, 960))
    except Exception:
        return ""


def _paid_row_text(hint: str) -> str:
    """从提示文字里抠出「💎30扫荡」那种付费按钮行，给日志用。"""
    m = re.search(r"(\d{1,3})\s*扫荡", hint or "")
    return f"{m.group(1)}扫荡" if m else ""


class DungeonTask(BaseTask):
    name = "dungeon"
    title = "日常副本（经验/金币/进阶/装备）"
    category = "combat"

    VICTORY_OK = (360, 1050)      # 副本胜利页「确定」
    DEFEAT_OK = (360, 1060)
    DEFEAT_OK_LEFT = (235, 1055)

    def _result(self, ui) -> str:
        """处理结算页，返回 win / lose / none。"""
        for _ in range(10):
            im = ui.screen("dun_res")
            st = vision.classify(im)
            if st == State.DEPLOY:
                return "none"
            if st == State.RESULT_DEFEAT or vision.defeat_page(im):
                pos = (self.DEFEAT_OK if vision.is_gold(im, *self.DEFEAT_OK, r=16)
                       else self.DEFEAT_OK_LEFT)
                ui.press(pos, 220)
                ui.wait(2.2)
                return "lose"
            if vision.victory_banner(im):
                ui.press(self.VICTORY_OK, 220)
                ui.wait(2.4)
                return "win"
            if st in (State.RESULT_TOWER, State.RESULT_TREE, State.RESULT_GENERIC,
                      State.RESULT_LEGEND):
                # 2026-11-19 审计：这里原来只要「是某个结算态」就 return "win"，
                # 而走到这一行时 victory_banner 已经判过是 False —— 等于把认不出
                # 胜负的结算页一律记成通关。改成如实报 unknown：不记通关、不记失败。
                ui.press((370, 1130), 220)
                ui.wait(2.2)
                log.info("  日常副本：结算页认不出「胜利」横幅（形态变了），这一层不按通关计")
                return "unknown"
            # 2026-11-09：胜利页「确定」(360,1050) 与失败页「确定」(360,1060) 几乎同一点，
            # 单看金色会把战败记成胜利；实测 23 张结算帧 victory_banner 与胜负 100% 一致。
            if vision.victory_banner(im) and vision.is_gold(im, *self.VICTORY_OK, r=16):
                ui.press(self.VICTORY_OK, 220)
                ui.wait(2.4)
                return "win"
            ui.wait(1.6)
        return "none"

    def _push(self, ui, page: DungeonPage, limit: int) -> tuple[int, bool]:
        """把当前副本往前推进，返回 (推了几层, 是否打输了)。"""
        wins = 0
        for _ in range(limit):
            if not page.at_page():
                log.warn("  日常副本：推进途中跑偏（不在副本列表页），停止推进")
                return wins, False
            pos = page.find_challenge()
            if pos is None:
                log.info("  日常副本：没有可挑战的下一层了")
                return wins, False
            ui.press(pos, 250)
            ui.wait(2.6)
            st = vision.classify(ui.screen("dun_after"))
            if st != State.DEPLOY:
                if st in (State.DIALOG, State.MAIN_CITY_DIM):
                    ui.close_popup()
                log.info("  日常副本：挑战没进布阵页（次数或等级限制），停止推进")
                # 2026-11-18 第 44 轮实测：这一下没进布阵页就不会自动回列表，
                # 后面的「扫荡/宝箱/切页签」全落在别的页面上（3 条 WARN）。
                # 收手前先把页面拉回副本列表页，后续步骤才有着落点。
                page.ensure_page()
                return wins, False
            ui.press(L.DEPLOY, 200, expect="none")
            ui.wait(1.0)
            ui.press(L.FIGHT, 200, label="fight", expect="none")
            # 2026-11-10 第 40 轮：09:55:36 点完「战斗」后画面仍是 deploy
            # （按钮没注册上），battle_finish 在宽限期内没见到 BATTLE 就返回了，
            # 于是后面的扫荡/宝箱/切页签全跑在布阵页上（4 条 WARN）。
            # 这里先复核一次：仍在布阵页就再点一次「战斗」。
            ui.wait(2.2)
            if vision.classify(ui.screen("dun_fightchk")) == State.DEPLOY:
                ui.press(L.FIGHT, 200, label="fight_retry", expect="none")
                ui.wait(1.0)
            # 2026-11-08：轮询式跳过，2~4 秒进结算，不再白等 8 秒
            ui.battle_finish(label="dun_skip", timeout=14.0)
            if not getattr(ui, "battle_started", True):
                # 2026-11-19 审计 B2：14s 内一次战斗画面都没见到 = 这场没打起来。
                # 回列表页并按「没打成」处理，别把布阵页当成结算页去点扫荡/宝箱。
                log.info("  日常副本：这一层没进战斗画面（次数/等级限制或加载慢），"
                         "回副本列表页、不按已打处理")
                page.ensure_page()
                return wins, False
            ui.wait(1.8)
            r = self._result(ui)
            if r == "none":
                # 2026-11-08：结算没出来就再推一轮（战斗可能还在打），
                # 推不动才算真失败，别把「还在打」直接当「没打赢」。
                ui.battle_finish(label="dun_skip2", timeout=14.0)
                ui.wait(1.2)
                r = self._result(ui)
            if r != "win":
                if r == "unknown":
                    # 结算页认不出胜负：不记通关也不记失败，交给后面的扫荡兜底。
                    log.info(f"  日常副本：第 {wins + 1} 层结算页认不出胜负，改用扫荡")
                    if not page.at_page():
                        ui.handle_interruptions()
                        if not page.at_page():
                            page.ensure_page(tries=2)
                    return wins, False
                if r == "none":
                    # 2026-11-07：跳过没生效/还在打时也会走到这里，别说成「没打赢」
                    log.info(f"  日常副本：第 {wins + 1} 层没结算出来（跳过没生效或战斗还在打），改用扫荡")
                    # 2026-11-10：先确认人在副本列表页；不在就先回去，
                    # 否则扫荡/宝箱/切页签全会在异常页面上空跑（第 40 轮 4 条 WARN）。
                    if not page.at_page():
                        ui.handle_interruptions()
                        if not page.at_page():
                            page.ensure_page(tries=2)
                else:
                    log.info(f"  日常副本：第 {wins + 1} 层没打赢（结算页判为「{r}」），改用扫荡")
                return wins, True
            wins += 1
            log.info(f"  日常副本：通关第 {wins} 层")
        return wins, False

    @staticmethod
    def _sweep_counts(im):
        """读「今日扫荡：N/6」→ (n, total) 或 None。"""
        try:
            txt = textocr.read_text(im, L.DUNGEON_SWEEP_TEXT)
        except Exception:      # noqa: BLE001
            return None
        m = re.search(L.DUNGEON_SWEEP_RE, txt)
        return (int(m.group(1)), int(m.group(2))) if m else None

    def _sweep_paid(self, ui, page: DungeonPage, limit: int, ctx, d0: int | None = None) -> int:
        """用钻石买「扫荡次数」：弹窗里读花费 → 确认 → 「今日扫荡」+1 才算买到。"""
        n = 0
        for _ in range(max(1, limit)):
            im = ui.screen("dun_paid0")
            # 2026-11-11 第 51 轮：结算/提示浮层会把「今日扫荡 N/6」那一行盖住，
            # 于是读不到计数（不盲买是对的，但等于没买成）→ 先确认还在列表页。
            if not page.at_page(im):
                ui.handle_interruptions()
                if not page.at_page():
                    page.ensure_page(tries=2)
                ui.wait(0.8)
                im = ui.screen("dun_paid0b")
            raw = ""
            try:
                raw = textocr.read_text(im, L.DUNGEON_SWEEP_TEXT)
            except Exception:      # noqa: BLE001
                raw = ""
            flat_raw = raw.replace(" ", "")
            if any(k in flat_raw for k in ("已用完", "购买上限")):
                log.info(f"  日常副本：游戏写着「{flat_raw[:14]}」→ 今日扫荡次数已到购买上限，不再买")
                break
            before = self._sweep_counts(im)
            if before is None:
                log.info("  日常副本：读不到「今日扫荡 N/6」，不盲买次数")
                break
            if before[0] >= before[1]:
                log.info(f"  日常副本：今日扫荡已满（{before[0]}/{before[1]}），不再买")
                break
            if not self.may_spend(ctx, "日常副本·扫荡次数", 20, kind="attempt"):
                break
            ui.press(L.DUNGEON_PAID_SWEEP, 250, label="dun_paid_sweep", expect="none")
            ui.wait(1.8)
            dlg = ui.screen("dun_paid1")
            txt = ""
            try:
                txt = textocr.read_text(dlg, L.DUNGEON_SWEEP_DLG_BOX)
            except Exception:      # noqa: BLE001
                txt = ""
            flat = txt.replace(" ", "")
            m = re.search(r"花费\s*(\d+)", flat)
            if "扫荡" not in flat or not m:
                log.info(f"  日常副本：点付费扫荡后没看到「是否花费 N…扫荡」弹窗"
                         f"（OCR：{flat[:24] or '空'}），不确认")
                if vision.dialog_confirm(dlg):
                    ui.press(L.DUNGEON_SWEEP_DLG_CANCEL, 200,
                             label="dun_paid_cancel", expect="none")
                break
            cost = int(m.group(1))
            ui.press(L.DUNGEON_SWEEP_DLG_OK, 220, label="dun_paid_ok", expect="none")
            ui.wait(2.4)
            ui.press(L.BLANK, 150, expect="none")
            ui.wait(0.9)
            after = self._sweep_counts(ui.screen("dun_paid2"))
            ok = False
            why = ""
            if after is None:
                # 计数变成「今日扫荡次数已用完」= 这一次把最后的额度用掉了
                ok = before[0] <= 1
                why = f"计数变成「今日扫荡…已用完」（{before[0]}/{before[1]} → 0）"
            elif after[0] == before[0] - 1:
                ok = True
                why = f"计数 {before[0]}/{before[1]} → {after[0]}/{after[1]}（花钻扫荡一次）"
            else:
                why = f"计数没按预期 -1（{before[0]}/{before[1]} → {after[0]}/{after[1]}）"
            if not ok:
                log.info(f"  日常副本：点了「购买」但没生效：{why}，不认这次购买")
                break
            n += 1
            self._paid_nominal = int(getattr(self, "_paid_nominal", 0)) + cost
            log.info(f"  日常副本：买扫荡并执行 ×{n}（花 {cost} 钻，{why}）")
        return n

    def _sweep(self, ui, page: DungeonPage, limit: int) -> int:
        """免费扫荡（绿色实心钮）。每次点完会弹「获得奖励」，点空白关掉。

        2026-11-07 复核（`logs\_dun_sweep_audit.py`、`_dun_scanall.py`、`_dun_up.py`）：
        列表里**已经没有绿色免费扫荡钮**——上下各翻 3~9 屏，带「扫荡」字样的只有
        `今日扫荡：N/6` 与行内 `💎20/30/50扫荡`（金色 + 左侧青色钻石，付费）；
        已通关行上是灰绿「已通过」印章（R≈152~178，`is_green` 为 False）。
        点 `💎30扫荡` 会弹「是否花费 30（拥有 9166）进行1次扫荡」，所以**绝不点**；
        底部「一键扫荡」是共 350 钻的面板（y≈1105，`DUNGEON_BTN_SCAN` 只到 980，不在范围）。
        也就是说：`find_sweep() is None` 是当前画面的**真值**，不是漏判。
        """
        n = 0
        for _ in range(limit):
            pos = page.find_sweep()
            if pos is None:
                # 同上：先确认画面还在副本列表页，否则「找不到免费扫荡」可能是浮层遮的
                if not page.at_page(ui.screen("dun_sw_chk")):
                    ui.handle_interruptions()
                    if not page.at_page():
                        page.ensure_page(tries=2)
                    pos = page.find_sweep()
                    if pos is not None:
                        continue
                hint = _sweep_hint(ui)
                rest = ""
                m = re.search(r"今日扫荡[：:]\s*(\d+)\s*/\s*(\d+)", hint or "")
                if m:
                    rest = f"，界面写着「今日扫荡 {m.group(1)}/{m.group(2)}」"
                if n:
                    log.info(f"  日常副本：又没绿色「免费扫荡」了，扫荡结束（本轮 {n} 次）{rest}")
                else:
                    log.info(
                        "  日常副本：列表里没有绿色「免费扫荡」按钮，行内只有"
                        f"「{_paid_row_text(hint) or '💎N扫荡'}」（付费，不点）{rest}"
                    )
                break
            before = ui.screen("dun_sweep0")
            ui.press(pos, 250)
            ui.wait(2.0)
            after = ui.screen("dun_sweep1")
            if vision.similar(before, after):
                log.info("  日常副本：扫荡次数用完了")
                break
            ui.press(L.BLANK, 150, expect="none")
            ui.wait(0.9)
            n += 1
            log.info(f"  日常副本：免费扫荡 ×{n}")
        return n

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        push_limit = int(p.get("max_push", 3))
        sweep_limit = int(p.get("sweeps", 6))
        # 2026-11-10 用户 m18598「日常副本次数没有购买」：免费扫荡没了之后，
        # 允许用钻石买扫荡次数（kind="attempt"，属「买次数」白名单）。
        buy_sweeps = int(p.get("buy_sweeps", 3))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        # 2026-11-11：买扫荡的钻石基线必须在**主城**读（副本页顶栏不是钻石）。
        # 读不到基线就不买（无自证不花钻）。
        d0 = self.diamonds_stable(ui, "dun_d0") if buy_sweeps > 0 else None
        if buy_sweeps > 0 and d0 is None:
            log.info("  日常副本：主城钻石读数失败 → 本轮不买扫荡次数（无自证不花钻）")
            buy_sweeps = 0
        if not TrialsHub(ui).enter("dungeon"):
            return TaskResult.fail("进不去日常副本（历练列表里没找到入口）")
        ui.wait(1.2)
        page = DungeonPage(ui)
        self._paid_nominal = 0

        total_wins = total_sweeps = total_chests = 0
        ok_tabs = 0
        deadline = time.time() + 60 * ctx.cfg.runtime.max_task_minutes
        for key in DungeonPage.ORDER:
            if time.time() > deadline:
                break
            if not page.tab(key):
                log.warn(f"  日常副本：{key} 页签回不去，跳过这一类（不在别的页面点按钮）")
                continue
            ok_tabs += 1
            wins, lost = self._push(ui, page, push_limit)
            total_wins += wins
            sweeps = 0
            if lost:
                sweeps = self._sweep(ui, page, sweep_limit)
                if buy_sweeps > 0:
                    sweeps += self._sweep_paid(ui, page, buy_sweeps, ctx, d0=d0)
                total_sweeps += sweeps
            chests = page.claim_chest()
            total_chests += chests
            log.info(f"  日常副本·{key}：推进 {wins}、扫荡 {sweeps}、宝箱 {chests}")

        MainCity(ui).ensure()
        nominal = int(getattr(self, "_paid_nominal", 0))
        d1 = self.diamonds_stable(ui, "dun_d1") if buy_sweeps > 0 else None
        if nominal > 0:
            if d0 is not None and d1 is not None:
                spent = d0 - d1
                if spent == nominal:
                    log.info(f"  日常副本：买扫荡花钻 {spent}（主城 {d0}→{d1}），账目一致")
                else:
                    log.warn(f"  日常副本：买扫荡名义 {nominal} 钻，主城实际 {d0}→{d1}"
                             f"（差 {spent}），对不上，请核对")
            else:
                log.info(f"  日常副本：买扫荡名义 {nominal} 钻，但主城钻石读数缺证"
                         f"（{d0}→{d1}）")
        stats = {"wins": total_wins, "sweeps": total_sweeps, "chests": total_chests,
                 "tabs": ok_tabs, "paid_sweeps_nominal": nominal,
                 "diamonds_before": d0, "diamonds_after": d1}
        if ok_tabs == 0:
            # 一次页签都没进去 = 根本没进到副本页，不能报 OK
            return TaskResult.fail("日常副本：四个子副本页签一个都没进去", stats)
        return TaskResult(True,
                          f"日常副本：推进 {total_wins} 层、扫荡 {total_sweeps} 次、宝箱 {total_chests}",
                          stats)
