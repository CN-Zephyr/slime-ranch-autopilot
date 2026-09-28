"""模拟控制层（SIM）。在无游戏画面/无键鼠库的情况下复现同一套状态机，
用于验证四项自主游玩要求是否真的会按规则执行，并把动作写入 Comms 供观察。

SimController 实现与 LiveIOController 相同的 IOController 接口，
因此大脑状态机代码在 SIM/LIVE 两种模式下是同一套。
"""
from __future__ import annotations
import random
import copy
from typing import Dict, Any, List

from .game import IOController
from .ranch import RanchState, facility_cost
from .explore import AREAS, SLIMES, pick_new_slime, decide_explore_area, PLORT_PRICES


class SimController(IOController):
    def __init__(self, comms, start_funds: int = 800):
        self.comms = comms
        self.funds = start_funds
        self.ranch = RanchState()
        self.ranch.levels = {"corral": 0, "coop": 0, "garden": 0}  # 兼容指针
        self.facilities: Dict[str, int] = {"corral": 0, "coop": 0, "garden": 0}
        self.inventory: Dict[str, int] = {}  # plort -> count
        self.slimes: List[str] = []
        self.areas_explored: List[str] = []
        self.treasure_hits = 0
        random.seed(42)

    # ------------------------------------------------------------ 接口实现
    def enter_game(self) -> Dict[str, Any]:
        self.comms.say(f"【SIM】已进入史莱姆牧场存档，初始资金 ${self.funds}")
        return {"ok": True, "note": "进入存档"}

    def is_alive(self) -> bool:
        return True

    def read_money(self) -> int:
        return self.funds

    def build(self, kind: str) -> Dict[str, Any]:
        cur = self.facilities.get(kind, 0)
        if cur >= 3:
            return {"ok": False, "cost": 0, "note": f"{kind} 已满级"}
        cost = facility_cost(kind, cur + 1)
        if self.funds < cost:
            return {"ok": False, "cost": cost, "note": f"资金不足(需${cost})"}
        self.funds -= cost
        self.facilities[kind] = cur + 1
        self.comms.say(f"【SIM】建造/升级 {kind} -> Lv{cur+1}，花费 ${cost}，剩余 ${self.funds}")
        return {"ok": True, "facility": kind, "cost": cost, "level": cur + 1,
                "note": f"已建造 {kind} Lv{cur+1}"}

    def upgrade(self, kind: str) -> Dict[str, Any]:
        return self.build(kind)

    def feed(self) -> Dict[str, Any]:
        count = len(self.slimes)
        self.comms.say(f"【SIM】已向 {count} 只史莱姆投喂食物")
        return {"ok": True, "note": f"投喂 {count} 只"}

    def harvest(self) -> Dict[str, Any]:
        plorts = 0
        for slime in self.slimes:
            plort = slime.replace("史莱姆", "结晶")
            self.inventory[plort] = self.inventory.get(plort, 0) + 1
            plorts += 1
        # 牧场设施等级加成
        farm = self.facilities.get("garden", 0) + self.facilities.get("coop", 0) + self.facilities.get("corral", 0)
        bonus = max(0, farm // 2)
        prices = sum(PLORT_PRICES.get(p, 10) for p in self.inventory)
        self.comms.say(f"【SIM】收集结晶 {plorts} 枚(设施加成 {bonus})，包裹总价约 ${prices}")
        return {"ok": True, "count": plorts, "bonus": bonus, "note": f"收集 {plorts} 枚结晶"}

    def get_plorts(self) -> List[str]:
        return list(self.inventory.keys())

    def sell(self) -> Dict[str, Any]:
        total = 0
        for plort, count in list(self.inventory.items()):
            price = PLORT_PRICES.get(plort, 10)
            total += price * count
        if total == 0:
            return {"ok": False, "gains": 0, "plorts": [], "note": "没有结晶可卖"}
        self.funds += total
        sold = sum(self.inventory.values())
        self.comms.say(f"【SIM】在集市卖出 {sold} 枚结晶，收入 ${total}，现有资金 ${self.funds}")
        self.inventory.clear()
        return {"ok": True, "gains": total, "plorts": sold, "note": f"收入 ${total}"}

    def explore(self) -> Dict[str, Any]:
        area = decide_explore_area(SimStateHack(self.areas_explored))
        caught = pick_new_slime(SimStateHack(self.slimes))
        new_area = area not in self.areas_explored
        self.areas_explored.append(area)
        got_treasure = random.random() < 0.3
        if got_treasure:
            gain = random.choice([50, 100, 150])
            self.funds += gain
            self.treasure_hits += 1
            self.comms.say(f"【SIM】探索 {area}：拾取宝箱 +${gain}，资金 ${self.funds}")
        if caught:
            self.slimes.append(caught)
        self.comms.say(f"【SIM】探索 {area}：{'抓到新史莱姆 ' + caught if caught else '未发现新目标'}")
        return {"ok": True, "area": area, "new_area": new_area, "caught": caught or None,
                "from": area, "slime": caught or None}

    def go_home(self) -> Dict[str, Any]:
        return {"ok": True, "note": "返回牧场"}

    def describe(self) -> Dict[str, Any]:
        return {"mode": "sim", "funds": self.funds, "facilities": dict(self.facilities),
                "slimes": list(self.slimes), "inventory": dict(self.inventory)}


class SimStateHack:
    """最小 status 兼容对象，供 explore/ranch 决策函数读取."""

    def __init__(self, items: list):
        self.items = items

    @property
    def explored_areas(self):
        return self.items

    @property
    def caught_slimes(self):
        return self.items