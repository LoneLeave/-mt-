"""配置：dataclass + JSON。所有可调参数集中在这里，业务代码不写死。

config.json 结构：
{
  "device":   {"adb": "...", "serial": "127.0.0.1:16384",
               "package": "com.wjmtjq.ma.android",
               "activity": "com.hnyl.core.fragment.AgreementSplashActivity"},
  "emulator": {"manager": "...MuMuManager.exe", "vm": "0", "start": true},
  "runtime":  {"screenshot_dir": "logs/screens", "state_file": "logs/state.json",
               "tap_ms": 220, "max_task_minutes": 40},
  "limits":   {"diamond_budget": 200, "gold_keep": 50000},
  "tasks":    {"tower": {"enabled": true, "params": {"max_wins": 100, "max_lose": 10}},
               ...}
}
未出现的任务使用内置默认值。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.json"


@dataclass
class DeviceConfig:
    adb: str = r"D:\Program Files\Netease\MuMu Player 12\shell\adb.exe"
    serial: str = "127.0.0.1:16384"
    package: str = "com.wjmtjq.ma.android"
    activity: str = "com.hnyl.core.fragment.AgreementSplashActivity"


@dataclass
class EmulatorConfig:
    manager: str = r"D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe"
    vm: str = "0"
    start: bool = True          # 允许脚本自己拉起模拟器


@dataclass
class RuntimeConfig:
    screenshot_dir: str = "logs/screens"
    state_file: str = "logs/state.json"
    tap_ms: int = 220           # 本作 50ms tap 经常不触发，统一用长按
    keep_screenshots: int = 300
    max_task_minutes: int = 20  # 单个任务的最长运行时间，防止死循环（任务可用 params.timeout_minutes 单独覆盖）
    allow_diamonds: bool = True   # 2026-11-10 用户规则开启；真正花在哪由 diamond_kinds 白名单决定
    # 2026-11-10 用户规则：「除了抽奖之外，钻石只用来买挑战次数，其余地方禁止使用钻石」。
    # 这条白名单是硬闸门 —— 不在里面的类别一律不花钻（may_spend 会拒）。
    #   attempt = 买挑战/挑战次数（公会试炼、角斗场「+」等）
    #   gacha   = 抽奖（召唤/十连）
    diamond_kinds: tuple = ("attempt", "gacha", "bounty_refresh")   # 2026-11-10 用户授权：悬赏刷新可以用钻石
    task_retries: int = 1       # 任务失败后自动重试次数（0=不重试）
    auto_recover: bool = True   # 任务失败后尝试回主城自愈，避免后续任务全挂
    # 2026-11-04：用户要求把「点击不准」量化——每次点击后抓帧校验点击点 ±120px
    # 区域是否真的有变化；无变化记为「空点」并按 ±8/±16px 重试。
    click_verify: bool = True
    click_verify_wait: float = 1.2
    click_retry: int = 2


@dataclass
class Limits:
    diamond_budget: int = 200   # 单次运行最多消耗的钻石
    # 2026-11-11：买次数类花费的地板——花完不能低于这个数，
    # 否则同一天后面的挑战次数就没钱买了
    diamond_reserve: int = 100
    gold_keep: int = 50000      # 保留的金币底线（金币强化类任务用）


@dataclass
class TaskConfig:
    enabled: bool = True
    priority: int = 100         # 数字越小越先跑
    params: dict = field(default_factory=dict)


DEFAULT_TASKS: dict[str, TaskConfig] = {
    # 战斗
    "tower": TaskConfig(True, 10, {"max_wins": 100, "max_lose": 10}),
    "legend": TaskConfig(True, 20, {"max_fights": 8}),
    "tree": TaskConfig(True, 30, {"max_stages": 12, "max_lose": 10, "star_fights": 3}),
    "demon": TaskConfig(True, 40, {"max_buff_picks": 40}),
    "dragon": TaskConfig(True, 41, {"max_fights": 6, "max_lose": 2, "buy_attempts": 2}),
    "faction": TaskConfig(True, 42, {"max_runs": 1}),
    "dungeon": TaskConfig(True, 79, {"max_push": 3, "sweeps": 6, "buy_sweeps": 6}),
    "soul": TaskConfig(True, 44, {"max_nodes": 10}),
    # 角斗场：必须排在 campaign(80) 之前 —— 主线会因为「角斗券已达上限」被挡住，
    # 先把券打掉，主线才走得动。（2026-11-09 按用户同意恢复竞技类，只恢复角斗场）
    "arena": TaskConfig(True, 45, {"max_fights": 10, "buy_attempts": 2}),
    # 荣耀竞技场：与角斗场同类（每天 10 次 PVP），排在角斗场之后、主线之前。
    "glory": TaskConfig(True, 46, {"max_fights": 10, "buy_attempts": 2}),
    "hall": TaskConfig(True, 47, {}),   # 荣耀殿堂每日点赞领奖（纯领取）
    # 先祖魂画：每天一次免费专武打造（不花钻）。
    "ancestor": TaskConfig(True, 16, {"free_only": True}),
        "tavern": TaskConfig(True, 17, {"buy_attempts": 2}),
        "guild_rank": TaskConfig(True, 48, {"max_fights": 3}),
    # 专武（专属武器）均匀升级：只花游戏内材料，材料不足时点「升级」只会弹物品浮层。
    "weapon": TaskConfig(True, 12, {"max_try": 3}),
        "tianshen": TaskConfig(True, 26, {}),
        "qianchou": TaskConfig(True, 28, {}),
    "goblin": TaskConfig(True, 82, {"max_occupy": 9, "layers": 10}),
    "guild_trial": TaskConfig(True, 78, {"times": 3, "buy_attempt": True, "buy_cost": 20}),
    "beast": TaskConfig(True, 81, {"times": 5}),
    "campaign": TaskConfig(True, 80, {"max_fights": 30}),
    # 奖励
    "mail": TaskConfig(True, 1, {}),
    "friend": TaskConfig(True, 3, {}),
    "welfare": TaskConfig(True, 4, {}),
    "claim": TaskConfig(True, 88, {}),
    "rank_board": TaskConfig(True, 6, {"max_rows": 5}),
    "bp": TaskConfig(True, 7, {}),
    "bounty": TaskConfig(True, 79, {"times": 8, "max_refreshes": 3, "sync_filter": False}),
    "merchant": TaskConfig(True, 15, {"min_bargain": 1100}),
    "idle": TaskConfig(True, 70, {"times": 3, "diamond_budget": 150}),
    "shop": TaskConfig(True, 76, {"times": 2}),
    "donate": TaskConfig(True, 77, {}),
    # 提升
    "relic": TaskConfig(True, 8, {}),
    "star": TaskConfig(True, 9, {}),
    "equipment": TaskConfig(True, 11, {}),
    # 助阵四个子系统拆开配置（2026-10-31 用户要求，方便单独调试）
    "glory_book": TaskConfig(True, 12, {}),
    "inherit": TaskConfig(True, 13, {"allow_advance": True}),   # 2026-11-10 用户要求：传承要真的往上提
    "artifact": TaskConfig(True, 14, {}),
    "pet": TaskConfig(True, 15, {}),
    "assist_mark": TaskConfig(True, 16, {"times": 10}),
    "collection": TaskConfig(True, 18, {}),
    "hero_bond": TaskConfig(True, 19, {}),
    "hero_level": TaskConfig(True, 17, {}),
    "forge": TaskConfig(True, 75, {"times": 1}),
}

# 预设：名字 -> 任务名列表（None 表示全部）
PROFILES: dict[str, list[str] | None] = {
    "all": None,
    "reward": ["mail", "friend", "welfare", "claim", "rank_board", "bp",
               "bounty", "merchant", "idle", "shop", "donate"],
    "upgrade": ["relic", "star", "equipment", "glory_book", "inherit", "artifact",
                "pet", "assist_mark", "collection", "hero_bond", "hero_level", "forge"],
    "combat": ["tower", "legend", "tree", "demon", "dragon", "faction", "dungeon", "soul",
               "goblin", "guild_trial", "beast", "campaign"],
    "daily": ["claim", "idle", "forge", "shop", "donate", "guild_trial", "beast", "goblin",
              "bounty", "campaign", "dungeon", "soul"],
    "full": ["mail", "friend", "welfare", "bp", "hero_level",
             "relic", "star", "equipment", "glory_book", "inherit", "artifact",
             "pet", "assist_mark", "collection", "hero_bond", "rank_board", "merchant",
             "claim", "idle", "forge", "shop", "donate", "guild_trial", "beast", "goblin",
             "bounty", "campaign", "tower", "legend", "tree", "demon", "dragon", "faction",
             "dungeon", "soul"],
}

# 每个任务的可配置项（GUI 自动渲染表单；OASX 风格的参数面板）
PARAM_SPECS: dict[str, dict[str, dict]] = {
    "tower": {
        "max_wins": {"type": "int", "label": "最多胜利层数", "default": 100, "min": 1, "max": 999},
        "max_lose": {"type": "int", "label": "连续失败停止", "default": 10, "min": 1, "max": 99},
    },
    "legend": {
        "max_fights": {"type": "int", "label": "挑战次数", "default": 8, "min": 1, "max": 20},
    },
    "tree": {
        "max_stages": {"type": "int", "label": "最多通关关数", "default": 12, "min": 1, "max": 100},
        "max_lose": {"type": "int", "label": "连续失败停止", "default": 10, "min": 1, "max": 99},
        "star_fights": {"type": "int", "label": "补星场次（0=不补）", "default": 3, "min": 0, "max": 20},
    },
    "demon": {
        "max_stages": {"type": "int", "label": "通关阶段上限", "default": 20, "min": 1, "max": 50},
    },
    "dungeon": {
        "max_push": {"type": "int", "label": "每个副本推进层数", "default": 3, "min": 0, "max": 20},
        "sweeps": {"type": "int", "label": "打输后免费扫荡次数", "default": 6, "min": 0, "max": 6},
    },
    "soul": {
        "max_nodes": {"type": "int", "label": "最多通关节点", "default": 10, "min": 1, "max": 20},
    },
    "goblin": {
        "max_occupy": {"type": "int", "label": "最多占领矿数", "default": 3, "min": 1, "max": 4},
        "layers": {"type": "int", "label": "统计层数", "default": 10, "min": 1, "max": 10},
    },
    "dragon": {
        "max_fights": {"type": "int", "label": "挑战场次上限", "default": 6, "min": 1, "max": 20},
        "max_lose": {"type": "int", "label": "连续失败停止", "default": 2, "min": 1, "max": 10},
    },
    "faction": {
        "max_runs": {"type": "int", "label": "每层闯关轮数", "default": 1, "min": 1, "max": 5},
    },
    "idle": {
        "times": {"type": "int", "label": "快速挂机次数", "default": 3, "min": 0, "max": 9},
        "diamond_budget": {"type": "int", "label": "本任务钻石预算", "default": 150, "min": 0, "max": 3000},
    },
    "forge": {
        "times": {"type": "int", "label": "强化次数", "default": 1, "min": 1, "max": 10},
    },
    "shop": {
        "times": {"type": "int", "label": "免费刷新次数", "default": 2, "min": 0, "max": 10},
    },
    "guild_trial": {
        "times": {"type": "int", "label": "挑战次数", "default": 3, "min": 1, "max": 6},
        "buy_attempt": {"type": "bool", "label": "次数用完买入一次", "default": True},
        "buy_cost": {"type": "int", "label": "购买单价（钻）", "default": 20, "min": 0, "max": 500},
    },
    "bounty": {
        "times": {"type": "int", "label": "最多接取数", "default": 8, "min": 1, "max": 8},
        "max_refreshes": {"type": "int", "label": "每天刷新次数（0=不刷，刷新花 30 钻）", "default": 0, "min": 0, "max": 5},
    },
    "merchant": {
        "min_bargain": {"type": "int", "label": "议价超过多少才买", "default": 1100, "min": 0, "max": 5000},
    },
    "rank_board": {
        "max_rows": {"type": "int", "label": "每个页签扫几行榜单", "default": 5, "min": 1, "max": 5},
    },
    "assist_mark": {
        "times": {"type": "int", "label": "助战徽记最多升级次数", "default": 10, "min": 1, "max": 50},
    },
    "artifact": {
        "star": {"type": "bool", "label": "顺带点神器升星", "default": True},
    },
    "beast": {
        "times": {"type": "int", "label": "圣兽挑战次数", "default": 5, "min": 1, "max": 5},
    },
    "campaign": {
        "max_fights": {"type": "int", "label": "主线挑战场次上限", "default": 30, "min": 1, "max": 100},
    },
    "arena": {
        "max_fights": {"type": "int", "label": "角斗场挑战场次上限", "default": 10, "min": 1, "max": 20},
        "buy_attempts": {"type": "int", "label": "券用完时最多买几次（钻石，仅买挑战次数）",
                         "default": 2, "min": 0, "max": 10},
    },
    "glory": {
        "max_fights": {"type": "int", "label": "荣耀竞技场挑战场次上限", "default": 10, "min": 1, "max": 10},
        "buy_attempts": {"type": "int", "label": "次数用完时最多买几次（钻石，仅买挑战次数）",
                         "default": 2, "min": 0, "max": 10},
    },
    "ancestor": {
        "free_only": {"type": "bool", "label": "只做免费打造（不花券/钻）", "default": True},
    },
}

# 全局可调项（GUI 顶部“选项”）
GLOBAL_SPECS: dict[str, dict] = {
    "diamond_budget": {"type": "int", "label": "全局钻石预算", "min": 0, "max": 10000},
    "max_task_minutes": {"type": "int", "label": "单任务超时（分钟）", "min": 1, "max": 240},
    "boot": {"type": "bool", "label": "启动前登录游戏"},
    "emulator": {"type": "bool", "label": "启动前拉起模拟器"},
    "cold": {"type": "bool", "label": "冷启动（杀进程重启）"},
}


@dataclass
class Config:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    emulator: EmulatorConfig = field(default_factory=EmulatorConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    limits: Limits = field(default_factory=Limits)
    tasks: dict[str, TaskConfig] = field(default_factory=lambda: dict(DEFAULT_TASKS))

    def task(self, name: str) -> TaskConfig:
        return self.tasks.get(name, TaskConfig())


def _merge(base: dict[str, TaskConfig], raw: dict) -> dict[str, TaskConfig]:
    merged = {k: TaskConfig(v.enabled, v.priority, dict(v.params)) for k, v in base.items()}
    for name, val in (raw or {}).items():
        if name not in merged:
            # 已删除的任务（rebate / resonance 等）即使旧 config.json 里还有，也不再复活
            continue
        cur = merged[name]
        if isinstance(val, bool):
            cur.enabled = val
        elif isinstance(val, dict):
            if "enabled" in val:
                cur.enabled = bool(val["enabled"])
            if "priority" in val:
                cur.priority = int(val["priority"])
            if "params" in val and isinstance(val["params"], dict):
                cur.params.update(val["params"])
        merged[name] = cur
    return merged


def load(path: str | Path | None = None) -> Config:
    """读配置；文件不存在时使用内置默认值。"""
    cfg = Config()
    p = Path(path) if path else DEFAULT_CONFIG
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        dev = data.get("device", {})
        for k in ("adb", "serial", "package", "activity"):
            if k in dev:
                setattr(cfg.device, k, dev[k])
        emu = data.get("emulator", {})
        for k in ("manager", "vm", "start"):
            if k in emu:
                setattr(cfg.emulator, k, emu[k])
        rt = data.get("runtime", {})
        for k in ("screenshot_dir", "state_file", "tap_ms", "keep_screenshots",
                  "max_task_minutes", "allow_diamonds", "diamond_kinds", "task_retries",
                  "auto_recover",
                  "click_verify", "click_verify_wait", "click_retry"):
            if k in rt:
                setattr(cfg.runtime, k, rt[k])
        lim = data.get("limits", {})
        for k in ("diamond_budget", "diamond_reserve", "gold_keep"):
            if k in lim:
                setattr(cfg.limits, k, lim[k])
        cfg.tasks = _merge(DEFAULT_TASKS, data.get("tasks", {}))
    return cfg


def dump_sample(path: str | Path | None = None) -> Path:
    """生成一份带注释含义的示例配置。"""
    p = Path(path) if path else DEFAULT_CONFIG
    cfg = Config()
    data = {
        "device": {
            "adb": cfg.device.adb,
            "serial": cfg.device.serial,
            "package": cfg.device.package,
            "activity": cfg.device.activity,
        },
        "emulator": {"manager": cfg.emulator.manager, "vm": cfg.emulator.vm, "start": True},
        "runtime": {
            "screenshot_dir": cfg.runtime.screenshot_dir,
            "state_file": cfg.runtime.state_file,
            "tap_ms": cfg.runtime.tap_ms,
            "keep_screenshots": cfg.runtime.keep_screenshots,
            "max_task_minutes": cfg.runtime.max_task_minutes,
            "allow_diamonds": cfg.runtime.allow_diamonds,
            "diamond_kinds": list(cfg.runtime.diamond_kinds),
            "task_retries": cfg.runtime.task_retries,
            "auto_recover": cfg.runtime.auto_recover,
            "click_verify": cfg.runtime.click_verify,
            "click_verify_wait": cfg.runtime.click_verify_wait,
            "click_retry": cfg.runtime.click_retry,
        },
        "limits": {"diamond_budget": cfg.limits.diamond_budget, "gold_keep": cfg.limits.gold_keep},
        "tasks": {
            name: {"enabled": t.enabled, "priority": t.priority, "params": t.params}
            for name, t in cfg.tasks.items()
        },
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
