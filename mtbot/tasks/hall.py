"""荣耀殿堂：每日点赞领奖。

2026-11-10 真机取证（`logs/probe_like.txt` / `logs/like2_pop1.png`）：
在荣耀殿堂页点底部「点赞」(361,1254)，会弹出浮层：
「传奇启幕，勇者无… / 获得奖励 / 20 / 钻石 / 点击空白处关闭」
—— 即每日点赞一次可领 20 钻石；点过之后底部文字变成「已点赞」，
再点不会弹任何东西。这是「全部完整的领取物品」里漏掉的一项。

绝不碰：万神天阶荣耀商店(582/629,1253) 、元素神殿 / 上古神域页签。
"""
from __future__ import annotations

import time

from .. import layout as L
from .. import log, textocr, vision
from ..pages import MainCity
from .base import BaseTask, TaskContext, TaskResult


class HallLikeTask(BaseTask):
    name = "hall"
    title = "荣耀殿堂（每日点赞领奖）"
    category = "reward"

    @staticmethod
    def _bottom(im) -> str:
        if not textocr.available():
            return ""
        try:
            return textocr.read_text(im, L.HALL_BOTTOM_BOX) or ""
        except Exception:  # noqa: BLE001
            return ""

    def _at_page(self, im) -> bool:
        if not textocr.available():
            return True
        try:
            head = textocr.read_text(im, L.HALL_PAGE_BOX) or ""
        except Exception:  # noqa: BLE001
            return True
        return any(k in head for k in L.HALL_PAGE_KEYS)

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        ui.press(L.HALL_ENTRY, 250, label="hall_entry", expect="none")
        ui.wait(2.6)
        im = ui.screen("hall_open")
        if not self._at_page(im):
            log.info("  荣耀殿堂：(382,532) 没进去（页面读不到殿堂标题），退回不动")
            ui.press(L.BACK, 250, label="hall_back", expect="none")
            ui.wait(1.2)
            MainCity(ui).ensure()
            return TaskResult.skip("荣耀殿堂没进去")

        bottom = self._bottom(im)
        if "已点赞" in bottom:
            ui.press(L.BACK, 250, label="hall_back", expect="none")
            ui.wait(1.2)
            MainCity(ui).ensure()
            return TaskResult(True, "荣耀殿堂：今天已点赞（奖励已领）",
                              {"liked": False, "noop_ok": True})

        ui.press(L.HALL_LIKE, 250, label="hall_like", expect="none")
        ui.wait(2.4)
        pop = ui.screen("hall_pop")
        gained = False
        if textocr.available():
            try:
                txt = textocr.read_text(pop, L.HALL_POP_BOX) or ""
            except Exception:  # noqa: BLE001
                txt = ""
            gained = ("获得奖励" in txt) or ("点击空白处关闭" in txt)
            if gained:
                ui.press(L.HALL_POP_CLOSE, 200, label="hall_pop_close", expect="none")
                ui.wait(1.6)
        after = self._bottom(ui.screen("hall_after"))
        liked = "已点赞" in after
        ui.press(L.BACK, 250, label="hall_back", expect="none")
        ui.wait(1.2)
        MainCity(ui).ensure()
        if liked:
            return TaskResult(True, "荣耀殿堂：点赞完成（奖励已领）",
                              {"liked": True, "popup": gained})
        log.info("  荣耀殿堂：点了「点赞」但底部还没变成「已点赞」（可能没点中），不计账")
        return TaskResult(True, "荣耀殿堂：点赞未确认", {"liked": False, "noop_ok": True})
