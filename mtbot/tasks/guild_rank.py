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
from .. import log, textocr, vision
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
        try:
            txt = textocr.read_text(im, L.GUILD_RANK_ATTEMPT_BOX) or ""
        except Exception:
            return None
        m = ATTEMPT_RE.search(re.sub(r"\s+", "", txt))
        return (int(m.group(1)), int(m.group(2))) if m else None

    @staticmethod
    def _power(val: str, unit: str) -> float:
        try:
            v = float(val)
        except ValueError:
            return 0.0
        return v * (1e8 if unit == "亿" else 1e4)

    def _opponents(self, im):
        """返回 [(power, x, y, beaten)]，按格子中心的 y/x 定位。"""
        lines = textocr.read_lines(im, L.GUILD_RANK_GRID, min_score=0.4)
        out = []
        for t, c, bb, s in lines:
            m = POWER_RE.search(t.replace(" ", ""))
            if not m:
                continue
            px, py = c
            beaten = False
            for t2, c2, _bb2, _s2 in lines:
                if "已击败" in t2 and abs(c2[0] - px) <= 90 and -90 <= (py - c2[1]) <= 20:
                    beaten = True
                    break
            out.append((self._power(m.group(1), m.group(2)), px, py, beaten))
        return out

    def _attack(self, ui, cell, idx: int) -> str | None:
        px, py = cell
        ui.press((px, py - 22), 250, label=f"grank_cell{idx}", expect="none")
        ui.wait(2.6)
        im = ui.screen(f"grank_lineup{idx}")
        if not vision.is_green(im, *L.DEPLOY, r=18) and not vision.is_gold(im, *L.GUILD_RANK_GO, r=16):
            log.info(f"  公会排位赛：点对手 (px={px}) 后没进布阵页，跳过")
            return None
        if vision.is_green(im, *L.DEPLOY, r=18):
            ui.press(L.DEPLOY, 220, label="grank_deploy", expect="none")
            ui.wait(2.2)
        ui.press(L.GUILD_RANK_GO, 240, label="grank_go", expect="none")
        ui.wait(3.0)
        ui.battle_finish(label="grank_finish", timeout=25.0)
        after = ui.screen(f"grank_after{idx}")
        txt = ""
        try:
            txt = textocr.read_text(after, L.GUILD_RANK_RESULT_BOX) or ""
        except Exception:
            pass
        pos = ui._result_panel_ok(after) if hasattr(ui, "_result_panel_ok") else None
        if pos:
            ui.press(pos, 220, label="grank_ok", expect="none")
            ui.wait(1.6)
        if "胜" in txt:
            return "win"
        if "败" in txt or "失败" in txt:
            return "lose"
        return "unknown"

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
        att = self._attempts(im)
        if att is None:
            log.info("  公会排位赛：读不到挑战次数，不敢打")
            MainCity(ui).ensure()
            return TaskResult(True, "跳过：公会排位赛读不到挑战次数", {"fights": 0, "noop_ok": True})
        left = min(att[0], att[1])
        log.info(f"  公会排位赛：挑战次数 {left}/{att[1]}")
        wins = loses = 0
        for i in range(min(left, max(0, max_fights))):
            ops = self._opponents(ui.screen(f"grank_scan{i}"))
            cand = [o for o in ops if not o[3]]
            if not cand:
                rest = min(left, max(0, max_fights)) - i
                if i == 0 or rest <= 0 or not ops:
                    log.info("  公会排位赛：对手列表里没有「未击败」的目标，收手")
                    break
                log.info(
                    f"  公会排位赛：扫不到「未击败」标签但还剩 {rest} 次机会，"
                    f"退化为挑战力最低的那一格"
                )
                cand = list(ops)
            cand.sort()
            power, px, py, _b = cand[0]
            log.info(f"  公会排位赛：第 {i + 1} 场挑战力最低的未击败对手（{power / 1e8:.2f}亿，x={px}, y={py}）")
            res = self._attack(ui, (px, py), i + 1)
            if res == "win":
                wins += 1
            elif res == "lose":
                loses += 1
            if res is None:
                break
        ui.press(L.BACK, 220, label="grank_back", expect="none")
        ui.wait(1.6)
        MainCity(ui).ensure()
        total = wins + loses
        if total <= 0:
            return TaskResult(True, "跳过：公会排位赛这次没打成（次数为 0 或没有可打对手）",
                              {"fights": 0, "noop_ok": True})
        return TaskResult(True, f"公会排位赛：打 {total} 场（胜 {wins} 负 {loses}）",
                          {"fights": total, "wins": wins, "loses": loses})