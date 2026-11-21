"""EdgeMonitor 指标采集模块。

与界面完全解耦，可以单独导入测试：python -c "import metrics; print(metrics.CpuSampler().read())"

采集内容：
- CPU  使用率、当前频率、物理核心 / 逻辑线程
- 内存 使用率、已用 / 总量
- GPU  NVIDIA 显卡使用率、显存占用、温度（通过 nvidia-smi）
- 显卡 型号、驱动版本、显存（通过 WMI Win32_VideoController）
- 网络 实时上下行速率、主用网卡、本机内网 IP

任何一项采集失败都不会抛异常，只会返回 ok=False 的空数据，保证界面稳定。
"""

from __future__ import annotations

import json
import platform
import socket
import subprocess
import threading
import time

try:  # psutil 是唯一第三方依赖
    import psutil
except Exception:  # pragma: no cover - 未安装时降级运行
    psutil = None

IS_WINDOWS = platform.system().lower() == "windows"
_CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _run(cmd, timeout: float = 6.0) -> str:
    """静默执行外部命令，失败返回空串。"""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def _to_float(text, default: float = 0.0) -> float:
    try:
        return float(str(text).strip())
    except Exception:
        return default


def human_bytes(value, digits: int = 1) -> str:
    """1536 -> '1.5 KB'。"""
    try:
        value = float(value)
    except Exception:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{value:.0f} B"
            return f"{value:.{digits}f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def human_speed(bps) -> str:
    """字节/秒 -> '1.2 MB/s'。"""
    try:
        value = float(bps)
    except Exception:
        return "0 B/s"
    if value < 1024:
        return f"{value:.0f} B/s"
    return human_bytes(value) + "/s"


# --------------------------------------------------------------------------- #
# CPU
# --------------------------------------------------------------------------- #
class CpuSampler:
    def __init__(self):
        self._data = {"ok": psutil is not None, "percent": 0.0, "freq_ghz": 0.0, "cores": 0, "threads": 0}
        if psutil:
            try:
                self._data["cores"] = psutil.cpu_count(logical=False) or 0
                self._data["threads"] = psutil.cpu_count(logical=True) or 0
                psutil.cpu_percent(interval=None)  # 预热，避免第一次读数为 0
            except Exception:
                pass

    def read(self):
        data = dict(self._data)
        if not psutil:
            return data
        try:
            data["percent"] = float(psutil.cpu_percent(interval=None))
        except Exception:
            pass
        try:
            freq = psutil.cpu_freq()
            if freq and freq.current:
                data["freq_ghz"] = freq.current / 1000.0
        except Exception:
            pass
        return data


# --------------------------------------------------------------------------- #
# 内存
# --------------------------------------------------------------------------- #
class MemSampler:
    def read(self):
        data = {"ok": psutil is not None, "percent": 0.0, "used": 0, "total": 0}
        if not psutil:
            return data
        try:
            vm = psutil.virtual_memory()
            data.update(percent=float(vm.percent), used=vm.used, total=vm.total)
        except Exception:
            pass
        return data


# --------------------------------------------------------------------------- #
# 网络
# --------------------------------------------------------------------------- #
class NetSampler:
    def __init__(self):
        self._prev = None
        self._prev_t = 0.0
        self._ip = "—"
        self._ip_t = 0.0
        self._iface = ""

    @staticmethod
    def _local_ip() -> str:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
            finally:
                sock.close()
        except Exception:
            return "—"

    def read(self):
        data = {"ok": psutil is not None, "up": 0.0, "down": 0.0, "ip": self._ip, "iface": self._iface}
        if psutil:
            try:
                up = down = 0
                best, best_bytes = "", -1
                for nic, io in psutil.net_io_counters(pernic=True).items():
                    name = str(nic)
                    if name.lower().startswith(("lo", "loopback")):
                        continue
                    try:
                        sent, recv = io.bytes_sent, io.bytes_recv
                    except Exception:
                        continue
                    up += sent
                    down += recv
                    if sent + recv > best_bytes:
                        best, best_bytes = name, sent + recv
                now = time.monotonic()
                if self._prev is not None:
                    dt = max(0.05, now - self._prev_t)
                    data["up"] = max(0.0, (up - self._prev[0]) / dt)
                    data["down"] = max(0.0, (down - self._prev[1]) / dt)
                self._prev = (up, down)
                self._prev_t = now
                self._iface = best
                data["iface"] = best
            except Exception:
                pass
        now = time.monotonic()
        if now - self._ip_t > 30:
            self._ip = self._local_ip()
            self._ip_t = now
        data["ip"] = self._ip
        return data


