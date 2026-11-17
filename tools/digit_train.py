"""数字模板采集与匹配验证（临时脚本）。

思路：等级数字在英雄详情页是青色 (约 40,140,120)；铁匠铺价格是绿色 (约 70,150,70)；
进阶石进度是橙色。三者字形相同（同一套数字字体），只是粗细略有差别。
先把已知数字的截图切出字形做模板，再用模板去读同一批截图，检查识别率。
"""
from __future__ import annotations

import json
import sys

from PIL import Image

W, H = 14, 20


def mask_green(R, G, B):
    return G > 115 and G - R > 50 and G - B > 5


def mask_orange(R, G, B):
    return R > 190 and 90 < G < 190 and B < 110 and (R - B) > 110


def mask_red(R, G, B):
    return R > 150 and (R - G) > 70 and B < 120


MASKS = {"green": mask_green, "orange": mask_orange, "red": mask_red}


def glyphs(im, box, mask_name):
    mask = MASKS[mask_name]
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    M = [[1 if mask(*im.getpixel((x0 + xx, y0 + yy))) else 0 for xx in range(w)]
         for yy in range(h)]
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
        out.append((s, min(ys), e, max(ys) + 1))
    return M, out


def normalize(M, g):
    s, y0, e, y1 = g
    gw, gh = e - s, y1 - y0
    out = []
    for yy in range(H):
        for xx in range(W):
            sx0 = s + xx * gw / W
            sx1 = s + (xx + 1) * gw / W
            sy0 = y0 + yy * gh / H
            sy1 = y0 + (yy + 1) * gh / H
            tot = n = 0
            for py in range(int(sy0), max(int(sy0) + 1, int(sy1))):
                for px in range(int(sx0), max(int(sx0) + 1, int(sx1))):
                    if 0 <= py < len(M) and 0 <= px < len(M[0]):
                        tot += M[py][px]
                        n += 1
            out.append(tot / n if n else 0.0)
    return out


def iou(a, b):
    inter = sum(min(x, y) for x, y in zip(a, b))
    union = sum(max(x, y) for x, y in zip(a, b))
    return inter / union if union else 0.0


SOURCES = [
    # (image, box, mask, text) —— 建模板
    (r"C:\Users\123\AppData\Local\Temp\detail_clean2.png", (95, 852, 205, 890), "green", "700"),
    (r"C:\Users\123\AppData\Local\Temp\hero_detail.png", (95, 852, 205, 890), "green", "800"),
    (r"C:\Users\123\AppData\Local\Temp\shaman_detail.png", (95, 852, 205, 890), "green", "750"),
    (r"E:\Reverse\auto_script\tests\fixtures\forge_enhance_ready.png", (312, 1022, 410, 1060), "green", "17346"),
    (r"E:\Reverse\auto_script\tests\fixtures\forge_enhance_broke.png", (312, 1022, 410, 1060), "red", "69412"),
]

# 验证集（不参与建模板）：没见过的截图 + 没见过的数字
UNSEEN = [
    (r"C:\Users\123\AppData\Local\Temp\nj_detail.png", (95, 852, 205, 890), "green", "700"),
    (r"E:\Reverse\auto_script\tests\fixtures\forge_enhance_ready.png", (90, 680, 240, 712), "green", "17346"),
]


def build():
    tmpl = {}
    counts = {}
    for path, box, m, text in SOURCES:
        im = Image.open(path).convert("RGB")
        M, gs = glyphs(im, box, m)
        digits = [c for c in text if c.isdigit()]
        if len(gs) != len(digits):
            print(f"[WARN] {path} {text}: glyphs={len(gs)} digits={len(digits)}")
            continue
        for g, d in zip(gs, digits):
            v = normalize(M, g)
            tmpl.setdefault(d, []).append(v)
            counts[d] = counts.get(d, 0) + 1
    avg = {d: [sum(col) / len(col) for col in zip(*vs)] for d, vs in tmpl.items()}
    return avg, counts


def main():
    avg, counts = build()
    print("templates:", sorted(avg), counts)
    ok = bad = 0
    for tag, group in (("train", SOURCES), ("unseen", UNSEEN)):
        for path, box, m, text in group:
            im = Image.open(path).convert("RGB")
            M, gs = glyphs(im, box, m)
            digits = [c for c in text if c.isdigit()]
            if len(gs) != len(digits):
                print(f"[{tag}] {text}: glyph count {len(gs)} != {len(digits)}")
                bad += 1
                continue
            got = []
            for g in gs:
                v = normalize(M, g)
                scores = sorted(((iou(v, t), d) for d, t in avg.items()), reverse=True)
                got.append(scores[0][1])
            res = "".join(got)
            okk = res == "".join(digits)
            ok += okk
            bad += not okk
            print(f"[{tag}] {text:>10} -> {res:<10} {'OK' if okk else 'MISMATCH'}")
    print(f"ok={ok} bad={bad}")
    if "--save" in sys.argv:
        out = {d: [round(x, 2) for x in v] for d, v in avg.items()}
        with open("tools/digits.json", "w", encoding="utf-8") as f:
            json.dump(out, f)
        print("saved tools/digits.json")


if __name__ == "__main__":
    main()
