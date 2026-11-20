"""每日任务：领奖 / 快速挂机 / 强化 / 商店刷新 / 公会捐献 / 公会试炼 / 悬赏 / 主线。

说明（2026-10-29 实测）：
  - 日常页任意一个「领取」会一次领完所有已完成任务，再点 4 个活跃度宝箱。
  - 挂机特权弹窗没有 X，用底部「战役」tab 退出；「挂机收益」弹窗点 (360,1228) 关。
  - 悬赏每次消耗 2000 悬赏积分，不够时点「接受」画面不变。
  - 主线战役有等级门槛（当前 118 级解锁），被挡时直接跳过。
"""
from __future__ import annotations

import re
import time

from .. import layout as L
from .. import log, textocr, vision
from ..pages import (BountyPage, CampaignPage, DailyPage, ForgePage,
                     GuildPage, MainCity, ShopPage)
from ..vision import State
from .base import BaseTask, TaskContext, TaskResult

def _cancel_dialog(ui, im, label: str) -> bool:
    """点弹窗里的「取消」：先 OCR 找字，找不到才用固定点兜底。

    2026-11-20 审计 M3：旧码两处直接点 (235, 1060)。弹窗高度一变就点空，
    弹窗关不掉时下一条指令还可能落在金色「确定」上（= 花钻）。
    """
    try:
        for t, c, _sc in textocr.read_lines(im, (80, 600, 660, 1150), min_score=0.45):
            if "取消" in t.replace(" ", ""):
                ui.press(c, 200, label=f"{label}_ocr", expect="none")
                ui.wait(1.0)
                return True
    except Exception:      # noqa: BLE001
        pass
    log.info(f"  {label}：弹窗里读不到「取消」文字，用固定点兜底")
    ui.press((235, 1060), 200, label=f"{label}_fb", expect="none")
    ui.wait(1.0)
    return False


POPUP_CLOSE_BOTTOM = (360, 1228)


def _row_changed(a, b, y: int) -> bool:
    """比较悬赏列表某一行（图标+按钮+倒计时）是否变化，避免顶部横幅动画干扰。"""
    if a.size != b.size:            # 被别的脚本转横屏时尺寸会变
        return True
    x0, y0, x1, y1 = 330, max(0, y - 60), 700, min(a.height, y + 60)
    d = t = 0
    for yy in range(y0, y1, 4):
        for xx in range(x0, x1, 4):
            p, q = a.getpixel((xx, yy)), b.getpixel((xx, yy))
            t += 1
            if abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) > 90:
                d += 1
    return t > 0 and (d / t) > 0.02


# ---------------------------------------------------------------- 悬赏（品质过滤）
QUALITIES = ("普通", "稀有", "史诗", "传说", "神话")
HIGH_QUALITIES = ("史诗", "传说", "神话")     # 用户规则：只接这三个档次


def bounty_quality(im, y: int):
    """读某一行的品质徽章（模板匹配，实测正确项 1.00、其它 ≤0.33）。"""
    from .. import template as T

    best, score = None, 0.0
    for q in QUALITIES:
        # ROI 必须覆盖整枚徽章（模板高 >100px）；实测 60~200 / y±75 才认得出传说
        sc = T.VI.best_score(im, f"悬赏_{q}.png", roi=(60, y - 75, 200, y + 75))
        if sc > score:
            best, score = q, sc
    return best if score >= 0.80 else None


def _checked(im, x: int, y: int) -> bool:
    """设置弹窗里的复选状态：勾上时是绿色对勾。"""
    n = 0
    for yy in range(y - 14, y + 14, 2):
        for xx in range(x - 14, x + 14, 2):
            R, G, B = im.getpixel((xx, yy))
            if G > 120 and (G - R) > 35 and (G - B) > 25:
                n += 1
    return n >= 10


def _settings_ready(im) -> bool:
    """设置弹窗是否渲染完成：复选框行出现浅色底（动画滑入中整块是深色，实测 <10 px）。

    2026-11-05 实测：press(齿轮) 后 wait(1.8) 有时弹窗还在滑入，5 行复选框全是深色，
    _checked 读成全 False → 把已勾的史诗/传说/神话误点取消。渲染完成后每行 ≥250 浅色 px。
    2026-11-06：底色判据偶尔仍会漏（弹窗已开、行底色偏暗），补一条 OCR 兜底——
    能读到「自动接受」就说明弹窗确实开了。
    """
    for y in L.BOUNTY_SETTING_ROWS:
        light = sum(1 for xx in range(465, 510) for yy in range(y - 12, y + 12)
                    if all(c > 150 for c in im.getpixel((xx, yy))))
        if light < 100:
            break
    else:
        return True
    text = textocr.read_text(im, L.BOUNTY_SETTING_TEXT_ROI)
    return "自动接受" in text


def _bottom_text(im) -> str:
    """悬赏页底栏文字（「一键领取」/「快速接受」+「30刷新」）。"""
    return textocr.read_text(im, L.BOUNTY_BOTTOM_ROI)


def ensure_bounty_filter(ui) -> bool:
    """把悬赏设置里的「自动接受」勾选改成 史诗/传说/神话（用户指定）。

    勾选后，点「刷新」时游戏会自动接取这些档次的悬赏，脚本不用逐条点接受。

    2026-11-06 实机踩坑：底栏左侧那个按钮会变——有已完成的悬赏时它是「一键领取」，
    正好盖住齿轮位置 `L.BOUNTY_SETTINGS=(425,1230)`。此时点齿轮弹出的是「获得奖励」
    浮层，设置弹窗根本没开（旧版只看像素判据，于是打「设置弹窗没渲染出来」跳过勾选）。
    所以点齿轮前先看底栏：是「一键领取」就先免费领掉、关浮层，等它变回「快速接受」。
    """
    for attempt in range(2):
        im = ui.screen("bounty_before_gear")
        if "一键领取" in _bottom_text(im):
            log.info("  悬赏：底栏是「一键领取」（盖住设置齿轮），先免费领掉再开设置")
            ui.press(L.BOUNTY_CLAIM_ALL, 250, label="bounty_claim_all", expect="none")
            ui.wait(2.0)
            ui.press(L.BLANK, 150, expect="none")   # 关「获得奖励」浮层
            ui.wait(1.2)
        # 齿轮是导航点：点完下面会用 _settings_ready 复核弹窗有没有出来，
        # 不需要变化校验（2026-11-10 第 33 轮：这里被判「空点」并触发 4 个补偿点）。
        ui.press(L.BOUNTY_SETTINGS, 250, label="bounty_gear", expect="none")
        # 等弹窗渲染完成（滑入动画有时 >1.8s）：每 0.4s 探一次，最多 3.2s
        im = ui.screen("bounty_set")
        for _ in range(6):
            if _settings_ready(im):
                break
            ui.wait(0.4)
            im = ui.screen("bounty_set_wait")
        if _settings_ready(im):
            break
        log.info(f"  悬赏：点齿轮后没出现设置弹窗（第 {attempt + 1} 次，多半是上一层的浮层没关干净），关掉浮层再试")
        ui.press(L.BLANK, 150, expect="none")
        ui.wait(1.0)
    else:
        log.warn("  悬赏：设置弹窗始终没出来，跳过勾选（本轮只用默认自动接受档位）")
        return False
    changed = 0
    for q, y in zip(QUALITIES, L.BOUNTY_SETTING_ROWS):
        want = q in HIGH_QUALITIES
        cur = _checked(im, L.BOUNTY_SETTING_CHECK_X, y)
        if cur == want:
            continue
        # 勾选框只有 28×28，变化 <2%，走默认校验会被判「空点」→ 4 次补偿重试
        # 反复勾/取消（2026-11-04 实测把「史诗」勾掉了）。所以点击不校验，
        # 但**点完必须回头复核**（2026-11-07 补）：否则勾没勾上全靠猜，日志只能写「改了 N 行」。
        for attempt in range(2):
            ui.press((L.BOUNTY_SETTING_CHECK_X, y), 200,
                     label=f"bounty_filter:{q}", expect="none")
            ui.wait(0.7)
            im = ui.screen(f"bounty_set2_{attempt}")
            now = _checked(im, L.BOUNTY_SETTING_CHECK_X, y)
            if now == want:
                changed += 1
                break
        else:
            log.warn(f"  悬赏：{q} 行的「自动接受」勾选没改过来"
                     f"（读到 {'已勾' if _checked(im, L.BOUNTY_SETTING_CHECK_X, y) else '未勾'}，"
                     f"想要 {'勾' if want else '不勾'}），下次运行再试")
    if changed:
        log.info(f"  悬赏：自动接受档位改成 {'/'.join(HIGH_QUALITIES)}（改了 {changed} 行）")
    else:
        log.info(f"  悬赏：自动接受档位已是 {'/'.join(HIGH_QUALITIES)}，无需改动")
    ui.press(L.BOUNTY_SETTINGS_CLOSE, 200, expect="none")
    ui.wait(1.0)
    return True


