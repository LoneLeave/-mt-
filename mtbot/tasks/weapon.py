"""专武（专属武器）均匀升级。

真机结构（2026-11-18 01:43~01:51 探针逐帧取证，720×1280）：
- 英雄页 → 点英雄卡 → 英雄详情。左下那颗 S+ 槽是**专武**（OCR「类型：xxx专属」「专武技能」），
  右侧那颗 S+ 槽是**神器装备**（「类型：神器装备」「神器词缀」）——后者不归本任务。
  详情页专武等级徽章 OCR (55,545,150,580) → 「S+130级」/「+130级」。
- 点专武槽 (100,600) → 专武面板（卸下/更换/培养/进阶/脱装/升级），金色「培养」在 (511,966)。
- 「培养」→ 专武培养页：`等级 130 → 131`、材料 `13050/19000`、金色「升级」在 (358,1094)；
  共鸣中的专武写「专武共鸣中，无法升级」+「设为支柱」，且该页没有任何金色升级钮（实测血怒战斧 1050 级）。
- **材料不足时点「升级」不会升级**，而是弹「熔火精华 类型：货币 拥有：13050 / 简介：专武升级所需要的经验」
  物品浮层（2026-11-18 01:50 实测 y=1075~1100 各处都会弹）→ 这正好当「材料不够」的判据。

策略（均匀）：先花一次代价确认材料够不够，不够就直接跳过，不白扫 12 个英雄；
够就扫英雄页可见卡位的专武等级，按「谁低先升谁」一轮一轮各升 1 级，直到材料见底或到轮数上限。
只用游戏内材料，绝不买钻石；每次点「升级」前后都跑一遍钻石确认框闸门。
"""
from __future__ import annotations

import re

from .. import layout as L
from .. import log, textocr, vision
from ..pages import MainCity
from .base import BaseTask, TaskContext, TaskResult

LV_RE = re.compile(r"(\d{1,4})\s*级")


def _txt(im, box) -> str:
    try:
        return (textocr.read_text(im, box) or "").replace(" ", "")
    except Exception:          # noqa: BLE001 - OCR 异常不该打断任务
        return ""


