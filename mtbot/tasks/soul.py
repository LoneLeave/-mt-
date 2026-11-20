"""罪魂之域（2026-10-30 新增副本，历练列表底部）。

2026-11-07 二次重写。上一版把「0 关」当成假成功，改完又掉进死循环；这一版按实机
逐屏取证重写了状态机。实测要点：

- 地图是绿蓝噪点画风，**没有任何能按颜色区分的水晶**；能点开的节点散布在探测网格上
  （x≈212/324/380/492/548 × y≈400~820），所以只能「点一下 → 看弹出什么」。
- 一轮完整流程：地图 → 点节点 → 关卡面板 → 金色「挑战」→ 快速战斗（BATTLE 约 2s）
  → 回地图并弹「挑战成功」横幅（约 6s）→ 横幅消失回地图。
- **赢一关后游戏会自动弹出「秘典」页**（OCR「当前秘典 / 请选择秘典」，米色占比 0.377）。
  它和关卡面板（0.66~0.81）落在同一个像素判据里：上一版把它当面板点 `(655,200)` 收面板，
  在秘典页这一点打开的是「是否将下方宝物移除」确认框，再点又退回秘典页，两态来回、
  diff 恒 0.567 → **7 分钟死循环**。秘典页唯一的出口是底部最左页签 `(140,1257)`。
- 首领页（OCR「选择首领词条 / 已通关难度：N/9」，米色 0.56~0.62）出口同上。
- 首领会进布阵页（「一键上阵」+ 金色「出战」），首领战是**实时战斗约 95 秒**，
  且**不消耗挑战次数**；默认不打（`boss: false`），碰到就退回地图。
- 「挑战次数：N/20」读得到就必须先读：**为 0 时金按钮照旧是亮金色**，点了游戏只在面板中间
  闪一行「挑战次数不足」（约 1.4s 出现、2.8s 消失），战斗不会开始——2026-11-07 05:13 用
  `logs\_soul_truth.py` 实测取证（第 2 关面板 gold=0.539、点了 5.6s 内始终是 panel）。
  次数为 0 时连面板都不用点：`_wait_battle` 也认这行提示，万一 OCR 读不出次数就直接收手。
- 退出该页不能用返回键（会弹「确认要退出游戏吗」），要点底部「主城」页签。
"""
from __future__ import annotations

import re
import time

from .. import layout as L
from .. import log, textocr, titles
from ..pages import MainCity, SoulPage
from .base import BaseTask, TaskContext, TaskResult

WIN_KEYS = ("挑战成功", "战斗胜利")
LOSE_KEYS = ("挑战失败", "战斗失败")
# 次数为 0 时游戏弹的一行提示（面板中间，约 1.4s 出现、2.8s 消失）
NOATT_KEYS = ("挑战次数不足", "次数不足")


