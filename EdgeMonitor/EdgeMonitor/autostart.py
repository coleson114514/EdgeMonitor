"""EdgeMonitor 开机自启动管理。

实现方式：写入当前用户的注册表启动项（无需管理员权限）

    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
    值名：EdgeMonitor
    数值：启动命令

同时兼容两种运行形态：
- 打包后的 exe（PyInstaller frozen）：直接注册 exe 自身路径
- 源码运行（pythonw edgemonitor.py）：注册 pythonw.exe + 脚本路径

所有函数在非 Windows 环境或注册表读写失败时都不会抛异常，
而是返回带 ok=False 与说明文字的结果，保证配置页不会崩溃。
"""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "EdgeMonitor"

try:  # winreg 仅 Windows 可用
    import winreg
except Exception:  # pragma: no cover
    winreg = None

IS_WINDOWS = sys.platform.startswith("win")


# --------------------------------------------------------------------------- #
# 启动命令
# --------------------------------------------------------------------------- #
def _script_path() -> str:
    """当前程序的主脚本绝对路径（兼容 -m / 相对路径调用）。"""
    try:
        return os.path.abspath(sys.argv[0])
    except Exception:
        return ""


def _pythonw() -> str:
    """优先使用 pythonw.exe，避免开机时弹出黑色控制台窗口。"""
    exe = sys.executable or ""
    if not exe:
        return "pythonw.exe"
    base = os.path.basename(exe).lower()
    if base.startswith("pythonw"):
        return exe
    candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(candidate):
        return candidate
    return exe


def expected_command() -> str:
    """按当前运行形态推导应写入注册表的启动命令。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = _script_path()
    if not script:
        return ""
    return f'"{_pythonw()}" "{script}"'


def _quote_exe(path: str) -> str:
    return f'"{path}"' if path else ""


# --------------------------------------------------------------------------- #
# 注册表读写
# --------------------------------------------------------------------------- #
def read_command():
    """读取已登记的启动命令；未登记返回 None。"""
    if not (IS_WINDOWS and winreg):
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _type = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError:
        return None


def is_enabled() -> bool:
    return read_command() is not None


def enable():
    """写入开机自启动，返回 (ok, message)。"""
    if not IS_WINDOWS:
        return False, "当前系统不是 Windows，无法设置注册表启动项。"
    if not winreg:
        return False, "当前 Python 环境缺少 winreg 模块，无法设置自启动。"
    command = expected_command()
    if not command:
        return False, "无法确定程序路径，请使用 exe 或绝对路径启动后再设置。"
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        return True, f"已设为开机自启动：{command}"
    except OSError as exc:
        return False, f"写入启动项失败：{exc}"


def disable():
    """移除开机自启动，返回 (ok, message)。"""
    if not IS_WINDOWS:
        return False, "当前系统不是 Windows，无法修改注册表启动项。"
    if not winreg:
        return False, "当前 Python 环境缺少 winreg 模块，无法修改自启动。"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True, "已取消开机自启动。"
    except FileNotFoundError:
        return True, "原本就未开启开机自启动。"
    except OSError as exc:
        return False, f"删除启动项失败：{exc}"


# --------------------------------------------------------------------------- #
# 状态汇总（供配置页显示）
# --------------------------------------------------------------------------- #
def status() -> dict:
    """返回 {ok, enabled, command, stale, message}。

    stale=True 表示注册表里的路径与当前程序位置不一致
    （通常是 exe 被移动过），开机时会启动失败，需要重新设置一次。
    """
    info = {
        "ok": IS_WINDOWS and winreg is not None,
        "enabled": False,
        "command": "",
        "stale": False,
        "message": "",
    }
    if not IS_WINDOWS:
        info["message"] = "非 Windows 系统，自启动功能不可用。"
        return info
    if not winreg:
        info["message"] = "当前环境缺少 winreg，自启动功能不可用。"
        return info

    current = read_command()
    if current is None:
        info["message"] = "当前未开启，开机后需手动启动。"
        return info

    info["enabled"] = True
    info["command"] = current
    info["message"] = f"已开启：{current}"

    # 校验路径是否仍指向本机存在的程序
    stale = False
    paths = [p.strip('"') for p in str(current).split('" "')]
    if len(paths) == 1:
        paths = [str(current).strip('"')]
    exe_path = paths[0].strip('"')
    if not os.path.exists(exe_path):
        stale = True
    else:
        for extra in paths[1:]:
            target = extra.strip('"')
            if target and not os.path.exists(target):
                stale = True
                break
    if stale:
        info["stale"] = True
        info["message"] = "启动项指向的路径已失效（程序可能被移动过），请重新开启一次。"
    return info
