"""历练速刷：守护者之塔 / 传奇试炼，用战斗内「跳过」按钮 (655,900) 秒结算。

2026-10-29 实测：
  - 塔：挑战 (565,1065) → 布阵「一键上阵」(270,1230) → 「战斗」(540,1230)
    → 战斗中点右侧第四个按钮 (655,900) 立即结算 → 胜利「下一关」(465,1050) /「确定」(200,1050)
  - 战败会回到塔主界面，此时「挑战」按钮依旧金色。
  - 传奇试炼：挑战 (360,1120) → 布阵同上 → battle 内同样可以 skip → 结算「确定」(360,1100)。

用法：
  python trial_grind.py --tower 20 --max-lose 10     # 塔最多 20 场，连输 10 场停
  python trial_grind.py --legend 7                   # 传奇试炼剩余次数刷掉
  python trial_grind.py --tower 10 --then-upgrade    # 打完回城跑提升再回来
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from full_adb import (  # noqa: E402
    avg, ensure_main_city, is_gold, is_green, log, press, shot, sleep, shell,
)

TAB_TRIAL = (470, 1225)
HUB_TOWER = (270, 600)
HUB_LEGEND = (490, 600)
TOWER_GO = (565, 1065)
DEPLOY = (270, 1230)
FIGHT = (540, 1230)
SKIP = (655, 900)          # 战斗内右侧第四个按钮：立即结算
NEXT_FLOOR = (465, 1075)
RESULT_OK = (200, 1075)
LEGEND_GO = (360, 1120)
LEGEND_OK = (360, 1100)
RECONNECT = (465, 748)     # 「继续重连」金按钮（断线弹窗）
RECONNECT_OK = (360, 748)  # 只有「确定」的断线弹窗（点完回登录页）


def in_battle(im):
    """战斗界面：右上角有计时器，右下角有暂停/加速按钮。"""
    return is_green(im, 655, 775, r=8) or is_green(im, 655, 838, r=8)


def to_deploy(im=None):
    """从塔/试炼主页进布阵：若在主页先点挑战，再点一键上阵。返回布阵页截图。"""
    if im is None:
        im = shot("grind_hub")
    if is_gold(im, *TOWER_GO, r=18):
        press(*TOWER_GO); sleep(2.6)
        im = shot("grind_dep")
    elif is_gold(im, *LEGEND_GO, r=18):
        press(*LEGEND_GO); sleep(2.6)
        im = shot("grind_dep")
    if is_green(im, *DEPLOY, r=18):
        press(*DEPLOY); sleep(1.0)
        im = shot("grind_dep2")
    return im


def wait_result(timeout=20):
    """布阵后点战斗并跳过，轮询结算界面，返回 'win' / 'lose' / None。"""
    press(*FIGHT)
    for i in range(timeout):
        sleep(1.5)
        im = shot("grind")
        if is_gold(im, *NEXT_FLOOR, r=18):
            return "win", im
        if is_gold(im, *LEGEND_OK, r=18):
            return "win", im
        # 战斗中点一次跳过（结算页该位置是空白，多点无害）
        if i % 2 == 0:
            press(*SKIP, ms=120)
        if is_gold(im, *RESULT_OK, r=18) and not in_battle(im):
            return "lose", im
    return None, None


def bright(im, x, y, r=8, thr=330):
    R, G, B = avg(im, x, y, r)
    return (R + G + B) > thr


def _relogin():
    """断线到登录页时用 boot.py 重新登录（它会处理公告、标题页、登录弹窗）。"""
    import subprocess
    log("  session lost -> relogin via boot.py")
    subprocess.run([sys.executable, "-I", str(Path(__file__).resolve().parent / "boot.py")],
                   cwd=str(Path(__file__).resolve().parent))


def _enter_tower():
    """从任意位置进塔并开出第一场战斗。"""
    press(*TAB_TRIAL); sleep(1.6)
    press(*HUB_TOWER); sleep(2.4)
    im = shot("tower_hub")
    if is_gold(im, *TOWER_GO, r=18):
        press(*TOWER_GO); sleep(2.6)
        im = shot("tower_dep")
        if is_green(im, *DEPLOY, r=18):
            press(*DEPLOY); sleep(1.0)
        press(*FIGHT); sleep(2.0)


def _handle_disconnect(im):
    """处理两种断线弹窗；返回 True 表示处理过。
    1) 继续重连 (465,748) + 返回登录 (234,748)
    2) 只有一个「确定」(360,748)，点完回登录页，需要重新登录
    """
    if is_gold(im, *RECONNECT, r=12):
        log("  connection lost -> reconnect")
        press(*RECONNECT); sleep(3.5)
        return True
    if is_gold(im, *RECONNECT_OK, r=12):
        press(*RECONNECT_OK); sleep(2.5)
        _relogin()
        _enter_tower()
        return True
    return False


def tower(max_fights=20, max_lose=10, max_seconds=1800):
    """塔：挂「自动挑战(5S)」，循环里只负责点跳过和下一关。

    实测：结算页勾上「自动挑战(5S)」后，点一次「下一关」游戏就会自己布阵开打，
    所以这里只要：战斗中按跳过 (655,900)、胜利点下一关、战败点确定再挑战。
    """
    import time

    log(f"tower grind: max {max_fights} wins, stop after {max_lose} straight losses")
    _enter_tower()

    wins = loses = streak = 0
    deadline = time.time() + max_seconds
    while time.time() < deadline and wins < max_fights:
        im = shot("grind")
        if _handle_disconnect(im):
            continue
        if is_gold(im, *NEXT_FLOOR, r=18):
            wins += 1
            streak = 0
            log(f"  win #{wins}")
            press(*NEXT_FLOOR); sleep(2.2)
            continue
        if is_gold(im, *RESULT_OK, r=18):
            loses += 1
            streak += 1
            log(f"  LOSE (streak {streak})")
            press(*RESULT_OK); sleep(2.0)
            if streak >= max_lose:
                log(f"  {max_lose} straight losses -> stop")
                break
            im = shot("grind")
            if is_gold(im, *TOWER_GO, r=18):
                press(*TOWER_GO); sleep(2.2)
                im = shot("grind")
                if is_green(im, *DEPLOY, r=18):
                    press(*DEPLOY); sleep(0.8)
                press(*FIGHT); sleep(1.6)
            continue
        # 布阵页兜底（自动挑战没接上时）
        if is_green(im, *DEPLOY, r=18):
            press(*DEPLOY); sleep(0.8)
            press(*FIGHT); sleep(1.8)
            continue
        # 战斗页：底部英雄卡那一排是亮的，只有这时才按跳过
        if bright(im, 360, 1050):
            press(*SKIP, ms=120)
        sleep(0.8)
    log(f"tower done: wins={wins} loses={loses}")
    press(85, 1205, ms=200); sleep(1.2)
    ensure_main_city()
    return wins, loses


def legend(max_fights=8):
    """传奇试炼：把剩余次数刷完（伤害制，不会输）。"""
    log(f"legend grind: up to {max_fights}")
    press(*TAB_TRIAL); sleep(1.6)
    press(*HUB_LEGEND); sleep(2.4)
    done = 0
    for i in range(max_fights):
        im = shot("legend_hub")
        if not is_gold(im, *LEGEND_GO, r=18):
            log("  legend challenge not gold, stop")
            break
        press(*LEGEND_GO); sleep(2.4)
        im = shot("legend_dep")
        if is_green(im, *DEPLOY, r=18):
            press(*DEPLOY); sleep(1.0)
        press(*FIGHT)
        for _ in range(20):
            sleep(1.5)
            im = shot("legend_b")
            if is_gold(im, *LEGEND_OK, r=18):
                break
            press(*SKIP, ms=120)
        press(*LEGEND_OK); sleep(2.0)
        done += 1
        log(f"  legend done {done}")
    log(f"legend finished: {done}")
    press(85, 1205, ms=200); sleep(1.2)
    ensure_main_city()
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tower", type=int, default=0)
    ap.add_argument("--legend", type=int, default=0)
    ap.add_argument("--max-lose", type=int, default=10)
    ap.add_argument("--then-upgrade", action="store_true")
    args = ap.parse_args()

    ensure_main_city()
    if args.tower:
        tower(args.tower, args.max_lose)
    if args.legend:
        legend(args.legend)
    if args.then_upgrade:
        import subprocess
        log("run light upgrade modules")
        subprocess.run([sys.executable, "-I", str(Path(__file__).resolve().parent / "full_adb.py"),
                        "--profile", "light"], cwd=str(Path(__file__).resolve().parent))


if __name__ == "__main__":
    main()
