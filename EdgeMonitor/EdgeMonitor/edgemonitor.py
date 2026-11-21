"""EdgeMonitor —— Windows 屏幕顶部边缘悬浮系统监控条

功能
----
1. 鼠标移动到屏幕“正上方边缘”时，监控条从顶部滑出；
2. 鼠标离开监控条且不在顶部边缘时，延时自动隐藏；
3. 显示 CPU / 内存 / GPU / 显卡 / 网络 实时信息；
4. 独立配置页面（齿轮按钮、右键菜单均可打开），修改后立即生效并写入配置；
5. 在监控条上按住左键可左右拖动，位置自动记忆。

运行：python edgemonitor.py
仅打开配置页：python edgemonitor.py --settings
"""

from __future__ import annotations

import ctypes
import sys
import time
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, messagebox, ttk

import autostart
import metrics
import settings

APP_NAME = "EdgeMonitor"
VERSION = "1.0.0"

CARD_ORDER = ["cpu", "mem", "gpu", "gpu_name", "net"]
CARD_LABEL = {"cpu": "CPU", "mem": "内存", "gpu": "GPU", "gpu_name": "显卡", "net": "网络"}
CARD_ACCENT = {
    "cpu": "#4FC3F7",
    "mem": "#81C784",
    "gpu": "#FFB74D",
    "gpu_name": "#9FAECD",
    "net": "#BA68C8",
}
TEXT_MAIN = "#E6EAF2"
TEXT_SUB = "#8B95A8"
TEXT_DIM = "#7C8798"
WARN_COLOR = "#FFB74D"
HIGH_COLOR = "#EF5350"


