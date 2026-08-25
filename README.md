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

## Download & Install | 下载与安装

1. Go to [Releases](https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases) and download the latest `GBFR_CooldownIndicator_V2007.exe` (single file, ~50MB, PySide6 bundled, no install needed).
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
