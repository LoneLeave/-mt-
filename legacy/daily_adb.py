"""《我叫MT：崛起》日常任务 ADB 脚本（非视觉主流程）

前提：
  - MuMu Player 12 已启动并登录游戏，停在任意界面。
  - 游戏分辨率 720x1280；本脚本坐标基于该分辨率。
  - 建议在每日重置后运行（列表顺序固定、任务都未完成），否则可能需要手动跳过已完成项。
  - 不使用截图/模板匹配；状态判断靠固定等待 + NvnLog 兜底（可选）。

运行：
  python daily_adb.py --dry-run          # 只打印计划，不点击
  python daily_adb.py                    # 执行全部任务
  python daily_adb.py --only summon,tower
  python daily_adb.py --list

注意：
  - 会消耗游戏资源：召唤券、钻石（快速挂机、公会试炼补次数、副本扫荡）、金币（装备强化）。
  - 不会进行真实充值；所有购买仅使用游戏内钻石。
  - 如果界面与预期不符，脚本会尽量点“空白处关闭”并继续，但可能需要人工修正坐标。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from adb_mumu import tap, swipe, back, shell, latest_log, tail_log  # noqa: E402

# ---------- 坐标（720x1280，游戏画面 x∈[28,691]） ----------
TOP_BTN = (565, 450)          # 日常列表最上面一行的“前往/领取”
BLANK = (360, 100)            # 通用空白关闭点
HOME = (88, 1205)             # 左下返回/回主页（实测要比视觉位置低一点）
MAIN_TAB = (75, 1225)         # 主城
DAILY_ICON = (85, 895)        # 主城左侧“日常”
CAMPAIGN_TAB = (360, 1225)    # 战役
GUILD_TAB = (650, 1225)       # 公会
ARENA_TAB = (540, 1225)       # 竞技
LEGEND_TAB = (450, 1225)      # 历练（未使用）

# 召唤
SUMMON_ONE = (160, 1110)
SUMMON_BACK = (225, 1155)
# 快速挂机
IDLE_ENTRY = (620, 690)       # 战役页“全民挂机”
IDLE_POPUP_X = (615, 135)     # 挂机特权弹窗关闭
IDLE_PET = (120, 1030)        # 左下挂机收益入口
IDLE_FAST = (250, 1024)       # 快速挂机（50/100 钻）
IDLE_CLAIM = (490, 1024)      # 领取收益
# 守护者之塔
TOWER_CHALLENGE = (527, 1090) # 实测按钮在视觉位置下方
AUTO_DEPLOY = (270, 1230)
FIGHT = (527, 1230)
NEXT_FLOOR = (490, 1080)
CONFIRM = (225, 1080)         # 战斗结算“确定”
# 公会试炼
GUILD_TRIAL = (210, 630)
GUILD_CHALLENGE = (490, 1185)
GUILD_PLUS = (428, 1095)
GUILD_BUY = (490, 771)
GUILD_SAVE = (490, 771)
GUILD_CONFIRM = (360, 1105)
# 日常副本
DUNGEON_FREE_SWEEP = (565, 590)
# 装备强化
FORGE_TAB = (525, 1185)
FORGE_ONE = (150, 744)
# 商店
SHOP_REFRESH = (650, 330)
# 传奇试炼
LEGEND_CHALLENGE = (360, 1130)
LEGEND_CONFIRM = (360, 1090)
# 时光之树
TREE_CHALLENGE = (360, 1185)
TREE_CONFIRM = (360, 1105)
# 好友
FRIEND_ICON = (620, 1000)
FRIEND_GIFT = (490, 968)
FRIEND_CLOSE = (658, 202)
# 公会捐献
GUILD_DONATE = (360, 760)
GUILD_DONATE_GOLD = (545, 463)
GUILD_DONATE_CLOSE = (658, 350)
# 竞技场
ARENA_ENTRY = (360, 520)
ARENA_CHALLENGE = (565, 540)
ARENA_BACK = (490, 783)
# 悬赏
BOUNTY_ACCEPT = [(565, 635), (565, 741), (565, 847)]
# 活跃度宝箱
CHESTS = [(275, 250), (380, 250), (490, 250), (600, 250)]

TASKS = [
    "main_campaign",
    "summon",
    "quick_idle",
    "tower",
    "guild_trial",
    "daily_dungeon",
    "enhance",
    "shop_refresh",
    "legendary",
    "time_tree",
    "friend_gift",
    "arena",
    "guild_donate",
    "bounty",
]


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def wait(sec=1.0):
    time.sleep(sec)


def tap_wait(pos, sec=1.0, label=None):
    if label:
        log(f"tap {label} {pos}")
    tap(*pos)
    wait(sec)


def close_popup():
    """通用关闭：先点空白，再按一次返回（返回可能弹退出，所以只点空白为主）。"""
    tap(*BLANK)
    wait(0.5)


def go_daily():
    """从任意界面回到日常任务页。"""
    log("go_daily")
    tap_wait(HOME, 1.2, "home")
    tap_wait(MAIN_TAB, 1.2, "main tab")
    tap_wait(DAILY_ICON, 1.5, "daily icon")


def go_main_city():
    tap_wait(HOME, 1.2, "home")
    tap_wait(MAIN_TAB, 1.2, "main tab")


def top_tap():
    """按日常列表最上面一行的按钮（前往/领取）。"""
    tap_wait(TOP_BTN, 1.5, "top row")


def claim_top():
    """完成一个任务后，列表顶部会变成该任务的“领取”。"""
    top_tap()
    wait(1.0)
    close_popup()


# ---------- 任务流程 ----------

def task_summon():
    """进行3次召唤：进入顶部任务 → 召唤一次（消耗1张券）。"""
    top_tap()
    wait(2.0)
    tap_wait(SUMMON_ONE, 5.0, "summon one")
    tap_wait(SUMMON_BACK, 1.5, "summon back")
    go_daily()
    claim_top()


def task_quick_idle():
    """快速挂机3次：战役 → 全民挂机 → 挂机收益 → 快速(50/100) ×2。"""
    top_tap()
    wait(2.0)
    tap_wait(CAMPAIGN_TAB, 1.2, "campaign tab")
    tap_wait(IDLE_ENTRY, 2.0, "idle entry")
    tap_wait(IDLE_POPUP_X, 0.8, "close idle privilege")
    tap_wait(IDLE_PET, 2.0, "idle pet")
    for i in range(2):
        tap_wait(IDLE_FAST, 3.0, f"fast idle {i+1}")
        close_popup()
    tap_wait(IDLE_CLAIM, 2.0, "claim idle")
    close_popup()
    go_daily()
    claim_top()


def task_tower():
    """守护者之塔战斗3次：挑战 → 一键上阵 → 战斗 → 下一关 ×2。"""
    top_tap()
    wait(2.0)
    tap_wait(TOWER_CHALLENGE, 3.0, "tower challenge")
    tap_wait(AUTO_DEPLOY, 0.8, "auto deploy")
    tap_wait(FIGHT, 3.0, "fight 1")
    wait(90)
    tap_wait(NEXT_FLOOR, 3.0, "next floor 2")
    wait(90)
    tap_wait(NEXT_FLOOR, 3.0, "next floor 3")
    wait(90)
    tap_wait(CONFIRM, 1.5, "confirm")
    go_daily()
    claim_top()


def task_guild_trial():
    """公会试炼3次：次数为0时花20钻买1次。"""
    top_tap()
    wait(2.0)
    # 日常“前往”先到公会大厅，再点“公会试炼”；若已经直达试炼，这一下相当于点空白
    tap_wait(GUILD_TRIAL, 1.5, "guild trial entry")
    tap_wait(GUILD_CHALLENGE, 3.0, "guild challenge")
    tap_wait(GUILD_PLUS, 1.5, "guild plus")
    tap_wait(GUILD_BUY, 1.5, "guild buy attempt")
    tap_wait(AUTO_DEPLOY, 0.8, "auto deploy")
    tap_wait(FIGHT, 3.0, "guild fight")
    wait(90)
    tap_wait(GUILD_SAVE, 1.5, "save guild result")
    tap_wait(GUILD_CONFIRM, 1.5, "confirm")
    go_daily()
    claim_top()


def task_daily_dungeon():
    """日常副本扫荡3次：经验副本 → 免费扫荡 ×3。"""
    top_tap()
    wait(2.0)
    for i in range(3):
        tap_wait(DUNGEON_FREE_SWEEP, 2.0, f"free sweep {i+1}")
        close_popup()
    go_daily()
    claim_top()


def task_enhance():
    """装备强化1次：铁匠铺 → 强化 → 强化1次。"""
    top_tap()
    wait(2.0)
    tap_wait(FORGE_TAB, 1.5, "forge tab")
    tap_wait(FORGE_ONE, 2.0, "enhance one")
    go_daily()
    claim_top()


def task_shop_refresh():
    """日常商店刷新2次：免费刷新图标点两次。"""
    top_tap()
    wait(2.0)
    tap_wait(SHOP_REFRESH, 2.0, "shop refresh 1")
    tap_wait(SHOP_REFRESH, 2.0, "shop refresh 2")
    go_daily()
    claim_top()


def task_legendary():
    """传奇试炼1次。"""
    top_tap()
    wait(2.0)
    tap_wait(LEGEND_CHALLENGE, 3.0, "legend challenge")
    tap_wait(AUTO_DEPLOY, 0.8, "auto deploy")
    tap_wait(FIGHT, 3.0, "legend fight")
    wait(90)
    tap_wait(LEGEND_CONFIRM, 1.5, "legend confirm")
    go_daily()
    claim_top()


def task_time_tree():
    """时光之树3次（输赢都计数）。"""
    top_tap()
    wait(2.0)
    for i in range(3):
        tap_wait(TREE_CHALLENGE, 2.5, f"tree challenge {i+1}")
        tap_wait(FIGHT, 3.0, "tree fight")
        wait(90)
        tap_wait(TREE_CONFIRM, 1.5, "tree confirm")
    go_daily()
    claim_top()


def task_friend_gift():
    """每日好友送礼5次：好友 → 赠送领取 ×2。"""
    top_tap()
    wait(2.0)
    # 日常“前往”通常直接打开好友；兜底从主城进
    tap_wait(FRIEND_GIFT, 1.8, "friend gift 1")
    tap_wait(FRIEND_GIFT, 1.8, "friend gift 2")
    tap_wait(FRIEND_CLOSE, 0.8, "close friends")
    go_daily()
    claim_top()


def task_arena():
    """角斗场3次：挑战 → 返回玩法 ×3。"""
    top_tap()
    wait(2.0)
    tap_wait(ARENA_ENTRY, 2.0, "arena entry")
    close_popup()  # 防守纪录弹窗
    for i in range(3):
        tap_wait(ARENA_CHALLENGE, 3.0, f"arena challenge {i+1}")
        tap_wait(ARENA_BACK, 1.5, "arena back")
    go_daily()
    claim_top()


def task_guild_donate():
    """公会捐献1次：金币捐献（免费）。"""
    top_tap()
    wait(2.0)
    tap_wait(GUILD_DONATE_GOLD, 2.0, "guild donate gold")
    tap_wait(GUILD_DONATE_CLOSE, 0.8, "close donate")
    go_daily()
    claim_top()


def task_bounty():
    """接取3次悬赏任务（每次消耗2000悬赏积分）。"""
    top_tap()
    wait(2.0)
    for i, pos in enumerate(BOUNTY_ACCEPT):
        tap_wait(pos, 2.0, f"bounty accept {i+1}")
        close_popup()
    go_daily()
    claim_top()


def task_main_campaign():
    """挑战主线战役1次：战役 → 当前关 → 挑战 → 一键上阵 → 战斗。"""
    top_tap()
    wait(2.0)
    tap_wait((360, 510), 2.0, "campaign stage")
    tap_wait((360, 970), 2.0, "stage challenge")
    tap_wait(AUTO_DEPLOY, 0.8, "auto deploy")
    tap_wait(FIGHT, 3.0, "campaign fight")
    wait(90)
    tap_wait(TREE_CONFIRM, 1.5, "campaign confirm")
    go_daily()
    claim_top()


HANDLERS = {
    "main_campaign": task_main_campaign,
    "summon": task_summon,
    "quick_idle": task_quick_idle,
    "tower": task_tower,
    "guild_trial": task_guild_trial,
    "daily_dungeon": task_daily_dungeon,
    "enhance": task_enhance,
    "shop_refresh": task_shop_refresh,
    "legendary": task_legendary,
    "time_tree": task_time_tree,
    "friend_gift": task_friend_gift,
    "arena": task_arena,
    "guild_donate": task_guild_donate,
    "bounty": task_bounty,
}


def claim_activity_chests():
    log("claim activity chests")
    for pos in CHESTS:
        tap_wait(pos, 1.0, f"chest {pos}")
        close_popup()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔的任务名")
    ap.add_argument("--start", default="", help="从某个任务开始")
    args = ap.parse_args()

    if args.list:
        for t in TASKS:
            print(t)
        return

    tasks = TASKS
    if args.only:
        wanted = [x.strip() for x in args.only.split(",") if x.strip()]
        tasks = [t for t in tasks if t in wanted]
    if args.start:
        if args.start not in tasks:
            raise SystemExit(f"unknown start task: {args.start}")
        tasks = tasks[tasks.index(args.start):]

    log(f"latest log: {latest_log()}")
    if args.dry_run:
        for t in tasks:
            log(f"would run: {t}")
        return

    go_daily()
    for name in tasks:
        fn = HANDLERS.get(name)
        if not fn:
            log(f"skip unknown task: {name}")
            continue
        log(f"=== {name} ===")
        try:
            fn()
            log(f"done: {name}")
        except Exception as e:
            log(f"ERROR {name}: {e}")
            try:
                go_daily()
            except Exception:
                pass

    claim_activity_chests()
    log("all done")


if __name__ == "__main__":
    main()
