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
import urllib.request
from ctypes import wintypes

import mastery_reader
import buff_data_generated

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QBitmap, QBrush, QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QLinearGradient, QPolygonF, QRadialGradient, QIcon, QImage, QPainter, QPen, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSlider,
    QScrollArea,
    QSpacerItem,
    QSpinBox,
    QDoubleSpinBox,
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
APP_ICON_PATH = os.path.join(_BUNDLE_DIR, "app_icon.ico")

# ============================ Version ============================
APP_VERSION = "4.01"
SETTINGS_SCHEMA_VERSION = 90
APP_TITLE = "GBFR_CooldownIndicator_V401"

# ============================ 三语翻译表（提前定义，供 UI 组件全局使用）===========================
from i18n_loader import UI_TRANS
ZH_TO_EN = {k: v.get("en", k) for k, v in UI_TRANS.items()}
ZH_TO_TW = {k: v.get("zh_tw", k) for k, v in UI_TRANS.items()}

def _tr(zh, lang=None):
    """按当前语言返回翻译；lang 缺省时取 retranslate_ui 维护的全局语言。"""
    if lang is None:
        lang = _CURRENT_LANG
    if lang == "en":
        return ZH_TO_EN.get(zh, zh)
    if lang == "zh_tw":
        return ZH_TO_TW.get(zh, zh)
    return zh

_CURRENT_LANG = "zh"
AUTHOR_TAG = "@Bilibili/Dangoooooo"

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
FIELD_DRAGON_HEART = 0x1CAA8
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
QM_DELTA = 0xc1dfd0


# 角色类型字节值 → 名称 (zh / en)
# 来源: CE实测 [玩家]+0x1FD 字节值；这里按十六进制记录
# (简中, 繁中, English) — 来源: GBFR 官方数据
CHAR_TYPE_NAMES = {
    0x07: ("菲莉", "菲莉", "Ferry"),
    0x11: ("齐格飞", "齊格菲", "Siegfried"),
    0x24: ("伽兰查", "伽藍薩", "Gallanza"),
    0x08: ("兰斯洛特", "蘭斯洛特", "Lancelot"),
    0x19: ("伊德", "伊度", "Id"),
    0x23: ("索恩", "蘇恩", "Tweyen"),
    0x17: ("巴萨拉卡", "巴薩拉加", "Vaseraga"),
    0x16: ("塞达", "瑟塔", "Zeta"),
    0x18: ("卡莉奥丝特罗", "卡莉歐斯托蘿", "Cagliostro"),
    0x10: ("珀西瓦尔", "帕西瓦爾", "Percival"),
    0x20: ("伊德(龙人化)", "伊度(龍人化)", "Id (Dragon)"),
    0x22: ("希耶提", "席耶提", "Seofon"),
}
SIEGFRIED_CHAR_TYPE = 0x11

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
# 姬塔(PL0100) 与 古兰(PL0000) 共用一套技能；龙人化(PL2000) 与 伊德(PL1900) 共用一套。
# 主控人物若经查表取不到技能名，按槽位借用规范角色的技能名，避免能力名空着。
PL_SKILL_FALLBACK = {"PL0100": "PL0000", "PL2000": "PL1900"}

# 语言 → CHAR_TYPE_NAMES 元组索引
LANG_NAME_IDX = {"zh": 0, "zh_tw": 1, "en": 2}

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
        return info.get("name_zh", pl), pl
    # 回退：0x1FD 字节
    return _char_name(char_type, lang), CHAR_TYPE_TO_PL.get(char_type)

def _pl_display_name(pl_id, lang="zh"):
    """角色名展示（含 PL 编号）：如 'PL1700 巴萨拉卡' / 'PL1700 Vaseraga'。"""
    info = _char_db.get(pl_id)
    if info:
        if lang == "en":
            nm = info.get("name_en", pl_id)
        elif lang == "zh_tw":
            nm = info.get("name_tw", info.get("name_zh", pl_id))
        else:
            nm = info.get("name_zh", pl_id)
    else:
        nm = pl_id
    return f"{pl_id} {nm}"

def _buff_name(buff, lang="zh"):
    """按语言获取 buff 名称。"""
    if lang == "en":
        return buff.get("en", "")
    if lang == "zh_tw":
        return buff.get("zh_tw", buff.get("zh", ""))
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
            pass
        nm = info.get("角色名", {})
        abilities = []
        for ab in info.get("能力", []):
            aid = ab.get("能力ID", "")
            an = ab.get("能力名", {})
            name_zh = an.get("简体中文", "") or aid
            name_en = an.get("英文", "") or name_zh
            name_tw = an.get("繁体中文", "") or name_zh
            abilities.append({"id": aid, "zh": name_zh, "zh_tw": name_tw, "en": name_en})
            if aid:
                try:
                    ab_hash[game_xxhash32(aid)] = {"pl": pl_id, "id": aid, "zh": name_zh, "zh_tw": name_tw, "en": name_en}
                except Exception:
                    pass
        db[pl_id] = {"name_zh": nm.get("简体中文", "") or pl_id,
                     "name_en": nm.get("英文", "") or pl_id,
                     "name_tw": nm.get("繁体中文", "") or nm.get("简体中文", "") or pl_id,
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
                    "zh_tw": a.get("zh_tw", ""), "en": a.get("en", "")}
    return None


def _skill_name(ab_hash_val, lang="zh", pl_id=None, slot=None):
    g = _lookup_ability(ab_hash_val, pl_id, slot)
    if not g:
        return ""
    if lang == "en":
        return g.get("en", g.get("zh", ""))
    if lang == "zh_tw":
        return g.get("zh_tw", g.get("zh", ""))
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
ID_FORM_NORMAL = 0x19              # 普通/神威一体态
ID_FORM_DRAGON = 0x20              # 龙人态
# 龙人态官方父子指针（来自 gbfr-logs/GBFR-ACT 公开 RE）：真身 actor = read_u64(actor+0xd488)+0x70
ID_DRAGON_PARENT_OFF = 0xD488
ID_DRAGON_PARENT_EXTRA = 0x70

# 伊德资源槽偏移（actor 直接偏移 / 二级指针链的子偏移）
ID_POWER_SUB = -0x3C22B10          # f32 0~1，异能槽
ID_CELLS_SUB = -0x3C22B18          # u32 0~4，龙人格子
ID_OVERDRIVE_SUB = -0x198D9D8      # f32 0~1，神威槽
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


