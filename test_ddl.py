# -*- coding: utf-8 -*-
"""DDL 选择器测试：任意小时（22:00）、任意分钟、过去日期不可选/不可创建、跨月边界"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent

import db as DB
from main import Canvas, month_grid

DB.init_db()
with DB._connect() as c:
    c.execute("DELETE FROM tasks")
    c.execute("DELETE FROM notes")

app = QApplication.instance() or QApplication(sys.argv)
nid = DB.create_note("ddl测试")
c = Canvas()
c.resize(1280, 720)
c.show()
c.page = "detail"
c.note_id = nid
c.refresh()

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


def click(x, y):
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    c.mousePressEvent(ev)
    app.processEvents()


def open_dlg():
    c.open_task_dialog()
    app.processEvents()
    return c.ddl_rects()


def click_date(g, year, month, day):
    """切到指定年月并点击某一天，返回是否点到"""
    for _ in range(60):
        if (c.cal_year, c.cal_month) == (year, month):
            break
        if c.cal_year * 12 + c.cal_month > year * 12 + month:
            click(g["bx"] + g["bw"] - 82 + 15, g["cal_y"] + 19)
        else:
            click(g["bx"] + g["bw"] - 50 + 15, g["cal_y"] + 19)
    grid = month_grid(c.cal_year, c.cal_month)
    cell_w = (g["bw"] - 24) / 7
    for ri, row in enumerate(grid):
        if day in row:
            ci = row.index(day)
            click(g["bx"] + 12 + ci * cell_w + (cell_w - 4) / 2,
                  g["cal_y"] + 56 + ri * 24 + 11)
            return True
    return False


print("规则1：小时滑条可拖到 22 点")
g = open_dlg()
tx, ty, tw = g["h_track"]
click(tx + tw * (22 / 23.0), ty)
check("小时滑条设为 22", c.pick_hour == 22, f"实际 {c.pick_hour}")
check("DDL 小时同步为 22", c.ddl_date.hour == 22, f"实际 {c.ddl_date}")

print("规则2：分钟滑条可拖到任意分钟（如 45 分）")
tx2, ty2, tw2 = g["m_track"]
click(tx2 + tw2 * (45 / 59.0), ty2)
check("分钟滑条设为 45", c.pick_minute == 45, f"实际 {c.pick_minute}")
check("最终 DDL 为 22:45", c.ddl_date.hour == 22 and c.ddl_date.minute == 45,
      f"实际 {c.ddl_date}")

print("规则3：常用时间按钮仍可用")
g = open_dlg()
click(g["bx"] + 52 + 2 * 84 + 38, g["chips_y"] + 13)
check("点 18:00 生效", c.pick_hour == 18 and c.pick_minute == 0, f"实际 {c.pick_hour}:{c.pick_minute}")

print("规则4：过去的日期不可选")
now = datetime.now()
yest = now - timedelta(days=1)
g = open_dlg()
before = c.ddl_date
hit = click_date(g, yest.year, yest.month, yest.day)
check("能点中昨天格子", hit)
check("过去日期未被选中", c.ddl_date == before, f"实际 {c.ddl_date} 期望不变 {before}")
check("弹出错误提示", bool(getattr(c, "ddl_error", "")), f"ddl_error={getattr(c, 'ddl_error', '')!r}")
check("提示语含『不能选择过去』", "不能选择过去" in getattr(c, "ddl_error", ""),
      f"实际 {getattr(c, 'ddl_error', '')!r}")

print("规则5：过去的日期无法创建事务")
g = open_dlg()
c.edits["task_content"].setText("测试内容")
# 强行把 DDL 设为过去（模拟绕过 UI 的情况）
c.ddl_date = now - timedelta(days=1)
c.ddl_error = ""
click(g["dx"] + g["vw"] - 102 + 39, g["dy"] + g["vh"] - 58 + 19)
tasks = DB.list_tasks(note_id=nid)
check("事务未被创建", len(tasks) == 0, f"实际 {len(tasks)}")
check("弹窗仍打开", c.overlay == "task_create", f"实际 {c.overlay}")
check("显示错误提示", "DDL 必须晚于当前时间" in getattr(c, "ddl_error", ""),
      f"实际 {getattr(c, 'ddl_error', '')!r}")
check("toast 提示无法创建", "无法创建" in (c.message or ""), f"message={c.message!r}")
print("规则6：今天但已过的时间也无法创建")
g = open_dlg()
c.edits["task_content"].setText("测试内容")
past_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
if past_today < now:
    c.ddl_date = past_today
    c.ddl_error = ""
    click(g["dx"] + g["vw"] - 102 + 39, g["dy"] + g["vh"] - 58 + 19)
    tasks = DB.list_tasks(note_id=nid)
    check("今天已过时刻的事务未创建", len(tasks) == 0, f"实际 {len(tasks)}")
    check("弹窗仍打开", c.overlay == "task_create", f"实际 {c.overlay}")
else:
    check("今天已过时刻的事务未创建", True)
    check("弹窗仍打开", True)

print("规则7：合法的将来时间可以正常创建")
g = open_dlg()
c.edits["task_content"].setText("测试内容")
tx, ty, tw = g["h_track"]
click(tx + tw * (22 / 23.0), ty)
tx2, ty2, tw2 = g["m_track"]
click(tx2 + tw2 * (45 / 59.0), ty2)
g = c.ddl_rects()
click(g["dx"] + g["vw"] - 102 + 39, g["dy"] + g["vh"] - 58 + 19)
tasks = DB.list_tasks(note_id=nid)
check("事务已创建", len(tasks) == 1, f"实际 {len(tasks)}")
if tasks:
    t = tasks[0]
    exp = c.ddl_date.strftime("%Y-%m-%d %H:%M:%S")
    check("入库 DDL 正确", t["ddl"] == exp, f"实际 {t['ddl']} 期望 {exp}")
check("弹窗已关闭", c.overlay is None, f"实际 {c.overlay}")

print("规则8：跨月选择不抛异常（31 号 -> 次年 2 月）")
g = open_dlg()
yr = c.ddl_date.year
# 跳到次年 1 月并选 31 号（1 月有 31 天）
ok31 = click_date(g, yr + 1, 1, 31)
check("可选 31 号", ok31)
check("选中 31 号", c.ddl_date.day == 31 and c.ddl_date.year == yr + 1,
      f"实际 {c.ddl_date}")
# 再翻到次年 2 月选 15 号（2 月无 31 日，不得抛异常）
ok15 = click_date(g, yr + 1, 2, 15)
check("次年 2 月可选 15 号且无异常", ok15 and c.ddl_date.month == 2 and c.ddl_date.day == 15,
      f"实际 {c.ddl_date}")

print("规则8b：过去月份可浏览但不可选")
g = open_dlg()
ok = click_date(g, now.year, now.month - 1 if now.month > 1 else 12, 15)
check("过去月份的日期不可选", c.ddl_date.date() == before.date(),
      f"实际 {c.ddl_date}")

print("规则9：默认 DDL 仍是未来时间")
c.open_task_dialog()
app.processEvents()
check("默认 DDL 在未来", c.ddl_date > datetime.now(), f"实际 {c.ddl_date}")
check("默认无错误提示", not getattr(c, "ddl_error", ""), f"实际 {getattr(c, 'ddl_error', '')!r}")

with DB._connect() as conn:
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM notes")

print()
print(f"通过 {passed} 项，失败 {len(failed)} 项")
if failed:
    print("失败项：", failed)
    sys.exit(1)
print("全部通过")
