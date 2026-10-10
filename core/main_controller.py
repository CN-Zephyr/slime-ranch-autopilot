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
from core.ranch import RanchState, decide_build_action, FACILITY_NAMES, record_built  # noqa: E402
from core.voice import HotkeyListener  # noqa: E402

# 真实购买菜单的按钮关键词（中英双语：SR1 界面文字跟游戏语言走）。
# 建造菜单(空地块购买页)三个按钮文字大致为 Corral/Coop/Garden 或 围栏/鸡舍/菜园。
BUILD_KEYWORDS = {
    "corral": ["Corral", "围栏", "牧场"],
    "coop": ["Coop", "鸡舍", "鸡圈"],
    "garden": ["Garden", "菜园", "花园"],
}
# 升级菜单按钮文字是升级件名（围网/水槽/气网/结晶收集器/喂食器/喷灌…），
# 但 SR1 的升级页只有一个"购买"按钮(PurchaseButton)买当前展示项，故关键词以它为主。
UPGRADE_KEYWORDS = [
    "购买", "Purchase",
    "Netting", "Water Tank", "Air Net", "Plort Collector",
    "Feeder", "Water Trough", "Sprinkler", "Upgrade",
    "升级", "围网", "水槽", "水缸", "气网", "结晶收集", "喂食", "喷灌", "喷洒",
]


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
        self._sell_pending = False   # 背包里还有没卖掉的结晶（上轮售卖失败）
        self._hotkey = HotkeyListener(on_toggle=self._on_hotkey)
        # 后端选择
        if settings.backend == "live" and os.path.exists(settings.game_exe):
            self.io: IOController = LiveIOController(
                settings.game_exe,
                calibration=getattr(settings, "calibration", None),
                fallback_funds=getattr(settings, "live_fallback_funds", -1),
                auto_launch=getattr(settings, "auto_launch_game", False),
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
                auto_launch=getattr(settings, "auto_launch_game", False),
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

    def _maybe_dismiss_blocking_menu(self) -> None:
        """输入吞噬面板看门狗。

        SR1 失焦会自动暂停并驻留暂停菜单（NEKO 桌面窗抢焦点就会触发），暂停时吞掉
        全部移动/视角输入，抢回焦点也不会自动恢复。特征：有 Resume/Close/Back/Cancel
        类按钮且**没有** PurchaseButton（有购买按钮的是正常地块菜单，绝不能关）。
        命中则 hover 自校准点它恢复游戏。
        """
        if not self.walk:
            return
        try:
            ui = self.io.ui_buttons()
        except Exception:
            return
        names = [str(b.get("name", "")) for b in ui.get("buttons", [])]
        if not names or any("Purchase" in n for n in names):
            return
        target = next((n for n in names
                       if n in ("ResumeButton", "CloseButton", "BackButton", "CancelButton")), "")
        if not target:
            return
        if self.walk.click_button_named(target):
            self.c.say(f"【自主】检测到吞输入的面板(暂停/设置)，已点 {target} 恢复")

    def _ranch_tick(self) -> None:
        """牧场循环：重置位置，收食物并投喂，收结晶卖掉，钱够再建造。"""
        self.ticks += 1
        if self.mode != "ranch":
            return
        self._maybe_dismiss_blocking_menu()
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
                self._sell_pending = True
                self._say("plort", f"【自主】{plort.get('note')}", every=2)
                sold = self.walk.sell_plorts()
                if sold.get("aborted"):
                    return
                if sold.get("ok"):
                    self._sell_pending = False
                every = 2 if sold.get("ok") else 3
                self._say("sell", f"【自主】{sold.get('note', '')}", every=every)
            elif getattr(self, "_sell_pending", False):
                # 背包里还有上轮没卖掉的结晶：地上扫不到新结晶也再去卖一次
                sold = self.walk.sell_plorts()
                if sold.get("aborted"):
                    return
                if sold.get("ok"):
                    self._sell_pending = False
                    self._say("sell", f"【自主】{sold.get('note', '')}", every=2)
                else:
                    self._say("sell-pending", f"【自主】背包结晶还没卖掉：{sold.get('note', '')}", every=6)
            else:
                self._say("no-plort", f"【自主】{plort.get('note', '附近没有结晶')}", every=4)
        else:
            fed = self.io.feed()
            if not fed.get("ok"):
                self._say("feed-skip", f"【自主】投喂未完成：{fed.get('note', '')}", every=4)
            self._gather_and_sell()
        if self.mode == "ranch":
            self._infra_step()

    # ------------------------------------------------------------ 需求1 建造/升级（真实 UI 购买）
    def _facilities_signature(self):
        """设施快照（供真实购买前后对比验证）：(kind, 是否空地块, 已拥有升级) 的排序元组。"""
        try:
            fac = self.io.scan_facilities()
        except Exception:
            fac = []
        return tuple(sorted(
            (str(f.get("kind", "")), bool(f.get("isEmpty")),
             tuple(str(u) for u in (f.get("upgrades") or ())))
            for f in fac if isinstance(f, dict)
        ))

    def _sync_ranch_from_facilities(self) -> None:
        """把建设进度与游戏真实设施对齐（含玩家手动建/升的部分）。"""
        try:
            fac = self.io.scan_facilities()
        except Exception:
            return
        for f in fac:
            if not isinstance(f, dict):
                continue
            kind = f.get("kind")
            if kind not in FACILITY_NAMES or f.get("isEmpty"):
                continue
            ups = [str(u) for u in (f.get("upgrades") or [])]
            self.ranch.level[kind] = 2 if ups else 1
            self.ranch.upgrades[kind] = ups

    def _infra_step(self) -> None:
        """建造/升级：走到对应地块→打开菜单→真实点击购买→用设施快照验证生效。

        不再调用 mod 的 build/upgrade 魔法（那条路只扣钱、画面里没有真购买）。
        """
        if not self.walk:
            return  # 纯桥接/模拟模式没有真实键鼠执行层，不做购买
        if not getattr(self.io, "supports", None) or not self.io.supports("ui_buttons"):
            # 能力握手失败：游戏里的 mod 是旧版（没有 ui_buttons 等真实 UI 感知动作）。
            # 宁可明确提示更新 mod，也不回退到"只扣钱不真买"的魔法路径。
            self._say("infra-mod-old",
                      "【自主】游戏内 SlimeBridge mod 版本过旧（缺少真实 UI 购买能力），"
                      "请完全退出游戏后更新 Mods\\SlimeBridge.dll 再进存档", every=12)
            return
        funds = self.io.read_money()
        self._sync_ranch_from_facilities()
        action = decide_build_action(self.ranch, funds)
        if not action:
            return
        kind = action["kind"]
        mode = action["mode"]  # "build" 或 "upgrade"
        keywords = BUILD_KEYWORDS.get(kind, []) if mode == "build" else UPGRADE_KEYWORDS
        res = self.walk.real_purchase(kind, mode, keywords, self._facilities_signature)
        if res.get("ok"):
            self._sync_ranch_from_facilities()
            new_level = self.ranch.level.get(kind, 0)
            record_built(self.ranch, kind)
            name = FACILITY_NAMES.get(kind, kind)
            verb = "建造了" if mode == "build" else "升级了"
            ups = self.ranch.upgrades.get(kind) or []
            detail = f"，升级件：{'/'.join(ups)}" if mode == "upgrade" and ups else ""
            self.c.report_discovery(f"{kind}-lv{new_level}",
                                    f"真实{verb}【{name}】Lv{new_level}{detail}，花费 ${action['cost']}")
        else:
            act = "建造" if mode == "build" else "升级"
            self._say(f"build-{kind}", f"【自主】真实{act}{kind}未成功：{res.get('note','')}", every=4)

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
        if hasattr(self.io, "scan_facilities"):
            self._sync_ranch_from_facilities()
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