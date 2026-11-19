# -*- coding: utf-8 -*-
"""记录管理 + 取缔语义回归自检

覆盖：
 A. 取缔便签后，已转入「已完成/延期/放弃」tab 的事务**保留**（不随便签删除）
 B. 未完成事务随便签一起删除
 C. 归档事务仍显示在分类页并计入统计
 D. 每个 tab 的「管理」按钮：进入管理模式、勾选、批量删除
 E. 管理模式在便签 tab 删除便签 -> 未完成事务清掉，归档事务保留
 F. 分类 tab 管理模式删除单条事务
"""
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


def clear_db():
    with DB._connect() as conn:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM notes")


def make_note_with_tasks(name):
    """建便签 + 4 条事务，分别落到 pending/done/delayed/abandoned"""
    nid = DB.create_note(name)
    t_done = DB.create_task(nid, "按时完成", "c", datetime.now() + timedelta(days=1))
    t_over = DB.create_task(nid, "超时完成", "c", datetime.now() - timedelta(days=1))
    t_ab = DB.create_task(nid, "取消", "c", datetime.now() + timedelta(days=1))
    t_pend = DB.create_task(nid, "未完成", "c", datetime.now() + timedelta(days=1))
    DB.complete_task(t_done)
    DB.complete_task(t_over)
    DB.cancel_task(t_ab)
    return nid, [t_done, t_over, t_ab, t_pend]


def counts():
    return (len(DB.list_tasks_with_note(status=DB.STATUS_DONE)),
            len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED)),
            len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED)),
            len(DB.list_tasks(status=DB.STATUS_PENDING)))


print("=== A. 取缔便签：归档事务保留，未完成事务删除 ===")
nid, tids = make_note_with_tasks("级联便签")
print("  取缔前 done/delayed/abandoned/pending =", counts())
check("取缔前四个分类都有记录", counts() == (1, 1, 1, 1))
DB.delete_note(nid)
print("  取缔后 done/delayed/abandoned/pending =", counts())
check("取缔便签后归档事务保留在分类页", counts()[:3] == (1, 1, 1))
check("取缔便签后未完成事务被删除", counts()[3] == 0)
check("数据库中无残留的未完成事务",
      len(DB.list_tasks(status=DB.STATUS_PENDING)) == 0)
check("归档事务仍计入统计", DB.stats()["total"] == 3)

