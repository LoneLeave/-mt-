"""《我叫MT：崛起》全量 ADB 自动化（奖励领取 + 属性提升 + 战斗）

设计目标：可重复运行、与运行前状态兼容。
  - 所有按钮用「长按 200ms」触发（短 tap 在本作里经常不响应）。
  - 每个模块动手前用截图像素判断状态（按钮是不是金色可点/红点是否存在），
    已完成的任务按钮是灰色或绿色，模块会自动跳过，不会空点、不会误买。
  - 所有模块都有 try/except，失败后用 ensure_main_city() 回主城继续。
  - 不触碰任何人民币充值界面（每日特惠、三日直升、超值首充、累充等一律不点）。

用法：
  python full_adb.py --list
  python full_adb.py --dry-run
  python full_adb.py                  # 跑默认全套
  python full_adb.py --only rewards,arena,tower
  python full_adb.py --profile light  # 只领免费奖励 + 一键提升，不打战斗

坐标：720x1280，游戏画面 x∈[28,691]。按钮实际点击位置普遍比视觉中心低 20–40px。
"""
import argparse
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from adb_mumu import adb, shell  # noqa: E402


def press(x, y, ms=220):
    """长按式点击：本作里 50ms 的 input tap 经常不响应，200ms 稳定。"""
    shell(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(ms)}")

OUT = Path(__file__).resolve().parent / "shots"
OUT.mkdir(exist_ok=True)

# ---------- 主城坐标 ----------
SKY = (360, 60)              # 主城顶部是蓝天；其他界面不是
BACK = (88, 1215)            # 左下返回箭头（1205 太靠上时无效）
BLANK = (200, 700)           # 通用「点击空白处关闭」
QUIT_CANCEL = (475, 725)     # 「确认要退出游戏吗?」取消

TAB_MAIN = (110, 1225)
TAB_HERO = (190, 1225)
TAB_TEAM = (270, 1225)
TAB_CAMPAIGN = (370, 1225)
TAB_TRIAL = (470, 1225)
TAB_ARENA = (545, 1225)
TAB_GUILD = (640, 1225)

ICON_WELFARE = (360, 150)
ICON_DAILY_OFFER = (190, 150)
ICON_3DAY = (95, 150)
ICON_HUNDRED = (190, 290)
ICON_HERO_PLAN = (280, 290)
ICON_CHAMPION = (370, 290)
ICON_CROSS = (85, 340)
ICON_REBATE = (190, 340)
ICON_GUILD_RALLY = (590, 150)

BLD_ANCESTOR = (105, 580)
BLD_RESONANCE = (590, 640)
BLD_STAR = (190, 770)
BLD_SUMMON = (370, 800)
BLD_FORGE = (590, 830)
BLD_RELIC = (180, 960)
BLD_SHOP = (470, 1010)
ICON_MAIL = (85, 1005)
ICON_FRIEND = (650, 1005)
ICON_BAG = (650, 1130)
ICON_STRONGER = (650, 855)
RANK_BAR = (150, 1085)

# ---------- 常用按钮 ----------
# 弹窗关闭
X_TOP = (655, 200)

# 军衔
RANK_CLAIM_YS = (752, 882, 990, 1100)
RANK_PROMOTE = (350, 905)
RANK_PROMOTE_OK = (350, 845)

# 好友
FRIEND_GIFT = (490, 968)

# 邮件
MAIL_CLAIM_ALL = (490, 1015)

# 千抽福利
HUNDRED_TABS = [(183, 938), (360, 965), (530, 938)]
HUNDRED_SKIP = (615, 258)
HUNDRED_BACK = (435, 1180)
HUNDRED_TAB_10 = (490, 1090)

# 召唤
SUMMON_ONE = (200, 1090)
SUMMON_TEN = (490, 1090)
SUMMON_RESULT_BACK = (200, 1185)

# 打造（先祖魂匣）
FORGE_ONE = (200, 940)
FORGE_TEN = (490, 905)
FORGE_CONFIRM = (470, 783)
FORGE_BACK = (200, 775)

# 圣物
RELIC_ONEKEY = (615, 1080)
RELIC_BLESS = (615, 150)
RELIC_BLESS_UP = (360, 925)

# 升星
STAR_BATCH = (215, 1095)
STAR_CONFIRM = (360, 1015)
STAR_SINGLE = (515, 1095)

# 铁匠铺
FORGE_TAB_ENHANCE = (500, 1215)
FORGE_TAB_STAR = (615, 1215)
ENHANCE_50 = (360, 1105)
ENHANCE_STAR_ONEKEY = (615, 1085)
ENHANCE_STAR_CONFIRM = (360, 730)

# 共鸣
RESONANCE_AUTO = (615, 720)

