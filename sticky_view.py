# -*- coding: utf-8 -*-
"""Agenda 桌面实体便签：每个便签在桌面上是一张实体便签小窗。

特点：
    - 无边框、置顶、圆角、轻微阴影，视觉上像贴在桌面的实体便签
    - 便签标题 + 其下每个事务的内容与红色倒计时
    - 每秒刷新倒计时；数据变化时自动重排
    - 右上角小菜单：重命名便签 / 取缔便签 / 打开主程序

本文件会被复制到 %APPDATA%\\Agenda\\sticky_view.py 并由独立进程加载。
"""
import os
import sys

from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, QObject
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QFontMetrics
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as DB
import settings as S

FONT = "Microsoft YaHei"
WIDTH = 240
TITLE_H = 30
ITEM_H = 54
PAD = 14
CLIP_H = 20


def f(size, bold=False):
    qf = QFont(FONT)
    qf.setPixelSize(size)
    qf.setBold(bold)
    qf.setFamily(FONT)
    return qf


def fmt_span(secs):
    secs = int(max(0, secs))
    d, rem = secs // 86400, secs % 86400
    h, rem = rem // 3600, rem % 3600
    m, s = rem // 60, rem % 60
    hm = f"{h:02d}:{m:02d}:{s:02d}"
    return f"{d}天 {hm}" if d else hm


def elide(text, max_chars):
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "…"


