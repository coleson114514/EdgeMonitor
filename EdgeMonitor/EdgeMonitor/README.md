# EdgeMonitor — Windows 顶部边缘悬浮系统监控条

把鼠标移到屏幕**正上方边缘**，一条轻量的监控面板就会从顶部滑出；鼠标移开即自动收起。
面板显示 CPU、内存、GPU、显卡型号与网络实时状态，并带一个独立的配置页面。

---

## 一、功能

| 能力 | 说明 |
| --- | --- |
| 顶部边缘唤起 | 鼠标进入屏幕顶部 `trigger_px` 像素范围内，面板滑出 |
| 自动隐藏 | 鼠标离开面板且不在顶部边缘，延时 `hide_delay_ms` 后收起 |
| CPU | 总使用率、当前主频、物理核心 / 逻辑线程 |
| 内存 | 使用率、已用 / 总容量 |
| GPU | NVIDIA 显卡使用率、显存占用、温度（需要 `nvidia-smi`） |
| 显卡 | 显卡型号、驱动版本、显存（WMI 查询，支持任意显卡） |
| 网络 | 实时上下行速率、本机内网 IP |
| 独立配置页 | 齿轮图标 / 右键菜单打开，改完立即生效并写入配置文件 |
| 位置记忆 | 按住面板左键可左右拖动，位置自动保存 |
| 低占用 | 仅在采样线程读取一次数据，界面仅在数值变化时重绘；鼠标轮询间隔可调 |

> GPU 使用率 / 温度依赖 NVIDIA 官方命令行工具。非 NVIDIA 显卡时该卡片显示 `N/A`，
> 其余功能不受影响；「显卡」卡片仍会显示你的实际显卡型号。

---

## 二、运行要求

- Windows 10 / 11（Windows 8.1 也可运行）
- Python 3.8 及以上，安装时勾选 **Add Python to PATH**
- 依赖：仅 `psutil`

---

## 三、快速开始

### 方式 A：不打包，直接用 Python 跑（需要本机有 Python）

> **重要：这种方式必须有 Python 环境。**
> `启动 EdgeMonitor.bat` 只是替你执行 `pythonw edgemonitor.py`，
> 它本身**不含** Python 运行时。没装 Python 的电脑双击它会直接报错提示。

最省事：直接双击 **`启动 EdgeMonitor.bat`**。它会自动依次检查：

1. 当前目录有没有 `edgemonitor.py`
2. 本机有没有 Python（`python` 或 `py` 命令）
3. 有没有 `psutil` 库 —— 缺了会**自动帮你安装**
4. 优先用 `pythonw` 启动（不弹黑色控制台窗口）

手动等价命令：

```bat
python -m pip install -r requirements.txt
pythonw edgemonitor.py
```

### 方式 B：打包成 exe（目标电脑无需 Python）

双击 `build.bat`，得到单个 `dist\EdgeMonitor.exe`，拷到任何 Windows 电脑双击即用。
详见第四节。**如果对方电脑没有 Python，这是唯一可行的方式。**

启动后把鼠标贴到屏幕最上方边缘，面板即滑出。

---

### 两种方式对比

| | 直接跑 bat | 打包 exe |
| --- | --- | --- |
| 需要 Python | **需要**（3.8+，含 psutil） | 不需要 |
| 体积 | 几十 KB 源码 | 约 10–15 MB 单文件 |
| 首次启动速度 | 快（约 0.3 秒） | 稍慢（约 1–3 秒，需解压） |
| 换电脑 | 每台都要装 Python | 拷过去即可用 |
| 适合场景 | 自己电脑、需要改代码 | 分发给别人、长期固定使用 |

---

## 四、打包成单个 exe 文件

### 最简单：双击 `build.bat`

脚本会自动完成全部步骤（检查环境 → 装依赖 → 清理旧产物 → 打包 → 校验），
成功后在项目目录生成**单个**可执行文件：

```
dist\EdgeMonitor.exe
```

这个 exe 已内置 Python 运行时、`psutil` 和全部代码，**拷走即可用**，
目标电脑无需安装 Python。

### 手动命令（等价做法）

```bat
python -m pip install psutil pyinstaller
python -m PyInstaller --noconfirm --clean EdgeMonitor.spec
```

`EdgeMonitor.spec` 是本项目自带的打包配置，已预设好：

- `console=False` —— 运行时不弹黑色命令行窗口
- `hiddenimports` —— 确保 `metrics`、`settings`、`psutil` 被打进去
- `excludes` —— 排除 numpy / pandas / matplotlib / Qt 等无用库，显著减小体积
- `--onefile` 单文件模式

