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
from .. import log, textocr
from ..pages import MainCity
from .base import BaseTask, TaskContext, TaskResult

HEROES = (
    ("小黑", L.TAVERN_XIAOHEI_GO, L.TAVERN_XIAOHEI_LEFT_BOX, L.TAVERN_XIAOHEI_SHARD_BOX),
    ("剁椒牛头", L.TAVERN_DUOJIAO_GO, L.TAVERN_DUOJIAO_LEFT_BOX, L.TAVERN_DUOJIAO_SHARD_BOX),
)

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
        try:
            m = self._parse(textocr.read_text(im, box) or "")
        except Exception:
            m = None
        if m:
            return m
        try:
            lines = textocr.read_lines(im, box, min_score=0.30)
        except Exception:
            return None
        for txt, _c, _bb, _s in lines:
            m = self._parse(txt)
            if m:
                return m
        return None

    def _left(self, im, box) -> int | None:
        m = self._read(im, box)
        return int(m.group(1)) if m else None

    def _shard(self, im, box) -> int | None:
        m = self._read(im, box)
        return int(m.group(1)) if m else None

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

    def _drink(self, ui, go, tag) -> None:
        ui.press(go, 240, label=f"tavern_drink_{tag}", expect="none")
        ui.wait(2.2)
        ui.press(L.BLANK, 160, label="tavern_pop_close", expect="none")
        ui.wait(1.2)

    def _left_retry(self, ui, box, tries: int = 3) -> int | None:
        """买完次数/关弹窗后，画面可能还在动画里，多抓几帧直到读出来。"""
        for i in range(max(1, tries)):
            val = self._left(ui.screen(f"tavern_left_{i + 1}"), box)
            if val is not None:
                return val
            ui.press(L.BLANK, 150, label="tavern_left_blank", expect="none")
            ui.wait(1.1)
        return None

    def _buy_and_drink(self, ui, ctx, go, left_box, buy_left: int) -> tuple[int, int]:
        """返回 (请客次数, 花掉的钻石名义值)。只有证据齐全才真买。"""
        got, spent = 0, 0
        for i in range(max(0, buy_left)):
            ui.press(go, 240, label=f"tavern_buy_probe_{i + 1}", expect="none")
            ui.wait(2.6)
            im = ui.screen(f"tavern_buy_dlg_{i + 1}")
            cost = self._dialog_cost(im)
            if cost is None:
                log.info("  英雄酒馆：点请客后没弹出购买弹窗（今天也许还能请），不再买次数")
                ui.press(L.BLANK, 150, expect="none")
                break
            if not self.may_spend(ctx, "英雄酒馆·请客次数", cost, kind="attempt"):
                ui.press(L.TAVERN_BUY_CANCEL, 200, label="tavern_buy_cancel", expect="none")
                ui.wait(1.2)
                log.info(f"  英雄酒馆：不买请客次数（弹窗写花费 {cost}）")
                break
            ui.press(L.TAVERN_BUY_OK, 220, label="tavern_buy_ok", expect="none")
            ui.wait(2.4)
            ui.press(L.BLANK, 160, label="tavern_buy_pop", expect="none")
            ui.wait(1.2)
            after_left = self._left_retry(ui, left_box)
            if after_left is not None and after_left > 0:
                log.info(f"  英雄酒馆：买到 1 次请客次数（弹窗写花费 {cost}，可请 {after_left}）")
                spent += cost
                self._drink(ui, go, f"bought{i + 1}")
                got += 1
            else:
                log.info(f"  英雄酒馆：点了购买但可请次数没增加（{after_left}），不再买")
                break
        return got, spent

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

        total, spent_all, report = 0, 0, []
        for name, go, left_box, shard_box in HEROES:
            before = self._shard(im, shard_box)
            m = self._read(im, left_box)
            if not m:
                log.info(f"  英雄酒馆·{name}：读不到「今日可请」次数，不敢点")
                report.append(f"{name} 跳过")
                continue
            # 「今日可请：N/2」= 已请 N 次（上限 2）→ 还能请 limit - N 次
            used, limit = int(m.group(1)), int(m.group(2))
            avail = max(0, limit - used)
            log.info(f"  英雄酒馆·{name}：今日已请 {used}/{limit}，还能请 {avail} 次")
            got = 0
            for i in range(min(avail, 4)):
                self._drink(ui, go, f"{name}{i + 1}")
                got += 1
            if name == "剁椒牛头" and buy_left > 0:
                extra, spent = self._buy_and_drink(ui, ctx, go, left_box, buy_left)
                got += extra
                spent_all += spent
            im = ui.screen("tavern_after")
            after_m = self._read(im, left_box)
            after_txt = f"{after_m.group(1)}/{after_m.group(2)}" if after_m else "读不到"
            after = self._shard(im, shard_box)
            log.info(f"  英雄酒馆·{name}：请客 {got} 次（今日已请 {used}/{limit} → {after_txt}，碎片 {before} → {after}）")
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
                log.warn(f"  英雄酒馆：买次数名义 {spent_all} 钻，主城钻石 {d0}→{d1} 对不上，请核对")
        stats = {"drinks": total, "diamonds_before": d0, "diamonds_after": d1,
                 "diamonds_spent_nominal": spent_all}
        if total <= 0:
            return TaskResult(True, "跳过：英雄酒馆今天没有可请客次数（或碎片未变）",
                              {**stats, "noop_ok": True})
        tail = f"，买次数花钻 {spent_all}" if spent_all else ""
        return TaskResult(True, f"英雄酒馆：请客 {total} 次（{'，'.join(report)}）{tail}", stats)