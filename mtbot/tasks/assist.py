"""助阵 / 助战 升级（2026-10-31 按用户要求拆分为独立任务）。

主城底部第三个页签叫「助阵」，圆环菜单里是四个子系统：
  - 荣耀之书（优先战士，被红字等级要求卡住时补其它职业）→ glory_book
  - 天神传承（四套传承的「突破」）                     → inherit
  - 神器（等级均衡升级 + 升星）                       → artifact
  - 战宠（圣坛升阶 + 培养升星）                       → pet

英雄页右上角还有一个「助战」图标，打开是「助战徽记」面板（全英雄属性加成 +
助战技能），材料够时可以一直「升级」 → assist_mark。

旧版把这两个系统混在一个 AssistTask 里、还叫成「助战升级」，2026-10-31 拆开，
每个子系统都能单独勾选调试。
"""
from __future__ import annotations

import re

from .. import layout as L
from .. import log, ocr, textocr, titles, vision
from ..pages import MainCity
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult


def _changed(a, b, box, thr: float = 0.002) -> bool:
    """box 区域前后像素差（升级是否真的生效）。尺寸变了（横屏）直接当“变了”。"""
    if a.size != b.size:
        return True
    x0, y0, x1, y1 = box
    d = t = 0
    for y in range(y0, min(y1, a.height), 4):
        for x in range(x0, min(x1, a.width), 4):
            p, q = a.getpixel((x, y)), b.getpixel((x, y))
            t += 1
            if abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) > 90:
                d += 1
    return t > 0 and (d / t) > thr