print("=== B. 孤儿事务不会残留在分类页 ===")
clear_db()
nid2, _ = make_note_with_tasks("孤儿源")
# 模拟历史脏数据：note_id 指向不存在的便签（需临时关闭外键约束才能插入）
with DB._connect() as conn:
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO tasks(note_id,name,content,ddl,delay_days,delay_seconds,status,created)"
                 " VALUES(?,?,?,?,0,0,'done',?)",
                 (99999, "孤儿事务", "c", "2030-01-01 00:00:00", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
before = len(DB.list_tasks_with_note(status=DB.STATUS_DONE))
print("  注入孤儿后 done 数 =", before)
check("注入后 done 为 2 条", before == 2)
n = DB.purge_orphan_tasks()
after = len(DB.list_tasks_with_note(status=DB.STATUS_DONE))
print("  清理后 done 数 =", after, " 清除条数 =", n)
check("孤儿事务被清除", after == 1 and n == 1)

print("=== C. 每个 tab 都有「管理」按钮 ===")
clear_db()
nid3, tids3 = make_note_with_tasks("管理便签")
c.manage = False
c.manage_tab = None
c.manage_sel = set()
c.tab = 0
c.page = "notes"
c.refresh()
app.processEvents()
tr = c.title_rect()
click(c.header_btns()[1].center().x(), c.header_btns()[1].center().y())
check("待完成 tab 点管理进入管理模式", c.manage is True)
check("管理模式列出便签", len(c.manage_items) == 1 and c.manage_items[0]["kind"] == "note")
check("管理项 id 为便签 id", c.manage_items[0]["id"] == nid3)
click(c.header_btns()[0].center().x(), c.header_btns()[0].center().y())
check("再次点击退出管理模式", c.manage is False)

# 分类 tab
c.tab = 1
c.page = "done"
c.refresh()
app.processEvents()
click(c.header_btns()[1].center().x(), c.header_btns()[1].center().y())
check("已完成 tab 点管理进入管理模式", c.manage is True)
check("已完成管理项为事务", len(c.manage_items) == 1 and c.manage_items[0]["kind"] == "task")
c.manage = False
c.manage_tab = None
c.manage_sel = set()
c.tab = 4
c.page = "stats"
c.refresh()
app.processEvents()
click(c.header_btns()[1].center().x(), c.header_btns()[1].center().y())
check("统计 tab 点管理进入管理模式", c.manage is True)
check("统计页无独立记录", len(c.manage_items) == 0)
c.manage = False
c.manage_tab = None
c.manage_sel = set()

print("=== D. 管理模式：便签 tab 勾选删除 -> 清掉未完成事务，归档事务保留 ===")
clear_db()
nid4, _ = make_note_with_tasks("待批量删")
c.tab = 0
c.page = "notes"
c.refresh()
app.processEvents()
click(c.header_btns()[1].center().x(), c.header_btns()[1].center().y())
check("进入管理模式", c.manage is True)
check("管理项 1 条", len(c.manage_items) == 1)
# 点第一行勾选
rows = getattr(c, "manage_row_rects", [])
check("有可点击的行", len(rows) == 1)
r = rows[0][1]
click(r.left() + 30, r.center().y())
check("已勾选 1 项", len(c.manage_sel) == 1)
# 底部删除按钮
dbn = c.manage_del_btn
click(dbn.left() + dbn.width() / 2, dbn.top() + dbn.height() / 2)
check("弹出删除确认框", c.overlay == "confirm")
click(1280 / 2 + 158, 720 / 2 + 28)   # 确定
app.processEvents()
print("  删除后 done/delayed/abandoned/pending =", counts())
check("便签及未完成事务被删除，归档事务保留", counts() == (1, 1, 1, 0))
check("数据库中无残留的未完成事务",
      len(DB.list_tasks(status=DB.STATUS_PENDING)) == 0)
check("归档事务仍在库中", len(DB.list_tasks()) == 3)
c.manage = False
c.manage_tab = None
c.manage_sel = set()

print("=== E. 管理模式：分类 tab 勾选删除单条事务 ===")
clear_db()
nid5, tids5 = make_note_with_tasks("分类管理")
c.tab = 1
c.page = "done"
c.refresh()
app.processEvents()
click(c.header_btns()[1].center().x(), c.header_btns()[1].center().y())
check("进入管理模式", c.manage is True)
check("已完成有 1 条", len(c.manage_items) == 1)
rows = getattr(c, "manage_row_rects", [])
r = rows[0][1]
click(r.left() + 30, r.center().y())
check("已勾选", len(c.manage_sel) == 1)
dbn = c.manage_del_btn
click(dbn.left() + dbn.width() / 2, dbn.top() + dbn.height() / 2)
click(1280 / 2 + 158, 720 / 2 + 28)
app.processEvents()
check("已完成分类已清空", len(DB.list_tasks_with_note(status=DB.STATUS_DONE)) == 0)
check("其他分类不受影响", len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED)) == 1)
c.manage = False
c.manage_tab = None
c.manage_sel = set()

print("=== F. 全选 ===")
clear_db()
nid6, _ = make_note_with_tasks("全选便签")
nid7 = DB.create_note("第二个便签")
c.tab = 0
c.page = "notes"
c.refresh()
app.processEvents()
click(c.header_btns()[1].center().x(), c.header_btns()[1].center().y())
check("进入管理模式", c.manage is True)
check("有 2 个便签", len(c.manage_items) == 2)
sa = c.manage_select_all
click(sa.left() + sa.width() / 2, sa.top() + sa.height() / 2)
check("全选后选中 2 项", len(c.manage_sel) == 2)
click(sa.left() + sa.width() / 2, sa.top() + sa.height() / 2)
check("再点取消全选", len(c.manage_sel) == 0)
c.manage = False
c.manage_tab = None
c.manage_sel = set()

clear_db()
print("全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)


