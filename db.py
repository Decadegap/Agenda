# -*- coding: utf-8 -*-
"""Agenda 数据库层：SQLite + Python"""
import os
import sqlite3
from datetime import datetime, timedelta

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Agenda")
DB_PATH = os.path.join(APP_DIR, "agenda.db")

STATUS_PENDING = "pending"
STATUS_DONE = "done"          # 按时完成
STATUS_DELAYED = "delayed"    # 延期（超时完成 / 延期后完成）
STATUS_ABANDONED = "abandoned"  # 放弃（取消）

DELAY_DAYS_PER_POSTPONE = 1
DELAY_SECONDS_PER_POSTPONE = 24 * 3600


def now():
    return datetime.now()


def _connect():
    os.makedirs(APP_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _needs_task_migration(conn, cols):
    """判断 tasks 表是否需要重建（旧库：note_id NOT NULL + 外键级联）"""
    if "note_name" in cols:
        # 已有 note_name 列，但可能仍带 NOT NULL / 级联外键，需检查
        pass
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
    if not sql or not sql[0]:
        return False
    ddl = sql[0]
    if "ON DELETE CASCADE" in ddl:
        return True
    for r in conn.execute("PRAGMA table_info(tasks)").fetchall():
        if r[1] == "note_id" and r[3]:   # notnull
            return True
    return False


def _migrate_tasks_table(conn):
    """重建 tasks 表：note_id 可为空、无外键级联，并补上 note_name 冗余列

    保留全部已有数据；note_name 从原便签名回填。
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ALTER TABLE tasks RENAME TO tasks_old")
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            ddl TEXT NOT NULL,
            delay_days INTEGER NOT NULL DEFAULT 0,
            delay_seconds INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created TEXT NOT NULL,
            finished TEXT,
            note_name TEXT
        )""")
    old_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks_old)").fetchall()]
    has_ds = "delay_seconds" in old_cols
    ds_expr = "delay_seconds" if has_ds else "delay_days * 86400"
    conn.execute(f"""
        INSERT INTO tasks (id, note_id, name, content, ddl, delay_days, delay_seconds,
                           status, created, finished, note_name)
        SELECT t.id, t.note_id, t.name, t.content, t.ddl, t.delay_days,
               {ds_expr}, t.status, t.created, t.finished, n.name
        FROM tasks_old t LEFT JOIN notes n ON n.id = t.note_id""")
    conn.execute("DROP TABLE tasks_old")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_note ON tasks(note_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("PRAGMA foreign_keys = ON")


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                ddl TEXT NOT NULL,
                delay_days INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created TEXT NOT NULL,
                finished TEXT,
                note_name TEXT
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_note ON tasks(note_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        # 迁移：延时改为精确到秒
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "delay_seconds" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN delay_seconds INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE tasks SET delay_seconds = delay_days * 86400")
        else:
            conn.execute("UPDATE tasks SET delay_seconds = delay_days * 86400"
                         " WHERE delay_seconds = 0 AND delay_days > 0")
        # 迁移：便签删除后归档事务需要保留，故 tasks 不再外键级联、note_id 可为空
        # 旧库需要重建表（SQLite 无法直接改外键/非空约束）
        if _needs_task_migration(conn, cols):
            _migrate_tasks_table(conn)


# ---------------- 便签 ----------------
def list_notes():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT n.id, n.name, n.created,"
            " (SELECT COUNT(*) FROM tasks t WHERE t.note_id = n.id AND t.status='pending') AS pending_cnt"
            " FROM notes n ORDER BY n.id ASC").fetchall()
        return [dict(r) for r in rows]


def get_note(note_id):
    with _connect() as conn:
        r = conn.execute(
            "SELECT n.*, (SELECT COUNT(*) FROM tasks t WHERE t.note_id=n.id AND t.status='pending')"
            " AS pending_cnt FROM notes n WHERE n.id=?", (note_id,)).fetchone()
        return dict(r) if r else None


def create_note(name):
    name = (name or "").strip() or "任务 1"
    with _connect() as conn:
        cur = conn.execute("INSERT INTO notes(name, created) VALUES(?,?)",
                            (name, now().strftime("%Y-%m-%d %H:%M:%S")))
        return cur.lastrowid


def rename_note(note_id, name):
    name = (name or "").strip() or "任务 1"
    with _connect() as conn:
        conn.execute("UPDATE notes SET name=? WHERE id=?", (name, note_id))
        # 同步更新事务上的便签冗余名（分类页显示用）
        conn.execute("UPDATE tasks SET note_name=? WHERE note_id=?", (name, note_id))


def delete_note(note_id):
    """取缔便签：只删便签本身和它名下**未完成**的事务

    业务规则（策划案）：已完成/延期/放弃的事务已移出便签，
    属于全局归档记录，**不受便签取缔影响**，仍留在对应分类 tab
    并继续计入统计。

    实现：先把归档事务的 note_id 置空（保留记录，并记下当时的便签名），
    再删掉便签与其下的 pending 事务。
    """
    with _connect() as conn:
        row = conn.execute("SELECT name FROM notes WHERE id=?", (note_id,)).fetchone()
        note_name = row[0] if row else None
        # 归档事务（done/delayed/abandoned）脱离便签，但保留下来
        conn.execute("""
            UPDATE tasks SET note_id = NULL, note_name = COALESCE(note_name, ?)
            WHERE note_id = ? AND status <> 'pending'""", (note_name, note_id))
        # 未完成事务随便签一起删除
        conn.execute("DELETE FROM tasks WHERE note_id=? AND status='pending'", (note_id,))
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))


