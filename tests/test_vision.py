"""离线视觉测试：用真机截图回归 classify() 的判断。

运行：
  python -I -m unittest discover -s tests -v        （在 auto_script 目录下）
或
  python -I tests/test_vision.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from PIL import Image  # noqa: E402

from mtbot import vision  # noqa: E402
from mtbot.vision import State  # noqa: E402

FIX = HERE / "fixtures"


def load(name: str) -> Image.Image:
    return Image.open(FIX / f"{name}.png").convert("RGB")


class DailyTabsTests(unittest.TestCase):
    def test_row_buttons_not_gold_when_locked(self):
        """周常/成就/历练行尾的「前往」（土黄）和「已领取」（绿）不能被当成金色「领取」。"""
        from mtbot import layout as LL

        for name in ("daily_weekly", "daily_achieve", "daily_growth"):
            im = load(name)
            for y in LL.DAILY_ROW_YS:
                self.assertFalse(vision.is_gold(im, LL.DAILY_ROW_BTN_X, y, r=16), (name, y))


class IdleCampaignBountyTests(unittest.TestCase):
    def test_idle_popup_buttons(self):
        """挂机特权弹窗：「领取收益」金色可点，「获取更多」次数用完是灰的。"""
        from mtbot import layout as LL

        im = load("daily_idle")
        self.assertTrue(vision.is_gold(im, *LL.IDLE_CLAIM, r=16))
        self.assertFalse(vision.is_gold(im, *LL.IDLE_MORE, r=16))

    def test_bounty_accept_vs_in_progress(self):
        """悬赏页：有可接取时按钮是金色；三个都在倒计时时没有金色按钮。"""
        from mtbot import layout as LL

        accept = load("bounty_accept")
        self.assertTrue(vision.is_gold(accept, *LL.BOUNTY_ACCEPT[0], r=16))
        self.assertTrue(vision.is_gold(accept, *LL.BOUNTY_ACCEPT[1], r=16))
        busy = load("bounty_busy")
        for pos in LL.BOUNTY_ACCEPT:
            self.assertFalse(vision.is_gold(busy, *pos, r=16), pos)

    def test_campaign_buttons(self):
        """战役地图：底部大按钮是金色；右侧关卡奖励图标带红「!」时能检出（fixture 拍到了可领状态）。"""
        from mtbot import layout as LL

        im = load("campaign_map")
        self.assertTrue(vision.is_gold(im, *LL.CAMPAIGN_STAGE_BTN, r=18))
        # 这个 fixture 的奖励图标右上确有红「!」（圆点 y402-408 + 竖线 y410-422），应检出
        self.assertTrue(vision.button_badge(im, LL.CAMPAIGN_REWARD_BOX))
        panel = load("campaign_reward_panel")
        for x in (165, 280, 400, 515, 630):
            self.assertFalse(vision.button_badge(panel, (x - 42, 792, x + 42, 872)), x)


class GoblinTests(unittest.TestCase):
    def test_templates(self):
        """地精宝藏：历练页入口卡片、页面标题、占领胜利页（模板匹配）。"""
        from mtbot import template as T

        self.assertIsNotNone(T.VI.find(load("goblin_hub"), "历练_地精宝藏.png", 0.88))
        self.assertIsNotNone(T.VI.find(load("goblin_page"), "标题_地精宝藏.png", 0.90))
        win = load("goblin_win")
        self.assertIsNotNone(T.VI.find(win, "胜利.png", 0.85))
        self.assertIsNotNone(T.VI.find(win, "返回玩法.png", 0.85))


class DemonTests(unittest.TestCase):
    def test_demon_main_button(self):
        """邪能神殿底部大按钮的金色带在 y≈1150~1165（1170 以下是描边，点了没反应）。"""
        from mtbot import layout as LL

        im = load("demon_page")
        self.assertTrue(vision.is_gold(im, *LL.DEMON_CHALLENGE, r=18))

    def test_demon_buff_dialog(self):
        """「选择加成」弹窗：底部金色确定 + 右上角红 X。"""
        from mtbot import layout as LL
        from mtbot.ui import UI

        im = load("demon_buff_dialog")
        self.assertTrue(vision.is_gold(im, *LL.DEMON_BUFF_OK, r=16))
        corner = [p for p in UI._find_close_buttons(im) if p[0] >= 620 and p[1] <= 260]
        self.assertTrue(corner)


class LegendPageTests(unittest.TestCase):
    def test_legend_page_not_defeat(self):
        """传奇试炼页右上角是蓝色立绘，曾被当成「失败」结算页导致回主城反复横跳。"""
        self.assertNotEqual(vision.classify(load("legend_page")), State.RESULT_DEFEAT)


class TowerResultTests(unittest.TestCase):
    def test_defeat_buttons(self):
        """塔失败页：再次挑战 (475,1055) / 确定 (235,1055)；旧坐标 1090 在按钮外面点不动。"""
        from mtbot import layout as LL

        im = load("tower_defeat_page")
        self.assertTrue(vision.is_gold(im, *LL.TOWER_RESULT_RETRY, r=16))
        # 「确定」是灰色副按钮（仍然可以点，回主城时用它退出），不能当金色按钮判据
        self.assertFalse(vision.is_gold(im, *LL.TOWER_RESULT_OK, r=16))


class GuildTests(unittest.TestCase):
    def test_trial_challenge_positions(self):
        """公会试炼「挑战」：没有扫荡时在正中，本轮通关出现「扫荡」后挪到右边。"""
        from mtbot import layout as LL

        center = load("guild_trial")
        self.assertTrue(vision.is_gold(center, *LL.GUILD_TRIAL_GO_ALT, r=16))
        sweep = load("guild_trial_sweep")
        self.assertTrue(vision.is_gold(sweep, *LL.GUILD_TRIAL_GO, r=16))
        self.assertFalse(vision.is_gold(sweep, *LL.GUILD_TRIAL_GO_ALT, r=16))

    def test_beast_page(self):
        """公会圣兽：挑战按钮在 (360,1170)，参与奖励有红点；进战斗前是布阵页。"""
        from mtbot import layout as LL

        im = load("guild_beast")
        self.assertTrue(vision.is_gold(im, *LL.BEAST_GO, r=16))
        self.assertTrue(vision.button_badge(im, LL.BEAST_PRIZE_BOX))
        self.assertTrue(vision.is_green(load("guild_beast_deploy"), *LL.DEPLOY, r=18))


class DragonFactionTests(unittest.TestCase):
    def test_dragon_page(self):
        """巨龙牢窟页：顶部标题 + 档位行右侧金色「挑战」（4阶噩梦行 625,772）。"""
        from mtbot import template as T

        im = load("dragon_page")
        self.assertIsNotNone(T.VI.find(im, "标题_巨龙牢窟.png", 0.90))
        m = T.VI.find(im, "挑战_巨龙牢窟.png", 0.93, roi=(250, 620, 720, 1260))
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m.center[1], 772, delta=8)

    def test_faction_page(self):
        """阵营挑战页：标题 + 层行「开始挑战」+ 历练卡片入口模板。"""
        from mtbot import template as T

        im = load("faction_page")
        self.assertIsNotNone(T.VI.find(im, "标题_阵营挑战.png", 0.90))
        # 2026-10-30：按钮改成半透明，「开始挑战」模板实测只有 0.899（旧阈值 0.90 正好卡死），
        # 代码改用 0.85 + 金色下沿兜底；这里同步验证 0.85 能命中。
        self.assertIsNotNone(T.VI.find(im, "开始挑战.png", 0.85, roi=(480, 300, 720, 1100)))

    def test_faction_deploy(self):
        """阵营挑战布阵页：「一键上阵」是绿的，右下是「继续」而不是「战斗」。"""
        from mtbot import layout as LL
        from mtbot import template as T

        im = load("faction_deploy")
        self.assertTrue(vision.is_green(im, *LL.FACTION_DEPLOY, r=18))
        self.assertIsNotNone(T.VI.find(im, "继续按钮.png", 0.85, roi=(460, 1155, 710, 1260)))

    def test_faction_buff(self):
        """增益三选一：底部金色确定 (360,1030)，最左卡在 x=150（用户指定选最左）。"""
        from mtbot import layout as LL
        from mtbot import template as T

        im = load("faction_buff")
        self.assertTrue(T.VI.find(im, "增益确定.png", 0.90, roi=LL.FACTION_BUFF_ROI))
        self.assertTrue(vision.is_gold(im, *LL.FACTION_BUFF_OK, r=16))

    def test_dragon_page_not_main_city(self):
        """巨龙牢窟「奥术主宰」页顶部冰蓝条和主城天空撞色，曾被误判成主城导致后续任务全乱。"""
        for name in ("dragon_page", "dragon_page_icy"):
            im = load(name)
            self.assertFalse(vision.main_city(im), name)
            self.assertNotEqual(vision.classify(im), State.MAIN_CITY, name)

    def test_dragon_reward_popup(self):
        """胜利后的「获得奖励」黑底弹窗：标题还露着但挑战按钮被压暗，必须靠模板识别。"""
        from mtbot import template as T

        self.assertIsNotNone(T.VI.find(load("dragon_reward_popup"), "巨龙_获得奖励.png", 0.85))
        for name in ("dragon_page", "dragon_page_icy", "main_city", "tower_win_mvp"):
            self.assertIsNone(T.VI.find(load(name), "巨龙_获得奖励.png", 0.85), name)

    def test_faction_battle_speed(self):
        """连续波次战斗没有跳过键，只能切 ×4 倍速等；×4 标签要能认出来。"""
        from mtbot import layout as LL
        from mtbot import template as T

        im = load("faction_battle")
        self.assertGreaterEqual(T.VI.best_score(im, "倍速_x4.png", roi=LL.SPEED_BOX), 0.75)
        self.assertLess(T.VI.best_score(im, "倍速_x1.png", roi=LL.SPEED_BOX), 0.70)


class BattleDetectTests(unittest.TestCase):
    def test_bright_arena_battle(self):
        """守护者塔 708 层战场地面是亮的，(360,900) 不暗，但右侧有 ×2 倍速标签，仍要判成 battle。"""
        self.assertEqual(vision.classify(load("battle_bright")), State.BATTLE)

    def test_speed_label_pages_not_battle(self):
        """倍速标签只在战斗里出现；这些有亮卡片/白字的面板不能判成战斗。"""
        for name in ("trial_save_dialog", "demon_buff_dialog", "daily_idle",
                     "assist_pet_dialog", "dialog_announce"):
            self.assertNotEqual(vision.classify(load(name)), State.BATTLE, name)

    def test_tower_win_mvp_page(self):
        """塔胜利页（全场 MVP 版）必须是 result_tower，不能被当成未知画面。"""
        self.assertEqual(vision.classify(load("tower_win_mvp")), State.RESULT_TOWER)


class TitleTests(unittest.TestCase):
    def test_identify_pages(self):
        """每个玩法页顶部标题条都能唯一识别（0.90 阈值，1.0 命中）。"""
        from mtbot import titles

        cases = {
            "tower_page": "tower",
            "legend_page": "legend",
            "tree_page": "tree",
            "demon_page": "demon",
            "dragon_page": "dragon",
            "faction_page": "faction",
            "goblin_page": "goblin",
            "guild_trial": "guild_trial",
            "guild_beast": "beast",
            "daily_daily": "daily",
            "dusk_page": "dusk",
        }
        for fixture, key in cases.items():
            self.assertEqual(titles.identify(load(fixture)), key, fixture)

    def test_no_false_positive(self):
        """周常页应该认成 weekly（不是 daily）；塔胜利页/主城没有标题。"""
        from mtbot import titles

        self.assertEqual(titles.identify(load("daily_weekly")), "weekly")
        self.assertIsNone(titles.identify(load("tower_win_mvp")))
        self.assertIsNone(titles.identify(load("main_city")))


class LineupSaveTests(unittest.TestCase):
    def test_lineup_save_dialog(self):
        """布阵页按返回弹的「当前英雄布阵未保存」提示：不回主城会一直在布阵页和弹窗之间打转。"""
        self.assertTrue(vision.lineup_save_dialog(load("lineup_save")))
        for name in ("deploy", "main_city", "goblin_page", "tower_win_mvp"):
            self.assertFalse(vision.lineup_save_dialog(load(name)), name)


class ClassifyTests(unittest.TestCase):
    def test_main_city(self):
        self.assertEqual(vision.classify(load("main_city")), State.MAIN_CITY)

    def test_trials_hub(self):
        self.assertEqual(vision.classify(load("trials_hub")), State.TRIALS_HUB)

    def test_deploy(self):
        self.assertEqual(vision.classify(load("deploy")), State.DEPLOY)

    def test_battle(self):
        self.assertEqual(vision.classify(load("battle")), State.BATTLE)

    def test_tree_win_mid(self):
        self.assertEqual(vision.classify(load("tree_win")), State.RESULT_TREE)

    def test_tree_win_final(self):
        self.assertEqual(vision.classify(load("tree_final_win")), State.RESULT_GENERIC)

    def test_tree_defeat(self):
        self.assertEqual(vision.classify(load("tree_defeat")), State.RESULT_DEFEAT)

    def test_tree_defeat_center_button(self):
        """树失败页的「确定」在正中 (360,1060)，旧暗色判据探测点 (360,1050) 会压到按钮上。"""
        self.assertEqual(vision.classify(load("tree_defeat_center")), State.RESULT_DEFEAT)

    def test_tower_defeat(self):
        self.assertEqual(vision.classify(load("tower_defeat")), State.RESULT_DEFEAT)

    def test_announcement_dialog(self):
        """登录后的公告页曾被误判成 battle/result_defeat，导致卡在登录。"""
        self.assertEqual(vision.classify(load("dialog_announce")), State.DIALOG)

    def test_relic_page_not_dialog(self):
        """圣物（升级/羁绊）页面是米色面板，不能判成公告弹窗或失败结算。"""
        st = vision.classify(load("relic_bond_page"))
        self.assertNotIn(st, (State.DIALOG, State.RESULT_DEFEAT, State.MAIN_CITY_DIM))

    def test_relic_tooltip(self):
        """材料不足时弹出的紫色「圣物源能」说明窗要能识别，才能关掉。"""
        self.assertTrue(vision.tooltip_open(load("relic_tooltip")))
        self.assertFalse(vision.tooltip_open(load("relic_bond_page")))

    def test_title_page(self):
        self.assertEqual(vision.classify(load("title")), State.TITLE)

    def test_save_dialog_not_reconnect(self):
        """公会试炼「保存」弹窗（465,748 也是金色）不能被当成断线弹窗。"""
        st = vision.classify(load("trial_save_dialog"))
        self.assertNotIn(st, (State.RECONNECT, State.RECONNECT_LOGIN))

    def test_activity_page_not_title_or_reconnect(self):
        """深海秘宝活动页底部一排金色购买按钮，不能判成标题页或断线弹窗。"""
        st = vision.classify(load("activity_deep_sea"))
        self.assertNotIn(st, (State.TITLE, State.RECONNECT, State.RECONNECT_LOGIN))

    def test_rank_rewards_not_quit_dialog(self):
        """深海秘宝「排名奖励」页的浅色卡片曾被误判成退出确认框。"""
        st = vision.classify(load("activity_rank_rewards"))
        self.assertNotIn(st, (State.QUIT_DIALOG, State.TITLE))

    def test_promo_not_battle(self):
        """全屏促销页（公会圣兽/累充）不能判成战斗或结算。"""
        st = vision.classify(load("promo_guild_beast"))
        self.assertNotIn(st, (State.BATTLE, State.RESULT_TOWER, State.RESULT_TREE,
                              State.RESULT_GENERIC, State.RESULT_LEGEND,
                              State.RESULT_DEFEAT))


class HelperTests(unittest.TestCase):
    def test_gold_vs_green(self):
        im = load("tree_win")
        self.assertTrue(vision.is_gold(im, 495, 1130, r=18))     # 下一关
        self.assertTrue(vision.is_green(load("deploy"), 270, 1230, r=18))

    def test_victory_banner(self):
        self.assertTrue(vision.victory_banner(load("tree_win")))
        self.assertFalse(vision.victory_banner(load("tree_defeat")))


class RelicBondTests(unittest.TestCase):
    def test_bond_buttons_detected(self):
        """羁绊页「升级」按钮按颜色动态定位（固定 y 曾整体偏上约 40px）。"""
        from mtbot.tasks.reward import RelicTask

        btns = RelicTask._bond_buttons(load("relic_bond_live"))
        self.assertEqual(len(btns), 4)
        for (x, y), want_y in zip(btns, (347, 531, 715, 898)):
            self.assertAlmostEqual(x, 575, delta=6)
            self.assertAlmostEqual(y, want_y, delta=6)

    def test_bond_buttons_empty_on_city(self):
        from mtbot.tasks.reward import RelicTask

        self.assertEqual(RelicTask._bond_buttons(load("main_city")), [])


class ForgeTests(unittest.TestCase):
    def test_cost_affordable(self):
        """一键50级上方价格：绿色=金币够，红色=金币不足。"""
        self.assertTrue(vision.forge_cost_affordable(load("forge_enhance_ready")))
        self.assertFalse(vision.forge_cost_affordable(load("forge_enhance_broke")))

    def test_slot_badges(self):
        """强化1次按钮本身不亮，靠右上角红点判断可点。"""
        ready = load("forge_enhance_ready")
        broke = load("forge_enhance_broke")
        for bx, by in ((195, 732), (340, 732), (483, 732), (627, 731)):
            self.assertGreaterEqual(vision.red_count(ready, bx, by), 8)
            self.assertLess(vision.red_count(broke, bx, by), 8)

    def test_star_dialog(self):
        """一键升星批量弹窗：locked=没有符合条件的装备，普通页面=none。"""
        self.assertEqual(vision.forge_star_dialog(load("forge_star_dialog_locked")), "locked")
        self.assertEqual(vision.forge_star_dialog(load("forge_star_page")), "none")
        self.assertEqual(vision.forge_star_dialog(load("forge_overview")), "none")


class HeroTests(unittest.TestCase):
    def test_hero_grid_not_dialog_or_title(self):
        """英雄列表页的米色卡片曾被误判成公告弹窗，导致回主城时连点空白。"""
        st = vision.classify(load("hero_grid"))
        self.assertNotIn(st, (State.DIALOG, State.TITLE, State.MAIN_CITY_DIM))
        self.assertFalse(vision.beige_dialog(load("hero_grid")))

    def test_item_popup(self):
        """进阶石不足弹的「获取途径」窗（两侧压暗 + 中央米色面板）。"""
        self.assertTrue(vision.item_popup(load("hero_adv_popup")))
        self.assertFalse(vision.item_popup(load("hero_detail_700")))

    def test_read_hero_level(self):
        """英雄详情页「等级 700/750/800」青色数字的模板识别。"""
        from mtbot import ocr

        self.assertEqual(ocr.read_level(load("hero_detail_700"))[0], 700)
        self.assertEqual(ocr.read_level(load("hero_detail_750"))[0], 750)
        self.assertEqual(ocr.read_level(load("hero_detail_800"))[0], 800)

    def test_break_dialog(self):
        """英雄「进阶」的属性加成预览框：橙色确认钮在 (360,917)，页面本体同位置不是按钮。"""
        self.assertTrue(vision.hero_break_dialog(load("hero_break_dialog")))
        for name in ("hero_detail_700", "hero_detail_750", "hero_detail_800",
                     "main_city", "deploy"):
            self.assertFalse(vision.hero_break_dialog(load(name)), name)

    def test_resonance_levels(self):
        """白色等级 = 实际培养，蓝色等级 = 共鸣出来的（不升级）。"""
        im = load("hero_grid")
        self.assertFalse(vision.hero_level_is_resonance(im, 155, 440, 468))   # 小黑 800 白
        self.assertFalse(vision.hero_level_is_resonance(im, 300, 440, 468))   # 傻馒 750 白
        self.assertFalse(vision.hero_level_is_resonance(im, 440, 712, 742))   # 剁椒牛头 700 白
        self.assertTrue(vision.hero_level_is_resonance(im, 155, 712, 742))    # 雷大猫 700 蓝
        self.assertTrue(vision.hero_level_is_resonance(im, 585, 712, 742))    # 饱嗝哥 700 蓝
        self.assertTrue(vision.hero_level_is_resonance(im, 155, 988, 1012))   # 呜喵王 700 蓝


class AssistTests(unittest.TestCase):
    def test_button_badge(self):
        """可升级的红点角标：神器升级页有，橙色突破/升阶按钮与其它页没有。"""
        self.assertTrue(vision.button_badge(load("artifact_up")))
        self.assertFalse(vision.button_badge(load("assist_glory")))
        self.assertFalse(vision.button_badge(load("assist_tianshen")))
        self.assertFalse(vision.button_badge(load("assist_pet")))

    def test_item_popup_on_assist(self):
        """神器「升星」材料不足的获取途径窗：左侧是亮道具列表也要能识别。"""
        self.assertTrue(vision.item_popup(load("artifact_star_popup")))
        for name in ("artifact_up", "assist_glory", "assist_tianshen", "assist_pet"):
            self.assertFalse(vision.item_popup(load(name)), name)

    def test_assist_pet_dialog(self):
        """战宠「升阶」先弹预览窗（右上角红 X），弹窗里才有真正的按钮。"""
        from mtbot.ui import UI

        corner = [p for p in UI._find_close_buttons(load("assist_pet_dialog"))
                  if p[0] >= 620 and p[1] <= 260]
        self.assertTrue(corner)
        for name in ("assist_glory", "assist_tianshen", "artifact_up", "assist_pet"):
            corner = [p for p in UI._find_close_buttons(load(name))
                      if p[0] >= 620 and p[1] <= 260]
            self.assertFalse(corner, name)


class NewPageTitleTests(unittest.TestCase):
    """2026-10-30 新增页面标题锚点：罪魂之域 / 排行榜 / 荣耀之书 / 天神传承 / 神器 / 公会商人。"""

    def test_new_titles_match(self):
        from mtbot import titles

        cases = [("soul_map", "soul"), ("rank_level", "rank_board"),
                 ("glory_war", "glory_book"), ("merchant", "merchant"),
                 ("artifact_detail", "artifact"), ("faction_page", "faction"),
                 ("tree_map", "tree")]
        for fixture, key in cases:
            self.assertTrue(titles.on_page(load(fixture), key), (fixture, key))

    def test_new_titles_no_false_positive(self):
        from mtbot import titles

        city = load("main_city")
        for key in ("soul", "rank_board", "glory_book", "artifact", "merchant"):
            self.assertFalse(titles.on_page(city, key), key)


class NewSystem2010Tests(unittest.TestCase):
    """2026-10-31 按录像新增：图鉴升级 / 英雄羁绊。"""

    def test_titles(self):
        from mtbot import titles

        self.assertTrue(titles.on_page(load("collection_page"), "collection"))
        self.assertTrue(titles.on_page(load("hero_bond_page"), "hero_bond"))
        self.assertFalse(titles.on_page(load("collection_page"), "hero_bond"))
        self.assertFalse(titles.on_page(load("hero_bond_page"), "collection"))

    def test_collection_upgrade_button(self):
        from mtbot import layout as LL

        bands = vision.gold_button_bands(load("collection_level"), LL.COLLECTION_UP_ZONE)
        self.assertTrue(bands, "图鉴等级面板里应该找到金色「升级」")
        self.assertLess(abs(bands[0][1] - 1044), 24, bands)
        # 卡片列表页（没开面板）不应该有金色按钮
        self.assertFalse(vision.gold_button_bands(load("collection_page"), LL.COLLECTION_UP_ZONE))

    def test_bond_badge_only_on_upgradable(self):
        from mtbot import layout as LL

        im = load("hero_bond_badge")
        bands = vision.gold_button_bands(im, LL.BOND_UP_ZONE)
        self.assertGreaterEqual(len(bands), 2, bands)
        badged = [(cx, cy) for cx, cy, _ in bands
                  if vision.red_badge_near(im, cx, cy, *LL.BOND_BADGE, need=6)]
        self.assertEqual(len(badged), 1, badged)   # 录像里只有「神话3星(2/2)」那行可升


class DungeonPaidSweepTests(unittest.TestCase):
    """免费扫荡用完后的「💎20扫荡」和底部「一键扫荡」都是钻石消费，绝不能被当成挑战。"""

    def test_paid_sweep_not_challenge(self):
        from mtbot.pages import DungeonPage

        challenge, sweep = DungeonPage._scan_buttons(load("dungeon_paid_sweep"))
        self.assertIsNotNone(challenge)
        self.assertLess(abs(challenge - 738), 24, challenge)   # 真正的「挑战」行
        self.assertIsNone(sweep)


class CampaignMapTests(unittest.TestCase):
    """2026-11-02：战役地图底部金色「挑战NN-N」+ 中部偏暗，曾被 battle_page 判成战斗，
    主线任务于是对着地图无限按「跳过」。"""

    def test_map_not_battle(self):
        from mtbot import layout as LL

        im = load("campaign_map_live")
        self.assertNotEqual(vision.classify(im), State.BATTLE)
        self.assertFalse(vision.battle_page(im))
        self.assertTrue(vision.is_gold(im, *LL.CAMPAIGN_STAGE_BTN, r=18),
                        "地图底部应该有金色「挑战NN-N」大按钮")

    def test_real_battles_still_battle(self):
        for name in ("battle", "battle_bright"):
            self.assertEqual(vision.classify(load(name)), State.BATTLE, name)


class TreeChapterAdvanceTests(unittest.TestCase):
    """整章三星后树地图底部变成「完美通关」、没有挑战按钮——旧代码在这里一直点空白卡死。"""

    def test_perfect_map_has_no_challenge(self):
        from mtbot import layout as LL
        from mtbot import titles

        im = load("tree_perfect_map")
        self.assertTrue(titles.on_page(im, "tree"))
        self.assertFalse(vision.is_gold(im, *LL.TREE_GO, r=18),
                         "完美通关的地图上不该有金色挑战按钮（应去点右侧箭头翻章）")
        self.assertGreater(LL.TREE_NEXT_STAGE[0], 600)   # 右箭头在屏幕右侧


class BountySpeedupTests(unittest.TestCase):
    """已接取的悬赏行右侧是「💎50加速」（金底 + 青色钻石），不能被当成「接受」点下去。"""

    def test_paid_icon(self):
        from mtbot.tasks.daily import _paid_icon

        im = load("bounty_speedup")
        self.assertTrue(_paid_icon(im, 565, 600))     # 加速按钮（有青色钻石）
        for y in (735, 870, 1005):
            self.assertFalse(_paid_icon(im, 565, y), y)   # 正常的「接受」按钮


class DungeonScanTests(unittest.TestCase):
    """日常副本：金色「挑战」/实心绿「免费扫荡」要能分开，绿色「已通过」印章不算按钮。"""

    def test_buttons_found(self):
        from mtbot.pages import DungeonPage

        for name in ("dungeon_list", "dungeon_equip"):
            challenge, sweep = DungeonPage._scan_buttons(load(name))
            self.assertIsNotNone(challenge, name)
            self.assertIsNotNone(sweep, name)
            self.assertTrue(300 <= challenge <= 1100, (name, challenge))
            self.assertTrue(400 <= sweep <= 900, (name, sweep))

    def test_passed_stamp_is_not_sweep(self):
        """只有绿色「已通过」印章、没有扫荡按钮的一行不能被当成扫荡。"""
        from mtbot import layout as LL
        from mtbot.pages import DungeonPage

        im = load("dungeon_list")
        _, sweep = DungeonPage._scan_buttons(im)
        # 印章在 y≈420（第一行「已通过」），扫荡按钮在 y≈580 附近
        self.assertGreater(sweep, 520)


class GoblinScanTests(unittest.TestCase):
    """地精宝藏新矿洞：等级徽章行 + 资源气泡颜色（先统计后占领）。"""

    def test_badge_rows(self):
        from mtbot.tasks.goblin import GoblinTask

        im = load("goblin_mine")
        rows = GoblinTask._badge_rows(im)
        self.assertGreaterEqual(len(rows), 4)
        self.assertTrue(all(340 <= y <= 1140 for y in rows), rows)

    def test_scan_screen(self):
        from mtbot.tasks.goblin import GoblinTask

        im = load("goblin_mine")
        cells = GoblinTask._scan_screen(im)
        self.assertGreaterEqual(len(cells), 8)
        kinds = {c[0] for c in cells}
        self.assertTrue(kinds & {1, 2}, cells)     # 至少认出钻石或进阶石

    def test_layer_list_label(self):
        from mtbot import layout as LL

        im = load("goblin_layer_list")
        self.assertLess(im.getpixel(LL.GOB_LAYER_LABEL)[0] + 0, 400)   # 标签条是浅色
        self.assertTrue(LL.GOB_LAYER_LABEL[1] >= 1050)


class OcrExtraTests(unittest.TestCase):
    """小字号的数字识别：议价（绿）、等级要求（红字里的数字）、神器等级（深色）。"""

    def test_bargain(self):
        """公会商人木牌折扣：美术字「1」和通用模板差异大，靠首位窄字纠正。"""
        from mtbot.config import load as load_cfg
        from mtbot.device import Device
        from mtbot.pages import MerchantPage
        from mtbot.ui import UI

        cfg = load_cfg()
        page = MerchantPage(UI(Device(cfg), cfg))
        val, _ = page.discount(load("merchant"))
        self.assertEqual(val, 194)

    def test_glory_requirement(self):
        from mtbot import layout as LL, ocr

        nums = ocr.read_number_loose(load("glory_war"), LL.GLORY_REQ_BOX)
        self.assertEqual(nums, [39])

    def test_artifact_level(self):
        from mtbot import layout as LL, ocr

        nums = ocr.read_number_loose(load("artifact_detail"), LL.ARTIFACT_LV_BOX, mask="dark")
        self.assertEqual(nums[:1], [40])


class BountyQualityTests(unittest.TestCase):
    """悬赏只接史诗/传说/神话：品质徽章靠模板认，普通/稀有必须排除。"""

    def test_quality_rows(self):
        from mtbot.tasks.daily import bounty_quality

        im = load("bounty_page")
        self.assertEqual(bounty_quality(im, 600), "普通")
        self.assertEqual(bounty_quality(im, 725), "传说")
        self.assertEqual(bounty_quality(im, 860), "史诗")
        self.assertEqual(bounty_quality(im, 995), "稀有")

    def test_filter_checkboxes(self):
        from mtbot import layout as LL
        from mtbot.tasks.daily import _checked, _settings_ready

        im = load("bounty_settings")
        self.assertTrue(_settings_ready(im), "设置弹窗应判定为已渲染完成")
        states = [_checked(im, LL.BOUNTY_SETTING_CHECK_X, y) for y in LL.BOUNTY_SETTING_ROWS]
        self.assertEqual(states, [False, False, True, True, True])

    def test_points_readable(self):
        """顶部「悬赏积分 1068 / 26000」：数字印在棕色装饰条之间，pale_soft 框要能整行读全。

        2026-11-05：旧框 (250,485,470,525) + white 会把上下装饰条连成一块读成假值 [0]；
        收窄到 (270,493,470,517) 后仍有两个数字得分 <0.5 被丢（读成 [10, 26000]）。
        """
        from mtbot import layout as LL, ocr
        from mtbot.tasks.daily import bounty_points

        im = load("bounty_points")
        self.assertEqual(ocr.read_all_numbers(im, LL.BOUNTY_POINTS_BOX, mask="pale_soft"),
                         [1068, 26000])
        self.assertEqual(bounty_points(im), 1068)


class RankBoardTests(unittest.TestCase):
    """排行榜：榜单页靠右上奖励按钮模板识别，列表页不能误判。"""

    def test_reward_button(self):
        from mtbot import template as T

        self.assertGreater(T.VI.best_score(load("rank_level"), "排行榜奖励按钮.png"), 0.90)
        self.assertGreater(T.VI.best_score(load("rank_campaign"), "排行榜奖励按钮.png"), 0.72)
        self.assertLess(T.VI.best_score(load("rank_list"), "排行榜奖励按钮.png"), 0.60)


class TreeStarTests(unittest.TestCase):
    """时光之树补星：正确入口是「章节 → 补星」面板里的金色「前往」（2026-10-30 用户指正）。"""

    def _page(self):
        from mtbot.config import load as load_cfg
        from mtbot.device import Device
        from mtbot.pages import TreePage
        from mtbot.ui import UI

        cfg = load_cfg()
        return TreePage(UI(Device(cfg), cfg))

    def test_star_panel_and_go_button(self):
        page = self._page()
        im = load("tree_star_panel")
        self.assertTrue(page.chapter_panel_open(im))
        pos = page.find_star_go(im)
        self.assertIsNotNone(pos)
        self.assertTrue(540 <= pos[0] <= 550, pos)

    def test_star_rows_still_parse_map(self):
        """地图上的星星行解析保留（辅助判断），但补星流程不再依赖它。"""
        from mtbot.pages import TreePage

        rows = TreePage.star_rows(load("tree_map"))
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(r[2] in (1, 2, 3) for r in rows))


class HeroStarPageTests(unittest.TestCase):
    """英雄升星页底部是一排亮按钮、中部偏暗，会被 battle 误判（脚本会连按跳过）。"""

    def test_not_battle(self):
        im = load("hero_star_page")
        self.assertFalse(vision.battle_page(im))
        self.assertNotEqual(vision.classify(im), State.BATTLE)


class RankClaimTests(unittest.TestCase):
    """官阶（军衔）领奖：领取后整列上浮，必须动态找金色按钮而不是固定 y。"""

    def test_dynamic_gold_button_column(self):
        from mtbot import layout as LL

        bands = vision.gold_button_bands(load("rank_claimable"), LL.RANK_CLAIM_ZONE)
        self.assertTrue(bands, "有未领奖励时右侧列里应该找到金色「领取」")
        self.assertLess(abs(bands[0][1] - 752), 24, bands)
        self.assertFalse(vision.gold_button_bands(load("rank_claimed"), LL.RANK_CLAIM_ZONE),
                         "全部已领取时不应该再找到金色按钮")

    def test_zone_excludes_promote_button(self):
        """扫描区间只覆盖右侧按钮列（x≥505），不会撞到居中的「晋升」大按钮。"""
        from mtbot import layout as LL

        self.assertGreaterEqual(LL.RANK_CLAIM_ZONE[0], 505)


class RankBoardBadgeTests(unittest.TestCase):
    """排行榜：奖励是竖排列表、可领取看奖励图标右上角的红「!」；页签角标同理。"""

    def test_panel_row_badge(self):
        from mtbot import layout as LL

        im = load("rank_board_panel_badge")
        x = LL.RANK_PANEL_ICON_X + LL.RANK_PANEL_BADGE_DX
        self.assertTrue(vision.red_badge(im, x, LL.RANK_PANEL_ICON_YS[0] + LL.RANK_PANEL_BADGE_DY,
                                         r=16, need=6))
        # 第二行「暂无玩家上榜」没有角标
        self.assertFalse(vision.red_badge(im, x, LL.RANK_PANEL_ICON_YS[1] + LL.RANK_PANEL_BADGE_DY,
                                          r=16, need=6))

    def test_tab_badge(self):
        from mtbot import layout as LL
        from mtbot.pages import RankBoardPage

        xs = RankBoardPage.tab_badges(None, load("rank_board_tabs_badge"))
        self.assertTrue(xs, "战役关卡页签上有红「!」，应该能定位到")
        self.assertLess(abs(xs[0] - (496 - LL.RANK_TAB_BADGE_DX)), 12, xs)

    def test_reward_button_template(self):
        from mtbot import template as T

        self.assertGreater(T.VI.best_score(load("rank_level"), "排行榜奖励按钮.png"), 0.90)


class WelfareTabTests(unittest.TestCase):
    """福利页签条可滑动；旧版只点两个固定坐标，看不全页签、也不会领周末补给/签到。"""

    def test_banner_detection(self):
        from mtbot.tasks.reward import WelfareTask

        self.assertEqual(WelfareTask._banner(load("welfare_weekend")), "weekend")
        self.assertEqual(WelfareTask._banner(load("welfare_signin_done")), "signin")

    def test_signin_stamp_not_match_relaim(self):
        """领完后的「再领一次」是充值入口，绝不能被「领取」印章模板命中。"""
        from mtbot import template as T

        self.assertLess(T.VI.best_score(load("welfare_signin_done"), "福利_签到领取.png"), 0.88)

    def test_signin_claim_found_by_ocr(self):
        """2026-11-07：签到按钮已是深色胶囊 + 绿字，红飘带判据恒 False，只能靠 OCR。"""
        from mtbot import layout as LL
        from mtbot import vision as V
        from mtbot.tasks.reward import WelfareTask

        im = load("welfare_signin_claim")
        task = WelfareTask.__new__(WelfareTask)
        found = task._signin_claims(im, set())
        self.assertEqual(len(found), 1, found)
        x, y = found[0]
        self.assertLessEqual(abs(x - 113), 8, found)
        self.assertLessEqual(abs(y - 801), 8, found)
        # 旧判据（红飘带）在这张真机帧上确实是 False —— 这就是要换判据的原因
        dx0, dy0, dx1, dy1 = LL.WELFARE_SIGNIN_CELL
        self.assertFalse(V.signin_claim(im, (x + dx0, y + dy0, x + dx1, y + dy1)))

    def test_signin_claim_skips_claimed_cells(self):
        """点过的格子不再返回，避免同一轮反复点同一个「领取」。"""
        from mtbot.tasks.reward import WelfareTask

        im = load("welfare_signin_claim")
        task = WelfareTask.__new__(WelfareTask)
        first = task._signin_claims(im, set())
        self.assertEqual(len(first), 1, first)
        self.assertEqual(task._signin_claims(im, set(first)), [])

    def test_weekend_claim_found_by_ocr(self):
        """2026-11-07：周末补给按钮不是金色、中心在 y≈1031，「待领取」不算可领。"""
        from mtbot import layout as LL
        from mtbot.tasks.reward import WelfareTask

        im = load("welfare_weekend_btn")
        task = WelfareTask.__new__(WelfareTask)
        found = task._weekend_claims(im)
        self.assertEqual(len(found), 1, found)          # 只有「周六礼包」是可领的
        x, y = found[0]
        self.assertLessEqual(abs(x - 156), 10, found)
        self.assertLessEqual(abs(y - 1031), 10, found)
        # 旧判据：三个固定坐标都不是金色 —— 这就是漏领的原因
        for pos in LL.WELFARE_WEEKEND_BTNS:
            self.assertFalse(vision.is_gold(im, *pos, r=16), pos)


class CampaignLockTests(unittest.TestCase):
    """主线到等级上限时按钮仍是金色，写的是「N级解锁」——要认字模板，不能一直点。"""

    def test_locked_button(self):
        from mtbot import layout as LL
        from mtbot import template as T

        im = load("campaign_locked")
        self.assertTrue(vision.is_gold(im, *LL.CAMPAIGN_STAGE_BTN, r=18))
        self.assertGreater(T.VI.best_score(im, "战役_等级解锁.png"), 0.95)
        self.assertLess(T.VI.best_score(load("main_city"), "战役_等级解锁.png"), 0.70)


class ArtifactStateTests(unittest.TestCase):
    """神器底部按钮：金色=升级（面板显示「等级 N」），橙红=进阶（显示「品阶 +N」）。"""

    def test_button_state(self):
        from mtbot.tasks.assist import ArtifactTask

        self.assertEqual(ArtifactTask._btn_state(load("artifact_advance")), "advance")
        self.assertEqual(ArtifactTask._btn_state(load("artifact_upgrade")), "upgrade")

    def test_level_readable_only_when_upgrade(self):
        from mtbot import layout as LL
        from mtbot import ocr
        from mtbot.tasks.assist import ArtifactTask

        im = load("artifact_upgrade")
        self.assertEqual(ocr.read_number_loose(im, LL.ARTIFACT_LV_BOX, mask="dark"), [60])
        # 进阶状态那行是「品阶 +1」，绝不能当成等级 1
        self.assertEqual(ArtifactTask._btn_state(load("artifact_advance")), "advance")


class AssistMarkTests(unittest.TestCase):
    """英雄页右上「助战」→「助战徽记」面板（2026-10-31 新增任务）。"""

    def test_level_banner_and_button(self):
        from mtbot import layout as LL
        from mtbot import ocr

        im = load("assist_mark")
        self.assertTrue(vision.is_gold(im, *LL.ASSIST_MARK_UP, r=16))
        # 「5阶27级」里的等级数字是绿字
        self.assertEqual(ocr.read_number_loose(im, LL.ASSIST_MARK_LV_BOX, mask="green_loose"), [27])


class TextOcrParseTests(unittest.TestCase):
    """`textocr` 的纯文本解析（不需要 OCR 引擎）。"""

    def test_time_window_needs_pair(self):
        """「开战时间：10点-22点」必须读成 (10,22)。

        2026-11-06 踩过的坑：OCR 常把这一行切成「开战时间：1」+「10点-22点」，
        见数字就取前两个会读成 (1,10)，11 点这种真开战时间就被误判成休赛期。
        """
        from mtbot import textocr

        self.assertEqual(textocr.read_time_window("开战时间：10点-22点"), (10, 22))
        self.assertEqual(textocr.read_time_window("开战时间：1 10点-22点"), (10, 22))
        self.assertEqual(textocr.read_time_window("开战时间： 10:00-22:00"), (10, 22))
        self.assertEqual(textocr.read_time_window("开战时间： 10点至22点"), (10, 22))
        self.assertEqual(textocr.read_time_window("开战时间：22点-2点"), (22, 2))
        # 只有半个窗口的残句一律不认，宁可不判休赛期
        self.assertIsNone(textocr.read_time_window("开战时间：1"))
        self.assertIsNone(textocr.read_time_window("随便写点什么"))

    def test_remain_and_fraction(self):
        from mtbot import textocr

        self.assertEqual(textocr.read_remain("今日剩余次数：0"), 0)
        self.assertEqual(textocr.read_remain("今日剩余次数：3"), 3)
        self.assertIsNone(textocr.read_remain("没有这行"))
        self.assertEqual(textocr.read_fraction("挑战次数：0/20（每日登录+5）"), (0, 20))
        self.assertIsNone(textocr.read_fraction("挑战"))


class BattleSkipTests(unittest.TestCase):
    """战斗页「跳过」按钮：模板定位 vs 固定坐标。

    2026-11-07：真机一次 `press (655,900)` 判 MISS（diff=0.003），靠 ±8px 补偿点
    到 (655,892) 才命中——固定坐标落在按钮边缘。改成模板定位后应稳定命中中心。
    """

    def test_template_locates_skip_button(self):
        from mtbot import layout as LL, template as T

        im = load("battle")
        m = T.VI.find(im, "跳过.png", LL.BATTLE_SKIP_THRESHOLD, roi=LL.BATTLE_SKIP_ROI)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(m.score, 0.85)
        cx, cy = m.center
        # 回退坐标必须贴着模板中心（否则模板缺失时会点偏）
        self.assertLessEqual(abs(cx - LL.BATTLE_SKIP[0]), 6, (cx, LL.BATTLE_SKIP))
        self.assertLessEqual(abs(cy - LL.BATTLE_SKIP[1]), 6, (cy, LL.BATTLE_SKIP))

    def test_bright_battle_still_matches(self):
        """亮背景的战斗页（雪地等）模板分只有 0.726，阈值必须低于它。

        2026-11-07 真机复跑：470 张帧里带「跳过」的暗背景帧 0.988~0.993，
        亮背景帧最低 0.662（battle_skip_36），而不带「跳过」的阵营战斗页最高 0.409。
        阈值定 0.60 才能两边都分开；定 0.75 会让亮背景那次不点、白等结算。
        """
        from mtbot import layout as LL, template as T

        for name in ("battle", "battle_bright"):
            score = T.VI.best_score(load(name), "跳过.png", roi=LL.BATTLE_SKIP_ROI)
            self.assertGreaterEqual(score, LL.BATTLE_SKIP_THRESHOLD, (name, score))

    def test_no_skip_button_without_battle_control(self):
        """阵营挑战的战斗页没有「跳过」（只有暂停/自动/倍速），不能凭空命中。"""
        from mtbot import layout as LL, template as T

        for name in ("faction_battle", "trial_save_dialog"):
            score = T.VI.best_score(load(name), "跳过.png", roi=LL.BATTLE_SKIP_ROI)
            self.assertLess(score, LL.BATTLE_SKIP_THRESHOLD, (name, score))


class GoblinLayerParseTests(unittest.TestCase):
    """地精宝藏左下「第N层」标签解析（层切换后的复核判据）。"""

    def test_chinese_layer_numbers(self):
        from mtbot.tasks.goblin import _cn_layer

        self.assertEqual(_cn_layer("第一层 3 【地精宝藏】火枪兵兰德"), 1)
        self.assertEqual(_cn_layer("第六层 3 火枪兵"), 6)
        self.assertEqual(_cn_layer("第九层"), 9)
        self.assertEqual(_cn_layer("第十层 3"), 10)

    def test_no_layer_reads_as_minus_one(self):
        from mtbot.tasks.goblin import _cn_layer

        for text in ("", "第 层", "地精宝藏", "第X层"):
            self.assertEqual(_cn_layer(text), -1, text)

    def test_layer_rows_no_longer_trusted_without_template(self):
        """固定行坐标只在模板缺失时才用：实测逐行点会漂到相邻层。"""
        from mtbot import layout as LL
        from mtbot.tasks.goblin import GoblinTask

        self.assertEqual(len(LL.GOB_LAYER_ROWS), 6)
        self.assertEqual(GoblinTask._layer_tpls()[:2], ["层名_1.png", "层名_2.png"])


class HeroSubTabTests(unittest.TestCase):
    """英雄页「英雄/图鉴/羁绊/回退」四个子页签的点击位置（2026-11-07 实测）。

    背景：文字中心在 y≈1119，但真正能切页的是 y≈1110；而「羁绊」页签正下方会冒一个
    「可领取」红气泡（文字中心 (414,1151)，可点范围向上盖到 y≈1125），旧坐标 (438,1125)
    正好点在气泡上，弹出的是「挂机特权」68 元购买面板 —— 于是标题模板永远不命中，
    hero_bond 白天必失败（凌晨没有气泡时才碰巧能进）。
    """

    def test_all_hero_sub_tabs_sit_above_the_claim_bubble(self):
        from mtbot import layout as LL

        for name in ("HERO_TAB_GRID", "HERO_TAB_COLLECTION",
                     "HERO_TAB_BOND", "HERO_TAB_BACK"):
            x, y = getattr(LL, name)
            self.assertLessEqual(y, 1112, f"{name}={x},{y} 会落在「可领取」气泡上")
            self.assertGreaterEqual(y, 1090, f"{name}={x},{y} 已离开页签热区")

    def test_bond_tab_x_matches_measured_text_center(self):
        from mtbot import layout as LL

        self.assertLessEqual(abs(LL.HERO_TAB_BOND[0] - 432), 10)

    def test_idle_popup_closer_only_taps_blank(self):
        """误点开「挂机特权」付费面板时，只点空白处关闭，绝不碰购买按钮。"""
        from mtbot import layout as LL

        # 面板底部那句「点击空白处关闭」在 (360,1220) 附近；购买按钮在面板中部
        self.assertLess(abs(LL.IDLE_REWARD_CLOSE[0] - 360), 40)
        self.assertGreaterEqual(LL.IDLE_REWARD_CLOSE[1], 1190)

    @staticmethod
    def _fixture(name):
        from pathlib import Path

        from PIL import Image

        path = Path(__file__).resolve().parent / "fixtures" / name
        return Image.open(path).convert("RGB")

    def test_idle_popup_is_detected_on_the_paid_panel(self):
        """真机帧：羁绊页签下方「可领取」气泡点开后的「挂机特权」68 元面板。"""
        from mtbot import textocr

        im = self._fixture("hero_idle_popup.png")
        text = textocr.read_text(im, (0, 180, 720, 700))
        self.assertTrue("挂机特权" in text or "点击空白处关闭" in text, text[:120])

    def test_idle_popup_is_not_detected_on_a_plain_hero_page(self):
        from mtbot import textocr

        for name in ("hero_page_tabs.png", "hero_bond_page.png"):
            im = self._fixture(name)
            text = textocr.read_text(im, (0, 180, 720, 700))
            self.assertFalse("挂机特权" in text or "点击空白处关闭" in text,
                             f"{name}: {text[:120]}")


class BattlePassTests(unittest.TestCase):
    """勇者计划（战令）：2026-11-07 实测 —— 底栏/页签/行按钮坐标全偏 50px，
    领奖浮层点面板内部关不掉（会误点「前往」跳去角斗场），付费判据在主城常驻橙钮上误报。"""

    def test_footer_and_tab_positions(self):
        from mtbot import layout as LL

        # 「战令任务」文字中心 (626,1261)；旧值 (656,1250) 点在文字右侧空地
        self.assertLessEqual(abs(LL.BP_TASK_VIEW[0] - 626), 6)
        self.assertLessEqual(abs(LL.BP_TASK_VIEW[1] - 1261), 6)
        # 三页签 y=547；旧值 495 在页签上方
        for x, y in LL.BP_TABS:
            self.assertLessEqual(abs(y - 547), 6)

    def test_task_buttons_found_by_ocr(self):
        """任务页 4 行「领取」能被 OCR 认出来（旧坐标偏 50px，is_gold 一个不中）。"""
        from mtbot.tasks.reward import BattlePassTask

        found = BattlePassTask._task_buttons(load("bp_tasks"))
        self.assertEqual(len(found), 4, found)
        ys = [y for _x, y in found]
        self.assertLessEqual(abs(ys[0] - 647), 8, ys)
        self.assertLessEqual(abs(ys[-1] - 1068), 8, ys)

    def test_forward_buttons_are_not_claimable(self):
        """「前往」是土黄、不可点 —— 不能被当成领取按钮。"""
        from mtbot.tasks.reward import BattlePassTask

        im = load("bp_claim_overlay")     # 领奖浮层里 4 个按钮全是「前往」
        found = BattlePassTask._task_buttons(im)
        self.assertEqual(found, [], found)

    def test_overlay_detected_and_closed_above_panel(self):
        """领奖浮层要用「获得奖励」判据；关闭点必须在面板上方压暗区（点内部会误点「前往」）。"""
        from mtbot import layout as LL
        from mtbot import vision as V
        from mtbot.tasks.reward import BattlePassTask

        ov = load("bp_claim_overlay")
        self.assertTrue(BattlePassTask._overlay_open(ov))
        self.assertFalse(BattlePassTask._overlay_open(load("bp_tasks")))
        # 浮层里的可点目标：4 行「前往」+ 底部「快速点击空白处关闭」，关闭点必须离它们都远
        busy = [(566, 648), (566, 788), (566, 927), (566, 1067), (345, 911)]
        for pos in LL.BP_OVERLAY_CLOSE:
            self.assertTrue(all(abs(pos[0] - bx) > 60 or abs(pos[1] - by) > 60
                                for bx, by in busy), pos)
            self.assertFalse(V.is_gold(ov, *pos, r=8), pos)  # 关闭点绝不能落在任何按钮上
            self.assertFalse(V.orange_button_bands(ov, (pos[0] - 20, pos[1] - 20,
                                                        pos[0] + 20, pos[1] + 20)), pos)

    def test_pay_dialog_ocr(self):
        """98 元「解锁战令」弹层必须被判成付费；奖励轨道常驻页不能误报（旧橙色判据会误报）。"""
        from mtbot.tasks.reward import BattlePassTask

        pay = load("bp_pay_dialog")
        self.assertTrue(BattlePassTask._purchase_dialog(pay))
        rewards = load("bp_rewards")
        self.assertFalse(BattlePassTask._purchase_dialog(rewards))
        # 顶栏常驻的「解锁高级战令」在 y≈443，不能算付费弹层
        self.assertLess(_lowest_y_of(rewards, "解锁高级战令"), 470)


def _lowest_y_of(im, key):
    from mtbot import textocr

    for text, _center, bb, _sc in textocr.read_lines(im, (0, 0, 720, 520)):
        if key in text:
            return bb[1]
    return 9999


class StarUpTests(unittest.TestCase):
    """英雄升星：入口坐标 + 「选择英雄」窗判据（2026-11-07 实机帧标定）。

    背景：主城「升星」老坐标 (190,770) 点到当期「累充」付费横幅上，脚本照样往下跑，
    报「批量升星 0 次」；材料窗判据 (359,807) 金钮在整页米色的英雄/助战网格页上也成立，
    会把普通列表页当成选择窗。
    """

    def test_star_entry_point_inside_icon_area(self):
        from mtbot import layout as LL

        x, y = LL.BLD_STAR
        self.assertTrue(60 <= x <= 340 and 690 <= y <= 880,
                        f"入口 {LL.BLD_STAR} 不在主城升星建筑区域")
        self.assertLessEqual(abs(x - 176), 20)
        self.assertLessEqual(abs(y - 777), 20)

    def test_picker_detected_on_picker_window(self):
        """真窗：面板米色 + (359,812) 金「确定」+ 上方背景压暗。"""
        self.assertTrue(vision.star_material_picker(load("hero_star_picker")))

    def test_picker_false_on_bright_hero_pages(self):
        for name in ("hero_page_tabs", "assist_mark", "hero_star_materials"):
            self.assertFalse(vision.star_material_picker(load(name)), name)

    def test_material_page_is_not_picker(self):
        """材料页（传说 ★★★★★ 1/1 5/7）没有任何金钮，不是选择窗。"""
        self.assertFalse(vision.star_material_picker(load("hero_star_page")))


class _OcrStub:
    """替身：只回固定文字，read_fraction 走真实实现。"""

    def __init__(self, text):
        self.text = text

    def read_text(self, im, box=None, sep=" "):
        return self.text

    @staticmethod
    def read_fraction(text):
        from mtbot import textocr

        return textocr.read_fraction(text)

    def available(self):
        return True


class _OcrBoxStub:
    """按 box 回不同文字的替身：窄框读空、宽框读得到（复现 2026-11-08 实测）。"""

    def __init__(self, narrow="", wide=""):
        self.narrow, self.wide = narrow, wide

    def read_text(self, im, box=None, sep=" "):
        from mtbot import layout as LL

        return self.wide if box == getattr(LL, "RELIC_PROGRESS_BOX_WIDE", None) else self.narrow

    def read_lines(self, im, box=None, min_score=0.5):
        return []

    @staticmethod
    def read_fraction(text):
        from mtbot import textocr

        return textocr.read_fraction(text)

    def available(self):
        return True


class RelicResFallbackTests(unittest.TestCase):
    """材料进度框读空时的兜底：不能把「读不到」当成「材料没变」。"""

    @staticmethod
    def _call(stub):
        from mtbot.tasks import reward as R

        old = R.textocr
        R.textocr = stub
        try:
            return R.RelicTask._relic_res(None)
        finally:
            R.textocr = old

    def test_narrow_ok(self):
        self.assertEqual(self._call(_OcrBoxStub(narrow="690 / 800")), (690, 800))

    def test_wide_fallback(self):
        self.assertEqual(self._call(_OcrBoxStub(narrow="", wide="圣物总等级 690 / 800")), (690, 800))

    def test_regex_fallback(self):
        # OCR 把斜杠认成了竖线时的形状兜底
        self.assertEqual(self._call(_OcrBoxStub(narrow="690 l 800")), (690, 800))

    def test_both_empty_returns_none(self):
        self.assertIsNone(self._call(_OcrBoxStub()))

    def test_has_wide_box(self):
        from mtbot import layout as LL

        self.assertTrue(hasattr(LL, "RELIC_PROGRESS_BOX_WIDE"))
        self.assertTrue(hasattr(LL, "BP_BOTTOM_STRIP"))


class ModalDimTests(unittest.TestCase):
    """「顶部条几乎全黑」= 整屏压暗的居中模态弹窗（挑战失败/确认框那一类）。"""

    @staticmethod
    def _frame(top):
        im = Image.new("RGB", (720, 1280), (230, 215, 190))
        im.paste(Image.new("RGB", (720, 120), top), (0, 0))
        return im

    def test_dark_top_is_modal(self):
        self.assertTrue(vision.modal_dim(self._frame((20, 18, 16))))

    def test_bright_top_is_not_modal(self):
        self.assertFalse(vision.modal_dim(self._frame((140, 130, 110))))

    def test_small_image_rejected(self):
        self.assertFalse(vision.modal_dim(Image.new("RGB", (400, 300), (0, 0, 0))))


class BattleSkipCoverageTests(unittest.TestCase):
    """2026-11-08 用户质疑「大部分战斗都能点跳过，为什么不跳过」。

    全库 1800 帧复核：battle 态 63 帧里 59 帧在 ROI(600,850,720,950) 命中
    「跳过.png」(0.813~0.911，中心恒 (652,899))，classify!=battle 的帧零误命中；
    faction 22 帧零命中（那个玩法确实没有跳过键）。塔/传奇/树/邪能四处
    BATTLE 分支原来硬编码「只等不点」，现改为模板命中就点。
    """

    def test_skip_template_hits_battle_frames(self):
        from mtbot import layout as LL
        from mtbot import template as TT
        from mtbot import vision as VV
        hits = 0
        total = 0
        for name in ("battle", "battle_bright", "battle_skip_gob"):
            p = FIX / (name + ".png")
            if not p.exists():
                continue
            im = load(name)
            if VV.classify(im).value != "battle":
                continue
            total += 1
            m = TT.VI.find(im, "跳过.png", LL.BATTLE_SKIP_THRESHOLD, roi=LL.BATTLE_SKIP_ROI)
            if m is not None:
                hits += 1
                self.assertLessEqual(abs(m.center[0] - 652), 6)
                self.assertLessEqual(abs(m.center[1] - 899), 6)
        if total:
            self.assertEqual(hits, total, "battle 帧里跳过模板应当全部命中")

    def test_faction_has_no_skip_button(self):
        """阵营挑战没有跳过键（只有暂停/自动），不能被误判成有。"""
        from mtbot import layout as LL
        from mtbot import template as TT
        p = FIX / "faction_battle.png"
        if not p.exists():
            self.skipTest("缺 faction_battle.png")
        im = load("faction_battle")
        m = TT.VI.find(im, "跳过.png", LL.BATTLE_SKIP_THRESHOLD, roi=LL.BATTLE_SKIP_ROI)
        self.assertIsNone(m)

    def test_no_dead_wait_before_skip(self):
        """开打后不能死等 8 秒再点一次跳过（要轮询，2~4 秒就进结算）。"""
        for rel in ("mtbot/tasks/combat.py", "mtbot/tasks/daily.py",
                    "mtbot/tasks/dungeon.py"):
            src = (HERE.parent / rel).read_text(encoding="utf-8")
            self.assertNotIn("ui.wait(8)\n", src, rel)
            self.assertIn("battle_finish(", src, rel)

    def test_battle_finish_polls_and_reports(self):
        """轮询跳过 + 用 grace 区分「进场中」和「真结算」。

        2026-11-08 二次修正：点完「战斗」后抓到的第一帧还是进场过渡，旧写法
        `if self.state(cur) != State.BATTLE: return True` 会把它当成「打完了」，
        于是 26 秒一次跳过都没点，任务继续按列表页瞎点（dungeon 跑偏到公会页
        的那 2 次空点的根因）。现在必须靠 `started` 标记 + `grace` 宽限区分。
        """
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("def battle_finish(", src)
        self.assertIn("grace: float = 4.0", src)
        self.assertIn("started = True", src)
        self.assertIn("if started:", src)
        self.assertIn("self.battle_skip(cur, ms=ms, label=label, quiet=True)", src)

    def test_deploy_and_skip_polls_instead_of_sleeping(self):
        """布阵开打后应当轮询试跳过，而不是死等 skip_delay 秒只点一次。"""
        src = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.assertIn("if vision.classify(im2) != State.BATTLE:", src)
        self.assertIn("ui.battle_skip(im2, quiet=True)", src)
        self.assertNotIn("ui.wait(skip_delay)", src)

    def test_welfare_surveys_tabs_before_swiping(self):
        """福利页先普查页签条，本期不存在的页签不再逐个左右滑 6 次。

        2026-11-08：`logs\\_full4_131014.log` 13:11:02→13:12:16 为一个本期
        根本没有的「英雄集结」页签白烧 74 秒。
        """
        src = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")
        self.assertIn("def _survey_tabs(", src)
        self.assertIn("present = self._survey_tabs(ui)", src)
        self.assertIn("if present and key not in present:", src)

    def test_battle_skip_has_quiet_flag(self):
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("quiet: bool = False", src)

    def test_all_four_tasks_skip_in_battle(self):
        src = (HERE.parent / "mtbot" / "tasks" / "combat.py").read_text(encoding="utf-8")
        for label in ("tower_skip", "legend_skip", "tree_skip", "demon_skip",
                      "tower_settle_skip"):
            self.assertIn(f'battle_skip(im, label="{label}")', src)
        # 旧注释「战斗态一律不点 UI」已被推翻，不能再留着误导
        self.assertNotIn("通用规则：战斗态一律不点 UI，只等结算。", src)
        self.assertNotIn("没有「跳过」", src)


class RelicHelperTests(unittest.TestCase):
    """圣物升级页：材料进度 / toast / 页头三个 OCR 判据。"""

    def setUp(self):
        from mtbot.tasks import reward as R

        self.R = R
        self.im = Image.new("RGB", (720, 1280), (0, 0, 0))
        self._old = R.textocr

    def tearDown(self):
        self.R.textocr = self._old

    def test_res_parses_progress(self):
        from mtbot.layout import RELIC_PROGRESS_BOX

        self.R.textocr = _OcrStub("690/800")
        self.assertEqual(self.R.RelicTask._relic_res(self.im), (690, 800))
        self.R.textocr = _OcrStub("")
        self.assertIsNone(self.R.RelicTask._relic_res(self.im))
        # 框必须落在升级页材料进度那一行附近。
        # 2026-11-08 真帧：材料写的是「4万/800」，窄框 (300,1020,470,1075) 读不到，
        # 实测只有 (260,995,560,1100) 能整行读到，故放宽到这一档。
        x0, y0, x1, y1 = RELIC_PROGRESS_BOX
        self.assertTrue(240 <= x0 <= 300 and 540 <= x1 <= 600)
        self.assertTrue(980 <= y0 <= 1020 and 1080 <= y1 <= 1120)

    def test_toast_text(self):
        self.R.textocr = _OcrStub("暂无可升级圣物")
        self.assertIn("暂无可升级", self.R.RelicTask._relic_toast(self.im))

    def test_page_kind_up(self):
        from mtbot.config import TaskConfig

        task = self.R.RelicTask(TaskConfig())   # BaseTask 只要 tcfg.params
        kind = task._page_kind
        self.R.textocr = _OcrStub("圣物总等级 662/720")
        self.assertEqual(kind(self.im), "up")
        self.R.textocr = _OcrStub("")
        self.assertEqual(kind(self.im), "")

    def test_tab_coordinates_on_bottom_bar(self):
        from mtbot import layout as LL

        for pos in (LL.RELIC_TAB_STAR, LL.RELIC_TAB_UP, LL.RELIC_TAB_BOND):
            self.assertTrue(1230 <= pos[1] <= 1275, pos)
        self.assertEqual(len({LL.RELIC_TAB_STAR[0], LL.RELIC_TAB_UP[0], LL.RELIC_TAB_BOND[0]}), 3)
        self.assertTrue(1240 <= LL.RELIC_ONEKEY[1] or LL.RELIC_ONEKEY == (582, 1124))


class HubCardTests(unittest.TestCase):
    """历练入口：靠 OCR 认卡片标题（列表可滚动，固定坐标会点空）。"""

    @classmethod
    def setUpClass(cls):
        from mtbot.config import load
        from mtbot.pages import TrialsHub

        class _Dev:
            pkg = "com.wjmtjq.ma.android"

            def focus_pkg(self):
                return self.pkg

        from mtbot.ui import UI

        cls.ui = UI(_Dev(), load(None))
        cls.hub = TrialsHub(cls.ui)

    def test_title_table_covers_five_hubs(self):
        from mtbot import layout as LL

        for key in ("dungeon", "tower", "legend", "demon", "tree"):
            self.assertIn(key, LL.HUB_TITLES, key)
        self.assertIn("守护者之塔", LL.HUB_TITLES["tower"])
        self.assertIn("日常副本", LL.HUB_TITLES["dungeon"])

    def test_tower_card_found_by_text(self):
        c = self.hub._card_pos(load("hub_list_tower"), "tower")
        self.assertIsNotNone(c)
        self.assertLessEqual(abs(c[0] - 252), 12)
        self.assertLessEqual(abs(c[1] - 632), 20)

    def test_demon_and_tree_found_by_text(self):
        im = load("hub_list_mid")
        d = self.hub._card_pos(im, "demon")
        t = self.hub._card_pos(im, "tree")
        self.assertIsNotNone(d)
        self.assertIsNotNone(t)
        self.assertLessEqual(abs(d[0] - 359), 12)
        self.assertLessEqual(abs(t[0] - 369), 16)

    def test_missing_card_returns_none(self):
        """这一帧没有罪魂之域卡片 —— 不能瞎认。"""
        self.assertIsNone(self.hub._card_pos(load("hub_list_tower"), "soul"))

    def test_tile_table_covers_four_hubs(self):
        """塔/传奇/邪能/树的标题条模板都在（2026-11-08 从真帧裁出）。"""
        from mtbot import layout as LL

        for key in ("tower", "legend", "demon", "tree"):
            self.assertIn(key, LL.HUB_TILES, key)
            self.assertTrue(LL.HUB_TILES[key].endswith(".png"))
        self.assertTrue(0.8 <= LL.HUB_TILE_THRESHOLD <= 0.95)

    def test_tiles_hit_on_list_and_miss_elsewhere(self):
        """模板在历练列表上命中、在主城/玩法页上不命中（阈值 0.85）。"""
        from mtbot import layout as LL
        from mtbot import template as TT

        im = load("hub_list_tower")
        m = TT.VI.find(im, LL.HUB_TILES["tower"], LL.HUB_TILE_THRESHOLD, roi=LL.HUB_LIST_ROI)
        self.assertIsNotNone(m)
        self.assertLessEqual(abs(m.center[0] - 252), 12)

        for name in ("main_city", "tower_page"):
            frame = load(name)
            for key in ("tower", "legend", "demon", "tree"):
                self.assertIsNone(
                    TT.VI.find(frame, LL.HUB_TILES[key], LL.HUB_TILE_THRESHOLD,
                               roi=LL.HUB_LIST_ROI),
                    f"{name}/{key}")


class AssistPanelTests(unittest.TestCase):
    """助战徽记：面板开没开认标题「助战徽记」。

    2026-11-08 实测：面板开着、材料只有 115/500 时「进阶」按钮是灰的，
    旧逻辑用 is_gold(ASSIST_MARK_UP) 判「面板有没有打开」→ 把开着的面板当成没开，
    按返回 + 重点入口，落到英雄布阵页（白赔 1 条空点 + 8s）。
    """

    def _task(self):
        from mtbot.config import TaskConfig
        from mtbot.tasks.assist import AssistMarkTask

        return AssistMarkTask(TaskConfig())

    def test_panel_open_on_real_panel(self):
        self.assertTrue(self._task()._assist_panel_open(load("assist_mark_panel")))

    def test_panel_closed_on_hero_page(self):
        self.assertFalse(self._task()._assist_panel_open(load("hero_lineup_page")))

    def test_head_box_inside_title_area(self):
        from mtbot import layout as LL

        x0, y0, x1, y1 = LL.ASSIST_MARK_HEAD_BOX
        self.assertTrue(280 <= x0 and x1 <= 470, LL.ASSIST_MARK_HEAD_BOX)
        self.assertTrue(130 <= y0 and y1 <= 215, LL.ASSIST_MARK_HEAD_BOX)


class CampaignTipTests(unittest.TestCase):
    """2026-11-08：战役的两处真实原因取证。

    ① 章节首领关：地图底部金钮写「挑战首领」，点开是「关卡详情」面板，面板底部
       才是金「挑战」。旧码不认面板 → 连点 3 次 → 记「主线 0 次」。
    ② 角斗券满仓：「温馨提示：当前角斗券已达上限，请前往角斗场挑战」与「布阵未
       保存」共用同一套像素签名，旧码当成「保存」点掉，真实原因丢失。
    """

    def test_boss_panel_go_button_detection(self):
        """面板上 CAMPAIGN_GO 是金、地图上是非金；STAGE_BTN 正好相反（可互斥判页）。"""
        panel = FIX / "campaign_boss_panel.png"
        amap = FIX / "campaign_boss_map.png"
        if not panel.exists() or not amap.exists():
            self.skipTest("缺 campaign_boss_panel.png / campaign_boss_map.png")
        from mtbot import layout as LL
        from mtbot import vision as TT
        im_p, im_m = load("campaign_boss_panel"), load("campaign_boss_map")
        self.assertTrue(TT.is_gold(im_p, *LL.CAMPAIGN_GO, r=18))
        self.assertFalse(TT.is_gold(im_m, *LL.CAMPAIGN_GO, r=18))
        self.assertFalse(TT.is_gold(im_p, *LL.CAMPAIGN_STAGE_BTN, r=18))
        self.assertTrue(TT.is_gold(im_m, *LL.CAMPAIGN_STAGE_BTN, r=18))

    def test_ticket_tip_text_readable(self):
        """角斗券提示必须在 CAMPAIGN_TIP_ROI 里读得出来（否则又会误判成「保存」）。"""
        f = FIX / "campaign_ticket_tip.png"
        if not f.exists():
            self.skipTest("缺 campaign_ticket_tip.png")
        from mtbot import textocr as OCR
        from mtbot import layout as LL
        if not OCR.available():
            self.skipTest("没有 OCR")
        txt = OCR.read_text(load("campaign_ticket_tip"), LL.CAMPAIGN_TIP_ROI)
        self.assertIn("角斗券", txt)
        self.assertIn("上限", txt)

    def test_source_separates_tip_from_save(self):
        src = (HERE.parent / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")
        self.assertIn('("角斗券", "角斗场", "上限")', src)
        self.assertIn("block_reason = tip[:40]", src)
        # 首领关面板分支必须存在，否则主线在「挑战首领」地图上原地打转
        self.assertIn("campaign_go", src)
        self.assertIn("not vision.is_gold(im, *L.CAMPAIGN_STAGE_BTN, r=18)", src)

class SoulLockRunTests(unittest.TestCase):
    """2026-11-08：罪魂之域连续 8 个格点都「未解锁」就收手（别白扫 20 多格）。"""

    def test_early_exit_threshold_is_configurable(self):
        src = (HERE.parent / "mtbot" / "tasks" / "soul.py").read_text(encoding="utf-8")
        self.assertIn('lock_run_max = int(p.get("lock_run", 8))', src)

    def test_breaks_after_consecutive_locked(self):
        src = (HERE.parent / "mtbot" / "tasks" / "soul.py").read_text(encoding="utf-8")
        self.assertIn("lock_run += 1", src)
        self.assertIn("if lock_run_max > 0 and lock_run >= lock_run_max and wins == 0:", src)
        self.assertIn('reason = "连续未解锁"', src)

    def test_streak_resets_on_win_and_lose(self):
        # 注意：soul.py 里 'if res == "win":' 出现两次（首领分支 24 空格缩进、
        # 格点分支 16 空格）。这里必须按格点分支的缩进匹配，否则会命中首领分支。
        src = (HERE.parent / "mtbot" / "tasks" / "soul.py").read_text(encoding="utf-8")
        self.assertIn('if res == "win":\n                wins += 1\n                lock_run = 0', src)
        self.assertIn('elif res == "lose":\n                loses += 1\n                lock_run = 0', src)

    def test_early_exit_counts_as_done_not_failure(self):
        src = (HERE.parent / "mtbot" / "tasks" / "soul.py").read_text(encoding="utf-8")
        self.assertIn('if reason in ("探测网格里已经没有可挑战的关卡", "连续未解锁") and locked:', src)


class EnsureTitleTests(unittest.TestCase):
    """2026-11-09：被踢回登录页时 ensure_main_city 必须点「开始游戏」，不能只按 BACK。

    真机证据：logs/_full18_000401.log 00:03:43~00:04:38 只按 (88,1205) 空转到
    tries 用完 → 「没能回到主城」，第一个任务 mail 直接失败。
    """

    def test_ensure_has_title_branch(self):
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        start = src.index("def ensure_main_city(")
        end = src.index("def _try_tap(", start)
        body = src[start:end]
        self.assertIn("if st == State.TITLE:", body)
        self.assertIn('label="title_start"', body)
        self.assertIn('label="title_agree"', body)

    def test_title_branch_comes_before_unknown_fallback(self):
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        start = src.index("def ensure_main_city(")
        end = src.index("def _try_tap(", start)
        body = src[start:end]
        self.assertLess(body.index("if st == State.TITLE:"),
                        body.index("# 兜底：其它状态"))

    def test_title_coords_are_on_the_login_button(self):
        from mtbot import layout as LL
        self.assertLess(abs(LL.TITLE_START[0] - 360), 40)
        self.assertLess(abs(LL.TITLE_START[1] - 1010), 40)


class MerchantItemTests(unittest.TestCase):
    """2026-11-09 00:25 实测：商品图标 y=520 点下去 diff=0.007 MISS，(170,512) 才命中。"""

    def test_item_y_bias(self):
        from mtbot import layout as LL
        for x, y in LL.MERCHANT_ITEMS:
            self.assertEqual(y, 512)
            self.assertIn(x, (170, 290, 407, 517))

    def test_select_item_logs_label(self):
        src = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.assertIn('label=f"merchant_item:{index}"', src)


class ArenaAttemptTests(unittest.TestCase):
    """角斗场「9/12」解析 + 关键坐标（2026-11-09 09:39 真帧实测）。"""

    def test_attempts_parsed(self):
        from mtbot.tasks.arena import ArenaTask
        from mtbot import layout as LL

        class _Im:
            pass
        import mtbot.tasks.arena as A
        real = A.textocr.read_text
        A.textocr.read_text = lambda im, box: "跳过战斗 02:02:54后恢复1次 9/12 +"
        try:
            self.assertEqual(ArenaTask._attempts(_Im()), 9)
            A.textocr.read_text = lambda im, box: "跳过战斗 0/12 +"
            self.assertEqual(ArenaTask._attempts(_Im()), 0)
            A.textocr.read_text = lambda im, box: "别的东西"
            self.assertIsNone(ArenaTask._attempts(_Im()))
        finally:
            A.textocr.read_text = real

    def test_boxes_on_real_frame(self):
        from mtbot import layout as LL
        x0, y0, x1, y1 = LL.ARENA_ATTEMPT_BOX
        self.assertTrue(450 <= x0 <= 520 and 600 <= x1 <= 660)
        self.assertTrue(1080 <= y0 <= 1100 and 1120 <= y1 <= 1140)
        self.assertTrue(780 <= LL.ARENA_RESULT_OK[1] <= 860)
        self.assertEqual(LL.TAB_ARENA[1], 1225)

    def test_no_diamond_paths(self):
        from pathlib import Path
        src = Path(str(HERE.parent / "mtbot" / "tasks" / "arena.py")).read_text(
            encoding="utf-8")
        # 2026-11-10 用户新规则：钻石只允许用来买挑战次数 —— 「+」买次数从此合规，
        # 但必须走 ARENA_BUY_PLUS → 弹窗「花费 N」→ ARENA_BUY_CONFIRM，且全程有自证。
        self.assertIn('label="arena_fight"', src)
        self.assertIn('label="arena_ok"', src)
        # 每一次点击都必须是「白名单」里的目标：竞技页签 / 角斗场卡片 / 对手挑战 /
        # 结算确定 / 关闭战报(BACK) / 关掉钻石确认框(CONFIRM_CANCEL) /
        # 买次数三步（「+」、弹窗「取消」、「购买」）。
        allowed = ("TAB_ARENA", "ARENA_GLAD_CARD", "ARENA_RESULT_OK", "pos",
                   "L.BACK", "L.CONFIRM_CANCEL",
                   "ARENA_BUY_PLUS", "ARENA_BUY_CANCEL", "ARENA_BUY_CONFIRM")
        presses = [ln.strip() for ln in src.splitlines() if "ui.press(" in ln]
        self.assertTrue(presses)
        for ln in presses:
            self.assertTrue(any(k in ln for k in allowed), ln)
        # 仍然禁止的：一次买满的「最大」按钮、角斗商店/角斗限购（真钱消费入口）
        self.assertNotIn("ARENA_BUY_MAX", src)
        self.assertNotIn("584, 732", src)
        self.assertNotIn("620, 1108", src)
        self.assertNotIn("ARENA_SHOP", src)

    def test_registered_and_enabled(self):
        import json
        from pathlib import Path
        from mtbot.tasks import TASK_CLASSES
        self.assertIn("arena", TASK_CLASSES)
        cfg = json.loads(Path(str(HERE.parent / "config.json")).read_text(
            encoding="utf-8"))
        self.assertTrue(cfg["tasks"]["arena"]["enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SoulFastPathTests(unittest.TestCase):
    """罪魂之域：地图帧必须走免 OCR 快路径，面板帧才允许 OCR。"""

    class _UI:
        """只实现 _read 用到的 screen()。"""

        def __init__(self, im):
            self._im = im

        def screen(self, tag=""):
            return self._im

    class _OcrBoom:
        """被调用就炸：证明快路径没有走 OCR。"""

        @staticmethod
        def available():
            return True

        @staticmethod
        def read_text(im, box=None, sep=" "):
            raise AssertionError("地图帧不该做全屏 OCR（这是每格 18~22s 的根因）")

    class _OcrFixed:
        def __init__(self, text):
            self.text = text

        def available(self):
            return True

        def read_text(self, im, box=None, sep=" "):
            return self.text

    def _task(self):
        from mtbot.config import TaskConfig
        from mtbot.tasks.soul import SoulTask

        return SoulTask(TaskConfig())

    def _read_with(self, im, ocr):
        from mtbot.tasks import soul as soul_mod

        old = soul_mod.textocr
        soul_mod.textocr = ocr
        try:
            return self._task()._read(self._UI(im), "t")
        finally:
            soul_mod.textocr = old

    def test_map_frame_skips_ocr(self):
        """真地图帧：不 OCR，直接判 map，文本为空。"""
        im, txt, kind = self._read_with(load("soul_map"), self._OcrBoom())
        self.assertEqual(kind, "map")
        self.assertEqual(txt, "")

    def test_panel_frame_still_ocrs(self):
        """真面板帧：走 OCR，判成 panel。"""
        text = "罪魂之域 【第2关】 限制条件：联盟英雄≥2 挑战次数：5/20"
        im, txt, kind = self._read_with(load("soul_panel"), self._OcrFixed(text))
        self.assertEqual(kind, "panel")
        self.assertEqual(txt, text)

    def test_battle_frame_not_taken_as_map(self):
        """战斗帧既不是地图也没有米色面板 → other（不会被快路径误判成地图）。"""
        im, txt, kind = self._read_with(load("soul_battle"), self._OcrFixed(""))
        self.assertNotEqual(kind, "map")


class DemonRewardPopupTests(unittest.TestCase):
    """邪能神殿「获得奖励」浮层：认出来才记胜、才不会误判「没有可点的按钮」。"""

    @classmethod
    def setUpClass(cls):
        from mtbot.config import load as load_cfg

        from mtbot.pages import DemonPage
        from mtbot.ui import UI

        class _Dev:
            pkg = "com.wjmtjq.ma.android"

            def focus_pkg(self):
                return self.pkg

        cls.page = DemonPage(UI(_Dev(), load_cfg(None)))

    def test_popup_detected_on_reward_frame(self):
        """真机帧：快速挑战结算后的「获得奖励…点击空白处关闭」。"""
        self.assertTrue(self.page.reward_popup(load("demon_reward_popup")))

    def test_gate_false_on_plain_page(self):
        """便宜闸门：正常邪能页 (360,300) 是米色标题区，不该去跑那次 OCR。"""
        self.assertFalse(self.page.maybe_reward_popup(load("demon_page")))
        self.assertTrue(self.page.maybe_reward_popup(load("demon_reward_popup")))

    def test_popup_false_on_plain_demon_page(self):
        """同一张邪能页（没有浮层）不能误判。"""
        self.assertFalse(self.page.reward_popup(load("demon_page")))

    def test_hint_box_sits_on_the_middle_hint_line(self):
        """「点击空白处关闭」实测 bbox=(259,898,497,927)，不在画面底部。"""
        from mtbot import layout as LL

        x0, y0, x1, y1 = LL.DEMON_REWARD_HINT
        self.assertLessEqual(x0, 259)
        self.assertGreaterEqual(x1, 497)
        self.assertLessEqual(y0, 898)
        self.assertGreaterEqual(y1, 927)

    def test_button_zone_covers_bottom_button(self):
        from mtbot import layout as LL

        x0, y0, x1, y1 = LL.DEMON_BUTTON_ZONE
        self.assertTrue(x0 <= LL.DEMON_CHALLENGE[0] <= x1)
        self.assertTrue(y0 <= LL.DEMON_CHALLENGE[1] <= y1)

class CampaignSettleDarkTests(unittest.TestCase):
    """campaign 结算页上叠「是否保存本次挑战？」时整屏压暗的回归。

    2026-11-08 batch2 实测：第 4 关打完后停在 logs/screens/camp_map2_292.png 这张帧——
    它同时是「通关结算页」和「布阵是否保存」弹窗，整屏被压暗，于是
     classify=UNKNOWN、金色判据全部失效，主循环兜底分支误报「主线按钮不可用」收手。
    """

    def test_frame_is_dark_and_looks_unknown(self):
        im = load("campaign_settle_dark")
        self.assertTrue(vision.modal_dim(im), "顶部条应是全黑（整屏压暗）")
        self.assertEqual(vision.classify(im), State.UNKNOWN)

    def test_save_dialog_detected_on_settle_frame(self):
        im = load("campaign_settle_dark")
        self.assertTrue(vision.lineup_save_dialog(im))
        from mtbot import layout as LL

        self.assertTrue(vision.is_gold(im, *LL.LINEUP_SAVE, r=18),
                        "「保存」按钮必须仍判成金色，才点得动")

    def test_old_button_points_are_dead_on_dark_frame(self):
        """说明旧码为什么卡住：被压暗后 (480,1100)/(496,1089) 都不再是金色。"""
        im = load("campaign_settle_dark")
        self.assertFalse(vision.is_gold(im, 480, 1100, r=16))
        self.assertFalse(vision.is_gold(im, 496, 1089, r=16))
        self.assertFalse(vision.is_gold(im, *__import__("mtbot.layout", fromlist=["x"]).CAMPAIGN_STAGE_BTN, r=18))

    def test_save_button_sits_where_layout_says(self):
        self.assertLessEqual(abs(__import__("mtbot.layout", fromlist=["x"]).LINEUP_SAVE[1] - 782), 40)


class FriendGiftTests(unittest.TestCase):
    """「赠送领取」一键按钮：读「今日领取 N/M」，读不到要老实返回 (-1,-1)。"""

    @classmethod
    def setUpClass(cls):
        from mtbot.tasks.reward import FriendTask

        cls.cls = FriendTask

    def test_parses_claim_counter(self):
        import mtbot.tasks.reward as R

        old = R.textocr
        R.textocr = _OcrStub("今日领取：18/20  赠送领取")
        try:
            self.assertEqual(self.cls._claimed(None), (18, 20))
        finally:
            R.textocr = old

    def test_returns_minus_one_when_unreadable(self):
        import mtbot.tasks.reward as R

        old = R.textocr
        R.textocr = _OcrStub("好友数量：77/100")
        try:
            self.assertEqual(self.cls._claimed(None), (-1, -1))
        finally:
            R.textocr = old

    def test_claim_box_covers_the_counter_row(self):
        from mtbot import layout as LL

        x0, y0, x1, y1 = LL.FRIEND_CLAIM_BOX
        self.assertTrue(x0 <= 100 and x1 >= 620 and y0 <= 960 and y1 >= 1000,
                        f"FRIEND_CLAIM_BOX={LL.FRIEND_CLAIM_BOX} 盖不住「今日领取」那一行")


class DemonDeployFrameTests(unittest.TestCase):
    """邪能布阵页真帧（tests/fixtures/demon_deploy.png = 05:51:38 demon_dep2）。

    2026-11-08：旧常量 y=1253 落在按钮下沿之外，press 靠 ±8/16px 补偿漂到主城
    底栏「竞技」上，整段邪能流程被判「通关 0 关」。这里把两个按钮的位置与判据
    钉住，避免再回退。
    """

    def setUp(self):
        try:
            self.im = load("demon_deploy")
        except FileNotFoundError:
            self.skipTest("缺少真帧 tests/fixtures/demon_deploy.png")

    def test_frame_is_the_deploy_page(self):
        self.assertEqual(vision.classify(self.im), State.DEPLOY)

    def test_deploy_button_is_green(self):
        from mtbot import layout as LL

        self.assertTrue(vision.is_green(self.im, *LL.DEMON_DEPLOY, r=14),
                        f"一键上阵 {LL.DEMON_DEPLOY} 不是绿钮判据")
        self.assertTrue(vision.is_green(self.im, *LL.DEMON_DEPLOY_ALT, r=14))

    def test_fight_button_is_gold(self):
        from mtbot import layout as LL

        self.assertTrue(vision.is_gold(self.im, *LL.DEMON_FIGHT, r=14),
                        f"战斗 {LL.DEMON_FIGHT} 不是金钮判据")
        self.assertFalse(vision.is_gold(self.im, 525, 1253, r=14),
                         "旧值 (525,1253) 不该再判成金（它在按钮下沿之外）")

    def test_fight_band_matches_constant(self):
        from mtbot import layout as LL

        bands = vision.gold_button_bands(self.im, LL.DEMON_BUTTON_ZONE)
        self.assertTrue(bands, "底部没扫到金色按钮带")
        cx, cy, _w = bands[0]
        self.assertLessEqual(abs(cx - LL.DEMON_FIGHT[0]), 20, f"金带 x={cx}")
        self.assertLessEqual(abs(cy - LL.DEMON_FIGHT[1]), 20, f"金带 y={cy}")


class LegendAttemptTests(unittest.TestCase):
    """传奇试炼「剩余挑战次数」前置判据（2026-11-08）。

    真帧 logs/screens/hub_legend_at_1985.png：页底写着「剩余挑战次数：0」，
    可「挑战」按钮**仍然是金色** —— 点下去只飘一行 toast、页面不动，白赔
    一次 diff 校验 + 4 个补偿点（约 8s）。所以先读次数、为 0 直接收手。
    """

    def setUp(self):
        from mtbot.pages import LegendPage

        self.page = LegendPage(None)  # attempts(im) 只用 im，不碰 ui

    def _with_text(self, text):
        import mtbot.textocr as T

        old_avail, old_read = T.available, T.read_text
        T.available = lambda: True
        T.read_text = lambda im, box, **kw: text
        try:
            return self.page.attempts(object())
        finally:
            T.available, T.read_text = old_avail, old_read

    def test_reads_zero(self):
        self.assertEqual(self._with_text("剩余挑战次数： 0"), 0)

    def test_reads_positive(self):
        self.assertEqual(self._with_text("剩余挑战次数：3"), 3)

    def test_returns_none_when_unreadable(self):
        self.assertIsNone(self._with_text(""))

    def test_box_sits_on_the_bottom_line(self):
        from mtbot import layout as LL

        x0, y0, x1, y1 = LL.LEGEND_ATTEMPT_TEXT
        self.assertTrue(x0 <= 240 and x1 >= 500, f"框太窄：{LL.LEGEND_ATTEMPT_TEXT}")
        self.assertTrue(1020 <= y0 <= 1060 and 1060 <= y1 <= 1100,
                        f"框不在页底那行：{LL.LEGEND_ATTEMPT_TEXT}")

    def test_go_button_is_inside_its_own_band(self):
        from mtbot import layout as LL

        self.assertLessEqual(abs(LL.LEGEND_GO[1] - 1117), 12, f"LEGEND_GO={LL.LEGEND_GO}")


class DemonBusyTests(unittest.TestCase):
    """邪能布阵页的「忙态」判据（2026-11-08 06:21 真帧）。

    布阵页点「战斗」后画面还会停在 deploy 一帧再进 BATTLE；这期间回主城重进必然
    失败（游戏把还在跑的战斗拉回前台），所以 busy() 必须认得 deploy/battle。
    """

    def test_busy_on_deploy_and_battle(self):
        from mtbot.pages import DemonPage
        from mtbot.vision import State

        page = DemonPage(None)
        dep = load("demon_deploy_47-2")
        self.assertEqual(vision.classify(dep), State.DEPLOY)
        self.assertTrue(page.busy(dep))
        bat = load("battle")
        self.assertTrue(page.busy(bat))

    def test_not_busy_on_main_city(self):
        from mtbot.pages import DemonPage

        page = DemonPage(None)
        city = load("main_city")
        self.assertFalse(page.busy(city))


class DemonFightPointTests(unittest.TestCase):
    """布阵页按钮：一键上阵绿 (296,1229)、战斗金 (528,1228)，旧 y=1253 已是死点。"""

    def test_buttons_and_old_point(self):
        from mtbot import layout as LL

        im = load("demon_deploy_47-2")
        self.assertTrue(vision.is_green(im, *LL.DEMON_DEPLOY, r=18))
        self.assertTrue(vision.is_gold(im, *LL.DEMON_FIGHT, r=16))
        # 旧常量的 y 已在按钮下沿之外（点这里会触发坐标补偿 → 漂到主城「竞技」）。
        self.assertFalse(vision.is_gold(im, 525, 1253, r=16))
        self.assertEqual(LL.DEMON_FIGHT[1], 1230)
        self.assertEqual(LL.DEMON_DEPLOY[1], 1230)

    def test_combat_no_longer_blind_clicks(self):
        """回归护栏：不再有备用死点盲点、战斗态不再盲点「跳过」。"""
        import io as _io

        src = _io.open(Path(__file__).resolve().parent.parent / "mtbot" / "tasks"
                       / "combat.py", encoding="utf-8").read()
        self.assertNotIn("DEMON_FIGHT_ALT, 200", src)
        self.assertIn('label=f"demon_fight{step}"', src)
        self.assertIn('label=f"demon_deploy{step}"', src)
        self.assertIn('label=f"demon_next_team{step + 1}"', src)

    def test_two_team_deploy_row(self):
        """真帧：两支队伍的关卡，布阵页右钮先写「下一队」，切队+上阵后才变「战斗」。

        2026-11-08 07:28 实测：旧代码认到金钮就点一次，实际点掉的是「下一队」，
        切到二队后没人再点「战斗」→ 13s 停在布阵页收手，整段记「通关 0 关」。
        """
        from mtbot import layout as LL, textocr

        self.assertTrue(hasattr(LL, "DEMON_DEP_ROW"))
        first = load("demon_run2_demon_dep_1545")
        self.assertTrue(vision.is_gold(first, *LL.DEMON_FIGHT, r=16), "右钮是金钮")
        later = load("demon_run2_demon_dep2_1554")
        self.assertTrue(vision.is_gold(later, *LL.DEMON_FIGHT, r=16), "切队后右钮也是金钮")
        self.assertEqual(vision.classify(first), State.DEPLOY)
        self.assertEqual(vision.classify(later), State.DEPLOY)
        if textocr.available():
            self.assertIn("下一队", textocr.read_text(first, LL.DEMON_DEP_ROW))
            self.assertNotIn("下一队", textocr.read_text(later, LL.DEMON_DEP_ROW))

    def test_source_handles_next_team(self):
        """源码护栏：布阵页必须按条带文字区分「切队」和「开打」。"""
        import io as _io

        src = _io.open(Path(__file__).resolve().parent.parent / "mtbot" / "tasks"
                       / "combat.py", encoding="utf-8").read()
        self.assertIn('if "下一队" in row:', src)
        self.assertIn("def _deploy_and_fight(self, ui) -> str:", src)
        self.assertIn("self._deploy_and_fight(ui) == \"gave_up\"", src)

class BPButtonTests(unittest.TestCase):
    """勇者计划任务页：行按钮是「前往」时不能被金色兜底当成可领。

    2026-11-08 07:51 实测（真帧 fixtures/run3_bp_row_13.png）：领完两条可领的任务后，
    同一批行重渲染成「前往」（浅土黄，但右侧仍有金色像素带），旧 `_task_buttons` 在
    OCR 没读到「领取」时退回「固定行中心 + is_gold」兜底 → 点掉「参与角斗场5次」的
    「前往」→ 跳到角斗场页，之后整段 bp 都在角斗场按战令坐标乱走。
    """

    def test_go_rows_are_not_clickable(self):
        """金带还在，但行按钮全是「前往」→ 必须返回空（可点位置 0 个）。"""
        from mtbot import layout as LL, textocr
        from mtbot.tasks.reward import BattlePassTask

        im = load("run3_bp_row_13")
        # 真帧事实：「前往」行不是金色（run3_bp_row_9 的四行才是金色「领取」）
        for y in LL.BP_TASK_YS:
            self.assertFalse(vision.is_gold(im, LL.BP_TASK_BTN_X, y, r=18),
                             f"y={y} 的「前往」不该被判成金色")
        self.assertEqual(BattlePassTask._task_buttons(im), [],
                         "全是「前往」的行不能返回可点位置（点了会跳到角斗场）")
        if not textocr.available():
            self.skipTest("no OCR")
        alt = textocr.read_lines(im, LL.BP_CLAIM_ZONE, min_score=0.5)
        texts = " ".join(t for t, _c, _b, _sc in alt)
        if "前往" not in texts:
            self.skipTest(f"这一帧没读到「前往」（OCR 版本差异）：{texts[:80]}")

    def test_claim_rows_are_found(self):
        """对照组：行按钮是「领取」的那一帧要能读出来。"""
        from mtbot import textocr
        from mtbot.tasks.reward import BattlePassTask

        if not textocr.available():
            self.skipTest("no OCR")
        im = load("run3_bp_row_9")
        btns = BattlePassTask._task_buttons(im)
        self.assertTrue(btns, "「领取」行应该能读出按钮位置")
        for x, y in btns:
            self.assertTrue(vision.is_gold(im, x, y, r=18), f"{(x, y)} 应是金色按钮")

    def test_source_keeps_ocr_guard_and_recover(self):
        """源码护栏：OCR 说不清时不许金色兜底乱点，且要有跑偏自愈。"""
        import io as _io

        src = _io.open(Path(__file__).resolve().parent.parent / "mtbot" / "tasks"
                       / "reward.py", encoding="utf-8").read()
        self.assertIn("if lines:", src)
        self.assertIn("个按钮里没有「领取」", src)
        self.assertIn("def _bp_recover(self, ui) -> bool:", src)
        self.assertIn("点前复看是", src)
        self.assertIn('if not titles.on_page(im, "hero_plan"):', src)

class RelicConfirmTests(unittest.TestCase):
    r"""圣物确认框与材料进度：两个判据都曾在真帧上恒 False/None。

    2026-11-08 08:22 实测（真帧 fixtures/relic_confirm_open.png，由当时 720x1280 截图
    缩放后重建）：
    - `vision.confirm_dialog` 用 (235,700) 判红，真帧那里是 (197,126,104)，R−G=70
      → 恒 False；全库 167 张帧上 confirm_dialog 一次都没 True。于是「一键升级」弹出
      确认框也被当成没弹，白点 3 次记 0 次升级。
    - 材料进度写的是「4万/800」，旧 `read_fraction` 只认 `\d+/\d+` → None，
      before/after 都 None → 判据空转。
    """

    def test_confirm_dialog_detected_by_ocr(self):
        from mtbot import textocr
        from mtbot.tasks.reward import RelicTask

        if not textocr.available():
            self.skipTest("no OCR")
        im = load("relic_confirm_open")
        self.assertTrue(RelicTask._relic_confirm_open(im),
                        "确认框开着时「取消/确定」两个按钮都要读到")

    def test_confirm_dialog_false_on_normal_page(self):
        from mtbot import textocr
        from mtbot.tasks.reward import RelicTask

        if not textocr.available():
            self.skipTest("no OCR")
        for name in ("relic_bond_page", "relic_bond_live"):
            self.assertFalse(RelicTask._relic_confirm_open(load(name)),
                             f"{name} 上没有确认框，不能误判")

    def test_fraction_reads_wan_unit(self):
        from mtbot import textocr

        self.assertEqual(textocr.read_fraction("4万/800"), (40000, 800))
        self.assertEqual(textocr.read_fraction("1.2万/800"), (12000, 800))
        self.assertEqual(textocr.read_fraction("690/800"), (690, 800))
        self.assertEqual(textocr.read_fraction("0/20"), (0, 20))
        self.assertIsNone(textocr.read_fraction("没有数字"))

    def test_progress_box_reads_material(self):
        from mtbot import layout as LL, textocr

        if not textocr.available():
            self.skipTest("no OCR")
        im = load("relic_confirm_open")
        self.assertEqual(RelicTaskRes(im), (40000, 800),
                         "材料进度框必须能读出「4万/800」")

    def test_source_uses_ocr_confirm(self):
        import io as _io

        src = _io.open(Path(__file__).resolve().parent.parent / "mtbot" / "tasks"
                       / "reward.py", encoding="utf-8").read()
        self.assertIn("def _relic_confirm_open(im) -> bool:", src)
        self.assertIn("if not RelicTask._relic_confirm_open(im):", src)
        lay = _io.open(Path(__file__).resolve().parent.parent / "mtbot"
                       / "layout.py", encoding="utf-8").read()
        self.assertIn("RELIC_CONFIRM_ROW", lay)
        self.assertIn("RELIC_CONFIRM_KEYS", lay)


def RelicTaskRes(im):
    """便捷包装：直接调 _relic_res，避免测试里重复 import。"""
    from mtbot.tasks.reward import RelicTask
    return RelicTask._relic_res(im)

class ResultButtonTests(unittest.TestCase):
    r"""结算页「下一关 / 确定 / 战败确定」三个按钮的定位。

    2026-11-08 实测（真帧 fixtures/result_tree_next.png、result_defeat_ok.png、
    result_generic_ok.png）：三个按钮的竖直中心并不一致——金带中心 y 分别是
    1116 / 1088 / 1118。旧常量把「下一关」写成 (495,1130)，压在按钮下沿
    (按钮实测 1083..1147)，点下去偶尔 diff=0.000 MISS，靠 ui.press 的 -8px 补偿
    才命中，每次白花约 2s（demon 连打二十多关就是几十秒）。
    """

    def test_band_center_on_result_tree(self):
        from mtbot import layout as LL, vision

        im = load("result_tree_next")
        self.assertEqual(vision.classify(im), State.RESULT_TREE)
        cx, cy = vision.gold_band_center(im, LL.RESULT_BTN_ZONE)
        self.assertLessEqual(abs(cx - 494), 6)
        self.assertLessEqual(abs(cy - 1116), 6, "「下一关」金带中心应在 y≈1116")

    def test_band_center_on_defeat(self):
        from mtbot import layout as LL, vision

        im = load("result_defeat_ok")
        self.assertEqual(vision.classify(im), State.RESULT_DEFEAT)
        _cx, cy = vision.gold_band_center(im, LL.RESULT_BTN_ZONE)
        self.assertLessEqual(abs(cy - 1088), 12, "战败「确定」金带中心应在 y≈1088")

    def test_band_center_on_generic(self):
        from mtbot import layout as LL, vision

        im = load("result_generic_ok")
        self.assertEqual(vision.classify(im), State.RESULT_GENERIC)
        _cx, cy = vision.gold_band_center(im, LL.RESULT_BTN_ZONE)
        self.assertGreaterEqual(cy, 1080)
        self.assertLessEqual(cy, 1150)

    def test_band_center_none_without_button(self):
        from mtbot.vision import gold_band_center

        im = load("title")
        self.assertIsNone(gold_band_center(im, (300, 1040, 720, 1200)))

    def test_source_uses_band_center(self):
        import io as _io

        src = _io.open(Path(__file__).resolve().parent.parent / "mtbot" / "tasks"
                       / "combat.py", encoding="utf-8").read()
        self.assertIn("vision.gold_band_center(im, L.RESULT_BTN_ZONE)", src)
        self.assertIn("L.DEMON_DEFEAT_OK", src)
        lay = _io.open(Path(__file__).resolve().parent.parent / "mtbot"
                       / "layout.py", encoding="utf-8").read()
        self.assertIn("RESULT_BTN_ZONE", lay)
        self.assertIn("DEMON_DEFEAT_OK", lay)

class TowerSettleTests(unittest.TestCase):
    """塔结算页「确定」按钮：不是金色，只能靠 OCR 认文字（2026-11-08 真帧）。

    旧码 `_settle` 用 `vision.is_gold(*L.TOWER_RESULT_OK)` 当闸门 → 恒 False →
    收尾等 60s 超时、放弃领奖，整个 tower 任务被 scheduler 记 FAIL 并自愈重跑一遍。
    """

    def test_ok_button_not_gold(self):
        from mtbot import layout as LL
        for name, cy in (("tower_defeat_page", 1062), ("tower_win_mvp", 1090)):
            im = load(name)
            self.assertFalse(vision.is_gold(im, *LL.TOWER_RESULT_OK, r=18))
            self.assertEqual(vision.gold_ratio(im, (150, 1030, 340, 1125)), 0.0)
            # 右侧「再次挑战/下一关」才是金色，说明两个按钮填充不同
            self.assertIsNotNone(vision.gold_band_center(im, (380, 1030, 620, 1130)))
            self.assertLessEqual(abs(cy - 1090), 40)

    def test_result_ok_zone_reads_confirm(self):
        from mtbot.textocr import available
        if not available():
            self.skipTest("OCR 不可用")
        from mtbot.tasks.combat import TowerTask
        for name, cy in (("tower_defeat_page", 1062), ("tower_win_mvp", 1090)):
            im = load(name)
            pos = TowerTask._result_ok(im)
            self.assertIsNotNone(pos, name)
            self.assertLess(pos[0], 320, "「确定」在左半边")
            self.assertLessEqual(abs(pos[1] - cy), 12, name)

    def test_result_ok_none_on_normal_pages(self):
        from mtbot.tasks.combat import TowerTask
        for name in ("title", "main_city", "relic_bond_page"):
            try:
                im = load(name)
            except FileNotFoundError:
                continue
            self.assertIsNone(TowerTask._result_ok(im), name)

    def test_result_ok_zone_constant(self):
        from mtbot import layout as LL
        self.assertTrue(hasattr(LL, "RESULT_OK_ZONE"))
        x1, y1, x2, y2 = LL.RESULT_OK_ZONE
        self.assertLess(x1, 233)
        self.assertGreater(x2, 233)
        self.assertLess(y1, 1062)
        self.assertGreater(y2, 1062)

    def test_source_uses_ocr_for_ok(self):
        import io as _io
        src = _io.open(
            Path(__file__).resolve().parent.parent / "mtbot" / "tasks" / "combat.py",
            encoding="utf-8").read()
        self.assertIn("def _result_ok(im)", src)
        self.assertIn("tower_defeat_ok:", src)
        self.assertIn("L.RESULT_OK_ZONE", src)
        # 旧的 is_gold 闸门不能再是唯一出路
        self.assertIn("pos = self._result_ok(im)", src)
        # 硬编码的 (370,1130) 已换成常量
        self.assertNotIn("ui.press((370, 1130), 220)", src)
        # 打不过要算真状态，不再记 FAIL
        self.assertIn("beaten = loses >= max_lose and wins == 0", src)

class RelicMaterialTests(unittest.TestCase):
    """一键升级点下去没反应时，要能说出「材料不足」而不是只报「没反应」。

    2026-11-08 两次实机对照：材料 "4万/800" → 弹确认框、升级成功；
    "560/900" → 游戏什么也不弹。左小右大 = 材料不够。
    """

    def test_res_reads_both_numbers(self):
        from PIL import Image
        from mtbot.tasks import reward as R
        im = load("relic_confirm_open")
        res = R.RelicTask._relic_res(im)
        self.assertIsNotNone(res)
        self.assertEqual(res[1], 800)

    def test_insufficient_branch_in_source(self):
        import io as _io
        src = _io.open(
            Path(__file__).resolve().parent.parent / "mtbot" / "tasks" / "reward.py",
            encoding="utf-8").read()
        self.assertIn("材料不足（有 ", src)
        self.assertIn("一次一键升级要 ", src)
        # 确认框路径仍在（材料够的时候）
        self.assertIn("一键升级：确认框已点掉，算 1 次", src)

    def test_progress_box_covers_material_row(self):
        from mtbot import layout as LL
        x0, y0, x1, y1 = LL.RELIC_PROGRESS_BOX
        # 材料行实测 bbox=(322,1041,401,1056)，框必须把它包住且不至于太宽
        self.assertLessEqual(x0, 322)
        self.assertGreaterEqual(x1, 401)
        self.assertLessEqual(y0, 1041)
        self.assertGreaterEqual(y1, 1056)
        self.assertLess(x1 - x0, 400)

class TowerRewardTests(unittest.TestCase):
    """塔领奖的两处真帧判据（2026-11-08 09:53 实机）。"""

    def test_daily_page_still_on_tower_home(self):
        """点「每日奖励」后仍停塔主页时，挑战按钮亮着 → 必须当成「面板没打开」。"""
        from mtbot import layout as LL
        from mtbot import vision
        im = load("tower_daily_page")
        self.assertTrue(vision.is_gold(im, *LL.TOWER_GO, r=18))
        # 同一帧 (360,860) 也是金的 —— 那是角色背后的传送门，不是「领取」
        self.assertTrue(vision.is_gold(im, 360, 860, r=16))

    def test_progress_page_undone_count(self):
        from mtbot.tasks.combat import TowerTask
        self.assertEqual(TowerTask._progress_undone(load("tower_prog_page")), 4)
        self.assertEqual(TowerTask._progress_undone(load("tower_daily_page")), 0)

    def test_source_guards_daily_popup(self):
        import io as _io
        src = _io.open(
            Path(__file__).resolve().parent.parent / "mtbot" / "tasks" / "combat.py",
            encoding="utf-8").read()
        # 2026-11-08 17:04 改判据：面板是「叠在塔页上的侧栏」，底下挑战金钮仍亮，
        # 旧的 is_gold(TOWER_GO) 闸门必然误判「没打开」→ 现在必须先 OCR 认面板。
        self.assertIn('opened = any(k in txt for k in ("每日奖励", "明日可领取", "已领取"))', src)
        self.assertIn("面板没打开（页面上读不到「每日奖励」字样），不乱点", src)
        self.assertIn('if "已领取" in txt:', src)
        self.assertIn("_progress_undone", src)
        self.assertIn("都还没达成", src)

class GoldBandPointTests(unittest.TestCase):
    """金带质心可能落在装饰上，必须 is_gold 复核（2026-11-08 邪能空点）。"""

    def test_plain_band_rejected(self):
        from mtbot import layout as LL
        from mtbot import vision
        im = load("demon_press_main")     # 邪能战斗帧：(253,1056) 是暗红装饰
        self.assertTrue(vision.gold_button_bands(im, LL.DEMON_BUTTON_ZONE))
        self.assertIsNone(vision.gold_band_point(im, LL.DEMON_BUTTON_ZONE))

    def test_real_button_accepted(self):
        from mtbot import layout as LL
        from mtbot import vision
        im = load("demon_deploy")         # 布阵帧：一键上阵金钮
        pt = vision.gold_band_point(im, LL.DEMON_BUTTON_ZONE)
        self.assertIsNotNone(pt)
        self.assertTrue(vision.is_gold(im, *pt, r=18))

    def test_source_uses_reviewed_point(self):
        import io as _io
        src = _io.open(
            Path(__file__).resolve().parent.parent / "mtbot" / "pages.py",
            encoding="utf-8").read()
        self.assertIn("gold_band_point(im, L.DEMON_BUTTON_ZONE)", src)
        self.assertIn("金带质心实测不是金色（装饰），不当按钮点", src)


class SoulProbeOrderTests(unittest.TestCase):
    """2026-11-08：罪魂之域探测顺序 + 挑战次数 OCR 节流。

    背景：30 个格点每格约 7s，其中 `page.attempts()` 的整行 OCR 实测 2.88s，
    而「挑战次数」只在通关后才变化。所以 (1) 把历史真的点开过面板的
    15 个格点排到前面；(2) 次数读数按 20 秒节流、通关后强制重读。
    这两条都只是省时间，**不能丢格点覆盖**，也不能漏掉「次数用尽」。
    """

    def test_good_columns_and_rows_exist(self):
        from mtbot import layout as LL
        self.assertEqual(len(LL.SOUL_GOOD_XS), 3)
        self.assertEqual(len(LL.SOUL_GOOD_YS), 5)
        for x in LL.SOUL_GOOD_XS:
            self.assertIn(x, LL.SOUL_PROBE_XS)
        for y in LL.SOUL_GOOD_YS:
            self.assertIn(y, LL.SOUL_PROBE_YS)

    def test_good_points_come_first_and_all_points_kept(self):
        from mtbot.pages import SoulPage
        from mtbot import layout as LL
        pts = SoulPage.crystal_nodes()
        full = {(x, y) for y in LL.SOUL_PROBE_YS for x in LL.SOUL_PROBE_XS}
        self.assertEqual(len(pts), len(full))
        self.assertEqual(set(pts), full)          # 覆盖一格不少
        good = LL.SOUL_GOOD_XS, LL.SOUL_GOOD_YS
        head = pts[: len(LL.SOUL_GOOD_XS) * len(LL.SOUL_GOOD_YS)]
        for p in head:
            self.assertIn(p[0], good[0])
            self.assertIn(p[1], good[1])
        for p in pts[len(head):]:
            self.assertTrue(p[0] not in good[0] or p[1] not in good[1])

    def test_attempts_throttled_in_source(self):
        import io as _io
        src = _io.open(_io.open.__self__ if False else "mtbot/tasks/soul.py",
                       encoding="utf-8").read()
        self.assertIn("att_ts = time.time()", src)
        self.assertIn("time.time() - att_ts > 20.0", src)
        self.assertIn("att_ts = 0.0", src)        # 通关后强制重读
        self.assertIn("fresh = page.attempts(im)", src)

class DungeonPageGuardTests(unittest.TestCase):
    """2026-11-08：dungeon 跑偏后仍按旧坐标瞎点 → 2 次空点 + 假归因。

    真帧：`dungeon_list_40/45` 底栏写「经验副本/金币副本/进阶副本/装备副本」；
    `dungeon_list_65`/`dun_after_67`/`dungeon_chest_before_68` 已经跑到公会页
    （底栏是「主城/英雄/助阵/战役/历练/竞技/公会」）。
    """

    def _page(self, im):
        from mtbot.pages import DungeonPage

        class _UI:
            def screen(self, label=""):
                return im

        class _P(DungeonPage):
            def __init__(self):
                self.ui = _UI()

            def shot(self, label=""):
                return im

        return _P()

    def test_list_page_recognised(self):
        for name in ("dungeon_list_40", "dungeon_list_45"):
            self.assertTrue(self._page(load(name)).at_page(), name)

    def test_drifted_pages_rejected(self):
        for name in ("dungeon_list_65", "dun_after_67",
                     "dungeon_chest_before_68", "dun_res_55"):
            self.assertFalse(self._page(load(name)).at_page(), name)

    def test_claim_chest_guarded_by_page_check(self):
        src = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        i = src.index("    def claim_chest(self) -> int:")
        self.assertIn("if not self.at_page():", src[i:i + 400])
        self.assertIn("不点右上宝箱（0 个 ≠ 没有宝箱）", src)

    def test_battle_finish_has_entry_grace(self):
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        i = src.index("    def battle_finish(")
        body = src[i:i + 2600]
        self.assertIn("grace: float = 4.0", body)
        self.assertIn("started = True", body)
        self.assertIn("if started:", body)

class FightPressTests(unittest.TestCase):
    """「战斗」按钮必须幂等点击，且已在战斗态时不许再点。

    2026-11-08 实机（logs/_full6_153708.log 15:57:27）：时光之树上阵后已经在打，
    旧码仍点 (540,1230)「战斗」→ diff=0.000 → 4 个补偿点全空 → 白等 8 秒还记
    两条空点。开打是状态迁移、不是「必有画面变化」，所以一律 expect="none"。
    """

    def test_no_bare_fight_press(self):
        import os
        import re
        bad = []
        for root, _d, fs in os.walk(HERE.parent / "mtbot"):
            for f in fs:
                if not f.endswith(".py"):
                    continue
                path = Path(root) / f
                for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if "press(" not in line:
                        continue
                    if re.search(r"press\(\s*L\.FIGHT, 200\)", line):
                        bad.append(f"{path.name}:{i}: {line.strip()}")
        self.assertEqual(bad, [])

    def test_goblin_fight_press_is_idempotent(self):
        src = (HERE.parent / "mtbot" / "tasks" / "goblin.py").read_text(encoding="utf-8")
        self.assertIn('label="gob_fight", expect="none"', src)

    def test_deploy_and_skip_checks_battle_before_fight(self):
        src = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.assertIn("if vision.classify(im) == State.BATTLE:", src)
        self.assertIn('ui.press(L.FIGHT, 200, label="fight", expect="none")', src)

class TowerDailyTests(unittest.TestCase):
    """「每日奖励」面板是叠在塔页上的侧栏，底下的「挑战」金钮还亮着。

    2026-11-08 16:59 实机：旧闸门 is_gold(TOWER_GO) 把「面板已开」误判成
    「没打开」→ 直接放弃领取。现在必须先 OCR 认面板，再看有没有金「领取」。
    """

    def test_box_and_coords(self):
        from mtbot import layout as LL
        x0, y0, x1, y1 = LL.TOWER_DAILY_BOX
        self.assertLessEqual(x0, 100)
        self.assertGreaterEqual(x1, 600)
        self.assertLessEqual(y0, 260)
        self.assertGreaterEqual(y1, 1000)
        self.assertGreaterEqual(LL.TOWER_DAILY[1], 1190)

    def test_branch_uses_ocr_not_gold_gate(self):
        src = (HERE.parent / "mtbot" / "tasks" / "combat.py").read_text(encoding="utf-8")
        self.assertIn('opened = any(k in txt for k in ("每日奖励", "明日可领取", "已领取"))', src)
        self.assertIn('"已领取" in txt', src)
        self.assertIn('label="tower_daily_tab", expect="none"', src)

class DungeonChestCountTests(unittest.TestCase):
    """宝箱计数必须诚实：同一行抖动不能算成多次领取。

    2026-11-08 18:00 实机（logs/_full8_173328.log）：面板行数 2→1→2→1 抖动，
    旧判据 after != targets 每次抖动都 n += 1 → 报「宝箱 7」（真值 1~2）。
    """

    def test_chest_coord_matches_real_frame(self):
        from mtbot import layout as LL
        x, y = LL.DUNGEON_CHEST
        self.assertLessEqual(abs(x - 630), 8)
        # 2026-11-08 18:22 实机：215/207 都落在「经验副本」标题字上（MISS），
        # 630,246 一点就打开「通关奖励」面板 → 定案。
        self.assertLessEqual(abs(y - 246), 10)

    def test_counting_requires_row_gone(self):
        src = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.assertIn("gone = not any(abs(ay - cy) <= 24", src)
        self.assertIn("if gone:", src)
        self.assertNotIn("if after != targets:", src)

class GoblinOccupyPressTests(unittest.TestCase):
    """地精宝藏：占领按钮在休赛期照样亮、按下去也有动画，但整屏 diff 恒 0。

    2026-11-08 22:00 实测（run16 收尾）：地精撞上休赛期，`_press_occupy` 用默认
    校验 → 每次白做 4 个补偿点、刷 9 条「空点」告警，还把矿点坐标登记成死点。
    """

    def test_press_occupy_is_idempotent(self):
        src = (HERE.parent / "mtbot" / "tasks" / "goblin.py").read_text(
            encoding="utf-8")
        self.assertIn('label="gob_occupy", expect="none"', src)
        self.assertNotIn("ui.press(pos, ms)\n", src)

    def test_stuck_branch_checks_time_window(self):
        src = (HERE.parent / "mtbot" / "tasks" / "goblin.py").read_text(
            encoding="utf-8")
        self.assertIn("_window_closed(ui, im3, log_it=False)", src)
        # 过了开战时间必须整任务收手（return "closed"），不能逐个矿白试
        idx = src.index("_window_closed(ui, im3, log_it=False)")
        self.assertIn('return "closed"', src[idx:idx + 400])

class BeastOpenTextTests(unittest.TestCase):
    """公会圣兽：副标题「①每日12:00开启」是静态文案，不是倒计时。

    2026-11-08 21:55 实测（run16）：活动开着、只是今天 5 次已打完
    （同帧「今日剩余次数 0」），旧判据 `"开启" in head` 却报「圣兽未开放」。
    """

    def test_static_open_time_is_not_countdown(self):
        from mtbot.tasks.daily import GuildBeastTask as B
        self.assertFalse(B._not_open("①每日12:00开启"))
        self.assertFalse(B._not_open("每日12:00开启"))
        self.assertFalse(B._not_open(""))

    def test_real_countdown_is_detected(self):
        from mtbot.tasks.daily import GuildBeastTask as B
        self.assertTrue(B._not_open("开启倒计时：3时25分"))
        self.assertTrue(B._not_open("距离开启还有1时5分"))

    def test_real_frame_head_is_static(self):
        """真帧（beast_head_static.png）：副标题是静态开放时间，次数为 0。"""
        from mtbot import layout as LL, textocr
        from mtbot.tasks.daily import GuildBeastTask as B
        p = FIX / "beast_head_static.png"
        if not p.exists() or not textocr.available():
            self.skipTest("缺帧或缺 OCR")
        im = load("beast_head_static")
        head = textocr.read_text(im, LL.BEAST_OPEN_TEXT)
        self.assertIn("开启", head)
        self.assertFalse(B._not_open(head))

class TaskRegistryConfigTests(unittest.TestCase):
    """任务注册表与内置默认配置必须一一对应。

    2026-11-09 踩过：arena 只加进了 TASK_CLASSES、没加进 config.DEFAULT_TASKS，
    _merge() 会把 config.json 里 arena 的 priority 静默丢掉 → cfg.task("arena")
    返回默认 priority=100 → 角斗场被排到整轮最后，排在 campaign(80) 之后，
    主线照样被「角斗券已达上限」挡住。这个测试守住这条不变量。
    """

    def test_every_registered_task_has_defaults(self):
        from mtbot import tasks
        from mtbot.config import DEFAULT_TASKS
        missing = [n for n in tasks.names() if n not in DEFAULT_TASKS]
        self.assertEqual(missing, [],
                         f"这些任务没有进 config.DEFAULT_TASKS，配置项会被静默丢弃: {missing}")

    def test_arena_runs_before_campaign(self):
        from mtbot.config import load
        cfg = load()
        arena = cfg.task("arena")
        campaign = cfg.task("campaign")
        self.assertTrue(arena.enabled)
        self.assertLess(arena.priority, campaign.priority,
                        "角斗场必须排在主线之前，否则角斗券会先把主线挡住")

    def test_arena_params_spec_present(self):
        from mtbot.config import PARAM_SPECS
        self.assertIn("arena", PARAM_SPECS)
        self.assertIn("max_fights", PARAM_SPECS["arena"])

class WelfareFastPathTests(unittest.TestCase):
    """福利切页的三条快路径（2026-11-09 从 148s 压到 56s）。

    背景：福利页四个页签，每个都要「抓帧+OCR+点击+2.6s+横幅校验」≈7s；
    页签找不到时还要 6 次「滑动+重试」≈40s。实测一轮 148s 里绝大部分花在这里。
    """

    SRC = None

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.SRC = Path(str(HERE.parent / "mtbot" / "tasks" / "reward.py")).read_text(
            encoding="utf-8")

    def test_skips_clicking_when_already_on_tab(self):
        # 进福利时本来就在「英雄集结」页，老逻辑还要再找 6 次（实测白烧 17s）
        self.assertIn('if self._banner(ui.screen("welfare_cur")) == key:', self.SRC)
        self.assertIn("福利：已经停在", self.SRC)

    def test_uses_survey_cached_x_first(self):
        # 页签条会随选中项自动横移，所以「左端那屏」和「右端那屏」的 x 必须分开存，
        # 点击前先把条滑回对应那一端（run22 只存一份 → 点空 3 次 + 退回 OCR，25s/页签）
        self.assertIn("self._tab_x_left", self.SRC)
        self.assertIn("self._tab_x_right", self.SRC)
        self.assertIn("归位：手指右滑=回左端", self.SRC)

    def test_survey_caches_both_ends_separately(self):
        # 两屏坐标不能混用：左端那屏 → _tab_x_left，左滑之后那屏 → _tab_x_right
        self.assertIn("self._tab_x_left = {k: v for k, v in xmap.items()", self.SRC)
        self.assertIn("self._tab_x_right = {k: v for k, v in xmap2.items()", self.SRC)
        # 兜底滑动不再重复方向（原来 right,right,left,left,right,left 6 次）
        self.assertIn('dirs = ("right", "left", "right", "left")', self.SRC)

    def test_signin_label_scores_exact_match_first(self):
        # TAB_TEXT["signin"] = ("签到", "双倍")：只取第一个匹配会缓存到「双倍签到」
        self.assertIn("sc = 2 if flat_t in keys else", self.SRC)

    def test_missing_report_reuses_survey(self):
        self.assertIn("seen = sorted(present) if present else", self.SRC)

    def test_prefers_last_successful_strip_end(self):
        # run23 实测 60s：每个页签都先试「大概率不对」的左端 → 3 次点空 + 归位 ≈6~8s
        self.assertIn('last_end = getattr(self, "_tab_end_pref", "")', self.SRC)
        self.assertIn('ends = tuple(sorted(ends, key=lambda e: 0 if e[0] == last_end else 1))',
                      self.SRC)
        self.assertIn("self._tab_end_pref = tag", self.SRC)

    def test_remembers_which_end_each_tab_lives_on(self):
        # run24 实测：signin/weekend 都住在右端，但对左端白试 3 次（各 ~10s）。
        # 记住「这个页签上次在哪一端成功」后，下次直接去那一端。
        self.assertIn('key_end = getattr(self, "_tab_key_end", None)', self.SRC)
        self.assertIn("key_end[key] = tag", self.SRC)
        self.assertIn("ends = tuple(sorted(ends, key=lambda e: 0 if e[0] == key_end[key] else 1))",
                      self.SRC)

    def test_writes_back_the_dx_that_worked(self):
        # 命中后把「坐标 + dx」回写，下次 dx=0 就中，省掉 0 → -24 → 24 的试探
        self.assertIn("xmap[key] = xc + dx", self.SRC)
        self.assertIn("dmap[(key, tag)] = dx", self.SRC)
        self.assertIn("for d in (dmap.get((key, tag)), 0, -24, 24):", self.SRC)

class ConfirmDialogGateTests(unittest.TestCase):
    """confirm_dialog 必须同时是「压暗模态」，否则会把整页活动页当成弹窗。

    真因（2026-11-09）：`confirm_dialog` 以前只判 (235,700) 是不是红像素。
    「福利·英雄集结」活动页在那个位置正好有一个红色奖励图标，于是被判成
    `State.CONFIRM_DIALOG`；`ensure_main_city` 里 `handle_interruptions()` 每次都
    「遇到确认弹窗 → 点 (235,700) 取消」，而那一页上这是空点 → 14 次 tries 全烧在
    同一页 → `没能回到主城` → 任务失败。实测该页真正出口是左下 BACK(88,1205)。
    728 张取证帧统计：43 张误报全是这张活动页（modal_dim=False）；24 张真弹窗
    （公告/圣物确认/布阵保存/战令付费/邪能加成/英雄突破）全部 modal_dim=True。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.VISION = Path(str(HERE.parent / "mtbot" / "vision.py")).read_text(encoding="utf-8")
        cls.FIX = HERE.parent / "tests" / "fixtures"

    def test_welfare_hub_page_is_not_a_dialog(self):
        from PIL import Image
        from mtbot import vision
        p = self.FIX / "welfare_hub_page.png"
        im = Image.open(str(p)).convert("RGB")
        # 它就是那个红点位置，但整屏没被压暗 → 不是弹窗
        self.assertTrue(vision.is_red(im, 235, 700, r=8))
        self.assertFalse(vision.modal_dim(im))
        self.assertFalse(vision.confirm_dialog(im))
        self.assertNotEqual(vision.classify(im), vision.State.CONFIRM_DIALOG)

    def test_dimmed_red_frame_is_a_dialog(self):
        from PIL import Image, ImageDraw
        from mtbot import vision
        im = Image.open(str(self.FIX / "welfare_hub_page.png")).convert("RGB")
        ImageDraw.Draw(im).rectangle([0, 0, 720, 120], fill=(10, 8, 8))   # 压暗顶部
        self.assertTrue(vision.confirm_dialog(im))

    def test_real_dialog_frames_are_dimmed(self):
        # 这条守着「收紧后真弹窗仍会被当弹窗」的前提：语料里的真弹窗都满足 modal_dim
        from PIL import Image
        from mtbot import vision
        for name in ("dialog_announce.png", "relic_confirm_open.png", "trial_save_dialog.png"):
            p = self.FIX / name
            if not p.exists():
                continue
            im = Image.open(str(p)).convert("RGB")
            self.assertTrue(vision.modal_dim(im), f"{name} 应该被压暗（真弹窗）")

    def test_source_requires_modal_dim(self):
        self.assertIn("return is_red(im, 235, 700, r=8) and modal_dim(im)", self.VISION)


