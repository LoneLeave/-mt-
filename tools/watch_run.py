"""整轮视觉盯梢：启动 mt.py 全量跑，同时每 2~3 秒抓帧判页面并落证。

用法（任何目录都可以，路径写绝对）：

  python E:\\Reverse\\auto_script\\tools\\watch_run.py --config E:\\Reverse\\auto_script\\config.fullrun.json
  python E:\\Reverse\\auto_script\\tools\\watch_run.py --ts 20261103_160000 --no-run   # 只盯已有日志

产物：artifacts/run/<ts>/run.log + frames/ + issues/<n>/（shot.png、shot_prev*.png、context.log）

盯梢项：
  * unknown 连续 ≥6 帧（约 15s）
  * 同一页面（非主城）停留 ≥120s
  * 弹窗/压暗页停留 ≥30s
  * 钻石/金币数字变化（OCR）
  * 同坐标 30s 内点击 ≥3 次（解析日志 press）
  * 任务报 OK 但画面和任务开始时几乎一样

注意：绝不 adb kill-server（OAS 共用 5037）。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops  # noqa: E402

from mtbot import config as C  # noqa: E402
from mtbot import titles, vision  # noqa: E402

ADB_FALLBACKS = [
    r"D:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe",
    "adb",
]

POPUP_STATES = {"dialog", "main_city_dim", "reconnect", "reconnect_login", "quit_dialog"}
# 顶部资源栏（720×1280 实测）：金币 877233 在 y57~74、钻石 154 在 y120~139。
# 这两处字体和通用数字模板不一致（OCR 得分低），改用「区域指纹变化」检测数字变动，
# 只负责发现「变了」，具体数值由人工看证据图。
RES_BOXES = {
    "gold": (398, 12, 492, 44),
    "diamond": (410, 48, 482, 84),
}


def resolve_adb(cfg) -> str:
    for c in [cfg.device.adb, *ADB_FALLBACKS]:
        if c and (c == "adb" or Path(c).exists()):
            return c
    raise RuntimeError("找不到 adb；请检查 config.json 的 device.adb")


def adb(adb_path: str, serial: str, args: list[str], timeout: int = 60) -> bytes:
    p = subprocess.run([adb_path, "-s", serial, *args], capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[:200])
    return p.stdout


def shot(adb_path: str, serial: str) -> Image.Image:
    raw = adb(adb_path, serial, ["exec-out", "screencap", "-p"], timeout=90)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def diff_ratio(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        b = b.resize(a.size)
    d = ImageChops.difference(a, b).convert("L")
    h = d.histogram()
    return sum(h[24:]) / (a.size[0] * a.size[1])


def res_sig(im: Image.Image) -> dict:
    """资源数字区域指纹：缩小到 40×10 灰度，只用于判断「有没有变」。"""
    return {k: list(im.crop(b).convert("L").resize((40, 10)).getdata())
            for k, b in RES_BOXES.items()}


def sig_changed(a, b) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return sum(1 for x, y in zip(a, b) if abs(x - y) > 30) > 0.15 * len(a)


class Watch:
    def __init__(self, run_dir: Path, adb_path: str, serial: str, interval: float,
                 log_path: Path, task_timeout: float):
        self.run_dir = run_dir
        self.adb_path = adb_path
        self.serial = serial
        self.interval = interval
        self.log_path = log_path
        self.task_timeout = task_timeout
        self.log_pos = 0
        self.lines: deque[tuple[float, str]] = deque(maxlen=400)
        self.frames: deque[tuple[float, Image.Image, str]] = deque(maxlen=3)
        self.task = "-"
        self.task_start = time.time()
        self.task_start_im: Image.Image | None = None
        self.state = "unknown"
        self.state_since = time.time()
        self.unknown_run = 0
        self.clicks: deque[tuple[float, int, int]] = deque(maxlen=50)
        self.res: dict = {}
        self.issue_n = 0
        self.last_issue: dict[str, float] = {}
        self.issues: list[dict] = []

    # ---------- 日志 ----------
    def _tail_log(self) -> list[str]:
        if not self.log_path.exists():
            return []
        with self.log_path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(self.log_pos)
            data = f.read()
            self.log_pos = f.tell()
        return data.splitlines()

    def _handle_log(self, lines: list[str]) -> None:
        now = time.time()
        for ln in lines:
            self.lines.append((now, ln))
            m = re.search(r"Current task: (\S+)", ln)
            if m:
                self._new_task(m.group(1), now)
            m = re.search(r"press \((\d+), (\d+)\)", ln)
            if m:
                self.clicks.append((now, int(m.group(1)), int(m.group(2))))
            if re.search(r"\bOK\s", ln) and self.task_start_im is not None:
                self._maybe_false_ok(now)

    def _new_task(self, name: str, now: float) -> None:
        self.task = name
        self.task_start = now
        try:
            self.task_start_im = self.frames[-1][1] if self.frames else shot(self.adb_path, self.serial)
        except Exception:  # noqa: BLE001
            self.task_start_im = None
        self.state_since = now
        self.unknown_run = 0
        self.clicks.clear()

    # ---------- 问题 ----------
    def _issue(self, kind: str, detail: str, im: Image.Image) -> None:
        now = time.time()
        if now - self.last_issue.get(kind, 0) < 60:
            return
        self.last_issue[kind] = now
        self.issue_n += 1
        d = self.run_dir / "issues" / f"{self.issue_n:03d}_{kind}"
        d.mkdir(parents=True, exist_ok=True)
        im.save(d / "shot.png")
        for i, (_, old, _) in enumerate(list(self.frames)[-3:], 1):
            old.save(d / f"shot_prev{i}.png")
        for k, box in RES_BOXES.items():
            im.crop(box).save(d / f"res_{k}.png")
        ctx = [
            f"time={time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"task={self.task} kind={kind} state={self.state}",
            f"detail={detail}",
        ]
        window = [ln for t, ln in self.lines if now - 15 <= t <= now]
        ctx += ["", "--- log last 15s ---", *window]
        (d / "context.log").write_text("\n".join(ctx), encoding="utf-8")
        self.issues.append({"kind": kind, "task": self.task, "detail": detail,
                            "dir": str(d)})
        print(f"[ISSUE {self.issue_n:03d}] {self.task} {kind}: {detail} -> {d}", flush=True)

    def _maybe_false_ok(self, now: float) -> None:
        if not self.frames or self.task_start_im is None:
            return
        im = self.frames[-1][1]
        if diff_ratio(self.task_start_im, im) < 0.01:
            self._issue("false_ok", "任务日志报 OK，但画面与任务开始时几乎相同", im)

    # ---------- 主循环 ----------
    def tick(self) -> None:
        self._handle_log(self._tail_log())
        try:
            im = shot(self.adb_path, self.serial)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 抓图失败：{e}", flush=True)
            return
        st = vision.classify(im).value
        if st == "unknown" and titles.on_page(im, "merchant"):
            st = "merchant"          # 商人页目前没进 classify，用标题模板补判，避免误报 unknown
        now = time.time()
        if st != self.state:
            self.state, self.state_since = st, now
        self.unknown_run = self.unknown_run + 1 if st == "unknown" else 0
        self.frames.append((now, im, st))

        # 资源栏只在主城顶部存在；进别的页面时这块区域本来就是别的 UI，不能算「数字变化」
        if st == "main_city":
            sig = res_sig(im)
            for k, v in sig.items():
                if sig_changed(self.res.get(k), v):
                    self._issue(f"res_{k}", f"{k} 数字区域发生变化（看证据裁图）", im)
                self.res[k] = v
        else:
            self.res = {}

        held = now - self.state_since
        if self.unknown_run >= 6:
            self._issue("unknown", f"连续 {self.unknown_run} 帧认不出页面", im)
        if st in POPUP_STATES and held >= 30:
            self._issue("popup_stuck", f"{st} 已停留 {held:.0f}s（疑似弹窗没关）", im)
        if st not in POPUP_STATES and st != "main_city" and held >= 120:
            self._issue("stuck_page", f"{st} 已停留 {held:.0f}s（任务 {self.task}）", im)
        if self.task != "-" and now - self.task_start > self.task_timeout:
            self._issue("task_overrun",
                        f"任务 {self.task} 已跑 {now - self.task_start:.0f}s 仍在进行", im)

        recent = [(t, x, y) for t, x, y in self.clicks if now - t <= 30]
        if recent:
            for (x, y) in {(x, y) for _, x, y in recent}:
                if sum(1 for _, xx, yy in recent if (xx, yy) == (x, y)) >= 4:
                    self._issue("repeat_click", f"同坐标 ({x},{y}) 30s 内点了 4+ 次", im)
                    break

    def summary(self) -> None:
        data = {"task": self.task, "issues": self.issues,
                "frames": len(self.frames), "end_state": self.state}
        (self.run_dir / "watch.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.fullrun.json"))
    ap.add_argument("--ts", default="")
    ap.add_argument("--interval", type=float, default=2.5)
    ap.add_argument("--task-timeout", type=float, default=240)
    ap.add_argument("--no-run", action="store_true", help="只盯已有 run.log，不启动 mt.py")
    a = ap.parse_args()

    cfg = C.load(a.config)
    adb_path = resolve_adb(cfg)
    subprocess.run([adb_path, "connect", cfg.device.serial], capture_output=True, timeout=30)
    ts = a.ts or time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "artifacts" / "run" / ts
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"

    proc = None
    if not a.no_run:
        cmd = [sys.executable, "-I", str(ROOT / "mt.py"), "--config", a.config]
        print(f"[run] {' '.join(cmd)}", flush=True)
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=open(log_path, "w", encoding="utf-8"),
                                stderr=subprocess.STDOUT)

    w = Watch(run_dir, adb_path, cfg.device.serial, a.interval, log_path, a.task_timeout)
    print(f"[watch] {run_dir}", flush=True)
    n = 0
    try:
        while True:
            if proc is not None and proc.poll() is not None:
                w._handle_log(w._tail_log())
                break
            w.tick()
            n += 1
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("[watch] 手动停止", flush=True)
    finally:
        w.summary()
        if proc is not None and proc.poll() is None:
            proc.terminate()
        print(f"[watch] 结束：{len(w.issues)} 个问题，{n} 帧", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
