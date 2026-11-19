# -*- coding: utf-8 -*-
"""窗口缩放测试：拖拽调整大小后，布局自适应且交互坐标仍正确"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, QRectF, Qt, QPoint
from PyQt6.QtGui import QMouseEvent, QWheelEvent

import db as DB
from main import Canvas, MIN_W, MIN_H
from datetime import datetime, timedelta

DB.init_db()
with DB._connect() as c:
    c.execute("DELETE FROM tasks")
    c.execute("DELETE FROM notes")

app = QApplication.instance() or QApplication(sys.argv)
nid = DB.create_note("缩放测试便签")
_fut = datetime.now() + timedelta(days=3)
tid = DB.create_task(nid, "任务A", "内容A", _fut)

passed = 0
failed = []


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name} {extra}")


def click(c, x, y):
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    c.mousePressEvent(ev)
    app.processEvents()


SIZES = [(1280, 720), (1600, 900), (1920, 1080), (1000, 650), (900, 600), (1400, 600)]

print("规则1：窗口可缩放到任意尺寸（不再固定大小）")
c = Canvas()
check("无 setFixedSize 锁定", c.minimumWidth() == MIN_W, f"minW={c.minimumWidth()}")
c.resize(1280, 720)
app.processEvents()
check("默认 1280x720", c.width() == 1280 and c.height() == 720,
      f"实际 {c.width()}x{c.height()}")

print("规则2：各种尺寸下内容矩形都在窗口内")
for w, h in SIZES:
    c.resize(w, h)
    app.processEvents()
    cr = c.content_rect()
    ok = (cr.left() >= -1 and cr.right() <= w + 1
          and cr.top() >= -1 and cr.bottom() <= h + 1
          and cr.width() > 100)
    check(f"{w}x{h} 内容矩形合法", ok,
          f"实际 x={cr.left():.0f} w={cr.width():.0f} bottom={cr.bottom():.0f}")

print("规则3：窄窗口自动减少便签列数")
c.resize(1280, 720)
app.processEvents()
check("1280 宽为 3 列", c.cols() == 3, f"实际 {c.cols()}")
c.resize(1000, 650)
app.processEvents()
check("1000 宽为 2 列", c.cols() == 2, f"实际 {c.cols()}")
c.resize(760, 600)
app.processEvents()
check("760 宽（最小）为 1 列", c.cols() == 1, f"实际 {c.cols()}")
check("最小宽度下内容矩形仍合法",
      c.content_rect().width() > 100 and c.content_rect().right() <= 760)

print("规则4：便签网格绘制与点击坐标一致（缩放后仍能命中）")
c.resize(1000, 650)
app.processEvents()
c.page = "notes"
c.refresh()
app.processEvents()
# 找到第一张卡片的位置并点击三点
cr = c.content_rect()
ncol = c.cols()
cw = (cr.width() - 18 * (ncol - 1)) / ncol
dot_x = cr.left() + cw - 88 + 30
dot_y = cr.top() + 8 + 14
c.menu = None
click(c, dot_x, dot_y)
check("缩放后三点菜单可打开", c.menu is not None and c.menu[0] == "note",
      f"实际 {c.menu}")

print("规则5：弹窗在缩放后的窗口里居中且不超出边界")
for kind in ("note_create", "rename", "delay", "confirm"):
    x, y, w, h = c.dlg_rect(kind)
    ok = (x >= 0 and y >= 0 and x + w <= c.width() + 1 and y + h <= c.height() + 1)
    check(f"{kind} 弹窗在窗口内", ok,
          f"实际 {x:.0f},{y:.0f} {w:.0f}x{h:.0f} 窗口 {c.width()}x{c.height()}")

print("规则6：任务弹窗在小窗口可滚动")
c.resize(900, 600)
app.processEvents()
c.open_task_dialog()
app.processEvents()
g = c.ddl_rects()
check("小窗口下弹窗高度自适应", g["vh"] <= c.height() - 80,
      f"vh={g['vh']} 窗口高 {c.height()}")
check("存在可滚动距离", c.task_max_scroll() > 0, f"max={c.task_max_scroll()}")
check("默认滚动位置为 0", getattr(c, "task_scroll", 0) == 0)
# 滚轮向下
ev = QWheelEvent(QPointF(g["dx"] + 100, g["dy"] + 100), QPointF(g["dx"] + 100, g["dy"] + 100),
                  QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                  Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
c.wheelEvent(ev)
app.processEvents()
check("滚轮可向下滚动", c.task_scroll > 0, f"scroll={c.task_scroll}")
# 滚到底
for _ in range(40):
    ev = QWheelEvent(QPointF(g["dx"] + 100, g["dy"] + 100), QPointF(g["dx"] + 100, g["dy"] + 100),
                      QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    c.wheelEvent(ev)
app.processEvents()
check("滚动不会超过上限", c.task_scroll == c.task_max_scroll(),
      f"scroll={c.task_scroll} max={c.task_max_scroll()}")

print("规则7：滚动后 DDL 控件坐标随之移动（点击仍命中）")
g2 = c.ddl_rects()
tx, ty, tw = g2["h_track"]
c.pick_hour = -1
click(c, tx + tw * (22 / 23.0), ty)
check("滚动后小时滑条仍可拖动", c.pick_hour == 22, f"实际 {c.pick_hour}")

print("规则8：任务弹窗按钮在大窗口下位置正确")
c.resize(1920, 1080)
app.processEvents()
c.note_id = nid
c.page = "detail"
c.open_task_dialog()
app.processEvents()
g3 = c.ddl_rects()
c.grab()   # 触发 paintEvent，创建输入框控件
app.processEvents()
c.edits["task_content"].setText("内容")
c.ddl_date = datetime.now() + timedelta(days=3)
click(c, g3["dx"] + g3["vw"] - 102 + 39, g3["dy"] + g3["vh"] - 58 + 19)
tasks = DB.list_tasks(note_id=nid)
check("大窗口下确定按钮可创建事务", len(tasks) == 2, f"实际 {len(tasks)}")
check("弹窗已关闭", c.overlay is None, f"实际 {c.overlay}")

print("规则9：便签弹窗确定/取消按钮位置自适应")
for w, h in [(1280, 720), (900, 600), (1600, 900)]:
    c.resize(w, h)
    app.processEvents()
    c.open_note_dialog()
    app.processEvents()
    c.grab()
    app.processEvents()
    dx, dy, dw, dh = c.dlg_rect("note_create")
    c.edits["note_name"].setText(f"便签{w}")
    click(c, dx + dw - 102 + 39, dy + dh - 62 + 19)
    check(f"{w}x{h} 便签弹窗确定可用", c.overlay is None, f"实际 {c.overlay}")

print("规则10：窗口最大化也能正常绘制")
c.resize(1920, 1080)
app.processEvents()
c.page = "stats"
c.refresh()
app.processEvents()
img_ok = True
try:
    c.grab()
except Exception as e:
    img_ok = False
    print("   绘制异常:", e)
check("统计页在 1920x1080 可绘制", img_ok)

with DB._connect() as conn:
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM notes")

print()
print(f"通过 {passed} 项，失败 {len(failed)} 项")
if failed:
    print("失败项：", failed)
    sys.exit(1)
print("全部通过")
