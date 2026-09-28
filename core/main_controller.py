"""大脑：自主游玩状态机 + 模式切换(V 键 / 语音指令 / 超时接管)。

它驱动 IOController (SIM 或 LIVE) 执行四项需求：
1) 建造/升级 牧场、鸡圈、菜园（资金 >= 2x 升级费用）；
2) 探索地图、抓捕史莱姆回牧场；
3) 收集结晶并在集市售卖；
4) 有新发现（新设施/新区域/新史莱姆）时推送汇报。

运行：python core/main_controller.py --data-dir <dir> --config <cfg.json>
可以 --ticks N --interval 0 快速跑完一次以便验收。
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.settings import Settings  # noqa: E402
from core.comms import Comms  # noqa: E402
from core.game import IOController, LiveIOController, run_manual_command  # noqa: E402
from core.sim import SimController  # noqa: E402
from core.bridge import BridgeIOController  # noqa: E402
from core.real import WalkCaptureIO  # noqa: E402
from core.ranch import RanchState, decide_build_action, FACILITY_NAMES, record_built  # noqa: E402
from core.voice import HotkeyListener, VoiceInput  # noqa: E402

AREA_NAME = {  # 探索/发现展示用
    "干燥采石场": "干燥采石场",
    "苔藓牧场": "苔藓牧场",
    "盐湖": "盐湖",
    "古代遗迹": "古代遗迹",
    "玻璃沙漠": "玻璃沙漠",
}
SLIME_NAME = {
    "粉红史莱姆": "粉红史莱姆", "岩史莱姆": "岩史莱姆", "闪电史莱姆": "闪电史莱姆",
    "苔藓史莱姆": "苔藓史莱姆", "水晶史莱姆": "水晶史莱姆", "猎人史莱姆": "猎人史莱姆",
    "钻石史莱姆": "钻石史莱姆",
}


class Brain:
    def __init__(self, settings: Settings, comms: Comms):
        self.s = settings
        self.c = comms
        self.mode = settings.default_mode
        self.ranch = RanchState()
        self.ticks = 0
        self.last_voice_at = 0.0
        self._takeover_active = False
        self._paused = False          # V 键热键：暂停/恢复自动游玩
        self._overlay_last = ""       # 游戏内叠加层状态文字（仅在变化时推送）
        self.voice = VoiceInput(lang="zh")
        self._hotkey = HotkeyListener(on_toggle=self._on_hotkey)
        # 后端选择
        if settings.backend == "live" and os.path.exists(settings.game_exe):
            self.io: IOController = LiveIOController(
                settings.game_exe,
                calibration=getattr(settings, "calibration", None),
                fallback_funds=getattr(settings, "live_fallback_funds", -1),
            )
            self.io.set_logger(self.c.logger)
        elif settings.backend in ("ws", "hybrid"):
            # 游戏内 SlimeBridge 桥接：读资金/设施来自游戏 mod，更准
            bridge = BridgeIOController(
                host=getattr(settings, "bridge_host", "127.0.0.1"),
                port=getattr(settings, "bridge_port", 8124),
                fallback_funds=getattr(settings, "live_fallback_funds", -1),
                game_exe=getattr(settings, "game_exe", ""),
                auto_launch=getattr(settings, "auto_launch_game", True),
            )
            self.io = bridge
            # hybrid：仅在执行层叠加真实键鼠（转向/走路/吸附），感知仍走桥接
            self.walk = WalkCaptureIO(bridge) if settings.backend == "hybrid" else None
            self._hybrid = settings.backend == "hybrid"
        else:
            self.io = SimController(comms, start_funds=settings.sim_start_funds)
            self.walk = None
            self._hybrid = False

    # ------------------------------------------------------------ 模式
    def _on_hotkey(self, paused: bool) -> None:
        """V 键热键回调：暂停/恢复自动游玩（不改变 chat/voice 模式）。"""
        self._paused = paused
        if paused:
            self.c.say("【热键】已按 V 键暂停自动游玩（再按 V 恢复）。")
        else:
            self.c.say("【热键】已按 V 键恢复自动游玩。")

    def _push_overlay(self) -> None:
        """把自动游玩状态渲染到游戏画面左上角（仅在状态变化时推送一次）。"""
        if not getattr(self, "_hybrid", False) or not hasattr(self.io, "set_overlay"):
            return
        text = "NEKO 自动游玩：已暂停（按 V 恢复）" if self._paused else "NEKO 自动游玩：运行中（按 V 暂停）"
        if text == getattr(self, "_overlay_last", ""):
            return
        self._overlay_last = text
        try:
            self.io.set_overlay(text)
        except Exception:
            pass

    def _set_mode(self, mode: str) -> None:
        if mode in ("chat", "voice"):
            self.mode = mode
            self.last_voice_at = time.time()
            self._takeover_active = False
            self.c.set_state(mode=mode)
            self.c.emit("info", f"模式已设为：{'语音指令' if mode=='voice' else '聊天/全程自主'}")

    # ------------------------------------------------------------ 需求1 建造/升级
    def _infra_step(self) -> None:
        funds = self.io.read_money()
        action = decide_build_action(self.ranch, funds)
        if not action:
            return
        kind = action["kind"]
        mode = action["mode"]  # "build" 或 "upgrade"
        res = self.io.build(kind) if mode == "build" else self.io.upgrade(kind)
        if res.get("ok"):
            new_level = self.ranch.level.get(kind, 0) + 1
            self.ranch.level[kind] = new_level
            record_built(self.ranch, kind)
            name = FACILITY_NAMES.get(kind, kind)
            verb = "建造了" if mode == "build" else "升级了"
            self.c.report_discovery(f"{kind}-lv{new_level}",
                                    f"{verb}【{name}】Lv{new_level}，花费 ${action['cost']}")
        else:
            act = "建造" if mode == "build" else "升级"
            self.c.say(f"【自主】{act} {kind} 未成功：{res.get('note','')}")

    # ------------------------------------------------------------ 需求2 探索/抓捕
    def _explore_step(self) -> None:
        res = self.io.explore()
        if res.get("new_area"):
            area = AREA_NAME.get(res.get("area", ""), res.get("area", ""))
            self.c.report_discovery(f"area-{res.get('area','')}", f"探索到了新区域：{area}")
        caught = res.get("caught")
        if caught:
            name = SLIME_NAME.get(caught, caught)
            if name not in self.ranch.known_slimes:
                self.ranch.known_slimes.append(name)
                self.c.report_discovery(f"slime-{caught}", f"在探索中发现了新史莱姆：{name}")

    # ------------------------------------------------------------ 混合模式真实抓捕
    # hybrid 后端：用真实键鼠走向并吸附近史莱姆/结晶（mod 只做感知，动作真实发生，
    # 画面与物品栏随之变化）。吸到史莱姆后真实走到最近围栏投放；吸到落地结晶则如实
    # 汇报（真空背包真实收集，不凭空变钱）。无目标时真实漫游几秒，再尝试收割售卖。
    def _capture_step(self) -> None:
        if not getattr(self, "walk", None) or not getattr(self, "_hybrid", False):
            self._explore_step()
            return
        res = self.walk.capture_target()
        if res.get("ok"):
            kind = res.get("kind", "")
            self.c.say(f"【自主】{res.get('note','')}")
            if kind == "slime":
                # 吸到史莱姆 -> 真实走到最近围栏投放（这才是"养史莱姆"）
                dr = self.walk.deposit_to_corral()
                self.c.say(f"【自主】投放史莱姆：{dr.get('note','')}")
            elif kind == "plort":
                # 吸到落地结晶 -> 真空背包真实收集，攒着由 _sell_step 周期真实走到结晶市场卖出
                self.c.say("【自主】已真实吸到落地结晶（在真空背包），待周期走到结晶市场卖出")
        else:
            # 无目标或不可达：真实漫游随机移动，制造探索感而非原地不动
            self.walk.wander_step()
            self.c.say(f"【自主】{res.get('note','')}，改真实漫游以便寻找目标")

    # ------------------------------------------------------------ 需求3 收集+售卖
    def _gather_and_sell(self) -> None:
        # 混合模式：钱必须来自真实动作。mod 的 harvest/sell 是"凭空注入结晶/兑换资金"
        # 的魔法层，若每 tick 调用会让资金无视真实行为持续上涨，与"画面真实运作"矛盾，
        # 故 hybrid 下彻底禁用；真实售卖待集市 UI 点击接入后再启用。
        if getattr(self, "_hybrid", False):
            return
        res = self.io.harvest()
        if res.get("ok") and res.get("count", 0) == 0:
            return
        sr = self.io.sell()
        if sr.get("ok"):
            gains = sr.get("gains", 0)
            self.c.say(f"【自主】已运回结晶并在集市售卖，收入 ${gains}，当前资金 ${self.io.read_money()}")

    # ------------------------------------------------------------ 真实售卖（hybrid）
    def _sell_step(self) -> None:
        """混合模式：周期（约每 60s）真实走到结晶市场，投出背包里的结晶换钱。

        收益 = 卖前后 mod 真实资金之差，汇报真实入账。这就是"看到钱从画面里来"。
        """
        if not getattr(self, "walk", None) or not getattr(self, "_hybrid", False):
            return
        now = time.time()
        if now - getattr(self, "_last_sell", 0.0) < 60.0:
            return
        self._last_sell = now
        res = self.walk.sell_plorts()
        self.c.say(f"【自主】{res.get('note','')}")

    # ------------------------------------------------------------ 自主一步
    def autonomous_tick(self) -> None:
        self.ticks += 1
        # 探索优先让目标/资金能滚动起来；同时推进建造、收割、售卖
        if getattr(self, "_hybrid", False):
            # 混合模式：真实走向并吸附附近史莱姆/结晶（画面/物品栏随之真实变化）
            self._capture_step()
            self._sell_step()          # 攒够时间就去结晶市场真实卖出
        else:
            need_explore = len(self.ranch.known_slimes) == 0 or self.ticks % 3 == 0
            if need_explore:
                self._explore_step()
        self._infra_step()
        self._gather_and_sell()

    # ------------------------------------------------------------ 主循环
    def run(self, stop_condition) -> None:
        self.c.set_state(running=True, mode=self.mode, phase="booting", funds=self.io.read_money())
        # 启动 / V 键热键
        gr = self.io.enter_game()
        if not gr.get("ok"):
            self.c.say(f"【启动】{gr.get('note','')}")
        # 从游戏同步已有设施进度，避免状态机从 0 记忆与实际脱节
        if hasattr(self.io, "get_facilities"):
            try:
                for kind, lvl in (self.io.get_facilities() or {}).items():
                    if lvl > self.ranch.level.get(kind, 0):
                        self.ranch.level[kind] = lvl
            except Exception:
                pass
        hotkey_ok = self._hotkey.start()
        if not hotkey_ok:
            self.c.say("【提示】未检测到 pynput，V 键热键不可用；可在插件控制台/配置文件切换模式")
            if self.s.default_mode == "voice":
                self.c.set_state(mode="chat")
                self.mode = "chat"
        self.c.set_state(phase="running")
        self.c.say("NEKO 已接管史莱姆牧场游玩。按 V 键暂停/恢复自动游玩。")

        while True:
            cmd = self.c.read_command()
            if cmd:
                self._handle_command(cmd)
            if stop_condition():
                break

            if self._paused:
                # 暂停：只响应指令与热键，不做任何自主动作，画面人物由玩家接管
                self.c.set_state(mode=self.mode, phase="paused",
                                 funds=self.io.read_money(),
                                 infra=dict(self.ranch.level),
                                 slimes=list(self.ranch.known_slimes))
                self._push_overlay()
                time.sleep(self._interval())
                continue

            if self.mode == "chat":
                # 聊天模式：全程自主
                self._takeover_active = False
                self.autonomous_tick()
            else:
                # 语音指令模式：先听玩家，超时则由 NEKO 接管
                self._voice_tick()

            self.c.set_state(mode=self.mode, phase="running",
                             funds=self.io.read_money(),
                             infra=dict(self.ranch.level),
                             slimes=list(self.ranch.known_slimes))
            self._push_overlay()
            time.sleep(self._interval())

        self.c.set_state(running=False, phase="stopped")
        self._hotkey.stop()

    def _interval(self) -> float:
        return self.s.sim_interval

    def _handle_command(self, cmd) -> None:
        t = cmd.get("type")
        if t == "stop":
            self.c.say("收到停止指令，停止游玩。")
            self._HALT = True  # noqa: F841
            raise SystemExit("stop_command")
        if t == "set_mode":
            self._set_mode(cmd.get("mode", "chat"))
        elif t == "set_timeout":
            self.s.timeout_seconds = max(1, int(cmd.get("seconds", self.s.timeout_seconds)))
            self.c.say(f"接管秒数已更新为 {self.s.timeout_seconds}s")
        elif t == "command":
            text = cmd.get("text", "")
            res = run_manual_command(self.io, text)
            self.c.say(f"[语音指令] 你说「{text}」 -> {res.get('note','')}")

    def _voice_tick(self) -> None:
        heard = self.voice.listen_once(seconds=2.0)
        if heard:
            self.last_voice_at = time.time()
            self._takeover_active = False
            res = run_manual_command(self.io, heard)
            self.c.say(f"[语音指令] 你说了「{heard}」 -> {res.get('note','')}")
            return
        idle = time.time() - self.last_voice_at
        if idle >= self.s.timeout_seconds:
            if not self._takeover_active:
                self.c.emit("info", f"玩家已 {self.s.timeout_seconds}s 未输入，NEKO 自主接管游玩。")
                self._takeover_active = True
            self.autonomous_tick()
        else:
            # 仍在等玩家输入
            self.c.set_state(phase="listening_voice")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="史莱姆牧场自动游玩核心")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--config", required=False, default="")
    ap.add_argument("--ticks", type=int, default=0, help="跑 N 轮自主 tick 后退出(0=一直运行)")
    ap.add_argument("--interval", type=float, default=2.0, help="每轮间隔秒数")
    ap.add_argument("--backend", choices=["sim", "live", "ws", "hybrid"], default="")
    args = ap.parse_args(argv)

    s = Settings.load(args.data_dir, args.config)
    if args.backend:
        s.backend = args.backend
    if args.interval >= 0:
        s.sim_interval = args.interval
    s.sim_interval = float(getattr(s, "sim_interval", args.interval))

    comms = Comms(args.data_dir)
    brain = Brain(s, comms)
    ticks = {"n": 0}

    def stop_condition() -> bool:
        if args.ticks and ticks["n"] >= args.ticks:
            return True
        return False

    # 封装 autonomous_tick 以累计次数
    orig = brain.autonomous_tick

    def counted_tick():
        if brain.mode == "chat" or brain._takeover_active:
            ticks["n"] += 1
        orig()
    brain._interval = lambda: float(s.sim_interval)
    brain.autonomous_tick = counted_tick

    try:
        brain.run(stop_condition)
    except SystemExit:
        pass
    finally:
        comms.set_state(running=False, phase="stopped")


if __name__ == "__main__":
    main()