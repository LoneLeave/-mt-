"""页面对象：每个类认识“这个页面长什么样、怎么进来、上面有哪些动作”。

页面对象只依赖 ui（点击/截图/状态）与 layout（坐标），不写业务判断。
"""
from __future__ import annotations

import re
import time

from . import layout as L
from . import log, template as T, textocr, titles, vision
from .ui import UI
from .vision import State


class Page:
    name = "page"

    def claim_badge_icons(self, band, dx: int, dy: int, label: str = "badge",
                          tries: int = 6, gap: float = 1.6) -> int:
        """把 band 里「带红 ! 角标的奖励图标」逐个点掉（点图标本体，不是角标）。

        2026-11-10：主线里程碑 / 巨龙首通 / 阵营通关奖励三处都是这个形态 ——
        达成后图标右上角挂红「!」，点图标本体领奖，角标变绿勾。
        返回领到几个；角标数不再减少就收手。必须先有角标才点（无角标不乱点）。
        """
        n = 0
        prev = None
        for i in range(tries):
            im = self.shot(f"{label}_badge{i}")
            clusters = vision.red_clusters(im, band)
            if not clusters:
                if i == 0:
                    return 0
                break
            cx, cy, px = clusters[0]
            if prev is not None and abs(cx - prev[0]) <= 2 and abs(cy - prev[1]) <= 2:
                log.info(f"  {label}：角标 ({cx},{cy}) 点过之后仍在，停止（可能条件未达成）")
                break
            prev = (cx, cy)
            target = (cx + dx, cy + dy)
            self.ui.press(target, 220, label=f"{label}_claim", expect="none")
            self.ui.wait(gap)
            after = self.shot(f"{label}_after{i}")
            left = vision.red_clusters(after, band)
            got = len(clusters) - len(left)
            if got <= 0 and vision.similar(im, after):
                log.info(f"  {label}：点图标 {target} 后角标没消失（可能条件未达成），停止")
                break
            n += 1
            if not left:
                break
        return n

    def claim_click(self, pos, label: str = "claim") -> bool:
        """点一个「领取」按钮并顺手关掉「获得奖励」浮层。

        2026-11-10 实测（军衔页，帧 `logs/rank_now.png`）：金带检测正常
        （`gold_button_bands` 与 `gold_bands_any` 都是 (571,752,1536)），点下去也真的领到了，
        但 `ui.press(..., expect="change")` 返回 False（浮层遮住时点击点附近像素几乎不变）
        → 旧码 `if not press(...): break` 直接 break，一行都不计数，日志报「没有可领的行」。
        现在改成盲点 + 前后帧对比：画面真的变了才算点到。
        """
        before = self.shot(f"{label}_b")
        self.ui.press(pos, 220, label=label, expect="none")
        self.ui.wait(1.6)
        after = self.shot(f"{label}_a")
        changed = vision.darkened(before, after) or not vision.similar(before, after)
        if changed:
            self.ui.press(L.BLANK, 150, expect="none")
            self.ui.wait(0.9)
        return changed

    def __init__(self, ui: UI):
        self.ui = ui

    def state(self):
        self.ui.set_page(self.name)
        return self.ui.state()

    def shot(self, tag: str = ""):
        self.ui.set_page(self.name)
        return self.ui.screen(f"{self.name}{('_' + tag) if tag else ''}")


# ---------- 主城 ----------

class MainCity(Page):
    name = "city"

    def ensure(self) -> bool:
        return self.ui.ensure_main_city()

    def tab(self, tab: tuple[int, int]) -> None:
        self.ui.ensure_main_city()
        # 页签的内容变化区可能跑到 ±120px 之外，且点已选中的页签本来就不变；
        # 这类导航点击只发不校验（2026-11-06）
        self.ui.press(tab, 250, expect="none")
        self.ui.wait(1.7)

    def open_building(self, pos: tuple[int, int], fallback: tuple[int, int] | None = None) -> None:
        """点建筑入口；若画面没变化且给了备用点，再点备用点。"""
        self.ui.ensure_main_city()
        before = self.ui.screen(f"{self.name}_before")
        self.ui.press(pos, 250)
        self.ui.wait(2.0)
        after = self.ui.screen(f"{self.name}_after")
        if fallback and vision.similar(before, after):
            self.ui.press(fallback, 250)
            self.ui.wait(1.8)

    # 主城左侧图标列的候选点（x≈70，间距约 55px）。
    # 2026-11-15：整列上移，日常从 (85,895) 变成 (70,795)——旧点现在点的是「邮件」，
    # claim 任务因此「进不去日常页」两次全局自愈都没救回来（_usrgr 20:19:08 FAIL）。
    DAILY_ICONS = ((70, 795), (85, 895), (70, 850), (70, 740), (70, 905))

    def open_daily(self) -> "DailyPage":
        self.ui.ensure_main_city()
        page = DailyPage(self.ui)
        for i, pos in enumerate(self.DAILY_ICONS):
            self.ui.press(pos, 250, expect="none", label="city_daily")
            self.ui.wait(1.6)
            if page.at_daily():
                if i:
                    log.info(f"  日常：主城图标实测可用点 {pos}（配置 {L.ICON_DAILY}）")
                return page
            self.ui.press(L.BACK, 250, expect="none")
            self.ui.wait(0.9)
            self.ui.ensure_main_city()
        log.warn("  日常：主城左侧图标逐个试过，都没点开「日常任务」页")
        return page

    def open_forge(self) -> "ForgePage":
        MainCity(self.ui).open_building(L.BLD_FORGE, fallback=L.BLD_FORGE_OLD)
        return ForgePage(self.ui)

    def open_shop(self) -> "ShopPage":
        MainCity(self.ui).open_building(L.BLD_SHOP)
        return ShopPage(self.ui)

    def open_rank(self) -> "RankPage":
        self.ui.ensure_main_city()
        self.ui.press(L.ICON_RANK_BAR, 250)
        self.ui.wait(2.0)
        return RankPage(self.ui)

    def open_trials(self) -> "TrialsHub":
        self.ui.ensure_main_city()
        self.ui.press(L.TAB_TRIAL, 250, expect="none")
        self.ui.wait(1.8)
        return TrialsHub(self.ui)

    def open_guild(self) -> "GuildPage":
        self.tab(L.TAB_GUILD)
        return GuildPage(self.ui)

    def open_campaign(self) -> "CampaignPage":
        self.tab(L.TAB_CAMPAIGN)
        return CampaignPage(self.ui)


# ---------- 历练 hub ----------

class TrialsHub(Page):
    name = "hub"

    def to_top(self) -> None:
        """滚到列表顶部（日常副本/塔/传奇/邪能 在顶部位置）。"""
        for _ in range(3):
            self.ui.dev.scroll_down(360, 250, 1000, 500)   # 内容往下 = 看顶部
            self.ui.wait(0.5)

    def scroll_down_once(self) -> None:
        for _ in range(2):
            self.ui.dev.scroll_up(360, 1000, 250, 600)     # 内容往上 = 看底部
            self.ui.wait(0.5)

    def to_bottom(self, tries: int = 6) -> None:
        """滚到列表底部（滚动量随玩法增加会变，不能按固定格数）。

        2026-10-29 起列表新增了巨龙牢窟/阵营挑战/罪魂之域，时光之树被挤到最底部。
        """
        prev = None
        for _ in range(tries):
            self.ui.dev.scroll_up(360, 1000, 250, 600)
            self.ui.wait(0.6)
            im = self.ui.screen("hub_bottom")
            if prev is not None and vision.similar(prev, im, tol=20, max_diff=0.05):
                return
            prev = im

    def _at_target(self, key: str, tries: int = 1, gap: float = 0.6) -> bool:
        """已经在目标玩法页上吗？dungeon 没有标题模板，用「离开历练列表」代替。"""
        for i in range(max(1, tries)):
            im = self.ui.screen(f"hub_{key}_at")
            if key in ("tower", "legend", "tree", "demon"):
                st = vision.classify(im)
                if st in (State.BATTLE, State.DEPLOY):
                    # 2026-11-08：游戏侧还挂着上一轮的战斗/布阵时（邪能「自动挑战」会一直打），
                    # 标题模板当然认不到；旧逻辑判「没进到页面」-> 回主城重进 -> 又被战斗顶回来，
                    # 最后 FAIL「历练列表里没找到入口」（实测 140s 空转）。战斗/布阵就说明
                    # 我们确实已经在对应玩法里，直接算到达，交给主循环等它打完。
                    log.info(f"  历练：画面是 {st.value}（战斗/布阵中），当作已经在「{key}」里")
                    return True
            if key == "dungeon":
                # dungeon 没有标题模板；但「不在历练列表」也包含主城/英雄页，
                # 所以还要排除主城（否则任务开局就以为自己已经在副本里）。
                ok = not vision.trials_hub(im) and not vision.main_city(im)
            else:
                ok = titles.on_page(im, key)
            if ok:
                return True
            if i + 1 < tries:
                self.ui.wait(gap)
        return False

    def _card_pos(self, im, key: str):
        """在历练列表帧上找目标卡片标题的中心点；找不到返回 None。

        2026-11-08：先试卡片标题模板（塔/传奇/邪能/树这四张是当天从真帧裁的），
        模板命中就给坐标，比 OCR 稳；模板没配或没命中再退回 OCR 认文字。
        """
        tile = L.HUB_TILES.get(key)
        if tile:
            try:
                m = T.VI.find(im, tile, L.HUB_TILE_THRESHOLD, roi=L.HUB_LIST_ROI)
            except Exception as e:  # noqa: BLE001
                log.warn(f"  历练：卡片模板 {tile} 匹配失败（{e}），改用 OCR")
                m = None
            if m is not None:
                log.info(f"  历练：卡片模板「{tile}」在 {m.center}（{m.score:.2f}）")
                return m.center
        names = L.HUB_TITLES.get(key)
        if not names or not textocr.available():
            return None
        try:
            lines = textocr.read_lines(im, L.HUB_LIST_ROI, min_score=0.5)
        except Exception as e:  # noqa: BLE001
            log.warn(f"  历练：OCR 读列表失败（{e}），改用固定坐标")
            return None
        limit = max(len(n) for n in names) + 6
        for text, center, _bb, score in lines:
            body = text.replace(" ", "")
            # 2026-11-08 02:54：结算页那行「当前战斗：守护者塔第960层」曾被子串命中，
            # 结果在 (360,423) 乱点。整行必须和卡片标题差不多长才算卡片。
            if len(body) <= limit and any(n in body for n in names):
                log.info(f"  历练：卡片「{text}」在 {center}（OCR {score:.2f}）")
                return center
        return None

    def enter(self, key: str) -> bool:
        """key: dungeon/tower/legend/demon/tree

        先确认自己真的在「历练」页签上：直接在主城里按塔的坐标不会打开任何东西，
        旧逻辑会因此每 7 秒无限重试（2026-10-29 爬塔卡死的根因）。

        2026-11-08：点完不再无条件 return True。塔/传奇/邪能/树没有卡片模板，旧版只能按
        固定坐标点；列表可滚动、卡片位置不固定，坐标偏几像素就点空（实测 (270,600)
        diff=0.000、(270,592) 才命中），而旧版照样往下跑 → 整个任务在列表页空转。
        现在先 OCR 认卡片标题（最稳），找不到再退回固定坐标，点完一律轮询复核标题模板。
        """
        pos_map = {
            "dungeon": L.HUB_DUNGEON,
            "tower": L.HUB_TOWER,
            "legend": L.HUB_LEGEND,
            "demon": L.HUB_DEMON,
        }
        if key == "tree":
            pos = L.HUB_TREE
        elif key in pos_map:
            pos = pos_map[key]
        else:
            return False
        if self._at_target(key):
            return True
        for attempt in range(3):
            if not vision.trials_hub(self.ui.screen("hub_open")):
                MainCity(self.ui).tab(L.TAB_TRIAL)
                self.ui.wait(1.2)
            if key == "tree":
                self.to_bottom()
            else:
                self.to_top()
            # 一屏一屏往下找卡片（最多 5 屏）；OCR 认不出来时第一屏就用固定坐标兜底
            if not self._click_card(key, pos, probe_fixed=(attempt == 0)):
                log.warn(f"  历练：列表里没找到「{key}」的卡片（第 {attempt + 1}/3 次）")
                continue
            if self._at_target(key, tries=8, gap=0.6):
                return True
            log.warn(f"  历练：点了「{key}」卡片但没进到页面（第 {attempt + 1}/3 次）")
        return False

    def _click_card(self, key: str, fixed, probe_fixed: bool = False) -> bool:
        """在当前列表页找卡片并点；找不到就往下翻，最多 5 屏。"""
        for page in range(5):
            im = self.ui.screen(f"hub_card_{key}")
            if not vision.trials_hub(im):
                # 不在历练列表（战斗/结算/主城）时不要认卡片：OCR 会把界面文字当标题
                log.info(f"  历练：当前不在历练列表（{key}），放弃认卡片")
                return False
            c = self._card_pos(im, key)
            if c is not None:
                # 卡片中心可能压字，只发不校验（补偿点会把列表滚走）
                self.ui.press(c, 250, label=f"hub_card:{key}", expect="none")
                self.ui.wait(1.6)
                return True
            if probe_fixed and page == 0:
                # OCR 没命中时（缺字体/被遮挡）用固定坐标试一次
                self.ui.press(fixed, 250, label=f"hub_{key}", expect="none")
                self.ui.wait(1.6)
                return True
            self.ui.dev.scroll_up(360, 1000, 250, 600)    # 内容往上 = 看后面的卡片
            self.ui.wait(0.6)
        return False

    def enter_tile(self, tile: str, header: str, tries: int = 6,
                   resumed=None) -> bool:
        """按卡片标题模板进玩法（卡片位置随滚动变化，不能写死坐标）。

        ``tile`` 是历练页的卡片模板，``header`` 是玩法页顶部标题模板。
        有的玩法（阵营挑战）进去会直接续上一场没打完的战斗，``resumed(im)``
        返回 True 时也算进成功，避免在战斗中继续滚动找卡片。
        """
        if T.VI.find(self.ui.screen("tile_now"), header, 0.88):
            return True
        if not vision.trials_hub(self.ui.screen("hub_open")):
            MainCity(self.ui).tab(L.TAB_TRIAL)
        for _ in range(2):
            self.ui.dev.scroll_down(360, 250, 1000, 500)
            self.ui.wait(0.5)
        for _ in range(tries):
            im = self.ui.screen("tile_hub")
            m = T.VI.find(im, tile, 0.88)
            if m:
                self.ui.press(m.center, 250)
                self.ui.wait(3.2)
                after = self.ui.screen("tile_after")
                if T.VI.find(after, header, 0.88):
                    return True
                if resumed is not None and resumed(after):
                    return True
                if not vision.trials_hub(after):
                    # 已经离开历练列表（页面/战斗还在加载），别再滚动列表乱点
                    return True
            self.ui.dev.scroll_up(360, 1000, 250, 600)
            self.ui.wait(0.9)
        log.warn(f"  历练列表里没找到 {tile}")
        return False


# ---------- 战斗类 ----------