def bounty_points(im):
    """读顶部「悬赏积分 N / M」，返回当前积分数。

    2026-11-06：原来走 `ocr.read_all_numbers(mask="pale_soft")`，实测在
    `bounty_page/bounty_points/bounty_accept/bounty_busy` 四张真机帧上全是 None
    （数字是米白细字，14×20 模板匹配不到），导致日志一路「积分读不出来，
    按单次点击接取」。改用 textocr 后这四张帧都稳定读出 `2116/26000`、
    `1068/26000`、`5908/26000`、`1956/26000`，置信度 0.999。
    """
    from .. import ocr, textocr

    if textocr.available():
        nums: list[int] = []
        for text, _c, _bb, _sc in textocr.read_lines(im, L.BOUNTY_POINTS_BOX):
            frac = textocr.read_fraction(text)
            if frac:
                return frac[0]
            t = text.strip().replace(",", "")
            if t.isdigit():
                nums.append(int(t))
        # OCR 会把「2116/26000」切成两行（'2116' + '26000'），左小右大，
        # 取小的那个当当前积分；顺序不保证，所以取 min。
        if nums:
            return min(nums)
        # 有 textocr 就不再用模板 OCR 兜底：设置页同样落在这个框里，
        # 模板 OCR 会在那儿读出一个凭空的「8」，比 None 更危险。
        return None
    nums = ocr.read_all_numbers(im, L.BOUNTY_POINTS_BOX, mask="pale_soft")
    return nums[0] if nums else None


def bounty_in_progress(im) -> int:
    """正在进行的悬赏数 = 右列按钮里「加速」出现的次数。

    2026-11-11：用户 m18005 说「点刷新才会消耗积分接取任务」——实测刷新确实会自动接一单
    （积分 8568 → 6768 那次），但脚本只统计手动点「接受」的次数，于是报「接取 0」。
    这里用「进行中的行数」前后差作为刷新自动接取的证据，不猜。
    """
    try:
        txt = textocr.read_text(im, L.BOUNTY_ROWS_BTN_BOX)
    except Exception:
        return 0
    return txt.count("加速")


def bounty_diamonds(im):
    """读悬赏页顶栏钻石（悬赏页顶栏跟主城位置不同，实测框 65,15,160,60）。

    2026-11-06：同 bounty_points，改 textocr 优先——框里还有一个「+」，
    所以只取纯数字行，别把「+」当读数。
    """
    from .. import ocr, textocr

    if textocr.available():
        for text, _c, _bb, _sc in textocr.read_lines(im, L.BOUNTY_DIAMOND_BOX):
            t = text.strip().replace(",", "")
            if t.isdigit():
                return int(t)
    nums = ocr.read_all_numbers(im, L.BOUNTY_DIAMOND_BOX, mask="dim_yellow")
    return nums[0] if nums else None


def _paid_icon(im, x: int, y: int) -> bool:
    """按钮左边有没有青色钻石图标（「💎50加速」「💎20扫荡」这类要花钻石的按钮）。

    2026-10-31 录像实测：已接取的悬赏行右侧是「💎50加速」，按钮底色和金「接受」
    几乎一样，只有左边多了颗青色钻石——必须靠这个图标区分，否则会花钻石加速。
    """
    for dx in range(-70, -14, 4):
        for dy in range(-20, 21, 4):
            xx = max(0, min(im.width - 1, x + dx))
            yy = max(0, min(im.height - 1, y + dy))
            R, G, B = im.getpixel((xx, yy))
            if G > 165 and (G - R) > 25 and B > 140 and R < 205:
                return True
    return False


def _accept_high_rows(ui, info, accept_cost: int = 2000) -> None:
    """接悬赏：行内「接受」→「任务详情」面板 →「派遣」才算接上（会扣积分）。

    2026-11-10 真帧（logs/screens/p3_1_16.png）：点「接受」只弹出「任务详情」
    （上阵位 / `14972/1800` / `达成要求` / 底部「派遣」），真正扣积分接单的是「派遣」。
    旧实现点完「接受」就按「行变化」记一次，实际一单都没接上（日志里积分 5 轮不变）。

    策略：四行里凡是有金色「接受」、且不是「加速」（要钻石）的，逐行走两步接单；
    积分不足以支付某一单时停下（读不到积分时只接一单就收，绝不连点）。
    """
    page = BountyPage(ui)
    pts = info.get("points")
    if pts is not None and pts < accept_cost:
        log.info(f"  悬赏：积分 {pts} < 接取 {accept_cost}，跳过接取（点了也不会有反应）")
        return
    seen: list[str] = []
    for idx, y in enumerate(L.BOUNTY_ROWS, start=1):
        # 2026-11-15：每一行动手前先确认没有残留的「是否消耗 ?N 加速…」钻石确认框。
        # f42 21:36 就是这个框压着，下一行的「接受」坐标 (565,762) 正好落在金色
        # 「加速」上，白扣 10 钻、日志只报一句「钻石少了对不上」。
        if ui.dismiss_diamond_prompt():
            log.info("  悬赏：先点掉残留的「消耗钻石加速」确认框，再继续看下一行")
        im = ui.screen("bounty_rows")
        q = bounty_quality(im, y)
        seen.append(q or "未识别")
        if not vision.is_gold(im, L.BOUNTY_ACCEPT_X, y, r=16):
            log.info(f"  悬赏：第 {idx} 行（{q or '未识别'}）没有金色「接受」（已在进行中或已接满），跳过")
            continue
        if _paid_icon(im, L.BOUNTY_ACCEPT_X, y):
            log.info(f"  悬赏：{q or '未识别'} 已在进行中（「加速」要钻石），跳过")
            continue
        ok, spent, why = page.accept_row(y, label=f"{q or 'row'}")
        if ok:
            info["accepted"] += 1
            if spent:
                info["spent_points"] = int(info.get("spent_points") or 0) + int(spent)
                if info.get("points") is not None:
                    info["points"] = max(0, int(info["points"]) - int(spent))
            log.info(f"  悬赏：接取 {q or '未识别'} ×{info['accepted']}（{why}，"
                     f"花积分 {spent}，剩余约 {info.get('points')}）")
            continue
        log.info(f"  悬赏：{q or '未识别'} 这一单没接上（{why}），继续看下一行")
        if info.get("points") is None:
            # 积分读不出来时只尝试一单，避免反复点空/重复下单
            log.info("  悬赏：积分不可读，本轮最多只尝试一单，收手")
            break
    if info["accepted"] == 0:
        log.info(f"  悬赏：四个槽位的品质是 {'/'.join(seen)}，本轮一单都没接上"
                 f"（积分 {info.get('points')}）")
    else:
        log.info(f"  悬赏：本轮共接取 {info['accepted']} 单，共花积分 {info.get('spent_points', 0)}"
                 f"（剩余约 {info.get('points')}）")


