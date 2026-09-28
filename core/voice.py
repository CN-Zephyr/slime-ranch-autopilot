"""语音输入(faster-whisper) + V 键热键暂停/恢复。

- V 键：暂停/恢复自动游玩（paused 开关），全局热键不受游戏窗口焦点影响。
- voice 模式：监听玩家语音，翻译为文字返回给大脑执行；超过 timeout_seconds 无输入，
  大脑切换回自主接管。
所有重型依赖(faster-whisper / sounddevice / pynput)均为可选：缺失时优雅降级
（在纯 SIM/无权限环境也能运行；真实语音需按 README 安装依赖）。
"""
from __future__ import annotations
import threading
import time
from typing import Callable, Optional

try:
    import pynput.keyboard  # type: ignore
    _HAS_PYNPUT = True
except Exception:  # pragma: no cover
    _HAS_PYNPUT = False

try:
    import sounddevice as sd  # type: ignore
    import numpy as np  # type: ignore
    _HAS_AUDIO = True
except Exception:  # pragma: no cover
    _HAS_AUDIO = False

_whisper_model = None


class VoiceInput:
    """负责"采集一段语音 -> 转写为文字"。"""

    def __init__(self, lang: str = "zh"):
        self.lang = lang
        self.enabled = _HAS_AUDIO

    def _load_model(self):
        global _whisper_model
        if _whisper_model is None:
            from faster_whisper import WhisperModel  # type: ignore
            _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        return _whisper_model

    def listen_once(self, seconds: float = 3.0) -> Optional[str]:
        """录 seconds 秒并转写。返回文字；失败/静音返回 None。"""
        if not self.enabled:
            return None
        try:
            import sounddevice as sd
            import numpy as np
            fs = 16000
            audio = sd.rec(int(fs * seconds), samplerate=fs, channels=1, dtype="float32")
            sd.wait()
            audio = np.squeeze(audio)
            if audio is None or not np.any(audio):
                return None
            model = self._load_model()
            segments, _ = model.transcribe(audio, language=self.lang)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text or None
        except Exception:
            return None


class HotkeyListener:
    """全局低延迟热键守卫。回调必须短小，重逻辑放线程/队列。

    V 键 = 暂停/恢复自动游玩开关（paused）。不改变 chat/voice 模式，
    模式切换仍走指令/配置文件。
    """

    def __init__(self, on_toggle: Callable[[bool], None]):
        self.on_toggle = on_toggle
        self.paused = False
        self._last_toggle_ts = 0.0          # 防抖：按住 V 时系统自动重复触发，只响应首次
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _listen(self) -> None:
        def on_press(key):
            if getattr(key, "char", None) == "v":
                now = time.time()
                if now - self._last_toggle_ts > 0.35:   # 350ms 防抖，忽略自动重复
                    self._last_toggle_ts = now
                    self.toggle()

        def on_release(key):
            return True

        try:
            with pynput.keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                self._stop.wait()
                listener.stop()
        except Exception:
            pass

    def start(self) -> bool:
        if not _HAS_PYNPUT:
            return False
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)

    def toggle(self):
        self.paused = not self.paused
        if self.on_toggle:
            try:
                self.on_toggle(self.paused)
            except Exception:
                pass
        return self.paused