# -*- coding: utf-8 -*-
"""
Agenda v0.01  ——  Python + PyQt6 + SQLite
排版为自行设计（不照搬 PPT 坐标），保留其信息结构与业务规则。
"""
import os
import sys
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QLineEdit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as DB
import settings as S
try:
    # 供 PyInstaller 静态分析收录（打包后 --sticky 子进程模式使用）
    import sticky_view
except Exception:      # pragma: no cover
    sticky_view = None

# ------------------------------------------------------------------ 设计系统
W, H = 1280, 720          # 默认窗口尺寸（可拖拽调整大小）
MIN_W, MIN_H = 760, 600   # 窗口最小尺寸（再窄则内部排版会拥挤）

PAGE_BG   = QColor("#F4F5F7")     # 页面底色
CARD_BG   = QColor("#FFFFFF")     # 卡片
INK       = QColor("#1B1D21")     # 主文字
INK_SOFT  = QColor("#5F6670")     # 次要文字
INK_FAINT = QColor("#9AA1AA")     # 弱化
LINE      = QColor("#E3E6EA")
ACCENT    = QColor("#4874CB")
ACCENT_LT = QColor("#EDF2FC")
RED       = QColor("#D93B40")
GREEN     = QColor("#2E9E68")
GRAY_PLUS = QColor("#C3C8CF")
WHITE     = QColor("#FFFFFF")

TABS = ["待完成", "已完成", "延期", "放弃", "统计"]
PAGE_TITLES = ["我的便签", "已完成", "延期", "放弃", "统计"]

# 版面
MARGIN     = 56           # 页面外留白
CONTENT_W  = 1080         # 内容最大宽度（居中）
TOP_Y      = 40           # 标题行
TAB_Y      = 92           # tab 行
HEADER_H   = 142          # 头部区高度
BODY_Y     = HEADER_H + 28
GRID_GAP   = 18           # 卡片间距

# 弹窗尺寸（会随窗口自适应缩小）
TASK_DLG_W = 560          # 任务弹窗内容宽度
TASK_CONTENT_H = 700      # 任务弹窗内容总高度（可滚动）
COLS       = 3            # 便签列表列数（宽度不够时自动减列）

FONT = "Microsoft YaHei"


def f(size, bold=False):
    qf = QFont(FONT)
    qf.setPixelSize(size)
    qf.setBold(bold)
    qf.setFamily(FONT)
    return qf


def fmt_span(secs):
    """倒计时格式化：精确到秒。例：'3天 04:12:08' / '04:12:08'"""
    secs = int(max(0, secs))
    d, rem = secs // 86400, secs % 86400
    h, rem = rem // 3600, rem % 3600
    m, s = rem // 60, rem % 60
    hm = f"{h:02d}:{m:02d}:{s:02d}"
    return f"{d}天 {hm}" if d else hm


def fmt_span_short(secs):
    """紧凑版倒计时（分类页用）：'3天04:12:08'"""
    secs = int(max(0, secs))
    d, rem = secs // 86400, secs % 86400
    h, rem = rem // 3600, rem % 3600
    m, s = rem // 60, rem % 60
    return f"{d}天{h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


def fmt_created(v):
    if not v:
        return ""
    s = str(v)
    try:
        dt = datetime.fromisoformat(s)
        return "创建于 " + dt.strftime("%m-%d %H:%M")
    except ValueError:
        return s[:16]


def parse_ddl(txt):
    txt = (txt or "").strip().replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H",
                "%Y-%m-%d", "%m-%d %H:%M", "%m-%d"):
        try:
            dt = datetime.strptime(txt, fmt)
            if fmt.startswith("%m"):
                dt = dt.replace(year=datetime.now().year)
            return dt
        except ValueError:
            continue
    return None


def default_ddl():
    """默认 DDL：今天晚上 18:00；若已过则取明天"""
    n = datetime.now().replace(second=0, microsecond=0)
    d = n.replace(hour=18, minute=0)
    if d <= n:
        d += timedelta(days=1)
    return d


def month_grid(year, month):
    """返回某月的日历格子（含前后补白，周一为首列）"""
    import calendar
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(year, month)
    cells = []
    for w in weeks:
        row = []
        for d in w:
            row.append(d if d else None)
        cells.append(row)
    return cells


