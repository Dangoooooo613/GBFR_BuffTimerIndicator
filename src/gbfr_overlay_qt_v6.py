#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GBFR Overlay Qt Edition v60 — 角色层数/倒计时指示器
改动：
1. 读取方式从指针链改为 ExStatus 结构扫描（更稳定，跨版本兼容）
2. 恢复伽兰查(武夫)和菲莉(托愿)支持
3. 层数上限从内存动态读取（+0xB0），尖刺个数自动适配
4. 倒计时最大值从内存动态读取（+0x7C），扇形比例自动正确
5. 设置面板简化：仅需 ExStatus 偏移（默认 0xAF8）
6. 有效性校验：NaN/Inf/垃圾数据过滤
"""

import ctypes
import json
import math
import os
import struct
import sys
import threading
import time
import logging
logger = logging.getLogger("GBFR_Indicator")
from ctypes import wintypes

import mastery_reader
import buff_data_generated

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QPointF, QProcess, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QLinearGradient, QRadialGradient, QStandardItem, QStandardItemModel, QIcon, QImage, QPainter, QPen, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QScrollArea,
    QSpacerItem,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,  # V2263：3D 效果 sub-tab 用 — 每风格参数页动态显隐
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ============================ Paths ============================
if getattr(sys, "frozen", False):
    # PyInstaller onefile: sys.executable 指向临时解压目录，
    # 用 sys.argv[0] 才能拿到用户双击的那个原始 exe 所在目录，日志/配置/缓存都写这里才持久。
    EXE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(EXE_DIR, "overlay_settings.json")
PTR_CACHE_FILE = os.path.join(EXE_DIR, "ptr_cache.txt")
if getattr(sys, "frozen", False):
    _BUNDLE_DIR = sys._MEIPASS
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SHRIMP_IMG_PATH = os.path.join(_BUNDLE_DIR, "embedded_roll_icon.png")
# V2313：第 6/7 次「图片模式」的内置默认警告图
DEFAULT_WARNING_IMG_PATH = os.path.join(_BUNDLE_DIR, "embedded_roll_warning_icon.png")
APP_ICON_PATH = os.path.join(_BUNDLE_DIR, "app_icon.ico")

# V2220：删除外放玩家字典 buff_attrs_user.json —— 数据来源改为「内置 buff_attrs.json（封进 exe）」
# + 外部补充文件 buff_attrs_unknown.json：玩家可补充未知 buff 的名字（含日文），保存即热更新生效；同时自动记录见过哪些未知 sid。

# V2050：全 Buff 显示模块数据源（全游戏 buff 属性 + 三语名），来自 GBFR_BuffMonitor 的 buff_attrs.json。
# V2070：改用与 i18n_loader 同款的健壮查找（多候选路径 + 递归兜底），避免运行期 BUFF_ATTRS 为空导致全 Buff 空白。
def _load_buff_attrs():
    import glob as _glob
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "buff_attrs.json"))
    candidates.append(os.path.join(EXE_DIR, "buff_attrs.json"))
    candidates.append(os.path.join(_BUNDLE_DIR, "buff_attrs.json"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "buff_attrs.json"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "argv", [None]) else __file__)), "buff_attrs.json"))
    # 兜底：在 _MEIPASS / EXE_DIR 递归找第一个 buff_attrs.json
    for base in (meipass, EXE_DIR, os.path.dirname(os.path.abspath(__file__))):
        if base:
            try:
                hits = _glob.glob(os.path.join(base, "**", "buff_attrs.json"), recursive=True)
                for h in hits:
                    candidates.append(h)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
    chosen = None
    for p in candidates:
        if p and os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                chosen = p
                break
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
    if chosen is None:
        builtin = {}
    else:
        builtin = data
    # V2220：不再加载外部玩家字典 buff_attrs_user.json（已删除）。
    # 数据来源 = 内置 buff_attrs.json（封进 exe，datas 注入）。
    # 未知 buff 处理见 _unknown_buff_attr / _dump_unknown_buffs / _reload_user_attrs —— 外部补充文件可热更新改名。
    return builtin
BUFF_ATTRS = _load_buff_attrs()

# V2105：debuff 判定改为查 buff_attrs.json 的「是否debuff」字段（来自 GBFR_BuffMonitor 的 xlsx 末列标注），
# 不再用 sid>=1000 的硬阈值。命中表则用表内标记；未命中（未知 id）才回退旧阈值 1000，保留对新增 ailment 的安全兜底。
def _is_debuff(sid):
    # V2309：调试态下，统一覆盖 dict 把「是否debuff」写成 False，导致所有调试 sid 都判不成 debuff。
    # 这里用注入时登记的 _DEBUG_DEBUFF_SIDS 显式还原 debuff 类别，让调试也能看到 debuff 渲染。
    if _DEBUG_ATTR.get("active") and int(sid) in _DEBUG_DEBUFF_SIDS:
        return True
    entry = _attr_for_sid(sid)
    if entry is not None:
        return bool(entry.get("是否debuff", False))
    return sid >= 1000

# ── V2209：未知 buff 显示 ID + 未知清单落盘 ────────────────────────────────
def _unknown_buff_attr(sid):
    """V2209：未收录进 buff_attrs.json 的未知 buff —— 合成一个最小 attr，
    让主控全 Buff 与 Boss 两个模块都能把它显示出来（名称直接就是十六进制 ID，玩家可照抄去补录）。
    `_is_debuff(sid)` 自身有 sid>=1000 兜底，所以这里不必设「是否debuff」键。
    `_unknown` 标记供 items.append 处判断要不要记进未知清单。"""
    return {
        "名称":       "0x{:X}".format(sid),
        "繁中名":     "0x{:X}".format(sid),
        "英文名":     "0x{:X}".format(sid),
        "日文名":     "0x{:X}".format(sid),
        "是否专属": False,
        "是否专精buff": False,
        "单层": False,
        "_unknown": True,
    }

# ── V2224：外部补充文件（buff_attrs_unknown.json）玩家可改名、保存即热更新 ──
# 该文件既是「自动记录见过哪些未知 sid」的日志，也是「玩家可补充名字（含日文）的覆盖文件」。
# 软件每帧按 mtime 检测文件变化，玩家在外部编辑器保存后下一帧（通常 <1 秒）即生效，无需重启/重装。
# 键格式与 BUFF_ATTRS 一致："0x{sid:X}({sid})"；玩家填的字段（名称/繁中名/英文名/日文名/布尔标记）优先于内置。
USER_ATTRS_FILE = os.path.join(EXE_DIR, "buff_attrs_unknown.json")
USER_ATTRS = {}
_USER_ATTRS_MTIME = [-1.0]

def _reload_user_attrs(force=False):
    """V2224：按 mtime 热加载外部补充文件到 USER_ATTRS。玩家保存文件后下一帧即生效。"""
    global USER_ATTRS
    try:
        mtime = os.path.getmtime(USER_ATTRS_FILE)
    except OSError:
        mtime = -1.0
    if (not force) and abs(mtime - _USER_ATTRS_MTIME[0]) < 1e-6:
        return
    _USER_ATTRS_MTIME[0] = mtime
    try:
        if mtime > 0 and os.path.isfile(USER_ATTRS_FILE):
            with open(USER_ATTRS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                USER_ATTRS = data
                return
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
    USER_ATTRS = {}

# 模块加载时先热加载一次（文件不存在也安全）
_reload_user_attrs(force=True)

# ── V2304：调试数据模式的名称覆盖 ─────────────────────────────────────────
# 「调试数据」选项卡开启后，全 Buff / Boss 两个模块的名字不再走 buff_attrs 查表，
# 而是统一显示玩家在设置里填的文本（默认「测试带编码」），便于纯离线核对排版/字号/换行。
# 用可变 dict 而不是模块级 bool，避免 global 声明散落各处；由 _inject_debug_data 每帧刷新。
_DEBUG_ATTR = {
    "active": False,       # 是否处于调试数据模式
    "text": "测试带编码",  # 覆盖用的显示文本
    "single": False,       # 合成 attr 的「单层」标记
}
_DEBUG_DEBUFF_SIDS = set()  # V2309：调试态注入的 debuff 假 sid 集合；_is_debuff 在调试态据此把对应 sid 判为 debuff。

def _debug_attr_override():
    """V2304：按当前调试文本合成一份 attr（四语同文本，不含 _unknown 标记，避免污染未知清单）。"""
    t = _DEBUG_ATTR.get("text") or "测试带编码"
    return {
        "名称":   t,
        "繁中名": t,
        "英文名": t,
        "日文名": t,
        "是否专属": False,
        "是否专精buff": False,
        "单层": bool(_DEBUG_ATTR.get("single", False)),
        "是否debuff": False,
    }

def _attr_for_sid(sid):
    """V2224：取某 sid 的显示 attr——外部补充优先，其次内置，最后未知兜底（hex ID）。
    V2304：调试数据模式下直接返回合成 attr（统一文本），完全跳过查表。
    V2319：封堵「陈旧 unknown 记录盖掉正确内置名」的反馈环——若外部补充条目是自动记录的
    兜底（名称为空 或 等于十六进制 ID，形如 0x94），而内置表已有真实名称，则改用内置；
    否则（外部填了真名 / 内置也缺失）仍按原优先级。避免 0x94 类「一直显示十六进制」复发。"""
    if _DEBUG_ATTR.get("active"):
        return _debug_attr_override()
    key = "0x{:X}({})".format(sid, sid)
    user = USER_ATTRS.get(key)
    if user is not None:
        _uname = (user.get("名称") or "").strip()
        _hex = "0x{:X}".format(sid)
        _stale = (_uname == "" or _uname.lower() == _hex.lower())
        if not _stale:
            return user
        # 陈旧兜底条目：仅当内置也缺失时才用它，否则退回内置真实名
        builtin = BUFF_ATTRS.get(key)
        if builtin is None:
            return user
        return builtin
    builtin = BUFF_ATTRS.get(key)
    if builtin is not None:
        return builtin
    return _unknown_buff_attr(sid)

# 未知 buff 观测记录：{sid: {"last": ts, "count": n}}
_UNKNOWN_BUFF_SIDS = {}
_UNKNOWN_LAST_DUMP = [0.0]

def _note_unknown_buff(sid):
    """V2209：render 端在 buff 通过全部门限、确定要显示时调用（避免把垃圾数据也记进来）。"""
    e = _UNKNOWN_BUFF_SIDS.get(sid)
    if e is None:
        e = {"last": 0.0, "count": 0}
        _UNKNOWN_BUFF_SIDS[sid] = e
    e["last"] = time.time()
    e["count"] += 1

def _dump_unknown_buffs(force=False):
    """V2224：把观测到的未知 sid 落盘到 EXE_DIR/buff_attrs_unknown.json（既是诊断日志，也是玩家补充文件）。
    未知 buff 默认显示十六进制 ID；玩家可直接在该文件补 名称/繁中名/英文名/日文名，保存后下一帧即生效。
    本文件亦供玩家核对「见过哪些不认识的 buff」、或向作者反馈 ID 以便补充进内置 buff_attrs.json。已有条目只更新观测次数/时间。"""
    if not _UNKNOWN_BUFF_SIDS:
        return
    now = time.time()
    if not force and now - _UNKNOWN_LAST_DUMP[0] < 5.0:
        return
    _UNKNOWN_LAST_DUMP[0] = now
    path = os.path.join(EXE_DIR, "buff_attrs_unknown.json")
    out = {}
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                _d = json.load(f)
            if isinstance(_d, dict):
                out = _d
    except Exception:
        out = {}
    for sid, e in _UNKNOWN_BUFF_SIDS.items():
        key = "0x{:X}({})".format(sid, sid)
        rec = out.get(key)
        if not isinstance(rec, dict):
            rec = _unknown_buff_attr(sid)
            rec.pop("_unknown", None)
            rec["_note"] = ("未收录 buff（自动记录）。本文件即外部补充文件：你可直接把 名称/繁中名/英文名/日文名"
                            "改成正确名字，保存后下一帧即生效（无需重启）；若不知是什么 buff，可连同此 ID 反馈给作者。")
        rec["_last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["last"]))
        rec["_seen_count"] = e["count"]
        out[key] = rec
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.debug("swallowed exception", exc_info=True)

# V2212 debug：把过滤后的 boss items 节流 dump 到 EXE_DIR/last_boss_buffs.json（1 秒）
# 玩家游戏暂停时也能直接读到 boss 身上当前 buff（不靠截游戏画面）。
# 上一轮 V2211 测试时用户报告"按理应该有 4 个 buff，前两个未知"，
# 但 ImageGrab.grab 截到的是暂停时主菜单遮住的画面，不是 boss 模块本身。V2212 加 dump 绕过截图。
# 不影响显示逻辑，dump 是 read-only 旁路。
_BOSS_LAST_DUMP = [0.0]
def _sanitize_info(info):
    """把 info 里的 NaN / ±Inf 转成 None，避免 json.dump 产出非法 JSON。"""
    _d = {}
    for k, v in (info or {}).items():
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            _d[k] = None
        else:
            _d[k] = v
    return _d

# V2319：调试 dump 总开关（默认关）。开启后才会写 last_boss_buffs.json / overlay_focus_log.txt，
# 避免运行时散落多余文件（正常只应输出 overlay_settings.json / ptr_cache.txt / buff_attrs_unknown.json 三份）。
ENABLE_BOSS_BUFF_DUMP = False
ENABLE_FOCUS_LOG = False

def _dump_boss_buffs(items, raw=None):
    """V2213 debug：dump 过滤**后**的 items + 过滤**前**的原始数据 raw。
    两份对比就能看出「哪个 buff 被门限丢了」，而不是只能看到幸存者。
    raw = render_bossbuff 的循环变量 buffs（read_boss_buffs 返回的 result_list）。"""
    if not ENABLE_BOSS_BUFF_DUMP:
        return
    import json
    now = time.time()
    if now - _BOSS_LAST_DUMP[0] < 1.0:
        return
    _BOSS_LAST_DUMP[0] = now
    path = os.path.join(EXE_DIR, "last_boss_buffs.json")
    out = []
    for sid, info, attr in items:
        out.append({
            "sid": int(sid),
            "info": _sanitize_info(info),
            "name": attr.get("名称") or "",
            "unknown": bool(attr.get("_unknown")),
        })
    raw_out = None
    if raw is not None:
        raw_out = []
        for _r in raw:
            try:
                _sid, _info = _r[0], _r[1]
            except Exception:
                continue
            raw_out.append({"sid": int(_sid), "info": _sanitize_info(_info)})
    try:
        with open(path, "w", encoding="utf-8") as _f:
            json.dump({"ts": now,
                       "count": len(out),
                       "raw_count": (len(raw_out) if raw_out is not None else None),
                       "items": out,
                       "raw": raw_out},
                      _f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        logger.debug("swallowed exception", exc_info=True)

# V2211：V2117 固化三门限（NaN/Inf / sid=0 永续 / 0.0/0.0 永续无效）再追加第 4 项：
#  `remaining < 0` 或 `initial < 0` 的 buff 直接丢弃。
#  玩家反馈：游戏里偶尔会出现「-0.5/8.5」这种状态转换瞬间 / 数据异常的 buff，
#  现在的「0.0/0.0 丢弃」拦不住负值，导致卡片显示「-0.5/8.5」这种无意义读数。
#  合并到同一个 `if _zr < 0 or _zi < 0 or f"{_zr:.1f}/{_zi:.1f}" == "0.0/0.0": continue` 里。
#  主控全 Buff 与 Boss 两个模块循环对称、一次改两处；同步把源码里所有
#  「V2117 三门限已固化」「V2117 三门限固化」字样更新为「V2117+V2211 四门限已固化」。
# V2210：两项改动
#  ① 删 Boss 模块的「分类显示」子标签（核心/永续/专属/专精/单层 五个排除开关）。
#     连带清掉 _connect_live_signals / reset_defaults / collect_settings 里的 5 个死引用
#     （控件没了还去 .stateChanged.connect / .setChecked / .isChecked 会抛 AttributeError）。
#     DEFAULT_SETTINGS 的 5 个键与 render 端 ex_inf/ex_excl/ex_mast/ex_single/ex_core 检查**都保留**，
#     兼容旧 overlay_settings.json / 玩家手动改 json 恢复。
#  ② 修「明明是同一个 buff 却在模块里出现两次」的 bug（玩家反馈：燃烧A 显示两张一模一样的卡）。
#     根因在数据源：ExStatus 是指针数组（16 槽），同一条 status 对象可能被多个槽位指向，
#     原逻辑每个槽位都读一次 → 同一条 buff 被收集多份；而燃烧/中毒这类 sid 玩家自己加进了
#     「多次出现名单」（本意是让燃烧A+燃烧B 这种真·两层如实显示），反而连重复读取也一起显示了。
#     两级去重，且**不误伤**「真·多实例」：
#       · read_exstatus_buffs：按 status 指针地址去重，同一 ptr 只读一次（主控 + Boss 共用，一并修）；
#       · render_allbuff / render_bossbuff：内容指纹去重 —— 同 sid 且
#         (sub_id / 层数 / 剩余 / 持续 / 永续) 五项全同才视为同一条的重复读取，只留 1 张；
#         真正不同的实例（燃烧A rem=8.5 / 燃烧B rem=3.2）指纹不同，照旧全部显示。
# V2209：五项改动（Boss + 主控全 Buff 两个模块同时生效）
#  ① BUGFIX 主控缩放被 Boss 缩放抢走：`_mk_scale_row` 内部会 `setattr(self, f"{key}_scale_slider")`，
#     而 Boss 段传的 key 写成了 "allbuff" → 主控的 slider/spin 属性被 Boss 控件覆盖 →
#     get_settings 两个键都写成同一控件的值（表现：主控缩放「消失」、Boss 缩放同时控制两个）。改回 "boss"。
#  ② 进度条与倒计时文本融合：倒计时文本居中浮在进度条上方（同一垂直槽位，文本带深色描边保证压在条上也清晰），
#     卡片由「名称 / 层数 / 时间 / 进度条」四行压缩为三行，真实省掉一整行垂直空间。
#     同步改了卡片内 _content_h 与窗口 auto_bh 两处高度估算，避免外框溢出衬底。
#  ③ buff 属性字典：数据来源为内置 buff_attrs.json（封进 exe，datas 注入）。V2220 起不再外放玩家字典；
#     未知 buff 显示十六进制 ID，并可经外部补充文件 buff_attrs_unknown.json 由玩家改名（保存即生效）。
#  ④ 新增「特殊独立」属性：指不走 ExStatus、需要单独找偏移单独读的 buff（BUFF_PROFILES 的 raw_source 类），
#     共 5 条 = 古兰/姬塔 Class等级(class_state)、巴萨拉卡古洛诺斯槽保持(actor_timer)、
#     伊德隐藏槽(id_direct)、芙劳转世的恩宠(actor_timer)。它们 sid 是负数占位且互相冲突，
#     不在 buff_attrs.json 的 sid 键空间，故外放字典用 "SP:{PL}:{idx}" 独立键，天然都是角色专属。
#  ⑤ 主控全 Buff 模块也支持未知 buff：与 V2208 的 Boss 模块一致，未收录 buff 不再丢弃而显示其十六进制 ID；
#     且**通过全部门限后**才记进未知清单，每 5 秒落盘 EXE_DIR/buff_attrs_unknown.json（玩家可在此补名，保存即生效）。
# 版本号：标题栏与自动更新共用同一基线，与 release_notes / version.json 同步。
# V2208：Boss Buff 模块对未收录进 buff_attrs.json 的未知 buff 不再直接丢弃——
# 原本 render_bossbuff 在 `attr = BUFF_ATTRS.get(...)` 拿到 None 时 `continue` 掉，
# 导致一些 boss 的 buff（DB 没收全 / 新出的 DLC）整张卡片根本不出现，玩家以为工具没读到。
# 现在保留 None 时合成一个最小 attr（名称/繁中名/英文名 都填成 "0x{sid:04X}"），
# 让玩家能直接看到 ID，便于后续 (a) 在 buff_attrs.json 里补名；(b) 开 issue 时直接复制 ID。
# `_is_debuff(sid)` 自身有 sid>=1000 兜底，兜底 attr 不用设「是否debuff」键。
# 过滤开关 (boss_exclude_*, boss_gate_*) / 黑名单 / 多次出现名单 一切照旧，玩家仍可手动屏蔽。
_BUILD_NO = 2236  # V2236：(1) **删除全buff小模块闪光**功能（flash_apply_allbuff_submodule/boss_flash_apply_allbuff_submodule 移除 + 3 键 + 3 复选框 + 闪光计时器/字段清除）；(2) **4 个名单 UI 重做**——QScrollArea+stretch → QListWidget+setItemWidget（小框+列表+滚轮）；(3) **门限全外露**——主控+Boss 顶部加 6 条 disabled checkbox（NaN/Inf / ID=0 非永续 / 隐藏 0.0 / remaining<0 舍弃 / 永续剩余≤0 舍弃【新加】 / 时长上限 10000s+9999 永续豁免）+ render 端硬编码 2 条新检查；(4) 卡片水平+垂直居中复核注释。源码备份到 `src_backups/2026-09-01_12-55-09_V2236/`。
_BUILD_NO = 2237  # V2237：能力模块「聚散距离」下限解负——UI SpinBox setRange(20,200)→(-200,200)；render_skill 去掉 max(spread, half_diag+8) 的「避免菱形覆盖中心」兜底，允许菱形完全聚拢/重叠（spread 直接生效）；recalc_layout 画布尺寸兜底从 half_diag+8 改为 0（画布不再防聚拢，但确保不变成负尺寸崩溃）；DEFAULT_SETTINGS["skill_cd_spread"]=90 默认值不变。源码备份到 `src_backups/<TS>_V2237/`。
_BUILD_NO = 2238  # V2238：紧急 hotfix 上一版 V2237——上一版「4 个名单 UI 重做」用了 QListWidget.setPlaceholderText(...) 设置空态文案，但 PySide6 6.11.1 的 QListWidget **根本没有**这个方法（那是 QLineEdit/QComboBox/QSpinBox 的）。结果：「设置」窗口一打开就 AttributeError，连主控/Boss 选项卡都进不去。修法：(1) _add_buff_list_group（主控 + Boss 两处）删 setPlaceholderText 调用（line 4102 + line 4462）；(2) _refresh_buff_list 在清空且 _items 为空时插入一个**不可点击/不可选中的暗灰 placeholder item**（_tr(empty_key) + Qt.NoItemFlags + QBrush(QColor("#5a6a85"))），跟真行数据完全独立、不会污染 sizeHint 计算。源码备份到 `src_backups/<TS>_V2238/`。
_BUILD_NO = 2239  # V2239：两个 buff 模块「已固化的门限」再瘦身——(1) **③④⑤ 三条合并为 1 条新规则**：「任何 buff 的剩余或初始时间都不可能 ≤ 0」——把「隐藏倒计时 0.0/0.0」「remaining/initial 任一 < 0 」「永续 remaining 不可能 ≤ 0」三条独立固化合并为一条更直白的统一规则，render 端 = `if remaining<=0 and remaining<9999: continue` + `if initial<=0: continue`。(2) **⑥ 时长上限改为可调数值**——disabled 固化复选框保留（永远开启），旁边新增 DoubleSpinBox，初始值 10000.0，玩家可在「门限」页调节上下限；render 端 `if not _huge_t and (initial>g_dur_max or remaining>g_dur_max): continue`，g_dur_max 从 settings.get(...) 动态读取（DEFAULT_SETTINGS["*_gate_duration_max_with_infinite_exemption"] 默认 10000.0，旧玩家升级保持原值）。(3) ① NaN/Inf 检查 + ② ID=0 不可能是永续 两条**完整保留**。源码备份到 `src_backups/<TS>_V2239/`。
_BUILD_NO = 2240  # V2240：核心模块画布宽/高可调——新增 core_canvas_w / core_canvas_h 两设置键（默认 0 = 自动，完全向后兼容）。recalc_layout 算完自动值后，若用户值 >0 则覆盖 core_canvas_w/h 并按新值重算 circle_cx/cy（内容本就相对画布自适应，自动重居中）；强制下限防裁切（宽 ≥ max(CANVAS_W, core_required_w)，高 ≥ 自动预览值 × CORE_AREA_MULT）。设置面板「圆环」卡片新增两个 SpinBox（0–4000，0 显示「自动」）。源码备份到 `src_backups/<TS>_V2240/`。
_BUILD_NO = 2241  # V2241：热修名单展示框排版——_refresh_buff_list 里 setItemWidget 不会自动把 row widget 撑满 QListWidget item 矩形（默认 Preferred size policy → 保留 sizeHint 宽度），导致 label+button 的横向布局被压缩、按钮 setFixedWidth(64) 实际只渲染出 20~30px，「移除」二字被裁成「移」。修法：(1) row widget 加 setSizePolicy(Expanding, Preferred) 强制填满 item 矩形；(2) 按钮改 min+max=76px（比 64 更宽确保留余量）+ font-size 10→11 + padding 2px6→3px8 + 加 PointingHandCursor；(3) retranslate 路径不变。源码备份到 `src_backups/<TS>_V2241/`。
_BUILD_NO = 2242  # V2242：彻底重做名单展示框——V2241 失败根因：QListWidgetItem.sizeHint 把 row widget 锁在 preferred 宽度，setSizePolicy(Expanding) 在 setItemWidget 下无效，按钮依旧被裁。修法：把 4 个名单（主控 bl/ml + boss_bl/ml）的列表容器从 QListWidget+setItemWidget 整个换成 QScrollArea + 内层 QWidget + QVBoxLayout。setWidgetResizable(True) 让 _inner 宽度自动跟 _scroll viewport 宽，QVBoxLayout.insertWidget 加的行 widget 直接拿 _inner 全宽（不受 item.sizeHint 限制），按钮 76px 完整显示在右侧。空态改用居中暗灰 QLabel 占位（替代 V2237 灰色 placeholder item）。行高用 setMinimumHeight(30) + QHBoxLayout sizeHint，不被拉伸。源码备份到 `src_backups/<TS>_V2242/`。
_BUILD_NO = 2243  # V2243：(1) 尖刺腰位置（spike_waist_pos）UI 范围从 5–95% 放开到 0–100%（渲染端已有 waist_pos = clamp(0.05,0.95) 兜底，无副作用）；(2) 「门限」页 4 条门限从 V2239 的「灰色 disabled 固化」改为「可勾选」——① NaN/Inf 检查 ② ID=0/ID=1（攻击UP/防御UP）不可能是永续（新增 ID=1 防御UP 过滤）③ 剩余/初始时间 ≤ X(秒)丢弃（带可调数值框，默认 0.0 秒，范围 0.0–999.0）④ 时长上限（含 9999 永续豁免，带可调数值框，默认 10000.0 秒）。主控全Buff + Boss 两模块对称实现；save()/reset() 同步读写为新 settings 键。源码备份到 `src_backups/<TS>_V2243/`。
_BUILD_NO = 2244  # V2244：整屏对齐体验修复——(1) 设置对话框「模块位置 X/Y」spinbox 与下方整屏对齐/边距/缩放联动：改动对齐方式、边距或缩放时，上方 X/Y 实时刷新为真实屏幕坐标（修复「改了布局位置但上方参数没一起变」）；(2) 非「自定义」对齐轴（靠左/靠右/居中/顶部/底部）禁止手动布局——该轴 X/Y spinbox 置灰不可改，且屏幕上禁止鼠标拖拽与四角缩放（对齐本质就是参数化布局，手动布局会破坏它）；仅「自定义」放开手动拖拽/缩放。五个模块（核心/翻滚/能力/全Buff/Boss）对称实现。源码备份到 `src_backups/<TS>_V2244/`。
_BUILD_NO = 2245  # V2245：彻底修复主控全Buff + Boss Buff 两个模块「名单」子页的排版问题——(1) 把主控/Boss 两处重复嵌套的 _add_buff_list_group 抽成 SettingsDialog 的单一方法，避免未来改一处漏一处；(2) 把内层 QWidget 的垂直 size policy 从 Expanding 改为 Preferred，并在 _refresh_buff_list 刷新后显式同步 _inner.setMinimumHeight 为内容实际所需高度，确保条目超出容器时正确出现垂直滚动条，不再被压缩/裁切；(3) 行 QLabel 加 setWordWrap(False)+横向 Expanding，行高最小 32px，按钮 76px 等宽，整体对齐。源码备份到 `src_backups/<TS>_V2245/`。
_BUILD_NO = 2246  # V2246：修正 V2245 引入的「容器 maxHeight 压制 inner → 行高被压扁 → 文字+按钮重叠」渲染错位——(1) 把 maxHeight/minHeight 从 _container wrapper 下沉到 _scroll（QScrollArea 自身），scroll area 外层仍 240 封顶（控制对话框高度）但内层 _inner 在 setWidgetResizable(True) 下保持 sizeHint (= N*32)、超出 viewport 时自动出垂直滚动条；(2) 删 _container wrapper——scroll area 直接进 form layout，少一层嵌套、行为更可预测；(3) inner 垂直 size policy 从 Preferred 改为 MinimumExpanding——双重保险，inner 永不低于 minHeight。两模块（主控 + Boss Buff）四名单（bl/ml × 2）全部经 _add_buff_list_group 统一修复。源码备份到 `src_backups/<TS>_V2246/`。
_BUILD_NO = 2247  # V2247：彻底重做名单列表——弃 QScrollArea+自定义行 widget，改用标准 QListWidget + 右键菜单移除。V2241~6 在 QScrollArea+custom widget 路线上 4 版都不稳（V2241 setItemWidget 锁宽裁按钮 / V2245 wrapper maxHeight 压扁行 / V2246 QFormLayout 不尊重 maxHeight + 每行两个按钮诡异 bug），用户反馈「不直接创建一个列表，里面放这些 buff，可以直接右键弄个菜单，菜单能移除不就好了」。V2247 实现：① _add_buff_list_group 列表本体从 QScrollArea+内层 QWidget+QVBoxLayout 换成 QListWidget，maxHeight 真生效、自带滚动/选中/行渲染；② _refresh_buff_list 改用 _list.clear() + addItem(QListWidgetItem)，setData(Qt.UserRole, sid) 存 sid；③ 新增 _show_buff_context_menu（Qt.CustomContextMenu → itemAt(pos) 拿 sid → QMenu 含「移除」action）；④ 空态用 Qt.NoItemFlags 占位 item（不可选中、不可右键响应）。两模块（主控 + Boss Buff）四名单（bl/ml × 2）统一经 _add_buff_list_group 工厂走新设计，零自定义 widget/零自定义 layout。源码备份到 `src_backups/<TS>_V2247/`。
_BUILD_NO = 2248  # V2248：名单行高紧贴文字——QFontMetrics(_list.font()).height() × 1.1 算行高，setSizeHint 到每个 QListWidgetItem（含占位 item）。QListWidget 默认行高（受 padding:6px 10px 影响）有约 26px 偏高，用户反馈「行高太高了，根据文字的高度设为1.1倍的文字最高高度就行了」。V2248 修：① _add_buff_list_group 里 stylesheet 显式 font-size:11px + padding 收紧为 0 10px；② 用 QFontMetrics 计算 1.1× 文字高度作为 _row_h，存到 _list._row_h；③ _refresh_buff_list 给每个 item（含占位）setSizeHint(QSize(0, _row_h))。setUniformItemSizes(True) 保证 4 名单（主控 bl/ml + Boss bl/ml）行高一致。源码备份到 `src_backups/<TS>_V2248/`。
_BUILD_NO = 2249  # V2249：名单行高系数 1.1 → 1.3（用户实测 V2248 的 1.1× 略挤，要求放宽到 1.3× 文字高度）。仅改 _add_buff_list_group 里 `_row_h = max(14, int(_fm.height() * 1.3))` 一个系数（原 1.1），其余 V2248 机制不变——仍用 QFontMetrics(_list.font()).height() 算基准、仍 setSizeHint 到每个 QListWidgetItem（含占位）、仍 setUniformItemSizes(True) 保证 4 名单（主控 bl/ml + Boss bl/ml）一致。11px 字 → 文字高度≈14px → 行高≈18px。源码备份到 `src_backups/<TS>_V2249/`。
_BUILD_NO = 2250  # V2250：名单行高系数 1.3 → 1.6（用户实测 1.3× 仍偏挤，要求再放宽到 1.6× 文字高度）。仅改 _add_buff_list_group 里 `_row_h = max(14, int(_fm.height() * 1.6))` 一个系数（原 1.3），其余 V2248/V2249 机制不变——仍用 QFontMetrics(_list.font()).height() 算基准、仍 setSizeHint 到每个 QListWidgetItem（含占位）、仍 setUniformItemSizes(True) 保证 4 名单（主控 bl/ml + Boss bl/ml）一致。11px 字 → 文字高度≈14px → 行高≈22px。源码备份到 `src_backups/<TS>_V2250/`。
_BUILD_NO = 2251  # V2251：倒计时/时长按「整数部分位数」分级显示小数——新增渲染类方法 `_fmt_dur(self, v)`：|v|<10 → 2 位小数（如 9.87）；10≤|v|<100（整数 2 位）→ 1 位小数（如 12.3）；|v|≥100（整数 >2 位）→ 不带小数（如 123）。用 abs() 判位数，负数脏值同样套规则不撑爆卡片。主模块 render_allbuff 与 Boss 模块 render_bossbuff 两处 `time_str = f"{rem:.1f}/{init:.1f}"` 统一改为 `f"{self._fmt_dur(rem)}/{self._fmt_dur(init)}"`，剩余（remaining）与持续（initial）两个值各自按自身位数套同一规则。V2215/V2216 的 ∞ / *∞（FLT_MAX / ≥9999）判定逻辑保持不变且优先级更高。源码备份到 `src_backups/<TS>_V2251/`。
_BUILD_NO = 2252  # V2252：把 V2251 的分级小数规则推广到软件全部倒计时（用户：「把这些应用在软件的所有倒计时上。能力的、核心模块的」）。① 把 `_fmt_dur` 从「全 Buff 渲染」节移到 render_core 之前（所有渲染方法之前），成为全模块共用工具方法，docstring 内列明全部 5 处调用点防漏改。② 新增 3 处调用：能力模块 `_draw_skill_cd_element` 的 `f"{cd_val:.2f}"` → `self._fmt_dur(cd_val)`（无 s 后缀）；核心模块 render_core 单 buff 分支与融合/多 buff 分支的 `f"{timer_val:.2f}s"` → `f"{self._fmt_dur(timer_val)}s"`（保留 s 后缀）。③ 全 Buff / Boss 两处 V2251 已改，保持。至此 5 处倒计时全部统一：`|v|<10`→2 位、`10≤|v|<100`→1 位、`|v|≥100`→不带小数。翻滚模块无数字倒计时（无需改）。V2215/V2216 的 ∞ / *∞ 判定优先级不变。源码备份到 `src_backups/<TS>_V2252/`。
_BUILD_NO = 2253  # V2253：修「整屏对齐要打开一次设置才生效」——_refresh_window_geometries() 此前只在 3 个时机被调用：① 重置窗口位置（确认后）② _on_screen_geometry_changed（且 res_scale 真变了）③ 设置对话框关闭后 _after_settings_changed()。启动时从未调用，模块开机用的是 settings 里的 X/Y 原始坐标，导致 halign/valign（靠左/靠右/居中/置顶/置底）必须开一次设置才生效。修复：在控制器初始化末尾「窗口全部 w.show() 之后」补一次 self._refresh_window_geometries()，让整屏对齐开机即生效。内部先 recalc_layout()+resize()，故 w.width()/height() 已定、_screen_available_geometry() 在 QApplication 建好后即可用，无需延后到事件循环（故直接调用而非 QTimer.singleShot）。5 个模块（core/roll/skill/allbuff/boss）全覆盖。源码备份到 `src_backups/<TS>_V2253/`。
_BUILD_NO = 2254  # V2254：About 页「重要内存地址与数据」面板 i18n 补齐——该面板静态速查表（21 行）此前是**裸字符串硬编码**
_BUILD_NO = 2255  # V2255：i18n 切语言不生效的系统性修复（用户反馈「好多选项、好多文本、全都是中文，尽管我已经调成日文了」）。排查结论：数据层其实是干净的（i18n.json ui 段 566 key 四语全非空、buffs 段 119 条四语齐、combo item 19 个中 16 个在翻译表、另 3 个是语言名「简体中文/繁體中文/日本語」本就不该翻译、源码传给 UI 控件的硬编码中文 0 个），_CURRENT_LANG 三处同步（控制器启动 / SettingsDialog 构造 / retranslate_ui）也正确。真正的四个代码 bug：① retranslate_ui **从不遍历 QComboBox 的 item 文本**（只遍历了 QLabel/QCheckBox/QPushButton/QGroupBox），导致下拉选项「按出现时间 / 居中 / 靠左 / 靠右 / 顶部对齐 / 底部对齐」切语言后仍是中文——新增通用 combo item 翻译：遍历所有 QComboBox，只改显示文本、不动 itemData，且仅当该文本在翻译表内才改（角色名/buff 名等数据项自动跳过，不误伤）。② timer_style / roll_orientation_combo / buff_order_direction_combo 三个手工硬编码刷新块把日文/繁中强制写回中文（"Ring" if lang=="en" else "圆环" → 日文下仍是「圆环」而非「円環」），已删除，改由①的通用逻辑处理（i18n.json 里 圆环→円環、扇形→セクター、横放→横置き、竖放→縦置き、越上越靠左→上ほど左へ 四语齐备）。③ 语言下拉框切换**只**连了 retranslate_ui，没把新语言推给控制器与模块——新增 `self.lang.currentIndexChanged.connect(self._emit_changed)`（先推送再刷本弹窗）。④ 5 个模块窗口的 self.settings 是构造时的深拷贝快照，此前只有 _apply_live_settings（实时拖动路径）回写，设置对话框关闭的 Accepted/Rejected 两条分支都不经过它 → 模块内读 settings["language"] 的路径（_draw_buff_name → _buff_name）永远用启动时的旧值 → 在 _after_settings_changed 末尾无条件回写 5 个窗口的 settings。源码备份到 `src_backups/<TS>_V2255/`。，完全没走 _tr()，无论切什么语言都显示中文；实时区标题【实时 · 运行期值（每 1 秒刷新）】与专精 fallback「未识别」同样是裸中文。修复：① static_part 21 行中文全部包 _tr()（"─"*64 分隔线为纯符号不译）；② live_lines 标题包 _tr()；③ mastery_zh 三系名（觉醒/真谛/秘义）+ fallback「未识别」包 _tr()；④ i18n.json 补 23 个 key 的 zh_tw/en/ja 三语（zh 不写——_tr(zh) 在 lang=="zh" 时直接返回 key 本身走 fallback，与面板已有 21 个 key 写法一致）。技术信息（hex 偏移 / 版本号 / 字段名 mgr、record、pptr、node_id）在各语言 value 里原样保留不译，只译中文说明部分。经核对实时区原有 21 个 key（如「模块基址 base    = 」）三语本就齐全，本次未重复添加。源码备份到 `src_backups/<TS>_V2254/`。
_BUILD_NO = 2256  # V2256：buff sid 勘误——「混沌转换」此前误记为 sid=129 (0x81)，正确应为 sid=148 (0x94)。依据：运行期自动记录的未知 buff 清单（EXE_DIR/buff_attrs_unknown.json）里实际出现的是 0x94(148)（当时显示 hex 兜底），而 0x81(129) 从未在游戏里出现过。修复：① buff_attrs.json 把该条目（名称 混沌转换 / 繁中名 混沌輪迴 / 英文名 Chaos Shift / 日文名 ケイオシフト，单层=True、是否专属=False）整体从键 "0x81(129)" 迁到 "0x94(148)"——内容四语名与属性原样保留，总条数仍 147；② 源码 L396 附近的 V2231 归档注释同步更正为 sid=148 (0x94)，并加勘误说明；③ ⚠️ 关键：外部补充文件 buff_attrs_unknown.json 的优先级**高于**内置表（_attr_for_sid 先查 USER_ATTRS），所以若运行目录里已存在 0x94(148) 的 hex 兜底记录，会把内置表的正确名字覆盖掉 —— 已清理 dist/buff_attrs_unknown.json 里的该条目（10→9 条）；玩家自己目录里的同名文件若也有 0x94(148) 条目，需一并删除或让软件重新生成（该文件可安全删除，删后重启会自动重建，仅保留仍未知的 sid）。源码备份到 `src_backups/<TS>_V2256/`。
_BUILD_NO = 2257  # V2257：把 dist/overlay_settings.json 的 359 项设置完整烘焙进 DEFAULT_SETTINGS，使「恢复默认」完全等于玩家当前这份配置。① 全量比对：旧 DEFAULT_SETTINGS 351 项、overlay_settings.json 359 项，overlay 完全覆盖 DEFAULT（无遗漏键）并多出 8 项（allbuff_debuff_bar_color_opacity=100 / arc_color_opacity=100 / flash_apply_allbuff_submodule=true / flash_apply_boss_submodule=true / icon_color_opacity=100 / skill_cd_color_opacity=100 / skill_cd_name_color_opacity=100 / skill_cd_text_color_opacity=100）；其中 179 项**值不同**，已逐项烘焙。② 生成方式：按 overlay_settings.json 的键顺序原样重建字典字面量，settings_schema_version 保留变量引用 SETTINGS_SCHEMA_VERSION（升级 schema 时自动跟随，不写死 94）；校验结果 359/359 零差异（缺项 0 / 多项 0 / 值不一致 0）。③ 顺带修 reset_defaults 的漏网 bug：core/roll/skill 三个模块缩放原本硬编码 setValue(100) 绕过 DEFAULT_SETTINGS，导致恢复默认时这三处恒为 100% 而非烘焙值（实测 core_scale_percent=73、roll/skill=100）；已改为与 allbuff/boss 一致读 DEFAULT_SETTINGS["*_scale_percent"]。④ 已扫描确认 overlay 里没有任何运行时状态类键（时间戳/缓存/上次检查等），49 个疑似键全是配置项，故无需排除、可放心全量烘焙。源码备份到 `src_backups/<TS>_V2257/`。
_BUILD_NO = 2258  # V2258：恢复默认的语言改回简体中文。V2257 把 overlay_settings.json 全量烘焙进 DEFAULT_SETTINGS 时，language 一项被烘成了 "ja"（玩家当时正在用日文界面）。玩家确认「默认是 zh」，故此处把 DEFAULT_SETTINGS["language"] 显式写回 "zh"——语言不应跟随某一次的配置快照，恢复默认统一回到简体中文。其余 358 项全部保持 V2257 的烘焙值不变。校验：359 项中仅 language 一项与 overlay_settings.json 不同（zh vs ja），缺项 0 / 多项 0。源码备份到 `src_backups/<TS>_V2258/`。
_BUILD_NO = 2259  # V2259：【修复「恢复默认」把设置冲掉的三处硬编码 + 用最新配置重新烘焙】用户报告：「点恢复默认后，buff 禁用启用里所有的勾选框都选上了」。排查结论：烘焙本身没坏（buff_enabled 119 项 true=94/false=25，与配置完全一致），是 reset_defaults 里有三处硬编码绕过了 DEFAULT_SETTINGS：① `group.set_all(True)` —— 把每个 buff 的觉醒/真谛/秘义三个勾选框无条件全勾，会经 orderChanged→get_settings 回写污染 settings.buff_mastery（用户看到的"全选上"）；已给 MasteryBuffGroup 新增 `apply_mastery_map(mapping)` 按 {bkey:{awakening,truth,secret}} 逐项还原，映射里没有的键按 False 处理（不再默认全勾）。② 三项全局快捷键硬编码 show="17,75"/lock=""/settings=""（含 enabled 全 False），会把玩家配好的 17,219/17,221/17,186 冲掉并禁用 lock/settings；已改为读 global_hotkey_<name> 与 global_hotkey_<name>_enabled。③ title_align 硬编码 findData("left")；玩家当前值恰好也是 left 所以没暴露，已改为读 DEFAULT_SETTINGS。另：全量复查 reset_defaults(345 行) 与 get_settings(309 行)，除以上三处外再无绕过 DEFAULT_SETTINGS 的控件赋值（其余 9 处均是从 DEFAULT_SETTINGS 取值的中间变量）；set_all() 仅保留给界面上的「全选/清空」按钮使用。烘焙：用最新的 overlay_settings.json 全量重烘（language 固定 "zh"，不跟随配置快照），并把烘焙基准另存为 src_backups/<TS>_V2259/overlay_settings_snapshot.json —— 该文件是活文件（软件每次运行都会回写，尤其窗口位置），后续校验一律用快照而非实时文件。源码备份到 `src_backups/<TS>_V2259/`。
_BUILD_NO = 2260  # V2260：主控全 Buff 与 Boss Buff 两个模块的「门限」新增一条**可勾选**规则——「⑤ 剩余时间 > 持续时间丢弃」。键：allbuff_gate_rem_gt_init_drop / boss_gate_rem_gt_init_drop（布尔，默认 True）。判定：`if g_e_remgtinit and not infinite and remaining > initial: continue`——正常 buff 的 remaining 必然 ≤ initial，超出即视为脏值/异常槽位；**永续 buff（infinite=True，显示 ∞ / *∞）豁免**（其 initial 可能为 0 而 remaining 残留正数，属正常），与既有 g_e_minrem / g_e_mininit 的 `not infinite` 守卫保持一致。改动共 12 处（每模块 6 处）：① DEFAULT_SETTINGS 新增键 ② render 读取开关变量 g_e_remgtinit ③ render 应用门限（紧跟 V2243 ③ min_time 判断之后）④ 设置 UI 用 _gate_toggle_row 新增勾选框（纯布尔门限、无数值）⑤ reset_defaults 重置 ⑥ get_settings 收集。i18n：新增 2 个 key（标题「⑤ 剩余时间 > 持续时间丢弃」+ tooltip），补齐 zh_tw/en/ja 三语（zh 不写——_tr(zh) 在 lang=="zh" 时返回 key 本身，与项目既有风格一致）。源码备份到 `src_backups/<TS>_V2260/`。
_BUILD_NO = 2262  # V2261：修正「圆环外勾边比尖刺/装饰小球薄、且要 >2px 才出现」。根因：`_draw_indicator_outer_outline` 里圆环勾边与圆环本体**同心**（都用半径 r），而 `_draw_circle` 的最外层暗边线宽 CIRCLE_WIDTH+2 = 5，占据 r±2.5 且**绘制在勾边之后**，于是把勾边从内侧一路盖到外侧 2.5px 处：outline_w=1（勾边半宽1.5）/ 2（半宽2.5）→ 被完全盖住看不见；outline_w>=3 → 只剩 (outline_w*2+1)/2 - 2.5 ≈ outline_w - 2.5。而尖刺是实心三角形、小球是实心圆，只盖住勾边内侧一半，剩外侧 (outline_w*2+1)/2 ≈ outline_w + 0.5——两者恒定相差 2.5px，这就是用户看到的「调相同值圆环更薄」。修法：圆环勾边改为以「圆环外边缘」为中心，即半径 r + (CIRCLE_WIDTH + 2)/2，露出的外侧宽度 = (outline_w*2+1)/2，与尖刺/小球完全一致（各档位实测一致），且 outline_w=1 起即可见（旧版要 3 才露出 1px）。注：勾边整体仍沿用「先画粗边、再由本体覆盖内侧」的既有设计，本次只修正圆环的圆心半径，不动尖刺/小球，也不改任何设置键与 UI 文案（i18n 无变化）。源码备份到 `src_backups/<TS>_V2261/`。
_BUILD_NO = 2263  # V2263：尖刺/小球立体感改为「可调风格」架构。核心检测模块下新增「3D 效果」子页，集中放置尖刺 5 种立体风格（flat 纯色 / highlight_line 中线高光(V2262) / two_tone 斜向两分面 / edge_band 边缘宽高光带 / bottom_shadow 底厚阴影）与小球 2 种风格（flat 纯色 / radial_gradient 径向球化）+ 通用投影（开关/偏移X/偏移Y/不透明度）+ 通用暗描边（开关/宽度/暗度）+ 各风格独立参数，共 20 个新设置键；每风格参数用 QStackedWidget 按下拉选择动态显隐，实时生效，无需重新构建即可对比调参。渲染侧 _draw_spikes 按 style 分支绘制（two_tone/edge_band 用 QLinearGradient 明暗渐变，bottom_shadow 沿长轴根部变暗，highlight_line 沿中线画亮线），_draw_spike_bead 支持 flat/radial_gradient。默认 spike_3d_style=two_tone、投影偏移 (4,5)、投影不透明度 120（V2262 的 1px 高光 + 2px 投影在 ~50px 尖刺上占比 <5%，肉眼不可见，故本次放大幅度）。i18n 新增 39 个 key 的 zh_tw/en/ja 三语（ui 键数 568->607）。源码备份到 src_backups/<TS>_V2263/。
_BUILD_NO = 2264  # V2264：修复 V2263 的崩溃 bug —— 「3D 效果」子页用了 QStackedWidget，但 PySide6.QtWidgets 的 import 列表里漏了它，导致打开设置对话框即抛 NameError: name 'QStackedWidget' is not defined。已在 import 列表补上 QStackedWidget。（回滚自 V2268：V2265~V2268 的改动已全部撤销，源码回到 V2264 状态。）
_BUILD_NO = 2300  # V2300（基于 V2264 重做）：修复「随游戏前后台自动切换」的两个症状——① 切到后台时两个 buff 模块照样出现；② 切回前台时只剩这两个模块，core/roll/skill 出不来。根因：模块「整窗显隐」散落在 4 处各写各的（启动 show 循环 / _hide_show_all_windows / _apply_live_settings / _sync_out_of_combat_visibility），其中后两处会**无条件** w.show() 两个 buff 模块，完全不知道游戏是否在前台。于是 focus_timer（250ms）刚藏好窗口，只要此时进出战斗/训练场状态翻一下（或改一下设置），buff 模块就被弹回来（症状①）；而它们一直可见 → any_visible 恒为 True → 回前台时 _show_all_windows 的触发条件 `if not any_visible:` 永不成立 → 另外三个模块再也出不来（症状②）。修法：新增统一仲裁入口 _apply_module_visibility() + 意图标志 _bg_hidden + 模块整窗开关映射 _MODULE_WINDOW_SWITCH，决策优先级为「后台隐藏 > 模块开关关闭 > 显示」；4 处调用点全部收敛为只登记意图、不直接操作窗口。同时修掉标题栏最小化按钮的同类隐患：它原先是裸 for 循环 w.hide() 不登记意图，收敛后改走 _hide_all_windows()，避免「点了最小化却自动复活」。注：core/roll/skill 的模块开关只隐藏内容（窗口与标题栏保留），不参与整窗裁决，保持原有语义。⚠️ 本版**只做显隐收敛，不涉及信号接线**——V2265 的全量接线（另一个问题的根源）已从 V2264 回滚，不在本版范围内。源码备份到 src_backups/<TS>_V2300/。
_BUILD_NO = 2301  # V2301：「3D 效果」标签页控件实时生效。该页共 20 个控件，其中 15 个（投影开关/偏移 X/偏移 Y/不透明度、暗描边开关/暗度、两分面明暗因子、边缘高光带明暗与宽度、底部阴影暗度与高度、小球明暗因子）创建后未接任何通知，改动只在关闭设置对话框后才生效，拖动时主界面毫无反应。本版给这 15 个补上 `self.<控件>.<信号>.connect(self._emit_changed)`。安全前提（逐条核实）：①全部是内联独立创建 `self.xxx = QSpinBox(); ...setValue(...)`，非 _mk_scale_row / _gate_int_row 等工厂函数创建（无隐藏配对绑定）；②审计确认零连接（真孤立），接上后每个控件恰好 1 条通知，不会多重触发。⚠️ 本版**只处理 3D 标签页这 15 个**，不涉及其他任何控件——V2265 因「全量接线」撞上滑块/数字框配对绑定引发信号风暴（设置打架、呼吸灯闪烁），已回滚，不在本版范围内。源码备份到 src_backups/<TS>_V2301/。
_BUILD_NO = 2302  # V2302：尖刺局部光照方向修正——12 根尖刺在圆周上径向朝向（每根 30°），原本 two_tone / edge_band 用世界坐标 (lx,ly)→(rx,ry) 做渐变方向，**只对最上方那根方向正确**，其它编号的亮/暗侧都错位。修法：算出光方向 (-shx,-shy) 在尖刺局部右轴 (px,py)=(-sinθ,cosθ) 上的投影 _local_lit_x，若 _local_lit_x>0（即光落在尖刺局部右）则交换渐变左右颜色 stop，让亮面始终在光来源侧。投影偏移 (shx,shy) **仍用世界坐标**——定向光的世界方向是固定的，所有尖刺的影子朝同一个世界方向落下，是物理正确的（用户最初以为阴影方向也得变，实际上影子方向不该变；只有身体渐变该跟着尖刺旋转）。其他风格（flat / highlight_line / bottom_shadow）不受影响：flat 是纯色；highlight_line 沿尖刺中线对称；bottom_shadow 沿尖刺长轴 tip→root 已经是局部的。源码备份到 src_backups/<TS>_V2302/。
_BUILD_NO = 2303  # V2303：尖刺光照渐变细腻化（在 V2302 方向上再进一步）。V2302 只是判「亮端在尖刺局部左还是右」，渐变轴仍固定在尖刺宽度方向、且是硬边分界。本版改为真正的二维方向渐变：① 渐变方向 = 投影方向的反向（指向光源），光从哪边来哪边就亮；② 渐变跨度 = 尖刺三个顶点在光方向上的投影范围 [pmin,pmax]，   起终点设为 重心+pmin*L 与 重心+pmax*L，保证亮暗覆盖整根尖刺；   光斜照时根部/尖端也会产生明暗差（V2302 做不到）；③ two_tone 保留 V2263 的硬边分界（0.48/0.52 突变，棱锥/钻石的立体感来源），   只让分界的方向与对比强度跟随投影 XY（edge_band 仍为柔和带结构）；④ 新增光照强度因子 _light_t = min(1, sqrt(投影模长/20))，   用它插值玩家设的明暗百分比：模长=0 -> 100（纯色），模长越大对比越强；   即「投影 XY 的多少同时决定渐变的方向和强度」。边界：投影模长 < 0.5（XY 都是 0 或关掉投影）时退化为纯色填充，避免零长度渐变。不改：flat / highlight_line / bottom_shadow（非方向性风格，强度也不随投影缩放）。源码备份到 src_backups/<TS>_V2303/。
_BUILD_NO = 2306  # V2306：修复 V2304 调试数据模式下「全 Buff / Boss 模块空白、核心模块正常」的真因。根因：调试假 buff 的 sid 是 0xD001/D101(53249/53505)，远超玩家为正常游戏设的 status_id_max(常见 3000)，被数值门限整批丢弃；核心模块用 active_buffs 字典不查 sid 门限故正常。修法：render_allbuff / render_bossbuff 在调试态(_DEBUG_ATTR.active)直接跳过所有门限与过滤开关，保证假 buff 一定全显、不受任何门限值影响。同时按用户要求删除 V2305 误加的「📌 自动排布5模块到屏幕中央」按钮及其 handler / _auto_layout_debug_modules 方法（_screen_available_geometry 保留，仍供 _refresh_window_geometries 复用）。源码备份到 src_backups/<TS>_V2306/。
_BUILD_NO = 2307  # V2307：全 Buff / Boss 两个模块顶部新增「统计条」——实时显示 共 N · Debuff · 永续 · 尾声 四项计数（共=通过门限的 buff 总数；Debuff=是否debuff；永续=infinite 标志；尾声=非永续且 remaining/initial < 倒计时尾声警告阈值 warn_thr）。统计条占固定高度（字号比名称小1号），网格整体下移、模块画布高度相应 +统计条高度（render / *_fixed_size / ModuleWindow 几何三处同步），避免文字被窗口底边切掉。源码备份到 src_backups/<TS>_V2307/。
_BUILD_NO = 2312  # V2312：修正 V2311 的方向错选——用户原意是「下拉只要原色 + V2264 的那个」，截图明确指向「斜向两分面（最像 3D 棱锥/钻石）」。V2311 误把 highlight_line（中线高光）当作 V2264 的那个留下，把 two_tone / edge_band / bottom_shadow 全砍；本版修正：① DEFAULT_SETTINGS 的 spike_3d_style 默认回到 "two_tone"（V2264 原默认值）；②恢复 spike_3d_twotone_light=130 / dark=110（V2264 默认值）；③ SettingsDialog 下拉砍到「纯色 + 斜向两分面（V2264 风格）」2 项，删除 highlight_line 的整块 params 页（spike_3d_line_width slider+label）、reset_defaults 残留 2 行、get_settings 1 行、comment 残留；④ _draw_spikes 用 V2264 时代最简两分面算法（沿尖刺左→右方向做 0.48-0.52 硬边渐变，无光向参与）；⑤彻底删 highlight_line 的预计算分支（ridge_c + line_w + spike_3d_line_width），并清空 v23.11 段注释里的 'highlight_line' 提及。源码备份到 src_backups/<TS>_V2312/。
_BUILD_NO = 2313  # V2313：翻滚图标「换图即生效」+ 第 6/7 次样式可选。(1) 第 1~5 次内嵌默认 PNG 换成新图（assets/embedded_roll_icon.png）
#   并新增内置警告图 assets/embedded_roll_warning_icon.png（spec datas 同步打包）。
#   (2) 第 6/7 次新增「样式」下拉：警告三角形（旧行为，默认）/ 图片。选图片时可用内置默认警告图或玩家自定义路径，
#   另有独立「警告图缩放」百分比。
#   (3) 闪光彻底图片无关化：_get_dodge_solid_img 新增 source / cache_tag 两个参数——警告图复用与第 1~5 次
#   完全相同的一条路径（遍历 alpha>128 像素填闪光色 + _flash_scale() 放大脉冲），所以**换任何 PNG 闪光都自动跟上**。
#   (4) BUGFIX：_dodge_solid_cache 此前只在 __init__ 建一次、此后永不失效 → 玩家换 PNG / 改颜色后闪光帧仍画旧图标的
#   实心剪影（"换图片闪光跟不上"的真因）。现在 load_dodge_icon() 每次重载图标都清空缓存。
#   (5) 图片无效或缺失时自动回退成警告三角形，绝不留空白槽位。源码备份到 src_backups/<TS>_V2313/。
_BUILD_NO = 2314  # V2314：全代码冗余彻底排查后的 A~E 级清理（只删死代码 + 修多语言漏接，行为零变化）。
#   【A 级】render_bossbuff 4 处死赋值 + 1 处重复赋值：
#     ① ex_excl（boss_exclude_exclusive）、② ex_mast（boss_exclude_mastery）——自 V2226 起 Boss 的
#        「角色专属 / 专精」过滤已固化为无条件剔除，且 Boss 侧**从未有过**对应 UI 控件
#        （allbuff 侧才有 控件/接线/reset/保存 完整四件套）；两行赋值后从未被读取。
#     ③ g_conflict（boss_gate_check_stack_conflict）——层数矛盾检查已固化，键已被 get_settings() pop，
#        此处读取恒等于兜底 True 且从未使用。
#     ④ g_durmax（boss_gate_duration_max）——真正生效的是 boss_gate_duration_max_with_infinite_exemption。
#     ⑤ 重复的 g_e_durmax 赋值（boss_gate_enabled_duration_max 在同一函数里被读了两次）。
#     两个键（boss_exclude_exclusive / boss_exclude_mastery）同步从 DEFAULT_SETTINGS 移除。
#   【B 级】V2019/V2020 遗留的 6 个 Win32 声明（GetTopWindow / GetWindow / EnumWindows /
#     GetClassNameA / IsIconic / IsWindowVisible）+ _SHELL_CLASS_NAMES 常量——全部只有
#     restype/argtypes 声明、零次实际调用，前后台判定实际只走 get_foreground_pid()。共删 24 行。
#     顺带清掉该交叉验证留下的死参数 enum_state：它在 3 个调用点恒写 "n/a"，
#     并贯穿 _append_focus_log 的签名 / sig 去重判定 / 日志条目 / 文件表头——
#     即 overlay_focus_log.txt 里的 enum= 列永远是 n/a，纯噪声。已整链移除（9 处）。
#   【C 级】12 个真孤儿设置键（剔除 32 个 f-string 动态键模板后才敢判定的）：
#     8 个 V2239 门限合并后的旧键（{allbuff,boss}_gate_{status_id_zero_not_infinite,
#     hide_zero_countdown, remaining_or_initial_negative, infinite_remaining_positive}）、
#     boss_name_keywords / boss_keep_backdrop_when_absent / flash_apply_{allbuff,boss}_submodule。
#     ⚠️ 这 8 个旧键除了 DEFAULT_SETTINGS，还在 get_settings() 与 reset_defaults() 里被
#     「旧 config 兼容」逻辑主动重写为 True —— 必须成对删除，否则退化成野键。共删 27 行。
#   【D 级】i18n.json ui 段删除 168 条真孤儿键（655 → 487）。
#     🔴 判定基准：不能只看「是否被 _tr() 引用」——源码里还有一批内联四语字典
#     （如 {"zh": "选择颜色", ...}）在独立提供翻译，那些键虽未走 _tr 但 UI 确实在用，
#     直接删会误杀。改用「孤儿键 ∩ 源码全部字符串字面量 = ∅」才删，保留 16 条内联字典项。
#     ✅ 顺带修 5 处多语言漏接：未设置（4 处）、按下组合键…（1 处）此前写死中文，
#     切英文/繁中/日文时仍显示中文；现已接回 _tr()（i18n 四语齐备）。
#   【E 级】3 个模块级死常量（_SPECIAL_BUFF_TEMPLATE / _SHELL_CLASS_NAMES /
#     BOSS_EX_STATUS_COMPONENT）；2 处 fm2 = QFontMetrics(f2) —— 每个 buff 卡片每帧都新建
#     一个 QFontMetrics 对象却从不使用（V2073 的 fm2.height() 写法早被 stacks_h 取代），
#     属于实打实的每帧开销；4 处无 _ 前缀的占位变量改成 _。
#     死赋值审计：24 处 → 12 处。剩余 12 处均为 `nm, _t, _full = ...` 类元组解包的
#     约定性丢弃（逐个核验过：_h/_s/_a、_b_list/_b_actor/_b_name 等其余分量都有实际使用）。
#     ⚠️ 另有 1 处**看着像死赋值、实际绝不能删**：main() 里的 `overlay = GBFROverlayQt(...)`。
#     它是该 Qt 对象在 Python 侧**唯一的强引用**（app.setQuitOnLastWindowClosed(False) 且
#     对象无持久 parent），不接收返回值的话 CPython 会立刻回收 → 窗口瞬间消失且无任何报错。
#     已加 `# noqa: keep-alive` 标记，tools/audit_dead_assign.py 会自动跳过，防后人误删。
#   ⚠️ 行为零变化：以上全是「算了但不用」的死代码，删除不影响任何渲染结果，也不动任何 UI。
#      注：get_settings() 里对 boss_gate_check_stack_conflict / boss_gate_duration_max 的 pop 保留
#      （用于清理老 config 文件里的废弃键）。源码备份到 src_backups/2026-09-03_22-12-41_V2314/。
_BUILD_NO = 2319  # V2319：① 收紧运行期输出文件——软件现在只写 3 个文件（ptr_cache.txt / buff_attrs_unknown.json / overlay_settings.json）；新增 ENABLE_BOSS_BUFF_DUMP / ENABLE_FOCUS_LOG 两个总开关（默认关），关闭 boss buff 每秒 dump（last_boss_buffs.json）与前后台焦点诊断日志（overlay_focus_log.txt）的写盘，不再在游戏目录散落多余文件；② 修复 0x94(148) 仍显示成十六进制「0x94」的问题——_attr_for_sid 现在对外部补充文件里「名称为空或仍等于十六进制 ID」的陈旧兜底条目改取内置真实名（仅当内置也缺失才保留），玩家手填的真名仍被尊重，避免 0x94 类「一直显示十六进制」复发。
#   【G 级】4 个零调用的函数（共 63 行）——全是 V2239「灰色固化门限」工厂的残留。
#     SettingsDialog.__init__ 里 allbuff / boss 两个对称作用域各定义了 3 个工厂：
#     _gate_fixed_note（在用）+ _gate_fixed_checkbox / _gate_fixed_double_row（零调用）。
#     V2243 把 ①②③④ 四条门限全部改成「可勾选」后，后两个工厂就再也没人调用。
#   【H 级】4 个「只写不读」的实例属性：
#     ① _dodge_outline_cache —— 翻滚图标「白色勾边光晕」缓存；实际生效的是 _dodge_solid_cache。
#     ② _qm_global —— 存 quest_mgr 的扫描基址，4 处赋值 / 0 处读取。删除时把解包改成
#        `qm, _` / `mgr, _`，保持「函数返回两个值」的接口不变。
#     ③ ui_scale —— recalc_layout 初始化、3 个模块窗口每帧 paintEvent 覆写，
#        但全项目 0 处读取（真正的缩放走 disp_w / disp_h）。删掉后每帧少 3 次属性写。
#     ④ _dl_dialog —— 3 处恒写 None（自更新进度早已改成走标题栏、不弹对话框）。
#   【I 级】55 处日志里的硬编码行号：`swallowed exception @line 4604` 这类数字是当年
#     手工填的，此后文件从 ~6000 行涨到 13800 行 —— **55 条全部对不上真实行号**
#     （偏差 4 ~ 2000+ 行，其中 3 条甚至是 @line 0 的占位符，从没填过）。
#     选择「直接删编号」而不是「改成正确的」：exc_info=True 已输出完整 traceback
#     （带真实文件 / 行号 / 函数名，且指向真正的 raise 点，比 handler 所在行更有用）；
#     而任何硬编码行号都会在下次编辑时立刻重新失效 —— 这是不可维护的设计。
#   【工具链】新增 tools/audit_dead_methods.py（死方法）、audit_dead_attrs.py（死属性）、
#     audit_dup_blocks.py（重复块；自动识别 allbuff↔boss 的约定对称，不误报为可合并）。
#     🔴 修 audit_true_orphans.py 一个会误删在用的翻译的 bug：i18n 孤儿判定原用
#     「raw 源码文本」比对，而源码里 \n 是转义序列、i18n.json 里存的是真换行 →
#     所有含换行的键被 100% 误报成孤儿（实测误报 6 条，全是在用的）。
#     改为「AST 解析后的字符串真实值」比对后误报归零，一个键都没误删。
#   ✅ 复核：死方法 0 / 死属性 0 / 死常量 0 / 未用 import 0 / 孤儿设置键 0 /
#     孤儿 i18n 键 0 / 翻译缺失 0；重复块 5 段（6 行阈值下 30 段）全部是 allbuff↔boss
#     刻意保持的对称结构，可合并候选 0。源码备份到 src_backups/2026-09-04_09-13-51_V2315/。
#   sid=149 (0x95) 世界裂痕 / Fractured World / 龜裂世界 / ワールドクラック
#   sid=146 (0x92) 纯白之境 / Proto-White World / 白堊境界 / 白亜の境界
#   sid=148 (0x94) 混沌转换 / Chaos Shift / 混沌輪迴 / ケイオシフト
#     ↑ V2256 勘误：此处原写作 sid=129 (0x81)，是错的——实测运行期未知清单里出现的是 0x94(148)，
#       而 0x81(129) 在游戏里从未出现过。已把 buff_attrs.json 该条目从 0x81(129) 迁到 0x94(148)。
# V2231 误把它们塞进每个角色的 bucket（i18n.json buffs 是 BUFF_PROFILES，只决定核心模块某角色有哪些专属 buff 及单层/专精属性，不参与命名），既污染角色配表、又根本没解决 boss 显示问题（boss 名字走 buff_attrs.json 的 BUFF_ATTRS）。
# 本版：i18n.json 角色 buffs 删掉 V2231 误加的 87 条（恢复 119 条）；buff_attrs.json 新增 3 条（144->147）。boss 战读到这 3 个 sid 现在显示正式四语名称，不再回落 0x0095/0x0092/0x0094。代码逻辑无改动。
# V2207：修 Boss Buff 模块「所有数值都不能修改、改了不反映到实时 UI」的三重 bug：
#  ① V2202 漏改 which="bl"/"ml" + 存到 self._allbuff_buff_groups 字典，
#     与主控段的 self._buff_groups 同 key 冲突，导致 _refresh_buff_combo 永远只刷主控的 combo，
#     Boss 自己的 combo 永远没内容（用户报告的"没有能选择的下拉菜单"）。
#  ② _WHICH_KEY / _WHICH_OPP 只支持 bl/ml 两个 key，Boss 段无法扩展。
#  ③ DEFAULT_SETTINGS.boss_multi_list 用裸 sid 列表 [7,42]，与主控的 dict 列表格式 [{"sid": 7}] 不一致，
#     _which_list 里 dict(7) 抛 TypeError；且旧版 overlay_settings.json 沿用 [7,42] 格式。
# 修法：_WHICH_KEY/_WHICH_OPP 扩展为 4 个 key（bl/ml/boss_bl/boss_ml，跨组不互斥），
#       _which_list 兼容裸 sid 自动转 dict 列表，Boss 段存到 self._buff_groups 共享字典。
# 验证：4 个 combo 全部 56 项通用 buff，boss_ml 已正确读取默认 [7,42] 转化为 [{"sid":7},{"sid":42}]。
# V2205：subtab 父对象错位；V2204：i18n 日语权威源；V2202/V2201/V2200 = Boss Buff 模块历程。
#                    导致 Boss 模块下完全是空的；6 个 subtab 实际被加到了「主控的全Buff模块」下，
#                    与原 6 个叠加为「同 5 个重复名称 + 配色与文字」= 视觉上 11 个标签条。
#                    用 make_sub_tab(父对象) 反查 7 处误用（6 处 a_sub + 1 处 about_top 误判）后修正。
#                    验证：主控仍是 6 个 subtab（Qt 标签条宽度不够时自动换行 = 5+1 两行显示），
#                    Boss 现在也是 6 个 subtab。
#                    V2204：i18n 日语全部改权威源；V2203/V2202/V2201/V2200 = Boss Buff 模块历程。
#                    V2117：固化四个门限；V2200 = Boss Buff 模块首次新增。
#                    角色专属 buff：从 GBFR Logs 的 lang/*/skillboard.json 文本里
#                    被一对「」(U+300C/U+300D) 括起来的词提取，按「同 key + 出现顺序」
#                    做 zh-TW↔jp 精确配对（zh-CN 版把括号删了，不能直接用，须走 zh-TW 桥）。
#                    共修正 55 条（例：领袖庇佑=カリスマ、漆黑血涌=黒き血潮、转世的恩宠=転世の恩寵）。
#                    专精 87 条：改用 lang/*/skillboard-branches.json（正好 87 条，含官方
#                    覚醒/真髄/極意 三阶名），按 en 名桥接，87/87 全部替换为官方文本。
#                    另修正伽兰查 武夫=荒事 / 莽夫=我武者羅（V2203 时两者写反）。
#                    V2203：i18n 三语→四语（新增日语）；V2202/V2201/V2200 为 Boss Buff 模块。
                       # V2085：① 修 V2084 加 _refresh_memref 时把 def 嵌进 __init__ 函数体（空行不打断）→
                       #              __init__ 末尾 layout.addLayout/addWidget 误归到 _refresh_memref → NameError。
                       #              修法：把"信号/按钮"段移到 _refresh_memref 之前（真正 __init__ 末尾），删冗余 def。
                       #          ② 全 Buff 模块占位提示（_draw_allbuff_placeholder）对齐 _draw_module_backdrop 风格：
                       #              锁定时整个 return（不画背景/边框/文字），未锁定时画 8% 黑底 + 15% 白细边 + 居中文字。
                       #          ③ 修 render_allbuff 之前只读 _out_of_combat_mult 但没应用到绘制的问题——
                       #              加 if self._out_of_combat_mult <= 0.0: return（与 render_core 一致）。
                       # V2097：修「钳蟹的报恩 sid=125 显示∞ 8/8 + 进度条不动」——游戏对该 buff 同时设 infinite=True 和\n#                       真实 remaining=8 initial=8（数据矛盾的伪永续）。V2095 信任游戏 flag 加了 ∞ 符号，\n#                       但 钳蟹本就是 8 秒链接奖励 buff（不是永续），∞ 让进度条不倒计时 = 时间显示错误。\n#                       修法：判定 `infinite=True and 0<remaining<9999 and 0<initial<9999`\n#                       → 视作「数据矛盾的伪永续」，覆写 infinite=False，按有限 buff 走。\n#                       真永续 buff 通常 initial=0/NaN/Inf 或 remaining>600s，不会满足此条件。\n# V2096：修「新 buff 出现时会闪一下」——根因是最小出现持续时间门限(g_e_minappear)的实现缺陷：
#   旧逻辑 `if g_e_minappear and not _was_new` 让刚出现的 1 帧因 _was_new 跳过检查而显示，
#   之后 _was_new=False 且还没满阈值(默认0.1s) → 被门限排除 → 视觉「闪一下」后重新加入。
#   修法：新增 `_buff_ever_shown` 集合记录「本会话出现过(哪怕一帧)的 sid」，出现过即永久放行，
#   直到该 buff 真正从游戏数据消失(底部 _raw_sids 清理)才清除 → 重新出现会重新计时。
#   结果：新 buff 立即显示、中途不再被时间门限丢掉(消除闪烁)；真正瞬时垃圾 buff 显示到自身消失为止。
# V2095：三件事：① 新增门限「ID=0 排除永续」（allbuff_gate_status_id_zero_not_infinite，默认开）——
#                       status_id=0（攻击UP）在游戏里不可能是永续 buff，但 sid=0 槽位残留的垃圾条目
#                       会把 infinite 标志位置 1，被误显示成永续。勾上时把这种条目丢弃。
#                       ② 全 Buff 模块时间显示「真实秒数」——百分比型 buff（如龙人化 sid=29，pct_cap=40）
#                       游戏存的是 0~100 的百分比读数，之前卡片直接显示原始读数（显示 76.7 而不是 30.7 秒）。
#                       现在从 BUFF_PROFILES 合并出 sid→pct_cap 映射（缓存到 self._pct_cap_by_sid），
#                       在 items.append 前把 remaining/initial 折算成真实秒数（核心区早已这样做，全 Buff 漏了）。
#                       ③ 永续 buff 在名称右侧加无限符号 ∞——阶梯缩字/elide 都把 ∞ 计入宽度。
# V2094：修「按出现时间排序根本没生效」——render_allbuff 在 GBFROverlayQt 类里（self == GBFROverlayQt 自己），
#                       但代码用 getattr(self, "ctrl", None) 试图从 ctrl 拿 _buff_first_seen_seq，
#                       而 self.ctrl 在 GBFROverlayQt 上**根本没设置**（只有 SettingsDialog / ModuleWindow 才有）→
#                       ctrl_self=None → seq_map=None → 走防御性回退按 sid 升序排！
#                       结果就是"按出现时间"设置**完全没生效**，玩家看到的"按 ID 升序"实际就是回退路径。
#                       修法：self 已经是 GBFROverlayQt，_buff_first_seen_seq / _buff_next_seq / _buff_gone_since
#                       都在 self 上（4376-4377 行 __init__ 里初始化），直接用 self 即可。
# V2093：「按出现时间」排序加「消失宽限期」——排序逻辑本身正确（ABC→ACB 推演验证通过），
#                       但 seq_map 清理是"一帧读不到就立刻清"，内存读取抖动会让排序号被误清，
#                       buff 下一帧回来就被重新分配到队尾 → 位置跳变，玩家感觉"排序不对"。
#                       修法：记录首次消失时间 _buff_gone_since[sid]，超过 allbuff_seq_gone_grace_sec
#                       （默认 1.0s，已做成 UI 选项"排序号消失宽限"）才真清。
#                       抖动（<1s）保住原排序号；真消失（>1s）排队尾——符合用户"消失后重新排队尾"的原始需求。
# V2092：修「全 Buff 模块抓不到 sid=0 攻击力强化」——根因不在 render_allbuff 主循环（17 个 gate/ex
#                       都有开关且用户已全关），而在数据源 read_exstatus_buffs 里**两处硬编码过滤**没有开关：
#                       ①  —— 0 是合法 sid（攻击力强化），但  = True 被 continue；
#                          写代码的人当时可能以为"0 号槽是 sentinel"，但 GBFR 里 sid=0 是真实 buff。
#                          V2012 时代全 Buff 模块还没加（V2062 才有），没人发现。
#                       ②  —— V2089 我加的永续守护，
#                          对正常 buff（remaining>0.01）不触发，留着。
#                       修法：① 改  —— 只过滤 read_u32 失败返回的 None，
#                          不过滤合法的 0。
# V2091：① 修 About 实时区每秒刷新把滚动条弹回顶——保存原位置/底部标志，刷新后恢复；
#                       ② 全局滚动条加宽到 2.4 倍（系统默认 16px → 38px）—— QSS 写在主对话框，
#                       子 widget 的 QScrollBar 通过 Qt 样式继承自动应用，
#                       设置对话框里所有滚动条（含子页/列表等）统一变宽。
# V2090：修伊德龙人化核心区 buff 空白（真正的根因，V2089 只修了一半）——
#                       V2038 为「能力模块技能名」把 PL2000 加进 GBFR_Character_Skills_Buffs.json 角色库，
#                       _pl_hash_map 因此多了 PL2000 的 hash 映射；龙人态 charid_hash 解析成 "PL2000"，
#                       而 BUFF_PROFILES（i18n.json 的 buffs）只有 PL1900、没有 PL2000
#                       → profile=None → buffs_out 为空 → 核心区空白。
#                       V2012 正常是因为那时角色库里还没有 PL2000（charid 解析不到 → 回退 CHAR_TYPE_TO_PL）。
#                       修法：pl_id 解析不到有效 BUFF_PROFILES 时强制回退 CHAR_TYPE_TO_PL
#                       （0x20 → PL1900）。能力模块零影响（走 ability_hash，不读 pl_id）。
# V2089：修伊德龙人化核心区 buff 空白——read_exstatus_buffs 的 V2068 NaN/Inf 整条
#                       discard 把 2.0.4 后龙人态下紫银之力(sid=60)等永续 buff 全丢了。改回 V2012
#                       行为：NaN/Inf 归零保留（永续 buff 由 infinite=True 守卫保住）。
#                       V2012 与 V2088 核心区循环体本身几乎一样，差异只在 read_exstatus_buffs。
#                       V2068 注释当时说"核心模块不受影响"——但 V2012 时代游戏还没改字段，
#                       2.0.4 更新后触发这个隐藏回归。
# V2088：修"全 Buff 模块疯狂闪烁"——两个 bug：
                       #   ① V2087 的 `_seen[sid] = _now` 是**无条件刷新**，每帧都把"首次观测时间"
                       #      改写成当前时间 → 已知 buff 的 `_now - _seen[sid]` 永远≈0 → 每帧被 minappear
                       #      丢一次 → 帧1显示/帧2丢/帧3显示... = 疯狂闪烁。
                       #      修法：只在首次记录（`if _was_new: _seen[sid] = _now`），之后不再刷新。
                       #   ② 循环外清理（_seen 与排序 seq_map）用**过滤后**的 items 判断"谁消失了"——
                       #      被其他门限（minrem/mininit/nan/ex_*）丢的 buff 不在 items → 每帧被判"消失"
                       #      → 计时/排序号反复重置 → 加剧震荡。
                       #      修法：改用**原始数据源** `buffs.keys()` 判断，只有游戏里真的没了才重置。
                       #   ③ 顺带清理用户明令禁止的探针代码（红线：分发工具不带诊断）：
                       #      移除 allbuff_debug.log 三处写盘（_load_buff_attrs 两条 + render_allbuff
                       #      头尾各一块）+ `drop_reasons` / `attr_none_sids` 全部诊断残留。
                       # V2087：修 V2084 加的"最小出现持续时间"allbuff_gate_min_appearance_time 门限逻辑 bug——
                       #              原版：`_seen[sid] = _now` 后立刻判 `_now - _seen[sid] < 阈值`
                       #                   → 第一次见到的任何 buff 都因 `_now - _now = 0 < 阈值` 被丢
                       #                   → 表现："启动后全 Buff 模块空白，必须手动开关一次才恢复"
                       #                   （开 → 关的循环里会触发 _emit_changed → save_settings → allbuff_win.show()）
                       #              修法：用 _was_new 标记"刚被记录的 sid"，minappear 仅对已知 buff 生效。
                       # V2086：修 V2085 删"信号/按钮"段时把真 retranslate_ui 的 def 也一起删了，
                       #              导致剩下那段"按语言刷文本"的代码就地成了孤儿方法（被错误命名为 _connect_live_signals），
                       #              启动设置弹窗调 self.retranslate_ui() → AttributeError。
                       #              修法：把那段错误命名的 def 改名回 retranslate_ui(self, *_)。
                       #              （真正的 _connect_live_signals 在 3437 行——这个定义不受影响）
                       # V2084：① 修缮「非战斗时隐藏整个 UI」文本——列入「全 Buff 模块」（之前漏了），
                       #              改用 _tr 三语（zh_tw/en 同步 i18n.json）。② About 页新增「重要内存地址与数据」
                       #              card：上半静态偏移速查（与 skill 同步），下半实时值（QTimer 每 1 秒刷新，
                       #              从 self.ctrl 读 pptr/base/quest_mgr/角色名/ID/状态/专精/翻滚/技能数/全 Buff 数）。
                       #              ③ 全 Buff 模块门限新加「最小出现持续时间」allbuff_gate_min_appearance_time
                       #              （默认 0.1s）——防瞬时 buff 闪现即逝被误判，逻辑：记录每个 sid 首次观测时间，
                       #              _now - first_seen[sid] < 阈值则丢，消失的 sid 在循环外清理重置。
                       #              主程序仍保持零扫描零诊断（memref 在用户主动打开 About 时才跑）。
                       # V2079 CSS border 渲染成方块），改用 QHBoxLayout 套独立 QLabel "▼" 字符。QLabel 是普通
                       # widget，100% 可靠。QComboBox 自身 setStyleSheet 去掉右上右下的圆角让 ▼ Label 接管右侧视觉。
                       # 同时诊断日志加入 buff_attrs_len / 命中路径，便于后续核对。若 BUFF_ATTRS 仍为空，日志会记录候选路径。
# V2040：死代码清理（P0+P1）。删除未使用的函数/常量/属性/局部/导入，以及 DEFAULT_SETTINGS 中
#       从未被读取的死键（bg_color/bg_color_opacity/arc_color_opacity/icon_color_opacity/
#       classmech_window_x|y|scale_percent/ex_status_offset/show_skill_cd/skill_cd_*_opacity/
#       supersample/update_mirror_url/flash_dodge_outline 共 15 个）。不含任何功能改动，行为不变。
#       保留项：overlay 实例引用（保对象生命周期）、_draw_title_bar 内的 th（绘制中使用）、
#       _btn_*_rect_win 命中矩形（活代码）。
# V2039：颜色选择对话框的 16 格「自定义颜色」持久化。
#       之前 QColorDialog.setCustomColor() 在进程退出后丢失，用户辛辛苦苦调好的色下次打开
#       全部归零。改法：pick_color() 入口前从 settings['custom_palette'] 把 16 个 hex
#       还原到 QColorDialog 全局 setCustomColor(i, ...)，关闭后立即用 customCount + customColor(i)
#       循环读 16 格回写到 settings 并 save_settings；reset_defaults 同步清空。
#       注意：PySide6 没有 customColors() 这种列表版 getter，只有 customCount + customColor(i) 单格读。
#       「Add to Custom Colors 总覆盖第一个」「点格子立刻被覆盖」仍是 Windows 系统 ColorDialog
#       内置行为无法定制，要彻底改需要重写一个内部 ColorPicker 对话框，按本版范围暂不做。
# V2038：真正修伊德龙人化形态下能力模块（skill_cd 菱形）的能力名显示错误。
#       根因（经 GBFR Logs 的 lang/zh-CN/abilities.json 核实）：伊德龙人化是独立的 PL2000，
#             其能力与 PL1900 人形态【不是同一套】——PL2000 有专属 AB_PL2000_01~05（圣迹再临/
#             天谴/永无止境/乐园之噬/神愿之力），而人形态是 AB_PL1900_01~08（含无缚之斩/赎罪/末日形态）。
#             龙人化 actor 的 +ABILITY_HASH_OFFSET 存的是 PL2000 的 hash，但项目数据库
#             GBFR_Character_Skills_Buffs.json 原先没收录 PL2000 → _ab_hash_map 命中不到 → 显示空。
#             V2036/V2037 误把龙人化技能「复用」成 PL1900 人形态的技能名，是错误做法。
#       改法：把 PL2000 的真实技能（hash→三语名）正式收录进项目的 GBFR_Character_Skills_Buffs.json，
#             让 _ab_hash_map 按 hash 直接命中龙人化的真实技能名；并移除 V2037 误加的
#             PL1900→PL1900 / PL2000→PL1900 技能借用（避免显示错误技能名）。核心 Buff 区
#             PL2000 仍与 PL1900 共用，那是 BUFF_PROFILES 的逻辑，不受影响。
# 改动：
#  ① 完全去掉「显示启动画面」（启动条）开关——不再以 splash 形式启动：
#     删 class StartupSplash（约 80 行），同步删除设置面板「核心检测模块」内
#     「显示启动画面」复选框以及 DEFAULT_SETTINGS["show_startup_splash"] / load_settings 迁移
#     / show_startup_splash_chk 三处触点；main() 直接 `GBFROverlayQt(progress_cb=None)`
#     启动，无需任何 qlineargradient 启动卡片。
#  ② 「EXE 同步列表」整行新增「启用 EXE 同步列表」勾选框（默认开启）：
#     设置 → 全局 → EXE 同步 卡片顶部；玩家可一键禁用全部 EXE 同步。
#     保存到 settings["enable_sync_exe_list"]；_sync_exe_list_at_startup 读取：
#     关掉时直接 return，不起后台线程，不再扫描与 start 各 EXE。
#  ③ 角色 Buff 顺位与专精门控三列（觉醒 / 真谛 / 秘义）列宽从 86~100
#     放大 1.5 倍 → 129~150；同时影响列标题（line 1805）和每行 checkbox（line 1931）。
#  ④ i18n.json：删除「显示启动画面」key（zh/zh_tw/en 三语），新增「启用 EXE 同步列表」三语。
#  ⑤ schema 94 不变；仅补丁性改动（功能清理 + 加一个开关 + 列宽调整）。
                       # V2034 改动：把「尖刺」与「装饰小球」的显示/隐藏彻底拆成两个互不耦合的独立开关——
                       #             原 V2033 的「隐藏尖刺与装饰小球」(hide_spikes_and_beads) +
                       #             「仅隐藏上面的尖刺」(hide_spikes_only) 两个 hide 选项，组合语义绕且互相耦合，
                       #             用户反馈「不如直接给两个独立开关」。本版改为：
                       #             ① DEFAULT_SETTINGS 删 "hide_spikes_and_beads"/"hide_spikes_only"，
                       #                加 "show_spikes": True / "show_bead": True（默认都显示）。
                       #             ② 设置面板「尖刺与圆环」卡片下两个复选框：
                       #                「显示尖刺（三角本体）」(show_spikes_chk) / 「显示装饰小球（尖刺顶端圆点）」(show_bead_chk)。
                       #             ③ 渲染层彻底解耦：
                       #                - 删 _hide_spikes()，改 _spike_drawn()（返回 show_spikes）/ _bead_drawn()（返回 show_bead）；
                       #                - _effective_opacity 对 spike_color_normal/lv7 在 show_spikes=False 时强制透明度 0
                       #                  （尖刺三角本体+外勾边+闪光整体消失）；装饰小球单独走 _bead_drawn() 判定，
                       #                  不依赖 _spike_drawn()。
                       #                - _draw_spikes 不再早 return：show_spikes=False 时仍可能要画装饰小球，循环内
                       #                  按 per-spike：不画三角则仅当 show_bead 画小球；正常分支也按 show_bead 决定画不画小球。
                       #                - _draw_indicator_outer_outline 外勾边：尖刺三角勾边受 _spike_drawn() 控制、
                       #                  装饰小球勾边受 _bead_drawn() 控制，两者独立。
                       #             ④ 组合效果（4 种）：都勾（默认，全显示）/ 只勾装饰（仅小球）/ 只勾尖刺（仅三角）/
                       #                都不勾（光秃秃圆环+倒计时+文字）——用户完全自由组合，不再受 hide 组合语义束缚。
                       #             ⑤ 画布下沿仅在 show_spikes 时额外预留 spike_len（dragon_bottom_y），不压缩圆环空间。
                       #             ⑥ load_settings 迁移：旧 hide_spikes_and_beads=True → 两者都 False；
                       #                hide_spikes_only=True → show_spikes=False / show_bead=True；都没勾 → 都 True。
                       #             schema 94 不变。
                       # V2032 改动：撤销 V2031 / V2027 / V2026 三次引入的 _any_active_buff_stacks() 错用——
                       #             ① spike_hidden 判定（行 4226）：not self._any_active_buff_stacks() → not self.active_buffs
                       #             ② render_core 外层分支（行 4255）：if self.active_buffs and self._any_active_buff_stacks():
                       #                → if self.active_buffs:
                       #             ③ _build_titlebar_status_text 标题栏 buff 名段（行 5028）：if not self._any_active_buff_stacks()
                       #                → if not self.active_buffs:
                       #             三处统一恢复『仅看 active_buffs 列表本身、忽略 stacks 数值』的 V2025 原始语义——
                       #             玩家原意：active_buffs 真为空（没有任何 buff）才考虑整圈隐；『已配满 buff 但游戏
                       #             实际 stacks=0（buff 还没激活 / 计数）』应仍正常显示圆环 + spike + 倒计时 + buff 名。
                       #             V2026 把 _any_active_buff_stacks() 错用到 spike 隐藏判定，导致『配置满 buff 但
                       #             stacks=0』时整圈按 SPIKE_HIDDEN_KEYS（circle/arc/text/timer 全在内）退到 0%
                       #             不可见、只剩 _draw_buff_name 的 buff 名标签飘着；V2027 想把它和标题栏 buff 名段
                       #             对齐、结果用户报怨『buff 名段消失了』；V2031 想把外层分支也加 _any 判定、结果
                       #             用户报怨『游戏画面里什么都没了』——三次错改一脉相承，全部撤回。本版后：
                       #             『隐藏尖刺与装饰小球』选项只控制 spike+bead 绘制路径（_draw_spikes 早 return），
                       #             不影响圆环 + 倒计时 + 文字；『无 buff 时隐藏尖刺圆模块』选项仅在 active_buffs
                       #             为空时让整圈按 SPIKE_HIDDEN_KEYS 退 0% 隐形，正符合选项设计意图。
                       #             circle_pad_title QSpinBox 允许负值的 V2031 改动保留。
                       #             schema 94 不变。
                       # V2031 改动（被 V2032 部分撤销）：circle_pad_title QSpinBox setRange(0, 999) → setRange(-999, 999)
                       #             允许负值——其余改动见 V2032。
                       # V2030 改动：清理 3 处 UI 残留（按用户截图反馈）：
                       #             ① 删除设置面板「更新检测版本地址」输入框下方那段长说明文字
                       #                （V303 起的 url_hint QLabel）——输入框 placeholder 已足够提示，
                       #                玩家不需要在这里再读一遍"为什么走 release CDN"。
                       #             ② 删除死函数 _open_config_dir（"打开配置 & 日志目录"）——
                       #                源码中除自身外零引用，托盘菜单从未 addAction 注册，
                       #                玩家根本不知道这个入口在哪，索性彻底删干净。
                       #             ③ 顺手清掉 i18n.json 里只被 _open_config_dir 引用的孤儿键「打开失败」
                       #                （「设置打开失败」键 5878 行仍被设置对话框使用，保留）。
                       #             「标题→圆间距」（circle_pad_title）控件保留——
                       #             它是活跃渲染参数，参与 base_cy = TITLE_BAR_H + circle_pad_title + circle_r + spike_top_pad
                       #             的圆环画布 Y 位置计算，并非无用功能。
                       #             schema 94 不变。
                       # V2029 改动：清理审计报告列出的垃圾——删 _detect_build_no 死函数（line 84-99）+
                       #               删 6 个未引用函数/类（find_pid / resolve_player_ptr / read_raw_buffs /
                       #               get_topmost_real_window_pid / enum_game_window_state / BuffOrderGroup）+
                       #               删 4 个无用 import（QAction/QPolygonF/QAbstractSpinBox/QDialogButtonBox）+
                       #               修 2 处 _tr() i18n 键缺失（2859 行 tooltip 整串、6528 行 "打开失败"）。
                       #               schema 94 不变。
                       # V2028 改动：第 6/7 次翻滚的警告牌（warning_mode）原本只有放大脉冲、无亮度闪烁；
                       #               现在在红边黄底三角之上叠加一层 flash_color 的「警告牌形状（圆角三角）」
                       #               透明度脉冲闪烁（flash_progress 越大越亮、随时间消退），外形始终是警告牌、
                       #               绝不用白色方块遮挡。复用 flash_apply_dodge / flash_color / flash_scale /
                       #               flash_duration_ms，不新增设置。schema 94 不变。
                       # V2026 改动：「无buff时隐藏尖刺圆模块」选项在「已配置显示但实际层数为0」时也生效。
                       #               之前判 `len(active_buffs) == 0`，但当用户把某个 buff 的三阶专精全勾后，
                       #               该 buff 即使实际 stacks=0 也会出现在 active_buffs 里 → 判定永远 False →
                       #               `_render_buff_ui` 仍按常规被调用 → 尖刺本体不画但圆环 `circle_color_normal` 满不透明度被
                       #               `_draw_circle` 画出来 → 用户看到「圆圈仍在那」的现象。
                       #               修复：判定改为 `not _any_active_buff_stacks()`（配置 OR 实际层数任一为正即保留），
                       #               与玩家对「无 buff」的直觉（无任何 buff 实际激活）一致。
                       #               schema 94 不变。
                       # V2025 改动（核心 bug 修复）
                       # V2025 改动（核心 bug 修复）：「随游戏前后台自动显隐」会把
                       #               点击 / 拖拽 / 缩放 overlay 自身模块误判成「游戏到后台」→ 整窗隐藏，
                       #               导致用户根本没法调模块（一点模块就消失）。
                       #               根因：_game_is_foreground 只认游戏 PID（self.pid 存的是游戏 PID），
                       #               工具自身进程 (os.getpid()) 不在集合里 → 前台变工具自身时被算成后台。
                       #               修法：① 把工具自身进程也并入「前台」集合（点/拖模块时保持可见）；
                       #                     ② 拖拽/缩放进行中置 _interacting 锁，焦点同步直接跳过、绝不隐藏。
                       #               schema 94 不变。
                       # V2024 改动：① 修复 Windows 区域设为「香港（繁体）」时
                       #               设置对话框 + 全部 overlay 窗口中文渲染成 □ 方框——
                       #               Qt 在 Windows 上不读系统亚洲字符回退表，
                       #               21 处 QFont("Segoe UI", ...) 都没有 CJK fallback；
                       #               启动时按优先级扫 QFontDatabase.families()，
                       #               对 Segoe UI 调用 QFont.insertSubstitution() 注册 CJK 替代，
                       #               所有 QFont 调用无需改动。
                       #             ② schema 94 不变；与隐显/焦点逻辑无关。
                       # V2023 改动：① 去掉 V2022 的 600ms 防抖，恢复 V2021 的「边沿触发立即动作」节奏；
                       #             ② 非战斗状态（_ooc_content_hidden=True）下也让前后台隐显生效
                       #               （V2022 之前一律 early return 等于关了，非战斗时 alt-tab 完全没反应）。
                       # schema 94 不变（同焦点/隐显模块）。
#   ① V2017 起的 _update_tray_menu 菜单 4 项 bug：show_all_action.connect(self._show_all)
#      但 def 只有 _show_all_windows——connect 时 AttributeError 中断整个函数，
#      后 5-9 项菜单（重置所有窗口 / 检查更新 / 打开配置 / 关于 / 退出）从未被 addAction。
#      现在补一个 def _show_all(self): self._show_all_windows() 当作 wrapping 彻底修复。
#   ② 同时把 _game_is_foreground 的判定收紧：仅用 GetForegroundWindow.PID == game_pids 主信号，
#      移除 IsIconic 交叉验证（V2020 那套在桌面切换时偶发判定不出=永不 hide）。
APP_VERSION = ("%d.%02d" % (_BUILD_NO // 100, _BUILD_NO % 100)) if _BUILD_NO is not None else "7.00"
APP_TITLE = ("GBFR_CooldownIndicator_V%d" % _BUILD_NO) if _BUILD_NO is not None else "GBFR_CooldownIndicator_V700"
SETTINGS_SCHEMA_VERSION = 94

# ============================ 三语翻译表（提前定义，供 UI 组件全局使用）===========================
from i18n_loader import UI_TRANS, CHAR_NAMES as I18N_CHARS   # V2203：CHAR_NAMES 含四语角色名
ZH_TO_EN = {k: v.get("en", k) for k, v in UI_TRANS.items()}
ZH_TO_TW = {k: v.get("zh_tw", k) for k, v in UI_TRANS.items()}
ZH_TO_JA = {k: v.get("ja", k) for k, v in UI_TRANS.items()}   # V2203：日语

def _tr(zh, lang=None):
    """按当前语言返回翻译；lang 缺省时取 retranslate_ui 维护的全局语言。"""
    if lang is None:
        lang = _CURRENT_LANG
    if lang == "en":
        return ZH_TO_EN.get(zh, zh)
    if lang == "zh_tw":
        return ZH_TO_TW.get(zh, zh)
    if lang == "ja":
        return ZH_TO_JA.get(zh, zh)
    return zh

_CURRENT_LANG = "zh"
AUTHOR_TAG = "@Bilibili/Dangoooooo"

class _UpdateCancelled(Exception):
    """用户在下载进度框点了「取消」。"""
    pass

def _qt_sync_get(url, timeout_ms=15000, on_chunk=None, on_total=None, abort_check=None):
    """同步 HTTP GET，基于 Qt QNetworkAccessManager。
    设计用于在**工作线程**里调用：内部起一个本地 QEventLoop 把异步请求转同步。
    - on_chunk(bytes): 可选，流式回调（用于边下边写文件 + 进度）。提供时返回 (None, total, err)。
    - abort_check(): 可选，返回 True 时中止请求（用于取消下载）。
    - 返回 (data: bytes|None, total: int, err: str|None)。
    这是 V406/V407 那一代把更新网络栈从 urllib 换成 Qt 的实现（4.xx 线终态），
    比 urllib 在国内部署更稳（同源走 Qt 事件循环，避免 urllib 的 getaddrinfo 类阻塞问题）。
    """
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    try:
        manager = QNetworkAccessManager()
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.UserAgentHeader, "GBFR-Overlay-Updater")
        # 强制 HTTP/1.1：国内不挂梯子时 GitHub CDN 的 HTTP/2 不稳定（易 protocol error / 极慢）
        try:
            req.setAttribute(QNetworkRequest.Http2AllowedAttribute, False)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        try:
            if hasattr(QNetworkRequest, "FollowRedirectsAttribute"):
                req.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        reply = manager.get(req)
        loop = QEventLoop()
        result = {"ok": False, "data": bytearray(), "err": "timeout", "total": 0}

        def on_meta():
            try:
                v = reply.header(QNetworkRequest.ContentLengthHeader)
                tv = int(v) if v is not None else 0
            except Exception:
                tv = 0
            result["total"] = tv
            if on_total is not None:
                on_total(tv)

        reply.metaDataChanged.connect(on_meta)

        def on_finished():
            if reply.error() == QNetworkReply.NoError:
                if on_chunk is None:
                    result["data"] = bytearray(reply.readAll().data())
                result["ok"] = True
            else:
                result["err"] = reply.errorString()
            loop.quit()

        reply.finished.connect(on_finished)

        if on_chunk is not None:
            def on_ready():
                chunk = reply.readAll().data()
                if chunk:
                    on_chunk(chunk)
            reply.readyRead.connect(on_ready)

        # 取消轮询
        if abort_check is not None:
            at = QTimer()
            at.setSingleShot(False)
            at.timeout.connect(
                lambda: reply.abort() if (abort_check() and reply.isRunning()) else None)
            at.start(150)
        # 超时保护（兜底，防止永久挂起）
        tt = QTimer()
        tt.setSingleShot(True)
        tt.timeout.connect(lambda: reply.abort() if reply.isRunning() else None)
        tt.start(timeout_ms + 10000)
        loop.exec()
        if abort_check is not None:
            try:
                at.stop()
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        tt.stop()
        if not result["ok"]:
            return (result["data"] if on_chunk is None else None), result["total"], result["err"]
        return (bytes(result["data"]) if on_chunk is None else None), result["total"], None
    except Exception as e:  # 含 QtNetwork 导入失败等
        return None, 0, str(e)

def pick_lang_text(value, lang="zh"):
    """按语言选取多语言文本：value 为 dict 时依次取 lang → zh → 第一个非空值；为 str 时原样返回。"""
    if isinstance(value, dict):
        for key in (lang, "zh"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
        for v in value.values():
            if isinstance(v, str) and v.strip():
                return v
        return ""
    if isinstance(value, str):
        return value
    return ""

# ============================ EXE 同步（全局设置：启动时按路径共同启动，不监视、不杀进程）============================
def _is_exe_running(exe_path):
    """轻量检测：指定 exe 是否已有进程在运行（仅按文件名匹配，不查完整路径）。
    使用 Toolhelp32 快照只读 szExeFile（文件名），全程 <50ms，不阻塞 Qt 事件循环。
    注意：复用全局 PROCESSENTRY32 类（与 find_pid 共用），绝不重新定义或设置 argtypes——
    否则会污染 kernel32 全局函数签名，导致 find_pid() 每次调用都抛
    'expected LP_PROCESSENTRY32 instance instead of pointer to PROCESSENTRY32'。"""
    if not IS_WINDOWS or not exe_path:
        return False
    try:
        target_name = os.path.basename(exe_path).lower()
        TH32CS_SNAPPROCESS = 0x00000002

        h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if int(h_snap) in (0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            return False
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        found = False
        if kernel32.Process32First(h_snap, ctypes.byref(pe)):
            while True:
                if pe.th32ProcessID and pe.szExeFile:
                    # szExeFile 是 ctypes 字节数组，必须 decode 成 str 再比较
                    name = pe.szExeFile.decode("ascii", "ignore").lower()
                    if name == target_name:
                        found = True
                        break
                if not kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                    break
        kernel32.CloseHandle(h_snap)
        return found
    except Exception:
        return False

def _launch_exe(path, cwd=None):
    """以完全独立方式启动 exe（效果等同双击 .lnk）。
    用 os.startfile（底层 ShellExecute）以指定「起始位置（工作目录）」启动：
      - 子进程工作目录 = 指定目录（与 .lnk「起始位置」完全一致）；
      - 若 exe 需要提权，ShellExecute 会正常弹出 UAC（subprocess.CreateProcess 在需提权时
        会直接失败 WinError 740，导致启动不了，因此绝不用 subprocess 启动外部 exe）。
    未指定工作目录时固定在 exe 自身所在目录（等同双击 .lnk 的起始位置 = exe 同目录）。
    不继承本程序的控制台 / IO 句柄，不阻塞、不监视、绝不杀进程。"""
    try:
        if cwd:
            os.startfile(path, cwd=cwd)
        else:
            os.startfile(path)
        return True
    except Exception:
        return False

def _run_sync_exe_list(raw_list):
    """启动时共同启动：列表中的 exe 若未运行则启动；已运行则跳过（绝不杀进程、不监视）。
    每条可附加「||工作目录」指定起始位置（等同 .lnk 的起始位置字段，可省略）；
    省略「||工作目录」时，默认固定在 exe 自身所在目录（等同双击 .lnk 的起始位置 = exe 同目录）。
    在后台 daemon 线程中执行（见 _sync_exe_list_at_startup），绝不阻塞 Qt 主线程。"""
    if not raw_list or not raw_list.strip():
        return
    parts = raw_list.replace("；", ";").replace("\r", ";").replace("\n", ";").split(";")
    for item in parts:
        item = item.strip().strip('"').strip("'")
        if not item:
            continue
        # 拆分 exe 路径与可选工作目录：格式  exe路径||工作目录
        exe_path = item
        cwd = None
        if "||" in item:
            exe_path, cwd = item.split("||", 1)
            exe_path = exe_path.strip().strip('"').strip("'")
            cwd = cwd.strip().strip('"').strip("'")
        # 兜底：未指定工作目录时，固定在 exe 自身所在目录（等同 .lnk 起始位置 = exe 同目录）
        if not cwd:
            cwd = os.path.dirname(exe_path) or None
        if not exe_path or not os.path.isfile(exe_path):
            continue
        if not _is_exe_running(exe_path):
            _launch_exe(exe_path, cwd)

def _load_local_changelog(lang="zh"):
    """读取随 exe 打包的本地 version.json 更新日志（未检查更新/检查失败时「关于」页兜底显示）。"""
    for base in (_BUNDLE_DIR, EXE_DIR):
        p = os.path.join(base, "version.json")
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                return pick_lang_text(d.get("changelog", ""), lang)
        except Exception:
            continue
    return ""

def _has_cjk(text: str) -> bool:
    """检测文本是否包含 CJK（中日韩）统一表意文字。用于防止远端 version.json 的 en 字段泄露中文。"""
    import re as _re
    return bool(_re.search(r'[\u4e00-\u9fff]', text))

def _safe_remote_changelog(remote_text: str, lang: str, local_fallback: str = "") -> str:
    """安全取远端 changelog：若当前语言为 en 但远端文本含 CJK（历史遗留脏数据），降级回本地干净版本。
    其他语言或干净的远端文本原样返回。"""
    if not remote_text or not remote_text.strip():
        return local_fallback
    if lang == "en" and _has_cjk(remote_text):
        return local_fallback
    return remote_text

def _app_title(lang="zh"):
    return APP_TITLE

# ============================ Game memory layer ============================
PROCESS_NAME = "granblue_fantasy_relink.exe"
MODULE_NAME = "granblue_fantasy_relink.exe"

AOB_HEX = (
    "488Bxxxxxxxxxx4885xx74xx488BxxFFxxxxxxxxxx4885xx74xx"
    "488Bxxxx488Bxxxx488Bxx488DxxxxxxFFxxxxxxxxxxEBxx"
    "C5xxxxxxxxxxxxxxC5xxxxxxxxxx488Bxx488D"
)
INSTR_END = 0x07
DISP_OFF = 0x03

CHAR_PTR_OFF = 0x00
FIELD_DODGE = 0x5788
FIELD_CHAR_TYPE = 0x1FD

# 任务管理器全局指针定位（relink-logs 逆向，v2.0.2/2.0.3 同源）。
# 调用 OnLoadQuestState(FUN_14063ecb0) 的指令形如：
#   48 8b 0d [disp32]   mov rcx,[rip+disp]   ; rcx = 任务管理器全局指针
#   e8 [rel32]          call FUN_14063ecb0
#   函数入口紧接着 c5 fb 12 ... (AVX 开头)
# 扫描到该调用点后，从 48 8b 0d 后 4 字节取 rip-relative disp，
# 全局绝对地址 = hit + 7 + disp32。任务管理器实例本身的偏移：
#   mgr+0x210 -> flow 对象指针（任务期间非0，城镇/菜单被销毁为0）。
QUEST_MGR_AOB = (
    "48 8b 0d xx xx xx xx e8 xx xx xx xx c5 fb 12 "
    "xx xx xx xx xx c5 f8 11 xx xx xx xx xx c5 f8 11 "
    "xx xx xx xx xx c7 87"
)
QUEST_FLOW_OFFSET = 0x210  # mgr+0x210 -> flow 对象指针（!=0 表示在任务中）

# 训练场识别：quest_mgr+0xB20 与 +0xB28 两个 u32 计时器/计数器
# 小镇/甲板/花都等非战斗地点恒为 0；进入训练场（自由战斗/木桩）后变为非零。
# 判定：非任务态(flow==0) 且任一计时器非零 → 训练场。
QUEST_TRAINING_TIMER_OFFSETS = (0xB20, 0xB28)

# quest_mgr 全局指针变量地址 与 player 全局指针变量地址(pptr) 的相对偏移。
# 二者同属 game.exe 同一模块，相减即与 ASLR 无关的相对距离。
# V2082：游戏 2.0.4 后旧值 0xc1dfd0 漂移；用独立工具 GBFR_OffsetFinder_V2 在 2.0.4 下实测出新值 0xC1E030。
# 实测见 src_backups/2026-08-29_09-55-*/V2082_qm_delta_0xC1E030/。
QM_DELTA = 0xC1E030

# 角色类型字节值 → 名称 (zh / en)
# 来源: CE实测 [玩家]+0x1FD 字节值；这里按十六进制记录
# (简中, 繁中, English, 日本語) — 来源: GBFR 官方数据（日语取自游戏内 text_chara.msg 原文）
CHAR_TYPE_NAMES = {
    0x07: ("菲莉", "菲莉", "Ferry", "フェリ"),
    0x11: ("齐格飞", "齊格菲", "Siegfried", "ジークフリート"),
    0x24: ("伽兰查", "伽藍薩", "Gallanza", "ガランツァ"),
    0x08: ("兰斯洛特", "蘭斯洛特", "Lancelot", "ランスロット"),
    0x19: ("伊德", "伊度", "Id", "イド"),
    0x23: ("索恩", "蘇恩", "Tweyen", "ソーン"),
    0x17: ("巴萨拉卡", "巴薩拉加", "Vaseraga", "バザラガ"),
    0x16: ("塞达", "瑟塔", "Zeta", "ゼタ"),
    0x18: ("卡莉奥丝特罗", "卡莉歐斯托蘿", "Cagliostro", "カリオストロ"),
    0x10: ("珀西瓦尔", "帕西瓦爾", "Percival", "パーシヴァル"),
    0x20: ("伊德(龙人化)", "伊度(龍人化)", "Id (Dragon)", "イド(竜人化)"),
    0x22: ("希耶提", "席耶提", "Seofon", "シエテ"),
}

# 0x1FD 角色类型字节 → 官方 PL ID（来源：GBFR_Character_Skills_Buffs.json 的 角色ID 字段）
# 用于把 charid 识别与旧 0x1FD 体系桥接，使 BUFF_PROFILES 也能按 pl_id 索引。
CHAR_TYPE_TO_PL = {
    0x07: "PL0700",  # 菲莉
    0x11: "PL1100",  # 齐格飞
    0x24: "PL2400",  # 伽兰查
    0x08: "PL0800",  # 兰斯洛特
    0x19: "PL1900",  # 伊德
    0x23: "PL2300",  # 索恩
    0x17: "PL1700",  # 巴萨拉卡
    0x16: "PL1600",  # 塞达
    0x18: "PL1800",  # 卡莉奥丝特罗
    0x10: "PL1000",  # 珀西瓦尔
    0x20: "PL1900",  # 伊德(龙人化)
    0x22: "PL2200",  # 希耶提
}

# 共享技能组的「主控人物 → 规范角色」回退映射：
# 姬塔(PL0100) 与 古兰(PL0000) 共用一套技能（PL0100 借用 PL0000）。
# 注意：伊德龙人化(PL2000) 的能力模块与人形态(PL1900) 是【两套不同】技能——
#       PL2000 的技能已在 GBFR_Character_Skills_Buffs.json 单独收录(AB_PL2000_01~05 及 _CG)，
#       按 ability_hash 直接命中，故此处不再把 PL2000 回退到 PL1900（否则会显示错误技能名）。
#       （核心 Buff 区 PL2000 仍与 PL1900 共用，那是 BUFF_PROFILES 的逻辑，与此处无关。）
PL_SKILL_FALLBACK = {"PL0100": "PL0000"}

# 语言 → CHAR_TYPE_NAMES 元组索引
LANG_NAME_IDX = {"zh": 0, "zh_tw": 1, "en": 2, "ja": 3}   # V2203：日语

def _char_name(char_type, lang="zh"):
    """按语言获取角色名。"""
    pair = CHAR_TYPE_NAMES.get(char_type)
    if not pair:
        return f"0x{char_type:02X}"
    return pair[LANG_NAME_IDX.get(lang, 0)]

def _resolve_char(charid_hash, char_type=0, lang="zh"):
    """角色识别：优先用 charid hash（actor+0x1AB40）直认，覆盖全部 29 角色；
    未命中则回退到 0x1FD 字节（CHAR_TYPE_NAMES，12 角色）。
    返回 (name, pl_id)；pl_id 可能为 None。"""
    pl = _pl_hash_map.get(charid_hash) if charid_hash else None
    if pl and pl in _char_db:
        info = _char_db[pl]
        if lang == "en":
            return info.get("name_en", pl), pl
        if lang == "zh_tw":
            return info.get("name_tw", info.get("name_zh", pl)), pl
        if lang == "ja":
            return info.get("name_ja", info.get("name_zh", pl)), pl
        return info.get("name_zh", pl), pl
    # 回退：0x1FD 字节
    return _char_name(char_type, lang), CHAR_TYPE_TO_PL.get(char_type)

def _buff_name(buff, lang="zh"):
    """按语言获取 buff 名称。"""
    if lang == "en":
        return buff.get("en", "")
    if lang == "zh_tw":
        return buff.get("zh_tw", buff.get("zh", ""))
    if lang == "ja":
        return buff.get("ja", buff.get("zh", ""))
    return buff.get("zh", "")

# ============================ GBFR XXHash32 ============================
_P1, _P2, _P3, _P4, _P5 = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1

def _xx_m(a, b): return (a * b) & 0xFFFFFFFF
def _xx_r(x, r): return ((x << r) | (x >> (32 - r))) & 0xFFFFFFFF
def _xx_u32(b, p): return b[p] | (b[p+1] << 8) | (b[p+2] << 16) | (b[p+3] << 24)

def game_xxhash32(text):
    data = text.encode("utf-8") if isinstance(text, str) else text
    n, p, h = len(data), 0, 0x178A54A4
    if n >= 16:
        V = [0x2557311B, 0x871FB76A, 0x0133ECF3, 0x62FC7342]
        while True:
            for k in range(4):
                V[k] = _xx_m(_xx_r((V[k] + _xx_m(_xx_u32(data, p + 4*k), _P2)) & 0xFFFFFFFF, 13), _P1)
            p += 16
            if n - p <= 16:
                break
        h = (_xx_r(V[0], 1) + _xx_r(V[1], 7) + _xx_r(V[2], 12) + _xx_r(V[3], 18)) & 0xFFFFFFFF
    h = (h + n) & 0xFFFFFFFF
    while n - p >= 4:
        h = _xx_m(_xx_r((h + _xx_m(_xx_u32(data, p), _P3)) & 0xFFFFFFFF, 17), _P4); p += 4
    while p < n:
        h = _xx_m(_xx_r((h + _xx_m(data[p], _P5)) & 0xFFFFFFFF, 11), _P1); p += 1
    h = (h ^ (h >> 15)) & 0xFFFFFFFF; h = _xx_m(h, _P2)
    h = (h ^ (h >> 13)) & 0xFFFFFFFF; h = _xx_m(h, _P3)
    return (h ^ (h >> 16)) & 0xFFFFFFFF

# ============================ 角色能力数据库 ============================
_char_db = {}
_ab_hash_map = {}
_abilities_by_pl = {}
_pl_hash_map = {}

def load_char_db():
    global _char_db, _ab_hash_map, _pl_hash_map, _abilities_by_pl
    # 多级目录回溯查找 JSON：打包目录 / exe目录 / 脚本目录 / 向上级最多4层
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    for base in (_BUNDLE_DIR, EXE_DIR, here):
        if base:
            candidates.append(os.path.join(base, "GBFR_Character_Skills_Buffs.json"))
    d = here
    for _ in range(4):
        d = os.path.dirname(d)
        if d:
            candidates.append(os.path.join(d, "GBFR_Character_Skills_Buffs.json"))
    path = ""
    for c in candidates:
        if c and os.path.isfile(c):
            path = c
            break
    if not path:
        return
    try:
        raw = json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return
    db, ab_hash, pl_hash = {}, {}, {}
    for pl_id, info in raw.get("角色", {}).items():
        try:
            pl_hash[game_xxhash32(pl_id)] = pl_id
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        nm = info.get("角色名", {})
        abilities = []
        for ab in info.get("能力", []):
            aid = ab.get("能力ID", "")
            an = ab.get("能力名", {})
            name_zh = an.get("简体中文", "") or aid
            name_en = an.get("英文", "") or name_zh
            name_tw = an.get("繁体中文", "") or name_zh
            # V2203：技能名日语——源表无日语字段，回退到简体（后续可从游戏 jp text.msg 补齐）
            name_ja = an.get("日文", "") or name_zh
            abilities.append({"id": aid, "zh": name_zh, "zh_tw": name_tw, "en": name_en, "ja": name_ja})
            if aid:
                try:
                    ab_hash[game_xxhash32(aid)] = {"pl": pl_id, "id": aid, "zh": name_zh, "zh_tw": name_tw, "en": name_en, "ja": name_ja}
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
        # V2203：日语角色名优先取 i18n.json（源自游戏内 text_chara.msg 原文），
        # 回退到技能表的「日文」字段，再回退到简体。
        _ija = ""
        try:
            _ija = (I18N_CHARS.get(pl_id) or {}).get("ja", "")
        except Exception:
            _ija = ""
        db[pl_id] = {"name_zh": nm.get("简体中文", "") or pl_id,
                     "name_en": nm.get("英文", "") or pl_id,
                     "name_tw": nm.get("繁体中文", "") or nm.get("简体中文", "") or pl_id,
                     "name_ja": _ija or nm.get("日文", "") or nm.get("简体中文", "") or pl_id,
                     "abilities": abilities}
    _char_db = db
    _ab_hash_map = ab_hash
    _pl_hash_map = pl_hash
    _abilities_by_pl = {pid: info.get("abilities", []) for pid, info in db.items()}

def _lookup_ability(ab_hash_val, pl_id=None, slot=None):
    """按 ability_hash 查技能；主控人物若与规范角色共享技能组（姬塔↔古兰、
    龙人化↔伊德），查不到时按槽位借用规范角色技能名，避免能力名空着。"""
    g = _ab_hash_map.get(ab_hash_val)
    if g:
        return g
    if pl_id and pl_id in PL_SKILL_FALLBACK:
        abl = _abilities_by_pl.get(PL_SKILL_FALLBACK[pl_id])
        if abl and isinstance(slot, int) and 0 <= slot < len(abl):
            a = abl[slot]
            return {"id": a.get("id", ""), "zh": a.get("zh", ""),
                    "zh_tw": a.get("zh_tw", ""), "en": a.get("en", ""),
                    "ja": a.get("ja", a.get("zh", ""))}
    return None

def _skill_name(ab_hash_val, lang="zh", pl_id=None, slot=None):
    # V2304：调试数据模式下技能名也统一显示调试文本（与 buff 名保持一致，便于核对字号/背景宽度）
    if _DEBUG_ATTR.get("active"):
        return str(_DEBUG_ATTR.get("text") or "")
    g = _lookup_ability(ab_hash_val, pl_id, slot)
    if not g:
        return ""
    if lang == "en":
        return g.get("en", g.get("zh", ""))
    if lang == "zh_tw":
        return g.get("zh_tw", g.get("zh", ""))
    if lang == "ja":
        return g.get("ja", g.get("zh", ""))
    return g.get("zh", "")

# BUFF_PROFILES: 每个角色可配置多个 buff（列表）
# 键：官方 PL ID（优先，因为角色识别已改用 charid hash -> pl_id）；同时保留 0x1FD char_type 键作回退。
# 每个 buff 条目: zh(简中), zh_tw(繁中), en(英文), stack_status_id, timer_status_id, timer_display, single_layer
# timer_display: "full_stack_only" = 仅满层显示倒计时; "any_stack" = 任意层数显示倒计时
# single_layer: True = 该 buff 只有倒计时、无层数概念（使用「单层buff倒计时胶囊」独立样式）

# ============================ 非 ExStatus 裸值 Buff / 资源槽偏移 ============================
# 来源：GBFR_ClassFinder / GBFR_IdGaugeMonitor 实测（v240 整合）

# 团长/古兰/姬塔 职业层数（Class Level）
CLASS_STATE_PTR_OFF = 0x1AE00      # actor -> 职业状态结构体指针（层数 rank 经此二级指针读）
CLASS_RANK_OFF = 0x1FA4            # u32，当前层数 1~4（位于 CLASS_STATE_PTR 指向的结构体内）
CLASS_DURATION_OFF = 0x1FBC       # f32，倒计时剩余秒（实机验证：rank=3 时 7.1914→7.1913 递减；位于 P 结构体内）
CLASS_DURATION_MAX_OFF = 0x1FB8    # f32，倒计时上限/初值（实机验证：稳定 7.2）
CLASS_DURATION_DIRECT_OFF = 0xCAAC # f32，备用回退路径（直读 actor；当前版本读不到有效值，保留兜底）

# 伊德（Id）形态识别
ID_FORM_OFF = 0x1FD
ID_FORM_DRAGON = 0x20              # 龙人态
# 龙人态官方父子指针（来自 gbfr-logs/GBFR-ACT 公开 RE）：真身 actor = read_u64(actor+0xd488)+0x70
ID_DRAGON_PARENT_OFF = 0xD488
ID_DRAGON_PARENT_EXTRA = 0x70

# 伊德资源槽偏移（actor 直接偏移 / 二级指针链的子偏移）
ID_OVERDRIVE_STATUS_ID = 30        # 神威一体 status id（ExStatus 槽位内 sid），用于 has_overdrive 判定；V350 起的模块级常量，重构时随 buff_data_generated 简化丢失，V370 补回
ID_HIDDEN_OFF = 0x1CB34            # f32 0~4，隐藏槽（actor 直接偏移）

# 巴萨拉卡（PL1700）古洛诺斯槽保持倒计时：actor 直接偏移（f32）
# 来源：gbfr_vaseraga_freeze_monitor.py 实测确认
VASERAGA_FREEZE_OFF = 0x1CAF0     # f32，古洛诺斯槽保持剩余秒数（仅冻结中>0）

BUFF_PROFILES = buff_data_generated.BUFF_PROFILES
MASTERY_BRANCHES = buff_data_generated.MASTERY_BRANCHES   # 每角色三系专精列名（三语）
CHAR_NAMES_TRI = buff_data_generated.CHAR_NAMES           # 每角色三语名

# ============================ Buff 顺位拖拽排序组件 ============================
class BuffListWidget(QListWidget):
    """生效区 / 隐藏区 列表。

    拖拽全部由 BuffOrderGroup 协调，保证：
    - 仅允许在同一角色（同一个 BuffOrderGroup）内拖动；跨角色一律拒绝；
    - 通过数据重建而非物理移动 item 对象，杜绝克隆 / 丢失条目。
    """

    def __init__(self, parent_group, is_hidden_side, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_group = parent_group
        self.is_hidden_side = is_hidden_side
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.setStyleSheet(
            "QListWidget::item{padding:1px 4px;color:#dfe7f5;}"
            "QListWidget::item:selected{background:#3a5a9a;}"
        )

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item is not None:
            self.parent_group._drag_key = item.data(Qt.UserRole)
            self.parent_group._drag_source = self
        super().startDrag(supportedActions)

    def dragEnterEvent(self, event):
        # 仅接受来自同一角色分组的拖拽（跨角色直接拒绝）
        src = event.source()
        if isinstance(src, BuffListWidget) and src.parent_group is self.parent_group:
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        src = event.source()
        if isinstance(src, BuffListWidget) and src.parent_group is self.parent_group:
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        source = event.source()
        # 跨角色拖拽：直接拒绝（底线），绝不接受别的角色的 buff
        if not (isinstance(source, BuffListWidget) and source.parent_group is self.parent_group):
            event.ignore()
            self.parent_group._drag_key = None
            self.parent_group._drag_source = None
            return

        # 同一列表内重排：交给 Qt 默认实现，再读回顺序
        if source is self:
            super().dropEvent(event)
            self.parent_group._sync_from_lists()
            self.parent_group._refresh_appearances()
            self.parent_group.orderChanged.emit()
            self.parent_group._drag_key = None
            self.parent_group._drag_source = None
            return

        # 跨列（生效 <-> 隐藏）移动：用数据重建，绝不产生克隆 / 丢失
        idx = self.parent_group._drag_key
        if idx is None:
            event.ignore()
        else:
            pos = event.position().toPoint()
            target_row = self.row(self.itemAt(pos))
            self.parent_group._move_idx(idx, to_hidden=self.is_hidden_side, at_row=target_row)
            event.accept()
        self.parent_group._drag_key = None
        self.parent_group._drag_source = None

    def _on_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item:
            return
        self.parent_group._on_context_menu(self, pos)

# ExStatus 结构体偏移（来自 GBFR_BuffMonitor 项目验证）
ACTOR_EX_STATUS = 0xAF8       # Actor → ExStatus 指针
STATUS_ID_OFFSET = 0x50      # StatusBase → StatusId (u32)
STATUS_CUR_STACKS = 0x58     # StatusBase → 当前层数 (i32)
STATUS_INFINITE_FLAG = 0x79  # StatusBase → 永续标记 (byte)
STATUS_INITIAL_DUR = 0x7C    # StatusBase → 初始持续时间 (f32) — timer_max
STATUS_REMAINING_DUR = 0x80  # StatusBase → 剩余时间 (f32) — 实时倒计时
STATUS_MAX_STACKS = 0xB0     # StatusBase → 上限层数 (i32)
STATUS_SUB_ID = 0x4C         # StatusBase → sub_id / cause 区分符 (u32) — 搬自 monitor 门限
EX_STATUS_PTR_SLOTS = 16     # 指针数组扫描槽位数

# 技能冷却偏移（来自 GBFR_SkillCooldown 验证）
SKILL_SLOT_OFFSETS = [0x330C, 0x335C, 0x33AC, 0x33FC]
# 修正：装备能力 hash 是 actor + 0x15030 + 0x5AF4 = 0x1AB24，不是 0x1AA24
ABILITY_HASH_OFFSET = 0x1AB24
CHARID_HASH_OFFSET = 0x1AB40
SKILL_READY_THRESHOLD = 0.05

# 角色能力数据库路径（实际由 load_char_db() 自行构造候选路径，下面的常量未使用，已删除）

# ------------------------- Windows API -------------------------
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.CHAR * 260),
    ]

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(wintypes.BYTE)),
        ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.CHAR * 256), ("szExePath", wintypes.CHAR * 260),
    ]

def find_game_pids():
    """枚举当前所有 granblue_fantasy_relink.exe 进程的 PID 集合（用于「游戏在前台」判断）。

    V2018 背景：游戏的真实顶层窗口可能不是主进程 create 的（Steam overlay、DirectX 子窗口、
    launcher 包裹等），GetForegroundWindow 拿到的窗口 PID 不一定等于 self.pid。若仅匹配
    self.pid，则「游戏是否在前台」的判断会永远失败，前后台切换的边沿触发整条失效。
    改为收集所有同名游戏进程 PID，foreground_pid ∈ self._game_pids 即视为游戏在前台。
    """
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wintypes.HANDLE(-1).value:
        return []
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    pids = []
    if kernel32.Process32First(snap, ctypes.byref(pe)):
        while True:
            name = pe.szExeFile.decode("ascii", "ignore")
            if name.lower() == PROCESS_NAME.lower():
                pids.append(pe.th32ProcessID)
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(snap)
    return pids

def get_module_info(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == wintypes.HANDLE(-1).value:
        return None
    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(me)
    base = size = None
    if kernel32.Module32First(snap, ctypes.byref(me)):
        while True:
            mod = me.szModule.decode("ascii", "ignore")
            if mod.lower() == MODULE_NAME.lower():
                base = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value
                size = me.modBaseSize
                break
            if not kernel32.Module32Next(snap, ctypes.byref(me)):
                break
    kernel32.CloseHandle(snap)
    return (base, size) if base is not None else None

def open_proc(pid):
    return kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)

def get_foreground_pid():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None

def rpm(handle, addr, size):
    buf = ctypes.create_string_buffer(size)
    nread = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(nread))
    if not ok or nread.value != size:
        return None
    return buf.raw

def read_u32(handle, addr):
    b = rpm(handle, addr, 4)
    return struct.unpack("<I", b)[0] if b else None

def read_u64(handle, addr):
    b = rpm(handle, addr, 8)
    return struct.unpack("<Q", b)[0] if b else None

def read_f32(handle, addr):
    b = rpm(handle, addr, 4)
    return struct.unpack("<f", b)[0] if b else None

def read_u8(handle, addr):
    b = rpm(handle, addr, 1)
    return struct.unpack("<B", b)[0] if b else None


def read_cstring(handle, addr, maxlen=32):
    """读一段以 NUL 结尾的 ASCII 字符串（V2200：boss 实体名识别用）。

    返回 str；不可读或为空时返回 None。
    """
    b = rpm(handle, addr, maxlen)
    if not b:
        return None
    nul = b.find(b"\x00")
    if nul >= 0:
        b = b[:nul]
    try:
        s = b.decode("ascii", "ignore").strip()
    except Exception:
        return None
    return s or None

def parse_aob(hexstr):
    # 允许 AOB 字符串中包含空格或换行，先统一剔除再解析
    hexstr = hexstr.replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", "")
    out = bytearray()
    mask = []
    for i in range(0, len(hexstr), 2):
        pair = hexstr[i : i + 2]
        if pair.lower() == "xx":
            out.append(0)
            mask.append(False)
        else:
            out.append(int(pair, 16))
            mask.append(True)
    return bytes(out), mask

def aob_scan(handle, base, size, pattern, mask):
    plen = len(pattern)
    chunk = 4 * 1024 * 1024
    overlap = plen
    offset = 0
    while offset < size:
        chunk_size = min(chunk + overlap, size - offset)
        data = rpm(handle, base + offset, chunk_size)
        if data is None:
            offset += chunk
            continue
        search_end = min(len(data) - plen + 1, chunk + 1)
        for i in range(search_end):
            if all((not mask[j]) or data[i + j] == pattern[j] for j in range(plen)):
                return base + offset + i
        offset += chunk
    return None

def aob_scan_multi(handle, base, size, specs):
    """单次全模块扫描，同时匹配多个特征码（锚点加速）。

    specs: [(key, pattern, mask), ...]。返回 {key: hit_addr}，未命中为 None。
    相比对每个 pattern 各调用一次 aob_scan，本函数只把模块读入内存一遍，
    大幅降低启动时的跨进程内存读取开销（80MB 只读一次而非多次）。

    实现：对每个特征码取首个「具体字节」作为锚点，用 bytes.find 在每块中快速
    定位候选位置，仅在锚点命中处做全量通配符校验，避免逐字节 Python 比对，
    显著降低启动扫描耗时（缓存未命中时不再阻塞 UI 数秒）。
    """
    if not specs:
        return {}
    prepared = []
    for key, pattern, mask in specs:
        anchor_pos = next((j for j, m in enumerate(mask) if m), 0)
        prepared.append((key, pattern, mask, anchor_pos, pattern[anchor_pos]))
    maxlen = max(len(p) for _, p, _, _, _ in prepared)
    chunk = 8 * 1024 * 1024
    overlap = maxlen
    offset = 0
    results = {key: None for key, _, _, _, _ in prepared}
    while offset < size:
        chunk_size = min(chunk + overlap, size - offset)
        data = rpm(handle, base + offset, chunk_size)
        if data is None:
            offset += chunk
            continue
        search_end = min(len(data) - maxlen + 1, chunk + 1)
        for key, pattern, mask, anchor_pos, anchor in prepared:
            if results[key] is not None:
                continue
            plen = len(pattern)
            j = 0
            while True:
                idx = data.find(anchor, j, search_end + anchor_pos)
                if idx < 0:
                    break
                i = idx - anchor_pos
                if i < 0 or i + plen > len(data):
                    j = idx + 1
                    continue
                if all((not mask[t]) or data[i + t] == pattern[t] for t in range(plen)):
                    results[key] = base + offset + i
                    break
                j = idx + 1
        if all(v is not None for v in results.values()):
            break
        offset += chunk
    return results

def resolve_player_from_hit(handle, hit):
    disp_b = rpm(handle, hit + DISP_OFF, 4)
    if disp_b is None:
        return None
    disp = struct.unpack("<i", disp_b)[0]
    return (hit + INSTR_END) + disp

def save_ptr_cache(pid, base, size, pptr):
    try:
        with open(PTR_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(f"{pid}\n{base:#x}\n{size:#x}\n{pptr:#x}\n")
    except Exception:
        logger.debug("swallowed exception", exc_info=True)

def load_ptr_cache():
    try:
        with open(PTR_CACHE_FILE, "r", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        if len(lines) < 4:
            return None
        return (int(lines[0]), int(lines[1], 16), int(lines[2], 16), int(lines[3], 16))
    except Exception:
        return None

def resolve_with_cache(handle, pid, extra_specs=None):
    """定位玩家指针（带文件缓存）。

    extra_specs: 可选的其他特征码 [(key, pattern, mask), ...]，仅在本函数
    需要全模块扫描时与玩家指针在同一次扫描中一并定位（避免重复读取 80MB 模块）。
    返回 (pptr, base, size, extra_hits)。
    """
    minfo = get_module_info(pid)
    if minfo is None:
        return None, None, None, {}
    base, size = minfo
    cached = load_ptr_cache()
    if cached:
        c_pid, c_base, c_size, c_pptr = cached
        if c_pid == pid and c_base == base and c_size == size:
            cb = read_u64(handle, c_pptr + CHAR_PTR_OFF)
            if cb:
                return c_pptr, base, size, {}
    # 缓存未命中 → 与 extra 特征码合并为单次扫描
    specs = [("player", *parse_aob(AOB_HEX))]
    if extra_specs:
        specs.extend(extra_specs)
    hits = aob_scan_multi(handle, base, size, specs)
    pptr = None
    ph = hits.get("player")
    if ph is not None:
        pptr = resolve_player_from_hit(handle, ph)
    if pptr is None:
        return None, None, None, {}
    save_ptr_cache(pid, base, size, pptr)
    extra_hits = {}
    for key, _, _ in specs:
        if key == "player":
            continue
        hit = hits.get(key)
        if key == "quest_mgr" and hit is not None:
            mgr, gaddr = resolve_quest_mgr_from_hit(handle, hit)
            extra_hits[key] = mgr
            extra_hits["_quest_mgr_global"] = gaddr
    return pptr, base, size, extra_hits

def resolve_quest_mgr_from_hit(handle, hit):
    """从 AOB 命中地址解出任务管理器实例指针及其全局变量地址。
    返回 (mgr_instance, global_ptr_addr)。global_ptr_addr 是模块内「指向 mgr 的全局指针」
    的地址，与 player 全局指针地址 (pptr) 同属一个模块，二者相减即为与 ASLR 无关的相对偏移。
    """
    if hit is None:
        return None, None
    # 48 8b 0d [disp32]  → disp 位于 hit+3..hit+7
    disp_b = rpm(handle, hit + 3, 4)
    if disp_b is None:
        return None, None
    disp = struct.unpack("<i", disp_b)[0]
    global_ptr_addr = hit + 7 + disp
    b = rpm(handle, global_ptr_addr, 8)
    if not b:
        return None, global_ptr_addr
    return struct.unpack("<Q", b)[0], global_ptr_addr

def resolve_quest_mgr_via_player(handle, pptr):
    """用 player 全局指针变量地址(pptr) + 写死偏移 QM_DELTA 直接取 quest_mgr。

    无需任何 AOB 扫描：qm_global = pptr + QM_DELTA 是模块内「指向 mgr 的全局指针」
    变量的地址，解引用即得 quest_mgr 实例指针。与 ASLR 无关（偏移经三次重启实测恒定）。
    返回 (mgr_instance, global_ptr_addr)，失败返回 (None, None)。
    """
    if not pptr:
        return None, None
    qm_global_addr = pptr + QM_DELTA
    b = rpm(handle, qm_global_addr, 8)
    if not b:
        return None, qm_global_addr
    return struct.unpack("<Q", b)[0], qm_global_addr

def resolve_quest_mgr_with_addr(handle, base, size):
    """兼容调用：返回 (mgr_instance, global_ptr_addr)。"""
    pat, mask = parse_aob(QUEST_MGR_AOB)
    hit = aob_scan(handle, base, size, pat, mask)
    return resolve_quest_mgr_from_hit(handle, hit)

# read_exstatus_buffs 在 V2050 中曾尝试接入 GBFR_BuffMonitor 的 gate 过滤，
# 但因 gate 默认会按 min_remaining_time/min_initial_time 无差别过滤「永续 buff（remaining=0）」，
# 会干扰核心模块依赖的 all_buffs，故此版撤销该接入，还原为 V2040 的基础过滤。
# V2068：与 GBFR_BuffMonitor 的 `_parse_statusbase` 同款 parse 行为——
#   NaN/Inf 时长的 buff（包括永续 buff）整条 discard（continue 跳过），不进 result 字典。
#   这样全 Buff 模块渲染时字典里只有「时间戳正常」的 buff，永续 buff 不会被
#   「最小初始时间 0.05s」「最小剩余时间 0.05s」门限误杀。
#   核心模块不受影响：核心模块读 `active_buffs`（= buffs_out，结构化 dict 来自 profile 配表），
#   不直接读 initial/remaining；ExStatus 的 NaN 字段只对核心区「计时是否生效」相关分支有间接影响，
#   但那些分支都已经各自有 None/0 兜底（line 1346-1350）。
def read_exstatus_buffs(handle, char_base, ex_status_offset=ACTOR_EX_STATUS):
    """从 Actor 的 ExStatus 指针数组读取全部活跃 buff。

    返回 (result, result_list)：
      result     = {status_id: info} 字典（按 sid 去重构 core 模块用；同 sid 多实例只保留最后一个）
      result_list = [(sid, info), ...] 列表（保留全部槽位，含同 sid 重复），
                    供「全 Buff 模块」显示同名 buff 的多个实例（如帕西瓦尔双重追击）。
    无效或无 buff 时返回 ({}, [])。
    V2068：与 GBFR_BuffMonitor 的 parse 行为对齐——NaN/Inf 时长字段的 buff 整条 discard。
    V2108 BUGFIX：原先只返回 result（按 sid 字典），同 sid 的第二个槽位会用 `result[sid]=...`
            覆盖第一个 → 全 Buff 模块永远只显示 1 张同名 buff（如帕西瓦尔的 2 个「追击」）。
            现在同时返回 result_list（按数组槽位逐个收集），全 Buff 模块改用它渲染，
            即可完整列出所有实例；core 模块继续用 result，零影响。
    """
    ex_status = read_u64(handle, char_base + ex_status_offset)
    if not ex_status or ex_status < 0x10000:
        return {}, []
    result = {}
    result_list = []
    consecutive_nulls = 0
    # V2210 BUGFIX：同一条 status 对象可能被指针数组里的**多个槽位指向**
    # （游戏 ExStatus 内部的重复注册 / 引用），原逻辑每个槽位都读一次 →
    # 同一条 buff 在模块里出现多张一模一样的卡（玩家反馈「明明是同一个燃烧A却显示两次」）。
    # 按 status 指针地址去重：同一 ptr 只读一次。
    # 不同的 status 对象（燃烧A / 燃烧B）地址不同，照旧全部保留 ——
    # 不影响「同 sid 多实例」的正当需求（玩家手动加进多次出现名单就是为此）。
    # 主控全 Buff 与 Boss 模块共用本函数，两处一并修复。
    seen_ptrs = set()
    for i in range(EX_STATUS_PTR_SLOTS):
        ptr = read_u64(handle, ex_status + i * 8)
        if not ptr or ptr < 0x10000 or ptr >= 0x7FF000000000:
            consecutive_nulls += 1
            if result and consecutive_nulls >= 2:
                break
            continue
        consecutive_nulls = 0
        if ptr in seen_ptrs:
            continue
        seen_ptrs.add(ptr)
        sid_raw = read_u32(handle, ptr + STATUS_ID_OFFSET)
        # V2092 BUGFIX：`if not sid` 把 sid=0（攻击力强化「攻击UP」）直接跳过——
        # 写代码的人当时可能以为"0 号槽是 sentinel/header"，但 GBFR 里 sid=0 是真实 buff。
        # V2012 时代全 Buff 模块还没加，没人发现；V2062 加全 Buff 模块后这个 bug 一直存在。
        # 玩家把门限全关后仍然抓不到 sid=0 就是这个原因——sid 在 read_exstatus_buffs
        # 这一关就被 continue 了，根本到不了 render_allbuff 的门限循环。
        # 修法：只过滤 read_u32 失败返回的 None（is None），不过滤合法的 0。
        if sid_raw is None or sid_raw > 0xFFFF:
            continue
        sid = sid_raw
        stacks = read_u32(handle, ptr + STATUS_CUR_STACKS) or 0
        if stacks > 9999:
            stacks = 0
        max_stacks = read_u32(handle, ptr + STATUS_MAX_STACKS) or 0
        if max_stacks > 9999:
            max_stacks = 0
        initial = read_f32(handle, ptr + STATUS_INITIAL_DUR) or 0
        remaining = read_f32(handle, ptr + STATUS_REMAINING_DUR) or 0
        infinite = (read_u8(handle, ptr + STATUS_INFINITE_FLAG) or 0) != 0
        sub_id = read_u32(handle, ptr + STATUS_SUB_ID) or 0
        # V2089 BUGFIX：改回 V2012 行为——NaN/Inf 归零保留（不再整条 discard）。
        # V2068 误以为"核心模块不受影响"，但 2.0.4 更新后，伊德龙人态下紫银之力(sid=60)等
        # 永续 buff 的 STATUS_INITIAL_DUR/STATUS_REMAINING_DUR 字段在游戏内存中变成 NaN/Inf
        # （V2012 时代是合法 float）→ 整条 discard 把这些 buff 从 all_buffs 字典里删掉
        # → 核心模块 `if sid in all_buffs` 判定失败 → 伊德龙人化时核心区 buff 全空白。
        # 改回归零后：永续 buff remaining=0 initial=0 但 `infinite=True` 让第二关
        # `if not infinite and remaining<=0.01 and initial<=0.01: continue` 不丢它们（V2012 行为）。
        # 对全 Buff 模块零影响：永续 buff 一直就被 `infinite` 守护；非永续 NaN/Inf 仍走第二关被过滤。
        if math.isnan(remaining) or math.isinf(remaining):
            remaining = 0
        if math.isnan(initial) or math.isinf(initial):
            initial = 0
        if not infinite and remaining <= 0.01 and initial <= 0.01:
            continue
        result[sid] = {
            "stacks": stacks,
            "max_stacks": max_stacks,
            "initial": initial,
            "remaining": remaining,  # 名字是 remaining，存量
            "infinite": infinite,
            "sub_id": sub_id,  # V2066：搬自 monitor 门限 sub_id 溢出门限
        }
        # V2108：保留全部槽位（含同 sid 重复），供全 Buff 模块显示多个同名实例
        # 存 (sid, info) 二元组，与 render_allbuff 的 `for sid, info in buffs` 迭代保持一致
        result_list.append((sid, result[sid]))
    return result, result_list


# ==================== V2200：Boss Buff 模块 —— 实体表定位 + ExStatus 读取 ====================
# 依据（2026-08-30 实测，别西卜 EM8200 / 胡拉坎 Em7202 各一把）：
#   * 全局实体表：*(module_base + ENTITY_TABLE_RVA) → entity_table
#       entity_table + 0x20 = ents（实体指针数组，步长 8）；+0x48 = ids（校验用）
#   * 实体 = entity-info block：+0x08 = ASCII 实体名；+0x70 = actor 实例指针
#   * boss 实体名**不只有 Em#### 一种**：别西卜叫 placement_enemy_member，
#     胡拉坎叫 Em7202 —— 所以识别规则要同时覆盖「含 enemy」与「大写 Em+4 位数字」。
#   * boss actor 的 ExStatus 组件在 actor + BOSS_EX_STATUS，list begin/end 在组件 +0x18/+0x20
#     → 即 begin = *(actor + 0xCF8 + 0x18) = *(actor + 0xD10)
#   * StatusBase 字段偏移与玩家完全一致（+0x50 sid / +0x4C sub / +0x58 stacks /
#     +0x79 infinite / +0x7C initial / +0x80 remaining / +0xB0 max_stacks）
ENTITY_TABLE_RVA_CANDIDATES = [
    ("v2.0.5", 0x701F948),
    ("v2.0.4", 0x701F728),
]
ENTITY_TABLE_ENTS_OFF = 0x20
ENTITY_TABLE_IDS_OFF = 0x48
INFO_NAME_OFF = 0x08
INFO_ACTOR_OFF = 0x70
MAX_ENTITIES_SCAN = 4096

# boss 的 ExStatus：组件嵌入在 actor + 0xCF8，组件内 list begin 在 +0x18、end 在 +0x20。
# 注意 read_exstatus_buffs 的 ex_status_offset 参数要的是「list begin 指针所在的偏移」
# （玩家侧对应 ACTOR_EX_STATUS = 0xAF8，而非组件偏移 0xAE0），所以这里是 0xCF8 + 0x18。
BOSS_EX_STATUS = 0xCF8 + 0x18  # = 0xD10，传给 read_exstatus_buffs 用

# 缓存：模块基址 → 实体表偏移（避免每帧重复试多个 RVA）
_BOSS_ET_CACHE = {}


def _boss_entity_table(handle, base):
    """定位全局实体表，返回 (ents, ids) 或 (None, None)。带模块基址缓存。"""
    key = base
    if key in _BOSS_ET_CACHE:
        return _BOSS_ET_CACHE[key]
    result = (None, None)
    for _tag, rva in ENTITY_TABLE_RVA_CANDIDATES:
        et = read_u64(handle, base + rva)
        if not et or et < 0x10000:
            continue
        ents = read_u64(handle, et + ENTITY_TABLE_ENTS_OFF)
        if not ents or ents < 0x10000:
            continue
        ids = read_u64(handle, et + ENTITY_TABLE_IDS_OFF)
        result = (ents, ids)
        break
    _BOSS_ET_CACHE[key] = result
    return result


def _is_boss_entity_name(name, keywords):
    """判断实体名是否像 boss 本体。

    规则（实测）：
      * 含 'enemy' 关键字 → placement_enemy_member（别西卜）等
      * 大写 Em/EM + 4 位数字 → Em7202（胡拉坎）等
    """
    if not name:
        return False
    low = name.lower()
    if "enemy" in low:
        return True
    if len(name) >= 6 and name[:2] in ("Em", "EM") and name[2:6].isdigit():
        return True
    # 兼容玩家自定义关键字
    for kw in (keywords or "").split(","):
        kw = kw.strip()
        if kw and kw in name:
            return True
    return False


def find_boss_actor(handle, base, keywords="enemy,Em"):
    """从实体表里找 boss 本体的 actor 指针。找不到返回 None。

    返回 (actor, entity_name)。
    """
    ents, _ids = _boss_entity_table(handle, base)
    if not ents:
        return None, None
    for i in range(MAX_ENTITIES_SCAN):
        ent = read_u64(handle, ents + i * 8)
        if not ent or ent < 0x10000:
            continue
        name = read_cstring(handle, ent + INFO_NAME_OFF, 32)
        if not _is_boss_entity_name(name, keywords):
            continue
        actor = read_u64(handle, ent + INFO_ACTOR_OFF)
        if not actor or actor < 0x10000:
            continue
        return actor, name
    return None, None


# V2200：boss actor 定位要遍历实体表（上限 4096 项，每项 2 次读内存），
# 而 tick 每秒会跑几十次 —— 每次都重扫会明显拖慢主循环。故做 TTL 缓存：
# 缓存期内复用上次的 actor，只在过期或 actor 失效（换场景/重开战斗）时才重扫。
_BOSS_CACHE = {"handle": None, "base": None, "actor": None, "name": None, "ts": 0.0}
_BOSS_CACHE_TTL = 1.5


def _boss_actor_alive(handle, actor):
    """轻量存活校验：缓存的 actor 是否仍指向一个像样的 ExStatus list。

    判定只看 list begin 指针是否有效（不逐槽校验，避免每次 tick 的额外开销）。
    """
    if not actor:
        return False
    begin = read_u64(handle, actor + BOSS_EX_STATUS)
    return bool(begin and begin > 0x10000)


def read_boss_buffs(handle, base, keywords="enemy,Em", ttl=None):
    """读取当前场上 boss 身上的全部 buff/debuff。

    返回 (result, result_list, boss_actor, boss_name)：
      result      = {sid: info} 字典（按 sid 去重，后出现的覆盖先出现的）
      result_list = [(sid, info), ...] 保留全部槽位（含同 sid 多个实例）
      boss_actor  = boss 的 actor 指针（未找到时为 None）
      boss_name   = boss 实体名（未找到时为 None）

    未找到 boss / 读不到时返回 ({}, [], actor_or_None, name_or_None)。

    ttl: boss actor 缓存秒数，None = 用默认 _BOSS_CACHE_TTL（1.5s）。
    """
    import time as _t
    ttl = _BOSS_CACHE_TTL if ttl is None else ttl
    now = _t.time()
    c = _BOSS_CACHE

    actor = name = None
    if (c.get("actor") and c.get("base") == base and c.get("handle") == handle
            and (now - c.get("ts", 0.0)) < ttl
            and _boss_actor_alive(handle, c["actor"])):
        actor, name = c["actor"], c["name"]

    if not actor:
        actor, name = find_boss_actor(handle, base, keywords)
        c["handle"], c["base"] = handle, base
        c["actor"], c["name"], c["ts"] = actor, name, now

    if not actor:
        # boss 不在场（未进战斗/已击杀）→ 清掉缓存，下次从头找
        c["actor"], c["name"] = None, None
        return {}, [], None, None

    result, result_list = read_exstatus_buffs(handle, actor, BOSS_EX_STATUS)
    return result, result_list, actor, name

def read_overlay_data(handle, pptr, raw_locked=None, duration_max=None):
    """读取角色层数、翻滚次数和全部角色专属 buff（V302 专精门控版）。

    数据源改吃 buff_data_generated.BUFF_PROFILES：每条 buff 带 sid（ExStatus）
    或 raw_source 字符串（class_state/id_direct/actor_timer 三 specials），
    以及 awakening/truth/secret 三专精勾选默认 + single_layer。
    ExStatus buff 仅当当前在场（all_buffs 含 sid）才输出 —— 自动实现形态门控
    （神威一体/龙人化等只在对应形态出现）。隐藏槽仅在神威一体在场时读。
    返回 buffs 每条带 awakening/truth/secret 元数据，供 tick 专精过滤。

    duration_max: {"kronos_freeze": float, "class_duration": float}
    传入当前学习到的最大值，函数会按实际读数继续更新并在返回值中回传。
    """
    raw_locked = raw_locked or {}
    duration_max = duration_max or {}
    kronos_max = float(duration_max.get("kronos_freeze", 10.0) or 10.0)
    class_dur_max = float(duration_max.get("class_duration", 30.0) or 30.0)
    char_base = read_u64(handle, pptr + CHAR_PTR_OFF)
    if not char_base:
        return {"status": "no_char", "dodge": None, "char_type": 0, "buffs": [], "raw_locked": raw_locked, "duration_max": duration_max}
    dodge = read_u32(handle, char_base + FIELD_DODGE)

    # 伊德龙人态：ExStatus 挂在真身 actor 上，需用官方父子指针回到真身再读。
    read_base, is_dragon_form = _resolve_id_actor(handle, char_base)
    char_type = read_u8(handle, read_base + FIELD_CHAR_TYPE) or 0
    charid_hash = read_u32(handle, read_base + CHARID_HASH_OFFSET) or 0

    all_buffs, all_buffs_list = read_exstatus_buffs(handle, read_base)
    pl_id = _pl_hash_map.get(charid_hash)
    if not pl_id and char_type in CHAR_TYPE_TO_PL:
        pl_id = CHAR_TYPE_TO_PL[char_type]
    # V2090 BUGFIX：伊德龙人化(PL2000) 在 BUFF_PROFILES 里【没有配表】——
    #   V2038 为「能力模块技能名」把 PL2000 加进了 GBFR_Character_Skills_Buffs.json 的角色库
    #   （PL2000 有专属 AB_PL2000_01~05 技能），于是 _pl_hash_map 多了 PL2000 的 hash 映射。
    #   龙人态时 charid_hash 解析成 "PL2000" → 上面的 `if not pl_id` 回退不生效
    #   → BUFF_PROFILES.get("PL2000") = None → `if profile:` 为 False → buffs_out 为空
    #   → 核心区 buff 全空白（全 Buff 模块不受影响：它用 all_buffs，不依赖 profile）。
    #   V2012 正常是因为那时角色库里还没有 PL2000。
    # 修法：pl_id 解析不到有效 BUFF_PROFILES 时，强制回退到 CHAR_TYPE_TO_PL 的同族 PL
    #   （伊德龙人化 0x20 → PL1900，与核心 Buff 区共用配表）。
    # 对能力模块零影响：read_skill_cooldowns 走 ABILITY_HASH_OFFSET + _ab_hash_map，
    #   完全不读 pl_id，PL2000 的专属技能名仍然正常显示。
    if not BUFF_PROFILES.get(pl_id) and char_type in CHAR_TYPE_TO_PL:
        pl_id = CHAR_TYPE_TO_PL[char_type]
    profile = BUFF_PROFILES.get(pl_id)
    buffs_out = []
    new_locked = raw_locked or {}
    has_overdrive = ID_OVERDRIVE_STATUS_ID in all_buffs

    if profile:
        for idx, bc in enumerate(profile["buffs"]):
            rs = bc.get("raw_source")
            entry = None
            # 条件生效：龙人化仅龙人态、神威一体仅神威一体态
            require = bc.get("require")
            if require == "dragon_form" and not is_dragon_form:
                continue
            if require == "overdrive" and not has_overdrive:
                continue
            # 条件生效：隐藏槽仅当被依赖 buff（如神威一体 sid 30）在场时才输出
            gated_by = bc.get("gated_by_sid")
            if gated_by is not None and gated_by not in all_buffs:
                continue
            if rs == "class_state":
                # 团长 Class：层数 rank 经二级指针读；
                # 倒计时主路径 = 职业结构体内 P + CLASS_DURATION_OFF（实机验证：rank=3 时 7.191→7.190 递减）；
                # 仅当主路径读不到有效值时，回退到 char_base + CLASS_DURATION_DIRECT_OFF 直读。
                P = read_u64(handle, char_base + CLASS_STATE_PTR_OFF)
                rank = 0
                if P:
                    rank = (read_u32(handle, P + CLASS_RANK_OFF) or 0) + 1
                if P:
                    dur = read_f32(handle, P + CLASS_DURATION_OFF)
                    # 上限/初值（P+CLASS_DURATION_MAX_OFF，实机稳定 7.2）→ 直接用作 timer_max，比学习值精确
                    dur_max = read_f32(handle, P + CLASS_DURATION_MAX_OFF)
                    if not (isinstance(dur_max, (int, float))
                            and not math.isnan(dur_max) and not math.isinf(dur_max) and 0 < dur_max < 999):
                        dur_max = None
                else:
                    dur = None
                    dur_max = None
                # 主路径无效（None/NaN/Inf/<=0）→ 回退到 char_base 直读
                if not (isinstance(dur, (int, float))
                        and not math.isnan(dur) and not math.isinf(dur) and dur > 0):
                    dur2 = read_f32(handle, char_base + CLASS_DURATION_DIRECT_OFF)
                    if isinstance(dur2, (int, float)) \
                            and not math.isnan(dur2) and not math.isinf(dur2) and dur2 > 0:
                        dur = dur2
                    else:
                        dur = None
                # timer_max：优先用结构体直读上限，其次学习值
                _timer_max = dur_max if dur_max else class_dur_max
                entry = {
                    "index": idx, "zh":  bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"], "ja": bc.get("ja", bc["zh"]),
                    "stacks": rank, "max_stacks": 4, "timer": dur, "timer_max": _timer_max,
                    "timer_display": bc.get("timer_display", "any_stack"),
                    "_class_dur": True,
                }
            elif rs == "id_direct":
                # 伊德隐藏槽：常驻显示（不再受神威一体在场限制）；gauge_mode=float 不倒计时，不会随时间消失
                off = bc.get("off", ID_HIDDEN_OFF)
                v = read_f32(handle, read_base + off)
                if v is None or math.isnan(v) or math.isinf(v):
                    v = 0.0
                entry = {
                    "index": idx, "zh": bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"], "ja": bc.get("ja", bc["zh"]),
                    "stacks": int(v), "max_stacks": bc.get("max_stacks", 4), "timer": None, "timer_max": None,
                    "timer_display": bc.get("timer_display", "any_stack"),
                    "gauge_mode": "float", "gauge_value": float(v),
                }
            elif rs == "actor_timer":
                # 巴萨拉卡古洛诺斯槽 / 芙劳「转世的恩宠」等长驻资源倒计时：
                # actor+off f32，仅读数>0.01 时视为激活并倒计时；上限自我学习（仅向上）。
                # 指定 cap_setting 时各自使用独立的学习上限键（如 grace_max / kronos_freeze_max），
                # 学习机制相同（首次上升沿捕获、之后仅向上），但数值互不干扰。
                off = bc.get("off", VASERAGA_FREEZE_OFF)
                v = read_f32(handle, read_base + off)
                if v is None or math.isnan(v) or math.isinf(v):
                    v = 0.0
                timer = float(v) if v > 0.01 else None
                cap_key = bc.get("cap_setting")
                if cap_key:
                    cur_cap = float(duration_max.get(cap_key, 0.0) or 0.0)
                    if timer is not None and timer > cur_cap:
                        cur_cap = timer
                        duration_max[cap_key] = cur_cap
                    timer_max = cur_cap if cur_cap > 0 else 30.0
                else:
                    if timer is not None and timer > kronos_max:
                        kronos_max = timer
                    duration_max["kronos_freeze"] = kronos_max
                    timer_max = kronos_max
                entry = {
                    "index": idx, "zh": bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"], "ja": bc.get("ja", bc["zh"]),
                    "stacks": 1, "max_stacks": 1, "timer": timer, "timer_max": timer_max,
                    "timer_display": bc.get("timer_display", "any_stack"),
                }
            else:
                # ExStatus buff：按 sid 读；进场即定（角色一换出就立即确定 buff 槽位）——
                # 即使该 sid 当前不在 ExStatus（all_buffs 不含）也输出 buff 槽（stacks=0/timer=None），
                # 让 tick 专精过滤时已经知道"哪些 buff 应显示"，而不是等 buff 出现再判断
                sid = bc.get("sid")
                if sid is None or sid < 0:
                    continue
                if sid in all_buffs:
                    b = all_buffs[sid]
                    stacks = b["stacks"]
                    max_stacks = b["max_stacks"] or None
                    timer = None
                    timer_max = None
                    if not b["infinite"]:
                        timer = b["remaining"]
                        timer_max = b["initial"] or None
                        # 龙人化：游戏存的是「龙人槽」百分比读数(0~100)，折算成秒 = pct_cap * 读数 / 100
                        # 不能用 timer_max 当分母（旧写法 timer*timer_max 错，导致倒计时永远卡在 40s 不动）
                        pct_cap = bc.get("pct_cap")
                        if pct_cap and timer is not None:
                            timer = min(timer * pct_cap / 100.0, pct_cap)
                            timer_max = pct_cap
                else:
                    # 该 buff 当前不在场：神威一体(no_reserve)不预留槽位（仅 buff 生效时才显示）；
                    # 其余专属 buff 仍保留槽位以便设置面板和专精过滤（进场即定）
                    if bc.get("no_reserve"):
                        continue
                    stacks = 0
                    max_stacks = None
                    timer = None
                    timer_max = None
                entry = {
                    "index": idx, "zh": bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"], "ja": bc.get("ja", bc["zh"]),
                    "stacks": stacks, "max_stacks": max_stacks, "timer": timer, "timer_max": timer_max,
                    "timer_display": bc.get("timer_display", "any_stack"),
                }
            if entry is None:
                continue
            # 专精门控元数据 + 单层标记
            entry["single_layer"] = bool(bc.get("single_layer", False))
            entry["awakening"] = bool(bc.get("awakening", False))
            entry["truth"] = bool(bc.get("truth", False))
            entry["secret"] = bool(bc.get("secret", False))
            entry["group"] = None
            buffs_out.append(entry)

    return {"status": "ok", "dodge": dodge or 0, "char_type": char_type,
            "charid_hash": charid_hash, "pl_id": pl_id, "buffs": buffs_out,
            "all_buffs": all_buffs,  # V2050：gate 过滤后的全量 buff（供 core 模块查 sid 在场）
            "all_buffs_list": all_buffs_list,  # V2108：保留全部槽位（含同 sid 重复），供全 Buff 模块渲染重复实例
            "raw_locked": new_locked,
            "duration_max": duration_max}

def _resolve_id_actor(handle, actor):
    """伊德龙人态 actor 切换时，尝试用官方父子指针回到真身 actor。
    返回 (resolved_actor, is_dragon_form)。"""
    if not actor:
        return actor, False
    form = read_u8(handle, actor + ID_FORM_OFF) or 0
    if form == ID_FORM_DRAGON:
        parent = read_u64(handle, actor + ID_DRAGON_PARENT_OFF)
        if parent and parent >= 0x10000:
            real = parent + ID_DRAGON_PARENT_EXTRA
            if real and real >= 0x10000:
                return real, True
    return actor, form == ID_FORM_DRAGON

def read_skill_cooldowns(handle, char_base):
    if not char_base:
        return []
    ab_hashes = [0, 0, 0, 0]
    try:
        ab_bytes = rpm(handle, char_base + ABILITY_HASH_OFFSET, 16)
        if ab_bytes and len(ab_bytes) >= 16:
            ab_hashes = list(struct.unpack("<4I", ab_bytes))
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
    skills = []
    for i in range(4):
        try:
            cd_val = read_f32(handle, char_base + SKILL_SLOT_OFFSETS[i])
        except Exception:
            cd_val = None
        if cd_val is None or cd_val < 0 or cd_val > 9999 or cd_val != cd_val:
            cd_val = 0.0
        skills.append({
            "slot": i,
            "ability_hash": ab_hashes[i],
            "cd": cd_val,
            "ready": cd_val <= SKILL_READY_THRESHOLD,
        })
    return skills

# 锁定时需要减半不透明度的颜色键（仅标题栏、背景；图标/锁头保持原色原不透明度以便解锁）
LOCK_HALVED_KEYS = {"title_bar_color"}

# 尖刺圆模块（buff 指示）在「无buff隐藏」时需要调整不透明度的颜色键分组。
# 翻滚UI 与 冷却技能UI 不属于此分组，永远按其各自配置的不透明度显示，互不影响。
SPIKE_HIDDEN_KEYS = {
    "circle_color_normal", "circle_color_lv7",
    "spike_color_normal", "spike_color_lv7",
    "arc_color", "text_color", "dh_text_outline_color",
    "text_color_timer", "dh_text_outline_color_timer",
    "timer_text_color", "indicator_outline_color",
}

# ============================ Settings ============================
DEFAULT_SETTINGS = {
    "settings_schema_version": SETTINGS_SCHEMA_VERSION,
    "language": "zh",
    "scan_ms": 20,
    "circle_radius": 37,
    "spike_length": 64,
    "spike_axis_pos_percent": 12,
    "spike_width": 25,
    "spike_waist_pos_percent": 31,
    "spike_bead_radius": 3,
    "spike_bead_pos_percent": 9,
    "use_indicator_outline": False,
    "indicator_outline_width": 1,
    "title_bar_color": "#000000",
    "title_bar_color_opacity": 70,
    "titlebar_font_size": 8,
    "title_align": "left",
    "titlebar_status_indent": 16,
    "circle_color_normal": "#ffd500",
    "circle_color_normal_opacity": 100,
    "circle_color_lv7": "#f54fff",
    "circle_color_lv7_opacity": 100,
    "spike_color_normal": "#ffd500",
    "spike_color_normal_opacity": 100,
    "spike_color_lv7": "#f54fff",
    "spike_color_lv7_opacity": 100,
    # V2312：尖刺立体感——仅 2 种风格（flat / two_tone）+ 通用投影/暗描边。
    # V2311 留了 flat + highlight_line（错）；用户截图明确要 V2264 的两分面；本版把 highlight_line 改回 two_tone。
    "spike_3d_style": "two_tone",          # flat | two_tone — V2312 净简化（V2264 默认值 = two_tone）
    "spike_3d_shadow_enabled": True,
    "spike_3d_shadow_offset_x": 4,        # 投影 X 偏移（像素）
    "spike_3d_shadow_offset_y": 5,        # 投影 Y 偏移（像素）
    "spike_3d_shadow_alpha": 120,         # 投影不透明度 0-255
    "spike_3d_outline_enabled": True,
    "spike_3d_outline_width": 1.0,        # 暗描边宽度（像素）
    "spike_3d_outline_dark": 150,         # 暗描边 darker 因子 100-200
    # V2312：two_tone（V2264 最简两分面）参数——左右两半硬边分界，中间 0.48-0.52 窄过渡，无光向参与。
    "spike_3d_twotone_light": 130,        # two_tone 左半 lighter 因子 100-200
    "spike_3d_twotone_dark": 110,         # two_tone 右半 darker 因子 50-150
    # V2263：小球立体感——2 种风格 + 可调参数
    "bead_3d_style": "radial_gradient",   # flat | radial_gradient
    "bead_3d_light": 160,                 # 高光 lighter 因子 100-250
    "bead_3d_dark": 125,                  # 边缘 darker 因子 50-150
    "bead_3d_highlight_offset": 0.35,     # 高光中心偏移（相对小球半径）0.0-0.5
    "arc_color": "#ffd500",
    "text_color": "#ffffff",
    "text_color_opacity": 100,
    "dh_text_outline_color": "#000000",
    "dh_text_outline_color_opacity": 50,
    "timer_text_color": "#ffffff",
    "timer_text_color_opacity": 100,
    "indicator_outline_color": "#ffd500",
    "indicator_outline_color_opacity": 54,
    "use_default_dodge_icon": True,
    "shrimp_img_path": "",
    "dodge_icon_scale_percent": 100,
    "timer_style": "sector",
    "timer_arc_radius_offset": 5,
    "dh_font_size": 34,
    "timer_font_size": 9,
    "core_scale_percent": 73,
    "core_halign": "left",
    "core_valign": "bottom",
    "core_hmargin": 0,
    "core_vmargin": 400,
    "roll_scale_percent": 100,
    "roll_halign": "center",
    "roll_valign": "bottom",
    "roll_hmargin": 0,
    "roll_vmargin": 128,
    "skill_scale_percent": 100,
    "skill_halign": "right",
    "skill_valign": "bottom",
    "skill_hmargin": 730,
    "skill_vmargin": 60,
    "circle_pad_title": 0,
    "core_canvas_w": 0,
    "core_canvas_h": 0,
    "flash_color": "#ffffff",
    "flash_scale": 150,
    "flash_duration_ms": 167,
    "flash_apply_spikes": True,
    "flash_apply_skill_ready": True,
    "flash_apply_dodge": True,
    "warning_size_scale": 0.96,
    "warning_outline_width": 0.13,
    "warning_corner_radius": 5,
    "warning_outline_color": "#f54fff",
    "warning_fill_color": "#ffd500",
    # V2313：第 6/7 次样式二选一——"triangle"=程序绘制警告三角形（旧行为，默认）；"image"=用 PNG 代替
    "dodge_warning_mode": "triangle",
    "use_default_dodge_warning_icon": True,
    "dodge_warning_image_path": "",
    "dodge_warning_icon_scale_percent": 100,
    "roll_orientation": "horizontal",
    "core_window_x": 0,
    "core_window_y": 568,
    "roll_window_x": 816,
    "roll_window_y": 1006,
    "skill_window_x": 1142,
    "skill_window_y": 940,
    "center_text_offset_x": 0,
    "center_text_offset_y": 3,
    "dh_text_outline_width": 3,
    "dh_font_size_timer": 30,
    "center_text_offset_x_timer": 1,
    "center_text_offset_y_timer": -4,
    "dh_text_outline_width_timer": 3,
    "text_color_timer": "#ffffff",
    "text_color_timer_opacity": 100,
    "dh_text_outline_color_timer": "#000000",
    "dh_text_outline_color_timer_opacity": 50,
    "icon_color": "#ffd500",
    "roll_icon_opacity": 100,
    "timer_center_offset_y": 0,
    "auto_focus_minimize": True,
    "resolution_auto_scale": True,
    "startup_locked": True,
    "sync_exe_list": "",
    "lv7_timer_y_offset": 6,
    "lv7_timer_badge_width": 9,
    "single_timer_y_offset": 0,
    "single_timer_badge_width": 9,
    "single_timer_font_size": 11,
    "single_timer_text_color": "#ffffff",
    "single_timer_text_color_opacity": 100,
    "spike_hide_when_no_buff": True,
    "spike_hidden_opacity": 0,
    "show_spikes": True,
    "show_bead": True,
    "out_of_combat_hide": True,
    "out_of_combat_opacity": 0,
    "show_titlebar_status": True,
    "buff_enabled": {
        "PL0000_0": True,
        "PL0100_0": True,
        "PL0000_1": True,
        "PL0100_1": True,
        "PL0000_2": True,
        "PL0100_2": True,
        "PL0000_3": False,
        "PL0100_3": False,
        "PL0200_0": True,
        "PL0200_1": True,
        "PL0200_2": True,
        "PL0200_3": True,
        "PL0300_0": True,
        "PL0300_1": True,
        "PL0300_2": True,
        "PL0400_0": True,
        "PL0400_1": True,
        "PL0400_2": True,
        "PL0400_3": True,
        "PL0500_0": True,
        "PL0500_1": False,
        "PL0600_0": True,
        "PL0600_1": True,
        "PL0600_2": True,
        "PL0600_3": False,
        "PL0700_0": True,
        "PL0700_1": True,
        "PL0700_2": True,
        "PL0800_0": True,
        "PL0800_1": True,
        "PL0800_2": True,
        "PL0800_3": True,
        "PL0900_0": True,
        "PL0900_1": True,
        "PL0900_2": True,
        "PL0900_3": False,
        "PL1000_0": True,
        "PL1000_1": True,
        "PL1000_2": True,
        "PL1000_3": True,
        "PL1100_0": True,
        "PL1100_1": True,
        "PL1100_2": True,
        "PL1100_3": False,
        "PL1200_0": True,
        "PL1200_1": True,
        "PL1200_2": True,
        "PL1200_3": False,
        "PL1300_0": True,
        "PL1300_1": True,
        "PL1300_2": False,
        "PL1400_0": True,
        "PL1400_1": True,
        "PL1400_2": True,
        "PL1400_3": True,
        "PL1500_0": True,
        "PL1500_1": False,
        "PL1600_0": True,
        "PL1600_1": True,
        "PL1600_2": True,
        "PL1600_3": False,
        "PL1700_0": True,
        "PL1700_1": True,
        "PL1700_2": True,
        "PL1700_3": True,
        "PL1700_4": True,
        "PL1700_5": True,
        "PL1800_0": True,
        "PL1800_1": True,
        "PL1800_2": True,
        "PL1800_3": True,
        "PL1900_0": True,
        "PL1900_1": True,
        "PL1900_2": True,
        "PL1900_3": True,
        "PL1900_4": False,
        "PL2100_0": True,
        "PL2100_1": True,
        "PL2100_2": False,
        "PL2200_0": True,
        "PL2200_1": True,
        "PL2200_2": True,
        "PL2200_3": True,
        "PL2300_0": True,
        "PL2300_1": True,
        "PL2300_2": True,
        "PL2300_3": False,
        "PL2300_4": False,
        "PL2300_5": False,
        "PL2400_0": True,
        "PL2400_1": True,
        "PL2400_2": True,
        "PL2400_3": True,
        "PL2400_4": True,
        "PL2400_5": False,
        "PL2500_0": True,
        "PL2500_1": True,
        "PL2500_2": False,
        "PL2600_0": False,
        "PL2600_1": False,
        "PL2600_2": False,
        "PL2600_3": False,
        "PL2600_4": True,
        "PL2600_5": True,
        "PL2600_6": True,
        "PL2600_7": True,
        "PL2600_8": False,
        "PL2700_0": True,
        "PL2700_1": True,
        "PL2700_2": False,
        "PL2800_0": False,
        "PL2800_1": True,
        "PL2800_2": True,
        "PL2800_3": False,
        "PL2800_4": True,
        "PL2800_5": True,
        "PL2900_0": True,
        "PL2900_1": True,
        "PL2900_2": True
    },
    "buff_order": {
        "PL0000_0": 1,
        "PL0100_0": 1,
        "PL0000_1": 2,
        "PL0100_1": 2,
        "PL0000_2": 3,
        "PL0100_2": 3,
        "PL0000_3": 4,
        "PL0100_3": 4,
        "PL0200_0": 1,
        "PL0200_1": 2,
        "PL0200_2": 3,
        "PL0200_3": 4,
        "PL0300_0": 1,
        "PL0300_1": 2,
        "PL0300_2": 3,
        "PL0400_0": 1,
        "PL0400_1": 2,
        "PL0400_2": 3,
        "PL0400_3": 4,
        "PL0500_0": 1,
        "PL0500_1": 2,
        "PL0600_0": 1,
        "PL0600_1": 2,
        "PL0600_2": 3,
        "PL0600_3": 4,
        "PL0700_0": 1,
        "PL0700_1": 2,
        "PL0700_2": 3,
        "PL0800_0": 1,
        "PL0800_1": 2,
        "PL0800_2": 3,
        "PL0800_3": 4,
        "PL0900_0": 1,
        "PL0900_1": 2,
        "PL0900_2": 3,
        "PL0900_3": 4,
        "PL1000_0": 1,
        "PL1000_1": 2,
        "PL1000_2": 3,
        "PL1000_3": 4,
        "PL1100_0": 1,
        "PL1100_1": 2,
        "PL1100_2": 3,
        "PL1100_3": 4,
        "PL1200_0": 1,
        "PL1200_1": 2,
        "PL1200_2": 3,
        "PL1200_3": 4,
        "PL1300_0": 1,
        "PL1300_1": 2,
        "PL1300_2": 3,
        "PL1400_0": 1,
        "PL1400_1": 2,
        "PL1400_2": 3,
        "PL1400_3": 4,
        "PL1500_0": 1,
        "PL1500_1": 2,
        "PL1600_0": 1,
        "PL1600_1": 2,
        "PL1600_2": 3,
        "PL1600_3": 4,
        "PL1700_0": 1,
        "PL1700_1": 2,
        "PL1700_2": 3,
        "PL1700_3": 4,
        "PL1700_4": 5,
        "PL1700_5": 6,
        "PL1800_0": 1,
        "PL1800_1": 2,
        "PL1800_2": 3,
        "PL1800_3": 4,
        "PL1900_0": 1,
        "PL1900_1": 2,
        "PL1900_2": 3,
        "PL1900_3": 4,
        "PL1900_4": 5,
        "PL2100_0": 1,
        "PL2100_1": 2,
        "PL2100_2": 3,
        "PL2200_0": 1,
        "PL2200_1": 2,
        "PL2200_2": 3,
        "PL2200_3": 4,
        "PL2300_0": 1,
        "PL2300_1": 2,
        "PL2300_2": 3,
        "PL2300_3": 4,
        "PL2300_4": 5,
        "PL2300_5": 6,
        "PL2400_0": 1,
        "PL2400_1": 2,
        "PL2400_2": 3,
        "PL2400_3": 4,
        "PL2400_4": 5,
        "PL2400_5": 6,
        "PL2500_0": 1,
        "PL2500_1": 2,
        "PL2500_2": 3,
        "PL2600_0": 1,
        "PL2600_1": 2,
        "PL2600_2": 3,
        "PL2600_3": 4,
        "PL2600_4": 5,
        "PL2600_5": 6,
        "PL2600_6": 7,
        "PL2600_7": 8,
        "PL2600_8": 9,
        "PL2700_0": 1,
        "PL2700_1": 2,
        "PL2700_2": 3,
        "PL2800_0": 1,
        "PL2800_1": 2,
        "PL2800_2": 3,
        "PL2800_3": 4,
        "PL2800_4": 5,
        "PL2800_5": 6,
        "PL2900_0": 1,
        "PL2900_1": 2,
        "PL2900_2": 3
    },
    "buff_mastery": {
        "PL0000_0": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL0100_0": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL0000_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL0100_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL0000_2": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0100_2": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0000_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL0100_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL0200_0": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL0200_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL0200_2": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0200_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0300_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0300_1": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0300_2": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0400_0": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0400_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0400_2": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0400_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0500_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0500_1": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL0600_0": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0600_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0600_2": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0600_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL0700_0": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL0700_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL0700_2": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0800_0": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0800_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0800_2": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL0800_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL0900_0": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL0900_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL0900_2": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL0900_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL1000_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1000_1": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1000_2": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL1000_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1100_0": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL1100_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1100_2": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1100_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL1200_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1200_1": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1200_2": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL1200_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL1300_0": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1300_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL1300_2": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL1400_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1400_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1400_2": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1400_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1500_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1500_1": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL1600_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1600_1": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1600_2": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL1600_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL1700_0": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1700_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1700_2": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1700_3": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL1700_4": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1700_5": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1800_0": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL1800_1": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1800_2": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1800_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1900_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL1900_1": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1900_2": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1900_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL1900_4": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2100_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL2100_1": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2100_2": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2200_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL2200_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL2200_2": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL2200_3": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL2300_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL2300_1": {
            "awakening": False,
            "truth": True,
            "secret": True
        },
        "PL2300_2": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2300_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2300_4": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2300_5": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2400_0": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL2400_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL2400_2": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2400_3": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2400_4": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL2400_5": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2500_0": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2500_1": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL2500_2": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2600_0": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2600_1": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2600_2": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2600_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2600_4": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2600_5": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2600_6": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2600_7": {
            "awakening": False,
            "truth": True,
            "secret": False
        },
        "PL2600_8": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2700_0": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL2700_1": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL2700_2": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2800_0": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2800_1": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL2800_2": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL2800_3": {
            "awakening": False,
            "truth": False,
            "secret": False
        },
        "PL2800_4": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL2800_5": {
            "awakening": True,
            "truth": True,
            "secret": True
        },
        "PL2900_0": {
            "awakening": True,
            "truth": False,
            "secret": False
        },
        "PL2900_1": {
            "awakening": False,
            "truth": False,
            "secret": True
        },
        "PL2900_2": {
            "awakening": True,
            "truth": True,
            "secret": True
        }
    },
    "buff_order_direction": "ltr",
    "multi_buff_scale_2": 100,
    "multi_buff_hgap_2": 206,
    "multi_buff_dy_2": 51,
    "multi_buff_ext_color_2": False,
    "multi_buff_int_color_2": False,
    "multi_buff_color_mode_2": "monochrome",
    "multi_buff_mono_span_2": -15,
    "multi_buff_scale_3": 100,
    "multi_buff_hgap_3": 201,
    "multi_buff_dy_3": 45,
    "multi_buff_ext_color_3": False,
    "multi_buff_int_color_3": False,
    "multi_buff_color_mode_3": "monochrome",
    "multi_buff_mono_span_3": 15,
    "multi_buff_scale_4": 95,
    "multi_buff_hgap_4": 135,
    "multi_buff_dy_4": -53,
    "multi_buff_ext_color_4": False,
    "multi_buff_int_color_4": False,
    "multi_buff_color_mode_4": "monochrome",
    "multi_buff_mono_span_4": 15,
    "multi_buff_scale_5": 82,
    "multi_buff_hgap_5": 92,
    "multi_buff_dy_5": 22,
    "multi_buff_ext_color_5": False,
    "multi_buff_int_color_5": False,
    "multi_buff_color_mode_5": "monochrome",
    "multi_buff_mono_span_5": 15,
    "show_buff_name": True,
    "buff_name_font_size": 8,
    "buff_name_offset_x": 0,
    "buff_name_offset_y": 6,
    "buff_name_bg_width": -4,
    "buff_name_color": "#ffffff",
    "buff_name_color_opacity": 90,
    "show_core_module": True,
    "show_roll_module": True,
    "show_skill_cd_module": True,
    "skill_cd_size": 24,
    "skill_cd_spread": 39,
    "skill_cd_color": "#ffd500",
    "skill_cd_capsule_bg": "#000000",
    "skill_cd_capsule_border": "#000000",
    "skill_cd_text_color": "#ffffff",
    "skill_cd_show_name": True,
    "skill_cd_name_font_size": 7,
    "skill_cd_name_offset_x": 0,
    "skill_cd_name_offset_y": 12,
    "skill_cd_name_bg_width": 0,
    "skill_cd_font_size": 9,
    "skill_cd_capsule_width": 1,
    "skill_cd_timer_offset_x": 0,
    "skill_cd_timer_offset_y": 0,
    "skill_cd_name_color": "#ffffff",
    "skill_cd_bg_opacity": 5,
    "skill_cd_sector_opacity": 90,
    "skill_cd_border_opacity": 90,
    "skill_cd_capsule_opacity": 80,
    "skill_cd_border_scale": 1.35,
    "skill_cd_breath_enabled": True,
    "skill_cd_breath_color": "#ffffff",
    "skill_cd_breath_color_opacity": 50,
    "skill_cd_breath_freq": 1.5,
    "skill_cd_breath_soft": 0.1,
    "skill_cd_breath_scale": 1.0,
    "skill_cooldown_max": {
        "AB_PL0400_05": 19.999998092651367,
        "AB_PL0400_02": 19.999998092651367,
        "AB_PL0400_07": 150.0,
        "AB_PL0400_03": 134.88803100585938,
        "AB_PL0000_02": 34.20000076293945,
        "AB_PL0000_03": 64.79999542236328,
        "AB_PL0000_10": 11.399999618530273,
        "AB_PL0000_01": 34.16654586791992,
        "AB_PL0800_06": 34.79999923706055,
        "AB_PL0300_05": 56.999996185302734,
        "AB_PL0300_03": 72.0,
        "AB_PL0300_06": 67.99999237060547,
        "AB_PL0300_01": 18.999998092651367,
        "AB_PL2100_05": 79.99999237060547,
        "AB_PL2100_07": 119.99999237060547,
        "AB_PL1700_01": 15.999999046325684,
        "AB_PL1700_04": 182.39999389648438,
        "AB_PL0700_05": 21.566556930541992,
        "AB_PL0700_06": 64.79999542236328,
        "AB_PL1700_03": 31.999998092651367,
        "AB_PL1900_06": 88.19999694824219,
        "1061903518": 110.0,
        "410537208": 19.599998474121094,
        "AB_PL1900_04": 180.0,
        "AB_PL1900_05": 29.39999771118164,
        "AB_PL1900_07": 58.79999542236328,
        "8315566": 88.19999694824219,
        "4211050552": 34.20000076293945,
        "AB_PL0400_06": 75.99999237060547,
        "AB_PL2500_02": 79.99999237060547,
        "AB_PL2500_03": 81.0,
        "AB_PL2500_04": 75.99999237060547,
        "AB_PL0900_08": 146.97265625,
        "AB_PL0900_07": 58.79999542236328,
        "AB_PL0900_05": 29.383329391479492,
        "AB_PL0900_04": 29.374990463256836,
        "AB_PL0700_01": 50.99166488647461,
        "823262814": 35.0,
        "3372778876": 46.79999542236328,
        "AB_PL2400_06": 22.5,
        "AB_PL2300_08": 188.99998474121094,
        "AB_PL2300_02": 162.0,
        "AB_PL2200_08": 377.9999694824219,
        "AB_PL2200_02": 29.39999771118164,
        "AB_PL1700_06": 41.14895248413086,
        "3496260479": 34.991661071777344,
        "AB_PL2800_04": 14.69999885559082,
        "4011919540": 70.19999694824219,
        "AB_PL0700_07": 130.5,
        "AB_PL0900_03": 53.999996185302734,
        "AB_PL1100_05": 98.39999389648438,
        "AB_PL1100_06": 87.29999542236328,
        "AB_PL1100_03": 77.5999984741211,
        "AB_PL1100_01": 14.549999237060547,
        "AB_PL2100_02": 44.99153518676758,
        "AB_PL0200_06": 107.99999237060547,
        "AB_PL0600_02": 23.999998092651367,
        "AB_PL0600_06": 95.0,
        "AB_PL0600_05": 93.5,
        "AB_PL0600_04": 25.499998092651367,
        "AB_PL2600_08": 142.5,
        "AB_PL2600_03": 45.0,
        "AB_PL2600_05": 56.999996185302734,
        "1113019419": 11.399999618530273,
        "2861865630": 22.799999237060547,
        "AB_PL0800_02": 104.375,
        "AB_PL0800_08": 43.4832763671875,
        "AB_PL0800_01": 10.4399995803833,
        "AB_PL2600_06": 45.0,
        "AB_PL2600_01": 19.999998092651367,
        "AB_PL0300_08": 97.19999694824219,
        "AB_PL0300_04": 18.0,
        "AB_PL1600_08": 26.099998474121094,
        "AB_PL2800_01": 44.099998474121094,
        "AB_PL2800_05": 44.099998474121094,
        "AB_PL0700_04": 60.79999542236328,
        "AB_PL2600_02": 14.999999046325684,
        "AB_PL2300_07": 111.59999084472656,
        "AB_PL2300_01": 74.39999389648438,
        "AB_PL2300_06": 21.599998474121094,
        "AB_PL2300_03": 34.20000076293945,
        "AB_PL2000_05": 79.19999694824219,
        "AB_PL2000_02": 52.79999542236328,
        "AB_PL2000_03": 35.19999694824219,
        "AB_PL2900_07": 38.25,
        "AB_PL2900_04": 50.999996185302734,
        "AB_PL2900_03": 14.399999618530273,
        "AB_PL2900_05": 48.599998474121094
    },
    "class_duration_max": 7.18333101272583,
    "kronos_freeze_max": 10.0,
    "auto_check_update": True,
    "enable_sync_exe_list": True,
    "skip_version": "",
    "update_check_url": "https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases/latest/download/version.json",
    "update_download_url": "",
    "custom_palette": [
        "#ff1764",
        "#ffffff",
        "#f32f2c",
        "#ffffff",
        "#ff80a0",
        "#ffffff",
        "#f552f5",
        "#ffffff",
        "#ff1777",
        "#ffffff",
        "#f54fff",
        "#ffffff",
        "#ffffff",
        "#ffffff",
        "#ffffff",
        "#ffffff"
    ],
    "global_hotkey_show_enabled": True,
    "global_hotkey_show": "17,219",
    "global_hotkey_lock_enabled": True,
    "global_hotkey_lock": "17,221",
    "global_hotkey_settings_enabled": True,
    "global_hotkey_settings": "17,186",
    "global_hotkey_key": "k",
    "titlebar_icon_indent": 16,
    "global_hotkey_enabled": True,
    "grace_max": 20.0,
    "pos_res_normalized": True,
    "show_allbuff_module": True,
    "allbuff_window_x": 305,
    "allbuff_window_y": 1114,
    "allbuff_scale_percent": 80,
    "allbuff_halign": "center",
    "allbuff_valign": "bottom",
    "allbuff_hmargin": 0,
    "allbuff_vmargin": 0,
    "allbuff_per_row": 20,
    "allbuff_rows": 1,
    "allbuff_row_spacing": 2,
    "allbuff_card_spacing": 2,
    "allbuff_sort_mode": "appearance",
    "allbuff_row_align": "center",
    "allbuff_seq_gone_grace_sec": 0.2,
    "allbuff_name_font_size": 9,
    "allbuff_name_color": "#ffd500",
    "allbuff_stacks_font_size": 9,
    "allbuff_stacks_color": "#ffd500",
    "allbuff_time_font_size": 9,
    "allbuff_time_color": "#ffffff",
    "allbuff_bar_color": "#ffd500",
    "allbuff_bar_color_opacity": 100,
    "allbuff_bar_width": 70,
    "allbuff_bar_height": 14,
    "allbuff_bar_frame_thickness": 1,
    "allbuff_backing_color": "#000000",
    "allbuff_backing_color_opacity": 40,
    "allbuff_backing_width": 75,
    "allbuff_backing_height": 48,
    "allbuff_canvas_bg_opacity": 0,
    "allbuff_element_spacing": 0,
    "allbuff_row_height_extra": 0,
    "allbuff_exclude_core": True,
    "allbuff_exclude_infinite": False,
    "allbuff_exclude_exclusive": True,
    "allbuff_exclude_mastery": True,
    "allbuff_exclude_single": False,
    "allbuff_gate_enabled_stacks_max": True,
    "allbuff_gate_stacks_max": 100,
    "allbuff_gate_enabled_max_stacks_max": True,
    "allbuff_gate_max_stacks_max": 100,
    "allbuff_gate_enabled_status_id_max": True,
    "allbuff_gate_status_id_max": 3000,
    "allbuff_gate_enabled_sub_id_max": False,
    "allbuff_gate_sub_id_max": 65535,
    "allbuff_gate_enabled_min_remaining_time": True,
    "allbuff_gate_min_remaining_time": 0.1,
    "allbuff_gate_enabled_min_initial_time": True,
    "allbuff_gate_min_initial_time": 0.5,
    "allbuff_gate_enabled_min_appearance_time": True,
    "allbuff_gate_min_appearance_time": 0.1,
    "allbuff_gate_check_nan_inf": True,
    "allbuff_gate_filter_status_id_zero_one_infinite_enabled": True,
    "allbuff_gate_check_min_time_enabled": True,
    "allbuff_gate_rem_gt_init_drop": True,
    "allbuff_gate_min_time": 0.1,
    "allbuff_gate_enabled_duration_max": True,
    "allbuff_gate_duration_max_with_infinite_exemption": 10000.0,
    "multi_buff_whitelist": [
        {
            "sid": 7,
            "name_zh": "追击",
            "name_zh_tw": "追擊",
            "name_en": "Pursuit"
        },
        {
            "sid": 42,
            "name_zh": "造成伤害UP",
            "name_zh_tw": "給予傷害UP",
            "name_en": "DMG↑"
        },
        {
            "sid": 0,
            "name_zh": "攻击UP",
            "name_zh_tw": "攻擊UP",
            "name_en": "ATK↑"
        },
        {
            "sid": 1,
            "name_zh": "防御UP",
            "name_zh_tw": "防禦UP",
            "name_en": "DEF↑"
        },
        {
            "sid": 56,
            "name_zh": "伤害上限UP",
            "name_zh_tw": "傷害上限UP",
            "name_en": "DMG Cap↑"
        },
        {
            "sid": 57,
            "name_zh": "叠加攻击Up",
            "name_zh_tw": "累積攻擊UP",
            "name_en": "Stackable ATK↑"
        },
        {
            "sid": 58,
            "name_zh": "叠加防御UP",
            "name_zh_tw": "累積防禦UP",
            "name_en": "Stackable DEF↑"
        }
    ],
    "multi_buff_blacklist": [
        {
            "sid": 146,
            "name_zh": "纯白之境",
            "name_zh_tw": "白堊境界",
            "name_en": "Proto-White World"
        },
        {
            "sid": 1020,
            "name_zh": "阿尔贝斯之印",
            "name_zh_tw": "亞爾貝斯‧菲爾瑪雷",
            "name_en": "Arvess Fermare"
        },
        {
            "sid": 36,
            "name_zh": "深渊荣耀",
            "name_zh_tw": "深淵榮耀",
            "name_en": "Abyssal Glory"
        },
        {
            "sid": 129,
            "name_zh": "混沌转换",
            "name_zh_tw": "混沌輪迴",
            "name_en": "Chaos Shift"
        },
        {
            "sid": 149,
            "name_zh": "世界裂痕",
            "name_zh_tw": "龜裂世界",
            "name_en": "Fractured World"
        },
        {
            "sid": 1021,
            "name_zh": "元素不和",
            "name_zh_tw": "元素不和",
            "name_en": "Elemental Friction"
        },
        {
            "sid": 32,
            "name_zh": "狂暴",
            "name_zh_tw": "狂暴氣場",
            "name_en": "Bloodthirst"
        }
    ],
    "allbuff_warn_enabled": True,
    "allbuff_warn_threshold_pct": 18,
    "allbuff_warn_color": "#ff80a0",
    "allbuff_warn_color_opacity": 100,
    "show_boss_module": True,
    "boss_window_x": 201,
    "boss_window_y": 8,
    "boss_scale_percent": 80,
    "boss_halign": "center",
    "boss_valign": "top",
    "boss_hmargin": 0,
    "boss_vmargin": 10,
    "boss_per_row": 20,
    "boss_rows": 1,
    "boss_row_spacing": 2,
    "boss_card_spacing": 2,
    "boss_sort_mode": "appearance",
    "boss_seq_gone_grace_sec": 0.2,
    "boss_name_font_size": 11,
    "boss_name_color": "#f54fff",
    "boss_stacks_font_size": 10,
    "boss_stacks_color": "#f54fff",
    "boss_time_font_size": 10,
    "boss_time_color": "#ffffff",
    "boss_bar_color": "#f54fff",
    "boss_bar_color_opacity": 100,
    "boss_bar_width": 83,
    "boss_bar_height": 11,
    "boss_bar_frame_thickness": 1,
    "boss_backing_color": "#000000",
    "boss_backing_color_opacity": 40,
    "boss_backing_width": 80,
    "boss_backing_height": 64,
    "boss_canvas_bg_opacity": 0,
    "boss_element_spacing": -1,
    "boss_row_height_extra": -1,
    "boss_exclude_core": False,
    "boss_exclude_infinite": False,
    "boss_exclude_single": False,
    "boss_row_align": "center",
    "boss_gate_enabled_stacks_max": True,
    "boss_gate_stacks_max": 100,
    "boss_gate_enabled_max_stacks_max": True,
    "boss_gate_max_stacks_max": 100,
    "boss_gate_enabled_status_id_max": True,
    "boss_gate_status_id_max": 3000,
    "boss_gate_enabled_sub_id_max": False,
    "boss_gate_sub_id_max": 65535,
    "boss_gate_enabled_min_remaining_time": True,
    "boss_gate_min_remaining_time": 0.1,
    "boss_gate_enabled_min_initial_time": True,
    "boss_gate_min_initial_time": 0.5,
    "boss_gate_enabled_min_appearance_time": True,
    "boss_gate_min_appearance_time": 0.1,
    "boss_gate_check_nan_inf": True,
    "boss_gate_filter_status_id_zero_one_infinite_enabled": True,
    "boss_gate_check_min_time_enabled": True,
    "boss_gate_rem_gt_init_drop": True,
    "boss_gate_min_time": 0.1,
    "boss_gate_enabled_duration_max": True,
    "boss_gate_duration_max_with_infinite_exemption": 10000.0,
    "boss_warn_enabled": True,
    "boss_warn_threshold_pct": 20,
    "boss_warn_color": "#ffd500",
    "boss_warn_color_opacity": 100,
    "boss_debuff_name_color": "#ffd500",
    "boss_debuff_stacks_color": "#ffd500",
    "boss_debuff_time_color": "#ffffff",
    "boss_debuff_bar_color": "#ffd500",
    "boss_debuff_warn_enabled": True,
    "boss_debuff_warn_color": "#ff80a0",
    "boss_debuff_warn_color_opacity": 100,
    "boss_blacklist": [
        {
            "sid": 9,
            "name_zh": "幻影",
            "name_zh_tw": "幻影",
            "name_en": "Mirror Image"
        },
        {
            "sid": 8,
            "name_zh": "霸体",
            "name_zh_tw": "畏怯無效",
            "name_en": "Stout Heart"
        },
        {
            "sid": 10,
            "name_zh": "挺身而出",
            "name_zh_tw": "挺身掩護",
            "name_en": "Substitute"
        },
        {
            "sid": 11,
            "name_zh": "安全",
            "name_zh_tw": "庇護",
            "name_en": "Covered"
        },
        {
            "sid": 20,
            "name_zh": "豪胆",
            "name_zh_tw": "堅毅",
            "name_en": "Guts"
        },
        {
            "sid": 24,
            "name_zh": "挑衅力UP",
            "name_zh_tw": "敵對心UP",
            "name_en": "Hostility↑"
        },
        {
            "sid": 54,
            "name_zh": "疾天",
            "name_zh_tw": "疾天",
            "name_en": "Sage"
        },
        {
            "sid": 55,
            "name_zh": "红天",
            "name_zh_tw": "紅天",
            "name_en": "Cardinal"
        },
        {
            "sid": 25,
            "name_zh": "自动复活",
            "name_zh_tw": "自動復活",
            "name_en": "Autorevive"
        },
        {
            "sid": 125,
            "name_zh": "钳蟹的报恩",
            "name_zh_tw": "同心蟹力",
            "name_en": "Pincer Synergy"
        },
        {
            "sid": 37,
            "name_zh": "最大HP减少",
            "name_zh_tw": "最大HP減少",
            "name_en": "Max HP↓"
        }
    ],
    "boss_multi_list": [
        {
            "sid": 7
        },
        {
            "sid": 42
        },
        {
            "sid": 59,
            "name_zh": "叠加防御DOWN",
            "name_zh_tw": "累積防禦DOWN",
            "name_en": "Stackable DEF↓"
        },
        {
            "sid": 1000,
            "name_zh": "中毒",
            "name_zh_tw": "中毒",
            "name_en": "Poison"
        },
        {
            "sid": 1020,
            "name_zh": "阿尔贝斯之印",
            "name_zh_tw": "亞爾貝斯‧菲爾瑪雷",
            "name_en": "Arvess Fermare"
        },
        {
            "sid": 67,
            "name_zh": "叠加攻击DOWN",
            "name_zh_tw": "累積攻擊DOWN",
            "name_en": "Stackable ATK↓"
        },
        {
            "sid": 2,
            "name_zh": "攻击DOWN",
            "name_zh_tw": "攻擊DOWN",
            "name_en": "ATK↓"
        },
        {
            "sid": 3,
            "name_zh": "防御DOWN",
            "name_zh_tw": "防禦DOWN",
            "name_en": "DEF↓"
        },
        {
            "sid": 0,
            "name_zh": "攻击UP",
            "name_zh_tw": "攻擊UP",
            "name_en": "ATK↑"
        },
        {
            "sid": 1,
            "name_zh": "防御UP",
            "name_zh_tw": "防禦UP",
            "name_en": "DEF↑"
        }
    ],
    "boss_debuff_bar_color_opacity": 100,
    "allbuff_debuff_name_color": "#f54fff",
    "allbuff_debuff_stacks_color": "#f54fff",
    "allbuff_debuff_time_color": "#ffffff",
    "allbuff_debuff_bar_color": "#f54fff",
    "allbuff_debuff_warn_enabled": True,
    "allbuff_debuff_warn_color": "#ffd500",
    "allbuff_debuff_warn_color_opacity": 100,
    "icon_color_opacity": 100,
    "arc_color_opacity": 100,
    "skill_cd_color_opacity": 100,
    "skill_cd_text_color_opacity": 100,
    "skill_cd_name_color_opacity": 100,
    "allbuff_debuff_bar_color_opacity": 100,
    # ── V2304：调试数据（不开游戏也能测 UI）。全部只在「调试数据」选项卡里调，默认全关 ──
    "debug_data_enabled": False,        # 主开关：开启后 scan() 直接注入假数据，不再读游戏内存
    "debug_text": "测试带编码",         # 统一显示文本（buff 名 / Boss buff 名 / 技能名）
    "debug_countdown": 8.88,            # 固定倒计时（秒）
    "debug_status": "ok",               # 模拟状态：ok / no_char / no_game / init
    "debug_in_combat": True,            # 模拟「战斗中」（用于验证非战斗隐藏）
    "debug_mastery": "",                # 模拟专精：空 / awakening / truth / secret
    "debug_core_buff_count": 3,         # 核心检测：buff 数量
    "debug_core_single_layer": False,   # 核心检测：是否单层 buff
    "debug_core_full_stacks": True,     # 核心检测：是否满层
    "debug_core_stacks": 1,             # 核心检测：非满层时的层数
    "debug_core_max_stacks": 8,         # 核心检测：最大层数
    "debug_core_awakening": False,      # 核心检测：标记为觉醒专精 buff
    "debug_core_truth": False,          # 核心检测：标记为真谛专精 buff
    "debug_core_secret": False,         # 核心检测：标记为秘义专精 buff
    # V2309：调试注入各类别数量（替代原「卡片数量」+「是否永续」；直接控制每类假 buff 个数，方便离线调试呈现更多可能性）
    "debug_allbuff_normal": 8,          # 全 Buff：普通 Buff 数量
    "debug_allbuff_debuff": 2,          # 全 Buff：Debuff 数量
    "debug_allbuff_perma": 1,           # 全 Buff：永续（∞）数量
    "debug_allbuff_coda": 1,            # 全 Buff：尾声（接近结束）数量
    "debug_allbuff_stacks": 8,          # 全 Buff：层数
    "debug_allbuff_max_stacks": 8,      # 全 Buff：最大层数
    "debug_boss_normal": 5,             # Boss：普通 Buff 数量
    "debug_boss_debuff": 1,             # Boss：Debuff 数量
    "debug_boss_perma": 1,              # Boss：永续（∞）数量
    "debug_boss_coda": 1,               # Boss：尾声（接近结束）数量
    "debug_boss_stacks": 8,             # Boss：层数
    "debug_boss_max_stacks": 8,         # Boss：最大层数
    "debug_skill_count": 4,             # 能力冷却：占用槽位数 0-4
    "debug_skill_ready_count": 1,       # 能力冷却：前 N 个显示为就绪
    "debug_skill_cd_max": 30.0,         # 能力冷却：冷却上限（决定扇形进度）
    "debug_dodge_count": 7              # 翻滚：翻滚次数
}

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 旧版 alpha(0-255) → 新版 opacity(0-100) 迁移
        _ALPHA_TO_OPACITY = {
            "skill_cd_bg_alpha": "skill_cd_bg_opacity",
            "skill_cd_sector_alpha": "skill_cd_sector_opacity",
            "skill_cd_border_alpha": "skill_cd_border_opacity",
            "skill_cd_capsule_alpha": "skill_cd_capsule_opacity",
        }
        for old_key, new_key in _ALPHA_TO_OPACITY.items():
            if old_key in data and new_key not in data:
                try:
                    data[new_key] = max(0, min(100, int(round(data[old_key] * 100 / 255))))
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
        # 旧版 buff_enabled 键 "0xXX_idx" -> "PLXXXX_idx" 迁移
        if "buff_enabled" in data:
            old_map = data["buff_enabled"]
            new_map = {}
            migrated = False
            for k, v in old_map.items():
                if isinstance(k, str) and k.startswith("0x"):
                    parts = k.split("_")
                    if len(parts) == 2:
                        try:
                            ct = int(parts[0], 16)
                            idx = int(parts[1])
                            pl = CHAR_TYPE_TO_PL.get(ct)
                            if pl:
                                new_map[f"{pl}_{idx}"] = v
                                migrated = True
                                continue
                        except Exception:
                            logger.debug("swallowed exception", exc_info=True)
                new_map[k] = v
            if migrated:
                data["buff_enabled"] = new_map
        # 由 buff_enabled 推导 buff_order（rank: 1-based, 0=不显示），兼容老存档与默认
        if "buff_enabled" in data and "buff_order" not in data:
            order = {}
            for k, v in data["buff_enabled"].items():
                if isinstance(k, str) and "_" in k:
                    _, idx_s = k.rsplit("_", 1)
                    try:
                        idx = int(idx_s)
                    except ValueError:
                        continue
                    order[k] = (idx + 1) if v else 0
            data["buff_order"] = order
        # 删除已废弃的 Class 倒计时「手动」上限键（V342 起移除手动输入框；自动学习键 class_duration_max 保留）
        data.pop("class_duration_manual", None)
        # V2009 起开机自启功能已删除；清理旧存档残留键，避免随 merged 写回磁盘
        data.pop("autostart_enabled", None)

        # 旧版多buff参数（全局单组：multi_buff_scale / _external_color / _internal_color）
        # → 新版按buff个数分组（映射到 2-buff 组，保留用户习惯）
        _OLD_MB = {
            "multi_buff_scale": "multi_buff_scale_2",
            "multi_buff_external_color": "multi_buff_ext_color_2",
            "multi_buff_internal_color": "multi_buff_int_color_2",
        }
        for _old_k, _new_k in _OLD_MB.items():
            if _old_k in data and _new_k not in data:
                try:
                    data[_new_k] = data[_old_k]
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
        # V2034：旧的「隐藏尖刺与装饰小球」/「仅隐藏上面的尖刺」两个 hide 选项
        # → 新的「显示尖刺」/「显示装饰小球」两个独立 show 开关（互为相反语义）：
        #   hide_spikes_and_beads=True → 两者都藏 → show_spikes=False, show_bead=False
        #   hide_spikes_only=True      → 仅藏尖刺  → show_spikes=False, show_bead=True
        #   两者都未勾                 → 都显示    → show_spikes=True,  show_bead=True
        _old_hide_all = data.pop("hide_spikes_and_beads", None)
        _old_hide_only = data.pop("hide_spikes_only", None)
        if _old_hide_all is not None or _old_hide_only is not None:
            _both = bool(_old_hide_all)
            _only = bool(_old_hide_only)
            data["show_spikes"] = not (_both or _only)
            data["show_bead"] = not _both
        # ─────────────────────────── 向后兼容合并 ───────────────────────────
        # 设计原则：发版一般只改 UI/逻辑，配置格式几乎不变；因此「schema 版本不同」不再清空
        # 任何用户配置。始终以 DEFAULT_SETTINGS 为基底，用磁盘上的用户数据覆盖（保留全部同名
        # key，包括 buff_order / buff_enabled / buff_mastery）。上方已执行的迁移
        # （alpha→opacity、0xXX→PLxxxx、buff_enabled→buff_order、旧 multi_buff→分组）只增不改，
        # 向后兼容。这样老存档（V334/85、V335/86…）升级到新版时，用户所有调好的参数都原样保留。
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        # V303：强制更新地址用 release CDN（旧 raw.githubusercontent.com 被墙/慢），不被旧存档覆盖
        merged["update_check_url"] = DEFAULT_SETTINGS["update_check_url"]
        # 对齐到当前 schema（不再因 schema 变化而触发丢弃）
        merged["settings_schema_version"] = SETTINGS_SCHEMA_VERSION
        # V2216：清理 V2215 及更早版本「过滤 status_id == 0」复选框对应的旧 settings 键
        # （复选框已删除，filter 固化为常闭——这些 key 留着只是占空间且永远不会被读）
        for _obsolete in ("allbuff_gate_filter_status_id_zero", "boss_gate_filter_status_id_zero"):
            merged.pop(_obsolete, None)
        # 固化迁移结果（确保 alpha→opacity 等已写回磁盘）
        save_settings(merged)
        return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.debug("swallowed exception", exc_info=True)

def qcolor(hex_value, fallback="#ffffff"):
    color = QColor(hex_value or fallback)
    return color if color.isValid() else QColor(fallback)

def rotate_hue(hex_value, deg):
    """将颜色按色相旋转 deg 度（保持饱和度/明度），用于多buff差异化着色。"""
    c = QColor(hex_value or "#ffffff")
    if not c.isValid():
        return "#ffffff"
    h, s, v, a = c.getHsv()
    if h < 0:
        h = 0
    h = (int(h) + int(deg)) % 360
    c.setHsv(h, s, v, a)
    return c.name()

# ============================ Settings Dialog ============================
class MasteryBuffGroup(QWidget):
    """专精门控 buff 组（V302）：每角色一个可拖拽列表，每行 = buff 名 + 觉醒/真谛/秘义 三勾选框。

    列标题 = 该角色三系专精名（MASTERY_BRANCHES[pl_id]，三语随语言切换）。
    拖拽排序 → buff_order（上→下 = 多 buff 界面左→右）；勾选 → buff_mastery。
    三框全选=常显，全不选=常关，单选/多选=仅当 current_mastery 命中选中项才显示。
    古兰/姬塔（PL0000/PL0100）合并为一组；伊德/龙人（PL1900）为一组。
    """
    orderChanged = Signal()

    def __init__(self, pl_ids, profile, buff_order, buff_mastery, lang="zh"):
        super().__init__()
        self.pl_ids = list(pl_ids)
        self.canon = pl_ids[0]
        self.profile = profile
        self.lang = lang
        self._loading = False
        self._collapsed = True
        outer = QVBoxLayout(self); outer.setContentsMargins(4, 4, 4, 4); outer.setSpacing(2)
        # 标题行
        hdr = QHBoxLayout(); hdr.setContentsMargins(0, 0, 0, 0); hdr.setSpacing(4)
        self._collapse_btn = QToolButton(); self._collapse_btn.setFixedSize(18, 18)
        self._collapse_btn.setStyleSheet("QToolButton{border:none;color:#cfe0ff;font-weight:bold;font-size:12px;}")
        self._title_lbl = QLabel(self._title_text(lang))
        self._title_lbl.setStyleSheet("color:#cfe0ff;font-weight:bold;font-size:11px;")
        hdr.addWidget(self._collapse_btn); hdr.addWidget(self._title_lbl); hdr.addStretch()
        outer.addLayout(hdr)
        # 主体（可折叠）
        self._body = QWidget()
        bl = QVBoxLayout(self._body); bl.setContentsMargins(2, 2, 2, 2); bl.setSpacing(3)
        # 列标题：与每行布局严格对齐（左=Buff名占位，右=三专精名）
        self._col_lbls_layout = QHBoxLayout(); self._col_lbls_layout.setContentsMargins(0, 0, 0, 0); self._col_lbls_layout.setSpacing(8)
        placeholder = QLabel("")
        placeholder.setStyleSheet("color:#9fb6d8;font-size:10px;")
        placeholder.setMinimumWidth(130)
        placeholder.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._col_lbls_layout.addWidget(placeholder)
        self._col_lbls_layout.addStretch()
        for br in ("awakening", "truth", "secret"):
            lbl = QLabel(self._branch_name(br, lang))
            lbl.setStyleSheet("color:#9fb6d8;font-size:10px;")
            lbl.setAlignment(Qt.AlignCenter)
            # V2035：列宽放大 1.5 倍（86~100 → 129~150），让「真谛：回复类能力强化」等长专精名能完整显示
            lbl.setMinimumWidth(129); lbl.setMaximumWidth(150)
            self._col_lbls_layout.addWidget(lbl, alignment=Qt.AlignVCenter)
        bl.addLayout(self._col_lbls_layout)
        # 列表
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setDragEnabled(True)
        self.list.setAcceptDrops(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        # 列表高度 = 有效 buff 条数 × 单行高 × 1.2（去掉固定 +2 余白，按内容自适应）
        buffs_for_h = self.profile.get("buffs", [])
        row_h = 44
        h = int(max(1, len(buffs_for_h)) * row_h * 1.2)
        self.list.setMinimumHeight(h)
        self.list.setMaximumHeight(h)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.model().rowsMoved.connect(lambda *a: self._on_order_changed())
        bl.addWidget(self.list)
        outer.addWidget(self._body)
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        self._apply_collapse()
        self._build(buff_order, buff_mastery)

    # ---------- 折叠 ----------
    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._apply_collapse()

    def _apply_collapse(self):
        self._body.setVisible(not self._collapsed)
        self._collapse_btn.setText("▾" if not self._collapsed else "▸")

    # ---------- 文案 ----------
    def _title_text(self, lang):
        # 合并组显示所有角色名，如 古兰/姬塔（PL0000/PL0100）
        names = []
        for pl_id in self.pl_ids:
            nm = CHAR_NAMES_TRI.get(pl_id, {})
            if isinstance(nm, dict):
                names.append(nm.get(lang, nm.get("zh", pl_id)))
            else:
                names.append(nm or pl_id)
        # 去重保持顺序
        seen = set(); uniq = []
        for n in names:
            if n not in seen:
                seen.add(n); uniq.append(n)
        name = "/".join(uniq) if len(uniq) > 1 else (uniq[0] if uniq else self.canon)
        pl_label = "/".join(self.pl_ids)
        return f"{name}  ({pl_label})"

    def _branch_name(self, br, lang):
        m = MASTERY_BRANCHES.get(self.canon, {})
        v = m.get(br, {}) if isinstance(m, dict) else {}
        if isinstance(v, dict):
            return v.get(lang, v.get("zh", br))
        return br

    def refresh_title(self, lang):
        self.lang = lang
        self._title_lbl.setText(self._title_text(lang))
        # 刷新列标题（使用保存的 layout，按 QLabel 顺序匹配三专精）
        col_lbls = getattr(self, "_col_lbls_layout", None)
        if col_lbls is None:
            return
        labels = []
        for idx in range(col_lbls.count()):
            w = col_lbls.itemAt(idx).widget()
            if isinstance(w, QLabel) and w.text():
                labels.append(w)
        for i, br in enumerate(("awakening", "truth", "secret")):
            if i < len(labels):
                labels[i].setText(self._branch_name(br, lang))

    def refresh_items(self, lang):
        """刷新每行 buff 名称为当前语言。"""
        self.lang = lang
        buffs = self.profile.get("buffs", [])
        for r in range(self.list.count()):
            item = self.list.item(r)
            idx = item.data(Qt.UserRole)
            if idx is None or idx < 0 or idx >= len(buffs):
                continue
            bc = buffs[idx]
            nm = bc.get(lang, bc.get("zh", ""))
            w = self.list.itemWidget(item)
            if w is None:
                continue
            for child in w.findChildren(QLabel):
                if child.text():
                    child.setText(nm)
                    break

    # ---------- 键 ----------
    def _bkey(self, idx):
        return f"{self.canon}_{idx}"

    # ---------- 构建 ----------
    def _build(self, buff_order, buff_mastery):
        self._loading = True
        buffs = self.profile.get("buffs", [])
        order = sorted(range(len(buffs)), key=lambda i: buff_order.get(self._bkey(i), i + 1))
        self.list.clear()
        for i in order:
            self.list.addItem(self._make_item(i, buffs[i], buff_mastery))
        self._loading = False

    def _make_item(self, idx, bc, buff_mastery):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, idx)
        self.list.addItem(item)
        w = QWidget()
        lay = QHBoxLayout(w); lay.setContentsMargins(4, 0, 4, 0); lay.setSpacing(8)
        lay.setAlignment(Qt.AlignVCenter)
        nm = bc.get(self.lang, bc.get("zh", ""))
        lbl = QLabel(nm); lbl.setStyleSheet("color:#dce8f8;font-size:12px;")
        lbl.setMinimumWidth(130)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lay.addWidget(lbl, alignment=Qt.AlignVCenter); lay.addStretch()
        chk = buff_mastery.get(self._bkey(idx))
        if chk is None:
            chk = {"awakening": bc.get("awakening", False), "truth": bc.get("truth", False), "secret": bc.get("secret", False)}
        for br in ("awakening", "truth", "secret"):
            cb = QCheckBox()
            cb.setChecked(bool(chk.get(br, False)))
            # V2035：列宽放大 1.5 倍（86~100 → 129~150），与列标题宽度对齐
            cb.setMinimumWidth(129); cb.setMaximumWidth(150)
            cb.setStyleSheet(
                "QCheckBox{color:#cfe0ff;font-size:11px;}"
                "QCheckBox::indicator{width:14px;height:14px;border-radius:4px;border:2px solid #60708c;background:#1a2030;subcontrol-position:center center;}"
                "QCheckBox::indicator:checked{background:#8c00ff;border:2px solid #c8a6ff;}"
            )
            cb.stateChanged.connect(lambda st, i=idx, b=br: self._on_check(i, b, st))
            lay.addWidget(cb, alignment=Qt.AlignCenter)
        w.setLayout(lay)
        # 行高 2x（约 44px），让 3-4 字 buff 名 + 3 勾选框不拥挤
        item.setSizeHint(QSize(-1, 44))
        self.list.setItemWidget(item, w)
        return item

    # ---------- 事件 ----------
    def _on_check(self, idx, br, state):
        if self._loading:
            return
        self.orderChanged.emit()

    def _on_order_changed(self):
        if self._loading:
            return
        self.orderChanged.emit()

    # ---------- 输出 ----------
    def get_order(self):
        """返回 {bkey: pos}（1-based，按当前列表顺序）。对多 pl_id 各写一份。"""
        result = {}
        for r in range(self.list.count()):
            item = self.list.item(r)
            idx = item.data(Qt.UserRole)
            if idx is None:
                continue
            for pid in self.pl_ids:
                result[f"{pid}_{idx}"] = r + 1
        return result

    def get_mastery(self):
        """返回 {bkey: {awakening,truth,secret}}。对多 pl_id 各写一份。"""
        result = {}
        for r in range(self.list.count()):
            item = self.list.item(r)
            idx = item.data(Qt.UserRole)
            if idx is None:
                continue
            w = self.list.itemWidget(item)
            cbs = w.findChildren(QCheckBox) if w else []
            vals = {}
            for br, cb in zip(("awakening", "truth", "secret"), cbs):
                vals[br] = cb.isChecked()
            for pid in self.pl_ids:
                result[f"{pid}_{idx}"] = dict(vals)
        return result

    def set_all(self, on):
        self._loading = True
        for r in range(self.list.count()):
            item = self.list.item(r)
            w = self.list.itemWidget(item)
            if w:
                for cb in w.findChildren(QCheckBox):
                    cb.setChecked(on)
        self._loading = False
        self.orderChanged.emit()

    def apply_mastery_map(self, mastery_map):
        """V2259：按 {bkey: {awakening, truth, secret}} 映射**逐项**设置每个 buff 的专精勾选框。

        背景（用户报的 bug）：「恢复默认」后 Buff 启用/禁用页里所有勾选框全被勾上。
        根因在 reset_defaults 里原本调用的是 `group.set_all(True)`——它把**每一行**的
        觉醒/真谛/秘义三个勾选框无条件全部设成 True，完全绕过 DEFAULT_SETTINGS。
        V2257 把玩家配置烘焙进默认值后（buff_mastery 里本来就有 false），这行就把
        那些 false 全冲成 true 了，还会经 orderChanged → get_settings 回写污染 settings。

        本方法改为严格按传入的映射逐项还原：映射里没有的键一律按 False 处理
        （不会像 set_all 那样默认全勾）。键格式与 _bkey() 一致：`{canon}_{idx}`。
        """
        self._loading = True
        try:
            for r in range(self.list.count()):
                item = self.list.item(r)
                idx = item.data(Qt.UserRole)
                if idx is None:
                    continue
                w = self.list.itemWidget(item)
                if not w:
                    continue
                vals = (mastery_map or {}).get(self._bkey(idx)) or {}
                for br, cb in zip(("awakening", "truth", "secret"), w.findChildren(QCheckBox)):
                    cb.setChecked(bool(vals.get(br, False)))
        finally:
            self._loading = False
        self.orderChanged.emit()

class HotkeyCaptureDialog(QDialog):
    """弹窗捕获全局快捷键组合（最多 3 个键：可选修饰键 Ctrl/Alt/Shift/Win + 1 个主键）。

    不再强制 Ctrl；Ctrl+K 只是默认。支持任意键（字母 / F1-F12 / 方向键 / 空格 等）。
    捕获结果以 VK 列表写入 captured_combo（如 [17, 75]），并以「Ctrl + K」样式写入 captured_name。
    """

    _MOD_VKS = frozenset({0x11, 0x12, 0x10, 0x5B, 0x5C})  # Ctrl / Alt / Shift / LWin / RWin
    _MAX_KEYS = 3

    def __init__(self, parent=None, current_label=""):
        super().__init__(parent)
        self.setWindowTitle(_tr("捕获快捷键"))
        self.setModal(True)
        self.setFixedSize(360, 172)
        self.captured_combo = None   # 捕获到的 VK 列表，如 [17, 75]
        self.captured_name = None
        self._keys = []              # [(vk, name, is_mod), ...]
        self._done = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        hint = QLabel(_tr("依次按下要绑定的组合键（最多 3 个）\n支持 Ctrl / Alt / Shift / Win + 字母 / F1-F12 / 方向键 等\nCtrl 不再强制，仅作为默认选项"))
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color:#aabbcc;font-size:11px;")
        self.label = QLabel(current_label or _tr("等待按键…"))
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size:20px;font-weight:bold;color:#9fd0ff;")
        self.cancel_btn = QPushButton(_tr("取消"))
        # 防止 Space/Enter 被取消按钮抢走焦点而误触：按钮不自动默认、不接收键盘焦点
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.setDefault(False)
        self.cancel_btn.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(hint)
        lay.addWidget(self.label)
        lay.addStretch()
        lay.addWidget(self.cancel_btn)
        self.cancel_btn.clicked.connect(self.reject)
        # 让本窗口先拿到键盘焦点，确保 keyPressEvent 落到这里
        QTimer.singleShot(1, self.setFocus)

    def keyPressEvent(self, ev):
        if ev.isAutoRepeat() or self._done:
            return
        ev.accept()
        vk = int(ev.nativeVirtualKey())
        # 同 VK 不重复计入
        if any(k[0] == vk for k in self._keys):
            return
        if len(self._keys) >= self._MAX_KEYS:
            return
        is_mod = vk in self._MOD_VKS
        self._keys.append((vk, self._key_name(ev), is_mod))
        self._refresh_label()
        # 有效组合 = 含主键（非修饰键）；或已达 3 键上限也收尾（避免空等）
        has_main = any((not k[2]) for k in self._keys)
        if has_main or len(self._keys) >= self._MAX_KEYS:
            self._done = True
            self.captured_combo = [k[0] for k in self._keys]
            self.captured_name = " + ".join(k[1] for k in self._keys)
            # 捕获后短暂延时自动确认，避免连续按键误触
            QTimer.singleShot(450, self.accept)

    def _refresh_label(self):
        parts = [k[1] for k in self._keys]
        self.label.setText(" + ".join(parts) if parts else _tr("等待按键…"))

    @staticmethod
    def _key_name(ev):
        """把 QKeyEvent 解析成人类可读按键名。优先用 ev.key() 避免 Ctrl 下 ev.text() 返回控制字符。"""
        k = ev.key()
        # 字母 A-Z：Ctrl+字母时 ev.text() 常返回控制字符，必须用 ev.key() 才稳定
        if Qt.Key_A <= k <= Qt.Key_Z:
            return chr(k - Qt.Key_A + ord("A"))
        # 数字主键盘 0-9
        if Qt.Key_0 <= k <= Qt.Key_9:
            return chr(k - Qt.Key_0 + ord("0"))
        specials = {
            Qt.Key_F1: "F1", Qt.Key_F2: "F2", Qt.Key_F3: "F3", Qt.Key_F4: "F4",
            Qt.Key_F5: "F5", Qt.Key_F6: "F6", Qt.Key_F7: "F7", Qt.Key_F8: "F8",
            Qt.Key_F9: "F9", Qt.Key_F10: "F10", Qt.Key_F11: "F11", Qt.Key_F12: "F12",
            Qt.Key_Space: "Space", Qt.Key_Left: "←", Qt.Key_Right: "→",
            Qt.Key_Up: "↑", Qt.Key_Down: "↓", Qt.Key_Return: "Enter",
            Qt.Key_Backspace: "Backspace", Qt.Key_Delete: "Delete", Qt.Key_Tab: "Tab",
            Qt.Key_Control: "Ctrl", Qt.Key_Alt: "Alt", Qt.Key_Shift: "Shift",
            Qt.Key_Meta: "Win",
        }
        if k in specials:
            return specials[k]
        # 兜底：小键盘数字等直接打印字符；控制字符不显示
        txt = ev.text()
        if txt and txt.isprintable():
            return txt.upper()
        # Ctrl/Alt/Shift+标点时 ev.text() 为空，用 native VK 兜底映射
        vk = ev.nativeVirtualKey()
        vk_punct = {
            0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
            0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
        }
        if vk in vk_punct:
            return vk_punct[vk]
        return "VK%d" % int(vk)

class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    def __init__(self, parent, settings, ctrl=None):
        super().__init__(parent)
        # ── V2304 BUGFIX（修 V2301 遗留）：构造期全程屏蔽实时通知 ────────────────
        # 症状：每次打开设置窗口，内部都会白发 2 次失败的实时通知。
        # 根因：3D 页两个复选框（spike_3d_shadow_enabled_chk / spike_3d_outline_enabled_chk）
        #   是「先 .connect(self._emit_changed) 再 .setChecked(...)」的顺序，setChecked 立刻
        #   触发通知 → _emit_changed → get_settings() 去读 self.spike_hide_chk，而那个复选框
        #   在更后面的「尖刺与圆环」页才创建 → AttributeError。
        # 为什么以前没人发现：windowed 打包后没有 stderr，Qt 把槽函数里的异常打到虚空里吞掉了。
        # 修法选型：构造期本来就不需要对外发通知（控制器拿到的就是同一份 settings），
        #   因此整段屏蔽，比逐个去调 connect / setValue 的先后顺序更稳，
        #   且未来任何新增的内联接线控件都不会再踩这个坑。__init__ 末尾恢复。
        self._suppress_emit = True
        # 先同步全局语言：构造过程中任何异常弹窗都必须用用户当前语言
        global _CURRENT_LANG
        _CURRENT_LANG = settings.get("language", "zh")
        # V611：setWindowTitle 中读取 self.ctrl，必须先完成 self.ctrl = ctrl 与信号连接，
        # 否则首次刷新时 self.ctrl 还未绑定 → AttributeError（"SettingsDialog object has no attribute 'ctrl'"）。
        self.setMinimumWidth(1120)
        self.setMaximumHeight(760)
        self.resize(1120, 760)
        self.settings = dict(settings)
        self.ctrl = ctrl
        # 标题栏实时更新状态：连接控制器广播信号（对话框关闭时 Qt 自动断开，无泄漏）
        if self.ctrl is not None:
            try:
                self.ctrl.update_status_changed.connect(self._on_update_status_changed)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        # 现在 self.ctrl 已绑定，再刷新标题栏（带实时更新状态简报）
        self._refresh_settings_title()
        self.color_buttons = {}
        self.opacity_spins = {}
        self._top_tabs_zh = []
        self._sub_tabs = []
        self.setStyleSheet(
            "QDialog{background:#1a2030;color:#dbe7ff;}"
            "QLabel{color:#aab6d0;}"
            "QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QPlainTextEdit{background:#242c40;color:#dce8f8;border:1px solid #3a4860;padding:3px;border-radius:4px;}"
            "QPlainTextEdit{color:#dce8f8;}"
            "QComboBox QAbstractItemView{background:#242c40;color:#ffffff;selection-background-color:#3a4860;selection-color:#ffffff;border:1px solid #3a4860;outline:0;}"
            # V2077~V2079 尝试 QSS sub-control 画下拉箭头（utf8 SVG/base64 SVG/CSS border）均失败。
            # V2080 改用独立 QLabel（cf.addRow 处）显示 ▼ 字符——QLabel 是普通 widget，100% 可靠。
            # QSS 这里不再干预 QComboBox::drop-down，让原生外观走（排序方式那个 combo 由 V2080 单独接管右侧视觉）。
            "QPushButton{background:#2a3450;color:#fff;border:1px solid #3a4860;padding:5px 15px;border-radius:4px;}"
            "QPushButton:hover{background:#3a4860;}"
            "QCheckBox{color:#ffffff; spacing:8px;}"
            "QCheckBox::indicator{width:18px;height:18px;border-radius:5px;border:2px solid #60708c;background:#1a2030;}"
            "QCheckBox::indicator:hover{border-color:#9a7bff;}"
            "QCheckBox::indicator:checked{background:#8c00ff;border:2px solid #c8a6ff;}"
            "QCheckBox::indicator:unchecked{background:#1a2030;border:2px solid #60708c;}"
            # V2107：彻底隐藏 QSpinBox 的原生上下按钮——之前 width:0px 仅对水平维度生效，
            # 竖排的 ▲▼ 在 Windows 上仍可见、且点击无任何作用（spinbox 已绑定 valueChanged 数字逻辑）。
            # 改 height:0px 让两块 sub-control 真正归零，配合 image:none 与 border:none。
            "QSpinBox::up-button,QSpinBox::down-button,QSpinBox::up-arrow,QSpinBox::down-arrow{height:0px;width:0px;border:none;image:none;}"
            "QSpinBox::up-button:hover,QSpinBox::down-button:hover,QSpinBox::up-button:pressed,QSpinBox::down-button:pressed{height:0px;width:0px;border:none;background:transparent;}"
            # QDoubleSpinBox 同步隐藏（同一原生控件）
            "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button,QDoubleSpinBox::up-arrow,QDoubleSpinBox::down-arrow{height:0px;width:0px;border:none;image:none;}"
            # V2107：隐藏 QComboBox 的原生下拉箭头（之前 V2080 把字符 ▼ 单独做 Label 接管了排序方式的视觉，
            # 这里把所有 QComboBox 的原生 drop-down 都归零，不再显示孤立的三角形）。
            "QComboBox::drop-down{width:0px;height:0px;border:none;}"
            "QComboBox::down-arrow{width:0px;height:0px;image:none;}"
            # V2091：用户要求滚动条加宽到默认的 2.4 倍（系统默认 16px → 38px）。
            # QSS 写在主对话框 → 子 widget 的 QScrollBar 也会继承（Qt 样式继承机制），
            # 因此设置对话框里所有滚动条（含子页/列表等）统一变宽。
            "QScrollBar:vertical{width:38px;background:#1a2030;border:none;margin:0;}"
            "QScrollBar:horizontal{height:38px;background:#1a2030;border:none;margin:0;}"
            "QScrollBar::handle:vertical{background:#3a4860;border-radius:6px;min-height:40px;margin:2px 4px;border:none;}"
            "QScrollBar::handle:horizontal{background:#3a4860;border-radius:6px;min-width:40px;margin:4px 2px;border:none;}"
            "QScrollBar::handle:vertical:hover{background:#5a6a90;}"
            "QScrollBar::handle:horizontal:hover{background:#5a6a90;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;background:none;border:none;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0px;background:none;border:none;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
        )

        layout = QVBoxLayout(self)
        self.settings_tabs = QTabWidget()
        TAB_STYLE = (
            "QTabWidget::pane{border:1px solid #2a3548;border-radius:6px;}"
            "QTabBar::tab{background:#20283a;color:#aab6d0;padding:7px 14px;border:1px solid #2a3548;border-bottom:none;}"
            "QTabBar::tab:selected{background:#2a3450;color:#ffffff;}"
            "QTabBar::tab:hover{background:#303b55;}"
        )
        self.settings_tabs.setStyleSheet(TAB_STYLE)

        def make_top_tab(title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea>QWidget>QWidget{background:transparent;}")
            inner = QWidget()
            inner.setStyleSheet("background:transparent;")
            vlay = QVBoxLayout(inner)
            vlay.setContentsMargins(8, 8, 8, 8)
            sub_tabs = QTabWidget()
            sub_tabs.setStyleSheet(TAB_STYLE)
            vlay.addWidget(sub_tabs)
            scroll.setWidget(inner)
            self.settings_tabs.addTab(scroll, title)
            self._top_tabs_zh.append(title)
            self._sub_tabs.append((sub_tabs, []))
            return sub_tabs

        def make_sub_tab(sub_tabs, title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea>QWidget>QWidget{background:transparent;}")
            inner = QWidget()
            inner.setStyleSheet("background:transparent;")
            form = QFormLayout(inner)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(8)
            scroll.setWidget(inner)
            sub_tabs.addTab(scroll, title)
            self._sub_tabs[-1][1].append(title)
            return form

        def make_card(parent_form, title=None):
            if title:
                sep = QLabel(title)
                sep.setStyleSheet("font-weight:bold; color:#7a8aa8; padding-top:8px;")
                parent_form.addRow(sep)
            card = QFrame()
            card.setStyleSheet(
                "QFrame{background:rgba(35,45,70,0.5);border-radius:8px;border:1px solid #2a3548;}"
                "QLabel{background:transparent;border:none;}"
            )
            cf = QFormLayout(card)
            cf.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            cf.setHorizontalSpacing(10)
            cf.setVerticalSpacing(8)
            cf.setContentsMargins(12, 8, 12, 8)
            return card, cf

        def _mk_opacity_row(cf_local, key, label):
            from PySide6.QtWidgets import QSlider, QLabel, QWidget, QHBoxLayout
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(int(self.settings.get(key, 50)))
            lab = QLabel(f"{sl.value()}%")
            lab.setFixedWidth(40)
            sl.valueChanged.connect(lambda v: lab.setText(f"{v}%"))
            hl.addWidget(sl)
            hl.addWidget(lab)
            cf_local.addRow(label, w)
            return sl

        def _mk_pos_row(cf_local, x_key, y_key):
            from PySide6.QtWidgets import QWidget, QHBoxLayout
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            rs = getattr(self.ctrl, "res_scale", 1.0) or 1.0
            xs = QSpinBox(); xs.setRange(-99999, 99999); xs.setPrefix("X "); xs.setValue(int(round(self.settings.get(x_key, 0) * rs)))
            ys = QSpinBox(); ys.setRange(-99999, 99999); ys.setPrefix("Y "); ys.setValue(int(round(self.settings.get(y_key, 0) * rs)))
            xs.valueChanged.connect(self._emit_changed)
            ys.valueChanged.connect(self._emit_changed)
            row.addWidget(xs); row.addWidget(ys)
            c = QWidget(); c.setLayout(row)
            cf_local.addRow(_tr("模块位置:"), c)
            return xs, ys

        def _mk_scale_row(cf_local, key, label):
            from PySide6.QtWidgets import QWidget, QHBoxLayout
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            sl = QSlider(Qt.Horizontal); sl.setRange(20, 400)
            sp = QSpinBox(); sp.setRange(20, 400); sp.setSuffix("%"); sp.setFixedWidth(86)
            val = int(self.settings.get(f"{key}_scale_percent", 100))
            sl.setValue(val); sp.setValue(val)
            sl.valueChanged.connect(sp.setValue)
            sp.valueChanged.connect(sl.setValue)
            row.addWidget(sl); row.addWidget(sp)
            c = QWidget(); c.setLayout(row)
            cf_local.addRow(label, c)
            setattr(self, f"{key}_scale_slider", sl)
            setattr(self, f"{key}_scale_spin", sp)
            return sl, sp

        layout.addWidget(self.settings_tabs)

        # ============ 顶级标签: 全局 ============
        g_sub = make_top_tab(_tr("全局"))
        # 常规
        f = make_sub_tab(g_sub, _tr("常规"))
        card, cf = make_card(f, _tr("── 常规 ──"))
        # 语言下拉菜单：硬编码三项 + userData 存语言代码（zh/zh_tw/en）。
        # 任何语言下三项文字保持不变，运行时直接读 currentData() 取语言代码。
        self.lang = QComboBox()
        self.lang.addItem("简体中文", "zh")
        self.lang.addItem("繁體中文", "zh_tw")
        self.lang.addItem("English", "en")
        self.lang.addItem("日本語", "ja")   # V2203
        _lang_cur = self.settings.get("language", "zh")
        _lang_idx = self.lang.findData(_lang_cur)
        if _lang_idx < 0:
            _lang_idx = 0  # 兜底：未知语言代码时落到简体中文
        self.lang.setCurrentIndex(_lang_idx)
        cf.addRow(_tr("语言 / Language:"), self.lang)
        self.auto_focus_minimize = QCheckBox(_tr("游戏在前台时显示，切到后台时自动最小化"))
        self.auto_focus_minimize.setChecked(bool(self.settings.get("auto_focus_minimize", DEFAULT_SETTINGS["auto_focus_minimize"])))
        cf.addRow(_tr("随游戏前后台:"), self.auto_focus_minimize)
        self.resolution_auto_scale = QCheckBox(_tr("按当前屏幕宽度自动放大"))
        self.resolution_auto_scale.setChecked(bool(self.settings.get("resolution_auto_scale", DEFAULT_SETTINGS["resolution_auto_scale"])))
        cf.addRow(_tr("随分辨率放大:"), self.resolution_auto_scale)
        self.startup_locked_chk = QCheckBox(_tr("启动软件默认锁定"))
        self.startup_locked_chk.setChecked(bool(self.settings.get("startup_locked", DEFAULT_SETTINGS["startup_locked"])))
        cf.addRow(_tr("启动锁定:"), self.startup_locked_chk)
        # V2084：文本修缮，列入"全 Buff 模块"（之前漏了），与 about 页文档保持一致
        self.ooc_hide_chk = QCheckBox(_tr("非战斗时隐藏全部 UI（尖刺圆/全 Buff/核心/翻滚/技能 UI）"))
        self.ooc_hide_chk.setChecked(bool(self.settings.get("out_of_combat_hide", DEFAULT_SETTINGS["out_of_combat_hide"])))
        cf.addRow(_tr("非战斗隐藏:"), self.ooc_hide_chk)
        self.ooc_op_spn = QSpinBox()
        self.ooc_op_spn.setRange(0, 100)
        self.ooc_op_spn.setSuffix("%")
        self.ooc_op_spn.setValue(int(self.settings.get("out_of_combat_opacity", DEFAULT_SETTINGS["out_of_combat_opacity"])))
        cf.addRow(_tr("隐藏时透明度:"), self.ooc_op_spn)
        f.addRow(card)
        # 扫描 / 内存
        card, cf = make_card(f, _tr("── 扫描 / 内存 ──"))
        self.scan = QSpinBox(); self.scan.setRange(10, 500); self.scan.setValue(int(self.settings.get("scan_ms", DEFAULT_SETTINGS["scan_ms"])))
        cf.addRow(_tr("扫描周期 (ms):"), self.scan)
        f.addRow(card)
        # 模块显示（三模块勾选；未勾选时该模块内容不透明度归 0，核心模块标题栏始终显示）
        card, cf = make_card(f, _tr("── 模块显示 ──"))
        self.show_core_module_chk = QCheckBox(_tr("核心检测模块（标题栏始终显示，仅内容隐藏）"))
        self.show_core_module_chk.setChecked(bool(self.settings.get("show_core_module", True)))
        cf.addRow(self.show_core_module_chk)
        self.show_roll_module_chk = QCheckBox(_tr("翻滚模块"))
        self.show_roll_module_chk.setChecked(bool(self.settings.get("show_roll_module", True)))
        cf.addRow(self.show_roll_module_chk)
        self.show_skill_module_chk = QCheckBox(_tr("能力冷却模块"))
        self.show_skill_module_chk.setChecked(bool(self.settings.get("show_skill_cd_module", True)))
        cf.addRow(self.show_skill_module_chk)
        self.show_allbuff_module_chk = QCheckBox(_tr("全Buff显示模块"))
        self.show_allbuff_module_chk.setChecked(bool(self.settings.get("show_allbuff_module", True)))
        cf.addRow(self.show_allbuff_module_chk)
        # V2200：Boss Buff 模块（第五模块）独立显隐开关
        self.show_boss_module_chk = QCheckBox(_tr("Boss Buff模块"))
        self.show_boss_module_chk.setChecked(bool(self.settings.get("show_boss_module", True)))
        cf.addRow(self.show_boss_module_chk)
        f.addRow(card)
        # 全局快捷键（移回全局-常规标签）
        card, cf = make_card(f, _tr("── 全局快捷键 ──"))
        # 三个热键：呼出/隐藏、锁定解锁、打开设置，每项独立勾选框
        self._build_hotkey_row(cf, "hk_show", _tr("呼出/隐藏所有窗口"), "global_hotkey_show", "17,75",
                               "global_hotkey_show_enabled", True)
        self._build_hotkey_row(cf, "hk_lock", _tr("锁定 / 解锁窗口"), "global_hotkey_lock", "",
                               "global_hotkey_lock_enabled", False)
        self._build_hotkey_row(cf, "hk_settings", _tr("打开设置"), "global_hotkey_settings", "",
                               "global_hotkey_settings_enabled", False)
        f.addRow(card)
        # EXE 同步（全局：启动时才生效，按绝对路径检测/启停）
        card, cf = make_card(f, _tr("── EXE 同步 ──"))
        # V2035 新增：整行启用勾选框，玩家可一键关掉 EXE 同步（不勾 = 永不启动列表中的任何 EXE）
        self.enable_sync_exe_chk = QCheckBox(_tr("启用 EXE 同步列表"))
        self.enable_sync_exe_chk.setChecked(bool(self.settings.get("enable_sync_exe_list", DEFAULT_SETTINGS["enable_sync_exe_list"])))
        cf.addRow(self.enable_sync_exe_chk)
        self.sync_exe_le = QPlainTextEdit()
        self.sync_exe_le.setPlainText(self.settings.get("sync_exe_list", DEFAULT_SETTINGS["sync_exe_list"]))
        self.sync_exe_le.setPlaceholderText(_tr("多个 exe 绝对路径，可用分号或换行分隔；可附加 ||工作目录"))
        self.sync_exe_le.setToolTip(_tr("多个 exe 的绝对路径，用分号或换行分隔。每条可附加「||工作目录」指定起始位置（等同 .lnk 的起始位置，可省略）。程序启动时检测：未运行则共同启动（以指定工作目录为起始位置），已运行则跳过（不监视、不杀进程）。"))
        # 5 倍行高：按字体行高固定约 5 行，方便查看 / 粘贴多个 exe 路径
        _fm = self.sync_exe_le.fontMetrics()
        self.sync_exe_le.setFixedHeight(_fm.height() * 5 + 12)
        cf.addRow(_tr("EXE 同步列表 (分号/换行分隔):"), self.sync_exe_le)
        f.addRow(card)

        # ── V2304：调试数据（不开游戏也能测 UI）─────────────────────────────
        # 开启主开关后，scan() 顶部直接注入假数据并 return，完全不读游戏内存。
        # 五个模块各有一组典型参数，全部实时生效（接 _emit_changed），拖动即可见。
        f = make_sub_tab(g_sub, _tr("调试数据"))
        card, cf = make_card(f, _tr("── 调试总开关 ──"))
        self.debug_data_enabled_chk = QCheckBox(_tr("启用调试假数据（不开游戏也能测 UI）"))
        self.debug_data_enabled_chk.setChecked(bool(self.settings.get("debug_data_enabled", False)))
        self.debug_data_enabled_chk.setToolTip(_tr("开启后不再读取游戏内存，五个模块全部用下面的假数据填充；关闭后立即恢复正常读取。"))
        cf.addRow(self.debug_data_enabled_chk)
        self.debug_text_le = QLineEdit(str(self.settings.get("debug_text", "测试带编码")))
        self.debug_text_le.setToolTip(_tr("核心 Buff 名、全 Buff 名、Boss Buff 名、技能名统一显示这个文本。"))
        cf.addRow(_tr("统一显示文本:"), self.debug_text_le)
        self.debug_countdown_spn = QDoubleSpinBox()
        self.debug_countdown_spn.setRange(0.0, 9999.0)
        self.debug_countdown_spn.setDecimals(2)
        self.debug_countdown_spn.setSingleStep(0.5)
        self.debug_countdown_spn.setValue(float(self.settings.get("debug_countdown", 8.88)))
        cf.addRow(_tr("固定倒计时(秒):"), self.debug_countdown_spn)
        self.debug_status_cmb = QComboBox()
        self.debug_status_cmb.addItem(_tr("正常（已识别角色）"), "ok")
        self.debug_status_cmb.addItem(_tr("未识别到角色"), "no_char")
        self.debug_status_cmb.addItem(_tr("未检测到游戏"), "no_game")
        self.debug_status_cmb.addItem(_tr("初始化中"), "init")
        _dsi = self.debug_status_cmb.findData(str(self.settings.get("debug_status", "ok")))
        self.debug_status_cmb.setCurrentIndex(_dsi if _dsi >= 0 else 0)
        cf.addRow(_tr("模拟状态:"), self.debug_status_cmb)
        self.debug_in_combat_chk = QCheckBox(_tr("模拟战斗中（取消勾选可验证「非战斗隐藏」）"))
        self.debug_in_combat_chk.setChecked(bool(self.settings.get("debug_in_combat", True)))
        cf.addRow(_tr("战斗状态:"), self.debug_in_combat_chk)
        self.debug_mastery_cmb = QComboBox()
        self.debug_mastery_cmb.addItem(_tr("不指定"), "")
        self.debug_mastery_cmb.addItem(_tr("觉醒"), "awakening")
        self.debug_mastery_cmb.addItem(_tr("真谛"), "truth")
        self.debug_mastery_cmb.addItem(_tr("秘义"), "secret")
        _dmi = self.debug_mastery_cmb.findData(str(self.settings.get("debug_mastery", "")))
        self.debug_mastery_cmb.setCurrentIndex(_dmi if _dmi >= 0 else 0)
        cf.addRow(_tr("模拟专精:"), self.debug_mastery_cmb)
        f.addRow(card)

        card, cf = make_card(f, _tr("── 核心检测模块 ──"))
        self.debug_core_count_spn = QSpinBox()
        self.debug_core_count_spn.setRange(0, 24)
        self.debug_core_count_spn.setValue(int(self.settings.get("debug_core_buff_count", 3)))
        cf.addRow(_tr("Buff 数量:"), self.debug_core_count_spn)
        self.debug_core_single_chk = QCheckBox(_tr("按单层 Buff 渲染（只有倒计时、无层数）"))
        self.debug_core_single_chk.setChecked(bool(self.settings.get("debug_core_single_layer", False)))
        cf.addRow(_tr("是否单层:"), self.debug_core_single_chk)
        self.debug_core_full_chk = QCheckBox(_tr("按满层渲染（层数 = 最大层数）"))
        self.debug_core_full_chk.setChecked(bool(self.settings.get("debug_core_full_stacks", True)))
        cf.addRow(_tr("是否满层:"), self.debug_core_full_chk)
        self.debug_core_stacks_spn = QSpinBox()
        self.debug_core_stacks_spn.setRange(0, 99)
        self.debug_core_stacks_spn.setValue(int(self.settings.get("debug_core_stacks", 1)))
        self.debug_core_stacks_spn.setToolTip(_tr("仅在未勾选「是否满层」时生效。"))
        cf.addRow(_tr("非满层时层数:"), self.debug_core_stacks_spn)
        self.debug_core_max_spn = QSpinBox()
        self.debug_core_max_spn.setRange(1, 99)
        self.debug_core_max_spn.setValue(int(self.settings.get("debug_core_max_stacks", 8)))
        cf.addRow(_tr("最大层数:"), self.debug_core_max_spn)
        self.debug_core_awk_chk = QCheckBox(_tr("觉醒"))
        self.debug_core_awk_chk.setChecked(bool(self.settings.get("debug_core_awakening", False)))
        self.debug_core_truth_chk = QCheckBox(_tr("真谛"))
        self.debug_core_truth_chk.setChecked(bool(self.settings.get("debug_core_truth", False)))
        self.debug_core_secret_chk = QCheckBox(_tr("秘义"))
        self.debug_core_secret_chk.setChecked(bool(self.settings.get("debug_core_secret", False)))
        _mrow = QHBoxLayout(); _mrow.setContentsMargins(0, 0, 0, 0); _mrow.setSpacing(10)
        _mrow.addWidget(self.debug_core_awk_chk)
        _mrow.addWidget(self.debug_core_truth_chk)
        _mrow.addWidget(self.debug_core_secret_chk)
        _mrow.addStretch(1)
        _mw = QWidget(); _mw.setLayout(_mrow)
        cf.addRow(_tr("专精标记:"), _mw)
        f.addRow(card)

        card, cf = make_card(f, _tr("── 全 Buff 模块 ──"))
        # V2309：调试注入各类别数量（替代原「卡片数量」+「是否永续」）
        self.debug_allbuff_normal_spn = QSpinBox()
        self.debug_allbuff_normal_spn.setRange(0, 60)
        self.debug_allbuff_normal_spn.setValue(int(self.settings.get("debug_allbuff_normal", 8)))
        self.debug_allbuff_normal_spn.setToolTip(_tr("调试时注入多少个「普通 Buff」假条目（非 debuff、非永续、剩余时间充足）。"))
        cf.addRow(_tr("普通Buff 数量:"), self.debug_allbuff_normal_spn)
        self.debug_allbuff_debuff_spn = QSpinBox()
        self.debug_allbuff_debuff_spn.setRange(0, 60)
        self.debug_allbuff_debuff_spn.setValue(int(self.settings.get("debug_allbuff_debuff", 2)))
        self.debug_allbuff_debuff_spn.setToolTip(_tr("调试时注入多少个「Debuff」假条目（红色、按 debuff 样式渲染）。"))
        cf.addRow(_tr("Debuff 数量:"), self.debug_allbuff_debuff_spn)
        self.debug_allbuff_perma_spn = QSpinBox()
        self.debug_allbuff_perma_spn.setRange(0, 60)
        self.debug_allbuff_perma_spn.setValue(int(self.settings.get("debug_allbuff_perma", 1)))
        self.debug_allbuff_perma_spn.setToolTip(_tr("调试时注入多少个「永续（∞）」假条目（显示 ∞ 符号）。"))
        cf.addRow(_tr("永续 数量:"), self.debug_allbuff_perma_spn)
        self.debug_allbuff_coda_spn = QSpinBox()
        self.debug_allbuff_coda_spn.setRange(0, 60)
        self.debug_allbuff_coda_spn.setValue(int(self.settings.get("debug_allbuff_coda", 1)))
        self.debug_allbuff_coda_spn.setToolTip(_tr("调试时注入多少个「尾声」假条目（非永续、剩余时间已接近结束，触发尾声样式）。"))
        cf.addRow(_tr("尾声 数量:"), self.debug_allbuff_coda_spn)
        self.debug_allbuff_stacks_spn = QSpinBox()
        self.debug_allbuff_stacks_spn.setRange(1, 99)
        self.debug_allbuff_stacks_spn.setValue(int(self.settings.get("debug_allbuff_stacks", 8)))
        cf.addRow(_tr("层数:"), self.debug_allbuff_stacks_spn)
        self.debug_allbuff_max_spn = QSpinBox()
        self.debug_allbuff_max_spn.setRange(1, 99)
        self.debug_allbuff_max_spn.setValue(int(self.settings.get("debug_allbuff_max_stacks", 8)))
        cf.addRow(_tr("最大层数:"), self.debug_allbuff_max_spn)
        f.addRow(card)

        card, cf = make_card(f, _tr("── Boss Buff 模块 ──"))
        # V2309：调试注入各类别数量（替代原「卡片数量」+「是否永续」）
        self.debug_boss_normal_spn = QSpinBox()
        self.debug_boss_normal_spn.setRange(0, 60)
        self.debug_boss_normal_spn.setValue(int(self.settings.get("debug_boss_normal", 5)))
        self.debug_boss_normal_spn.setToolTip(_tr("调试时注入多少个「普通 Buff」假条目（非 debuff、非永续、剩余时间充足）。"))
        cf.addRow(_tr("普通Buff 数量:"), self.debug_boss_normal_spn)
        self.debug_boss_debuff_spn = QSpinBox()
        self.debug_boss_debuff_spn.setRange(0, 60)
        self.debug_boss_debuff_spn.setValue(int(self.settings.get("debug_boss_debuff", 1)))
        self.debug_boss_debuff_spn.setToolTip(_tr("调试时注入多少个「Debuff」假条目（红色、按 debuff 样式渲染）。"))
        cf.addRow(_tr("Debuff 数量:"), self.debug_boss_debuff_spn)
        self.debug_boss_perma_spn = QSpinBox()
        self.debug_boss_perma_spn.setRange(0, 60)
        self.debug_boss_perma_spn.setValue(int(self.settings.get("debug_boss_perma", 1)))
        self.debug_boss_perma_spn.setToolTip(_tr("调试时注入多少个「永续（∞）」假条目（显示 ∞ 符号）。"))
        cf.addRow(_tr("永续 数量:"), self.debug_boss_perma_spn)
        self.debug_boss_coda_spn = QSpinBox()
        self.debug_boss_coda_spn.setRange(0, 60)
        self.debug_boss_coda_spn.setValue(int(self.settings.get("debug_boss_coda", 1)))
        self.debug_boss_coda_spn.setToolTip(_tr("调试时注入多少个「尾声」假条目（非永续、剩余时间已接近结束，触发尾声样式）。"))
        cf.addRow(_tr("尾声 数量:"), self.debug_boss_coda_spn)
        self.debug_boss_stacks_spn = QSpinBox()
        self.debug_boss_stacks_spn.setRange(1, 99)
        self.debug_boss_stacks_spn.setValue(int(self.settings.get("debug_boss_stacks", 8)))
        cf.addRow(_tr("层数:"), self.debug_boss_stacks_spn)
        self.debug_boss_max_spn = QSpinBox()
        self.debug_boss_max_spn.setRange(1, 99)
        self.debug_boss_max_spn.setValue(int(self.settings.get("debug_boss_max_stacks", 8)))
        cf.addRow(_tr("最大层数:"), self.debug_boss_max_spn)
        f.addRow(card)

        card, cf = make_card(f, _tr("── 能力冷却 / 翻滚模块 ──"))
        self.debug_skill_count_spn = QSpinBox()
        self.debug_skill_count_spn.setRange(0, 4)
        self.debug_skill_count_spn.setValue(int(self.settings.get("debug_skill_count", 4)))
        cf.addRow(_tr("技能槽数量:"), self.debug_skill_count_spn)
        self.debug_skill_ready_spn = QSpinBox()
        self.debug_skill_ready_spn.setRange(0, 4)
        self.debug_skill_ready_spn.setValue(int(self.settings.get("debug_skill_ready_count", 1)))
        self.debug_skill_ready_spn.setToolTip(_tr("前 N 个槽位显示为「就绪」（触发就绪呼吸灯/闪光），其余处于倒计时。"))
        cf.addRow(_tr("就绪槽位数:"), self.debug_skill_ready_spn)
        self.debug_skill_cdmax_spn = QDoubleSpinBox()
        self.debug_skill_cdmax_spn.setRange(0.1, 999.0)
        self.debug_skill_cdmax_spn.setDecimals(1)
        self.debug_skill_cdmax_spn.setValue(float(self.settings.get("debug_skill_cd_max", 30.0)))
        self.debug_skill_cdmax_spn.setToolTip(_tr("冷却上限，决定菱形内扇形进度的比例。"))
        cf.addRow(_tr("冷却上限(秒):"), self.debug_skill_cdmax_spn)
        self.debug_dodge_spn = QSpinBox()
        self.debug_dodge_spn.setRange(0, 7)
        self.debug_dodge_spn.setValue(int(self.settings.get("debug_dodge_count", 7)))
        cf.addRow(_tr("翻滚次数:"), self.debug_dodge_spn)
        f.addRow(card)

        # 闪光（全局统一·跨模块）
        f = make_sub_tab(g_sub, _tr("闪光"))
        card, cf = make_card(f, _tr("── 闪光 ──"))
        self._add_color_row(cf, "flash_color", _tr("闪光颜色:"), with_opacity=False)
        self.flash_scale_spn = QSpinBox(); self.flash_scale_spn.setRange(100, 300); self.flash_scale_spn.setValue(int(self.settings.get("flash_scale", DEFAULT_SETTINGS["flash_scale"])))
        cf.addRow(_tr("放大比例%:"), self.flash_scale_spn)
        self.flash_dur_spn = QSpinBox(); self.flash_dur_spn.setRange(100, 2000); self.flash_dur_spn.setSingleStep(50); self.flash_dur_spn.setValue(int(self.settings.get("flash_duration_ms", DEFAULT_SETTINGS["flash_duration_ms"])))
        cf.addRow(_tr("动画时长ms:"), self.flash_dur_spn)
        f.addRow(card)
        card, cf = make_card(f, _tr("── 闪光应用模块 ──"))
        self.flash_apply_spikes_chk = QCheckBox(_tr("尖刺闪光（核心检测模块）"))
        self.flash_apply_spikes_chk.setChecked(bool(self.settings.get("flash_apply_spikes", DEFAULT_SETTINGS["flash_apply_spikes"])))
        cf.addRow(self.flash_apply_spikes_chk)
        self.flash_apply_skill_ready_chk = QCheckBox(_tr("能力冷却完成闪光"))
        self.flash_apply_skill_ready_chk.setChecked(bool(self.settings.get("flash_apply_skill_ready", DEFAULT_SETTINGS["flash_apply_skill_ready"])))
        cf.addRow(self.flash_apply_skill_ready_chk)
        self.flash_apply_dodge_chk = QCheckBox(_tr("翻滚图标闪光"))
        self.flash_apply_dodge_chk.setChecked(bool(self.settings.get("flash_apply_dodge", DEFAULT_SETTINGS["flash_apply_dodge"])))
        cf.addRow(self.flash_apply_dodge_chk)
        f.addRow(card)

        # ============ 顶级标签 2: 核心检测模块 ============
        c_sub = make_top_tab(_tr("核心检测模块"))
        # Buff启用/禁用 + 顺位（放在核心检测模块最前面）
        f = make_sub_tab(c_sub, _tr("Buff启用/禁用"))
        lang = self.settings.get("language", "zh")
        card, cf = make_card(f, _tr("── 角色 Buff 顺位与专精门控（每行三勾选框 = 觉醒/真谛/秘义 / 拖动排序 / 可折叠） ──"))
        # 全局按钮 + 说明文字
        buff_btn_row = QHBoxLayout(); buff_btn_row.setContentsMargins(0, 0, 0, 0); buff_btn_row.setSpacing(8)
        self.buff_btn_all = QPushButton(_tr("全勾选")); self.buff_btn_none = QPushButton(_tr("全取消"))
        self.buff_btn_all.setAutoDefault(False); self.buff_btn_none.setAutoDefault(False)
        # 排序方向：上→左 / 上→右
        dir_lbl = QLabel(_tr("排序方向:"))
        dir_lbl.setStyleSheet("color:#8aa0c0;")
        dir_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.buff_order_direction_combo = QComboBox()
        self.buff_order_direction_combo.setStyleSheet("color:#dce8f8;")
        if lang == "en":
            self.buff_order_direction_combo.addItem("Top → Left", "ltr")
            self.buff_order_direction_combo.addItem("Top → Right", "rtl")
        else:
            self.buff_order_direction_combo.addItem(_tr("越上越靠左"), "ltr")
            self.buff_order_direction_combo.addItem(_tr("越上越靠右"), "rtl")
        cur_dir = self.settings.get("buff_order_direction", DEFAULT_SETTINGS["buff_order_direction"])
        idx = self.buff_order_direction_combo.findData(cur_dir)
        self.buff_order_direction_combo.setCurrentIndex(max(0, idx))
        buff_hint = QLabel(_tr("拖动排序；勾选专精：全选=常显 / 全不选=常关"))
        buff_hint.setWordWrap(True)
        buff_hint.setStyleSheet("color:#8aa0c0;")
        buff_hint.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        buff_btn_row.addWidget(self.buff_btn_all); buff_btn_row.addWidget(self.buff_btn_none)
        buff_btn_row.addWidget(dir_lbl); buff_btn_row.addWidget(self.buff_order_direction_combo)
        buff_btn_row.addWidget(buff_hint, 1)
        buff_btn_row.addStretch()
        buff_btn_container = QWidget(); buff_btn_container.setLayout(buff_btn_row); cf.addRow(buff_btn_container)
        self.buff_order_groups = {}
        buff_order = self.settings.get("buff_order", {})
        buff_mastery = self.settings.get("buff_mastery", {})
        # 仅遍历 pl_id 字符串键，按角色编号排序
        pl_profiles = [(k, v) for k, v in BUFF_PROFILES.items() if isinstance(k, str) and k.startswith("PL")]
        pl_profiles.sort(key=lambda kv: int(kv[0][2:]) if kv[0][2:].isdigit() else 9999)
        # 团长合并组：古兰(PL0000)/姬塔(PL0100) 共享 Class，合并为一组
        captain_group = MasteryBuffGroup(["PL0000", "PL0100"], BUFF_PROFILES["PL0000"], buff_order, buff_mastery, lang)
        captain_group.orderChanged.connect(self._emit_changed)
        self.buff_order_groups["CAPTAIN"] = captain_group
        cf.addRow(captain_group)
        # 其余角色（PL0000/PL0100 已并入团长，伊德 PL1900 含龙人化 PL2000）
        for pl_id, profile in pl_profiles:
            if pl_id in ("PL0000", "PL0100", "PL2000"):
                continue
            group = MasteryBuffGroup([pl_id], profile, buff_order, buff_mastery, lang)
            group.orderChanged.connect(self._emit_changed)
            self.buff_order_groups[pl_id] = group
            cf.addRow(group)
        self.buff_btn_all.clicked.connect(lambda: self._set_all_buff_rank(True))
        self.buff_btn_none.clicked.connect(lambda: self._set_all_buff_rank(False))
        f.addRow(card)
        # 标题栏
        f = make_sub_tab(c_sub, _tr("标题栏"))
        card, cf = make_card(f, _tr("── 标题栏 ──"))
        self.show_titlebar_status = QCheckBox(_tr("在标题栏显示角色名和buff状态文字"))
        self.show_titlebar_status.setChecked(bool(self.settings.get("show_titlebar_status", DEFAULT_SETTINGS["show_titlebar_status"])))
        cf.addRow(_tr("标题栏状态文字:"), self.show_titlebar_status)
        self.titlebar_font_size_spn = QSpinBox(); self.titlebar_font_size_spn.setRange(6, 32); self.titlebar_font_size_spn.setSuffix("px"); self.titlebar_font_size_spn.setValue(int(self.settings.get("titlebar_font_size", DEFAULT_SETTINGS["titlebar_font_size"])))
        cf.addRow(_tr("标题栏字体大小:"), self.titlebar_font_size_spn)
        # 标题栏对齐下拉（靠左/居中/靠右，默认靠左）
        self.title_align_combo = QComboBox()
        self.title_align_combo.addItem(_tr("靠左"), "left")
        self.title_align_combo.addItem(_tr("居中"), "center")
        self.title_align_combo.addItem(_tr("靠右"), "right")
        _align_cur = self.settings.get("title_align", "left")
        _align_idx = self.title_align_combo.findData(_align_cur)
        if _align_idx < 0:
            _align_idx = 0
        self.title_align_combo.setCurrentIndex(_align_idx)
        cf.addRow(_tr("标题栏对齐:"), self.title_align_combo)
        self.title_align_combo.currentIndexChanged.connect(self._emit_changed)
        self.status_indent_spn = QSpinBox(); self.status_indent_spn.setRange(0, 64); self.status_indent_spn.setSuffix("px"); self.status_indent_spn.setValue(int(self.settings.get("titlebar_status_indent", DEFAULT_SETTINGS["titlebar_status_indent"])))
        cf.addRow(_tr("状态行缩进:"), self.status_indent_spn)
        self.icon_indent_spn = QSpinBox(); self.icon_indent_spn.setRange(0, 64); self.icon_indent_spn.setSuffix("px"); self.icon_indent_spn.setValue(int(self.settings.get("titlebar_icon_indent", DEFAULT_SETTINGS["titlebar_icon_indent"])))
        cf.addRow(_tr("图标行缩进:"), self.icon_indent_spn)
        self._add_color_row(cf, "title_bar_color", _tr("标题栏色:"))
        self._add_color_row(cf, "icon_color", _tr("标题UI色:"))
        # V2031：允许负值——标题栏可以叠在圆环画布之上时使用
        self.circle_pad_title = QSpinBox(); self.circle_pad_title.setRange(-999, 999); self.circle_pad_title.setValue(int(self.settings.get("circle_pad_title", DEFAULT_SETTINGS["circle_pad_title"])))
        self.circle_pad_title.setMinimumWidth(110)
        self.circle_pad_title.setToolTip(_tr("标题栏底色行与圆环画布之间的垂直间距（像素）。\n"
                                            "默认 0 表示两者直接贴在一起；想让标题栏和圆之间留出呼吸空间可加大。"))
        cf.addRow(_tr("标题→圆间距:"), self.circle_pad_title)
        f.addRow(card)
        # 尖刺与圆环
        f = make_sub_tab(c_sub, _tr("尖刺与圆环"))
        card, cf = make_card(f, _tr("── 尖刺(含顶端圆点) ──"))
        self.spike_length = QSpinBox(); self.spike_length.setRange(8, 80); self.spike_length.setValue(int(self.settings.get("spike_length", DEFAULT_SETTINGS["spike_length"])))
        cf.addRow(_tr("尖刺长度:"), self.spike_length)
        self.spike_axis_pos = QSpinBox(); self.spike_axis_pos.setRange(-60, 80); self.spike_axis_pos.setSuffix("%"); self.spike_axis_pos.setValue(int(self.settings.get("spike_axis_pos_percent", DEFAULT_SETTINGS["spike_axis_pos_percent"])))
        cf.addRow(_tr("尖刺根部距圆心:"), self.spike_axis_pos)
        self.spike_width = QSpinBox(); self.spike_width.setRange(8, 100); self.spike_width.setSuffix("px"); self.spike_width.setValue(int(self.settings.get("spike_width", DEFAULT_SETTINGS["spike_width"])))
        cf.addRow(_tr("尖刺宽度:"), self.spike_width)
        # V2243: 范围 5-95 → 0-100,允许极端腰位（顶部圆点 / 根部圆点）。
        # 渲染端已有 `max(0.05, min(0.95, self.spike_waist_pos))` 安全夹紧，UI 0/100 不会被渲染误用。
        self.spike_waist_pos = QSpinBox(); self.spike_waist_pos.setRange(0, 100); self.spike_waist_pos.setSuffix("%"); self.spike_waist_pos.setValue(int(self.settings.get("spike_waist_pos_percent", DEFAULT_SETTINGS["spike_waist_pos_percent"])))
        cf.addRow(_tr("尖刺腰位置:"), self.spike_waist_pos)
        self.spike_bead_radius = QSpinBox(); self.spike_bead_radius.setRange(0, 30); self.spike_bead_radius.setSuffix("px"); self.spike_bead_radius.setValue(int(self.settings.get("spike_bead_radius", DEFAULT_SETTINGS["spike_bead_radius"])))
        cf.addRow(_tr("尖刺顶端圆点半径:"), self.spike_bead_radius)
        self.spike_bead_pos = QSpinBox(); self.spike_bead_pos.setRange(-60, 80); self.spike_bead_pos.setSuffix("%"); self.spike_bead_pos.setValue(int(self.settings.get("spike_bead_pos_percent", DEFAULT_SETTINGS["spike_bead_pos_percent"])))
        cf.addRow(_tr("顶端圆点距圆心:"), self.spike_bead_pos)
        self._add_color_row(cf, "spike_color_normal", _tr("尖刺色(正常):"))
        self._add_color_row(cf, "spike_color_lv7", _tr("尖刺色(满层):"))
        self.show_spikes_chk = QCheckBox(_tr("显示尖刺（三角本体）"))
        self.show_spikes_chk.setChecked(bool(self.settings.get("show_spikes", DEFAULT_SETTINGS["show_spikes"])))
        cf.addRow(self.show_spikes_chk)
        self.show_bead_chk = QCheckBox(_tr("显示装饰小球（尖刺顶端圆点）"))
        self.show_bead_chk.setChecked(bool(self.settings.get("show_bead", DEFAULT_SETTINGS["show_bead"])))
        cf.addRow(self.show_bead_chk)
        f.addRow(card)
        card, cf = make_card(f, _tr("── 圆环 ──"))
        self.circle_radius = QSpinBox(); self.circle_radius.setRange(30, 120); self.circle_radius.setValue(int(self.settings.get("circle_radius", DEFAULT_SETTINGS["circle_radius"])))
        cf.addRow(_tr("圆半径:"), self.circle_radius)
        # V2240：核心画布宽/高可调——0 显示「自动」，>0 覆盖自动计算值（强制下限防裁切）
        self.core_canvas_w_spn = QSpinBox(); self.core_canvas_w_spn.setRange(0, 4000); self.core_canvas_w_spn.setSuffix("px"); self.core_canvas_w_spn.setSpecialValueText(_tr("自动")); self.core_canvas_w_spn.setValue(int(self.settings.get("core_canvas_w", DEFAULT_SETTINGS["core_canvas_w"])))
        self.core_canvas_w_spn.setMinimumWidth(110)
        self.core_canvas_w_spn.setToolTip(_tr("核心模块画布宽度（像素）。0 = 自动（按尖刺/圆环/标题自动计算）。\n"
                                              "设大窗口会更宽，内容（圆/标题/buff 名）自动水平居中；设太小会被强制拉回防裁切下限。"))
        cf.addRow(_tr("画布宽(0=自动):"), self.core_canvas_w_spn)
        self.core_canvas_h_spn = QSpinBox(); self.core_canvas_h_spn.setRange(0, 4000); self.core_canvas_h_spn.setSuffix("px"); self.core_canvas_h_spn.setSpecialValueText(_tr("自动")); self.core_canvas_h_spn.setValue(int(self.settings.get("core_canvas_h", DEFAULT_SETTINGS["core_canvas_h"])))
        self.core_canvas_h_spn.setMinimumWidth(110)
        self.core_canvas_h_spn.setToolTip(_tr("核心模块画布高度（像素）。0 = 自动（按尖刺/圆环/标题自动计算）。\n"
                                              "设大窗口会更高，内容（圆/标题/buff 名）自动垂直居中；设太小会被强制拉回防裁切下限。"))
        cf.addRow(_tr("画布高(0=自动):"), self.core_canvas_h_spn)
        self._add_color_row(cf, "circle_color_normal", _tr("圆环色(正常):"))
        self._add_color_row(cf, "circle_color_lv7", _tr("圆环色(满层):"))
        f.addRow(card)
        card, cf = make_card(f, _tr("── 外描边 ──"))
        self.indicator_outline_enabled = QCheckBox(_tr("启用整体外描边"))
        self.indicator_outline_enabled.setChecked(bool(self.settings.get("use_indicator_outline", DEFAULT_SETTINGS["use_indicator_outline"])))
        cf.addRow(_tr("整体外描边:"), self.indicator_outline_enabled)
        self.indicator_outline_width = QSpinBox(); self.indicator_outline_width.setRange(0, 20); self.indicator_outline_width.setSuffix("px"); self.indicator_outline_width.setValue(int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])))
        cf.addRow(_tr("外描边粗细:"), self.indicator_outline_width)
        self._add_color_row(cf, "indicator_outline_color", _tr("外描边色:"))
        f.addRow(card)
        # V2263：3D 效果 sub-tab（尖刺/小球立体感可调参数集中页）
        f = make_sub_tab(c_sub, _tr("3D 效果"))
        # === 卡片 1：尖刺立体感 ===
        card, cf = make_card(f, _tr("── 尖刺立体感 ──"))
        # 风格下拉
        self.spike_3d_style_combo = QComboBox()
        self.spike_3d_style_combo.addItem(_tr("纯色（无 3D 效果）"), "flat")
        self.spike_3d_style_combo.addItem(_tr("斜向两分面（最像 3D 棱锥/钻石，V2264 风格）"), "two_tone")
        _idx = self.spike_3d_style_combo.findData(self.settings.get("spike_3d_style", DEFAULT_SETTINGS["spike_3d_style"]))
        self.spike_3d_style_combo.setCurrentIndex(max(0, _idx))
        cf.addRow(_tr("尖刺风格:"), self.spike_3d_style_combo)
        # 通用投影组
        card_sh, cf_sh = make_card(f, _tr("── 通用投影（所有风格共用）──"))
        self.spike_3d_shadow_enabled_chk = QCheckBox(_tr("启用投影"))
        self.spike_3d_shadow_enabled_chk.stateChanged.connect(self._emit_changed)  # V2301 实时生效
        self.spike_3d_shadow_enabled_chk.setChecked(bool(self.settings.get("spike_3d_shadow_enabled", DEFAULT_SETTINGS["spike_3d_shadow_enabled"])))
        cf_sh.addRow(self.spike_3d_shadow_enabled_chk)
        self.spike_3d_shadow_offset_x_spn = QSpinBox(); self.spike_3d_shadow_offset_x_spn.setRange(0, 20); self.spike_3d_shadow_offset_x_spn.setSuffix("px"); self.spike_3d_shadow_offset_x_spn.setValue(int(self.settings.get("spike_3d_shadow_offset_x", DEFAULT_SETTINGS["spike_3d_shadow_offset_x"])))
        self.spike_3d_shadow_offset_x_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        cf_sh.addRow(_tr("投影偏移 X:"), self.spike_3d_shadow_offset_x_spn)
        self.spike_3d_shadow_offset_y_spn = QSpinBox(); self.spike_3d_shadow_offset_y_spn.setRange(0, 20); self.spike_3d_shadow_offset_y_spn.setSuffix("px"); self.spike_3d_shadow_offset_y_spn.setValue(int(self.settings.get("spike_3d_shadow_offset_y", DEFAULT_SETTINGS["spike_3d_shadow_offset_y"])))
        self.spike_3d_shadow_offset_y_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        cf_sh.addRow(_tr("投影偏移 Y:"), self.spike_3d_shadow_offset_y_spn)
        self.spike_3d_shadow_alpha_spn = QSpinBox(); self.spike_3d_shadow_alpha_spn.setRange(0, 255); self.spike_3d_shadow_alpha_spn.setValue(int(self.settings.get("spike_3d_shadow_alpha", DEFAULT_SETTINGS["spike_3d_shadow_alpha"])))
        self.spike_3d_shadow_alpha_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        cf_sh.addRow(_tr("投影不透明度 (0-255):"), self.spike_3d_shadow_alpha_spn)
        f.addRow(card_sh)
        # 通用暗描边组
        card_ol, cf_ol = make_card(f, _tr("── 通用暗描边（所有风格共用）──"))
        self.spike_3d_outline_enabled_chk = QCheckBox(_tr("启用暗描边"))
        self.spike_3d_outline_enabled_chk.stateChanged.connect(self._emit_changed)  # V2301 实时生效
        self.spike_3d_outline_enabled_chk.setChecked(bool(self.settings.get("spike_3d_outline_enabled", DEFAULT_SETTINGS["spike_3d_outline_enabled"])))
        cf_ol.addRow(self.spike_3d_outline_enabled_chk)
        # 暗描边宽度用 slider（0.0-3.0，步长 0.1）
        self.spike_3d_outline_width_sld = QSlider(Qt.Horizontal); self.spike_3d_outline_width_sld.setRange(0, 30); self.spike_3d_outline_width_sld.setValue(int(round(float(self.settings.get("spike_3d_outline_width", DEFAULT_SETTINGS["spike_3d_outline_width"])) * 10)))
        self.spike_3d_outline_width_lbl = QLabel(f"{self.spike_3d_outline_width_sld.value()/10.0:.1f}px")
        self.spike_3d_outline_width_sld.valueChanged.connect(lambda v: (self.spike_3d_outline_width_lbl.setText(f"{v/10.0:.1f}px"), self._emit_changed()))
        _ol_w = QWidget(); _ol_w_lay = QHBoxLayout(_ol_w); _ol_w_lay.setContentsMargins(0,0,0,0); _ol_w_lay.addWidget(self.spike_3d_outline_width_sld); _ol_w_lay.addWidget(self.spike_3d_outline_width_lbl)
        cf_ol.addRow(_tr("暗描边宽度 (0.0-3.0px):"), _ol_w)
        self.spike_3d_outline_dark_spn = QSpinBox(); self.spike_3d_outline_dark_spn.setRange(100, 200); self.spike_3d_outline_dark_spn.setValue(int(self.settings.get("spike_3d_outline_dark", DEFAULT_SETTINGS["spike_3d_outline_dark"])))
        self.spike_3d_outline_dark_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        cf_ol.addRow(_tr("暗描边暗度 (100=不暗):"), self.spike_3d_outline_dark_spn)
        f.addRow(card_ol)
        # 动态：每风格独立参数（QStackedWidget 根据下拉切换）
        self._spike_3d_style_params_stack = QStackedWidget()
        # --- flat：无参数 ---
        _flat_page = QWidget(); _flat_lay = QVBoxLayout(_flat_page); _flat_lay.setContentsMargins(0,0,0,0)
        _flat_hint = QLabel(_tr("纯色风格无独立参数（只受上面通用投影/暗描边影响）。"))
        _flat_hint.setStyleSheet("color:#8aa0c0;")
        _flat_hint.setWordWrap(True)
        _flat_lay.addWidget(_flat_hint)
        self._spike_3d_style_params_stack.addWidget(_flat_page)
        # --- two_tone（V2264 最简两分面）：左半亮因子 + 右半暗因子 ---
        _tt_page = QWidget(); _tt_form = QFormLayout(_tt_page)
        _tt_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        _tt_form.setContentsMargins(0,0,0,0)
        self.spike_3d_twotone_light_spn = QSpinBox(); self.spike_3d_twotone_light_spn.setRange(100, 200); self.spike_3d_twotone_light_spn.setValue(int(self.settings.get("spike_3d_twotone_light", DEFAULT_SETTINGS["spike_3d_twotone_light"])))
        self.spike_3d_twotone_light_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        _tt_form.addRow(_tr("左半亮因子 (100=不亮):"), self.spike_3d_twotone_light_spn)
        self.spike_3d_twotone_dark_spn = QSpinBox(); self.spike_3d_twotone_dark_spn.setRange(50, 150); self.spike_3d_twotone_dark_spn.setValue(int(self.settings.get("spike_3d_twotone_dark", DEFAULT_SETTINGS["spike_3d_twotone_dark"])))
        self.spike_3d_twotone_dark_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        _tt_form.addRow(_tr("右半暗因子 (100=不暗):"), self.spike_3d_twotone_dark_spn)
        _tt_hint = QLabel(_tr("沿尖刺左→右方向做硬边两分面（中间 0.48-0.52 窄过渡），模拟棱锥/钻石切面。"))
        _tt_hint.setStyleSheet("color:#8aa0c0;")
        _tt_hint.setWordWrap(True)
        _tt_form.addRow(_tt_hint)
        self._spike_3d_style_params_stack.addWidget(_tt_page)
        # 风格切换时切换 stack 页
        def _on_spike_3d_style_changed(idx):
            self._spike_3d_style_params_stack.setCurrentIndex(idx)
            self._emit_changed()
        self.spike_3d_style_combo.currentIndexChanged.connect(_on_spike_3d_style_changed)
        self._spike_3d_style_params_stack.setCurrentIndex(self.spike_3d_style_combo.currentIndex())
        cf.addRow(self._spike_3d_style_params_stack)
        f.addRow(card)
        # === 卡片 2：装饰小球立体感 ===
        card_bead, cf_bead = make_card(f, _tr("── 装饰小球立体感 ──"))
        self.bead_3d_style_combo = QComboBox()
        self.bead_3d_style_combo.addItem(_tr("纯色"), "flat")
        self.bead_3d_style_combo.addItem(_tr("径向球化（推荐）"), "radial_gradient")
        _bidx = self.bead_3d_style_combo.findData(self.settings.get("bead_3d_style", DEFAULT_SETTINGS["bead_3d_style"]))
        self.bead_3d_style_combo.setCurrentIndex(max(0, _bidx))
        cf_bead.addRow(_tr("小球风格:"), self.bead_3d_style_combo)
        # 动态：小球参数
        self._bead_3d_params_stack = QStackedWidget()
        _bead_flat = QWidget(); _bead_flat_lay = QVBoxLayout(_bead_flat); _bead_flat_lay.setContentsMargins(0,0,0,0)
        _bead_flat_hint = QLabel(_tr("纯色风格无独立参数。"))
        _bead_flat_hint.setStyleSheet("color:#8aa0c0;")
        _bead_flat_lay.addWidget(_bead_flat_hint)
        self._bead_3d_params_stack.addWidget(_bead_flat)
        _bead_rg = QWidget(); _bead_rg_form = QFormLayout(_bead_rg)
        _bead_rg_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        _bead_rg_form.setContentsMargins(0,0,0,0)
        self.bead_3d_light_spn = QSpinBox(); self.bead_3d_light_spn.setRange(100, 250); self.bead_3d_light_spn.setValue(int(self.settings.get("bead_3d_light", DEFAULT_SETTINGS["bead_3d_light"])))
        self.bead_3d_light_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        _bead_rg_form.addRow(_tr("高光亮因子 (100=不亮):"), self.bead_3d_light_spn)
        self.bead_3d_dark_spn = QSpinBox(); self.bead_3d_dark_spn.setRange(50, 150); self.bead_3d_dark_spn.setValue(int(self.settings.get("bead_3d_dark", DEFAULT_SETTINGS["bead_3d_dark"])))
        self.bead_3d_dark_spn.valueChanged.connect(self._emit_changed)  # V2301 实时生效
        _bead_rg_form.addRow(_tr("边缘暗因子 (100=不暗):"), self.bead_3d_dark_spn)
        # 高光偏移用 slider（0.00-0.50，步长 0.01）
        self.bead_3d_highlight_offset_sld = QSlider(Qt.Horizontal); self.bead_3d_highlight_offset_sld.setRange(0, 50); self.bead_3d_highlight_offset_sld.setValue(int(round(float(self.settings.get("bead_3d_highlight_offset", DEFAULT_SETTINGS["bead_3d_highlight_offset"])) * 100)))
        self.bead_3d_highlight_offset_lbl = QLabel(f"{self.bead_3d_highlight_offset_sld.value()/100.0:.2f}")
        self.bead_3d_highlight_offset_sld.valueChanged.connect(lambda v: (self.bead_3d_highlight_offset_lbl.setText(f"{v/100.0:.2f}"), self._emit_changed()))
        _bo_w = QWidget(); _bo_w_lay = QHBoxLayout(_bo_w); _bo_w_lay.setContentsMargins(0,0,0,0); _bo_w_lay.addWidget(self.bead_3d_highlight_offset_sld); _bo_w_lay.addWidget(self.bead_3d_highlight_offset_lbl)
        _bead_rg_form.addRow(_tr("高光中心偏移 (0=正中心):"), _bo_w)
        _bead_rg_hint = QLabel(_tr("径向球化：高光偏左上模拟右上光源，数值越大偏移越远。"))
        _bead_rg_hint.setStyleSheet("color:#8aa0c0;")
        _bead_rg_hint.setWordWrap(True)
        _bead_rg_form.addRow(_bead_rg_hint)
        self._bead_3d_params_stack.addWidget(_bead_rg)
        def _on_bead_3d_style_changed(idx):
            self._bead_3d_params_stack.setCurrentIndex(idx)
            self._emit_changed()
        self.bead_3d_style_combo.currentIndexChanged.connect(_on_bead_3d_style_changed)
        self._bead_3d_params_stack.setCurrentIndex(self.bead_3d_style_combo.currentIndex())
        cf_bead.addRow(self._bead_3d_params_stack)
        f.addRow(card_bead)
        # 倒计时
        f = make_sub_tab(c_sub, _tr("倒计时"))
        card, cf = make_card(f, _tr("── 倒计时弧线 ──"))
        self.timer_style = QComboBox(); self.timer_style.addItem(_tr("圆环"), "ring"); self.timer_style.addItem(_tr("扇形"), "sector")
        idx = self.timer_style.findData(self.settings.get("timer_style", DEFAULT_SETTINGS["timer_style"])); self.timer_style.setCurrentIndex(max(0, idx))
        cf.addRow(_tr("倒计时样式:"), self.timer_style)
        self.timer_arc_radius = QSpinBox(); self.timer_arc_radius.setRange(0, 60); self.timer_arc_radius.setValue(int(self.settings.get("timer_arc_radius_offset", DEFAULT_SETTINGS["timer_arc_radius_offset"])))
        cf.addRow(_tr("倒计时弧线内缩:"), self.timer_arc_radius)
        self.timer_center_y = QSpinBox(); self.timer_center_y.setRange(-50, 50); self.timer_center_y.setValue(int(self.settings.get("timer_center_offset_y", 0)))
        cf.addRow(_tr("倒计时圆心Y偏移:"), self.timer_center_y)
        self._add_color_row(cf, "arc_color", _tr("倒计时弧颜色:"))
        f.addRow(card)
        card, cf = make_card(f, _tr("── 倒计时胶囊 ──"))
        self.lv7_timer_y_offset = QSpinBox(); self.lv7_timer_y_offset.setRange(-30, 30); self.lv7_timer_y_offset.setValue(int(self.settings.get("lv7_timer_y_offset", 0)))
        cf.addRow(_tr("时间胶囊Y偏移:"), self.lv7_timer_y_offset)
        self.lv7_timer_badge_width = QSpinBox(); self.lv7_timer_badge_width.setRange(0, 40); self.lv7_timer_badge_width.setSuffix("px"); self.lv7_timer_badge_width.setValue(int(self.settings.get("lv7_timer_badge_width", DEFAULT_SETTINGS["lv7_timer_badge_width"])))
        cf.addRow(_tr("时间胶囊宽度:"), self.lv7_timer_badge_width)
        self.timer_font_size = QSpinBox(); self.timer_font_size.setRange(0, 48); self.timer_font_size.setValue(int(self.settings.get("timer_font_size", DEFAULT_SETTINGS["timer_font_size"])))
        cf.addRow(_tr("倒计时字体大小:"), self.timer_font_size)
        self._add_color_row(cf, "timer_text_color", _tr("倒计时文字色:"))
        f.addRow(card)
        card, cf = make_card(f, _tr("── 单层buff倒计时胶囊 ──"))
        self.single_timer_y_offset = QSpinBox(); self.single_timer_y_offset.setRange(-30, 30); self.single_timer_y_offset.setValue(int(self.settings.get("single_timer_y_offset", DEFAULT_SETTINGS["single_timer_y_offset"])))
        cf.addRow(_tr("时间胶囊Y偏移:"), self.single_timer_y_offset)
        self.single_timer_badge_width = QSpinBox(); self.single_timer_badge_width.setRange(0, 40); self.single_timer_badge_width.setSuffix("px"); self.single_timer_badge_width.setValue(int(self.settings.get("single_timer_badge_width", DEFAULT_SETTINGS["single_timer_badge_width"])))
        cf.addRow(_tr("时间胶囊宽度:"), self.single_timer_badge_width)
        self.single_timer_font_size = QSpinBox(); self.single_timer_font_size.setRange(0, 48); self.single_timer_font_size.setValue(int(self.settings.get("single_timer_font_size", DEFAULT_SETTINGS["single_timer_font_size"])))
        cf.addRow(_tr("倒计时字体大小:"), self.single_timer_font_size)
        self._add_color_row(cf, "single_timer_text_color", _tr("倒计时文字色:"))
        f.addRow(card)
        # 层数数字
        f = make_sub_tab(c_sub, _tr("层数数字"))
        card, cf = make_card(f, _tr("── 层数数字(无计时) ──"))
        self.center_offset_x = QSpinBox(); self.center_offset_x.setRange(-50, 50); self.center_offset_x.setValue(int(self.settings.get("center_text_offset_x", 0)))
        cf.addRow(_tr("层数数字X偏移:"), self.center_offset_x)
        self.center_offset_y = QSpinBox(); self.center_offset_y.setRange(-50, 50); self.center_offset_y.setValue(int(self.settings.get("center_text_offset_y", 0)))
        cf.addRow(_tr("层数数字Y偏移:"), self.center_offset_y)
        self.dh_font_size = QSpinBox(); self.dh_font_size.setRange(14, 72); self.dh_font_size.setValue(int(self.settings.get("dh_font_size", DEFAULT_SETTINGS["dh_font_size"])))
        cf.addRow(_tr("层数数字大小:"), self.dh_font_size)
        self.dh_text_outline_width = QSpinBox(); self.dh_text_outline_width.setRange(0, 12); self.dh_text_outline_width.setValue(int(self.settings.get("dh_text_outline_width", DEFAULT_SETTINGS["dh_text_outline_width"])))
        cf.addRow(_tr("层数数字勾边粗细:"), self.dh_text_outline_width)
        self._add_color_row(cf, "text_color", _tr("层数数字色:"))
        self._add_color_row(cf, "dh_text_outline_color", _tr("层数数字勾边色:"))
        f.addRow(card)
        card, cf = make_card(f, _tr("── 层数数字(有计时) ──"))
        self.center_offset_x_timer = QSpinBox(); self.center_offset_x_timer.setRange(-50, 50); self.center_offset_x_timer.setValue(int(self.settings.get("center_text_offset_x_timer", 0)))
        cf.addRow(_tr("层数数字X偏移 — (计时版):"), self.center_offset_x_timer)
        self.center_offset_y_timer = QSpinBox(); self.center_offset_y_timer.setRange(-50, 50); self.center_offset_y_timer.setValue(int(self.settings.get("center_text_offset_y_timer", 0)))
        cf.addRow(_tr("层数数字Y偏移 — (计时版):"), self.center_offset_y_timer)
        self.dh_font_size_timer = QSpinBox(); self.dh_font_size_timer.setRange(14, 72); self.dh_font_size_timer.setValue(int(self.settings.get("dh_font_size_timer", DEFAULT_SETTINGS["dh_font_size_timer"])))
        cf.addRow(_tr("层数数字大小 — (计时版):"), self.dh_font_size_timer)
        self.dh_text_outline_width_timer = QSpinBox(); self.dh_text_outline_width_timer.setRange(0, 12); self.dh_text_outline_width_timer.setValue(int(self.settings.get("dh_text_outline_width_timer", DEFAULT_SETTINGS["dh_text_outline_width_timer"])))
        cf.addRow(_tr("层数数字勾边粗细 — (计时版):"), self.dh_text_outline_width_timer)
        self._add_color_row(cf, "text_color_timer", _tr("层数数字色 — (计时版):"))
        self._add_color_row(cf, "dh_text_outline_color_timer", _tr("层数数字勾边色 — (计时版):"))
        f.addRow(card)
        # 多buff差异化（按同时监测的buff个数 2/3/4/5 分组，每组 5 参数 = 20）
        f = make_sub_tab(c_sub, _tr("多buff布局"))
        card, cf = make_card(f, _tr("── 多buff差异化（按同时监测的buff个数 2/3/4/5；每组：缩放 / 圆心水平间距 / 圆心Delta_Y / 外部差异化颜色 / 内部差异化颜色） ──"))

        def _mb_slider(target, label_key, key, default, rmin, rmax, suffix, value_scale=1):
            label_text = _tr(label_key)
            if "{}" in label_text:
                label_text = label_text.format(cnt)
            lbl = QLabel(label_text)
            sl = QSlider(Qt.Horizontal); sl.setRange(rmin, rmax)
            sp = QSpinBox(); sp.setRange(rmin, rmax); sp.setSuffix(suffix)
            # value_scale>1 时，settings 里存的是浮点比例（如 0.68），UI 显示整数（如 68）
            raw = self.settings.get(key, default / value_scale)
            v = int(round(raw * value_scale))
            sl.setValue(v); sp.setValue(v)
            sl.valueChanged.connect(sp.setValue); sp.valueChanged.connect(sl.setValue)
            sl.valueChanged.connect(self._emit_changed)
            row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
            row.addWidget(sl); row.addWidget(sp)
            c = QWidget(); c.setLayout(row); target.addRow(lbl, c)
            return sl, sp, lbl

        def _mb_check(target, label_key, key, default):
            lbl = QLabel(_tr(label_key).format(cnt))
            cb = QCheckBox(); cb.setChecked(bool(self.settings.get(key, default)))
            cb.stateChanged.connect(self._emit_changed)
            target.addRow(lbl, cb)
            return cb, lbl

        self.multi_buff_ctrls = {}
        self.multi_buff_labels = {}  # (cnt, key) -> QLabel / QGroupBox
        for cnt in (2, 3, 4, 5):
            # 每个 buff 个数各包一个小组框，实现不同个数之间的隔离
            gb = QGroupBox(_tr("{} 个 buff 同屏").format(cnt))
            self.multi_buff_labels[(cnt, "group_title")] = gb
            gb.setStyleSheet("QGroupBox{border:1px solid #3a4a66;border-radius:6px;margin-top:6px;"
                             "padding-top:10px;color:#cfe0ff;font-weight:bold;font-size:11px;}"
                             "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
            gcf = QFormLayout(); gcf.setContentsMargins(8, 8, 8, 8); gcf.setSpacing(4)
            gb.setLayout(gcf)
            ctrl = {"gb": gb}
            ctrl["scale_sl"], ctrl["scale_sp"], self.multi_buff_labels[(cnt, "scale")] = _mb_slider(
                gcf, _tr("缩放{}:"), f"multi_buff_scale_{cnt}", DEFAULT_SETTINGS[f"multi_buff_scale_{cnt}"], 20, 100, "%")
            ctrl["hgap_sl"], ctrl["hgap_sp"], self.multi_buff_labels[(cnt, "hgap")] = _mb_slider(
                gcf, _tr("圆心水平间距{}:"), f"multi_buff_hgap_{cnt}", DEFAULT_SETTINGS[f"multi_buff_hgap_{cnt}"], 20, 400, "px")
            ctrl["dy_sl"], ctrl["dy_sp"], self.multi_buff_labels[(cnt, "dy")] = _mb_slider(
                gcf, _tr("圆心Delta_Y{}:"), f"multi_buff_dy_{cnt}", DEFAULT_SETTINGS[f"multi_buff_dy_{cnt}"], -300, 300, "px")
            ctrl["ext_cb"], self.multi_buff_labels[(cnt, "ext_color")] = _mb_check(
                gcf, _tr("外部差异化颜色{}:"), f"multi_buff_ext_color_{cnt}", DEFAULT_SETTINGS[f"multi_buff_ext_color_{cnt}"])
            ctrl["int_cb"], self.multi_buff_labels[(cnt, "int_color")] = _mb_check(
                gcf, _tr("内部差异化颜色{}:"), f"multi_buff_int_color_{cnt}", DEFAULT_SETTINGS[f"multi_buff_int_color_{cnt}"])
            # 颜色分布模式：下拉选单 + 同色系间距（仅同色系启用）
            mode_cb = QComboBox()
            mode_cb.addItem(_tr("色环均匀 / 大反差"), "uniform")
            mode_cb.addItem(_tr("同色系 / 相近"), "monochrome")
            cur_mode = self.settings.get(f"multi_buff_color_mode_{cnt}", DEFAULT_SETTINGS[f"multi_buff_color_mode_{cnt}"])
            mode_cb.setCurrentIndex(0 if cur_mode == "uniform" else 1)
            mode_cb.currentIndexChanged.connect(self._emit_changed)
            mode_lbl = QLabel(_tr("颜色分布模式{}:").format(cnt))
            self.multi_buff_labels[(cnt, "mode")] = mode_lbl
            gcf.addRow(mode_lbl, mode_cb)
            ctrl["mode_cb"] = mode_cb
            ctrl["mono_span_sl"], ctrl["mono_span_sp"], self.multi_buff_labels[(cnt, "mono_span")] = _mb_slider(
                gcf, _tr("同色系间距{}:"), f"multi_buff_mono_span_{cnt}",
                DEFAULT_SETTINGS[f"multi_buff_mono_span_{cnt}"], -180, 180, "°")
            ctrl["mono_span_sl"].setEnabled(cur_mode == "monochrome")
            ctrl["mono_span_sp"].setEnabled(cur_mode == "monochrome")
            def _on_mode_changed(idx, mcb=mode_cb, ms_sl=ctrl["mono_span_sl"], ms_sp=ctrl["mono_span_sp"]):
                mode = mcb.itemData(idx)
                en = (mode == "monochrome")
                ms_sl.setEnabled(en); ms_sp.setEnabled(en)
                self._emit_changed()
            mode_cb.currentIndexChanged.connect(_on_mode_changed)
            self.multi_buff_ctrls[cnt] = ctrl
            cf.addRow(gb)
        f.addRow(card)
        # Buff名字
        f = make_sub_tab(c_sub, _tr("Buff名字"))
        card, cf = make_card(f)
        self.show_buff_name_cb = QCheckBox(_tr("在画布上显示Buff名称"))
        self.show_buff_name_cb.setChecked(bool(self.settings.get("show_buff_name", DEFAULT_SETTINGS["show_buff_name"]))); cf.addRow(_tr("Buff名显示:"), self.show_buff_name_cb)
        self.buff_name_font_size = QSpinBox(); self.buff_name_font_size.setRange(1, 48); self.buff_name_font_size.setSuffix(" px"); self.buff_name_font_size.setValue(int(self.settings.get("buff_name_font_size", DEFAULT_SETTINGS["buff_name_font_size"])))
        cf.addRow(_tr("Buff名字体大小:"), self.buff_name_font_size)
        name_pos_row = QHBoxLayout(); name_pos_row.setContentsMargins(0, 0, 0, 0); name_pos_row.setSpacing(8)
        self.buff_name_offset_x = QSpinBox(); self.buff_name_offset_x.setRange(-200, 200); self.buff_name_offset_x.setPrefix("X "); self.buff_name_offset_x.setValue(int(self.settings.get("buff_name_offset_x", DEFAULT_SETTINGS["buff_name_offset_x"])))
        self.buff_name_offset_y = QSpinBox(); self.buff_name_offset_y.setRange(-200, 200); self.buff_name_offset_y.setPrefix("Y "); self.buff_name_offset_y.setValue(int(self.settings.get("buff_name_offset_y", DEFAULT_SETTINGS["buff_name_offset_y"])))
        name_pos_row.addWidget(self.buff_name_offset_x); name_pos_row.addWidget(self.buff_name_offset_y)
        name_pos_container = QWidget(); name_pos_container.setLayout(name_pos_row); cf.addRow(_tr("Buff名位置:"), name_pos_container)
        self.buff_name_bg_width = QSpinBox(); self.buff_name_bg_width.setRange(-100, 100); self.buff_name_bg_width.setSuffix(" px"); self.buff_name_bg_width.setValue(int(self.settings.get("buff_name_bg_width", DEFAULT_SETTINGS["buff_name_bg_width"])))
        cf.addRow(_tr("Buff名衬色块宽度微调:"), self.buff_name_bg_width)
        self._add_color_row(f, "buff_name_color", _tr("Buff名色:"))
        f.addRow(card)
        # 隐藏与位置
        f = make_sub_tab(c_sub, _tr("位置与隐藏"))
        card, cf = make_card(f, _tr("── 隐藏 ──"))
        self.spike_hide_chk = QCheckBox(_tr("无buff时隐藏尖刺圆模块（翻滚/技能UI不受影响）"))
        self.spike_hide_chk.setChecked(bool(self.settings.get("spike_hide_when_no_buff", DEFAULT_SETTINGS["spike_hide_when_no_buff"])))
        cf.addRow(self.spike_hide_chk)
        self.spike_hidden_op_spn = QSpinBox(); self.spike_hidden_op_spn.setRange(0, 100); self.spike_hidden_op_spn.setSuffix("%"); self.spike_hidden_op_spn.setValue(int(self.settings.get("spike_hidden_opacity", DEFAULT_SETTINGS["spike_hidden_opacity"])))
        cf.addRow(_tr("隐藏时透明度:"), self.spike_hidden_op_spn)
        f.addRow(card)
        # 核心模块位置与缩放（从原“模块位置”顶级标签迁入）
        card, cf = make_card(f, _tr("── 核心模块位置与缩放 ──"))
        self.core_x_spn, self.core_y_spn = _mk_pos_row(cf, "core_window_x", "core_window_y")
        self.core_scale_slider, self.core_scale_spin = _mk_scale_row(cf, "core", _tr("模块缩放:"))
        # V2229：整屏对齐（核心模块）——与全 Buff/Boss 模式一致
        self.core_halign_combo = QComboBox()
        self.core_halign_combo.addItem(_tr("自定义"), "custom")
        self.core_halign_combo.addItem(_tr("靠左"), "left")
        self.core_halign_combo.addItem(_tr("居中"), "center")
        self.core_halign_combo.addItem(_tr("靠右"), "right")
        _cur_ha = str(self.settings.get("core_halign", DEFAULT_SETTINGS["core_halign"]))
        _idx_ha = self.core_halign_combo.findData(_cur_ha)
        if _idx_ha < 0: _idx_ha = 0
        self.core_halign_combo.setCurrentIndex(_idx_ha)
        self.core_halign_combo.setToolTip(_tr("整屏水平对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「靠左」贴屏幕左缘；「居中」水平居中；「靠右」贴屏幕右缘。每次刷新窗口（缩放/分辨率变化/行数变化）都会重算，始终贴边或居中。"))
        self.core_valign_combo = QComboBox()
        self.core_valign_combo.addItem(_tr("自定义"), "custom")
        self.core_valign_combo.addItem(_tr("顶部对齐"), "top")
        self.core_valign_combo.addItem(_tr("居中"), "center")
        self.core_valign_combo.addItem(_tr("底部对齐"), "bottom")
        _cur_va = str(self.settings.get("core_valign", DEFAULT_SETTINGS["core_valign"]))
        _idx_va = self.core_valign_combo.findData(_cur_va)
        if _idx_va < 0: _idx_va = 0
        self.core_valign_combo.setCurrentIndex(_idx_va)
        self.core_valign_combo.setToolTip(_tr("整屏垂直对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「顶部对齐」贴屏幕上缘；「居中」垂直居中；「底部对齐」贴屏幕下缘（已排除任务栏）。每次刷新窗口都会重算。"))
        self.core_hmargin_spn = QSpinBox(); self.core_hmargin_spn.setRange(-2000, 2000); self.core_hmargin_spn.setSuffix(" px"); self.core_hmargin_spn.setValue(int(self.settings.get("core_hmargin", DEFAULT_SETTINGS["core_hmargin"])))
        self.core_hmargin_spn.setToolTip(_tr("水平对齐时的左右边距。仅在「靠左 / 靠右」时生效。正数把窗口往外推；负数让窗口往里推（可溢出屏幕外）。「自定义/居中」不使用。"))
        self.core_vmargin_spn = QSpinBox(); self.core_vmargin_spn.setRange(-2000, 2000); self.core_vmargin_spn.setSuffix(" px"); self.core_vmargin_spn.setValue(int(self.settings.get("core_vmargin", DEFAULT_SETTINGS["core_vmargin"])))
        self.core_vmargin_spn.setToolTip(_tr("垂直对齐时的上下边距。仅在「顶部对齐 / 底部对齐」时生效。正数把窗口往外推；负数让窗口往里推（可盖到任务栏上、贴齐物理屏幕底）。「自定义/居中」不使用。"))
        cf.addRow(_tr("屏幕水平对齐"), self.core_halign_combo)
        cf.addRow(_tr("屏幕垂直对齐"), self.core_valign_combo)
        cf.addRow(_tr("水平边距(可负)"), self.core_hmargin_spn)
        cf.addRow(_tr("垂直边距(可负)"), self.core_vmargin_spn)
        # V2244：对齐/边距/缩放变动 → 上方 X/Y 联动同步 + 非 custom 轴禁用手改
        self._wire_anchor_sync(self.core_halign_combo, self.core_valign_combo, self.core_hmargin_spn, self.core_vmargin_spn, self.core_x_spn, self.core_y_spn, "core")
        f.addRow(card)
        # ============ 顶级标签 3: 翻滚模块 ============
        r_sub = make_top_tab(_tr("翻滚模块"))
        f = make_sub_tab(r_sub, _tr("翻滚图标"))
        card, cf = make_card(f, _tr("── 翻滚图标 ──"))
        self.icon_use_default = QCheckBox(_tr("使用内置默认图标"))
        self.icon_use_default.setChecked(bool(self.settings.get("use_default_dodge_icon", DEFAULT_SETTINGS["use_default_dodge_icon"])))
        cf.addRow(_tr("默认图标:"), self.icon_use_default)
        icon_row = QHBoxLayout(); icon_row.setContentsMargins(0, 0, 0, 0); icon_row.setSpacing(8)
        self.icon_path = QLineEdit(self.settings.get("shrimp_img_path", DEFAULT_SETTINGS["shrimp_img_path"]))
        self.browse_icon_btn = QPushButton(_tr("浏览...")); self.browse_icon_btn.setAutoDefault(False); self.browse_icon_btn.setDefault(False); self.browse_icon_btn.setFixedWidth(80)
        self.browse_icon_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_path); icon_row.addWidget(self.browse_icon_btn)
        icon_container = QWidget(); icon_container.setLayout(icon_row); cf.addRow(_tr("翻滚图标绝对路径:"), icon_container)
        self._sync_icon_default_enabled()
        self.icon_scale = QSpinBox(); self.icon_scale.setRange(10, 400); self.icon_scale.setSuffix("%"); self.icon_scale.setValue(int(self.settings.get("dodge_icon_scale_percent", DEFAULT_SETTINGS["dodge_icon_scale_percent"])))
        cf.addRow(_tr("翻滚图标缩放:"), self.icon_scale)
        self.roll_icon_opacity_spin = QSpinBox(); self.roll_icon_opacity_spin.setRange(0, 100); self.roll_icon_opacity_spin.setSuffix("%"); self.roll_icon_opacity_spin.setValue(int(self.settings.get("roll_icon_opacity", DEFAULT_SETTINGS["roll_icon_opacity"])))
        cf.addRow(_tr("翻滚图标不透明度:"), self.roll_icon_opacity_spin)
        self.roll_orientation_combo = QComboBox(); self.roll_orientation_combo.addItem(_tr("横放"), "horizontal"); self.roll_orientation_combo.addItem(_tr("竖放"), "vertical")
        roidx = self.roll_orientation_combo.findData(self.settings.get("roll_orientation", DEFAULT_SETTINGS["roll_orientation"])); self.roll_orientation_combo.setCurrentIndex(max(0, roidx))
        cf.addRow(_tr("翻滚朝向:"), self.roll_orientation_combo)
        f.addRow(card)
        # ── 翻滚警告牌（V273 五项可调）──
        card, cf = make_card(f, _tr("── 翻滚警告牌（第6/7次）──"))
        # V2313：第 6/7 次样式二选一 —— 警告三角形 / 图片
        self.warning_mode_combo = QComboBox()
        self.warning_mode_combo.addItem(_tr("警告三角形"), "triangle")
        self.warning_mode_combo.addItem(_tr("图片"), "image")
        _wmidx = self.warning_mode_combo.findData(self.settings.get("dodge_warning_mode", DEFAULT_SETTINGS["dodge_warning_mode"]))
        self.warning_mode_combo.setCurrentIndex(max(0, _wmidx))
        self.warning_mode_combo.setToolTip(_tr("第 6/7 次翻滚显示成什么。「警告三角形」= 程序绘制的红边黄底三角（可改尺寸、边宽、圆角、配色）；「图片」= 用一张 PNG 代替，可选内置默认警告图或自己指定图片。闪光对任意 PNG 都自动生效。"))
        cf.addRow(_tr("第6/7次样式:"), self.warning_mode_combo)
        self.warning_size_sld, self.warning_size_spn, _ = _mb_slider(cf, _tr("警告牌相对尺寸:"), "warning_size_scale", int(DEFAULT_SETTINGS["warning_size_scale"] * 100), 30, 100, "%", value_scale=100)
        self.warning_bw_sld, self.warning_bw_spn, _ = _mb_slider(cf, _tr("红边宽度占比:"), "warning_outline_width", int(DEFAULT_SETTINGS["warning_outline_width"] * 100), 10, 50, "%", value_scale=100)
        self.warning_corner_spn = QSpinBox(); self.warning_corner_spn.setRange(0, 30); self.warning_corner_spn.setSuffix(" px"); self.warning_corner_spn.setValue(int(self.settings.get("warning_corner_radius", DEFAULT_SETTINGS["warning_corner_radius"])))
        cf.addRow(_tr("圆角半径:"), self.warning_corner_spn)
        self._add_color_row(cf, "warning_outline_color", _tr("红边色:"), with_opacity=False)
        self._add_color_row(cf, "warning_fill_color", _tr("黄色面:"), with_opacity=False)
        # V2313：图片模式专属控件（内置默认警告图 / 自定义路径 / 缩放）
        self.warning_img_use_default = QCheckBox(_tr("使用内置默认警告图"))
        self.warning_img_use_default.setChecked(bool(self.settings.get("use_default_dodge_warning_icon", DEFAULT_SETTINGS["use_default_dodge_warning_icon"])))
        self.warning_img_use_default.setToolTip(_tr("勾选=用软件内置的警告图；不勾=用下方自己选的图片。"))
        cf.addRow(_tr("默认警告图:"), self.warning_img_use_default)
        _wimg_row = QHBoxLayout(); _wimg_row.setContentsMargins(0, 0, 0, 0); _wimg_row.setSpacing(8)
        self.warning_img_path = QLineEdit(self.settings.get("dodge_warning_image_path", DEFAULT_SETTINGS["dodge_warning_image_path"]))
        self.browse_warning_icon_btn = QPushButton(_tr("浏览...")); self.browse_warning_icon_btn.setAutoDefault(False); self.browse_warning_icon_btn.setDefault(False); self.browse_warning_icon_btn.setFixedWidth(80)
        self.browse_warning_icon_btn.clicked.connect(self._browse_warning_icon)
        _wimg_row.addWidget(self.warning_img_path); _wimg_row.addWidget(self.browse_warning_icon_btn)
        _wimg_container = QWidget(); _wimg_container.setLayout(_wimg_row)
        cf.addRow(_tr("警告图绝对路径:"), _wimg_container)
        self.warning_img_scale = QSpinBox(); self.warning_img_scale.setRange(10, 400); self.warning_img_scale.setSuffix("%"); self.warning_img_scale.setValue(int(self.settings.get("dodge_warning_icon_scale_percent", DEFAULT_SETTINGS["dodge_warning_icon_scale_percent"])))
        self.warning_img_scale.setToolTip(_tr("警告图相对翻滚图标尺寸的百分比。100% = 和第 1~5 次的翻滚图标一样大。"))
        cf.addRow(_tr("警告图缩放:"), self.warning_img_scale)
        self._sync_warning_mode_ui()
        f.addRow(card)
        # 翻滚模块位置与缩放（从原“模块位置”顶级标签迁入）
        f = make_sub_tab(r_sub, _tr("位置与缩放"))
        card, cf = make_card(f, _tr("── 翻滚模块位置与缩放 ──"))
        self.roll_x_spn, self.roll_y_spn = _mk_pos_row(cf, "roll_window_x", "roll_window_y")
        self.roll_scale_slider, self.roll_scale_spin = _mk_scale_row(cf, "roll", _tr("模块缩放:"))
        # V2229：整屏对齐（翻滚模块）
        self.roll_halign_combo = QComboBox()
        self.roll_halign_combo.addItem(_tr("自定义"), "custom")
        self.roll_halign_combo.addItem(_tr("靠左"), "left")
        self.roll_halign_combo.addItem(_tr("居中"), "center")
        self.roll_halign_combo.addItem(_tr("靠右"), "right")
        _cur_ha = str(self.settings.get("roll_halign", DEFAULT_SETTINGS["roll_halign"]))
        _idx_ha = self.roll_halign_combo.findData(_cur_ha)
        if _idx_ha < 0: _idx_ha = 0
        self.roll_halign_combo.setCurrentIndex(_idx_ha)
        self.roll_halign_combo.setToolTip(_tr("整屏水平对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「靠左」贴屏幕左缘；「居中」水平居中；「靠右」贴屏幕右缘。每次刷新窗口（缩放/分辨率变化/行数变化）都会重算，始终贴边或居中。"))
        self.roll_valign_combo = QComboBox()
        self.roll_valign_combo.addItem(_tr("自定义"), "custom")
        self.roll_valign_combo.addItem(_tr("顶部对齐"), "top")
        self.roll_valign_combo.addItem(_tr("居中"), "center")
        self.roll_valign_combo.addItem(_tr("底部对齐"), "bottom")
        _cur_va = str(self.settings.get("roll_valign", DEFAULT_SETTINGS["roll_valign"]))
        _idx_va = self.roll_valign_combo.findData(_cur_va)
        if _idx_va < 0: _idx_va = 0
        self.roll_valign_combo.setCurrentIndex(_idx_va)
        self.roll_valign_combo.setToolTip(_tr("整屏垂直对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「顶部对齐」贴屏幕上缘；「居中」垂直居中；「底部对齐」贴屏幕下缘（已排除任务栏）。每次刷新窗口都会重算。"))
        self.roll_hmargin_spn = QSpinBox(); self.roll_hmargin_spn.setRange(-2000, 2000); self.roll_hmargin_spn.setSuffix(" px"); self.roll_hmargin_spn.setValue(int(self.settings.get("roll_hmargin", DEFAULT_SETTINGS["roll_hmargin"])))
        self.roll_hmargin_spn.setToolTip(_tr("水平对齐时的左右边距。仅在「靠左 / 靠右」时生效。正数把窗口往外推；负数让窗口往里推（可溢出屏幕外）。「自定义/居中」不使用。"))
        self.roll_vmargin_spn = QSpinBox(); self.roll_vmargin_spn.setRange(-2000, 2000); self.roll_vmargin_spn.setSuffix(" px"); self.roll_vmargin_spn.setValue(int(self.settings.get("roll_vmargin", DEFAULT_SETTINGS["roll_vmargin"])))
        self.roll_vmargin_spn.setToolTip(_tr("垂直对齐时的上下边距。仅在「顶部对齐 / 底部对齐」时生效。正数把窗口往外推；负数让窗口往里推（可盖到任务栏上、贴齐物理屏幕底）。「自定义/居中」不使用。"))
        cf.addRow(_tr("屏幕水平对齐"), self.roll_halign_combo)
        cf.addRow(_tr("屏幕垂直对齐"), self.roll_valign_combo)
        cf.addRow(_tr("水平边距(可负)"), self.roll_hmargin_spn)
        cf.addRow(_tr("垂直边距(可负)"), self.roll_vmargin_spn)
        # V2244：对齐/边距/缩放变动 → 上方 X/Y 联动同步 + 非 custom 轴禁用手改
        self._wire_anchor_sync(self.roll_halign_combo, self.roll_valign_combo, self.roll_hmargin_spn, self.roll_vmargin_spn, self.roll_x_spn, self.roll_y_spn, "roll")
        f.addRow(card)
        # ============ 顶级标签 4: 能力模块 ============
        s_sub = make_top_tab(_tr("能力模块"))
        f = make_sub_tab(s_sub, _tr("能力冷却"))
        card, cf = make_card(f, _tr("── 能力冷却 ──"))
        self.skill_cd_size_spn = QSpinBox(); self.skill_cd_size_spn.setRange(10, 80); self.skill_cd_size_spn.setValue(int(self.settings.get("skill_cd_size", 18)))
        cf.addRow(_tr("方形大小:"), self.skill_cd_size_spn)
        self.skill_cd_spread_spn = QSpinBox(); self.skill_cd_spread_spn.setRange(-200, 200); self.skill_cd_spread_spn.setValue(int(self.settings.get("skill_cd_spread", 70)))
        cf.addRow(_tr("聚散距离:"), self.skill_cd_spread_spn)
        self.skill_cd_font_size_spn = QSpinBox(); self.skill_cd_font_size_spn.setRange(6, 40); self.skill_cd_font_size_spn.setValue(int(self.settings.get("skill_cd_font_size", 12)))
        cf.addRow(_tr("倒计时字号:"), self.skill_cd_font_size_spn)
        self.skill_cd_capsule_w_spn = QSpinBox(); self.skill_cd_capsule_w_spn.setRange(-60, 60); self.skill_cd_capsule_w_spn.setValue(int(self.settings.get("skill_cd_capsule_width", 0))); self.skill_cd_capsule_w_spn.setSpecialValueText(_tr("不微调"))
        cf.addRow(_tr("胶囊宽度微调(Δ):"), self.skill_cd_capsule_w_spn)
        self.skill_cd_timer_offx_spn = QSpinBox(); self.skill_cd_timer_offx_spn.setRange(-100, 100); self.skill_cd_timer_offx_spn.setValue(int(self.settings.get("skill_cd_timer_offset_x", 0)))
        cf.addRow(_tr("倒计时X偏移:"), self.skill_cd_timer_offx_spn)
        self.skill_cd_timer_offy_spn = QSpinBox(); self.skill_cd_timer_offy_spn.setRange(-100, 100); self.skill_cd_timer_offy_spn.setValue(int(self.settings.get("skill_cd_timer_offset_y", 0)))
        cf.addRow(_tr("倒计时Y偏移:"), self.skill_cd_timer_offy_spn)
        self.skill_cd_bg_opacity_sl = _mk_opacity_row(cf, "skill_cd_bg_opacity", _tr("背景不透明度:"))
        self.skill_cd_sector_opacity_sl = _mk_opacity_row(cf, "skill_cd_sector_opacity", _tr("扇形不透明度:"))
        self.skill_cd_border_opacity_sl = _mk_opacity_row(cf, "skill_cd_border_opacity", _tr("边框不透明度:"))
        self.skill_cd_border_scale_dspn = QDoubleSpinBox(); self.skill_cd_border_scale_dspn.setRange(0.5, 4.0); self.skill_cd_border_scale_dspn.setSingleStep(0.05); self.skill_cd_border_scale_dspn.setDecimals(2); self.skill_cd_border_scale_dspn.setSuffix("×"); self.skill_cd_border_scale_dspn.setValue(float(self.settings.get("skill_cd_border_scale", 1.35)))
        cf.addRow(_tr("边框粗细倍数:"), self.skill_cd_border_scale_dspn)
        self.skill_cd_capsule_opacity_sl = _mk_opacity_row(cf, "skill_cd_capsule_opacity", _tr("胶囊不透明度:"))
        # 胶囊背景色 / 边框色：复用上方「胶囊不透明度」滑块统一控制透明度（持久化写入 JSON）
        self._add_color_row(cf, "skill_cd_capsule_bg", _tr("胶囊背景色:"), with_opacity=False)
        self._add_color_row(cf, "skill_cd_capsule_border", _tr("胶囊边框色:"), with_opacity=False)
        self._add_color_row(cf, "skill_cd_color", _tr("扇形颜色:"), with_opacity=True)
        self._add_color_row(cf, "skill_cd_text_color", _tr("倒计时文字色:"), with_opacity=True)
        f.addRow(card)
        # 就绪呼吸光（冷却完毕提示）
        f = make_sub_tab(s_sub, _tr("就绪呼吸光"))
        card, cf = make_card(f, _tr("── 就绪呼吸光（冷却完毕提示）──"))
        self.skill_cd_breath_chk = QCheckBox(_tr("启用就绪呼吸光"))
        self.skill_cd_breath_chk.setChecked(bool(self.settings.get("skill_cd_breath_enabled", True)))
        cf.addRow(self.skill_cd_breath_chk)
        self._add_color_row(cf, "skill_cd_breath_color", _tr("呼吸光颜色:"), with_opacity=True)
        self.skill_cd_breath_freq_dspn = QDoubleSpinBox(); self.skill_cd_breath_freq_dspn.setRange(0.05, 3.0); self.skill_cd_breath_freq_dspn.setSingleStep(0.05); self.skill_cd_breath_freq_dspn.setDecimals(2); self.skill_cd_breath_freq_dspn.setSuffix("Hz"); self.skill_cd_breath_freq_dspn.setValue(float(self.settings.get("skill_cd_breath_freq", 0.5)))
        cf.addRow(_tr("呼吸频率:"), self.skill_cd_breath_freq_dspn)
        self.skill_cd_breath_soft_dspn = QDoubleSpinBox(); self.skill_cd_breath_soft_dspn.setRange(0.0, 3.0); self.skill_cd_breath_soft_dspn.setSingleStep(0.1); self.skill_cd_breath_soft_dspn.setDecimals(2); self.skill_cd_breath_soft_dspn.setValue(float(self.settings.get("skill_cd_breath_soft", 1.0)))
        cf.addRow(_tr("柔和程度:"), self.skill_cd_breath_soft_dspn)
        self.skill_cd_breath_scale_dspn = QDoubleSpinBox(); self.skill_cd_breath_scale_dspn.setRange(0.5, 3.0); self.skill_cd_breath_scale_dspn.setSingleStep(0.1); self.skill_cd_breath_scale_dspn.setDecimals(2); self.skill_cd_breath_scale_dspn.setValue(float(self.settings.get("skill_cd_breath_scale", 1.0)))
        cf.addRow(_tr("放大倍数:"), self.skill_cd_breath_scale_dspn)
        cf.addRow(QWidget())  # 占位，避免界面留白突兀
        f.addRow(card)
        # 技能名称
        f = make_sub_tab(s_sub, _tr("能力名称"))
        card, cf = make_card(f, _tr("── 能力名称 ──"))
        self.skill_cd_name_chk = QCheckBox(_tr("显示能力名称"))
        self.skill_cd_name_chk.setChecked(bool(self.settings.get("skill_cd_show_name", True)))
        cf.addRow(self.skill_cd_name_chk)
        self.skill_cd_name_font_spn = QSpinBox(); self.skill_cd_name_font_spn.setRange(1, 48); self.skill_cd_name_font_spn.setValue(int(self.settings.get("skill_cd_name_font_size", 7)))
        cf.addRow(_tr("字号:"), self.skill_cd_name_font_spn)
        self.skill_cd_name_offx_spn = QSpinBox(); self.skill_cd_name_offx_spn.setRange(-200, 200); self.skill_cd_name_offx_spn.setValue(int(self.settings.get("skill_cd_name_offset_x", 0)))
        cf.addRow(_tr("能力名X偏移:"), self.skill_cd_name_offx_spn)
        self.skill_cd_name_offy_spn = QSpinBox(); self.skill_cd_name_offy_spn.setRange(-200, 200); self.skill_cd_name_offy_spn.setValue(int(self.settings.get("skill_cd_name_offset_y", 0)))
        cf.addRow(_tr("能力名Y偏移:"), self.skill_cd_name_offy_spn)
        self.skill_cd_name_bgw_spn = QSpinBox(); self.skill_cd_name_bgw_spn.setRange(-100, 100); self.skill_cd_name_bgw_spn.setValue(int(self.settings.get("skill_cd_name_bg_width", 0)))
        cf.addRow(_tr("衬色块宽微调:"), self.skill_cd_name_bgw_spn)
        self._add_color_row(cf, "skill_cd_name_color", _tr("能力名色:"), with_opacity=True)
        f.addRow(card)
        # 能力模块位置与缩放（从原“模块位置”顶级标签迁入）
        f = make_sub_tab(s_sub, _tr("位置与缩放"))
        card, cf = make_card(f, _tr("── 能力模块位置与缩放 ──"))
        self.skill_x_spn, self.skill_y_spn = _mk_pos_row(cf, "skill_window_x", "skill_window_y")
        self.skill_scale_slider, self.skill_scale_spin = _mk_scale_row(cf, "skill", _tr("模块缩放:"))
        # V2229：整屏对齐（能力模块）
        self.skill_halign_combo = QComboBox()
        self.skill_halign_combo.addItem(_tr("自定义"), "custom")
        self.skill_halign_combo.addItem(_tr("靠左"), "left")
        self.skill_halign_combo.addItem(_tr("居中"), "center")
        self.skill_halign_combo.addItem(_tr("靠右"), "right")
        _cur_ha = str(self.settings.get("skill_halign", DEFAULT_SETTINGS["skill_halign"]))
        _idx_ha = self.skill_halign_combo.findData(_cur_ha)
        if _idx_ha < 0: _idx_ha = 0
        self.skill_halign_combo.setCurrentIndex(_idx_ha)
        self.skill_halign_combo.setToolTip(_tr("整屏水平对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「靠左」贴屏幕左缘；「居中」水平居中；「靠右」贴屏幕右缘。每次刷新窗口（缩放/分辨率变化/行数变化）都会重算，始终贴边或居中。"))
        self.skill_valign_combo = QComboBox()
        self.skill_valign_combo.addItem(_tr("自定义"), "custom")
        self.skill_valign_combo.addItem(_tr("顶部对齐"), "top")
        self.skill_valign_combo.addItem(_tr("居中"), "center")
        self.skill_valign_combo.addItem(_tr("底部对齐"), "bottom")
        _cur_va = str(self.settings.get("skill_valign", DEFAULT_SETTINGS["skill_valign"]))
        _idx_va = self.skill_valign_combo.findData(_cur_va)
        if _idx_va < 0: _idx_va = 0
        self.skill_valign_combo.setCurrentIndex(_idx_va)
        self.skill_valign_combo.setToolTip(_tr("整屏垂直对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「顶部对齐」贴屏幕上缘；「居中」垂直居中；「底部对齐」贴屏幕下缘（已排除任务栏）。每次刷新窗口都会重算。"))
        self.skill_hmargin_spn = QSpinBox(); self.skill_hmargin_spn.setRange(-2000, 2000); self.skill_hmargin_spn.setSuffix(" px"); self.skill_hmargin_spn.setValue(int(self.settings.get("skill_hmargin", DEFAULT_SETTINGS["skill_hmargin"])))
        self.skill_hmargin_spn.setToolTip(_tr("水平对齐时的左右边距。仅在「靠左 / 靠右」时生效。正数把窗口往外推；负数让窗口往里推（可溢出屏幕外）。「自定义/居中」不使用。"))
        self.skill_vmargin_spn = QSpinBox(); self.skill_vmargin_spn.setRange(-2000, 2000); self.skill_vmargin_spn.setSuffix(" px"); self.skill_vmargin_spn.setValue(int(self.settings.get("skill_vmargin", DEFAULT_SETTINGS["skill_vmargin"])))
        self.skill_vmargin_spn.setToolTip(_tr("垂直对齐时的上下边距。仅在「顶部对齐 / 底部对齐」时生效。正数把窗口往外推；负数让窗口往里推（可盖到任务栏上、贴齐物理屏幕底）。「自定义/居中」不使用。"))
        cf.addRow(_tr("屏幕水平对齐"), self.skill_halign_combo)
        cf.addRow(_tr("屏幕垂直对齐"), self.skill_valign_combo)
        cf.addRow(_tr("水平边距(可负)"), self.skill_hmargin_spn)
        cf.addRow(_tr("垂直边距(可负)"), self.skill_vmargin_spn)
        # V2244：对齐/边距/缩放变动 → 上方 X/Y 联动同步 + 非 custom 轴禁用手改
        self._wire_anchor_sync(self.skill_halign_combo, self.skill_valign_combo, self.skill_hmargin_spn, self.skill_vmargin_spn, self.skill_x_spn, self.skill_y_spn, "skill")
        f.addRow(card)

        # ============ 顶级标签 5: 主控的全Buff显示模块（第四模块）============
        a_sub = make_top_tab(_tr("主控的全Buff模块"))
        # 位置与缩放
        f = make_sub_tab(a_sub, _tr("位置与缩放"))
        card, cf = make_card(f, "── " + _tr("全Buff显示模块") + " ──")
        self.allbuff_x_spn, self.allbuff_y_spn = _mk_pos_row(cf, "allbuff_window_x", "allbuff_window_y")
        self.allbuff_scale_slider, self.allbuff_scale_spin = _mk_scale_row(cf, "allbuff", _tr("模块缩放:"))
        # V2228：整屏对齐（水平：自定义/靠左/居中/靠右；垂直：自定义/顶部对齐/居中/底部对齐）
        self.allbuff_halign_combo = QComboBox()
        self.allbuff_halign_combo.addItem(_tr("自定义"), "custom")
        self.allbuff_halign_combo.addItem(_tr("靠左"), "left")
        self.allbuff_halign_combo.addItem(_tr("居中"), "center")
        self.allbuff_halign_combo.addItem(_tr("靠右"), "right")
        _cur_ha = str(self.settings.get("allbuff_halign", DEFAULT_SETTINGS["allbuff_halign"]))
        _idx_ha = self.allbuff_halign_combo.findData(_cur_ha)
        if _idx_ha < 0:
            _idx_ha = 0
        self.allbuff_halign_combo.setCurrentIndex(_idx_ha)
        self.allbuff_halign_combo.setToolTip(_tr("整屏水平对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「靠左」贴屏幕左缘；「居中」水平居中；「靠右」贴屏幕右缘。每次刷新窗口（缩放/分辨率变化/行数变化）都会重算，始终贴边或居中。"))
        self.allbuff_valign_combo = QComboBox()
        self.allbuff_valign_combo.addItem(_tr("自定义"), "custom")
        self.allbuff_valign_combo.addItem(_tr("顶部对齐"), "top")
        self.allbuff_valign_combo.addItem(_tr("居中"), "center")
        self.allbuff_valign_combo.addItem(_tr("底部对齐"), "bottom")
        _cur_va = str(self.settings.get("allbuff_valign", DEFAULT_SETTINGS["allbuff_valign"]))
        _idx_va = self.allbuff_valign_combo.findData(_cur_va)
        if _idx_va < 0:
            _idx_va = 0
        self.allbuff_valign_combo.setCurrentIndex(_idx_va)
        self.allbuff_valign_combo.setToolTip(_tr("整屏垂直对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「顶部对齐」贴屏幕上缘；「居中」垂直居中；「底部对齐」贴屏幕下缘（已排除任务栏）。每次刷新窗口都会重算。"))
        cf.addRow(_tr("屏幕水平对齐"), self.allbuff_halign_combo)
        cf.addRow(_tr("屏幕垂直对齐"), self.allbuff_valign_combo)
        # V2229：水平/垂直边距（可负数）
        self.allbuff_hmargin_spn = QSpinBox(); self.allbuff_hmargin_spn.setRange(-2000, 2000); self.allbuff_hmargin_spn.setSuffix(" px"); self.allbuff_hmargin_spn.setValue(int(self.settings.get("allbuff_hmargin", DEFAULT_SETTINGS["allbuff_hmargin"])))
        self.allbuff_hmargin_spn.setToolTip(_tr("水平对齐时的左右边距。仅在「靠左 / 靠右」时生效。正数把窗口往外推；负数让窗口往里推（可溢出屏幕外）。「自定义/居中」不使用。"))
        self.allbuff_vmargin_spn = QSpinBox(); self.allbuff_vmargin_spn.setRange(-2000, 2000); self.allbuff_vmargin_spn.setSuffix(" px"); self.allbuff_vmargin_spn.setValue(int(self.settings.get("allbuff_vmargin", DEFAULT_SETTINGS["allbuff_vmargin"])))
        self.allbuff_vmargin_spn.setToolTip(_tr("垂直对齐时的上下边距。仅在「顶部对齐 / 底部对齐」时生效。正数把窗口往外推；负数让窗口往里推（可盖到任务栏上、贴齐物理屏幕底）。「自定义/居中」不使用。"))
        cf.addRow(_tr("水平边距(可负)"), self.allbuff_hmargin_spn)
        cf.addRow(_tr("垂直边距(可负)"), self.allbuff_vmargin_spn)
        # V2244：对齐/边距/缩放变动 → 上方 X/Y 联动同步 + 非 custom 轴禁用手改
        self._wire_anchor_sync(self.allbuff_halign_combo, self.allbuff_valign_combo, self.allbuff_hmargin_spn, self.allbuff_vmargin_spn, self.allbuff_x_spn, self.allbuff_y_spn, "allbuff")
        f.addRow(card)
        # 布局
        f = make_sub_tab(a_sub, _tr("布局"))
        card, cf = make_card(f, "── " + _tr("布局") + " ──")
        # V2104：恢复「显示行数」控件（之前 V2062 删除，行数改为自动延伸；现改回固定网格可调）
        self.allbuff_per_row_spn = QSpinBox(); self.allbuff_per_row_spn.setRange(1, 30); self.allbuff_per_row_spn.setValue(int(self.settings.get("allbuff_per_row", 10)))
        cf.addRow(_tr("每行数量"), self.allbuff_per_row_spn)
        self.allbuff_rows_spn = QSpinBox(); self.allbuff_rows_spn.setRange(1, 20); self.allbuff_rows_spn.setValue(int(self.settings.get("allbuff_rows", 3)))
        cf.addRow(_tr("显示行数"), self.allbuff_rows_spn)
        self.allbuff_row_spacing_spn = QSpinBox(); self.allbuff_row_spacing_spn.setRange(0, 100); self.allbuff_row_spacing_spn.setSuffix(" px"); self.allbuff_row_spacing_spn.setValue(int(self.settings.get("allbuff_row_spacing", 4)))
        cf.addRow(_tr("行间距"), self.allbuff_row_spacing_spn)
        self.allbuff_card_spacing_spn = QSpinBox(); self.allbuff_card_spacing_spn.setRange(0, 100); self.allbuff_card_spacing_spn.setSuffix(" px"); self.allbuff_card_spacing_spn.setValue(int(self.settings.get("allbuff_card_spacing", 4)))
        cf.addRow(_tr("卡片间距"), self.allbuff_card_spacing_spn)
        # V2063：排序方式
        self.allbuff_sort_mode_combo = QComboBox()
        self.allbuff_sort_mode_combo.addItem(_tr("按ID升序"), "id_asc")
        self.allbuff_sort_mode_combo.addItem(_tr("按出现时间"), "appearance")
        _cur_sort = self.settings.get("allbuff_sort_mode", DEFAULT_SETTINGS["allbuff_sort_mode"])
        _idx_sort = self.allbuff_sort_mode_combo.findData(_cur_sort)
        if _idx_sort < 0:
            _idx_sort = 0
        self.allbuff_sort_mode_combo.setCurrentIndex(_idx_sort)
        self.allbuff_sort_mode_combo.setToolTip(_tr("决定 buff 卡片的排列方式。「按ID」按编号数值升序（稳定）；「按出现时间」按首次进入列表的相对顺序，新出现的Buff 排在末尾；V2076 修复：消失-再出现的Buff **重新**分配排序号（先出的在最前，消失后清空它自己的排序号，回归时按当前最大号+1 重新算）。例：ABC 依次出现 → ABC；B 消失 → AC；B 重现 → ACB。"))
        # V2080：QSS sub-control 渲染 QComboBox::down-arrow 不可靠（V2077 utf8 SVG 不支持、V2078 base64 SVG 缺 QtSvg、
        # V2079 CSS border 退化成方块），改用 QHBoxLayout 套独立 QLabel ▼ 字符——QLabel 是普通 widget 100% 可靠。
        _sort_hbox = QHBoxLayout(); _sort_hbox.setContentsMargins(0, 0, 0, 0); _sort_hbox.setSpacing(0)
        _sort_hbox.addWidget(self.allbuff_sort_mode_combo, 1)
        _sort_arrow = QLabel("▼")
        _sort_arrow.setFixedWidth(22)
        _sort_arrow.setAlignment(Qt.AlignCenter)
        _sort_arrow.setStyleSheet("color:#dce8f8;background:#2a3450;border:1px solid #3a4860;border-left:none;border-top-right-radius:4px;border-bottom-right-radius:4px;font-size:10px;")
        _sort_hbox.addWidget(_sort_arrow)
        _sort_widget = QWidget(); _sort_widget.setLayout(_sort_hbox)
        # 把 combo 的边框去掉（QLabel 接管右侧视觉边框）
        self.allbuff_sort_mode_combo.setStyleSheet("QComboBox{border-top-right-radius:0px;border-bottom-right-radius:0px;}")
        cf.addRow(_tr("排序方式"), _sort_widget)
        # V2226：行内对齐（靠左 / 居中 / 靠右，默认靠左）
        self.allbuff_row_align_combo = QComboBox()
        self.allbuff_row_align_combo.addItem(_tr("靠左"), "left")
        self.allbuff_row_align_combo.addItem(_tr("居中"), "center")
        self.allbuff_row_align_combo.addItem(_tr("靠右"), "right")
        _cur_align = str(self.settings.get("allbuff_row_align", DEFAULT_SETTINGS["allbuff_row_align"]))
        _idx_align = self.allbuff_row_align_combo.findData(_cur_align)
        if _idx_align < 0:
            _idx_align = 0
        self.allbuff_row_align_combo.setCurrentIndex(_idx_align)
        self.allbuff_row_align_combo.setToolTip(_tr("决定每行 buff 卡片在该行内的水平对齐方式。「靠左」从行首开始排（默认，与旧版行为一致）；「居中」不足一行的卡片整体居中；「靠右」贴行尾排。满行时三者完全等价，只有最后一行（不足「每行数量」）才看得出差别。"))
        # 与「排序方式」同款外观：QComboBox + 独立 QLabel ▼
        # （QSS 的 QComboBox::down-arrow sub-control 不可靠，见 V2077~V2079）
        _align_hbox = QHBoxLayout(); _align_hbox.setContentsMargins(0, 0, 0, 0); _align_hbox.setSpacing(0)
        _align_hbox.addWidget(self.allbuff_row_align_combo, 1)
        _align_arrow = QLabel("▼")
        _align_arrow.setFixedWidth(22)
        _align_arrow.setAlignment(Qt.AlignCenter)
        _align_arrow.setStyleSheet("color:#dce8f8;background:#2a3450;border:1px solid #3a4860;border-left:none;border-top-right-radius:4px;border-bottom-right-radius:4px;font-size:10px;")
        _align_hbox.addWidget(_align_arrow)
        _align_widget = QWidget(); _align_widget.setLayout(_align_hbox)
        self.allbuff_row_align_combo.setStyleSheet("QComboBox{border-top-right-radius:0px;border-bottom-right-radius:0px;}")
        cf.addRow(_tr("行内对齐"), _align_widget)
        # V2093：「按出现时间」排序的消失宽限秒数——buff 读不到后等这么多秒才真清排序号，
        # 防内存读取抖动（一帧读不到）导致排序号被误清 → buff 重现时排到队尾 → 位置跳变。
        # 0 = 立即清除（V2092 及更早行为）。
        self.allbuff_seq_gone_grace_dspn = QDoubleSpinBox()
        self.allbuff_seq_gone_grace_dspn.setRange(0.0, 10.0)
        self.allbuff_seq_gone_grace_dspn.setSingleStep(0.1)
        self.allbuff_seq_gone_grace_dspn.setDecimals(1)
        self.allbuff_seq_gone_grace_dspn.setSuffix(" s")
        self.allbuff_seq_gone_grace_dspn.setValue(float(self.settings.get("allbuff_seq_gone_grace_sec", 1.0)))
        self.allbuff_seq_gone_grace_dspn.setToolTip(_tr("仅对「按出现时间」排序生效。Buff 从游戏数据里读不到后，等待这么多秒才真正清除它的排序号。0 = 立即清除；调大可防止读取抖动导致卡片位置跳变，但真消失的 Buff 要等更久才会重新排到队尾。"))
        cf.addRow(_tr("排序号消失宽限"), self.allbuff_seq_gone_grace_dspn)
        # V2060：单参通用——卡片内 名称↔层数↔时间↔进度条 之间的统一垂直间距
        # V2075：允许负值——负间距让行与行更紧凑（可重叠），用于压缩卡片高度
        self.allbuff_element_spacing_spn = QSpinBox(); self.allbuff_element_spacing_spn.setRange(-20, 30); self.allbuff_element_spacing_spn.setSuffix(" px"); self.allbuff_element_spacing_spn.setValue(int(self.settings.get("allbuff_element_spacing", 4)))
        cf.addRow(_tr("元素间距"), self.allbuff_element_spacing_spn)
        # V2074：行高加成——每行文字自己的高度，在实测 QFontMetrics.height() 基础上额外加 px
        # V2075：允许负值——负加成让行高比自动测量更紧（可能切字，玩家自行权衡）
        self.allbuff_row_height_extra_spn = QSpinBox(); self.allbuff_row_height_extra_spn.setRange(-10, 20); self.allbuff_row_height_extra_spn.setSuffix(" px"); self.allbuff_row_height_extra_spn.setValue(int(self.settings.get("allbuff_row_height_extra", 0)))
        self.allbuff_row_height_extra_spn.setToolTip(_tr("每行文字自己的高度加成。0=自动（按系统字体测量，保证不切字）；调大=每行字与卡片上下边留更多空隙。与「元素间距」不同——元素间距是行与行之间的空隙，行高加成是每行自己的高度。"))
        cf.addRow(_tr("行高加成"), self.allbuff_row_height_extra_spn)
        # V2060：进度条外框粗细（0=纯填充无外框；>0=画 4 边线作为 100% 上限标识）
        self.allbuff_bar_frame_thickness_spn = QSpinBox(); self.allbuff_bar_frame_thickness_spn.setRange(0, 10); self.allbuff_bar_frame_thickness_spn.setSuffix(" px"); self.allbuff_bar_frame_thickness_spn.setValue(int(self.settings.get("allbuff_bar_frame_thickness", 2)))
        cf.addRow(_tr("进度条边框粗细"), self.allbuff_bar_frame_thickness_spn)
        # V2217：进度条/衬底的「宽」「高」从「配色与文字」tab 移入此处（与其它布局相关参数同组便于联调）
        self.allbuff_bar_width_spn = QSpinBox(); self.allbuff_bar_width_spn.setRange(1, 400); self.allbuff_bar_width_spn.setSuffix(" px"); self.allbuff_bar_width_spn.setValue(int(self.settings.get("allbuff_bar_width", 60)))
        cf.addRow(_tr("进度条宽度"), self.allbuff_bar_width_spn)
        self.allbuff_bar_height_spn = QSpinBox(); self.allbuff_bar_height_spn.setRange(1, 100); self.allbuff_bar_height_spn.setSuffix(" px"); self.allbuff_bar_height_spn.setValue(int(self.settings.get("allbuff_bar_height", 5)))
        cf.addRow(_tr("进度条高度"), self.allbuff_bar_height_spn)
        self.allbuff_backing_width_spn = QSpinBox(); self.allbuff_backing_width_spn.setRange(1, 400); self.allbuff_backing_width_spn.setSuffix(" px"); self.allbuff_backing_width_spn.setValue(int(self.settings.get("allbuff_backing_width", 80)))
        self.allbuff_backing_width_spn.setToolTip(_tr("V2062：作为「自适应 floor」——按当前进度条宽度+外框计算的最小可视宽度之上再叠加。比最小值更小会被自动向上取。"))
        cf.addRow(_tr("衬底宽度"), self.allbuff_backing_width_spn)
        self.allbuff_backing_height_spn = QSpinBox(); self.allbuff_backing_height_spn.setRange(1, 100); self.allbuff_backing_height_spn.setSuffix(" px"); self.allbuff_backing_height_spn.setValue(int(self.settings.get("allbuff_backing_height", 64)))
        self.allbuff_backing_height_spn.setToolTip(_tr("V2062：作为「自适应 floor」——按当前字体+元素间距+进度条+外框计算的最小可视高度之上再叠加。比最小值更小会被自动向上取。"))
        cf.addRow(_tr("衬底高度"), self.allbuff_backing_height_spn)
        f.addRow(card)
        # V2116：「分类显示」——显示层面开关（核心/永续/专属/专精/单层）（门限在下方独立 tab）
        f = make_sub_tab(a_sub, _tr("分类显示"))
        card, cf = make_card(f, "── " + _tr("分类显示") + " ──")
        self.allbuff_exclude_core_chk = QCheckBox(_tr("不显示核心区已展示的"))
        self.allbuff_exclude_core_chk.setChecked(bool(self.settings.get("allbuff_exclude_core", False)))
        cf.addRow(self.allbuff_exclude_core_chk)
        self.allbuff_exclude_infinite_chk = QCheckBox(_tr("不显示永续的"))
        self.allbuff_exclude_infinite_chk.setChecked(bool(self.settings.get("allbuff_exclude_infinite", False)))
        cf.addRow(self.allbuff_exclude_infinite_chk)
        self.allbuff_exclude_exclusive_chk = QCheckBox(_tr("不显示角色专属的"))
        self.allbuff_exclude_exclusive_chk.setChecked(bool(self.settings.get("allbuff_exclude_exclusive", False)))
        cf.addRow(self.allbuff_exclude_exclusive_chk)
        self.allbuff_exclude_mastery_chk = QCheckBox(_tr("不显示专精专属"))
        self.allbuff_exclude_mastery_chk.setChecked(bool(self.settings.get("allbuff_exclude_mastery", False)))
        cf.addRow(self.allbuff_exclude_mastery_chk)
        self.allbuff_exclude_single_chk = QCheckBox(_tr("不显示单层"))
        self.allbuff_exclude_single_chk.setChecked(bool(self.settings.get("allbuff_exclude_single", False)))
        cf.addRow(self.allbuff_exclude_single_chk)
        f.addRow(card)
        # V2066 + V2236：「门限」——搬自 GBFR_BuffMonitor 的 monitor 风格数值废料过滤（全部可开关，实时生效）。
        # V2236 重构：上半部分列出全部「已固化的门限」（永远开启，灰色 disabled checkbox，仅供查阅），
        #              下半部分保留 V2066 风格的「可调数值门限」——每个 = 「启用勾选 + 数值」同行。
        f = make_sub_tab(a_sub, _tr("门限"))
        card, cf = make_card(f, "── " + _tr("门限 (实时生效)") + " ──")

        # V2236 + V2243：上半区工厂函数——「可勾选」的 checkbox 行 + 一行说明。
        # 注：定义在 sub_tab 局部作用域内仅供主控/全buff 门限使用；Boss 门限另有一组（结构对称）。
        # V2315：删掉零调用的 _gate_fixed_checkbox / _gate_fixed_double_row —— V2243 把 ①②③④
        #        全改成「可勾选」后，V2239 那套灰色 disabled 固化门限工厂就再也没人调用了。
        def _gate_toggle_row(label, tip, en_key, default_checked):
            """V2243：可勾选的纯 checkbox 行。default_checked=True 时默认启用。"""
            c = QCheckBox(label)
            c.setChecked(bool(self.settings.get(en_key, default_checked)))
            c.setStyleSheet(
                "QCheckBox{color:#cfe0ff;font-weight:bold;}"
                "QCheckBox::indicator{width:14px;height:14px;}"
            )
            c.setToolTip(tip)
            return c
        def _gate_toggle_double_row(label, tip, en_key, val_key, default_val, vmin, vmax):
            """V2243：可勾选 checkbox + 可调 DoubleSpinBox 同行。勾选=启用门限+实时同步 settings。"""
            r = QWidget(); rl = QHBoxLayout(r); rl.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(label)
            chk.setChecked(bool(self.settings.get(en_key, True)))
            chk.setStyleSheet(
                "QCheckBox{color:#cfe0ff;font-weight:bold;}"
                "QCheckBox::indicator{width:14px;height:14px;}"
            )
            chk.setToolTip(tip)
            spn = QDoubleSpinBox()
            spn.setDecimals(1); spn.setSingleStep(100.0); spn.setRange(vmin, vmax)
            spn.setValue(float(self.settings.get(val_key, default_val)))
            spn.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda _s, _c=chk, _w=spn: _w.setEnabled(_c.isChecked()))
            chk.setToolTip(tip)
            spn.setToolTip(tip)
            spn.setStyleSheet("QDoubleSpinBox{color:#c0d0e8;background:#22304a;}"
                              "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{width:14px;}")
            rl.addWidget(chk); rl.addStretch(1); rl.addWidget(spn)
            cf.addRow(r)
            return chk, spn
        def _gate_fixed_note(label, tip):
            lbl = QLabel(label)
            lbl.setStyleSheet("color:#8fb4ff;font-weight:bold;padding-top:4px;")
            lbl.setToolTip(tip)
            return lbl
        # ── V2243：上半区——4 条「可勾选」门限（默认开启；玩家可关）──
        # V2243 大改动：①/②/③/④ 从 V2239 的「灰色 disabled checkbox」（永远开启）
        #              改为「可勾选」——玩家可关闭任意一条（默认全部开启以保留原行为）。
        #  · ① NaN/Inf 检查 → settings key: allbuff_gate_check_nan_inf（V2117 留 key, 现改可关）
        #  · ② ID=0/ID=1 不可能是永续 → 新 key: allbuff_gate_filter_status_id_zero_one_infinite_enabled
        #  · ③ 剩余/初始时间 ≤ min_time 丢弃 → 新 keys: allbuff_gate_check_min_time_enabled + allbuff_gate_min_time
        #  · ④ 时长上限（含 9999 永续豁免）→ en key: allbuff_gate_enabled_duration_max + val key: allbuff_gate_duration_max_with_infinite_exemption
        cf.addRow(_gate_fixed_note(_tr("── 已固化的门限（永远开启，不可关闭）──"),
                                  _tr("以下 4 条门限默认全部开启，玩家可单独关闭任意一项以诊断行为或适应特殊场景。勾选=启用，取消勾选=跳过（③/④ 数值仍可调）。")))
        # ① NaN/Inf 检查
        self.allbuff_gate_nan_inf_chk = _gate_toggle_row(
            _tr("① NaN/Inf 检查"),
            _tr("任何 remaining / initial 为 NaN 或 ±Infinity 时丢弃。对运行时瞬态类型异常（极罕见）也有兜底——纯 Python != / == 比较不抛异常。"),
            "allbuff_gate_check_nan_inf", True)
        cf.addRow(self.allbuff_gate_nan_inf_chk)
        # ② ID=0/ID=1 不可能是永续
        self.allbuff_gate_filter_id01_chk = _gate_toggle_row(
            _tr("② ID=0/ID=1 不可能是永续"),
            _tr("status_id == 0（攻击UP）或 status_id == 1（防御UP）在游戏里不可能是永续 buff。sid=0/1 槽位残留的垃圾条目有时会把 infinite 标志位置 1，被此条过滤丢弃（默认开启）。玩家关闭后可能显示 0/1 槽位的伪永续条目，请谨慎。"),
            "allbuff_gate_filter_status_id_zero_one_infinite_enabled", True)
        cf.addRow(self.allbuff_gate_filter_id01_chk)
        # ③ 剩余/初始时间 ≤ min_time 丢弃（默认 0.0 秒 = 等价于原 ≤ 0 规则）
        self.allbuff_gate_min_time_chk, self.allbuff_gate_min_time_spn = _gate_toggle_double_row(
            _tr("③ 剩余/初始时间 ≤ X(秒)丢弃"),
            _tr("剩余（remaining）或初始（initial）时间 ≤ 此阈值（默认 0.0 秒，范围 0.0–999.0 秒）一律丢弃。阈值=0 等价于原 V2239 规则「≤ 0 丢弃」；调到 0.5 等价于把 < 0.5 秒的瞬时 buff 全部隐藏（与下方「最小剩余/初始时间」门限功能类似，但本项走 V2243 主路径）。例外：剩余 ≥9999 由 V2216「FLT_MAX 自动永续」豁免，视为永续 buff（显示 *∞）。"),
            "allbuff_gate_check_min_time_enabled",
            "allbuff_gate_min_time", 0.0, 0.0, 999.0)
        def _on_mintime_changed(_v, _k="allbuff_gate_min_time"):
            self.settings[_k] = float(_v)
        self.allbuff_gate_min_time_spn.valueChanged.connect(_on_mintime_changed)
        # ④ 时长上限（含 9999 永续豁免）
        self.allbuff_gate_dur_max_chk, self.allbuff_gate_dur_max_spn = _gate_toggle_double_row(
            _tr("④ 时长上限（含 9999 永续豁免）"),
            _tr("initial 或 remaining 大于此上限（默认 10000.0 秒）一律视为非游戏数据（脏值）丢弃。剩余 ≥9999 由 V2216「FLT_MAX 自动判定永续」豁免，视为永续 buff（显示 *∞）。玩家可在右侧调整上限数值，范围 10.0–600000.0 秒。取消勾选=不剔除任何时长上限异常值（可能显示非常离谱的长 buff 倒计时）。"),
            "allbuff_gate_enabled_duration_max",
            "allbuff_gate_duration_max_with_infinite_exemption", 10000.0, 10.0, 600000.0)
        def _on_dur_changed(_v, _k="allbuff_gate_duration_max_with_infinite_exemption"):
            self.settings[_k] = float(_v)
        self.allbuff_gate_dur_max_spn.valueChanged.connect(_on_dur_changed)
        # V2260 ⑤ 剩余时间 > 持续时间丢弃（纯布尔门限，无数值）
        self.allbuff_gate_rem_gt_init_chk = _gate_toggle_row(
            _tr("⑤ 剩余时间 > 持续时间丢弃"),
            _tr("正常情况下剩余时间（remaining）不可能大于持续时间（initial）——出现这种情况通常说明读到的是脏值或异常槽位数据，勾选后直接丢弃该条。永续 buff（显示 ∞ / *∞）不受此限：它的 initial 可能为 0 而 remaining 残留正数，属于正常现象，不会被误杀。默认开启。"),
            "allbuff_gate_rem_gt_init_drop", True)
        cf.addRow(self.allbuff_gate_rem_gt_init_chk)
        # 每个数值门限 = 「启用勾选」+「数值」同行：勾选=启用该项检查，取消勾选=跳过（数值灰显）。
        def _gate_int_row(en_key, key, label, val, vmin, vmax):
            r = QWidget(); rl = QHBoxLayout(r); rl.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(label); chk.setChecked(bool(self.settings.get(en_key, True)))
            spn = QSpinBox(); spn.setRange(vmin, vmax); spn.setValue(int(self.settings.get(key, val)))
            spn.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda _s, c=chk, w=spn: w.setEnabled(c.isChecked()))
            rl.addWidget(chk); rl.addStretch(1); rl.addWidget(spn)
            cf.addRow(r)
            return chk, spn
        def _gate_float_row(en_key, key, label, val, vmax):
            r = QWidget(); rl = QHBoxLayout(r); rl.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(label); chk.setChecked(bool(self.settings.get(en_key, True)))
            spn = QDoubleSpinBox(); spn.setRange(0.0, vmax); spn.setDecimals(2); spn.setSingleStep(0.05)
            spn.setValue(float(self.settings.get(key, val))); spn.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda _s, c=chk, w=spn: w.setEnabled(c.isChecked()))
            rl.addWidget(chk); rl.addStretch(1); rl.addWidget(spn)
            cf.addRow(r)
            return chk, spn

        # ── 基础 ID 门限 ──
        # V2216：曾去掉「过滤 status_id == 0」复选框；V2222 起 sid==0 永远显示（用户要求），
        # render 端不再硬剔除 sid==0。status_id/sub_id 上限恢复为下方可配置门限。
        # V2217：再删「status_id 上限」「sub_id 上限」两个数值门限的 UI 控件——
        # 这两项已固化为常闭 + 默认常量：`status_id > 0xFFFF / sub_id > 0xFFFF` 一律丢弃。游戏实际 sid/sub
        # 远小于 0xFFFF，玩家无任何可见影响。
        # ── 层数门限 ──
        self.gate_stacks_max_chk, self.gate_stacks_max_spn = _gate_int_row(
            "allbuff_gate_enabled_stacks_max", "allbuff_gate_stacks_max", _tr("当前层数上限 (超范围丢弃)"), 100, 0, 9999)
        self.gate_max_stacks_max_chk, self.gate_max_stacks_max_spn = _gate_int_row(
            "allbuff_gate_enabled_max_stacks_max", "allbuff_gate_max_stacks_max", _tr("上限层数上限 (超范围丢弃)"), 100, 0, 9999)
        # V2222：恢复 status_id / sub_id 上限门限 UI（V2217 曾删除并硬编码为 0xFFFF 常闭）。
        self.gate_status_id_max_chk, self.gate_status_id_max_spn = _gate_int_row(
            "allbuff_gate_enabled_status_id_max", "allbuff_gate_status_id_max", _tr("status_id 上限 (超范围丢弃)"), 0xFFFF, 0, 0xFFFF)
        self.gate_sub_id_max_chk, self.gate_sub_id_max_spn = _gate_int_row(
            "allbuff_gate_enabled_sub_id_max", "allbuff_gate_sub_id_max", _tr("sub_id 上限 (超范围丢弃)"), 0xFFFF, 0, 0xFFFF)
        # V2217：删「层数矛盾检查」QCheckBox——render 端恒执行 `if max_stacks>0 and cur_stacks > max_stacks: continue`
        # （max_stacks 来自 buff 自身数据，非 settings；max_stacks=0 视为「未定义」不动）。
        # ── 时长门限 ──
        # V2217：删「时长上限」_gate_float_row——render 端硬剔除 `if initial>10000 or remaining>10000`，
        # 仍保留 V2216 的 9999 永续豁免（≥9999 不丢，显示 *∞）。
        self.gate_min_remaining_chk, self.gate_min_remaining_spn = _gate_float_row(
            "allbuff_gate_enabled_min_remaining_time", "allbuff_gate_min_remaining_time", _tr("最小剩余时间 (秒, remaining 少于则丢)"), 0.05, 60.0)
        self.gate_min_initial_chk, self.gate_min_initial_spn = _gate_float_row(
            "allbuff_gate_enabled_min_initial_time", "allbuff_gate_min_initial_time", _tr("最小持续时间 (秒, initial 少于则丢)"), 0.05, 60.0)
        # V2084：最小出现持续时间门限——buff 首次被观测到后需持续 ≥N 秒才算有效
        self.gate_min_appearance_chk, self.gate_min_appearance_spn = _gate_float_row(
            "allbuff_gate_enabled_min_appearance_time", "allbuff_gate_min_appearance_time", _tr("最小出现持续时间 (秒, 首次观测后不足则丢)"), 0.1, 60.0)
        # V2117：NaN/Inf 检查、ID=0 排除永续、隐藏倒计时 0.0/0.0、remaining/initial 任一 < 0 四门限已固化（永远开启），UI 开关移除。
        # 下面是其它仍可调的数值门限（status_id 上限/sub_id 上限/层数上限/层数矛盾/时长上限/最小剩余/最小初始/最小出现持续时间）。
        f.addRow(card)
        # V2116：「名单」子标签页含两个 GroupBox —— 黑名单（在前） + 多次出现名单（在后）。
        # 两个 GroupBox 结构对称：描述 + 下拉 + 添加按钮 + 已添加列表；下拉菜单互斥（对方有则不列）+ 专属性过滤。
        f = make_sub_tab(a_sub, _tr("名单"))

        self._buff_groups = {
            "bl": self._add_buff_list_group(
                f, _tr("黑名单"),
                _tr("黑名单中的 buff 在全 Buff 模块中永不显示（用于屏蔽干扰视觉或毫无意义的 buff 残余，例如某些沉默帧残留的瞬时护盾）。从下方下拉菜单选择要屏蔽的 Buff（仅限全角色通用 buff；角色专属 buff 已自动排除，不必再加入黑名单）。"),
                "bl",
                _tr("（空）从上方下拉菜单选择 Buff 以永久屏蔽。"),
            ),
            "ml": self._add_buff_list_group(
                f, _tr("多次出现名单"),
                _tr("多次出现名单中的 buff 在全 Buff 模块中可显示多个实例（如帕西瓦尔双重追击）；其它 buff 默认只显示 1 个。从下方下拉菜单选择要放行的 Buff（仅限全角色通用 buff；角色专属 buff 已自动排除，无法多次出现）。注：黑名单中的 buff 不会出现在此处。"),
                "ml",
                _tr("（空）从上方下拉菜单选择 Buff 以放行多次出现。"),
            ),
        }
        self._refresh_buff_list("bl"); self._refresh_buff_combo("bl")
        self._refresh_buff_list("ml"); self._refresh_buff_combo("ml")
        # 配色与文字
        f = make_sub_tab(a_sub, _tr("配色与文字"))
        card, cf = make_card(f, "── " + _tr("配色与文字") + " ──")
        self.allbuff_name_font_size_spn = QSpinBox(); self.allbuff_name_font_size_spn.setRange(1, 48); self.allbuff_name_font_size_spn.setSuffix(" px"); self.allbuff_name_font_size_spn.setValue(int(self.settings.get("allbuff_name_font_size", 11)))
        cf.addRow(_tr("名称字号"), self.allbuff_name_font_size_spn)
        self._add_color_row(cf, "allbuff_name_color", _tr("名称颜色") + ":", with_opacity=False)
        self.allbuff_stacks_font_size_spn = QSpinBox(); self.allbuff_stacks_font_size_spn.setRange(1, 48); self.allbuff_stacks_font_size_spn.setSuffix(" px"); self.allbuff_stacks_font_size_spn.setValue(int(self.settings.get("allbuff_stacks_font_size", 10)))
        cf.addRow(_tr("层数字号"), self.allbuff_stacks_font_size_spn)
        self._add_color_row(cf, "allbuff_stacks_color", _tr("层数颜色") + ":", with_opacity=False)
        self.allbuff_time_font_size_spn = QSpinBox(); self.allbuff_time_font_size_spn.setRange(1, 48); self.allbuff_time_font_size_spn.setSuffix(" px"); self.allbuff_time_font_size_spn.setValue(int(self.settings.get("allbuff_time_font_size", 10)))
        cf.addRow(_tr("时间字号"), self.allbuff_time_font_size_spn)
        self._add_color_row(cf, "allbuff_time_color", _tr("时间颜色") + ":", with_opacity=False)
        # V2217：进度条/衬底的「宽」「高」已移至「布局」tab（与每行数量、显示行数等同组）
        #          此处仅保留「进度条颜色」与「衬底颜色」两行
        self._add_color_row(cf, "allbuff_bar_color", _tr("进度条颜色") + ":", with_opacity=True)
        self._add_color_row(cf, "allbuff_backing_color", _tr("衬底颜色") + ":", with_opacity=True)
        f.addRow(card)

        # V2064：画布级不透明背景填充（遮罩设置对话框等背景窗口的内容透出）
        card_cb, cf_cb = make_card(f, "── " + _tr("画布背景填充") + " ──")
        self.allbuff_canvas_bg_opacity_spn = QSpinBox()
        self.allbuff_canvas_bg_opacity_spn.setRange(0, 100)
        self.allbuff_canvas_bg_opacity_spn.setSuffix(" %")
        self.allbuff_canvas_bg_opacity_spn.setValue(int(self.settings.get("allbuff_canvas_bg_opacity", 0)))
        self.allbuff_canvas_bg_opacity_spn.setToolTip(_tr("V2065：在 buff 卡片下面整张画布填充一层半透明黑色，防止背景窗口（如设置对话框的文件路径标签）的内容透到 overlay 上来。0 = 纯透明（默认，沿用旧观感）；30~70 = 显著遮罩；100 = 全不透明黑底。"))
        cf_cb.addRow(_tr("画布背景不透明度"), self.allbuff_canvas_bg_opacity_spn)
        f.addRow(card_cb)

        # V2060 ── 倒计时尾声警告（buff） ──
        card_w, cf_w = make_card(f, "── " + _tr("倒计时尾声警告") + " ──")
        self.allbuff_warn_enabled_chk = QCheckBox(_tr("启用警告色"))
        self.allbuff_warn_enabled_chk.setChecked(bool(self.settings.get("allbuff_warn_enabled", False)))
        cf_w.addRow(self.allbuff_warn_enabled_chk)
        self.allbuff_warn_threshold_spn = QSpinBox(); self.allbuff_warn_threshold_spn.setRange(1, 99); self.allbuff_warn_threshold_spn.setSuffix(" %"); self.allbuff_warn_threshold_spn.setValue(int(self.settings.get("allbuff_warn_threshold_pct", 20)))
        cf_w.addRow(_tr("剩余百分比阈值"), self.allbuff_warn_threshold_spn)
        self._add_color_row(cf_w, "allbuff_warn_color", _tr("警告颜色") + ":", with_opacity=True)
        f.addRow(card_w)

        # V2060 ── Debuff 配色（编号 ≥ 1000） ──
        card_d, cf_d = make_card(f, "── " + _tr("Debuff 配色（编号 ≥ 1000）") + " ──")
        self._add_color_row(cf_d, "allbuff_debuff_name_color", _tr("Debuff 名称颜色") + ":", with_opacity=False)
        self._add_color_row(cf_d, "allbuff_debuff_stacks_color", _tr("Debuff 层数颜色") + ":", with_opacity=False)
        self._add_color_row(cf_d, "allbuff_debuff_time_color", _tr("Debuff 时间颜色") + ":", with_opacity=False)
        self._add_color_row(cf_d, "allbuff_debuff_bar_color", _tr("Debuff 进度条颜色") + ":", with_opacity=True)
        # Debuff 警告色
        self.allbuff_debuff_warn_enabled_chk = QCheckBox(_tr("Debuff 启用警告色"))
        self.allbuff_debuff_warn_enabled_chk.setChecked(bool(self.settings.get("allbuff_debuff_warn_enabled", True)))
        cf_d.addRow(self.allbuff_debuff_warn_enabled_chk)
        self._add_color_row(cf_d, "allbuff_debuff_warn_color", _tr("Debuff 警告色") + ":", with_opacity=True)
        # V2104：Debuff 不再单独分行（直接排在全部 Buff 之后），移除「Debuff 强制另起一行」开关。
        f.addRow(card_d)

        # ============ V2200：Boss Buff 模块（第五模块）============
        # 独立顶级 tab：只放它自己的「位置与缩放」。
        # 外观（配色 / 布局 / 门限 / 名单）沿用「主控的全Buff模块」的同一套设置，
        # 这样两个模块天然同款，也避免把 100+ 行外观设置复制一份。

        b_sub = make_top_tab(_tr("Boss Buff模块"))
        # 位置与缩放
        f = make_sub_tab(b_sub, _tr("位置与缩放"))
        card, cf = make_card(f, "── " + _tr("Boss Buff模块") + " ──")
        self.boss_x_spn, self.boss_y_spn = _mk_pos_row(cf, "boss_window_x", "boss_window_y")
        # V2209 BUGFIX：原传 "allbuff"，而 _mk_scale_row 内部会 setattr(self, f"{key}_scale_slider")，
        # 于是主控的 allbuff_scale_slider/spin 被 Boss 控件覆盖 → 两个模块缩放被同一控件绑定
        # （表现：主控缩放「消失」、Boss 缩放同时控制两个）。改回 "boss" 即各自独立。
        self.boss_scale_slider, self.boss_scale_spin = _mk_scale_row(cf, "boss", _tr("模块缩放:"))
        # V2228：整屏对齐（水平：自定义/靠左/居中/靠右；垂直：自定义/顶部对齐/居中/底部对齐）
        self.boss_halign_combo = QComboBox()
        self.boss_halign_combo.addItem(_tr("自定义"), "custom")
        self.boss_halign_combo.addItem(_tr("靠左"), "left")
        self.boss_halign_combo.addItem(_tr("居中"), "center")
        self.boss_halign_combo.addItem(_tr("靠右"), "right")
        _cur_ha = str(self.settings.get("boss_halign", DEFAULT_SETTINGS["boss_halign"]))
        _idx_ha = self.boss_halign_combo.findData(_cur_ha)
        if _idx_ha < 0:
            _idx_ha = 0
        self.boss_halign_combo.setCurrentIndex(_idx_ha)
        self.boss_halign_combo.setToolTip(_tr("整屏水平对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「靠左」贴屏幕左缘；「居中」水平居中；「靠右」贴屏幕右缘。每次刷新窗口（缩放/分辨率变化/行数变化）都会重算，始终贴边或居中。"))
        self.boss_valign_combo = QComboBox()
        self.boss_valign_combo.addItem(_tr("自定义"), "custom")
        self.boss_valign_combo.addItem(_tr("顶部对齐"), "top")
        self.boss_valign_combo.addItem(_tr("居中"), "center")
        self.boss_valign_combo.addItem(_tr("底部对齐"), "bottom")
        _cur_va = str(self.settings.get("boss_valign", DEFAULT_SETTINGS["boss_valign"]))
        _idx_va = self.boss_valign_combo.findData(_cur_va)
        if _idx_va < 0:
            _idx_va = 0
        self.boss_valign_combo.setCurrentIndex(_idx_va)
        self.boss_valign_combo.setToolTip(_tr("整屏垂直对齐方式。「自定义」= 沿用上方 X/Y 坐标自由定位（默认）；「顶部对齐」贴屏幕上缘；「居中」垂直居中；「底部对齐」贴屏幕下缘（已排除任务栏）。每次刷新窗口都会重算。"))
        cf.addRow(_tr("屏幕水平对齐"), self.boss_halign_combo)
        cf.addRow(_tr("屏幕垂直对齐"), self.boss_valign_combo)
        # V2229：水平/垂直边距（可负数）
        self.boss_hmargin_spn = QSpinBox(); self.boss_hmargin_spn.setRange(-2000, 2000); self.boss_hmargin_spn.setSuffix(" px"); self.boss_hmargin_spn.setValue(int(self.settings.get("boss_hmargin", DEFAULT_SETTINGS["boss_hmargin"])))
        self.boss_hmargin_spn.setToolTip(_tr("水平对齐时的左右边距。仅在「靠左 / 靠右」时生效。正数把窗口往外推；负数让窗口往里推（可溢出屏幕外）。「自定义/居中」不使用。"))
        self.boss_vmargin_spn = QSpinBox(); self.boss_vmargin_spn.setRange(-2000, 2000); self.boss_vmargin_spn.setSuffix(" px"); self.boss_vmargin_spn.setValue(int(self.settings.get("boss_vmargin", DEFAULT_SETTINGS["boss_vmargin"])))
        self.boss_vmargin_spn.setToolTip(_tr("垂直对齐时的上下边距。仅在「顶部对齐 / 底部对齐」时生效。正数把窗口往外推；负数让窗口往里推（可盖到任务栏上、贴齐物理屏幕底）。「自定义/居中」不使用。"))
        cf.addRow(_tr("水平边距(可负)"), self.boss_hmargin_spn)
        cf.addRow(_tr("垂直边距(可负)"), self.boss_vmargin_spn)
        # V2244：对齐/边距/缩放变动 → 上方 X/Y 联动同步 + 非 custom 轴禁用手改
        self._wire_anchor_sync(self.boss_halign_combo, self.boss_valign_combo, self.boss_hmargin_spn, self.boss_vmargin_spn, self.boss_x_spn, self.boss_y_spn, "boss")
        f.addRow(card)
        # 布局
        f = make_sub_tab(b_sub, _tr("布局"))
        card, cf = make_card(f, "── " + _tr("布局") + " ──")
        # V2104：恢复「显示行数」控件（之前 V2062 删除，行数改为自动延伸；现改回固定网格可调）
        self.boss_per_row_spn = QSpinBox(); self.boss_per_row_spn.setRange(1, 30); self.boss_per_row_spn.setValue(int(self.settings.get("boss_per_row", 10)))
        cf.addRow(_tr("每行数量"), self.boss_per_row_spn)
        self.boss_rows_spn = QSpinBox(); self.boss_rows_spn.setRange(1, 20); self.boss_rows_spn.setValue(int(self.settings.get("boss_rows", 3)))
        cf.addRow(_tr("显示行数"), self.boss_rows_spn)
        self.boss_row_spacing_spn = QSpinBox(); self.boss_row_spacing_spn.setRange(0, 100); self.boss_row_spacing_spn.setSuffix(" px"); self.boss_row_spacing_spn.setValue(int(self.settings.get("boss_row_spacing", 4)))
        cf.addRow(_tr("行间距"), self.boss_row_spacing_spn)
        self.boss_card_spacing_spn = QSpinBox(); self.boss_card_spacing_spn.setRange(0, 100); self.boss_card_spacing_spn.setSuffix(" px"); self.boss_card_spacing_spn.setValue(int(self.settings.get("boss_card_spacing", 4)))
        cf.addRow(_tr("卡片间距"), self.boss_card_spacing_spn)
        # V2063：排序方式
        self.boss_sort_mode_combo = QComboBox()
        self.boss_sort_mode_combo.addItem(_tr("按ID升序"), "id_asc")
        self.boss_sort_mode_combo.addItem(_tr("按出现时间"), "appearance")
        _cur_sort = self.settings.get("boss_sort_mode", DEFAULT_SETTINGS["boss_sort_mode"])
        _idx_sort = self.boss_sort_mode_combo.findData(_cur_sort)
        if _idx_sort < 0:
            _idx_sort = 0
        self.boss_sort_mode_combo.setCurrentIndex(_idx_sort)
        self.boss_sort_mode_combo.setToolTip(_tr("决定 buff 卡片的排列方式。「按ID」按编号数值升序（稳定）；「按出现时间」按首次进入列表的相对顺序，新出现的Buff 排在末尾；V2076 修复：消失-再出现的Buff **重新**分配排序号（先出的在最前，消失后清空它自己的排序号，回归时按当前最大号+1 重新算）。例：ABC 依次出现 → ABC；B 消失 → AC；B 重现 → ACB。"))
        # V2080：QSS sub-control 渲染 QComboBox::down-arrow 不可靠（V2077 utf8 SVG 不支持、V2078 base64 SVG 缺 QtSvg、
        # V2079 CSS border 退化成方块），改用 QHBoxLayout 套独立 QLabel ▼ 字符——QLabel 是普通 widget 100% 可靠。
        _sort_hbox = QHBoxLayout(); _sort_hbox.setContentsMargins(0, 0, 0, 0); _sort_hbox.setSpacing(0)
        _sort_hbox.addWidget(self.boss_sort_mode_combo, 1)
        _sort_arrow = QLabel("▼")
        _sort_arrow.setFixedWidth(22)
        _sort_arrow.setAlignment(Qt.AlignCenter)
        _sort_arrow.setStyleSheet("color:#dce8f8;background:#2a3450;border:1px solid #3a4860;border-left:none;border-top-right-radius:4px;border-bottom-right-radius:4px;font-size:10px;")
        _sort_hbox.addWidget(_sort_arrow)
        _sort_widget = QWidget(); _sort_widget.setLayout(_sort_hbox)
        # 把 combo 的边框去掉（QLabel 接管右侧视觉边框）
        self.boss_sort_mode_combo.setStyleSheet("QComboBox{border-top-right-radius:0px;border-bottom-right-radius:0px;}")
        cf.addRow(_tr("排序方式"), _sort_widget)
        # V2226：行内对齐（靠左 / 居中 / 靠右，默认靠左）
        self.boss_row_align_combo = QComboBox()
        self.boss_row_align_combo.addItem(_tr("靠左"), "left")
        self.boss_row_align_combo.addItem(_tr("居中"), "center")
        self.boss_row_align_combo.addItem(_tr("靠右"), "right")
        _cur_align = str(self.settings.get("boss_row_align", DEFAULT_SETTINGS["boss_row_align"]))
        _idx_align = self.boss_row_align_combo.findData(_cur_align)
        if _idx_align < 0:
            _idx_align = 0
        self.boss_row_align_combo.setCurrentIndex(_idx_align)
        self.boss_row_align_combo.setToolTip(_tr("决定每行 buff 卡片在该行内的水平对齐方式。「靠左」从行首开始排（默认，与旧版行为一致）；「居中」不足一行的卡片整体居中；「靠右」贴行尾排。满行时三者完全等价，只有最后一行（不足「每行数量」）才看得出差别。"))
        # 与「排序方式」同款外观：QComboBox + 独立 QLabel ▼
        # （QSS 的 QComboBox::down-arrow sub-control 不可靠，见 V2077~V2079）
        _align_hbox = QHBoxLayout(); _align_hbox.setContentsMargins(0, 0, 0, 0); _align_hbox.setSpacing(0)
        _align_hbox.addWidget(self.boss_row_align_combo, 1)
        _align_arrow = QLabel("▼")
        _align_arrow.setFixedWidth(22)
        _align_arrow.setAlignment(Qt.AlignCenter)
        _align_arrow.setStyleSheet("color:#dce8f8;background:#2a3450;border:1px solid #3a4860;border-left:none;border-top-right-radius:4px;border-bottom-right-radius:4px;font-size:10px;")
        _align_hbox.addWidget(_align_arrow)
        _align_widget = QWidget(); _align_widget.setLayout(_align_hbox)
        self.boss_row_align_combo.setStyleSheet("QComboBox{border-top-right-radius:0px;border-bottom-right-radius:0px;}")
        cf.addRow(_tr("行内对齐"), _align_widget)
        # V2093：「按出现时间」排序的消失宽限秒数——buff 读不到后等这么多秒才真清排序号，
        # 防内存读取抖动（一帧读不到）导致排序号被误清 → buff 重现时排到队尾 → 位置跳变。
        # 0 = 立即清除（V2092 及更早行为）。
        self.boss_seq_gone_grace_dspn = QDoubleSpinBox()
        self.boss_seq_gone_grace_dspn.setRange(0.0, 10.0)
        self.boss_seq_gone_grace_dspn.setSingleStep(0.1)
        self.boss_seq_gone_grace_dspn.setDecimals(1)
        self.boss_seq_gone_grace_dspn.setSuffix(" s")
        self.boss_seq_gone_grace_dspn.setValue(float(self.settings.get("boss_seq_gone_grace_sec", 1.0)))
        self.boss_seq_gone_grace_dspn.setToolTip(_tr("仅对「按出现时间」排序生效。Buff 从游戏数据里读不到后，等待这么多秒才真正清除它的排序号。0 = 立即清除；调大可防止读取抖动导致卡片位置跳变，但真消失的 Buff 要等更久才会重新排到队尾。"))
        cf.addRow(_tr("排序号消失宽限"), self.boss_seq_gone_grace_dspn)
        # V2060：单参通用——卡片内 名称↔层数↔时间↔进度条 之间的统一垂直间距
        # V2075：允许负值——负间距让行与行更紧凑（可重叠），用于压缩卡片高度
        self.boss_element_spacing_spn = QSpinBox(); self.boss_element_spacing_spn.setRange(-20, 30); self.boss_element_spacing_spn.setSuffix(" px"); self.boss_element_spacing_spn.setValue(int(self.settings.get("boss_element_spacing", 4)))
        cf.addRow(_tr("元素间距"), self.boss_element_spacing_spn)
        # V2074：行高加成——每行文字自己的高度，在实测 QFontMetrics.height() 基础上额外加 px
        # V2075：允许负值——负加成让行高比自动测量更紧（可能切字，玩家自行权衡）
        self.boss_row_height_extra_spn = QSpinBox(); self.boss_row_height_extra_spn.setRange(-10, 20); self.boss_row_height_extra_spn.setSuffix(" px"); self.boss_row_height_extra_spn.setValue(int(self.settings.get("boss_row_height_extra", 0)))
        self.boss_row_height_extra_spn.setToolTip(_tr("每行文字自己的高度加成。0=自动（按系统字体测量，保证不切字）；调大=每行字与卡片上下边留更多空隙。与「元素间距」不同——元素间距是行与行之间的空隙，行高加成是每行自己的高度。"))
        cf.addRow(_tr("行高加成"), self.boss_row_height_extra_spn)
        # V2060：进度条外框粗细（0=纯填充无外框；>0=画 4 边线作为 100% 上限标识）
        self.boss_bar_frame_thickness_spn = QSpinBox(); self.boss_bar_frame_thickness_spn.setRange(0, 10); self.boss_bar_frame_thickness_spn.setSuffix(" px"); self.boss_bar_frame_thickness_spn.setValue(int(self.settings.get("boss_bar_frame_thickness", 2)))
        cf.addRow(_tr("进度条边框粗细"), self.boss_bar_frame_thickness_spn)
        # V2217：进度条/衬底的「宽」「高」从「配色与文字」tab 移入此处（与其它布局相关参数同组便于联调）
        self.boss_bar_width_spn = QSpinBox(); self.boss_bar_width_spn.setRange(1, 400); self.boss_bar_width_spn.setSuffix(" px"); self.boss_bar_width_spn.setValue(int(self.settings.get("boss_bar_width", 60)))
        cf.addRow(_tr("进度条宽度"), self.boss_bar_width_spn)
        self.boss_bar_height_spn = QSpinBox(); self.boss_bar_height_spn.setRange(1, 100); self.boss_bar_height_spn.setSuffix(" px"); self.boss_bar_height_spn.setValue(int(self.settings.get("boss_bar_height", 5)))
        cf.addRow(_tr("进度条高度"), self.boss_bar_height_spn)
        self.boss_backing_width_spn = QSpinBox(); self.boss_backing_width_spn.setRange(1, 400); self.boss_backing_width_spn.setSuffix(" px"); self.boss_backing_width_spn.setValue(int(self.settings.get("boss_backing_width", 80)))
        self.boss_backing_width_spn.setToolTip(_tr("V2062：作为「自适应 floor」——按当前进度条宽度+外框计算的最小可视宽度之上再叠加。比最小值更小会被自动向上取。"))
        cf.addRow(_tr("衬底宽度"), self.boss_backing_width_spn)
        self.boss_backing_height_spn = QSpinBox(); self.boss_backing_height_spn.setRange(1, 100); self.boss_backing_height_spn.setSuffix(" px"); self.boss_backing_height_spn.setValue(int(self.settings.get("boss_backing_height", 64)))
        self.boss_backing_height_spn.setToolTip(_tr("V2062：作为「自适应 floor」——按当前字体+元素间距+进度条+外框计算的最小可视高度之上再叠加。比最小值更小会被自动向上取。"))
        cf.addRow(_tr("衬底高度"), self.boss_backing_height_spn)
        f.addRow(card)
        # V2210：原「排除开关」子标签已删（统一在「门限」里处理）；render 端 boss_exclude_* 检查保留以兼容旧 config。
        # V2066 + V2236：「门限」——搬自 GBFR_BuffMonitor 的 monitor 风格数值废料过滤（全部可开关，实时生效）。
        # V2236 重构（与主控对称）：上半部分列出 ①②③④ 四条门限，
        # V2243 起全部改为「可勾选」（默认开启，玩家可关）；下半部分保留 V2066 风格的「可调数值门限」。
        f = make_sub_tab(b_sub, _tr("门限"))
        card, cf = make_card(f, "── " + _tr("门限 (实时生效)") + " ──")

        # V2236 + V2243：上半区工厂函数——与主控完全对称（boss 版，定义在 sub_tab 局部作用域内）
        # V2315：删掉零调用的 _gate_fixed_checkbox / _gate_fixed_double_row（与主控同理）。
        def _gate_fixed_note(label, tip):
            lbl = QLabel(label)
            lbl.setStyleSheet("color:#8fb4ff;font-weight:bold;padding-top:4px;")
            lbl.setToolTip(tip)
            return lbl
        # V2243: 镜像主控——两个新工厂 _gate_toggle_row / _gate_toggle_double_row 提供「可勾选」版本。
        def _gate_toggle_row(label, tip, en_key, default_checked):
            c = QCheckBox(label)
            c.setChecked(bool(self.settings.get(en_key, default_checked)))
            c.setStyleSheet(
                "QCheckBox{color:#cfe0ff;font-weight:bold;}"
                "QCheckBox::indicator{width:14px;height:14px;}"
            )
            c.setToolTip(tip)
            return c
        def _gate_toggle_double_row(label, tip, en_key, val_key, default_val, vmin, vmax):
            r = QWidget(); rl = QHBoxLayout(r); rl.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(label)
            chk.setChecked(bool(self.settings.get(en_key, True)))
            chk.setStyleSheet(
                "QCheckBox{color:#cfe0ff;font-weight:bold;}"
                "QCheckBox::indicator{width:14px;height:14px;}"
            )
            chk.setToolTip(tip)
            spn = QDoubleSpinBox()
            spn.setDecimals(1); spn.setSingleStep(100.0); spn.setRange(vmin, vmax)
            spn.setValue(float(self.settings.get(val_key, default_val)))
            spn.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda _s, _c=chk, _w=spn: _w.setEnabled(_c.isChecked()))
            chk.setToolTip(tip)
            spn.setToolTip(tip)
            spn.setStyleSheet("QDoubleSpinBox{color:#c0d0e8;background:#22304a;}"
                              "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{width:14px;}")
            rl.addWidget(chk); rl.addStretch(1); rl.addWidget(spn)
            cf.addRow(r)
            return chk, spn
        # ── V2243：上半区——与主控对称的 4 条「可勾选」门限（默认开启；玩家可关）──
        cf.addRow(_gate_fixed_note(_tr("── 已固化的门限（永远开启，不可关闭）──"),
                                  _tr("以下 4 条门限默认全部开启，玩家可单独关闭任意一项。与主控全 buff 模块规则完全一致——但 key 用 boss_gate_ 前缀独立。")))
        # ① NaN/Inf 检查
        self.boss_gate_nan_inf_chk = _gate_toggle_row(
            _tr("① NaN/Inf 检查"),
            _tr("任何 remaining / initial 为 NaN 或 ±Infinity 时丢弃。与主控一致。"),
            "boss_gate_check_nan_inf", True)
        cf.addRow(self.boss_gate_nan_inf_chk)
        # ② ID=0/ID=1 不可能是永续
        self.boss_gate_filter_id01_chk = _gate_toggle_row(
            _tr("② ID=0/ID=1 不可能是永续"),
            _tr("status_id == 0（攻击UP）或 == 1（防御UP）在游戏里不可能是永续 buff（与主控一致）。"),
            "boss_gate_filter_status_id_zero_one_infinite_enabled", True)
        cf.addRow(self.boss_gate_filter_id01_chk)
        # ③ 剩余/初始时间 ≤ min_time 丢弃
        self.boss_gate_min_time_chk, self.boss_gate_min_time_spn = _gate_toggle_double_row(
            _tr("③ 剩余/初始时间 ≤ X(秒)丢弃"),
            _tr("剩余（remaining）或初始（initial）≤ 此阈值（默认 0.0 秒，范围 0.0–999.0 秒）一律丢弃。剩余 ≥9999 由 V2216 豁免为永续。"),
            "boss_gate_check_min_time_enabled",
            "boss_gate_min_time", 0.0, 0.0, 999.0)
        def _on_mintime_changed_b(_v, _k="boss_gate_min_time"):
            self.settings[_k] = float(_v)
        self.boss_gate_min_time_spn.valueChanged.connect(_on_mintime_changed_b)
        # ④ 时长上限（含 9999 永续豁免）
        self.boss_gate_dur_max_chk, self.boss_gate_dur_max_spn = _gate_toggle_double_row(
            _tr("④ 时长上限（含 9999 永续豁免）"),
            _tr("initial / remaining > 此上限（默认 10000.0 秒）一律丢弃。剩余 ≥9999 由 V2216 豁免为永续。"),
            "boss_gate_enabled_duration_max",
            "boss_gate_duration_max_with_infinite_exemption", 10000.0, 10.0, 600000.0)
        def _on_dur_changed_b(_v, _k="boss_gate_duration_max_with_infinite_exemption"):
            self.settings[_k] = float(_v)
        self.boss_gate_dur_max_spn.valueChanged.connect(_on_dur_changed_b)
        # V2260 ⑤ 剩余时间 > 持续时间丢弃（纯布尔门限，无数值）
        self.boss_gate_rem_gt_init_chk = _gate_toggle_row(
            _tr("⑤ 剩余时间 > 持续时间丢弃"),
            _tr("正常情况下剩余时间（remaining）不可能大于持续时间（initial）——出现这种情况通常说明读到的是脏值或异常槽位数据，勾选后直接丢弃该条。永续 buff（显示 ∞ / *∞）不受此限：它的 initial 可能为 0 而 remaining 残留正数，属于正常现象，不会被误杀。默认开启。"),
            "boss_gate_rem_gt_init_drop", True)
        cf.addRow(self.boss_gate_rem_gt_init_chk)
        # 每个数值门限 = 「启用勾选」+「数值」同行：勾选=启用该项检查，取消勾选=跳过（数值灰显）。
        def _gate_int_row(en_key, key, label, val, vmin, vmax):
            r = QWidget(); rl = QHBoxLayout(r); rl.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(label); chk.setChecked(bool(self.settings.get(en_key, True)))
            spn = QSpinBox(); spn.setRange(vmin, vmax); spn.setValue(int(self.settings.get(key, val)))
            spn.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda _s, c=chk, w=spn: w.setEnabled(c.isChecked()))
            rl.addWidget(chk); rl.addStretch(1); rl.addWidget(spn)
            cf.addRow(r)
            return chk, spn
        def _gate_float_row(en_key, key, label, val, vmax):
            r = QWidget(); rl = QHBoxLayout(r); rl.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox(label); chk.setChecked(bool(self.settings.get(en_key, True)))
            spn = QDoubleSpinBox(); spn.setRange(0.0, vmax); spn.setDecimals(2); spn.setSingleStep(0.05)
            spn.setValue(float(self.settings.get(key, val))); spn.setEnabled(chk.isChecked())
            chk.stateChanged.connect(lambda _s, c=chk, w=spn: w.setEnabled(c.isChecked()))
            rl.addWidget(chk); rl.addStretch(1); rl.addWidget(spn)
            cf.addRow(r)
            return chk, spn

        # ── 基础 ID 门限 ──
        # V2216：曾去掉「过滤 status_id == 0」复选框；V2222 起 sid==0 永远显示（用户要求），
        # render 端不再硬剔除 sid==0。status_id/sub_id 上限恢复为下方可配置门限。
        # V2217：再删「status_id 上限」「sub_id 上限」两个数值门限的 UI 控件——
        # 这两项已固化为常闭 + 默认常量：`status_id > 0xFFFF / sub_id > 0xFFFF` 一律丢弃。
        # ── 层数门限 ──
        self.boss_gate_stacks_max_chk, self.boss_gate_stacks_max_spn = _gate_int_row(
            "boss_gate_enabled_stacks_max", "boss_gate_stacks_max", _tr("当前层数上限 (超范围丢弃)"), 100, 0, 9999)
        self.boss_gate_max_stacks_max_chk, self.boss_gate_max_stacks_max_spn = _gate_int_row(
            "boss_gate_enabled_max_stacks_max", "boss_gate_max_stacks_max", _tr("上限层数上限 (超范围丢弃)"), 100, 0, 9999)
        # V2222：恢复 status_id / sub_id 上限门限 UI（V2217 曾删除并硬编码为 0xFFFF 常闭）。
        self.boss_gate_status_id_max_chk, self.boss_gate_status_id_max_spn = _gate_int_row(
            "boss_gate_enabled_status_id_max", "boss_gate_status_id_max", _tr("status_id 上限 (超范围丢弃)"), 0xFFFF, 0, 0xFFFF)
        self.boss_gate_sub_id_max_chk, self.boss_gate_sub_id_max_spn = _gate_int_row(
            "boss_gate_enabled_sub_id_max", "boss_gate_sub_id_max", _tr("sub_id 上限 (超范围丢弃)"), 0xFFFF, 0, 0xFFFF)
        # V2217：删「层数矛盾检查」QCheckBox——render 端恒执行 `if max_stacks>0 and cur_stacks > max_stacks: continue`。
        # ── 时长门限 ──
        # V2217：删「时长上限」_gate_float_row——render 端硬剔除 `if initial>10000 or remaining>10000`。
        self.boss_gate_min_remaining_chk, self.boss_gate_min_remaining_spn = _gate_float_row(
            "boss_gate_enabled_min_remaining_time", "boss_gate_min_remaining_time", _tr("最小剩余时间 (秒, remaining 少于则丢)"), 0.05, 60.0)
        self.boss_gate_min_initial_chk, self.boss_gate_min_initial_spn = _gate_float_row(
            "boss_gate_enabled_min_initial_time", "boss_gate_min_initial_time", _tr("最小持续时间 (秒, initial 少于则丢)"), 0.05, 60.0)
        # V2084：最小出现持续时间门限——buff 首次被观测到后需持续 ≥N 秒才算有效
        self.boss_gate_min_appearance_chk, self.boss_gate_min_appearance_spn = _gate_float_row(
            "boss_gate_enabled_min_appearance_time", "boss_gate_min_appearance_time", _tr("最小出现持续时间 (秒, 首次观测后不足则丢)"), 0.1, 60.0)
        # V2117：NaN/Inf 检查、ID=0 排除永续、隐藏倒计时 0.0/0.0、remaining/initial 任一 < 0 四门限已固化（永远开启），UI 开关移除。
        # 下面是其它仍可调的数值门限（status_id 上限/sub_id 上限/层数上限/层数矛盾/时长上限/最小剩余/最小初始/最小出现持续时间）。
        f.addRow(card)
        # V2116：「名单」子标签页含两个 GroupBox —— 黑名单（在前） + 多次出现名单（在后）。
        # 两个 GroupBox 结构对称：描述 + 下拉 + 添加按钮 + 已添加列表；下拉菜单互斥（对方有则不列）+ 专属性过滤。
        f = make_sub_tab(b_sub, _tr("名单"))

        # V2206：boss 独立两套名单（which="boss_bl"/"boss_ml"），存到 self._buff_groups 与主控同字典
        if not hasattr(self, "_buff_groups"):
            self._buff_groups = {}
        self._buff_groups["boss_bl"] = self._add_buff_list_group(
            f, _tr("黑名单"),
            _tr("黑名单中的 buff 在 Boss Buff 模块中永不显示（避免在 boss 监控里出现没意义的 buff 残余）。从下方下拉菜单选择要屏蔽的 Buff（仅限通用 buff；boss 专属由模块自带过滤）。"),
            "boss_bl",
            _tr("（空）从上方下拉菜单选择 Buff 以永久屏蔽。"),
        )
        self._buff_groups["boss_ml"] = self._add_buff_list_group(
            f, _tr("多次出现名单"),
            _tr("多次出现名单中的 buff 在 Boss Buff 模块中可显示多个实例（boss 身上同 buff 多个源时各显示一次）。从下方下拉菜单选择要放行的 Buff（仅限通用 buff）。注：黑名单中的 buff 不会出现在此处。"),
            "boss_ml",
            _tr("（空）从上方下拉菜单选择 Buff 以放行多次出现。"),
        )
        self._refresh_buff_list("boss_bl"); self._refresh_buff_combo("boss_bl")
        self._refresh_buff_list("boss_ml"); self._refresh_buff_combo("boss_ml")
        # 配色与文字
        f = make_sub_tab(b_sub, _tr("配色与文字"))
        card, cf = make_card(f, "── " + _tr("配色与文字") + " ──")
        self.boss_name_font_size_spn = QSpinBox(); self.boss_name_font_size_spn.setRange(1, 48); self.boss_name_font_size_spn.setSuffix(" px"); self.boss_name_font_size_spn.setValue(int(self.settings.get("boss_name_font_size", 11)))
        cf.addRow(_tr("名称字号"), self.boss_name_font_size_spn)
        self._add_color_row(cf, "boss_name_color", _tr("名称颜色") + ":", with_opacity=False)
        self.boss_stacks_font_size_spn = QSpinBox(); self.boss_stacks_font_size_spn.setRange(1, 48); self.boss_stacks_font_size_spn.setSuffix(" px"); self.boss_stacks_font_size_spn.setValue(int(self.settings.get("boss_stacks_font_size", 10)))
        cf.addRow(_tr("层数字号"), self.boss_stacks_font_size_spn)
        self._add_color_row(cf, "boss_stacks_color", _tr("层数颜色") + ":", with_opacity=False)
        self.boss_time_font_size_spn = QSpinBox(); self.boss_time_font_size_spn.setRange(1, 48); self.boss_time_font_size_spn.setSuffix(" px"); self.boss_time_font_size_spn.setValue(int(self.settings.get("boss_time_font_size", 10)))
        cf.addRow(_tr("时间字号"), self.boss_time_font_size_spn)
        self._add_color_row(cf, "boss_time_color", _tr("时间颜色") + ":", with_opacity=False)
        # V2217：进度条/衬底的「宽」「高」已移至「布局」tab（与每行数量、显示行数等同组）
        #          此处仅保留「进度条颜色」与「衬底颜色」两行
        self._add_color_row(cf, "boss_bar_color", _tr("进度条颜色") + ":", with_opacity=True)
        self._add_color_row(cf, "boss_backing_color", _tr("衬底颜色") + ":", with_opacity=True)
        f.addRow(card)

        # V2064：画布级不透明背景填充（遮罩设置对话框等背景窗口的内容透出）
        card_cb, cf_cb = make_card(f, "── " + _tr("画布背景填充") + " ──")
        self.boss_canvas_bg_opacity_spn = QSpinBox()
        self.boss_canvas_bg_opacity_spn.setRange(0, 100)
        self.boss_canvas_bg_opacity_spn.setSuffix(" %")
        self.boss_canvas_bg_opacity_spn.setValue(int(self.settings.get("boss_canvas_bg_opacity", 0)))
        self.boss_canvas_bg_opacity_spn.setToolTip(_tr("V2065：在 buff 卡片下面整张画布填充一层半透明黑色，防止背景窗口（如设置对话框的文件路径标签）的内容透到 overlay 上来。0 = 纯透明（默认，沿用旧观感）；30~70 = 显著遮罩；100 = 全不透明黑底。"))
        cf_cb.addRow(_tr("画布背景不透明度"), self.boss_canvas_bg_opacity_spn)
        f.addRow(card_cb)

        # V2060 ── 倒计时尾声警告（buff） ──
        card_w, cf_w = make_card(f, "── " + _tr("倒计时尾声警告") + " ──")
        self.boss_warn_enabled_chk = QCheckBox(_tr("启用警告色"))
        self.boss_warn_enabled_chk.setChecked(bool(self.settings.get("boss_warn_enabled", False)))
        cf_w.addRow(self.boss_warn_enabled_chk)
        self.boss_warn_threshold_spn = QSpinBox(); self.boss_warn_threshold_spn.setRange(1, 99); self.boss_warn_threshold_spn.setSuffix(" %"); self.boss_warn_threshold_spn.setValue(int(self.settings.get("boss_warn_threshold_pct", 20)))
        cf_w.addRow(_tr("剩余百分比阈值"), self.boss_warn_threshold_spn)
        self._add_color_row(cf_w, "boss_warn_color", _tr("警告颜色") + ":", with_opacity=True)
        f.addRow(card_w)

        # V2060 ── Debuff 配色（编号 ≥ 1000） ──
        card_d, cf_d = make_card(f, "── " + _tr("Debuff 配色（编号 ≥ 1000）") + " ──")
        self._add_color_row(cf_d, "boss_debuff_name_color", _tr("Debuff 名称颜色") + ":", with_opacity=False)
        self._add_color_row(cf_d, "boss_debuff_stacks_color", _tr("Debuff 层数颜色") + ":", with_opacity=False)
        self._add_color_row(cf_d, "boss_debuff_time_color", _tr("Debuff 时间颜色") + ":", with_opacity=False)
        self._add_color_row(cf_d, "boss_debuff_bar_color", _tr("Debuff 进度条颜色") + ":", with_opacity=True)
        # Debuff 警告色
        self.boss_debuff_warn_enabled_chk = QCheckBox(_tr("Debuff 启用警告色"))
        self.boss_debuff_warn_enabled_chk.setChecked(bool(self.settings.get("boss_debuff_warn_enabled", True)))
        cf_d.addRow(self.boss_debuff_warn_enabled_chk)
        self._add_color_row(cf_d, "boss_debuff_warn_color", _tr("Debuff 警告色") + ":", with_opacity=True)
        # V2104：Debuff 不再单独分行（直接排在全部 Buff 之后），移除「Debuff 强制另起一行」开关。
        f.addRow(card_d)

        # ============ V2200：Boss Buff 模块（第五模块）============
        # 独立顶级 tab：只放它自己的「位置与缩放」。
        # 外观（配色 / 布局 / 门限 / 名单）沿用「主控的全Buff模块」的同一套设置，
        # 这样两个模块天然同款，也避免把 100+ 行外观设置复制一份。
        about_top = make_top_tab(_tr("关于/更新"))
        about_form = make_sub_tab(about_top, _tr("关于"))
        # 关于页内容少，避免单个 card 被纵向撑出大片空白
        about_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        card, cf = make_card(about_form, _tr("── 在线更新 ──"))
        cf.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.current_ver_label = QLabel(f"v{APP_VERSION}")
        self.current_ver_label.setStyleSheet("font-weight:bold; color:#9fd0ff;")
        cf.addRow(_tr("当前版本："), self.current_ver_label)
        self.update_status_label = QLabel("—")
        self.update_status_label.setStyleSheet("color:#aabbcc;")
        cf.addRow(_tr("状态："), self.update_status_label)
        btn_row = QWidget(); btn_lay = QHBoxLayout(btn_row); btn_lay.setContentsMargins(0, 0, 0, 0); btn_lay.setSpacing(6)
        self.check_update_btn = QPushButton(_tr("检查更新"))
        self.check_update_btn.clicked.connect(self._on_check_update_clicked)
        self.download_btn = QPushButton(_tr("前往下载"))
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.skip_btn = QPushButton(_tr("跳过此版本"))
        self.skip_btn.setEnabled(False)
        self.skip_btn.clicked.connect(self._on_skip_clicked)
        btn_lay.addWidget(self.check_update_btn); btn_lay.addWidget(self.download_btn); btn_lay.addWidget(self.skip_btn)
        cf.addRow(btn_row)
        self.auto_check_cb = QCheckBox(_tr("自动检查更新"))
        self.auto_check_cb.setChecked(bool(self.settings.get("auto_check_update", True)))
        cf.addRow(self.auto_check_cb)
        self.update_url_le = QLineEdit(self.settings.get("update_check_url", "") or "")
        self.update_url_le.setPlaceholderText("https://.../version.json")
        cf.addRow(_tr("更新检测版本地址："), self.update_url_le)
        # V304：下载地址（来自 version.json 的 download_url，可在检查更新后自动填入；也可手填）
        self.download_url_le = QLineEdit(self.settings.get("update_download_url", "") or "")
        self.download_url_le.setPlaceholderText(_tr("检查更新后自动填入，或手动填写 exe 下载直链"))
        cf.addRow(_tr("更新下载地址："), self.download_url_le)
        # V303：原"检测地址走 release CDN"长说明已被用户删除（V2030）——版本号输入框的 placeholder 已经足够提示。
        self.changelog_edit = QPlainTextEdit()
        self.changelog_edit.setReadOnly(True)
        self.changelog_edit.setMaximumHeight(120)
        self.changelog_edit.setStyleSheet("background:rgba(20,26,40,0.6); color:#cdd6e0; border-radius:6px;")
        cf.addRow(_tr("更新日志："), self.changelog_edit)
        about_form.addRow(card)
        # ============ V2084：内存地址与数据速查 ============
        # 静态表（偏移含义 + 2.0.4 实测值）+ 实时区（pptr/base/角色属性，每 1 秒刷新）
        card2, cf2 = make_card(about_form, _tr("── 重要内存地址与数据 ──"))
        cf2.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.memref_edit = QPlainTextEdit()
        self.memref_edit.setReadOnly(True)
        self.memref_edit.setMinimumHeight(420)
        self.memref_edit.setStyleSheet(
            "background:rgba(20,26,40,0.6); color:#cdd6e0; border-radius:6px;"
            "font-family:Consolas,'Courier New',monospace;font-size:11px;")
        cf2.addRow(self.memref_edit)
        about_form.addRow(card2)
        # QTimer 每 1 秒刷新一次实时区
        from PySide6.QtCore import QTimer as _QTimer
        self._memref_timer = _QTimer(self)
        self._memref_timer.setInterval(1000)
        self._memref_timer.timeout.connect(self._refresh_memref)
        self._memref_timer.start()
        self._refresh_memref()       # 立即填一次

        about_form.addItem(QSpacerItem(20, 1, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.skip_version = self.settings.get("skip_version", "") or ""
        if self.ctrl is not None and getattr(self.ctrl, "update_info", None) is not None:
            self.refresh_update_ui(self.ctrl.update_info)
        else:
            self.update_status_label.setText("—")
            self.changelog_edit.setPlainText(_load_local_changelog(self.settings.get("language", "zh")))
        # V2084：让角色名/专精等显示跟当前语言刷新
        if hasattr(self, "_refresh_memref"):
            self._refresh_memref()
        # ── 信号 / 按钮（必须留在 __init__ 函数体，不能被 _refresh_memref 的缩进吞掉）──
        self._connect_live_signals()
        # V2255 BUGFIX：语言切换此前**只**连了 retranslate_ui（仅刷新设置弹窗自己的文本），
        # 没有把新语言推出去：控制器与 5 个模块窗口的 settings 都不更新（模块那份还是
        # 构造时的深拷贝快照）→ overlay 上读 self.settings["language"] 的路径（buff 名等）
        # 仍按旧语言渲染，玩家切完日文要重启软件才生效。
        # 先 _emit_changed（写 settings → 控制器 → 5 个模块窗口），再 retranslate_ui（刷本弹窗）。
        self.lang.currentIndexChanged.connect(self._emit_changed)
        self.lang.currentIndexChanged.connect(self.retranslate_ui)
        buttons = QHBoxLayout()
        defaults = QPushButton(_tr("恢复默认")); ok = QPushButton(_tr("确定")); cancel = QPushButton(_tr("取消"))
        defaults.setAutoDefault(False); defaults.setDefault(False); ok.setAutoDefault(True); ok.setDefault(True); cancel.setAutoDefault(False); cancel.setDefault(False)
        defaults.clicked.connect(self.reset_defaults); ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        buttons.addWidget(defaults); buttons.addWidget(ok); buttons.addWidget(cancel)
        layout.addLayout(buttons)
        sig = QLabel(AUTHOR_TAG); sig.setStyleSheet("color:#445566; font-size:9px;"); sig.setAlignment(Qt.AlignCenter)
        layout.addWidget(sig)
        self.retranslate_ui()
        # V2304：构造彻底结束（含 retranslate_ui 回填文本），放开实时通知。
        # 必须放在 retranslate_ui 之后——它会重设下拉项文本/索引，同样会触发通知。
        self._suppress_emit = False

    def _refresh_memref(self):
        """V2084：About 页「重要内存地址与数据」实时刷新——每 1 秒一次。
        上半：静态偏移速查表（常量，模块内相对）。下半：实时值（从 self.ctrl 读运行期）。"""
        # 静态：偏移速查（与 ~/.workbuddy/skills/gbfr-offset-drift-fix/SKILL.md 同步）
        # V2254：静态速查表全部包 _tr()——此前是裸字符串，无论切什么语言都硬显示中文。
        # 技术信息（hex 偏移 / 版本号 / 字段名如 mgr、record、pptr、node_id）在各语言 value 里
        # **原样保留不译**，只把中文说明部分译成对应语言，保证开发者对照偏移时不被翻译干扰。
        static_part = [
            _tr("【静态 · 偏移速查（2.0.4 实测 / 模块内相对，与 ASLR 无关）】"),
            "─" * 64,  # 纯符号分隔线，无语言，不翻译
            _tr("玩家全局指针变量地址 pptr   = (actor+0x5788 ptr)        模块内: 动态 AOB 定位"),
            _tr("模块基址  base                = granblue_fantasy_relink.exe 基址"),
            _tr("模块大小  size                = 0x8217000 (136.0 MB) 实测"),
            _tr("quest_mgr 全局指针  (与 pptr 相对 QM_DELTA = 0xC1E030)"),
            _tr("    mgr + 0x210   → flow 指针 (0=城镇/非任务, 非0=任务中)"),
            _tr("    mgr + 0x2d8   → flow 状态枚举 (relink-logs v2.0.2+)"),
            _tr("    mgr + 0xB20/0xB28  → 训练场计时器 (城镇=0, 训练场非0)"),
            _tr("    mgr + 0xAC8   → 任务已用秒数 (城镇时为残留值, 不要严格校验)"),
            _tr("    mgr + 0xDC8   → 任务 ID (含 0xf00000 掩码)"),
            _tr("actor + 0x15030 → record (内嵌)            2.0.4 沿用"),
            _tr("record + 0x5B10 → 当前 charid             2.0.4 沿用"),
            _tr("record + 0x138  → 专精节点数组 (400 槽 × 0x38) 2.0.4 沿用"),
            _tr("CharaPower RVA   = 0x7C22F38              2.0.4 实测 (2.0.3=0x7C21A38, 2.0.2=0x7C22CB8)"),
            _tr("    mgr + 0x320/0x330/0x348  → node_instance_key → row (key→row map)"),
            _tr("    mgr + 0x728/0x738/0x750  → charid → key_vector (charid→key map)"),
            _tr("    row + 0x48 → node_id, row + 0x5C → unlock bit, row + 0x74 → effect_id"),
            _tr("actor + 0x1FD   → 角色类型字节 (0x07=菲莉, 0x11=齐格飞, ...)"),
            _tr("actor + 0x1AB40 → 角色 ID (PL0100/PL0000 etc.)"),
            _tr("actor + 0x5788  → player 全局指针 (pptr)"),
            _tr("field 0x64C/0xAC8/0x5788  → 奥义槽 / 任务计时 / 玩家"),
        ]
        # 实时：运行期从 self.ctrl 读
        # V2254：实时区标题同样包 _tr()（此前是裸中文字符串）
        live_lines = ["", _tr("【实时 · 运行期值（每 1 秒刷新）】"), "─" * 64]
        c = getattr(self, "ctrl", None)
        if c is None:
            live_lines.append(_tr("（ctrl 尚未绑定——设置窗口打开时主程序未运行）"))
        else:
            lang = self.settings.get("language", "zh") if hasattr(self, "settings") else "zh"
            try:
                pptr = getattr(c, "pptr", None)
                base = getattr(c, "module_base", None)
                size = getattr(c, "module_size", None) or 0
                quest_mgr = getattr(c, "quest_mgr", None)
                char_type = getattr(c, "char_type", 0) or 0
                charid_hash = getattr(c, "charid_hash", 0) or 0
                pl_id = getattr(c, "pl_id", None) or ""
                # 角色名（用 _resolve_char；不可用时显示 charid_hash/char_type）
                char_name = "—"
                try:
                    nm, _t, _full = _resolve_char(charid_hash, char_type, lang)
                    if nm:
                        char_name = nm
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
                in_combat = getattr(c, "in_combat", None)
                in_training = getattr(c, "in_training_area", None)
                mastery = getattr(c, "current_mastery", None)
                # V2254：专精三系名也走 _tr()（此前硬编码中文，切语言不变）
                mastery_zh = {"awakening": _tr("觉醒"), "truth": _tr("真谛"), "secret": _tr("秘义")}.get(mastery, mastery or _tr("未识别"))
                dodge_count = getattr(c, "dodge_count", 0) or 0
                status = getattr(c, "status", "init")
                sk_n = len(getattr(c, "skill_cd_data", []) or [])
                buf_n = len(getattr(c, "all_buffs_filtered", {}) or {})

                # V2219：诊断行改成「_tr(静态中文片段) + 动态值」。f-string 整串不能包 _tr，
                # 否则键会变成运行时拼接结果（如 "角色名 char_name = Gran"）而在 i18n 里查不到。
                live_lines.append(f"{_tr('模块基址 base    = ')}{base:#x}" if base else _tr("模块基址 base    = ") + _tr("（未读到）"))
                live_lines.append(f"{_tr('模块大小 size    = ')}{size:#x} ({size/1048576:.1f} MB)" if size else _tr("模块大小 size    = ") + _tr("（未读到）"))
                live_lines.append(f"{_tr('玩家 pptr        = ')}{pptr:#x}" if pptr else _tr("玩家 pptr        = ") + _tr("（未读到）"))
                live_lines.append(f"quest_mgr        = {quest_mgr:#x}" if quest_mgr else "quest_mgr        = " + _tr("（未读到）"))
                # 角色
                live_lines.append(_tr("角色名 char_name = ") + f"{char_name}")
                live_lines.append(_tr("角色 ID  pl_id    = ") + (f"{pl_id}" if pl_id else _tr("（未识别）")))
                live_lines.append(_tr("char_type 字节   = ") + f"{char_type:#04x}   charid_hash = {charid_hash:#010x}")
                # 状态
                live_lines.append(_tr("运行状态 status  = ") + f"{status}")
                live_lines.append(_tr("战斗中 in_combat  = ") + f"{in_combat}    " + _tr("训练场 in_training = ") + f"{in_training}")
                live_lines.append(_tr("专精 mastery     = ") + f"{mastery_zh}")
                live_lines.append(_tr("翻滚次数 dodge    = ") + f"{dodge_count}")
                live_lines.append(_tr("技能数 skills    = ") + f"{sk_n}    " + _tr("全 Buff 候选 = ") + f"{buf_n}")
            except Exception as e:
                live_lines.append(f"{_tr('（读取运行期数据失败：')}{e}" + _tr("）"))
        # V2091 修「实时区每秒刷新把滚动条弹回顶」：setPlainText 触发 Qt 重置滚动条到 0，
        # 玩家手动滚到中间看某行下一秒就被弹回去。修法：保存原位置/底部标志，刷新后恢复。
        _vbar = self.memref_edit.verticalScrollBar()
        _was_at_bottom = _vbar.value() >= _vbar.maximum() - 4
        _old_pos = _vbar.value()
        self.memref_edit.setPlainText("\n".join(static_part + live_lines))
        if _was_at_bottom:
            _vbar.setValue(_vbar.maximum())   # 在底部时保持底部（tail 行为）
        else:
            _vbar.setValue(min(_old_pos, _vbar.maximum()))  # 中间时保持原绝对位置

    def retranslate_ui(self, *_):
        """根据语言下拉框刷新设置弹窗文本。"""
        lang = self.lang.currentData() if hasattr(self, "lang") else self.settings.get("language", "zh")
        global _CURRENT_LANG
        _CURRENT_LANG = lang

        en_to_zh = {v: k for k, v in ZH_TO_EN.items()}
        tw_to_zh = {v: k for k, v in ZH_TO_TW.items()}
        ja_to_zh = {v: k for k, v in ZH_TO_JA.items()}   # V2203：日语
        if lang == "en":
            target_map = ZH_TO_EN
        elif lang == "zh_tw":
            target_map = ZH_TO_TW
        elif lang == "ja":
            target_map = ZH_TO_JA          # V2203：日语
        else:
            target_map = {}

        def _translate_text(text):
            """先归一化到简中，再翻译到目标语言。"""
            if text in en_to_zh:
                text = en_to_zh[text]
            elif text in tw_to_zh:
                text = tw_to_zh[text]
            elif text in ja_to_zh:
                text = ja_to_zh[text]
            return target_map.get(text, text)

        self._refresh_settings_title()
        if hasattr(self, "settings_tabs") and hasattr(self, "_top_tabs_zh"):
            for i, name in enumerate(self._top_tabs_zh):
                if i < self.settings_tabs.count():
                    self.settings_tabs.setTabText(i, _translate_text(name))
        if hasattr(self, "_sub_tabs"):
            for sub_tabs, names in self._sub_tabs:
                for i, name in enumerate(names):
                    if i < sub_tabs.count():
                        sub_tabs.setTabText(i, _translate_text(name))
        for label in self.findChildren(QLabel):
            text = label.text()
            translated = _translate_text(text)
            if translated != text:
                label.setText(translated)
        for checkbox in self.findChildren(QCheckBox):
            text = checkbox.text()
            translated = _translate_text(text)
            if translated != text:
                checkbox.setText(translated)
        for button in self.findChildren(QPushButton):
            text = button.text()
            translated = _translate_text(text)
            if translated != text:
                button.setText(translated)
        for gb in self.findChildren(QGroupBox):
            text = gb.title()
            translated = _translate_text(text)
            if translated != text:
                gb.setTitle(translated)

        # V2255 BUGFIX：QComboBox 的下拉选项（item 文本）此前**完全不在**自动翻译范围内——
        # retranslate_ui 只遍历了 QLabel / QCheckBox / QPushButton / QGroupBox 四类，
        # 下拉框的 item 一个都没碰，仅 timer_style / roll_orientation / buff_order_direction /
        # title_align 少数几个被手工硬编码处理过。后果：玩家切到日文后，设置面板里
        # 「按出现时间 / 居中 / 靠左 / 靠右 / 顶部对齐 / 底部对齐」等下拉选项仍是中文，
        # 而 label 已经正确变日文 —— 用户反馈「好多选项、好多文本、全都是中文」。
        # 这里统一遍历所有 QComboBox，只翻译 item 的**显示文本**、不动 itemData；
        # 且仅当该文本在翻译表里存在时才改（角色名 / buff 名等数据项不在 UI 翻译表内，
        # 会自动跳过，不会被误伤）。
        for combo in self.findChildren(QComboBox):
            for _i in range(combo.count()):
                _t = combo.itemText(_i)
                if not _t:
                    continue
                _nt = _translate_text(_t)
                if _nt != _t:
                    combo.setItemText(_i, _nt)

        # V2255：这两个手工块已删除——它们把日文/繁中强制写回中文
        # （"Ring" if lang=="en" else "圆环" → 日文下仍是「圆环」而非「円環」），
        # 且覆盖上面新加的通用 combo item 翻译。i18n.json 里 圆环/扇形/横放/竖放
        # 四语的译文齐备（ja: 円環/セクター/横置き/縦置き），交给通用逻辑即可，4 语全支持。

        # EXE 同步：tooltip / placeholder 不在上面的自动翻译范围内，显式刷新
        if hasattr(self, "sync_exe_le"):
            self.sync_exe_le.setToolTip(_tr("多个 exe 的绝对路径，用分号或换行分隔。每条可附加「||工作目录」指定起始位置（等同 .lnk 的起始位置，可省略）。程序启动时检测：未运行则共同启动（以指定工作目录为起始位置），已运行则跳过（不监视、不杀进程）。", lang))
            self.sync_exe_le.setPlaceholderText(_tr("多个 exe 绝对路径，可用分号或换行分隔；可附加 ||工作目录", lang))

        # V2255：同样删除——原逻辑 zh_tw / ja 两支返回值相同（都是「越上越靠左」），
        # 日文下不会变成「上ほど左へ」。i18n.json 里 ja=上ほど左へ / 上ほど右へ 齐备，
        # 交给上面的通用 combo item 翻译处理。

        # 标题栏对齐下拉：QComboBox 文本不在 QLabel 自动翻译范围内，显式刷新
        if hasattr(self, "title_align_combo"):
            for _data, _key in (("left", "靠左"), ("center", "居中"), ("right", "靠右")):
                _i = self.title_align_combo.findData(_data)
                if _i >= 0:
                    self.title_align_combo.setItemText(_i, _tr(_key, lang))

        # V350/V373：补全此前漏翻的控件
        if hasattr(self, "multi_buff_ctrls"):
            for _cnt, _c in self.multi_buff_ctrls.items():
                _mcb = _c.get("mode_cb")
                if _mcb is not None:
                    _mcb.setItemText(0, _tr("色环均匀 / 大反差"))
                    _mcb.setItemText(1, _tr("同色系 / 相近"))
        # V373：多 buff 分组 label / QGroupBox 标题按当前语言刷新
        if hasattr(self, "multi_buff_labels"):
            for (_cnt, _key), _w in self.multi_buff_labels.items():
                if _key == "group_title":
                    _w.setTitle(_tr("{} 个 buff 同屏").format(_cnt))
                else:
                    _map = {
                        "scale": "缩放{}:",
                        "hgap": "圆心水平间距{}:",
                        "dy": "圆心Delta_Y{}:",
                        "ext_color": "外部差异化颜色{}:",
                        "int_color": "内部差异化颜色{}:",
                        "mode": "颜色分布模式{}:",
                        "mono_span": "同色系间距{}:",
                    }
                    _tmpl = _map.get(_key)
                    if _tmpl:
                        _w.setText(_tr(_tmpl).format(_cnt))
        if hasattr(self, "download_url_le"):
            self.download_url_le.setPlaceholderText(_tr("检查更新后自动填入，或手动填写 exe 下载直链"))

        # 翻译角色分组框标题（含编号）
        if hasattr(self, "buff_order_groups"):
            for _, group in self.buff_order_groups.items():
                group.refresh_title(lang)
                group.refresh_items(lang)

        # 更新日志按当前语言重取（远端多语言 changelog / 本地兜底）
        if hasattr(self, "changelog_edit"):
            try:
                info = getattr(self.ctrl, "update_info", None)
                remote_cl = pick_lang_text(info.get("changelog", ""), lang) if info and not info.get("error") else ""
                self.changelog_edit.setPlainText(_safe_remote_changelog(remote_cl, lang, _load_local_changelog(lang)))
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

        # V2116：两个名单（黑名单 + 多次出现名单）的 list / combo / hint / GroupBox 标题随语言刷新
        # V2206：扩展为 4 个 key，boss 模块的 hint/title 文本以 Boss Buff 模块为前缀
        if hasattr(self, "_buff_groups"):
            try:
                for _which in ("bl", "ml", "boss_bl", "boss_ml"):
                    self._refresh_buff_list(_which)
                    self._refresh_buff_combo(_which)
                _hint_keys = {
                    "bl": "黑名单中的 buff 在全 Buff 模块中永不显示（用于屏蔽干扰视觉或毫无意义的 buff 残余，例如某些沉默帧残留的瞬时护盾）。从下方下拉菜单选择要屏蔽的 Buff（仅限全角色通用 buff；角色专属 buff 已自动排除，不必再加入黑名单）。",
                    "ml": "多次出现名单中的 buff 在全 Buff 模块中可显示多个实例（如帕西瓦尔双重追击）；其它 buff 默认只显示 1 个。从下方下拉菜单选择要放行的 Buff（仅限全角色通用 buff；角色专属 buff 已自动排除，无法多次出现）。注：黑名单中的 buff 不会出现在此处。",
                    "boss_bl": "黑名单中的 buff 在 Boss Buff 模块中永不显示（避免在 boss 监控里出现没意义的 buff 残余）。从下方下拉菜单选择要屏蔽的 Buff（仅限通用 buff；boss 专属由模块自带过滤）。",
                    "boss_ml": "多次出现名单中的 buff 在 Boss Buff 模块中可显示多个实例（boss 身上同 buff 多个源时各显示一次）。从下方下拉菜单选择要放行的 Buff（仅限通用 buff）。注：黑名单中的 buff 不会出现在此处。",
                }
                _gb_titles = {
                    "bl": "黑名单",
                    "ml": "多次出现名单",
                    "boss_bl": "黑名单",
                    "boss_ml": "多次出现名单",
                }
                for _which in ("bl", "ml", "boss_bl", "boss_ml"):
                    _gd = self._buff_groups.get(_which, {})
                    if _gd.get("hint") is not None:
                        _gd["hint"].setText(_tr(_hint_keys[_which]))
                    if _gd.get("gb") is not None:
                        _gd["gb"].setTitle(_tr(_gb_titles[_which]))
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

    def _add_color_row(self, form, key, label, with_opacity=True):
        """创建一行：颜色按钮 + 不透明度标签 + 不透明度微调框。"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        hex_val = self.settings.get(key, "#ffffff")
        btn = QPushButton(hex_val)
        btn.setStyleSheet(f"background:{hex_val}; color:#fff; border-radius:4px;")
        btn.setFixedWidth(90)
        btn.clicked.connect(lambda _=False, k=key, b=btn: self.pick_color(k, b))

        if with_opacity:
            op_label = QLabel(_tr("不透明度"))
            op_label.setStyleSheet("color:#8899aa; font-size:11px;")

        row.addWidget(btn)
        if with_opacity:
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix("%")
            spin.setValue(int(self.settings.get(f"{key}_opacity", 100)))
            spin.setFixedWidth(64)
            row.addWidget(op_label)
            row.addWidget(spin)
            self.opacity_spins[key] = spin
        row.addStretch()
        container = QWidget()
        container.setLayout(row)
        form.addRow(label, container)

        self.color_buttons[key] = btn

    def _emit_changed(self, *_):
        if getattr(self, "_suppress_emit", False):
            return
        if hasattr(self, "icon_use_default"):
            self._sync_icon_default_enabled()
        # V2313：第 6/7 次样式切换后同步「三角形 / 图片」两组参数的可用态
        if hasattr(self, "warning_mode_combo"):
            self._sync_warning_mode_ui()
        self.settings_changed.emit(self.get_settings())

    def _sync_icon_default_enabled(self):
        use_default = bool(self.icon_use_default.isChecked())
        self.icon_path.setEnabled(not use_default)
        self.browse_icon_btn.setEnabled(not use_default)

    def _sync_warning_mode_ui(self):
        """V2313：按「第 6/7 次样式」启用/禁用对应参数区——
        选「警告三角形」→ 三角形参数可用、图片参数禁用；选「图片」→ 反过来。

        注意：这里只改控件可用态，不写 settings、不触发 get_settings()，
        所以不会造成 V2265 那种配对控件互相触发的信号风暴。
        """
        if not hasattr(self, "warning_mode_combo"):
            return
        is_img = (self.warning_mode_combo.currentData() == "image")
        # 三角形专属参数
        for _w in (getattr(self, "warning_size_sld", None), getattr(self, "warning_size_spn", None),
                   getattr(self, "warning_bw_sld", None), getattr(self, "warning_bw_spn", None),
                   getattr(self, "warning_corner_spn", None)):
            if _w is not None:
                _w.setEnabled(not is_img)
        for _k in ("warning_outline_color", "warning_fill_color"):
            _btn = self.color_buttons.get(_k)
            if _btn is not None:
                _btn.setEnabled(not is_img)
        # 图片模式专属参数
        _use_def = bool(getattr(self, "warning_img_use_default", None) and self.warning_img_use_default.isChecked())
        for _w in (getattr(self, "warning_img_use_default", None), getattr(self, "warning_img_scale", None)):
            if _w is not None:
                _w.setEnabled(is_img)
        if getattr(self, "warning_img_path", None) is not None:
            self.warning_img_path.setEnabled(is_img and not _use_def)
        if getattr(self, "browse_warning_icon_btn", None) is not None:
            self.browse_warning_icon_btn.setEnabled(is_img and not _use_def)

    def _wire_anchor_sync(self, ha_combo, va_combo, hm_spn, vm_spn, xs, ys, module_key):
        """V2244：整屏对齐 / 边距 / 缩放变化时，让上方「模块位置 X/Y」spinbox 同步刷新显示，
        且非「自定义」轴禁用 X/Y 编辑（对齐本质就是参数化布局，禁止手动改坐标）。"""
        def _sync(*_):
            _s = getattr(self.ctrl, "settings", None)
            if _s is None:
                return
            # 先把本模块的对齐设置写回 ctrl，保证下面重排用的是「当前对话框里的值」
            # （不依赖信号连接顺序，自包含、可重入）
            _s[f"{module_key}_halign"] = ha_combo.currentData() or "custom"
            _s[f"{module_key}_valign"] = va_combo.currentData() or "custom"
            _s[f"{module_key}_hmargin"] = int(hm_spn.value())
            _s[f"{module_key}_vmargin"] = int(vm_spn.value())
            _sl = getattr(self, f"{module_key}_scale_slider", None)
            if _sl is not None:
                _s[f"{module_key}_scale_percent"] = int(_sl.value())
            # 让主程序按当前对齐设置重排窗口（对齐模式下窗口会被 move 到贴边/居中位置）
            _refresh = getattr(self.ctrl, "_refresh_window_geometries", None)
            if _refresh is not None:
                try:
                    _refresh()
                except Exception:
                    pass
            # 读真实屏幕坐标回填 X/Y
            w = None
            for _ww in self.ctrl._all_windows():
                if getattr(_ww, "module_key", None) == module_key:
                    w = _ww
                    break
            if w is not None:
                xs.blockSignals(True); xs.setValue(int(round(w.x()))); xs.blockSignals(False)
                ys.blockSignals(True); ys.setValue(int(round(w.y()))); ys.blockSignals(False)
            # 非「自定义」轴：X/Y 置灰不可手改（参数化布局接管）
            xs.setEnabled((ha_combo.currentData() or "custom") == "custom")
            ys.setEnabled((va_combo.currentData() or "custom") == "custom")
        for _w in (ha_combo, va_combo, hm_spn, vm_spn):
            if isinstance(_w, QComboBox):
                _w.currentIndexChanged.connect(_sync)
            elif isinstance(_w, (QSpinBox, QDoubleSpinBox)):
                _w.valueChanged.connect(_sync)
        # 缩放滑块 / 数字框改变尺寸后，居中 / 靠右 / 靠上 / 靠下 对齐位置会随之变化，也要重算
        _sl = getattr(self, f"{module_key}_scale_slider", None)
        _sp = getattr(self, f"{module_key}_scale_spin", None)
        for _w in (_sl, _sp):
            if isinstance(_w, (QSlider, QSpinBox, QDoubleSpinBox)):
                _w.valueChanged.connect(_sync)
        # 打开对话框时先按当前对齐状态定位 + 禁用非 custom 轴
        _sync()

    def _set_all_buff_rank(self, show):
        """「全勾选」= 每组三框全勾（常显）；「全取消」= 三框全不勾（常关）。"""
        action = _tr("全部勾选") if show else _tr("全部取消")
        reply = QMessageBox.question(
            self,
            _tr("确认操作"),
            _tr("确定要{}所有角色的专精勾选框吗？\n（仅影响当前设置，可手动撤销）").format(action),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for group in getattr(self, "buff_order_groups", {}).values():
            group.set_all(bool(show))
        self._emit_changed()

    def _connect_live_signals(self):
        widgets = [
            self.lang, self.auto_focus_minimize, self.resolution_auto_scale, self.spike_hide_chk, self.spike_hidden_op_spn, self.show_spikes_chk, self.show_bead_chk, self.show_titlebar_status, self.titlebar_font_size_spn, self.status_indent_spn, self.icon_indent_spn, self.icon_use_default,
            self.core_scale_slider, self.core_scale_spin, self.roll_scale_slider, self.roll_scale_spin, self.skill_scale_slider, self.skill_scale_spin,
            self.core_halign_combo, self.core_valign_combo, self.core_hmargin_spn, self.core_vmargin_spn,
            self.roll_halign_combo, self.roll_valign_combo, self.roll_hmargin_spn, self.roll_vmargin_spn,
            self.skill_halign_combo, self.skill_valign_combo, self.skill_hmargin_spn, self.skill_vmargin_spn,
            self.scan, self.circle_radius, self.spike_length, self.spike_axis_pos,
            self.spike_width, self.spike_waist_pos, self.spike_bead_radius, self.spike_bead_pos,
            self.indicator_outline_enabled, self.indicator_outline_width,
            self.dh_font_size, self.dh_text_outline_width, self.timer_font_size,
            self.timer_style, self.timer_arc_radius,
            self.timer_center_y,
            self.center_offset_x, self.center_offset_y,
            self.dh_font_size_timer, self.center_offset_x_timer, self.center_offset_y_timer, self.dh_text_outline_width_timer,
            self.icon_path, self.icon_scale, self.roll_icon_opacity_spin,
            self.circle_pad_title,
            self.core_canvas_w_spn, self.core_canvas_h_spn,
            self.lv7_timer_y_offset,
            self.lv7_timer_badge_width,
            self.single_timer_y_offset,
            self.single_timer_badge_width,
            self.single_timer_font_size,
            self.skill_cd_size_spn, self.skill_cd_spread_spn,
            self.skill_cd_font_size_spn, self.skill_cd_capsule_w_spn,
            self.skill_cd_timer_offx_spn, self.skill_cd_timer_offy_spn,
            self.skill_cd_bg_opacity_sl, self.skill_cd_sector_opacity_sl,
            self.skill_cd_border_opacity_sl, self.skill_cd_capsule_opacity_sl,
            self.skill_cd_name_chk, self.skill_cd_name_font_spn,
            self.skill_cd_name_offx_spn, self.skill_cd_name_offy_spn,
            self.skill_cd_name_bgw_spn,
            self.skill_cd_border_scale_dspn, self.skill_cd_breath_chk,
            self.skill_cd_breath_freq_dspn, self.skill_cd_breath_soft_dspn,
            self.skill_cd_breath_scale_dspn,
            # ── V203: 闪光全局化 / 模块位置 / 翻滚朝向 ──
            self.flash_scale_spn, self.flash_dur_spn,
            self.flash_apply_spikes_chk, self.flash_apply_skill_ready_chk,
            self.flash_apply_dodge_chk,
            self.warning_corner_spn,
            # V2313：第 6/7 次样式（下拉 / 内置图勾选 / 图片路径 / 图片缩放）
            self.warning_mode_combo, self.warning_img_use_default, self.warning_img_path, self.warning_img_scale,
            self.roll_orientation_combo,
            self.buff_order_direction_combo,
            self.core_x_spn, self.core_y_spn, self.roll_x_spn, self.roll_y_spn,
            self.skill_x_spn, self.skill_y_spn,
            self.allbuff_x_spn, self.boss_x_spn, self.allbuff_y_spn, self.boss_y_spn,
            self.allbuff_scale_slider, self.boss_scale_slider,
            self.allbuff_scale_spin, self.boss_scale_spin,
            # V2200：Boss 模块位置 / 缩放
            self.allbuff_per_row_spn, self.boss_per_row_spn,
            self.allbuff_rows_spn, self.boss_rows_spn,
            self.allbuff_sort_mode_combo, self.boss_sort_mode_combo,
            # V2226：行内对齐（靠左 / 居中 / 靠右）
            self.allbuff_row_align_combo, self.boss_row_align_combo,
            # V2228：整屏对齐（水平 / 垂直）
            self.allbuff_halign_combo, self.boss_halign_combo,
            self.allbuff_valign_combo, self.boss_valign_combo,
            # V2229：水平/垂直边距（可负数）
            self.allbuff_hmargin_spn, self.allbuff_vmargin_spn,
            self.boss_hmargin_spn, self.boss_vmargin_spn,
            self.allbuff_row_spacing_spn, self.boss_row_spacing_spn,
            self.allbuff_card_spacing_spn, self.boss_card_spacing_spn,
            # V2060：元素统一间距 + 进度条外框粗细
            self.allbuff_element_spacing_spn, self.boss_element_spacing_spn,
            self.allbuff_bar_frame_thickness_spn, self.boss_bar_frame_thickness_spn,
            # V2074：行高加成
            self.allbuff_row_height_extra_spn, self.boss_row_height_extra_spn,
            # V2093：排序号消失宽限
            self.allbuff_seq_gone_grace_dspn, self.boss_seq_gone_grace_dspn,
            self.allbuff_warn_enabled_chk, self.boss_warn_enabled_chk,
            self.allbuff_warn_threshold_spn, self.boss_warn_threshold_spn,
            # V2060：Debuff 警告开关
            self.allbuff_debuff_warn_enabled_chk, self.boss_debuff_warn_enabled_chk,
            self.allbuff_name_font_size_spn, self.boss_name_font_size_spn,
            self.allbuff_stacks_font_size_spn, self.boss_stacks_font_size_spn,
            self.allbuff_time_font_size_spn, self.boss_time_font_size_spn,
            self.allbuff_bar_width_spn, self.boss_bar_width_spn,
            self.allbuff_bar_height_spn, self.boss_bar_height_spn,
            self.allbuff_backing_width_spn, self.boss_backing_width_spn,
            self.allbuff_backing_height_spn, self.boss_backing_height_spn,
            # ── V2304：调试数据（全部内联独立创建，走下方 isinstance 分派自动接线）──
            self.debug_data_enabled_chk, self.debug_text_le, self.debug_countdown_spn,
            self.debug_status_cmb, self.debug_in_combat_chk, self.debug_mastery_cmb,
            self.debug_core_count_spn, self.debug_core_single_chk, self.debug_core_full_chk,
            self.debug_core_stacks_spn, self.debug_core_max_spn,
            self.debug_core_awk_chk, self.debug_core_truth_chk, self.debug_core_secret_chk,
            self.debug_allbuff_normal_spn, self.debug_allbuff_debuff_spn,
            self.debug_allbuff_perma_spn, self.debug_allbuff_coda_spn,
            self.debug_allbuff_stacks_spn, self.debug_allbuff_max_spn,
            self.debug_boss_normal_spn, self.debug_boss_debuff_spn,
            self.debug_boss_perma_spn, self.debug_boss_coda_spn,
            self.debug_boss_stacks_spn, self.debug_boss_max_spn,
            self.debug_skill_count_spn, self.debug_skill_ready_spn,
            self.debug_skill_cdmax_spn, self.debug_dodge_spn,
        ]
        for w in widgets:
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._emit_changed)
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(self._emit_changed)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox, QSlider)):
                w.valueChanged.connect(self._emit_changed)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(self._emit_changed)
        for spin in self.opacity_spins.values():
            spin.valueChanged.connect(self._emit_changed)
        # 全局快捷键逐项勾选框
        for prefix in ("hk_show", "hk_lock", "hk_settings"):
            chk = getattr(self, f"{prefix}_enabled", None)
            if isinstance(chk, QCheckBox):
                chk.stateChanged.connect(self._emit_changed)
        self.show_buff_name_cb.stateChanged.connect(self._emit_changed)
        self.buff_name_font_size.valueChanged.connect(self._emit_changed)
        self.buff_name_offset_x.valueChanged.connect(self._emit_changed)
        self.buff_name_offset_y.valueChanged.connect(self._emit_changed)
        self.buff_name_bg_width.valueChanged.connect(self._emit_changed)
        # 模块显示开关：勾选/取消后立即反馈到主界面
        self.show_core_module_chk.stateChanged.connect(self._emit_changed)
        self.show_roll_module_chk.stateChanged.connect(self._emit_changed)
        self.show_skill_module_chk.stateChanged.connect(self._emit_changed)
        self.show_allbuff_module_chk.stateChanged.connect(self._emit_changed)
        self.show_boss_module_chk.stateChanged.connect(self._emit_changed)
        self.allbuff_exclude_core_chk.stateChanged.connect(self._emit_changed)
        self.allbuff_exclude_infinite_chk.stateChanged.connect(self._emit_changed)
        self.allbuff_exclude_exclusive_chk.stateChanged.connect(self._emit_changed)
        self.allbuff_exclude_mastery_chk.stateChanged.connect(self._emit_changed)
        self.allbuff_exclude_single_chk.stateChanged.connect(self._emit_changed)
        # V2066：门限（monitor 风格数值废料过滤）实时生效
        # V2216：allbuff_gate_filter_status_id_zero 复选框已移除（filter 固化常闭）
        # V2222：status_id_max / sub_id_max 两项已恢复为可配置门限（见上方 reset 与 UI 控件）；
        #         gate_check_stack_conflict / gate_duration_max 仍为固化（无 UI 控件）。
        self.gate_stacks_max_chk.stateChanged.connect(self._emit_changed)
        self.gate_stacks_max_spn.valueChanged.connect(self._emit_changed)
        self.gate_max_stacks_max_chk.stateChanged.connect(self._emit_changed)
        self.gate_max_stacks_max_spn.valueChanged.connect(self._emit_changed)
        self.gate_min_remaining_chk.stateChanged.connect(self._emit_changed)
        self.gate_min_remaining_spn.valueChanged.connect(self._emit_changed)
        self.gate_min_initial_chk.stateChanged.connect(self._emit_changed)
        self.gate_min_initial_spn.valueChanged.connect(self._emit_changed)
        # V2084
        self.gate_min_appearance_chk.stateChanged.connect(self._emit_changed)
        self.gate_min_appearance_spn.valueChanged.connect(self._emit_changed)
        # V2117：NaN/Inf、ID=0 排除永续、隐藏 0.0/0.0、remaining/initial 任一 < 0 四门限已固化，不再有 UI 开关/信号连接。
        # V2065：画布背景不透明度
        self.allbuff_canvas_bg_opacity_spn.valueChanged.connect(self._emit_changed)
        # V2200：Boss 模块实时生效（布局/字体/衬底/警告控件已在上方 widgets 列表内统一连接）
        # V2210：boss 分类显示控件已删除（玩家不需），此处无需 connect
        # V2200：Boss 门限（monitor 风格数值废料过滤）实时生效
        # V2216：boss_gate_filter_status_id_zero 复选框已移除（filter 固化常闭）
        # V2222：boss_gate_status_id_max / boss_gate_sub_id_max 两项已恢复为可配置门限（见上方 connect 与 UI 控件）；
        #        boss_gate_check_stack_conflict / boss_gate_duration_max 仍为固化（无 UI 控件）。
        self.boss_gate_stacks_max_chk.stateChanged.connect(self._emit_changed)
        self.boss_gate_stacks_max_spn.valueChanged.connect(self._emit_changed)
        self.boss_gate_max_stacks_max_chk.stateChanged.connect(self._emit_changed)
        self.boss_gate_max_stacks_max_spn.valueChanged.connect(self._emit_changed)
        self.boss_gate_min_remaining_chk.stateChanged.connect(self._emit_changed)
        self.boss_gate_min_remaining_spn.valueChanged.connect(self._emit_changed)
        self.boss_gate_min_initial_chk.stateChanged.connect(self._emit_changed)
        self.boss_gate_min_initial_spn.valueChanged.connect(self._emit_changed)
        self.boss_gate_min_appearance_chk.stateChanged.connect(self._emit_changed)
        self.boss_gate_min_appearance_spn.valueChanged.connect(self._emit_changed)
        # V2065：Boss 画布背景不透明度
        self.boss_canvas_bg_opacity_spn.valueChanged.connect(self._emit_changed)

    def keyPressEvent(self, event):
        """禁止 Enter/Return 键关闭对话框，避免输入中途误退出。"""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _browse_icon(self):
        lang = self.settings.get("language", "zh")
        dlg_titles = {"zh": "选择翻滚图标", "zh_tw": "選擇翻滾圖標", "en": "Select Dodge Icon"}
        dlg_filters = {"zh": "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)",
                        "zh_tw": "圖片檔案 (*.png *.jpg *.jpeg *.bmp *.gif)",
                        "en": "Image files (*.png *.jpg *.jpeg *.bmp *.gif)"}
        path, _ = QFileDialog.getOpenFileName(
            self, dlg_titles.get(lang, dlg_titles["zh"]), "",
            dlg_filters.get(lang, dlg_filters["zh"])
        )
        if path:
            self.icon_path.setText(path)

    def _browse_warning_icon(self):
        """V2313：选择第 6/7 次用的警告图片（任意 PNG/JPG/BMP/GIF，闪光自动适配）。"""
        lang = self.settings.get("language", "zh")
        dlg_titles = {"zh": "选择警告图片", "zh_tw": "選擇警告圖片", "en": "Select Warning Image", "ja": "警告画像を選択"}
        dlg_filters = {"zh": "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)",
                        "zh_tw": "圖片檔案 (*.png *.jpg *.jpeg *.bmp *.gif)",
                        "en": "Image files (*.png *.jpg *.jpeg *.bmp *.gif)",
                        "ja": "画像ファイル (*.png *.jpg *.jpeg *.bmp *.gif)"}
        path, _ = QFileDialog.getOpenFileName(
            self, dlg_titles.get(lang, dlg_titles["zh"]), "",
            dlg_filters.get(lang, dlg_filters["zh"])
        )
        if path:
            self.warning_img_path.setText(path)

    def pick_color(self, key, button):
        lang = self.settings.get("language", "zh")
        color_titles = {"zh": "选择颜色", "zh_tw": "選擇顏色", "en": "Select Color"}
        # V2039：颜色对话框持久化调色板。
        # 入口前：从 settings['custom_palette'] 还原到 QColorDialog 全局 16 格，
        # 这样关闭软件再打开，用户辛辛苦苦调好的色不会丢。
        saved_palette = list(self.settings.get("custom_palette") or [])
        for i in range(16):
            try:
                hex_str = saved_palette[i] if i < len(saved_palette) else ""
                QColorDialog.setCustomColor(i, QColor(hex_str) if hex_str else QColor("#ffffff"))
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        color = QColorDialog.getColor(qcolor(self.settings.get(key)), self,
                                      color_titles.get(lang, color_titles["zh"]))
        # V2039：不论用户按 OK 还是 Cancel，都把当前 16 格里有效的颜色回写到 settings
        # 并立即 save_settings。PySide6 没有 customColors() 列表版 getter，
        # 用 customCount + customColor(i) 循环 16 格读出。
        try:
            cnt = int(QColorDialog.customCount())
            new_palette = []
            for i in range(cnt):
                try:
                    c = QColorDialog.customColor(i)
                except Exception:
                    c = None
                if c is not None and c.isValid():
                    new_palette.append(c.name())
                else:
                    new_palette.append("#ffffff")
            # 长度对齐 16
            while len(new_palette) < 16:
                new_palette.append("#ffffff")
            self.settings["custom_palette"] = new_palette[:16]
            save_settings(self.settings)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        if color.isValid():
            self.settings[key] = color.name()
            button.setText(color.name())
            button.setStyleSheet(f"background:{color.name()}; color:#fff; border-radius:4px;")
            self._emit_changed()

    def reset_defaults(self):
        lang = self.settings.get("language", "zh")
        # V2304：这两个硬编码字典原本漏了 "ja"，日文用户点「恢复默认」会看到英文提示，补齐四语。
        title = {"zh": "恢复默认", "zh_tw": "恢復預設", "en": "Reset to Defaults",
                 "ja": "既定値に戻す"}.get(lang, "Reset to Defaults")
        text = {"zh": "确定要把所有设置恢复为默认吗？此操作会清空当前所有自定义配置（含已禁用的 Buff）。",
                "zh_tw": "確定要把所有設定恢復為預設嗎？此操作會清空目前所有自訂配置（含已停用的 Buff）。",
                "en": "Reset all settings to defaults? This clears all current custom configuration.",
                "ja": "すべての設定を既定値に戻しますか？現在のカスタム設定（無効化したバフを含む）はすべて消去されます。"}.get(lang, "Reset all settings to defaults?")
        reply = QMessageBox.question(self, title, text,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._suppress_emit = True
        self.settings = dict(DEFAULT_SETTINGS)
        # V2039：重置默认时，同时清空「颜色对话框自定义色」持久化 + 同步 Qt 全局
        try:
            self.settings["custom_palette"] = []
            for i in range(16):
                QColorDialog.setCustomColor(i, QColor("#ffffff"))
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        self.lang.setCurrentIndex(max(0, self.lang.findData(DEFAULT_SETTINGS["language"])))
        self.auto_focus_minimize.setChecked(DEFAULT_SETTINGS["auto_focus_minimize"])
        self.resolution_auto_scale.setChecked(DEFAULT_SETTINGS["resolution_auto_scale"])
        self.startup_locked_chk.setChecked(DEFAULT_SETTINGS["startup_locked"])
        self.spike_hide_chk.setChecked(DEFAULT_SETTINGS["spike_hide_when_no_buff"])
        self.spike_hidden_op_spn.setValue(DEFAULT_SETTINGS["spike_hidden_opacity"])
        self.show_spikes_chk.setChecked(DEFAULT_SETTINGS["show_spikes"])
        self.show_bead_chk.setChecked(DEFAULT_SETTINGS["show_bead"])
        self.ooc_hide_chk.setChecked(DEFAULT_SETTINGS["out_of_combat_hide"])
        self.ooc_op_spn.setValue(DEFAULT_SETTINGS["out_of_combat_opacity"])
        self.show_titlebar_status.setChecked(DEFAULT_SETTINGS["show_titlebar_status"])
        self.titlebar_font_size_spn.setValue(DEFAULT_SETTINGS["titlebar_font_size"])
        # V2259 BUGFIX：原本硬编码 findData("left")，不读 DEFAULT_SETTINGS。
        # 玩家当前配置恰好也是 "left" 所以一直没暴露，一旦改成 center/right 就会被冲掉。
        _ta_idx = self.title_align_combo.findData(DEFAULT_SETTINGS.get("title_align", "left"))
        self.title_align_combo.setCurrentIndex(_ta_idx if _ta_idx >= 0 else 0)
        self.status_indent_spn.setValue(DEFAULT_SETTINGS["titlebar_status_indent"])
        self.icon_indent_spn.setValue(DEFAULT_SETTINGS["titlebar_icon_indent"])
        # V2259 BUGFIX：原先是 `group.set_all(True)`——把每个 buff 的觉醒/真谛/秘义三个勾选框
        # 无条件全勾，完全绕过 DEFAULT_SETTINGS。V2257 把玩家配置烘焙进默认值后
        # （buff_mastery 里本来就有 false），这行会把那些 false 全冲成 true，
        # 还会经 orderChanged → get_settings 回写污染 settings.buff_mastery。
        # 改为按烘焙进来的映射逐项还原（映射里没有的键按 False 处理，不会默认全勾）。
        _mastery_map = DEFAULT_SETTINGS.get("buff_mastery", {}) or {}
        for group in getattr(self, "buff_order_groups", {}).values():
            group.apply_mastery_map(_mastery_map)
        self.auto_check_cb.setChecked(DEFAULT_SETTINGS["auto_check_update"])
        self.update_url_le.setText(DEFAULT_SETTINGS["update_check_url"])
        self.download_url_le.setText(DEFAULT_SETTINGS["update_download_url"])
        # V2259 BUGFIX：三项全局快捷键原本硬编码（show="17,75" / lock="" / settings=""），
        # 完全不走 DEFAULT_SETTINGS —— 玩家配好的组合（实测 17,219 / 17,221 / 17,186）会在
        # 「恢复默认」时被冲掉，lock 与 settings 还会被禁用。改为逐项读默认值。
        # 控件前缀 hk_<name> 对应设置键 global_hotkey_<name> / global_hotkey_<name>_enabled。
        for _p in ("hk_show", "hk_lock", "hk_settings"):
            _name = _p[3:]  # hk_show -> show / hk_lock -> lock / hk_settings -> settings
            _d = DEFAULT_SETTINGS.get(f"global_hotkey_{_name}", "")
            _e = bool(DEFAULT_SETTINGS.get(f"global_hotkey_{_name}_enabled", False))
            getattr(self, f"{_p}_enabled").setChecked(_e)
            setattr(self, f"{_p}_combo", _d)
            getattr(self, f"{_p}_lbl").setText(self._combo_to_name(_d) if _d else _tr("未设置"))
        self.skip_version = DEFAULT_SETTINGS.get("skip_version", "")
        # 多buff差异化：按 buff 个数 2/3/4/5 恢复参数
        for cnt in (2, 3, 4, 5):
            c = self.multi_buff_ctrls.get(cnt, {})
            sv = DEFAULT_SETTINGS[f"multi_buff_scale_{cnt}"]; c.get("scale_sl", QSlider()).setValue(sv); c.get("scale_sp", QSpinBox()).setValue(sv)
            hv = DEFAULT_SETTINGS[f"multi_buff_hgap_{cnt}"]; c.get("hgap_sl", QSlider()).setValue(hv); c.get("hgap_sp", QSpinBox()).setValue(hv)
            dv = DEFAULT_SETTINGS[f"multi_buff_dy_{cnt}"]; c.get("dy_sl", QSlider()).setValue(dv); c.get("dy_sp", QSpinBox()).setValue(dv)
            c.get("ext_cb", QCheckBox()).setChecked(DEFAULT_SETTINGS[f"multi_buff_ext_color_{cnt}"])
            c.get("int_cb", QCheckBox()).setChecked(DEFAULT_SETTINGS[f"multi_buff_int_color_{cnt}"])
            mode_cb = c.get("mode_cb")
            if mode_cb:
                mode = DEFAULT_SETTINGS[f"multi_buff_color_mode_{cnt}"]
                mode_cb.setCurrentIndex(0 if mode == "uniform" else 1)
            ms = DEFAULT_SETTINGS[f"multi_buff_mono_span_{cnt}"]
            c.get("mono_span_sl", QSlider()).setValue(ms); c.get("mono_span_sp", QSpinBox()).setValue(ms)
        self.show_buff_name_cb.setChecked(DEFAULT_SETTINGS["show_buff_name"])
        self.buff_name_font_size.setValue(DEFAULT_SETTINGS["buff_name_font_size"])
        self.buff_name_offset_x.setValue(DEFAULT_SETTINGS["buff_name_offset_x"])
        self.buff_name_offset_y.setValue(DEFAULT_SETTINGS["buff_name_offset_y"])
        self.buff_name_bg_width.setValue(DEFAULT_SETTINGS["buff_name_bg_width"])
        self.icon_use_default.setChecked(DEFAULT_SETTINGS["use_default_dodge_icon"])
        # V2257 BUGFIX：这三行原本硬编码 setValue(100)，绕过 DEFAULT_SETTINGS →
        # 「恢复默认」时 core/roll/skill 三个模块的缩放恒为 100%，不会回到烘焙进默认值的
        # 实际数值（实测 core_scale_percent=73，是用户调过的）。已改为与 allbuff/boss 一致，
        # 统一读 DEFAULT_SETTINGS（下方 allbuff_scale_*/boss_scale_* 本来就是这么写的）。
        self.core_scale_slider.setValue(DEFAULT_SETTINGS["core_scale_percent"]); self.core_scale_spin.setValue(DEFAULT_SETTINGS["core_scale_percent"])
        self.roll_scale_slider.setValue(DEFAULT_SETTINGS["roll_scale_percent"]); self.roll_scale_spin.setValue(DEFAULT_SETTINGS["roll_scale_percent"])
        self.skill_scale_slider.setValue(DEFAULT_SETTINGS["skill_scale_percent"]); self.skill_scale_spin.setValue(DEFAULT_SETTINGS["skill_scale_percent"])
        self.scan.setValue(DEFAULT_SETTINGS["scan_ms"])
        self.circle_radius.setValue(DEFAULT_SETTINGS["circle_radius"])
        self.spike_length.setValue(DEFAULT_SETTINGS["spike_length"])
        self.spike_axis_pos.setValue(DEFAULT_SETTINGS["spike_axis_pos_percent"])
        self.spike_width.setValue(DEFAULT_SETTINGS["spike_width"])
        self.spike_waist_pos.setValue(DEFAULT_SETTINGS["spike_waist_pos_percent"])
        self.spike_bead_radius.setValue(DEFAULT_SETTINGS["spike_bead_radius"])
        self.spike_bead_pos.setValue(DEFAULT_SETTINGS["spike_bead_pos_percent"])
        # V2263：3D 效果（尖刺/小球立体感）重置
        self.spike_3d_style_combo.setCurrentIndex(max(0, self.spike_3d_style_combo.findData(DEFAULT_SETTINGS["spike_3d_style"])))
        self.spike_3d_shadow_enabled_chk.setChecked(DEFAULT_SETTINGS["spike_3d_shadow_enabled"])
        self.spike_3d_shadow_offset_x_spn.setValue(DEFAULT_SETTINGS["spike_3d_shadow_offset_x"])
        self.spike_3d_shadow_offset_y_spn.setValue(DEFAULT_SETTINGS["spike_3d_shadow_offset_y"])
        self.spike_3d_shadow_alpha_spn.setValue(DEFAULT_SETTINGS["spike_3d_shadow_alpha"])
        self.spike_3d_outline_enabled_chk.setChecked(DEFAULT_SETTINGS["spike_3d_outline_enabled"])
        self.spike_3d_outline_width_sld.setValue(int(round(DEFAULT_SETTINGS["spike_3d_outline_width"] * 10)))
        self.spike_3d_outline_width_lbl.setText(f"{DEFAULT_SETTINGS['spike_3d_outline_width']:.1f}px")
        self.spike_3d_outline_dark_spn.setValue(DEFAULT_SETTINGS["spike_3d_outline_dark"])
        self.bead_3d_style_combo.setCurrentIndex(max(0, self.bead_3d_style_combo.findData(DEFAULT_SETTINGS["bead_3d_style"])))
        self.bead_3d_light_spn.setValue(DEFAULT_SETTINGS["bead_3d_light"])
        self.bead_3d_dark_spn.setValue(DEFAULT_SETTINGS["bead_3d_dark"])
        self.bead_3d_highlight_offset_sld.setValue(int(round(DEFAULT_SETTINGS["bead_3d_highlight_offset"] * 100)))
        self.bead_3d_highlight_offset_lbl.setText(f"{DEFAULT_SETTINGS['bead_3d_highlight_offset']:.2f}")
        # 同步风格 stack 当前页
        self._spike_3d_style_params_stack.setCurrentIndex(self.spike_3d_style_combo.currentIndex())
        self._bead_3d_params_stack.setCurrentIndex(self.bead_3d_style_combo.currentIndex())
        self.indicator_outline_enabled.setChecked(DEFAULT_SETTINGS["use_indicator_outline"])
        self.indicator_outline_width.setValue(DEFAULT_SETTINGS["indicator_outline_width"])
        self.dh_font_size.setValue(DEFAULT_SETTINGS["dh_font_size"])
        self.dh_text_outline_width.setValue(DEFAULT_SETTINGS["dh_text_outline_width"])
        self.timer_font_size.setValue(DEFAULT_SETTINGS["timer_font_size"])
        self.timer_style.setCurrentIndex(max(0, self.timer_style.findData(DEFAULT_SETTINGS["timer_style"])))
        self.timer_arc_radius.setValue(DEFAULT_SETTINGS["timer_arc_radius_offset"])
        self.icon_path.setText(DEFAULT_SETTINGS["shrimp_img_path"])
        self.icon_scale.setValue(DEFAULT_SETTINGS["dodge_icon_scale_percent"])
        self.circle_pad_title.setValue(DEFAULT_SETTINGS["circle_pad_title"])
        self.core_canvas_w_spn.setValue(DEFAULT_SETTINGS["core_canvas_w"])
        self.core_canvas_h_spn.setValue(DEFAULT_SETTINGS["core_canvas_h"])
        # 闪光（全局统一·跨模块）
        self.flash_scale_spn.setValue(DEFAULT_SETTINGS["flash_scale"])
        self.flash_dur_spn.setValue(DEFAULT_SETTINGS["flash_duration_ms"])
        self.flash_apply_spikes_chk.setChecked(DEFAULT_SETTINGS["flash_apply_spikes"])
        self.flash_apply_skill_ready_chk.setChecked(DEFAULT_SETTINGS["flash_apply_skill_ready"])
        self.flash_apply_dodge_chk.setChecked(DEFAULT_SETTINGS["flash_apply_dodge"])
        # 警告牌（V273 五项可调）
        self.warning_size_spn.setValue(int(DEFAULT_SETTINGS["warning_size_scale"] * 100))
        self.warning_bw_spn.setValue(int(DEFAULT_SETTINGS["warning_outline_width"] * 100))
        self.warning_corner_spn.setValue(DEFAULT_SETTINGS["warning_corner_radius"])
        # V2313：第 6/7 次样式（三角形 / 图片）
        self.warning_mode_combo.setCurrentIndex(max(0, self.warning_mode_combo.findData(DEFAULT_SETTINGS["dodge_warning_mode"])))
        self.warning_img_use_default.setChecked(DEFAULT_SETTINGS["use_default_dodge_warning_icon"])
        self.warning_img_path.setText(DEFAULT_SETTINGS["dodge_warning_image_path"])
        self.warning_img_scale.setValue(DEFAULT_SETTINGS["dodge_warning_icon_scale_percent"])
        self._sync_warning_mode_ui()
        # 翻滚朝向
        self.roll_orientation_combo.setCurrentIndex(max(0, self.roll_orientation_combo.findData(DEFAULT_SETTINGS["roll_orientation"])))
        # 各模块独立屏幕位置（DEFAULT 为基准宽度坐标，按当前分辨率换算成真实像素显示）
        rs = getattr(self.ctrl, "res_scale", 1.0) or 1.0
        self.core_x_spn.setValue(int(round(DEFAULT_SETTINGS["core_window_x"] * rs)))
        self.core_y_spn.setValue(int(round(DEFAULT_SETTINGS["core_window_y"] * rs)))
        self.roll_x_spn.setValue(int(round(DEFAULT_SETTINGS["roll_window_x"] * rs)))
        self.roll_y_spn.setValue(int(round(DEFAULT_SETTINGS["roll_window_y"] * rs)))
        self.skill_x_spn.setValue(int(round(DEFAULT_SETTINGS["skill_window_x"] * rs)))
        self.skill_y_spn.setValue(int(round(DEFAULT_SETTINGS["skill_window_y"] * rs)))
        self.center_offset_x.setValue(DEFAULT_SETTINGS["center_text_offset_x"])
        self.center_offset_y.setValue(DEFAULT_SETTINGS["center_text_offset_y"])
        self.dh_font_size_timer.setValue(DEFAULT_SETTINGS["dh_font_size_timer"])
        self.center_offset_x_timer.setValue(DEFAULT_SETTINGS["center_text_offset_x_timer"])
        self.center_offset_y_timer.setValue(DEFAULT_SETTINGS["center_text_offset_y_timer"])
        self.dh_text_outline_width_timer.setValue(DEFAULT_SETTINGS["dh_text_outline_width_timer"])
        self.roll_icon_opacity_spin.setValue(DEFAULT_SETTINGS["roll_icon_opacity"])
        self.lv7_timer_y_offset.setValue(DEFAULT_SETTINGS["lv7_timer_y_offset"])
        self.lv7_timer_badge_width.setValue(DEFAULT_SETTINGS["lv7_timer_badge_width"])
        self.single_timer_y_offset.setValue(DEFAULT_SETTINGS["single_timer_y_offset"])
        self.single_timer_badge_width.setValue(DEFAULT_SETTINGS["single_timer_badge_width"])
        self.single_timer_font_size.setValue(DEFAULT_SETTINGS["single_timer_font_size"])
        self.timer_center_y.setValue(DEFAULT_SETTINGS["timer_center_offset_y"])
        # 技能冷却
        self.skill_cd_size_spn.setValue(DEFAULT_SETTINGS["skill_cd_size"])
        self.skill_cd_spread_spn.setValue(DEFAULT_SETTINGS["skill_cd_spread"])
        self.skill_cd_font_size_spn.setValue(DEFAULT_SETTINGS["skill_cd_font_size"])
        self.skill_cd_capsule_w_spn.setValue(DEFAULT_SETTINGS["skill_cd_capsule_width"])
        self.skill_cd_timer_offx_spn.setValue(DEFAULT_SETTINGS["skill_cd_timer_offset_x"])
        self.skill_cd_timer_offy_spn.setValue(DEFAULT_SETTINGS["skill_cd_timer_offset_y"])
        self.skill_cd_name_chk.setChecked(DEFAULT_SETTINGS["skill_cd_show_name"])
        self.skill_cd_name_font_spn.setValue(DEFAULT_SETTINGS["skill_cd_name_font_size"])
        self.skill_cd_name_offx_spn.setValue(DEFAULT_SETTINGS["skill_cd_name_offset_x"])
        self.skill_cd_name_offy_spn.setValue(DEFAULT_SETTINGS["skill_cd_name_offset_y"])
        self.skill_cd_name_bgw_spn.setValue(DEFAULT_SETTINGS["skill_cd_name_bg_width"])
        self.skill_cd_border_scale_dspn.setValue(DEFAULT_SETTINGS["skill_cd_border_scale"])
        self.skill_cd_breath_chk.setChecked(DEFAULT_SETTINGS["skill_cd_breath_enabled"])
        self.show_core_module_chk.setChecked(DEFAULT_SETTINGS["show_core_module"])
        self.show_roll_module_chk.setChecked(DEFAULT_SETTINGS["show_roll_module"])
        self.show_skill_module_chk.setChecked(DEFAULT_SETTINGS["show_skill_cd_module"])
        self.show_allbuff_module_chk.setChecked(DEFAULT_SETTINGS["show_allbuff_module"])
        self.show_boss_module_chk.setChecked(DEFAULT_SETTINGS["show_boss_module"])
        self.allbuff_x_spn.setValue(int(round(DEFAULT_SETTINGS["allbuff_window_x"] * rs)))
        self.allbuff_y_spn.setValue(int(round(DEFAULT_SETTINGS["allbuff_window_y"] * rs)))
        self.allbuff_scale_slider.setValue(DEFAULT_SETTINGS["allbuff_scale_percent"])
        self.allbuff_scale_spin.setValue(DEFAULT_SETTINGS["allbuff_scale_percent"])
        self.boss_x_spn.setValue(int(round(DEFAULT_SETTINGS["boss_window_x"] * rs)))
        self.boss_y_spn.setValue(int(round(DEFAULT_SETTINGS["boss_window_y"] * rs)))
        self.boss_scale_slider.setValue(DEFAULT_SETTINGS["boss_scale_percent"])
        self.boss_scale_spin.setValue(DEFAULT_SETTINGS["boss_scale_percent"])
        self.allbuff_per_row_spn.setValue(DEFAULT_SETTINGS["allbuff_per_row"])
        self.allbuff_rows_spn.setValue(DEFAULT_SETTINGS["allbuff_rows"])
        self.allbuff_row_spacing_spn.setValue(DEFAULT_SETTINGS["allbuff_row_spacing"])
        self.allbuff_card_spacing_spn.setValue(DEFAULT_SETTINGS["allbuff_card_spacing"])
        # V2063：排序方式
        _sort_idx = self.allbuff_sort_mode_combo.findData(DEFAULT_SETTINGS["allbuff_sort_mode"])
        if _sort_idx < 0:
            _sort_idx = 0
        self.allbuff_sort_mode_combo.setCurrentIndex(_sort_idx)
        # V2226：行内对齐（默认靠左）
        _align_idx = self.allbuff_row_align_combo.findData(DEFAULT_SETTINGS["allbuff_row_align"])
        if _align_idx < 0:
            _align_idx = 0
        self.allbuff_row_align_combo.setCurrentIndex(_align_idx)
        # V2229：核心/翻滚/能力/主控的 halign/valign/hmargin/vmargin 重置
        self.core_halign_combo.setCurrentIndex(self.core_halign_combo.findData(DEFAULT_SETTINGS["core_halign"]))
        self.core_valign_combo.setCurrentIndex(self.core_valign_combo.findData(DEFAULT_SETTINGS["core_valign"]))
        self.core_hmargin_spn.setValue(DEFAULT_SETTINGS["core_hmargin"])
        self.core_vmargin_spn.setValue(DEFAULT_SETTINGS["core_vmargin"])
        self.roll_halign_combo.setCurrentIndex(self.roll_halign_combo.findData(DEFAULT_SETTINGS["roll_halign"]))
        self.roll_valign_combo.setCurrentIndex(self.roll_valign_combo.findData(DEFAULT_SETTINGS["roll_valign"]))
        self.roll_hmargin_spn.setValue(DEFAULT_SETTINGS["roll_hmargin"])
        self.roll_vmargin_spn.setValue(DEFAULT_SETTINGS["roll_vmargin"])
        self.skill_halign_combo.setCurrentIndex(self.skill_halign_combo.findData(DEFAULT_SETTINGS["skill_halign"]))
        self.skill_valign_combo.setCurrentIndex(self.skill_valign_combo.findData(DEFAULT_SETTINGS["skill_valign"]))
        self.skill_hmargin_spn.setValue(DEFAULT_SETTINGS["skill_hmargin"])
        self.skill_vmargin_spn.setValue(DEFAULT_SETTINGS["skill_vmargin"])
        self.allbuff_hmargin_spn.setValue(DEFAULT_SETTINGS["allbuff_hmargin"])
        self.allbuff_vmargin_spn.setValue(DEFAULT_SETTINGS["allbuff_vmargin"])
        # V2228：整屏对齐（默认 custom）
        _ha_idx = self.allbuff_halign_combo.findData(DEFAULT_SETTINGS["allbuff_halign"])
        if _ha_idx < 0:
            _ha_idx = 0
        self.allbuff_halign_combo.setCurrentIndex(_ha_idx)
        _va_idx = self.allbuff_valign_combo.findData(DEFAULT_SETTINGS["allbuff_valign"])
        if _va_idx < 0:
            _va_idx = 0
        self.allbuff_valign_combo.setCurrentIndex(_va_idx)
        # V2060：元素间距 / 进度条外框粗细
        self.allbuff_element_spacing_spn.setValue(DEFAULT_SETTINGS["allbuff_element_spacing"])
        self.allbuff_row_height_extra_spn.setValue(DEFAULT_SETTINGS["allbuff_row_height_extra"])
        self.allbuff_seq_gone_grace_dspn.setValue(DEFAULT_SETTINGS["allbuff_seq_gone_grace_sec"])
        self.allbuff_bar_frame_thickness_spn.setValue(DEFAULT_SETTINGS["allbuff_bar_frame_thickness"])
        # V2060：倒计时尾声警告（buff）
        self.allbuff_warn_enabled_chk.setChecked(DEFAULT_SETTINGS["allbuff_warn_enabled"])
        self.allbuff_warn_threshold_spn.setValue(DEFAULT_SETTINGS["allbuff_warn_threshold_pct"])
        # V2060：Debuff 警告
        self.allbuff_debuff_warn_enabled_chk.setChecked(DEFAULT_SETTINGS["allbuff_debuff_warn_enabled"])
        self.allbuff_exclude_core_chk.setChecked(DEFAULT_SETTINGS["allbuff_exclude_core"])
        self.allbuff_exclude_infinite_chk.setChecked(DEFAULT_SETTINGS["allbuff_exclude_infinite"])
        self.allbuff_exclude_exclusive_chk.setChecked(DEFAULT_SETTINGS["allbuff_exclude_exclusive"])
        self.allbuff_exclude_mastery_chk.setChecked(DEFAULT_SETTINGS["allbuff_exclude_mastery"])
        self.allbuff_exclude_single_chk.setChecked(DEFAULT_SETTINGS["allbuff_exclude_single"])
        # V2066：门限（monitor 风格数值废料过滤）重置
        # V2216：allbuff_gate_filter_status_id_zero 复选框已移除（filter 固化常闭，无需重置）
        # V2222：gate_status_id_max / gate_sub_id_max 两项已恢复为可配置门限（见上方 reset）；
        #         gate_check_stack_conflict / gate_duration_max 仍为固化（无须重置）。
        self.gate_stacks_max_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_stacks_max"])
        self.gate_stacks_max_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_stacks_max"])
        self.gate_max_stacks_max_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_max_stacks_max"])
        self.gate_max_stacks_max_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_max_stacks_max"])
        # V2222：恢复 status_id / sub_id 上限门限复位
        self.gate_status_id_max_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_status_id_max"])
        self.gate_status_id_max_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_status_id_max"])
        self.gate_sub_id_max_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_sub_id_max"])
        self.gate_sub_id_max_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_sub_id_max"])
        self.gate_min_remaining_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_min_remaining_time"])
        self.gate_min_remaining_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_min_remaining_time"])
        self.gate_min_initial_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_min_initial_time"])
        self.gate_min_initial_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_min_initial_time"])
        # V2084
        self.gate_min_appearance_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_min_appearance_time"])
        self.gate_min_appearance_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_min_appearance_time"])
        # V2243：4 条「可勾选」门限复位（默认全部开启；数值回默认）
        self.allbuff_gate_nan_inf_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_check_nan_inf"])
        self.allbuff_gate_filter_id01_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_filter_status_id_zero_one_infinite_enabled"])
        self.allbuff_gate_min_time_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_check_min_time_enabled"])
        self.allbuff_gate_min_time_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_min_time"])
        self.allbuff_gate_dur_max_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_enabled_duration_max"])
        self.allbuff_gate_rem_gt_init_chk.setChecked(DEFAULT_SETTINGS["allbuff_gate_rem_gt_init_drop"])
        self.allbuff_gate_dur_max_spn.setValue(DEFAULT_SETTINGS["allbuff_gate_duration_max_with_infinite_exemption"])
        # V2200：Boss 模块布局 / 字体 / 衬底 / 警告 / 分类 / 门限复位（位置 / 缩放已在 4631-4634 复位）
        self.boss_per_row_spn.setValue(DEFAULT_SETTINGS["boss_per_row"])
        self.boss_rows_spn.setValue(DEFAULT_SETTINGS["boss_rows"])
        _boss_sort_idx = self.boss_sort_mode_combo.findData(DEFAULT_SETTINGS["boss_sort_mode"])
        if _boss_sort_idx < 0:
            _boss_sort_idx = 0
        self.boss_sort_mode_combo.setCurrentIndex(_boss_sort_idx)
        # V2226：行内对齐（默认靠左）
        _boss_align_idx = self.boss_row_align_combo.findData(DEFAULT_SETTINGS["boss_row_align"])
        if _boss_align_idx < 0:
            _boss_align_idx = 0
        self.boss_row_align_combo.setCurrentIndex(_boss_align_idx)
        # V2229：boss 的 hmargin/vmargin 重置
        self.boss_hmargin_spn.setValue(DEFAULT_SETTINGS["boss_hmargin"])
        self.boss_vmargin_spn.setValue(DEFAULT_SETTINGS["boss_vmargin"])
        # V2228：整屏对齐（默认 custom）
        _boss_ha_idx = self.boss_halign_combo.findData(DEFAULT_SETTINGS["boss_halign"])
        if _boss_ha_idx < 0:
            _boss_ha_idx = 0
        self.boss_halign_combo.setCurrentIndex(_boss_ha_idx)
        _boss_va_idx = self.boss_valign_combo.findData(DEFAULT_SETTINGS["boss_valign"])
        if _boss_va_idx < 0:
            _boss_va_idx = 0
        self.boss_valign_combo.setCurrentIndex(_boss_va_idx)
        self.boss_row_spacing_spn.setValue(DEFAULT_SETTINGS["boss_row_spacing"])
        self.boss_card_spacing_spn.setValue(DEFAULT_SETTINGS["boss_card_spacing"])
        self.boss_element_spacing_spn.setValue(DEFAULT_SETTINGS["boss_element_spacing"])
        self.boss_row_height_extra_spn.setValue(DEFAULT_SETTINGS["boss_row_height_extra"])
        self.boss_seq_gone_grace_dspn.setValue(DEFAULT_SETTINGS["boss_seq_gone_grace_sec"])
        self.boss_bar_frame_thickness_spn.setValue(DEFAULT_SETTINGS["boss_bar_frame_thickness"])
        self.boss_warn_enabled_chk.setChecked(DEFAULT_SETTINGS["boss_warn_enabled"])
        self.boss_warn_threshold_spn.setValue(DEFAULT_SETTINGS["boss_warn_threshold_pct"])
        self.boss_debuff_warn_enabled_chk.setChecked(DEFAULT_SETTINGS["boss_debuff_warn_enabled"])
        self.boss_name_font_size_spn.setValue(DEFAULT_SETTINGS["boss_name_font_size"])
        self.boss_stacks_font_size_spn.setValue(DEFAULT_SETTINGS["boss_stacks_font_size"])
        self.boss_time_font_size_spn.setValue(DEFAULT_SETTINGS["boss_time_font_size"])
        self.boss_bar_width_spn.setValue(DEFAULT_SETTINGS["boss_bar_width"])
        self.boss_bar_height_spn.setValue(DEFAULT_SETTINGS["boss_bar_height"])
        self.boss_backing_width_spn.setValue(DEFAULT_SETTINGS["boss_backing_width"])
        self.boss_backing_height_spn.setValue(DEFAULT_SETTINGS["boss_backing_height"])
        self.boss_canvas_bg_opacity_spn.setValue(DEFAULT_SETTINGS["boss_canvas_bg_opacity"])
        # V2210：分类显示控件已删除，无须复位（settings 键保留以兼容旧 config）
        # 门限复位
        # V2216：boss_gate_filter_status_id_zero 复选框已移除（filter 固化常闭，无需重置）
        # V2222：boss_gate_status_id_max / boss_gate_sub_id_max 两项已恢复为可配置门限（见上方 reset）；
        #         boss_gate_check_stack_conflict / boss_gate_duration_max 仍为固化（无须重置）。
        self.boss_gate_stacks_max_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_stacks_max"])
        self.boss_gate_stacks_max_spn.setValue(DEFAULT_SETTINGS["boss_gate_stacks_max"])
        self.boss_gate_max_stacks_max_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_max_stacks_max"])
        self.boss_gate_max_stacks_max_spn.setValue(DEFAULT_SETTINGS["boss_gate_max_stacks_max"])
        # V2222：恢复 status_id / sub_id 上限门限复位
        self.boss_gate_status_id_max_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_status_id_max"])
        self.boss_gate_status_id_max_spn.setValue(DEFAULT_SETTINGS["boss_gate_status_id_max"])
        self.boss_gate_sub_id_max_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_sub_id_max"])
        self.boss_gate_sub_id_max_spn.setValue(DEFAULT_SETTINGS["boss_gate_sub_id_max"])
        self.boss_gate_min_remaining_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_min_remaining_time"])
        self.boss_gate_min_remaining_spn.setValue(DEFAULT_SETTINGS["boss_gate_min_remaining_time"])
        self.boss_gate_min_initial_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_min_initial_time"])
        self.boss_gate_min_initial_spn.setValue(DEFAULT_SETTINGS["boss_gate_min_initial_time"])
        self.boss_gate_min_appearance_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_min_appearance_time"])
        self.boss_gate_min_appearance_spn.setValue(DEFAULT_SETTINGS["boss_gate_min_appearance_time"])
        # V2243：Boss 4 条「可勾选」门限复位（与主控对称；默认全部开启；数值回默认）
        self.boss_gate_nan_inf_chk.setChecked(DEFAULT_SETTINGS["boss_gate_check_nan_inf"])
        self.boss_gate_filter_id01_chk.setChecked(DEFAULT_SETTINGS["boss_gate_filter_status_id_zero_one_infinite_enabled"])
        self.boss_gate_min_time_chk.setChecked(DEFAULT_SETTINGS["boss_gate_check_min_time_enabled"])
        self.boss_gate_min_time_spn.setValue(DEFAULT_SETTINGS["boss_gate_min_time"])
        self.boss_gate_dur_max_chk.setChecked(DEFAULT_SETTINGS["boss_gate_enabled_duration_max"])
        self.boss_gate_rem_gt_init_chk.setChecked(DEFAULT_SETTINGS["boss_gate_rem_gt_init_drop"])
        self.boss_gate_dur_max_spn.setValue(DEFAULT_SETTINGS["boss_gate_duration_max_with_infinite_exemption"])
        # V2117：NaN/Inf、ID=0 排除永续、隐藏 0.0/0.0、remaining/initial 任一 < 0 四门限已固化（不再有 UI 开关/控件）
        # V2065：画布背景不透明度
        self.allbuff_canvas_bg_opacity_spn.setValue(DEFAULT_SETTINGS["allbuff_canvas_bg_opacity"])
        self.allbuff_name_font_size_spn.setValue(DEFAULT_SETTINGS["allbuff_name_font_size"])
        self.allbuff_stacks_font_size_spn.setValue(DEFAULT_SETTINGS["allbuff_stacks_font_size"])
        self.allbuff_time_font_size_spn.setValue(DEFAULT_SETTINGS["allbuff_time_font_size"])
        self.allbuff_bar_width_spn.setValue(DEFAULT_SETTINGS["allbuff_bar_width"])
        self.allbuff_bar_height_spn.setValue(DEFAULT_SETTINGS["allbuff_bar_height"])
        self.allbuff_backing_width_spn.setValue(DEFAULT_SETTINGS["allbuff_backing_width"])
        self.allbuff_backing_height_spn.setValue(DEFAULT_SETTINGS["allbuff_backing_height"])
        self.skill_cd_breath_freq_dspn.setValue(DEFAULT_SETTINGS["skill_cd_breath_freq"])
        self.skill_cd_breath_soft_dspn.setValue(DEFAULT_SETTINGS["skill_cd_breath_soft"])
        self.skill_cd_breath_scale_dspn.setValue(DEFAULT_SETTINGS["skill_cd_breath_scale"])
        for key, btn in self.color_buttons.items():
            val = DEFAULT_SETTINGS.get(key, "#ffffff")
            self.settings[key] = val
            btn.setText(val)
            btn.setStyleSheet(f"background:{val}; color:#fff; border-radius:4px;")
        for key, spin in self.opacity_spins.items():
            val = DEFAULT_SETTINGS.get(f"{key}_opacity", 100)
            self.settings[f"{key}_opacity"] = val
            spin.setValue(val)
        # ── V2304：调试数据（逐控件读 DEFAULT_SETTINGS，禁硬编码）────────────
        self.debug_data_enabled_chk.setChecked(DEFAULT_SETTINGS["debug_data_enabled"])
        self.debug_text_le.setText(DEFAULT_SETTINGS["debug_text"])
        self.debug_countdown_spn.setValue(DEFAULT_SETTINGS["debug_countdown"])
        _i = self.debug_status_cmb.findData(DEFAULT_SETTINGS["debug_status"])
        self.debug_status_cmb.setCurrentIndex(_i if _i >= 0 else 0)
        self.debug_in_combat_chk.setChecked(DEFAULT_SETTINGS["debug_in_combat"])
        _i = self.debug_mastery_cmb.findData(DEFAULT_SETTINGS["debug_mastery"])
        self.debug_mastery_cmb.setCurrentIndex(_i if _i >= 0 else 0)
        self.debug_core_count_spn.setValue(DEFAULT_SETTINGS["debug_core_buff_count"])
        self.debug_core_single_chk.setChecked(DEFAULT_SETTINGS["debug_core_single_layer"])
        self.debug_core_full_chk.setChecked(DEFAULT_SETTINGS["debug_core_full_stacks"])
        self.debug_core_stacks_spn.setValue(DEFAULT_SETTINGS["debug_core_stacks"])
        self.debug_core_max_spn.setValue(DEFAULT_SETTINGS["debug_core_max_stacks"])
        self.debug_core_awk_chk.setChecked(DEFAULT_SETTINGS["debug_core_awakening"])
        self.debug_core_truth_chk.setChecked(DEFAULT_SETTINGS["debug_core_truth"])
        self.debug_core_secret_chk.setChecked(DEFAULT_SETTINGS["debug_core_secret"])
        self.debug_allbuff_normal_spn.setValue(DEFAULT_SETTINGS["debug_allbuff_normal"])
        self.debug_allbuff_debuff_spn.setValue(DEFAULT_SETTINGS["debug_allbuff_debuff"])
        self.debug_allbuff_perma_spn.setValue(DEFAULT_SETTINGS["debug_allbuff_perma"])
        self.debug_allbuff_coda_spn.setValue(DEFAULT_SETTINGS["debug_allbuff_coda"])
        self.debug_allbuff_stacks_spn.setValue(DEFAULT_SETTINGS["debug_allbuff_stacks"])
        self.debug_allbuff_max_spn.setValue(DEFAULT_SETTINGS["debug_allbuff_max_stacks"])
        self.debug_boss_normal_spn.setValue(DEFAULT_SETTINGS["debug_boss_normal"])
        self.debug_boss_debuff_spn.setValue(DEFAULT_SETTINGS["debug_boss_debuff"])
        self.debug_boss_perma_spn.setValue(DEFAULT_SETTINGS["debug_boss_perma"])
        self.debug_boss_coda_spn.setValue(DEFAULT_SETTINGS["debug_boss_coda"])
        self.debug_boss_stacks_spn.setValue(DEFAULT_SETTINGS["debug_boss_stacks"])
        self.debug_boss_max_spn.setValue(DEFAULT_SETTINGS["debug_boss_max_stacks"])
        self.debug_skill_count_spn.setValue(DEFAULT_SETTINGS["debug_skill_count"])
        self.debug_skill_ready_spn.setValue(DEFAULT_SETTINGS["debug_skill_ready_count"])
        self.debug_skill_cdmax_spn.setValue(DEFAULT_SETTINGS["debug_skill_cd_max"])
        self.debug_dodge_spn.setValue(DEFAULT_SETTINGS["debug_dodge_count"])
        self._suppress_emit = False
        self._emit_changed()

    def get_settings(self):
        self.settings["language"] = self.lang.currentData() or "zh"
        self.settings["auto_focus_minimize"] = self.auto_focus_minimize.isChecked()
        self.settings["resolution_auto_scale"] = self.resolution_auto_scale.isChecked()
        self.settings["startup_locked"] = self.startup_locked_chk.isChecked()
        self.settings["spike_hide_when_no_buff"] = self.spike_hide_chk.isChecked()
        self.settings["spike_hidden_opacity"] = self.spike_hidden_op_spn.value()
        self.settings["show_spikes"] = self.show_spikes_chk.isChecked()
        self.settings["show_bead"] = self.show_bead_chk.isChecked()
        self.settings["out_of_combat_hide"] = self.ooc_hide_chk.isChecked()
        self.settings["out_of_combat_opacity"] = self.ooc_op_spn.value()
        self.settings["show_titlebar_status"] = self.show_titlebar_status.isChecked()
        self.settings["titlebar_font_size"] = self.titlebar_font_size_spn.value()
        self.settings["title_align"] = self.title_align_combo.currentData()
        self.settings["titlebar_status_indent"] = self.status_indent_spn.value()
        self.settings["titlebar_icon_indent"] = self.icon_indent_spn.value()
        # Buff 顺位 + 专精勾选：从各组拖拽列表/勾选框读取
        order = {}
        mastery = {}
        for group in getattr(self, "buff_order_groups", {}).values():
            order.update(group.get_order())
            mastery.update(group.get_mastery())
        self.settings["buff_order"] = order
        self.settings["buff_mastery"] = mastery
        # 兼容性派生：有任意勾选视为启用（供旧逻辑/外部引用）
        self.settings["buff_enabled"] = {k: any(v.values()) if isinstance(v, dict) else bool(v) for k, v in mastery.items()}
        # 多buff差异化：按 buff 个数 2/3/4/5 写入参数
        for cnt in (2, 3, 4, 5):
            c = self.multi_buff_ctrls.get(cnt, {})
            self.settings[f"multi_buff_scale_{cnt}"] = c.get("scale_sp", QSpinBox()).value()
            self.settings[f"multi_buff_hgap_{cnt}"] = c.get("hgap_sp", QSpinBox()).value()
            self.settings[f"multi_buff_dy_{cnt}"] = c.get("dy_sp", QSpinBox()).value()
            self.settings[f"multi_buff_ext_color_{cnt}"] = c.get("ext_cb", QCheckBox()).isChecked()
            self.settings[f"multi_buff_int_color_{cnt}"] = c.get("int_cb", QCheckBox()).isChecked()
            mode_cb = c.get("mode_cb")
            self.settings[f"multi_buff_color_mode_{cnt}"] = (mode_cb.currentData() if mode_cb else "uniform")
            self.settings[f"multi_buff_mono_span_{cnt}"] = c.get("mono_span_sp", QSpinBox()).value()
        self.settings["show_core_module"] = self.show_core_module_chk.isChecked()
        self.settings["show_roll_module"] = self.show_roll_module_chk.isChecked()
        self.settings["show_skill_cd_module"] = self.show_skill_module_chk.isChecked()
        self.settings["show_buff_name"] = self.show_buff_name_cb.isChecked()
        self.settings["buff_name_font_size"] = self.buff_name_font_size.value()
        self.settings["buff_name_offset_x"] = self.buff_name_offset_x.value()
        self.settings["buff_name_offset_y"] = self.buff_name_offset_y.value()
        self.settings["buff_name_bg_width"] = self.buff_name_bg_width.value()
        # 技能冷却
        self.settings["skill_cd_size"] = self.skill_cd_size_spn.value()
        self.settings["skill_cd_spread"] = self.skill_cd_spread_spn.value()
        self.settings["skill_cd_font_size"] = self.skill_cd_font_size_spn.value()
        self.settings["skill_cd_capsule_width"] = self.skill_cd_capsule_w_spn.value()
        self.settings["skill_cd_timer_offset_x"] = self.skill_cd_timer_offx_spn.value()
        self.settings["skill_cd_timer_offset_y"] = self.skill_cd_timer_offy_spn.value()
        self.settings["skill_cd_bg_opacity"] = self.skill_cd_bg_opacity_sl.value()
        self.settings["skill_cd_sector_opacity"] = self.skill_cd_sector_opacity_sl.value()
        self.settings["skill_cd_border_opacity"] = self.skill_cd_border_opacity_sl.value()
        self.settings["skill_cd_border_scale"] = self.skill_cd_border_scale_dspn.value()
        self.settings["skill_cd_capsule_opacity"] = self.skill_cd_capsule_opacity_sl.value()
        self.settings["skill_cd_breath_enabled"] = self.skill_cd_breath_chk.isChecked()
        self.settings["skill_cd_breath_freq"] = self.skill_cd_breath_freq_dspn.value()
        self.settings["skill_cd_breath_soft"] = self.skill_cd_breath_soft_dspn.value()
        self.settings["skill_cd_breath_scale"] = self.skill_cd_breath_scale_dspn.value()
        # 注：能力冷却模块的显隐已由全局「模块显示」统一控制（show_skill_cd_module），
        # 此处不再单独写 show_skill_cd。
        self.settings["flash_scale"] = self.flash_scale_spn.value()
        self.settings["flash_duration_ms"] = self.flash_dur_spn.value()
        self.settings["flash_apply_spikes"] = self.flash_apply_spikes_chk.isChecked()
        self.settings["flash_apply_skill_ready"] = self.flash_apply_skill_ready_chk.isChecked()
        self.settings["flash_apply_dodge"] = self.flash_apply_dodge_chk.isChecked()
        # 警告牌（V273 五项可调）
        self.settings["warning_size_scale"] = self.warning_size_spn.value() / 100.0
        self.settings["warning_outline_width"] = self.warning_bw_spn.value() / 100.0
        self.settings["warning_corner_radius"] = self.warning_corner_spn.value()
        # V2313：第 6/7 次样式（三角形 / 图片）
        self.settings["dodge_warning_mode"] = self.warning_mode_combo.currentData()
        self.settings["use_default_dodge_warning_icon"] = self.warning_img_use_default.isChecked()
        self.settings["dodge_warning_image_path"] = self.warning_img_path.text().strip()
        self.settings["dodge_warning_icon_scale_percent"] = self.warning_img_scale.value()
        self.settings["skill_cd_show_name"] = self.skill_cd_name_chk.isChecked()
        self.settings["skill_cd_name_font_size"] = self.skill_cd_name_font_spn.value()
        self.settings["skill_cd_name_offset_x"] = self.skill_cd_name_offx_spn.value()
        self.settings["skill_cd_name_offset_y"] = self.skill_cd_name_offy_spn.value()
        self.settings["skill_cd_name_bg_width"] = self.skill_cd_name_bgw_spn.value()
        self.settings["use_default_dodge_icon"] = self.icon_use_default.isChecked()
        self.settings["roll_orientation"] = self.roll_orientation_combo.currentData()
        self.settings["buff_order_direction"] = self.buff_order_direction_combo.currentData() if self.buff_order_direction_combo.count() else "ltr"
        # 各模块独立屏幕位置（对话框里显示/输入的是「当前分辨率真实像素」，
        # 保存时按 res_scale 归一化到基准宽度，使位置随分辨率等比迁移）
        rs = getattr(self.ctrl, "res_scale", 1.0) or 1.0
        self.settings["core_window_x"] = round(self.core_x_spn.value() / rs)
        self.settings["core_window_y"] = round(self.core_y_spn.value() / rs)
        self.settings["roll_window_x"] = round(self.roll_x_spn.value() / rs)
        self.settings["roll_window_y"] = round(self.roll_y_spn.value() / rs)
        self.settings["skill_window_x"] = round(self.skill_x_spn.value() / rs)
        self.settings["skill_window_y"] = round(self.skill_y_spn.value() / rs)
        self.settings["core_scale_percent"] = self.core_scale_spin.value()
        self.settings["roll_scale_percent"] = self.roll_scale_spin.value()
        self.settings["skill_scale_percent"] = self.skill_scale_spin.value()
        # 全Buff显示模块（第四模块）
        self.settings["show_allbuff_module"] = self.show_allbuff_module_chk.isChecked()
        self.settings["show_boss_module"] = self.show_boss_module_chk.isChecked()
        self.settings["allbuff_window_x"] = round(self.allbuff_x_spn.value() / rs)
        self.settings["allbuff_window_y"] = round(self.allbuff_y_spn.value() / rs)
        self.settings["allbuff_scale_percent"] = self.allbuff_scale_spin.value()
        self.settings["boss_window_x"] = round(self.boss_x_spn.value() / rs)
        self.settings["boss_window_y"] = round(self.boss_y_spn.value() / rs)
        self.settings["boss_scale_percent"] = self.boss_scale_spin.value()
        # V2200：Boss 模块布局 / 字体 / 衬底 / 警告（位置 / 缩放已在上方）
        self.settings["boss_per_row"] = self.boss_per_row_spn.value()
        self.settings["boss_rows"] = self.boss_rows_spn.value()
        self.settings["boss_sort_mode"] = self.boss_sort_mode_combo.currentData() or "id_asc"
        # V2226：行内对齐（靠左 / 居中 / 靠右，默认靠左）
        self.settings["boss_row_align"] = self.boss_row_align_combo.currentData() or "left"
        # V2229：boss 的 halign/valign/hmargin/vmargin 写入
        self.settings["boss_halign"] = self.boss_halign_combo.currentData() or "custom"
        self.settings["boss_valign"] = self.boss_valign_combo.currentData() or "custom"
        self.settings["boss_hmargin"] = int(self.boss_hmargin_spn.value())
        self.settings["boss_vmargin"] = int(self.boss_vmargin_spn.value())
        self.settings["boss_row_spacing"] = self.boss_row_spacing_spn.value()
        self.settings["boss_card_spacing"] = self.boss_card_spacing_spn.value()
        self.settings["boss_element_spacing"] = self.boss_element_spacing_spn.value()
        self.settings["boss_row_height_extra"] = self.boss_row_height_extra_spn.value()
        self.settings["boss_seq_gone_grace_sec"] = float(self.boss_seq_gone_grace_dspn.value())
        self.settings["boss_bar_frame_thickness"] = self.boss_bar_frame_thickness_spn.value()
        self.settings["boss_warn_enabled"] = self.boss_warn_enabled_chk.isChecked()
        self.settings["boss_warn_threshold_pct"] = self.boss_warn_threshold_spn.value()
        self.settings["boss_debuff_warn_enabled"] = self.boss_debuff_warn_enabled_chk.isChecked()
        self.settings["boss_name_font_size"] = self.boss_name_font_size_spn.value()
        self.settings["boss_stacks_font_size"] = self.boss_stacks_font_size_spn.value()
        self.settings["boss_time_font_size"] = self.boss_time_font_size_spn.value()
        self.settings["boss_bar_width"] = self.boss_bar_width_spn.value()
        self.settings["boss_bar_height"] = self.boss_bar_height_spn.value()
        self.settings["boss_backing_width"] = self.boss_backing_width_spn.value()
        self.settings["boss_backing_height"] = self.boss_backing_height_spn.value()
        self.settings["boss_canvas_bg_opacity"] = self.boss_canvas_bg_opacity_spn.value()
        # V2210：分类显示控件已删除，但 settings 键仍保留（兼容旧 config / 玩家手动改 json）
        self.settings["allbuff_per_row"] = self.allbuff_per_row_spn.value()
        self.settings["allbuff_rows"] = self.allbuff_rows_spn.value()
        self.settings["allbuff_sort_mode"] = self.allbuff_sort_mode_combo.currentData() or "id_asc"
        # V2226：行内对齐（靠左 / 居中 / 靠右，默认靠左）
        self.settings["allbuff_row_align"] = self.allbuff_row_align_combo.currentData() or "left"
        # V2229：核心/翻滚/能力/主控的 halign/valign/hmargin/vmargin 写入
        for _k in ("core", "roll", "skill"):
            self.settings[f"{_k}_halign"] = getattr(self, f"{_k}_halign_combo").currentData() or "custom"
            self.settings[f"{_k}_valign"] = getattr(self, f"{_k}_valign_combo").currentData() or "custom"
            self.settings[f"{_k}_hmargin"] = int(getattr(self, f"{_k}_hmargin_spn").value())
            self.settings[f"{_k}_vmargin"] = int(getattr(self, f"{_k}_vmargin_spn").value())
        self.settings["allbuff_halign"] = self.allbuff_halign_combo.currentData() or "custom"
        self.settings["allbuff_valign"] = self.allbuff_valign_combo.currentData() or "custom"
        self.settings["allbuff_hmargin"] = int(self.allbuff_hmargin_spn.value())
        self.settings["allbuff_vmargin"] = int(self.allbuff_vmargin_spn.value())
        self.settings["allbuff_row_spacing"] = self.allbuff_row_spacing_spn.value()
        self.settings["allbuff_card_spacing"] = self.allbuff_card_spacing_spn.value()
        # V2060：元素统一间距 + 进度条外框粗细
        self.settings["allbuff_element_spacing"] = self.allbuff_element_spacing_spn.value()
        self.settings["allbuff_row_height_extra"] = self.allbuff_row_height_extra_spn.value()
        self.settings["allbuff_seq_gone_grace_sec"] = float(self.allbuff_seq_gone_grace_dspn.value())
        self.settings["allbuff_bar_frame_thickness"] = self.allbuff_bar_frame_thickness_spn.value()
        # V2060：倒计时尾声警告（buff）
        self.settings["allbuff_warn_enabled"] = self.allbuff_warn_enabled_chk.isChecked()
        self.settings["allbuff_warn_threshold_pct"] = self.allbuff_warn_threshold_spn.value()
        # V2060：Debuff 配色（4 色）+ debuff 警告三件套
        self.settings["allbuff_debuff_warn_enabled"] = self.allbuff_debuff_warn_enabled_chk.isChecked()
        self.settings["allbuff_exclude_core"] = self.allbuff_exclude_core_chk.isChecked()
        self.settings["allbuff_exclude_infinite"] = self.allbuff_exclude_infinite_chk.isChecked()
        self.settings["allbuff_exclude_exclusive"] = self.allbuff_exclude_exclusive_chk.isChecked()
        self.settings["allbuff_exclude_mastery"] = self.allbuff_exclude_mastery_chk.isChecked()
        self.settings["allbuff_exclude_single"] = self.allbuff_exclude_single_chk.isChecked()
        # V2066：门限（monitor 风格数值废料过滤）保存
        # V2216：allbuff_gate_filter_status_id_zero 复选框已移除，不再收集；同时清理旧 key
        # V2217：4 个门限（status_id/sub_id/duration/stack_conflict）固化为 render 默认值，不再从 UI 读；
        #                  同时主动 pop 玩家旧 config 里这 12 个键，避免污染
        for _obs in ("allbuff_gate_check_stack_conflict",
                    "allbuff_gate_duration_max"):
            self.settings.pop(_obs, None)
        self.settings["allbuff_gate_enabled_stacks_max"] = self.gate_stacks_max_chk.isChecked()
        self.settings["allbuff_gate_stacks_max"] = int(self.gate_stacks_max_spn.value())
        self.settings["allbuff_gate_enabled_max_stacks_max"] = self.gate_max_stacks_max_chk.isChecked()
        self.settings["allbuff_gate_max_stacks_max"] = int(self.gate_max_stacks_max_spn.value())
        # V2222：status_id / sub_id 上限门限收集（恢复为可配置，不再 pop）
        self.settings["allbuff_gate_enabled_status_id_max"] = self.gate_status_id_max_chk.isChecked()
        self.settings["allbuff_gate_status_id_max"] = int(self.gate_status_id_max_spn.value())
        self.settings["allbuff_gate_enabled_sub_id_max"] = self.gate_sub_id_max_chk.isChecked()
        self.settings["allbuff_gate_sub_id_max"] = int(self.gate_sub_id_max_spn.value())
        self.settings["allbuff_gate_enabled_min_remaining_time"] = self.gate_min_remaining_chk.isChecked()
        self.settings["allbuff_gate_min_remaining_time"] = float(self.gate_min_remaining_spn.value())
        self.settings["allbuff_gate_enabled_min_initial_time"] = self.gate_min_initial_chk.isChecked()
        self.settings["allbuff_gate_min_initial_time"] = float(self.gate_min_initial_spn.value())
        # V2084
        self.settings["allbuff_gate_enabled_min_appearance_time"] = self.gate_min_appearance_chk.isChecked()
        self.settings["allbuff_gate_min_appearance_time"] = float(self.gate_min_appearance_spn.value())
        # V2243：4 条「可勾选」门限——从 UI 控件读取勾选状态 + 数值（玩家可关任意一条以诊断行为）。
        self.settings["allbuff_gate_check_nan_inf"] = self.allbuff_gate_nan_inf_chk.isChecked()
        self.settings["allbuff_gate_filter_status_id_zero_one_infinite_enabled"] = self.allbuff_gate_filter_id01_chk.isChecked()
        self.settings["allbuff_gate_check_min_time_enabled"] = self.allbuff_gate_min_time_chk.isChecked()
        self.settings["allbuff_gate_min_time"] = float(self.allbuff_gate_min_time_spn.value())
        self.settings["allbuff_gate_enabled_duration_max"] = self.allbuff_gate_dur_max_chk.isChecked()
        self.settings["allbuff_gate_rem_gt_init_drop"] = self.allbuff_gate_rem_gt_init_chk.isChecked()
        self.settings["allbuff_gate_duration_max_with_infinite_exemption"] = float(self.allbuff_gate_dur_max_spn.value())
        # V2200：Boss 门限（与 allbuff 同结构，独立 boss_gate_* 键）
        # V2216：boss_gate_filter_status_id_zero 复选框已移除，不再收集；同时清理旧 key
        # V2217：4 个门限（status_id/sub_id/duration/stack_conflict）固化为 render 默认值，不再从 UI 读；
        #                  同时主动 pop 玩家旧 config 里这 12 个键
        self.settings.pop("boss_gate_filter_status_id_zero", None)
        for _obs in ("boss_gate_check_stack_conflict",
                    "boss_gate_duration_max"):
            self.settings.pop(_obs, None)
        self.settings["boss_gate_enabled_stacks_max"] = self.boss_gate_stacks_max_chk.isChecked()
        self.settings["boss_gate_stacks_max"] = int(self.boss_gate_stacks_max_spn.value())
        self.settings["boss_gate_enabled_max_stacks_max"] = self.boss_gate_max_stacks_max_chk.isChecked()
        self.settings["boss_gate_max_stacks_max"] = int(self.boss_gate_max_stacks_max_spn.value())
        # V2222：status_id / sub_id 上限门限收集（恢复为可配置，不再 pop）
        self.settings["boss_gate_enabled_status_id_max"] = self.boss_gate_status_id_max_chk.isChecked()
        self.settings["boss_gate_status_id_max"] = int(self.boss_gate_status_id_max_spn.value())
        self.settings["boss_gate_enabled_sub_id_max"] = self.boss_gate_sub_id_max_chk.isChecked()
        self.settings["boss_gate_sub_id_max"] = int(self.boss_gate_sub_id_max_spn.value())
        self.settings["boss_gate_enabled_min_remaining_time"] = self.boss_gate_min_remaining_chk.isChecked()
        self.settings["boss_gate_min_remaining_time"] = float(self.boss_gate_min_remaining_spn.value())
        self.settings["boss_gate_enabled_min_initial_time"] = self.boss_gate_min_initial_chk.isChecked()
        self.settings["boss_gate_min_initial_time"] = float(self.boss_gate_min_initial_spn.value())
        # V2084
        self.settings["boss_gate_enabled_min_appearance_time"] = self.boss_gate_min_appearance_chk.isChecked()
        self.settings["boss_gate_min_appearance_time"] = float(self.boss_gate_min_appearance_spn.value())
        # V2243：Boss 4 条「可勾选」门限——与主控对称，从 UI 控件读取（key 用 boss_gate_ 前缀）。
        self.settings["boss_gate_check_nan_inf"] = self.boss_gate_nan_inf_chk.isChecked()
        self.settings["boss_gate_filter_status_id_zero_one_infinite_enabled"] = self.boss_gate_filter_id01_chk.isChecked()
        self.settings["boss_gate_check_min_time_enabled"] = self.boss_gate_min_time_chk.isChecked()
        self.settings["boss_gate_min_time"] = float(self.boss_gate_min_time_spn.value())
        self.settings["boss_gate_enabled_duration_max"] = self.boss_gate_dur_max_chk.isChecked()
        self.settings["boss_gate_rem_gt_init_drop"] = self.boss_gate_rem_gt_init_chk.isChecked()
        self.settings["boss_gate_duration_max_with_infinite_exemption"] = float(self.boss_gate_dur_max_spn.value())
        # V2065：画布背景不透明度
        self.settings["allbuff_canvas_bg_opacity"] = self.allbuff_canvas_bg_opacity_spn.value()
        self.settings["allbuff_name_font_size"] = self.allbuff_name_font_size_spn.value()
        self.settings["allbuff_stacks_font_size"] = self.allbuff_stacks_font_size_spn.value()
        self.settings["allbuff_time_font_size"] = self.allbuff_time_font_size_spn.value()
        self.settings["allbuff_bar_width"] = self.allbuff_bar_width_spn.value()
        self.settings["allbuff_bar_height"] = self.allbuff_bar_height_spn.value()
        self.settings["allbuff_backing_width"] = self.allbuff_backing_width_spn.value()
        self.settings["allbuff_backing_height"] = self.allbuff_backing_height_spn.value()
        self.settings["scan_ms"] = self.scan.value()
        self.settings["settings_schema_version"] = SETTINGS_SCHEMA_VERSION
        self.settings["circle_radius"] = self.circle_radius.value()
        self.settings["spike_length"] = self.spike_length.value()
        self.settings["spike_axis_pos_percent"] = self.spike_axis_pos.value()
        self.settings["spike_width"] = self.spike_width.value()
        self.settings["spike_waist_pos_percent"] = self.spike_waist_pos.value()
        self.settings["spike_bead_radius"] = self.spike_bead_radius.value()
        self.settings["spike_bead_pos_percent"] = self.spike_bead_pos.value()
        # V2263：3D 效果（尖刺/小球立体感）
        self.settings["spike_3d_style"] = self.spike_3d_style_combo.currentData() or "flat"
        self.settings["spike_3d_shadow_enabled"] = self.spike_3d_shadow_enabled_chk.isChecked()
        self.settings["spike_3d_shadow_offset_x"] = self.spike_3d_shadow_offset_x_spn.value()
        self.settings["spike_3d_shadow_offset_y"] = self.spike_3d_shadow_offset_y_spn.value()
        self.settings["spike_3d_shadow_alpha"] = self.spike_3d_shadow_alpha_spn.value()
        self.settings["spike_3d_outline_enabled"] = self.spike_3d_outline_enabled_chk.isChecked()
        self.settings["spike_3d_outline_width"] = self.spike_3d_outline_width_sld.value() / 10.0
        self.settings["spike_3d_outline_dark"] = self.spike_3d_outline_dark_spn.value()
        self.settings["spike_3d_twotone_light"] = self.spike_3d_twotone_light_spn.value()
        self.settings["spike_3d_twotone_dark"] = self.spike_3d_twotone_dark_spn.value()
        self.settings["bead_3d_style"] = self.bead_3d_style_combo.currentData() or "radial_gradient"
        self.settings["bead_3d_light"] = self.bead_3d_light_spn.value()
        self.settings["bead_3d_dark"] = self.bead_3d_dark_spn.value()
        self.settings["bead_3d_highlight_offset"] = self.bead_3d_highlight_offset_sld.value() / 100.0
        self.settings["use_indicator_outline"] = self.indicator_outline_enabled.isChecked()
        self.settings["indicator_outline_width"] = self.indicator_outline_width.value()
        self.settings["dh_font_size"] = self.dh_font_size.value()
        self.settings["dh_text_outline_width"] = self.dh_text_outline_width.value()
        self.settings["timer_font_size"] = self.timer_font_size.value()
        self.settings["timer_style"] = self.timer_style.currentData()
        self.settings["timer_arc_radius_offset"] = self.timer_arc_radius.value()
        self.settings["shrimp_img_path"] = self.icon_path.text().strip()
        self.settings["dodge_icon_scale_percent"] = self.icon_scale.value()
        self.settings["circle_pad_title"] = self.circle_pad_title.value()
        self.settings["core_canvas_w"] = self.core_canvas_w_spn.value()
        self.settings["core_canvas_h"] = self.core_canvas_h_spn.value()
        self.settings["center_text_offset_x"] = self.center_offset_x.value()
        self.settings["center_text_offset_y"] = self.center_offset_y.value()
        self.settings["dh_font_size_timer"] = self.dh_font_size_timer.value()
        self.settings["center_text_offset_x_timer"] = self.center_offset_x_timer.value()
        self.settings["center_text_offset_y_timer"] = self.center_offset_y_timer.value()
        self.settings["dh_text_outline_width_timer"] = self.dh_text_outline_width_timer.value()
        self.settings["roll_icon_opacity"] = self.roll_icon_opacity_spin.value()
        self.settings["lv7_timer_y_offset"] = self.lv7_timer_y_offset.value()
        self.settings["lv7_timer_badge_width"] = self.lv7_timer_badge_width.value()
        self.settings["single_timer_y_offset"] = self.single_timer_y_offset.value()
        self.settings["single_timer_badge_width"] = self.single_timer_badge_width.value()
        self.settings["single_timer_font_size"] = self.single_timer_font_size.value()
        self.settings["timer_center_offset_y"] = self.timer_center_y.value()
        for key, btn in self.color_buttons.items():
            self.settings[key] = btn.text()
        for key, spin in self.opacity_spins.items():
            self.settings[f"{key}_opacity"] = spin.value()
        self.settings["auto_check_update"] = self.auto_check_cb.isChecked()
        self.settings["skip_version"] = self.skip_version or ""
        self.settings["update_check_url"] = self.update_url_le.text().strip()
        self.settings["update_download_url"] = self.download_url_le.text().strip()
        # 全局快捷键：逐项保存启用状态与组合
        for _p, _k, _e in (("hk_show", "global_hotkey_show", "global_hotkey_show_enabled"),
                           ("hk_lock", "global_hotkey_lock", "global_hotkey_lock_enabled"),
                           ("hk_settings", "global_hotkey_settings", "global_hotkey_settings_enabled")):
            self.settings[_k] = getattr(self, f"{_p}_combo", "")
            self.settings[_e] = getattr(self, f"{_p}_enabled").isChecked()
        # 旧版总开关废弃：保存时写入 True，避免旧版读取时误判为禁用
        self.settings["global_hotkey_enabled"] = True
        # EXE 同步列表（仅保存；实际共同启动发生在程序启动时，仅一次）。
        # V2035：新增「启用 EXE 同步列表」整行开关，关掉时连列表本身都跳过、绝不启动任何 EXE。
        self.settings["enable_sync_exe_list"] = self.enable_sync_exe_chk.isChecked()
        self.settings["sync_exe_list"] = (self.sync_exe_le.toPlainText() or "").strip()
        # ── V2304：调试数据 ──────────────────────────────────────────────
        self.settings["debug_data_enabled"] = self.debug_data_enabled_chk.isChecked()
        self.settings["debug_text"] = (self.debug_text_le.text() or "").strip() or DEFAULT_SETTINGS["debug_text"]
        self.settings["debug_countdown"] = round(float(self.debug_countdown_spn.value()), 2)
        self.settings["debug_status"] = self.debug_status_cmb.currentData() or "ok"
        self.settings["debug_in_combat"] = self.debug_in_combat_chk.isChecked()
        self.settings["debug_mastery"] = self.debug_mastery_cmb.currentData() or ""
        self.settings["debug_core_buff_count"] = self.debug_core_count_spn.value()
        self.settings["debug_core_single_layer"] = self.debug_core_single_chk.isChecked()
        self.settings["debug_core_full_stacks"] = self.debug_core_full_chk.isChecked()
        self.settings["debug_core_stacks"] = self.debug_core_stacks_spn.value()
        self.settings["debug_core_max_stacks"] = self.debug_core_max_spn.value()
        self.settings["debug_core_awakening"] = self.debug_core_awk_chk.isChecked()
        self.settings["debug_core_truth"] = self.debug_core_truth_chk.isChecked()
        self.settings["debug_core_secret"] = self.debug_core_secret_chk.isChecked()
        self.settings["debug_allbuff_normal"] = int(self.debug_allbuff_normal_spn.value())
        self.settings["debug_allbuff_debuff"] = int(self.debug_allbuff_debuff_spn.value())
        self.settings["debug_allbuff_perma"] = int(self.debug_allbuff_perma_spn.value())
        self.settings["debug_allbuff_coda"] = int(self.debug_allbuff_coda_spn.value())
        self.settings["debug_allbuff_stacks"] = self.debug_allbuff_stacks_spn.value()
        self.settings["debug_allbuff_max_stacks"] = self.debug_allbuff_max_spn.value()
        self.settings["debug_boss_normal"] = int(self.debug_boss_normal_spn.value())
        self.settings["debug_boss_debuff"] = int(self.debug_boss_debuff_spn.value())
        self.settings["debug_boss_perma"] = int(self.debug_boss_perma_spn.value())
        self.settings["debug_boss_coda"] = int(self.debug_boss_coda_spn.value())
        self.settings["debug_boss_stacks"] = self.debug_boss_stacks_spn.value()
        self.settings["debug_boss_max_stacks"] = self.debug_boss_max_spn.value()
        self.settings["debug_skill_count"] = self.debug_skill_count_spn.value()
        self.settings["debug_skill_ready_count"] = self.debug_skill_ready_spn.value()
        self.settings["debug_skill_cd_max"] = round(float(self.debug_skill_cdmax_spn.value()), 1)
        self.settings["debug_dodge_count"] = self.debug_dodge_spn.value()
        return self.settings

    # ─────────────────────── V2116：黑名单 + 多次出现名单（统称「名单」子页）增 / 删 / 刷新 ───────────────────────
    # V2206 扩展：4 个 key（bl/ml 走主控全 Buff 设置；boss_bl/boss_ml 走 Boss Buff 设置），
    # 互斥关系按组：bl↔ml、boss_bl↔boss_ml，跨组不互斥。
    _WHICH_KEY = {
        "bl": "multi_buff_blacklist",  # 黑名单：sid 永不显示（全 Buff 模块 render 端硬过滤）
        "ml": "multi_buff_whitelist",  # 多次出现名单：sid 豁免单实例，可叠多实例
        "boss_bl": "boss_blacklist",   # V2206：Boss Buff 模块独立黑名单
        "boss_ml": "boss_multi_list",   # V2206：Boss Buff 模块独立多次出现名单
    }
    _WHICH_OPP = {"bl": "ml", "ml": "bl", "boss_bl": "boss_ml", "boss_ml": "boss_bl"}

    def _whitelist_display_name(self, entry, lang):
        """黑名单 / 多次出现名单 条目在指定语言下的显示名：优先用条目自带 name_xx，否则回退 buff_attrs.json 官方名，最后回退 sid。"""
        _name_key = {"zh": "name_zh", "zh_tw": "name_zh_tw", "en": "name_en"}.get(lang, "name_zh")
        _nm = (entry.get(_name_key) or "").strip()
        if _nm:
            return _nm
        _sid = int(entry.get("sid", -1))
        _attr = BUFF_ATTRS.get(f"0x{_sid:X}({_sid})")
        if _attr:
            _nkey = {"zh": "名称", "zh_tw": "繁中名", "en": "英文名", "ja": "日文名"}.get(lang, "名称")
            return (_attr.get(_nkey) or "").strip() or f"0x{_sid:X}"
        return f"0x{_sid:X}"

    def _which_list(self, which):
        """读取指定名单当前列表（dict 副本，不修改 DEFAULT_SETTINGS 共享引用）。
        兼容 V2204 旧版裸 sid 列表格式（[7, 42]）→ 自动规范为 [{"sid": 7}, ...]。"""
        _raw = self.settings.get(self._WHICH_KEY[which]) or []
        out = []
        for _x in _raw:
            if isinstance(_x, dict):
                out.append(dict(_x))
            else:
                out.append({"sid": int(_x)})
        return out

    def _set_which_list(self, which, items):
        self.settings[self._WHICH_KEY[which]] = items

    def _add_buff_list_group(self, parent_form, title_key, hint_key, which, empty_key):
        """V2247：彻底放弃 QScrollArea+自定义行 widget，改用标准 QListWidget + 右键菜单移除。

        V2241~6 在 QScrollArea+custom widget 路线上反复翻车（4 版都不稳）：
        · V2241 QListWidget.setItemWidget → setItemWidget 的 item.sizeHint 锁宽，按钮被裁成「移」字
        · V2242 换 QScrollArea+自定义行 → 按钮 OK，但 V2245/V2246 都翻车
        · V2245 wrapper _container maxHeight(240) 压制 inner → 行高被压扁、文本+按钮错位
        · V2246 wrapper 删了 + inner MinimumExpanding → 但 QFormLayout 不尊重 scroll area maxHeight(240)
          （form 字段行高 = widget.sizeHint，不看 maxHeight），导致内容撑出滚动区封顶；
          + 出现诡异的「每行两个移除按钮」渲染 bug（用户截图 V2246 实测）

        V2247 方案——标准 QListWidget + 右键菜单：
        · QListWidget 自带滚动（maxHeight 真生效）、自带选中、自带行渲染 → 零自定义 widget、零自定义 layout
        · 每个 QListWidgetItem 存 sid 到 Qt.UserRole
        · 启用 Qt.CustomContextMenu，右键 item 弹 QMenu 含「移除」action
        · 空态加占位 item（Qt.NoItemFlags → 右键空白处不弹菜单 / 占位 item 不响应）
        which ∈ {"bl", "ml", "boss_bl", "boss_ml"}。
        返回 dict：{gb, combo, btn, list_widget (QListWidget), hint, empty_key}。
        """
        _gb = QGroupBox(_tr(title_key))
        _gb.setStyleSheet(
            "QGroupBox{border:1px solid #3a4a66;border-radius:6px;margin-top:6px;"
            "padding-top:12px;color:#cfe0ff;font-weight:bold;font-size:11px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}"
        )
        _gcf = QFormLayout(); _gcf.setContentsMargins(8, 8, 8, 8); _gcf.setSpacing(6)
        _gb.setLayout(_gcf)
        # 描述
        _hint = QLabel(_tr(hint_key))
        _hint.setWordWrap(True)
        _hint.setStyleSheet("color:#9fb0cc;")
        _gcf.addRow(_hint)
        # 下拉 + 添加
        _row = QWidget()
        _rh = QHBoxLayout(_row); _rh.setContentsMargins(0, 0, 0, 0); _rh.setSpacing(6)
        _combo = QComboBox()
        _combo.setModel(QStandardItemModel(_combo))
        _btn = QPushButton(_tr("添加"))
        _btn.setEnabled(False)
        _combo.currentIndexChanged.connect(lambda _idx, _w=which: self._on_buff_combo_changed(_w, _idx))
        _btn.clicked.connect(lambda _c, _w=which: self._on_buff_add(_w))
        _rh.addWidget(_combo, 1)
        _rh.addWidget(_btn)
        _gcf.addRow(_row)
        # V2247：列表本体换 QListWidget + 右键菜单
        _list = QListWidget()
        _list.setMaximumHeight(240)
        _list.setMinimumHeight(96)
        _list.setUniformItemSizes(True)
        _list.setSelectionMode(QAbstractItemView.SingleSelection)
        _list.setContextMenuPolicy(Qt.CustomContextMenu)
        _list.customContextMenuRequested.connect(
            lambda pos, _w=which, _l=_list: self._show_buff_context_menu(_w, _l, pos)
        )
        _list.setStyleSheet(
            "QListWidget{background:#11192b;border:1px solid #2a3a55;border-radius:4px;color:#dfe7f5;outline:0;font-size:11px;}"
            "QListWidget::item{padding:0 10px;border-bottom:1px solid #1f2c44;}"  # V2248：padding 收紧，行高走 sizeHint
            "QListWidget::item:hover{background:#1a2540;}"
            "QListWidget::item:selected{background:#3a4a66;color:#fff;}"
            "QScrollBar:vertical{background:#0e1626;width:10px;border:none;margin:0;}"
            "QScrollBar::handle:vertical{background:#3a4a66;border-radius:5px;min-height:28px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;background:none;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}"
        )
        # V2248：行高 = N× 文字高度（QFontMetrics 计算，保证不浪费纵向空间）；V2249：1.1→1.3；V2250：1.3→1.6
        _fm = QFontMetrics(_list.font())
        _row_h = max(14, int(_fm.height() * 1.6))
        _list._row_h = _row_h  # 存起来供 _refresh_buff_list 用
        _gcf.addRow(_list)
        parent_form.addRow(_gb)
        return {"gb": _gb, "combo": _combo, "btn": _btn, "list_widget": _list, "hint": _hint, "empty_key": empty_key}

    def _refresh_buff_list(self, which):
        """V2247：彻底重做——用标准 QListWidget 替代 QScrollArea+自定义行 widget。
        - _list.clear() 清空所有 item；
        - 每个 buff 用 QListWidgetItem，setData(Qt.UserRole, sid) 存 sid 供右键菜单用；
        - 空态放一个 Qt.NoItemFlags 的占位 QListWidgetItem（不可选中、不可右键响应）；
        - 不再需要 row widget / QHBoxLayout / setMinimumHeight——QListWidget 全管。
        """
        _g = getattr(self, "_buff_groups", None)
        if not _g or which not in _g:
            return
        _gdata = _g[which]
        _list = _gdata.get("list_widget")
        if _list is None:
            return
        _list.clear()
        _items = self._which_list(which)
        _lang = self.settings.get("language", "zh")
        # V2248：拿 _add_buff_list_group 算好的行高（1.1× 文字高度），setSizeHint 到每个 item
        _row_h = getattr(_list, "_row_h", 0) or 0
        if not _items:
            # 空态：居中暗灰 QListWidgetItem（Qt.NoItemFlags 禁掉所有交互）
            _ph = QListWidgetItem(_tr(_gdata.get("empty_key", "尚未添加"), _lang))
            _ph.setFlags(Qt.NoItemFlags)
            _ph.setForeground(QBrush(QColor("#5a6a85")))
            if _row_h:
                _ph.setSizeHint(QSize(0, _row_h))
            _list.addItem(_ph)
            return
        for _e in _items:
            _sid = int(_e.get("sid", -1))
            # V2113：角色专属 buff 不可能进名单（即便旧配置误入也在此隐藏；render 端另有硬保险）
            if BUFF_ATTRS.get(f"0x{_sid:X}({_sid})", {}).get("是否专属"):
                continue
            _text = f"0x{_sid:X}({_sid})  {self._whitelist_display_name(_e, _lang)}"
            _item = QListWidgetItem(_text)
            _item.setData(Qt.UserRole, _sid)  # V2247：右键菜单用 setData(Qt.UserRole) 存 sid
            if _row_h:
                _item.setSizeHint(QSize(0, _row_h))  # V2248：行高 = 1.1× 文字高度
            _list.addItem(_item)

    def _show_buff_context_menu(self, which, list_widget, pos):
        """V2247：右键弹出 QMenu，含「移除」action——itemAt(pos) 拿 sid 调 _on_buff_remove。
        - 右键空白处（itemAt=None）→ 直接返回，不弹菜单；
        - 右键占位 item（Qt.UserRole=None）→ 返回（占位 item 没存 sid）；
        - 右键真实 buff item → 弹菜单含「移除」action，触发 _on_buff_remove(which, sid)。
        """
        _item = list_widget.itemAt(pos)
        if _item is None:
            return  # 右键空白处不弹菜单
        _sid = _item.data(Qt.UserRole)
        if _sid is None:
            return  # 占位 item 没有 sid
        try:
            _sid = int(_sid)
        except (TypeError, ValueError):
            return
        _menu = QMenu(list_widget)
        _menu.setStyleSheet(
            "QMenu{background:#1a2540;color:#dfe7f5;border:1px solid #3a4a66;border-radius:4px;padding:4px;}"
            "QMenu::item{padding:4px 16px;border-radius:3px;}"
            "QMenu::item:selected{background:#3a4a66;color:#fff;}"
        )
        _act_remove = _menu.addAction(_tr("移除"))
        _act_remove.triggered.connect(lambda _c=False, _w=which, s=_sid: self._on_buff_remove(_w, s))
        _menu.exec_(list_widget.mapToGlobal(pos))

    def _refresh_buff_combo(self, which):
        """重建指定名单的下拉菜单项（三层过滤：角色专属不列 + 已加入自己名单不列 + 已加入对方名单不列）。"""
        _g = getattr(self, "_buff_groups", None)
        if not _g or which not in _g:
            return
        _gdata = _g[which]
        _combo = _gdata["combo"]
        _btn = _gdata["btn"]
        _lang = self.settings.get("language", "zh")
        _name_key = {"zh": "名称", "zh_tw": "繁中名", "en": "英文名", "ja": "日文名"}.get(_lang, "名称")
        _combo.setPlaceholderText(_tr("选择一个 Buff…"))
        _model = _combo.model()
        _model.clear()
        # 自己名单已加入 sid
        _self_sids = set()
        for _e in self._which_list(which):
            try:
                _self_sids.add(int(_e.get("sid")))
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        # V2116：对方名单已加入 sid 也排除（黑名单/多次名单互斥）
        _opp = self._WHICH_OPP[which]
        _opp_sids = set()
        for _e in self._which_list(_opp):
            try:
                _opp_sids.add(int(_e.get("sid")))
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        _entries = []
        for _key, _attr in BUFF_ATTRS.items():
            try:
                _sid = int(str(_key).split("(")[1].rstrip(")"))
            except Exception:
                continue
            # V2113/V2116：角色专属 buff 直接从下拉菜单中剔除
            if _attr.get("是否专属"):
                continue
            # 已在对方名单/已在自己名单的也剔除
            if _sid in _self_sids or _sid in _opp_sids:
                continue
            _nm = (_attr.get(_name_key) or "").strip() or f"0x{_sid:X}"
            _entries.append((_sid, _nm))
        _entries.sort(key=lambda x: x[0])
        for _sid, _nm in _entries:
            _item = QStandardItem(f"{_nm}  (0x{_sid:X})")
            _item.setData(_sid, Qt.UserRole)
            _item.setToolTip(f"0x{_sid:X}")
            _model.appendRow(_item)
        _combo.setCurrentIndex(-1)
        _btn.setEnabled(False)

    def _on_buff_combo_changed(self, which, idx):
        """下拉菜单选中变化：仅启用 add。"""
        _g = getattr(self, "_buff_groups", None)
        if not _g or which not in _g:
            return
        _g[which]["btn"].setEnabled(idx >= 0)

    def _on_buff_add(self, which):
        """添加 sid：写入自己名单 + 刷新两个名单的 list + 刷新两个名单的 combo（互斥过滤）。"""
        _g = getattr(self, "_buff_groups", None)
        if not _g or which not in _g:
            return
        _gdata = _g[which]
        _combo = _gdata["combo"]
        _idx = _combo.currentIndex()
        if _idx < 0:
            return
        _m = _combo.model()
        _it = _m.item(_idx) if _m is not None else None
        if _it is None:
            return
        _sid = _it.data(Qt.UserRole)
        if not isinstance(_sid, int) or not (0 <= _sid <= 0xFFFF):
            return
        _attr = BUFF_ATTRS.get(f"0x{_sid:X}({_sid})")
        _items = self._which_list(which)
        _found = None
        for _x in _items:
            if int(_x.get("sid", -1)) == _sid:
                _found = _x; break
        if _found is None:
            _name_zh = (_attr.get("名称") or "") if _attr else ""
            _name_zh_tw = (_attr.get("繁中名") or "") if _attr else ""
            _name_en = (_attr.get("英文名") or "") if _attr else ""
            _items.append({"sid": _sid, "name_zh": _name_zh, "name_zh_tw": _name_zh_tw, "name_en": _name_en})
        self._set_which_list(which, _items)
        _combo.setCurrentIndex(-1)
        _gdata["btn"].setEnabled(False)
        self._refresh_buff_list(which)
        # V2116：刚加的 sid 从双方下拉中消失（自己 list 也排除；对方 list 也排除）
        self._refresh_buff_combo(which)
        self._refresh_buff_combo(self._WHICH_OPP[which])
        self._emit_changed()

    def _on_buff_remove(self, which, sid):
        """从指定名单移除 sid：刷新 list + 双方 combo（移除后 sid 在双方下拉里重现）。"""
        _items = [_x for _x in self._which_list(which) if int(_x.get("sid", -1)) != sid]
        self._set_which_list(which, _items)
        self._refresh_buff_list(which)
        self._refresh_buff_combo(which)
        self._refresh_buff_combo(self._WHICH_OPP[which])
        self._emit_changed()

    # ---------------- 全局快捷键：弹窗捕获 ----------------
    def _vk_to_name(self, vk):
        """Windows VK 十进制 → 显示名（含 Win）。"""
        names = {
            0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift", 0x11: "Ctrl",
            0x12: "Alt", 0x13: "Pause", 0x20: "Space", 0x25: "←", 0x26: "↑",
            0x27: "→", 0x28: "↓", 0x2E: "Delete", 0x5B: "Win", 0x5C: "Win",
            # 主键盘标点（Ctrl/Alt/Shift+标点时避免显示 VKxxx）
            0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
            0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
        }
        for i in range(1, 13):
            names[0x70 + (i - 1)] = "F%d" % i
        if vk in names:
            return names[vk]
        if 0x41 <= vk <= 0x5A:        # A-Z
            return chr(vk)
        if 0x30 <= vk <= 0x39:        # 0-9
            return chr(vk)
        return "VK%d" % vk

    def _combo_to_name(self, combo):
        """VK 逗号串（如 '17,75'）→ 显示名（如 'Ctrl + K'）；空串 → '未设置'。"""
        if not combo:
            return _tr("未设置")
        parts = []
        for part in str(combo).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                vk = int(part)
            except ValueError:
                continue
            parts.append(self._vk_to_name(vk))
        return " + ".join(parts) if parts else _tr("未设置")

    def _build_hotkey_row(self, cf, prefix, label_text, setting_key, default_combo, enabled_key=None, default_enabled=True):
        """生成一行热键设置：勾选框（启用）+ 按钮（捕获）+ 当前组合标签。
        状态存到 self.{prefix}_enabled/_combo/_lbl/_btn。
        """
        enabled_key = enabled_key or f"{setting_key}_enabled"
        row = QWidget()
        lay = QHBoxLayout(row); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        chk = QCheckBox()
        # 旧版总开关迁移：若存在 global_hotkey_enabled=False，则默认全部禁用
        old_enabled = self.settings.get("global_hotkey_enabled")
        if old_enabled is False:
            default_enabled = False
        chk.setChecked(bool(self.settings.get(enabled_key, default_enabled)))
        btn = QPushButton(_tr("设置按键…"))
        btn.setFixedWidth(110)
        lbl = QLabel()
        lbl.setStyleSheet("color:#cfe0ff;font-weight:bold;font-size:13px;")
        combo = self.settings.get(setting_key, default_combo) or ""
        lbl.setText(self._combo_to_name(combo) if combo else _tr("未设置"))
        btn.clicked.connect(lambda _=None, p=prefix: self._capture_hotkey(p))
        lay.addWidget(chk); lay.addWidget(btn); lay.addWidget(lbl); lay.addStretch()
        cf.addRow(label_text + "：", row)
        setattr(self, f"{prefix}_enabled", chk)
        setattr(self, f"{prefix}_combo", combo)
        setattr(self, f"{prefix}_lbl", lbl)
        setattr(self, f"{prefix}_btn", btn)

    def _capture_hotkey(self, which):
        combo = getattr(self, f"{which}_combo", "") or ""
        dlg = HotkeyCaptureDialog(self, self._combo_to_name(combo) if combo else _tr("按下组合键…"))
        if dlg.exec() == QDialog.Accepted and dlg.captured_combo:
            new_combo = ",".join(str(v) for v in dlg.captured_combo)
            setattr(self, f"{which}_combo", new_combo)
            getattr(self, f"{which}_lbl").setText(dlg.captured_name)
            self._emit_changed()

    def accept(self):
        """确定前校验：三个全局热键两两不能相同（空值不参与比较）。"""
        combos = {
            "呼出/隐藏所有窗口": getattr(self, "hk_show_combo", "") or "",
            "锁定 / 解锁窗口": getattr(self, "hk_lock_combo", "") or "",
            "打开设置": getattr(self, "hk_settings_combo", "") or "",
        }
        non_empty = [(name, c) for name, c in combos.items() if c]
        seen = {}
        for name, c in non_empty:
            if c in seen:
                QMessageBox.warning(
                    self,
                    _tr("热键冲突"),
                    "全局热键不能两两相同：\n\n" +
                    f"「{seen[c]}」与「{name}」都设置为\n{self._combo_to_name(c)}\n\n请修改后再确定。",
                )
                return
            seen[c] = name
        super().accept()

    # ---------------- 在线更新 ----------------
    def refresh_update_ui(self, info=None):
        if info is None:
            info = getattr(self.ctrl, "update_info", None)
        lang = self.settings.get("language", "zh")
        local_cl = _load_local_changelog(lang)
        if info is None:
            self.update_status_label.setText("—")
            self.download_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.changelog_edit.setPlainText(local_cl)
            return
        if info.get("error") == "no_url":
            self.update_status_label.setText(_tr("未配置更新地址"))
            self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
            self.changelog_edit.setPlainText(local_cl)
            return
        if info.get("error"):
            self.update_status_label.setText(_tr("检查失败：") + str(info.get("error")))
            self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
            # 远端拉取失败：显示随 exe 打包的本地当前版本日志（非陈旧远端内容）
            self.changelog_edit.setPlainText(local_cl)
            return
        latest = info.get("latest_version", "")
        self.changelog_edit.setPlainText(_safe_remote_changelog(pick_lang_text(info.get("changelog", ""), lang), lang, local_cl))
        if info.get("has_update"):
            self.update_status_label.setText(_tr("发现新版本") + " v" + str(latest) + "！")
            dl = info.get("download_url") or ""
            if dl:
                self.download_url_le.setText(dl)
                self.settings["update_download_url"] = dl
            self.download_btn.setEnabled(bool(info.get("download_url")))
            self.skip_btn.setEnabled(True)
            self.skip_btn.setText(_tr("跳过 v") + str(latest))
        else:
            # latest <= APP_VERSION：不显示该版本号（用户要求"小于等于则不在日志里显示"）
            self.update_status_label.setText(_tr("已是最新版本"))
            self.download_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)

    def _refresh_settings_title(self):
        """设置窗口标题栏：Overlay 设置 vX[ · 更新状态]。无状态时只显示版本。"""
        ctrl = getattr(self, "ctrl", None)
        brief = getattr(ctrl, "update_brief", "") or "" if ctrl is not None else ""
        title = _tr("Overlay 设置") + f" v{APP_VERSION}"
        if brief:
            title += " · " + brief
        self.setWindowTitle(title)

    def _on_update_status_changed(self, brief):
        self._refresh_settings_title()

    def _on_check_update_clicked(self):
        self.update_status_label.setText(_tr("检查中…"))
        self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
        if self.ctrl is not None:
            self.ctrl.check_update(manual=True)

    def _on_download_clicked(self):
        info = getattr(self.ctrl, "update_info", None)
        url = (info.get("download_url") if info else None) or self.download_url_le.text().strip()
        if url:
            # 优先应用内下载（同目录 → 完成后启动新版本并退出旧程序），失败回退浏览器
            if self.ctrl is None or not self.ctrl.start_self_update(url):
                QDesktopServices.openUrl(QUrl(url))

    def _on_skip_clicked(self):
        info = getattr(self.ctrl, "update_info", None)
        if info and info.get("latest_version"):
            self.skip_version = str(info["latest_version"])
            self.update_status_label.setText(_tr("已跳过 v") + self.skip_version)
            self.skip_btn.setEnabled(False)
            self.download_btn.setEnabled(False)

# ============================ 全局快捷键（最多 3 键组合；呼出/隐藏 / 锁定 / 设置）============================
IS_WINDOWS = (sys.platform == "win32")
# 三个热键用途的注册 id（RegisterHotKey 的 id 参数，用于区分回调）
_HK_SHOW = 1        # 呼出/隐藏所有窗口
_HK_LOCK = 2        # 锁定/解锁窗口
_HK_SETTINGS = 3    # 打开设置
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
# 修饰键 VK → RegisterHotKey 的 MOD_* 标志（左右 Win 合并为 MOD_WIN）
_VK_MOD_FLAGS = {
    0x11: _MOD_CONTROL,   # VK_CONTROL
    0x12: _MOD_ALT,       # VK_MENU
    0x10: _MOD_SHIFT,     # VK_SHIFT
    0x5B: _MOD_WIN,       # VK_LWIN
    0x5C: _MOD_WIN,       # VK_RWIN
}
_WM_HOTKEY = 0x0312

class _HotkeyFilter(QAbstractNativeEventFilter):
    """拦截 Win32 WM_HOTKEY 消息，按 id 触发对应回调。"""

    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == "windows_generic_MSG":
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG))
                if msg.contents.message == _WM_HOTKEY:
                    self._cb(int(msg.contents.wParam))
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        return False

# ============================ Overlay Widget ============================
class GBFROverlayQt(QObject):
    update_checked = Signal(object)
    update_dl_progress = Signal(int, int)   # 已下载字节, 总字节(0=未知)
    update_dl_done = Signal(str, str)       # (新exe完整路径, 错误信息；成功时错误为空)
    update_dl_retry = Signal(int, int)      # (当前重试次数, 最大重试次数)
    update_status_changed = Signal(str)      # 标题栏实时更新状态文案：""/检查中…/已是最新/发现新版本 vX/检查失败/未配置更新地址
    """控制器（隐藏、不绘制）：负责扫描内存、持有共享状态、托盘、设置，
    并创建/管理 3 个独立可拖动的模块窗口（核心检测 / 翻滚 / 能力冷却）。"""

    TITLE_BAR_H = 44
    CANVAS_W = 648  # 核心检测模块画布宽度基准（原 480 × 1.35，放大监测区尺寸）
    CORE_AREA_MULT = 1.35  # 核心监测区整体（长/宽）放大倍数（用户要求 ×1.35）
    SHRIMP_BASE_SIZE = 36
    ARC_WIDTH = 7
    CIRCLE_WIDTH = 3
    BACKDROP_RADIUS = 10
    GLOW_LAYERS = 3
    ICON_BTN_SIZE = 16
    ICON_BTN_GAP = 7
    MAX_DODGES = 7
    ROLL_ICON_GAP = 4

    def __init__(self, progress_cb=None):
        super().__init__()

        def _step(pct, msg):
            if progress_cb:
                try:
                    progress_cb(pct, msg)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)

        _step(8, _tr("正在加载设置…"))
        self.settings = load_settings()
        # 启动即同步全局语言：确保更新检查/标题栏等早期路径的 _tr() 能正确翻译
        global _CURRENT_LANG
        _CURRENT_LANG = self.settings.get("language", "zh")
        self.locked = bool(self.settings.get("startup_locked", False))
        self._pressed_core_btn = None  # 标题栏图标按下反馈态：None/"minimize"/"settings"/"lock"/"exit"
        self._pressed_visual = False   # 指针是否仍在被按下的按钮内（仅影响凹陷视觉，不清除锁定）
        # 窗口局部像素版命中矩形（与绘制缩放一致，避免画布<->窗口坐标换算误差）
        self._btn_minimize_rect_win = QRect()
        self._btn_settings_rect_win = QRect()
        self._btn_lock_rect_win = QRect()
        self._btn_exit_rect_win = QRect()

        self.handle = None
        self.pid = None
        self._interacting = False   # V2025：拖拽 / 缩放模块进行中锁（焦点同步跳过隐藏）
        self.pptr = None
        self.module_base = None
        self.module_size = 0
        self.quest_mgr = None
        self.in_training_area = False
        self.status = "init"
        self.active_buffs = []
        self.dodge_count = 0
        self.char_type = 0
        self.charid_hash = 0
        self.pl_id = None
        # V2063：buff 排序用——记录每个 sid 首次出现的 seq（monotonic），
        # 用于「按出现时间」排序；消失-再出现不重置 seq，原位补回。
        self._buff_first_seen_seq = {}
        self._buff_next_seq = 0
        # 前后台边沿检测：上一拍游戏是否在前台（None=未初始化）
        self._prev_is_game_foreground = None
        # V2316：游戏强退后重进的「窗口一直最小化」修复标志。
        # scan() 重连分支置 True → _sync_visibility_with_game_focus 下一拍强制按当前前台判定补一次弹出。
        self._force_fg_sync = False
        # 当前所有同名游戏进程 PID 集合（V2018 引入）：用于「游戏是否在前台」判断
        # 见 find_game_pids() 与 _sync_visibility_with_game_focus() 注释。
        self._game_pids = set()
        # V2018 焦点诊断：让用户能直观看到当前 GetForegroundWindow 的 PID vs game_pids。
        # 写入 overlay_focus_log.txt（最近 200 行环形），便于确认前后台识别是否生效。
        self._focus_log_ring = []   # [dict(ts/ms/prev/fg/game_pids/self_pid/is_game_fg/action), ...] 环形 200 条
        self._focus_log_path = None  # 由 __init__ 阶段后初始化为 dist 目录或 exe 同目录

        self._ooc_content_mult = 1.0
        self._ooc_content_hidden = False
        # V2300：「游戏在后台 → 整体隐藏」的意图标志。由 _hide_all_windows / _show_all_windows
        # 登记，统一仲裁入口 _apply_module_visibility 读取。所有整窗显隐都必须尊重它——
        # 此前每处各自直接 w.show()/w.hide()，互相覆盖，是「切后台不隐藏 / 回前台只出 2 个模块」的根因。
        self._bg_hidden = False
        # 技能冷却状态
        self.skill_cd_data = []
        self._skill_ready_anim = [None] * 4  # 每槽的完成动画时间戳
        self._spike_flash = {}        # 每层buff的尖刺闪光：{bkey: {"start": ms, "from": prev_stacks}}
        self._prev_buff_stacks = {}   # 每层buff上一帧层数：{bkey: stacks}
        self.spike_hidden = False
        # 裸值资源槽地址锁定（伊德四槽等）：{profile_buff_index: addr}
        self._raw_locked_addrs = {}
        self._prev_actor = 0
        # 专精判定（觉醒/真谛/秘义）：attach 时建 MasteryReader，tick 更新 current_mastery
        self.mastery_reader = None
        self.current_mastery = None  # 'awakening'/'truth'/'secret'/None
        _step(22, _tr("已加载角色数据库"))
        load_char_db()

        # 计算「核心检测模块」画布布局（尖刺圆 + 标题栏）
        _step(38, _tr("正在计算界面布局…"))
        self.recalc_layout()
        # 旧版本(≤V703)原始像素位置一次性归一化，必须在窗口创建读取位置前执行
        self._migrate_pos_res()
        _step(52, _tr("正在加载图标资源…"))
        self.load_dodge_icon()
        # 翻滚图标闪光状态
        self._dodge_flash = None
        self._dodge_solid_cache = {}      # 翻滚图标实心缓存 {color_hex: QPixmap}
        self._prev_dodge_count = 0

        # 任务栏归并：用一个隐藏的“宿主”窗口持有 3 个模块窗口，
        # 使它们在 Windows 任务栏中只显示为一个条目（受属主窗口约束）。
        self.taskbar_owner = QWidget()
        # Qt.Tool 使宿主窗不进任务栏；仅系统托盘图标作为唯一入口
        self.taskbar_owner.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.taskbar_owner.setAttribute(Qt.WA_TranslucentBackground, True)
        self.taskbar_owner.resize(1, 1)
        self.taskbar_owner.move(-32000, -32000)
        self.taskbar_owner.setWindowTitle(f"{_app_title(self.settings.get('language', 'zh'))} v{APP_VERSION}")
        self.taskbar_owner.show()

        # 创建 4 个独立模块窗口（各自可鼠标拖动、各自屏幕位置与缩放），归并到宿主窗口
        self.core_win = CoreWindow(self, "core", parent=self.taskbar_owner)
        self.roll_win = DodgeWindow(self, "roll", parent=self.taskbar_owner)
        self.skill_win = SkillWindow(self, "skill", parent=self.taskbar_owner)
        self.allbuff_win = AllBuffWindow(self, "allbuff", parent=self.taskbar_owner)
        # V2200：Boss Buff 模块（第五模块）——独立窗口，数据源为场上 boss 的 ExStatus
        self.boss_win = BossBuffWindow(self, "boss", parent=self.taskbar_owner)
        self.core_win.setWindowTitle(f"{_app_title(self.settings.get('language', 'zh'))} v{APP_VERSION}")

        _step(72, _tr("已创建悬浮窗口"))
        self._setup_tray_icon()
        _step(86, _tr("已初始化系统托盘"))

        # ---- 在线更新检测 ----
        self.update_info = None
        self.update_brief = ""   # 标题栏实时更新状态文案（核心模块 canvas 与设置窗口标题栏共用）
        self._update_thread = None
        self.settings_dialog = None
        self.update_checked.connect(self._on_update_checked)
        # ---- 应用内自更新（下载新 exe 到旧 exe 同目录 → 启动新 → 退出旧）----
        self._dl_thread = None
        self._dl_cancel = False
        self.update_dl_progress.connect(self._on_dl_progress)
        self.update_dl_done.connect(self._on_dl_done)
        self.update_dl_retry.connect(self._on_dl_retry)
        self._update_startup_timer = QTimer(self)
        self._update_startup_timer.setSingleShot(True)
        self._update_startup_timer.timeout.connect(lambda: self.check_update())
        self._update_startup_timer.start(4000)
        self._update_periodic_timer = QTimer(self)
        self._update_periodic_timer.setInterval(24 * 3600 * 1000)
        self._update_periodic_timer.timeout.connect(lambda: self.check_update())
        self._update_periodic_timer.start()

        # V2018：焦点诊断 log 写到 exe 同目录（onefile 下用 sys.argv[0] 取得真实 exe 路径）。
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        except Exception:
            exe_dir = os.getcwd()
        self._focus_log_path = os.path.join(exe_dir, "overlay_focus_log.txt")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        # 焦点同步独立低频定时器（默认 250ms）：与 50ms 游戏数据扫描解耦，
        # 避免每帧都调用 GetForegroundWindow（修复 ④ 不必要的轮询开销）。
        self.focus_timer = QTimer(self)
        self.focus_timer.setInterval(250)
        self.focus_timer.timeout.connect(self._sync_visibility_with_game_focus)
        self.focus_timer.start()
        # 首次扫描延后到事件循环启动后执行，避免阻塞构造。
        QTimer.singleShot(0, self.tick)

        # 显示模块窗口
        _step(95, _tr("正在显示悬浮窗口…"))
        # V2300：整窗显隐统一走仲裁入口（模块开关的判定集中在那里）
        self._apply_module_visibility()
        # V2253：启动即应用整屏对齐（halign/valign）——
        # 此前 _refresh_window_geometries() 只在三个时机被调用：① 重置窗口位置（确认后）
        # ② 屏幕分辨率变化（且 res_scale 真变了）③ 设置对话框关闭后 _after_settings_changed()。
        # 启动时从未调用过，所以模块开机时用的是 settings 里的 X/Y 原始坐标，
        # 「靠左/靠右/居中/置顶/置底」要等玩家打开一次设置才生效（用户反馈的 bug）。
        # 这里在窗口全部 show 之后立即刷一次几何，让整屏对齐开机就位。
        # 内部会先 recalc_layout() + resize()，故 w.width()/w.height() 已是最终尺寸，
        # _screen_available_geometry() 在 QApplication 建好后即可用，无需延后到事件循环。
        self._refresh_window_geometries()
        _step(100, _tr("启动完成"))

        # 全局快捷键：最多 3 键组合（呼出/隐藏、锁定/解锁、打开设置）
        self._hotkey_filter = _HotkeyFilter(self._on_hotkey_triggered)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._hotkey_filter)
            try:
                app.aboutToQuit.connect(self._unregister_global_hotkey)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        self._register_all_hotkeys()

        # 启动即同步 EXE 列表（仅开启时发生一次：未运行则启动，已运行则关闭）
        QTimer.singleShot(0, self._sync_exe_list_at_startup)

        # 分辨率实时监听：显示器分辨率/主屏变化 → 窗口大小与位置自动跟随缩放
        self._bind_primary_screen()

    # ----------------------------------------------------------------
    #  窗口集合辅助
    # ----------------------------------------------------------------
    def _all_windows(self):
        return [self.core_win, self.roll_win, self.skill_win, self.allbuff_win, self.boss_win]

    # V2300：哪些模块拥有「整窗显隐开关」。core / roll / skill 的开关只隐藏**内容**
    # （窗口与标题栏保留，见各 render_* 内的 early-return），因此不在此表内。
    _MODULE_WINDOW_SWITCH = {
        "allbuff": "show_allbuff_module",
        "boss": "show_boss_module",
    }

    def _apply_module_visibility(self):
        """V2300：模块「整窗显隐」的唯一仲裁入口。

        背景（为什么要收敛）：此前整窗显隐散落在 4 处各写各的——
          ① 启动时的窗口 show 循环
          ② _hide_all_windows / _show_all_windows（前后台边沿，250ms 定时器）
          ③ _apply_live_settings（设置变化时）
          ④ _sync_out_of_combat_visibility（进出战斗 / 训练场状态跳变时）
        其中 ③④ 会**无条件** w.show() 两个 buff 模块，完全不知道游戏是否在前台。
        于是：focus_timer 刚把 5 个窗口藏好，只要此时战斗状态翻一下（或改一下设置），
        buff 模块就被弹回来 —— 表现为「切后台时两个 buff 模块照样出现」（症状①）；
        而它们一直可见 → any_visible 恒为 True → 回前台时 _show_all_windows 的触发条件
        `if not any_visible:` 永不成立 → core/roll/skill 再也出不来（症状②）。

        修法：所有路径只登记「意图」（_bg_hidden / 模块开关），由本入口统一裁决，
        禁止任何地方再直接 w.show()/w.hide() 绕过。

        决策优先级（高 → 低）：
          1. _bg_hidden（游戏在后台）→ 全部隐藏，无视其它条件；
          2. 模块整窗开关关闭 → 该模块隐藏；
          3. 其余 → 显示。
        """
        bg_hidden = bool(getattr(self, "_bg_hidden", False))
        for w in self._all_windows():
            if w is None:
                continue
            # 1) 后台：最高优先级，全部隐藏
            if bg_hidden:
                if w.isVisible():
                    w.hide()
                continue
            # 2) 模块整窗开关
            sw_key = self._MODULE_WINDOW_SWITCH.get(getattr(w, "module_key", None))
            if sw_key is not None and not bool(self.settings.get(sw_key, True)):
                if w.isVisible():
                    w.hide()
                continue
            # 3) 正常显示
            if not w.isVisible():
                w.show()

    def _sync_exe_list_at_startup(self):
        """启动时共同启动 EXE 列表中的程序（未运行则启动，已运行则跳过；不监视、不杀进程）。
        整段逻辑放进后台 daemon 线程执行，彻底避免任何启动/进程枚举可能造成的 Qt 主线程阻塞
        （上一版用 QProcess.startDetached 在主线程同步启动，会导致『打开瞬间读到状态后卡死』）。
        V2035：先看「启用 EXE 同步列表」整行开关，关掉就直接 return，连列表都跳过；
        这样既不遍历列表、不枚举进程、不启动任何 EXE，CPU=0 真正零开销。"""
        if not bool(self.settings.get("enable_sync_exe_list", True)):
            return
        raw = self.settings.get("sync_exe_list", "") or ""
        if not raw.strip():
            return
        import threading
        threading.Thread(target=_run_sync_exe_list, args=(raw,), daemon=True).start()

    def _register_all_hotkeys(self):
        """（重新）注册全部全局快捷键：呼出/隐藏、锁定/解锁、打开设置。

        每个热键为最多 3 键组合（修饰键 Ctrl/Alt/Shift/Win + 1 个主键），
        以 VK 逗号串存于 settings。空串 = 该热键未设置、跳过。
        """
        self._unregister_global_hotkey()
        if not IS_WINDOWS:
            return
        # 旧版单键迁移：global_hotkey_key 表示「Ctrl + 单键」，恢复为「Ctrl + 该键」组合。
        # 仅当 show 未显式设置（空或仍为默认 17,75）时才迁移，避免覆盖用户在新版里已自定义的组合。
        show = self.settings.get("global_hotkey_show")
        old = self.settings.get("global_hotkey_key")
        if old and (not show or show == "17,75"):
            show = self._migrate_old_key(old)
            self.settings["global_hotkey_show"] = show
            try:
                save_settings(self.settings)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        mapping = [
            (_HK_SHOW, show, bool(self.settings.get("global_hotkey_show_enabled", True))),
            (_HK_LOCK, self.settings.get("global_hotkey_lock"), bool(self.settings.get("global_hotkey_lock_enabled", False))),
            (_HK_SETTINGS, self.settings.get("global_hotkey_settings"), bool(self.settings.get("global_hotkey_settings_enabled", False))),
        ]
        self._hotkey_registered = {}
        for hid, combo, enabled in mapping:
            if not enabled or not combo:
                continue
            mods, main = self._parse_combo(combo)
            if main is None:
                continue
            try:
                if ctypes.windll.user32.RegisterHotKey(0, hid, mods, main):
                    self._hotkey_registered[hid] = True
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

    @staticmethod
    def _migrate_old_key(old):
        """旧版 global_hotkey_key 表示「Ctrl + 单键」，恢复为带 Ctrl 的组合串（如 '17,75'）。"""
        if not old:
            return "17,75"
        if old.isdigit():
            vk = old
        elif old and old[0].isalpha():
            vk = str(ord(old[0].upper()))
        else:
            vk = "75"
        return "17," + vk

    @staticmethod
    def _parse_combo(combo):
        """VK 逗号串 → (mod_flags, main_vk)。无主键时 main_vk 为 None。"""
        if not combo:
            return (0, None)
        mods = 0
        main = None
        for part in str(combo).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                vk = int(part)
            except ValueError:
                continue
            if vk in _VK_MOD_FLAGS:
                mods |= _VK_MOD_FLAGS[vk]
            elif main is None:
                main = vk          # 只取第一个非修饰键作为主键
        return (mods, main)

    def _unregister_global_hotkey(self):
        if not IS_WINDOWS:
            return
        for hid in (_HK_SHOW, _HK_LOCK, _HK_SETTINGS):
            try:
                ctypes.windll.user32.UnregisterHotKey(0, hid)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        self._hotkey_registered = {}

    def _on_hotkey_triggered(self, hid):
        try:
            if hid == _HK_SHOW:
                self._toggle_all_windows()
            elif hid == _HK_LOCK:
                self._toggle_lock()
            elif hid == _HK_SETTINGS:
                self.open_settings()
        except Exception:
            logger.debug("swallowed exception", exc_info=True)

    def _toggle_all_windows(self):
        """切换所有悬浮窗口显隐：任一可见则全部隐藏，否则全部显示。"""
        wins = self._all_windows()
        if not wins:
            return
        any_visible = any(w.isVisible() for w in wins)
        if any_visible:
            self._hide_all_windows()
        else:
            self._show_all_windows()

    def _hide_all_windows(self):
        """整窗隐藏（不进任务栏），与标题栏最小化图标完全同一动作；供 手动隐藏 / 自动下降沿 共用。
        V2300：改为登记「后台隐藏意图」后交给统一仲裁入口，不再自己 for 循环。"""
        self._bg_hidden = True
        self._apply_module_visibility()

    def _show_all_windows(self):
        """整窗显示并置顶，与手动呼出完全同一动作；供 手动呼出 / 自动上升沿 共用。
        V2300：清除「后台隐藏意图」后交给统一仲裁入口（模块开关判定也集中在那里）。"""
        self._bg_hidden = False
        self._apply_module_visibility()
        # 置顶：只对最终处于可见状态的窗口生效
        for w in self._all_windows():
            if w is not None and w.isVisible():
                w.raise_()

    def _show_all(self):
        """V2020a 补回别名：托盘「显示所有窗口」/_reset_all_windows 都连到 _show_all，
        但 def 实际只有 _show_all_windows——以前 connect 时 AttributeError 中断整个
        _update_tray_menu、导致第 5-9 项菜单不显示。现在补回来当作 wrapping。"""
        self._show_all_windows()

    def _reset_all_windows(self):
        """托盘「重置所有窗口」：把三个模块的屏幕位置与缩放恢复为默认值并居中显示。"""
        lang = self.settings.get("language", "zh")
        title = {"zh": "重置所有窗口", "zh_tw": "重置所有視窗", "en": "Reset All Windows"}.get(lang, "Reset All Windows")
        text = {"zh": "确定要把三个模块的窗口位置与缩放恢复为默认并居中吗？此操作会覆盖当前布局。",
                "zh_tw": "確定要把三個模組的視窗位置與縮放恢復為預設並置中嗎？此操作會覆蓋目前佈局。",
                "en": "Reset the position and scale of all three module windows to default and center them?"}.get(lang, "Reset all window positions and scale to default?")
        reply = QMessageBox.question(self._all_windows()[0] if self._all_windows() else None, title, text,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for w in self._all_windows():
            key = w.module_key
            self.settings[f"{key}_window_x"] = DEFAULT_SETTINGS[f"{key}_window_x"]
            self.settings[f"{key}_window_y"] = DEFAULT_SETTINGS[f"{key}_window_y"]
            self.settings[f"{key}_scale_percent"] = 100
        self._refresh_window_geometries()
        self._show_all()
        save_settings(self.settings)

    def _refresh_window_geometries(self):
        """设置变化后刷新各窗口尺寸/位置（位置数值调整实时同步到屏幕）。"""
        self.recalc_layout()
        self.load_dodge_icon()
        for w in self._all_windows():
            w.recalc_layout()
            w.resize(w.window_w, w.window_h)
            nx = int(self.settings.get(f"{w.module_key}_window_x", w.x()))
            ny = int(self.settings.get(f"{w.module_key}_window_y", w.y()))
            x, y = self.denorm_pos(nx, ny)
            # V2228：整屏对齐——水平（靠左/居中/靠右）与垂直（置顶/居中/置底）。
            # 非 custom 时按「当前屏幕可用区域」重算该轴坐标，覆盖 X/Y 数值；
            # 因为每次刷新几何都重算，模块缩放、分辨率变化、每行数量变化后依然保持贴边/居中。
            _ha = str(self.settings.get(f"{w.module_key}_halign", "custom"))
            _va = str(self.settings.get(f"{w.module_key}_valign", "custom"))
            if _ha != "custom" or _va != "custom":
                _sg = self._screen_available_geometry()
                if _sg is not None:
                    _ww, _wh = w.width(), w.height()
                    # V2229：水平/垂直边距——左/右对齐时用 hmargin，上/下对齐时用 vmargin
                    # center 不应用 margin；custom 不进入此分支
                    _hm = int(self.settings.get(f"{w.module_key}_hmargin", 0))
                    _vm = int(self.settings.get(f"{w.module_key}_vmargin", 0))
                    if _ha == "left":
                        x = _sg.left() + _hm
                    elif _ha == "center":
                        x = _sg.left() + (_sg.width() - _ww) // 2
                    elif _ha == "right":
                        x = _sg.left() + _sg.width() - _ww - _hm
                    if _va == "top":
                        y = _sg.top() + _vm
                    elif _va == "center":
                        y = _sg.top() + (_sg.height() - _wh) // 2
                    elif _va == "bottom":
                        y = _sg.top() + _sg.height() - _wh - _vm
            w.move(x, y)
            w.update()

    def _screen_available_geometry(self):
        """V2228：取主屏可用区域（排除任务栏）；取不到时返回 None，调用方保留原 X/Y 行为。"""
        try:
            from PySide6.QtWidgets import QApplication
            _scr = QApplication.primaryScreen()
            if _scr is None:
                return None
            return _scr.availableGeometry()
        except Exception:
            return None

    def _on_screen_geometry_changed(self, *args):
        """显示器分辨率/主屏变化时：仅当 res_scale 真正改变时，重算布局并让所有窗口
        按新分辨率重新缩放与定位（位置/大小都跟随，兑现「按当前屏幕宽度自动放大」）。
        已存的位置是「基准宽度归一化坐标」，直接用新 res_scale 反算即可，无需先回写。"""
        old = getattr(self, "res_scale", 1.0)
        self.recalc_layout()
        if self.res_scale == old:
            return
        self._refresh_window_geometries()

    def _bind_primary_screen(self):
        """绑定主屏 geometryChanged（分辨率变化即时重定位）；主屏整体切换时重绑。"""
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.primaryScreenChanged.connect(self._on_primary_screen_changed)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        screen = QApplication.primaryScreen()
        if screen is not None:
            try:
                screen.geometryChanged.connect(self._on_screen_geometry_changed)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

    def _on_primary_screen_changed(self, *args):
        """主屏被替换（如拔插显示器）时，重新绑定新主屏的 geometryChanged 并刷新一次。"""
        screen = QApplication.primaryScreen()
        if screen is not None:
            try:
                screen.geometryChanged.connect(self._on_screen_geometry_changed)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        self._on_screen_geometry_changed()

    # ----------------------------------------------------------------
    #  不透明度辅助
    # ----------------------------------------------------------------
    def _effective_opacity(self, color_key):
        """返回 0.0–1.0 的有效不透明度，锁定时仅标题栏/背景/图标减半（向上取整）。
        当尖刺圆模块因「无buff隐藏」而隐藏时，仅尖刺圆相关颜色键改用 spike_hidden_opacity；
        翻滚UI 与 冷却技能UI 不受影响，永远按其各自配置的不透明度显示。
        标题栏相关键（标题栏底色、图标/状态文字）不受「非战斗隐藏」影响，永远正常显示。"""
        # 标题栏相关键：豁免「非战斗隐藏」乘数，确保隐藏内容时标题栏始终可见
        TITLE_OOC_EXEMPT = ("title_bar_color", "icon_color")
        opacity = int(self.settings.get(f"{color_key}_opacity", 100))
        if self.locked and color_key in LOCK_HALVED_KEYS:
            opacity = math.ceil(opacity / 2)
        if self.spike_hidden and color_key in SPIKE_HIDDEN_KEYS:
            opacity = int(self.settings.get("spike_hidden_opacity", 0))
        # V2034：尖刺与装饰小球各自独立开关——关闭时该层不透明度强制为 0
        # （尖刺三角本体与装饰小球都用 spike_color_normal/lv7 着色，前者受 show_spikes 控制、
        #  后者受 show_bead 控制；绘制层 _draw_spikes 内对「仅画小球」也单独判定 show_bead）。
        if color_key in ("spike_color_normal", "spike_color_lv7") and not self._spike_drawn():
            opacity = 0
        base = max(0, min(100, opacity)) / 100.0
        if color_key in TITLE_OOC_EXEMPT:
            return base
        return base * getattr(self, "_out_of_combat_mult", 1.0)

    def _buff_max_stacks(self, buff):
        """单个 buff 的满层层数。优先使用内存动态读取值，回退到默认7。"""
        ms = buff.get("max_stacks")
        if ms and ms > 0:
            return max(1, int(ms))
        return 7

    def _is_buff_full_stack(self, buff):
        """单个 buff 是否进入满层状态。浮点槽按 gauge_value 判定；单层 buff 无层数概念，固定非满层。"""
        if buff.get("single_layer"):
            return False
        if buff.get("gauge_mode") == "float":
            gv = buff.get("gauge_value")
            if isinstance(gv, (int, float)):
                return gv >= self._buff_max_stacks(buff) * 0.99
            return False
        return int(buff.get("stacks", 0)) >= self._buff_max_stacks(buff)

    def _buff_has_timer(self, buff):
        """单个 buff 是否有有效倒计时。"""
        # 单层buff（不死之身/无限之辉）只有倒计时、无层数概念，
        # 不应以 stacks>0 作为门槛，否则层数恒为0时永远不显示倒计时。
        if buff.get("single_layer"):
            should = True
        else:
            timer_display = buff.get("timer_display", "any_stack")
            stacks = int(buff.get("stacks", 0))
            if timer_display == "full_stack_only":
                should = self._is_buff_full_stack(buff)
            else:
                should = stacks > 0
        return should and isinstance(buff.get("timer"), (int, float)) and 0 <= buff["timer"] < 999

    def _is_buff_single_layer(self, buff):
        """buff 是否为单层（只有倒计时，无层数概念）。"""
        if buff.get("single_layer"):
            return True
        ms = buff.get("max_stacks")
        return ms is not None and ms <= 1

    def recalc_layout(self):
        # 分辨率自适应：以 1920x1080 为基准，屏幕越宽缩放越大，可在设置中关闭
        if bool(self.settings.get("resolution_auto_scale", DEFAULT_SETTINGS["resolution_auto_scale"])):
            screen = QApplication.primaryScreen()
            screen_w = screen.availableGeometry().width() if screen else 1920
            self.res_scale = max(1.0, screen_w / 1920.0)
        else:
            self.res_scale = 1.0
        self.circle_r = int(self.settings.get("circle_radius", DEFAULT_SETTINGS["circle_radius"]))
        # ── 尖刺 / 翻滚 / 技能 实时画布参数 ──
        # V20.08 修复：原本这部分被错放在 _migrate_pos_res()（一次性迁移函数）末尾，
        # 导致设置面板改尖刺 / 半径 / 翻转尺寸等任何一项都不会触发画布重算、也就
        # 没有实时反馈。这里把「每帧布局」真正该跑的代码搬回 recalc_layout()，
        # 每次 _after_settings_changed / 屏幕分辨率变化都会被调用一次。
        self.spike_len = int(self.settings.get("spike_length", DEFAULT_SETTINGS["spike_length"]))
        self.spike_axis_pos = int(self.settings.get("spike_axis_pos_percent", DEFAULT_SETTINGS["spike_axis_pos_percent"])) / 100.0
        self.spike_w = int(self.settings.get("spike_width", DEFAULT_SETTINGS["spike_width"]))
        self.spike_waist_pos = int(self.settings.get("spike_waist_pos_percent", DEFAULT_SETTINGS["spike_waist_pos_percent"])) / 100.0
        self.spike_bead_radius = int(self.settings.get("spike_bead_radius", DEFAULT_SETTINGS["spike_bead_radius"]))
        self.spike_bead_pos = int(self.settings.get("spike_bead_pos_percent", DEFAULT_SETTINGS["spike_bead_pos_percent"])) / 100.0
        self.indicator_outline_width = int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])) if bool(self.settings.get("use_indicator_outline", True)) else 0
        self.circle_pad_title = int(self.settings.get("circle_pad_title", DEFAULT_SETTINGS["circle_pad_title"]))
        scale = int(self.settings.get("dodge_icon_scale_percent", DEFAULT_SETTINGS["dodge_icon_scale_percent"]))
        self.dodge_icon_size = max(4, int(self.SHRIMP_BASE_SIZE * scale / 100))

        # ── 核心检测模块画布（标题栏 + 尖刺圆 + buff），不含翻滚/技能 ──
        # 「显示尖刺」/「显示装饰小球」只控制绘制（不画尖刺本体/外勾边），绝不压缩画布空间：
        # 若把 spike_*_pad 在 show_spikes=False 时缩小，整个 core_canvas_h / circle_cy 会跟着
        # 收缩，导致圆环、buff 名位置在勾选瞬间整体跳动。这里始终按有尖刺时计算、
        # 下沿只在 show_spikes 时额外预留 spike_len 给龙形/外描边，圆环、倒计时、文字与勾选前完全一致。
        outline_pad = max(0, self.indicator_outline_width + 2)
        spike_outer_extent = max(0, int((1.0 + self.spike_axis_pos) * self.spike_len))
        bead_outer_extent = self.spike_bead_radius + max(0, int(abs(self.spike_bead_pos) * self.spike_len))
        spike_side_extent = spike_outer_extent + max(self.spike_w // 2, self.spike_bead_radius) + outline_pad
        spike_top_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent) + outline_pad
        spike_bottom_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent) + outline_pad
        core_required_w = (self.circle_r + max(spike_side_extent, bead_outer_extent) + outline_pad + 10) * 2
        # 标题栏诊断文字完整显示，整体宽度给足
        self.core_canvas_w = max(self.CANVAS_W, int(core_required_w))
        self.core_canvas_h = (
            self.TITLE_BAR_H
            + self.circle_pad_title
            + spike_top_pad
            + self.circle_r * 2
            + spike_bottom_pad
        )
        self.circle_cx = self.core_canvas_w // 2
        base_cy = self.TITLE_BAR_H + self.circle_pad_title + self.circle_r + spike_top_pad
        # 核心监测区整体放大 CORE_AREA_MULT 倍（长/宽 ×1.35），并把圆构图垂直居中
        mult = self.CORE_AREA_MULT
        base_h = self.core_canvas_h
        self.core_canvas_h = int(base_h * mult)
        self.circle_cy = int(base_cy + (self.core_canvas_h - base_h) / 2.0)

        # V2240：核心画布宽/高可调——settings 里 >0 时覆盖自动计算值，并据新值重算圆心；
        # 内容（圆/标题/buff名）本就相对 core_canvas_w/h + circle_cx/cy 自适应布局，会自动重居中。
        # 强制下限防裁切：宽 ≥ max(CANVAS_W, core_required_w)；高 ≥ 自动预览值 × CORE_AREA_MULT。
        _cw_user = int(self.settings.get("core_canvas_w", 0) or 0)
        _ch_user = int(self.settings.get("core_canvas_h", 0) or 0)
        if _cw_user > 0:
            _cw_min = max(self.CANVAS_W, int(core_required_w))
            self.core_canvas_w = max(_cw_user, _cw_min)
            self.circle_cx = self.core_canvas_w // 2
        if _ch_user > 0:
            _ch_auto = (
                self.TITLE_BAR_H
                + self.circle_pad_title
                + spike_top_pad
                + self.circle_r * 2
                + spike_bottom_pad
            )
            _ch_min = int(_ch_auto * self.CORE_AREA_MULT)
            self.core_canvas_h = max(_ch_user, _ch_min)
            self.circle_cy = int(base_cy + (self.core_canvas_h - base_h) / 2.0)

        # ── 翻滚模块画布（独立窗口，横/竖可选）──
        roll_pad = 6
        horizontal = (self.settings.get("roll_orientation", "horizontal") != "vertical")
        if horizontal:
            self.roll_canvas_w = self.MAX_DODGES * self.dodge_icon_size + (self.MAX_DODGES - 1) * self.ROLL_ICON_GAP + 2 * roll_pad
            self.roll_canvas_h = self.dodge_icon_size + 2 * roll_pad
        else:
            self.roll_canvas_w = self.dodge_icon_size + 2 * roll_pad
            self.roll_canvas_h = self.MAX_DODGES * self.dodge_icon_size + (self.MAX_DODGES - 1) * self.ROLL_ICON_GAP + 2 * roll_pad
        self.roll_cx = self.roll_canvas_w / 2.0
        self.roll_cy = self.roll_canvas_h / 2.0

        # ── 能力冷却模块画布（独立窗口，4 菱形十字布局）──
        # V2237：spread 可负，但画布最小兜底改为 0 而非 half_diag+8——画布永远能装下 1 个菱形，
        # 但不再强行把 spread 拉到「覆盖中心」之外（玩家要的就是把菱形聚拢到中心）。
        skill_cd_spread = int(self.settings.get("skill_cd_spread", 70))
        skill_cd_size = int(self.settings.get("skill_cd_size", 18))
        half_diag = int(skill_cd_size * 1.5)
        eff_spread = max(skill_cd_spread, 0)
        skill_pad = 10
        self.skill_canvas_w = 2 * (eff_spread + half_diag + skill_pad)
        self.skill_canvas_h = self.skill_canvas_w
        self.skill_cx = self.skill_canvas_w / 2.0
        self.skill_cy = self.skill_canvas_h / 2.0

    def norm_pos(self, x, y):
        """保存位置前：当前分辨率下的真实像素 → 基准宽度(1920)归一化坐标。
        配合 res_scale（= 屏幕宽 / 1920），使窗口位置随分辨率等比迁移。"""
        rs = self.res_scale or 1.0
        return round(x / rs), round(y / rs)

    def denorm_pos(self, nx, ny):
        """读取位置后：基准宽度(1920)归一化坐标 → 当前分辨率下的真实像素。"""
        rs = self.res_scale or 1.0
        return int(round(nx * rs)), int(round(ny * rs))

    def _migrate_pos_res(self):
        """一次性迁移：旧版本(≤V703)保存的是「当前分辨率原始像素」位置；
        这里按当前 res_scale 归一化到基准宽度一次，避免存量用户升级后位置跳变。

        注意：本函数只负责位置迁移。画布尺寸 / 尖刺 / 翻滚 / 技能 等实时布局参数
        的计算已搬到 `recalc_layout()`——V20.08 修：原本它们被错放在本函数末尾、
        写在 `if pos_res_normalized:` 守卫之外，但本函数只在启动时调用一次，结果
        设置面板改尖刺 / 半径 / 翻滚尺寸等设置时画布不刷新（实时反馈失效）。"""
        if not self.settings.get("pos_res_normalized"):
            rs = self.res_scale or 1.0
            for key in ("core", "roll", "skill"):
                xk, yk = f"{key}_window_x", f"{key}_window_y"
                if xk in self.settings:
                    self.settings[xk] = round(self.settings[xk] / rs)
                if yk in self.settings:
                    self.settings[yk] = round(self.settings[yk] / rs)
            self.settings["pos_res_normalized"] = True
            try:
                save_settings(self.settings)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

    def load_dodge_icon(self):
        # V2313：换图后必须清空实心闪光缓存。旧版只在 __init__ 建一次缓存、此后永不失效，
        # 玩家换了 PNG（或改缩放/颜色）后闪光帧仍画旧图标的实心剪影——这就是「换图片闪光跟不上」的真因。
        try:
            self._dodge_solid_cache = {}
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        path = DEFAULT_SHRIMP_IMG_PATH if bool(self.settings.get("use_default_dodge_icon", True)) else self.settings.get("shrimp_img_path", DEFAULT_SHRIMP_IMG_PATH)
        self.shrimp = QPixmap(path)
        if not self.shrimp.isNull():
            _sz = getattr(self, "dodge_icon_size", self.SHRIMP_BASE_SIZE)
            self.shrimp = self.shrimp.scaled(
                _sz,
                _sz,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        # V2313：第 6/7 次的图片同步加载（内部已判断是否为图片模式）
        self.load_warning_icon()

    # ---- V2313：第 6/7 次「图片模式」----
    def _use_warning_image(self):
        """第 6/7 次是否用 PNG 代替程序绘制的警告三角形。"""
        try:
            return str(self.settings.get("dodge_warning_mode", DEFAULT_SETTINGS["dodge_warning_mode"])) != "triangle"
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            return False

    def load_warning_icon(self):
        """加载第 6/7 次图片模式用的 PNG（内置默认警告图 / 玩家自定义路径）。

        与 self.shrimp 完全对称：非图片模式或图无效时 self.dodge_warning_icon 为空 QPixmap，
        渲染端检测到空图会自动回退到警告三角形，绝不会留下空白槽位。
        """
        self.dodge_warning_icon = QPixmap()
        try:
            if not self._use_warning_image():
                return
            use_default = bool(self.settings.get("use_default_dodge_warning_icon", True))
            path = DEFAULT_WARNING_IMG_PATH if use_default else str(self.settings.get("dodge_warning_image_path", "") or "")
            if not path:
                return
            pm = QPixmap(path)
            if pm.isNull():
                return
            _sz = getattr(self, "dodge_icon_size", self.SHRIMP_BASE_SIZE)
            _wscale = int(self.settings.get("dodge_warning_icon_scale_percent", DEFAULT_SETTINGS["dodge_warning_icon_scale_percent"]))
            _sz = max(4, int(_sz * _wscale / 100))
            self.dodge_warning_icon = pm.scaled(
                _sz,
                _sz,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        except Exception:
            logger.debug("swallowed exception", exc_info=True)

    def _draw_pixmap_centered(self, painter, pm, x, y, box):
        """V2313：把 pm 等比缩放（只在超出时缩）并居中画进 (x, y, box, box) 方框。"""
        if pm is None or pm.isNull() or box <= 0:
            return False
        if pm.width() > box or pm.height() > box:
            pm = pm.scaled(box, box, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        dx = x + (box - pm.width()) / 2.0
        dy = y + (box - pm.height()) / 2.0
        painter.drawPixmap(int(round(dx)), int(round(dy)), pm)
        return True

    def _calc_icon_btn_rects(self):
        """计算标题栏图标按钮区域：
        - 居中(center)：历史默认布局，最小化/设置/锁定/退出 整体水平居中，版本号置于最小化左侧；
        - 靠左(left)：按 [锁定、关闭、设置、最小化、版本信息] 顺序从左往右排成一行，整体贴左；
        - 靠右(right)：同样顺序但整体贴右（锁定在最右，版本信息在最左）。
        """
        s = self.ICON_BTN_SIZE
        gap = self.ICON_BTN_GAP
        icon_row_h = self.ICON_BTN_SIZE + 10
        _align = self.settings.get("title_align", "left")
        _margin = 6
        _icon_indent = int(self.settings.get("titlebar_icon_indent", DEFAULT_SETTINGS["titlebar_icon_indent"]))
        y = (icon_row_h - s) // 2

        # 版本号文字宽度（左/右模式布局需要知道它占多宽）
        _vb = getattr(self, "update_brief", "") or ""
        ver_font = QFont("Segoe UI", max(6, int(self.settings.get("titlebar_font_size", DEFAULT_SETTINGS["titlebar_font_size"]))), QFont.Medium)
        ver_text = f"v{APP_VERSION}" + (f" · {_vb}" if _vb else "")
        ver_w = QFontMetrics(ver_font).horizontalAdvance(ver_text)

        if _align == "center":
            n = 4
            total_w = n * s + (n - 1) * gap
            start_x = (self.core_canvas_w - total_w) / 2.0
            if not self.locked:
                minimize_x = start_x
                settings_x = start_x + (s + gap)
                lock_x = start_x + 2 * (s + gap)
                exit_x = start_x + 3 * (s + gap)
            else:
                lock_x = (self.core_canvas_w - s) / 2.0
                minimize_x = settings_x = exit_x = -9999
            ver_x = None  # 居中模式版本号沿用 _draw_title_bar 旧逻辑
        else:
            if not self.locked:
                if _align == "left":
                    # 从左往右：锁定 -> 关闭 -> 设置 -> 最小化 -> 版本信息
                    lock_x = _margin + _icon_indent
                    exit_x = lock_x + (s + gap)
                    settings_x = exit_x + (s + gap)
                    minimize_x = settings_x + (s + gap)
                    ver_x = minimize_x + (s + gap)
                else:  # right：从右往左：锁定(最右) -> 关闭 -> 设置 -> 最小化 -> 版本信息(最左)
                    lock_x = self.core_canvas_w - _margin - s - _icon_indent
                    exit_x = lock_x - (s + gap)
                    settings_x = exit_x - (s + gap)
                    minimize_x = settings_x - (s + gap)
                    ver_x = minimize_x - gap - ver_w
            else:
                # 锁定态：仅 lock 图标，按对齐贴边
                if _align == "left":
                    lock_x = _margin + _icon_indent
                else:
                    lock_x = self.core_canvas_w - _margin - s - _icon_indent
                minimize_x = settings_x = exit_x = -9999
                ver_x = -9999
        return (
            QRect(int(minimize_x), int(y), s, s),
            QRect(int(settings_x), int(y), s, s),
            QRect(int(lock_x), int(y), s, s),
            QRect(int(exit_x), int(y), s, s),
            ver_x,
        )

    # ================================================================
    #  绘制：主事件
    # ================================================================
    # ================================================================
    #  剩余/持续时长分级小数格式化（V2251 新增；V2252 推广到全部模块倒计时）
    # ================================================================
    def _fmt_dur(self, v):
        """V2252：所有模块的倒计时/时长统一按「整数部分位数」分级显示小数——
          · 整数部分 1 位（|v| < 10，如 9.87）    → 2 位小数  → "9.87"
          · 整数部分 2 位（10 ≤ |v| < 100，如 12.3）→ 1 位小数 → "12.3"
          · 整数部分 >2 位（|v| ≥ 100，如 123.4） → 不带小数 → "123"
        取值用 abs() 判位数，负数（异常脏值）同样按位数套规则不至于撑爆卡片。

        全软件 5 处调用点（分布在 4 个辅助绘制方法里，改动务必全部覆盖，别漏）：
          1. `_draw_center_text`（核心模块 render_core 调用）单 buff 分支      —— f"{self._fmt_dur(timer_val)}s"
          2. `_draw_center_text`（核心模块 render_core 调用）融合/多 buff 分支 —— f"{self._fmt_dur(timer_val)}s"
          3. `_draw_skill_cd_element`（能力模块 render_skill 调用）           —— self._fmt_dur(cd_val)
          4. `_draw_allbuff_card`（全 Buff 模块 render_allbuff 调用）         —— self._fmt_dur(rem)/self._fmt_dur(init)
          5. `_draw_boss_card`（Boss 模块 render_bossbuff 调用）              —— self._fmt_dur(rem)/self._fmt_dur(init)
        ⚠️ 注意：真正画倒计时文本的是这 4 个 `_draw_*` 辅助方法，不是 render_core /
          render_skill / render_allbuff / render_bossbuff 这些入口——改的时候要进辅助方法里改。
        本方法定义在 render_core 之前，保证上述所有渲染方法都能调到。
        """
        _v = float(v or 0.0)
        _a = abs(_v)
        if _a < 10.0:
            return f"{_v:.2f}"   # <10：两位小数
        if _a < 100.0:
            return f"{_v:.1f}"   # 10~99：一位小数
        return f"{_v:.0f}"       # ≥100：不带小数

    # ================================================================
    #  绘制：核心检测模块（尖刺圆 + 标题栏 + buff），由 CoreWindow 调用
    # ================================================================
    def render_core(self, painter):
        cx, cy, r = self.circle_cx, self.circle_cy, self.circle_r
        # 仅尖刺圆模块可能隐藏：当「无buff隐藏」选项开启且主控角色当前没有任何 buff 实际激活（层数=0）时。
        # 注意：判定是「实际层数为 0」，而不是「active_buffs 列表为空」——
        # 一个 buff 即使被三阶专精全勾进 active_buffs，只要游戏里它的 stacks=0，
        # 仍然算"没有 buff"——这是狼奶奶反馈的 V2025 之前 bug。
        # 翻滚UI 与 冷却技能UI 永远显示，不受此影响。
        self.spike_hidden = bool(self.settings.get("spike_hide_when_no_buff", True)) and not self.active_buffs

        # 全局非战斗隐藏：仅作用于「内容区」（buff/技能/翻滚），标题栏（背景+图标+状态文字）始终保留。
        # 内容区乘数 = _ooc_content_mult（由 tick 中的 _sync_out_of_combat_visibility 计算）：
        #   >0  → 内容区按该不透明度半透明显示；
        #   <=0 → 内容区完全不绘制（仅剩顶部标题栏）。
        self._out_of_combat_mult = getattr(self, "_ooc_content_mult", 1.0)

        # 模块显示开关：未勾选核心检测模块时，仅保留标题栏（标题栏背景+图标+文字），
        # 不绘制下方内容区的背景框与内容
        show_core = bool(self.settings.get("show_core_module", True))
        if show_core:
            self._draw_backdrop(painter)
        else:
            self._draw_backdrop(painter, title_only=True)
        self._draw_title_bar(painter)

        if not show_core:
            return
        if self._out_of_combat_mult <= 0.0:
            return

        # V2032：撤销 V2031 的『列表非空但全 stacks=0 也归并进空 buff』语义——
        # 那是 V2026 _any_active_buff_stacks() 错用于 spike 隐藏判定的连锁假修复：
        # 用户原意是『active_buffs 真为空（没有任何 buff）』才考虑整圈隐，『已配满 buff
        # 但游戏里 stacks=0（buff 还没激活计数）』应仍正常显示圆环 + spike + 内部信息。
        # 此处恢复 `if self.active_buffs:`，spike_hidden 判定也恢复 `not self.active_buffs`（4226 行），
        # 标题栏 buff 名段恢复 `if not self.active_buffs:`（_build_titlebar_status_text 5028 行）——
        # 三处统一回到『仅看 active_buffs 列表本身，不看 stacks』的 V2025 语义。
        if self.active_buffs:
            n = len(self.active_buffs)
            if n == 1:
                # 单buff模式：正常大小，正常位置，正常颜色
                buff = self.active_buffs[0]
                is_lv7 = self._is_buff_full_stack(buff)
                self._render_buff_ui(painter, buff, cx, cy, r, is_lv7)
                self._draw_buff_name(painter, buff, cx, cy, r, 1.0)
            else:
                # 多buff差异化模式（最多同时监测 5 个）：
                # 水平均匀分布（圆心 x 等间距居中）+ 垂直 Delta_Y 错位（+ΔY,-ΔY,+ΔY,-ΔY…）
                cnt = min(n, 5)
                cfg = self._multi_buff_cfg(cnt)
                scale = cfg["scale"] / 100.0
                hgap = cfg["hgap"]
                dy = cfg["dy"]
                shown = self.active_buffs[:5]
                rtl = self.settings.get("buff_order_direction", "ltr") == "rtl"
                if rtl:
                    shown = list(reversed(shown))
                m = len(shown)
                for i, buff in enumerate(shown):
                    ix = cx + (i - (m - 1) / 2.0) * hgap
                    # 垂直错位也按当前整体缩放比例走，避免小圆圈配大 ΔY 导致名字脱节
                    iy = cy + (dy * scale if (i % 2 == 0) else -dy * scale)
                    is_lv7 = self._is_buff_full_stack(buff)
                    # 颜色按 buff 在 active_buffs 中的原始顺位（rank）分配，而非屏幕显示序号 i，
                    # 使“颜色随 buff 排序”在 ltr/rtl 下都正确跟随：正位（rank 0）恒为基准色，
                    # 选“越上越左”它在最左、选“越上越右”它在最右，颜色始终跟着该 buff 走。
                    rank_idx = (m - 1 - i) if rtl else i
                    override = self._make_index_color_override(rank_idx, cfg)
                    self._render_buff_ui(painter, buff, ix, iy, r, is_lv7, scale=scale,
                                         color_override=override, color_index=rank_idx)
                    self._draw_buff_name(painter, buff, ix, iy, r, scale, color_override=override)
        else:
            # 无任何可显示buff：绘制空的尖刺圆模块（受 spike_hidden 控制，可隐藏/变暗）
            self._draw_indicator_outer_outline(painter, cx, cy, r, False, include_spikes=self._spike_drawn())
            self._draw_circle(painter, cx, cy, r, False)

    def _render_buff_ui(self, painter, buff, cx, cy, r, is_lv7, scale=1.0,
                         color_override=None, color_index=0):
        """渲染一个完整的 buff UI 元素（圆环+尖刺+倒计时+中心文字）。"""
        is_single_layer = self._is_buff_single_layer(buff)
        painter.save()
        if scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        self._draw_glow(painter, cx, cy, r, is_lv7, color_override=color_override)
        include_spikes = not is_single_layer and self._spike_drawn()
        self._draw_indicator_outer_outline(painter, cx, cy, r, is_lv7,
                                           include_spikes=include_spikes,
                                           buff=buff, color_override=color_override)
        if not is_single_layer:
            self._draw_spikes(painter, cx, cy, r, is_lv7, buff=buff, color_override=color_override)
        self._draw_circle(painter, cx, cy, r, is_lv7, color_override=color_override)
        self._draw_timer_progress(painter, cx, cy, r, is_lv7, buff=buff,
                                   color_override=color_override, color_index=color_index)
        self._draw_center_text(painter, cx, cy, r, is_lv7, buff=buff,
                               is_single_layer=is_single_layer, color_override=color_override)
        painter.restore()

    def _draw_buff_name(self, painter, buff, cx, cy, r, scale, color_override=None):
        """在buff UI下方绘制buff名称（带反色圆角背景，独立缩放）。"""
        if not bool(self.settings.get("show_buff_name", True)):
            return
        name = _buff_name(buff, self.settings.get("language", "zh"))
        if not name:
            return
        name_hex = self._get_color("buff_name_color", color_override)
        name_opacity = self._effective_opacity("buff_name_color")
        font_size = max(1, int(self.settings.get("buff_name_font_size", 8) * scale))
        font = QFont("Segoe UI", font_size, QFont.Bold)
        painter.save()

        # 计算文字实际尺寸
        metrics = QFontMetrics(font)
        text_advance = metrics.horizontalAdvance(name)
        text_h = font_size + 2

        # 名字位置：以圆心为基准 + 用户偏移
        off_x = int(self.settings.get("buff_name_offset_x", 0) * scale)
        off_y = int(self.settings.get("buff_name_offset_y", 0) * scale)
        scaled_r = r * scale
        center_x = int(cx + off_x)
        center_y = int(cy + scaled_r + int(6 * scale) - off_y)

        # 圆角矩形背景（buff字体颜色的反色）
        pad_x = max(3, int(5 * scale))
        pad_y = max(1, int(2 * scale))
        bg_w = max(1, text_advance + pad_x * 2 + int(self.settings.get("buff_name_bg_width", 0) * scale))
        bg_h = text_h + pad_y * 2
        bg_x = int(center_x - bg_w / 2)
        bg_y = int(center_y - bg_h / 2)
        # 防止名字被窗口底部裁掉；若圆圈太低则名字上移（宁可重叠也要可见）
        max_y = getattr(self, "core_canvas_h", bg_y + bg_h) - bg_h
        bg_y = min(bg_y, max_y)
        bg_rect = QRect(bg_x, bg_y, bg_w, bg_h)
        radius = max(2, int(4 * scale))

        name_color = QColor(name_hex)
        inv_color = QColor(255 - name_color.red(), 255 - name_color.green(), 255 - name_color.blue())
        painter.setOpacity(name_opacity)
        painter.setPen(Qt.NoPen)
        painter.setBrush(inv_color)
        painter.drawRoundedRect(bg_rect, radius, radius)

        # 绘制文字
        painter.setPen(name_color)
        painter.setFont(font)
        painter.drawText(bg_rect, Qt.AlignCenter, name)
        painter.restore()

    # ==================== 技能冷却 UI ====================

    def render_skill(self, painter):
        """绘制4个技能冷却指示器（十字菱形布局：左1/上2/右3/下4）。

        能力模块已独立成单独窗口：菱形围绕本窗口画布中心（skill_cx/cy）排布，
        不受核心窗口坐标影响。
        """
        # 模块显示开关：由全局「模块显示」统一控制，未勾选能力冷却模块时，
        # 整个窗口（含背景框与占位文字）完全不绘制
        if not bool(self.settings.get("show_skill_cd_module", True)):
            return

        # 先画模块背景：即使没进游戏/无技能，也让窗口可见、可拖动
        self._draw_module_backdrop(painter, self.skill_canvas_w, self.skill_canvas_h, draw_border=True, module_key="skill")
        if self.status != "ok":
            self._draw_skill_placeholder(painter, self.status)
            return
        if not self.skill_cd_data:
            self._draw_skill_placeholder(painter, "no_skill")
            return
        # 与 render_core 相同：每次绘制前刷新非战斗内容乘数，
        # 保证 skill_win 独立重绘时（core_win 未重绘）也使用最新的隐藏状态
        self._out_of_combat_mult = getattr(self, "_ooc_content_mult", 1.0)
        cx, cy = self.skill_cx, self.skill_cy
        s = int(self.settings.get("skill_cd_size", 18))
        spread = int(self.settings.get("skill_cd_spread", 70))
        # 聚散距离直接生效（V2237：下限彻底解负，不再保留「half_diag+8」防菱形覆盖中心；
        # spread 可取任意值，负值时 4 个菱形向画布中心收缩甚至完全重叠）
        # 十字菱形：左1/上2/右3/下4
        positions = [
            (cx - spread, cy),       # 槽1 左
            (cx, cy - spread),       # 槽2 上
            (cx + spread, cy),       # 槽3 右
            (cx, cy + spread),       # 槽4 下
        ]
        enabled = bool(self.settings.get("skill_cd_breath_enabled", True))
        # 呼吸灯不透明度乘「非战斗隐藏」系数：与能力模块菱形同步隐藏/半透明
        # （非战斗隐藏不透明度=0 时乘数为 0 → alpha=0 → 不绘制，呼吸灯随菱形一起消失）
        base_opacity = max(0.0, min(1.0, int(self.settings.get("skill_cd_breath_color_opacity", 90)) / 100.0)) \
            * getattr(self, "_out_of_combat_mult", 1.0)
        # 第一遍：绘制所有菱形（不含名称），避免相邻菱形互相遮挡名称
        for i, (sx, sy) in enumerate(positions):
            if i < len(self.skill_cd_data):
                try:
                    self._draw_skill_cd_element(painter, self.skill_cd_data[i], sx, sy, draw_name=False)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
        # 第二遍：在每个就绪的技能菱形中心叠加同形呼吸光
        # 呼吸灯中心与技能菱形中心完全重合，作为发光层叠加在技能菱形上。
        # 形状、圆角、x/y 中心全部与技能菱形一致——视觉上就是技能菱形本身在呼吸。
        if enabled:
            for i, (sx, sy) in enumerate(positions):
                if i >= len(self.skill_cd_data):
                    continue
                sk = self.skill_cd_data[i]
                if sk.get("ready", True):
                    try:
                        self._draw_ready_breath(painter, sx, sy, s, base_opacity)
                    except Exception:
                        logger.debug("swallowed exception", exc_info=True)
        # 第三遍：统一把所有技能名称绘制在最顶层（置于顶层）
        if bool(self.settings.get("skill_cd_show_name", True)):
            for i, (sx, sy) in enumerate(positions):
                if i < len(self.skill_cd_data):
                    try:
                        self._draw_skill_cd_name(painter, self.skill_cd_data[i], sx, sy, s)
                    except Exception:
                        logger.debug("swallowed exception", exc_info=True)

    def _draw_skill_cd_element(self, painter, skill, cx, cy, draw_name=True):
        """绘制单个技能冷却元素：圆角菱形（旋转45°）+ 填满菱形的扇形倒计时 + 名称 + 完成动画。"""
        s = int(self.settings.get("skill_cd_size", 18))
        cd_val = skill.get("cd", 0)
        ready = skill.get("ready", True)
        cd_max = skill.get("cd_max", 0)

        # 完成动画进度
        anim_scale = 1.0
        anim_color = None
        anim_idx = skill.get("slot", 0)
        anim_start = self._skill_ready_anim[anim_idx] if anim_idx < 4 else None
        if anim_start is not None:
            dur = int(self.settings.get("flash_duration_ms", 400))
            elapsed = int(time.time() * 1000) - anim_start
            if elapsed < dur:
                progress = elapsed / dur
                # 先放大再缩回
                ready_scale = int(self.settings.get("flash_scale", 140)) / 100.0
                if progress < 0.3:
                    anim_scale = 1.0 + (ready_scale - 1.0) * (progress / 0.3)
                else:
                    anim_scale = ready_scale - (ready_scale - 1.0) * ((progress - 0.3) / 0.7)
                anim_color = self.settings.get("flash_color", "#ffffff")
            else:
                self._skill_ready_anim[anim_idx] = None

        # 颜色
        base_color_hex = anim_color if anim_color else self.settings.get("skill_cd_color", "#55aaff")
        base_opacity = self._effective_opacity("skill_cd_color") if not anim_color else 1.0

        half = s
        radius = max(3, s // 4)
        d = half * math.sqrt(2.0)  # 菱形半对角线

        painter.save()  # A：整体不透明度 + 完成动画缩放
        painter.setOpacity(base_opacity)

        # 缩放（完成动画）
        if anim_scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(anim_scale, anim_scale)
            painter.translate(-cx, -cy)

        # 就绪呼吸光：移到 render_skill 在 4 菱形中心绘制一次（不逐菱形重复）
        # 在旋转45°坐标系下绘制菱形（背景/扇形/边框），文字保持正向不旋转
        painter.save()  # R：旋转坐标系
        painter.translate(cx, cy)
        painter.rotate(45)
        painter.translate(-cx, -cy)

        # 轴对齐圆角矩形，旋转后即为圆角菱形
        rect = QRectF(cx - half, cy - half, half * 2, half * 2)

        # 裁剪进菱形
        painter.save()
        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip_path)

        # 背景
        bg_color = qcolor(base_color_hex)
        bg_color.setAlpha(int(self.settings.get("skill_cd_bg_opacity", 16) * 255 / 100))
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, radius, radius)

        # 扇形进度：圆形扇形被菱形裁剪 → 显示为「冷却进度」（从空逐渐填满，填满即就绪）
        big = int(d * 1.5)
        pie_rect = QRect(cx - big, cy - big, big * 2, big * 2)
        sector_alpha = int(self.settings.get("skill_cd_sector_opacity", 53) * 255 / 100)
        sector_color = qcolor(base_color_hex)
        painter.setPen(Qt.NoPen)
        # 扇形起始角写死 135°（用户实测确认 0 点=顶部尖角方向），乘以16转成 Qt 1/16度单位。
        pie_start = 135 * 16
        if not ready and cd_max > 0:
            # 填充语义翻转：扇形代表「冷却进度」而非「剩余冷却」。
            # cd_val=cd_max(刚进入冷却) → 进度0 → 扇形为空；
            # cd_val→0(即将就绪) → 进度→1 → 扇形逐渐填满；就绪走下方 full 分支画满。
            remaining_ratio = max(0.0, min(1.0, cd_val / cd_max))
            fill_ratio = 1.0 - remaining_ratio
            sector_color.setAlpha(sector_alpha)
            painter.setBrush(sector_color)
            painter.drawPie(pie_rect, pie_start, int(fill_ratio * 360 * 16))
        elif ready:
            # 就绪：完整填充
            sector_color.setAlpha(sector_alpha)
            painter.setBrush(sector_color)
            painter.drawPie(pie_rect, pie_start, int(-1.0 * 360 * 16))
        painter.restore()  # 取消裁剪

        # 立体边框（菱形轮廓）：外暗边 + 主色边 + 内高光，营造凸起立体感
        border_alpha = int(self.settings.get("skill_cd_border_opacity", 71) * 255 / 100)
        bw = float(self.settings.get("skill_cd_border_scale", 1.35))  # 边框粗细倍数
        # 1) 外暗边（向右下偏移 1px，模拟厚度/投影）—— 在旋转坐标系下即斜向暗边，仍读为立体
        painter.setPen(QPen(QColor(0, 0, 0, 120), 2 * bw))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1.0, 1.0, 1.0, 1.0), radius, radius)
        # 2) 主色边
        border_color = qcolor(base_color_hex)
        border_color.setAlpha(border_alpha)
        painter.setPen(QPen(border_color, 1.5 * bw))
        painter.drawRoundedRect(rect, radius, radius)
        # 3) 内高光（左上提亮，模拟受光面）
        painter.setPen(QPen(QColor(255, 255, 255, 130), 1 * bw))
        painter.drawRoundedRect(rect.adjusted(-1.0, -1.0, -1.0, -1.0), max(1, radius - 1), max(1, radius - 1))

        painter.restore()  # R：取消旋转

        # 胶囊（倒计时文字）—— 正常方向，不随菱形旋转；就绪时连胶囊一起隐藏
        if not ready:
            timer_text = self._fmt_dur(cd_val)
            # 倒计时字号：手动固定值（不再自动推算）
            font_size = int(self.settings.get("skill_cd_font_size", 12))
            if font_size < 6:
                font_size = 12
            cap_font = QFont("Segoe UI", font_size, QFont.Bold)
            cap_metrics = QFontMetrics(cap_font)
            # 时间胶囊宽度：在自动推算宽度基础上微调（Δ；0=不微调，可负）
            auto_cap_w = min(s * 2 - 6, max(16, cap_metrics.horizontalAdvance(timer_text) + 8))
            cap_w = max(8, auto_cap_w + int(self.settings.get("skill_cd_capsule_width", 0)))
            cap_h = max(12, int(font_size * 1.6))
            cap_rect = QRect(int(cx - cap_w / 2), int(cy - cap_h / 2), cap_w, cap_h)
            timer_off_x = int(self.settings.get("skill_cd_timer_offset_x", 0))
            timer_off_y = int(self.settings.get("skill_cd_timer_offset_y", 0))
            cap_rect.translate(timer_off_x, -timer_off_y)
            cap_bg = qcolor(self.settings.get("skill_cd_capsule_bg", "#0a0e1a"))
            cap_alpha = int(self.settings.get("skill_cd_capsule_opacity", 63) * 255 / 100)
            cap_bg.setAlpha(cap_alpha)
            cap_border = qcolor(self.settings.get("skill_cd_capsule_border", base_color_hex))
            cap_border.setAlpha(cap_alpha)
            painter.setPen(QPen(cap_border, 1))
            painter.setBrush(cap_bg)
            painter.drawRoundedRect(cap_rect, 4, 4)
            painter.setOpacity(self._effective_opacity("skill_cd_text_color"))
            text_color_hex = self.settings.get("skill_cd_text_color", "#ffffff")
            if cd_val < 3:
                text_color_hex = "#00ff44"
            painter.setPen(qcolor(text_color_hex))
            painter.setFont(cap_font)
            painter.drawText(cap_rect, Qt.AlignCenter, timer_text)

        painter.restore()  # A

        # 技能名称（不受缩放影响）
        # 默认在元素内绘制；render_skill 会用 draw_name=False 做两遍绘制，
        # 第二遍统一把名称画在所有菱形之上，确保「能力buff名称置于顶层」。
        if draw_name and bool(self.settings.get("skill_cd_show_name", True)):
            self._draw_skill_cd_name(painter, skill, cx, cy, s)

    def _draw_ready_breath(self, painter, cx, cy, s, base_opacity):
        """就绪呼吸光：在技能菱形下方绘制同形圆角菱形呼吸光。

        (cx,cy) 为呼吸光中心；形状为旋转 45° 圆角矩形（与技能菱形完全一致），
        填充径向渐变，按 freq/soft 呼吸。
        可调项：skill_cd_breath_color / 峰值不透明度 / freq(Hz) / soft / scale。
        soft 同时控制核心渐变半径与外发光扩散范围，效果肉眼可见。
        """
        color_hex = self.settings.get("skill_cd_breath_color", "#ffcc00")
        col = qcolor(color_hex)
        peak = int(max(0.0, min(1.0, base_opacity)) * 255)
        freq = float(self.settings.get("skill_cd_breath_freq", 0.5))
        soft = max(0.0, min(3.0, float(self.settings.get("skill_cd_breath_soft", 1.0))))
        scale = float(self.settings.get("skill_cd_breath_scale", 1.0))
        phase = (math.sin(2.0 * math.pi * freq * time.time()) + 1.0) / 2.0
        alpha = int(peak * (0.25 + 0.75 * phase))
        if alpha <= 0:
            return
        # 圆角菱形大小：默认与技能菱形同大（scale=1.0 → half=s），完全同形叠加
        half = s * scale
        radius = max(2, int(half * 0.25))
        # 旋转 45° 画圆角矩形（与技能菱形绘制方式完全一致）
        painter.save()
        painter.setOpacity(1.0)
        painter.setPen(Qt.NoPen)
        painter.translate(cx, cy)
        painter.rotate(45)
        painter.translate(-cx, -cy)
        rect = QRectF(cx - half, cy - half, half * 2, half * 2)
        # soft 影响核心光半径：soft 越大越扩散
        core_r = half * (1.0 + soft * 0.8)
        grad = QRadialGradient(cx, cy, core_r)
        c = QColor(col); c.setAlpha(alpha)
        grad.setColorAt(0.0, c)
        c2 = QColor(col); c2.setAlpha(int(alpha * 0.45))
        grad.setColorAt(0.55, c2)
        c3 = QColor(col); c3.setAlpha(0)
        grad.setColorAt(1.0, c3)
        painter.setBrush(grad)
        painter.drawRoundedRect(rect, radius, radius)
        # 外发光层：soft 越大，光晕越大越柔和
        if soft > 0.3:
            glow_r = core_r * (1.0 + soft * 0.6)
            glow = QRadialGradient(cx, cy, glow_r)
            g_alpha = int(alpha * 0.22 * min(soft, 1.5))
            gc = QColor(col); gc.setAlpha(g_alpha)
            glow.setColorAt(0.0, gc)
            gc2 = QColor(col); gc2.setAlpha(int(g_alpha * 0.35))
            glow.setColorAt(0.65, gc2)
            gc3 = QColor(col); gc3.setAlpha(0)
            glow.setColorAt(1.0, gc3)
            painter.setBrush(glow)
            painter.drawRoundedRect(rect, radius, radius)
        painter.restore()

    def _draw_skill_cd_name(self, painter, skill, cx, cy, s):
        """绘制技能名称（带反色圆角背景，类似Buff名）。"""
        lang = self.settings.get("language", "zh")
        name = _skill_name(skill.get("ability_hash", 0), lang, self.pl_id, skill.get("slot"))
        if not name:
            return
        name_hex = self.settings.get("skill_cd_name_color", "#aaccff")
        name_opacity = self._effective_opacity("skill_cd_name_color")
        font_size = max(1, int(self.settings.get("skill_cd_name_font_size", 7)))
        font = QFont("Segoe UI", font_size, QFont.Bold)
        painter.save()
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(name)
        text_h = font_size + 2
        off_x = int(self.settings.get("skill_cd_name_offset_x", 0))
        off_y = int(self.settings.get("skill_cd_name_offset_y", 0))
        bg_pad_x = max(2, font_size // 2)
        bg_pad_y = max(1, font_size // 4)
        bg_w = max(1, text_w + bg_pad_x * 2 + int(self.settings.get("skill_cd_name_bg_width", 0)))
        bg_h = text_h + bg_pad_y * 2
        bg_x = int(cx - bg_w / 2 + off_x)
        bg_y = int(cy + s + 4 - off_y)
        bg_rect = QRect(bg_x, bg_y, bg_w, bg_h)
        radius = max(2, font_size // 2)
        name_color = qcolor(name_hex)
        inv_color = QColor(255 - name_color.red(), 255 - name_color.green(), 255 - name_color.blue())
        painter.setOpacity(name_opacity)
        painter.setPen(Qt.NoPen)
        painter.setBrush(inv_color)
        painter.drawRoundedRect(bg_rect, radius, radius)
        painter.setPen(name_color)
        painter.setFont(font)
        painter.drawText(bg_rect, Qt.AlignCenter, name)
        painter.restore()

    # 外部颜色（圆环/尖刺/外描边）和内部颜色（弧线/数字/计时文字）
    EXTERNAL_COLOR_KEYS = {"circle_color_normal", "circle_color_lv7",
                           "spike_color_normal", "spike_color_lv7",
                           "indicator_outline_color"}
    INTERNAL_COLOR_KEYS = {"arc_color", "text_color",
                           "dh_text_outline_color", "timer_text_color",
                           "single_timer_text_color",
                           "buff_name_color",
                           "text_color_timer", "dh_text_outline_color_timer"}

    # ---- 多buff差异化（按 buff 个数分组）----
    # 每个额外 buff（index>=1）按预设色相旋转角度生成差异化颜色覆盖；
    # index 0 使用基础色（无覆盖）。外部/内部差异化开关分别控制是否对
    # 圆环/尖刺/外描边 与 弧线/数字/计时文字 应用旋转。
    _MB_HUE_OFFSETS = {1: 180, 2: 60, 3: 240, 4: 120}

    def _multi_buff_cfg(self, cnt):
        """返回某 buff 个数（2/3/4/5）对应的多buff布局配置。"""
        k = lambda s: f"multi_buff_{s}_{cnt}"
        return {
            "scale": int(self.settings.get(k("scale"), DEFAULT_SETTINGS[k("scale")])),
            "hgap": int(self.settings.get(k("hgap"), DEFAULT_SETTINGS[k("hgap")])),
            "dy": int(self.settings.get(k("dy"), DEFAULT_SETTINGS[k("dy")])),
            "ext": bool(self.settings.get(k("ext_color"), DEFAULT_SETTINGS[k("ext_color")])),
            "int": bool(self.settings.get(k("int_color"), DEFAULT_SETTINGS[k("int_color")])),
            "color_mode": self.settings.get(k("color_mode"), DEFAULT_SETTINGS[k("color_mode")]),
            "mono_span": int(self.settings.get(k("mono_span"), DEFAULT_SETTINGS[k("mono_span")])),
        }

    def _make_index_color_override(self, index, cfg):
        """为第 index 个 buff（index 从 0 起）生成颜色覆盖；index 0 返回 None（用基础色）。"""
        if index <= 0:
            return None
        if cfg.get("color_mode") == "monochrome":
            # 同色系：按 index 依次偏离基础色相，间距由用户实时调节
            deg = (index * cfg.get("mono_span", 15)) % 360
        else:
            # 色环均匀分布（大反差/对称）
            deg = self._MB_HUE_OFFSETS.get(index, (index * 72) % 360)
        override = {}
        if cfg["ext"]:
            for key in self.EXTERNAL_COLOR_KEYS:
                override[key] = rotate_hue(self.settings.get(key, "#ffffff"), deg)
        if cfg["int"]:
            # 层数数字(text_color / text_color_timer)默认白(#ffffff, s=0)，rotate_hue 对零饱和度是空操作
            # → 数字永远白色、不参与差异化，只剩勾边变色，破坏「同色系」一致性。
            # 因此当旋转无效时，用同色系勾边色相生成「亮色填充」，让数字也参与差异化且与勾边同色系可辨。
            _TEXT_TO_OUTLINE = {"text_color": "dh_text_outline_color",
                                "text_color_timer": "dh_text_outline_color_timer"}
            for key in self.INTERNAL_COLOR_KEYS:
                base = self.settings.get(key, "#ffffff")
                rot = rotate_hue(base, deg)
                if rot == base and key in _TEXT_TO_OUTLINE:
                    _oh = QColor(rotate_hue(self.settings.get(_TEXT_TO_OUTLINE[key], "#7d2a00"), deg))
                    _h, _s, _v, _a = _oh.getHsv()
                    if _h < 0:
                        _h = 0
                    _fill = QColor()
                    _fill.setHsv(_h, min(int(_s) if _s else 120, 120), 245, _a)
                    rot = _fill.name()
                override[key] = rot
        # arc_color 严格按 int 开关控制：之前为了让弧形不"脱节"加了「ext/int 任一开启
        # 就跟着差异化」的兜底，结果变成「关了内部差异化但倒计时表盘仍变色」的 bug——
        # 用户明确要求 int 不勾时，倒计时表盘必须保持基础色，不跟随 ext 联动。
        return override

    def _get_color(self, key, color_override=None):
        """获取颜色十六进制值，支持补色覆盖。"""
        if color_override and key in color_override:
            return color_override[key]
        return self.settings.get(key, "#ffffff")

    # ================================================================
    #  绘制：一体化圆角半透明背景（标题栏独立色 + 内容区独立色）
    # ================================================================
    def _draw_backdrop(self, painter, title_only=False):
        """一体化圆角半透明背景。title_only=True 时只绘制标题栏区域（用于核心模块隐藏时仍保留标题栏）。"""
        backdrop_bottom = self.TITLE_BAR_H if title_only else self.core_canvas_h

        title_hex = self.settings.get("title_bar_color", "#1a2030")

        path = QPainterPath()
        path.addRoundedRect(
            0, 0,
            self.core_canvas_w, backdrop_bottom,
            self.BACKDROP_RADIUS, self.BACKDROP_RADIUS,
        )

        # 内容区背景（写死：锁定→0，未锁定→黑色10%）
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor("#000000"))
        painter.setOpacity(0.0 if self.locked else 0.08)
        painter.drawPath(path)

        # 标题栏区域（裁剪到圆角路径内，仅填充顶部一条）
        # 锁定后标题栏背景完全不透明=0；锁头图标保持原色/原不透明度用于解锁。
        painter.setClipPath(path)
        title_opacity = 0.0 if self.locked else self._effective_opacity("title_bar_color")
        painter.setOpacity(title_opacity)
        painter.setBrush(qcolor(title_hex))
        painter.drawRect(0, 0, self.core_canvas_w, self.TITLE_BAR_H)
        painter.restore()

        # 白色勾边（15% 不透明度）—— 即使背景很淡，也能看清窗口轮廓；锁定后消失
        painter.save()
        painter.setPen(QPen(qcolor("#FFFFFF"), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.setOpacity(0.0 if self.locked else 0.15)
        painter.drawPath(path)
        painter.restore()

    def _draw_module_backdrop(self, painter, width, height, draw_border=True, module_key="roll"):
        """独立模块窗口（翻滚/能力）的统一圆角背景。

        背景写死：锁定后不透明度=0，未锁定时黑色、不透明度=5%（无参数）。
        模块窗没有标题栏等可见抓手，但窗口内容（图标/技能格）本身以满不透明度绘制，
        因此即使背景很淡，仍可凭内容定位并拖动/四角缩放。
        同时绘制一条细边框，让窗口轮廓在复杂游戏背景下更清晰。
        """
        bg_hex = "#000000"
        opacity = 0.0 if self.locked else 0.08
        painter.save()
        path = QPainterPath()
        path.addRoundedRect(0, 0, width, height, self.BACKDROP_RADIUS, self.BACKDROP_RADIUS)
        # 背景填充
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor(bg_hex))
        painter.setOpacity(opacity)
        painter.drawPath(path)
        # 白色勾边（15% 不透明度）—— 即使背景很淡也能看清窗口轮廓；锁定后消失
        if draw_border and not self.locked:
            border_color = qcolor("#FFFFFF")
            border_color.setAlphaF(0.15)
            pen = QPen(border_color)
            pen.setWidthF(max(1.0, 1.5))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawPath(path)
        painter.restore()

    def _draw_skill_placeholder(self, painter, reason):
        """能力冷却模块空状态提示：高对比度白字+黑描边，确保用户一定能看到窗口在哪里。"""
        # 未检测到角色：不显示任何提示文字，仅保留模块背景以便拖动/缩放
        if reason == "no_char":
            return
        lang = self.settings.get("language", "zh")
        if reason == "hidden":
            texts = {"zh": "能力冷却已隐藏", "zh_tw": "能力冷卻已隱藏", "en": "Skill CD hidden"}
        elif reason == "no_game":
            return  # 不显示「等待游戏...」占位文字，仅保留窗口背景以便拖动/缩放
        elif reason == "init":
            texts = {"zh": "初始化中...", "zh_tw": "初始化中...", "en": "Initializing..."}
        else:
            texts = {"zh": "未检测到技能", "zh_tw": "未偵測到技能", "en": "No skills detected"}
        text = texts.get(lang, texts["zh"])

        cx, cy = self.skill_cx, self.skill_cy
        font_size = max(10, int(self.skill_canvas_w / 11))
        font = QFont("Segoe UI", font_size, QFont.Bold)
        painter.save()
        painter.setFont(font)
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text)
        th = metrics.height()
        x = int(cx - tw / 2)
        y = int(cy + th / 4)
        # 黑色描边（上下左右各偏移 1px）
        painter.setPen(QColor(0, 0, 0, 220))
        for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1), (0, -1), (0, 1), (-1, 0), (1, 0)]:
            painter.drawText(x + dx, y + dy, text)
        # 白色主文字
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(x, y, text)
        painter.restore()

    # ================================================================
    #  绘制：标题栏（状态点/状态文字 + 图标按钮）
    # ================================================================
    def _draw_title_bar(self, painter):
        th = self.TITLE_BAR_H
        lang = self.settings.get("language", "zh")

        # 标题栏文本统一字体大小（第二行状态文字与版本号共用此设置）
        titlebar_font_size = max(6, int(self.settings.get("titlebar_font_size", DEFAULT_SETTINGS["titlebar_font_size"])))

        # 图标按钮区域（最小化、设置、锁定、退出，从左到右）
        minimize_rect, settings_rect, lock_rect, exit_rect, ver_x = self._calc_icon_btn_rects()
        hidden_rect = QRect(-9999, -9999, 0, 0)
        # 窗口局部像素版命中矩形（与 paintEvent 的 painter.scale(disp_w) 对应：画布坐标×disp = 窗口像素）
        # 用窗口局部像素直接命中，避免 event.position() 先除 disp_w 再比画布矩形的换算误差（释放不触发）
        disp = getattr(getattr(self, "core_win", None), "disp_w", 1.0) or 1.0
        hit_m = 2  # 命中容差（窗口像素），补偿按下到释放间的极微位移取整
        def _to_win(r):
            return QRect(int(r.x() * disp) - hit_m, int(r.y() * disp) - hit_m,
                         int(r.width() * disp) + 2 * hit_m, int(r.height() * disp) + 2 * hit_m)
        self._btn_minimize_rect_win = hidden_rect if self.locked else _to_win(minimize_rect)
        self._btn_settings_rect_win = hidden_rect if self.locked else _to_win(settings_rect)
        # 锁定图标始终显示且必须可点击（用于解锁），其窗口命中矩形不能因为 locked 而变成空矩形
        self._btn_lock_rect_win = _to_win(lock_rect)
        self._btn_exit_rect_win = hidden_rect if self.locked else _to_win(exit_rect)

        icon_color = QColor(self.settings.get("icon_color", "#7f8fa6"))

        # 当前被按住的按钮（按下反馈）：仅 CoreWindow 场景有效
        # 注意：_draw_title_bar 是 GBFROverlayQt 控制器的方法，状态存在 self 上
        # 按下即锁定 _pressed_core_btn；_pressed_visual 仅在指针仍位于该按钮内时为 True（决定凹陷视觉）
        pressed = getattr(self, "_pressed_core_btn", None) if getattr(self, "_pressed_visual", False) else None

        painter.save()
        painter.setOpacity(self._effective_opacity("icon_color"))

        if not self.locked:
            # 标题栏状态文字（锁定时隐藏）：放在图标行下方的「文本层」，水平居中
            if self.settings.get("show_titlebar_status", True):
                status_text = self._build_titlebar_status_text(lang)
                if status_text:
                    icon_row_h = self.ICON_BTN_SIZE + 10
                    _mt = 6
                    _indent = int(self.settings.get("titlebar_status_indent", DEFAULT_SETTINGS["titlebar_status_indent"]))
                    _align_mode = self.settings.get("title_align", "left")
                    _halign = {"left": Qt.AlignLeft, "right": Qt.AlignRight}.get(
                        _align_mode, Qt.AlignHCenter)
                    # 按对齐方向施加缩进：靠左→左边多空_indent；靠右→右边多空_indent
                    if _align_mode == "left":
                        text_rect = QRect(_mt + _indent, icon_row_h, self.core_canvas_w - _mt - _indent, th - icon_row_h)
                    elif _align_mode == "right":
                        text_rect = QRect(_mt, icon_row_h, self.core_canvas_w - 2 * _mt - _indent, th - icon_row_h)
                    else:
                        # 居中模式不缩进（保持原行为）
                        text_rect = QRect(_mt, icon_row_h, self.core_canvas_w - 2 * _mt, th - icon_row_h)
                    painter.setPen(QColor(self.settings.get("icon_color", "#7f8fa6")))
                    painter.setFont(QFont("Segoe UI", titlebar_font_size, QFont.Bold))
                    painter.drawText(text_rect, _halign | Qt.AlignVCenter, status_text)

            # 版本号（小字，跟随图标色/不透明度）+ 实时更新状态
            # 字体大小与标题栏第二行状态文字共用 titlebar_font_size 设置
            ver_font = QFont("Segoe UI", titlebar_font_size, QFont.Medium)
            painter.setFont(ver_font)
            brief = getattr(self, "update_brief", "") or ""
            ver_text = f"v{APP_VERSION}" + (f" · {brief}" if brief else "")
            ver_metrics = QFontMetrics(ver_font)
            ver_w = ver_metrics.horizontalAdvance(ver_text)
            ver_h = ver_metrics.height()
            _align = self.settings.get("title_align", "left")
            if _align == "center":
                # 居中模式：版本号置于最小化图标左侧（历史行为，与旧版一致）
                ver_x = minimize_rect.x() - ver_w - 6
                _ver_ok = ver_x > 2
            else:
                # 左/右模式：版本号位置已由 _calc_icon_btn_rects 按对齐算好（ver_x 为左边缘）
                if _align == "left":
                    _ver_ok = ver_x + ver_w <= self.core_canvas_w - 2
                else:
                    _ver_ok = ver_x > 2
            ver_y = minimize_rect.y() + (minimize_rect.height() - ver_h) // 2
            if _ver_ok:  # 只有空间够时才画（避免与窗口边缘重叠）
                painter.setPen(QColor(self.settings.get("icon_color", "#7f8fa6")))
                painter.drawText(QRect(int(ver_x), ver_y, ver_w, ver_h), Qt.AlignLeft | Qt.AlignVCenter, ver_text)

            # 按下态凹陷背景（在画图标前先铺底）
            for name, rect in (("minimize", minimize_rect), ("settings", settings_rect), ("exit", exit_rect)):
                if pressed == name:
                    self._draw_btn_press_bg(painter, rect)

            # 最小化图标：横线（按下时整体下移 1px，呈「按进去」感）
            self._draw_icon_minimize(painter, minimize_rect.translated(1, 1) if pressed == "minimize" else minimize_rect, icon_color)
            # 设置图标：圆角矩形 + S
            self._draw_icon_settings(painter, settings_rect.translated(1, 1) if pressed == "settings" else settings_rect, icon_color)
            # 退出图标：X
            self._draw_icon_exit(painter, exit_rect.translated(1, 1) if pressed == "exit" else exit_rect, icon_color)

        # 锁定图标（始终显示）
        if pressed == "lock":
            self._draw_btn_press_bg(painter, lock_rect)
        # 锁定后：在锁头图标背后加一个同标题栏颜色/不透明度的圆角背景布，提示更明显
        if self.locked:
            painter.save()
            bar_color = QColor(self.settings.get("title_bar_color", "#2c3e50"))
            bar_opacity = int(self.settings.get("title_bar_color_opacity", 100)) / 100.0
            bar_color.setAlphaF(bar_opacity)
            painter.setPen(Qt.NoPen)
            painter.setBrush(bar_color)
            bg_rect = lock_rect.adjusted(-3, -3, 3, 3)
            painter.drawRoundedRect(bg_rect, 5, 5)
            painter.restore()
        # 锁头保持锁定前的颜色/不透明度，仅形状切换为锁定图标
        lock_icon_color = icon_color
        self._draw_icon_lock(painter, lock_rect.translated(1, 1) if pressed == "lock" else lock_rect, lock_icon_color, self.locked)

        painter.restore()

    def _draw_btn_press_bg(self, painter, rect):
        """标题栏图标被按下时的凹陷/高亮背景，营造「按下去」的反馈。"""
        painter.save()
        painter.setOpacity(0.4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 255))
        painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 4, 4)
        # 顶部受光高光，强化凹陷立体感
        painter.setOpacity(0.25)
        painter.setBrush(QColor(255, 255, 255, 255))
        painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 0), 4, 4)
        painter.restore()

    def _build_titlebar_status_text(self, lang="zh"):
        """构建标题栏状态文字：角色名 + 最高阶专精 + 启用的buff名称和层数。
        格式：菲莉-真谛: 孤高幽灵-(应出现的buff)
        V2027: 判定从 `not self.active_buffs` 改为 `not self._any_active_buff_stacks()`，
        与 render_core 中 spike 隐藏判定保持一致——勾选「无 buff 隐藏尖刺」时，
        标题栏 buff 名段也同步隐藏（之前只藏圆环，buff 名段残留 → 狼奶奶/希耶提反馈「只剩 buff 名」）。
        """
        if self.status == "no_game":
            return ""  # 不显示「等待游戏...」，避免能力/标题栏出现该占位文字
        if self.status == "no_char" or not (self.char_type or self.charid_hash):
            if lang == "en": return "No character"
            if lang == "zh_tw": return "未偵測到角色"
            return "未检测到角色"
        char_name = _resolve_char(self.charid_hash, self.char_type, lang)[0]
        # 最高阶专精段：角色名-真谛: 孤高幽灵
        # MASTERY_BRANCHES 里的专精名已带"真谛："/"觉醒："/"秘义："前缀（zh）
        # 或 "Essence: "/"Insight: "/"Crux: "（en），需剥掉再接我们的"真谛: "前缀
        mastery_seg = ""
        cur = getattr(self, "current_mastery", None)
        if cur and self.pl_id and self.pl_id in MASTERY_BRANCHES:
            cat_base = {"awakening": "觉醒", "truth": "真谛", "secret": "秘义"}.get(cur, "")
            cat_label = _tr(cat_base, lang) if cat_base else ""
            branch_info = MASTERY_BRANCHES[self.pl_id].get(cur, {})
            branch_name = branch_info.get(lang, branch_info.get("zh", "")) if isinstance(branch_info, dict) else ""
            # 剥前缀：zh="真谛："/"觉醒："/"秘义："，en="Essence: "/"Insight: "/"Crux: "
            prefixes = [
                cat_base + "：", cat_base + ":",
                _tr(cat_base, "zh_tw") + "：",
                {"awakening": "Insight", "truth": "Essence", "secret": "Crux"}.get(cur, "") + ": ",
            ]
            for prefix in prefixes:
                if prefix and branch_name.startswith(prefix):
                    branch_name = branch_name[len(prefix):].lstrip()
                    break
            if cat_label and branch_name:
                mastery_seg = f"-{cat_label}: {branch_name} "
        if not self.active_buffs:  # V2032: 撤销 V2027 的 _any_active_buff_stacks() 误用，恢复 V2025 语义
            return f"{char_name}{mastery_seg}"
        buff_parts = []
        for buff in self.active_buffs:
            name = _buff_name(buff, lang)
            stacks = int(buff.get("stacks", 0))
            max_s = buff.get("max_stacks")
            if max_s and max_s > 1:
                buff_parts.append(f"{name} {stacks}/{max_s}")
            else:
                buff_parts.append(name)
        return f"{char_name}{mastery_seg}-({ ' + '.join(buff_parts) })"

    def _draw_icon_minimize(self, painter, rect, color):
        """标题栏最小化图标。"""
        cx = rect.center().x()
        cy = rect.center().y()
        d = 5
        painter.save()
        painter.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPoint(cx - d, cy + 4), QPoint(cx + d, cy + 4))
        painter.restore()

    def _draw_icon_settings(self, painter, rect, color):
        """圆角矩形 + 中间一个 S。"""
        painter.save()
        margin = 2
        painter.setPen(QPen(color, 1.2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            rect.x() + margin, rect.y() + margin,
            rect.width() - margin * 2, rect.height() - margin * 2,
            3, 3,
        )
        painter.setPen(color)
        painter.setFont(QFont("Segoe UI", 6, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, "S")
        painter.restore()

    def _draw_icon_lock(self, painter, rect, color, is_locked):
        cx = rect.center().x()
        cy = rect.center().y()
        body_w, body_h = 8, 6
        painter.save()
        painter.setPen(QPen(color, 1.2))
        painter.setBrush(color)
        painter.drawRoundedRect(cx - body_w // 2, cy - 1, body_w, body_h, 1, 1)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(cx - 4, cy - 7, 8, 8, 0 * 16, 180 * 16)
        if not is_locked:
            painter.setPen(QPen(color, 1.2))
            painter.drawLine(cx + 4, cy - 8, cx + 7, cy - 5)
        painter.restore()

    def _draw_icon_exit(self, painter, rect, color):
        cx = rect.center().x()
        cy = rect.center().y()
        d = 5
        painter.save()
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPoint(cx - d, cy - d), QPoint(cx + d, cy + d))
        painter.drawLine(QPoint(cx - d, cy + d), QPoint(cx + d, cy - d))
        painter.restore()

    # ================================================================
    #  绘制：圆环外发光
    # ================================================================
    def _draw_glow(self, painter, cx, cy, r, is_lv7, color_override=None):
        key = "circle_color_lv7" if is_lv7 else "circle_color_normal"
        base_opacity = self._effective_opacity(key)
        glow_color = QColor(self._get_color(key, color_override))
        painter.save()
        painter.setOpacity(base_opacity)
        painter.setPen(Qt.NoPen)
        for i in range(self.GLOW_LAYERS, 0, -1):
            alpha = int(18 * (self.GLOW_LAYERS - i + 1) / self.GLOW_LAYERS)
            glow_color.setAlpha(alpha)
            painter.setBrush(glow_color)
            painter.drawEllipse(QPoint(cx, cy), r + i * 4, r + i * 4)
        painter.restore()

    # ================================================================
    #  绘制：尖刺
    # ================================================================
    def _draw_indicator_outer_outline(self, painter, cx, cy, r, is_lv7, include_spikes=True, buff=None, color_override=None):
        """绘制指示器最外层勾边：先画底层粗白边，再由圆环/尖刺本体覆盖内侧。"""
        if not bool(self.settings.get("use_indicator_outline", DEFAULT_SETTINGS["use_indicator_outline"])):
            return
        outline_w = max(0, int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])))
        if outline_w <= 0:
            return
        opacity = self._effective_opacity("indicator_outline_color")
        if opacity <= 0:
            return

        outline_color = qcolor(self._get_color("indicator_outline_color", color_override))
        if buff:
            max_stacks = self._buff_max_stacks(buff)
            visible_spikes = min(max(int(buff.get("stacks", 0)), 0), max_stacks) if include_spikes else 0
        else:
            max_stacks = 7
            visible_spikes = 0

        painter.save()
        painter.setOpacity(opacity)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(outline_color, outline_w * 2 + 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)

        # 圆环外勾边：V2261 BUGFIX —— 原先这里直接用半径 r 画，与圆环本体同心。
        #   圆环本体（_draw_circle）以 r 为中心、最外层线宽 CIRCLE_WIDTH + 2（=5），
        #   即占据 [r - 2.5, r + 2.5]；本勾边同样以 r 为中心时，圆环绘制在后面，
        #   会把勾边从内侧一路盖到外侧 2.5px 处，结果：
        #     outline_w = 1（勾边半宽 1.5）→ 完全看不见
        #     outline_w = 2（勾边半宽 2.5）→ 正好被盖完，还是看不见  ← 用户反馈「要大于 2px 才出现」
        #     outline_w >= 3 → 只剩 (outline_w*2+1)/2 - 2.5 ≈ outline_w - 2.5  ← 「比尖刺/小球薄」
        #   而尖刺是实心三角形、小球是实心圆：它们只盖住勾边的内侧一半，
        #   剩外侧 (outline_w*2+1)/2 ≈ outline_w + 0.5，与圆环相差恒定的 2.5px。
        # 修法：把圆环勾边挪到「圆环外边缘」为中心（r + (CIRCLE_WIDTH+2)/2），
        #   这样露出的外侧宽度 = (outline_w*2+1)/2，与尖刺/小球完全一致。
        _circle_outer_r = r + (self.CIRCLE_WIDTH + 2) / 2.0
        painter.drawEllipse(QPoint(cx, cy), _circle_outer_r, _circle_outer_r)

        # 尖刺外勾边 + 装饰小球勾边：分别受 show_spikes / show_bead 独立开关控制（V2034）。
        for i in range(visible_spikes):
            angle = -90 + i * (360.0 / max_stacks)
            points = self._calc_spike_points(cx, cy, r, angle)
            if self._spike_drawn():
                path = QPainterPath()
                path.moveTo(points["tip"][0], points["tip"][1])
                path.lineTo(points["left"][0], points["left"][1])
                path.lineTo(points["root"][0], points["root"][1])
                path.lineTo(points["right"][0], points["right"][1])
                path.closeSubpath()
                painter.drawPath(path)
            bead_r = max(0, int(self.spike_bead_radius))
            if bead_r > 0 and self._bead_drawn():
                bead_x, bead_y = points["bead"]
                painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)

        painter.restore()

    def _spike_drawn(self):
        """尖刺三角本体是否绘制（含其外勾边 / 闪光），由「显示尖刺」独立开关控制。"""
        return bool(self.settings.get("show_spikes", True))

    def _bead_drawn(self):
        """尖刺顶端装饰小球是否绘制，由「显示装饰小球」独立开关控制；与尖刺三角互不耦合。"""
        return bool(self.settings.get("show_bead", True))

    def _draw_spikes(self, painter, cx, cy, r, is_lv7, buff=None, color_override=None):
        """绘制尖刺三角本体 + 装饰小球。两层独立控制，互不耦合：
        - show_spikes：尖刺三角本体（含其闪光）
        - show_bead  ：尖刺顶端的装饰小球

        V2311 尖刺立体感精简为 2 种风格（flat / highlight_line），
        小球支持 2 种（flat / radial_gradient）。
        所有风格共用"通用投影"和"通用暗描边"两组参数。详见设置对话框"3D 效果"页。
        """
        if not buff:
            return

        # 1) 计算可见层数与发光起点（与 max_stacks 截断）
        max_stacks = self._buff_max_stacks(buff)
        visible_spikes = min(max(int(buff.get("stacks", 0)), 0), max_stacks)
        key = "spike_color_lv7" if is_lv7 else "spike_color_normal"
        spike_color = qcolor(self._get_color(key, color_override))

        # 2) 闪光状态（仅控制尖刺三角的外扩动画；不影响小球绘制）
        _pl = self.pl_id
        if not _pl and self.char_type in CHAR_TYPE_TO_PL:
            _pl = CHAR_TYPE_TO_PL[self.char_type]
        _grp = buff.get("group")
        if _grp == "GENERAL":
            bkey = f"GENERAL_{buff.get('index')}"
        elif _pl:
            bkey = f"{_pl}_{buff.get('index')}"
        else:
            bkey = f"{self.char_type:#04x}_{buff.get('index')}"
        flash = self._spike_flash.get(bkey)
        flash_color = None
        anim_scale = 1.0
        flash_from = 0
        flash_to = visible_spikes
        if flash:
            dur = int(self.settings.get("flash_duration_ms", 400))
            now_ms = int(time.time() * 1000)
            elapsed = now_ms - flash["start"]
            if elapsed < dur:
                progress = elapsed / dur
                ready_scale = int(self.settings.get("flash_scale", 140)) / 100.0
                if progress < 0.3:
                    anim_scale = 1.0 + (ready_scale - 1.0) * (progress / 0.3)
                else:
                    anim_scale = ready_scale - (ready_scale - 1.0) * ((progress - 0.3) / 0.7)
                flash_color = qcolor(self.settings.get("flash_color", "#ffffff"))
                flash_from = flash["from"]
                flash_to = max(visible_spikes, int(flash.get("to", visible_spikes)))
            else:
                self._spike_flash.pop(bkey, None)

        draw_count = max(visible_spikes, flash_to)
        if draw_count <= 0:
            return

        draw_spike = self._spike_drawn()
        draw_bead = self._bead_drawn()
        if not draw_spike and not draw_bead:
            return

        painter.save()

        bead_r = max(0, int(self.spike_bead_radius))
        spike_opacity = self._effective_opacity(key)
        only_bead_opacity = 1.0

        # === V2263：读取 3D 立体感参数 ===
        style = self.settings.get("spike_3d_style", "flat")
        shadow_on = bool(self.settings.get("spike_3d_shadow_enabled", True))
        shx = int(self.settings.get("spike_3d_shadow_offset_x", 4))
        shy = int(self.settings.get("spike_3d_shadow_offset_y", 5))
        sh_alpha = int(self.settings.get("spike_3d_shadow_alpha", 120))
        outline_on = bool(self.settings.get("spike_3d_outline_enabled", True))
        outline_w = float(self.settings.get("spike_3d_outline_width", 1.0))
        outline_dark_f = int(self.settings.get("spike_3d_outline_dark", 150))

        # 暗描边色（所有风格共用）
        out_c = QColor(spike_color).darker(outline_dark_f)
        out_c.setAlpha(220)

        # 各风格预计算色
        if style == "two_tone":
            # V2312：two_tone 沿用 V2264 原版最简两分面（沿尖刺左→右方向，左亮右暗，中间 0.48-0.52 窄过渡硬边）。
            tt_light = QColor(spike_color).lighter(int(self.settings.get("spike_3d_twotone_light", 130)))
            tt_dark = QColor(spike_color).darker(int(self.settings.get("spike_3d_twotone_dark", 110)))

        # 4) 逐层绘制
        for i in range(draw_count):
            angle = -90 + i * (360.0 / max_stacks)
            points = self._calc_spike_points(cx, cy, r, angle)
            tip_x, tip_y = points["tip"]
            root_x, root_y = points["root"]
            lx, ly = points["left"]
            rx, ry = points["right"]
            bead_x, bead_y = points["bead"]

            # === A) 三角本体（含闪光） ===
            if draw_spike:
                path = QPainterPath()
                path.moveTo(tip_x, tip_y)
                path.lineTo(lx, ly)
                path.lineTo(root_x, root_y)
                path.lineTo(rx, ry)
                path.closeSubpath()

                if flash_color is not None and i >= flash_from:
                    # 闪光分支（与 V2262 一致）
                    painter.save()
                    painter.setOpacity(1.0)
                    if anim_scale != 1.0:
                        painter.translate(root_x, root_y)
                        painter.scale(anim_scale, anim_scale)
                        painter.translate(-root_x, -root_y)
                    f_outline = QColor(flash_color).darker(180)
                    f_outline.setAlpha(240)
                    outline_w_local = max(0, int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])))
                    f_outline_width = max(2.0, outline_w_local * 2 + 1)
                    painter.setBrush(QBrush(flash_color))
                    painter.setPen(QPen(f_outline, f_outline_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    painter.drawPath(path)
                    if bead_r > 0 and draw_bead:
                        painter.setBrush(flash_color)
                        painter.setPen(QPen(f_outline, max(1.2, f_outline_width * 0.6)))
                        painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)
                    painter.restore()
                else:
                    # === 1) 投影（通用） ===
                    if shadow_on and sh_alpha > 0 and (shx != 0 or shy != 0):
                        painter.save()
                        painter.setOpacity(spike_opacity * (sh_alpha / 255.0))
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QColor(0, 0, 0))
                        sp = QPainterPath()
                        sp.moveTo(tip_x + shx, tip_y + shy)
                        sp.lineTo(lx + shx, ly + shy)
                        sp.lineTo(root_x + shx, root_y + shy)
                        sp.lineTo(rx + shx, ry + shy)
                        sp.closeSubpath()
                        painter.drawPath(sp)
                        if bead_r > 0 and draw_bead:
                            painter.drawEllipse(QPoint(int(bead_x) + shx, int(bead_y) + shy), bead_r, bead_r)
                        painter.restore()

                    # === 2) 尖刺本体（按风格） ===
                    if style == "flat":
                        painter.setBrush(QBrush(spike_color))
                        if outline_on and outline_w > 0:
                            painter.setPen(QPen(out_c, outline_w))
                        else:
                            painter.setPen(Qt.NoPen)
                        painter.drawPath(path)
                    elif style == "two_tone":
                        # V2312：two_tone 沿用 V2264 原版最简两分面——沿尖刺左→右方向做 0.48-0.52 硬边渐变，左亮右暗。
                        grad = QLinearGradient(lx, ly, rx, ry)
                        grad.setColorAt(0.0, tt_light)
                        grad.setColorAt(0.48, tt_light)
                        grad.setColorAt(0.52, tt_dark)
                        grad.setColorAt(1.0, tt_dark)
                        painter.setBrush(QBrush(grad))
                        if outline_on and outline_w > 0:
                            painter.setPen(QPen(out_c, outline_w))
                        else:
                            painter.setPen(Qt.NoPen)
                        painter.drawPath(path)
                    else:
                        # 兜底：纯色（未知风格时与 flat 等价）
                        painter.setBrush(QBrush(spike_color))
                        if outline_on and outline_w > 0:
                            painter.setPen(QPen(out_c, outline_w))
                        else:
                            painter.setPen(Qt.NoPen)
                        painter.drawPath(path)

                    # === 3) 小球 ===
                    if bead_r > 0 and draw_bead:
                        self._draw_spike_bead(painter, spike_color, bead_x, bead_y, bead_r)

            # === B) 不画三角，仅画装饰小球 ===
            elif bead_r > 0 and draw_bead:
                painter.setOpacity(only_bead_opacity)
                # 投影（通用）
                if shadow_on and sh_alpha > 0 and (shx != 0 or shy != 0):
                    painter.save()
                    painter.setOpacity(only_bead_opacity * (sh_alpha / 255.0))
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(0, 0, 0))
                    painter.drawEllipse(QPoint(int(bead_x) + shx, int(bead_y) + shy), bead_r, bead_r)
                    painter.restore()
                self._draw_spike_bead(painter, spike_color, bead_x, bead_y, bead_r)

        painter.restore()

    def _draw_spike_bead(self, painter, spike_color, bead_x, bead_y, bead_r):
        """绘制尖刺根部装饰小球（从 _draw_spikes 抽出，供『仅隐藏尖刺』模式单独画）。
        V2263：支持 flat / radial_gradient 两种风格，参数全部从 settings 读取。"""
        style = self.settings.get("bead_3d_style", "radial_gradient")
        if style == "flat":
            # 纯色 + 暗描边（描边与尖刺共用 spike_3d_outline_* 设置）
            outline_on = bool(self.settings.get("spike_3d_outline_enabled", True))
            outline_w = float(self.settings.get("spike_3d_outline_width", 1.0))
            outline_dark_f = int(self.settings.get("spike_3d_outline_dark", 150))
            painter.setBrush(QBrush(spike_color))
            if outline_on and outline_w > 0:
                out_c = QColor(spike_color).darker(outline_dark_f)
                out_c.setAlpha(220)
                painter.setPen(QPen(out_c, outline_w))
            else:
                painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)
        else:
            # 径向渐变球化（左上高光 → 基色 → 边缘暗）
            light = QColor(spike_color).lighter(int(self.settings.get("bead_3d_light", 160)))
            dark = QColor(spike_color).darker(int(self.settings.get("bead_3d_dark", 125)))
            offset = float(self.settings.get("bead_3d_highlight_offset", 0.35))
            bead_outline = QColor(spike_color).darker(180)
            bead_grad = QRadialGradient(bead_x - bead_r * offset, bead_y - bead_r * offset, bead_r * 1.4)
            bead_grad.setColorAt(0.0, light)
            bead_grad.setColorAt(0.55, spike_color)
            bead_grad.setColorAt(1.0, dark)
            painter.setBrush(bead_grad)
            painter.setPen(QPen(bead_outline, 1.2))
            painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)

    def _calc_spike_points(self, cx, cy, r, angle_deg):
        rad = math.radians(angle_deg)
        dx, dy = math.cos(rad), math.sin(rad)
        px, py = -dy, dx
        nx, ny = cx + r * dx, cy + r * dy
        spike_shift = self.spike_len * self.spike_axis_pos
        root_x, root_y = nx + spike_shift * dx, ny + spike_shift * dy
        tip_x, tip_y = root_x + self.spike_len * dx, root_y + self.spike_len * dy
        waist_pos = max(0.05, min(0.95, self.spike_waist_pos))
        shoulder_x = root_x + self.spike_len * waist_pos * dx
        shoulder_y = root_y + self.spike_len * waist_pos * dy
        shoulder_half = max(1.0, self.spike_w / 2.0)
        bead_x = nx + self.spike_len * self.spike_bead_pos * dx
        bead_y = ny + self.spike_len * self.spike_bead_pos * dy
        return {
            "root": (root_x, root_y),
            "tip": (tip_x, tip_y),
            "left": (shoulder_x - shoulder_half * px, shoulder_y - shoulder_half * py),
            "right": (shoulder_x + shoulder_half * px, shoulder_y + shoulder_half * py),
            "bead": (bead_x, bead_y),
        }

    # ================================================================
    #  绘制：圆环
    # ================================================================
    def _draw_circle(self, painter, cx, cy, r, is_lv7, forced_opacity=None, color_override=None):
        key = "circle_color_lv7" if is_lv7 else "circle_color_normal"
        circle_color = self._get_color(key, color_override)
        base = qcolor(circle_color)
        painter.save()
        painter.setOpacity(self._effective_opacity(key) if forced_opacity is None else forced_opacity)

        # V2262：整环投影——向右下偏移的半透明暗环，营造"浮起"厚度（光源左上，与尖刺/小球一致）
        shx, shy = 2, 3
        shadow_pen = QPen(QColor(0, 0, 0, 80), self.CIRCLE_WIDTH + 2)
        shadow_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(shadow_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPoint(cx + shx, cy + shy), r, r)

        # 外侧暗边（加深，营造厚度感）
        dark = QColor(base).darker(175)
        pen_dark = QPen(dark, self.CIRCLE_WIDTH + 2)
        pen_dark.setCapStyle(Qt.RoundCap)
        painter.setPen(pen_dark)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPoint(cx, cy), r, r)

        # 主环：径向渐变（左上亮 → 中间基色 → 右下暗），模拟金属质感
        light = QColor(base).lighter(165)
        shadow = QColor(base).darker(140)
        grad = QRadialGradient(cx - r * 0.35, cy - r * 0.35, r * 1.8)
        grad.setColorAt(0.0, light)
        grad.setColorAt(0.45, base)
        grad.setColorAt(1.0, shadow)
        pen_main = QPen(QBrush(grad), self.CIRCLE_WIDTH)
        pen_main.setCapStyle(Qt.RoundCap)
        painter.setPen(pen_main)
        painter.drawEllipse(QPoint(cx, cy), r, r)

        # 内侧高光线（细而亮，增强立体反光）
        hi = QColor(base).lighter(185)
        hi.setAlpha(130)
        pen_hi = QPen(hi, 1)
        painter.setPen(pen_hi)
        inner_r = max(2, r - self.CIRCLE_WIDTH // 2 - 1)
        painter.drawEllipse(QPoint(cx, cy), inner_r, inner_r)

        painter.restore()

    # ================================================================
    #  绘制：倒计时进度（圆环 / 扇形，半径可调）
    # ================================================================
    def _draw_timer_progress(self, painter, cx, cy, r, is_lv7, buff=None,
                             color_override=None, color_index=0):
        if not buff:
            return
        if not self._buff_has_timer(buff):
            return
        arc_opacity = self._effective_opacity("arc_color")
        if arc_opacity <= 0:
            return
        timer_val = buff["timer"]
        timer_max_val = buff.get("timer_max")
        timer_max = timer_max_val if timer_max_val and timer_max_val > 0 else 30.0
        ratio = max(0.0, min(1.0, timer_val / timer_max))
        offset = int(self.settings.get("timer_arc_radius_offset", DEFAULT_SETTINGS["timer_arc_radius_offset"]))
        arc_r = max(8, r - offset)
        timer_cx = cx
        timer_cy = cy - int(self.settings.get("timer_center_offset_y", 0))
        rect = QRect(timer_cx - arc_r, timer_cy - arc_r, arc_r * 2, arc_r * 2)
        style = self.settings.get("timer_style", DEFAULT_SETTINGS["timer_style"])

        painter.save()
        painter.setOpacity(arc_opacity)

        # 扇形颜色：三级优先取 arc_color
        #   1. color_override 字典（_make_index_color_override 生成，按用户配的 color_mode/mono_span 旋转）
        #   2. color_index 直接算（绕过 override 字典的兜底，同样按用户配置算 deg）
        #   3. 设置默认值
        # 注：「内部差异化颜色」关闭时，倒计时表盘必须保持基础色——上面两条路径都要
        # 受 cfg["int"] 严格控制，不能在 int=False 时通过 color_index 兜底分支继续变
        # 色（这是同色系间距 mode 下"未勾但仍差异化"的真正根因）。
        arc_hex = None
        if color_override:
            arc_hex = color_override.get("arc_color")
        if not arc_hex and color_index > 0:
            cfg = self._multi_buff_cfg(min(len(self.active_buffs), 5))
            if cfg.get("int"):
                base = self.settings.get("arc_color", "#55ff00")
                if cfg.get("color_mode") == "monochrome":
                    deg = (color_index * cfg.get("mono_span", 15)) % 360
                else:
                    deg = self._MB_HUE_OFFSETS.get(color_index, (color_index * 72) % 360)
                arc_hex = rotate_hue(base, deg)
        if not arc_hex:
            arc_hex = self._get_color("arc_color", color_override)
        if style == "sector":
            fill = qcolor(arc_hex)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawPie(rect, 90 * 16, int(-ratio * 360 * 16))
        else:
            pen = QPen(qcolor(arc_hex), self.ARC_WIDTH)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(rect, 90 * 16, int(-ratio * 360 * 16))

        painter.restore()

    # ================================================================
    #  绘制：中心文字
    # ================================================================
    def _draw_centered_outlined_text(self, painter, text, rect, font, fill_color,
                                     outline_adjust=0, color_override=None,
                                     outline_width_key="dh_text_outline_width",
                                     outline_color_key="dh_text_outline_color",
                                     fill_color_key="text_color"):
        """绘制居中且可勾边的层数字。"""
        outline_w = max(0, int(self.settings.get(outline_width_key, DEFAULT_SETTINGS.get(outline_width_key, 3))) + int(outline_adjust))
        painter.save()
        painter.setFont(font)

        metrics = QFontMetrics(font)
        bounds = metrics.boundingRect(text)
        baseline_x = rect.center().x() - bounds.width() / 2 - bounds.left()
        baseline_y = rect.center().y() - bounds.height() / 2 - bounds.top()

        path = QPainterPath()
        path.addText(baseline_x, baseline_y, font, text)

        if outline_w > 0:
            painter.setOpacity(self._effective_opacity(outline_color_key))
            outline_hex = self._get_color(outline_color_key, color_override)
            painter.setPen(QPen(qcolor(outline_hex), outline_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        painter.setOpacity(self._effective_opacity(fill_color_key))
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor(fill_color))
        painter.drawPath(path)
        painter.restore()

    def _draw_timer_badge(self, painter, text, rect, color, color_override=None,
                          font_size_key="timer_font_size", text_color_key="timer_text_color"):
        """绘制圆内底部倒计时胶囊。
        font_size_key / text_color_key 允许「单层buff倒计时胶囊」复用本函数并使用独立样式。"""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # 背景与边框：额外buff（color_override）跟随槽位色相旋转色；首个buff保持原深色/紧急色
        if color_override:
            slot = QColor(self._get_color(text_color_key, color_override))
            h, s, _, _ = slot.getHsv()
            if h < 0:
                h = 0
            bg = QColor(); bg.setHsv(h, min(int(s), 140), 38, 120)  # 暗色调的槽位色
            edge = slot
        else:
            bg = QColor(3, 5, 10, 125)
            edge = qcolor(color)
        edge.setAlpha(78)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 7, 7)

        font_size = max(10, min(16, int(self.settings.get(font_size_key, 11)) + 1))
        painter.setOpacity(self._effective_opacity(text_color_key))
        badge_color = self._get_color(text_color_key, color_override) if color_override else color
        painter.setPen(qcolor(badge_color))
        painter.setFont(QFont("Segoe UI", font_size, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def _draw_center_text(self, painter, cx, cy, r, is_lv7, buff=None, is_single_layer=False, color_override=None):
        if not buff:
            return
        painter.save()
        stacks = int(buff.get("stacks", 0))
        is_float_gauge = buff.get("gauge_mode") == "float"
        has_timer = self._buff_has_timer(buff)

        if is_single_layer:
            # 单层资源槽（如芙劳「转世的恩宠」）：gauge_mode=float 时中心显示浮点值；
            # 其余单层 buff 只有倒计时胶囊。无 timer 且无 gauge 则不画中心文字。
            if is_float_gauge:
                num_offset_x = int(self.settings.get("center_text_offset_x", 0))
                num_offset_y = int(self.settings.get("center_text_offset_y", 0))
                gv = buff.get("gauge_value")
                if isinstance(gv, (int, float)):
                    if buff.get("max_stacks", 1) == 1:
                        text = f"{gv:.2f}"
                    else:
                        text = f"{gv:.1f}" if gv != int(gv) else str(int(gv))
                else:
                    text = "--"
                font = QFont("Segoe UI", max(14, int(self.settings.get("dh_font_size", DEFAULT_SETTINGS["dh_font_size"])) - 4), QFont.Bold)
                text_color = self._get_color("text_color", color_override)
                text_rect = QRect(cx - r + num_offset_x, cy - r - num_offset_y, r * 2, r * 2)
                self._draw_centered_outlined_text(painter, text, text_rect, font, text_color,
                                                  color_override=color_override)
            elif has_timer:
                timer_font_setting = int(self.settings.get("single_timer_font_size", DEFAULT_SETTINGS["single_timer_font_size"]))
                if timer_font_setting > 0:
                    timer_val = buff["timer"]
                    timer_y_offset = int(self.settings.get("single_timer_y_offset", DEFAULT_SETTINGS["single_timer_y_offset"]))
                    badge_pad = int(self.settings.get("single_timer_badge_width", DEFAULT_SETTINGS["single_timer_badge_width"]))
                    timer_text = f"{self._fmt_dur(timer_val)}s"
                    timer_color = ("#00bbbb" if color_override else "#ff4444") if timer_val < 3 else self._get_color("single_timer_text_color", color_override)
                    timer_font_size = max(1, min(16, timer_font_setting + 1))
                    timer_font = QFont("Segoe UI", timer_font_size, QFont.Bold)
                    timer_metrics = QFontMetrics(timer_font)
                    badge_w = min(r * 2 - 12, max(36, timer_metrics.horizontalAdvance(timer_text) + badge_pad))
                    badge_h = 16
                    timer_rect = QRect(int(cx - badge_w / 2), int(cy - badge_h / 2 - timer_y_offset), int(badge_w), badge_h)
                    self._draw_timer_badge(painter, timer_text, timer_rect, timer_color,
                                           color_override=color_override,
                                           font_size_key="single_timer_font_size",
                                           text_color_key="single_timer_text_color")
            painter.restore()
            return

        # 浮点槽：中心显示原始浮点值（如 0.52 / 3.5）
        if is_float_gauge:
            num_offset_x = int(self.settings.get("center_text_offset_x", 0))
            num_offset_y = int(self.settings.get("center_text_offset_y", 0))
            gv = buff.get("gauge_value")
            if isinstance(gv, (int, float)):
                # 0~1 显示两位小数；0~4 显示一位或整数
                if buff.get("max_stacks", 1) == 1:
                    text = f"{gv:.2f}"
                else:
                    text = f"{gv:.1f}" if gv != int(gv) else str(int(gv))
            else:
                text = "--"
            font = QFont("Segoe UI", max(14, int(self.settings.get("dh_font_size", DEFAULT_SETTINGS["dh_font_size"])) - 4), QFont.Bold)
            text_color = self._get_color("text_color", color_override)
            text_rect = QRect(cx - r + num_offset_x, cy - r - num_offset_y, r * 2, r * 2)
            self._draw_centered_outlined_text(painter, text, text_rect, font, text_color,
                                              color_override=color_override)
        elif has_timer:
            # 有计时版：使用独立的参数
            num_offset_x = int(self.settings.get("center_text_offset_x_timer", 0))
            num_offset_y = int(self.settings.get("center_text_offset_y_timer", 0))
            dh_text = "" if stacks == 0 else str(stacks)
            dh_font_size = max(22, int(int(self.settings.get("dh_font_size_timer", DEFAULT_SETTINGS["dh_font_size_timer"])) * 0.88))
            dh_font = QFont("Segoe UI", dh_font_size, QFont.Bold)
            text_color = self._get_color("text_color_timer", color_override)
            dh_rect = QRect(cx - r + num_offset_x, cy - r - 3 - num_offset_y, r * 2, int(r * 1.18))
            self._draw_centered_outlined_text(painter, dh_text, dh_rect, dh_font, text_color,
                                              outline_adjust=-1, color_override=color_override,
                                              outline_width_key="dh_text_outline_width_timer",
                                              outline_color_key="dh_text_outline_color_timer",
                                              fill_color_key="text_color_timer")
        else:
            # 无计时版：使用无计时参数
            num_offset_x = int(self.settings.get("center_text_offset_x", 0))
            num_offset_y = int(self.settings.get("center_text_offset_y", 0))
            text = "" if stacks == 0 else str(stacks)
            font = QFont("Segoe UI", int(self.settings.get("dh_font_size", DEFAULT_SETTINGS["dh_font_size"])), QFont.Bold)
            text_color = self._get_color("text_color", color_override)
            text_rect = QRect(cx - r + num_offset_x, cy - r - num_offset_y, r * 2, r * 2)
            self._draw_centered_outlined_text(painter, text, text_rect, font, text_color,
                                              color_override=color_override)

        if has_timer:
            # 计时胶囊不受层数数字偏移影响，位置基于圆心
            timer_font_setting = int(self.settings.get("timer_font_size", 11))
            if timer_font_setting > 0:
                timer_val = buff["timer"]
                timer_y_offset = int(self.settings.get("lv7_timer_y_offset", 0))
                badge_pad = int(self.settings.get("lv7_timer_badge_width", DEFAULT_SETTINGS["lv7_timer_badge_width"]))
                timer_text = f"{self._fmt_dur(timer_val)}s"
                timer_color = ("#00bbbb" if color_override else "#ff4444") if timer_val < 3 else self._get_color("timer_text_color", color_override)
                timer_font_size = max(1, min(16, timer_font_setting + 1))
                timer_font = QFont("Segoe UI", timer_font_size, QFont.Bold)
                timer_metrics = QFontMetrics(timer_font)
                badge_w = min(r * 2 - 12, max(36, timer_metrics.horizontalAdvance(timer_text) + badge_pad))
                badge_h = 16
                timer_rect = QRect(int(cx - badge_w / 2), int(cy + r * 0.36 - timer_y_offset), int(badge_w), badge_h)
                self._draw_timer_badge(painter, timer_text, timer_rect, timer_color, color_override=color_override)
        painter.restore()

    # ================================================================
    #  绘制：翻滚模块（独立窗口，横/竖可选；图标闪光勾边发光）
    # ================================================================
    def _draw_dodge_icon_at(self, painter, x, y, icon, flash_progress, icon_index=None, force_warning=False):
        """在 (x,y) 绘制单个翻滚图标（警告牌 / png / 兜底方块）。

        闪光逻辑（V274 同款 + V2028 警告牌亮度闪烁）：
          - 普通翻滚图标：闪光时画单层放大实心白色图标，完全替代原图标。
          - 警告牌（第 6/7 次）：闪光时=整体放大脉冲(复用 flash_scale) + 在警告牌形状之上叠加
            flash_color 的透明度脉冲闪烁（V2028 新增），外形始终是警告牌、绝不用白色方块遮挡。
        icon_index：该图标在序列中的序号（0 起）。
        force_warning：第 6/7 次翻滚时为 True——序列内所有图标都变警告牌。
        """
        warning_mode = force_warning or (icon_index is not None and icon_index >= 5)
        flash_active = flash_progress > 0 and bool(self.settings.get("flash_apply_dodge", False))

        def _flash_scale():
            """闪光缩放曲线：1.0 → flash_scale → 1.0（脉冲）。"""
            ready_scale = int(self.settings.get("flash_scale", 140)) / 100.0
            if flash_progress < 0.3:
                return 1.0 + (ready_scale - 1.0) * (flash_progress / 0.3)
            else:
                return ready_scale - (ready_scale - 1.0) * ((flash_progress - 0.3) / 0.7)

        if warning_mode:
            # V2313：新增「图片模式」——第 6/7 次改用 PNG（内置默认警告图 / 玩家自选图）。
            # 闪光直接复用第 1~5 次完全相同的路径（_get_dodge_solid_img：alpha>128 填闪光色 +
            # _flash_scale() 放大脉冲），所以换任何 PNG 闪光都自动跟上，不需要额外适配。
            _wimg = getattr(self, "dodge_warning_icon", None)
            if self._use_warning_image() and _wimg is not None and not _wimg.isNull():
                if flash_active:
                    _solid = self._get_dodge_solid_img(
                        self.settings.get("flash_color", "#ffffff"), source=_wimg, cache_tag="warn")
                    if _solid is not None:
                        _s = _flash_scale()
                        _cx, _cy = x + icon / 2.0, y + icon / 2.0
                        painter.save()
                        painter.translate(_cx, _cy)
                        painter.scale(_s, _s)
                        painter.translate(-_cx, -_cy)
                        painter.setOpacity(1.0)
                        self._draw_pixmap_centered(painter, _solid, x, y, icon)
                        painter.restore()
                        return
                # 非闪光：原样画警告图（保留 painter 当前不透明度 = 翻滚图标不透明度设置）
                self._draw_pixmap_centered(painter, _wimg, x, y, icon)
                return
            # 警告牌模式：从不画白色方块遮挡；闪光时=放大脉冲(复用 flash_scale) + 警告牌形状亮度闪烁(V2028)。
            # （图片模式但选的图无效/缺失时也会落到这里，自动回退成三角形，不会留空白槽位。）
            if flash_active:
                scale = _flash_scale()
                cx, cy = x + icon / 2.0, y + icon / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(scale, scale)
                painter.translate(-cx, -cy)
                self._draw_warning_roll_icon(painter, x, y, icon, flash_progress=flash_progress)
                painter.restore()
            else:
                self._draw_warning_roll_icon(painter, x, y, icon, flash_progress=0.0)
            return

        if flash_active:
            # 普通翻滚图标：闪光期间画单层放大实心白色图标完全覆盖原图标，最实心、不露馅
            if not self.shrimp.isNull():
                solid = self._get_dodge_solid_img(self.settings.get("flash_color", "#ffffff"))
                if solid is not None:
                    scale = _flash_scale()
                    cx, cy = x + icon / 2.0, y + icon / 2.0
                    painter.save()
                    painter.translate(cx, cy)
                    painter.scale(scale, scale)
                    painter.translate(-cx, -cy)
                    painter.setOpacity(1.0)
                    painter.drawPixmap(x, y, solid)
                    painter.restore()
                    return
            else:
                # 兜底：无 shrimp 时画白色放大方块
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(self.settings.get("flash_color", "#ffffff")))
                sz = icon * int(self.settings.get("flash_scale", 140)) / 100.0
                cx, cy = x + icon / 2.0, y + icon / 2.0
                painter.drawRoundedRect(int(cx - sz / 2), int(cy - sz / 2), int(sz), int(sz), 6, 6)
                return

        if not self.shrimp.isNull():
            painter.drawPixmap(x, y, self.shrimp)
        else:
            # V2063：兜底改为程序绘制「白对号 ✓ + 深透明圆角底」——任何 PNG 路径加载失败/缺失场景下
            # 都不会退化为无意义的橙色色块，UI 风格保持统一：
            #   · 半透明深底（不透明 160/255）+ 圆角矩形作为徽章基底；
            #   · 白色对号（两段折线），RoundCap + RoundJoin 让笔触端点和拐角为圆滑造型。
            cx = x + icon / 2.0
            cy = y + icon / 2.0
            sz = max(8, int(icon * 0.78))
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.drawRoundedRect(int(cx - sz / 2.0), int(cy - sz / 2.0), int(sz), int(sz), 4, 4)
            pen = QPen(QColor(255, 255, 255), max(2, int(sz * 0.18)), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - sz * 0.30, cy - sz * 0.02)
            path.lineTo(cx - sz * 0.08, cy + sz * 0.22)
            path.lineTo(cx + sz * 0.32, cy - sz * 0.24)
            painter.drawPath(path)
            painter.restore()

    # ================================================================
    #  全 Buff 显示模块（第四模块）渲染
    # ================================================================
    def render_allbuff(self, painter):
        """网格化列出当前主控角色可读到的全部 buff（已 gate 过滤），可叠加 5 个可选过滤开关。"""
        # V2064：模块独立显隐开关：关闭时整窗隐藏由 _apply_live_settings / 启动逻辑处理，
        # 这里仍兜底返回，确保任何残留绘制都不出现。
        if not bool(self.settings.get("show_allbuff_module", True)):
            return

        # V2063：与 SkillWindow 一致——每次绘制前刷新「非战斗」内容乘数，
        # 保证 allbuff_win 独立重绘时（core_win 未重绘）也使用最新的隐藏状态。
        self._out_of_combat_mult = getattr(self, "_ooc_content_mult", 1.0)

        # V2064：画布级不透明背景填充——防止背景窗口（如设置对话框）的内容透出来
        # 在 settings 标签里玩家可调，默认 0 = 不画（保留 V2063 之前的纯透明外观）。
        # 玩家遇到「buff 文字显示不全/有路径片段透过」时把这里调到 30~70 即可遮罩。
        canvas_bg_op = max(0, min(100, int(self.settings.get("allbuff_canvas_bg_opacity", 0)))) / 100.0
        if canvas_bg_op > 0.0:
            cw_canvas = getattr(self, "allbuff_canvas_w", 0)
            ch_canvas = getattr(self, "allbuff_canvas_h", 0)
            if cw_canvas > 0 and ch_canvas > 0:
                painter.save()
                bg = QColor(0, 0, 0)
                bg.setAlphaF(canvas_bg_op)
                painter.setPen(Qt.NoPen)
                painter.setBrush(bg)
                painter.drawRoundedRect(0, 0, cw_canvas, ch_canvas, 4, 4)
                painter.restore()

        # V2101：模块背景/线框——仅由「锁定」决定可见性，永不绑定战斗；
        # 与核心/能力/翻滚模块的 _draw_module_backdrop 完全一致（未锁定时底框始终显示）。
        # 此处先画底框，再让下方的「非战斗隐藏」只隐藏内容、不隐藏底框（与核心模块一致）。
        self._draw_module_backdrop(painter, self.allbuff_canvas_w, self.allbuff_canvas_h, draw_border=True)

        # V2084：非战斗隐藏——「非战斗隐藏」开启且非战斗时，仅隐藏内容区（底框保留），
        # 与 render_core / render_roll / render_skill_cd 一致；之前误把整窗（含底框）一起隐藏。
        if self._out_of_combat_mult <= 0.0:
            return

        lang = self.settings.get("language", "zh")
        status = getattr(self, "status", "init")
        has_char = bool(self.char_type or self.charid_hash or self.pl_id)
        # V2115：未检测到角色 / 初始化时不再画任何占位文字——只保留 _draw_module_backdrop 背景，
        # _apply_allbuff_fixed_size 仍保留以维持固定区域/可拖动/可缩放（与 _draw_module_backdrop 配合）。
        if status in ("no_game", "init") or not has_char:
            self._apply_allbuff_fixed_size()  # V2103：无角色也预留 3 行固定区域
            return


        buffs = getattr(self, "all_buffs_filtered", []) or []

        if not buffs:
            # V2115：同 V2115 顶部说明——无活动 Buff 时也不画占位文字。
            self._apply_allbuff_fixed_size()  # V2103：无活动 Buff 也预留 3 行固定区域
            return

        # ── 读取布局 / 样式参数 ──
        # V2062：取消「显示行数」硬上限 → 改为 ceil(n/per_row) 自动延伸
        per_row = max(1, int(self.settings.get("allbuff_per_row", 10)))
        row_sp = int(self.settings.get("allbuff_row_spacing", 4))
        card_sp = int(self.settings.get("allbuff_card_spacing", 4))
        bw_setting = max(1, int(self.settings.get("allbuff_backing_width", 80)))
        bh_setting = max(1, int(self.settings.get("allbuff_backing_height", 64)))

        name_fs = max(1, int(self.settings.get("allbuff_name_font_size", 11)))
        stacks_fs = max(1, int(self.settings.get("allbuff_stacks_font_size", 10)))
        time_fs = max(1, int(self.settings.get("allbuff_time_font_size", 10)))
        bar_w = max(1, int(self.settings.get("allbuff_bar_width", 60)))
        bar_h = max(1, int(self.settings.get("allbuff_bar_height", 5)))
        # V2060：进度条外框粗细（0=不要外框）+ 卡片内统一垂直间距
        bar_frame_t = max(0, min(10, int(self.settings.get("allbuff_bar_frame_thickness", 2))))
        # V2075：允许负值——负间距让卡片内各行更紧凑（可重叠）
        elem_sp = int(self.settings.get("allbuff_element_spacing", 4))
        # V2074：行高加成——在三行文字实测 QFontMetrics.height()+2 基础上额外加的高度（默认 0）
        # V2075：允许负值——负加成收紧行高（QRect 高度在 _draw_allbuff_card 内 clamp 到 >=1）
        row_h_extra = int(self.settings.get("allbuff_row_height_extra", 0))

        # V2062：自适应 floor——按当前字体/元素间距/进度条/外框厚度算出「最小可视高度/宽度」
        # 取 max(自适应最小值, 用户设置) ⇒ 永远不裁切 buff 内容，玩家仍可在自适应基础上继续加 padding
        # V2073：用 QFontMetrics 实际测量行高替代 `font_size + 2` 硬编码——
        # 11pt Segoe UI Bold 的 fm.height()≈15-17px（视系统字体），font_size+2=13 不够，
        # QRect 高度偏小→中文字符 ascender 顶部被卡片圆角裁切，表现为「減」「消」「霸」等
        # 汉字上半部被遮挡、进度条上沿被切。auto_bh 与三行文字绘制均用 fm.height()+2 同步。
        from PySide6.QtGui import QFont as _QF, QFontMetrics as _QFM
        _afm_name   = _QFM(_QF("Segoe UI", name_fs,   _QF.Bold))
        _afm_stacks = _QFM(_QF("Segoe UI", stacks_fs, _QF.Bold))
        _afm_time   = _QFM(_QF("Segoe UI", time_fs,   _QF.Bold))
        _name_h   = _afm_name.height()   + 2 + row_h_extra
        _stacks_h = _afm_stacks.height() + 2 + row_h_extra
        _time_h   = _afm_time.height()   + 2 + row_h_extra
        pad = 2
        # V2217：融合为 3 行（名称 / 层数 / 时间+进度条共用一行），行高取 max(时间, 进度条外框)；
        # 与 _apply_allbuff_fixed_size / _draw_allbuff_card 的 _content_h 完全一致，避免卡片比窗口槽高导致多排被切。
        _fused_h = max(_time_h, (bar_h + 2 * bar_frame_t))
        auto_bh = (2 * pad
                   + _name_h       # 名称行高（QFontMetrics 实测）
                   + elem_sp
                   + _stacks_h     # 层数行高（QFontMetrics 实测）
                   + elem_sp
                   + _fused_h)     # 时间+进度条融合行（取二者较大值）
        # V2075：负 elem_sp 可能让 auto_bh 变很小甚至为负 → clamp 到 >=1，
        # 但 bh 最终还会取 max(auto_bh, bh_setting)，玩家设的衬底高度仍优先。
        auto_bh = max(1, auto_bh)
        auto_bw = bar_w + 2 * bar_frame_t + 8     # 4 px 左右 padding，避免贴边
        # V2077 防御：force_bh_min = 内容总高 + 上下 pad，确保 _draw_allbuff_card
        # 算出 _content_top 居中起点后，by + outer_h 永远在衬底内（不被切）。
        # auto_bh 算式已含 2*pad + _content_h，所以 auto_bh 已经是这个值。
        # 但 _draw_allbuff_card 内会用 cur_name_fs（阶梯缩字后）算 name_h，
        # 与这里的 _name_h 可能略不同（实际更小，不会更糟），所以理论上安全。
        bh = max(auto_bh, bh_setting)
        bw = max(auto_bw, bw_setting)

        name_col = QColor(self._get_color("allbuff_name_color"))
        stacks_col = QColor(self._get_color("allbuff_stacks_color"))
        time_col = QColor(self._get_color("allbuff_time_color"))
        bar_col = QColor(self._get_color("allbuff_bar_color"))
        bar_op = max(0, min(100, int(self.settings.get("allbuff_bar_color_opacity", 100)))) / 100.0
        bar_col.setAlpha(int(255 * bar_op))
        backing_col = QColor(self._get_color("allbuff_backing_color"))
        backing_op = max(0, min(100, int(self.settings.get("allbuff_backing_color_opacity", 50)))) / 100.0
        backing_col.setAlpha(int(255 * backing_op))

        # ── V2060：倒计时尾声警告（buff） ──
        warn_en = bool(self.settings.get("allbuff_warn_enabled", False))
        warn_thr = max(1, min(99, int(self.settings.get("allbuff_warn_threshold_pct", 20)))) / 100.0
        warn_col = QColor(self._get_color("allbuff_warn_color"))
        warn_op = max(0, min(100, int(self.settings.get("allbuff_warn_color_opacity", 100)))) / 100.0
        warn_col.setAlpha(int(255 * warn_op))

        # ── V2060：Debuff 配色（编号 ≥ 1000） ──
        debuff_name_col  = QColor(self._get_color("allbuff_debuff_name_color"))
        debuff_stacks_col= QColor(self._get_color("allbuff_debuff_stacks_color"))
        debuff_time_col  = QColor(self._get_color("allbuff_debuff_time_color"))
        debuff_bar_col   = QColor(self._get_color("allbuff_debuff_bar_color"))
        debuff_bar_op = max(0, min(100, int(self.settings.get("allbuff_debuff_bar_color_opacity", 100)))) / 100.0
        debuff_bar_col.setAlpha(int(255 * debuff_bar_op))
        # Debuff 警告
        debuff_warn_en = bool(self.settings.get("allbuff_debuff_warn_enabled", True))
        debuff_warn_col = QColor(self._get_color("allbuff_debuff_warn_color"))
        debuff_warn_op = max(0, min(100, int(self.settings.get("allbuff_debuff_warn_color_opacity", 100)))) / 100.0
        debuff_warn_col.setAlpha(int(255 * debuff_warn_op))

        # ── 过滤开关（默认全关 = 显示全部）──
        ex_core = bool(self.settings.get("allbuff_exclude_core", False))
        ex_inf = bool(self.settings.get("allbuff_exclude_infinite", False))
        ex_excl = bool(self.settings.get("allbuff_exclude_exclusive", False))
        ex_mast = bool(self.settings.get("allbuff_exclude_mastery", False))
        ex_single = bool(self.settings.get("allbuff_exclude_single", False))

        core_sids = set()
        if ex_core:
            prof = BUFF_PROFILES.get(self.pl_id, {})
            for b in prof.get("buffs", []):
                sid = b.get("sid")
                if isinstance(sid, int) and sid >= 0:
                    core_sids.add(sid)

        # ── V2066：门限（monitor 风格数值废料过滤）——在「过滤」开关之前先过滤 ──
        # V2216：删 allbuff_gate_filter_status_id_zero 键 + 复选框；V2222 起 sid==0 永远显示（用户要求），
        # 下方不再 `if sid_i == 0: continue`。status_id/sub_id 上限恢复为可配置门限（见下方 g_e_sidmax/g_sidmax 等）。
        # V2217：再删 4 个门限的 settings + 控件，全部**固化为 render 默认值常量**：
        #   · status_id 上限 = 0xFFFF、sub_id 上限 = 0xFFFF（玩家实际 sid/sub 远小于，影响为零）
        #   · 层数矛盾检查 = 始终执行 `if max_stacks>0 and cur_stacks > max_stacks: continue`
        #   · 时长上限 = 10000.0 秒（保留 9999 永续豁免，对应 V2216）
        g_e_stkmax = bool(self.settings.get("allbuff_gate_enabled_stacks_max", True))
        g_stkmax = int(self.settings.get("allbuff_gate_stacks_max", 100))
        g_e_mstkmax = bool(self.settings.get("allbuff_gate_enabled_max_stacks_max", False))
        g_mstkmax = int(self.settings.get("allbuff_gate_max_stacks_max", 100))
        # V2222：恢复 status_id / sub_id 上限门限（V2217 曾硬编码 0xFFFF 常闭，现改为可配置阈值）
        g_e_sidmax = bool(self.settings.get("allbuff_gate_enabled_status_id_max", True))
        g_sidmax = int(self.settings.get("allbuff_gate_status_id_max", 0xFFFF))
        g_e_submax = bool(self.settings.get("allbuff_gate_enabled_sub_id_max", True))
        g_submax = int(self.settings.get("allbuff_gate_sub_id_max", 0xFFFF))
        g_e_minrem = bool(self.settings.get("allbuff_gate_enabled_min_remaining_time", True))
        g_minrem = float(self.settings.get("allbuff_gate_min_remaining_time", 0.05))
        g_e_mininit = bool(self.settings.get("allbuff_gate_enabled_min_initial_time", True))
        g_mininit = float(self.settings.get("allbuff_gate_min_initial_time", 0.05))
        g_e_minappear = bool(self.settings.get("allbuff_gate_enabled_min_appearance_time", True))  # V2084
        g_minappear = float(self.settings.get("allbuff_gate_min_appearance_time", 0.1))         # V2084
        # V2243: 4 条「固化」门限改为可勾选 gating——玩家可单独关闭任一项。
        g_e_nancheck = bool(self.settings.get("allbuff_gate_check_nan_inf", True))
        g_e_id01inf = bool(self.settings.get("allbuff_gate_filter_status_id_zero_one_infinite_enabled", True))
        g_e_mintime = bool(self.settings.get("allbuff_gate_check_min_time_enabled", True))
        g_mintime = float(self.settings.get("allbuff_gate_min_time", 0.0))
        g_e_durmax = bool(self.settings.get("allbuff_gate_enabled_duration_max", True))
        # V2260 ⑤：剩余时间 > 持续时间（remaining > initial）视为脏值丢弃（可勾选，默认开启）。
        g_e_remgtinit = bool(self.settings.get("allbuff_gate_rem_gt_init_drop", True))
        # V2116：全 Buff「黑名单」——名单内 sid 永不显示（无视任何其它开关，最优先过滤）
        # V2110/V2116：「多次出现名单」——名单内 sid 不受去重限制，可显示多个实例；其余按 sid 只保留 1 个
        def _collect_sids(setting_key, exclusive=False):
            out = set()
            for _e in (self.settings.get(setting_key) or []):
                try:
                    _s = int(_e.get("sid"))
                    if 0 <= _s <= 0xFFFF:
                        # V2111/V2116：专属 buff 永远不可多次出现 / 不必入黑名单（render 端硬保险剔除）
                        _wa = BUFF_ATTRS.get(f"0x{_s:X}({_s})")
                        if _wa and _wa.get("是否专属"):
                            continue
                        out.add(_s)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
            return out
        _multi_buff_blacklist = _collect_sids("multi_buff_blacklist")
        _multi_buff_whitelist = _collect_sids("multi_buff_whitelist")

        # ── V2095：构建 sid→pct_cap 映射（百分比型 buff 如龙人化，游戏存的是 0~100 读数）──
        # 从 BUFF_PROFILES（i18n.json 的角色配表）合并，一次算好缓存到 self，避免每帧重建。
        _pct = getattr(self, "_pct_cap_by_sid", None)
        if _pct is None:
            _pct = {}
            try:
                for _pl, _prof in (BUFF_PROFILES or {}).items():
                    for _b in (_prof.get("buffs") or []):
                        _sidv = _b.get("sid")
                        _pc = _b.get("pct_cap")
                        if isinstance(_sidv, int) and _sidv >= 0 and _pc:
                            _pct[_sidv] = float(_pc)
            except Exception:
                _pct = {}
            self._pct_cap_by_sid = _pct
        # ── 收集 + 过滤 + 排序（按 sid 稳定排序）──
        items = []
        # V2109：永续 / 角色专属 buff 只保留 1 个实例（不去重普通有限 buff）
        _shown_unique_sids = set()
        # V2210：内容指纹去重集合（同 sid 且五项数据全同 → 视为同一条 status 的重复读取）
        _seen_content_fp = set()
        # V2084：维护「首次观测到的时间」dict，判定瞬时 buff（闪现即逝）是否够老
        _now = time.time()
        if not hasattr(self, "_buff_first_seen"):
            self._buff_first_seen = {}
        _seen = self._buff_first_seen
        # V2096：与 _seen 配套，记录「已经出现过（哪怕只出现一帧）」的 sid，
        # 用来消除「最小出现持续时间」门限造成的闪烁——见下方 g_e_minappear 处的说明。
        if not hasattr(self, "_buff_ever_shown"):
            self._buff_ever_shown = set()
        _ever_shown = self._buff_ever_shown
        # V2224：每帧按 mtime 热加载外部补充文件（玩家保存后 <1 秒生效）
        _reload_user_attrs()
        for sid, info in buffs:
            attr = _attr_for_sid(sid)
            # V2224：attr 已按「外部补充 > 内置 > 未知兜底(hex ID)」三优先级取好；
            # _unknown 标记（仅未知兜底时存在）供下方 items.append 处决定是否记进未知清单。
            # V2116：黑名单 sid 永不显示（在所有门限/开关之前生效，玩家最强制最强的过滤）
            if sid in _multi_buff_blacklist:
                continue
            # V2306 BUGFIX：调试数据模式下，合成假 buff 的 sid 是 0xD001/D101（53249/53505），
            # 远超玩家为正常游戏设的 status_id_max（如 3000），会被数值门限整批丢弃，
            # 表现为「全 Buff / Boss 模块在调试模式下空白、但核心模块正常」（核心用 active_buffs
            # 字典、不查 sid 门限）。调试只为离线核对排版/字号，假数据本就不该被正常游戏的废料门限
            # 过滤，故调试态直接跳过所有门限与过滤开关，保证注入的假 buff 一定全部显示。
            if _DEBUG_ATTR.get("active"):
                items.append((sid, info, attr))
                continue
            # V2084：首次观测到的 buff 记录时间，已观测的复用。消失的 sid 在循环外清理。
            # V2087 BUGFIX①：原版 `_seen[sid] = _now` 后立刻判 `_now - _seen[sid] < 阈值`
            #              → 首次观测必然 `_now - _now = 0 < 阈值` → 被丢（全 Buff 空白）。
            # V2088 BUGFIX②：V2087 的修法仍有致命漏洞——`_seen[sid] = _now` 是**无条件刷新**，
            #              每帧都把"首次时间"改写成当前时间 → 已知 buff 的差值永远≈0
            #              → 帧1 显示 / 帧2 丢 / 帧3 显示... → **疯狂闪烁**。
            #              正确写法：只在首次记录，之后**不再刷新**。
            _was_new = sid not in _seen
            if _was_new:
                _seen[sid] = _now
            # ── 门限：数值废料判定（不依赖 BUFF_ATTRS，纯数值阈值）──
            sid_i = int(sid)
            sub_id = int(info.get("sub_id", 0) or 0)
            cur_stacks = int(info.get("stacks", 0) or 0)
            max_stacks = int(info.get("max_stacks", 0) or 0)
            initial = float(info.get("initial", 0.0) or 0.0)
            remaining = float(info.get("remaining", 0.0) or 0.0)
            infinite = bool(info.get("infinite"))
            # V2222：sid==0 不再硬丢（用户要求 sid==0 永远显示，攻击UP 等 sid==0 条目现在也会显示）。
            # status_id / sub_id 上限恢复为「门限(阈值)」机制：由设置里的
            # *_gate_enabled_status_id_max / *_gate_status_id_max（及 sub 对应项）控制；
            # 默认阈值 0xFFFF，与旧硬编码常闭等价，玩家可在「门限」页调节。
            if g_e_sidmax and sid_i > g_sidmax: continue
            if g_e_submax and sub_id > g_submax: continue
            if g_e_stkmax and not (0 <= cur_stacks <= g_stkmax): continue
            if g_e_mstkmax and not (0 <= max_stacks <= g_mstkmax): continue
            # 层数矛盾检查：max_stacks=0 视为「无上限/未定义」不触发丢弃
            if max_stacks > 0 and cur_stacks > max_stacks: continue
            _huge_t = (remaining >= 9999) or (initial >= 9999)
            # V2243 ④ 时长上限改为「settings 双层 gating」——en 键启用+val 键设值。
            # 默认 10000.0 秒,玩家可在「门限」面板调整；取消勾选 = 不剔除任何时长上限异常值。
            _g_dur_max = float(self.settings.get("allbuff_gate_duration_max_with_infinite_exemption", 10000.0))
            if g_e_durmax and not _huge_t and (initial > _g_dur_max or remaining > _g_dur_max): continue
            # V2243 ② ID=0/ID=1 不可能是永续（V2236 仅过滤 ID=0,V2243 扩展到 ID=1 防御UP）：
            # 攻击UP/防御UP 等 sid=0/1 槽位的垃圾条目会把 infinite 标志位置 1 → 误显成永续 buff；
            # 游戏里 sid=0/1 不存在真正的永续 buff。玩家关闭勾选后可能显示 0/1 槽位的伪永续条目。
            if g_e_id01inf and sid_i in (0, 1) and infinite: continue
            # V2243 ③ 剩余/初始时间 ≤ min_time 丢弃（默认 0.0 秒 = 等价于 V2239 原 ≤ 0 规则）：
            #   · 剩余 ≤ min_time 且不在 V2216 永续豁免（≥9999）内 → 丢
            #   · 初始 ≤ min_time（不论是否永续）→ 丢
            # 玩家把 min_time 调到 > 0（如 0.5）即过滤 < 0.5 秒的瞬时 buff。
            if g_e_mintime:
                if remaining <= g_mintime and remaining < 9999.0: continue
                if initial <= g_mintime: continue

            # V2260 ⑤ 剩余时间 > 持续时间丢弃（可勾选，默认开启）：
            #   正常 buff 的 remaining 必然 ≤ initial（剩余不可能比总时长还长）。
            #   一旦 remaining > initial，说明内存里读到的是脏值/异常槽位，直接丢弃。
            #   永续 buff（infinite=True，显示 ∞ / *∞）豁免：它的 initial 可能为 0 而
            #   remaining 残留正数，属正常现象，不应被此条误杀（与 g_e_minrem / g_e_mininit 一致）。
            if g_e_remgtinit and not infinite and remaining > initial: continue
            if g_e_minrem and not infinite and remaining < g_minrem: continue
            # V2068：min_initial_time 加 `not infinite` 守卫——永续 buff 即使是 initial>0 也无意义
            # （在 visual 上无倒计时），不应该被「初始时间过短」误杀。与 g_e_minrem 守卫一致。
            if g_e_mininit and not infinite and initial < g_mininit: continue
            # V2096 BUGFIX：最小出现持续时间（防瞬时垃圾 buff）——旧逻辑 `if g_e_minappear and not _was_new`
            #   会让「刚出现那 1 帧」因 _was_new 跳过检查 → 显示；下一帧 _was_new=False 且 elapsed<阈值
            #   → 被门限排除 → 视觉上「闪一下」然后重新加入（用户实测新 buff 闪烁）。
            #   修法：引入 _buff_ever_shown——只要这个 sid 本会话出现过（哪怕只一帧），就永久放行，
            #   直到它真正从游戏数据里消失（下方 _raw_sids 清理）。这样：
            #     · 新 buff 立即显示，中途不会被「最小出现时间」门限丢掉 → 不再闪烁；
            #     · 真正「闪现即逝」的垃圾 buff 会显示到它自己消失为止（消失本身是正确的），不会被误留。
            #   旧意图「过滤 <阈值秒瞬时 buff」仍保留：这种 buff 会因自身消失而被移除，并非靠时间门限预过滤。
            if g_e_minappear:
                if sid in _ever_shown:
                    pass
                elif _was_new:
                    _ever_shown.add(sid)
                elif (_now - _seen[sid]) < g_minappear:
                    continue
                else:
                    _ever_shown.add(sid)
            # V2243 ① NaN/Inf 检查改为可勾选 gating——玩家可关。
            # V2072 fix 保留：纯 Python 比较——NaN 是唯一满足 x != x 的 float 值，Inf 用 == float('inf') 检测。
            _bad = False
            try:
                _bad = (initial != initial) or (remaining != remaining)
                if not _bad:
                    _bad = (initial == float("inf") or initial == float("-inf") or
                            remaining == float("inf") or remaining == float("-inf"))
            except Exception:
                _bad = False
            if g_e_nancheck and _bad: continue
            # ── 原有「过滤」开关（核心/永续/专属/专精/单层）──
            if ex_inf and infinite: continue
            if ex_excl and attr.get("是否专属"): continue
            if ex_mast and attr.get("是否专精buff"): continue
            if ex_single and attr.get("单层"): continue
            if ex_core and sid in core_sids: continue
            # V2095：把「真实秒数」折算进 info 副本再交给卡片绘制——
            # 百分比型 buff（如龙人化 sid=29，pct_cap=40）游戏存的是 0~100 的百分比读数，
            # 不折算的话卡片上显示的是 76.7（%）而不是真实的 30.7 秒。
            # 核心区（read_overlay_data）早已做这个折算，全 Buff 模块之前漏了。
            _pc = _pct.get(sid_i)
            if _pc and not infinite:
                _info2 = dict(info)
                try:
                    _rem2 = float(info.get("remaining", 0.0) or 0.0)
                except Exception:
                    _rem2 = 0.0
                _info2["remaining"] = min(_rem2 * _pc / 100.0, _pc)
                _info2["initial"] = _pc
            else:
                _info2 = info
            # V2117+V2211：隐藏「倒计时 0.0/0.0」与「remaining/initial 任一 < 0」已固化
            # （永续 buff 时间区无意义；负数时间表示数据异常或状态转换中，舍弃避免显示「-0.5/8.5」之类垃圾）
            _zr = float(_info2.get("remaining", 0.0) or 0.0)
            _zi = float(_info2.get("initial", 0.0) or 0.0)
            if _zr < 0 or _zi < 0 or f"{_zr:.1f}/{_zi:.1f}" == "0.0/0.0":
                continue
            # V2110：默认只显示 1 个实例（回滚 V2107 行为）。
            # 白名单（multi_buff_whitelist）内的 buff 不受去重限制，可显示多个实例（如帕西瓦尔双重追击）；
            # 名单外的所有 buff（含永续 / 角色专属）一律按 sid 只保留首实例。
            if sid not in _multi_buff_whitelist and sid in _shown_unique_sids:
                continue
            _shown_unique_sids.add(sid)
            # V2210 BUGFIX②：名单内的 sid 不去重（玩家要的就是同 sid 多实例），
            # 但游戏里同一条 status 有时会被读到多次（指针数组重复引用 / 内容完全相同的多条），
            # 于是「明明是同一个燃烧A却出现两张一模一样的卡」。
            # 用「内容指纹」去重：同 sid 且 sub_id/层数/剩余/持续/永续 五项全同 → 视为同一条的重复读取，
            # 只留 1 张；真正不同的实例（燃烧A rem=8.5 / 燃烧B rem=3.2）指纹不同，照旧全部显示。
            _fp = (sid_i, sub_id, cur_stacks,
                   round(float(_info2.get("remaining", 0.0) or 0.0), 1),
                   round(float(_info2.get("initial", 0.0) or 0.0), 1), infinite)
            if _fp in _seen_content_fp:
                continue
            _seen_content_fp.add(_fp)
            items.append((sid, _info2,  attr))
            # V2209：能走到这里的 buff 已通过全部门限；此时若是未收录的未知 buff，
            # 记进未知清单（每 5 秒落盘 buff_attrs_unknown.json，诊断日志，不提供外部改名通道）。
            if attr.get("_unknown"):
                _note_unknown_buff(sid)
        # V2063：根据排序方式选 key
        # 「按出现时间」= 首次出现得越早越靠前；新出现 buff 自动排到末尾。
        # V2076 修复：消失-再出现的 buff **重新**分配 seq（清空原 seq_map 项），
        # 实现"先进的 buff 就在最前面，消失后它自个儿的排序又要清空"——例：
        #   ABC 依次出现 → A=0, B=1, C=2 → 显示 ABC
        #   B 消失 → 清 B → A=0, C=2 → 显示 AC
        #   B 重新出现 → 分配 seq=3（_buff_next_seq 递增）→ 显示 ACB
        sort_mode = self.settings.get("allbuff_sort_mode", DEFAULT_SETTINGS["allbuff_sort_mode"])
        if sort_mode == "appearance":
            seq_map = getattr(self, "_buff_first_seen_seq", None)  # V2094: self==GBFROverlayQt, _buff_first_seen_seq 在 self 上
            ctrl_self = self  # 共用 ctrl_self 名字，让下面代码无需大改
            if seq_map is not None and hasattr(self, "_buff_next_seq"):
                # 1) 清理消失的 buff：seq_map 里存在但本次 items 没有的 sid 全部删除
                # V2088 BUGFIX：与 _seen 同理，必须用**原始数据源** buffs 的 sid 集合。
                #   用 items 的后果：某 buff 因门限（minrem/mininit/nan/ex_*）被丢 → 不在 items
                #   → 排序号被清 → 下一帧重新分配到队尾 → 卡片位置每帧跳变 → 视觉上疯狂闪烁。
                #   正确语义：只有「游戏里这个 buff 真的没了」才清空排序号。
                # V2093 BUGFIX（宽限期）：即使 buff 真的从游戏里消失，也**不立即**清排序号——
                #   内存读取偶发抖动（一帧读不到 / 换场景瞬间）会让 seq 被误清，
                #   buff 下一帧回来就被重新分配到队尾 → 位置跳变，玩家感觉「排序不对」。
                #   加宽限：记录首次消失时间，超过 allbuff_seq_gone_grace_sec（默认 1.0s）才真清。
                current_sids = set(sid for sid, _ in buffs)
                _grace = float(self.settings.get("allbuff_seq_gone_grace_sec", 1.0) or 0.0)
                _gone = getattr(ctrl_self, "_buff_gone_since", None)
                if _gone is None:
                    _gone = {}
                    ctrl_self._buff_gone_since = _gone
                for sid in list(seq_map.keys()):
                    if sid in current_sids:
                        # 回来了：取消消失计时
                        _gone.pop(sid, None)
                        continue
                    # 不在本次数据源里 → 可能是真消失，也可能只是抖动
                    if _grace <= 0.0:
                        del seq_map[sid]
                        _gone.pop(sid, None)
                        continue
                    _t0 = _gone.get(sid)
                    if _t0 is None:
                        _gone[sid] = _now           # 首次观测到消失，开始计时
                    elif (_now - _t0) >= _grace:
                        del seq_map[sid]            # 消失超过宽限 → 真清
                        del _gone[sid]
                # 2) 给新出现的 buff 分配 seq（_buff_next_seq 单调递增；已删的旧 seq 自然留下空洞但不影响排序）
                for sid, _info, _attr in items:
                    if sid not in seq_map:
                        seq_map[sid] = self._buff_next_seq  # V2094: 同上 self
                        self._buff_next_seq += 1
                items.sort(key=lambda t: (seq_map.get(t[0], 0), t[0]))
            else:
                # 防御性回退：仍按 sid
                items.sort(key=lambda t: t[0])
        else:
            items.sort(key=lambda t: t[0])

        # V2084：清理本帧消失的 sid（重置首次观测时间，下次再出现时重新计时）
        # V2088 BUGFIX：必须用**原始数据源** buffs 的 sid 集合，不能用过滤后的 items！
        #   用 items 的后果：某 buff 因「其他门限」（minrem/mininit/nan/ex_*）被丢 → 不在 items
        #   → 本帧把它从 _seen 删掉 → 下一帧变 _was_new=True → 又过 minappear → 又被其他门限丢
        #   → 每帧都在「新 → 丢 → 新 → 丢」震荡 → 全 Buff 模块疯狂闪烁。
        #   正确语义：只有「游戏里这个 buff 真的没了（原始 buffs 里读不到了）」才重置计时。
        _raw_sids = set(sid for sid, _ in buffs)
        for sid in list(_seen.keys()):
            if sid not in _raw_sids:
                del _seen[sid]
        # V2096：buff 真正从游戏数据里消失时，一并清掉「出现过」记忆，
        # 下次再出现会重新计时（重新出现即 _was_new → 再次立即放行）。
        for sid in list(_ever_shown):
            if sid not in _raw_sids:
                _ever_shown.discard(sid)

        # ── 固定布局：rows 行 × per_row 列（V2104）──
        # 模块尺寸固定（rows × per_row），不再随 buff 数量伸缩。
        # 排序规则（简化）：所有 Buff 在前（保持各自原有排序），所有 Debuff 接在 Buff 之后（不再单独分行）；
        # 总容量 = per_row × rows，超出直接截断丢弃。
        rows = max(1, int(self.settings.get("allbuff_rows", 3)))
        normal_items = [t for t in items if not _is_debuff(int(t[0]))]
        debuff_items = [t for t in items if _is_debuff(int(t[0]))]
        combined = (normal_items + debuff_items)[: per_row * rows]
        placed = [(idx, t) for idx, t in enumerate(combined)]

        # 名称字段（按语言）
        if lang == "en":
            name_key = "英文名"
        elif lang == "zh_tw":
            name_key = "繁中名"
        elif lang == "ja":
            name_key = "日文名"
        else:
            name_key = "名称"

        # ── 绘制固定网格 ──
        # V2226：行内水平对齐（靠左 / 居中 / 靠右，默认靠左）——按「每行实际卡片数」算该行偏移，
        # 只有最后一行（不足 per_row 个）才会看出差异，满行时三种对齐完全等价。
        _align_cfg = str(self.settings.get("allbuff_row_align", "left"))
        _avail_w = per_row * bw + max(0, per_row - 1) * card_sp
        for slot, (sid, info, attr) in placed:
            row = slot // per_row
            col = slot % per_row
            if _align_cfg == "left":
                _row_off = 0.0
            else:
                _row_n = min(per_row, len(placed) - row * per_row)
                _row_w = _row_n * bw + max(0, _row_n - 1) * card_sp
                _row_off = (_avail_w - _row_w) / 2.0 if _align_cfg == "center" else (_avail_w - _row_w)
            x = _row_off + col * (bw + card_sp)
            y = row * (bh + row_sp)
            is_debuff = _is_debuff(int(sid))
            # 接近尾声判定（rem/init 低于阈值）
            infinite = bool(info.get("infinite"))
            if infinite:
                is_low = False
            else:
                _rem = float(info.get("remaining", 0.0) or 0.0)
                _init = float(info.get("initial", 0.0) or 0.0)
                ratio = (_rem / _init) if _init > 0 else 0.0
                is_low = ratio < warn_thr
            self._draw_allbuff_card(
                painter, x, y, bw, bh, info, attr, name_key,
                name_fs, stacks_fs, time_fs, bar_w, bar_h,
                name_col, stacks_col, time_col, bar_col, backing_col,
                elem_sp, bar_frame_t,
                is_debuff, is_low, warn_en, warn_col,
                debuff_name_col, debuff_stacks_col, debuff_time_col, debuff_bar_col,
                debuff_warn_en, debuff_warn_col,
            )

        # ── 固定窗口尺寸（3 行 × per_row 列，含行/列间隙）── V2103
        self._apply_allbuff_fixed_size()

    def _apply_allbuff_fixed_size(self):
        """V2104：固定全 Buff 窗口尺寸（rows 行 × per_row 列，含行/列间隙），不随 buff 数量伸缩。
        即使无角色/无活动 Buff 也预留 rows × per_row 的固定区域。rows 取自 allbuff_rows（可调）。"""
        win = getattr(self, "allbuff_win", None)
        if win is None:
            return
        per_row = max(1, int(self.settings.get("allbuff_per_row", 10)))
        rows = max(1, int(self.settings.get("allbuff_rows", 3)))
        row_sp = int(self.settings.get("allbuff_row_spacing", 4))
        card_sp = int(self.settings.get("allbuff_card_spacing", 4))
        bw_setting = max(1, int(self.settings.get("allbuff_backing_width", 80)))
        bh_setting = max(1, int(self.settings.get("allbuff_backing_height", 64)))
        name_fs = max(1, int(self.settings.get("allbuff_name_font_size", 11)))
        stacks_fs = max(1, int(self.settings.get("allbuff_stacks_font_size", 10)))
        time_fs = max(1, int(self.settings.get("allbuff_time_font_size", 10)))
        bar_w = max(1, int(self.settings.get("allbuff_bar_width", 60)))
        bar_h = max(1, int(self.settings.get("allbuff_bar_height", 5)))
        bar_frame_t = max(0, min(10, int(self.settings.get("allbuff_bar_frame_thickness", 2))))
        elem_sp = int(self.settings.get("allbuff_element_spacing", 4))
        row_h_extra = int(self.settings.get("allbuff_row_height_extra", 0))
        from PySide6.QtGui import QFont as _QF, QFontMetrics as _QFM
        _afm_name = _QFM(_QF("Segoe UI", name_fs, _QF.Bold))
        _afm_stacks = _QFM(_QF("Segoe UI", stacks_fs, _QF.Bold))
        _afm_time = _QFM(_QF("Segoe UI", time_fs, _QF.Bold))
        _name_h = _afm_name.height() + 2 + row_h_extra
        _stacks_h = _afm_stacks.height() + 2 + row_h_extra
        _time_h = _afm_time.height() + 2 + row_h_extra
        pad = 2
        # V2209：融合后时间文本与进度条共用一行，行高取二者较大值（真实省掉一行）
        _fused_h = max(_time_h, (bar_h + 2 * bar_frame_t))
        auto_bh = (2 * pad + _name_h + elem_sp + _stacks_h + elem_sp + _fused_h)
        auto_bh = max(1, auto_bh)
        auto_bw = bar_w + 2 * bar_frame_t + 8
        bh = max(auto_bh, bh_setting)
        bw = max(auto_bw, bw_setting)
        actual_cw = per_row * bw + max(0, per_row - 1) * card_sp
        actual_ch = rows * bh + max(0, rows - 1) * row_sp
        self.allbuff_canvas_w = actual_cw
        self.allbuff_canvas_h = actual_ch
        new_w = max(1, int(actual_cw * win.disp_w))
        new_h = max(1, int(actual_ch * win.disp_h))
        if abs(new_w - win.width()) > 1.5 or abs(new_h - win.height()) > 1.5:
            win.resize(new_w, new_h)

    def _draw_allbuff_card(self, painter, x, y, bw, bh, info, attr, name_key,                           name_fs, stacks_fs, time_fs, bar_w, bar_h,
                           name_col, stacks_col, time_col, bar_col, backing_col,
                           elem_sp, bar_frame_t,
                           is_debuff, is_low, warn_en, warn_col,
                           debuff_name_col, debuff_stacks_col, debuff_time_col, debuff_bar_col,
                           debuff_warn_en, debuff_warn_col):
        """绘制单张轻量卡片：衬底 + 名称 + 层数/最大层 + 剩余/持续 + 倒计时横条（含 100% 外框）。"""
        painter.save()
        # 衬底（三处文字共用一套样式）
        painter.setPen(Qt.NoPen)
        painter.setBrush(backing_col)
        painter.drawRoundedRect(x, y, bw, bh, 3, 3)

        pad = 2
        cx = x + bw / 2.0

        # ── 颜色：根据 is_debuff / is_low 切换 ──
        if is_debuff:
            cur_name_col   = debuff_name_col
            cur_stacks_col = debuff_stacks_col
            cur_time_col   = debuff_time_col
            cur_bar_col    = debuff_bar_col
            if is_low and debuff_warn_en:
                cur_time_col = debuff_warn_col
                cur_bar_col  = debuff_warn_col
        else:
            cur_name_col   = name_col
            cur_stacks_col = stacks_col
            cur_time_col   = time_col
            cur_bar_col    = bar_col
            if is_low and warn_en:
                cur_time_col = warn_col
                cur_bar_col  = warn_col

        # 名称（顶部，V2064 自适应阶梯：name_fs → 10 → 9 → 8 → ElideRight）
        name = (attr.get(name_key) or "").strip()
        # V2217：移除名称右侧的 ∞ 永续符号——剩余/持续时间条里已显示 ∞（见下方时间区），
        # 名称处不再重复，避免长名被 ∞ 挤占宽度导致阶梯缩字/省略号截断。
        _name_disp = name
        # V2064：阶梯缩字——优先用玩家设置的 name_fs；超出 bw-4 时降到 10pt 重测，再降到 9pt、8pt，
        # 最后仍超才用 ElideRight(...)。这样长名（5+ 中文）能完整显示而不被省略号截断。
        # V2076 修复：玩家设的 name_fs 优先。
        # V2078 修复：阶梯改为"只缩不升"——玩家设 1pt 直接用 1pt（不再升到 8，玩家自负看不清楚）；
        # 玩家设 11pt 装不下才降到 10/9/8 找最大能装下的（防溢出）。
        # 之前的"只升不降"阶梯会让 render 端算的 _name_h 与 _draw_allbuff_card 实际 name_h 不一致——
        # render 端用 name_fs=1 算小高度，_draw_allbuff_card 用阶梯升到 8 算大高度，
        # 实际 _content_h > render 估算 → 外框底部超出 bh → 进度条被切。
        cur_name_fs = max(1, int(name_fs))
        cur_name = name
        # 阶梯降字号（不升）——从玩家设的值开始试，装不下就降到下一档（仅往下）
        _shrink_steps = sorted(set([cur_name_fs, 10, 9, 8]), reverse=True)
        _found = False
        for fs in _shrink_steps:
            if fs > cur_name_fs:
                continue  # V2078: 跳过比玩家设的还大的字号（不放大）
            fs = max(1, fs)
            _f = QFont("Segoe UI", fs, QFont.Bold)
            _fm = QFontMetrics(_f)
            _w = _fm.horizontalAdvance(_name_disp)  # V2095: 含 ∞ 一起测宽
            if _w <= max(1, bw - 4):
                cur_name_fs = fs
                cur_name = _name_disp  # V2095: 含 ∞
                _found = True
                break
        if not _found:
            # 都装不下（玩家设的字号本来就大，且 buff 名特别长），用 8pt 兜底 + elide
            cur_name_fs = min(8, max(1, int(name_fs)))
            _f = QFont("Segoe UI", cur_name_fs, QFont.Bold)
            _fm = QFontMetrics(_f)
            cur_name = _fm.elidedText(_name_disp, Qt.ElideRight, max(1, bw - 4))  # V2095
        f = QFont("Segoe UI", cur_name_fs, QFont.Bold)
        painter.setFont(f)
        painter.setPen(cur_name_col)
        fm = QFontMetrics(f)
        if fm.horizontalAdvance(cur_name) > max(1, bw - 4):
            cur_name = fm.elidedText(cur_name, Qt.ElideRight, max(1, bw - 4))
        # V2073: 用 fm.height()+2 替代 cur_name_fs+2，确保 QRect 容纳完整粗体字体
        # V2074: 在 fm.height()+2 基础上再加 row_h_extra（用户可调，默认 0，V2075 起允许负值）
        # V2075: QRect 高度 clamp >=1 防止负高度
        # V2076: 元素在衬底内水平垂直居中——按内容总高算起始 y，让整组元素在衬底里居中
        # V2236 居中复核（综合 V2076/V2078/V2226 既有实现）：
        # 文字——drawText(QRect(x, y, bw, line_h), Qt.AlignHCenter | Qt.AlignVCenter, text)
        # 进度条外框——bar_x = cx - full_w/2（水平居中），by = fy + (_fused_row_h - outer_h)/2（垂直居中于融合行）
        # 时间融合文本——addText(cx - tw/2, baseline_in_centered_rect) + 黑色描边（保证压在条上也清晰）
        # 三者共享同一融合行 _fused_row_h 中心，**严格水平 + 垂直居中于卡片**。
        # 计算顺序：先算各行实际高度，再算内容总高与居中起点，最后用 AlignHCenter|AlignVCenter 绘制
        _row_h_extra = int(self.settings.get("allbuff_row_height_extra", 0))
        name_h   = max(1, fm.height()  + 2 + _row_h_extra)
        stacks_h = max(1, QFontMetrics(QFont("Segoe UI", stacks_fs, QFont.Bold)).height() + 2 + _row_h_extra)
        time_h   = max(1, QFontMetrics(QFont("Segoe UI", time_fs,   QFont.Bold)).height() + 2 + _row_h_extra)
        _outer_h = bar_h + 2 * bar_frame_t
        # V2209：倒计时文本与进度条融合为同一行（文本浮在条上方），卡片由 4 行压成 3 行
        _content_h = name_h + elem_sp + stacks_h + elem_sp + max(time_h, _outer_h)
        _content_top = y + max(pad, (bh - _content_h) / 2)  # 上下 pad 自然对称；bh 不够时退化为 pad
        # 名称
        ny = _content_top
        painter.drawText(QRect(x, ny, bw, name_h), Qt.AlignHCenter | Qt.AlignVCenter, cur_name)

        # 层数 / 最大层（中部；单层显示 1/1）
        if attr.get("单层"):
            stacks_str = "1/1"
        else:
            st = int(info.get("stacks", 0) or 0)
            mx = int(info.get("max_stacks", 0) or 1)
            if mx <= 0:
                mx = 1
            stacks_str = f"{st}/{mx}"
        sy = ny + name_h + elem_sp
        f2 = QFont("Segoe UI", stacks_fs, QFont.Bold)
        painter.setFont(f2)
        painter.setPen(cur_stacks_col)
        # V2074：加 row_h_extra
        # V2076：用 AlignVCenter 在自己 QRect 内垂直居中（配合 _content_top 整体居中）
        painter.drawText(QRect(x, sy, bw, stacks_h), Qt.AlignHCenter | Qt.AlignVCenter, stacks_str)

        # V2209：倒计时文本与进度条融合为同一行——进度条照常绘制，倒计时文本居中浮在进度条上方，
        # 卡片从「名称 / 层数 / 时间 / 进度条」四行压缩为三行，省掉一整行的垂直空间。
        # 剩余 / 持续（时间区；警告色切换）
        # V2098：时间区始终显示最真实读到的 remaining/initial，绝不用 ∞ 替代。
        # 永续标志 ∞ 只出现在名称右侧（见上文 _name_disp），此处一律显示真实读值。
        # V2215：FLT_MAX（≈3.4e38）在游戏里表示「永续 / 无时限」，
        # 直接按 f"{rem:.1f}" 打印会变成 340282346638528860000000000000000000000.0 这种天文数字撑爆卡片，
        # 这里统一显示成 ∞。
        # V2216：玩家可在 UI 上区分「真永续」和「值过大自动判为永续」——
        #   · infinite=True（游戏自身声明的永续）→ 纯 "∞"；
        #   · infinite=False 但 remaining/initial ≥ 9999（值过大自动判定）→ "*∞"（前缀星号表示非游戏原声明）。
        # 其余情况照旧显示真实读值。
        infinite = bool(info.get("infinite"))  # V2216：本地重读一次，规避上方 infinite 变量被 refactor 移走的风险
        rem = float(info.get("remaining", 0.0) or 0.0)
        init = float(info.get("initial", 0.0) or 0.0)
        if infinite or rem >= 9999 or init >= 9999:
            time_str = "∞" if infinite else "*∞"
        else:
            time_str = f"{self._fmt_dur(rem)}/{self._fmt_dur(init)}"
        f3 = QFont("Segoe UI", time_fs, QFont.Bold)
        painter.setFont(f3)
        # V2073：同 stacks 用 fm3.height()+2
        # V2074：加 row_h_extra
        fm3 = QFontMetrics(f3)
        # 融合行：起点 = 原「时间行」位置；行高 = max(时间文字高, 进度条外框高)
        fy = sy + stacks_h + elem_sp
        # V2078 防御（融合版）：内容总高超出衬底 bh 时，把进度条外框 clamp 进剩余空间
        _actual_content_h = name_h + elem_sp + stacks_h + elem_sp + max(time_h, _outer_h)
        if _actual_content_h + 2 * pad > bh:
            _avail_for_outer = max(1, (bh - 2 * pad) - (name_h + elem_sp + stacks_h + elem_sp))
            if _avail_for_outer < _outer_h:
                _outer_h = max(1, _avail_for_outer)  # 进度条外框高度 clamp 到剩余可用空间
        if infinite:
            ratio = 1.0
        else:
            init = float(info.get("initial", 0.0) or 0.0)
            rem = float(info.get("remaining", 0.0) or 0.0)
            ratio = (rem / init) if init > 0 else 0.0
            ratio = max(0.0, min(1.0, ratio))
        full_w = min(bar_w, bw - 4)
        bar_x = int(round(cx - full_w / 2.0))
        # V2078: outer_h 用 _outer_h（被前面的防御 clamp 过），不再用 bar_h+2*bar_frame_t 重新算
        outer_h = _outer_h
        _fused_row_h = max(time_h, outer_h)
        # 进度条垂直居中于融合行（时间文字随后浮在其上）
        by = fy + max(0, (_fused_row_h - outer_h) / 2.0)
        # 外框：4 条 bar_col 描边
        if bar_frame_t > 0:
            pen = QPen(cur_bar_col)
            pen.setWidth(max(1, bar_frame_t))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            # 上下两边
            painter.drawLine(bar_x, by, bar_x + full_w, by)
            painter.drawLine(bar_x, by + outer_h, bar_x + full_w, by + outer_h)
            # 左右两边
            painter.drawLine(bar_x, by, bar_x, by + outer_h)
            painter.drawLine(bar_x + full_w, by, bar_x + full_w, by + outer_h)
        # 内：track + fill
        inner_x = bar_x + bar_frame_t
        inner_y = by + bar_frame_t
        inner_w = max(0, full_w - 2 * bar_frame_t)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))          # 轨道底
        if inner_w > 0 and bar_h > 0:
            painter.drawRect(inner_x, inner_y, inner_w, bar_h)
            painter.setBrush(cur_bar_col)               # 填充
            painter.drawRect(inner_x, inner_y, int(round(inner_w * ratio)), bar_h)
        # V2209：倒计时文本居中浮在进度条上方；描一层深色边，保证压在进度条上也清晰可读
        _tpath = QPainterPath()
        _tw = fm3.horizontalAdvance(time_str)
        _tpath.addText(cx - _tw / 2.0,
                       fy + (_fused_row_h - fm3.height()) / 2.0 + fm3.ascent(),
                       f3, time_str)
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(_tpath)
        painter.setPen(Qt.NoPen)
        painter.setBrush(cur_time_col)
        painter.drawPath(_tpath)
        painter.restore()

    # V2115：删除 _draw_allbuff_placeholder 占位提示函数——未检测到角色 / 无活动 Buff 时不再画任何文字，
    # 只保留 _draw_module_backdrop 背景板（已在上方 render_allbuff 调用过），玩家看到的就是一个空壳。

    def render_bossbuff(self, painter):
        """网格化列出当前 BOSS 身上可读到的全部 buff/debuff（已 gate 过滤）。
        V2200：数据源 = boss_actor + 0xCF8 的 ExStatus（list begin = actor + 0xD10）。
        外观/布局/门限逻辑与全 Buff 模块一致（复制自 render_allbuff）。"""
        # V2064：模块独立显隐开关：关闭时整窗隐藏由 _apply_live_settings / 启动逻辑处理，
        # 这里仍兜底返回，确保任何残留绘制都不出现。
        if not bool(self.settings.get("show_boss_module", True)):
            return

        # V2063：与 SkillWindow 一致——每次绘制前刷新「非战斗」内容乘数，
        # 保证 boss_win 独立重绘时（core_win 未重绘）也使用最新的隐藏状态。
        self._out_of_combat_mult = getattr(self, "_ooc_content_mult", 1.0)

        # V2064：画布级不透明背景填充——防止背景窗口（如设置对话框）的内容透出来
        # 在 settings 标签里玩家可调，默认 0 = 不画（保留 V2063 之前的纯透明外观）。
        # 玩家遇到「buff 文字显示不全/有路径片段透过」时把这里调到 30~70 即可遮罩。
        canvas_bg_op = max(0, min(100, int(self.settings.get("boss_canvas_bg_opacity", 0)))) / 100.0
        if canvas_bg_op > 0.0:
            cw_canvas = getattr(self, "boss_canvas_w", 0)
            ch_canvas = getattr(self, "boss_canvas_h", 0)
            if cw_canvas > 0 and ch_canvas > 0:
                painter.save()
                bg = QColor(0, 0, 0)
                bg.setAlphaF(canvas_bg_op)
                painter.setPen(Qt.NoPen)
                painter.setBrush(bg)
                painter.drawRoundedRect(0, 0, cw_canvas, ch_canvas, 4, 4)
                painter.restore()

        # V2101：模块背景/线框——仅由「锁定」决定可见性，永不绑定战斗；
        # 与核心/能力/翻滚模块的 _draw_module_backdrop 完全一致（未锁定时底框始终显示）。
        # 此处先画底框，再让下方的「非战斗隐藏」只隐藏内容、不隐藏底框（与核心模块一致）。
        self._draw_module_backdrop(painter, self.boss_canvas_w, self.boss_canvas_h, draw_border=True, module_key="boss")

        # V2084：非战斗隐藏——「非战斗隐藏」开启且非战斗时，仅隐藏内容区（底框保留），
        # 与 render_core / render_roll / render_skill_cd 一致；之前误把整窗（含底框）一起隐藏。
        if self._out_of_combat_mult <= 0.0:
            return

        lang = self.settings.get("language", "zh")
        status = getattr(self, "status", "init")
        # V2200：boss 模块不依赖主控角色，改以「是否定位到 boss actor」为准
        has_char = bool(getattr(self, "boss_actor", None))
        # V2115：未检测到角色 / 初始化时不再画任何占位文字——只保留 _draw_module_backdrop 背景，
        # _apply_boss_fixed_size 仍保留以维持固定区域/可拖动/可缩放（与 _draw_module_backdrop 配合）。
        if status in ("no_game", "init") or not has_char:
            self._apply_boss_fixed_size()  # V2103：无角色也预留 3 行固定区域
            return


        buffs = getattr(self, "boss_buffs_filtered", []) or []

        if not buffs:
            # V2115：同 V2115 顶部说明——无活动 Buff 时也不画占位文字。
            self._apply_boss_fixed_size()  # V2103：无活动 Buff 也预留 3 行固定区域
            return

        # ── 读取布局 / 样式参数 ──
        # V2062：取消「显示行数」硬上限 → 改为 ceil(n/per_row) 自动延伸
        per_row = max(1, int(self.settings.get("boss_per_row", 10)))
        row_sp = int(self.settings.get("boss_row_spacing", 4))
        card_sp = int(self.settings.get("boss_card_spacing", 4))
        bw_setting = max(1, int(self.settings.get("boss_backing_width", 80)))
        bh_setting = max(1, int(self.settings.get("boss_backing_height", 64)))

        name_fs = max(1, int(self.settings.get("boss_name_font_size", 11)))
        stacks_fs = max(1, int(self.settings.get("boss_stacks_font_size", 10)))
        time_fs = max(1, int(self.settings.get("boss_time_font_size", 10)))
        bar_w = max(1, int(self.settings.get("boss_bar_width", 60)))
        bar_h = max(1, int(self.settings.get("boss_bar_height", 5)))
        # V2060：进度条外框粗细（0=不要外框）+ 卡片内统一垂直间距
        bar_frame_t = max(0, min(10, int(self.settings.get("boss_bar_frame_thickness", 2))))
        # V2075：允许负值——负间距让卡片内各行更紧凑（可重叠）
        elem_sp = int(self.settings.get("boss_element_spacing", 4))
        # V2074：行高加成——在三行文字实测 QFontMetrics.height()+2 基础上额外加的高度（默认 0）
        # V2075：允许负值——负加成收紧行高（QRect 高度在 _draw_boss_card 内 clamp 到 >=1）
        row_h_extra = int(self.settings.get("boss_row_height_extra", 0))

        # V2062：自适应 floor——按当前字体/元素间距/进度条/外框厚度算出「最小可视高度/宽度」
        # 取 max(自适应最小值, 用户设置) ⇒ 永远不裁切 buff 内容，玩家仍可在自适应基础上继续加 padding
        # V2073：用 QFontMetrics 实际测量行高替代 `font_size + 2` 硬编码——
        # 11pt Segoe UI Bold 的 fm.height()≈15-17px（视系统字体），font_size+2=13 不够，
        # QRect 高度偏小→中文字符 ascender 顶部被卡片圆角裁切，表现为「減」「消」「霸」等
        # 汉字上半部被遮挡、进度条上沿被切。auto_bh 与三行文字绘制均用 fm.height()+2 同步。
        from PySide6.QtGui import QFont as _QF, QFontMetrics as _QFM
        _afm_name   = _QFM(_QF("Segoe UI", name_fs,   _QF.Bold))
        _afm_stacks = _QFM(_QF("Segoe UI", stacks_fs, _QF.Bold))
        _afm_time   = _QFM(_QF("Segoe UI", time_fs,   _QF.Bold))
        _name_h   = _afm_name.height()   + 2 + row_h_extra
        _stacks_h = _afm_stacks.height() + 2 + row_h_extra
        _time_h   = _afm_time.height()   + 2 + row_h_extra
        pad = 2
        # V2217：融合为 3 行（名称 / 层数 / 时间+进度条共用一行），行高取 max(时间, 进度条外框)；
        # 与 _apply_allbuff_fixed_size / _draw_allbuff_card 的 _content_h 完全一致，避免卡片比窗口槽高导致多排被切。
        _fused_h = max(_time_h, (bar_h + 2 * bar_frame_t))
        auto_bh = (2 * pad
                   + _name_h       # 名称行高（QFontMetrics 实测）
                   + elem_sp
                   + _stacks_h     # 层数行高（QFontMetrics 实测）
                   + elem_sp
                   + _fused_h)     # 时间+进度条融合行（取二者较大值）
        # V2075：负 elem_sp 可能让 auto_bh 变很小甚至为负 → clamp 到 >=1，
        # 但 bh 最终还会取 max(auto_bh, bh_setting)，玩家设的衬底高度仍优先。
        auto_bh = max(1, auto_bh)
        auto_bw = bar_w + 2 * bar_frame_t + 8     # 4 px 左右 padding，避免贴边
        # V2077 防御：force_bh_min = 内容总高 + 上下 pad，确保 _draw_boss_card
        # 算出 _content_top 居中起点后，by + outer_h 永远在衬底内（不被切）。
        # auto_bh 算式已含 2*pad + _content_h，所以 auto_bh 已经是这个值。
        # 但 _draw_boss_card 内会用 cur_name_fs（阶梯缩字后）算 name_h，
        # 与这里的 _name_h 可能略不同（实际更小，不会更糟），所以理论上安全。
        bh = max(auto_bh, bh_setting)
        bw = max(auto_bw, bw_setting)

        name_col = QColor(self._get_color("boss_name_color"))
        stacks_col = QColor(self._get_color("boss_stacks_color"))
        time_col = QColor(self._get_color("boss_time_color"))
        bar_col = QColor(self._get_color("boss_bar_color"))
        bar_op = max(0, min(100, int(self.settings.get("boss_bar_color_opacity", 100)))) / 100.0
        bar_col.setAlpha(int(255 * bar_op))
        backing_col = QColor(self._get_color("boss_backing_color"))
        backing_op = max(0, min(100, int(self.settings.get("boss_backing_color_opacity", 50)))) / 100.0
        backing_col.setAlpha(int(255 * backing_op))

        # ── V2060：倒计时尾声警告（buff） ──
        warn_en = bool(self.settings.get("boss_warn_enabled", False))
        warn_thr = max(1, min(99, int(self.settings.get("boss_warn_threshold_pct", 20)))) / 100.0
        warn_col = QColor(self._get_color("boss_warn_color"))
        warn_op = max(0, min(100, int(self.settings.get("boss_warn_color_opacity", 100)))) / 100.0
        warn_col.setAlpha(int(255 * warn_op))

        # ── V2060：Debuff 配色（编号 ≥ 1000） ──
        debuff_name_col  = QColor(self._get_color("boss_debuff_name_color"))
        debuff_stacks_col= QColor(self._get_color("boss_debuff_stacks_color"))
        debuff_time_col  = QColor(self._get_color("boss_debuff_time_color"))
        debuff_bar_col   = QColor(self._get_color("boss_debuff_bar_color"))
        debuff_bar_op = max(0, min(100, int(self.settings.get("boss_debuff_bar_color_opacity", 100)))) / 100.0
        debuff_bar_col.setAlpha(int(255 * debuff_bar_op))
        # Debuff 警告
        debuff_warn_en = bool(self.settings.get("boss_debuff_warn_enabled", True))
        debuff_warn_col = QColor(self._get_color("boss_debuff_warn_color"))
        debuff_warn_op = max(0, min(100, int(self.settings.get("boss_debuff_warn_color_opacity", 100)))) / 100.0
        debuff_warn_col.setAlpha(int(255 * debuff_warn_op))

        # ── 过滤开关（默认全关 = 显示全部）──
        # V2314：移除 ex_excl（boss_exclude_exclusive）/ ex_mast（boss_exclude_mastery）两行死赋值。
        #   这两键自 V2226 起已废弃——Boss 的「角色专属 / 专精」过滤是固化的无条件剔除（见下方），
        #   且 Boss 侧从未有过对应 UI 控件（allbuff 侧才有），键本身也已于 V2314 从 DEFAULT_SETTINGS 删除。
        ex_core = bool(self.settings.get("boss_exclude_core", False))
        ex_inf = bool(self.settings.get("boss_exclude_infinite", False))
        ex_single = bool(self.settings.get("boss_exclude_single", False))

        core_sids = set()
        if ex_core:
            prof = BUFF_PROFILES.get(self.pl_id, {})
            for b in prof.get("buffs", []):
                sid = b.get("sid")
                if isinstance(sid, int) and sid >= 0:
                    core_sids.add(sid)

        # ── V2066：门限（monitor 风格数值废料过滤）——在「过滤」开关之前先过滤 ──
        # V2216：删 boss_gate_filter_status_id_zero 键 + 复选框；「过滤 status_id == 0」已固化为常闭
        # V2222：sid==0 不再硬丢（用户要求 sid==0 永远显示）。status_id/sub_id 上限恢复为可配置门限，
        # 由下方 g_e_sidmax/g_sidmax/g_e_submax/g_submax 控制（默认 0xFFFF 等同旧硬编码常闭）。
        g_e_sidmax = bool(self.settings.get("boss_gate_enabled_status_id_max", True))
        g_sidmax = int(self.settings.get("boss_gate_status_id_max", 0xFFFF))
        g_e_submax = bool(self.settings.get("boss_gate_enabled_sub_id_max", True))
        g_submax = int(self.settings.get("boss_gate_sub_id_max", 0xFFFF))
        g_e_stkmax = bool(self.settings.get("boss_gate_enabled_stacks_max", True))
        g_stkmax = int(self.settings.get("boss_gate_stacks_max", 100))
        g_e_mstkmax = bool(self.settings.get("boss_gate_enabled_max_stacks_max", False))
        g_mstkmax = int(self.settings.get("boss_gate_max_stacks_max", 100))
        # V2314：移除 g_conflict（boss_gate_check_stack_conflict）死赋值——层数矛盾检查已固化为
        #   循环内「max_stacks > 0 and cur_stacks > max_stacks」无条件丢弃，无 UI 开关；该键
        #   早已被 get_settings() 主动 pop（废弃键），此处读取恒等于兜底值 True 且从未被使用。
        g_e_durmax = bool(self.settings.get("boss_gate_enabled_duration_max", True))
        # V2260 ⑤：剩余时间 > 持续时间（remaining > initial）视为脏值丢弃（可勾选，默认开启）。
        g_e_remgtinit = bool(self.settings.get("boss_gate_rem_gt_init_drop", True))
        # V2314：移除 g_durmax（boss_gate_duration_max）死赋值——真正生效的是循环内读的
        #   boss_gate_duration_max_with_infinite_exemption；旧键 boss_gate_duration_max 已被
        #   get_settings() 主动 pop，此处读取从未被使用。
        g_e_minrem = bool(self.settings.get("boss_gate_enabled_min_remaining_time", True))
        g_minrem = float(self.settings.get("boss_gate_min_remaining_time", 0.05))
        g_e_mininit = bool(self.settings.get("boss_gate_enabled_min_initial_time", True))
        g_mininit = float(self.settings.get("boss_gate_min_initial_time", 0.05))
        g_e_minappear = bool(self.settings.get("boss_gate_enabled_min_appearance_time", True))  # V2084
        g_minappear = float(self.settings.get("boss_gate_min_appearance_time", 0.1))         # V2084
        # V2243: boss 端同样新增 4 条可勾选 gating keys（与主控对称）。
        g_e_nancheck = bool(self.settings.get("boss_gate_check_nan_inf", True))
        g_e_id01inf = bool(self.settings.get("boss_gate_filter_status_id_zero_one_infinite_enabled", True))
        g_e_mintime = bool(self.settings.get("boss_gate_check_min_time_enabled", True))
        g_mintime = float(self.settings.get("boss_gate_min_time", 0.0))
        # V2314：删除与上方 g_e_durmax 完全重复的这行赋值（boss_gate_enabled_duration_max 读了两次）。
        # V2116：全 Buff「黑名单」——名单内 sid 永不显示（无视任何其它开关，最优先过滤）
        # V2110/V2116：「多次出现名单」——名单内 sid 不受去重限制，可显示多个实例；其余按 sid 只保留 1 个
        def _collect_sids(setting_key, exclusive=False):
            out = set()
            for _e in (self.settings.get(setting_key) or []):
                try:
                    _s = int(_e.get("sid"))
                    if 0 <= _s <= 0xFFFF:
                        # V2111/V2116：专属 buff 永远不可多次出现 / 不必入黑名单（render 端硬保险剔除）
                        _wa = BUFF_ATTRS.get(f"0x{_s:X}({_s})")
                        if _wa and _wa.get("是否专属"):
                            continue
                        out.add(_s)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
            return out
        _boss_blacklist = _collect_sids("boss_blacklist")
        _boss_multi_list = _collect_sids("boss_multi_list")

        # ── V2095：构建 sid→pct_cap 映射（百分比型 buff 如龙人化，游戏存的是 0~100 读数）──
        # 从 BUFF_PROFILES（i18n.json 的角色配表）合并，一次算好缓存到 self，避免每帧重建。
        _pct = getattr(self, "_pct_cap_by_sid", None)
        if _pct is None:
            _pct = {}
            try:
                for _pl, _prof in (BUFF_PROFILES or {}).items():
                    for _b in (_prof.get("buffs") or []):
                        _sidv = _b.get("sid")
                        _pc = _b.get("pct_cap")
                        if isinstance(_sidv, int) and _sidv >= 0 and _pc:
                            _pct[_sidv] = float(_pc)
            except Exception:
                _pct = {}
            self._pct_cap_by_sid = _pct
        # ── 收集 + 过滤 + 排序（按 sid 稳定排序）──
        items = []
        # V2109：永续 / 角色专属 buff 只保留 1 个实例（不去重普通有限 buff）
        _shown_unique_sids = set()
        # V2210：内容指纹去重集合（同 sid 且五项数据全同 → 视为同一条 status 的重复读取）
        _seen_content_fp = set()
        # V2084：维护「首次观测到的时间」dict，判定瞬时 buff（闪现即逝）是否够老
        _now = time.time()
        if not hasattr(self, "_bossbuff_first_seen"):
            self._bossbuff_first_seen = {}
        _seen = self._bossbuff_first_seen
        # V2096：与 _seen 配套，记录「已经出现过（哪怕只出现一帧）」的 sid，
        # 用来消除「最小出现持续时间」门限造成的闪烁——见下方 g_e_minappear 处的说明。
        if not hasattr(self, "_bossbuff_ever_shown"):
            self._bossbuff_ever_shown = set()
        _ever_shown = self._bossbuff_ever_shown
        # V2224：每帧按 mtime 热加载外部补充文件（玩家保存后 <1 秒生效）
        _reload_user_attrs()
        for sid, info in buffs:
            attr = _attr_for_sid(sid)
            # V2224：attr 已按「外部补充 > 内置 > 未知兜底(hex ID)」三优先级取好；
            # `_is_debuff(sid)` 自身有 sid>=1000 兜底，因此兜底 attr 不必设「是否debuff」键。
            # V2116：黑名单 sid 永不显示（在所有门限/开关之前生效，玩家最强制最强的过滤）
            if sid in _boss_blacklist:
                continue
            # V2306 BUGFIX：同 render_allbuff——调试态跳过所有门限/过滤开关，保证假 buff 全显。
            if _DEBUG_ATTR.get("active"):
                items.append((sid, info, attr))
                continue
            # V2084：首次观测到的 buff 记录时间，已观测的复用。消失的 sid 在循环外清理。
            # V2087 BUGFIX①：原版 `_seen[sid] = _now` 后立刻判 `_now - _seen[sid] < 阈值`
            #              → 首次观测必然 `_now - _now = 0 < 阈值` → 被丢（全 Buff 空白）。
            # V2088 BUGFIX②：V2087 的修法仍有致命漏洞——`_seen[sid] = _now` 是**无条件刷新**，
            #              每帧都把"首次时间"改写成当前时间 → 已知 buff 的差值永远≈0
            #              → 帧1 显示 / 帧2 丢 / 帧3 显示... → **疯狂闪烁**。
            #              正确写法：只在首次记录，之后**不再刷新**。
            _was_new = sid not in _seen
            if _was_new:
                _seen[sid] = _now
            # ── 门限：数值废料判定（不依赖 BUFF_ATTRS，纯数值阈值）──
            sid_i = int(sid)
            sub_id = int(info.get("sub_id", 0) or 0)
            cur_stacks = int(info.get("stacks", 0) or 0)
            max_stacks = int(info.get("max_stacks", 0) or 0)
            initial = float(info.get("initial", 0.0) or 0.0)
            remaining = float(info.get("remaining", 0.0) or 0.0)
            infinite = bool(info.get("infinite"))
            # V2222：sid==0 不再硬丢（用户要求 sid==0 永远显示，攻击UP 等 sid==0 条目现在也会显示）。
            # status_id / sub_id 上限恢复为「门限(阈值)」机制：由设置里的
            # *_gate_enabled_status_id_max / *_gate_status_id_max（及 sub 对应项）控制；
            # 默认阈值 0xFFFF，与旧硬编码常闭等价，玩家可在「门限」页调节。
            if g_e_sidmax and sid_i > g_sidmax: continue
            if g_e_submax and sub_id > g_submax: continue
            if g_e_stkmax and not (0 <= cur_stacks <= g_stkmax): continue
            if g_e_mstkmax and not (0 <= max_stacks <= g_mstkmax): continue
            # 层数矛盾检查：max_stacks=0 视为「无上限/未定义」不触发丢弃
            if max_stacks > 0 and cur_stacks > max_stacks: continue
            _huge_t = (remaining >= 9999) or (initial >= 9999)
            # V2243 ④ 时长上限（与主控对称）：en 键启用 + val 键数值；玩家取消勾选 = 不过滤时长上限异常。
            _g_dur_max = float(self.settings.get("boss_gate_duration_max_with_infinite_exemption", 10000.0))
            if g_e_durmax and not _huge_t and (initial > _g_dur_max or remaining > _g_dur_max): continue
            # V2243 ② ID=0/ID=1 不可能是永续（与主控对称）：攻击UP/防御UP 槽位的垃圾条目会被过滤。
            if g_e_id01inf and sid_i in (0, 1) and infinite: continue
            # V2243 ③ 剩余/初始时间 ≤ min_time 丢弃（与主控对称）：默认 0.0 秒,玩家可调到 > 0 过滤瞬时 buff。
            if g_e_mintime:
                if remaining <= g_mintime and remaining < 9999.0: continue
                if initial <= g_mintime: continue

            # V2260 ⑤ 剩余时间 > 持续时间丢弃（可勾选，默认开启）：
            #   正常 buff 的 remaining 必然 ≤ initial（剩余不可能比总时长还长）。
            #   一旦 remaining > initial，说明内存里读到的是脏值/异常槽位，直接丢弃。
            #   永续 buff（infinite=True，显示 ∞ / *∞）豁免：它的 initial 可能为 0 而
            #   remaining 残留正数，属正常现象，不应被此条误杀（与 g_e_minrem / g_e_mininit 一致）。
            if g_e_remgtinit and not infinite and remaining > initial: continue
            if g_e_minrem and not infinite and remaining < g_minrem: continue
            # V2068：min_initial_time 加 `not infinite` 守卫——永续 buff 即使是 initial>0 也无意义
            # （在 visual 上无倒计时），不应该被「初始时间过短」误杀。与 g_e_minrem 守卫一致。
            if g_e_mininit and not infinite and initial < g_mininit: continue
            # V2096 BUGFIX：最小出现持续时间（防瞬时垃圾 buff）——旧逻辑 `if g_e_minappear and not _was_new`
            #   会让「刚出现那 1 帧」因 _was_new 跳过检查 → 显示；下一帧 _was_new=False 且 elapsed<阈值
            #   → 被门限排除 → 视觉上「闪一下」然后重新加入（用户实测新 buff 闪烁）。
            #   修法：引入 _bossbuff_ever_shown——只要这个 sid 本会话出现过（哪怕只一帧），就永久放行，
            #   直到它真正从游戏数据里消失（下方 _raw_sids 清理）。这样：
            #     · 新 buff 立即显示，中途不会被「最小出现时间」门限丢掉 → 不再闪烁；
            #     · 真正「闪现即逝」的垃圾 buff 会显示到它自己消失为止（消失本身是正确的），不会被误留。
            #   旧意图「过滤 <阈值秒瞬时 buff」仍保留：这种 buff 会因自身消失而被移除，并非靠时间门限预过滤。
            if g_e_minappear:
                if sid in _ever_shown:
                    pass
                elif _was_new:
                    _ever_shown.add(sid)
                elif (_now - _seen[sid]) < g_minappear:
                    continue
                else:
                    _ever_shown.add(sid)
            # V2243 ① NaN/Inf 检查改为可勾选 gating（与主控对称）。V2072 fix 保留。
            _bad = False
            try:
                _bad = (initial != initial) or (remaining != remaining)
                if not _bad:
                    _bad = (initial == float("inf") or initial == float("-inf") or
                            remaining == float("inf") or remaining == float("-inf"))
            except Exception:
                _bad = False
            if g_e_nancheck and _bad: continue
            # ── 原有「过滤」开关（核心/永续/专属/专精/单层）──
            if ex_inf and infinite: continue
            # V2226：内部固化门限（永远开启，无 UI 开关）——boss 身上不可能出现「角色专属」
            # 与「专精」buff（这两类只属于玩家角色）。若读到只可能是玩家角色数据残留/误读，
            # 无条件剔除。
            # V2314：已删除 ex_excl（boss_exclude_exclusive）/ ex_mast（boss_exclude_mastery）两个
            #   废弃键及其死赋值读取——Boss 侧从未有过对应 UI 控件（allbuff 侧才有），保留只会误导维护。
            if attr.get("是否专属"): continue
            if attr.get("是否专精buff"): continue
            if ex_single and attr.get("单层"): continue
            if ex_core and sid in core_sids: continue
            # V2095：把「真实秒数」折算进 info 副本再交给卡片绘制——
            # 百分比型 buff（如龙人化 sid=29，pct_cap=40）游戏存的是 0~100 的百分比读数，
            # 不折算的话卡片上显示的是 76.7（%）而不是真实的 30.7 秒。
            # 核心区（read_overlay_data）早已做这个折算，全 Buff 模块之前漏了。
            _pc = _pct.get(sid_i)
            if _pc and not infinite:
                _info2 = dict(info)
                try:
                    _rem2 = float(info.get("remaining", 0.0) or 0.0)
                except Exception:
                    _rem2 = 0.0
                _info2["remaining"] = min(_rem2 * _pc / 100.0, _pc)
                _info2["initial"] = _pc
            else:
                _info2 = info
            # V2117+V2211：隐藏「倒计时 0.0/0.0」与「remaining/initial 任一 < 0」已固化
            # （永续 buff 时间区无意义；负数时间表示数据异常或状态转换中，舍弃避免显示「-0.5/8.5」之类垃圾）
            _zr = float(_info2.get("remaining", 0.0) or 0.0)
            _zi = float(_info2.get("initial", 0.0) or 0.0)
            if _zr < 0 or _zi < 0 or f"{_zr:.1f}/{_zi:.1f}" == "0.0/0.0":
                continue
            # V2110：默认只显示 1 个实例（回滚 V2107 行为）。
            # 多次出现名单（boss_multi_list）内的 buff 不受去重限制，可显示多个实例（如帕西瓦尔双重追击）；
            # 名单外的所有 buff（含永续 / 角色专属）一律按 sid 只保留首实例。
            if sid not in _boss_multi_list and sid in _shown_unique_sids:
                continue
            _shown_unique_sids.add(sid)
            # V2210 BUGFIX②：名单内的 sid 不去重（玩家要的就是同 sid 多实例），
            # 但游戏里同一条 status 有时会被读到多次（指针数组重复引用 / 内容完全相同的多条），
            # 于是「明明是同一个燃烧A却出现两张一模一样的卡」。
            # 用「内容指纹」去重：同 sid 且 sub_id/层数/剩余/持续/永续 五项全同 → 视为同一条的重复读取，
            # 只留 1 张；真正不同的实例（燃烧A rem=8.5 / 燃烧B rem=3.2）指纹不同，照旧全部显示。
            _fp = (sid_i, sub_id, cur_stacks,
                   round(float(_info2.get("remaining", 0.0) or 0.0), 1),
                   round(float(_info2.get("initial", 0.0) or 0.0), 1), infinite)
            if _fp in _seen_content_fp:
                continue
            _seen_content_fp.add(_fp)
            items.append((sid, _info2,  attr))
            # V2209：能走到这里的 buff 已通过全部门限；此时若是未收录的未知 buff，
            # 记进未知清单（每 5 秒落盘 buff_attrs_unknown.json，诊断日志，不提供外部改名通道）。
            if attr.get("_unknown"):
                _note_unknown_buff(sid)
        # V2213 debug：每 1 秒 dump 过滤后 items + 过滤前原始数据 buffs（对比看哪个被门限丢了）
        _dump_boss_buffs(items, buffs)
        # V2063：根据排序方式选 key
        # 「按出现时间」= 首次出现得越早越靠前；新出现 buff 自动排到末尾。
        # V2076 修复：消失-再出现的 buff **重新**分配 seq（清空原 seq_map 项），
        # 实现"先进的 buff 就在最前面，消失后它自个儿的排序又要清空"——例：
        #   ABC 依次出现 → A=0, B=1, C=2 → 显示 ABC
        #   B 消失 → 清 B → A=0, C=2 → 显示 AC
        #   B 重新出现 → 分配 seq=3（_buff_next_seq 递增）→ 显示 ACB
        sort_mode = self.settings.get("boss_sort_mode", DEFAULT_SETTINGS["boss_sort_mode"])
        if sort_mode == "appearance":
            seq_map = getattr(self, "_bossbuff_first_seen_seq", None)  # V2094: self==GBFROverlayQt, _bossbuff_first_seen_seq 在 self 上
            ctrl_self = self  # 共用 ctrl_self 名字，让下面代码无需大改
            if seq_map is not None and hasattr(self, "_buff_next_seq"):
                # 1) 清理消失的 buff：seq_map 里存在但本次 items 没有的 sid 全部删除
                # V2088 BUGFIX：与 _seen 同理，必须用**原始数据源** buffs 的 sid 集合。
                #   用 items 的后果：某 buff 因门限（minrem/mininit/nan/ex_*）被丢 → 不在 items
                #   → 排序号被清 → 下一帧重新分配到队尾 → 卡片位置每帧跳变 → 视觉上疯狂闪烁。
                #   正确语义：只有「游戏里这个 buff 真的没了」才清空排序号。
                # V2093 BUGFIX（宽限期）：即使 buff 真的从游戏里消失，也**不立即**清排序号——
                #   内存读取偶发抖动（一帧读不到 / 换场景瞬间）会让 seq 被误清，
                #   buff 下一帧回来就被重新分配到队尾 → 位置跳变，玩家感觉「排序不对」。
                #   加宽限：记录首次消失时间，超过 boss_seq_gone_grace_sec（默认 1.0s）才真清。
                current_sids = set(sid for sid, _ in buffs)
                _grace = float(self.settings.get("boss_seq_gone_grace_sec", 1.0) or 0.0)
                _gone = getattr(ctrl_self, "_buff_gone_since", None)
                if _gone is None:
                    _gone = {}
                    ctrl_self._buff_gone_since = _gone
                for sid in list(seq_map.keys()):
                    if sid in current_sids:
                        # 回来了：取消消失计时
                        _gone.pop(sid, None)
                        continue
                    # 不在本次数据源里 → 可能是真消失，也可能只是抖动
                    if _grace <= 0.0:
                        del seq_map[sid]
                        _gone.pop(sid, None)
                        continue
                    _t0 = _gone.get(sid)
                    if _t0 is None:
                        _gone[sid] = _now           # 首次观测到消失，开始计时
                    elif (_now - _t0) >= _grace:
                        del seq_map[sid]            # 消失超过宽限 → 真清
                        del _gone[sid]
                # 2) 给新出现的 buff 分配 seq（_buff_next_seq 单调递增；已删的旧 seq 自然留下空洞但不影响排序）
                for sid, _info, _attr in items:
                    if sid not in seq_map:
                        seq_map[sid] = self._buff_next_seq  # V2094: 同上 self
                        self._buff_next_seq += 1
                items.sort(key=lambda t: (seq_map.get(t[0], 0), t[0]))
            else:
                # 防御性回退：仍按 sid
                items.sort(key=lambda t: t[0])
        else:
            items.sort(key=lambda t: t[0])

        # V2084：清理本帧消失的 sid（重置首次观测时间，下次再出现时重新计时）
        # V2088 BUGFIX：必须用**原始数据源** buffs 的 sid 集合，不能用过滤后的 items！
        #   用 items 的后果：某 buff 因「其他门限」（minrem/mininit/nan/ex_*）被丢 → 不在 items
        #   → 本帧把它从 _seen 删掉 → 下一帧变 _was_new=True → 又过 minappear → 又被其他门限丢
        #   → 每帧都在「新 → 丢 → 新 → 丢」震荡 → 全 Buff 模块疯狂闪烁。
        #   正确语义：只有「游戏里这个 buff 真的没了（原始 buffs 里读不到了）」才重置计时。
        _raw_sids = set(sid for sid, _ in buffs)
        for sid in list(_seen.keys()):
            if sid not in _raw_sids:
                del _seen[sid]
        # V2096：buff 真正从游戏数据里消失时，一并清掉「出现过」记忆，
        # 下次再出现会重新计时（重新出现即 _was_new → 再次立即放行）。
        for sid in list(_ever_shown):
            if sid not in _raw_sids:
                _ever_shown.discard(sid)

        # ── 固定布局：rows 行 × per_row 列（V2104）──
        # 模块尺寸固定（rows × per_row），不再随 buff 数量伸缩。
        # 排序规则（简化）：所有 Buff 在前（保持各自原有排序），所有 Debuff 接在 Buff 之后（不再单独分行）；
        # 总容量 = per_row × rows，超出直接截断丢弃。
        rows = max(1, int(self.settings.get("boss_rows", 3)))
        normal_items = [t for t in items if not _is_debuff(int(t[0]))]
        debuff_items = [t for t in items if _is_debuff(int(t[0]))]
        combined = (normal_items + debuff_items)[: per_row * rows]
        placed = [(idx, t) for idx, t in enumerate(combined)]

        # 名称字段（按语言）
        if lang == "en":
            name_key = "英文名"
        elif lang == "zh_tw":
            name_key = "繁中名"
        elif lang == "ja":
            name_key = "日文名"
        else:
            name_key = "名称"

        # ── 绘制固定网格 ──
        # V2226：行内水平对齐（靠左 / 居中 / 靠右，默认靠左）——按「每行实际卡片数」算该行偏移，
        # 只有最后一行（不足 per_row 个）才会看出差异，满行时三种对齐完全等价。
        _align_cfg = str(self.settings.get("boss_row_align", "left"))
        _avail_w = per_row * bw + max(0, per_row - 1) * card_sp
        for slot, (sid, info, attr) in placed:
            row = slot // per_row
            col = slot % per_row
            if _align_cfg == "left":
                _row_off = 0.0
            else:
                _row_n = min(per_row, len(placed) - row * per_row)
                _row_w = _row_n * bw + max(0, _row_n - 1) * card_sp
                _row_off = (_avail_w - _row_w) / 2.0 if _align_cfg == "center" else (_avail_w - _row_w)
            x = _row_off + col * (bw + card_sp)
            y = row * (bh + row_sp)
            is_debuff = _is_debuff(int(sid))
            # 接近尾声判定（rem/init 低于阈值）
            infinite = bool(info.get("infinite"))
            if infinite:
                is_low = False
            else:
                _rem = float(info.get("remaining", 0.0) or 0.0)
                _init = float(info.get("initial", 0.0) or 0.0)
                ratio = (_rem / _init) if _init > 0 else 0.0
                is_low = ratio < warn_thr
            self._draw_boss_card(
                painter, x, y, bw, bh, info, attr, name_key,
                name_fs, stacks_fs, time_fs, bar_w, bar_h,
                name_col, stacks_col, time_col, bar_col, backing_col,
                elem_sp, bar_frame_t,
                is_debuff, is_low, warn_en, warn_col,
                debuff_name_col, debuff_stacks_col, debuff_time_col, debuff_bar_col,
                debuff_warn_en, debuff_warn_col,
            )

        # ── 固定窗口尺寸（3 行 × per_row 列，含行/列间隙）── V2103
        self._apply_boss_fixed_size()

    def _apply_boss_fixed_size(self):
        """V2104：固定 Boss Buff 窗口尺寸（rows 行 × per_row 列，含行/列间隙），不随 buff 数量伸缩。
        即使无角色/无活动 Buff 也预留 rows × per_row 的固定区域。rows 取自 boss_rows（可调）。"""
        win = getattr(self, "boss_win", None)
        if win is None:
            return
        per_row = max(1, int(self.settings.get("boss_per_row", 10)))
        rows = max(1, int(self.settings.get("boss_rows", 3)))
        row_sp = int(self.settings.get("boss_row_spacing", 4))
        card_sp = int(self.settings.get("boss_card_spacing", 4))
        bw_setting = max(1, int(self.settings.get("boss_backing_width", 80)))
        bh_setting = max(1, int(self.settings.get("boss_backing_height", 64)))
        name_fs = max(1, int(self.settings.get("boss_name_font_size", 11)))
        stacks_fs = max(1, int(self.settings.get("boss_stacks_font_size", 10)))
        time_fs = max(1, int(self.settings.get("boss_time_font_size", 10)))
        bar_w = max(1, int(self.settings.get("boss_bar_width", 60)))
        bar_h = max(1, int(self.settings.get("boss_bar_height", 5)))
        bar_frame_t = max(0, min(10, int(self.settings.get("boss_bar_frame_thickness", 2))))
        elem_sp = int(self.settings.get("boss_element_spacing", 4))
        row_h_extra = int(self.settings.get("boss_row_height_extra", 0))
        from PySide6.QtGui import QFont as _QF, QFontMetrics as _QFM
        _afm_name = _QFM(_QF("Segoe UI", name_fs, _QF.Bold))
        _afm_stacks = _QFM(_QF("Segoe UI", stacks_fs, _QF.Bold))
        _afm_time = _QFM(_QF("Segoe UI", time_fs, _QF.Bold))
        _name_h = _afm_name.height() + 2 + row_h_extra
        _stacks_h = _afm_stacks.height() + 2 + row_h_extra
        _time_h = _afm_time.height() + 2 + row_h_extra
        pad = 2
        # V2209：融合后时间文本与进度条共用一行，行高取二者较大值（真实省掉一行）
        _fused_h = max(_time_h, (bar_h + 2 * bar_frame_t))
        auto_bh = (2 * pad + _name_h + elem_sp + _stacks_h + elem_sp + _fused_h)
        auto_bh = max(1, auto_bh)
        auto_bw = bar_w + 2 * bar_frame_t + 8
        bh = max(auto_bh, bh_setting)
        bw = max(auto_bw, bw_setting)
        actual_cw = per_row * bw + max(0, per_row - 1) * card_sp
        actual_ch = rows * bh + max(0, rows - 1) * row_sp
        self.boss_canvas_w = actual_cw
        self.boss_canvas_h = actual_ch
        new_w = max(1, int(actual_cw * win.disp_w))
        new_h = max(1, int(actual_ch * win.disp_h))
        if abs(new_w - win.width()) > 1.5 or abs(new_h - win.height()) > 1.5:
            win.resize(new_w, new_h)

    def _draw_boss_card(self, painter, x, y, bw, bh, info, attr, name_key,                           name_fs, stacks_fs, time_fs, bar_w, bar_h,
                           name_col, stacks_col, time_col, bar_col, backing_col,
                           elem_sp, bar_frame_t,
                           is_debuff, is_low, warn_en, warn_col,
                           debuff_name_col, debuff_stacks_col, debuff_time_col, debuff_bar_col,
                           debuff_warn_en, debuff_warn_col):
        """绘制单张轻量卡片：衬底 + 名称 + 层数/最大层 + 剩余/持续 + 倒计时横条（含 100% 外框）。"""
        painter.save()
        # 衬底（三处文字共用一套样式）
        painter.setPen(Qt.NoPen)
        painter.setBrush(backing_col)
        painter.drawRoundedRect(x, y, bw, bh, 3, 3)

        pad = 2
        cx = x + bw / 2.0

        # ── 颜色：根据 is_debuff / is_low 切换 ──
        if is_debuff:
            cur_name_col   = debuff_name_col
            cur_stacks_col = debuff_stacks_col
            cur_time_col   = debuff_time_col
            cur_bar_col    = debuff_bar_col
            if is_low and debuff_warn_en:
                cur_time_col = debuff_warn_col
                cur_bar_col  = debuff_warn_col
        else:
            cur_name_col   = name_col
            cur_stacks_col = stacks_col
            cur_time_col   = time_col
            cur_bar_col    = bar_col
            if is_low and warn_en:
                cur_time_col = warn_col
                cur_bar_col  = warn_col

        # 名称（顶部，V2064 自适应阶梯：name_fs → 10 → 9 → 8 → ElideRight）
        name = (attr.get(name_key) or "").strip()
        # V2217：移除名称右侧的 ∞ 永续符号——剩余/持续时间条里已显示 ∞（见下方时间区），
        # 名称处不再重复，避免长名被 ∞ 挤占宽度导致阶梯缩字/省略号截断。
        _name_disp = name
        # V2064：阶梯缩字——优先用玩家设置的 name_fs；超出 bw-4 时降到 10pt 重测，再降到 9pt、8pt，
        # 最后仍超才用 ElideRight(...)。这样长名（5+ 中文）能完整显示而不被省略号截断。
        # V2076 修复：玩家设的 name_fs 优先。
        # V2078 修复：阶梯改为"只缩不升"——玩家设 1pt 直接用 1pt（不再升到 8，玩家自负看不清楚）；
        # 玩家设 11pt 装不下才降到 10/9/8 找最大能装下的（防溢出）。
        # 之前的"只升不降"阶梯会让 render 端算的 _name_h 与 _draw_boss_card 实际 name_h 不一致——
        # render 端用 name_fs=1 算小高度，_draw_boss_card 用阶梯升到 8 算大高度，
        # 实际 _content_h > render 估算 → 外框底部超出 bh → 进度条被切。
        cur_name_fs = max(1, int(name_fs))
        cur_name = name
        # 阶梯降字号（不升）——从玩家设的值开始试，装不下就降到下一档（仅往下）
        _shrink_steps = sorted(set([cur_name_fs, 10, 9, 8]), reverse=True)
        _found = False
        for fs in _shrink_steps:
            if fs > cur_name_fs:
                continue  # V2078: 跳过比玩家设的还大的字号（不放大）
            fs = max(1, fs)
            _f = QFont("Segoe UI", fs, QFont.Bold)
            _fm = QFontMetrics(_f)
            _w = _fm.horizontalAdvance(_name_disp)  # V2095: 含 ∞ 一起测宽
            if _w <= max(1, bw - 4):
                cur_name_fs = fs
                cur_name = _name_disp  # V2095: 含 ∞
                _found = True
                break
        if not _found:
            # 都装不下（玩家设的字号本来就大，且 buff 名特别长），用 8pt 兜底 + elide
            cur_name_fs = min(8, max(1, int(name_fs)))
            _f = QFont("Segoe UI", cur_name_fs, QFont.Bold)
            _fm = QFontMetrics(_f)
            cur_name = _fm.elidedText(_name_disp, Qt.ElideRight, max(1, bw - 4))  # V2095
        f = QFont("Segoe UI", cur_name_fs, QFont.Bold)
        painter.setFont(f)
        painter.setPen(cur_name_col)
        fm = QFontMetrics(f)
        if fm.horizontalAdvance(cur_name) > max(1, bw - 4):
            cur_name = fm.elidedText(cur_name, Qt.ElideRight, max(1, bw - 4))
        # V2073: 用 fm.height()+2 替代 cur_name_fs+2，确保 QRect 容纳完整粗体字体
        # V2074: 在 fm.height()+2 基础上再加 row_h_extra（用户可调，默认 0，V2075 起允许负值）
        # V2075: QRect 高度 clamp >=1 防止负高度
        # V2076: 元素在衬底内水平垂直居中——按内容总高算起始 y，让整组元素在衬底里居中
        # V2236 居中复核（综合 V2076/V2078/V2226 既有实现）：
        # 文字——drawText(QRect(x, y, bw, line_h), Qt.AlignHCenter | Qt.AlignVCenter, text)
        # 进度条外框——bar_x = cx - full_w/2（水平居中），by = fy + (_fused_row_h - outer_h)/2（垂直居中于融合行）
        # 时间融合文本——addText(cx - tw/2, baseline_in_centered_rect) + 黑色描边（保证压在条上也清晰）
        # 三者共享同一融合行 _fused_row_h 中心，**严格水平 + 垂直居中于卡片**。
        # 计算顺序：先算各行实际高度，再算内容总高与居中起点，最后用 AlignHCenter|AlignVCenter 绘制
        _row_h_extra = int(self.settings.get("boss_row_height_extra", 0))
        name_h   = max(1, fm.height()  + 2 + _row_h_extra)
        stacks_h = max(1, QFontMetrics(QFont("Segoe UI", stacks_fs, QFont.Bold)).height() + 2 + _row_h_extra)
        time_h   = max(1, QFontMetrics(QFont("Segoe UI", time_fs,   QFont.Bold)).height() + 2 + _row_h_extra)
        _outer_h = bar_h + 2 * bar_frame_t
        # V2209：倒计时文本与进度条融合为同一行（文本浮在条上方），卡片由 4 行压成 3 行
        _content_h = name_h + elem_sp + stacks_h + elem_sp + max(time_h, _outer_h)
        _content_top = y + max(pad, (bh - _content_h) / 2)  # 上下 pad 自然对称；bh 不够时退化为 pad
        # 名称
        ny = _content_top
        painter.drawText(QRect(x, ny, bw, name_h), Qt.AlignHCenter | Qt.AlignVCenter, cur_name)

        # 层数 / 最大层（中部；单层显示 1/1）
        if attr.get("单层"):
            stacks_str = "1/1"
        else:
            st = int(info.get("stacks", 0) or 0)
            mx = int(info.get("max_stacks", 0) or 1)
            if mx <= 0:
                mx = 1
            stacks_str = f"{st}/{mx}"
        sy = ny + name_h + elem_sp
        f2 = QFont("Segoe UI", stacks_fs, QFont.Bold)
        painter.setFont(f2)
        painter.setPen(cur_stacks_col)
        # V2074：加 row_h_extra
        # V2076：用 AlignVCenter 在自己 QRect 内垂直居中（配合 _content_top 整体居中）
        painter.drawText(QRect(x, sy, bw, stacks_h), Qt.AlignHCenter | Qt.AlignVCenter, stacks_str)

        # V2209：倒计时文本与进度条融合为同一行——进度条照常绘制，倒计时文本居中浮在进度条上方，
        # 卡片从「名称 / 层数 / 时间 / 进度条」四行压缩为三行，省掉一整行的垂直空间。
        # 剩余 / 持续（时间区；警告色切换）
        # V2098：时间区始终显示最真实读到的 remaining/initial，绝不用 ∞ 替代。
        # 永续标志 ∞ 只出现在名称右侧（见上文 _name_disp），此处一律显示真实读值。
        # V2215：FLT_MAX（≈3.4e38）在游戏里表示「永续 / 无时限」，
        # 直接按 f"{rem:.1f}" 打印会变成 340282346638528860000000000000000000000.0 这种天文数字撑爆卡片，
        # 这里统一显示成 ∞。
        # V2216：玩家可在 UI 上区分「真永续」和「值过大自动判为永续」——
        #   · infinite=True（游戏自身声明的永续）→ 纯 "∞"；
        #   · infinite=False 但 remaining/initial ≥ 9999（值过大自动判定）→ "*∞"（前缀星号表示非游戏原声明）。
        # 其余情况照旧显示真实读值。
        infinite = bool(info.get("infinite"))  # V2216：本地重读一次，规避上方 infinite 变量被 refactor 移走的风险
        rem = float(info.get("remaining", 0.0) or 0.0)
        init = float(info.get("initial", 0.0) or 0.0)
        if infinite or rem >= 9999 or init >= 9999:
            time_str = "∞" if infinite else "*∞"
        else:
            time_str = f"{self._fmt_dur(rem)}/{self._fmt_dur(init)}"
        f3 = QFont("Segoe UI", time_fs, QFont.Bold)
        painter.setFont(f3)
        # V2073：同 stacks 用 fm3.height()+2
        # V2074：加 row_h_extra
        fm3 = QFontMetrics(f3)
        # 融合行：起点 = 原「时间行」位置；行高 = max(时间文字高, 进度条外框高)
        fy = sy + stacks_h + elem_sp
        # V2078 防御（融合版）：内容总高超出衬底 bh 时，把进度条外框 clamp 进剩余空间
        _actual_content_h = name_h + elem_sp + stacks_h + elem_sp + max(time_h, _outer_h)
        if _actual_content_h + 2 * pad > bh:
            _avail_for_outer = max(1, (bh - 2 * pad) - (name_h + elem_sp + stacks_h + elem_sp))
            if _avail_for_outer < _outer_h:
                _outer_h = max(1, _avail_for_outer)  # 进度条外框高度 clamp 到剩余可用空间
        if infinite:
            ratio = 1.0
        else:
            init = float(info.get("initial", 0.0) or 0.0)
            rem = float(info.get("remaining", 0.0) or 0.0)
            ratio = (rem / init) if init > 0 else 0.0
            ratio = max(0.0, min(1.0, ratio))
        full_w = min(bar_w, bw - 4)
        bar_x = int(round(cx - full_w / 2.0))
        # V2078: outer_h 用 _outer_h（被前面的防御 clamp 过），不再用 bar_h+2*bar_frame_t 重新算
        outer_h = _outer_h
        _fused_row_h = max(time_h, outer_h)
        # 进度条垂直居中于融合行（时间文字随后浮在其上）
        by = fy + max(0, (_fused_row_h - outer_h) / 2.0)
        # 外框：4 条 bar_col 描边
        if bar_frame_t > 0:
            pen = QPen(cur_bar_col)
            pen.setWidth(max(1, bar_frame_t))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            # 上下两边
            painter.drawLine(bar_x, by, bar_x + full_w, by)
            painter.drawLine(bar_x, by + outer_h, bar_x + full_w, by + outer_h)
            # 左右两边
            painter.drawLine(bar_x, by, bar_x, by + outer_h)
            painter.drawLine(bar_x + full_w, by, bar_x + full_w, by + outer_h)
        # 内：track + fill
        inner_x = bar_x + bar_frame_t
        inner_y = by + bar_frame_t
        inner_w = max(0, full_w - 2 * bar_frame_t)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))          # 轨道底
        if inner_w > 0 and bar_h > 0:
            painter.drawRect(inner_x, inner_y, inner_w, bar_h)
            painter.setBrush(cur_bar_col)               # 填充
            painter.drawRect(inner_x, inner_y, int(round(inner_w * ratio)), bar_h)
        # V2209：倒计时文本居中浮在进度条上方；描一层深色边，保证压在进度条上也清晰可读
        _tpath = QPainterPath()
        _tw = fm3.horizontalAdvance(time_str)
        _tpath.addText(cx - _tw / 2.0,
                       fy + (_fused_row_h - fm3.height()) / 2.0 + fm3.ascent(),
                       f3, time_str)
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(_tpath)
        painter.setPen(Qt.NoPen)
        painter.setBrush(cur_time_col)
        painter.drawPath(_tpath)
        painter.restore()

    # V2115：删除 _draw_boss_placeholder 占位提示函数——未检测到角色 / 无活动 Buff 时不再画任何文字，
    # 只保留 _draw_module_backdrop 背景板（已在上方 render_bossbuff 调用过），玩家看到的就是一个空壳。


    def render_roll(self, painter):
        """翻滚模块渲染：图标整体居中于本窗口画布（roll_cx/cy），支持横/竖排与闪光。"""
        # 模块显示开关：未勾选翻滚模块时，整个窗口（含背景框）完全不绘制
        if not bool(self.settings.get("show_roll_module", True)):
            return

        # 先画模块背景：即使 dodge_count=0 或没进游戏，也让窗口可见、可拖动
        self._draw_module_backdrop(painter, self.roll_canvas_w, self.roll_canvas_h, draw_border=True, module_key="roll")

        count = min(max(int(self.dodge_count), 0), self.MAX_DODGES)
        if count <= 0:
            return

        # 翻滚UI不透明度（锁定时不减半；且不随角色是否被识别而改变）
        roll_opacity = max(0, min(100, int(self.settings.get("roll_icon_opacity", DEFAULT_SETTINGS["roll_icon_opacity"])))) / 100.0

        # 闪光进度（0~1，随时间消退）
        flash_progress = 0.0
        if bool(self.settings.get("flash_apply_dodge", False)):
            start = getattr(self, "_dodge_flash", None)
            if start is not None:
                dur = int(self.settings.get("flash_duration_ms", 400))
                elapsed = int(time.time() * 1000) - start
                if elapsed < dur:
                    flash_progress = elapsed / dur
                else:
                    self._dodge_flash = None

        icon = self.dodge_icon_size
        gap = self.ROLL_ICON_GAP
        horizontal = (self.settings.get("roll_orientation", "horizontal") != "vertical")

        painter.save()
        painter.setOpacity(roll_opacity)
        # 第 6/7 次翻滚（count>=6）时，序列里所有图标都变成警告牌（不只是第 6/7 个位置）
        warning_all = count >= 6
        if horizontal:
            group_width = count * icon + (count - 1) * gap if count > 1 else icon
            start_x = self.roll_cx - group_width / 2.0
            base_y = self.roll_cy - icon / 2.0
            for i in range(count):
                x = int(start_x + i * (icon + gap))
                self._draw_dodge_icon_at(painter, x, int(base_y), icon, flash_progress, icon_index=i, force_warning=warning_all)
        else:
            group_height = count * icon + (count - 1) * gap if count > 1 else icon
            start_y = self.roll_cy - group_height / 2.0
            base_x = self.roll_cx - icon / 2.0
            for i in range(count):
                y = int(start_y + i * (icon + gap))
                self._draw_dodge_icon_at(painter, int(base_x), y, icon, flash_progress, icon_index=i, force_warning=warning_all)
        painter.restore()

    def _draw_warning_roll_icon(self, painter, x, y, icon, flash_progress=0.0):
        """绘制警告牌：红边 + 黄底圆角三角，无感叹号。
        形状：圆角三角形（三个角全圆角）；三角形重心始终与 (cx,cy) 重合。
        实现：先画红色外三角，再在其内部以重心为中心画黄色内三角。
        红边宽度由 warning_outline_width 控制：值越大，黄色内三角越小、红色占比越多，
        但外三角大小/重心完全不变，因此拉大红边占比时图标不会上/下/左/右漂移。
        可调项：warning_size_scale、warning_outline_width、warning_corner_radius、warning_outline_color、warning_fill_color。
        flash_progress：0~1 的闪光进度；>0 时在警告牌之上叠加一层 flash_color 的
                        「警告牌形状（圆角三角）」透明度脉冲闪烁（V2028 新增），外形始终是警告牌。
        """
        sz = int(icon * float(self.settings.get("warning_size_scale", 0.68)))
        if sz < 8:
            return
        cx = x + icon / 2.0
        cy = y + icon / 2.0
        # 让三角形重心与 (cx,cy) 重合：等腰三角形高=sz，重心距底边 sz/3、距顶点 2*sz/3
        apex_y = cy - 2.0 * sz / 3.0
        base_y = cy + sz / 3.0
        left_x = cx - sz / 2.0
        right_x = cx + sz / 2.0
        red_hex = self.settings.get("warning_outline_color", "#e53935")
        yellow_hex = self.settings.get("warning_fill_color", "#ffef00")
        outline_ratio = max(0.0, min(0.9, float(self.settings.get("warning_outline_width", 0.24))))

        # 外三角圆角半径（用户可调 px，但不超过几何安全上限）
        half_ac = math.hypot(sz / 2.0, sz)
        max_r = min(sz * 0.25, half_ac * 0.35)
        outer_corner_r = max(0.0, min(float(self.settings.get("warning_corner_radius", 6)), max_r))

        # 外三角路径（红色）
        outer_path = self._rounded_triangle_path(
            cx, apex_y,
            right_x, base_y,
            left_x, base_y,
            outer_corner_r,
        )

        # 内三角以重心 G=(cx,cy) 为中心缩放 k 倍：k=1 时与外长完全一致；k=0 时消失（全红）。
        # outline_ratio 从 0 到 0.9 对应 k 从 1 到 0.1，红边占比随 outline_ratio 增大而增大。
        k = max(0.05, 1.0 - outline_ratio * 2.0)
        inner_apex_y = cy + (apex_y - cy) * k
        inner_base_y = cy + (base_y - cy) * k
        inner_left_x = cx + (left_x - cx) * k
        inner_right_x = cx + (right_x - cx) * k
        inner_corner_r = outer_corner_r * k

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        # 1) 红色外三角（整个图标外轮廓）
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(red_hex))
        painter.drawPath(outer_path)
        # 2) 黄色内三角（同心缩放）
        inner_path = self._rounded_triangle_path(
            cx, inner_apex_y,
            inner_right_x, inner_base_y,
            inner_left_x, inner_base_y,
            inner_corner_r,
        )
        painter.setBrush(QColor(yellow_hex))
        painter.drawPath(inner_path)

        # ── V2028 警告牌闪光层 ──
        # 在红边黄底三角之上叠加一层 flash_color 的「警告牌形状（圆角三角）」透明度脉冲闪烁。
        # 外形始终是警告牌（圆角三角），绝不用白色方块遮挡原形状；
        # 复用 flash_apply_dodge（开关）/ flash_color（颜色）/ flash_scale（放大脉冲由调用方处理）。
        if flash_progress > 0 and bool(self.settings.get("flash_apply_dodge", False)):
            fc = QColor(self.settings.get("flash_color", "#ffffff"))
            alpha = int((1.0 - flash_progress) * 150)  # 峰值约 150，随时间消退→0
            if alpha > 0:
                fc.setAlpha(alpha)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fc)
                painter.drawPath(outer_path)  # 用外三角路径，确保闪光外形=警告牌
        painter.restore()

    def _rounded_triangle_path(self, apex_x, apex_y, left_x, left_y, right_x, right_y, r):
        """画圆角三角形路径：三个角都用 quadTo（二次贝塞尔曲线）实现圆角过渡。"""
        A = QPointF(apex_x, apex_y)
        B = QPointF(right_x, right_y)
        C = QPointF(left_x, left_y)

        def unit(p):
            l = math.hypot(p.x(), p.y())
            if l <= 0:
                return QPointF(0.0, 0.0)
            return QPointF(p.x() / l, p.y() / l)

        AB_u = unit(B - A)
        AC_u = unit(C - A)
        BA_u = unit(A - B)
        BC_u = unit(C - B)
        CA_u = unit(A - C)
        CB_u = unit(B - C)

        # 每个角从两侧边各偏移 r（圆角起点/终点）
        A1 = A + AB_u * r
        A2 = A + AC_u * r
        B1 = B + BA_u * r
        B2 = B + BC_u * r
        C1 = C + CA_u * r
        C2 = C + CB_u * r

        path = QPainterPath()
        path.moveTo(A1)
        # 顶点 A 圆角（A1 → A2）
        path.quadTo(A, A2)
        # AC 边到 C1
        path.lineTo(C1)
        # 左下角 C 圆角（C1 → C2）
        path.quadTo(C, C2)
        # CB 边到 B2
        path.lineTo(B2)
        # 右下角 B 圆角（B2 → B1）
        path.quadTo(B, B1)
        # BA 边回到 A1（闭合）
        path.lineTo(A1)
        path.closeSubpath()
        return path

    def _get_dodge_solid_img(self, color_hex="#ffffff", source=None, cache_tag=""):
        """缓存图标实心 QPixmap（alpha>128 处填指定色）。

        直接遍历源像素：alpha>128 的位置写入 flash_color，alpha<=128 设透明。
        不用 QBitmap.fromImage/QRegion/QPainterPath 那一套——V303 的方案在某些 Qt 渲染路径下
        会出现 fillPath 后输出空白或边缘锯齿严重，肉眼看不到任何闪光（用户反馈"压根没看到"）。
        直接遍历可靠得多，100x100 图标首帧 1 万次像素操作一次性缓存，后续帧直接命中。

        V2313：新增 source / cache_tag 两个参数——
          · source    默认 self.shrimp（第 1~5 次翻滚图标）；传入警告图即为第 6/7 次生成实心闪光图。
          · cache_tag 缓存键后缀，防止不同来源的图标在同色下互相串味（普通虾图 ≠ 警告图）。
        因为只认 alpha 通道、不认具体图形，所以**换任何 PNG 闪光都天然适配**，无需额外适配代码。
        """
        norm = (color_hex or "#ffffff").lower()
        if cache_tag:
            norm = norm + "|" + str(cache_tag)
        if norm in self._dodge_solid_cache:
            return self._dodge_solid_cache[norm]
        src_pix = source if source is not None else self.shrimp
        if src_pix is None or src_pix.isNull():
            return None
        src = src_pix.toImage().convertToFormat(QImage.Format_ARGB32)
        w, h = src.width(), src.height()
        if w <= 0 or h <= 0:
            return None
        color = QColor(color_hex)
        r, g, b = color.red(), color.green(), color.blue()
        out = QImage(w, h, QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        for y in range(h):
            for x in range(w):
                sa = src.pixelColor(x, y).alpha()
                if sa > 128:
                    out.setPixelColor(x, y, QColor(r, g, b, 255))
        pm = QPixmap.fromImage(out)
        self._dodge_solid_cache[norm] = pm
        return pm

    # ================================================================
    #  鼠标事件：标题栏拖动 + 图标按钮
    # ================================================================
    # 鼠标事件 / 拖动 / 图标按钮 均在 ModuleWindow / CoreWindow 子类中实现。

    def open_settings(self):
        dlg = getattr(self, "settings_dialog", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        if not self.core_win.isVisible():
            self.core_win.show()
        backup = dict(self.settings)
        try:
            dlg = SettingsDialog(self.core_win, self.settings, ctrl=self)
        except Exception as e:
            QMessageBox.critical(self.core_win, _tr("设置打开失败"), _tr("设置窗口构造异常：\n%s") % e)
            return
        dlg.settings_changed.connect(self._apply_live_settings)
        self.settings_dialog = dlg
        if dlg.exec() == QDialog.Accepted:
            self.settings = dlg.get_settings()
            save_settings(self.settings)
            self._after_settings_changed()
        else:
            self.settings = backup
            save_settings(self.settings)
            self._after_settings_changed()
        self.settings_dialog = None

    def _after_settings_changed(self):
        """设置变化后刷新标题、重新计算布局并刷新三个窗口尺寸/位置。"""
        lang = self.settings.get("language", "zh")
        self.core_win.setWindowTitle(f"{_app_title(lang)} v{APP_VERSION}")
        self.recalc_layout()
        self.load_dodge_icon()
        self._refresh_window_geometries()
        # 全局快捷键组合/开关变化后重新注册
        self._register_all_hotkeys()
        # V2255 BUGFIX（模块 settings 快照永不更新）：5 个模块窗口的 self.settings 是
        # 构造时 `dict(settings)` 的**深拷贝快照**（ModuleWindow.__init__），此前只有
        # _apply_live_settings()（设置面板**实时拖动**路径）会回写它，而「设置对话框关闭」
        # 的 Accepted / Rejected 两条分支都不经过 _apply_live_settings → 模块内的 settings
        # 永远停留在启动时的旧值。
        # 影响最大的是 language：模块内 buff 名（_draw_buff_name → _buff_name(buff, lang)，
        # lang 取自 self.settings["language"]）以及显式传 lang 的 _tr(..., lang) 都读它，
        # 旧值恒为 "zh" → 玩家切成日文后 overlay 上的 buff 名仍是中文，必须重启才生效。
        # 这里无条件回写一次，Accepted / Rejected 两条关闭路径都覆盖到。
        for win in (self.core_win, self.roll_win, self.skill_win, self.allbuff_win, self.boss_win):
            if win is not None:
                win.settings = dict(self.settings)

    def _apply_live_settings(self, new_settings):
        self.settings = dict(new_settings)
        save_settings(self.settings)
        # 实时同步到三个子窗口：它们的 self.settings 是构造时的拷贝，
        # 否则设置面板拖动滑块时窗口内部仍读旧值。
        for win in (self.core_win, self.roll_win, self.skill_win, self.allbuff_win, self.boss_win):
            if win is not None:
                win.settings = dict(new_settings)
        # V2300：整窗显隐统一走仲裁入口（模块开关变化时仍尊重「后台隐藏意图」）
        self._apply_module_visibility()
        self._after_settings_changed()

    # ================================================================
    #  系统托盘
    # ================================================================
    def _setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        # 优先使用自定义图标文件，找不到则回退到蓝色圆形 S
        if os.path.isfile(APP_ICON_PATH):
            self.tray_icon.setIcon(QIcon(APP_ICON_PATH))
        else:
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.transparent)
            p = QPainter(pixmap)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor("#18a4ef"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(3, 3, 26, 26)
            p.setPen(QColor("#ffffff"))
            p.setFont(QFont("Segoe UI", 12, QFont.Bold))
            p.drawText(pixmap.rect(), Qt.AlignCenter, "S")
            p.end()
            self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip(f"{_app_title(self.settings.get('language', 'zh'))} v{APP_VERSION}")

        self.tray_menu = QMenu()
        self.tray_menu.setStyleSheet(
            "QMenu{background:#1a2030;color:#ccccee;border:1px solid #2a3548;padding:4px;}"
            "QMenu::item{padding:4px 20px;}"
            "QMenu::item:selected{background:#2a3548;}"
            "QMenu::separator{height:1px;background:#2a3548;margin:4px 8px;}"
        )
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_menu.aboutToShow.connect(self._update_tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _tray_status_text(self, lang):
        """返回当前状态的三语短文本（不带前缀圆点）。"""
        if self.status == "ok" and (self.char_type or self.charid_hash):
            status_core = self._build_titlebar_status_text(lang)
            if status_core:
                return status_core
        status_map = {
            "no_game": {"zh": "未检测到游戏", "zh_tw": "未偵測到遊戲", "en": "No game"},
            "no_char": {"zh": "未检测到角色", "zh_tw": "未偵測到角色", "en": "No character"},
            "ok": {"zh": "检测正常", "zh_tw": "偵測正常", "en": "Active"},
            "init": {"zh": "初始化中...", "zh_tw": "初始化中...", "en": "Initializing..."},
        }
        return status_map.get(self.status, {}).get(lang, status_map.get(self.status, {}).get("zh", "---"))

    def _update_tray_tooltip(self):
        """实时更新托盘tooltip，与标题栏状态文字同步。"""
        if not hasattr(self, "tray_icon") or self.tray_icon is None:
            return
        lang = self.settings.get("language", "zh")
        status_short = self._tray_status_text(lang)
        self.tray_icon.setToolTip(f"{_app_title(lang)} v{APP_VERSION} - {status_short}")

    def _update_tray_menu(self):
        self.tray_menu.clear()
        lang = self.settings.get("language", "zh")
        status_short = self._tray_status_text(lang)
        status_text = f"● {status_short}"

        self.tray_icon.setToolTip(f"{_app_title(lang)} v{APP_VERSION} - {status_short}")

        status_action = self.tray_menu.addAction(status_text)
        status_action.setEnabled(False)
        self.tray_menu.addSeparator()

        settings_labels = {"zh": "设置...", "zh_tw": "設定...", "en": "Settings..."}
        settings_action = self.tray_menu.addAction(settings_labels.get(lang, settings_labels["zh"]))
        settings_action.triggered.connect(self.open_settings)

        lock_labels = {
            "zh": ("解锁" if self.locked else "锁定"),
            "zh_tw": ("解鎖" if self.locked else "鎖定"),
            "en": ("Unlock" if self.locked else "Lock"),
        }
        lock_action = self.tray_menu.addAction(lock_labels.get(lang, lock_labels["zh"]))
        lock_action.triggered.connect(self._toggle_lock)

        show_all_labels = {"zh": "显示所有窗口", "zh_tw": "顯示所有視窗", "en": "Show All Windows"}
        show_all_action = self.tray_menu.addAction(show_all_labels.get(lang, show_all_labels["zh"]))
        show_all_action.triggered.connect(self._show_all)

        reset_labels = {"zh": "重置所有窗口", "zh_tw": "重置所有視窗", "en": "Reset All Windows"}
        reset_action = self.tray_menu.addAction(reset_labels.get(lang, reset_labels["zh"]))
        reset_action.triggered.connect(self._reset_all_windows)

        self.tray_menu.addSeparator()

        exit_labels = {"zh": "退出", "zh_tw": "退出", "en": "Exit"}
        exit_action = self.tray_menu.addAction(exit_labels.get(lang, exit_labels["zh"]))
        exit_action.triggered.connect(QApplication.quit)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            any_hidden = all(not w.isVisible() for w in self._all_windows())
            if any_hidden:
                self._show_all_windows()
            else:
                self._hide_all_windows()

    def _toggle_lock(self):
        self.locked = not self.locked
        for w in self._all_windows():
            w.update()

    # ================================================================
    #  V2030：移除历史残留的 _open_config_dir 死函数（源码中除自身外零引用，
    #         托盘菜单从未 addAction 注册；i18n.json 的 "打开失败" 键一并清理）。
    # ================================================================

    # ================================================================
    #  主循环
    # ================================================================
    def tick(self):
        try:
            self.scan()
            self._sync_out_of_combat_visibility()
            self._sync_mouse_transparency()
            self._update_tray_tooltip()
            _dump_unknown_buffs()   # V2209：未知 buff 清单定期落盘（内部自带 5 秒节流）
            # 生存兜底：scan_ms 非整数绝不能让定时器停摆，否则会『读一次就卡死』
            try:
                # V2304：调试数据模式下没有 handle，但仍要按 scan_ms 快刷，
                # 否则拖动设置滑块要等 500ms 才见反馈，失去「实时」意义。
                if self.handle or self.settings.get("debug_data_enabled", False):
                    interval = int(self.settings.get("scan_ms", 50))
                else:
                    interval = 500
            except Exception:
                interval = 500
            self.timer.start(interval)
            for w in self._all_windows():
                w.update()
        except Exception:
            # 生存兜底：任何 tick 异常都绝不让定时器停摆，否则会『读一次就卡死』
            try:
                self.timer.start(500)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

    def _sync_mouse_transparency(self):
        """各模块窗口在创建时已设置不穿透（可拖动/点击）；此处统一确保。"""
        for w in self._all_windows():
            w.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def _sync_out_of_combat_visibility(self):
        """根据「非战斗隐藏」设置调整内容区的不透明度与窗口尺寸。

        标题栏（背景+图标+状态文字）始终保留显示，不受隐藏影响。
        仅内容区（buff/技能/翻滚）受隐藏设置影响：
        - 战斗中/训练场/手动常显/有木桩 → 内容区正常（乘数=1），窗口恢复完整高度。
        - 非战斗且（勾选隐藏 或 开启训练场自动）并位于非训练场：
          * 隐藏不透明度=0% → 内容区不绘制，窗口缩到仅标题栏高度（不拦截游戏鼠标）；
            全 Buff 独立窗口整窗 hide()，与 Skill/Roll 共享一个「OOC 全隐」语义；
          * 隐藏不透明度>0% → 内容区半透明，窗口保持完整高度。
        """
        in_combat = getattr(self, "in_combat", True)
        # 非战斗 = 不在副本/任务中 且 不在训练场
        in_training_area = getattr(self, "in_training_area", False)
        ooc_hide = bool(self.settings.get("out_of_combat_hide", False))
        want_hide_content = ooc_hide and not in_combat and not in_training_area
        if want_hide_content:
            opacity_f = max(0.0, min(100, int(self.settings.get("out_of_combat_opacity", 0)))) / 100.0
            self._ooc_content_mult = opacity_f
            content_hidden = opacity_f <= 0.0
        else:
            self._ooc_content_mult = 1.0
            content_hidden = False

        if content_hidden != self._ooc_content_hidden:
            self._ooc_content_hidden = content_hidden
            full_h = self.core_win.window_h
            title_h = max(1, int(self.TITLE_BAR_H * self.core_win.disp_h))
            if content_hidden:
                self.core_win.resize(self.core_win.window_w, title_h)
            else:
                self.core_win.resize(self.core_win.window_w, full_h)
            self.core_win.update()
            # V2101：全 Buff 模块的底框（backdrop）仅由「锁定」决定可见性，与核心/能力模块一致——
            # 非战斗隐藏只隐藏「内容」（render_allbuff 内 early-return 跳过内容），不再整窗 hide，
            # 因此底框在未锁定时始终显示（含非战斗状态）。这里只在「模块开关」维度控制整窗显隐，
            # 模块关闭时整窗隐藏，模块开启时整窗显示（底框随之可见）。
            # V2300：整窗显隐统一走仲裁入口。
            # 旧代码在这里无条件 show() 两个 buff 模块，完全不知道游戏是否在前台——
            # 后台期间只要战斗状态翻一下（或改一下设置），就会把 focus_timer 刚藏好的窗口弹回来。
            self._apply_module_visibility()


    def _game_is_foreground(self):
        """综合判定游戏是否处于『用户正在看的前台』状态。

        返回 True（前台）/ False（后台）。

        V2025 修复（关键）：把工具自身进程 (os.getpid()) 也并入「前台」集合。
        根因：self.pid 存的是【游戏】PID（scan() 里 self.pid = game_pids[0]），
        之前 _game_is_foreground 只认游戏 PID。于是用户点击 / 拖拽 / 缩放 overlay
        自身的模块窗口时，前台窗口变成工具自己的进程（PID 不在游戏集合里），
        被误判成「游戏到后台」→ 整窗隐藏 → 用户根本没法调模块（一点模块就消失）。
        现在前台判定 = 游戏进程 或 工具自身进程 即视为前台（保持可见）；
        真正的「后台」= 前台是两者之外的其它程序（桌面 / 浏览器 / 其它软件）→ 才隐藏。

        V2021 收紧信号：仅用 GetForegroundWindow 的 PID ∈ 集合 这一个最稳信号判断。
        三种模式 (窗口化 / 无边框 / 全屏独占) 下 GetForegroundWindow 都能稳定反映「用户
        当前切到哪个程序」。
        """
        game_pids = self._game_pids or set()
        # V2025：工具自身进程也算前台（点 / 拖 / 缩放模块时保持可见，不被误杀）
        own_pid = os.getpid()
        fg_allowed = game_pids | {own_pid}
        if not fg_allowed:
            self._last_fg = None
            return False
        fg = get_foreground_pid()
        self._last_fg = fg
        # 前台 = 前台窗口属于游戏进程 或 工具自身进程
        return fg in fg_allowed

    def _sync_visibility_with_game_focus(self):
        """随游戏前后台自动显隐（作用于全部三个窗口）。

        行为规则（V2020 重写）：
          - 功能关闭（auto_focus_minimize == False）：本函数不动作，显隐完全由用户手动控制
            （标题栏最小化图标 / 快捷键 / 双击托盘 直接 hide，照旧）。
          - 功能开启：按「游戏是否在前台」做状态同步，且无视当前状态：
              · 前台 + 任一窗口被隐藏 → 强制 _show_all_windows() 弹出；
              · 后台 + 任一窗口可见 → 强制 _hide_all_windows() 整窗消失
                （与标题栏最小化图标完全一致，不再 showMinimized 进任务栏）；
              · 无法判定（None）→ 保留现状，绝不 hide（杜绝 V2019『出不来』灾难）。
            这同时满足两个诉求：切到后台立刻整窗消失；手动隐藏后游戏仍在前台会自动弹回。

        判定见 _game_is_foreground()：GetForegroundWindow.PID 单信号（V2021 起由三态收敛为二态）。
        诊断：每次 tick 把 fg / decision / action 写入
        overlay_focus_log.txt（最近 200 行环形），便于排查前后台识别是否生效。
        """
        # V2023 改动：去掉「非战斗内容隐藏时 early return」的旧 V2013 行为，
        # 让非战斗状态也跟随前后台隐显（hide() 会让整窗含标题栏一起消失），
        # 回前台时由 _show_all_windows() 一次性完整弹出，后续 tick 再按 _ooc_content_mult 恢复缩为标题栏的视觉效果。
        enabled = bool(self.settings.get("auto_focus_minimize", DEFAULT_SETTINGS["auto_focus_minimize"]))
        if not enabled:
            return

        # V2025：用户正在拖拽 / 缩放 overlay 模块时，绝对不触发隐藏（否则一点模块就消失）
        if getattr(self, "_interacting", False):
            return

        # 游戏未运行：不动作，复位边沿状态（新进程接入时不误触发）
        if self.pid is None:
            self._prev_is_game_foreground = None
            self._append_focus_log(action="pid_none")
            return

        # V2316：游戏强退→重进的「窗口一直最小化、需手动唤醒」修复。
        # 根因：强退时 auto_focus_minimize 把窗口整窗藏起（bg_hide），随后 self.pid 变 None
        # 把 _prev_is_game_foreground 复位成 None；游戏重进后 scan() 重连分支会再清成 None
        # 并置 _force_fg_sync=True。若只走下方「prev is None → init_prev 只记录不动作」旧分支，
        # 被藏起的窗口永远不会被重新弹出（除非再发生一次 fg/bg 边沿）。
        # 修复：重连时强制按「当前前台判定」补一次显隐——只强制弹出（fg + 隐藏 → show），
        # 绝不强制隐藏（隐藏由正常 fg/bg 边沿处理），从而既修好「重进后自动恢复显示」，
        # 又完全不改变干净启动 / 后台初始态行为（干净启动时窗口本就可见，force-show 为 no-op）。
        if getattr(self, "_force_fg_sync", False):
            self._force_fg_sync = False
            decision = self._game_is_foreground()
            any_visible = any(w.isVisible() for w in self._all_windows())
            action = "none"
            if decision and not any_visible:
                self._show_all_windows()
                action = "reconnect_fg_show"
            self._prev_is_game_foreground = decision
            self._append_focus_log(prev=None, fg=getattr(self, "_last_fg", None),
                                   is_game_fg=decision, action=action)
            return

        # V2021：单信号判定（GetForegroundWindow.PID ∈ game_pids）。三态→二态，
        # 杜绝"V2020 偶发 None → 永不 hide"的情况。
        decision = self._game_is_foreground()

        any_visible = any(w.isVisible() for w in self._all_windows())
        prev = self._prev_is_game_foreground
        action = "none"

        # V2023 改动：去掉 V2022 引入的 600ms 防抖（用户实测说"战斗中前后台确实可以"
        # 但防抖让窗口出不来，节奏太慢反而变卡）。回到 V2021 的"边沿触发立即动作"节奏。
        # 同时也不再 early-return _ooc_content_hidden（让非战斗状态也跟随前后台隐显）。
        action = "none"

        if prev is None:
            # 首拍：仅记录 prev、不主动切换（让用户手动 ctrl+h 切或按当前状态自然显示）
            self._prev_is_game_foreground = decision
            self._append_focus_log(prev=prev, fg=getattr(self, "_last_fg", None),
                                   is_game_fg=decision, action="init_prev")
            return

        if decision == prev:
            # 无边沿（与上一拍一致），仅做诊断日志、不动作
            self._append_focus_log(prev=prev, fg=getattr(self, "_last_fg", None),
                                   is_game_fg=decision, action="none")
            return

        # 边沿变化：立刻切换（V2023 移除 600ms 防抖）
        if decision:
            if not any_visible:
                # 游戏在前台但窗口被隐藏 → 无视当前状态强制弹出
                self._show_all_windows()
                action = "fg_show"
        else:
            if any_visible:
                # 游戏在后台但窗口可见 → 强制整窗消失
                self._hide_all_windows()
                action = "bg_hide"
        self._prev_is_game_foreground = decision
        self._append_focus_log(prev=prev, fg=getattr(self, "_last_fg", None),
                               is_game_fg=decision, action=action)

    def _append_focus_log(self, prev=None, fg=None, is_game_fg=None, action="none"):
        """V2019 诊断：把每次焦点定时器的状态追加到 overlay_focus_log.txt，最多 200 行环形。

        让用户能直观确认：当前前台窗口 PID（GetForegroundWindow）与 self._game_pids / self.pid 的关系，
        以及状态同步是否真的触发 fg_show / bg_hide。仅当 self._focus_log_path 已初始化才写文件，
        且只在「状态真的变化」或「有动作」时写，无变化时每 16 拍（约 4 秒）写一次，避免日志刷屏。
        """
        path = self._focus_log_path
        if not path:
            return
        # 仅在状态真正变化 / 触发动作 / 每 16 次（约 4 秒）记录一次，避免日志刷屏
        last = self._focus_log_ring[-1] if self._focus_log_ring else None
        sig = (prev, fg, is_game_fg, action)
        if last is not None and last["sig"] == sig and action == "none":
            self._focus_log_skip = getattr(self, "_focus_log_skip", 0) + 1
            if self._focus_log_skip < 16:
                return
            self._focus_log_skip = 0
        else:
            self._focus_log_skip = 0
        import time as _t
        entry = {
            "ts": _t.strftime("%H:%M:%S"),
            "ms": int(_t.monotonic() * 1000),
            "sig": sig,
            "prev": prev,
            "fg": fg,
            "game_pids": sorted(self._game_pids) if self._game_pids else [],
            "self_pid": self.pid,
            "is_game_fg": is_game_fg,
            "action": action,
        }
        self._focus_log_ring.append(entry)
        if len(self._focus_log_ring) > 200:
            self._focus_log_ring = self._focus_log_ring[-200:]
        if ENABLE_FOCUS_LOG:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("# overlay focus diagnostic log (V2020) — last 200 entries, newest at bottom\n")
                    f.write("# ts | prev | fg(GetForeground PID) | game_pids | self_pid | decision | action\n")
                    for e in self._focus_log_ring:
                        f.write("{ts} | prev={prev} | fg={fg} | game_pids={gp} | self_pid={sp} | decision={dec} | action={act}\n".format(
                            ts=e["ts"], prev=e["prev"], fg=e["fg"],
                            gp=e["game_pids"], sp=e["self_pid"],
                            dec=e["is_game_fg"], act=e["action"]))
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

    # ── V2304：调试数据注入 ───────────────────────────────────────────────
    def _inject_debug_data(self):
        """V2304：不开游戏也能测 UI。按「调试数据」选项卡的参数合成假数据，
        直接写进 scan() 正常会填的那些状态属性，其余读游戏内存的逻辑全部跳过。

        覆盖的五个模块：
          核心检测（active_buffs）/ 全 Buff（all_buffs_filtered）/ Boss（boss_buffs_filtered）
          / 能力冷却（skill_cd_data）/ 翻滚（dodge_count）
        文本统一走 `_DEBUG_ATTR`，让 `_attr_for_sid` 与 `_skill_name` 都返回同一个调试文本。
        """
        st = self.settings
        text = str(st.get("debug_text", "测试带编码") or "测试带编码")
        cd = float(st.get("debug_countdown", 8.88))
        single = bool(st.get("debug_core_single_layer", False))

        # 名称覆盖：全 Buff / Boss / 技能名三处统一显示调试文本
        _DEBUG_ATTR["active"] = True
        _DEBUG_ATTR["text"] = text
        _DEBUG_ATTR["single"] = single

        # ── 基础状态：伪装成「已进游戏、已识别角色、战斗中」 ──────────────
        self.status = str(st.get("debug_status", "ok") or "ok")
        self.char_type = 0x1FD
        self.charid_hash = 0
        self.pl_id = "PL0000"
        self.in_combat = bool(st.get("debug_in_combat", True))
        self.in_training_area = False
        m = str(st.get("debug_mastery", "") or "")
        self.current_mastery = m if m in ("awakening", "truth", "secret") else None

        # ── 核心检测模块：按数量生成 buff 字典（字段与 read_overlay_data 完全一致）──
        n_core = max(0, min(24, int(st.get("debug_core_buff_count", 3))))
        mx = max(1, int(st.get("debug_core_max_stacks", 8)))
        if bool(st.get("debug_core_full_stacks", True)):
            stk = mx
        else:
            stk = max(0, min(mx, int(st.get("debug_core_stacks", 1))))
        core = []
        for i in range(n_core):
            core.append({
                "index": i,
                "zh": text, "zh_tw": text, "en": text, "ja": text,
                "stacks": 0 if single else stk,
                "max_stacks": mx,
                "timer": cd,
                "timer_max": max(cd, 1.0),
                "timer_display": "any_stack",
                "single_layer": single,
                "awakening": bool(st.get("debug_core_awakening", False)),
                "truth": bool(st.get("debug_core_truth", False)),
                "secret": bool(st.get("debug_core_secret", False)),
                "group": None,
            })
        self.active_buffs = core
        self.all_buffs = list(core)

        # ── 全 Buff / Boss 模块：(sid, info) 元组列表，字段同 read_exstatus_buffs ──
        # V2309：调试注入「各类别数量」——替代原单一「卡片数量」+「是否永续」，
        # 直接控制每类假 buff 个数，方便离线调试呈现更多可能性（普通/Debuff/永续/尾声 都能看到）。
        # 渲染端既定分类逻辑：debuff = _is_debuff(sid) 命中；永续 = infinite=True；
        # 尾声 = 非永续且 remaining/initial < 倒计时尾声警告阈值 warn_thr。
        # 调试态 _attr_for_sid 返回的统一覆盖 dict 把「是否debuff」写成 False，故 _is_debuff 对调试 sid
        # 恒返回 False——这里改用 _DEBUG_DEBUFF_SIDS 显式登记 debuff 的 sid，让调试态也能正确分出 debuff。
        _DEBUG_DEBUFF_SIDS.clear()
        def _mk_mix(normal, debuff, perma, coda, stacks, max_stacks, cd, base):
            out = []
            _ini = max(cd, 1.0)
            # 普通：非 debuff、非永续、剩余充足（ratio≈1 ≥ warn_thr）
            for i in range(normal):
                sid = base + 0x100 + i
                out.append((sid, {"sid": sid, "sub_id": 1, "stacks": max(1, int(stacks)),
                    "max_stacks": max(1, int(max_stacks)), "remaining": cd, "initial": _ini, "infinite": False}))
            # Debuff：sid 写入 _DEBUG_DEBUFF_SIDS，渲染端 _is_debuff 命中
            for i in range(debuff):
                sid = base + 0xD000 + i
                _DEBUG_DEBUFF_SIDS.add(sid)
                out.append((sid, {"sid": sid, "sub_id": 1, "stacks": max(1, int(stacks)),
                    "max_stacks": max(1, int(max_stacks)), "remaining": cd, "initial": _ini, "infinite": False}))
            # 永续：infinite=True
            for i in range(perma):
                sid = base + 0x200 + i
                out.append((sid, {"sid": sid, "sub_id": 1, "stacks": max(1, int(stacks)),
                    "max_stacks": max(1, int(max_stacks)), "remaining": cd, "initial": _ini, "infinite": True}))
            # 尾声：非永续、剩余/初始 明显 < warn_thr（取 0.05，默认 warn_thr=0.2 必然命中）
            for i in range(coda):
                sid = base + 0x300 + i
                out.append((sid, {"sid": sid, "sub_id": 1, "stacks": max(1, int(stacks)),
                    "max_stacks": max(1, int(max_stacks)), "remaining": _ini * 0.05, "initial": _ini, "infinite": False}))
            return out

        self.all_buffs_filtered = _mk_mix(
            max(0, min(60, int(st.get("debug_allbuff_normal", 8)))),
            max(0, min(60, int(st.get("debug_allbuff_debuff", 2)))),
            max(0, min(60, int(st.get("debug_allbuff_perma", 1)))),
            max(0, min(60, int(st.get("debug_allbuff_coda", 1)))),
            st.get("debug_allbuff_stacks", 8), st.get("debug_allbuff_max_stacks", 8), cd, 0)
        self.boss_buffs_filtered = _mk_mix(
            max(0, min(60, int(st.get("debug_boss_normal", 5)))),
            max(0, min(60, int(st.get("debug_boss_debuff", 1)))),
            max(0, min(60, int(st.get("debug_boss_perma", 1)))),
            max(0, min(60, int(st.get("debug_boss_coda", 1)))),
            st.get("debug_boss_stacks", 8), st.get("debug_boss_max_stacks", 8), cd, 0)
        # V2304 关键：render_bossbuff 第一道闸是 `has_char = bool(self.boss_actor)`，
        # boss_actor 为空就直接 return（只剩底框、一个 buff 都不画）。调试模式必须给个假指针，
        # 否则「Boss 张数」怎么调都看不到东西。boss_name 一并给，名称行才有内容。
        self.boss_actor = 0xD0550000          # 假 actor 指针，仅用于通过 has_char 闸
        self.boss_name = text

        # ── 能力冷却模块：4 槽位，前 N 个就绪、其余处于倒计时 ──────────────
        n_sk = max(0, min(4, int(st.get("debug_skill_count", 4))))
        n_ready = max(0, min(4, int(st.get("debug_skill_ready_count", 1))))
        cd_max = max(0.1, float(st.get("debug_skill_cd_max", 30.0)))
        skills = []
        for i in range(n_sk):
            rdy = i < n_ready
            skills.append({
                "slot": i,
                "ability_hash": 0xD0000001 + i,  # 非 0：让 _skill_name 走调试名覆盖分支
                "cd": 0.0 if rdy else cd,
                "ready": rdy,
                "cd_max": cd_max,
            })
        self.skill_cd_data = skills

        # ── 翻滚模块 ──────────────────────────────────────────────────────
        self.dodge_count = max(0, min(self.MAX_DODGES, int(st.get("debug_dodge_count", self.MAX_DODGES))))

    def scan(self):
        # V2304：调试数据模式——完全绕开游戏进程读取，直接把假数据灌进各模块状态属性。
        # 放在函数最顶部 return，保证不碰 find_game_pids / open_proc / 任何 read_*，
        # 因此不开游戏也能实时预览五个模块的排版、字号、换行、颜色与 3D 效果。
        if self.settings.get("debug_data_enabled", False):
            self._inject_debug_data()
            return
        if _DEBUG_ATTR.get("active"):
            # 刚从调试模式切回正常模式：清掉名称覆盖，避免真实 buff 名被「测试带编码」顶掉
            _DEBUG_ATTR["active"] = False
            _DEBUG_DEBUFF_SIDS.clear()  # V2309：同步清空调试 debuff 标记，恢复正常游戏的 debuff 判定
        # V2018：先把所有同名游戏进程 PID 都收进来，供「游戏是否在前台」判断使用。
        # 这里不能再用 find_pid() 单值接口，因为多进程场景下 attach 用的 handle
        # 只对应 self.pid，但前台窗口可能在另一个同名的子进程下。
        game_pids = find_game_pids()
        self._game_pids = set(game_pids)
        pid = game_pids[0] if game_pids else None
        if pid is None:
            self.close_handle()
            self.status = "no_game"
            return
        if self.handle is None or self.pid != pid:
            self.pid = pid
            # 新游戏进程接入：清除上一局的边沿状态，让焦点同步从干净状态重新检测
            # （先开工具调设置、再启动游戏时，旧的边沿记忆不会残留，避免误触发）
            self._prev_is_game_foreground = None
            # V2316：标记「需要强制补一次前后台同步」。否则强退→重进后，被 auto_focus_minimize
            # 整窗藏起的窗口不会自动弹出（prev 被重置成 None，旧 init 分支只记录不动作）。
            self._force_fg_sync = True
            # V2316 BUGFIX：游戏重启后强制清空上一局的 quest_mgr（战斗状态判定的数据源）。
            # 旧进程地址在重启后失效；若不清空，下面 `if self.quest_mgr is None` 会跳过重解，
            # 战斗检测读到野指针 → in_combat 误判 False → 开启「非战斗隐藏」时
            # 除翻滚外所有模块内容被隐藏（翻滚故意忽略 OOC，故独善其身）。
            self.quest_mgr = None
            self.handle = open_proc(pid)
            if not self.handle:
                self.status = "no_game"
                return
            self.pptr, self.module_base, self.module_size, _ = resolve_with_cache(
                self.handle, pid
            )
            # 重连进程后清除裸值资源槽的锁定地址（地址已随 ASLR/堆分配改变）
            self._raw_locked_addrs = {}
            self._prev_actor = 0
            # 建专精判定器（用已解析的模块基址/大小，避免重复枚举）
            self.mastery_reader = mastery_reader.MasteryReader.from_existing(
                self.handle, self.module_base or 0, self.module_size or 0)
            self.current_mastery = None
            if self.pptr is None:
                self.status = "no_game"
                self.close_handle()
                return
            # quest_mgr：优先用 player 偏移直接读（pptr + QM_DELTA，零 AOB 扫描）；
            # 仅当该读取失败（如游戏更新导致偏移失效）才回退到 AOB 扫描。
            if self.quest_mgr is None:
                qm, _ = resolve_quest_mgr_via_player(self.handle, self.pptr)
                if qm:
                    self.quest_mgr = qm
                else:
                    mgr, _ = resolve_quest_mgr_with_addr(
                        self.handle, self.module_base, self.module_size or 0x80000000
                    )
                    if mgr:
                        self.quest_mgr = mgr
        duration_max = {
            "kronos_freeze": float(self.settings.get("kronos_freeze_max", 10.0) or 10.0),
            "class_duration": float(self.settings.get("class_duration_max", 0.0) or 0.0),
            "grace_max": float(self.settings.get("grace_max", 0.0) or 0.0),
        }
        # 调用前快照存储值：read_overlay_data 会原地写入 duration_max 同一对象，
        # 学习时必须拿「本帧观察值」比「调用前的存储值」，否则 new_dmax 与 duration_max 是同一对象、自比恒 False。
        prev_dmax = dict(duration_max)
        snap = read_overlay_data(self.handle, self.pptr, raw_locked=self._raw_locked_addrs, duration_max=duration_max)
        self._raw_locked_addrs = snap.get("raw_locked", {})

        # 同步学习到的时间上限（古洛诺斯槽保持 / 团长 Class 倒计时）
        dmax_changed = False

        # 古洛诺斯槽保持（巴萨拉卡）：剩余秒经 actor+0x1CAF0 读取；最大值自我学习（仅向上）。
        new_dmax = snap.get("duration_max", {})
        if new_dmax.get("kronos_freeze") and new_dmax["kronos_freeze"] > prev_dmax["kronos_freeze"]:
            self.settings["kronos_freeze_max"] = new_dmax["kronos_freeze"]
            dmax_changed = True

        # 芙劳「转世的恩宠」倒计时上限：独立学习（仅向上），与古洛诺斯槽学习机制一致，
        # 但上限数值彼此独立——首次上升沿（读数首次跳变到正值）即作为基准，之后仅当读数更高才更新。
        if new_dmax.get("grace_max") and new_dmax["grace_max"] > prev_dmax["grace_max"]:
            self.settings["grace_max"] = new_dmax["grace_max"]
            dmax_changed = True

        # 团长 Class 倒计时（古兰/姬塔）上限：仅自动学习，不再提供手动输入框。
        # 仅在「真正激活那一刻」（上一帧≈0 或首次检测，且当前值明显跳高）把当前值定为上限；
        # 倒计时过程中只降不升，杜绝中途突增值污染上限。
        class_buff = next((b for b in snap.get("buffs", []) if b.get("_class_dur")), None)
        cur_dur = class_buff["timer"] if (class_buff and class_buff.get("timer") is not None) else 0.0
        prev_dur = getattr(self, "_prev_class_dur", None)
        if cur_dur > 0:
            is_activation = (prev_dur is None) or (prev_dur < 1.0 and cur_dur > prev_dur + 3.0)
            if is_activation:
                self.settings["class_duration_max"] = cur_dur
                dmax_changed = True
        self._prev_class_dur = cur_dur

        if dmax_changed:
            save_settings(self.settings)
        # actor 变化日志（用于诊断伊德龙人化等形态切换）
        char_base = read_u64(self.handle, self.pptr + CHAR_PTR_OFF) if self.pptr else 0
        if char_base and char_base != self._prev_actor:
            self._prev_actor = char_base

        # 专精判定：每 tick 读当前主控最高阶专精（awakening/truth/secret/None）。
        # None=未判定（游戏未运行/CharaPower 未命中/角色未加载），调用方应视为常显。
        try:
            if self.mastery_reader and char_base and snap.get("status") == "ok":
                self.current_mastery = self.mastery_reader.read_top_mastery(char_base)
            else:
                self.current_mastery = None
        except Exception:
            self.current_mastery = None
        self.status = snap["status"]
        self.dodge_count = snap["dodge"] or 0
        # 翻滚图标闪光：可用翻滚次数增加时触发（勾边发光）
        if bool(self.settings.get("flash_apply_dodge", False)):
            if self.dodge_count > getattr(self, "_prev_dodge_count", 0):
                self._dodge_flash = int(time.time() * 1000)
        self._prev_dodge_count = self.dodge_count
        self.char_type = snap.get("char_type", 0)
        self.charid_hash = snap.get("charid_hash", 0)
        self.pl_id = snap.get("pl_id") or _pl_hash_map.get(self.charid_hash)
        self.all_buffs_filtered = snap.get("all_buffs_list", [])  # V2108：全 Buff 模块数据源（保留重复 sid；含所有槽位）

        # V2200：Boss Buff 模块数据源。独立定位 boss actor（实体表）后读其 ExStatus。
        # 与主控角色完全解耦：主控角色的读取失败（如 no_game / no_char）不影响本模块；
        # 反过来 boss 不在场时也只是列表为空，不动摇其余模块。
        # read_boss_buffs 内部带 1.5s 的 actor 缓存，tick 频率下不会拖慢主循环。
        try:
            if self.handle and self.module_base:
                _b_res, _b_list, _b_actor, _b_name = read_boss_buffs(self.handle, self.module_base)
                self.boss_actor = _b_actor
                self.boss_name = _b_name
                self.boss_buffs_filtered = _b_list or []
            else:
                self.boss_actor = None
                self.boss_name = None
                self.boss_buffs_filtered = []
        except Exception:
            self.boss_actor = None
            self.boss_name = None
            self.boss_buffs_filtered = []

        # 按专精门控过滤 + 按顺位（buff_order）升序排列
        # 三框全选=常显；全不选=常关；单选/多选=仅当 current_mastery 命中选中项才显示
        # current_mastery=None（未判定）时降级为“有勾选即显示”，避免检测失败致全黑。
        buff_order = self.settings.get("buff_order", {})
        buff_mastery = self.settings.get("buff_mastery", {})
        all_buffs = snap.get("buffs", [])
        cur = self.current_mastery
        self.active_buffs = []

        def _bkey(idx, group=None):
            if group == "GENERAL":
                return f"GENERAL_{idx}"
            pl = self.pl_id
            if not pl and self.char_type in CHAR_TYPE_TO_PL:
                pl = CHAR_TYPE_TO_PL[self.char_type]
            return f"{pl}_{idx}" if pl else f"{self.char_type:#04x}_{idx}"

        _ordered = []
        for buff in all_buffs:
            idx = buff['index']
            bkey = _bkey(idx, buff.get("group"))
            chk = buff_mastery.get(bkey)
            if chk is None:
                chk = {"awakening": buff.get("awakening", False),
                       "truth": buff.get("truth", False),
                       "secret": buff.get("secret", False)}
            aw = chk.get("awakening", False)
            tr = chk.get("truth", False)
            se = chk.get("secret", False)
            if not (aw or tr or se):
                continue  # 常关
            if not (aw and tr and se):
                # 非全选：需 current_mastery 命中（None=降级显示）
                hit = (cur is None
                       or (cur == "awakening" and aw)
                       or (cur == "truth" and tr)
                       or (cur == "secret" and se))
                if not hit:
                    continue
            pos = buff_order.get(bkey, idx + 1)
            _ordered.append((pos, buff))
        _ordered.sort(key=lambda t: t[0])
        self.active_buffs = [b for _, b in _ordered]
        # 检测层数增加 → 新出现尖刺闪光（全局闪光：完成色/放大比例/动画时长；应用模块含尖刺）
        if bool(self.settings.get("flash_apply_spikes", True)):
            now_ms = int(time.time() * 1000)
            new_prev = {}
            for buff in self.active_buffs:
                bkey = _bkey(buff['index'], buff.get("group"))
                cur = int(buff.get("stacks", 0))
                prev = self._prev_buff_stacks.get(bkey, 0)
                if cur > prev:
                    self._spike_flash[bkey] = {"start": now_ms, "from": prev, "to": cur}
                elif cur < prev:
                    # 层数回退：消失的尖刺（index 从 cur 到 prev-1）全部闪光。
                    # from=当前层数(新低)，to=回退前的旧层数；绘制时这些多出来的尖刺以闪光呈现后消失。
                    self._spike_flash[bkey] = {"start": now_ms, "from": cur, "to": prev}
                new_prev[bkey] = cur
            self._prev_buff_stacks = new_prev
            # 清理已结束的闪光记录
            dur = int(self.settings.get("flash_duration_ms", 400))
            expired = [k for k, v in self._spike_flash.items() if now_ms - v["start"] >= dur]
            for k in expired:
                del self._spike_flash[k]
        else:
            self._prev_buff_stacks = {
                _bkey(b['index'], b.get("group")): int(b.get("stacks", 0))
                for b in self.active_buffs
            }
        # 读取技能冷却
        if self.status == "ok":
            char_base = read_u64(self.handle, self.pptr + CHAR_PTR_OFF)
            new_skills = read_skill_cooldowns(self.handle, char_base)
            cd_max = self.settings.get("skill_cooldown_max", {})
            now_ms = int(time.time() * 1000)
            for i, sk in enumerate(new_skills):
                abid = ""
                g = _lookup_ability(sk["ability_hash"], self.pl_id, i)
                if g:
                    abid = g.get("id", "")
                # 学习冷却上限：第一次读取或当前值更大时更新；即使 abid 为空也
                # 用当前 cd 作为临时上限，避免首次使用技能时扇形为空。
                current_max = cd_max.get(abid, 0) if abid else cd_max.get(str(sk["ability_hash"]), 0)
                if sk["cd"] > current_max:
                    if abid:
                        cd_max[abid] = sk["cd"]
                    else:
                        cd_max[str(sk["ability_hash"])] = sk["cd"]
                # 检测冷却完成 → 触发动画（受「应用：能力模块」开关控制）
                if sk["ready"] and bool(self.settings.get("flash_apply_skill_ready", True)) \
                        and self.skill_cd_data and i < len(self.skill_cd_data):
                    if not self.skill_cd_data[i].get("ready", True):
                        self._skill_ready_anim[i] = now_ms
                sk["ability_id"] = abid
                sk["cd_max"] = cd_max.get(abid, 0) if abid else cd_max.get(str(sk["ability_hash"]), 0)
            self.skill_cd_data = new_skills
            if cd_max != self.settings.get("skill_cooldown_max", {}):
                self.settings["skill_cooldown_max"] = cd_max
                save_settings(self.settings)

        # ── 战斗/任务状态检测（用于「非战斗隐藏」）──
        # 非战斗 = 不在副本/任务中 且 不在训练场。
        # 训练场通过 quest_mgr+0xB20/0xB28 两个 u32 计时器判定（小镇等恒为0，训练场非零）。
        in_combat = True
        in_training_area = False
        if self.module_base and self.handle:
            try:
                if self.quest_mgr is None:
                    mgr, _ = resolve_quest_mgr_with_addr(
                        self.handle, self.module_base, self.module_size or 0x80000000
                    )
                    self.quest_mgr = mgr
                mgr = self.quest_mgr
                if mgr:
                    flow = read_u64(self.handle, mgr + QUEST_FLOW_OFFSET)
                    in_quest = bool(flow and flow > 0x10000)
                    in_combat = in_quest
                    try:
                        training_timers = [
                            read_u32(self.handle, mgr + off) or 0
                            for off in QUEST_TRAINING_TIMER_OFFSETS
                        ]
                        # 训练场判定：T20 或 T28 任意一个非零即视为训练场（OR 逻辑，非 AND）。
                        # 二者是同一计时器的两个字段，实战中常只有一个在涨，所以必须用 OR。
                        t20 = training_timers[0]
                        t28 = training_timers[1]
                        in_training_area = (not in_quest) and (t20 != 0 or t28 != 0)
                    except Exception:
                        in_training_area = False
                    if in_training_area:
                        in_combat = True
            except Exception:
                in_combat = True
        self.in_combat = in_combat
        self.in_training_area = in_training_area

    def close_handle(self):
        if self.handle:
            try:
                kernel32.CloseHandle(self.handle)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        self.handle = None
        self.pptr = None
        self.module_base = None
        self.pid = None
        self.mastery_reader = None
        self.current_mastery = None
        # V2316 BUGFIX：进程关闭即清空 quest_mgr。
        # 否则重启游戏后它仍指向旧进程地址，战斗状态判定 read_u64(新句柄, 旧地址) 读到野指针
        # → in_combat 误判 False → 「非战斗隐藏」开启时除翻滚外所有模块内容被隐藏
        # （翻滚故意忽略 OOC，故独善其身）。见 scan() 重连分支同款修复。
        self.quest_mgr = None

    # ================================================================
    #  在线更新检测
    # ================================================================
    def _set_update_brief(self, text):
        """更新『标题栏实时更新状态』文案，广播给设置窗口标题栏，并强制核心模块重绘。"""
        self.update_brief = text or ""
        try:
            self.update_status_changed.emit(self.update_brief)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
        # 核心模块 canvas 版本文本是绘制出来的，强制一次重绘保证实时可见
        try:
            if getattr(self, "core_win", None) is not None:
                self.core_win.update()
        except Exception:
            logger.debug("swallowed exception", exc_info=True)

    def check_update(self, manual=False, force=False):
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        url = (self.settings.get("update_check_url") or "").strip()
        if not url:
            self.update_info = {"error": "no_url"}
            self._set_update_brief(_tr("未配置更新地址"))
            self.update_checked.emit(self.update_info)
            return
        auto = bool(self.settings.get("auto_check_update", True))
        if not manual and not auto and not force:
            return
        skip = self.settings.get("skip_version", "") or ""
        self._set_update_brief(_tr("检查中…"))
        self._update_thread = threading.Thread(target=self._do_check_update, args=(url, manual, skip), daemon=True)
        self._update_thread.start()

    def _do_check_update(self, url, manual, skip):
        info = {"has_update": False, "error": None, "checked_at": time.time()}
        try:
            data_bytes, _, err = _qt_sync_get(url, timeout_ms=15000)
            if err:
                info["error"] = err
                self.update_info = info
                self.update_checked.emit(info)
                return
            data = json.loads(data_bytes.decode("utf-8"))
            latest = str(data.get("version", "")).strip()
            info["latest_version"] = latest
            info["download_url"] = data.get("download_url", "")
            info["changelog"] = data.get("changelog", "")
            info["min_version"] = data.get("min_version", "")
            if latest and self._version_gt(latest, APP_VERSION) and latest != skip:
                info["has_update"] = True
        except Exception as e:
            info["error"] = str(e)
        self.update_info = info
        if info.get("error"):
            self._set_update_brief(_tr("检查失败"))
        elif info.get("has_update"):
            self._set_update_brief(_tr("发现新版本") + " v" + str(info.get("latest_version", "")))
        else:
            self._set_update_brief(_tr("已是最新"))
        self.update_checked.emit(info)

    def _on_update_checked(self, info):
        if info.get("has_update"):
            try:
                latest = str(info.get("latest_version", "")).strip()
                msg = QMessageBox(self.core_win)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle(_tr("发现新版本"))
                msg.setText(_tr("发现新版本") + (f" v{latest}" if latest else "") + "！")
                msg.setInformativeText(_tr("是否前往下载？更新日志可在 设置 → 关于 查看。"))
                btn_dl = msg.addButton(_tr("去下载"), QMessageBox.AcceptRole)
                btn_skip = msg.addButton(_tr("跳过此版本"), QMessageBox.RejectRole)
                msg.addButton(_tr("稍后"), QMessageBox.NoRole)
                msg.setDefaultButton(btn_dl)
                msg.exec()
                clicked = msg.clickedButton()
                if clicked is btn_dl:
                    url = (info.get("download_url") or "").strip()
                    if url and not self.start_self_update(url):
                        # 应用内下载启动失败（如无写入权限）时回退浏览器
                        QDesktopServices.openUrl(QUrl(url))
                elif clicked is btn_skip:
                    self.settings["skip_version"] = latest
                    save_settings(self.settings)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        dlg = getattr(self, "settings_dialog", None)
        if dlg is not None:
            try:
                dlg.refresh_update_ui(info)
            except Exception:
                logger.debug("swallowed exception", exc_info=True)

    # ---------------- 应用内自更新 ----------------
    def start_self_update(self, url):
        """应用内下载新 exe 到旧 exe 同目录；返回 False 表示无法启动下载。"""
        url = (url or "").strip()
        if not url:
            return False
        if self._dl_thread is not None and self._dl_thread.is_alive():
            return True
        # 直连 GitHub Release CDN（国内不挂梯时 releases/download 走 CDN 最稳）
        # 不再使用第三方镜像（mirror 站不稳定导致 Connection timed out）
        from urllib.parse import urlparse, unquote
        name = os.path.basename(unquote(urlparse(url).path)) or "GBFR_CooldownIndicator_new.exe"
        # 新文件名不能与当前正在运行的 exe 重名（Windows 下运行中的 exe 被锁定）
        cur_name = os.path.basename(os.path.abspath(sys.argv[0])) if getattr(sys, "frozen", False) else ""
        if cur_name and name.lower() == cur_name.lower():
            stem, ext = os.path.splitext(name)
            name = stem + "_new" + ext
        target = os.path.join(EXE_DIR, name)
        part_path = target + ".part"   # 先下 .part，校验 MZ 头成功后再改名，避免半截 exe
        self._dl_cancel = False
        # 进度/状态全显示在标题栏（不弹任何对话框）
        self._set_update_brief(_tr("正在下载新版本…"))
        self._dl_thread = threading.Thread(
            target=self._do_download_update, args=(url, part_path, target), daemon=True)
        self._dl_thread.start()
        return True

    def _do_download_update(self, url, part_path, target_path):
        # HTTP/1.1 单连接下载，失败自动重试 3 次（不弹窗，状态显示在标题栏）。
        _MAX_RETRIES = 3
        for attempt in range(1, _MAX_RETRIES + 1):
            if self._dl_cancel:
                self._safe_remove(part_path)
                self.update_dl_done.emit("", "cancelled")
                return
            if attempt > 1:
                self.update_dl_retry.emit(attempt - 1, _MAX_RETRIES - 1)
                time.sleep(1)   # 重试前等 1 秒
            self._set_update_brief(_tr("正在下载新版本…"))
            try:
                self._safe_remove(part_path)
                fd = open(part_path, "wb")
                try:
                    recv = [0]
                    total = [0]

                    def _on_total(t):
                        total[0] = t

                    def _on_chunk(chunk):
                        if self._dl_cancel:
                            return
                        fd.write(chunk)
                        recv[0] += len(chunk)
                        self.update_dl_progress.emit(recv[0], total[0])

                    _, _, err = _qt_sync_get(
                        url, timeout_ms=600000, on_chunk=_on_chunk,
                        on_total=_on_total, abort_check=lambda: self._dl_cancel)
                finally:
                    fd.close()
                if self._dl_cancel:
                    raise _UpdateCancelled()
                if err:
                    if attempt < _MAX_RETRIES:
                        continue
                    self._safe_remove(part_path)
                    self.update_dl_done.emit("", err)
                    return
                with open(part_path, "rb") as f:
                    head = f.read(2)
                if head != b"MZ":
                    self._safe_remove(part_path)
                    self.update_dl_done.emit("", "bad_file")
                    return
                os.replace(part_path, target_path)
                self.update_dl_done.emit(target_path, "")
                return
            except _UpdateCancelled:
                self._safe_remove(part_path)
                self.update_dl_done.emit("", "cancelled")
                return
            except Exception as e:
                if attempt < _MAX_RETRIES:
                    continue
                self._safe_remove(part_path)
                self.update_dl_done.emit("", str(e))
                return

    @staticmethod
    def _safe_remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _on_dl_progress(self, recv, total):
        # 进度显示在标题栏（通过 _set_update_brief → 核心模块 canvas + 设置窗口标题）
        if total > 0:
            pct = int(recv * 100 / total)
            self._set_update_brief(_tr("下载中") + f" {recv / 1048576:.1f} / {total / 1048576:.1f} MB ({pct}%)")
        else:
            self._set_update_brief(_tr("下载中") + f" {recv / 1048576:.1f} MB")

    def _on_dl_done(self, path, error):
        if error == "cancelled":
            self._set_update_brief(_tr("下载已取消"))
            return
        if error:
            # 错误只显示在标题栏，不弹对话框（用户不想要弹窗）
            self._set_update_brief(_tr("下载失败") + f": {error}")
            return
        if not path:
            return
        # 下载完成：静默关闭当前程序并启动新 exe（不弹窗）
        ok = QProcess.startDetached(path, [], EXE_DIR)
        if ok:
            # 先关闭所有窗口，再退出事件循环，避免残留界面闪烁
            for w in QApplication.topLevelWidgets():
                try:
                    w.close()
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
            QApplication.quit()
        else:
            self._set_update_brief(_tr("启动新版本失败") + f": {path}")

    def _on_dl_retry(self, current, maximum):
        """下载失败自动重试时更新标题栏。"""
        self._set_update_brief(_tr("下载重试") + f" {current}/{maximum}…")

    @staticmethod
    def _version_gt(a, b):
        def _v(s):
            parts = []
            for p in str(s).split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return tuple(parts)
        return _v(a) > _v(b)

class ModuleWindow(QWidget):
    """可鼠标拖动的独立模块窗口：无边框、透明背景、置顶；各自保存屏幕位置与缩放。

    支持从四个角拖动以独立缩放本模块（每个模块有各自的缩放比例，
    取代原先的全局等比缩放）。窗口归并到一个隐藏宿主窗口，任务栏只显示一项。
    """

    RESIZE_MARGIN = 14
    MIN_SCALE = 0.2
    MAX_SCALE = 8.0

    def __init__(self, ctrl, module_key, title="", parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.module_key = module_key
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.drag_pos = None
        self.resize_mode = None            # 'tl'/'tr'/'bl'/'br' 或 None
        self.resize_start = None           # QPoint 全局起始位置
        self.resize_start_rect = None      # (x, y, w, h, disp)
        self.window_w = 100
        self.window_h = 100
        self.module_scale = 1.0
        self.disp_w = 1.0
        self.disp_h = 1.0
        if title:
            self.setWindowTitle(title)
        self.recalc_layout()
        nx = int(self.ctrl.settings.get(f"{module_key}_window_x", 100))
        ny = int(self.ctrl.settings.get(f"{module_key}_window_y", 100))
        x, y = self.ctrl.denorm_pos(nx, ny)
        self.move(x, y)
        self.resize(self.window_w, self.window_h)

    # --------------------------------------------------------------
    #  缩放（每个模块独立）
    # --------------------------------------------------------------
    def recalc_layout(self):
        """基类：读取本模块等比缩放，计算显示缩放（宽高统一，不做独立拉伸）；子类负责按画布计算 window_w/h。"""
        self.module_scale = max(self.MIN_SCALE, min(self.MAX_SCALE,
            int(self.ctrl.settings.get(f"{self.module_key}_scale_percent", 100)) / 100.0))
        self.disp_w = self.module_scale * self.ctrl.res_scale
        self.disp_h = self.disp_w

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.scale(self.disp_w, self.disp_h)
            self.render(painter)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)

    def render(self, painter):
        pass

    # --------------------------------------------------------------
    #  角点检测 / 光标
    # --------------------------------------------------------------
    def _corner_at(self, pos):
        m = self.RESIZE_MARGIN
        w, h = self.width(), self.height()
        left = pos.x() <= m
        right = pos.x() >= w - m
        top = pos.y() <= m
        bottom = pos.y() >= h - m
        if left and top:
            return "tl"
        if right and top:
            return "tr"
        if left and bottom:
            return "bl"
        if right and bottom:
            return "br"
        return None

    def _cursor_for_corner(self, corner):
        if corner in ("tl", "br"):
            return Qt.SizeFDiagCursor
        return Qt.SizeBDiagCursor

    def nativeEvent(self, eventType, message):
        # Windows：frameless + 半透明 Tool 窗口下，Qt 默认会在 WM_SETCURSOR 时把光标
        # 重置回箭头，导致四角缩放光标（斜向双箭头）悬停/拖拽时不显示。这里接管
        # WM_SETCURSOR，按当前鼠标所在角落直接调用 SetCursor，确保缩放光标正确切换。
        # 注意：WM_SETCURSOR 的 lParam 是「命中测试码 + 鼠标消息ID」，并非坐标，
        # 必须用 QCursor.pos() 取真实全局坐标再 mapFromGlobal 转窗口局部坐标。
        if eventType == b"windows_generic_MSG":
            try:
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x0020:  # WM_SETCURSOR
                    corner = None
                    if not self.ctrl.locked:
                        gp = QCursor.pos()
                        pos = self.mapFromGlobal(gp)
                        c = self._corner_at(pos)
                        if c is not None and not (self.module_key == "core" and self._over_core_button(pos)):
                            corner = c
                    if corner in ("tl", "br"):
                        h = user32.LoadCursorW(0, 32642)   # IDC_SIZENWSE  (\)
                    elif corner in ("tr", "bl"):
                        h = user32.LoadCursorW(0, 32643)   # IDC_SIZENESW  (/)
                    else:
                        h = user32.LoadCursorW(0, 32512)   # IDC_ARROW
                    if h:
                        user32.SetCursor(h)
                    return True, 0
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
        return super().nativeEvent(eventType, message)

    def _over_core_button(self, pos):
        """核心窗口：标题栏右上角图标按钮区域不触发缩放，避免与按钮冲突。
        但四角优先用于缩放——即使角落恰好压在按钮上，也按缩放处理，保证四个角都能拖。"""
        if self.module_key != "core":
            return False
        if self._corner_at(pos) is not None:
            return False
        ctrl = self.ctrl
        th = ctrl.TITLE_BAR_H
        disp = getattr(getattr(ctrl, "core_win", None), "disp_w", 1.0) or 1.0
        # pos 为窗口局部像素：标题栏高（画布）= TITLE_BAR_H，换算成窗口像素比较
        if pos.y() > th * disp:
            return False
        for rect in (getattr(ctrl, "_btn_exit_rect_win", None),
                     getattr(ctrl, "_btn_settings_rect_win", None),
                     getattr(ctrl, "_btn_minimize_rect_win", None),
                     getattr(ctrl, "_btn_lock_rect_win", None)):
            if rect is not None and rect.contains(pos):
                return True
        return False

    # --------------------------------------------------------------
    #  鼠标交互：移动 / 四角缩放
    # --------------------------------------------------------------
    def _begin_drag_or_resize(self, event):
        if self.ctrl.locked:
            return
        # V2244：非「自定义」对齐轴 = 参数化布局，禁止一切手动布局（拖拽 + 四角缩放）
        if self._manual_blocked():
            return
        # V2025：拖拽 / 缩放进行中置锁，焦点同步跳过、绝不隐藏（防止点模块瞬间被误杀）
        self.ctrl._interacting = True
        pos = event.position().toPoint()
        corner = self._corner_at(pos)
        if corner is not None:
            self.resize_mode = corner
            self.resize_start = event.globalPosition().toPoint()
            self.resize_start_rect = (self.x(), self.y(), self.width(), self.height(), int(self.ctrl.settings.get(f"{self.module_key}_scale_percent", 100)))
        else:
            self.drag_pos = event.globalPosition().toPoint() - self.geometry().topLeft()

    def _anchor_locked(self):
        """V2244：按整屏对齐状态返回各轴是否「参数化锁定」（非「自定义」即锁定）。
        锁定后禁止鼠标手动拖拽 / 缩放——对齐本质就是参数化布局。"""
        _s = getattr(self.ctrl, "settings", {})
        _ha = str(_s.get(f"{self.module_key}_halign", "custom"))
        _va = str(_s.get(f"{self.module_key}_valign", "custom"))
        return (_ha != "custom", _va != "custom")

    def _manual_blocked(self):
        """V2244：任一轴非自定义即禁止一切手动布局（拖拽 + 四角缩放）。"""
        h_lock, v_lock = self._anchor_locked()
        return h_lock or v_lock

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_drag_or_resize(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self.resize_mode is not None and not self.ctrl.locked:
            self._do_resize(event)
            return
        if self.drag_pos is not None and not self.ctrl.locked:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            return
        # 悬停时光标提示缩放角（非 custom 轴锁定时不显示可拖拽光标）
        if not self.ctrl.locked and not self._manual_blocked():
            corner = self._corner_at(pos)
            if corner is not None and not (self.module_key == "core" and self._over_core_button(pos)):
                self.setCursor(self._cursor_for_corner(corner))
            elif self.cursor().shape() != Qt.ArrowCursor:
                self.setCursor(Qt.ArrowCursor)

    def _do_resize(self, event):
        gp = event.globalPosition().toPoint()
        dx = gp.x() - self.resize_start.x()
        dy = gp.y() - self.resize_start.y()
        corner = self.resize_mode
        sx, sy, sw, sh, start_pct = self.resize_start_rect
        pw = sw + dx if "r" in corner else sw - dx
        ph = sh + dy if "b" in corner else sh - dy
        pw = max(30, pw)
        ph = max(30, ph)
        # 等比缩放：取位移较大的轴作为基准，保持画布宽高比（鼠标拖拽只改 scale_percent）
        scale_x = pw / sw
        scale_y = ph / sh
        rel = scale_x if abs(dx) >= abs(dy) else scale_y
        # 相对起始比例的缩放，限制在全局 MIN/MAX 之内
        rel = max(self.MIN_SCALE / (start_pct / 100.0), min(self.MAX_SCALE / (start_pct / 100.0), rel))
        new_pct = max(self.MIN_SCALE * 100, min(self.MAX_SCALE * 100, start_pct * rel))
        self.ctrl.settings[f"{self.module_key}_scale_percent"] = int(round(new_pct))
        self.recalc_layout()
        new_w = self.window_w
        new_h = self.window_h
        nx, ny = sx, sy
        if "l" in corner:
            nx = sx + (sw - new_w)
        if "t" in corner:
            ny = sy + (sh - new_h)
        self.setGeometry(nx, ny, new_w, new_h)
        self.update()
        self._notify_scale_changed()

    def _notify_scale_changed(self):
        """拖拽缩放时，若设置对话框开着，同步更新其滑块数值（不触发级联刷新）。"""
        dlg = getattr(self.ctrl, "settings_dialog", None)
        if dlg is None:
            return
        val = int(round(self.module_scale * 100))
        for name in (f"{self.module_key}_scale_slider", f"{self.module_key}_scale_spin"):
            w = getattr(dlg, name, None)
            if w is not None:
                w.blockSignals(True)
                w.setValue(val)
                w.blockSignals(False)

    def mouseReleaseEvent(self, event):
        # V2025：拖拽 / 缩放结束，解除交互锁
        self.ctrl._interacting = False
        if self.resize_mode is not None:
            self.resize_mode = None
            nx, ny = self.ctrl.norm_pos(self.x(), self.y())
            self.ctrl.settings[f"{self.module_key}_window_x"] = nx
            self.ctrl.settings[f"{self.module_key}_window_y"] = ny
            save_settings(self.ctrl.settings)
            return
        if self.drag_pos is not None:
            nx, ny = self.ctrl.norm_pos(self.x(), self.y())
            self.ctrl.settings[f"{self.module_key}_window_x"] = nx
            self.ctrl.settings[f"{self.module_key}_window_y"] = ny
            save_settings(self.ctrl.settings)
        self.drag_pos = None

class CoreWindow(ModuleWindow):
    """核心检测模块：尖刺圆 + 标题栏（含控制图标）。"""

    def recalc_layout(self):
        super().recalc_layout()
        _cw = getattr(self.ctrl, "core_canvas_w", self.ctrl.CANVAS_W)
        _ch = getattr(self.ctrl, "core_canvas_h", self.ctrl.TITLE_BAR_H + 300)
        self.window_w = max(1, int(_cw * self.disp_w))
        self.window_h = max(1, int(_ch * self.disp_h))

    def render(self, painter):
        self.ctrl.render_core(painter)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        raw = event.position().toPoint()
        # 标题栏图标命中：直接用窗口局部像素与 *_rect_win 比较（与 paintEvent 的 scale(disp_w) 一致，无需换算）
        if self.ctrl.locked:
            if self.ctrl._btn_lock_rect_win.contains(raw):
                self.ctrl._pressed_core_btn = "lock"
                self.ctrl._pressed_visual = True
                self.update()
            return
        # 按下时只记录「按下态」并刷新绘制（凹陷反馈），实际动作延迟到 mouseRelease 触发
        if self.ctrl._btn_exit_rect_win.contains(raw):
            self.ctrl._pressed_core_btn = "exit"; self.ctrl._pressed_visual = True; self.update(); return
        if self.ctrl._btn_minimize_rect_win.contains(raw):
            self.ctrl._pressed_core_btn = "minimize"; self.ctrl._pressed_visual = True; self.update(); return
        if self.ctrl._btn_lock_rect_win.contains(raw):
            self.ctrl._pressed_core_btn = "lock"; self.ctrl._pressed_visual = True; self.update(); return
        if self.ctrl._btn_settings_rect_win.contains(raw):
            self.ctrl._pressed_core_btn = "settings"; self.ctrl._pressed_visual = True; self.update(); return
        # ── 四角缩放（按钮之外的角落）──
        if self._corner_at(raw) is not None:
            self._begin_drag_or_resize(event)
            return
        # ── 其余区域拖动窗口（标题栏与内容区均可拖动）──
        self._begin_drag_or_resize(event)

    def mouseMoveEvent(self, event):
        # 按住某个标题栏图标时：仅更新视觉按下态（指针是否仍在按钮内），【不清除】已锁定的按钮，
        # 避免按下到释放间的极微抖动使命中矩形 miss、导致 mouseRelease 读到 None 而不触发动作
        if self.ctrl._pressed_core_btn is not None:
            raw = event.position().toPoint()
            rect = getattr(self.ctrl, "_btn_%s_rect_win" % self.ctrl._pressed_core_btn, None)
            self.ctrl._pressed_visual = bool(rect is not None and rect.contains(raw))
            self.update()
            return
        # 核心窗口：显式处理四角缩放光标，确保系统光标正确切换
        pos = event.position().toPoint()
        corner = self._corner_at(pos)
        if corner is not None and not self._over_core_button(pos):
            self.setCursor(self._cursor_for_corner(corner))
        elif self.cursor().shape() != Qt.ArrowCursor:
            self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        btn = self.ctrl._pressed_core_btn
        if btn is not None:
            self.ctrl._pressed_core_btn = None
            self.ctrl._pressed_visual = False
            self.update()
            # 按下即已锁定该按钮，释放即触发（轻微移出按钮也算点击，符合常规按钮行为）
            self._activate_core_btn(btn)
            return
        super().mouseReleaseEvent(event)

    def _activate_core_btn(self, btn):
        """标题栏图标在 mouseRelease（且仍在按钮内）时触发的实际动作。"""
        if btn == "exit":
            QApplication.quit()
        elif btn == "minimize":
            # V2300：必须走统一仲裁入口（登记隐藏意图）。
            # 旧代码是裸 for 循环 w.hide()，不登记 _bg_hidden，
            # 于是下一次仲裁（进出战斗 / 改设置）会因为「意图为空 + 模块开关为开」把窗口又弹回来，
            # 表现为「点了最小化却自动复活」。
            self.ctrl._hide_all_windows()
        elif btn == "lock":
            self.ctrl.locked = not self.ctrl.locked
            for w in self.ctrl._all_windows():
                w.update()
        elif btn == "settings":
            self.ctrl.open_settings()

class DodgeWindow(ModuleWindow):
    """翻滚模块：独立窗口，可横/竖排。"""

    def recalc_layout(self):
        super().recalc_layout()
        _rw = getattr(self.ctrl, "roll_canvas_w", 200)
        _rh = getattr(self.ctrl, "roll_canvas_h", 60)
        self.window_w = max(1, int(_rw * self.disp_w))
        self.window_h = max(1, int(_rh * self.disp_h))

    def render(self, painter):
        self.ctrl.render_roll(painter)

class SkillWindow(ModuleWindow):
    """能力冷却模块：独立窗口，4 菱形。"""

    def recalc_layout(self):
        super().recalc_layout()
        _sw = getattr(self.ctrl, "skill_canvas_w", 300)
        _sh = getattr(self.ctrl, "skill_canvas_h", 300)
        self.window_w = max(1, int(_sw * self.disp_w))
        self.window_h = max(1, int(_sh * self.disp_h))

    def render(self, painter):
        self.ctrl.render_skill(painter)


class AllBuffWindow(ModuleWindow):
    """全 Buff 显示模块（第四模块）：网格化轻量卡片，列出当前主控角色可读到的全部 buff。

    复用三大模块的交集特质：独立显隐开关 / 独立屏幕位置 XY / 整体缩放 / 位置与缩放子页 /
    元素级透明度（名称·层数·时间各字号+颜色；进度条与衬底各带独立不透明度）。
    """

    # V2104：恢复 allbuff_rows 设置项后，recalc_layout 直接用 allbuff_rows 预留精确行数，
    # 与运行时 render_allbuff 的固定网格（rows × per_row）完全一致；不再用估算值。

    def recalc_layout(self):
        super().recalc_layout()
        bw_setting = max(1, int(self.ctrl.settings.get("allbuff_backing_width", 80)))
        bh_setting = max(1, int(self.ctrl.settings.get("allbuff_backing_height", 64)))
        per_row = max(1, int(self.ctrl.settings.get("allbuff_per_row", 10)))
        rows = max(1, int(self.ctrl.settings.get("allbuff_rows", 3)))
        row_sp = int(self.ctrl.settings.get("allbuff_row_spacing", 4))
        card_sp = int(self.ctrl.settings.get("allbuff_card_spacing", 4))

        # V2062：自适应 floor——取 max(按当前 font/elem_sp/bar/frame 计算的最小可视尺寸, 用户设置)
        # 玩家调小 bw/bh 也不会让卡片裁切
        pad = 2
        name_fs = max(1, int(self.ctrl.settings.get("allbuff_name_font_size", 11)))
        stacks_fs = max(1, int(self.ctrl.settings.get("allbuff_stacks_font_size", 10)))
        time_fs = max(1, int(self.ctrl.settings.get("allbuff_time_font_size", 10)))
        bar_w = max(1, int(self.ctrl.settings.get("allbuff_bar_width", 60)))
        bar_h = max(1, int(self.ctrl.settings.get("allbuff_bar_height", 5)))
        bar_frame_t = max(0, min(10, int(self.ctrl.settings.get("allbuff_bar_frame_thickness", 2))))
        # V2075：允许负值，与 render_allbuff 一致（负间距让估算的卡片高度更紧凑）
        elem_sp = int(self.ctrl.settings.get("allbuff_element_spacing", 4))
        row_h_extra = int(self.ctrl.settings.get("allbuff_row_height_extra", 0))
        # V2217：融合 3 行 + QFontMetrics，与 _apply_allbuff_fixed_size / render_* 完全一致，消除多排被切。
        from PySide6.QtGui import QFont as _QF, QFontMetrics as _QFM
        _name_h   = _QFM(_QF("Segoe UI", name_fs,   _QF.Bold)).height() + 2 + row_h_extra
        _stacks_h = _QFM(_QF("Segoe UI", stacks_fs, _QF.Bold)).height() + 2 + row_h_extra
        _time_h   = _QFM(_QF("Segoe UI", time_fs,   _QF.Bold)).height() + 2 + row_h_extra
        _fused_bh = max(_time_h, (bar_h + 2 * bar_frame_t))
        auto_bh = (2 * pad
                   + _name_h   + elem_sp
                   + _stacks_h + elem_sp
                   + _fused_bh)
        auto_bh = max(1, auto_bh)
        auto_bw = bar_w + 2 * bar_frame_t + 8
        bw = max(auto_bw, bw_setting)
        bh = max(auto_bh, bh_setting)

        # 画布尺寸（未经 res_scale 缩放，window_w/h 由 disp_w 处理）
        cw = per_row * bw + max(0, per_row - 1) * card_sp
        ch = rows * bh + max(0, rows - 1) * row_sp
        self.ctrl.allbuff_canvas_w = cw
        self.ctrl.allbuff_canvas_h = ch
        self.window_w = max(1, int(cw * self.disp_w))
        self.window_h = max(1, int(ch * self.disp_h))

    def render(self, painter):
        self.ctrl.render_allbuff(painter)



class BossBuffWindow(ModuleWindow):
    """Boss Buff 显示模块（第五模块）：网格化轻量卡片，列出当前 BOSS 身上的全部 buff/debuff。

    V2200：与全 Buff 模块的区别只在数据源——
      全 Buff = 主控角色 actor + 0xAF8 的 ExStatus
      Boss   = 场上 boss actor + 0xD10 的 ExStatus（组件在 +0xCF8）
    外观 / 布局 / 门限 / 名单逻辑与全 Buff 模块一致（render_bossbuff 复制自 render_allbuff）。

    复用三大模块的交集特质：独立显隐开关 / 独立屏幕位置 XY / 整体缩放 / 位置与缩放子页 /
    元素级透明度（名称·层数·时间各字号+颜色；进度条与衬底各带独立不透明度）。
    """

    # V2104：恢复 boss_rows 设置项后，recalc_layout 直接用 boss_rows 预留精确行数，
    # 与运行时 render_bossbuff 的固定网格（rows × per_row）完全一致；不再用估算值。

    def recalc_layout(self):
        super().recalc_layout()
        bw_setting = max(1, int(self.ctrl.settings.get("boss_backing_width", 80)))
        bh_setting = max(1, int(self.ctrl.settings.get("boss_backing_height", 64)))
        per_row = max(1, int(self.ctrl.settings.get("boss_per_row", 10)))
        rows = max(1, int(self.ctrl.settings.get("boss_rows", 3)))
        row_sp = int(self.ctrl.settings.get("boss_row_spacing", 4))
        card_sp = int(self.ctrl.settings.get("boss_card_spacing", 4))

        # V2062：自适应 floor——取 max(按当前 font/elem_sp/bar/frame 计算的最小可视尺寸, 用户设置)
        # 玩家调小 bw/bh 也不会让卡片裁切
        pad = 2
        name_fs = max(1, int(self.ctrl.settings.get("boss_name_font_size", 11)))
        stacks_fs = max(1, int(self.ctrl.settings.get("boss_stacks_font_size", 10)))
        time_fs = max(1, int(self.ctrl.settings.get("boss_time_font_size", 10)))
        bar_w = max(1, int(self.ctrl.settings.get("boss_bar_width", 60)))
        bar_h = max(1, int(self.ctrl.settings.get("boss_bar_height", 5)))
        bar_frame_t = max(0, min(10, int(self.ctrl.settings.get("boss_bar_frame_thickness", 2))))
        # V2075：允许负值，与 render_bossbuff 一致（负间距让估算的卡片高度更紧凑）
        elem_sp = int(self.ctrl.settings.get("boss_element_spacing", 4))
        row_h_extra = int(self.ctrl.settings.get("boss_row_height_extra", 0))
        # V2217：融合 3 行 + QFontMetrics，与 _apply_allbuff_fixed_size / render_* 完全一致，消除多排被切。
        from PySide6.QtGui import QFont as _QF, QFontMetrics as _QFM
        _name_h   = _QFM(_QF("Segoe UI", name_fs,   _QF.Bold)).height() + 2 + row_h_extra
        _stacks_h = _QFM(_QF("Segoe UI", stacks_fs, _QF.Bold)).height() + 2 + row_h_extra
        _time_h   = _QFM(_QF("Segoe UI", time_fs,   _QF.Bold)).height() + 2 + row_h_extra
        _fused_bh = max(_time_h, (bar_h + 2 * bar_frame_t))
        auto_bh = (2 * pad
                   + _name_h   + elem_sp
                   + _stacks_h + elem_sp
                   + _fused_bh)
        auto_bh = max(1, auto_bh)
        auto_bw = bar_w + 2 * bar_frame_t + 8
        bw = max(auto_bw, bw_setting)
        bh = max(auto_bh, bh_setting)

        # 画布尺寸（未经 res_scale 缩放，window_w/h 由 disp_w 处理）
        cw = per_row * bw + max(0, per_row - 1) * card_sp
        ch = rows * bh + max(0, rows - 1) * row_sp
        self.ctrl.boss_canvas_w = cw
        self.ctrl.boss_canvas_h = ch
        self.window_w = max(1, int(cw * self.disp_w))
        self.window_h = max(1, int(ch * self.disp_h))

    def render(self, painter):
        self.ctrl.render_bossbuff(painter)
# V2024 修复：Windows 区域=香港（繁体）/台湾 等非简体中文 Windows 下，
# 整个 overlay 的中文（包括设置对话框的所有 tab/label/button）渲染成 □□ 方框。
# 原因：Qt 在 Windows 上不读系统「亚洲字符字体回退」表，代码内 21 处全部 hardcode
# QFont("Segoe UI", ...)，Segoe UI 不含 CJK glyph，常规情况下由 fontconfig/font fallback
# 兜底，但港/繁系统下 Qt 默认行为直接退回 unicode 缺字矩形。修法：在 main() 启动时扫描
# QFontDatabase.families()，挑出已装的 CJK 字体（优先 YaHei → JhengHei → 其他），
# 对 Segoe UI 调用 QFont.insertSubstitution() 注册替代——之后所有 QFont("Segoe UI", ...)
# 缺字时自动回退到该 CJK 字体，零调用点改动。
_CJK_FALLBACK_FAMILY = ""  # 启动时填充；空串 = 没找到任何 CJK 字体（极端系统）
def _setup_cjk_font_fallback():
    global _CJK_FALLBACK_FAMILY
    try:
        from PySide6.QtGui import QFontDatabase
        installed = set(QFontDatabase.families())
    except Exception:
        return
    # 优先级顺序：大陆简体 → 港台繁体 → 日韩 + 开源 Source Han
    # （港台系统反而 JhengHei/PMingLiU 命中，繁中系统 YaHei 也照常装着）
    for cand in (
        "Microsoft YaHei UI", "Microsoft YaHei",
        "Microsoft JhengHei UI", "Microsoft JhengHei",
        "PingFang SC", "PingFang TC",
        "SimHei", "SimSun",
        "Malgun Gothic",         # 韩
        "Yu Gothic", "Meiryo",   # 日
        "Source Han Sans CN", "Source Han Sans SC",
        "Source Han Sans TC", "Noto Sans CJK SC", "Noto Sans CJK TC",
    ):
        if cand in installed:
            _CJK_FALLBACK_FAMILY = cand
            break
    if not _CJK_FALLBACK_FAMILY:
        # 兜底：找任何包含 CJK 字形特征的 family 名（heuristic）
        for fam in installed:
            if any(k in fam for k in ("YaHei", "JhengHei", "Hei", "Sim", "PingFang",
                                       "Han", "CJK", "Yu Gothic", "Malgun", "Meiryo")):
                _CJK_FALLBACK_FAMILY = fam
                break
    if _CJK_FALLBACK_FAMILY:
        # 全局注册 Segoe UI → CJK 字体的字形替代
        try:
            QFont.insertSubstitution("Segoe UI", _CJK_FALLBACK_FAMILY)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)

def main():
    app = QApplication(sys.argv)
    # V2024 修复：先注册 Segoe UI 的 CJK 字体替代，后面的 widget / overlay 全继承。
    # 必须在 QApplication 构造后立即调（QFont.insertSubstitution 是 Qt 全局注册）。
    _setup_cjk_font_fallback()
    if os.path.isfile(APP_ICON_PATH):
        app.setWindowIcon(QIcon(APP_ICON_PATH))
    app.setQuitOnLastWindowClosed(False)
    load_settings()  # 预加载/迁移配置文件（构造内会再次加载，此处仅保留副作用）
    # V2035：去掉启动画面（StartupSplash 类已删除）。直接构造 overlay，无任何进度回调。
    # 🔴 overlay 必须接住返回值：它是这个 Qt 对象在 Python 侧**唯一的强引用**
    # （app.setQuitOnLastWindowClosed(False) 且对象无持久 parent）。若不接收返回值，
    # CPython 会在这一行结束后立刻回收它 —— 窗口瞬间消失且无任何报错。
    # 该行的白名单标记用法见 tools/audit_dead_assign.py 文件头说明。
    overlay = GBFROverlayQt(progress_cb=None)  # noqa: keep-alive —— 构造内已创建并 show 三个模块窗口
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

