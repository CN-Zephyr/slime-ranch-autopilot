@echo off
REM ===== 史莱姆牧场自动游玩 - 依赖一键安装 =====
REM 用法：右键“以管理员身份运行”，或在此目录命令行执行 setup.bat
echo 开始为自动化核心创建虚拟环境与安装依赖...
cd /d "%~dp0"

set PYTHON=python
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装 Python 3.10+ 并勾选 "Add to PATH"
  pause
  exit /b 1
)

%PYTHON% -m venv .venv-core
call .venv-core\Scripts\activate.bat

echo 安装核心依赖（PyAutoGUI/OpenCV/pynput/whisper 等）...
pip install --upgrade pip
pip install -r core\requirements.txt

echo.
echo 安装完成！
echo 注意：
echo   1. 真实游戏画面识别需要额外安装 Tesseract OCR（https://github.com/UB-Mannheim/tesseract）并加入 PATH。
echo   2. faster-whisper 首次运行会自动下载 small 模型（约 500MB）。
echo   3. 若只想验收逻辑，可直接运行： .venv-core\Scripts\python run_standalone.py --ticks 20
pause