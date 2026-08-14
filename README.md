# GBFR_BuffTimer_V098

A real-time buff stack & countdown timer overlay for Granblue Fantasy: Relink.

---

GBFR_BuffTimer is a real-time buff monitoring overlay for Granblue Fantasy: Relink. It reads game memory (read-only, safe) to display live buff stacks and countdown timers on a transparent, always-on-top window.

- Real-time countdown ring — precise to the second, never miss a buff expiry
- 12 characters, 13 buffs fully supported
- 60+ customizable parameters — colors, sizes, opacities, fonts, layout
- Simplified Chinese / Traditional Chinese / English — switch anytime
- Transparent & non-intrusive — drag, scale, lock
- Single-file portable EXE — no install needed

**Install:**
1. Download GBFR_BuffTimer_V098.exe
2. Run it — done
3. Launch Granblue Fantasy: Relink, the overlay auto-detects your character
4. Right-click the tray icon for Settings / Lock / Exit

> Windows Defender may false-positive the EXE (common for PyInstaller). Add to exclusions if needed.

## Build from Source

```bash
git clone https://github.com/yourname/GBFR_Indicator.git
cd GBFR_Indicator
pip install -r requirements.txt
pyinstaller GBFR_BuffTimer_V098.spec --noconfirm
```
Output: dist/GBFR_BuffTimer_V098.exe

## Project Structure

```
GBFR_Indicator/
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt
├── GBFR_BuffTimer_V098.spec    # PyInstaller spec
├── assets/
│   ├── app_icon.ico
│   └── embedded_roll_icon.png
└── src/
    └── gbfr_overlay_qt_v6.py   # Main source (~3000 lines)
```

## Tech Stack

- Python 3.11 / PySide6 (Qt6) / pymem / PyInstaller

## License

Personal use. Character and buff names belong to Cygames, Inc.

---
---

# GBFR_BuffTimer_V098（中文）

碧蓝幻想：Relink 实时Buff层数与倒计时叠加显示工具。

---

GBFR_BuffTimer 是一款《碧蓝幻想：Relink》实时Buff监控工具，通过只读方式读取游戏内存，在透明置顶窗口上显示Buff层数和倒计时。

- 实时倒计时圆环——精确到秒，Buff到期不再靠猜
- 支持12个角色、13个Buff
- 60+项可调参数——颜色、大小、透明度、字体、布局随心定制
- 简中/繁中/英文三语随时切换
- 透明置顶不挡视线——可拖动、可缩放、可锁定
- 单文件便携EXE——无需安装

**安装方式：**
1. 下载 GBFR_BuffTimer_V098.exe
2. 双击运行，完事
3. 启动《碧蓝幻想：Relink》，自动检测角色并显示Buff
4. 右键托盘图标可打开设置 / 锁定窗口 / 退出

> Windows Defender 可能误报此EXE（PyInstaller打包常见问题），添加到信任列表即可。

## 从源码构建

```bash
git clone https://github.com/yourname/GBFR_Indicator.git
cd GBFR_Indicator
pip install -r requirements.txt
pyinstaller GBFR_BuffTimer_V098.spec --noconfirm
```
输出：dist/GBFR_BuffTimer_V098.exe

## 项目结构

```
GBFR_Indicator/
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt
├── GBFR_BuffTimer_V098.spec    # PyInstaller打包配置
├── assets/
│   ├── app_icon.ico
│   └── embedded_roll_icon.png
└── src/
    └── gbfr_overlay_qt_v6.py   # 主源码（约3000行）
```

## 技术栈

- Python 3.11 / PySide6 (Qt6) / pymem / PyInstaller

## 许可

个人使用。角色名和Buff名版权归 Cygames, Inc. 所有。