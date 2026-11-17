"""《我叫MT：崛起》从零启动脚本：开模拟器 → 开游戏 → 进游戏（主城）

流程（已实测）：
  1. MuMuManager 检查模拟器，没开就 launch，等 adb + sys.boot_completed
  2. am start 启动游戏（AgreementSplashActivity）
  3. 「资源加载中」splash → 公告弹窗（点空白关闭）
  4. 标题页：确认已勾选《用户协议》→ 点「开始游戏」
  5. 「冒险即将开始」加载 → 登录后一堆弹窗（离线收益/挂机收益/累充/公会圣兽/
     深海秘宝/等级提升…）逐个点空白关闭，离线收益顺手领取
  6. 判定进主城（顶部天空像素 + 底部导航不被压暗）

用法：
  python boot.py                 # 只负责进游戏
  python boot.py --then light    # 进游戏后跑 full_adb 的 light 套餐
  python boot.py --then full     # 进游戏后跑 full_adb 全套（含战斗）
  python boot.py --then daily    # 进游戏后跑 daily_adb 每日任务
  python boot.py --cold          # 先 force-stop 游戏，模拟真正冷启动

不点任何人民币入口；不关机、不重装。
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

from full_adb import (  # noqa: E402
    avg, in_main_city, is_gold, press, shot, sleep, log, is_quit_dialog,
)
QUIT_CANCEL = (475, 725)

MUMU_DIR = Path(r"D:\Program Files\Netease\MuMu Player 12")
MUMU_MANAGER = MUMU_DIR / "nx_main" / "MuMuManager.exe"
ADB = str(MUMU_DIR / "shell" / "adb.exe")
VM = "0"
PKG = "com.wjmtjq.ma.android"
ACT = "com.hnyl.core.fragment.AgreementSplashActivity"
PY = sys.executable

BACK = (88, 1215)              # 左下返回箭头（活动页/子页面用）
START_BTN = (360, 1040)        # 标题页「开始游戏」
TITLE_AGREE = (128, 1119)      # 标题页协议勾选框
ANNC_AGREE = (135, 1030)       # 公告页协议勾选框
# 弹窗遮罩的可点空白：四角最稳（全屏促销弹窗中间是内容，点中间没用）
BLANKS = [(60, 150), (670, 150), (60, 1150), (670, 1150), (360, 100), (360, 1190)]
CLAIM_IDLE = (360, 1040)       # 离线收益「领取收益」
# 弹窗右上角 X 的实际命中点会偏移，按小簇尝试（累充弹窗实测在 (590,170)）
X_CANDIDATES = [
    (590, 170), (610, 185), (600, 175), (620, 195),
    (635, 185), (655, 200), (640, 240), (615, 300),
]


def adb(*args, timeout=25):
    p = subprocess.run([ADB, "-s", "127.0.0.1:16384", *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", timeout=timeout)
    return (p.stdout or "").strip()


def sh(cmd, timeout=25):
    return adb("shell", cmd, timeout=timeout)


def emulator_info():
    try:
        out = subprocess.run([str(MUMU_MANAGER), "info", "-v", VM],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="ignore", timeout=20).stdout
        return json.loads(out[out.index("{"):])
    except Exception:
        return {}


def start_emulator():
    info = emulator_info()
    if info.get("is_process_started") and info.get("is_android_started"):
        log("emulator already running")
        return True
    log("starting emulator...")
    subprocess.run([str(MUMU_MANAGER), "control", "-v", VM, "launch"],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="ignore", timeout=60)
    return wait_adb()


def wait_adb(timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        subprocess.run([ADB, "connect", "127.0.0.1:16384"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", timeout=15)
        out = adb("shell", "getprop sys.boot_completed")
        if out.strip() == "1":
            log("adb ready")
            return True
        time.sleep(5)
    log("WARN: adb not ready")
    return False


def focus_pkg():
    out = sh("dumpsys window | grep mCurrentFocus")
    m = re.search(r"u0 ([\w.]+)/", out)
    return m.group(1) if m else ""


def launch_game(cold=False):
    if cold:
        log("force-stop game")
        sh(f"am force-stop {PKG}")
        sleep(2)
    log("launch game")
    sh(f"am start -n {PKG}/{ACT}")
    sleep(3)


# ---------- 画面判定 ----------

def has_green_check(im, cx, cy):
    n = 0
    for y in range(cy - 12, cy + 13, 3):
        for x in range(cx - 12, cx + 13, 3):
            R, G, B = im.getpixel((x, y))
            if G > 110 and G - R > 45 and G - B > 35:
                n += 1
    return n >= 6


def is_title(im):
    """标题页：「开始游戏」大金按钮（主城同位置是土黄地面，R−B 只有 ~75）。"""
    R, G, B = avg(im, *START_BTN, r=18)
    return (not in_main_city(im)) and R > 195 and (R - B) > 85


def is_dim(im):
    """主城被弹窗压暗：底部导航亮度骤降。"""
    R, G, B = avg(im, 110, 1225, r=8)
    return (R + G + B) < 170


def similar(im1, im2, tol=30, max_diff=0.10):
    diff = total = 0
    for y in range(40, 1200, 40):
        for x in range(50, 670, 40):
            a, b = im1.getpixel((x, y)), im2.getpixel((x, y))
            total += 1
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) > tol * 3:
                diff += 1
    return diff / total < max_diff


def ensure_agreement(im):
    """标题页未勾选协议就点一下。"""
    if not has_green_check(im, *TITLE_AGREE):
        log("  tick agreement")
        press(*TITLE_AGREE)
        sleep(0.8)



def find_close_buttons(im):
    """在右上角找红色圆形关闭按钮，返回候选中心（实测命中点在图标左下 ~20px）。"""
    from collections import deque
    pts = set()
    for y in range(60, 430, 2):
        for x in range(430, im.width - 16, 2):
            R, G, B = im.getpixel((x, y))
            if R > 165 and G < 100 and B < 100 and (R - G) > 75 and (R - B) > 75:
                pts.add((x, y))
    out = []
    while pts:
        seed = pts.pop()
        q = deque([seed]); comp = [seed]
        while q:
            cx, cy = q.popleft()
            for dx in (-2, 0, 2):
                for dy in (-2, 0, 2):
                    np_ = (cx + dx, cy + dy)
                    if np_ in pts:
                        pts.discard(np_); q.append(np_); comp.append(np_)
        xs = [p[0] for p in comp]; ys = [p[1] for p in comp]
        w = max(xs) - min(xs); h = max(ys) - min(ys)
        if len(comp) >= 40 and 12 <= w <= 70 and 12 <= h <= 70 and abs(w - h) <= 22:
            out.append((sum(xs) / len(comp), sum(ys) / len(comp)))
    return out


def close_popup():
    """弹窗：先点上方空白，再点下方提示处，最后按 X 簇逐个试。"""
    for pos in BLANKS:
        press(*pos)
        sleep(1.2)
        im = shot("pop")
        if in_main_city(im) or not is_dim(im):
            return True
    # 优先：截图里找红色关闭按钮，按实测偏移点
    im = shot("popx")
    for cx, cy in find_close_buttons(im):
        for dx, dy in ((0, 0), (-20, 10), (-20, 0), (-10, 12), (8, 8)):
            press(int(cx + dx), int(cy + dy), ms=90)
            sleep(0.9)
            im2 = shot("pop4")
            if in_main_city(im2) or not is_dim(im2):
                return True
    for pos in X_CANDIDATES:
        press(*pos, ms=120)
        sleep(1.0)
        im = shot("pop3")
        if in_main_city(im) or not is_dim(im):
            return True
    return False


def wait_ingame(timeout=300):
    """轮询直到进入主城；顺带处理标题页、公告页、登录弹窗、充值活动页。"""
    deadline = time.time() + timeout
    claimed = 0
    while time.time() < deadline:
        # 被别的应用（比如同一模拟器上的阴阳师脚本）抢前台时，重新拉起本游戏
        if focus_pkg() != PKG:
            log("  foreground lost -> relaunch")
            sh(f"am start -n {PKG}/{ACT}")
            sleep(4)
            continue
        im = shot("boot")
        if im.width > im.height:      # 横屏说明被别的游戏占用
            log("  landscape app on top -> relaunch")
            sh(f"am start -n {PKG}/{ACT}")
            sleep(4)
            continue
        if in_main_city(im):
            log("in main city")
            return True
        if is_quit_dialog(im):
            log("  quit dialog -> cancel")
            press(*QUIT_CANCEL)
            sleep(1.0)
            continue
        if is_title(im):
            log("title screen")
            ensure_agreement(im)
            log("  press start")
            press(*START_BTN)
            sleep(3)
            continue
        if is_dim(im):
            # 弹窗：离线收益/挂机收益是「领取收益」，其余直接关
            if claimed < 2 and is_gold(im, *CLAIM_IDLE, r=16):
                log("  claim offline earnings")
                press(*CLAIM_IDLE)
                claimed += 1
                sleep(2)
                continue
            log("  close popup")
            close_popup()
            continue
        # 登录后经常直接弹全屏充值/VIP 活动页（底部是亮米色栏）：左下返回箭头退出
        R, G, B = avg(im, 110, 1225, r=8)
        if R > 200 and G > 180:
            log("  activity page -> back")
            press(*BACK)
            sleep(1.6)
            continue
        # splash / loading
        sleep(2.5)
    log("WARN: not in main city yet")
    return False


def run_then(what):
    if what == "none":
        return
    if what == "daily":
        cmd = [PY, "-I", str(HERE / "daily_adb.py")]
    else:
        cmd = [PY, "-I", str(HERE / "full_adb.py"), "--profile", what]
    log("run: " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cold", action="store_true", help="先杀掉游戏进程再启动")
    ap.add_argument("--then", default="none",
                    choices=["none", "light", "full", "all", "daily"])
    ap.add_argument("--no-emulator", action="store_true", help="跳过模拟器启动")
    args = ap.parse_args()

    if not args.no_emulator and not start_emulator():
        log("ERROR: emulator failed to start")
        return 1

    if focus_pkg() == PKG:
        im = shot("chk")
        if in_main_city(im) and not args.cold:
            log("already in game (main city)")
            run_then(args.then)
            return 0

    launch_game(cold=args.cold)
    ok = wait_ingame()
    if not ok:
        return 2
    run_then(args.then)
    return 0


if __name__ == "__main__":
    sys.exit(main())
