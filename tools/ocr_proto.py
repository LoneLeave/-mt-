"""原型：从截图里切数字字形，看看能不能做模板匹配（临时脚本，不参与运行）。

用法：
  python -I tools/ocr_proto.py <img> <x0> <y0> <x1> <y1>
"""
from __future__ import annotations

import sys

from PIL import Image

TMP = r"C:\Users\123\AppData\Local\Temp"


def digit_mask(im: Image.Image, x0, y0, x1, y1, white_thresh=195, blue=True):
    w, h = x1 - x0, y1 - y0
    m = [[0] * w for _ in range(h)]
    for yy in range(h):
        for xx in range(w):
            R, G, B = im.getpixel((x0 + xx, y0 + yy))
            white = min(R, G, B) > white_thresh and (max(R, G, B) - min(R, G, B)) < 50
            bl = blue and (B - R) > 50 and B > 150
            if white or bl:
                m[yy][xx] = 1
    return m


def glyphs(m):
    h = len(m)
    w = len(m[0])
    cols = [any(m[y][x] for y in range(h)) for x in range(w)]
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
        ys = [y for y in range(h) for xx in range(s, e) if m[y][xx]]
        if not ys:
            continue
        y0, y1 = min(ys), max(ys) + 1
        out.append((s, y0, e, y1))
    return out


def norm(m, box, W=12, H=18):
    s, y0, e, y1 = box
    gw, gh = e - s, y1 - y0
    out = [0.0] * (W * H)
    for yy in range(H):
        for xx in range(W):
            # 采样：把目标方块按比例映射回原图，取块内平均
            sx0 = s + xx * gw / W
            sx1 = s + (xx + 1) * gw / W
            sy0 = y0 + yy * gh / H
            sy1 = y0 + (yy + 1) * gh / H
            tot = n = 0
            for py in range(int(sy0), max(int(sy0) + 1, int(sy1))):
                for px in range(int(sx0), max(int(sx0) + 1, int(sx1))):
                    if py < len(m) and px < len(m[0]):
                        tot += m[py][px]
                        n += 1
            out[yy * W + xx] = tot / n if n else 0.0
    return out


def show(vec, W=12, H=18):
    for y in range(H):
        print("".join("#" if vec[y * W + x] > 0.5 else "." for x in range(W)))
    print()


if __name__ == "__main__":
    img, x0, y0, x1, y1 = sys.argv[1], *map(int, sys.argv[2:6])
    im = Image.open(img).convert("RGB")
    m = digit_mask(im, x0, y0, x1, y1)
    gs = glyphs(m)
    print(f"glyphs: {len(gs)}", gs)
    for g in gs:
        show(norm(m, g))
