"""通用中文识读（RapidOCR）。

项目自带的 `ocr.py` 只有 14×20 的数字模板，只能读「N/M」这种纯数字；游戏里
大量关键信息是 18~22px 的中文（「挑战次数：0/20（每日登录+5）」「需通关第3关·
右后解锁」「限制条件：部落英雄≥4」），旧模板完全读不出来。

这里用 RapidOCR（onnxruntime，模型随包自带、不联网）做兜底：
  - 懒加载：第一次调用才初始化（1~2 秒），之后复用；
  - 没装 rapidocr 时 `available()` 返回 False，`read_text()` 返回 ""，调用方按旧逻辑回退；
  - 小字号自动放大到 ~44px 高再识别（游戏正文约 20px，直接喂会掉分）。
"""
from __future__ import annotations

import re
import threading

from . import log

_MIN_H = 40          # 识别前把 ROI 放大到这个高度
_MAX_SCALE = 4.0

_lock = threading.Lock()
_engine = None
_tried = False

Line = tuple  # (text, (cx, cy), (x0, y0, x1, y1), score)


def available() -> bool:
    """装了 rapidocr 就返回 True（不初始化引擎）。"""
    global _tried
    if _engine is not None:
        return True
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        if not _tried:
            _tried = True
            log.info("  textocr：未安装 rapidocr-onnxruntime，中文识读不可用")
        return False
    return True


def _get():
    global _engine, _tried
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        _tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as exc:  # pragma: no cover - 环境相关
            log.warn(f"  textocr：rapidocr 不可用（{exc}）")
            return None
        _engine = RapidOCR()
        return _engine


def _crop_scaled(im, box):
    from PIL import Image
    if box:
        x0, y0, x1, y1 = box
        x0 = max(0, min(x0, im.width - 1))
        y0 = max(0, min(y0, im.height - 1))
        x1 = max(x0 + 1, min(x1, im.width))
        y1 = max(y0 + 1, min(y1, im.height))
        im = im.crop((x0, y0, x1, y1))
        ox, oy = x0, y0
    else:
        ox, oy = 0, 0
    scale = min(_MAX_SCALE, max(1.0, _MIN_H / max(1, im.height)))
    if scale > 1.0:
        # Pillow 10 把 Image.LANCZOS 挪到 Image.Resampling.LANCZOS（9.x 只有前者），
        # 用 getattr 两头都兼容，避免每次跑测试都刷 DeprecationWarning。
        lanczos = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        im = im.resize((int(im.width * scale), int(im.height * scale)), lanczos)
    return im, ox, oy, scale


def read_lines(im, box=None, min_score: float = 0.45) -> list:
    """OCR 一段区域，返回 [(text, (cx,cy), (x0,y0,x1,y1), score)]，坐标回到原图。"""
    eng = _get()
    if eng is None or im is None:
        return []
    try:
        import numpy as np
        crop, ox, oy, scale = _crop_scaled(im, box)
        arr = np.array(crop.convert("RGB"))
        res, _ = eng(arr)
    except Exception as exc:  # pragma: no cover - 引擎/环境异常不影响主流程
        log.warn(f"  textocr：识别失败（{exc}）")
        return []
    out = []
    for item in res or []:
        try:
            pts, text, score = item
        except Exception:
            continue
        if not text or score < min_score:
            continue
        xs = [p[0] / scale + ox for p in pts]
        ys = [p[1] / scale + oy for p in pts]
        x0, x1 = int(min(xs)), int(max(xs))
        y0, y1 = int(min(ys)), int(max(ys))
        out.append((text.strip(), ((x0 + x1) // 2, (y0 + y1) // 2), (x0, y0, x1, y1), float(score)))
    return out


def read_text(im, box=None, sep: str = " ") -> str:
    """把一行行文字拼成一段，便于正则/关键字匹配。"""
    return sep.join(t for t, *_ in read_lines(im, box))


def find(im, keys, box=None, exact: bool = False) -> tuple[int, int] | None:
    """在一段区域里找包含任一关键字的行，返回该行中心坐标。"""
    if isinstance(keys, str):
        keys = (keys,)
    for text, center, _bb, _sc in read_lines(im, box):
        for k in keys:
            if (text == k) if exact else (k in text):
                return center
    return None


def find_line(im, keys, box=None) -> tuple | None:
    """同 `find`，但返回整行 (text, center, bbox, score)。"""
    if isinstance(keys, str):
        keys = (keys,)
    for row in read_lines(im, box):
        for k in keys:
            if k in row[0]:
                return row
    return None


_NUMS = re.compile(r"(\d+(?:\.\d+)?)\s*(万)?\s*/\s*(\d+)")


def read_remain(text: str, key: str = "剩余次数"):
    """从「今日剩余次数：0」这种文本里取整数次数；读不到返回 None。"""
    if not text:
        return None
    m = re.search(key + r"[^0-9]{0,6}(\d+)", text)
    return int(m.group(1)) if m else None


def read_fraction(text: str):
    """从「挑战次数：0/20」这类文本里取 (0, 20)；读不到返回 None。

    2026-11-08：圣物材料写成「4万/800」（4 万 = 40000），旧正则只认纯数字，
    于是「/」前面是「万」就整条匹配不上 → 材料进度恒 None，一键升级判据空转。
    这里把「万」当 ×10000，其它调用点（0/20、5/20、690/800）行为不变。
    """
    if not text:
        return None
    m = _NUMS.search(text.replace("／", "/"))
    if not m:
        return None
    head = float(m.group(1))
    if m.group(2):
        head *= 10000
    return int(head), int(m.group(3))


_WIN_POINT = re.compile(r"(\d{1,2})\s*点\s*[-~～至—]?\s*(\d{1,2})\s*点")
_WIN_CLOCK = re.compile(r"(\d{1,2}):\d{2}\s*[-~～至—]\s*(\d{1,2}):\d{2}")


def read_time_window(text: str, key: str = "开战时间"):
    """从「开战时间：10点-22点」里取 (10, 22)；读不到返回 None。

    2026-11-06 实测（地精宝藏面板顶部）：这行就是休赛期说明，窗口外点「占领」
    按钮照样有按下动画，但游戏只弹一个 toast「当前处于休赛期，无法占领」。
    必须用「N点-M点」这种成对约束，不能见数字就取前两个 —— OCR 常把
    「开战时间：10点-22点」切成「开战时间：1」+「10点-22点」两行，
    松散取法会读成 (1, 10)，在 11 点这种真开战时间被误判成休赛期。
    """
    if not text:
        return None
    idx = text.find(key)
    if idx >= 0:
        text = text[idx + len(key):]
    m = _WIN_POINT.search(text) or _WIN_CLOCK.search(text)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if not (0 <= a <= 24 and 0 <= b <= 24):
        return None
    return a, b