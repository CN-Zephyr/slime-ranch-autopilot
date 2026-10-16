"""临时探针：测试 SlimeBridge 桥接的真实动作。"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8124"


def post(action, kind=""):
    req = urllib.request.Request(
        BASE + "/api/action",
        data=json.dumps({"action": action, "kind": kind}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())


def status():
    return json.loads(urllib.request.urlopen(BASE + "/api/status", timeout=10).read().decode())


def main():
    st = status()
    print("initial:", json.dumps(st, ensure_ascii=False))
    if not st.get("game_loaded"):
        print("continue ->", post("continue"))
        for i in range(12):
            time.sleep(2)
            st = status()
            print(f"poll{i}: game_loaded={st['game_loaded']} money={st['money']} "
                  f"estimated={st['money_estimated']} area={st['area']}")
            if st["game_loaded"]:
                break
    if st.get("game_loaded"):
        print("=== money ===")
        print("money_add 100 ->", post("money_add", "100"))
        print("status:", status())
        print("=== explore ===")
        print("explore ->", post("explore"))
        print("=== harvest ===")
        print("harvest ->", post("harvest"))
        print("status:", status())
        print("=== sell ===")
        print("sell ->", post("sell"))
        print("status:", status())


if __name__ == "__main__":
    main()
