# -*- coding: utf-8 -*-
"""生成设置弹窗 + 桌面实体便签的验收截图"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

import db as DB
import settings as S
import main as M

OUT = r"C:\temp\ag_settings"
os.makedirs(OUT, exist_ok=True)


def main():
    app = QApplication.instance() or QApplication([])
    DB.init_db()

    # 准备演示数据
    with DB._connect() as c:
        c.execute("DELETE FROM tasks")
        c.execute("DELETE FROM notes")
    n1 = DB.create_note("考研复习")
    DB.create_task(n1, "背单词", "背 200 个考研词汇", datetime.now() + timedelta(days=3))
    DB.create_task(n1, "刷真题", "做一套 2020 真题", datetime.now() + timedelta(hours=5))
    DB.create_task(n1, "英语作文", "背一篇高分范文", datetime.now() - timedelta(hours=2))
    n2 = DB.create_note("项目跟进")
    DB.create_task(n2, "对接需求", "和客户确认 v2 方案范围", datetime.now() + timedelta(days=1))

    # 1. 设置弹窗
    c = M.Canvas()
    c.resize(1280, 720)
    c.show()
    app.processEvents()
    c.open_settings()
    app.processEvents()
    c.grab().save(os.path.join(OUT, "01_settings.png"))

    # 2. 设置弹窗 - 选了薄荷绿皮肤
    c.setting_draft["skin"] = "mint"
    c.setting_size_val = 300
    c.setting_opacity_val = 0.85
    c.update()
    app.processEvents()
    c.grab().save(os.path.join(OUT, "02_settings_mint.png"))

    # 3. 头部齿轮按钮
    c.close_overlay()
    app.processEvents()
    c.grab().save(os.path.join(OUT, "03_header_gear.png"))

    # 4. 各皮肤实体便签
    from sticky_view import StickyWindow
    for key, sk in S.SKINS.items():
        S.set_value("skin", key)
        w = StickyWindow(n1)
        w.show()
        app.processEvents()
        w.grab().save(os.path.join(OUT, f"04_sticky_{key}.png"))
        w.close()

    S.set_value("skin", "classic")

    # 5. 宽便签
    S.set_value("sticky_size", 340)
    w = StickyWindow(n1)
    w.show()
    app.processEvents()
    w.grab().save(os.path.join(OUT, "05_sticky_wide.png"))
    w.close()
    S.set_value("sticky_size", 220)

    print("screenshots ->", OUT)
    for f in sorted(os.listdir(OUT)):
        print("  ", f, os.path.getsize(os.path.join(OUT, f)))


if __name__ == "__main__":
    main()
