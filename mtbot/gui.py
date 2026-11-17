"""图形界面（Tkinter）：任务勾选 / 轮次 / 运行队列 / 当前任务 / OAS 风格实时日志。

启动：
  python -I E:\\Reverse\\auto_script\\mt.py --gui
  或 python -I -m mtbot.gui

界面素材来自解包资源（E:/Reverse/export）：
  - 顶部横幅：hero_details_back_3 的城堡段（压暗左侧放标题）
  - 应用图标：ic_launcher_foreground
  - 分类图标：icon_zc_kfkh（战斗）/ icon_xsfl_ysz（奖励）/ icon_zc_kfgh（提升）
生成脚本见 tools/make_gui_assets.py，产物在 mtbot/gui_assets/。

功能要点（仿 OASX）：
  - 左上角任务勾选 + 预设；右侧按任务改参数，运行前写回 config.json；
  - 「轮次」可设置整套任务重复跑 N 遍；
  - 顶部状态卡显示**当前任务 / 当前界面 / 第几轮 / 队列进度**；
  - 「任务队列」表格按优先级列出待执行任务，随日志实时切换 等待/进行中/完成/失败；
  - 运行在独立子进程里，日志逐行回显（DEBUG 可开关）。
"""
from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import tasks
from .config import PARAM_SPECS, PROFILES, ROOT, Config, load

ROOT_DIR = ROOT
CFG_PATH = ROOT / "config.json"
MT_PY = ROOT / "mt.py"
ASSETS = Path(__file__).resolve().parent / "gui_assets"

CATEGORY_TITLE = {"combat": "战斗", "reward": "奖励", "upgrade": "提升"}
CATEGORY_ICON = {"combat": "cat_combat.png", "reward": "cat_reward.png",
                 "upgrade": "cat_upgrade.png"}
LEVEL_COLORS = {"DEBUG": "#8b8378", "INFO": "#7fb2e5", "WARN": "#e0b45a", "ERROR": "#ef7b68"}

UI_BG = "#14100b"
PANEL = "#201811"
PANEL2 = "#2a2016"
BORDER = "#6b4a26"
GOLD = "#c6952f"
GOLD_HI = "#f0cf7a"
TEXT = "#e9dcc2"
MUTED = "#a4916f"
GREEN = "#7fd18a"
RED = "#ef7b68"