# 竞技
ARENA_COLOSSEUM = (360, 490)
ARENA_GLORY = (200, 700)
ARENA_SKIP_BOX = (75, 1100)
COLOSSEUM_DEFENSE_CLOSE = (360, 180)
COLOSSEUM_CHALLENGE_YS = (818, 560, 691, 945, 1070)
COLOSSEUM_BACK = (490, 843)
GLORY_START = (360, 1080)
GLORY_BACK = (490, 843)

# 娜迦秘境
NAGA_CHALLENGE = (360, 1105)
NAGA_RESULT_OK = (360, 1080)

# 争霸赛
CHAMP_REWARD = (615, 905)
CHAMP_QUEST_TAB = (415, 1105)
CHAMP_RANK_TAB = (545, 1105)
CHAMP_CHAT = (280, 1113)
CHAMP_SEND = (615, 1113)
CHAMP_SAVE = (360, 1015)

# 历练（试炼）入口
TRIAL_DUNGEON = (360, 280)
TRIAL_TOWER = (270, 600)
TRIAL_LEGEND = (490, 600)
TRIAL_DEMON = (360, 900)
TOWER_GO = (565, 1070)
LEGEND_GO = (360, 1120)
DEPLOY = (270, 1230)          # 布阵页「一键上阵」实际在 1230
START_FIGHT = (515, 1230)     # 布阵页「战斗」实际在 1230
TOWER_NEXT = (490, 1080)
TOWER_OK = (200, 1080)
LEGEND_OK = (360, 1100)

# 战斗类（来自 daily_adb 的成熟坐标）
TOWER_CHALLENGE = (527, 1090)
AUTO_DEPLOY = (270, 1230)
FIGHT = (527, 1230)
NEXT_FLOOR = (490, 1080)
BATTLE_CONFIRM = (225, 1080)
TREE_CHALLENGE = (360, 1185)
TREE_CONFIRM = (360, 1105)
LEGEND_CHALLENGE = (360, 1130)
LEGEND_CONFIRM = (360, 1090)
GUILD_TRIAL = (210, 630)
GUILD_CHALLENGE = (490, 1185)
GUILD_PLUS = (428, 1095)
GUILD_BUY = (490, 771)
GUILD_CONFIRM = (360, 1105)
DUNGEON_SWEEP = (565, 590)

# ---------- 基础工具 ----------

def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def sleep(sec=1.0):
    time.sleep(sec)


_shot_id = 0


def shot(name="cur"):
    global _shot_id
    _shot_id += 1
    remote = f"/sdcard/_f{_shot_id}.png"
    local = OUT / f"{name}_{_shot_id}.png"
    shell(f"screencap -p {remote}")
    adb("pull", remote, str(local))
    shell(f"rm -f {remote}")
    return Image.open(local).convert("RGB")


def avg(im, x, y, r=10, step=4):
    n = 0
    rs = gs = bs = 0
    for dx in range(-r, r + 1, step):
        for dy in range(-r, r + 1, step):
            px = im.getpixel((max(0, min(im.width - 1, x + dx)),
                              max(0, min(im.height - 1, y + dy))))
            rs += px[0]; gs += px[1]; bs += px[2]; n += 1
    return rs / n, gs / n, bs / n


def is_gold(im, x, y, r=14):
    """亮金色按钮（领取/挑战/升级）。「前往」那种浅土黄、已领取的绿色都排除。"""
    R, G, B = avg(im, x, y, r)
    return R >= 212 and G >= 150 and (R - B) >= 85


def similar(im1, im2, tol=25, max_diff=0.12):
    """粗比较两张截图：只有小动画变化时返回 True。"""
    diff = 0
    total = 0
    for y in range(40, 1200, 40):
        for x in range(50, 670, 40):
            a = im1.getpixel((x, y))
            b = im2.getpixel((x, y))
            total += 1
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) > tol * 3:
                diff += 1
    return diff / total < max_diff


def ensure_checked(pos):
    """勾选复选框（已勾选时不动）。"""
    im = shot("chk")
    R, G, B = avg(im, *pos, r=6)
    if not (G > R + 25 and G > B + 25):
        press(*pos); sleep(0.6)


def has_cancel_dialog(im):
    """确认弹窗：左侧红色「取消」按钮（购买次数、消耗确认等）。"""
    R, G, B = avg(im, 235, 700, r=8)
    return R > 175 and G < 120 and B < 110


def has_badge(im, cx, cy):
    """按钮右上角的红点（=免费/可用的角标）。扫描一小块区域数橙红像素。"""
    n = 0
    for y in range(cy - 75, cy - 15, 3):
        for x in range(cx + 45, cx + 100, 3):
            if not (0 <= x < im.width and 0 <= y < im.height):
                continue
            R, G, B = im.getpixel((x, y))
            if R > 175 and G < 110 and B < 85 and R - G > 75:
                n += 1
    return n >= 12