class BattleResult(Page):
    name = "result"

    def read(self) -> dict:
        st = self.state()
        return {
            "state": st,
            "win": st in (State.RESULT_TOWER, State.RESULT_TREE, State.RESULT_LEGEND,
                          State.RESULT_GENERIC),
            "next": st == State.RESULT_TOWER,
            "final": st == State.RESULT_TREE or st == State.RESULT_GENERIC,
        }

    def next_floor(self) -> None:
        self.ui.press(L.TOWER_RESULT_NEXT, 220)
        self.ui.wait(2.2)

    def next_tree(self) -> None:
        self.ui.press(L.TREE_RESULT_NEXT, 220)
        self.ui.wait(2.2)

    def ok(self, which: str = "tower") -> None:
        pos = {
            "tower": L.TOWER_RESULT_OK,
            "tree": L.TREE_RESULT_OK,
            "tree_final": L.TREE_RESULT_OK_FINAL,
            "legend": L.LEGEND_RESULT_OK,
        }.get(which, (370, 1130))
        self.ui.press(pos, 220)
        self.ui.wait(1.9)


class FightMixin:
    """布阵 → 战斗 → 跳过 的通用动作。"""

    def deploy_and_skip(self, skip_delay: float = 8.0) -> None:
        ui = self.ui  # type: ignore[attr-defined]
        im = ui.screen("deploy")
        if vision.is_green(im, *L.DEPLOY, r=18):
            # 2026-11-04 实测：这枚绿色按钮点了 diff=0（游戏已自动布阵），默认校验会
            # 触发 4 个补偿点、每次白等 ~20s；单次点击即可，真正开打靠下面的「战斗」。
            ui.press(L.DEPLOY, 200, label="deploy", expect="none")
            ui.wait(1.0)
            im = ui.screen("deploy2")
        if vision.classify(im) == State.BATTLE:
            # 2026-11-08 实机（logs\_full6_153708.log 15:57:27）：树有时点了「上阵」
            # 或进页就已经在打，此时再点 (540,1230)「战斗」是空点 —— 默认校验会触发
            # 4 个补偿点、白等 8 秒还记一条空点。已在战斗态就别点，直接去跳过。
            ui.wait(1.0)
        else:
            ui.press(L.FIGHT, 200, label="fight", expect="none")
        # 2026-11-08：旧实现是「死等 skip_delay 秒 → 只点一次跳过」——战斗早就开始了，
        # 前 7~8 秒纯属白等；只点一次的话，没点中就一直等到战斗自然结束（45s+）。
        # 现在每 1.2s 抓一帧：还在战斗就再点一次「跳过」（模板定位 + 阈值 0.60，
        # 未命中不盲点；暂停键在 y≈775、跳过键在 y≈899，ROI 已把两者分开），
        # 一离开战斗态立刻返回。
        deadline = time.time() + max(2.5, skip_delay)
        while time.time() < deadline:
            ui.wait(1.2)
            im2 = ui.screen("skip_probe")
            if vision.classify(im2) != State.BATTLE:
                break
            ui.battle_skip(im2, quiet=True)
        ui.wait(1.0)


class TowerPage(Page, FightMixin):
    name = "tower"

    def at_page(self, im=None) -> bool:
        return titles.on_page(im or self.shot("tower_at"), "tower")

    def busy(self, im=None) -> bool:
        """是不是还在塔的战斗/结算里（含「点击空白处关闭」提示层）。

        2026-11-08 02:45 实测：塔战失败先弹提示层（classify=UNKNOWN，约 3s），
        再出完整结算页。这期间任何「重进塔页」都是有害的 —— 游戏会把还在
        收尾的战斗拉回前台，入口判定必然失败。
        """
        im = im if im is not None else self.shot("tower_busy")
        try:
            if "守护者塔" in textocr.read_text(im, L.TOWER_BATTLE_TOP):
                return True
            if "点击空白处关闭" in textocr.read_text(im, L.TOWER_BLANK_HINT):
                return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def enter(self) -> bool:
        if self.busy():
            log.info("  塔：当前已经在塔的战斗/结算里，直接继续（不重进）")
            return True
        return TrialsHub(self.ui).enter("tower")

    def challenge(self) -> bool:
        """点「挑战」并确认进了布阵页（2026-11-08 与传奇/树对齐）。

        次数为 0 时按钮仍是金色，点了只飘一行提示；旧版直接 return True，
        塔任务会接着等 1.5s×N 个空帧。
        """
        im = self.shot("hub")
        if not vision.is_gold(im, *L.TOWER_GO, r=18):
            return False
        self.ui.press(L.TOWER_GO, 250)
        self.ui.wait(2.5)
        return vision.is_green(self.shot("tower_dep"), *L.DEPLOY, r=18)


class LegendPage(Page, FightMixin):
    name = "legend"

    def at_page(self, im=None) -> bool:
        return titles.on_page(im or self.shot("legend_at"), "legend")

    def enter(self) -> bool:
        return TrialsHub(self.ui).enter("legend")

    def attempts(self, im=None):
        """底部「剩余挑战次数：N」，读不到返回 None。

        2026-11-08 真帧（logs/screens/hub_legend_at_1985.png）：页底写着
        「剩余挑战次数：0」，可「挑战」按钮**仍然是金色**——点下去只飘一行 toast，
        页面不动，白赔一次 diff 校验 + 4 个补偿点（约 8s）。
        """
        from . import textocr

        im = im or self.shot("legend_cnt")
        if not textocr.available():
            return None
        return textocr.read_remain(textocr.read_text(im, L.LEGEND_ATTEMPT_TEXT),
                                   key="剩余挑战次数")

    def challenge(self) -> bool:
        """点「挑战」并确认进了布阵页；次数为 0 时按钮仍是金色，只会飘一行提示。"""
        im = self.shot("hub")
        if not vision.is_gold(im, *L.LEGEND_GO, r=18):
            return False
        self.ui.press(L.LEGEND_GO, 250)
        self.ui.wait(2.5)
        return vision.is_green(self.shot("legend_dep"), *L.DEPLOY, r=18)


