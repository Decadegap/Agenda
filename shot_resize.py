# -*- coding: utf-8 -*-
"""缩放截图工具：在多个窗口尺寸下渲染关键页面，输出到 C:\\temp\\ag_resize"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from datetime import datetime, timedelta
import db as DB
from main import Canvas

out = sys.argv[1] if len(sys.argv) > 1 else r"C:\temp\ag_resize"
os.makedirs(out, exist_ok=True)

DB.init_db()
with DB._connect() as c:
    c.execute("DELETE FROM tasks")
    c.execute("DELETE FROM notes")

app = QApplication(sys.argv)

nid = DB.create_note("任务一（例子）")
DB.create_note("任务二（例子）")
DB.create_note("学习计划（例子）")
DB.create_note("健身打卡（例子）")
DB.create_task(nid, "背单词", "背 100 个单词", datetime.now() + timedelta(days=2, hours=5))
DB.create_task(nid, "写周报", "写本周周报并同步给组员", datetime.now() - timedelta(days=1, hours=3))
tid = DB.create_task(nid, "改简历", "按岗位要求修改简历", datetime.now() + timedelta(hours=6))
DB.set_delay(tid, 2 * 3600 + 30 * 60)
DB.create_note("会议记录")
DB.create_note("读书笔记")

c = Canvas()
c.show()


def snap(name, w, h, prep=None):
    c.resize(w, h)
    app.processEvents()
    if prep:
        prep()
    app.processEvents()
    c.grab().save(os.path.join(out, name + ".png"))
    print("saved", name, f"{w}x{h}")


# 便签列表（3列 / 2列 / 1列）
snap("01_notes_1280", 1280, 720, lambda: (setattr(c, "page", "notes"), c.refresh()))
snap("02_notes_1000", 1000, 650, lambda: (setattr(c, "page", "notes"), c.refresh()))
snap("03_notes_760", 760, 600, lambda: (setattr(c, "page", "notes"), c.refresh()))
snap("04_notes_1920", 1920, 1080, lambda: (setattr(c, "page", "notes"), c.refresh()))

# 详情页
def detail():
    c.page = "detail"
    c.note_id = nid
    c.refresh()


snap("05_detail_1280", 1280, 720, detail)
snap("06_detail_760", 760, 600, detail)


# 统计页
snap("07_stats_1280", 1280, 720, lambda: (setattr(c, "page", "stats"), c.refresh()))
snap("08_stats_1920", 1920, 1080, lambda: (setattr(c, "page", "stats"), c.refresh()))
snap("09_stats_900", 900, 600, lambda: (setattr(c, "page", "stats"), c.refresh()))


# 创建事务弹窗（矮窗口可滚动）
def task_dlg():
    c.page = "detail"
    c.note_id = nid
    c.open_task_dialog()


snap("10_dlg_task_1280", 1280, 720, task_dlg)
snap("11_dlg_task_900", 900, 600, task_dlg)
snap("12_dlg_task_760", 760, 600, task_dlg)


# 延期弹窗
def delay_dlg():
    c.page = "detail"
    c.note_id = nid
    c.open_delay_dialog(tid)


snap("13_dlg_delay_1280", 1280, 720, delay_dlg)
snap("14_dlg_delay_900", 900, 600, delay_dlg)

# 空状态
with DB._connect() as cn:
    cn.execute("DELETE FROM tasks")
    cn.execute("DELETE FROM notes")
snap("15_empty_1280", 1280, 720, lambda: (setattr(c, "page", "notes"), c.refresh()))
snap("16_empty_760", 760, 600, lambda: (setattr(c, "page", "notes"), c.refresh()))

print("done ->", out)