def claim_bounty_rewards(ui, limit: int = 3) -> int:
    """底栏「一键领取」：把已完成的悬赏一次领掉（免费）。

    2026-11-06 实机：底栏左侧那颗按钮在「快速接受」↔「一键领取」之间切换——
    有已完成的悬赏时它是「一键领取」（OCR 中心 (403,1229)），领完变回「快速接受」。
    领完会弹「获得奖励」浮层，点空白关掉。这步顺带把设置齿轮的位置让出来
    （否则点齿轮会点在「一键领取」上，弹出奖励浮层而不是设置弹窗）。
    """
    n = 0
    for _ in range(limit):
        im = ui.screen("bounty_claim")
        if "一键领取" not in _bottom_text(im):
            break
        ui.press(L.BOUNTY_CLAIM_ALL, 250, label="bounty_claim_all", expect="none")
        ui.wait(2.0)
        ui.press(L.BLANK, 150, expect="none")      # 关「获得奖励」浮层
        ui.wait(1.0)
        after = ui.screen("bounty_claim_after")
        if "一键领取" in _bottom_text(after):
            log.warn("  悬赏：点了「一键领取」底栏仍是它，收手（奖励面板可能没关掉）")
            break
        n += 1
        log.info(f"  悬赏：一键领取已完成悬赏 ×{n}")
    return n


def accept_bounties(ui, limit: int = 8, allow_refresh: bool = False,
                    max_refreshes: int = 1, accept_cost: int = 2000,
                    sync_filter: bool = False, diamonds: int | None = None) -> dict:
    """悬赏：只接史诗/传说/神话，点数不足时不刷新；刷新会自动接取勾选档次。

    用户规则（2026-10-30）：
      - 只接史诗、传说、神话三个档次；
      - 接取其实在点「刷新」时由游戏自动完成（设置里勾选自动接受），
        脚本只要注意**积分不够时别再刷新**。
    2026-11-04 实测：一次刷新扣 2000 积分 + 30 钻石；旧版空点补偿重试
    连点 3 次刷新，一次运行扣了 90 钻石/6000 积分，故刷新改为单次点击。
    2026-11-04 再次收紧：刷新默认**关闭**（花 30 钻，违反「只做免费动作」），
    只有调用方显式 allow_refresh=True（且过 may_spend）才会刷。

    2026-11-10 用户指正（m18005）：「一直点开设置刷新界面没用，要点刷新才会消耗积分
    接取任务，这里允许使用钻石刷新。」→ 不再打开设置弹窗（`sync_filter` 默认 False），
    主路径改成点底栏「刷新」；钻石刷新按 `bounty_refresh` 类别放行（见 BountyTask）。
    """
    info = {"accepted": 0, "refreshes": 0, "claimed": 0, "points": None,
            "diamonds_before": None, "diamonds_after": None}
    page = BountyPage(ui)
    if not page.enter():
        MainCity(ui).ensure()
        return info
    im = ui.screen("bounty")
    info["diamonds_before"] = bounty_diamonds(im)
    info["points"] = bounty_points(im)
    if info["points"] is None:
        # 2026-11-10 实测：悬赏列表会保留上次的滚动位置，滚下去以后顶部的
        # 「积分」数字就跑出 OCR 框 (270,493,470,517) 了。先把列表滚回顶部再读一次。
        for _ in range(2):
            ui.dev.scroll_up(360, 1000, 400, 500)
            ui.wait(0.8)
        im = ui.screen("bounty_top")
        info["points"] = bounty_points(im)
        if info["points"] is None:
            log.warn("  悬赏：滚回顶部后仍没读到积分（OCR 框 270,493,470,517），按单次点击接取，不刷新")
        else:
            log.info(f"  悬赏：滚回顶部后读到积分 {info['points']}")
    if not allow_refresh and max_refreshes > 0:
        log.info("  悬赏：刷新要花 30 钻，本次未授权，跳过刷新（只做免费接取）")

    # 0) 先领掉已完成的悬赏（免费）：顺带把设置齿轮的位置让出来
    info["claimed"] = claim_bounty_rewards(ui)

    # 2026-11-10 用户指正：设置弹窗那条路没用（它只是勾「自动接受档位」，
    # 真正消耗积分接取任务的是下面点「刷新」）。默认不再打开它。
    if sync_filter:
        ensure_bounty_filter(ui)
    else:
        log.info("  悬赏：跳过「自动接受」设置弹窗（用户规则：直接点刷新接取）")

    # 1) 当前列表里已是高品质且可接的，直接接下（普通/稀有绝不点）
    _accept_high_rows(ui, info, accept_cost)

    # 2) 刷新（会自动接取勾选档次）：积分不够「刷新+接取」两笔钱时不刷
    while allow_refresh and info["refreshes"] < max_refreshes:
        ui.wait(0.8)
        before = ui.screen("bounty_before_refresh")
        pts = bounty_points(before)
        info["points"] = pts
        if pts is not None and pts < accept_cost + 2000:
            log.info(f"  悬赏：积分 {pts} < 刷新2000+接取{accept_cost}，不再刷新（刷新也接不了）")
            break
        if pts is None and info["refreshes"] >= 1:
            # 积分读不出来时只做「每日第一次刷新」（必出传说+），之后不冒险再花钻石
            log.warn("  悬赏：积分不可读，只刷新一次（每日首刷必出传说+），不再继续")
            break
        # 底栏文案先说清这一刷是免费还是花钻（用户 m18005 允许钻石刷新）
        bar = _bottom_text(before)
        free = "免费" in bar
        if not free:
            # 底栏此时是「30刷新」这种文案：先读单价，再和主城钻石比大小
            m_cost = re.search(r"(\d{1,4})\s*刷新", bar.replace(" ", ""))
            need = int(m_cost.group(1)) if m_cost else None
            if need is not None and diamonds is not None and need > diamonds:
                log.info(f"  悬赏：这一刷要 {need} 钻，主城只有 {diamonds} 钻 → 不刷新"
                         f"（点了也不会有反应）")
                break
            if need is None:
                # 2026-11-20 审计 CRITICAL：原来只判「单价和钻石都读不到」才收手，
                # 于是「单价读不到 + 主城钻石读得到」照样点刷新 = 不知价格就付款，
                # 而且预算闸用的是 30 钻的估价。现在一律不刷。
                log.info("  悬赏：读不到刷新单价 → 不刷新（不知价格就不花钻）")
                break
            log.info(f"  悬赏：底栏是「{bar.strip()[:12]}」→ 这一刷要花 "
                     f"{need if need is not None else '?'} 钻（主城 {diamonds}，用户已授权）")
        ip0 = bounty_in_progress(before)
        # 单次点击，expect="none" 不做拟补偿；旧版 ±8/±16 重试会连刷 3 次
        ui.press(L.BOUNTY_REFRESH, 250, label="bounty_refresh", expect="none")
        ui.wait(2.6)
        after = ui.screen("bounty_refresh")
        if vision.dialog_confirm(after):
            # 2026-11-10：确认框要么是「是否花费 30 钻刷新」，要么是积分不足提示。
            # 先读正文：含「刷新」才确认（用户授权花钻），否则当作拦截、取消退出。
            txt = ""
            try:
                from .. import textocr
                txt = textocr.read_text(after, L.BOUNTY_REFRESH_DIALOG) or ""
            except Exception:
                txt = ""
            flat = txt.replace(" ", "")
            if "刷新" in flat:
                pos = vision.gold_button_bands(after, (300, 700, 620, 900))
                if pos:
                    ui.press(pos[0][:2], 220, label="bounty_refresh_confirm", expect="none")
                    log.info(f"  悬赏：确认花钻刷新（弹窗「{flat[:24]}」）")
                    ui.wait(2.6)
                    after = ui.screen("bounty_refresh_ok")
                else:
                    log.warn("  悬赏：刷新确认框里没找到金色「确定」，取消本次刷新")
                    _cancel_dialog(ui, after, "bounty_refresh_cancel")
                    break
            else:
                log.info(f"  悬赏：刷新被拦（弹窗「{flat[:24] or '读不出文字'}」），不再刷新")
                _cancel_dialog(ui, after, "bounty_refresh_cancel2")
                break
        if vision.similar(before, after):
            log.warn("  悬赏：刷新按钮单次点击后画面没变（没点中），停止，不重试")
            break
        info["refreshes"] += 1
        if not free:
            # 2026-11-10 ：用户 m18005 已授权钻石刷新（类别 bounty_refresh）。
            # 这里把每次实际单价记下来，收尾用它对账。
            info.setdefault("paid_refreshes", 0)
            info["paid_refreshes"] += 1
            info.setdefault("paid_cost", 0)
            info["paid_cost"] += int(need or 0)
        log.info(f"  悬赏：刷新 ×{info['refreshes']}（本次{'免费' if free else '花钻'}）")
        if not free and diamonds is not None:
            d_now = bounty_diamonds(after)
            if d_now is None:
                log.info("  悬赏：刷新后读不到主城钻石，这一刷没法对账，不再继续刷新")
                break
            if diamonds - d_now != int(need or 0):
                log.warn(f"  悬赏：刷新弹窗写 {need} 钻，主城钻石实际 {diamonds}→{d_now}"
                         f"（扣了 {diamonds - d_now}），停止继续刷新，收尾统一对账")
                break
            diamonds = d_now
        # 刷新后那一帧常常还在动画里 → 积分读成 None；重试 3 次再认
        pts2 = None
        for _ in range(3):
            pts2 = bounty_points(after)
            if pts2 is not None:
                break
            ui.wait(1.0)
            after = ui.screen("bounty_refresh_re")
        info["points"] = pts2
        ip1 = bounty_in_progress(after)
        if ip1 > ip0:
            info["auto"] = int(info.get("auto", 0) or 0) + (ip1 - ip0)
            log.info(f"  悬赏：刷新后自动接取 {ip1 - ip0} 单（进行中 {ip0} → {ip1}）")
        log.info(f"  悬赏：刷新后积分 {info['points']}（每次刷新扣 {accept_cost} 并自动接取）")
        _accept_high_rows(ui, info, accept_cost)      # 自动接取没成功时补一次

    # 收尾读积分：列表可能被滚过，先滚回顶部再读（否则整轮报「积分 None」）
    if info.get("points") is None:
        for _ in range(2):
            ui.dev.scroll_up(360, 1000, 400, 500)
            ui.wait(0.8)
        info["points"] = bounty_points(ui.screen("bounty_end_top"))
    im_end = ui.screen("bounty_end")
    info["diamonds_after"] = bounty_diamonds(im_end)
    d0, d1 = info["diamonds_before"], info["diamonds_after"]
    if d0 is not None and d1 is not None and d1 < d0:
        spent = d0 - d1
        n_paid = int(info.get("paid_refreshes", 0) or 0)
        expect = int(info.get("paid_cost", 0) or 0)
        if n_paid and spent == expect:
            # 2026-11-10 用户 m18005 明确授权钻石刷新 → 这是计划内的花费，不是异常
            log.info(f"  悬赏：钻石 {d0} → {d1}（花钻刷新 {n_paid} 次，共 {spent}，"
                     f"用户已授权）")
        else:
            log.warn(f"  悬赏：钻石 {d0} → {d1}（少了 {spent}），"
                     f"与授权刷新 {n_paid} 次（应 {expect}）对不上，请核对")
    ui.press(L.BOUNTY_BACK, 250, expect="none")
    ui.wait(1.2)
    MainCity(ui).ensure()
    return info


