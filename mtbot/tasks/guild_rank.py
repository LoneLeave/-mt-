"""公会排位赛（挑「未击败」里战力最低的对手打，只用免费次数）。

真机结构（logs/_probe_guildrank.py / _guildrank2.py，2026-11-11 18:39~18:40）：
- 公会页有 `公会排位赛` 入口（OCR 命中「排位」即进）。
- 对局页左上角 `挑战次数：3/3`（框 (60,150,270,200)）。
- 对手是两列格子，每格三行：状态（`已击败` / `100%` / `x10`）、`[西部XX服]名字`、战力（`3.77亿`）。
- 点格子 → 布阵/阵容页（整排 `1250级/1300级…`、`助战`、`扫荡奖励`），**金色「挑战」在 (358,916)**。

安全边界：只打「未击败」的对手；不点「扫荡奖励」；不买次数（次数为 0 就收手）。
"""
from __future__ import annotations

import re

from .. import layout as L
from .. import log
from .. import template as _T, textocr, vision
from ..pages import MainCity
from ..ui import State
from .base import BaseTask, TaskContext, TaskResult

POWER_RE = re.compile(r"([\d.]+)\s*(亿|万)")
ATTEMPT_RE = re.compile(r"挑战次数[：:]([0-9]{1,2})/([0-9]{1,2})")


