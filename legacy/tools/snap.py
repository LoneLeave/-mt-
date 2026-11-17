from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PIL import Image  # noqa: E402

from core.adb import Adb  # noqa: E402
from core.config import load_config, templates_dir  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="截取设备当前画面，保存到 templates/raw")
    parser.add_argument("name", nargs="?", default="", help="截图名称，如 main_home")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    device_cfg = cfg.get("device") or {}
    adb = Adb(device_cfg.get("adb") or None, args.serial or device_cfg.get("serial") or None, BASE_DIR)
    adb.resolve_serial(device_cfg.get("connect") or [])

    png = adb.screencap()
    width, height = Image.open(io.BytesIO(png)).size
    name = args.name or time.strftime("%Y%m%d_%H%M%S")
    out = templates_dir(cfg) / "raw" / f"{name}_{width}x{height}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    out.with_suffix(".json").write_text(json.dumps({"ref": [width, height]}), encoding="utf-8")
    print(f"截图已保存: {out}")
    print("裁剪模板: python tools/crop_tool.py")


if __name__ == "__main__":
    main()
