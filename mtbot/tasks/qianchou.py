# -*- coding: utf-8 -*-
"""千抽福利（新手千抽活动）+ 自动选择部落英雄。

背景（用户 m20058/m20201 第 5 项）：「千抽福利自动选择部落英雄」。
2026-11-18 实机取证结论：**它是一个会轮换的活动横幅**，不是常驻页面 ——
`mtbot/tasks/reward.py` 里记着旧坐标 `ICON_HERO_PLAN=(280,290)` 曾经点到「千抽福利」，
而 2026-11-18 同一点位的实际内容是「赛前竞猜」，说明活动位换了。
所以本任务不写死坐标，而是：
1) 逐个试主城顶部活动位候选槽，OCR 认出页面里出现「千抽」才算找到；
2) 找到后只做**免费**动作：页面写「免费」的召唤/领取按钮才点，部落英雄选择器按
   「部落」字样定位；任何「充值/首充/购买/立即购买」字样出现就立刻退出；
3) 找不到就如实跳过（`今天主城没有「千抽福利」入口`），不盲点、不花钻。
"""
from .. import log, textocr, vision
from ..pages import MainCity
from .base import BaseTask, TaskResult

# 主城顶部活动位（会轮换，只用来「找」，不假设内容）
CITY_SLOTS = ((280, 290), (360, 200), (200, 290), (470, 290), (524, 175), (175, 189))
QIANCHOU_KEYS = ("千抽",)
# 出现这些字样就立刻退：付费/充值页面不是我们要的
PAY_KEYS = ("充值", "首充", "立即购买", "确认购买", "前往购买", "解锁高级")
FREE_KEYS = ("免费",)
PICK_MARK_KEYS = ("已选择", "已选", "当前英雄", "已锁定")
HORDE_KEYS = ("部落",)


def _page_text(im) -> str:
    try:
        return textocr.read_text(im, (0, 60, 720, 1250)).replace(" ", "")
    except Exception:  # noqa: BLE001 - OCR 不可用时按「没找到」处理
        return ""


class QianchouTask(BaseTask):
    """千抽福利：找入口 → 做免费抽 → 选部落英雄。"""

    name = "qianchou"
    title = "千抽福利（免费抽 + 自动选部落英雄）"
    category = "reward"

    def _find(self):
        ui = self.ui
        for pos in CITY_SLOTS:
            MainCity(ui).ensure()
            ui.press(pos, 250, expect="none")
            ui.wait(2.4)
            im = ui.screen(f"qc_slot_{pos[0]}_{pos[1]}")
            txt = _page_text(im)
            if any(k in txt for k in QIANCHOU_KEYS):
                log.info(f"  千抽福利：在 {pos} 找到了活动页")
                return im, pos, txt
            if any(k in txt for k in PAY_KEYS):
                log.info(f"  千抽福利：{pos} 是付费活动页（含充值/购买字样），退出")
            MainCity(ui).ensure()
        return None, None, ""

    def _pick_horde(self, im) -> int:
        """在活动页里找「部落」相关的英雄选择器，选中它。"""
        ui = self.ui
        picks = 0
        for t, c, _b, _s in textocr.read_lines(im, (0, 100, 720, 1200), min_score=0.4):
            if any(k in t for k in HORDE_KEYS):
                log.info(f"  千抽福利：点「部落」选项 {c}")
                ui.press(c, 240, expect="none")
                ui.wait(1.8)
                # 2026-11-19 假成功审计（audit2 TOP4）：点完必须看到选中态才算选到
                after = ui.screen("qc_pick_chk")
                at = _page_text(after)
                # 2026-11-20 审计 MAJOR：旧码还接受「这片区域像素不一样」当选中证据，
                # 任何动画/按钮高亮都能满足 → 假选中。只认 OCR 到的选中标记。
                marked = any(k in at for k in PICK_MARK_KEYS)
                if marked:
                    picks += 1
                else:
                    log.info("  千抽福利：点了「部落」后画面没有选中标记变化，不计数（可能只是文字标签）")
                break
        return picks

    def _free_draw(self, im) -> int:
        """只点页面明确写「免费」的金色按钮。"""
        ui = self.ui
        txt = _page_text(im)
        if not any(k in txt for k in FREE_KEYS):
            log.info("  千抽福利：页面没有「免费」字样，今天不抽（不花钻石）")
            return 0
        for band in vision.gold_button_bands(im, (0, 700, 720, 1250)):
            x, y = int(band[0]), int(band[1])
            label = ""
            for t, c, _b, _s in textocr.read_lines(im, (x - 120, y - 40, x + 120, y + 40), min_score=0.4):
                label += t
            if any(k in label for k in FREE_KEYS):
                log.info(f"  千抽福利：点免费按钮 ({x},{y})「{label}」")
                ui.press((x, y), 250, label="qc_free_draw", expect="none")
                ui.wait(2.6)
                after = ui.screen("qc_draw_chk")
                if vision.item_popup(after) or vision.modal_dim(after):
                    log.info("  千抽福利：免费抽出现结果/奖励浮层，记 1 次")
                    return 1
                # 2026-11-19 假成功审计（audit2 TOP4）：没浮层也要有「免费标签消失」这类变化
                if not any(k in _page_text(after) for k in FREE_KEYS):
                    log.info("  千抽福利：抽完页面「免费」字样消失，记 1 次")
                    return 1
                log.info("  千抽福利：点了免费按钮但画面没有结果浮层/免费标签变化，不计数")
                return 0
        log.info("  千抽福利：没找到写着「免费」的金色按钮，不抽")
        return 0

    def run(self, ctx):
        self.ui = ctx.ui
        ui = self.ui
        ui.ensure_main_city()
        im, pos, txt = self._find()
        if im is None:
            return TaskResult.skip("今天主城没有「千抽福利」入口（活动位轮换，没写死坐标避免点错）",
                                   {"found": False, "noop_ok": True})
        picks = self._pick_horde(im)
        draws = 0
        if picks:
            im = ui.screen("qc_after_pick")
        draws = self._free_draw(im)
        MainCity(ui).ensure()
        return TaskResult(True, f"千抽福利：部落选择 {picks} 次，免费抽 {draws} 次",
                          {"found": True, "picks": picks, "draws": draws, "noop_ok": True})