def in_main_city(im):
    R, G, B = avg(im, *SKY, r=8)
    return B > 210 and 140 < G < 200 and R < 125


def is_quit_dialog(im):
    # 退出确认：两个浅灰按钮（避开按钮上的深色文字，取左侧填充区）
    R, G, B = avg(im, 170, 720, r=6)
    return R > 190 and G > 190 and B > 190 and abs(R - B) < 12


def ensure_main_city(tries=14):
    """回主城：主城按返回会弹「确认退出游戏」，看到它就说明已经在主城根节点。"""
    im = shot("nav")
    if in_main_city(im):
        return True
    if is_quit_dialog(im):
        press(*QUIT_CANCEL); sleep(0.8)
        return True
    for i in range(tries):
        im = shot("nav")
        if is_gold(im, *TOWER_OK, r=16):
            press(*TOWER_OK); sleep(1.2)
            continue
        if is_gold(im, *LEGEND_OK, r=16):
            press(*LEGEND_OK); sleep(1.2)
            continue
        press(*BACK)
        sleep(1.4)
        im = shot("nav")
        if is_quit_dialog(im):
            log(f"  at city root after {i+1} back")
            press(*QUIT_CANCEL); sleep(0.9)
            return True
        if in_main_city(im):
            log(f"  back to city after {i+1} steps")
            return True
    log("  WARN: not in main city")
    return False


def close_modal():
    press(*BLANK)
    sleep(0.8)


def tap_gold(im, pos, label, r=14, wait=1.2):
    """只有金色可点时才按，返回是否点了。"""
    if is_gold(im, *pos, r=r):
        log(f"  tap {label} {pos}")
        press(*pos)
        sleep(wait)
        return True
    return False


# ---------- 奖励领取 ----------

def m_mail():
    log("mail")
    press(*ICON_MAIL); sleep(1.3)
    for _ in range(8):
        im = shot("mail")
        if is_gold(im, 360, 970, r=18):      # 打开了单封邮件详情
            press(360, 970); sleep(1.2)
            continue
        if not is_gold(im, *MAIL_CLAIM_ALL, r=18):
            break
        press(*MAIL_CLAIM_ALL); sleep(1.2)
    press(655, 243)  # X
    sleep(1.0)


def m_rank():
    log("rank / login rewards")
    press(*RANK_BAR); sleep(1.4)
    shell("input swipe 360 700 360 1080 300"); sleep(1.0)   # 列表回到顶部
    im = shot("rank")
    for y in RANK_CLAIM_YS:
        if tap_gold(im, (545, y), "rank claim", wait=1.3):
            close_modal()
            im = shot("rank")
    # 向下滚动，再领一轮
    shell("input swipe 360 1060 360 640 400"); sleep(1.2)
    im = shot("rank2")
    for y in RANK_CLAIM_YS:
        if tap_gold(im, (545, y), "rank claim 2", wait=1.3):
            close_modal()
            im = shot("rank2")
    # 晋升（材料不足时只是无反应）
    if is_gold(im, *RANK_PROMOTE, r=10):
        log("  promote rank")
        press(*RANK_PROMOTE); sleep(1.3)
        press(*RANK_PROMOTE_OK); sleep(1.2)
        close_modal()
    press(*BACK); sleep(1.2)


def m_friend():
    log("friend gifts")
    press(*ICON_FRIEND); sleep(1.3)
    for i in range(3):
        press(*FRIEND_GIFT); sleep(1.8)
    press(*X_TOP); sleep(1.0)


def m_welfare():
    log("welfare hub: lifetime gift")
    press(*ICON_WELFARE); sleep(1.6)
    press(550, 1245); sleep(1.2)
    press(240, 1245); sleep(1.2)
    press(645, 1245); sleep(1.2)
    press(540, 1245); sleep(1.4)
    im = shot("welfare")
    if tap_gold(im, (545, 1080), "lifetime claim", wait=1.4):
        close_modal()
    press(*BACK); sleep(1.2)


def m_hundred():
    """千抽福利：只在三个十连按钮带红点时抽（红点=免费次数）。"""
    log("hundred draws")
    press(*ICON_HUNDRED); sleep(1.6)
    for i, pos in enumerate(HUNDRED_TABS):
        im = shot("hundred")
        # 红点在按钮上方 30px 左右
        if not is_red(im, pos[0] - 45, pos[1] - 40, r=10):
            log(f"  draw {i+1}: no free badge, skip")
            continue
        press(*pos); sleep(2.2)
        press(*HUNDRED_SKIP); sleep(2.8)
        press(*HUNDRED_BACK); sleep(1.6)
    press(640, 205); sleep(1.0)
    ensure_main_city()


