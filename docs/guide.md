# 史莱姆牧场自动游玩 —— 用户指南

## 一、这是什么
NEKO 连接插件后，默认**观望**，不操作游戏。按键如下：

- **V 键**：在观望和自主经营之间切换。没有 `pynput` 时，Windows 上仍用系统键盘钩子。
  - **观望（默认）**：不按键、不走路、不主动说话。要猫娘看见画面，请自己打开 NEKO 的屏幕分享。
  - **自主经营**：先到结晶市场，再收食物投喂、收结晶卖掉，钱够费用两倍才建造或升级。

自主经营一轮做这些事：
1. 人在主牧场就走到结晶市场；连续两次走不到、或不在主牧场，就传到市场前。
2. 吸起地上的食物。画面没有变化就不算收进背包，也不会去围栏投。
3. 走到最近围栏，把背包里的东西投出去。
4. 吸起结晶，拿到市场投掷。卖完资金没有增加，不算卖出。
5. 建造或升级围栏、鸡圈、菜园，每种只建一次、再加一个升级件。

不跑图、不抓野生史莱姆。

## 二、快速验收（不用打开游戏也能验证逻辑）
核心自带 **SIM 模拟模式**，用同一套决策代码跑一遍。

```bat
:: 创建 .venv-core 并安装依赖（SIM 只需 Python 3.10+ 标准库）
setup.bat

:: 快速跑 20 轮自主游玩并退出（--ticks 会临时切到自主经营）
py -3 run_standalone.py --ticks 20 --interval 0 --backend sim

:: 查看自主动作日志
notepad data\runtime\outbox.jsonl
```

## 三、安装到 NEKO
在仓库根目录双击 `install.bat`，或执行：

```bat
py -3 install.py
```

脚本会：
1. 把仓库复制到旁边的 `N.E.K.O\plugin\plugins\slime_ranch_autopilot`（目录名必须是下划线）。
2. 在那份副本里建 `.venv-core` 并安装 Pillow。
3. 把 `engine_python` 和找到的 `SlimeRancher.exe` 写入副本的 `plugin.toml`。
4. 用系统 `csc.exe` 编译 `SlimeBridge.dll`，覆盖到游戏的 `Mods\SlimeBridge.dll`。

然后完全退出游戏再进存档，浏览器打开 `http://127.0.0.1:8124/api/health`，返回
`{"ok":true,"name":"slime_bridge"}` 即桥接就绪。最后重启 NEKO，在插件管理器里可看到
「史莱姆牧场自动游玩」，面板上有状态、启动/停止按钮和手动指令输入框。

> **打开 NEKO「用户插件」总开关，不会自动拉起自动化核心，也不会自动启动游戏窗口。**
> 核心只在你点面板上的「启动自动游玩」按钮时才 spawn；想让它顺带自动开游戏、进最近存档，
> 需要在 `plugin.toml` 的 `[slime_ranch]` 里把 `auto_launch_game` 显式改成 `true`（默认 `false`）。

> 若 NEKO 插件 SDK 校验入口路径，请确保 `plugin.toml` 里 `entry` 与你放入的文件夹名一致
> （默认都是 `slime_ranch_autopilot`）。

## 四、真实游玩（hybrid 模式）
推荐后端是 `hybrid`（SlimeBridge 读状态/坐标 + 真实键鼠转向走路 + 画面验证吸附）。
在 `plugin.toml` 的 `[slime_ranch]` 里：
- `backend = "hybrid"`
- `game_exe` 留空则自动在常见 Steam 目录里找游戏。
- 需要"吸附必须画面有变化才算成功"时，把 `engine_python` 指向 `.venv-core\Scripts\python.exe`。

自主经营的建造/升级走**游戏内真实 UI 购买**：走到空地块/已有设施跟前 → 等购买/升级菜单出现
→ 用真实鼠标点对应按钮 → 用设施快照+资金变化验证生效。这要求游戏里的 SlimeBridge mod 是
含 `scan_plot` / `scan_facilities` / `ui_buttons` 的新版；改过 `bridge/SlimeBridge/*.cs` 后必须
**完全退出游戏**再编译覆盖 `Mods\SlimeBridge.dll`（游戏开着时 DLL 被占用写不进去）。
结晶市场的站位是贴近投入口（橙色投掷管）正前方约 3.5m、正对投掷口。

改完 C# 桥或后端配置后重新跑 `install.bat`；游戏正在运行时覆盖 `Mods\SlimeBridge.dll` 会失败，
请先完全退出游戏。

### 4.1 mod 接口契约（NEKO 接入预留）
- 加载位：`<游戏目录>\Mods\SlimeBridge.dll`（UnityCoreMod/SRMP.dll 加载）；网络位：`127.0.0.1:8124`，
  与 `plugin.toml` 的 `[slime_ranch] bridge_port` 必须一致。
- 能力握手：插件启动核心后先读 `GET /api/health` 的 `version`/`features`；mod 缺 `ui_buttons`
  等动作时，自主经营会明确提示"更新 Mods\SlimeBridge.dll"，**不会**回退到只扣钱的魔法购买。
- 完整动作清单见 `bridge/SlimeBridge/ModInfo.txt`（含 `scan_plot`/`scan_facilities`/`ui_buttons`/
  `debug_ui` 与 payload 约定）。改 mod 后记得同步更新该文件与 `/api/health` 的 features。

## 五、常见问题
- **V 键没反应**：热键需要本机允许全局键盘钩子；也可在插件控制台点「切到自主经营」或「切到观望」。
- **吸了但没去卖**：画面没有变化时，这次不算收进背包，也不会去市场空投。
- **建造一直没发生**：资金要达到该档费用的两倍。围栏首建 225，至少要有 450。每种建筑只会再升级一次。
- **插件面板启动失败**：参考 `data\runtime` 下的日志，并确认 `engine_python` 解释器路径正确。