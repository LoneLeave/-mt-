# -*- coding: utf-8 -*-
"""天神符文（朱鹤/白虎/玄牛/青龙）更换 + 印记背包分解。

2026-11-18 实机取证（720×1280，帧存 tests/fixtures/）：
- 助阵(246,1254) → 「天神传承」卡片(557,842) → 页标题「朱鹤圣印·2阶」、右上「印记背包」(634,154)
- 四套页签 朱鹤(189,770)/白虎(304,771)/玄牛(417,771)/青龙(532,771)
- 六颗符文 水(187,295)/火(530,295)/土(118,469)/风(602,469)/木(188,641)/雷(530,641)
- 带感叹号的符文上方有**红色角标**（vision.red_clusters 命中：土符文 (119,433)）
- 点符文 → 详情页：「神话朱鹤土之印」「神力值：50」「更换」(361,980) 金钮
- 点「更换」→「镶嵌印记」列表：当前那颗标「当前装备」，没有可换的写「暂无可镶嵌印记」
- 印记背包 → 右下圆形「分解」图标(582,888) → 「印记分解」页
  「快速选择」(228,988) 勾选全部可分解 →「分解」(492,988) **立即执行、没有二次确认**
  →「获得奖励」浮层（150 印记核心 / 白虎粉尘），点空白关闭
  空选点「分解」只提示「请选择要分解的印记」；没有可分解时写「暂无印记」

安全边界（绝不误伤）：
- 只分解「≤BAG_SAFE_RANK 阶」且名字不含「传说/神话」的印记；一旦看到高档印记就整页不动。
- 「更换」只在列表里确实出现可镶嵌选项、且不是「当前装备」那颗时才按，按完必须复核。
"""
import re

from .. import layout as L, log, textocr, titles, vision
from ..pages import MainCity
from .base import BaseTask, TaskResult

POWER_RE = re.compile(r"神力值[:：]?\s*(\d{1,6})")
RANK_RE = re.compile(r"(\d{1,2})\s*阶")


def _key_y(lines):
    """「当前装备」标记的 y 坐标（换装前后对比用）。

    2026-11-20 第 68 轮实机：`_swap` 里引用了一个不存在的 `txt`（NameError），
    整个天神任务 FAIL。顺手把「是否真的换动」从「文本里有/没有」改成
    「标记的 y 位置是否移动」—— 换装前后这条标记都在，比文本有无可靠。
    """
    for t, c, _b, _s in lines:
        if L.TIANSHEN_CHANGE_KEY in t:
            return c[1]
    return None


def _txt(im, box, min_score=0.3):
    try:
        return textocr.read_text(im, box) or ""
    except Exception:
        return ""


