# -*- coding: utf-8 -*-
"""一次性诊断：手动驱动角色走向结晶市场站位点。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.settings import Settings
from core.bridge import BridgeIOController
from core.real import WalkCaptureIO

DATA = os.path.join(os.environ.get("TEMP", "."), "neko-slime-ranch-autopilot", "runtime")
s = Settings.load(DATA, os.path.join(DATA, "config.json"))
bridge = BridgeIOController(
    host=getattr(s, "bridge_host", "127.0.0.1"),
    port=getattr(s, "bridge_port", 8124),
    fallback_funds=getattr(s, "live_fallback_funds", -1),
    game_exe="", auto_launch=False,
)
walk = WalkCaptureIO(bridge)
walk._ensure_ready()
walk._lock_mouse()
time.sleep(0.5)

for i in range(14):
    m = bridge.scan_market()
    if not m.get("ok"):
        print(f"[{i}] SCAN FAIL: {m.get('note')}", flush=True)
        break
    d = float(m.get("dist", 1e9))
    yaw = float(m.get("yaw", 0.0))
    px = float(m.get("px", 0.0))
    pz = float(m.get("py", 0.0))
    print(f"[{i}] d={d:6.1f}m yaw={yaw:+7.1f} pos=({px:.1f},{pz:.1f})", flush=True)
    if d <= 5.0:
        print("REACHED", flush=True)
        break
    ok = walk._turn_toward(m, rescanner=bridge.scan_market)
    print(f"    turn_ok={ok}", flush=True)
    if not ok:
        print("TURN FAILED", flush=True)
        break
    win = walk._load()
    before = walk._capture_frame()
    if d > 60:
        hold, keys = 2.2, ["w", "shift"]
    elif d > 15:
        hold, keys = 1.4, ["w", "shift"]
    else:
        hold, keys = 0.8, ["w"]
    try:
        if len(keys) > 1:
            win.keys_hold(keys, hold)
        else:
            win.key_hold(keys[0], hold)
    except Exception as e:
        print(f"    HOLD FAIL: {e}", flush=True)
        break
    time.sleep(0.15)
    after = walk._capture_frame()
    v = walk._vload()
    mv = None
    if v is not None and v is not False and after is not None and before is not None:
        mv = v.movement_fraction(before, after)
    print(f"    hold={hold}s keys={keys} mv={mv}", flush=True)
    if mv is not None and mv < 0.02:
        print("    STUCK -> 转 90° 测试侧向移动", flush=True)
        try:
            win.mouse_move_rel(420, 0)
            time.sleep(0.3)
            win.key_hold("w", 1.2)
            time.sleep(0.2)
            win.mouse_move_rel(-420, 0)
            time.sleep(0.3)
        except Exception:
            pass
    time.sleep(0.2)

print("DONE", flush=True)
