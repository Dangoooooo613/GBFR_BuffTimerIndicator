# GBFR Cooldown Indicator (碧蓝幻想 Relink 指示器)

> A single-file Windows tool that reads the *Granblue Fantasy: Relink* process memory in real time and overlays **skill cooldowns**, **Buff status**, and **character resource gauges** on screen to assist normal play and speedrunning.
> Built with Python + PySide6 + pymem. Shipped as a single self-contained exe — no installation required.

> 单文件 Windows 工具，实时读取《碧蓝幻想 Relink》进程内存，在屏幕上叠加显示**技能冷却**、**Buff 状态**、**角色资源槽**等关键信息，辅助游玩与速通。
> 基于 Python + PySide6 + pymem 构建，单 exe 发布，无需安装。

---

## Features | 功能特性

### 1. Skill Cooldown Monitor (能力冷却模块)
- A four-slot diamond layout (Brave Blade + skill slots 1–4): rounded diamonds rotated 45°, with a three-layer 3D border.
- Automatic AOB scan to locate the actor; if the scan fails you can paste a pointer copied from Cheat Engine manually.
- Automatic recognition of 29 characters (based on the charid hash).
- Real-time cooldown countdown + progress ratio; peak cooldowns are learned automatically at runtime and persisted, and can be exported as a cooldown-cap table with one click.
- **V250 added**:
  - Diamond border thickness is adjustable (default ×1.35).
  - When a cooldown finishes, a soft **breathing glow** is drawn around the **bottom tip** of the diamond to signal "cooldown complete". Breathing frequency, softness, glow color (default white), and peak opacity are all adjustable.

### 1. 技能冷却监视（能力冷却模块）
- 四槽菱形布局（无畏之刃 + 技能槽 1~4），旋转 45° 的圆角菱形，带立体三层边框。
- 自动 AOB 扫描定位 actor；扫描失败时可从 Cheat Engine 复制指针手动填入。
- 29 个角色自动识别（基于 charid 哈希）。
- 实时冷却倒计时 + 进度占比；运行时自动学习各技能冷却峰值并持久化，可一键导出冷却上限表。
- **V250 新增**：
  - 菱形边框粗细可调（默认 ×1.35）。
  - 冷却完毕时，在菱形**底部尖角**绘制一圈柔和**呼吸光**，用于提示“冷却结束”。呼吸频率、柔和程度、光的颜色（默认白色）、峰值不透明度全部可调。

### 2. Core Buff Detection Module (核心 Buff 检测模块)
- Built around a "spiked circle" as the main body, monitoring up to **5 Buffs** simultaneously.
- Multi-Buff layout: the core detection area is scaled ×1.35 in width/height; all Buffs are **evenly distributed horizontally** (spacing adjustable), with vertical **Delta_Y offset** (+Δ / −Δ alternation) and vertical centering.
- Differentiated colors: the base color you set per Buff slot undergoes an **HSV hue rotation** (two independent toggles for the outer group / inner group), so each Buff stays distinguishable without breaking your color scheme.
- Layer count display; when the count is 0 it shows "−" instead of "0".
- The countdown capsule (background / border / text) follows the slot's hue rotation as a whole, color-matched to the spiked circle.

### 2. 核心 Buff 检测模块
- 以“尖刺圆”为主体，最多同时监测 **5 个 Buff**。
- 多 Buff 布局：核心监测区长宽 ×1.35；所有 Buff **水平均匀分布**（圆心间距可调），垂直方向以 **Delta_Y 错位**（+Δ / −Δ 循环），并垂直居中。
- 差异化颜色：按 Buff 槽位对你设定的基础色做 **HSV 色相旋转**（外部组 / 内部组两个开关独立控制），既保证每个 Buff 可区分，又不会破坏你的配色风格。
- 层数显示；层数为 0 时显示“-”而非“0”。
- 倒计时胶囊（背景 / 边框 / 文字）整体跟随槽位色相旋转，与尖刺圆同色系区分。

### 3. Buff Enable / Disable (Buff 启用 / 禁用)
- One collapsible group box per character; an "active" zone and a "hidden" zone in two columns, drag to toggle visibility, and **cannot cross characters** (no mis-operation).
- Buff order per character is drag-sortable, with right-click to pin to top.

### 3. Buff 启用 / 禁用
- 每个角色一个可折叠小组框；生效区 / 隐藏区双栏，拖拽切换显示与隐藏，且**不可跨角色**误操作。
- 角色 Buff 顺位可拖拽排序、右键置顶。

### 4. Captain / Gran / Katalina & Id Exclusives (团长 / 古兰 / 姬塔 与 伊德专属)
- Captain (PL0000) / Gran (PL0100) / Katalina: Class level + countdown.
- Id (PL1900): Azure/Arvess power, The One, hidden gauge.

### 4. 团长 / 古兰 / 姬塔 与 伊德专属
- 团长（PL0000）/ 古兰（PL0100）/ 姬塔：Class 等级 + 倒计时。
- 伊德（PL1900）：紫银之力、神威一体、隐藏槽。

### 5. Misc (其他)
- Window always-on-top, target selection, a rich settings panel (all parameters persisted).
- **EXE sync list** (Global → General): a multi-line box (≈5 rows tall) where you enter absolute paths of multiple EXEs, separated by semicolons OR newlines. Each entry may append `||working_directory` to set its **start-in directory** (equivalent to a .lnk's "Start in" field; omit to default to the EXE's own directory). At startup each is checked once — launched if not running (with its start-in directory), skipped if already running (never killed, never monitored) — so your common side tools launch together with the indicator. Exact absolute-path matching only.
- **Launch at Windows startup** (Global → General): a toggle that auto-runs the indicator when you log into Windows. **On by default.** Implemented via the HKCU "Run" registry key (no admin required); turning it off removes the entry.
- **Unified program icon**: the packaged exe now embeds `app_icon.ico`, so its file icon matches the system tray icon and the settings dialog title-bar icon (previously the exe used PyInstaller's default icon). All three now use the same icon.
- **Title bar alignment** (Core Detection → Title Bar): a dropdown lets you align the title bar (icon row + status text) to **Left** / **Center** / **Right**; defaults to **Left**. Center keeps the classic centered layout; Left/Right pack everything to the corresponding edge. The dropdown label and options are fully trilingual (zh / zh_tw / en).
- Online update: you can fill in a `version.json` URL in Settings; it auto-checks for new versions on launch / on a schedule.

### 5. 其他
- 窗口置顶、目标选择、丰富的设置面板（全参数持久化）。
- **EXE 同步列表**（全局 → 常规）：一个多行输入框（约 5 行高），填入多个 exe 的绝对路径，可用**分号或换行**分隔。每条可附加 `||工作目录` 指定**起始位置**（等同 .lnk 的「起始位置」字段，省略则固定在 exe 同目录）。启动时逐个检测一次——未运行则启动（以指定起始位置为工作目录）、已运行则跳过（绝不杀进程、不监视），让常用辅助工具随指示器一起启动；仅按绝对路径精确匹配。
- **开机自动启动**（全局 → 常规）：开关，登录 Windows 后自动运行本程序。**默认开启**。通过 HKCU「运行」注册表项实现（无需管理员权限）；关闭即移除该项。
- **程序图标统一**：打包后的 exe 现已内嵌 `app_icon.ico`，其文件图标与系统托盘图标、设置卡标题栏图标保持一致（此前 exe 用的是 PyInstaller 默认图标）。三处现在使用同一个图标。
- **标题栏对齐**（核心检测 → 标题栏）：下拉菜单可选**靠左** / **居中** / **靠右**，默认**靠左**。居中保持经典居中布局；靠左/靠右把图标行与状态文字整体贴到对应边缘。下拉标签与所有选项均三语（简 / 繁 / 英）适配。
- 在线更新：设置内可填入 `version.json` 地址，启动 / 定时自动检测新版本。

---

### 6. All-Buff Display Module (全 Buff 显示模块)
- A 4th independent module that lists **every buff currently readable on the main character** as a grid of lightweight cards (same data source as the Buff Monitor, supplied after a unified gate filter, shared with the core module).
- Reuses the shared traits of the three existing modules: independent show/hide toggle / independent screen XY / overall scale / Position & Scale sub-tab / per-element opacity.
- Each card, top to bottom: **buff name → stacks / max-stacks (single-layer shows 1/1) → remaining / duration seconds → a horizontal countdown bar**. The three text areas each have their own font size + color; the countdown bar and the text backing plate each have their own width / height / color / opacity.
- Layout is adjustable: rows / per-row / row spacing / card spacing.
- **V2066 Gate (门限) tab** — monitor-style numerical junk filter ported from GBFR_BuffMonitor. Each threshold toggles independently and is live: status_id==0 / status_id max / sub_id max / ailment threshold (also drives the debuff color boundary) / current-stacks max / max-stacks max / stack-conflict / duration max / min remaining / min initial / NaN∪Inf checks.
- **V2066 Filter (过滤) tab** — display-level toggles: hide buffs shown in core / hide infinite / hide character-exclusive / hide mastery-exclusive / hide single-layer.
- **V2064 Canvas Background Fill** — a brand-new slider (default 0% = transparent) fills the entire canvas under the cards with semi-transparent black to mask content from background windows (e.g. settings-dialog file-path labels) bleeding through the translucent overlay.
- 5 optional filter switches (all off by default = show everything): **hide core-module buffs / hide infinite buffs / hide character-exclusive buffs / hide mastery buffs / hide single-layer buffs**, mapped to the Buff Monitor's single-layer / exclusive / mastery fields.
- Data source: `buff_attrs.json` (143 in-game buffs with trilingual names and exclusive/mastery/single-layer flags), bundled with the build.
- **V2060 add-on:**
  - **Unified Element Spacing** (single parameter): default 4 px between name ↔ stacks ↔ time ↔ bar, breathing room inside each card.
  - **Bar 100% Outline Frame:** default 2 px stroke (same color as the bar) marks the visible upper-limit reference. Set thickness to 0 to disable.
  - **End-of-Timer Warning:** when remaining % < threshold, both the time text and the bar switch to the warning color. Enable / threshold (1-99%) / warning color / opacity are independently adjustable.
  - **Debuff Colors (ID ≥ 1000):** Poison/Burn/Slow/Dizzy/Glaciate etc. debuffs have independent name / stacks / time / bar colors, visually distinct from normal buffs. Debuff warning is on by default (pure white).
  - **Fixed V2050 character-detection regression** (a leftover `gate` reference caused a runtime NameError each frame, breaking the readout thread).
- **V2061 hotfix:** All-Buff card backing default **width 72 → 80** and **height 52 → 64**, preventing the countdown bar from spilling past the card and overlapping the next row (user-reported "text being obscured"). The Element Spacing and per-row-count controls were both already wired in — only the defaults were off.
- **V2062 enhancement:** The **card backing width / height** controls are now treated as an **auto-fit floor** — the layout recomputes the minimum visible size from current font / element-spacing / bar / frame settings every render, then takes the max with the user's value, so the card is **never clipped** no matter how small the slider is set (the user-reported 75×58 setting now produces cards where the progress bar always fits). The Layout sub-tab **no longer has a "Rows" control** — row count is `ceil(buff_total / per_row)` and the window auto-grows with the actual buff count. The per-row count control is kept as the only layout knob.
- **V2063 enhancement:**
  - **Sort Mode (Layout sub-tab):** new "Sort Mode" combo — **By ID (Ascending)** (default, stable, the historical behavior) or **By Appearance Time** (each new buff's first-seen tick is recorded; new buffs go to the end; buffs that left and came back keep their original position — the "newer one at the bottom, gap stays put" feel).
  - **Combat-Only Hidden (synced with the other modules):** the All-Buff module now respects the global "Hide out of combat" toggle exactly like Skill / Core / Roll — when combat state ends and "hide" is on, the window hides entirely (not just dims), and re-shows the moment combat starts again. Out-of-combat opacity > 0% lets the cards softly fade along with the multiplier.
  - **Dodge Icon Fallback:** the orange-rounded-rect fallback for the dodge icons is gone. When the dodge icon PNG fails to load (or no custom path is set), the indicator now draws a **clean white check-mark + dark semi-transparent rounded square** at runtime so the UI keeps a consistent "dodge ready" feel regardless of what asset is bundled.

### 6. 全 Buff 显示模块
- 第四独立模块：以网格化轻量卡片列出**当前主控角色可读到的全部 buff**（与 Buff Monitor 同源，统一 gate 过滤后同时供给核心模块与本模块）。
- 复用三大模块交集特质：独立显隐开关 / 独立屏幕位置 XY / 整体缩放 / 位置与缩放子页 / 元素级透明度。
- 每张卡片自上而下：**buff 名 → 层数/最大层（单层显示 1/1）→ 剩余/持续秒 → 横向倒计时条**。三处文字各有独立字号+颜色；倒计时条与文字衬底各有独立的宽/高/颜色/不透明度。
- 布局可调：行数 / 每行数量 / 行间距 / 卡片间距。
- 5 个可选过滤开关（默认全关=显示全部）：**不显示核心区已展示的 / 不显示永续的 / 不显示角色专属的 / 不显示专精专属 / 不显示单层**，分别对齐 Buff Monitor 的 单层 / 是否专属 / 是否专精buff 字段。
- 数据源：`buff_attrs.json`（143 个游戏内 buff 的三语名与专属/专精/单层标记），已随打包分发。
- **V2060 增量：**
  - **元素统一间距**：单参通用，默认 4 px，在 名称 ↔ 层数 ↔ 时间 ↔ 进度条 之间留出呼吸空间。
  - **进度条 100% 外框**：默认 2 px 描边（颜色与进度条相同）作为可见的上限参考框；粗细设回 0 关闭。
  - **倒计时尾声警告**：剩余百分比低于阈值时，时间文字与进度条统一切到警告色；启用 / 阈值（1-99%）/ 警告颜色 / 不透明度 四件套独立可调。
  - **Debuff 配色（编号 ≥ 1000）**：中毒/灼热/缓速/昏迷/冰冻 等 debuff 独立 名称·层数·时间·进度条 四色，与普通 buff 视觉区分；Debuff 警告默认开启（纯白更醒目）。
  - **修复 V2050 「角色检测失效」回归**（V2050 引入的 `gate` NameError 每帧崩溃，导致读取线程挂掉）。
- **V2061 增量：**
  - **衬底默认值收紧到 80×64**（之前 72×52），避免进度条溢出衬底底边扎入下一行卡片。
  - **新增工程红线 ⑥**：每次源码修改必须把 `_BUILD_NO` +1，并同步 version.json + README Changelog + release_notes 三语。
- **V2062 增量：**
  - **衬底宽/高改为「自适应 floor」语义**——按当前字体/元素间距/进度条/外框计算每帧最小可见尺寸，再取 `max(自适应最小值, 用户设置)`，玩家拖小也不会裁切内容（用户截图设的 75×58 也会被自动顶到不裁切的最小值）。
  - **布局子页取消「显示行数」控件**——行数 = `ceil(buff 总数 / 每行数量)` 自动延伸，窗口按实际 buff 数精确收/扩；**每行数量**作为唯一布局参数保留。
- **V2063 增量：**
  - **排序方式可调（布局子页新增「排序方式」下拉）**：二选一「按ID升序」（历史默认）/「按出现时间」——后者按每个 buff 首次出现的 monotonic seq 排序，新出现的 buff 自动排到末尾；消失后重新出现的 buff 保留原位（即「后到的在后面，消失后后面的顶上来」）。
  - **全 Buff 模块同步其它模块的「非战斗隐藏」**：勾选「非战斗隐藏」后离开战斗状态，全 Buff 模块整窗 `hide()`（不再挂一块透明窗挡游戏鼠标），回到战斗再 show；隐藏不透明度 > 0% 时按 mult 渐变淡出。
- **V2064 增量：**
  - **新增「过滤垃圾」标签页（硬核 monitor 风格废料过滤）**：与原「筛选显示」拆分，独立硬核数据源层面过滤：
    - **内置硬编码黑名单（不可关闭）**——根据 `buff_attrs.json` 自动识别典型废料（invisible / hidden / passive tracker / 内部状态等），启动时自动屏蔽；总数实时显示给玩家。
    - **用户黑名单（多行文本框）**——填入要过滤的 buff sid，十进制（如 `1024`）/十六进制（如 `0x400`），多个用空格/逗号/换行/分号分隔；`#` 或 `//` 开头为注释行。
    - **用户白名单 + 白名单模式 toggle**——开启后只显示白名单中的 sid（黑名单失效）。
    - **最短持续秒数**——0.5s 默认（硬核 monitor 风格），过滤闪屏废料；0 = 不过滤。
    - **隐藏零层 buff** + **隐藏 debuff**——可选项。
  - **「过滤」→「筛选显示」改名**——i18n 三语同步；移除「不显示永续的」（搬到「过滤垃圾」的最短秒数控制）；保留 4 个显示层开关（核心/角色专属/专精专属/单层）。
  - **画布背景填充（配色与文字新增子卡）**——玩家可调 0~100% 不透明黑色填充整张画布（默认 0 = 透明），避免设置对话框/其他窗口的内容（如文件路径标签）透过半透明卡片漏出来；之前用户截图里「ndicator_Debug / dist / buff_Attrs.json」之类的路径片段就是这类穿透，调到 30~70 即可遮罩。
  - **名称字号自适应阶梯**——之前 `name_fs=11` 时 5 字中文 buff 名（如「钳蟹的据固」）会被 ElideRight 截成「钳蟹的据…」，现在阶梯 `name_fs → 10 → 9 → 8` 缩字到能完整放下，最后再降不下才用 ElideRight。
  - **翻滚图标兜底重做**：删掉原先无特征的橙色圆角矩形，PNG 失败/未设置时改为 QPainter 程序绘制的「白对号 ✓ + 深透明圆角底」，UI 风格统一为「dodge ready」徽章。

---

## Download & Install | 下载与安装

1. Go to [Releases](https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases) and download the latest `GBFR_CooldownIndicator_V2063.exe` (single file, ~50MB, PySide6 bundled, no install needed).
2. **Recommended to run as Administrator** (pymem usually needs sufficient privileges to read game memory; otherwise scan/read may fail).
3. Launch *Granblue Fantasy: Relink*, then in the tool click "Connect" to run the automatic AOB scan; if the scan fails, copy the actor pointer from Cheat Engine and paste it manually.
4. Select your current character and open the settings panel to adjust layout and colors as needed.

### 下载与安装
1. 前往 [Releases](https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases) 下载最新版 `GBFR_CooldownIndicator_V2007.exe`（单文件，约 50MB，已内含 PySide6，无需安装）。
2. **建议以管理员身份运行**（pymem 读取游戏内存通常需要足够权限，否则可能扫描/读取失败）。
3. 启动《碧蓝幻想 Relink》，进入游戏后点击工具内“连接”自动 AOB 扫描；若扫描失败，可从 Cheat Engine 复制 actor 指针手动填入。
4. 选择当前操控角色，按需打开设置面板调整布局与配色。

---

## Usage Tips | 使用提示

- **Settings panel groups**:
  - Skill Cooldown (includes a "Ready Breathing Glow" sub-page: toggle / color / frequency Hz / softness / peak opacity).
  - Multi-Buff Layout (one group per 2 / 3 / 4 / 5 Buffs; each group has: scale, horizontal center spacing, center Delta_Y, outer differentiated color, inner differentiated color — 20 parameters total).
  - Buff Enable / Disable (collapsible group per character).
  - Online Update (Check Update button + URL input + auto-check checkbox).
- **Cooldown cap table**: cooldown peaks accumulate automatically during play; click "Export Cooldown Cap Table" to generate a CSV / JSON, making it easy to see each ability's real cooldown seconds.

### 使用提示
- **设置面板分组**：
  - 技能冷却（含“就绪呼吸光”子页：开关 / 颜色 / 频率 Hz / 柔和程度 / 峰值不透明度）。
  - 多 Buff 布局（按 2 / 3 / 4 / 5 个 Buff 各一组，每组含：缩放、圆心水平间距、圆心 Delta_Y、外部差异化颜色、内部差异化颜色，共 20 个参数）。
  - Buff 启用 / 禁用（每角色折叠小组框）。
  - 在线更新（检查更新按钮 + URL 输入框 + 自动检查勾选）。
- **冷却上限表**：实战中自动累积各技能冷却峰值；点“导出冷却上限表”生成 CSV / JSON，便于查看每个能力的真实冷却秒数。

---

## Build from Source | 从源码构建

Verified environment:
- Python 3.11 (`C:/Python311/python.exe`)
- `PySide6==6.11.1`, `PyInstaller==6.21.0`

```bash
cd GBFR_Indicator
C:/Python311/python.exe -m PyInstaller GBFR_CooldownIndicator_V2007.spec --noconfirm
```

The output is `dist/GBFR_CooldownIndicator_V2007.exe` (~50MB, PySide6 bundled). The app reads its own version from the exe filename at runtime (e.g. `..._V2007.exe` → reports version **20.07**).

> Note: Always build with the Python 3.11 environment above. If you build with an interpreter that doesn't have PySide6 installed, you'll get a broken ~8–9MB exe that fails at runtime with `No module named 'PySide6'`.

### 从源码构建
已验证环境：
- Python 3.11（`C:/Python311/python.exe`）
- `PySide6==6.11.1`、`PyInstaller==6.21.0`

```bash
cd GBFR_Indicator
C:/Python311/python.exe -m PyInstaller GBFR_CooldownIndicator_V2007.spec --noconfirm
```

产物位于 `dist/GBFR_CooldownIndicator_V2007.exe`（约 50MB，PySide6 已打包）。程序在运行时会从自身 exe 文件名读取版本号（例如 `..._V2007.exe` → 自报版本 **20.07**）。

> 注意：务必使用上述 Python 3.11 环境构建。若用未安装 PySide6 的解释器构建，会生成约 8~9MB 的残缺 exe，运行时会报 `No module named 'PySide6'`。

---

## Online Update (Advanced) | 在线更新（进阶）

Maintain a `version.json` at the repository root:

```json
{
  "version": "20.03",
  "download_url": "https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases/latest/download/GBFR_CooldownIndicator_V2007.exe",
  "changelog": {
    "zh": "== v20.03 ==\n- 写死 ExStatus 偏移：移除核心检测设置里的 ExStatus 偏移 SpinBox，偏移固定为 0xAF8（2808），由源码常量 ACTOR_EX_STATUS 唯一决定。\n- 修复英文模式 Changelog 泄露中文：新增 CJK 检测防护，lang=en 且远端含中文时降级为本地干净英文日志。",
    "zh_tw": "== v20.03 ==\n- 寫死 ExStatus 偏移：移除核心檢測設定裡的 ExStatus 偏移 SpinBox，偏移固定為 0xAF8（2808），由原始碼常數 ACTOR_EX_STATUS 唯一決定。\n- 修復英文模式 Changelog 洩漏中文：新增 CJK 檢測防護，lang=en 且遠端含中文時降級為本地乾淨英文日誌。",
    "en": "== v20.03 ==\n- Hardcoded ExStatus offset: removed the ExStatus offset SpinBox from settings; offset is now fixed at 0xAF8 (2808) via the ACTOR_EX_STATUS constant.\n- Fixed changelog Chinese leak in English mode: added a CJK-detection guard that falls back to the clean local changelog when lang=en but the remote text contains CJK."
  },
  "min_version": "20.03"
}
```

Set the tool's `update_check_url` (in Settings) to:

```
https://raw.githubusercontent.com/Dangoooooo613/GBFR_BuffTimerIndicator/main/version.json
```

and it will auto-check for new versions on launch / on a schedule.

> **Trilingual changelog:** As of V623 the `changelog` field is a three-language dict `{"zh":..., "zh_tw":..., "en":...}`. The in-app changelog (Settings → About / Update) picks the correct language automatically — English users will no longer see Chinese text. When you publish a new build, update `version` / `download_url` and prepend the new notes to **all three** language keys so the history stays trilingual.

### 在线更新（进阶）
在仓库根目录维护 `version.json`：

```json
{
  "version": "20.03",
  "download_url": "https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases/latest/download/GBFR_CooldownIndicator_V2007.exe",
  "changelog": {
    "zh": "== v20.03 ==\n- 写死 ExStatus 偏移：移除核心检测设置里的 ExStatus 偏移 SpinBox，偏移固定为 0xAF8（2808），由源码常量 ACTOR_EX_STATUS 唯一决定。\n- 修复英文模式 Changelog 泄露中文：新增 CJK 检测防护，lang=en 且远端含中文时降级为本地干净英文日志。",
    "zh_tw": "== v20.03 ==\n- 寫死 ExStatus 偏移：移除核心檢測設定裡的 ExStatus 偏移 SpinBox，偏移固定為 0xAF8（2808），由原始碼常數 ACTOR_EX_STATUS 唯一決定。\n- 修復英文模式 Changelog 洩漏中文：新增 CJK 檢測防護，lang=en 且遠端含中文時降級為本地乾淨英文日誌。",
    "en": "== v20.03 ==\n- Hardcoded ExStatus offset: removed the ExStatus offset SpinBox from settings; offset is now fixed at 0xAF8 (2808) via the ACTOR_EX_STATUS constant.\n- Fixed changelog Chinese leak in English mode: added a CJK-detection guard that falls back to the clean local changelog when lang=en but the remote text contains CJK."
  },
  "min_version": "20.03"
}
```

将工具设置里的 `update_check_url` 填为：

```
https://raw.githubusercontent.com/Dangoooooo613/GBFR_BuffTimerIndicator/main/version.json
```

即可在启动 / 定时自动检测新版本。

> **三语更新日志：** 自 V623 起，`changelog` 字段为三语 dict `{"zh":..., "zh_tw":..., "en":...}`。应用内更新日志（设置 → 关于/更新）会按所选语言自动放出正确内容——英文用户不再看到中文。发布新版本时，请同步更新 `version` / `download_url`，并把新说明**按三语**分别前缀到三个语言键，确保历史始终保持三语。

---

## Changelog | 更新日志

== v23.07 ==
全 Buff / Boss 两模块顶部新增「统计条」：实时显示 共 N · Debuff · 永续 · 尾声 四项计数
· 共 = 当前通过门限的 buff 总数；Debuff = 是否 debuff；永续 = 永续（infinite）标志；尾声 = 非永续且 剩余/初始 < 倒计时尾声警告阈值的 buff 数量。
· 统计条占固定高度（字号比名称小 1 号），网格整体下移、模块窗口高度相应增加，文字不会被窗口底边切掉。
== v23.20 ==
[1] 修复「游戏重启后 boss buff 模块丢失工作、其他模块正常」的根因：scan() 重连分支原本只清空 player 的缓存，漏了 boss 模块的 _BOSS_CACHE / _BOSS_ET_CACHE；重启后若指针被复用，陈旧 boss actor 会毒害 find_boss_actor 使 boss 模块整屏空白。现与 player 对称地重连即清空，并加 pid 守卫（双保险）。
[2] 补上日文(ja)本地化缺口：托盘菜单 / 技能模块状态占位 / 文件·颜色对话框 等约 10 处字符串此前缺 ja 键且兜底掉回中文；现已补 ja 键，兜底统一改为「lang → en → zh」。

== v23.19 ==
[1] 收紧运行期输出文件：软件现在只写 3 个文件——ptr_cache.txt / buff_attrs_unknown.json / overlay_settings.json；新增 ENABLE_BOSS_BUFF_DUMP / ENABLE_FOCUS_LOG 两个总开关（默认关），关闭 boss buff 每秒 dump（last_boss_buffs.json）与前后台焦点诊断日志（overlay_focus_log.txt）的写盘，不再在游戏目录散落多余文件；
[2] 修复 0x94(148) 这个 buff 仍显示成十六进制「0x94」的问题：根因是历史上该 sid 还没收录进内置表时，被自动记进了外部补充文件 buff_attrs_unknown.json（名称=0x94），而外部文件优先级高于内置表，于是即使后来内置补了真名「混沌转换」也被陈旧的 0x94 记录盖掉；_attr_for_sid 现在对「名称为空或仍等于十六进制 ID」的外部兜底条目改取内置真实名（仅当内置也缺失才保留），玩家手填的真名仍被尊重，避免 0x94 类「一直显示十六进制」复发。
== v23.18 ==
[1] 正式发布版（distill 2317 设置而成，代码与 V2317 完全一致）：修复「软件没重启、仅游戏强退后再重启，悬浮窗会一直保持最小化、需要手动唤醒」的问题——游戏强退后再进、开启「游戏在前台时显示、切到后台时自动最小化」时，被整窗藏起的窗口能自动弹回；
[2] 根因与修法同 V2317 开发线：新增 _force_fg_sync 标志，扫描到新游戏进程接入时置位，下一拍前后台同步强制按当前前台判定补一次弹出（仅前台且窗口隐藏才弹出，绝不强制隐藏）；干净启动与后台初始态行为完全不变；
[3] 同时包含 V2316「游戏重启后除翻滚外其它模块不渲染」修复；未新增任何设置、UI 不变。

== v23.17 ==
[1] BUGFIX：修复「软件没重启、仅游戏强退后再重启，悬浮窗会一直保持最小化、需要手动唤醒才能恢复显示」的问题；
[2] 根因：开启「游戏在前台时显示、切到后台时自动最小化」后，游戏强退（相当于切到后台）会把全部模块窗口整窗藏起；随后因进程消失 self.pid 变 None，把上一拍的前后台边沿状态复位成 None；游戏重进时重连逻辑又把该状态清成 None，旧逻辑在「首拍只记录、不动作」分支下被藏起的窗口永远不会自动弹出，必须手动唤醒；
[3] 修法：新增 _force_fg_sync 标志，扫描到新游戏进程接入时置位，下一拍前后台同步强制按「当前是否在前台」补一次弹出（仅在前台且窗口被隐藏时弹出，绝不强制隐藏），从而重进后自动恢复显示；干净启动与后台初始态行为完全不变。未新增任何设置、UI 不变。

== v23.16 ==
[1] BUGFIX：修复「软件没重启、仅游戏重启（强退后再进）后，只有翻滚模块正常、其余四个模块（核心检测 / 全 Buff / Boss Buff / 能力冷却）都不渲染」的问题；
[2] 根因：战斗状态判定依赖的 quest_mgr（任务管理器地址）在游戏进程关闭 / 重启后没有清空，仍指向旧进程地址，新句柄读旧地址得到野指针 → in_combat 误判 False → 开启「非战斗隐藏」时除翻滚外所有模块内容被隐藏（翻滚刻意忽略该机制，故独善其身）；
[3] 修法：close_handle() 与 scan() 重连分支两处强制 self.quest_mgr = None，游戏重启后必定重新解析任务管理器地址。行为零变化、UI 不变、未新增任何设置。

== v23.15 ==
[1] 第二轮冗余清理：继续只删「算了但不用」的死代码，并修掉一批会误导排查的陈旧日志行号；行为零变化、渲染结果完全不变；
[2] 【G 级】删除 4 个零调用的函数（共 63 行）：设置面板「门限」页里 allbuff 与 boss 两组对称代码各定义了 3 个工厂函数，其中「灰色固化复选框」与「固化数值行」这两个自 V2243 把四条门限改成可勾选之后就再也没人调用，只有「说明文字」那个还在用；
[3] 【H 级】删除 4 个「只写不读」的内部变量：翻滚图标的一个废弃缓存、任务管理器的一个扫描基址（4 处写入、0 处读取）、一个名为 ui_scale 的缩放值（三个模块窗口每帧都在写它，但全软件没有任何地方读它，真正生效的缩放走另一套值——删掉后每帧还少 3 次无用写入）、以及自更新流程里一个恒定写空的对话框句柄；
[4] 【I 级】修 55 处日志里的硬编码行号：形如「已忽略异常 @line 4604」的数字是当年手工填的，代码从约 6000 行涨到 13800 行之后，这 55 条**全部**对不上真实行号（偏差 4 到 2000 多行，其中 3 条甚至是没填过的 0）。改为不再写死行号——日志本身已带完整调用栈，里面是真实的文件名、行号与函数名，而且直接指向出错的那一行，比写死的数字更准、也不会再次失效；
[5] 【工具链】新增三个自查脚本（死函数 / 死变量 / 重复代码块），并修复一个**会误删在用翻译**的判定 bug：旧判定直接拿源码原文和文案表比对，而源码里换行是 \n 两个字符、文案表里是真正的换行，导致所有带换行的文案都被误判成没人用（实测误报 6 条，全部是在用的），修正后误报归零、一条都没误删；
[6] 复核结果：死函数 0、死变量 0、死常量 0、未使用的 import 0、孤儿设置键 0、孤儿文案 0、翻译缺失 0；重复代码块 5 段（6 行阈值下 30 段）全部是 allbuff 与 boss 刻意保持的对称结构，可合并的 0 处。源码 13874 行 → 13825 行。

== v23.14 ==
[1] 全代码冗余彻底排查后的 A~E 级清理：只删「算了但不用」的死代码，顺手修 5 处多语言漏接；行为零变化、渲染结果完全不变；
[2] 【A 级】删除 Boss 模块 4 处死赋值 + 1 处重复赋值：ex_excl / ex_mast（Boss 的角色专属 / 专精过滤自 V2226 起已固化为无条件剔除，且 Boss 侧从未有过对应 UI 控件，两个设置键同步移除）、g_conflict（层数矛盾检查已固化，该键早已在保存时被清理）、g_durmax（真正生效的是 boss_gate_duration_max_with_infinite_exemption）、重复的 g_e_durmax；
[3] 【B 级】删除 V2019 / V2020 遗留的 6 个 Windows API 声明与 _SHELL_CLASS_NAMES 常量——它们只有声明、零次实际调用，前后台判定实际只走 get_foreground_pid()；计划中的 EnumWindows 交叉验证从未接上（诊断日志里恒为 n/a 的 enum_state 字段就是证据），共删 24 行；同时连带移除该计划残留的死参数 enum_state——它恒为 n/a，却贯穿函数签名、去重判定、日志条目与文件表头共 9 处；
[4] 【C 级】删除 12 个孤儿设置键（V2239 门限合并后的 8 个旧键 + boss_name_keywords + boss_keep_backdrop_when_absent + 2 个 V2236 残留的闪光键）；其中 8 个旧键在保存与重置时还会被重写为 True，必须成对删除，否则会退化成野键，共删 27 行；
[5] 【D 级】i18n 文案表删除 168 条历史残留条目（655 → 487）。判定标准很严：源码里还有一批内联四语字典在独立提供翻译，那些条目虽然没走统一翻译接口、但界面确实在用，一律保留（16 条），只有源码里任何地方都找不到的才删；
[6] 【D 级附带修复】修 5 处多语言漏接：「未设置」（4 处）与「按下组合键…」（1 处）此前写死中文，切到英文 / 繁中 / 日文时仍然显示中文，现已接回统一翻译接口；
[7] 【E 级】删除 3 个死常量；删除 2 处 fm2 = QFontMetrics(f2)——每个 buff 卡片每帧都会新建一个字体度量对象却从不使用（V2073 的写法早已被 stacks_h 取代），属于实打实的每帧开销；4 处占位变量规范化；死赋值审计 24 处 → 13 处（剩余均为约定性解包占位，刻意保留）；
[8] 不动任何 UI、不删任何玩家可见功能。未使用的 import 0 条、常量条件死分支 0 处、翻译缺失 0 条。

== v23.13 ==

- 第 1~5 次翻滚的内嵌默认 PNG 换成新图（原「虾」图标已替换）。
- 第 6/7 次新增「样式」下拉：「警告三角形」（程序绘制的红边黄底三角，旧行为、仍是默认）或「图片」。
- 选「图片」时可二选一：内置默认警告图，或自己指定任意 PNG（有浏览按钮），另有独立的「警告图缩放」百分比。
- 闪光彻底图片无关化：警告图复用与第 1~5 次完全同一条路径（alpha>128 的像素填闪光色 + 放大脉冲），换任何 PNG 都自动跟上。
- 修复：闪光实心缓存此前建一次后永不失效，换 PNG / 改闪光色后闪光帧仍画旧图标剪影（「换图片闪光跟不上」的真因）；现在每次重载图标都清空缓存。
- 图片无效或路径缺失时自动回退成警告三角形，绝不留空白槽位。

== v23.12 ===

- 修正 V2311 的错选：用户原意是保留 V2264 的「斜向两分面」，结果 V2311 误留「中线高光」。下拉菜单现在是「纯色」与「斜向两分面（V2264 风格，最像 3D 棱锥/钻石）」两种。
- 彻底移除「中线高光」及其参数键 spike_3d_line_width，不留任何死代码。
- 恢复 V2264 原版 two_tone 最简算法——沿尖刺左→右方向做 0.48-0.52 硬边渐变（左亮右暗），无光向参与。
- 默认 spike_3d_style 改回「two_tone」（V2264 默认值）。


- 「two_tone」3D 风格升级为「棱柱面对齐」：棱线永远沿尖刺对称轴（root→tip），不再随光变。
- 哪边亮、哪边暗由「光向在对称轴垂直方向的投影」符号决定，每面内部按光向做线性渐变。
- 新增「渐变幅度」滑块（0–100%，默认 35%）控制每面内部明暗强度；0 时退化为纯色。
- 参数 spike_3d_twotone_light/dark 已替换为 spike_3d_ridge_face_light/dark/amplitude。

调试数据模式（不开游戏也能测 UI）新增「各类别注入数量」：全 Buff / Boss 两模块的「调试数据」页各加 4 个数量框——普通 Buff / Debuff / 永续 / 尾声，分别控制注入多少个该类假 buff。
· 默认即给混合（全 Buff 8 普通+2Debuff+1永续+1尾声，Boss 5+1+1+1），一开调试就看到各种可能性；Debuff 调试条目现能被正确归类为 debuff 渲染（之前因统一覆盖字典恒判非 debuff 而看不到）。拖动实时生效。
== v23.06 ==
修复 V2304 调试数据模式下「全 Buff / Boss 模块空白、核心模块正常」的真因
· 根因：调试假 buff 的 sid 是 0xD001/D101（53249/53505），远超你为正常游戏设的 status_id_max（常见 3000），被数值门限整批丢弃；核心模块用 active_buffs 字典不查该门限故正常。
· 修法：调试态下 render_allbuff / render_bossbuff 直接跳过所有门限与过滤开关，保证假 buff 一定全显，不受任何门限值影响；同时移除 V2305 误加的「自动排布到屏幕中央」按钮（位置本就在屏内，与空白无关）。
== v23.05 ==
修复 V2304「调试数据」看不到模块的问题
· 模块默认坐标（核心 y=568、全Buff y=1114、Boss y=8）常被任务栏盖住或落在屏幕外，开启调试数据后全Buff和Boss的假数据其实在后台渲染、但桌面上看不到。
· 调试数据页顶部新增「📌 自动排布5模块到屏幕中央」按钮，一键把五个模块（核心 / 翻滚 / 能力 / 全Buff / Boss）按顺序竖排在屏幕中央可见区域，立刻能对照假数据调外观。

== v23.04 ==
新增「调试数据」：不开游戏也能在桌面上调所有模块的外观
· 位置：设置 → 全局 → 常规 → 调试数据。打开总开关后，五个模块（核心检测 / 全 Buff / Boss Buff / 能力冷却 / 翻滚）立刻显示一整套假数据。
· 通用参数：显示文本（默认「测试带编码」）、倒计时（默认 8.88）、角色状态、是否战斗中、专精（无 / 觉醒 / 真谛 / 秘义）。
· 核心：buff 数量 0–24（默认 3）、单层开关、满层开关（默认开）、层数、最大层数（默认 8）、觉醒 / 真谛 / 秘义 标记。
· 全 Buff / Boss：张数（默认 12 / 8）、层数、最大层数、永续开关；能力冷却：槽数 0–4、已就绪数（默认 1）、冷却上限（默认 30.0 秒）；翻滚：次数 0–7。
· 所有假 buff 与技能名统一显示为设定文本，不走 buff 名表 / 技能名表，方便一眼看出长文本会不会挤爆排版。
· 26 个选项全部实时生效（拖动即变）；关掉总开关立即回到读游戏的正常模式。

== v23.03 ==
尖刺明暗渐变更细腻：平滑过渡 + 方向和强度跟随投影 XY
· 硬边保留：亮面和暗面仍是两坨色块、中间硬边分界（棱锥/钻石的立体感来源），不做平滑过渡。
· 方向跟随：渐变方向 = 投影 XY 的方向（光从哪边打过来，哪边就亮）。光斜着照时根部和尖端也会产生明暗差。
· 强度跟随：渐变强度 = 投影 XY 的大小。偏移越大对比越强；XY 都是 0 时自动变回纯色。

== v23.02 ==
修复「3D 效果」标签页另一个隐蔽 bug：12 根尖刺亮/暗方向错位
· 问题：12 根尖刺在圆周上径向朝向，但两种风格一直用世界坐标方向画渐变，所以只有最上方那根尖刺方向是对的，其他编号的亮/暗位置全错。
· 修法：身体渐变跟着每根尖刺的局部朝向旋转，光从哪边来，亮面就在那一侧。影子方向保持世界坐标不变——定向光的世界方向是固定的。

== v23.01 ==
「3D 效果」标签页改为实时生效
· 问题：该页共 20 个选项，其中 15 个改动后必须关闭设置窗口才生效——拖动滑块或勾选开关时主界面看不到任何变化，只能靠猜。
· 涉及：投影开关与偏移 X/Y、投影不透明度、暗描边开关与暗度、两分面明暗因子、边缘高光带明暗与宽度、底部阴影暗度与高度、小球明暗因子。
· 修复：为这 15 个选项补上即时生效，现在调参可以边拖边看效果。
· 说明：本版只处理 3D 标签页这一处，没有动其他设置项。

== v23.00 ==
修复「随游戏前后台自动切换」：切后台不隐藏 + 回前台只出两个模块
· 症状①：切到后台时，两个 buff 模块照样出现（另外三个正常隐藏）。
· 症状②：切回前台时，只剩这两个 buff 模块，核心／翻滚／能力三个模块出不来。
· 根因：模块窗口的显隐判断分散在四处、彼此覆盖。负责前后台的定时器（250 毫秒）刚把窗口藏好，另一处只认「模块开关」、完全不知道游戏是否在前台的代码就会把它们又显示出来——后台期间只要进出战斗或训练场状态翻一下（或改一下设置）就会触发。
· 于是那两个模块一直可见，「有窗口可见」这个判断恒为真，回前台时的「全部显示」动作因条件不成立被跳过，另外三个模块就再也出不来了。
· 修法：把显隐判断收敛为单一裁决入口，明确优先级——游戏在后台时一律隐藏，其次才看模块开关。四处调用点改为只登记「意图」，不再各自直接操作窗口。
· 附带修复：标题栏最小化按钮原先是裸循环隐藏、不登记意图，导致点了最小化后会被自动弹回。

== v22.64 ==
修复 V2263 的崩溃问题 + 新增构建前自检脚本
· 问题：新增的「3D 效果」设置子页用到了 QStackedWidget，但导入列表里漏了它，导致一打开设置对话框就报 NameError 并退出。
· 修复：在 PySide6.QtWidgets 的导入列表中补上 QStackedWidget。
· 新增：通用「未定义名」检查脚本，构建前自动扫描源码里「用了却没定义/没导入」的名字。实测把导入删掉后能精确报出出错行，杜绝同类漏导入问题。

== v22.63 ==
尖刺/小球立体感改为「可调风格」架构：核心检测模块新增「3D 效果」子页。
· 尖刺 5 种立体风格：纯色 / 中线高光(V2262) / 斜向两分面（最像 3D 棱锥·钻石）/ 边缘宽高光带 / 底厚阴影
· 小球 2 种风格：纯色 / 径向球化（推荐）
· 通用投影：启用开关 + 偏移 X/Y + 不透明度（0-255）
· 通用暗描边：启用开关 + 宽度（0.0-3.0px）+ 暗度（100-200）
· 各风格独立参数（随下拉动态显隐、实时生效，可在线对比调参，无需重新构建）
· 默认改为「斜向两分面」+ 投影偏移 (4,5) + 不透明度 120
· 新增 20 个设置键、39 条三语文案

== v22.62 ==
【尖刺/小球立体感重构：统一光源 + 小球球化 + 投影】
1) 现象：此前尖刺填充用了「根部压暗→原色→尖端提亮」的大跨度线性渐变（暗 135% / 亮 140%），导致你设定的尖刺色只在 42% 长度处出现，根与尖都被染色，整体看起来"不是纯色、有渐变"。
2) 修复：改为「统一光源」模型（光来自左上），尖刺改为**纯色填充**你给定的颜色，仅叠加：①沿中线一条 1px 凸起高光线（lighter 128）②1px 暗描边（darker 150）③整根尖刺向右下偏移的半透明投影——颜色保真度从约 60% 提升到约 95%，同时保留立体/厚度感。
3) 装饰小球：由原本单纯 darker(110) 平涂，改为**径向渐变球化**（左上高光 lighter 160 → 基色 → 边缘 darker 125），立刻呈现圆球质感。
4) 圆环：新增整环向右下偏移的半透明暗环投影，与尖刺/小球共用同一光源方向，"浮起"厚度更一致。
5) 新层出现时的白色外扩闪光动画不受影响，仍为瞬时动画。未改动任何设置键 / UI / i18n。
== v22.61 ==
【修正圆环外勾边偏薄、且数值较小时不显示的问题】
1) 现象：把「外勾边」调到某个数值时，圆环上的勾边明显比尖刺和装饰小球上的更细；而且数值调到 1 或 2 时，圆环上完全看不到勾边，要调到 3 以上才出现。
2) 原因：圆环勾边原本是贴着圆环中心线画的，而圆环本体（带阴影边的那一层）会更晚绘制、直接盖在上面。圆环本体比勾边宽，于是把勾边整个吃掉了大半——数值小的时候全被盖住，数值大了也只剩一小条。尖刺和装饰小球是实心的，只会盖住勾边靠内的一半，所以看起来正常。
3) 修复：把圆环勾边挪到圆环外沿再来画，让它露在外面的宽度与尖刺、装饰小球完全一致。现在数值 1 起就能看到，且三者粗细一致。

