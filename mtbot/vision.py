"""视觉层：像素判读 + 画面状态分类。只依赖 PIL 图像，不认识 adb 与游戏业务。

坐标锚点集中在 anchors.py；本模块只提供“怎么判”，不提供“点哪里”。
"""
from __future__ import annotations

from collections import deque
from enum import Enum

from PIL import Image

# ---------- 基础像素 ----------


def avg(im: Image.Image, x: int, y: int, r: int = 10, step: int = 4) -> tuple[float, float, float]:
    n = 0
    rs = gs = bs = 0.0
    w, h = im.size
    for dx in range(-r, r + 1, step):
        for dy in range(-r, r + 1, step):
            R, G, B = im.getpixel((max(0, min(w - 1, x + dx)), max(0, min(h - 1, y + dy))))
            rs += R
            gs += G
            bs += B
            n += 1
    return rs / n, gs / n, bs / n


def is_gold(im: Image.Image, x: int, y: int, r: int = 14) -> bool:
    """亮金色按钮（领取/挑战/升级/确定）。浅土黄的「前往」、绿色「已领取」不算。"""
    R, G, B = avg(im, x, y, r)
    return R >= 212 and G >= 150 and (R - B) >= 85


def gold_ratio(im: Image.Image, box, step: int = 3) -> float:
    """box 内亮金色像素占比（金色大按钮的整块判据，比单点 is_gold 稳）。

    实测罪魂之域「挑战」按钮填充 (242,190,39)：R 高、G 中、B 极低。
    单点 is_gold 会压到按钮中间的字，改成整块占比。
    """
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, im.width), min(y1, im.height)
    n = hit = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            R, G, B = im.getpixel((x, y))[:3]
            n += 1
            if R >= 200 and 150 <= G <= 235 and B < 120 and (R - B) >= 120:
                hit += 1
    return hit / n if n else 0.0


def beige_ratio(im: Image.Image, box, step: int = 3) -> float:
    """box 内亮米色像素占比（罪魂之域关卡面板的底色判据）。

    实测（2026-11-06）：地图 0.028、任意关卡面板 0.66；阈值 0.20 就能分开。
    比「整屏 diff」靠谱——地图有持续动画，两帧之间 diff 本来就有 0.088。
    """
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, im.width), min(y1, im.height)
    n = hit = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            R, G, B = im.getpixel((x, y))[:3]
            n += 1
            if R > 150 and G > 150 and B > 150:
                hit += 1
    return hit / n if n else 0.0


def is_green(im: Image.Image, x: int, y: int, r: int = 14) -> bool:
    """青绿色按钮（免费扫荡/快速挂机/一键上阵/奖励领取）。"""
    R, G, B = avg(im, x, y, r)
    return R < 195 and G > 165 and (G - R) > 25 and (G - B) > 20


def green_ratio(im: Image.Image, box, step: int = 1) -> float:
    """box 内「绿勾」像素占比（勾选框开关状态）。

    实测（2026-11-20 `logs/_bag_dec.png`，印记分解页底部
    「获得普通、史诗印记时自动分解」）：已勾上时勾选框 (180,836,224,880)
    绿像素占比 0.206，右侧文字区 0.000、空白面板 0.000 → 阈值 0.05 干净。
    单点 is_green 不行：白底圆角框把均值拉高了，这里要按像素占比。
    """
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, im.width), min(y1, im.height)
    n = hit = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            R0, G0, B0 = im.getpixel((x, y))[:3]
            n += 1
            if G0 > R0 + 18 and G0 > B0 + 18 and G0 > 85:
                hit += 1
    return hit / n if n else 0.0


def is_amber(im: Image.Image, x: int, y: int, r: int = 14) -> bool:
    """浅琥珀色按钮（圣物羁绊「升级」这类：比主按钮更淡的黄）。

    实测 (226,205,161)：R−B≈65，比 is_gold 的 85 更淡；面板底色 (238,228,207) R−B=31 会被排除。
    """
    R, G, B = avg(im, x, y, r)
    return R > 205 and G > 175 and 40 <= (R - B) <= 95 and (G - B) > 25


def is_bright(im: Image.Image, x: int, y: int, r: int = 8, threshold: int = 330) -> bool:
    R, G, B = avg(im, x, y, r)
    return (R + G + B) > threshold


def is_red(im: Image.Image, x: int, y: int, r: int = 6) -> bool:
    R, G, B = avg(im, x, y, r)
    return R > 175 and G < 120 and B < 110


def has_badge(im: Image.Image, cx: int, cy: int) -> bool:
    """按钮右上角的红点角标（免费/可用）。"""
    n = 0
    for y in range(cy - 75, cy - 15, 3):
        for x in range(cx + 45, cx + 100, 3):
            if not (0 <= x < im.width and 0 <= y < im.height):
                continue
            R, G, B = im.getpixel((x, y))
            if R > 175 and G < 110 and B < 85 and R - G > 75:
                n += 1
    return n >= 12


def similar(a: Image.Image, b: Image.Image, tol: int = 25, max_diff: float = 0.12) -> bool:
    if a.size != b.size:            # 尺寸变了（横竖屏切换）一定不相似
        return False
    w, h = a.size
    # 固定坐标基于竖屏 720×1280；OAS 切横屏(1280×720)时 y=1200 会越界
    xs = range(50, min(670, w), 40)
    ys = range(40, min(1200, h), 40)
    diff = total = 0
    for y in ys:
        for x in xs:
            p, q = a.getpixel((x, y)), b.getpixel((x, y))
            total += 1
            if abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) > tol * 3:
                diff += 1
    return total > 0 and diff / total < max_diff


# ---------- 状态分类 ----------

class State(str, Enum):
    MAIN_CITY = "main_city"            # 主城（顶部蓝天 + 底部导航）
    MAIN_CITY_DIM = "main_city_dim"    # 主城被弹窗压暗
    TITLE = "title"                    # 标题页（开始游戏）
    TRIALS_HUB = "trials_hub"          # 历练页
    DEPLOY = "deploy"                  # 布阵页（一键上阵/战斗）
    BATTLE = "battle"                  # 战斗中（底部英雄卡亮）
    RESULT_TOWER = "result_tower"      # 塔结算（下一关 465,1075）
    RESULT_TREE = "result_tree"        # 时空之树/主线结算（按钮更低 495,1130）
    RESULT_LEGEND = "result_legend"    # 传奇试炼结算（确定 360,1100）
    RESULT_GENERIC = "result_generic"  # 其他结算（确定 360,1082）
    RESULT_DEFEAT = "result_defeat"    # 失败结算页（按钮不亮/再战）
    QUIT_DIALOG = "quit_dialog"        # 「确认要退出游戏吗」
    SUMMON_RESULT = "summon_result"    # 召唤结果页（返回键无效，只能点左「返回」）
    RECONNECT = "reconnect"            # 「继续重连」
    RECONNECT_LOGIN = "reconnect_login"  # 「确定」→ 回登录页
    CONFIRM_DIALOG = "confirm_dialog"  # 通用确认弹窗（左红取消）
    DIALOG = "dialog"                  # 米色弹窗（公告/奖励/提示，点空白关闭）
    NAV_PAGE = "nav_page"              # 主城体系一级页（英雄/助阵/战役/历练…有底部导航条）
    LOADING = "loading"                # 黑屏加载（游戏重启/切场景，画面全黑只剩左上角小图标）
    UNKNOWN = "unknown"


