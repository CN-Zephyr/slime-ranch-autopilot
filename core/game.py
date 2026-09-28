"""控制层（live 模式）：启动游戏、模拟键鼠、按命令执行动作。

定义统一 IO 接口 IOController：真实实现 LiveIOController 与模拟实现 SimController
（在 sim.py）都实现同一组方法，供大脑状态机调用。
所有动作都返回 dict：{"ok": bool, ...}。
"""
from __future__ import annotations
import abc
import os
import subprocess
import tempfile
import time
from typing import Dict, Any, List

try:
    import pyautogui  # type: ignore
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.08
except Exception:  # pragma: no cover
    pyautogui = None


class IOController(abc.ABC):
    """大脑依赖的控制接口。"""

    @abc.abstractmethod
    def enter_game(self) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def is_alive(self) -> bool: ...

    @abc.abstractmethod
    def read_money(self) -> int: ...

    @abc.abstractmethod
    def build(self, kind: str) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def upgrade(self, kind: str) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def feed(self) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def harvest(self) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def get_plorts(self) -> List[str]: ...

    @abc.abstractmethod
    def sell(self) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def explore(self) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def go_home(self) -> Dict[str, Any]: ...

    @abc.abstractmethod
    def describe(self) -> Dict[str, Any]: ...


class LiveIOController(IOController):
    """真实键鼠控制（Windows）。窗口需为前台或可被置为前台。

    使用 winio(纯 ctypes Win32) 附加游戏窗口 + GDI 截屏 + SendInput 键鼠，
    用 vision 读取资金(OCR，可选)。关键点击/菜单坐标依赖校准配置
    (README 校准节 / "校准截图"命令)，未校准时按键盘式通用操作尽量执行。
    """

    def __init__(self, game_exe: str = "", calibration: dict = None,
                 window_exe: str = "SlimeRancher.exe", fallback_funds: int = -1):
        self.game_exe = game_exe
        self.auto_launch = bool(game_exe)
        self.window_exe = window_exe
        self.calibration = calibration or {}
        self.fallback_funds = fallback_funds  # OCR 不可用时资金兜底值
        self._win = None  # 惰性导入 winio
        self._vision = None  # 惰性导入 vision
        self._logger = None
        self._launched = False  # 只自动启动一次，避免重复拉起多个游戏实例

    # ---- 惰性载入依赖：只在需要时 import，避免拖垮 sim 模式 ----
    def _load(self):
        if self._win is None or self._win is False:
            try:
                from . import winio  # type: ignore
                self._win = winio
            except Exception as e:  # pragma: no cover
                self._win = False
                self._load_error = e
        if self._vision is None or self._vision is False:
            try:
                from . import vision  # type: ignore
                self._vision = vision
            except Exception as e:  # pragma: no cover
                self._vision = False
                self._load_error = e
        win = self._win if self._win is not False else None
        vis = self._vision if self._vision is not False else None
        return win, vis

    def _load_ok(self) -> bool:
        win, _ = self._load()
        return win is not None

    def set_logger(self, logger=None):
        self._logger = logger

    def _hwnd(self):
        win, _ = self._load()
        if win is None:
            return None
        hwnd = win.find_game_window(self.window_exe)
        if hwnd is None and not self._launched and self.auto_launch \
                and self.game_exe and os.path.exists(self.game_exe):
            self._launched = True
            subprocess.Popen([self.game_exe], cwd=os.path.dirname(self.game_exe))
            for _ in range(30):
                time.sleep(1.0)
                hwnd = win.find_game_window(self.window_exe)
                if hwnd is not None:
                    break
        return hwnd

    def _screen_pt(self, hwnd, fx: float, fy: float):
        """窗口内部归一化坐标 (0..1) -> 屏幕绝对坐标。"""
        win, _ = self._load()
        rect = win.get_window_rect(hwnd)
        if rect is None:
            return None
        x, y, w, h = rect
        return (int(x + w * fx), int(y + h * fy))

    def _click_btn(self, hwnd, point_key: str, default=(0.5, 0.5)) -> bool:
        """点击校准配置里的某个屏幕点位（归一化窗口坐标）；缺省用默认点。"""
        win, _ = self._load()
        cfg = self.calibration.get(point_key) if self.calibration else None
        fx, fy = cfg if cfg else default
        pt = self._screen_pt(hwnd, fx, fy)
        if not pt:
            return False
        win.mouse_click(pt[0], pt[1])
        return True

    # ------------------------------------------------------------------
    def enter_game(self) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "note": "未找到游戏窗口，先打开《史莱姆牧场》并进入存档"}
        win.ensure_foreground(hwnd)
        time.sleep(0.5)
        win.press_key("enter")  # 若在主菜单/继续存档，回车可直接进入
        time.sleep(2.0)
        return {"ok": True, "note": "已附加游戏窗口并尝试进入存档"}

    def is_alive(self) -> bool:
        if self._load()[0] is None:
            return False
        try:
            return self._hwnd() is not None
        except Exception:
            return False

    def read_money(self) -> int:
        win, vision = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return -1
        img = vision.capture_game(hwnd)
        if img is None:
            return -1
        region = self.calibration.get("money_region") if self.calibration else None
        value = vision.read_money(img, region, self._logger)
        # OCR 不可用/失败时，退回固定保底资金，让自主游玩仍能推进（仅在未校准时）
        if value is None or value < 0:
            if self.fallback_funds >= 0:
                return self.fallback_funds
        return value

    def capture_calibration(self, data_dir: str = ".") -> str:
        """把当前游戏画面存成 PNG，用于模板/坐标校准。返回文件路径。"""
        win, vision = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            raise ValueError("未找到游戏窗口")
        img = vision.capture_game(hwnd)
        if img is None:
            raise ValueError("窗口截图失败")
        return vision.save_calibration(img, data_dir)

    def build(self, kind: str) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "facility": kind, "note": "未找到游戏窗口"}
        # 建造菜单：Tab 打开 -> 若配置了选择按钮则点击，否则回车确认
        win.ensure_foreground(hwnd)
        win.press_key("tab")
        time.sleep(1.0)
        if not self._click_btn(hwnd, "btn_confirm", (0.5, 0.75)):
            win.press_key("enter")
        time.sleep(1.0)
        return {"ok": True, "facility": kind, "cost": 0,
                "note": f"已建造 {kind}(live) [点击坐标需校准]".format(kind=kind)}

    def upgrade(self, kind: str) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "facility": kind, "note": "未找到游戏窗口"}
        win.ensure_foreground(hwnd)
        win.press_key("tab")
        time.sleep(1.0)
        win.press_key("u")
        time.sleep(1.0)
        return {"ok": True, "facility": kind, "cost": 0,
                "note": f"已升级 {kind}(live) [点击坐标需校准]"}

    def feed(self) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "note": "未找到游戏窗口"}
        win.ensure_foreground(hwnd)
        win.press_key("1")  # 切换食物槽
        pt = self._screen_pt(hwnd, 0.5, 0.5)
        if pt:
            win.mouse_hold(pt[0], pt[1], 1.0)  # 对准场地投喂
        return {"ok": True, "note": "已投喂史莱姆(live)"}

    def harvest(self) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "note": "未找到游戏窗口"}
        win.ensure_foreground(hwnd)
        pt = self._screen_pt(hwnd, 0.5, 0.5)
        if pt:
            win.mouse_hold(pt[0], pt[1], 2.0)  # 左键吸
        return {"ok": True, "note": "已收集结晶(live)"}

    def get_plorts(self) -> List[str]:
        return []  # 读包需画面识别，未实现时返回空

    def sell(self) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "note": "未找到游戏窗口"}
        win.ensure_foreground(hwnd)
        win.press_key("e")  # 与市场交互
        time.sleep(1.0)
        if not self._click_btn(hwnd, "btn_sell_all", (0.5, 0.6)):
            win.press_key("enter")
        time.sleep(1.0)
        return {"ok": True, "gains": 0, "plorts": [], "note": "已在集市售卖结晶(live)"}

    def explore(self) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "caught": False, "note": "未找到游戏窗口"}
        win.ensure_foreground(hwnd)
        win.key_hold("w", 5.0)  # 前进探索
        return {"ok": True, "caught": False, "area": "野外", "note": "已在野外探索(live)"}

    def go_home(self) -> Dict[str, Any]:
        win, _ = self._load()
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "note": "未找到游戏窗口"}
        win.ensure_foreground(hwnd)
        win.press_key("m")
        time.sleep(0.5)
        if not self._click_btn(hwnd, "btn_home", (0.5, 0.8)):
            win.press_key("home")
        return {"ok": True, "note": "已尝试返回牧场(live)"}

    def describe(self) -> Dict[str, Any]:
        win, _ = self._load()
        alive = self.is_alive()
        cal = sorted((self.calibration or {}).keys())
        return {"mode": "live", "winapi": win is not None, "game_window": alive,
                "calibration_keys": cal}

    def capture(self) -> Dict[str, Any]:
        """把当前游戏画面存成 PNG 以便校准，返回保存路径。"""
        win, vision = self._load()
        if win is None:
            return {"ok": False, "note": "视觉依赖未就绪(winio 不可用)"}
        hwnd = self._hwnd()
        if hwnd is None:
            return {"ok": False, "note": "未找到游戏窗口"}
        img = vision.capture_game(hwnd)
        if img is None:
            return {"ok": False, "note": "窗口截图失败"}
        out = os.path.join(tempfile.gettempdir(), "slime_ranch_calib")
        p = vision.save_calibration(img, out, tag="live")
        return {"ok": True, "path": p, "note": f"已保存校准截图: {p}"}