class ClaimDailyTask(BaseTask):
    name = "claim"
    title = "日常/周常/成就/历练 领奖 + 活跃宝箱"
    category = "reward"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = MainCity(ui).open_daily()

        # 日常（页面会记住上次停留的页签，必须显式切回）
        page.switch(L.TAB_DAILY_MAIN, expect="daily")
        if not page.at_daily():
            log.warn("  日常页没打开（标题不对），退回去重试一次")
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.0)
            page = MainCity(ui).open_daily()
            page.switch(L.TAB_DAILY_MAIN, expect="daily")
            if not page.at_daily():
                MainCity(ui).ensure()
                return TaskResult.fail("进不去日常页")
        claimed = page.claim_all()
        # 2026-11-03：页面支持「一键领取 + 自动置顶」，领完列表自动回到顶部，
        # 只补扫顶部一屏（不再多滚，滚动反而会把「领取」滚到屏幕外）。
        daily_rows = page.claim_rows(1)
        chests = page.claim_chests(L.DAILY_CHESTS)

        # 周常/成就/历练：切页失败 → 回退主城重进日常页 → 再判一次，仍失败才跳过
        def _tab_or_reenter(page, tab, label: str, expect: str) -> tuple[object, bool]:
            if page.switch(tab, expect=expect):
                return page, True
            log.warn(f"  日常：{label}页切换失败，回退主城重进日常页再判一次")
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.2)
            p2 = MainCity(ui).open_daily()
            if p2.switch(tab, expect=expect):
                log.info(f"  日常：{label}页重进后切换成功")
                return p2, True
            log.warn(f"  日常：{label}页第二次仍失败，跳过（页签点击/标题模板均未通过）")
            return p2, False

        page, switched = _tab_or_reenter(page, L.TAB_WEEKLY, "周常", "weekly")
        w_chests = page.claim_chests(L.DAILY_WEEKLY_CHESTS) if switched else 0
        w_rows = page.claim_rows(1) if switched else 0

        page, a_ok = _tab_or_reenter(page, L.TAB_ACHIEVE, "成就", "achieve")
        a_rows = page.claim_rows(1) if a_ok else 0

        page, e_ok = _tab_or_reenter(page, L.TAB_GROWTH, "历练", "growth")
        e_rows = page.claim_rows(1) if e_ok else 0


        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        log.info(f"  日常领取 {int(claimed) + daily_rows} / 周常 {w_rows} / 成就 {a_rows} / 历练 {e_rows}")
        stats = {"daily": int(claimed) + daily_rows, "weekly": w_rows,
                 "achieve": a_rows, "growth": e_rows, "chests": chests + w_chests}
        if not any(stats[k] for k in ("daily", "weekly", "achieve", "growth", "chests")):
            # 2026-11-09 假成功审计：四类都没领到也要讲清原因（今天没有可领的），
            # 并用 noop_ok 显式声明「无动作是合法的」
            stats["noop_ok"] = True
        return TaskResult(True,
                          f"日常 {int(claimed) + daily_rows}、周常 {w_rows}、成就 {a_rows}、历练 {e_rows}",
                          stats)


