@echo off
chcp 936 >nul
setlocal
title EdgeMonitor 打包
cd /d "%~dp0"

echo ============================================================
echo   EdgeMonitor 单文件打包
echo   产物 dist\EdgeMonitor.exe 免安装 双击即用
echo ============================================================
echo.

echo [1/5] 检查 Python 环境...
python --version >nul 2>nul
if errorlevel 1 goto NOPY
python --version
goto DEPS

:NOPY
echo.
echo [失败] 未找到 python 命令
echo        请安装 Python 3.8 以上版本 安装时务必勾选 Add Python to PATH
echo        下载地址 https://www.python.org/downloads/
echo.
pause
exit /b 1

:DEPS
echo.
echo [2/5] 检查并安装依赖...
python -c "import psutil" >nul 2>nul
if errorlevel 1 python -m pip install psutil
python -m PyInstaller --version >nul 2>nul
if errorlevel 1 python -m pip install pyinstaller
python -c "import psutil" >nul 2>nul
if errorlevel 1 goto PIPFAIL
python -m PyInstaller --version >nul 2>nul
if errorlevel 1 goto PIPFAIL
echo 依赖就绪

echo.
echo [3/5] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [4/5] 开始打包 约 1 到 3 分钟 请勿关闭窗口...
if exist EdgeMonitor.spec goto SPEC
python -m PyInstaller --noconfirm --clean --onefile --windowed --name EdgeMonitor --hidden-import psutil edgemonitor.py
goto CHECK

:SPEC
python -m PyInstaller --noconfirm --clean EdgeMonitor.spec

:CHECK
if not exist "dist\EdgeMonitor.exe" goto BUILDFAIL
echo.
echo ============================================================
echo   打包成功
echo   文件位置 %cd%\dist\EdgeMonitor.exe
echo ------------------------------------------------------------
echo   使用方法
echo     1 把 EdgeMonitor.exe 复制到固定目录 例如 D:\Tools\
echo     2 右键 exe 发送到 桌面快捷方式
echo     3 双击运行 鼠标贴到屏幕最上方边缘唤出监控条
echo   提示 单文件 exe 首次启动需解压 约 1 到 3 秒 属正常现象
echo ============================================================
echo.
set "OPEN="
set /p OPEN=输入 Y 回车打开 dist 文件夹 直接回车跳过: 
if /i "%OPEN%"=="Y" explorer "dist"
echo.
pause
exit /b 0

:BUILDFAIL
echo.
echo [失败] 未生成 dist\EdgeMonitor.exe 请把上方错误信息复制下来排查
echo.
pause
exit /b 1

:PIPFAIL
echo.
echo [失败] 依赖安装失败 可换国内源重试
echo        python -m pip install psutil pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1
