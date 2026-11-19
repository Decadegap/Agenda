# -*- coding: utf-8 -*-
"""端到端自检：在 UI 里取缔便签后，未完成事务被清除，已归档事务保留在分类页"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent

import db as DB
from main import Canvas

DB.init_db()
with DB._connect() as c:
    c.execute("DELETE FROM tasks")
    c.execute("DELETE FROM notes")

app = QApplication(sys.argv)
nid = DB.create_note("待删便签")
DB.create_task(nid, "按时完成", "内容", datetime.now() + timedelta(days=1))
DB.create_task(nid, "超时完成", "内容", datetime.now() - timedelta(days=1))
DB.create_task(nid, "取消", "内容", datetime.now() + timedelta(days=1))
DB.create_task(nid, "未完成", "内容", datetime.now() + timedelta(days=1))

tids = DB.list_tasks(note_id=nid)
for t in tids:
    if t["name"] == "按时完成":
        DB.complete_task(t["id"])
    elif t["name"] == "超时完成":
        DB.complete_task(t["id"])
    elif t["name"] == "取消":
        DB.cancel_task(t["id"])

print("删除前：done=%d delayed=%d abandoned=%d pending=%d" % (
    len(DB.list_tasks_with_note(status=DB.STATUS_DONE)),
    len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED)),
    len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED)),
    len(DB.list_tasks(note_id=nid, only_pending=True))))

c = Canvas()
c.resize(1280, 720)
c.show()
app.processEvents()

ok = True


def check(label, cond):
    global ok
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        ok = False


def click(x, y):
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    c.mousePressEvent(ev)
    app.processEvents()


# 便签卡片三点 -> 取缔 -> 确认
cr = c.content_rect()
cw = (cr.width() - 18) / 3
click(cr.left() + cw - 88 + 30, cr.top() + 8 + 14)
check("便签菜单已打开", c.menu == ("note", nid))
mx, my = c.menu_pos
click(mx + 20, my + 4 + 40 + 20)   # 第二项：取缔
check("弹出确认框", c.overlay == "confirm")
click(W_C := 1280 / 2 + 158, 720 / 2 + 28)   # 确定
check("便签已从数据库删除", DB.get_note(nid) is None)

print("删除后：done=%d delayed=%d abandoned=%d" % (
    len(DB.list_tasks_with_note(status=DB.STATUS_DONE)),
    len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED)),
    len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED))))

check("已完成分类页保留该便签的事务", len(DB.list_tasks_with_note(status=DB.STATUS_DONE)) == 1)
check("延期分类页保留该便签的事务", len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED)) == 1)
check("放弃分类页保留该便签的事务", len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED)) == 1)
check("统计中仍计入这些归档事务", DB.stats()["total"] == 3)
check("未完成事务已清除", len(DB.list_tasks(status=DB.STATUS_PENDING)) == 0)

# 分类页渲染时仍应显示
for tab, st in ((1, DB.STATUS_DONE), (2, DB.STATUS_DELAYED), (3, DB.STATUS_ABANDONED)):
    c.tab = tab
    c.page = "done"
    c.refresh()
    app.processEvents()
    check(f"分类页 tab{tab} 仍显示归档事务", len(c.tasks) == 1)

with DB._connect() as conn:
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM notes")

print("全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)
