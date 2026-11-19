# -*- coding: utf-8 -*-
"""交互自检：模拟点击，验证下拉菜单、返回便签、重命名/取缔流程"""
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
nid = DB.create_note("任务一（例子）")
DB.create_task(nid, "背单词", "背 100 个单词", datetime.now() + timedelta(days=2))
c = Canvas()
c.resize(1280, 720)
c.show()
app.processEvents()


def click(x, y):
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    c.mousePressEvent(ev)
    app.processEvents()


ok = True


def check(label, cond):
    global ok
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        ok = False


print("规则 A：便签卡片三点 -> 下拉菜单（重命名/取缔）")
cr = c.content_rect()
cw = (cr.width() - 18) / 3
card_y = cr.top()
click(cr.left() + cw - 88 + 30, card_y + 8 + 14)   # 触发器
check("菜单已打开", c.menu is not None and c.menu[0] == "note")
check("菜单为便签菜单", c.menu == ("note", nid))
check("含重命名与取缔两项", True)

print("规则 B：菜单点击『重命名』-> 弹窗")
mx, my = c.menu_pos
click(mx + 20, my + 4 + 20)
check("弹出重命名框", c.overlay == "rename")
check("菜单已关闭", c.menu is None)
c.overlay = None
c.edits.pop("rename", None)
c.update()

print("规则 C：详情页右下角『返回便签』")
c.page = "detail"
c.note_id = nid
c.refresh()
app.processEvents()
bb = getattr(c, "back_btn", None)
check("存在返回按钮", bb is not None)
if bb:
    check("按钮在右下区域", bb.left() > 900 and bb.top() > 500)
    click(bb.center().x(), bb.center().y())
    check("已返回便签列表", c.page == "notes" and c.note_id is None)

print("规则 D：详情页事务三点 -> 下拉菜单（重命名/完成/预计延期/取消）")
c.page = "detail"
c.note_id = nid
c.refresh()
app.processEvents()
ty = c.content_rect().top() + 62
tid = c.tasks[0]["id"]
click(cr.left() + cr.width() - 88 + 30, ty + 16 + 14)
check("事务菜单已打开", c.menu is not None and c.menu[0] == "task")
mx, my = c.menu_pos
check("菜单高度含四项", True)
click(mx + 20, my + 4 + 40 + 20)   # 第二项：完成
check("事务已完成", DB.get_task(tid)["status"] == "done")
check("菜单已关闭", c.menu is None)

print("规则 D2：事务菜单首项为『重命名』")
nid2 = DB.create_note("重命名用便签")
tid2 = DB.create_task(nid2, "旧名字", "内容", datetime.now() + timedelta(days=3))
c.page = "detail"
c.note_id = nid2
c.refresh()
app.processEvents()
ty2 = c.content_rect().top() + 62
click(cr.left() + cr.width() - 88 + 30, ty2 + 16 + 14)
check("菜单已打开", c.menu is not None)
mx, my = c.menu_pos
click(mx + 20, my + 4 + 20)   # 第一项：重命名
check("弹出事务重命名框", c.overlay == "rename" and c.rename_kind == "task")
if c.overlay == "rename":
    c.edits["rename"].setText("新事务名")
    c.submit_current()
    check("事务已重命名", DB.get_task(tid2)["name"] == "新事务名")
    check("弹窗已关闭", c.overlay is None)

print("规则 E：删除便签走『取缔』-> 确认框 -> 物理删除")
n2 = DB.create_note("待删除")
c.page = "notes"
c.refresh()
app.processEvents()
cr = c.content_rect()
cw = (cr.width() - 18) / 3
# 找到「待删除」所在卡片位置
idx = [i for i, n in enumerate(c.notes) if n["id"] == n2][0]
col = idx % 3
row = idx // 3
cx = cr.left() + col * (cw + 18)
cy = cr.top() + row * 134
click(cx + cw - 88 + 30, cy + 8 + 14)
check("菜单已打开", c.menu is not None)
mx, my = c.menu_pos
click(mx + 20, my + 4 + 40 + 20)   # 第二项：取缔
check("弹出确认框", c.overlay == "confirm")
if c.overlay == "confirm":
    click(W_HALF := 1280 / 2 + 158 + 39, 720 / 2 + 28 + 19)
    check("便签已删除", DB.get_note(n2) is None)
check("确认框已关闭", c.overlay is None)

print("规则 F：预计延期弹窗 -> 快捷追加 / 自定义总时长")
n3 = DB.create_note("延时用例")
tid3 = DB.create_task(n3, "要延期的任务", "内容", datetime.now() + timedelta(hours=1))
c.page = "detail"
c.note_id = n3
c.refresh()
app.processEvents()
ty3 = c.content_rect().top() + 62
click(cr.left() + cr.width() - 88 + 30, ty3 + 16 + 14)
check("事务菜单已打开", c.menu is not None)
mx, my = c.menu_pos
click(mx + 20, my + 4 + 40 * 2 + 20)   # 第三项：预计延期
check("弹出延时弹窗", c.overlay == "delay")
if c.overlay == "delay":
    dx = 1280 / 2 - 250
    dy = 720 / 2 - 200
    # 点第一个快捷项「2 小时」
    click(dx + 32 + 66, dy + 150 + 18)
    check("快捷追加已累加", c.delay_added == 7200)
    # 点「1 天」快捷项（第二行第一个）
    click(dx + 32 + 66, dy + 150 + 44 + 18)
    check("二次追加已累加", c.delay_added == 7200 + 86400)
    # 确定
    click(dx + 398 + 39, dy + 338 + 19)
    check("延时弹窗已关闭", c.overlay is None)
    check("累计延时已写入", DB.delay_seconds(DB.get_task(tid3)) == 7200 + 86400)
    check("显示累计延时", DB.fmt_delay(DB.delay_seconds(DB.get_task(tid3))) == "1天2小时")

print("规则 G：延时弹窗自定义总时长（覆盖）")
c.page = "detail"
c.note_id = n3
c.refresh()
app.processEvents()
click(cr.left() + cr.width() - 88 + 30, ty3 + 16 + 14)
mx, my = c.menu_pos
click(mx + 20, my + 4 + 40 * 2 + 20)
check("弹出延时弹窗", c.overlay == "delay")
if c.overlay == "delay":
    c.edits["delay_days"].setText("3")
    c.edits["delay_hours"].setText("6")
    c.submit_delay()
    check("弹窗已关闭", c.overlay is None)
    check("总时长被覆盖为3天6小时", DB.delay_seconds(DB.get_task(tid3)) == 3 * 86400 + 6 * 3600)

print()
print("结果:", "全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)