class SoulTask(BaseTask):
    name = "soul"
    title = "罪魂之域"
    category = "combat"
    _noatt = False       # 上一次 _wait_battle 是否看到了「挑战次数不足」

    # ---------- 小工具 ----------

    def _leave(self, ui) -> None:
        """从罪魂之域回主城：点底部「主城」页签（返回键会弹退出游戏确认）。"""
        ui.press(L.TAB_MAIN, 250, expect="none")
        ui.wait(1.5)
        MainCity(ui).ensure()

    @staticmethod
    def _fingerprint(text: str) -> str:
        """面板指纹：同一关重复点开时用来去重（【第N关】+ 限制条件 / 宝箱正文）。"""
        return re.sub(r"\s+", "", text or "")[:80]

    @staticmethod
    def _note(text: str) -> str:
        """从面板文字里抠出「需通关…」这类提示，便于日志可读。"""
        for line in (text or "").split():
            if "需通关" in line or "未解锁" in line:
                return line
        return ""

    def _read(self, ui, tag: str):
        """抓帧 + 判屏，返回 (im, text, kind)。

        2026-11-08 提速：先走「免 OCR 快路径」。全屏 OCR 单次实测 2.5~12.8s
        （logs\_ocr_var.py），而探测网格里绝大多数格点点下去什么都不会发生、画面
        仍是地图 —— 那些格子原先每格都白等一次全屏 OCR（实机每格 18~22s，
        10 格 1013s）。现在先用两个便宜判据确认「米色面板没开 + 罪魂之域标题还在」
        = 地图，直接返回、不做 OCR：`panel_open` 0.032s + `titles.on_page` 0.085s。
        `logs\_soul_kind_probe.py` 在 100+ 张真帧上对照 OCR 真值：mismatch 0。
        """
        im = ui.screen(tag)
        if textocr.available():
            if not SoulPage.panel_open(im) and titles.on_page(im, "soul"):
                return im, "", "map"
        txt = textocr.read_text(im) if textocr.available() else ""
        return im, txt, SoulPage.screen_kind(im, txt)

    def _settle(self, ui, page: SoulPage, kind: str, txt: str) -> str:
        """把非地图屏处理掉，返回处理后的动作名（用于日志/预算）。"""
        if kind == "dialog":
            log.info("  罪魂之域：遇到「宝物移除」确认框，点取消")
            page.cancel_remove_dialog()
            return "dialog"
        if kind == "codex":
            log.info("  罪魂之域：弹出秘典页，点底部最左页签回地图")
            page.exit_codex()
            return "codex"
        if kind == "boss":
            if self.p.get("boss", False):
                return "boss"
            log.info("  罪魂之域：碰到首领页，本轮不打首领，退回地图")
            page.exit_codex()
            return "boss"
        if kind == "result":
            page.close_result()
            return "result"
        if kind in ("panel", "chest"):
            page.close_panel()
            return kind
        if kind == "other":
            # 未知米色浮层：先试右上关闭点，再试秘典页出口，最后交给上层兜底
            page.close_panel()
            return "other"
        return ""

    def _drain_banner(self, ui, page: SoulPage, budget: float = 30.0) -> None:
        """等「挑战成功」横幅自己消失，顺便把自动弹出的秘典页关掉。

        横幅阶段画面仍是地图但盖着半透明文字，此时任何点位点击都不可靠；
        实测横幅约 +4.6s 出现、+12.4s 消失，之后才真正回地图。
        """
        t0 = time.time()
        while time.time() - t0 < budget:
            ui.wait(1.8)
            im, txt, kind = self._read(ui, "soul_banner")
            if kind == "codex":
                page.exit_codex()
                return
            if any(k in txt for k in WIN_KEYS):
                continue
            if kind in ("map", "panel", "chest", "boss"):
                return
        log.warn("  罪魂之域：胜利横幅 30 秒还没散，直接继续")

    def _wait_battle(self, ui, page: SoulPage, att_before, budget: float = 150.0):
        """点完「挑战」/「出战」后等结果，返回 (win, lose)。

        判定顺序：OCR「挑战成功/战斗胜利」→ win；「挑战失败」→ lose；结算页 → 点确定；
        回到地图且「挑战次数」比点之前少 → win（快速战斗只闪一下横幅时兜底）。
        """
        t0 = time.time()
        self._noatt = False
        last_att = 0.0
        while time.time() - t0 < budget:
            ui.wait(1.6)
            im, txt, kind = self._read(ui, "soul_battle")
            if kind == "panel" and any(k in txt for k in NOATT_KEYS):
                # 「挑战次数不足」：战斗根本没开始，别在这里白等到 budget 用完
                log.info("  罪魂之域：游戏提示「挑战次数不足」，这次挑战没发出去")
                self._noatt = True
                return False, False
            if any(k in txt for k in WIN_KEYS):
                self._drain_banner(ui, page)
                return True, False
            if any(k in txt for k in LOSE_KEYS):
                self._drain_banner(ui, page)
                return False, True
            if kind == "result":
                # 2026-11-19：首领战的结算页必须先把「胜利/失败」读出来再关。
                # 旧码这里直接 close_result() 把结果扔了 → 回塔页面后横幅读不到
                # 「挑战成功」、次数又不变 → 白等 240 秒判 unknown（_soul_boss1 两次 FAIL）。
                rt = ""
                try:
                    if textocr.available():
                        rt = textocr.read_text(im, L.SOUL_RESULT_ROI).replace(" ", "")
                except Exception:        # noqa: BLE001 - 读不到就看下面兜底
                    rt = ""
                if any(k in rt for k in L.SOUL_RESULT_WIN_KEYS):
                    page.close_result()
                    self._drain_banner(ui, page)
                    return True, False
                if any(k in rt for k in L.SOUL_RESULT_LOSE_KEYS):
                    page.close_result()
                    self._drain_banner(ui, page)
                    return False, True
                page.close_result()
                continue
            if kind == "codex":
                page.exit_codex()
                return True, False
            if kind == "dialog":
                page.cancel_remove_dialog()
                continue
            if kind in ("battle", "other", "unknown"):
                # 2026-11-15：罪魂之域的真实战斗也有「跳过」模板（中心 (652,899)）。
                # 旧码在这里只 ui.wait 干等，90 秒到点就判「未通关」——_usrgr 20:00:51
                # 那次 FAIL（0 关）就是打赢了却被当成没打开。战斗中先点跳过，快点进结算。
                ui.battle_skip(im, quiet=True)
                continue
            if kind == "map":
                # 2026-11-15：_read 的快路径为了省 OCR 会把文字清空，而「挑战成功 /
                # 挑战失败」横幅正好盖在地图 y≈200~420 上。快速战斗的胜负都不会让
                # 「挑战次数」变化，旧码只看次数 → 150 秒静默空转、0 关 FAIL
                # （_usrgr 20:00 与 20:35 两次）。这里只 OCR 那一条，成本远低于全屏。
                ban = ""
                if textocr.available():
                    try:
                        ban = textocr.read_text(im, L.SOUL_BANNER_ROI)
                    except Exception:      # noqa: BLE001 - 读不到就当没横幅
                        ban = ""
                if any(k in ban for k in WIN_KEYS):
                    self._drain_banner(ui, page)
                    return True, False
                if any(k in ban for k in LOSE_KEYS):
                    self._drain_banner(ui, page)
                    return False, True
                # 次数只能靠 OCR 读（模板法恒空），单次约 4.6s → 最多每 5s 读一次，
                # 否则等结算的那 90 秒里会反复付这笔钱。
                # 2026-11-19 审计：这里原来「次数变少就判通关」，但同一函数的注释
                # （见上）已经写明快速战斗胜负都不改变次数 → 那条判断拿不到真证据，
                # 还会因 OCR 把 18/20 读成 17/20 而虚报一关胜利。现在只记日志不判胜负。
                if time.time() - last_att >= 5.0:
                    last_att = time.time()
                    att_now = page.attempts(im)
                    if att_before and att_now and att_now[0] < att_before[0]:
                        log.info(f"  罪魂之域：挑战次数 {att_before} → {att_now}"
                                 f"（快速战斗胜负都不改次数，这里不据此判胜负）")
        log.warn(f"  罪魂之域：{budget:.0f} 秒内没看到明确结果，按未通关处理")
        return False, False

    def _continue_battle(self, ui, page: SoulPage) -> str:
        """误进布阵页/战斗时把它走完（首领战的实时战斗）。"""
        im, txt, kind = self._read(ui, "soul_mid")
        if kind == "deploy":
            ui.press(L.DEPLOY, 200, expect="none")
            ui.wait(1.2)
            ui.press(L.SOUL_DEPLOY_GO, 250, label="soul_deploy_go", expect="none")
        win, lose = self._wait_battle(ui, page, None, budget=300.0)
        return "win" if win else ("lose" if lose else "unknown")

    # ---------- 单个节点 ----------

    def _try_node(self, ui, page: SoulPage, pos, seen: set) -> str:
        """点一个探测格：返回 win / lose / locked / seen / noatt / none / unknown。"""
        ui.press(pos, 200, expect="none")
        ui.wait(1.5)
        im, txt, kind = self._read(ui, "soul_panel")

        if kind == "map":
            return "none"
        if kind in ("deploy", "battle", "result"):
            return self._continue_battle(ui, page)
        if kind == "boss" and self.p.get("boss", False):
            return self._fight_boss(ui, page)
        if kind != "panel":
            # 宝箱 / 秘典 / 首领 / 未知浮层：都不是关卡，处理掉再继续
            act = self._settle(ui, page, kind, txt)
            return "none" if act else "unknown"

        if page.locked_panel(txt):
            log.info(f"  罪魂之域：{pos} 是未解锁关卡（{self._note(txt)}）")
            page.close_panel()
            return "locked"

        fp = self._fingerprint(txt)
        if fp and fp in seen:
            page.close_panel()
            return "seen"
        if fp:
            seen.add(fp)

        if not page.challenge_panel(im):
            log.info(f"  罪魂之域：{pos} 面板没有金色「挑战」（可能已通关）")
            page.close_panel()
            return "none"

        att_before = page.attempts(im)
        if att_before and att_before[0] <= 0:
            log.info(f"  罪魂之域：面板显示挑战次数 {att_before[0]}/{att_before[1]}，按钮点了也没用")
            page.close_panel()
            return "noatt"

        log.info(f"  罪魂之域：挑战 {pos}（{self._note(txt) or '已解锁'}）")
        # expect="none"：这一击的结果由 _wait_battle 判，别让「变化校验」在这里白做 4 个
        # 补偿点（实测 8s）——次数为 0 时游戏只闪 1.4~2.8s 的「挑战次数不足」，
        # 补偿点等完提示早没了，既漏判又刷一条空点 WARN。
        ui.press(L.SOUL_CHALLENGE, 250, label="soul_challenge", expect="none")
        win, lose = self._wait_battle(ui, page, att_before)
        if self._noatt:
            page.close_panel()
            return "noatt"
        if win:
            return "win"
        if lose:
            return "lose"
        return "unknown"

    # ---------- 首领 ----------

    def _fight_boss(self, ui, page: SoulPage) -> str:
        """首领页 → 挑战 → 布阵页「一键上阵 + 出战」→ 实时战斗 ~95s。"""
        log.info("  罪魂之域：打首领")
        ui.press(L.SOUL_BOSS_CHALLENGE, 250, label="soul_boss_go", expect="none")
        ui.wait(2.0)
        im, txt, kind = self._read(ui, "soul_boss_deploy")
        if kind != "deploy":
            log.warn(f"  罪魂之域：首领页点「挑战」后没进布阵页（{kind}）")
            self._settle(ui, page, kind, txt)
            return "none"
        ui.press(L.DEPLOY, 200, expect="none")
        ui.wait(1.2)
        ui.press(L.SOUL_DEPLOY_GO, 250)
        win, lose = self._wait_battle(ui, page, None, budget=240.0)
        if win:
            return "win"
        if lose:
            return "lose"
        return "unknown"

    # ---------- 首领塔（第 N 层）版页面 ----------

    @staticmethod
    def _boss_mode_text(im) -> str:
        """读整页文字（用于判断是不是首领塔页面）。读不到返回空串。"""
        try:
            if not textocr.available():
                return ""
            return textocr.read_text(im, (0, 60, 720, 1240)).replace(" ", "")
        except Exception:            # noqa: BLE001
            return ""

    def _enter_boss(self, ui, page: SoulPage) -> bool:
        """从塔页面点开首领页；成功返回 True。"""
        for pos in L.SOUL_BOSS_ENTRY_CANDS:
            ui.press(pos, 200, label=f"soul_boss_entry:{pos[0]},{pos[1]}", expect="none")
            ui.wait(1.6)
            im = ui.screen("soul_boss_open")
            txt = self._boss_mode_text(im)
            kind = page.screen_kind(im, txt)
            if kind == "boss":
                log.info(f"  罪魂之域：点 {pos} 打开了首领页")
                return True
            if kind not in ("map", ""):
                self._settle(ui, page, kind, txt)
        return False

    def _run_boss_mode(self, ui, page: SoulPage, att, max_fights: int,
                       deadline_s: float = 1500.0) -> "TaskResult":
        """首领塔：点首领 → 首领页挑战 → 布阵 → 战斗，直到次数用尽/连败/到时限。"""
        deadline = time.time() + deadline_s
        wins = loses = 0
        reason = ""
        limit = int(L.SOUL_BOSS_FIGHT_LIMIT)
        log.info("  罪魂之域：今天这版是「第 N 层首领」塔（没有水晶路线），走首领挑战")

        while wins + loses < max_fights and time.time() < deadline:
            if ui.handle_interruptions():
                continue
            im, txt, kind = self._read(ui, "soul_boss_loop")
            if kind not in ("", "map"):
                self._settle(ui, page, kind, txt)
                continue
            if not page.at_page(im):
                if not page.enter():
                    reason = "中途离开后又进不去罪魂之域"
                    break
                continue
            fresh = page.attempts(im)
            if fresh is not None:
                att = fresh
            if att and att[0] <= 0:
                reason = f"挑战次数用尽（{att[0]}/{att[1]}）"
                break
            if not self._enter_boss(ui, page):
                reason = "点不开首领页"
                break
            res = self._fight_boss(ui, page)
            if res == "win":
                wins += 1
                log.info(f"  罪魂之域：首领战第 {wins} 胜")
            elif res == "lose":
                loses += 1
                log.info(f"  罪魂之域：首领战第 {loses} 负（这一场没打过）")
                if loses >= limit and wins == 0:
                    reason = "连败"
                    log.info(f"  罪魂之域：首领战连输 {loses} 场，战力不够，收手")
                    break
            else:
                reason = "首领战没有明确结果"
                break
            # 战斗结束后可能弹秘典/结算，逐帧收掉，直到回到塔页面
            for _ in range(3):
                im2, txt2, kind2 = self._read(ui, "soul_boss_after")
                if kind2 in ("", "map"):
                    break
                self._settle(ui, page, kind2, txt2)

        self._leave(ui)
        stats = {"wins": wins, "loses": loses, "mode": "boss"}
        if wins:
            return TaskResult(True, f"罪魂之域（首领会战）：胜 {wins} 负 {loses}", stats)
        if loses:
            return TaskResult.skip(f"罪魂之域（首领会战）：今天一关都没打过（{loses} 负）", stats)
        return TaskResult.fail(f"罪魂之域：0 关（{reason or '首领塔没有可打的'}）", stats)

    # ---------- 主流程 ----------

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_nodes = int(p.get("max_nodes", 10))
        with_boss = bool(p.get("boss", False))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = SoulPage(ui)
        if not page.enter():
            MainCity(ui).ensure()
            return TaskResult.fail("进不去罪魂之域")

        im, txt, kind = self._read(ui, "soul_map")
        att = page.attempts(im)
        # 2026-11-08 提速：`attempts()` 是一次整行 OCR（本机实测 2.88s），
        # 而它读的「挑战次数」只在通关后才会变。以前每探测一个格点都重读
        # 一次 → 30 格白烧约 87s。现在按 20 秒节流，通关后（次数变了）
        # 再把时间戳清零强制重读。
        att_ts = time.time()
        if att is not None and att[0] <= 0:
            self._leave(ui)
            return TaskResult.skip(f"挑战次数已用尽（{att[0]}/{att[1]}，每日登录 +5）")
        if att is None:
            log.warn("  罪魂之域：读不出挑战次数，按「还能打」继续")

        # 2026-11-19：页面可能是「第 N 层首领」塔（没有水晶格点）。
        # 旧码继续扫 30 个格点 → 全空 → FAIL「探测网格里已经没有可挑战的关卡」。
        flat_map = ""
        try:
            if textocr.available():
                flat_map = textocr.read_text(im, (0, 60, 720, 1240)).replace(" ", "")
        except Exception:            # noqa: BLE001 - 读不到就按老路走
            flat_map = ""
        if any(k in flat_map for k in L.SOUL_BOSS_MODE_KEYS):
            return self._run_boss_mode(ui, page, att, max_nodes, deadline_s=25 * 60)

        wins = loses = 0
        locked = 0
        # 2026-11-08：连续「未解锁」计数。前 8 个格点是历史命中点，
        # 它们全未解锁就说明今天能打的已经打完，别再白扫 20 多个格点。
        lock_run = 0
        lock_run_max = int(p.get("lock_run", 8))
        seen: set = set()
        probes = 0
        reason = ""
        noatt = False
        deadline = time.time() + 25 * 60
        grid = list(page.crystal_nodes())
        gi = 0

        while wins < max_nodes and time.time() < deadline:
            if ui.handle_interruptions():
                continue
            im, txt, kind = self._read(ui, "soul_loop")

            # 非地图屏：原地处理掉，不消耗探测预算
            if kind not in ("", "map"):
                if kind == "boss" and with_boss:
                    res = self._fight_boss(ui, page)
                    if res == "win":
                        wins += 1
                        log.info(f"  罪魂之域：首领通关（第 {wins} 胜）")
                    elif res == "lose":
                        loses += 1
                    else:
                        reason = "首领战没有明确结果"
                        break
                else:
                    self._settle(ui, page, kind, txt)
                continue

            if not page.at_page(im):
                log.info("  罪魂之域：被弹窗/其他页面顶掉，重新进入")
                if not page.enter():
                    reason = "中途离开后再也进不去罪魂之域"
                    break
                continue

            if time.time() - att_ts > 20.0:
                fresh = page.attempts(im)
                if fresh is not None:
                    att = fresh
                att_ts = time.time()
            if att and att[0] <= 0:
                reason = f"挑战次数用尽（{att[0]}/{att[1]}）"
                break

            if gi >= len(grid):
                reason = "探测网格里已经没有可挑战的关卡"
                break

            pos = grid[gi]
            gi += 1
            probes += 1
            res = self._try_node(ui, page, pos, seen)
            if res == "win":
                wins += 1
                lock_run = 0
                att_ts = 0.0        # 次数变了，下一轮立刻重读
                log.info(f"  罪魂之域：通关第 {wins} 个关卡")
            elif res == "lose":
                loses += 1
                lock_run = 0
                log.info("  罪魂之域：这一关没打过")
                # 2026-11-15：快速战斗失败不扣次数，但每打一次要 ~9s；连输 3 场说明
                # 今天的战力就是打不动，再扫下去只是白耗时间（_usrgr 曾扫满 508s）。
                if wins == 0 and loses >= 3:
                    reason = "连败"
                    log.info(f"  罪魂之域：连输 {loses} 场，今天的战力打不过，收手")
                    break
            elif res == "noatt":
                noatt = True
                reason = "挑战次数用尽"
                break
            elif res == "locked":
                locked += 1
                lock_run += 1
                if lock_run_max > 0 and lock_run >= lock_run_max and wins == 0:
                    reason = "连续未解锁"
                    log.info(f"  罪魂之域：连续 {lock_run} 个格点都是未解锁关卡，"
                             f"今天能打的应该已经打完，不再白扫剩下的格点")
                    break
            elif res == "unknown":
                reason = f"{pos} 点开后没有明确结果"
                break
            # none / locked / seen：继续下一个格点

        self._leave(ui)
        if wins:
            return TaskResult(True, f"罪魂之域：通关 {wins} 关",
                              {"wins": wins, "loses": loses, "probes": probes})
        if noatt:
            # 次数用尽是每天的正常状态（00:00 才补），不是脚本故障：和进门时读数为 0 一样按「跳过」报
            return TaskResult.skip("挑战次数已用尽（游戏提示「挑战次数不足」）")
        if reason in ("探测网格里已经没有可挑战的关卡", "连续未解锁") and locked:
            # 2026-11-08：网格扫完、只看到「未解锁」→ 今天能打的已经打完了，不是脚本故障。
            return TaskResult.skip(
                f"罪魂之域：今天能打的都打完了（{locked} 个关卡未解锁，探测 {probes} 个格点）")
        if loses:
            # 打不过属于真状态（战力不够），不是脚本故障：按「跳过」报，别把真状态当 FAIL
            return TaskResult.skip(
                f"罪魂之域：今天一关都没打过（{loses} 负，探测 {probes} 个格点）")
        if reason:
            return TaskResult.fail(f"罪魂之域：0 关（{reason}）")
        return TaskResult.fail("罪魂之域：0 关（到 25 分钟上限）")