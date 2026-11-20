"""英雄酒馆（请客拿碎片：小黑 + 剁椒牛头；可花钻买请客次数）。

真机结构（logs/_probe_tavern2.txt / _probe_tavern_buy2.txt，2026-11-11）：
- 战役页 `英雄酒馆 (635,598)` → 页内两行四格英雄，每格 `X/50` + `今日可请：N/2` + 金钮「请客」。
  小黑 请客 (579,509)、可请框 (500,448,690,500)
  剁椒牛头 请客 (579,696)、可请框 (500,636,690,692)
- 配额为 0 时点「请客」会弹**标准购买弹窗**：
  `是否花费 N（拥有 1568) 购买1次请客次数？` + `今日可购买次数（1/1）`
  `取消 (234,828)` / `购买 (493,828)`（金色，金带 (483,826)）
- 底部 (408,1052) 不是买次数，是「信物产出」信息面板（点开只读说明），本任务不碰。

安全边界：买了次数只用于「剁椒牛头」；买之前必须读到弹窗金额、通过 may_spend(kind="attempt")，
并用主城钻石前后差 + 可请次数增加双重自证；任何一环缺证就不买。
"""
from __future__ import annotations

import re

from .. import layout as L
from .. import log, textocr, vision
from ..pages import MainCity
from .base import BaseTask, TaskContext, TaskResult

HERO_NAMES = ("小黑", "剁椒牛头")


def _cards(im):
    """按画面文字找两位英雄的卡片位置，返回 [(名字, 请客按钮, 今日可请框, 碎片框)]。

    2026-11-20：卡片行高会随版本变（新版比 layout 里的常量整体下移 ~370px），
    写死坐标只会「天天读不到次数 → 天天跳过」。这里用 OCR 出来的
    「名字 / 今日可请：N/2 / 请客」三行互配对，行高变了也不会失手：
      名字 → 同名右侧 +134 x、+113 y 附近是「请客」，+77 y 是「今日可请」。
    配不上任何一行的英雄直接不出现在结果里（调用方如实跳过）。
    """
    try:
        lines = textocr.read_lines(im, (0, 120, 720, 1250), min_score=0.45)
    except Exception:      # noqa: BLE001 - OCR 不可用就当认不出
        return []
    acts, lefts = [], []
    for t, c, _bb, _s in lines:
        flat = t.replace(" ", "")
        if flat.startswith("请客"):
            acts.append(c)
        elif flat.startswith("今日可请"):
            lefts.append(c)
    out = []
    for t, c, _bb, _s in lines:
        flat = t.replace(" ", "")
        name = next((n for n in HERO_NAMES if flat == n or flat.startswith(n)), None)
        if not name:
            continue
        nx, ny = c
        # 同一行左右两列都有「请客」「今日可请」，所以按**横向最近**配，
        # 不能只按纵向距离（两列 dy 一样，会把左边那颗的次数读到右边英雄身上）。
        go = None
        best = 999.0
        for ax, ay in acts:
            if abs(ax - nx) <= 165 and 55 <= ay - ny <= 150 and abs(ax - nx) < best:
                go, best = (ax, ay), abs(ax - nx)
        lt = None
        best = 999.0
        for lx, ly in lefts:
            if abs(lx - nx) <= 160 and 45 <= ly - ny <= 115 and abs(lx - nx) < best:
                lt, best = (lx, ly), abs(lx - nx)
        if lt is None:
            continue          # 连「今日可请：N/2」都读不到 → 这颗不动手
        if go is None:
            # 第二行（剁椒牛头）的「请客」有时读不出来（压在底栏附近），
            # 用「今日可请」那行的固定偏移顶上：同排实测 小黑 (580,845)→(578,882)、
            # 巫毒之影 (263,845)→(261,881)，横 -2 / 纵 +37 稳定。
            go = (lt[0] - 2, lt[1] + 37)
        out.append((name, go,
                    (max(0, lt[0] - 120), lt[1] - 20, min(720, lt[0] + 120), lt[1] + 20),
                    # 碎片那行的斜杠在窄框里会被 OCR 吞掉（实测 '45' '50' 两个 token），
                    # 放宽到能读到 '45/50' 的高度（真帧 小黒 (586,813)）。
                    (max(0, nx + 60), ny + 14, min(720, nx + 250), ny + 72)))
    return out

PAIR_RE = re.compile(r"(\d+)/(\d+)")
COST_RE = re.compile(r"花费(\d+)")