class StickyWindow(QWidget):
    """一张桌面实体便签（对应数据库里的一个便签）"""

    def __init__(self, note_id):
        super().__init__()
        self.note_id = note_id
        self.rows = []
        self.complete_buttons = []
        self.menu_open = False
        self._drag_offset = None
        self._drag_start = None

        self.setWindowTitle("Agenda 便签")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.cfg = S.load()
        self.skin = S.SKINS.get(self.cfg.get("skin"), S.SKINS["classic"])
        self.setFixedWidth(int(self.cfg.get("sticky_size", 220)))
        op = float(self.cfg.get("sticky_opacity", 1.0))
        self.setWindowOpacity(max(0.3, min(1.0, op)))

        self.reload()
        self.place()

    def place(self):
        """按便签 id 错开摆放，避免多张便签完全重叠"""
        try:
            notes = [n for n in DB.list_notes() if n["pending_cnt"] > 0]
            ids = [n["id"] for n in notes]
            idx = ids.index(self.note_id) if self.note_id in ids else 0
        except Exception:
            idx = 0
        col = idx % 4
        row = (idx // 4) % 4
        screen = QApplication.primaryScreen()
        sw = screen.availableGeometry() if screen else None
        if sw:
            x = sw.right() - self.width() - 40 - col * (self.width() + 24)
            y = sw.top() + 80 + row * 260
        else:
            x, y = 100 + col * 240, 80 + row * 260
        self.move(int(x), int(y))

    # ---------------- 数据 ----------------
    def reload(self):
        """重新读取便签与其事务，并按内容调整窗口高度"""
        n = DB.get_note(self.note_id)
        if not n:
            # 便签已被删除 -> 关闭这张实体便签
            self.close()
            return
        self.note_name = n["name"]
        tasks = DB.list_tasks(note_id=self.note_id, only_pending=True)
        self.rows = []
        for t in tasks:
            overdue, secs = DB.remaining(t)
            self.rows.append({
                "id": t["id"],
                "name": t["name"],
                "content": t["content"],
                "overdue": overdue,
                "secs": secs,
                "delay": DB.delay_seconds(t),
                "ddl": DB.effective_ddl(t),
            })
        title = (self.note_name or "").replace("\n", " ").strip()
        self.display_title = title[:32] + ("..." if len(title) > 32 else "")
        metrics = QFontMetrics(f(13, bold=True))
        title_rect = metrics.boundingRect(
            0, 0, self.width() - PAD * 2 - 22, 1000,
            int(Qt.TextFlag.TextWrapAnywhere), self.display_title)
        self.title_h = max(TITLE_H, 14 + title_rect.height())
        self.layout_size()
        self.sync_complete_buttons()
        should_pin = any(r["overdue"] or r["delay"] > 0 for r in self.rows)
        is_pinned = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if should_pin != is_pinned:
            was_visible = self.isVisible()
            position = self.pos()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, should_pin)
            self.move(position)
            if was_visible:
                self.show()
        self.update()

    def sync_complete_buttons(self):
        for button in self.complete_buttons:
            button.hide()
            button.deleteLater()
        self.complete_buttons = []
        for index, row in enumerate(self.rows[:4]):
            button = QPushButton("完成", self)
            button.setGeometry(self.width() - PAD - 44,
                               self.title_h + PAD + index * ITEM_H, 44, 22)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton { color: #28734B; background: #E7F3EB; "
                "border: 1px solid #B9DCC6; border-radius: 5px; font-size: 11px; }"
                "QPushButton:hover { background: #CFE8D8; }"
                "QPushButton:pressed { background: #B9DCC6; }")
            button.clicked.connect(lambda checked=False, task_id=row["id"]:
                                   self.complete_task(task_id))
            button.show()
            self.complete_buttons.append(button)

    def complete_task(self, task_id):
        DB.complete_task(task_id)
        self.reload()
        if not self.rows:
            self.hide()
        self.update()

    def layout_size(self):
        """按行数计算窗口高度（最多显示 4 个事务，超出显示省略提示）"""
        n = len(self.rows)
        shown = min(n, 4)
        h = self.title_h + PAD
        if shown:
            h += shown * ITEM_H
        if n > shown:
            h += CLIP_H
        h += PAD
        self.setFixedSize(self.width(), max(120, h))

    # ---------------- 绘制 ----------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        sk = self.skin
        paper = QColor(sk["paper"])
        edge = QColor(sk["paper_edge"])
        ink = QColor(sk["ink"])
        soft = QColor(sk["ink_soft"])
        accent = QColor(sk["accent"])

        w, h = self.width(), self.height()
        body = QRectF(0, 0, w, h)

        # 阴影
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(QRectF(3, 5, w - 6, h - 6), 8, 8)

        # 纸面
        p.setBrush(paper)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(body, 6, 6)

        # 顶部夹子
        clip_w = 46
        clip_x = (w - clip_w) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(sk["clip"]))
        p.drawRoundedRect(QRectF(clip_x, 0, clip_w, 13), 4, 4)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(clip_x + 6, 2, clip_w - 12, 4), 2, 2)

        # 便签名
        p.setFont(f(13, bold=True))
        p.setPen(ink)
        p.drawText(QRectF(PAD, 14, w - PAD * 2 - 22, self.title_h - 14),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWrapAnywhere),
                   self.display_title)
        # 右上角小按钮（⋯）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 22))
        p.drawEllipse(QPointF(w - 18, 22), 9, 9)
        p.setFont(f(13, bold=True))
        p.setPen(soft)
        p.drawText(QRectF(w - 27, 12, 18, 20),
                   int(Qt.AlignmentFlag.AlignCenter), "⋯")

        # 分隔线
        p.setPen(QPen(edge, 1))
        p.drawLine(QPointF(PAD, self.title_h + 6), QPointF(w - PAD, self.title_h + 6))

        # 事务行
        y = self.title_h + PAD
        shown = self.rows[:4]
        for r in shown:
            # 内容摘要
            p.setFont(f(12))
            p.setPen(ink)
            p.drawText(QRectF(PAD, y, w - PAD * 2 - 52, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       elide(r["content"] or r["name"], 16))
            # 倒计时（红字）+ 已延时标记
            p.setFont(f(11, bold=True))
            p.setPen(accent)
            label = "已超时 " + fmt_span(r["secs"]) if r["overdue"] \
                else "剩余 " + fmt_span(r["secs"])
            p.drawText(QRectF(PAD, y + 18, w - PAD * 2, 16),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            if r["delay"]:
                p.setFont(f(10))
                p.setPen(soft)
                p.drawText(QRectF(PAD + 92, y + 18, w - PAD * 2 - 92, 16),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           "已延时 " + DB.fmt_delay(r["delay"]))
            # DDL
            if self.cfg.get("sticky_show_ddl", True) and r.get("ddl"):
                p.setFont(f(10))
                p.setPen(soft)
                p.drawText(QRectF(PAD, y + 34, w - PAD * 2, 15),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           "DDL " + str(r["ddl"])[:16])
            y += ITEM_H

        # 超出提示
        if len(self.rows) > 4:
            p.setFont(f(10))
            p.setPen(soft)
            p.drawText(QRectF(PAD, y, w - PAD * 2, 16),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"还有 {len(self.rows) - 4} 个事务…")

        p.end()

    # ---------------- 交互 ----------------
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        self._drag_offset = None
        self._drag_start = None
        x, y = e.position().x(), e.position().y()
        # 右上角 ⋯ 按钮
        if x > self.width() - 36 and y < TITLE_H + 12:
            self.menu_open = not self.menu_open
            self.update()
            return
        self._drag_start = e.globalPosition().toPoint()
        self._drag_offset = self._drag_start - self.pos()
        # 点击正文关闭菜单
        self.menu_open = False
        self.update()

    def mouseMoveEvent(self, e):
        if (self._drag_offset is not None
                and e.buttons() & Qt.MouseButton.LeftButton):
            current = e.globalPosition().toPoint()
            if (current - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                self.move(current - self._drag_offset)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self._drag_start = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        # 双击打开主程序
        try:
            if getattr(sys, "frozen", False):
                os.startfile(sys.executable)
            else:
                os.startfile(os.path.join(os.path.dirname(sys.executable), "Agenda.exe"))
        except Exception:
            pass


class StickyManager(QObject):
    """管理所有实体便签窗口，跟随数据库变化增删刷新"""

    def __init__(self):
        super().__init__()
        self.windows = {}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        # 每次心跳都同步一次：新增便签自动出现、删除的便签自动关闭
        self.sync()

    def sync(self):
        """仅为仍有待处理事务（含延时未完成）的便签保留窗口"""
        notes = [n for n in DB.list_notes() if n["pending_cnt"] > 0]
        ids = {n["id"] for n in notes}
        # 删除已不存在的
        for nid in list(self.windows):
            if nid not in ids:
                w = self.windows.pop(nid)
                w.close()
        # 新增
        for n in notes:
            if n["id"] not in self.windows:
                w = StickyWindow(n["id"])
                w.show()
                self.windows[n["id"]] = w
        for w in self.windows.values():
            w.reload()


def main():
    DB.init_db()
    app = QApplication(sys.argv)
    mgr = StickyManager()
    mgr.sync()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
