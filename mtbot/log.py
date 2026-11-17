"""统一日志（OAS 风格）：

    INFO     2026-10-29 09:11:59.675 │ No task pending
    INFO     2026-10-29 09:11:59.677 │ [Task] WantedQuests (Enable, 5, 2026-10-29 11:40:47)
    INFO     2026-10-29 09:12:00.672 │ <<< UI GOTO PAGE_MAIN >>>
    INFO     2026-10-29 09:12:01.614 │ [UI] page_main
    INFO     2026-10-29 09:12:04.606 │ [3.9s] Page arrived page_main
    ERROR    2026-10-29 09:12:09.101 │ [pages.py:210] ...

- 每条日志带毫秒级时间戳和来源文件:行号（调用处），出问题时能直接定位到哪一行。
- 控制台 + logs/mtbot_YYYYMMDD.log 双写；GUI 通过 stdout 订阅。
"""
from __future__ import annotations

import inspect
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
_LEVEL_WIDTH = 8


def _source(skip: int = 2) -> str:
    """返回调用处的 文件:行号（相对 mtbot 目录）。

    2026-10-30 修：用相对路径启动（如 `python tests/test_log.py`）时，
    co_filename 是相对路径，relative_to 失败后拿到的是 str，str 没有
    as_posix 会抛 AttributeError，来源就退化成 "-"。现在先转成绝对路径。
    """
    try:
        frame = sys._getframe(skip)
        path = Path(frame.f_code.co_filename)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = Path(path.name)
        return f"{rel.as_posix()}:{frame.f_lineno}"
    except Exception:  # noqa: BLE001
        return "-"


# 2026-11-15：控制台输出改成「后台线程 + 有界队列」。
# 真因：在 Windows 控制台里误点一下窗口就进入「标记/选择」模式，控制台停止读，
# 进程的 print 会在管道里无限期阻塞（PID 59096 就是这么冻结的：CPU 3.06s 不再增长、
# 22 个线程全 Wait、日志停在半句话上，锁文件却一直占着，之后每一轮都 exit 4）。
# 现在文件始终先写（证据不丢），控制台写入交给守护线程；队列满了就丢控制台行，
# 主流程再也不会被控制台卡死。
_CONSOLE_Q: "queue.Queue[str]" = queue.Queue(maxsize=4000)
_CONSOLE_DROPPED = 0
_CONSOLE_STOP = object()
_console_lock = threading.Lock()
_console_thread = None


def _console_worker() -> None:
    while True:
        line = _CONSOLE_Q.get()
        if line is _CONSOLE_STOP:
            return
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass


def _ensure_console_thread() -> None:
    global _console_thread
    with _console_lock:
        if _console_thread is None or not _console_thread.is_alive():
            _console_thread = threading.Thread(
                target=_console_worker, name="mtbot-console", daemon=True)
            _console_thread.start()


def flush(timeout: float = 2.0) -> None:
    """把控制台队列排空（测试与收尾用；正常运行时不需要调）。"""
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        _ensure_console_thread()
        if _CONSOLE_Q.empty():
            time.sleep(0.02)
            if _CONSOLE_Q.empty():
                return
        time.sleep(0.01)


def _stdout_is_real() -> bool:
    """真句柄（控制台/管道/文件）才可能有「对面不读 → print 永久阻塞」的问题。"""
    try:
        sys.stdout.fileno()
        return True
    except Exception:  # noqa: BLE001  StringIO / 被替换的捕获对象
        return False


def _emit(line: str) -> None:
    """控制台输出：真句柄走队列（永不阻塞）；被捕获时同步写（调用即见）。"""
    global _CONSOLE_DROPPED
    if not _stdout_is_real():
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        return
    _ensure_console_thread()
    try:
        _CONSOLE_Q.put_nowait(line)
    except queue.Full:
        _CONSOLE_DROPPED += 1


def _write(level: str, msg: str, with_source: bool = True) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    src = f"[{_source(3)}] " if with_source else ""
    line = f"{level:<{_LEVEL_WIDTH}} {ts} │ {src}{msg}"
    try:
        with (LOG_DIR / f"mtbot_{datetime.now():%Y%m%d}.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    _emit(line)


def debug(msg: str) -> None:
    _write("DEBUG", msg)


def info(msg: str, with_source: bool = True) -> None:
    _write("INFO", msg, with_source)


def warn(msg: str) -> None:
    _write("WARN", msg)


def error(msg: str) -> None:
    _write("ERROR", msg)


# OAS 风格的界面/页面专用标签
def ui(msg: str) -> None:
    _write("INFO", f"[UI] {msg}", with_source=False)


def goto(page: str) -> None:
    _write("INFO", f"<<< UI GOTO PAGE_{page.upper()} >>>", with_source=False)


def arrived(page: str, seconds: float) -> None:
    _write("INFO", f"[{seconds:.1f}s] Page arrived page_{page}", with_source=False)


def task(name: str, msg: str) -> None:
    _write("INFO", f"[Task] {msg}", with_source=False)