若想改成命令行参数方式，也可直接用：

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name EdgeMonitor --hidden-import psutil edgemonitor.py
```

### 打包产物怎么用

1. 把 `dist\EdgeMonitor.exe` 复制到固定目录，例如 `D:\Tools\EdgeMonitor\`
2. 右键 exe → 发送到 → 桌面快捷方式（可再给快捷方式换图标）
3. 双击运行，鼠标贴到屏幕最上方边缘即可唤出监控条

### 常见打包问题

| 现象 | 原因与解决 |
| --- | --- |
| 首次启动要等 1–3 秒 | 单文件 exe 启动时需解压到临时目录，属正常现象 |
| 杀软报毒 | PyInstaller 打包的 exe 常被误报。可加白名单；`spec` 中已关闭 UPX 以减少误报 |
| 打包报 `ModuleNotFoundError` | 用本项目的 `EdgeMonitor.spec` 打包（已含 hiddenimports），不要只传单个 py |
| 提示 pip 安装失败 | 换国内源：`python -m pip install psutil pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 想要自定义图标 | 准备 `icon.ico` 放在项目目录，取消 `spec` 里 `icon="icon.ico"` 的注释后重新打包 |

> 打包必须在 **Windows** 上进行（PyInstaller 不支持跨平台生成 exe）。

### 开机自启

**推荐直接在程序里勾选**：打开配置页面，在「开机自启动」区域勾选即可（详见第五节）。
程序会写入当前用户注册表启动项，无需管理员权限。

也可以手动把快捷方式放进启动文件夹：`Win+R` 输入 `shell:startup`。

---

## 五、配置页面

三种打开方式：

1. 面板右侧的 **⚙** 图标
2. 在面板上**右键** → 配置…
3. 命令行：`pythonw edgemonitor.py --settings`（启动即打开配置页）

可调项：

| 分组 | 项目 | 作用 |
| --- | --- | --- |
| 触发与动画 | 触发高度 | 鼠标距顶部多少像素触发，默认 3 |
| | 隐藏延迟 | 鼠标离开后多久收起，默认 700ms |
| | 刷新间隔 | 数据采样周期，默认 1000ms |
| | 动画时长 | 滑出 / 收起动画，默认 150ms |
| | 鼠标轮询 | 越小越灵敏，默认 50ms |
| 外观 | 卡片宽度 / 高度 | 单张卡片尺寸 |
| | 卡片间距 / 内边距 | 排版留白 |
| | 不透明度 | 0.3 – 1.0 |
| | 水平偏移 | 0 为屏幕居中 |
| | 面板背景色 | 取色器选择 |
| 显示内容 | 五个勾选项 | 单独关掉不需要的卡片 |
| 开机自启动 | 单选框开关 | 勾选即写入注册表启动项，立即生效；取消即移除 |

配置文件位置：

```
%APPDATA%\EdgeMonitor\config.json
```

直接编辑这个文件也能生效（重启程序后加载）。

---

## 六、操作速查

| 操作 | 效果 |
| --- | --- |
| 鼠标移到屏幕顶部边缘 | 面板滑出 |
| 鼠标移开 | 自动隐藏 |
| 按住面板左键拖动 | 左右移动面板并记忆位置 |
| 面板上右键 | 打开菜单（配置 / 立即刷新 / 隐藏 / 退出） |
| ⚙ 图标 | 打开配置页面 |
| ✕ 图标 | 退出程序 |

---

## 七、文件说明

```
EdgeMonitor/
├─ edgemonitor.py        主程序：悬浮条 + 配置页面
├─ metrics.py            指标采集（CPU/内存/GPU/显卡/网络），与界面解耦
├─ settings.py           配置读写、取值校正、默认值
├─ requirements.txt      依赖（psutil）
├─ build.bat             一键打包 exe
└─ 启动 EdgeMonitor.bat  免命令行启动
```

三个 Python 文件职责分离，`metrics.py` 可以单独导入做测试。

---

## 八、常见问题

**面板一直不出现？**
确认鼠标指针触到了屏幕**最上边缘**（`y` 坐标 ≤ 触发高度）。若开启了任务栏自动隐藏，
可能与之争抢顶部边框，可把「触发高度」调大一点，或调整任务栏位置。

**GPU 卡片显示 N/A？**
本机是 AMD / Intel 显卡，或未安装 NVIDIA 驱动。`nvidia-smi` 可用时才会读取使用率与温度。
显卡型号卡片仍然有效。

**双击 exe 没反应？**
程序已限制单实例运行。先检查右下角托盘区域 / 任务管理器是否已有 `EdgeMonitor.exe` 在运行。

**想彻底关闭？**
面板右侧 ✕，或面板右键 → 退出。

**高分屏字体有点小？**
程序已做 DPI 感知，会按系统缩放自动放大。仍觉得小可以在配置页把「卡片宽度 / 高度」调大。

---

## 九、隐私

全部数据在本机采集，不联网、不上传、无遥测。
