from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from core.adb import Adb, AdbError
from core.config import BASE_DIR, load_config, logs_dir, templates_dir
from core.device import AdbDevice, MockDevice
from core.engine import Runner, TaskError
from core.vision import Matcher, imwrite_unicode


def setup_logging(logdir: Path, verbose: bool) -> None:
    logdir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout)]
    handlers.append(logging.FileHandler(logdir / f"run_{time.strftime('%Y%m%d_%H%M%S')}.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def build_adb(cfg: dict, serial: str | None = None) -> Adb:
    device_cfg = cfg.get("device") or {}
    return Adb(device_cfg.get("adb") or None, serial or device_cfg.get("serial") or None, BASE_DIR)


def connect_targets(cfg: dict, extra: list[str] | None = None) -> list[str]:
    device_cfg = cfg.get("device") or {}
    targets = list(device_cfg.get("connect") or [])
    if extra:
        targets += extra
    return [str(t) for t in targets]


def build_matcher(cfg: dict) -> Matcher:
    vision_cfg = cfg.get("vision") or {}
    return Matcher(
        templates_dir(cfg),
        threshold=float(vision_cfg.get("threshold", 0.86)),
        scales=[float(s) for s in vision_cfg.get("scales") or []],
        grayscale=bool(vision_cfg.get("grayscale", False)),
    )


def load_mock_frames(path: str) -> list[np.ndarray]:
    folder = Path(path)
    if not folder.is_dir():
        raise SystemExit(f"--mock 需要目录，收到: {path}")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"))
    if not files:
        raise SystemExit(f"--mock 目录里没有图片: {folder}")
    frames = []
    for file in files:
        data = np.fromfile(str(file), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"无法读取: {file}")
        frames.append(img)
    return frames


def resolve_task(name: str) -> Path:
    path = Path(name)
    if path.is_file():
        return path
    candidates = [
        BASE_DIR / "tasks" / name,
        BASE_DIR / "tasks" / f"{name}.yaml",
        BASE_DIR / "tasks" / f"{name}.yml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(f"找不到任务: {name}（可运行 python main.py --list 查看）")


def cmd_list() -> None:
    task_dir = BASE_DIR / "tasks"
    files = sorted(task_dir.rglob("*.yaml")) + sorted(task_dir.rglob("*.yml"))
    if not files:
        print("tasks/ 下没有任务文件")
        return
    for file in files:
        if file.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            print(f"{file.relative_to(BASE_DIR)}  (解析失败: {exc})")
            continue
        rel = file.relative_to(task_dir).with_suffix("")
        print(f"{str(rel):28s}  {data.get('name', '')}  {data.get('description', '')}")


def cmd_check(cfg: dict, args) -> None:
    adb = build_adb(cfg, args.serial)
    print(f"adb: {adb.adb}")
    print(f"version: {adb.version()}")
    devices = adb.list_devices()
    print(f"devices: {devices or '（无）'}")
    serial = adb.resolve_serial(connect_targets(cfg, args.connect))
    print(f"使用设备: {serial}")
    png = adb.screencap()
    out = logs_dir(cfg) / "check.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    height, width = img.shape[:2]
    print(f"截图尺寸: {width}x{height}  -> {out}")
    print(f"wm size: {adb.wm_size()}")
    print(f"前台应用: {adb.foreground() or '（未获取到）'}")


def cmd_snap(cfg: dict, args) -> None:
    adb = build_adb(cfg, args.serial)
    adb.resolve_serial(connect_targets(cfg, args.connect))
    png = adb.screencap()
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    height, width = img.shape[:2]
    raw_dir = templates_dir(cfg) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    name = args.snap or time.strftime("%Y%m%d_%H%M%S")
    out = raw_dir / f"{name}_{width}x{height}.png"
    out.write_bytes(png)
    (out.with_suffix(".json")).write_text(
        yaml.safe_dump({"ref": [width, height]}, allow_unicode=True), encoding="utf-8"
    )
    print(f"截图已保存: {out}")
    print("下一步: python tools/crop_tool.py   （拖动框选后按 S 保存为模板）")


def cmd_run(cfg: dict, args) -> int:
    if args.mock:
        device = MockDevice(load_mock_frames(args.mock))
        logging.getLogger("auto").info("离线模式: %d 帧", len(device.frames))
    else:
        adb = build_adb(cfg, args.serial)
        adb.resolve_serial(connect_targets(cfg, args.connect))
        device = AdbDevice(adb)

    matcher = build_matcher(cfg)
    runner = Runner(
        device=device,
        matcher=matcher,
        config=cfg,
        templates_dir=templates_dir(cfg),
        logs_dir=logs_dir(cfg),
        dry_run=args.dry_run,
        max_minutes=args.max_minutes,
    )
    task = resolve_task(args.task)
    try:
        runner.run_task(task)
    except TaskError as exc:
        logging.getLogger("auto").error("任务失败: %s", exc)
        return 2
    except AdbError as exc:
        logging.getLogger("auto").error("设备错误: %s", exc)
        return 3
    except FileNotFoundError as exc:
        logging.getLogger("auto").error("%s", exc)
        logging.getLogger("auto").error("提示: 先运行 python main.py --snap 截图，再用 tools/crop_tool.py 裁剪模板")
        return 4
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="手游自动化脚本（ADB + OpenCV 模板匹配）")
    parser.add_argument("--config", default=None, help="配置文件路径，默认 config.yaml")
    parser.add_argument("--task", default=None, help="任务名或 tasks/ 下的 yaml 路径")
    parser.add_argument("--list", action="store_true", help="列出所有任务")
    parser.add_argument("--check", action="store_true", help="检查 adb/设备/分辨率/前台应用")
    parser.add_argument("--snap", nargs="?", const="", default=None, help="截取当前画面到 templates/raw")
    parser.add_argument("--mock", default=None, help="离线测试：用目录里的图片当作画面")
    parser.add_argument("--dry-run", action="store_true", help="只识别不点击")
    parser.add_argument("--serial", default=None, help="设备序列号")
    parser.add_argument("--connect", action="append", default=None, help="尝试 adb connect 的地址，可多次传入")
    parser.add_argument("--max-minutes", type=float, default=None, help="整个任务/循环的时间上限（分钟）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(logs_dir(cfg), args.verbose)

    if args.list:
        cmd_list()
        return 0

    try:
        if args.check:
            cmd_check(cfg, args)
            return 0
        if args.snap is not None:
            cmd_snap(cfg, args)
            return 0
        if not args.task:
            parser.print_help()
            return 1
        return cmd_run(cfg, args)
    except AdbError as exc:
        logging.getLogger("auto").error("%s", exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
