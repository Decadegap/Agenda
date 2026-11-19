# -*- coding: utf-8 -*-
"""Agenda 设置模块：设置项持久化 + 桌面实体便签同步。

设置以 JSON 存在 %APPDATA%\\Agenda\\settings.json。

桌面实体便签（sticky）：
    每一个便签（note）在桌面上就是一张「实体便签」小窗，
    上面直接写事务内容与倒计时，随数据库变化自动刷新。
"""
import json
import os
import shutil
import sys

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Agenda")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

# ---- 便签皮肤（未来可扩展为皮肤系统）----
SKINS = {
    "classic": {
        "label": "经典黄",
        "paper": "#FFF7A6",
        "paper_edge": "#F0E39A",
        "clip": "#3A3F47",
        "ink": "#2B2B26",
        "ink_soft": "#6E6A55",
        "accent": "#D94F4F",
    },
    "mint": {
        "label": "薄荷绿",
        "paper": "#D6F2E3",
        "paper_edge": "#B9E3CF",
        "clip": "#2F5D50",
        "ink": "#22352E",
        "ink_soft": "#5C7C71",
        "accent": "#2E9E68",
    },
    "blush": {
        "label": "樱花粉",
        "paper": "#FFE0E6",
        "paper_edge": "#F6C6D0",
        "clip": "#7A4550",
        "ink": "#3A262B",
        "ink_soft": "#8A6670",
        "accent": "#D93B40",
    },
    "sky": {
        "label": "天青蓝",
        "paper": "#DCEBFA",
        "paper_edge": "#BCD5EF",
        "clip": "#2E4A68",
        "ink": "#1F2C38",
        "ink_soft": "#5E7288",
        "accent": "#4874CB",
    },
    "graphite": {
        "label": "石墨灰",
        "paper": "#EDEFF2",
        "paper_edge": "#D5D9DF",
        "clip": "#2B2F36",
        "ink": "#1B1D21",
        "ink_soft": "#5F6670",
        "accent": "#4874CB",
    },
}

DEFAULTS = {
    "desktop_sticky": False,   # 是否在桌面显示实体便签
    "skin": "classic",          # 便签皮肤
    "sticky_size": 220,         # 实体便签宽度（px）
    "sticky_opacity": 1.0,      # 实体便签不透明度 0.3~1.0
    "sticky_show_ddl": True,    # 实体便签上显示 DDL
    "sticky_click_through": False,  # 点击穿透（鼠标穿透，不接收点击）
}

VALID = {
    "skin": lambda v: v in SKINS,
    "sticky_size": lambda v: 160 <= int(v) <= 420,
    "sticky_opacity": lambda v: 0.3 <= float(v) <= 1.0,
    "desktop_sticky": lambda v: bool(v),
    "sticky_show_ddl": lambda v: bool(v),
    "sticky_click_through": lambda v: bool(v),
}


def _ensure_dir():
    os.makedirs(APP_DIR, exist_ok=True)


def load():
    """读取设置（缺项用默认值，非法值回退默认）"""
    data = dict(DEFAULTS)
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                if k in DEFAULTS and VALID[k](v):
                    data[k] = v
    except Exception:
        pass
    return data


def save(data):
    """保存设置（只保存合法项）"""
    _ensure_dir()
    clean = {}
    for k, v in data.items():
        if k in DEFAULTS and VALID[k](v):
            clean[k] = v
    clean.setdefault("skin", DEFAULTS["skin"])
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_PATH)
    return clean


def get(key, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def set_value(key, value):
    """更新单项设置并保存，返回更新后的完整设置"""
    data = load()
    if key not in DEFAULTS:
        return data
    if not VALID[key](value):
        return data
    data[key] = value
    return save(data)


def skin():
    """当前皮肤配置"""
    return SKINS.get(get("skin"), SKINS["classic"])


# ------------------------------------------------------------------
# 桌面实体便签
# ------------------------------------------------------------------
def sticky_script_path():
    return os.path.join(APP_DIR, "sticky_view.py")


def desktop_dir():
    """实体便签的落盘目录（存到 APPDATA，避免污染桌面）"""
    return os.path.join(APP_DIR, "stickies")


def write_sticky_view():
    """把实体便签的渲染脚本写到 APPDATA，由独立进程加载。

    这样主程序 exe 打包时不会把渲染脚本漏进 PyInstaller 的静态资源，
    也方便用户以后替换成自己的皮肤实现。
    """
    _ensure_dir()
    path = sticky_script_path()
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sticky_view.py")
    if os.path.exists(src):
        shutil.copyfile(src, path)
    return path