== v22.60 ==
【新增门限：剩余时间 > 持续时间时丢弃】
1) 主控全 Buff 与 Boss Buff 两个模块的「门限」页各新增一条**可勾选**规则：「⑤ 剩余时间 > 持续时间丢弃」，默认开启。
2) 作用：正常情况下剩余时间不可能比持续时间还长。一旦出现这种情况，基本可以断定读到的是脏数据或异常残留，勾选后直接丢弃该条，不显示。
3) 例外：永续 buff（显示为无穷符号）不受此限——它的持续时间记录可能是 0，而剩余时间残留正数，这是正常现象，不会被误杀。
4) 不需要时可在门限页取消勾选，该条检查即被跳过。

== v22.59 ==
【修复「恢复默认」把配置冲掉的问题 + 按最新配置重新烘焙】
1) 修复「点恢复默认后，Buff 启用/禁用页里所有勾选框都被勾上」。原因不是烘焙出错——烘焙进默认值的配置完全正确——而是重置代码里有三处写死的值绕过了默认值表：
   · Buff 专精勾选：重置时被无条件全部勾上（而不是按你配置里实际的勾选状态还原）。现已改为逐项还原。
   · 全局快捷键：三项被写死成一组固定值，会把你配好的组合键冲掉，其中「锁定窗口」「打开设置」两个还会被一并禁用。现已改为按默认值还原。
   · 标题栏对齐：写死为「靠左」，你当前设置恰好也是靠左所以一直没暴露。现已改为按默认值还原。
2) 已对「恢复默认」与「读取设置」两处代码做全量复查（合计 650 余行），除以上三处外，再无其它绕过默认值表的写死赋值。
3) 同时用你**当前最新的配置**重新烘焙了一遍默认值（界面语言仍固定为简体中文，不跟随快照）。现在点「恢复默认」，结果应当与你最后一次打开软件时的状态一致。

== v22.58 ==
【恢复默认的语言改回简体中文】
1) 上一版把你的配置完整烘焙为默认值时，语言这一项被一并烘成了「日文」（因为烘焙时你正在使用日文界面）。
2) 已按你的要求改回：点「恢复默认」时，界面语言统一回到**简体中文**。
3) 除语言外的其余全部设置保持不变，仍然是你烘焙进去的那一份配置。

== v22.57 ==
【把当前配置完整烘焙为默认值】
1) 应玩家要求，将你当前正在使用的这份配置（软件目录下的 overlay_settings.json，共 359 项）**完整烘焙进程序内置的默认值表**。今后点「恢复默认」，就会精确恢复成这份配置，而不再是一套出厂的通用参数。
2) 比对结果：内置默认值原本 351 项，你的配置有 359 项——你的配置完整覆盖了内置默认值（没有遗漏任何一项），并多出 8 项运行时新增的设置。其中 **179 项的数值与旧默认值不同**，已逐项烘焙，没有遗漏。
3) 顺带修复一处「恢复默认」的漏网问题：核心、翻滚、能力三个模块的缩放比例，原本在恢复默认时被写死成 100%，不会跟随默认值（例如你调过的核心模块 73% 会被冲掉）。现在改为与其它两个模块一致，统一读取默认值。

== v22.56 ==
【Buff 编号勘误：混沌转换】
1) 修正一处编号记录错误：「混沌转换」此前被登记为 编号 129（0x81），正确的编号应为 **148（0x94）**。判断依据是软件运行期自动记录的未知 buff 清单——里面实际出现的是 148（0x94），而 129（0x81）在游戏里从未出现过。
2) 已将内置名称表中该条目的编号改正，四种语言的名称（混沌转换 / 混沌輪迴 / Chaos Shift / ケイオシフト）与属性（单层、非角色专属）全部原样保留，条目总数不变。
3) 重要提示：软件目录下的「补充命名文件」（buff_attrs_unknown.json）优先级高于内置名称表。如果你之前的版本在运行目录里已经留下过 148（0x94）的占位记录，它会把新表里的正确名字盖掉——遇到「改了却不生效」的情况，把该文件删除即可，重启软件后会自动重建，里面仍然未知的编号不会丢失。

== v22.55 ==
【切换语言不生效——系统性修复】
1) 玩家反馈：切成日文后，设置面板里「好多选项、好多文本仍然是中文」。逐项排查后结论是——数据层其实是干净的（界面翻译表 566 条四语全非空、buff 名 119 条四语齐全、下拉选项 19 个里 16 个在翻译表内、另 3 个是语言名本就不该翻译、源码零硬编码中文），问题全部出在代码。
2) 主因：切语言时的文本刷新逻辑遍历了标签、复选框、按钮、分组框四类控件，却「从不遍历下拉框的选项文字」——所以标签正确变成日文了，而下拉框里的「按出现时间 / 居中 / 靠左 / 靠右 / 顶部对齐 / 底部对齐」仍然是中文。现已新增通用下拉选项翻译：遍历所有下拉框，只改显示文字、不动选项的绑定值，且仅当该文字在翻译表内时才修改（角色名、buff 名等数据项会自动跳过，不会被误伤）。
3) 三处手工写死的刷新代码会把日文/繁体强制写回中文（例如「圆环」在日文下本应显示「円環」，旧代码却写死成中文），已删除，改由上面的通用逻辑统一处理。
4) 切换语言下拉框时，此前只刷新设置窗口自身的文字，没有把新语言推送给主界面。现已补上推送，切换后立即生效。
5) 五个模块窗口各自持有一份「启动时拷贝」的设置快照，此前只有「设置面板实时拖动」这一条路径会回写它，而「设置窗口关闭」的两条分支都不经过 → 模块内读取语言的路径（例如 buff 名称）永远停留在启动时的旧值。现已在设置变化后统一回写，修掉「必须重启软件才生效」的问题。

== v22.54 ==
[About page · 'Important memory addresses & data' panel i18n completed]
1) A player reported the panel did not switch languages. Investigation: the static offset reference table (21 lines) was **raw hardcoded strings** with no `_tr()` at all, so it always displayed Chinese regardless of the selected language; the live-section header and the mastery fallback 'unidentified' were also raw Chinese.
2) Fix: wrapped all 21 static lines in `_tr()` (the `"─"*64` separator is pure symbols, left untranslated); wrapped the live header and the three mastery names (Insight/Essence/Crux) plus the 'unidentified' fallback in `_tr()`.
3) Added 23 keys to i18n.json with zh_tw / en / ja (no zh — `_tr(zh)` returns the key itself as a fallback when lang=="zh", matching the 21 existing panel keys).
4) Technical data (hex offsets / version numbers / field names mgr, record, pptr, node_id) is **kept verbatim** in every language; only the Chinese descriptive parts are translated, so developers comparing offsets are not confused by translation.
5) Verified: the 21 pre-existing live-section keys (e.g. 'Module base    = ') already had all three translations and were not duplicated. i18n audit REAL MISSING=0.

== v23.07 ==
[All Buff / Boss modules now show a stats bar at the top: live counts of Total · Debuff · Infinite · Tail-end]
1) Total = buffs that passed the gates; Debuff = is-debuff flag; Infinite = the infinite (permanent) flag; Tail-end = non-infinite buffs whose remaining/initial is below the countdown tail-end warning threshold.
2) The bar takes a fixed height (1 point smaller than the name font); the grid shifts down and the module window grows by that height, so the text is never clipped.
== v23.15 ==
[1] Second redundancy-cleanup pass: still dead-code-only removal, plus a fix for a batch of stale log line numbers that actively misled debugging. Zero behaviour change, pixel-identical rendering;
[2] [G] Removed 4 never-called functions (63 lines). The "Gates" page defines 3 local factories in each of its two mirrored allbuff / boss scopes; two of them - the greyed-out "fixed" checkbox and the fixed value-row - have had zero callers ever since V2243 turned the four gates into toggleable options. Only the note-label factory is still used;
[3] [H] Removed 4 write-only internal fields: an obsolete dodge-icon cache, a quest-manager scan base address (4 writes, 0 reads), a value named ui_scale that all three module windows rewrite on every single frame while nothing in the whole app ever reads it (real scaling goes through a different pair of values - removing it also drops 3 useless attribute writes per frame), and an update-dialog handle that was only ever set to None;
[4] [I] Fixed 55 hardcoded line numbers inside log messages. Entries like "swallowed exception @line 4604" were typed in by hand years ago; the file has since grown from roughly 6,000 to 13,800 lines, so all 55 now point at the wrong place - off by 4 to more than 2,000 lines, and 3 of them were never filled in at all (literally "@line 0"). The number is dropped rather than corrected: the entry already carries a full traceback with the real file, line and function, and it points at the raising line instead of the handler, which is both more accurate and impossible to let go stale again;
[5] [Tooling] Added three self-audit scripts (dead functions / dead attributes / duplicated blocks) and fixed a check that would have deleted live translations: the orphan test compared raw source text against the translation table, but a newline is the two characters \n in source versus a real newline in the table, so every multi-line string was reported as unused (6 false positives, all of them actually in use). It now compares real string values parsed from the AST - false positives went to zero and no key was removed;
[6] Re-audit: dead functions 0, dead attributes 0, dead constants 0, unused imports 0, orphan setting keys 0, orphan translation keys 0, missing translations 0. All 5 duplicated blocks are the deliberately mirrored allbuff / boss structures - 0 merge candidates. Source 13874 -> 13825 lines.

== v23.14 ==
[1] A~E tier cleanup after a full redundancy audit: removes only dead code that was computed but never used, plus 5 missed i18n wirings. Zero behavior change, pixel-identical rendering.
[2] [A] Removed 4 dead assignments + 1 duplicated assignment in the Boss module: ex_excl / ex_mast (Boss exclusive/mastery filtering has been an unconditional drop since V2226, and the Boss side never had any matching UI control, so both setting keys are removed as well), g_conflict (stack-conflict check is hardcoded), g_durmax (the one that actually works is boss_gate_duration_max_with_infinite_exemption), and a duplicated g_e_durmax read.
[3] [B] Removed 6 leftover Windows API declarations from V2019/V2020 plus the _SHELL_CLASS_NAMES constant. They were declared but never called; foreground detection only ever used get_foreground_pid(). The planned EnumWindows cross-check was never wired up (the enum_state diagnostic field, permanently "n/a", is the proof). 24 lines removed, plus the leftover enum_state dead parameter: permanently "n/a" yet threaded through the function signature, dedup key, log entry and file header - 9 more sites.
[4] [C] Removed 12 orphan setting keys (8 pre-V2239 gate keys, boss_name_keywords, boss_keep_backdrop_when_absent, and 2 leftover V2236 flash keys). 8 of them were also being force-written to True on save/reset, so they had to be deleted in pairs or they would degrade into wild keys. 27 lines removed.
[5] [D] Pruned 168 stale entries from the i18n table (655 -> 487). Deliberately strict: the source still has inline four-language dicts providing translations independently, and those entries are genuinely used by the UI even though they bypass the shared translation helper, so all 16 of them were kept. Only entries absent from every string literal in the source were deleted.
[6] [D, bugfix] Fixed 5 missed i18n wirings: "Not set" (4 places) and "Press a key combination..." (1 place) were hardcoded Chinese and stayed Chinese when switching to English / Traditional Chinese / Japanese. Now routed through the shared translation helper.
[7] [E] Removed 3 dead constants; removed 2x fm2 = QFontMetrics(f2), which built a throwaway font-metrics object for every buff card on every frame (the V2073 usage was replaced long ago) - real per-frame overhead. Normalized 4 throwaway variables. Dead-assignment audit: 24 -> 13 (the rest are conventional tuple-unpack placeholders, kept on purpose).
[8] No UI is touched and no player-visible feature is removed. Unused imports: 0. Constant-condition dead branches: 0. Missing translations: 0.

== v23.13 ==

- The embedded default PNG for dodges 1-5 is replaced with a new image (the old "shrimp" icon is gone).
- Dodges 6/7 now have a "Style" dropdown: "Warning triangle" (the drawn red-bordered yellow triangle - old behaviour, still the default) or "Image".
- With "Image" you can use the built-in default warning image or point at any PNG (browse button included), plus a separate "Warning image scale" percentage.
- Flashing is now fully image-agnostic: the warning image reuses the exact same path as dodges 1-5 (fill pixels with alpha>128 in the flash color + a scale pulse), so any PNG just works.
- Fixed: the solid-flash cache was built once and never invalidated, so after changing the PNG or the flash color the flash frames still drew the old icon silhouette (the real cause of "flashing doesn't follow my new image"); the cache is now cleared whenever icons reload.
- If the image is invalid or the path is empty it falls back to the warning triangle - never a blank slot.

== v23.12 ===

- Fix V2311's mistake: the user wanted V2264 'Diagonal two-tone' preserved, but V2311 kept 'Highlight Line' by accident. Dropdown now offers 'Plain (flat)' and 'Diagonal two-tone (V2264 style, most like a 3D pyramid/diamond)'.
- 'Highlight Line' and its parameter key spike_3d_line_width are fully removed (no dead code left).
- Restored the V2264 original two-tone algorithm: 0.48 / 0.52 hard-edge gradient along the spike's left→right direction (bright on left, dark on right), with no light-direction involvement.
- Default spike_3d_style switched back to 'two_tone' (V2264 default).


- 'two_tone' 3D style upgraded to 'Ridge-Face Aligned': the ridge line always follows the spike's symmetry axis (root → tip), independent of light direction.
- Which side is bright vs dark is decided by projecting the light vector onto the axis-perpendicular; each face has its own light-direction linear gradient.
- New 'Gradient Amplitude' slider (0–100%, default 35%) controls the per-face intensity; degrades to flat color at 0.
- Params spike_3d_twotone_light/dark replaced by spike_3d_ridge_face_light/dark/amplitude.

Debug-data mode (test UI without the game running) now has per-category injection counts: the "Debug Data" tab of both the All-Buff and Boss modules gets 4 count boxes - Normal Buff / Debuff / Permanent / Tail-end - each controlling how many fake buffs of that category to inject.
· Defaults to a mix (All-Buff: 8 normal + 2 debuff + 1 permanent + 1 tail-end; Boss: 5+1+1+1) so you see every possibility the moment debug is on; debug Debuff entries are now correctly classified as debuff for rendering (previously the unified override dict forced non-debuff, so they never showed). Changes apply live.
2) Both Buff modules (All Buff / Boss) now get 4 'count cap' options on the Category Display tab: Max Normal Buffs / Max Debuffs / Max Permanent / Max Tail-end (range 0–99, 0 = no limit).
3) Applied after gates/exclusions and before the grid truncation: the first N of each category are kept by current order; all four at 0 short-circuits with zero overhead (shows everything). Changes apply live as you drag.
== v23.06 ==
[Fixes the real cause of V2304 Debug Data showing blank All Buff / Boss modules while Core worked]
1) Root cause: debug fake buffs use sids 0xD001/D101 (53249/53505), far above the status_id_max you set for normal play (commonly 3000), so they were dropped entirely by the numeric gates; Core uses the active_buffs dict and skips that gate, hence it worked.
2) Fix: in debug mode render_allbuff / render_bossbuff skip all gates and filter switches, so fake buffs always show regardless of any gate value; also removes the mistaken V2305 'snap to screen center' button (positions were already on-screen and unrelated to the blank issue).
== v23.05 ==
[Fixes the V2304 Debug Data feature where modules were invisible]
1) Default module positions (core y=568, All Buff y=1114, Boss y=8) often land under the taskbar or off-screen, so the All Buff and Boss fake data was being rendered in the background but not visible on the desktop.
2) New button at the top of the Debug Data page labeled "📌 Snap 5 modules to screen center" - one click stacks all five modules (Core / Dodge / Ability / All Buff / Boss) vertically and centered in the visible screen area, putting the fake data right in front of you for live layout tuning.

== v23.04 ==
[New Debug Data page: tune every module on your desktop without launching the game]
1) Location: Settings -> Global -> General -> Debug Data. Flip the master switch and all five modules (Core, All Buffs, Boss Buffs, Ability Cooldown, Dodge) immediately show a full set of fake data.
2) Shared parameters: display text (one editable string used everywhere), countdown value (8.88 by default), character status, in-combat flag, mastery (none / Awakening / Truth / Secret).
3) Core module: buff count 0-24 (3 by default), single-layer toggle, full-stack toggle (on by default), stack count, max stacks (8 by default), Awakening / Truth / Secret flags.
4) All-Buff / Boss modules: card count (12 / 8 by default), stacks, max stacks, infinite toggle. Ability Cooldown: slot count 0-4, ready slots (1 by default), cooldown ceiling (30.0 s by default). Dodge: count 0-7.
5) Every fake buff and skill name renders as the string you typed, bypassing the buff-name and ability-name tables, so it is obvious at a glance whether long text breaks the layout.
6) All 26 options apply live (drag and see it change); turning the master switch off returns to normal game-reading mode instantly.

== v23.03 ==
[Smoother spike shading: gradient direction and strength now follow the shadow X/Y]
1) Hard edge kept: the bright and dark faces remain two colour blocks with a hard facet edge between them (that is what gives the prism/diamond look) - no smoothing is applied.
2) Direction follows the light: the gradient axis is the shadow X/Y direction, so whichever side the light comes from is lit. When light arrives at an angle, the base and tip of each spike also pick up a brightness difference.
3) Strength follows the offset: a larger shadow offset means stronger contrast; when X and Y are both 0 (or the shadow is disabled) it falls back to a flat colour.

== v23.02 ==
[Fixes another hidden bug on the 3D Effect tab: bright/dark sides swapped on most spikes]
1) Problem: the 12 spikes are radially arranged on a circle (one every 30°), but the Two-Tone and Edge Band styles have always used world-space coordinates for their gradient direction. Only the top spike rendered correctly — every other spike had its bright and dark sides swapped.
2) Fix: the body shading now rotates with each spike's local orientation, so the bright side is always the side facing the light.
3) About the shadow: the shadow offset stays in world coordinates — a directional light is fixed in world space, so all shadows correctly fall in the same direction.

== v23.01 ==
[The 3D Effect tab now applies changes live]
1) Problem: that page has 20 options, and 15 of them only took effect after closing the settings dialog — nothing changed on screen while dragging a slider or ticking a toggle, so you had to guess.
2) Affected: shadow toggle and offset X/Y, shadow alpha, outline toggle and darkness, two-tone light/dark factors, edge band light/dark/width, bottom shadow darkness/height, and the bead light/dark factors.
3) Fix: those 15 options now apply instantly, so you can tune while watching the effect.
4) Note: this version only touches the 3D Effect tab; no other settings were changed.

== v23.00 ==
[Fixed auto show/hide on game focus: not hiding on blur, only two modules returning]
1) Symptom 1: when the game went to the background, the two buff modules stayed visible (the other three hid correctly).
2) Symptom 2: returning to the foreground, only those two buff modules came back; the core, dodge and skill modules stayed hidden.
3) Cause: window visibility decisions were duplicated across four places that overrode each other. The focus timer (250 ms) had just hidden the windows when another code path, which only looked at the module toggle and knew nothing about foreground state, showed them again — triggered whenever the in-combat or training-area state flipped while in the background, or a setting was changed.
4) Because those two modules were always visible, the "any window visible" check was permanently true, so the "show all" action on returning to the foreground was skipped by its own condition and the other three never came back.
5) Fix: all visibility decisions now go through a single arbiter with an explicit priority — game in background hides everything, then module toggles are applied. The four call sites now only record intent instead of touching windows directly.
6) Bonus fix: the title bar minimize button used a raw hide loop that recorded no intent, so windows could reappear on their own after minimizing. It now uses the same arbiter.

== v22.64 ==
[Fixes the v22.63 crash + adds a pre-build self-check script]
1) Problem: the new "3D Effect" settings sub-tab used QStackedWidget, but it was missing from the PySide6.QtWidgets import list, so opening the settings dialog raised `NameError: name 'QStackedWidget' is not defined` and quit.
2) Fix: added QStackedWidget to the import list.
3) New: a generic "undefined name" checker (ast-based, scope-aware) that scans the source for names used but never defined or imported. It is run before every build. Verified by deleting the import — the checker then reports the exact offending lines, so this class of mistake cannot slip through again.

== v22.63 ==
[Spike / bead 3D shading is now a selectable, tunable style system]
1) A new "3D Effect" sub-tab is added under the Core Detection module, gathering every 3D-related control in one place.
2) Spikes now offer 5 shading styles: Solid (no 3D) / Midline Highlight (the V2262 look) / Diagonal Two-Tone (the most 3D, like a faceted prism or diamond) / Wide Edge Band (lighter and darker bands on the sides, your base colour kept in the middle) / Bottom Shadow (tip keeps your colour, root near the ring darkens).
3) Beads offer 2 styles: Solid / Radial Sphere (recommended), with adjustable highlight light factor, edge dark factor and highlight centre offset.
4) Two shared groups apply to every style: a drop shadow (enable, offset X, offset Y, alpha 0-255) and a dark outline (enable, width 0.0-3.0px, darkness 100-200).
5) Per-style parameters sit in a stacked panel that shows or hides itself to match the dropdown, and every control applies live — you can switch between styles and compare them on screen without rebuilding.
6) Defaults changed: style = Diagonal Two-Tone, shadow offset (4,5), shadow alpha 120.
7) Adds 20 new settings and 39 new localized strings (zh_tw / en / ja).

== v22.62 ==
[Spike / bead 3D shading rebuilt: unified light source, shaded beads, drop shadow]
1) Symptom: the spike fill used a wide root-to-tip gradient (dark 135% at the root, your colour at 42%, light 140% at the tip), so your chosen colour only appeared partway along the spike and both ends were tinted. The result never looked like the solid colour you picked.
2) Fix: switched to a unified light source model (light from upper-left). The spike is now filled with your exact colour, and depth comes only from three additions: a 1px raised highlight along the midline (lighter 128), a 1px dark outline (darker 150), and a translucent shadow copy offset down-right. Colour fidelity rises from roughly 60% to roughly 95% while keeping a sense of relief and thickness.
3) Beads: changed from a flat darker(110) fill to a radial sphere shading (upper-left highlight lighter 160, base colour, edge darker 125), giving an immediate ball-like look.
4) Ring: added a translucent shadow ring offset down-right, sharing the same light direction as the spikes and beads so the whole indicator floats consistently.
5) The white outward flash animation when a new stack appears is unaffected. No settings, UI or i18n changes in this version.

== v22.61 ==
[Fixed: ring outline looked thinner than the spike/bead outline and vanished at low values]
1) Symptom: at the same outline width setting, the outline around the ring was noticeably thinner than the one on the spikes and the decorative beads. At width 1 or 2 it disappeared from the ring entirely and only showed up from 3 upwards.
2) Cause: the ring outline was stroked along the ring's centre line, but the ring body (the layer with the shadow edge) is drawn afterwards and is wider - so it swallowed most of the stroke. At small widths it covered it completely; at larger widths only a sliver survived. Spikes and beads are solid shapes, so they only cover the inner half of their stroke, which is why they looked correct.
3) Fix: the ring outline is now stroked around the outer edge of the ring instead, so the visible width matches the spikes and beads exactly. It is now visible from width 1 upwards, and all three are consistent.

== v22.60 ==
[New gate: drop entries whose remaining time exceeds their duration]
1) The Gates page of both the All Buffs and Boss Buff modules gains a new **toggleable** rule: "Drop if remaining > duration", enabled by default.
2) Purpose: remaining time can never legitimately exceed total duration. When it does, the entry is almost certainly garbage or a stale slot - check this to discard it instead of displaying it.
3) Exception: permanent buffs (shown with the infinity symbol) are exempt. Their duration field may read 0 while remaining holds a leftover positive value, which is normal and will not be filtered out.
4) Uncheck it on the Gates page to skip this check entirely.

== v22.59 ==
[Fix "Reset to Defaults" overwriting your settings + re-bake from the latest config]
1) Fixed: after "Reset to Defaults", every checkbox on the Buff enable/disable page became checked. The baked defaults were NOT wrong - they matched your configuration exactly. The cause was three hardcoded values in the reset routine that bypassed the defaults table:
   - Buff mastery checkboxes: unconditionally checked every box on reset instead of restoring your actual per-buff state. Now restored item by item.
   - Global hotkeys: all three were pinned to a fixed set, wiping your configured key combos, and additionally disabling the "Lock windows" and "Open settings" hotkeys. Now restored from defaults.
   - Title bar alignment: pinned to "Left". Your current value happened to be Left too, so it never showed. Now restored from defaults.
2) Audited the entire reset routine and the settings-read routine (650+ lines combined): apart from the three above, no other assignment bypasses the defaults table.
3) Also re-baked the defaults from your **current, latest** configuration (interface language remains pinned to Simplified Chinese and does not follow the snapshot). "Reset to Defaults" should now reproduce exactly how the app looked the last time you opened it.

== v22.58 ==
[Reset-to-defaults language back to Simplified Chinese]
1) When the previous version baked your configuration into the defaults, the language entry was baked in as "Japanese" - because you were running the Japanese UI at that moment.
2) Changed back as requested: "Reset to Defaults" now returns the interface language to **Simplified Chinese**.
3) Every other setting is untouched and still matches the configuration you baked in.

== v22.57 ==
[Bake current configuration into defaults]
1) By player request, your current live configuration (overlay_settings.json next to the executable - 359 entries) has been **fully baked into the built-in defaults table**. From now on "Reset to Defaults" restores exactly this configuration instead of a generic factory set.
2) Comparison: the built-in defaults had 351 entries, your configuration has 359 - it fully covers the built-in defaults (nothing missing) plus 8 entries added at runtime. **179 entries differ in value** from the old defaults and every one of them has been baked in.
3) Also fixed a leak in the reset routine: the scale of the Core, Dodge and Skill modules was hardcoded to 100% on reset and ignored the defaults table (so e.g. your adjusted Core scale of 73% was lost). They now read from defaults like the other two modules already did.

== v22.56 ==
[Buff ID correction: Chaos Shift]
1) Fixed a wrongly recorded buff ID: "Chaos Shift" was previously registered as ID 129 (0x81); the correct ID is **148 (0x94)**. The evidence comes from the unknown-buff list the app records at runtime - 148 (0x94) actually appeared there, while 129 (0x81) never showed up in-game at all.
2) The entry in the built-in name table has been moved to the correct ID. All four language names (simplified / traditional Chinese, English, Japanese) and its attributes (single-layer, not character-exclusive) are preserved unchanged; the total entry count is unchanged.
3) Important: the supplemental naming file next to the executable (buff_attrs_unknown.json) takes priority over the built-in table. If an older version already left a placeholder record for 148 (0x94) in your run directory, it will override the corrected name. If the fix appears to have no effect, simply delete that file - the app rebuilds it on next start, and IDs that are still unknown are not lost.

== v22.55 ==
[Language switching not taking effect - systematic fix]
1) Player report: after switching to Japanese, "many options and much text in the settings panel were still Chinese". A module-by-module audit showed the data layer was actually clean (566 UI translation keys with all four languages populated, 119 buff-name entries complete in four languages, 16 of 19 combo items present in the translation table and the other 3 being language names that should never be translated, zero hardcoded Chinese strings in source) - the bugs were all in code.
2) Root cause: the retranslate routine refreshed QLabel, QCheckBox, QPushButton and QGroupBox text but "never iterated combo box items" - so labels correctly turned Japanese while drop-down entries such as "By appearance time / Center / Left / Right / Top / Bottom" stayed Chinese. Added a generic combo-item translation pass: walks every combo box, changes only the display text (never the bound itemData), and only when that text exists in the translation table (data entries like character names and buff names are skipped automatically, so nothing gets corrupted).
3) Three hand-hardcoded refresh blocks forced Japanese/Traditional Chinese back to Chinese (e.g. the ring timer style should render as the Japanese term, but old code pinned the Chinese word). Removed; the generic pass above now handles them correctly in all four languages.
4) Changing the language drop-down previously refreshed only the settings window itself and never pushed the new language to the overlay. The push is now wired up, so switching takes effect immediately.
5) Each of the five module windows keeps its own snapshot of settings copied at construction time. Only the "live drag in settings panel" path wrote back to it; neither branch of "settings dialog closed" went through that path, so anything reading language inside a module (e.g. buff names) stayed at the startup value. Settings are now written back uniformly after any settings change, fixing the "requires restart" behaviour.

== v22.54 ==
【关于页 · 「重要内存地址与数据」面板多语言补齐】
① 玩家反馈该面板在不同语言下不切换。经查：静态偏移速查表（21 行）此前是**裸字符串硬编码**，完全没走 `_tr()`，无论切什么语言都显示中文；实时区标题与专精 fallback「未识别」同样是裸中文。
② 修复：`static_part` 21 行中文全部包 `_tr()`（`"─"*64` 分隔线为纯符号不译）；实时区标题【实时 · 运行期值（每 1 秒刷新）】包 `_tr()`；专精三系名（觉醒/真谛/秘义）与 fallback「未识别」包 `_tr()`。
③ i18n.json 补 23 个 key 的 zh_tw / en / ja 三语（zh 不写——`_tr(zh)` 在 lang=="zh" 时直接返回 key 本身走 fallback，与面板已有 21 个 key 写法一致）。
④ 技术信息（hex 偏移 / 版本号 / 字段名 mgr、record、pptr、node_id）在各语言里**原样保留不译**，只译中文说明部分，保证开发者对照偏移时不被翻译干扰。
⑤ 经核对：实时区原有 21 个 key（如「模块基址 base    = 」）三语本就齐全，本次未重复添加。i18n 审计 REAL MISSING=0。

