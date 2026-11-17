from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image
import io


class AdbError(RuntimeError):
    pass


_COMMON_ADB = [
    r"C:/Android/platform-tools/adb.exe",
    r"C:/Android/Sdk/platform-tools/adb.exe",
    r"C:/Program Files/Netease/MuMuPlayer-12.0/shell/adb.exe",
    r"C:/Program Files/Netease/MuMuPlayer-12.0/shell/adb.exe",
    r"C:/Program Files (x86)/Nox/bin/adb.exe",
    r"C:/Program Files/Nox/bin/adb.exe",
    r"C:/Program Files/BlueStacks_nxt/HD-Adb.exe",
    r"C:/Program Files/Microvirt/MEmu/adb.exe",
    r"C:/LDPlayer/LDPlayer9/adb.exe",
    r"C:/LDPlayer4.0/adb.exe",
    r"C:/Program Files/Scrcpy/adb.exe",
]


def find_adb(explicit: str | None = None, project_dir: Path | None = None) -> str:
    """按 显式配置 -> 环境变量 -> PATH -> 常见安装路径 的顺序查找 adb。"""
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    for key in ("ADB", "ADB_PATH", "ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.environ.get(key)
        if val:
            p = Path(val)
            candidates.append(str(p / "adb.exe" if p.is_dir() else p))
    which = shutil.which("adb")
    if which:
        candidates.append(which)

    base = project_dir or Path(__file__).resolve().parent.parent
    candidates += [
        str(base / "bin" / "platform-tools" / "adb.exe"),
        str(base / "bin" / "adb.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"),
        str(Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe"),
    ] + _COMMON_ADB

    for c in candidates:
        try:
            if c and Path(c).is_file():
                return str(Path(c))
        except OSError:
            continue

    raise AdbError(
        "没有找到 adb。请任选一种方式：\n"
        "  1. 安装 Android platform-tools，并把 adb 加入 PATH；\n"
        "  2. 运行 python tools/get_adb.py 自动下载到 bin/ 目录；\n"
        "  3. 在 config.yaml 的 device.adb 里写 adb.exe 的完整路径；\n"
        "  4. 使用模拟器自带的 adb（如 MuMu/LDPlayer/Nox 安装目录下的 adb.exe）。"
    )


class Adb:
    def __init__(self, adb_path: str | None = None, serial: str | None = None, project_dir: Path | None = None):
        self.adb = find_adb(adb_path, project_dir)
        self.serial = serial or None

    # ---------- 基础 ----------
    def _cmd(self, args: list[str]) -> list[str]:
        return [self.adb] + (["-s", self.serial] if self.serial else []) + list(args)

    def run(self, args: list[str], timeout: float = 30, check: bool = True) -> bytes:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.run(self._cmd(args), capture_output=True, timeout=timeout, **kwargs)
        except FileNotFoundError as exc:
            raise AdbError(f"无法执行 adb: {self.adb}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb 命令超时: {' '.join(args)}") from exc
        if check and proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "ignore").strip() or proc.stdout.decode("utf-8", "ignore").strip()
            raise AdbError(f"adb {' '.join(args)} 失败: {err}")
        return proc.stdout

    def version(self) -> str:
        out = self.run(["version"], timeout=10).decode("utf-8", "ignore").strip()
        return out.splitlines()[0] if out else ""

    # ---------- 设备 ----------
    def list_devices(self) -> dict[str, str]:
        out = self.run(["devices"], timeout=15).decode("utf-8", "ignore")
        devices: dict[str, str] = {}
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices[parts[0]] = parts[1]
        return devices

    def connect(self, target: str) -> str:
        return self.run(["connect", target], timeout=15, check=False).decode("utf-8", "ignore").strip()

    def resolve_serial(self, connect_targets: list[str] | None = None) -> str:
        if self.serial:
            return self.serial
        ready = [s for s, st in self.list_devices().items() if st == "device"]
        if not ready and connect_targets:
            for target in connect_targets:
                self.connect(target)
            time.sleep(0.5)
            ready = [s for s, st in self.list_devices().items() if st == "device"]
        if len(ready) == 1:
            self.serial = ready[0]
            return self.serial
        if len(ready) > 1:
            raise AdbError("检测到多个设备，请在 config.yaml 的 device.serial 指定序列号：\n  " + "\n  ".join(ready))
        raise AdbError(
            "没有已授权的设备。请检查：\n"
            "  - 手机：开启开发者选项和 USB 调试，数据线连接后手机上点“允许调试”；\n"
            "  - 模拟器：确认已启动，并在 config.yaml 的 device.connect 里加模拟器 adb 端口，"
            "例如 MuMu12 为 127.0.0.1:16384，LDPlayer 为 127.0.0.1:5555；\n"
            "  - 运行 python main.py --check 查看详情。"
        )

    # ---------- 画面 ----------
    def screencap(self) -> bytes:
        data = self.run(["exec-out", "screencap", "-p"], timeout=25, check=False)
        idx = data.find(b"\x89PNG\r\n\x1a\n")
        if idx >= 0:
            return data[idx:]

        with tempfile.TemporaryDirectory() as tmp:
            remote = "/sdcard/_auto_screen.png"
            local = Path(tmp) / "screen.png"
            self.run(["shell", "screencap", "-p", remote], timeout=25)
            self.run(["pull", remote, str(local)], timeout=25)
            self.run(["shell", "rm", "-f", remote], timeout=10, check=False)
            if not local.exists():
                raise AdbError("截图失败：既不能用 exec-out，也没能 pull 到文件")
            return local.read_bytes()

    def screen_size(self) -> tuple[int, int]:
        img = Image.open(io.BytesIO(self.screencap()))
        return img.size

    def wm_size(self) -> str:
        return self.run(["shell", "wm", "size"], timeout=10, check=False).decode("utf-8", "ignore").strip()

    # ---------- 操作 ----------
    def tap(self, x: int, y: int) -> None:
        self.run(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=10)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.run(
            ["shell", "input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms))],
            timeout=15,
        )

    def keyevent(self, code: str | int) -> None:
        self.run(["shell", "input", "keyevent", str(code)], timeout=10)

    def back(self) -> None:
        self.keyevent(4)

    def home(self) -> None:
        self.keyevent(3)

    # ---------- 应用 ----------
    def launch(self, package: str) -> bool:
        try:
            out = self.run(
                ["shell", "cmd", "package", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", package],
                timeout=15,
                check=False,
            ).decode("utf-8", "ignore").strip()
            activity = out.splitlines()[-1].strip() if out else ""
            if "/" in activity and "Exception" not in activity:
                self.run(["shell", "am", "start", "-n", activity], timeout=15)
                return True
        except AdbError:
            pass
        out = self.run(
            ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=20,
            check=False,
        ).decode("utf-8", "ignore")
        return "No activities found" not in out and "monkey aborted" not in out

    def force_stop(self, package: str) -> None:
        self.run(["shell", "am", "force-stop", package], timeout=15, check=False)

    def foreground(self) -> str:
        out = self.run(["shell", "dumpsys", "window", "windows"], timeout=20, check=False).decode("utf-8", "ignore")
        for pattern in (r"mCurrentFocus=.*?([\w.]+/[\w.$]+)", r"mFocusedApp=.*?([\w.]+/[\w.$]+)"):
            match = re.search(pattern, out)
            if match:
                return match.group(1)
        return ""