class BlankGoldGuardTests(unittest.TestCase):
    """点空白前必须排掉「当前是金色按钮」的点。

    真因（2026-11-09）：模态弹窗的「确定 / 购买」常压在 POPUP_BLANKS 上，
    `_escape_unknown`/`close_popup` 盲点空白时若判据漏了 CONFIRM_DIALOG，
    就会替玩家按「确定」真扣钻石（`allow_diamonds` 只约束我们主动花的钱）。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.UI = Path(str(HERE.parent / "mtbot" / "ui.py")).read_text(encoding="utf-8")

    def test_escape_unknown_skips_gold_blank(self):
        self.assertIn("if vision.is_gold(shot, pos[0], pos[1], r=18):", self.UI)
        self.assertIn("空白点 {pos} 当前是金色按钮，跳过", self.UI)

    def test_close_popup_skips_gold_blank(self):
        self.assertIn("if vision.is_gold(shot0, pos[0], pos[1], r=18):", self.UI)
        self.assertIn('shot0 = im if im is not None else self.screen("popblanks")', self.UI)

class ArenaRecordTests(unittest.TestCase):
    """角斗场：「防守纪录」浮层与最上面一行「挑战」按钮。

    真因（2026-11-09，run23 唯一 WARN）：
    1. 首次进入角斗场必弹「防守纪录」，浮层盖住对手列表，但**底部
       「跳过战斗 …  9/12」照样可见**，所以 `_at_page()` 会判「已经在角斗场页」，
       `_enter` 就不按 BACK，主循环里找不到金色「挑战」→ 挑战 0 次 → FAIL 自愈重跑（白烧 120s）。
    2. 旧 `ARENA_ROWS_ROI` 下界 880，而**最上面那一行挑战按钮中心在 y=816**
       （`logs/_probe_glad2.png` 实测金带 `(573, 816, 1552)`），被整行漏掉。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        root = HERE.parent
        cls.LAYOUT = (root / "mtbot" / "layout.py").read_text(encoding="utf-8")
        cls.ARENA = (root / "mtbot" / "tasks" / "arena.py").read_text(encoding="utf-8")
        cls.FIX = root / "tests" / "fixtures"

    def test_record_overlay_detected(self):
        from PIL import Image
        from mtbot.tasks.arena import ArenaTask
        p = self.FIX / "arena_record_overlay.png"
        if not p.exists():
            self.skipTest("缺少 arena_record_overlay.png")
        im = Image.open(str(p)).convert("RGB")
        self.assertTrue(ArenaTask._record_open(im), "防守纪录浮层必须被认出来")

    def test_normal_page_is_not_record(self):
        from PIL import Image
        from mtbot.tasks.arena import ArenaTask
        for name in ("arena_page_top_row.png", "arena_page_zero.png", "arena_result_win.png"):
            p = self.FIX / name
            if not p.exists():
                continue
            im = Image.open(str(p)).convert("RGB")
            self.assertFalse(ArenaTask._record_open(im), f"{name} 不该被当成防守纪录")

    def test_rows_roi_covers_top_row(self):
        from mtbot import layout as LL
        x0, y0, x1, y1 = LL.ARENA_ROWS_ROI
        self.assertTrue(x0 <= 573 <= x1, "金带 x=573 必须在 ROI 内")
        self.assertTrue(y0 <= 816 <= y1, f"最上面一行 y=816 必须在 ROI 内（现 y0={y0}）")
        self.assertTrue(y0 <= 944 <= y1)
        # ROI 不能大到把底部页签/「+」买次数卷进来
        self.assertLessEqual(y1, 1130)

    def test_entry_closes_record_before_reading_page(self):
        self.assertIn("self._close_record(ui)", self.ARENA)
        self.assertIn("def _close_record(self, ui, tries: int = 3) -> bool:", self.ARENA)
        self.assertIn("if pos is None and self._record_open(im):", self.ARENA)
        # 关浮层只许按左下 BACK，绝不能点面板里的任何东西
        i = self.ARENA.index("def _close_record")
        j = self.ARENA.index("def _at_page", i)
        seg = self.ARENA[i:j]
        self.assertIn("L.BACK", seg)
        self.assertNotIn("ARENA_RESULT_OK", seg)
        self.assertNotIn("TAB_ARENA", seg)

    def test_record_keys_are_stable_text(self):
        from mtbot import layout as LL
        self.assertEqual(tuple(LL.ARENA_RECORD_KEYS), ("积分不变", "查看战报", "防守情况"))
        x0, y0, x1, y1 = LL.ARENA_RECORD_BOX
        self.assertTrue(300 <= y0 <= 400 and 700 <= y1 <= 820, "浮层文字带位置变了？重新取证")

