from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


def imread_unicode(path: str | Path):
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        raise ValueError(f"文件为空: {path}")
    return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)


def imwrite_unicode(path: str | Path, image) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        raise ValueError(f"图片编码失败: {path}")
    buf.tofile(str(path))


@dataclass
class Template:
    path: Path
    bgr: np.ndarray
    mask: np.ndarray | None
    ref_size: tuple[int, int] | None
    mtime: float


@dataclass
class Match:
    name: str
    score: float
    cx: float
    cy: float
    x: int
    y: int
    w: int
    h: int
    scale: float

    @property
    def center(self) -> tuple[int, int]:
        return int(round(self.cx)), int(round(self.cy))


class Matcher:
    def __init__(
        self,
        templates_dir: str | Path,
        threshold: float = 0.86,
        scales: list[float] | None = None,
        grayscale: bool = False,
    ):
        self.templates_dir = Path(templates_dir)
        self.threshold = float(threshold)
        self.scales = [float(s) for s in (scales or [0.96, 0.98, 1.0, 1.02, 1.04])]
        if 1.0 not in self.scales:
            self.scales.append(1.0)
        self.grayscale = bool(grayscale)
        self._cache: dict[Path, Template] = {}

    # ---------- 模板加载 ----------
    def resolve(self, name: str | Path) -> Path:
        path = Path(name)
        if not path.is_absolute():
            path = self.templates_dir / path
        if not path.suffix:
            path = path.with_suffix(".png")
        return path

    def _load(self, path: Path) -> Template:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"模板不存在: {path}")
        mtime = path.stat().st_mtime
        cached = self._cache.get(path)
        if cached and cached.mtime == mtime:
            return cached

        img = imread_unicode(path)
        if img is None:
            raise ValueError(f"无法读取模板: {path}")

        if img.ndim == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3]
            ys, xs = np.nonzero(alpha)
            if xs.size == 0:
                raise ValueError(f"模板全透明: {path}")
            x0, y0 = int(xs.min()), int(ys.min())
            x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
            img = img[y0:y1, x0:x1]
            bgr = np.ascontiguousarray(img[:, :, :3])
            alpha = np.ascontiguousarray(img[:, :, 3])
            mask = None if int(alpha.min()) == 255 else alpha
        elif img.ndim == 3 and img.shape[2] == 3:
            bgr, mask = np.ascontiguousarray(img), None
        else:
            bgr, mask = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), None

        ref_size = None
        sidecar = path.with_suffix(".json")
        if sidecar.is_file():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                ref = meta.get("ref")
                if ref and len(ref) == 2:
                    ref_size = (int(ref[0]), int(ref[1]))
            except Exception:
                ref_size = None

        tpl = Template(path=path, bgr=bgr, mask=mask, ref_size=ref_size, mtime=mtime)
        self._cache[path] = tpl
        return tpl

    # ---------- 匹配 ----------
    def find(
        self,
        screen: np.ndarray,
        name: str | Path,
        threshold: float | None = None,
        region: list | tuple | None = None,
    ) -> Match | None:
        tpl = self._load(self.resolve(name))
        thr = self.threshold if threshold is None else float(threshold)

        h, w = screen.shape[:2]
        ox, oy = 0, 0
        roi = screen
        if region:
            ox, oy, rw, rh = self._parse_region(region, w, h)
            if rw <= 0 or rh <= 0:
                return None
            roi = screen[oy:oy + rh, ox:ox + rw]
        if roi.size == 0:
            return None

        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if self.grayscale else roi
        tpl_bgr = cv2.cvtColor(tpl.bgr, cv2.COLOR_BGR2GRAY) if self.grayscale else tpl.bgr

        best: Match | None = None
        for scale in self._scales_for(tpl, w):
            tw = max(1, int(round(tpl.bgr.shape[1] * scale)))
            th = max(1, int(round(tpl.bgr.shape[0] * scale)))
            if tw < 6 or th < 6 or tw > gray_roi.shape[1] or th > gray_roi.shape[0]:
                continue
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            tpl_img = cv2.resize(tpl_bgr, (tw, th), interpolation=interp)
            mask_img = None
            if tpl.mask is not None:
                mask_img = cv2.resize(tpl.mask, (tw, th), interpolation=cv2.INTER_AREA)
                _, mask_img = cv2.threshold(mask_img, 32, 255, cv2.THRESH_BINARY)
                if cv2.countNonZero(mask_img) < tw * th * 0.05:
                    mask_img = None

            if mask_img is not None:
                res = cv2.matchTemplate(gray_roi, tpl_img, cv2.TM_CCORR_NORMED, mask=mask_img)
            else:
                res = cv2.matchTemplate(gray_roi, tpl_img, cv2.TM_CCOEFF_NORMED)
            res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            score = min(1.0, float(max_val))
            if best is None or score > best.score:
                best = Match(
                    name=str(name),
                    score=score,
                    cx=ox + max_loc[0] + tw / 2.0,
                    cy=oy + max_loc[1] + th / 2.0,
                    x=ox + int(max_loc[0]),
                    y=oy + int(max_loc[1]),
                    w=tw,
                    h=th,
                    scale=scale,
                )
        if best is not None and best.score >= thr:
            return best
        return None

    def find_any(
        self,
        screen: np.ndarray,
        names: list[str | Path],
        threshold: float | None = None,
        region: list | tuple | None = None,
    ) -> list[Match]:
        results = []
        for name in names:
            match = self.find(screen, name, threshold=threshold, region=region)
            if match is not None:
                results.append(match)
        results.sort(key=lambda m: m.score, reverse=True)
        return results

    # ---------- 辅助 ----------
    def _scales_for(self, tpl: Template, screen_w: int) -> list[float]:
        if tpl.ref_size and tpl.ref_size[0] > 0:
            base = screen_w / float(tpl.ref_size[0])
            values = [base * s for s in self.scales]
        else:
            values = list(self.scales)
        return sorted({round(v, 4) for v in values if 0.05 < v < 4.0})

    @staticmethod
    def _parse_region(region, width: int, height: int) -> tuple[int, int, int, int]:
        if len(region) != 4:
            raise ValueError(f"region 需要 4 个值 [x,y,w,h]，收到 {region}")
        x, y, w, h = region
        if all(isinstance(v, float) for v in (x, y, w, h)):
            return int(x * width), int(y * height), int(w * width), int(h * height)
        return int(x), int(y), int(w), int(h)
