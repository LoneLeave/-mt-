"""数字识别：模板匹配（英雄等级 / 资源数字）。

游戏里数字是同一套字形，英雄详情页「等级 700」是青色 (约 40,140,120)，
铁匠铺价格是绿色 (约 70,150,70)，进阶石进度是橙色。
用颜色把数字像素切出来 → 分成单个字形 → 归一化 14×20 → 和 10 个数字模板比 IoU。

模板来自 2026-10-29 真机截图（700/750/800/17346/69412 五个样本），
未见过的截图与数字验证过：正确字形得分 0.8~1.0，次优 ≤0.62。
"""
from __future__ import annotations

from PIL import Image

GLYPH_W, GLYPH_H = 14, 20

TEMPLATES: dict[str, str] = {
    "0": "0000999999900000009999999000000999999999000099990009999000990000000990009900000009909999000000099999990000000999999900000009999999000000099999990000000999999900000009999999000000099900990000000990009900000009900099000000099000999900099990000999999999000000999999900000000049000000",
    "1": "0099999990000000999999900000009999999000000000009990000000000099900000000000999000000000009990000000000099900000000000999000000000009990000000000099900000000000999000000000009990000000000099900000000000999000000000009990000000000099900000000000999000000099999999999999999999999999",
    "2": "0000999999900000009999999000009999999999900000000000999000000000009990000000000099900000000000099000000000009990000000000099900000000000999000000000009990000000009990000000000999000000000009990000000009999900000000099900000000009990000000000099900000009999999999999999999999999999",
    "3": "0099999999900000999999999000999999099999909900000000099900000000000999000000000009990000000000099900000000099990000000999990000000009999900000000099999000000000000999900000000000099900000000000999000000000009990000000000099999000000000999990000000009999999999999999000999999999000",
    "4": "0000000049444000000000494440000000099999400000004999994000000449999940000009994499400000499004994000049940049940000490000499400049900004994044994000049940999400000499409999900499994099999449999944999999999999990000000444994000000000049940000000000499400000000004994000000000049940",
    "5": "0099999999999000999999999990009999999999990099900000000000999000000000999990000000009999900000000099999000000000999999999990009999999999999000990000009999000000000009990000000000099900000000000999000000000009990000000000099999000000009999999999999999909999999999900000000999000000",
    "6": "0000009999994000000099999940004999999999940099990000000044994000000000449940000000004494000000000099940000000000999999999999409999999999994099999900004994999940000049949994000000004999940000000049449400000000494499400000004400499900004994004999000049940049999999999000000099994000",
    "7": "3399999999999933999999999999666666666669990000000003999600000000039990000000000996600000000339960000000003399600000000099996000000000996000000000039960000000000399600000000009990000000000099900000000000999000000000009660000000003396600000000033966000000000399660000000003396600000",
    "8": "0000099999990000000999999900000999999999900099990000999900999000000099009990000000990099990000999900999900009999000999900099900009999999990000099999999990009990000999999999900000999999900000000099999000000000999999900000009999999000000099009999900999990009999999999000000099990000",
    "9": "0000999999900000009999999000009999909999900099900000999099990000000999999900000009999999000000099999990000000999999900000009999999000000099900999990999999000099999909990000000000099900000000000999000000000009990000000000099000000000009990000000000099900099999999900000009999990000",
}


def _green(R: int, G: int, B: int) -> bool:
    """青色/绿色数字：等级数字与铁匠铺价格都是这一类。"""
    return G > 115 and (G - R) > 50 and (G - B) > 5


