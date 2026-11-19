# -*- coding: utf-8 -*-
"""离屏渲染截图工具：python shot.py [输出目录]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from datetime import datetime, timedelta
import db as DB
from main import Canvas, W, H, month_grid

out = sys.argv[1] if len(sys.argv) > 1 else r"C:\temp\ag_shots2"
os.makedirs(out, exist_ok=True)

DB.init_db()
with DB._connect() as c:
    c.execute("DELETE FROM tasks")
    c.execute("DELETE FROM notes")

app = QApplication(sys.argv)


def shot(canvas, name):
    canvas.resize(W, H)
    canvas.show()
    app.processEvents()
    canvas.grab().save(os.path.join(out, name + ".png"))
    print("saved", name)


c = Canvas()
shot(c, "01_empty")           # 空状态

nid = DB.create_note("任务一（例子）")
DB.create_note("任务二（例子）")
DB.create_task(nid, "背单词", "背 100 个单词", datetime.now() + timedelta(days=2, hours=5))
DB.create_task(nid, "写周报", "写本周周报并同步给组员", datetime.now() - timedelta(days=1, hours=3))
tid_late = DB.create_task(nid, "改简历", "按岗位要求修改简历", datetime.now() + timedelta(hours=6))
DB.set_delay(tid_late, 2 * 3600 + 30 * 60)
# 造几条已结束的事务，让「已完成/延期/放弃」分类页有内容
tid_done = DB.create_task(nid, "已完成的任务", "示例：按时完成", datetime.now() + timedelta(days=1))
DB.complete_task(tid_done)
tid_over = DB.create_task(nid, "超时的任务", "示例：超时后完成", datetime.now() - timedelta(days=1))
DB.complete_task(tid_over)
tid_ab = DB.create_task(nid, "放弃的任务", "示例：已取消", datetime.now() + timedelta(days=1))
DB.cancel_task(tid_ab)
c.refresh()
shot(c, "02_notes")

c.overlay = "note_create"
shot(c, "03_dlg_note")
c.close_overlay()

c.page = "detail"
c.note_id = nid
c.refresh()
shot(c, "04_detail")

c.menu = ("note", nid)
c.menu_pos = (c.content_rect().left() + c.content_rect().width() - 152, c.content_rect().top() + 30)
shot(c, "04b_menu")
c.menu = None

c.page = "notes"
c.page = "done"
c.tab = 1
c.refresh()
shot(c, "05_done")
c.tab = 2
c.refresh()
shot(c, "06_delayed")
c.tab = 3
c.refresh()
shot(c, "07_abandoned")

c.page = "stats"
shot(c, "08_stats")

c.page = "detail"
c.note_id = nid
c.open_task_dialog()
# 演示：用滑条选到 22:45
c.pick_hour = 22
c.pick_minute = 45
c.ddl_date = c.ddl_date.replace(hour=22, minute=45, second=0, microsecond=0)
c.update()
shot(c, "09_dlg_task")
c.close_overlay()

# DDL 错误提示态（真实模拟：点击一个过去的日期）
c.open_task_dialog()
app.processEvents()
g = c.ddl_rects()
now = datetime.now()
c.cal_year, c.cal_month = now.year, now.month
grid = month_grid(c.cal_year, c.cal_month)
cell_w = (g["bw"] - 24) / 7
target = now.day - 1 if now.day > 1 else 1
for ri, row in enumerate(grid):
    if target in row:
        ci = row.index(target)
        x = g["bx"] + 12 + ci * cell_w + (cell_w - 4) / 2
        y = g["cal_y"] + 56 + ri * 24 + 11
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        c.mousePressEvent(ev)
        app.processEvents()
        break
shot(c, "11_ddl_error")
c.close_overlay()

# 延时弹窗
tid_d = DB.create_task(nid, "要延期的任务", "内容", datetime.now() + timedelta(hours=1))
DB.set_delay(tid_d, 2 * 3600)
c.open_delay_dialog(tid_d)
c.delay_added = 86400
shot(c, "10_dlg_delay")
c.close_overlay()

# 记录管理模式：便签 tab
c.page = "notes"
c.tab = 0
c.manage = False
c.manage_tab = None
c.manage_sel = set()
c.refresh()
c.enter_manage()
shot(c, "12_manage_notes")
# 勾选第一项
rows = getattr(c, "manage_row_rects", [])
if rows:
    r = rows[0][1]
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(r.left() + 30, r.center().y()),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    c.mousePressEvent(ev)
    app.processEvents()
shot(c, "13_manage_sel")
c.manage = False
c.manage_tab = None
c.manage_sel = set()

# 记录管理模式：已完成 tab
c.page = "done"
c.tab = 1
c.refresh()
c.enter_manage()
shot(c, "14_manage_done")
c.manage = False
c.manage_tab = None
c.manage_sel = set()

# 记录管理模式：统计 tab
c.page = "stats"
c.tab = 4
c.refresh()
c.enter_manage()
shot(c, "15_manage_stats")
c.manage = False
c.manage_tab = None
c.manage_sel = set()

# 归档事务保留验证：取缔便签后，已完成/延期/放弃 tab 仍显示这些记录
nid_keep = DB.create_note("即将取罪的便签")
DB.create_task(nid_keep, "保留的已完成事务", "示例", datetime.now()+timedelta(days=1))
DB.complete_task(DB.list_tasks(note_id=nid_keep)[0]["id"])
DB.create_task(nid_keep, "会被一起删的待办", "示例", datetime.now()+timedelta(days=1))
DB.delete_note(nid_keep)
c.page = "done"
c.tab = 1
c.refresh()
app.processEvents()
print("  取罪后已完成 tab 记录数 =", len(c.tasks))
shot(c, "16_archive_kept")
c.tab = 0
c.page = "notes"
c.refresh()
print("done")