class WeaponTask(BaseTask):
    name = "weapon"
    title = "专武（专属武器）均匀升级"
    category = "upgrade"

    # ---------------- 读数 ----------------

    def _level(self, im) -> "int | None":
        """英雄详情页专武槽的等级（「S+130级」/「+130级」→ 130）。"""
        # 真帧：「S+130级」/「+130级」；培养页同框可能读到「等级130」，所以只认数字
        m = re.search(r"(\d{1,4})", _txt(im, L.WEAPON_LEVEL_BOX))
        return int(m.group(1)) if m else None

    def _material(self, im) -> "tuple[int, int] | None":
        """培养页底部的「13050/19000」→ (拥有, 需要)。

        真帧 OCR 会把斜杠吞掉读成「13050 19000」（2026-11-18 实测 box 输出
        [('13050',…,0.998), ('19000',…,0.997)]）；若直接把空格删掉再配两条数字，
        会把「1305019000」切成 (1305019, 000) 这种鬼数字，所以按 token 走。
        """
        try:
            lines = textocr.read_lines(im, L.WEAPON_MATERIAL_BOX, min_score=0.3)
        except Exception:          # noqa: BLE001
            lines = []
        nums = []
        for text, _c, _b, _s in lines:
            tok = (text or "").replace(" ", "")
            if re.fullmatch(r"\d{1,7}", tok):
                nums.append(int(tok))
        if len(nums) >= 2:
            have, need = nums[0], nums[1]
            return (have, need) if have <= need else (need, have)
        # 兜底：整框文本里找「数字 数字」
        m = re.search(r"(\d{2,7})\s*/?\s*(\d{2,7})", _txt(im, L.WEAPON_MATERIAL_BOX))
        if not m:
            return None
        have, need = int(m.group(1)), int(m.group(2))
        return (have, need) if have <= need else (need, have)

    def _cult_level(self, im) -> "int | None":
        # 真帧实测该框读回的是「等级130」（不是「130级」），只认数字
        m = re.search(r"(\d{1,4})", _txt(im, L.WEAPON_CULT_LEVEL_BOX))
        return int(m.group(1)) if m else None

    def _resonating(self, im) -> bool:
        """「专武共鸣中，无法升级」——这种专武今天升不动（要走「设为支柱」，不归本任务）。"""
        return "共鸣" in _txt(im, L.WEAPON_RESONATE_BOX)

    # ---------------- 导航 ----------------

    def _hero_list(self) -> None:
        ui = self.ui
        MainCity(ui).ensure()
        ui.press(L.TAB_HERO, 250, label="weapon_tab", expect="none")
        ui.wait(1.8)

    def _reset_list(self) -> None:
        """退回英雄列表并重新锚定。

        实测：培养页 →BACK→ 英雄详情 →BACK→ 列表 →BACK→ 主城；所以盲按 2 次
        （从详情起步会多退一层到主城，也无害），最后按「英雄」页签重新锚定。
        全程 expect="none"：这几次按键本身不做成功判据，判据在随后的 OCR/金色钮上。
        """
        ui = self.ui
        for _ in range(2):
            ui.press(L.BACK, 180, label="weapon_back", expect="none")
            ui.wait(1.0)
        ui.press(L.TAB_HERO, 220, label="weapon_tab", expect="none")
        ui.wait(1.7)

    def _back_to_list(self) -> None:
        """只在英雄详情页用：按一次返回到列表；万一没退成功（还是详情）再补一次。"""
        ui = self.ui
        ui.press(L.BACK, 180, label="weapon_back", expect="none")
        ui.wait(1.0)
        if self._level(ui.screen("weapon_back_chk")) is not None:
            ui.press(L.BACK, 180, label="weapon_back2", expect="none")
            ui.wait(1.0)

    def _open_detail(self, pos) -> bool:
        ui = self.ui
        ui.press(pos, 240, label="weapon_hero", expect="none")
        ui.wait(2.2)
        if self._level(ui.screen("weapon_detail")) is not None:
            return True
        # 有的英雄卡要再点一次才进详情
        ui.press(pos, 240, label="weapon_hero2", expect="none")
        ui.wait(1.8)
        return self._level(ui.screen("weapon_detail2")) is not None

    def _open_cultivate(self) -> tuple[bool, object]:
        """从英雄详情进专武培养页。返回 (成功, 培养页帧)。"""
        ui = self.ui
        ui.press(L.WEAPON_SLOT, 220, label="weapon_slot", expect="none")
        ui.wait(1.8)
        ui.press(L.WEAPON_CULTIVATE, 220, label="weapon_cultivate", expect="none")
        ui.wait(1.9)
        im = ui.screen("weapon_cult")
        # 到页判据：培养页底部那颗大金色「升级」（真帧金块 (358,1092,3281)），
        # 或读到材料 / 等级 / 共鸣提示。只靠 OCR 数字会漏（「等级130」不带「级」）。
        ok = (vision.is_gold(im, *L.WEAPON_UPGRADE, r=18)
              or self._material(im) is not None
              or self._cult_level(im) is not None
              or self._resonating(im))
        return ok, im

    # ---------------- 升级 ----------------

    def _upgrade_one(self, card, levels: int = 1) -> tuple[int, str]:
        """给这一件专武最多升 levels 级。返回 (实际升级数, 结束原因)。"""
        ui = self.ui
        if not self._open_detail(card):
            self._reset_list()
            return 0, "打不开英雄详情"
        ok, im = self._open_cultivate()
        if not ok:
            self._reset_list()
            return 0, "打不开专武培养页"
        if self._resonating(im):
            self._reset_list()
            return 0, "专武共鸣中，无法升级"
        mat = self._material(im)
        if mat and mat[1] > 0 and mat[0] < mat[1]:
            self._reset_list()
            return 0, f"材料 {mat[0]}/{mat[1]} 不足"
        lv = self._cult_level(im)
        done = 0
        reason = "到次数上限"
        for _ in range(max(1, levels)):
            if ui.dismiss_diamond_prompt(im):
                reason = "弹了钻石确认框（已点取消）"
                break
            ui.press(L.WEAPON_UPGRADE, 240, label="weapon_upgrade", expect="none")
            ui.wait(1.9)
            im2 = ui.screen("weapon_after")
            tip = _txt(im2, L.WEAPON_TIP_BOX)
            if any(k in tip for k in L.WEAPON_TIP_KEYS):
                # 材料不足：游戏只弹出「熔火精华」物品说明，等级不变。
                # 关法是点浮层上方的空白处（实测点浮层本体不关；2026-11-18 02:00 探针）。
                for pt in (L.WEAPON_TIP_CLOSE, (360, 300), (620, 1000)):
                    ui.press(pt, 180, label="weapon_tip_close", expect="none")
                    ui.wait(1.0)
                    im = ui.screen("weapon_after2")
                    if not any(k in _txt(im, L.WEAPON_TIP_BOX) for k in L.WEAPON_TIP_KEYS):
                        break
                mat2 = self._material(im)
                reason = f"材料不足（{mat2[0]}/{mat2[1]}）" if mat2 else "材料不足"
                break
            lv1 = self._cult_level(im2)
            if lv1 is None or (lv is not None and lv1 <= lv):
                reason = "点了「升级」等级没变"
                break
            log.info(f"  专武：{lv} → {lv1} 级")
            lv = lv1
            done += 1
            im = im2
        self._reset_list()
        return done, reason

    # ---------------- 主流程 ----------------

    def run(self, ctx: TaskContext) -> TaskResult:
        self.ui = ctx.ui
        ui = self.ui
        self._hero_list()
        cards = [(x, row[0]) for row in L.HERO_CARD_ROWS for x in L.HERO_CARD_XS]

        # 先花一次代价摸清底细：第一件的材料/等级（也能立刻发现「共鸣中」这种整队都升不了的情况）
        if not self._open_detail(cards[0]):
            return TaskResult.fail("专武：英雄页点不开英雄详情", {"opened": 0})
        ok, im = self._open_cultivate()
        if not ok:
            self._reset_list()
            return TaskResult.fail("专武：点「培养」没打开专武培养页", {"cultivated": 0})
        first_mat = self._material(im)
        if self._resonating(im):
            lv = self._cult_level(im)
            self._reset_list()
            return TaskResult(True, "跳过：第一件专武在共鸣中，今天没有可养成的目标",
                              {"noop_ok": True, "resonating": True, "level": lv})
        self._reset_list()

        # 扫可见卡位的专武等级（英雄页一屏 12 个卡位）
        found: "list[tuple[int, tuple[int, int]]]" = []
        for card in cards:
            if not self._open_detail(card):
                self._back_to_list()
                continue
            lv = self._level(ui.screen("weapon_scan"))
            if lv is not None:
                found.append((lv, card))
            self._back_to_list()
        if not found:
            return TaskResult(True, "跳过：英雄页上没读出任何专武等级", {"noop_ok": True})
        found.sort()
        log.info(f"  专武：扫到 {len(found)} 件，等级 {found[0][0]}~{found[-1][0]}"
                 f"（最低 {found[0][0]} 级）；第一件材料 {first_mat}")

        # 从最低的开始一件一件试：每一件都用自己的「拥有/需要」当场判材料，
        # 材料不足就不点「升级」（游戏只会弹个「熔火精华」物品说明，白折腾）。
        total = 0
        stop = ""
        tried = 0
        for lv, card in found[: int(self.p.get("max_try", 3) or 3)]:
            tried += 1
            n, why = self._upgrade_one(card, 1)
            if n:
                total += n
            else:
                stop = why
                if why.startswith("材料") or "共鸣" in why:
                    break
        MainCity(ui).ensure()
        if total <= 0:
            return TaskResult(True, f"跳过：专武今天没升动（{stop or '没有可升的'}）",
                              {"noop_ok": True, "levels": 0})
        return TaskResult(True, f"专武：升了 {total} 级（{len(found)} 件里挑最低的先升）",
                          {"levels": total, "items": len(found), "stop": stop})