class TianshenTask(BaseTask):
    """天神符文更换 + 印记背包分解。"""

    name = "tianshen"
    title = "天神符文（感叹号换装 + 印记分解）"
    category = "upgrade"

    # ---------- 进入 ----------
    def _open_page(self):
        ui = self.ui
        ui.press((246, 1254), 250, expect="none")       # 助阵
        ui.wait(2.2)
        ui.press(L.TIANSHEN_ENTRY, 250, expect="none")  # 天神传承
        ui.wait(2.4)
        im = ui.screen("ts_page")
        return im if self._at_page(im) else None

    def _at_page(self, im=None):
        """是不是停在「天神传承」主页（六颗符文那一页）。

        坑（2026-11-18 实测）：「更换」弹层和符文详情页**也**画着右上「印记背包」和
        「XX圣印·N阶」标题，只看这两个词会误判为在主页 → 于是对着弹层点 (634,154)
        什么都不会发生，后面的分解整段被跳过。所以这里排除两件事：
        出现「镶嵌印记」（更换弹层）或「神力值」（符文详情）就说明不在主页。
        """
        if im is None:
            im = self.ui.screen("ts_at")
        lines = textocr.read_lines(im, (0, 140, 720, 330), min_score=0.3)
        txt = "".join(t for t, _c, _b, _s in lines).replace(" ", "")
        if "镶嵌印记" in txt or "神力值" in txt or "暂无可镶嵌" in txt:
            return False
        return ("圣印" in txt and "印记背包" in txt) or titles.on_page(im, "inherit")

    def _back_to_page(self, tries: int = 3) -> None:
        """退回到天神传承主页（BACK 次数会随叠加层数变，按页面判据走）。"""
        for _ in range(tries):
            if self._at_page():
                return
            self.ui.press(L.BACK, 220, expect="none")
            self.ui.wait(1.2)

    # ---------- 感叹号扫描 ----------
    def _badges(self, im):
        """返回 (set_name, 序号, (x,y)) 列表：哪些符文带红角标。"""
        out = []
        ui = self.ui
        for name, tx, ty in L.TIANSHEN_TABS:
            ui.press((tx, ty), 220, expect="none")
            ui.wait(1.2)
            im = ui.screen(f"ts_set_{name}")
            for i, (x, y) in enumerate(L.TIANSHEN_RUNES):
                box = (x - L.TIANSHEN_RUNE_PAD, y - L.TIANSHEN_RUNE_PAD,
                       x + L.TIANSHEN_RUNE_PAD, y + L.TIANSHEN_RUNE_PAD)
                if vision.red_clusters(im, box):
                    out.append((name, i, (x, y)))
        return out, im

    # ---------- 换装 ----------
    def _power(self, im):
        m = POWER_RE.search(_txt(im, L.TIANSHEN_DETAIL_POWER_BOX).replace(" ", ""))
        return int(m.group(1)) if m else None

    def _swap(self, x, y, tag):
        """点开带感叹号的符文，看「更换」列表里有没有更合适的印记。"""
        ui = self.ui
        ui.press((x, y), 240, expect="none")
        ui.wait(1.8)
        im = ui.screen(f"{tag}_detail")
        cur = self._power(im)
        ui.press(L.TIANSHEN_CHANGE, 240, expect="none")
        ui.wait(1.8)
        im = ui.screen(f"{tag}_change")
        lines = textocr.read_lines(im, L.TIANSHEN_CHANGE_BOX, min_score=0.3)
        txt = _txt(im, L.TIANSHEN_CHANGE_BOX).replace(" ", "")
        cur_y = _key_y(lines)
        # 「暂无可镶嵌印记」用行级判定：read_text 会把多行拼成一条，容易被换行/空格打断。
        empty = any(L.TIANSHEN_CHANGE_EMPTY[:5] in t for t, _c, _b, _s in lines)
        if not empty and not any(L.TIANSHEN_CHANGE_KEY in t for t, _c, _b, _s in lines):
            # 页面上连「当前装备」都没读到 = 大概率还停在详情/动画里，再看一帧
            ui.wait(1.0)
            im = ui.screen(f"{tag}_change2")
            lines = textocr.read_lines(im, L.TIANSHEN_CHANGE_BOX, min_score=0.3)
            empty = any(L.TIANSHEN_CHANGE_EMPTY[:5] in t for t, _c, _b, _s in lines)
        if empty:
            log.info(f"  天神符文 {tag}：没有可镶嵌的印记（背包里没有更合适的），只是提示可强化")
            self._back_to_page()
            return "none", cur
        # 有可选印记：按第一颗「不是当前装备」的
        cand = None
        for t, c, b, _s in lines:
            if L.TIANSHEN_CHANGE_KEY in t:
                continue
            if "印" in t and "阶" not in t:
                cand = c
                break
        if cand is None:
            log.info(f"  天神符文 {tag}：列表里没认出可点的印记，先不动")
            self._back_to_page()
            return "unknown", cur
        ui.press((cand[0], cand[1] - 40), 240, expect="none")
        ui.wait(2.0)
        im3 = ui.screen(f"{tag}_swapped")
        lines3 = textocr.read_lines(im3, L.TIANSHEN_CHANGE_BOX, min_score=0.3)
        txt3 = _txt(im3, L.TIANSHEN_CHANGE_BOX).replace(" ", "")
        new_y = _key_y(lines3)
        # 证据一：标记的 y 明显移动；证据二：标记落到刚点那颗印记那一行；
        # 证据三：列表文本整体变了且标记还在（重排）。三条都拿不到就不算换动。
        moved = bool(new_y is not None and cur_y is not None and abs(new_y - cur_y) >= 20)
        if not moved and new_y is not None and abs(new_y - cand[1]) <= 45:
            moved = True
        if not moved and txt3 and txt3 != txt and L.TIANSHEN_CHANGE_KEY in txt3:
            moved = True
        log.info(f"  天神符文 {tag}：换了一颗（当前装备标记{'已移动' if moved else '没变'}"
                 f"，y {cur_y}→{new_y}）")
        self._back_to_page()
        return ("swapped" if moved else "unknown"), cur

    # ---------- 分解 ----------
    def _auto_decompose(self, im):
        """「获得普通、史诗印记时自动分解」是否勾上；读不到文字返回 None。"""
        try:
            txt = textocr.read_text(im, L.BAG_AUTO_ROW_BOX) or ""
        except Exception:
            return None
        if L.BAG_AUTO_KEY not in txt.replace(" ", ""):
            return None
        try:
            return vision.green_ratio(im, L.BAG_AUTO_BOX) >= L.BAG_AUTO_ON_RATIO
        except Exception:
            return None

    def _decompose(self):
        ui = self.ui
        self._back_to_page()
        if not self._at_page():
            self._open_page()
        ui.press(L.TIANSHEN_BAG, 240, expect="none")   # 右上「印记背包」
        ui.wait(2.4)
        bag = ui.screen("ts_bag")
        if "印记背包" not in _txt(bag, (0, 150, 720, 240)):
            log.info("  印记：没打开「印记背包」，本次不分解")
            return 0, "no-bag"
        ui.press(L.BAG_DECOMPOSE, 240, expect="none")  # 圆形「分解」图标
        ui.wait(2.2)
        im = ui.screen("ts_decompose")
        txt = _txt(im, (0, 150, 720, 240))
        if "印记分解" not in txt:
            log.info("  印记：没进「印记分解」页，本次不分解")
            return 0, "no-mode"
        # 2026-11-20 真帧取证（logs/_bag_dec.png）：这一页底部有「获得普通、史诗印记时
        # 自动分解」开关，默认就是勾上的，管的是以后入包的普通/史诗印记。用户第 8 项要
        # 「把没用的印记分解掉」，所以先确认它开着（关着就点开，不花任何资源、可逆），
        # 再看这一页有没有值得动的低阶货。
        auto = self._auto_decompose(im)
        if auto is None:
            log.info("  印记：读不到「自动分解」开关（缺证），本次不动手")
            return 0, "no-auto-evidence"
        if not auto:
            log.info("  印记：「获得普通、史诗印记时自动分解」没开，先点开"
                     "（以后普通/史诗印记入包自动分解，不用天天手动清）")
            ui.press(L.BAG_AUTO_TAP, 220, label="bag_auto_on", expect="none")
            ui.wait(1.4)
            im = ui.screen("ts_dec_auto")
            if not self._auto_decompose(im):
                log.info("  印记：点开后开关没勾上（读不到绿勾），本次不分解")
                return 0, "auto-off"
        items = _txt(im, L.BAG_ITEMS_BOX).replace(" ", "")
        if any(k in items for k in L.BAG_EMPTY_KEYS):
            log.info("  印记：背包里没有可分解的印记")
            return 0, "empty"
        ranks = [int(m) for m in RANK_RE.findall(items)]
        premium = [k for k in L.BAG_PREMIUM if k in items]
        # 2026-11-20 审计 C4：分解不可撤销。阶数一个都没读出来时，下面「高档保护」
        # 判据（max(ranks) > BAG_SAFE_RANK）恒为假 → 会把整页连高档的一起分解。
        # 读不出阶数就当证据缺失，直接不动。
        if not ranks and not premium:
            log.info("  印记：读不出待分解印记的阶数（缺证），本次不分解")
            return 0, "no-rank-evidence"
        if premium or (ranks and max(ranks) > L.BAG_SAFE_RANK):
            # 「快速选择」是整页全选，混着高档印记就会误伤（分解不可撤销）。
            log.info("  印记：这一页只剩" +
                     ("、".join(premium) if premium else f"{max(ranks)} 阶") +
                     "这类高档印记（没有普通/史诗低阶货），不分解；"
                     "「获得普通、史诗印记时自动分解」已开着，以后的垃圾印记会自动处理")
            return 0, "only-premium"
        ui.press(L.BAG_QUICK, 220, expect="none")      # 快速选择
        ui.wait(1.6)
        im = ui.screen("ts_quick")
        if not any(k in _txt(im, (120, 880, 620, 960)) for k in L.BAG_PICK_KEYS):
            log.info("  印记：「快速选择」后没出现「分解可得」，不按分解")
            return 0, "no-pick"
        ui.press(L.BAG_GO, 240, expect="none")         # 分解（立即执行）
        ui.wait(2.2)
        gain = ui.screen("ts_gain")
        got = _txt(gain, L.BAG_GAIN_BOX).replace(" ", "")
        if any(k in got for k in L.BAG_GAIN_KEYS):
            ui.press(L.BLANK, 200, expect="none")
            ui.wait(1.0)
            log.info(f"  印记：分解完成（{got[:40]}）")
            return 1, "done"
        log.info("  印记：点了「分解」没有「获得奖励」浮层，按没分解记账")
        return 0, "no-gain"

    # ---------- 主流程 ----------
    def run(self, ctx):
        self.ui = ctx.ui
        ui = self.ui
        ui.ensure_main_city()
        im = self._open_page()
        if im is None:
            MainCity(ui).ensure()
            return TaskResult.skip("进不去天神传承页", {"badges": 0})

        badges, im = self._badges(im)
        log.info(f"  天神符文：四套页签扫完，带感叹号的符文 {len(badges)} 颗" +
                 ("：" + "、".join(f"{n}#{i + 1}" for n, i, _p in badges) if badges else ""))

        try:
            max_swap = int(self.p.get("max_swap", 6) or 6)
        except Exception:
            max_swap = 6
        swapped = 0
        none_list = 0
        for name, i, (x, y) in badges[:max_swap]:
            kind, _cur = self._swap(x, y, f"{name}{i + 1}")
            if kind == "swapped":
                swapped += 1
            elif kind == "none":
                none_list += 1

        n_dec, why = self._decompose()
        MainCity(ui).ensure()
        why_cn = {"only-premium": "包里只剩传说/神话，没动",
                  "no-auto-evidence": "读不到自动分解开关，没动",
                  "auto-off": "自动分解开关点不着，没动",
                  "empty": "背包里没有可分解印记",
                  "risky": "有高档印记，没动"}.get(why, why)
        parts = [f"带感叹号符文 {len(badges)} 颗",
                 f"换装 {swapped} 颗",
                 f"无可换 {none_list} 颗",
                 f"分解 {n_dec} 批" + (f"（{why_cn}）" if n_dec == 0 else "")]
        return TaskResult(True, "天神符文：" + "，".join(parts),
                          {"badges": len(badges), "swapped": swapped,
                           "decomposed": n_dec, "noop_ok": True})