# ------------------------------------------------------------------ 主画布
class Canvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(MIN_W, MIN_H)
        self.resize(W, H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.page = "notes"          # notes | detail | done | stats
        self.tab = 0
        self.note_id = None
        self.overlay = None          # note_create | task_create | confirm | rename
        self.confirm_payload = None
        self.edits = {}
        self._focus_key = None
        self.rename_kind = "note"
        self.message = ""
        self.message_until = 0
        self.menu = None             # (kind, id)
        self.menu_pos = (0, 0)
        self.bar_mode = "month"
        self._dragging = False
        self.page_scroll = 0       # 列表页滚动偏移
        self.detail_scroll = 0     # 详情页滚动偏移
        self.task_scroll = 0       # 任务弹窗滚动偏移
        self._scroll_total = 0
        self.sticky_proc = None    # 桌面实体便签子进程
        self.setting_draft = {}
        # 记录管理模式：每个 tab 一个「管理」按钮，进入后可勾选删除记录
        self.manage = False          # 是否处于管理模式
        self.manage_tab = None       # 管理模式对应的 tab
        self.manage_sel = set()       # 勾选的记录 id
        # DDL 选择器状态
        self.ddl_date = default_ddl()
        self.cal_year = self.ddl_date.year
        self.cal_month = self.ddl_date.month
        self.pick_hour = self.ddl_date.hour
        self.pick_minute = self.ddl_date.minute

        self.notes = []
        self.tasks = []
        self.refresh()

        # 秒级倒计时：每秒重绘一次
        self.tick = QTimer(self)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start(1000)

    def on_tick(self):
        """每秒刷新：让倒计时/超时显示实时更新"""
        need = False
        if self.page == "detail":
            need = any(t["status"] == DB.STATUS_PENDING for t in self.tasks)
        if need or self.message:
            self.update()

    # -------------------------------------------------- 数据
    def refresh(self):
        self.notes = DB.list_notes()
        if self.page == "detail" and self.note_id is not None:
            self.tasks = DB.list_tasks(note_id=self.note_id, only_pending=True)
        elif self.page == "done":
            st = [DB.STATUS_DONE, DB.STATUS_DELAYED, DB.STATUS_ABANDONED][self.tab - 1]
            self.tasks = DB.list_tasks_with_note(status=st)
        else:
            self.tasks = []
        if self.manage:
            self.manage_items = self.load_manage_items()
            # 清理已不存在的勾选项
            alive = {it["id"] for it in self.manage_items}
            self.manage_sel = {i for i in self.manage_sel if i in alive}
        else:
            self.manage_items = []
    def load_manage_items(self):
        """管理模式下列出可管理的记录

        - tab 0（待完成）：管理便签（删除便签会删除其名下未完成事务；
          已结束事务保留在对应分类 tab 并继续计入统计）
        - tab 1/2/3（已完成/延期/放弃）：管理该分类下的事务记录
        - tab 4（统计）：无独立记录，返回空（统计页提供「清空归档记录」）
        """
        tab = self.manage_tab if self.manage_tab is not None else self.tab
        if tab == 0:
            return [{"id": n["id"], "kind": "note",
                     "title": n["name"],
                     "sub": f"{n['pending_cnt']} 个待完成事务"} for n in DB.list_notes()]
        if 1 <= tab <= 3:
            st = [DB.STATUS_DONE, DB.STATUS_DELAYED, DB.STATUS_ABANDONED][tab - 1]
            out = []
            for t in DB.list_tasks_with_note(status=st):
                out.append({"id": t["id"], "kind": "task",
                            "title": t["name"],
                            "sub": (t.get("note_name") or "已删除的便签")})
            return out
        return []

    def enter_manage(self):
        """进入记录管理模式"""
        self.manage = True
        self.manage_tab = self.tab
        self.manage_sel = set()
        self.refresh()
        self.update()

    def exit_manage(self):
        """退出记录管理模式"""
        self.manage = False
        self.manage_tab = None
        self.manage_sel = set()
        self.refresh()
        self.update()

    def msg(self, text, ms=2200):
        self.message = text
        self.message_until = datetime.now().timestamp() * 1000 + ms
        self.update()

    # -------------------------------------------------- 几何
    @property
    def W(self):
        """当前窗口宽度（随拖拽变化）"""
        return self.width()

    @property
    def H(self):
        """当前窗口高度（随拖拽变化）"""
        return self.height()

    def body_h(self):
        """内容区可用高度（不超出窗口底部）"""
        return max(120, self.H - BODY_Y - MARGIN)

    def cols(self):
        """便签网格列数：按可用宽度自适应（窄窗口减列）"""
        avail = self.W - MARGIN * 2
        if avail < 660:
            return 1
        if avail < 940:
            return 2
        return COLS

    def content_rect(self):
        """内容容器（居中，最大宽 CONTENT_W，窄窗口时占满可用宽度）"""
        cw = min(CONTENT_W, self.W - MARGIN * 2)
        x = (self.W - cw) / 2
        return QRectF(x, BODY_Y, cw, self.body_h())

    def title_rect(self):
        cw = min(CONTENT_W, self.W - MARGIN * 2)
        return QRectF((self.W - cw) / 2, TOP_Y, cw, 34)

    def tab_labels(self):
        """tab 排布：前 4 个是状态筛选，统计用竖线隔开"""
        counts = self.tab_counts()
        out = []
        x = (self.W - min(CONTENT_W, self.W - MARGIN * 2)) / 2
        for i, name in enumerate(TABS):
            if i == 4:
                out.append(("__sep__", QRectF(x, TAB_Y, 12, 30), 0))
                x += 12
            tw = len(name) * 16
            cnt = counts.get(i, 0)
            bw = 26 if cnt else 0
            w = tw + 8 + bw
            out.append((name, QRectF(x, TAB_Y, w, 30), cnt))
            x += w + 42
        return out

    def tab_counts(self):
        done = DB.list_tasks(status=DB.STATUS_DONE)
        delayed = DB.list_tasks(status=DB.STATUS_DELAYED)
        abandoned = DB.list_tasks(status=DB.STATUS_ABANDONED)
        pending = 0
        for n in DB.list_notes():
            pending += n["pending_cnt"]
        return {0: pending, 1: len(done), 2: len(delayed), 3: len(abandoned)}

    # -------------------------------------------------- 绘制入口
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), PAGE_BG)
        if self.overlay not in ("note_create", "task_create", "rename"):
            self.hide_edits()

        self.draw_header(p)

        if self.manage:
            # 管理模式覆盖整个内容区，不绘制常规页面内容
            self._scroll_total = 0
            self.draw_manage(p)
        else:
            if self.page == "notes":
                self._scroll_total = self.notes_max_scroll()
                # 滚动量不超上限（窗口变化时收紧）
                if getattr(self, "page_scroll", 0) > self._scroll_total:
                    self.page_scroll = self._scroll_total
                self.draw_notes(p)
            elif self.page == "detail":
                self._scroll_total = self.detail_max_scroll()
                if getattr(self, "detail_scroll", 0) > self._scroll_total:
                    self.detail_scroll = self._scroll_total
                self.draw_detail(p)
            elif self.page == "done":
                self._scroll_total = 0
                self.draw_done(p)
            elif self.page == "stats":
                self._scroll_total = 0
                self.draw_stats(p)

        if self.overlay == "note_create":
            self.draw_note_dialog(p)
        elif self.overlay == "task_create":
            self.draw_task_dialog(p)
        elif self.overlay == "rename":
            self.draw_rename_dialog(p)
        elif self.overlay == "delay":
            self.draw_delay_dialog(p)
        elif self.overlay == "confirm":
            self.draw_confirm(p)
        elif self.overlay == "settings":
            self.draw_settings_dialog(p)

        if self.menu:
            self.draw_menu(p)
        if self.message and datetime.now().timestamp() * 1000 < self.message_until:
            self.draw_toast(p)

    # -------------------------------------------------- 头部
    def header_btns(self):
        """返回头部按钮矩形（不依赖绘制，可随时用于点击命中）

        返回 (primary_btn, manage_btn, settings_btn)
        """
        tr = self.title_rect()
        primary = None
        manage = None
        settings = QRectF(tr.right() - 42, tr.top() - 2, 36, 36)
        if (self.page in ("notes", "detail")
                and not self.manage
                and not (self.page == "notes" and not self.notes)):
            primary = QRectF(tr.right() - 168, tr.top() - 2, 116, 36)
        if self.page != "detail":
            if self.manage:
                primary = QRectF(tr.right() - 168, tr.top() - 2, 116, 36)
            else:
                manage = QRectF(tr.right() - 262, tr.top() - 2, 84, 36)
        return primary, manage, settings

    def draw_header(self, p):
        tr = self.title_rect()
        p.setFont(f(22, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(tr.left(), tr.top(), 500, 34),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   PAGE_TITLES[self.tab])

        # 右侧主操作（空状态时隐藏，避免与空状态按钮重复；管理模式下一并隐藏）
        self.primary_btn, self.manage_btn, self.settings_btn = self.header_btns()
        if self.primary_btn is not None and not self.manage:
            label = "新建便签" if self.page == "notes" else "新建事务"
            self.draw_primary_btn(p, self.primary_btn.left(), self.primary_btn.top(),
                                  self.primary_btn.width(), label)
        elif self.primary_btn is not None and self.manage:
            self.draw_primary_btn(p, self.primary_btn.left(), self.primary_btn.top(),
                                  self.primary_btn.width(), "完成管理")

        # 右侧「管理」按钮（每个 tab 都有，用于删除该 tab 的记录）
        if self.manage_btn is not None:
            self.draw_ghost_btn(p, self.manage_btn.left(), self.manage_btn.top(),
                                self.manage_btn.width(), "管理")

        # 右侧「设置」齿轮按钮（最右，独立点击区）
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(self.settings_btn, 8, 8)
        self.draw_gear(p, self.settings_btn.center().x(), self.settings_btn.center().y(), 9)

        # tab 行
        for item in self.tab_labels():
            name, r = item[0], item[1]
            if name == "__sep__":
                p.setPen(QPen(LINE, 1))
                p.drawLine(QPointF(r.center().x(), TAB_Y + 5),
                           QPointF(r.center().x(), TAB_Y + 25))
                continue
            cnt = item[2] if len(item) > 2 else 0
            active = (TABS.index(name) == self.tab)
            tw = len(name) * 16
            p.setFont(f(14, bold=active))
            p.setPen(INK if active else INK_SOFT)
            p.drawText(QRectF(r.left(), r.top(), tw + 4, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
            if cnt:
                bx = r.left() + tw + 8
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ACCENT_LT if active else QColor("#EDEFF2"))
                p.drawRoundedRect(QRectF(bx, r.center().y() - 9, 22, 18), 9, 9)
                p.setFont(f(11))
                p.setPen(ACCENT if active else INK_FAINT)
                p.drawText(QRectF(bx, r.top(), 22, r.height()),
                           int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), str(cnt))
            if active:
                p.setPen(QPen(ACCENT, 2))
                p.drawLine(QPointF(r.left(), r.bottom() + 8),
                           QPointF(r.left() + tw, r.bottom() + 8))

        # 头部底部分隔线
        p.setPen(QPen(LINE, 1))
        p.drawLine(QPointF(tr.left(), HEADER_H),
                   QPointF(tr.right(), HEADER_H))

    def draw_primary_btn(self, p, x, y, w, label):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT)
        p.drawRoundedRect(QRectF(x, y, w, 36), 8, 8)
        p.setFont(f(14, bold=True))
        p.setPen(WHITE)
        p.drawText(QRectF(x, y, w, 36),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), label)

    def draw_gear(self, p, cx, cy, r):
        """绘制齿轮图标（设置按钮）"""
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(INK_SOFT)
        # 8 个齿
        for i in range(8):
            import math
            a = math.radians(i * 45)
            p.drawRoundedRect(QRectF(cx + math.cos(a) * (r - 1) - 1.6,
                                       cy + math.sin(a) * (r - 1) - 1.6,
                                       3.2, 3.2), 1, 1)
        # 中心环
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(INK_SOFT, 2))
        p.drawEllipse(QPointF(cx, cy), r - 4, r - 4)
        p.setBrush(INK_SOFT)
        p.drawEllipse(QPointF(cx, cy), 2, 2)
        p.restore()

    def draw_settings_dialog(self, p):
        """设置弹窗：桌面实体便签开关 + 皮肤 + 尺寸 + 不透明度"""
        x, y, w, h = self.dlg_rect("settings")
        self.panel(p, x, y, w, h)

        p.setFont(f(19, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, y + 26, 300, 28),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "设置")

        cfg = dict(getattr(self, "setting_draft", None) or S.load())
        cy = y + 82

        # ---- 桌面实体便签开关
        p.setFont(f(14, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, cy, w - 64, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "桌面实体便签")
        p.setFont(f(12))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x + 32, cy + 22, w - 64, 18),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "每个便签在桌面上显示为一张实体便签，直接写事务内容与倒计时")
        cy += 50

        # 开关
        sw_x, sw_y, sw_w, sw_h = x + w - 92, cy - 4, 44, 24
        on = cfg.get("desktop_sticky")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT if on else QColor("#D7DBE0"))
        p.drawRoundedRect(QRectF(sw_x, sw_y, sw_w, sw_h), 12, 12)
        p.setBrush(WHITE)
        p.drawEllipse(QPointF(sw_x + (sw_w - 12) if on else sw_x + 12,
                              sw_y + sw_h / 2), 9, 9)
        self.setting_switch = (QRectF(sw_x - 4, sw_y - 4, sw_w + 8, sw_h + 8), "desktop_sticky")
        cy += 40

        # ---- 便签皮肤
        p.setFont(f(14, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, cy, w - 64, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "便签皮肤")
        cy += 28
        self.setting_skins = []
        sk_w = (w - 64 - 10 * 4) / 5
        for i, (key, sk) in enumerate(S.SKINS.items()):
            sx = x + 32 + i * (sk_w + 10)
            cur = cfg.get("skin") == key
            p.setPen(QPen(ACCENT if cur else QColor("#E3E6EA"), 2 if cur else 1))
            p.setBrush(QColor(sk["paper"]))
            p.drawRoundedRect(QRectF(sx, cy, sk_w, 46), 6, 6)
            # 小夹子
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(sk["clip"]))
            p.drawRoundedRect(QRectF(sx + sk_w / 2 - 11, cy, 22, 7), 3, 3)
            p.setFont(f(10))
            p.setPen(INK_SOFT if not cur else ACCENT)
            p.drawText(QRectF(sx, cy + 50, sk_w, 18),
                       int(Qt.AlignmentFlag.AlignCenter), sk["label"])
            self.setting_skins.append((key, QRectF(sx, cy, sk_w, 46)))
        cy += 76

        # ---- 实体便签尺寸
        p.setFont(f(13))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, cy, 200, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"实体便签宽度：{cfg.get('sticky_size')} px")
        self.setting_size_track = QRectF(x + 32, cy + 26, w - 64, 6)
        self.setting_size_val = cfg.get("sticky_size", 220)
        self.draw_slider(p, x + 32, cy + 26, w - 64, 160, 420, self.setting_size_val)
        cy += 56

        # ---- 不透明度
        p.setFont(f(13))
        p.setPen(INK)
        op = int(cfg.get("sticky_opacity", 1.0) * 100)
        p.drawText(QRectF(x + 32, cy, 200, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"不透明度：{op}%")
        self.setting_opacity_val = cfg.get("sticky_opacity", 1.0)
        self.setting_opacity_track = QRectF(x + 32, cy + 26, w - 64, 6)
        self.draw_slider(p, x + 32, cy + 26, w - 64, 30, 100, op)
        cy += 54

        # ---- 底部按钮
        self.button(p, x + w - 190, y + h - 62, 78, "取消")
        self.button(p, x + w - 102, y + h - 62, 78, "保存", primary=True)

    def draw_ghost_btn(self, p, x, y, w, label):
        """次级按钮（白底描边）"""
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, y, w, 36), 8, 8)
        p.setFont(f(14))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x, y, w, 36),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), label)

    # -------------------------------------------------- 便签列表
    def notes_grid(self):
        """计算便签卡片位置（考虑滚动偏移），返回 [(note, x, y, w)]"""
        cr = self.content_rect()
        ncol = self.cols()
        cw = (cr.width() - GRID_GAP * (ncol - 1)) / ncol
        max_scroll = self.notes_max_scroll()
        scroll = min(getattr(self, "page_scroll", 0), max_scroll)
        out = []
        y = cr.top() - scroll
        for i, n in enumerate(self.notes):
            col = i % ncol
            if col == 0 and i:
                y += 134
            out.append((n, cr.left() + col * (cw + GRID_GAP), y, cw))
        return out

    def notes_max_scroll(self):
        """便签列表可滚动的最大距离（保证滚到底时最后一行完整可见）"""
        cr = self.content_rect()
        ncol = self.cols()
        rows = (len(self.notes) + ncol - 1) // ncol
        if rows <= 0:
            return 0
        content_h = (rows - 1) * 134 + 118   # 最后一行卡片底边
        return max(0, content_h - cr.height())

    def draw_notes(self, p):
        if not self.notes:
            self.draw_empty_state(p)
            return
        cr = self.content_rect()
        # 超出可视区的卡片才裁剪
        p.save()
        p.setClipRect(cr)
        for n, x, y, cw in self.notes_grid():
            if y + 118 < cr.top() or y > cr.bottom():
                continue
            self.draw_note_card(p, n, x, y, cw)
        p.restore()
        self.draw_scrollbar(p, cr)

    # -------------------------------------------------- 记录管理
    def draw_scrollbar(self, p, cr):
        """内容区右侧滚动条（仅在有溢出时显示）"""
        total = getattr(self, "_scroll_total", 0)
        if total <= 0:
            return
        cur = getattr(self, "page_scroll", 0) if self.page == "notes" \
            else getattr(self, "detail_scroll", 0)
        x = cr.right() - 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E8EAED"))
        p.drawRoundedRect(QRectF(x, cr.top(), 4, cr.height()), 2, 2)
        frac = cur / total
        p.setBrush(QColor("#B8BEC6"))
        h = max(30, cr.height() * 0.3)
        y = cr.top() + (cr.height() - h) * frac
        p.drawRoundedRect(QRectF(x, y, 4, h), 2, 2)

    def draw_manage(self, p):
        """管理模式：列出当前 tab 的记录，左侧复选框，底部批量删除栏"""
        cr = self.content_rect()
        items = getattr(self, "manage_items", [])
        tab = self.manage_tab if self.manage_tab is not None else self.tab

        # 顶部提示条
        tip = {0: "勾选要删除的便签（未完成事务一并清除；已结束的事务保留在分类中）",
               1: "勾选要删除的已完成记录",
               2: "勾选要删除的延期记录",
               3: "勾选要删除的放弃记录",
               4: "统计页没有独立记录，可在下方清空全部归档记录"}[tab]
        p.setPen(QPen(LINE, 1))
        p.setBrush(QColor("#FAFBFC"))
        p.drawRoundedRect(QRectF(cr.left(), cr.top(), cr.width(), 52), 10, 10)
        p.setFont(f(13))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(cr.left() + 20, cr.top(), cr.width() - 40, 52),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), tip)

        # 列表
        bar_h = 64
        by = self.H - MARGIN - bar_h + 18
        list_bottom = by - 12
        y = cr.top() + 72
        items = getattr(self, "manage_items", [])
        self.manage_row_rects = []
        if not items:
            p.setFont(f(14))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(cr.left(), cr.top() + 90, cr.width(), 90),
                       int(Qt.AlignmentFlag.AlignCenter), "这个分类下没有可管理的记录")
        else:
            for it in items:
                if y + 62 > list_bottom:
                    break
                r = QRectF(cr.left(), y, cr.width(), 62)
                self.manage_row_rects.append((it, r))
                # 卡片
                p.setPen(QPen(LINE, 1))
                p.setBrush(CARD_BG)
                p.drawRoundedRect(r, 10, 10)
                # 复选框
                cx = r.left() + 30
                cy = r.center().y()
                checked = it["id"] in self.manage_sel
                p.setPen(QPen(ACCENT if checked else QColor("#C6CBD2"), 2))
                p.setBrush(ACCENT if checked else WHITE)
                p.drawRoundedRect(QRectF(cx - 9, cy - 9, 18, 18), 4, 4)
                if checked:
                    p.setPen(QPen(WHITE, 2))
                    p.drawLine(QPointF(cx - 4.5, cy + 0.5), QPointF(cx - 1, cy + 4))
                    p.drawLine(QPointF(cx - 1, cy + 4), QPointF(cx + 5, cy - 4))
                # 文本
                tw = max(120, r.width() - (cx + 24 - r.left()) - 20)
                p.setFont(f(14, bold=True))
                p.setPen(INK)
                p.drawText(QRectF(cx + 24, r.top() + 10, tw, 24),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), it["title"])
                p.setFont(f(12))
                p.setPen(INK_FAINT)
                p.drawText(QRectF(cx + 24, r.top() + 34, tw, 20),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), it["sub"])
                y += 70
            # 超出可视区域的提示
            shown = len(self.manage_row_rects)
            if len(items) > shown:
                p.setFont(f(12))
                p.setPen(INK_FAINT)
                p.drawText(QRectF(cr.left(), y, cr.width(), 22),
                           int(Qt.AlignmentFlag.AlignCenter),
                           f"共 {len(items)} 条，已显示 {shown} 条，请滚动查看剩余")

        # 底部操作栏
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(cr.left(), by, cr.width(), bar_h), 12, 12)

        p.setFont(f(13))
        p.setPen(INK_SOFT)
        sel = len(self.manage_sel)
        p.drawText(QRectF(cr.left() + 24, by, 320, bar_h),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"已选 {sel} 项" if sel else "选择要删除的记录")

        # 全选（统计页无记录，不显示）
        all_sel = bool(items) and sel == len(items)
        self.manage_select_all = None
        if items:
            p.setPen(QPen(LINE, 1))
            p.setBrush(QColor("#F2F4F7"))
            p.drawRoundedRect(QRectF(cr.left() + cr.width() - 320, by + 15, 96, 34), 8, 8)
            p.setFont(f(13, bold=True))
            p.setPen(INK_SOFT)
            p.drawText(QRectF(cr.left() + cr.width() - 320, by + 15, 96, 34),
                       int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
                       "取消全选" if all_sel else "全选")
            self.manage_select_all = QRectF(cr.left() + cr.width() - 320, by + 15, 96, 34)

        # 删除按钮
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(RED if sel else QColor("#F2F4F7"))
        p.drawRoundedRect(QRectF(cr.left() + cr.width() - 212, by + 15, 188, 34), 8, 8)
        p.setFont(f(13, bold=True))
        p.setPen(WHITE if sel else INK_FAINT)
        p.drawText(QRectF(cr.left() + cr.width() - 212, by + 15, 188, 34),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
                   f"删除 {sel} 项" if sel else "删除")
        self.manage_del_btn = QRectF(cr.left() + cr.width() - 212, by + 15, 188, 34)

        # 统计页额外提供「清空归档记录」
        if tab == 4:
            p.setPen(QPen(LINE, 1))
            p.setBrush(WHITE)
            p.drawRoundedRect(QRectF(cr.left() + 24, by + 15, 150, 34), 8, 8)
            p.setFont(f(13, bold=True))
            p.setPen(RED)
            p.drawText(QRectF(cr.left() + 24, by + 15, 150, 34),
                       int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
                       "清空归档记录")
            self.manage_clear_btn = QRectF(cr.left() + 24, by + 15, 150, 34)
        else:
            self.manage_clear_btn = None

    def draw_empty_state(self, p):
        cr = self.content_rect()
        cx = cr.center().x()
        cy = cr.top() + 118

        # 圆形容器 + 线性加号
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#EDF0F4"))
        p.drawEllipse(QPointF(cx, cy), 44, 44)
        p.setPen(QPen(QColor("#A9B0BA"), 3))
        p.drawLine(QPointF(cx - 13, cy), QPointF(cx + 13, cy))
        p.drawLine(QPointF(cx, cy - 13), QPointF(cx, cy + 13))

        p.setFont(f(16, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(cx - 200, cy + 66, 400, 26),
                   int(Qt.AlignmentFlag.AlignCenter), "还没有便签")
        p.setFont(f(13))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(cx - 200, cy + 96, 400, 22),
                   int(Qt.AlignmentFlag.AlignCenter), "创建一个便签，把想做的事装进去")
        self.empty_btn = (cx - 60, cy + 134, 120, 36)
        self.draw_primary_btn(p, cx - 60, cy + 134, 120, "立即创建")

    def draw_note_card(self, p, n, x, y, w):
        h = 118
        p.setPen(QPen(LINE, 1))
        p.setBrush(CARD_BG)
        p.drawRoundedRect(QRectF(x, y, w, h), 12, 12)

        cnt = n["pending_cnt"]
        p.setFont(f(15, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 18, y + 14, w - 56, 26),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), n["name"])

        # 顶部右侧三点（下拉菜单）
        self.draw_dots(p, x + w - 84, y + 22)

        sub = "暂无事务" if cnt == 0 else f"{cnt} 个待完成事务"
        p.setFont(f(13))
        p.setPen(INK_FAINT)
        p.drawText(QRectF(x + 18, y + 44, w - 36, 22),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), sub)

        # 底部操作条
        p.setPen(QPen(LINE, 1))
        p.drawLine(QPointF(x + 18, y + h - 40), QPointF(x + w - 18, y + h - 40))

        p.setFont(f(12))
        p.setPen(INK_FAINT)
        p.drawText(QRectF(x + 18, y + h - 36, w - 130, 30),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   fmt_created(n.get("created")))
        p.setFont(f(13))
        p.setPen(ACCENT)
        p.drawText(QRectF(x + w - 96, y + h - 36, 78, 30),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "查看详细")

    def draw_dots(self, p, x, y, w=64):
        """下拉菜单触发器：胶囊背景 + 三点 + 下箭头"""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#F1F3F6"))
        p.drawRoundedRect(QRectF(x, y - 13, w, 26), 6, 6)
        p.setBrush(INK_FAINT)
        for i in range(3):
            p.drawEllipse(QPointF(x + 13 + i * 7, y), 3.0, 3.0)
        p.setPen(QPen(INK_FAINT, 1.4))
        p.drawLine(QPointF(x + w - 17, y - 2.5), QPointF(x + w - 13, y + 2))
        p.drawLine(QPointF(x + w - 13, y + 2), QPointF(x + w - 9, y - 2.5))

    # -------------------------------------------------- 便签详情
    def draw_detail(self, p):
        note = DB.get_note(self.note_id) if self.note_id else None
        name = note["name"] if note else ""
        cr = self.content_rect()

        p.setFont(f(19, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(cr.left(), cr.top() - 8, 600, 30),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)

        cnt = note["pending_cnt"] if note else 0
        p.setFont(f(13))
        p.setPen(INK_FAINT)
        p.drawText(QRectF(cr.left(), cr.top() + 24, 500, 22),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"{cnt} 个待完成事务")

        y = cr.top() + 62 - getattr(self, "detail_scroll", 0)
        if not self.tasks:
            p.setPen(QPen(LINE, 1))
            p.setBrush(QColor("#FAFBFC"))
            p.drawRoundedRect(QRectF(cr.left(), y, cr.width(), 96), 12, 12)
            p.setFont(f(14))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(cr.left(), y + 32, cr.width(), 26),
                       int(Qt.AlignmentFlag.AlignCenter), "这个便签还没有事务")
        else:
            # 裁剪到内容区，超出部分可滚动
            p.save()
            p.setClipRect(QRectF(cr.left(), cr.top(), cr.width(), cr.height() - 8))
            for t in self.tasks:
                if y + 86 < cr.top() or y > cr.bottom():
                    y += 98
                    continue
                self.draw_task_card(p, t, cr.left(), y, cr.width())
                y += 98
            p.restore()
            self.draw_scrollbar(p, cr)

        self.draw_back_btn(p, cr)

    def detail_max_scroll(self):
        """便签详情页可滚动的最大距离"""
        cr = self.content_rect()
        if not self.tasks:
            return 0
        content_h = 62 + len(self.tasks) * 98
        return max(0, content_h - cr.height())

    def draw_back_btn(self, p, cr):
        """右下角「返回便签」"""
        w, h = 92, 34
        x = cr.right() - w
        y = self.H - MARGIN - h + 26
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, y, w, h), 8, 8)
        p.setFont(f(14))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x, y, w, h),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), "返回便签")
        self.back_btn = QRectF(x, y, w, h)

    def draw_task_card(self, p, t, x, y, w):
        h = 86
        p.setPen(QPen(LINE, 1))
        p.setBrush(CARD_BG)
        p.drawRoundedRect(QRectF(x, y, w, h), 12, 12)

        p.setFont(f(15, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 24, y + 11, 460, 26),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), t["name"])

        p.setFont(f(13))
        p.setPen(INK_FAINT)
        detail = (t.get("content") or "")[:40]
        if show_note_flag(t):
            detail = f"{t.get('note_name')} · {detail}"
        p.drawText(QRectF(x + 24, y + 39, 440, 22),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), detail)

        # DDL 绝对时间（精确到秒）+ 累计延时
        p.setFont(f(12))
        p.setPen(QColor("#B4BAC2"))
        ddl_txt = (t.get("ddl") or "")[:19]
        dsec = DB.delay_seconds(t)
        if dsec:
            ddl_txt += f"   已延时 {DB.fmt_delay(dsec)}"
        p.drawText(QRectF(x + 24, y + 58, 440, 18),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"DDL {ddl_txt}")

        st = t["status"]
        if st == DB.STATUS_DONE:
            label, col = "按时完成", GREEN
        elif st == DB.STATUS_DELAYED:
            label, col = "延期", RED
        elif st == DB.STATUS_ABANDONED:
            label, col = "放弃", INK_SOFT
        else:
            overdue, secs = DB.remaining(t)
            label = ("已超时 " if overdue else "剩余 ") + fmt_span(secs)
            col = RED
        p.setFont(f(13, bold=(st == DB.STATUS_PENDING)))
        p.setPen(col)
        p.drawText(QRectF(x + w - 360, y + 16, 260, 28),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), label)

        # 已延时的任务：在倒计时下方用橙色标出累计延时
        dsec2 = DB.delay_seconds(t)
        if dsec2:
            p.setFont(f(12, bold=True))
            p.setPen(QColor("#E08A2E"))
            p.drawText(QRectF(x + w - 360, y + 42, 260, 20),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       f"已延时 {DB.fmt_delay(dsec2)}")

        if st == DB.STATUS_PENDING:
            self.draw_dots(p, x + w - 84, y + 30)

    # -------------------------------------------------- 分类页
    def draw_done(self, p):
        cr = self.content_rect()
        if not self.tasks:
            p.setPen(QPen(LINE, 1))
            p.setBrush(QColor("#FAFBFC"))
            p.drawRoundedRect(QRectF(cr.left(), cr.top(), cr.width(), 96), 12, 12)
            p.setFont(f(14))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(cr.left(), cr.top() + 32, cr.width(), 26),
                       int(Qt.AlignmentFlag.AlignCenter), "这里还没有记录")
            return
        y = cr.top()
        for t in self.tasks:
            self.draw_task_card(p, t, cr.left(), y, cr.width())
            y += 98

    # -------------------------------------------------- 统计页
    def draw_stats(self, p):
        cr = self.content_rect()
        s = DB.stats()
        tiles = [("事务总数", f"{s['total']}", INK),
                 ("完成率", f"{s['done_rate']:.0f}%", GREEN),
                 ("延期率", f"{s['delayed_rate']:.0f}%", RED),
                 ("取消率", f"{s['abandoned_rate']:.0f}%", INK_SOFT)]
        gap = 18
        tw = (cr.width() - gap * 3) / 4
        for i, (label, val, col) in enumerate(tiles):
            x = cr.left() + i * (tw + gap)
            p.setPen(QPen(LINE, 1))
            p.setBrush(CARD_BG)
            p.drawRoundedRect(QRectF(x, cr.top(), tw, 88), 12, 12)
            p.setFont(f(13))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(x + 20, cr.top() + 14, tw - 40, 20),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            p.setFont(f(26, bold=True))
            p.setPen(col)
            p.drawText(QRectF(x + 20, cr.top() + 36, tw - 40, 36),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), val)

        chart_y = cr.top() + 116
        card_h = 268
        # 饼图卡宽度自适应：窄窗口时缩小，最小 240
        left_w = max(240, min(340, cr.width() * 0.32))
        # 饼图卡
        p.setPen(QPen(LINE, 1))
        p.setBrush(CARD_BG)
        p.drawRoundedRect(QRectF(cr.left(), chart_y, left_w, card_h), 12, 12)
        p.setFont(f(14, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(cr.left() + 22, chart_y + 16, 200, 24),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "状态分布")
        self.draw_pie(p, cr.left(), chart_y, left_w, card_h, s)

        # 柱状图卡
        bx = cr.left() + left_w + gap
        bw = cr.width() - left_w - gap
        p.setPen(QPen(LINE, 1))
        p.setBrush(CARD_BG)
        p.drawRoundedRect(QRectF(bx, chart_y, bw, card_h), 12, 12)
        p.setFont(f(14, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(bx + 22, chart_y + 16, 200, 24),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "新建事务趋势")
        # 切换
        self.draw_toggle(p, bx + bw - 92, chart_y + 14, 70,
                         "月" if self.bar_mode == "month" else "周")
        self.draw_bar(p, bx, chart_y, bw, card_h)

    def draw_toggle(self, p, x, y, w, label):
        p.setPen(QPen(LINE, 1))
        p.setBrush(QColor("#F2F4F7"))
        p.drawRoundedRect(QRectF(x, y, w, 26), 13, 13)
        p.setFont(f(12, bold=True))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x, y, w, 26),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), label)

    def draw_pie(self, p, x, y, w, h, s):
        cx = x + w / 2
        cy = y + 74
        r = max(44, min(78, w / 2 - 30))   # 饼图半径自适应卡片宽度
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#F2F4F7"))
        p.drawEllipse(QPointF(cx, cy), r, r)

        total = s["total"]
        if total:
            segs = [(s["done"], GREEN), (s["delayed"], RED), (s["abandoned"], QColor("#C3C8CF"))]
            start = 90 * 16
            for val, col in segs:
                if val <= 0:
                    continue
                span = int(-val * 360 * 16 / total)
                p.setPen(QPen(WHITE, 2))
                p.setBrush(col)
                p.drawPie(QRectF(cx - r, cy - r, 2 * r, 2 * r), start, span)
                start += span

        p.setFont(f(12))
        legend = [(f"按时完成 {s['done']}", GREEN),
                  (f"延期 {s['delayed']}", RED),
                  (f"放弃 {s['abandoned']}", QColor("#A8ADB5"))]
        ly = y + h - 66
        for i, (label, col) in enumerate(legend):
            lx = x + 28 + (i % 2) * 150
            yy = ly + (i // 2) * 24
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(lx + 5, yy + 8), 4.5, 4.5)
            p.setPen(INK_SOFT)
            p.drawText(QRectF(lx + 16, yy, 130, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)

    def draw_bar(self, p, x, y, w, h):
        data = DB.created_buckets(self.bar_mode)
        maxv = max([d[1] for d in data] + [1])
        n = len(data)
        px0 = x + 30
        pw = w - 60
        slot = pw / n
        bw = min(slot * 0.5, 42)
        base = y + h - 42

        p.setPen(QPen(LINE, 1))
        p.drawLine(QPointF(px0, base), QPointF(px0 + pw, base))
        for i, (label, v) in enumerate(data):
            bh = (base - y - 62) * v / maxv
            bx = px0 + slot * i + (slot - bw) / 2
            by = base - bh
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ACCENT if v else QColor("#E8EAED"))
            p.drawRoundedRect(QRectF(bx, by, bw, max(bh, 3)), 5, 5)
            if v:
                p.setFont(f(11))
                p.setPen(INK_SOFT)
                p.drawText(QRectF(bx - 10, by - 20, bw + 20, 16),
                           int(Qt.AlignmentFlag.AlignCenter), str(v))
            p.setFont(f(11))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(bx - 18, base + 9, bw + 36, 16),
                       int(Qt.AlignmentFlag.AlignCenter), label)

    # -------------------------------------------------- 三点菜单
    def draw_menu(self, p):
        kind, oid = self.menu
        if kind == "note":
            items = [("重命名", INK), ("取缔", RED)]
            x, y = self.menu_pos
            w, h = 148, 40 * len(items) + 8
        else:
            t = DB.get_task(oid)
            overdue = DB.remaining(t)[0] if t else False
            items = [("重命名", INK), ("完成", GREEN)]
            if not overdue:
                items.append(("预计延期", RED))
            items.append(("取消", INK_SOFT))
            x, y = self.menu_pos
            w, h = 156, 40 * len(items) + 8

        # 阴影
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 28))
        p.drawRoundedRect(QRectF(x + 2, y + 3, w, h), 10, 10)
        # 面板
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, y, w, h), 10, 10)

        ih = 40
        for i, (label, col) in enumerate(items):
            iy = y + 4 + ih * i
            if i:
                p.setPen(QPen(QColor("#F0F2F5"), 1))
                p.drawLine(QPointF(x + 12, iy), QPointF(x + w - 12, iy))
            p.setFont(f(14))
            p.setPen(col)
            p.drawText(QRectF(x + 16, iy, w - 32, ih),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)

    # -------------------------------------------------- 弹窗
    def field(self, p, key, x, y, w, label, placeholder, text=""):
        p.setFont(f(13))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x, y - 24, w, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, y, w, 40), 8, 8)
        le = self.edits.get(key)
        if le is None:
            le = QLineEdit(self)
            le.setPlaceholderText(placeholder)
            le.setFont(f(14))
            le.setStyleSheet(
                "QLineEdit{background:#FFFFFF;border:1px solid #E3E6EA;border-radius:8px;"
                "padding-left:12px;color:#1B1D21;}"
                "QLineEdit:focus{border:1px solid #4874CB;}")
            self.edits[key] = le
            self.edits[key].textChanged.connect(lambda: self.update())
            le.installEventFilter(self)
            if text:
                le.setText(text)
        le.setGeometry(int(x), int(y), int(w), 40)
        # 裁剪区外的输入框不显示（滚动时避免悬浮在弹窗外）
        clip = getattr(self, "_field_clip", None)
        if clip is not None and not clip.intersects(QRectF(x, y, w, 40)):
            le.hide()
            return
        le.show()
        if getattr(self, "_focus_key", None) == key:
            self._focus_key = None
            le.setFocus()
            le.selectAll()

    def eventFilter(self, obj, event):
        """输入框回车提交"""
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if getattr(self, "overlay", None) == "delay":
                self.submit_delay()
            else:
                self.submit_current()
            return True
        return super().eventFilter(obj, event)

    def panel(self, p, x, y, w, h):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawRect(self.rect())
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, y, w, h), 16, 16)

    def button(self, p, x, y, w, label, primary=False):
        p.setPen(QPen(ACCENT if primary else LINE, 1))
        p.setBrush(ACCENT if primary else WHITE)
        p.drawRoundedRect(QRectF(x, y, w, 38), 8, 8)
        p.setFont(f(14, bold=primary))
        p.setPen(WHITE if primary else INK_SOFT)
        p.drawText(QRectF(x, y, w, 38),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), label)

    def draw_note_dialog(self, p):
        x, y, w, h = self.dlg_rect("note_create")
        self.panel(p, x, y, w, h)
        p.setFont(f(19, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, y + 28, 300, 28),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "创建便签")
        self.field(p, "note_name", x + 32, y + 100, w - 64, "便签名称",
                   "给它起个名字，例如：考研复习")
        self.button(p, x + w - 190, y + h - 62, 78, "取消")
        self.button(p, x + w - 102, y + h - 62, 78, "确定", True)

    # -------------------------------------------------- DDL 选择器
    def ddl_rects(self):
        """DDL 选择器全部几何（屏幕坐标，绘制与点击共用，保证坐标一致）

        任务弹窗内容较高（小窗口放不下），因此支持纵向滚动：
        内容按固定高度 TASK_CONTENT_H 布局，实际显示区高度不足时用 task_scroll 偏移。
        """
        vw = min(TASK_DLG_W, self.W - 80)
        vh = min(TASK_CONTENT_H, self.H - 80)
        dx = (self.W - vw) / 2
        dy = (self.H - vh) / 2
        bx = dx + 32
        bw = vw - 64
        sy = dy - getattr(self, "task_scroll", 0)   # 内容顶端（滚动后）
        by = sy + 240            # DDL 显示框
        cal_y = by + 62          # 日历框顶部（给提示行留出空间）
        cal_h = 200
        head_y = sy + 508        # "时间" 标题行
        hours_y = sy + 532       # 小时滑条行
        mins_y = sy + 570        # 分钟滑条行
        chips_y = sy + 608       # 常用时间按钮行
        h_track = (bx + 48, hours_y + 11, bw - 48 - 78)
        m_track = (bx + 48, mins_y + 11, bw - 48)
        return dict(dx=dx, dy=dy, vw=vw, vh=vh, sy=sy, bx=bx, bw=bw, by=by,
                    cal_y=cal_y, cal_h=cal_h, head_y=head_y, hours_y=hours_y,
                    mins_y=mins_y, chips_y=chips_y,
                    h_track=h_track, m_track=m_track)

    def draw_ddl_picker(self, p, x, y, w):
        """DDL 选择器：显示框 + 日历（可选过去日期）+ 小时/分钟滑条"""
        g = self.ddl_rects()
        now = datetime.now()
        today = now.date()

        # ---------- DDL 显示框
        p.setFont(f(13))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x, y - 24, w, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "DDL（必填）")
        p.setPen(QPen(QColor("#C62828"), 2) if getattr(self, "ddl_error", "")
                 else QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, y, w, 40), 8, 8)
        p.setFont(f(14))
        p.setPen(INK)
        p.drawText(QRectF(x + 12, y, w - 130, 40),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.ddl_date.strftime("%Y-%m-%d %H:%M"))
        past = self.ddl_date < now
        p.setFont(f(12))
        p.setPen(RED if past else INK_FAINT)
        if past:
            hint = "已过期"
        else:
            today_d = now.date()
            diff = (self.ddl_date.date() - today_d).days
            hint = {0: "今天", 1: "明天", 2: "后天"}.get(diff, f"{diff} 天后")
        p.drawText(QRectF(x + w - 118, y, 106, 40),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), hint)
        # 提示行（显示框正下方）：默认灰色说明，错误时红色警示条
        err = getattr(self, "ddl_error", "")
        if err:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FDECEC"))
            p.drawRoundedRect(QRectF(x, y + 42, w, 22), 6, 6)
            p.setFont(f(11, bold=True))
            p.setPen(QColor("#C62828"))
            p.drawText(QRectF(x + 10, y + 42, w - 20, 22),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), err)
        else:
            p.setFont(f(11))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(x, y + 42, w, 20),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       "过去的日期不可选择，DDL 需晚于当前时间")

        # ---------- 日历
        cy = g["cal_y"]
        cw = w
        p.setPen(QPen(LINE, 1))
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, cy, cw, g["cal_h"]), 10, 10)
        # 月份头 + 翻页
        p.setFont(f(14, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 12, cy + 6, 120, 26),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"{self.cal_year} 年 {self.cal_month} 月")
        p.setFont(f(16))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x + cw - 82, cy + 6, 30, 26),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), "\u2039")
        p.drawText(QRectF(x + cw - 50, cy + 6, 30, 26),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), "\u203a")
        # 星期头
        heads = ["一", "二", "三", "四", "五", "六", "日"]
        cell_w = (cw - 24) / 7
        for i, hd in enumerate(heads):
            p.setFont(f(12))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(x + 12 + i * cell_w, cy + 34, cell_w, 20),
                       int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), hd)
        # 日期格子
        for ri, row in enumerate(month_grid(self.cal_year, self.cal_month)):
            for ci, d in enumerate(row):
                if d is None:
                    continue
                cx = x + 12 + ci * cell_w
                cyy = cy + 56 + ri * 24
                rect = QRectF(cx, cyy, cell_w - 4, 22)
                is_today = (d == today.day and self.cal_month == today.month
                            and self.cal_year == today.year)
                is_sel = (d == self.ddl_date.day and self.cal_month == self.ddl_date.month
                          and self.cal_year == self.ddl_date.year)
                is_past = datetime(self.cal_year, self.cal_month, d).date() < today
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ACCENT if is_sel else QColor(0, 0, 0, 0))
                p.drawRoundedRect(rect, 6, 6)
                p.setFont(f(13, bold=is_sel or is_today))
                if is_sel:
                    p.setPen(WHITE)
                elif is_past:
                    p.setPen(QColor("#C4C9D0"))
                elif is_today:
                    p.setPen(ACCENT)
                else:
                    p.setPen(INK_SOFT)
                p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
                           str(d))
        # ---------- 时间滑条
        head_y = g["head_y"]
        p.setFont(f(13))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x, head_y, 60, 24),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "时间")
        p.setFont(f(16, bold=True))
        p.setPen(ACCENT)
        p.drawText(QRectF(x + w - 78, head_y, 78, 24),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   f"{self.pick_hour:02d}:{self.pick_minute:02d}")
        # 小时滑条
        p.setFont(f(12))
        p.setPen(INK_FAINT)
        p.drawText(QRectF(x, g["hours_y"], 44, 24),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "小时")
        self.draw_slider(p, g["h_track"][0], g["h_track"][1], g["h_track"][2],
                         0, 23, self.pick_hour)
        # 分钟滑条
        p.setFont(f(12))
        p.setPen(INK_FAINT)
        p.drawText(QRectF(x, g["mins_y"], 44, 24),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "分钟")
        self.draw_slider(p, g["m_track"][0], g["m_track"][1], g["m_track"][2],
                         0, 59, self.pick_minute)
        # 常用时间
        p.setFont(f(12))
        p.setPen(INK_FAINT)
        p.drawText(QRectF(x, g["chips_y"], 44, 26),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "常用")
        for i, c in enumerate(["09:00", "12:00", "18:00", "21:00", "23:00"]):
            hh, mm = c.split(":")
            sel = (self.pick_hour == int(hh) and self.pick_minute == int(mm))
            rect = QRectF(x + 52 + i * 84, g["chips_y"], 76, 26)
            p.setPen(QPen(ACCENT if sel else LINE, 1))
            p.setBrush(QColor("#EEF3FC") if sel else WHITE)
            p.drawRoundedRect(rect, 6, 6)
            p.setFont(f(12, bold=sel))
            p.setPen(ACCENT if sel else INK_SOFT)
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), c)

    def draw_slider(self, p, x, y, w, lo, hi, value):
        """绘制一条滑条；value 为当前值"""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E8EAEE"))
        p.drawRoundedRect(QRectF(x, y - 3, w, 6), 3, 3)
        frac = (value - lo) / float(hi - lo) if hi > lo else 0
        p.setBrush(ACCENT)
        p.drawRoundedRect(QRectF(x, y - 3, max(w * frac, 6), 6), 3, 3)
        p.setFont(f(10))
        p.setPen(INK_FAINT)
        p.drawText(QRectF(x, y + 8, 30, 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), str(lo))
        p.drawText(QRectF(x + w - 30, y + 8, 30, 16),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), str(hi))
        kx = x + w * frac
        p.setPen(QPen(ACCENT, 2))
        p.setBrush(WHITE)
        p.drawEllipse(QRectF(kx - 8, y - 8, 16, 16))

    def dlg_rect(self, kind):
        """弹窗矩形（屏幕坐标），自适应窗口大小。

        绘制与点击共用，保证坐标一致。
        """
        specs = {
            "note_create": (520, 260),
            "rename": (440, 220),
            "delay": (500, 400),
            "confirm": (520, 180),
            "settings": (560, 560),
        }
        w, h = specs.get(kind, (520, 260))
        w = min(w, self.W - 60)
        h = min(h, self.H - 60)
        x = (self.W - w) / 2
        y = (self.H - h) / 2
        return x, y, w, h

    def task_max_scroll(self):
        """任务弹窗可滚动的最大距离（内容实际高度约 640）"""
        vh = min(TASK_CONTENT_H, self.H - 80)
        return max(0, 640 - vh)

    def draw_task_dialog(self, p):
        g = self.ddl_rects()
        x, y, w, h = g["dx"], g["dy"], g["vw"], g["vh"]
        sy = g["sy"]
        self.panel(p, x, y, w, h)

        # ---- 标题（固定）
        p.setFont(f(19, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, y + 24, 300, 28),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "创建事务")
        iw = w - 64
        # 内容区（可滚动）：标题下方到按钮栏之间
        body_top = y + 62
        body_bot = y + h - 66
        # 裁剪到内容区，避免溢出到弹窗外
        p.save()
        clip_rect = QRectF(x + 2, body_top, w - 4, body_bot - body_top)
        p.setClipRect(clip_rect)
        self._field_clip = clip_rect
        self.field(p, "task_name", x + 32, sy + 80, iw, "事务名称",
                   "给它起个名字，例如：背单词")
        self.field(p, "task_content", x + 32, sy + 150, iw, "具体内容（必填）",
                   "例如：背 100 个单词")
        self.draw_ddl_picker(p, x + 32, g["by"], iw)
        p.restore()
        self._field_clip = None

        # 滚动提示（内容被裁掉时）
        if self.task_max_scroll() > 0:
            maxs = self.task_max_scroll()
            frac = getattr(self, "task_scroll", 0) / maxs
            p.setPen(QPen(LINE, 1))
            p.setBrush(QColor("#D8DCE1"))
            p.drawRoundedRect(QRectF(x + w - 8, body_top + 4, 3, (body_bot - body_top) - 8), 2, 2)
            th = max(30, (body_bot - body_top - 8) * 0.35)
            ty = body_top + 4 + ((body_bot - body_top - 8) - th) * frac
            p.setBrush(QColor("#9AA1AA"))
            p.drawRoundedRect(QRectF(x + w - 8, ty, 3, th), 2, 2)
            p.setFont(f(10))
            p.setPen(INK_FAINT)
            p.drawText(QRectF(x + w - 46, y + h - 52, 40, 16),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "滚轮")

        self.button(p, x + w - 190, y + h - 58, 78, "取消")
        self.button(p, x + w - 102, y + h - 58, 78, "确定", True)

    def draw_delay_dialog(self, p):
        """预计延期弹窗：快捷选项 + 自定义天数/小时"""
        x, y, w, h = self.dlg_rect("delay")
        self.panel(p, x, y, w, h)
        p.setFont(f(19, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, y + 28, 320, 28),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "预计延期")

        cur = getattr(self, "delay_total", 0) or 0
        added = getattr(self, "delay_added", 0) or 0
        p.setFont(f(13))
        p.setPen(INK_FAINT)
        tip = f"当前累计延时 {DB.fmt_delay(cur)}，可选择追加时长或直接设定总时长"
        p.drawText(QRectF(x + 32, y + 68, w - 64, 22),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), tip)
        if added:
            p.setFont(f(13, bold=True))
            p.setPen(QColor("#E08A2E"))
            p.drawText(QRectF(x + 32, y + 94, w - 64, 20),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"本次追加 {DB.fmt_delay(added)}，延时后总计 {DB.fmt_delay(cur + added)}")

        # 追加快捷选项
        p.setFont(f(13, bold=True))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x + 32, y + 124, 200, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "追加")
        presets = [("2 小时", 2 * 3600), ("6 小时", 6 * 3600), ("半天", 12 * 3600),
                   ("1 天", 86400), ("2 天", 2 * 86400), ("1 周", 7 * 86400)]
        avail = w - 64
        gap = 12
        bw = (avail - gap * 2) / 3      # 按钮宽度自适应
        bx = x + 32
        for i, (label, secs) in enumerate(presets):
            col, row = i % 3, i // 3
            px = bx + col * (bw + gap)
            py = y + 150 + row * 44
            p.setPen(QPen(LINE, 1))
            p.setBrush(WHITE)
            p.drawRoundedRect(QRectF(px, py, bw, 36), 8, 8)
            p.setFont(f(14))
            p.setPen(INK_SOFT)
            p.drawText(QRectF(px, py, bw, 36),
                       int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), label)

        # 自定义
        p.setFont(f(13, bold=True))
        p.setPen(INK_SOFT)
        p.drawText(QRectF(x + 32, y + 248, 200, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "自定义总时长")
        fw = (w - 64 - 14) / 2      # 天数/小时输入框宽度自适应
        self.field(p, "delay_days", x + 32, y + 292, fw, "天数", "0")
        self.field(p, "delay_hours", x + 32 + fw + 14, y + 292, fw, "小时", "0")
        self.button(p, x + w - 190, y + h - 62, 78, "取消")
        self.button(p, x + w - 102, y + h - 62, 78, "确定", True)

    def draw_rename_dialog(self, p):
        is_task = getattr(self, "rename_kind", "note") == "task"
        x, y, w, h = self.dlg_rect("rename")
        self.panel(p, x, y, w, h)
        p.setFont(f(19, bold=True))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, y + 28, 300, 28),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "重命名事务" if is_task else "重命名便签")
        self.field(p, "rename", x + 32, y + 100, w - 64,
                   "事务名称" if is_task else "便签名称",
                   "事务名称" if is_task else "便签名称",
                   getattr(self, "rename_text", ""))
        self.button(p, x + w - 190, y + h - 62, 78, "取消")
        self.button(p, x + w - 102, y + h - 62, 78, "确定", True)

    def draw_confirm(self, p):
        x, y, w, h = self.dlg_rect("confirm")
        self.panel(p, x, y, w, h)
        p.setFont(f(16))
        p.setPen(INK)
        p.drawText(QRectF(x + 32, y + 32, w - 64, 62),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap),
                   self.confirm_payload["text"])
        self.button(p, x + w - 190, y + h - 62, 78, "取消")
        self.button(p, x + w - 102, y + h - 62, 78, "确定", True)

    def draw_toast(self, p):
        p.setFont(f(13))
        w = 320
        h = 40
        if self.overlay:
            # 有弹窗时移到左下角：避开弹窗（居中）与其底部的取消/确定按钮
            x, y = 24, self.H - 76
        else:
            x = (self.W - w) / 2
            y = self.H - 76
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#22262B"))
        p.drawRoundedRect(QRectF(x, y, w, h), 10, 10)
        p.setPen(WHITE)
        p.drawText(QRectF(x, y, w, h),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), self.message)

    # -------------------------------------------------- 交互
    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.overlay in ("note_create", "task_create", "rename"):
                self.submit_current()
                return
            if self.overlay == "delay":
                self.submit_delay()
                return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        """任务弹窗内容过高时支持滚轮滚动；列表页也支持滚轮"""
        delta = e.angleDelta().y()
        if self.overlay == "task_create":
            if delta:
                old = getattr(self, "task_scroll", 0)
                new = max(0, min(self.task_max_scroll(), old - delta // 2))
                if new != old:
                    self.task_scroll = new
                    self.update()
                return
            return
        # 列表页滚动
        if delta and not self.manage and self.page == "notes" and self.notes:
            old = getattr(self, "page_scroll", 0)
            new = max(0, min(self.notes_max_scroll(), old - delta // 2))
            if new != old:
                self.page_scroll = new
                self.update()
            return
        if delta and not self.manage and self.page == "detail" and self.tasks:
            old = getattr(self, "detail_scroll", 0)
            new = max(0, min(self.detail_max_scroll(), old - delta // 2))
            if new != old:
                self.detail_scroll = new
                self.update()
            return
        super().wheelEvent(e)

    def mouseMoveEvent(self, e):
        """滑条拖动"""
        if getattr(self, "_dragging", False) and self.overlay == "task_create":
            x, y = e.position().x(), e.position().y()
            self.handle_slider_drag(x, y)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        """结束滑条拖动"""
        if getattr(self, "_dragging", False):
            self._dragging = False
            return
        super().mouseReleaseEvent(e)

    def hide_edits(self):
        for le in self.edits.values():
            le.hide()

    @staticmethod
    def hit(x, y, r):
        return r.left() <= x <= r.right() and r.top() <= y <= r.bottom()

    def mousePressEvent(self, e):
        x, y = e.position().x(), e.position().y()

        # ---- 滑条拖动（按下即开始）
        if self.overlay == "task_create":
            if self.handle_slider_drag(x, y):
                self._dragging = True
                return

        # ---- 弹窗
        if self.overlay:
            if self.overlay == "note_create":
                dx, dy, dw, dh = self.dlg_rect("note_create")
                if self.hit(x, y, QRectF(dx + dw - 102, dy + dh - 62, 78, 38)):
                    name = self.edits["note_name"].text().strip() or "任务 1"
                    DB.create_note(name)
                    self.close_overlay()
                    self.refresh()
                    self.msg(f"已创建便签「{name}」")
                    return
                if self.hit(x, y, QRectF(dx + dw - 190, dy + dh - 62, 78, 38)):
                    self.close_overlay()
                    return
                return
            if self.overlay == "task_create":
                g = self.ddl_rects()
                dx = g["dx"]
                dy = g["dy"]
                vw, vh = g["vw"], g["vh"]
                # 日历/滑条交互
                if self.handle_ddl_click(x, y, g["bx"], g["by"], g["bw"]):
                    return
                if self.hit(x, y, QRectF(dx + vw - 102, dy + vh - 58, 78, 38)):
                    name = self.edits["task_name"].text().strip() or "未命名事务"
                    content = self.edits["task_content"].text().strip()
                    if not content:
                        self.msg("具体内容为必填项")
                        return
                    if not self.validate_ddl():
                        self.msg("无法创建：DDL 必须晚于当前时间")
                        self.update()
                        return
                    DB.create_task(self.note_id, name, content, self.ddl_date)
                    self.close_overlay()
                    self.refresh()
                    self.msg("已创建事务")
                    return
                if self.hit(x, y, QRectF(dx + vw - 190, dy + vh - 58, 78, 38)):
                    self.close_overlay()
                    return
                return
            if self.overlay == "rename":
                dx, dy, dw, dh = self.dlg_rect("rename")
                if self.hit(x, y, QRectF(dx + dw - 102, dy + dh - 62, 78, 38)):
                    name = self.edits["rename"].text().strip() or "任务 1"
                    DB.rename_note(self.rename_id, name)
                    self.close_overlay()
                    self.refresh()
                    self.msg(f"已重命名为「{name}」")
                    return
                if self.hit(x, y, QRectF(dx + dw - 190, dy + dh - 62, 78, 38)):
                    self.close_overlay()
                    return
                return
            if self.overlay == "delay":
                dx, dy, dw, dh = self.dlg_rect("delay")
                # 快捷追加
                presets = [("2 小时", 2 * 3600), ("6 小时", 6 * 3600), ("半天", 12 * 3600),
                           ("1 天", 86400), ("2 天", 2 * 86400), ("1 周", 7 * 86400)]
                for i, (label, secs) in enumerate(presets):
                    col, row = i % 3, i // 3
                    bw = (dw - 64 - 24) / 3
                    px = dx + 32 + col * (bw + 12)
                    py = dy + 150 + row * 44
                    if self.hit(x, y, QRectF(px, py, bw, 36)):
                        self.delay_added = getattr(self, "delay_added", 0) + secs
                        self.update()
                        return
                # 确定
                if self.hit(x, y, QRectF(dx + dw - 102, dy + dh - 62, 78, 38)):
                    self.submit_delay()
                    return
                if self.hit(x, y, QRectF(dx + dw - 190, dy + dh - 62, 78, 38)):
                    self.close_overlay()
                    return
                return
            if self.overlay == "confirm":
                dx, dy, dw, dh = self.dlg_rect("confirm")
                if self.hit(x, y, QRectF(dx + dw - 102, dy + dh - 62, 78, 38)):
                    fn = self.confirm_payload["action"]
                    self.close_overlay()
                    fn()
                    return
                if self.hit(x, y, QRectF(dx + dw - 190, dy + dh - 62, 78, 38)):
                    self.close_overlay()
                    return
                return
            if self.overlay == "settings":
                self.handle_settings_click(x, y)
                return

        # ---- 记录管理模式
        if self.manage:
            tr = self.title_rect()
            # 头部「完成管理」按钮
            pb = getattr(self, "primary_btn", None)
            if pb and self.hit(x, y, pb):
                self.exit_manage()
                return
            # 底部全选
            sa = getattr(self, "manage_select_all", None)
            if sa and self.hit(x, y, sa):
                items = getattr(self, "manage_items", [])
                if self.manage_sel and len(self.manage_sel) == len(items):
                    self.manage_sel = set()
                else:
                    self.manage_sel = {it["id"] for it in items}
                self.update()
                return
            # 底部删除
            db_ = getattr(self, "manage_del_btn", None)
            if db_ and self.hit(x, y, db_):
                self.confirm_manage_delete()
                return
            # 统计页「清空归档记录」
            cb = getattr(self, "manage_clear_btn", None)
            if cb and self.hit(x, y, cb):
                self.open_confirm(
                    "将清空全部已结束记录（已完成、延期、放弃），此操作不可恢复，确定继续吗？",
                    self.do_clear_archived)
                return
            # 列表行勾选
            for it, r in getattr(self, "manage_row_rects", []):
                if self.hit(x, y, r):
                    if it["id"] in self.manage_sel:
                        self.manage_sel.discard(it["id"])
                    else:
                        self.manage_sel.add(it["id"])
                    self.update()
                    return
            return

        # ---- 菜单
        if self.menu:
            kind, oid = self.menu
            if kind == "note":
                mx, my = self.menu_pos
                mw, mh = 148, 88
                if self.hit(x, y, QRectF(mx, my, mw, mh)):
                    idx = 0 if y < my + 4 + 40 else 1
                    self.menu = None
                    self.update()
                    if idx == 0:
                        self.open_rename(oid)
                    else:
                        n = DB.get_note(oid)
                        cnt = n["pending_cnt"] if n else 0
                        total = DB.count_tasks(oid)
                        archived = total - cnt
                        if archived > 0:
                            extra = (f"，该便签下还有 {archived} 个已结束事务"
                                     "（已完成/延期/放弃），将保留在对应分类中并继续计入统计")
                        else:
                            extra = ""
                        self.open_confirm(
                            f"该便签下有 {cnt} 个未完成事务{extra}。"
                            "删除便签与未完成事务后将无法恢复，确定删除吗？",
                            lambda: self.do_delete_note(oid))
                    return
                self.menu = None
                self.update()
                return
            else:
                t = DB.get_task(oid)
                overdue = DB.remaining(t)[0] if t else False
                labels = ["重命名", "完成", "取消"] if overdue else ["重命名", "完成", "预计延期", "取消"]
                mx, my = self.menu_pos
                mw = 156
                mh = 40 * len(labels) + 8
                if self.hit(x, y, QRectF(mx, my, mw, mh)):
                    idx = int((y - my - 4) // 40)
                    label = labels[min(idx, len(labels) - 1)]
                    self.menu = None
                    self.update()
                    if label == "重命名":
                        self.open_task_rename(oid)
                        return
                    if label == "完成":
                        DB.complete_task(oid)
                        self.msg("已完成")
                    elif label == "预计延期":
                        self.open_delay_dialog(oid)
                        return
                    else:
                        DB.cancel_task(oid)
                        self.msg("已取消，归入放弃")
                    self.refresh()
                    return
                self.menu = None
                self.update()
                return

        # ---- 头部主按钮
        tr = self.title_rect()
        pb, mb, sb = self.header_btns()
        if (pb and self.page in ("notes", "detail")
                and not self.manage
                and not (self.page == "notes" and not self.notes)
                and self.hit(x, y, pb)):
            if self.page == "notes":
                self.open_note_dialog()
            else:
                self.open_task_dialog()
            self.update()
            return

        # ---- 头部「管理」按钮
        if mb and self.hit(x, y, mb):
            self.enter_manage()
            return

        # ---- 头部「设置」齿轮按钮
        if self.hit(x, y, sb):
            self.open_settings()
            return

        # ---- tab
        for item in self.tab_labels():
            name, r = item[0], item[1]
            if name == "__sep__":
                continue
            if self.hit(x, y, r):
                self.tab = TABS.index(name)
                self.page = ["notes", "done", "done", "done", "stats"][self.tab]
                self.menu = None
                self.manage = False       # 切换 tab 时退出管理模式
                self.manage_tab = None
                self.manage_sel = set()
                self.page_scroll = 0
                self.refresh()
                self.update()
                return

        cr = self.content_rect()
        if self.page == "notes":
            if self.notes:
                for n, cx0, ry, cw in self.notes_grid():
                    if ry + 118 < cr.top() or ry > cr.bottom():
                        continue
                    if self.hit(x, y, QRectF(cx0 + cw - 96, ry + 74, 78, 32)):
                        self.page = "detail"
                        self.note_id = n["id"]
                        self.refresh()
                        self.update()
                        return
                    if self.hit(x, y, QRectF(cx0 + cw - 88, ry + 8, 68, 28)):
                        self.menu = ("note", n["id"])
                        self.menu_pos = (cx0 + cw - 152, ry + 42)
                        self.update()
                        return
                    if self.hit(x, y, QRectF(cx0, ry, cw - 56, 74)):
                        self.page = "detail"
                        self.note_id = n["id"]
                        self.refresh()
                        self.update()
                        return
            else:
                eb = getattr(self, "empty_btn", None)
                if eb and eb[0] <= x <= eb[0] + eb[2] and eb[1] <= y <= eb[1] + eb[3]:
                    self.open_note_dialog()
                    return
        elif self.page == "detail":
            bb = getattr(self, "back_btn", None)
            if bb and self.hit(x, y, bb):
                self.page = "notes"
                self.note_id = None
                self.refresh()
                self.update()
                return
            ry = cr.top() + 62 - getattr(self, "detail_scroll", 0)
            for t in self.tasks:
                if self.hit(x, y, QRectF(cr.left() + cr.width() - 88, ry + 16, 68, 28)):
                    self.menu = ("task", t["id"])
                    self.menu_pos = (cr.left() + cr.width() - 162, ry + 48)
                    self.update()
                    return
                ry += 98
        elif self.page == "stats":
            bx = cr.left() + 340 + 18
            bw = cr.width() - 340 - 18
            if self.hit(x, y, QRectF(bx + bw - 92, cr.top() + 116 + 14, 70, 26)):
                self.bar_mode = "week" if self.bar_mode == "month" else "month"
                self.update()

    def close_overlay(self):
        self.overlay = None
        self.menu = None
        self.confirm_payload = None
        self.hide_edits()
        self.update()

    def open_settings(self):
        """打开设置弹窗"""
        self.overlay = "settings"
        self.setting_draft = S.load()
        self.setting_size_val = self.setting_draft.get("sticky_size", 220)
        self.setting_opacity_val = self.setting_draft.get("sticky_opacity", 1.0)
        self.update()

    def handle_settings_click(self, x, y):
        """设置弹窗内的点击处理"""
        dx, dy, dw, dh = self.dlg_rect("settings")

        # 开关
        sw = getattr(self, "setting_switch", None)
        if sw and self.hit(x, y, sw[0]):
            key = sw[1]
            self.setting_draft[key] = not self.setting_draft.get(key)
            self.update()
            return

        # 皮肤
        for key, r in getattr(self, "setting_skins", []):
            if self.hit(x, y, r):
                self.setting_draft["skin"] = key
                self.update()
                return

        # 尺寸滑条
        st = getattr(self, "setting_size_track", None)
        if st and st.top() - 14 <= y <= st.bottom() + 14:
            frac = self.slider_value_at(x, (st.left(), st.top(), st.width()))
            self.setting_size_val = int(160 + frac * (420 - 160))
            self.setting_draft["sticky_size"] = self.setting_size_val
            self.update()
            return

        # 不透明度滑条
        op = getattr(self, "setting_opacity_track", None)
        if op and op.top() - 14 <= y <= op.bottom() + 14:
            frac = self.slider_value_at(x, (op.left(), op.top(), op.width()))
            self.setting_opacity_val = round(30 + frac * 70) / 100.0
            self.setting_draft["sticky_opacity"] = self.setting_opacity_val
            self.update()
            return

        # 底部按钮
        if self.hit(x, y, QRectF(dx + dw - 190, dy + dh - 62, 78, 38)):
            self.close_overlay()
            return
        if self.hit(x, y, QRectF(dx + dw - 102, dy + dh - 62, 78, 38)):
            self.save_settings()
            return

    def save_settings(self):
        """保存设置并同步桌面实体便签"""
        draft = dict(getattr(self, "setting_draft", {}))
        draft["sticky_size"] = int(getattr(self, "setting_size_val", 220))
        draft["sticky_opacity"] = float(getattr(self, "setting_opacity_val", 1.0))
        S.save(draft)
        self.close_overlay()
        self.refresh()
        self.sync_desktop_sticky()
        self.msg("设置已保存")

    def sync_desktop_sticky(self):
        """根据设置启动 / 停止桌面实体便签进程"""
        want = S.get("desktop_sticky")
        running = self.sticky_proc is not None and self.sticky_proc.poll() is None
        if want and not running:
            self.start_sticky()
        elif not want and running:
            self.stop_sticky()
        elif want and running:
            # 已运行：重启以应用新的皮肤 / 尺寸
            self.stop_sticky()
            self.start_sticky()

    def start_sticky(self):
        """启动桌面实体便签子进程"""
        if self.sticky_proc is not None and self.sticky_proc.poll() is None:
            return
        try:
            import subprocess
            CREATE_NO_WINDOW = 0x08000000
            if getattr(sys, "frozen", False):
                # 打包后：用当前 exe 以 --sticky 模式启动子进程
                cmd = [sys.executable, "--sticky"]
                cwd = None
            else:
                # 源码运行：直接用源码目录的 sticky_view.py 启动
                src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "sticky_view.py")
                if not os.path.exists(src):
                    self.msg("实体便签脚本缺失，无法启动")
                    return
                cmd = [sys.executable, src]
                cwd = os.path.dirname(src)
            self.sticky_proc = subprocess.Popen(
                cmd, cwd=cwd, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.msg(f"实体便签启动失败：{e}")

    def stop_sticky(self):
        """停止桌面实体便签子进程"""
        if self.sticky_proc is not None:
            try:
                self.sticky_proc.terminate()
                self.sticky_proc.wait(timeout=3)
            except Exception:
                try:
                    self.sticky_proc.kill()
                except Exception:
                    pass
            self.sticky_proc = None

    def open_rename(self, note_id):
        self.overlay = "rename"
        self.rename_kind = "note"
        self.rename_id = note_id
        n = DB.get_note(note_id)
        self.rename_text = n["name"] if n else ""
        self.edits.pop("rename", None)
        self._focus_key = "rename"
        self.update()

    def open_task_rename(self, task_id):
        self.overlay = "rename"
        self.rename_kind = "task"
        self.rename_id = task_id
        t = DB.get_task(task_id)
        self.rename_text = t["name"] if t else ""
        self.edits.pop("rename", None)
        self._focus_key = "rename"
        self.update()

    def validate_ddl(self):
        """校验 DDL 必须晚于当前时间，并写入错误提示"""
        if self.ddl_date <= datetime.now():
            self.ddl_error = "DDL 必须晚于当前时间，请选择将来的时间"
            return False
        self.ddl_error = ""
        return True

    def set_pick_time(self, hour, minute):
        """设置所选时间（小时 0-23，分钟 0-59），并同步到 ddl_date"""
        self.pick_hour = max(0, min(23, int(hour)))
        self.pick_minute = max(0, min(59, int(minute)))
        self.ddl_date = self.ddl_date.replace(hour=self.pick_hour,
                                             minute=self.pick_minute,
                                             second=0, microsecond=0)
        self.validate_ddl()
        self.update()

    def slider_value_at(self, x, track):
        """把鼠标 x 坐标换算为滑条值"""
        tx, ty, tw = track
        frac = (x - tx) / float(tw) if tw else 0
        frac = max(0.0, min(1.0, frac))
        return frac

    def handle_slider_drag(self, x, y):
        """滑条按下/拖动。返回 True 表示已处理"""
        g = self.ddl_rects()
        for track, lo, hi, getter in ((g["h_track"], 0, 23, "hour"),
                                      (g["m_track"], 0, 59, "minute")):
            tx, ty, tw = track
            if y >= ty - 18 and y <= ty + 18 and x >= tx - 12 and x <= tx + tw + 12:
                frac = self.slider_value_at(x, track)
                v = lo + round(frac * (hi - lo))
                if getter == "hour":
                    self.set_pick_time(v, self.pick_minute)
                else:
                    self.set_pick_time(self.pick_hour, v)
                return True
        return False

    def handle_ddl_click(self, x, y, bx, by, bw):
        """DDL 选择器点击：月份翻页 / 选日期 / 拖动滑条 / 常用时间。返回 True 表示已处理"""
        g = self.ddl_rects()
        cy = g["cal_y"]
        # 滑条（可拖动）
        if self.handle_slider_drag(x, y):
            return True
        # 月份翻页
        if self.hit(x, y, QRectF(bx + bw - 82, cy + 6, 30, 26)):
            self.cal_month -= 1
            if self.cal_month < 1:
                self.cal_month = 12
                self.cal_year -= 1
            self.update()
            return True
        if self.hit(x, y, QRectF(bx + bw - 50, cy + 6, 30, 26)):
            self.cal_month += 1
            if self.cal_month > 12:
                self.cal_month = 1
                self.cal_year += 1
            self.update()
            return True
        # 日期格子（过去的日期不可选）
        cell_w = (bw - 24) / 7
        today = datetime.now().date()
        for ri, row in enumerate(month_grid(self.cal_year, self.cal_month)):
            for ci, d in enumerate(row):
                if d is None:
                    continue
                rect = QRectF(bx + 12 + ci * cell_w, cy + 56 + ri * 24, cell_w - 4, 22)
                if self.hit(x, y, rect):
                    if datetime(self.cal_year, self.cal_month, d).date() < today:
                        # 过去的日期：不允许选择，直接提示
                        self.ddl_error = "不能选择过去的日期，请选择今天或之后的日期"
                        self.update()
                        return True
                    try:
                        self.ddl_date = self.ddl_date.replace(year=self.cal_year,
                                                            month=self.cal_month,
                                                            day=d)
                    except ValueError:
                        # 该月没有这一天（如 2/30），退到当月最后一天
                        import calendar as _cal
                        last = _cal.monthrange(self.cal_year, self.cal_month)[1]
                        self.ddl_date = self.ddl_date.replace(year=self.cal_year,
                                                            month=self.cal_month,
                                                            day=min(d, last))
                    self.validate_ddl()
                    self.update()
                    return True
        # 常用时间
        for i, c in enumerate(["09:00", "12:00", "18:00", "21:00", "23:00"]):
            rect = QRectF(bx + 52 + i * 84, g["chips_y"], 76, 26)
            if self.hit(x, y, rect):
                hh, mm = c.split(":")
                self.set_pick_time(int(hh), int(mm))
                return True
        return False

    def open_delay_dialog(self, task_id):
        """打开预计延期弹窗"""
        self.overlay = "delay"
        self.delay_id = task_id
        t = DB.get_task(task_id)
        self.delay_total = DB.delay_seconds(t) if t else 0
        self.delay_added = 0
        self.edits.pop("delay_days", None)
        self.edits.pop("delay_hours", None)
        self.update()

    def open_note_dialog(self):
        """打开创建便签弹窗：清空上次输入"""
        self.overlay = "note_create"
        self.edits.pop("note_name", None)
        self._focus_key = "note_name"
        self.update()

    def open_task_dialog(self):
        """打开创建事务弹窗：清空上次输入"""
        self.overlay = "task_create"
        for k in ("task_name", "task_content", "task_ddl"):
            self.edits.pop(k, None)
        self.ddl_date = default_ddl()
        self.cal_year = self.ddl_date.year
        self.cal_month = self.ddl_date.month
        self.pick_hour = self.ddl_date.hour
        self.pick_minute = self.ddl_date.minute
        self.ddl_error = ""
        self.task_scroll = 0
        self._focus_key = "task_name"
        self.update()

    def submit_current(self):
        """回车提交当前弹窗"""
        if self.overlay == "note_create":
            name = self.edits["note_name"].text().strip() or "任务 1"
            DB.create_note(name)
            self.close_overlay()
            self.refresh()
            self.msg(f"已创建便签「{name}」")
        elif self.overlay == "task_create":
            name = self.edits["task_name"].text().strip() or "未命名事务"
            content = self.edits["task_content"].text().strip()
            if not content:
                self.msg("具体内容为必填项")
                return
            if not self.validate_ddl():
                self.msg("无法创建：DDL 必须晚于当前时间")
                self.update()
                return
            DB.create_task(self.note_id, name, content, self.ddl_date)
            self.close_overlay()
            self.refresh()
            self.msg("已创建事务")
        elif self.overlay == "rename":
            name = self.edits["rename"].text().strip()
            if getattr(self, "rename_kind", "note") == "task":
                if not name:
                    self.msg("事务名称不能为空")
                    return
                DB.rename_task(self.rename_id, name)
                self.close_overlay()
                self.refresh()
                self.msg(f"已重命名为「{name}」")
                return
            name = name or "任务 1"
            DB.rename_note(self.rename_id, name)
            self.close_overlay()
            self.refresh()
            self.msg(f"已重命名为「{name}」")

    def submit_delay(self):
        """确定延时：自定义总时长优先，否则用快捷追加累计"""
        tid = getattr(self, "delay_id", None)
        if not tid:
            self.close_overlay()
            return
        base = getattr(self, "delay_total", 0) or 0
        added = getattr(self, "delay_added", 0) or 0
        d_txt = (self.edits.get("delay_days").text().strip() if self.edits.get("delay_days") else "")
        h_txt = (self.edits.get("delay_hours").text().strip() if self.edits.get("delay_hours") else "")
        custom = None
        if d_txt or h_txt:
            try:
                d = int(d_txt) if d_txt else 0
                h = int(h_txt) if h_txt else 0
            except ValueError:
                self.msg("天数/小时请填数字")
                return
            if d < 0 or h < 0:
                self.msg("天数/小时不能为负")
                return
            custom = d * 86400 + h * 3600
        if custom is not None:
            DB.set_delay(tid, custom)
            total = custom
        else:
            total = base + added
            DB.set_delay(tid, total)
        self.close_overlay()
        self.refresh()
        self.msg(f"已延时 {DB.fmt_delay(total)}")

    def open_confirm(self, text, action):
        self.overlay = "confirm"
        self.confirm_payload = {"text": text, "action": action}
        self.update()

    def do_delete_note(self, note_id):
        DB.delete_note(note_id)
        self.refresh()
        self.msg("便签已删除")

    def confirm_manage_delete(self):
        """管理模式下的批量删除确认"""
        sel = sorted(self.manage_sel)
        if not sel:
            self.msg("请先选择要删除的记录")
            return
        tab = self.manage_tab if self.manage_tab is not None else self.tab
        if tab == 0:
            text = (f"将删除 {len(sel)} 个便签及其未完成事务，"
                    "已结束的事务（已完成/延期/放弃）会保留在对应分类中，确定删除吗？")
        else:
            names = {0: "已完成", 1: "延期", 2: "放弃"}
            text = (f"将删除 {len(sel)} 条{names.get(tab - 1, '')}记录，"
                    "删除后不可恢复且不再计入统计，确定删除吗？")
        self.open_confirm(text, self.do_manage_delete)

    def do_manage_delete(self):
        sel = sorted(self.manage_sel)
        tab = self.manage_tab if self.manage_tab is not None else self.tab
        if tab == 0:
            n = DB.delete_notes(sel)
            self.msg(f"已删除 {n} 个便签")
        else:
            n = DB.delete_tasks(sel)
            self.msg(f"已删除 {n} 条记录")
        self.manage_sel = set()
        self.refresh()
        self.update()

    def do_clear_archived(self):
        """清空全部已结束记录（已完成/延期/放弃）"""
        ids = []
        for st in (DB.STATUS_DONE, DB.STATUS_DELAYED, DB.STATUS_ABANDONED):
            ids.extend(t["id"] for t in DB.list_tasks_with_note(status=st))
        n = DB.delete_tasks(ids)
        self.manage_sel = set()
        self.refresh()
        self.msg(f"已清空 {n} 条归档记录")


def show_note_flag(t):
    return bool(t.get("note_name"))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agenda")
        self.setStyleSheet("background:#F4F5F7;")
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)
        self.resize(W, H)
        # 允许拖拽调整窗口大小
        self.setMinimumSize(MIN_W, MIN_H)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 尺寸变化时重新布局（输入框位置由 paintEvent 同步）
        self.canvas.update()


def main():
    # 子进程模式：仅显示桌面实体便签
    if "--sticky" in sys.argv:
        import sticky_view
        sticky_view.main()
        return
    DB.init_db()
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    # 根据设置自动启动 / 停止桌面实体便签
    if S.get("desktop_sticky"):
        w.canvas.start_sticky()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