== v22.53 ==
[Screen-edge alignment now applies at startup (fix: 'only works after opening Settings once')]
1) User report: the 'Screen horizontal/vertical alignment' options (left/right/center/top/bottom) only took effect after opening the Settings dialog once.
2) Root cause: `_refresh_window_geometries()` — the method that actually recomputes window coordinates from halign/valign — was only called in three places: (a) after confirming a window-position reset, (b) on screen resolution change (and only when res_scale actually changed), (c) after the Settings dialog closes via `_after_settings_changed()`. It was **never called at startup**, so on launch the modules used the raw X/Y from settings and the alignment was only applied once Settings had been opened.
3) Fix: call `self._refresh_window_geometries()` once at the end of controller init, right after all five module windows are `w.show()`n. Since the method itself runs `recalc_layout()` + `resize()` first, `w.width()/height()` are already final and `_screen_available_geometry()` is usable once QApplication exists — so a direct call works, no need to defer to the event loop.
4) Covers all five modules (core / roll / skill / all-buff / Boss); alignment is in place from the moment the app starts.

== v22.53 ==
【整屏对齐开机即生效（修复「要打开一次设置才生效」）】
① 用户反馈：设置里的「屏幕水平/垂直对齐」（靠左/靠右/居中/顶部/底部）每次都要点开一次设置对话框才生效。
② 根因：`_refresh_window_geometries()`（真正按 halign/valign 重算窗口坐标的方法）此前只在 3 个时机被调用——① 重置窗口位置（确认后）② 屏幕分辨率变化（且 res_scale 真变了）③ 设置对话框关闭后 `_after_settings_changed()`。**启动时从未调用**，所以开机用的是 settings 里的 X/Y 原始坐标，对齐必须开一次设置才被应用。
③ 修复：在控制器初始化末尾「5 个模块窗口全部 `w.show()` 之后」补一次 `self._refresh_window_geometries()`。因该方法内部会先 `recalc_layout()` + `resize()`，`w.width()/height()` 已是最终尺寸，`_screen_available_geometry()` 在 QApplication 建好后即可用，故直接调用即可、无需延后到事件循环。
④ 5 个模块（核心/翻滚/能力/全Buff/Boss）全覆盖，开机即按对齐设置就位。

== v22.52 ==
[All modules · graded countdown decimals applied everywhere]
1) User asked to spread V2251's graded-decimal rule to every countdown in the app (skill module and core module included).
2) `_fmt_dur` was moved out of the "all-buff render" section to just before render_core, becoming a shared utility for all modules; its docstring now lists all 5 call sites so none get missed in future edits.
3) Three new call sites: skill module `_draw_skill_cd_element` `f"{cd_val:.2f}"` → `self._fmt_dur(cd_val)` (no 's' suffix for skill cooldown); core module render_core single-buff branch and fused/multi-buff branch `f"{timer_val:.2f}s"` → `f"{self._fmt_dur(timer_val)}s"` (keeps the 's' suffix).
4) The all-buff and Boss modules were already converted in V2251 and are unchanged. The roll module has no numeric countdown (nothing to change).
5) All 5 countdowns now share one rule: `|v| < 10` → 2 decimals (9.87); `10 <= |v| < 100` → 1 decimal (12.3); `|v| >= 100` → no decimals (123). V2215/V2216 infinity handling keeps its priority.

== v22.52 ==
【全部模块倒计时统一分级小数显示】
① 用户要求把 V2251 的分级小数规则推广到软件全部倒计时（能力的、核心模块的）。
② 把 `_fmt_dur` 从「全 Buff 渲染」节移到 render_core 之前，升级为全模块共用工具方法，docstring 内列明全部 5 处调用点防漏改。
③ 新增 3 处调用：能力模块 `_draw_skill_cd_element` 的 `f"{cd_val:.2f}"` → `self._fmt_dur(cd_val)`（能力冷却无 s 后缀）；核心模块 render_core 单 buff 分支与融合/多 buff 分支的 `f"{timer_val:.2f}s"` → `f"{self._fmt_dur(timer_val)}s"`（保留 s 后缀）。
④ 全 Buff 与 Boss 两模块 V2251 已改，保持不变。翻滚模块无数字倒计时（无需改）。
⑤ 至此 5 处倒计时全部统一规则：`|v| < 10` → 2 位小数（9.87）；`10 ≤ |v| < 100` → 1 位小数（12.3）；`|v| ≥ 100` → 不带小数（123）。V2215/V2216 的 ∞ / *∞ 判定优先级不变。

== v22.51 ==
[Both Buff modules · countdown decimals graded by integer-digit count]
1) User request: countdown <10 shows 2 decimals; a 2-digit integer part (10~99) shows only 1 decimal; an integer part longer than 2 digits (>=100) shows no decimals.
2) New render class method `_fmt_dur(self, v)`: `|v| < 10` → 2 decimals (e.g. 9.87); `10 <= |v| < 100` → 1 decimal (e.g. 12.3); `|v| >= 100` → no decimals (e.g. 123). Uses abs() to judge digit count, so negative dirty values also follow the rule instead of blowing up the card.
3) Both `time_str` sites (render_allbuff for the main module and render_bossbuff for the Boss module) now use `self._fmt_dur(rem)/self._fmt_dur(init)`; remaining and initial each get graded by their own magnitude.
4) The V2215/V2216 infinity logic (∞ / *∞ for FLT_MAX or >=9999) is unchanged and still takes priority.

== v22.51 ==
【两个 Buff 模块 · 倒计时按整数位数分级显示小数】
① 用户需求：倒计时 <10 显示两位小数；整数部分两位数（10~99）只显示一位小数；整数部分大于 2 位（≥100）不显示小数点后的。
② 新增渲染类方法 `_fmt_dur(self, v)`：`|v| < 10` → 2 位小数（如 9.87）；`10 ≤ |v| < 100` → 1 位小数（如 12.3）；`|v| ≥ 100` → 不带小数（如 123）。用 abs() 判位数，负数脏值同样套规则不至于撑爆卡片。
③ 主模块 render_allbuff 与 Boss 模块 render_bossbuff 两处 `time_str` 统一改为 `self._fmt_dur(rem)/self._fmt_dur(init)`，剩余（remaining）与持续（initial）两个值各自按自身位数套同一规则。
④ V2215/V2216 的 ∞ / *∞（FLT_MAX / ≥9999）判定逻辑保持不变且优先级更高。

== v22.50 ==
[Both Buff modules · buff-list row-height factor 1.3 → 1.6]
1) User tested V2249's 1.3× text height and still found it cramped; asked to widen further to 1.6×.
2) Only one coefficient changed in _add_buff_list_group: `int(_fm.height() * 1.6)` (was 1.3). The rest of the V2248/V2249 mechanism is unchanged: still uses QFontMetrics(_list.font()).height() as the base, still setSizeHint on every QListWidgetItem (placeholder included), still setUniformItemSizes(True) so all 4 lists stay consistent.
3) 11px font → text height ≈14px → row height ≈22px.

== v22.50 ==
【两个 Buff 模块 · 名单行高系数 1.3 → 1.6】
① 用户实测 V2249 的 1.3× 文字高度仍偏挤，要求再放宽到 1.6×。
② 仅改 _add_buff_list_group 里 `int(_fm.height() * 1.6)` 一个系数（原 1.3），其余 V2248/V2249 机制不变：仍用 QFontMetrics(_list.font()).height() 算基准、仍 setSizeHint 到每个 QListWidgetItem（含占位）、仍 setUniformItemSizes(True) 保证 4 名单一致。
③ 11px 字 → 文字高度≈14px → 行高≈22px。

== v22.49 ==
[Both Buff modules · buff-list row-height factor 1.1 → 1.3]
1) User tested V2248's 1.1× text height and found it a bit cramped; asked to widen to 1.3×.
2) Only one coefficient changed in _add_buff_list_group: `int(_fm.height() * 1.3)` (was 1.1). The rest of the V2248 mechanism is unchanged: still uses QFontMetrics(_list.font()).height() as the base, still setSizeHint on every QListWidgetItem (placeholder included), still setUniformItemSizes(True) so all 4 lists stay consistent.
3) 11px font → text height ≈14px → row height ≈18px.

== v22.49 ==
【两个 Buff 模块 · 名单行高系数 1.1 → 1.3】
① 用户实测 V2248 的 1.1× 文字高度略挤，要求放宽到 1.3×。
② 仅改 _add_buff_list_group 里 `int(_fm.height() * 1.3)` 一个系数（原 1.1），其余 V2248 机制不变：仍用 QFontMetrics(_list.font()).height() 算基准、仍 setSizeHint 到每个 QListWidgetItem（含占位）、仍 setUniformItemSizes(True) 保证 4 名单一致。
③ 11px 字 → 文字高度≈14px → 行高≈18px。

== v22.48 ==
[Both Buff modules · buff-list row height tightened to text]
1) V2247's default QListWidget row height was ≈26px due to padding; user feedback: 'row height is too tall, set it to 1.1× the max text height and that's enough'.
2) V2248 fix: in _add_buff_list_group the stylesheet now sets font-size:11px explicitly and padding tightened to 0 10px; row height _row_h computed as QFontMetrics(_list.font()).height() × 1.1 and stored on _list._row_h.
3) _refresh_buff_list calls setSizeHint(QSize(0, _row_h)) on every QListWidgetItem (placeholder included); setUniformItemSizes(True) keeps all 4 lists at the same row height.

== v22.48 ==
【两个 Buff 模块 · 名单行高紧贴文字】
① V2247 默认 QListWidget 行高受 padding 影响≈26px，用户反馈「行高太高了，根据文字的高度设为1.1倍的文字最高高度就行了」。
② V2248 修：_add_buff_list_group 里 stylesheet 显式 font-size:11px + padding 收紧为 0 10px；用 QFontMetrics(_list.font()).height() × 1.1 算行高 _row_h 存到 _list._row_h。
③ _refresh_buff_list 给每个 QListWidgetItem（含占位 item）setSizeHint(QSize(0, _row_h))，setUniformItemSizes(True) 保证 4 名单行高一致。

== v22.47 ==
[Both Buff modules · buff-list fully rewritten (QScrollArea+custom widget dropped)]
1) V2241~6 repeatedly failed on the QScrollArea+custom-widget path across 4 versions: V2241 setItemWidget locks width and clips the remove button / V2245 wrapper maxHeight squashes row heights / V2246 QFormLayout ignores the scroll area maxHeight AND a bizarre two-'remove'-buttons-per-row rendering bug. User report: 'why not just create a list, put these buffs in it, right-click for a menu, the menu removes — isn't that good?'
2) V2247 drops QScrollArea+custom widget entirely in favor of a standard QListWidget + right-click context-menu removal — maxHeight now actually takes effect, scrolling/selection/row rendering come for free, zero custom widgets and zero custom layouts.
3) _add_buff_list_group list body: QScrollArea + inner QWidget + QVBoxLayout → QListWidget; _list.setContextMenuPolicy(Qt.CustomContextMenu) + customContextMenuRequested → _show_buff_context_menu.
4) _refresh_buff_list now uses _list.clear() + addItem(QListWidgetItem), setData(Qt.UserRole, sid) stores the sid for the right-click menu; empty state uses a Qt.NoItemFlags placeholder item (not selectable, not right-clickable).
5) New _show_buff_context_menu: itemAt(pos) to grab sid → QMenu with a 'Remove' action → _on_buff_remove(which, sid).
6) Both modules (core all-buff + Boss Buff) and all four lists (bl/ml × 2) flow through the single _add_buff_list_group factory on the new design.

== v22.47 ==
【两个 Buff 模块 · 名单列表彻底重做（弃 QScrollArea+自定义行）】
① V2241~6 在 QScrollArea+自定义行 widget 路线上反复翻车 4 版都不稳——V2241 setItemWidget 锁宽裁按钮 / V2245 wrapper maxHeight 压扁行 / V2246 QFormLayout 不尊重 scroll area maxHeight + 每行渲染出两个「移除」按钮的诡异 bug；用户反馈「不直接创建一个列表，里面放这些 buff，可以直接右键弄个菜单，菜单能移除不就好了」。
② V2247 彻底弃 QScrollArea+自定义 widget，改用标准 QListWidget + 右键菜单移除——maxHeight 真生效、自带滚动/选中/行渲染，零自定义 widget、零自定义 layout。
③ _add_buff_list_group 列表本体：QScrollArea+内层 QWidget+QVBoxLayout → QListWidget；_list.setContextMenuPolicy(Qt.CustomContextMenu) + customContextMenuRequested → _show_buff_context_menu。
④ _refresh_buff_list 改用 _list.clear() + addItem(QListWidgetItem)，setData(Qt.UserRole, sid) 存 sid 供右键菜单用；空态用 Qt.NoItemFlags 占位 item（不可选中、不可右键响应）。
⑤ 新增 _show_buff_context_menu：itemAt(pos) 拿 sid → QMenu 含「移除」action → _on_buff_remove(which, sid)。
⑥ 两模块（主控 + Boss Buff）四名单（bl/ml × 2）统一经 _add_buff_list_group 工厂走新设计。

== v22.46 ==
[Both Buff modules · buff-list rendering misalignment fully fixed]
1) Fixed a regression introduced in V2245 — V2245 kept maxHeight/minHeight on the wrapper container AND switched to Preferred policy while syncing inner.minHeight, which forced 9+ list rows (288px) into a 240px container, squashing every row from 32px to ~26px so the remove-button overlapped each row's text (user report: 'why is it even messier now').
2) V2246 fix — moved maxHeight/minHeight from the wrapper container down to the QScrollArea itself; the scroll area is still capped at 240px (to bound the dialog height) but the inner _inner now keeps its sizeHint (= N*32) under setWidgetResizable(True), and the scroll area auto-shows the vertical scrollbar when content exceeds the viewport.
3) Dropped the _container wrapper — the scroll area now lives straight in the form layout: one less layer of nesting, much more predictable behavior.
4) Changed the inner widget's vertical size policy from Preferred to MinimumExpanding — double insurance that the inner never shrinks below its minimum height.
5) Both modules (core all-buff + Boss Buff) and all four lists (bl/ml × 2) flow through the single _add_buff_list_group factory, so there is no longer a V2245-style 'fix one place, miss the other' risk.
6) Backfilled the v22.45 blocks that V2245 missed in release_notes.txt + README.md so the tri-lingual red-line is whole again.

== v22.46 ==
【两个 Buff 模块 · 名单列表渲染错位彻底修复】
① 修正 V2245 引入的 bug——V2245 把 maxHeight/minHeight 留在 wrapper container 上、同时改 Preferred policy 同步 inner.minHeight, 导致 9+ 行名单 (288px) 被强行塞进 240px 容器, 每行从 32 压到 ~26px, 按钮 + 文字上下错位重叠（用户反馈『怎么更乱了』）。
② V2246 修复——把 maxHeight/minHeight 从 wrapper container 下沉到 QScrollArea 自身, scroll area 外层仍 240 封顶（控制对话框高度）但内层 _inner 在 setWidgetResizable(True) 下保持 sizeHint (= N*32), 超出 viewport 时由 scroll area 自动出垂直滚动条。
③ 删 _container wrapper——scroll area 直接进 form layout, 少一层嵌套, 行为更可预测。
④ _inner 垂直 size policy 从 Preferred 改 MinimumExpanding——双重保险, inner 永不低于 minHeight。
⑤ 两模块（主控 + Boss Buff）四名单（bl/ml × 2）经 _add_buff_list_group 统一修复, 不再有 V2245「一处改一处忘」风险。
⑥ 顺手补齐 V2245 当年漏同步的 release_notes.txt + README.md v22.45 块, 三语红线恢复完整。

== v22.44 ==
[Screen alignment · sync + manual-layout lock]
1) Sync fix: after changing "screen horizontal/vertical align", "horizontal/vertical margin", or "module scale" in Settings, the top "module position X/Y" now refreshes to the real on-screen coordinates immediately (fixes the previous lag where "layout changed but the top params didn't update together").
2) Manual-layout lock: on a non-"custom" align axis (left/right/center/top/bottom) manual layout is no longer allowed — that axis' X/Y box is greyed out and uneditable, and dragging the module or corner-resizing it with the mouse in-game is fully disabled (alignment IS parametric layout; manual layout would break it). Only "custom" re-enables mouse drag and resize.
All five modules (core / roll / skill / main all-Buff / Boss) get the symmetric change.

== v22.43 ==
[Spike waist position · range unlocked + Gate page fully toggleable]
1) Spike waist position (spike_waist_pos): range widened from 5%~95% to 0%~100% — you can now push the spike ring all the way to the very top or bottom, with no dead margin at the canvas edge.
2) The 4 gate rules that were previously greyed-out / hard-disabled are now fully toggleable gating (main + Boss modules perfectly symmetric):
   · ① NaN/Inf check: can be turned OFF (when off, NaN/Inf junk values are also shown, for diagnostics).
   · ② ID=0/ID=1 cannot be infinite: now also filters "Defense UP (ID=1)" (previously only Attack UP ID=0); turning it off stops filtering them.
   · ③ Remaining/initial time ≤ X(seconds) drop: a new time input box added (default 0.0 s = no filter); players can set >0 to drop transient junk buffs.
   · ④ Duration cap (with 9999 infinite exemption): checkbox + number box (default 10000.0 s); unchecking disables the duration-cap filter.
The two hardened gates (hide 0.0/0.0, negative durations) remain always-on and cannot be turned off, as a safety net.
All toggles default ON; old configs auto-migrate with no manual change.

== v22.41 ==
[List widget · "Remove" button layout hotfix]
V2240 user screenshot reported the "Remove" button on every row of all 4 lists (blacklist + multi-instance × main + Boss) showed only the character "移" with the second character clipped off.
Root cause: `_refresh_buff_list` uses QListWidget.setItemWidget to embed a custom row widget. Qt does NOT auto-stretch the widget to the item rect by default — the row's default Preferred size policy keeps sizeHint width → the label+button row gets compressed → setFixedWidth(64) effectively rendered only ~20-30 px.
Fix:
(1) Row widget now uses `setSizePolicy(Expanding, Preferred)` → forces it to fill the QListWidget item rect.
(2) "Remove" button uses `setMinimumWidth(76) + setMaximumWidth(76)` (fixed-width with more headroom) + padding `2px 6px` → `3px 8px` + font-size `10 → 11` + `min-height: 22px` + `PointingHandCursor`.
(3) `retranslate_ui` path unchanged (button text still `_tr("移除")`; zh / zh_tw / en / ja automatic).

== v22.42 ==
[List widget · full rewrite (replaces the failed V2241 attempt)]
V2240 user screenshot reported the "Remove" button on every row of all 4 lists showed only "移"; V2241 tried setItemWidget + setSizePolicy(Expanding) to stretch it, but it still got clipped (user replied "still the same").
Root cause: QListWidget.setItemWidget renders the widget inside QListWidgetItem.sizeHint(); sizeHint defaults to the widget's preferred width, and setSizePolicy(Expanding) is **completely ignored** under setItemWidget — that is why V2241 failed.
Fix: replaced the list container of all 4 lists (main blacklist / main multi-instance / Boss blacklist / Boss multi-instance) from "QListWidget + setItemWidget" with "QScrollArea + inner QWidget + QVBoxLayout":
  (1) _scroll.setWidgetResizable(True) + inner _inner (sizePolicy Expanding) so _inner width auto-follows the _scroll viewport width;
  (2) row widget is added via _layout.insertWidget into the QVBoxLayout, taking _inner's full width (no item.sizeHint limit); label fills the left, the 76px "Remove" button shows fully on the right;
  (3) empty state now uses a centred dark-grey QLabel placeholder (replacing V2237's grey placeholder item) — cleaner logic;
  (4) row height uses setMinimumHeight(30) + QHBoxLayout natural height, no stretching/distortion.
All 4 lists take effect simultaneously. retranslate_ui path unchanged (button text still _tr("移除"); zh / zh_tw / en / ja automatic).

== v22.40 ==
[Core module · canvas width/height now adjustable]
Added two knobs "Canvas width (0=auto)" / "Canvas height (0=auto)" (Settings → Circle card, range 0–4000, 0 shows "auto"):
1) Default 0 = auto — keeps the old auto-computed layout exactly; existing users see zero change and need no reconfig.
2) A value >0 overrides the core module canvas (spike-circle + title bar + buff names). Content (circle / title / buff names) is already laid out relative to the canvas, so it auto re-centres both horizontally and vertically.
3) A hard floor prevents clipping — width ≥ max(base 648, circle + both-side spikes/outline width), height ≥ auto-preview height × 1.35; too-small values are pulled back so the circle or buff names never get cut off.
4) Orthogonal with the existing core_scale_percent / circle_radius (final size = user W/H × scale% × resolution scale).
Both modules' layout logic unchanged for existing users.

== v22.39 ==
[Gates slim-down + duration cap made tunable on both buff modules]
① "NaN/Inf check" → preserved;
② "ID=0 cannot be infinite" → preserved;
③ ③④⑤ merged into ONE rule: "any buff's remaining or initial time cannot be ≤ 0" —
    combines "hide 0.0/0.0", "remaining/initial < 0 drop", "infinite remaining cannot ≤ 0"
    (render side: remaining ≤ 0 AND < 9999 → drop; initial ≤ 0 → drop; ≥ 9999 still exempted as V2216 infinite);
④ "Duration cap" is now a tunable number: checkbox stays locked-on (always enabled),
    a DoubleSpinBox next to it (default 10000.0 s, range 10.0–600000.0) lets players adjust the cap.
    render reads from settings dynamically; existing 9999 infinite exemption preserved; old configs auto-migrate.
Both modules (main + Boss) get the symmetric change.

== v22.38 ==
• V2238 (22.38) hotfix：修复 V2237 的「4 个名单 UI 重做」让「设置」窗口打不开的崩溃——V2237 调用了 `QListWidget.setPlaceholderText(...)` 设置空态文案，但 PySide6 6.11.1 的 `QListWidget` 根本没有这个方法（那是 QLineEdit / QComboBox 的）。
修法：(1) 主控 + Boss 两处 `_add_buff_list_group` 删除 `setPlaceholderText` 调用；
(2) `_refresh_buff_list` 在清空且 `_items` 为空时插入一个不可点击/不可选中的暗灰 placeholder item
(`Qt.NoItemFlags` + `QBrush(QColor("#5a6a85"))`)，跟真实数据行完全独立、不会污染 sizeHint。
V2237 的「聚散距离下限解负」功能本身不变，本版纯粹是修一个外部错误调用。

== v22.37 ==
• V2237 (22.37)：能力模块「聚散距离」下限解负——
  ① **UI SpinBox**：`聚散距离:` 下限由 20 放开到 -200（与 `能力名X/Y偏移` / `倒计时X/Y偏移` 同款对称风格），范围（-200, 200），可输入负值让 4 个技能菱形向画布中心靠拢甚至完全重叠。
  ② **render_skill 去除「防菱形覆盖中心」兜底**：原 `spread = max(spread, half_diag + 8)` 强制 spread 不低于菱形半对角线+8，造成 spread 输入 -50/0 等值完全无效。现改为 spread 直接生效——spread=0 时 4 菱形全堆在中心，spread=-N 时则更密集重叠。
  ③ **recalc_layout 画布尺寸兜底由 half_diag+8 改 0**：画布可能容纳不下完全重叠的菱形，但保证画布尺寸永不为负（程序不会崩溃）；DEFAULT_SETTINGS["skill_cd_spread"]=90 默认不变。
== v22.36 ==
== v22.36 ==
• V2236 (22.36)：清理 + 整治三件套——
  ① **删除「全buff小模块闪光」功能**：V2107 加入、作用于子模块闪光。用户反馈「不勾选这个闪光选项，主控 buff 模块就直接消失」——根因是废弃变量导致异常链路被 paintEvent 的 try/except 吞掉、整模块空白。保留该功能既让玩家困惑、又可能闪烁，故彻底删除：DEFAULT_SETTINGS 移除 flash_apply_allbuff_submodule / boss_flash_apply_allbuff_submodule 等键，设置面板 3 处对应复选框删除，闪光动画计时器与字段一并移除。
  ② **4 个名单 UI 重做**：主控黑名单 / 主控多次出现名单 / Boss 黑名单 / Boss 多次出现名单，从「QScrollArea + 垂直均分(stretch)」改为「小框(QGroupBox)包裹 QListWidget + 每行 setItemWidget + Native 滚动条」。内部列表自然高度、超出即滚动，不再撑爆 GroupBox、行也不再叠成一团。4 个名单同时生效。
  ③ **门限全外露**：主控 + Boss「门限」子标签上半段新增「已固化的门限（永远开启，不可关闭）」6 条 disabled 复选框，显式列出所有固化门限——NaN/Inf 检查 / status_id=0 不可能是永续 / 隐藏倒计时 0.0/0.0 / remaining 或 initial 任一 <0 舍弃 / **⑤ 永续 buff 的 remaining 不可能 ≤0【V2236 新增】** / 时长上限 10000s（含 9999 永续豁免）。下方原有可调数值门限（status_id / sub_id 上限 / 层数上限 / 最小剩余 / 最小初始 / 最小出现持续）保留。render 端新增两条硬编码检查：`if sid_i==0 and infinite: continue` 与 `if infinite and remaining<=0.0 and remaining<9999.0: continue`。
  ④ **卡片居中复核**：两个 buff 模块小模块的进度条与文字（drawText / addText / bar_x / by 公式）确认已是严格水平 + 垂直居中，并加 V2236 居中复核注释。

== v22.35 ==
• V2235 (22.35)：彻底根治「主控全 Buff 空白」低级绘制 bug——V2234 的自动防裁切没解决问题，说明根因不在裁切而在绘制层。V2235 三条硬改：
  ① **绘制 sanity 色块**：在 _draw_allbuff_card 入口（painter.save 后立即）画 3 条醒目横块（红 255,0,0 / 蓝 0,128,255 / 绿 0,220,90），覆盖卡片顶部 1~14px 区。
     - 能看到色块 = 绘制链路触达卡片层，问题在 backing_col/名称/层数/bar 颜色。
     - 看不到色块 = painter 状态、外层坐标系、widget clip 本身有问题（不在本函数内）。
     这是用户原话「你要花更多的精力在更基础更底层的逻辑错误上」的精神——以后再卡绘制类问题，第一时间走这两步。
  ② **dump 函数原子化**：之前 line 8790 的 dict literal 一旦中间任一字段求值抛异常，整个 _dump_allbuff_buffs 调用被外层 except 吞掉、dump 文件保留上一次成功的内容——这就是 V2234 用户看到的 dump 没有 win_geo/layout/cards/alpha、让我误判 V2234 没真跑的原因。
     现在改为「每个字段独立 try/except + lambda 包裹」，任何字段异常降级为 err:ExceptionType，整个 dump 调用不会因为一个字段而失败；下次跑就能立刻看到完整的诊断字段（win_geo / layout / cards / alpha）。
  ③ **保留 V2234 的自动防裁切逻辑不动**：移动整个模块到屏幕内保证底框/边框可见，但绘制层低级错误仍可能在裁切消失后继续表现为空白。

== v22.34 ==
• V2234 (22.34)：V2233 自愈逻辑上线后实测发现，「主控全 Buff 空白」的真正根因不是 pptr 失效，而是「窗口被屏底物理裁切」——
  1) 位置按 1920 宽度归一化保存，res_scale = max(1.0, 屏宽/1920)。当显示器为 2560×1440 时，res_scale=1.333，原本 1030 的归一化 y 放大为 1373，看似距屏底（1440）还有 67px 余量；
  2) valign=bottom + vmargin=-40 的组合下，y 再下推 40px 到 1413，距屏底仅 27px；
  3) canvas 高度 = bh(=56) × disp_h(=1.333) ≈ 75px，但 Qt 窗口已被屏底裁掉 16px，window_h 实际只剩 59px；
  4) 卡片主体（名称/层数/时间/进度条）正好落在 canvas 30~60px 区段——恰是被裁掉的 16~43px 区间内，视觉上只见底框/边框，看不到 buff 名字与倒计时，与「主控无值、Boss 正常」完全一致。
  修法：在 _refresh_window_geometries 末尾新增「自动防裁切」：窗口下沿超出可用区时，把 y 向上回退到 max(屏顶, 屏底-窗口高)，让整窗完整落在屏幕内。同步处理水平溢出（左/右）但优先级低于位置主动选择——玩家故意拖到屏外的情况尊重原意、不主动回拉。V2233 的两个 dump（_dump_allbuff_buffs 渲染级 / _dump_allbuff_source 数据源级）与「pptr 失效时自愈」逻辑（_pptr_broken 标志 + 3 秒节流 AOB 重解）一并保留。

== v22.33 ==
• V2233 (22.33)：修复「Boss 模块有值、主控全 Buff 模块始终空白」。两个模块的数据源不对称：Boss 走 read_boss_buffs(module_base)，module_base 由 get_module_info 直接取得、永远正确；主控走 read_overlay_data(self.pptr)，pptr 来自 ptr 缓存 / AOB 反解，可能失效（缓存陈旧但解出恰好非 0 的垃圾值也会被信任；AOB 误命中）→ char_base = 0 或垃圾地址 → read_overlay_data 返回 no_char、all_buffs_list 为空 → 主控全 Buff 永远空白，而 Boss 照常有值。
  - 自愈：检测到 status == no_char、或 status == ok 但 charid_hash 与 char_type 全为 0（说明 char_base 是垃圾地址）时，删除 ptr 缓存并重新 AOB 反解 pptr，成功后立即用新指针重读一次快照，主控模块随即恢复显示（节流 3 秒一次，避免每帧做 80MB 全模块扫描拖垮帧率）。
  - 诊断旁路：新增 _dump_allbuff_buffs，每秒把「过滤后 items + 过滤前 raw + 定位链路上下文（pptr / char_base / charid_hash / char_type / pl_id / boss_actor / boss_buff_count）」写到 EXE_DIR/last_allbuff_buffs.json，与既有的 last_boss_buffs.json 完全对称，用于区分三类根因：数据源为空 / 门限丢光 / 渲染未执行。

== v22.32 ==
• V2232 (22.32)：纠正 V2231 的错误放置——3 个 boss buff（sid=149/146/129）从「核心检测模块的角色配表」(i18n.json buffs) 移出，改放进「全局 buff 名表」(buff_attrs.json)，这才是 Boss 模块与全 Buff 模块真正读取名称的地方（经 _attr_for_sid → BUFF_ATTRS）。V2231 误把它们塞进每个角色的 bucket，既污染角色配表、又根本没解决 boss 显示问题（boss 名字不读 i18n.json 的 buffs）。
  - sid=149 (0x95) 世界裂痕 / Fractured World / 龜裂世界 / ワールドクラック
  - sid=146 (0x92) 纯白之境 / Proto-White World / 白堊境界 / 白亜の境界
  - sid=129 (0x81) 混沌转换 / Chaos Shift / 混沌輪迴 / ケイオシフト
  - 属性：单层、非专属、非 debuff。现在 boss 战读到这 3 个 sid 会显示正式四语名称，不再回落 0x0095/0x0092/0x0081。i18n.json 角色 buffs 恢复 119 条（删掉 V2231 误加的 87 条）；buff_attrs.json 新增 3 条（144→147）。代码逻辑无改动。

== v22.30 ==
• V2230 (22.30)：代码审计清理版（功能与默认值完全不变，老用户升级零感）。
  - 删除 DEFAULT_SETTINGS 中 6 个重复的 boss 设置键（show_boss_module / boss_window_x / boss_window_y / boss_scale_percent / boss_name_keywords / boss_keep_backdrop_when_absent）——V2200 加 boss 模块时的复制粘贴遗留，前一份为死默认值，现已合并到首段统一定义。
  - 删除 get_settings 里 allbuff / boss 的 halign / valign 各一处重复写入（V2228 残留块，值与 V2229 块完全相同、幂等）。
  - 新增模块级 logger（logging.getLogger("GBFR_Indicator")），将 52 处「静默吞异常 except Exception: pass」改为 logger.debug(..., exc_info=True) 留痕——游戏更新导致内存偏移漂移等问题时，开启 logging 即可看到被吞的异常，大幅提升可排查性，不改变任何控制流与默认行为。
- **V2229 (22.29)**: 把「整屏水平/垂直对齐」+「水平/垂直边距（可负数）」推广到全部 5 个模块（核心 / 翻滚 / 能力 / 主控的全Buff / Boss）。每个模块的「位置与缩放」子标签现在都有：
  - **屏幕水平对齐**：自定义 / 靠左 / 居中 / 靠右（默认「自定义」= 原 X 坐标）
  - **屏幕垂直对齐**：自定义 / 顶部对齐 / 居中 / 底部对齐（默认「自定义」= 原 Y 坐标）
  - **水平边距（可负）**：左/右对齐时的左右间距，-2000..2000 px。正数把窗口往外推（远离边缘）；负数让窗口往里推（可溢出屏幕外）。
  - **垂直边距（可负）**：上/下对齐时的上下间距，-2000..2000 px。正数把窗口往外推；负数让窗口往里推（可盖到任务栏上、贴齐物理屏幕底）。
  - 默认值均为「自定义 / 0」，与旧版完全一致，老用户升级零感。
  - **Bug 修复**：底部对齐「浮上来一点」是因为 Qt availableGeometry() 已扣除任务栏区域；现在用「垂直边距」设负值（≈ -任务栏高度，如 -48）就能贴齐物理屏幕底，负数能力完全保留。
  - 模块缩放/分辨率变化时，每次刷新都会重算贴边或居中。

- **V2228 (22.28)**: 给「主控的全Buff模块」与「Boss Buff模块」各新增「整屏对齐」设置（位于对应模块的「位置与缩放」子标签）：**水平方向** 自定义 / 靠左 / 居中 / 靠右，**垂直方向** 自定义 / 顶部对齐 / 居中 / 底部对齐，**默认均为「自定义」**（沿用原 X/Y 坐标自由定位，与旧版行为完全一致）。非自定义时，每次刷新窗口（模块缩放、分辨率变化、每行数量 / 行数变化）都会按**主屏可用区域**（已排除任务栏）重算该轴坐标——水平：靠左贴屏幕左缘、居中水平居中、靠右贴右缘；垂直：顶部对齐贴屏幕上缘、居中垂直居中、底部对齐贴屏幕下缘。两个模块独立计算、互不影响。V2227 的名单滚动条修复不受影响。

- **V2227 (22.27)**: 修复「名单列表项多了就叠成一团」的**真正病根**。此前一直当成「高度不够、最后一行被裁」在治（V2221 加滚动区、V2225 把最大高度 180→220），实际是**容器被 QScrollArea 压扁**：滚动区用了 `setWidgetResizable(True)`，但内部容器没有 sizePolicy 约束，被强行压缩到可视高度，于是 N 行内容被塞进不足的空间、行高被挤压，buff 名与右侧「移除」按钮重叠（玩家截图：Boss 黑名单第 7 项仍叠在一起）。修法：给内部容器设 `setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)`，让它保持内容自然高度——**内容超出最大高度时才出现滚动条**，永不压缩；最大高度再放宽到 260px（约 7-8 行默认可见）。现在名单加到多少项都不会叠，超出即滚动。4 个名单（主控黑名单 / 主控多次出现名单 / Boss 黑名单 / Boss 多次出现名单）同时生效。

== v22.41 ==
【名单展示框 · 「移除」按钮排版热修】
用户截图 V2240 反馈「4 个名单（黑名单 + 多次出现名单 × 主控 + Boss）每行的『移除』按钮只显示『移』字，『除』字被裁掉」。
根因：`_refresh_buff_list` 用 `QListWidget.setItemWidget` 嵌入自定义行 widget，Qt 默认不会自动把 widget 撑满 item 矩形——row widget 默认 Preferred size policy → 保留 sizeHint 宽度，导致 label+button 的横向布局被压缩，`setFixedWidth(64)` 实际渲染只有 20~30px。
修法：
  ① row widget 加 `setSizePolicy(Expanding, Preferred)` → 强制填满 QListWidget item 矩形；
  ②「移除」按钮改 `setMinimumWidth(76) + setMaximumWidth(76)`（等宽且更宽松量）+ padding `2px 6px → 3px 8px` + font-size `10 → 11` + `min-height: 22px` + `PointingHandCursor`；
  ③ `retranslate_ui` 路径不变（按钮文字仍走 `_tr("移除")`，中文/繁中/英文/日文四语全自动）。

== v22.42 ==
【名单展示框 · 彻底重做（移除 V2241 失败方案）】
用户 V2240 截图反馈「4 个名单每行的『移除』按钮只显示『移』字」，V2241 用 setItemWidget + setSizePolicy(Expanding) 试图撑满，但实测仍被裁（用户回「还是这样」）。
根因：QListWidget.setItemWidget 把 widget 渲染在 QListWidgetItem.sizeHint() 矩形里，sizeHint 默认 = widget 的 preferred 宽；setSizePolicy(Expanding) 在 setItemWidget 下**完全无效**（这是 V2241 失败的根因）。
修法：把 4 个名单（主控黑名单 / 主控多次出现名单 / Boss 黑名单 / Boss 多次出现名单）的列表容器从「QListWidget + setItemWidget」整个换成「QScrollArea + 内层 QWidget + QVBoxLayout」：
  ① _scroll.setWidgetResizable(True) + 内层 _inner（sizePolicy Expanding），让 _inner 宽度自动跟随 _scroll viewport 宽；
  ② 行 widget 直接 _layout.insertWidget 到 QVBoxLayout，拿到 _inner 全宽（不受 item.sizeHint 限制），label 占满左侧、按钮 76px 完整显示在右侧；
  ③ 空态改用居中暗灰 QLabel 占位（替代 V2237 的灰色 placeholder item），逻辑更干净；
  ④ 行高用 setMinimumHeight(30) + QHBoxLayout 自然高度，不被拉伸变形。
