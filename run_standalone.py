#!/usr/bin/env python3
"""独立启动器：不依赖 NEKO，也能单独运行/验证自动化核心。

用法:
  python run_standalone.py                  # SIM 运行(默认), 一直跑, Ctrl+C 停止
  python run_standalone.py --ticks 20       # 快速跑 20 轮自主后退出(验收用)
  python run_standalone.py --backend live   # 尝试真实键鼠控制
  python run_standalone.py --interval 0.5   # 调快轮询间隔

运行后会在 data/runtime/ 生成 state.json / outbox.jsonl，可查看自主动作日志
（建造/升级设施、探索抓史莱姆、收集售卖结晶、新发现汇报）。
"""
from __future__ import annotations
import os
import sys
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core.main_controller import main  # noqa: E402


def _default_data_dir() -> str:
    d = os.path.join(HERE, "data", "runtime")
    os.makedirs(d, exist_ok=True)
    return d


if __name__ == "__main__":
    # 若用户未显式传 data-dir，则默认到插件包内 data/runtime
    if "--data-dir" not in sys.argv:
        sys.argv += ["--data-dir", _default_data_dir()]
    # 默认 config 若不存在则生成默认配置
    cfg = os.path.join(HERE, "data", "config.json")
    if "--config" not in sys.argv:
        sys.argv += ["--config", cfg]
    main()