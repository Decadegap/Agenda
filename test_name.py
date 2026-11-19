# -*- coding: utf-8 -*-
"""命名功能测试：便命名、事务命名、重命名事务"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db as DB

FAILS = []


def check(cond, label):
    if cond:
        print("  PASS", label)
    else:
        print("  FAIL", label)
        FAILS.append(label)


def main():
    tmp = tempfile.mkdtemp(prefix="agenda_name_")
    os.environ["APPDATA"] = tmp
    DB.DB_PATH = os.path.join(tmp, "agenda.db")
    DB.init_db()

    print("规则 A：创建便签可自定义名称")
    nid = DB.create_note("考研复习计划")
    check(DB.get_note(nid)["name"] == "考研复习计划", "便签名称已保存")

    print("规则 B：创建事务可自定义名称")
    tid = DB.create_task(nid, "背单词", "背 100 个单词", DB.now().replace(day=1))
    check(DB.get_task(tid)["name"] == "背单词", "事务名称已保存")

    print("规则 C：名称为空时回落默认")
    tid2 = DB.create_task(nid, "   ", "内容", DB.now().replace(day=1))
    check(DB.get_task(tid2)["name"] == "未命名事务", "空名称回落为默认")

    print("规则 D：重命名事务")
    DB.rename_task(tid, "背单词 100 个")
    check(DB.get_task(tid)["name"] == "背单词 100 个", "事务重命名生效")

    print("规则 E：重命名便签")
    DB.rename_note(nid, "期末冲刺")
    check(DB.get_note(nid)["name"] == "期末冲刺", "便签重命名生效")

    print("规则 F：输入框内容不会被重绘清空（回归）")
    import main as M
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    c = M.Canvas()
    from PyQt6.QtGui import QPainter, QImage
    img = QImage(1280, 720, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    c.overlay = "note_create"
    c.edits.pop("note_name", None)
    c.field(p, "note_name", 100, 100, 300, "便签名称", "占位")
    c.edits["note_name"].setText("我的名字")
    p.end()
    # 重新绘制一次（模拟鼠标移动触发的重绘）
    img2 = QImage(1280, 720, QImage.Format.Format_ARGB32)
    p2 = QPainter(img2)
    c.field(p2, "note_name", 100, 100, 300, "便签名称", "占位")
    p2.end()
    check(c.edits["note_name"].text() == "我的名字", "重绘后输入内容保留")

    print("规则 G：回车提交当前弹窗")
    c.edits["note_name"].setText("回车创建的便签")
    c.submit_current()
    notes = DB.list_notes()
    check(any(n["name"] == "回车创建的便签" for n in notes), "回车可提交便签")

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("结果: %d 项失败" % len(FAILS))
        sys.exit(1)
    print("结果: 全部通过")


if __name__ == "__main__":
    main()
