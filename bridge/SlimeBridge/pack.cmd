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
echo 下一步（UMF 加载）：
echo  1. 用 UMF 安装器把 UMF 装进史莱姆牧场目录。
echo  2. 用 UMF 的 Mod Builder / Mod Maker 把本工程(SlimeBridge)打包成 .umfmod。
echo  3. 把生成的 .umfmod 放到 <游戏目录>\uModFramework\Mods\ 下。
echo  4. 启动游戏，控制台应输出 "[SlimeBridge] HTTP server listening ..."。
echo  5. 浏览器/浏览器访问 http://127.0.0.1:8124/api/health 验证存活。
endlocal