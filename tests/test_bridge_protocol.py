"""验证 ws backend(BridgeIOController) 与游戏内 SlimeBridge 的 HTTP 协议一致性。

启动一个标准库 http.server 模拟 SlimeBridge(内存台账)，再断言 BridgeIOController
能读资金/状态并以 JSON 下发动作。整个测试只用标准库，可在无 pyautogui/pynput 的环境跑。
运行: python -m tests.test_bridge_protocol
"""
from __future__ import annotations

import json
import sys
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bridge import BridgeIOController  # noqa: E402

# 内存台账：模拟 SlimeBridge 服务器行为
LEDGER = {
    "money": 1500, "corral": {"level": 1, "count": 1},
    "coop": {"level": 0, "count": 0}, "garden": {"level": 0, "count": 0},
}

HEALTH = b'{"ok":true,"name":"slime_bridge"}'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默
        pass

    def _status(self):
        body = json.dumps({
            "ok": True, "mode": "bridge", "game_loaded": True,
            "money": LEDGER["money"], "money_estimated": False,
            "facilities": LEDGER,
            "plorts": "count=5,gains=50", "area": "干燥采石场",
            "note": "test-fake",
        }).encode("utf-8")
        self._send(body)

    def _action(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n).decode("utf-8"))
        a, k = req.get("action", ""), req.get("kind", "")
        if a == "sell":
            LEDGER["money"] += 50; LEDGER["money_estimated"] = False
            body = {"ok": True, "strategy": "simulate", "gains": 50, "note": "sold"}
        elif a == "build":
            LEDGER[k] = {"level": 1, "count": 1}
            body = {"ok": True, "strategy": "simulate", "gains": 0, "note": "built"}
        else:
            body = {"ok": True, "strategy": "simulate", "gains": 0, "note": a}
        self._send(json.dumps(body).encode("utf-8"))

    def _send(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/health":
            self._send(HEALTH)
        elif self.path == "/api/status":
            self._status()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == "/api/action":
            self._action()
        else:
            self.send_response(404); self.end_headers()


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    io = BridgeIOController("127.0.0.1", port, fallback_funds=-1)
    ok = io.is_alive()
    assert ok, "is_alive 失败"
    assert io.read_money() == 1500, "read_money 失败"
    d = io.describe()
    assert d["connected"] is True, "describe.connected 失败"

    b = io.build("coop")
    assert b["ok"] and b["cost"] == 400, f"build(新建coop)费用/结果异常: {b}"
    u = io.upgrade("corral")
    assert u["ok"] and u["cost"] == 350, f"upgrade(corral lv1)费用异常: {u}"
    s = io.sell()
    assert s["ok"] and s["gains"] == 50, f"sell 结果异常: {s}"
    e = io.explore()
    assert e["ok"], f"explore 结果异常: {e}"
    print("=== 协议验证通过: ws backend 与 SlimeBridge 兼容 ===")
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())