MASKS = {
    "green": _green,
    "orange": lambda R, G, B: R > 190 and 90 < G < 190 and B < 110 and (R - B) > 110,
    "red": lambda R, G, B: R > 150 and (R - G) > 70 and B < 120,
    # 白字：议价数字、职业技能等级、神器等级、悬赏积分、挑战次数……
    # 这些数字印在深色/彩色底上，白色最亮；阈值取 195 防止米色面板底板混进来。
    "white": lambda R, G, B: R > 195 and G > 195 and B > 195,
    # 米白数字（悬赏积分那种印在棕色进度条上的字，实测 (233,222,198)）
    "pale": lambda R, G, B: R > 225 and G > 210 and B > 185 and (R - B) < 55,
    # 悬赏积分「1068/26000」这行：字芯是 (233,222,198)，但抗锯齿边缘掉到 ~(180,175,160)，
    # 严格 white(195)/pale(225) 会把笔画切断，再和上下两条全宽米色装饰条连成一大块
    # （2026-11-05 实测读成 [0] 的假值）。阈值 170 能把 10 个数字全部切出（得分 0.63~0.86）。
    "pale_soft": lambda R, G, B: R > 170 and G > 170 and B > 170,
    # 宽松绿：公会商人的「议价 1194」是绿色，细笔画抗锯齿会把严格绿掩码切断
    "green_loose": lambda R, G, B: G > 100 and (G - R) > 30 and (G - B) >= 0,
    # 深色字（神器升级页「等级 40」是深灰字印在米色面板上）
    "dark": lambda R, G, B: R < 150 and G < 150 and B < 150,
    # 红字要求行（荣耀之书「所有职业技能需达到39级」），比按钮红更暗更虚，
    # 只取“红得明显”的像素，避免米色底被算进来。
    "red_text": lambda R, G, B: R > 150 and (R - G) > 55 and (R - B) > 45 and G < 140,
    # 主城顶栏资源数字（钻石 154）：暗黄色 (~190,182,141) 印在深蓝底 (~68,83,98) 上。
    "dim_yellow": lambda R, G, B: R > 150 and G > 140 and B < 178 and (R - B) > 28,
    # 公会商人木牌上的折扣数字：亮黄色 (255,239,165) 印在米色纸 (233,217,185) 上。
    # 靠亮度拉开差距，避免把纸底整块当成字形。
    "bright_yellow": lambda R, G, B: R > 245 and G > 228 and B < 205,
}


def _mask(im: Image.Image, box, mask_name: str):
    x0, y0, x1, y1 = box
    x1 = min(x1, im.width)
    y1 = min(y1, im.height)
    w, h = x1 - x0, y1 - y0
    fn = MASKS[mask_name]
    return [[1 if fn(*im.getpixel((x0 + xx, y0 + yy))) else 0 for xx in range(w)]
            for yy in range(h)]


def _segments(M):
    h = len(M)
    w = len(M[0]) if h else 0
    cols = [any(M[y][x] for y in range(h)) for x in range(w)]
    out = []
    x = 0
    while x < w:
        if not cols[x]:
            x += 1
            continue
        s = x
        while x < w and cols[x]:
            x += 1
        e = x
        ys = [y for y in range(h) for xx in range(s, e) if M[y][xx]]
        if not ys or e - s < 3:
            continue
        if (max(ys) + 1 - min(ys)) < 6:
            continue
        out.append((s, min(ys), e, max(ys) + 1))
    return out


def _normalize(M, g):
    s, y0, e, y1 = g
    gw, gh = e - s, y1 - y0
    out = []
    for yy in range(GLYPH_H):
        for xx in range(GLYPH_W):
            sx0 = s + xx * gw / GLYPH_W
            sx1 = s + (xx + 1) * gw / GLYPH_W
            sy0 = y0 + yy * gh / GLYPH_H
            sy1 = y0 + (yy + 1) * gh / GLYPH_H
            tot = n = 0
            for py in range(int(sy0), max(int(sy0) + 1, int(sy1))):
                for px in range(int(sx0), max(int(sx0) + 1, int(sx1))):
                    if 0 <= py < len(M) and 0 <= px < len(M[0]):
                        tot += M[py][px]
                        n += 1
            out.append(tot / n if n else 0.0)
    return out


_T = {d: [int(c) / 9 for c in s] for d, s in TEMPLATES.items()}


def _iou(a, b):
    inter = sum(min(x, y) for x, y in zip(a, b))
    union = sum(max(x, y) for x, y in zip(a, b))
    return inter / union if union else 0.0


