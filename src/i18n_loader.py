# -*- coding: utf-8 -*-
"""
GBFR CooldownIndicator —— 三语单一真源载入器
=============================================
所有「应用自维护」的三语数据（角色名 / Buff / 专精分支 / UI 自译串）
统一存放在同目录的 i18n.json，本模块负责：

  1. 定位 i18n.json（单 exe 运行时在 sys._MEIPASS；开发时在脚本目录）；
  2. 载入 JSON；
  3. 暴露给全程序使用的四个对象：
       BUFF_PROFILES     角色专属 Buff（与旧 buff_data_generated 结构一致）
       CHAR_NAMES        角色三语名
       MASTERY_BRANCHES  每角色三系专精列名（三语）
       UI_TRANS          UI 自译串查找表 {简中: {zh_tw, en}}（供 _tr 使用）

这样三语数据不再散落在多个 .py 字典里，增减只需编辑 i18n.json。
"""
import os
import sys
import json

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_i18n():
    """按优先级查找 i18n.json：onefile 解压目录 -> 脚本目录 -> 项目根。"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "i18n.json"))
    candidates.append(os.path.join(_HERE, "i18n.json"))
    candidates.append(os.path.join(os.path.dirname(_HERE), "i18n.json"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError("i18n.json 未找到，候选路径: " + str(candidates))


def load_i18n():
    with open(_find_i18n(), encoding="utf-8") as f:
        return json.load(f)


_DATA = load_i18n()

# ---- 角色专属 Buff（保持 {"PLxxxx": {"buffs": [...]}} 结构）----
BUFF_PROFILES = {pl: {"buffs": buffs} for pl, buffs in _DATA.get("buffs", {}).items()}

# ---- 角色三语名 ----
CHAR_NAMES = _DATA.get("chars", {})

# ---- 每角色三系专精列名 ----
MASTERY_BRANCHES = _DATA.get("mastery", {})

# ---- UI 自译串查找表（供 _tr 使用）----
UI_TRANS = _DATA.get("ui", {})

# ---- 版本 schema（与 APP 设置兼容，读取即用）----
SCHEMA = _DATA.get("meta", {}).get("schema", 89)
