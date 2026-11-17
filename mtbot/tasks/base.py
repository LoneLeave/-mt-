"""任务基类与上下文。任务只描述“目标”，导航交给 pages，判读交给 vision。"""
from __future__ import annotations

from dataclasses import dataclass, field

import re

from .. import layout as L
from .. import log, textocr
from ..config import Config, TaskConfig
from ..ui import UI


@dataclass
class TaskResult:
    ok: bool = True
    message: str = ""
    stats: dict = field(default_factory=dict)

    @classmethod
    def skip(cls, why: str, stats: dict | None = None) -> "TaskResult":
        return cls(True, f"跳过：{why}", dict(stats or {}))

    @classmethod
    def fail(cls, why: str, stats: dict | None = None) -> "TaskResult":
        # stats 可选：全库有多处写成 fail(msg, stats)，早期实现只收一个参数会在运行期抛
        # TypeError（2026-11-10 战令就这么「失败（异常: fail() takes 2 positional arguments）」）。
        return cls(False, why, dict(stats or {}))


@dataclass
class TaskContext:
    ui: UI
    cfg: Config
    dry_run: bool = False


class BaseTask:
    name: str = "base"
    title: str = "基础任务"
    category: str = "misc"

    def __init__(self, tcfg: TaskConfig):
        self.cfg = tcfg
        self.p = tcfg.params

    # 子类实现
    def run(self, ctx: TaskContext) -> TaskResult:  # pragma: no cover - 接口
        raise NotImplementedError

    # 工具
    @staticmethod
    def param(tcfg: TaskConfig, key: str, default):
        return tcfg.params.get(key, default)

    def ready(self, ctx: TaskContext) -> bool:
        """每个任务开始前保证在主城（页面对象自己也会保证）。"""
        return ctx.ui.ensure_main_city()

    # ---------- 读数 ----------
    @staticmethod
    def diamonds(im) -> "int | None":
        """顶栏钻石数（OCR）。读不到返回 None —— 绝不能把「读不到」当成 0。

        2026-11-09 假成功审计：快速挂机 / 公会试炼买次数 / 军衔晋升这些「花了钻或
        号称花了钻」的动作，必须拿前后两帧的钻石数做对比才允许计数。
        """
        if not textocr.available():
            return None
        # 2026-11-10 实测：read_text 在这个小框上会丢位（真值 970 返回 '9'），
        # 导致「990→9」被算成花了 981 钻。read_lines 同一帧给出 '970'（score 0.999），
        # 所以优先用 read_lines 挑纯数字 token，读不到才退回 read_text。
        try:
            lines = textocr.read_lines(im, L.CITY_DIAMOND_BOX, min_score=0.5)
        except Exception:            # noqa: BLE001
            lines = []
        best = None
        for text, _center, _bbox, score in lines:
            tok = text.replace(" ", "")
            if re.fullmatch(r"\d{1,7}", tok):
                if best is None or score > best[0]:
                    best = (score, int(tok))
        if best is not None:
            return best[1]
        try:
            txt = textocr.read_text(im, L.CITY_DIAMOND_BOX).replace(" ", "")
        except Exception:            # noqa: BLE001 - OCR 异常不该打断任务
            return None
        m = re.search(r"\d{1,7}", txt)
        return int(m.group(0)) if m else None

    def diamonds_stable(self, ui, tag: str, tries: int = 3) -> "int | None":
        """多帧读数：连续两帧读到同一个数才算数，否则返回 None（缺证）。

        2026-11-10：单帧 OCR 会把 970 读成 9，进而报出「花了 981 钻」这种假账。
        这里最多抓 tries 帧，只要相邻两次一致就采纳；都不一致就按「读数失败」处理，
        调用方会走「主城钻石前后对比缺证」分支而不是编一个数字出来。
        """
        prev = None
        for i in range(max(2, tries)):
            im = ui.screen(f"{tag}_{i}")
            val = self.diamonds(im)
            if val is not None and prev is not None and val == prev:
                return val
            prev = val
            ui.wait(0.5)
        return None

    # ---------- 资源保护 ----------
    def may_spend(self, ctx: TaskContext, what: str, cost: int | None = None,
                  kind: str = "other") -> bool:
        """花钻石的动作统一走这里：默认拒绝，需过两道闸。

        2026-11-03 用户反馈“BP/日常任务在乱花钻石”，所以任何会被游戏扣钻的按钮
        都必须先过这道闸；cost 已知时同时校验预算。
        2026-11-10 用户新规则「除了抽奖之外，钻石只用来买挑战次数，其余地方禁止使用钻石」：
        kind 必须是 runtime.diamond_kinds 白名单里的类别（默认 attempt / gacha），
        其它（加速、刷新、付费扫荡、商店…）直接拒绝。
        """
        kinds = tuple(getattr(ctx.cfg.runtime, "diamond_kinds", ("attempt", "gacha")))
        if kind not in kinds:
            log.info(f"  不花钻石：{what}（类别 {kind}，用户规则只允许 {'/'.join(kinds)}）")
            return False
        if not ctx.cfg.runtime.allow_diamonds:
            log.warn(f"  跳过付费操作：{what}"
                     f"（{'钻石 ' + str(cost) if cost else '会消耗钻石'}）；"
                     f"runtime.allow_diamonds=false")
            return False
        budget = int(self.p.get("diamond_budget", ctx.cfg.limits.diamond_budget))
        if cost is not None and cost > budget:
            log.warn(f"  跳过付费操作：{what}（需要 {cost} 钻，超出预算 {budget}）")
            return False
        log.info(f"  允许花钻（类别 {kind}）：{what}"
                 f"（{'钻石 ' + str(cost) if cost else '会消耗钻石'}，"
                 f"allow_diamonds=true，预算 {budget}）")
        return True