def save_config(cfg: Config) -> None:
    data = {
        "device": {
            "adb": cfg.device.adb, "serial": cfg.device.serial,
            "package": cfg.device.package, "activity": cfg.device.activity,
        },
        "emulator": {"manager": cfg.emulator.manager, "vm": cfg.emulator.vm,
                     "start": cfg.emulator.start},
        "runtime": {
            "screenshot_dir": cfg.runtime.screenshot_dir,
            "state_file": cfg.runtime.state_file,
            "tap_ms": cfg.runtime.tap_ms,
            "keep_screenshots": cfg.runtime.keep_screenshots,
            "max_task_minutes": cfg.runtime.max_task_minutes,
        },
        "limits": {"diamond_budget": cfg.limits.diamond_budget,
                   "gold_keep": cfg.limits.gold_keep},
        "tasks": {n: {"enabled": t.enabled, "priority": t.priority, "params": t.params}
                  for n, t in cfg.tasks.items()},
    }
    CFG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_content(line: str) -> str:
    """从 OAS 风格日志行里取出正文（去掉时间戳和 [文件:行号] 前缀）。"""
    if "│" not in line:
        return line.strip()
    body = line.split("│", 1)[1]
    m = re.match(r"\s*\[[^\]]*\]\s?(.*)$", body)
    return (m.group(1) if m else body).strip()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load(CFG_PATH if CFG_PATH.exists() else None)
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue[str] = queue.Queue()
        self.selected: set[str] = {n for n, t in self.cfg.tasks.items() if t.enabled}
        self.current_task: str | None = None
        self.param_vars: dict[str, tk.Variable] = {}

        self.queue_names: list[str] = []
        self.running_name: str | None = None
        self.round_text = "—"
        self.round_start = 0.0
        self.images: dict[str, tk.PhotoImage] = {}

        root.title("mtbot · 我叫MT：崛起 自动化控制台")
        root.geometry("1240x820")
        root.minsize(1080, 700)
        self._load_assets()
        self._setup_style()

        self._build_header()
        self._build_toolbar()
        self._build_body()
        self._build_footer()
        self.root.after(120, self._poll_queue)

    # ---------- 素材与主题 ----------
    def _load_assets(self) -> None:
        for name in ("banner.png", "logo.png", "cat_combat.png", "cat_reward.png",
                     "cat_upgrade.png", "gold.png", "diamond.png"):
            p = ASSETS / name
            if p.exists():
                try:
                    self.images[name] = tk.PhotoImage(file=str(p))
                except tk.TclError:
                    pass
        if "logo.png" in self.images:
            try:
                self.root.iconphoto(True, self.images["logo.png"])
            except tk.TclError:
                pass

    def _setup_style(self) -> None:
        self.root.configure(bg=UI_BG)
        s = ttk.Style(self.root)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=PANEL, foreground=TEXT, fieldbackground=PANEL2,
                    font=("Microsoft YaHei UI", 9))
        s.configure("TFrame", background=PANEL)
        s.configure("Dark.TFrame", background=UI_BG)
        s.configure("Card.TFrame", background=PANEL2)
        s.configure("TLabel", background=PANEL, foreground=TEXT)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("DarkMuted.TLabel", background=UI_BG, foreground=MUTED)
        s.configure("Gold.TLabel", foreground=GOLD_HI)
        s.configure("Title.TLabel", font=("Microsoft YaHei UI", 10, "bold"),
                    foreground=GOLD_HI)
        s.configure("Big.TLabel", font=("Microsoft YaHei UI", 13, "bold"),
                    foreground=GOLD_HI, background=PANEL2)
        s.configure("Card.TLabel", background=PANEL2, foreground=TEXT)
        s.configure("CardMuted.TLabel", background=PANEL2, foreground=MUTED)
        s.configure("TButton", padding=(12, 5))
        s.configure("Gold.TButton", background=GOLD, foreground="#241708",
                    font=("Microsoft YaHei UI", 9, "bold"), borderwidth=0)
        s.map("Gold.TButton",
              background=[("active", GOLD_HI), ("disabled", "#6a552e")],
              foreground=[("disabled", "#3a2d17")])
        s.configure("Red.TButton", background="#8f2f24", foreground="#ffe9e0",
                    borderwidth=0)
        s.map("Red.TButton", background=[("active", "#b24334"), ("disabled", "#5a2a24")],
              foreground=[("disabled", "#3a2320")])
        s.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        s.map("TCheckbutton", background=[("active", PANEL)])
        s.configure("Card.TCheckbutton", background=PANEL2, foreground=TEXT)
        s.map("Card.TCheckbutton", background=[("active", PANEL2)])
        s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                    foreground=TEXT, arrowcolor=TEXT)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
              foreground=[("readonly", TEXT)])
        s.configure("TSpinbox", fieldbackground=PANEL2, background=PANEL2,
                    foreground=TEXT, arrowcolor=GOLD_HI)
        s.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT,
                    insertcolor=TEXT)
        s.configure("Treeview", background=PANEL2, fieldbackground=PANEL2,
                    foreground=TEXT, rowheight=23, borderwidth=0)
        s.configure("Treeview.Heading", background=PANEL, foreground=GOLD_HI,
                    font=("Microsoft YaHei UI", 9, "bold"))
        s.map("Treeview", background=[("selected", "#4b3a22")],
              foreground=[("selected", "#ffe9b0")])
        s.configure("TLabelframe", background=PANEL, bordercolor=BORDER)
        s.configure("TLabelframe.Label", background=PANEL, foreground=GOLD_HI,
                    font=("Microsoft YaHei UI", 9, "bold"))
        s.configure("Horizontal.TProgressbar", troughcolor=PANEL2, bordercolor=BORDER,
                    background=GOLD, lightcolor=GOLD, darkcolor=GOLD)
        s.configure("TPanedwindow", background=UI_BG)
        s.configure("Sash", background=BORDER)

    # ---------- 顶部横幅 ----------
    def _build_header(self) -> None:
        header = tk.Canvas(self.root, height=124, highlightthickness=0, bg=UI_BG)
        header.pack(fill="x")
        if "banner.png" in self.images:
            header.create_image(0, 0, image=self.images["banner.png"], anchor="nw")
        if "logo.png" in self.images:
            header.create_image(20, 62, image=self.images["logo.png"], anchor="w")
        header.create_text(96, 42, text="我叫MT：崛起 · mtbot 自动化控制台",
                           fill="#ffe9b0", font=("Microsoft YaHei UI", 17, "bold"),
                           anchor="w")
        header.create_text(98, 78, text="任务勾选 · 轮次 · 运行队列 · 实时日志",
                           fill="#f2e3c2", font=("Microsoft YaHei UI", 9), anchor="w")
        self.header = header

    # ---------- 工具栏 ----------
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, style="Dark.TFrame")
        bar.pack(fill="x", padx=10, pady=(6, 2))

        ttk.Label(bar, text="预设", style="DarkMuted.TLabel").pack(side="left")
        self.profile_var = tk.StringVar(value="（自定义）")
        self.profile_box = ttk.Combobox(bar, textvariable=self.profile_var, width=9,
                                        values=["（自定义）"] + sorted(PROFILES),
                                        state="readonly")
        self.profile_box.pack(side="left", padx=(4, 10))
        self.profile_box.bind("<<ComboboxSelected>>", self._on_profile)

        ttk.Button(bar, text="全选", command=self.select_all).pack(side="left", padx=2)
        ttk.Button(bar, text="全不选", command=self.select_none).pack(side="left", padx=2)
        ttk.Button(bar, text="反选", command=self.invert).pack(side="left", padx=(2, 12))

        ttk.Label(bar, text="轮次", style="DarkMuted.TLabel").pack(side="left")
        self.rounds_var = tk.StringVar(value="1")
        self.rounds_box = ttk.Spinbox(bar, from_=1, to=99, width=4,
                                      textvariable=self.rounds_var)
        self.rounds_box.pack(side="left", padx=(4, 12))

        self.boot_var = tk.BooleanVar(value=True)
        self.emu_var = tk.BooleanVar(value=False)
        self.cold_var = tk.BooleanVar(value=False)
        self.debug_var = tk.BooleanVar(value=False)
        for text, var in (("登录游戏", self.boot_var), ("拉起模拟器", self.emu_var),
                          ("冷启动", self.cold_var), ("点击调试", self.debug_var)):
            ttk.Checkbutton(bar, text=text, variable=var).pack(side="left", padx=3)

        self.run_sel_btn = ttk.Button(bar, text="▶ 运行选中任务", style="Gold.TButton",
                                      command=self.run_selected)
        self.run_sel_btn.pack(side="right")
        self.run_one_btn = ttk.Button(bar, text="▶ 运行当前任务", command=self.run_current)
        self.run_one_btn.pack(side="right", padx=6)
        self.stop_btn = ttk.Button(bar, text="⏹ 停止", style="Red.TButton",
                                   command=self.stop, state="disabled")
        self.stop_btn.pack(side="right", padx=6)
        ttk.Button(bar, text="日志目录", command=self.open_logs).pack(side="right", padx=6)

    # ---------- 主体 ----------
    def _build_body(self) -> None:
        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=4)

        left = ttk.Labelframe(body, text="任务列表（勾选组合，双击编辑参数）")
        body.add(left, weight=2)
        self._build_tasks(left)

        right = ttk.Frame(body)
        body.add(right, weight=5)
        self._build_status(right)
        mid = ttk.Frame(right)
        mid.pack(fill="both", expand=False)
        self._build_params(mid)     # 先占右侧固定宽度，再让队列吃掉剩余空间
        self._build_queue(mid)
        self._build_log(right)

    def _build_tasks(self, frame) -> None:
        canvas = tk.Canvas(frame, borderwidth=0, highlightthickness=0, bg=PANEL)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        self.task_frame = ttk.Frame(canvas)
        self.task_frame.bind("<Configure>",
                             lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.task_frame, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.check_vars: dict[str, tk.BooleanVar] = {}
        self.task_buttons: dict[str, ttk.Checkbutton] = {}
        self.task_rows: dict[str, ttk.Frame] = {}
        by_cat: dict[str, list[str]] = {}
        for name in tasks.names():
            by_cat.setdefault(tasks.TASK_CLASSES[name].category, []).append(name)
        for cat in ("combat", "reward", "upgrade"):
            head = ttk.Frame(self.task_frame)
            head.pack(fill="x", pady=(8, 2))
            icon = self.images.get(CATEGORY_ICON.get(cat, ""))
            if icon is not None:
                tk.Label(head, image=icon, bg=PANEL).pack(side="left", padx=(4, 4))
            ttk.Label(head, text=CATEGORY_TITLE.get(cat, cat), style="Title.TLabel",
                      font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
            for name in sorted(by_cat.get(cat, []),
                               key=lambda n: self.cfg.task(n).priority):
                var = tk.BooleanVar(value=name in self.selected)
                row = ttk.Frame(self.task_frame)
                row.pack(fill="x", padx=(24, 4))
                cb = ttk.Checkbutton(row, text=f"{name} · {tasks.TASK_CLASSES[name].title}",
                                     variable=var, command=lambda n=name: self._toggle(n))
                cb.pack(side="left", anchor="w")
                cb.bind("<Double-Button-1>", lambda e, n=name: self._select_task(n))
                self.check_vars[name] = var
                self.task_buttons[name] = cb
                self.task_rows[name] = row
        self._refresh_state_marks()

    def _state_map(self) -> dict:
        p = ROOT / "logs" / "state.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _refresh_state_marks(self) -> None:
        """任务名后面标上次结果：✓ 成功 / ✗ 失败。"""
        st = self._state_map()
        for name, cb in getattr(self, "task_buttons", {}).items():
            info = st.get(name)
            mark = "" if not info else ("  ✓" if info.get("ok") else "  ✗")
            cb.configure(text=f"{name} · {tasks.TASK_CLASSES[name].title}{mark}")

    # ---------- 状态卡 ----------
    def _build_status(self, parent) -> None:
        wrap = ttk.Frame(parent, style="Card.TFrame")
        wrap.pack(fill="x")
        card = tk.Frame(wrap, bg=PANEL2, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", padx=6, pady=6)

        tk.Label(card, text="当前任务", bg=PANEL2, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w",
                                                      padx=12, pady=(8, 0))
        self.cur_task_var = tk.StringVar(value="空闲（等待开始）")
        tk.Label(card, textvariable=self.cur_task_var, bg=PANEL2, fg=GOLD_HI,
                 font=("Microsoft YaHei UI", 14, "bold"), anchor="w").grid(
            row=1, column=0, sticky="w", padx=12)
        self.page_var = tk.StringVar(value="界面：—")
        tk.Label(card, textvariable=self.page_var, bg=PANEL2, fg=TEXT,
                 font=("Microsoft YaHei UI", 9), anchor="w").grid(
            row=2, column=0, sticky="w", padx=12, pady=(2, 8))

        right = tk.Frame(card, bg=PANEL2)
        right.grid(row=0, column=1, rowspan=3, sticky="e", padx=16)
        self.round_var = tk.StringVar(value="轮次：—")
        tk.Label(right, textvariable=self.round_var, bg=PANEL2, fg=TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="e")
        self.queue_var = tk.StringVar(value="队列：0 / 0")
        tk.Label(right, textvariable=self.queue_var, bg=PANEL2, fg=MUTED).pack(anchor="e")
        self.progress = ttk.Progressbar(right, length=260, mode="determinate")
        self.progress.pack(anchor="e", pady=(6, 0))
        card.columnconfigure(0, weight=1)

    # ---------- 运行队列 ----------
    def _build_queue(self, parent) -> None:
        frame = ttk.Labelframe(parent, text="待执行队列（按优先级）")
        frame.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        cols = ("status", "idx", "name", "title")
        self.queue = ttk.Treeview(frame, columns=cols, show="headings", height=6)
        for c, t, w, anchor in (("status", "状态", 70, "center"),
                                ("idx", "#", 40, "center"),
                                ("name", "任务", 130, "w"),
                                ("title", "说明", 420, "w")):
            self.queue.heading(c, text=t)
            self.queue.column(c, width=w, anchor=anchor)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.queue.yview)
        self.queue.configure(yscrollcommand=vsb.set)
        self.queue.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vsb.pack(side="right", fill="y", pady=6)
        self.queue.tag_configure("pending", foreground=MUTED)
        self.queue.tag_configure("running", background="#4a3417", foreground="#ffdf9e")
        self.queue.tag_configure("done", foreground=GREEN)
        self.queue.tag_configure("fail", foreground=RED)
        self.queue.tag_configure("skip", foreground="#b9a37e")

    def _queue_rebuild(self, names: list[str]) -> None:
        self.queue.delete(*self.queue.get_children())
        self.queue_names = list(names)
        self.running_name = None
        for i, n in enumerate(names, 1):
            title = tasks.TASK_CLASSES[n].title if n in tasks.TASK_CLASSES else "?"
            self.queue.insert("", "end", iid=n, values=("等待", i, n, title),
                              tags=("pending",))
        self._queue_counter()

    def _queue_mark(self, name: str, state: str, note: str = "") -> None:
        if name not in self.queue.get_children():
            return
        marks = {"running": "进行中", "done": "完成", "fail": "失败", "skip": "跳过"}
        vals = list(self.queue.item(name, "values"))
        vals[0] = marks.get(state, state)
        if note:
            vals[3] = note
        self.queue.item(name, values=vals, tags=(state,))
        if state == "running":
            self.running_name = name
            self.queue.see(name)
        elif name == self.running_name:
            self.running_name = None
        self._queue_counter()

    def _queue_finish_rest(self) -> None:
        """进程结束时把还挂着的行收尾（被停止/中止时不会再有 OK/FAIL 行）。"""
        for n in self.queue.get_children():
            vals = list(self.queue.item(n, "values"))
            if vals[0] == "进行中":
                vals[0] = "中断"
                self.queue.item(n, values=vals, tags=("skip",))
            elif vals[0] == "等待":
                vals[0] = "未执行"
                self.queue.item(n, values=vals, tags=("skip",))
        self._queue_counter()

    def _queue_counter(self) -> None:
        total = len(self.queue_names)
        done = sum(1 for n in self.queue_names
                   if n in self.queue.get_children()
                   and self.queue.item(n, "values")[0] in
                   ("完成", "失败", "跳过", "中断", "未执行"))
        cur = self.running_name
        pos = (self.queue_names.index(cur) + 1) if cur in self.queue_names else done
        self.queue_var.set(f"队列：{min(pos, total)} / {total}")
        self.progress.configure(maximum=max(total, 1), value=done)

    # ---------- 参数区 ----------
    def _build_params(self, parent) -> None:
        holder = ttk.Frame(parent, width=400)
        holder.pack(side="right", fill="y", padx=6, pady=(0, 6))
        holder.pack_propagate(False)
        frame = ttk.Labelframe(holder, text="任务参数")
        frame.pack(fill="both", expand=True)
        self.param_area = ttk.Frame(frame)
        self.param_area.pack(fill="x", padx=8, pady=6)
        self.param_hint = ttk.Label(frame, text="← 双击任务后修改参数",
                                    style="Muted.TLabel")
        self.param_hint.pack(anchor="w", padx=8)

        g = ttk.Labelframe(frame, text="全局选项")
        g.pack(fill="x", padx=8, pady=(6, 8))
        self.diamond_var = tk.StringVar(value=str(self.cfg.limits.diamond_budget))
        self.minutes_var = tk.StringVar(value=str(self.cfg.runtime.max_task_minutes))
        for icon_name, text, var in (
                ("diamond.png", "全局钻石预算", self.diamond_var),
                ("gold.png", "单任务超时(分钟)", self.minutes_var)):
            row = ttk.Frame(g)
            row.pack(anchor="w", pady=2, padx=(0, 10))
            if icon_name in self.images:
                tk.Label(row, image=self.images[icon_name], bg=PANEL).pack(
                    side="left", padx=(4, 4))
            ttk.Label(row, text=text).pack(side="left")
            ttk.Entry(row, textvariable=var, width=7).pack(side="left", padx=(8, 0))

    # ---------- 日志 ----------
    def _build_log(self, parent) -> None:
        frame = ttk.Labelframe(parent, text="运行日志（OAS 风格：等级 · 毫秒时间 · 文件:行号）")
        frame.pack(fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        self.log_text = tk.Text(frame, height=16, wrap="none", font=("Consolas", 9),
                                bg="#0f0c08", fg=TEXT, insertbackground=TEXT,
                                relief="flat", highlightthickness=0)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vsb.pack(side="right", fill="y", pady=6)
        for level, color in LEVEL_COLORS.items():
            self.log_text.tag_configure(level, foreground=color)
        self.log_text.tag_configure("STATE", foreground="#7fd18a")

    # ---------- 底栏 ----------
    def _build_footer(self) -> None:
        bar = ttk.Frame(self.root, style="Dark.TFrame")
        bar.pack(fill="x", padx=10, pady=(0, 6))
        self.status_var = tk.StringVar(value="空闲")
        ttk.Label(bar, textvariable=self.status_var,
                  style="DarkMuted.TLabel").pack(side="left")

    # ---------- 交互 ----------
    def _toggle(self, name: str) -> None:
        if self.check_vars[name].get():
            self.selected.add(name)
        else:
            self.selected.discard(name)

    def _select_task(self, name: str) -> None:
        self.current_task = name
        self._render_params(name)

    def _render_params(self, name: str) -> None:
        for w in self.param_area.winfo_children():
            w.destroy()
        self.param_vars.clear()
        specs = PARAM_SPECS.get(name, {})
        params = self.cfg.task(name).params
        ttk.Label(self.param_area, text=f"{name} · {tasks.TASK_CLASSES[name].title}",
                  style="Title.TLabel").grid(row=0, column=0, columnspan=3,
                                             sticky="w", pady=(0, 4))
        if not specs:
            ttk.Label(self.param_area, text="（该任务没有可配置项）",
                      style="Muted.TLabel").grid(row=1, column=0, sticky="w")
            self.param_hint.configure(text="参数会写入 config.json，运行前自动保存")
            return
        for i, (key, spec) in enumerate(specs.items(), start=1):
            ttk.Label(self.param_area, text=spec.get("label", key)).grid(
                row=i, column=0, sticky="w", padx=4, pady=2)
            cur = params.get(key, spec.get("default"))
            if spec["type"] == "bool":
                var: tk.Variable = tk.BooleanVar(value=bool(cur))
                ttk.Checkbutton(self.param_area, variable=var).grid(row=i, column=1, sticky="w")
            else:
                var = tk.StringVar(value=str(cur))
                ttk.Entry(self.param_area, textvariable=var, width=12).grid(
                    row=i, column=1, sticky="w")
            self.param_vars[key] = var
            if spec.get("min") is not None or spec.get("max") is not None:
                ttk.Label(self.param_area,
                          text=f"{spec.get('min', '')}~{spec.get('max', '')}",
                          style="Muted.TLabel").grid(row=i, column=2, sticky="w")
        self.param_hint.configure(text="参数会写入 config.json，运行前自动保存")

    def _collect_params(self) -> None:
        name = self.current_task
        if name:
            params = self.cfg.task(name).params
            for key, var in self.param_vars.items():
                val = var.get()
                spec = PARAM_SPECS.get(name, {}).get(key, {})
                if spec.get("type") == "int":
                    try:
                        val = int(str(val).strip())
                    except ValueError:
                        messagebox.showerror("参数错误", f"{key} 需要整数")
                        raise
                params[key] = val
        try:
            self.cfg.limits.diamond_budget = int(self.diamond_var.get())
            self.cfg.runtime.max_task_minutes = int(self.minutes_var.get())
        except ValueError:
            messagebox.showerror("参数错误", "全局钻石预算/超时需要整数")
            raise

    def _on_profile(self, _evt=None) -> None:
        name = self.profile_var.get()
        if name == "（自定义）":
            return
        wanted = PROFILES.get(name)
        if wanted is None:
            wanted = tasks.names()
        self.selected = set(wanted)
        for n, var in self.check_vars.items():
            var.set(n in self.selected)

    def select_all(self) -> None:
        self.selected = set(self.check_vars)
        for v in self.check_vars.values():
            v.set(True)
        self.profile_var.set("（自定义）")

    def select_none(self) -> None:
        self.selected.clear()
        for v in self.check_vars.values():
            v.set(False)
        self.profile_var.set("（自定义）")

    def invert(self) -> None:
        self.selected = {n for n in self.check_vars if n not in self.selected}
        for n, v in self.check_vars.items():
            v.set(n in self.selected)
        self.profile_var.set("（自定义）")

    # ---------- 运行 ----------
    def run_selected(self) -> None:
        names = [n for n in tasks.names() if n in self.selected]
        self._run(names)

    def run_current(self) -> None:
        if not self.current_task:
            messagebox.showinfo("提示", "先在左侧双击选择一个任务")
            return
        self._run([self.current_task])

    def _rounds(self) -> int:
        try:
            return max(1, min(99, int(self.rounds_var.get())))
        except ValueError:
            return 1

    def _run(self, names: list[str]) -> None:
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("提示", "已有任务在运行")
            return
        if not names:
            messagebox.showwarning("提示", "没有勾选任何任务")
            return
        try:
            self._collect_params()
        except ValueError:
            return
        save_config(self.cfg)

        rounds = self._rounds()
        names = sorted(names, key=lambda n: self.cfg.task(n).priority)
        cmd = [sys.executable, "-I", str(MT_PY), "--task", ",".join(names),
               "--rounds", str(rounds)]
        if self.boot_var.get():
            cmd.append("--boot")
        if self.emu_var.get():
            cmd.append("--emulator")
        if self.cold_var.get():
            cmd.append("--cold")
        self._append(f"$ {' '.join(cmd)}\n", "STATE")
        self._queue_rebuild(names)
        self.round_text = f"1 / {rounds}" if rounds > 1 else "单轮"
        self.round_var.set(f"轮次：第 {self.round_text} 轮" if rounds > 1 else "轮次：单轮")
        self.cur_task_var.set("准备启动…")
        self.root.title("mtbot · 准备启动…")
        self.page_var.set("界面：—")
        self.round_start = time.time()
        self.progress.configure(maximum=max(len(names), 1), value=0)
        self.status_var.set(f"运行中：{len(names)} 个任务 × {rounds} 轮")
        self.run_sel_btn.configure(state="disabled")
        self.run_one_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                     errors="replace", bufsize=1)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self.q.put(line)
        self.q.put(f"__EXIT__{proc.wait()}\n")

    def _poll_queue(self) -> None:
        try:
            while True:
                line = self.q.get_nowait()
                if line.startswith("__EXIT__"):
                    code = line.replace("__EXIT__", "").strip()
                    elapsed = time.time() - self.round_start if self.round_start else 0
                    self._append(f"—— 进程结束（exit {code}，用时 {elapsed:.0f}s）——\n", "STATE")
                    self.status_var.set(f"空闲（上次 exit {code}）")
                    self.cur_task_var.set("空闲（等待开始）")
                    self.root.title("mtbot · 我叫MT：崛起 自动化控制台")
                    self.run_sel_btn.configure(state="normal")
                    self.run_one_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.proc = None
                    self._queue_finish_rest()
                    self._refresh_state_marks()
                    continue
                level = "INFO"
                for lv in LEVEL_COLORS:
                    if line.lstrip().startswith(lv):
                        level = lv
                        break
                if level == "DEBUG" and not self.debug_var.get():
                    continue
                self._track(line)
                self._append(line, level)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _track(self, line: str) -> None:
        """从日志里维护：当前任务 / 队列状态 / 轮次 / 当前界面。"""
        content = _log_content(line)
        m = re.search(r"=====\s*第\s*(\d+)\s*/\s*(\d+)\s*轮\s*=====", content)
        if m:
            self.round_text = f"{m.group(1)} / {m.group(2)}"
            self.round_var.set(f"轮次：第 {self.round_text} 轮")
            for n in self.queue.get_children():
                vals = list(self.queue.item(n, "values"))
                vals[0] = "等待"
                self.queue.item(n, values=vals, tags=("pending",))
            self.running_name = None
            self._queue_counter()
            return
        if content.startswith("共 ") and "个任务:" in content:
            names = [x.strip() for x in content.split(":", 1)[1].split(",") if x.strip()]
            if names and (not self.queue_names or set(names) != set(self.queue_names)):
                self._queue_rebuild(names)
            return
        m = re.search(r"Current task:\s*(\S+)", content)
        if m:
            name = m.group(1)
            self._queue_mark(name, "running")
            title = tasks.TASK_CLASSES[name].title if name in tasks.TASK_CLASSES else ""
            self.cur_task_var.set(f"{name} · {title}")
            self.root.title(f"mtbot · 运行中：{name} · 我叫MT：崛起 自动化控制台")
            return
        if content.startswith("OK ") or content.startswith("FAIL "):
            ok = content.startswith("OK ")
            msg = content.split(" ", 1)[1].strip() if " " in content else ""
            if self.running_name:
                self._queue_mark(self.running_name, "done" if ok else "fail", msg)
            return
        if content.startswith("完成 ") and "个任务" in content:
            self.status_var.set(content)
            return
        if "中止运行" in content or "本次运行被中止" in content:
            if self.running_name:
                self._queue_mark(self.running_name, "fail", content[:40])
            for n in self.queue.get_children():
                vals = list(self.queue.item(n, "values"))
                if vals[0] == "等待":
                    vals[0] = "未执行"
                    self.queue.item(n, values=vals, tags=("skip",))
            self._queue_counter()
            return
        if "[UI]" in line:
            page = line.split("[UI]", 1)[1].strip()
            self.page_var.set(f"界面：{page}")

    def _append(self, text: str, tag: str = "INFO") -> None:
        self.log_text.insert("end", text, tag)
        self.log_text.see("end")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._append("—— 已发送停止信号 ——\n", "WARN")
            self.status_var.set("正在停止…")

    @staticmethod
    def open_logs() -> None:
        p = ROOT / "logs"
        p.mkdir(exist_ok=True)
        subprocess.Popen(["explorer", str(p)])


def main() -> int:
    try:                       # Windows 高 DPI 下字更清晰
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:          # noqa: BLE001
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
