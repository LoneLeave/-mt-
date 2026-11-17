"""页面标题识别：每个玩法页顶部左侧都有专属标题条，用它做页面锚点。

2026-10-30：逆向导出的美术里标题是文字渲染（NewArtFont 只有战斗数字位图字体），
没有单独的标题贴图，所以模板统一取自 720×1280 真机截图 1:1 裁切
（E:/DailyIdea/游戏脚本框架/assets 的 标题_*.png + E:/Reverse/tools 的截图复核）。

阈值 0.90 是必须的：「周常任务」会被「日常任务」模板以 0.857 误命中。
只扫顶部 (0,0,340,95) 区域，避免页面中间的同名文字/卡片标题干扰。
"""
from __future__ import annotations

from PIL import Image

from . import template as T

ROI = (0, 0, 340, 95)
THRESHOLD = 0.90

# key -> 模板文件名（templates/ 下）
TITLES = {
    "tower": "标题_守护者之塔.png",
    "legend": "标题_传奇试炼.png",
    "tree": "标题_时光之树.png",
    "demon": "标题_邪能神殿.png",
    "dragon": "标题_巨龙牢窟.png",
    "faction": "标题_阵营挑战.png",
    "goblin": "标题_地精宝藏.png",
    "guild_trial": "标题_公会试炼.png",
    "beast": "标题_公会圣兽.png",
    "daily": "标题_日常任务.png",
    "weekly": "标题_周常任务.png",       # 2026-11-04 实测裁切，和周常页交叉误配最高 0.877
    "achieve": "标题_成就任务.png",
    "growth": "标题_历练任务.png",
    "dusk": "标题_暮光要塞.png",          # 还没做任务，先备着
    "soul": "标题_罪魂之域.png",          # 罪魂之域（2026-10-30 新副本）
    "glory_book": "标题_荣耀之书.png",
    "inherit": "标题_天神传承.png",
    "artifact": "标题_神器.png",
    "rank_board": "标题_排行榜.png",
    "merchant": "标题_公会商人.png",
    "hero_star": "标题_英雄升星.png",   # 主城「升星」页（2026-10-30 加，防止被 battle 误判）
    "collection": "标题_图鉴.png",        # 英雄页「图鉴」子页（2026-10-31）
    "hero_bond": "标题_英雄羁绊.png",    # 英雄页「羁绊」子页（2026-10-31）
    "hero_plan": "标题_勇者计划.png",    # 勇者计划（战令），2026-11-04 接入
}

# 有模板但暂未接入任务的
UNUSED = {
    "bounty": "标题_悬赏任务.png",
}


def identify(im: Image.Image, threshold: float = THRESHOLD) -> str | None:
    """返回当前页面标题对应的 key；认不出返回 None。"""
    for key, tpl in TITLES.items():
        if T.VI.find(im, tpl, threshold, roi=ROI):
            return key
    return None


def on_page(im: Image.Image, key: str, threshold: float = THRESHOLD) -> bool:
    tpl = TITLES.get(key)
    if not tpl:
        return False
    return T.VI.find(im, tpl, threshold, roi=ROI) is not None