# --------------------------------------------------------------------------- #
# NVIDIA GPU（使用率 / 显存 / 温度）
# --------------------------------------------------------------------------- #
class NvidiaGpuSampler:
    _FIELDS = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"
    _FAIL_BACKOFF = 30.0  # 连续失败后的重试间隔（秒）

    def __init__(self):
        self.name = ""
        self._last_try = 0.0
        self._consecutive_fail = 0

    def _cached_failure(self, data):
        data["ok"] = False
        data["name"] = self.name
        return data

    def read(self):
        data = {"ok": False, "name": self.name, "util": 0.0, "mem_used": 0.0, "mem_total": 0.0, "temp": 0.0}
        now = time.monotonic()
        if self._consecutive_fail >= 3 and now - self._last_try < self._FAIL_BACKOFF:
            return self._cached_failure(data)
        self._last_try = now
        out = _run(["nvidia-smi", f"--query-gpu={self._FIELDS}", "--format=csv,noheader,nounits"], 5.0)
        if not out:
            self._consecutive_fail += 1
            return self._cached_failure(data)
        parts = [p.strip() for p in out.splitlines()[0].split(",")]
        if len(parts) < 5:
            self._consecutive_fail += 1
            return self._cached_failure(data)
        self._consecutive_fail = 0
        self.name = parts[0]
        data.update(
            ok=True,
            name=parts[0],
            util=_to_float(parts[1]),
            mem_used=_to_float(parts[2]) * 1024 * 1024,
            mem_total=_to_float(parts[3]) * 1024 * 1024,
            temp=_to_float(parts[4]),
        )
        return data


# --------------------------------------------------------------------------- #
# 显卡型号信息（WMI，后台查询一次）
# --------------------------------------------------------------------------- #
class VideoControllerInfo:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {"name": "", "driver": "", "memory": "", "items": []}
        self._started = False

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._query, daemon=True).start()

    def data(self):
        with self._lock:
            return dict(self._data)

    def _query(self):
        if not IS_WINDOWS:
            return
        script = (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,DriverVersion,AdapterRAM | ConvertTo-Json -Compress"
        )
        out = _run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout=15.0,
        )
        if not out:
            return
        try:
            raw = json.loads(out)
        except Exception:
            return
        if isinstance(raw, dict):
            raw = [raw]
        items = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("Name") or "").strip()
            if not name:
                continue
            items.append(
                {
                    "name": name,
                    "driver": str(entry.get("DriverVersion") or "").strip(),
                    "ram": entry.get("AdapterRAM") or 0,
                }
            )
        if not items:
            return
        primary = next((i for i in items if "basic" not in i["name"].lower()), items[0])
        with self._lock:
            self._data = {
                "name": primary["name"],
                "driver": primary["driver"],
                "memory": human_bytes(primary["ram"]) if primary["ram"] else "",
                "items": items,
            }


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
class Monitor:
    """统一采样入口，供界面线程调用。"""

    def __init__(self):
        self.cpu = CpuSampler()
        self.mem = MemSampler()
        self.gpu = NvidiaGpuSampler()
        self.net = NetSampler()
        self.video = VideoControllerInfo()
        self.video.start()

    def sample(self) -> dict:
        snap = {}
        for key, sampler in (("cpu", self.cpu), ("mem", self.mem), ("gpu", self.gpu), ("net", self.net)):
            try:
                snap[key] = sampler.read()
            except Exception:
                snap[key] = {"ok": False}
        snap["gpu_name"] = self.video.data()
        return snap
