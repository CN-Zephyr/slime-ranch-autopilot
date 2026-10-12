@echo off
REM 编译 SlimeBridge (UMF 游戏内桥接插件) 到 bin\Release\SlimeBridge.dll
REM 前置：装好 .NET Framework 开发包(Visual Studio 或 Build Tools)。
REM       把 史莱姆牧场游戏目录里的 参考dll(见 csproj) 放到 ..\references\ 下。
setlocal
cd /d "%~dp0"

set CONFIG=%1
if "%CONFIG%"=="" set CONFIG=Release

echo [1/2] building %CONFIG% ...
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" (
  "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" SlimeBridge.csproj /p:Configuration=%CONFIG% /t:Build /v:m
) else if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe" (
  "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe" SlimeBridge.csproj /p:Configuration=%CONFIG% /t:Build /v:m
) else (
  echo [!] 未找到 MSBuild。请安装 Visual Studio/Build Tools 后重试。
  exit /b 1
)

set DLL=bin\%CONFIG%\SlimeBridge.dll
if not exist "%DLL%" (
  echo [!] 编译失败，未生成 %DLL%
  exit /b 1
)
echo [2/2] packed: %DLL%
echo.
echo 下一步（本机实际加载方式：UnityCoreMod / SRMP.dll）：
echo  1. 完全退出《史莱姆牧场》。
echo  2. 复制 %DLL% 到 ^<游戏目录^>\Mods\SlimeBridge.dll（覆盖旧版）。
echo  3. 启动游戏进存档，控制台/日志应出现 "[SlimeBridge] HTTP server listening ..."。
echo  4. 浏览器访问 http://127.0.0.1:8124/api/health 验证存活与 features 清单。
echo  （BUILD.md 里的 UMF/.umfmod 流程为历史文档；本机 Mods\ 直载是唯一在用的通路。）
endlocal