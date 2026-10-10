"""一键把插件装进旁边的 N.E.K.O。

用法：双击 install.bat，或在本目录执行 py -3 install.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = (ROOT.parent / "N.E.K.O" / "plugin" / "plugins" / "slime_ranch_autopilot").resolve()
SKIP = {".git", ".venv-core", "data", "__pycache__", ".venv"}


def find_python() -> str:
    return sys.executable


def find_game() -> str:
    roots = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Steam", "steamapps", "common", "Slime Rancher", "SlimeRancher.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Steam", "steamapps", "common", "Slime Rancher", "SlimeRancher.exe"),
    ]
    for drive in "CDEFG":
        roots.append(rf"{drive}:\SteamLibrary\steamapps\common\Slime Rancher\SlimeRancher.exe")
        roots.append(rf"{drive}:\Steam\steamapps\common\Slime Rancher\SlimeRancher.exe")
    for path in roots:
        if path and os.path.exists(path):
            return path
    return ""


def copy_tree() -> None:
    if not (ROOT.parent / "N.E.K.O" / "plugin" / "plugins").is_dir():
        raise SystemExit("找不到旁边的 N.E.K.O\\plugin\\plugins")
    DEST.mkdir(parents=True, exist_ok=True)
    for src in ROOT.rglob("*"):
        rel = src.relative_to(ROOT)
        if any(part in SKIP for part in rel.parts):
            continue
        dst = DEST / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def ensure_venv(python: str) -> Path:
    venv_python = DEST / ".venv-core" / "Scripts" / "python.exe"
    if not venv_python.exists():
        subprocess.check_call([python, "-m", "venv", str(DEST / ".venv-core")])
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "-q", "Pillow"])
    return venv_python


def toml_string(value: str) -> str:
    # 单引号字符串不处理反斜杠，Windows 路径可以直接放进去。
    return "'" + value.replace("'", "''") + "'"


def write_config(venv_python: Path, game: str) -> None:
    toml = DEST / "plugin.toml"
    text = toml.read_text(encoding="utf-8")
    text = re.sub(
        r"(?m)^engine_python\s*=.*$",
        lambda _m: "engine_python = " + toml_string(str(venv_python)),
        text,
    )
    text = re.sub(
        r"(?m)^game_exe\s*=.*$",
        lambda _m: "game_exe = " + toml_string(game),
        text,
    )
    toml.write_text(text, encoding="utf-8")


CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
REF_DLLS = (
    "Assembly-CSharp.dll",
    "UnityEngine.dll",
    "UnityEngine.CoreModule.dll",
    "UnityEngine.UI.dll",
    "UnityEngine.UIModule.dll",
    "UnityEngine.InputLegacyModule.dll",
    "UnityEngine.TextRenderingModule.dll",
    "UnityEngine.PhysicsModule.dll",
    "UnityEngine.IMGUIModule.dll",
    "UnityCoreMod.dll",
)


def install_mod(game: str) -> Path:
    if not game:
        raise SystemExit("没找到史莱姆牧场，无法把 mod 放进游戏。")
    if not CSC.exists():
        raise SystemExit("没找到系统 C# 编译器，无法生成 mod。")
    managed = Path(game).parent / "SlimeRancher_Data" / "Managed"
    mods = Path(game).parent / "Mods"
    mods.mkdir(parents=True, exist_ok=True)
    out = ROOT / "bridge" / "SlimeBridge" / "bin" / "Release" / "SlimeBridge.dll"
    out.parent.mkdir(parents=True, exist_ok=True)
    srcs = [ROOT / "bridge" / "SlimeBridge" / name for name in ("GameState.cs", "Plugin.cs", "HttpServer.cs")]
    cmd = [str(CSC), "/nologo", "/target:library", "/optimize+", f"/out:{out}"]
    for name in REF_DLLS:
        dll = managed / name
        if not dll.exists():
            raise SystemExit(f"游戏里缺少 {dll}")
        cmd.append(f"/r:{dll}")
    cmd.extend(str(p) for p in srcs)
    subprocess.check_call(cmd)
    dest = mods / "SlimeBridge.dll"
    shutil.copy2(out, dest)
    return dest


def main() -> None:
    print("[1/4] 复制到", DEST)
    copy_tree()
    print("[2/4] 安装 Pillow")
    venv_python = ensure_venv(find_python())
    game = find_game()
    print("[3/4] 写入路径")
    write_config(venv_python, game)
    print("[4/4] 编译并替换游戏 Mods\\SlimeBridge.dll")
    mod = install_mod(game)
    print("解释器", venv_python)
    print("游戏", game)
    print("mod", mod)
    print()
    print("装好了。先完全退出游戏再启动，然后重启 NEKO。")
    print("进存档后浏览器打开 http://127.0.0.1:8124/api/health ，看到 ok 才算接上。")


if __name__ == "__main__":
    main()
