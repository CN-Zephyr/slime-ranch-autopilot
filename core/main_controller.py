"""大脑：观望 / 自主经营。

默认观望，不操作游戏。按 V 进入自主经营：先到结晶市场重置位置，
然后在牧场里收食物并投喂、收结晶卖掉，资金达到费用两倍才建造或升级。
不跑图、不抓野生史莱姆。

运行：python core/main_controller.py --data-dir <dir> --config <cfg.json>
可以 --ticks N --interval 0 --backend sim 快速验收。
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
from core.ranch import RanchState, decide_build_action, FACILITY_NAMES, record_built, MAX_LEVEL  # noqa: E402
from core.voice import HotkeyListener  # noqa: E402


class Brain:
    def __init__(self, settings: Settings, comms: Comms):
        self.s = settings
        self.c = comms
        self.mode = settings.default_mode if settings.default_mode in ("watch", "ranch") else "watch"
        self.ranch = RanchState()
        self.ticks = 0
        self._market_ready = False
        self._reset_fails = 0
        self._said: dict[str, tuple[str, int]] = {}
        self._overlay_last = ""
        self._hotkey = HotkeyListener(on_toggle=self._on_hotkey)
        # 后端选择
        if settings.backend == "live" and os.path.exists(settings.game_exe):
            self.io: IOController = LiveIOController(
                settings.game_exe,
                calibration=getattr(settings, "calibration", None),
                fallback_funds=getattr(settings, "live_fallback_funds", -1),
            )
            self.io.set_logger(self.c.logger)
            self.walk = None
            self._hybrid = False
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
    def _on_hotkey(self) -> None:
        """V 键：观望 <-> 自主经营。"""
        self._set_mode("watch" if self.mode == "ranch" else "ranch")

    def _say(self, key: str, text: str, every: int = 1) -> None:
        prev = self._said.get(key)
        if prev and prev[0] == text and self.ticks - prev[1] < every:
            return
        self._said[key] = (text, self.ticks)
        self.c.say(text)

    def _push_overlay(self) -> None:
        """把当前模式写到游戏画面左上角（仅在文字变化时推送）。"""
        if not getattr(self, "_hybrid", False) or not hasattr(self.io, "set_overlay"):
            return
        if self.mode != "ranch":
            text = "NEKO 观望中（按 V 自主经营）"
        elif not self._market_ready:
            text = "NEKO 正在前往结晶市场"
        else:
            text = "NEKO 自主经营中（按 V 回到观望）"
        if text == self._overlay_last:
            return
        self._overlay_last = text
        try:
            self.io.set_overlay(text)
        except Exception:
            pass

    def _set_mode(self, mode: str) -> None:
        if mode == "voice":
            mode = "ranch"
        elif mode not in ("watch", "ranch"):
            mode = "watch"
        self.mode = mode
        self._market_ready = False
        self._reset_fails = 0
        self._said.clear()
        if self.walk:
            if mode == "ranch":
                self.walk.clear_abort()
            else:
                self.walk.abort()
        label = "自主经营" if mode == "ranch" else "观望"
        phase = "resetting" if mode == "ranch" else "watching"
        self.c.set_state(mode=mode, phase=phase)
        self.c.say(f"模式已设为：{label}")
        self._push_overlay()

    def _finish_reset(self, ok: bool, key: str, text: str) -> None:
        if ok:
            self._market_ready = True
            self._reset_fails = 0
        self._say(key, text, every=3)

    def _teleport_market(self, why: str) -> None:
        tp = self.io.tp_market() if hasattr(self.io, "tp_market") else {"ok": False, "note": "无法传送到市场"}
        self._finish_reset(bool(tp.get("ok")), "reset-tp", f"【自主】{why}{tp.get('note', '')}")

    def _reset_to_market(self) -> None:
        """已在主牧场则走到市场。连续走不到就改传送。不在主牧场则直接传送。"""
        self.c.set_state(phase="resetting")
        if not self.walk:
            self._market_ready = True
            self._say("reset-sim", "【自主】模拟模式从牧场经营开始", every=99)
            return
        market = self.io.scan_market() if hasattr(self.io, "scan_market") else {"ok": False}
        on_ranch = market.get("ok") and market.get("area") == "牧场"
        if on_ranch and self._reset_fails < 2:
            res = self.walk.approach_market()
            if res.get("aborted"):
                return
            if res.get("ok"):
                self._finish_reset(True, "reset-walk", "【自主】已走到结晶市场，开始经营")
            else:
                self._reset_fails += 1
                self._say("reset-walk-fail", f"【自主】{res.get('note', '未能走到市场')}，再试一次后改为传送", every=1)
            return
        why = "走不到市场，改为传送。" if on_ranch else ""
        self._teleport_market(why)

    def _ranch_tick(self) -> None:
        """牧场循环：重置位置，收食物并投喂，收结晶卖掉，钱够再建造。"""
        self.ticks += 1
        if self.mode != "ranch":
            return
        if not self._market_ready:
            self._reset_to_market()
            return
        if self.walk:
            food = self.walk.collect_scanned(self.io.scan_food, "食物")
            if food.get("aborted") or self.mode != "ranch":
                return
            if food.get("ok"):
                self._say("food", f"【自主】{food.get('note')}", every=2)
                fed = self.walk.deposit_to_corral()
                if fed.get("aborted"):
                    return
                self._say("feed", f"【自主】投喂：{fed.get('note', '')}", every=2)
            else:
                self._say("no-food", f"【自主】{food.get('note', '附近没有食物')}，跳过投喂", every=4)
            if self.mode != "ranch":
                return
            plort = self.walk.collect_scanned(self.io.scan_plort, "结晶")
            if plort.get("aborted") or self.mode != "ranch":
                return
            if plort.get("ok"):
                self._say("plort", f"【自主】{plort.get('note')}", every=2)
                sold = self.walk.sell_plorts()
                if sold.get("aborted"):
                    return
                every = 2 if sold.get("ok") else 3
                self._say("sell", f"【自主】{sold.get('note', '')}", every=every)
            else:
                self._say("no-plort", f"【自主】{plort.get('note', '附近没有结晶')}", every=4)
        else:
            fed = self.io.feed()
            if not fed.get("ok"):
                self._say("feed-skip", f"【自主】投喂未完成：{fed.get('note', '')}", every=4)
            self._gather_and_sell()
        if self.mode == "ranch":
            self._infra_step()

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
            note = res.get("note", "")
            if mode == "upgrade" and any(w in note for w in ("已升满", "没有可升级", "不支持升级")):
                self.ranch.level[kind] = MAX_LEVEL
            self._say(f"build-{kind}", f"【自主】{act} {kind} 未成功：{note}", every=4)

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

    # ------------------------------------------------------------ 主循环
    def run(self, stop_condition) -> None:
        phase = "watching" if self.mode != "ranch" else "resetting"
        self.c.set_state(running=True, mode=self.mode, phase=phase, funds=self.io.read_money())
        gr = self.io.enter_game()
        if not gr.get("ok"):
            self.c.say(f"【启动】{gr.get('note','')}")
        if hasattr(self.io, "get_facilities"):
            try:
                for kind, lvl in (self.io.get_facilities() or {}).items():
                    if lvl > self.ranch.level.get(kind, 0):
                        self.ranch.level[kind] = lvl
            except Exception:
                pass
        hotkey_ok = self._hotkey.start()
        if not hotkey_ok:
            self.c.say("【提示】V 键热键没有挂上；可在插件控制台切换观望或自主经营")
        self.c.say("NEKO 已连接史莱姆牧场。当前是观望，按 V 键进入自主经营。" if self.mode != "ranch"
                   else "NEKO 已连接史莱姆牧场。当前是自主经营，按 V 键回到观望。")
        self._push_overlay()

        while True:
            cmd = self.c.read_command()
            if cmd:
                self._handle_command(cmd)
            if stop_condition():
                break

            if self.mode != "ranch":
                self.c.set_state(mode="watch", phase="watching",
                                 funds=self.io.read_money(),
                                 infra=dict(self.ranch.level),
                                 slimes=list(self.ranch.known_slimes))
                self._push_overlay()
                time.sleep(self._interval())
                continue

            self._ranch_tick()
            self.c.set_state(mode="ranch",
                             phase="running" if self._market_ready else "resetting",
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
            raise SystemExit("stop_command")
        if t == "set_mode":
            self._set_mode(cmd.get("mode", "watch"))
        elif t == "set_timeout":
            self.s.timeout_seconds = max(1, int(cmd.get("seconds", self.s.timeout_seconds)))
            self.c.say(f"接管秒数已更新为 {self.s.timeout_seconds}s")
        elif t == "command":
            text = cmd.get("text", "")
            res = run_manual_command(self.io, text)
            self.c.say(f"[指令] 「{text}」 -> {res.get('note','')}")


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
    if args.ticks:
        s.default_mode = "ranch"
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

    orig = brain._ranch_tick

    def counted_tick():
        if brain.mode == "ranch" and brain._market_ready:
            ticks["n"] += 1
        orig()
    brain._interval = lambda: float(s.sim_interval)
    brain._ranch_tick = counted_tick

    try:
        brain.run(stop_condition)
    except SystemExit:
        pass
    finally:
        comms.set_state(running=False, phase="stopped")


if __name__ == "__main__":
    main()