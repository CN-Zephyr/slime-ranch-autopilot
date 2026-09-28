#!/usr/bin/env python3
"""端到端验证：真实走到结晶市场并投出背包结晶卖钱。

验证链路 = mod 感知(scan_market 站位/投入口) -> 真实键鼠(转向/走路/蓄力投掷)
         -> 卖前/卖后 mod 真实资金对比。
"""
from __future__ import annotations
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core.bridge import BridgeIOController  # noqa: E402
from core.real import WalkCaptureIO  # noqa: E402

bridge = BridgeIOController(host="127.0.0.1", port=8124, fallback_funds=-1)
walk = WalkCaptureIO(bridge)

st = bridge._get_status()
print(f"[状态] game_loaded={st.get('game_loaded')} area={st.get('area')} "
      f"money={bridge.read_money()} plorts={st.get('plorts')}", flush=True)
if not st.get("game_loaded"):
    print("未进入存档，退出", flush=True)
    sys.exit(1)

m = bridge.scan_market()
print(f"[scan_market] ok={m.get('ok')} dist={m.get('dist'):.1f}m "
      f"yaw={m.get('yaw'):+.1f}° cyaw={m.get('cyaw'):+.1f}° area={m.get('area')}", flush=True)
if not m.get("ok"):
    print("市场不可达，退出", flush=True)
    sys.exit(1)

before = bridge.read_money()
print(f"[卖前] 资金 ${before}", flush=True)

res = walk.sell_plorts(throws=8)
print(f"[sell_plorts] ok={res.get('ok')} gains={res.get('gains')} note={res.get('note')}", flush=True)

after = bridge.read_money()
print(f"[卖后] 资金 ${after}  实际入账 ${max(0, after - before)}", flush=True)