# --------------------------------------------------------------------------- #
# Windows 平台辅助（DPI、鼠标、屏幕尺寸、单实例）
# --------------------------------------------------------------------------- #
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def enable_dpi_awareness():
    """让程序使用物理像素，避免高分屏下字体发虚、位置偏移。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def dpi_scale() -> float:
    try:
        get_dpi = ctypes.windll.user32.GetDpiForSystem
        return max(0.75, min(4.0, float(get_dpi()) / 96.0))
    except Exception:
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return max(0.75, min(4.0, float(dpi) / 96.0))
    except Exception:
        return 1.0


def primary_size():
    try:
        return (
            int(ctypes.windll.user32.GetSystemMetrics(0)),
            int(ctypes.windll.user32.GetSystemMetrics(1)),
        )
    except Exception:
        return (1920, 1080)


def cursor_pos():
    try:
        pt = _POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)
    except Exception:
        return (-1, -1)


def single_instance_mutex():
    """返回 (handle, already_running)。"""
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\EdgeMonitorTopBarMutex")
        already = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        return handle, already
    except Exception:
        return None, False


def alert(text: str, title: str = APP_NAME):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:
        print(text)


def shade(hex_color: str, factor: float) -> str:
    """把颜色按比例变亮（factor>1）或变暗（factor<1）。"""
    try:
        text = hex_color.lstrip("#")
        r, g, b = (int(text[i : i + 2], 16) for i in (0, 2, 4))
        if factor >= 1:
            r = int(r + (255 - r) * (factor - 1))
            g = int(g + (255 - g) * (factor - 1))
            b = int(b + (255 - b) * (factor - 1))
        else:
            r, g, b = int(r * factor), int(g * factor), int(b * factor)
        clamp = lambda v: max(0, min(255, v))
        return "#{:02x}{:02x}{:02x}".format(clamp(r), clamp(g), clamp(b))
    except Exception:
        return hex_color


# --------------------------------------------------------------------------- #
# 悬浮监控条
# --------------------------------------------------------------------------- #
class TopBar:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot: dict = {}
        self._settings_win = None
        self._anim_job = None
        self._render_job = None
        self._target_show = False
        self._cur_y = 0.0
        self._hide_at = None
        self._drag = None
        self._font_cache: dict = {}

        self._scale = dpi_scale()
        self._screen_w, self._screen_h = primary_size()

        self.monitor = metrics.Monitor()  # 后台启动显卡信息线程

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.title(APP_NAME)

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label=f"配置…（{APP_NAME} {VERSION}）", command=self.open_settings)
        self.menu.add_command(label="立即刷新数据", command=self._refresh_now)
        self.menu.add_separator()
        self.menu.add_command(label="隐藏", command=self._hide)
        self.menu.add_command(label="退出", command=self.quit)

        self.canvas.bind("<Button-3>", self._popup_menu)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self._rebuild()
        self.root.deiconify()
        self.root.update_idletasks()
        self._cur_y = float(-(self._win_h + 8))
        self._place()

        self._sample_thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._sample_thread.start()

        self._render_loop()
        self.root.after(max(20, int(self.cfg["poll_ms"])), self._poll)

    # ------------------------------------------------------------------ #
    # 采样
    # ------------------------------------------------------------------ #
    def _sample_loop(self):
        while not self._stop.is_set():
            try:
                snap = self.monitor.sample()
                with self._lock:
                    self._snapshot = snap
            except Exception:
                pass
            interval = max(0.2, float(self.cfg.get("refresh_ms", 1000)) / 1000.0)
            self._stop.wait(interval)

    def _snapshot_copy(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    def _refresh_now(self):
        def work():
            try:
                snap = self.monitor.sample()
                with self._lock:
                    self._snapshot = snap
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ #
    # 布局与绘制
    # ------------------------------------------------------------------ #
    def _rebuild(self):
        cfg, s = self.cfg, self._scale
        keys = [k for k in CARD_ORDER if cfg["show"].get(k, True)]
        self.keys = keys

        pad = int(round(cfg["pad"] * s))
        gap = int(round(cfg["gap"] * s))
        cw = int(round(cfg["card_width"] * s))
        ch = int(round(cfg["height"] * s))
        btn = int(round(22 * s))
        ctrl_w = btn + int(round(6 * s))

        n = len(keys)
        cards_w = n * cw + max(0, n - 1) * gap
        W = max(int(120 * s), pad * 2 + cards_w + int(round(8 * s)) + ctrl_w)
        H = ch + pad * 2

        self._win_w, self._win_h = W, H
        center = (self._screen_w - W) // 2 + int(round(cfg["x_offset"] * s))
        min_visible = int(80 * s)
        self._win_x = max(min_visible - W, min(center, self._screen_w - min_visible))

        bg = cfg["bg_color"]
        self.canvas.delete("all")
        self.canvas.configure(bg=bg, width=W, height=H)
        self.root.configure(bg=bg)
        try:
            self.root.attributes("-alpha", float(cfg["opacity"]))
        except Exception:
            pass

        # 顶部一条细高光，增强“贴边”观感
        self.canvas.create_line(0, 0, W, 0, fill=shade(bg, 1.9), width=max(1, int(s)))

        self.cards = {}
        x = pad
        for key in keys:
            self.cards[key] = self._create_card(key, x, pad, cw, ch, s)
            x += cw + gap

        # 右侧按钮：齿轮 / 关闭
        bx = W - pad - ctrl_w // 2
        self._create_icon_button("⚙", bx, H // 2 - btn // 2 - int(4 * s), s, self.open_settings)
        self._create_icon_button("✕", bx, H // 2 + btn // 2 + int(4 * s), s, self.quit)
        self._place()

    def _create_icon_button(self, text, cx, cy, s, command):
        item = self.canvas.create_text(
            cx, cy, text=text, fill=TEXT_DIM, font=("Segoe UI Symbol", -int(14 * s)),
            tags=("iconbtn",),
        )
        self.canvas.tag_bind(item, "<Button-1>", lambda _e: command())
        self.canvas.tag_bind(item, "<Enter>", lambda _e: self.canvas.itemconfigure(item, fill=TEXT_MAIN))
        self.canvas.tag_bind(item, "<Leave>", lambda _e: self.canvas.itemconfigure(item, fill=TEXT_DIM))

    def _font(self, family, size_px, weight="normal"):
        key = (family, size_px, weight)
        if key not in self._font_cache:
            self._font_cache[key] = tkfont.Font(family=family, size=-abs(size_px), weight=weight)
        return self._font_cache[key]

    @staticmethod
    def _round_points(x1, y1, x2, y2, r):
        r = max(0, min(int(r), (x2 - x1) // 2, (y2 - y1) // 2))
        return [
            x1 + r, y1, x2 - r, y1, x2, y1,
            x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2,
            x1, y2 - r, x1, y1 + r, x1, y1,
        ]

    def _round_rect(self, x1, y1, x2, y2, r, fill, tags=()):
        return self.canvas.create_polygon(
            self._round_points(x1, y1, x2, y2, r),
            smooth=True, splinesteps=24, fill=fill, outline="", tags=tags,
        )

    def _create_card(self, key, x, y, w, h, s):
        accent = CARD_ACCENT[key]
        card_bg = shade(self.cfg["bg_color"], 1.55)
        items = {"key": key}
        items["bg"] = self._round_rect(x, y, x + w, y + h, int(9 * s), card_bg, tags=("dragzone",))

        padx = int(11 * s)
        items["label"] = self.canvas.create_text(
            x + padx, y + int(8 * s), text=CARD_LABEL[key], anchor="nw",
            fill=TEXT_SUB, font=self._font("Segoe UI", int(10 * s)),
        )
        value_size = int(12 * s) if key == "gpu_name" else int(19 * s)
        items["value"] = self.canvas.create_text(
            x + padx, y + int(22 * s), text="—", anchor="nw",
            fill=accent, font=self._font("Segoe UI Semibold", value_size, "bold"),
        )
        items["sub"] = self.canvas.create_text(
            x + padx, y + h - int(31 * s), text="", anchor="nw",
            fill=TEXT_DIM, font=self._font("Segoe UI", int(10 * s)),
        )
        items["geo"] = {"x": x, "w": w, "padx": padx, "value_y": y + int(22 * s), "h": h}

        if key in ("cpu", "mem", "gpu"):
            bar_y = y + h - int(12 * s)
            bar_h = max(3, int(4 * s))
            bx1, bx2 = x + padx, x + w - padx
            items["bar_geo"] = (bx1, bx2, bar_y, bar_h)
            items["bar_bg"] = self._round_rect(bx1, bar_y, bx2, bar_y + bar_h, bar_h // 2, "#2A303C")
            items["bar"] = self._round_rect(bx1, bar_y, bx1 + bar_h, bar_y + bar_h, bar_h // 2, accent)
        return items

    def _set_bar(self, items, ratio, color):
        if "bar" not in items:
            return
        bx1, bx2, bar_y, bar_h = items["bar_geo"]
        ratio = max(0.0, min(1.0, float(ratio)))
        width = max(bar_h, int((bx2 - bx1) * ratio))
        self.canvas.coords(items["bar"], *self._round_points(bx1, bar_y, bx1 + width, bar_y + bar_h, bar_h // 2))
        self.canvas.itemconfigure(items["bar"], fill=color)

    def _fit(self, text, font, max_width):
        text = str(text or "")
        if max_width <= 8:
            return text
        if font.measure(text) <= max_width:
            return text
        ell = "…"
        while text and font.measure(text + ell) > max_width:
            text = text[:-1]
        return (text + ell) if text else ell

    def _level_color(self, pct, accent):
        if pct >= 90:
            return HIGH_COLOR
        if pct >= 70:
            return WARN_COLOR
        return accent

    # ------------------------------------------------------------------ #
    # 渲染
    # ------------------------------------------------------------------ #
    def _render_loop(self):
        try:
            self._render()
        except Exception:
            pass
        interval = max(120, int(float(self.cfg.get("refresh_ms", 1000)) * 0.5))
        self._render_job = self.root.after(interval, self._render_loop)

    def _render(self):
        snap = self._snapshot_copy()
        if not snap:
            return
        for key, items in self.cards.items():
            data = snap.get(key)
            if not data:
                continue
            if key == "cpu":
                self._render_cpu(items, data)
            elif key == "mem":
                self._render_mem(items, data)
            elif key == "gpu":
                self._render_gpu(items, data)
            elif key == "gpu_name":
                self._render_gpu_name(items, data)
            elif key == "net":
                self._render_net(items, data)

    def _card_text_width(self, items):
        return items["geo"]["w"] - items["geo"]["padx"] * 2

    def _render_cpu(self, items, d):
        pct = float(d.get("percent", 0.0) or 0.0)
        color = self._level_color(pct, CARD_ACCENT["cpu"])
        self.canvas.itemconfigure(items["value"], text=f"{pct:.0f}%", fill=color)
        parts = []
        if d.get("freq_ghz"):
            parts.append(f"{d['freq_ghz']:.2f}GHz")
        if d.get("cores"):
            parts.append(f"{d['cores']}核{d.get('threads', '')}线程")
        sub = " · ".join(parts) if parts else "正在读取…"
        self.canvas.itemconfigure(
            items["sub"], text=self._fit(sub, self._font("Segoe UI", int(10 * self._scale)), self._card_text_width(items))
        )
        self._set_bar(items, pct / 100.0, color)

    def _render_mem(self, items, d):
        pct = float(d.get("percent", 0.0) or 0.0)
        color = self._level_color(pct, CARD_ACCENT["mem"])
        self.canvas.itemconfigure(items["value"], text=f"{pct:.0f}%", fill=color)
        if d.get("total"):
            sub = f"{metrics.human_bytes(d.get('used', 0))} / {metrics.human_bytes(d['total'])}"
        else:
            sub = "正在读取…"
        self.canvas.itemconfigure(
            items["sub"], text=self._fit(sub, self._font("Segoe UI", int(10 * self._scale)), self._card_text_width(items))
        )
        self._set_bar(items, pct / 100.0, color)

    def _render_gpu(self, items, d):
        if not d.get("ok"):
            self.canvas.itemconfigure(items["value"], text="N/A", fill=TEXT_DIM)
            self.canvas.itemconfigure(items["sub"], text="未检测到 NVIDIA GPU")
            self._set_bar(items, 0.0, TEXT_DIM)
            return
        pct = float(d.get("util", 0.0) or 0.0)
        color = self._level_color(pct, CARD_ACCENT["gpu"])
        self.canvas.itemconfigure(items["value"], text=f"{pct:.0f}%", fill=color)
        sub = f"{metrics.human_bytes(d.get('mem_used', 0))} / {metrics.human_bytes(d.get('mem_total', 0))}"
        if d.get("temp"):
            sub += f" · {float(d['temp']):.0f}°C"
        self.canvas.itemconfigure(
            items["sub"], text=self._fit(sub, self._font("Segoe UI", int(10 * self._scale)), self._card_text_width(items))
        )
        self._set_bar(items, pct / 100.0, color)

    def _render_gpu_name(self, items, d):
        name = (d.get("name") or "").strip()
        font = self._font("Segoe UI Semibold", int(12 * self._scale), "bold")
        if not name:
            self.canvas.itemconfigure(items["value"], text="检测中…", fill=TEXT_DIM)
            self.canvas.itemconfigure(items["sub"], text="读取显卡信息")
            return
        self.canvas.itemconfigure(
            items["value"], text=self._fit(name, font, self._card_text_width(items)), fill=CARD_ACCENT["gpu_name"]
        )
        parts = [p for p in (d.get("driver"), d.get("memory")) if p]
        self.canvas.itemconfigure(
            items["sub"],
            text=self._fit(" · ".join(parts) if parts else "驱动信息未知",
                           self._font("Segoe UI", int(10 * self._scale)), self._card_text_width(items)),
        )

    def _render_net(self, items, d):
        down = float(d.get("down", 0.0) or 0.0)
        up = float(d.get("up", 0.0) or 0.0)
        self.canvas.itemconfigure(items["value"], text=f"↓ {metrics.human_speed(down)}", fill=CARD_ACCENT["net"])
        sub = f"↑ {metrics.human_speed(up)}"
        if d.get("ip") and d["ip"] != "—":
            sub += f" · {d['ip']}"
        self.canvas.itemconfigure(
            items["sub"], text=self._fit(sub, self._font("Segoe UI", int(10 * self._scale)), self._card_text_width(items))
        )

    # ------------------------------------------------------------------ #
    # 位置 / 动画
    # ------------------------------------------------------------------ #
    def _place(self):
        try:
            self.root.geometry(f"{self._win_w}x{self._win_h}+{int(self._win_x)}+{int(self._cur_y)}")
        except Exception:
            pass

    def _hidden_y(self):
        return float(-(self._win_h + 8))

    def _animate_to(self, show: bool):
        self._target_show = show
        if self._anim_job:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None
        duration = max(0, int(self.cfg.get("anim_ms", 150)))
        start, end = self._cur_y, (0.0 if show else self._hidden_y())
        if duration <= 0:
            self._cur_y = end
            self._place()
            return
        frame_ms = 16
        frames = max(1, duration // frame_ms)
        step = (end - start) / frames

        def tick(remain):
            if remain <= 0:
                self._cur_y = end
                self._place()
                self._anim_job = None
                return
            self._cur_y += step
            self._place()
            self._anim_job = self.root.after(frame_ms, tick, remain - 1)

        tick(frames)

    def _show(self):
        self._hide_at = None
        self._animate_to(True)

    def _hide(self):
        self._hide_at = None
        self._animate_to(False)

    # ------------------------------------------------------------------ #
    # 顶部边缘检测
    # ------------------------------------------------------------------ #
    def _poll(self):
        if self._stop.is_set():
            return
        try:
            px, py = cursor_pos()
            s = self._scale
            trigger = max(1, int(self.cfg.get("trigger_px", 3) * s))
            in_zone = py <= trigger and py >= -5 and 0 <= px <= self._screen_w

            in_panel = False
            if self._target_show or self._cur_y > self._hidden_y() + 1:
                top = self._cur_y
                in_panel = (
                    self._win_x <= px <= self._win_x + self._win_w
                    and top <= py <= top + self._win_h
                )

            keep = in_zone or in_panel or self._settings_open()

            if keep:
                self._hide_at = None
                if not self._target_show:
                    self._show()
            elif self._target_show:
                if self._hide_at is None:
                    self._hide_at = time.monotonic() + float(self.cfg.get("hide_delay_ms", 700)) / 1000.0
                elif time.monotonic() >= self._hide_at:
                    self._hide()
        except Exception:
            pass
        if not self._stop.is_set():
            self.root.after(max(20, int(self.cfg.get("poll_ms", 50))), self._poll)

    def _settings_open(self) -> bool:
        win = self._settings_win
        if win is None:
            return False
        try:
            return bool(win.win.winfo_exists())
        except Exception:
            self._settings_win = None
            return False

    # ------------------------------------------------------------------ #
    # 拖动 / 菜单
    # ------------------------------------------------------------------ #
    def _on_press(self, event):
        current = self.canvas.find_withtag("current")
        tags = self.canvas.gettags(current[0]) if current else ()
        if "iconbtn" in tags:
            return
        self._drag = (event.x_root, self._win_x)

    def _on_drag(self, event):
        if not self._drag:
            return
        x0, win_x0 = self._drag
        s = self._scale
        min_visible = int(80 * s)
        new_x = win_x0 + (event.x_root - x0)
        self._win_x = max(min_visible - self._win_w, min(new_x, self._screen_w - min_visible))
        self._place()

    def _on_release(self, _event):
        if not self._drag:
            return
        self._drag = None
        s = self._scale
        center = (self._screen_w - self._win_w) // 2
        self.cfg["x_offset"] = int(round((self._win_x - center) / s))
        try:
            settings.save(self.cfg)
        except Exception:
            pass

    def _popup_menu(self, event):
        try:
            self._show()
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.menu.grab_release()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # 配置页
    # ------------------------------------------------------------------ #
    def open_settings(self):
        if self._settings_open():
            try:
                self._settings_win.win.deiconify()
                self._settings_win.win.lift()
                self._settings_win.win.focus_force()
                return
            except Exception:
                self._settings_win = None
        self._show()
        self._settings_win = SettingsWindow(self)

    def close_settings(self):
        self._settings_win = None

    def apply_config(self):
        """配置变更后重新计算尺寸并重绘（保持当前显示状态）。"""
        self._rebuild()
        if self._target_show:
            self._cur_y = 0.0
        else:
            self._cur_y = self._hidden_y()
        self._place()
        self._render()

    # ------------------------------------------------------------------ #
    def run(self):
        self.root.mainloop()

    def quit(self):
        self._stop.set()
        for job in (self._anim_job, self._render_job):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        try:
            self.root.destroy()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 独立配置页面
# --------------------------------------------------------------------------- #
class SettingsWindow:
    NUMBER_FIELDS = [
        ("触发与动画", [
            ("trigger_px", "触发高度（px）", 1, "鼠标距屏幕顶部多少像素内弹出"),
            ("hide_delay_ms", "隐藏延迟（ms）", 100, "鼠标离开后多久自动收起"),
            ("refresh_ms", "刷新间隔（ms）", 100, "数据采样周期"),
            ("anim_ms", "动画时长（ms）", 20, "滑出 / 收起动画"),
            ("poll_ms", "鼠标轮询（ms）", 10, "越小越灵敏，越大越省 CPU"),
        ]),
        ("外观", [
            ("card_width", "卡片宽度（px）", 5, ""),
            ("height", "卡片高度（px）", 2, ""),
            ("gap", "卡片间距（px）", 1, ""),
            ("pad", "面板内边距（px）", 1, ""),
            ("opacity", "不透明度（0.3-1.0）", 0.01, ""),
            ("x_offset", "水平偏移（px）", 5, "0 表示屏幕居中，可直接拖动监控条"),
        ]),
    ]

    SHOW_FIELDS = [
        ("cpu", "CPU 使用率"),
        ("mem", "内存占用"),
        ("gpu", "GPU 使用率"),
        ("gpu_name", "显卡型号"),
        ("net", "网络速率"),
    ]

    def __init__(self, app: TopBar):
        self.app = app
        self.vars: dict = {}
        self.color_buttons: dict = {}

        win = tk.Toplevel(app.root)
        self.win = win
        win.title(f"{APP_NAME} 设置")
        win.configure(bg="#1B1F27")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)

        style = ttk.Style(win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#1B1F27")
        style.configure("TLabelframe", background="#1B1F27", foreground=TEXT_MAIN, bordercolor="#333A47")
        style.configure("TLabelframe.Label", background="#1B1F27", foreground="#9FB0C9")
        style.configure("TLabel", background="#1B1F27", foreground="#C8D2E0")
        style.configure("Hint.TLabel", background="#1B1F27", foreground="#7C8798")
        style.configure("TCheckbutton", background="#1B1F27", foreground="#C8D2E0")
        style.map("TCheckbutton", background=[("active", "#1B1F27")])
        style.configure("TButton", padding=(10, 4))
        style.configure("Accent.TButton", padding=(14, 6))

        outer = ttk.Frame(win, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer, text=f"{APP_NAME} 设置", font=("Segoe UI Semibold", 13)
        ).grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Label(
            outer,
            text="鼠标移到屏幕最上方边缘即可唤出监控条；在监控条上按住左键可左右拖动。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(2, 10))

        row = 2
        for group_title, fields in self.NUMBER_FIELDS:
            box = ttk.Labelframe(outer, text=group_title, padding=8)
            box.grid(row=row, column=0, columnspan=6, sticky="ew", pady=(0, 10))
            for i, (key, label, step, hint) in enumerate(fields):
                r, c = divmod(i, 2)
                ttk.Label(box, text=label).grid(row=r, column=c * 3, sticky="e", padx=(0, 6), pady=3)
                var = tk.StringVar(value=str(app.cfg.get(key, "")))
                self.vars[key] = var
                ttk.Spinbox(
                    box, from_=-10000, to=10000, increment=step, textvariable=var, width=10
                ).grid(row=r, column=c * 3 + 1, sticky="w", pady=3)
                ttk.Label(box, text=hint, style="Hint.TLabel").grid(
                    row=r, column=c * 3 + 2, sticky="w", padx=(8, 18), pady=3
                )
            row += 1

        show_box = ttk.Labelframe(outer, text="显示内容", padding=8)
        show_box.grid(row=row, column=0, columnspan=6, sticky="ew", pady=(0, 10))
        for i, (key, label) in enumerate(self.SHOW_FIELDS):
            var = tk.BooleanVar(value=bool(app.cfg["show"].get(key, True)))
            self.vars[f"show.{key}"] = var
            ttk.Checkbutton(show_box, text=label, variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 16), pady=2
            )
        row += 1

        color_box = ttk.Labelframe(outer, text="配色", padding=8)
        color_box.grid(row=row, column=0, columnspan=6, sticky="ew", pady=(0, 10))
        for i, (key, label) in enumerate((("bg_color", "面板背景色"),)):
            ttk.Label(color_box, text=label).grid(row=0, column=i * 2, sticky="e", padx=(0, 8), pady=3)
            self.vars[key] = tk.StringVar(value=app.cfg.get(key, "#15181F"))
            btn = tk.Button(
                color_box, textvariable=self.vars[key], width=10, relief="flat",
                bg=app.cfg.get(key, "#15181F"), fg="#FFFFFF", activebackground="#2A303C",
                command=lambda k=key: self._pick_color(k),
            )
            btn.grid(row=0, column=i * 2 + 1, sticky="w", pady=3)
            self.color_buttons[key] = btn
        ttk.Label(color_box, text="左键拖动监控条也可微调水平位置", style="Hint.TLabel").grid(
            row=0, column=2, columnspan=4, sticky="w", padx=(16, 0)
        )
        row += 1

        auto_box = ttk.Labelframe(outer, text="开机自启动", padding=8)
        auto_box.grid(row=row, column=0, columnspan=6, sticky="ew", pady=(0, 10))
        auto_box.columnconfigure(2, weight=1)
        self.autostart_var = tk.BooleanVar(value=False)
        self.autostart_check = ttk.Checkbutton(
            auto_box,
            text="开机时自动启动 EdgeMonitor（登录 Windows 后自动在后台运行）",
            variable=self.autostart_var,
            command=self._toggle_autostart,
        )
        self.autostart_check.grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(
            auto_box,
            text="写入当前用户注册表启动项，无需管理员权限，勾选后立即生效。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=(22, 0))
        self.autostart_status = ttk.Label(auto_box, text="", style="Hint.TLabel")
        self.autostart_status.grid(row=2, column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(2, 0))
        self.autostart_refresh = ttk.Button(auto_box, text="刷新状态", command=self._refresh_autostart)
        self.autostart_refresh.grid(row=0, column=3, sticky="e", padx=(12, 0))
        self._refresh_autostart()
        row += 1

        actions = ttk.Frame(outer)
        actions.grid(row=row, column=0, columnspan=6, sticky="ew", pady=(4, 0))
        ttk.Button(actions, text="保存并应用", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(actions, text="恢复默认", command=self.restore_defaults).pack(side="left", padx=8)
        ttk.Button(actions, text="重新载入当前配置", command=self.reload_from_config).pack(side="left")
        ttk.Button(actions, text="关闭", command=self.close).pack(side="right")

        self.status = ttk.Label(outer, text=f"配置文件：{settings.config_path()}", style="Hint.TLabel")
        self.status.grid(row=row + 1, column=0, columnspan=6, sticky="w", pady=(8, 0))

        win.update_idletasks()
        self._center_on_screen()
        win.lift()
        try:
            win.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _center_on_screen(self):
        try:
            w, h = self.win.winfo_width(), self.win.winfo_height()
            sw, sh = self.app._screen_w, self.app._screen_h
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
            self.win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _pick_color(self, key):
        try:
            current = self.vars[key].get()
            _rgb, picked = colorchooser.askcolor(color=current, parent=self.win, title="选择颜色")
            if picked:
                self.vars[key].set(picked.lower())
                btn = self.color_buttons.get(key)
                if btn is not None:
                    btn.configure(bg=picked.lower())
        except Exception:
            pass

    def _refresh_autostart(self):
        """读取注册表实际状态并同步到勾选框与提示文字。"""
        try:
            info = autostart.status()
        except Exception as exc:  # noqa: BLE001
            info = {"ok": False, "enabled": False, "stale": False, "message": f"读取失败：{exc}"}
        try:
            self.autostart_var.set(bool(info.get("enabled")))
            if not info.get("ok"):
                text, color = info.get("message", "自启动功能不可用"), TEXT_DIM
            elif info.get("stale"):
                text, color = info.get("message", ""), WARN_COLOR
            elif info.get("enabled"):
                text, color = info.get("message", "已开启"), "#81C784"
            else:
                text, color = info.get("message", "当前未开启"), TEXT_DIM
            self.autostart_status.configure(text=text, foreground=color)
            self.autostart_status.configure(wraplength=460)
            state = "normal" if info.get("ok") else "disabled"
            self.autostart_check.configure(state=state)
            self.autostart_refresh.configure(state=state)
        except Exception:
            pass

    def _toggle_autostart(self):
        """勾选/取消时立即写入或删除注册表启动项。"""
        want = bool(self.autostart_var.get())
        try:
            ok, message = autostart.enable() if want else autostart.disable()
        except Exception as exc:  # noqa: BLE001
            ok, message = False, f"操作失败：{exc}"
        if not ok:
            # 失败时回滚勾选状态，避免界面与真实状态不一致
            self.autostart_var.set(not want)
            try:
                self.autostart_status.configure(text=message, foreground=HIGH_COLOR, wraplength=460)
            except Exception:
                pass
            messagebox.showwarning(APP_NAME, message, parent=self.win)
            return
        self._refresh_autostart()
        try:
            self.status.configure(text=message)
        except Exception:
            pass

    def _collect(self) -> dict:
        cfg = dict(self.app.cfg)
        cfg["show"] = dict(self.app.cfg["show"])
        for key, var in self.vars.items():
            if key.startswith("show."):
                cfg["show"][key.split(".", 1)[1]] = bool(var.get())
            elif key == "bg_color":
                cfg["bg_color"] = settings.normalize_color(var.get(), cfg["bg_color"])
            else:
                cfg[key] = settings.coerce(key, var.get())
        return cfg

    def save(self):
        try:
            cfg = self._collect()
        except ValueError:
            messagebox.showerror(APP_NAME, "请检查数值项：只能填写数字。", parent=self.win)
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"保存失败：{exc}", parent=self.win)
            return
        self.app.cfg = cfg
        try:
            path = settings.save(cfg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"写入配置失败：{exc}", parent=self.win)
            return
        self.app.apply_config()
        self.status.configure(text=f"已保存并应用 · {path}")

    def restore_defaults(self):
        cfg = settings._merge(settings.DEFAULT_CONFIG, settings.DEFAULT_CONFIG)
        self.app.cfg = cfg
        self._fill(cfg)
        self.app.apply_config()
        self.status.configure(text="已恢复默认设置，点击「保存并应用」可写入配置文件")

    def reload_from_config(self):
        cfg = settings.load()
        self.app.cfg = cfg
        self._fill(cfg)
        self.app.apply_config()
        self._refresh_autostart()
        self.status.configure(text="已重新载入配置文件")

    def _fill(self, cfg):
        for key, var in self.vars.items():
            if key.startswith("show."):
                var.set(bool(cfg["show"].get(key.split(".", 1)[1], True)))
            elif key == "bg_color":
                var.set(cfg["bg_color"])
                btn = self.color_buttons.get(key)
                if btn is not None:
                    btn.configure(bg=cfg["bg_color"])
            else:
                var.set(str(cfg.get(key, "")))

    def close(self):
        self.app.close_settings()
        try:
            self.win.destroy()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
def main():
    enable_dpi_awareness()
    handle, already = single_instance_mutex()
    if already:
        alert("EdgeMonitor 已经在运行中。\n\n把鼠标移到屏幕最上方边缘即可看到监控条，\n右键监控条可以打开配置页面。")
        return

    cfg = settings.load()
    app = TopBar(cfg)
    if "--settings" in sys.argv or "-s" in sys.argv:
        app.root.after(300, app.open_settings)
    app.run()


if __name__ == "__main__":
    main()
