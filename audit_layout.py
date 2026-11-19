# -*- coding: utf-8 -*-
"""布局几何审计：检查各尺寸下关键元素是否越界/重叠"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRectF
from datetime import datetime, timedelta
import db as DB
from main import Canvas, MARGIN, BODY_Y, GRID_GAP

DB.init_db()
with DB._connect() as c:
    c.execute("DELETE FROM tasks")
    c.execute("DELETE FROM notes")

app = QApplication.instance() or QApplication(sys.argv)
nid = DB.create_note("任务一（例子）")
DB.create_note("任务二（例子）")
DB.create_note("学习计划（例子）")
for i in range(5):
    DB.create_task(nid, f"任务{i}", "内容描述文字", datetime.now() + timedelta(days=i + 1))

c = Canvas()
c.show()

problems = []
notes = []


def chk(cond, msg):
    (notes if cond else problems).append(msg)


def overlap(a, b):
    return not (a.right() <= b.left() or b.right() <= a.left()
                or a.bottom() <= b.top() or b.bottom() <= a.top())


SIZES = [(760, 600), (900, 600), (1000, 650), (1280, 720), (1440, 900),
         (1600, 900), (1920, 1080), (1280, 560)]

for W_, H_ in SIZES:
    c.resize(W_, H_)
    app.processEvents()
    tag = f"{W_}x{H_}"

    # 1. 内容矩形不越界
    cr = c.content_rect()
    chk(cr.left() >= -0.5 and cr.right() <= W_ + 0.5
        and cr.top() >= -0.5 and cr.bottom() <= H_ + 0.5,
        f"{tag} 内容矩形越界: {cr}")

    # 2. tab 全部在窗口内且不重叠
    tabs = c.tab_labels()
    prev = None
    for name, r, cnt in tabs:
        chk(r.left() >= 0 and r.right() <= W_,
            f"{tag} tab {name} 越界: {r.left():.0f}~{r.right():.0f}")
        if prev is not None and name != "__sep__":
            chk(not overlap(prev, r),
                f"{tag} tab {name} 与前一个重叠")
        prev = r

    # 3. 标题区与 tab 区不重叠
    tr = c.title_rect()
    tabs_r = [r for _, r, _ in tabs if r.height() > 0]
    tab_top = min(r.top() for r in tabs_r)
    tab_bot = max(r.bottom() for r in tabs_r)
    chk(tr.bottom() <= tab_top,
        f"{tag} 标题区与 tab 区重叠: title.bottom={tr.bottom():.0f} tab.top={tab_top:.0f}")

    # 4. 便签卡片网格：不重叠；超出可视区的卡片必须可通过滚动到达
    c.page = "notes"
    c.refresh()
    app.processEvents()
    grid = c.notes_grid()
    ncol = c.cols()
    cw = (cr.width() - GRID_GAP * (ncol - 1)) / ncol
    rects = [QRectF(x, y, cw, 118) for _, x, y, _ in grid]
    # 滚动到底后，最后一行必须完整可见（允许上方卡片滑出视口，这是滚动的前提）
    max_scroll = c.notes_max_scroll()
    c.page_scroll = max_scroll
    app.processEvents()
    grid_b = c.notes_grid()
    for _, x, y, _ in grid_b[-ncol:]:
        chk(y + 118 <= cr.bottom() + 0.5,
            f"{tag} 最后一行滚动到底后仍越界: y={y:.0f} bottom={y+118:.0f} 可视底={cr.bottom():.0f}")
    # 未滚动时，第一行必须完整可见
    c.page_scroll = 0
    app.processEvents()
    grid_t = c.notes_grid()
    for _, x, y, _ in grid_t[:ncol]:
        chk(y >= cr.top() - 0.5 and y + 118 <= cr.bottom() + 0.5,
            f"{tag} 首行未完整可见: y={y:.0f}")
    for i, r in enumerate(rects):
        chk(r.left() >= -0.5 and r.right() <= W_ + 0.5,
            f"{tag} 卡片{i} 横向越界: {r.left():.0f}~{r.right():.0f}")
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if overlap(rects[i], rects[j]):
                problems.append(f"{tag} 卡片{i}与卡片{j}重叠")

    # 5. 新建便签按钮与卡片不重叠
    nb = getattr(c, "new_btn", None)
    if nb is not None:
        for i, r in enumerate(rects):
            if overlap(nb, r):
                problems.append(f"{tag} 新建按钮与卡片{i}重叠")

    # 6. 弹窗全部在窗口内
    for kind in ("note_create", "rename", "delay", "confirm"):
        x, y, w, h = c.dlg_rect(kind)
        chk(x >= -0.5 and y >= -0.5 and x + w <= W_ + 0.5 and y + h <= H_ + 0.5,
            f"{tag} {kind} 弹窗越界: {x:.0f},{y:.0f} {w:.0f}x{h:.0f}")

    # 7. 任务弹窗：内容区高度为正，滚动上限合理
    c.page = "detail"
    c.note_id = nid
    c.open_task_dialog()
    app.processEvents()
    g = c.ddl_rects()
    chk(g["vh"] > 200, f"{tag} 任务弹窗高度过小 {g['vh']:.0f}")
    chk(g["vh"] <= H_ - 40, f"{tag} 任务弹窗过高 {g['vh']:.0f} > {H_}")
    chk(c.task_max_scroll() >= 0, f"{tag} 滚动上限为负")
    c.close_overlay()

    # 8. 管理模式底栏不越界
    c.page = "notes"
    c.refresh()
    app.processEvents()
    if hasattr(c, "enter_manage"):
        c.enter_manage()
        app.processEvents()
        bb = getattr(c, "manage_del_btn", None)
        if bb is not None:
            chk(bb.bottom() <= H_ and bb.left() >= 0 and bb.right() <= W_,
                f"{tag} 管理底栏越界: {bb}")
        c.exit_manage()
        app.processEvents()

    # 9. 统计页图表卡片不越界
    c.page = "stats"
    c.refresh()
    app.processEvents()
    chk(cr.bottom() <= H_ + 0.5, f"{tag} 统计内容越界")

print(f"通过 {len(notes)} 项检查")
if problems:
    print(f"发现 {len(problems)} 个问题：")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("布局审计全部通过")