class QuickIdleTask(BaseTask):
    name = "idle"
    title = "快速挂机 + 领挂机收益"
    category = "reward"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        times = int(p.get("times", 3))
        budget = int(p.get("diamond_budget", ctx.cfg.limits.diamond_budget))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        MainCity(ui).tab(L.TAB_CAMPAIGN)
        # 战役页里点「挂机」入口：可能已经在挂机页，点空不算失败
        ui.press(L.IDLE_PET, 250, expect="none")
        ui.wait(2.0)

        # 1) 先领累计挂机收益（金色「领取收益」，领完弹「挂机收益」奖励窗）
        claimed = 0
        im = ui.screen("idle")
        if vision.is_gold(im, *L.IDLE_CLAIM, r=16):
            ui.press(L.IDLE_CLAIM, 250)
            ui.wait(1.8)
            # 2026-11-20 审计 C2：只凭「点之前是金钮」就记领取 = 假成功。
            # 现在点完必须有证据：弹出奖励层（变暗/物品浮层）或金钮熄灭。
            after_claim = ui.screen("idle_claim_after")
            got = (vision.modal_dim(after_claim) or vision.item_popup(after_claim)
                   or not vision.is_gold(after_claim, *L.IDLE_CLAIM, r=16))
            ui.press(L.IDLE_POPUP_BLANK, 150, expect="none")
            ui.wait(1.0)
            if got:
                claimed = 1
                log.info("  挂机收益已领取（点后出了奖励层或金钮熄灭）")
            else:
                log.info("  挂机收益：点了「领取收益」画面没变化，不算领取")
        else:
            log.info("  没有可领取的挂机收益")

        # 2) 买快速挂机次数（「获取更多」金色时才能买）
        done = 0
        # 2026-11-20 审计 C1：这里原来是 free_left = 1（「默认还有免费次数」），
        # OCR 读不到次数时该值保持 1 → need=0 → 预算闸与钻石对账整段被短路，
        # 而按钮其实可能是金色付费钮，于是「真花钱记成免费成功」。现在默认 None
        # （不知道就是不知道），免不免费只看按钮颜色：绿=免费、金=付费。
        free_left = None
        spent = 0
        for _ in range(times):
            im = ui.screen("idle")
            # 2026-11-10：免费次数那条路按钮是**绿色**（真帧 136,993-334,1073），
            # 只有花钻买次数时才是金色。旧码只认金色，免费那次永远不点。
            free_btn = vision.is_green(im, *L.IDLE_MORE, r=16)
            paid_btn = vision.is_gold(im, *L.IDLE_MORE, r=16)
            # 2026-11-18 03:18 空点 (235,1033)：今日剩余次数为 0 时「获取更多」是
            # **灰掉的土黄**（真帧像素 (202,173,130)），旧码用 gold_bands_any 兜底
            # 会把这条灰带当成金钮按下去 → diff=0.000 空点 + 4 个补偿点白赔 8s。
            # 现在只认真金/真绿：金带必须质心本身 is_gold，否则不动手。
            if not (free_btn or paid_btn):
                bands = vision.gold_bands_any(im, L.IDLE_MORE_BOX)
                pt = None
                if bands:
                    pt = vision.gold_band_point(im, L.IDLE_MORE_BOX)
                # 再加一道金色占比：真金按钮 gold_ratio ≥0.33（领取收益 0.477、
                # 特权购买块 0.335），灰化土黄那条是 0.000。两道都过才敢按。
                if pt is not None and vision.gold_ratio(im, L.IDLE_MORE_BOX) >= 0.25:
                    paid_btn = True
                else:
                    log.info("  快速挂机：「获取更多」现在是灰的（今日剩余次数 0），不点")
                    break
            if textocr.available():
                m = re.search(r"(?:免费|今日剩余)?次数[:：]?\s*(\d+)",
                              textocr.read_text(im, L.IDLE_FREE_TEXT))
                if m:
                    free_left = int(m.group(1))
            if free_left is not None and free_left <= 0 and not paid_btn:
                log.info("  快速挂机：今日剩余次数 0（按钮灰化），今天不买了")
                break
            if free_btn and not paid_btn:
                need = 0                      # 绿色 = 真免费，不涉及钻石
            else:
                need = 50 if done == 0 else 100   # 金色 = 付费，按游戏标价记账
            # 2026-11-03 用户反馈「用钻石买刷怪次数被乱用」：付费次数一律走全局闸门，
            # runtime.allow_diamonds=false（默认）时直接停，不再靠 diamond_budget 兜底。
            # 两道闸：先看单任务预算（第 251 行 budget），再走全局 allow_diamonds 开关。
            if need and spent + need > budget:
                log.info("  钻石预算不够，停止快速挂机")
                break
            if need and not self.may_spend(ctx, "快速挂机次数", need, kind="attempt"):
                log.info(f"  快速挂机第 {done + 1} 次要花 {need} 钻，已按保护策略停止")
                break
            d0 = self.diamonds(im) if need else None
            if not ui.press(L.IDLE_MORE, 250):
                log.info("  快速挂机：点「获取更多」没有反应，停止本次")
                break
            ui.wait(2.4)
            # 购买/收益弹窗底部关闭（可能已被上一轮关掉）
            ui.press(POPUP_CLOSE_BOTTOM, 150, expect="none")
            ui.wait(0.9)
            if need:
                # 2026-11-09 假成功审计：花钻必须自证（钻石前后差 ≥ need）
                d1 = self.diamonds(ui.screen("idle_paid"))
                if d0 is None or d1 is None or d1 > d0 - need:
                    log.info(f"  快速挂机：钻石读数对不上（{d0} → {d1}，本次应花 {need}），"
                             f"不把这一次算进次数")
                    break
                log.info(f"  快速挂机：钻石 {d0} → {d1}（-{need}），确认真的买到了")
            done += 1
            if free_left is not None and free_left > 0:
                free_left -= 1
            elif need:
                spent += need
            log.info(f"  快速挂机 {done}（累计 {spent} 钻）")

        ui.press(L.IDLE_POPUP_BLANK, 150, expect="none")
        ui.wait(0.8)
        MainCity(ui).tab(L.TAB_CAMPAIGN)
        MainCity(ui).ensure()

        # 3) 挂机会涨悬赏值：顺手把悬赏按品质规则接一轮
        b = accept_bounties(ui)
        return TaskResult(True,
                          f"挂机 {done} 次、领收益 {'是' if claimed else '否'}、接悬赏 {b['accepted']}",
                          {"times": done, "claimed": claimed, "bounties": b["accepted"]})


class ForgeEnhanceTask(BaseTask):
    name = "forge"
    title = "装备强化"
    category = "upgrade"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        times = int(p.get("times", 1))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = MainCity(ui).open_forge()
        page.star_popup()       # 进铁匠铺常常直接弹「一键升星」
        page.enhance_tab()
        done = 0
        for _ in range(times):
            if not page.enhance_one():
                break
            done += 1
        if not done:
            # enhance_one() 只认「装备槽上的红角标」；一个都没有时要说清是
            # 都强化到顶了还是判据漏了（日志此前只有「强化 0 次」）。
            log.info("  装备强化：四件装备都点过「强化1次」且卡片无变化"
                     "（金币/材料不足或都已到顶）")
        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        stats = {"times": done}
        if not done:
            stats["noop_ok"] = True     # 2026-11-09：没有可强化的装备槽 = 真状态
        return TaskResult(True, f"强化 {done} 次", stats)


class ShopRefreshTask(BaseTask):
    name = "shop"
    title = "日常商店刷新"
    category = "reward"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        times = int(p.get("times", 2))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = MainCity(ui).open_shop()
        done = 0
        for _ in range(times):
            if not page.free_refresh():
                break
            done += 1
        if not done:
            log.info(f"  商店：{times} 次免费刷新一次都没点成（按钮不亮），今天可能已用完")
        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        stats = {"times": done}
        if not done:
            stats["noop_ok"] = True     # 2026-11-09：免费次数用完/未开放 = 真状态
        return TaskResult(True, f"免费刷新 {done} 次", stats)