def m_summon_free():
    log("summon free single")
    press(*BLD_SUMMON); sleep(1.5)
    im = shot("summon")
    # 免费时按钮右上角有红点
    if has_badge(im, *SUMMON_ONE):
        press(*SUMMON_ONE); sleep(2.2)
        press(615, 258); sleep(2.2)          # 跳过动画（若有）
        press(*SUMMON_RESULT_BACK); sleep(1.5)
    else:
        log("  not free, skip")
    press(*BACK); sleep(1.2)


def m_forge_free():
    log("ancestor forge free single")
    press(*BLD_ANCESTOR); sleep(1.6)
    im = shot("forge")
    if has_badge(im, *FORGE_ONE):
        press(*FORGE_ONE); sleep(2.2)
        press(*FORGE_BACK); sleep(1.5)
    else:
        log("  not free, skip")
    press(*BACK); sleep(1.2)


def m_relic():
    log("relic upgrade")
    press(*BLD_RELIC); sleep(1.6)
    im = shot("relic")
    # 一键升级按钮是金色时材料够
    if tap_gold(im, RELIC_ONEKEY, "relic one-key", r=16, wait=1.4):
        press(465, 697); sleep(2.2)          # 确定
        close_modal()
        im = shot("relic2")
        if is_gold(im, *RELIC_ONEKEY, r=16):  # 还能升就再来一次
            press(*RELIC_ONEKEY); sleep(1.4)
            press(465, 697); sleep(2.2)
            close_modal()
    # 祝福
    press(*RELIC_BLESS); sleep(1.4)
    im = shot("bless")
    if tap_gold(im, RELIC_BLESS_UP, "blessing up", r=16, wait=1.5):
        close_modal()
    press(*BACK); sleep(1.2)


def m_star():
    log("hero star up (batch)")
    press(*BLD_STAR); sleep(1.6)
    for i in range(3):
        im = shot("star")
        if not is_gold(im, *STAR_BATCH, r=16):
            log("  batch button not gold, stop")
            break
        press(*STAR_BATCH); sleep(1.5)
        press(*STAR_CONFIRM); sleep(2.0)
        close_modal()
    press(*BACK); sleep(1.2)


def m_equipment():
    log("equipment enhance + star")
    press(*BLD_FORGE); sleep(1.8)
    # 强化
    for i in range(4):
        im = shot("eq")
        if not is_gold(im, *ENHANCE_50, r=16):
            log("  enhance button not gold, stop")
            break
        press(*ENHANCE_50); sleep(2.2)
        close_modal()
    # 升星
    press(*FORGE_TAB_STAR); sleep(1.6)
    im = shot("eqstar")
    if is_gold(im, *ENHANCE_STAR_ONEKEY, r=16):
        press(*ENHANCE_STAR_ONEKEY); sleep(1.6)
        press(*ENHANCE_STAR_CONFIRM); sleep(2.0)
        close_modal()
    press(*BACK); sleep(1.2)


def m_resonance():
    log("resonance auto")
    press(*BLD_RESONANCE); sleep(1.8)
    im = shot("resonance")
    if is_gold(im, *RESONANCE_AUTO, r=16):
        press(*RESONANCE_AUTO); sleep(1.6)
    press(*BACK); sleep(1.2)


def m_championship():
    log("championship: chat + gamble quests")
    press(*ICON_CHAMPION); sleep(1.8)
    # 发言一次
    press(*CHAMP_CHAT); sleep(0.8)
    shell("input text 666"); sleep(0.8)
    press(*CHAMP_SEND); sleep(1.5)
    # 领竞猜任务奖励
    press(*CHAMP_REWARD); sleep(1.5)
    press(*CHAMP_QUEST_TAB); sleep(1.2)
    for y in (463, 578, 693, 808, 920):
        im = shot("champ")
        if is_gold(im, 545, y, r=14):
            press(545, y); sleep(1.4)
            close_modal()
        else:
            break
    press(655, 200); sleep(1.0)
    press(*BACK); sleep(1.2)


def m_rebate():
    """达标返利 → 钻石限购的「福利礼包」每日免费 20 钻。"""
    log("rebate free daily gift")
    press(*ICON_REBATE); sleep(1.8)
    press(555, 690); sleep(1.6)     # 绿色「免费」
    close_modal()
    press(*BACK); sleep(1.0)


def m_hero_level():
    """英雄界面第一个英雄：升 50 级 / 进阶（有资源时连续点）。"""
    log("hero level / advance")
    press(*TAB_HERO); sleep(1.8)
    press(150, 330); sleep(2.0)
    # 详情页底部按钮在「进阶 / 升50级」之间切换，颜色都偏橙，直接点两次，失败只是提示
    for _ in range(3):
        press(360, 1105); sleep(1.6)
        close_modal()
    press(*BACK); sleep(1.2)
    press(*BACK); sleep(1.2)


