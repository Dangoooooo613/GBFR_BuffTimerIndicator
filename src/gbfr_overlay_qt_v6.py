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
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QFontMetrics, QLinearGradient, QRadialGradient, QIcon, QPainter, QPen, QPainterPath, QPixmap, QImage, QPainterPathStroker
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
# 源码运行（src/）时 bundled 资源在父目录 assets/ 下，做一次回退定位
if not os.path.isfile(DEFAULT_SHRIMP_IMG_PATH):
    DEFAULT_SHRIMP_IMG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "embedded_roll_icon.png"
    )
APP_ICON_PATH = os.path.join(_BUNDLE_DIR, "app_icon.ico")
if not os.path.isfile(APP_ICON_PATH):
    APP_ICON_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "app_icon.ico"
    )

# ============================ Version ============================
APP_VERSION = "3.1"
SETTINGS_SCHEMA_VERSION = 75
APP_TITLE = "GBFR_CooldownIndicator_V301"
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
_pl_hash_map = {}

def load_char_db():
    global _char_db, _ab_hash_map, _pl_hash_map
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

def _skill_name(ab_hash_val, lang="zh"):
    g = _ab_hash_map.get(ab_hash_val)
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
CLASS_STATE_PTR_OFF = 0x1AE00      # actor -> 职业状态结构体指针
CLASS_RANK_OFF = 0x1FA4            # u32，当前层数 1~4
CLASS_DURATION_OFF = 0x1FBC        # f32，倒计时

# 伊德（Id）形态识别
ID_FORM_OFF = 0x1FD
ID_FORM_NORMAL = 0x19              # 普通/神威一体态
ID_FORM_DRAGON = 0x20              # 龙人态
# 龙人态官方父子指针（来自 gbfr-logs/GBFR-ACT 公开 RE）：真身 actor = read_u64(actor+0xd488)+0x70
ID_DRAGON_PARENT_OFF = 0xD488
ID_DRAGON_PARENT_EXTRA = 0x70

# 伊德资源槽指针链：actor+0x28 -> P，然后 P+sub 读到目标值
# sub 偏移来自同一进程多地址扫描，形态切换后绝对地址不变，因此配合锁定机制使用
ID_GAUGE_CHAIN_OFF = 0x28
ID_POWER_SUB = -0x3C22B10          # f32 0~1，异能槽
ID_CELLS_SUB = -0x3C22B18          # u32 0~4，龙人格子
ID_OVERDRIVE_SUB = -0x198D9D8      # f32 0~1，神威槽
ID_HIDDEN_OFF = 0x1CB34            # f32 0~4，隐藏槽（actor 直接偏移）

# 巴萨拉卡（PL1700）古洛诺斯槽冻结倒计时：actor 直接偏移（f32）
# 来源：gbfr_vaseraga_freeze_monitor.py 实测确认
VASERAGA_FREEZE_OFF = 0x1CAF0     # f32，古洛诺斯冻结剩余秒数（仅冻结中>0）

_profile_siegfried = {
    "buffs": [
        {"zh": "屠龙之心", "zh_tw": "滅龍的鼓動", "en": "Dragonsbane Pulse",
         "stack_status_id": 0x40, "timer_status_id": 0x40,
         "timer_display": "full_stack_only"},
        {"zh": "拂晓", "zh_tw": "拂曉", "en": "Daybreak",
         "stack_status_id": 144, "timer_status_id": 144,
         "timer_display": "any_stack", "single_layer": True},
        {"zh": "漆黑血涌", "zh_tw": "黑色血潮", "en": "Dark Zeal",
         "stack_status_id": 65, "timer_status_id": 65,
         "timer_display": "any_stack"},
    ]
}
_profile_gallanza = {
    "buffs": [
        {"zh": "武夫", "zh_tw": "荒事", "en": "Wild Showman",
         "stack_status_id": 0x72, "timer_status_id": 0x72,
         "timer_display": "any_stack"},
        {"zh": "回旋王", "zh_tw": "絕好勢", "en": "Ultimatum",
         "stack_status_id": 112, "timer_status_id": 112,
         "timer_display": "any_stack"},
    ]
}
_profile_ferry = {
    "buffs": [
        {"zh": "托愿", "zh_tw": "被託付的願望", "en": "Loving Trust",
         "stack_status_id": 0x4E, "timer_status_id": 0x4E,
         "timer_display": "any_stack"},
        {"zh": "幽缘", "zh_tw": "幽緣", "en": "Spiritbond",
         "stack_status_id": 79, "timer_status_id": 79,
         "timer_display": "any_stack"},
    ]
}
_profile_lancelot = {
    "buffs": [
        {"zh": "连击", "zh_tw": "連擊", "en": "Avalanche",
         "stack_status_id": 0x69, "timer_status_id": 0x69,
         "timer_display": "any_stack"},
    ]
}
# 伊德神威一体 ExStatus 标志（用于判断神威槽/隐藏槽是否生效）
ID_OVERDRIVE_STATUS_ID = 0x1E  # 30

_profile_id = {
    "buffs": [
        # 紫银之力：常显（人形态/龙人态/神威一体态均存在）
        {"zh": "紫银之力", "zh_tw": "紫銀之力", "en": "Heliotrope Aura",
         "stack_status_id": 0x3C, "timer_status_id": 0x3C,
         "timer_display": "any_stack"},
        # 神威一体（单层buff）：仅神威一体形态存在（require overdrive = 有神威一体 ExStatus）
        {"zh": "神威一体", "zh_tw": "神威一體", "en": "Godmight",
         "stack_status_id": ID_OVERDRIVE_STATUS_ID, "timer_status_id": ID_OVERDRIVE_STATUS_ID,
         "timer_display": "any_stack", "single_layer": True, "require": "overdrive"},
        # 龙人化（单层buff）：仅龙人态存在（require dragon_form）
        {"zh": "龙人化", "zh_tw": "龍人化", "en": "Dragonform",
         "stack_status_id": 29, "timer_status_id": 29,
         "timer_display": "any_stack", "single_layer": True, "require": "dragon_form"},
        # 化龙（单层buff）：伊德专属 debuff（sid=126=Inversa），仅龙人态存在
        {"zh": "化龙", "zh_tw": "龍深化", "en": "Inversa",
         "stack_status_id": 126, "timer_status_id": 126,
         "timer_display": "any_stack", "single_layer": True, "require": "dragon_form"},
        # 隐藏槽：非 ExStatus 裸值（actor 直接偏移）；仅神威一体形态有意义（require overdrive）
        {"zh": "隐藏槽", "zh_tw": "隱藏槽", "en": "Hidden Gauge",
         "raw_source": {"kind": "id_direct", "off": ID_HIDDEN_OFF, "fmt": "f32"},
         "gauge_mode": "float", "max_stacks": 4, "timer_display": "any_stack", "require": "overdrive"},
    ]
}
_profile_captain = {
    "buffs": [
        {"zh": "Class等级", "zh_tw": "Class等級", "en": "Class Level",
         "raw_source": {"kind": "class_state", "ptr_off": CLASS_STATE_PTR_OFF,
                        "rank_off": CLASS_RANK_OFF, "dur_off": CLASS_DURATION_OFF},
         "max_stacks": 4, "timer_display": "any_stack"},
        {"zh": "不屈攻刃", "zh_tw": "不屈攻刃", "en": "Combat Healer",
         "stack_status_id": 66, "timer_status_id": 66,
         "timer_display": "any_stack"},
    ]
}
_profile_tweyen = {
    "buffs": [
        {"zh": "致命一击强化", "zh_tw": "致命一擊強化", "en": "Enhanced Clincher",
         "stack_status_id": 0x7F, "timer_status_id": 0x7F,
         "timer_display": "any_stack"},
        {"zh": "煌矢", "zh_tw": "煌矢", "en": "Piercing Gleam",
         "stack_status_id": 109, "timer_status_id": 109,
         "timer_display": "any_stack"},
    ]
}
_profile_vaseraga = {
    "buffs": [
        {"zh": "冥刃", "zh_tw": "冥刃", "en": "Ebony Glint",
         "stack_status_id": 0x52, "timer_status_id": 0x52,
         "timer_display": "any_stack"},
        {"zh": "不死之身", "zh_tw": "不死之身", "en": "Undying",
         "stack_status_id": 0x1F, "timer_status_id": 0x1F,
         "timer_display": "any_stack", "single_layer": True},
        {"zh": "古洛诺斯之力", "zh_tw": "格羅諾斯解放", "en": "Grynoth Unleashed",
         "stack_status_id": 88, "timer_status_id": 88,
         "timer_display": "any_stack"},
        {"zh": "造成伤害UP", "zh_tw": "給予傷害UP", "en": "DMG\u2191",
         "stack_status_id": 42, "timer_status_id": 42,
         "timer_display": "any_stack"},
        {"zh": "蚀魂魔刃", "zh_tw": "蝕魂之刃", "en": "Blood-Drinking Blade",
         "stack_status_id": 138, "timer_status_id": 138,
         "timer_display": "any_stack"},
        # 古洛诺斯冻结倒计时（单层）：actor+0x1CAF0 直接偏移，仅冻结中>0 时显示
        {"zh": "古洛诺斯冻结", "zh_tw": "古洛諾斯凍結", "en": "Grynoth Freeze",
         "raw_source": {"kind": "actor_timer", "off": VASERAGA_FREEZE_OFF, "fmt": "f32", "max": 30.0},
         "single_layer": True, "timer_display": "any_stack"},
    ]
}
_profile_io = {
    "buffs": [
        {"zh": "专注", "zh_tw": "全神貫注", "en": "Focused",
         "stack_status_id": 27, "timer_status_id": 27,
         "timer_display": "any_stack", "single_layer": True},
        {"zh": "魔力漩涡", "zh_tw": "魔力漩渦", "en": "Mystic Vortex",
         "stack_status_id": 26, "timer_status_id": 26,
         "timer_display": "any_stack"},
        {"zh": "魔法连锁", "zh_tw": "魔法連擊", "en": "Magic Chain",
         "stack_status_id": 81, "timer_status_id": 81,
         "timer_display": "any_stack"},
    ]
}
_profile_maglielle = {
    "buffs": [
        {"zh": "超凡艺术", "zh_tw": "極致戰藝", "en": "Arts Superiór",
         "stack_status_id": 87, "timer_status_id": 87,
         "timer_display": "any_stack"},
    ]
}
_profile_catalina = {
    "buffs": [
        {"zh": "苍刃", "zh_tw": "蒼刃", "en": "Blade Blue",
         "stack_status_id": 69, "timer_status_id": 69,
         "timer_display": "any_stack"},
        {"zh": "双璧突击", "zh_tw": "雙重強襲", "en": "Dual Raid",
         "stack_status_id": 139, "timer_status_id": 139,
         "timer_display": "any_stack"},
        {"zh": "阿瑞斯强袭", "zh_tw": "艾瑞斯強襲", "en": "Ares Surge",
         "stack_status_id": 68, "timer_status_id": 68,
         "timer_display": "any_stack"},
    ]
}
_profile_rosetta = {
    "buffs": [
        {"zh": "落花无情强化", "zh_tw": "花散強化", "en": "Lost Love Bloomed",
         "stack_status_id": 98, "timer_status_id": 98,
         "timer_display": "any_stack", "single_layer": True},
        {"zh": "螺旋玫瑰强化", "zh_tw": "螺旋玫瑰強化", "en": "Spiral Rose Bloomed",
         "stack_status_id": 97, "timer_status_id": 97,
         "timer_display": "any_stack", "single_layer": True},
    ]
}
_profile_zeta = {
    "buffs": [
        {"zh": "跃空强化", "zh_tw": "浮空強化", "en": "Loop Master",
         "stack_status_id": 0x5E, "timer_status_id": 0x5E,
         "timer_display": "any_stack"},
    ]
}
_profile_cagliostro = {
    "buffs": [
        {"zh": "岩塌强化", "zh_tw": "大崩壞強化", "en": "Super Collapse",
         "stack_status_id": 0x56, "timer_status_id": 0x56,
         "timer_display": "any_stack"},
    ]
}
_profile_percival = {
    "buffs": [
        {"zh": "红莲之刃", "zh_tw": "紅蓮之刃", "en": "Molten Edge",
         "stack_status_id": 0x55, "timer_status_id": 0x55,
         "timer_display": "any_stack"},
        {"zh": "征战之剑＋＋强化", "zh_tw": "征戰＋＋強化", "en": "Stoked Charge",
         "stack_status_id": 83, "timer_status_id": 83,
         "timer_display": "any_stack"},
    ]
}
_profile_sandalphon = {
    "buffs": [
        {"zh": "无限之辉", "zh_tw": "無限光", "en": "Limitless Light",
         "stack_status_id": 0x6A, "timer_status_id": 0x6A,
         "timer_display": "any_stack", "single_layer": True},
        {"zh": "极彩羽翼", "zh_tw": "極彩之羽", "en": "Chromatic Wings",
         "stack_status_id": 45, "timer_status_id": 45,
         "timer_display": "any_stack", "single_layer": True},
        {"zh": "白辉祝福", "zh_tw": "白輝之加護", "en": "Lucent Refuge",
         "stack_status_id": 107, "timer_status_id": 107,
         "timer_display": "any_stack"},
    ]
}
_profile_seofon = {
    "buffs": [
        {"zh": "剑王", "zh_tw": "劍王", "en": "Sovereign",
         "stack_status_id": 0x74, "timer_status_id": 0x74,
         "timer_display": "any_stack"},
        {"zh": "星海", "zh_tw": "星海", "en": "Star Sea",
         "stack_status_id": 0x75, "timer_status_id": 0x75,
         "timer_display": "any_stack"},
        {"zh": "集谛", "zh_tw": "集諦", "en": "Samudaya",
         "stack_status_id": 133, "timer_status_id": 133,
         "timer_display": "any_stack"},
    ]
}

# ============================ 新增角色 Buff 配置 ============================
_profile_rackam = {
    "buffs": [
        {"zh": "双发子弹", "zh_tw": "雙連擊", "en": "Double Tap",
         "stack_status_id": 38, "timer_status_id": 38,
         "timer_display": "any_stack", "single_layer": True},
        {"zh": "靶心狙击强化", "zh_tw": "靶心狙擊強化", "en": "Super Bull's Eye Blast",
         "stack_status_id": 70, "timer_status_id": 70,
         "timer_display": "any_stack", "single_layer": True},
    ]
}
_profile_barn = {
    "buffs": [
        {"zh": "强化回馈", "zh_tw": "協同增幅", "en": "Synergy Boost",
         "stack_status_id": 93, "timer_status_id": 93,
         "timer_display": "any_stack"},
    ]
}
_profile_charlotte = {
    "buffs": [
        {"zh": "崇高指令", "zh_tw": "高潔秩序", "en": "Noble Order",
         "stack_status_id": 74, "timer_status_id": 74,
         "timer_display": "any_stack"},
    ]
}
_profile_eustace = {
    "buffs": [
        {"zh": "弗拉梅克之力", "zh_tw": "弗拉梅格解放", "en": "Flamek Unleashed",
         "stack_status_id": 118, "timer_status_id": 118,
         "timer_display": "any_stack"},
    ]
}
_profile_fif = {
    "buffs": [
        {"zh": "连击收招强化", "zh_tw": "連技終擊強化", "en": "Enhanced Combo Finishers",
         "stack_status_id": 123, "timer_status_id": 123,
         "timer_display": "any_stack"},
        {"zh": "暗灾", "zh_tw": "闇禍", "en": "Malice",
         "stack_status_id": 124, "timer_status_id": 124,
         "timer_display": "any_stack"},
    ]
}

# ============================ 通用 Buff（全角色生效的状态效果）============================
_profile_general = {
    "buffs": [
        {"zh": "再生", "zh_tw": "再生", "en": "Regen",
         "stack_status_id": 5, "timer_status_id": 5, "timer_display": "any_stack"},
        {"zh": "无敌", "zh_tw": "無敵", "en": "Invincibility",
         "stack_status_id": 6, "timer_status_id": 6, "timer_display": "any_stack", "single_layer": True},
        {"zh": "追击", "zh_tw": "追擊", "en": "Supplementary DMG",
         "stack_status_id": 7, "timer_status_id": 7, "timer_display": "any_stack"},
        {"zh": "霸体", "zh_tw": "畏怯無效", "en": "Stout Heart",
         "stack_status_id": 8, "timer_status_id": 8, "timer_display": "any_stack"},
        {"zh": "挺身而出", "zh_tw": "挺身掩護", "en": "Substitute",
         "stack_status_id": 10, "timer_status_id": 10, "timer_display": "any_stack", "single_layer": True},
        {"zh": "弱化免疫", "zh_tw": "弱化無效", "en": "Debuff Immunity",
         "stack_status_id": 17, "timer_status_id": 17, "timer_display": "any_stack"},
        {"zh": "暴击率UP", "zh_tw": "爆擊機率UP", "en": "Critical Hit Rate\u2191",
         "stack_status_id": 23, "timer_status_id": 23, "timer_display": "any_stack"},
        {"zh": "豪胆", "zh_tw": "堅毅", "en": "Guts",
         "stack_status_id": 20, "timer_status_id": 20, "timer_display": "any_stack", "single_layer": True},
        {"zh": "自动复活", "zh_tw": "自動復活", "en": "Autorevive",
         "stack_status_id": 25, "timer_status_id": 25, "timer_display": "any_stack", "single_layer": True},
    ]
}

