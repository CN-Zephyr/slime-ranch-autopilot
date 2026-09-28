"""探索与抓捕（需求2）+ 售卖结晶（需求3）的决策帮助。

- explore: 选择未探索区域，抓捕新史莱姆，记录"新发现"供 brain 汇报。
- selling: 决定何时去集市售卖结晶、判断价格滑落风险。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict

# 示例地图区域与可能的史莱姆（可在配置里扩充）
AREAS = ["干燥采石场", "苔藓牧场", "盐湖", "古代遗迹", "玻璃沙漠"]
SLIMES = ["粉红史莱姆", "岩史莱姆", "闪电史莱姆", "苔藓史莱姆", "水晶史莱姆", "猎人史莱姆", "钻石史莱姆"]
FABLED_SLIMES = ["黄金史莱姆", "幸运史莱姆", "彩虹史莱姆"]

# 各类结晶的稳定价格（示例）
PLORT_PRICES = {
    "粉红结晶": 10, "岩结晶": 15, "闪电结晶": 20, "苔藓结晶": 16,
    "水晶结晶": 25, "猎人结晶": 30, "钻石结晶": 40, "黄金结晶": 300,
}


@dataclass
class ExploreState:
    explored_areas: List[str] = field(default_factory=list)
    caught_slimes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MarketState:
    """集市状态：帮助判断是否该卖。"""
    slop_penalty: float = 0.0   # 供大于求的压价因子（0~1）
    last_sold_plorts: int = 0

    def price_for(self, plort: str) -> int:
        base = PLORT_PRICES.get(plort, 10)
        return max(1, int(base * (1.0 - self.slop_penalty)))


def decide_explore_area(state: ExploreState) -> str:
    """挑一个还没去过的区域；如果都去过了就随机/轮流探索。"""
    for a in AREAS:
        if a not in state.explored_areas:
            return a
    # 返场：按序轮转
    return AREAS[len(state.explored_areas) % len(AREAS)]


def pick_new_slime(state: ExploreState):
    """从尚未抓捕过的史莱姆中随机挑一种。"""
    candidates = [s for s in SLIMES if s not in state.caught_slimes]
    if not candidates:
        return None
    return candidates[len(state.caught_slimes) * 7 % len(candidates)]