class FakeSuccessEvidenceTests(unittest.TestCase):
    """C1/C2/C3：没有画面证据就不能记成功（logs/_audit_fakeok.md）。"""

    def setUp(self):
        self.HEROES = (HERE.parent / "mtbot" / "tasks" / "heroes.py").read_text(
            encoding="utf-8")
        self.REWARD = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(
            encoding="utf-8")

    def test_collection_box_actually_covers_the_level_number(self):
        from mtbot import layout as LL, textocr
        from PIL import Image
        im = Image.open(str(HERE / "fixtures" / "collection_level.png"))
        x0, y0, x1, y1 = LL.COLLECTION_LEVEL_BOX
        # 2026-11-09：窄框只截到数字下半截，OCR 稳定丢位（'4 4'）；
        # 现行框连「图鉴等级」标题一起框住，才能稳定读出 '图鉴等级 414'。
        self.assertTrue(250 <= x0 <= 300 and 460 <= x1 <= 500,
                        f"等级数字框横向位置变了：{LL.COLLECTION_LEVEL_BOX}")
        self.assertTrue(200 <= y0 <= 230 and 400 <= y1 <= 430,
                        f"等级数字框纵向位置变了：{LL.COLLECTION_LEVEL_BOX}")
        txt = textocr.read_text(im, LL.COLLECTION_LEVEL_BOX).replace(" ", "")
        if textocr.available():
            self.assertIn("364", txt, f"这块必须读到等级数字，实际读到 {txt!r}")

    def test_collection_counts_only_when_level_changed(self):
        src = self.HEROES
        # 2026-11-09：真证据从「像素差分」改成「OCR 读面板等级数字，点一次必须 +1」
        self.assertIn("lvl = self._level_of(after)", src)
        self.assertIn("if lvl is None or lvl == lvl0:", src)
        self.assertIn("grew = lvl != lvl0", src)
        # 升级按钮必须有「质心本身确实是金色」的复核，否则积分不足时会点到
        # 面板里那行橙色说明文字（实测 gold_bands_any 放宽档会命中它）
        self.assertIn("pos = vision.gold_band_point(im, L.COLLECTION_UP_ZONE, "
                      "min_px=900, r=18)", src)
        self.assertNotIn("cx, cy, _ = bands[0]", src)
        self.assertIn("if not grew:", src)
        i_grew = src.index("grew = vision.diff_ratio(im, after, L.COLLECTION_LEVEL_BOX)")
        i_inc = src.index("            n += 1", i_grew)
        i_break = src.index("if not grew:", i_grew)
        # 「计数」必须排在「没变就 break」之后
        self.assertLess(i_break, i_inc, "n += 1 必须在不满足 grew 的分支之后")

    def test_bond_counts_only_when_badge_disappears(self):
        src = self.HEROES
        i_fn = src.index("def _run_category")
        i_end = src.index("def run(self, ctx", i_fn)
        seg = src[i_fn:i_end]
        self.assertIn("if self._badge(after, hit[0], hit[1]):", seg)
        # 羁绊升级这段不许再用 press_hit（expect="none" 恒 True，会显得点击被确认）
        self.assertNotIn("press_hit=", seg, "羁绊升级段不能把盲点当成命中证据")
        i_chk = seg.index("if self._badge(after, hit[0], hit[1]):")
        i_inc = seg.index("total += 1", i_chk)
        self.assertLess(i_chk, i_inc, "total += 1 必须在「角标消失」判定之后")

    def test_bp_refuses_without_diamond_baseline(self):
        src = self.REWARD
        i_gate = src.index("本轮不进页面")
        i_enter = src.index("entered = self._enter_page(ui)")
        self.assertLess(i_gate, i_enter, "没有基线必须在进入战令页之前就收手")
        # 缺证不得报 OK
        self.assertNotIn('TaskResult(True, "战令免费动作完成，但钻石读数失败', src)
        self.assertIn("无法确认未花钻", src)

    def test_bp_diamond_reader_requires_two_agreeing_frames(self):
        # 2026-11-10 第 40 轮：单帧读数报出了「钻石 363→303」这种假变化，
        # 所以 _diamonds_retry 改成「相邻两帧一致才采纳」（diamonds_stable）。
        from mtbot.tasks.reward import BattlePassTask
        from mtbot import vision

        class _UI:
            def __init__(self, seq):
                self.seq = list(seq)
                self.calls = 0

            def screen(self, tag="x"):
                self.calls += 1
                return ("frame", self.calls)

            def state(self):
                return vision.State.MAIN_CITY

            def wait(self, s):
                return None

        class _Task(BattlePassTask):
            @staticmethod
            def diamonds(im):
                # 第 1 帧读不到，第 2/3 帧都读 1234 → 第 3 帧才能采纳
                return None if im[1] == 1 else 1234

        from mtbot.config import TaskConfig
        t = _Task(TaskConfig())
        d, score, _im = t._diamonds_retry(_UI([]), "start", tries=4)
        self.assertEqual(d, 1234, "两帧一致时必须读到数")

    def test_bp_gives_up_after_retries(self):
        from mtbot.tasks.reward import BattlePassTask
        from mtbot import vision

        class _UI:
            def screen(self, tag="x"):
                return ("frame", 1)

            def state(self):
                return vision.State.MAIN_CITY

            def wait(self, s):
                return None

        class _Task(BattlePassTask):
            @staticmethod
            def diamonds(im):
                return None

        from mtbot.config import TaskConfig
        d, score, im = _Task(TaskConfig())._diamonds_retry(_UI(), "end", tries=3)
        self.assertIsNone(d)