class TavernTask(BaseTask):
    name = "tavern"
    title = "英雄酒馆（请客拿小黑/剁椒牛头碎片，可花钻买次数）"
    category = "reward"

    @staticmethod
    def _parse(txt: str):
        s = re.sub(r"\s+", "", txt or "").replace("\uff0f", "/")
        return PAIR_RE.search(s)

    def _read(self, im, box):
        """从框里读「A/B」，返回 (A, B) 或 None。

        2026-11-20 真帧：OCR 会把「今日可请：1/2」拆成 '今日' / '可请：1' / '1' / '1/2'，
        拼成一整行后正则会把 '111/2' 当成分母 —— 所以优先按 token 找 `A/B`，
        并要求 A ≤ B（请客次数、碎片数都满足），多个候选取最后一个（画面里最靠右/下）。
        """
        cand = None
        try:
            lines = textocr.read_lines(im, box, min_score=0.25)
        except Exception:      # noqa: BLE001 - OCR 不可用就当读不到
            lines = []
        for tok, _c, _bb, _s in lines:
            m = self._parse(tok)
            if not m:
                continue
            a, b = int(m.group(1)), int(m.group(2))
            if 0 <= a <= b:
                cand = (a, b)
        if cand is not None:
            return cand
        try:
            m = self._parse(textocr.read_text(im, box) or "")
        except Exception:      # noqa: BLE001
            return None
        if m and 0 <= int(m.group(1)) <= int(m.group(2)):
            return int(m.group(1)), int(m.group(2))
        return None

    def _avail(self, ui, box, tries: int = 3) -> int | None:
        """卡片上的「今日可请：A/2」——A 就是**还能请几次**（真帧 2026-11-20：
        小黑 2/2 时按钮是金色可点、巫毒之影 0/2 时按钮是灰的）。读不到返回 None。"""
        for i in range(max(1, tries)):
            v = self._read(ui.screen(f"tavern_avail_{i + 1}"), box)
            if v:
                return max(0, v[0])
            ui.press(L.TAVERN_POP_BLANK, 150, label="tavern_avail_blank", expect="none")
            ui.wait(1.1)
        return None

    def _pool(self, im) -> int | None:
        """顶部「请客次数：A/2」→ A（全酒馆共用的请客次数）。"""
        try:
            txt = textocr.read_text(im, L.TAVERN_POOL_BOX)
        except Exception:      # noqa: BLE001
            return None
        m = re.search(r"(\d)\s*/\s*(\d)", txt)
        return int(m.group(1)) if m else None

    def _buy_pool(self, ui, ctx: TaskContext, buy_left: int):
        """点顶部金色「+」花钻买请客次数。只认弹窗写的金额 + 次数真的变多。"""
        got, spent = 0, 0
        for i in range(max(0, buy_left)):
            pool = self._pool(ui.screen(f"tavern_pool_pre{i + 1}"))
            if pool is not None and pool > 0:
                break
            ui.press(L.TAVERN_POOL_PLUS, 240, label=f"tavern_pool_plus{i + 1}", expect="none")
            ui.wait(2.2)
            im = ui.screen(f"tavern_pool_dlg{i + 1}")
            cost = self._dialog_cost(im)
            if cost is None:
                log.info("  英雄酒馆：点「+」没弹出购买弹窗，不再买请客次数")
                ui.press(L.TAVERN_POP_BLANK, 150, expect="none")
                break
            if not self.may_spend(ctx, "英雄酒馆·请客次数", cost, kind="attempt"):
                ui.press(L.TAVERN_BUY_CANCEL, 200, label="tavern_pool_cancel", expect="none")
                ui.wait(1.2)
                log.info(f"  英雄酒馆：不买请客次数（弹窗写花费 {cost}）")
                break
            ui.press(L.TAVERN_BUY_OK, 220, label="tavern_pool_ok", expect="none")
            ui.wait(2.4)
            after = self._pool(ui.screen(f"tavern_pool_post{i + 1}"))
            if after is None or (pool is not None and after <= pool):
                log.info(f"  英雄酒馆：点了购买但请客次数没变多（{pool} → {after}），不再买")
                ui.press(L.TAVERN_POP_BLANK, 160, expect="none")
                break
            spent += cost
            got += 1
            log.info(f"  英雄酒馆：买到 1 次请客次数（弹窗写花费 {cost}，现在 {after} 次）")
            ui.press(L.TAVERN_POP_BLANK, 160, label="tavern_pool_pop", expect="none")
            ui.wait(1.0)
        return got, spent

    def _shard(self, im, box) -> int | None:
        v = self._read(im, box)
        return v[0] if v else None

    def _at_page(self, im) -> bool:
        try:
            txt = textocr.read_text(im, L.TAVERN_PAGE_BOX) or ""
        except Exception:
            return False
        return "请客" in txt or "酒馆" in txt

    def _dialog_cost(self, im) -> int | None:
        try:
            txt = textocr.read_text(im, L.TAVERN_BUY_DLG_BOX) or ""
        except Exception:
            return None
        if "请客次数" not in txt and "购买" not in txt:
            return None
        m = COST_RE.search(re.sub(r"\s+", "", txt))
        return int(m.group(1)) if m else None

    def _drink(self, ui, go, tag) -> bool:
        """点一次「请客」，然后把奖励浮层关掉。返回是否真的弹出了奖励。"""
        ui.press(go, 240, label=f"tavern_drink_{tag}", expect="none")
        ui.wait(2.0)
        im = ui.screen(f"tavern_drink_after_{tag}")
        if not vision.modal_dim(im):
            log.info(f"  英雄酒馆：点「请客」后没出现奖励浮层（{tag}），不算请客")
            return False
        for k in range(2):
            ui.press(L.TAVERN_POP_BLANK, 160, label=f"tavern_pop_close_{tag}_{k + 1}",
                     expect="none")
            ui.wait(1.1)
            if not vision.modal_dim(ui.screen(f"tavern_pop_after_{tag}_{k + 1}")):
                return True
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        buy_left = int((self.p or {}).get("buy_attempts", 2) or 0)
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        d0 = self.diamonds_stable(ui, "tavern_d0") if buy_left else None
        ui.press(L.TAB_CAMPAIGN, 250, label="tavern_campaign", expect="none")
        ui.wait(2.4)
        ui.press(L.TAVERN_ENTRY, 250, label="tavern_entry", expect="none")
        ui.wait(3.0)
        im = ui.screen("tavern_page")
        if not self._at_page(im):
            log.warn("  英雄酒馆：点了战役页入口但没进酒馆（可能被横幅挡住），本次跳过")
            MainCity(ui).ensure()
            return TaskResult.fail("进不去英雄酒馆")

        total, spent_all, report, i_buy = 0, 0, [], 0
        dcheck_bad = False
        cards = _cards(im)
        if not cards:
            log.info("  英雄酒馆：认不出「小黑/剁椒牛头」的卡片（文字没读到），本次不动手")
        for name, go, left_box, shard_box in cards:
            before = self._shard(im, shard_box)
            v0 = self._read(im, left_box)
            if not v0:
                log.info(f"  英雄酒馆·{name}：读不到「今日可请」次数，不敢点")
                report.append(f"{name} 跳过")
                continue
            used, limit = v0[0], v0[1]
            avail = max(0, used)                    # 卡片上第一个数 = 还能请几次
            log.info(f"  英雄酒馆·{name}：今日可请 {used}/{limit}（还能请 {avail} 次）")
            if before is not None and before >= 50:
                log.info(f"  英雄酒馆·{name}：碎片已满 {before}/50，不再请客")
                report.append(f"{name} 已满")
                continue
            if avail <= 0:
                report.append(f"{name} 次数已用完")
                continue
            pool = self._pool(im)
            if pool is not None and pool <= 0 and buy_left and i_buy < buy_left:
                need = min(buy_left - i_buy, max(1, avail))
                bought, spent = self._buy_pool(ui, ctx, need)
                i_buy += bought
                spent_all += spent
                if bought <= 0:
                    log.info(f"  英雄酒馆·{name}：请客次数 0 又买不到（多半今天的购买额度用完了），"
                             f"这颗先不请")
                    report.append(f"{name} 无次数")
                    continue
                im = ui.screen(f"tavern_{name}_p0")
            for k in range(min(avail, 4)):
                self._drink(ui, go, f"{name}{k + 1}")
            im = ui.screen("tavern_after")
            after_m = self._read(im, left_box)
            after_txt = f"{after_m[0]}/{after_m[1]}" if after_m else "读不到"
            # 2026-11-19 假成功审计 C2：以前 got 是「按上限推算能请几次」，点没点成
            # 都照加。现在只认「今日已请 N」从 used 涨到 M 的差值；读不到就记 0。
            if after_m:
                # 「今日可请：A/2」的 A 是**还能请几次**：请客成功它必然变小
                grew = avail - after_m[0]
                got = grew if grew > 0 else 0
                if grew < 0:
                    log.info(f"  英雄酒馆·{name}：可请次数反而变多"
                             f"（{avail} → {after_m[0]}），按 0 记")
            else:
                log.info(f"  英雄酒馆·{name}：点完读不到「今日已请」次数，按 0 记（不虚报）")
                got = 0
            after = self._shard(im, shard_box)
            log.info(f"  英雄酒馆·{name}：请客 {got} 次（今日可请 {avail}/{limit} → {after_txt}，碎片 {before} → {after}）")
            total += got
            report.append(f"{name} +{got}")

        ui.press(L.BACK, 220, label="tavern_back", expect="none")
        ui.wait(1.6)
        MainCity(ui).ensure()
        d1 = self.diamonds_stable(ui, "tavern_d1") if buy_left else None
        if spent_all:
            if d0 is not None and d1 is not None and d0 - d1 == spent_all:
                log.info(f"  英雄酒馆：买请客次数花钻 {spent_all}（主城 {d0}→{d1}）")
            else:
                dcheck_bad = True
                log.warn(f"  英雄酒馆：买次数名义 {spent_all} 钻，主城钻石 {d0}→{d1} 对不上，请核对")
        stats = {"drinks": total, "diamonds_before": d0, "diamonds_after": d1,
                 "diamonds_spent_nominal": spent_all,
                 "diamonds_check": "mismatch" if dcheck_bad else "ok"}
        if total <= 0:
            why = "，".join(report) if report else "认不出卡片"
            return TaskResult(True, f"跳过：英雄酒馆今天没请到（{why}）",
                              {**stats, "noop_ok": True})
        tail = f"，买次数花钻 {spent_all}" if spent_all else ""
        return TaskResult(True, f"英雄酒馆：请客 {total} 次（{'，'.join(report)}）{tail}", stats)