# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成单个免安装 exe。

用法（在项目目录下）：
    python -m PyInstaller --noconfirm --clean EdgeMonitor.spec

产物：dist\\EdgeMonitor.exe
"""

import sys

block_cipher = None

# 项目自身的三个模块需要一起打进去（它们是同目录导入，不在 site-packages 里）
analysis = Analysis(
    ["edgemonitor.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "metrics",
        "settings",
        "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明确排除大而无用的库，显著减小体积
    excludes=[
        "numpy", "pandas", "matplotlib", "scipy", "PIL",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "test", "unittest", "pydoc", "doctest",
        "email", "html", "xmlrpc", "pdb",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="EdgeMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX 容易触发杀软误报，默认关闭
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # 关键：不弹黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 若有图标，把下一行取消注释并放入 icon.ico
    # icon="icon.ico",
)
