"""独立运行的模拟 SlimeBridge 服务端（仅用于本地/CI 端到端演示，不碰真实游戏）。

模拟游戏内 SlimeBridge 的 HTTP 行为：内存台账 + /api/health、/api/status、/api/action。
用途：在没启动游戏/UMF 的环境，验证 ws backend 全链路（大脑状态机 -> 桥接 -> HTTP -> 台账）能推进。

运行:
  python tests/fake_bridge_server.py --port 8124      # 前台常驻
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LEDGER = {
    "money": 1500,
    "corral": {"level": 1, "count": 1},
    "coop": {"level": 0, "count": 0},
    "garden": {"level": 0, "count": 0},
}

HEALTH = b'{"ok":true,"name":"slime_bridge"}'
BUILD_COST = {"corral": 225, "coop": 400, "garden": 300}   # 新建
UPGRADE_COST = {"corral": 350, "coop": 625, "garden": 500}  # 单级升级


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _status(self):
        body = json.dumps({
            "ok": True, "mode": "bridge", "game_loaded": True,
            "money": LEDGER["money"], "money_estimated": False,
            "facilities": LEDGER,
            "plorts": "count=5,gains=50", "area": "干燥采石场",
            "note": "fake-slime-bridge",
        }).encode("utf-8")
        self._send(body)

    def _action(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n).decode("utf-8"))
        a, k = req.get("action", ""), req.get("kind", "")
        note = a
        if a == "build":
            lvl = LEDGER.get(k, {}).get("level", 0)
            cost = BUILD_COST.get(k, 200) if lvl == 0 else UPGRADE_COST.get(k, 300) * lvl
            LEDGER["money"] -= cost
            if LEDGER.get(k) is None:
                LEDGER[k] = {"level": 1, "count": 1}
            else:
                LEDGER[k]["count"] += 1
                LEDGER[k]["level"] = max(1, LEDGER[k]["level"])
            note = f"built {k} cost={cost}"
        elif a == "upgrade":
            lvl = LEDGER.get(k, {}).get("level", 0) + 1
            LEDGER[k] = {"level": lvl, "count": LEDGER.get(k, {}).get("count", 1)}
            note = f"upgraded {k} to lv{lvl}"
        else:
            body = json.dumps({
                "ok": True, "strategy": "simulate",
                "gains": 50 if a == "sell" else 0,
                "note": note,
            }).encode("utf-8")
            self._send(body)
            return
        body = json.dumps({
            "ok": True, "strategy": "simulate", "gains": 0, "note": note,
        }).encode("utf-8")
        self._send(body)

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8124)
    args = ap.parse_args()
    srv = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"fake SlimeBridge listening on 127.0.0.1:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())