4 个名单同时生效。retranslate_ui 路径不变（按钮文字仍走 _tr("移除")，中文/繁中/英文/日文四语全自动）。

== v22.40 ==
【核心模块 · 画布宽/高可调】
新增「画布宽(0=自动)」/「画布高(0=自动)」两个旋钮（设置 → 圆环 卡片，范围 0–4000，0 显示「自动」）：
① 默认 0 = 自动——完全沿用旧版自动计算逻辑，老用户无感、配置零变化；
② 设 >0 时覆盖核心模块（尖刺圆 + 标题栏 + buff 名）画布尺寸，内容（圆/标题/buff 名）本就相对画布自适应，自动水平 + 垂直重居中；
③ 强制下限防裁切——宽 ≥ max(基准宽 648, 圆 + 两侧尖刺/外描边所需宽)，高 ≥ 自动预览高度 × 1.35，设太小自动拉回，不会把圆或 buff 名切掉；
④ 与现有 core_scale_percent / circle_radius 正交叠加（最终尺寸 = 用户宽高 × 缩放% × 分辨率缩放）。

== v22.39 ==
【两个 buff 模块 · 门限瘦身 + 时长上限可调】
①「NaN/Inf 检查」→ 保留；
②「ID=0 不可能是永续」→ 保留；
③ ③④⑤ 三条合并为一条：「任何 buff 的剩余或初始时间都不可能 ≤ 0」——
    把「隐藏倒计时 0.0/0.0」「remaining/initial 任一 < 0 」「永续剩余不可能 ≤ 0」三条独立规则合并为更直白的一条
    （render 端：remaining ≤ 0 且 < 9999 → 丢；initial ≤ 0 → 丢，9999 起仍为 V2216 永续豁免）；
④「时长上限」改为可调数值：复选框永远开启（玩家无法取消），旁边新增 DoubleSpinBox（默认 10000.0 秒，范围 10.0–600000.0）——
    render 端从 settings 动态读取上限，保留原 9999 永续豁免，旧 config 自动迁移无需手动改。
两个模块（主控 + Boss）完全对称改动。

== v22.38 ==
• V2238 (22.38) hotfix: fixes V2237's "4 buff-list UI rewrite" that bricked the Settings window——V2237 called `QListWidget.setPlaceholderText(...)` for empty-state text, but PySide6 6.11.1's `QListWidget` doesn't have that method at all (it's QLineEdit/QComboBox's).
Fix: (1) Remove the `setPlaceholderText` calls in both Main + Boss `_add_buff_list_group`; (2) `_refresh_buff_list` now inserts a non-clickable / non-selectable dark-grey placeholder item (`Qt.NoItemFlags` + `QBrush(QColor("#5a6a85"))`) when the list is cleared and `_items` is empty, completely independent from real data rows, not polluting sizeHint.
V2237's "unlock convergence-distance lower bound" feature itself is unchanged — this version is purely fixing an erroneous API call.

== v22.37 ==
• V2237 (22.37): release the lower bound of the ability module's "spread distance" —
  1) **UI SpinBox**: the `Spread Distance:` control's minimum drops from 20 to -200 (mirroring the existing `Skill Name X/Y Offset` and `Timer X/Y Offset` controls' symmetric style). Range is now (-200, 200). You can now enter negatives to pull all 4 skill diamonds toward — or fully onto — the canvas centre.
  2) **render_skill removes the "anti-overlap" clamp**: the previous `spread = max(spread, half_diag + 8)` forced the spread to stay at least half a diagonal + 8 px, which made inputs like -50 or 0 do nothing. The clamp is gone — spread now takes effect as-is. spread=0 collapses all 4 diamonds onto the centre; spread=-N even more so.
  3) **recalc_layout canvas-dimension floor changes from half_diag+8 to 0**: the canvas may be smaller than the full overlapped cluster, but its size is guaranteed non-negative (no crash). DEFAULT_SETTINGS["skill_cd_spread"]=90 stays the default.
== v22.36 ==
== v22.36 ==
• V2236 (22.36): cleanup + 3 fixes——
  1) **Removed the "All-Buff submodule flash" feature**: added in V2107, it flashed the submodule. User reported "if I don't tick this flash option, the main All-Buff module just vanishes" — the root cause was a stale variable throwing in a path whose exception was swallowed by paintEvent's try/except, blanking the whole module. Keeping it only confused players and could flicker, so it is fully removed: the flash_apply_allbuff_submodule / boss_flash_apply_allbuff_submodule keys are dropped from DEFAULT_SETTINGS, the 3 corresponding checkboxes in the settings panel are removed, and the flash animation timer/fields are gone.
  2) **Rebuilt all 4 list UIs**: Main blacklist / Main multi-occurrence / Boss blacklist / Boss multi-occurrence. Changed from "QScrollArea + vertical stretch (evenly distributed)" to "small frame (QGroupBox) wrapping a QListWidget + per-row setItemWidget + Native scrollbar". The inner list uses natural row heights and scrolls when overflowing; it no longer blows up the GroupBox and rows never overlap. All 4 lists updated together.
  3) **All gates now exposed**: the upper part of the "Gates" sub-tab for both Main and Boss gets 6 disabled "baked-in gates (always on, cannot disable)" checkboxes that explicitly list every baked-in gate — NaN/Inf check / status_id=0 can't be infinite / hide 0.0/0.0 countdown / drop if remaining or initial < 0 / **⑤ an infinite buff's remaining can't be <=0 [NEW in V2236]** / duration cap 10000s (with 9999 infinite exemption). The adjustable numeric gates below (status_id / sub_id cap / stack cap / min remaining / min initial / min appearance duration) are kept. Two hard-coded checks added at the render side: `if sid_i==0 and infinite: continue` and `if infinite and remaining<=0.0 and remaining<9999.0: continue`.
  4) **Card centering review**: confirmed the progress bar and text in both buff-module submodules (drawText / addText / bar_x / by formulas) are strictly horizontally + vertically centered, and added a V2236 centering-review comment.

== v22.35 ==
• V2235 (22.35): final fix for the low-level rendering bug behind "Main All-Buff blank" - V2234's auto-clamp didn't solve it, so the root cause is in the rendering layer rather than the clip. V2235 ships three hard changes:
  1) **Render sanity bands**: at the very start of _draw_allbuff_card (right after painter.save), draw three glaring horizontal bars (red 255,0,0 / blue 0,128,255 / green 0,220,90) covering the top 1~14px of the card.
     - If you can see the bands -> the render pipeline reaches the card layer; the issue is in backing_col / name / stacks / bar colors.
     - If you cannot see the bands -> painter state, outer coordinate system, or widget clipping is broken (not in this function).
     This is the spirit of the user's quote "spend more time on the lower-level logic errors": for any future draw-pipeline issue, this is the first thing to wire up.
  2) **Dump atomicity**: previously, the dict literal at line 8790 - if any single field's evaluation raised, the whole _dump_allbuff_buffs call was swallowed by the outer except, leaving the dump file with whatever the LAST successful run had written. That is exactly why V2234's dump came out without win_geo / layout / cards / alpha and I mistakenly concluded V2234 had not been run.
     Now each field is wrapped in its own try/except + lambda, with any field-level error downgrading to err:ExceptionType. The whole dump call cannot fail because of one bad field; the next run will surface the full diagnostic fields immediately.
  3) **V2234's auto-clamp is kept as-is**: it keeps the backdrop / border visible by clamping the whole module onto the screen, but a low-level rendering error can still produce a blank card even with the clip gone.

== v22.34 ==
• V2234 (22.34): After V2233's self-healing went live, the real root cause of "Main All-Buff blank" turned out NOT to be a stale pptr but a physical off-screen clip:/n  1) Positions are saved normalized to a 1920-wide canvas; res_scale = max(1.0, screen_w/1920). On a 2560x1440 monitor that is 1.333, so a stored y of 1030 becomes 1373 - seemingly 67px clear of the screen bottom (1440);
  2) With valign=bottom + vmargin=-40, the y is pushed another 40px to 1413, leaving only 27px of room;
  3) The canvas height is bh(=56) * disp_h(=1.333) ~= 75px, but the Qt window has already been clipped 16px by the screen bottom, so the actual window_h is only 59px;
  4) The card body (name / stacks / time / bar) sits in the canvas 30~60px band - exactly inside the 16~43px clip range, so the user only ever sees the backdrop / border, never the buff name or timer. This matches the reported "Main empty, Boss fine" symptom perfectly.
  Fix: a new auto-clamp at the end of _refresh_window_geometries: when the window's bottom edge goes past the available area, the y is pulled up to max(screen_top, screen_bottom - window_h) so the whole window fits on screen. Horizontal overflow (left/right) is handled the same way but with a lower priority than explicit placement - if the user has deliberately dragged a window off-screen, the auto-clamp leaves it alone. V2233's two dumps (_dump_allbuff_buffs render-level / _dump_allbuff_source data-source-level) and the pptr self-healing logic (_pptr_broken flag + 3s AOB-rescan throttle) are kept in place.

== v22.33 ==
• V2233 (22.33): Fixes "Boss module shows values but the Main All-Buff module is always empty". The two modules read from asymmetric sources: Boss uses read_boss_buffs(module_base), where module_base comes straight from get_module_info and is ALWAYS correct; Main uses read_overlay_data(self.pptr), where pptr comes from the ptr cache / AOB reverse-resolve and CAN go stale (a stale cache is trusted whenever it happens to deref to any non-zero garbage value; AOB can also mis-hit) -> char_base becomes 0 or a garbage address -> read_overlay_data returns no_char with an empty all_buffs_list -> the Main All-Buff module stays blank forever while Boss keeps working.
  - Self-healing: when status == no_char, OR status == ok but BOTH charid_hash and char_type are 0 (meaning char_base is a garbage address), the ptr cache is deleted and pptr is re-resolved via AOB; a fresh snapshot is then read immediately with the new pointer, restoring the Main module (throttled to once every 3s so the 80MB full-module scan can't tank the frame rate).
  - Diagnostic bypass: new _dump_allbuff_buffs writes, every second, "post-filter items + pre-filter raw + pointer-chain context (pptr / char_base / charid_hash / char_type / pl_id / boss_actor / boss_buff_count)" to EXE_DIR/last_allbuff_buffs.json - fully symmetric with the existing last_boss_buffs.json - to tell apart three root causes: empty data source / everything dropped by gates / render never executed.

== v22.32 ==
• V2232 (22.32): Corrects V2231's misplacement - the 3 boss buffs (sid=149/146/129) are moved OUT of the core detection module's per-character profile table (i18n.json buffs) and INTO the global buff name table (buff_attrs.json), which is what the Boss module and All-Buff module actually read for names (via _attr_for_sid -> BUFF_ATTRS). V2231 wrongly injected them into every character's bucket - polluting the character profiles AND not fixing boss display at all (boss names don't come from i18n.json buffs).
  - sid=149 (0x95) 世界裂痕 / Fractured World / 龜裂世界 / ワールドクラック
  - sid=146 (0x92) 纯白之境 / Proto-White World / 白堊境界 / 白亜の境界
  - sid=129 (0x81) 混沌转换 / Chaos Shift / 混沌輪迴 / ケイオシフト
  - Attributes: single-layer, non-exclusive, non-debuff. Boss fights now show proper 4-language names for these sids instead of falling back to 0x0095/0x0092/0x0081. i18n.json character buffs reverted to 119 entries (87 wrongly-added removed); buff_attrs.json gained 3 entries (144->147). No source-code logic change.

== v22.30 ==
• V2230 (22.30): Code-audit cleanup release (no functional or default changes - zero impact for existing users).
  - Removed 6 duplicate boss setting keys in DEFAULT_SETTINGS (show_boss_module / boss_window_x / boss_window_y / boss_scale_percent / boss_name_keywords / boss_keep_backdrop_when_absent) - leftover copy-paste from when the Boss module was added in V2200; the first copy was a dead default. Now unified into the main definition block.
  - Removed one redundant write of allbuff / boss halign / valign in get_settings (V2228 residue block, identical and idempotent with the V2229 block).
  - Added a module-level logger (logging.getLogger("GBFR_Indicator")); converted 52 silent `except Exception: pass` swallowers to `logger.debug(..., exc_info=True)` so swallowed exceptions (e.g. after a game update shifts memory offsets) become visible when logging is enabled - debuggability greatly improved, no change to control flow or defaults.
- **V2229 (22.29)**: Promoted "Screen H/V Alignment" + "H/V Margin (can be negative)" to all 5 modules (Core / Dodge / Skill / Main AllBuff / Boss). Each module's "Position & Scale" sub-tab now has:
  - **Screen Horizontal Align**: Custom / Left / Center / Right (default "Custom" = original X)
  - **Screen Vertical Align**: Custom / Top / Center / Bottom (default "Custom" = original Y)
  - **Horizontal Margin (can be negative)**: left/right margin for L/R alignment, -2000..2000 px. Positive pushes outward (away from edge); negative pulls inward (may overflow off-screen).
  - **Vertical Margin (can be negative)**: top/bottom margin for T/B alignment, -2000..2000 px. Positive pushes outward; negative pulls inward (may overlap taskbar and align flush with the physical screen bottom).
  - Defaults are "Custom / 0" — identical to old behavior, zero impact for existing users.
  - **Bug fix**: the "bottom alignment floats up a bit" issue was caused by Qt's availableGeometry() excluding the taskbar; set "Vertical Margin" to a negative value (≈ -taskbar height, e.g. -48) to align flush with the physical screen bottom. Negative values are fully supported.
  - Recalculated on every window refresh (scaling / resolution change), always kept aligned.

- **V2228 (22.28)**: Added a **Screen Alignment** setting to both the **Main all-Buff module** and the **Boss Buff module** (under each module's "Position & Scale" subtab): **horizontal** = Custom / Left / Center / Right, **vertical** = Custom / Top / Center / Bottom, **both default to "Custom"** (uses the original X/Y coordinates, identical to the old behavior). When not Custom, every window refresh (module scaling, resolution change, per-row / row-count change) recomputes that axis against the **primary screen's available area (taskbar excluded)** — horizontal: Left snaps to the left edge, Center centers horizontally, Right snaps to the right edge; vertical: Top snaps to the top edge, Center centers vertically, Bottom snaps to the bottom edge. The two modules compute independently and do not affect each other. The V2227 list-scrollbar fix is unaffected.

- **V2227 (22.27)**: Fixed the **real root cause** of "list rows collapsing into an unreadable pile when there are many entries". It had been treated as a simple "not enough height, last row gets clipped" problem (V2221 added the scroll area, V2225 raised max height 180→220), but the container was actually being **squashed by the QScrollArea**: it uses `setWidgetResizable(True)` while the inner container had no `sizePolicy`, so it was force-compressed to the viewport height — N rows got crammed into insufficient space, row heights squeezed, and the buff name overlapped the "移除" (Remove) button (player screenshot: the 7th entry of the Boss blacklist still overlapped). Fix: set the inner container's `sizePolicy` to `(Preferred, Maximum)` so it keeps its natural content height — the scrollbar now **actually appears** once content exceeds the max height, and content is never compressed. Max height also relaxed to 260px (~7-8 rows visible by default). Lists now never overlap no matter how many entries you add; they simply scroll. Applies to all 4 lists.

- **V2226 (22.26)**: 两件事。① Boss Buff 模块新增「内部固化门限」（永远开启，无开关）——boss 身上不可能出现「角色专属」与「专精」buff（这两类只属于玩家角色），render 端无条件剔除。原 `boss_exclude_exclusive` / `boss_exclude_mastery` 两个设置键保留，仅作旧配置兼容、不再影响判定；**主控全 Buff 模块的同名开关保持不变**，因为你自己的角色确实会有专属 / 专精 buff。② 主控全 Buff 与 Boss 两个模块新增「行内对齐」设置（靠左 / 居中 / 靠右，**默认靠左**）：决定每行 buff 卡片在该行内的水平排布——「靠左」从行首开始排（与旧版一致）、「居中」不足一行的卡片整体居中、「靠右」贴行尾排。满行时三者完全等价，只有最后一行（不足「每行数量」）才看得出差别。设置位置：对应模块的「布局」子标签。

- **V2226 (22.26)**: Two changes. 1) The Boss Buff module now has a hard-coded internal gate (always on, no toggle) — a boss can never have "character-exclusive" or "mastery" buffs (those belong only to the player's character), so the renderer drops them unconditionally. The old `boss_exclude_exclusive` / `boss_exclude_mastery` keys are kept only for backwards compatibility and no longer affect the decision. **The same switches in the main All-Buff module are unchanged**, since your own character really can have exclusive/mastery buffs. 2) Both the main All-Buff and Boss Buff modules get a new "Row Alignment" setting (Left / Center / Right, **default Left**): it controls how buff cards are laid out horizontally within each row — "Left" starts at the row start (same as older versions), "Center" centers the cards of a partially filled row, "Right" pushes them to the row end. All three are identical for full rows; the difference only shows on the last row when it holds fewer cards than "Cards per row". Found in each module's "Layout" sub-tab.

- **V2225 (22.25)**: 修复「名单列表第 6 行显示乱码」的 bug。V2221 给名单加的 QScrollArea 固定最大高度 180px，刚好卡在「6 行」边界上——第 6 行底部被滚动区裁掉，QLabel 的 buff 名与右侧「移除」按钮叠在一起，显示成一团乱码（玩家截图反馈 Boss 黑名单第 6 项那一行）。现把最大高度放宽为 220px（约 7-8 行），6 行可完整显示、7-8 行才触发滚动条。两处名单容器（主控 / Boss）同改，4 个名单（主控黑名单 / 主控多次出现名单 / Boss 黑名单 / Boss 多次出现名单）同时生效。

- **V2225 (22.25)**: Fixed a bug where the 6th row of the buff-name lists rendered as garbled overlapping text. The QScrollArea added in V2221 had a fixed max height of 180px, which landed exactly on the "6 rows" boundary: the bottom of the 6th row got clipped by the scroll area, so the QLabel text (buff name) overlapped the "移除" (Remove) button and turned into unreadable mojibake (reported via screenshot on the 6th entry of the Boss blacklist). Max height is now relaxed to 220px (~7-8 rows), so 6 rows display fully and scrolling only kicks in at 7-8 rows. Both list containers (main / Boss) are changed, so all 4 lists are fixed at once.

- **V2224 (22.24)**: 外部补充文件 buff_attrs_unknown.json 改为「玩家可补充、保存即热更新」的覆盖文件。未知 buff 不再只是诊断日志，玩家可直接在该文件补 名称/繁中名/英文名/日文名，保存后下一帧（通常 <1 秒）即生效，无需重启或重装；未知 buff 的 attr 现含 日文名 占位（修 V2223 引入的「日语下未知 buff 名字空白」回归）；主控全 Buff 与 Boss 两模块对称接入热加载。V2220 删掉的外部改名通道，在此以更彻底的方式回归——保存即热更新，而非仅启动时读一次。

- **V2224 (22.24)**: The external supplement file buff_attrs_unknown.json is now a player-editable override with live hot-reload. Unknown buffs are no longer just a diagnostic log — players can fill in 名称/繁中名/英文名/日文名 directly, and changes apply on the next frame (<1s) after saving, no restart or reinstall needed. Unknown buff attrs now include a 日文名 placeholder (fixing the V2223 regression where unknown buff names were blank in Japanese). Both the AllBuff and Boss modules hook into the hot-reload. The external rename channel removed in V2220 returns in a more complete form — live hot-reload instead of loading once at startup.

- **V2223 (22.23)**: 修复日语模式下 buff 名显示为简体中文的问题。i18n.json 的 buffs 段本就含日语译名（ja），但三处名称映射都漏写了 ja：① 实时悬浮窗——read_overlay_data 组装 buff entry 时未写入 "ja" 字段，导致 `_buff_name(buff,"ja")` 永远 fallback 到简中；② 全 Buff 模块卡片的 name_key 映射、③ 设置面板名单回退映射，均漏 ja→日文名。现已全部补齐，切到日本語时 buff 名正确显示日文。

- **V2223 (22.23)**: Fixed buff names showing Simplified Chinese under Japanese language mode. The i18n.json buffs section already had JA translations, but three name-mapping spots all missed 'ja': 1) the live overlay — read_overlay_data did not write the "ja" field when assembling buff entries, so `_buff_name(buff,"ja")` always fell back to Simplified Chinese; 2) the All-Buff module card name_key mapping; 3) the settings-panel list fallback mapping — both missed ja→Japanese. All fixed; buff names now display correctly in Japanese.

- **V2222 (22.22)**: 恢复 sid/sub_id 上限「门限(阈值)」机制 + sid==0 永远显示。① 移除 V2217 硬编码的 `if sid_i == 0: continue` 与 `if sid_i == 0 and infinite: continue`——sid==0 的 buff（如攻击UP）现在也正常显示，不再被强制丢弃。② status_id / sub_id 上限从硬编码 0xFFFF 常闭，恢复为 V2217 之前的可配置门限：主控「门限」页与 Boss「门限」页各重新出现「status_id 上限」「sub_id 上限」两个勾选+数值框，默认阈值 0xFFFF（与旧硬编码行为等价，只有玩家主动调小才会过滤）。改动只触及渲染端门限 + 设置键 + UI 控件。

- **V2222 (22.22)**: Restored the status_id/sub_id upper-limit GATE (threshold) and made sid==0 always show. ① Removed the V2217 hardcoded `if sid_i == 0: continue` and `if sid_i == 0 and infinite: continue` — buffs with sid==0 (e.g. DMG↑) now display normally instead of being force-dropped. ② status_id / sub_id upper limits changed from a hardcoded 0xFFFF constant back to the pre-V2217 configurable gate: both the "All Buff" and "Boss Buff" "Gate" pages regain a "status_id max" and a "sub_id max" checkbox+spinbox, defaulting to 0xFFFF (same as the old hardcoded behavior — only a player-lowered threshold actually filters). Only the render gate, settings keys and UI controls changed.

- **V2221 (22.21)**: 名单列表添加 `QScrollArea` 滚动条——「全 Buff」与「Boss Buff」两个模块各有两个名单（黑名单 + 多次出现名单），合计 4 处。原先用 `QVBoxLayout` 直接堆叠 buff 行、无最大高度也无滚动条，buff 多了就被对话框切掉。现在 4 处统一在 `_add_buff_list_group` 工厂函数内把内部容器包进 `QScrollArea`，固定最大高度 `180px`（约 6–7 行），超出即可上下滚动；深色风格滚动条样式与整体配色一致。一处修改、4 处生效（工厂函数被 4 个名单共用）。标题栏自报 `V2221`。

- **V2221 (22.21)**: Added a `QScrollArea` scrollbar to all buff lists — both the "All Buff" and "Boss Buff" modules each have a "Blacklist" + "Multi-instance" pair (4 lists in total). Previously these stacked added-buff rows directly in a `QVBoxLayout` with no max height and no scroll bar, so a long list would be cropped by the dialog. All 4 lists now wrap the inner container in a `QScrollArea` inside the shared factory `_add_buff_list_group`, with a fixed `180px` max height (~6–7 rows); the dark-themed scrollbar matches the UI. One change covers all 4 lists. Title bar shows `V2221`.

- **V2220 (22.20)**: 删除外放玩家字典 `buff_attrs_user.json`。现在数据来源为「内置 `buff_attrs.json`（封进 exe）+ 外部唯一诊断文件 `buff_attrs_unknown.json`」，exe 同目录里 buff 相关 json 只剩 `buff_attrs_unknown.json` 一个。未知 buff 永远显示十六进制 ID，不再提供外部改名通道；`buff_attrs_unknown.json` 仅作诊断日志（记录见过哪些不认识的 buff、各出现次数与最后见到时间），若你确认了某 ID 是什么，请连同 ID 反馈给作者以便补充进内置表。

- **V2220 (22.20)**: Removed the external player dictionary `buff_attrs_user.json`. Data source is now built-in `buff_attrs.json` (bundled in the exe) plus the single external diagnostic file `buff_attrs_unknown.json`; the only buff-related json next to the exe is `buff_attrs_unknown.json`. Unknown buffs always show their hex ID with no external renaming channel; `buff_attrs_unknown.json` is diagnostic-only (which unknown buffs were seen, their counts and last-seen time). If you identify what an ID is, please report it to the author with the ID.

- **V2219 (22.19)**: 全面 i18n 收尾。217 处硬编码中文 UI 文本（标签页 / 卡片标题 / 行标签 / 复选框 / 按钮 / 启动进度 / 下拉项）此前完全没调用翻译，英文与日文玩家会直接看到中文——而这些译文早就写在 i18n.json 里，只是代码没取用。现已全部接入 `_tr()`；另补 15 条缺失的四语键（Boss 名单说明、About 诊断面板文本等），诊断面板 f-string 改为「`_tr`(静态片段) + 动态值」以免键变成运行时拼接值。语言下拉的「简体中文 / 繁體中文 / 日本語」按国际惯例保持各语言自己的写法，并修正了「繁体中文（繁体的）」这个开发备注。玩家可见的未翻译文本由 186 处降为 0。

- **V2219 (22.19)**: Full i18n sweep. 217 hard-coded Chinese UI strings (tab titles / card headers / row labels / checkboxes / buttons / startup progress / dropdown items) never called the translation layer, so English and Japanese players saw raw Chinese — even though those translations already existed in i18n.json and were simply never looked up. All now go through `_tr()`. Also added 15 missing four-language keys (Boss list descriptions, About diagnostic panel text, etc.), and rewrote the diagnostic panel's f-strings as `_tr(static fragment) + dynamic value` so the lookup key is not a runtime-concatenated string. The language dropdown keeps each language written in its own language (简体中文 / 繁體中文 / 日本語) as is conventional, and the dev note "繁体中文（繁体的）" was corrected to "繁體中文". Untranslated player-visible text: 186 → 0.

- **V2218 (22.18)**: 新增「启动软件默认锁定」开关（设置 → 全局 → 常规）。勾选后软件启动时默认锁定窗口，防止误拖拽/误缩放；解锁仍可用标题栏锁图标、全局热键（锁定/解锁）、托盘菜单。

- **V2218 (22.18)**: New "Lock windows on startup" toggle (Settings → Global → General). When enabled the app starts locked, preventing accidental drag/resize; unlock via the title-bar lock icon, global hotkey (Lock/Unlock), or tray menu.

- **V2217 (22.17)**: 修复「多排 buff 被模块窗口拦腰砍掉」的高度 bug：render 端卡片绘制高度沿用的旧「名称/层数/时间/进度条」四行公式，与已在 V2209 融合为三行（名称/层数/时间+进度条）的固定窗口尺寸、卡片实际内容不一致，四行公式算出的卡片比窗口槽高约 13px，第二排起被切。现把 render 高度公式、以及主控与 Boss 两模块的 recalc_layout 都对齐成与固定尺寸函数完全一致的「融合三行 + QFontMetrics」公式，三处（绘制/固定尺寸/重算布局）高度完全一致，多排 buff 完整显示。名称右侧 ∞ 移除（时间条已显示 ∞ / *∞）。四个门限 UI（status_id/sub_id 上限、层数矛盾、时长上限）固化为常闭、进度条与衬底宽高移入布局标签页，随本版一并落地。

- **V2217 (22.17)**: Fixed the height bug where multi-row buffs got sliced off by the module window. Root cause: the render-side card draw height still used the old 4-row formula (name/stacks/time/bar), while the per-frame fixed window size and the actual card content had already been fused into 3 rows (name/stacks/time+bar) since V2209, making each card ~13px taller than the window slot and clipping from the 2nd row. This version aligns the render height formula and both AllBuff/Boss modules' recalc_layout to the exact same fused-3-row + QFontMetrics formula, so all three height computations agree and multi-row buffs display fully. Removed the ∞ symbol from buff names (the time bar already shows ∞ / *∞). The four threshold UI controls are now hardcoded always-on and the progress-bar/backing width-height moved into the Layout tab, both finalized in this version.

- **V2216 (22.16)**: **「时长上限」门限改造**：remaining/initial 任一 ≥ 9999 秒时一律视作「永续」（不再走 durmax 丢弃），覆盖范围比 V2214 的「≥ 1e30（FLT_MAX）兜底」更广——V2214 只解决游戏用 float32 最大值 3.4e38 标记的「假永续」buff，现在连 9999~100000 秒级的真实长 buff（如某些变身/长增益）也保留下来。**时间区永续显示区分「真/假」**：游戏 `infinite=True` 真永续 → 纯 `∞`；`infinite=False` 但因值 ≥ 9999 自动判定的「假永续」→ `*∞`（前缀星号提示非游戏原声明）。**删除「过滤 status_id == 0 (攻击UP 等)」两复选框**（主控与 Boss 各一个）：该过滤已固化为「常闭」——render 端无条件 `if sid_i == 0: continue`，攻击UP 类（sid=0）永不显示，无需 UI 开关。对应 settings 键从 DEFAULT_SETTINGS 移除，并加 load 迁移主动清理用户旧 config 里的残留 key，i18n.json 删 1 条 UI 串（4 语均无残留）。主控全 Buff 与 Boss 两处同步。

- **V2216 (22.16)**: **Max-duration gate overhaul**: when remaining/initial is ≥ 9999 s, the buff is now treated as perpetual (bypasses the durmax drop) — broader than V2214's `>= 1e30 (FLT_MAX)` fallback. V2214 only handled the float32-max sentinel; V2216 also keeps real long buffs in the 9999–100000 s range (e.g. some transformation / long-buff forms). **Time display distinguishes 'true' vs 'auto-detected' perpetual**: `infinite=True` (game-flagged) → plain `∞`; `infinite=False` but value ≥ 9999 (auto-detected) → `*∞` (asterisk prefix signals this is our own call, not a game-declared perpetual). **Removed the two `Filter status_id == 0 (DMG UP, etc.)` checkboxes** (one in AllBuff, one in Boss): the filter is now hard-coded as 'always on' — the render side unconditionally does `if sid_i == 0: continue`, so DMG-UP-class buffs (sid=0) never show, no UI toggle needed. The two settings keys are removed from DEFAULT_SETTINGS; a load-time migration also pops them from the user's on-disk config. i18n.json drops the matching UI string (no residue in any of the 4 languages). Both AllBuff and Boss modules in sync.

- **V2215 (22.15)**: **V2214 的配套显示修复**：FLT_MAX（≈3.4e38）表示「永续/无时限」buff，V2214 已让它不再被时长上限门限误杀，但卡片时间区仍按 `f"{rem:.1f}/{init:.1f}"` 打印会显示天文数字撑爆卡片。现在检测到 remaining 或 initial ≥ 1e30 时，时间区统一显示 `∞`。主控全 Buff 与 Boss 两处同步。

- **V2215 (22.15)**: **Companion display fix for V2214**: FLT_MAX (~3.4e38) means a permanent/untimed buff. V2214 stopped the duration-max gate from dropping those buffs, but the card's time row still printed `f"{rem:.1f}/{init:.1f}"`, producing an astronomical number that blew the card layout apart. Now when `remaining` or `initial` is >= 1e30 the time row shows `∞`. Applied to both modules.

- **V2214 (22.14)**: **修复「永续 buff 不显示」的 bug**：游戏用 float32 最大值（FLT_MAX ≈ 3.4e38）表示「永续/无时限」buff，但这类 buff 的 `infinite` 标志未必为 True（实测 sid=0x92(146) 就是 `infinite=False` + FLT_MAX）。原来的「时长上限」门限（默认 10000 秒）把它当成「时长超上限的垃圾」丢掉，导致这类永续 buff 永远不显示。修法：把极大的 remaining/initial（≥ 1e30）视作永续并豁免时长上限门限，主控全 Buff 与 Boss 两处同步。**配套**：`render_bossbuff` 每 1 秒把「过滤前 raw」与「过滤后 items」dump 到 `last_boss_buffs.json`，对比即可看出哪个 buff 被哪道门限丢了（游戏暂停时主菜单遮住画面，截图截不到 overlay 本身）。

