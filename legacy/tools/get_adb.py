from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BASE_DIR / "bin"

URLS = [
    "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "https://googledownloads.cn/android/repository/platform-tools-latest-windows.zip",
]


def download(url: str, dest: Path, timeout: float = 60) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            received += len(chunk)
            if total:
                print(f"\r下载中 {received * 100 // total}%  ({received // 1048576}/{total // 1048576} MB)", end="")
        print()


def install(zip_path: Path) -> Path:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(BIN_DIR)
    adb = BIN_DIR / "platform-tools" / "adb.exe"
    if not adb.is_file():
        raise RuntimeError(f"解压后没有找到 {adb}")
    return adb


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 Android platform-tools 到 bin/ 目录")
    parser.add_argument("--url", default=None, help="自定义下载地址")
    args = parser.parse_args()

    urls = [args.url] if args.url else URLS
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "platform-tools.zip"
        for url in urls:
            print(f"尝试: {url}")
            try:
                download(url, zip_path)
                adb = install(zip_path)
                print(f"完成: {adb}")
                print("现在可以运行: python main.py --check")
                return
            except Exception as exc:
                print(f"失败: {exc}")
                continue
    print("全部下载源都失败了。可以手动下载 platform-tools 解压到 bin/ 目录：")
    print("  https://developer.android.com/studio/releases/platform-tools")
    sys.exit(1)


if __name__ == "__main__":
    main()
