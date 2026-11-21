"""EdgeMonitor 配置文件读写。

配置文件位置：%APPDATA%\\EdgeMonitor\\config.json
（若环境没有 APPDATA，则退回到脚本同目录下的 config.json）
"""

from __future__ import annotations

import json
import os
import re

APP_NAME = "EdgeMonitor"

DEFAULT_CONFIG = {
    # 触发与动画
    "trigger_px": 3,          # 鼠标距屏幕顶部多少像素内触发展开
    "refresh_ms": 1000,       # 数据刷新间隔（毫秒）
    "hide_delay_ms": 700,     # 鼠标离开后多久自动隐藏（毫秒）
    "anim_ms": 150,           # 滑出 / 收起动画时长（毫秒）
    "poll_ms": 50,            # 鼠标位置轮询间隔（毫秒）
    # 外观
    "card_width": 168,        # 单张信息卡宽度（px，逻辑像素）
    "height": 88,             # 卡片高度（px）
    "gap": 8,                 # 卡片间距（px）
    "pad": 10,                # 面板内边距（px）
    "opacity": 0.95,          # 面板不透明度 0.3 - 1.0
    "bg_color": "#15181F",    # 面板背景色
    "x_offset": 0,            # 水平偏移（相对屏幕居中位置，px）
    # 显示哪些卡片
    "show": {
        "cpu": True,
        "mem": True,
        "gpu": True,
        "gpu_name": True,
        "net": True,
    },
}

NUMERIC_RANGES = {
    "trigger_px": (0, 300),
    "refresh_ms": (200, 10000),
    "hide_delay_ms": (0, 10000),
    "anim_ms": (0, 800),
    "poll_ms": (20, 500),
    "card_width": (100, 400),
    "height": (56, 200),
    "gap": (0, 40),
    "pad": (0, 40),
    "opacity": (0.3, 1.0),
    "x_offset": (-10000, 10000),
}

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def normalize_color(value, fallback: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("#"):
        text = "#" + text
    return text.lower() if _COLOR_RE.match(text) else fallback


def coerce(key: str, raw):
    """把界面输入转成合法值，非法时抛 ValueError。"""
    lo, hi = NUMERIC_RANGES.get(key, (None, None))
    text = str(raw).strip().replace("，", ".").replace(",", ".")
    if not text:
        raise ValueError(f"{key} 不能为空")
    value = float(text)
    if lo is not None:
        value = max(lo, min(hi, value))
    if isinstance(DEFAULT_CONFIG.get(key), int):
        value = int(round(value))
    return value


def _merge(base: dict, incoming: dict) -> dict:
    merged = json.loads(json.dumps(base))
    for key, value in (incoming or {}).items():
        if key == "show" and isinstance(value, dict):
            for sub, flag in value.items():
                if sub in merged["show"]:
                    merged["show"][sub] = bool(flag)
        elif key in merged:
            merged[key] = value
    # 类型与范围校正
    for key, (lo, hi) in NUMERIC_RANGES.items():
        try:
            value = coerce(key, merged.get(key, DEFAULT_CONFIG[key]))
        except Exception:
            value = DEFAULT_CONFIG[key]
        merged[key] = max(lo, min(hi, value))
    merged["bg_color"] = normalize_color(merged.get("bg_color"), DEFAULT_CONFIG["bg_color"])
    return merged


def load() -> dict:
    path = config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return _merge(DEFAULT_CONFIG, json.load(fh))
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save(cfg: dict) -> str:
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = _merge(DEFAULT_CONFIG, cfg)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path