BUFF_PROFILES = {
    # pl_id 键（推荐，charid hash 直接命中）
    "PL0000": _profile_captain,
    "PL0100": _profile_captain,
    "PL0200": _profile_catalina,
    "PL0300": _profile_rackam,
    "PL0400": _profile_io,
    "PL0600": _profile_rosetta,
    "PL0700": _profile_ferry,
    "PL0800": _profile_lancelot,
    "PL0900": _profile_barn,
    "PL1000": _profile_percival,
    "PL1100": _profile_siegfried,
    "PL1200": _profile_charlotte,
    "PL1600": _profile_zeta,
    "PL1700": _profile_vaseraga,
    "PL1800": _profile_cagliostro,
    "PL1900": _profile_id,
    "PL2100": _profile_sandalphon,
    "PL2200": _profile_seofon,
    "PL2300": _profile_tweyen,
    "PL2400": _profile_gallanza,
    "PL2500": _profile_maglielle,
    "PL2700": _profile_eustace,
    "PL2900": _profile_fif,
    "GENERAL": _profile_general,
    # 0x1FD char_type 键（回退兼容）
    0x11: _profile_siegfried,
    0x24: _profile_gallanza,
    0x07: _profile_ferry,
    0x08: _profile_lancelot,
    0x19: _profile_id,
    0x20: _profile_id,
    0x23: _profile_tweyen,
    0x17: _profile_vaseraga,
    0x16: _profile_zeta,
    0x18: _profile_cagliostro,
    0x10: _profile_percival,
    0x22: _profile_seofon,
}


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
        self._lang = lang
        # title 可以是 str（固定标题）或 dict（{"zh","zh_tw","en"} 多语标题）
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
        # 标题：支持 str / dict（多语） / None（自动 PL 名）
        if title is None:
            _ttl = _pl_display_name(self.pl_ids[0], lang)
        elif isinstance(title, dict):
            _ttl = title.get(lang, title.get("zh", ""))
        else:
            _ttl = title
        self._title_lbl = QLabel(_ttl)
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
        _col_map = {"zh": {}, "zh_tw": zh_to_tw, "en": zh_to_en}.get(self._lang, {})
        def _ct(text):
            return _col_map.get(text, text)
        lbl_shown = QLabel(_ct("生效区（拖动排序）")); lbl_shown.setStyleSheet("color:#b0c4e0;font-size:10px;")
        lbl_hidden = QLabel(_ct("隐藏区")); lbl_hidden.setStyleSheet("color:#b0c4e0;font-size:10px;")
        self._lbl_shown = lbl_shown
        self._lbl_hidden = lbl_hidden
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

        hint = QLabel(_ct("左栏=显示，右栏=隐藏；拖到另一侧切换（不可跨角色）"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8aa0c0;font-size:10px;")
        self._hint = hint
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
        disp = ("✕ " if hidden else "") + label + (self._tt("（单层buff）") if sl else "")
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
            item.setText("✕ " + label + (self._tt("（单层buff）") if sl else ""))
            item.setForeground(QColor(255, 95, 95, 204))
        for i in range(self.shown_list.count()):
            item = self.shown_list.item(i)
            idx = item.data(Qt.UserRole)
            label, sl = self._meta.get(idx, ("", False))
            item.setText(label + (self._tt("（单层buff）") if sl else ""))
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
            act_top = menu.addAction(self._tt("置顶"))
            act_toggle = menu.addAction(self._tt("隐藏"))
            choiced = menu.exec_(source_list.mapToGlobal(pos))
            if choiced == act_top:
                self._move_top(idx)
            elif choiced == act_toggle:
                self._move_idx(idx, to_hidden=True, at_row=None)
        else:
            act_toggle = menu.addAction(self._tt("显示"))
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

    def _tt(self, text):
        m = {"zh": {}, "zh_tw": zh_to_tw, "en": zh_to_en}.get(self._lang, {})
        return m.get(text, text)

    def refresh_title(self, lang):
        self._lang = lang
        if self._title_override:
            t = self._title_override
            if isinstance(t, dict):
                self._title_lbl.setText(t.get(lang, t.get("zh", "")))
            else:
                self._title_lbl.setText(t)
        else:
            self._title_lbl.setText(_pl_display_name(self.pl_ids[0], lang))
        _col_map = {"zh": {}, "zh_tw": zh_to_tw, "en": zh_to_en}.get(lang, {})
        self._lbl_shown.setText(_col_map.get("生效区（拖动排序）", "生效区（拖动排序）"))
        self._lbl_hidden.setText(_col_map.get("隐藏区", "隐藏区"))
        self._hint.setText(_col_map.get("左栏=显示，右栏=隐藏；拖到另一侧切换（不可跨角色）",
                                        "左栏=显示，右栏=隐藏；拖到另一侧切换（不可跨角色）"))

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


def read_overlay_data(handle, pptr, raw_locked=None):
    """读取角色层数、翻滚次数和全部角色专属 buff。

    通过 ExStatus 指针数组 + 裸值资源槽读取 buff 数据。
    返回 {status, dodge, char_type, buffs: [...], raw_locked}.
    buffs 列表每个条目: {index, zh, en, stacks, max_stacks, timer, timer_max, timer_display, gauge_mode?, gauge_value?}.
    """
    char_base = read_u64(handle, pptr + CHAR_PTR_OFF)
    if not char_base:
        return {"status": "no_char", "dodge": None, "char_type": 0, "buffs": [], "raw_locked": raw_locked or {}}
    dodge = read_u32(handle, char_base + FIELD_DODGE)

    # 伊德龙人态：ExStatus（如紫银之力 0x3C）挂在真身 actor 上；龙人态时 party 指针指向的是
    # 外壳 actor，需用官方父子指针回到真身再读，否则龙人态下紫银之力读不到 / 不显示。
    read_base, _ = _resolve_id_actor(handle, char_base)
    char_type = read_u8(handle, read_base + FIELD_CHAR_TYPE) or 0
    charid_hash = read_u32(handle, read_base + CHARID_HASH_OFFSET) or 0

    all_buffs = read_exstatus_buffs(handle, read_base)
    # 优先 charid hash -> pl_id -> BUFF_PROFILES，回退 0x1FD char_type -> BUFF_PROFILES
    pl_id = _pl_hash_map.get(charid_hash)
    if not pl_id and char_type in CHAR_TYPE_TO_PL:
        pl_id = CHAR_TYPE_TO_PL[char_type]
    profile = BUFF_PROFILES.get(pl_id) or BUFF_PROFILES.get(char_type)
    buffs_out = []
    new_locked = raw_locked or {}

    if profile:
        # 先读 ExStatus buff
        exstatus_buffs = []
        raw_indices = set()
        for idx, buff_cfg in enumerate(profile["buffs"]):
            if buff_cfg.get("raw_source"):
                raw_indices.add(idx)
                continue
            # 条件生效：神威一体等仅在神威一体形态（有 神威一体 ExStatus）时出现
            require = buff_cfg.get("require")
            if require == "overdrive" and ID_OVERDRIVE_STATUS_ID not in all_buffs:
                continue
            # 占位 buff（status id 全为 0）= 尚未从 CE 配置，跳过不显示
            stack_sid = buff_cfg.get("stack_status_id")
            timer_sid = buff_cfg.get("timer_status_id")
            if not stack_sid and not timer_sid:
                continue
            timer_sid = buff_cfg.get("timer_status_id")
            stacks = 0
            max_stacks = None
            timer = None
            timer_max = None

            if stack_sid and stack_sid in all_buffs:
                b = all_buffs[stack_sid]
                stacks = b["stacks"]
                max_stacks = b["max_stacks"] or None

            if timer_sid and timer_sid in all_buffs:
                b = all_buffs[timer_sid]
                if not b["infinite"]:
                    timer = b["remaining"]
                    timer_max = b["initial"] or None

            exstatus_buffs.append({
                "index": idx,
                "zh": buff_cfg["zh"],
                "zh_tw": buff_cfg.get("zh_tw", buff_cfg["zh"]),
                "en": buff_cfg["en"],
                "stacks": stacks,
                "max_stacks": max_stacks,
                "timer": timer,
                "timer_max": timer_max,
                "timer_display": buff_cfg.get("timer_display", "any_stack"),
                "single_layer": bool(buff_cfg.get("single_layer", False)),
            })

        # 再读裸值 buff（需要状态锁定）
        raw_buffs, new_locked = read_raw_buffs(handle, char_base, profile, locked_addrs=raw_locked, all_buffs=all_buffs)

        # 合并：按原 profile 顺序排列
        for idx in range(len(profile["buffs"])):
            if idx in raw_buffs:
                buffs_out.append(raw_buffs[idx])
            elif idx < len(exstatus_buffs):
                buffs_out.append(exstatus_buffs[idx])

    # 通用 Buff（全角色生效的状态效果）：从 ExStatus 中匹配，仅显示有层数或有倒计时的
    gen_profile = BUFF_PROFILES.get("GENERAL")
    if gen_profile:
        for idx, buff_cfg in enumerate(gen_profile["buffs"]):
            stack_sid = buff_cfg.get("stack_status_id")
            timer_sid = buff_cfg.get("timer_status_id")
            if not stack_sid and not timer_sid:
                continue
            stacks = 0
            max_stacks = None
            timer = None
            timer_max = None
            if stack_sid and stack_sid in all_buffs:
                b = all_buffs[stack_sid]
                stacks = b["stacks"]
                max_stacks = b["max_stacks"] or None
            if timer_sid and timer_sid in all_buffs:
                b = all_buffs[timer_sid]
                if not b["infinite"]:
                    timer = b["remaining"]
                    timer_max = b["initial"] or None
            # 仅在 buff 实际存在（有层数或有计时器）时加入
            if stacks <= 0 and (timer is None or timer <= 0):
                continue
            buffs_out.append({
                "index": idx,
                "group": "GENERAL",
                "zh": buff_cfg.get("zh", ""),
                "zh_tw": buff_cfg.get("zh_tw", buff_cfg.get("zh", "")),
                "en": buff_cfg.get("en", ""),
                "stacks": stacks,
                "max_stacks": max_stacks,
                "timer": timer,
                "timer_max": timer_max,
                "timer_display": buff_cfg.get("timer_display", "any_stack"),
                "single_layer": bool(buff_cfg.get("single_layer", False)),
            })

    return {"status": "ok", "dodge": dodge or 0, "char_type": char_type,
            "charid_hash": charid_hash, "pl_id": pl_id, "buffs": buffs_out,
            "raw_locked": new_locked}


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
        dur_off = src.get("dur_off", CLASS_DURATION_OFF)
        return P + dur_off, locked, True  # 返回 duration 地址；调用处同时读 rank
    if kind == "id_direct":
        addr = actor + src.get("off", 0)
        return addr, addr, True
    if kind == "id_chain":
        actor_off = src.get("actor_off", ID_GAUGE_CHAIN_OFF)
        sub = src.get("sub", 0)
        P = read_u64(handle, actor + actor_off)
        if not P:
            if locked:
                return locked, locked, True
            return 0, locked, False
        calc = (P + sub) & 0xFFFFFFFFFFFFFFFF
        if locked == 0:
            return calc, calc, True
        # 计算结果与锁定地址偏离不大则更新锁定；偏离大则形态切换，读锁定地址
        if abs(calc - locked) < 0x100000:
            return calc, calc, True
        return locked, locked, True
    if kind == "actor_timer":
        # 巴萨拉卡古洛诺斯冻结：actor 直接偏移读 f32 倒计时
        addr = actor + src.get("off", 0)
        return addr, 0, True
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

        # 古洛诺斯冻结倒计时：仅冻结中 >0，非冻结时为 0，跳过不显示
        if kind == "actor_timer":
            if v <= 0.01:
                continue
            timer = v
            timer_max = src.get("max", 30.0)
            out[idx] = {
                "index": idx,
                "zh": buff_cfg.get("zh", ""),
                "zh_tw": buff_cfg.get("zh_tw", buff_cfg.get("zh", "")),
                "en": buff_cfg.get("en", ""),
                "stacks": 0,
                "max_stacks": 0,
                "timer": timer,
                "timer_max": timer_max,
                "timer_display": buff_cfg.get("timer_display", "any_stack"),
                "single_layer": bool(buff_cfg.get("single_layer", False)),
                "gauge_mode": buff_cfg.get("gauge_mode"),
                "gauge_value": None,
            }
            continue

        max_stacks = buff_cfg.get("max_stacks")
        if max_stacks is None:
            max_stacks = 4 if fmt == "f32" else 7

        # 值域校验：明显越界说明链/偏移不对，放弃本次读取
        # actor_timer（冻结倒计时）跳过 stacks 值域校验，单独处理
        if kind not in ("class_state", "actor_timer"):
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
                dur = read_f32(handle, P + src.get("dur_off", CLASS_DURATION_OFF))
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
    ("bg_color", "背景色:"),
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

# 锁定时需要减半不透明度的颜色键（仅标题栏、背景、图标；层数UI和翻滚UI不受影响）
LOCK_HALVED_KEYS = {"title_bar_color", "icon_color"}

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
    "bg_color": "#000000",
    "bg_color_opacity": 0,
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
    "dodge_outline_enabled": True,        # 翻滚模块：沿图案轮廓常驻勾边（与闪光解耦）
    "dodge_outline_width": 2.0,           # 翻滚勾边：贴边描边粗细(px，相对图标分辨率）
    # ── 警告牌（翻滚第6/7次）可调参数 ──
    "warning_size_scale": 0.68,           # 警告三角相对图标槽的缩放（0.3~1.0）
    "warning_outline_color": "#e53935",   # 外部红色圆角三角边框色
    "warning_outline_color_opacity": 100,
    "warning_fill_color": "#ffef00",      # 内部黄色填充色
    "warning_fill_color_opacity": 100,
    "warning_outline_width": 0.24,        # 红色边框粗度（占三角形边长比例 0.05~0.5）
    "dodge_outline_glow": 5.0,            # 翻滚勾边：外扩辉光宽度(px)
    "dodge_outline_threshold": 24,        # 翻滚勾边：alpha 阈值(>该值视为图案像素)
    # ── 翻滚模块布局方向 ──
    "roll_orientation": "horizontal",     # horizontal / vertical
    # ── 各模块独立屏幕位置（取代旧的 shrimp_gap_circle / 分割线 相对定位）──
    "core_window_x": 424,
    "core_window_y": 696,
    "roll_window_x": 620,
    "roll_window_y": 770,
    "skill_window_x": 300,
    "skill_window_y": 770,
    "classmech_window_x": 300,
    "classmech_window_y": 860,
    "classmech_scale_percent": 100,
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
    # buff 顺位：{ "PLxxxx_idx": rank }，1-based；0 或缺失=不显示（按 profile 默认顺序）
    "buff_order": {},
    # ── 多buff差异化（按同时监测的buff个数 2/3/4/5 分组，每组 5 参数 = 20）──
    # 每个分组含：缩放% / 圆心水平间距px / 圆心Delta_Y(px，垂直错位) / 外部差异化颜色 / 内部差异化颜色
    "multi_buff_scale_2": 80, "multi_buff_hgap_2": 110, "multi_buff_dy_2": 34,
    "multi_buff_ext_color_2": True, "multi_buff_int_color_2": True,
    "multi_buff_scale_3": 70, "multi_buff_hgap_3": 104, "multi_buff_dy_3": 30,
    "multi_buff_ext_color_3": True, "multi_buff_int_color_3": True,
    "multi_buff_scale_4": 60, "multi_buff_hgap_4": 98, "multi_buff_dy_4": 26,
    "multi_buff_ext_color_4": True, "multi_buff_int_color_4": True,
    "multi_buff_scale_5": 52, "multi_buff_hgap_5": 92, "multi_buff_dy_5": 22,
    "multi_buff_ext_color_5": True, "multi_buff_int_color_5": True,
    "show_buff_name": False,
    "buff_name_font_size": 8,
    "buff_name_offset_x": 0,
    "buff_name_offset_y": -4,
    "buff_name_bg_width": -4,
    "buff_name_color": "#ff0000",
    "buff_name_color_opacity": 80,
    # ── 技能冷却 (Cooldown Indicator) ──
    "show_skill_cd": True,
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
    "skill_cd_breath_color": "#ffffff",     # 光颜色（默认白色）
    "skill_cd_breath_color_opacity": 65,    # 峰值不透明度%
    "skill_cd_breath_freq": 0.5,            # 呼吸频率（Hz，每秒呼吸次数）
    "skill_cd_breath_soft": 0.5,            # 柔和程度（0~1，越大越扩散柔和；真正控制渐变衰减指数）
    "skill_cd_breath_size": 1.9,            # 光圈大小（半径倍率，相对能力尺寸 s；控制光晕扩散半径）
    "skill_cooldown_max": {},
    # ── 在线更新检测 ──
    "auto_check_update": True,      # 启动/定时自动检查更新
    "skip_version": "",             # 跳过的版本号（不再提示）
    "update_check_url": "https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases/latest/download/version.json",  # version.json 地址（默认走 releases 下载 CDN，国内比 raw 快；留空则禁用检查）
    # ── 启动与界面 ──
    "splash_enabled": True,        # 启动时是否显示读条窗口
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
        # V270：旧版「翻滚图标闪光：勾边发光」开关 → 新版独立的「沿图案轮廓勾边」
        if "flash_dodge_outline" in data and "dodge_outline_enabled" not in data:
            try:
                data["dodge_outline_enabled"] = bool(data["flash_dodge_outline"])
            except Exception:
                pass
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
        if data.get("settings_schema_version") != SETTINGS_SCHEMA_VERSION:
            preserved = {}
            for key in DEFAULT_SETTINGS:
                if key in data:
                    preserved[key] = data[key]
            merged = dict(DEFAULT_SETTINGS)
            merged.update(preserved)
            save_settings(merged)
            return merged
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
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
class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    def __init__(self, parent, settings, ctrl=None):
        super().__init__(parent)
        self.setWindowTitle("Overlay 设置")
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
        self.dodge_outline_enabled_chk = QCheckBox("翻滚闪光·白色实心勾边")
        self.dodge_outline_enabled_chk.setChecked(bool(self.settings.get("dodge_outline_enabled", DEFAULT_SETTINGS["dodge_outline_enabled"])))
        cf.addRow(self.dodge_outline_enabled_chk)
        self.dodge_outline_width_dspn = QDoubleSpinBox(); self.dodge_outline_width_dspn.setRange(0.5, 8.0); self.dodge_outline_width_dspn.setSingleStep(0.5); self.dodge_outline_width_dspn.setDecimals(1); self.dodge_outline_width_dspn.setSuffix("px"); self.dodge_outline_width_dspn.setValue(float(self.settings.get("dodge_outline_width", DEFAULT_SETTINGS["dodge_outline_width"])))
        cf.addRow("勾边粗细:", self.dodge_outline_width_dspn)
        self.dodge_outline_glow_dspn = QDoubleSpinBox(); self.dodge_outline_glow_dspn.setRange(0.0, 20.0); self.dodge_outline_glow_dspn.setSingleStep(0.5); self.dodge_outline_glow_dspn.setDecimals(1); self.dodge_outline_glow_dspn.setSuffix("px"); self.dodge_outline_glow_dspn.setValue(float(self.settings.get("dodge_outline_glow", DEFAULT_SETTINGS["dodge_outline_glow"])))
        cf.addRow("勾边辉光:", self.dodge_outline_glow_dspn)
        f.addRow(card)

        # ============ 顶级标签 2: 核心检测模块 ============
        c_sub = make_top_tab("核心检测模块")
        # 标题栏
        f = make_sub_tab(c_sub, "标题栏")
        card, cf = make_card(f, "── 标题栏 ──")
        self.show_titlebar_status = QCheckBox("在标题栏显示角色名和buff状态文字")
        self.show_titlebar_status.setChecked(bool(self.settings.get("show_titlebar_status", DEFAULT_SETTINGS["show_titlebar_status"])))
        cf.addRow("标题栏状态文字:", self.show_titlebar_status)
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

        def _mb_slider(target, label, key, default, rmin, rmax, suffix):
            sl = QSlider(Qt.Horizontal); sl.setRange(rmin, rmax)
            sp = QSpinBox(); sp.setRange(rmin, rmax); sp.setSuffix(suffix)
            v = int(self.settings.get(key, default)); sl.setValue(v); sp.setValue(v)
            sl.valueChanged.connect(sp.setValue); sp.valueChanged.connect(sl.setValue)
            sl.valueChanged.connect(self._emit_changed)
            row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
            row.addWidget(sl); row.addWidget(sp)
            c = QWidget(); c.setLayout(row); target.addRow(label, c)
            return sl, sp

        def _mb_check(target, label, key, default):
            cb = QCheckBox(); cb.setChecked(bool(self.settings.get(key, default)))
            cb.stateChanged.connect(self._emit_changed)
            target.addRow(label, cb)
            return cb

        self.multi_buff_ctrls = {}
        for cnt in (2, 3, 4, 5):
            # 每个 buff 个数各包一个小组框，实现不同个数之间的隔离
            gb = QGroupBox(f"{cnt} 个 buff 同屏")
            gb.setStyleSheet("QGroupBox{border:1px solid #3a4a66;border-radius:6px;margin-top:6px;"
                             "padding-top:10px;color:#cfe0ff;font-weight:bold;font-size:11px;}"
                             "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
            gcf = QFormLayout(); gcf.setContentsMargins(8, 8, 8, 8); gcf.setSpacing(4)
            gb.setLayout(gcf)
            ctrl = {}
            ctrl["scale_sl"], ctrl["scale_sp"] = _mb_slider(gcf, f"缩放{cnt}:", f"multi_buff_scale_{cnt}", DEFAULT_SETTINGS[f"multi_buff_scale_{cnt}"], 20, 100, "%")
            ctrl["hgap_sl"], ctrl["hgap_sp"] = _mb_slider(gcf, f"圆心水平间距{cnt}:", f"multi_buff_hgap_{cnt}", DEFAULT_SETTINGS[f"multi_buff_hgap_{cnt}"], 20, 400, "px")
            ctrl["dy_sl"], ctrl["dy_sp"] = _mb_slider(gcf, f"圆心Delta_Y{cnt}:", f"multi_buff_dy_{cnt}", DEFAULT_SETTINGS[f"multi_buff_dy_{cnt}"], -300, 300, "px")
            ctrl["ext_cb"] = _mb_check(gcf, f"外部差异化颜色{cnt}:", f"multi_buff_ext_color_{cnt}", DEFAULT_SETTINGS[f"multi_buff_ext_color_{cnt}"])
            ctrl["int_cb"] = _mb_check(gcf, f"内部差异化颜色{cnt}:", f"multi_buff_int_color_{cnt}", DEFAULT_SETTINGS[f"multi_buff_int_color_{cnt}"])
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
        f = make_sub_tab(c_sub, "隐藏与位置")
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
        # Buff启用/禁用 + 顺位（拖拽排序 + 分组框）
        f = make_sub_tab(c_sub, "Buff启用/禁用")
        lang = self.settings.get("language", "zh")
        card, cf = make_card(f, "── 角色 Buff 顺位（左栏显示·右栏隐藏 / 拖动切换 / 右键置顶 / 可折叠） ──")
        # 全局按钮
        buff_btn_row = QHBoxLayout(); buff_btn_row.setContentsMargins(0, 0, 0, 0); buff_btn_row.setSpacing(8)
        self.buff_btn_all = QPushButton("全显示"); self.buff_btn_none = QPushButton("全不显示")
        self.buff_btn_all.setAutoDefault(False); self.buff_btn_none.setAutoDefault(False)
        buff_btn_row.addWidget(self.buff_btn_all); buff_btn_row.addWidget(self.buff_btn_none); buff_btn_row.addStretch()
        buff_btn_container = QWidget(); buff_btn_container.setLayout(buff_btn_row); cf.addRow(buff_btn_container)
        self.buff_order_groups = {}
        buff_order = self.settings.get("buff_order", {})
        # 仅遍历 pl_id 字符串键（0x1FD 整数键为回退重复，跳过）；按角色编号从小到大排序。
        pl_profiles = [(k, v) for k, v in BUFF_PROFILES.items() if isinstance(k, str)]
        pl_profiles.sort(key=lambda kv: int(kv[0][2:]) if kv[0].startswith("PL") and kv[0][2:].isdigit() else 0)
        # 团长合并组：古兰(PL0000) / 姬塔(PL0100) 共享 Class等级，合并为一个分组
        CAPTAIN_TITLE = {
            "zh": "团长（古兰/姬塔）",
            "zh_tw": "團長（古蘭/姬塔）",
            "en": "Captain (Gran/Katalina)",
        }
        captain_group = BuffOrderGroup(
            ["PL0000", "PL0100"], _profile_captain, buff_order, lang,
            title=CAPTAIN_TITLE,
        )
        captain_group.orderChanged.connect(self._emit_changed)
        self.buff_order_groups["CAPTAIN"] = captain_group
        cf.addRow(captain_group)
        # 其余角色（排除团长两个 pl_id，避免重复分组）
        for pl_id, profile in pl_profiles:
            if pl_id in ("PL0000", "PL0100", "GENERAL"):
                continue
            group = BuffOrderGroup([pl_id], profile, buff_order, lang)
            group.orderChanged.connect(self._emit_changed)
            self.buff_order_groups[pl_id] = group
            cf.addRow(group)
        # 通用 Buff 分组（全角色生效）
        GENERAL_TITLE = {
            "zh": "通用 Buff（全角色）",
            "zh_tw": "通用 Buff（全角色）",
            "en": "General Buffs (All Characters)",
        }
        general_group = BuffOrderGroup(
            ["GENERAL"], _profile_general, buff_order, lang,
            title=GENERAL_TITLE,
        )
        general_group.orderChanged.connect(self._emit_changed)
        self.buff_order_groups["GENERAL"] = general_group
        cf.addRow(general_group)
        self.buff_btn_all.clicked.connect(lambda: self._set_all_buff_rank(True))
        self.buff_btn_none.clicked.connect(lambda: self._set_all_buff_rank(False))
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
        # 警告牌（翻滚第6/7次）可调参数
        card, cf = make_card(f, "── 翻滚警告牌（第6/7次）──")
        self.warning_size_dspn = QDoubleSpinBox(); self.warning_size_dspn.setRange(0.30, 1.00); self.warning_size_dspn.setSingleStep(0.02); self.warning_size_dspn.setDecimals(2); self.warning_size_dspn.setSuffix("x"); self.warning_size_dspn.setValue(float(self.settings.get("warning_size_scale", DEFAULT_SETTINGS["warning_size_scale"])))
        cf.addRow("图标大小:", self.warning_size_dspn)
        self.warning_outline_w_dspn = QDoubleSpinBox(); self.warning_outline_w_dspn.setRange(0.03, 0.50); self.warning_outline_w_dspn.setSingleStep(0.01); self.warning_outline_w_dspn.setDecimals(2); self.warning_outline_w_dspn.setSuffix("x"); self.warning_outline_w_dspn.setValue(float(self.settings.get("warning_outline_width", DEFAULT_SETTINGS["warning_outline_width"])))
        cf.addRow("外边粗细:", self.warning_outline_w_dspn)
        self._add_color_row(cf, "warning_outline_color", "外部边色:")
        self._add_color_row(cf, "warning_fill_color", "内部填充色:")
        f.addRow(card)
        # 翻滚模块位置与缩放（从原"模块位置"顶级标签迁入）
        f = make_sub_tab(r_sub, "位置与缩放")
        card, cf = make_card(f, "── 翻滚模块位置与缩放 ──")
        self.roll_x_spn, self.roll_y_spn = _mk_pos_row(cf, "roll_window_x", "roll_window_y")
        self.roll_scale_slider, self.roll_scale_spin = _mk_scale_row(cf, "roll", "模块缩放:")
        f.addRow(card)
        # ============ 顶级标签 4: 能力模块 ============
        s_sub = make_top_tab("能力模块")
        f = make_sub_tab(s_sub, "能力冷却")
        card, cf = make_card(f, "── 能力冷却 ──")
        self.skill_cd_show_chk = QCheckBox("显示能力冷却")
        self.skill_cd_show_chk.setChecked(bool(self.settings.get("show_skill_cd", True)))
        cf.addRow(self.skill_cd_show_chk)
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
        self.skill_cd_breath_soft_dspn = QDoubleSpinBox(); self.skill_cd_breath_soft_dspn.setRange(0.0, 1.0); self.skill_cd_breath_soft_dspn.setSingleStep(0.05); self.skill_cd_breath_soft_dspn.setDecimals(2); self.skill_cd_breath_soft_dspn.setValue(float(self.settings.get("skill_cd_breath_soft", 0.5)))
        cf.addRow("柔和程度(0紧~1散):", self.skill_cd_breath_soft_dspn)
        self.skill_cd_breath_size_dspn = QDoubleSpinBox(); self.skill_cd_breath_size_dspn.setRange(0.5, 4.0); self.skill_cd_breath_size_dspn.setSingleStep(0.1); self.skill_cd_breath_size_dspn.setDecimals(2); self.skill_cd_breath_size_dspn.setSuffix("×"); self.skill_cd_breath_size_dspn.setValue(float(self.settings.get("skill_cd_breath_size", 1.9)))
        cf.addRow("光圈大小:", self.skill_cd_breath_size_dspn)
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
        self.splash_cb = QCheckBox("启动时显示读条窗口")
        self.splash_cb.setChecked(bool(self.settings.get("splash_enabled", True)))
        self.splash_cb.setToolTip("关闭后双击 exe 不再弹出启动读条，直接进入主界面")
        cf.addRow(self.splash_cb)
        self.update_url_le = QLineEdit(self.settings.get("update_check_url", "") or "")
        self.update_url_le.setPlaceholderText("https://.../version.json")
        cf.addRow("更新地址：", self.update_url_le)
        self.changelog_edit = QPlainTextEdit()
        self.changelog_edit.setReadOnly(True)
        self.changelog_edit.setMaximumHeight(120)
        self.changelog_edit.setStyleSheet("background:rgba(20,26,40,0.6); color:#cdd6e0; border-radius:6px;")
        cf.addRow("更新日志：", self.changelog_edit)
        self.dump_mem_btn = QPushButton("导出角色内存(找偏移用)")
        self.dump_mem_btn.setToolTip("把当前角色 actor 内存按 u32 导出到桌面 actor_dump.txt，用于定位 class/异能 等裸值偏移")
        self.dump_mem_btn.clicked.connect(self._on_dump_memory_clicked)
        cf.addRow("内存探针：", self.dump_mem_btn)
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
        zh_to_en = {
            "Overlay 设置": "Overlay Settings",
            "── 常规 ──": "── General ──",
            "语言 / Language:": "Language:",
            "随游戏前后台:": "Game focus:",
            "游戏在前台时显示，切到后台时自动最小化": "Show when game is focused; minimize when game is in background",
            "随分辨率放大:": "Resolution scale:",
            "按当前屏幕宽度自动放大": "Auto scale by current screen width",
            "尖刺圆隐藏:": "Spike hide:",
            "无buff时隐藏尖刺圆模块（翻滚/技能UI不受影响）": "Hide spike module when no buff (dodge/skill UI unaffected)",
            "隐藏时透明度:": "Hidden opacity:",
            "倒计时字号:": "Timer font size:",
            "时间胶囊宽度:": "Capsule width:",
            "胶囊宽度微调(Δ):": "Capsule width Δ:",
            "尖刺UI不透明度:": "Spike UI opacity:",
            "翻滚UI不透明度:": "Dodge UI opacity:",
            "技能CD不透明度:": "Skill CD opacity:",
            "标题栏状态文字:": "Title bar status text:",
            "在标题栏显示角色名和buff状态文字": "Show character name and buff status text in title bar",
            "标题栏不透明度:": "Title bar opacity:",
            "背景画布不透明度:": "Background opacity:",
            "── 透明度 ──": "── Opacity ──",
            "── 背景 ──": "── Background ──",
            "── 标题栏 ──": "── Title Bar ──",
            "多buff偏移量:": "Multi-buff offset:",
            "多buff缩放:": "Multi-buff scale:",
            "多buff夹角:": "Multi-buff angle:",
            "Buff 启用/禁用:": "Buff Enable/Disable:",
            "全选": "Select All",
            "全不选": "Deselect All",
            "全显示": "Show All",
            "全不显示": "Hide All",
            "生效区（拖动排序）": "Active (drag to reorder)",
            "隐藏区": "Hidden",
            "左栏=显示，右栏=隐藏；拖到另一侧切换（不可跨角色）": "Left=shown, right=hidden; drag to switch (no cross-char)",
            "（单层buff）": "(single-layer)",
            "启用就绪呼吸光": "Enable Ready Glow",
            "导出角色内存(找偏移用)": "Dump Character Memory (offset finding)",
            "关闭后双击 exe 不再弹出启动读条，直接进入主界面": "No splash next launch: double-clicking the exe opens the main UI directly",
            "把当前角色 actor 内存按 u32 导出到桌面 actor_dump.txt，用于定位 class/异能 等裸值偏移": "Exports current actor memory as u32 rows to Desktop actor_dump.txt, for locating raw offsets (class / Id gauge, etc.)",
            "未进入战斗时隐藏整个UI（尖刺圆/翻滚/技能UI 全部）": "Hide entire UI when not in battle (spike ring / roll / skill UI)",
            "检查中…": "Checking…",
            "已跳过 v": "Skipped v",
            "启动中…": "Starting…",
            "准备": "Ready",
            "完成": "Done",
            "正在加载设置…": "Loading settings…",
            "已加载角色数据库": "Character database loaded",
            "正在计算界面布局…": "Computing layout…",
            "正在加载图标资源…": "Loading icon resources…",
            "已创建悬浮窗口": "Floating windows created",
            "已初始化系统托盘": "System tray initialized",
            "正在显示悬浮窗口…": "Showing floating windows…",
            "启动完成": "Startup complete",
            "置顶": "Pin to Top",
            "隐藏": "Hide",
            "显示": "Show",
            "不显示": "Not shown",
            "启动位置:": "Start position:",
            "整体等比缩放:": "UI scale:",
            "模块缩放:": "Module scale:",
            "宽度拉伸:": "Width stretch:",
            "高度拉伸:": "Height stretch:",
            "扫描周期 (ms):": "Scan interval (ms):",
            "── 尖刺(含顶端圆点) ──": "── Spikes (incl. tip bead) ──",
            "── 圆环 ──": "── Ring ──",
            "── 外描边 ──": "── Outline ──",
            "── 布局间距 ──": "── Layout Spacing ──",
            "── 翻滚图标 ──": "── Dodge Icon ──",
            "圆半径:": "Circle radius:",
            "尖刺长度:": "Spike length:",
            "尖刺根部距圆心:": "Spike root distance:",
            "尖刺宽度:": "Spike width:",
            "尖刺腰位置:": "Spike waist position:",
            "尖刺顶端圆点半径:": "Spike tip bead radius:",
            "顶端圆点距圆心:": "Bead distance from center:",
            "整体外描边:": "Outer outline:",
            "启用整体外描边": "Enable outer outline",
            "外描边粗细:": "Outer outline width:",
            "── 倒计时弧线 ──": "── Timer Arc ──",
            "倒计时样式:": "Timer style:",
            "圆环": "Ring",
            "扇形": "Sector",
            "倒计时弧线内缩:": "Timer arc inset:",
            "倒计时圆心Y偏移:": "Timer center Y offset:",
            "层数数字Y偏移:": "Stack number Y offset:",
            "层数数字X偏移:": "Stack number X offset:",
            "── 层数数字(无计时) ──": "── Stack Number (No Timer) ──",
            "── 层数数字(有计时) ──": "── Stack Number (With Timer) ──",
            "── 倒计时布局 ──": "── Timer Layout ──",
            "时间胶囊Y偏移:": "Time capsule Y offset:",
            "时间胶囊宽度:": "Timer capsule width:",
            "── 计时文字 ──": "── Timer Text ──",
            "── 倒计时胶囊 ──": "── Timer Capsule ──",
            "层数数字大小:": "Stack number size:",
            "层数数字大小 — (计时版):": "Stack number size — (Timer):",
            "层数数字勾边粗细:": "Stack outline width:",
            "层数数字勾边粗细 — (计时版):": "Stack outline width — (Timer):",
            "层数数字X偏移:": "Stack number X offset:",
            "层数数字X偏移 — (计时版):": "Stack number X offset — (Timer):",
            "层数数字Y偏移:": "Stack number Y offset:",
            "层数数字Y偏移 — (计时版):": "Stack number Y offset — (Timer):",
            "倒计时字体大小:": "Countdown font size:",
            "倒计时文字色:": "Timer text color:",
            "默认图标:": "Default icon:",
            "使用内置默认图标": "Use embedded default icon",
            "浏览...": "Browse...",
            "翻滚图标绝对路径:": "Dodge icon path:",
            "翻滚图标缩放:": "Dodge icon scale:",
            "标题→圆间距:": "Title to circle gap:",
            "圆→翻滚UI间距:": "Circle to dodge UI gap:",
            "分割线:": "Divider:",
            "显示层数/翻滚分割线": "Show stack/roll divider",
            "分割线不透明度:": "Divider opacity:",
            "── 内存 ──": "── Memory ──",
            "ExStatus偏移:": "ExStatus offset:",
            "── 颜色与不透明度 ──": "── Colors & Opacity ──",
            "标题栏色:": "Title bar color:",
            "背景色:": "Background color:",
            "圆环色(正常):": "Circle color (normal):",
            "圆环色(满层):": "Circle color (full stack):",
            "尖刺色(正常):": "Spike color (normal):",
            "尖刺色(满层):": "Spike color (full stack):",
            "倒计时弧颜色:": "Timer arc color:",
            "层数数字色:": "Stack number color:",
            "层数数字勾边色:": "Stack outline color:",
            "层数数字色 — (计时版):": "Stack number color — (Timer):",
            "层数数字勾边色 — (计时版):": "Stack outline color — (Timer):",
            "外描边色:": "Outline color:",
            "不透明度": "Opacity",
            "标题UI色:": "Title UI color:",
            "Buff名色:": "Buff name color:",
            "翻滚图标不透明度:": "Dodge icon opacity:",
            "外部差异化:": "External diff:",
            "内部差异化:": "Internal diff:",
            "外部差异化颜色（圆环/尖刺/外描边）": "External color diff (ring/spike/outline)",
            "内部差异化颜色（弧线/数字/计时文字）": "Internal color diff (arc/text/timer)",
            "Buff名显示:": "Buff name display:",
            "在画布上显示Buff名称": "Show buff name on canvas",
            "Buff名字体大小:": "Buff name font size:",
            "Buff名位置:": "Buff name position:",
            "Buff名衬色块宽度微调:": "Buff name bg width adjust:",
            "── 能力冷却 ──": "── Ability Cooldown ──",
            "显示能力冷却": "Show Ability Cooldowns",
            "方形大小:": "Square Size:",
            "聚散距离:": "Spread Distance:",
            "扇形颜色:": "Sector Color:",
            "倒计时文字色:": "Timer Text Color:",
            "── 冷却完成动画 ──": "── Cooldown Complete Animation ──",
            "完成色:": "Ready Color:",
            "放大比例%:": "Scale Up %:",
            "动画时长ms:": "Animation Duration ms:",
            "── 能力名称 ──": "── Ability Name ──",
            "显示能力名称": "Show Ability Name",
            "字号:": "Font Size:",
            "倒计时X偏移:": "Timer X Offset:",
            "倒计时Y偏移:": "Timer Y Offset:",
            "能力名X偏移:": "Ability Name X Offset:",
            "能力名Y偏移:": "Ability Name Y Offset:",
            "衬色块宽微调:": "BG Width Adjust:",
            "能力名色:": "Ability Name Color:",
            "恢复默认": "Reset",
            "确定": "OK",
            "取消": "Cancel",
            # ── V203: 4 一级标签 / 二级子页 / 闪光全局化 / 翻滚朝向 ──
            "全局": "Global",
            "核心检测模块": "Core Detection",
            "多buff布局": "Multi-buff Layout",
            "翻滚模块": "Dodge Module",
            "能力模块": "Skill Module",
            "常规": "General",
            "背景": "Background",
            "闪光": "Flash",
            "标题栏": "Title Bar",
            "尖刺与圆环": "Spikes & Ring",
            "倒计时": "Timer",
            "层数数字": "Stack Number",
            "多buff差异化": "Multi-buff",
            "Buff名字": "Buff Name",
            "隐藏与位置": "Hide & Position",
            "Buff启用/禁用": "Buff Enable/Disable",
            "翻滚图标": "Dodge Icon",
            "能力冷却": "Ability Cooldown",
            "能力名称": "Ability Name",
            "── 扫描 / 缩放 / 内存 ──": "── Scan / Scale / Memory ──",
            "── 闪光 ──": "── Flash ──",
            "── 闪光应用模块 ──": "── Flash Apply To ──",
            "── 隐藏 ──": "── Hide ──",
            "── 模块位置 ──": "── Module Position ──",
            "核心模块": "Core",
            "位置与缩放": "Position & Scale",
            "── 核心模块位置与缩放 ──": "── Core Position & Scale ──",
            "── 翻滚模块位置与缩放 ──": "── Dodge Position & Scale ──",
            "── 翻滚警告牌（第6/7次）──": "── Dodge Warning (6th/7th) ──",
            "── 能力模块位置与缩放 ──": "── Skill Position & Scale ──",
            "── 单层buff倒计时胶囊 ──": "── Single-layer Buff Timer Capsule ──",
            "闪光颜色:": "Flash color:",
            "背景不透明度:": "Skill BG opacity:",
            "扇形不透明度:": "Sector opacity:",
            "边框不透明度:": "Border opacity:",
            "胶囊不透明度:": "Capsule opacity:",
            "翻滚朝向:": "Dodge orientation:",
            "图标大小:": "Icon size:",
            "外边粗细:": "Border thickness:",
            "外部边色:": "Border color:",
            "内部填充色:": "Fill color:",
            "勾边粗细:": "Outline width:",
            "勾边辉光:": "Outline glow:",
            "翻滚闪光·白色实心勾边": "Dodge flash·white solid outline",
            "尖刺闪光（核心检测模块）": "Spike flash (core)",
            "能力冷却完成闪光": "Skill ready flash",
            "翻滚图标闪光": "Dodge icon flash",
            "翻滚图标闪光：勾边发光": "Dodge icon flash: outline glow",
            "圆环": "Ring",
            "扇形": "Sector",
            "横放": "Horizontal",
            "竖放": "Vertical",
            "关于/更新": "About / Update",
            "关于": "About",
            "当前版本：": "Current version:",
            "状态：": "Status:",
            "检查更新": "Check for Updates",
            "前往下载": "Go to Download",
            "跳过此版本": "Skip this version",
            "自动检查更新": "Auto check for updates",
            "启动时显示读条窗口": "Show splash on startup",
            "更新地址：": "Update URL:",
            "更新日志：": "Changelog:",
            "检查失败：": "Check failed: ",
            "未配置更新地址": "Update URL not configured",
            "连接超时，请检查网络或开启梯子后重试": "Connection timed out. Check network or enable VPN",
            "更新服务器连接被拒绝，请检查网络或开启梯子": "Update server refused. Check network or enable VPN",
            "网络连接异常，请检查网络或 DNS": "Network error. Check network or DNS",
            "更新检查失败: ": "Update check failed: ",
            "发现新版本": "New version available",
            "已是最新": "Up to date",
        }
        zh_to_tw = {
            "Overlay 设置": "Overlay 設定",
            "── 常规 ──": "── 常規 ──",
            "语言 / Language:": "語言 / Language:",
            "随游戏前后台:": "隨遊戲前後台:",
            "游戏在前台时显示，切到后台时自动最小化": "遊戲在前台時顯示，切到後台時自動最小化",
            "随分辨率放大:": "隨解析度放大:",
            "按当前屏幕宽度自动放大": "按當前螢幕寬度自動放大",
            "尖刺圆隐藏:": "尖刺圓隱藏:",
            "无buff时隐藏尖刺圆模块（翻滚/技能UI不受影响）": "無buff時隱藏尖刺圓模組（翻滾/技能UI不受影響）",
            "隐藏时透明度:": "隱藏時透明度:",
            "倒计时字号:": "倒數字號:",
            "时间胶囊宽度:": "時間膠囊寬度:",
            "胶囊宽度微调(Δ):": "膠囊寬度微調(Δ):",
            "尖刺UI不透明度:": "尖刺UI不透明度:",
            "翻滚UI不透明度:": "翻滾UI不透明度:",
            "技能CD不透明度:": "技能CD不透明度:",
            "标题栏状态文字:": "標題列狀態文字:",
            "在标题栏显示角色名和buff状态文字": "在標題列顯示角色名和buff狀態文字",
            "标题栏不透明度:": "標題列不透明度:",
            "背景画布不透明度:": "背景畫布不透明度:",
            "── 透明度 ──": "── 透明度 ──",
            "── 背景 ──": "── 背景 ──",
            "── 标题栏 ──": "── 標題列 ──",
            "多buff偏移量:": "多buff偏移量:",
            "多buff缩放:": "多buff縮放:",
            "多buff夹角:": "多buff夾角:",
            "Buff 启用/禁用:": "Buff 啟用/禁用:",
            "全选": "全選",
            "全不选": "全不選",
            "全显示": "全顯示",
            "全不显示": "全不顯示",
            "生效区（拖动排序）": "生效區（拖動排序）",
            "隐藏区": "隱藏區",
            "左栏=显示，右栏=隐藏；拖到另一侧切换（不可跨角色）": "左欄=顯示，右欄=隱藏；拖到另一側切換（不可跨角色）",
            "（单层buff）": "（單層buff）",
            "启用就绪呼吸光": "啟用就緒呼吸光",
            "导出角色内存(找偏移用)": "匯出角色記憶體(找偏移用)",
            "关闭后双击 exe 不再弹出启动读条，直接进入主界面": "關閉後雙擊 exe 不再彈出啟動讀條，直接進入主介面",
            "把当前角色 actor 内存按 u32 导出到桌面 actor_dump.txt，用于定位 class/异能 等裸值偏移": "把當前角色 actor 記憶體按 u32 匯出到桌面 actor_dump.txt，用於定位 class/異能 等裸值偏移",
            "未进入战斗时隐藏整个UI（尖刺圆/翻滚/技能UI 全部）": "未進入戰鬥時隱藏整個UI（尖刺圓/翻滾/技能UI 全部）",
            "检查中…": "檢查中…",
            "已跳过 v": "已跳過 v",
            "启动中…": "啟動中…",
            "准备": "準備",
            "完成": "完成",
            "正在加载设置…": "正在載入設定…",
            "已加载角色数据库": "已載入角色資料庫",
            "正在计算界面布局…": "正在計算介面佈局…",
            "正在加载图标资源…": "正在載入圖示資源…",
            "已创建悬浮窗口": "已建立懸浮視窗",
            "已初始化系统托盘": "已初始化系統托盤",
            "正在显示悬浮窗口…": "正在顯示懸浮視窗…",
            "启动完成": "啟動完成",
            "置顶": "置頂",
            "隐藏": "隱藏",
            "显示": "顯示",
            "不显示": "不顯示",
            "启动位置:": "啟動位置:",
            "整体等比缩放:": "整體等比縮放:",
            "模块缩放:": "模組縮放:",
            "宽度拉伸:": "寬度拉伸:",
            "高度拉伸:": "高度拉伸:",
            "扫描周期 (ms):": "掃描週期 (ms):",
            "── 尖刺(含顶端圆点) ──": "── 尖刺(含頂端圓點) ──",
            "── 圆环 ──": "── 圓環 ──",
            "── 外描边 ──": "── 外描邊 ──",
            "── 布局间距 ──": "── 佈局間距 ──",
            "── 翻滚图标 ──": "── 翻滾圖標 ──",
            "圆半径:": "圓半徑:",
            "尖刺长度:": "尖刺長度:",
            "尖刺根部距圆心:": "尖刺根部距圓心:",
            "尖刺宽度:": "尖刺寬度:",
            "尖刺腰位置:": "尖刺腰位置:",
            "尖刺顶端圆点半径:": "尖刺頂端圓點半徑:",
            "顶端圆点距圆心:": "頂端圓點距圓心:",
            "整体外描边:": "整體外描邊:",
            "启用整体外描边": "啟用整體外描邊",
            "外描边粗细:": "外描邊粗細:",
            "── 倒计时弧线 ──": "── 倒計時弧線 ──",
            "倒计时样式:": "倒計時樣式:",
            "圆环": "圓環",
            "扇形": "扇形",
            "倒计时弧线内缩:": "倒計時弧線內縮:",
            "倒计时圆心Y偏移:": "倒計時圓心Y偏移:",
            "层数数字Y偏移:": "層數數字Y偏移:",
            "层数数字X偏移:": "層數數字X偏移:",
            "── 层数数字(无计时) ──": "── 層數數字(無計時) ──",
            "── 层数数字(有计时) ──": "── 層數數字(有計時) ──",
            "── 倒计时布局 ──": "── 倒計時佈局 ──",
            "时间胶囊Y偏移:": "時間膠囊Y偏移:",
            "时间胶囊宽度:": "時間膠囊寬度:",
            "── 计时文字 ──": "── 計時文字 ──",
            "── 倒计时胶囊 ──": "── 倒計時膠囊 ──",
            "层数数字大小:": "層數數字大小:",
            "层数数字大小 — (计时版):": "層數數字大小 — (計時版):",
            "层数数字勾边粗细:": "層數數字勾邊粗細:",
            "层数数字勾边粗细 — (计时版):": "層數數字勾邊粗細 — (計時版):",
            "层数数字X偏移 — (计时版):": "層數數字X偏移 — (計時版):",
            "层数数字Y偏移 — (计时版):": "層數數字Y偏移 — (計時版):",
            "倒计时字体大小:": "倒計時字體大小:",
            "倒计时文字色:": "倒計時文字色:",
            "默认图标:": "預設圖標:",
            "使用内置默认图标": "使用內建預設圖標",
            "浏览...": "瀏覽...",
            "翻滚图标绝对路径:": "翻滾圖標絕對路徑:",
            "翻滚图标缩放:": "翻滾圖標縮放:",
            "标题→圆间距:": "標題→圓間距:",
            "圆→翻滚UI间距:": "圓→翻滾UI間距:",
            "分割线:": "分割線:",
            "显示层数/翻滚分割线": "顯示層數/翻滾分割線",
            "分割线不透明度:": "分割線不透明度:",
            "── 内存 ──": "── 記憶體 ──",
            "ExStatus偏移:": "ExStatus偏移:",
            "── 颜色与不透明度 ──": "── 顏色與不透明度 ──",
            "标题栏色:": "標題列色:",
            "背景色:": "背景色:",
            "圆环色(正常):": "圓環色(正常):",
            "圆环色(满层):": "圓環色(滿層):",
            "尖刺色(正常):": "尖刺色(正常):",
            "尖刺色(满层):": "尖刺色(滿層):",
            "倒计时弧颜色:": "倒計時弧顏色:",
            "层数数字色:": "層數數字色:",
            "层数数字勾边色:": "層數數字勾邊色:",
            "层数数字色 — (计时版):": "層數數字色 — (計時版):",
            "层数数字勾边色 — (计时版):": "層數數字勾邊色 — (計時版):",
            "外描边色:": "外描邊色:",
            "不透明度": "不透明度",
            "标题UI色:": "標題UI色:",
            "Buff名色:": "Buff名色:",
            "翻滚图标不透明度:": "翻滾圖標不透明度:",
            "外部差异化:": "外部差異化:",
            "内部差异化:": "內部差異化:",
            "外部差异化颜色（圆环/尖刺/外描边）": "外部差異化顏色（圓環/尖刺/外描邊）",
            "内部差异化颜色（弧线/数字/计时文字）": "內部差異化顏色（弧線/數字/計時文字）",
            "Buff名显示:": "Buff名顯示:",
            "在画布上显示Buff名称": "在畫布上顯示Buff名稱",
            "Buff名字体大小:": "Buff名字體大小:",
            "Buff名位置:": "Buff名位置:",
            "Buff名衬色块宽度微调:": "Buff名襯色塊寬度微調:",
            "── 能力冷却 ──": "── 能力冷卻 ──",
            "显示能力冷却": "顯示能力冷卻",
            "方形大小:": "方形大小:",
            "聚散距离:": "聚散距離:",
            "扇形颜色:": "扇形顏色:",
            "倒计时文字色:": "倒計時文字色:",
            "── 冷却完成动画 ──": "── 冷卻完成動畫 ──",
            "完成色:": "完成色:",
            "放大比例%:": "放大比例%:",
            "动画时长ms:": "動畫時長ms:",
            "── 能力名称 ──": "── 能力名稱 ──",
            "显示能力名称": "顯示能力名稱",
            "字号:": "字號:",
            "倒计时X偏移:": "倒數X偏移:",
            "倒计时Y偏移:": "倒數Y偏移:",
            "能力名X偏移:": "能力名X偏移:",
            "能力名Y偏移:": "能力名Y偏移:",
            "衬色块宽微调:": "襯色塊寬微調:",
            "能力名色:": "能力名色:",
            "恢复默认": "恢復預設",
            "确定": "確定",
            "取消": "取消",
            # ── V203: 4 一级标签 / 二级子页 / 闪光全局化 / 翻滚朝向 ──
            "全局": "全域",
            "核心检测模块": "核心檢測模組",
            "多buff布局": "多buff佈局",
            "翻滚模块": "翻滾模組",
            "能力模块": "能力模組",
            "常规": "常規",
            "背景": "背景",
            "闪光": "閃光",
            "标题栏": "標題列",
            "尖刺与圆环": "尖刺與圓環",
            "倒计时": "倒計時",
            "层数数字": "層數數字",
            "多buff差异化": "多buff差異化",
            "Buff名字": "Buff名字",
            "隐藏与位置": "隱藏與位置",
            "Buff启用/禁用": "Buff啟用/禁用",
            "翻滚图标": "翻滾圖標",
            "能力冷却": "能力冷卻",
            "能力名称": "能力名稱",
            "── 扫描 / 缩放 / 内存 ──": "── 掃描 / 縮放 / 記憶體 ──",
            "── 闪光 ──": "── 閃光 ──",
            "── 闪光应用模块 ──": "── 閃光應用模組 ──",
            "── 隐藏 ──": "── 隱藏 ──",
            "── 模块位置 ──": "── 模組位置 ──",
            "核心模块": "核心模組",
            "位置与缩放": "位置與縮放",
            "── 核心模块位置与缩放 ──": "── 核心模組位置與縮放 ──",
            "── 翻滚模块位置与缩放 ──": "── 翻滾模組位置與縮放 ──",
            "── 翻滚警告牌（第6/7次）──": "── 翻滾警告牌（第6/7次）──",
            "── 能力模块位置与缩放 ──": "── 能力模組位置與縮放 ──",
            "── 单层buff倒计时胶囊 ──": "── 單層buff倒數膠囊 ──",
            "闪光颜色:": "閃光顏色:",
            "背景不透明度:": "背景不透明度:",
            "扇形不透明度:": "扇形不透明度:",
            "边框不透明度:": "邊框不透明度:",
            "胶囊不透明度:": "膠囊不透明度:",
            "翻滚朝向:": "翻滾朝向:",
            "图标大小:": "圖標大小:",
            "外边粗细:": "外邊粗細:",
            "外部边色:": "外部邊色:",
            "内部填充色:": "內部填充色:",
            "勾边粗细:": "勾邊粗細:",
            "勾边辉光:": "勾邊輝光:",
            "翻滚闪光·白色实心勾边": "翻滾閃光·白色實心勾邊",
            "尖刺闪光（核心检测模块）": "尖刺閃光（核心檢測模組）",
            "能力冷却完成闪光": "能力冷卻完成閃光",
            "翻滚图标闪光": "翻滾圖標閃光",
            "翻滚图标闪光：勾边发光": "翻滾圖標閃光：勾邊發光",
            "圆环": "圓環",
            "扇形": "扇形",
            "横放": "橫放",
            "竖放": "豎放",
            "关于/更新": "關於/更新",
            "关于": "關於",
            "当前版本：": "目前版本：",
            "状态：": "狀態：",
            "检查更新": "檢查更新",
            "前往下载": "前往下載",
            "跳过此版本": "跳過此版本",
            "自动检查更新": "自動檢查更新",
            "启动时显示读条窗口": "啟動時顯示讀條視窗",
            "更新地址：": "更新地址：",
            "更新日志：": "更新日誌：",
            "检查失败：": "檢查失敗：",
            "未配置更新地址": "未設定更新位址",
            "连接超时，请检查网络或开启梯子后重试": "連線逾時，請檢查網路或開啟梯子後重試",
            "更新服务器连接被拒绝，请检查网络或开启梯子": "更新伺服器連線被拒，請檢查網路或開啟梯子",
            "网络连接异常，请检查网络或 DNS": "網路連線異常，請檢查網路或 DNS",
            "更新检查失败: ": "更新檢查失敗: ",
            "发现新版本": "發現新版本",
            "已是最新": "已是最新",
        }
        en_to_zh = {v: k for k, v in zh_to_en.items()}
        tw_to_zh = {v: k for k, v in zh_to_tw.items()}
        if lang == "en":
            target_map = zh_to_en
        elif lang == "zh_tw":
            target_map = zh_to_tw
        else:
            target_map = {}

        def _translate_text(text):
            """先归一化到简中，再翻译到目标语言。"""
            if text in en_to_zh:
                text = en_to_zh[text]
            elif text in tw_to_zh:
                text = tw_to_zh[text]
            return target_map.get(text, text)

        self.setWindowTitle(_translate_text("Overlay 设置"))
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
        for widget in self.findChildren(QWidget):
            tip = widget.toolTip()
            if tip:
                translated = _translate_text(tip)
                if translated != tip:
                    widget.setToolTip(translated)

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

        # 翻译角色分组框标题（含编号）
        if hasattr(self, "buff_order_groups"):
            for pl_id, group in self.buff_order_groups.items():
                group.refresh_title(lang)
        # 让动态刷新也能使用同一翻译函数
        self._translate_text = _translate_text

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
            op_label = QLabel("不透明度")
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
        """「全显示」= 每组所有 buff 设为默认顺位；「全不显示」= 全部隐藏。"""
        for group in getattr(self, "buff_order_groups", {}).values():
            if show:
                group.show_all()
            else:
                group.hide_all()
        self._emit_changed()

    def _connect_live_signals(self):
        widgets = [
            self.lang, self.auto_focus_minimize, self.resolution_auto_scale, self.spike_hide_chk, self.spike_hidden_op_spn, self.show_titlebar_status, self.icon_use_default,
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
            self.skill_cd_show_chk, self.skill_cd_size_spn, self.skill_cd_spread_spn,
            self.skill_cd_font_size_spn, self.skill_cd_capsule_w_spn,
            self.skill_cd_timer_offx_spn, self.skill_cd_timer_offy_spn,
            self.skill_cd_bg_opacity_sl, self.skill_cd_sector_opacity_sl,
            self.skill_cd_border_opacity_sl, self.skill_cd_capsule_opacity_sl,
            self.skill_cd_name_chk, self.skill_cd_name_font_spn,
            self.skill_cd_name_offx_spn, self.skill_cd_name_offy_spn,
            self.skill_cd_name_bgw_spn,
            self.skill_cd_border_scale_dspn, self.skill_cd_breath_chk,
            self.skill_cd_breath_freq_dspn, self.skill_cd_breath_soft_dspn,
            self.skill_cd_breath_size_dspn,
            # ── V203: 闪光全局化 / 模块位置 / 翻滚朝向 ──
            self.flash_scale_spn, self.flash_dur_spn,
            self.flash_apply_spikes_chk, self.flash_apply_skill_ready_chk,
            self.dodge_outline_enabled_chk,
            self.dodge_outline_width_dspn, self.dodge_outline_glow_dspn,
            self.warning_size_dspn, self.warning_outline_w_dspn,
            self.roll_orientation_combo,
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
        self.show_buff_name_cb.stateChanged.connect(self._emit_changed)
        self.buff_name_font_size.valueChanged.connect(self._emit_changed)
        self.buff_name_offset_x.valueChanged.connect(self._emit_changed)
        self.buff_name_offset_y.valueChanged.connect(self._emit_changed)
        self.buff_name_bg_width.valueChanged.connect(self._emit_changed)

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
        self.ooc_hide_chk.setChecked(DEFAULT_SETTINGS["out_of_combat_hide"])
        self.ooc_op_spn.setValue(DEFAULT_SETTINGS["out_of_combat_opacity"])
        self.show_titlebar_status.setChecked(DEFAULT_SETTINGS["show_titlebar_status"])
        # buff 顺位重置为默认（按 profile 顺序，全部显示）
        for group in getattr(self, "buff_order_groups", {}).values():
            group.show_all()
        self.auto_check_cb.setChecked(DEFAULT_SETTINGS["auto_check_update"])
        self.splash_cb.setChecked(DEFAULT_SETTINGS["splash_enabled"])
        self.update_url_le.setText(DEFAULT_SETTINGS["update_check_url"])
        self.skip_version = DEFAULT_SETTINGS.get("skip_version", "")
        # 多buff差异化：按 buff 个数 2/3/4/5 恢复 20 个参数
        for cnt in (2, 3, 4, 5):
            c = self.multi_buff_ctrls.get(cnt, {})
            sv = DEFAULT_SETTINGS[f"multi_buff_scale_{cnt}"]; c.get("scale_sl", QSlider()).setValue(sv); c.get("scale_sp", QSpinBox()).setValue(sv)
            hv = DEFAULT_SETTINGS[f"multi_buff_hgap_{cnt}"]; c.get("hgap_sl", QSlider()).setValue(hv); c.get("hgap_sp", QSpinBox()).setValue(hv)
            dv = DEFAULT_SETTINGS[f"multi_buff_dy_{cnt}"]; c.get("dy_sl", QSlider()).setValue(dv); c.get("dy_sp", QSpinBox()).setValue(dv)
            c.get("ext_cb", QCheckBox()).setChecked(DEFAULT_SETTINGS[f"multi_buff_ext_color_{cnt}"])
            c.get("int_cb", QCheckBox()).setChecked(DEFAULT_SETTINGS[f"multi_buff_int_color_{cnt}"])
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
        self.dodge_outline_enabled_chk.setChecked(DEFAULT_SETTINGS["dodge_outline_enabled"])
        self.warning_size_dspn.setValue(DEFAULT_SETTINGS["warning_size_scale"])
        self.warning_outline_w_dspn.setValue(DEFAULT_SETTINGS["warning_outline_width"])
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
        self.skill_cd_show_chk.setChecked(DEFAULT_SETTINGS["show_skill_cd"])
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
        self.skill_cd_breath_freq_dspn.setValue(DEFAULT_SETTINGS["skill_cd_breath_freq"])
        self.skill_cd_breath_soft_dspn.setValue(DEFAULT_SETTINGS["skill_cd_breath_soft"])
        self.skill_cd_breath_size_dspn.setValue(DEFAULT_SETTINGS["skill_cd_breath_size"])
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
        self.settings["out_of_combat_hide"] = self.ooc_hide_chk.isChecked()
        self.settings["out_of_combat_opacity"] = self.ooc_op_spn.value()
        self.settings["show_titlebar_status"] = self.show_titlebar_status.isChecked()
        # Buff 顺位：从各组拖拽列表读取；rank>=1 为显示（顺序=从左到右），0=隐藏
        order = {}
        for group in getattr(self, "buff_order_groups", {}).values():
            order.update(group.get_order())
        self.settings["buff_order"] = order
        # 兼容性派生：rank>0 视为启用（供旧逻辑/外部引用）
        self.settings["buff_enabled"] = {k: v > 0 for k, v in order.items()}
        # 多buff差异化：按 buff 个数 2/3/4/5 写入 20 个参数
        for cnt in (2, 3, 4, 5):
            c = self.multi_buff_ctrls.get(cnt, {})
            self.settings[f"multi_buff_scale_{cnt}"] = c.get("scale_sp", QSpinBox()).value()
            self.settings[f"multi_buff_hgap_{cnt}"] = c.get("hgap_sp", QSpinBox()).value()
            self.settings[f"multi_buff_dy_{cnt}"] = c.get("dy_sp", QSpinBox()).value()
            self.settings[f"multi_buff_ext_color_{cnt}"] = c.get("ext_cb", QCheckBox()).isChecked()
            self.settings[f"multi_buff_int_color_{cnt}"] = c.get("int_cb", QCheckBox()).isChecked()
        self.settings["show_buff_name"] = self.show_buff_name_cb.isChecked()
        self.settings["buff_name_font_size"] = self.buff_name_font_size.value()
        self.settings["buff_name_offset_x"] = self.buff_name_offset_x.value()
        self.settings["buff_name_offset_y"] = self.buff_name_offset_y.value()
        self.settings["buff_name_bg_width"] = self.buff_name_bg_width.value()
        # 技能冷却
        self.settings["show_skill_cd"] = self.skill_cd_show_chk.isChecked()
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
        self.settings["skill_cd_breath_size"] = self.skill_cd_breath_size_dspn.value()
        self.settings["flash_scale"] = self.flash_scale_spn.value()
        self.settings["flash_duration_ms"] = self.flash_dur_spn.value()
        self.settings["flash_apply_spikes"] = self.flash_apply_spikes_chk.isChecked()
        self.settings["flash_apply_skill_ready"] = self.flash_apply_skill_ready_chk.isChecked()
        self.settings["dodge_outline_enabled"] = self.dodge_outline_enabled_chk.isChecked()
        self.settings["dodge_outline_width"] = self.dodge_outline_width_dspn.value()
        self.settings["dodge_outline_glow"] = self.dodge_outline_glow_dspn.value()
        self.settings["warning_size_scale"] = self.warning_size_dspn.value()
        self.settings["warning_outline_width"] = self.warning_outline_w_dspn.value()
        self.settings["skill_cd_show_name"] = self.skill_cd_name_chk.isChecked()
        self.settings["skill_cd_name_font_size"] = self.skill_cd_name_font_spn.value()
        self.settings["skill_cd_name_offset_x"] = self.skill_cd_name_offx_spn.value()
        self.settings["skill_cd_name_offset_y"] = self.skill_cd_name_offy_spn.value()
        self.settings["skill_cd_name_bg_width"] = self.skill_cd_name_bgw_spn.value()
        self.settings["use_default_dodge_icon"] = self.icon_use_default.isChecked()
        self.settings["roll_orientation"] = self.roll_orientation_combo.currentData()
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
        self.settings["splash_enabled"] = self.splash_cb.isChecked()
        self.settings["skip_version"] = self.skip_version or ""
        self.settings["update_check_url"] = self.update_url_le.text().strip()
        return self.settings

    # ---------------- 在线更新 ----------------
    def refresh_update_ui(self, info=None):
        def _t(text):
            fn = getattr(self, "_translate_text", None)
            return fn(text) if fn else text
        if info is None:
            info = getattr(self.ctrl, "update_info", None)
        if info is None:
            self.update_status_label.setText("—")
            self.download_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.changelog_edit.setPlainText("")
            return
        if info.get("error") == "no_url":
            self.update_status_label.setText(_t("未配置更新地址"))
            self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
            self.changelog_edit.setPlainText("")
            return
        if info.get("error"):
            self.update_status_label.setText(_t("检查失败：") + str(info.get("error")))
            self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
            return
        latest = info.get("latest_version", "")
        self.changelog_edit.setPlainText(info.get("changelog", "") or "")
        if info.get("has_update"):
            self.update_status_label.setText(_t("发现新版本") + " v" + str(latest) + "！")
            self.download_btn.setEnabled(bool(info.get("download_url")))
            self.skip_btn.setEnabled(True)
            self.skip_btn.setText(_t("跳过此版本") + " v" + str(latest))
        else:
            self.update_status_label.setText(_t("已是最新") + " (v" + str(latest) + ")")
            self.download_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)

    def _on_check_update_clicked(self):
        _tr = getattr(self, "_translate_text", None)
        self.update_status_label.setText(_tr("检查中…") if _tr else "检查中…")
        self.download_btn.setEnabled(False); self.skip_btn.setEnabled(False)
        if self.ctrl is not None:
            self.ctrl.check_update(manual=True)

    def _on_download_clicked(self):
        info = getattr(self.ctrl, "update_info", None)
        url = (info.get("download_url") if info else None) or self.update_url_le.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _on_skip_clicked(self):
        info = getattr(self.ctrl, "update_info", None)
        if info and info.get("latest_version"):
            self.skip_version = str(info["latest_version"])
            _tr = getattr(self, "_translate_text", None)
            self.update_status_label.setText((_tr("已跳过 v") if _tr else "已跳过 v") + self.skip_version)
            self.skip_btn.setEnabled(False)
            self.download_btn.setEnabled(False)

    def _on_dump_memory_clicked(self):
        if self.ctrl is not None:
            self.ctrl.dump_actor_memory()


# ============================ Overlay Widget ============================
class GBFROverlayQt(QObject):
    update_checked = Signal(object)
    update_downloaded = Signal(str)   # 新版 exe 已下载到本地路径
    update_download_failed = Signal(str)  # 下载失败原因
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
        self._pressed_core_btn = None  # 标题栏图标按下反馈态：None/"update"/"minimize"/"settings"/"lock"/"exit"
        self._pressed_visual = False   # 指针是否仍在被按下的按钮内（仅影响凹陷视觉，不清除锁定）
        # 窗口局部像素版命中矩形（与绘制缩放一致，避免画布<->窗口坐标换算误差）
        self._btn_update_rect_win = QRect()
        self._btn_minimize_rect_win = QRect()
        self._btn_settings_rect_win = QRect()
        self._btn_lock_rect_win = QRect()
        self._btn_exit_rect_win = QRect()
        # 标题栏更新按钮状态
        self._update_has_update = False
        self._update_downloading = False
        self._update_progress_pct = 0
        # 翻滚勾边轮廓缓存（按 PNG 图案外边缘）
        self._dodge_outline_img = None
        self._dodge_outline_key = None

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
        self._spike_group_flash = None  # 尖刺圆整体模块级闪光：{"start": ms}
        self._prev_buff_stacks = {}   # 每层buff上一帧层数：{bkey: stacks}
        self.spike_hidden = False
        # 裸值资源槽地址锁定（伊德四槽等）：{profile_buff_index: addr}
        self._raw_locked_addrs = {}
        self._prev_actor = 0
        _step(22, "已加载角色数据库")
        load_char_db()

        # 计算「核心检测模块」画布布局（尖刺圆 + 标题栏）
        _step(38, "正在计算界面布局…")
        self.recalc_layout()
        _step(52, "正在加载图标资源…")
        self.load_dodge_icon()
        # 翻滚模块级闪光状态：{"start": ms}；dodge_count 增加时触发
        self._roll_group_flash = None
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
        self.update_downloaded.connect(self._on_update_downloaded)
        self.update_download_failed.connect(self._on_update_download_failed)
        # 标题栏更新按钮呼吸光动画（仅在有新版本时真正触发重绘）
        self._update_glow_timer = QTimer(self)
        self._update_glow_timer.timeout.connect(lambda: self.core_win.update() if getattr(self, "_update_has_update", False) else None)
        self._update_glow_timer.start(100)
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

        # 常驻高频动画重绘：驱动呼吸光/闪光放大等基于时间的动画。
        # 即使设置面板以 modal 打开也能持续重绘（repaint 同步执行，不受 modal 事件循环合并影响），
        # 解决「拖动呼吸光/闪光参数时悬浮窗不实时反馈、只有颜色能立即变」的问题。
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._anim_repaint_all)
        self._anim_timer.start(40)
        # 首次扫描延后到事件循环启动后执行，避免阻塞构造。
        QTimer.singleShot(0, self.tick)

        # 显示模块窗口
        _step(95, "正在显示悬浮窗口…")
        for w in (self.core_win, self.roll_win, self.skill_win):
            w.show()
        _step(100, "启动完成")

    # ----------------------------------------------------------------
    #  窗口集合辅助
    # ----------------------------------------------------------------
    def _all_windows(self):
        return [self.core_win, self.roll_win, self.skill_win]

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
        """单个 buff 是否进入满层状态。浮点槽按 gauge_value 判定。"""
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
        spike_outer_extent = max(0, int((1.0 + self.spike_axis_pos) * self.spike_len))
        bead_outer_extent = self.spike_bead_radius + max(0, int(abs(self.spike_bead_pos) * self.spike_len))
        outline_pad = max(0, self.indicator_outline_width + 2)
        spike_side_extent = spike_outer_extent + max(self.spike_w // 2, self.spike_bead_radius) + outline_pad
        core_required_w = (self.circle_r + max(spike_side_extent, bead_outer_extent) + outline_pad + 10) * 2
        # 标题栏诊断文字完整显示，整体宽度给足
        self.core_canvas_w = max(self.CANVAS_W, int(core_required_w))
        spike_top_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent) + outline_pad
        spike_bottom_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent) + outline_pad
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
        self.dragon_bottom_y = self.circle_cy + self.circle_r + self.spike_len

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
        # 用户自定义路径失效时回退到默认图标，避免勾边/图标本体全空
        if self.shrimp.isNull() and os.path.isfile(DEFAULT_SHRIMP_IMG_PATH):
            self.shrimp = QPixmap(DEFAULT_SHRIMP_IMG_PATH)
        if not self.shrimp.isNull():
            self.shrimp = self.shrimp.scaled(
                self.dodge_icon_size,
                self.dodge_icon_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        # 图标变更 → 轮廓缓存失效（下次绘制按新图标重建）
        self._dodge_outline_img = None
        self._dodge_outline_key = None

    def _calc_icon_btn_rects(self):
        """计算标题栏图标按钮区域（含更新按钮）。

        顺序从左到右：更新(update)、最小化、设置、锁定、退出。
        未锁定时 5 个图标整体水平居中；锁定后仅显示锁定图标，
        若有新版本则额外显示更新按钮（更新按钮在最左）。
        """
        th = self.TITLE_BAR_H
        s = self.ICON_BTN_SIZE
        gap = self.ICON_BTN_GAP
        icon_row_h = self.ICON_BTN_SIZE + 10
        has_update = getattr(self, "_update_has_update", False)
        off = -9999
        if not self.locked:
            n = 5
            total_w = n * s + (n - 1) * gap
            start_x = (self.core_canvas_w - total_w) / 2.0
            y = (icon_row_h - s) // 2
            update_x = start_x
            minimize_x = start_x + (s + gap)
            settings_x = start_x + 2 * (s + gap)
            lock_x = start_x + 3 * (s + gap)
            exit_x = start_x + 4 * (s + gap)
        else:
            y = (icon_row_h - s) // 2
            if has_update:
                n = 2
                total_w = n * s + (n - 1) * gap
                start_x = (self.core_canvas_w - total_w) / 2.0
                update_x = start_x
                lock_x = start_x + (s + gap)
                minimize_x = settings_x = exit_x = off
            else:
                lock_x = (self.core_canvas_w - s) / 2.0
                update_x = minimize_x = settings_x = exit_x = off
        return (
            QRect(int(update_x), int(y), s, s),
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

        self._draw_backdrop(painter)
        self._draw_title_bar(painter)

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
                m = len(shown)
                for i, buff in enumerate(shown):
                    ix = cx + (i - (m - 1) / 2.0) * hgap
                    iy = cy + (dy if (i % 2 == 0) else -dy)
                    is_lv7 = self._is_buff_full_stack(buff)
                    override = self._make_index_color_override(i, cfg)
                    self._render_buff_ui(painter, buff, ix, iy, r, is_lv7, scale=scale, color_override=override)
                    self._draw_buff_name(painter, buff, ix, iy, r, scale, color_override=override)
        else:
            # 无任何可显示buff：绘制空的尖刺圆模块（受 spike_hidden 控制，可隐藏/变暗）
            self._draw_indicator_outer_outline(painter, cx, cy, r, False, include_spikes=True)
            self._draw_circle(painter, cx, cy, r, False)

    def _buff_key(self, buff):
        """与内存更新循环一致的 buff 键：PLxxxx_idx 或 char_type_idx。"""
        pl = self.pl_id
        if not pl and self.char_type in CHAR_TYPE_TO_PL:
            pl = CHAR_TYPE_TO_PL[self.char_type]
        return f"{pl}_{buff['index']}" if pl else f"{self.char_type:#04x}_{buff['index']}"

    def _render_buff_ui(self, painter, buff, cx, cy, r, is_lv7, scale=1.0, color_override=None):
        """渲染一个完整的 buff UI 元素（圆环+尖刺+倒计时+中心文字）。

        闪光规则（V271）：层数增加时【仅尖刺 + 装饰小球】放大并白色闪光；
        中间圆环、计时器、层数字【不随闪光缩放/变色】，保持不动。
        """
        is_single_layer = self._is_buff_single_layer(buff)
        # V274 尖刺闪光：改为「仅新增尖刺」——按本 buff 的 flash 记录独立判定，
        # 只有 index >= 上一次层数 的尖刺放大白闪；外圈圆环勾边不参与闪光。
        bkey = self._buff_key(buff)
        spike_flash_record = self._spike_flash.get(bkey)
        painter.save()
        # scale 仅用于多buff布局缩放（位置/大小），不是动画闪光，绝不动到中间层
        if scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        # 中间层（始终不动）：外发光 + 圆环外勾边 + 圆环 + 计时器 + 中心文字
        # V274：圆环外勾边固定不随闪光缩放（flash_scale=1.0，需求1）。
        self._draw_glow(painter, cx, cy, r, is_lv7, color_override=color_override)
        include_spikes = not is_single_layer
        self._draw_indicator_outer_outline(painter, cx, cy, r, is_lv7,
                                           include_spikes=False,
                                           buff=buff, color_override=color_override,
                                           flash_scale=1.0)
        if not is_single_layer:
            self._draw_spikes(painter, cx, cy, r, is_lv7, buff=buff,
                              color_override=color_override,
                              flash_record=spike_flash_record)
        self._draw_circle(painter, cx, cy, r, is_lv7, color_override=color_override)
        self._draw_timer_progress(painter, cx, cy, r, is_lv7, buff=buff, color_override=color_override)
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
        bg_rect = QRect(int(center_x - bg_w / 2), int(center_y - bg_h / 2), bg_w, bg_h)
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
        # 先画模块背景：即使 show_skill_cd 关闭或没读到技能，也让窗口可见、可拖动
        self._draw_module_backdrop(painter, self.skill_canvas_w, self.skill_canvas_h, draw_border=True, module_key="skill")

        if not bool(self.settings.get("show_skill_cd", True)):
            self._draw_skill_placeholder(painter, "hidden")
            return
        if self.status != "ok":
            self._draw_skill_placeholder(painter, self.status)
            return
        if not self.skill_cd_data:
            self._draw_skill_placeholder(painter, "no_skill")
            return
        cx, cy = self.skill_cx, self.skill_cy
        spread = int(self.settings.get("skill_cd_spread", 70))
        s = int(self.settings.get("skill_cd_size", 18))
        # 聚散距离直接生效，仅保留极小下限避免菱形覆盖中心
        half_diag = int(s * 1.5)
        spread = max(spread, half_diag + 8)
        group_cx = cx
        group_cy = cy
        # 十字菱形：左1/上2/右3/下4
        positions = [
            (group_cx - spread, group_cy),       # 槽1 左
            (group_cx, group_cy - spread),       # 槽2 上
            (group_cx + spread, group_cy),       # 槽3 右
            (group_cx, group_cy + spread),       # 槽4 下
        ]
        # 第一遍：绘制所有菱形（不含名称），避免相邻菱形互相遮挡名称
        for i, (sx, sy) in enumerate(positions):
            if i < len(self.skill_cd_data):
                try:
                    self._draw_skill_cd_element(painter, self.skill_cd_data[i], sx, sy, draw_name=False)
                except Exception:
                    pass
        # 第二遍：统一把所有技能名称绘制在最顶层（置于顶层）
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

        # 就绪呼吸光：冷却完毕时在菱形底部尖角加一圈柔和呼吸光（位于菱形之后绘制 → 衬在底层）
        if ready and bool(self.settings.get("skill_cd_breath_enabled", True)):
            self._draw_ready_breath(painter, cx, cy, s, base_opacity)

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
            cap_bg.setAlpha(int(self.settings.get("skill_cd_capsule_opacity", 63) * 255 / 100))
            cap_border = qcolor(self.settings.get("skill_cd_capsule_border", base_color_hex))
            cap_border.setAlpha(100)
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
        """就绪呼吸光：以能力菱形为轮廓的柔和径向呼吸光晕（衬在菱形底层，露出一圈光环）。

        仅在能力冷却完毕（ready）时由 _draw_skill_cd_element 调用。
        关键修复：
          1) 发光形状不再是圆形，而是与能力完全同形的「菱形」；
          2) 发光中心与菱形中心重合；
          3) 所有参数（颜色/不透明度/频率/柔和度/光圈大小）在设置面板实时可调，
             并通过 _apply_live_settings 立即反馈到悬浮窗重绘。
        """
        color_hex = self.settings.get("skill_cd_breath_color", "#ffffff")
        col = qcolor(color_hex)
        peak = int(self.settings.get("skill_cd_breath_color_opacity", 65) * 255 / 100)
        freq = float(self.settings.get("skill_cd_breath_freq", 0.5))   # Hz
        soft = max(0.0, min(1.0, float(self.settings.get("skill_cd_breath_soft", 0.5))))
        size_mul = max(0.2, float(self.settings.get("skill_cd_breath_size", 1.9)))
        # 正弦呼吸相位 0..1（freq 越大呼吸越快）
        phase = (math.sin(2.0 * math.pi * freq * time.time()) + 1.0) / 2.0
        alpha = int(peak * (0.3 + 0.7 * phase))   # 在 30%~100% 之间往复呼吸
        if alpha <= 0:
            return
        # 呼吸菱形的几何：与能力菱形同心、同圆角比例，线性尺寸放大 size_mul
        half_b = s * size_mul
        radius_b = max(2, int(half_b / 4))
        R = half_b * math.sqrt(2.0)  # 覆盖菱形角点的径向渐变半径
        # 衰减指数：soft 越大 → p 越小 → 渐变更平缓（更扩散柔和）；soft 越小 → 核心更紧实
        p = 0.5 + (1.0 - soft) * 3.0
        grad = QRadialGradient(cx, cy, R)
        for t in (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0):
            a = int(alpha * max(0.0, (1.0 - t) ** p))
            c = QColor(col); c.setAlpha(a)
            grad.setColorAt(t, c)
        painter.save()
        painter.setOpacity(base_opacity)
        # 把坐标系旋转 45°，使圆角矩形变成菱形；径向渐变中心 (cx,cy) 在旋转下保持不变
        painter.translate(cx, cy)
        painter.rotate(45)
        painter.translate(-cx, -cy)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(cx - half_b, cy - half_b, half_b * 2, half_b * 2), radius_b, radius_b)
        painter.setClipPath(clip_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawRect(QRectF(cx - R, cy - R, R * 2, R * 2))
        painter.restore()

    def _draw_skill_cd_name(self, painter, skill, cx, cy, s):
        """绘制技能名称（带反色圆角背景，类似Buff名）。"""
        lang = self.settings.get("language", "zh")
        name = _skill_name(skill.get("ability_hash", 0), lang)
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
        }

    def _make_index_color_override(self, index, cfg):
        """为第 index 个 buff（index 从 0 起）生成颜色覆盖；index 0 返回 None（用基础色）。"""
        if index <= 0:
            return None
        deg = self._MB_HUE_OFFSETS.get(index, (index * 72) % 360)
        override = {}
        if cfg["ext"]:
            for key in self.EXTERNAL_COLOR_KEYS:
                override[key] = rotate_hue(self.settings.get(key, "#ffffff"), deg)
        if cfg["int"]:
            for key in self.INTERNAL_COLOR_KEYS:
                override[key] = rotate_hue(self.settings.get(key, "#ffffff"), deg)
        return override

    def _get_color(self, key, color_override=None):
        """获取颜色十六进制值，支持补色覆盖。"""
        if color_override and key in color_override:
            return color_override[key]
        return self.settings.get(key, "#ffffff")

    # ================================================================
    #  绘制：一体化圆角半透明背景（标题栏独立色 + 内容区独立色）
    # ================================================================
    def _draw_backdrop(self, painter):
        backdrop_bottom = self.core_canvas_h

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
        painter.setClipPath(path)
        painter.setOpacity(self._effective_opacity("title_bar_color"))
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
        elif reason == "no_char":
            texts = {"zh": "未检测到角色", "zh_tw": "未偵測到角色", "en": "No character"}
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
        has_update = getattr(self, "_update_has_update", False)
        hidden_rect = QRect(-9999, -9999, 0, 0)

        # 图标按钮区域：更新(update)、最小化、设置、锁定、退出
        update_rect, minimize_rect, settings_rect, lock_rect, exit_rect = self._calc_icon_btn_rects()
        self._btn_update_rect = update_rect if has_update or not self.locked else hidden_rect
        self._btn_minimize_rect = hidden_rect if self.locked else minimize_rect
        self._btn_settings_rect = hidden_rect if self.locked else settings_rect
        self._btn_lock_rect = lock_rect
        self._btn_exit_rect = hidden_rect if self.locked else exit_rect

        # 窗口局部像素版命中矩形（与 paintEvent 的 painter.scale(disp_w) 对应）
        disp = getattr(getattr(self, "core_win", None), "disp_w", 1.0) or 1.0
        hit_m = 2
        def _to_win(r):
            return QRect(int(r.x() * disp) - hit_m, int(r.y() * disp) - hit_m,
                         int(r.width() * disp) + 2 * hit_m, int(r.height() * disp) + 2 * hit_m)
        self._btn_update_rect_win = _to_win(update_rect) if (has_update or not self.locked) else hidden_rect
        self._btn_minimize_rect_win = hidden_rect if self.locked else _to_win(minimize_rect)
        self._btn_settings_rect_win = hidden_rect if self.locked else _to_win(settings_rect)
        self._btn_lock_rect_win = _to_win(lock_rect)
        self._btn_exit_rect_win = hidden_rect if self.locked else _to_win(exit_rect)

        icon_color = QColor(self.settings.get("icon_color", "#7f8fa6"))
        pressed = getattr(self, "_pressed_core_btn", None) if getattr(self, "_pressed_visual", False) else None

        painter.save()
        painter.setOpacity(self._effective_opacity("icon_color"))

        if not self.locked:
            # 状态文字
            if self.settings.get("show_titlebar_status", True):
                status_text = self._build_titlebar_status_text(lang)
                if status_text:
                    icon_row_h = self.ICON_BTN_SIZE + 10
                    text_rect = QRect(0, icon_row_h, self.core_canvas_w, th - icon_row_h)
                    painter.setPen(QColor(self.settings.get("icon_color", "#7f8fa6")))
                    painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                    painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, status_text)

            # 按下态凹陷背景
            for name, rect in (("update", update_rect), ("minimize", minimize_rect),
                               ("settings", settings_rect), ("exit", exit_rect)):
                if pressed == name:
                    self._draw_btn_press_bg(painter, rect)

            # 更新按钮：有新版本时发光高亮，否则暗淡占位
            update_color = QColor("#f5c842") if has_update else icon_color
            if has_update:
                self._draw_icon_update(painter, update_rect, update_color, glow=True)
            else:
                base_op = painter.opacity()
                painter.setOpacity(base_op * 0.30)
                self._draw_icon_update(painter, update_rect, icon_color, glow=False)
                painter.setOpacity(base_op)

            # 最小化 / 设置 / 退出
            self._draw_icon_minimize(painter, minimize_rect.translated(1, 1) if pressed == "minimize" else minimize_rect, icon_color)
            self._draw_icon_settings(painter, settings_rect.translated(1, 1) if pressed == "settings" else settings_rect, icon_color)
            self._draw_icon_exit(painter, exit_rect.translated(1, 1) if pressed == "exit" else exit_rect, icon_color)
        else:
            # 锁定模式：锁定图标始终可点；有新版本时再显示更新按钮
            if has_update:
                if pressed == "update":
                    self._draw_btn_press_bg(painter, update_rect)
                self._draw_icon_update(painter, update_rect, QColor("#f5c842"), glow=True)
            if pressed == "lock":
                self._draw_btn_press_bg(painter, lock_rect)
        lock_icon_color = QColor("#ffaa22") if self.locked else icon_color
        self._draw_icon_lock(painter, lock_rect.translated(1, 1) if pressed == "lock" else lock_rect, lock_icon_color, self.locked)

        # 下载中：在更新按钮上叠加环形进度 + 百分比（修复「下载进度从未绘制」的问题）
        if getattr(self, "_update_downloading", False):
            pct = max(0, min(100, int(getattr(self, "_update_progress_pct", 0))))
            self._draw_update_progress(painter, update_rect, pct)

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
        """构建标题栏状态文字：角色名 + 启用的buff名称和层数。"""
        if self.status == "no_game":
            return ""  # 不显示「等待游戏...」，避免能力/标题栏出现该占位文字
        if self.status == "no_char" or not (self.char_type or self.charid_hash):
            if lang == "en": return "No character"
            if lang == "zh_tw": return "未偵測到角色"
            return "未检测到角色"
        char_name = _resolve_char(self.charid_hash, self.char_type, lang)[0]
        if not self.active_buffs:
            return char_name
        buff_parts = []
        for buff in self.active_buffs:
            name = _buff_name(buff, lang)
            stacks = int(buff.get("stacks", 0))
            max_s = buff.get("max_stacks")
            if max_s and max_s > 1:
                buff_parts.append(f"{name} {stacks}/{max_s}")
            else:
                buff_parts.append(name)
        return f"{char_name} / {' + '.join(buff_parts)}"

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

    def _draw_icon_update(self, painter, rect, color, glow=False):
        """更新按钮图标：向下箭头 + 可选呼吸光晕。"""
        painter.save()
        if glow:
            # 柔和呼吸光：alpha 随时间 50~140 脉动
            t = time.time()
            alpha = int(95 + 55 * math.sin(t * 5.5))
            grad = QRadialGradient(rect.center(), rect.width() * 0.85)
            grad.setColorAt(0.0, QColor(255, 200, 60, alpha))
            grad.setColorAt(0.6, QColor(255, 170, 40, int(alpha * 0.35)))
            grad.setColorAt(1.0, QColor(255, 170, 40, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(rect.center(), int(rect.width() / 2), int(rect.height() / 2))
        # 箭头
        cx = rect.center().x()
        cy = rect.center().y()
        pen = QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPoint(cx, cy - 4), QPoint(cx, cy + 3))
        painter.drawLine(QPoint(cx - 4, cy - 1), QPoint(cx, cy + 3))
        painter.drawLine(QPoint(cx + 4, cy - 1), QPoint(cx, cy + 3))
        painter.restore()

    def _draw_update_progress(self, painter, rect, pct):
        """下载中：在更新按钮上绘制环形进度 + 百分比文字（绿环表示进行中）。"""
        if rect is None or rect.width() <= 0:
            return
        painter.save()
        cx, cy = rect.center().x(), rect.center().y()
        r = min(rect.width(), rect.height()) / 2 - 1
        # 背景底环（半透明白）
        painter.setPen(QPen(QColor(255, 255, 255, 55), 2))
        painter.drawEllipse(QPoint(cx, cy), int(r), int(r))
        # 进度环（绿色，从 12 点方向顺时针）
        if pct > 0:
            span = int(pct * 360 / 100.0)
            painter.setPen(QPen(QColor("#3fd16b"), 2.5))
            painter.drawArc(QPoint(cx, cy), int(r), int(r), 90 * 16, -span * 16)
        # 百分比文字
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 6, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, f"{int(pct)}%")
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
    def _draw_indicator_outer_outline(self, painter, cx, cy, r, is_lv7, include_spikes=True, buff=None, color_override=None, flash_scale=1.0):
        """绘制指示器最外层勾边：先画底层粗白边，再由圆环/尖刺本体覆盖内侧。

        V273：flash_scale 透传——层数闪光时圆环外描边随尖刺一起以圆心为中心放大，
        避免「尖刺外扩、外圈勾边不动」的脱节观感。
        """
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
        # V273：闪光时同步放大圆环 + 尖刺外描边（与 _draw_spikes 同 flash_scale，保持对齐）
        if flash_scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(flash_scale, flash_scale)
            painter.translate(-cx, -cy)
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

    def _draw_spikes(self, painter, cx, cy, r, is_lv7, buff=None, color_override=None, flash_record=None):
        """绘制尖刺 + 装饰小球。

        V274 变更：层数增加的闪光【只作用于「新增」的那一支（及装饰圆、勾边）】——
        仅 index >= flash_record["from"]（上一次层数）的尖刺以圆心为中心放大并白色闪光；
        其余尖刺保持不动。中间圆环/计时器/层数字完全不在此函数内绘制，不受闪光影响。
        """
        if not buff:
            return
        max_stacks = self._buff_max_stacks(buff)
        visible_spikes = min(max(int(buff.get("stacks", 0)), 0), max_stacks)
        if visible_spikes <= 0:
            return
        key = "spike_color_lv7" if is_lv7 else "spike_color_normal"
        spike_color = qcolor(self._get_color(key, color_override))

        # 预计算几何
        spikes = []
        for i in range(visible_spikes):
            angle = -90 + i * (360.0 / max_stacks)
            spikes.append(self._calc_spike_points(cx, cy, r, angle))

        # 新增尖刺判定：仅 index >= 上一次层数 的尖刺参与闪光
        prev_stacks = 0
        flash_scale = 1.0
        flash_progress = 0.0
        if flash_record is not None:
            flash_scale, flash_progress = self._compute_group_flash_scale(flash_record)
            prev_stacks = int(flash_record.get("from", 0))
        new_from = max(0, prev_stacks)

        # 局部函数：描出一支尖刺的勾边路径（含装饰圆）
        def _stroke_spike(p, pts):
            path = QPainterPath()
            path.moveTo(pts["tip"][0], pts["tip"][1])
            path.lineTo(pts["left"][0], pts["left"][1])
            path.lineTo(pts["root"][0], pts["root"][1])
            path.lineTo(pts["right"][0], pts["right"][1])
            path.closeSubpath()
            p.drawPath(path)
            bead_r = max(0, int(self.spike_bead_radius))
            if bead_r > 0:
                bx, by = pts["bead"]
                p.drawEllipse(QPoint(int(bx), int(by)), bead_r, bead_r)

        use_outline = bool(self.settings.get("use_indicator_outline", DEFAULT_SETTINGS.get("use_indicator_outline", True)))
        outline_w = max(0, int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS.get("indicator_outline_width", 2))))
        outline_color = qcolor(self._get_color("indicator_outline_color", color_override))
        out_opacity = self._effective_opacity("indicator_outline_color")

        # 0) 普通尖刺外勾边（仅非新增尖刺；新增尖刺的勾边在闪光段随尖刺一起放大绘制）
        if use_outline and outline_w > 0 and out_opacity > 0:
            painter.save()
            painter.setOpacity(out_opacity)
            painter.setBrush(Qt.NoBrush)
            pen = QPen(outline_color, outline_w * 2 + 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            for i, pts in enumerate(spikes):
                if i >= new_from and flash_progress > 0.0:
                    continue
                _stroke_spike(painter, pts)
            painter.restore()

        # 1) 正常尖刺本体 + 装饰小球（始终绘制，含新增尖刺的正常位置）
        painter.setOpacity(self._effective_opacity(key))
        light_c = QColor(spike_color).lighter(140)
        dark_c = QColor(spike_color).darker(135)
        outline_c = QColor(spike_color).darker(180)
        outline_c.setAlpha(150)
        for pts in spikes:
            path = QPainterPath()
            path.moveTo(pts["tip"][0], pts["tip"][1])
            path.lineTo(pts["left"][0], pts["left"][1])
            path.lineTo(pts["root"][0], pts["root"][1])
            path.lineTo(pts["right"][0], pts["right"][1])
            path.closeSubpath()
            bead_r = max(0, int(self.spike_bead_radius))
            bead_x, bead_y = pts["bead"]
            grad = QLinearGradient(pts["root"][0], pts["root"][1], pts["tip"][0], pts["tip"][1])
            grad.setColorAt(0.0, dark_c)
            grad.setColorAt(0.42, spike_color)
            grad.setColorAt(1.0, light_c)
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(outline_c, 1.0))
            painter.drawPath(path)
            if bead_r > 0:
                bead_c = QColor(spike_color).darker(110)
                bead_outline = QColor(spike_color).darker(180)
                painter.setBrush(bead_c)
                painter.setPen(QPen(bead_outline, 1.2))
                painter.drawEllipse(QPoint(int(bead_x), int(bead_y)), bead_r, bead_r)

        # 2) 新增尖刺的闪光：以圆心为中心放大 + 白色叠加（仅 i>=new_from 且闪光进行中）
        if flash_progress > 0.0 and flash_scale > 1.0 and new_from < visible_spikes:
            fc = qcolor(self.settings.get("flash_color", "#ffffff"))
            whiten = max(0.0, 1.0 - flash_progress)
            for i, pts in enumerate(spikes):
                if i < new_from:
                    continue
                painter.save()
                painter.translate(cx, cy)
                painter.scale(flash_scale, flash_scale)
                painter.translate(-cx, -cy)
                # 勾边（随尖刺一起放大闪）
                if use_outline and outline_w > 0 and out_opacity > 0:
                    painter.save()
                    painter.setOpacity(out_opacity)
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(QPen(outline_color, outline_w * 2 + 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    _stroke_spike(painter, pts)
                    painter.restore()
                # 白色闪光叠加
                painter.setOpacity(whiten)
                painter.setBrush(QBrush(fc))
                painter.setPen(QPen(fc, 1.0))
                _stroke_spike(painter, pts)
                painter.restore()

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
    def _draw_timer_progress(self, painter, cx, cy, r, is_lv7, buff=None, color_override=None):
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
            # 单层buff：只有倒计时胶囊，居中显示（使用「单层buff倒计时胶囊」独立样式）
            if has_timer:
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
            dh_text = "-" if stacks == 0 else str(stacks)
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
            text = "-" if stacks == 0 else str(stacks)
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
    def _draw_dodge_icon_at(self, painter, x, y, icon, flash_scale=1.0, flash_progress=0.0):
        """在 (x,y) 绘制单个翻滚图标（警告牌 / png / 兜底方块）。

        V272 闪光规则：翻滚次数增加时触发一次模块级放大+白闪。
        闪光形状 = 白色实心填充 + 白色勾边外轮廓，作为整体放大并随 progress 衰减，
        平时不显示（由设置「翻滚闪光·白色实心勾边」开关控制是否启用）。
        """
        warning_mode = self.dodge_count >= 6
        if warning_mode:
            # 第6/7次：黄色圆角三角填充 + 红色圆角三角边框
            self._draw_warning_roll_icon(painter, x, y, icon)
            return
        has_shrimp = not self.shrimp.isNull()
        # 图标本体
        if has_shrimp:
            painter.drawPixmap(x, y, self.shrimp)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ff8a56"))
            path = QPainterPath()
            path.addRoundedRect(x + 2, y + max(2, icon // 6), icon - 4, max(8, icon * 2 // 3), 6, 6)
            painter.drawPath(path)
        # 白色实心勾边闪光：仅翻滚触发瞬间（flash_progress>0）出现一次，随 progress 衰减消失
        if flash_progress > 0.0 and has_shrimp and bool(self.settings.get("dodge_outline_enabled", True)):
            cxic, cyic = x + icon / 2.0, y + icon / 2.0
            fade = max(0.0, 1.0 - flash_progress)
            painter.save()
            if flash_scale != 1.0:
                painter.translate(cxic, cyic)
                painter.scale(flash_scale, flash_scale)
                painter.translate(-cxic, -cyic)
            # 1) 内部实心填充（白色）：V274 完全不透明——勾边内部是实心白块，不淡出
            simg = self._get_dodge_solid_img_white()
            if simg is not None:
                painter.setOpacity(1.0)
                painter.drawImage(QRectF(x, y, icon, icon), simg)
            # 2) 外部勾边轮廓（白色辉光）：自然随 progress 衰减
            oimg = self._get_dodge_outline_img_white()
            if oimg is not None:
                painter.setOpacity(fade)
                ow, oh = oimg.width(), oimg.height()
                painter.drawImage(QRectF(x - (ow - icon) / 2.0, y - (oh - icon) / 2.0, ow, oh), oimg)
            painter.restore()

    # ----------------------------------------------------------------
    #  翻滚勾边：按 PNG 内部图案外边缘描边（形态学膨胀求轮廓）
    # ----------------------------------------------------------------
    def _build_shape_outline(self, src_img, edge_w, glow_w, threshold, color):
        """从带透明通道的源图 alpha 求出图案外轮廓，返回一张带 alpha 的 RGBA 图像
        （图案边缘一圈实色描边 + 向外扩展的渐隐辉光），颜色已染成 color。
        返回 None 表示无法处理。
        """
        if src_img is None or src_img.isNull():
            return None
        w0, h0 = src_img.width(), src_img.height()
        if w0 <= 0 or h0 <= 0:
            return None
        edge_w = max(0, int(round(edge_w)))
        glow_w = max(0, int(round(glow_w)))
        pad = edge_w + glow_w
        W, H = w0 + 2 * pad, h0 + 2 * pad
        # 1) 构建掩码（图案像素 = alpha>阈值），放置在带 padding 的画布中央
        mask = bytearray(W * H)
        src = src_img.toImage().convertToFormat(QImage.Format_ARGB32)
        for yy in range(h0):
            row = bytes(src.scanLine(yy))
            dy = yy + pad
            base = dy * W + pad
            for xx in range(w0):
                a = row[xx * 4 + 3]
                mask[base + xx] = 1 if a > threshold else 0

        # 2) 3x3 极大值膨胀一步（半径+1）
        def dilate_step(m):
            out = bytearray(W * H)
            for y in range(H):
                y0 = max(0, y - 1); y1 = min(H - 1, y + 1)
                base = y * W
                for x in range(W):
                    if m[base + x]:
                        out[base + x] = 1
                        continue
                    x0 = max(0, x - 1); x1 = min(W - 1, x + 1)
                    found = False
                    for ny in range(y0, y1 + 1):
                        nb = ny * W
                        for nx in range(x0, x1 + 1):
                            if m[nb + nx]:
                                found = True
                                break
                        if found:
                            break
                    if found:
                        out[base + x] = 1
            return out

        # 3) 逐级膨胀，逐带染色：前 edge_w 层为实色描边，其后 glow_w 层为渐隐辉光
        out = QImage(W, H, QImage.Format_ARGB32)
        out.fill(0)
        prev = mask
        R = edge_w + glow_w
        cr = color.red(); cg = color.green(); cb = color.blue()
        glow_peak = 150
        for r in range(1, R + 1):
            cur = dilate_step(prev)
            # band = cur 且不在 prev（即本次新扩张到的像素）
            is_edge = r <= edge_w
            if is_edge:
                a = 255
            else:
                a = int(glow_peak * (1.0 - (r - edge_w) / (glow_w + 1.0)))
                if a < 0:
                    a = 0
            if a > 0:
                for y in range(H):
                    base = y * W
                    ob = base
                    for x in range(W):
                        i = base + x
                        if cur[i] and not prev[i]:
                            out.setPixelColor(x, y, QColor(cr, cg, cb, a))
            prev = cur
        return out

    def _get_dodge_outline_img(self):
        """获取（带缓存）翻滚 PNG 的图案轮廓辉光图像；参数/图标变化时自动重建。"""
        if self.shrimp.isNull():
            return None
        edge_w = float(self.settings.get("dodge_outline_width", 2.0))
        glow_w = float(self.settings.get("dodge_outline_glow", 5.0))
        thr = int(self.settings.get("dodge_outline_threshold", 24))
        fc = QColor(self.settings.get("flash_color", "#ffffff"))
        key = (id(self.shrimp), edge_w, glow_w, thr, fc.rgb())
        if getattr(self, "_dodge_outline_img", None) is not None and self._dodge_outline_key == key:
            return self._dodge_outline_img
        img = self._build_shape_outline(self.shrimp, edge_w, glow_w, thr, fc)
        self._dodge_outline_img = img
        self._dodge_outline_key = key
        return img

    def _get_dodge_outline_img_white(self):
        """白色翻滚勾边（闪光形状用），与 flash_color 解耦，恒为白色。"""
        if self.shrimp.isNull():
            return None
        edge_w = float(self.settings.get("dodge_outline_width", 2.0))
        glow_w = float(self.settings.get("dodge_outline_glow", 5.0))
        thr = int(self.settings.get("dodge_outline_threshold", 24))
        white = QColor("#ffffff")
        key = (id(self.shrimp), edge_w, glow_w, thr, "white")
        if getattr(self, "_dodge_outline_img_white", None) is not None and getattr(self, "_dodge_outline_key_white", None) == key:
            return self._dodge_outline_img_white
        img = self._build_shape_outline(self.shrimp, edge_w, glow_w, thr, white)
        self._dodge_outline_img_white = img
        self._dodge_outline_key_white = key
        return img

    def _get_dodge_solid_img_white(self):
        """白色实心填充（闪光内部用），按 PNG alpha 阈值决定填充区域。"""
        if self.shrimp.isNull():
            return None
        thr = int(self.settings.get("dodge_outline_threshold", 24))
        key = (id(self.shrimp), thr, "solid_white")
        if getattr(self, "_dodge_solid_img_white", None) is not None and getattr(self, "_dodge_solid_key_white", None) == key:
            return self._dodge_solid_img_white
        src = self.shrimp.toImage().convertToFormat(QImage.Format_ARGB32)
        w, h = src.width(), src.height()
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(0)
        white = QColor("#ffffff")
        for yy in range(h):
            row = bytes(src.scanLine(yy))
            base = yy * w
            for xx in range(w):
                if row[xx * 4 + 3] > thr:
                    img.setPixelColor(xx, yy, white)
        self._dodge_solid_img_white = img
        self._dodge_solid_key_white = key
        return img

    def _compute_group_flash_scale(self, flash_record):
        """计算统一闪光放大缩放。flash_record 为 {"start": ms} 或 None。

        动画曲线：0~30% 放大到 flash_scale，30%~100% 缩回 1.0。
        返回 (scale, progress)，其中 progress=0 表示闪光已结束/未触发。
        """
        if flash_record is None:
            return 1.0, 0.0
        start = flash_record.get("start")
        if start is None:
            return 1.0, 0.0
        dur = int(self.settings.get("flash_duration_ms", 400))
        elapsed = int(time.time() * 1000) - start
        if elapsed >= dur:
            return 1.0, 0.0
        progress = elapsed / dur
        ready_scale = int(self.settings.get("flash_scale", 140)) / 100.0
        if progress < 0.3:
            scale = 1.0 + (ready_scale - 1.0) * (progress / 0.3)
        else:
            scale = ready_scale - (ready_scale - 1.0) * ((progress - 0.3) / 0.7)
        return scale, progress

    def render_roll(self, painter):
        """翻滚模块渲染：图标整体居中于本窗口画布（roll_cx/cy），支持横/竖排与模块级闪光。"""
        # 先画模块背景：即使 dodge_count=0 或没进游戏，也让窗口可见、可拖动
        self._draw_module_backdrop(painter, self.roll_canvas_w, self.roll_canvas_h, draw_border=True, module_key="roll")

        count = min(max(int(self.dodge_count), 0), self.MAX_DODGES)
        if count <= 0:
            # 没有翻滚次数时清理组级闪光记录，避免下次从过期状态开始
            self._roll_group_flash = None
            return

        # 翻滚UI不透明度（锁定时不减半；且不随角色是否被识别而改变）
        roll_opacity = max(0, min(100, int(self.settings.get("roll_icon_opacity", DEFAULT_SETTINGS["roll_icon_opacity"])))) / 100.0

        # 模块级闪光：翻滚次数增加时整个图标组统一放大闪烁
        group_flash_scale, group_flash_progress = self._compute_group_flash_scale(getattr(self, "_roll_group_flash", None))
        if group_flash_progress <= 0.0:
            self._roll_group_flash = None

        icon = self.dodge_icon_size
        gap = self.ROLL_ICON_GAP
        horizontal = (self.settings.get("roll_orientation", "horizontal") != "vertical")

        painter.save()
        painter.setOpacity(roll_opacity)
        # 以画布中心为锚点应用模块级闪光缩放
        if group_flash_scale != 1.0:
            painter.translate(self.roll_cx, self.roll_cy)
            painter.scale(group_flash_scale, group_flash_scale)
            painter.translate(-self.roll_cx, -self.roll_cy)
        if horizontal:
            group_width = count * icon + (count - 1) * gap if count > 1 else icon
            start_x = self.roll_cx - group_width / 2.0
            base_y = self.roll_cy - icon / 2.0
            for i in range(count):
                x = int(start_x + i * (icon + gap))
                self._draw_dodge_icon_at(painter, x, int(base_y), icon, group_flash_scale, group_flash_progress)
        else:
            group_height = count * icon + (count - 1) * gap if count > 1 else icon
            start_y = self.roll_cy - group_height / 2.0
            base_x = self.roll_cx - icon / 2.0
            for i in range(count):
                y = int(start_y + i * (icon + gap))
                self._draw_dodge_icon_at(painter, int(base_x), y, icon, group_flash_scale, group_flash_progress)
        painter.restore()

    def _draw_warning_roll_icon(self, painter, x, y, icon):
        """第6/7次翻滚：黄色圆角三角内部填充 + 红色圆角三角边框。

        V274 全部参数可调：大小 warning_size_scale、外边色 warning_outline_color、
        内填色 warning_fill_color、外边粗度 warning_outline_width（占三角边长比例）。
        红边用「两个不同尺寸三角」直接控制：红比黄每边少 inset bt=边长*wfrac，
        红边可见粗度=bt，不受描边宽度上限钳制。
        """
        warn_scale = float(self.settings.get("warning_size_scale", DEFAULT_SETTINGS.get("warning_size_scale", 0.68)))
        warn_scale = max(0.3, min(1.0, warn_scale))
        sz = int(icon * warn_scale)
        if sz < 8:
            return
        ox = x + (icon - sz) // 2
        oy = y + (icon - sz) // 2
        cx = ox + sz / 2.0

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # 红边可见粗度（占三角边长比例，可调）
        wfrac = float(self.settings.get("warning_outline_width", DEFAULT_SETTINGS.get("warning_outline_width", 0.24)))
        wfrac = max(0.03, min(0.5, wfrac))
        bt = max(3, int(sz * wfrac))
        pad_red = max(3, int(sz * 0.07))
        pad_yellow = pad_red + bt
        corner_r = max(4, int(sz * 0.14))

        def _rounded_triangle(top, left, right, bottom, w):
            sharp = QPainterPath()
            sharp.moveTo(cx, top)
            sharp.lineTo(right, bottom)
            sharp.lineTo(left, bottom)
            sharp.closeSubpath()
            st = QPainterPathStroker()
            st.setWidth(w)
            st.setJoinStyle(Qt.RoundJoin)
            st.setCapStyle(Qt.RoundCap)
            return st.createStroke(sharp).united(sharp)

        # 红色大三角（外框）
        tri_red = _rounded_triangle(oy + pad_red, ox + pad_red, ox + sz - pad_red, oy + sz - pad_red, corner_r * 2)
        # 黄色小三角（内填，向内收 bt → 露出红边）
        tri_yellow = _rounded_triangle(oy + pad_yellow, ox + pad_yellow, ox + sz - pad_yellow, oy + sz - pad_yellow, corner_r * 2)

        red = qcolor(self._get_color("warning_outline_color"))
        yellow = qcolor(self._get_color("warning_fill_color"))

        painter.setPen(Qt.NoPen)
        painter.setOpacity(self._effective_opacity("warning_outline_color"))
        painter.setBrush(red)
        painter.drawPath(tri_red)
        painter.setOpacity(self._effective_opacity("warning_fill_color"))
        painter.setBrush(yellow)
        painter.drawPath(tri_yellow)

        painter.restore()

    # ================================================================
    #  鼠标事件：标题栏拖动 + 图标按钮
    # ================================================================
    # 鼠标事件 / 拖动 / 图标按钮 均在 ModuleWindow / CoreWindow 子类中实现。

    def open_settings(self):
        if not self.core_win.isVisible():
            self.core_win.show()
        backup = dict(self.settings)
        try:
            # 关键修复：设置对话框不再以 core_win（Qt.Tool 窗口）为父。
            # Windows 上，若一个模态对话框之父是 Qt.Tool 窗口，当焦点切到其它应用（如游戏）时，
            # 父级 Tool 窗口会被系统级联隐藏，表现为「只有核心检测区消失、重置才能找回」。
            # 改为无父顶层对话框 + WindowStaysOnTopHint + 应用模态，并手动定位到核心窗口附近。
            dlg = SettingsDialog(None, self.settings, ctrl=self)
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
            try:
                cg = self.core_win.geometry()
                dlg.move(max(0, cg.x() + (cg.width() - dlg.width()) // 2),
                          max(0, cg.y() + max(20, int(cg.height() * 0.12))))
            except Exception:
                pass
        except Exception as e:
            import traceback as _tb
            err = _tb.format_exc()
            try:
                _logp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings_error.log")
                with open(_logp, "a", encoding="utf-8") as _f:
                    _f.write(err + "\n")
            except Exception:
                pass
            lang = self.settings.get("language", "zh")
            _tt = {"zh": ("设置打开失败", "设置窗口构造异常：\n%s"),
                   "zh_tw": ("設定開啟失敗", "設定視窗建構異常：\n%s"),
                   "en": ("Settings Error", "Settings dialog construction failed:\n%s")}
            _tt = _tt.get(lang, _tt["en"])
            QMessageBox.critical(self.core_win, _tt[0], _tt[1] % e)
            return
        dlg.settings_changed.connect(self._apply_live_settings)
        self.settings_dialog = dlg
        # 设置对话框打开期间启动高频刷新（50ms），拖动滑块时悬浮窗预览更跟手
        self._settings_live_timer = QTimer(self)
        self._settings_live_timer.timeout.connect(self._refresh_live_preview)
        self._settings_live_timer.start(50)
        rc = dlg.exec()
        if getattr(self, "_settings_live_timer", None) is not None:
            self._settings_live_timer.stop()
            self._settings_live_timer.deleteLater()
            self._settings_live_timer = None
        # 关闭后兜底：确保核心窗口仍可见（防止任何意外的级联隐藏）
        try:
            if not self.core_win.isVisible():
                self.core_win.show()
            self.core_win.raise_()
        except Exception:
            pass
        if rc == QDialog.Accepted:
            self.settings = dlg.get_settings()
            save_settings(self.settings)
            self._after_settings_changed()
        else:
            self.settings = backup
            save_settings(self.settings)
            self._after_settings_changed()
        self.settings_dialog = None

    # ----------------------------------------------------------------
    # 内存探针：把当前角色 actor 结构体的内存按 u32 导出到文件，
    # 用于在「class(团长职业等级) / 异能槽(伊度)」这类非 ExStatus 的裸值 buff
    # 找不到可读地址时，由用户在游戏中实测、定位真实偏移。
    # ----------------------------------------------------------------
    def dump_actor_memory(self, start=0x0, length=0x2000, path=None):
        lang = self.settings.get("language", "zh")
        _t = {
            "no_game": {"zh": "尚未连接到游戏进程（请先启动游戏并进入战斗）。",
                        "zh_tw": "尚未連線到遊戲進程（請先啟動遊戲並進入戰鬥）。",
                        "en": "Not connected to game (please launch the game and enter combat)."},
            "no_char": {"zh": "未检测到角色基址（请确认已进入游戏）。",
                        "zh_tw": "未偵測到角色基址（請確認已進入遊戲）。",
                        "en": "Character base address not found (please confirm game has loaded)."},
            "read_fail": {"zh": "读取内存失败（角色可能已离场）。",
                          "zh_tw": "讀取記憶體失敗（角色可能已離場）。",
                          "en": "Memory read failed (character may have left the field)."},
            "ok": {"zh": "已导出到：\n%s\n(offset 范围 0x%X ~ 0x%X)\n\n请在游戏中切换/改变目标值（如更换团长职业、消耗/积攒伊度异能），对比两次 dump 找出对应偏移后告诉我。",
                   "zh_tw": "已匯出到：\n%s\n(offset 範圍 0x%X ~ 0x%X)\n\n請在遊戲中切換/改變目標值（如更換團長職業、消耗/積攢伊度異能），對比兩次 dump 找出對應偏移後告訴我。",
                   "en": "Exported to:\n%s\n(offset range 0x%X ~ 0x%X)\n\nChange target values in-game (e.g. switch Captain class, spend/charge Id gauge), compare two dumps to find the offset."},
            "write_fail": {"zh": "写出失败：%s",
                           "zh_tw": "寫出失敗：%s",
                           "en": "Write failed: %s"},
            "title": {"zh": "内存探针", "zh_tw": "記憶體探針", "en": "Memory Probe"},
        }
        if self.handle is None or self.pptr is None:
            QMessageBox.warning(self.core_win, _t["title"][lang], _t["no_game"][lang])
            return
        try:
            char_base = read_u64(self.handle, self.pptr + CHAR_PTR_OFF)
        except Exception:
            char_base = None
        if not char_base:
            QMessageBox.warning(self.core_win, _t["title"][lang], _t["no_char"][lang])
            return
        buf = rpm(self.handle, char_base + start, length)
        if buf is None:
            QMessageBox.warning(self.core_win, _t["title"][lang], _t["read_fail"][lang])
            return
        if path is None:
            try:
                desk = os.path.join(os.path.expanduser("~"), "Desktop")
            except Exception:
                desk = EXE_DIR
            path = os.path.join(desk, "actor_dump.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# actor base = 0x%X\n" % char_base)
                f.write("# offset(相对actor基址)  hex        dec\n")
                for i in range(0, len(buf) - 3, 4):
                    val = struct.unpack("<I", buf[i:i + 4])[0]
                    f.write("0x%04X  0x%08X  %10d\n" % (start + i, val, val))
            QMessageBox.information(self.core_win, _t["title"][lang],
                                    _t["ok"][lang] % (path, start, start + length))
        except Exception as e:
            QMessageBox.critical(self.core_win, _t["title"][lang], _t["write_fail"][lang] % e)

    def _after_settings_changed(self):
        """设置变化后刷新标题、重新计算布局并刷新三个窗口尺寸/位置。"""
        lang = self.settings.get("language", "zh")
        self.core_win.setWindowTitle(f"{_app_title(lang)} v{APP_VERSION}")
        self.recalc_layout()
        self.load_dodge_icon()
        self._refresh_window_geometries()

    def _apply_live_settings(self, new_settings):
        self.settings = dict(new_settings)
        save_settings(self.settings)
        self._after_settings_changed()
        # 轮廓参数/图标变更时让缓存失效，确保新参数立即重建
        self._dodge_outline_img = None
        self._dodge_outline_key = None
        # 强制三个模块窗口同步重绘（repaint 比 update 更即时，适合设置面板拖动时实时预览）
        for name in ("core_win", "roll_win", "skill_win"):
            w = getattr(self, name, None)
            if w is not None:
                w.repaint()
                w.update()
        # 在模态设置对话框内也立即把重绘事件刷到屏幕上，避免被事件循环缓冲
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def _anim_repaint_all(self):
        """常驻高频重绘（40ms）：驱动呼吸光/闪光放大等基于时间的动画。

        即使设置面板以 modal 打开，本定时器仍在事件循环中触发，repaint() 同步执行，
        让呼吸光频率/柔和度/光圈大小以及闪光放大在拖动滑块时实时反馈到悬浮窗。
        """
        for name in ("core_win", "roll_win", "skill_win"):
            w = getattr(self, name, None)
            if w is not None and w.isVisible():
                w.repaint()

    def _refresh_live_preview(self):
        """设置对话框打开期间的高频刷新回调，让滑块/数值改动即时反映到悬浮窗。"""
        for name in ("core_win", "roll_win", "skill_win"):
            w = getattr(self, name, None)
            if w is not None and w.isVisible():
                w.repaint()

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
                    # 用 hide() 而非 showMinimized()：本程序窗口是 Qt.Tool+无边框+透明背景，
                    # 在 Windows 上 showMinimized() 容易变成「最小化后无法从任务栏/托盘恢复」的隐形状态。
                    w.hide()

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
        snap = read_overlay_data(self.handle, self.pptr, raw_locked=self._raw_locked_addrs)
        self._raw_locked_addrs = snap.get("raw_locked", {})
        # actor 变化日志（用于诊断伊德龙人化等形态切换）
        char_base = read_u64(self.handle, self.pptr + CHAR_PTR_OFF) if self.pptr else 0
        if char_base and char_base != self._prev_actor:
            self._prev_actor = char_base
        self.status = snap["status"]
        self.dodge_count = snap["dodge"] or 0
        # 翻滚模块级闪光：可用翻滚次数增加时触发统一放大动画
        if self.dodge_count > getattr(self, "_prev_dodge_count", 0):
            self._roll_group_flash = {"start": int(time.time() * 1000)}
        self._prev_dodge_count = self.dodge_count
        self.char_type = snap.get("char_type", 0)
        self.charid_hash = snap.get("charid_hash", 0)
        self.pl_id = snap.get("pl_id") or _pl_hash_map.get(self.charid_hash)

        # 按设置过滤启用的 buff，并按顺位（buff_order）升序排列
        # 键格式：优先新 pl_id 键 "PLxxxx_idx"（与设置面板一致）。
        buff_order = self.settings.get("buff_order", {})
        all_buffs = snap.get("buffs", [])
        self.active_buffs = []

        def _bkey(buff):
            """计算 buff 顺位键。通用 buff 用 GENERAL_ 前缀，角色专属用 PL_id。"""
            group = buff.get("group")
            if group:
                return f"{group}_{buff['index']}"
            pl = self.pl_id
            if not pl and self.char_type in CHAR_TYPE_TO_PL:
                pl = CHAR_TYPE_TO_PL[self.char_type]
            return f"{pl}_{buff['index']}" if pl else f"{self.char_type:#04x}_{buff['index']}"

        # 过滤（rank>0 视为启用）并按顺位升序排列：buff[0]=第1位，buff[1]=第2位...
        _ordered = []
        for buff in all_buffs:
            rank = buff_order.get(_bkey(buff), buff['index'] + 1)
            if rank and rank > 0:
                _ordered.append((rank, buff))
        _ordered.sort(key=lambda t: t[0])
        self.active_buffs = [b for _, b in _ordered]
        # 检测层数增加 → 新出现尖刺闪光（全局闪光：完成色/放大比例/动画时长；应用模块含尖刺）
        if bool(self.settings.get("flash_apply_spikes", True)):
            now_ms = int(time.time() * 1000)
            new_prev = {}
            any_stack_increased = False
            for buff in self.active_buffs:
                bkey = _bkey(buff)
                cur = int(buff.get("stacks", 0))
                prev = self._prev_buff_stacks.get(bkey, 0)
                if cur > prev:
                    self._spike_flash[bkey] = {"start": now_ms, "from": prev}
                    any_stack_increased = True
                new_prev[bkey] = cur
            self._prev_buff_stacks = new_prev
            # 任意层数增加时同时触发尖刺圆整体模块级闪光
            if any_stack_increased:
                self._spike_group_flash = {"start": now_ms}
            # 清理已结束的闪光记录
            dur = int(self.settings.get("flash_duration_ms", 400))
            expired = [k for k, v in self._spike_flash.items() if now_ms - v["start"] >= dur]
            for k in expired:
                del self._spike_flash[k]
        else:
            self._prev_buff_stacks = {
                _bkey(b): int(b.get("stacks", 0))
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
                g = _ab_hash_map.get(sk["ability_hash"])
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

    # 更新源镜像：国内优先走 releases 下载 CDN（与 GBFR Logs 显血插件同款，快），
    # 其次 jsDelivr（代理 main 分支，国内通常可达），最后才回退 raw（常被墙/限速）。
    UPDATE_MIRRORS = [
        "https://github.com/Dangoooooo613/GBFR_BuffTimerIndicator/releases/latest/download/version.json",
        "https://cdn.jsdelivr.net/gh/Dangoooooo613/GBFR_BuffTimerIndicator@main/version.json",
        "https://raw.githubusercontent.com/Dangoooooo613/GBFR_BuffTimerIndicator/main/version.json",
    ]

    def _do_check_update(self, url, manual, skip):
        info = {"has_update": False, "error": None, "checked_at": time.time()}
        last_err = None
        # 快速通道放最前：先试镜像（releases 下载 CDN / jsDelivr），最后才试用户自定义地址
        # （用户自定义若恰好是旧 raw 默认则已在镜像列表里，不会重复尝试）。
        candidates = list(self.UPDATE_MIRRORS)
        if url and url not in candidates:
            candidates.append(url)
        # 断梯子/网络波动时 8s 太短：改成递增超时 + 3 次重试
        timeouts = [15, 25, 35]
        for c_url in candidates:
            for attempt, timeout in enumerate(timeouts, start=1):
                try:
                    req = urllib.request.Request(c_url, headers={"User-Agent": "GBFR-Overlay-Updater"})
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    latest = str(data.get("version", "")).strip()
                    info["latest_version"] = latest
                    info["download_url"] = data.get("download_url", "")
                    info["changelog"] = data.get("changelog", "")
                    info["min_version"] = data.get("min_version", "")
                    if latest and self._version_gt(latest, APP_VERSION) and latest != skip:
                        info["has_update"] = True
                    self.update_info = info
                    self.update_checked.emit(info)
                    return
                except Exception as e:
                    last_err = e
                    if attempt < len(timeouts):
                        time.sleep(1.5)
            # 该镜像全部超时/失败，换下一个（不在此打印，避免刷屏）
        info["error"] = self._format_update_error(last_err)
        self.update_info = info
        self.update_checked.emit(info)

    def _format_update_error(self, e):
        """把原始异常转成用户看得懂的短句（同时用于翻译）。"""
        s = str(e)
        low = s.lower()
        if "timed out" in low or "timeout" in low:
            return "连接超时，请检查网络或开启梯子后重试"
        if "10061" in s or "actively refused" in low:
            return "更新服务器连接被拒绝，请检查网络或开启梯子"
        if "10060" in s or "10054" in s or "getaddrinfo" in low or "name or service not known" in low:
            return "网络连接异常，请检查网络或 DNS"
        return "更新检查失败: " + s

    def _on_update_checked(self, info):
        had_update = getattr(self, "_update_has_update", False)
        self._update_has_update = bool(info.get("has_update"))
        if self._update_has_update:
            try:
                lang = self.settings.get("language", "zh")
                if lang == "en":
                    tray_title = "New version available"
                    tray_msg = f"v{info.get('latest_version')} available. Click the title bar update button or go to Settings → About."
                elif lang == "zh_tw":
                    tray_title = "發現新版本"
                    tray_msg = f"v{info.get('latest_version')} 可用，請點擊標題列更新按鈕或到設定 → 關於 查看"
                else:
                    tray_title = "发现新版本"
                    tray_msg = f"v{info.get('latest_version')} 可用，请点击标题栏更新按钮或到设置 → 关于 查看"
                self.tray_icon.showMessage(tray_title, tray_msg, QSystemTrayIcon.Information, 8000)
            except Exception:
                pass
        # 标题栏按钮亮起/熄灭（有更新时开始呼吸光）
        if had_update != self._update_has_update and getattr(self, "core_win", None) is not None:
            self.core_win.update()
        dlg = getattr(self, "settings_dialog", None)
        if dlg is not None:
            try:
                dlg.refresh_update_ui(info)
            except Exception:
                pass

    def on_titlebar_update_clicked(self):
        """用户点击标题栏更新按钮：开始下载新版 exe。"""
        info = getattr(self, "update_info", None)
        if not info or not info.get("has_update"):
            return
        if getattr(self, "_update_downloading", False):
            return
        url = info.get("download_url", "")
        if not url:
            lang = self.settings.get("language", "zh")
            if lang == "en":
                QMessageBox.warning(self.core_win, "Update", "No download URL available.")
            elif lang == "zh_tw":
                QMessageBox.warning(self.core_win, "更新", "沒有可用的下載連結。")
            else:
                QMessageBox.warning(self.core_win, "更新", "没有可用的下载链接。")
            return
        self._update_downloading = True
        threading.Thread(target=self._do_download_update, args=(url,), daemon=True).start()

    def _do_download_update(self, url):
        """后台下载新版 exe 到当前程序同目录（保留 JSON 配置）。"""
        try:
            # 从下载链接解析文件名，例如 GBFR_CooldownIndicator_V262.exe
            from urllib.parse import urlparse, unquote
            name = os.path.basename(urlparse(url).path) or "GBFR_CooldownIndicator_new.exe"
            name = unquote(name)
            dest_tmp = os.path.join(EXE_DIR, name + ".tmp")
            dest = os.path.join(EXE_DIR, name)
            req = urllib.request.Request(url, headers={"User-Agent": "GBFR-Overlay-Updater"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(dest_tmp, "wb") as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self._update_progress_pct = int(downloaded * 100 / total)
            # 替换旧文件（如果同名已存在）
            if os.path.exists(dest):
                os.remove(dest)
            os.rename(dest_tmp, dest)
            self.update_downloaded.emit(dest)
        except Exception as e:
            self._update_downloading = False
            self.update_download_failed.emit(str(e))

    def _on_update_downloaded(self, dest):
        self._update_downloading = False
        self._ask_restart(dest)

    def _on_update_download_failed(self, msg):
        self._update_downloading = False
        lang = self.settings.get("language", "zh")
        if lang == "en":
            QMessageBox.warning(self.core_win, "Download Failed", f"Download failed:\n{msg}")
        elif lang == "zh_tw":
            QMessageBox.warning(self.core_win, "下載失敗", f"新版下載失敗：\n{msg}")
        else:
            QMessageBox.warning(self.core_win, "下载失败", f"新版下载失败：\n{msg}")

    def _ask_restart(self, dest):
        """下载完成后弹窗：关闭当前并打开新版 / 仅打开新版 / 稍后。"""
        lang = self.settings.get("language", "zh")
        if lang == "en":
            title = "Update downloaded"
            text = f"New version saved to:\n{dest}"
            btn_restart_text = "Close current & open new"
            btn_open_text = "Open new only"
            btn_later_text = "Later"
        elif lang == "zh_tw":
            title = "更新已下載"
            text = f"新版已儲存至：\n{dest}"
            btn_restart_text = "關閉當前並打開新版"
            btn_open_text = "僅打開新版"
            btn_later_text = "稍後"
        else:
            title = "更新已下载"
            text = f"新版已保存到：\n{dest}"
            btn_restart_text = "关闭当前并打开新版"
            btn_open_text = "仅打开新版"
            btn_later_text = "稍后"
        # 不以 core_win（Qt.Tool）为父，避免模态框在切游戏时级联隐藏核心窗口
        box = QMessageBox(None)
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        box.setWindowTitle(title)
        box.setText(text)
        info_text = {"zh": "是否立即运行新版？",
                      "zh_tw": "是否立即執行新版？",
                      "en": "Run the new version now?"}.get(lang, "Run the new version now?")
        box.setInformativeText(info_text)
        btn_restart = box.addButton(btn_restart_text, QMessageBox.YesRole)
        btn_open = box.addButton(btn_open_text, QMessageBox.NoRole)
        btn_later = box.addButton(btn_later_text, QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == btn_restart:
            subprocess.Popen([dest], cwd=EXE_DIR)
            QApplication.quit()
        elif box.clickedButton() == btn_open:
            subprocess.Popen([dest], cwd=EXE_DIR)

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
        except Exception as e:
            # 不再静默吞掉异常：首次出现的绘制错误记录到日志，方便定位缺失导入等问题。
            try:
                import traceback
                logged = getattr(self, "_logged_paint_errors", set())
                key = (type(e).__name__, str(e))
                if key not in logged:
                    logged.add(key)
                    self._logged_paint_errors = logged
                    logp = os.path.join(EXE_DIR, "paint_errors.log")
                    with open(logp, "a", encoding="utf-8") as f:
                        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] paintEvent error in {self.module_key}: {key}\n")
                        f.write(traceback.format_exc() + "\n")
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
        if self.ctrl._btn_update_rect_win.contains(raw):
            self.ctrl._pressed_core_btn = "update"; self.ctrl._pressed_visual = True; self.update(); return
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
        elif btn == "update":
            self.ctrl.on_titlebar_update_clicked()


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
    """双击启动时的读条窗口：紧凑简约，显示当前步骤与进度。"""

    def __init__(self, lang="zh"):
        super().__init__()
        self._lang = lang
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(280, 62)
        self.setStyleSheet(
            "QWidget{background:rgba(14,19,32,0.96);border-radius:8px;"
            "border:1px solid #283450;}"
            "QLabel{color:#c8d6f0;}"
            "QProgressBar{background:rgba(255,255,255,0.07);border:none;"
            "border-radius:3px;height:4px;}"
            "QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #4f8dff,stop:1 #7ee0a0);border-radius:3px;}"
        )
        self._build_ui()
        self._center()

    def _tr(self, text):
        m = {"zh": {}, "zh_tw": zh_to_tw, "en": zh_to_en}.get(self._lang, {})
        return m.get(text, text)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(0)
        self.title_lbl = QLabel(self._tr("启动中…"))
        self.title_lbl.setStyleSheet("font-size:12px;font-weight:bold;color:#e8eefc;")
        self.status_lbl = QLabel(self._tr("准备"))
        self.status_lbl.setStyleSheet("font-size:11px;color:#8aa2cc;")
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.title_lbl)
        top.addStretch()
        top.addWidget(self.status_lbl)
        layout.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

    def _center(self):
        geo = QApplication.primaryScreen().availableGeometry()
        r = self.geometry()
        self.move(geo.width() // 2 - r.width() // 2, geo.height() // 2 - r.height() // 2)

    def set_progress(self, pct=None, msg=None):
        if pct is not None:
            self.bar.setValue(int(pct))
        if msg:
            self.status_lbl.setText(self._tr(msg))
        QApplication.processEvents()

    def finish(self, msg=None):
        if msg is None:
            msg = self._tr("完成")
        self.bar.setValue(100)
        self.status_lbl.setText(self._tr(msg))
        self.status_lbl.setStyleSheet("font-size:12px;color:#7ee0a0;font-weight:bold;")
        QApplication.processEvents()
        QTimer.singleShot(600, self.close)


def main():
    app = QApplication(sys.argv)
    if os.path.isfile(APP_ICON_PATH):
        app.setWindowIcon(QIcon(APP_ICON_PATH))
    app.setQuitOnLastWindowClosed(False)
    settings = load_settings()
    splash = None
    if settings.get("splash_enabled", True):
        splash = StartupSplash(settings.get("language", "zh"))
        splash.show()
        splash.set_progress(4, "正在加载设置…")
    overlay = GBFROverlayQt(progress_cb=splash.set_progress if splash else None)
    if splash is not None:
        splash.finish()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

