"""混合模式执行器（hybrid backend）：真实键鼠操作 + 画面验证。

感知仍由 SlimeBridge mod 提供（资金/设施/坐标/目标 yaw 偏差都很准），本模块只负责把
mod 的"目标感知"（scan_target 返回的 yaw_delta / dist）翻译成**真实游戏输入**：
  - 用鼠标移动真实转动视角，直到对准目标（mod 的 yaw 实时反馈收敛）；
  - 按 W 真实向前走，直到距离进入真空枪射程；
  - 按住鼠标左键真实吸附目标。

这样人物的移动、转向、动作都是真实在画面上发生的（不再是瞬移魔法），物品栏/真空包
计数会随真实抓捕变化，汇报与画面一致。

winio 依赖惰性加载，避免进 sim 模式时拖垮环境。
"""
from __future__ import annotations

import time
from typing import Dict, Any

# 转向收敛阈值：目标已基本居中
YAW_TOLERANCE = 5.0
# 真空枪实用吸附射程（米）：距离小于它就开始按左键吸
VACUUM_RANGE = 5.0


class WalkCaptureIO:
    def __init__(self, bridge, window_exe: str = "SlimeRancher.exe"):
        self.io = bridge          # BridgeIOController（负责感知：scan_target / read_money 等）
        self.window_exe = window_exe
        self._win = None
        self._vision = None
        self._hwnd = None

    # ---------------- 依赖与窗口 ----------------
    def _load(self):
        if self._win is None or self._win is False:
            try:
                from . import winio  # type: ignore
                self._win = winio
            except Exception:
                self._win = False
        return self._win

    def _vload(self):
        """惰性加载视觉层(vision.py)，提供帧对比/区域裁剪。"""
        if self._vision is None or self._vision is False:
            try:
                from . import vision  # type: ignore
                self._vision = vision
            except Exception:
                self._vision = False
        return self._vision

    def _capture_frame(self):
        """抓当前游戏画面，供 NEKO 用眼睛确认真实动作。失败返回 None。"""
        win = self._load()
        if win is None or win is False or not self._hwnd:
            return None
        try:
            return win.capture_window(self._hwnd)
        except Exception:
            return None

    def _ensure_ready(self) -> bool:
        win = self._load()
        if win is None or win is False:
            return False
        try:
            self._hwnd = win.find_game_window(self.window_exe)
        except Exception:
            self._hwnd = None
        if not self._hwnd:
            return False
        try:
            win.ensure_foreground(self._hwnd)
        except Exception:
            pass
        return True

    def _lock_mouse(self) -> None:
        """把光标放回窗口中心并单击一次，让第三人称视角进入"鼠标锁定/准星"状态，
        之后相对移动鼠标即可真实转动视角（光标被锁在中央不会跑丢）。"""
        win = self._win
        try:
            win.ensure_foreground(self._hwnd)          # 每次按键/鼠标前再次抢前台
        except Exception:
            pass
        c = self._center()
        if not c:
            return
        try:
            win.mouse_move_to(c[0], c[1])
            time.sleep(0.05)
            win.mouse_click(c[0], c[1])   # 单击锁定视角（游戏会把光标归中并进入准星态）
            time.sleep(0.1)
        except Exception:
            pass

    def _center(self):
        """返回窗口屏幕中心绝对坐标 (x, y)。取不到则 None。"""
        win = self._load()
        try:
            rect = win.get_window_rect(self._hwnd)
        except Exception:
            rect = None
        if rect is None:
            return None
        x, y, w, h = rect
        return int(x + w / 2), int(y + h / 2)

    # ---------------- 真实操作 ----------------
    def _turn_toward(self, target: Dict[str, Any], max_steps: int = 18,
                     rescanner=None) -> bool:
        """真实转动视角对准目标。用两段式步长 + 短反馈周期，抑制史莱姆跳动导致过冲：
        - 大偏差粗调(大步)，小偏差/中偏差精调(小步)，避免一次转太多。
        - 相对移动只产生像素增量，光标始终锁在中央，可持续小幅修正。
        - rescanner 可选：每步重扫目标的反馈源。默认扫史莱姆/结晶(scan_target)；
          走向市场/围栏时必须传对应 rescanner，否则中途会改成去追史莱姆。
        """
        win = self._load()
        if win is None or win is False:
            return False
        re_scan = rescanner or self.io.scan_target
        for _ in range(max_steps):
            yaw = float(target.get("yaw", 0.0))
            if abs(yaw) < YAW_TOLERANCE:
                return True
            if abs(yaw) > 30:
                step = 300          # 粗调：大偏差大步
            elif abs(yaw) > 12:
                step = 120          # 中调
            else:
                step = 50           # 精调：小步趋近，避免过冲
            dx = int(step) if yaw > 0 else int(-step)   # yaw<0 时左移使 yaw 回升到 0
            try:
                win.mouse_move_rel(dx, 0)               # 相对移动真实转视角
            except Exception:
                return False
            time.sleep(0.28)                            # 短反馈，及时跟目标移动
            target = re_scan()
            if not target.get("ok"):
                return False
        return abs(float(target.get("yaw", 0.0))) < (YAW_TOLERANCE + 6.0)

    def _walk_to_point(self, target_dist: float, max_steps: int, rescanner,
                       stall_limit: int = 3, final_dist: float | None = None) -> Dict[str, Any]:
        """按 W 真实走向 rescanner() 报告的目标，直到进入 target_dist 米。

        距离自适应：>60m 按住 W+Shift 2.2s(≈20m)，15-60m 按住 W+Shift 1.4s(≈12m)，
        <15m 按住 W 0.8s(≈3-4m，慢速防过冲)。每步先用 yaw 反馈对准方向，再真实前进，
        并用**眼睛(帧对比)确认人物真的在动**：连走几步画面纹丝不动(失焦/被墙挡/输入
        没生效)就提前放弃，避免空口汇报"已走到"。stall_limit 控制连续"没动"几次才放弃
        （投放围栏这类近处小目标可调大，避免误判被墙挡）。

        两点改进：
        1) 距离感知优先：只要 rescanner 报的距离确实在缩短（说明在往前走），即使单步
           画面变化小也不算"卡住"——避免对着大建筑缓慢接近时误判失焦；
        2) final_dist 放宽到达：步数耗尽或判定被堵时，若实际距离已 <= final_dist 仍算
           "已到达"（市场/围栏这类大建筑：站在外圈就能投，不必贴到中心）。

        返回 {"ok", "moved"}：moved=True 表示画面检测到真实位移。
        """
        win = self._load()
        vision = self._vload()
        if win is None or win is False:
            return {"ok": False, "moved": False}
        accept_dist = final_dist if final_dist is not None else (target_dist + 1.5)
        stalls = 0
        detours = 0
        last_d = None
        for _ in range(max_steps):
            t = rescanner()
            if not t.get("ok"):
                return {"ok": False, "moved": False}
            d = float(t.get("dist", 1e9))
            if d <= target_dist:
                return {"ok": True, "moved": True}
            if not self._turn_toward(t, rescanner=rescanner):   # 先对准再走，避免白走
                return {"ok": False, "moved": False}
            improved = last_d is not None and d < last_d - 0.4   # 距离确在缩短 = 在往前走
            last_d = d
            before = self._capture_frame()
            if d > 60:
                hold, keys = 2.2, ["w", "shift"]        # 远距离：跑步，大步长
            elif d > 15:
                hold, keys = 1.4, ["w", "shift"]
            else:
                hold, keys = 0.8, ["w"]                 # 近距离：慢走，避免冲过头
            try:
                if len(keys) > 1:
                    win.keys_hold(keys, hold)
                else:
                    win.key_hold(keys[0], hold)
            except Exception:
                return {"ok": False, "moved": False}
            time.sleep(0.15)
            # 眼睛：画面没变 且 距离也没缩短 才算卡住（失焦/被墙挡）-> 先重抢焦点再试
            if before is not None and vision is not None and vision is not False:
                after = self._capture_frame()
                mv = vision.movement_fraction(before, after)
                if mv is not None and mv < 0.012 and not improved:
                    stalls += 1
                    if stalls >= 2:
                        # 连续卡住 = 大概率被墙/围栏挡住：保持面向目标，A/D 侧移绕行 1.3s
                        stalls = 0
                        side = "a" if (detours % 2 == 0) else "d"
                        detours += 1
                        try:
                            win.key_hold(side, 1.3)
                        except Exception:
                            return {"ok": False, "moved": False}
                        if detours >= 5:
                            t2 = rescanner()            # 绕了多圈仍被堵：放弃前最后确认够近
                            if t2.get("ok") and float(t2.get("dist", 1e9)) <= accept_dist:
                                return {"ok": True, "moved": True}
                            return {"ok": False, "moved": False}
                    else:
                        self._lock_mouse()              # 第一次疑似卡住：先重锁焦点再走
        t = rescanner()
        got = t.get("ok") and float(t.get("dist", 1e9)) <= accept_dist
        return {"ok": got, "moved": True}

    def _walk_toward(self, max_steps: int = 30) -> Dict[str, Any]:
        """真实走向最近抓捕目标(史莱姆/结晶)，直到进入真空枪射程。"""
        return self._walk_to_point(VACUUM_RANGE, max_steps, self.io.scan_target)

    def _vacuum(self, seconds: float = 1.1) -> Dict[str, Any]:
        """对准目标后，按住鼠标左键真实吸附。

        返回 {"ok", "visual"}：visual=True 表示画面检测到物品栏/画面发生变化，
        说明真的吸到了东西（这就是你要的"物品栏的变化"验证）。
        """
        win = self._load()
        vision = self._vload()
        if win is None or win is False:
            return {"ok": False, "visual": False}
        c = self._center()
        if not c:
            return {"ok": False, "visual": False}
        before = self._capture_frame()
        try:
            win.mouse_hold(c[0], c[1], seconds)         # 对准中心按左键吸
        except Exception:
            return {"ok": False, "visual": False}
        time.sleep(0.25)
        visual = False
        if before is not None and vision is not None and vision is not False:
            after = self._capture_frame()
            if after is not None:
                hud_chg = vision.frame_diff(before, after, region=vision.HUD_REGION)
                whole_chg = vision.frame_diff(before, after)
                visual = hud_chg > 0.02 or whole_chg > 0.03
        return {"ok": True, "visual": visual}

    # ---------------- 对外动作 ----------------
    def capture_target(self, vacuum_seconds: float = 1.1) -> Dict[str, Any]:
        """混合模式抓捕一步：感知目标 -> 真实转向 -> 真实走近 -> 左键吸。

        返回 {"ok", "kind", "note", "remaining"}: remaining=吸完后目标是否还在射程
        （吸收未吐出的史莱姆降低 remaining，提示可继续）。纯真实输入，无可瞬移副作用。
        """
        if not self._ensure_ready():
            return {"ok": False, "kind": "", "note": "未找到游戏窗口，无法真实操作"}
        self._lock_mouse()                              # 锁定一次进入准星态，后续相对移动转视角
        t = self.io.scan_target()
        if not t.get("ok"):
            return {"ok": False, "kind": "", "note": t.get("note", "附近无可抓捕目标")}
        kind = t.get("kind", "")
        if not self._turn_toward(t):
            return {"ok": False, "kind": kind, "note": "转向对准目标失败（未对准）"}
        wres = self._walk_toward()
        if not wres.get("ok"):
            return {"ok": False, "kind": kind,
                    "note": "未能靠近目标至吸程内（画面检测疑似失焦/被堵，已尝试重锁）"}
        vres = self._vacuum(vacuum_seconds)
        # 吸入后看目标是否仍在（判定为"吸附到东西 / 击退目标"）
        after = self.io.scan_target()
        remaining = bool(after.get("ok"))
        label = "史莱姆" if kind == "slime" else "结晶"
        if vres.get("visual"):
            note = "已真实走向并吸附 %s（画面确认生效：物品栏/画面有变化）" % label
        else:
            note = "已走向%s并按住左键，但画面未见明显变化（可能被挡/已吸到但未刷新，下一轮会核实）" % label
        if remaining and kind == "slime":
            note += "（目标仍在附近，可继续抓捕）"
        return {"ok": True, "kind": kind, "note": note, "remaining": remaining,
                "dist": float(after.get("dist", t.get("dist", 0))),
                "visual": vres.get("visual", False)}

    def deposit_to_corral(self, max_steps: int = 30) -> Dict[str, Any]:
        """把真空背包里的史莱姆真实走到最近围栏并投放（快速左键投出）。

        感知仍走 mod（scan_corral 给最近围栏的方向/距离），执行全真实：走到围栏 4m 内
        -> 对准 -> 轻按左键把背包当前物品投出（画面中史莱姆应落进围栏）。
        返回 {"ok", "note"}。
        """
        win = self._load()
        if win is None or win is False or not self._ensure_ready():
            return {"ok": False, "note": "未找到游戏窗口"}
        self._lock_mouse()
        c = self.io.scan_corral()
        if not c.get("ok"):
            return {"ok": False, "note": c.get("note", "场景中没有围栏，无法投放")}
        # 走到围栏 6m 内（围栏平台本身约 4m 宽，6m 已算"贴着围栏"；stall 容忍放大避免误判被堵）
        wres = self._walk_to_point(6.0, max_steps, self.io.scan_corral, stall_limit=5)
        if not wres.get("ok"):
            return {"ok": False, "note": "未能走到围栏旁（画面检测疑似失焦/被堵）"}
        if not self._turn_toward(self.io.scan_corral()):
            return {"ok": False, "note": "未能对准围栏"}
        try:
            win.mouse_move_rel(0, 25)                   # 略微向下看，让投出物落进围栏
            time.sleep(0.1)
            c2 = self._center()
            if not c2:
                return {"ok": False, "note": "取不到窗口中心"}
            win.mouse_click(c2[0], c2[1])               # 快速左键 = 投出真空背包当前物品
        except Exception:
            return {"ok": False, "note": "投放点击失败"}
        return {"ok": True, "note": "已走到围栏旁并投出真空背包物品（史莱姆应已进入围栏）"}

    def sell_plorts(self, throws: int = 8) -> Dict[str, Any]:
        """真实售卖结晶：真实走到结晶市场建筑前，对准投入口，连续左键投出背包结晶。

        Slime Rancher 的真实售卖机制：把真空背包里的结晶投进结晶市场投入口，结晶立刻
        换成钱（无需开面板）。收益验证走 mod 真实资金（卖前/卖后 read_money 对比），
        画面中人物真实走到市场、结晶真实飞进出（这才是"看到钱从画面里来"）。
        返回 {"ok", "gains", "note"}。
        """
        win = self._load()
        if win is None or win is False or not self._ensure_ready():
            return {"ok": False, "gains": 0, "note": "未找到游戏窗口"}
        self._lock_mouse()
        m = self.io.scan_market()
        if not m.get("ok"):
            return {"ok": False, "gains": 0, "note": m.get("note", "场景中找不到结晶市场")}
        # 市场在牧场，玩家若在野外直线走回会被牧场围墙挡住，故仅当已在牧场时才真实走去卖
        if m.get("area") != "牧场":
            return {"ok": False, "gains": 0, "note": f"玩家当前在{m.get('area','未知区域')}，暂不穿越围墙去市场，待回到牧场再卖"}
        # 走向目标 = 投入口正面站位点（mod 的 scan_market 已把 dist/yaw 指向站位点），
        # 站到 4m 内即对准投入口；堵在路上会自动 A/D 侧移绕行。
        wres = self._walk_to_point(4.0, 40, self.io.scan_market, stall_limit=6, final_dist=10.0)
        if not wres.get("ok"):
            # 兜底：当前起点可能被卡（贴围墙/建筑/地形缝隙），先传送回牧场房子
            # （开阔区，实测从房子到市场可正常直线走到）再走一次。
            try:
                self.io.go_home()
                time.sleep(1.5)
            except Exception:
                pass
            m2 = self.io.scan_market()
            if m2.get("ok") and m2.get("area") == "牧场":
                wres = self._walk_to_point(4.0, 30, self.io.scan_market,
                                           stall_limit=6, final_dist=10.0)
        if not wres.get("ok"):
            t = self.io.scan_market()
            dnote = f"（距投入口站位 {float(t.get('dist', 0)):.0f}m）" if t.get("ok") else ""
            return {"ok": False, "gains": 0,
                    "note": f"未能走到结晶市场投入口前{dnote}，本轮暂不售卖"}

        def scan_port():
            """重扫市场并转成"对准投入口开孔"的目标，供最终投掷转向反馈。"""
            mm = self.io.scan_market()
            if mm.get("ok"):
                mm["yaw"] = mm.get("cyaw", 0.0)
            return mm

        if not self._turn_toward(scan_port(), rescanner=scan_port):
            return {"ok": False, "gains": 0, "note": "未能对准结晶市场投入口"}
        try:
            before = int(self.io.read_money())
        except Exception:
            before = -1
        c = self._center()
        if not c:
            return {"ok": False, "gains": 0, "note": "取不到窗口中心"}
        try:
            # 投入口是建筑上方抬高开孔：对准后上抬视角(约 25px)再投；用蓄力投掷
            # （按住左键约 0.45s 再松开）让结晶划出弧线飞进开孔，比点射命中率高。
            win.mouse_move_rel(0, -25)
            time.sleep(0.15)
            for _ in range(throws):
                win.mouse_hold(c[0], c[1], 0.45)    # 蓄力投出背包结晶
                time.sleep(0.35)
            time.sleep(2.0)                     # 等结晶飞入市场入账
        except Exception:
            return {"ok": False, "gains": 0, "note": "投出点击失败"}
        try:
            after = int(self.io.read_money())
        except Exception:
            after = -1
        gains = max(0, after - before) if before >= 0 and after >= 0 else 0
        if gains > 0:
            return {"ok": True, "gains": gains,
                    "note": f"已真实在结晶市场卖出背包结晶，收入 ${gains}，当前资金 ${after}"}
        return {"ok": True, "gains": 0,
                "note": "已走向结晶市场并投出背包结晶（本轮无入账：背包可能为空或未命中投入口）"}

    def wander_step(self, seconds: float = 1.5) -> Dict[str, Any]:
        """无目标时随机真实走动几秒（漫游），让画面真实移动而非原地/瞬移。"""
        win = self._load()
        if win is None or win is False or not self._ensure_ready():
            return {"ok": False, "note": "未找到游戏窗口"}
        # 小概率随机转动视角，其余向前漫游，制造真实探索感
        try:
            c = self._center()
            if c and _maybe(0.4):
                win.mouse_move_to(c[0] + (280 if _maybe(0.5) else -280), c[1])
                time.sleep(0.2)
            win.key_hold("w", seconds)
        except Exception:
            return {"ok": False, "note": "漫游失败"}
        return {"ok": True, "note": "已真实漫游 %.1fs" % seconds}


def _maybe(p: float) -> bool:
    import random
    return random.random() < p