class GuildDonateTask(BaseTask):
    name = "donate"
    title = "公会捐献"
    category = "reward"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui = ctx.ui
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = MainCity(ui).open_guild()
        status = page.donate_gold()
        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        stats = {"status": status, "donated": status == "done"}
        if status == "no_page":
            # 连捐献面板都没打开 = 真的没做事，不能报 OK
            return TaskResult.fail("公会捐献：捐献面板没打开（OCR 读不到「公会捐献」）", stats)
        if status == "unclear":
            return TaskResult.fail("公会捐献：按钮不金但也没读到「已捐」，无法确认今天的状态", stats)
        msg = "金币捐献成功" if status == "done" else "今天已捐献过（面板写「已捐赠」）"
        return TaskResult(True, f"金币捐献：{msg}", stats)


class GuildTrialTask(BaseTask):
    name = "guild_trial"
    title = "公会试炼"
    category = "combat"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        times = int(p.get("times", 3))
        # 2026-11-03：买挑战次数会花钻石，默认改为关闭；要买必须显式 buy_attempt=true
        # 且 runtime.allow_diamonds=true。
        buy = bool(p.get("buy_attempt", False))
        buy_cost = int(p.get("buy_cost", 20))
        budget = int(p.get("diamond_budget", ctx.cfg.limits.diamond_budget))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        # 2026-11-10：钻石自证必须在主城读（公会页顶栏换成公会币，CITY_DIAMOND_BOX 在那里读不到）
        d_start = self.diamonds_stable(ui, "gtrial_d0") if buy else None
        page = MainCity(ui).open_guild()
        page.trial_enter()
        if not page.trial_page():
            log.info("  公会试炼没进去，退回去重试一次")
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.0)
            page.trial_enter()
        if not page.trial_page():
            MainCity(ui).ensure()
            return TaskResult.skip("进不去公会试炼")
        done = spent = 0
        bought_n = 0
        for _ in range(times):
            if ui.handle_interruptions():
                continue
            if not page.trial_challenge():
                if not buy or spent + buy_cost > budget:
                    log.info("  公会试炼次数用完")
                    break
                if not self.may_spend(ctx, "公会试炼次数", buy_cost, kind="attempt"):
                    log.info(f"  公会试炼买次数需 {buy_cost} 钻，已按保护策略停止")
                    break
                if page.trial_buy_attempt():
                    # 2026-11-10：页内不再读钻石（顶栏是公会币），只数买了几次；
                    # 真账在收尾回主城后用「主城钻石前后差」一次性核对。
                    bought_n += 1
                    ui.wait(1.2)           # 买完的提示/动画先落定，再找金色「挑战」
                    if not page.trial_challenge():
                        log.info("  公会试炼次数仍不足，停止")
                        break
                else:
                    log.info("  公会试炼次数用完（购买未成功）")
                    break
            # 布阵 → 战斗 → 跳过 → 结算（保存 → 确定）
            im = ui.screen("gtrial_dep")
            if vision.is_green(im, *L.DEPLOY, r=18):
                ui.press(L.DEPLOY, 200, expect="none")
                ui.wait(1.0)
            ui.press(L.FIGHT, 200, label="fight", expect="none")
            # 2026-11-08：轮询式跳过（有跳过就用，没有就等结算）。
            # 2026-11-10 实测：公会试炼这一模式**没有跳过键**，一轮 60~110s，
            # 这里必然超时——超时不是错，后面 trial_save 会继续守着结算页。
            ui.battle_finish(label="gtrial_skip", timeout=14.0)
            ui.wait(1.6)
            if page.trial_save():
                done += 1
                log.info(f"  公会试炼 {done}")
            else:
                log.info("  公会试炼：这一局没等到结算/保存（不计入）")
                break
        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        if bought_n:
            d_end = self.diamonds_stable(ui, "gtrial_d1")
            if d_start is None or d_end is None:
                log.warn(f"  公会试炼：买了 {bought_n} 次，但主城钻石前后对比缺证"
                         f"（{d_start}→{d_end}），本次不记花费")
            else:
                spent = d_start - d_end
                expect = bought_n * buy_cost
                if spent < expect:
                    log.warn(f"  公会试炼：买了 {bought_n} 次（应花 {expect}），"
                             f"但主城钻石只少了 {spent}（{d_start}→{d_end}），按实际差值记")
        return TaskResult(True, f"公会试炼 {done} 次（{spent} 钻）",
                          {"fights": done, "diamonds": spent, "bought": bought_n})


class GuildBeastTask(BaseTask):
    """公会圣兽：每天中午 12 点后开放，每日 5 次挑战（打伤害，结算要手动保存）。

    流程与公会试炼相同：挑战 → 布阵（一键上阵/战斗）→ 跳过 → 结算「保存」→ 胜利「确定」。
    另外圣兽页右侧「参与奖励」钻石图标带红点时顺手领掉。
    """

    name = "beast"
    title = "公会圣兽"
    category = "combat"

    @staticmethod
    def _times_left(im):
        """读「今日剩余次数：N」。读不到返回 None（按旧逻辑继续）。

        2026-11-06 实测：次数为 0 时底部「挑战」按钮**依旧是亮金色**，点下去游戏
        静默忽略（diff 0.000），旧逻辑靠「点完没出现绿色上阵按钮」反推次数不足，
        会白等一整套空点补偿（实测 8 秒），最后还返回 `OK 公会圣兽 0 次`。
        现在直接读文字，0 次就早退并 skip。
        """
        from .. import textocr
        if not textocr.available():
            return None
        return textocr.read_remain(textocr.read_text(im, L.BEAST_TIMES_TEXT))

    @staticmethod
    def _open_text(im) -> str:
        """读副标题：平时是静态开放时间「①每日12:00开启」，未开放时是倒计时。

        2026-11-07 实测：每天 00:00 次数重置成 5，但活动 12:00 才开；这期间
        「今日剩余次数：5」+ 底部「挑战」亮金色全都成立，点下去却 diff 0.000
        （游戏静默忽略），旧逻辑要白等 4 个补偿点（约 8 秒）才靠「没有绿色上阵按钮」反推。
        """
        from .. import textocr
        if not textocr.available():
            return ""
        return textocr.read_text(im, L.BEAST_OPEN_TEXT)

    @staticmethod
    def _not_open(head: str) -> bool:
        """副标题是不是真的在倒计时（活动没开）。

        2026-11-08 21:55 实测（run16，帧 `beast_head_1499.png`）：副标题读作
        `①每日12:00开启` —— 这是**静态开放时间**，不是倒计时；同帧
        `今日剩余次数 = 0`。旧判据 `"开启" in head` 命中静态文案，于是把
        「今天已经打完 5 次」误报成「圣兽未开放」。
        真倒计时长这样：`开启倒计时：3时25分`（含「时」「分」）。
        """
        if not head:
            return False
        # 2026-11-10 实测（帧 `logs/probe_beast_page.png`）：活动期间副标题写的是
        # 「结束倒计时：6时18分」——这是「还有多久结束」，不是「还没开始」。
        # 旧判据只要含「倒计时」就当未开放，会把正常开放期误判成休市。
        if "结束倒计时" in head:
            return False
        if "开启倒计时" in head:
            return True
        if "倒计时" in head and "开启" in head:
            return True
        return "时" in head and "分" in head and "开启" in head

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        times = int(p.get("times", 5))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        page = MainCity(ui).open_guild()
        page.beast_enter()
        if not page.beast_page():
            log.info("  公会圣兽没进去，退回去重试一次")
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.0)
            page.beast_enter()
        if not page.beast_page():
            MainCity(ui).ensure()
            return TaskResult.skip("进不去公会圣兽")
        if not page.beast_ready():
            log.info("  公会圣兽未开放（每天 12 点后开始）或次数已用完")
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.0)
            MainCity(ui).ensure()
            return TaskResult.skip("圣兽未开放")

        head = self._open_text(ui.screen("beast_head"))
        # 2026-11-08 21:55 实测（run16）：副标题平时写的是静态开放时间
        # 「①每日12:00开启」，只有真正没开放时才写「开启倒计时：N时N分」。
        # 旧判据 `"开启" in head` 会把静态文案当成倒计时 → 明明开着（只是今天
        # 次数已用完）也报「圣兽未开放」，归因错、还掩盖了「次数 0」这个真状态。
        counting = self._not_open(head)
        if counting:
            # 次数刚重置、按钮是亮的，但活动还没开：点了也只会静默忽略。
            log.info(f"  公会圣兽还没开放（{head}），金按钮点了也没反应，收手")
            ui.press(L.BACK, 250, expect="none")
            ui.wait(1.0)
            MainCity(ui).ensure()
            return TaskResult.skip(f"圣兽未开放（{head}）")

        done = 0
        spare = None
        for _ in range(times):
            ui.handle_interruptions()
            im = ui.screen("beast")
            spare = self._times_left(im)
            if spare == 0:
                # 次数为 0 时「挑战」照旧是亮金色，点下去只飘一行「今日剩余挑战次数不足」，
                # 之后再靠「没有绿色的上阵按钮」反推，就会白等一整套补偿点（实测 8 秒）。
                log.info("  公会圣兽今日剩余次数 0（金按钮可点但游戏静默忽略），不再挑战")
                break
            if not vision.is_gold(im, *L.BEAST_GO, r=16):
                log.info("  公会圣兽次数用完")
                break
            ui.press(L.BEAST_GO, 250, expect="none")   # 进没进布阵页由下面的绿按钮判定
            ui.wait(2.6)
            im = ui.screen("beast_dep")
            if not vision.is_green(im, *L.DEPLOY, r=18):
                # 兜底：次数为 0 时按钮仍是金色，点下去只飘一行「今日剩余挑战次数不足」
                log.info("  公会圣兽次数不足，停止")
                break
            ui.press(L.DEPLOY, 200, expect="none")
            ui.wait(1.0)
            ui.press(L.FIGHT, 200, label="fight", expect="none")
            # 圣兽也没有跳过键、一轮 60~110s，这里超时是正常的
            ui.battle_finish(label="beast_skip", timeout=14.0)
            ui.wait(1.6)
            # 保存 → 胜利「确定」（和试炼同一套结算界面）。
            # 2026-11-10：只有真的点到「确定」才算打完，否则日志里会出现
            # 「公会圣兽 N」而实际一局都没保存。
            if not page.trial_save():
                log.info("  公会圣兽：这一局没等到结算/保存（不计入）")
                break
            done += 1
            log.info(f"  公会圣兽 {done}")

        im = ui.screen("beast_prize")
        if vision.button_badge(im, L.BEAST_PRIZE_BOX):
            ui.press(L.BEAST_PRIZE, 250)
            ui.wait(1.6)
            ui.press(L.BLANK, 150, expect="none")
            ui.wait(0.8)
            log.info("  参与奖励已领取")

        ui.press(L.BACK, 250, expect="none")
        ui.wait(1.0)
        MainCity(ui).ensure()
        if done:
            return TaskResult(True, f"公会圣兽 {done} 次", {"fights": done})
        if spare == 0:
            return TaskResult.skip(f"今日剩余次数已用尽（0/{times}）")
        return TaskResult.skip("没有可挑战的次数（入口未亮）")