class GuildRankTask(BaseTask):
    name = "guild_rank"
    title = "公会排位赛（挑最低战力的未击败对手）"
    category = "pvp"

    @staticmethod
    def _attempts(im) -> tuple[int, int] | None:
        """读「挑战次数：N/M」。

        2026-11-18 实测：窄框 OCR 会把「0/3」读成「挑战次数： 3」（0/ 丢失），
        于是整条判定退化成「读不到次数」。这里先拍平整行正则，再退一步用
        read_lines 把同一行里孤立的两个数字拼起来。
        """
        txt = ""
        try:
            txt = textocr.read_text(im, L.GUILD_RANK_ATTEMPT_BOX) or ""
        except Exception:
            txt = ""
        flat = re.sub(r"\s+", "", txt)
        m = ATTEMPT_RE.search(flat)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        # 兜底：同框里如果只有「挑战次数」+一串数字，按「0/M」「N/M」两种理解都不确定，
        # 宁可返回 None 也绝不猜，交给上层「不敢打」。
        return None

    @staticmethod
    def _closed(im) -> bool:
        """页面是不是「未开启」状态（只有预告文案，没有挑战次数）。"""
        try:
            txt = textocr.read_text(im, L.GUILD_RANK_CLOSED_BOX) or ""
        except Exception:
            return False
        flat = txt.replace(" ", "")
        return any(k.replace(" ", "") in flat for k in L.GUILD_RANK_CLOSED_KEYS)

    @staticmethod
    def _power(val: str, unit: str) -> float:
        try:
            v = float(val)
        except ValueError:
            return 0.0
        return v * (1e8 if unit == "亿" else 1e4)

    @staticmethod
    def _flat(im, box) -> str:
        try:
            return (textocr.read_text(im, box) or "").replace(" ", "").replace("\n", "")
        except Exception:      # noqa: BLE001
            return ""

    def _info_open(self, im) -> bool:
        """点对手格子后弹出的「敌阵信息」层（写 敌阵信息 / 击败可得 / 挑战次数）。"""
        flat = self._flat(im, L.GUILD_RANK_INFO_BOX)
        return any(k in flat for k in L.GUILD_RANK_INFO_KEYS)

    def _result_of(self, im) -> str | None:
        """结算页判胜负：读 MVP 大横幅（实测「MVP 败方 失败」）。

        2026-11-18 实机：横幅字在 (340,220,720,520) 内能 1.00 读出；不用
        classify（失败页是 result_defeat，胜利页可能是 result_tree/generic，不稳定）。
        """
        flat = self._flat(im, L.GUILD_RANK_BANNER_BOX)
        if "失败" in flat or "败方" in flat:
            return "lose"
        if "胜利" in flat or "胜方" in flat:
            return "win"
        return None

    def _opponents(self, im):
        """返回 [(power, x, y, beaten)]，按战力行的中心定位。"""
        lines = textocr.read_lines(im, L.GUILD_RANK_GRID, min_score=0.4)
        out = []
        for t, c, _bb, s in lines:
            m = POWER_RE.search(t.replace(" ", ""))
            if not m:
                continue
            px, py = c
            beaten = False
            for t2, c2, _bb2, _s2 in lines:
                fl2 = t2.replace(" ", "")
                if "击败" not in fl2 or "可得" in fl2:
                    continue
                # 2026-11-18 实机量坐标：状态行在名字上方约 29px、战力上方约 54px
                # （已击败 (193,802) / 名字 (194,831) / 战力 (189,858)）。旧窗口
                # (-90..20) 把 -56 挡在外面 → 打过的对手仍算「未击败」，会重复打。
                # 2026-11-20 用真帧 tests/fixtures/grank_list_zero.png 复核：
                # 状态行在战力行**上方** 56px（已击败 (193,802) / 战力 (189,858)），
                # 旧窗口写成 -80..-25（战力在状态上方）→ 一次都没命中，
                # 于是「已击败」的对手仍被当成可打目标，会重复打同一个。
                if abs(c2[0] - px) <= 90 and 25 <= abs(py - c2[1]) <= 90:
                    beaten = True
                    break
            out.append((self._power(m.group(1), m.group(2)), px, py, beaten))
        return out

    def _attack(self, ui, cell, idx: int) -> str | None:
        """一场：点格子 →「敌阵信息」挑战 → 布阵（一键上阵 + 战斗）→ 跳过 → 结算确定。

        2026-11-18 12:20 实机链路（logs/_probe_grank4~8.py）：
          (513,1033) → 弹层（敌阵信息…挑战次数：3/3）→ 金「挑战」(358,916)
          → 布阵页（绿一键上阵 (294,1228)）→ 金「战斗」(519,1228)
          → 战斗 2~4s（点跳过）→「MVP 败方 失败」+ 金「确定」(363,1136)。
        旧码只按了一次 (358,916) 就以为进了布阵页：那一下其实是弹层里的「挑战」，
        进布阵页后没人按「战斗」，battle_finish 宽限期一过就返回 → 记 0 场。
        """
        px, py = cell
        ui.press((px, py - 22), 250, label=f"grank_cell{idx}", expect="none")
        ui.wait(2.6)
        im = ui.screen(f"grank_info{idx}")
        if self._info_open(im):
            # 弹层里的按钮会随对手状态改文案：未击败=金「挑战」、已击败=金「扫荡奖励」、
            # 次数用尽=「点击空白处关闭」。按 OCR 出来的文字点，绝不按坐标点。
            go = None
            sweep = None
            for t, c, _bb, _s in textocr.read_lines(im, L.GUILD_RANK_POPUP_BTN,
                                                   min_score=0.5):
                flat = t.replace(" ", "")
                if any(k in flat for k in L.GUILD_RANK_POPUP_GO_KEYS) and "扫荡" not in flat:
                    go = (int(c[0]), int(c[1]))
                elif any(k in flat for k in L.GUILD_RANK_POPUP_SWEEP_KEYS):
                    sweep = (int(c[0]), int(c[1]))
            if go is None:
                if sweep is not None:
                    log.info("  公会排位赛：这个对手已经打过了（弹层里是「扫荡奖励/"
                             "点击空白处关闭」，扫荡要花一次挑战次数），关掉弹层换下一个")
                else:
                    log.info("  公会排位赛：弹层里没读到「挑战」字样，关掉弹层换下一个")
                ui.press(sweep or L.BLANK, 200, label="grank_info_close", expect="none")
                ui.wait(1.2)
                if self._info_open(ui.screen(f"grank_info_x{idx}")):
                    ui.press(L.BLANK, 180, label="grank_info_close2", expect="none")
                    ui.wait(1.0)
                return None
            ui.press(go, 240, label="grank_info_do", expect="none")
        elif not (vision.is_green(im, *L.DEPLOY, r=18)
                  or vision.classify(im) == State.DEPLOY):
            log.info(f"  公会排位赛：点对手 (x={px}) 后既没弹「敌阵信息」也没进布阵页，跳过")
            return None
        # 战斗也可能被游戏直接以自动战斗开打（不进布阵页），所以布阵页/战斗态都算「进去了」
        for _ in range(8):
            ui.wait(1.6)
            im = ui.screen(f"grank_lineup{idx}")
            st = vision.classify(im)
            if (vision.is_green(im, *L.DEPLOY, r=18) or st == State.DEPLOY
                    or st == State.BATTLE or _T.VI.find(im, "跳过.png",
                                                        L.BATTLE_SKIP_THRESHOLD,
                                                        roi=L.BATTLE_SKIP_ROI)):
                break
        else:
            log.info("  公会排位赛：按下「挑战」后等了 ~13s 既没进布阵页也没开战，跳过这个对手")
            return None
        st = vision.classify(im)
        if vision.is_green(im, *L.DEPLOY, r=18):
            ui.press(L.DEPLOY, 220, label="grank_deploy", expect="none")
            ui.wait(2.2)
            im = ui.screen(f"grank_lineup2{idx}")
        if not (st == State.BATTLE or _T.VI.find(im, "跳过.png",
                                                  L.BATTLE_SKIP_THRESHOLD,
                                                  roi=L.BATTLE_SKIP_ROI)):
            # 2026-11-20 审计 C5：找不到金带时旧码回落 L.FIGHT 盲点。现在拿不到就收手。
            pt = vision.gold_band_center(im, L.GUILD_RANK_FIGHT_ZONE)
            if pt is None:
                log.info(f"  公会排位赛：第 {idx} 场找不到金色的「战斗」按钮，这一场不打")
                ui.press(L.BACK, 220, label=f"grank_back_nobtn{idx}", expect="none")
                ui.wait(1.4)
                return None
            ui.press(pt, 240, label=f"grank_fight{idx}", expect="none")
        ui.battle_finish(label="grank_finish", timeout=45.0)
        if not getattr(ui, "battle_started", True):
            # 2026-11-19 审计 B2：45s 内没见过战斗画面 = 这场没打起来，别按已打一场计。
            log.info(f"  公会排位赛：第 {idx} 场没进战斗画面（次数不足/加载慢），按「没打成」处理")
            ui.press(L.BACK, 220, label="grank_back_nofight", expect="none")
            ui.wait(1.6)
            return None
        res = None
        ok = None
        for _ in range(8):
            im = ui.screen(f"grank_after{idx}")
            res = self._result_of(im)
            ok = vision.gold_band_point(im, L.GUILD_RANK_OK_ZONE)
            if res or ok:
                break
            ui.wait(1.6)
        if ok:
            ui.press(ok, 220, label="grank_ok", expect="none")
            ui.wait(1.8)
        if res is None:
            res = self._result_of(ui.screen(f"grank_after2{idx}"))
        return res or "unknown"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        max_fights = int((self.p or {}).get("max_fights", 3) or 0)
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        ui.press(L.TAB_GUILD, 250, label="grank_guild", expect="none")
        ui.wait(3.0)
        im = ui.screen("grank_guild")
        entry = None
        try:
            for t, c, _bb, _s in textocr.read_lines(im, (0, 100, 720, 1280), min_score=0.4):
                if "排位" in t:
                    entry = c
                    break
        except Exception:
            entry = None
        if not entry:
            log.warn("  公会排位赛：公会页找不到「公会排位赛」入口，跳过")
            MainCity(ui).ensure()
            return TaskResult.fail("进不去公会排位赛")
        ui.press(entry, 250, label="grank_entry", expect="none")
        ui.wait(3.2)
        im = ui.screen("grank_page")
        # 2026-11-18 第 51 轮实测：整轮跑到排位赛这一步时（13:25）页面还在加载，
        # 3.2s 那一帧 OCR 什么都没读到 → 报「读不到挑战次数」。这里给页面 4 次机会，
        # 每次都重抓一帧再看；真读不到才判跳过。
        for _wait in range(4):
            if self._closed(im) or self._attempts(im) is not None:
                break
            ui.wait(1.6)
            im = ui.screen(f"grank_page{_wait + 2}")
        if self._closed(im):
            # 2026-11-18 03:17 实测：排位赛 12:00-20:00 才开，凌晨进页只写
            # 「排位赛即将开启 / 今天（12:00-20:00） / 准备好迎接敌军吧 / 对战列表」，
            # 没有「挑战次数」那一行。旧码报「读不到挑战次数」，像是判据坏了。
            # 2026-11-19 12:02（周四）实测另一版：非开放日写
            # 「排位赛尚未开启 / 每周：一、三、五（12:00-20:00）」——今天根本不是开放日，
            # 12:00 到了也不会开，得如实说清楚，别让人以为脚本错过时间。
            week_only = False
            try:
                flat = textocr.read_text(im, L.GUILD_RANK_CLOSED_BOX).replace(" ", "")
                week_only = any(k in flat for k in L.GUILD_RANK_WEEKDAY_KEYS)
            except Exception:     # noqa: BLE001
                week_only = False
            MainCity(ui).ensure()
            if week_only:
                log.info("  公会排位赛：今天不是开放日（页面写「每周：一、三、五 12:00-20:00」），不占时间")
                return TaskResult(True, "跳过：公会排位赛不是开放日（每周一、三、五 12:00-20:00）",
                                  {"fights": 0, "noop_ok": True})
            log.info("  公会排位赛：今天还没到开放时间（页面写「排位赛即将开启」），不占时间")
            return TaskResult(True, "跳过：公会排位赛未开启（今天 12:00-20:00）",
                              {"fights": 0, "noop_ok": True})
        att = self._attempts(im)
        if att is None:
            # 兜底：只在顶部那条带里找「挑战次数」后面的 N/M（宽框避免边角被切）
            try:
                flat = re.sub(r"\s+", "", textocr.read_text(im, (0, 100, 720, 260)) or "")
                m = ATTEMPT_RE.search(flat)
                if m:
                    att = (int(m.group(1)), int(m.group(2)))
            except Exception:   # noqa: BLE001
                pass
        if att is None:
            log.info("  公会排位赛：读不到挑战次数，不敢打")
            MainCity(ui).ensure()
            return TaskResult(True, "跳过：公会排位赛读不到挑战次数", {"fights": 0, "noop_ok": True})
        left = min(att[0], att[1])
        log.info(f"  公会排位赛：挑战次数 {left}/{att[1]}")
        if left <= 0:
            MainCity(ui).ensure()
            return TaskResult(True, f"跳过：公会排位赛今天 {att[0]}/{att[1]} 次已经用完",
                              {"fights": 0, "noop_ok": True})
        wins = loses = unknowns = 0
        for i in range(min(left, max(0, max_fights))):
            # 2026-11-18：战斗刚结束那一帧常是过场/结算残影，直接扫会拿到空表
            # （f50 09:46 就是这样记成「没有未击败目标」、0 场跳过）。现在重扫几帧。
            ops = []
            for _try in range(3):
                frame = ui.screen(f"grank_scan{i}_{_try}")
                if self._info_open(frame):
                    # 2026-11-20 真帧实测（tests/fixtures/grank_popup_fresh.png）：
                    # 「敌阵信息」弹层还压着时，弹层里那个对手会被读成「列表里唯一一颗」，
                    # 于是「挑最低战力」直接挑到弹层里那个人——先关层再扫。
                    log.info("  公会排位赛：上一场的「敌阵信息」弹层还开着，先关掉再扫列表")
                    ui.press(L.BLANK, 200, label=f"grank_scan_close{i}_{_try}", expect="none")
                    ui.wait(1.2)
                    frame = ui.screen(f"grank_scan{i}_{_try}b")
                ops = self._opponents(frame)
                if ops:
                    break
                ui.wait(1.4)
            cand = [o for o in ops if not o[3]]
            if not cand:
                rest = min(left, max(0, max_fights)) - i
                if not ops:
                    if i == 0:
                        log.info("  公会排位赛：对手列表读不出来（页面可能没画完），收手")
                    else:
                        log.info("  公会排位赛：打完这一场后读不到对手列表，收手")
                    break
                if i == 0 or rest <= 0:
                    log.info("  公会排位赛：对手列表里没有「未击败」的目标，收手")
                    break
                # 2026-11-20 审计 MAJOR：旧码这里退化成 list(ops)（含已击败的），
                # 会白耗挑战次数打一个打过的对手。扫不到标签就收手，不猜。
                log.info(f"  公会排位赛：扫不到「未击败」标签（还剩 {rest} 次机会），不猜着打，收手")
                break
            cand.sort()
            power, px, py, _b = cand[0]
            log.info(f"  公会排位赛：第 {i + 1} 场挑战力最低的未击败对手（{power / 1e8:.2f}亿，x={px}, y={py}）")
            res = self._attack(ui, (px, py), i + 1)
            if res == "win":
                wins += 1
            elif res == "lose":
                loses += 1
            elif res == "unknown":
                # 2026-11-19 假成功审计（audit2 TOP5）：以前把「打了但读不到横幅」也算进
                # fights —— 玩家看到的「打 N 场」里含未知场次，账对不上。现在单列。
                unknowns += 1
                log.info("  公会排位赛：这一场没读到胜负横幅（结算页形态变了），单列不计入场次")
            if res is None:
                break
        ui.press(L.BACK, 220, label="grank_back", expect="none")
        ui.wait(1.6)
        MainCity(ui).ensure()
        total = wins + loses

        if total <= 0 and not unknowns:
            return TaskResult(True, "跳过：公会排位赛这次没打成（次数为 0 或没有可打对手）",
                              {"fights": 0, "noop_ok": True})
        msg = f"公会排位赛：打 {total} 场（胜 {wins} 负 {loses}"
        if unknowns:
            msg += f"，另有 {unknowns} 场没收到的结算横幅（不计入场次）"
        return TaskResult(True, msg + "）",
                          {"fights": total, "wins": wins, "loses": loses,
                           "unconfirmed": unknowns})