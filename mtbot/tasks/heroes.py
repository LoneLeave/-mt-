"""英雄页里的两个养成页：图鉴升级、英雄羁绊（2026-10-31 按录像新增）。

录像里用户手动点过、脚本此前完全没做的两个系统：

- **图鉴**（英雄 → 图鉴）：底部三个分类（英雄/专武/神器），右下角书图标写着「N级」，
  点开「图鉴等级」面板；面板底部有金色「升级」（消耗图鉴积分，材料够才出现），
  点一次等级 +1（录像里 364→372，50 积分 / 每次 6 分，点了 8 次）。
- **英雄羁绊**（英雄 → 羁绊）：一行一个羁绊（如「死亡都要爱3级」），
  满足「羁绊内英雄均达到神话3星(2/2)」这类条件时右侧「升级」按钮右上角挂红「!」；
  没满足时按钮仍是金色，点了只弹「羁绊未达到升级条件」，所以只点带角标的。
"""
from __future__ import annotations

import re

from .. import layout as L
from .. import log, titles, vision
from ..pages import MainCity
from .base import BaseTask, TaskContext, TaskResult


def _close_idle_popup(ui) -> bool:
    """关掉「挂机特权」68 元购买面板（只关不买）。返回是否点过。

    2026-11-07：英雄页「羁绊」页签正下方会冒一个「可领取」红气泡，点到它会打开挂机特权
    付费面板（OCR：挂机特权 / 有效期：永久 / 68元 / 每日快速挂机购买数+5），面板底部写着
    「点击空白处关闭」(360,1220)。这里只点空白，绝不碰任何「购买/前往」按钮。
    """
    im = ui.screen("idle_popup_probe")
    text = ""
    try:
        from .. import textocr
        if textocr.available():
            text = textocr.read_text(im, (0, 180, 720, 700))
    except Exception:      # OCR 只是辅助判据，读不到就照点空白
        text = ""
    if "挂机特权" not in text and "点击空白处关闭" not in text:
        return False
    log.warn("  英雄页上弹出了「挂机特权」付费面板（点到了页签下方的「可领取」气泡），"
             "只关不买")
    for _ in range(2):
        ui.press(L.IDLE_REWARD_CLOSE, 160, label="idle_close", expect="none")
        ui.wait(0.9)
        if not vision.similar(im, ui.screen("idle_after")):
            return True
    return True


def _enter_hero_sub(ctx: TaskContext, pos, title_key: str) -> bool:
    """进英雄页并切到 图鉴 / 羁绊 子页签，用标题锚点确认。"""
    ui = ctx.ui
    if not MainCity(ui).ensure():
        return False
    MainCity(ui).tab(L.TAB_HERO)
    ui.wait(1.8)
    for _ in range(3):
        # 页签本来就不改画面（已是当前页时），硬校验只会白等 4 个补偿点
        ui.press(pos, 250, label=f"hero_sub:{title_key}", expect="none")
        ui.wait(2.0)
        if titles.on_page(ui.screen("hero_sub"), title_key):
            return True
        if _close_idle_popup(ui):
            continue           # 被付费面板挡住：关掉后原地点一次页签
        ui.press(L.BACK, 220, expect="none")
        ui.wait(1.2)
    return False


