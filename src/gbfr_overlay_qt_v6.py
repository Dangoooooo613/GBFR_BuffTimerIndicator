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
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QRadialGradient, QIcon, QPainter, QPen, QPainterPath, QPixmap
from PySide6.QtWidgets import (
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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSlider,
    QScrollArea,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


# ============================ Paths ============================
EXE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(EXE_DIR, "overlay_settings.json")
PTR_CACHE_FILE = os.path.join(EXE_DIR, "ptr_cache.txt")
if getattr(sys, "frozen", False):
    _BUNDLE_DIR = sys._MEIPASS
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SHRIMP_IMG_PATH = os.path.join(_BUNDLE_DIR, "embedded_roll_icon.png")
APP_ICON_PATH = os.path.join(_BUNDLE_DIR, "app_icon.ico")

# ============================ Version ============================
APP_VERSION = "1.01"
SETTINGS_SCHEMA_VERSION = 37
APP_TITLE = "GBFR_CooldownIndicator_V101"
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

# 语言 → CHAR_TYPE_NAMES 元组索引
LANG_NAME_IDX = {"zh": 0, "zh_tw": 1, "en": 2}

def _char_name(char_type, lang="zh"):
    """按语言获取角色名。"""
    pair = CHAR_TYPE_NAMES.get(char_type)
    if not pair:
        return f"0x{char_type:02X}"
    return pair[LANG_NAME_IDX.get(lang, 0)]

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
    path = ""
    for c in [CHAR_DB_PATH, CHAR_DB_FALLBACK]:
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
# 每个 buff 条目: zh(简中), zh_tw(繁中), en(英文), stack_status_id, timer_status_id, timer_display
# timer_display: "full_stack_only" = 仅满层显示倒计时; "any_stack" = 任意层数显示倒计时
BUFF_PROFILES = {
    0x11: {  # 齐格飞
        "buffs": [
            {"zh": "屠龙之心", "zh_tw": "滅龍的鼓動", "en": "Dragonsbane Pulse",
             "stack_status_id": 0x40, "timer_status_id": 0x40,
             "timer_display": "full_stack_only"},
        ]
    },
    0x24: {  # 伽兰查
        "buffs": [
            {"zh": "武夫", "zh_tw": "荒事", "en": "Wild Showman",
             "stack_status_id": 0x72, "timer_status_id": 0x72,
             "timer_display": "any_stack"},
        ]
    },
    0x07: {  # 菲莉
        "buffs": [
            {"zh": "托愿", "zh_tw": "被託付的願望", "en": "Loving Trust",
             "stack_status_id": 0x4E, "timer_status_id": 0x4E,
             "timer_display": "any_stack"},
        ]
    },
    0x08: {  # 兰斯洛特
        "buffs": [
            {"zh": "连击", "zh_tw": "連擊", "en": "Avalanche",
             "stack_status_id": 0x69, "timer_status_id": 0x69,
             "timer_display": "any_stack"},
        ]
    },
    0x19: {  # 伊德
        "buffs": [
            {"zh": "紫银之力", "zh_tw": "紫銀之力", "en": "Heliotrope Aura",
             "stack_status_id": 0x3C, "timer_status_id": 0x3C,
             "timer_display": "any_stack"},
        ]
    },
    0x23: {  # 索恩
        "buffs": [
            {"zh": "致命一击强化", "zh_tw": "致命一擊強化", "en": "Enhanced Clincher",
             "stack_status_id": 0x7F, "timer_status_id": 0x7F,
             "timer_display": "any_stack"},
        ]
    },
    0x17: {  # 巴萨拉卡
        "buffs": [
            {"zh": "冥刃", "zh_tw": "冥刃", "en": "Ebony Glint",
             "stack_status_id": 0x52, "timer_status_id": 0x52,
             "timer_display": "any_stack"},
        ]
    },
    0x16: {  # 塞达
        "buffs": [
            {"zh": "跃空强化", "zh_tw": "浮空強化", "en": "Loop Master",
             "stack_status_id": 0x5E, "timer_status_id": 0x5E,
             "timer_display": "any_stack"},
        ]
    },
    0x18: {  # 卡莉奥丝特罗
        "buffs": [
            {"zh": "岩塌强化", "zh_tw": "大崩壞強化", "en": "Super Collapse",
             "stack_status_id": 0x56, "timer_status_id": 0x56,
             "timer_display": "any_stack"},
        ]
    },
    0x10: {  # 珀西瓦尔
        "buffs": [
            {"zh": "红莲之刃", "zh_tw": "紅蓮之刃", "en": "Molten Edge",
             "stack_status_id": 0x55, "timer_status_id": 0x55,
             "timer_display": "any_stack"},
        ]
    },
    0x20: {  # 伊德(龙人化) — 与普通形态共用 buff
        "buffs": [
            {"zh": "紫银之力", "zh_tw": "紫銀之力", "en": "Heliotrope Aura",
             "stack_status_id": 0x3C, "timer_status_id": 0x3C,
             "timer_display": "any_stack"},
        ]
    },
    0x22: {  # 希耶提 — 多buff差异化
        "buffs": [
            {"zh": "剑王", "zh_tw": "劍王", "en": "Sovereign",
             "stack_status_id": 0x74, "timer_status_id": 0x74,
             "timer_display": "any_stack"},
            {"zh": "星海", "zh_tw": "星海", "en": "Star Sea",
             "stack_status_id": 0x75, "timer_status_id": 0x75,
             "timer_display": "any_stack"},
        ]
    },
}

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
ABILITY_HASH_OFFSET = 0x1AA24
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


def resolve_player_ptr(handle, base, size):
    pattern, mask = parse_aob(AOB_HEX)
    hit = aob_scan(handle, base, size, pattern, mask)
    if hit is None:
        return None
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


def resolve_with_cache(handle, pid):
    minfo = get_module_info(pid)
    if minfo is None:
        return None, None, None
    base, size = minfo
    cached = load_ptr_cache()
    if cached:
        c_pid, c_base, c_size, c_pptr = cached
        if c_pid == pid and c_base == base and c_size == size:
            cb = read_u64(handle, c_pptr + CHAR_PTR_OFF)
            if cb:
                return c_pptr, base, size
    pptr = resolve_player_ptr(handle, base, size)
    if pptr is None:
        return None, None, None
    save_ptr_cache(pid, base, size, pptr)
    return pptr, base, size


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


def read_overlay_data(handle, pptr):
    """读取角色层数、翻滚次数和全部角色专属 buff。

    通过 ExStatus 指针数组读取 buff 数据。
    返回 {status, dodge, char_type, buffs: [...]}.
    buffs 列表每个条目: {index, zh, en, stacks, max_stacks, timer, timer_max, timer_display}.
    """
    char_base = read_u64(handle, pptr + CHAR_PTR_OFF)
    if not char_base:
        return {"status": "no_char", "dodge": None, "char_type": 0, "buffs": []}
    dodge = read_u32(handle, char_base + FIELD_DODGE)
    char_type = read_u8(handle, char_base + FIELD_CHAR_TYPE) or 0

    all_buffs = read_exstatus_buffs(handle, char_base)
    profile = BUFF_PROFILES.get(char_type)
    buffs_out = []

    if profile:
        for idx, buff_cfg in enumerate(profile["buffs"]):
            stack_sid = buff_cfg.get("stack_status_id")
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

            buffs_out.append({
                "index": idx,
                "zh": buff_cfg["zh"],
                "zh_tw": buff_cfg.get("zh_tw", buff_cfg["zh"]),
                "en": buff_cfg["en"],
                "stacks": stacks,
                "max_stacks": max_stacks,
                "timer": timer,
                "timer_max": timer_max,
                "timer_display": buff_cfg.get("timer_display", "any_stack"),
            })

    return {"status": "ok", "dodge": dodge or 0, "char_type": char_type, "buffs": buffs_out}

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
    ("skill_cd_color", "技能扇形色:"),
    ("skill_cd_ready_color", "技能完成色:"),
    ("skill_cd_text_color", "技能倒计时色:"),
    ("skill_cd_name_color", "技能名色:"),
]

# 锁定时需要减半不透明度的颜色键（仅标题栏、背景、图标；层数UI和翻滚UI不受影响）
LOCK_HALVED_KEYS = {"title_bar_color", "bg_color", "icon_color"}

# 非战斗状态下需要调整不透明度的颜色键分组
NON_COMBAT_SPIKE_KEYS = {
    "circle_color_normal", "circle_color_lv7",
    "spike_color_normal", "spike_color_lv7",
    "arc_color", "text_color", "dh_text_outline_color",
    "text_color_timer", "dh_text_outline_color_timer",
    "timer_text_color", "indicator_outline_color",
}
NON_COMBAT_SKILL_CD_KEYS = {
    "skill_cd_color", "skill_cd_text_color", "skill_cd_name_color",
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
    "ui_scale_percent": 90,
    "window_x": 424,
    "window_y": 696,
    "window_x_ratio": 0.165625,
    "window_y_ratio": 0.5,
    "circle_pad_title": 0,
    "shrimp_gap_circle": 20,
    "show_roll_divider": False,
    "roll_divider_opacity": 3,
    "ex_status_offset": ACTOR_EX_STATUS,
    "center_text_offset_x": 0,
    "center_text_offset_y": -2,
    "dh_text_outline_width": 3,
    # 有计时版层数数字（独立参数）
    "dh_font_size_timer": 30,
    "center_text_offset_x_timer": 1,
    "center_text_offset_y_timer": 4,
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
    "lv7_timer_y_offset": -6,
    "lv7_timer_badge_width": 9,
    "siegfried_only": True,
    "non_combat_spike_opacity": 30,
    "non_combat_roll_opacity": 30,
    "non_combat_skill_cd_opacity": 30,
    "show_titlebar_status": True,
    "buff_enabled": {
        "0x11_0": True,
        "0x24_0": True,
        "0x07_0": True,
        "0x08_0": True,
        "0x19_0": True,
        "0x23_0": True,
        "0x17_0": True,
        "0x16_0": True,
        "0x18_0": True,
        "0x10_0": True,
        "0x20_0": True,
        "0x22_0": True,
        "0x22_1": True,
    },
    "multi_buff_offset": 123,
    "multi_buff_scale": 80,
    "multi_buff_angle": 43,
    "multi_buff_external_color": True,
    "multi_buff_internal_color": True,
    "show_buff_name": False,
    "buff_name_font_size": 8,
    "buff_name_offset_x": 0,
    "buff_name_offset_y": 4,
    "buff_name_bg_width": -4,
    "buff_name_color": "#ff0000",
    "buff_name_color_opacity": 80,
    # ── 技能冷却 (Cooldown Indicator) ──
    "show_skill_cd": True,
    "skill_cd_size": 28,
    "skill_cd_spread": 55,
    "skill_cd_offset_x": 0,
    "skill_cd_offset_y": 0,
    "skill_cd_color": "#55aaff",
    "skill_cd_color_opacity": 70,
    "skill_cd_ready_color": "#ffffff",
    "skill_cd_ready_scale": 140,
    "skill_cd_ready_duration_ms": 400,
    "skill_cd_capsule_bg": "#0a0e1a",
    "skill_cd_capsule_border": "#55aaff",
    "skill_cd_text_color": "#ffffff",
    "skill_cd_text_color_opacity": 100,
    "skill_cd_show_name": True,
    "skill_cd_name_font_size": 7,
    "skill_cd_name_offset_y": 0,
    "skill_cd_name_bg_width": 0,
    "skill_cd_name_color": "#aaccff",
    "skill_cd_name_color_opacity": 80,
    "skill_cooldown_max": {},
}


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
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


