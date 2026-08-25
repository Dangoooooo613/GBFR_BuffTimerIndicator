# -*- coding: utf-8 -*-
"""
角色 / Buff / 专精 三语数据
=========================
本文件不再内嵌大段数据，改为从 i18n_loader 载入（数据源 = 同目录 i18n.json）。
对外暴露的结构保持不变，原 `from buff_data_generated import BUFF_PROFILES,
CHAR_NAMES, MASTERY_BRANCHES` 的所有调用点无需改动。

i18n.json 才是唯一真源：要增删 Buff / 角色名 / 专精名 / UI 译文，直接编辑 i18n.json
后用 build 脚本重新打包即可。
"""
from i18n_loader import BUFF_PROFILES, CHAR_NAMES, MASTERY_BRANCHES, UI_TRANS, SCHEMA
