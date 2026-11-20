"""任务注册表：名字 -> 类。调度器与 CLI 只认名字。

2026-10-30 起按用户要求只保留三类：战斗（combat）/ 奖励（reward）/ 提升（upgrade）。
竞技相关（角斗场、荣耀竞技场、争霸赛）2026-10-30 整体删除；
2026-11-09 按用户同意恢复「角斗场」（只打角斗券，解主线「角斗券满仓」的死结）。
"""
from __future__ import annotations

from .base import BaseTask, TaskContext, TaskResult
from .assist import (ArtifactTask, AssistMarkTask, GloryBookTask, InheritTask,
                     PetTask)
from .ancestor import AncestorTask
from .tavern import TavernTask
from .weapon import WeaponTask
from .tianshen import TianshenTask
from .qianchou import QianchouTask
from .guild_rank import GuildRankTask
from .arena import ArenaTask
from .glory import GloryTask
from .hall import HallLikeTask
from .combat import DemonTask, LegendTask, TowerTask, TreeTask
from .daily import (BountyTask, CampaignTask, ClaimDailyTask,
                    ForgeEnhanceTask, GuildBeastTask, GuildDonateTask,
                    GuildTrialTask, QuickIdleTask, ShopRefreshTask)
from .dungeon import DungeonTask
from .events import DragonTask, FactionTask
from .goblin import GoblinTask
from .heroes import CollectionTask, HeroBondTask
from .merchant import MerchantTask
from .rankboard import RankBoardTask
from .reward import (BattlePassTask, EquipmentTask, FriendTask,
                     HeroLevelTask, MailTask, RelicTask, StarUpTask,
                     WelfareTask)
from .soul import SoulTask

TASK_CLASSES: dict[str, type[BaseTask]] = {
    t.name: t for t in (
        # 战斗
        AncestorTask,
    TavernTask,
    WeaponTask, TianshenTask, QianchouTask,
    GuildRankTask,
    ArenaTask,
    GloryTask,
    HallLikeTask,
        TowerTask, LegendTask, TreeTask, DemonTask, DragonTask, FactionTask,
        DungeonTask, SoulTask, GoblinTask, GuildTrialTask, GuildBeastTask, CampaignTask,
        # 奖励
        MailTask, FriendTask, WelfareTask, BattlePassTask, ClaimDailyTask,
        RankBoardTask, BountyTask, MerchantTask, QuickIdleTask, ShopRefreshTask,
        GuildDonateTask,
        # 提升（助阵四个子系统 + 英雄页助战徽记各自独立，方便单独调试）
        RelicTask, StarUpTask, EquipmentTask,
        GloryBookTask, InheritTask, ArtifactTask, PetTask, AssistMarkTask,
        CollectionTask, HeroBondTask,
        HeroLevelTask, ForgeEnhanceTask,
    )
}


def names() -> list[str]:
    return list(TASK_CLASSES)


def make(name: str, cfg) -> BaseTask:
    cls = TASK_CLASSES[name]
    return cls(cfg.task(name))


__all__ = ["TASK_CLASSES", "BaseTask", "TaskContext", "TaskResult", "names", "make"]
