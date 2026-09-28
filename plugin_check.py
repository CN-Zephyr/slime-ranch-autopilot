#!/usr/bin/env python3
"""plugin.toml 契约自检 + 入口类扫描（不依赖 NEKO SDK，可在本机运行）。

用法：
  python plugin_check.py        # 校验 plugin.toml 是否满足 NEKO 插件契约
  python plugin_check.py -i     # 另扫描 __init__.py 里的异步入口方法
"""
from __future__ import annotations
import argparse
import os
import re
import sys

try:
    import tomllib  # Python 3.11+
except Exception:  # pragma: no cover
    tomllib = None

HERE = os.path.dirname(os.path.abspath(__file__))
TOML_PATH = os.path.join(HERE, "plugin.toml")

MANIFEST = None  # populated on load for tests


def load_manifest() -> dict:
    global MANIFEST
    if MANIFEST is not None:
        return MANIFEST
    if tomllib is None:
        raise RuntimeError("需要 Python 3.11+ 才能解析 plugin.toml")
    with open(TOML_PATH, "rb") as f:
        MANIFEST = tomllib.load(f)
    return MANIFEST


def run_checks() -> list[str]:
    problems: list[str] = []
    m = load_manifest()
    p = m.get("plugin", {})
    folder = os.path.basename(HERE)

    if not p.get("id"):
        problems.append("[ident] plugin.id 缺失")
    if p.get("id") != folder:
        problems.append(f"[ident] plugin.id({p.get('id')}) 与文件夹名({folder})不一致")
    if not p.get("entry"):
        problems.append("[ident] plugin.entry 缺失")
    else:
        ep = p["entry"].split(":")
        if len(ep) != 2:
            problems.append(f"[ident] plugin.entry 应为 module:Class：{p['entry']}")
        else:
            e_mod, e_cls = ep
            expect = f"plugin.plugins.{folder}:{e_cls}"
            if p["entry"] != expect:
                problems.append(f"[ident] 入口应为 {expect}，当前 {p['entry']}")

    rt = m.get("plugin_runtime", {})
    for k in ("enabled", "auto_start"):
        if k in rt and not isinstance(rt[k], bool):
            problems.append(f"[runtime] {k} 必须是布尔")
    if "timeout" in rt and not (0 < rt["timeout"] <= 300):
        problems.append("[runtime] timeout 需满足 0<timeout<=300")

    ui = p.get("ui", {})
    if ui and ui.get("panel"):
        for panel in ui["panel"]:
            if not panel.get("entry", "").endswith(".tsx"):
                problems.append(f"[ui] 面板 {panel.get('id')} 的 entry 应以 .tsx 结尾")
            if not os.path.exists(os.path.join(HERE, panel.get("entry", ""))):
                problems.append(f"[ui] 面板 {panel.get('id')} 的 entry 文件不存在: {panel.get('entry')}")

    cfg = m.get("slime_ranch", {})
    if "timeout_seconds" in cfg and not isinstance(cfg["timeout_seconds"], int):
        problems.append("[cfg] slime_ranch.timeout_seconds 应为整数")
    return problems


def scan_entries() -> list[tuple[str, str]]:
    """扫描 __init__.py 中以 @plugin_entry 修饰的方法，校验皆为 async def。"""
    path = os.path.join(HERE, "__init__.py")
    src = open(path, "r", encoding="utf-8").read()
    entries = []
    src_lines = src.splitlines()
    for i, line in enumerate(src_lines):
        if "@plugin_entry" in line:
            # 找下一个 def 行
            for j in range(i + 1, len(src_lines)):
                if re.search(r"def\s+(\w+)\(", src_lines[j]):
                    name = re.search(r"def\s+(\w+)\(", src_lines[j]).group(1)
                    is_async = "async" in src_lines[j - 1] or "async" in src_lines[j]
                    entries.append((name, is_async))
                    break
    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--inspect", action="store_true", help="扫描入口方法是否 async")
    args = ap.parse_args()

    print(f"校验插件：{HERE}")
    problems = run_checks()
    if problems:
        print("发现契约问题：")
        for xp in problems:
            print("  ✗ " + xp)
        print("判定：未通过")
        return 1
    print("  ✓ plugin.toml 契约检查通过")

    if args.inspect:
        for name, is_async in scan_entries():
            tag = "async ✓" if is_async else "非 async ✗"
            print(f"  入口 {name:<24} {tag}")
        bad = [n for n, a in scan_entries() if not a]
        if bad:
            print("存在非异步入口", bad)
            return 1
    print("判定：OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())