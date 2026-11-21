@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title EdgeMonitor 启动

echo ============================================================
echo   EdgeMonitor 启动检查
echo ============================================================
echo.

if not exist "edgemonitor.py" goto NOFILE

set "PYX="
python --version >nul 2>nul
if not errorlevel 1 set "PYX=python"
if not defined PYX goto TRYPY
goto HAVEPY

:TRYPY
py --version >nul 2>nul
if not errorlevel 1 set "PYX=py"
if not defined PYX goto NOPY

:HAVEPY
for /f "delims=" %%v in ('%PYX% --version 2^>^&1') do echo [1/3] 已检测到 %%v

%PYX% -c "import psutil" >nul 2>nul
if not errorlevel 1 goto DEPSOK
echo [2/3] 缺少 psutil 正在自动安装...
%PYX% -m pip install psutil
%PYX% -c "import psutil" >nul 2>nul
if errorlevel 1 goto PIPFAIL
echo [2/3] 依赖已就绪
goto RUN

:DEPSOK
echo [2/3] 依赖 psutil 就绪

:RUN
echo [3/3] 正在启动 EdgeMonitor...
where pythonw >nul 2>nul
if errorlevel 1 goto CONSOLE
start "" pythonw edgemonitor.py
echo.
echo 已启动 请把鼠标移到屏幕最上方边缘唤出监控条
echo 若未出现 请检查是否已有实例在运行 本程序限制单实例
timeout /t 3 >nul
exit /b 0

:CONSOLE
start "" %PYX% edgemonitor.py
echo.
echo 已用控制台方式启动 请把鼠标移到屏幕最上方边缘唤出监控条
timeout /t 3 >nul
exit /b 0

:NOFILE
echo [失败] 当前目录找不到 edgemonitor.py
echo        请确认本 bat 与 edgemonitor.py 等文件在同一目录
echo        当前目录 %cd%
pause
exit /b 1

:NOPY
echo [失败] 未检测到 Python 无法运行本程序
echo.
echo   EdgeMonitor 是 Python 程序 直接运行 bat 需要本机装有 Python 3.8 以上
echo.
echo   方案 A 推荐 无需 Python
echo     双击 build.bat 打包出 dist\EdgeMonitor.exe
echo     之后单独拷贝这个 exe 到任何 Windows 电脑都能直接用
echo.
echo   方案 B 保留 Python 方式
echo     到 https://www.python.org/downloads/ 下载安装
echo     安装时务必勾选 Add Python to PATH 然后重新运行本 bat
echo.
pause
exit /b 1

:PIPFAIL
echo [失败] psutil 安装失败 可换国内源重试
echo        %PYX% -m pip install psutil -i https://pypi.tuna.tsinghua.edu.cn/simple
pause
exit /b 1
