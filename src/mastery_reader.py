# -*- coding: utf-8 -*-
"""专精（觉醒/真谛/秘义）最高阶判定 —— 移植自 GBFR_BuffMonitor 的 read_skillboard。

数据通路（villith/relink-logs read_record_skillboard）：
  record = actor + 0x15030
  节点数组 = record + 0x138  (400 * 0x38, 每槽 {u32 id, u32 bits})
  当前角色 charid = record + 0x5B10  (= actor + 0x1AB40)
  CharaPower 全局双 unordered_map：用 charid 查 char_map 得该角色节点 key 向量，
    再用每个 key 查 node_map 得 (node_id, bit, effect_id)；用节点数组的 bits 第 bit 位
    判断是否解锁；effect_id 经 effect_id_class.json 分到 SB_DEF/SB_ATK/SB_LIMIT ×
    R1/R2/R3/EX 的 3×4 计数。
  决策：每类阈值 {R1:3,R2:6,R3:6} 折成 0..3 阶，三类取 max，按
    (SB_DEF=觉醒, SB_ATK=真谛, SB_LIMIT=秘义) 顺序取首个达 max 的类别作最高阶专精。

本模块自包含（ctypes/kernel32 读取，不依赖 pymem），numpy 可选：
  - 有 numpy：候选 RVA 命中失败时全段扫描游戏模块数据段（与 BuffMonitor 一致）；
  - 无 numpy：仅用候选 RVA，命中失败则返回 None（专精门控降级为“不判定”）。
"""
import os
import sys
import json
import struct
import ctypes
from ctypes import wintypes

# ---------------- 常量 ----------------
MODULE_NAME = "granblue_fantasy_relink.exe"

RECORD_BASE_OFF      = 0x15030
SB_NODE_ARRAY_OFF    = 0x138
SB_NODE_ARRAY_COUNT  = 400
SB_NODE_ARRAY_STRIDE = 0x38
EMPTY_SIGIL_HASH     = 0x887AE0B0
SB_CHARID_OFF        = 0x5B10

# CharaPower 全局 RVA 候选（随补丁漂移；2.0.4 优先，2.0.3 次之，2.0.2 末位）
# V2082：2.0.4 下旧候选 0x7c21a38 / 0x7c22cb8 全部失效（BuffMonitor 的 numpy 全模块扫描也找不到，
#   一度怀疑 2.0.4 重构了 CharaPower 结构本身）。
# V2083：研读 relink-logs `src-hook/src/hooks/player.rs` 源码后确认——
#   源码里 `const CHARA_POWER_RVA: usize = 0x7c22f38; // 2.0.4: 0x7c22cb8`
#   即 2.0.4 的真实 RVA 是 **0x7c22f38**（比 2.0.2 的 0x7c22cb8 只漂移 0x80，结构完全没变）。
#   旧候选之所以"找不到"，纯粹是列表里没有这个新值，不是结构变了。
#   附注：2.0.4 的 map 偏移（0x728/0x738/0x750、0x320/0x330/0x348）、节点数组 0x138、
#   charid 0x5B10、actor record 0x15030 全部沿用旧值，无需改动。
CHARA_POWER_RVA_CANDIDATES = [0x7C22F38, 0x7C21A38, 0x7C22CB8]
# 巴恩 charid，功能指纹用
SB_TARGET_CHARID = 0x2EBE91D5

# mgr 内字段偏移
SB_CHAR_MAP_END     = 0x728
SB_CHAR_MAP_BUCKETS = 0x738
SB_CHAR_MAP_MASK    = 0x750
SB_NODE_MAP_END     = 0x320
SB_NODE_MAP_BUCKETS = 0x330
SB_NODE_MAP_MASK    = 0x348
# MSVC unordered_map 节点布局
HM_NODE_NEXT  = 0x08
HM_NODE_KEY   = 0x10
HM_NODE_VALUE = 0x18
# CharaPower 节点 row 布局
NODE_ROW_NODE_ID   = 0x48
NODE_ROW_BIT       = 0x5C
NODE_ROW_EFFECT_ID = 0x74
# char_node 向量布局
CHAR_NODE_BEGIN  = 0x18
CHAR_NODE_END    = 0x20
CHAR_NODE_STRIDE = 8

MASTERY_CAT_LABEL = {"SB_DEF": "觉醒", "SB_ATK": "真谛", "SB_LIMIT": "秘义"}
MASTERY_RANK_THRESH = {"R1": 3, "R2": 6, "R3": 6}
MASTERY_CAT_ORDER = ("SB_DEF", "SB_ATK", "SB_LIMIT")
# 中文 label -> 英文键（与 buff_data_generated 的 awakening/truth/secret 对齐）
LABEL_TO_KEY = {"觉醒": "awakening", "真谛": "truth", "秘义": "secret"}

