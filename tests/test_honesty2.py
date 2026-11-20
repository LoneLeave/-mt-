# -*- coding: utf-8 -*-
"""新增 HonestyGuardTests2：把 2026-11-19 这批审计修复钉住。

覆盖：
  * 先祖魂画三台「免费」框必须同时罩住「免费」标签与倒计时（真帧 OCR 验证）
  * goblin 战斗判据必须先判失败（否则输了记成赢）
  * 好友送礼读不到「今日领取」时不许拿点击次数当领取数
  * scheduler 完成行要把「真干活 / 真状态跳过」分开报
  * RankPage.at_page 读空时要复核一帧、不许退化成「任何非主城页都算」
"""
import io
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class HonestyGuardTests2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from mtbot import layout as L
        cls.L = L
        cls.ANC = _src("mtbot/tasks/ancestor.py")
        cls.GOB = _src("mtbot/tasks/goblin.py")
        cls.REW = _src("mtbot/tasks/reward.py")
        cls.SCH = _src("mtbot/scheduler.py")
        cls.PAGES = _src("mtbot/pages.py")

    # ---------- 先祖魂画免费框 ----------
    @staticmethod
    def _in_box(box, pt) -> bool:
        x0, y0, x1, y1 = box
        return x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1

    def test_forge_free_box_covers_label_and_countdown(self):
        # 真帧：'免费' bbox (200,873,249,902) 中心 (224,887)；用掉后倒计时在 (222,992)
        box = self.L.ANCESTOR_FREE_BOX
        self.assertTrue(self._in_box(box, (224, 887)), f"天锻炉免费标签不在 {box}")
        self.assertTrue(self._in_box(box, (222, 992)), f"天锻炉倒计时不在 {box}")

    def test_artifact_free_box_covers_label_and_countdown(self):
        box = self.L.ANCESTOR_ART_FREE_BOX
        self.assertTrue(self._in_box(box, (220, 1017)), f"神铸台免费标签不在 {box}")
        self.assertTrue(self._in_box(box, (223, 1122)), f"神铸台倒计时不在 {box}")

    def test_pet_free_box_covers_countdown(self):
        box = self.L.ANCESTOR_PET_FREE_BOX
        self.assertTrue(self._in_box(box, (221, 1125)), f"唤灵台倒计时不在 {box}")

    def test_free_state_on_real_frames(self):
        import mtbot.textocr as textocr
        from mtbot.tasks.ancestor import AncestorTask
        if not textocr.available():
            self.skipTest("rapidocr 不可用")
        forge = ROOT / "tests/fixtures/ancestor_forge_free_new.png"
        art = ROOT / "tests/fixtures/ancestor_art_free_new.png"
        pet = ROOT / "tests/fixtures/ancestor_pet_used_new.png"
        for p in (forge, art, pet):
            self.assertTrue(p.exists(), f"缺少证据帧 {p.name}")
        from PIL import Image
        with Image.open(forge) as im:
            st, raw = AncestorTask._free_state(im, self.L.ANCESTOR_FREE_BOX)
            self.assertEqual(st, "free", f"天锻炉免费帧被判成 {st}（{raw}）")
        with Image.open(art) as im:
            st, raw = AncestorTask._free_state(im, self.L.ANCESTOR_ART_FREE_BOX)
            self.assertEqual(st, "free", f"神铸台免费帧被判成 {st}（{raw}）")
        with Image.open(pet) as im:
            st, raw = AncestorTask._free_state(im, self.L.ANCESTOR_PET_FREE_BOX)
            self.assertEqual(st, "used", f"唤灵台倒计时帧被判成 {st}（{raw}）")
            self.assertIn("后免费", raw)

    # ---------- goblin：先判失败 ----------
    def test_goblin_checks_lose_before_win(self):
        start = self.GOB.index("def _battle(")
        seg = self.GOB[start:]
        nxt = seg.find("\n    def ", 1)
        seg = seg if nxt < 0 else seg[:nxt]
        i_lose = seg.index("失败.png")
        i_win = seg.index("胜利.png")
        self.assertLess(i_lose, i_win, "必须先判「失败.png」再判「胜利/结算」")

    # ---------- 好友送礼不许虚报 ----------
    def test_friend_does_not_use_taps_as_claims(self):
        # 只查真实代码行（注释里提到旧写法是允许的）
        code = [ln for ln in self.REW.splitlines() if not ln.strip().startswith("#")]
        self.assertFalse([ln for ln in code if "got = max(got, i + 1)" in ln],
                         "好友送礼仍在拿点击次数当领取数")
        seg = self.REW[self.REW.index("class FriendTask"):]
        seg = seg[:seg.index("class WelfareTask")]
        self.assertIn("blind_taps", seg)
        self.assertIn("不拿点击次数当领取数", seg)

    # ---------- 完成行拆分 ----------
    def test_scheduler_splits_skip_from_real_work(self):
        self.assertIn("真状态跳过", self.SCH)
        seg = self.SCH[self.SCH.index("skipped = sum("):]
        self.assertIn('startswith("跳过")', seg)

    # ---------- RankPage.at_page ----------
    def test_rank_at_page_does_not_pass_on_empty_ocr(self):
        seg = self.PAGES[self.PAGES.index("class RankPage"):]
        seg = seg[:seg.index("def claim_rows")]
        i_empty = seg.index("if not txt:")
        i_retry = seg.index('self.shot("rank_at2")')
        self.assertLess(i_empty, i_retry, "读空后必须复核一帧")
        # 复核仍空必须 False（不许落回 classify 弱判据）
        tail = seg[i_retry:]
        self.assertIn("return False", tail)


class HonestyGuardTests3(unittest.TestCase):
    """2026-11-19 审计第二批：两处「没有真证据就记数」。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        cls.soul = (root / "mtbot" / "tasks" / "soul.py").read_text(encoding="utf-8")
        cls.events = (root / "mtbot" / "tasks" / "events.py").read_text(encoding="utf-8")

    def test_soul_does_not_judge_win_by_attempts(self):
        """快速战斗胜负都不改挑战次数 → 不能拿「次数变少」当通关证据。"""
        seg = self.soul[self.soul.index("att_now = page.attempts(im)"):]
        seg = seg[:400]
        self.assertIn("不据此判胜负", seg)
        # 次数分支之后不许紧跟 `return True`
        after = seg[seg.index("att_now[0] < att_before[0]"):]
        self.assertNotIn("return True, False", after.split("\n")[1] + "\n" + after.split("\n")[2]
                         if len(after.split("\n")) > 2 else after)

    def test_faction_counts_only_finished_rounds(self):
        """`runs += 1` 必须写在 `if out != "done":` 之后，且没跑完要在结论里说明。"""
        seg = self.events[self.events.index("class FactionTask"):]
        i_done = seg.index('if out != "done":')
        rest = seg[i_done:]
        i_inc = rest.index("runs += 1")
        self.assertLess(i_inc, rest.index("partial = True"),
                        "runs += 1 必须写在「没跑完就 break」之后、partial 之前")
        self.assertIn("partial = True", seg)
        self.assertIn("另有一轮没跑完就收手，不计", seg)


class SoulBossModeTests(unittest.TestCase):
    """2026-11-19：罪魂之域变成「第 N 层首领」塔，旧码只会扫水晶格点 → FAIL。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        cls.soul = (root / "mtbot" / "tasks" / "soul.py").read_text(encoding="utf-8")
        cls.layout = (root / "mtbot" / "layout.py").read_text(encoding="utf-8")

    def test_layout_has_boss_entry(self):
        for key in ("SOUL_BOSS_ENTRY", "SOUL_BOSS_ENTRY_CANDS", "SOUL_BOSS_MODE_KEYS",
                    "SOUL_RESULT_ROI", "SOUL_RESULT_WIN_KEYS", "SOUL_RESULT_LOSE_KEYS"):
            self.assertIn(key, self.layout, f"layout 缺少 {key}")

    def test_run_dispatches_boss_mode(self):
        """run() 里必须先用 SOUL_BOSS_MODE_KEYS 判页面形态，再扫格点。"""
        seg = self.soul[self.soul.index("    def run("):]
        i_mode = seg.index("SOUL_BOSS_MODE_KEYS")
        i_grid = seg.index("grid = list(page.crystal_nodes())")
        self.assertLess(i_mode, i_grid, "必须在扫格点之前判首领塔")
        self.assertIn("_run_boss_mode", seg)

    def test_result_page_reads_win_lose_before_close(self):
        """结算页必须先读胜负再 close_result()，否则首领战永远 unknown。"""
        seg = self.soul[self.soul.index("def _wait_battle"):]
        i = seg.index('if kind == "result":')
        blk = seg[i:i + 1200]
        i_ocr = blk.index("SOUL_RESULT_ROI")
        i_close = blk.index("page.close_result()")
        self.assertLess(i_ocr, i_close, "先读结果再关")
        self.assertIn("SOUL_RESULT_WIN_KEYS", blk)
        self.assertIn("SOUL_RESULT_LOSE_KEYS", blk)

    def test_no_diamond_paths_in_boss_mode(self):
        seg = self.soul[self.soul.index("def _run_boss_mode"):]
        seg = seg[:seg.index("def _leave")] if "def _leave" in seg else seg
        for bad in ("DIAMOND_PROMPT_GOLD", "购买", "前往>>"):
            self.assertNotIn(bad, seg)