class BuffOrderGroup(QWidget):
    """每个角色一个分组，左栏=生效区（可拖拽排序），右栏=隐藏区。

    关键点（V246 重写，V247 增加折叠）：
    - 所有拖拽都只在本分组（同一角色）内发生；跨角色拖拽在 dropEvent / dragEnter
      处直接拒绝，绝不让一个角色的 buff 跑到另一个角色去；
    - 不物理移动 QListWidgetItem 对象，而是维护 _shown_idx / _hidden_idx 两份
      数据，任何改动后整体重建列表。这样不可能产生克隆条目，也不会让其它 buff 消失；
    - 支持 pl_ids 为多个（如团长：古兰 PL0000 + 姬塔 PL0100 合并一组，共享顺位）；
    - 分组带折叠按钮，默认折叠，便于在众多角色中快速定位。
    """

    orderChanged = Signal()

    def __init__(self, pl_ids, profile, buff_order, lang="zh", title=None):
        self.pl_ids = list(pl_ids)
        self.profile = profile
        self._title_override = title
        self._meta = {
            i: (bc.get("zh", ""), bool(bc.get("single_layer")))
            for i, bc in enumerate(profile.get("buffs", []))
        }
        # 同一分组内拖拽时记录的被拖 idx（UserRole 直接存 idx）
        self._drag_key = None
        self._drag_source = None
        self._collapsed = True
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        # 标题行：折叠按钮 + 标题
        hdr = QHBoxLayout(); hdr.setContentsMargins(0, 0, 0, 0); hdr.setSpacing(4)
        self._collapse_btn = QToolButton(); self._collapse_btn.setFixedSize(18, 18)
        self._collapse_btn.setStyleSheet("QToolButton{border:none;color:#cfe0ff;font-weight:bold;font-size:12px;}")
        self._title_lbl = QLabel(title or _pl_display_name(self.pl_ids[0], lang))
        self._title_lbl.setStyleSheet("color:#cfe0ff;font-weight:bold;font-size:11px;")
        hdr.addWidget(self._collapse_btn); hdr.addWidget(self._title_lbl); hdr.addStretch()
        outer.addLayout(hdr)

        # 主体（可折叠）
        self._body = QWidget()
        b_layout = QVBoxLayout(self._body)
        b_layout.setContentsMargins(2, 2, 2, 2)
        b_layout.setSpacing(3)

        # 左右栏标题：等宽两栏，「生效区」左对齐于左栏左边界、「隐藏区」左对齐于右栏左边界（=中线）
        colhdr = QHBoxLayout(); colhdr.setContentsMargins(0, 0, 0, 0); colhdr.setSpacing(6)
        lbl_shown = QLabel(_tr("生效区（拖动排序）")); lbl_shown.setStyleSheet("color:#b0c4e0;font-size:10px;")
        lbl_hidden = QLabel(_tr("隐藏区")); lbl_hidden.setStyleSheet("color:#b0c4e0;font-size:10px;")
        sw = QWidget(); _sl = QHBoxLayout(); _sl.setContentsMargins(0, 0, 0, 0); _sl.setSpacing(0); _sl.addWidget(lbl_shown); sw.setLayout(_sl)
        hw = QWidget(); _hl = QHBoxLayout(); _hl.setContentsMargins(0, 0, 0, 0); _hl.setSpacing(0); _hl.addWidget(lbl_hidden); hw.setLayout(_hl)
        colhdr.addWidget(sw); colhdr.addWidget(hw)
        b_layout.addLayout(colhdr)

        # 左右列表
        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(6)

        self.shown_list = BuffListWidget(self, is_hidden_side=False)
        self.hidden_list = BuffListWidget(self, is_hidden_side=True)
        # 高度再次放大为当前的 1.2 倍（125 → 150）
        self.shown_list.setMaximumHeight(150)
        self.hidden_list.setMaximumHeight(150)
        self.shown_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.hidden_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        lists_layout.addWidget(self.shown_list)
        lists_layout.addWidget(self.hidden_list)
        b_layout.addLayout(lists_layout)

        hint = QLabel(_tr("左栏=显示，右栏=隐藏；拖到另一侧切换（不可跨角色）"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8aa0c0;font-size:10px;")
        b_layout.addWidget(hint)

        outer.addWidget(self._body)
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        self._apply_collapse()
        self._build_from_buff_order(buff_order)

    # ---------- 折叠 ----------
    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._apply_collapse()

    def _apply_collapse(self):
        self._body.setVisible(not self._collapsed)
        self._collapse_btn.setText("▾" if not self._collapsed else "▸")

    # ---------- 数据 ----------
    def _rank_of(self, i, buff_order):
        for pid in self.pl_ids:
            v = buff_order.get(f"{pid}_{i}")
            if v is not None:
                return int(v or 0)
        return i + 1

    def _build_from_buff_order(self, buff_order):
        buffs = self.profile.get("buffs", [])
        self._shown_idx = []
        self._hidden_idx = []
        for i in range(len(buffs)):
            rank = self._rank_of(i, buff_order)
            if rank > 0:
                self._shown_idx.append(i)
            else:
                self._hidden_idx.append(i)
        # 显示区按 rank 升序排好
        self._shown_idx.sort(key=lambda i: self._rank_of(i, buff_order))
        self._rebuild()

    def _rebuild(self):
        self.shown_list.clear()
        self.hidden_list.clear()
        for i in self._shown_idx:
            self.shown_list.addItem(self._make_item(i, False))
        for i in self._hidden_idx:
            self.hidden_list.addItem(self._make_item(i, True))

    def _make_item(self, idx, hidden):
        label, sl = self._meta.get(idx, ("", False))
        disp = ("✕ " if hidden else "") + label + (_tr("（单层buff）") if sl else "")
        it = QListWidgetItem(disp)
        it.setData(Qt.UserRole, idx)
        if hidden:
            it.setForeground(QColor(255, 95, 95, 204))  # 红色 + 80% 不透明度
        else:
            it.setForeground(QColor(223, 231, 245, 255))
        it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
        return it

    def _refresh_appearances(self):
        """刷新隐藏区外观：加红色✕ + 80%不透明度。"""
        for i in range(self.hidden_list.count()):
            item = self.hidden_list.item(i)
            idx = item.data(Qt.UserRole)
            label, sl = self._meta.get(idx, ("", False))
            item.setText("✕ " + label + (_tr("（单层buff）") if sl else ""))
            item.setForeground(QColor(255, 95, 95, 204))
        for i in range(self.shown_list.count()):
            item = self.shown_list.item(i)
            idx = item.data(Qt.UserRole)
            label, sl = self._meta.get(idx, ("", False))
            item.setText(label + (_tr("（单层buff）") if sl else ""))
            item.setForeground(QColor(223, 231, 245, 255))

    def _sync_from_lists(self):
        """从当前两个列表的视觉顺序读回数据（用于同列内部重排）。"""
        self._shown_idx = []
        self._hidden_idx = []
        for i in range(self.shown_list.count()):
            d = self.shown_list.item(i).data(Qt.UserRole)
            if d is not None:
                self._shown_idx.append(d)
        for i in range(self.hidden_list.count()):
            d = self.hidden_list.item(i).data(Qt.UserRole)
            if d is not None:
                self._hidden_idx.append(d)

    def _move_idx(self, idx, to_hidden, at_row):
        """把 idx 移动到目标侧（to_hidden 决定），插入位置 at_row（None=追加）。"""
        if idx in self._shown_idx:
            self._shown_idx.remove(idx)
        if idx in self._hidden_idx:
            self._hidden_idx.remove(idx)
        if to_hidden:
            lst = self._hidden_idx
        else:
            lst = self._shown_idx
        if at_row is None or at_row < 0 or at_row > len(lst):
            lst.append(idx)
        else:
            lst.insert(at_row, idx)
        self._rebuild()
        self.orderChanged.emit()

    # ---------- 右键菜单 ----------
    def _on_context_menu(self, source_list, pos):
        item = source_list.itemAt(pos)
        if item is None:
            return
        idx = item.data(Qt.UserRole)
        if idx is None:
            return
        menu = QMenu(self)
        if source_list is self.shown_list:
            act_top = menu.addAction(_tr("置顶"))
            act_toggle = menu.addAction(_tr("隐藏"))
            choiced = menu.exec_(source_list.mapToGlobal(pos))
            if choiced == act_top:
                self._move_top(idx)
            elif choiced == act_toggle:
                self._move_idx(idx, to_hidden=True, at_row=None)
        else:
            act_toggle = menu.addAction(_tr("显示"))
            choiced = menu.exec_(source_list.mapToGlobal(pos))
            if choiced == act_toggle:
                self._move_idx(idx, to_hidden=False, at_row=None)

    def _move_top(self, idx):
        if idx in self._shown_idx:
            self._shown_idx.remove(idx)
            self._shown_idx.insert(0, idx)
            self._rebuild()
            self.orderChanged.emit()

    # ---------- 输出 / 批量 ----------
    def get_order(self):
        """返回 {key: rank}：rank>=1 为显示（顺序即从左到右），0 为隐藏。
        多 pl_id（如团长）会为每个 pl_id 各写一份相同顺位。"""
        result = {}
        for pl_id in self.pl_ids:
            shown = 0
            for idx in self._shown_idx:
                shown += 1
                result[f"{pl_id}_{idx}"] = shown
            for idx in self._hidden_idx:
                result[f"{pl_id}_{idx}"] = 0
        return result

    def refresh_title(self, lang):
        if self._title_override:
            self._title_lbl.setText(self._title_override)
        else:
            self._title_lbl.setText(_pl_display_name(self.pl_ids[0], lang))

    def show_all(self):
        buffs = self.profile.get("buffs", [])
        self._shown_idx = list(range(len(buffs)))
        self._hidden_idx = []
        self._rebuild()
        self.orderChanged.emit()

    def hide_all(self):
        buffs = self.profile.get("buffs", [])
        self._shown_idx = []
        self._hidden_idx = list(range(len(buffs)))
        self._rebuild()
        self.orderChanged.emit()


# ExStatus 结构体偏移（来自 GBFR_BuffMonitor 项目验证）
ACTOR_EX_STATUS = 0xAF8       # Actor → ExStatus 指针
STATUS_ID_OFFSET = 0x50      # StatusBase → StatusId (u32)
STATUS_CUR_STACKS = 0x58     # StatusBase → 当前层数 (i32)
STATUS_INFINITE_FLAG = 0x79  # StatusBase → 永续标记 (byte)
STATUS_INITIAL_DUR = 0x7C    # StatusBase → 初始持续时间 (f32) — timer_max
STATUS_REMAINING_DUR = 0x80  # StatusBase → 剩余时间 (f32) — 实时倒计时
STATUS_MAX_STACKS = 0xB0     # StatusBase → 上限层数 (i32)
EX_STATUS_PTR_SLOTS = 16     # 指针数组扫描槽位数

# 技能冷却偏移（来自 GBFR_SkillCooldown 验证）
SKILL_SLOT_OFFSETS = [0x330C, 0x335C, 0x33AC, 0x33FC]
# 修正：装备能力 hash 是 actor + 0x15030 + 0x5AF4 = 0x1AB24，不是 0x1AA24
ABILITY_HASH_OFFSET = 0x1AB24
CHARID_HASH_OFFSET = 0x1AB40
SKILL_READY_THRESHOLD = 0.05

# 角色能力数据库路径
CHAR_DB_PATH = os.path.join(_BUNDLE_DIR, "GBFR_Character_Skills_Buffs.json")
CHAR_DB_FALLBACK = os.path.join(EXE_DIR, "GBFR_Character_Skills_Buffs.json")

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


def find_pid():
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wintypes.HANDLE(-1).value:
        return None
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    pid = None
    if kernel32.Process32First(snap, ctypes.byref(pe)):
        while True:
            name = pe.szExeFile.decode("ascii", "ignore")
            if name.lower() == PROCESS_NAME.lower():
                pid = pe.th32ProcessID
                break
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(snap)
    return pid


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


def resolve_player_ptr(handle, base, size):
    """兼容旧调用：单独扫描并解析玩家指针。"""
    pattern, mask = parse_aob(AOB_HEX)
    hit = aob_scan(handle, base, size, pattern, mask)
    if hit is None:
        return None
    return resolve_player_from_hit(handle, hit)


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
        pass


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


def read_exstatus_buffs(handle, char_base, ex_status_offset=ACTOR_EX_STATUS):
    """从 Actor 的 ExStatus 指针数组读取全部活跃 buff。

    返回 {status_id: {"stacks", "max_stacks", "initial", "remaining", "infinite"}} 字典。
    无效或无 buff 时返回空字典。
    """
    ex_status = read_u64(handle, char_base + ex_status_offset)
    if not ex_status or ex_status < 0x10000:
        return {}
    result = {}
    consecutive_nulls = 0
    for i in range(EX_STATUS_PTR_SLOTS):
        ptr = read_u64(handle, ex_status + i * 8)
        if not ptr or ptr < 0x10000 or ptr >= 0x7FF000000000:
            consecutive_nulls += 1
            if result and consecutive_nulls >= 2:
                break
            continue
        consecutive_nulls = 0
        sid = read_u32(handle, ptr + STATUS_ID_OFFSET)
        if not sid or sid > 0xFFFF:
            continue
        stacks = read_u32(handle, ptr + STATUS_CUR_STACKS) or 0
        if stacks > 9999:
            stacks = 0
        max_stacks = read_u32(handle, ptr + STATUS_MAX_STACKS) or 0
        if max_stacks > 9999:
            max_stacks = 0
        initial = read_f32(handle, ptr + STATUS_INITIAL_DUR) or 0
        remaining = read_f32(handle, ptr + STATUS_REMAINING_DUR) or 0
        infinite = (read_u8(handle, ptr + STATUS_INFINITE_FLAG) or 0) != 0
        # 过滤 NaN/Inf
        if math.isnan(remaining) or math.isinf(remaining):
            remaining = 0
        if math.isnan(initial) or math.isinf(initial):
            initial = 0
        # 过滤空槽：非永续且时间都为0
        if not infinite and remaining <= 0.01 and initial <= 0.01:
            continue
        result[sid] = {
            "stacks": stacks,
            "max_stacks": max_stacks,
            "initial": initial,
            "remaining": remaining,
            "infinite": infinite,
        }
    return result


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

    all_buffs = read_exstatus_buffs(handle, read_base)
    pl_id = _pl_hash_map.get(charid_hash)
    if not pl_id and char_type in CHAR_TYPE_TO_PL:
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
                    "index": idx, "zh":  bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"],
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
                    "index": idx, "zh": bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"],
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
                    "index": idx, "zh": bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"],
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
                    "index": idx, "zh": bc["zh"], "zh_tw": bc.get("zh_tw", bc["zh"]), "en": bc["en"],
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


def _resolve_gauge_addr(handle, actor, src, locked):
    """解析单个 raw_source 目标地址；返回 (addr, new_locked, ok)。"""
    kind = src.get("kind")
    if kind == "class_state":
        P = read_u64(handle, actor + src.get("ptr_off", CLASS_STATE_PTR_OFF))
        if not P:
            return 0, locked, False
        # 倒计时(剩余秒) 经实机验证为直接相对 actor 的 f32 @0xCAAC（非 P+dur_off）
        return actor + CLASS_DURATION_DIRECT_OFF, locked, True  # 返回 duration 地址；调用处同时读 rank
    if kind == "id_direct":
        addr = actor + src.get("off", 0)
        return addr, addr,  True
    return 0, locked, False


def read_raw_buffs(handle, actor, profile, locked_addrs=None, prev_actor=0, all_buffs=None):
    """读取非 ExStatus 的裸值 buff/资源槽。

    locked_addrs: {buff_index: addr}，用于伊德形态切换后保持地址锁定。
    all_buffs: ExStatus 读取结果，用于判断伊德神威一体等生效条件。
    返回 (buffs_out, new_locked_addrs)。
    """
    if not profile:
        return {}, {}
    if locked_addrs is None:
        locked_addrs = {}
    new_locked = dict(locked_addrs)
    out = {}

    # 伊德：龙人态时切到真身 actor 再读
    resolved_actor, is_dragon_form = _resolve_id_actor(handle, actor)
    # 神威一体 buff 是否存在（伊德 status id 0x1E）
    has_overdrive = bool(all_buffs and ID_OVERDRIVE_STATUS_ID in all_buffs)

    for idx, buff_cfg in enumerate(profile.get("buffs", [])):
        src = buff_cfg.get("raw_source")
        if not src:
            continue

        # 条件生效判断
        require = buff_cfg.get("require")
        if require == "dragon_form" and not is_dragon_form:
            continue
        if require == "overdrive" and not has_overdrive:
            continue

        key = idx
        locked = new_locked.get(key, 0)
        addr, locked_new, ok = _resolve_gauge_addr(handle, resolved_actor, src, locked)
        if not ok:
            continue
        new_locked[key] = locked_new
        fmt = src.get("fmt", "f32")
        try:
            if fmt == "u32":
                v = read_u32(handle, addr)
            else:
                v = read_f32(handle, addr)
        except Exception:
            v = None
        if v is None:
            continue
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            v = 0.0

        kind = src.get("kind")
        max_stacks = buff_cfg.get("max_stacks")
        if max_stacks is None:
            max_stacks = 4 if fmt == "f32" else 7

        # 值域校验：明显越界说明链/偏移不对，放弃本次读取
        if kind != "class_state":
            if fmt == "f32":
                if v < -0.01 or v > max(max_stacks * 1.5, 1.0) + 0.1:
                    continue
            elif fmt == "u32":
                if v > max(max_stacks, 4) + 2:
                    continue

        stacks = 0
        timer = None
        timer_max = None
        gauge_value = None

        if kind == "class_state":
            P = read_u64(handle, resolved_actor + src.get("ptr_off", CLASS_STATE_PTR_OFF))
            if P:
                rank = read_u32(handle, P + src.get("rank_off", CLASS_RANK_OFF))
                # 团长 class 层数游戏内为 1~4，但内存值为 0~3，需要 +1
                stacks = (rank or 0) + 1
                # 倒计时(剩余秒) 经实机验证为直接相对 actor 的 f32 @0xCAAC
                dur = read_f32(handle, resolved_actor + CLASS_DURATION_DIRECT_OFF)
                if dur is not None and not math.isnan(dur) and not math.isinf(dur) and dur > 0:
                    timer = dur
                    timer_max = dur  # 首次读到即作为最大值参考
        elif fmt == "u32":
            stacks = int(v)
        elif fmt == "f32":
            gauge_value = v
            # 浮点槽：stacks 取整部分用于尖刺数量；满层阈值用 0.99
            stacks = int(v)

        out[idx] = {
            "index": idx,
            "zh": buff_cfg.get("zh", ""),
            "zh_tw": buff_cfg.get("zh_tw", buff_cfg.get("zh", "")),
            "en": buff_cfg.get("en", ""),
            "stacks": stacks,
            "max_stacks": max_stacks,
            "timer": timer,
            "timer_max": timer_max,
            "timer_display": buff_cfg.get("timer_display", "any_stack"),
            "single_layer": bool(buff_cfg.get("single_layer", False)),
            "gauge_mode": buff_cfg.get("gauge_mode"),
            "gauge_value": gauge_value,
        }
    return out, new_locked


def read_skill_cooldowns(handle, char_base):
    if not char_base:
        return []
    ab_hashes = [0, 0, 0, 0]
    try:
        ab_bytes = rpm(handle, char_base + ABILITY_HASH_OFFSET, 16)
        if ab_bytes and len(ab_bytes) >= 16:
            ab_hashes = list(struct.unpack("<4I", ab_bytes))
    except Exception:
        pass
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


# ============================ Color fields (ordered for settings dialog) ============================
COLOR_FIELDS = [
    ("title_bar_color", "标题栏色:"),
    ("circle_color_normal", "圆环色(正常):"),
    ("circle_color_lv7", "圆环色(满层):"),
    ("spike_color_normal", "尖刺色(正常):"),
    ("spike_color_lv7", "尖刺色(满层):"),
    ("arc_color", "倒计时弧颜色:"),
    ("text_color", "层数数字色:"),
    ("dh_text_outline_color", "层数数字勾边色:"),
    ("text_color_timer", "层数数字色 — (计时版):"),
    ("dh_text_outline_color_timer", "层数数字勾边色 — (计时版):"),
    ("timer_text_color", "倒计时文字色:"),
    ("indicator_outline_color", "外描边色:"),
    ("icon_color", "标题UI色:"),
    ("buff_name_color", "Buff名色:"),
    ("skill_cd_color", "能力扇形色:"),
    ("flash_color", "闪光颜色:"),
    ("skill_cd_text_color", "能力倒计时色:"),
    ("skill_cd_name_color", "能力名色:"),
]

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
    "circle_radius": 40,
    "spike_length": 64,
    "spike_axis_pos_percent": 12,
    "spike_width": 25,
    "spike_waist_pos_percent": 31,
    "spike_bead_radius": 3,
    "spike_bead_pos_percent": 9,
    "use_indicator_outline": True,
    "indicator_outline_width": 1,
    "title_bar_color": "#000000",
    "title_bar_color_opacity": 5,
    "titlebar_font_size": 8,
    "circle_color_normal": "#8c00ff",
    "circle_color_normal_opacity": 100,
    "circle_color_lv7": "#dd2e28",
    "circle_color_lv7_opacity": 100,
    "spike_color_normal": "#8c00ff",
    "spike_color_normal_opacity": 100,
    "spike_color_lv7": "#dd2e28",
    "spike_color_lv7_opacity": 100,
    "arc_color": "#55ff00",
    "arc_color_opacity": 80,
    "text_color": "#ffffff",
    "text_color_opacity": 100,
    "dh_text_outline_color": "#8c00ff",
    "dh_text_outline_color_opacity": 50,
    "timer_text_color": "#ffee88",
    "timer_text_color_opacity": 100,
    "indicator_outline_color": "#ffffff",
    "indicator_outline_color_opacity": 60,
    "use_default_dodge_icon": True,
    "shrimp_img_path": "",
    "dodge_icon_scale_percent": 100,
    "timer_style": "sector",
    "timer_arc_radius_offset": 4,
    "dh_font_size": 34,
    "timer_font_size": 9,
    # ── 各模块独立缩放（取代旧的全局 ui_scale_percent）──
    "core_scale_percent": 100,
    "roll_scale_percent": 100,
    "skill_scale_percent": 100,
    "circle_pad_title": 0,
    # ── 闪光（全局统一·跨模块）──
    "flash_color": "#ffffff",             # 闪光颜色（取代原 skill_cd_ready_color）
    "flash_scale": 140,                   # 闪光放大比例%
    "flash_duration_ms": 400,             # 闪光动画时长ms
    "flash_apply_spikes": True,           # 应用：核心检测模块·尖刺闪光（原 spike_flash_on_stack_change）
    "flash_apply_skill_ready": True,      # 应用：能力模块·冷却完成闪光
    "flash_apply_dodge": True,            # 应用：翻滚模块·图标闪光（找 PNG 边界→用 flash_color 不透明填满）
    # ── 翻滚警告牌（V273 五项可调：尺寸/边宽/圆角/边色/面色）──
    "warning_size_scale": 0.68,            # 警告牌相对图标大小（V273 修正3：0.68 缩放）
    "warning_outline_width": 0.24,         # 红边宽度（占 sz 比例；0.24≈旧版 2x）
    "warning_corner_radius": 6,            # 圆角半径（px）
    "warning_outline_color": "#e53935",    # 红边色
    "warning_fill_color": "#ffef00",       # 黄色面
    # ── 翻滚模块布局方向 ──
    "roll_orientation": "horizontal",     # horizontal / vertical
    # ── 各模块独立屏幕位置（取代旧的 shrimp_gap_circle / 分割线 相对定位）──
    "core_window_x": 424,
    "core_window_y": 696,
    "roll_window_x": 620,
    "roll_window_y": 770,
    "skill_window_x": 300,
    "skill_window_y": 770,
    "ex_status_offset": ACTOR_EX_STATUS,
    "center_text_offset_x": 0,
    "center_text_offset_y": 2,
    "dh_text_outline_width": 3,
    # 有计时版层数数字（独立参数）
    "dh_font_size_timer": 30,
    "center_text_offset_x_timer": 1,
    "center_text_offset_y_timer": -4,
    "dh_text_outline_width_timer": 3,
    "text_color_timer": "#ffffff",
    "text_color_timer_opacity": 100,
    "dh_text_outline_color_timer": "#000000",
    "dh_text_outline_color_timer_opacity": 100,
    "icon_color": "#ff55ff",
    "icon_color_opacity": 40,
    "roll_icon_opacity": 100,
    "timer_center_offset_y": 0,
    "auto_focus_minimize": False,
    "resolution_auto_scale": True,
    "lv7_timer_y_offset": 6,
    "lv7_timer_badge_width": 9,
    # ── 单层buff倒计时胶囊（独立样式）──
    "single_timer_y_offset": 6,
    "single_timer_badge_width": 9,
    "single_timer_font_size": 11,
    "single_timer_text_color": "#ffee88",
    "single_timer_text_color_opacity": 100,
    "spike_hide_when_no_buff": True,
    "spike_hidden_opacity": 0,
    "hide_spikes_and_beads": False,
    "out_of_combat_hide": False,
    "out_of_combat_opacity": 0,
    "show_titlebar_status": True,
    "buff_enabled": {
        "PL1100_0": True,
        "PL2400_0": True,
        "PL0700_0": True,
        "PL0800_0": True,
        "PL1900_0": True,
        "PL2300_0": True,
        "PL1700_0": True,
        "PL1700_1": True,
        "PL1600_0": True,
        "PL1800_0": True,
        "PL1000_0": True,
        "PL2100_0": True,
        "PL2200_0": True,
        "PL2200_1": True,
    },
    # buff 顺位：{ "PLxxxx_idx": pos }，1-based 位置（上→下=界面左→右）；缺失=按 profile 默认顺序
    "buff_order": {},
    # 专精门控勾选：{ "PLxxxx_idx": {"awakening":bool,"truth":bool,"secret":bool} }；缺失=用 profile 默认勾选
    "buff_mastery": {},
    # 多buff顺位方向："ltr"=越上面的越靠左（默认），"rtl"=越上面的越靠右
    "buff_order_direction": "ltr",
    # ── 多buff差异化（按同时监测的buff个数 2/3/4/5 分组）──
    # 每组含：缩放% / 圆心水平间距px / 圆心Delta_Y(px) / 外部差异化颜色 / 内部差异化颜色
    # V331 新增：颜色分布模式（uniform=色环均匀/大反差；monochrome=同色系/相近）+ 同色系间距
    "multi_buff_scale_2": 80, "multi_buff_hgap_2": 110, "multi_buff_dy_2": 34,
    "multi_buff_ext_color_2": True, "multi_buff_int_color_2": True,
    "multi_buff_color_mode_2": "uniform", "multi_buff_mono_span_2": 15,
    "multi_buff_scale_3": 70, "multi_buff_hgap_3": 104, "multi_buff_dy_3": 30,
    "multi_buff_ext_color_3": True, "multi_buff_int_color_3": True,
    "multi_buff_color_mode_3": "uniform", "multi_buff_mono_span_3": 15,
    "multi_buff_scale_4": 60, "multi_buff_hgap_4": 98, "multi_buff_dy_4": 26,
    "multi_buff_ext_color_4": True, "multi_buff_int_color_4": True,
    "multi_buff_color_mode_4": "uniform", "multi_buff_mono_span_4": 15,
    "multi_buff_scale_5": 52, "multi_buff_hgap_5": 92, "multi_buff_dy_5": 22,
    "multi_buff_ext_color_5": True, "multi_buff_int_color_5": True,
    "multi_buff_color_mode_5": "uniform", "multi_buff_mono_span_5": 15,
    "show_buff_name": False,
    "buff_name_font_size": 8,
    "buff_name_offset_x": 0,
    "buff_name_offset_y": -4,
    "buff_name_bg_width": -4,
    "buff_name_color": "#ff0000",
    "buff_name_color_opacity": 80,
    # ── 三模块显示开关（未勾选时该模块内容不透明度归 0；核心模块标题栏始终显示）──
    "show_core_module": True,
    "show_roll_module": True,
    "show_skill_cd_module": True,
    # ── 技能冷却 (Cooldown Indicator) ──
    "skill_cd_size": 24,
    "skill_cd_spread": 90,
    "skill_cd_color": "#55aaff",
    "skill_cd_color_opacity": 70,
    "skill_cd_capsule_bg": "#0a0e1a",
    "skill_cd_capsule_border": "#55aaff",
    "skill_cd_text_color": "#ffffff",
    "skill_cd_text_color_opacity": 100,
    "skill_cd_show_name": True,
    "skill_cd_name_font_size": 7,
    "skill_cd_name_offset_x": 0,
    "skill_cd_name_offset_y": 0,
    "skill_cd_name_bg_width": 0,
    "skill_cd_font_size": 12,
    "skill_cd_capsule_width": 0,
    "skill_cd_timer_offset_x": 0,
    "skill_cd_timer_offset_y": 0,
    "skill_cd_name_color": "#aaccff",
    "skill_cd_name_color_opacity": 80,
    # 能力槽各元素不透明度（百分比 0-100；内部绘制时再换算为 alpha=opacity*255/100）
    "skill_cd_bg_opacity": 16,
    "skill_cd_sector_opacity": 53,
    "skill_cd_border_opacity": 71,
    "skill_cd_capsule_opacity": 63,
    # 菱形边框粗细倍数（相对原粗细，1.0=不变；用户要求就绪提示边框更粗 → 默认 1.35）
    "skill_cd_border_scale": 1.35,
    # 就绪呼吸光（冷却完毕提示）：仅在能力 ready 时绘制
    "skill_cd_breath_enabled": True,        # 开关
    "skill_cd_breath_color": "#ffcc00",     # 光颜色（默认金色，高对比度）
    "skill_cd_breath_color_opacity": 90,    # 峰值不透明度%
    "skill_cd_breath_freq": 0.5,            # 呼吸频率（Hz，每秒呼吸次数）
    "skill_cd_breath_soft": 1.0,            # 柔和程度（0.0~3.0，越大越扩散柔和；0=最紧致）
    "skill_cd_breath_scale": 1.0,           # 放大倍数（0.5~3.0，呼吸灯半宽 = s*scale*0.6）
    "skill_cooldown_max": {},
    # 团长/古兰/姬塔 Class 倒计时上限（纯运行时自动学习；默认 0 表示未学，首帧 reader 兜底用 30）
    "class_duration_max": 0.0,
    # 巴萨拉卡古洛诺斯槽保持上限（运行时学习）
    "kronos_freeze_max": 10.0,
    # ── 在线更新检测 ──
    "auto_check_update": True,      # 启动/定时自动检查更新
    "skip_version": "",             # 跳过的版本号（不再提示）
    "update_check_url": "https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases/latest/download/version.json",  # release CDN（国内快速）；不走 raw（被墙/慢）
    "update_download_url": "",        # exe 下载地址（检查更新后从 version.json 的 download_url 自动填入，可手填覆盖）
    # ── 全局快捷键（最多 3 键组合；Ctrl 不再强制，仅默认 Ctrl+K）──
    # V331 起改为逐项勾选；global_hotkey_enabled 总开关废弃，仅作旧版迁移兼容。
    "global_hotkey_show_enabled": True,    # 呼出/隐藏所有窗口 是否启用
    "global_hotkey_show": "17,75",         # 呼出/隐藏所有窗口（默认 Ctrl+K，VK 十进制逗号分隔）
    "global_hotkey_lock_enabled": False,   # 锁定/解锁窗口 是否启用
    "global_hotkey_lock": "",              # 锁定/解锁窗口（空 = 未设置）
    "global_hotkey_settings_enabled": False, # 打开设置 是否启用
    "global_hotkey_settings": "",          # 打开设置（空 = 未设置）
    "global_hotkey_key": "k",              # [已废弃]旧版单字母，仅供迁移兼容
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
                    pass
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
                            pass
                new_map[k] = v
            if migrated:
                data["buff_enabled"] = new_map
        # 由 buff_enabled 推导 buff_order（rank: 1-based, 0=不显示），兼容老存档与默认
        if "buff_enabled" in data and "buff_order" not in data:
            order = {}
            for k, v in data["buff_enabled"].items():
                if isinstance(k, str) and "_" in k:
                    pl_id, idx_s = k.rsplit("_", 1)
                    try:
                        idx = int(idx_s)
                    except ValueError:
                        continue
                    order[k] = (idx + 1) if v else 0
            data["buff_order"] = order
        # 删除已废弃的 Class 倒计时「手动」上限键（V342 起移除手动输入框；自动学习键 class_duration_max 保留）
        data.pop("class_duration_manual", None)

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
                    pass
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
        pass


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
            lbl.setMinimumWidth(86); lbl.setMaximumWidth(100)
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
            cb.setMinimumWidth(86); cb.setMaximumWidth(100)
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
        # 先同步全局语言：构造过程中任何异常弹窗都必须用用户当前语言
        global _CURRENT_LANG
        _CURRENT_LANG = settings.get("language", "zh")
        self.setWindowTitle(_tr("Overlay 设置") + f" v{APP_VERSION}")
        self.setMinimumWidth(1120)
        self.setMaximumHeight(760)
        self.resize(1120, 760)
        self.settings = dict(settings)
        self.ctrl = ctrl
        self.color_buttons = {}
        self.opacity_spins = {}
        self._top_tabs_zh = []
        self._sub_tabs = []
        self.setStyleSheet(
            "QDialog{background:#1a2030;color:#dbe7ff;}"
            "QLabel{color:#aab6d0;}"
            "QLineEdit,QSpinBox,QComboBox{background:#242c40;color:#fff;border:1px solid #3a4860;padding:3px;border-radius:4px;}"
            "QPushButton{background:#2a3450;color:#fff;border:1px solid #3a4860;padding:5px 15px;border-radius:4px;}"
            "QPushButton:hover{background:#3a4860;}"
            "QCheckBox{color:#ffffff; spacing:8px;}"
            "QCheckBox::indicator{width:18px;height:18px;border-radius:5px;border:2px solid #60708c;background:#1a2030;}"
            "QCheckBox::indicator:hover{border-color:#9a7bff;}"
            "QCheckBox::indicator:checked{background:#8c00ff;border:2px solid #c8a6ff;}"
            "QCheckBox::indicator:unchecked{background:#1a2030;border:2px solid #60708c;}"
            "QSpinBox::up-button,QSpinBox::down-button{width:0px;border:none;}"
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
            xs = QSpinBox(); xs.setRange(-99999, 99999); xs.setPrefix("X "); xs.setValue(int(self.settings.get(x_key, 0)))
            ys = QSpinBox(); ys.setRange(-99999, 99999); ys.setPrefix("Y "); ys.setValue(int(self.settings.get(y_key, 0)))
            xs.valueChanged.connect(self._emit_changed)
            ys.valueChanged.connect(self._emit_changed)
            row.addWidget(xs); row.addWidget(ys)
            c = QWidget(); c.setLayout(row)
            cf_local.addRow("模块位置:", c)
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
        g_sub = make_top_tab("全局")
        # 常规
        f = make_sub_tab(g_sub, "常规")
        card, cf = make_card(f, "── 常规 ──")
        self.lang = QComboBox()
        self.lang.addItems(["zh", "zh_tw", "en"])
        self.lang.setCurrentText(self.settings.get("language", "zh"))
        cf.addRow("语言 / Language:", self.lang)
        self.auto_focus_minimize = QCheckBox("游戏在前台时显示，切到后台时自动最小化")
        self.auto_focus_minimize.setChecked(bool(self.settings.get("auto_focus_minimize", DEFAULT_SETTINGS["auto_focus_minimize"])))
        cf.addRow("随游戏前后台:", self.auto_focus_minimize)
        self.resolution_auto_scale = QCheckBox("按当前屏幕宽度自动放大")
        self.resolution_auto_scale.setChecked(bool(self.settings.get("resolution_auto_scale", DEFAULT_SETTINGS["resolution_auto_scale"])))
        cf.addRow("随分辨率放大:", self.resolution_auto_scale)
        self.ooc_hide_chk = QCheckBox("未进入战斗时隐藏整个UI（尖刺圆/翻滚/技能UI 全部）")
        self.ooc_hide_chk.setChecked(bool(self.settings.get("out_of_combat_hide", DEFAULT_SETTINGS["out_of_combat_hide"])))
        cf.addRow("非战斗隐藏:", self.ooc_hide_chk)
        self.ooc_op_spn = QSpinBox()
        self.ooc_op_spn.setRange(0, 100)
        self.ooc_op_spn.setSuffix("%")
        self.ooc_op_spn.setValue(int(self.settings.get("out_of_combat_opacity", DEFAULT_SETTINGS["out_of_combat_opacity"])))
        cf.addRow("隐藏时透明度:", self.ooc_op_spn)
        f.addRow(card)
        # 扫描 / 内存
        card, cf = make_card(f, "── 扫描 / 内存 ──")
        self.scan = QSpinBox(); self.scan.setRange(10, 500); self.scan.setValue(int(self.settings.get("scan_ms", DEFAULT_SETTINGS["scan_ms"])))
        cf.addRow("扫描周期 (ms):", self.scan)
        self.ex_status_offset_spin = QSpinBox(); self.ex_status_offset_spin.setRange(0, 0xFFFF); self.ex_status_offset_spin.setPrefix("0x"); self.ex_status_offset_spin.setDisplayIntegerBase(16)
        self.ex_status_offset_spin.setValue(int(self.settings.get("ex_status_offset", ACTOR_EX_STATUS)))
        cf.addRow("ExStatus偏移:", self.ex_status_offset_spin)
        f.addRow(card)
        # 模块显示（三模块勾选；未勾选时该模块内容不透明度归 0，核心模块标题栏始终显示）
        card, cf = make_card(f, "── 模块显示 ──")
        self.show_core_module_chk = QCheckBox("核心检测模块（标题栏始终显示，仅内容隐藏）")
        self.show_core_module_chk.setChecked(bool(self.settings.get("show_core_module", True)))
        cf.addRow(self.show_core_module_chk)
        self.show_roll_module_chk = QCheckBox("翻滚模块")
        self.show_roll_module_chk.setChecked(bool(self.settings.get("show_roll_module", True)))
        cf.addRow(self.show_roll_module_chk)
        self.show_skill_module_chk = QCheckBox("能力冷却模块")
        self.show_skill_module_chk.setChecked(bool(self.settings.get("show_skill_cd_module", True)))
        cf.addRow(self.show_skill_module_chk)
        f.addRow(card)
        # 全局快捷键（移回全局-常规标签）
        card, cf = make_card(f, "── 全局快捷键 ──")
        # 三个热键：呼出/隐藏、锁定解锁、打开设置，每项独立勾选框
        self._build_hotkey_row(cf, "hk_show", "呼出/隐藏所有窗口", "global_hotkey_show", "17,75",
                               "global_hotkey_show_enabled", True)
        self._build_hotkey_row(cf, "hk_lock", "锁定 / 解锁窗口", "global_hotkey_lock", "",
                               "global_hotkey_lock_enabled", False)
        self._build_hotkey_row(cf, "hk_settings", "打开设置", "global_hotkey_settings", "",
                               "global_hotkey_settings_enabled", False)
        f.addRow(card)
        # 闪光（全局统一·跨模块）
        f = make_sub_tab(g_sub, "闪光")
        card, cf = make_card(f, "── 闪光 ──")
        self._add_color_row(cf, "flash_color", "闪光颜色:", with_opacity=False)
        self.flash_scale_spn = QSpinBox(); self.flash_scale_spn.setRange(100, 300); self.flash_scale_spn.setValue(int(self.settings.get("flash_scale", DEFAULT_SETTINGS["flash_scale"])))
        cf.addRow("放大比例%:", self.flash_scale_spn)
        self.flash_dur_spn = QSpinBox(); self.flash_dur_spn.setRange(100, 2000); self.flash_dur_spn.setSingleStep(50); self.flash_dur_spn.setValue(int(self.settings.get("flash_duration_ms", DEFAULT_SETTINGS["flash_duration_ms"])))
        cf.addRow("动画时长ms:", self.flash_dur_spn)
        f.addRow(card)
        card, cf = make_card(f, "── 闪光应用模块 ──")
        self.flash_apply_spikes_chk = QCheckBox("尖刺闪光（核心检测模块）")
        self.flash_apply_spikes_chk.setChecked(bool(self.settings.get("flash_apply_spikes", DEFAULT_SETTINGS["flash_apply_spikes"])))
        cf.addRow(self.flash_apply_spikes_chk)
        self.flash_apply_skill_ready_chk = QCheckBox("能力冷却完成闪光")
        self.flash_apply_skill_ready_chk.setChecked(bool(self.settings.get("flash_apply_skill_ready", DEFAULT_SETTINGS["flash_apply_skill_ready"])))
        cf.addRow(self.flash_apply_skill_ready_chk)
        self.flash_apply_dodge_chk = QCheckBox("翻滚图标闪光")
        self.flash_apply_dodge_chk.setChecked(bool(self.settings.get("flash_apply_dodge", DEFAULT_SETTINGS["flash_apply_dodge"])))
        cf.addRow(self.flash_apply_dodge_chk)
        f.addRow(card)

        # ============ 顶级标签 2: 核心检测模块 ============
        c_sub = make_top_tab("核心检测模块")
        # Buff启用/禁用 + 顺位（放在核心检测模块最前面）
        f = make_sub_tab(c_sub, "Buff启用/禁用")
        lang = self.settings.get("language", "zh")
        card, cf = make_card(f, "── 角色 Buff 顺位与专精门控（每行三勾选框 = 觉醒/真谛/秘义 / 拖动排序 / 可折叠） ──")
        # 全局按钮 + 说明文字
        buff_btn_row = QHBoxLayout(); buff_btn_row.setContentsMargins(0, 0, 0, 0); buff_btn_row.setSpacing(8)
        self.buff_btn_all = QPushButton("全勾选"); self.buff_btn_none = QPushButton("全取消")
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
            self.buff_order_direction_combo.addItem("越上越靠左", "ltr")
            self.buff_order_direction_combo.addItem("越上越靠右", "rtl")
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
        f = make_sub_tab(c_sub, "标题栏")
        card, cf = make_card(f, "── 标题栏 ──")
        self.show_titlebar_status = QCheckBox("在标题栏显示角色名和buff状态文字")
        self.show_titlebar_status.setChecked(bool(self.settings.get("show_titlebar_status", DEFAULT_SETTINGS["show_titlebar_status"])))
        cf.addRow("标题栏状态文字:", self.show_titlebar_status)
        self.titlebar_font_size_spn = QSpinBox(); self.titlebar_font_size_spn.setRange(6, 32); self.titlebar_font_size_spn.setSuffix("px"); self.titlebar_font_size_spn.setValue(int(self.settings.get("titlebar_font_size", DEFAULT_SETTINGS["titlebar_font_size"])))
        cf.addRow("标题栏字体大小:", self.titlebar_font_size_spn)
        self._add_color_row(cf, "title_bar_color", "标题栏色:")
        self._add_color_row(cf, "icon_color", "标题UI色:")
        self.circle_pad_title = QSpinBox(); self.circle_pad_title.setRange(0, 999); self.circle_pad_title.setValue(int(self.settings.get("circle_pad_title", DEFAULT_SETTINGS["circle_pad_title"])))
        cf.addRow("标题→圆间距:", self.circle_pad_title)
        f.addRow(card)
        # 尖刺与圆环
        f = make_sub_tab(c_sub, "尖刺与圆环")
        card, cf = make_card(f, "── 尖刺(含顶端圆点) ──")
        self.spike_length = QSpinBox(); self.spike_length.setRange(8, 80); self.spike_length.setValue(int(self.settings.get("spike_length", DEFAULT_SETTINGS["spike_length"])))
        cf.addRow("尖刺长度:", self.spike_length)
        self.spike_axis_pos = QSpinBox(); self.spike_axis_pos.setRange(-60, 80); self.spike_axis_pos.setSuffix("%"); self.spike_axis_pos.setValue(int(self.settings.get("spike_axis_pos_percent", DEFAULT_SETTINGS["spike_axis_pos_percent"])))
        cf.addRow("尖刺根部距圆心:", self.spike_axis_pos)
        self.spike_width = QSpinBox(); self.spike_width.setRange(8, 100); self.spike_width.setSuffix("px"); self.spike_width.setValue(int(self.settings.get("spike_width", DEFAULT_SETTINGS["spike_width"])))
        cf.addRow("尖刺宽度:", self.spike_width)
        self.spike_waist_pos = QSpinBox(); self.spike_waist_pos.setRange(5, 95); self.spike_waist_pos.setSuffix("%"); self.spike_waist_pos.setValue(int(self.settings.get("spike_waist_pos_percent", DEFAULT_SETTINGS["spike_waist_pos_percent"])))
        cf.addRow("尖刺腰位置:", self.spike_waist_pos)
        self.spike_bead_radius = QSpinBox(); self.spike_bead_radius.setRange(0, 30); self.spike_bead_radius.setSuffix("px"); self.spike_bead_radius.setValue(int(self.settings.get("spike_bead_radius", DEFAULT_SETTINGS["spike_bead_radius"])))
        cf.addRow("尖刺顶端圆点半径:", self.spike_bead_radius)
        self.spike_bead_pos = QSpinBox(); self.spike_bead_pos.setRange(-60, 80); self.spike_bead_pos.setSuffix("%"); self.spike_bead_pos.setValue(int(self.settings.get("spike_bead_pos_percent", DEFAULT_SETTINGS["spike_bead_pos_percent"])))
        cf.addRow("顶端圆点距圆心:", self.spike_bead_pos)
        self._add_color_row(cf, "spike_color_normal", "尖刺色(正常):")
        self._add_color_row(cf, "spike_color_lv7", "尖刺色(满层):")
        self.hide_spikes_beads_chk = QCheckBox(_tr("隐藏尖刺与装饰小球（仅保留圆环+倒计时+文字）"))
        self.hide_spikes_beads_chk.setChecked(bool(self.settings.get("hide_spikes_and_beads", DEFAULT_SETTINGS["hide_spikes_and_beads"])))
        cf.addRow(self.hide_spikes_beads_chk)
        f.addRow(card)
        card, cf = make_card(f, "── 圆环 ──")
        self.circle_radius = QSpinBox(); self.circle_radius.setRange(30, 120); self.circle_radius.setValue(int(self.settings.get("circle_radius", DEFAULT_SETTINGS["circle_radius"])))
        cf.addRow("圆半径:", self.circle_radius)
        self._add_color_row(cf, "circle_color_normal", "圆环色(正常):")
        self._add_color_row(cf, "circle_color_lv7", "圆环色(满层):")
        f.addRow(card)
        card, cf = make_card(f, "── 外描边 ──")
        self.indicator_outline_enabled = QCheckBox("启用整体外描边")
        self.indicator_outline_enabled.setChecked(bool(self.settings.get("use_indicator_outline", DEFAULT_SETTINGS["use_indicator_outline"])))
        cf.addRow("整体外描边:", self.indicator_outline_enabled)
        self.indicator_outline_width = QSpinBox(); self.indicator_outline_width.setRange(0, 20); self.indicator_outline_width.setSuffix("px"); self.indicator_outline_width.setValue(int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])))
        cf.addRow("外描边粗细:", self.indicator_outline_width)
        self._add_color_row(cf, "indicator_outline_color", "外描边色:")
        f.addRow(card)
        # 倒计时
        f = make_sub_tab(c_sub, "倒计时")
        card, cf = make_card(f, "── 倒计时弧线 ──")
        self.timer_style = QComboBox(); self.timer_style.addItem("圆环", "ring"); self.timer_style.addItem("扇形", "sector")
        idx = self.timer_style.findData(self.settings.get("timer_style", DEFAULT_SETTINGS["timer_style"])); self.timer_style.setCurrentIndex(max(0, idx))
        cf.addRow("倒计时样式:", self.timer_style)
        self.timer_arc_radius = QSpinBox(); self.timer_arc_radius.setRange(0, 60); self.timer_arc_radius.setValue(int(self.settings.get("timer_arc_radius_offset", DEFAULT_SETTINGS["timer_arc_radius_offset"])))
        cf.addRow("倒计时弧线内缩:", self.timer_arc_radius)
        self.timer_center_y = QSpinBox(); self.timer_center_y.setRange(-50, 50); self.timer_center_y.setValue(int(self.settings.get("timer_center_offset_y", 0)))
        cf.addRow("倒计时圆心Y偏移:", self.timer_center_y)
        self._add_color_row(cf, "arc_color", "倒计时弧颜色:")
        f.addRow(card)
        card, cf = make_card(f, "── 倒计时胶囊 ──")
        self.lv7_timer_y_offset = QSpinBox(); self.lv7_timer_y_offset.setRange(-30, 30); self.lv7_timer_y_offset.setValue(int(self.settings.get("lv7_timer_y_offset", 0)))
        cf.addRow("时间胶囊Y偏移:", self.lv7_timer_y_offset)
        self.lv7_timer_badge_width = QSpinBox(); self.lv7_timer_badge_width.setRange(0, 40); self.lv7_timer_badge_width.setSuffix("px"); self.lv7_timer_badge_width.setValue(int(self.settings.get("lv7_timer_badge_width", DEFAULT_SETTINGS["lv7_timer_badge_width"])))
        cf.addRow("时间胶囊宽度:", self.lv7_timer_badge_width)
        self.timer_font_size = QSpinBox(); self.timer_font_size.setRange(0, 48); self.timer_font_size.setValue(int(self.settings.get("timer_font_size", DEFAULT_SETTINGS["timer_font_size"])))
        cf.addRow("倒计时字体大小:", self.timer_font_size)
        self._add_color_row(cf, "timer_text_color", "倒计时文字色:")
        f.addRow(card)
        card, cf = make_card(f, "── 单层buff倒计时胶囊 ──")
        self.single_timer_y_offset = QSpinBox(); self.single_timer_y_offset.setRange(-30, 30); self.single_timer_y_offset.setValue(int(self.settings.get("single_timer_y_offset", DEFAULT_SETTINGS["single_timer_y_offset"])))
        cf.addRow("时间胶囊Y偏移:", self.single_timer_y_offset)
        self.single_timer_badge_width = QSpinBox(); self.single_timer_badge_width.setRange(0, 40); self.single_timer_badge_width.setSuffix("px"); self.single_timer_badge_width.setValue(int(self.settings.get("single_timer_badge_width", DEFAULT_SETTINGS["single_timer_badge_width"])))
        cf.addRow("时间胶囊宽度:", self.single_timer_badge_width)
        self.single_timer_font_size = QSpinBox(); self.single_timer_font_size.setRange(0, 48); self.single_timer_font_size.setValue(int(self.settings.get("single_timer_font_size", DEFAULT_SETTINGS["single_timer_font_size"])))
        cf.addRow("倒计时字体大小:", self.single_timer_font_size)
        self._add_color_row(cf, "single_timer_text_color", "倒计时文字色:")
        f.addRow(card)
        # 层数数字
        f = make_sub_tab(c_sub, "层数数字")
        card, cf = make_card(f, "── 层数数字(无计时) ──")
        self.center_offset_x = QSpinBox(); self.center_offset_x.setRange(-50, 50); self.center_offset_x.setValue(int(self.settings.get("center_text_offset_x", 0)))
        cf.addRow("层数数字X偏移:", self.center_offset_x)
        self.center_offset_y = QSpinBox(); self.center_offset_y.setRange(-50, 50); self.center_offset_y.setValue(int(self.settings.get("center_text_offset_y", 0)))
        cf.addRow("层数数字Y偏移:", self.center_offset_y)
        self.dh_font_size = QSpinBox(); self.dh_font_size.setRange(14, 72); self.dh_font_size.setValue(int(self.settings.get("dh_font_size", DEFAULT_SETTINGS["dh_font_size"])))
        cf.addRow("层数数字大小:", self.dh_font_size)
        self.dh_text_outline_width = QSpinBox(); self.dh_text_outline_width.setRange(0, 12); self.dh_text_outline_width.setValue(int(self.settings.get("dh_text_outline_width", DEFAULT_SETTINGS["dh_text_outline_width"])))
        cf.addRow("层数数字勾边粗细:", self.dh_text_outline_width)
        self._add_color_row(cf, "text_color", "层数数字色:")
        self._add_color_row(cf, "dh_text_outline_color", "层数数字勾边色:")
        f.addRow(card)
        card, cf = make_card(f, "── 层数数字(有计时) ──")
        self.center_offset_x_timer = QSpinBox(); self.center_offset_x_timer.setRange(-50, 50); self.center_offset_x_timer.setValue(int(self.settings.get("center_text_offset_x_timer", 0)))
        cf.addRow("层数数字X偏移 — (计时版):", self.center_offset_x_timer)
        self.center_offset_y_timer = QSpinBox(); self.center_offset_y_timer.setRange(-50, 50); self.center_offset_y_timer.setValue(int(self.settings.get("center_text_offset_y_timer", 0)))
        cf.addRow("层数数字Y偏移 — (计时版):", self.center_offset_y_timer)
        self.dh_font_size_timer = QSpinBox(); self.dh_font_size_timer.setRange(14, 72); self.dh_font_size_timer.setValue(int(self.settings.get("dh_font_size_timer", DEFAULT_SETTINGS["dh_font_size_timer"])))
        cf.addRow("层数数字大小 — (计时版):", self.dh_font_size_timer)
        self.dh_text_outline_width_timer = QSpinBox(); self.dh_text_outline_width_timer.setRange(0, 12); self.dh_text_outline_width_timer.setValue(int(self.settings.get("dh_text_outline_width_timer", DEFAULT_SETTINGS["dh_text_outline_width_timer"])))
        cf.addRow("层数数字勾边粗细 — (计时版):", self.dh_text_outline_width_timer)
        self._add_color_row(cf, "text_color_timer", "层数数字色 — (计时版):")
        self._add_color_row(cf, "dh_text_outline_color_timer", "层数数字勾边色 — (计时版):")
        f.addRow(card)
        # 多buff差异化（按同时监测的buff个数 2/3/4/5 分组，每组 5 参数 = 20）
        f = make_sub_tab(c_sub, "多buff布局")
        card, cf = make_card(f, "── 多buff差异化（按同时监测的buff个数 2/3/4/5；每组：缩放 / 圆心水平间距 / 圆心Delta_Y / 外部差异化颜色 / 内部差异化颜色） ──")

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
                gcf, "缩放{}:", f"multi_buff_scale_{cnt}", DEFAULT_SETTINGS[f"multi_buff_scale_{cnt}"], 20, 100, "%")
            ctrl["hgap_sl"], ctrl["hgap_sp"], self.multi_buff_labels[(cnt, "hgap")] = _mb_slider(
                gcf, "圆心水平间距{}:", f"multi_buff_hgap_{cnt}", DEFAULT_SETTINGS[f"multi_buff_hgap_{cnt}"], 20, 400, "px")
            ctrl["dy_sl"], ctrl["dy_sp"], self.multi_buff_labels[(cnt, "dy")] = _mb_slider(
                gcf, "圆心Delta_Y{}:", f"multi_buff_dy_{cnt}", DEFAULT_SETTINGS[f"multi_buff_dy_{cnt}"], -300, 300, "px")
            ctrl["ext_cb"], self.multi_buff_labels[(cnt, "ext_color")] = _mb_check(
                gcf, "外部差异化颜色{}:", f"multi_buff_ext_color_{cnt}", DEFAULT_SETTINGS[f"multi_buff_ext_color_{cnt}"])
            ctrl["int_cb"], self.multi_buff_labels[(cnt, "int_color")] = _mb_check(
                gcf, "内部差异化颜色{}:", f"multi_buff_int_color_{cnt}", DEFAULT_SETTINGS[f"multi_buff_int_color_{cnt}"])
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
                gcf, "同色系间距{}:", f"multi_buff_mono_span_{cnt}",
                DEFAULT_SETTINGS[f"multi_buff_mono_span_{cnt}"], 0, 60, "°")
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
        f = make_sub_tab(c_sub, "Buff名字")
        card, cf = make_card(f)
        self.show_buff_name_cb = QCheckBox("在画布上显示Buff名称")
        self.show_buff_name_cb.setChecked(bool(self.settings.get("show_buff_name", DEFAULT_SETTINGS["show_buff_name"]))); cf.addRow("Buff名显示:", self.show_buff_name_cb)
        self.buff_name_font_size = QSpinBox(); self.buff_name_font_size.setRange(1, 48); self.buff_name_font_size.setSuffix(" px"); self.buff_name_font_size.setValue(int(self.settings.get("buff_name_font_size", DEFAULT_SETTINGS["buff_name_font_size"])))
        cf.addRow("Buff名字体大小:", self.buff_name_font_size)
        name_pos_row = QHBoxLayout(); name_pos_row.setContentsMargins(0, 0, 0, 0); name_pos_row.setSpacing(8)
        self.buff_name_offset_x = QSpinBox(); self.buff_name_offset_x.setRange(-200, 200); self.buff_name_offset_x.setPrefix("X "); self.buff_name_offset_x.setValue(int(self.settings.get("buff_name_offset_x", DEFAULT_SETTINGS["buff_name_offset_x"])))
        self.buff_name_offset_y = QSpinBox(); self.buff_name_offset_y.setRange(-200, 200); self.buff_name_offset_y.setPrefix("Y "); self.buff_name_offset_y.setValue(int(self.settings.get("buff_name_offset_y", DEFAULT_SETTINGS["buff_name_offset_y"])))
        name_pos_row.addWidget(self.buff_name_offset_x); name_pos_row.addWidget(self.buff_name_offset_y)
        name_pos_container = QWidget(); name_pos_container.setLayout(name_pos_row); cf.addRow("Buff名位置:", name_pos_container)
        self.buff_name_bg_width = QSpinBox(); self.buff_name_bg_width.setRange(-100, 100); self.buff_name_bg_width.setSuffix(" px"); self.buff_name_bg_width.setValue(int(self.settings.get("buff_name_bg_width", DEFAULT_SETTINGS["buff_name_bg_width"])))
        cf.addRow("Buff名衬色块宽度微调:", self.buff_name_bg_width)
        self._add_color_row(f, "buff_name_color", "Buff名色:")
        f.addRow(card)
        # 隐藏与位置
        f = make_sub_tab(c_sub, "位置与隐藏")
        card, cf = make_card(f, "── 隐藏 ──")
        self.spike_hide_chk = QCheckBox("无buff时隐藏尖刺圆模块（翻滚/技能UI不受影响）")
        self.spike_hide_chk.setChecked(bool(self.settings.get("spike_hide_when_no_buff", DEFAULT_SETTINGS["spike_hide_when_no_buff"])))
        cf.addRow(self.spike_hide_chk)
        self.spike_hidden_op_spn = QSpinBox(); self.spike_hidden_op_spn.setRange(0, 100); self.spike_hidden_op_spn.setSuffix("%"); self.spike_hidden_op_spn.setValue(int(self.settings.get("spike_hidden_opacity", DEFAULT_SETTINGS["spike_hidden_opacity"])))
        cf.addRow("隐藏时透明度:", self.spike_hidden_op_spn)
        f.addRow(card)
        # 核心模块位置与缩放（从原“模块位置”顶级标签迁入）
        card, cf = make_card(f, "── 核心模块位置与缩放 ──")
        self.core_x_spn, self.core_y_spn = _mk_pos_row(cf, "core_window_x", "core_window_y")
        self.core_scale_slider, self.core_scale_spin = _mk_scale_row(cf, "core", "模块缩放:")
        f.addRow(card)
        # ============ 顶级标签 3: 翻滚模块 ============
        r_sub = make_top_tab("翻滚模块")
        f = make_sub_tab(r_sub, "翻滚图标")
        card, cf = make_card(f, "── 翻滚图标 ──")
        self.icon_use_default = QCheckBox("使用内置默认图标")
        self.icon_use_default.setChecked(bool(self.settings.get("use_default_dodge_icon", DEFAULT_SETTINGS["use_default_dodge_icon"])))
        cf.addRow("默认图标:", self.icon_use_default)
        icon_row = QHBoxLayout(); icon_row.setContentsMargins(0, 0, 0, 0); icon_row.setSpacing(8)
        self.icon_path = QLineEdit(self.settings.get("shrimp_img_path", DEFAULT_SETTINGS["shrimp_img_path"]))
        self.browse_icon_btn = QPushButton("浏览..."); self.browse_icon_btn.setAutoDefault(False); self.browse_icon_btn.setDefault(False); self.browse_icon_btn.setFixedWidth(80)
        self.browse_icon_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_path); icon_row.addWidget(self.browse_icon_btn)
        icon_container = QWidget(); icon_container.setLayout(icon_row); cf.addRow("翻滚图标绝对路径:", icon_container)
        self._sync_icon_default_enabled()
        self.icon_scale = QSpinBox(); self.icon_scale.setRange(10, 400); self.icon_scale.setSuffix("%"); self.icon_scale.setValue(int(self.settings.get("dodge_icon_scale_percent", DEFAULT_SETTINGS["dodge_icon_scale_percent"])))
        cf.addRow("翻滚图标缩放:", self.icon_scale)
        self.roll_icon_opacity_spin = QSpinBox(); self.roll_icon_opacity_spin.setRange(0, 100); self.roll_icon_opacity_spin.setSuffix("%"); self.roll_icon_opacity_spin.setValue(int(self.settings.get("roll_icon_opacity", DEFAULT_SETTINGS["roll_icon_opacity"])))
        cf.addRow("翻滚图标不透明度:", self.roll_icon_opacity_spin)
        self.roll_orientation_combo = QComboBox(); self.roll_orientation_combo.addItem("横放", "horizontal"); self.roll_orientation_combo.addItem("竖放", "vertical")
        roidx = self.roll_orientation_combo.findData(self.settings.get("roll_orientation", DEFAULT_SETTINGS["roll_orientation"])); self.roll_orientation_combo.setCurrentIndex(max(0, roidx))
        cf.addRow("翻滚朝向:", self.roll_orientation_combo)
        f.addRow(card)
        # ── 翻滚警告牌（V273 五项可调）──
        card, cf = make_card(f, "── 翻滚警告牌（第6/7次）──")
        self.warning_size_sld, self.warning_size_spn, _ = _mb_slider(cf, "警告牌相对尺寸:", "warning_size_scale", int(DEFAULT_SETTINGS["warning_size_scale"] * 100), 30, 100, "%", value_scale=100)
        self.warning_bw_sld, self.warning_bw_spn, _ = _mb_slider(cf, "红边宽度占比:", "warning_outline_width", int(DEFAULT_SETTINGS["warning_outline_width"] * 100), 10, 50, "%", value_scale=100)
        self.warning_corner_spn = QSpinBox(); self.warning_corner_spn.setRange(0, 30); self.warning_corner_spn.setSuffix(" px"); self.warning_corner_spn.setValue(int(self.settings.get("warning_corner_radius", DEFAULT_SETTINGS["warning_corner_radius"])))
        cf.addRow("圆角半径:", self.warning_corner_spn)
        self._add_color_row(cf, "warning_outline_color", "红边色:", with_opacity=False)
        self._add_color_row(cf, "warning_fill_color", "黄色面:", with_opacity=False)
        f.addRow(card)
        # 翻滚模块位置与缩放（从原“模块位置”顶级标签迁入）
        f = make_sub_tab(r_sub, "位置与缩放")
        card, cf = make_card(f, "── 翻滚模块位置与缩放 ──")
        self.roll_x_spn, self.roll_y_spn = _mk_pos_row(cf, "roll_window_x", "roll_window_y")
        self.roll_scale_slider, self.roll_scale_spin = _mk_scale_row(cf, "roll", "模块缩放:")
        f.addRow(card)
        # ============ 顶级标签 4: 能力模块 ============
        s_sub = make_top_tab("能力模块")
        f = make_sub_tab(s_sub, "能力冷却")
        card, cf = make_card(f, "── 能力冷却 ──")
        self.skill_cd_size_spn = QSpinBox(); self.skill_cd_size_spn.setRange(10, 80); self.skill_cd_size_spn.setValue(int(self.settings.get("skill_cd_size", 18)))
        cf.addRow("方形大小:", self.skill_cd_size_spn)
        self.skill_cd_spread_spn = QSpinBox(); self.skill_cd_spread_spn.setRange(20, 200); self.skill_cd_spread_spn.setValue(int(self.settings.get("skill_cd_spread", 70)))
        cf.addRow("聚散距离:", self.skill_cd_spread_spn)
        self.skill_cd_font_size_spn = QSpinBox(); self.skill_cd_font_size_spn.setRange(6, 40); self.skill_cd_font_size_spn.setValue(int(self.settings.get("skill_cd_font_size", 12)))
        cf.addRow("倒计时字号:", self.skill_cd_font_size_spn)
        self.skill_cd_capsule_w_spn = QSpinBox(); self.skill_cd_capsule_w_spn.setRange(-60, 60); self.skill_cd_capsule_w_spn.setValue(int(self.settings.get("skill_cd_capsule_width", 0))); self.skill_cd_capsule_w_spn.setSpecialValueText("不微调")
        cf.addRow("胶囊宽度微调(Δ):", self.skill_cd_capsule_w_spn)
        self.skill_cd_timer_offx_spn = QSpinBox(); self.skill_cd_timer_offx_spn.setRange(-100, 100); self.skill_cd_timer_offx_spn.setValue(int(self.settings.get("skill_cd_timer_offset_x", 0)))
        cf.addRow("倒计时X偏移:", self.skill_cd_timer_offx_spn)
        self.skill_cd_timer_offy_spn = QSpinBox(); self.skill_cd_timer_offy_spn.setRange(-100, 100); self.skill_cd_timer_offy_spn.setValue(int(self.settings.get("skill_cd_timer_offset_y", 0)))
        cf.addRow("倒计时Y偏移:", self.skill_cd_timer_offy_spn)
        self.skill_cd_bg_opacity_sl = _mk_opacity_row(cf, "skill_cd_bg_opacity", "背景不透明度:")
        self.skill_cd_sector_opacity_sl = _mk_opacity_row(cf, "skill_cd_sector_opacity", "扇形不透明度:")
        self.skill_cd_border_opacity_sl = _mk_opacity_row(cf, "skill_cd_border_opacity", "边框不透明度:")
        self.skill_cd_border_scale_dspn = QDoubleSpinBox(); self.skill_cd_border_scale_dspn.setRange(0.5, 4.0); self.skill_cd_border_scale_dspn.setSingleStep(0.05); self.skill_cd_border_scale_dspn.setDecimals(2); self.skill_cd_border_scale_dspn.setSuffix("×"); self.skill_cd_border_scale_dspn.setValue(float(self.settings.get("skill_cd_border_scale", 1.35)))
        cf.addRow("边框粗细倍数:", self.skill_cd_border_scale_dspn)
        self.skill_cd_capsule_opacity_sl = _mk_opacity_row(cf, "skill_cd_capsule_opacity", "胶囊不透明度:")
        # 胶囊背景色 / 边框色：复用上方「胶囊不透明度」滑块统一控制透明度（持久化写入 JSON）
        self._add_color_row(cf, "skill_cd_capsule_bg", "胶囊背景色:", with_opacity=False)
        self._add_color_row(cf, "skill_cd_capsule_border", "胶囊边框色:", with_opacity=False)
        self._add_color_row(cf, "skill_cd_color", "扇形颜色:", with_opacity=True)
        self._add_color_row(cf, "skill_cd_text_color", "倒计时文字色:", with_opacity=True)
        f.addRow(card)
        # 就绪呼吸光（冷却完毕提示）
        f = make_sub_tab(s_sub, "就绪呼吸光")
        card, cf = make_card(f, "── 就绪呼吸光（冷却完毕提示）──")
        self.skill_cd_breath_chk = QCheckBox("启用就绪呼吸光")
        self.skill_cd_breath_chk.setChecked(bool(self.settings.get("skill_cd_breath_enabled", True)))
        cf.addRow(self.skill_cd_breath_chk)
        self._add_color_row(cf, "skill_cd_breath_color", "呼吸光颜色:", with_opacity=True)
        self.skill_cd_breath_freq_dspn = QDoubleSpinBox(); self.skill_cd_breath_freq_dspn.setRange(0.05, 3.0); self.skill_cd_breath_freq_dspn.setSingleStep(0.05); self.skill_cd_breath_freq_dspn.setDecimals(2); self.skill_cd_breath_freq_dspn.setSuffix("Hz"); self.skill_cd_breath_freq_dspn.setValue(float(self.settings.get("skill_cd_breath_freq", 0.5)))
        cf.addRow("呼吸频率:", self.skill_cd_breath_freq_dspn)
        self.skill_cd_breath_soft_dspn = QDoubleSpinBox(); self.skill_cd_breath_soft_dspn.setRange(0.0, 3.0); self.skill_cd_breath_soft_dspn.setSingleStep(0.1); self.skill_cd_breath_soft_dspn.setDecimals(2); self.skill_cd_breath_soft_dspn.setValue(float(self.settings.get("skill_cd_breath_soft", 1.0)))
        cf.addRow("柔和程度:", self.skill_cd_breath_soft_dspn)
        self.skill_cd_breath_scale_dspn = QDoubleSpinBox(); self.skill_cd_breath_scale_dspn.setRange(0.5, 3.0); self.skill_cd_breath_scale_dspn.setSingleStep(0.1); self.skill_cd_breath_scale_dspn.setDecimals(2); self.skill_cd_breath_scale_dspn.setValue(float(self.settings.get("skill_cd_breath_scale", 1.0)))
        cf.addRow("放大倍数:", self.skill_cd_breath_scale_dspn)
        cf.addRow(QWidget())  # 占位，避免界面留白突兀
        f.addRow(card)
        # 技能名称
        f = make_sub_tab(s_sub, "能力名称")
        card, cf = make_card(f, "── 能力名称 ──")
        self.skill_cd_name_chk = QCheckBox("显示能力名称")
        self.skill_cd_name_chk.setChecked(bool(self.settings.get("skill_cd_show_name", True)))
        cf.addRow(self.skill_cd_name_chk)
        self.skill_cd_name_font_spn = QSpinBox(); self.skill_cd_name_font_spn.setRange(1, 48); self.skill_cd_name_font_spn.setValue(int(self.settings.get("skill_cd_name_font_size", 7)))
        cf.addRow("字号:", self.skill_cd_name_font_spn)
        self.skill_cd_name_offx_spn = QSpinBox(); self.skill_cd_name_offx_spn.setRange(-200, 200); self.skill_cd_name_offx_spn.setValue(int(self.settings.get("skill_cd_name_offset_x", 0)))
        cf.addRow("能力名X偏移:", self.skill_cd_name_offx_spn)
        self.skill_cd_name_offy_spn = QSpinBox(); self.skill_cd_name_offy_spn.setRange(-200, 200); self.skill_cd_name_offy_spn.setValue(int(self.settings.get("skill_cd_name_offset_y", 0)))
        cf.addRow("能力名Y偏移:", self.skill_cd_name_offy_spn)
        self.skill_cd_name_bgw_spn = QSpinBox(); self.skill_cd_name_bgw_spn.setRange(-100, 100); self.skill_cd_name_bgw_spn.setValue(int(self.settings.get("skill_cd_name_bg_width", 0)))
        cf.addRow("衬色块宽微调:", self.skill_cd_name_bgw_spn)
        self._add_color_row(cf, "skill_cd_name_color", "能力名色:", with_opacity=True)
        f.addRow(card)
        # 能力模块位置与缩放（从原“模块位置”顶级标签迁入）
        f = make_sub_tab(s_sub, "位置与缩放")
        card, cf = make_card(f, "── 能力模块位置与缩放 ──")
        self.skill_x_spn, self.skill_y_spn = _mk_pos_row(cf, "skill_window_x", "skill_window_y")
        self.skill_scale_slider, self.skill_scale_spin = _mk_scale_row(cf, "skill", "模块缩放:")
        f.addRow(card)

        # ============ 关于 / 更新 ============
        about_top = make_top_tab("关于/更新")
        about_form = make_sub_tab(about_top, "关于")
        # 关于页内容少，避免单个 card 被纵向撑出大片空白
        about_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        card, cf = make_card(about_form, "── 在线更新 ──")
        cf.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.current_ver_label = QLabel(f"v{APP_VERSION}")
        self.current_ver_label.setStyleSheet("font-weight:bold; color:#9fd0ff;")
        cf.addRow("当前版本：", self.current_ver_label)
        self.update_status_label = QLabel("—")
        self.update_status_label.setStyleSheet("color:#aabbcc;")
        cf.addRow("状态：", self.update_status_label)
        btn_row = QWidget(); btn_lay = QHBoxLayout(btn_row); btn_lay.setContentsMargins(0, 0, 0, 0); btn_lay.setSpacing(6)
        self.check_update_btn = QPushButton("检查更新")
        self.check_update_btn.clicked.connect(self._on_check_update_clicked)
        self.download_btn = QPushButton("前往下载")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.skip_btn = QPushButton("跳过此版本")
        self.skip_btn.setEnabled(False)
        self.skip_btn.clicked.connect(self._on_skip_clicked)
        btn_lay.addWidget(self.check_update_btn); btn_lay.addWidget(self.download_btn); btn_lay.addWidget(self.skip_btn)
        cf.addRow(btn_row)
        self.auto_check_cb = QCheckBox("自动检查更新")
        self.auto_check_cb.setChecked(bool(self.settings.get("auto_check_update", True)))
        cf.addRow(self.auto_check_cb)
        self.update_url_le = QLineEdit(self.settings.get("update_check_url", "") or "")
        self.update_url_le.setPlaceholderText("https://.../version.json")
        cf.addRow("更新检测版本地址：", self.update_url_le)
        # V304：下载地址（来自 version.json 的 download_url，可在检查更新后自动填入；也可手填）
        self.download_url_le = QLineEdit(self.settings.get("update_download_url", "") or "")
        self.download_url_le.setPlaceholderText("检查更新后自动填入，或手动填写 exe 下载直链")
        cf.addRow("更新下载地址：", self.download_url_le)
        # V303：明示两个 URL 的区别（检测地址走 release CDN，非 raw，国内快速且不易被墙）
        url_hint = QLabel(_tr("检测版本地址（上方）走 GitHub Release CDN（releases/latest/download/version.json），非 raw，国内快速且不易被墙；exe 下载地址从该 version.json 的 download_url 字段读取并自动填入下方，无需另外配置。"))
        url_hint.setWordWrap(True)
        url_hint.setStyleSheet("color:#8aa0c0;font-size:10px;")
        cf.addRow(url_hint)
        self.changelog_edit = QPlainTextEdit()
        self.changelog_edit.setReadOnly(True)
        self.changelog_edit.setMaximumHeight(120)
        self.changelog_edit.setStyleSheet("background:rgba(20,26,40,0.6); color:#cdd6e0; border-radius:6px;")
        cf.addRow("更新日志：", self.changelog_edit)
        about_form.addRow(card)
        about_form.addItem(QSpacerItem(20, 1, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.skip_version = self.settings.get("skip_version", "") or ""
        if self.ctrl is not None and getattr(self.ctrl, "update_info", None) is not None:
            self.refresh_update_ui(self.ctrl.update_info)
        else:
            self.update_status_label.setText("—")

        # 信号 / 按钮
        self._connect_live_signals()
        self.lang.currentIndexChanged.connect(self.retranslate_ui)
        buttons = QHBoxLayout()
        defaults = QPushButton("恢复默认"); ok = QPushButton("确定"); cancel = QPushButton("取消")
        defaults.setAutoDefault(False); defaults.setDefault(False); ok.setAutoDefault(True); ok.setDefault(True); cancel.setAutoDefault(False); cancel.setDefault(False)
        defaults.clicked.connect(self.reset_defaults); ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        buttons.addWidget(defaults); buttons.addWidget(ok); buttons.addWidget(cancel)
        layout.addLayout(buttons)
        sig = QLabel(AUTHOR_TAG); sig.setStyleSheet("color:#445566; font-size:9px;"); sig.setAlignment(Qt.AlignCenter)
        layout.addWidget(sig)
        self.retranslate_ui()
    def retranslate_ui(self, *_):
        """根据语言下拉框刷新设置弹窗文本。"""
        lang = self.lang.currentText() if hasattr(self, "lang") else self.settings.get("language", "zh")
        global _CURRENT_LANG
        _CURRENT_LANG = lang

        en_to_zh = {v: k for k, v in ZH_TO_EN.items()}
        tw_to_zh = {v: k for k, v in ZH_TO_TW.items()}
        if lang == "en":
            target_map = ZH_TO_EN
        elif lang == "zh_tw":
            target_map = ZH_TO_TW
        else:
            target_map = {}

        def _translate_text(text):
            """先归一化到简中，再翻译到目标语言。"""
            if text in en_to_zh:
                text = en_to_zh[text]
            elif text in tw_to_zh:
                text = tw_to_zh[text]
            return target_map.get(text, text)

        self.setWindowTitle(_translate_text("Overlay 设置") + f" v{APP_VERSION}")
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

        if hasattr(self, "timer_style"):
            ring_idx = self.timer_style.findData("ring")
            sector_idx = self.timer_style.findData("sector")
            if ring_idx >= 0:
                self.timer_style.setItemText(ring_idx, "Ring" if lang == "en" else "圆环")
            if sector_idx >= 0:
                self.timer_style.setItemText(sector_idx, "Sector" if lang == "en" else "扇形")

        if hasattr(self, "roll_orientation_combo"):
            h_idx = self.roll_orientation_combo.findData("horizontal")
            v_idx = self.roll_orientation_combo.findData("vertical")
            hz = "橫放" if lang == "zh_tw" else "横放"
            vz = "豎放" if lang == "zh_tw" else "竖放"
            if h_idx >= 0:
                self.roll_orientation_combo.setItemText(h_idx, "Horizontal" if lang == "en" else hz)
            if v_idx >= 0:
                self.roll_orientation_combo.setItemText(v_idx, "Vertical" if lang == "en" else vz)

        if hasattr(self, "buff_order_direction_combo"):
            l_idx = self.buff_order_direction_combo.findData("ltr")
            r_idx = self.buff_order_direction_combo.findData("rtl")
            if lang == "en":
                l_text, r_text = "Top → Left", "Top → Right"
            elif lang == "zh_tw":
                l_text, r_text = "越上越靠左", "越上越靠右"
            else:
                l_text, r_text = "越上越靠左", "越上越靠右"
            if l_idx >= 0:
                self.buff_order_direction_combo.setItemText(l_idx, l_text)
            if r_idx >= 0:
                self.buff_order_direction_combo.setItemText(r_idx, r_text)

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
            for pl_id, group in self.buff_order_groups.items():
                group.refresh_title(lang)
                group.refresh_items(lang)

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
        self.settings_changed.emit(self.get_settings())

    def _sync_icon_default_enabled(self):
        use_default = bool(self.icon_use_default.isChecked())
        self.icon_path.setEnabled(not use_default)
        self.browse_icon_btn.setEnabled(not use_default)

    def _set_all_buff_rank(self, show):
        """「全勾选」= 每组三框全勾（常显）；「全取消」= 三框全不勾（常关）。"""
        action = "全部勾选" if show else "全部取消"
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
            self.lang, self.auto_focus_minimize, self.resolution_auto_scale, self.spike_hide_chk, self.spike_hidden_op_spn, self.hide_spikes_beads_chk, self.show_titlebar_status, self.titlebar_font_size_spn, self.icon_use_default,
            self.core_scale_slider, self.core_scale_spin, self.roll_scale_slider, self.roll_scale_spin, self.skill_scale_slider, self.skill_scale_spin,
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
            self.ex_status_offset_spin,
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
            self.roll_orientation_combo,
            self.buff_order_direction_combo,
            self.core_x_spn, self.core_y_spn, self.roll_x_spn, self.roll_y_spn,
            self.skill_x_spn, self.skill_y_spn,
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

    def pick_color(self, key, button):
        lang = self.settings.get("language", "zh")
        color_titles = {"zh": "选择颜色", "zh_tw": "選擇顏色", "en": "Select Color"}
        color = QColorDialog.getColor(qcolor(self.settings.get(key)), self,
                                      color_titles.get(lang, color_titles["zh"]))
        if color.isValid():
            self.settings[key] = color.name()
            button.setText(color.name())
            button.setStyleSheet(f"background:{color.name()}; color:#fff; border-radius:4px;")
            self._emit_changed()

    def reset_defaults(self):
        lang = self.settings.get("language", "zh")
        title = {"zh": "恢复默认", "zh_tw": "恢復預設", "en": "Reset to Defaults"}.get(lang, "Reset to Defaults")
        text = {"zh": "确定要把所有设置恢复为默认吗？此操作会清空当前所有自定义配置（含已禁用的 Buff）。",
                "zh_tw": "確定要把所有設定恢復為預設嗎？此操作會清空目前所有自訂配置（含已停用的 Buff）。",
                "en": "Reset all settings to defaults? This clears all current custom configuration."}.get(lang, "Reset all settings to defaults?")
        reply = QMessageBox.question(self, title, text,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._suppress_emit = True
        self.settings = dict(DEFAULT_SETTINGS)
        self.lang.setCurrentText(DEFAULT_SETTINGS["language"])
        self.auto_focus_minimize.setChecked(DEFAULT_SETTINGS["auto_focus_minimize"])
        self.resolution_auto_scale.setChecked(DEFAULT_SETTINGS["resolution_auto_scale"])
        self.spike_hide_chk.setChecked(DEFAULT_SETTINGS["spike_hide_when_no_buff"])
        self.spike_hidden_op_spn.setValue(DEFAULT_SETTINGS["spike_hidden_opacity"])
        self.hide_spikes_beads_chk.setChecked(DEFAULT_SETTINGS["hide_spikes_and_beads"])
        self.ooc_hide_chk.setChecked(DEFAULT_SETTINGS["out_of_combat_hide"])
        self.ooc_op_spn.setValue(DEFAULT_SETTINGS["out_of_combat_opacity"])
        self.show_titlebar_status.setChecked(DEFAULT_SETTINGS["show_titlebar_status"])
        self.titlebar_font_size_spn.setValue(DEFAULT_SETTINGS["titlebar_font_size"])
        # buff 顺位/专精勾选重置为默认（全勾=常显）
        for group in getattr(self, "buff_order_groups", {}).values():
            group.set_all(True)
        self.auto_check_cb.setChecked(DEFAULT_SETTINGS["auto_check_update"])
        self.update_url_le.setText(DEFAULT_SETTINGS["update_check_url"])
        self.download_url_le.setText(DEFAULT_SETTINGS["update_download_url"])
        for _p, _d, _e in (("hk_show", "17,75", True), ("hk_lock", "", False), ("hk_settings", "", False)):
            getattr(self, f"{_p}_enabled").setChecked(_e)
            setattr(self, f"{_p}_combo", _d)
            getattr(self, f"{_p}_lbl").setText(self._combo_to_name(_d) if _d else "未设置")
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
        self.core_scale_slider.setValue(100); self.core_scale_spin.setValue(100)
        self.roll_scale_slider.setValue(100); self.roll_scale_spin.setValue(100)
        self.skill_scale_slider.setValue(100); self.skill_scale_spin.setValue(100)
        self.scan.setValue(DEFAULT_SETTINGS["scan_ms"])
        self.circle_radius.setValue(DEFAULT_SETTINGS["circle_radius"])
        self.spike_length.setValue(DEFAULT_SETTINGS["spike_length"])
        self.spike_axis_pos.setValue(DEFAULT_SETTINGS["spike_axis_pos_percent"])
        self.spike_width.setValue(DEFAULT_SETTINGS["spike_width"])
        self.spike_waist_pos.setValue(DEFAULT_SETTINGS["spike_waist_pos_percent"])
        self.spike_bead_radius.setValue(DEFAULT_SETTINGS["spike_bead_radius"])
        self.spike_bead_pos.setValue(DEFAULT_SETTINGS["spike_bead_pos_percent"])
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
        # 翻滚朝向
        self.roll_orientation_combo.setCurrentIndex(max(0, self.roll_orientation_combo.findData(DEFAULT_SETTINGS["roll_orientation"])))
        # 各模块独立屏幕位置
        self.core_x_spn.setValue(int(DEFAULT_SETTINGS["core_window_x"]))
        self.core_y_spn.setValue(int(DEFAULT_SETTINGS["core_window_y"]))
        self.roll_x_spn.setValue(int(DEFAULT_SETTINGS["roll_window_x"]))
        self.roll_y_spn.setValue(int(DEFAULT_SETTINGS["roll_window_y"]))
        self.skill_x_spn.setValue(int(DEFAULT_SETTINGS["skill_window_x"]))
        self.skill_y_spn.setValue(int(DEFAULT_SETTINGS["skill_window_y"]))
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
        self.ex_status_offset_spin.setValue(DEFAULT_SETTINGS["ex_status_offset"])
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
        self._suppress_emit = False
        self._emit_changed()

    def get_settings(self):
        self.settings["language"] = self.lang.currentText()
        self.settings["auto_focus_minimize"] = self.auto_focus_minimize.isChecked()
        self.settings["resolution_auto_scale"] = self.resolution_auto_scale.isChecked()
        self.settings["spike_hide_when_no_buff"] = self.spike_hide_chk.isChecked()
        self.settings["spike_hidden_opacity"] = self.spike_hidden_op_spn.value()
        self.settings["hide_spikes_and_beads"] = self.hide_spikes_beads_chk.isChecked()
        self.settings["out_of_combat_hide"] = self.ooc_hide_chk.isChecked()
        self.settings["out_of_combat_opacity"] = self.ooc_op_spn.value()
        self.settings["show_titlebar_status"] = self.show_titlebar_status.isChecked()
        self.settings["titlebar_font_size"] = self.titlebar_font_size_spn.value()
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
        self.settings["skill_cd_show_name"] = self.skill_cd_name_chk.isChecked()
        self.settings["skill_cd_name_font_size"] = self.skill_cd_name_font_spn.value()
        self.settings["skill_cd_name_offset_x"] = self.skill_cd_name_offx_spn.value()
        self.settings["skill_cd_name_offset_y"] = self.skill_cd_name_offy_spn.value()
        self.settings["skill_cd_name_bg_width"] = self.skill_cd_name_bgw_spn.value()
        self.settings["use_default_dodge_icon"] = self.icon_use_default.isChecked()
        self.settings["roll_orientation"] = self.roll_orientation_combo.currentData()
        self.settings["buff_order_direction"] = self.buff_order_direction_combo.currentData() if self.buff_order_direction_combo.count() else "ltr"
        # 各模块独立屏幕位置
        self.settings["core_window_x"] = self.core_x_spn.value()
        self.settings["core_window_y"] = self.core_y_spn.value()
        self.settings["roll_window_x"] = self.roll_x_spn.value()
        self.settings["roll_window_y"] = self.roll_y_spn.value()
        self.settings["skill_window_x"] = self.skill_x_spn.value()
        self.settings["skill_window_y"] = self.skill_y_spn.value()
        self.settings["core_scale_percent"] = self.core_scale_spin.value()
        self.settings["roll_scale_percent"] = self.roll_scale_spin.value()
        self.settings["skill_scale_percent"] = self.skill_scale_spin.value()
        self.settings["scan_ms"] = self.scan.value()
        self.settings["settings_schema_version"] = SETTINGS_SCHEMA_VERSION
        self.settings["circle_radius"] = self.circle_radius.value()
        self.settings["spike_length"] = self.spike_length.value()
        self.settings["spike_axis_pos_percent"] = self.spike_axis_pos.value()
        self.settings["spike_width"] = self.spike_width.value()
        self.settings["spike_waist_pos_percent"] = self.spike_waist_pos.value()
        self.settings["spike_bead_radius"] = self.spike_bead_radius.value()
        self.settings["spike_bead_pos_percent"] = self.spike_bead_pos.value()
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
        self.settings["ex_status_offset"] = self.ex_status_offset_spin.value()
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
        return self.settings

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
            return "未设置"
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
        return " + ".join(parts) if parts else "未设置"

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
        btn = QPushButton("设置按键…")
        btn.setFixedWidth(110)
        lbl = QLabel()
        lbl.setStyleSheet("color:#cfe0ff;font-weight:bold;font-size:13px;")
        combo = self.settings.get(setting_key, default_combo) or ""
        lbl.setText(self._combo_to_name(combo) if combo else "未设置")
        btn.clicked.connect(lambda _=None, p=prefix: self._capture_hotkey(p))
        lay.addWidget(chk); lay.addWidget(btn); lay.addWidget(lbl); lay.addStretch()
        cf.addRow(label_text + "：", row)
        setattr(self, f"{prefix}_enabled", chk)
        setattr(self, f"{prefix}_combo", combo)
        setattr(self, f"{prefix}_lbl", lbl)
        setattr(self, f"{prefix}_btn", btn)

    def _capture_hotkey(self, which):
        combo = getattr(self, f"{which}_combo", "") or ""
        dlg = HotkeyCaptureDialog(self, self._combo_to_name(combo) if combo else "按下组合键…")
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
        if info is None:
            self.update_status_label.setText("—")
            self.download_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.changelog_edit.setPlainText("")
            return
        if info.get("error") == "no_url":
            self.update_status_label.setText(_tr("未配置更新地址"))
            self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
            self.changelog_edit.setPlainText("")
            return
        if info.get("error"):
            self.update_status_label.setText(_tr("检查失败：") + str(info.get("error")))
            self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
            # 清除陈旧日志，避免残留旧版本（如 3.0）内容误导用户
            self.changelog_edit.setPlainText("")
            return
        latest = info.get("latest_version", "")
        self.changelog_edit.setPlainText(info.get("changelog", "") or "")
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

    def _on_check_update_clicked(self):
        self.update_status_label.setText(_tr("检查中…"))
        self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
        if self.ctrl is not None:
            self.ctrl.check_update(manual=True)

    def _on_download_clicked(self):
        info = getattr(self.ctrl, "update_info", None)
        url = (info.get("download_url") if info else None) or self.download_url_le.text().strip()
        if url:
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
            pass
        return False


# ============================ Overlay Widget ============================
class GBFROverlayQt(QObject):
    update_checked = Signal(object)
    """控制器（隐藏、不绘制）：负责扫描内存、持有共享状态、托盘、设置，
    并创建/管理 3 个独立可拖动的模块窗口（核心检测 / 翻滚 / 能力冷却）。"""

    TITLE_BAR_H = 44
    CANVAS_W = 648  # 核心检测模块画布宽度基准（原 480 × 1.35，放大监测区尺寸）
    CORE_AREA_MULT = 1.35  # 核心监测区整体（长/宽）放大倍数（用户要求 ×1.35）
    DEFAULT_NUM_SPIKES = 7
    SPIKE_W = 16
    SHRIMP_BASE_SIZE = 36
    SHRIMP_LEFT_PAD = 10
    SHRIMP_RIGHT_PAD = 10
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
                    pass

        _step(8, "正在加载设置…")
        self.settings = load_settings()
        self.locked = False
        self._pressed_core_btn = None  # 标题栏图标按下反馈态：None/"minimize"/"settings"/"lock"/"exit"
        self._pressed_visual = False   # 指针是否仍在被按下的按钮内（仅影响凹陷视觉，不清除锁定）
        # 窗口局部像素版命中矩形（与绘制缩放一致，避免画布<->窗口坐标换算误差）
        self._btn_minimize_rect_win = QRect()
        self._btn_settings_rect_win = QRect()
        self._btn_lock_rect_win = QRect()
        self._btn_exit_rect_win = QRect()

        self.handle = None
        self.pid = None
        self.pptr = None
        self.module_base = None
        self.module_size = 0
        self.quest_mgr = None
        self._qm_global = None
        self.in_training_area = False
        self.status = "init"
        self.active_buffs = []
        self.dodge_count = 0
        self.char_type = 0
        self.charid_hash = 0
        self.pl_id = None
        self._auto_minimized_by_game_focus = False
        self._ooc_content_mult = 1.0
        self._ooc_content_hidden = False
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
        _step(22, "已加载角色数据库")
        load_char_db()

        # 计算「核心检测模块」画布布局（尖刺圆 + 标题栏）
        _step(38, "正在计算界面布局…")
        self.recalc_layout()
        _step(52, "正在加载图标资源…")
        self.load_dodge_icon()
        # 翻滚图标闪光状态
        self._dodge_flash = None
        self._dodge_solid_cache = {}      # 翻滚图标实心缓存 {color_hex: QPixmap}
        self._dodge_outline_cache = {}    # 翻滚图标白色勾边光晕缓存 {color_hex: QPixmap}
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
        self.core_win.setWindowTitle(f"{_app_title(self.settings.get('language', 'zh'))} v{APP_VERSION}")

        _step(72, "已创建悬浮窗口")
        self._setup_tray_icon()
        _step(86, "已初始化系统托盘")

        # ---- 在线更新检测 ----
        self.update_info = None
        self._update_thread = None
        self.settings_dialog = None
        self.update_checked.connect(self._on_update_checked)
        self._update_startup_timer = QTimer(self)
        self._update_startup_timer.setSingleShot(True)
        self._update_startup_timer.timeout.connect(lambda: self.check_update())
        self._update_startup_timer.start(4000)
        self._update_periodic_timer = QTimer(self)
        self._update_periodic_timer.setInterval(24 * 3600 * 1000)
        self._update_periodic_timer.timeout.connect(lambda: self.check_update())
        self._update_periodic_timer.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        # 首次扫描延后到事件循环启动后执行，避免阻塞构造。
        QTimer.singleShot(0, self.tick)

        # 显示模块窗口
        _step(95, "正在显示悬浮窗口…")
        for w in (self.core_win, self.roll_win, self.skill_win):
            w.show()
        _step(100, "启动完成")

        # 全局快捷键：最多 3 键组合（呼出/隐藏、锁定/解锁、打开设置）
        self._hotkey_filter = _HotkeyFilter(self._on_hotkey_triggered)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._hotkey_filter)
            try:
                app.aboutToQuit.connect(self._unregister_global_hotkey)
            except Exception:
                pass
        self._register_all_hotkeys()

    # ----------------------------------------------------------------
    #  窗口集合辅助
    # ----------------------------------------------------------------
    def _all_windows(self):
        return [self.core_win, self.roll_win, self.skill_win]

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
                pass
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
                pass

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
                pass
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
            pass

    def _toggle_all_windows(self):
        """切换所有悬浮窗口显隐：任一可见则全部隐藏，否则全部显示。"""
        wins = self._all_windows()
        if not wins:
            return
        any_visible = any(w.isVisible() and not w.isMinimized() for w in wins)
        if any_visible:
            for w in wins:
                w.hide()
        else:
            self._show_all()

    def _show_all(self):
        for w in self._all_windows():
            if w.isMinimized():
                w.showNormal()
            w.show()
            w.raise_()

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
            x = int(self.settings.get(f"{w.module_key}_window_x", w.x()))
            y = int(self.settings.get(f"{w.module_key}_window_y", w.y()))
            w.move(x, y)
            w.update()

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
        # 各模块独立缩放：ui_scale 仅作渲染期临时值，由对应窗口在 paintEvent 中写入
        self.ui_scale = self.res_scale
        self.circle_r = int(self.settings.get("circle_radius", DEFAULT_SETTINGS["circle_radius"]))
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
        hide_spikes = bool(self.settings.get("hide_spikes_and_beads", False))
        outline_pad = max(0, self.indicator_outline_width + 2)
        if hide_spikes:
            spike_outer_extent = 0
            bead_outer_extent = 0
            spike_side_extent = outline_pad
            spike_top_pad = outline_pad
            spike_bottom_pad = outline_pad
        else:
            spike_outer_extent = max(0, int((1.0 + self.spike_axis_pos) * self.spike_len))
            bead_outer_extent = self.spike_bead_radius + max(0, int(abs(self.spike_bead_pos) * self.spike_len))
            spike_side_extent = spike_outer_extent + max(self.spike_w // 2, self.spike_bead_radius) + outline_pad
            spike_top_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent) + outline_pad
            spike_bottom_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent) + outline_pad
        core_required_w = (self.circle_r + max(spike_side_extent, bead_outer_extent if not hide_spikes else 0) + outline_pad + 10) * 2
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
        self.dragon_bottom_y = self.circle_cy + self.circle_r + (0 if hide_spikes else self.spike_len)

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
        skill_cd_spread = int(self.settings.get("skill_cd_spread", 70))
        skill_cd_size = int(self.settings.get("skill_cd_size", 18))
        half_diag = int(skill_cd_size * 1.5)
        eff_spread = max(skill_cd_spread, half_diag + 8)
        skill_pad = 10
        self.skill_canvas_w = 2 * (eff_spread + half_diag + skill_pad)
        self.skill_canvas_h = self.skill_canvas_w
        self.skill_cx = self.skill_canvas_w / 2.0
        self.skill_cy = self.skill_canvas_h / 2.0

    def load_dodge_icon(self):
        path = DEFAULT_SHRIMP_IMG_PATH if bool(self.settings.get("use_default_dodge_icon", True)) else self.settings.get("shrimp_img_path", DEFAULT_SHRIMP_IMG_PATH)
        self.shrimp = QPixmap(path)
        if not self.shrimp.isNull():
            self.shrimp = self.shrimp.scaled(
                self.dodge_icon_size,
                self.dodge_icon_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )

    def _calc_icon_btn_rects(self):
        """计算标题栏图标按钮区域：未锁定时 4 个图标(最小化/设置/锁定/退出)作为整体水平居中于
        标题栏顶部一行；锁定时仅显示锁定图标并居中。下方另留「文本层」给状态文字。"""
        th = self.TITLE_BAR_H
        s = self.ICON_BTN_SIZE
        gap = self.ICON_BTN_GAP
        icon_row_h = self.ICON_BTN_SIZE + 10
        if not self.locked:
            n = 4
            total_w = n * s + (n - 1) * gap
            start_x = (self.core_canvas_w - total_w) / 2.0
            y = (icon_row_h - s) // 2
            minimize_x = start_x
            settings_x = start_x + (s + gap)
            lock_x = start_x + 2 * (s + gap)
            exit_x = start_x + 3 * (s + gap)
        else:
            # 仅锁定图标：整体居中
            lock_x = (self.core_canvas_w - s) / 2.0
            y = (icon_row_h - s) // 2
            off = -9999
            minimize_x = settings_x = exit_x = off
        return (
            QRect(int(minimize_x), int(y), s, s),
            QRect(int(settings_x), int(y), s, s),
            QRect(int(lock_x), int(y), s, s),
            QRect(int(exit_x), int(y), s, s),
        )

    # ================================================================
    #  绘制：主事件
    # ================================================================
    # ================================================================
    #  绘制：核心检测模块（尖刺圆 + 标题栏 + buff），由 CoreWindow 调用
    # ================================================================
    def render_core(self, painter):
        cx, cy, r = self.circle_cx, self.circle_cy, self.circle_r
        # 仅尖刺圆模块可能隐藏：当「无buff隐藏」选项开启且主控角色没有任何可显示buff时。
        # 翻滚UI 与 冷却技能UI 永远显示，不受此影响。
        self.spike_hidden = bool(self.settings.get("spike_hide_when_no_buff", True)) and (len(self.active_buffs) == 0)

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
            hide_spikes = bool(self.settings.get("hide_spikes_and_beads", False))
            self._draw_indicator_outer_outline(painter, cx, cy, r, False, include_spikes=not hide_spikes)
            self._draw_circle(painter, cx, cy, r, False)

    def _render_buff_ui(self, painter, buff, cx, cy, r, is_lv7, scale=1.0,
                         color_override=None, color_index=0):
        """渲染一个完整的 buff UI 元素（圆环+尖刺+倒计时+中心文字）。"""
        is_single_layer = self._is_buff_single_layer(buff)
        hide_spikes = bool(self.settings.get("hide_spikes_and_beads", False))
        painter.save()
        if scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        self._draw_glow(painter, cx, cy, r, is_lv7, color_override=color_override)
        include_spikes = not is_single_layer and not hide_spikes
        self._draw_indicator_outer_outline(painter, cx, cy, r, is_lv7,
                                           include_spikes=include_spikes,
                                           buff=buff, color_override=color_override)
        if not is_single_layer and not hide_spikes:
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
        # 聚散距离直接生效，仅保留极小下限避免菱形覆盖中心
        half_diag = int(s * 1.5)
        spread = max(spread, half_diag + 8)
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
                    pass
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
                        pass
        # 第三遍：统一把所有技能名称绘制在最顶层（置于顶层）
        if bool(self.settings.get("skill_cd_show_name", True)):
            for i, (sx, sy) in enumerate(positions):
                if i < len(self.skill_cd_data):
                    try:
                        self._draw_skill_cd_name(painter, self.skill_cd_data[i], sx, sy, s)
                    except Exception:
                        pass

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
            timer_text = f"{cd_val:.2f}"
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
            for key in self.INTERNAL_COLOR_KEYS:
                override[key] = rotate_hue(self.settings.get(key, "#ffffff"), deg)
        # 倒计时扇形(arc_color)始终随多buff差异化着色：它是中央最显眼的计时元素，
        # 之前只归在 INTERNAL 里，一旦关闭「内部差异化颜色」开关扇形就不变色，
        # 与圆环/尖刺(外部)的变色脱节。这里让扇形只要「任一差异化」开启就跟随，
        # 其余内部色(数字/计时文字)仍受 int 开关控制。
        if "arc_color" not in override and (cfg["ext"] or cfg["int"]):
            override["arc_color"] = rotate_hue(self.settings.get("arc_color", "#55ff00"), deg)
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

        # 图标按钮区域（最小化、设置、锁定、退出，从左到右）
        minimize_rect, settings_rect, lock_rect, exit_rect = self._calc_icon_btn_rects()
        self._btn_lock_rect = lock_rect
        hidden_rect = QRect(-9999, -9999, 0, 0)
        self._btn_minimize_rect = hidden_rect if self.locked else minimize_rect
        self._btn_settings_rect = hidden_rect if self.locked else settings_rect
        self._btn_exit_rect = hidden_rect if self.locked else exit_rect
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
                    text_rect = QRect(0, icon_row_h, self.core_canvas_w, th - icon_row_h)
                    painter.setPen(QColor(self.settings.get("icon_color", "#7f8fa6")))
                    font_size = max(6, int(self.settings.get("titlebar_font_size", DEFAULT_SETTINGS["titlebar_font_size"])))
                    painter.setFont(QFont("Segoe UI", font_size, QFont.Bold))
                    painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, status_text)

            # 版本号（最小化按钮左侧，小字，跟随图标色/不透明度）
            ver_font = QFont("Segoe UI", 7, QFont.Medium)
            painter.setFont(ver_font)
            ver_text = f"v{APP_VERSION}"
            ver_metrics = QFontMetrics(ver_font)
            ver_w = ver_metrics.horizontalAdvance(ver_text)
            ver_h = ver_metrics.height()
            ver_x = minimize_rect.x() - ver_w - 6
            ver_y = minimize_rect.y() + (minimize_rect.height() - ver_h) // 2
            if ver_x > 2:  # 只有空间够时才画（避免与窗口边缘重叠）
                painter.setPen(QColor(self.settings.get("icon_color", "#7f8fa6")))
                painter.drawText(QRect(ver_x, ver_y, ver_w, ver_h), Qt.AlignLeft | Qt.AlignVCenter, ver_text)

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
        if not self.active_buffs:
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

        # 圆环外勾边：原圆环会覆盖中间，只留下外侧白边。
        painter.drawEllipse(QPoint(cx, cy), r, r)

        # 尖刺外勾边。
        for i in range(visible_spikes):
            angle = -90 + i * (360.0 / max_stacks)
            points = self._calc_spike_points(cx, cy, r, angle)
            path = QPainterPath()
            path.moveTo(points["tip"][0], points["tip"][1])
            path.lineTo(points["left"][0], points["left"][1])
            path.lineTo(points["root"][0], points["root"][1])
            path.lineTo(points["right"][0], points["right"][1])
            path.closeSubpath()
            painter.drawPath(path)

            bead_r = max(0, int(self.spike_bead_radius))
            if bead_r > 0:
                bead_x, bead_y = points["bead"]
                painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)

        painter.restore()

    def _draw_spikes(self, painter, cx, cy, r, is_lv7, buff=None, color_override=None):
        if not buff:
            return
        max_stacks = self._buff_max_stacks(buff)
        visible_spikes = min(max(int(buff.get("stacks", 0)), 0), max_stacks)
        key = "spike_color_lv7" if is_lv7 else "spike_color_normal"
        spike_color = qcolor(self._get_color(key, color_override))
        painter.save()
        painter.setOpacity(self._effective_opacity(key))

        light_c = QColor(spike_color).lighter(140)
        dark_c = QColor(spike_color).darker(135)
        outline_c = QColor(spike_color).darker(180)
        outline_c.setAlpha(150)

        # 尖刺闪光：层数增加时新出现尖刺(index>=from)闪光；层数回退时消失的尖刺(index>=from, from=回退后层数)
        # 也会以闪光呈现后消失。flash 记录含 from(闪烁起点索引) 与 to(动画期间需要绘制到的最高尖刺索引)。
        # 键必须与 tick 存储侧 _bkey(idx, group) 一致（pl_id 优先，回退 char_type），否则存读不匹配→不闪。
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

        # 即使当前层数归零，只要存在回退闪光(from<to)，也要把消失的尖刺画出来并闪光
        draw_count = max(visible_spikes, flash_to)
        if draw_count <= 0:
            painter.restore()
            return

        for i in range(draw_count):
            angle = -90 + i * (360.0 / max_stacks)
            points = self._calc_spike_points(cx, cy, r, angle)
            path = QPainterPath()
            path.moveTo(points["tip"][0], points["tip"][1])
            path.lineTo(points["left"][0], points["left"][1])
            path.lineTo(points["root"][0], points["root"][1])
            path.lineTo(points["right"][0], points["right"][1])
            path.closeSubpath()

            bead_r = max(0, int(self.spike_bead_radius))
            bead_x, bead_y = points["bead"]

            if flash_color is not None and i >= flash_from:
                # 新出现尖刺：以根部(root)为锚点向外放大，保证底部不动、只向尖端外扩
                root_x, root_y = points["root"]
                painter.save()
                painter.setOpacity(1.0)
                if anim_scale != 1.0:
                    painter.translate(root_x, root_y)
                    painter.scale(anim_scale, anim_scale)
                    painter.translate(-root_x, -root_y)
                f_outline = QColor(flash_color).darker(180)
                f_outline.setAlpha(240)
                # 同步外勾边：与 indicator_outline_width 一致，保证尖刺本体和勾边一起外扩
                outline_w = max(0, int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])))
                f_outline_width = max(2.0, outline_w * 2 + 1)
                painter.setBrush(QBrush(flash_color))
                painter.setPen(QPen(f_outline, f_outline_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPath(path)
                if bead_r > 0:
                    painter.setBrush(flash_color)
                    painter.setPen(QPen(f_outline, max(1.2, f_outline_width * 0.6)))
                    painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)
                painter.restore()
            else:
                # 正常绘制：根部略深、尖端略亮
                grad = QLinearGradient(points["root"][0], points["root"][1], points["tip"][0], points["tip"][1])
                grad.setColorAt(0.0, dark_c)
                grad.setColorAt(0.42, spike_color)
                grad.setColorAt(1.0, light_c)
                painter.setBrush(QBrush(grad))
                painter.setPen(QPen(outline_c, 1.0))
                painter.drawPath(path)

                # 根部小圆点：对应PPT里底部的小圆
                if bead_r > 0:
                    bead_c = QColor(spike_color).darker(110)
                    bead_outline = QColor(spike_color).darker(180)
                    painter.setBrush(bead_c)
                    painter.setPen(QPen(bead_outline, 1.2))
                    painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)

        painter.restore()

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
        arc_hex = None
        if color_override:
            arc_hex = color_override.get("arc_color")
        if not arc_hex and color_index > 0:
            base = self.settings.get("arc_color", "#55ff00")
            cfg = self._multi_buff_cfg(min(len(self.active_buffs), 5))
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
            h, s, v, a = slot.getHsv()
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
                    timer_text = f"{timer_val:.2f}s"
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
                timer_text = f"{timer_val:.2f}s"
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

        闪光逻辑（V274 同款）：
          - 普通翻滚图标：闪光时画单层放大实心白色图标，完全替代原图标。
          - 警告牌（第 6/7 次）：闪光时只让警告牌整体放大脉冲，绝不用白色遮挡。
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
            # 警告牌模式：从不画白色遮挡；闪光时仅让警告牌整体放大脉冲（复用闪光的放大比例）
            if flash_active:
                scale = _flash_scale()
                cx, cy = x + icon / 2.0, y + icon / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(scale, scale)
                painter.translate(-cx, -cy)
                self._draw_warning_roll_icon(painter, x, y, icon)
                painter.restore()
            else:
                self._draw_warning_roll_icon(painter, x, y, icon)
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
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ff8a56"))
            path = QPainterPath()
            path.addRoundedRect(x + 2, y + max(2, icon // 6), icon - 4, max(8, icon * 2 // 3), 6, 6)
            painter.drawPath(path)

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

    def _draw_warning_roll_icon(self, painter, x, y, icon):
        """绘制警告牌：红边 + 黄底圆角三角，无感叹号。
        形状：圆角三角形（三个角全圆角）；三角形重心始终与 (cx,cy) 重合。
        实现：先画红色外三角，再在其内部以重心为中心画黄色内三角。
        红边宽度由 warning_outline_width 控制：值越大，黄色内三角越小、红色占比越多，
        但外三角大小/重心完全不变，因此拉大红边占比时图标不会上/下/左/右漂移。
        可调项：warning_size_scale、warning_outline_width、warning_corner_radius、warning_outline_color、warning_fill_color。
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

    def _get_dodge_solid_img(self, color_hex="#ffffff"):
        """缓存翻滚图标（self.shrimp）实心 QPixmap（alpha>128 处填指定色）。

        直接遍历源像素：alpha>128 的位置写入 flash_color，alpha<=128 设透明。
        不用 QBitmap.fromImage/QRegion/QPainterPath 那一套——V303 的方案在某些 Qt 渲染路径下
        会出现 fillPath 后输出空白或边缘锯齿严重，肉眼看不到任何闪光（用户反馈"压根没看到"）。
        直接遍历可靠得多，100x100 图标首帧 1 万次像素操作一次性缓存，后续帧直接命中。
        """
        norm = (color_hex or "#ffffff").lower()
        if norm in self._dodge_solid_cache:
            return self._dodge_solid_cache[norm]
        if self.shrimp.isNull():
            return None
        src = self.shrimp.toImage().convertToFormat(QImage.Format_ARGB32)
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

    def _get_dodge_alpha_path(self):
        """从 self.shrimp 的 alpha 通道提取轮廓 QPainterPath（一次性缓存）。

        用 createAlphaMask -> QBitmap -> QRegion -> QPainterPath.addRegion，
        得到与 PNG 透明/不透明边界完全一致的矢量路径，用于外侧描边光晕。
        只会在 shrimp 加载后生成一次。
        """
        if getattr(self, "_dodge_alpha_path", None) is not None:
            return self._dodge_alpha_path
        if self.shrimp.isNull():
            return None
        src = self.shrimp.toImage().convertToFormat(QImage.Format_ARGB32)
        mask = src.createAlphaMask()
        bmp = QBitmap.fromImage(mask)
        region = QRegion(bmp)
        path = QPainterPath()
        path.addRegion(region)
        self._dodge_alpha_path = path
        return path

    def _get_dodge_outline_img(self, color_hex="#ffffff"):
        """缓存翻滚图标的外侧实心光晕 QPixmap（颜色可调）。

        基于 _get_dodge_solid_img 生成的实心图标，把它放大后画到更大的画布上，
        得到“形状和原图标一致、但比原图标大一圈的实心光晕”。颜色变更时按 hex 重新生成。
        返回的 pixmap 比原图标四周各大一个 pad，绘制时需要在原图标坐标基础上左/上偏移 pad。
        """
        norm = (color_hex or "#ffffff").lower()
        if norm in self._dodge_outline_cache:
            return self._dodge_outline_cache[norm]
        if self.shrimp.isNull():
            return None
        solid = self._get_dodge_solid_img(color_hex)
        if solid is None:
            return None
        w = self.shrimp.width()
        h = self.shrimp.height()
        # 光晕外扩尺寸：按图标短边约 18%~22%（可调整）
        glow = max(4, int(min(w, h) * 0.20))
        pad = glow + 2
        cw, ch = w + pad * 2, h + pad * 2
        img = QImage(cw, ch, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # 把实心图标放大 (w+2*glow, h+2*glow)，居中于画布
        target = QRect(pad - glow, pad - glow, w + glow * 2, h + glow * 2)
        p.drawPixmap(target, solid, solid.rect())
        p.end()
        pm = QPixmap.fromImage(img)
        self._dodge_outline_cache[norm] = pm
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

    def _apply_live_settings(self, new_settings):
        self.settings = dict(new_settings)
        save_settings(self.settings)
        # 实时同步到三个子窗口：它们的 self.settings 是构造时的拷贝，
        # 否则设置面板拖动滑块时窗口内部仍读旧值。
        for win in (self.core_win, self.roll_win, self.skill_win):
            if win is not None:
                win.settings = dict(new_settings)
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
            any_hidden = all((not w.isVisible()) or w.isMinimized() for w in self._all_windows())
            if any_hidden:
                for w in self._all_windows():
                    w.showNormal()
                    w.raise_()
                    w.activateWindow()
            else:
                for w in self._all_windows():
                    w.hide()

    def _toggle_lock(self):
        self.locked = not self.locked
        for w in self._all_windows():
            w.update()

    # ================================================================
    #  主循环
    # ================================================================
    def tick(self):
        try:
            self.scan()
            self._sync_out_of_combat_visibility()
            self._sync_visibility_with_game_focus()
            self._sync_mouse_transparency()
            self._update_tray_tooltip()
        except Exception:
            pass
        interval = int(self.settings.get("scan_ms", 50)) if self.handle else 500
        self.timer.start(interval)
        for w in self._all_windows():
            w.update()

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
          * 隐藏不透明度=0% → 内容区不绘制，窗口缩到仅标题栏高度（不拦截游戏鼠标）。
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

    def _sync_visibility_with_game_focus(self):
        """游戏在前台时自动显示，切到后台时自动最小化（作用于全部三个窗口）。
        若当前被「非战斗隐藏」强制缩为标题栏，则本逻辑不干预。"""
        # 非战斗内容隐藏（窗口已缩为标题栏）时，焦点逻辑不干预
        if getattr(self, "_ooc_content_hidden", False):
            return

        if not bool(self.settings.get("auto_focus_minimize", DEFAULT_SETTINGS["auto_focus_minimize"])):
            if self._auto_minimized_by_game_focus:
                self._auto_minimized_by_game_focus = False
                for w in self._all_windows():
                    if w.isMinimized() or not w.isVisible():
                        w.showNormal()
            return

        if QApplication.activeModalWidget() is not None:
            return

        foreground_pid = get_foreground_pid()
        if foreground_pid in (None, os.getpid()):
            return

        game_is_foreground = self.pid is not None and foreground_pid == self.pid
        if game_is_foreground:
            if self._auto_minimized_by_game_focus or any(w.isMinimized() or not w.isVisible() for w in self._all_windows()):
                for w in self._all_windows():
                    w.showNormal()
                    w.raise_()
            self._auto_minimized_by_game_focus = False
        else:
            if any(w.isVisible() and not w.isMinimized() for w in self._all_windows()):
                self._auto_minimized_by_game_focus = True
                for w in self._all_windows():
                    w.showMinimized()

    def scan(self):
        pid = find_pid()
        if pid is None:
            self.close_handle()
            self.status = "no_game"
            return
        if self.handle is None or self.pid != pid:
            self.pid = pid
            self.handle = open_proc(pid)
            if not self.handle:
                self.status = "no_game"
                return
            self.pptr, self.module_base, self.module_size, extra = resolve_with_cache(
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
                qm, gaddr = resolve_quest_mgr_via_player(self.handle, self.pptr)
                if qm:
                    self.quest_mgr = qm
                    self._qm_global = gaddr
                else:
                    mgr, g = resolve_quest_mgr_with_addr(
                        self.handle, self.module_base, self.module_size or 0x80000000
                    )
                    if mgr:
                        self.quest_mgr = mgr
                        self._qm_global = g
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
        skill_geo = ""
        if hasattr(self, "skill_win"):
            w = self.skill_win
            skill_geo = (f" skill_win=({w.x()},{w.y()} {w.width()}x{w.height()} "
                         f"vis={w.isVisible()} min={w.isMinimized()})")

        # ── 战斗/任务状态检测（用于「非战斗隐藏」）──
        # 非战斗 = 不在副本/任务中 且 不在训练场。
        # 训练场通过 quest_mgr+0xB20/0xB28 两个 u32 计时器判定（小镇等恒为0，训练场非零）。
        in_combat = True
        in_training_area = False
        if self.module_base and self.handle:
            try:
                if self.quest_mgr is None:
                    mgr, gaddr = resolve_quest_mgr_with_addr(
                        self.handle, self.module_base, self.module_size or 0x80000000
                    )
                    self.quest_mgr = mgr
                    self._qm_global = gaddr
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
                pass
        self.handle = None
        self.pptr = None
        self.module_base = None
        self.pid = None
        self.mastery_reader = None
        self.current_mastery = None



    # ================================================================
    #  在线更新检测
    # ================================================================
    def check_update(self, manual=False, force=False):
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        url = (self.settings.get("update_check_url") or "").strip()
        if not url:
            self.update_info = {"error": "no_url"}
            self.update_checked.emit(self.update_info)
            return
        auto = bool(self.settings.get("auto_check_update", True))
        if not manual and not auto and not force:
            return
        skip = self.settings.get("skip_version", "") or ""
        self._update_thread = threading.Thread(target=self._do_check_update, args=(url, manual, skip), daemon=True)
        self._update_thread.start()

    def _do_check_update(self, url, manual, skip):
        info = {"has_update": False, "error": None, "checked_at": time.time()}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GBFR-Overlay-Updater"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
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
                    if url:
                        QDesktopServices.openUrl(QUrl(url))
                elif clicked is btn_skip:
                    self.settings["skip_version"] = latest
                    save_settings(self.settings)
            except Exception:
                pass
        dlg = getattr(self, "settings_dialog", None)
        if dlg is not None:
            try:
                dlg.refresh_update_ui(info)
            except Exception:
                pass

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
        x = int(self.ctrl.settings.get(f"{module_key}_window_x", 100))
        y = int(self.ctrl.settings.get(f"{module_key}_window_y", 100))
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
            # 渲染时把当前模块的显示缩放写入 ctrl，供控制器内部绘制（标题栏等）使用
            self.ctrl.ui_scale = self.disp_w
            painter.scale(self.disp_w, self.disp_h)
            self.render(painter)
        except Exception:
            pass

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
                pass
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
        pos = event.position().toPoint()
        corner = self._corner_at(pos)
        if corner is not None:
            self.resize_mode = corner
            self.resize_start = event.globalPosition().toPoint()
            self.resize_start_rect = (self.x(), self.y(), self.width(), self.height(), int(self.ctrl.settings.get(f"{self.module_key}_scale_percent", 100)))
        else:
            self.drag_pos = event.globalPosition().toPoint() - self.geometry().topLeft()

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
        # 悬停时光标提示缩放角
        if not self.ctrl.locked:
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
        if self.resize_mode is not None:
            self.resize_mode = None
            self.ctrl.settings[f"{self.module_key}_window_x"] = self.x()
            self.ctrl.settings[f"{self.module_key}_window_y"] = self.y()
            save_settings(self.ctrl.settings)
            return
        if self.drag_pos is not None:
            self.ctrl.settings[f"{self.module_key}_window_x"] = self.x()
            self.ctrl.settings[f"{self.module_key}_window_y"] = self.y()
            save_settings(self.ctrl.settings)
        self.drag_pos = None


class CoreWindow(ModuleWindow):
    """核心检测模块：尖刺圆 + 标题栏（含控制图标）。"""

    def recalc_layout(self):
        super().recalc_layout()
        self.window_w = max(1, int(self.ctrl.core_canvas_w * self.disp_w))
        self.window_h = max(1, int(self.ctrl.core_canvas_h * self.disp_h))

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
            for w in self.ctrl._all_windows():
                w.hide()
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
        self.window_w = max(1, int(self.ctrl.roll_canvas_w * self.disp_w))
        self.window_h = max(1, int(self.ctrl.roll_canvas_h * self.disp_h))

    def render(self, painter):
        self.ctrl.render_roll(painter)


class SkillWindow(ModuleWindow):
    """能力冷却模块：独立窗口，4 菱形。"""

    def recalc_layout(self):
        super().recalc_layout()
        self.window_w = max(1, int(self.ctrl.skill_canvas_w * self.disp_w))
        self.window_h = max(1, int(self.ctrl.skill_canvas_h * self.disp_h))

    def render(self, painter):
        self.ctrl.render_skill(painter)


class StartupSplash(QWidget):
    """双击启动时的读条窗口：显示当前正在做什么，初始化完成后显示完成消息。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(400, 80)
        self._meta_base = f"v{APP_VERSION} · by Dangoooooo"
        self._build_ui()
        self._center()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        container = QWidget()
        # 方案 B · 胶囊形卡片：全圆角 + 对角深色渐变 + 外发光描边
        container.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #1a233a,stop:1 #111725);"
            "border-radius:40px;"
            "border:none;"
        )
        inner = QVBoxLayout(container)
        inner.setContentsMargins(24, 0, 24, 0)
        inner.setSpacing(3)
        # 上下 stretch 把内容垂直居中
        inner.addStretch(1)

        # 标题（居中）
        self.title_lbl = QLabel(_tr("GBFR 指示器"))
        self.title_lbl.setStyleSheet("font-size:17px;font-weight:bold;color:#f1f5f9;letter-spacing:1px;background:transparent;border:none;")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.title_lbl)

        # 元信息行：状态 · 版本 · 作者（居中、淡灰）
        self.status_lbl = QLabel(f"{_tr('正在准备…')} · {self._meta_base}")
        self.status_lbl.setStyleSheet("font-size:9px;color:#94a3b8;letter-spacing:0.5px;background:transparent;border:none;")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.status_lbl)

        # 进度条（居中、发光胶囊，无轨道边框）
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setFixedWidth(280)
        self.bar.setStyleSheet(
            "QProgressBar{background:transparent;border:none;border-radius:4px;}"
            "QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #6366f1,stop:0.5 #3b82f6,stop:1 #14b8a6);border-radius:4px;}"
        )
        bar_wrap = QHBoxLayout()
        bar_wrap.addStretch()
        bar_wrap.addWidget(self.bar)
        bar_wrap.addStretch()
        inner.addLayout(bar_wrap)

        inner.addStretch(1)
        layout.addWidget(container)

    def _center(self):
        geo = QApplication.primaryScreen().availableGeometry()
        r = self.geometry()
        self.move(geo.width() // 2 - r.width() // 2, geo.height() // 2 - r.height() // 2)

    def set_progress(self, pct=None, msg=None):
        if pct is not None:
            self.bar.setValue(int(pct))
        if msg:
            self.status_lbl.setText(f"{msg} · {self._meta_base}")
        QApplication.processEvents()

    def finish(self, msg="启动完成"):
        self.bar.setValue(100)
        self.status_lbl.setText(f"{msg} · {self._meta_base}")
        self.status_lbl.setStyleSheet("font-size:9px;color:#7ee0a0;font-weight:bold;letter-spacing:0.5px;")
        QApplication.processEvents()
        # 事件循环启动后才真正关闭，避免构造期间直接销毁
        QTimer.singleShot(1000, self.close)


def main():
    app = QApplication(sys.argv)
    if os.path.isfile(APP_ICON_PATH):
        app.setWindowIcon(QIcon(APP_ICON_PATH))
    app.setQuitOnLastWindowClosed(False)
    splash = StartupSplash()
    splash.show()
    splash.set_progress(4, "正在加载设置…")
    overlay = GBFROverlayQt(progress_cb=splash.set_progress)  # 构造内已创建并 show 三个模块窗口
    splash.finish()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