def delete_tasks(task_ids):
    """按 id 列表批量物理删除事务（用于分类页的记录管理）"""
    ids = [int(i) for i in (task_ids or [])]
    if not ids:
        return 0
    qs = ",".join("?" * len(ids))
    with _connect() as conn:
        cur = conn.execute(f"DELETE FROM tasks WHERE id IN ({qs})", ids)
        return cur.rowcount


def delete_notes(note_ids):
    """按 id 列表批量取缔便签：同样只删未完成事务，归档事务保留"""
    ids = [int(i) for i in (note_ids or [])]
    if not ids:
        return 0
    qs = ",".join("?" * len(ids))
    with _connect() as conn:
        # 归档事务脱离便签并保留
        conn.execute(f"""
            UPDATE tasks SET note_id = NULL,
                note_name = COALESCE(note_name, (SELECT n.name FROM notes n WHERE n.id = tasks.note_id))
            WHERE note_id IN ({qs}) AND status <> 'pending'""", ids)
        # 未完成事务删除
        conn.execute(f"DELETE FROM tasks WHERE note_id IN ({qs}) AND status='pending'", ids)
        conn.execute(f"DELETE FROM notes WHERE id IN ({qs})", ids)
        return len(ids)


def purge_orphan_tasks():
    """清理孤儿事务

    两种情况属于脏数据，应清理：
      1. note_id 非空但指向已不存在的便签（旧库脏数据）
      2. note_id 为空且仍是 pending（未完成却没归属）

    注意：**已归档的事务（done/delayed/abandoned）note_id 为空是正常的**，
    它们是全局记录，不应被清理。
    """
    with _connect() as conn:
        cur = conn.execute("""
            DELETE FROM tasks
            WHERE (note_id IS NOT NULL AND note_id NOT IN (SELECT id FROM notes))
               OR (note_id IS NULL AND status='pending')""")
        return cur.rowcount


# ---------------- 事务 ----------------
def list_tasks(note_id=None, status=None, desc=False, only_pending=False):
    sql = "SELECT * FROM tasks"
    args = []
    cond = []
    if note_id is not None:
        cond.append("note_id=?")
        args.append(note_id)
    if status is not None:
        cond.append("status=?")
        args.append(status)
    if only_pending:
        cond.append("status='pending'")
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY id " + ("DESC" if desc else "ASC")
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]


def list_tasks_with_note(status=None):
    """分类页用：带便签名的任务列表

    归档事务在便签被取缔后，note_id 会置空，但其 note_name 冗余列仍
    记录着当时的便签名，因此分类页仍能显示「来自哪个便签」。
    """
    sql = ("SELECT t.*, COALESCE(n.name, t.note_name) AS note_name FROM tasks t "
           "LEFT JOIN notes n ON n.id = t.note_id")
    args = []
    if status is not None:
        sql += " WHERE t.status=?"
        args.append(status)
    sql += " ORDER BY COALESCE(t.finished, t.created) DESC, t.id DESC"
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def count_tasks(note_id):
    """便签下全部事务数（含已完成/延期/放弃）"""
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM tasks WHERE note_id=?",
                            (note_id,)).fetchone()[0]


def get_task(task_id):
    with _connect() as conn:
        r = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(r) if r else None


def create_task(note_id, name, content, ddl):
    name = (name or "").strip() or "未命名事务"
    content = (content or "").strip()
    with _connect() as conn:
        # 冗余记下当时的便签名，便签被取缔后分类页仍能显示来源
        row = conn.execute("SELECT name FROM notes WHERE id=?", (note_id,)).fetchone()
        note_name = row[0] if row else None
        cur = conn.execute(
            "INSERT INTO tasks(note_id, name, content, ddl, delay_days, status, created, note_name)"
            " VALUES(?,?,?,?,0,?,?,?)",
            (note_id, name, content, ddl.strftime("%Y-%m-%d %H:%M:%S"),
             STATUS_PENDING, now().strftime("%Y-%m-%d %H:%M:%S"), note_name))
        return cur.lastrowid


