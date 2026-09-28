using UnityEngine;
using UnityCoreMod;
using SlimeBridge;

// UnityCoreMod 挂载入口（SRMP standalone 同款加载框架）。
// 加载器把 Mods 目录下实现 IUnityMod 的 dll 加载进游戏，调用 Load()。
// Load() 里创建挂 MonoBehaviour 的 GameObject，Awake 即桥接服务入口。
namespace SlimeBridge
{
    public class Main : IUnityMod
    {
        private static GameObject _root;

        public void Load()
        {
            try
            {
                if (_root != null) return;
                _root = new GameObject("SlimeBridge");
                _root.AddComponent<SlimeBridgeBehaviour>();
                Object.DontDestroyOnLoad(_root);
                UMFLog.Log("[SlimeBridge] UnityCoreMod Load() done");
            }
            catch (System.Exception e)
            {
                UMFLog.Log("[SlimeBridge] Load error: " + e);
            }
        }

        public void Unload()
        {
            if (_root != null)
            {
                Object.Destroy(_root);
                _root = null;
            }
        }
    }

    public class SlimeBridgeBehaviour : MonoBehaviour
    {
        private static SlimeBridgeServer _server;
        private static GameFacade _facade;

        private void Awake()
        {
            try
            {
                UMFLog.Log("[SlimeBridge] Awake, starting HTTP bridge...");
                string strategy = GetStrategyFromConfig();
                _facade = new GameFacade(strategy);
                _server = new SlimeBridgeServer(SlimeBridgeServer.DefaultPort) { Facade = _facade };
                _server.Start();
                UMFLog.Log("[SlimeBridge] HTTP server started, port " + SlimeBridgeServer.DefaultPort);
            }
            catch (System.Exception e)
            {
                UMFLog.Log("[SlimeBridge] Awake error: " + e);
            }
        }

        private void Update()
        {
            // 让 HTTP 线程的动作安全地在 Unity 主线程执行
            if (_facade != null)
                _facade.FlushMainThreadQueue();
        }

        private static Font _overlayFont;   // 支持中文的系统字体（懒加载并缓存）
        private static string _overlayFontName = "";   // 实际选中的字体名（诊断用）

        // Unity 默认 IMGUI 字体不含中文字形，中文会渲染成乱码/方块。
        // 从操作系统已安装字体里挑一个支持中文的，动态生成动态字体。
        private static Font GetOverlayFont()
        {
            if (_overlayFont != null) return _overlayFont;
            try
            {
                string[] wanted = { "Microsoft YaHei", "Microsoft YaHei UI", "SimHei", "SimSun",
                                    "Microsoft JhengHei", "Noto Sans CJK SC", "Source Han Sans SC",
                                    "WenQuanYi Micro Hei" };
                string[] installed = Font.GetOSInstalledFontNames();
                foreach (string w in wanted)
                {
                    foreach (string i in installed)
                    {
                        // 注册表字体名可能带后缀（如 "Microsoft YaHei (TrueType)"），用包含匹配
                        if (i.IndexOf(w, System.StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            _overlayFont = Font.CreateDynamicFontFromOSFont(i, 26);
                            if (_overlayFont != null)
                            {
                                _overlayFontName = w + " <- " + i;
                                return _overlayFont;
                            }
                        }
                    }
                }
            }
            catch (System.Exception) { }
            _overlayFont = GUI.skin.label.font;   // 兜底：找不到中文字体时退回默认
            _overlayFontName = "DEFAULT(" + GUI.skin.label.font.name + ")";
            return _overlayFont;
        }

        // 诊断：GetOverlayFont 选中了什么字体（供 core debug_font 动作查询）
        public static string FontDiagnostics()
        {
            try
            {
                string[] installed = Font.GetOSInstalledFontNames();
                var sb = new System.Text.StringBuilder();
                sb.Append("picked=").Append(_overlayFontName).Append("; installedCount=")
                  .Append(installed.Length).Append("; names=");
                int n = 0;
                foreach (string s in installed)
                {
                    if (++n > 60) { sb.Append("..."); break; }
                    sb.Append(s).Append(", ");
                }
                return sb.ToString();
            }
            catch (System.Exception e)
            {
                return "FontDiagnostics ERR: " + e.Message;
            }
        }

        private void OnGUI()
        {
            // 屏幕左上角叠加层：显示 NEKO 自动游玩状态（core 通过 set_overlay 推送）
            try
            {
                string text = GameFacade.OverlayText;
                if (string.IsNullOrEmpty(text)) return;
                var style = new GUIStyle(GUI.skin.label);
                style.font = GetOverlayFont();
                style.fontSize = 26;
                style.fontStyle = FontStyle.Bold;
                style.normal.textColor = new Color(0.15f, 1f, 0.35f);
                GUIStyle shadow = new GUIStyle(style);
                shadow.normal.textColor = Color.black;
                GUI.Label(new Rect(9, 9, 1000, 60), text, shadow);   // 黑色描边，保证任意背景可读
                GUI.Label(new Rect(10, 10, 1000, 60), text, style);
            }
            catch (System.Exception) { }
        }

        private void OnDestroy()
        {
            if (_server != null) _server.Stop();
        }

        // 策略：可从环境变量 SLIME_BRIDGE_STRATEGY 取，缺省 native。
        private static string GetStrategyFromConfig()
        {
            try
            {
                string env = System.Environment.GetEnvironmentVariable("SLIME_BRIDGE_STRATEGY");
                if (!string.IsNullOrEmpty(env)) return env.ToLowerInvariant();
            }
            catch (System.Exception) { }
            return "native";
        }
    }
}
