# 史莱姆牧场自动游玩 设计说明 (DESIGN.md)

## Identity Lock
- plugin_id: `slime_ranch_autopilot`
- folder: `slime_ranch_autopilot/`
- name: 史莱姆牧场自动游玩
- entry: `plugin.plugins.slime_ranch_autopilot:SlimeRanchAutopilotPlugin`
- main class: `SlimeRanchAutopilotPlugin`
- package type: `plugin`（独立功能插件）

## Purpose
NEKO 启动后自动进入史莱姆牧场游戏并接管游玩。玩家可按 **V 键** 切换：
- **聊天模式（默认）**：NEKO 全程自主游玩，玩家语音仅与 NEKO 对话，不作为指令。
- **语音指令模式**：玩家用语音下达下一步指令，NEKO 执行；超过可配置秒数（默认 10s）未说话，NEKO 自主接管。

## 自主游玩目标（对应需求）
1. 建造升级基础设施：牧场(围栏 Corral)、鸡圈(Coop)、菜园(Garden)，资金 > 升级费用 2 倍时升级。
2. 探索地图并抓捕史莱姆带回牧场养成。
3. 收集结晶(Plort) 并在集市(Plort Market)售卖。
4. 有新发现（新史莱姆/新区域/建了新设施）时主动推送消息给玩家。

## Package Type and Capabilities
- package type: plugin
- capabilities:
  - `@lifecycle(startup)`：创建数据目录、同步配置、生成独立自动化核心进程。
  - `@plugin_entry`：start_autopilot / stop_autopilot / set_timeout / set_mode / push_command。
  - `@message`：接收聊天消息（聊天模式中仅做对话上下文，不当作指令）。
  - Hosted UI：`@ui.context(dashboard)` 状态面板 + 模拟核心提供的动作按钮。
  - 独立核心子进程：state.json / outbox.jsonl / command.json / config.json 四类文件通信。
- inferred architecture：
  NEKO 插件进程（薄壳）+ 独立 Python 自动化核心子进程（重逻辑）。两者之间用文件握手，
  避免在 NEKO 主进程中加载 pyautogui/opencv/whisper 等重型依赖、阻塞事件循环。

## First Version Scope
- 自动化核心（`core/`）：状态机控制器、感知层、执行层、语音热键层、模拟层。
- NEKO 集成：插件入口、状态/动作、Hosted UI 面板、配置同步。
- 独立启动器 `run_standalone.py`（可脱离 NEKO 单独运行/测试核心）。
- 模拟模式（SIM）：无需真实游戏画面，复现四项自主游玩要求并输出日志，用于验收。
- 冒烟测试 + 安装脚本。

## Out of Scope
- 不修复/改动 NEKO 平台代码（`plugin.sdk.shared` 等）——不越界。
- 不强行保证 3D 实景 CV 的高可靠性（对固定窗口、分辨率、站位有前提，见 README 校准节）。
- 不做杂交体 Largo / Tarr 复杂混养策略（留存后续版本）。

## Inferred Technical Needs
- plugin.toml sections: `[plugin]`, `[plugin_runtime]`, `[plugin.store]`, `[plugin.i18n]`,
  `[plugin.ui]` + `[[plugin.ui.panel]]`, 自定义 `[slime_ranch]`。
- SDK surfaces: `NekoPluginBase`, `neko_plugin`, `plugin_entry`, `lifecycle`, `message`,
  `ui.context`, `ui.action`, `Ok`, `Err`, `tr`, `self.config`, `self.data_path`, `push_message`,
  `self.logger`, `self.store`。
- UI surfaces: 一个 Hosted TSX 控制台面板 `ui/panel.tsx` + `docs/guide.md`。
- state/config: `[slime_ranch]` 节 + config.json(核心) 双向同步。
- lifecycle/background work: startup 生成子进程；shutdown 关闭子进程。
- external integrations: 自动化核心(独立进程) + faster-whisper(语音) + pyautogui/pynput/opencv(控制)。

## Write Workspace
`slime_ranch_autopilot/`

## Risk Follow-ups
- NEKO 插件 SDK 在 `plugin/` 目录，本机因源码包截断未取得，入口按官方契约手写、
  用独立核心+模拟模式做功能验收；真实 NEKO 加载需用户放入 `plugin/plugins/<id>/` 后确认。
- 真实游戏实时 CV 控制对窗口位置/分辨率/站位有前提，需按 README 校准。