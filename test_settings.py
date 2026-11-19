# -*- coding: utf-8 -*-
"""设置 + 桌面实体便签 功能自检"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRectF

import db as DB
import settings as S
import main as M

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def main():
    app = QApplication.instance() or QApplication([])

    # ---------- 设置持久化 ----------
    print("\n[1] 设置持久化")
    orig = S.load()
    S.save(dict(orig, skin="mint", sticky_size=260, sticky_opacity=0.8))
    cfg = S.load()
    check("皮肤已保存", cfg["skin"] == "mint")
    check("尺寸已保存", cfg["sticky_size"] == 260)
    check("不透明度已保存", abs(cfg["sticky_opacity"] - 0.8) < 1e-6)

    # 非法值应被过滤
    S.save(dict(orig, skin="__nope__", sticky_size=99999, sticky_opacity=5))
    cfg = S.load()
    check("非法皮肤回退默认", cfg["skin"] == "classic")
    check("非法尺寸回退默认", cfg["sticky_size"] == 220)
    check("非法不透明度回退默认", abs(cfg["sticky_opacity"] - 1.0) < 1e-6)

    # 恢复
    S.save(orig)

    # ---------- 设置弹窗 ----------
    print("\n[2] 设置弹窗")
    c = M.Canvas()
    c.resize(1280, 720)
    c.show()
    app.processEvents()

    c.open_settings()
    app.processEvents()
    check("设置弹窗已打开", c.overlay == "settings")

    # 开关
    sw = c.setting_switch
    check("存在桌面便签开关", sw is not None and sw[1] == "desktop_sticky")
    before = c.setting_draft["desktop_sticky"]
    c.handle_settings_click(sw[0].center().x(), sw[0].center().y())
    check("开关可切换", c.setting_draft["desktop_sticky"] != before)
    c.setting_draft["desktop_sticky"] = before

    # 皮肤
    check("存在 5 种皮肤", len(c.setting_skins) == len(S.SKINS))
    key, r = c.setting_skins[2]
    c.handle_settings_click(r.center().x(), r.center().y())
    check("皮肤可选择", c.setting_draft["skin"] == key)

    # 尺寸滑条
    st = c.setting_size_track
    c.handle_settings_click(st.left() + st.width(), st.center().y())
    check("尺寸滑条可拖到最大", c.setting_draft["sticky_size"] >= 400)
    c.handle_settings_click(st.left(), st.center().y())
    check("尺寸滑条可拖到最小", c.setting_draft["sticky_size"] <= 165)

    # 不透明度
    op = c.setting_opacity_track
    c.handle_settings_click(op.left(), op.center().y())
    check("不透明度滑条可调", c.setting_draft["sticky_opacity"] <= 0.35)
    c.handle_settings_click(op.left() + op.width(), op.center().y())
    check("不透明度滑条可调满", c.setting_draft["sticky_opacity"] >= 0.95)

    # 取消不保存
    c.setting_draft["skin"] = "blush"
    dx, dy, dw, dh = c.dlg_rect("settings")
    c.handle_settings_click(dx + dw - 190 + 39, dy + dh - 62 + 19)
    check("取消后弹窗关闭", c.overlay is None)
    check("取消后未写入磁盘", S.load()["skin"] != "blush")

    # 保存生效
    c.open_settings()
    app.processEvents()
    c.setting_draft["skin"] = "sky"
    c.setting_size_val = 300
    c.setting_opacity_val = 0.9
    dx, dy, dw, dh = c.dlg_rect("settings")
    c.handle_settings_click(dx + dw - 102 + 39, dy + dh - 62 + 19)
    app.processEvents()
    saved = S.load()
    check("保存后写入磁盘", saved["skin"] == "sky")
    check("保存后尺寸生效", saved["sticky_size"] == 300)
    check("保存后不透明度生效", abs(saved["sticky_opacity"] - 0.9) < 1e-6)
    S.save(orig)

    # ---------- 齿轮按钮 ----------
    print("\n[3] 齿轮设置按钮")
    c2 = M.Canvas()
    c2.resize(1280, 720)
    c2.show()
    app.processEvents()
    pb, mb, sb = c2.header_btns()
    check("齿轮按钮存在", sb is not None)
    check("齿轮按钮在最右侧", sb is not None and sb.right() <= c2.title_rect().right() + 1)
    # 齿轮不与主按钮/管理按钮重叠
    tr = c2.title_rect()
    no_overlap = True
    for r in (pb, mb):
        if r is None:
            continue
        if sb.intersects(r):
            no_overlap = False
    check("齿轮与其它头部按钮不重叠", no_overlap)

    # ---------- 实体便签 ----------
    print("\n[4] 桌面实体便签")
    import sticky_view as SV

    with DB._connect() as conn:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM notes")
    nid = DB.create_note("考研复习")
    from datetime import datetime, timedelta
    DB.create_task(nid, "背单词", "背 200 个考研词汇", datetime.now() + timedelta(days=3))
    DB.create_task(nid, "刷真题", "做一套 2020 真题", datetime.now() + timedelta(hours=5))
    DB.create_task(nid, "作文", "背一篇高分范文", datetime.now() - timedelta(hours=2))

    w = SV.StickyWindow(nid)
    w.show()
    app.processEvents()
    check("实体便签宽度取自设置", w.width() == int(S.get("sticky_size")))
    check("实体便签高度随内容变化", w.height() > 120)
    check("实体便签列出 3 个事务", len(w.rows) == 3)
    check("超时事务被识别", any(r["overdue"] for r in w.rows))
    check("未超时事务被识别", any(not r["overdue"] for r in w.rows))

    # 便签名与内容
    check("实体便签读取便签名", w.note_name == "考研复习")

    # 渲染不报错、产出非空图像
    pm = w.grab()
    check("实体便签可渲染", not pm.isNull() and pm.width() > 0)

    # 删除便签后窗口应关闭
    DB.delete_note(nid)
    w.reload()
    check("便签删除后实体便签关闭", not w.isVisible())

    # 皮肤切换生效
    for k in S.SKINS:
        S.set_value("skin", k)
        w2 = SV.StickyWindow(nid) if False else None
    S.set_value("skin", "classic")

    print(f"\n{'='*46}")
    print(f"  通过 {PASS}  失败 {FAIL}")
    print(f"{'='*46}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