def read_digits(im: Image.Image, box, mask: str = "green", min_score: float = 0.55):
    """读一段数字。返回 (字符串, 最低单字得分)；不可靠时返回 (None, score)。"""
    M = _mask(im, box, mask)
    gs = _segments(M)
    if not gs:
        return None, 0.0
    text = []
    worst = 1.0
    for g in gs:
        v = _normalize(M, g)
        scores = sorted(((_iou(v, t), d) for d, t in _T.items()), reverse=True)
        best, digit = scores[0]
        worst = min(worst, best)
        if best < min_score:
            return None, best
        text.append(digit)
    return "".join(text), worst


# 英雄详情页「等级 700」的数字区域（720×1280，青色数字，左边「等级」是灰色不会进掩码）
# 2026-10-30：部分英雄页整体上移约 17px（数字在 y≈843~870），旧框 (95,848,265,892)
# 会切掉数字顶部导致识别失败（得分 0.45 且读不出）——改成覆盖两种布局的宽框。
LEVEL_BOX = (95, 828, 265, 879)


def read_level(im: Image.Image):
    """读英雄详情页的等级。返回 (int|None, 分数)。"""
    text, score = read_digits(im, LEVEL_BOX, "green")
    if text and 2 <= len(text) <= 4:
        return int(text), score
    return None, score


def read_number(im: Image.Image, box, mask: str = "white", digits=(1, 8)):
    """读指定区域里的纯数字（议价/积分/等级/次数）。返回 (int|None, 分数)。"""
    text, score = read_digits(im, box, mask)
    lo, hi = digits
    if text and lo <= len(text) <= hi:
        return int(text), score
    return None, score


def read_number_loose(im: Image.Image, box, mask: str = "red_text", accept: float = 0.6,
                      digits=(1, 4)):
    """从一段「汉字+数字」的混合文字里只挑出数字。

    荣耀之书的红字要求行「所有职业技能需达到39级」整行都是红的，汉字字形
    会和数字一样进掩码；这里只认得分 ≥ accept 的字形（实测数字 0.74，汉字 ≤0.43），
    相邻字形按 x 间距拼接。返回 [int, ...]。
    """
    M = _mask(im, box, mask)
    gs = _segments(M)
    glyphs = []
    for g in gs:
        v = _normalize(M, g)
        best, digit = max(((_iou(v, t), d) for d, t in _T.items()))
        if best >= accept:
            glyphs.append((g[0], g[2], digit))
    merged: list[str] = []
    cur = ""
    last_x1 = None
    for x0, x1, digit in glyphs:
        if last_x1 is not None and x0 - last_x1 < 10:
            cur += digit
        else:
            if cur:
                merged.append(cur)
            cur = digit
        last_x1 = x1
    if cur:
        merged.append(cur)
    lo, hi = digits
    return [int(s) for s in merged if lo <= len(s) <= hi]


def read_all_numbers(im: Image.Image, box, mask: str = "white", digits=(1, 8)):
    """把区域里的每一段数字分别读出来（用「/」分隔的多数字行）。

    read_digits 会把「5/20」的 5 和 20 用斜杠连起来（斜杠不在掩码里，会切成两段），
    所以这里返回 [int, ...]，调用方自己决定取第几个。
    """
    M = _mask(im, box, mask)
    gs = _segments(M)
    lo, hi = digits
    glyphs = []
    for g in gs:
        v = _normalize(M, g)
        scores = sorted(((_iou(v, t), d) for d, t in _T.items()), reverse=True)
        best, digit = scores[0]
        if best < 0.5:
            continue
        glyphs.append((g[0], g[2], digit))
    merged: list[str] = []
    cur = ""
    last_x1 = None
    for x0, x1, digit in glyphs:
        if last_x1 is not None and x0 - last_x1 < 8:
            cur += digit
        else:
            if cur:
                merged.append(cur)
            cur = digit
        last_x1 = x1
    if cur:
        merged.append(cur)
    return [int(s) for s in merged if lo <= len(s) <= hi]
