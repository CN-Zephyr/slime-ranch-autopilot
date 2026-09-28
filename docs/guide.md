# 史莱姆牧场自动游玩 —— 用户指南

## 一、这是什么
NEKO 启动插件后，会自动进入《史莱姆牧场》并接管游玩。按键、语音、模式切换如下：

- **V 键**：全局热键，在两种模式间切换。
  - **聊天模式（默认）**：NEKO 全程自主游玩；你说话只是与 NEKO 聊天，不作指令。
  - **语音指令模式**：你说话，NEKO 执行你的下一步指令；超过设定的秒数（默认 10s）没有说话，
    NEKO 自动接管继续自主游玩。

自主游玩会持续执行四件事：
1. 建造/升级 **牧场(围栏)、鸡圈、菜园** —— 资金 > 升级费的 2 倍时才升级；
2. 探索地图、**抓捕史莱姆**回牧场养成；
3. 收集**结晶(Plort)** 并到集市售卖；
4. 有了新发现（新设施 / 新区域 / 新史莱姆）会主动推送这个消息给你。

## 二、快速验收（不用打开游戏也能验证逻辑）
核心自带 **SIM 模拟模式**，用同一套决策代码跑一遍，能看到四项要求是否都会触发。

```bat
:: 先安装依赖(可选，SIM 只需 Python 3.11+ 标准库)
setup.bat

:: 快速跑 20 轮自主游玩并退出
python run_standalone.py --ticks 20 --interval 0

:: 查看自主动作日志
notepad data\runtime\outbox.jsonl
```

看到 `[新发现]` 包含「建造/升级」「探索到了新区域」「抓捕到了新史莱姆」以及「售卖结晶」收入，
即为通过。

## 三、安装到 NEKO
1. 命令提示符进入脚本目录，运行 `setup.bat`（创建 `.venv-core` 并安装依赖）。
2. 把整个 `slime_ranch_autopilot` 文件夹复制到 NEKO 仓库的：
   ```
   plugin/plugins/slime_ranch_autopilot/
   ```
3. 启动/重启 NEKO，在 **插件管理器** 里能看到「史莱姆牧场自动游玩」
   （`auto_start=true`，正常会自动启动）。面板里有：
   - 状态（运行中 / 模式 / 阶段 / 资金 / 最新发现）
   - 启动 / 停止 按钮
   - **语音无输入接管秒数**（可改，默认 10）
   - 手动指令输入框（测试用）
4. 在 `E:\neko插件\N.E.K.O-main\plugin\plugins\` 下确认与上面路径一致。

> 若 NEKO 插件 SDK 校验入口路径，请确保 `plugin.toml` 里 `entry` 与你放入的文件夹名一致
> （默认都是 `slime_ranch_autopilot`）。

## 四、真实游玩（live 模式）前的校准
实时画面识别（截图→模板匹配/OCR→键鼠控制）对以下条件敏感，请先校准：

1. **窗口化 + 固定分辨率**：游戏设为 **窗口化** 或 **无边框 1280×720**，并固定窗口位置
   （建议左上角 0,0）。Steam 启动项可加：`SlimeRancher.exe -popupwindow -w 1280 -h 720`。
2. **模拟键鼠/OCR 权限**：用管理员运行 NEKO 与核心；安装 Tesseract 并加入 PATH。
3. **模板图片**：`core/vision.py` 的 `locate()` 依赖目标小图；请在 `data/templates/` 放入
   按钮/物体截图用于定位。
4. **切到真实控制**：在 `plugin.toml` 或 `data/runtime/config.json` 中把 `backend` 改为 `live`，
   并填对 `game_exe`、`engine_python`（指向 `.venv-core\Scripts\python.exe`）。
5. **备份存档**：`LocalLow\Monomi Park\Slime Rancher` 下的 `.sav` 建议先备份，防止误操作造成损失。

## 五、常见问题
- **V 键没反应**：核心没检测到 `pynput`。请确保用安装了依赖的解释器启动，并给 NEKO/核心管理员权限；
  也可在插件控制台直接点「切到语音指令/聊天」。
- **语音模式不说话**：`faster-whisper` 首次运行要下载模型；确认麦克风可用、`sounddevice` 已装。
- **建造一直没发生**：请确认资金 ≥ 升级费 2 倍；live 模式下资金读取依赖 OCR 定位 HUD，需校准模板。
- **插件面板启动失败**：参考 `data/runtime/` 下日志，并确认解释器路径正确。