"""临时探针2：测试建造/升级/回家动作在真实游戏中的结果。"""
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
    print("status:", json.dumps(st, ensure_ascii=False))
    if not st.get("game_loaded"):
        print("continue ->", post("continue"))
        for _ in range(12):
            time.sleep(2)
            st = status()
            if st.get("game_loaded"):
                break
        print("after continue:", json.dumps(st, ensure_ascii=False))
    if not st.get("game_loaded"):
        print("still not loaded, abort")
        return
    print("=== build corral ===")
    print(post("build", "corral"))
    time.sleep(1)
    print("status:", json.dumps(status(), ensure_ascii=False))
    print("=== build coop ===")
    print(post("build", "coop"))
    time.sleep(1)
    print("status:", json.dumps(status(), ensure_ascii=False))
    print("=== upgrade corral ===")
    print(post("upgrade", "corral"))
    time.sleep(1)
    print("status:", json.dumps(status(), ensure_ascii=False))
    print("=== go_home ===")
    print(post("go_home"))
    time.sleep(1)
    print("status:", json.dumps(status(), ensure_ascii=False))


if __name__ == "__main__":
    main()