def main_city(im: Image.Image) -> bool:
    """主城：顶部蓝天 + 右侧天空也是蓝的。

    2026-10-30：只测 (360,60) 会误判——巨龙牢窟「奥术主宰」页顶部冰蓝条实测
    (105,167,212)，和主城 (107,166,223) 几乎一样，导致 ensure_main_city 认为
    已经在主城而不做任何事，后面的任务全在错误的页面上乱点。
    加右侧 (520,40) 的蓝色判据区分：主城 (117,172,234)，龙窟页 (41,57,60)。
    用相对差（B−R、B−G）而不是绝对阈值，弹窗压暗主城时也能认出来。

    2026-11-03：暮光要塞/邪能神殿这两个「副本地图」页顶部同样是蓝天
    （实测暮光要塞 (83,165,223)/(25,64,130) 两个判据都过），所以 classify
    在调用本函数前先用标题模板把它们排除，见 clone_page()。
    """
    R, G, B = avg(im, 360, 60, r=8)
    if not (B > 210 and 140 < G < 200 and R < 125):
        return False
    R2, G2, B2 = avg(im, 520, 40, r=8)
    return B2 > R2 + 60 and B2 > G2 + 15


# 顶部标题与主城同样「蓝天」的副本地图页：只靠像素分不开，用标题模板排除。
_CLONE_PAGE_TITLES = ("标题_暮光要塞.png", "标题_邪能神殿.png")


def clone_page(im: Image.Image) -> bool:
    """是不是「暮光要塞 / 邪能神殿」这类会被 main_city 误判的副本地图页。

    模板命中分数实测：暮光要塞页 标题_暮光要塞 命中；主城 best=0.370 不命中。
    延迟导入 template，避免 vision 顶层依赖 cv2。
    """
    from . import template as T
    for name in _CLONE_PAGE_TITLES:
        try:
            if T.VI.find(im, name, 0.90) is not None:
                return True
        except Exception:  # noqa: BLE001 - 模板缺失时不影响其它判据
            continue
    return False


def city_dim(im: Image.Image) -> bool:
    R, G, B = avg(im, 110, 1225, r=8)
    return (R + G + B) < 170


def quit_dialog(im: Image.Image) -> bool:
    """「确认要退出游戏吗」：左右两个浅灰按钮，中间是深色缝隙。

    活动页的奖励卡片也是浅色，但 (360,720) 不会是深色缝隙，借此排除。
    """
    R, G, B = avg(im, 170, 720, r=6)
    if not (R > 190 and G > 190 and B > 190 and abs(R - B) < 12):
        return False
    # 2026-11-06 实测真机弹窗（uiautomator 证实 text="确认要退出游戏吗？"）：
    # 两个按钮 y 687~759，中缝 x≈355~367 是 (137~154) 的灰，avg(r=6) 取到 149，
    # 旧阈值 sum<=420（即单通道<=140）判不出来。改成单通道 <=180 仍然安全：
    # 105 张 720x1280 fixtures 全量跑过，误报 0 张。
    R2, G2, B2 = avg(im, 360, 720, r=6)
    if R2 > 180 or G2 > 180 or B2 > 180:   # 中间也是亮的 → 整块面板，不是按钮行
        return False
    R3, G3, B3 = avg(im, 540, 720, r=6)    # 右按钮右下角（479 会压到按钮上的文字，实测只剩 164）
    return R3 > 190 and G3 > 190 and B3 > 190


def dialog_confirm(im: Image.Image) -> bool:
    """有确认框压在上面：整屏被压暗、且不是物品说明浮层。

    2026-11-20 审计 M1/M2：`confirm_dialog()` 要求 (235,700) 是红像素，全库 5867 帧
    **一次都没命中**（取消钮在弹窗里的位置随弹窗高度变，不在固定点），于是悬赏刷新
    确认框、铁匠铺一键50级确认框、助战升级确认框、副本付费扫荡确认框四条分支
    永远进不去 —— 该拦的不拦。这里改用已大量验证的 `modal_dim()`（999 帧压暗为真、
    24 张真弹窗全命中），并排除「物品说明浮层」（那种没有确认钮）。
    """
    return modal_dim(im) and not item_popup(im)


def confirm_dialog(im: Image.Image) -> bool:
    """通用确认弹窗：左侧红色「取消」按钮 **且** 整屏被压暗（真的模态弹窗）。

    2026-11-09 修（logs\_confirm_scan.py）：只判 (235,700) 是不是红像素会把
    「福利·英雄集结」这种整页活动页误判成确认弹窗 —— 那张脸上 (235,700) 正好是
    一个红色奖励图标。后果是 ensure_main_city 里的 handle_interruptions() 每次都
    判定「遇到确认弹窗」去点 (235,700)（在那个页面上是空点），于是 14 次 tries
    全烧在同一个页面上，最后报「没能回到主城」→ 任务失败。实测该页真正的出口是
    左下 BACK(88,1205)，一次就回主城。
    728 张取证帧统计：43 张误报全是这张活动页（modal_dim=False），24 张真弹窗
    （公告/圣物确认/布阵保存/战令付费/邪能加成/英雄突破…）全部 modal_dim=True。
    """
    return is_red(im, 235, 700, r=8) and modal_dim(im)