class BountyTask(BaseTask):
    name = "bounty"
    title = "悬赏任务（只接史诗/传说/神话）"
    category = "reward"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        limit = int(p.get("times", 8))
        max_refresh = int(p.get("max_refreshes", 3))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        # 2026-11-10 用户规则：刷新才是「消耗积分接取任务」的那一步，且允许钻石刷新。
        # 类别 bounty_refresh 在 RuntimeConfig.diamond_kinds 白名单里（其余类别仍禁止）。
        paid_ok = max_refresh > 0
        if paid_ok:
            paid_ok = self.may_spend(ctx, f"悬赏刷新 ×{max_refresh}", 30 * max_refresh,
                                     kind="bounty_refresh")
        # 刷新要花钻石：先在主城读一次「现在的钻石」，够了才刷（读不到就不刷）
        d0 = self.diamonds_stable(ui, "bounty_d0")
        info = accept_bounties(ui, limit, allow_refresh=paid_ok,
                               max_refreshes=max_refresh,
                               sync_filter=bool(p.get("sync_filter", False)),
                               diamonds=d0)
        auto = int(info.get("auto", 0) or 0)
        tail = f"（刷新自动接 {auto}）" if auto else ""
        return TaskResult(True,
                          f"悬赏：接取 {info['accepted']}{tail}、领取 {info['claimed']}、"
                          f"刷新 {info['refreshes']}、积分 {info['points']}",
                          info)