# ------------------------------------------------------------------ 指令执行器
_MANUAL_COMMANDS = {
    "build_corral": ("build", "corral"),
    "build_coop": ("build", "coop"),
    "build_garden": ("build", "garden"),
    "upgrade_corral": ("upgrade", "corral"),
    "upgrade_coop": ("upgrade", "coop"),
    "upgrade_garden": ("upgrade", "garden"),
    "feed": ("feed", ""),
    "harvest": ("harvest", ""),
    "sell": ("sell", ""),
    "explore": ("explore", ""),
    "go_home": ("go_home", ""),
}


def run_manual_command(io: IOController, text: str) -> Dict[str, Any]:
    """把玩家语音/文字指令翻译成 IO 动作。返回 {"ok":..,"note":..}。
    支持自然语言关键词映射，双语兼容。"""
    t = text.lower().strip()
    action, arg = _match_command(t)
    if action is None:
        return {"ok": False, "note": f"无法识别的指令: {text}"}

    if action == "build":
        res = io.build(arg)
        return {"ok": res.get("ok", False), "note": f"建造{arg}: {res.get('note','')}"}
    if action == "upgrade":
        res = io.upgrade(arg)
        return {"ok": res.get("ok", False), "note": f"升级{arg}: {res.get('note','')}"}
    if action == "feed":
        res = io.feed()
        return {"ok": res.get("ok", False), "note": res.get("note", "已投喂")}
    if action == "harvest":
        res = io.harvest()
        return {"ok": res.get("ok", False), "note": res.get("note", "已收集")}
    if action == "sell":
        res = io.sell()
        return {"ok": res.get("ok", False), "note": f"售卖: {res.get('note','')}"}
    if action == "explore":
        res = io.explore()
        return {"ok": res.get("ok", False), "note": f"探索: {res.get('note','')}"}
    if action == "go_home":
        res = io.go_home()
        return {"ok": res.get("ok", False), "note": res.get("note", "已回家")}
    if action == "capture":
        fn = getattr(io, "capture", None)
        if fn is None:
            return {"ok": False, "note": "当前后端不支持校准截图"}
        res = fn()
        return {"ok": res.get("ok", False), "note": res.get("note", "")}
    return {"ok": False, "note": "未知动作"}


def _match_command(text: str):
    t = text
    if any(w in t for w in ("造鸡", "鸡圈", "鸡舍", "coop")):
        return ("build", "coop")
    if any(w in t for w in ("造菜", "菜园", "菜地", "花园", "garden")):
        return ("build", "garden")
    if any(w in t for w in ("造围栏", "造牧场", "围栏", "牧场", "corral")):
        return ("build", "corral")
    if any(w in t for w in ("升级", "upgrade")):
        if any(w in t for w in ("鸡", "coop")):
            return ("upgrade", "coop")
        if any(w in t for w in ("菜", "花园", "garden")):
            return ("upgrade", "garden")
        return ("upgrade", "corral")
    if any(w in t for w in ("喂", "投喂", "feed")):
        return ("feed", "")
    if any(w in t for w in ("吸", "收集", "结晶", "harvest")):
        return ("harvest", "")
    if any(w in t for w in ("卖", "贩", "出售", "sell")):
        return ("sell", "")
    if any(w in t for w in ("探索", "抓", "捕捉", "explore")):
        return ("explore", "")
    if any(w in t for w in ("回家", "返回", "home")):
        return ("go_home", "")
    if any(w in t for w in ("校准", "截图", "capture")):
        return ("capture", "")
    return (None, "")