# ============================ Settings Dialog ============================
class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Overlay 设置")
        self.setMinimumWidth(1120)
        self.setMaximumHeight(700)
        self.resize(1120, 700)
        self.settings = dict(settings)
        self.color_buttons = {}
        self.opacity_spins = {}
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
        self.settings_tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid #2a3548;border-radius:6px;}"
            "QTabBar::tab{background:#20283a;color:#aab6d0;padding:7px 14px;border:1px solid #2a3548;border-bottom:none;}"
            "QTabBar::tab:selected{background:#2a3450;color:#ffffff;}"
            "QTabBar::tab:hover{background:#303b55;}"
        )

        def make_tab(title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea>QWidget>QWidget{background:transparent;}")
            inner_widget = QWidget()
            inner_widget.setStyleSheet("background:transparent;")
            tab_form = QFormLayout(inner_widget)
            tab_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            tab_form.setHorizontalSpacing(10)
            tab_form.setVerticalSpacing(8)
            scroll.setWidget(inner_widget)
            self.settings_tabs.addTab(scroll, title)
            return tab_form

        def make_card(parent_form, title=None):
            """创建带圆角矩形背景的卡片区域，返回 (card_widget, card_form)。"""
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

        form_global = make_tab("全局")
        form_bg = make_tab("背景与标题")
        form_buff_outer = make_tab("Buff外层")
        form_stack = make_tab("层数数字")
        form_timer_shape = make_tab("倒计时")
        form_buff_name = make_tab("Buff名字")
        form_multi = make_tab("多buff差异化")
        form_roll = make_tab("翻滚")
        form_skill_cd = make_tab("技能冷却")
        form_buff_cfg = make_tab("Buff启用/禁用")
        form = form_global
        layout.addWidget(self.settings_tabs)

        # ── 常规 ──
        card, cf = make_card(form, "── 常规 ──")

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

        self.siegfried_only = QCheckBox("非战斗状态/未接入角色时调整透明度")
        self.siegfried_only.setChecked(bool(self.settings.get("siegfried_only", DEFAULT_SETTINGS["siegfried_only"])))
        cf.addRow("非战斗透明度:", self.siegfried_only)
        self.non_combat_spike_op_spn = QSpinBox()
        self.non_combat_spike_op_spn.setRange(0, 100)
        self.non_combat_spike_op_spn.setSuffix("%")
        self.non_combat_spike_op_spn.setValue(int(self.settings.get("non_combat_spike_opacity", 30)))
        cf.addRow("尖刺UI不透明度:", self.non_combat_spike_op_spn)
        self.non_combat_roll_op_spn = QSpinBox()
        self.non_combat_roll_op_spn.setRange(0, 100)
        self.non_combat_roll_op_spn.setSuffix("%")
        self.non_combat_roll_op_spn.setValue(int(self.settings.get("non_combat_roll_opacity", 30)))
        cf.addRow("翻滚UI不透明度:", self.non_combat_roll_op_spn)
        self.non_combat_skill_cd_op_spn = QSpinBox()
        self.non_combat_skill_cd_op_spn.setRange(0, 100)
        self.non_combat_skill_cd_op_spn.setSuffix("%")
        self.non_combat_skill_cd_op_spn.setValue(int(self.settings.get("non_combat_skill_cd_opacity", 30)))
        cf.addRow("技能CD不透明度:", self.non_combat_skill_cd_op_spn)
        form.addRow(card)

        form = form_bg
        card, cf = make_card(form, "── 背景 ──")
        self._add_color_row(cf, "bg_color", "背景色:")
        form.addRow(card)

        card, cf = make_card(form, "── 标题栏 ──")
        self.show_titlebar_status = QCheckBox("在标题栏显示角色名和buff状态文字")
        self.show_titlebar_status.setChecked(bool(self.settings.get("show_titlebar_status", DEFAULT_SETTINGS["show_titlebar_status"])))
        cf.addRow("标题栏状态文字:", self.show_titlebar_status)
        self._add_color_row(cf, "title_bar_color", "标题栏色:")
        self._add_color_row(cf, "icon_color", "标题UI色:")
        form.addRow(card)

        # ── 技能冷却 ──
        form = form_skill_cd
        card, cf = make_card(form, "── 技能冷却 ──")
        self.skill_cd_show_chk = QCheckBox("显示技能冷却")
        self.skill_cd_show_chk.setChecked(bool(self.settings.get("show_skill_cd", True)))
        cf.addRow(self.skill_cd_show_chk)
        self.skill_cd_size_spn = QSpinBox()
        self.skill_cd_size_spn.setRange(10, 80)
        self.skill_cd_size_spn.setValue(int(self.settings.get("skill_cd_size", 28)))
        cf.addRow("方形大小:", self.skill_cd_size_spn)
        self.skill_cd_spread_spn = QSpinBox()
        self.skill_cd_spread_spn.setRange(20, 200)
        self.skill_cd_spread_spn.setValue(int(self.settings.get("skill_cd_spread", 55)))
        cf.addRow("聚散距离:", self.skill_cd_spread_spn)
        self.skill_cd_offx_spn = QSpinBox()
        self.skill_cd_offx_spn.setRange(-300, 300)
        self.skill_cd_offx_spn.setValue(int(self.settings.get("skill_cd_offset_x", 0)))
        cf.addRow("位置偏移X:", self.skill_cd_offx_spn)
        self.skill_cd_offy_spn = QSpinBox()
        self.skill_cd_offy_spn.setRange(-300, 300)
        self.skill_cd_offy_spn.setValue(int(self.settings.get("skill_cd_offset_y", 0)))
        cf.addRow("位置偏移Y:", self.skill_cd_offy_spn)
        self._add_color_row(cf, "skill_cd_color", "扇形颜色:", with_opacity=True)
        self._add_color_row(cf, "skill_cd_text_color", "倒计时文字色:", with_opacity=True)
        form.addRow(card)
        # 完成动画
        card, cf = make_card(form, "── 冷却完成动画 ──")
        self._add_color_row(cf, "skill_cd_ready_color", "完成色:")
        self.skill_cd_ready_scale_spn = QSpinBox()
        self.skill_cd_ready_scale_spn.setRange(100, 300)
        self.skill_cd_ready_scale_spn.setValue(int(self.settings.get("skill_cd_ready_scale", 140)))
        cf.addRow("放大比例%:", self.skill_cd_ready_scale_spn)
        self.skill_cd_ready_dur_spn = QSpinBox()
        self.skill_cd_ready_dur_spn.setRange(100, 2000)
        self.skill_cd_ready_dur_spn.setSingleStep(50)
        self.skill_cd_ready_dur_spn.setValue(int(self.settings.get("skill_cd_ready_duration_ms", 400)))
        cf.addRow("动画时长ms:", self.skill_cd_ready_dur_spn)
        form.addRow(card)
        # 技能名称
        card, cf = make_card(form, "── 技能名称 ──")
        self.skill_cd_name_chk = QCheckBox("显示技能名称")
        self.skill_cd_name_chk.setChecked(bool(self.settings.get("skill_cd_show_name", True)))
        cf.addRow(self.skill_cd_name_chk)
        self.skill_cd_name_font_spn = QSpinBox()
        self.skill_cd_name_font_spn.setRange(1, 48)
        self.skill_cd_name_font_spn.setValue(int(self.settings.get("skill_cd_name_font_size", 7)))
        cf.addRow("字号:", self.skill_cd_name_font_spn)
        self.skill_cd_name_offy_spn = QSpinBox()
        self.skill_cd_name_offy_spn.setRange(-200, 200)
        self.skill_cd_name_offy_spn.setValue(int(self.settings.get("skill_cd_name_offset_y", 0)))
        cf.addRow("Y偏移:", self.skill_cd_name_offy_spn)
        self.skill_cd_name_bgw_spn = QSpinBox()
        self.skill_cd_name_bgw_spn.setRange(-100, 100)
        self.skill_cd_name_bgw_spn.setValue(int(self.settings.get("skill_cd_name_bg_width", 0)))
        cf.addRow("衬色块宽微调:", self.skill_cd_name_bgw_spn)
        self._add_color_row(cf, "skill_cd_name_color", "技能名色:", with_opacity=True)
        form.addRow(card)

        form = form_global
        # ── Buff 启用/禁用（直接放在标签页中）──
        form = form_buff_cfg
        card, cf = make_card(form)

        # 全选 / 全不选按钮
        buff_btn_row = QHBoxLayout()
        buff_btn_row.setContentsMargins(0, 0, 0, 0)
        buff_btn_row.setSpacing(8)
        self.buff_btn_all = QPushButton("全选")
        self.buff_btn_none = QPushButton("全不选")
        self.buff_btn_all.setAutoDefault(False)
        self.buff_btn_none.setAutoDefault(False)
        buff_btn_row.addWidget(self.buff_btn_all)
        buff_btn_row.addWidget(self.buff_btn_none)
        buff_btn_row.addStretch()
        buff_btn_container = QWidget()
        buff_btn_container.setLayout(buff_btn_row)
        cf.addRow(buff_btn_container)

        # 直接在标签页中创建所有 buff 复选框
        self.buff_checkboxes = {}
        buff_enabled = self.settings.get("buff_enabled", {})
        for char_type, profile in BUFF_PROFILES.items():
            char_name = _char_name(char_type, "zh")
            for idx, buff_cfg in enumerate(profile["buffs"]):
                key = f"{char_type:#04x}_{idx}"
                buff_name = buff_cfg["zh"]
                cb = QCheckBox(f"{char_name} - {buff_name}")
                is_enabled = buff_enabled.get(key, True)
                cb.setChecked(is_enabled)
                cf.addRow("", cb)
                self.buff_checkboxes[key] = cb

        self.buff_btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self.buff_checkboxes.values()])
        self.buff_btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb in self.buff_checkboxes.values()])
        form.addRow(card)

        form = form_global
        pos_row = QHBoxLayout()
        pos_row.setContentsMargins(0, 0, 0, 0)
        pos_row.setSpacing(8)
        self.window_x = QSpinBox()
        self.window_x.setRange(-99999, 99999)
        self.window_x.setPrefix("X ")
        self.window_y = QSpinBox()
        self.window_y.setRange(-99999, 99999)
        self.window_y.setPrefix("Y ")
        self.window_x.setValue(int(self.settings.get("window_x") if self.settings.get("window_x") is not None else parent.x()))
        self.window_y.setValue(int(self.settings.get("window_y") if self.settings.get("window_y") is not None else parent.y()))
        pos_row.addWidget(self.window_x)
        pos_row.addWidget(self.window_y)
        pos_container = QWidget()
        pos_container.setLayout(pos_row)
        form.addRow("启动位置:", pos_container)

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(8)
        self.ui_scale_slider = QSlider(Qt.Horizontal)
        self.ui_scale_slider.setRange(30, 250)
        self.ui_scale_spin = QSpinBox()
        self.ui_scale_spin.setRange(30, 250)
        self.ui_scale_spin.setSuffix("%")
        self.ui_scale_spin.setFixedWidth(86)
        scale_value = int(self.settings.get("ui_scale_percent", DEFAULT_SETTINGS["ui_scale_percent"]))
        self.ui_scale_slider.setValue(scale_value)
        self.ui_scale_spin.setValue(scale_value)
        self.ui_scale_slider.valueChanged.connect(self.ui_scale_spin.setValue)
        self.ui_scale_spin.valueChanged.connect(self.ui_scale_slider.setValue)
        scale_row.addWidget(self.ui_scale_slider)
        scale_row.addWidget(self.ui_scale_spin)
        scale_container = QWidget()
        scale_container.setLayout(scale_row)
        form.addRow("整体等比缩放:", scale_container)

        self.scan = QSpinBox()
        self.scan.setRange(10, 500)
        self.scan.setValue(int(self.settings.get("scan_ms", DEFAULT_SETTINGS["scan_ms"])))
        form.addRow("扫描周期 (ms):", self.scan)

        card, cf = make_card(form, "── 布局间距 ──")

        self.circle_pad_title = QSpinBox()
        self.circle_pad_title.setRange(0, 999)
        self.circle_pad_title.setValue(int(self.settings.get("circle_pad_title", DEFAULT_SETTINGS["circle_pad_title"])))
        cf.addRow("标题→圆间距:", self.circle_pad_title)

        self.shrimp_gap_circle = QSpinBox()
        self.shrimp_gap_circle.setRange(0, 999)
        self.shrimp_gap_circle.setValue(int(self.settings.get("shrimp_gap_circle", DEFAULT_SETTINGS["shrimp_gap_circle"])))
        cf.addRow("圆→翻滚UI间距:", self.shrimp_gap_circle)

        self.show_roll_divider = QCheckBox("显示层数/翻滚分割线")
        self.show_roll_divider.setChecked(bool(self.settings.get("show_roll_divider", DEFAULT_SETTINGS["show_roll_divider"])))
        cf.addRow("分割线:", self.show_roll_divider)

        self.roll_divider_opacity = QSpinBox()
        self.roll_divider_opacity.setRange(0, 100)
        self.roll_divider_opacity.setSuffix("%")
        self.roll_divider_opacity.setValue(int(self.settings.get("roll_divider_opacity", DEFAULT_SETTINGS["roll_divider_opacity"])))
        cf.addRow("分割线不透明度:", self.roll_divider_opacity)
        form.addRow(card)

        card, cf = make_card(form, "── 内存 ──")

        self.ex_status_offset_spin = QSpinBox()
        self.ex_status_offset_spin.setRange(0, 0xFFFF)
        self.ex_status_offset_spin.setPrefix("0x")
        self.ex_status_offset_spin.setDisplayIntegerBase(16)
        self.ex_status_offset_spin.setValue(int(self.settings.get("ex_status_offset", ACTOR_EX_STATUS)))
        cf.addRow("ExStatus偏移:", self.ex_status_offset_spin)
        form.addRow(card)

        form = form_buff_name
        # ── Buff名显示 + 字体大小 + 位置偏移 + 衬色块 ──
        self.show_buff_name_cb = QCheckBox("在画布上显示Buff名称")
        self.show_buff_name_cb.setChecked(bool(self.settings.get("show_buff_name", DEFAULT_SETTINGS["show_buff_name"])))
        form.addRow("Buff名显示:", self.show_buff_name_cb)

        self.buff_name_font_size = QSpinBox()
        self.buff_name_font_size.setRange(1, 48)
        self.buff_name_font_size.setSuffix(" px")
        self.buff_name_font_size.setValue(int(self.settings.get("buff_name_font_size", DEFAULT_SETTINGS["buff_name_font_size"])))
        form.addRow("Buff名字体大小:", self.buff_name_font_size)

        name_pos_row = QHBoxLayout()
        name_pos_row.setContentsMargins(0, 0, 0, 0)
        name_pos_row.setSpacing(8)
        self.buff_name_offset_x = QSpinBox()
        self.buff_name_offset_x.setRange(-200, 200)
        self.buff_name_offset_x.setPrefix("X ")
        self.buff_name_offset_x.setValue(int(self.settings.get("buff_name_offset_x", DEFAULT_SETTINGS["buff_name_offset_x"])))
        self.buff_name_offset_y = QSpinBox()
        self.buff_name_offset_y.setRange(-200, 200)
        self.buff_name_offset_y.setPrefix("Y ")
        self.buff_name_offset_y.setValue(int(self.settings.get("buff_name_offset_y", DEFAULT_SETTINGS["buff_name_offset_y"])))
        name_pos_row.addWidget(self.buff_name_offset_x)
        name_pos_row.addWidget(self.buff_name_offset_y)
        name_pos_container = QWidget()
        name_pos_container.setLayout(name_pos_row)
        form.addRow("Buff名位置:", name_pos_container)

        self.buff_name_bg_width = QSpinBox()
        self.buff_name_bg_width.setRange(-100, 100)
        self.buff_name_bg_width.setSuffix(" px")
        self.buff_name_bg_width.setValue(int(self.settings.get("buff_name_bg_width", DEFAULT_SETTINGS["buff_name_bg_width"])))
        form.addRow("Buff名衬色块宽度微调:", self.buff_name_bg_width)

        form = form_multi
        card, cf = make_card(form)

        # 缩放
        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(4)
        self.multi_buff_scale_slider = QSlider(Qt.Horizontal)
        self.multi_buff_scale_slider.setRange(20, 100)
        self.multi_buff_scale_spin = QSpinBox()
        self.multi_buff_scale_spin.setRange(20, 100)
        self.multi_buff_scale_spin.setSuffix("%")
        scale_val = int(self.settings.get("multi_buff_scale", 60))
        self.multi_buff_scale_slider.setValue(scale_val)
        self.multi_buff_scale_spin.setValue(scale_val)
        self.multi_buff_scale_slider.valueChanged.connect(self.multi_buff_scale_spin.setValue)
        self.multi_buff_scale_spin.valueChanged.connect(self.multi_buff_scale_slider.setValue)
        scale_row.addWidget(self.multi_buff_scale_slider)
        scale_row.addWidget(self.multi_buff_scale_spin)
        scale_container = QWidget()
        scale_container.setLayout(scale_row)
        cf.addRow("多buff缩放:", scale_container)

        # 偏移
        offset_row = QHBoxLayout()
        offset_row.setContentsMargins(0, 0, 0, 0)
        offset_row.setSpacing(4)
        self.multi_buff_offset_slider = QSlider(Qt.Horizontal)
        self.multi_buff_offset_slider.setRange(0, 150)
        self.multi_buff_offset_spin = QSpinBox()
        self.multi_buff_offset_spin.setRange(0, 150)
        self.multi_buff_offset_spin.setSuffix("%")
        offset_val = int(self.settings.get("multi_buff_offset", 70))
        self.multi_buff_offset_slider.setValue(offset_val)
        self.multi_buff_offset_spin.setValue(offset_val)
        self.multi_buff_offset_slider.valueChanged.connect(self.multi_buff_offset_spin.setValue)
        self.multi_buff_offset_spin.valueChanged.connect(self.multi_buff_offset_slider.setValue)
        offset_row.addWidget(self.multi_buff_offset_slider)
        offset_row.addWidget(self.multi_buff_offset_spin)
        offset_container = QWidget()
        offset_container.setLayout(offset_row)
        cf.addRow("多buff偏移量:", offset_container)

        # 夹角
        angle_row = QHBoxLayout()
        angle_row.setContentsMargins(0, 0, 0, 0)
        angle_row.setSpacing(4)
        self.multi_buff_angle_slider = QSlider(Qt.Horizontal)
        self.multi_buff_angle_slider.setRange(0, 360)
        self.multi_buff_angle_spin = QSpinBox()
        self.multi_buff_angle_spin.setRange(0, 360)
        self.multi_buff_angle_spin.setSuffix("°")
        angle_val = int(self.settings.get("multi_buff_angle", 45))
        self.multi_buff_angle_slider.setValue(angle_val)
        self.multi_buff_angle_spin.setValue(angle_val)
        self.multi_buff_angle_slider.valueChanged.connect(self.multi_buff_angle_spin.setValue)
        self.multi_buff_angle_spin.valueChanged.connect(self.multi_buff_angle_slider.setValue)
        angle_row.addWidget(self.multi_buff_angle_slider)
        angle_row.addWidget(self.multi_buff_angle_spin)
        angle_container = QWidget()
        angle_container.setLayout(angle_row)
        cf.addRow("多buff夹角:", angle_container)

        # 差异化颜色选项
        self.multi_buff_external_color_cb = QCheckBox("外部差异化颜色（圆环/尖刺/外描边）")
        self.multi_buff_external_color_cb.setChecked(bool(self.settings.get("multi_buff_external_color", True)))
        cf.addRow("外部差异化:", self.multi_buff_external_color_cb)

        self.multi_buff_internal_color_cb = QCheckBox("内部差异化颜色（弧线/数字/计时文字）")
        self.multi_buff_internal_color_cb.setChecked(bool(self.settings.get("multi_buff_internal_color", True)))
        cf.addRow("内部差异化:", self.multi_buff_internal_color_cb)
        form.addRow(card)

        # ── Buff外层 ──
        form = form_buff_outer

        # 尖刺组(含顶端圆点)
        card, cf = make_card(form, "── 尖刺(含顶端圆点) ──")

        self.spike_length = QSpinBox()
        self.spike_length.setRange(8, 80)
        self.spike_length.setValue(int(self.settings.get("spike_length", DEFAULT_SETTINGS["spike_length"])))
        cf.addRow("尖刺长度:", self.spike_length)

        self.spike_axis_pos = QSpinBox()
        self.spike_axis_pos.setRange(-60, 80)
        self.spike_axis_pos.setSuffix("%")
        self.spike_axis_pos.setValue(int(self.settings.get("spike_axis_pos_percent", DEFAULT_SETTINGS["spike_axis_pos_percent"])))
        cf.addRow("尖刺根部距圆心:", self.spike_axis_pos)

        self.spike_width = QSpinBox()
        self.spike_width.setRange(8, 100)
        self.spike_width.setSuffix("px")
        self.spike_width.setValue(int(self.settings.get("spike_width", DEFAULT_SETTINGS["spike_width"])))
        cf.addRow("尖刺宽度:", self.spike_width)

        self.spike_waist_pos = QSpinBox()
        self.spike_waist_pos.setRange(5, 95)
        self.spike_waist_pos.setSuffix("%")
        self.spike_waist_pos.setValue(int(self.settings.get("spike_waist_pos_percent", DEFAULT_SETTINGS["spike_waist_pos_percent"])))
        cf.addRow("尖刺腰位置:", self.spike_waist_pos)

        self.spike_bead_radius = QSpinBox()
        self.spike_bead_radius.setRange(0, 30)
        self.spike_bead_radius.setSuffix("px")
        self.spike_bead_radius.setValue(int(self.settings.get("spike_bead_radius", DEFAULT_SETTINGS["spike_bead_radius"])))
        cf.addRow("尖刺顶端圆点半径:", self.spike_bead_radius)

        self.spike_bead_pos = QSpinBox()
        self.spike_bead_pos.setRange(-60, 80)
        self.spike_bead_pos.setSuffix("%")
        self.spike_bead_pos.setValue(int(self.settings.get("spike_bead_pos_percent", DEFAULT_SETTINGS["spike_bead_pos_percent"])))
        cf.addRow("顶端圆点距圆心:", self.spike_bead_pos)
        self._add_color_row(cf, "spike_color_normal", "尖刺色(正常):")
        self._add_color_row(cf, "spike_color_lv7", "尖刺色(满层):")
        form.addRow(card)

        # 圆环组
        card, cf = make_card(form, "── 圆环 ──")

        self.circle_radius = QSpinBox()
        self.circle_radius.setRange(30, 120)
        self.circle_radius.setValue(int(self.settings.get("circle_radius", DEFAULT_SETTINGS["circle_radius"])))
        cf.addRow("圆半径:", self.circle_radius)
        self._add_color_row(cf, "circle_color_normal", "圆环色(正常):")
        self._add_color_row(cf, "circle_color_lv7", "圆环色(满层):")
        form.addRow(card)

        # 外描边组
        card, cf = make_card(form, "── 外描边 ──")

        self.indicator_outline_enabled = QCheckBox("启用整体外描边")
        self.indicator_outline_enabled.setChecked(bool(self.settings.get("use_indicator_outline", DEFAULT_SETTINGS["use_indicator_outline"])))
        cf.addRow("整体外描边:", self.indicator_outline_enabled)

        self.indicator_outline_width = QSpinBox()
        self.indicator_outline_width.setRange(0, 20)
        self.indicator_outline_width.setSuffix("px")
        self.indicator_outline_width.setValue(int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])))
        cf.addRow("外描边粗细:", self.indicator_outline_width)
        self._add_color_row(cf, "indicator_outline_color", "外描边色:")
        form.addRow(card)

        form = form_roll
        card, cf = make_card(form, "── 翻滚图标 ──")

        self.icon_use_default = QCheckBox("使用内置默认图标")
        self.icon_use_default.setChecked(bool(self.settings.get("use_default_dodge_icon", DEFAULT_SETTINGS["use_default_dodge_icon"])))
        cf.addRow("默认图标:", self.icon_use_default)

        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(8)
        self.icon_path = QLineEdit(self.settings.get("shrimp_img_path", DEFAULT_SETTINGS["shrimp_img_path"]))
        self.browse_icon_btn = QPushButton("浏览...")
        self.browse_icon_btn.setAutoDefault(False)
        self.browse_icon_btn.setDefault(False)
        self.browse_icon_btn.setFixedWidth(80)
        self.browse_icon_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_path)
        icon_row.addWidget(self.browse_icon_btn)
        icon_container = QWidget()
        icon_container.setLayout(icon_row)
        cf.addRow("翻滚图标绝对路径:", icon_container)
        self._sync_icon_default_enabled()

        self.icon_scale = QSpinBox()
        self.icon_scale.setRange(10, 400)
        self.icon_scale.setSuffix("%")
        self.icon_scale.setValue(int(self.settings.get("dodge_icon_scale_percent", DEFAULT_SETTINGS["dodge_icon_scale_percent"])))
        cf.addRow("翻滚图标缩放:", self.icon_scale)

        self.roll_icon_opacity_spin = QSpinBox()
        self.roll_icon_opacity_spin.setRange(0, 100)
        self.roll_icon_opacity_spin.setSuffix("%")
        self.roll_icon_opacity_spin.setValue(int(self.settings.get("roll_icon_opacity", DEFAULT_SETTINGS["roll_icon_opacity"])))
        cf.addRow("翻滚图标不透明度:", self.roll_icon_opacity_spin)
        form.addRow(card)

        # ── 倒计时 ──
        form = form_timer_shape
        card, cf = make_card(form, "── 倒计时弧线 ──")

        self.timer_style = QComboBox()
        self.timer_style.addItem("圆环", "ring")
        self.timer_style.addItem("扇形", "sector")
        idx = self.timer_style.findData(self.settings.get("timer_style", DEFAULT_SETTINGS["timer_style"]))
        self.timer_style.setCurrentIndex(max(0, idx))
        cf.addRow("倒计时样式:", self.timer_style)

        self.timer_arc_radius = QSpinBox()
        self.timer_arc_radius.setRange(0, 60)
        self.timer_arc_radius.setValue(int(self.settings.get("timer_arc_radius_offset", DEFAULT_SETTINGS["timer_arc_radius_offset"])))
        cf.addRow("倒计时弧线内缩:", self.timer_arc_radius)

        self.timer_center_y = QSpinBox()
        self.timer_center_y.setRange(-50, 50)
        self.timer_center_y.setValue(int(self.settings.get("timer_center_offset_y", 0)))
        cf.addRow("倒计时圆心Y偏移:", self.timer_center_y)
        self._add_color_row(cf, "arc_color", "倒计时弧颜色:")
        form.addRow(card)

        # ── 倒计时胶囊 ──
        card, cf = make_card(form, "── 倒计时胶囊 ──")

        self.lv7_timer_y_offset = QSpinBox()
        self.lv7_timer_y_offset.setRange(-30, 30)
        self.lv7_timer_y_offset.setValue(int(self.settings.get("lv7_timer_y_offset", 0)))
        cf.addRow("时间胶囊Y偏移:", self.lv7_timer_y_offset)

        self.lv7_timer_badge_width = QSpinBox()
        self.lv7_timer_badge_width.setRange(0, 40)
        self.lv7_timer_badge_width.setSuffix("px")
        self.lv7_timer_badge_width.setValue(int(self.settings.get("lv7_timer_badge_width", DEFAULT_SETTINGS["lv7_timer_badge_width"])))
        cf.addRow("时间胶囊宽度:", self.lv7_timer_badge_width)

        self.timer_font_size = QSpinBox()
        self.timer_font_size.setRange(0, 48)
        self.timer_font_size.setValue(int(self.settings.get("timer_font_size", DEFAULT_SETTINGS["timer_font_size"])))
        cf.addRow("倒计时字体大小:", self.timer_font_size)
        self._add_color_row(cf, "timer_text_color", "倒计时文字色:")
        form.addRow(card)

        # ── 层数数字（合并标签页）──
        form = form_stack

        # ── 层数数字(无计时) ──
        card, cf = make_card(form, "── 层数数字(无计时) ──")

        self.center_offset_x = QSpinBox()
        self.center_offset_x.setRange(-50, 50)
        self.center_offset_x.setValue(int(self.settings.get("center_text_offset_x", 0)))
        cf.addRow("层数数字X偏移:", self.center_offset_x)

        self.center_offset_y = QSpinBox()
        self.center_offset_y.setRange(-50, 50)
        self.center_offset_y.setValue(int(self.settings.get("center_text_offset_y", 0)))
        cf.addRow("层数数字Y偏移:", self.center_offset_y)

        self.dh_font_size = QSpinBox()
        self.dh_font_size.setRange(14, 72)
        self.dh_font_size.setValue(int(self.settings.get("dh_font_size", DEFAULT_SETTINGS["dh_font_size"])))
        cf.addRow("层数数字大小:", self.dh_font_size)

        self.dh_text_outline_width = QSpinBox()
        self.dh_text_outline_width.setRange(0, 12)
        self.dh_text_outline_width.setValue(int(self.settings.get("dh_text_outline_width", DEFAULT_SETTINGS["dh_text_outline_width"])))
        cf.addRow("层数数字勾边粗细:", self.dh_text_outline_width)
        self._add_color_row(cf, "text_color", "层数数字色:")
        self._add_color_row(cf, "dh_text_outline_color", "层数数字勾边色:")
        form.addRow(card)

        # ── 层数数字(有计时) ──
        card, cf = make_card(form, "── 层数数字(有计时) ──")

        self.center_offset_x_timer = QSpinBox()
        self.center_offset_x_timer.setRange(-50, 50)
        self.center_offset_x_timer.setValue(int(self.settings.get("center_text_offset_x_timer", 0)))
        cf.addRow("层数数字X偏移 — (计时版):", self.center_offset_x_timer)

        self.center_offset_y_timer = QSpinBox()
        self.center_offset_y_timer.setRange(-50, 50)
        self.center_offset_y_timer.setValue(int(self.settings.get("center_text_offset_y_timer", 0)))
        cf.addRow("层数数字Y偏移 — (计时版):", self.center_offset_y_timer)

        self.dh_font_size_timer = QSpinBox()
        self.dh_font_size_timer.setRange(14, 72)
        self.dh_font_size_timer.setValue(int(self.settings.get("dh_font_size_timer", DEFAULT_SETTINGS["dh_font_size_timer"])))
        cf.addRow("层数数字大小 — (计时版):", self.dh_font_size_timer)

        self.dh_text_outline_width_timer = QSpinBox()
        self.dh_text_outline_width_timer.setRange(0, 12)
        self.dh_text_outline_width_timer.setValue(int(self.settings.get("dh_text_outline_width_timer", DEFAULT_SETTINGS["dh_text_outline_width_timer"])))
        cf.addRow("层数数字勾边粗细 — (计时版):", self.dh_text_outline_width_timer)
        self._add_color_row(cf, "text_color_timer", "层数数字色 — (计时版):")
        self._add_color_row(cf, "dh_text_outline_color_timer", "层数数字勾边色 — (计时版):")
        form.addRow(card)

        # ── 颜色行分散到各模块标签页 ──
        form = form_buff_name
        self._add_color_row(form, "buff_name_color", "Buff名色:")

        self._connect_live_signals()
        self.lang.currentIndexChanged.connect(self.retranslate_ui)

        buttons = QHBoxLayout()
        defaults = QPushButton("恢复默认")
        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        defaults.setAutoDefault(False)
        defaults.setDefault(False)
        ok.setAutoDefault(True)
        ok.setDefault(True)
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        defaults.clicked.connect(self.reset_defaults)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(defaults)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        # 署名 — 设置最底部小字
        sig = QLabel(AUTHOR_TAG)
        sig.setStyleSheet("color:#445566; font-size:9px;")
        sig.setAlignment(Qt.AlignCenter)
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
            "未接入角色简化:": "Non-combat opacity:",
            "未接入/非目标角色时仅显示圆圈和翻滚UI": "Adjust opacity when not in combat / character not connected",
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
            "启动位置:": "Start position:",
            "整体等比缩放:": "UI scale:",
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
            "倒计时字体大小:": "Timer font size:",
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
            "── 技能冷却 ──": "── Skill Cooldown ──",
            "显示技能冷却": "Show Skill Cooldowns",
            "方形大小:": "Square Size:",
            "聚散距离:": "Spread Distance:",
            "位置偏移X:": "Position Offset X:",
            "位置偏移Y:": "Position Offset Y:",
            "扇形颜色:": "Sector Color:",
            "倒计时文字色:": "Timer Text Color:",
            "── 冷却完成动画 ──": "── Cooldown Complete Animation ──",
            "完成色:": "Ready Color:",
            "放大比例%:": "Scale Up %:",
            "动画时长ms:": "Animation Duration ms:",
            "── 技能名称 ──": "── Skill Name ──",
            "显示技能名称": "Show Skill Name",
            "字号:": "Font Size:",
            "Y偏移:": "Y Offset:",
            "衬色块宽微调:": "BG Width Adjust:",
            "技能名色:": "Skill Name Color:",
            "恢复默认": "Reset",
            "确定": "OK",
            "取消": "Cancel",
        }
        zh_to_tw = {
            "Overlay 设置": "Overlay 設定",
            "── 常规 ──": "── 常規 ──",
            "语言 / Language:": "語言 / Language:",
            "随游戏前后台:": "隨遊戲前後台:",
            "游戏在前台时显示，切到后台时自动最小化": "遊戲在前台時顯示，切到後台時自動最小化",
            "随分辨率放大:": "隨解析度放大:",
            "按当前屏幕宽度自动放大": "按當前螢幕寬度自動放大",
            "未接入角色简化:": "非戰鬥透明度:",
            "未接入/非目标角色时仅显示圆圈和翻滚UI": "非戰鬥狀態/未接入角色時調整透明度",
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
            "启动位置:": "啟動位置:",
            "整体等比缩放:": "整體等比縮放:",
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
            "── 技能冷却 ──": "── 技能冷卻 ──",
            "显示技能冷却": "顯示技能冷卻",
            "方形大小:": "方形大小:",
            "聚散距离:": "聚散距離:",
            "位置偏移X:": "位置偏移X:",
            "位置偏移Y:": "位置偏移Y:",
            "扇形颜色:": "扇形顏色:",
            "倒计时文字色:": "倒計時文字色:",
            "── 冷却完成动画 ──": "── 冷卻完成動畫 ──",
            "完成色:": "完成色:",
            "放大比例%:": "放大比例%:",
            "动画时长ms:": "動畫時長ms:",
            "── 技能名称 ──": "── 技能名稱 ──",
            "显示技能名称": "顯示技能名稱",
            "字号:": "字號:",
            "Y偏移:": "Y偏移:",
            "衬色块宽微调:": "襯色塊寬微調:",
            "技能名色:": "技能名色:",
            "恢复默认": "恢復預設",
            "确定": "確定",
            "取消": "取消",
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
        if hasattr(self, "settings_tabs"):
            tab_names_zh = ["全局", "背景与标题", "Buff外层", "层数数字", "倒计时", "Buff名字", "多buff差异化", "翻滚", "技能冷却", "Buff启用/禁用"]
            tab_names_tw = ["全域", "背景與標題", "Buff外層", "層數數字", "倒計時", "Buff名字", "多buff差異化", "翻滾", "技能冷卻", "Buff啟用/禁用"]
            tab_names_en = ["Global", "Background & Title", "Buff Outer", "Stack Number", "Timer", "Buff Name", "Multi-buff", "Dodge", "Skill Cooldown", "Buff Enable/Disable"]
            tab_names = tab_names_en if lang == "en" else (tab_names_tw if lang == "zh_tw" else tab_names_zh)
            for i, name in enumerate(tab_names):
                if i < self.settings_tabs.count():
                    self.settings_tabs.setTabText(i, name)
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

        if hasattr(self, "timer_style"):
            ring_idx = self.timer_style.findData("ring")
            sector_idx = self.timer_style.findData("sector")
            if ring_idx >= 0:
                self.timer_style.setItemText(ring_idx, "Ring" if lang == "en" else "圆环")
            if sector_idx >= 0:
                self.timer_style.setItemText(sector_idx, "Sector" if lang == "en" else "扇形")

        # 翻译 buff 复选框标签
        if hasattr(self, "buff_checkboxes"):
            for key, cb in self.buff_checkboxes.items():
                parts = key.split("_")
                char_type = int(parts[0], 16)
                buff_idx = int(parts[1])
                profile = BUFF_PROFILES.get(char_type, {})
                buffs = profile.get("buffs", [])
                if buff_idx < len(buffs):
                    char_name = _char_name(char_type, lang)
                    buff_name = _buff_name(buffs[buff_idx], lang)
                    cb.setText(f"{char_name} - {buff_name}")

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

    def _connect_live_signals(self):
        widgets = [
            self.lang, self.auto_focus_minimize, self.resolution_auto_scale, self.siegfried_only, self.show_titlebar_status, self.icon_use_default,
            self.window_x, self.window_y,
            self.ui_scale_slider, self.ui_scale_spin,
            self.scan, self.circle_radius, self.spike_length, self.spike_axis_pos,
            self.spike_width, self.spike_waist_pos, self.spike_bead_radius, self.spike_bead_pos,
            self.indicator_outline_enabled, self.indicator_outline_width,
            self.dh_font_size, self.dh_text_outline_width, self.timer_font_size,
            self.timer_style, self.timer_arc_radius,
            self.timer_center_y,
            self.center_offset_x, self.center_offset_y,
            self.dh_font_size_timer, self.center_offset_x_timer, self.center_offset_y_timer, self.dh_text_outline_width_timer,
            self.icon_path, self.icon_scale, self.roll_icon_opacity_spin,
            self.circle_pad_title, self.shrimp_gap_circle, self.show_roll_divider, self.roll_divider_opacity,
            self.ex_status_offset_spin,
            self.lv7_timer_y_offset,
            self.lv7_timer_badge_width,
            self.skill_cd_show_chk, self.skill_cd_size_spn, self.skill_cd_spread_spn,
            self.skill_cd_offx_spn, self.skill_cd_offy_spn,
            self.skill_cd_ready_scale_spn, self.skill_cd_ready_dur_spn,
            self.skill_cd_name_chk, self.skill_cd_name_font_spn,
            self.skill_cd_name_offy_spn, self.skill_cd_name_bgw_spn,
            self.non_combat_spike_op_spn, self.non_combat_roll_op_spn, self.non_combat_skill_cd_op_spn,
        ]
        for w in widgets:
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._emit_changed)
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(self._emit_changed)
            elif isinstance(w, (QSpinBox, QSlider)):
                w.valueChanged.connect(self._emit_changed)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(self._emit_changed)
        for spin in self.opacity_spins.values():
            spin.valueChanged.connect(self._emit_changed)
        self.multi_buff_offset_slider.valueChanged.connect(self._emit_changed)
        self.multi_buff_offset_spin.valueChanged.connect(self._emit_changed)
        self.multi_buff_scale_slider.valueChanged.connect(self._emit_changed)
        self.multi_buff_scale_spin.valueChanged.connect(self._emit_changed)
        self.multi_buff_angle_slider.valueChanged.connect(self._emit_changed)
        self.multi_buff_angle_spin.valueChanged.connect(self._emit_changed)
        self.multi_buff_external_color_cb.stateChanged.connect(self._emit_changed)
        self.multi_buff_internal_color_cb.stateChanged.connect(self._emit_changed)
        self.show_buff_name_cb.stateChanged.connect(self._emit_changed)
        self.buff_name_font_size.valueChanged.connect(self._emit_changed)
        self.buff_name_offset_x.valueChanged.connect(self._emit_changed)
        self.buff_name_offset_y.valueChanged.connect(self._emit_changed)
        self.buff_name_bg_width.valueChanged.connect(self._emit_changed)
        # buff 复选框实时响应
        for cb in self.buff_checkboxes.values():
            cb.stateChanged.connect(self._emit_changed)

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
        self._suppress_emit = True
        self.settings = dict(DEFAULT_SETTINGS)
        self.lang.setCurrentText(DEFAULT_SETTINGS["language"])
        self.auto_focus_minimize.setChecked(DEFAULT_SETTINGS["auto_focus_minimize"])
        self.resolution_auto_scale.setChecked(DEFAULT_SETTINGS["resolution_auto_scale"])
        self.siegfried_only.setChecked(DEFAULT_SETTINGS["siegfried_only"])
        self.non_combat_spike_op_spn.setValue(DEFAULT_SETTINGS["non_combat_spike_opacity"])
        self.non_combat_roll_op_spn.setValue(DEFAULT_SETTINGS["non_combat_roll_opacity"])
        self.non_combat_skill_cd_op_spn.setValue(DEFAULT_SETTINGS["non_combat_skill_cd_opacity"])
        self.show_titlebar_status.setChecked(DEFAULT_SETTINGS["show_titlebar_status"])
        # buff 全部重置为启用
        for cb in self.buff_checkboxes.values():
            cb.setChecked(True)
        self.multi_buff_offset_spin.setValue(DEFAULT_SETTINGS["multi_buff_offset"])
        self.multi_buff_offset_slider.setValue(DEFAULT_SETTINGS["multi_buff_offset"])
        self.multi_buff_scale_spin.setValue(DEFAULT_SETTINGS["multi_buff_scale"])
        self.multi_buff_scale_slider.setValue(DEFAULT_SETTINGS["multi_buff_scale"])
        self.multi_buff_angle_spin.setValue(DEFAULT_SETTINGS["multi_buff_angle"])
        self.multi_buff_angle_slider.setValue(DEFAULT_SETTINGS["multi_buff_angle"])
        self.multi_buff_external_color_cb.setChecked(DEFAULT_SETTINGS["multi_buff_external_color"])
        self.multi_buff_internal_color_cb.setChecked(DEFAULT_SETTINGS["multi_buff_internal_color"])
        self.show_buff_name_cb.setChecked(DEFAULT_SETTINGS["show_buff_name"])
        self.buff_name_font_size.setValue(DEFAULT_SETTINGS["buff_name_font_size"])
        self.buff_name_offset_x.setValue(DEFAULT_SETTINGS["buff_name_offset_x"])
        self.buff_name_offset_y.setValue(DEFAULT_SETTINGS["buff_name_offset_y"])
        self.buff_name_bg_width.setValue(DEFAULT_SETTINGS["buff_name_bg_width"])
        self.icon_use_default.setChecked(DEFAULT_SETTINGS["use_default_dodge_icon"])
        self.ui_scale_slider.setValue(DEFAULT_SETTINGS["ui_scale_percent"])
        self.ui_scale_spin.setValue(DEFAULT_SETTINGS["ui_scale_percent"])
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
        self.shrimp_gap_circle.setValue(DEFAULT_SETTINGS["shrimp_gap_circle"])
        self.show_roll_divider.setChecked(DEFAULT_SETTINGS["show_roll_divider"])
        self.roll_divider_opacity.setValue(DEFAULT_SETTINGS["roll_divider_opacity"])
        self.center_offset_x.setValue(DEFAULT_SETTINGS["center_text_offset_x"])
        self.center_offset_y.setValue(DEFAULT_SETTINGS["center_text_offset_y"])
        self.dh_font_size_timer.setValue(DEFAULT_SETTINGS["dh_font_size_timer"])
        self.center_offset_x_timer.setValue(DEFAULT_SETTINGS["center_text_offset_x_timer"])
        self.center_offset_y_timer.setValue(DEFAULT_SETTINGS["center_text_offset_y_timer"])
        self.dh_text_outline_width_timer.setValue(DEFAULT_SETTINGS["dh_text_outline_width_timer"])
        self.roll_icon_opacity_spin.setValue(DEFAULT_SETTINGS["roll_icon_opacity"])
        self.lv7_timer_y_offset.setValue(DEFAULT_SETTINGS["lv7_timer_y_offset"])
        self.lv7_timer_badge_width.setValue(DEFAULT_SETTINGS["lv7_timer_badge_width"])
        self.timer_center_y.setValue(DEFAULT_SETTINGS["timer_center_offset_y"])
        self.ex_status_offset_spin.setValue(DEFAULT_SETTINGS["ex_status_offset"])
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
        self.settings["siegfried_only"] = self.siegfried_only.isChecked()
        self.settings["non_combat_spike_opacity"] = self.non_combat_spike_op_spn.value()
        self.settings["non_combat_roll_opacity"] = self.non_combat_roll_op_spn.value()
        self.settings["non_combat_skill_cd_opacity"] = self.non_combat_skill_cd_op_spn.value()
        self.settings["show_titlebar_status"] = self.show_titlebar_status.isChecked()
        self.settings["buff_enabled"] = {key: cb.isChecked() for key, cb in self.buff_checkboxes.items()}
        self.settings["multi_buff_offset"] = self.multi_buff_offset_spin.value()
        self.settings["multi_buff_scale"] = self.multi_buff_scale_spin.value()
        self.settings["multi_buff_angle"] = self.multi_buff_angle_spin.value()
        self.settings["multi_buff_external_color"] = self.multi_buff_external_color_cb.isChecked()
        self.settings["multi_buff_internal_color"] = self.multi_buff_internal_color_cb.isChecked()
        self.settings["show_buff_name"] = self.show_buff_name_cb.isChecked()
        self.settings["buff_name_font_size"] = self.buff_name_font_size.value()
        self.settings["buff_name_offset_x"] = self.buff_name_offset_x.value()
        self.settings["buff_name_offset_y"] = self.buff_name_offset_y.value()
        self.settings["buff_name_bg_width"] = self.buff_name_bg_width.value()
        # 技能冷却
        self.settings["show_skill_cd"] = self.skill_cd_show_chk.isChecked()
        self.settings["skill_cd_size"] = self.skill_cd_size_spn.value()
        self.settings["skill_cd_spread"] = self.skill_cd_spread_spn.value()
        self.settings["skill_cd_offset_x"] = self.skill_cd_offx_spn.value()
        self.settings["skill_cd_offset_y"] = self.skill_cd_offy_spn.value()
        self.settings["skill_cd_ready_scale"] = self.skill_cd_ready_scale_spn.value()
        self.settings["skill_cd_ready_duration_ms"] = self.skill_cd_ready_dur_spn.value()
        self.settings["skill_cd_show_name"] = self.skill_cd_name_chk.isChecked()
        self.settings["skill_cd_name_font_size"] = self.skill_cd_name_font_spn.value()
        self.settings["skill_cd_name_offset_y"] = self.skill_cd_name_offy_spn.value()
        self.settings["skill_cd_name_bg_width"] = self.skill_cd_name_bgw_spn.value()
        self.settings["use_default_dodge_icon"] = self.icon_use_default.isChecked()
        self.settings["window_x"] = self.window_x.value()
        self.settings["window_y"] = self.window_y.value()
        # 同步保存比例位置（跨分辨率自适应）
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            sw, sh = geo.width(), geo.height()
            if sw > 0 and sh > 0:
                self.settings["window_x_ratio"] = self.window_x.value() / sw
                self.settings["window_y_ratio"] = self.window_y.value() / sh
        self.settings["ui_scale_percent"] = self.ui_scale_spin.value()
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
        self.settings["shrimp_gap_circle"] = self.shrimp_gap_circle.value()
        self.settings["show_roll_divider"] = self.show_roll_divider.isChecked()
        self.settings["roll_divider_opacity"] = self.roll_divider_opacity.value()
        self.settings["center_text_offset_x"] = self.center_offset_x.value()
        self.settings["center_text_offset_y"] = self.center_offset_y.value()
        self.settings["dh_font_size_timer"] = self.dh_font_size_timer.value()
        self.settings["center_text_offset_x_timer"] = self.center_offset_x_timer.value()
        self.settings["center_text_offset_y_timer"] = self.center_offset_y_timer.value()
        self.settings["dh_text_outline_width_timer"] = self.dh_text_outline_width_timer.value()
        self.settings["roll_icon_opacity"] = self.roll_icon_opacity_spin.value()
        self.settings["lv7_timer_y_offset"] = self.lv7_timer_y_offset.value()
        self.settings["lv7_timer_badge_width"] = self.lv7_timer_badge_width.value()
        self.settings["timer_center_offset_y"] = self.timer_center_y.value()
        self.settings["ex_status_offset"] = self.ex_status_offset_spin.value()
        for key, btn in self.color_buttons.items():
            self.settings[key] = btn.text()
        for key, spin in self.opacity_spins.items():
            self.settings[f"{key}_opacity"] = spin.value()
        return self.settings


