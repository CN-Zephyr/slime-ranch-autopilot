# 史莱姆牧场自动游玩 (NEKO 插件)

让 NEKO 连接《史莱姆牧场》一代。默认是观望：不操作游戏，屏幕分享由玩家自己开。按 **V 键** 进入自主经营：先到结晶市场重置位置，然后在牧场里收食物并投喂、收结晶卖掉。资金达到下一档费用的两倍，才建造或升级围栏、鸡圈、菜园。每种建筑只建一次，再加一个升级件。

## 功能
| 需求 | 实现位置 |
| --- | --- |
| 观望 / 自主经营，V 键切换 | `core/voice.py` + `core/main_controller.py` |
| 走到或传送到结晶市场 | `core/real.py` `approach_market` + `GameState.cs` `tp_market` |
| 收食物、投进围栏、收结晶并卖出 | `core/real.py` + `GameState.cs` 的 `scan_food` / `scan_plort` |
| 建造/升级，资金达到费用两倍才动手 | `core/ranch.py` + `core/main_controller.py` |
| 新建设施时汇报 | `core/comms.py` `report_discovery` |

## 结构
```
slime_ranch_autopilot/
├── plugin.toml            # NEKO 插件清单
├── __init__.py            # NEKO 插件入口（薄壳：拉核心、同步配置、消息转发、Hosted UI）
├── plugin_check.py        # plugin.toml 契约自检（不依赖 SDK）
├── run_standalone.py      # 脱离 NEKO 独立运行核心（支持 SIM 验收 / live）
├── setup.bat              # 一键安装依赖（建 .venv-core）
├── core/                  # 自动化核心（可独立进程）
│   ├── main_controller.py # 观望 / 自主经营
│   ├── game.py            # 启动游戏 + 键鼠动作 + 指令执行器
│   ├── bridge.py          # 连游戏内 SlimeBridge
│   ├── vision.py          # 截图，用来确认吸附是否真的发生
│   ├── ranch.py           # 建造/升级决策（2 倍资金，每种建筑一次升级）
│   ├── explore.py         # 仅模拟模式还保留的区域名单
│   ├── sim.py             # SIM 后端
│   ├── voice.py           # V 键热键（pynput，否则 Windows 钩子）
│   ├── comms.py           # 进程间文件通信 + 新发现汇报去重
│   └── settings.py        # 配置加载
├── ui/panel.tsx           # Hosted UI 控制台（状态/按钮/秒数设置）
├── i18n/zh.json           # 界面文案
├── bridge/SlimeBridge/    # 方案B：游戏内 UMF mod(史莱姆牧场侧 HTTP 服务端)
├── docs/guide.md          # 详细安装/校准/FAQ
└── tests/                 # 无依赖冒烟测试
```

## 在本机验证（无需游戏）
```bat
python run_standalone.py --ticks 20 --interval 0   :: SIM 跑 20 轮
python plugin_check.py -i                           :: 契约与异步入口自检
python -m unittest discover -s tests                :: 单元冒烟测试
```

## 依赖（仅 live 模式需要，SIM 只需 Python 3.11+ 标准库）
`core/requirements.txt`：pyautogui、opencv-python、pytesseract、pynput、sounddevice、faster-whisper 等。
跑 `setup.bat` 安装；live 模式另需安装 Tesseract OCR 并加入 PATH。

> 注意事项：真实实时画面识别对「窗口化固定分辨率 + 固定站位」有较强前提，请按 `docs/guide.md` 校准；
> 操作前请备份存档。本项目不改动 NEKO 平台代码。

## 方案B：游戏内 SlimeBridge 桥接（推荐）

不再靠截图猜资金，而是让 NEKO 插件直接连游戏内 mod 提供的本机 HTTP 服务，读取**真实资金/设施状态**并下发动作。

```
NEKO 插件(ws backend) ──HTTP/JSON──▶ 游戏内 SlimeBridge(UMF mod) ──▶ 史莱姆牧场
   [core/bridge.py]                 [bridge/SlimeBridge/]          (读/改游戏内部)
```

### 1) 编译 SlimeBridge（需一台装有 Visual Studio / Build Tools 的电脑）
1. 建目录 `bridge/references/`，把以下 dll 从史莱姆牧场安装目录拷进去：
   `Assembly-CSharp.dll`、`UnityEngine.dll`、`UnityEngine.CoreModule.dll`、`UModFramework.API.dll`（UMF 装好后就会出现在游戏目录）。
2. 双击/命令行执行 `bridge\SlimeBridge\pack.cmd`（或直接用 VS 打开 `SlimeBridge.csproj` 生成）。
3. 若编译报缺少引用，把实际 dll 调整进 `SlimeBridge.csproj` 的 `<HintPath>`。

### 2) 安装到游戏
1. 用 UMF 安装器把 UMF 装进史莱姆牧场目录。
2. 用 UMF 的 Mod Builder 把本工程打包成 `.umfmod`，放进 `<游戏目录>\uModFramework\Mods\`。
3. 启动游戏进入存档，控制台应输出 `[SlimeBridge] HTTP server listening ...`；浏览器访问
   `http://127.0.0.1:8124/api/health` 应返回 `{"ok":true,...}`。

### 3) NEKO 插件侧配置
`plugin.toml` / 插件管理页里：
```toml
[slime_ranch]
backend = "ws"      # 切换为桥接模式
bridge_host = "127.0.0.1"
bridge_port = 8124
```
> 动作策略：SlimeBridge 默认用 `simulate`（台账记录成功动作，最稳、可演示）；
> 要真正在游戏内执行建造/喂食/收集，把环境变量 `SLIME_BRIDGE_STRATEGY=native` 设给游戏进程，
> 并在 `bridge/SlimeBridge/GameState.cs` 的 `ExecuteAction` native 分支里按你游戏版本的 API 填真实调用。

### 4) 无游戏时验证桥接协议
`python -m tests.test_bridge_protocol`（用标准库虚拟 SlimeBridge 跑一遍读状态/动作）。