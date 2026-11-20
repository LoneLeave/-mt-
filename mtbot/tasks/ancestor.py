"""主城 → 先祖魂画（三台每日免费一次：专武打造 / 战宠召唤 / 神器锻造）。

**为什么需要它**：先祖魂画底部有三个台位页签 —— `天锻炉`（专武打造）、`唤灵台`
（战宠召唤）、`神铸台`（神器锻造）。三台各自每天有一次免费的「一次」操作，
脚本 2026-11-11 之前只做了天锻炉那一次，唤灵台/神铸台每天白丢。

**真机坐标（logs/_probe_ancestor3.txt，2026-11-11 17:39）**：
- 页签：天锻炉 (401,1258) / 唤灵台 (513,1259) / 神铸台 (625,1259)
- 天锻炉：免费 (224,887) + 打造一次 (224,945)
- 唤灵台：召唤一次 (224,1074) + 免费 (221,1125)（免费在按钮下方）
- 神铸台：免费 (220,1017) + 神铸一次 (225,1075)（免费在按钮上方）

**安全边界**：只点「一次」；「十次 / 十连」与「战令」一律不点；
没有读到「免费」就跳过该台（不花券/钻）。
"""
from __future__ import annotations

import re

from .. import layout as L
from .. import log, textocr
from ..pages import MainCity
from .base import BaseTask, TaskContext, TaskResult

# (台名, 页签坐标或 None, 免费标签框, 「一次」按钮, 人类可读动作)
TABS = (
    ("天锻炉", None, L.ANCESTOR_FREE_BOX, L.ANCESTOR_FORGE_ONE, "专武打造"),
    ("唤灵台", L.ANCESTOR_TAB_PET, L.ANCESTOR_PET_FREE_BOX, L.ANCESTOR_PET_ONE, "战宠召唤"),
    ("神铸台", L.ANCESTOR_TAB_ARTIFACT, L.ANCESTOR_ART_FREE_BOX, L.ANCESTOR_ART_ONE, "神器锻造"),
)


class AncestorTask(BaseTask):
    name = "ancestor"
    title = "先祖魂画（三台每日免费各一次，别白丢）"
    category = "reward"

    @staticmethod
    def _free_state(im, box) -> tuple[str, str]:
        """读「免费」标签的真实状态 —— 返回 (状态, 原文)。

        状态取值：
          - `"free"`    ：今天还免费，可以点「一次」；
          - `"used"`    ：文案是「16时6分后免费」这种倒计时 → 今天免费已用掉，
                          **再点就是花券/钻**，必须跳过（2026-11-18 真帧：三台
                          今天全是这种倒计时，旧代码把倒计时里的「免费」当成
                          「还免费」，在唤灵台上白点了一次「召唤一次」）；
          - `"unknown"` ：没读到任何「免费」字样。
        """
        try:
            txt = (textocr.read_text(im, box) or "").replace(" ", "")
        except Exception:      # noqa: BLE001
            return "unknown", ""
        if not txt:
            return "unknown", ""
        if "免费" not in txt:
            return "unknown", txt
        m = re.search(r"(\d{1,2})时(\d{1,2})分后免费", txt)
        if m:
            return "used", f"{m.group(1)}时{m.group(2)}分后免费"
        if re.search(r"\d+天\d+时后免费", txt):
            return "used", txt
        if "后免费" in txt or "后可免费" in txt:
            return "used", txt
        return "free", txt

    @staticmethod
    def _at_page(im) -> bool:
        try:
            txt = textocr.read_text(im, L.ANCESTOR_PAGE_BOX) or ""
        except Exception:
            return False
        return "打造" in txt or "召唤" in txt or "神铸" in txt

    @staticmethod
    def _got(im) -> bool:
        try:
            txt = textocr.read_text(im, (0, 120, 720, 1280)) or ""
        except Exception:
            return False
        return "恭喜获得" in txt or "获得" in txt

    def _ensure_page(self, ui) -> bool:
        if ui.state().value != "main_city" and self._at_page(ui.screen("ancestor_chk")):
            return True
        MainCity(ui).ensure()
        ui.press(L.BLD_ANCESTOR, 250, label="ancestor_entry", expect="none")
        ui.wait(2.8)
        im = ui.screen("ancestor_page")
        if self._at_page(im):
            return True
        log.warn("  先祖魂画：点了主城入口但没进页（可能被横幅挡住），本次停止")
        return False

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        if not self._ensure_page(ui):
            MainCity(ui).ensure()
            return TaskResult.fail("进不去先祖魂画页")

        done, skipped, used = [], [], []
        for name, tab, free_box, btn, what in TABS:
            if not self._ensure_page(ui):
                break
            if tab is not None:
                ui.press(tab, 220, label=f"ancestor_tab_{name}", expect="none")
                ui.wait(1.8)
            im = ui.screen(f"ancestor_{name}")
            state, raw = self._free_state(im, free_box)
            if state != "free":
                if state == "used":
                    log.info(f"  先祖魂画·{name}（{what}）：今天免费已用掉（{raw}），"
                             f"再点就是花券/钻，不点")
                    used.append(f"{name}:{raw}")
                else:
                    log.info(f"  先祖魂画·{name}（{what}）：没读到「免费」标签，不点")
                skipped.append(name)
                continue
            log.info(f"  先祖魂画·{name}（{what}）：读到「免费」，点一次")
            ui.press(btn, 250, label=f"ancestor_{name}_free", expect="none")
            ui.wait(2.8)
            after = ui.screen(f"ancestor_{name}_after")
            got = self._got(after)
            # 2026-11-19 假成功审计 C3：以前点了就 done.append，不看结果。
            # 现在要两条证据之一：①弹出结果弹窗；②「免费」标签变成「N时N分后免费」倒计时
            # （说明这次免费真的被消耗掉了）。
            st2, raw2 = self._free_state(after, free_box)
            if got or st2 == "used":
                log.info(f"  先祖魂画·{name}：免费{what}完成（结果弹窗={got}，免费标签→{raw2 or '无'}）")
                done.append(name)
            else:
                log.info(f"  先祖魂画·{name}：点了「免费{what}」但既没弹结果、免费标签也没变倒计时，"
                         f"不算完成")
                skipped.append(name)
            if got:
                ui.press(L.BACK, 220, label="ancestor_pop_close", expect="none")
                ui.wait(1.6)

        ui.press(L.BACK, 220, label="ancestor_leave", expect="none")
        ui.wait(1.4)
        MainCity(ui).ensure()
        if not done:
            if used:
                return TaskResult(True, f"跳过：先祖魂画三台今天免费都已用掉（{used[0]}，别再点）",
                                  {"forged": 0, "skipped": skipped, "used": used, "noop_ok": True})
            return TaskResult(True, f"跳过：先祖魂画三台今天都没有免费（{', '.join(skipped) or '无'}）",
                              {"forged": 0, "skipped": skipped, "noop_ok": True})
        tail = f"；跳过 {len(skipped)} 台（{', '.join(skipped)}）" if skipped else ""
        return TaskResult(True, f"先祖魂画：三台免费手工点 {len(done)} 台（{'/'.join(done)}）{tail}",
                          {"forged": len(done), "done": done, "skipped": skipped})
