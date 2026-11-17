# -*- coding: utf-8 -*-
"""UI 验证工具（只读观测 + 可选点一下），不参与任务逻辑。

用法（在 E:\\Reverse\\auto_script 下执行，解释器用带 PIL/opencv 的那个）：

  # 抓图 + 状态 + 模板得分 + 金色按钮带
  python tools/verify_ui.py --issue 01 --name rank_before --state --tpl 标题_军衔

  # 指定区域测金色按钮带并打印坐标
  python tools/verify_ui.py --issue 01 --name rank_before --bands 28,80,700,1260

  # 点一下（长按 220ms），再抓图对比
  python tools/verify_ui.py --issue 01 --name rank_after --press 360,908 --prev 01/rank_before.png

  # 只算两张图的差异比例
  python tools/verify_ui.py --diff 01/rank_before.png 01/rank_after.png

产出：artifacts/verify/<问题编号>/<name>.png 与 report.txt（追加）。
失败会打印原因并以非 0 退出，不影响 GUI / 任务代码。
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops  # noqa: E402

from mtbot import config as C  # noqa: E402
from mtbot import ocr, vision  # noqa: E402
from mtbot.template import VI  # noqa: E402

ART = ROOT / "artifacts" / "verify"


def _cfg():
    """adb 解析顺序：config.json 的 device.adb → 本机已知安装路径 → PATH。

    注意：OAS 也在用同一个 adb server（5037），本工具绝不 kill-server。
    """
    cfg = C.load()
    cands = [cfg.device.adb,
             r"D:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
             r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe",
             "adb"]
    for c in cands:
        if not c:
            continue
        if c == "adb" or Path(c).exists():
            return c, cfg.device.serial
    raise RuntimeError("找不到 adb；请把可执行文件路径写进 config.json 的 device.adb")


def _adb(args: list[str], adb: str, serial: str, timeout: int = 60) -> bytes:
    cmd = [adb, "-s", serial] + args
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"adb 失败：{' '.join(cmd)}\n{p.stderr.decode('utf-8', 'replace')}")
    return p.stdout


def connect(adb: str, serial: str) -> None:
    p = subprocess.run([adb, "connect", serial], capture_output=True, timeout=30)
    out = (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    print(f"[adb] connect {serial}: {out}")
    dev = subprocess.run([adb, "devices"], capture_output=True, timeout=30).stdout
    if serial.encode() not in dev:
        raise RuntimeError(f"设备不在线：{serial}\n{dev.decode('utf-8', 'replace')}")


def shot(adb: str, serial: str) -> Image.Image:
    raw = _adb(["exec-out", "screencap", "-p"], adb, serial, timeout=90)
    im = Image.open(io.BytesIO(raw))
    return im.convert("RGB")


def press(adb: str, serial: str, x: int, y: int, ms: int = 220) -> None:
    _adb(["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(ms)], adb, serial, timeout=30)


def diff_ratio(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        b = b.resize(a.size)
    d = ImageChops.difference(a, b).convert("L")
    hist = d.histogram()
    changed = sum(hist[24:])
    total = a.size[0] * a.size[1]
    return changed / total if total else 0.0


def report(issue_dir: Path, lines: list[str]) -> None:
    issue_dir.mkdir(parents=True, exist_ok=True)
    with (issue_dir / "report.txt").open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", default="misc")
    ap.add_argument("--name", default="shot")
    ap.add_argument("--adb", default="")
    ap.add_argument("--serial", default="")
    ap.add_argument("--state", action="store_true", help="打印当前画面状态")
    ap.add_argument("--tpl", action="append", default=[], help="模板名，可重复")
    ap.add_argument("--bands", default="", help="金色按钮带扫描区域 x0,y0,x1,y1")
    ap.add_argument("--numbers", default="", help="数字 OCR 区域 x0,y0,x1,y1")
    ap.add_argument("--closex", action="store_true", help="列出右上角红色关闭钮候选（含命中偏移）")
    ap.add_argument("--press", default="", help="x,y 长按 220ms")
    ap.add_argument("--prev", default="", help="上一张图（相对 artifacts/verify）用于对比")
    ap.add_argument("--diff", nargs=2, default=None, help="直接比较两张图")
    ap.add_argument("--image", default="", help="离线分析已有截图（相对 artifacts/verify 或绝对路径），不连设备")
    ap.add_argument("--wait", type=float, default=1.2)
    a = ap.parse_args()

    adb, serial = _cfg()
    adb = a.adb or adb
    serial = a.serial or serial
    issue_dir = ART / a.issue

    if a.diff:
        p1, p2 = (ART / a.diff[0], ART / a.diff[1])
        im1, im2 = Image.open(p1).convert("RGB"), Image.open(p2).convert("RGB")
        r = diff_ratio(im1, im2)
        print(f"[diff] {p1.name} vs {p2.name}: {r:.2%} 像素变化")
        return 0

    if a.image:
        p = Path(a.image)
        if not p.is_absolute():
            p = ART / p
        im = Image.open(p).convert("RGB")
        issue_dir.mkdir(parents=True, exist_ok=True)
        out = p
        print(f"[image] {out}  size={im.size}")
    else:
        connect(adb, serial)
        im = shot(adb, serial)
        issue_dir.mkdir(parents=True, exist_ok=True)
        out = issue_dir / f"{a.name}.png"
        im.save(out)
        print(f"[shot] {out}  size={im.size}")

    lines = [f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {a.name}.png size={im.size}"]
    if a.state:
        st = vision.classify(im)
        print(f"[state] {st}")
        lines.append(f"state={st}")
    for name in a.tpl:
        try:
            best = VI.best_score(im, name)
            hit = VI.find(im, name)
        except Exception as e:  # noqa: BLE001 - 模板缺失不该让工具崩
            print(f"[tpl] {name}: 不可用（{e}）")
            lines.append(f"tpl {name}: 不可用")
            continue
        # Match.center 是属性（tuple），不是方法；旧代码写成 center() 会在命中时崩
        print(f"[tpl] {name}: best={best:.3f} hit={'yes ' + str(hit.center) if hit else 'no'}")
        lines.append(f"tpl {name}: best={best:.3f} center={hit.center if hit else None}")
    if a.bands:
        box = tuple(int(v) for v in a.bands.split(","))
        gold = vision.gold_button_bands(im, box)
        orange = vision.orange_button_bands(im, box)
        print(f"[bands] gold={gold}")
        print(f"[bands] orange={orange}")
        lines.append(f"gold={gold} orange={orange}")
    if a.numbers:
        box = tuple(int(v) for v in a.numbers.split(","))
        nums = ocr.read_all_numbers(im, box)
        print(f"[ocr] {nums}")
        lines.append(f"numbers={nums}")
    if a.closex:
        from mtbot.ui import UI
        cands = UI._find_close_buttons(im)
        hits = [(round(cx - 20), round(cy + 10)) for cx, cy in cands]
        print(f"[closex] centers={[(round(cx), round(cy)) for cx, cy in cands]}")
        print(f"[closex] taps={hits}")
        lines.append(f"closex centers={cands} taps={hits}")

    if a.press:
        x, y = (int(v) for v in a.press.split(","))
        print(f"[press] ({x},{y}) 220ms")
        lines.append(f"press=({x},{y}) ms=220")
        press(adb, serial, x, y)
        time.sleep(a.wait)
        im2 = shot(adb, serial)
        (issue_dir / f"{a.name}_after.png").parent.mkdir(parents=True, exist_ok=True)
        im2.save(issue_dir / f"{a.name}_after.png")
        print(f"[shot] {issue_dir / (a.name + '_after.png')}")
        r = diff_ratio(im, im2)
        print(f"[diff] ≈ {r:.2%} 像素变化")
        lines.append(f"diff={r:.3f}")
        st2 = vision.classify(im2)
        print(f"[state] after={st2}")
        lines.append(f"state_after={st2}")
    report(issue_dir, lines)
    print(f"[report] {issue_dir / 'report.txt'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[ERR] {e}")
        raise SystemExit(2)