# ============================ Overlay Widget ============================
class GBFROverlayQt(QWidget):
    TITLE_BAR_H = 26
    CANVAS_W = 240
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

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.locked = False
        self.drag_pos = None

        self.handle = None
        self.pid = None
        self.pptr = None
        self.module_base = None
        self.status = "init"
        self.active_buffs = []
        self.dodge_count = 0
        self.char_type = 0
        self._auto_minimized_by_game_focus = False
        # 技能冷却状态
        self.skill_cd_data = []
        self._skill_ready_anim = [None] * 4  # 每槽的完成动画时间戳
        self.non_combat_opacity_active = False
        load_char_db()

        self.recalc_layout()
        self.load_dodge_icon()
        self.setWindowTitle(f"{_app_title(self.settings.get('language', 'zh'))} v{APP_VERSION}")
        if os.path.isfile(APP_ICON_PATH):
            self.setWindowIcon(QIcon(APP_ICON_PATH))
        # 不使用 Qt.Tool：普通窗口会出现在任务栏，同时仍保持置顶和无边框
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.resize(self.window_w, self.window_h)

        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None
        saved_xr = self.settings.get("window_x_ratio")
        saved_yr = self.settings.get("window_y_ratio")
        if saved_xr is not None and saved_yr is not None and screen_geo:
            self.move(int(saved_xr * screen_geo.width()), int(saved_yr * screen_geo.height()))
        else:
            saved_x = self.settings.get("window_x")
            saved_y = self.settings.get("window_y")
            if saved_x is not None and saved_y is not None:
                self.move(int(saved_x), int(saved_y))
            elif screen_geo:
                self.move(screen_geo.right() - self.window_w - 15, screen_geo.top() + 15)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        self.tick()

        self._setup_tray_icon()

    # ----------------------------------------------------------------
    #  不透明度辅助
    # ----------------------------------------------------------------
    def _effective_opacity(self, color_key):
        """返回 0.0–1.0 的有效不透明度，锁定时仅标题栏/背景/图标减半（向上取整）。
        非战斗状态下尖刺UI/技能CD UI使用各自的不透明度覆写。"""
        opacity = int(self.settings.get(f"{color_key}_opacity", 100))
        if self.locked and color_key in LOCK_HALVED_KEYS:
            opacity = math.ceil(opacity / 2)
        if self.non_combat_opacity_active:
            if color_key in NON_COMBAT_SPIKE_KEYS:
                opacity = int(self.settings.get("non_combat_spike_opacity", 30))
            elif color_key in NON_COMBAT_SKILL_CD_KEYS:
                opacity = int(self.settings.get("non_combat_skill_cd_opacity", 30))
        return max(0, min(100, opacity)) / 100.0

    def _buff_max_stacks(self, buff):
        """单个 buff 的满层层数。优先使用内存动态读取值，回退到默认7。"""
        ms = buff.get("max_stacks")
        if ms and ms > 0:
            return max(1, int(ms))
        return 7

    def _is_buff_full_stack(self, buff):
        """单个 buff 是否进入满层状态。"""
        return int(buff.get("stacks", 0)) >= self._buff_max_stacks(buff)

    def _buff_has_timer(self, buff):
        """单个 buff 是否有有效倒计时。"""
        timer_display = buff.get("timer_display", "any_stack")
        stacks = int(buff.get("stacks", 0))
        if timer_display == "full_stack_only":
            should = self._is_buff_full_stack(buff)
        else:
            should = stacks > 0
        return should and isinstance(buff.get("timer"), (int, float)) and 0 <= buff["timer"] < 999

    def _is_buff_single_layer(self, buff):
        """buff 是否为单层（只有倒计时，无层数概念）。"""
        ms = buff.get("max_stacks")
        return ms is not None and ms <= 1

    def recalc_layout(self):
        # 用户手动缩放
        user_scale = int(self.settings.get("ui_scale_percent", DEFAULT_SETTINGS["ui_scale_percent"])) / 100.0
        # 分辨率自适应：以 1920x1080 为基准，屏幕越宽缩放越大，可在设置中关闭
        if bool(self.settings.get("resolution_auto_scale", DEFAULT_SETTINGS["resolution_auto_scale"])):
            screen = QApplication.primaryScreen()
            screen_w = screen.availableGeometry().width() if screen else 1920
            self.res_scale = max(1.0, screen_w / 1920.0)
        else:
            self.res_scale = 1.0
        # 最终缩放 = 用户缩放 × 分辨率缩放
        self.ui_scale = max(0.1, min(5.0, user_scale * self.res_scale))
        self.circle_r = int(self.settings.get("circle_radius", DEFAULT_SETTINGS["circle_radius"]))
        self.spike_len = int(self.settings.get("spike_length", DEFAULT_SETTINGS["spike_length"]))
        self.spike_axis_pos = int(self.settings.get("spike_axis_pos_percent", DEFAULT_SETTINGS["spike_axis_pos_percent"])) / 100.0
        self.spike_w = int(self.settings.get("spike_width", DEFAULT_SETTINGS["spike_width"]))
        self.spike_waist_pos = int(self.settings.get("spike_waist_pos_percent", DEFAULT_SETTINGS["spike_waist_pos_percent"])) / 100.0
        self.spike_bead_radius = int(self.settings.get("spike_bead_radius", DEFAULT_SETTINGS["spike_bead_radius"]))
        self.spike_bead_pos = int(self.settings.get("spike_bead_pos_percent", DEFAULT_SETTINGS["spike_bead_pos_percent"])) / 100.0
        self.indicator_outline_width = int(self.settings.get("indicator_outline_width", DEFAULT_SETTINGS["indicator_outline_width"])) if bool(self.settings.get("use_indicator_outline", True)) else 0
        self.circle_pad_title = int(self.settings.get("circle_pad_title", DEFAULT_SETTINGS["circle_pad_title"]))
        self.shrimp_gap_circle = int(self.settings.get("shrimp_gap_circle", DEFAULT_SETTINGS["shrimp_gap_circle"]))
        scale = int(self.settings.get("dodge_icon_scale_percent", DEFAULT_SETTINGS["dodge_icon_scale_percent"]))
        self.dodge_icon_size = max(4, int(self.SHRIMP_BASE_SIZE * scale / 100))
        roll_group_w = self.MAX_DODGES * self.dodge_icon_size + (self.MAX_DODGES - 1) * self.ROLL_ICON_GAP
        spike_outer_extent = max(0, int((1.0 + self.spike_axis_pos) * self.spike_len))
        bead_outer_extent = self.spike_bead_radius + max(0, int(abs(self.spike_bead_pos) * self.spike_len))
        outline_pad = max(0, self.indicator_outline_width + 2)
        spike_side_extent = spike_outer_extent + max(self.spike_w // 2, self.spike_bead_radius) + outline_pad
        dragon_required_w = (self.circle_r + max(spike_side_extent, bead_outer_extent) + outline_pad + 10) * 2
        # 技能冷却UI所需宽度
        skill_cd_spread = int(self.settings.get("skill_cd_spread", 55))
        skill_cd_size = int(self.settings.get("skill_cd_size", 28))
        skill_cd_extent = skill_cd_spread + skill_cd_size + 10
        skill_cd_required_w = (self.circle_r + skill_cd_extent) * 2
        self.canvas_w = max(self.CANVAS_W, int(roll_group_w + self.SHRIMP_LEFT_PAD + self.SHRIMP_RIGHT_PAD), int(dragon_required_w), int(skill_cd_required_w))
        self.circle_cx = self.canvas_w // 2
        spike_top_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent, skill_cd_extent) + outline_pad
        spike_bottom_pad = max(self.spike_len, spike_outer_extent, bead_outer_extent, skill_cd_extent) + outline_pad
        self.circle_cy = self.TITLE_BAR_H + self.circle_pad_title + self.circle_r + spike_top_pad
        self.dragon_bottom_y = self.circle_cy + self.circle_r + self.spike_len
        self.roll_y = self.dragon_bottom_y + self.shrimp_gap_circle
        self.canvas_h = (
            self.TITLE_BAR_H
            + self.circle_pad_title
            + spike_top_pad
            + self.circle_r * 2
            + spike_bottom_pad
            + self.shrimp_gap_circle
            + self.dodge_icon_size
            + 16
        )
        self.window_w = max(1, int(self.canvas_w * self.ui_scale))
        self.window_h = max(1, int(self.canvas_h * self.ui_scale))

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
        """计算标题栏右上角四个图标区域：最小化、设置、锁定、退出（从左到右）。"""
        th = self.TITLE_BAR_H
        s = self.ICON_BTN_SIZE
        gap = self.ICON_BTN_GAP
        exit_x = self.canvas_w - s - 6
        lock_x = exit_x - s - gap
        settings_x = lock_x - s - gap
        minimize_x = settings_x - s - gap
        y = (th - s) // 2
        return (
            QRect(minimize_x, y, s, s),
            QRect(settings_x, y, s, s),
            QRect(lock_x, y, s, s),
            QRect(exit_x, y, s, s),
        )

    # ================================================================
    #  绘制：主事件
    # ================================================================
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.ui_scale, self.ui_scale)

        cx, cy, r = self.circle_cx, self.circle_cy, self.circle_r
        non_combat = (
            bool(self.settings.get("siegfried_only", True))
            and self.status == "ok"
            and self.char_type not in BUFF_PROFILES
        ) or (self.status == "ok" and not self.active_buffs)
        self.non_combat_opacity_active = non_combat

        self._draw_backdrop(painter)
        self._draw_title_bar(painter)

        if non_combat:
            # 非战斗/未接入角色：不隐藏UI，而是降低不透明度
            self._draw_indicator_outer_outline(painter, cx, cy, r, False, include_spikes=True)
            self._draw_circle(painter, cx, cy, r, False)
            self._draw_skill_cd_group(painter)
            self._draw_divider(painter)
            self._draw_roll_ui_row(painter)
            return

        if len(self.active_buffs) >= 2:
            # 多buff差异化模式：两个缩小的UI，按夹角方向对角错开
            multi_scale = int(self.settings.get("multi_buff_scale", 60)) / 100.0
            offset_pct = int(self.settings.get("multi_buff_offset", 70))
            offset = int(r * offset_pct / 100.0)
            angle_deg = int(self.settings.get("multi_buff_angle", 45))
            angle_rad = math.radians(angle_deg)
            dx = offset * math.cos(angle_rad)
            dy = offset * math.sin(angle_rad)

            buff1 = self.active_buffs[0]
            cx1, cy1 = cx - dx, cy - dy
            is_lv7_1 = self._is_buff_full_stack(buff1)
            self._render_buff_ui(painter, buff1, cx1, cy1, r, is_lv7_1, scale=multi_scale)

            buff2 = self.active_buffs[1]
            cx2, cy2 = cx + dx, cy + dy
            is_lv7_2 = self._is_buff_full_stack(buff2)
            comp_override = self._build_complementary_override()
            self._render_buff_ui(painter, buff2, cx2, cy2, r, is_lv7_2,
                                 scale=multi_scale, color_override=comp_override)

            # 所有buff UI渲染完毕后再绘制名字（避免被覆盖）
            self._draw_buff_name(painter, buff1, cx1, cy1, r, multi_scale)
            self._draw_buff_name(painter, buff2, cx2, cy2, r, multi_scale, color_override=comp_override)
        else:
            # 单buff模式：正常大小，正常位置，正常颜色
            buff = self.active_buffs[0] if self.active_buffs else None
            if buff:
                is_lv7 = self._is_buff_full_stack(buff)
                self._render_buff_ui(painter, buff, cx, cy, r, is_lv7)
                self._draw_buff_name(painter, buff, cx, cy, r, 1.0)

        self._draw_skill_cd_group(painter)
        self._draw_divider(painter)
        self._draw_roll_ui_row(painter)

    def _render_buff_ui(self, painter, buff, cx, cy, r, is_lv7, scale=1.0, color_override=None):
        """渲染一个完整的 buff UI 元素（圆环+尖刺+倒计时+中心文字）。"""
        is_single_layer = self._is_buff_single_layer(buff)
        painter.save()
        if scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        self._draw_glow(painter, cx, cy, r, is_lv7, color_override=color_override)
        include_spikes = not is_single_layer
        self._draw_indicator_outer_outline(painter, cx, cy, r, is_lv7,
                                           include_spikes=include_spikes,
                                           buff=buff, color_override=color_override)
        if not is_single_layer:
            self._draw_spikes(painter, cx, cy, r, is_lv7, buff=buff, color_override=color_override)
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
        center_y = int(cy + scaled_r + int(6 * scale) + off_y)

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

    def _draw_skill_cd_group(self, painter):
        """绘制4个技能冷却指示器（菱形布局：左1/上2/右3/下4）。"""
        if not bool(self.settings.get("show_skill_cd", True)):
            return
        if not self.skill_cd_data or self.status != "ok":
            return
        cx, cy, r = self.circle_cx, self.circle_cy, self.circle_r
        off_x = int(self.settings.get("skill_cd_offset_x", 0))
        off_y = int(self.settings.get("skill_cd_offset_y", 0))
        spread = int(self.settings.get("skill_cd_spread", 55))
        group_cx = cx + off_x
        group_cy = cy + off_y
        # 菱形方位：左/上/右/下
        positions = [
            (group_cx - spread, group_cy),       # 槽1 左
            (group_cx, group_cy - spread),       # 槽2 上
            (group_cx + spread, group_cy),       # 槽3 右
            (group_cx, group_cy + spread),       # 槽4 下
        ]
        for i, (sx, sy) in enumerate(positions):
            if i < len(self.skill_cd_data):
                self._draw_skill_cd_element(painter, self.skill_cd_data[i], sx, sy)

    def _draw_skill_cd_element(self, painter, skill, cx, cy):
        """绘制单个技能冷却元素：方形扇+胶囊+名称+完成动画。"""
        s = int(self.settings.get("skill_cd_size", 28))
        cd_val = skill.get("cd", 0)
        ready = skill.get("ready", True)
        cd_max = skill.get("cd_max", 0)
        lang = self.settings.get("language", "zh")

        # 完成动画进度
        anim_scale = 1.0
        anim_color = None
        anim_idx = skill.get("slot", 0)
        anim_start = self._skill_ready_anim[anim_idx] if anim_idx < 4 else None
        if anim_start is not None:
            dur = int(self.settings.get("skill_cd_ready_duration_ms", 400))
            elapsed = int(time.time() * 1000) - anim_start
            if elapsed < dur:
                progress = elapsed / dur
                # 先放大再缩回
                ready_scale = int(self.settings.get("skill_cd_ready_scale", 140)) / 100.0
                if progress < 0.3:
                    anim_scale = 1.0 + (ready_scale - 1.0) * (progress / 0.3)
                else:
                    anim_scale = ready_scale - (ready_scale - 1.0) * ((progress - 0.3) / 0.7)
                anim_color = self.settings.get("skill_cd_ready_color", "#ffffff")
            else:
                self._skill_ready_anim[anim_idx] = None

        # 颜色
        base_color_hex = anim_color if anim_color else self.settings.get("skill_cd_color", "#55aaff")
        base_opacity = self._effective_opacity("skill_cd_color") if not anim_color else 1.0

        painter.save()
        painter.setOpacity(base_opacity)

        # 缩放
        if anim_scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(anim_scale, anim_scale)
            painter.translate(-cx, -cy)

        # 方形扇 — 圆角矩形背景
        half = s
        rect = QRect(cx - half, cy - half, half * 2, half * 2)
        radius = max(3, s // 4)

        bg_color = qcolor(base_color_hex)
        bg_color.setAlpha(40)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, radius, radius)

        # 扇形进度（冷却中）
        if not ready and cd_max > 0:
            ratio = max(0.0, min(1.0, cd_val / cd_max))
            sector_color = qcolor(base_color_hex)
            sector_color.setAlpha(120)
            painter.setBrush(sector_color)
            painter.drawPie(rect, 90 * 16, int(-ratio * 360 * 16))
        elif ready:
            # 就绪：完整扇形
            sector_color = qcolor(base_color_hex)
            sector_color.setAlpha(100)
            painter.setBrush(sector_color)
            painter.drawPie(rect, 90 * 16, int(-1.0 * 360 * 16))

        # 边框
        border_color = qcolor(base_color_hex)
        border_color.setAlpha(180)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        # 胶囊（倒计时文字）
        if not ready:
            timer_text = f"{cd_val:.1f}"
        else:
            timer_text = "✓"
        cap_font = QFont("Segoe UI", max(7, s // 3), QFont.Bold)
        cap_metrics = QFontMetrics(cap_font)
        cap_w = min(s * 2 - 6, max(16, cap_metrics.horizontalAdvance(timer_text) + 8))
        cap_h = max(12, s // 2)
        cap_rect = QRect(int(cx - cap_w / 2), int(cy - cap_h / 2), cap_w, cap_h)
        cap_bg = qcolor(self.settings.get("skill_cd_capsule_bg", "#0a0e1a"))
        cap_bg.setAlpha(160)
        cap_border = qcolor(self.settings.get("skill_cd_capsule_border", base_color_hex))
        cap_border.setAlpha(100)
        painter.setPen(QPen(cap_border, 1))
        painter.setBrush(cap_bg)
        painter.drawRoundedRect(cap_rect, 4, 4)
        painter.setOpacity(self._effective_opacity("skill_cd_text_color"))
        text_color_hex = self.settings.get("skill_cd_text_color", "#ffffff")
        if cd_val < 3 and not ready:
            text_color_hex = "#ff4444"
        painter.setPen(qcolor(text_color_hex))
        painter.setFont(cap_font)
        painter.drawText(cap_rect, Qt.AlignCenter, timer_text)

        painter.restore()

        # 技能名称（不受缩放影响）
        if bool(self.settings.get("skill_cd_show_name", True)):
            self._draw_skill_cd_name(painter, skill, cx, cy, s)

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
        off_y = int(self.settings.get("skill_cd_name_offset_y", 0))
        bg_pad_x = max(2, font_size // 2)
        bg_pad_y = max(1, font_size // 4)
        bg_w = max(1, text_w + bg_pad_x * 2 + int(self.settings.get("skill_cd_name_bg_width", 0)))
        bg_h = text_h + bg_pad_y * 2
        bg_x = int(cx - bg_w / 2)
        bg_y = int(cy + s + 4 + off_y)
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
                           "buff_name_color",
                           "text_color_timer", "dh_text_outline_color_timer"}

    def _build_complementary_override(self):
        """构建补色覆盖字典：按外部/内部设置决定哪些颜色取补色。"""
        override = {}
        ext_enabled = self.settings.get("multi_buff_external_color", True)
        int_enabled = self.settings.get("multi_buff_internal_color", True)
        color_keys = [k for k in self.settings
                       if (k.endswith("_color") or "_color_" in k)
                       and not k.endswith("_opacity")]
        for key in color_keys:
            # 跳过共享颜色（标题栏/背景/图标）
            if key in ("title_bar_color", "bg_color", "icon_color"):
                continue
            # 按外部/内部设置过滤
            if key in self.EXTERNAL_COLOR_KEYS and not ext_enabled:
                continue
            if key in self.INTERNAL_COLOR_KEYS and not int_enabled:
                continue
            hex_val = self.settings.get(key, "#ffffff")
            if not isinstance(hex_val, str):
                continue
            c = QColor(hex_val)
            if c.isValid():
                comp = QColor(255 - c.red(), 255 - c.green(), 255 - c.blue())
                override[key] = comp.name()
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
        backdrop_bottom = self.roll_y + self.dodge_icon_size + 6

        bg_hex = self.settings.get("bg_color", "#0a0e16")
        title_hex = self.settings.get("title_bar_color", "#1a2030")

        path = QPainterPath()
        path.addRoundedRect(
            0, 0,
            self.canvas_w, backdrop_bottom,
            self.BACKDROP_RADIUS, self.BACKDROP_RADIUS,
        )

        # 内容区背景
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor(bg_hex))
        painter.setOpacity(self._effective_opacity("bg_color"))
        painter.drawPath(path)

        # 标题栏区域（裁剪到圆角路径内，仅填充顶部一条）
        painter.setClipPath(path)
        painter.setOpacity(self._effective_opacity("title_bar_color"))
        painter.setBrush(qcolor(title_hex))
        painter.drawRect(0, 0, self.canvas_w, self.TITLE_BAR_H)
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

        icon_color = QColor(self.settings.get("icon_color", "#7f8fa6"))

        painter.save()
        painter.setOpacity(self._effective_opacity("icon_color"))

        if not self.locked:
            # 标题栏状态文字（锁定时隐藏）
            if self.settings.get("show_titlebar_status", True):
                status_text = self._build_titlebar_status_text(lang)
                if status_text:
                    text_x = 4
                    text_rect = QRect(text_x, 0, minimize_rect.left() - text_x - 4, th)
                    painter.setPen(QColor(self.settings.get("icon_color", "#7f8fa6")))
                    painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                    painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, status_text)

            # 最小化图标：横线
            self._draw_icon_minimize(painter, minimize_rect, icon_color)
            # 设置图标：圆角矩形 + S
            self._draw_icon_settings(painter, settings_rect, icon_color)
            # 退出图标：X
            self._draw_icon_exit(painter, exit_rect, icon_color)

        # 锁定图标
        lock_icon_color = QColor("#ffaa22") if self.locked else icon_color
        self._draw_icon_lock(painter, lock_rect, lock_icon_color, self.locked)

        painter.restore()

    def _build_titlebar_status_text(self, lang="zh"):
        """构建标题栏状态文字：角色名 + 启用的buff名称和层数。"""
        if self.status == "no_game":
            if lang == "en": return "Waiting for game..."
            if lang == "zh_tw": return "等待遊戲..."
            return "等待游戏..."
        if self.status == "no_char" or not self.char_type:
            if lang == "en": return "No character"
            if lang == "zh_tw": return "未偵測到角色"
            return "未检测到角色"
        char_name = _char_name(self.char_type, lang)
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
        if visible_spikes <= 0:
            return
        key = "spike_color_lv7" if is_lv7 else "spike_color_normal"
        spike_color = qcolor(self._get_color(key, color_override))
        painter.save()
        painter.setOpacity(self._effective_opacity(key))

        light_c = QColor(spike_color).lighter(140)
        dark_c = QColor(spike_color).darker(135)
        outline_c = QColor(spike_color).darker(180)
        outline_c.setAlpha(150)

        for i in range(visible_spikes):
            angle = -90 + i * (360.0 / max_stacks)
            points = self._calc_spike_points(cx, cy, r, angle)
            path = QPainterPath()
            path.moveTo(points["tip"][0], points["tip"][1])
            path.lineTo(points["left"][0], points["left"][1])
            path.lineTo(points["root"][0], points["root"][1])
            path.lineTo(points["right"][0], points["right"][1])
            path.closeSubpath()

            # PPT示意风格：整体偏实心，根部略深、尖端略亮
            grad = QLinearGradient(points["root"][0], points["root"][1], points["tip"][0], points["tip"][1])
            grad.setColorAt(0.0, dark_c)
            grad.setColorAt(0.42, spike_color)
            grad.setColorAt(1.0, light_c)
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(outline_c, 1.0))
            painter.drawPath(path)

            # 根部小圆点：对应PPT里底部的小圆
            bead_c = QColor(spike_color).darker(110)
            bead_outline = QColor(spike_color).darker(180)
            bead_r = max(0, int(self.spike_bead_radius))
            bead_x, bead_y = points["bead"]
            if bead_r > 0:
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
        timer_cy = cy + int(self.settings.get("timer_center_offset_y", 0))
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

    def _draw_timer_badge(self, painter, text, rect, color, color_override=None):
        """绘制圆内底部倒计时胶囊。"""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        bg = QColor(3, 5, 10, 125)
        if color_override:
            bg = QColor(252, 250, 245, 125)  # 补色背景
        border = qcolor(color)
        border.setAlpha(78)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 7, 7)

        font_size = max(10, min(16, int(self.settings.get("timer_font_size", 11)) + 1))
        painter.setOpacity(self._effective_opacity("timer_text_color"))
        badge_color = self._get_color("timer_text_color", color_override) if color_override else color
        painter.setPen(qcolor(badge_color))
        painter.setFont(QFont("Segoe UI", font_size, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def _draw_center_text(self, painter, cx, cy, r, is_lv7, buff=None, is_single_layer=False, color_override=None):
        if not buff:
            return
        painter.save()
        stacks = int(buff.get("stacks", 0))
        has_timer = self._buff_has_timer(buff)

        if is_single_layer:
            # 单层buff：只有倒计时胶囊，居中显示
            if has_timer:
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
                    timer_rect = QRect(int(cx - badge_w / 2), int(cy - badge_h / 2 + timer_y_offset), int(badge_w), badge_h)
                    self._draw_timer_badge(painter, timer_text, timer_rect, timer_color, color_override=color_override)
            painter.restore()
            return

        if has_timer:
            # 有计时版：使用独立的参数
            num_offset_x = int(self.settings.get("center_text_offset_x_timer", 0))
            num_offset_y = int(self.settings.get("center_text_offset_y_timer", 0))
            dh_text = str(stacks)
            dh_font_size = max(22, int(int(self.settings.get("dh_font_size_timer", DEFAULT_SETTINGS["dh_font_size_timer"])) * 0.88))
            dh_font = QFont("Segoe UI", dh_font_size, QFont.Bold)
            text_color = self._get_color("text_color_timer", color_override)
            dh_rect = QRect(cx - r + num_offset_x, cy - r - 3 + num_offset_y, r * 2, int(r * 1.18))
            self._draw_centered_outlined_text(painter, dh_text, dh_rect, dh_font, text_color,
                                              outline_adjust=-1, color_override=color_override,
                                              outline_width_key="dh_text_outline_width_timer",
                                              outline_color_key="dh_text_outline_color_timer",
                                              fill_color_key="text_color_timer")
        else:
            # 无计时版：使用无计时参数
            num_offset_x = int(self.settings.get("center_text_offset_x", 0))
            num_offset_y = int(self.settings.get("center_text_offset_y", 0))
            text = str(stacks)
            font = QFont("Segoe UI", int(self.settings.get("dh_font_size", DEFAULT_SETTINGS["dh_font_size"])), QFont.Bold)
            text_color = self._get_color("text_color", color_override)
            text_rect = QRect(cx - r + num_offset_x, cy - r + num_offset_y, r * 2, r * 2)
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
                timer_rect = QRect(int(cx - badge_w / 2), int(cy + r * 0.36 + timer_y_offset), int(badge_w), badge_h)
                self._draw_timer_badge(painter, timer_text, timer_rect, timer_color, color_override=color_override)
        painter.restore()

    # ================================================================
    #  绘制：分界线（层数区域与翻滚区域之间淡淡一条线）
    # ================================================================
    def _draw_divider(self, painter):
        if self.shrimp_gap_circle <= 0 or not bool(self.settings.get("show_roll_divider", DEFAULT_SETTINGS["show_roll_divider"])):
            return
        opacity = max(0, min(100, int(self.settings.get("roll_divider_opacity", DEFAULT_SETTINGS["roll_divider_opacity"]))))
        if self.non_combat_opacity_active:
            opacity = int(self.settings.get("non_combat_roll_opacity", 30))
        if opacity <= 0:
            return
        y = int(self.dragon_bottom_y + self.shrimp_gap_circle / 2)
        x1 = self.SHRIMP_LEFT_PAD
        x2 = self.canvas_w - self.SHRIMP_RIGHT_PAD
        painter.save()
        painter.setPen(QPen(QColor(255, 255, 255, int(255 * opacity / 100)), 1))
        painter.drawLine(QPoint(x1, y), QPoint(x2, y))
        painter.restore()

    # ================================================================
    #  绘制：翻滚图标行（整体居中，中轴过圆心，第6次起改为警告牌）
    # ================================================================
    def _draw_roll_ui_row(self, painter):
        sh_y = self.roll_y
        count = min(max(int(self.dodge_count), 0), self.MAX_DODGES)
        if count <= 0:
            return

        # 翻滚UI不透明度（锁定时不减半，与层数UI一样不受锁定影响）
        roll_opacity = max(0, min(100, int(self.settings.get("roll_icon_opacity", DEFAULT_SETTINGS["roll_icon_opacity"])))) / 100.0
        if self.non_combat_opacity_active:
            roll_opacity = int(self.settings.get("non_combat_roll_opacity", 30)) / 100.0

        icon = self.dodge_icon_size
        gap = self.ROLL_ICON_GAP
        group_width = count * icon + (count - 1) * gap if count > 1 else icon
        start_x = self.circle_cx - group_width / 2.0
        warning_mode = count >= 6

        painter.save()
        painter.setOpacity(roll_opacity)
        for i in range(count):
            x = int(start_x + i * (icon + gap))
            if warning_mode:
                self._draw_warning_roll_icon(painter, x, sh_y, icon)
            elif not self.shrimp.isNull():
                painter.drawPixmap(x, sh_y, self.shrimp)
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#ff8a56"))
                path = QPainterPath()
                path.addRoundedRect(x + 2, sh_y + max(2, icon // 6), icon - 4, max(8, icon * 2 // 3), 6, 6)
                painter.drawPath(path)
        painter.restore()

    def _draw_warning_roll_icon(self, painter, x, y, icon):
        """绘制红边框、黄底、红色粗感叹号的三角形警告牌。"""
        pad = max(2, int(icon * 0.08))
        cx = x + icon / 2.0
        top = y + pad
        left = x + pad
        right = x + icon - pad
        bottom = y + icon - pad

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # 三角形路径
        tri = QPainterPath()
        tri.moveTo(cx, top)
        tri.lineTo(right, bottom)
        tri.lineTo(left, bottom)
        tri.closeSubpath()

        # 红色粗边框 + 黄色背景填充
        red = QColor("#d71920")
        border_w = max(3, int(icon * 0.105))
        painter.setPen(QPen(red, border_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(QColor("#ffef00"))
        painter.drawPath(tri)

        # 红色粗感叹号 — 竖条
        bar_w = max(2, int(icon * 0.105))
        bar_h = max(8, int(icon * 0.34))
        bar_x = int(cx - bar_w / 2)
        bar_y = int(y + icon * 0.36)
        painter.setPen(Qt.NoPen)
        painter.setBrush(red)
        painter.drawRoundedRect(QRect(bar_x, bar_y, bar_w, bar_h), max(1, bar_w // 2), max(1, bar_w // 2))

        # 红色感叹号 — 底部圆点
        dot_r = max(2, int(icon * 0.075))
        painter.drawEllipse(QPoint(int(cx), int(y + icon * 0.81)), dot_r, dot_r)

        painter.restore()

    # ================================================================
    #  鼠标事件：标题栏拖动 + 图标按钮
    # ================================================================
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        raw_pos = event.position().toPoint()
        pos = QPoint(int(raw_pos.x() / self.ui_scale), int(raw_pos.y() / self.ui_scale))

        # 1) 图标按钮优先
        if self.locked:
            if hasattr(self, "_btn_lock_rect") and self._btn_lock_rect.contains(pos):
                self.locked = False
                self.update()
            return

        if hasattr(self, "_btn_exit_rect") and self._btn_exit_rect.contains(pos):
            QApplication.quit()
            return
        if hasattr(self, "_btn_minimize_rect") and self._btn_minimize_rect.contains(pos):
            self.showMinimized()
            return
        if hasattr(self, "_btn_lock_rect") and self._btn_lock_rect.contains(pos):
            self.locked = not self.locked
            self.update()
            return
        if hasattr(self, "_btn_settings_rect") and self._btn_settings_rect.contains(pos):
            self.open_settings()
            return

        # 2) 拖拽移动
        if not self.locked:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None and not self.locked:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseReleaseEvent(self, event):
        if self.drag_pos is not None:
            self.settings["window_x"] = self.x()
            self.settings["window_y"] = self.y()
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                sw, sh = geo.width(), geo.height()
                if sw > 0 and sh > 0:
                    self.settings["window_x_ratio"] = self.x() / sw
                    self.settings["window_y_ratio"] = self.y() / sh
            save_settings(self.settings)
        self.drag_pos = None

    def contextMenuEvent(self, event):
        pass

    def open_settings(self):
        if not self.isVisible():
            self.show()
        backup = dict(self.settings)
        dlg = SettingsDialog(self, self.settings)
        dlg.settings_changed.connect(self._apply_live_settings)
        if dlg.exec() == QDialog.Accepted:
            self.settings = dlg.get_settings()
            save_settings(self.settings)
            lang = self.settings.get("language", "zh")
            self.setWindowTitle(f"{_app_title(lang)} v{APP_VERSION}")
            self.recalc_layout()
            self.resize(self.window_w, self.window_h)
            self.move(int(self.settings.get("window_x", self.x())), int(self.settings.get("window_y", self.y())))
            self.load_dodge_icon()
            self.update()
        else:
            self.settings = backup
            save_settings(self.settings)
            lang = self.settings.get("language", "zh")
            self.setWindowTitle(f"{_app_title(lang)} v{APP_VERSION}")
            self.recalc_layout()
            self.resize(self.window_w, self.window_h)
            self.load_dodge_icon()
            self.update()

    def _apply_live_settings(self, new_settings):
        self.settings = dict(new_settings)
        save_settings(self.settings)
        lang = self.settings.get("language", "zh")
        self.setWindowTitle(f"{_app_title(lang)} v{APP_VERSION}")
        self.recalc_layout()
        self.resize(self.window_w, self.window_h)
        self.load_dodge_icon()
        self.update()

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
        if self.status == "ok" and self.char_type:
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

        self.tray_menu.addSeparator()

        exit_labels = {"zh": "退出", "zh_tw": "退出", "en": "Exit"}
        exit_action = self.tray_menu.addAction(exit_labels.get(lang, exit_labels["zh"]))
        exit_action.triggered.connect(QApplication.quit)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            if (not self.isVisible()) or self.isMinimized():
                self.showNormal()
                self.raise_()
                self.activateWindow()
            else:
                self.hide()

    def _toggle_lock(self):
        self.locked = not self.locked
        self.update()

    # ================================================================
    #  主循环
    # ================================================================
    def tick(self):
        try:
            self.scan()
            self._sync_visibility_with_game_focus()
            self._sync_mouse_transparency()
            self._update_tray_tooltip()
        except Exception:
            pass
        interval = int(self.settings.get("scan_ms", 50)) if self.handle else 500
        self.timer.start(interval)
        self.update()

    def _sync_mouse_transparency(self):
        """未接入/非目标角色仍显示圆圈和翻滚UI，不再启用鼠标穿透。"""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def _sync_visibility_with_game_focus(self):
        """游戏在前台时自动显示，切到后台时自动最小化。"""
        if not bool(self.settings.get("auto_focus_minimize", DEFAULT_SETTINGS["auto_focus_minimize"])):
            if self._auto_minimized_by_game_focus:
                self._auto_minimized_by_game_focus = False
                if self.isMinimized() or not self.isVisible():
                    self.showNormal()
            return

        if QApplication.activeModalWidget() is not None:
            return

        foreground_pid = get_foreground_pid()
        if foreground_pid in (None, os.getpid()):
            return

        game_is_foreground = self.pid is not None and foreground_pid == self.pid
        if game_is_foreground:
            if self._auto_minimized_by_game_focus or self.isMinimized() or not self.isVisible():
                self.showNormal()
                self.raise_()
            self._auto_minimized_by_game_focus = False
        else:
            if self.isVisible() and not self.isMinimized():
                self._auto_minimized_by_game_focus = True
                self.showMinimized()

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
            self.pptr, self.module_base, _ = resolve_with_cache(self.handle, pid)
            if self.pptr is None:
                self.status = "no_game"
                self.close_handle()
                return
        snap = read_overlay_data(self.handle, self.pptr)
        self.status = snap["status"]
        self.dodge_count = snap["dodge"] or 0
        self.char_type = snap.get("char_type", 0)
        # 按设置过滤启用的 buff
        buff_enabled = self.settings.get("buff_enabled", {})
        all_buffs = snap.get("buffs", [])
        self.active_buffs = []
        for buff in all_buffs:
            key = f"{self.char_type:#04x}_{buff['index']}"
            if buff_enabled.get(key, True):
                self.active_buffs.append(buff)
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
                if abid and sk["cd"] > cd_max.get(abid, 0):
                    cd_max[abid] = sk["cd"]
                # 检测冷却完成 → 触发动画
                was_ready = self._skill_ready_anim[i] is not None or (
                    self.skill_cd_data and not self.skill_cd_data[i].get("ready", True) if i < len(self.skill_cd_data) else False
                )
                if sk["ready"] and self.skill_cd_data and i < len(self.skill_cd_data):
                    if not self.skill_cd_data[i].get("ready", True):
                        self._skill_ready_anim[i] = now_ms
                sk["ability_id"] = abid
                sk["cd_max"] = cd_max.get(abid, 0) if abid else 0
            self.skill_cd_data = new_skills
            if cd_max != self.settings.get("skill_cooldown_max", {}):
                self.settings["skill_cooldown_max"] = cd_max
                save_settings(self.settings)

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


def main():
    try:
        kernel32.FreeConsole()
    except Exception:
        pass
    app = QApplication(sys.argv)
    if os.path.isfile(APP_ICON_PATH):
        app.setWindowIcon(QIcon(APP_ICON_PATH))
    app.setQuitOnLastWindowClosed(False)
    overlay = GBFROverlayQt()
    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