# ---------------- ctypes 基础 ----------------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPMODULE = 0x0008
TH32CS_SNAPMODULE32 = 0x0010


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("proccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


def _rpm(handle, addr, size):
    buf = ctypes.create_string_buffer(size)
    nread = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(nread))
    if not ok or nread.value != size:
        return None
    return buf.raw


def _read_u32(handle, addr):
    b = _rpm(handle, addr, 4)
    return struct.unpack("<I", b)[0] if b else None


def _read_u64(handle, addr):
    b = _rpm(handle, addr, 8)
    return struct.unpack("<Q", b)[0] if b else None


def _read_ptr(handle, addr):
    return _read_u64(handle, addr)


def _read_u64_safe(handle, addr):
    v = _read_u64(handle, addr)
    return v if v is not None else 0


def _enum_module(pid):
    """返回 (base, size) 或 None。"""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == ctypes.c_void_p(-1).value or not snap:
        return None
    try:
        me = MODULEENTRY32()
        me.dwSize = ctypes.sizeof(me)
        if kernel32.Module32First(snap, ctypes.byref(me)):
            while True:
                mod = me.szModule.decode("ascii", "ignore")
                if mod.lower() == MODULE_NAME.lower():
                    return (me.modBaseAddr or 0, me.modBaseSize or 0)
                if not kernel32.Module32Next(snap, ctypes.byref(me)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return None


# ---------------- 数据文件 ----------------
def _resolve_data(name):
    cands = []
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(os.path.join(here, "assets", name))
    cands.append(os.path.join(here, name))
    mp = getattr(sys, "_MEIPASS", "")
    if mp:
        cands.append(os.path.join(mp, name))
        cands.append(os.path.join(mp, "assets", name))
    cands.append(os.path.join(os.path.dirname(sys.executable), "assets", name))
    cands.append(os.path.join(os.path.dirname(sys.executable), name))
    # 兜底：BuffMonitor 目录
    cands.append(os.path.join(r"E:/zfh/game/GBFR_BuffMonitor", name))
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[0]


def _load_effect_id_class():
    path = _resolve_data("effect_id_class.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        m = {}
        for k, v in raw.items():
            eid = int(k)
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                m[eid] = (v[0], v[1])
        return m
    except Exception:
        return {}


def _load_mastery_map():
    path = _resolve_data("skillboard_map.json")
    m = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for h, v in raw.items():
            key = int(h, 16) if isinstance(h, str) else int(h)
            if isinstance(v, dict):
                m[key] = (v.get("cat"), v.get("rank"))
            elif isinstance(v, (list, tuple)) and len(v) >= 2:
                m[key] = (v[0], v[1])
    except Exception:
        pass
    return m


# ---------------- 读取器 ----------------
class MasteryReader:
    def __init__(self, handle, pid):
        self.handle = handle
        self.pid = pid
        ms = _enum_module(pid)
        self.mod_base = ms[0] if ms else 0
        self.mod_size = ms[1] if ms else 0
        self._cp_ok = False
        self._cp_rva_used = 0
        self._cp_mgr = 0
        self._cp_node_end = self._cp_node_buckets = self._cp_node_mask = 0
        self._cp_char_end = self._cp_char_buckets = self._cp_char_mask = 0
        self._cp_keys_cache = {}
        self._eclass = None
        self._mastery_hashes = None
        self._tried_cp = False

    @classmethod
    def from_existing(cls, handle, mod_base, mod_size):
        """用主程序已解析好的模块基址/大小构造，避免重复枚举。"""
        obj = cls.__new__(cls)
        obj.handle = handle
        obj.pid = 0
        obj.mod_base = mod_base or 0
        obj.mod_size = mod_size or 0
        obj._cp_ok = False
        obj._cp_rva_used = 0
        obj._cp_mgr = 0
        obj._cp_node_end = obj._cp_node_buckets = obj._cp_node_mask = 0
        obj._cp_char_end = obj._cp_char_buckets = obj._cp_char_mask = 0
        obj._cp_keys_cache = {}
        obj._eclass = None
        obj._mastery_hashes = None
        obj._tried_cp = False
        return obj

    # ---- 内存读取薄封装 ----
    def _u32(self, addr):
        return _read_u32(self.handle, addr)

    def _u64(self, addr):
        return _read_u64(self.handle, addr)

    def _ptr(self, addr):
        return _read_ptr(self.handle, addr)

    def _bytes(self, addr, size):
        return _rpm(self.handle, addr, size)

    # ---- 数据表 ----
    def effect_id_class(self):
        if self._eclass is None:
            self._eclass = _load_effect_id_class()
        return self._eclass

    def mastery_hashes(self):
        if self._mastery_hashes is None:
            self._mastery_hashes = _load_mastery_map()
        return self._mastery_hashes

    # ---- CharaPower 全局探测 ----
    def ensure_charapower(self):
        if self._tried_cp:
            return self._cp_ok
        self._tried_cp = True
        self._cp_ok = False
        if not self.mod_base or not self.mod_size or self.mod_size < 0x100000:
            return False
        # 1) 候选 RVA 优先（极快）
        for rva in CHARA_POWER_RVA_CANDIDATES:
            mgr, meta = self._probe_at_rva(self.mod_base, rva)
            if meta and meta["ok"]:
                self._adopt(rva, mgr, meta)
                return True
        try:
            import numpy as _np
        except Exception:
            return False
        CHUNK = 0x1000000  # 16MB
        lo_heap, hi_heap = 0x10000, 0x7FFFFFFFFFFF
        img_lo, img_hi = self.mod_base, self.mod_base + self.mod_size
        import time
        deadline = time.time() + 35.0
        for coff in range(0, self.mod_size - 0x800, CHUNK):
            try:
                chunk = self._bytes(self.mod_base + coff, min(CHUNK, self.mod_size - coff))
            except Exception:
                continue
            if not chunk:
                continue
            arr = _np.frombuffer(chunk, dtype=_np.uint64)
            is_ptr = (arr >= lo_heap) & (arr <= hi_heap)
            is_heap = (arr < img_lo) | (arr > img_hi)
            cand = _np.nonzero(is_ptr & is_heap)[0]
            for j in cand.tolist():
                rva = coff + int(j) * 8
                mgr, meta = self._probe_at_rva(self.mod_base, rva)
                if meta and meta.get("ok"):
                    self._adopt(rva, mgr, meta)
                    return True
            if time.time() > deadline:
                break
        return False

    def _probe_at_rva(self, base, rva):
        meta = {"ok": False, "ne": 0, "nb": 0, "nm": 0, "ce": 0, "cb": 0, "cm": 0}
        try:
            mgr = self._ptr(base + rva)
            if not mgr or mgr < 0x10000:
                return mgr, meta
            ne = self._ptr(mgr + SB_NODE_MAP_END)
            nb = self._ptr(mgr + SB_NODE_MAP_BUCKETS)
            nm = self._u64(mgr + SB_NODE_MAP_MASK) & 0xFFFFFFFF
            ce = self._ptr(mgr + SB_CHAR_MAP_END)
            cb = self._ptr(mgr + SB_CHAR_MAP_BUCKETS)
            cm = self._u64(mgr + SB_CHAR_MAP_MASK) & 0xFFFFFFFF
            meta.update(ne=ne or 0, nb=nb or 0, nm=nm or 0, ce=ce or 0, cb=cb or 0, cm=cm or 0)
            mask_ok_n = nm > 0 and (nm & (nm + 1)) == 0
            mask_ok_c = cm > 0 and (cm & (cm + 1)) == 0
            ptrs_valid = all(0x10000 <= p <= 0x7FFFFFFFFFFF for p in (ne, nb, ce, cb) if p)
            ptrs_distinct = len({ne, nb, ce, cb}) == 4
            meta["ok"] = (all(meta[k] for k in ("ne", "nb", "nm", "ce", "cb", "cm"))
                          and mask_ok_n and mask_ok_c and nm >= 0x7F and cm >= 0x7F
                          and ptrs_valid and ptrs_distinct)
        except Exception:
            pass
        return mgr, meta

    def _adopt(self, rva, mgr, meta):
        self._cp_mgr = mgr
        self._cp_rva_used = rva
        self._cp_node_end, self._cp_node_buckets, self._cp_node_mask = meta["ne"], meta["nb"], meta["nm"]
        self._cp_char_end, self._cp_char_buckets, self._cp_char_mask = meta["ce"], meta["cb"], meta["cm"]
        self._cp_ok = True

    def _walk_bucket(self, which, key):
        try:
            if which == "char":
                end, buckets, mask = self._cp_char_end, self._cp_char_buckets, self._cp_char_mask
            else:
                end, buckets, mask = self._cp_node_end, self._cp_node_buckets, self._cp_node_mask
            if not buckets or not mask:
                return 0
            bucket = (key & mask) * 0x10
            bucket_head = self._ptr(buckets + bucket)
            node_ptr = self._ptr(buckets + bucket + 8)
            seen = 0
            while node_ptr and node_ptr != end and seen < 64:
                seen += 1
                k = self._u32(node_ptr + HM_NODE_KEY)
                if k == key:
                    return node_ptr
                if node_ptr == bucket_head:
                    return 0
                node_ptr = self._ptr(node_ptr + HM_NODE_NEXT)
        except Exception:
            pass
        return 0

    def _lookup_char_keys(self, charid):
        node_ptr = self._walk_bucket("char", charid)
        if not node_ptr:
            return []
        begin = self._ptr(node_ptr + CHAR_NODE_BEGIN)
        endp = self._ptr(node_ptr + CHAR_NODE_END)
        if not begin or not endp or endp <= begin:
            return []
        n = (endp - begin) // CHAR_NODE_STRIDE
        keys = []
        for i in range(min(n, 512)):
            kk = self._u32(begin + i * CHAR_NODE_STRIDE)
            if kk:
                keys.append(kk)
        return keys

    def _lookup_node(self, key):
        node_ptr = self._walk_bucket("node", key)
        if not node_ptr:
            return None
        row = self._ptr(node_ptr + HM_NODE_VALUE)
        if not row or row <= 0x10000:
            return None
        node_id = self._u32(row + NODE_ROW_NODE_ID)
        bit = self._u32(row + NODE_ROW_BIT)
        effect_id = self._u32(row + NODE_ROW_EFFECT_ID)
        return (node_id, bit, effect_id)

    def _best_char_keys(self, unlock_set):
        best, best_overlap = [], 0
        try:
            for b in range(self._cp_char_mask + 1):
                node_ptr = self._ptr(self._cp_char_buckets + b * 0x10 + 8)
                seen = 0
                while node_ptr and node_ptr != self._cp_char_end and seen < 256:
                    seen += 1
                    begin = self._ptr(node_ptr + CHAR_NODE_BEGIN)
                    endp = self._ptr(node_ptr + CHAR_NODE_END)
                    nxt = self._ptr(node_ptr + HM_NODE_NEXT)
                    if begin and endp and endp > begin:
                        n = (endp - begin) // CHAR_NODE_STRIDE
                        overlap, keys = 0, []
                        for i in range(min(n, 512)):
                            kk = self._u32(begin + i * CHAR_NODE_STRIDE)
                            if not kk:
                                continue
                            keys.append(kk)
                            ri = self._lookup_node(kk)
                            if ri and ri[0] in unlock_set:
                                overlap += 1
                        if overlap > best_overlap:
                            best_overlap, best = overlap, keys
                    node_ptr = nxt
        except Exception:
            pass
        if best_overlap >= max(5, len(unlock_set) // 4):
            return best
        return []

    # ---- 技能板读取 ----
    def read_skillboard(self, actor):
        """返回详细 dict（同 BuffMonitor 结构）。"""
        res = {"found": False, "count": 0, "valid": False, "note": "",
               "counts": {c: {"R1": 0, "R2": 0, "R3": 0, "EX": 0} for c in MASTERY_CAT_LABEL},
               "cat_ranks": {c: 0 for c in MASTERY_CAT_LABEL},
               "top_rank": 0, "top_cat": None, "top_cat_label": None, "top_key": None}
        if not actor:
            return res
        record = actor + RECORD_BASE_OFF
        try:
            arr = self._bytes(record + SB_NODE_ARRAY_OFF, SB_NODE_ARRAY_COUNT * SB_NODE_ARRAY_STRIDE)
        except Exception:
            arr = None
        if not arr:
            res["note"] = "节点数组读取失败"
            return res
        unlock = {}
        for i in range(SB_NODE_ARRAY_COUNT):
            off = i * SB_NODE_ARRAY_STRIDE
            if off + 8 > len(arr):
                break
            nid = struct.unpack_from("<I", arr, off)[0]
            if nid == 0 or nid == EMPTY_SIGIL_HASH:
                continue
            bits = struct.unpack_from("<I", arr, off + 4)[0]
            unlock[nid] = bits
        res["count"] = len(unlock)
        if not unlock:
            res["note"] = "节点数组为空"
            return res
        charid = self._u32(record + SB_CHARID_OFF) or 0
        keys = None
        if charid:
            keys = self._cp_keys_cache.get(charid)
            if keys is None:
                if self.ensure_charapower():
                    keys = self._lookup_char_keys(charid)
                    if not keys:
                        keys = self._best_char_keys(unlock.keys())
                self._cp_keys_cache[charid] = keys if keys is not None else []
        if not keys and self.ensure_charapower():
            keys = self._best_char_keys(unlock.keys())
        unlocked = []
        if keys:
            for k in keys:
                ri = self._lookup_node(k)
                if not ri:
                    continue
                node_id, bit, effect_id = ri
                if effect_id is None:
                    continue
                if effect_id < 10 or (100 <= effect_id < 110) or (200 <= effect_id < 210):
                    continue
                if bit is None or bit > 0x1F:
                    continue
                b = unlock.get(node_id)
                if b is not None and ((b >> bit) & 1):
                    unlocked.append((node_id, effect_id))
            if unlocked:
                res["found"] = True
                res["valid"] = True
        # 兜底：直接对 skillboard_map.json
        if not res["found"]:
            mh = self.mastery_hashes()
            mapped = [nid for nid in unlock if mh.get(nid)]
            if len(mapped) >= max(3, res["count"] // 3):
                res["found"] = True
                res["valid"] = True
                for nid in mapped:
                    unlocked.append((nid, 0))
        eclass = self.effect_id_class()
        unmapped = 0
        for nid, eid in unlocked:
            if not eid:
                unmapped += 1
                continue
            info = eclass.get(eid)
            if info and info[0] in MASTERY_CAT_LABEL and info[1] in ("R1", "R2", "R3", "EX"):
                res["counts"][info[0]][info[1]] += 1
            else:
                unmapped += 1
        # 每类激活阶位
        cat_ranks = {c: 0 for c in MASTERY_CAT_LABEL}
        for cat, c in res["counts"].items():
            rank = 0
            if c.get("R1", 0) >= MASTERY_RANK_THRESH["R1"]:
                rank = 1
                if c.get("R2", 0) >= MASTERY_RANK_THRESH["R2"]:
                    rank = 2
                    if c.get("R3", 0) >= MASTERY_RANK_THRESH["R3"]:
                        rank = 3
            cat_ranks[cat] = rank
        res["cat_ranks"] = cat_ranks
        top_rank = max(cat_ranks.values()) if cat_ranks else 0
        # 最高专精判定：默认取「阶位最高」的类别；但这并不要求该树必须满到 3 阶——
        # 1 阶 / 2 阶 / 3 阶 都会被正常判定为当前专精（用于 buff 门控与标题栏）。
        # 若三个类别都未达 1 阶（角色特地只点了几颗、甚至完全不点满 3 阶），
        # 则退化为按「实际已点节点总数」最多的类别来挑最高的那棵树，保证总能判定出专精。
        top_cat = None
        top_label = None
        cat_total = {c: sum(res["counts"][c].values()) for c in MASTERY_CAT_LABEL}
        if top_rank > 0:
            for cat in MASTERY_CAT_ORDER:
                if cat_ranks.get(cat, 0) == top_rank:
                    top_cat = cat
                    break
        else:
            best_total = 0
            for cat in MASTERY_CAT_ORDER:
                t = cat_total.get(cat, 0)
                if t > best_total:
                    best_total = t
                    top_cat = cat
        if top_cat is not None:
            top_label = MASTERY_CAT_LABEL.get(top_cat)
        res["top_rank"] = top_rank
        res["top_cat"] = top_cat
        res["top_cat_label"] = top_label
        res["top_key"] = LABEL_TO_KEY.get(top_label) if top_label else None
        # 合理性校验
        caps = {"R1": 10, "R2": 10, "R3": 10, "EX": 20}
        total = 0
        oob = False
        for cat, rc in res["counts"].items():
            for rk, n in rc.items():
                if n < 0 or n > caps[rk]:
                    oob = True
                total += n
        if total > 50 or oob or unmapped > len(unlocked):
            res["found"] = False
            res["valid"] = False
            res["note"] = "计数越界 total=%d unmapped=%d" % (total, unmapped)
            res["top_key"] = None
        return res

    def read_top_mastery(self, actor):
        """返回 'awakening'/'truth'/'secret'/None。None=未判定（降级，调用方应视为常显）。"""
        try:
            r = self.read_skillboard(actor)
        except Exception:
            return None
        if not r.get("valid"):
            return None
        return r.get("top_key")


if __name__ == "__main__":
    # 离线自检：打印数据表加载情况
    print("effect_id_class 条目:", len(_load_effect_id_class()))
    print("mastery_hashes 条目:", len(_load_mastery_map()))
