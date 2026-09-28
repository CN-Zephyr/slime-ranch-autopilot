"""牧场经营决策（需求1）：建造/升级 牧场(围栏)、鸡圈、菜园。

核心规则：资金(funds) > 升级费用(cost) 的 2 倍 时才升级。
设施优先级：先有围栏，再鸡圈，再菜园；逐步升满。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List

FACILITY_ORDER = ["corral", "coop", "garden"]
FACILITY_NAMES = {"corral": "牧场/围栏", "coop": "鸡圈", "garden": "菜园"}

# 每个设施 0 级(未建) -> max 级 的建造/升级费用（与游戏真实价格一致）：
#   corral 建 225；coop 建 400；garden 建 300（升级取该设施常见升级的基准价）
BASE_COSTS = {
    "corral": [225, 350, 350],   # 建围栏225，升1级350，升2级350
    "coop":   [400, 650, 650],
    "garden": [300, 500, 500],
}
MAX_LEVEL = 3  # level 0 = 未建；建后 level=1；max 级 = MAX_LEVEL


@dataclass
class RanchState:
    """牧场建设进度知识。"""
    level: Dict[str, int] = field(default_factory=lambda: {"corral": 0, "coop": 0, "garden": 0})
    known_slimes: List[str] = field(default_factory=list)
    known_areas: List[str] = field(default_factory=list)
    built_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


def facility_cost(kind: str, next_level: int) -> int:
    """返回从 next_level-1 升级到 next_level 的费用。next_level=1 表示首次建造。"""
    table = BASE_COSTS.get(kind, [100, 300, 700])
    idx = next_level - 1
    if 0 <= idx < len(table):
        return table[idx]
    return 999999  # 已满级


def next_planned(kind: str, state: RanchState) -> dict:
    """返回下一个要建的设施及费用/等级。"""
    current = state.level.get(kind, 0)
    if current >= MAX_LEVEL:
        return {"kind": kind, "next_level": None, "cost": None, "building": False}
    return {"kind": kind, "next_level": current + 1, "cost": facility_cost(kind, current + 1), "building": True}


def decide_build_action(state: RanchState, funds: int) -> dict | None:
    """根据资金与已有设施，决策优先建/升级哪个。满足 资金 >= 2*cost 才行动。"""
    # 1) 未建的按优先级先建齐
    for kind in FACILITY_ORDER:
        if state.level.get(kind, 0) == 0:
            cost = facility_cost(kind, 1)
            if funds >= 2 * cost:
                return {"mode": "build", "kind": kind, "cost": cost}
            return None  # 钱不够就等——不占用别的资源
    # 2) 都已建，则按优先级升级
    for kind in FACILITY_ORDER:
        cur = state.level.get(kind, 0)
        if cur < MAX_LEVEL:
            cost = facility_cost(kind, cur + 1)
            if funds >= 2 * cost:
                return {"mode": "upgrade", "kind": kind, "cost": cost}
    return None  # 全满或钱不够


def record_built(state: RanchState, kind: str) -> None:
    if kind in state.built_flags:
        return
    state.built_flags.append(kind)
    state.built_flags = state.built_flags[-12:]