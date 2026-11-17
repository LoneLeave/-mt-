"""模板匹配（cv2）：图标/按钮/层名这类不好用像素阈值判断的东西。

移植自 E:/DailyIdea 的同名实现（用户之前写好的地精宝藏脚本），模板素材在
E:/Reverse/auto_script/templates/，与 720×1280 真机截图 1:1。
支持 RGBA 美术素材（alpha 当 mask）和同名 .json 的缩放配置。

"""
import json
from pathlib import Path

import cv2
import numpy as np


class Match:
    __slots__ = ("name", "x", "y", "w", "h", "score", "scale")

    def __init__(self, name, x, y, w, h, score, scale=1.0):
        self.name = name
        self.x, self.y, self.w, self.h = x, y, w, h
        self.score = score
        self.scale = scale

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    def __repr__(self):
        return "<%s (%d,%d %dx%d) %.3f>" % (
            self.name, self.x, self.y, self.w, self.h, self.score)


class Vision:
    def __init__(self, assets_dir, threshold=0.85):
        self.assets = Path(assets_dir)
        self.threshold = threshold
        self._cache = {}

    def path(self, name):
        p = Path(name)
        return p if p.is_absolute() else self.assets / name

    def template(self, name):
        """返回 (bgr, mask, sidecar_scales)。

        mask 只在模板带透明通道时存在；sidecar_scales 来自同名 .json。
        """
        key = str(name)
        p = self.path(key)
        if not p.exists():
            raise FileNotFoundError("找不到模板：%s" % p)
        sidecar = p.with_name(p.name + ".json")
        mtime = p.stat().st_mtime
        if sidecar.exists():
            mtime = max(mtime, sidecar.stat().st_mtime)
        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]

        raw = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise ValueError("模板读不出来：%s" % p)

        mask = None
        if raw.ndim == 3 and raw.shape[2] == 4:
            alpha = raw[:, :, 3]
            ys, xs = np.nonzero(alpha)
            if xs.size:
                x0, y0 = int(xs.min()), int(ys.min())
                x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
                raw = raw[y0:y1, x0:x1]
                alpha = alpha[y0:y1, x0:x1]
            bgr = np.ascontiguousarray(raw[:, :, :3])
            alpha = np.ascontiguousarray(alpha)
            if int(alpha.min()) < 250:
                mask = alpha
        elif raw.ndim == 3:
            bgr = np.ascontiguousarray(raw)
        else:
            bgr = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)

        scales = None
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                if meta.get("scales"):
                    scales = tuple(float(s) for s in meta["scales"])
                elif meta.get("scale"):
                    scales = (float(meta["scale"]),)
            except Exception:
                scales = None

        data = (bgr, mask, scales)
        self._cache[key] = (mtime, data)
        return data

    @staticmethod
    def _to_bgr(pil_image):
        arr = np.array(pil_image)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _crop(img, roi):
        """roi = (x0, y0, x1, y1)，None 表示全图。"""
        if not roi:
            return img, 0, 0
        x0, y0, x1, y1 = [int(v) for v in roi]
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(img.shape[1], x1)
        y1 = min(img.shape[0], y1)
        return img[y0:y1, x0:x1], x0, y0

    def _scales(self, sidecar_scales, scales):
        if scales:
            return tuple(float(s) for s in scales)
        if sidecar_scales:
            return tuple(sidecar_scales)
        return (1.0,)

    @staticmethod
    def _resize(tpl, mask, scale):
        if scale == 1.0:
            return tpl, mask
        h, w = tpl.shape[:2]
        tw, th = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        tpl2 = cv2.resize(tpl, (tw, th), interpolation=interp)
        mask2 = None
        if mask is not None:
            mask2 = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_AREA)
            _, mask2 = cv2.threshold(mask2, 32, 255, cv2.THRESH_BINARY)
            if cv2.countNonZero(mask2) < tw * th * 0.05:
                mask2 = None
        return tpl2, mask2

    @staticmethod
    def _match(search, tpl, mask):
        if mask is not None:
            res = cv2.matchTemplate(search, tpl, cv2.TM_CCORR_NORMED, mask=mask)
        else:
            res = cv2.matchTemplate(search, tpl, cv2.TM_CCOEFF_NORMED)
        return np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)

    def find(self, screen, name, threshold=None, scales=None, roi=None):
        """返回最佳匹配（高于阈值），找不到返回 None。"""
        tpl0, mask0, sidecar_scales = self.template(name)
        th = self.threshold if threshold is None else threshold
        img = self._to_bgr(screen) if not isinstance(screen, np.ndarray) else screen
        search, ox, oy = self._crop(img, roi)
        best = None
        for s in self._scales(sidecar_scales, scales):
            tpl, mask = self._resize(tpl0, mask0, s)
            h, w = tpl.shape[:2]
            if search.shape[0] < h or search.shape[1] < w:
                continue
            res = self._match(search, tpl, mask)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if best is None or max_val > best[0]:
                best = (float(max_val), max_loc, w, h, s)
        if not best or best[0] < th:
            return None
        max_val, loc, w, h, s = best
        return Match(str(name), loc[0] + ox, loc[1] + oy, w, h, max_val, s)

    def find_all(self, screen, name, threshold=None, max_results=10, roi=None, scales=None):
        """找所有匹配（去重）。带 alpha 的模板同样支持。"""
        tpl0, mask0, sidecar_scales = self.template(name)
        th = self.threshold if threshold is None else threshold
        img = self._to_bgr(screen) if not isinstance(screen, np.ndarray) else screen
        search, ox, oy = self._crop(img, roi)
        best = None
        for s in self._scales(sidecar_scales, scales):
            tpl, mask = self._resize(tpl0, mask0, s)
            h, w = tpl.shape[:2]
            if search.shape[0] < h or search.shape[1] < w:
                continue
            res = self._match(search, tpl, mask)
            if best is None or float(res.max()) > best[0]:
                best = (float(res.max()), res, w, h, s)
        if best is None:
            return []
        _, res, w, h, s = best
        ys, xs = np.where(res >= th)
        picked = []
        for x, y in sorted(zip(xs, ys), key=lambda p: -res[p[1], p[0]]):
            if all(abs(x - px) > w // 2 or abs(y - py) > h // 2 for px, py, _ in picked):
                picked.append((int(x), int(y), float(res[y, x])))
            if len(picked) >= max_results:
                break
        return [Match(str(name), x + ox, y + oy, w, h, sc, s) for x, y, sc in picked]

    def best_score(self, screen, name, roi=None, scales=None):
        tpl0, mask0, sidecar_scales = self.template(name)
        img = self._to_bgr(screen) if not isinstance(screen, np.ndarray) else screen
        search, _, _ = self._crop(img, roi)
        best = 0.0
        for s in self._scales(sidecar_scales, scales):
            tpl, mask = self._resize(tpl0, mask0, s)
            if search.shape[0] < tpl.shape[0] or search.shape[1] < tpl.shape[1]:
                continue
            res = self._match(search, tpl, mask)
            best = max(best, float(res.max()))
        return best


# 项目内模板目录（720×1280 真机截图 1:1；模板素材来自 E:/DailyIdea 的 assets）
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parent.parent
VI = Vision(ROOT / "templates", threshold=0.85)