class CollectionTask(BaseTask):
    name = "collection"
    title = "图鉴升级"
    category = "upgrade"

    @staticmethod
    def _level_of(im):
        """读「图鉴等级」面板顶部的大数字（364）；读不到返回 None。"""
        from .. import textocr
        if not textocr.available():
            return None
        try:
            text = textocr.read_text(im, L.COLLECTION_LEVEL_BOX).replace(" ", "")
        except Exception:      # noqa: BLE001 - 只是证据判据，读不到就当没有
            return None
        m = re.search(r"\d{1,4}", text)
        return int(m.group(0)) if m else None

    def _upgrade_current(self, ui, idx: int = 0) -> int:
        """当前分类：书图标 → 「图鉴等级」面板 → 金色「升级」点到消失。"""
        before = ui.screen("tj_before")
        hit = ui.press(L.COLLECTION_BOOK, 250, label="collection_book")
        ui.wait(1.8)
        im = ui.screen("tj_panel")
        if not hit or vision.similar(before, im):
            # 2026-11-04：不许静默 break——写清第几类、点了哪里、为什么没进面板
            log.warn(f"  图鉴：第 {idx} 类点书图标 {L.COLLECTION_BOOK} 后画面没变"
                     f"（press_hit={hit}），本类跳过")
            return 0
        log.info(f"  图鉴：第 {idx} 类「图鉴等级」面板已打开")
        n = 0
        lvl0 = self._level_of(im)
        if lvl0 is not None:
            log.info(f"  图鉴：第 {idx} 类当前等级 {lvl0}（点一次应 +1）")
        for i in range(40):
            # 2026-11-09：必须有「质心本身就是金色」的按钮才算可点。放宽档在
            # 积分不足时会命中面板里那行橙色说明文字（见 docstring），那不是按钮。
            pos = vision.gold_band_point(im, L.COLLECTION_UP_ZONE, min_px=900, r=18)
            if pos is None:
                log.info(f"  图鉴：第 {idx} 类第 {i + 1} 轮没有可点的金色「升级」按钮"
                         f"（区域 {L.COLLECTION_UP_ZONE}，已满级或图鉴积分不足）")
                break
            cx, cy = pos
            # 2026-11-08：升级是纯本地结算（点一下就 +1 级，没有动画要等），
            # 旧版每次 wait(1.6) 让 120 次升级白烧 314 秒。0.85 秒足够让计数
            # 刷新，同时保留「每次看一眼有没有弹奖励窗」的判据。
            ui.press((cx, cy), 160, label=f"collection_up:{idx}", expect="none")
            ui.wait(0.85)
            after = ui.screen("tj_panel2")
            if vision.darkened(im, after):
                ui.press(L.BLANK, 150, expect="none")
                ui.wait(0.8)
                after = ui.screen("tj_panel3")
            # 2026-11-09 假成功审计 C2：原来这里无条件 n += 1，只要金色块还在就能
            # 一路数到 40（日志里连续多天满额「升级 40 级」，而 state 里累计同一数字）。
            # 真证据是面板顶部的等级数字（真帧「364」）：点一次必须 +1。
            lvl = self._level_of(after)
            if lvl is None or lvl == lvl0:
                # 数字动画/浮层可能慢一拍：等一次再看
                ui.wait(1.2)
                after2 = ui.screen("tj_panel4")
                lvl = self._level_of(after2)
                after = after2
            if lvl is not None and lvl0 is not None:
                grew = lvl != lvl0
                why = f"等级 {lvl0}→{lvl}"
            else:
                # OCR 不可用：退回像素差分（只作兜底，阈值放低些）
                grew = vision.diff_ratio(im, after, L.COLLECTION_LEVEL_BOX) >= 0.01
                why = f"等级数字读不到，像素差分={'变了' if grew else '没变'}"
            if not grew:
                log.info(f"  图鉴：第 {idx} 类升级停在 {n} 级（{why} = 没有升动，"
                         f"材料/积分不足或已满级），不再计数")
                im = after
                break
            n += 1
            lvl0 = lvl if lvl is not None else lvl0
            im = after
            log.info(f"  图鉴：第 {idx} 类升级 ×{n}（{why}）")
        m = [p for p in ui._find_close_buttons(ui.screen("tj_close")) if p[1] <= 320]
        if m:
            ui.press((int(m[0][0]), int(m[0][1])), 160, expect="none")
        else:
            ui.press(L.COLLECTION_CLOSE, 180, expect="none")
        ui.wait(0.9)
        return n

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        log.info(f"  图鉴：进入英雄页子页签 {L.HERO_TAB_COLLECTION}")
        if not _enter_hero_sub(ctx, L.HERO_TAB_COLLECTION, "collection"):
            log.warn(f"  图鉴：点了 {L.HERO_TAB_COLLECTION} 但标题模板没命中，放弃本次任务")
            MainCity(ui).ensure()
            return TaskResult.fail("进不去图鉴页（标题模板未命中）")
        total = 0
        for i, pos in enumerate(L.COLLECTION_TABS, 1):
            # 已选中的分类页签再点不会变，硬校验只会白等 4 个补偿点
            hit = ui.press(pos, 220, label=f"collection_tab:{i}", expect="none")
            ui.wait(1.3)
            n = self._upgrade_current(ui, i)
            total += n
            log.info(f"  图鉴：分类 {i}（{pos}）press_hit={hit} 升级 {n} 级")
        ui.press(L.BACK, 220, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        stats = {"levels": total}
        if not total:
            stats["noop_ok"] = True   # 2026-11-09：今天没有可升级的（积分/材料不足）= 真状态
        return TaskResult(True, f"图鉴升级 {total} 级", stats)


class HeroBondTask(BaseTask):
    name = "hero_bond"
    title = "英雄羁绊"
    category = "upgrade"

    @staticmethod
    def _badge(im, cx, cy) -> bool:
        """按钮上有没有红「!」角标（窗口扫描，见 L.BOND_BADGE）。"""
        return vision.red_badge_near(im, cx, cy, *L.BOND_BADGE, need=6)

    @classmethod
    def _badged_button(cls, im, bands=None):
        """只挑右上角带红「!」的「升级」（没满足条件的按钮点了只会弹提示）。"""
        bands = bands if bands is not None else vision.gold_bands_any(im, L.BOND_UP_ZONE)
        for cx, cy, _ in bands:
            if cls._badge(im, cx, cy):
                return (cx, cy)
        return None

    def _run_category(self, ui, idx: int = 0) -> int:
        """翻一个分类：只点带红「!」的升级按钮，翻不动就收。

        2026-11-07：日志降噪——「本类没有可升级的」是常态（条件行写着
        「羁绊内英雄均达到神话5星（0/2）」未满足），用 info 记一次就够；
        只有「有角标却没升动/升到一半卡住」才值得 warn。
        """
        total = 0
        last = (0, 0)
        seen_badge = 0
        for i in range(16):
            im = ui.screen("bond")
            bands = vision.gold_bands_any(im, L.BOND_UP_ZONE)
            badged = sum(1 for cx, cy, _ in bands if self._badge(im, cx, cy))
            last = (len(bands), badged)
            seen_badge = max(seen_badge, badged)
            if i == 0:
                log.info(f"  英雄羁绊：第 {idx} 类第 1 屏：金色升级按钮 {len(bands)} 个，"
                         f"带红角标 {badged} 个（之后每屏不再逐条记）")
            hit = self._badged_button(im, bands)
            if hit:
                ui.press(hit, 250, label=f"bond_up:{idx}", expect="none")
                ui.wait(1.8)
                after = ui.screen("bond2")
                if vision.darkened(im, after):
                    ui.press(L.BLANK, 150, expect="none")
                    ui.wait(0.8)
                    after = ui.screen("bond2b")
                # 2026-11-09 假成功审计 C3：原来 press 用 expect="none"（恒 True）、
                # 点完直接 total += 1，同一按钮被反复命中也能刷成 48 次。
                # 真证据：升动之后这个按钮的红「!」角标会消失。
                if self._badge(after, hit[0], hit[1]):
                    log.info(f"  英雄羁绊：第 {idx} 类点了带角标的升级但角标仍在"
                             f"（条件仍未满足），本类到 {total} 次为止")
                    break
                total += 1
                log.info(f"  英雄羁绊：升级 ×{total}（角标已消失）")
                continue
            # 没有可升的：往下翻，翻不动就结束
            before = im
            ui.dev.swipe(*L.BOND_SCROLL, 500)
            ui.wait(1.0)
            if vision.similar(before, ui.screen("bond3")):
                if seen_badge:
                    log.warn(f"  英雄羁绊：第 {idx} 类翻不动了（本屏金块 {len(bands)} 个、"
                             f"带角标 {badged} 个），本类结束，共升级 {total} 次")
                else:
                    log.info(f"  英雄羁绊：第 {idx} 类翻了 {i + 1} 屏到底，本类没有可升级的"
                             f"（最后一屏金块 {len(bands)} 个、带角标 0 个）")
                break
        else:
            log.warn(f"  英雄羁绊：第 {idx} 类翻了 16 屏仍未到底，本类结束，共升级 {total} 次"
                     f"（最后一屏金块 {last[0]}、带角标 {last[1]}）")
        if total == 0 and seen_badge:
            # 有角标却一次没升动 —— 这才是真问题
            log.warn(f"  英雄羁绊：第 {idx} 类 0 次升级（最后一屏金块 {last[0]}、"
                     f"带角标 {last[1]}，区域 {L.BOND_UP_ZONE}）")
        return total

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        log.info(f"  英雄羁绊：进入英雄页子页签 {L.HERO_TAB_BOND}")
        if not _enter_hero_sub(ctx, L.HERO_TAB_BOND, "hero_bond"):
            log.warn(f"  英雄羁绊：点了 {L.HERO_TAB_BOND} 但标题模板没命中，放弃本次任务")
            MainCity(ui).ensure()
            return TaskResult.fail("进不去英雄羁绊页（标题模板未命中）")
        total = 0
        # 羁绊也分 英雄/专武/神器 三个分类页签（2026-10-31 实测）
        for i, pos in enumerate(L.COLLECTION_TABS, 1):
            hit = ui.press(pos, 220, label=f"bond_tab:{i}", expect="none")
            ui.wait(1.3)
            n = self._run_category(ui, i)
            total += n
            log.info(f"  英雄羁绊：分类 {i}（{pos}）press_hit={hit} 升级 {n} 次")
            # 回到列表顶部，避免上一类翻到底影响下一类
            for _ in range(3):
                ui.dev.swipe(360, 420, 360, 950, 400)
                ui.wait(0.4)
        ui.press(L.BACK, 220, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        stats = {"times": total}
        if not total:
            stats["noop_ok"] = True   # 2026-11-09：没有满足条件的羁绊 = 真状态
        return TaskResult(True, f"英雄羁绊升级 {total} 次", stats)