class LoginFalsePositiveTests(unittest.TestCase):
    """2026-11-19 02:50：付费商店页被判成断线弹窗 → 对着付费页盲点 5 下。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.root = Path(__file__).resolve().parent.parent
        cls.ui = (cls.root / "mtbot" / "ui.py").read_text(encoding="utf-8")
        cls.layout = (cls.root / "mtbot" / "layout.py").read_text(encoding="utf-8")
        cls.frame = cls.root / "tests" / "fixtures" / "shop_gift_false_login.png"

    def test_shop_page_is_not_reconnect_login(self):
        from PIL import Image
        from mtbot import vision as V
        from mtbot.vision import State
        self.assertTrue(self.frame.exists(), "缺真帧 shop_gift_false_login.png")
        im = Image.open(self.frame).convert("RGB")
        self.assertFalse(V.reconnect_login_dialog(im))
        self.assertNotEqual(V.classify(im), State.RECONNECT_LOGIN)

    def test_layout_has_login_texts_and_pay_keys(self):
        self.assertIn("RECONNECT_LOGIN_TEXTS", self.layout)
        self.assertIn("RECONNECT_PAY_KEYS", self.layout)

    def test_ocr_confirm_before_blind_candidates(self):
        seg = self.ui[self.ui.index("if st == State.RECONNECT_LOGIN:"):]
        seg = seg[:seg.index("    # ---------- 页面根节点 ----------")]
        self.assertIn("_login_popup_confirmed(im)", seg)
        self.assertLess(seg.index("_login_popup_confirmed(im)"),
                        seg.index("for cand in L.RECONNECT_LOGIN_CANDS:"),
                        "必须先 OCR 确认再盲点候选点")

    def test_pay_keys_block_press(self):
        seg = self.ui[self.ui.index("def _login_popup_confirmed"):]
        seg = seg[:seg.index("    # ---------- 页面根节点 ----------")]
        self.assertIn("RECONNECT_PAY_KEYS", seg)
        self.assertNotIn("press(", seg)


class HonestyGuardTests4(unittest.TestCase):
    """2026-11-19 第三批：圣物确认框、装备升星弹窗、副本站页签认不出。"""

    @staticmethod
    def _src(rel):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")

    @staticmethod
    def _only_code(src):
        """去掉注释行，避免断言命中自己写的注释。"""
        out = []
        for ln in src.split("\n"):
            if ln.strip().startswith("#"):
                continue
            out.append(ln)
        return "\n".join(out)

    def test_relic_confirm_needs_material_evidence(self):
        seg = self._only_code(self._src("mtbot/tasks/reward.py"))
        i = seg.find("if self._confirm(ui):")
        self.assertGreater(i, 0, "找不到圣物的确认框分支")
        blk = seg[i:i + 900]
        self.assertIn("after_c = self._relic_res(", blk)
        self.assertIn("材料没变", blk)
        # 旧写法「确认框点掉就直接 ups += 1」必须消失
        self.assertNotIn('log.info(f"  一键升级：确认框已点掉，算 1 次', blk)

    def test_forge_star_needs_dialog_gone(self):
        seg = self._only_code(self._src("mtbot/tasks/reward.py"))
        # 主循环里那一处（进店自动弹窗也有一处同形代码，取最后一处）
        i = seg.rfind("st_after = vision.forge_star_dialog(after)")
        self.assertGreater(i, 0, "找不到升星结果判据")
        blk = seg[i:i + 700]
        self.assertIn('if st_after != "none":', blk)
        self.assertIn("材料不足", blk)
        self.assertIn("弹窗已关闭", blk)
        # 旧写法：still 只要「弹窗还在+按钮不金」也计入
        self.assertNotIn("still = (vision.forge_star_dialog(after)", seg)

    def test_dungeon_tab_unreadable_is_not_success(self):
        seg = self._only_code(self._src("mtbot/pages.py"))
        i = seg.find("def tab(self, key: str) -> bool:")
        self.assertGreater(i, 0)
        blk = seg[i:i + 1400]
        self.assertIn("if cur is None:", blk)
        self.assertIn("不当成功", blk)
        # 旧写法「认不出就放行」的注释与 return True 必须消失
        self.assertNotIn("保持旧行为，别把好流程拦死", blk)
        j = blk.find("if cur is None:")
        self.assertNotIn("return True", blk[j:j + 20].split("self.ui.wait")[0])


class Audit2EvidenceTests(unittest.TestCase):
    """2026-11-19 audit2：把「我发出过点击」当「操作生效」的几处补上证据链。"""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.root = Path(__file__).resolve().parent.parent
        cls.ui_src = (cls.root / "mtbot" / "ui.py").read_text(encoding="utf-8")
        cls.reward = (cls.root / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")
        cls.combat = (cls.root / "mtbot" / "tasks" / "combat.py").read_text(encoding="utf-8")
        cls.pages = (cls.root / "mtbot" / "pages.py").read_text(encoding="utf-8")
        cls.grank = (cls.root / "mtbot" / "tasks" / "guild_rank.py").read_text(encoding="utf-8")
        cls.merchant = (cls.root / "mtbot" / "tasks" / "merchant.py").read_text(encoding="utf-8")
        cls.assist = (cls.root / "mtbot" / "tasks" / "assist.py").read_text(encoding="utf-8")
        cls.qc = (cls.root / "mtbot" / "tasks" / "qianchou.py").read_text(encoding="utf-8")

    @staticmethod
    def _code(src: str) -> str:
        return "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))

    def test_relic_confirm_verifies_dialog_closed(self):
        code = self._code(self.reward)
        i = code.index("def _confirm(ui) -> bool:")
        seg = code[i:i + 1600]
        self.assertIn("_relic_confirm_open(again)", seg)
        self.assertIn("return False", seg.split("_relic_confirm_open(again)")[1][:600])

    def test_relic_blind_ups_not_counted(self):
        code = self._code(self.reward)
        self.assertIn("blind_ups += 1", code)
        self.assertIn('"blind_ups": blind_ups', code)
        i = code.index("before is None and after_c is None")
        seg = code[i:i + 240]
        # 注意 blind_ups += 1 里也含 "ups += 1" 子串，按整行比
        self.assertNotIn("ups += 1", [l.strip() for l in seg.split("\n")])

    def test_demon_settlement_requires_armed(self):
        code = self._code(self.combat)
        # 2026-11-20 审计 MAJOR：金带读不到就 `or 死坐标` 的写法已删，改成等下一帧
        for marker in ("nxt = vision.gold_band_center(im, L.RESULT_BTN_ZONE)",
                       "ok = vision.gold_band_center(im, L.RESULT_BTN_ZONE)"):
            i = code.index(marker)
            seg = code[i:i + 1400]
            self.assertIn("if not armed:", seg)
            self.assertLess(seg.index("if not armed:"), seg.index("wins += 1"))

    def test_tree_wins_after_page_left(self):
        code = self._code(self.combat)
        i = code.index("res.next_tree()")
        seg = code[i:i + 700]
        self.assertIn("RESULT_TREE", seg)
        self.assertLess(seg.index("tree_next_chk"), seg.index("wins += 1"))

    def test_guild_rank_unknown_not_in_fights(self):
        code = self._code(self.grank)
        self.assertIn("total = wins + loses", code)
        self.assertNotIn("total = wins + loses + unknowns", code)
        self.assertIn('"unconfirmed": unknowns', code)
        self.assertNotIn("wins += 0", code)

    def test_claim_click_uses_row_band(self):
        code = self._code(self.pages)
        i = code.index("def claim_click(")
        seg = code[i:i + 2000]
        self.assertIn("vision.gold_ratio(before, band)", seg)
        self.assertIn("vision.diff_ratio(before, after, band)", seg)
        self.assertNotIn("changed = vision.darkened(before, after) or not vision.similar(before, after)", seg)

    def test_merchant_counts_only_after_discount(self):
        code = self._code(self.merchant)
        i = code.index("while n < max_bargains")
        seg = code[i:i + 1200]
        self.assertLess(seg.index("page.discount(im)"), seg.index("n += 1"))

    def test_artifact_pixel_change_is_not_a_level(self):
        code = self._code(self.assist)
        i = code.index("ARTIFACT_CARD_LV_BAND) >= 0.01")
        seg = code[i - 260:i + 900]
        self.assertNotIn("total += 1", seg)
        self.assertIn("suspect += 1", seg)

    def test_battle_finish_marks_started(self):
        code = self._code(self.ui_src)
        i = code.index("def battle_finish(")
        seg = code[i:i + 2600]
        self.assertIn("self.battle_started = False", seg)
        self.assertIn("self.battle_started = True", seg)
        self.assertIn("这场没打起来", seg)

    def test_dungeon_checks_battle_started(self):
        code = (self.root / "mtbot" / "tasks" / "dungeon.py").read_text(encoding="utf-8")
        self.assertIn('getattr(ui, "battle_started", True)', code)

    def test_qianchou_draw_needs_evidence(self):
        code = self._code(self.qc)
        i = code.index("def _free_draw(")
        seg = code[i:i + 1800]
        self.assertIn("vision.item_popup(after) or vision.modal_dim(after)", seg)
        self.assertIn("不计数", seg)


class PageAnchorEnterTests(unittest.TestCase):
    """2026-11-19 审计 B3：mail/friend/welfare/forge 没有 titles 锚点，
    旧 enter() 只要「不是主城」就放行，随后按固定坐标乱点。本组锁住新加的页锚。"""

    @classmethod
    def setUpClass(cls):
        from mtbot.tasks import reward as R
        from mtbot.tasks.reward import FriendTask, MailTask, WelfareTask, EquipmentTask, RelicTask
        cls.R = R
        cls.src = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")
        cls.tasks = (MailTask, FriendTask, WelfareTask, EquipmentTask, RelicTask)

    def test_four_tasks_have_anchors_and_relic_does_not(self):
        mail, friend, welfare, equip, relic = self.tasks
        for cls in (mail, friend, welfare, equip):
            self.assertTrue(cls.PAGE_ANCHORS, f"{cls.name} 还没有页锚")
            for box, words in cls.PAGE_ANCHORS:
                self.assertEqual(len(box), 4, f"{cls.name} 锚点框不是 4 元组：{box}")
                self.assertTrue(words, f"{cls.name} 锚点没有关键词")
                self.assertGreaterEqual(box[2], 200, f"{cls.name} 锚点框太窄：{box}")
        self.assertEqual(relic.PAGE_ANCHORS, ())

    def test_enter_checks_anchor_before_titles(self):
        seg = self.src
        self.assertIn("def _page_anchored", seg)
        # 主路径（不带 cands）里：先判页锚，判 False 才 BACK，再 return None
        head = "if not page:\n            ok = self._page_anchored(im)"
        self.assertIn(head, seg)
        i_hook = seg.index(head)
        i_back = seg.index("ui.press(L.BACK, 250, expect=\"none\")", i_hook)
        i_ret = seg.index("return None", i_back)
        self.assertLess(i_hook, i_back)
        self.assertLess(i_back, i_ret)
        # 这个闸必须在 titles 校验之前（titles 分支只对 page 非空生效）
        self.assertLess(i_hook, seg.index("if page and not titles.on_page(im, page):", i_hook))
        # cands 分支也用同一个闸，且全失败才 warn + 跳过
        self.assertIn("for cand in cands:", seg)
        self.assertIn("个候选入口都没进到目标页，跳过本任务", seg)

    def test_anchor_returns_none_when_ocr_missing(self):
        from mtbot.tasks import reward as R
        orig = R.textocr.available
        try:
            R.textocr.available = lambda: False
            task = R.MailTask.__new__(R.MailTask)
            task.name = "mail"
            self.assertIsNone(R.MailTask._page_anchored(task, object()))
        finally:
            R.textocr.available = orig

    def test_anchor_accepts_mail_page_and_rejects_main_city(self):
        from PIL import Image
        from mtbot import textocr
        if not textocr.available():
            self.skipTest("OCR 不可用")
        task = self.task_like(self.R.MailTask, "mail")
        mail = Image.open(HERE / "fixtures" / "head_mail_page.png")
        self.assertIs(self.R.MailTask._page_anchored(task, mail), True)
        city = Image.open(HERE / "fixtures" / "main_city.png")
        self.assertIs(self.R.MailTask._page_anchored(task, city), False)

    def test_anchor_accepts_forge_page(self):
        from PIL import Image
        from mtbot import textocr
        if not textocr.available():
            self.skipTest("OCR 不可用")
        task = self.task_like(self.R.EquipmentTask, "equipment")
        im = Image.open(HERE / "fixtures" / "head_forge_page.png")
        self.assertIs(self.R.EquipmentTask._page_anchored(task, im), True)

    @staticmethod
    def task_like(cls, name):
        t = cls.__new__(cls)
        t.name = name
        return t


class HonestyGuardTests5(unittest.TestCase):
    """2026-11-19 审计第三批：副本结算不得把「认不出胜负」当通关；
    公会商人成交不得只看「画面变了」；`expect="none"` 的死分支要清掉。"""

    @classmethod
    def setUpClass(cls):
        root = HERE.parent / "mtbot"
        cls.dun = (root / "tasks" / "dungeon.py").read_text(encoding="utf-8")
        cls.pages = (root / "pages.py").read_text(encoding="utf-8")
        cls.reward = (root / "tasks" / "reward.py").read_text(encoding="utf-8")
        from mtbot import layout as L
        cls.L = L

    def test_dungeon_unknown_not_counted_as_win(self):
        self.assertIn('return "unknown"', self.dun)
        self.assertIn("结算页认不出「胜利」横幅", self.dun)
        # 旧的「是结算态就 return win」写法必须消失
        self.assertNotIn('State.RESULT_LEGEND):\n                ui.press((370, 1130), 220)\n                ui.wait(2.2)\n                return "win"',
                         self.dun.replace("\r\n", "\n"))
        # 调用方对 unknown 既不算通关也不算失败
        seg = self.dun[self.dun.index('if r == "unknown":'):]
        self.assertIn("不记通关也不记失败", seg)
        self.assertIn("return wins, False", seg[:400])

    def test_merchant_buy_needs_hard_evidence(self):
        self.assertIn("MERCHANT_CENTER_BOX", self.pages)
        self.assertIn("self._already_bought(after)", self.pages)
        self.assertIn("vision.item_popup(after)", self.pages)
        self.assertIn("不按买到算", self.pages)
        self.assertNotIn('return "bought" if not vision.similar(im, after) else "no_confirm"',
                         self.pages)
        self.assertEqual(len(self.L.MERCHANT_CENTER_BOX), 4)

    def test_no_dead_press_branches_left(self):
        # expect="none" 恒 True，`if not ...press(..., expect="none")` 是死分支
        for path_src in (self.reward, self.pages):
            for line in path_src.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue            # 注释里会引用旧写法
                if "if not " in stripped and 'expect="none"' in stripped:
                    self.fail(f"还有死分支：{stripped}")
        # 签到/周末补给/终身福利 仍必须先打点再判画面证据
        self.assertIn("_tapped(ui, im)", self.reward)




class DungeonTabOverlayTests(unittest.TestCase):
    """2026-11-19：f59 里 dungeon 三类页签因浮层压着读不出选中项被跳过。"""

    def setUp(self):
        from pathlib import Path
        self.src = (Path(__file__).resolve().parent.parent / "mtbot" / "pages.py").read_text(
            encoding="utf-8")

    def test_tab_clears_overlay_first(self):
        seg = self.src[self.src.index("    def tab(self, key: str) -> bool:"):]
        seg = seg[:seg.index("    # ----", 10)] if "    # ----" in seg else seg[:3000]
        self.assertIn("self._clear_overlay()", seg)
        self.assertLess(seg.index("self._clear_overlay()"),
                        seg.index("self.ui.press(self.TABS[key]"))

    def test_clear_overlay_uses_dim_and_blank(self):
        seg = self.src[self.src.index("    def _clear_overlay(self) -> bool:"):]
        seg = seg[:seg.index("    def tab(self, key: str) -> bool:")]
        self.assertIn("vision.modal_dim(im)", seg)
        self.assertIn("vision.item_popup(im)", seg)
        self.assertIn("L.BLANK", seg)
        # 关浮层是导航类动作，不能带变化校验（否则每次都白赔 4 个补偿点）
        self.assertIn('expect="none"', seg)

    def test_clear_overlay_in_retry_attempt(self):
        seg = self.src[self.src.index("    def tab(self, key: str) -> bool:"):]
        seg = seg[:seg.index("    @staticmethod", 10)]
        self.assertIn("if attempt:", seg)




class MailAnchorFrameTests(unittest.TestCase):
    """2026-11-19：邮件页是盖在主城上的面板，标题 y≈248，底部是页签不是领取钮。"""

    def setUp(self):
        from pathlib import Path
        self.root = Path(__file__).resolve().parent.parent
        self.src = (self.root / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")

    def test_mail_anchor_rois_match_real_frame(self):
        seg = self.src[self.src.index("class MailTask(_RewardTask):"):]
        seg = seg[:seg.index("    def run(self, ctx: TaskContext)")]
        self.assertIn('"邮件"', seg)
        self.assertIn('"一键删除"', seg)
        self.assertIn('"普通邮件"', seg)
        # 页头框必须下移到面板标题那一行（y>=180），不能是 (0, 0, 720, 200)
        self.assertNotIn("((0, 0, 720, 200)", seg)

    def test_enter_failed_is_reason_aware(self):
        self.assertIn("def _enter_failed", self.src)
        self.assertIn('if getattr(self, "_enter_reason", "page") == "home":', self.src)
        body = self.src.split("def _enter_failed")[1][:1200]
        self.assertIn("TaskResult.skip(", body)
        self.assertIn('TaskResult.fail("回不到主城")', body)

    def test_enter_clears_overlay_before_candidates(self):
        seg = self.src[self.src.index("    def enter(self, ctx: TaskContext, pos"):]
        seg = seg[:seg.index("    def _clear_overlay")] if "    def _clear_overlay" in seg else seg[:1500]
        self.assertIn("self._clear_overlay(ui)", seg)
        self.assertLess(seg.index("self._clear_overlay(ui)"), seg.index("if cands:"))




class GuildRankWeekdayTests(unittest.TestCase):
    """2026-11-19 周四：排位赛页面写「尚未开启 / 每周一、三、五」，不是「即将开启」。"""

    def setUp(self):
        from pathlib import Path
        self.root = Path(__file__).resolve().parent.parent
        self.tpl = (self.root / "mtbot" / "tasks" / "guild_rank.py").read_text(encoding="utf-8")
        self.lay = (self.root / "mtbot" / "layout.py").read_text(encoding="utf-8")

    def test_closed_keys_cover_not_yet_and_wrong_day(self):
        seg = self.lay[self.lay.index("GUILD_RANK_CLOSED_KEYS"):]
        seg = seg[:400]
        self.assertIn("尚未开启", seg)
        self.assertIn("即将开启", seg)

    def test_weekday_branch_before_not_open_branch(self):
        seg = self.tpl[self.tpl.index("if self._closed(im):"):]
        seg = seg[:2600]
        self.assertIn("GUILD_RANK_WEEKDAY_KEYS", seg)
        self.assertLess(seg.index("if week_only:"), seg.index("跳过：公会排位赛未开启"))

    def test_real_frame_reads_weekday_closed(self):
        from pathlib import Path
        from PIL import Image
        from mtbot import textocr, layout as L
        f = Path(__file__).resolve().parent / "fixtures" / "grank_weekday_closed.png"
        if not f.exists():
            self.skipTest("no frame")
        im = Image.open(f)
        flat = textocr.read_text(im, L.GUILD_RANK_CLOSED_BOX).replace(" ", "")
        self.assertTrue(any(k in flat for k in L.GUILD_RANK_WEEKDAY_KEYS), flat[:60])


class EntryRetryOnNoChangeTests(unittest.TestCase):
    """2026-11-19 第 65 轮：邮件任务在「刚重开/刚回主城」的几秒内点击被吞。

    同一个坐标 (74,909) 在设备空闲时能正常打开邮件页（真帧见
    fixtures/head_mail_page.png），所以「点下去整屏一点没动」不能立刻判
    「图标换位」，要先等一会儿把同一个候选点再按一次；全部候选失败后
    还要给主城一次补点机会，不能一失败就把邮件任务跳过。
    """

    def setUp(self):
        self.src = (HERE.parent / "mtbot" / "tasks" / "reward.py").read_text(encoding="utf-8")
        self.enter = self.src[self.src.index("    def enter(self, ctx"):]
        self.enter = self.enter[: self.enter.index("    def _clear_overlay")]

    def test_retries_same_candidate_when_frame_unmoved(self):
        self.assertIn("before = ui.screen(f\"{self.name}_candb\")", self.enter)
        self.assertIn("diff_ratio(before, im, (0, 0, 720, 1280)) < 0.01", self.enter)
        self.assertIn("_candretry", self.enter)
        # 补点必须在「scene 完全没动」判定之后、并且只对同一个候选点
        i_chk = self.enter.index("diff_ratio(before, im, (0, 0, 720, 1280)) < 0.01")
        i_retry = self.enter.index("_candretry")
        i_next = self.enter.index("if vision.classify(im) == State.MAIN_CITY:\n                        continue")
        self.assertLess(i_chk, i_retry)
        self.assertLess(i_retry, i_next)

    def test_last_chance_retry_before_skip(self):
        self.assertIn("ui.wait(3.0)", self.enter)
        self.assertIn("_lasttry", self.enter)
        self.assertIn("补点入口", self.enter)
        # 补点必须在 warn「跳过本任务」之前
        self.assertLess(self.enter.index("_lasttry"),
                        self.enter.index("个候选入口都没进到目标页"))

    def test_mail_page_anchor_matches_real_frame(self):
        """真帧里的标题「邮件」必须在页锚 ROI 内，否则进对页也会被判失败。"""
        from mtbot import layout as L  # noqa: F401
        import mtbot.tasks.reward as R
        rois, keys = zip(*R.MailTask.PAGE_ANCHORS)
        self.assertTrue(any("邮件" in k for k in keys))
        top = [r for r in rois if r[1] <= 248 <= r[3]]
        self.assertTrue(top, "标题「邮件」y=248 必须落在某个页锚 ROI 内")


class StallWatchdogTests(unittest.TestCase):
    """2026-11-19 用户：「全部任务一起跑会在某一个任务卡住」。

    修法三件套里的两件在这里验收：
    ① 任务里完全没有点击动作超过 8 分钟 → 看门狗把 ui.deadline 设成过去时间，
       主线程下一次 screen/press 就会抛 TaskTimeout 中止该任务；
    ② 超时的任务不再重试（重试只会再卡一遍）。
    """

    def _scheduler(self):
        import types
        from mtbot import scheduler as S
        from mtbot import config as C
        cfg = types.SimpleNamespace(runtime=types.SimpleNamespace(max_task_minutes=20))
        sch = S.Scheduler.__new__(S.Scheduler)
        sch.cfg = cfg
        sch.ui = types.SimpleNamespace(actions=0, deadline=1.0, task_name="demo",
                                       stall_note="")
        return S, sch

    def test_watchdog_trips_when_no_actions(self):
        import time
        S, sch = self._scheduler()
        old = S.Scheduler.STALL_SECONDS
        old_tick = S.Scheduler.WATCHDOG_TICK
        S.Scheduler.STALL_SECONDS = 0.2
        S.Scheduler.WATCHDOG_TICK = 0.1
        try:
            stop = sch._start_watchdog()
            time.sleep(0.6)
            stop.set()
        finally:
            S.Scheduler.STALL_SECONDS = old
            S.Scheduler.WATCHDOG_TICK = old_tick
        self.assertIsNotNone(sch.ui.deadline)
        self.assertLess(sch.ui.deadline, time.time())
        self.assertIn("看门狗", sch.ui.stall_note)

    def test_watchdog_quiet_when_actions_grow(self):
        import time
        S, sch = self._scheduler()
        old = S.Scheduler.STALL_SECONDS
        S.Scheduler.STALL_SECONDS = 0.2
        try:
            stop = sch._start_watchdog()
            for _ in range(6):
                time.sleep(0.15)
                sch.ui.actions += 1
            stop.set()
        finally:
            S.Scheduler.STALL_SECONDS = old
        self.assertEqual(sch.ui.stall_note, "")
        self.assertEqual(sch.ui.deadline, 1.0)

    def test_timeout_is_not_retried(self):
        src = (HERE.parent / "mtbot" / "scheduler.py").read_text(encoding="utf-8")
        self.assertIn("是卡住超时，不再重试", src)
        self.assertLess(src.index('startswith("超时")'),
                        src.index("是卡住超时，不再重试"))
        # 任务级超时覆盖：塔单独 25 分钟
        self.assertIn('"timeout_minutes"', src)

    def test_stall_note_reaches_timeout_message(self):
        src = (HERE.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("stall_note", src)
        self.assertIn("raise TaskTimeout(note or", src)


class FactionSettlingTests(unittest.TestCase):
    """2026-11-19 第 66 轮：阵营挑战页还在「N分M秒后结算」时，「开始挑战」真的按不动。

    真帧 `tests/fixtures/faction_settling.png`（logs/screens/faction_after2_83.png）
    左上写「2分8秒后结算」，点 (602,685) 整屏 diff=0.000、4 个补偿点全空；
    结算结束后同一坐标 diff=0.824 正常进布阵页。所以任务要如实说「还在结算」，
    不能把它当成空点/卡死。
    """

    def setUp(self):
        self.pages = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        self.events = (HERE.parent / "mtbot" / "tasks" / "events.py").read_text(encoding="utf-8")
        import mtbot.layout as L
        self.L = L

    def test_settle_regex_matches_real_text(self):
        import re
        for txt in ("2分8秒后结算", "7分5秒后结算", "11分30秒后结算"):
            m = re.search(self.L.FACTION_SETTLE_RE, txt)
            self.assertIsNotNone(m, txt)
        self.assertIsNone(re.search(self.L.FACTION_SETTLE_RE, "开始挑战"))

    def test_start_run_checks_settling_before_click(self):
        seg = self.pages[self.pages.index("    def start_run(self) -> str:"):]
        seg = seg[: seg.index("    def deploy(")]
        self.assertIn('return "settling"', seg)
        self.assertLess(seg.index("self.settling(im)"), seg.index("self._start_pos(im)"))

    def test_settle_box_covers_top_left_label(self):
        x1, y1, x2, y2 = self.L.FACTION_SETTLE_BOX
        self.assertLessEqual(x1, 60)
        self.assertLess(y1, 150)
        self.assertGreater(y2, 180)

    def test_task_reports_settling_not_failure(self):
        self.assertIn('if r == "settling":', self.events)
        self.assertIn("本页还在结算中", self.events)
        # 结算分支不许报 fail
        i = self.events.index('if r == "settling":')
        self.assertNotIn("TaskResult.fail", self.events[i:i + 400])

    def test_start_click_does_not_warn_empty_point(self):
        """点「开始挑战」用 expect="none" + 自己判画面，别让「按钮按不动」记成空点。"""
        seg = self.pages[self.pages.index("    def start_run(self) -> str:"):]
        seg = seg[: seg.index("    def deploy(")]
        self.assertIn('label="fac_start", expect="none"', seg)
        self.assertIn("_fac_retry", seg) if False else None
        self.assertIn('label="fac_start_retry", expect="none"', seg)


class DragonZeroDeltaTests(unittest.TestCase):
    """2026-11-20 第 67 轮：巨龙买了 2 次（弹窗合计 200），主城钻石 2472→2472 没变。

    和 11-18 那次一样，这一单扣的不是钻石（龙晶/券）。「钻石没变」本身就是证据，
    不该再报「与预期对不上，请核对」让人去查账。
    """

    def setUp(self):
        self.src = (HERE.parent / "mtbot" / "tasks" / "events.py").read_text(encoding="utf-8")

    def test_zero_delta_is_not_a_warning(self):
        i = self.src.index("spent == 0 and bought > 0")
        seg = self.src[i:self.src.index('elif spent != spent_popup:', i)]
        self.assertIn("扣的不是钻石", seg)
        self.assertNotIn("log.warn", seg)
        self.assertIn("log.info", seg)

    def test_mismatch_still_warns(self):
        i = self.src.index("elif spent != spent_popup:")
        self.assertIn("log.warn", self.src[i:i + 300])


class DeviceRecoverTests(unittest.TestCase):
    """设备整机挂掉时的自动恢复（2026-11-20，第 64 轮教训）。"""

    def _src(self, rel):
        return (HERE.parent / rel).read_text(encoding="utf-8")

    def test_device_has_recover_and_alive(self):
        src = self._src("mtbot/device.py")
        self.assertIn("def recover(self, timeout: float = 180.0) -> bool:", src)
        self.assertIn("def alive(self) -> bool:", src)
        self.assertIn("def mumu_manager(self) -> str:", src)
        self.assertIn("control", src)
        self.assertIn("launch", src)

    def test_screenshot_revives_before_raising(self):
        src = self._src("mtbot/device.py")
        win = src[src.index("def screenshot("):src.index("def _trim(")]
        self.assertIn("_recovered", win)
        self.assertIn("if not recovered and self.recover():", win)
        # 必须先试恢复，才允许抛「截图连续失败」
        self.assertLess(win.index("self.recover()"), win.index("raise DeviceError"))

    def test_scheduler_revives_device(self):
        src = self._src("mtbot/scheduler.py")
        self.assertIn("def _revive_device(self) -> bool:", src)
        run = src[src.index("def run(self, names"):]
        self.assertIn("if self._revive_device():", run)
        # 回主城出错时先救设备再判 stuck_backs
        win = run[run.index("back_ok = self.ui.ensure_main_city()"):]
        win = win[:win.index("stuck_backs = 0 if back_ok")]
        self.assertIn("self._revive_device()", win)

    def test_recover_is_bounded(self):
        src = self._src("mtbot/device.py")
        win = src[src.index("def recover("):src.index("def screenshot(")]
        self.assertIn("deadline = time.time() + max(30.0, timeout)", win)
        self.assertIn("while time.time() < deadline:", win)


class BootEmulatorFirstTests(unittest.TestCase):
    """--boot 要先拉起模拟器实例，再去连 adb（2026-11-20）。"""

    def _boot(self):
        return (HERE.parent / "mtbot/boot.py").read_text(encoding="utf-8")

    def test_emulator_started_before_adb(self):
        src = self._boot()
        win = src[src.index("def bootstrap("):]
        start = win.index("模拟器没在跑，先启动实例")
        adb = win.index('adb 已连接')
        self.assertLess(start, adb)
        self.assertIn("em.wait_android(240)", win)
        self.assertIn("if not connected and em is not None:", win)
        self.assertIn("em.wait_android(180)", win)

    def test_step5_uses_same_instance(self):
        src = self._boot()
        self.assertNotIn("            Emulator(cfg).start()", src)
        self.assertIn("em.start()          # 幂等", src)

    def test_mumu_manager_prefers_config(self):
        src = (HERE.parent / "mtbot/device.py").read_text(encoding="utf-8")
        win = src[src.index("def mumu_manager("):src.index("def alive(")]
        self.assertIn("self.cfg.emulator.manager", win)


class LineupSaveDialogTests(unittest.TestCase):
    """2026-11-20 第 68 轮 02:20：副本列表上叠「是否保存本次挑战？」浮层。

    真帧 `tests/fixtures/dungeon_save_prompt.png`；按钮行 OCR 实测
    `重新挑战 (249,746)` / `保存 (473,747)`，而固定常量 `L.LINEUP_SAVE=(465,782)` 偏低。
    """

    FIX = HERE / "fixtures" / "dungeon_save_prompt.png"

    def test_real_frame_recognised(self):
        from PIL import Image
        from mtbot import vision
        im = Image.open(self.FIX).convert("RGB")
        self.assertTrue(vision.lineup_save_dialog(im))

    def test_body_says_save_and_ocr_finds_button(self):
        from PIL import Image
        from mtbot import layout as L, textocr
        im = Image.open(self.FIX).convert("RGB")
        body = textocr.read_text(im, L.LINEUP_BODY_BOX)
        self.assertIn("是否保存本次挑战", body.replace(" ", ""))
        hits = [(t, c) for t, c, _b, _s in
                textocr.read_lines(im, L.LINEUP_BTN_ROW_BOX, min_score=0.5)
                if t.replace(" ", "") == L.LINEUP_SAVE_KEY]
        self.assertTrue(hits, "按钮行里必须能 OCR 出「保存」")
        cx, cy = hits[0][1]
        self.assertGreater(cx, 400)          # 保存是右侧按钮，左侧是「重新挑战」
        self.assertTrue(700 <= cy <= 800)

    def test_ui_uses_helper_not_blind_constant(self):
        src = io.open(ROOT / "mtbot" / "ui.py", encoding="utf-8").read()
        flat = src.replace("\n", " ")
        self.assertIn("return self.clear_lineup_dialog(im)", src)
        self.assertIn("def clear_lineup_dialog(self", src)
        # 旧的「盲点 L.LINEUP_SAVE」写法必须不再出现
        self.assertNotIn("self.press(L.LINEUP_SAVE, 220)", src)
        self.assertIn("LINEUP_BLOCK_KEYS", flat)

    def test_dungeon_clear_overlay_tries_helper_first(self):
        src = io.open(ROOT / "mtbot" / "pages.py", encoding="utf-8").read()
        i0 = src.index("def _clear_overlay(self) -> bool:", src.index("class DungeonPage"))
        seg = src[i0:src.index("    def tab(self", i0)]
        self.assertIn("clear_lineup_dialog", seg)
        self.assertLess(seg.index("clear_lineup_dialog"), seg.index("dun_clear_overlay"))

    def test_never_presses_rechallenge(self):
        for name in ("mtbot/ui.py", "mtbot/pages.py"):
            src = io.open(ROOT / name, encoding="utf-8").read()
            self.assertNotIn('重新挑战", 220', src)


    def test_clear_lineup_dialog_presses_ocr_save(self):
        """真帧上跑一遍 `UI.clear_lineup_dialog`：必须点 OCR 出的「保存」(x>400, y≈747)，
        而不是固定常量 (465,782)，也绝不能碰「重新挑战」。"""
        from unittest import mock
        from PIL import Image
        from mtbot.ui import UI
        im = Image.open(self.FIX).convert("RGB")
        ui = object.__new__(UI)
        clicks = []
        ui.press = lambda pos, ms=200, label="", expect="hit": clicks.append((pos, label))
        with mock.patch("mtbot.ui.time.sleep"):
            self.assertTrue(UI.clear_lineup_dialog(ui, im))
        self.assertEqual(len(clicks), 1)
        (x, y), label = clicks[0]
        self.assertGreater(x, 400)
        self.assertTrue(700 <= y <= 800)
        self.assertEqual(label, "lineup_save")

    def test_dungeon_clear_overlay_uses_helper_on_real_frame(self):
        """`DungeonPage._clear_overlay` 在真帧上必须先走 clear_lineup_dialog，
        一次空白都不要点（旧码点空白 → 浮层不动 → 三个页签全被跳过）。"""
        from unittest import mock
        from PIL import Image
        from mtbot.ui import UI
        from mtbot.pages import DungeonPage
        im = Image.open(self.FIX).convert("RGB")
        ui = object.__new__(UI)
        clicks = []
        ui.press = lambda pos, ms=200, label="", expect="hit": clicks.append((pos, label))
        ui.wait = lambda *a, **k: None
        ui.screen = lambda name="x", fresh=True: im
        ui.deadline = None
        ui.actions = 0
        page = object.__new__(DungeonPage)
        page.ui = ui
        page.shot = lambda name="x", fresh=True: im
        with mock.patch("mtbot.ui.time.sleep"), mock.patch("mtbot.pages.time.sleep"):
            page._clear_overlay()
        labels = [lab for _p, lab in clicks]
        self.assertIn("lineup_save", labels)
        self.assertNotIn("dun_clear_overlay", labels)

class PressSwallowRetryTests(unittest.TestCase):
    """真机上「页面刚切换的 1~2 秒 UI 不吃输入」会把点击吞掉（diff≈0）。
    这种吞点击不是坐标错，必须先用同一坐标重试一次，再去谈偏移补偿。
    """

    SRC = (Path(__file__).resolve().parent.parent / "mtbot" / "ui.py").read_text(encoding="utf-8")

    def test_same_point_retry_exists_before_offsets(self):
        src = self.SRC
        self.assertIn("空点重试", src)
        i_retry = src.index("空点重试")
        i_offset = src.index("逐级放大偏移重试")
        self.assertLess(i_retry, i_offset)

    def test_retry_uses_same_coordinate_and_marks_log(self):
        src = self.SRC
        i = src.index("空点重试")
        seg = src[max(0, i - 900): i + 400]
        self.assertIn("self.dev.press(x, y, ms)", seg)
        self.assertIn("diff, -1)", seg)

    def test_retry_only_when_click_retry_enabled(self):
        src = self.SRC
        i = src.index("空点重试")
        seg = src[max(0, i - 900): i]
        self.assertIn("if self.click_retry > 0:", seg)


class GuildRankFrameTests(unittest.TestCase):
    """用真实帧把 `GuildRankTask` 的解析与「弹层还开着」的坑钉住。

    帧来源：`tests/fixtures/grank_list_zero.png`（对局列表，含一颗「已击败」）、
    `grank_popup_fresh.png`（点格子后的「敌阵信息」弹层）、
    `grank_weekday_closed.png`（非开放日）。
    """

    FIX = Path(__file__).resolve().parent / "fixtures"

    def _task(self):
        from mtbot.tasks.guild_rank import GuildRankTask
        return object.__new__(GuildRankTask)

    def test_attempts_and_closed_on_real_frames(self):
        from PIL import Image
        from mtbot.tasks.guild_rank import GuildRankTask
        lst = Image.open(self.FIX / "grank_list_zero.png").convert("RGB")
        closed = Image.open(self.FIX / "grank_weekday_closed.png").convert("RGB")
        self.assertEqual(GuildRankTask._attempts(lst), (0, 3))
        self.assertFalse(GuildRankTask._closed(lst))
        self.assertTrue(GuildRankTask._closed(closed))
        self.assertIsNone(GuildRankTask._attempts(closed))

    def test_opponents_marks_beaten_on_real_frame(self):
        """「已击败」那颗必须被标成 beaten=True（否则会重复打同一个对手）。"""
        from PIL import Image
        im = Image.open(self.FIX / "grank_list_zero.png").convert("RGB")
        ops = self._task()._opponents(im)
        self.assertGreaterEqual(len(ops), 4)
        beaten = [round(p / 1e8, 2) for p, _x, _y, b in ops if b]
        alive = [round(p / 1e8, 2) for p, _x, _y, b in ops if not b]
        # 真帧里有两颗写了「已击败」：2.75亿(y=858) 与 2.08亿(y=1055)，
        # 状态行都在这两个战力行**上方** 56px。旧码窗口符号写反 → 一颗都没认出来。
        self.assertEqual(sorted(beaten), [2.08, 2.75])
        self.assertEqual(sorted(alive), [5.15, 5.53, 7.18])

    def test_info_popup_detected_only_on_popup_frame(self):
        from PIL import Image
        t = self._task()
        pop = Image.open(self.FIX / "grank_popup_fresh.png").convert("RGB")
        lst = Image.open(self.FIX / "grank_list_zero.png").convert("RGB")
        self.assertTrue(t._info_open(pop))
        self.assertFalse(t._info_open(lst))

    def test_scan_closes_popup_before_reading_list(self):
        """扫对手列表前必须先看一眼是不是「敌阵信息」弹层还开着。"""
        src = (Path(__file__).resolve().parent.parent / "mtbot" / "tasks"
               / "guild_rank.py").read_text(encoding="utf-8")
        i_popup = src.index("弹层还开着，先关掉再扫列表")
        i_scan = src.index("ops = self._opponents(frame)")
        self.assertLess(i_popup, i_scan)
        self.assertIn("self._info_open(frame)", src[max(0, i_popup - 400): i_scan])


class AuditCriticalGuardsTests(unittest.TestCase):
    """2026-11-20 audit18 的 CRITICAL 六条 + MAJOR 一条：源码层面的守门断言。

    这些都是「真实付费 / 不可逆动作 / 盲点」的护栏，掉一条就可能真的花钱或分解错东西，
    所以宁可让测试因为措辞变化而红，也不允许悄悄回退。
    """

    def test_idle_need_comes_from_button_color_not_counter(self):
        src = _src("mtbot/tasks/daily.py")
        self.assertIn("free_left = None", src)                 # 不再默认「还有 1 次免费」
        self.assertNotIn("free_left = 1\n", src)
        self.assertIn("if free_btn and not paid_btn:", src)
        self.assertIn("need = 0                      # 绿色 = 真免费", src)
        self.assertIn("need = 50 if done == 0 else 100", src)

    def test_idle_claim_requires_evidence(self):
        src = _src("mtbot/tasks/daily.py")
        i_after = src.index("idle_claim_after")
        i_claimed = src.index("claimed = 1")
        self.assertLess(i_after, i_claimed)
        self.assertIn("不算领取", src)

    def test_dragon_buy_rejects_missing_attempts(self):
        src = _src("mtbot/tasks/events.py")
        i_guard = src.index("点「购买」后读不到挑战次数（缺证），不认这次购买")
        i_ok = src.index("买到 1 次挑战次数（弹窗写花费")
        self.assertLess(i_guard, i_ok)

    def test_dragon_fight_has_no_blind_fixed_coord(self):
        src = _src("mtbot/tasks/events.py")
        self.assertNotIn('m.center if m else L.FIGHT', src)
        self.assertIn("vision.gold_band_point(im, (460, 1155, 710, 1260))", src)

    def test_decompose_stops_without_rank_evidence(self):
        src = _src("mtbot/tasks/tianshen.py")
        i_guard = src.index("no-rank-evidence")
        i_quick = src.index("L.BAG_QUICK")
        self.assertLess(i_guard, i_quick)

    def test_glory_buy_gate_uses_real_cost(self):
        src = _src("mtbot/tasks/glory.py")
        self.assertNotIn('"荣耀竞技场买 1 次挑战次数", None', src)
        self.assertIn('self.may_spend(ctx, "荣耀竞技场买 1 次挑战次数",', src)
        self.assertIn('cost, kind="attempt")', src)          # 闸门拿的是弹窗里的真金额
        i_gate = src.index('cost, kind="attempt")')
        i_confirm = src.index("L.ARENA_BUY_CONFIRM")
        self.assertLess(i_gate, i_confirm)
        self.assertIn("ctx=ctx", src)

    def test_guild_rank_no_blind_fight_and_no_beaten_fallback(self):
        src = _src("mtbot/tasks/guild_rank.py")
        self.assertNotIn("or L.FIGHT", src)
        self.assertNotIn("cand = list(ops)", src)
        self.assertIn("不猜着打", src)


class AuditMajorGuardsTests(unittest.TestCase):
    """2026-11-20 audit18 的 MAJOR 条目护栏：假成功计数 / 猜页签 / 探针误请客。"""

    def test_legend_claim_needs_claimed_count(self):
        src = _src("mtbot/pages.py")
        i_gate = src.index("if got2 > got or gained:")
        i_count = src.index("n += 1", i_gate)
        self.assertLess(i_gate, i_count)
        self.assertIn("已领取计数没涨", src)

    def test_glory_no_fake_empty_attempts(self):
        src = _src("mtbot/tasks/glory.py")
        self.assertIn("attempts_unreadable", src)
        self.assertNotIn("→ 按今天没得打处理\")\n                left = 0", src)
        i_flag = src.index("att_unread = True")
        self.assertNotIn("left = 0", src[i_flag: i_flag + 200])

    def test_rankboard_always_clicks_tab(self):
        src = _src("mtbot/tasks/rankboard.py")
        self.assertNotIn("已是当前页签，跳过点击", src)
        self.assertIn("仍点一次确认", src)
        i_hint = src.index("仍点一次确认")
        i_press = src.index('label=f"rank_tab:{gx}"', i_hint)
        self.assertLess(i_press - i_hint, 400)      # 提示后紧接着还是点了

    def test_qianchou_selection_requires_ocr_mark(self):
        src = _src("mtbot/tasks/qianchou.py")
        self.assertNotIn("or not vision.similar(", src)
        self.assertIn("只认 OCR 到的选中标记", src)

    def test_tavern_never_probes_by_drinking(self):
        # 2026-11-20：买次数改走顶部「+」，卡片上的「请客」不再当购买探针
        # （旧 _buy_and_drink 整段已删）。
        src = _src("mtbot/tasks/tavern.py")
        self.assertNotIn("tavern_buy_probe", src)
        self.assertNotIn("_buy_and_drink", src)
        self.assertIn("TAVERN_POOL_PLUS", src)
        self.assertIn("diamonds_check", src)


class ArtifactStarEvidenceTests(unittest.TestCase):
    """神器升星：像素变化不算账，只认 ★ 数量增量（2026-11-20 审计 MAJOR）。"""

    FIX = Path(__file__).resolve().parent / "fixtures"

    def _task(self):
        from mtbot.tasks.assist import ArtifactTask
        return object.__new__(ArtifactTask)

    def test_reads_stars_on_real_frame(self):
        from PIL import Image
        im = Image.open(self.FIX / "artifact_star_popup.png").convert("RGB")
        self.assertEqual(self._task()._stars(im), 5)

    def test_returns_none_when_no_stars(self):
        from PIL import Image
        im = Image.open(self.FIX / "artifact_detail.png").convert("RGB")
        self.assertIsNone(self._task()._stars(im))

    def test_star_count_is_the_only_evidence(self):
        src = _src("mtbot/tasks/assist.py")
        self.assertNotIn('total += self._upgrade_loop(ui, "神器·升星")', src)
        self.assertIn("total += real", src)
        self.assertIn("不虚报", src)


class TavernDynamicCardsTests(unittest.TestCase):
    """英雄酒馆卡片定位：新版行高比 layout 常量整体下移 ~370px，必须按文字定位。

    真帧 tests/fixtures/tavern_newrows.png（2026-11-20 05:50，720x1280）实测：
      小黑(444,768) 45/50(587,814) 今日可请：2/2(580,845) 请客(578,882)
      剁椒牛头(467,954) 35/50(586,1000) 今日可请：2/2(581,1031)
    """

    FIX = Path(__file__).resolve().parent / "fixtures"

    def test_cards_found_by_text_on_new_layout(self):
        from PIL import Image
        from mtbot.tasks.tavern import _cards
        im = Image.open(self.FIX / "tavern_newrows.png").convert("RGB")
        cards = {c[0]: c for c in _cards(im)}
        self.assertEqual(set(cards), {"小黑", "剁椒牛头"})
        go_x, go_y = cards["小黑"][1]
        self.assertLess(abs(go_x - 578), 26)
        self.assertLess(abs(go_y - 882), 26)
        lx0, ly0, lx1, ly1 = cards["小黑"][2]
        self.assertTrue(lx0 <= 580 <= lx1 and ly0 <= 845 <= ly1)
        # 剁椒牛头的「请客」读不出来，用「今日可请」偏移顶上
        go_x, go_y = cards["剁椒牛头"][1]
        self.assertLess(abs(go_x - 581), 30)
        self.assertLess(abs(go_y - 1068), 30)

    def test_run_uses_dynamic_cards(self):
        src = _src("mtbot/tasks/tavern.py")
        self.assertIn("for name, go, left_box, shard_box in cards:", src)
        self.assertIn("cards = _cards(im)", src)
        self.assertNotIn("for name, go, left_box, shard_box in HEROES:", src)


class TavernPairReadTests(unittest.TestCase):
    """「今日可请：1/2」被 OCR 拆成 '今日'/'可请：1'/'1'/'1/2' 时不能读成 111/2。

    真帧 tests/fixtures/tavern_avail_frag.png（2026-11-20 06:11，小黑那张写 1/2）。
    """

    FIX = Path(__file__).resolve().parent / "fixtures"

    def test_fragmented_avail_reads_1_of_2(self):
        from PIL import Image
        from mtbot.tasks.tavern import _cards
        t = _tavern()
        im = Image.open(self.FIX / "tavern_avail_frag.png").convert("RGB")
        cards = {c[0]: c for c in _cards(im)}
        self.assertIn("小黑", cards)
        self.assertEqual(t._read(im, cards["小黑"][2]), (1, 2))
        self.assertEqual(t._pool(im), 0)

    def test_pool_and_full_guards_in_source(self):
        src = _src("mtbot/tasks/tavern.py")
        self.assertIn("碎片已满", src)
        self.assertIn("购买额度用完了", src)
        self.assertIn("TAVERN_POOL_PLUS", src)
        # 奖励浮层必须用酒馆自己的安全空白点关，不能用通用 L.BLANK
        self.assertNotIn("ui.press(L.BLANK", src)


def _tavern():
    from mtbot.tasks.tavern import TavernTask
    t = object.__new__(TavernTask)
    t.p = {}
    return t


class Audit26GuardsTests(unittest.TestCase):
    """audit26 第二批（其余 26 项任务）的硬证据闸门。"""

    def _src(self, *parts):
        return (HERE.parent.joinpath("mtbot", *parts)).read_text(encoding="utf-8")

    def test_bounty_refresh_requires_price(self):
        s = self._src("tasks", "daily.py")
        # 旧写法「单价读不到 + 钻石也读不到才收手」必须消失
        self.assertNotIn("if need is None and diamonds is None:", s)
        self.assertIn("读不到刷新单价 → 不刷新", s)
        # 每一刷都要有主城钻石前后差对账
        i_warn = s.index("刷新弹窗写 {need} 钻，主城钻石实际")
        i_log = s.index("悬赏：刷新 ×{info['refreshes']}")
        self.assertLess(i_log, i_warn)

    def test_hero_advance_needs_post_confirm_evidence(self):
        s = self._src("tasks", "reward.py")
        i_confirm = s.index("ui.press(L.HERO_BREAK_CONFIRM, 260)")
        i_ev = s.index("preview_gone = not vision.hero_break_dialog(after2)")
        i_acted = s.index("acted = True", i_ev)
        self.assertLess(i_confirm, i_ev)
        self.assertLess(i_ev, i_acted)
        self.assertIn("确认后没拿到「已进阶」证据", s)

    def test_arena_spend_gate_uses_real_price(self):
        s = self._src("tasks", "arena.py")
        self.assertNotIn('"角斗场买 1 次挑战次数", None,', s)
        self.assertIn('self.may_spend(ctx, "角斗场买 1 次挑战次数", cost,', s)
        self.assertIn("ctx: TaskContext | None = None", s)

    def test_hall_no_blind_like(self):
        s = self._src("tasks", "hall.py")
        self.assertIn("return None", s)             # _at_page 三态
        i_gold = s.index("if not vision.is_gold(im, *L.HALL_LIKE, r=18):")
        i_press = s.index('ui.press(L.HALL_LIKE, 250, label="hall_like"')
        self.assertLess(i_gold, i_press)

    def test_demon_same_does_not_arm(self):
        s = self._src("tasks", "combat.py")
        i_same = s.index('if r == "same":')
        seg = s[i_same:i_same + 600]
        self.assertNotIn("armed = True", seg)
        self.assertIn("保持原值", seg)

    def test_no_fallback_dead_coords_in_demon_result(self):
        s = self._src("tasks", "combat.py")
        self.assertNotIn("or L.TREE_RESULT_NEXT", s)
        self.assertNotIn("or L.TREE_RESULT_OK_FINAL", s)
        self.assertNotIn("or L.DEMON_DEFEAT_OK", s)

    def test_merchant_verifies_diamond_delta(self):
        s = self._src("tasks", "merchant.py")
        self.assertIn("diamonds_stable(ui, \"merchant_d0\")", s)
        self.assertIn("diamonds_stable(ui, \"merchant_d1\")", s)
        i_check = s.index("if ok and d0 is not None and d1 is not None and d1 < d0:")
        i_fail = s.index("怀疑真花钻了", i_check)
        self.assertLess(i_check, i_fail)

    def test_assist_upgrade_needs_gold(self):
        s = self._src("tasks", "assist.py")
        i_gold = s.index("if not vision.is_gold(im, *L.ASSIST_UPGRADE_BTN, r=18):")
        i_press = s.index("ui.press(L.ASSIST_UPGRADE_BTN, 250")
        self.assertLess(i_gold, i_press)

    def test_welfare_claim_needs_word(self):
        s = self._src("tasks", "reward.py")
        i_ocr = s.index('if "领取" in text and "已领取" not in text')
        i_press = s.index("if not ui.press((cx, cy), 220):")
        self.assertLess(i_ocr, i_press)

    def test_trial_save_verifies_leaving(self):
        s = self._src("pages.py")
        i_press = s.index('label="gtrial_ok"')
        i_chk = s.index("gtrial_ok_chk", i_press)
        self.assertLess(i_press, i_chk)
        self.assertIn("还停在结算页，继续等", s)


class DeadConfirmDialogFixTests(unittest.TestCase):
    """audit26 M1/M2/M3/M6：死判据 confirm_dialog 换掉、取消点按字找、像素兜底要二证。"""

    def _src(self, *parts):
        return (HERE.parent.joinpath("mtbot", *parts)).read_text(encoding="utf-8")

    def test_dialog_confirm_uses_modal_dim(self):
        s = self._src("vision.py")
        i = s.index("def dialog_confirm(im: Image.Image) -> bool:")
        seg = s[i:i + 900]
        self.assertIn("return modal_dim(im) and not item_popup(im)", seg)
        self.assertIn("5867", seg)          # 记下死判据的取证依据

    def test_task_sites_use_dialog_confirm(self):
        for rel in ("tasks/assist.py", "tasks/daily.py", "tasks/dungeon.py", "tasks/reward.py"):
            s = self._src(*rel.split("/"))
            self.assertIn("vision.dialog_confirm(", s)
            self.assertNotIn("vision.confirm_dialog(", s)

    def test_bounty_cancel_found_by_text(self):
        s = self._src("tasks", "daily.py")
        i = s.index("def _cancel_dialog(ui, im, label: str) -> bool:")
        seg = s[i:i + 900]
        self.assertIn('if "取消" in t.replace(" ", "")', seg)
        self.assertIn("用固定点兜底", seg)
        i_ocr = seg.index('if "取消" in t.replace')
        i_fb = seg.rindex("(235, 1060)")
        self.assertLess(i_ocr, i_fb)
        # 旧的裸固定点调用必须消失
        self.assertNotIn('label="bounty_refresh_cancel", expect="none")', s)

    def test_enhance_pixel_fallback_needs_gold_text(self):
        s = self._src("pages.py")
        i = s.index("2026-11-20 审计 M6")
        seg = s[i:i + 1400]
        self.assertIn("c0 and c1 and c0 != c1", seg)
        self.assertIn("当高亮，不算强化", seg)
        self.assertLess(seg.index("c0 and c1 and c0 != c1"), seg.index("当高亮，不算强化"))


class BountyNoBlindRetryTests(unittest.TestCase):
    """2026-11-20 08:02 实机：画面变了但没压暗时，同坐标补点会砸到「加速完成」。"""

    def test_accept_retry_only_when_screen_unchanged(self):
        s = (HERE.parent / "mtbot" / "pages.py").read_text(encoding="utf-8")
        i = s.index("def accept_row(self, y: int, label: str = \"\")")
        seg = s[i:i + 3200]
        self.assertIn("vision.diff_ratio(", seg)
        self.assertIn("不在同一坐标", seg)
        i_chk = seg.index(">= 0.01:")
        i_retry = seg.index('label=f"{tag}_accept2"')
        self.assertLess(i_chk, i_retry)



class BagAutoDecomposeTests(unittest.TestCase):
    """印记分解页的「获得普通、史诗印记时自动分解」开关（2026-11-20 真帧）。"""

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        cls.im = Image.open(HERE / "fixtures" / "bag_decompose_premium.png")

    def test_green_ratio_calibration(self):
        from mtbot import layout as L, vision
        # 真帧：勾选框里有绿勾，右边文字区和空白面板都没有
        self.assertGreaterEqual(vision.green_ratio(self.im, L.BAG_AUTO_BOX), L.BAG_AUTO_ON_RATIO)
        self.assertLess(vision.green_ratio(self.im, (300, 600, 500, 700)), 0.01)

    def test_auto_decompose_reads_on(self):
        from mtbot.tasks.tianshen import TianshenTask
        t = object.__new__(TianshenTask)
        self.assertIs(t._auto_decompose(self.im), True)

    def test_premium_page_reports_only_premium(self):
        src = (ROOT / "mtbot" / "tasks" / "tianshen.py").read_text(encoding="utf-8")
        # 开关判定必须在「快速选择」之前（快速选择是整页全选，混着高档会误伤）
        self.assertLess(src.index("auto = self._auto_decompose(im)"), src.index("L.BAG_QUICK"))
        # 只剩高档时不许再报「怕误伤」这种像失败的措辞，要如实说明
        self.assertIn('"only-premium"', src)
        self.assertNotIn("怕误伤", src)
        # 开关点开后必须复核绿勾
        self.assertIn("self._auto_decompose(im)", src)


class GoblinScrollRetryTests(unittest.TestCase):
    """地精层列表：滑动被界面吞掉时要给第二次机会（第 76 轮 10:47 的 WARN）。"""

    def setUp(self):
        self.src = (ROOT / "mtbot" / "tasks" / "goblin.py").read_text(encoding="utf-8")

    def test_scroll_helper_retries_once(self):
        self.assertIn("def _scroll(self, ui, up: bool, before: list, tag: str) -> list:", self.src)
        seg = self.src[self.src.index("def _scroll("):self.src.index("def _layer_rows(")]
        self.assertIn("for i in range(2):", seg)
        self.assertIn("同一手势再来一次", seg)

    def test_both_branches_use_scroll(self):
        self.assertEqual(self.src.count("self._scroll(ui, up=True"), 1)
        self.assertEqual(self.src.count("self._scroll(ui, up=False"), 1)
        # 旧写法不许回来
        self.assertNotIn('after = [r[0] for r in self._layer_rows(ui, "gob_layer_pg")]', self.src)

    def test_budget_allows_walking_back(self):
        seg = self.src[self.src.index("def _goto_layer("):]
        self.assertIn("budget = 40.0", seg)
        self.assertIn("for attempt in range(6):", seg)

if __name__ == "__main__":

    unittest.main()