class _AssistBase(BaseTask):
    category = "upgrade"

    # 面板顶部「传说/神话 + ★★★★★ + 名字」那一行（真帧 tests/fixtures/artifact_star_popup.png：
    # 800级(107,164) / ★★★★★(359,180) / 安魂之杖+1(359,209)）。升星是否生效只认
    # 这一行里 ★ 的个数变化，像素变化一律不落账。
    STAR_BOX = (60, 150, 660, 215)

    def _stars(self, im) -> int | None:
        """读当前星级（★ 字符数）。读不到返回 None —— 调用方必须按「缺证」处理。"""
        try:
            txt = textocr.read_text(im, self.STAR_BOX) or ""
        except Exception:      # noqa: BLE001
            return None
        n = txt.count("\u2605")
        return n if n >= 1 else None

    # 2026-11-03：底部大按钮若是橙色，是否视为「进阶/突破」并需要 allow_advance 开关。
    # 只有天神传承会把它设成 True；其它面板（荣耀之书/战宠等）保持旧行为。
    ORANGE_MEANS_ADVANCE = False

    # 判定“这次升级真的生效了”用面板中部文字区的前后差异；实测同一页面间隔 2 秒静置差异为 0
    CHANGE_BOX = (300, 880, 430, 1080)
    # 战宠预览弹窗里的文字区（等级上限/升阶属性），按钮本身在别处，避免按下去的阴影误判
    DIALOG_BOX = (140, 500, 580, 760)

    # ---------- 导航 ----------
    def enter_team(self, ui) -> bool:
        if not MainCity(ui).ensure():
            return False
        MainCity(ui).tab(L.TAB_TEAM)          # 主城底部第三个页签 = 助阵
        ui.wait(1.8)
        im = ui.screen("assist_home")
        if vision.classify(im) == State.MAIN_CITY:
            log.warn("  {}：助阵页没打开（页签位置可能变了）".format(self.title))
            return False
        return True

    def open_panel(self, ui, entry, label: str):
        """点圆环页上的入口。返回面板截图；没打开返回 None。

        2026-11-06：助阵圆环页现在能识别成 State.NAV_PAGE 了，入口点不开时画面会停在
        圆环页上（以前 classify 是 UNKNOWN，这个检查从来没触发过），两种都算失败，
        免得继续往错误画面上按「升级」把死点表污染掉。
        """
        # 2026-11-09：助阵圆环页是**动画页**（整圈会缓慢旋转），像素差分在它身上
        # 不可靠 —— 实测战宠那次 diff=0.974「命中」但画面仍停在圆环页，随后
        # classify 判成 NAV_PAGE 才失败；自愈重试时同一点又正常打开了。
        # 所以这里不用变化校验、失败就再点一次，判定只认 classify。
        for attempt in range(2):
            ui.press(entry, 250, label=f"{label}_entry{attempt + 1}", expect="none")
            ui.wait(2.0)
            im = ui.screen(f"assist_panel{attempt + 1}")
            if vision.classify(im) not in (State.MAIN_CITY, State.NAV_PAGE):
                return im
            if attempt == 0:
                log.info(f"  {label}：点了一次入口仍停在助阵圆环页，再点一次")
        log.warn(f"  {label}入口没打开（画面还停在助阵页）")
        return None

    @staticmethod
    def back_ring(ui) -> None:
        # 导航类点击，不校验单点命中（on the ring page BACK may be co-opted by
        # decoration）；如果校验失败会被登记成死点，后面就再也不发了。
        ui.press(L.BACK, 220, label="ring_back", expect="none")
        ui.wait(1.2)

    def finish(self, ctx: TaskContext) -> None:
        ui = ctx.ui
        ui.press(L.BACK, 250, label="assist_finish", expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()

    # ---------- 通用按钮循环（荣耀之书/传承/战宠/神器升星共用） ----------
    @staticmethod
    def _dialog_open(ui, im) -> bool:
        """战宠的预览弹窗：右上角（x≥620, y≤260）有红色圆形关闭钮。"""
        for cx, cy in ui._find_close_buttons(im):
            if cx >= 620 and cy <= 260:
                return True
        return False

    def _dialog_loop(self, ui, label: str) -> int:
        done = 0
        for _ in range(6):
            before = ui.screen("assist_dlg")
            # 这里「点了不变」是合法状态（材料不足 / 按钮不可用），变化由下面的
            # _changed 判定，所以不交给 UI 的变化校验（否则会白等补偿点还报空点）。
            ui.press(L.ASSIST_DIALOG_BTN, 250, expect="none")
            ui.wait(2.0)
            after = ui.screen("assist_dlg2")
            if vision.item_popup(after):
                if done == 0:
                    log.info(f"  {label}：材料不足（弹窗内提示）")
                ui.press(L.HERO_BLANK, 150, expect="none")
                ui.wait(0.9)
                break
            if not _changed(before, after, self.DIALOG_BOX):
                if done == 0:
                    log.info(f"  {label}：弹窗里的按钮点不动")
                break
            done += 1
            log.info(f"  {label}：弹窗内升级 ×{done}")
        ui.press(L.ASSIST_DIALOG_X, 150, expect="none")
        ui.wait(0.9)
        return done

    def _upgrade_loop(self, ui, label: str, limit: int = 10) -> int:
        """按一次大按钮并校验是否真的升级；材料不足/弹预览窗/无反应都各有分支。"""
        done = 0
        im = ui.screen("assist_up")
        for _ in range(limit):
            before = im
            # 2026-11-03 修复 #6：天神传承底部按钮可能是「升级」（金）或「进阶」（橙）。
            # 旧代码只认位置不看颜色，把进阶当升级点，材料一空就卡住。
            if self.ORANGE_MEANS_ADVANCE:
                bands = vision.orange_button_bands(im, (240, 1050, 480, 1190))
                if bands and not vision.is_gold(im, *L.ASSIST_UPGRADE_BTN, r=18):
                    if not bool(self.p.get("allow_advance", False)):
                        log.info(f"  {label}：当前是「进阶」（橙色按钮），已跳过；"
                                 "要进阶请在任务参数里设 allow_advance=true")
                        break
                    log.info(f"  {label}：allow_advance=true，执行一次进阶")
            if not vision.is_gold(im, *L.ASSIST_UPGRADE_BTN, r=18):
                # 2026-11-20 审计 MAJOR：这行原来是固定坐标盲点（荣耀之书/战宠/神器都走
                # 这条路）。现在要求该位置确实是金钮（可点），否则不点、按「已到上限」收手。
                log.info(f"  {label}：升级钮不是金钮（材料不足/已到上限），本轮不点")
                break
            ui.press(L.ASSIST_UPGRADE_BTN, 250, expect="none")
            ui.wait(2.0)
            after = ui.screen("assist_up2")
            if vision.item_popup(after):
                if done == 0:
                    log.info(f"  {label}：材料不足（弹出获取途径窗）")
                ui.press(L.HERO_BLANK, 150, expect="none")
                ui.wait(0.9)
                break
            if self._dialog_open(ui, after):
                done += self._dialog_loop(ui, label)
                break
            if vision.dialog_confirm(after):
                for p in ((465, 697), (360, 805), (360, 905), (465, 760)):
                    if vision.is_gold(after, *p, r=16):
                        ui.press(p, 220)
                        ui.wait(1.8)
                        break
                after = ui.screen("assist_up3")
            if vision.darkened(before, after):
                # 天神传承「突破」这类橙红色按钮会先弹确认窗（窗里还是橙红大按钮），
                # 点掉后再关「突破成功」浮层；找不到橙色按钮就保持原样交给下面的变化判定。
                bands = vision.orange_button_bands(after, (200, 560, 520, 1100))
                if bands:
                    ui.press(bands[0][:2], 250)
                    ui.wait(2.2)
                    ui.press(L.HERO_BLANK, 150, expect="none")
                    ui.wait(0.9)
                    after = ui.screen("assist_up4")
            if not _changed(before, after, self.CHANGE_BOX):
                if done == 0:
                    log.info(f"  {label}：点了没反应（按钮当前不可用）")
                break
            # 2026-11-18：第 44 轮出现过「升级 ×1 但等级没变」——真因是材料不足窗
            # 弹了一下又自动关掉，2.0s 后抓的那一帧只是浮层残留，`_changed` 就为真。
            # 再等 0.9s 抓一帧：只有变化仍然在，才算真的升动；否则按「闪一下」处理。
            ui.wait(0.9)
            again = ui.screen("assist_up_chk")
            if not _changed(before, again, self.CHANGE_BOX):
                if done == 0:
                    log.info(f"  {label}：画面只是闪了一下（多半是材料不足窗弹了又关），不算升级")
                break
            after = again
            done += 1
            log.info(f"  {label}：升级 ×{done}")
            im = after
            if not vision.button_badge(im, L.ASSIST_BADGE_BOX):
                break
        return done


class GloryBookTask(_AssistBase):
    """荣耀之书：优先战士，其它职业只在「所有职业技能需达到N级」的要求下补。"""

    name = "glory_book"
    title = "荣耀之书"

    @staticmethod
    def _requirement(ui):
        im = ui.screen("glory_req")
        nums = ocr.read_number_loose(im, L.GLORY_REQ_BOX)
        return nums[0] if nums else None

    @staticmethod
    def _levels(ui):
        """读四个职业的技能等级；读不到的位置返回 None。"""
        im = ui.screen("glory_levels")
        vals = []
        for box in L.GLORY_LEVEL_BOXES:
            txt = textocr.read_text(im, box).replace(" ", "") if textocr.available() else ""
            m = re.search(r"(\d{1,3})", txt)
            vals.append(int(m.group(1)) if m else None)
        return vals

    def _book(self, ui) -> int:
        """均匀升级：每一轮都挑「当前等级最低」的职业升一次，直到四个职业都升不动。"""
        total = 0
        tried = set()
        for _ in range(40):
            levels = self._levels(ui)
            known = [(lv, i) for i, lv in enumerate(levels) if lv is not None]
            if not known:
                log.info("  荣耀之书：读不到四个职业的技能等级，收手")
                break
            known.sort()
            picked = None
            for lv, idx in known:
                if idx not in tried:
                    picked = (lv, idx)
                    break
            if picked is None:
                req = self._requirement(ui)
                if req is None:
                    log.info("  荣耀之书：四个职业都升不动，收手")
                else:
                    log.info(f"  荣耀之书：四个职业都升不动（当前要求：所有职业技能达到 {req} 级）")
                break
            lv, idx = picked
            name = L.GLORY_CLASS_NAMES[idx]
            ui.press(L.GLORY_TABS[idx], 200, label=f"glory_tab_{idx}", expect="none")
            ui.wait(0.9)
            n = self._upgrade_loop(ui, f"荣耀之书·{name}({lv}级)", limit=1)
            if n <= 0:
                tried.add(idx)
                continue
            after = self._levels(ui)
            now = after[idx] if idx < len(after) else None
            # 2026-11-18：第 44 轮 `辅助(65级)：升级 ×1` 但立刻复读仍是 65 ——
            # `_upgrade_loop` 的像素变化判定把「材料不足窗弹了又关」当成了升级。
            # 升级必须由等级数字自证：没变大就当材料不足，不计入、也不再试这一职业。
            if now is None or now <= lv:
                log.info(f"  荣耀之书：{name} 点了没升动（{lv} → {now if now is not None else '?'}），按材料不足处理")
                tried.add(idx)
                continue
            total += now - lv
            tried.clear()
            log.info(f"  荣耀之书：{name} 升级一次（{lv} → {now}），当前四职业 {after}")
        return total

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not self.enter_team(ui):
            return TaskResult.fail("进不去助阵页")
        if self.open_panel(ui, L.ASSIST_GLORY, "荣耀之书") is None:
            self.finish(ctx)
            return TaskResult.fail("进不去荣耀之书面板")
        total = self._book(ui)
        self.finish(ctx)
        if total <= 0:
            return TaskResult(True, "荣耀之书：技能已满或材料不足，本次没有可升级的",
                              {"times": 0, "noop_ok": True})
        return TaskResult(True, f"荣耀之书升级 {total} 次", {"times": total})


class InheritTask(_AssistBase):
    """天神传承：四套传承逐个点「升级」；橙色「进阶」默认不点（需 allow_advance=true）。"""

    name = "inherit"
    title = "天神传承"
    ORANGE_MEANS_ADVANCE = True       # 2026-11-03 #6：区分 升级(金) / 进阶(橙)

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not self.enter_team(ui):
            return TaskResult.fail("进不去助阵页")
        im = self.open_panel(ui, L.ASSIST_INHERIT, "天神传承")
        if im is None or not titles.on_page(im, "inherit"):
            log.info("  天神传承没打开，退回圆环再进一次")
            self.back_ring(ui)
            im = self.open_panel(ui, L.ASSIST_INHERIT, "天神传承")
        if im is None or not titles.on_page(im, "inherit"):
            self.finish(ctx)
            return TaskResult.fail("进不去天神传承面板")
        total = 0
        for i, tab in enumerate(L.ASSIST_TEAM_TABS, 1):
            # 2026-11-04：第 1 套默认就是当前页签，再点一次 diff=0 会被判空点并做 4 点补偿，
            # 每次白等 ~20s。页签点击不需要命中校验（下一轮自然会按新页读数据）。
            ui.press(tab, 220, expect="none")
            ui.wait(1.2)
            total += self._upgrade_loop(ui, f"天神传承·第{i}套")
        self.finish(ctx)
        if total <= 0:
            return TaskResult(True, "天神传承：四套都已满级或材料不足，本次没有突破",
                              {"times": 0, "noop_ok": True})
        return TaskResult(True, f"天神传承突破 {total} 次", {"times": total})


class ArtifactTask(_AssistBase):
    """神器：均衡升级（永远先升等级最低的那件）。

    2026-10-31 实测：
      - 一屏 4 件可点（x=200/310/430/560 命中 1~4 号），卡片上印「50级/1级/40级/60级」；
      - 底部大按钮**金色 = 升级（等级+1）**，**橙红 = 进阶（品阶+1）**；
        橙色状态下面板那行是「品阶 +N」而不是「等级 N」，旧版把 +N 当等级读，读出来是 1/2；
      - 橙色按钮会弹出「神器进阶」确认窗（窗内仍是橙色「进阶」(360,822)），
        确认后弹「升阶成功」浮层（点空白关），之后按钮变回金色、等级行也回来了。
    """

    name = "artifact"
    title = "神器（均衡升级）"

    @staticmethod
    def _btn_state(im) -> str:
        if all(vision.is_gold(im, *p, r=8) for p in L.ARTIFACT_BTN_GOLD_SAMPLES):
            return "upgrade"
        R, G, B = vision.avg(im, *L.ARTIFACT_BTN, r=8)
        if R > 175 and G < 165 and (R - G) > 45 and B < 140:
            return "advance"
        return "unknown"

    def _select(self, ui, x: int) -> None:
        # 2026-11-07：选中的卡片再点一次画面几乎不变（diff 0.008~0.012），
        # 用 expect="change" 只会白做 4 个补偿点并把这里登记成死点。
        # 选中与否由调用方读 _btn_state / 等级行判定。
        ui.press((x, 615), 200, expect="none")
        ui.wait(1.2)
        self._sel_x = x

    def _advance(self, ui) -> bool:
        """点橙色「进阶」→ 确认窗里再点「进阶」→ 关「升阶成功」浮层。"""
        before = ui.screen("art_adv")
        ui.press(L.ARTIFACT_BTN, 250)
        ui.wait(1.6)
        im = ui.screen("art_adv_dlg")
        if vision.item_popup(im):
            log.info("  神器：进阶材料不足")
            ui.press(L.HERO_BLANK, 150, expect="none")
            ui.wait(0.8)
            return False
        if not vision.darkened(before, im):
            log.info("  神器：进阶没弹出确认窗")
            return False
        ui.press(L.ARTIFACT_ADV_CONFIRM, 250)
        ui.wait(2.2)
        ui.press((200, 400), 150, expect="none")   # 关「升阶成功」
        ui.wait(1.0)
        return True

    def _scan(self, ui):
        """返回 [(x, state, level|None), ...]，按 1~4 号顺序。"""
        out = []
        for x in L.ARTIFACT_CARDS:
            self._select(ui, x)
            im = ui.screen("art_card")
            st = self._btn_state(im)
            # 2026-11-10：等级直接印在卡片下沿（`89级`），按该卡的 x 就近取一行；
            # 旧固定框 ARTIFACT_LV_BOX 已过期（那里现在是品阶/词缀文案）。
            lv = self._card_level(im, x)
            out.append((x, st, lv))
        return out

    @staticmethod
    def _card_level(im, x: int):
        """读某张卡下沿的等级（`89级` / `+115级` → 89 / 115）；读不到返回 None。"""
        import re as _re
        box = (max(0, x - 70), 552, min(719, x + 70), 592)
        try:
            txt = textocr.read_text(im, box).replace(" ", "")
        except Exception:      # noqa: BLE001
            return None
        m = _re.search(r"(\d{1,3})\s*级", txt)
        return int(m.group(1)) if m else None

    def _hint_text(self, ui) -> str:
        """读「升级」按钮附近的提示行（实测会写「神器共鸣中，无法升级」）。

        2026-11-11：窄框只到 y=1090 时读出来是空串（文字其实在 1050~1170 那条带上），
        所以再补一个大框兜底；两段拼起来给调用方判断。
        """
        try:
            im = ui.screen("art_hint")
        except Exception:      # noqa: BLE001
            return ""
        out = ""
        for box in (L.ARTIFACT_HINT_BOX, L.ARTIFACT_HINT_BOX_WIDE):
            try:
                txt = textocr.read_text(im, box) or ""
            except Exception:      # noqa: BLE001
                txt = ""
            if txt.strip():
                out = out + " " + txt.strip()
            if "共鸣" in out:
                break
        return out

    def _level_once(self, ui):
        im = ui.screen("art_lv")
        st = self._btn_state(im)
        lv = None
        if st == "upgrade":
            lv = self._card_level(im, int(getattr(self, "_sel_x", L.ARTIFACT_CARDS[0])))
        return st, lv, im

    def _balance(self, ui) -> int:
        total = 0
        stalls = 0
        # 2026-11-07：材料不足时「连续两轮没升动 / 本轮 +0」这两句原来的 warn 与
        # 上面那句「升级材料不足，停手」说的是同一件事，一天刷两条噪声告警。
        # 现在记住是不是材料挡住的：是就走 info，只有没材料证据的卡住才 warn。
        blocked_by_mat = False
        no_res: set[int] = set()      # 「共鸣中，无法升级」的神器，本次不再尝试
        for _ in range(6):
            cards = self._scan(ui)
            readable = sorted((lv, x) for x, st, lv in cards if lv is not None)
            adv = [x for x, st, lv in cards if st == "advance"]
            desc = "，".join(f"{i + 1}号={lv}" for i, (x, st, lv) in enumerate(cards)
                            if lv is not None)
            if desc:
                log.info(f"  神器等级：{desc}")
            if not readable:
                if not adv:
                    log.warn("  神器：一件都读不到等级，也没法进阶，停手（界面可能又改了）")
                    break
                log.info("  神器：能读到的等级为空，先把它进阶解锁再读")
                self._select(ui, adv[0])
                if not self._advance(ui):
                    blocked_by_mat = True
                    break
                continue
            live = [(lv, x) for lv, x in readable if x not in no_res]
            if not live:
                log.info("  神器：能读到的神器都「共鸣中，无法升级」，今天升不了")
                break
            low_lv, low_x = live[0]
            second = readable[1][0] if len(readable) > 1 else low_lv + 1
            if second <= low_lv:
                # 2026-11-04 根因修复：1号=2号=56 时 second 也=56，旧逻辑 lv>=second 立刻 break，
                # 于是「连续两轮没升动、收手」——等级永远不变。并列最低时必须至少升 1 级。
                second = low_lv + 1
                try:
                    _ord = L.ARTIFACT_CARDS.index(low_x) + 1
                except ValueError:
                    _ord = 1
                log.info(f"  神器：最低等级并列（{low_lv} 级多件），先升 {_ord} 号到 {second} 级")
            self._select(ui, low_x)
            hint = self._hint_text(ui)
            if "共鸣" in hint:      # 「共鸣」
                log.info(f"  神器：{low_x} 号提示「{hint.strip()[:14]}」→ 这件在共鸣里不能升级，换下一件")
                no_res.add(low_x)
                continue
            before_total = total
            before_lv = ui.screen("art_lv_before")
            # 2026-11-11 第 50 轮实测：选中卡片后该卡的等级数字会被「已选中」高亮盖住，
            # `_level_once()` 读到 None；旧逻辑拿「刚选完那一帧」当 before 去比同一帧，
            # diff 恒 0 → 第一轮就 break，连「升级」按钮都没点过（整天 0 级）。
            # 现在读不到等级时用扫描阶段的 low_lv 当基准继续点，靠「等级变大 / 等级带变化」判成败。
            cur = low_lv
            blind = 0
            suspect = 0
            for _ in range(40):
                st, lv, im = self._level_once(ui)
                if st == "advance":
                    if not self._advance(ui):
                        log.info("  神器：进阶材料不足，换下一件")
                        blocked_by_mat = True
                        break
                    continue
                if lv is not None:
                    cur = lv
                if cur >= second:
                    break
                # 2026-11-07：升级只改等级行那几个数字，整屏 diff 仅 0.007~0.010，
                # 用 expect="change" 会误判空点甚至登记死点——结果由下面的 _level_once 判定。
                ui.press(L.ARTIFACT_BTN, 250, expect="none")
                ui.wait(1.5)
                after = ui.screen("art_up")
                if vision.item_popup(after):
                    ui.press(L.HERO_BLANK, 150, expect="none")
                    ui.wait(0.8)
                    log.info("  神器：升级材料不足，停手")
                    blocked_by_mat = True
                    break
                st2 = self._btn_state(after)
                lv2 = None
                if st2 == "upgrade":
                    lv2 = self._card_level(after, int(getattr(self, "_sel_x", L.ARTIFACT_CARDS[0])))
                if lv2 is not None and lv2 > cur:
                    total += lv2 - cur
                    log.info(f"  神器·升级：{cur} → {lv2}（最低那件）")
                    cur = lv2
                    before_lv = after
                    suspect = 0
                elif vision.diff_ratio(before_lv, after, L.ARTIFACT_CARD_LV_BAND) >= 0.01:
                    # 2026-11-19 假成功审计（audit2 TOP3）：等级带 1% 像素变化只说明
                    # 「那里有东西动了」（高亮切换/数字过渡动画也算），不能当升级证据。
                    # 记为疑似、不落账；下一轮按真实等级结算。
                    suspect += 1
                    before_lv = after
                    log.info(f"  神器·升级：等级带变了但读不到更高的等级（疑似，不计数），"
                             f"下一轮按真实等级结算（第 {suspect} 次）")
                    if suspect >= 2:
                        log.info("  神器：连续 2 次只看到像素变化、读不到等级 → 停手（不虚报升级数）")
                        break
                else:
                    blind += 1
                    log.info(f"  神器：点了没反应（当前 {cur} 级，第 {blind} 次），停手")
                    break
            if total == before_total:
                stalls += 1
                if stalls >= 2:
                    if blocked_by_mat:
                        log.info("  神器：材料不足，本轮就升到这里")
                    else:
                        log.warn("  神器：连续两轮没升动，收手（按钮可能不可用，界面也许又改了）")
                    break
            else:
                stalls = 0
        if total == 0:
            if blocked_by_mat:
                log.info("  神器：本轮等级 +0（材料不足，不是点击失败）")
            else:
                log.warn("  神器：本轮等级 +0（不是点击失败，见上面的等级/材料日志）")
        return total

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not self.enter_team(ui):
            return TaskResult.fail("进不去助阵页")
        if self.open_panel(ui, L.ASSIST_ARTIFACT, "神器") is None:
            self.finish(ctx)
            return TaskResult.fail("进不去神器面板")
        ui.press(L.ARTIFACT_TAB_UP, 220, label="artifact_tab_up", expect="none")  # 升级页签
        ui.wait(1.6)
        total = self._balance(ui)
        if bool(self.p.get("star", True)):
            ui.press(L.ARTIFACT_TABS[0], 220, label="artifact_tab_star", expect="none")  # 升星页签
            ui.wait(1.5)
            # 2026-11-20 审计 MAJOR：升星段原来直接把 _upgrade_loop 的「像素变化次数」
            # 加进 total —— 高亮/数字过渡也会让像素动，等于虚报。现在先读 ★ 个数，
            # 升完再读一次，只认真实星数增量；读不到就按缺证记 0，绝不虚报。
            star_before = self._stars(ui.screen("art_star_ready"))
            guessed = self._upgrade_loop(ui, "神器·升星")
            star_after = self._stars(ui.screen("art_star_done"))
            if star_before is not None and star_after is not None:
                real = max(0, star_after - star_before)
                if real != guessed:
                    log.info(f"  神器·升星：像素判定 {guessed} 次，★ {star_before} → "
                             f"{star_after} 实际只涨 {real} → 按 {real} 记")
                total += real
            else:
                log.info(f"  神器·升星：读不到 ★ 数量（{star_before} → {star_after}），"
                         f"无法核实升星次数 → 本轮按 0 记（不虚报）")
        self.finish(ctx)
        if total <= 0:
            return TaskResult(True, "神器：等级都已最高或材料不足，本次没有升级",
                              {"levels": 0, "noop_ok": True})
        return TaskResult(True, f"神器：等级 +{total}", {"levels": total})


class PetTask(_AssistBase):
    """战宠：圣坛「升阶」→ 培养「升星」。"""

    name = "pet"
    title = "战宠"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not self.enter_team(ui):
            return TaskResult.fail("进不去助阵页")
        if self.open_panel(ui, L.ASSIST_PET, "战宠") is None:
            self.finish(ctx)
            return TaskResult.fail("进不去战宠面板")
        ui.press(L.PET_TABS[0], 220, label="pet_tab_altar", expect="none")   # 圣坛
        ui.wait(1.5)
        total = self._upgrade_loop(ui, "战宠·圣坛升阶")
        ui.press(L.PET_TABS[1], 220, label="pet_tab_train", expect="none")   # 培养
        ui.wait(1.5)
        total += self._upgrade_loop(ui, "战宠·培养升星")
        self.finish(ctx)
        log.info("  兽印/羁绊（镶嵌拼图）未做自动处理")
        if total <= 0:
            return TaskResult(True, "战宠：圣坛/培养都升不动（已满级或材料不足），本次没有升级",
                              {"times": 0, "noop_ok": True})
        return TaskResult(True, f"战宠升级 {total} 次", {"times": total})


class AssistMarkTask(BaseTask):
    """助战徽记（英雄页右上「助战」）：材料够就一直点「升级」。

    2026-10-31 实测：
      - 英雄页右上角「助战」图标 (540,150) → 「助战徽记」面板；
      - 面板中部「5阶27级」的等级数字是绿字（green_loose 可读），底部金色「升级」(360,977)；
      - 每点一次：等级 +1、材料 -80，画面飘 +属性，没有确认框；
      - 材料不足弹「助战徽记不足」道具窗（带「前往>>」按钮，绝不去点），右上角红 X (655,156) 关掉。
    """

    name = "assist_mark"
    title = "助战徽记"
    category = "upgrade"

    def _assist_panel_open(self, im) -> bool:
        """助战徽记面板开没开：认标题「助战徽记」。

        2026-11-08 实测：面板开着但材料不足时「进阶」是灰的，用 is_gold 判面板
        会把「开着的面板」当成「没打开」（assist_mark_401.png 就是这样），
        于是按返回 + 重点入口，落到英雄布阵页。标题 OCR 才是面板本身。
        """
        if not textocr.available():
            # 2026-11-09 假成功审计 M19：认不出 ≠ 已打开。返回 False 让调用方重试/收手，
            # 避免「按返回 + 重点入口」落到英雄布阵页、后面接着点金色按钮。
            log.info("  助战徽记面板判据：OCR 不可用，无法确认面板，按「未打开」处理")
            return False
        try:
            return "助战徽记" in textocr.read_text(im, L.ASSIST_MARK_HEAD_BOX)
        except Exception:      # noqa: BLE001
            log.info("  助战徽记面板判据：OCR 异常，无法确认面板，按「未打开」处理")
            return False

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        limit = int(p.get("times", 10))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        MainCity(ui).tab(L.TAB_HERO)
        ui.wait(1.8)
        ui.press(L.HERO_ASSIST, 250)
        ui.wait(2.0)
        im = ui.screen("assist_mark")
        if not self._assist_panel_open(im):
            log.info("  助战徽记面板没打开，重试一次")
            ui.press(L.BACK, 220, expect="none")
            ui.wait(1.0)
            ui.press(L.HERO_ASSIST, 250, label="hero_assist_retry", expect="none")
            ui.wait(2.0)
            im = ui.screen("assist_mark2")
            if not self._assist_panel_open(im):
                log.warn(f"  助战徽记：点 {L.HERO_ASSIST} 两次都没打开面板，跳过本任务")
                ui.press(L.BACK, 220, expect="none")
                ui.wait(1.0)
                MainCity(ui).ensure()
                return TaskResult.fail("打不开助战徽记面板（英雄页右上入口坐标可能变了）")

        if not vision.is_gold(im, *L.ASSIST_MARK_UP, r=16):
            # 2026-11-08：面板开着但「进阶」是灰的 = 助战技能材料不足（实测 115/500）。
            # 旧逻辑把它当成「面板没打开」，白赔 1 条空点 + 8s 还把页面带到布阵页。
            log.info("  助战徽记：进阶按钮是灰的（助战技能材料不足），本次不升级")
            ui.press(L.BACK, 220, expect="none")
            ui.wait(1.0)
            MainCity(ui).ensure()
            return TaskResult(True, "助战徽记：材料不足，本次没有升级",
                              {"times": 0, "noop_ok": True})

        done = 0
        for _ in range(limit):
            im = ui.screen("mark")
            if vision.item_popup(im):
                ui.press(L.ASSIST_MARK_X, 150, expect="none")
                ui.wait(1.0)
                break
            if not vision.is_gold(im, *L.ASSIST_MARK_UP, r=16):
                log.info("  助战徽记：升级按钮不可用，收手")
                break
            nums = ocr.read_number_loose(im, L.ASSIST_MARK_LV_BOX, mask="green_loose")
            lv = nums[0] if nums else None
            # 2026-11-07 根因修复：这里原来用默认 expect="change"——按钮点下去会弹
            # 「助战徽记不足」道具窗，但变化校验先判成空点、再去 ±8/±16px 补偿点击，
            # 补偿点正好把刚弹出的道具窗点掉 → 下一帧既没弹窗、等级也没变，于是被误判
            # 成「按钮态不可用」收手（实测 13:12 那轮读到 lv=36、0 次升级）。
            # 现在点击不校验，结果只看道具窗和等级数字（与神器一致）。
            ui.press(L.ASSIST_MARK_UP, 250, label="assist_mark_up", expect="none")
            ui.wait(1.9)
            after = ui.screen("mark_after")
            if vision.item_popup(after):
                ui.press(L.ASSIST_MARK_X, 150, expect="none")
                ui.wait(1.0)
                # 材料不足是每天都会遇到的正常状态（0 次不是失败），降成 info
                log.info("  助战徽记：材料不足（弹出道具窗，已关闭），今天就升到这里")
                break
            nums2 = ocr.read_number_loose(after, L.ASSIST_MARK_LV_BOX, mask="green_loose")
            lv2 = nums2[0] if nums2 else None
            # 2026-11-11 实测：等级框会被切位（12 -> 1），单看数值会误判「没升」。
            # 改成「等级文字变了」也算升成功，只有文字一模一样才当没升。
            raw_before = textocr.read_text(im, L.ASSIST_MARK_LV_BOX).strip()
            raw_after = textocr.read_text(after, L.ASSIST_MARK_LV_BOX).strip()
            grew = bool(raw_before and raw_after and raw_before != raw_after)
            if (not grew) and (lv2 is None or (lv is not None and lv2 <= lv)):
                # 真正「点了没反应」才告警（带等级读数，便于复查）
                log.warn(f"  助战徽记：点了「升级」（{L.ASSIST_MARK_UP}）但等级没变"
                         f"（{lv} → {lv2}），收手")
                break
            done += 1
            log.info(f"  助战徽记：升级 ×{done}（{raw_before or lv} → {raw_after or lv2}）")
        ui.press(L.BACK, 220, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        return TaskResult(True, f"助战徽记升级 {done} 次", {"times": done})