def loading_black(im: Image.Image) -> bool:
    """黑屏加载态：整屏几乎全黑（2026-11-19 06:54 事故帧实测全屏均值 2.2，最大 255）。

    这个状态以前落到 UNKNOWN，`ensure_main_city` 认为「没有可用出口」直接放弃，
    连着两个任务就中止整轮。它其实只需要等（或重启游戏），不是死页面。
    """
    try:
        w, h = im.size
        n = 0
        tot = 0
        for y in range(120, h - 80, 120):
            for x in range(60, w - 60, 120):
                R, G, B = im.getpixel((x, y))
                tot += 1
                if R + G + B >= 36:      # 明显不是黑的点
                    n += 1
        return tot > 0 and n <= max(1, tot // 20)
    except Exception:
        return False


def title_screen(im: Image.Image) -> bool:
    """标题页「开始游戏」大金按钮。

    2026-11-19 06:06 实测两个问题：
    1. 改版后的「开始游戏」是金底黑字，中心点被字形盖住 —— `is_gold(360,1000,r=8)`
       在真帧上是 False，于是标题页一路落到 `battle_page` 被判成「战斗中」，
       回主城流程按战斗乱点，最后「登录超时」；
    2. 只靠「(360,1000) 是金的」又会把一堆米色弹窗（98元/晋升为司令/挑战…）当成标题页。
    现在：先模板确认（阈值 0.90），没命中再看金钮兜底；命中后用 OCR 小框
    确认那行字就是「开始游戏」，否则一律不算标题页。
    """
    if main_city(im):
        return False
    hit = False
    try:
        from . import template as _T
        hit = _T.VI.find(im, "登录页_开始游戏.png", 0.90,
                         roi=(250, 950, 480, 1060)) is not None
    except Exception:          # pragma: no cover - 模板缺失时退回像素判据
        hit = False
    if not hit:
        if is_gold(im, 150, 1000, r=8):
            return False
        hit = is_gold(im, 360, 1000, r=8)
    if not hit:
        return False
    try:
        from . import textocr as _ocr
        if not _ocr.available():
            return True                 # 没有 OCR 时退回旧的像素判据
        # 小框只框「开始游戏」那行字（bbox 293,984,426,1024），面积小 → OCR 快
        txt = _ocr.read_text(im, (288, 976, 432, 1032)).replace(" ", "")
        return "开始游戏" in txt
    except Exception:                   # pragma: no cover
        return True


def trials_hub(im: Image.Image) -> bool:
    """历练页：底部是紫蓝色星光背景（见 trials_hub 探测点）。"""
    R, G, B = avg(im, 360, 1100, r=8)
    return B > 150 and B > R + 30 and not main_city(im)


def deploy_page(im: Image.Image) -> bool:
    return is_green(im, 270, 1230, r=18)


def _battle_speed_label(im: Image.Image) -> bool:
    """战斗界面右侧的倍速标签（×1/×2/×4）；别的页面没有这个控件。

    cv2 模板惰性导入：视觉层平时只用 PIL，这里兜底时才用模板匹配。
    实测战斗帧 ≥0.79，非战斗最高 0.69（公会试炼保存弹窗虽然有 0.89，但它
    底部没有 5 张亮英雄卡，进不到这一步）。
    """
    try:
        from . import template as _T
    except Exception:          # pragma: no cover - cv2 不可用时退回纯像素判据
        return False
    best = 0.0
    for name in ("倍速_x1.png", "倍速_x2.png", "倍速_x4.png"):
        try:
            best = max(best, _T.VI.best_score(im, name, roi=(625, 860, 690, 915)))
        except Exception:
            continue
    return best >= 0.75


def battle_page(im: Image.Image) -> bool:
    """战斗中：底部 5 张英雄卡那一排是亮的，且右侧有战斗控制。

    2026-10-30 修正：有的塔层（如守护者塔 708 层）战场地面是亮的，
    旧判据「(360,900) 偏暗」会把正常战斗判成 unknown——爬塔因此把战斗当成
    “不认识的界面”直接回主城重进（日志里每次胜利后都会跳一次主城）。
    现在改成：英雄卡通亮 + （中部偏暗 或 右侧 ×1/×2/×4 倍速标签命中）。
    全屏促销页/铁匠铺等列表页既没有倍速标签、中部也偏亮，仍然会被排除。
    """
    bright = 0
    for x in (155, 260, 365, 470, 570):
        if is_bright(im, x, 1050, r=8, threshold=330):
            bright += 1
    if bright < 3:
        return False
    # 2026-11-02：战役地图底部是横贯整行的金色「挑战NN-N」大按钮（x 250~620），
    # 会让上面的亮像素判据命中、中部又偏暗 → 地图被误判成战斗，主线任务无限按跳过。
    if all(is_gold(im, x, 1055, r=14) for x in (300, 360, 430)):
        return False
    R, G, B = avg(im, 360, 900, r=8)
    if (R + G + B) < 330:
        # 2026-10-30：英雄升星页底部是一排亮按钮、中部选择区偏暗，会被判成 battle
        # （脚本会对它连按「跳过」）。有页面标题锚点的界面一律不算战斗。
        try:
            from . import titles as _titles
            if _titles.identify(im) is not None:
                return False
        except Exception:      # pragma: no cover
            pass
        return True
    return _battle_speed_label(im)


def beige_dialog(im: Image.Image) -> bool:
    """登录后的「公告」整页弹窗（米色、四行大按钮）。

    只认公告特有的色调：行区 (360,374)/(360,442) 是偏黄米色 (201,176,141)；
    游戏内圣物/铁匠铺等面板是偏灰米色 (212,201,182)，会被 (R−B)/(G−B) 条件排除。
    英雄列表页的金色卡片底色 (222,201,157) 也会撞色，所以再要求两侧背景被压暗
    （公告是模态弹窗；英雄页两侧 (60,700)/(660,700) 是亮英雄卡，实测 R+G+B ≥ 414）。
    """
    ok = 0
    for x, y in ((360, 374), (360, 442)):
        R, G, B = avg(im, x, y, r=8)
        if R > 190 and G > 160 and 55 <= (R - B) <= 95 and (G - B) > 25:
            ok += 1
    if ok != 2:
        return False
    for x, y in ((60, 700), (660, 700)):
        R, G, B = avg(im, x, y, r=8)
        if (R + G + B) > 380:      # 两侧是亮的 → 普通页面，不是模态弹窗
            return False
    return True


def victory_banner(im: Image.Image) -> bool:
    """结算页右上角的「胜利」大字是暖金色；「失败」是淡紫白色。

    实测：胜 (238,186,89)，败 (207,180,166)，用 R−B>80 区分。
    """
    R, G, B = avg(im, 560, 300, r=6)
    return R > 200 and (R - B) > 80


def result_button(im: Image.Image) -> tuple[int, int] | None:
    """返回结算页主按钮（下一关/确定/再次挑战）的坐标；无则 None。"""
    for pos in ((465, 1075), (495, 1130), (465, 1090), (370, 1130), (360, 1100)):
        if is_gold(im, *pos, r=18):
            return pos
    return None


def result_title_bar(im: Image.Image) -> bool:
    """结算页「当前战斗」标题条：(70,645)。

    胜利页是饱和暖棕 (119,64,40)；失败页是紫 (82,79,132)。
    米色弹窗和战斗画面 (27,69,108) 都要排除掉。
    """
    R, G, B = avg(im, 70, 645, r=8)
    warm = 90 < R < 175 and (R - B) > 60 and (R - G) > 30
    purple = B > 120 and (B - R) > 40 and R < 100
    return warm or purple


def defeat_page(im: Image.Image) -> bool:
    """失败结算页：右上角「失败」淡紫大字 + 「当前战斗」标题条 + 深色底。

    (560,300) 的失败大字实测 (195,164,161)；传奇试炼页同一位置是蓝色立绘 (62,104,154)，
    曾因此把试炼页误判成失败结算页，导致回主城反复横跳。
    """
    R, G, B = avg(im, 360, 700, r=8)
    if (R + G + B) > 340:          # 面板类页面这里是米色信息区（很亮）
        return False
    R2, G2, B2 = avg(im, 560, 300, r=8)
    if not (R2 > 180 and G2 > 150 and B2 > 140 and (R2 - B2) > 20):
        return False
    return result_title_bar(im) and not victory_banner(im)


def hero_break_dialog(im: Image.Image) -> bool:
    """英雄详情「进阶」的属性加成预览框。

    判据：底部橙色确认钮 (360,917)（页面本体同位置是立绘/背景）+ 米色面板 (360,700)。
    主页面的大按钮在 y≈1060，所以 y=917 的橙色按钮只在预览框里出现。
    """
    R, G, B = avg(im, 360, 917, r=12)
    if not (R > 190 and 95 < G < 155 and B < 130 and (R - G) > 60 and (R - B) > 80):
        return False
    return _pale(*avg(im, 360, 700, r=10))


def lineup_save_dialog(im: Image.Image) -> bool:
    """布阵页按返回时的「温馨提示：当前英雄布阵未保存，是否保存？」

    米色弹窗 + 左浅珊瑚色「取消」(200,782) + 右金色「保存」(465,782)。
    地精宝藏/塔等布阵页都会弹；不处理的话回主城会一直在布阵页和弹窗之间来回按返回。
    取消按钮实测 (207,143,109)（比 is_red 的饱和红更淡），所以单独判。
    """
    R, G, B = avg(im, 200, 782, r=12)
    if not (R > 190 and G < 170 and B < 145 and (R - G) > 45 and (R - B) > 70):
        return False
    if not is_gold(im, 465, 782, r=18):
        return False
    return _pale(*avg(im, 360, 555, r=10))


def tooltip_open(im: Image.Image) -> bool:
    """居中的道具/详情弹窗：紫色标题条（圣物源能）或粉红标题条（圣物详情）。"""
    def purple(r, g, b):
        return 80 < r < 145 and g < 115 and b > 120 and (b - r) > 30

    def pink(r, g, b):
        return r > 180 and g < 165 and b < 155 and (r - g) > 50

    a = avg(im, 120, 390, r=8)
    b = avg(im, 500, 390, r=8)
    if purple(*a) and purple(*b):
        return True
    c = avg(im, 360, 255, r=8)
    d = avg(im, 360, 300, r=8)
    return pink(*c) and pink(*d)


def button_badge(im: Image.Image, box=(440, 1028, 522, 1095)) -> bool:
    """按钮右上角的红色「!」角标 = 这个按钮现在可以点（材料够）。

    注意和橙色按钮区分：橙色大按钮实测 (207,112,80)，B≈80；红色角标 B≈15~30、G<105。
    """
    x0, y0, x1, y1 = box
    n = 0
    for y in range(y0, min(y1, im.height), 2):
        for x in range(x0, min(x1, im.width), 2):
            R, G, B = im.getpixel((x, y))
            if R > 185 and G < 105 and B < 65 and (R - G) > 95:
                n += 1
    return n >= 8


def _pale(r: float, g: float, b: float) -> bool:
    """弹窗面板的米色底。"""
    return r > 185 and g > 170 and b > 140 and 15 < (r - b) < 95


def red_count(im: Image.Image, x: int, y: int, r: int = 12) -> int:
    """小范围内红色像素数（按钮角标「!」约 50，空白处 0）。"""
    n = 0
    for dx in range(-r, r + 1, 2):
        for dy in range(-r, r + 1, 2):
            R, G, B = im.getpixel((max(0, min(im.width - 1, x + dx)),
                                    max(0, min(im.height - 1, y + dy))))
            if R > 190 and G < 130 and B < 110 and (R - G) > 90:
                n += 1
    return n


def red_ribbon(im: Image.Image, box) -> bool:
    """格子里的红色「领取」横飘带（2026-11-03 实测签到页）。

    只认「宽扁横条」：实测领取飘带连通块 86×35（宽/高≈2.5），
    而「第27天/第29天」卡片上的红色图标是 82×46（宽/高≈1.8），
    所以用 高度≤42 且 宽高比≥2.1 把图标排除，避免误点奖励图标。
    """
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(x1, im.width), min(y1, im.height)
    pts: set[tuple[int, int]] = set()
    for y in range(y0, y1):
        for x in range(x0, x1):
            R, G, B = im.getpixel((x, y))
            if R > 140 and G < 90 and B < 90 and (R - G) > 60:
                pts.add((x, y))
    while pts:
        seed = pts.pop()
        q = deque([seed])
        comp = [seed]
        while q:
            cx, cy = q.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                np_ = (cx + dx, cy + dy)
                if np_ in pts:
                    pts.discard(np_)
                    q.append(np_)
                    comp.append(np_)
        if len(comp) < 300:
            continue
        bw = max(p[0] for p in comp) - min(p[0] for p in comp) + 1
        bh = max(p[1] for p in comp) - min(p[1] for p in comp) + 1
        if bw >= 80 and bh <= 42 and bw / bh >= 2.1:
            return True
    return False


def signin_claim(im: Image.Image, box) -> bool:
    """签到格是不是「领取」（而不是付费的「再领一次」）。

    2026-11-03 实测：两种飘带都是深色半透明条 + 绿字，形状一样
    （红飘带判据会同时命中），中文 OCR 又不可用，只能量绿字宽度：
      领取   = 2 字，绿字像素宽 ≈35（303 px）
      再领一次 = 4 字，绿字像素宽 ≈75（481 px）
    因此红飘带成立 + 绿字宽 ≤55 才算真的「领取」。
    """
    if not red_ribbon(im, box):
        return False
    x0, y0, x1, y1 = box
    xs = []
    for y in range(max(0, y0), min(y1, im.height)):
        for x in range(max(0, x0), min(x1, im.width)):
            R, G, B = im.getpixel((x, y))
            if G > 110 and G > R + 30 and G > B + 30:
                xs.append(x)
    if len(xs) < 80:
        return False
    return (max(xs) - min(xs)) <= 55


def forge_cost_affordable(im: Image.Image, box: tuple[int, int, int, int] = (320, 1025, 400, 1058)) -> bool:
    """铁匠铺强化页「一键50级」上方的价格文字：绿色=金币够，红色=金币不足。

    实测金币够时绿色像素 202 / 红色 0；金币不足时绿色 0 / 红色 223。
    不能用 is_green 整体平均（文字只占小部分，背景米色会稀释掉）。
    """
    x0, y0, x1, y1 = box
    green = red = 0
    for y in range(y0, min(y1, im.height)):
        for x in range(x0, min(x1, im.width)):
            R, G, B = im.getpixel((x, y))
            if G > 90 and (G - R) > 40 and (G - B) > 25:
                green += 1
            elif R > 140 and (R - G) > 70 and B < 120:
                red += 1
    return green >= 30 and green > red


def forge_star_dialog(im: Image.Image) -> str:
    """升星页点「一键升星」后的批量弹窗：'ready' 有可升 / 'locked' 没有符合条件的装备 / 'none' 没弹窗。

    判据：右上角红色圆形关闭钮 + 中央按钮颜色（金=可升，灰米=不可升）。
    正常页面在同一位置没有红色关闭钮，所以不会误判。
    """
    red = 0
    for y in range(270, 345):
        for x in range(620, min(700, im.width)):
            R, G, B = im.getpixel((x, y))
            if R > 165 and G < 100 and B < 100 and (R - G) > 75 and (R - B) > 75:
                red += 1
    if red < 30:
        return "none"
    R, G, B = avg(im, 360, 755, r=14)
    if R >= 212 and G >= 150 and (R - B) >= 85:
        return "ready"
    return "locked"



def hero_level_is_resonance(im: Image.Image, cx: int, y0: int, y1: int) -> bool:
    """英雄卡底部的等级文字是不是蓝色（共鸣带出来的等级）。

    白色 = 实际培养的（可以进阶）；蓝色 = 共鸣等级（跟着共鸣支柱走，不用升级）。
    实测：培养英雄 0 个蓝像素；共鸣英雄 40~360 个。
    """
    blue = 0
    for y in range(y0, min(y1, im.height)):
        for x in range(max(0, cx - 50), min(cx + 50, im.width)):
            R, G, B = im.getpixel((x, y))
            if (B - R) > 40 and B > 150:
                blue += 1
    return blue >= 15


def item_popup(im: Image.Image) -> bool:
    """道具说明弹窗（如「进阶石」不足时的获取途径窗）：中央米色面板 + 两侧不是米色。

    神器页弹窗左侧是亮的道具列表、英雄页两侧是压暗背景，两种都要认：
    关键判据是 (360,600)/(360,800) 都是米色面板且左右边缘 (60,600)/(620,600) 不是米色。
    实测：神器「升星」不足弹窗 True；英雄进阶弹窗 True；各面板页 False。

    2026-11-07 补一条：英雄列表页 / 图鉴 / 导航页整页都是米色，光看
    (360,600)/(360,800) 会把它们也判成弹窗（`logs/screens/ui_335.png`、
    `ui_391.png` 实测 True）。真弹窗是居中模态，**上方 (360,300) 一定是压暗背景**
    （实测 (57,52,45)/(26,18,20)），而米色页面那里仍是卡片色 (236,205,201)。
    所以再加 `not _pale(avg(im, 360, 300))`：551 张历史帧里 old=True 58 张 →
    new=True 32 张，26 张翻转全是这类米色页面，真弹窗（进阶石/荣耀结晶/神铸辉石/
    圣坛精露/助战徽记不足等）一张都没丢。
    """
    if not (_pale(*avg(im, 360, 600, r=8)) and _pale(*avg(im, 360, 800, r=8))):
        return False
    if _pale(*avg(im, 60, 600, r=8)) or _pale(*avg(im, 620, 600, r=8)):
        return False
    return not _pale(*avg(im, 360, 300, r=8))


def reconnect_dialog(im: Image.Image) -> bool:
    """「您与游戏世界已失去连接，请选择重新登录或重试」：左灰「返回登录」+ 右金「继续重连」。

    注意：公会试炼的「保存」弹窗也是 (465,748) 金色，但左边是红色「重新挑战」，
    必须用左键颜色排除，否则会把保存弹窗当断线。
    """
    if not is_gold(im, 465, 748, r=12):
        return False
    if is_red(im, 234, 748, r=10):
        return False
    R, G, B = avg(im, 234, 748, r=8)
    if not (_pale(R, G, B) and abs(R - G) < 45):
        return False
    # 2026-11-10 实测（帧 `logs/cov5_元素神殿.png`）：荣耀殿堂·元素神殿页上
    # (465,748) 是领主立绘的金色块、(234,748) 是淡黄底（245,211,155），也会凑齐
    # 「右金 + 左不红 + 左浅色」三条件，被误判成断线弹窗。真弹窗左键「返回登录」
    # 是灰白色，不是暖色底 —— 这里额外要求它接近灰（B 离 R/G 都不远）。
    return abs(R - B) < 55 and abs(G - B) < 40


def reconnect_login_dialog(im: Image.Image) -> bool:
    """只有「确定」的断线弹窗（点完回登录页）。

    深海秘宝等活动页在 (360,748) 也有金色按钮，所以要同时要求上下文是米色弹窗面板。
    """
    if not is_gold(im, 360, 748, r=12) or is_gold(im, 465, 748, r=12):
        return False
    a = avg(im, 360, 600, r=8)
    b = avg(im, 150, 600, r=8)
    if not (_pale(*a) and _pale(*b)):
        return False
    # 2026-11-19 02:50 事故：付费商店页「福利礼包」也在 (360,748) 有金钮、
    # 旁边是米色卡片，被判成断线弹窗 → 对着付费页盲点 5 下。
    # 断线弹窗是「整屏压暗 + 居中面板」，屏幕下半的左/右边缘是暗的；
    # 商店页那两处是亮的背景（实测 (228,217,185) / (226,213,180)）。
    bl = avg(im, 60, 1000, r=8)
    br = avg(im, 660, 1000, r=8)
    if (sum(bl) / 3.0) > 200 or (sum(br) / 3.0) > 200:
        return False
    return True


def summon_result(im: Image.Image) -> bool:
    """召唤结果页：底部「返回」(220,1180) 米色 + 「召唤一次」(502,1180) 亮金。

    2026-11-05 01:07 实测帧：bp 免费一抽后整屏就是这个页，安卓返回键无效、没有红 X，
    ensure_main_city 会在这里无限按 (88,1205)。按钮所在行是 y=1180（不是 1125）：
    左 (107-333) 心 (191,163,129)，右 (390-615) 心 (229,187,86)。
    """
    if not is_gold(im, 502, 1180, r=14):
        return False
    R, G, B = avg(im, 220, 1180, r=14)
    if not (R > 172 and G > 142 and 35 <= (R - B) <= 80):
        return False
    return not main_city(im) and not beige_dialog(im)


def find_beige_button(im: Image.Image) -> tuple[int, int] | None:
    """底部一带里的浅米色大按钮（全屏页的「返回/确定」）。找不到返回 None。"""
    w, h = im.size
    for y in range(1100, min(h - 60, 1240), 20):
        run = None
        for x in range(40, w - 40, 20):
            R, G, B = avg(im, x, y, r=10, step=6)
            pale = R > 172 and G > 142 and 35 <= (R - B) <= 80
            if pale:
                run = [x, x] if run is None else [run[0], x]
            else:
                if run and run[1] - run[0] >= 60:
                    return (run[0] + run[1]) // 2, y
                run = None
        if run and run[1] - run[0] >= 60:
            return (run[0] + run[1]) // 2, y
    return None


# ---------- 2026-11-06：底部导航条（主城体系一级页） ----------
# 主城/英雄/助阵/战役地图/战斗/历练 hub/地精 hub 这些「一级页」底部都是同一套
# 六页签导航条（y≈1186~1272）；二级页（商店、排行榜、荣耀之书面板……）没有。
# 为什么需要它：一级页左下角没有返回箭头（那个位置被导航条占着），
# ensure_main_city 在这里按 BACK 会整屏 diff≈0.0016 空转，直到 tries 用完。
# 实测分层（105 张 fixtures + 60 张真实截图）：一级页 ≥0.90，其余 ≤0.50。
# 用 72 个采样点逐点比色：单次约 0.5 ms，比模板匹配（192 ms）便宜两个量级。
NAV_POINTS = (
    (12, 1204, 16, 30, 30), (42, 1204, 73, 55, 45), (72, 1204, 250, 242, 218),
    (102, 1204, 79, 56, 45), (132, 1204, 108, 75, 60), (162, 1204, 241, 197, 99),
    (192, 1204, 129, 57, 26), (222, 1204, 128, 140, 127), (252, 1204, 62, 39, 32),
    (282, 1204, 136, 96, 62), (312, 1204, 88, 62, 46), (342, 1204, 62, 59, 59),
    (372, 1204, 159, 172, 165), (402, 1204, 93, 68, 54), (432, 1204, 92, 63, 50),
    (462, 1204, 62, 141, 61), (492, 1204, 224, 204, 160), (522, 1204, 93, 64, 51),
    (552, 1204, 78, 79, 95), (582, 1204, 168, 69, 13), (612, 1204, 89, 61, 49),
    (642, 1204, 229, 221, 183), (672, 1204, 186, 79, 27), (702, 1204, 16, 29, 29),
    (12, 1220, 16, 29, 29), (42, 1220, 164, 104, 100), (72, 1220, 193, 152, 114),
    (102, 1220, 204, 102, 67), (132, 1220, 206, 150, 91), (162, 1220, 238, 186, 93),
    (192, 1220, 66, 46, 37), (222, 1220, 217, 151, 105), (252, 1220, 211, 147, 100),
    (282, 1220, 92, 63, 51), (312, 1220, 90, 66, 50), (342, 1220, 176, 127, 63),
    (372, 1220, 84, 68, 58), (402, 1220, 88, 68, 62), (432, 1220, 89, 61, 49),
    (462, 1220, 100, 170, 70), (492, 1220, 219, 208, 165), (522, 1220, 92, 63, 51),
    (552, 1220, 81, 50, 47), (582, 1220, 204, 204, 204), (612, 1220, 92, 63, 51),
    (642, 1220, 113, 116, 133), (672, 1220, 91, 62, 50), (702, 1220, 16, 30, 30),
    (12, 1236, 16, 30, 30), (42, 1236, 205, 168, 140), (72, 1236, 114, 69, 32),
    (102, 1236, 219, 185, 154), (132, 1236, 54, 36, 30), (162, 1236, 210, 126, 71),
    (192, 1236, 90, 61, 49), (222, 1236, 90, 61, 49), (252, 1236, 177, 113, 78),
    (282, 1236, 90, 61, 49), (312, 1236, 117, 104, 98), (342, 1236, 93, 68, 54),
    (372, 1236, 83, 65, 59), (402, 1236, 162, 109, 56), (432, 1236, 90, 61, 49),
    (462, 1236, 168, 156, 112), (492, 1236, 174, 147, 112), (522, 1236, 90, 61, 49),
    (552, 1236, 138, 95, 57), (582, 1236, 48, 33, 25), (612, 1236, 90, 61, 49),
    (642, 1236, 186, 116, 99), (672, 1236, 89, 60, 48), (702, 1236, 16, 29, 29),
)

NAV_TOL = 30          # 每个采样点允许的单通道最大偏差
NAV_THRESHOLD = 0.80  # 命中率阈值（一级页实测 ≥0.90，其余 ≤0.50）


def nav_score(im: Image.Image) -> float:
    """底部导航条与参考图的逐点命中率（0~1）。非 720×1280 帧一律 0。"""
    if im.width < 708 or im.height < 1237:
        return 0.0
    hit = 0
    for x, y, r, g, b in NAV_POINTS:
        pr, pg, pb = im.getpixel((x, y))[:3]
        if abs(pr - r) <= NAV_TOL and abs(pg - g) <= NAV_TOL and abs(pb - b) <= NAV_TOL:
            hit += 1
    return hit / len(NAV_POINTS)


def navigation_bar(im: Image.Image, threshold: float = NAV_THRESHOLD) -> bool:
    """当前画面是否带主城体系的一级页底部导航条（主城/英雄/助阵/战役/战斗/历练…）。"""
    return nav_score(im) >= threshold


def modal_dim(im: Image.Image, box=(0, 0, 720, 120), thresh: int = 90,
              ratio: float = 0.95, step: int = 6) -> bool:
    """整屏被压暗的居中模态弹窗（顶部条几乎全黑）。

    2026-11-07 实测「挑战失败」弹窗顶部条 dark≈1.00；正常主城 0.22、圣物页 0.44，
    所以这条判据只对「全屏压暗 + 居中面板」成立。只做闸门，真正动作还要 OCR 确认文字。
    """
    if im.width < 600 or im.height < 200:
        return False
    n = d = 0
    for y in range(box[1], min(box[3], im.height), step):
        for x in range(box[0], min(box[2], im.width), step):
            R, G, B = im.getpixel((x, y))[:3]
            n += 1
            if (R + G + B) / 3 < thresh:
                d += 1
    return n > 0 and (d / n) >= ratio


def classify(im: Image.Image) -> State:
    """按优先级判断当前画面。顺序很关键：先排弹窗，再排页面。"""
    # 2026-11-03：暮光要塞/邪能神殿页与主城同样蓝天，先排除，否则
    # ensure_main_city 会把这些页当主城，后面的任务在错误页面上乱点。
    if not clone_page(im) and main_city(im):
        return State.MAIN_CITY if not city_dim(im) else State.MAIN_CITY_DIM
    if quit_dialog(im):
        return State.QUIT_DIALOG
    # 断线：必须同时满足按钮 + 弹窗面板特征（避免和保存/活动页的按钮混淆）
    if reconnect_dialog(im):
        return State.RECONNECT
    if reconnect_login_dialog(im):
        return State.RECONNECT_LOGIN
    # 黑屏加载：必须排在标题/战斗之前（全黑帧会被 battle_page 的「中部偏暗」命中）
    if loading_black(im):
        return State.LOADING
    if title_screen(im):
        return State.TITLE
    # 米色弹窗（公告/奖励/提示）：必须在结算/战斗之前挡掉，否则会被误判
    if beige_dialog(im):
        return State.DIALOG
    # 召唤结果页（bp 免费一抽后的整屏页：返回键无效、无红 X）
    if summon_result(im):
        return State.SUMMON_RESULT
    # 结算页：横幅 + 按钮（失败页可能没有亮按钮，但一定有「当前战斗」标题条）
    btn = result_button(im)
    win = victory_banner(im)
    if win and btn is not None:
        if btn == (495, 1130):
            return State.RESULT_TREE
        if btn == (370, 1130):
            return State.RESULT_GENERIC
        if btn == (360, 1100):
            return State.RESULT_LEGEND
        return State.RESULT_TOWER
    if defeat_page(im):
        return State.RESULT_DEFEAT
    if deploy_page(im):
        return State.DEPLOY
    if battle_page(im):
        return State.BATTLE
    if trials_hub(im):
        return State.TRIALS_HUB
    if confirm_dialog(im):
        return State.CONFIRM_DIALOG
    # 2026-11-06：带底部导航条 = 主城体系一级页（英雄/助阵/战役/历练 hub…）。
    # 这些页左下角没有返回箭头（位置被导航条占着），按 BACK 会整屏 diff≈0.001 空转；
    # 必须放在最后：battle_page/trials_hub 等更具体的判据要先命中。
    if navigation_bar(im):
        return State.NAV_PAGE
    return State.UNKNOWN


# ---------- 2026-10-31：列表/角标/浮层 ----------

def red_badge(im: Image.Image, x: int, y: int, r: int = 16, need: int = 6) -> bool:
    """某个位置是不是红色「!」角标（排行榜奖励格、底部页签都是这个样式）。"""
    return red_count(im, x, y, r) >= need


def red_in_rect(im: Image.Image, box, step: int = 2) -> int:
    """矩形内红色像素数，判据与 `red_count` 一致。"""
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(im.width, x1), min(im.height, y1)
    n = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            R, G, B = im.getpixel((x, y))
            if R > 190 and G < 130 and B < 110 and (R - G) > 90:
                n += 1
    return n


def red_clusters(im: Image.Image, box, gap: int = 8, min_n: int = 40,
                 step: int = 1) -> list[tuple[int, int, int]]:
    """在 box 里找红色「!」角标的连通块，返回 [(cx, cy, 像素数), ...]（从左到右）。

    2026-11-10：主线/巨龙/阵营的领奖面板都不是「金色领取按钮」形态，而是
    **奖励图标右上角挂一个红「!」**（红 (R>185,G<105,B<65,R-G>95)，约 130px）。
    用固定点判会漏（图标位置随里程碑数量漂移），所以按连通块找。
    """
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(im.width, x1), min(im.height, y1)
    cols: dict[int, list[int]] = {}
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            R, G, B = im.getpixel((x, y))
            if R > 185 and G < 105 and B < 65 and (R - G) > 95:
                cols.setdefault(x, []).append(y)
    if not cols:
        return []
    xs = sorted(cols)
    groups: list[list[int]] = []
    cur = [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= gap:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    out = []
    for g in groups:
        ys = [y for x in g for y in cols[x]]
        n = sum(len(cols[x]) for x in g)
        if n >= min_n:
            out.append(((min(g) + max(g)) // 2, (min(ys) + max(ys)) // 2, n))
    return out


def red_badge_near(im: Image.Image, cx: int, cy: int,
                   dx0: int, dy0: int, dx1: int, dy1: int,
                   need: int = 6, step: int = 2) -> bool:
    """角标「!」的窗口判据：在相对 (cx,cy) 的一块矩形里数红像素。

    2026-11-07：英雄羁绊页的「升级」按钮只有 64px 宽（bb 531,223-595,260），
    旧判据是固定单点 (cx+88, cy-10) —— 那已经落在按钮右侧 57px 的空白/屏幕边缘，
    角标真出现时很可能数不到。这里改成一个覆盖「按钮右上角 + 其右侧一小段」的窗口，
    实测无角标帧该窗口红像素为 0，不会误报。
    """
    return red_in_rect(im, (cx + dx0, cy + dy0, cx + dx1, cy + dy1), step) >= need


def gold_band_center(im: Image.Image, box, min_px: int = 5, min_h: int = 24,
                     step: int = 2) -> tuple[int, int] | None:
    """box 内金色像素最多的那条带子的质心，找不到返回 None。

    2026-11-08：结算页「下一关 / 确定 / 战败确定」三个按钮的竖直位置并不一致
    （实测金带中心 y = 1116 / 1118 / 1088），固定坐标压在按钮下沿时会偶尔 MISS，
    然后靠 ui.press 的 -8px 补偿才命中，白花约 2s。这里直接按实测金带取中心。
    """
    bands = gold_button_bands(im, box, min_px=min_px, min_h=min_h, step=step)
    if not bands:
        return None
    cx, cy, px = max(bands, key=lambda b: b[2])
    return (int(cx), int(cy))


def gold_button_bands(im: Image.Image, box, min_px: int = 5, min_h: int = 24,
                      step: int = 2, relax: int = 0) -> list[tuple[int, int, int]]:
    """在 box 内按行找亮金色按钮块，返回 [(cx, cy, 像素数), ...]，从上到下。

    用于「领取后整列会浮动」的列表（官阶/福利），不再依赖固定 y。
    只认 is_gold 那一档的像素（浅土黄「前往」、绿色「已领取」都不算）。

    2026-11-04：新增 relax（0/1/2）——用户要求模板/颜色识别失败时按
    0.90/0.80/0.70 三档召回，找不到可点按钮就用更松的颜色阈值再试一次。
    """
    thr = ((212, 150, 85), (200, 138, 72), (188, 124, 60))[max(0, min(relax, 2))]
    min_total = (900, 700, 520)[max(0, min(relax, 2))]
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, im.width), min(y1, im.height)
    rows: list[tuple[int, int, int]] = []      # (y, px, sum_x)
    for y in range(y0, y1, step):
        cnt = sx = 0
        for x in range(x0, x1, step):
            R, G, B = im.getpixel((x, y))
            if R >= thr[0] and G >= thr[1] and (R - B) >= thr[2]:
                cnt += 1
                sx += x
        rows.append((y, cnt, sx))
    out: list[tuple[int, int, int]] = []
    run: list[tuple[int, int, int]] = []

    def _flush(band):
        if len(band) * step >= min_h:
            px = sum(r[1] for r in band)
            sx = sum(r[2] for r in band)
            cy = band[len(band) // 2][0]
            out.append((int(sx / px), cy, px))

    for r in rows:
        if r[1] >= min_px:
            run.append(r)
        else:
            _flush(run)
            run = []
    _flush(run)
    # 大按钮实测 3000+ 像素，金色按钮的抗锯齿边缘只有几百，按总量再筛一次
    return [b for b in out if b[2] >= min_total]


def gold_band_point(im: Image.Image, box, min_px: int = 900, r: int = 18):
    """金带里第一个「质心本身确实金色」的点；没有就返回 None。

    2026-11-08：邪能战斗帧的 (253,1056) 是金带质心，但那一像素是暗红 (119,60,58)
    —— 质心会被同一行里的装饰金像素带偏，所以必须用 is_gold 复核再点，
    否则是一次空点 + 一次坐标补偿（约 8s）。
    """
    for cx, cy, px in gold_button_bands(im, box):
        if px >= min_px and is_gold(im, cx, cy, r=r):
            return (cx, cy)
    return None


def gold_bands_any(im: Image.Image, box, **kw) -> list[tuple[int, int, int]]:
    """三档宽松召回：0→1→2 依次放宽颜色阈值，第一个非空结果直接返回。"""
    for relax in (0, 1, 2):
        bands = gold_button_bands(im, box, relax=relax, **kw)
        if bands:
            return bands
    return []



def diff_ratio(a: Image.Image, b: Image.Image, box=(50, 40, 670, 1200), tol: int = 25,
               step: int = 2) -> float:
    """两个画面在 box 内的差异像素占比（0~1）。用于校验某个格子/按钮是否真的变样。

    2026-11-04 新增：英雄升星的材料格点击后必须确认「高亮/勾选态」确实变了，
    整页 similar 粒度太粗（435 个采样点，单个格子只占几个点），所以按区域算。
    """
    if a.size != b.size:
        return 1.0
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, a.width), min(y1, a.height)
    diff = total = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            p, q = a.getpixel((x, y)), b.getpixel((x, y))
            total += 1
            if abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) > tol * 3:
                diff += 1
    return diff / total if total else 0.0


def star_material_picker(im: Image.Image) -> bool:
    """「请选择升星材料」里点材料格后弹出的「选择英雄」窗（2026-11-04 实测）。

    判据：米色面板 (360,600) + 底部金色「确定」(359,807)（实图量测 x260~458 / y770~845）
    + 弹窗外背景被压暗（(360,300) 不是米色）。该窗里显示「已选择：1/1」+ 英雄卡绿勾，
    按「确定」才真正把材料放进槽位。

    2026-11-07 全库复核（575 张 720×1280 帧）：只用前两条会误报 10 张——英雄列表页/
    助战网格页整页米色、恰好在 (359,807) 有个金钮（`hero_page_tabs.png`、
    `_va_hero_grid.png`、`_mark_0.png`、`_bb_before.png` 等）。真窗上方 (360,300)
    是压暗背景 `(25,36,47)`，那些页面是 `186~232`（明亮卡片）→ 加第三条后
    真窗（`star_mat_tap1_210.png`）保留、10 张误报全灭。
    """
    if not (_pale(*avg(im, 360, 600, r=8)) and is_gold(im, 359, 807, r=16)):
        return False
    return max(avg(im, 360, 300, r=8)) < 90


def mean_brightness(im: Image.Image, box=(0, 0, 120, 80), step: int = 6) -> float:
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, im.width), min(y1, im.height)
    tot = n = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            R, G, B = im.getpixel((x, y))
            tot += (R + G + B) / 3
            n += 1
    return tot / n if n else 0.0


def darkened(a: Image.Image, b: Image.Image, box=(0, 0, 120, 80), drop: float = 25.0) -> bool:
    """b 相比 a 在 box 内明显变暗 = 弹出了「获得奖励」这类全屏浮层。"""
    if a.size != b.size:
        return False
    return (mean_brightness(a, box) - mean_brightness(b, box)) >= drop


def orange_button_bands(im: Image.Image, box, min_px: int = 5, min_h: int = 24,
                        step: int = 2) -> list[tuple[int, int, int]]:
    """在 box 内按行找橙红色按钮块（神器「进阶」/传承「突破」/确认窗里的确定）。

    实测按钮填充约 (209,114,80)：R 高、G 中、B 低；金色按钮 (243,193,44) 的 G 明显更高，
    所以用 G<165 区分。返回 [(cx, cy, px), ...]，从上到下。
    """
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, im.width), min(y1, im.height)
    rows: list[tuple[int, int, int]] = []
    for y in range(y0, y1, step):
        cnt = sx = 0
        for x in range(x0, x1, step):
            R, G, B = im.getpixel((x, y))
            if R > 175 and 70 < G < 168 and B < 150 and (R - G) > 45 and (R - B) > 60:
                cnt += 1
                sx += x
        rows.append((y, cnt, sx))
    out: list[tuple[int, int, int]] = []
    run: list[tuple[int, int, int]] = []

    def _flush(band):
        if len(band) * step >= min_h:
            px = sum(r[1] for r in band)
            sx = sum(r[2] for r in band)
            cy = band[len(band) // 2][0]
            out.append((int(sx / px), cy, px))

    for r in rows:
        if r[1] >= min_px:
            run.append(r)
        else:
            _flush(run)
            run = []
    _flush(run)
    # 大按钮实测 3000+ 像素，金色按钮的抗锯齿边缘只有几百，按总量再筛一次
    return [b for b in out if b[2] >= 900]
