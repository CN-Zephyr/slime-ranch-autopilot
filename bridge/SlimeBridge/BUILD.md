# SlimeBridge 编译引导 & 踩坑清单

目标：把《史莱姆牧场》游戏内的桥接 mod(`bridge/SlimeBridge`, C#) 编译成能被 UMF 加载的
`.umfmod`，并在游戏里跑起 `http://127.0.0.1:8124`。

> ⚠️ 分两类内容：
> - **[可靠]** 网络协议、反射读资金、台账、主线程调度：与 UMF 版本无关，是我们的核心逻辑，
>   已用 Python 协议测试锁定，出错概率低。
> - **[按版本对齐]** UMF 挂载标注 / `.umfmod` 打包：随你安装的 UMF 版本变化，**必须以 UMF
>   官网 wiki + 你游戏目录里 UMF 自带的 example 为准**，本清单只给通用路径和排错思路。

---

## 一、前置条件（先打勾）
- [ ] 一台 Windows，装有 **Visual Studio 2022 Community** 或 **VS Build Tools**，安装时勾选
      “使用 .NET 的桌面开发(.NET desktop development)” 工作负载。
- [ ] 《史莱姆牧场》游戏本体（Steam）。默认路径参考 `plugin.toml` 里的 `game_exe`。
- [ ] 已用 **UMF 安装器**把 UMF 装进游戏目录（装完后游戏目录会出现 `uModFramework` 文件夹）。

## 二、拿到引用 dll（放 `bridge/references/`）
游戏是 Unity 游戏，引用 dll 都在游戏数据目录：
```
<游戏目录>\SlimeRancher_Data\Managed\
    Assembly-CSharp.dll
    UnityEngine.dll            (或拆分为 UnityEngine.CoreModule.dll 等，按实际)
    UnityEngine.CoreModule.dll
    mscorlib.dll (可选，若需对齐游戏 Mono 版本)
```
UMF 的 API dll：
```
<游戏目录>\uModFramework\Mods\UModFramework.API.dll   （或搜索 UModFramework.API.dll 所在路径）
```
把它们复制到 `bridge\references\`（没有就新建），并对照修 `SlimeBridge.csproj` 里的 `<HintPath>`。

## 三、编译（两条路二选一）
**路线 A（推荐，命令行）**
```
cd bridge/SlimeBridge
pack.cmd            # 自动找 MSBuild，编译到 bin\Release\SlimeBridge.dll
```
**路线 B（开 IDE）**
用 Visual Studio 打开 `SlimeBridge.csproj` → 解决方案生成。
> 若 IDE 提示 net47 无目标包：在“安装程序”里补装“.NET Framework 4.7.x 开发工具”。

## 四、打包成 .umfmod（关键，必须用 UMF 官方工具）
- ❌ 不要直接把 dll 改后缀名为 .umfmod。
- ✅ 用 **UMF 官方 Mod Builder / Mod Maker** 把本工程(或编译出的 SlimeBridge.dll + 元数据)打包：
  - 不同版本入口不同（有的在游戏内控制台，有的是独立工具），**以 UMF 官网 wiki + 安装包内
    说明为准**。
  - 找不到时，直接看 UMF GitHub 的示例工程仓库（参考 [UMFDev/SRCheatMenu]）怎么构建。
- 最终得到一个 `SlimeBridge.umfmod`。

## 五、部署 & 启动验证
1. 把 `SlimeBridge.umfmod` 放入 `<游戏目录>\uModFramework\Mods\`。
2. 启动游戏并进入存档。
3. 期望出现输出：`[SlimeBridge] HTTP server listening ...`。
4. 验证：
   - 浏览器访问 `http://127.0.0.1:8124/api/health` → `{"ok":true,"name":"slime_bridge"}`
   - 主目录 Python 侧：`python -m tests.test_bridge_protocol` 参考（那是用虚拟服务测 Python 端）。

## 六、常见报错对照（踩坑清单）

| 现象 | 原因 | 处理 |
|---|---|---|
| `命令 dotnet 不是内部命令` / 找不到 dotnet | 本机只有运行时没 SDK | 装 VS 并勾 .NET 桌面开发，或 Build Tools |
| 编译报“缺少引用 / 找不到类型 UnityEngine.X” | UnityEngine 引用版本/路径不对 | 用游戏本体 `Managed\` 下的 dll，改 csproj `<HintPath>` |
| `CS0246 找不到 UModFramework.API` 类型 | UModFramework.API.dll 没引用到 | 从 UMF 安装目录找到该 dll，加到引用 |
| `UMFMod` / `ModDefinition` 属性不识别 | 你的 UMF 版本标注 API 名字不同 | 打开 UMF 自带 example，改成它用的标注写法（见下） |
| 游戏加载 mod 时报 DLL 版本不兼容 | 游戏是较老的 Mono/.NET，net47 过新 | 对照 UMF 官方示例把 `TargetFramework`/引用调成游戏支持的版本 |
| HTTP 服务启动但 IP 连不上 | 防火墙 / 端口占用 | 只开 127.0.0.1 本应注意；检查 8124 是否被占 |
| 动作返回 `ok:true` 但游戏没变化 | 默认 `simulate` 策略只记账 | 设环境变量 `SLIME_BRIDGE_STRATEGY=native` 并补齐 `GameState.cs` 真实调用 |
| UMF 加载了 mod 但没有日志输出 | 挂载入口(Plugin.cs 标注)未命中 | 对齐 UMF 版本的 ModDefinition/UMFMod 标注，参考官方 example |

### 关于“挂载标注”的诚实说明
`SlimeBridge/Plugin.cs` 顶部我写的是 `[assembly: UMFMod("SlimeBridge","1.0.0",...) ]`，
这是 UMF 常见写法之一，但**你的版本可能不同**（也可能是 `[ModDefinition(...)]`、`[UMFMod(...)]` 类属性）。
如果这条标注导致编译报错或游戏不加载：
1. 打开游戏目录 `uModFramework` 里 UMF 自带的 **example mod 工程**；
2. 把它的 ModDefinition/入口脚本写法复制过来，套到 `Plugin.cs` 上即可——**核心的
   `HttpServer`/`GameFacade` 逻辑不用动**。

## 七、备选：卡在 UMF 时改用 SRML
《史莱姆牧场》社区另一主流 mod loader 是 **SRML**（针对本游戏专用）。若 UMF 装不上/不稳定，
可把本工程挂载入口从 UMF 换成 SRML 的 MonoBehaviour 写法（`SRML` 会在游戏场景里把你标注的
类当 MonoBehaviour 挂载）。`HttpServer.cs`、`GameState.cs` 直接复用，只需改一个入口文件。

## 参考
- [UMF 官网 & 安装](https://umodframework.com/)
- [UMFDev/SRCheatMenu（现成 Slime Rancher UMF mod，含 API 用法）](https://github.com/UMFDev/SRCheatMenu)
- [README 方案B（NEKO 插件侧配置）](../README.md)

[UMFDev/SRCheatMenu]: https://github.com/UMFDev/SRCheatMenu