class TreePage(Page, FightMixin):
    name = "tree"

    def at_page(self, im=None) -> bool:
        return titles.on_page(im or self.shot("tree_at"), "tree")

    def enter(self) -> bool:
        return TrialsHub(self.ui).enter("tree")

    def challenge(self) -> bool:
        """点「挑战」并确认进了布阵页；次数为 0 时只会飘一行提示。"""
        im = self.shot("map")
        if not vision.is_gold(im, *L.TREE_GO, r=18):
            return False
        self.ui.press(L.TREE_GO, 350)
        self.ui.wait(2.6)
        return vision.is_green(self.shot("tree_dep"), *L.DEPLOY, r=18)

    def leave(self) -> None:
        self.ui.press(L.BACK_TREE, 250, expect="none")
        self.ui.wait(1.8)

    # ---- 奖励（2026-10-30 实测） ----
    def claim_rewards(self) -> int:
        """地图右下「奖励」→ 每日奖励面板里的金色「领取」→ 关面板。"""
        n = 0
        # 2026-11-09：地图上不一定有「奖励」这个按钮（翻章/结算后的地图状态里它会消失）。
        # 原来是默认变化校验 + 4 个补偿点，点空一次白烧 8s 并刷两条空点告警。
        self.ui.press(L.TREE_REWARD_BTN, 250, label="tree_reward", expect="none")
        self.ui.wait(2.0)
        im = self.shot("reward")
        panel = vision.is_gold(im, *L.TREE_REWARD_CLAIM, r=18) or bool(
            [p for p in self.ui._find_close_buttons(im) if p[0] >= 600 and 120 <= p[1] <= 300])
        if not panel:
            log.info("  时光之树：地图上没有可打开的「奖励」面板（这张地图不显示该按钮），跳过领奖")
            return 0
        # 2026-11-10：先看底部是不是已有「已领取」印章（绿色），有就是今天领过了。
        if textocr.available():
            stamp = textocr.read_text(im, L.TREE_REWARD_STAMP_BOX)
            if any(k in stamp for k in L.TREE_REWARD_STAMP_KEYS):
                log.info("  时光之树：每日奖励面板写着「已领取」，今天已经领过了")
                self.ui.press(L.TREE_REWARD_CLOSE, 200, expect="none")
                self.ui.wait(1.0)
                return 0
        # 领取钮在底部条里（面板标题栏的浅金横幅不是按钮，所以限 y 858~940）
        bands = vision.gold_bands_any(im, L.TREE_REWARD_BTN_ROW)
        if bands and bands[0][1] >= L.TREE_REWARD_BTN_ROW[1]:
            pos = (bands[0][0], bands[0][1])
            self.ui.press(pos, 220, label="tree_daily_claim", expect="none")
            self.ui.wait(1.9)
            after = self.shot("reward_after")
            ok = False
            if textocr.available():
                ok = any(k in textocr.read_text(after, L.TREE_REWARD_STAMP_BOX)
                         for k in L.TREE_REWARD_STAMP_KEYS)
            if not ok:
                ok = vision.similar(im, after) is False
            if ok:
                n += 1
                log.info(f"  时光之树：每日奖励领取 ×{n}（点 {pos}）")
            else:
                log.info(f"  时光之树：点 {pos} 后没看到「已领取」印章，画面也没变（没领到），不计入")
            self.ui.press(L.BLANK, 150, expect="none")
            self.ui.wait(0.8)
        else:
            log.info("  时光之树：每日奖励面板底部没有金色的「领取」钮（今天不可领），跳过")
        # 面板可能已被上一步「点空白」关掉：关闭按钮点空不该算失败
        self.ui.press(L.TREE_REWARD_CLOSE, 200, expect="none")
        self.ui.wait(1.0)
        return n

    # ---- 补星面板（章节 / 补星 两个页签，2026-10-30 用户指正后重做） ----
    def chapter_panel_open(self, im=None) -> bool:
        """「章节 / 补星」面板是否打开：右上角红 X + 底部两个页签。"""
        im = im or self.shot("chap")
        return bool([p for p in self.ui._find_close_buttons(im)
                     if p[0] >= 600 and 120 <= p[1] <= 260])

    def open_star_panel(self) -> bool:
        """地图右下「章节」→ 面板 → 点「补星」页签。"""
        if not self.chapter_panel_open():
            self.ui.press(L.TREE_CHAPTER_BTN, 250)
            self.ui.wait(1.8)
        if not self.chapter_panel_open():
            return False
        self.ui.press(L.TREE_TAB_STAR, 220, label="tree_tab_star", expect="none")
        self.ui.wait(1.5)
        return self.chapter_panel_open()

    def close_chapter_panel(self) -> None:
        im = self.shot("chap_close")
        for cx, cy in self.ui._find_close_buttons(im):
            if cx >= 600 and 120 <= cy <= 260:
                self.ui.press((int(cx), int(cy)), 160, expect="none")
                self.ui.wait(1.0)
                return
        self.ui.press((655, 157), 160, expect="none")
        self.ui.wait(1.0)

    def find_star_go(self, im=None):
        """补星列表里第一个金色「前往」按钮（x≈545，行高约 72）。"""
        im = im or self.shot("star_list")
        x = L.TREE_STAR_GO_X
        for y in range(L.TREE_STAR_GO_SCAN[0], L.TREE_STAR_GO_SCAN[1], 4):
            if all(vision.is_gold(im, x + dx, y, r=12) for dx in (-30, 0, 30)):
                return (x, y + 18)
        return None

    # ---- 补星（2026-10-30 实测） ----
    @staticmethod
    def star_rows(im) -> list[tuple[int, int, int]]:
        """在地图上找「星星行」，返回 [(节点x, 节点y, 亮着的星数)]。

        星星是节点下方一排 3 颗小星，金色 = 已点亮，暗灰 = 没打满/未通关。
        只统计金色星：1~2 颗 = 可补星，3 颗 = 满星，0 颗 = 「新」节点（不碰）。
        做法：金色像素连通域 → 按 y 分组 → 同一行里按 x 间距拼成星星行。
        """
        x0, y0, x1, y1 = L.TREE_MAP_STARS
        mask: set[tuple[int, int]] = set()
        for y in range(y0, y1, 2):
            for x in range(x0, x1, 2):
                R, G, B = im.getpixel((x, y))
                if R > 200 and G > 160 and B < 150 and (R - B) > 80:
                    mask.add((x, y))
        comps = []
        while mask:
            seed = mask.pop()
            q = [seed]
            xs = [seed[0]]
            ys = [seed[1]]
            while q:
                cx, cy = q.pop()
                for dx in (-2, 0, 2):
                    for dy in (-2, 0, 2):
                        p = (cx + dx, cy + dy)
                        if p in mask:
                            mask.discard(p)
                            q.append(p)
                            xs.append(p[0])
                            ys.append(p[1])
            comps.append((min(xs), min(ys), max(xs), max(ys), len(xs)))
        stars = [c for c in comps
                 if 3 <= c[2] - c[0] <= 18 and 3 <= c[3] - c[1] <= 18 and c[4] >= 6]
        stars.sort(key=lambda c: (c[1], c[0]))
        rows: list[dict] = []
        for c in stars:
            cy = (c[1] + c[3]) // 2
            cx = (c[0] + c[2]) // 2
            for r in rows:
                if abs(r["y"] - cy) <= 8 and cx - r["xs"][-1] <= 60:
                    r["xs"].append(cx)
                    r["y"] = (r["y"] + cy) // 2
                    break
            else:
                rows.append({"y": cy, "xs": [cx]})
        # 星星行在节点正下方约 40px（实测 43-4：星行 y≈585，节点中心 y≈545）
        return [(sum(r["xs"]) // len(r["xs"]), r["y"] - 40, len(r["xs"]))
                for r in rows if 1 <= len(r["xs"]) <= 3]


class DemonPage(Page):
    """邪能神殿（2026-10-29 改版后）。

    页面结构：顶部章节/进度、Boss 立绘、当前增益格子、底部大按钮（挑战 / 选择加成）。
    点挑战进布阵页，打完一场结算「下一关」可直接连打，章节打满 10 关后弹「选择加成」。
    """

    name = "demon"

    def at_page(self, im=None) -> bool:
        return titles.on_page(im or self.shot("demon_at"), "demon")

    def busy(self, im=None) -> bool:
        """是不是还在邪能的战斗/布阵里（这时绝不能回主城重进）。

        2026-11-08 06:21 实测：布阵页点「战斗」后画面还会停在 deploy 一帧再进
        BATTLE；这期间回主城重进必然失败（游戏会把还在跑的战斗拉回前台）。
        """
        im = im if im is not None else self.shot("demon_busy")
        return vision.classify(im) in (State.BATTLE, State.DEPLOY)

    def enter(self) -> bool:
        if self.busy():
            # 2026-11-08：已经在打邪能了，别再重进（重进必然失败，白赔 3 次点击）。
            log.info("  邪能神殿：当前已经在邪能的战斗/布阵里，直接继续（不重进）")
            return True
        return TrialsHub(self.ui).enter("demon")

    def press_main(self) -> str:
        """点底部大按钮（一键扫荡 / 选择加成 / 挑战都出现在这个位置）。

        返回 'deploy'（进了布阵页）/ 'battle'（直接开打）/ 'same'（按了但还在本页）/
        'none'（没有金色按钮）。每日第一次的一键扫荡 + 符文自动选择就是靠连续按压推进的。
        """
        im = self.shot("demon")
        pts = [pt for pt in (L.DEMON_CHALLENGE, L.DEMON_CHALLENGE_ALT)
               if vision.is_gold(im, *pt, r=18)]
        if not pts:
            # 2026-11-08：实测金带在 y≈1142（比 DEMON_CHALLENGE 还高），固定点会落空；
            # 这里用整条底部区域扫金带兜底。质心必须再用 is_gold 复核：
            # 战斗帧里 (253,1056) 这种「像金色的装饰」也会成带，点了是纯空点。
            pt = vision.gold_band_point(im, L.DEMON_BUTTON_ZONE)
            if pt:
                pts = [pt]
                log.info(f"  邪能神殿：固定点没扫到金按钮，改用金带兜底 {pts[0]}")
            elif vision.gold_button_bands(im, L.DEMON_BUTTON_ZONE):
                log.info("  邪能神殿：金带质心实测不是金色（装饰），不当按钮点")
        for pt in pts:
            self.ui.press(pt, 250)
            self.ui.wait(2.4)
            after = self.shot("demon_after")
            if vision.is_green(after, *L.DEPLOY, r=18):
                return "deploy"
            if vision.classify(after) == State.BATTLE:
                return "battle"
            return "same"
        return "none"

    def reward_popup(self, im) -> bool:
        """「获得奖励」浮层（快速挑战瞬间结算后弹出的那层）。

        判据取浮层底部的「点击空白处关闭」——不依赖标题，避免和「通关奖励」列表混淆。
        """
        if not textocr.available():
            log.info("  邪能神殿：OCR 不可用，「奖励浮层」判据本轮退化（按没有浮层处理）")
            return False
        try:
            return "点击空白处关闭" in textocr.read_text(im, L.DEMON_REWARD_HINT)
        except Exception as e:                      # OCR 失败就当没这层
            log.warn(f"  邪能神殿：奖励浮层判据 OCR 失败（{e}）")
            return False

    def maybe_reward_popup(self, im) -> bool:
        """便宜的闸门 + 判据：浮层把整页压暗，先看 (360,300) 再决定要不要 OCR。

        实测：有浮层（84~92, 77~83, 72~74），正常邪能页（228~232, 174~177, 149~153）。
        """
        if max(vision.avg(im, 360, 300, r=8)) >= 140:
            return False
        return self.reward_popup(im)

    def dismiss_rewards(self, im=None) -> bool:
        """点空白关掉「获得奖励」浮层（im 可复用调用方已抓好的帧）。"""
        if im is None:
            im = self.shot("demon_reward")
        if not self.reward_popup(im):
            return False
        self.ui.press(L.BLANK, 200, expect="none")
        self.ui.wait(1.4)
        return True

    def buff_dialog(self, im) -> bool:
        """「选择加成」弹窗：右上角红 X + 底部金色「确定」。"""
        if not vision.is_gold(im, *L.DEMON_BUFF_OK, r=16):
            return False
        return any(cx >= 620 and cy <= 260 for cx, cy in self.ui._find_close_buttons(im))

    def pick_buff(self) -> bool:
        """选第 1 个加成并确定（剩余可选次数多于 1 时多调用几次）。"""
        im = self.shot("buff")
        if not self.buff_dialog(im):
            return False
        self.ui.press(L.DEMON_BUFF_OPTION1, 200)
        self.ui.wait(0.6)
        self.ui.press(L.DEMON_BUFF_OK, 220)
        self.ui.wait(1.6)
        return True


class DragonPage(Page):
    """巨龙牢窟（2026-10-29 实测）。

    页面：顶部标题，左边首通奖励/战斗记录，中间龙种（灾变之翼/奥术主宰/翡翠噩梦，
    按星期轮换），下面是难度档位行（4阶困难=已通关可扫荡、4阶噩梦=可挑战），
    右下角「挑战次数」。只点档位行右侧的金色「挑战」，不点「扫荡」。
    次数为 0 时点挑战只弹提示框（带红 X），关掉就收手。
    """

    name = "dragon"
    HEADER = "标题_巨龙牢窟.png"
    TILE = "历练_巨龙牢窟.png"
    CHALLENGE = "挑战_巨龙牢窟.png"
    REWARD = "巨龙_获得奖励.png"

    def at_page(self, im=None) -> bool:
        return T.VI.find(im or self.shot(), self.HEADER, 0.88) is not None

    def reward_popup(self, im=None) -> bool:
        """胜利后的「获得奖励」黑底弹窗：标题在，但「挑战」按钮被压暗认不出来。

        实测它会一直挂着（不会自动消失），必须点面板外的暗色区域关掉。
        """
        return T.VI.find(im or self.shot(), self.REWARD, 0.85) is not None

    def dismiss_rewards(self, tries: int = 3) -> bool:
        """点空白关掉「获得奖励」浮层。

        2026-11-09 付费审计 M1：旧版对 ((386,1069),(360,1150),(60,600)) 连点 4 轮、用默认
        `expect="change"`（会触发 ±8/±16 坐标补偿，一次点击最多 5 击），且不排除金色按钮
        ——(360,1150) 正落在底部按钮排上。现在：`expect="none"` 不补偿、点前先看该点是不是
        金色（金色=付费钮，跳过）、最多 3 轮，关不掉就说明白。
        """
        if not self.reward_popup():
            return True
        blanks = ((386, 1069), (360, 1150), (60, 600), (620, 950))
        for _ in range(max(1, tries)):
            for pos in blanks:
                im = self.shot("dragon_reward_blank")
                if vision.is_gold(im, pos[0], pos[1], r=16):
                    continue
                self.ui.press(pos, 200, label="dragon_reward_blank", expect="none")
                self.ui.wait(1.2)
                if not self.reward_popup():
                    return True
        ok = not self.reward_popup()
        if not ok:
            log.info("  巨龙牢窟：奖励浮层点了 3 轮空白仍没关掉，收手（不乱点按钮）")
        return ok

    def claim_progress(self) -> int:
        """领取「进度奖励」面板里已达成的通关奖励（2026-11-03 修复 #9）。

        实测：右侧「进度奖励」按钮 (625,1025) 打开「通关奖励」面板，奖励行右侧
        状态列 x≈500，达到关卡就变成金色「领取」，未达成是灰字。旧版从不进这个面板，
        所以首通/进度奖励一直没领。
        """
        if not self.at_page():
            return 0
        self.ui.press(L.DRAGON_PROGRESS_BTN, 250)
        self.ui.wait(1.8)
        # 2026-11-10：旧版用严格金带 gold_button_bands 找「领取」，但该面板的奖励是
        # 褐色图标+钻石图案，严格档恒返回 []（今日每轮都静默 0）。真帧里达成态是
        # 图标右上角挂红「!」（(605,382) → 图标中心 (566,424)），改成角标连通块。
        n = self.claim_badge_icons(L.DRAGON_REWARD_BOX, L.DRAGON_BADGE_DX,
                                   L.DRAGON_BADGE_DY, label="dragon_reward", tries=6)
        self.ui.press(L.DRAGON_REWARD_CLOSE, 200, expect="none")
        self.ui.wait(1.1)
        return n

    def buy_attempt(self, ui=None):
        """点档位行金色「挑战」看是否弹出购买框；返回 (有没有弹窗, 花费)。

        2026-11-11 实测（次数 0 时）：点「挑战」(575,778) 弹出预制购买框
        「是否花费 100（拥有 1518) 购买1次挑战次数？今日可购买次数（1/2）」；
        底部那行「挑战次数+2」(y=1230) 四个 x 坐标点下去画面完全不变，**不是按钮**。
        """
        ui = ui or self.ui
        im = self.shot("drg_buy_probe")
        pos = (575, 778)
        bands = vision.gold_bands_any(im, (500, 700, 700, 900))
        if bands:
            pos = (bands[0][0], bands[0][1])
        ui.press(pos, 220, label="drg_buy_challenge", expect="none")
        ui.wait(1.5)
        im2 = self.shot("drg_buy_dlg")
        if not vision.modal_dim(im2):
            return False, 0
        txt = textocr.read_text(im2, L.DRAGON_BUY_DLG_BOX).replace(" ", "")
        m = re.search(r"花费(\d+)", txt)
        cost = int(m.group(1)) if m else 0
        if "购买1次挑战次数" not in txt and cost <= 0:
            return False, 0
        return True, cost

    def close_buy_dialog(self) -> None:
        """点「取消」关掉购买框（绝不点「最大」）。"""
        self.ui.press(L.DRAGON_BUY_CANCEL, 200, label="drg_buy_cancel", expect="none")
        self.ui.wait(1.0)

    def attempts(self, im=None):
        """底部「挑战次数：N」，读不到返回 None。

        2026-11-07：次数为 0 时「挑战」按钮仍是金色、点下去只飘一行 toast
        （「今日购买次数已用完」）页面不变，任务只能靠兜底判据收手；先读出来
        就能直接说明原因、少点一次空点。
        """
        from . import textocr
        im = im or self.shot("dragon_cnt")
        text = textocr.read_text(im, L.DRAGON_ATTEMPT_TEXT)
        return textocr.read_remain(text, key="挑战次数")

    def enter(self) -> bool:
        if self.at_page():
            return True
        if not TrialsHub(self.ui).enter_tile(self.TILE, self.HEADER):
            return False
        for _ in range(6):                   # 页面可能还在加载
            if self.at_page():
                return True
            self.ui.wait(0.9)
        return False

    def challenge(self) -> str:
        """点可挑战档位的「挑战」。返回 deploy / popup / none。"""
        im = self.shot("page")
        if self.reward_popup(im):
            self.dismiss_rewards()
            im = self.shot("page2")
        m = T.VI.find(im, self.CHALLENGE, L.DRAGON_CHALLENGE_THRESHOLD,
                      roi=L.DRAGON_CHALLENGE_ROI)
        if not m:
            return "none"
        # 2026-11-04：次数为 0 时按钮仍是金色、点下去只飘提示（diff=0），默认校验白等 20s。
        # 单次点击，靠下面的 after 截图判「布阵/弹窗/无反应」。
        self.ui.press(m.center, 250, label="dragon_challenge", expect="none")
        self.ui.wait(2.6)
        after = self.shot("after")
        if vision.is_green(after, *L.DEPLOY, r=18):
            return "deploy"
        if vision.classify(after) in (State.DIALOG, State.MAIN_CITY_DIM):
            self.ui.close_popup(after)
            return "popup"
        # 次数为 0 时「挑战」仍是金色，点下去只飘一行提示，页面不变；
        # 不要去点右上角的红色像素——龙立绘的红色翅膀就在那一片，会误判成关闭钮。
        pop = T.VI.find(after, "关闭.png", 0.90, roi=(480, 110, 720, 340))
        if pop:
            self.ui.press(pop.center, 150)
            self.ui.wait(1.0)
        return "popup"


class FactionPage(Page):
    """阵营挑战（2026-10-29 实测）。

    邪能/联盟/部落三个阵营按星期轮换，每层 30 波，每 10 波一个存档点。
    点「开始挑战」进布阵页：一键上阵 → 继续（没有「战斗」），随后弹增益三选一
    （用户要求选最左），确定后开打。战斗里没有跳过键，只有暂停/自动/倍速，
    所以脚本只负责把倍速切到 ×4 并等这一轮自己打完（团灭或 30 波）。
    """

    name = "faction"
    HEADER = "标题_阵营挑战.png"
    TILE = "历练_阵营挑战.png"
    START = "开始挑战.png"
    CONTINUE = "继续按钮.png"
    BUFF_OK = "增益确定.png"
    SPEED4 = "倍速_x4.png"
    POPUP_TEXT_ROI = (80, 380, 640, 900)     # 提示框文字区（诊断用）
    popup_text = ""                          # 最近一次提示框读到的文字

    def at_page(self, im=None) -> bool:
        return T.VI.find(im or self.shot(), self.HEADER, 0.88) is not None

    # 只有这些词的行才可能解释「为什么点不动」；ROI 覆盖大半个屏幕时，
    # 弹窗背后的榜单/关卡文字也会被读进来（离线实测 faction_page.png 读出
    # "500 / 13 / 关奖励 / 第10波 …"），直接拼进日志会误导。
    POPUP_KEYS = ("次数", "战力", "不足", "未开放", "未开启", "无法", "条件",
                  "失败", "需要", "已用完", "挑战次数", "达到")

    def _popup_reason(self, im) -> str:
        """把提示框里的文字读出来（2026-11-07：全量里出现「0 轮」但日志看不出
        是次数用完还是点错位置，加一句可读原因）。

        2026-11-08：只保留含 POPUP_KEYS 的行；一行都没有就返回空串，
        调用方会退回「点「开始挑战」只弹了提示框」这句实话。"""
        from . import textocr

        if not textocr.available():
            return ""
        lines = textocr.read_lines(im, self.POPUP_TEXT_ROI, min_score=0.5)
        keep = [t for t, _c, _bb, _s in lines
                if any(k in t for k in self.POPUP_KEYS)]
        return " / ".join(keep)[:60]

    def battle_like(self, im) -> bool:
        return max(T.VI.best_score(im, self.SPEED4, roi=L.SPEED_BOX),
                   T.VI.best_score(im, "倍速_x1.png", roi=L.SPEED_BOX)) >= 0.55

    def enter(self) -> bool:
        if self.at_page():
            return True
        if not TrialsHub(self.ui).enter_tile(self.TILE, self.HEADER,
                                             resumed=self.battle_like):
            return False
        for _ in range(6):                   # 页面/战斗可能还在加载
            im = self.shot("faction_in")
            if self.at_page(im) or self.battle_like(im):
                return True
            self.ui.wait(0.9)
        return False

    def claim_rewards(self) -> int:
        """领「通关奖励」（第 10/20/30 波宝箱）。

        2026-11-10 真帧：奖励图标右上角挂红「!」= 可领，领完变绿勾；
        图标中心比角标低 ~53px、左移 ~18px。已通关但没领的点图标会直接领到，
        未达成的点了只弹道具说明（不会误领别的东西）。
        """
        return self.claim_badge_icons(L.FACTION_REWARD_BAND, L.FACTION_BADGE_DX,
                                      L.FACTION_BADGE_DY, label="faction_reward",
                                      tries=6)

    def ensure_active_faction(self) -> None:
        """底部三个阵营页签（邪能/联盟/部落）只有“开启中”的那个能打。

        开启中的页签整块是亮的（实测 (164,172,128)，另两个 (83,78,66)），
        进页先把它点一下，避免停在别的阵营上「开始挑战」怎么点都没反应。
        """
        im = self.shot("faction_tabs")
        best, pos = -1, None
        for x in (155, 360, 565):
            R, G, B = vision.avg(im, x, 1140, r=30)
            if R + G + B > best:
                best, pos = R + G + B, (x, 1140)
        if pos and best > 330:
            self.ui.press(pos, 220)
            self.ui.wait(1.2)

    def _start_pos(self, im):
        """「开始挑战」按钮的位置：模板优先，半透明金按钮用金色下沿兜底。

        2026-10-30 实测：按钮是半透明的（中心 (194,185,162) 不满足 is_gold），
        模板分数只有 0.899，旧阈值 0.90 正好卡在门槛下 —— 这就是“识别到页面却
        永远不开打”的根因。按钮金色带在 y≈650~668，x≈520~680。
        """
        m = T.VI.find(im, self.START, 0.85, roi=(440, 300, 720, 1100))
        if m:
            return m.center
        for y in range(560, 1060, 6):
            if vision.is_gold(im, 600, y, r=10) and vision.is_gold(im, 520, y, r=10):
                return (600, y - 8)
        return None

    def start_run(self) -> str:
        im = self.shot("page")
        pos = self._start_pos(im)
        if pos is None:
            # 当前层可能在列表下方，往下翻几屏找「开始挑战」
            for _ in range(3):
                self.ui.dev.swipe(360, 820, 360, 620, 600)
                self.ui.wait(0.9)
                im = self.shot("page_scroll")
                pos = self._start_pos(im)
                if pos:
                    break
        if pos is None:
            return "none"
        self.ui.press(pos, 250)
        self.ui.wait(2.8)
        after = self.shot("after")
        if vision.is_green(after, *L.FACTION_DEPLOY, r=18) or \
                T.VI.find(after, self.CONTINUE, 0.85, roi=(460, 1155, 710, 1260)):
            return "deploy"
        if self.battle_like(after):
            return "battle"
        if vision.classify(after) in (State.DIALOG, State.MAIN_CITY_DIM):
            self.popup_text = self._popup_reason(after)
            log.info(f"  阵营挑战：点「开始挑战」弹了提示框（{self.popup_text or '没读到文字'}），先关掉")
            self.ui.close_popup(after)
            return "popup"
        pop = T.VI.find(after, "关闭.png", 0.90, roi=(480, 110, 720, 340))
        if pop:
            self.ui.press(pop.center, 150)
            self.ui.wait(1.0)
        return "popup"

    def deploy(self) -> bool:
        """布阵页：一键上阵 → 继续。每一步都重新截图确认，避免在过渡画面上按到主城导航。"""
        im = self.shot("dep_chk")
        auto = vision.is_green(im, *L.FACTION_DEPLOY, r=18)
        m = T.VI.find(im, self.CONTINUE, 0.85, roi=(460, 1155, 710, 1260))
        if not (auto or m):
            return False
        if auto:
            self.ui.press(L.FACTION_DEPLOY, 200, expect="none")
            self.ui.wait(1.2)
            m = T.VI.find(self.shot("dep_chk2"), self.CONTINUE, 0.85,
                          roi=(460, 1155, 710, 1260))
            if not m:
                return False
        self.ui.press(m.center, 250)
        self.ui.wait(2.8)
        return True

    def buff_dialog(self, im) -> bool:
        return T.VI.find(im, self.BUFF_OK, 0.90, roi=L.FACTION_BUFF_ROI) is not None

    def pick_buff(self) -> None:
        """三选一选最左那张，再点确定。"""
        self.ui.press(L.FACTION_BUFF_CARD, 200)
        self.ui.wait(0.7)
        self.ui.press(L.FACTION_BUFF_OK, 220)
        self.ui.wait(2.0)

    def ensure_speed(self, im, state: dict) -> bool:
        """确保倍速是 ×4；只在确认自己在战斗画面（看得到倍速标签）时才点。

        倍速钮是半透明的，背景会透出来：同一张 ×4 标签实测只有 0.73~0.84，
        非战斗画面最高 0.39，×1 帧上的 ×4 分数约 0.5——阈值取 0.65 / 0.85 才不会来回切。
        """
        x4 = T.VI.best_score(im, self.SPEED4, roi=L.SPEED_BOX)
        if x4 >= 0.65:
            return False
        x1 = T.VI.best_score(im, "倍速_x1.png", roi=L.SPEED_BOX)
        if max(x1, x4) < 0.55:
            return False                 # 加载/布阵画面，别乱点
        if x1 < 0.85 and x4 < 0.65:
            return False                 # 可能是 ×2，先不动，免得切回 ×1
        if state.get("presses", 0) >= 3:
            return False
        self.ui.press(L.SPEED_TOGGLE, 150)
        state["presses"] = state.get("presses", 0) + 1
        self.ui.wait(1.2)
        return True

    def run_battle(self, timeout: float) -> str:
        """把当前这一轮打完，直到回到阵营挑战页。返回 done / timeout / lost。

        一轮 30 波没有跳过键，只能等。若连续 2 分钟看不到任何已知画面
        （战斗倍速标签 / 布阵 / 增益弹窗 / 阵营页），说明游戏被切走了，直接放弃，
        免得在别人的界面上空等半小时。
        """
        ui = self.ui
        t0 = time.time()
        speed: dict = {}
        confirmed = 0
        last_known = t0
        last_note = t0
        while time.time() - t0 < timeout:
            im = self.shot("run")
            if self.buff_dialog(im):
                self.pick_buff()
                last_known = time.time()
                continue
            if vision.is_green(im, *L.FACTION_DEPLOY, r=18) or \
                    T.VI.find(im, self.CONTINUE, 0.85, roi=(460, 1155, 710, 1260)):
                if self.deploy():
                    last_known = time.time()
                continue
            if self.at_page(im):
                return "done"
            m = None
            for tpl in ("结算确定.png", "确定按钮.png"):
                m = T.VI.find(im, tpl, 0.82)
                if m:
                    break
            if m and confirmed < 3:
                ui.press(m.center, 220)
                ui.wait(2.0)
                confirmed += 1
                last_known = time.time()
                continue
            in_battle = self.battle_like(im)
            if in_battle:
                last_known = time.time()
                if self.ensure_speed(im, speed):
                    continue
                now = time.time()
                if now - last_note >= 60:
                    last_note = now
                    log.info(f"  阵营挑战：战斗中…（已 {int(now - t0)} 秒）")
            elif time.time() - last_known > 120:
                log.warn("  阵营挑战：连续 2 分钟不是战斗/布阵/阵营页，画面被切走，放弃这一轮")
                return "lost"
            ui.wait(4.0)
        return "timeout"


# ---------- 日常副本 / 罪魂之域 / 排行榜 / 公会商人 ----------

class DungeonPage(Page):
    """日常副本（历练页顶部「海量资源」）。

    四个子副本（经验/金币/进阶/装备）共用一套布局：一列关卡行，行右侧按钮是
    金色「挑战」（下一层）、绿色「免费扫荡」（已通关的最高层，每日 6 次）、
    灰字「通关上一层」；底部大按钮「一键扫荡」带钻石扫荡，脚本永不点；
    右上角宝箱 = 通关奖励（里程碑，进度达标后行内出现金色「领取」）。
    """

    name = "dungeon"
    TABS = L.DUNGEON_TABS
    ORDER = L.DUNGEON_TAB_ORDER

    def at_page(self, im=None) -> bool:
        """当前画面是不是日常副本的关卡列表页。

        2026-11-08：底栏写「经验副本/金币副本/进阶副本/装备副本」才是副本页；
        战斗页与主城底栏写的是「主城/英雄/助阵/战役/历练/竞技/公会」。跑偏后
        旧码照样按 (635,1215)/(632,215) 瞎点，制造空点与假归因（见
        `logs\_verify_bf_123225.log` 12:35 那两下）。
        """
        try:
            from . import textocr
            if not textocr.available():
                # 2026-11-09 假成功审计 m9：判据退化时要说出来（返回仍放行，
                # 免得把好好的任务拦成失败），日志里能看出这一轮没在验页。
                log.info("  日常副本：OCR 不可用，「是否在副本列表页」这一判据本轮退化（放行）")
                return True
            im = im or self.shot("dun_at")
            txt = textocr.read_text(im, L.DUNGEON_TAB_ROW)
        except Exception:            # noqa: BLE001 - OCR 异常不阻塞任务
            return True
        return any(k in txt for k in L.DUNGEON_TAB_KEYS)

    def ensure_page(self, tries: int = 2) -> bool:
        """回到日常副本列表页；跑偏（战斗页/公会页/主城）时重进。"""
        for i in range(max(1, tries)):
            if self.at_page():
                return True
            log.warn(f"  日常副本：当前不在副本列表页（第 {i + 1}/{tries} 次检查），重新进入")
            if not MainCity(self.ui).ensure():
                return False
            if not TrialsHub(self.ui).enter("dungeon"):
                return False
            self.ui.wait(1.4)
        ok = self.at_page()
        if not ok:
            log.warn("  日常副本：重进后仍不在副本列表页，本任务收手（不在别的页面点按钮）")
        return ok

    @staticmethod
    def active_tab(im) -> str | None:
        """哪个子副本页签是选中的（按文字框亮度，真帧实测选中项明显更亮）。

        返回 `exp/gold/grade/equip`，不确定时返回 None（不确定不等于失败）。
        """
        scores = {}
        for k, (x, y) in L.DUNGEON_TABS.items():
            r, _g, _b = vision.avg(im, x, y - 6, 10)
            scores[k] = r
        order = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if len(order) < 2:
            return None
        if order[0][1] - order[1][1] < 20:
            return None
        return order[0][0]

    def tab(self, key: str) -> bool:
        """切子副本页签，并用「选中项亮度」复核真的切过去了。

        2026-11-09 假成功审计：旧码 `press(..., expect="none")` 后直接 return True，
        切没切过去都不知道 → `ok_tabs` 恒 4、层数/宝箱记到错副本名下。
        """
        if not self.at_page():
            log.warn(f"  日常副本：切页签 {key} 前发现不在副本页，先回页")
            if not self.ensure_page():
                return False
        for attempt in range(2):
            self.ui.press(self.TABS[key], 250, expect="none")
            self.ui.wait(1.6)
            cur = self.active_tab(self.ui.screen(f"dun_tab_{key}{attempt}"))
            if cur is None:
                # 认不出版本（被压暗/浮层）就放行，保持旧行为，别把好流程拦死
                return True
            if cur == key:
                return True
            log.warn(f"  日常副本：点页签 {key} 后选中的是 {cur}（第 {attempt + 1}/2 次），"
                     f"再点一次")
        log.warn(f"  日常副本：页签 {key} 点了两次都没切过去，本子副本跳过")
        return False

    @staticmethod
    def _scan_buttons(im):
        """返回 (挑战按钮 y, 免费扫荡 y)，没找到给 None。

        2026-10-30 实测坑：关卡行右侧的绿色「已通过」印章也是绿的（实测 R≈177，
        只占 3/5 个取样点），会被当成「免费扫荡」乱点。真按钮是实心绿底（R≈107），
        x±30 三点全绿；用这组判据区分印章和按钮。

        2026-10-31 录像里发现新坑：免费扫荡用完 6 次后，已通关行变成金底的
        「💎20扫荡」（钻石扫荡），底部还有「一键扫荡」大按钮——两者都是金色，
        旧逻辑会把它们当成「挑战」去点（可能花钻石）。现在：
          ① 行内金色按钮左边有青色钻石图标的，一律当成付费扫荡跳过；
          ② 扫描区间收到 y<980，底部「一键扫荡」(y≈1010) 永远不在范围内。
        """
        def paid_icon(x, y):
            # y 是候选金色行（可能是按钮上沿也可能是下半截）；钻石图标在按钮左侧、
            # 垂直居中，所以在一整条按钮高度（上下各留余量）里找青色像素
            for dx in range(-100, -26, 4):
                for dy in range(-20, 48, 2):
                    xx = max(0, min(im.width - 1, x + dx))
                    yy = max(0, min(im.height - 1, y + dy))
                    R, G, B = im.getpixel((xx, yy))
                    if G > 165 and (G - R) > 25 and B > 140 and R < 205:
                        return True
            return False

        def green_btn(x, y):
            if not all(vision.is_green(im, x + dx, y, r=12) for dx in (-30, 0, 30)):
                return False
            R, G, B = vision.avg(im, x, y, r=10)
            return R < 150

        def gold_raw(x, y):
            return all(vision.is_gold(im, x + dx, y, r=12) for dx in (-30, 0, 30))

        def bands_of(x, test):
            """把连续命中的 y 合成按钮块，返回 [(top, bottom), ...]。"""
            out = []
            run = []
            for y in range(L.DUNGEON_BTN_SCAN[0], L.DUNGEON_BTN_SCAN[1], 4):
                if test(x, y):
                    run.append(y)
                elif run:
                    out.append((run[0], run[-1]))
                    run = []
            if run:
                out.append((run[0], run[-1]))
            return out

        x = L.DUNGEON_BTN_X
        challenge = None
        for top, bot in bands_of(x, gold_raw):
            # 2026-11-08 22:48/22:49 实机（run17，帧 tests\fixtures\
            # dun_push_miss_before.png + 裁图 logs\_crop_push_btn.png）：
            # 「挑战」按钮可见范围 y≈708~770、金带中心 738，但按 738/740
            # 两轮都是 diff=0.000 MISS，补偿点 732 两次都命中（0.80/0.88）。
            # 说明可点区域比可见金带偏上 ~8px（下沿是发光描边），所以中心再上移 8。
            cy = (top + bot) // 2 - 8
            if paid_icon(x, cy):
                continue        # 💎N扫荡：付费扫荡，跳过
            challenge = cy
            break
        sweep = None
        for top, bot in bands_of(x, green_btn):
            sweep = (top + bot) // 2
            break
        return challenge, sweep

    def find_challenge(self):
        im = self.shot("list")
        y, _ = self._scan_buttons(im)
        return (L.DUNGEON_BTN_X, y) if y else None

    def find_sweep(self):
        im = self.shot("list")
        _, y = self._scan_buttons(im)
        return (L.DUNGEON_BTN_X, y) if y else None

    @staticmethod
    def _claim_rows(im, need: int = 10):
        """奖励面板右列的金色「领取」按钮中心 [(cx, cy), ...]，从上到下。

        2026-11-06 实测（dungeon_chest_129/141/153 三张实拍）：按钮是横跨
        x≈512~652 的一整条金色，中心 x 落在 561~569，y 为 272/456/636/812/984。
        旧代码只扫 x=545 这一列、r=14，那一点的均值被按钮里的白字和暗边拉低
        （(225,184,141)，不满足 is_gold），所以 4 个子副本全部报「没找到金色领取」，
        实际是有 5 个待领——这次的 12 个宝箱就是这么漏掉的。
        现在按行扫整条：一行里有 ≥need 个金色像素才算按钮行，再把相邻行合成块。
        另外要求块高 ≥24px（实拍真按钮都占 9 行 ×4px≈36px）：equip 副本面板里
        有斜向的金色装饰线，单行/五行也能凑够 10 个像素，不设下限会当成按钮去点。

        2026-11-06 二次实测（logs/_dgn_panel0.png，通关奖励面板）：上面那版判据
        `R>=205 and G>=148 and R-B>=70` 把米色文字 (242,219,166) 也算成金色，
        于是「通关经验副本地狱22可获得 (43/45) 未达成」那四行被当成 5 个「领取」，
        4 个子副本各假领 1 个、报「宝箱 4」，实际一个都没领到（OCR 那行明写「未达成」）。
        收紧到饱和金（`L.DUNGEON_CHEST_GOLD`：B<=110、R-B>=110）后该面板 0 块，
        而列表页的扫荡金钮、罪魂面板的金色「挑战」仍然命中。
        """
        r_min, g_min, g_max, b_max, rb_min = L.DUNGEON_CHEST_GOLD
        rows = []
        for y in range(L.DUNGEON_CHEST_SCAN[0], L.DUNGEON_CHEST_SCAN[1], 4):
            cnt = sx = 0
            for x in range(L.DUNGEON_CHEST_BOX[0], L.DUNGEON_CHEST_BOX[1], 4):
                R, G, B = im.getpixel((x, y))
                if R >= r_min and g_min <= G <= g_max and B <= b_max and (R - B) >= rb_min:
                    cnt += 1
                    sx += x
            if cnt >= need:
                rows.append((sx // cnt, y))
        out, run = [], []
        for cx, y in rows:
            if run and y - run[-1][1] <= 24:
                run.append((cx, y))
            else:
                if len(run) >= 6:
                    out.append(run[len(run) // 2])
                run = [(cx, y)]
        if len(run) >= 6:
            out.append(run[len(run) // 2])
        return out

    @staticmethod
    def _panel_hint(im) -> str:
        """奖励面板上的文字（只为日志：区分「未达成」和「判据又漏了」）。"""
        try:
            from . import textocr
            if not textocr.available():
                return ""
            return textocr.read_text(im, (300, 240, 700, 1160))[:80]
        except Exception:      # noqa: BLE001 - 取证用，读不出来就算了
            return ""

    def claim_chest(self) -> int:
        if not self.at_page():
            log.warn("  副本宝箱：当前不在副本列表页（跑偏到战斗/其它页），"
                     "不点右上宝箱（0 个 ≠ 没有宝箱）")
            return 0
        before = self.shot("chest_before")
        # 2026-11-08 22:49 实机（run17）：宝箱图标在、位置也对（人眼核对裁图
        # logs\_crop_chest_miss22.png，(630,246) 正落在箱体上），但本页奖励已领完/
        # 全部「未达成」时游戏**不响应**这次点击（整屏 diff 0.000）。用默认校验
        # 会白做 4 个补偿点、刷 5 条「空点」告警，还报「0 个 ≠ 没有宝箱」的假故障。
        # 所以只点不校验，开没开面板由下面的 similar() 判。
        self.ui.press(L.DUNGEON_CHEST, 250, label="dungeon_chest",
                      expect="none")
        self.ui.wait(1.8)
        im = self.shot("chest")
        if vision.similar(before, im):
            hint = self._panel_hint(im)
            log.info(f"  副本宝箱：点了右上宝箱 {L.DUNGEON_CHEST} 面板没开"
                     f"（本页奖励已领完或全部未达成，界面：{hint or '—'}），跳过")
            return 0
        n, stall = 0, 0
        for _ in range(20):
            targets = self._claim_rows(im)
            if not targets:
                break
            cx, cy = targets[0]
            log.info(f"  副本宝箱：点「领取」({cx},{cy})，本页还有 {len(targets)} 个")
            self.ui.press((cx, cy), 220, label="dungeon_chest_claim", expect="none")
            self.ui.wait(1.6)
            self.ui.press(L.BLANK, 150, expect="none")   # 关「获得奖励」浮层
            self.ui.wait(0.8)
            im = self.shot("chest2")
            # 2026-11-06：必须复核「领取按钮真的少了一个」才计数。
            # 旧版点完无条件 n+=1，面板上其实全是「未达成」时也会报「领取 ×1」，
            # 于是 4 个子副本各报 1 个、合计「宝箱 4」，而实际一个都没领到。
            after = self._claim_rows(im)
            # 2026-11-08 18:00 实机（logs\_full8_173328.log）：面板行数在
            # 2 → 1 → 2 → 1 之间抖（同一行随浮层/滚动微量位移被重新识别），
            # 旧判据 `after != targets` 每次抖动都算一次 → 报「宝箱 7」。
            # 只认「刚点的这一行真的从列表里消失」，一次领取只计一次。
            gone = not any(abs(ay - cy) <= 24 and abs(ax - cx) <= 80
                           for ax, ay in after)
            if gone:
                n += 1
                stall = 0
            else:
                stall += 1
                if stall >= 2:
                    log.warn("  副本宝箱：连点两次「领取」按钮都没有变化，收手（按钮可能不可领）")
                    break
        if n == 0:
            hint = self._panel_hint(im)
            if "未达成" in hint:
                # 2026-11-07 实测：OCR 每行都写着「未达成 (43/45)」，说明确实没达标，
                # 不是判据漏了——降成 info，别每次跑都刷 WARN。
                log.info(f"  副本宝箱：本页奖励都写着「未达成」，0 个可领（{hint[:40]}）")
            else:
                log.warn(f"  副本宝箱：奖励面板已打开，但 {L.DUNGEON_CHEST_BOX} 里没找到金色「领取」"
                         f"（可能是未达标/已领完；面板文字：{hint or '没读到'}）")
        else:
            log.info(f"  副本宝箱：领取 ×{n}")
        self.ui.press(L.DUNGEON_CHEST_CLOSE, 200, expect="none")
        self.ui.wait(1.0)
        return n


class SoulPage(Page):
    """罪魂之域（2026-10-30 新副本，历练列表底部）。

    三列水晶组成一条路线，点亮的水晶点开是关卡面板（限制条件 + 首通奖励 + 挑战），
    面板底部金色「挑战」；默认勾选「快速战斗」，打完直接出「挑战成功」。
    挑战次数显示在底部（N/20，每日登录 +5）。
    """

    name = "soul"

    def at_page(self, im=None) -> bool:
        return titles.on_page(im or self.shot("at"), "soul")

    def enter(self) -> bool:
        if self.at_page():
            return True
        if not TrialsHub(self.ui).enter_tile("历练_罪魂之域.png", "标题_罪魂之域.png"):
            # 卡片模板没命中时按坐标兜底（列表底部倒数第二行中间）
            TrialsHub(self.ui).to_bottom()
            self.ui.press((360, 530), 250)
            self.ui.wait(3.0)
        for _ in range(6):
            if self.at_page():
                return True
            self.ui.wait(0.8)
        return False

    def attempts(self, im=None):
        """读底部「挑战次数：N/20」，返回 (剩余, 上限) 或 None。

        2026-11-06：旧版只读 `SOUL_ATTEMPT_BOX` 里的数字（14×20 模板），实测这行是
        18px 中文「挑战次数：0/20（每日登录+5）」，数字模板全读到垃圾。改用 textocr
        读整行中文再取分数，数字模板留作兜底。
        """
        from . import ocr, textocr
        im = im or self.shot("attempts")
        if textocr.available():
            frac = textocr.read_fraction(textocr.read_text(im, L.SOUL_ATTEMPT_TEXT))
            if frac:
                return frac
        nums = ocr.read_all_numbers(im, L.SOUL_ATTEMPT_BOX)
        if len(nums) >= 2:
            return nums[0], nums[1]
        return None

    @staticmethod
    def crystal_nodes(im=None) -> list[tuple[int, int]]:
        """罪魂之域地图上「值得试一次」的水晶点位（探测网格）。

        旧版按颜色（蓝/紫/绿高饱和）找水晶，实测无效：地图是绿蓝噪点画风，
        掩码要么返回 127 个全挤在草地带 y≈810 的假点，要么整块饱和、毫无区分度；
        地图也**不能滚动**（swipe diff 恒等于动画噪声底 0.088）。
        实测能点开面板的位置散布在 3 列 × 6 行上（x≈212/324~380/492~548，
        y≈400~820，y>880 一个都没有），所以直接给探测格，由调用方
        「点开面板 → 读面板文字」来判定是不是有效关卡。

        顺序按 y 从下往上排：关卡是「越靠下关数越小」，能打的永远是最低那一关
        （2026-11-07 实测按 y 从小到大要空点 22 次才摸到可挑战的第 1 关，218 秒）。
        """
        pts = [(x, y) for y in L.SOUL_PROBE_YS for x in L.SOUL_PROBE_XS]

        # 2026-11-08 提速：把「历史上真的点开过面板」的格子排到前面。
        # 统计 logs/mtbot_*.log 里全部 32 次面板命中，只落在 3 列
        # x=212/380/548 与 5 行 y=400/460/520/640/760 上；x=324/492 与
        # y=820 一次都没命中过（那些位置是草地/装饰）。30 格全试时每格
        # 约 7s（press 0.2 + wait 1.5 + 抓帧），全空跑一轮 416s；
        # 先试这 15 格能在「今天只剩未解锁关卡」时把耗时砍掉约一半，
        # 而剩下的格子仍然排在后面兜底，不丢覆盖。
        good_x, good_y = L.SOUL_GOOD_XS, L.SOUL_GOOD_YS
        pts.sort(key=lambda p: (0 if (p[0] in good_x and p[1] in good_y) else 1,
                                -p[1], p[0]))
        return pts

    def challenge_panel(self, im) -> bool:
        """面板上是否有可点的金色「挑战」按钮。

        实测按钮填充 (242,190,39)、框 x 258~462 / y 952~1020，整块占比 0.68；
        旧版单点 is_gold(360,986,r=16) 恒 False（窗口把按钮中间的「挑战」二字一起平均了）。
        未解锁关卡的面板只有红字「需通关第N关·右后解锁」，没有金按钮 → False。
        """
        if vision.gold_ratio(im, L.SOUL_CHALLENGE_BOX) >= 0.30:
            return True
        return vision.is_gold(im, *L.SOUL_CHALLENGE, r=16)

    def panel_text(self, im) -> str:
        """面板上的全部文字（【第4关】/限制条件/需通关…/挑战）。读不到返回 ""。"""
        from . import textocr
        if not textocr.available():
            return ""
        return textocr.read_text(im)

    @staticmethod
    def panel_open(im) -> bool:
        """关卡面板是否已打开（米色底占比 > 0.20）。地图实测 0.03、面板 0.29~0.37。

        ⚠️ 只判米色不够：赢一关后自动弹出的「秘典」页同样是 0.377。要区分屏幕请用
        `screen_kind()`（2026-11-07 死循环的根因就是把它当成了关卡面板）。
        """
        return vision.beige_ratio(im, L.SOUL_BEIGE_ROI) > 0.20

    @staticmethod
    def screen_kind(im, text: str = "") -> str:
        """罪魂之域的屏幕分类（2026-11-07 实机取证）。

        返回 map / panel / chest / codex / boss / deploy / battle / result / dialog / other。
        判定以 OCR 文字为主、像素为辅，覆盖这些实测屏：
          - map    地图（挑战次数 N/20）
          - panel  关卡面板（【第N关】+ 限制条件 + 金色「挑战」）
          - chest  宝箱详情（「在前往首领的路途中…」）
          - codex  秘典页（「当前秘典」/「请选择秘典」）——赢关后自动弹出，出口 (140,1257)
          - boss   首领页（「选择首领词条」+「已通关难度：N/9」）——出口 (140,1257)
          - deploy 首领布阵页（「一键上阵」+ 金色「出战」）
          - battle 实时战斗（伤害数字 / 自动 / x1）
          - result 结算页（「MVP / 全场 / 胜利 / 点击空白处关闭」）——出口 (364,1090)
          - dialog 「是否将下方宝物移除」确认框——出口 (228,1001) 取消
        """
        t = text or ""
        if not t:
            if not SoulPage.panel_open(im):
                return "map"
            return "other"
        if "宝物移除" in t:
            return "dialog"
        if "当前秘典" in t or "请选择秘典" in t:
            return "codex"
        if "点击空白处关闭" in t or "MVP" in t or "全场" in t:
            return "result"
        if "一键上阵" in t:
            return "deploy"
        if "选择首领词条" in t or "首领词条越多" in t:
            return "boss"
        if "【第" in t and "限制条件" in t:
            return "panel"
        if "宝箱详情" in t:
            return "chest"
        if "战斗开始" in t or ("伤害" in t and "自动" in t) or "x1" in t and "首领" in t:
            return "battle"
        if "挑战次数" in t or "已通关难度" in t:
            return "map"
        # 2026-11-15：普通罪魂之域战斗的 OCR 里没有「伤害」字样（只有 自动/x1/跳过），
        # 旧判据于是落到 "other"，而 _wait_battle 没有 other 分支 → 150 秒静默空转，
        # 打赢了也被判成「点开后没有明确结果」（_usrgr 20:00 / 20:35 两次 FAIL）。
        # 用通用「跳过」模板兜底：命中即战斗态。
        try:
            from . import template as _T
            if _T.VI.find(im, "跳过.png", L.BATTLE_SKIP_THRESHOLD, roi=L.BATTLE_SKIP_ROI):
                return "battle"
        except Exception:        # noqa: BLE001 - 模板不可用就维持原判
            pass
        return "other"

    @staticmethod
    def locked_panel(text: str) -> bool:
        """面板是「未解锁」关卡（红字提示需先通关前一关）。"""
        return ("需通关" in text) or ("未解锁" in text) or ("尚未解锁" in text)

    def close_panel(self) -> None:
        # 面板本来就可能已经关了（点空白/上一轮收尾），点空不算异常
        self.ui.press(L.SOUL_INFO_CLOSE, 180, expect="none")
        self.ui.wait(0.9)

    def exit_codex(self) -> None:
        """秘典页 / 首领页回地图：点底部最左页签「首通奖励」（实测唯一有效出口）。"""
        self.ui.press(L.SOUL_CODEX_EXIT, 180, expect="none")
        self.ui.wait(1.6)

    def cancel_remove_dialog(self) -> None:
        """「是否将下方宝物移除」确认框：点「取消」。"""
        self.ui.press(L.SOUL_DIALOG_CANCEL, 180, expect="none")
        self.ui.wait(1.2)

    def close_result(self) -> None:
        """战斗结算页（MVP/胜利）：点「确定」。"""
        self.ui.press(L.SOUL_RESULT_OK, 200, expect="none")
        self.ui.wait(1.6)


class RankBoardPage(Page):
    """排行榜（主城右侧）。

    2026-10-31 重做（旧版按「奖励格子 + 长按」写，实际界面不是这样）：
      - 列表页底部三个大分类（本服进度/本服养成/跨服排行），点一行进榜单；
      - 榜单页底部是一排小页签（等级排行/战力排行/战役关卡/守护者之塔/邪能神殿…可滑动），
        **有未领奖励的页签图标上方会挂一个红色「!」**；
      - 右上角奖杯「奖励」打开「进度奖励」面板，是**竖排列表**：每行右侧一颗奖励图标，
        可领取时图标右上角有红色「!」，**单击图标**就领（会弹「获得奖励」浮层）；
        没达标是「暂无玩家上榜」，已领是绿色「已领取」。
    """

    name = "rank_board"
    REWARD_BTN_TPL = "排行榜奖励按钮.png"

    def at_page(self, im=None) -> bool:
        return titles.on_page(im or self.shot("at"), "rank_board")

    def in_leaderboard(self, im=None) -> bool:
        """榜单页判定：优先认「排名 / 玩家名称 / 等级」表头。

        2026-11-04 实测：旧判定只认右上奖杯模板，跨服分类的榜单页奖杯被偶像挡住，
        模板 0.72 匹配不到 → 已进榜单却判 False，于是对着玩家行反复点（空耗 2 次补偿）。
        表头模板跨分类稳定（0.99~1.0，列表页 0.27）。
        """
        im = im or self.shot("lb")
        if T.VI.find(im, "排行榜_榜单页头.png", 0.85):
            return True
        if T.VI.find(im, self.REWARD_BTN_TPL, 0.72) is not None:
            return True
        # 2026-11-11 实测：跨服分类的榜单页两套模板都匹配不到（只报「点不进榜单」，
        # 实际已经点进去了）。用表头文字兜底：「玩家名称」只在榜单页出现（列表页写「等级排行」）。
        try:
            txt = textocr.read_text(im, L.RANK_BOARD_HEAD_BOX)
        except Exception:
            txt = ""
        flat = txt.replace(" ", "")
        return "玩家名称" in flat or ("排名" in flat and "我的排名" in flat)

    def enter(self) -> bool:
        if self.at_page():
            return True
        if not MainCity(self.ui).ensure():
            return False
        self.ui.press(L.RANK_BOARD_ENTRY, 250)
        self.ui.wait(2.2)
        for _ in range(3):
            if self.at_page():
                return True
            self.ui.wait(0.8)
        return False

    def open_board(self) -> bool:
        """在榜单列表里点一行进榜单页。

        2026-11-11 修：旧版只试 `RANK_BOARD_ROWS[:3]` 且每行只等 2.0s 看一帧 ——
        第 47 轮实测第三个分类点 (330,581) 空点、补偿点 (330,565) 才命中，但那一帧
        还没出榜单页 → 整个分类被跳过（只跑 2 个分类）。现在候选 6 行、每行轮询 3 帧，
        全失败再下滚屏重试一遍（列表可能被上一个分类滚过）。
        """
        for attempt in range(2):
            if self.in_leaderboard():
                return True
            for y in L.RANK_BOARD_ROWS:
                self.ui.press((330, y), 220, label=f"rank_row:{y}", expect="none")
                self.ui.wait(1.4)
                for _ in range(3):
                    if self.in_leaderboard():
                        return True
                    self.ui.wait(0.7)
            if attempt == 0:
                log.info("  排行榜：榜单列表里没点进任何一行，下滚一屏再试")
                self.ui.dev.swipe(*L.RANK_LIST_SCROLL, 420)
                self.ui.wait(1.0)
        return False

    def back_to_list(self, tries: int = 4, gap: float = 0.7) -> bool:
        """从榜单页回分类列表页（轮询，2026-11-07：旧版只看一帧，过渡帧会判成失败）。"""
        self.ui.press(L.RANK_LIST_BACK, 220, expect="none")
        self.ui.wait(1.5)
        for i in range(tries):
            if self.at_page():
                return True
            self.ui.wait(gap)
        return False

    def open_reward_panel(self) -> bool:
        """打开「进度奖励」面板；2026-11-04 实测跨服分类的榜单页没有这颗奖杯，
        旧版找不到模板就盲点 (630,265)，会白点 + 4 次补偿空转 ~16s，还误以为面板已开。"""
        im = self.shot("lb")
        m = T.VI.find(im, self.REWARD_BTN_TPL, 0.72)
        if not m:
            # 2026-11-07：跨服分类确实没有这颗奖杯（整帧 OCR 无「奖励」字样），
            # 属正常状态，不是异常 —— 降成 info，避免每次全量都刷 WARN。
            log.info("  排行榜：榜单页右上角没有「奖励」奖杯（该榜无进度奖励面板），"
                     "跳过 open_reward_panel")
            return False
        self.ui.press(m.center, 220)
        self.ui.wait(2.0)
        return True

    def close_reward_panel(self) -> None:
        im = self.shot("panel_close")
        m = [p for p in self.ui._find_close_buttons(im) if p[1] <= 300]
        # 2026-11-08：全量日志里 "close_reward_panel:655,238" 空点 7 次——
        # 面板已经关掉时再点关闭，画面当然不变；这里只发点击不校验。
        pos = (int(m[0][0]), int(m[0][1])) if m else L.RANK_PANEL_CLOSE
        self.ui.press(pos, 160, expect="none")
        self.ui.wait(1.2)

    def tab_badges(self, im=None) -> list[int]:
        """底部页签条上挂了红色「!」的页签：返回应点击的页签中心 x 列表。"""
        im = im or self.shot("tabs")
        xs = []
        x = 100
        while x <= 700:
            if vision.red_count(im, x, L.RANK_TAB_BADGE_Y, r=14) >= 6:
                # 角标 ~20px 宽，做个局部重心再减偏移，避免按在页签缝上
                tot = n = 0
                for xx in range(max(0, x - 22), min(im.width, x + 22)):
                    for yy in range(max(0, L.RANK_TAB_BADGE_Y - 14),
                                    min(im.height, L.RANK_TAB_BADGE_Y + 15), 2):
                        R, G, B = im.getpixel((xx, yy))
                        if R > 190 and G < 130 and B < 110 and (R - G) > 90:
                            tot += xx
                            n += 1
                cx = int(tot / n) if n else x
                xs.append(cx - L.RANK_TAB_BADGE_DX)
                x += 70            # 跳过同一个角标
            else:
                x += 12
        return [v for v in xs if 90 <= v <= 700]

    def claim_panel_rows(self, ui=None) -> int:
        """在「进度奖励」面板里把带红「!」的行逐个领掉（列表可滚动）。"""
        ui = ui or self.ui
        n = 0
        idle = 0
        for _ in range(16):
            im = self.shot("panel")
            hit = None
            for y in L.RANK_PANEL_ICON_YS:
                if vision.red_badge(im, L.RANK_PANEL_ICON_X + L.RANK_PANEL_BADGE_DX,
                                    y + L.RANK_PANEL_BADGE_DY, r=16, need=6):
                    hit = (L.RANK_PANEL_ICON_X, y)
                    break
            if hit is None:
                if idle >= 1:
                    break
                idle += 1
                ui.dev.swipe(*L.RANK_PANEL_SCROLL, 550)
                ui.wait(1.0)
                continue
            idle = 0
            ui.press(hit, 220)
            ui.wait(1.7)
            after = self.shot("panel_claim")
            if vision.darkened(im, after):
                # 「获得奖励」浮层：点空白关闭（空白点本来就不改画面）
                ui.press((360, 1060), 150, expect="none")
                ui.wait(0.9)
            n += 1
        return n


class MerchantPage(Page):
    """公会商人（2026-11-03 实机 720×1280 重写）。

    真实交互（旧实现整个模型错了）：
      1. 底部大按钮默认是「议价」，每点一次公会折扣上升（实测 -146 → -151）。
      2. 折扣显示在商人手持木牌的红爆炸角标里，形如「-151」（**负号代表折扣幅度**，
         不是旧代码读的「当前累计 44/59人 议价 646」）。
      3. 点一个商品图标 → 弹道具说明，同时底部按钮变成「💎-N」（购买）。
      4. 购买按钮第一下只关道具说明，第二下才弹「是否花费 💎-N 购买礼包」确认框，
         红色「取消」(256,956) / 金色「确定」(500,956)。
    """

    name = "merchant"

    def at_page(self, im=None) -> bool:
        return titles.on_page(im or self.shot("at"), "merchant")

    def enter(self) -> bool:
        if self.at_page():
            return True
        if not MainCity(self.ui).ensure():
            return False
        MainCity(self.ui).tab(L.TAB_GUILD)
        for _ in range(2):
            self.ui.press(L.MERCHANT_ENTRY, 250)
            self.ui.wait(2.4)
            for _ in range(3):
                if self.at_page():
                    return True
                self.ui.wait(0.8)
        return False

    def discount(self, im=None):
        """读木牌角标里的折扣数字（返回正数，例如 151）。低置信度返回 None。

        2026-11-07 白天实测：数字模板把「-170」读成「270」且置信度只有 0.42（低于
        0.45 门槛）→ `discount()` 返回 None，商家任务整轮跳过（夜里没暴露是因为
        那时底部没金钮、走的是另一条分支）。改用 `textocr` 直读整框：
        `read_lines((500,400,620,460))` = `-170 置信度 0.978`，稳。模板 OCR 仅兜底。
        """
        from . import ocr, textocr
        im = im or self.shot("merchant")
        score = 0.0
        if textocr.available():
            for text, _c, _bb, sc in textocr.read_lines(im, L.MERCHANT_DISCOUNT_BOX,
                                                       min_score=0.55):
                digits = "".join(ch for ch in text if ch.isdigit())
                if 2 <= len(digits) <= 4:
                    return int(digits), sc
        for mask in ("bright_yellow", "pale", "white"):
            text, score = ocr.read_digits(im, L.MERCHANT_DISCOUNT_BOX, mask=mask, min_score=0.45)
            # 这个美术字体的「1」和项目通用数字模板差异大，实测得分 ~0.50 且稳定；
            # 达标判断只看数量级（≥100），所以放宽到 0.45，低置信度由调用方记录。
            if text and 2 <= len(text) <= 4 and score < 0.60:
                # 这个美术字体的「1」比其它数字窄很多，通用模板会误判成 2/7（实测 -154 读成 254）。
                # 首位字宽明显小于中位宽时，按「1」纠正。
                gs = ocr._segments(ocr._mask(im, L.MERCHANT_DISCOUNT_BOX, mask))
                if gs and len(gs) == len(text):
                    widths = [g[2] - g[0] for g in gs]
                    med = sorted(widths)[len(widths) // 2]
                    if widths[0] <= med * 0.9 and text[0] != "1":
                        text = "1" + text[1:]
            if text and 2 <= len(text) <= 4:
                return int(text), score
        return None, score

    def bargain(self) -> bool:
        """点底部「议价」，等折扣刷新。返回 False = 按钮不是金色（已购买/议价上限）。

        2026-11-04 实测（f0005）：商店这一阶段底部按钮已变成灰色「已购买」，
        旧版死点 (356,1090) → 每次 diff=0.000 再做 4 点补偿，一轮白等 20s ×2。
        """
        im = self.shot("merchant_bargain")
        bands = vision.gold_button_bands(im, L.MERCHANT_BUY_BOX)
        if not bands:
            # 今天这档已买过/议价上限 = 正常收手，不是异常（2026-11-07 降级为 info）
            log.info("  公会商人：底部没有金色按钮（已是「已购买」/议价不可用），跳过议价")
            return False
        self.ui.press((bands[0][0], bands[0][1]), 250,
                      label="merchant_bargain", expect="none")
        self.ui.wait(1.8)
        return True

    def select_item(self, index: int = 0) -> bool:
        """选商品：底部按钮从「议价」变成「💎-N」（购买）。

        2026-11-10 实测（第 38 轮 07:38）：商品图标压在货架上，点它只有底部按钮变样，
        点击点 ±120px 几乎没有像素变化 —— 用默认变化校验会 MISS + 4 个补偿点
        （日志里的 `空点：merchant:merchant_item:0:170,512`）。改成只点不校验，
        点完复核「底部出现金钮」或「写着已购买」，两者都没有才算没选中。
        """
        pos = L.MERCHANT_ITEMS[max(0, min(index, len(L.MERCHANT_ITEMS) - 1))]
        self.ui.press(pos, 250, label=f"merchant_item:{index}", expect="none")
        self.ui.wait(1.2)
        im = self.shot("merchant_item")
        if vision.gold_button_bands(im, L.MERCHANT_BUY_BOX) or self._already_bought(im):
            return True
        log.info(f"  公会商人：点商品 {pos} 后底部没有出现购买按钮（该档已买过/不可买）")
        return False

    @staticmethod
    def confirm_open(im) -> bool:
        """购买确认框：左红「取消」+ 右金「确定」都在（通用 confirm_dialog 的 235,700 在这里不适用）。"""
        return (vision.is_red(im, *L.MERCHANT_CANCEL_DOT, r=10)
                and vision.is_gold(im, *L.MERCHANT_CONFIRM_DOT, r=26))

    @staticmethod
    def read_diamonds(im):
        """读主城顶栏钻石数（负折扣交易是收入，买卖前后要用它自证）。"""
        from . import ocr
        score = 0.0
        for mask in ("dim_yellow", "pale"):
            text, score = ocr.read_digits(im, L.CITY_DIAMOND_BOX, mask=mask, min_score=0.45)
            if text and 1 <= len(text) <= 7:
                return int(text), score
        return None, score

    def buy(self, cancel_only: bool = False, evidence_path: str | None = None) -> str:
        """点购买 → 过确认框。返回状态字符串（不是 bool）。

        重要语义（2026-11-03 用户确认）：确认框里的「花费 💎-154」是**商人倒给你 154 钻**，
        负号代表收入，不是支出；所以这里不调用 may_spend / allow_diamonds 拦截。
        cancel_only=True 仅用于验证到弹窗为止（不成交）。

        返回：`"bought"` 成交 / `"sold_out"` 底部写着「已购买」（今天已经买过，不是失败）
        / `"no_button"` 底部既不是金钮也没有「已购买」字样（不可买）
        / `"cancelled"` cancel_only 时点取消 / `"no_confirm"` 点了没弹确认框。

        2026-11-07：旧版返回 bool，`sold_out` 和「购买按钮坏了」都落到 `False`，
        结果文案一律写成「购买未完成」——白天实跑就是这种误导（底部 OCR 明确读到
        「已购买」，0.98 置信度）。
        """
        im = self.shot("merchant_buy")
        for _ in range(4):
            if self.confirm_open(im):
                break
            bands = vision.gold_button_bands(im, L.MERCHANT_BUY_BOX)
            if not bands:
                # 2026-11-04：没有金色购买带（按钮是灰「已购买」）时别再死点旧坐标，
                # 旧版 4 次 diff=0.000 + 每次 4 点补偿，白等 ~40s。
                if self._already_bought(im):
                    log.info("  公会商人：底部是「已购买」，今天这档已经买过了，不再点")
                    return "sold_out"
                # 2026-11-07：同「议价」，底部没金钮 = 已购买/不可买，属正常收手，降为 info
                log.info("  公会商人：底部没有金色购买按钮（已购买/不可买），跳过购买")
                return "no_button"
            self.ui.press((bands[0][0], bands[0][1]), 250,
                          label="merchant_buy", expect="none")
            self.ui.wait(1.5)
            im = self.shot("merchant_buy")
        if not self.confirm_open(im):
            log.warn("  公会商人：点了购买但没弹出确认框（按钮可能不可用）")
            return "no_confirm"
        if evidence_path:
            im.save(evidence_path)
        if cancel_only:
            self.ui.press(L.MERCHANT_CANCEL, 200)
            self.ui.wait(1.4)
            self.shot("merchant_cancel")
            log.info("  公会商人：已弹出购买确认框，本轮点「取消」不消费钻石")
            return "cancelled"
        self.ui.press(L.MERCHANT_CONFIRM, 200)
        self.ui.wait(2.2)
        after = self.shot("merchant_bought")
        if self.confirm_open(after):
            return "no_confirm"
        # 购买成功时中央会出现「获得」面板；没变化则按失败处理，避免谎报
        return "bought" if not vision.similar(im, after) else "no_confirm"

    @staticmethod
    def _already_bought(im) -> bool:
        """底部区域是否写着「已购买」（灰按钮，今天已买过）。"""
        from . import textocr
        if not textocr.available():
            return False
        txt = textocr.read_text(im, L.MERCHANT_BUY_BOX)
        return "已购买" in txt

    def back_to_guild(self) -> None:
        self.ui.press(L.MERCHANT_BACK, 250, expect="none")
        self.ui.wait(1.2)
        self.ui.press(L.BACK, 250, expect="none")
        self.ui.wait(1.2)


# ---------- 日常 ----------

class DailyPage(Page):
    name = "daily"

    def at_daily(self, im=None) -> bool:
        """日常页（标题「日常任务」；周常/成就/历练页有自己的标题）。"""
        return titles.on_page(im or self.shot("daily_at"), "daily")

    def switch(self, tab, expect: str | None = None, tries: int = 4) -> bool:
        """切页签（日常/周常/成就/历练），必须确认「真的切过去了」。

        2026-11-04（用户反馈「点击不准 / 直接跳过」）：只按一个固定 y 点，
        页签条一旦改版就整段静默跳过。现在按 tab[1] / -25 / -50 / -75 四个
        候选 y 逐个试，每次用 press 的「±120px 区域是否有变化」结果作判据，
        再叠加标题模板；全部失败才跳过一次，并把每次失败原因写进 warning。
        注意：menu 只保留数据，不静默 continue。
        """
        before = self.shot("tab_before")
        # 2026-11-04：实测页签图标中心 y≈1230，±12 微调即可；旧候选 -25/-50/-75
        # 全部落在列表行上，靠「行高亮」误判成切页成功。
        ys = (tab[1], tab[1] - 12, tab[1] + 12, tab[1] - 24)[:max(1, tries)]
        for i, y in enumerate(ys):
            pos = (tab[0], y)
            # 有标题模板时不走「±120px 必须变化」的校验：停留在同一页签时
            # 点击本来就不会产生变化，硬校验只会白等 4 次补偿（每次 1s+）。
            hit = self.ui.press(pos, 220, label=f"daily_tab:{tab[0]}",
                                expect="none" if expect else "change")
            self.ui.wait(1.4)
            after = self.shot("tab_after")
            changed = not vision.similar(before, after)
            tpl_ok = bool(expect) and titles.on_page(after, expect)
            # 2026-11-04：已经在目标页签上时点击不产生画面变化（diff=0），
            # 这是正常态，不能当失败。有标题模板就以标题为准；没有模板才退回
            # 「点击命中 + 画面变化」的老判据。
            ok = tpl_ok if expect else (hit and changed)
            if ok:
                if i:
                    log.info(f"  日常：页签 x={tab[0]} 实测可用 y={y}（配置 {tab[1]}，差 {y - tab[1]}px）")
                return True
            # 逐个候选失败不算真问题：下一个 y 常常就命中（实测配置 1230 与真值 1218 差 12px）。
            # 只有全部候选都没成功（下面那条才是 warn）才值得告警。
            log.info(f"  日常：页签切换失败 x={tab[0]} y={y} "
                     f"（hit={hit} 画面变化={changed} 标题模板={tpl_ok if expect else '未校验'}）")
            before = after
        log.warn(f"  日常：页签 x={tab[0]} 的 {len(ys)} 个候选 y 全部失败，本页跳过")
        return False

    @staticmethod
    def _tab_active(im, pos) -> bool:
        """被选中的页签是米白圆角块：中心区域明显比两侧亮（未选中是深棕）。"""
        r, g, b = vision.avg(im, pos[0], pos[1] - 30, 10)
        return r > 175 and g > 150 and b > 120

    def claim_all(self) -> bool:
        im = self.shot("open")
        if not vision.is_gold(im, *L.DAILY_CLAIM, r=18):
            # 2026-11-03：用户明确说「一键领取 + 自动置顶」，不要往下翻页滚动；
            # 找不到就说明当前没有可领项（列表顶部就是「前往」），直接返回。
            log.info("  日常：没有金色的「一键领取」按钮（今天没有可领项或已领完）")
            return False
        self.ui.press(L.DAILY_CLAIM, 220)
        self.ui.wait(1.8)
        self.ui.press(L.BLANK, 150, expect="none")
        self.ui.wait(0.8)
        # 2026-11-09 假成功审计：点完要复核 —— 真的领掉之后按钮就不再是金色
        # （领完列表会「自动置顶」并变成「前往」/灰态）。按钮仍金说明没生效。
        after = self.shot("after_claim_all")
        if vision.is_gold(after, *L.DAILY_CLAIM, r=18):
            log.info("  日常：点了「一键领取」但按钮仍是金色（没领掉，可能被动画/浮层挡住），"
                     "本次不计入领取数")
            return False
        return True

    @staticmethod
    def _chest_claimed(im, pos) -> bool:
        """宝箱图标正中的绿色对勾：已领过就跳过，别再把「已领取」提示算成一次领取。"""
        import numpy as np

        cx, cy = pos
        crop = np.array(im.crop((cx - 24, cy - 24, cx + 24, cy + 24))).astype(int)
        r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
        # 实测对勾是黄绿色（R>170,G>150,B<110），不是纯绿
        return int(((r > 170) & (g > 150) & (b < 110)).sum()) > 90

    def claim_chests(self, positions=None) -> int:
        n = 0
        for pos in (positions or L.DAILY_CHESTS):
            im = self.shot("chest")
            if self._chest_claimed(im, pos):
                log.debug(f"  宝箱 {pos} 已有对勾（已领），跳过")
                continue
            if self.ui.press(pos, 200):
                # 2026-11-09 假成功审计 m2：点完要看见「已领对勾」才算领到
                if self._chest_claimed(self.shot("chest_after"), pos):
                    n += 1
                else:
                    log.info(f"  宝箱 {pos}：点了但没出现「已领取」对勾，不计入")
            self.ui.wait(1.3)
        self.ui.press(L.BLANK, 150, expect="none")
        return n

    def claim_rows(self, scrolls: int = 3) -> int:
        """周常/成就/历练每一行右侧的「领取」（亮金色）逐个点掉。

        「前往」是土黄色、「已领取」是绿色，都过不了 is_gold，不会被误点。
        """
        n = 0
        for _ in range(scrolls):
            im = self.shot("rows")
            for y in L.DAILY_ROW_YS:
                if vision.is_gold(im, L.DAILY_ROW_BTN_X, y, r=16):
                    # 2026-11-10：旧码靠 press 的返回值判「点到了没」，浮层一出来就返回
                    # False → continue，且不会点空白关浮层 → 后面几行全部看不到。
                    if not self.claim_click((L.DAILY_ROW_BTN_X, y), f"daily_claim{y}"):
                        continue
                    n += 1
                    im = self.shot("rows2")
            self.ui.dev.scroll_up(360, 1000, 400, 500)
            self.ui.wait(1.0)
        return n


# ---------- 铁匠铺 / 商店 ----------

class ForgePage(Page):
    name = "forge"

    def enhance_tab(self) -> None:
        self.ui.press(L.FORGE_TAB_ENHANCE, 250, label="forge_tab_enhance", expect="none")
        self.ui.wait(1.8)

    def enhance_one(self) -> bool:
        """点一件装备的「强化1次」，用「卡片区域真变了」判成败。

        2026-11-10 真帧：强化页没有红角标（四点 red_count 全 0），按钮是米色
        （过不了 is_gold），旧码因此一次都没强化过。现在逐个槽位点按，
        以 `FORGE_SLOT_ZONES` 的像素变化作为成功证据；全都没变化就返回 False。
        """
        im = self.shot("enh")
        for (bx, by), zone in zip(L.FORGE_SLOT_BTNS, L.FORGE_SLOT_ZONES):
            self.ui.press((bx, by), 220, label=f"forge_one_{bx}", expect="none")
            self.ui.wait(1.9)
            after = self.shot("enh_after")
            if vision.diff_ratio(im, after, zone) >= 0.02:
                return True
            im = after
        log.info("  铁匠铺：四件装备点「强化1次」后卡片都没变化（金币/材料不足），不算强化")
        return False

    def enhance_50(self) -> bool:
        """「强化50级」：金币够才点；点完复核金币条/等级真的变了。

        2026-11-09 假成功审计：旧码只看「金币够」就 return True。
        """
        im = self.shot("enh50")
        if vision.forge_cost_affordable(im, L.FORGE_COST_BOX):
            self.ui.press(L.FORGE_ENHANCE_50, 250)
            self.ui.wait(2.5)
            after = self.shot("enh50_after")
            if vision.diff_ratio(im, after, L.FORGE_COST_BOX) < 0.02 and vision.similar(
                    im, after):
                log.info("  铁匠铺：点「强化50级」后画面没变化（金币/材料不足），不算强化")
                return False
            return True
        return False

    def star_popup(self) -> bool:
        """进铁匠铺时可能直接弹出「一键升星」弹窗（可升星时才有金色确认按钮）。"""
        im = self.shot("star")
        st = vision.forge_star_dialog(im)
        if st == "ready":
            self.ui.press(L.FORGE_STAR_POPUP, 250)
            self.ui.wait(2.2)
            return True
        if st == "locked":
            self.ui.press(L.FORGE_STAR_POPUP_X, 150, expect="none")
            self.ui.wait(0.9)
        return False


class ShopPage(Page):
    name = "shop"

    def free_refresh(self) -> bool:
        self.ui.press(L.SHOP_TAB_MYSTIC, 250, label="shop_tab_mystic", expect="none")
        self.ui.wait(1.5)
        im = self.shot("mystic")
        green = vision.is_green(im, *L.SHOP_FREE_REFRESH, r=16)
        gold = vision.is_gold(im, *L.SHOP_FREE_REFRESH, r=10)
        # 2026-11-09 审计（logs/_audit_paid.md C2）：原来 `green or gold` 两支都点。
        # 本项目的颜色约定是「付费钮=金色」，而免费次数用完后同一坐标会变成
        # 「💎N 刷新」——金色分支等于替玩家花钻石，与「钻石刷新一律不点」冲突。
        # 现在只认绿（免费）；金色只在 OCR 明确读到「免费」时才点。
        if not green and gold:
            txt = ""
            try:
                from . import textocr
                if textocr.available():
                    txt = textocr.read_text(im, L.SHOP_REFRESH_BOX)
            except Exception:      # noqa: BLE001
                txt = ""
            if "免费" in txt:
                log.info(f"  商店：「刷新」钮是金色但文字含「免费」（OCR：{txt.strip()[:12]}），按免费处理")
                green = True
            else:
                log.info("  商店：「刷新」钮是金色（大概率是「💎N 刷新」，付费），不点"
                         "（免费次数用完/未开放）")
                return False
        if green:
            before = im
            self.ui.press(L.SHOP_FREE_REFRESH, 220)
            self.ui.wait(1.6)
            # 2026-11-09 假成功审计 M9：点完要复核 —— 商品区变了，或「刷新」钮不再绿
            after = self.shot("mystic_after")
            moved = vision.diff_ratio(before, after, L.SHOP_ITEMS_ZONE) >= 0.02
            still = vision.is_green(after, *L.SHOP_FREE_REFRESH, r=16)
            if not moved and still:
                log.info("  商店：点了「免费刷新」但商品区没变化、按钮仍绿，不计入"
                         "（可能次数已用完）")
                return False
            return True
        # 2026-11-08：按钮既不绿也不金时这里原来一句都不打，实机只看到
        # 「免费刷新 0 次」，分不清是今天用完了、页签没切过去，还是判据漏了。
        r, g, b = vision.avg(im, *L.SHOP_FREE_REFRESH, r=12)
        log.info(f"  商店：「免费刷新」按钮不亮（rgb={r:.0f},{g:.0f},{b:.0f}，"
                 f"绿={green} 金={gold}），今天可能已用完或未开放")
        return False


# ---------- 公会 ----------

class GuildPage(Page):
    name = "guild"

    def trial_page(self, im=None) -> bool:
        """公会试炼页（标题「公会试炼」）。"""
        return titles.on_page(im or self.shot("trial_at"), "guild_trial")

    def beast_page(self, im=None) -> bool:
        """公会圣兽页（标题「公会圣兽」）。"""
        return titles.on_page(im or self.shot("beast_at"), "beast")

    def donate_gold(self) -> str:
        """金币捐献，返回 done / already / no_page / unclear（**必须带证据**）。

        2026-11-09 假成功审计：旧版只要按钮不金就返回 False，任务侧一律写
        「已捐献过」并报 OK —— 面板根本没打开时也是这样。现在面板文字（OCR）必须
        读出「公会捐献」才算打开；点完还要复核那一行不再是金色。
        """
        self.ui.press(L.GUILD_DONATE, 250)
        self.ui.wait(1.8)
        im = self.shot("donate")
        txt = ""
        try:
            txt = textocr.read_text(im, L.GUILD_DONATE_BOX) or ""
        except Exception:      # noqa: BLE001 - OCR 只是判据，读不到就按 no_page 处理
            txt = ""
        opened = "公会捐献" in txt or "金币捐献" in txt
        if not opened:
            log.warn(f"  公会捐献：点 {L.GUILD_DONATE} 后没读到捐献面板文字"
                     f"（OCR：{txt.strip()[:24]!r}），不乱点")
            self.ui.press(L.GUILD_DONATE_CLOSE, 200, expect="none")
            self.ui.wait(0.9)
            return "no_page"
        status = "unclear"
        if vision.is_gold(im, *L.GUILD_DONATE_GOLD, r=16):
            self.ui.press(L.GUILD_DONATE_GOLD, 250)
            self.ui.wait(2.0)
            after = self.shot("donate_after")
            self.ui.press(L.BLANK, 150, expect="none")
            self.ui.wait(0.7)
            if not vision.is_gold(after, *L.GUILD_DONATE_GOLD, r=16):
                status = "done"
            else:
                log.info("  公会捐献：点了金币捐献但按钮仍是金色（可能只是提示框），不记成功")
                status = "unclear"
        elif "已捐" in txt:
            status = "already"
        else:
            log.info(f"  公会捐献：金币档按钮不是金色、面板也没写「已捐」（OCR 片段："
                     f"{txt.strip()[:40]!r}），本轮不记成功")
        self.ui.press(L.GUILD_DONATE_CLOSE, 200, expect="none")
        self.ui.wait(0.9)
        return status

    def trial_enter(self) -> None:
        self.ui.press(L.GUILD_TRIAL, 250)
        self.ui.wait(2.4)

    def beast_enter(self) -> None:
        self.ui.press(L.BEAST_ENTRY, 250)
        self.ui.wait(2.4)

    def beast_ready(self) -> bool:
        """公会圣兽页「挑战」金色 = 已开放且还有次数（中午 12 点后开放，每日 5 次）。"""
        return vision.is_gold(self.shot("beast"), *L.BEAST_GO, r=16)

    def trial_challenge(self, tries: int = 3, gap: float = 1.0) -> bool:
        """点「挑战」：本轮已通关时会出现「扫荡」，挑战按钮从正中挪到右侧，两个位置都查。

        次数为 0 时按钮仍是金色、点下去只飘一行「今日剩余挑战次数不足」，所以按完要
        确认真的进了布阵页，没进就算没有次数。

        2026-11-10 实测：刚买完次数时页面上还挂着提示/动画，第一帧可能读不到金钮或
        点击被吞掉（logs/_verify_gtrial3 那次买到 1 次却报「次数仍不足」）。这里改成
        轮询：最多 tries 轮，每轮重抓一帧找金钮，点完仍不在布阵页就等一会儿再来。
        """
        for i in range(max(1, tries)):
            im = self.shot(f"trial{i}")
            for pos in (L.GUILD_TRIAL_GO, L.GUILD_TRIAL_GO_ALT):
                if not vision.is_gold(im, *pos, r=16):
                    continue
                self.ui.press(pos, 250, label=f"gtrial_go{i}", expect="none")
                self.ui.wait(2.6)
                after = self.shot(f"trial_dep{i}")
                if vision.is_green(after, *L.DEPLOY, r=18):
                    return True
                log.info(f"  公会试炼：点了「挑战」没进布阵页（第 {i + 1}/{tries} 次），再试")
                self.ui.wait(gap)
                break
            else:
                # 本帧两处都没有金钮：可能还在动画/提示里，等一下再抓
                self.ui.wait(gap)
        return False

    def trial_attempts(self, im=None) -> "int | None":
        """读「日次数：N」。读不到返回 None。

        2026-11-10：旧版只看「点了购买后确认钮消失」就认买到，
        钻石不足时游戏只弹提示、确认钮一样消失 → 假账。现在要求这个数字真的 +1。
        """
        if not textocr.available():
            return None
        try:
            txt = textocr.read_text(im if im is not None else self.shot("gtrial_times"),
                                    L.GUILD_TRIAL_TIMES_TEXT)
            return textocr.read_remain(txt)
        except Exception:  # noqa: BLE001
            return None

    def trial_buy_attempt(self) -> bool:
        """点次数行右边的「+」→ 读弹窗金额 → 点「购买」。返回是否真的买到。

        2026-11-10 真帧：那个「+」在 (428,1046)（旧 (425,1015) 高 31px，点空 →
        买次数永远失败）。弹窗是预制款：`提示 / 花费 20购买一次挑战次数？/
        （当前拥有：N)`，底部左「取消」(248,776)、右金「购买」(472,776)。
        这里必须真的读到「购买一次挑战次数」才往下点，点完还要复核弹窗关掉了；
        真账由调用方用「主城钻石前后差」核对。
        """
        # 2026-11-10 实机：点「+」后弹窗有 1.5~2.5s 的滑入动画，抓早一帧就只看到原页面
        # （第 36 轮 06:25 那次就是这样误判成「买满了」）。这里轮询到弹窗真的出现，
        # 必要时再补点一次「+」（最多 2 次点击），整体预算 ~5s。
        im = self.shot("buy0")
        att0 = self.trial_attempts(im)     # 购买前的次数（做 +1 对比）
        txt = ""
        for attempt in range(5):
            try:
                txt = textocr.read_text(im, L.GUILD_TRIAL_BUY_BOX) or ""
            except Exception:  # noqa: BLE001
                txt = ""
            if "购买一次挑战次数" in txt or vision.modal_dim(im):
                break
            if attempt == 0:
                self.ui.press(L.GUILD_TRIAL_BUY, 220, label="gtrial_buy_plus",
                              expect="none")
            elif attempt == 2:
                self.ui.press(L.GUILD_TRIAL_BUY, 220, label="gtrial_buy_plus_retry",
                              expect="none")
            self.ui.wait(0.9)
            im = self.shot(f"buy{attempt + 1}")
        if "购买一次挑战次数" not in txt and not vision.modal_dim(im):
            log.info("  公会试炼：点「+」后没弹出购买弹窗（补点 1 次仍未出现，"
                     "可能今天买满了/未开放）")
            return False
        m = re.search(r"花费\s*(\d+)", txt.replace(" ", ""))
        cost = m.group(1) if m else "?"
        if not vision.is_gold(im, *L.GUILD_TRIAL_BUY_OK, r=16):
            log.info(f"  公会试炼：购买弹窗里没有金色「购买」（读到「{txt[:24]}」），取消本次购买")
            self.ui.press(L.GUILD_TRIAL_BUY_CANCEL, 200, label="gtrial_buy_cancel", expect="none")
            self.ui.wait(1.2)
            return False
        self.ui.press(L.GUILD_TRIAL_BUY_OK, 220, label="gtrial_buy_ok", expect="none")
        self.ui.wait(2.0)
        after = self.shot("buy_after")
        if vision.is_gold(after, *L.GUILD_TRIAL_BUY_OK, r=16):
            log.info("  公会试炼：点了「购买」后确认钮仍在（确认没生效），不算买到次数")
            return False
        # …还要看到「日次数：N」真的 +1（旧版只凭「确认钮消失」就认买到，钻石不足时会假账）
        att1 = self.trial_attempts(after)
        if att1 is None:
            log.info("  公会试炼：点了「购买」但读不到「日次数」（缺证），不认这次购买")
            return False
        if att0 is not None and att1 <= att0:
            log.info(f"  公会试炼：点了「购买」但次数没增加（{att0}→{att1}，可能钻石不足），不认这次购买")
            return False
        log.info(f"  公会试炼买次数：买到 1 次（弹窗写花费 {cost}，日次数 {att0}→{att1}）")
        return True

    def trial_save(self, timeout: float = 200.0) -> bool:
        """等结算：保存 → 胜利确定。返回是否真的点到了「确定」。

        2026-11-09 假成功审计 m4：原来返回 None，调用方拿不到结果。

        2026-11-10 实测（logs/_verify_gtrial4 06:36 那次）：公会试炼一轮战斗要
        60~110 秒（帧 `logs/screens/guild_res_25.png` 显示「公会试炼第18轮 01:04」，
        classify=BATTLE、没有跳过键），旧版只等 6×5s=30s 就报「结算页等了 30s」，
        于是每轮都把好局记成「没保存」。现在按截止时间轮询：战斗中就等，见到
        金色「保存」就点，见到金色「确定」才算完成。
        """
        end = time.time() + max(20.0, float(timeout))
        while time.time() < end:
            im = self.shot("res")
            if vision.is_gold(im, *L.GUILD_TRIAL_SAVE, r=16):
                self.ui.press(L.GUILD_TRIAL_SAVE, 220, label="gtrial_save", expect="none")
                self.ui.wait(2.5)
                continue
            if vision.is_gold(im, *L.GUILD_TRIAL_OK, r=16):
                self.ui.press(L.GUILD_TRIAL_OK, 220, label="gtrial_ok", expect="none")
                self.ui.wait(2.0)
                return True
            fighting = vision.classify(im) == State.BATTLE
            self.ui.wait(2.0 if fighting else 4.0)
        log.info(f"  结算页等了 {timeout:.0f}s 没看到金色「确定」（保存/胜利钮都没出现）")
        return False


# ---------- 战役 / 悬赏 ----------

class CampaignPage(Page):
    name = "campaign"

    def open_stage(self) -> bool:
        """点关卡节点并确认「关卡详情/挑战」真的出现了。

        2026-11-09 假成功审计 m1：原来这里只有一句 `pass`（判据被丢弃，无条件 True），
        点空 / 点到位阶未开的节点都会报成功。
        """
        im = self.shot("map")
        if not vision.is_gold(im, 640, 480, r=14):     # 冒险地图上 悬赏入口是金色图标
            log.info("  战役：地图 (640,480) 没看到金色节点，仍点一次并复核结果")
        self.ui.press(L.CAMPAIGN_NODE, 250)
        self.ui.wait(2.0)
        after = self.shot("stage_open")
        ok = (vision.is_gold(after, *L.CAMPAIGN_GO, r=18)
              or vision.is_gold(after, *L.CAMPAIGN_STAGE_BTN, r=18))
        if not ok:
            log.info("  战役：点了关卡节点后「挑战/关卡详情」都没出现，认为没打开关卡")
        return ok

    def challenge(self) -> bool:
        """点「挑战」并确认进了布阵页。

        2026-11-09 假成功审计 M11：四个试炼/战役页里唯独这里点完就 return True。
        对照正例 TowerPage/LegendPage/TreePage.challenge 都要求 is_green(*L.DEPLOY)。
        """
        im = self.shot("stage")
        if not vision.is_gold(im, *L.CAMPAIGN_GO, r=18):
            return False
        self.ui.press(L.CAMPAIGN_GO, 250)
        self.ui.wait(1.8)
        return vision.is_green(self.shot("camp_dep"), *L.DEPLOY, r=18)


class BountyPage(Page):
    name = "bounty"

    def at_bounty(self, im=None) -> bool:
        """悬赏页：顶部「悬赏任务」大标题（2026-10-30 改版后的新 logo）。"""
        return T.VI.find(im or self.shot("at"), "标题_悬赏任务.png", 0.90,
                         roi=(40, 80, 720, 220)) is not None

    def enter(self) -> bool:
        """战役地图右侧的悬赏入口（图标会随地图状态换位，模板优先 + 固定点兜底）。

        2026-10-30 实测：固定点 (632,445) 有时会点到关卡直接进战斗，
        所以按完先确认是不是悬赏页；不是就退出来，避免在战役里瞎打。
        """
        for attempt in range(2):
            MainCity(self.ui).tab(L.TAB_CAMPAIGN)
            im = self.shot("camp_map")
            m = T.VI.find(im, "悬赏入口.png", 0.80)
            self.ui.press(m.center if m else L.BOUNTY_ENTRY, 250)
            self.ui.wait(2.2)
            after = self.shot("bounty_chk")
            if self.at_bounty(after):
                return True
            st = vision.classify(after)
            if st in (State.DEPLOY, State.BATTLE):
                # 误点进关卡：退回战役地图，再试一次
                self.ui.press(L.BACK, 250, expect="none")
                self.ui.wait(1.4)
                if vision.lineup_save_dialog(self.ui.screen("save?")):
                    self.ui.press(L.LINEUP_SAVE, 220)
                    self.ui.wait(1.4)
                self.ui.press(L.BACK, 250, expect="none")
                self.ui.wait(1.4)
        log.warn("  悬赏入口打不开")
        return False

    def points(self, im) -> int | None:
        """读顶部「14972/26000」的当前积分（读不到返回 None，不返回 0）。

        注意：OCR 给的是「14972 26000」，若先去掉空格会拼成 1497226000，
        因此必须在**原始文本**上用 `A/B` 形式匹配。
        """
        if not textocr.available():
            return None
        try:
            txt = textocr.read_text(im, L.BOUNTY_POINTS_BOX) or ""
        except Exception:  # noqa: BLE001
            return None
        m = re.search(r"(\d{3,6})\s*/\s*(\d{3,6})", txt)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d{3,6})", txt)
        return int(m.group(1)) if m else None

    def detail_open(self, im) -> bool:
        """是否停在「任务详情」面板上（点「接受」之后的那一层）。"""
        if not textocr.available():
            return False
        try:
            txt = textocr.read_text(im, L.BOUNTY_DETAIL_BOX) or ""
        except Exception:  # noqa: BLE001
            return False
        return any(k in txt for k in L.BOUNTY_DETAIL_KEYS)

    def detail_cost(self, im) -> tuple[int, int] | None:
        """读「14972/1800」→ (当前积分, 本单花费)。读不到返回 None。"""
        if not textocr.available():
            return None
        try:
            txt = textocr.read_text(im, L.BOUNTY_DETAIL_COST_BOX) or ""
        except Exception:  # noqa: BLE001
            return None
        m = re.search(r"(\d{3,6})\s*/\s*(\d{2,5})", txt)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    def accept_row(self, y: int, label: str = "") -> tuple[bool, int, str]:
        """接一条悬赏：接受 → 「一键上阵」→ 「派遣」，三条证据齐全才算接上。

        证据：①面板真的出现（OCR 含「一键上阵」「派遣」）②「派遣」后面板关闭
        ③顶部积分真的减少（减少值即本单花费）。缺一条都返回 False，绝不虚记。
        """
        tag = f"bounty_{label or y}"
        before = self.shot(f"{tag}_before")
        pts0 = self.points(before)
        self.ui.press((L.BOUNTY_ACCEPT_X, y), 250, label=f"{tag}_accept", expect="none")
        im = None
        for i in range(3):
            self.ui.wait(1.2)
            im = self.shot(f"{tag}_detail{i}")
            if self.detail_open(im):
                break
            if i == 0:
                self.ui.press((L.BOUNTY_ACCEPT_X, y), 250, label=f"{tag}_accept2",
                              expect="none")
        if im is None or not self.detail_open(im):
            self.ui.press(L.BLANK, 150, expect="none")
            return False, 0, "点「接受」后没弹出「任务详情」面板（可能已接/不可接）"
        pair = self.detail_cost(im)
        cost = pair[1] if pair else None
        # 「一键上阵」先把队伍填满 —— 不点这一步，「派遣」按了也不生效（2026-11-10 实测）
        self.ui.press(L.BOUNTY_FILL, 250, label=f"{tag}_fill", expect="none")
        self.ui.wait(1.6)
        self.ui.press(L.BOUNTY_SEND, 220, label=f"{tag}_send", expect="none")
        self.ui.wait(2.4)
        after = self.shot(f"{tag}_after")
        if self.detail_open(after):
            self.ui.press(L.BLANK, 150, expect="none")
            return False, 0, "点了「派遣」后面板还在（没接上）"
        pts1 = self.points(after)
        if pts0 is None or pts1 is None:
            return False, 0, f"接单后积分读不到（{pts0}→{pts1}），缺证不认"
        spent = pts0 - pts1
        if spent <= 0:
            return False, 0, f"「派遣」后面板关了但积分没减少（{pts0}→{pts1}），不认这一单"
        return True, int(spent), "已接单"

    def accept(self, idx: int) -> bool:
        pos = L.BOUNTY_ACCEPT[idx]
        before = self.shot("before")
        self.ui.press(pos, 250)
        self.ui.wait(1.8)
        after = self.shot("after")
        return not vision.similar(before, after)


# ---------- 军衔 ----------

class RankPage(Page):
    name = "rank"

    def claim_rows(self) -> int:
        """官阶奖励：领取后该行会被移到列表末尾、整列上浮，固定 y 一定会漏领。

        2026-10-31 实测流程：点右侧金色「领取」→ 全屏「获得奖励」浮层（点空白关闭）
        → 该行变成绿色「已领取」并被追加到列表末尾，其上的行整体上移。
        所以改成动态识别：在右侧按钮列里找金色按钮 → 点一个 → 关浮层 → 再找；
        当前屏没有了就往下滚，连续两屏都没有才结束。
        """
        # 2026-11-09：进页时的滚动位置会沿用上一次（promote() 先 scroll_up 过），
        # 而旧码「连续 1 屏没金钮就收手」——奖励行在下面一两屏时就整片漏领。
        # 实测：军衔页「累计登录28天 28/28」的「领取」在 y=752，一次 scroll_up 后就
        # 落到扫描区外，任务报「领奖 0 行」。改成先归位到顶部，再容忍 4 屏空。
        for _ in range(2):
            self.ui.dev.scroll_up(360, 1000, 400, 500)
            self.ui.wait(0.8)
        n = 0
        idle = 0
        screens = 0
        for _ in range(30):
            im = self.shot("rows")
            screens += 1
            bands = vision.gold_button_bands(im, L.RANK_CLAIM_ZONE)
            if not bands:
                if idle >= 4:
                    break
                idle += 1
                self.ui.dev.swipe(*L.RANK_LIST_SCROLL, 500)
                self.ui.wait(1.0)
                continue
            idle = 0
            cx, cy, _ = bands[0]
            # 2026-11-10：不能用 press 的返回值判成败（实测点中了也返回 False），
            # 改成前后帧对比 + 自动关浮层（见 Page.claim_click）。
            if not self.claim_click((cx, cy), "rank_claim"):
                log.info("  军衔：点「领取」后画面没变化（该行已失效），停止")
                break
            n += 1
        if n == 0:
            log.info(f"  军衔：官阶奖励扫了 {screens} 屏，没有可领的行（都领过或条件未达成）")
        else:
            log.info(f"  军衔：官阶奖励扫了 {screens} 屏，领取 {n} 行")
        return n

    def promote(self) -> bool:
        """点「晋升」。

        2026-11-09 假成功审计两处修正：
          ① 兜底坐标只存实例字段 `self._promote_pos`，**不再** 改写 `L.RANK_PROMOTE`
             模块全局（一次误判会污染本进程后续所有判据）；
          ② 点完要复核（画面确实变了 / 出现了确认钮）才算晋升成功，否则 return False
             —— 旧码无论如何都 `return True`，`promoted += 1` 无条件累加。
        """
        self.ui.dev.scroll_up(360, 1000, 400, 500)
        self.ui.wait(1.2)
        im = self.shot("promo")
        pos = L.RANK_PROMOTE
        if not vision.is_gold(im, *pos, r=18):
            # 界面整体下移/改版时，按「最大金色圆钮」兜底（实测晋升钮就是屏内最宽的金块）
            bands = vision.gold_button_bands(im, (240, 740, 480, 1010))
            if not bands:
                log.info("  军衔：页面上没有金色的「晋升」按钮（条件未达成或已满级）")
                return False
            pos = bands[0][:2]
            self._promote_pos = pos
            log.info(f"  军衔：晋升按钮按金色兜底定位到 {pos}")
            im = self.shot("promo2")
        if not self.ui.press(pos, 220):
            log.info(f"  军衔：点晋升 {pos} 没有反应，不算晋升")
            return False
        self.ui.wait(2.0)
        im = self.shot("promo_ok")
        confirmed = False
        if vision.is_gold(im, *L.RANK_PROMOTE_OK, r=18):
            self.ui.press(L.RANK_PROMOTE_OK, 220)
            self.ui.wait(2.0)
            confirmed = True
        else:
            after = self.shot("promo_ok2")
            if not vision.similar(im, after):
                self.ui.press(L.BLANK, 150, expect="none")
                self.ui.wait(1.0)
                confirmed = True
        if not confirmed:
            log.info("  军衔：点了晋升但画面没有任何变化（条件未达成），不算晋升")
        return confirmed