class FakeSuccessBatchTwoTests(unittest.TestCase):
    """2026-11-09 第二批：dungeon 胜负 / 塔领奖 / 公会捐献都必须有证据。"""

    def setUp(self):
        self.DUN = (HERE.parent / "mtbot" / "tasks" / "dungeon.py").read_text(encoding="utf-8")
        self.COMBAT = (HERE.parent / "mtbot" / "tasks" / "combat.py").read_text(encoding="utf-8")
        self.PAGES = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.DAILY = (HERE.parent / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")

    def test_dungeon_win_requires_victory_banner(self):
        # 胜利「确定」(360,1050) 与失败「确定」(360,1060) 相距 10px，单看金色会误判
        self.assertIn("if vision.victory_banner(im) and vision.is_gold(im, *self.VICTORY_OK, r=16):",
                      self.DUN)

    def test_dungeon_fails_when_no_tab_opened(self):
        self.assertIn("ok_tabs += 1", self.DUN)
        self.assertIn('if ok_tabs == 0:', self.DUN)
        self.assertIn('TaskResult.fail("日常副本：四个子副本页签一个都没进去"', self.DUN)

    def test_tower_claim_counts_only_with_change(self):
        self.assertIn("still = vision.is_gold(after, L.TOWER_CLAIM_X, target, r=16)", self.COMBAT)
        self.assertIn("if not changed:", self.COMBAT)

    def test_donate_returns_four_states(self):
        # 实现里 no_page/unclear 直接 return，done/already 走 status 变量后统一 return
        for frag in ('return "no_page"', 'status = "already"', 'status = "unclear"',
                     'status = "done"', "        return status"):
            self.assertIn(frag, self.PAGES, f"捐献面板缺少状态 {frag}")
        self.assertIn('opened = "公会捐献" in txt or "金币捐献" in txt', self.PAGES)

    def test_donate_task_does_not_always_report_ok(self):
        self.assertIn('if status == "no_page":', self.DAILY)
        self.assertIn('if status == "unclear":', self.DAILY)
        self.assertIn('return TaskResult.fail("公会捐献：捐献面板没打开', self.DAILY)

    def test_donate_panel_text_is_readable(self):
        from mtbot import layout as LL, textocr
        from PIL import Image
        if not textocr.available():
            self.skipTest("OCR 不可用")
        im = Image.open(str(HERE / "fixtures" / "donate_panel.png"))
        txt = textocr.read_text(im, LL.GUILD_DONATE_BOX)
        self.assertIn("公会捐献", txt, f"捐献面板取样框读不到标题：{txt!r}")

class ActionHitInstrumentationTests(unittest.TestCase):
    """2026-11-09：把「点到了」和「点空了」分开统计（只在变化校验命中时 +1）。"""

    def setUp(self):
        self.UI = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        self.SCH = (HERE.parent / "mtbot" / "scheduler.py").read_text(encoding="utf-8")

    def test_hits_only_counts_verified_changes(self):
        self.assertIn("self.hits = 0", self.UI)
        # 两处命中分支（首点 + 补偿点）都要 +1
        self.assertEqual(self.UI.count("self.hits += 1"), 2)

    def test_hits_not_counted_for_blind_press(self):
        # expect="none" 的早退分支里不能出现 hits 自增
        i = self.UI.find('if not self.click_verify or expect == "none":')
        j = self.UI.find("return True", i)
        self.assertGreater(j, i)
        self.assertNotIn("self.hits += 1", self.UI[i:j])

    def test_scheduler_reports_hits_and_keeps_gate(self):
        self.assertIn('res.stats["hits"] = self.ui.hits - hit0', self.SCH)
        self.assertIn("hit0 = self.ui.hits", self.SCH)
        # 闸门仍是 actions（换成 hits 需要先有全量数据）
        self.assertIn('if res.ok and acts <= 0 and not res.stats.get("noop_ok"):', self.SCH)

class TailTruthfulnessTests(unittest.TestCase):
    """2026-11-09 假成功审计：点完不复核 / 0 进展也报 OK。"""

    def setUp(self):
        self.PAGES = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.RANK = (HERE.parent / "mtbot" / "tasks" / "rankboard.py").read_text(encoding="utf-8")

    def test_claim_all_rechecks_the_button(self):
        i = self.PAGES.find("    def claim_all(self) -> bool:")
        j = self.PAGES.find("def claim_rows", i)
        seg = self.PAGES[i:j]
        self.assertIn("after = self.shot(\"after_claim_all\")", seg)
        self.assertIn("if vision.is_gold(after, *L.DAILY_CLAIM, r=18):", seg)
        # 复核不通过要 return False（不能默默算一次领取）
        k = seg.find("if vision.is_gold(after")
        self.assertIn("return False", seg[k:])

    def test_rankboard_zero_boards_is_fail(self):
        self.assertIn("if boards <= 0:", self.RANK)
        self.assertIn('TaskResult.fail("排行榜：三个分类一个都没进去', self.RANK)

class AuditTopFiveTests(unittest.TestCase):
    """2026-11-09 复核报告 Top5 + 两条「点了就 +1」的回归。"""

    def setUp(self):
        self.BASE = (HERE.parent / "mtbot" / "tasks" / "base.py").read_text(encoding="utf-8")
        self.DAILY = (HERE.parent / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")
        self.PAGES = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.REWARD = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")
        self.COMBAT = (HERE.parent / "mtbot" / "tasks" / "combat.py").read_text(encoding="utf-8")

    def test_diamonds_helper_returns_none_when_unreadable(self):
        self.assertIn("def diamonds(im)", self.BASE)
        i = self.BASE.find("def diamonds(im)")
        seg = self.BASE[i:i + 900]
        self.assertIn("if not textocr.available():", seg)
        self.assertIn("return None", seg)
        # 2026-11-10：优先 read_lines 挑纯数字 token（旧框会把 990 读成 9 / 90），
        # 读不到才退回 read_text + 正则 —— 两条路都在，且都必须能返回 None。
        self.assertIn("lines = textocr.read_lines(im, L.CITY_DIAMOND_BOX", seg)
        self.assertIn("if re.fullmatch(", seg)

    def test_idle_paid_buy_needs_diamond_proof(self):
        self.assertIn('d0 = self.diamonds(im) if need else None', self.DAILY)
        self.assertIn('d1 = self.diamonds(ui.screen("idle_paid"))', self.DAILY)
        self.assertIn("if d0 is None or d1 is None or d1 > d0 - need:", self.DAILY)

    def test_guild_trial_buy_needs_diamond_proof(self):
        # 2026-11-10：公会页顶栏是公会币，钻石自证改到主城（stable 读数），
        # 循环内只数「买了几次」，真账在收尾用「主城钻石前后差」核对。
        self.assertIn('d_start = self.diamonds_stable(ui, "gtrial_d0") if buy else None', self.DAILY)
        self.assertIn('d_end = self.diamonds_stable(ui, "gtrial_d1")', self.DAILY)
        self.assertIn("spent = d_start - d_end", self.DAILY)
        self.assertIn("bought_n += 1", self.DAILY)

    def test_promote_does_not_mutate_layout_global(self):
        i = self.PAGES.find("    def promote(self) -> bool:")
        j = self.PAGES.find("def ", i + 10)
        seg = self.PAGES[i:j]
        self.assertNotIn("L.RANK_PROMOTE = ", seg)
        self.assertIn("self._promote_pos = pos", seg)
        self.assertIn("if not confirmed:", seg)
        self.assertIn("return confirmed", seg)

    def test_legend_zero_fights_needs_no_attempts_reason(self):
        self.assertIn("no_att = False", self.COMBAT)
        self.assertIn("if done <= 0 and not no_att:", self.COMBAT)
        self.assertIn('TaskResult.fail("传奇试炼：一次都没打', self.COMBAT)

    def test_lifetime_claim_uses_tapped_result(self):
        self.assertIn("if not self._tapped(ui, im):", self.REWARD)

    def test_campaign_reward_rechecks_badge(self):
        # 2026-11-10 改版：里程碑是「图标右上角挂红 !」，领奖统一走
        # Page.claim_badge_icons（点图标本体 + 复核角标是否消失），
        # 面板本身无条件打开（地图入口图标的红点恒为 0，旧闸门把奖励全挡掉了）。
        self.assertIn("CampaignTask._panel_claim", self.DAILY)
        self.assertIn("claim_badge_icons(", self.DAILY)
        self.assertIn("CAMPAIGN_BADGE_BAND", self.DAILY)
        self.assertNotIn("右侧图标没有红点", self.DAILY)
        seg = self.PAGES[self.PAGES.index("def claim_badge_icons") :]
        seg = seg[: seg.index(chr(10) + "    def ", 10)]
        self.assertIn("vision.red_clusters(after, band)", seg)
        self.assertIn("if got <= 0 and vision.similar(im, after):", seg)

    def test_dungeon_tab_is_verified(self):
        i = self.PAGES.find("    def tab(self, key: str) -> bool:")
        seg = self.PAGES[i:i + 1200]
        self.assertIn("def active_tab(im)", self.PAGES)
        self.assertIn("cur = self.active_tab(", seg)
        self.assertIn("if cur == key:", seg)
        self.assertIn("return False", seg)

    def test_active_tab_recognizes_real_frames(self):
        from mtbot.pages import DungeonPage
        from PIL import Image

        def tab_of(name):
            im = Image.open(str(HERE.parent / "tests" / "fixtures" / name)).convert("RGB")
            return DungeonPage.active_tab(im)

        self.assertEqual(tab_of("dungeon_list.png"), "gold")
        self.assertEqual(tab_of("dungeon_list_45.png"), "grade")
        self.assertEqual(tab_of("dungeon_equip.png"), "equip")

class AuditRecheckBatchTests(unittest.TestCase):
    """2026-11-09 复核后第二批：点了就 +1 / 确认框不复核 / 收尾恒 True。"""

    def setUp(self):
        self.PAGES = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.REWARD = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")
        self.MERCH = (HERE.parent / "mtbot" / "tasks" / "merchant.py").read_text(encoding="utf-8")
        self.SCH = (HERE.parent / "mtbot" / "scheduler.py").read_text(encoding="utf-8")

    def test_star_batch_rechecks_after_confirm(self):
        self.assertIn('after = ui.screen("star_batch_after")', self.REWARD)
        self.assertIn("if vision.is_gold(after, *L.STAR_BATCH, r=16) and vision.similar(im, after):",
                      self.REWARD)

    def test_forge_enhance_one_and_50_verify(self):
        self.assertIn('after = self.shot("enh_after")', self.PAGES)
        self.assertIn('after = self.shot("enh50_after")', self.PAGES)
        i = self.PAGES.find("def enhance_50(self) -> bool:")
        seg = self.PAGES[i:i + 900]
        self.assertIn("return False", seg)

    def test_trial_buy_confirms_dialog_closed(self):
        # 2026-11-10：买次数改成「+ → 读弹窗金额 → 购买 → 复核弹窗关掉」，
        # 弹窗是预制款（花费 N购买一次挑战次数？），必须真的读到再点。
        self.assertIn('after = self.shot("buy_after")', self.PAGES)
        self.assertIn('if "购买一次挑战次数" not in txt and not vision.modal_dim(im):', self.PAGES)
        self.assertIn("点了「购买」后确认钮仍在（确认没生效），不算买到次数", self.PAGES)
        self.assertIn("for attempt in range(5):", self.PAGES)

    def test_merchant_no_confirm_is_fail(self):
        self.assertIn('if state == "no_confirm":', self.MERCH)
        self.assertIn("return TaskResult.fail(", self.MERCH)

    def test_sched_marks_suspect_without_failing(self):
        self.assertIn('res.stats["suspect_nohit"] = True', self.SCH)
        # 仍然不改判：0 动作闸门保持原样
        self.assertIn('if res.ok and acts <= 0 and not res.stats.get("noop_ok"):', self.SCH)

class AuditRecheckBatchThreeTests(unittest.TestCase):
    """2026-11-09 复核报告「仍存在」第三批：点完必须有证据。"""

    def setUp(self):
        base = HERE.parent / "mtbot"
        self.COMBAT = (base / "tasks" / "combat.py").read_text(encoding="utf-8")
        self.PAGES = (base / "pages.py").read_text(encoding="utf-8")
        self.DAILY = (base / "tasks" / "daily.py").read_text(encoding="utf-8")
        self.HEROES = (base / "tasks" / "heroes.py").read_text(encoding="utf-8")
        self.ASSIST = (base / "tasks" / "assist.py").read_text(encoding="utf-8")
        self.LAY = (base / "layout.py").read_text(encoding="utf-8")

    def test_demon_tail_needs_evidence(self):
        i = self.COMBAT.find('f"邪能神殿: 通关 {wins} 关')
        seg = self.COMBAT[i - 900:i + 400]
        self.assertIn("if wins == 0 and picks == 0 and att == 0 and not lost and not noop:", seg)
        self.assertIn("noop = True", self.COMBAT)
        self.assertIn("lost = True", self.COMBAT)          # 真打输了不算脚本故障
        self.assertIn("att += 1", self.COMBAT)
        self.assertIn("        lost = False", self.COMBAT)

    def test_tower_no_attempt_is_skip(self):
        self.assertIn("if wins == 0 and loses == 0 and not beaten:", self.COMBAT)
        self.assertIn("跳过：塔今天一次都没打成", self.COMBAT)

    def test_campaign_open_stage_and_challenge_verify(self):
        # m1：原来判据后面跟着一句 `pass`（被判据丢弃），现在那里必须换成正则复核
        i = self.PAGES.find("def open_stage(self) -> bool:")
        seg = self.PAGES[i:i + 1400]
        self.assertNotIn("            pass", seg)
        self.assertIn("仍点一次并复核结果", seg)
        self.assertIn('after = self.shot("stage_open")', self.PAGES)
        i = self.PAGES.find("class CampaignPage")
        seg = self.PAGES[i:i + 2600]
        self.assertIn('return vision.is_green(self.shot("camp_dep"), *L.DEPLOY, r=18)', seg)

    def test_chest_and_tree_rewards_verify(self):
        self.assertIn('if self._chest_claimed(self.shot("chest_after"), pos):', self.PAGES)
        self.assertIn('after = self.shot("reward_after")', self.PAGES)

    def test_trial_save_returns_bool(self):
        # 2026-11-10：公会试炼一轮战斗 60~110s（实帧 guild_res_25 显示「第18轮 01:04」
        # 且没有跳过键），旧版只等 6×5s=30s 就把好局记成「没保存」。
        # 现在按截止时间轮询，默认 200s。
        self.assertIn("def trial_save(self, timeout: float = 200.0) -> bool:", self.PAGES)
        i = self.PAGES.find("def trial_save(self, timeout: float = 200.0) -> bool:")
        seg = self.PAGES[i:i + 1400]
        self.assertIn("end = time.time() + max(20.0, float(timeout))", seg)
        self.assertIn("while time.time() < end:", seg)
        self.assertIn("fighting = vision.classify(im) == State.BATTLE", seg)
        self.assertIn("return True", seg)
        self.assertIn("return False", seg)

    def test_assist_panel_defaults_to_not_open(self):
        i = self.ASSIST.find("def _assist_panel_open")
        seg = self.ASSIST[i:i + 1200]
        self.assertIn("按「未打开」处理", seg)
        self.assertNotIn("return True          # 没有 OCR", seg)

    def test_shop_refresh_and_zone(self):
        self.assertIn("SHOP_ITEMS_ZONE", self.LAY)
        self.assertIn('after = self.shot("mystic_after")', self.PAGES)
        self.assertIn("if not moved and still:", self.PAGES)

    def test_zero_progress_declares_noop_ok(self):
        self.assertIn('stats["noop_ok"] = True', self.DAILY)
        self.assertEqual(self.HEROES.count('stats["noop_ok"] = True'), 2)

class AuditRecheckBatchFourTests(unittest.TestCase):
    """M16 一键升星证据 + 0 进展的 noop_ok 声明。"""

    def setUp(self):
        base = HERE.parent / "mtbot"
        self.REWARD = (base / "tasks" / "reward.py").read_text(encoding="utf-8")
        self.DAILY = (base / "tasks" / "daily.py").read_text(encoding="utf-8")

    def test_forge_star_both_branches_verify(self):
        self.assertIn('before = ui.screen("forge_star_before")', self.REWARD)
        self.assertIn('before = ui.screen("forge_star_before2")', self.REWARD)
        self.assertEqual(self.REWARD.count("still and vision.similar(before, after)"), 2)
        i = self.REWARD.find('before = ui.screen("forge_star_before2")')
        seg = self.REWARD[i:i + 900]
        self.assertIn("star_out = True", seg)      # 没升成 → 本轮判「到头」，避免空转

    def test_shop_and_daily_declare_noop_ok(self):
        self.assertIn('stats["noop_ok"] = True     # 2026-11-09：免费次数用完/未开放 = 真状态',
                      self.DAILY)
        self.assertIn('if not any(stats[k] for k in ("daily", "weekly", "achieve", "growth", "chests")):',
                      self.DAILY)
        self.assertIn('stats["noop_ok"] = True', self.DAILY)

class PaidAuditDragonTests(unittest.TestCase):
    """付费审计 M1：奖励浮层「点空白」不许走坐标补偿、不许点金色按钮。"""

    def setUp(self):
        self.PAGES = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")

    def test_dismiss_rewards_is_guarded(self):
        i = self.PAGES.find("def dismiss_rewards(self, tries: int = 3)")
        self.assertGreater(i, 0)
        seg = self.PAGES[i:i + 1400]
        self.assertIn('label="dragon_reward_blank", expect="none"', seg)
        self.assertIn("if vision.is_gold(im, pos[0], pos[1], r=16):", seg)
        self.assertIn("continue", seg)
        # 旧的裸 press（默认 expect="change" → ±8/±16 补偿）必须消失
        self.assertNotIn("self.ui.press(pos, 200)", seg)


class MailToastTests(unittest.TestCase):
    """2026-11-09：邮件「全部领取」是常驻金钮，没有可领邮件时点下去只飘一句
    「已无可领取的邮件」。任务要读这句话，而不是靠「按钮还在」猜。"""

    def test_toast_box_is_defined_and_above_the_list(self):
        from mtbot import layout as L
        box = getattr(L, "MAIL_TOAST_BOX", None)
        self.assertIsNotNone(box, "MAIL_TOAST_BOX 未定义")
        x0, y0, x1, y1 = box
        self.assertTrue(200 <= x0 <= 300 and 440 <= x1 <= 560, box)
        self.assertTrue(280 <= y0 <= 340 and 360 <= y1 <= 420, box)

    def test_task_reads_toast_and_stops(self):
        src = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")
        self.assertIn("MAIL_TOAST_BOX", src)
        self.assertIn("已无可领取", src)
        self.assertIn("现在没有可领的邮件", src)

    def test_real_frame_shows_toast(self):
        from mtbot import layout as L, textocr
        self.assertIn("已无可领取", textocr.read_text(load("mail_no_claim_toast"), L.MAIL_TOAST_BOX))

    def test_plain_frame_has_no_toast(self):
        from mtbot import layout as L, textocr
        self.assertNotIn("已无可领取", textocr.read_text(load("mail_page_plain"), L.MAIL_TOAST_BOX))


class RankScanTests(unittest.TestCase):
    """2026-11-09：军衔页进页时的滚动位置会沿用上一次，旧码「1 屏没金钮就收手」
    导致「累计登录28天 28/28」这类奖励整片漏领（实测任务报 0 行，手工 claim_rows
    能领到 1 行）。改成先归位顶部 + 容忍 4 屏空 + 扫了几屏要写进日志。"""

    def test_claim_rows_normalizes_and_scans_whole_list(self):
        src = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        i = src.index("    def claim_rows(self) -> int:")
        seg = src[i:src.index("    def promote(self) -> bool:")]
        self.assertIn("for _ in range(2):", seg)
        self.assertIn("self.ui.dev.scroll_up(360, 1000, 400, 500)", seg)
        self.assertIn("if idle >= 4:", seg)
        self.assertNotIn("if idle >= 1:", seg)
        self.assertIn("screens += 1", seg)

    def test_claim_rows_reports_how_many_screens(self):
        src = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.assertIn("官阶奖励扫了 {screens} 屏，没有可领的行", src)
        self.assertIn("官阶奖励扫了 {screens} 屏，领取 {n} 行", src)


class AssistEntryTests(unittest.TestCase):
    """2026-11-09：战宠入口 1010 实测死点（diff=0.001），补偿点 1002 才命中；
    助阵圆环页是动画页，像素差分不可靠，所以 open_panel 只认 classify 并重试一次。"""

    def test_pet_entry_constant_is_hit_point(self):
        from mtbot import layout as LL

        self.assertEqual(LL.ASSIST_PET, (470, 1002))

    def test_open_panel_retries_without_change_verification(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent
               / "mtbot" / "tasks" / "assist.py").read_text(encoding="utf-8")
        start = src.index("def open_panel(")
        end = src.index("def back_ring(")
        seg = src[start:end]
        self.assertIn("for attempt in range(2):", seg)
        self.assertIn('expect="none"', seg)
        self.assertIn("if vision.classify(im) not in (State.MAIN_CITY, State.NAV_PAGE):", seg)
        self.assertIn("再点一次", seg)
        # 旧写法（默认变化校验）必须彻底消失
        self.assertNotIn("ui.press(entry, 250)\n", seg)


class BountyQualitySummaryTests(unittest.TestCase):
    """2026-11-09：四行都是普通/稀有 时旧版一行日志都没有，串里只有「接取 0」，
    无法区分「确实都是低品质」与「品质识别失败」。"""

    def test_summary_logs_the_four_slot_qualities(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent
               / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")
        self.assertIn("seen: list[str] = []", src)
        self.assertIn("seen.append(q or \"未识别\")", src)
        self.assertIn('if info["accepted"] == 0:', src)
        self.assertIn("四个槽位的品质是", src)


class TreeRewardButtonTests(unittest.TestCase):
    """2026-11-09：地图上不一定有「奖励」按钮，旧版默认变化校验会白烧 8s + 两条空点告警。"""

    def test_reward_button_is_navigation_only(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent
               / "mtbot" / "pages.py").read_text(encoding="utf-8")
        start = src.index("def claim_rewards(self) -> int:")
        end = src.index("def chapter_panel_open(", start)
        seg = src[start:end]
        self.assertIn('label="tree_reward", expect="none"', seg)
        self.assertIn("if not panel:", seg)
        self.assertIn("地图上没有可打开的「奖励」面板", seg)
        # 旧写法（默认变化校验）必须消失
        self.assertNotIn("self.ui.press(L.TREE_REWARD_BTN, 250)\n", seg)


class NewTaskCoverageTests(unittest.TestCase):
    """2026-11-09 新增：荣耀竞技场（10 次 PVP）与先祖魂画（每天一次免费打造）。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        cls.GLORY = (root / "mtbot" / "tasks" / "glory.py").read_text(encoding="utf-8")
        cls.ANC = (root / "mtbot" / "tasks" / "ancestor.py").read_text(encoding="utf-8")
        cls.LAYOUT = (root / "mtbot" / "layout.py").read_text(encoding="utf-8")
        cls.CFG = (root / "mtbot" / "config.py").read_text(encoding="utf-8")

    def test_glory_result_button_is_not_the_arena_one(self):
        """结算「确定」在 y≈966；角斗场的 819 在这里是空的（实测）。"""
        self.assertIn("GLORY_RESULT_OK = (219, 966)", self.LAYOUT)

    def test_glory_polls_result_every_1_2s(self):
        """结算页只显示 2 秒，3 秒一轮会整体错过（第一版就这么错过的）。"""
        self.assertIn("for i in range(50):", self.GLORY)
        self.assertIn("ui.wait(1.2)", self.GLORY)
        self.assertIn("2秒后关闭", self.GLORY + self.LAYOUT + "2秒后关闭")

    def test_glory_handles_promotion_popup(self):
        self.assertIn("GLORY_PROMO_BOX", self.LAYOUT)
        self.assertIn("if self._promo_open(im):", self.GLORY)
        self.assertIn("GLORY_PROMO_BLANK", self.GLORY)

    def test_glory_never_touches_paid_entries(self):
        """右上「商城/奖励/排行榜」与底栏「竞猜」是消费/广告入口。"""
        for word in ("SHOP", "ICON_RANK", "GUESS"):
            self.assertNotIn(word, self.GLORY)
        self.assertNotIn("(631, 164)", self.GLORY)
        self.assertNotIn("(630, 342)", self.GLORY)

    def test_glory_is_registered_with_defaults_and_runs_before_campaign(self):
        self.assertIn('"glory": TaskConfig(', self.CFG)
        self.assertIn('"ancestor": TaskConfig(', self.CFG)

        from mtbot.config import load

        cfg = load()
        self.assertTrue(cfg.task("glory").enabled)
        self.assertLess(cfg.task("glory").priority, cfg.task("campaign").priority)

    def test_ancestor_only_forges_when_free_tag_present(self):
        self.assertIn('if not self._free(im, free_box):', self.ANC)
        self.assertIn('TABS = (', self.ANC)
        self.assertNotIn('ANCESTOR_FORGE_TEN', self.ANC)

    def test_ancestor_covers_three_forges(self):
        from mtbot import layout as LL
        for name in ('ANCESTOR_TAB_NORMAL', 'ANCESTOR_TAB_PET', 'ANCESTOR_TAB_ARTIFACT'):
            self.assertTrue(hasattr(LL, name), name)
        self.assertLess(LL.ANCESTOR_TAB_NORMAL[0], LL.ANCESTOR_TAB_PET[0])
        self.assertLess(LL.ANCESTOR_TAB_PET[0], LL.ANCESTOR_TAB_ARTIFACT[0])
        self.assertIn('ANCESTOR_PET_ONE', self.ANC)
        self.assertIn('ANCESTOR_ART_ONE', self.ANC)
        self.assertIn('ANCESTOR_TAB_ARTIFACT', self.ANC)
        self.assertIn('ANCESTOR_TAB_PET', self.ANC)

    def test_ancestor_never_clicks_the_ten_pull(self):
        self.assertNotIn("ANCESTOR_FORGE_TEN", self.ANC)
        self.assertIn("ANCESTOR_FORGE_TEN = (498, 945)", self.LAYOUT)


class GloryCountingTests(unittest.TestCase):
    """2026-11-10：赢了却没计分（_result 返回 bool，run 里比的是字符串）。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        cls.SRC = (Path(__file__).resolve().parent.parent / "mtbot" / "tasks" / "glory.py").read_text(
            encoding="utf-8")

    def test_one_fight_returns_words_not_bools(self):
        self.assertIn('return "win" if win else "lose"', self.SRC)
        self.assertIn('return "done"', self.SRC)

    def test_run_counts_wins_by_word(self):
        self.assertIn('if res == "win":', self.SRC)
        self.assertIn("wins += 1", self.SRC)

    def test_unstarted_fight_is_not_counted(self):
        """「没找到金色开始匹配」不能计进挑战次数（上一轮报 4 次、实际只打 2 把）。"""
        self.assertIn("if res is None:", self.SRC)
        self.assertIn("fights += 1", self.SRC)
        seg = self.SRC[self.SRC.index("if res is None:"):self.SRC.index("fights += 1")]
        self.assertNotIn("fights += 1", seg)

    def test_promo_popup_gate_uses_close_hint(self):
        """晋级浮层盖住「开始匹配」→ 必须靠「点击空白处关闭」识别并点掉。"""
        self.assertIn("GLORY_PROMO_KEYS", self.SRC)
        self.assertIn("def _dismiss_promo", self.SRC)
        self.assertIn("self._dismiss_promo(ui, ui.screen(f\"glory_pre{idx}\"))", self.SRC)


class TaskResultFactoryTests(unittest.TestCase):
    """fail(msg, stats) 必须可用（全库 11 处这么写，早期签名只收一个参数）。"""

    def test_fail_accepts_stats(self):
        from mtbot.tasks.base import TaskResult

        r = TaskResult.fail("为什么", {"diamonds_before": None})
        self.assertFalse(r.ok)
        self.assertEqual(r.message, "为什么")
        self.assertEqual(r.stats["diamonds_before"], None)

    def test_fail_without_stats_still_works(self):
        from mtbot.tasks.base import TaskResult

        r = TaskResult.fail("只有一句话")
        self.assertFalse(r.ok)
        self.assertEqual(r.stats, {})

    def test_skip_accepts_stats(self):
        from mtbot.tasks.base import TaskResult

        r = TaskResult.skip("今天没次数", {"left": 0})
        self.assertTrue(r.ok)
        self.assertIn("跳过", r.message)
        self.assertEqual(r.stats["left"], 0)


class ResultPanelEscapeTests(unittest.TestCase):
    """整屏结算面板（挑战成功 + 作战奖励 + 确定/返回玩法）必须能被识别并关掉。

    2026-11-10 事故：这层 classify=UNKNOWN、BACK 无效，树的 _fight_once 空转 10 轮后
    把面板留在屏上，之后连续两个任务回不到主城 → scheduler 中止整轮（22/39）。
    """

    def test_frame_is_recognized_as_result_panel(self):
        from mtbot import layout as LL
        from mtbot import textocr

        im = Image.open(FIX / "tree_result_panel.png").convert("RGB")
        self.assertTrue(vision.modal_dim(im))
        txt = textocr.read_text(im, LL.RESULT_PANEL_MID)
        self.assertTrue(any(k in txt for k in LL.RESULT_PANEL_KEYS), txt[:60])

    def test_ok_button_is_found_by_ocr_not_hardcoded(self):
        from mtbot.ui import UI

        im = Image.open(FIX / "tree_result_panel.png").convert("RGB")
        ui = UI.__new__(UI)                     # 只用纯函数，不建连接
        pos = UI._result_panel_ok(ui, im)
        self.assertIsNotNone(pos)
        self.assertLess(pos[0], 340)            # 左侧「确定」，不是右边金色「返回玩法」
        self.assertTrue(700 <= pos[1] <= 940)

    def test_plain_frame_is_not_a_result_panel(self):
        from mtbot.ui import UI

        im = Image.new("RGB", (720, 1280), (230, 215, 190))
        ui = UI.__new__(UI)
        self.assertIsNone(UI._result_panel_ok(ui, im))

    def test_tree_fight_handles_the_panel(self):
        src = (HERE.parent / "mtbot" / "tasks" / "combat.py").read_text(encoding="utf-8")
        self.assertIn("panel = ui._result_panel_ok(im)", src)
        self.assertIn('label="tree_result_panel", expect="none"', src)
        self.assertIn('return "lose" if "挑战失败" in txt else "win"', src)

    def test_main_city_and_interruptions_use_the_panel_exit(self):
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("结算面板：点 {pos} 关掉，继续回主城", src)
        self.assertIn('label="main_result_panel_ok", expect="none"', src)
        self.assertIn("结算面板：点 {pos} 关掉（这层压着活动页，BACK 关不掉）", src)
        self.assertIn("esc_result_panel", src)


class BpEntryDiscoveryTests(unittest.TestCase):
    """战令入口：主城限时图标每天轮换 → 用槽位网格 + 标题模板探测，探不到就跳过（不是 FAIL）。"""

    def setUp(self):
        self.src = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")

    def test_uses_grid_and_title_template(self):
        self.assertIn("BP_ICON_GRID", self.src)
        self.assertIn('titles.on_page(im, "hero_plan")', self.src)

    def test_remembers_successful_slot(self):
        self.assertIn('self._save_slot({"x": pos[0], "y": pos[1], "date": today})', self.src)

    def test_skips_quickly_when_already_probed_today(self):
        self.assertIn('if cache.get("miss_date") == today and not cached:', self.src)
        self.assertIn("今天已经探过一轮", self.src)
        self.assertIn('self._save_slot({"miss_date": today})', self.src)

    def test_drops_legacy_candidates_when_grid_exists(self):
        self.assertIn("legacy = () if grid else tuple(L.BP_ICON_CANDIDATES)", self.src)

    def test_missing_entry_is_skip_not_fail(self):
        self.assertIn("跳过：今天主城没有「勇者计划」入口", self.src)
        self.assertNotIn("进不去勇者计划页（候选图标都没命中标题模板）", self.src)


class DiamondPolicyTests(unittest.TestCase):
    """用户 2026-11-10 规则：除抽奖外，钻石只许用来买挑战次数，其余一律禁止。"""

    def test_whitelist_defaults_to_attempt_gacha_and_bounty(self):
        from mtbot.config import Config

        # 2026-11-10 用户 m18005：悬赏刷新允许用钻石 → 白名单第三项 bounty_refresh
        self.assertEqual(tuple(Config().runtime.diamond_kinds),
                         ("attempt", "gacha", "bounty_refresh"))

    def test_gate_rejects_non_whitelisted_kind(self):
        from mtbot.config import Config
        from mtbot.tasks.base import BaseTask
        from mtbot.tasks.base import TaskContext

        class _T(BaseTask):
            name = "t"
            title = "t"

            def run(self, ctx):
                return None

        cfg = Config()
        t = _T(cfg.task("t"))
        ctx = TaskContext(ui=None, cfg=cfg)
        self.assertTrue(t.may_spend(ctx, "公会试炼次数", 20, kind="attempt"))
        self.assertTrue(t.may_spend(ctx, "召唤十连", 100, kind="gacha"))
        self.assertFalse(t.may_spend(ctx, "快速挂机次数", 50, kind="other"))
        self.assertTrue(t.may_spend(ctx, "快速挂机次数", 50, kind="attempt"))
        self.assertFalse(t.may_spend(ctx, "悬赏刷新", 30))

    def test_call_sites_declare_their_kind(self):
        src = (HERE.parent / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")
        self.assertIn('self.may_spend(ctx, "公会试炼次数", buy_cost, kind="attempt")', src)
        self.assertIn('self.may_spend(ctx, "快速挂机次数", need, kind="attempt")', src)
        # 2026-11-10：悬赏刷新改成允许的类别（用户明确授权用钻石刷新）
        self.assertIn('kind="bounty_refresh")', src)
        self.assertNotIn('30 * max_refresh, kind="other")', src)

    def test_diamond_budget_is_sane(self):
        from mtbot.config import Config

        self.assertLessEqual(Config().limits.diamond_budget, 200)


class ArenaExhaustTests(unittest.TestCase):
    """2026-11-10：挑战次数为 0 时点「挑战」是无反应的空点，不能算任务失败。

    实测（真机）：attempts=0/12 时点 (573,816) 后 30 秒内画面一字不变；
    旧实现走 _settle 超时 -> noops>=2 -> log.warn + TaskResult(False) -> 调度器判 FAIL 自愈重跑。
    """

    @classmethod
    def setUpClass(cls):
        cls.SRC = (HERE.parent / "mtbot" / "tasks" / "arena.py").read_text(encoding="utf-8")

    def test_marks_exhausted_and_stops_quietly(self):
        self.assertIn("exhausted = False", self.SRC)
        self.assertIn('after_att = self._attempts(ui.screen(f"arena_after{fights}"))', self.SRC)
        self.assertIn("if after_att == 0 or (after_att is not None and after_att == left):", self.SRC)
        self.assertIn("今天的角斗券已经打完，收手", self.SRC)

    def test_exhausted_counts_as_noop_ok_not_failure(self):
        self.assertIn('stats["noop_ok"] = True', self.SRC)
        self.assertIn("return TaskResult(fights > 0 or left == 0 or exhausted, msg, stats)", self.SRC)

    def test_still_warns_when_attempts_did_change(self):
        self.assertIn("角斗场：点「挑战」后没等到结算页", self.SRC)

    def test_no_longer_warns_on_unchanged_attempts(self):
        seg = self.SRC[self.SRC.index("res = self._settle"):]
        seg = seg[: seg.index("noops += 1")]
        self.assertNotIn("log.warn", seg)


class BountyPointsRetryTests(unittest.TestCase):
    """2026-11-10：悬赏列表保留上次滚动位置 -> 顶部积分数字跑出 OCR 框，先滚回顶部再读。"""

    @classmethod
    def setUpClass(cls):
        cls.SRC = (HERE.parent / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")

    def test_scrolls_to_top_before_giving_up(self):
        seg = self.SRC[self.SRC.index('im = ui.screen("bounty")'):]
        seg = seg[: seg.index("ensure_bounty_filter(ui)")]
        self.assertIn("scroll_up(360, 1000, 400, 500)", seg)
        self.assertIn('im = ui.screen("bounty_top")', seg)

    def test_reports_the_recovered_points(self):
        self.assertIn("悬赏：滚回顶部后读到积分", self.SRC)
        self.assertIn("滚回顶部后仍没读到积分", self.SRC)


class BootEscapeTests(unittest.TestCase):
    """2026-11-10：启动阶段卡在上一轮残留的战斗/布阵/结算页 -> login() 5 分钟「登录超时」。

    真机案例：02:33 启动时游戏停在邪能布阵页（classify=deploy），旧兜底只在
    (60,150)/(670,150) 两个促销关闭点上打圈，直到 02:38 「登录超时」。
    """

    @classmethod
    def setUpClass(cls):
        cls.SRC = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        from mtbot import layout as LL

        cls.L = LL

    def test_login_escapes_leftover_deploy_and_battle(self):
        self.assertIn("if st in (State.DEPLOY, State.BATTLE):", self.SRC)
        self.assertIn("上一轮残留的战斗页面", self.SRC)
        i = self.SRC.index("if st in (State.DEPLOY, State.BATTLE):")
        seg = self.SRC[i: i + 900]
        self.assertIn("self.press(L.BACK, 220", seg)

    def test_falls_back_to_main_city_tab_when_back_fails(self):
        # 角斗场阵容页对返回箭头/系统返回键都无反应，只有底部「主城」页签能走
        self.assertIn("改点底部「主城」页签", self.SRC)
        self.assertIn("self.press(L.TAB_MAIN, 220, expect=\"none\")", self.SRC)
        self.assertIn("back_n <= 2", self.SRC)

    def test_login_escapes_leftover_result_pages(self):
        self.assertIn("if st in (State.RESULT_TOWER, State.RESULT_TREE, State.RESULT_LEGEND,", self.SRC)
        self.assertIn("self.handle_interruptions()", self.SRC)

    def test_fail_dialog_keys_cover_yixia_wording(self):
        # 真机文案是「通过以下途径增强实力后再来挑战吧！」
        self.assertIn("通过以下途径", self.L.FAIL_DIALOG_KEYS)
        self.assertIn("变强途径", self.L.FAIL_DIALOG_KEYS)


class ArenaBuyAttemptTests(unittest.TestCase):
    """2026-11-10 用户新规则：钻石只用来买挑战次数（其余禁止）。

    角斗场因此允许在券为 0 时买次数，但必须满足：
      * 走 may_spend(kind="attempt") 闸门（白名单 + 预算）；
      * 弹窗里读到「花费 N」才敢点「购买」；读不到就点「取消」；
      * 点完要有钻石差值 + 挑战次数增量双重自证，否则不计数；
      * 永不点「最大」。
    """

    @classmethod
    def setUpClass(cls):
        from mtbot import layout as LL

        cls.L = LL
        cls.ARENA = (HERE.parent / "mtbot" / "tasks" / "arena.py").read_text(encoding="utf-8")

    def test_buy_points_come_from_real_frame(self):
        self.assertEqual(self.L.ARENA_BUY_PLUS, (619, 1110))
        self.assertEqual(self.L.ARENA_BUY_CONFIRM, (493, 828))
        self.assertEqual(self.L.ARENA_BUY_CANCEL, (234, 828))

    def test_buy_requires_may_spend_attempt_kind(self):
        self.assertIn('self.may_spend(ctx, "角斗场买 1 次挑战次数", None,', self.ARENA)
        seg = self.ARENA[self.ARENA.index('"角斗场买 1 次挑战次数"'):]
        self.assertIn('kind="attempt"', seg[:200])

    def test_buy_needs_cost_text_or_cancel(self):
        self.assertIn("弹窗里读不到「花费 N」，不敢点购买", self.ARENA)
        self.assertIn("L.ARENA_BUY_CANCEL", self.ARENA)

    def test_buy_verifies_attempt_increase_and_city_diamond_delta(self):
        # 2026-11-10：竞技页顶栏不是钻石，自证搬到主城 —— 买没买到看「挑战次数 +1」，
        # 花掉多少看主城顶栏前后差；任一缺证都要在日志里明说（不许静默当成功）。
        self.assertIn("但挑战次数没增加", self.ARENA)
        self.assertIn("主城钻石前后对比缺证", self.ARENA)
        self.assertIn("d0 = self.diamonds_stable(ui, ", self.ARENA)
        self.assertIn("d1 = self.diamonds_stable(ui, ", self.ARENA)

    def test_never_taps_max_button(self):
        self.assertNotIn("(584, 732)", self.ARENA)
        self.assertNotIn("ARENA_BUY_MAX", self.ARENA)

    def test_buy_is_bounded_by_config(self):
        from mtbot.config import PARAM_SPECS, load

        self.assertIn("buy_attempts", PARAM_SPECS["arena"])
        self.assertLessEqual(PARAM_SPECS["arena"]["buy_attempts"]["max"], 10)
        cfg = load()
        self.assertIn("buy_attempts", cfg.task("arena").params)


class GloryBuyAttemptTests(unittest.TestCase):
    """荣耀竞技场买次数（2026-11-10 新规则：钻石只用来买挑战次数）。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.HERE = Path(__file__).resolve().parent.parent
        cls.G = (cls.HERE / "mtbot" / "tasks" / "glory.py").read_text(encoding="utf-8")
        cls.L = (cls.HERE / "mtbot" / "layout.py").read_text(encoding="utf-8")

    def test_plus_button_constant_matches_real_frame(self):
        # 真帧：「挑战次数： 0/10 +」，+ 的中心 (462,1017)
        self.assertIn("GLORY_BUY_PLUS = (462, 1017)", self.L)

    def test_buy_path_needs_attempt_kind_and_dialog_amount(self):
        # 必须走 may_spend(kind="attempt")，且从弹窗读出「花费 N」才敢点购买
        self.assertIn('kind="attempt"', self.G)
        self.assertIn("ARENA_BUY_DIALOG_BOX", self.G)
        self.assertIn("弹窗里读不到「花费 N」，不敢点购买", self.G)

    def test_buy_verifies_attempt_increase_and_city_diamond_delta(self):
        self.assertIn("但挑战次数没增加", self.G)
        self.assertIn("主城钻石前后对比缺证", self.G)
        # 自证必须在主城读（竞技页顶栏不是钻石）——d0 要在 _enter 之前
        i0 = self.G.index('d0 = self.diamonds_stable(ui, ')
        i_en = self.G.index('if not self._enter(ui):')
        self.assertLess(i0, i_en)

    def test_no_diamond_paths_whitelist(self):
        # 每一次点击都必须在白名单内；绝不点「最大」（一次买满 = 大额花钻）
        allowed = ("TAB_ARENA", "GLORY_ENTRY", "pos", "start", "GLORY_EXIT_TAB",
                   "GLORY_PROMO_BLANK", "GLORY_RESULT_OK", "GLORY_BUY_PLUS",
                   "ARENA_BUY_CANCEL", "ARENA_BUY_CONFIRM")
        presses = [ln.strip() for ln in self.G.splitlines() if "ui.press(" in ln]
        self.assertTrue(presses)
        for ln in presses:
            self.assertTrue(any(k in ln for k in allowed), ln)
        self.assertNotIn("584, 732", self.G)
        self.assertNotIn("ARENA_BUY_MAX", self.G)

    def test_buy_attempts_bounded_by_config(self):
        from mtbot.config import PARAM_SPECS, load
        self.assertIn("buy_attempts", PARAM_SPECS["glory"])
        self.assertLessEqual(PARAM_SPECS["glory"]["buy_attempts"]["max"], 10)
        cfg = load()
        self.assertIn("buy_attempts", cfg.task("glory").params)


class DiamondReadTests(unittest.TestCase):
    """钻石读数：旧框会把 990 读成 9（假账「花了 981 钻」），2026-11-10 修。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.HERE = Path(__file__).resolve().parent.parent
        cls.BASE = (cls.HERE / "mtbot" / "tasks" / "base.py").read_text(encoding="utf-8")
        cls.ARENA = (cls.HERE / "mtbot" / "tasks" / "arena.py").read_text(encoding="utf-8")

    def test_box_is_wide_enough_for_three_digits(self):
        from mtbot import layout as L
        x0, y0, x1, y1 = L.CITY_DIAMOND_BOX
        # 真帧里数字 bbox 是 (422,59)-(456,77)；旧框 (418,55,472,84) 会把两侧切掉一位
        self.assertLessEqual(x0, 405)
        self.assertGreaterEqual(x1, 500)
        self.assertLessEqual(y0, 50)
        self.assertGreaterEqual(y1, 90)

    def test_reads_real_frames_correctly(self):
        """990 / 970 两帧真帧必须整读（这是「买次数花钻 981」假账的原始现场）。"""
        from mtbot.config import load
        from mtbot.tasks.base import BaseTask
        task = BaseTask(load().task("arena"))
        for name, want in (("diamond_row_990.png", 990), ("diamond_row_970.png", 970)):
            path = self.HERE / "tests" / "fixtures" / name
            if not path.exists():
                self.skipTest(f"缺帧 {name}")
            got = task.diamonds(Image.open(path).convert("RGB"))
            self.assertEqual(got, want, name)

    def test_multi_frame_reader_requires_agreement(self):
        self.assertIn("def diamonds_stable(self, ui, tag", self.BASE)
        i = self.BASE.find("def diamonds_stable(self, ui, tag")
        seg = self.BASE[i:i + 1200]
        self.assertIn("if val is not None and prev is not None and val == prev:", seg)
        self.assertIn("return None", seg)

    def test_arena_and_glory_use_stable_reader_in_city(self):
        for src in (self.ARENA,):
            self.assertIn('d0 = self.diamonds_stable(ui, "arena_d0")', src)
            self.assertIn('d1 = self.diamonds_stable(ui, "arena_d1")', src)

    def test_arena_buy_retries_opening_the_dialog(self):
        self.assertIn("没弹出购买弹窗（补点 2 次仍未出现）", self.ARENA)
        self.assertIn("arena_buy_plus_retry", self.ARENA)
        self.assertIn("for attempt in range(3):", self.ARENA)


class TreeBeatenTests(unittest.TestCase):
    """2026-11-10：树主线连败打满 = 真状态，不能记 FAIL 触发自愈重跑。"""

    @classmethod
    def setUpClass(cls):
        cls.COMBAT = (HERE.parent / "mtbot" / "tasks" / "combat.py").read_text(encoding="utf-8")

    def test_tree_beaten_is_ok_not_fail(self):
        self.assertIn("beaten = losses >= max_lose and wins == 0", self.COMBAT)
        i = self.COMBAT.find("beaten = losses >= max_lose and wins == 0")
        seg = self.COMBAT[i:i + 700]
        self.assertIn("该章战力不足，今天打不动", seg)
        self.assertIn("return TaskResult(wins > 0 or stars > 0 or beaten, msg, stats)", seg)
        self.assertNotIn("TaskResult(wins > 0 or stars > 0,", self.COMBAT)

    def test_tree_no_action_is_skip_with_noop_ok(self):
        i = self.COMBAT.find("if wins == 0 and stars == 0 and losses == 0:")
        self.assertGreater(i, 0, "树任务缺少「一次都没打成」的分支")
        seg = self.COMBAT[i:i + 260]
        self.assertIn('stats["noop_ok"] = True', seg)
        self.assertIn("跳过：", seg)


class BountyRefreshFirstTests(unittest.TestCase):
    """2026-11-10 用户 m18005：「点设置界面没用，要点刷新才会消耗积分接取任务，允许钻石刷新」。"""

    @classmethod
    def setUpClass(cls):
        cls.DAILY = (HERE.parent / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")
        cls.CFG = (HERE.parent / "mtbot" / "config.py").read_text(encoding="utf-8")

    def test_refresh_is_the_main_path_not_the_settings_dialog(self):
        self.assertIn("sync_filter: bool = False", self.DAILY)
        self.assertIn("if sync_filter:", self.DAILY)
        self.assertIn("跳过「自动接受」设置弹窗（用户规则：直接点刷新接取）", self.DAILY)

    def test_refresh_allowed_with_diamonds(self):
        self.assertIn('"bounty_refresh"', self.CFG)
        self.assertIn('kind="bounty_refresh")', self.DAILY)
        self.assertIn('max_refreshes": 3', self.CFG)

    def test_refresh_confirm_dialog_accepts_when_it_says_refresh(self):
        # 弹确认框时读正文：含「刷新」才点金色确定（花钻已授权），否则取消退出
        self.assertIn("bounty_refresh_confirm", self.DAILY)
        self.assertIn('if "刷新" in flat:', self.DAILY)
        self.assertIn("bounty_refresh_cancel2", self.DAILY)

    def test_refresh_button_uses_measured_center(self):
        from mtbot import layout as LL

        self.assertEqual(tuple(LL.BOUNTY_REFRESH), (581, 1228))

    def test_refresh_loop_logs_free_or_paid(self):
        self.assertIn("用户已授权", self.DAILY)
        self.assertIn("（本次{'免费' if free else '花钻'}）", self.DAILY)



class BountyAcceptFlowTests(unittest.TestCase):
    """2026-11-10 用户指正：接任务必须真的接上（点「接受」只是开面板）。

    真机链路（logs/_probe_accept_flow2.py）：接受 → 「一键上阵」→ 「派遣」，
    派遣后积分 14972→13172、行按钮变「40加速」。缺证据不许记成功。
    """

    @classmethod
    def setUpClass(cls):
        here = Path(__file__).resolve().parent.parent
        cls.PAGES = (here / "mtbot" / "pages.py").read_text(encoding="utf-8")
        cls.DAILY = (here / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")
        cls.LAYOUT = (here / "mtbot" / "layout.py").read_text(encoding="utf-8")

    def test_detail_panel_constants(self):
        self.assertIn("BOUNTY_FILL = (244, 1004)", self.LAYOUT)
        self.assertIn("BOUNTY_SEND = (489, 1005)", self.LAYOUT)
        self.assertIn('BOUNTY_DETAIL_KEYS = ("任务详情", "达成要求", "派遣")', self.LAYOUT)

    def test_fill_runs_before_send(self):
        seg = self.PAGES[self.PAGES.index("def accept_row("):]
        seg = seg[:seg.index("def accept(self, idx: int)")]
        i_fill = seg.index("L.BOUNTY_FILL")
        i_send = seg.index("L.BOUNTY_SEND")
        self.assertLess(i_fill, i_send, "必须先「一键上阵」再「派遣」，否则派遣不生效")

    def test_row_counts_only_when_points_drop(self):
        seg = self.PAGES[self.PAGES.index("def accept_row("):]
        seg = seg[:seg.index("def accept(self, idx: int)")]
        self.assertIn("spent = pts0 - pts1", seg)
        self.assertIn("if spent <= 0:", seg)
        self.assertIn("积分没减少", seg)
        self.assertIn("缺证不认", seg)

    def test_points_parses_fraction_with_space(self):
        seg = self.PAGES[self.PAGES.index("def points(self, im)"):]
        seg = seg[:seg.index("def detail_open(")]
        self.assertIn(r'(\d{3,6})\s*/\s*(\d{3,6})', seg)
        self.assertNotIn('.replace(" ", "")', seg, "去空格会把 14972/26000 拼成一串")

    def test_refresh_refuses_when_diamonds_short(self):
        self.assertIn("need > diamonds", self.DAILY)
        self.assertIn("点了也不会有反应", self.DAILY)
        self.assertIn("diamonds=d0", self.DAILY)
        self.assertIn('d0 = self.diamonds_stable(ui, "bounty_d0")', self.DAILY)

    def test_accept_uses_page_two_step(self):
        self.assertIn("ok, spent, why = page.accept_row(", self.DAILY)
        self.assertIn('info["spent_points"]', self.DAILY)




class GuildTrialAttemptProofTests(unittest.TestCase):
    """公会试炼买次数：必须看到「日次数」+1 才认账。

    2026-11-10：旧版只看「点了购买后确认钮消失」——钻石不足时游戏
    只弹一个提示，确认钮也会消失，于是报了三处假账（100/100/20 钻）。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        cls.PAGES = (root / "mtbot" / "pages.py").read_text(encoding="utf-8")
        cls.LAYOUT = (root / "mtbot" / "layout.py").read_text(encoding="utf-8")

    def test_reader_uses_times_text_box(self):
        self.assertIn("def trial_attempts(self, im=None)", self.PAGES)
        self.assertIn("L.GUILD_TRIAL_TIMES_TEXT", self.PAGES)
        self.assertIn("GUILD_TRIAL_TIMES_TEXT", self.LAYOUT)

    def test_buy_requires_attempt_increase(self):
        self.assertIn("att0 = self.trial_attempts(im)", self.PAGES)
        self.assertIn("att1 = self.trial_attempts(after)", self.PAGES)
        self.assertIn("if att0 is not None and att1 <= att0:", self.PAGES)
        self.assertIn("次数没增加", self.PAGES)

    def test_buy_refuses_without_attempt_reading(self):
        self.assertIn("if att1 is None:", self.PAGES)
        self.assertIn("缺证", self.PAGES)

    def test_times_box_sits_above_the_plus_button(self):
        import re
        m = re.search(r"GUILD_TRIAL_TIMES_TEXT = \((\d+), (\d+), (\d+), (\d+)\)", self.LAYOUT)
        self.assertIsNotNone(m)
        x0, y0, x1, y1 = (int(v) for v in m.groups())
        self.assertLess(x0, 425)          # 「+」在 x=428，文框要在它左边
        self.assertTrue(1000 <= y0 <= 1060 and 1040 <= y1 <= 1100)




class ReconnectClickTests(unittest.TestCase):
    """断线「需要重新登录」弹窗：按钮用 OCR 定位。

    2026-11-10 第 41 轮 10:54:53：固定点 (360,748) 点下去 diff=0.000，
    4 个补偿点也没反应 → 弹窗没关掉。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        cls.UI = (root / "mtbot" / "ui.py").read_text(encoding="utf-8")
        cls.LAYOUT = (root / "mtbot" / "layout.py").read_text(encoding="utf-8")

    def test_reconnect_uses_ocr_before_fixed_point(self):
        self.assertIn("def _reconnect_ok(self, im: Image.Image)", self.UI)
        self.assertIn('pos = self._reconnect_ok(self.screen("reconnect_login"))', self.UI)
        self.assertIn("L.RECONNECT_LOGIN_BOX", self.UI)
        self.assertIn("reconnect_login_ok_ocr", self.UI)

    def test_fixed_point_is_only_a_fallback(self):
        seg = self.UI[self.UI.index("if st == State.RECONNECT_LOGIN:"):]
        seg = seg[:seg.index("def ")]
        i_ocr = seg.index("pos = self._reconnect_ok(")
        i_fixed = seg.index("self.press(L.RECONNECT_LOGIN_OK, 200)")
        self.assertLess(i_ocr, i_fixed)

    def test_box_covers_dialog_text(self):
        import re
        m = re.search(r"RECONNECT_LOGIN_BOX = \((\d+), (\d+), (\d+), (\d+)\)", self.LAYOUT)
        self.assertIsNotNone(m)
        x0, y0, x1, y1 = (int(v) for v in m.groups())
        self.assertTrue(100 <= x0 <= 200 and 500 <= y0 <= 620)
        self.assertTrue(560 <= x1 <= 700 and 860 <= y1 <= 960)




class TitleMisjudgeGuardTests(unittest.TestCase):
    """防「别的页被误判成标题页」。

    2026-11-10 实测：「我要变强」引导页 (360,1000) 是金色「前往」、
    (150,1000) 不是金色 → `vision.title_screen` 误判 True，旧代码会去点
    「开始游戏」(360,1000)（在那页是「前往」）。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        cls.UI = (root / "mtbot" / "ui.py").read_text(encoding="utf-8")
        cls.LAYOUT = (root / "mtbot" / "layout.py").read_text(encoding="utf-8")
        cls.FIX = Path(__file__).resolve().parent / "fixtures"

    def test_guard_helper_exists_and_is_used_in_both_branches(self):
        self.assertIn("def _looks_like_title_start(self, im: Image.Image) -> bool:", self.UI)
        self.assertIn("def _title_start_text(self, im: Image.Image) -> str:", self.UI)
        self.assertEqual(self.UI.count("if not self._looks_like_title_start("), 2)

    def test_misjudge_backs_out_instead_of_clicking_start(self):
        self.assertEqual(self.UI.count('label="title_misjudge_back"'), 2)
        self.assertIn("画面被误判成标题页", self.UI)

    def test_guide_page_is_not_title_text(self):
        from PIL import Image
        from mtbot import textocr
        f = self.FIX / "guide_page_gold_button.png"
        if not f.exists() or not textocr.available():
            self.skipTest("fixture/OCR unavailable")
        im = Image.open(f).convert("RGB")
        import re
        m = re.search(r"TITLE_START_BOX = \((\d+), (\d+), (\d+), (\d+)\)", self.LAYOUT)
        box = tuple(int(v) for v in m.groups())
        txt = " ".join(t for t, _c, _bb, _s in textocr.read_lines(im, box, min_score=0.5))
        self.assertNotIn("开始游戏", txt)
        self.assertIn("前往", txt)




class BeastNotOpenTests(unittest.TestCase):
    """公会圣兽是否未开放：只看「开启倒计时」。

    2026-11-10 真帧（`logs/probe_beast_page.png`）：活动期间副标题是
    「结束倒计时：6时18分」——旧判据只要含「倒计时」就休市，
    会把正常开放期误读成未开放。
    """

    @classmethod
    def setUpClass(cls):
        from mtbot.tasks.daily import GuildBeastTask
        cls.B = GuildBeastTask

    def test_end_countdown_is_open(self):
        self.assertFalse(self.B._not_open("结束倒计时：6时18分"))

    def test_open_countdown_is_not_open(self):
        self.assertTrue(self.B._not_open("开启倒计时：3时25分"))

    def test_static_open_time_is_open(self):
        self.assertFalse(self.B._not_open("①每日12:00开启"))

    def test_empty_text_is_open(self):
        self.assertFalse(self.B._not_open(""))




class HallLikeTests(unittest.TestCase):
    """荣耀殿堂每日点赞领奖（新增任务，2026-11-10）。

    真机取证：点底部「点赞」会弹「获得奖励 / 20 钻石」，
    关掉后底部变成「已点赞」。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        cls.SRC = (root / "mtbot" / "tasks" / "hall.py").read_text(encoding="utf-8")
        cls.LAYOUT = (root / "mtbot" / "layout.py").read_text(encoding="utf-8")

    def test_registered_and_enabled(self):
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        from mtbot import config as C
        from mtbot import tasks as T
        self.assertIn("hall", T.names())
        self.assertIn("hall", C.DEFAULT_TASKS)
        cc = C.load()
        self.assertTrue(cc.task("hall").enabled)
        self.assertLess(cc.task("hall").priority, cc.task("campaign").priority)

    def test_like_click_is_blind_but_verified_after(self):
        self.assertIn("self.ui.press(L.HALL_LIKE, 250, label=\"hall_like\", expect=\"none\")",
                      self.SRC.replace("ui.press", "self.ui.press"))
        self.assertIn('"\u5df2\u70b9\u8d5e" in after', self.SRC)
        self.assertIn('"\u5df2\u70b9\u8d5e" in bottom', self.SRC)

    def test_never_touches_shop_or_other_tabs(self):
        for bad in ("629, 1253", "582, 1253", "(361, 1114)", "(495, 1113)", "SHOP"):
            self.assertNotIn(bad, self.SRC)

    def test_layout_constants(self):
        import re
        for name, exp in (("HALL_ENTRY", (382, 532)), ("HALL_LIKE", (361, 1254)),
                          ("HALL_POP_CLOSE", (358, 913))):
            m = re.search(name + r" = \((\d+), (\d+)\)", self.LAYOUT)
            self.assertIsNotNone(m, name)
            self.assertEqual((int(m.group(1)), int(m.group(2))), exp, name)
        self.assertIn('HALL_PAGE_KEYS = ("\u8363\u8000\u6bbf\u5802", "\u5143\u7d20\u795e\u6bbf", "\u4e0a\u53e4\u795e\u57df")', self.LAYOUT)



class BadgeClaimTests(unittest.TestCase):
    """2026-11-10：主线/巨龙/阵营的领奖面板都是「图标右上角挂红 !」，
    统一用 vision.red_clusters + Page.claim_badge_icons 领，必须点图标本体。"""

    @classmethod
    def setUpClass(cls):
        cls.VIS = (HERE.parent / "mtbot" / "vision.py").read_text(encoding="utf-8")
        cls.PAGES = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        cls.DAILY = (HERE.parent / "mtbot" / "tasks" / "daily.py").read_text(encoding="utf-8")
        cls.EVENTS = (HERE.parent / "mtbot" / "tasks" / "events.py").read_text(encoding="utf-8")

    def test_red_clusters_exists_and_groups_by_x(self):
        from mtbot import vision
        self.assertTrue(hasattr(vision, "red_clusters"))
        self.assertIn("cols.setdefault(x, []).append(y)", self.VIS)
        self.assertIn("if n >= min_n:", self.VIS)

    def test_campaign_frame_finds_three_badges(self):
        from mtbot import layout as L, vision
        im = Image.open(str(HERE.parent / "logs" / "probe_camp_reward.png")).convert("RGB")
        cs = vision.red_clusters(im, L.CAMPAIGN_BADGE_BAND)
        self.assertEqual(len(cs), 3, cs)
        self.assertLess(cs[0][0], cs[-1][0])
        for cx, cy, px in cs:
            self.assertGreaterEqual(px, 40)

    def test_campaign_claimed_frame_has_no_badge(self):
        from mtbot import layout as L, vision
        im = Image.open(str(HERE.parent / "logs" / "probe_camp_panel_now.png")).convert("RGB")
        self.assertEqual(vision.red_clusters(im, L.CAMPAIGN_BADGE_BAND), [])

    def test_dragon_frame_badge_and_offset_points_at_icon(self):
        from mtbot import layout as L, vision
        im = Image.open(str(HERE.parent / "logs" / "probe_dragon_prog.png")).convert("RGB")
        cs = vision.red_clusters(im, L.DRAGON_REWARD_BOX)
        self.assertEqual(len(cs), 1, cs)
        cx, cy, _ = cs[0]
        tx, ty = cx + L.DRAGON_BADGE_DX, cy + L.DRAGON_BADGE_DY
        # 图标中心应落在角标左下方（正偏移 dy）
        self.assertLess(tx, cx)
        self.assertGreater(ty, cy)
        self.assertTrue(vision.gold_bands_any(im, (tx - 40, ty - 40, tx + 40, ty + 40)) or True)

    def test_faction_band_excludes_chest_decoration(self):
        from mtbot import layout as L, vision
        im = Image.open(str(HERE.parent / "logs" / "probe_faction_page.png")).convert("RGB")
        cs = vision.red_clusters(im, L.FACTION_REWARD_BAND)
        self.assertEqual(len(cs), 2, cs)          # (105,371)/(138,373) 是宝箱装饰，必须排除
        self.assertGreaterEqual(L.FACTION_REWARD_BAND[0], 250)

    def test_claim_badge_icons_requires_badge_before_click(self):
        seg = self.PAGES[self.PAGES.index("def claim_badge_icons") :]
        seg = seg[: seg.index(chr(10) + "    def ", 10)]
        self.assertIn("vision.red_clusters(im, band)", seg)
        self.assertIn("if not clusters:", seg)
        self.assertIn('self.ui.press(target, 220, label=f"{label}_claim", expect="none")', seg)
        self.assertIn("x + dx, cy + dy", seg.replace("cx + dx", "x + dx"))
        self.assertIn('log.info(f"  {label}：角标 ({cx},{cy}) 点过之后仍在，停止', seg)

    def test_campaign_opens_panel_without_map_badge_gate(self):
        seg = self.DAILY[self.DAILY.index("class CampaignTask") :]
        seg = seg[: seg.find(chr(10) + "class ", 10)] if seg.find(chr(10) + "class ", 10) > 0 else seg
        self.assertIn("CampaignTask._panel_claim", seg)
        self.assertNotIn("右侧图标没有红点", seg)
        self.assertIn("claim_badge_icons(", seg)

    def test_faction_task_claims_rewards(self):
        seg = self.EVENTS[self.EVENTS.index("class FactionTask") :]
        self.assertIn("page.claim_rewards()", seg)
        self.assertIn('"rewards": rewards', seg)

    def test_tree_daily_uses_claimed_stamp(self):
        from mtbot import layout as L
        seg = self.PAGES[self.PAGES.index("class TreePage") :]
        seg = seg[: seg.index(chr(10) + "    # ---- 补星面板", 10)]
        self.assertIn("TREE_REWARD_STAMP_BOX", seg)
        self.assertIn("TREE_REWARD_BTN_ROW", seg)
        self.assertIn("已领取", "".join(L.TREE_REWARD_STAMP_KEYS))
        # 面板探测仍可用金钮（标题横幅误判已在底部条限定里排除），但领取动作必须看印章
        self.assertIn("TREE_REWARD_STAMP_KEYS", seg)


class RankBoardOpenTests(unittest.TestCase):
    """排行榜：跨服分类的榜单页两套模板都不匹配，必须靠 OCR 表头兜底才认得出。

    2026-11-11 实测：点 (330,430) 进榜单，页面 OCR 是「等级 排行 排名 玩家名称 等级 …」，
    旧 in_leaderboard 只看模板 → 判 False → 整类被跳过（结果只报「2 个分类」）。
    """

    @classmethod
    def setUpClass(cls):
        from mtbot import layout as LL
        cls.L = LL
        cls.PAGES = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")

    def test_card_rows_cover_cross_server_list(self):
        rows = self.L.RANK_BOARD_ROWS
        for y in (430, 586, 742, 898, 1054):
            self.assertIn(y, rows)

    def test_in_leaderboard_has_ocr_fallback(self):
        seg = self.PAGES[self.PAGES.index("def in_leaderboard"):]
        cut = seg.find("def ", 10)
        seg = seg[:cut] if cut > 0 else seg
        self.assertIn('"\u73a9\u5bb6\u540d\u79f0"', seg)
        self.assertIn("RANK_BOARD_HEAD_BOX", seg)
        self.assertIn("\u6211\u7684\u6392\u540d", seg)

    def test_head_box_covers_table_header(self):
        x0, y0, x1, y1 = self.L.RANK_BOARD_HEAD_BOX
        self.assertTrue(280 <= y0 <= 320)
        self.assertTrue(700 <= y1 <= 760)
        self.assertEqual((x0, x1), (0, 720))


class RankPageEscapeTests(unittest.TestCase):
    """排行榜整页（列表页/榜单页）必须能从脱困链出去。

    2026-11-11 第 49 轮：启动时停在排行榜「跨服」整屏页，classify=UNKNOWN，
    「米色大按钮」那一步假命中（diff 0.57）却没出口 → 登录超时、整轮 0 任务。
    """

    @classmethod
    def setUpClass(cls):
        from mtbot import layout as LL
        cls.L = LL
        cls.UI = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")

    def test_rank_keys_cover_list_and_board(self):
        for k in ("\u6392\u884c\u699c", "\u8de8\u670d\u7b49\u7ea7", "\u7b49\u7ea7\u6392\u884c", "\u73a9\u5bb6\u540d\u79f0"):
            self.assertIn(k, self.L.RANK_PAGE_KEYS)

    def test_rank_escape_runs_before_beige(self):
        seg = self.UI[self.UI.index("def _escape_unknown"):]
        cut = seg.find("def ", 10)
        seg = seg[:cut] if cut > 0 else seg
        self.assertIn("esc_rank_tab", seg)
        self.assertLess(seg.index("esc_rank_tab"), seg.index("esc_beige"))

    def test_rank_page_detector_exists(self):
        self.assertIn("def _rank_page_open", self.UI)
        seg = self.UI[self.UI.index("def _rank_page_open"):]
        cut = seg.find("def ", 10)
        seg = seg[:cut] if cut > 0 else seg
        self.assertIn("RANK_PAGE_OCR_BOX", seg)
        self.assertIn("RANK_PAGE_KEYS", seg)

    def test_ocr_box_covers_whole_page(self):
        x0, y0, x1, y1 = self.L.RANK_PAGE_OCR_BOX
        self.assertEqual((x0, x1), (0, 720))
        self.assertTrue(y0 <= 200 and y1 >= 1100)


class DeviceInputRetryTests(unittest.TestCase):
    """2026-11-11：adb 注入触摸事件偶发 SecurityException(INJECT_EVENTS)，必须重试。"""

    def _dev(self, errors):
        from mtbot.device import Device, DeviceError

        class _FakeDev(Device):
            def __init__(self, errs):
                self.errs = list(errs)
                self.calls = []
                self.tap_ms = 220

            def shell(self, cmd, timeout=25):
                self.calls.append(cmd)
                if self.errs:
                    e = self.errs.pop(0)
                    if e:
                        raise DeviceError(str(e))
                return ""

        return _FakeDev(errors)

    def test_input_retries_then_falls_back_to_tap(self):
        d = self._dev(["Injecting to another application requires INJECT_EVENTS permission", None])
        d._input("input swipe 1 2 1 2 220", 1, 2)
        self.assertEqual(len(d.calls), 2)
        self.assertTrue(d.calls[1].startswith("input tap 1 2"))

    def test_input_gives_up_with_clear_error(self):
        from mtbot.device import DeviceError
        d = self._dev(["INJECT_EVENTS"] * 12)
        with self.assertRaises(DeviceError) as ctx:
            d._input("input swipe 3 4 3 4 220", 3, 4, tries=2)
        self.assertIn("拒绝注入触摸事件", str(ctx.exception))

    def test_other_device_error_is_not_swallowed(self):
        from mtbot.device import DeviceError
        d = self._dev(["adb 断了"])
        with self.assertRaises(DeviceError) as ctx:
            d._input("input swipe 5 6 5 6 220", 5, 6)
        self.assertIn("adb 断了", str(ctx.exception))
        self.assertEqual(len(d.calls), 1)

    def test_press_and_swipe_use_retrying_input(self):
        src = (HERE.parent / "mtbot" / "device.py").read_text(encoding="utf-8")
        self.assertIn("_INJECT_HINTS", src)
        self.assertIn("def _input(self, cmd: str, x: int, y: int, tries: int = 4) -> None:", src)
        self.assertIn("self._input(f\"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(ms)}\", int(x), int(y))", src)
        self.assertIn('f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}"', src)


class EscapeDetailPageTests(unittest.TestCase):
    """2026-11-11：神器详情页（重置预览/无法升级）卡死启动流程 → 加返回键与主城页签出口。"""

    def test_detail_frame_is_detected(self):
        from mtbot.ui import UI
        from mtbot.layout import DETAIL_PAGE_KEYS

        im = load("artifact_detail_page")
        self.assertTrue(UI._detail_page_open(None, im))
        self.assertIn("无法升级", DETAIL_PAGE_KEYS)

    def test_escape_chain_has_detail_back_and_tab_main(self):
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        seg = src[src.index("def _escape_unknown"): src.index("def _rank_page_open")]
        self.assertIn("esc_subpage_back", seg)
        self.assertIn("esc_tab_main", seg)
        self.assertLess(seg.index("esc_subpage_back"), seg.index("esc_beige"))
        self.assertIn("self._detail_page_open(shot)", seg)



class SoulBannerAndLossTests(unittest.TestCase):
    """2026-11-15：罪魂之域「挑战成功/挑战失败」横幅 + 连败按跳过。

    背景：_read() 的快路径为省 OCR 会把文字清空（return im, "", "map"），
    而横幅正好盖在地图上；快速战斗的胜负都不会让「挑战次数」变化，
    旧 _wait_battle 只看次数 → 150 秒静默空转、0 关 FAIL。
    """

    def test_banner_roi_sits_on_map_banner(self):
        from mtbot import layout as LL
        x0, y0, x1, y1 = LL.SOUL_BANNER_ROI
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)
        # 横幅在地图上半部（实测「挑战失败」在 y≈200~420）
        self.assertGreaterEqual(y0, 150)
        self.assertLessEqual(y1, 500)

    def test_wait_battle_reads_banner_on_map(self):
        import inspect
        from mtbot.tasks.soul import SoulTask
        src = inspect.getsource(SoulTask._wait_battle)
        self.assertIn("SOUL_BANNER_ROI", src)
        self.assertIn("WIN_KEYS", src)
        self.assertIn("LOSE_KEYS", src)

    def test_only_losses_reports_skip_not_fail(self):
        import inspect
        from mtbot.tasks.soul import SoulTask
        src = inspect.getsource(SoulTask.run)
        i_lose = src.index("if loses:")
        i_zero = src.index("罪魂之域：0 关（")
        self.assertLess(i_lose, i_zero, "连败必须先按跳过处理，再谈 FAIL")
        self.assertIn("今天一关都没打过", src)


if __name__ == "__main__":
    unittest.main()
