"""排行榜奖励（用户点名要求，移植自 E:/DailyIdea 的 claim_events.rank_rewards）。

2026-10-31 重做（旧版两个假设都是错的）：
  ① 进度奖励不是格子阵、也不用长按：面板是**竖排列表**，可领取的行在奖励图标
     右上角挂红色「!」，**单击图标**就领（弹「获得奖励」浮层，点空白关掉）；
  ② 底部小页签（等级排行/战力排行/战役关卡/守护者之塔/邪能神殿…）可横向滑动，
     **有未领奖励的页签图标上方有红「!」**——脚本先找角标，有角标才切过去开奖励面板，
     不再像旧版那样“切到 10 个榜单、领取 0 档”。

另外列表页还有「本服进度 / 本服养成 / 跨服排行」三个大分类，每个分类的榜单不同，
任务会三个分类都过一遍。
"""
from __future__ import annotations

import time

from .. import layout as L
from .. import log, vision
from ..pages import MainCity, RankBoardPage
from .base import BaseTask, TaskContext, TaskResult


def _strip_same(a, b) -> bool:
    """底部页签条（y 1150~1235）前后是否一样：一样 = 已经滑到头，没有更多页签。"""
    if a.size != b.size:
        return False
    d = t = 0
    for y in range(1150, min(1235, b.height), 6):
        for x in range(100, 700, 6):
            p, q = a.getpixel((x, y)), b.getpixel((x, y))
            t += 1
            if abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) > 60:
                d += 1
    return t > 0 and (d / t) < 0.02


class RankBoardTask(BaseTask):
    name = "rank_board"
    title = "排行榜奖励"
    category = "reward"

    def _claim_board(self, ui, page: RankBoardPage) -> int:
        """当前榜单：先看底部页签的红「!」，有角标就切过去领；页签条可以一直往左滑。"""
        claimed = 0
        seen: set[int] = set()
        swipes = 0
        deadline = time.time() + 300
        while time.time() < deadline:
            im = ui.screen("rank_tabs")
            badges = page.tab_badges(im)
            todo = [x for x in badges if x not in seen]
            if not todo:
                if swipes >= 3:
                    break
                ui.dev.swipe(*L.RANK_TAB_STRIP, 600)
                ui.wait(1.2)
                swipes += 1
                im2 = ui.screen("rank_tabs2")
                if _strip_same(im, im2):
                    break
                badges = page.tab_badges(im2)
                todo = [x for x in badges if x not in seen]
                if not todo:
                    continue
            x = todo[0]
            seen.add(x)
            ui.press((x, L.RANK_TAB_TAP_Y), 220, label=f"rank_tab_badge:{x}", expect="none")
            ui.wait(1.8)
            if not page.in_leaderboard():
                log.info(f"  排行榜：页签 x={x} 切过去不是榜单页，跳过")
                continue
            if page.open_reward_panel():
                got = page.claim_panel_rows()
                page.close_reward_panel()
                claimed += got
                if got:
                    log.info(f"  排行榜：页签 x={x} 领取 {got} 档")
        # 2026-11-04：页签没有红「!」也要开一次「进度奖励」面板核对行内红点——
        # 既可能补领面板里漏掉的档位，也给「本榜已领完」留下面板帧证据（已领取/暂无玩家上榜）。
        # 跨服分类没有奖杯按钮，open_reward_panel 返回 False 时直接跳过（不再盲点+补偿空转）。
        if page.open_reward_panel():
            got = page.claim_panel_rows()
            page.close_reward_panel()
            claimed += got
            log.info(f"  排行榜：进度奖励面板核对完毕，补领 {got} 档")
        else:
            log.info("  排行榜：本榜无进度奖励入口，跳过面板核对")
        return claimed

    def _await_list(self, ui, page: RankBoardPage, tries: int = 5, gap: float = 0.8) -> bool:
        """等榜单列表页稳定下来（轮询，不是看一眼就判死）。

        2026-11-07 11:12 实机：从「本服进度」榜单返回列表后立刻点 (540,1212)
        「本服养成」，1.4s 后那一帧还没画完 → `at_page` False，整类被
        `continue` 跳过，结果只报了「2 个分类」。同一条路径在探针里连跑
        12 次全部成功（`logs\\_rk_probe3.py`，bad=0），说明是瞬时态而不是
        坐标错。现在：轮询到列表页出现为止，中间把残留浮层/确认框点掉。
        """
        for i in range(tries):
            im = ui.screen(f"rank_settle{i}")
            if page.at_page(im):
                return True
            if ui.handle_interruptions() or ui.close_popup(im):
                log.info(f"  排行榜：列表页被浮层挡住（第 {i + 1} 次），已关闭")
            ui.wait(gap)
        return False

    def _switch(self, ui, page: RankBoardPage, gx: int, gy: int) -> bool:
        """切到一个大分类并确认列表页已就绪；失败就整页重进再试一次。

        2026-11-07 12:11 实机（全量 v6）：第 3 个分类 (613,1212) 点下去后轮询 5 次
        `at_page` 全是 False，整类被跳过（结果只报「2 个分类」）；同一路径单独重跑
        3/3 全过、探针连跑 12 次 bad=0 → 是偶发瞬时态（上一类收尾的浮层还没散）。
        所以这里不再「看一眼就放弃」：先原地轮询，仍不行就回主城把排行榜页整个重进
        一次再切，只有二次仍失败才认输。
        """
        cur = ui.screen("rank_tabs")
        if vision.avg(cur, gx, gy, 20)[0] > 160:
            log.info(f"  排行榜：分类 ({gx},{gy}) 已是当前页签，跳过点击")
        else:
            ui.press((gx, gy), 220, label=f"rank_tab:{gx}", expect="none")
        ui.wait(1.4)
        if self._await_list(ui, page):
            return True

        log.info(f"  排行榜：分类 ({gx},{gy}) 列表页没就绪，回主城重进排行榜页再切一次")
        if not (MainCity(ui).ensure() and page.enter()):
            return False
        ui.wait(1.2)
        ui.press((gx, gy), 220, label=f"rank_tab2:{gx}", expect="none")
        ui.wait(1.4)
        return self._await_list(ui, page)

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = RankBoardPage(ui)
        if not page.enter():
            MainCity(ui).ensure()
            return TaskResult.skip("排行榜入口没打开")

        claimed = boards = 0
        for gx, gy in L.RANK_BOARD_TABS:
            if not self._switch(ui, page, gx, gy):
                # 2026-11-04：不许静默 continue——写清哪个页签、点了哪里、判定值
                log.warn(f"  排行榜：页签 ({gx},{gy}) 重进后仍没命中列表页，跳过该分类")
                continue
            if not page.open_board():
                log.warn(f"  排行榜：分类 ({gx},{gy}) 点不进榜单（open_board 返回 False），跳过")
                continue
            boards += 1
            claimed += self._claim_board(ui, page)
            if not page.back_to_list():
                # 回不到列表就重新从主城进一次
                MainCity(ui).ensure()
                if not page.enter():
                    break

        MainCity(ui).ensure()
        stats = {"boards": boards, "claimed": claimed}
        if boards <= 0:
            # 2026-11-09 假成功审计：三个分类一个都没进去，不该算 OK
            return TaskResult.fail("排行榜：三个分类一个都没进去（页签/榜单都没打开）", stats)
        return TaskResult(True, f"排行榜：{boards} 个分类，领取 {claimed} 档", stats)