class CampaignTask(BaseTask):
    name = "campaign"
    title = "主线战役 + 关卡奖励"
    category = "combat"

    @staticmethod
    def _claim_reward(ui) -> int:
        """右侧钻石图标的「通关主线」奖励：打开面板，把里程碑行里带红点的领掉。"""
        # 2026-11-10：旧版要求「地图右侧入口图标带红点」才开面板，而实测该图标
        # 红点恒为 0（红像素 0）—— 里程碑早就能领了却一次都没开过面板。
        # 现在无条件开面板，用里程碑图标右上角的红「!」判「还能不能领」。
        ui.press(L.CAMPAIGN_REWARD_ICON, 250, label="camp_reward_icon", expect="none")
        ui.wait(1.8)
        panel = ui.screen("camp_reward_panel")
        from ..pages import Page  # noqa: F401  (claim_badge_icons 在 Page 上)
        n = CampaignTask._panel_claim(ui, panel)
        ui.press(L.CAMPAIGN_BLANK, 150, expect="none")
        ui.wait(1.0)
        return n

    @staticmethod
    def _panel_claim(ui, panel) -> int:
        """在已打开的通关奖励面板里领里程碑（红角标 → 点图标本体）。"""
        from ..pages import Page

        class _Claimer(Page):  # 借用 Page.claim_badge_icons 的截图/点击能力
            name = "camp_claim"

        return _Claimer(ui).claim_badge_icons(
            L.CAMPAIGN_BADGE_BAND, L.CAMPAIGN_BADGE_DX, L.CAMPAIGN_BADGE_DY,
            label="camp_reward", tries=6)

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        max_fights = int(p.get("max_fights", 30))
        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        MainCity(ui).tab(L.TAB_CAMPAIGN)

        fought = 0
        locked = False
        defeat = False
        engaged = False
        # 2026-11-19 假成功审计 C1：进过布阵页 ≠ 打过一场。点「战斗」本身
        # 只要求 expect="none"（不校验画面），所以这里先记 pending，等真的
        # 看到战斗帧或结算页再把 pending 结算成 fought。
        pending = 0
        last_action = ""
        stage_tries = 0
        stage_dialog = 0      # 「下一章」切换时的过渡弹窗，第一次不当成等级封锁
        block_reason = ""    # 被游戏明说挡住时的原话（如「角斗券已达上限」）
        for _ in range(max(12, max_fights * 6)):
            if fought + pending >= max_fights:
                log.info(f"  主线达到本次场次上限（{max_fights} 场）")
                break
            im = ui.screen("camp_map")
            # 2026-11-08：结算页上叠了「温馨提示：是否保存本次挑战？」时整屏被压暗，
            # classify 只能给 UNKNOWN、金色判据全部失效，主循环会误报
            # 「主线按钮不可用」然后收手（batch2 实测只打 4 关就停，帧 camp_map2_292）。
            # 这里先用两个只看像素的便宜判据当闸门，命中才走公共干扰处理
            # （handle_interruptions 自己还要多抓两帧，不能每轮都白付）。
            # 2026-11-08：「米色弹窗 + 珊瑚『取消』(200,782) + 金色『确定』(465,782)」
            # 这套像素签名背后至少有两种完全不同的提示：
            #   ①「当前英雄布阵未保存，是否保存？」→ 应该点「保存」
            #   ②「当前角斗券已达上限，请前往角斗场挑战」→ 点哪个都只是关窗，
            #     主线今天打不了。旧码把②当成①去点「保存」，于是打 0 场还被
            #     记成「等级未解锁」（run9 实测 19:11:58 帧 ui_9.png）。
            # 两句话都在同一块区域，读一次就能分开。
            if vision.lineup_save_dialog(im):
                tip = ""
                try:
                    tip = textocr.read_text(im, L.CAMPAIGN_TIP_ROI).strip()
                except Exception:  # noqa: BLE001
                    tip = ""
                if any(k in tip for k in ("角斗券", "角斗场", "上限")):
                    log.warn(f"  主线被游戏挡住：「{tip[:40]}」（角斗券满仓，得先去角斗场消耗）")
                    ui.press((200, 782), 180, label="campaign_tip_cancel", expect="none")
                    ui.wait(1.0)
                    block_reason = tip[:40]
                    break
                if ui.handle_interruptions():
                    ui.wait(0.6)
                    continue
            if vision.modal_dim(im):
                if ui.handle_interruptions():
                    ui.wait(0.6)
                    continue
            st = vision.classify(im)
            if st in (State.BATTLE, State.RESULT_DEFEAT, State.RESULT_TOWER,
                      State.RESULT_TREE, State.RESULT_GENERIC, State.RESULT_LEGEND):
                if pending:
                    fought += pending
                    pending = 0
            if st == State.RESULT_DEFEAT:
                defeat = True
                ui.press(L.BLANK, 150, expect="none")
                ui.wait(1.0)
                break
            if st in (State.RESULT_TOWER, State.RESULT_TREE, State.RESULT_GENERIC,
                      State.RESULT_LEGEND):
                # 2026-10-31：战役结算页右侧是金色「下一关」，旧代码只认「确定」，
                # 打赢一关后就卡在结算页（下一轮找不到金色按钮），日志表现为“只打了 1 关”。
                engaged = False
                if vision.is_gold(im, 480, 1100, r=16):
                    ui.press((480, 1100), 250)      # 下一关：继续挑战
                    ui.wait(2.4)
                    last_action = "next"
                    continue
                ui.press((215, 1100), 220)          # 末关只有灰色「确定」，回地图
                ui.wait(2.0)
                last_action = "ok"
                continue
            if st == State.DEPLOY:
                if not engaged:
                    # 先记「待结算」，看到战斗/结算页才变成一次挑战
                    pending += 1
                    engaged = True
                    stage_tries = 0
                    log.info(f"  主线第 {fought + pending} 次进布阵页（等战斗画面确认）")
                ui.press(L.DEPLOY, 200, expect="none")
                ui.wait(1.0)
                ui.press(L.FIGHT, 200, label="fight", expect="none")
                ui.battle_finish(label="campaign_skip", timeout=14.0)
                ui.wait(1.8)
                last_action = "fight"
                continue
            # 2026-11-02：战役地图底部亮着金色「挑战NN-N」、中部又是暗的，
            # battle_page() 会把地图判成「战斗中」，主循环于是无限按「跳过」。
            # 这里先认地图的金色挑战按钮（真战斗页该位置实测不是金色）。
            # 2026-11-08：**章节首领关**。地图底部金钮写的是「挑战首领」，点开后
            # 是「关卡详情」面板（标题「挑战首领」+「本关敌人」+「通关奖励」+ 底部
            # 金色「挑战」）。旧码不认这个面板：每次点「挑战首领」只是开关面板，
            # stage_tries 涨到 4 就收手，日志表现为「主线 0 次（等级未解锁）」——其实是
            # 根本没开打。判据实测互斥（camp_map_1378 地图 / camp_map_1380 面板）：
            # 面板上 CAMPAIGN_GO(360,970) 是金、CAMPAIGN_STAGE_BTN(360,1055) 非金；
            # 地图上正好相反。
            if (vision.is_gold(im, *L.CAMPAIGN_GO, r=18)
                    and not vision.is_gold(im, *L.CAMPAIGN_STAGE_BTN, r=18)):
                engaged = False
                stage_tries = 0
                ui.press(L.CAMPAIGN_GO, 250, label="campaign_go", expect="none")
                ui.wait(2.2)
                last_action = "go"
                continue
            if vision.is_gold(im, *L.CAMPAIGN_STAGE_BTN, r=18):
                from .. import template as Tmpl
                if Tmpl.VI.find(im, "战役_等级解锁.png", 0.85):
                    # 按钮是金色但写的是「126级解锁」——点了只会弹升级推荐，直接收手
                    log.info("  主线被等级挡住（按钮显示 N级解锁）")
                    locked = True
                    break
                engaged = False
                stage_tries += 1
                if stage_tries >= 4:
                    log.info("  主线按钮点了多次都没开打（可能被等级/前置条件挡住），停止")
                    locked = True
                    break
                ui.press(L.CAMPAIGN_STAGE_BTN, 250)
                # 「下一章」会先播转换动画再回到新章节地图，1.8s 不够，容易误判成未知页
                ui.wait(3.0)
                last_action = "stage"
                continue
            if st == State.BATTLE:
                if not engaged:
                    fought += 1
                    engaged = True
                    stage_tries = 0
                    log.info(f"  主线挑战 {fought} 次")
                ui.battle_skip(im)
                ui.wait(3)
                last_action = "skip"
                continue
            if st in (State.DIALOG, State.MAIN_CITY_DIM):
                # 「升级推荐」面板：点完整主线按钮之后弹出来的，说明等级不够了。
                # 2026-11-03 #12：「下一章」切换也有一次过渡弹窗，第一次先关掉再继续，
                # 连续第二次才认定是被等级挡住，否则会把正常的切章误判成“没切成功”。
                ui.press(L.CAMPAIGN_BLANK, 150, expect="none")
                ui.wait(1.4)
                if last_action == "stage":
                    stage_dialog += 1
                    if stage_dialog >= 2:
                        log.info("  主线被等级挡住（升级推荐面板）")
                        locked = True
                        break
                    log.info("  主线：关掉切章过渡弹窗，继续")
                    last_action = ""
                continue
            # 兜底：既不是战斗也不是地图挑战按钮的未知画面
            ui.press(L.CAMPAIGN_BLANK, 150, expect="none")
            ui.wait(1.0)
            im2 = ui.screen("camp_map2")
            if vision.is_gold(im2, *L.CAMPAIGN_STAGE_BTN, r=18):
                continue
            if vision.is_gold(im2, 480, 1100, r=16) or vision.is_gold(im2, 496, 1089, r=16):
                # 结算页还开着（右上金「下一关」）——先打下一关，别当成地图
                ui.press((480, 1100), 250)
                ui.wait(2.0)
                last_action = "next"
                continue
            if vision.lineup_save_dialog(im2):
                log.info("  结算页上叠着「是否保存本次挑战？」——点「保存」再继续")
                ui.press(L.LINEUP_SAVE, 220)
                ui.wait(1.8)
                continue
            log.info("  主线按钮不可用，停止")
            break

        rewards = self._claim_reward(ui)
        MainCity(ui).ensure()
        b = accept_bounties(ui)
        if block_reason:
            state = block_reason
        elif locked:
            state = "等级未解锁"
        else:
            state = "战斗失败" if defeat else "已尽力"
        if pending:
            log.info(f"  主线：还有 {pending} 次进了布阵页但没看到战斗/结算，不计入")
        return TaskResult(True,
                          f"主线挑战 {fought} 次（{state}）、关卡奖励 {rewards}、接悬赏 {b['accepted']}",
                          {"fights": fought, "rewards": rewards, "bounties": b["accepted"],
                           "unconfirmed": pending})