def m_bp():
    """勇者计划（战令）：领取每日任务奖励，滚动两次覆盖更多行。"""
    log("battle pass quests")
    press(*ICON_HERO_PLAN); sleep(2.0)
    for _ in range(2):
        im = shot("bp")
        for y in (650, 790, 930, 1070):
            if is_gold(im, 545, y, r=16):
                press(545, y); sleep(1.2)
        shell("input swipe 360 1040 360 700 350"); sleep(1.0)
    press(*BACK); sleep(1.0)


# ---------- 战斗 ----------

def _ensure_trials_hub(tries=3):
    """回到主城并进入历练页；用页面底部的紫色光斑判断是否真的在历练页。"""
    for _ in range(tries):
        ensure_main_city()
        press(*TAB_TRIAL); sleep(1.8)
        im = shot("hub")
        R, G, B = avg(im, 360, 1100, r=8)
        if B > 150 and B > R + 30:
            return True
        log("  not trials hub, retry")
        press(*BACK); sleep(1.2)
    return False


def _wait_battle_result(timeout=200):
    """等结算：返回 (image, 按钮)。塔的「下一关/确定」在 y1080，试炼「确定」在 y1100。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        sleep(4)
        im = shot("res")
        if is_gold(im, *TOWER_NEXT, r=16):
            return im, TOWER_NEXT
        if is_gold(im, *TOWER_OK, r=16):
            return im, TOWER_OK
        if is_gold(im, *LEGEND_OK, r=16):
            return im, LEGEND_OK
    return None, None


def b_tower(fights=3):
    """守护者之塔：连续打 N 层（赢了点下一关，失败点确定）。"""
    log("battle: tower")
    if not _ensure_trials_hub():
        log("  cannot reach trials hub")
        return
    press(*TRIAL_TOWER); sleep(3.0)
    for i in range(fights):
        im = shot("tower")
        if not is_gold(im, *TOWER_GO, r=18):
            close_modal(); sleep(1.0)
            im = shot("tower")
        if not is_gold(im, *TOWER_GO, r=18):
            log("  tower challenge not gold, stop")
            break
        press(*TOWER_GO); sleep(1.6)
        press(*DEPLOY); sleep(0.8)
        press(*START_FIGHT); sleep(3.0)
        sleep(88)
        im, btn = _wait_battle_result(90)
        if btn is None:
            log("  battle result timeout")
            break
        if btn == TOWER_NEXT and i < fights - 1:
            press(*TOWER_NEXT); sleep(1.6)
        else:
            press(*btn); sleep(1.4)
            break
    press(*BACK); sleep(1.0)
    ensure_main_city()


def b_legend(fights=3):
    """传奇试炼：打 N 次（8 次/天），每次结算点确定。"""
    log("battle: legendary trial")
    if not _ensure_trials_hub():
        log("  cannot reach trials hub")
        return
    press(*TRIAL_LEGEND); sleep(3.0)
    for i in range(fights):
        im = shot("legend")
        if not is_gold(im, *LEGEND_GO, r=18):
            close_modal(); sleep(1.0)
            im = shot("legend")
        if not is_gold(im, *LEGEND_GO, r=18):
            log("  legend challenge not gold, stop")
            break
        press(*LEGEND_GO); sleep(1.6)
        press(*DEPLOY); sleep(0.8)
        press(*START_FIGHT); sleep(3.0)
        sleep(90)                      # 战斗固定约 85–100 秒
        press(*LEGEND_OK); sleep(2.0)  # 结算「确定」
        close_modal()
    press(*BACK); sleep(1.0)
    ensure_main_city()


def b_demon():
    """邪能神殿：可扫荡时扫荡（圣物材料）。扫荡后进入加成选择，自动选卡直到次数耗尽。"""
    log("battle: demon temple sweep")
    if not _ensure_trials_hub():
        log("  cannot reach trials hub")
        return
    press(*TRIAL_DEMON); sleep(1.8)
    im = shot("demon")
    # 「快速挑战 / 选择加成」在 y≈1140（980/1040/1100 是旧估位，已实测偏低）
    for y in (1140, 1100, 1040, 980):
        if is_gold(im, 360, y, r=18):
            press(360, y); sleep(2.0)
            break
    close_modal(); sleep(0.8)          # 获得奖励弹窗
    # 加成选择循环：有金「确定」就选第一张卡确定；槽位满时出现替换弹窗，再选格位确定
    for _ in range(40):
        im = shot("demon_buff")
        if not is_gold(im, *DEMON_CONFIRM, r=20):
            break
        press(*DEMON_CARD); sleep(0.6)
        press(*DEMON_CONFIRM); sleep(1.6)
        im = shot("demon_rep")
        if is_gold(im, *DEMON_CONFIRM, r=20):
            press(*DEMON_REPLACE); sleep(0.6)
            press(*DEMON_CONFIRM); sleep(1.4)
    press(*DEMON_CLOSE); sleep(1.0)
    press(*BACK); sleep(1.0)
    ensure_main_city()



def b_colosseum(max_fights=12):
    """角斗场：有次数就打（选靠下的弱对手），失败也有奖励。"""
    log("battle: colosseum")
    press(*TAB_ARENA); sleep(1.4)
    press(*ARENA_COLOSSEUM); sleep(1.8)
    press(*COLOSSEUM_DEFENSE_CLOSE); sleep(1.2)   # 关防守纪录
    ensure_checked(ARENA_SKIP_BOX)                # 勾选跳过战斗
    fought = 0
    for _ in range(max_fights):
        im = shot("colosseum")
        pos = None
        for y in COLOSSEUM_CHALLENGE_YS:
            if is_gold(im, 565, y, r=18):
                pos = (565, y)
                break
        if pos is None:
            log("  no gold challenge button, stop")
            break
        before = im
        press(*pos); sleep(2.2)
        im2 = shot("colo_chk")
        if has_cancel_dialog(im2):
            log("  purchase/confirm popup -> cancel")
            press(235, 700); sleep(1.2)
            break
        if similar(before, im2):
            log("  no attempts (screen unchanged)")
            break
        press(*COLOSSEUM_BACK); sleep(1.6)
        fought += 1
    log(f"  fought {fought}")
    press(*BACK); sleep(1.0)
    ensure_main_city()


def b_glory(max_fights=3):
    """荣耀竞技场：匹配对战。"""
    log("battle: glory arena")
    press(*TAB_ARENA); sleep(1.4)
    press(*ARENA_GLORY); sleep(1.8)
    press(655, 400); sleep(1.2)   # 关防守战报
    for _ in range(max_fights):
        im = shot("glory")
        if not is_gold(im, *GLORY_START, r=18):
            log("  start match not gold, stop")
            break
        press(*GLORY_START); sleep(2.5)
        im2 = shot("glory_chk")
        if has_cancel_dialog(im2):
            log("  purchase/confirm popup -> cancel")
            press(235, 700); sleep(1.2)
            break
        sleep(6)
        press(*GLORY_BACK); sleep(2.5)
    press(*BACK); sleep(1.0)
    ensure_main_city()


# ---------- 每日任务（2026-10-29 实测流程，坐标均为当天验证值） ----------

TAB_DAILY = (85, 895)            # 主城左侧「日常」图标
DAILY_CLAIM = (565, 451)         # 任意一行的「领取」：一次点击会领完所有已完成任务
CHEST_POS = [(270, 258), (380, 258), (490, 258), (600, 258)]   # 活跃度 25/50/75/100 宝箱
IDLE_PET = (115, 1040)           # 战役页左下睡觉的猫（挂机收益入口）
IDLE_FAST = (240, 1022)          # 挂机特权弹窗「快速挂机 / 快速♻50/100」
FORGE_TAB_ENHANCE_NEW = (515, 1225)
FORGE_ENHANCE_ONE = (150, 744)   # 强化1次（16202 金币）
SHOP_FREE_REFRESH = (655, 325)   # 神秘商店「免费刷新(N/N)」
DONATE_GOLD = (545, 500)         # 公会捐献·金币捐献（按 463 不响应，500 才触发）
BOUNTY_ACCEPT = [(565, 615), (565, 757), (565, 899)]
GUILD_TRIAL_GO = (515, 1128)     # 公会试炼「挑战」
GUILD_PLUS_BUY = (432, 1056)     # 试炼次数 +（20 钻/次）
GUILD_BUY_OK = (465, 775)        # 购买确认「购买」
TRIAL_SAVE = (465, 765)          # 试炼结算「保存」（787 是按钮下缘，765 才是命中点）
TRIAL_OK = (360, 1105)           # 试炼结算「确定」
CAMPAIGN_NODE = (360, 540)       # 战役页当前关卡节点
CAMPAIGN_GO = (360, 970)         # 关卡弹窗「挑战」
DEMON_GO = (360, 1140)           # 邪能神殿「快速挑战 / 选择加成」
DEMON_CONFIRM = (465, 1018)      # 加成弹窗「确定」
DEMON_CARD = (170, 755)          # 加成弹窗第一张卡
DEMON_REPLACE = (435, 808)       # 槽位满时的替换目标格
DEMON_CLOSE = (638, 212)         # 加成弹窗右上 X 的实际命中点


def is_green(im, x, y, r=14):
    """青绿色按钮（免费扫荡 / 快速挂机 / 一键上阵）：R 低、G 高、B 中。"""
    R, G, B = avg(im, x, y, r)
    return R < 195 and G > 165 and (G - R) > 25 and (G - B) > 20


def _unchanged(a, b):
    return similar(a, b)


def d_claim():
    """日常页：点一次「领取」领完全部已完成任务，再点 4 个活跃度宝箱。"""
    log("daily: claim task rewards + chests")
    ensure_main_city()
    press(*TAB_DAILY); sleep(2.0)
    im = shot("daily")
    if not is_gold(im, *DAILY_CLAIM, r=18):
        shell("input swipe 360 420 360 1050 500"); sleep(1.2)
        im = shot("daily")
    if is_gold(im, *DAILY_CLAIM, r=18):
        press(*DAILY_CLAIM); sleep(1.8)
        close_modal(); sleep(0.8)
    for pos in CHEST_POS:
        press(*pos); sleep(1.4)
    close_modal()
    press(*BACK); sleep(0.8)
    ensure_main_city()


def d_idle(times=3):
    """快速挂机：先用免费次数（1 次），之后每次 50/100 钻，默认做满 3 次（≤150 钻）。"""
    log("daily: quick idle")
    press(*TAB_CAMPAIGN); sleep(1.4)
    press(*IDLE_PET); sleep(2.0)
    done = 0
    while done < times:
        im = shot("idle")
        if not is_green(im, *IDLE_FAST, r=16):
            log(f"  fast idle unavailable after {done}")
            break
        press(*IDLE_FAST); sleep(2.4)
        close_modal(); sleep(0.8)      # 「挂机收益」弹窗
        done += 1
        log(f"  fast idle {done}")
    press(*TAB_CAMPAIGN); sleep(1.2)   # 挂机特权弹窗没有 X，切 tab 退出
    ensure_main_city()


def d_forge():
    """装备强化1次：铁匠铺 → 强化 → 强化1次。"""
    log("daily: forge enhance x1")
    press(*BLD_FORGE); sleep(2.0)
    press(*FORGE_TAB_ENHANCE_NEW); sleep(1.8)
    im = shot("forge")
    for y in (744, 700, 780):
        if is_gold(im, 150, y, r=16):
            press(150, y); sleep(1.8)
            break
    close_modal()
    press(*BACK); sleep(0.8)
    ensure_main_city()


def d_shop():
    """日常商店刷新2次（免费）。"""
    log("daily: shop free refresh x2")
    press(*BLD_SHOP); sleep(2.0)
    for _ in range(2):
        im = shot("shop")
        if not is_green(im, *SHOP_FREE_REFRESH, r=16) and not is_gold(im, *SHOP_FREE_REFRESH, r=10):
            log("  refresh button not active")
            break
        press(*SHOP_FREE_REFRESH); sleep(1.6)
    press(*BACK); sleep(0.8)
    ensure_main_city()


def d_donate():
    """公会捐献1次（金币，免费档）。"""
    log("daily: guild donate (gold)")
    press(*TAB_GUILD); sleep(1.6)
    press(435, 725); sleep(1.8)        # 公会捐献
    im = shot("donate")
    if is_gold(im, *DONATE_GOLD, r=16):
        press(*DONATE_GOLD); sleep(2.0)
        close_modal(); sleep(0.8)
    press(658, 367); sleep(1.0)        # 关闭捐献弹窗
    press(*BACK); sleep(0.8)
    ensure_main_city()


def _guild_trial_fight():
    """打一次公会试炼：挑战 → 一键上阵 → 战斗 → 保存 → 确定。"""
    press(*GUILD_TRIAL_GO); sleep(2.8)
    press(*DEPLOY); sleep(1.0)
    press(*START_FIGHT); sleep(3.0)
    sleep(95)                          # 战斗上限 60 秒 + 结算动画
    for _ in range(6):
        im = shot("gtrial")
        if is_gold(im, *TRIAL_SAVE, r=16):
            press(*TRIAL_SAVE); sleep(2.5)
            continue
        if is_gold(im, *TRIAL_OK, r=16):
            press(*TRIAL_OK); sleep(2.0)
            break
        sleep(5)


def d_guild_trial(times=3):
    """公会试炼3次：次数用完花 20 钻买 1 次。"""
    log("daily: guild trial x3")
    press(*TAB_GUILD); sleep(1.6)
    press(*GUILD_TRIAL); sleep(2.5)
    for i in range(times):
        im = shot("gtrial_hub")
        if not is_gold(im, *GUILD_TRIAL_GO, r=16):
            log("  no attempts, buy one (20 diamonds)")
            press(*GUILD_PLUS_BUY); sleep(1.8)
            im2 = shot("gtrial_buy")
            if is_gold(im2, *GUILD_BUY_OK, r=16):
                press(*GUILD_BUY_OK); sleep(1.8)
            else:
                log("  cannot buy attempt, stop")
                break
        _guild_trial_fight()
        log(f"  trial fight {i+1} done")
    press(*BACK); sleep(1.0)
    ensure_main_city()


def d_bounty(times=3):
    """接取悬赏：每次消耗 2000 悬赏积分；积分不够时按钮点击后画面不变即停。"""
    log("daily: accept bounties")
    press(*TAB_CAMPAIGN); sleep(1.4)
    press(640, 480); sleep(2.2)        # 战役页右侧「悬赏」
    done = 0
    for y, x in [(p[1], p[0]) for p in BOUNTY_ACCEPT][:times]:
        before = shot("bounty")
        press(x, y); sleep(1.8)
        after = shot("bounty2")
        if _unchanged(before, after):
            log("  accept did nothing (points insufficient?)")
            break
        done += 1
        log(f"  accepted {done}")
    press(*BACK); sleep(0.8)
    ensure_main_city()


def d_campaign():
    """挑战主线战役1次；玩家等级不足（32章要求116级）时直接跳过。"""
    log("daily: main campaign")
    press(*TAB_CAMPAIGN); sleep(1.4)
    press(*CAMPAIGN_NODE); sleep(2.0)
    before = shot("camp")
    press(*CAMPAIGN_GO); sleep(1.6)
    after = shot("camp2")
    if is_gold(after, *DEPLOY, r=18) or not _unchanged(before, after):
        if is_gold(after, *DEPLOY, r=18):
            press(*DEPLOY); sleep(0.8)
            press(*START_FIGHT); sleep(3.0)
            sleep(95)
            for _ in range(6):
                im = shot("camp_res")
                if is_gold(im, *TRIAL_OK, r=16):
                    press(*TRIAL_OK); sleep(1.8)
                    break
                sleep(5)
            log("  campaign fight done")
        else:
            log("  campaign challenge did not open (level gate / toast)")
    else:
        log("  campaign blocked (player level too low)")
    ensure_main_city()


REWARD_MODULES = [
    "mail", "rank", "friend", "welfare", "rebate", "bp", "hero_level",
    "relic", "star", "equipment", "resonance", "championship",
]
BATTLE_MODULES = ["tower", "legend", "demon", "colosseum", "glory"]
DAILY_MODULES = ["idle", "forge", "shop", "donate", "guild_trial", "bounty",
                 "campaign", "claim"]
DRAW_MODULES = ["hundred", "summon_free", "forge_free"]

HANDLERS = {
    "mail": m_mail,
    "rank": m_rank,
    "friend": m_friend,
    "welfare": m_welfare,
    "rebate": m_rebate,
    "hundred": m_hundred,
    "summon_free": m_summon_free,
    "forge_free": m_forge_free,
    "relic": m_relic,
    "star": m_star,
    "equipment": m_equipment,
    "resonance": m_resonance,
    "bp": m_bp,
    "hero_level": m_hero_level,
    "championship": m_championship,
    "tower": b_tower,
    "legend": b_legend,
    "demon": b_demon,
    "colosseum": b_colosseum,
    "glory": b_glory,
    "idle": d_idle,
    "forge": d_forge,
    "shop": d_shop,
    "donate": d_donate,
    "guild_trial": d_guild_trial,
    "bounty": d_bounty,
    "campaign": d_campaign,
    "claim": d_claim,
}

PROFILES = {
    "light": REWARD_MODULES,
    "combat": BATTLE_MODULES,
    "daily": DAILY_MODULES,
    "full": REWARD_MODULES + BATTLE_MODULES,
    "all": REWARD_MODULES + BATTLE_MODULES + DRAW_MODULES,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--profile", default="full", choices=sorted(PROFILES))
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    args = ap.parse_args()

    if args.list:
        print("profiles:")
        for k, v in PROFILES.items():
            print(f"  {k}: {', '.join(v)}")
        print("modules:", ", ".join(HANDLERS))
        return

    mods = list(PROFILES[args.profile])
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        mods = [m for m in mods if m in want]
    if args.skip:
        drop = {x.strip() for x in args.skip.split(",") if x.strip()}
        mods = [m for m in mods if m not in drop]

    if args.dry_run:
        for m in mods:
            log(f"would run: {m}")
        return

    if not ensure_main_city():
        log("ERROR: 无法回到主城，先手动切到主城再运行")
        return

    for name in mods:
        fn = HANDLERS.get(name)
        if not fn:
            log(f"unknown module: {name}")
            continue
        log(f"=== {name} ===")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            log(f"ERROR {name}: {e}")
            ensure_main_city()

    log("done")


if __name__ == "__main__":
    main()