def rename_task(task_id, name):
    name = (name or "").strip()
    if not name:
        return
    with _connect() as conn:
        conn.execute("UPDATE tasks SET name=? WHERE id=?", (name, task_id))


def effective_ddl(task):
    """红字倒计时判定基准：原始 DDL + 累计延时（精确到秒）"""
    base = datetime.strptime(task["ddl"], "%Y-%m-%d %H:%M:%S")
    return base + timedelta(seconds=delay_seconds(task))


def delay_seconds(task):
    """累计延时秒数"""
    s = task.get("delay_seconds", 0) or 0
    if not s:
        s = (task.get("delay_days", 0) or 0) * 86400
    return int(s)


def fmt_delay(secs):
    """累计延时格式化：'3天2小时' / '5小时30分' / '45分'"""
    secs = int(max(0, secs))
    if secs <= 0:
        return "0分"
    d, rem = secs // 86400, secs % 86400
    h, rem = rem // 3600, rem % 3600
    m = rem // 60
    if d:
        return f"{d}天{h}小时" if h else f"{d}天"
    if h:
        return f"{h}小时{m}分" if m else f"{h}小时"
    return f"{m}分"


def remaining(task, ref=None):
    """返回 (是否超时, 剩余秒数)"""
    ref = ref or now()
    delta = (effective_ddl(task) - ref).total_seconds()
    return (delta < 0, abs(delta))


def complete_task(task_id):
    """完成：未超时 -> 按时完成(done)；已超时 -> 延期(delayed)"""
    t = get_task(task_id)
    if not t:
        return
    overdue, _ = remaining(t)
    status = STATUS_DELAYED if overdue else STATUS_DONE
    with _connect() as conn:
        conn.execute("UPDATE tasks SET status=?, finished=? WHERE id=?",
                     (status, now().strftime("%Y-%m-%d %H:%M:%S"), task_id))


def postpone_task(task_id, seconds=DELAY_SECONDS_PER_POSTPONE):
    """预计延期：红字倒计时顺延，可指定时长（秒），多次调用累加"""
    seconds = int(seconds)
    if seconds <= 0:
        return
    with _connect() as conn:
        conn.execute(
            "UPDATE tasks SET delay_seconds = delay_seconds + ?,"
            " delay_days = CAST((delay_seconds + ?) / 86400 AS INTEGER) WHERE id=?",
            (seconds, seconds, task_id))


def postpone_task_days(task_id, days):
    postpone_task(task_id, int(days) * 86400)


def set_delay(task_id, seconds):
    """直接设置累计延时总秒数（覆盖）"""
    seconds = max(0, int(seconds))
    with _connect() as conn:
        conn.execute(
            "UPDATE tasks SET delay_seconds = ?, delay_days = CAST(? / 86400 AS INTEGER)"
            " WHERE id=?", (seconds, seconds, task_id))


def cancel_task(task_id):
    """取消 -> 放弃"""
    with _connect() as conn:
        conn.execute("UPDATE tasks SET status=?, finished=? WHERE id=?",
                     (STATUS_ABANDONED, now().strftime("%Y-%m-%d %H:%M:%S"), task_id))


# ---------------- 统计 ----------------
def stats():
    """仅统计已完成/延期/放弃的事务（便签内未结束事务不计）"""
    with _connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) c FROM tasks GROUP BY status").fetchall()
    m = {r["status"]: r["c"] for r in rows}
    done = m.get(STATUS_DONE, 0)
    delayed = m.get(STATUS_DELAYED, 0)
    abandoned = m.get(STATUS_ABANDONED, 0)
    total = done + delayed + abandoned
    pct = lambda x: (x * 100.0 / total) if total else 0.0
    return {
        "total": total,
        "done": done,
        "delayed": delayed,
        "abandoned": abandoned,
        "done_rate": pct(done),
        "delayed_rate": pct(delayed),
        "abandoned_rate": pct(abandoned),
    }


def created_buckets(mode="month"):
    """按月/周统计新建事务数量，用于柱状图"""
    with _connect() as conn:
        rows = conn.execute("SELECT created FROM tasks ORDER BY created").fetchall()
    pts = [datetime.strptime(r["created"], "%Y-%m-%d %H:%M:%S") for r in rows]
    ref = now()
    buckets = []
    if mode == "month":
        for i in range(5, -1, -1):
            y, m = ref.year, ref.month - i
            while m <= 0:
                m += 12
                y -= 1
            buckets.append((f"{y}-{m:02d}",
                            [p for p in pts if p.year == y and p.month == m]))
    else:
        for i in range(7, -1, -1):
            d0 = (ref - timedelta(days=7 * i + ref.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
            d1 = d0 + timedelta(days=7)
            buckets.append((f"{d0.strftime('%m-%d')}",
                            [p for p in pts if d0 <= p < d1]))
    return [(label, len(items)) for label, items in buckets]


if __name__ == "__main__":
    init_db()
    print("db ready:", DB_PATH)