- **V2214 (22.14)**: **Fixed: permanent/untimed buffs were never displayed.** The game encodes a permanent buff as float32 max (FLT_MAX ~ 3.4e38) in remaining/initial, but its `infinite` flag is not necessarily True (measured sid=0x92(146): `infinite=False` + FLT_MAX). The duration-max gate (default 10000 s) treated FLT_MAX as garbage exceeding the cap and dropped it, so permanent buffs never appeared. Now a huge remaining/initial (>= 1e30) is treated as permanent and exempted from the duration-max gate, in both the Master All-Buff and Boss loops. **Companion**: `render_bossbuff` dumps both pre-filter raw and post-filter items to `last_boss_buffs.json` every second, so you can diff and see exactly which buff was dropped by which gate (when paused, the pause menu covers the screen so screenshots can't capture the overlay).

- **V2212 (22.12)**: V2212 debug：把 render_bossbuff 过滤后的 items 节流 dump 到 EXE_DIR/last_boss_buffs.json（每 1 秒）。游戏暂停时主菜单会遮住游戏画面，截图只能截到主菜单，看不到 boss 模块本身。加 dump 后玩家或自动化工具直接读这个 json 就能拿到 boss 身上当前所有 buff（sid/名称/剩余/持续/是否未知），完全不需要截游戏画面。**纯 read-only 旁路，不影响显示逻辑与门限行为**。

- **V2212 (22.12)**: V2212 debug: throttled dump of render_bossbuff filtered items to EXE_DIR/last_boss_buffs.json (every 1 s). When the game is paused, the pause menu covers the game window and ImageGrab.grab only captures the menu, not the boss overlay. With this dump, players/automation can directly read last_boss_buffs.json to get the boss's current buffs (sid, name, remaining, initial, unknown flag) without any screenshot. **Pure read-only side channel, no impact on display logic or any gate**.

- **V2211 (22.11)**: V2117 固化的三门限再追加第 4 项：**剩余时间或持续时间任一 < 0 直接舍弃** —— 原来 0.0/0.0 的判断拦不住「-0.5/8.5」这种状态转换瞬间或数据异常导致的负值，现在合并成同一行判断 `if _zr < 0 or _zi < 0 or "0.0/0.0": continue`。主控全 Buff 与 Boss 循环对称、一次改两处。源码里所有「V2117 三门限」字样同步更新为「V2117+V2211 四门限」。

- **V2211 (22.11)**: The three gates V2117 locked in gained a fourth: drop any buff where remaining or initial goes below 0 - the old 0.0/0.0 check could not catch the negative values that occasionally show up during state transitions or data glitches. Now merged into one check `if _zr < 0 or _zi < 0 or "0.0/0.0": continue`. Applied symmetrically to the Master All-Buff and Boss loops. Also updated every in-source "V2117 三门限" wording to "V2117+V2211 四门限".

- **V2210 (22.10)**: 删除 Boss 模块的「分类显示」子标签（五个排除开关），设置项与内部检查保留以兼容旧配置；修复「明明是同一个 buff 却在模块里出现两次」的 bug —— ExStatus 是指针数组，同一条 status 可能被多个槽位指向，原逻辑每个槽位都读一次，而这些 sid 又被加进了「多次出现名单」，于是连重复读取也一起显示了。现在做两级去重且**不误伤真·多实例**：读取时按 status 指针地址去重，渲染时按内容指纹去重（同 sid 且 sub_id / 层数 / 剩余 / 持续 / 永续 五项全同才合并）。燃烧A(剩 8.5 秒) + 燃烧B(剩 3.2 秒) 这种真正不同的两层照旧全部显示；主控全 Buff 与 Boss 共用读取函数，一并修复。

- **V2210 (22.10)**: Removed the Boss module's "分类显示 / Category" sub-tab (five exclude switches); setting keys and internal checks are kept for old-config compatibility. Fixed "the same buff shows up twice": ExStatus is a pointer array and the same status can be pointed to by several slots, so the old code collected it once per slot - and because those sids were in the multi-instance list, the duplicate reads got displayed too. Now deduplicated in two stages **without harming real multi-instances**: by status pointer address at read time, and by content fingerprint at render time (same sid AND identical sub_id / stacks / remaining / initial / infinite). Genuinely different layers such as Burn A (8.5s left) + Burn B (3.2s left) are still all shown. The Master All-Buff and Boss modules share the reader, so both are fixed.

- **V2209 (22.09)**: 修复主控全 Buff 模块「模块缩放」被 Boss 模块缩放抢走的 bug（Boss 缩放同时控制两个、主控缩放改了没反应）；进度条与倒计时文本融合——倒计时文本居中浮在进度条上方，卡片由「名称 / 层数 / 时间 / 进度条」四行压缩为三行，真实省掉一整行垂直空间（主控 + Boss 同步生效）；buff 属性字典外放为 exe 同目录的 `buff_attrs_user.json`（首次运行自动导出全部 144 条，外部优先、按字段合并，玩家可直接增删改）；新增「特殊独立」属性，标记 5 条不走 ExStatus、需单独找偏移读取的 buff —— 古兰 / 姬塔的 Class等级、巴萨拉卡的古洛诺斯槽保持、伊德的隐藏槽、芙劳的转世的恩宠（sid 为负数占位，外放字典里用 `SP:{PL}:{idx}` 独立键）；主控全 Buff 模块也支持未知 buff 直接显示十六进制 ID，并把通过门限的未知 buff 每 5 秒落盘到 `buff_attrs_unknown.json`，玩家补好名字后复制进 `buff_attrs_user.json` 即永久生效。

- **V2209 (22.09)**: Fixed the Master All-Buff module's "Module Scale" being hijacked by the Boss module's scale (Boss scale controlled both, Master scale did nothing). Fused the countdown text into the progress bar: the text now sits centered on top of the bar, shrinking cards from 4 rows (name / stacks / time / bar) to 3 and saving a full row of vertical space - applied to both Master and Boss modules. The buff attribute dictionary is now external: `buff_attrs_user.json` is auto-exported next to the exe on first run (all 144 entries); the external file wins and merges per field, so editing only a name keeps 是否专属 / 单层 and the rest. Added a new "特殊独立" (standalone) attribute marking the 5 buffs that bypass ExStatus and need their own offset and read path: Gran / Djeeta's Adept Arts Level, Vaseraga's Grynoth Gauge Hold, Id's Hidden Gauge and Fraux's Enchantress's Blessing (their sids are colliding negative placeholders, so they are listed under `SP:{PL}:{idx}` keys). The Master All-Buff module now also shows uncataloged buffs as their hex ID, and dumps gate-passing unknown buffs to `buff_attrs_unknown.json` every 5s so players can name them and copy the entry into `buff_attrs_user.json`.

- **V2208 (22.08)**: Boss Buff 模块对未收录进 buff_attrs.json 的未知 buff 不再直接丢弃——之前 `render_bossbuff` 在 `BUFF_ATTRS.get(...)` 拿 None 时直接 `continue`，导致一些 boss 的 buff (DB 没收全 / 新 DLC / 玩家开 issue 找 buff) 整张卡片根本不出现，玩家以为工具没读到。现在改成：未知 buff 合成一个最小 attr（`名称 / 繁中名 / 英文名` 都填成 `0x{sid:04X}` 形式），玩家在 Boss 模块里能直接看到 ID，便于后续在 `buff_attrs.json` 里补名或 issue 报告里直接复制 ID。过滤开关（`boss_exclude_*`、`boss_gate_*`）/ 黑名单 / 多次出现名单 一切照旧。

- **V2208 (22.08)**: Boss Buff module no longer silently drops buffs missing from `buff_attrs.json` — previously `render_bossbuff` did `continue` when `BUFF_ATTRS.get(...)` returned None, so any buff not yet cataloged (new DLC / DB gap / player-reported miss) was never rendered. Unknown buffs now synthesize a minimal attr (name / 繁中名 / 英文名 all become `0x{sid:04X}`), so the player sees the raw ID. Filter switches / blacklist / multi-instance whitelist unchanged.
- **V2207 (22.07)**: Fixed the triple bug where the Boss Buff module's values could not be edited and changes never reflected to the live UI. (1) get_settings() only wrote 3 boss keys (window x/y, scale); all other boss_* keys were never saved. (2) The Boss gate widgets mistakenly reused self.gate_* (same names as the Master All-Buff module), overwriting AllBuff's references and leaving Boss with no self.boss_gate_* to reference. (3) Several Boss signals (exclude filters, gate checkboxes/spinboxes, canvas bg opacity) were never connected. Fix: renamed all 16 Boss gate attributes to self.boss_gate_*, wired all missing Boss signals, and completed all non-color boss_* keys in get_settings/reset_defaults. Title bar reports 22.07; built GBFR_CooldownIndicator_V2207.exe.
- **V2207 (22.07)**：修 Boss Buff 模块「所有数值都不能修改、改了不反映到实时 UI」的三重 bug：① get_settings() 只写回 3 个 boss 键（窗口 x/y、缩放），其余 boss_* 键全未保存；② Boss 门限控件误用 self.gate_*（与主控全 Buff 模块同名），覆盖 AllBuff 引用且 Boss 自身无 self.boss_gate_* 可引用；③ 多个 Boss 信号（排除过滤、门限勾选/数值、画布背景不透明度）从未连接。修法：Boss 门限 16 个属性全部重命名为 self.boss_gate_*、补连全部漏连信号、补齐 get_settings/reset_defaults 的全部非颜色 boss_* 键。版本号 +1（V2206 → V2207，标题栏自报 22.07）；构建 GBFR_CooldownIndicator_V2207.exe。

- **V2206 (22.06)**: Fixed three bugs in the **Boss Buff** module's "Lists" subtab that left its dropdown menus empty (the user's "no selectable dropdown" report). (1) V2202 failed to rewrite `which="bl"/"ml"` and stored groups in `self._allbuff_buff_groups`, a dict separate from the main module's `self._buff_groups` — `_refresh_buff_combo` always refreshed only the main module's combo. (2) `_WHICH_KEY` / `_WHICH_OPP` only supported `bl` / `ml`. (3) `DEFAULT_SETTINGS.boss_multi_list` was a bare-sid list `[7, 42]` inconsistent with the main module's dict list format, causing `dict(7)` TypeError. Fix: `_WHICH_KEY` / `_WHICH_OPP` expanded to four keys (`bl` / `ml` / `boss_bl` / `boss_ml`, no cross-group mutex), `_which_list` tolerates bare sids and normalizes them, Boss groups share the main `self._buff_groups` dict. Verified: all 4 combos hold 56 generic buffs, `boss_ml` reads legacy `[7, 42]` and normalizes to `[{"sid": 7}, {"sid": 42}]`. i18n.json still covers 721 entries in four languages, `_audit_lang.py` reports "missing: 0". Title bar reports 22.06; built `GBFR_CooldownIndicator_V2206.exe`.\n- **V2206 (22.06)**：修 Boss Buff 模块「名单」subtab 的 3 个 bug（下拉菜单永远是空的，即用户报告的"没有能选择的下拉菜单"）。① V2202 漏改 `which="bl"/"ml"` + 存到独立的 `self._allbuff_buff_groups` 字典（与主控的 `self._buff_groups` 同 key 冲突），导致 `_refresh_buff_combo` 永远只刷主控的 combo。② `_WHICH_KEY` / `_WHICH_OPP` 只支持 `bl` / `ml` 两个 key。③ `DEFAULT_SETTINGS.boss_multi_list` 用裸 sid 列表 `[7, 42]`，与主控的 dict 列表格式 `{"sid": 7}` 不一致，`_which_list` 里 `dict(7)` 抛 TypeError；旧版 `overlay_settings.json` 也沿用此格式。修法：`_WHICH_KEY`/`_WHICH_OPP` 扩展为 4 个 key（`bl`/`ml`/`boss_bl`/`boss_ml`，跨组不互斥），`_which_list` 兼容裸 sid 自动转 dict 列表，Boss 段存到 `self._buff_groups` 共享字典。验证：4 个 combo 全部 56 项通用 buff，`boss_ml` 正确读取旧版 `[7, 42]` → `[{"sid": 7}, {"sid": 42}]`。i18n.json 四语仍为 721 条，`_audit_lang.py`「缺失 0」。版本号 +1（V2205 → V2206，标题栏自报 22.06）；构建 `GBFR_CooldownIndicator_V2206.exe`。\n- **V2205 (22.05)**: Fixed a V2202 regression where all 6 subtabs of the **Boss Buff** settings page were added to the wrong parent tab (`a_sub` instead of `b_sub`) — the Boss module's settings page was empty, and the 6 subtabs were stacked on top of the Master All-Buff module's 6, making the user see what looked like 11 tab labels in the Master module (5 + a wrapped second row containing the same 5 names plus Color/Text). Verified after fix: both modules show 6 subtabs each (位置与缩放 / 布局 / 分类显示 / 门限 / 名单 / 配色与文字); the apparent 'duplication' in the Master module was just Qt wrapping its 6 subtabs into 2 rows when the tab bar was too narrow. i18n.json still covers 721 entries in four languages, `_audit_lang.py` reports "missing: 0". Title bar reports 22.05; built `GBFR_CooldownIndicator_V2205.exe`.\n- **V2205 (22.05)**：修 Boss Buff 模块设置页 6 个 subtab 父对象错位（V2202 漏改 `a_sub` → `b_sub`，导致 Boss 模块下完全是空的；6 个 subtab 实际被加到了「主控的全Buff模块」下，与原 6 个叠加为「同 5 个重复名称 + 配色与文字」= 视觉上 11 个标签条）。修复后：主控仍是 6 个 subtab（Qt 标签条宽度不够时自动换行 = 5+1 两行显示），Boss 现在也是 6 个 subtab。i18n.json 四语仍为 721 条，`_audit_lang.py`「缺失 0」。版本号 +1（V2204 → V2205，标题栏自报 22.05）；构建 `GBFR_CooldownIndicator_V2205.exe`。\n- **V2204 (22.04)**: Japanese names now come from authoritative sources instead of being translated from the Chinese names. (1) **Character-exclusive buffs**: extracted from the terms wrapped in a pair of corner brackets 「」 (U+300C/U+300D) inside GBFR Logs' `lang/*/skillboard.json` descriptions, then aligned zh-TW→jp by "same key + order of appearance" — the zh-CN file strips the brackets entirely and cannot be used directly, so zh-TW must serve as the bridge. **55 entries corrected**: Charisma = カリスマ (was リーダーの加護), Dark Zeal = 黒き血潮 (was 漆黒の血潮), Grynoth Unleashed = グロウノス解放 (was グロノスの力), Enchantress's Blessing = 転世の恩寵 (was 転生の恩寵), Loving Trust = 託された想い, Blood-Drinking Blade = 魂を蝕む刃, Limitless Light = 無限光, Malice = 闇禍, and more. (2) **All 87 mastery branches**: switched to `lang/*/skillboard-branches.json` (exactly 87 entries, carrying the official 覚醒/真髄/極意 tier names), bridged by English name — **87/87 replaced with official text** (all 87 had been self-translated before). (3) Fixed two swapped Gallanza buffs: Wild Showman = 荒事, Daredevil = 我武者羅 (reversed in V2203). i18n.json still covers 721 entries in four languages; `_audit_lang.py` reports "missing: 0". Title bar reports 22.04; built `GBFR_CooldownIndicator_V2204.exe`.
- **V2204 (22.04)**：日语译名全面改为权威来源，不再凭中文名自译。① **角色专属 buff**：从 GBFR Logs 的 `lang/*/skillboard.json` 文本描述里、被一对「」(U+300C/U+300D) 括起来的词中提取，按「同 key + 出现顺序」做 zh-TW↔jp 精确配对（**注意 zh-CN 版把括号整段删了、不能用，必须走 zh-TW 当桥**），共修正 **55 条**：领袖庇佑=カリスマ（原误 リーダーの加護）、漆黑血涌=黒き血潮（原误 漆黒の血潮）、古洛诺斯之力=グロウノス解放（原误 グロノスの力）、转世的恩宠=転世の恩寵（原误 転生の恩寵）、托愿=託された想い、蚀魂魔刃=魂を蝕む刃、无限之辉=無限光、暗灾=闇禍 等。② **专精 87 条**：改用 `lang/*/skillboard-branches.json`（正好 87 条，含官方 覚醒/真髄/極意 三阶名），按 en 名桥接，**87/87 全部替换为官方文本**（此前 87 条全是自译）。③ 修正伽兰查两条写反：武夫=荒事、莽夫=我武者羅（V2203 时两者互换）。i18n.json 四语仍为 721 条，`_audit_lang.py`「缺失 0」。版本号 +1（V2203 → V2204，标题栏自报 22.04）；构建 `GBFR_CooldownIndicator_V2204.exe`。
- **V2203 (22.03)**: i18n expanded from three to four languages — **Japanese (ja)** added alongside Simplified Chinese, Traditional Chinese and English. All four sections of i18n.json now carry Japanese: 486 UI strings, 29 character names, 119 character-exclusive buffs, 87 mastery branches (**721 entries**), verified by `_audit_lang.py` with "missing: 0". Proper nouns come from authoritative sources: (1) character names are verbatim from the game's own `data/system/table/text/jp/text_chara.msg` (グラン / ジータ / カタリナ …); (2) common statuses from GBFR Logs' `lang/jp/statuses.json` (攻撃UP / 防御UP / 毒 / 灼熱 / スロウ …); (3) character-exclusive buffs and the three mastery tiers (Insight/Essence/Crux → 覚醒/真髄/極意) have no official Japanese text and were translated from the Chinese/English names. Source-side: `ZH_TO_JA`, `_tr()` Japanese branch, `LANG_NAME_IDX` ja:3, Japanese branches in `_resolve_char` / `_buff_name` / `_skill_name`, a 4th tuple element in `CHAR_TYPE_NAMES`, a "日本語" entry in the language dropdown, and a Japanese reverse map in `retranslate_ui`. `release_notes.txt` and `version.json` changelogs are now quadrilingual (README stays bilingual per project convention). Title bar reports 22.03; built `GBFR_CooldownIndicator_V2203.exe`.
- **V2203 (22.03)**：i18n 三语 → **四语**，新增日语（ja），与简中/繁中/英文并列。i18n.json 四段全部补齐日语：UI 自译串 486 条、角色名 29 条、角色专属 Buff 119 条、专精分支 87 条（**合计 721 条**），`_audit_lang.py` 四语检查「缺失 0」。专有名词优先取权威来源：① 角色名取自游戏内 `data/system/table/text/jp/text_chara.msg` 原文（グラン / ジータ / カタリナ…）；② 通用 status 取自 GBFR Logs 的 `lang/jp/statuses.json`（攻撃UP / 防御UP / 毒 / 灼熱 / スロウ…）；③ 角色专属 Buff 与专精三阶（觉醒/真谛/秘义 → 覚醒/真髄/極意）游戏内无官方日语，按中文名+英文意译自译。源码同步支持 ja：`ZH_TO_JA`、`_tr()` 日语分支、`LANG_NAME_IDX` 加 ja:3、`_resolve_char` / `_buff_name` / `_skill_name` 日语分支、`CHAR_TYPE_NAMES` 元组加第 4 元素、语言下拉新增「日本語」、`retranslate_ui` 加日语反向映射。`release_notes.txt` 与 `version.json` 的 changelog 同步为四语（README 按项目惯例保持双语）。版本号 +1（V2202 → V2203，标题栏自报 22.03）；构建 `GBFR_CooldownIndicator_V2203.exe`。
- **V2202 (22.02)**: Boss Buff module's settings UI is now fully independent: cloned the entire Master All-Buff settings tab (layout / colors / text / progress bar / thresholds / exclusions / warning colors / lists) into a dedicated Boss Buff tab. All settings live on the new boss page; no more shared widgets with the Master All-Buff module. Added ~60 dedicated boss_* settings keys (boss_per_row / boss_rows / boss_name_font_size / boss_gate_* / boss_exclude_* etc.) — the Boss module now reads boss_* keys, the Master All-Buff module reads allbuff_* keys, and **the two no longer affect each other**. V2201 fixed a silent paintEvent crash (GBFROverlayQt was missing _boss_sub_flash / _boss_prev_sids initialization, so render_bossbuff threw AttributeError on first access and the outer try/except swallowed it — the window only showed an empty backdrop). V2200 initial release. Title bar reports 22.02; built `GBFR_CooldownIndicator_V2202.exe`.
- **V2202 (22.02)**：Boss Buff 模块的 UI 设置页完全独立化：复刻主控全 Buff 模块的整套设置页（布局/配色/文字/进度条/门限/排除/警告色/名单）为 boss 版，所有设置改 boss 模块的「Boss Buff模块」标签页里的控件，不与主控全 Buff 模块共用。再加约 60 个独立的 boss_* 设置键（boss_per_row / boss_rows / boss_name_font_size / boss_gate_* / boss_exclude_* 等）—— 现在 boss 模块读的是 boss_* 键，主控全 Buff 模块读的是 allbuff_* 键，**两者不再相互影响**。V2201 修 paintEvent AttributeError 静默失败（GBFROverlayQt 缺少 _boss_sub_flash / _boss_prev_sids 初始化，导致 render_bossbuff 第一次访问时抛异常被外层 try/except 吞掉，结果窗口只显示空底框）。V2200 首次新增。版本号 +2（V2200 → V2202，标题栏自报 22.02）；构建 `GBFR_CooldownIndicator_V2202.exe`。
- **V2200 (22.00)**: New **Boss Buff module** (5th module) — a separate overlay window that shows every buff/debuff currently on the boss in real time (ATK DOWN, DEF DOWN, Poison, Burn, Slow, ...). The data source is fully decoupled from your own character: the boss body is located through the game entity table (entity name containing `enemy`, or uppercase `Em` + 4 digits, e.g. `placement_enemy_member` / `Em7202`), then its ExStatus is read (component at `actor+0xCF8`, list begin pointer at `actor+0xD10`). Verified in-game to reliably read every status id / stack count / remaining time on the boss (8 statuses read at once in testing). The module follows the same three shared traits as the existing modules: independent show/hide switch (Settings → Module switches), independent on-screen X/Y position, and independent overall scale, plus its own **Boss Buff** settings tab. Its appearance (colors / layout / thresholds / lists) reuses the **Master All-Buff** module's settings, so both stay in sync — tune once and both modules match. When not in combat, or the boss has no status, only the empty backdrop is drawn (no placeholder text). Boss lookup is cached for 1.5 s so the main loop is unaffected. Title bar reports 22.00; built `GBFR_CooldownIndicator_V2200.exe`.
- **V2200 (22.00)**：新增 **Boss Buff 模块**（第五模块）——独立悬浮窗口，实时显示当前场上 BOSS 身上的全部增益/减益（攻击DOWN、防御DOWN、中毒、灼热、缓速等）。数据源与主控角色完全解耦：通过游戏实体表定位 boss 本体（实体名含 `enemy` 关键字，或大写 `Em`+4 位数字，如 `placement_enemy_member` / `Em7202`），再读其 ExStatus（组件在 `actor+0xCF8`，列表首指针在 `actor+0xD10`）。实测可稳定读出 boss 身上全部 status 的 id / 层数 / 剩余时间（测试中一次读出 8 个）。模块具备三大共有特质：独立显隐开关（设置 → 模块开关）、独立屏幕位置 XY、独立整体缩放，并新增独立的 **Boss Buff** 设置标签页。外观（配色 / 布局 / 门限 / 名单）沿用**主控的全Buff模块**的同一套设置，两处同步生效——调一次两模块同款。未进战斗或 boss 身上没有状态时只画空底框，不出任何文字。boss 定位带 1.5 秒缓存，不影响主循环。版本号 +1（V2117 → V2200，标题栏自报 22.00）；构建 `GBFR_CooldownIndicator_V2200.exe`。
- **V2117 (21.17)**: Three gates are now permanent — no UI switch, always on: ① **NaN/Inf check** (data correctness — disabling it would only show garbage); ② **ID=0 exclude-infinite** (Attack UP can never be infinite; garbage entries set the infinite flag); ③ **Hide 0.0/0.0 countdowns** (infinite buffs have meaningless time fields). UI removes the three corresponding `QCheckBox`es, their signal connections, reset, and settings save. The render side drops the `g_nan` / `g_zero_notinf` / `g_hide_zero` local variables and the corresponding `if` guards (logic now runs unconditionally). `settings` save still writes `True` for the three keys for backward compatibility. `DEFAULT_SETTINGS` keeps the three keys (with comments marking them as permanent). Other numeric gates (status_id max / sub_id max / stacks max / stack-conflict / duration max / min remaining / min initial / min appearance) remain user-tunable. Title bar reports 21.17; built `GBFR_CooldownIndicator_V2117.exe`.
- **V2117 (21.17)**：固化三个门限（永远开启，不再提供开关）：① **NaN/Inf 检查**（数据自洽，关掉只会显示垃圾）；② **ID=0 排除永续**（攻击 UP 不可能是永续，垃圾条目会把 infinite 置 1）；③ **隐藏倒计时 0.0/0.0**（永续 buff 时间区无意义）。UI 移除三个对应 QCheckBox、信号连接、重置与保存；render 端去掉 `g_nan` / `g_zero_notinf` / `g_hide_zero` 局部变量与对应 `if` 守卫（无条件执行）；settings 保存仍写 `True` 以兼容旧 config；`DEFAULT_SETTINGS` 三个 key 保留并加注释说明已固化。其它数值门限（status_id 上限/sub_id 上限/层数上限/层数矛盾/时长上限/最小剩余/最小初始/最小出现持续时间）仍可调。版本号 +1（V2116 → V2117，标题栏自报 21.17）；构建 `GBFR_CooldownIndicator_V2117.exe`。
- **V2116 (21.16)**: Top-level tab "All-Buff" renamed to **Master All-Buff**; the "Filter" sub-tab renamed to **Categorization** (it only governs display-layer switches). The old "Multi-Appearance Whitelist" section is rebuilt into two `QGroupBox`es under a new **Lists** sub-tab: **Blacklist** (placed first; listed sids never show, useful for suppressing transient shields that linger for one silent frame) + **Multi-Appearance List** (placed second; listed sids are exempt from the single-instance cap so multiple instances can stack). Both GroupBoxes share the same structure and UI; the dropdown uses three-layer filtering (character-exclusive buffs hidden + already-on-this-list hidden + already-on-the-other-list hidden). The render side now reads both lists (`multi_buff_blacklist` / `multi_buff_whitelist`); blacklist sids are filtered first, before any other gate or switch. New `settings["multi_buff_blacklist"]` default `[]`. Title bar reports 21.16; built `GBFR_CooldownIndicator_V2116.exe`.
- **V2116 (21.16)**：顶级 tab「全Buff模块」改名为**主控的全Buff模块**；「过滤」子标签改名**分类显示**（语义更准，只管显示层面开关）。原「多次出现白名单」段重构成「**名单**」子标签页下两个 `QGroupBox`：**黑名单**（在前，指定 sid 永不显示，适合屏蔽某些沉默帧残留的瞬时护盾）+ **多次出现名单**（在后，指定 sid 豁免单实例、可叠多实例）。两个 GroupBox 结构对称、UI 完全一致；下拉菜单三层过滤（角色专属不列 + 已加入自己名单不列 + 已加入对方名单不列）。render 端读双名单（`multi_buff_blacklist` / `multi_buff_whitelist`），黑名单 sid 在所有门限/开关之前最优先过滤。新增 `settings["multi_buff_blacklist"]` 默认 `[]`。版本号 +1（V2115 → V2116，标题栏自报 21.16）；构建 `GBFR_CooldownIndicator_V2116.exe`。
- **V2115 (21.15)**: All-Buff module removes every status-machine placeholder text: when no character or no active buff is detected, the centered "All-Buff (no character)" / "All-Buff (no active buff)" texts no longer appear; only the gray backdrop + white thin border from `_draw_module_backdrop` remain (visually identical to the Core/Skill/Roll modules empty-state). The `_draw_allbuff_placeholder` function body and the two i18n placeholder keys are gone — status-machine static text fully scrubbed from source and trilingual i18n. Title bar reports 21.15; built `GBFR_CooldownIndicator_V2115.exe`.
- **V2115 (21.15)**：全 Buff 模块删除所有状态机占位文本：未检测到角色、无活动 Buff 时不再显示「全Buff模块（未检测到角色）」「全Buff模块（无活动Buff）」居中文字，仅保留 `_draw_module_backdrop` 画的灰色背景板与白细边（与核心/能力/翻滚三大模块的空状态视觉一致）。彻底清掉 `_draw_allbuff_placeholder` 函数本体与 i18n.json 两条占位键——状态机静态文本从源码与三语 i18n 全部清理。版本号 +1（V2114 → V2115，标题栏自报 21.15）；构建 `GBFR_CooldownIndicator_V2115.exe`。
- **V2114 (21.14)**: The whitelist "Multi-Instance" dropdown now also hides buffs already on the list (instant disappear on add, re-appears on remove) to prevent duplicate adds; also restores the buff-attribute lookup that V2113 accidentally removed (clicking "Add" would have thrown NameError). Title bar reports 21.14; built `GBFR_CooldownIndicator_V2114.exe`.
- **V2114 (21.14)**：白名单「多次出现」下拉菜单进一步排除已加入白名单的 buff（添加后即时消失、移除后重现），杜绝重复添加；并补回 V2113 误删的 buff 属性赋值（点「添加」曾会 NameError）。版本号 +1（V2113 -> V2114，标题栏自报 21.14）；构建 `GBFR_CooldownIndicator_V2114.exe`。
- **V2113 (21.13)**: The whitelist "Multi-Instance" dropdown no longer lists character-exclusive buffs at all (V2111/V2112 greyed them out; V2113 removes them entirely) since exclusive buffs can never appear multiple times. The added-list also hides any exclusive sid accidentally present (legacy V2110 config defense); the render-side hard guard is kept. Version +1 (V2112 -> V2113, title bar reports 21.13); built `GBFR_CooldownIndicator_V2113.exe`.
- **V2113 (21.13)**：白名单「多次出现」下拉菜单彻底不再列出角色专属 buff（V2111/V2112 灰显，V2113 直接不出现）；已添加列表也会隐藏误入的专属 sid（防御 V2110 旧配置）；render 端保留硬保险强制剔除。版本号 +1（V2112 -> V2113，标题栏自报 21.13）；构建 `GBFR_CooldownIndicator_V2113.exe`。
- **V2112 (21.12)**: Hotfix: add the missing "from PySide6.QtGui import ... QStandardItemModel" that V2111 omitted. V2111 switched the whitelist add UI to a dropdown that used QStandardItemModel and QStandardItem, but only imported the latter, causing "Settings window construction error: name QStandardItemModel is not defined" on every launch. Adding QStandardItemModel to the existing import line fixes the crash. Version +1 (V2111 -> V2112, title bar reports 21.12); built `GBFR_CooldownIndicator_V2112.exe`.
- **V2112 (21.12)**：热补丁——补上 V2111 漏掉的「from PySide6.QtGui import ... QStandardItemModel」导入。V2111 把白名单改为下拉菜单时用了 QStandardItemModel 与 QStandardItem，但只导入了后者，导致一启动就弹「设置窗口构造异常：name QStandardItemModel is not defined」。把 QStandardItemModel 一并加进导入即可修复运行崩溃。版本号 +1（V2111 -> V2112，标题栏自报 21.12）；构建 `GBFR_CooldownIndicator_V2112.exe`。
- **V2111 (21.11)**: All-Buff module "Multi-Instance Whitelist" add UI changed to a dropdown listing every buff from buff_attrs.json (names in current language); players just pick a buff to allow multiple appearances — no manual ID typing. Character-exclusive buffs are greyed-out and unselectable in the dropdown. The render side adds a hard guard so an exclusive sid can never bypass de-duplication even if misconfigured. Version +1 (V2110 -> V2111, title bar reports 21.11); built `GBFR_CooldownIndicator_V2111.exe`.
- **V2111 (21.11)**：全 Buff 模块「多次出现白名单」添加改为下拉菜单，直接列出 buff_attrs.json 全部 buff（按当前语言显示名称），玩家点选即可放行多次出现，无需手动输入 ID；角色专属 buff 在下拉菜单灰显不可选。render 端加硬保险，专属 sid 即便误入白名单也会被强制剔除，永不可多次出现。版本号 +1（V2110 -> V2111，标题栏自报 21.11）；构建 `GBFR_CooldownIndicator_V2111.exe`。
- **V2110 (21.10)**: All-Buff module restores "default one instance per buff" (reverting V2108/V2109 per-slot multi-instance behavior): de-duplicate by sid, keeping only the first instance per same-name/same-sid and skipping the rest, matching the in-game UI. Added a "Multi-Instance Whitelist" — players can add buffs allowed to appear multiple times in the settings panel (All-Buff module -> Gates -> Multi-Instance Whitelist) by id (decimal or 0x hex); sids on the whitelist bypass de-duplication and can show multiple instances. Pre-seeded with two character-agnostic multi-instance buffs: "Pursuit" (sid=7) and "DMG up" (sid=42). The Gates tab also adds a "Hide buffs whose countdown reads 0.0/0.0 (perpetual etc.)" toggle (ON by default). Version +1 (V2109 -> V2110, title bar reports 21.10); built `GBFR_CooldownIndicator_V2110.exe`.
- **V2110 (21.10)**：全 Buff 模块恢复「默认每个 buff 只显示 1 个实例」（回滚 V2108/V2109 的逐槽位多实例行为）：按 sid 去重，同名/同 sid 仅保留首条实例，其余重复实例跳过，与游戏 UI 一致；同时新增「多次出现白名单」——玩家可在设置面板（全 Buff 模块 → 门限 → 多次出现白名单）添加允许重复出现的 buff（按 id，支持十进制或 0x 十六进制），白名单内的 sid 不受去重限制可显示多个实例，默认预置「追击(sid=7)」「造成伤害UP(sid=42)」两个全角色通用、可多次出现的 buff。门限页另新增「隐藏倒计时为 0.0/0.0 的 buff（永续等）」开关（默认开启）。版本号 +1（V2109 -> V2110，标题栏自报 21.10）；构建 `GBFR_CooldownIndicator_V2110.exe`。
- **V2109 (21.09)**: All-Buff module now de-duplicates perpetual / character-exclusive buffs down to one card. On top of V2108's "render every ExStatus instance", this keeps only the first instance per sid when the buff is `infinite` or flagged `是否专属` (is-exclusive) in buff_attrs — so persistent+exclusive buffs like Blazing Edge Infinity no longer spawn multiple cards, matching the in-game UI; ordinary finite buffs still keep multiple instances. Version +1 (V2108 -> V2109, title bar reports 21.09); built `GBFR_CooldownIndicator_V2109.exe`.
- **V2108 (21.08)**: All-Buff module now renders from the ExStatus slot list instead of the old sid dict. `read_exstatus_buffs` now also returns `result_list` (one entry per array slot, including duplicate sids), and `render_allbuff` iterates that list — multiple same-sid instances render as separate cards with independent countdowns and flashes. The Core module keeps using the sid dict, zero impact. Version +1 (V2107 -> V2108, title bar reports 21.08); built `GBFR_CooldownIndicator_V2108.exe`. module "same-name buff shows only one" bug. Root cause: `read_exstatus_buffs` was writing each ExStatus slot into a sid-keyed dict (`result[sid]=...`), so when the game gives multiple instances of the same sid (e.g. Percival's two "Pursuit" buffs), the later slot overwrote the earlier one, so the All-Buff module always drew just one card. Now it also returns `result_list` (one entry per array slot, including duplicate sids), and `render_allbuff` iterates that list instead — duplicate same-name buffs now render as separate cards with independent countdowns and flashes. The Core module keeps using the sid dict, zero impact. Version +1 (V2107 → V2108, title bar reports 21.08); built `GBFR_CooldownIndicator_V2108.exe`.
- **V2109 (21.09)**：全 Buff 模块新增「永续 / 角色专属 buff 只显示 1 个」去重。在 V2108「按 ExStatus 槽位列表如实显示所有实例」的基础上，对 `infinite` 或 buff_attrs「是否专属」标记的同 sid 仅保留首条实例，其余重复实例跳过——红莲之刃∞ 等永续+角色专属 buff 不再刷出多张卡，与游戏 UI 体验一致；普通有限 buff 仍保留多实例。版本号 +1（V2108 -> V2109，标题栏自报 21.09）；构建 `GBFR_CooldownIndicator_V2109.exe`。
- **V2108 (21.08)**：全 Buff 模块改为按 ExStatus 槽位列表渲染（而非旧的 sid 字典）。`read_exstatus_buffs` 现在同时返回 `result_list`（按数组槽位逐个收集所有实例），`render_allbuff` 改为按列表迭代——同名/同 sid 的多个实例会独立卡片显示，各自独立倒计时与闪光；核心模块继续用 sid 字典，零影响。版本号 +1（V2107 -> V2108，标题栏自报 21.08）；构建 `GBFR_CooldownIndicator_V2108.exe`。「同名 buff 只显示 1 个」的 bug。根因是 `read_exstatus_buffs` 把每个 ExStatus 槽位按 sid 字典写入（`result[sid]=...`），当游戏对同一 buff（如帕西瓦尔双「追击」）给出多个 sid 相同的实例时，后一个槽位覆盖前一个，全 Buff 模块永远只画 1 张卡。现同时返回 `result_list`（按数组槽位逐个收集所有实例），`render_allbuff` 改为按槽位列表渲染——同名副本显示成多张独立卡片，各自独立倒计时与闪光；核心模块继续用 sid 字典，零影响。版本号 +1（V2107 → V2108，标题栏自报 21.08）；构建 `GBFR_CooldownIndicator_V2108.exe`。

- **V2107 (21.07)**: Three things — (1) QSS now fully hides QSpinBox native up/down buttons (▲▼) and QComboBox native dropdown arrow (▽). The previous V2091 rule `width:0px` did nothing for vertically-stacked spinbox buttons, leaving the useless ▲▼ next to every number field and an isolated ▽ on combo boxes on Windows. Now uses `height:0px` plus `image:none` and `border:none` for the sub-controls, so both the up/down arrows and the dropdown arrow are truly invisible. (2) New "All-buff submodule flash" toggle in the **Flash Apply To** card (on by default), listed alongside Spike / Skill ready / Dodge icon flash. `render_allbuff` now does appear/disappear diff per sub-module: a sid present last frame but missing this frame → disappear flash; a newly added sid → appear flash. Flash shape = card-rect outline (1.5 px in `flash_color`) + translucent fill (alpha 60). Appear pulse curve is 0.3 ramp-up / 0.7 ramp-down (matching spike flash); disappear fades alpha 1→0 directly. Reuses global `flash_color` / `flash_duration_ms`. (3) i18n schema bumped 89 → 95, plus the new "全buff小模块闪光 / 全buff小模組閃光 / All-buff submodule flash" trilingual key. Version +1 (V2106 → V2107, title bar reports 21.07); built `GBFR_CooldownIndicator_V2107.exe`.
- **V2107 (21.07)**：三件事——① QSS 彻底隐藏 QSpinBox 原生上下按钮（▲▼）与 QComboBox 原生下拉箭头（▽）。之前 V2091 的 `width:0px` 对竖排 spinbox 按钮无效，Windows 上每个数字字段仍露出 ▲▼（点击无效，纯粹的废物）与孤立显示在组合框右侧的 ▽；现在改用 `height:0px` 并补 `image:none` + `border:none`，让两类 sub-control 真正归零。② **闪光应用模块**新增「全buff小模块闪光」开关（默认开），与尖刺闪光 / 能力冷却闪光 / 翻滚图标闪光 并列。`render_allbuff` 增每小卡片 appear/disappear 差分触发——上一帧 placed 里有、本帧没有 → disappear 闪光；本帧新出现 → appear 闪光。闪外形 = 卡片矩形描边（1.5 px `flash_color`）+ 半透填充（alpha 60）。appear 脉冲曲线 0.3 升 / 0.7 降（与尖刺闪光一致）；disappear 直接 alpha 1→0 淡出。复用全局 `flash_color` / `flash_duration_ms`。③ i18n 索引 schema 89 → 95，新增「全buff小模块闪光」三语键。版本号 +1（V2106 → V2107，标题栏自报 21.07）；构建 `GBFR_CooldownIndicator_V2107.exe`。

- **V2106 (21.06)**: Baked the author's personally tuned settings (overlay_settings.json, schema 90 — ~100 scalar/color/position/scale keys plus the 14 enabled characters in buff_enabled) directly into the source DEFAULT_SETTINGS, so fresh downloads ship with the author's tuned layout out of the box. Preserved: (1) all allbuff_* keys (the All-Buff module, absent from the author's file); (2) buff_order / buff_mastery / skill_cooldown_max (the author's file had these as empty {}, so the source-preset 119 mastery entries + 79 skill cooldowns are kept, avoiding wiping out-of-box data); (3) the settings_schema_version constant. The 13 orphan keys in the author's file were verified to be dead keys already removed in V2033/V2040 and are NOT written to DEFAULT (no resurrection of dead keys). Version +1 (V2105 → V2106, title bar reports 21.06), schema unchanged; built `GBFR_CooldownIndicator_V2106.exe`.
- **V2106 (21.06)**：把作者本人调好的全部设置（overlay_settings.json，schema 90，约 100 个标量/颜色/位置/缩放键 + 启用的 14 个角色 buff_enabled）烘焙进源码 DEFAULT_SETTINGS——新下载玩家开箱即作者调好的布局。保留项：① 全部 allbuff_*（全 Buff 模块，作者文件无此键）；② buff_order / buff_mastery / skill_cooldown_max（作者文件为空 {}，保留源码预置的 119 条专精 + 79 条技能冷却，避免清空开箱即用数据）；③ settings_schema_version 常量。作者文件里的 13 个孤儿键经核对均为 V2033/V2040 清理过的死键，不写入 DEFAULT（避免复活死键）。版本号 +1（V2105 → V2106，标题栏自报 21.06），schema 不变；构建 `GBFR_CooldownIndicator_V2106.exe`。

- **V2105 (21.05)**: Debuff classification is now table-driven instead of a numeric threshold. Debuffs are decided by the new `是否debuff` field in buff_attrs.json (merged from the last column of BuffMonitor's buff_attrs_v4.xlsx), replacing the old `sid ≥ 1000` cutoff. Known buffs use the table flag (26 known debuffs correctly flagged, including Poison/Burn/Slow/Dizzy/Glaciate and low-id debuffs like ATK↓/DEF↓/Max HP↓; notably 1009/1010/1013/1014 are ≥1000 but NOT flagged, so they correctly show as Buffs). Unknown ids fall back to `sid >= 1000` as a safety net. Also removed the "ailment classification threshold" gate setting (UI/connect/reset/save). Version +1 (V2104 → V2105, title bar reports 21.05), schema unchanged; built `GBFR_CooldownIndicator_V2105.exe`.
- **V2105 (21.05)**：Debuff 判定改为「查表」而非「编号阈值」。Debuff 现在由 buff_attrs.json 里新增的「是否debuff」字段决定（该字段由 BuffMonitor 的 buff_attrs_v4.xlsx 末列标注合并而来），取代旧的「编号 ≥ 1000」硬阈值。命中表用表内标记（26 个已知 debuff 正确标注，含中毒/灼热/缓速/昏迷/冰冻等 ailment，以及攻击DOWN/防御DOWN/最大HP减少等低编号 debuff；注意 1009/1010/1013/1014 虽 ≥1000 但未标记，正确识别为 Buff）；未命中（未知 id）回退旧阈值 1000 兜底。同时删除「ailment 分类阈值」门限设置（UI/连接/重置/保存）。版本号 +1（V2104 → V2105，标题栏自报 21.05），schema 不变；构建 `GBFR_CooldownIndicator_V2105.exe`。

- **V2104 (21.04)**: All-Buff module logic simplified. (1) Debuffs no longer get their own row — all Buffs come first, then all Debuffs appended after them in their existing sort order (no row break). (2) "Per Row" (per_row) and the new "Rows" (allbuff_rows) are both adjustable again; the module's overall size = per_row × rows × card size + row/column gaps, derived dynamically from these two values and the card size/gaps (it no longer scales with buff count, and a fixed grid is reserved even when empty / no character). (3) Capacity = per_row × rows, overflow truncated. (4) Removed the "Debuff Force New Row" toggle and its setting/i18n/reset/save wiring. Version +1 (V2103 → V2104, title bar reports 21.04), schema unchanged; built `GBFR_CooldownIndicator_V2104.exe`.
- **V2104 (21.04)**：全 Buff 模块逻辑简化。① Debuff 不再单独分行——所有 Buff 在前、所有 Debuff 接在其后（按原有排序），不另起一行；② 「每行数量」(per_row) 与新增的「显示行数」(allbuff_rows) 恢复为可调，模块整体尺寸 = per_row × rows × 卡片尺寸 + 行/列间隙，完全由这两个值和卡片尺寸/间隙动态算出（不再随 buff 数量伸缩，空 buff / 无角色时也预留固定网格）；③ 容量 = per_row × rows，超出直接截断丢弃；④ 删除「Debuff 强制另起一行」开关及其设置项/i18n/重置/保存逻辑。版本号 +1（V2103 → V2104，标题栏自报 21.04），schema 不变；构建 `GBFR_CooldownIndicator_V2104.exe`。

- **V2065 (20.65)**: Hotfix — fixed crash on opening the Settings dialog. V2064 had two stray method-local imports (`from PySide6.QtWidgets import QPlainTextEdit, QLabel` and `from PySide6.QtWidgets import QDoubleSpinBox`) inside the new Junk Filter tab builder. Since `QLabel` / `QPlainTextEdit` / `QDoubleSpinBox` were already imported at module top, re-importing them inside a method made them locals of that method, which broke every nested closure that captured them (textChanged / stateChanged callbacks etc.) — Python raised `cannot access free variable 'QLabel' where it is not associated with a value in enclosing scope`. Fix: removed both method-local imports; reuse the module-top names. Version +1 (V2064 → V2065, title bar reports 20.65), schema unchanged; built `GBFR_CooldownIndicator_V2065.exe`.
- **V2065 (20.65)**：热修复——修复打开设置时的崩溃 bug。V2064 在「过滤垃圾」tab 的构建方法内多写了两行 `from PySide6.QtWidgets import QPlainTextEdit, QLabel` 与 `from PySide6.QtWidgets import QDoubleSpinBox`，但这三个名字在文件顶部已 import 过；方法内重复 import 会让它们成为该方法的 local 变量，导致所有内嵌 closure（textChanged/stateChanged 等回调中引用同名符号的）抛 `cannot access free variable 'QLabel' where it is not associated with a value in enclosing scope`。修法：删掉这两行方法内 import，复用模块顶部已 import 的同名符号。版本号 +1（V2064 → V2065，标题栏自报 20.65），schema 不变；构建 `GBFR_CooldownIndicator_V2065.exe`。

- **V2068 (20.68)**: All-Buff module — fixed the deeper "NaN-to-zero" root cause that V2067 had not fully resolved. `read_exstatus_buffs` had been writing NaN/Inf duration fields as 0 (GBFR stores NaN for infinite / pending buffs). Those buffs entered `all_buffs_filtered` and were then killed by the render gate's `min_initial_time < 0.05s` and `min_remaining_time < 0.05s` checks, leaving the whole All-Buff module blank (the Core module is unaffected, as it does not read `initial`/`remaining`). Now matches `GBFR_BuffMonitor._parse_statusbase`: the reader discards any buff with NaN/Inf duration at parse time (`continue` skip). The render also adds a `not infinite` guard to `min_initial_time` for defense. All V2067's 5+5 numeric gates / `BUFF_ATTRS` whitelist / 5 legacy Filter toggles are unchanged — the Indicator and the Monitor are now behaviorally identical with matching gate settings. Version +1 (V2067 → V2068, title bar reports 20.68), schema unchanged; built `GBFR_CooldownIndicator_V2068.exe`.
- **V2068 (20.68)**：全 Buff 模块——修复 V2067 未完全解决的「NaN 归零误杀」真凶。`read_exstatus_buffs` 把 NaN/Inf 时长字段（GBFR 中永续/触发型 buff 常为 NaN）归零成 0 写入字典，这些 buff 进入 `all_buffs_filtered` 后被 render 的「最小初始时间 0.05s」「最小剩余时间 0.05s」门限全部误杀——全 Buff 模块空白（核心区不受影响，核心区不读 `initial`/`remaining`）。本次按 GBFR_BuffMonitor 的 `_parse_statusbase` 行为接管——reader 直接把 NaN/Inf 时长的 buff 整条 discard（continue 跳过）；render 同步给 `min_initial_time` 加 `not infinite` 守卫生效。所有 V2067 的 5+5 数值门限 / `BUFF_ATTRS` 白名单 / 5 个老过滤开关保持不变——monitor 与指示器「门限一致设置」完全同款行为。版本号 +1（V2067 → V2068，标题栏自报 20.68），schema 不变；构建 `GBFR_CooldownIndicator_V2068.exe`。

- **V2067 (20.67)**: All-Buff module — fixed the Gate's stack-conflict check. V2066's `cur_stacks>max_stacks` test lacked the `max_stacks>0` guard; GBFR reports `max_stacks==0` ("uncapped/undefined") for many buffs, so every buff with any stacks was wrongly dropped as a "stack conflict", leaving the whole All-Buff module blank. Now matches GBFR_BuffMonitor: conflict is only judged when `max_stacks>0`. Version +1 (V2066 → V2067, title bar reports 20.67), schema unchanged; built `GBFR_CooldownIndicator_V2067.exe`.
- **V2067 (20.67)**：全 Buff 模块——修复「门限」层数矛盾检查。V2066 的 `cur_stacks>max_stacks` 缺少 `max_stacks>0` 守卫；GBFR 大量 buff 的 max_stacks 为 0（无上限/未定义），导致所有有层数的 buff 被当成「层数矛盾」整批丢光，全 Buff 模块 Blank。现与 GBFR_BuffMonitor 一致——仅在 max_stacks>0 时才判矛盾。版本号 +1（V2066 → V2067，标题栏自报 20.67），schema 不变；构建 `GBFR_CooldownIndicator_V2067.exe`。

- **V2066 (20.66)**: All-Buff module — replaced the V206 4/V2065 blacklist/whitelist "Junk Filter" with the Gate (from GBFR_BuffMonitor) numerical junk filter. Every threshold is independently toggleable and live: status_id==0 / status_id max / sub_id max / ailment threshold (also drives the debuff color boundary) / current-stacks max / max-stacks max / stack-conflict / duration max / min remaining / min initial / NaN∪Inf checks. Defaults: most numeric thresholds on, `filter_status_id_zero` off (keeps id=0 like Damage Up), `max_stacks_max` off. The "Display Filter" tab reverts to V2063's "Filter" naming and restores the "Hide Infinite" toggle. Version +1 (V2065 → V2066, title bar reports 20.66), schema unchanged; built `GBFR_CooldownIndicator_V2066.exe`.
- **V2066 (20.66)**：全 Buff 模块——撤销 V2064/V2065 的「过滤垃圾」黑名单/白名单方案，改为搬自 GBFR_BuffMonitor 的「门限」(gate) 数值废料过滤。每项门限均可独立开关、实时生效：status_id==0 / status_id 上限 / sub_id 上限 / ailment 阈值（同时接管 debuff 颜色边界）/ 当前层数上限 / 上限层数上限 / 层数矛盾 / 时长上限 / 最小剩余 / 最小初始 / NaN∪Inf 检查。默认值：多数数值门限开启，`filter_status_id_zero` 关闭（保留 id=0 如攻击UP），`max_stacks_max` 关闭。「筛选显示」恢复 V2063 的「过滤」命名并补回「不显示永续」。版本号 +1（V2065 → V2066，标题栏自报 20.66），schema 不变；构建 `GBFR_CooldownIndicator_V2066.exe`。

- **V2062 (20.62)**: All-Buff module — auto-fit card backing and unbounded rows. The **card backing width / height** are now treated as an **auto-fit floor**: the layout recomputes the minimum visible width from `bar_width + 2*frame_thickness + 8 px inner padding` and the minimum visible height from `2*pad + name_h + elem_sp + stacks_h + elem_sp + time_h + elem_sp + bar_total` for every render frame, then takes `max(auto_min, user_value)` so cards are **never clipped** regardless of how small the user sets the slider. If the user set 75 × 58 (the screenshot value) and `auto_min` is 72 × 62, the card draws at 75 × 62 and the progress bar always fits. The **"Rows" control has been removed from the Layout sub-tab** — the row count is now `ceil(buff_count / per_row)` and the window auto-grows with the actual number of active buffs (e.g. 3 buffs with `per_row=3` ⇒ 1 row; 30 buffs ⇒ 10 rows). Render-end also resizes the AllBuff window precisely to the actual canvas when the user adds/loses a buff, so the window stays tight with no manual adjustment. The **per-row count** control is preserved as the only layout knob the player needs. Two new tooltip strings (`auto-fit floor` for width/height) added; one obsolete i18n key (`显示行数 / 顯示行數 / Rows`) removed; audit MISSING keys=0. Version +1 (V2061 → V2062, title bar reports 20.62), schema unchanged; built `GBFR_CooldownIndicator_V2062.exe`.
- **V2062 (20.62)**：全 Buff 模块——衬底自适应 floor + 取消硬行数上限。**卡片衬底宽/高**改为**自适应下限**语义：每帧按当前 `bar_width + 2*frame_thickness + 8 px` 算最小可见宽、按 `2*pad + name_h + elem_sp + stacks_h + elem_sp + time_h + elem_sp + bar_total` 算最小可见高，再取 `max(自适应最小值, 用户设置)`——玩家滑块拖到多小都不会裁切 buff 内容（用户截图设的 75×58 会被自动顶到不裁切的最小值）。**布局子页删除「显示行数」控件**——行数 = `ceil(buff 总数 / 每行数量)` 自动延伸（3 个 buff + 每行 3 ⇒ 1 行；30 个 buff ⇒ 10 行），窗口按实际 buff 数精确收/扩。**每行数量**作为唯一布局参数保留。i18n 删 1 条过期键（`显示行数` / `顯示行數` / `Rows`），加 2 条 tooltip 提示（三语完整、审计 MISSING=0）。版本号 +1（V2061 → V2062，标题栏自报 20.62），schema 不变；构建 `GBFR_CooldownIndicator_V2062.exe`。

- **V2061 (20.61)**: All-Buff module: default card backing **width 72 → 80** and **height 52 → 64**, fixing the visual bug where the countdown bar spilled past the card's bottom edge and overlapped the next row's cards (user screenshot reported "text being obscured"). Important context: the **Element Spacing** control is actually wired in correctly (the code already applies `elem_sp` at every gap — line 6178 / 6193 / 6201) and the **per-row count** control was already in the Layout sub-tab (line 2799) — only the *default values* were too tight, neither control was actually missing. Also added **Red Line ⑥** to the project memory: every source-code edit must bump `_BUILD_NO` (+1) and sync version.json + README Changelog + trilingual `release_notes.txt`. Version +1 (V2060 → V2061, title bar reports 20.61), schema unchanged; built `GBFR_CooldownIndicator_V2061.exe`.
- **V2061 (20.61)**：全 Buff 模块：卡片衬底默认 **宽度 72 → 80**、**高度 52 → 64**，修复「进度条溢出衬底底边扎入下一行卡片」的视觉 bug（用户截图反馈「字被遮住」）。重要说明：**元素统一间距**控件其实在代码里已经生效（line 6178 / 6193 / 6201 三处都用 elem_sp），**每行数量**控件也早已在布局子页（line 2799）——只是默认值不够紧，并非控件缺失。同时新增 **工程红线 ⑥** 写入项目长期记忆：每次源码修改必须把 `_BUILD_NO` +1，并同步 version.json + README Changelog + release_notes 三语。版本号 +1（V2060 → V2061，标题栏自报 20.61），schema 不变；构建 `GBFR_CooldownIndicator_V2061.exe`。

- **V2060 (20.60)**: All-Buff module UX pass. **Unified Element Spacing** (single parameter, default 4 px) inserted between name ↔ stacks ↔ time ↔ bar to give cards breathing room and stop the previously squashed values. **Bar 100% Outline Frame** (default 2 px stroke, same color as the bar) draws a visible upper-limit reference around each countdown bar; thickness adjustable, set to 0 to disable. **End-of-Timer Warning**: when the buff's remaining/initial percentage falls below the threshold, both the time text and the bar switch to the warning color; enable / threshold (1-99%) / warning color / opacity are independently adjustable. **Debuff Colors (ID ≥ 1000)**: Poison/Burn/Slow/Dizzy/Glaciate etc. debuffs (decimal sid ≥ 1000) have independent name / stacks / time / bar colors, visually distinct from normal buffs; Debuff warning is on by default (pure white for higher visibility). **Hotfix: V2050 character-detection regression** caused by an undefined `gate` reference in `read_exstatus_buffs` (runtime NameError every frame, breaking the readout thread); also removed the now-unused `sub_id` read and `GATE_DEFAULTS`/`_gate_filter_buff` dead code introduced alongside it, restoring V2040-equivalent core behavior. i18n adds 14 UI keys (zh/zh_tw/en complete, audit MISSING keys=0). Version +10 (V2050 → V2060, title bar reports 20.60); exe filename keeps `GBFR_CooldownIndicator_V2050.exe` (release URL continuity), `version.json` bumped to 20.60.
- **V2050 (20.50)**: **New "All-Buff Display" module (4th module).** A grid of lightweight cards lists every buff currently readable on the main character (same source as the Buff Monitor, supplied to both the core module and the all-buff module after a unified gate filter). It reuses the shared traits of the three existing modules: independent show/hide toggle / independent screen XY / overall scale / Position & Scale sub-tab / per-element opacity (name/stacks/time each have their own font size + color; the countdown bar and text backing each have independent opacity). Each card, top to bottom: buff name → stacks/max-stacks (single-layer shows 1/1) → remaining/duration seconds → a horizontal countdown bar; layout is adjustable (rows / per-row / row spacing / card spacing). 5 optional filter switches (all off by default = show everything): hide core-module buffs / hide infinite buffs / hide character-exclusive buffs / hide mastery buffs / hide single-layer buffs, mapped to the Buff Monitor's single-layer / exclusive / mastery fields. Data source switched to `buff_attrs.json` (143 in-game buffs with trilingual names and exclusive/mastery/single-layer flags), now bundled with the build; i18n adds 31 UI keys (zh/zh_tw/en all complete, three audit scripts report MISSING keys=0). Version +10 (V2040 → V2050, title bar reports 20.50), schema 94 unchanged; built `GBFR_CooldownIndicator_V2050.exe`.

- **V2039 (20.39)**: **Color-picker dialog "Custom colors" (16-cell palette) now persist across sessions.** Previously, `QColorDialog.getColor()` popped the system ColorPicker; after clicking "Add to Custom Colors" to fill cells, closing the app and re-launching wiped them all back to white (Qt's `QColorDialog` palette is in-process only — not customizable from Python). **Fix**: in `pick_color()`, **before** showing the dialog, restore the 16 stored hex colors from `settings['custom_palette']` via `QColorDialog.setCustomColor(i, QColor(hex))`; **after** the dialog closes (regardless of OK / Cancel), immediately read back `QColorDialog.customColors()` → save to `settings['custom_palette']` and call `save_settings` (so the 16 colors survive app restart). The **"Reset to Defaults"** button now also clears the 16 cells and resets the Qt global. `DEFAULT_SETTINGS` gains a `custom_palette: []` field. **Known limitations NOT fixed** (out of V2039 scope): ① "Add to Custom Colors" always fills the first empty cell — Windows system ColorPicker behavior, not customizable from Python; ② clicking an existing custom cell immediately overwrites the current selection — same reason. To get full flexibility would require a custom internal ColorPicker (~300 LOC); left as future work. Version +1 (V2038 → V2039, title bar reports 20.39), schema 94 unchanged; no i18n key added/removed (only `pick_color` flow changed + one settings field added).

- **V2038 (20.38)**: **Corrected fix** for Id's dragon-form ability names. V2037 wrongly reused PL1900 human-form skill names (Reginleiv Recidive / Unbound / Atonement / Ragnarok Form) for the dragon form, but the dragon form is a *separate* PL2000 with its own skill set (AB_PL2000_01~05: Reginleiv Recidive / Scourge / Never Enough / Arcadia / Fourfold Vengeance — not the same as human-form PL1900). Cross-checked against GBFR Logs `lang/zh-CN/abilities.json`: the project DB did not include PL2000, so the PL2000 hashes stored at `+ABILITY_HASH_OFFSET` never matched `_ab_hash_map`, showing blank. **Fix**: formally add PL2000's real abilities (hash→trilingual name) to `GBFR_Character_Skills_Buffs.json` so the hash lookup hits the real dragon-form names directly; and remove the erroneous `PL1900→PL1900` / `PL2000→PL1900` fallbacks added in V2037. Core Buff area still shares PL1900 data (BUFF_PROFILES logic, unaffected). Version +1 (V2037 → V2038, title bar reports 20.38), schema 94 unchanged; no i18n key added/removed (data entries + data-path fix only).

- **V2037 (20.37)**: **The REAL fix** for the bug where ability names under the Skill Module (skill_cd diamonds) disappeared when Id entered dragon form. V2036 misdiagnosed the cause — it tried to make `read_skill_cooldowns` read the ability hash from the true-body actor via `_resolve_id_actor`, but the game does NOT necessarily update `+ABILITY_HASH_OFFSET` on the true body during dragon form, so V2036 still ended up reading 0 / stale values, hence "still nothing". V2037 finally traces the **real** root cause: in dragon form, `pl_id` is resolved by `read_overlay_data` via `charid_hash` to **"PL1900"** (the true-body character ID — `CHAR_TYPE_TO_PL[0x20]="PL1900"`, **NOT** `PL2000`). The 4 hashes at `+ABILITY_HASH_OFFSET` on the dragon-form actor are dragon-form-specific hashes (not in the database), so `_ab_hash_map.get(h)` is a guaranteed miss; the original `PL_SKILL_FALLBACK` only listed `PL0100`/`PL2000`, **PL1900 was NOT in the fallback → `_lookup_ability` returned None → `_skill_name=""` → `_draw_skill_cd_name` returned → all 4 diamonds rendered nameless**. **Fix**: add `"PL1900":"PL1900"` to `PL_SKILL_FALLBACK`, so dragon-form hash misses can borrow the true-body PL1900 `ab_01..ab_04` by slot (Reginleiv Recidive / Unbound / Atonement / Ragnarok Form). Also reverted V2036's `_resolve_id_actor` change inside `read_skill_cooldowns` (wrong root cause; restore direct `char_base` read). **PL1900 true-body path is completely unaffected** — first branch hits and returns the same true-body ability names. Version +1 (V2036 → V2037, title bar reports 20.37), schema 94 unchanged; no i18n key added/removed (V2037 only touches the hash fallback table `PL_SKILL_FALLBACK`, no UI strings).

- **V2036 (20.36)**: **Bugfix — Skill-module ability names reappear when Id enters dragon form.** Root cause: `read_skill_cooldowns` reads the 4 ability hashes directly from `char_base + ABILITY_HASH_OFFSET`, but in dragon form `char_base` is the dragon-form actor (0x20) whose 4 hashes differ from the true-body PL1900; `_lookup_ability(pl_id="PL1900", ab_hash=dragon_hash)` misses, `_skill_name` returns empty, and `_draw_skill_cd_name` returns immediately, so the whole ability-name strip under the 4 diamond icons goes blank. `read_overlay_data` already applies `_resolve_id_actor` for the same class of bug on ExStatus — `read_skill_cooldowns` was the last holdout. **Fix**: add `_resolve_id_actor` inside `read_skill_cooldowns` so the ability hash is read from the true body actor; cd cooldown is still read from `char_base` (dragon actor's own cooldown state) to avoid introducing new risk. Normal form, Overdrive, and all other characters unaffected. Version +1 (V2035 → V2036, title bar reports 20.36), schema 94 unchanged; no i18n key added/removed (V2036 touches only the back-end data path, no UI string changes).

- **V2035 (20.35)**: **Three cleanup / UX changes** — (1) **Deleted the "Show startup splash screen" feature entirely** (no more splash-at-launch). Removed `class StartupSplash` (~80 LOC: `__init__ / _build_ui / _center / set_progress / finish`), the `DEFAULT_SETTINGS['show_startup_splash']` entry, the checkbox in Settings → Core Detection, the 5 touch-points (reset / creation / save / load / i18n key). `main()` now goes straight to `GBFROverlayQt(progress_cb=None)` — no qlineargradient card, no progress bar, no "正在加载设置…" stub. `i18n.json` dropped the "Show startup splash screen" trilingual key. (2) **Added a master "Enable EXE sync list" checkbox on the EXE-Sync card row (default ON).** One click to disable EXE sync entirely. Persisted to `settings['enable_sync_exe_list']` (default `True`); `_sync_exe_list_at_startup` reads it first — if off, return immediately, no daemon thread, no process enumeration, CPU = 0. `i18n.json` adds the trilingual "Enable EXE sync list" key. (3) **Buff-order & Mastery-gating table three-column width x 1.5**: column header label width `86~100` → `129~150px` (`MasteryBuffGroup._build` line 1805); per-row checkbox width `86~100` → `129~150px` (`_make_item` line 1931). Fixes earlier truncation of long branch names like "真谛：回复类能力强化"; column header and per-row checkbox geometry are now strictly aligned. Version +1 (V2034 → V2035, title bar reports 20.35), schema 94 unchanged; `GBFROverlayQt(progress_cb=...)` parameter kept to support any future progress-display need.
 201→
 202→- **V2034 (20.34)**: **Split spike-visibility and bead-visibility into two fully independent toggles.** V2033 used two "hide" options (hide spikes+beads / hide spikes only) whose combined semantics were convoluted and coupled. This build replaces them with the most straightforward design: two checkboxes under the "Spikes & Ring" card — "Show spikes (triangle bodies)" and "Show decorative beads (spike-tip dots)" — each toggled independently, giving 4 free combinations: both on (default, everything shown) / beads only / spikes only / both off (bare ring + timer + text). Implementation simply forces the relevant layer's color opacity to 0 or its configured value; no coupled combo logic remains. Old saves auto-migrate: previously "hide spikes+beads" -> both off; "hide spikes only" -> spikes off, beads on; neither -> both on. **Bugfix (same V2034 build, re-issued 2026-08-27 09:30)**: two rendering bugs in `_draw_spikes` reported via screenshots — (1) when a buff has zero stacks, decorative beads were incorrectly painted at all 7 phantom slots even though no spike exists to attach them; (2) when only "Show beads" is checked and "Show spikes" is unchecked, **both** spikes and beads vanished because the function set the global painter opacity to `spike_color_*` opacity (which is 0 when `show_spikes=False`), polluting the subsequent bead draw. Fixed by rewriting `_draw_spikes` with a single clear flow: when `draw_count<=0` return immediately (no spikes, no phantom beads); in the per-layer loop, branch A draws the triangle + bead together with explicit `setOpacity(spike_opacity)`; branch B draws bead-only and explicitly `setOpacity(1.0)` to recover from the 0-opacity pollution. No `_BUILD_NO` change (still 2034), schema 94 unchanged.

- **V2033 (20.33)**: **Added "Hide spikes only (keep beads)" toggle** (Settings → Spike module, right after "Hide spikes & beads"). Difference: "Hide spikes & beads" also hides the root decorative beads; "Hide spikes only" keeps the beads in place and only drops the outward spike triangles — for players who want just the ring + timer + text + beads, no spike triangles. Implementation: `DEFAULT_SETTINGS` adds `hide_spikes_only`; extracted `_draw_spike_bead` helper used inside `_draw_spikes`' `hide_only` branch; new `_hide_spikes()` helper merges the two flags at the canvas-size / empty-branch / `_render_buff_ui` call sites; the outline's bead stroke is also kept in only mode. Both toggles can be checked together (no mutual exclusion) — checking both equals "Hide spikes & beads". Version +1 (V2032 -> V2033, title bar reports 20.33), schema 94 unchanged.

- **V2032 (20.32)**: **Reverted three chained over-fixes** (V2026/V2027/V2031) that misapplied `_any_active_buff_stacks()`. Player intent: only when `active_buffs` is truly empty (no configured buff at all) does the whole module hide; "configured buff but live game stacks=0" should keep rendering the ring + spikes + timer + buff name normally. The same wrong predicate was shoveled into all three sites (spike_hidden / render_core outer-if / title-bar buff-name segment), each time making the previous fix look broken. This version rewinds all three back to V2025 semantics: look at `active_buffs` only, not at `stacks`. The "Hide spikes and decorative beads" option stays as-is (only short-circuits the spike/bead draw path). The "Hide spike-circle module when no buff" option stays as-is (only when `active_buffs` is empty does it push SPIKE_HIDDEN_KEYS entries to 0% opacity). V2031's "title->circle spacing spinbox now accepts negative values" is kept. Version +1 (V2031 -> V2032, title bar reports 20.32), schema 94 unchanged.

- **V2031 (20.31)**: **Fixed two regression bugs (per user-submitted screenshots).** (1) The "Title -> Circle Spacing" (`circle_pad_title`) QSpinBox in Settings used `setRange(0, 999)` which rejected negative values -- changed to `setRange(-999, 999)` so users can now drag the spike-circle canvas upward to overlap the title bar (`base_cy = TITLE_BAR_H + circle_pad_title + ...` already uses `circle_pad_title` as an active Y-position parameter; V2030 wrongly suspected this control was unused and kept its >=0 lower bound, the lower bound was simply meaningless, removing it <=0 allows the canvas to slide up over the title bar). (2) Fixed a chain bug introduced when V2026 changed the spike-hidden check to `_any_active_buff_stacks()`: the outer render branch in `render_core` was still `if self.active_buffs:` -- when the list was non-empty but every buff had `stacks == 0`, the circle / spikes / center icon / timer arc (all belonging to `SPIKE_HIDDEN_KEYS`) got clamped to `spike_hidden_opacity` (default 0%, fully invisible), while `_draw_buff_name` uses `buff_name_color` (NOT in `SPIKE_HIDDEN_KEYS`) so the buff-name tag kept rendering -- leaving the surreal visual of a perfectly drawn buff module whose circle / spikes / icon / timer are all invisible but a buff-name tag still floating in mid-air. Changed to `if self.active_buffs and self._any_active_buff_stacks():` -- when the list is non-empty but every buff's stacks=0, falls through to the empty branch (identical to the empty-list case), and the "hide spike circle when no buff" option controls "fully hidden / show empty circle" uniformly. Three places are now consistent: (a) spike hidden (since V2026), (b) buff module rendering branch (this version), (c) title-bar buff-name segment (already used `_any_active_buff_stacks()` since V2027). Version +1 (V2030 -> V2031, title bar reports 20.31), schema 94 unchanged.

- **V2030 (20.30)**: **Cleaned up 3 leftover UI artifacts (per user-submitted screenshots).** (1) Removed the long hint QLabel that used to sit under the "Update Check URL" input box in the Settings panel (the V303 url_hint) -- the input's placeholder is now considered enough hint, no need to read a paragraph explaining "why release CDN" right there. (2) Removed the dead `_open_config_dir` function ("Open Config & Log Directory") -- AST scan confirmed zero call sites (other than itself) and the tray menu never `addAction`'d it, so users never even knew where this entry was. Cleanly excised. (3) Removed the orphan `打开失败` key from `i18n.json` (its sole reference was the deleted function). The "设置打开失败" key is still used by the Settings dialog (line 5878) and is kept. The "Title -> Circle spacing" (`circle_pad_title`) control is kept -- it is an active render parameter that participates in `base_cy = TITLE_BAR_H + circle_pad_title + circle_r + spike_top_pad` (circle canvas Y position), NOT dead code. Version +1 (V2029 -> V2030, title bar reports 20.30), schema 94 unchanged.

- **V2029 (20.29)**: **Cleaned up the user-submitted audit report's dead code and missing keys.** Removed the never-called `_detect_build_no()` function (lines 84-99) and collapsed the 6-line `_BUILD_NO` comment block to 1 line (the changelog history was moved into release_notes / git log) -- AST scan showed zero call sites since `_BUILD_NO` was always hard-coded. Removed 6 unused top-level functions / classes (all AST-confirmed `used_as_Name=False`): `find_pid`, `resolve_player_ptr`, `read_raw_buffs`, `get_topmost_real_window_pid`, `enum_game_window_state` (plus its 4 orphan helpers `_enum_pids` / `_enum_state` / `_enum_game_windows_proc` / `_EnumWindowsProc` that became dead the moment the parent was removed), and the `BuffOrderGroup` class. Removed 4 unused imports (`QAction`, `QPolygonF` from QtGui; `QAbstractSpinBox`, `QDialogButtonBox` from QtWidgets). Patched 1 missing i18n key: the full tooltip string passed to `setToolTip(_tr(...))` at line 2363 (originally 2859) -- the entry was absent from `i18n.json`, so all three languages fell back to the zh string verbatim; complete zh / zh_tw / en translations were added. Note: the audit also flagged `_tr("打开失败")` (line 6026) as missing, but that key is actually present in `i18n.json` with valid zh_tw / en translations -- the report was wrong on this one, no change needed. Version +1 (V2028 -> V2029, title bar reports 20.29), schema 94 unchanged.

- **V2028 (20.28)**: **Added a flash to the 6th/7th-roll warning sign.** Previously the warning sign (red-outline yellow-fill rounded triangle shown on the 6th and 7th dodge) only did a scale pulse during the flash -- there was no brightness flash. V2028 overlays an additional `flash_color` pulse shaped exactly like the warning sign (rounded triangle, using the outer triangle path) on top of the red/yellow icon, with opacity that fades as `flash_progress` decays -- so the warning sign visibly flashes in its own shape, never replaced by a white box. It reuses the existing `flash_apply_dodge` (toggle), `flash_color`, `flash_scale` (pulse) and `flash_duration_ms` settings; no new setting was added. Version +1 (V2027 -> V2028, title bar reports 20.28), schema 94 unchanged.

- **V2027 (20.27)**: **Fixed the buff-name segment in the title bar status text still rendering while the spike circle had become transparent after enabling "Hide spiked circle when no buff"** (reporter 希耶提/Seofon: "after I turn off the hide-spike option, all that's left in the game is the buff name, the rest is gone"). Root cause: V2026 changed the spike visibility check in `render_core` to `not self._any_active_buff_stacks()` so a fully-specced buff with stacks=0 correctly hides the circle, but line 5486 in `_build_titlebar_status_text` (the function that builds the title bar's status text `角色名 - 专精 - (buff 名)`) was still using the old `if not self.active_buffs` check. With a buff fully specced but stacked=0, the spike circle hid but the buff-name segment stayed -- exactly the "only the buff name is left" symptom. V2027 aligns line 5486 with the same predicate, so the buff-name segment hides in lockstep with the spike circle. Version +1 (V2026 -> V2027, title bar reports 20.27), schema 94 unchanged.

- **V2026 (20.26)**: **Fixed "hide spike circle when no buff" failing when the user has a buff's three mastery tiers all checked but the buff's actual game-state stacks are 0** (reporter 狼奶奶: "I checked the option but it still shows when there's no buff"). Root cause: `render_core` checked `len(active_buffs) == 0`, but a buff fully enabled across all three mastery tiers is permanently in `active_buffs` regardless of real-time game-state -- even when its stacks are 0. The condition was always False, `spike_hidden=False`, and `_draw_circle` painted the empty ring at full `circle_color_normal` opacity. V2026 introduces `_any_active_buff_stacks()` and changes the condition to `not _any_active_buff_stacks()` (every entry in `active_buffs` has stacks `<= 0` = truly "no buff"), aligning with what the option label promises to the player. Version +1 (V2025 -> V2026, title bar reports 20.26), schema 94 unchanged.

- **V2025 (20.25)**: **Fixed "auto-hide when game loses focus" wrongly vanishing the overlay the moment you click/drag/resize one of its own modules.** Root cause: `_game_is_foreground()` only accepted the game PID (`self.pid` holds the game process, not the tool), so when you clicked or dragged a module the foreground became the tool's own process and was judged "background" -> the whole window hid, making module size/position/scale adjustment impossible. V2025 now also counts the tool's own process (`os.getpid()`) as "foreground" (stays visible while you interact with modules), and adds an `_interacting` lock during drag/resize so the focus-sync is skipped entirely and never hides. True "background" is now only when the foreground is a third-party program (desktop/browser/other app). Version +1 (V2024 -> V2025, title bar reports 20.25), schema 94 unchanged.

- **V2024 (20.24)**: **Fixed all overlay text rendering as tofu boxes (□□) when Windows regional settings = "Hong Kong (Traditional Chinese)"** (a user reported "boxes appear when region is Hong Kong, switching back to mainland fixes it"). Root cause: Qt on Windows does not read the system's Asian-font fallback table, and the entire codebase has 21 hardcoded `QFont("Segoe UI", ...)` calls -- Segoe UI contains no CJK glyphs, so Qt falls back to the missing-glyph rectangle. V2024 scans `QFontDatabase.families()` at startup (inside `main()`), picks an installed CJK family by priority (Microsoft YaHei -> JhengHei -> PingFang SC -> SimHei -> Malgun Gothic -> Yu Gothic -> Meiryo -> Source Han Sans CN/TC -> Noto Sans CJK), and calls `QFont.insertSubstitution("Segoe UI", cjk_family)` so every `QFont("Segoe UI", ...)` request that hits a missing glyph is filled by the CJK family -- zero call-site changes; works on any locale whose system has at least one CJK family installed (which is true for every Windows build shipped since Windows 7, both Simplified- and Traditional-Chinese regions). Version +1 (V2023 -> V2024, title bar reports 20.24), schema 94 unchanged.

- **V2023 (20.23)**: **Removed V2022's 600ms debounce** -- V2022 added a 600ms wait to mask the brief window flicker caused by rapid Alt-Tab, but the wait actually made "overlay fails to come back when the game returns to foreground" the new norm. V2023 restores the V2021 edge-triggered cadence -- the instant `prev != decision`, call `_show_all_windows()` / `_hide_all_windows()` (the 250ms focus timer itself is kept). **Out-of-combat now also follows foreground/background** -- Since V2013 the early-return for `_ooc_content_hidden=True` meant alt-tab while out of combat (map screen, quest NPCs, town) was dead. V2023 removes that early return so `hide()` clears the whole window (title bar included), and `_show_all_windows()` brings it back whole on the next edge; the next tick's `_ooc_content_mult` then re-applies the title-bar-only shrink. Version +1 (V2022 -> V2023, title bar reports 20.23), schema 94 unchanged.

- **V2013 (20.13)**: - **Reworked "auto-hide when the game loses focus" (随游戏前后台自动显隐)**: fixed 6 long-standing bugs. (1) Manual hide is now respected - pressing the Show/Hide hotkey or double-clicking the tray no longer gets force-restored by the auto-sync ~50ms later. (2) When the game isn't running the overlay no longer auto-minimizes, so you can open the tool first and tune settings before launching. (3) Steam/Discord overlays & companion pop-ups no longer trigger a false "game switched to background" minimize. (4) The foreground-window poll is now a separate low-frequency timer (250ms) instead of piggybacking on every 50ms scan tick - no more unnecessary per-frame Win32 calls. (5) Modal dialogs (e.g. Settings) now correctly suspend the sync. (6) A short grace window after a manual show prevents the race between manual-show and auto-minimize. - Version +1 (V2012 -> V2013, title bar reports 20.13), schema 93 -> 94.

- **V2012 (20.12)**: - **Fixed unreadable black-on-dark text in the settings dialog (QComboBox drop-down items + EXE-sync plain text box)**: the old global setStyleSheet only set `color:#fff` on QComboBox's *selected* row, so its `QComboBox QAbstractItemView` drop-down fell back to Qt's OS default theme (light background, black text) and the `zh / zh_tw / en` items looked like a black blob. The EXE-sync `QPlainTextEdit` wasn't covered by the stylesheet at all, so Qt default gave it black text too. The global stylesheet now also covers QPlainTextEdit (text `#dce8f8`, matching QLabel) and QComboBox's drop-down view (background `#242c40`, text `#ffffff`, selection `#3a4860`). - **Language drop-down is now hard-coded to three labels: 「简体中文 / 繁体中文（繁体的） / English」**: the previous list just showed the raw language codes `zh / zh_tw / en` like untranslated placeholders. The three labels are now fixed text + `addItem(text, userData)` so the actual `zh / zh_tw / en` codes live in userData and the runtime reads `currentData()`. **These three labels stay the same in every language mode** (retranslate_ui only walks findChildren(QLabel/QCheckBox/QPushButton/QLineEdit), never QComboBox items). DEFAULT_SETTINGS `language` default is now `"zh"`, so fresh installs start in Simplified Chinese. - Version +1 (V2011 -> V2012, title bar reports 20.12), schema 92 -> 93.
- **V2011 (20.11)**: - **Baked the entire dist settings file into the exe's built-in DEFAULT_SETTINGS (factory default now equals your currently tuned config)**: every entry of `dist/overlay_settings.json` (196 items, verified zero mismatches) overwrites DEFAULT_SETTINGS; the removed "Launch at Windows startup" key `autostart_enabled` is intentionally excluded, and `load_settings()` now actively `data.pop`s it to strip leftovers from old saves. - Version +1 (V2010 -> V2011, title bar reports 20.11), schema 91 -> 92.
- **V2010 (20.10)**: - **Added "Show startup splash screen" toggle (Global -> General, on by default)**: this is the progress-bar splash shown while the app is launching. On = current behavior (splash with progress bar at launch); Off = no splash at launch, goes straight to the main UI. After removing the mistakenly-added "Launch at Windows startup", this finally makes the "startup bar" a real on/off toggle. - **Fixed internal-dial differentiation leak (stack-count only / no countdown)**: when a dial's interior shows only the stack number (no countdown arc), the only colored elements are the number and its outline. The stack number defaults to white (zero saturation), and rotate_hue is a no-op on white -> the number stayed white and never differentiated, leaving only the outline to change color and breaking the same-color-family consistency. Now, when internal differentiation is on and the number color fails to rotate, it derives a bright tint from the outline's hue family, so the number also differentiates and stays distinguishable from the outline. - **i18n fixes (EXE sync + new feature)**: added English / Traditional-Chinese translations for the EXE-sync list label, placeholder and tooltip, the Title<->Circle gap tooltip, and the new splash-toggle label (these strings were never in the translation table, so they showed Chinese under en/zh_tw). The update-status state-machine strings were already covered and confirmed correct. - Version +1 (V2009 -> V2010, title bar reports 20.10).
- **V2009 (20.09)**: **Removed the "Launch at Windows startup (auto-run this app after logging into Windows)" checkbox** -- the HKCU Run registry write/remove feature added in V2007 was a misunderstanding: you actually meant a "startup bar" (a progress bar / splash screen shown while the app is launching), which is completely different from Windows boot-time auto-start. This build deletes the `autostart_chk` checkbox in Global -> General, the `_apply_autostart()` function, the two registry write sites (at startup and at save-time), and the `autostart_enabled` default in DEFAULT_SETTINGS -- all removed cleanly. Already-upgraded users have no residual risk: the save-site write is gone so the app will not re-create the registry entry; if you want to clean up the leftover in your local registry, run `reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v GBFR_CooldownIndicator /f` manually. Version +1 (V2008 -> V2009, title bar reports 20.09).
- **V2008 (20.08)**: **Fixed "Spikes (incl. tip beads) / Circle / Outer outline" card: every numeric control was non-functional with no live preview.** The widgets' valueChanged/stateChanged were wired correctly into `_emit_changed → get_settings()`, but the canvas size / spike parameters / roll / skill-canvas calculations had been sitting at the tail of `_migrate_pos_res()` -- a one-shot position-migration function that only runs once at startup. So changing spike length / root / width / waist / bead radius / bead position in the settings dialog triggered `_after_settings_changed → recalc_layout()` which actually did nothing -- the canvas never recomputed and nothing visually changed. This build moves that "per-frame layout" code back into `recalc_layout()` (right after `self.circle_r = ...`) and updates the docstrings; now any change to spike / circle / outline parameters instantly recomputes canvas + window sizes with a working live preview. **Tooltip added to "Title↔Circle spacing"** (`circle_pad_title`, the Title-bar color card pixel SpinBox for the vertical gap between the title-bar background row and the circle canvas -- default 0 = flush). Also `setMinimumWidth(110)` so the box is not squeezed in narrow columns. Version bumped +1 (V2007 → V2008, title bar reports 20.08).
- **V2007 (20.07)**: UX and startup improvements. (1) The **EXE sync list** input is now a multi-line box ~5 rows tall — you can paste multiple EXE paths separated by semicolons or newlines (previously a single-line box that scrolled). (2) Added a **"Launch at Windows startup"** toggle in Global → General (**on by default**); it writes/removes the indicator's entry in the HKCU "Run" registry key, so the app auto-runs when you log in (no admin needed; turn off to remove). Version +1 (V2006 -> V2007, title bar reports 20.07).
- **V2003 (20.03)**: **Hardcoded ExStatus offset** -- removed the ExStatus offset SpinBox from settings; offset is now fixed at 0xAF8 (2808) as ACTOR_EX_STATUS constant. **Fixed changelog Chinese leak in English mode** -- added CJK-detection guard (_safe_remote_changelog) that falls back to clean local embedded changelog when lang=en but remote text contains CJK characters. Both retranslate_ui and refresh_update_ui paths are now protected.
- **V2002 (20.02)**: Fixed the **title-bar first-row (icon button row) indent** being non-functional. When V2000 reverted to the V713 baseline, the render code was also reverted to a hardcoded `_margin = 6`, so the `titlebar_icon_indent` setting became a dead setting (changing it did nothing) — the first-row icons / version text stayed flush to the edge. This build re-reads the setting inside `_calc_icon_btn_rects()`: left-align → `lock_x = _margin + indent`, right-align → `lock_x = canvas_w - _margin - icon_w - indent` (the locked single-icon state is also indented), center unchanged. The Settings panel regains the "Icon row indent" SpinBox, wired into save / reset / live-signal. The i18n label (Icon row indent) already existed and needed no change. Version bumped +1 (V2001 → V2002, title bar reports 20.02).

- **V2001 (20.01)**: Added the **Damage Dealt Up** buff (in-game status id = 42) to the **enable/disable list of every character**, enabled by default and added to the display order. Sourced from GBFR_BuffMonitor's `buff_attrs.json` (offset `0x2A(42)`, single-layer buff, not character-exclusive = applies to all characters); cross-verified that the offset's decimal equals the indicator's `sid`. The definition is written into `i18n.json`'s `BUFF_PROFILES` (per-character buffs list), and a new `PLxxxx_N` `buff_enabled` / `buff_order` / `buff_mastery` key is added for every character in both the factory default (`DEFAULT_SETTINGS`) and `dist/overlay_settings.json`. Version bumped +1 (V2000 → V2001, title bar reports 20.01).

- **V2000 (20.00)**: Reverted and rebuilt on the **V713 baseline** — dropped the V714 offscreen supersampling (poor result) and the V720 forced yellow 6th/7th dodge flash (poor result); back to the V713 title-bar inset + status-line/icon-row indent baseline. **All 195 parameters** from `dist/overlay_settings.json` were baked into the exe's `DEFAULT_SETTINGS` as the factory default, so a fresh install (or deleting the external settings file) reproduces the user's tuned layout exactly — colors / opacities / spikes / flash / warning card / per-module positions & scales / dodge / buff enable·order·mastery gating / multi-buff differentiation / skill cooldown / hotkeys / updates. `update_download_url` is hardcoded to V2000 (avoiding the stale V680 address left in the old settings file). Version set to 2000 by explicit user request (V713 → V2000, title bar reports 20.00).

- **V720 (7.20)**: Dodge UI now forces a **yellow flash** on the **6th / 7th dodge** (the warning-roll state): the flash color is hardcoded to the warning card's middle yellow (`warning_fill_color`, default `#ffef00`), completely ignoring the `flash_color` setting. The red warning-card outline is still drawn on top so the "warning" meaning is preserved. Dodges 1-5 are unchanged (still use `flash_color`). Still based on **V713 baseline** (title bar inset + status-line/icon-row indent), no V706 forced sharpness change. Version set to 720 by explicit user request (V713 -> V720).

- **V713 (7.13)**: Added adjustable **Icon Row Indent** setting (default 16px): the title bar's **first line (icon button row)** now also indents based on the **Title Bar Alignment** direction — left-align indents the whole row from the left edge, right-align indents from the right edge, center mode unchanged. Adjust in real-time via the Settings panel SpinBox (0–64px). The V712 Status Line Indent is retained. Both indents are independently adjustable and fully trilingual (zh/zh_tw/en). Still based on **V705 baseline** (title bar inset), no V706 sharpness changes. Version bumped +1 (V712 → V713).

- **V712 (7.13)**: Added adjustable **Status Line Indent** setting (default 16px = icon button width): the title bar's second line (character name / skill status text) now indents automatically based on the **Title Bar Alignment** direction — left-align indents from the left edge, right-align indents from the right edge, center mode has no indent. Adjust in real-time via the Settings panel SpinBox (0–64px range), no restart needed. Full zh/zh_tw/en UI translations included. Still based on **V705 baseline** (title bar inset), no V706 sharpness changes. Version bumped +1 (V711 → V712).

- **V711 (7.13)**: Fixed a runtime issue where **all three overlay windows disappeared** — the root cause was `_migrate_pos_res()` fusing "position resolution-migration" with "canvas size computation" (core_canvas_w / dodge_icon_size / circle_r / spike params) in one method, guarded by `if pos_res_normalized: return`. Existing users' settings already carried `pos_res_normalized=True` (written by V704+), so after startup the canvas sizes were never computed and the three windows rendered nothing (appearing gone); "Reset All Windows" also failed because the canvas was never computed. Now: position migration runs once (guarded by `pos_res_normalized`), but canvas size computation runs every time. Still based on **V705 baseline** (title bar inset), no V706 sharpness changes. Version bumped +1 (V710 → V711).

- **V705 (7.05)**: Title bar **Left / Right** alignment polish — the icon row (Lock / Close / Settings / Minimize / Version) now leaves one extra lock-button width of empty space at the left / right screen edge, so icons no longer hug the very edge. The locked single-icon state is inset the same way. The second status-text row keeps the same edge inset as the icon row in Left / Right modes for a tidier look; Center is unchanged. Version bumped +1 (V704 → V705).

- **V704 (7.04)**: Fixed the **"scale with resolution"** feature only scaling size but not position. Module window positions now also migrate proportionally with screen resolution, so after switching between 1080p / 4K the overlay appears at the same relative spot instead of flying to a screen corner or off-screen. Added **live resolution monitoring** — changing the monitor resolution while the app is running now immediately re-lays-out window size and position with no restart. Old versions (≤V703) stored raw pixel positions; V704 normalizes them to the 1920 base width once on first launch, so existing users won't see a position jump after upgrading. Version bumped +1 (V703 → V704).

- **V703 (7.03)**: Adjusted the highest-mastery detection for the active character — the highest mastery tree no longer needs to be maxed to tier 3 (tier 1 / 2 / 3 are all correctly detected as the current mastery, used for buff gating and the title bar). If none of the three trees reaches tier 1 (e.g. the player deliberately only invested a few nodes and did not max tier 3), it now falls back to picking the tree with the most activated nodes, so a highest mastery is always detected instead of silently failing (which previously degraded to showing everything). Version bumped +1 (V702 → V703).

- **V702 (7.02)**: Fixed the **Title bar alignment** feature added in V701 — it now applies **live** (changing the dropdown immediately re-lays-out the title bar, no reopen needed) and the **Left / Right** order is corrected to **Lock → Close → Settings → Minimize → Version** (previously the icon order was hardcoded and ignored the setting). Center is unchanged. Version bumped +1 (V701 → V702).

- **V701 (7.01)**: New **"Title bar alignment"** setting (Core Detection → Title Bar): a dropdown offers **Left / Center / Right** (default **Left**). Center keeps the classic centered layout; Left/Right pack the icon row (minimize/settings/lock/exit) with the version number, and the second-line status text, to the corresponding edge. The dropdown label and options are fully trilingual (zh / zh_tw / en). Version bumped +1 (V700 → V701).
- **V700 (7.00)**: Reverted naming — rolled the product name back from **GBFR_BuffTimerIndicator_v2.0** to **GBFR_CooldownIndicator_V700**; the exe is now `GBFR_CooldownIndicator_V700.exe` (title bar reports v7.00) and the publisher tool (`GBFR_IndicatorPublisher.py`) is reverted to the old naming logic. Settings defaults (the 6 keys added at the v2.0 attempt) and all v6.24 / v3.60 features are retained. Also fixed a startup freeze caused by the EXE sync list: the old code launched the listed EXEs on the Qt main thread via `QProcess.startDetached`, which could block the main thread and freeze the UI after the first frame; it now launches them in a background daemon thread with `subprocess.Popen` (DETACHED_PROCESS), so the co-launch still works without freezing.

- **V2050（20.50）**：**新增【全 Buff 显示模块】（第四模块）**。以网格化轻量卡片列出当前主控角色可读到的全部 buff（与 Buff Monitor 同源，统一 gate 过滤后同时供给核心模块与本模块）。复用三大模块交集特质：独立显隐开关 / 独立屏幕位置 XY / 整体缩放 / 位置与缩放子页 / 元素级透明度（名称·层数·时间各字号+颜色；倒计时条与文字衬底各带独立不透明度）。每张卡片自上而下：buff 名 → 层数/最大层（单层显示 1/1）→ 剩余/持续秒 → 横向倒计时条；布局可调（行数 / 每行数量 / 行间距 / 卡片间距）。5 个可选过滤开关（默认全关=显示全部）：不显示核心区已展示的 / 不显示永续的 / 不显示角色专属的 / 不显示专精专属 / 不显示单层，分别对齐 Buff Monitor 的 单层 / 是否专属 / 是否专精buff 字段。数据源改用 `buff_attrs.json`（143 个游戏内 buff 的三语名与专属/专精/单层标记），已随打包分发；i18n 新增 31 个 UI 键（zh/zh_tw/en 三语齐全，三审计脚本 MISSING keys=0）。版本号 +10（V2040 → V2050，标题栏自报 20.50），schema 94 不变；已构建 `GBFR_CooldownIndicator_V2050.exe`。

- **V2039（20.39）**：**颜色选择对话框「自定义颜色」16 格永久保留**。之前 `QColorDialog.getColor()` 弹出系统 ColorPicker，调好色点「Add to Custom Colors」加到 16 格后，关闭软件再开就归零（Qt 的 `QColorDialog` 调色板只在进程内有效，Python 层无法定制）。**改法**：在 `pick_color()` 入口前从 `settings['custom_palette']` 把 16 个 hex 还原到 `QColorDialog.setCustomColor(i, QColor(hex))`，关闭后（无论 OK / Cancel）立即读 `QColorDialog.customColors()` 回写 `settings['custom_palette']` 并 `save_settings`——这样下次启动你辛辛苦苦调好的色还在。「恢复默认」按钮同步清空这 16 格并重置 Qt 全局。`DEFAULT_SETTINGS` 新增 `custom_palette: []` 字段。**已知未修**（按本版范围出外）：①「Add to Custom Colors 永远覆盖第一个空格子」是 Windows 系统 ColorPicker 内置行为，Python 不可改；②「点已有格子立刻把当前色覆盖上去」同理。要彻底灵活必须自己重写一个内部 ColorPicker（≈300 行），按用户之前选 B 方案仅做"关闭保留"。版本号 +1（V2038 → V2039，标题栏自报 20.39），schema 94 不变；i18n 无新增 / 删除 UI 字符串（仅改 `pick_color` 流程并新增一个 settings 字段）。

- **V2038（20.38）**：**修正**伊德龙人化能力模块技能名显示错误——V2037 错误地把龙人化技能名「复用」成 PL1900 人形态的圣迹再临 / 无缚之斩 / 赎罪 / 末日形态，但龙人化其实是独立编号 **PL2000**，技能本就不同（AB_PL2000_01~05：圣迹再临 / 天谴 / 永无止境 / 乐园之噬 / 神愿之力，区别于人形态 PL1900）。经 GBFR Logs `lang/zh-CN/abilities.json` 核实后确认：项目数据库原先没收录 PL2000，导致龙人化 actor 的 `+ABILITY_HASH_OFFSET` 所存的 PL2000 hash 在 `_ab_hash_map` 命中不到而显示空白。**改法**：把 PL2000 真实技能（hash→三语名）正式收录进 `GBFR_Character_Skills_Buffs.json`，按 hash 直接命中龙人化的真实技能名；并移除 V2037 误加的 `PL1900→PL1900` / `PL2000→PL1900` 技能借用（避免显示错误技能名）。核心 Buff 区 PL2000 仍与 PL1900 共用（那是 BUFF_PROFILES 的逻辑，不受影响）。版本号 +1（V2037 → V2038，标题栏自报 20.38），schema 94 不变；i18n 无新增 / 删除 UI 字符串（仅新增数据条目与数据通路修正）。

- **V2037（20.37）**：**真修复**——彻底修好伊德龙人化时技能模块（skill_cd 菱形）下方的能力名（圣迹再临 / 无缚之斩 / 赎罪 / 末日形态）不显示的 bug。V2036 猜错了根因（试图让 `read_skill_cooldowns` 从真身 actor 读 ability hash，但游戏在龙人化下未必更新真身的 `+ABILITY_HASH_OFFSET`——读到 0 或旧值——所以"还是没有"）。V2037 终于查到**真正的**根因并真修复：龙人化时 `pl_id` 由 `read_overlay_data` 经 `charid_hash` 解析得 **"PL1900"**（真身的角色 ID，因为 `CHAR_TYPE_TO_PL[0x20]="PL1900"`、**不是** `PL2000`）；龙人化 actor 的 `+ABILITY_HASH_OFFSET` 处的 4 个 hash 是龙人化**专属** hash（数据库没收），所以 `_ab_hash_map.get(h)` 必 miss；原 `PL_SKILL_FALLBACK` 只放了 `PL0100` / `PL2000`，**PL1900 不在兜底表里 → `_lookup_ability` 返回 None → `_skill_name=""` → `_draw_skill_cd_name` 直接 return → 4 个菱形下方全空**。**改法**：`PL_SKILL_FALLBACK` 加 `"PL1900":"PL1900"`，让龙人化 hash miss 时按 slot 借用真身 PL1900 的 `ab_01..ab_04`（圣迹再临 / 无缚之斩 / 赎罪 / 末日形态）。同时撤销 V2036 在 `read_skill_cooldowns` 内部加的 `_resolve_id_actor` 改动（猜猜错根因了，**还原为直接读 char_base**，避免把误导性代码留在那）。**PL1900 真身路径完全不受影响**——第一条分支命中直接返回同样的真身技能名，不走 fallback。版本号 +1（V2036 → V2037，标题栏自报 20.37），schema 94 不变；i18n 无新增 / 删除 key（V2037 仅改 hash 兜底表 `PL_SKILL_FALLBACK`，未改任何 UI 字符串）。

- **V2036（20.36）**：**修复 bug——伊德龙人化时技能模块（skill_cd 菱形）下方的能力名（紫银之力等）重新显示。** 根因：`read_skill_cooldowns` 直接从 `char_base + ABILITY_HASH_OFFSET` 读 4 个 ability hash，但龙人化时 `char_base` 是龙人化 actor（0x20），其 4 个 hash 跟真身 PL1900 不一致；`_lookup_ability(pl_id="PL1900", ab_hash=龙人hash)` 查不到技能名 → `_skill_name` 返回空 → `_draw_skill_cd_name` 直接 return → 4 个菱形图标下方的能力名整片消失。`read_overlay_data` 走 `_resolve_id_actor` 已修了 ExStatus 同源问题，`read_skill_cooldowns` 是最后漏网。**改法**：在 `read_skill_cooldowns` 内部加 `_resolve_id_actor`，ability hash 改从真身 actor 读；cd 倒计时仍读 `char_base`（龙人化 actor 自己的冷却状态，不动以免引入新风险）。普通形态 / 神威一体 / 其他角色完全不受影响。最小修复、逻辑清晰可回溯。版本号 +1（V2035 → V2036，标题栏自报 20.36），schema 94 不变；i18n 无新增 / 删除 key（V2036 只改后端数据通路、未改任何 UI 字符串）。

- **V2035（20.35）**：**三处清理 / 体验改进**——① **彻底删掉「显示启动画面」功能（启动条），不再以 splash 形式冷启动**：删 `class StartupSplash`（整个类约 80 行：`__init__ / _build_ui / _center / set_progress / finish` 五方法）、`DEFAULT_SETTINGS['show_startup_splash']`、设置面板「核心检测模块」里的复选框、五处触点（重置 / 创建 / 保存 / 读取 / i18n key）。`main()` 现在直接 `GBFROverlayQt(progress_cb=None)`——无 qlineargradient 启动卡片、无进度条、无「正在加载设置…」提示文字。`i18n.json` 删除「显示启动画面」三语 key；初次启动 → 进设置 → 任意语言切换都不会再看到这个标签。② **「EXE 同步列表」整行新增「启用 EXE 同步列表」勾选框（默认开启）**：放 EXE 同步卡片顶部，玩家可一键关掉整个 EXE 同步功能（不勾 = 永不启动列表里的任何 EXE、也永不枚举任何进程）。存到 `settings['enable_sync_exe_list']`（默认 `True`）；`_sync_exe_list_at_startup` 读到 `False` 直接 `return`，连后台 daemon 线程都不起，CPU = 0 零开销。`i18n.json` 新增「启用 EXE 同步列表」三语 key。③ **角色 Buff 顺位与专精门控三列（觉醒 / 真谛 / 秘义）列宽放大 1.5 倍**：列标题宽度 `86~100` → `129~150px`（`MasteryBuffGroup._build` 第 1805 行）；每行 checkbox 宽度 `86~100` → `129~150px`（`_make_item` 第 1931 行）。修之前「真谛：回复类能力强化」这类长专精名被截断显示不完整的问题，让列标题与每行勾选框布局严格对齐。版本号 +1（V2034 → V2035，标题栏自报 20.35），schema 94 不变；`GBFROverlayQt(progress_cb=...)` 参数保留以兼容未来若有进度显示需要。

- **V2034（20.34）**：**把「尖刺」和「装饰小球」的显示/隐藏彻底拆成两个互不耦合的独立开关。** 之前 V2033 用两个 hide 选项（「隐藏尖刺与装饰小球」+「仅隐藏上面的尖刺」）组合控制，语义绕、互相耦合，玩家不容易想清楚到底开了什么。本版改成最直白的：设置面板「尖刺与圆环」卡片下两个复选框——「显示尖刺（三角本体）」和「显示装饰小球（尖刺顶端圆点）」，各自独立勾选，四种组合任意切换：都勾（默认，全显示）/ 只勾装饰（只剩小球）/ 只勾尖刺（只剩三角）/ 都不勾（光秃秃圆环+倒计时+文字）。实现就是各自控制对应图层颜色不透明度为 0 或原值，不再有任何组合逻辑纠缠。旧存档自动迁移：原「隐藏尖刺与装饰小球」勾过 → 两开关都关；原「仅隐藏上面的尖刺」勾过 → 只关尖刺、保留装饰小球；都没勾 → 都开。**修复（2026-08-27 09:30 重发同一版本号）**：用户截图反馈 `_draw_spikes` 还有两个 bug——① buff 没有层数时仍凭空虚画 7 个装饰小球（实际上尖刺本体都没有）；② 只勾装饰小球不勾尖刺时，**尖刺和小球全都看不见**了。后者根因是 `painter.setOpacity(self._effective_opacity(key))` 在 `show_spikes=False` 时把全局 painter 透明度锁成 0，后面 `_draw_spike_bead` 沿用同一 painter 状态，小球被 0 透明度"吃"掉。重写 `_draw_spikes` 为单一清晰流程：`draw_count<=0` 直接 return（两层都不画，包括没尖刺就没小球）；主循环分 A/B/C 三个分支——A（画尖刺三角本体，用 spike_opacity 局部设置；闪光或正常球同时画）/ B（仅画装饰小球，显式 `painter.setOpacity(1.0)` 矫正被 0-opacity 污染的 painter 状态）/ C（两开关都关，啥都不画）。`_BUILD_NO` 不变（仍 2034），schema 94 不变。

- **V2033（20.33）**：**新增「仅隐藏上面的尖刺（保留装饰小球）」选项**（设置面板 → 尖刺模块区，紧跟在「隐藏尖刺与装饰小球」之后）。与「隐藏尖刺与装饰小球」的区别：后者连根部的装饰小球(bead)一起藏，前者只藏向外发散的尖刺三角本体、装饰小球仍画在原位置——满足「只要尖刺、不要外面那圈刺、但小球装饰保留」的视觉偏好。实现：`DEFAULT_SETTINGS` 加 `hide_spikes_only`；抽 `_draw_spike_bead` 子函数，在 `_draw_spikes` 内部 `hide_only` 分支仅画 bead；新增 `_hide_spikes()` helper 合并判定，统一接画布计算 / empty 分支 / `_render_buff_ui` 三处调用点；外描边的 bead 勾边在 only 模式下仍画。两者可同时勾选（UI 不做互斥强制），同时勾等价于「隐藏尖刺与装饰小球」。版本号 +1（V2032 → V2033，标题栏自报 20.33），schema 94 不变。

- **V2032（20.32）**：**撤销三次一脉相承的连锁假修复**（V2026/V2027/V2031 错用 `_any_active_buff_stacks()`）。玩家原意：只有 `active_buffs` 真为空（没有任何 buff）才考虑整圈隐；「已配置 buff 但游戏里 stacks 暂时=0」应仍正常显示圆环 + spike + 倒计时 + buff 名。AI 三次试图把同一个错误判定（`_any_active_buff_stacks()`）塞进三个判定点（spike_hidden / render_core 外层 if / 标题栏 buff 名段），每次都让它看起来"对"。本版把三处全部回退到 V2025 原始语义——只看 `active_buffs` 列表本身，不看 `stacks` 数值。「隐藏尖刺与装饰小球」选项语义保持原状（仅短路 spike/bead 绘制路径）；「无 buff 时隐藏尖刺圆模块」选项语义保持原状（仅在 active_buffs 为空时让整圈按 SPIKE_HIDDEN_KEYS 退 0% 隐形）。V2031「标题→圆间距允许负值」改动保留。版本号 +1（V2031 → V2032，标题栏自报 20.32），schema 94 不变。

- **V2031（20.31）**：**修复两个回归 bug（按用户截图反馈）**。(1) 设置面板「标题→圆间距」（`circle_pad_title`）QSpinBox 由 `setRange(0, 999)` 改成 `setRange(-999, 999)`，允许负值——需要让圆环画布上移、叠在标题栏之上时使用（`base_cy = TITLE_BAR_H + circle_pad_title + ...` 中的 `circle_pad_title` 本身就是活跃渲染参数，参与圆环 Y 位置计算，V2030 误判「是否还有用」被保留、但限制 >=0 没意义，下沉到 <0 即允许）。(2) 修 V2026 改 `_any_active_buff_stacks()` 后的连锁 bug——之前 `if self.active_buffs:` 直接进 buff 分支，会出现「active_buffs 列表非空、但所有 buff 的 stacks=0」时：圆环 / spike / 中心 icon / 倒计时弧等所有 SPIKE_HIDDEN_KEYS 按 `spike_hidden_opacity`（默认 0%）全部变成 0% 不透明（即看不见），但 `_draw_buff_name` 用的是 `buff_name_color`（不在 SPIKE_HIDDEN_KEYS）依然正常显示——出现「整圈 buff UI 看不见、只剩一个 buff 名标签飘在空中」的诡异残留。外层判定改为 `if self.active_buffs and self._any_active_buff_stacks():`——列表非空但 stacks 全 0 时直接并入 empty 分支（与列表空一致），由「无 buff 隐藏尖刺圆模块」选项统一控制「完全隐藏 / 显示空圆环」。三处一致：①spike 隐藏（V2026 起）②buff 模块渲染分支（本版）③标题栏 buff 名段（V2027 已用 `_any_active_buff_stacks()`）。版本号 +1（V2030 → V2031，标题栏自报 20.31），schema 94 不变。

- **V2030（20.30）**：**清理 3 处 UI 残留（按用户截图反馈）**。(1) 删除设置面板「更新检测版本地址」输入框下方那段长说明文字（V303 起的 url_hint QLabel）——输入框 placeholder 已足够提示，玩家不需要在这里再读一遍「为什么走 release CDN」。(2) 删除死函数 `_open_config_dir`（「打开配置 & 日志目录」）——AST 全量扫描证实零引用（除自身外）、托盘菜单从未 addAction 注册，玩家根本不知道这个入口在哪，索性彻底删干净。(3) 顺手清掉 i18n.json 里只被 `_open_config_dir` 引用的孤儿键「打开失败」（「设置打开失败」键 5878 行仍被设置对话框使用，保留）。「标题→圆间距」（`circle_pad_title`）控件保留——它是活跃渲染参数，参与 `base_cy = TITLE_BAR_H + circle_pad_title + circle_r + spike_top_pad` 的圆环画布 Y 位置计算，并非无用功能。版本号 +1（V2029 → V2030，标题栏自报 20.30），schema 94 不变。

- **V2026（20.26）**：**修复「无 buff 时隐藏尖刺圆模块」选项在用户把某个 buff 的三阶专精全勾、但游戏里该 buff 实际层数为 0 时不生效、圆环仍然显示的 bug**——狼奶奶反馈「勾了无BUFF隐藏圈圈尖刺，但是在没有BUFF的时候显示」。根因：`render_core` 的判定条件是 `len(active_buffs) == 0`，但一个 buff 即使被三阶专精全勾、永远在 active_buffs 列表里、只要游戏里 stacks=0，照样算「无 buff」——前者永远为 False → `spike_hidden=False` → 空圆环被 `_draw_circle` 以 `circle_color_normal` 满不透明度画出。本版新增 `_any_active_buff_stacks()` 辅助函数，判定改为 `not _any_active_buff_stacks()`（active_buffs 里所有 buff 的 stacks 都 ≤ 0 即视为无 buff），与玩家对「无 buff」的直觉（无任何 buff 实际激活）一致。版本号 +1（V2025 → V2026，标题栏自报 20.26），schema 94 不变。

- **V2025（20.25）**：**修复「随游戏前后台自动显隐」把点击 / 拖拽 / 缩放 overlay 自身模块误判成游戏到后台、一点模块就整窗消失、根本没法调模块大小/位置/缩放**——根因是 `_game_is_foreground()` 只认游戏 PID（`self.pid` 存的是游戏进程，不是工具自身），于是用户点/拖模块时前台变成工具自己的进程就被算成「后台」→ 隐藏。V2025 把工具自身进程（`os.getpid()`）也并入「前台」集合（点/拖模块时保持可见），并新增拖拽/缩放进行中的 `_interacting` 锁，焦点同步直接跳过、绝不隐藏。真正的「后台」只剩前台是游戏/工具之外的其它程序（桌面/浏览器/其它软件）。版本号 +1（V2024 → V2025，标题栏自报 20.25），schema 94 不变。

- **V2024（20.24）**：**修复 Windows 区域设为「香港（繁体中文）」时整个 overlay 中文渲染成 □□ 方框**——有用户反馈「区域换香港就出方框，换回大陆就好了」。原因是 Qt 在 Windows 上不读系统的「亚洲字符字体回退」表，全项目 21 处 `QFont` 都 hardcode 了 `"Segoe UI"`，Segoe UI 没有中文字形，Qt 直接退到缺字矩形显示 □。本版在 `main()` 启动时扫 `QFontDatabase.families()`，按优先级挑系统已装 CJK 字体（Microsoft YaHei → JhengHei → PingFang SC → SimHei → Malgun Gothic → Yu Gothic → Meiryo → Source Han Sans CN/TC → Noto Sans CJK），对 Segoe UI 调 `QFont.insertSubstitution("Segoe UI", cjk_family)` 全局注册字形替代——所有 `QFont("Segoe UI", ...)` 命中缺字时由该 CJK 字体兜底，零调用点改动；任何 Windows 系统（Win7 以上，无论简/繁/英区）只要装了一种 CJK 字体就自动生效。版本号 +1（V2023 → V2024，标题栏自报 20.24），schema 94 不变。

- **V2023（20.23）**：**砍掉 V2022 的「600ms 防抖」**——V2022 为了快速 Alt-Tab 来回时不让用户看到一闪而过的窗口加了 600ms 等待，实战发现这一等待让「游戏切回前台时 overlay 没及时弹回」成为常态。V2023 回到 V2021 的边沿节奏：`prev != decision` 的瞬间就 `_show_all_windows()` / `_hide_all_windows()`（焦点定时器 250ms 仍保留）。**非战斗状态也跟随前后台显隐**——V2013 时代把「窗口缩为仅标题栏」的非战斗状态当成 `auto_focus_minimize` 的死角直接 early return，于是非战斗（地图界面、任务接取区、NPC 旁）alt-tab 完全没反应。本版删掉那行 return，`hide()` 一次清空整窗（含标题栏），回前台时由 `_show_all_windows()` 一次性完整弹出，下一拍 tick 再按 `_ooc_content_mult` 恢复缩为标题栏的视觉状态。版本号 +1（V2022 → V2023，标题栏自报 20.23），schema 94 不变。

- **V2013（20.13）**：- **重写「随游戏前后台自动显隐」逻辑，修复 6 个长期 bug**：(1) 尊重手动隐藏——按呼出/隐藏热键或双击托盘隐藏后，不再被自动同步在约 50ms 后强行弹回；(2) 游戏未运行时不再自动最小化，可以先开工具调好设置再启动游戏；(3) Steam/Discord 覆盖层与伴侣进程弹窗不再被误判为「游戏切到后台」而自动最小化；(4) 前景窗口轮询改为独立的低频定时器（250ms），不再挂在每 50ms 的扫描帧里，去掉无谓的逐帧 Win32 调用；(5) 设置等模态对话框打开时正确暂停同步；(6) 手动呼出后设短暂豁免期，避免「手动显示」与「自动最小化」竞速。- 版本号 +1（V2012 → V2013，标题栏自报 20.13），schema 93 → 94。

- **V2012（20.12）**：- **修复设置弹窗深色主题下的黑色字看不清（QComboBox 弹出项 + EXE 同步文本框）**：原全局 setStyleSheet 只给 QComboBox 的「已选中行」设了 `color:#fff`，弹出项 `QComboBox QAbstractItemView` 走的是 Qt 的 OS 默认主题（浅色背景 + 黑色字），所以点开语言下拉看到的 `zh / zh_tw / en` 是黑字一片；EXE 同步列表的 `QPlainTextEdit` 根本不在 setStyleSheet 覆盖范围里，Qt 默认给的就是黑字。已在全局样式表补齐：QPlainTextEdit 文字 `#dce8f8`（与 QLabel 一致）、QComboBox 弹出视图背景 `#242c40` / 文字 `#ffffff` / 选中态 `#3a4860`，展开后字体看得清。 - **语言下拉菜单硬编码为「简体中文 / 繁体中文（繁体的） / English」三项**：之前下拉里直接是 `zh / zh_tw / en` 这三字语言代码，像没翻译的占位符；现在改为三行固定文字 + `addItem(text, userData)` 把 `zh / zh_tw / en` 存在 userData 里，运行时改读 `currentData()`。**任何语言模式下这三项都保持原样不翻译**（retranslate_ui 走 findChildren(QLabel/QCheckBox/QPushButton/QLineEdit)，不会动 QComboBox 内部 item）。DEFAULT_SETTINGS 默认 `language` 改为 `"zh"`，新装用户首启即简体中文。 - 版本号 +1（V2011 → V2012，标题栏自报 20.12），schema 92 → 93。
- **V2011（20.11）**：- **将 dist 设置文件全部烘焙进软件内置 DEFAULT_SETTINGS（出厂默认即等于你当前调好的配置）**：用 `dist/overlay_settings.json` 的每一项实际值覆盖 `DEFAULT_SETTINGS`（196 项，逐项核对零不一致）；刻意排除已删除的开机自启键 `autostart_enabled`，并在 `load_settings()` 中主动剔除旧存档残留。 - 版本号 +1（V2010 → V2011，标题栏自报 20.11），schema 91 → 92。
- **V2010（20.10）**：- **新增「显示启动画面」开关（全局 → 常规，默认开启）**：就是开这个软件时那个读条启动画面。开启 = 维持现状（启动显示进度条）；关闭 = 启动时不显示该启动画面，直接进主界面。去掉之前误加的「开机自动启动」后，这里把「启动条」真正做成可开关。 - **修复内部表盘差异化遗漏（仅层数 / 无倒计时）**：当一个表盘内部只有层数数字（没有倒计时弧）时，可见的彩色元素只剩「层数数字」+「它的勾边」。之前层数数字默认白色（零饱和度），而 rotate_hue 对白色是空操作 → 数字永远白色、不参与差异化，只有勾边变色，破坏「同色系」一致性。现改为：开启内部差异化时，若数字颜色旋转无效，则改用「同色系勾边」的色相生成亮色填充，让数字也参与差异化，且与勾边同色系可辨。 - **i18n 补漏（exe 同步 + 新功能）**：补齐「EXE 同步列表」标签 / 占位符 / 提示 tooltip、「标题↔圆间距」tooltip、以及新增「显示启动画面」开关标签的英文与繁中翻译（此前这些串未进翻译表，英文 / 繁中模式下显示中文）。检测更新状态机的几个状态文本此前已覆盖，本次确认无误。 - 版本号 +1（V2009 → V2010，标题栏自报 20.10）。
- **V2009（20.09）**：**删除「开机自动启动（登录 Windows 后自动运行本程序）」复选框**——V2007 引入的 HKCU Run 注册表写入/移除功能是被误加的：你说的其实是「启动条」（开这个软件时的进度条 / 启动画面），与 Windows 开机自启完全不同。本版把设置面板「全局 → 常规」里的 `autostart_chk` 复选框、`_apply_autostart()` 函数、启动时和保存时两处注册表写入逻辑、DEFAULT_SETTINGS 里的 `autostart_enabled` 默认值，全部删除干净。已升级老用户无残留风险：保存逻辑已删，软件不会再写注册表；想清理本机残留 HKCU 项可手动 `reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v GBFR_CooldownIndicator /f`。版本号 +1（V2008 → V2009，标题栏自报 20.09）。
- **V2008（20.08）**：**修复「尖刺（含顶端圆点）/ 圆环 / 外描边」卡片所有数值选项完全失效 + 无实时反馈**。这些控件的 valueChanged/stateChanged 都正确接到 `_emit_changed → get_settings()`，但画布尺寸 / 尖刺参数 / 翻滚 / 技能 画布 这套计算被错误地放在 `_migrate_pos_res()`（一次性位置迁移函数）末尾，*只在启动时跑一次*。设置面板里改尖刺长度 / 根部位置 / 宽度 / 腰位置 / 圆点半径 / 圆点位置 → `_after_settings_changed → recalc_layout()` → 啥都没刷新，外观毫无变化。本版把这段「每帧布局」真正该跑的代码整体搬回 `recalc_layout()`（紧接 `self.circle_r = ...` 之后），函数注释同步更新；现在改尖刺 / 圆环 / 外描边任意一项，画布与窗口尺寸立即按新值重算，实时反馈可用。**「标题↔圆间距」加 tooltip 解释**（`circle_pad_title`，标题栏色卡片里的像素 SpinBox，标题栏底色行与圆环画布之间的垂直间距，默认 0 表示贴在一起），并 `setMinimumWidth(110)` 防窄列被挤。版本号 +1（V2007 → V2008，标题栏自报 20.08）。
- **V2007（20.07）**：体验与启动改进。(1) **EXE 同步列表**输入框改为约 5 行高的多行框——可直接粘贴多个 exe 路径，用分号或换行分隔（此前是单行滚动框）。(2) 在「全局 → 常规」新增**「开机自动启动」**开关（**默认开启**），通过 HKCU「运行」注册表项写入/移除本程序启动项，登录 Windows 后自动运行（无需管理员；关闭即移除）。版本号 +1（V2006 -> V2007，标题栏自报 20.07）。
- **V2003（20.03）**：**写死 ExStatus 偏移**——移除设置面板里的 ExStatus 偏移 SpinBox，偏移值固定为 0xAF8（2808），唯一数据源是 ACTOR_EX_STATUS 常量（原控件本身是摆设，read_exstatus_buffs 从未读取该设置）。**修复英文模式下 Changelog 泄露中文**——新增 CJK 检测防护函数 _safe_remote_changelog，当 lang=en 但远端 changelog 含 CJK 字符时自动降级为本地内嵌的干净英文日志。retranslate_ui 和 refresh_update_ui 两条路径均已防护。
- **V2002（20.02）**：修复**标题栏第一行（图标按钮行）缩进失效**。V2000 回退到 V713 基线时，渲染代码被一并回退成写死 `_margin = 6`，导致 `titlebar_icon_indent` 设置成了「死设置」（改了也没用）——第一行图标 / 版本号永远贴边。本版在 `_calc_icon_btn_rects()` 重新读取该设置：靠左时 `lock_x = _margin + 缩进`、靠右时 `lock_x = 画布宽 - _margin - 图标宽 - 缩进`（锁定态单图标同样内缩），居中不变。设置面板补回「图标行缩进」SpinBox 并接入保存 / 重置 / 实时信号链路。i18n 标签（图标行缩进）此前已存在，本轮无需改动。版本号 +1（V2001 → V2002，标题栏自报 20.02）。

- **V2001（20.01）**：在「buff 启用 / 禁用」列表里，为【每个角色】追加**造成伤害UP**（游戏内 status id = 42）buff，默认启用并加入显示顺位。数据源来自 GBFR_BuffMonitor 项目的 `buff_attrs.json`（偏移 `0x2A(42)`，单层 buff，是否专属=false 即全角色通用）；已交叉验证该偏移十进制即指示器的 `sid`。buff 定义写入 `i18n.json` 的 `BUFF_PROFILES`（每角色 buffs 列表），并在出厂默认（`DEFAULT_SETTINGS`）与 `dist/overlay_settings.json` 中为每角色新增 `PLxxxx_N` 的 `buff_enabled` / `buff_order` / `buff_mastery` 键。版本号 +1（V2000 → V2001，标题栏自报 20.01）。

- **V2000（20.00）**：基于 **V713 基线**回退重建——丢弃 V714 离屏超采样（效果差）与 V720 第 6/7 次翻滚强制黄色闪光（效果不好）两次改动，回到 V713 标题栏内缩 + 状态行/图标行缩进基线。**把 `dist/overlay_settings.json` 里的【全部 195 项参数】逐条烘焙进 exe 的 `DEFAULT_SETTINGS` 作为出厂默认**：删掉外部设置文件、全新安装也能原样复现用户调好的布局（颜色/透明度/尖刺/闪光/警告牌/各模块位置与缩放/翻滚/buff 启用·顺位·专精门控/多 buff 差异化/技能冷却/热键/更新）。`update_download_url` 写死指向 V2000（避免沿用旧文件里的 V680 过期地址）。版本号按用户指定跳至 2000（V713 → V2000，标题栏自报 20.00）。

- **V720 (7.20)**：翻滚 UI 在第 6、7 次翻滚（警告翻滚状态）时**强制为黄色闪光**：闪光颜色写死为警告牌的中间黄色（`warning_fill_color`，默认 `#ffef00`），完全不受 `flash_color` 设置影响。上层仍绘制红色警告牌轮廓，保留「警告」语义。第 1~5 次翻滚不变（仍用 `flash_color`）。仍基于 **V713 基线**（标题栏内缩 + 状态行/图标行缩进），不含 V706 强制清晰度改动。版本号按用户指定跳至 720（V713 -> V720）。

- **V713 (7.13)**：新增**「图标行缩进」**可调设置（默认 16px）：标题栏**第一行（图标按钮行）**现在也根据**「标题栏对齐」**方向缩进——靠左时整体左内缩、靠右时整体右内缩、居中不变。通过设置面板 SpinBox 实时调节（0~64px）。V712 的「状态行缩进」保留。两项缩进独立可调，均含 zh / zh_tw / en 三语翻译。仍基于 **V705 基线**（标题栏内缩），不含 V706 清晰度改动。版本号 +1（V712 → V713）。

- **V712 (7.13)**：新增**「状态行缩进」**可调设置（默认 16px = 图标按钮宽度）：标题栏第二行（角色名 / 技能状态文字）现在会根据**「标题栏对齐」**方向自动缩进——靠左时左边缩进、靠右时右边缩进、居中时不缩进。缩进量通过设置面板 SpinBox 实时调节（0~64px），无需重启。同步提供 zh / zh_tw / en 三语界面翻译。仍基于 **V705 基线**（标题栏内缩），不含 V706 清晰度改动。版本号 +1（V711 → V712）。

- **V711 (7.13)**：修复**「三个悬浮窗全不见了」**的运行期问题——根因是 `_migrate_pos_res()` 把「位置分辨率迁移」与「画布尺寸计算（core_canvas_w / dodge_icon_size / circle_r / 尖刺参数等）」写在同一个方法里，却用 `if pos_res_normalized: return` 整体早退。存量用户的 settings 已带 `pos_res_normalized=True`（之前 V704+ 写入），导致启动后画布尺寸从未计算，三个窗口渲染不出内容、看起来像消失；「重置窗口」也因画布未算而无效。现改为：位置迁移仅做一次（pos_res_normalized 守卫），画布尺寸计算每次都执行。仍基于 **V705 基线**（标题栏内缩），不含 V706 清晰度改动。版本号 +1（V710 → V711）。

- **V705 (7.05)**：标题栏**「靠左 / 靠右」**对齐优化——图标行（锁定 / 关闭 / 设置 / 最小化 / 版本信息）在贴左、贴右的边缘各额外空出一个锁按钮的宽度，图标不再紧紧顶住屏幕最左 / 最右边；锁定态单图标同样内缩。第二行状态文字在左 / 右模式下与图标行保持一致的边缘内缩，整体更整齐。居中模式不变。版本号 +1（V704 → V705）。

- **V704 (7.04)**：修复**「随分辨率放大」**只缩放大小、不缩放位置的问题——各模块窗口的位置现在也会随屏幕分辨率等比迁移，切换 1080p / 4K 后悬浮窗会出现在相对相同的位置（不再飞到画面角落或跑出屏幕）。新增**「运行时分辨率实时监听」**：程序运行中直接调节显示器分辨率，窗口大小与位置会立即自动重排，无需重启。旧版本(≤V703)保存的是「当前分辨率原始像素」位置，V704 首次启动会一次性归一化到基准宽度(1920)，存量用户升级后位置不会跳变。版本号 +1（V703 → V704）。

- **V703 (7.03)**：调整主控角色「最高专精」判定逻辑——最高专精不再要求该树必须满到 3 阶（1 阶 / 2 阶 / 3 阶 都会被正常判定为当前专精，用于 buff 门控与标题栏显示）；若三系都未达 1 阶（角色特地只点了几颗、不点满 3 阶），则退化为按「实际已点节点总数」最多的那棵树挑出最高的专精，保证总能判定，不再因未点满而整体失效（降级为全显示）。版本号 +1（V702 → V703）。

- **V702 (7.02)**：修正 V701 新增的**「标题栏对齐」**功能——现已**实时生效**（更改下拉菜单立即重排标题栏，无需重开），并修正**靠左 / 靠右**的排列顺序为 **锁定 → 关闭 → 设置 → 最小化 → 版本信息**（此前图标顺序被写死、未跟随设置）。居中保持不变。版本号 +1（V701 → V702）。

- **V701 (7.01)**：新增**「标题栏对齐」**设置（核心检测 → 标题栏）：下拉菜单可选**靠左 / 居中 / 靠右**，默认**靠左**。居中保持经典居中布局；靠左/靠右把图标行（最小化/设置/锁定/退出）与版本号、以及第二行状态文字整体贴到对应边缘。下拉标签与选项均三语（简 / 繁 / 英）适配。版本号 +1（V700 → V701）。
- **V700 (7.00)**：回退更名——产品名由 **GBFR_BuffTimerIndicator_v2.0** 回退为 **GBFR_CooldownIndicator_V700**；exe 现为 `GBFR_CooldownIndicator_V700.exe`（标题栏自报 v7.00），发布工具（`GBFR_IndicatorPublisher.py`）一并还原为旧命名逻辑。此前为 v2.0 尝试补齐的 6 个默认值、以及 v6.24 / v3.60 的全部功能均保留。另修复了「EXE 同步列表」在启动时导致界面永久卡死的问题：原实现在 Qt 主线程用 `QProcess.startDetached` 同步启动列表中的 exe，有概率阻塞主线程、在读出第一帧后卡死；现改为在后台 daemon 线程用 `subprocess.Popen`（DETACHED_PROCESS）启动，共同启动行为保留且不再卡。

- **V624 (6.24)**: New **"EXE sync list"** (Settings → Global → General): enter absolute paths of multiple EXEs separated by semicolons. It takes effect only once at startup — each listed EXE is checked, and launched if not running or skipped if already running (never killed, never monitored), so your common side tools launch together with the indicator. Matched by exact absolute path (won't touch a same-named program elsewhere). Label / placeholder / tooltip are all trilingual (zh / zh_tw / en).
- **V2005 (20.05)**: Fixed the EXE sync **"Start in" directory actually being applied**. The previous build passed the working directory via `os.startfile(path, cwd=...)`, but on Windows `ShellExecute` does not reliably set the child process's current directory for an `.exe`, so synced programs (e.g. GBFR Logs) launched in the indicator's own directory instead of their own. Now the launcher uses `subprocess.Popen([path], cwd=...)` (CreateProcess `lpCurrentDirectory`), which guarantees the child runs with the specified start-in directory -- exactly like double-clicking a .lnk. Also moved the fallback so that omitting `||working_directory` always defaults to the EXE's own directory (previously the fallback only applied when `||` was present, so old saved settings without `||` got no working directory at all).
- **V2007 (20.07)**: UX and startup improvements. (1) The **EXE sync list** input is now a multi-line box ~5 rows tall — you can paste multiple EXE paths separated by semicolons or newlines (previously a single-line box that scrolled). (2) Added a **"Launch at Windows startup"** toggle in Global → General (**on by default**); it writes/removes the indicator's entry in the HKCU "Run" registry key, so the app auto-runs when you log in (no admin needed; turn off to remove). Version +1 (V2006 -> V2007, title bar reports 20.07).
- **V2006 (20.06)**: Reverted the EXE sync launcher to `os.startfile` (ShellExecute). V2005 switched to `subprocess.Popen`, but `CreateProcess` cannot trigger UAC elevation -- when a synced program needs elevation (e.g. GBFR Logs), it failed with WinError 740 and never launched. `os.startfile` (ShellExecute) both elevates correctly and sets the start-in directory via `lpDirectory`, exactly like double-clicking a .lnk. The V2005 working-directory fallback fix (omitting `||working_directory` defaults to the EXE's own directory) is kept. (Note: the V2005 entry's claim that "os.startfile's cwd is unreliable" was a misdiagnosis -- the real cause was subprocess being unable to elevate. This build reverts and corrects it.)
- **V2004 (20.04)**: Added **"Start in" (working directory)** support to the EXE sync list. Each entry may append `||working_directory` to set its start-in directory (equivalent to a .lnk's "Start in" field; omit to default to the EXE's own directory). The factory default now sets GBFR Logs' start-in to `C:\Program Files\GBFR Logs\`.
- **V2005 (20.05)**：修复 EXE 同步**「起始位置」真正生效**的问题。上一版用 `os.startfile(path, cwd=...)` 传工作目录，但 Windows 对 `.exe` 走 `ShellExecute` 时并不保证把 `cwd` 设成子进程的工作目录，导致同步拉起的程序（如 GBFR Logs）跑到了指示器自己的目录下，而非 exe 同目录。现改用 `subprocess.Popen([path], cwd=...)`（CreateProcess 的 `lpCurrentDirectory`），保证子进程以指定起始位置运行——与双击 .lnk 完全一致。同时把「省略 `||工作目录` 时默认用 exe 同目录」的兜底逻辑移到 `if` 判断之外，此前该兜底只在写了 `||` 时才生效，导致你那种没写 `||` 的旧配置完全拿不到工作目录。
- **V2007 (20.07)**：体验与启动改进。(1) **EXE 同步列表**输入框改为约 5 行高的多行框——可直接粘贴多个 exe 路径，用分号或换行分隔（此前是单行滚动框）。(2) 在「全局 → 常规」新增**「开机自动启动」**开关（**默认开启**），通过 HKCU「运行」注册表项写入/移除本程序启动项，登录 Windows 后自动运行（无需管理员；关闭即移除）。版本号 +1（V2006 -> V2007，标题栏自报 20.07）。
- **V2006 (20.06)**：回退 EXE 同步启动方式至 `os.startfile`（ShellExecute）。V2005 改用 `subprocess.Popen`，但 `CreateProcess` 不会弹 UAC 提权——需要提权的同步程序（如 GBFR Logs）会直接失败（WinError 740）而启动不了。恢复 `os.startfile` 后既能正常提权，又通过 `lpDirectory` 正确设置起始位置（工作目录），与双击 .lnk 完全一致。V2005 引入的「省略 `||工作目录` 时兜底到 exe 同目录」修复保留。（注：V2005 条目所述「os.startfile 的 cwd 不可靠」为误判，真实根因是 subprocess 无法提权，本条已回退修正。）
- **V2004 (20.04)**：为「EXE 同步列表」增加**「起始位置（工作目录）」**支持：每条可附加 `||工作目录` 指定同步启动时的起始目录（等同 .lnk 的「起始位置」字段，省略则固定在 exe 同目录）；出厂默认值已为 GBFR Logs 配上 `C:\Program Files\GBFR Logs\`。
- **V624 (6.24)**：新增**「EXE 同步列表」**（设置 → 全局 → 常规）：填入多个 exe 的绝对路径，用分号分隔。仅在程序启动时生效一次——逐个检测，未运行则启动、已运行则跳过（绝不杀进程、不监视），可把常用辅助工具随指示器一起启动。按绝对路径精确匹配（不会误伤同名其他路径的程序）。标签 / 占位符 / 提示均已三语（简 / 繁 / 英）适配。

- **V623 (6.23)**: Fixed the in-app changelog showing Chinese text when the UI language was set to English or Traditional Chinese. The `version.json` `changelog` field is now a trilingual dict (`zh` / `zh_tw` / `en`), and the about/update panel selects the correct language automatically. The publisher (`GBFR_IndicatorPublisher.py`) now writes the three-language changelog as well, so future releases won't revert it to a single-language string.
- **V623 (6.23)**：修复「更新日志」在英文 / 繁中界面下仍显示中文的问题。`version.json` 的 `changelog` 字段改为三语 dict（`zh` / `zh_tw` / `en`），关于/更新页按所选语言自动放出正确内容。发布器（`GBFR_IndicatorPublisher.py`）同步改为写入三语更新日志，避免后续发布会把三语打回单语字符串。

- **V275**: UI adjustment. The "Dodge Warning Card (6th/7th)" settings card was moved into the **Dodge module** tab: in V274 it lived under "Core Detection → Flash Application", away from the dodge icon; now it sits inside "Dodge module → Dodge icon" sub-tab, right after the dodge icon card, in the same module tab as the dodge icon and position/scale. All related label text was also translated to English / Traditional Chinese (icon size / outline width / outer edge color / inner fill color / check edge width / check edge glow / dodge flash · white solid check edge).
- **V275**：UI 调整。**翻滚警告牌（第6/7次）设置卡片移入「翻滚模块」标签页**：V274 该卡片放在「核心检测模块→闪光应用模块」下，与翻滚图标不在同一处；现移到「翻滚模块→翻滚图标」子标签内、紧跟翻滚图标卡片之后，与翻滚图标、位置缩放同属一个模块标签页。同步补充该卡片涉及的全部标签文案的英文/繁体翻译（图标大小/外边粗细/外部边色/内部填充色/勾边粗细/勾边辉光/翻滚闪光·白色实心勾边）。

- **V274**: Four fixes per feedback. (1) **The spiked circle's outer ring no longer flashes**: `_render_buff_ui()` now always passes `flash_scale=1.0` to `_draw_indicator_outer_outline()`, so the outer ring outline no longer scales/moves with the flash (the middle layer stays fixed). (2) **Spiked flash applies only to the "newly added" spikes**: `_draw_spikes()` now judges per-Buff using each Buff's own flash record (the record's `from` = previous layer count); only spikes with `index >= from` (plus decoration circles and outlines) scale up from the center and flash white, the rest stay put; adding multiple at once flashes all the new ones. Added `_buff_key()` to generate Buff keys consistent with the memory update loop. (3) **The 6th/7th dodge warning card is now fully adjustable**: new keys `warning_size_scale` (0.30~1.00), `warning_outline_width` (0.03~0.50), `warning_outline_color`, `warning_fill_color`; a "Dodge Warning (6th/7th)" card was added under the Flash Application module; the red border is still directly controlled by dual-size triangles (not clamped by the outline-width cap). (4) **The dodge white-flash solid block is fully opaque**: `_draw_dodge_icon_at()`'s solid white fill opacity is fixed at 1.0 (completely opaque white block), only vanishing at the instant the flash ends; the outer outline glow still decays with progress.
- **V274**：四处按反馈修正。(1) **尖刺圆外圈圆环不再参与闪光**：`_render_buff_ui()` 调用 `_draw_indicator_outer_outline()` 固定传 `flash_scale=1.0`，圆环外勾边不再随闪光缩放/移动（中间层始终不动）。(2) **尖刺闪光只作用于「新增」的那一支**：`_draw_spikes()` 改为按每个 buff 自身的闪光记录（记录里的 `from`=上一次层数）独立判定，仅 `index >= from` 的尖刺（及装饰圆、勾边）以圆心为中心放大并白色闪光，其余尖刺保持不动；一次增加多支则新增的几支都闪。新增 `_buff_key()` 统一生成与内存更新循环一致的 buff 键。(3) **翻滚警告牌（第6/7次）四项全部可调**：新增设置键 `warning_size_scale`（大小 0.30~1.00）、`warning_outline_width`（外边粗细比例 0.03~0.50）、`warning_outline_color`（外边色）、`warning_fill_color`（内填色），设置面板「闪光应用模块」下新增「翻滚警告牌（第6/7次）」卡片；红边仍用双尺寸三角直接控制（不受描边宽度上限钳制）。(4) **翻滚白闪实心块完全不透明**：`_draw_dodge_icon_at()` 实心白色填充不透明度固定 1.0（完全不透明白块），仅闪光结束瞬间整体消失；外部勾边辉光仍随 progress 衰减。

- **V273**: Three more fixes per feedback. (1) **The outermost ring outline now also scales with the flash**: V272 feedback said the spikes scaled but the outermost ring outline didn't move; `_draw_indicator_outer_outline()` gained a `flash_scale` parameter, and `_render_buff_ui()` passes `group_flash_scale` through, so the ring outline and spike outer outline use the same `flash_scale` and enlarge together from the center while the middle circle / timer / layer number stay fixed. (2) **The dodge white-flash solid fill is more solid**: `_draw_dodge_icon_at()` splits "solid fill" and "outline glow" opacity — the solid white fill has a 0.82 floor (nearly full white throughout), while the outline glow decays naturally with progress, more solid than V272's 0.5 floor. (3) **The 6th/7th warning card shrinks 32% + red border doubles**: the warning triangle scales by 0.68 centered; the red border thickness uses two different-size triangles directly (red triangle insets `bt = max(8, sz*0.24)` per side vs the yellow, ~2× the old value), with the yellow inner fill receding with `bt` — the old `W_big-W_small` formula was clamped by `corner_r*2` so doubling would eat the yellow interior, hence the size method.
- **V273**：三处按反馈继续修正。(1) **最外圈圆环描边也随闪光放大**：V272 反馈尖刺放大了但最外圈圆环勾边没动；`_draw_indicator_outer_outline()` 新增 `flash_scale` 参数，`_render_buff_ui()` 把 `group_flash_scale` 透传进去，圆环描边与尖刺外勾边用同一 `flash_scale` 以圆心为中心同步放大，中间圆/计时器/层数字仍不动。(2) **翻滚白闪实心填充更实**：`_draw_dodge_icon_at()` 将「实心填充」与「勾边辉光」拆开设不透明度——实心白色填充最低保底 0.82（几乎全程接近全白），勾边辉光随 progress 自然衰减，比 V272 的 0.5 保底更实。(3) **第 6/7 次警告牌缩小 32% + 红色边框翻倍**：警示三角整体按 0.68 倍居中；红边粗度改用「两个不同尺寸三角」直接控制（红三角比黄三角每边多 inset `bt = max(8, sz*0.24)`，约旧值 2 倍），黄色内填随 `bt` 内收。

- **V272**: Two fixes per feedback. (1) **Dodge white-flash changed to "solid fill + outline" scaling together**: the old white flash was only a hollow outline ring; now at the flash instant it draws both a "white solid fill" (new `_get_dodge_solid_img_white()`, fills white by PNG alpha threshold) and a "white outline", both anchored at the icon center, scaling with `flash_scale` and flashing with `flash_progress`, hidden normally. The setting toggle text changed to "Dodge flash · white solid check edge". (2) **The 6th/7th dodge warning card returns to "red border + yellow fill"**: drawn as two layered rounded triangles — a red layer (`#e53935`, larger rounded triangle) painted first as the full red, then a yellow layer (`#ffef00`, smaller rounded triangle) painted on top covering only the interior, revealing a red rounded border (the triangle stroke band needs `.united(sharp)` to fill the hole, otherwise yellow only draws a ring), no exclamation mark.
- **V272**：两处按反馈修正。(1) **翻滚白闪改为「实心填充 + 勾边」整体放大**：旧版白闪只是空心勾边环；现闪光瞬间同时绘制「白色实心填充（新增 `_get_dodge_solid_img_white()`，按 PNG alpha 阈值填白）」+「白色勾边轮廓」，两者都以图标中心为锚点随 `flash_scale` 放大、随 `flash_progress` 衰减闪一下，平时不显示。设置开关文案改为「翻滚闪光·白色实心勾边」。(2) **翻滚第 6/7 次警告牌回归「红边黄底」**：改为两层圆角三角叠画——红色层（`#e53935`，大圆角三角）先画整片红、黄色层（`#ffef00`，小圆角三角）后画仅覆盖内部，露出红色圆角边框，无感叹号。

- **V271**: Fixed three flash / warning behaviors. (1) **Spiked-circle flash now affects only spikes + decoration balls**: the old version applied the module-level flash scale to the entire buff element (including the middle ring / countdown / number), enlarging the whole core UI; now `_render_buff_ui` no longer scales the whole thing — the middle layer is drawn fixed, and the flash scale + white overlay only expand from the center on the spikes (+ top decoration balls) in `_draw_spikes`, decaying with progress. (2) **Dodge white outline becomes a flash shape**: removed the persistent outline; the white outline appears only at the instant the dodge count increases, scales up and flashes once (new `_get_dodge_outline_img_white()`, always white), controlled by the "Dodge flash · white outline" toggle. (3) **The 6th/7th dodge warning becomes a pure yellow rounded triangle**, removing the red border and exclamation mark.
- **V271**：修正三处闪光/警告牌行为。(1) **尖刺圆闪光只作用于尖刺+装饰小球**：旧版把模块级闪光缩放作用到整个 buff 元素（含中间圆环/倒计时/数字），导致整块核心 UI 放大；现 `_render_buff_ui` 不再整体缩放，中间层固定绘制，闪光缩放+白色叠加仅在 `_draw_spikes`（尖刺+顶端装饰小球）上以圆心为中心外扩放大、白色叠加随 progress 衰减。(2) **翻滚白色勾边改为闪光形状**：删除常驻勾边，白色勾边只在翻滚次数增加瞬间出现、放大并衰减闪一下（新增 `_get_dodge_outline_img_white()`，恒为白色），由设置「翻滚闪光·白色勾边」开关控制。(3) **翻滚第 6/7 次改为纯黄色圆角三角**，去掉红色边框与感叹号。

- **V269**: Fixed two fatal `NameError`s that were silently swallowed: (1) the source used `QImage` without importing it, so checking "Outline along shape contour" threw in `_build_shape_outline()`, and the bare `except: pass` in `paintEvent` swallowed it, blanking the entire dodge UI; (2) the source used `QPainterPathStroker` without importing it, so the 6th/7th dodge `_draw_warning_roll_icon()` threw and the warning card didn't show. Both classes were added to the `PySide6.QtGui` import line, and a one-time error log was added to `paintEvent` to avoid future silent ignores. Also enhanced settings real-time feedback: after `repaint()` added `update()` + `QApplication.processEvents()`, and started a 50ms high-frequency refresh timer while the settings dialog is open.
- **V269**：修复两个被静默吞掉的致命 `NameError`：(1) 源码使用了 `QImage` 却未导入，导致勾选「沿图案轮廓勾边」时 `_build_shape_outline()` 抛错，`paintEvent` 的裸 `except: pass` 吞掉后整个翻滚 UI 空白；(2) 源码使用了 `QPainterPathStroker` 却未导入，导致第 6/7 次翻滚 `_draw_warning_roll_icon()` 抛错，警告牌不显示。已在 `PySide6.QtGui` 导入行补齐这两个类，并给 `paintEvent` 增加一次性错误日志避免未来再被静默忽略。同时设置面板实时反馈增强：`repaint()` 后补 `update()` + `QApplication.processEvents()`，并在设置对话框打开期间启动 50ms 高频刷新定时器。

- **V268**: Fixed three stability issues: (1) settings parameter tweaks now use synchronous `repaint()` for more immediate real-time feedback (the breathing glow is only visible when the ability is ready); (2) hardened the dodge default icon load path (source-mode fallback + custom-path failure fallback + rectangle outer-glow fallback when the icon is missing), fixing a complete blank after checking "Outline along shape contour" in some environments; (3) added a degraded fallback draw for the 6th/7th dodge warning card to keep it always visible.
- **V268**：修复三个稳定性问题：(1) 设置面板调参改为同步 `repaint()`，实时反馈更即时（呼吸光需在能力就绪时才可见）；(2) 加固翻滚默认图标加载路径（源码模式回退 + 自定义路径失效回退 + 图标丢失时矩形外发光兜底），解决部分环境下勾选「沿图案轮廓勾边」后完全空白；(3) 翻滚第 6/7 次警告牌增加退化兜底绘制，确保始终可见。

- **V267**: Fixed three UI issues: (1) the ability-ready **breathing glow shape changed to a diamond** (no longer a circle), matching the ability diamond and clipped into a diamond halo; (2) the dodge "Outline along shape contour" is now **always visible** when checked, and fixed the contour-generation failure caused by `QPixmap.convertToFormat()`, pulsing stronger during flash; (3) the 6th/7th dodge **warning icon changed to a rounded triangle**, smoother. Also, settings tweaks now force all three module windows to `update()` immediately for real-time feedback.
- **V267**：修复三个 UI 问题：(1) 能力就绪**呼吸光形状改为菱形**（不再圆形），与能力菱形同形，并被 clip 成菱形光环；(2) 翻滚「沿图案轮廓勾边」勾选后**常驻可见**，并修复 `QPixmap.convertToFormat()` 导致的轮廓生成失败，闪光时再脉冲增强；(3) 翻滚第 6/7 次**警告图标改为圆角三角形**，更圆润。同时设置面板调参现在会强制三个模块窗口立即 `update()`，实现实时反馈。

- **V266**: Fixed two UI flaws: (1) the ability-ready **breathing glow center was misaligned with the diamond center** — the glow center is now concentric with the diamond; "softness" now truly controls the radial-gradient decay exponent (soft/hard adjustable), and a new "glow size" control sets the halo radius; (2) the dodge icon flash **outline only stroked the PNG rectangle frame** — now it reads the PNG alpha channel, applies morphological dilation to get the **shape outer contour** stroke + fading glow, with new "outline width" and "outline glow" settings.
- **V266**：修复两个 UI 硬伤：(1) 能力就绪**呼吸光中心与菱形中心对不上**——发光中心改为菱形中心同心；「柔和程度」现在真正控制径向渐变衰减指数（软硬可调），并新增「光圈大小」控制光晕半径；(2) 翻滚图标闪光**勾边只描 PNG 矩形外框**——改为读取 PNG alpha 通道做形态学膨胀得到**图案外轮廓**描边 + 渐隐辉光，新增「勾边粗细」「勾边辉光」设置。

- **V265**: Fixed the core detection area "mysteriously disappearing when it's the only one" — root cause: the core window (`Qt.Tool`) was the parent of the "Settings dialog"; on Windows, when switching to the game it gets cascaded-hidden by the system (the ability / dodge areas, being children of a non-modal box, were unaffected). The settings dialog and the update "three-choice" popup were changed to parentless top-level + `WindowStaysOnTopHint` + application-modal, and after closing they force `core_win.show()/raise_()` as a fallback.
- **V265**：修复**核心检测区"只有它"神秘消失**的问题——根因是核心窗口（`Qt.Tool`）作为「设置对话框」父窗口，在 Windows 上切到游戏时会被系统级联隐藏（能力区/翻滚区因非模态框之父不受影响）。设置对话框与更新「三选一」弹窗改为无父顶层 + `WindowStaysOnTopHint` + 应用模态，关闭后强制 `core_win.show()/raise_()` 兜底。

- **V264**: Fixed the title-bar update button **never drawing the download progress** — now during download a green ring progress + percentage text is overlaid on the button; and changed the "auto-hide on game focus loss" handling from `showMinimized()` to `hide()`, avoiding the Windows Tool borderless transparent window "minimize then stuck/unrecoverable" hazard that could lose the window.
- **V264**：修复标题栏更新按钮**下载进度从未绘制**的问题——现在下载时按钮上叠加绿色环形进度 + 百分比文字；并将「随游戏前后台自动隐藏」的失焦处理由 `showMinimized()` 改为 `hide()`，规避 Windows 上 Tool 无边框透明窗口"最小化后卡死不可恢复"导致窗口丢失的隐患。

- **V263**: Fixed the update check error `The read operation timed out` on disconnected proxy / flaky networks: relaxed the timeout and added 3 incremental retries (15s / 25s / 35s), improving success on slow `raw.githubusercontent.com` connections; the update-failure message is now more intuitive Chinese (with English / Traditional-Chinese translations adapted).
- **V263**：修复断梯子 / 网络波动时更新检测报 `The read operation timed out` 的问题：检测超时从 8 秒放宽并增加 3 次递增超时重试（15s / 25s / 35s），提升 `raw.githubusercontent.com` 慢连接成功率；更新失败提示改为更直观的中文说明（并适配英文/繁体界面翻译）。

- **V262**: Added an **update button** to the core window title bar — after launch it auto-checks for new versions in the background, and when an update is found the button lights up with a breathing glow; clicking it **downloads the new exe to the current program directory in one click** (preserving `overlay_settings.json` and other config), and after download a three-choice popup appears: "Close current and open new / Open new only / Later". **Reworked the launch progress window**: more compact, and added a "Show progress window on launch" toggle in Settings → About/Update (default on).
- **V262**：核心窗口标题栏新增**更新按钮**——启动后自动后台检查新版本，发现更新时按钮亮起并呼吸发光；点击按钮即可**一键下载新版 exe 到当前程序同目录**（保留 `overlay_settings.json` 等配置），下载完成后弹窗三选一：「关闭当前并打开新版 / 仅打开新版 / 稍后」。**启动读条窗口重做**：更简约紧凑，并在设置 → 关于/更新 中新增「启动时显示读条窗口」开关（默认开启）。

- **V261**: Added a **launch progress window** — double-clicking to open the app shows a progress bar and a "what is happening now" status text; after init completes it shows "Launch complete" before entering the main UI; **a default update URL is baked in** (`raw.githubusercontent.com` direct link), so the first launch auto-checks for updates without manual entry.
- **V261**：新增**启动读条窗口**——双击开启软件时显示进度条与「当前正在做什么」状态文字，初始化完成后显示「启动完成」消息再进入主界面；**默认写定更新地址**（`raw.githubusercontent.com` 直链），首次启动即自动检测新版本，无需手动填写。

- **V250**: Skill cooldown diamond border ×1.35 (adjustable); soft breathing glow at cooldown end (frequency / softness / color / peak opacity adjustable, default white); integrated `version.json` auto-update.
- **V250**：技能冷却菱形边框 ×1.35（可调）；冷却完毕底部柔和呼吸光（频率 / 柔和程度 / 颜色 / 峰值不透明度可调，默认白色）；接入 `version.json` 自动更新。

- **V249**: The countdown capsule (background / border / text) follows the slot's hue rotation as a whole.
- **V249**：倒计时胶囊（背景 / 边框 / 文字）整体跟随槽位色相旋转。

- **V248**: Multi-Buff layout isolated into per-count group boxes; Delta_Y allows negative values; active / hidden zone height ×1.2 again; layer 0 shows "−".
- **V248**：多 Buff 布局按个数隔离小组框；Delta_Y 允许负值；生效区 / 隐藏区高度再 ×1.2；层数 0 显示“-”。

- **V247**: All settings parameters strictly landed end-to-end; Buff group box collapsible + 1.2× height + left-aligned; core multi-Buff rewritten (up to 5, ×1.35, horizontal-even + ΔY offset, 20 params, hue-rotation differentiation).
- **V247**：设置参数全链路严格落地；Buff 小组框折叠 + 1.2 倍高度 + 左对齐；核心多 Buff 重写（最多 5 个、×1.35、水平均匀 + ΔY 错位、20 参数、色相旋转差异化）。

- **V244**: Captain / Gran / Katalina Class level + countdown; Id four gauges (Azure/Arvess / The One / hidden); raw-value resource gauge read framework.
- **V244**：团长 / 古兰 / 姬塔 Class 等级 + 倒计时；伊德四槽（紫银 / 神威 / 隐藏）；裸值资源槽读取框架。

- (Earlier V098–V101 were the basic cooldown monitor and skill-cooldown UI fixes.)
- （更早 V098–V101 为基础冷却监视与技能冷却 UI 修复。）

---

## Disclaimer | 免责声明

- This tool only **reads** the game process memory and does not modify any game files; intended for single-player / offline use.
- Using third-party memory-reading tools carries account risk — please assess and bear the consequences yourself; the author is not responsible for any outcome of use.
- This tool is not an official Cygames / PlatinumGames product.

### 免责声明
- 本工具仅**读取**游戏进程内存，不修改任何游戏文件，面向单机 / 离线使用。
- 使用第三方内存读取工具存在账号风险，请自行评估并承担相关后果；作者不对任何使用后果负责。
- 本工具并非 Cygames / PlatinumGames 官方产品。
== v22.45 ==
[Both Buff modules · buff-list display fully fixed]
1) Refactored the duplicated nested _add_buff_list_group in both core all-buff and Boss Buff modules' buff-list pages into a single SettingsDialog method to avoid the 'fix one, miss the other' trap.
2) Changed the inner QWidget's vertical size policy from Expanding to Preferred, and explicitly synced _inner.setMinimumHeight to the actual content-required height after _refresh_buff_list refreshes, so vertical scrollbar appears correctly when items overflow.
3) Row QLabel got setWordWrap(False)+horizontal Expanding, row min height 32px, button 76px equal width, overall aligned.
Note: this version did not finish the tri-lingual red-line; release_notes.txt and README.md were not synced with v22.45 blocks; V2246 has filled them in.

