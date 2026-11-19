# -*- coding: utf-8 -*-
"""便签取缔语义回归（用户纠正后的正确规则）

规则：取缔便签时
  - 便签本身：删除
  - 该便签名下**未完成**（pending）的事务：删除
  - 已进入已完成/延期/放弃分类的事务：**保留**，继续显示在对应 tab 并计入统计

同时验证：旧库（含 ON DELETE CASCADE 的旧 schema）能自动迁移。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as DB

ok = True


def check(label, cond):
    global ok
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        ok = False


def fresh_db():
    """用临时库跑，避免污染真实数据库"""
    tmp = tempfile.mkdtemp()
    DB.APP_DIR = tmp
    DB.DB_PATH = os.path.join(tmp, "agenda.db")
    DB.init_db()
    return tmp


def make_case():
    """建便签 + 4 状态事务"""
    nid = DB.create_note("测试便签")
    t_done = DB.create_task(nid, "按时完成", "c", datetime.now() + timedelta(days=1))
    t_over = DB.create_task(nid, "超时完成", "c", datetime.now() - timedelta(days=1))
    t_ab = DB.create_task(nid, "取消", "c", datetime.now() + timedelta(days=1))
    t_pend = DB.create_task(nid, "未完成", "c", datetime.now() + timedelta(days=1))
    DB.complete_task(t_done)
    DB.complete_task(t_over)
    DB.cancel_task(t_ab)
    return nid, t_done, t_over, t_ab, t_pend


def counts():
    return (len(DB.list_tasks_with_note(status=DB.STATUS_DONE)),
            len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED)),
            len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED)),
            len(DB.list_tasks(status=DB.STATUS_PENDING)))


print("=== A. 取缔便签：归档事务保留，未完成事务删除 ===")
fresh_db()
nid, t_done, t_over, t_ab, t_pend = make_case()
print("  取缔前 done/delayed/abandoned/pending =", counts())
check("取缔前四类齐全", counts() == (1, 1, 1, 1))

DB.delete_note(nid)
after = counts()
print("  取缔后 done/delayed/abandoned/pending =", after)
check("已完成记录保留", after[0] == 1)
check("延期记录保留", after[1] == 1)
check("放弃记录保留", after[2] == 1)
check("未完成事务被删除", after[3] == 0)
check("便签本身已删除", DB.get_note(nid) is None)
check("数据库中 pending 事务为 0", len(DB.list_tasks(status=DB.STATUS_PENDING)) == 0)

print("=== B. 保留的归档事务仍显示在分类页，并带原便签名 ===")
done_list = DB.list_tasks_with_note(status=DB.STATUS_DONE)
check("已完成页仍有 1 条", len(done_list) == 1)
check("记录名称正确", done_list[0]["name"] == "按时完成")
check("仍显示原便签名", done_list[0]["note_name"] == "测试便签")
delayed_list = DB.list_tasks_with_note(status=DB.STATUS_DELAYED)
check("延期页仍有 1 条", len(delayed_list) == 1)
check("延期记录名称正确", delayed_list[0]["name"] == "超时完成")
ab_list = DB.list_tasks_with_note(status=DB.STATUS_ABANDONED)
check("放弃页仍有 1 条", len(ab_list) == 1)
check("放弃记录名称正确", ab_list[0]["name"] == "取消")

print("=== C. 归档事务继续计入统计 ===")
st = DB.stats()
print("  统计:", {k: st[k] for k in ("total", "done", "delayed", "abandoned")})
check("统计总数为 3", st["total"] == 3)
check("完成数 1", st["done"] == 1)
check("延期数 1", st["delayed"] == 1)
check("放弃数 1", st["abandoned"] == 1)
check("完成率 33.3%", abs(st["done_rate"] - 100.0 / 3) < 0.01)

print("=== D. 批量取缔多个便签 ===")
fresh_db()
n1, _, _, _, _ = make_case()
n2 = DB.create_note("第二个便签")
DB.create_task(n2, "第二个的任务", "c", datetime.now() + timedelta(days=1))
DB.delete_notes([n1, n2])
after = counts()
print("  批量取缔后 done/delayed/abandoned/pending =", after)
check("归档事务保留", after[:3] == (1, 1, 1))
check("未完成事务删除", after[3] == 0)

print("=== E. 旧库迁移（含 ON DELETE CASCADE 的旧 schema）===")
tmp2 = tempfile.mkdtemp()
old_path = os.path.join(tmp2, "old.db")
conn = sqlite3.connect(old_path)
conn.executescript("""
    CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created TEXT NOT NULL
    );
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        content TEXT NOT NULL,
        ddl TEXT NOT NULL,
        delay_days INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        created TEXT NOT NULL,
        finished TEXT,
        FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
    );
""")
conn.execute("INSERT INTO notes(id,name,created) VALUES(1,'旧便签','2026-01-01 00:00:00')")
conn.execute("INSERT INTO tasks(note_id,name,content,ddl,delay_days,status,created,finished)"
             " VALUES(1,'旧事务','c','2030-01-01 00:00:00',0,'done','2026-01-01 00:00:00','2026-01-02 00:00:00')")
conn.execute("INSERT INTO tasks(note_id,name,content,ddl,delay_days,status,created)"
             " VALUES(1,'旧待办','c','2030-01-01 00:00:00',0,'pending','2026-01-01 00:00:00')")
conn.commit()
conn.close()

DB.APP_DIR = tmp2
DB.DB_PATH = old_path
DB.init_db()
# 迁移后旧表应被重建
c2 = sqlite3.connect(old_path)
ddl = c2.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()[0]
c2.close()
print("  迁移后 tasks DDL 含 note_name:", "note_name" in ddl)
check("已迁移为新 schema（含 note_name 列）", "note_name" in ddl)
check("迁移后不再有 ON DELETE CASCADE", "ON DELETE CASCADE" not in ddl)
check("迁移后数据保留（2 条事务）", len(DB.list_tasks()) == 2)
check("迁移后旧事务 note_name 回填", DB.list_tasks_with_note(status=DB.STATUS_DONE)[0]["note_name"] == "旧便签")

# 迁移后删除便签，归档事务应保留
DB.delete_note(1)
check("迁移后取缔便签：归档事务保留",
      len(DB.list_tasks_with_note(status=DB.STATUS_DONE)) == 1)
check("迁移后取缔便签：未完成事务删除",
      len(DB.list_tasks(status=DB.STATUS_PENDING)) == 0)

print("=== F. purge_orphan_tasks 不误删归档事务 ===")
fresh_db()
nid, _, _, _, _ = make_case()
DB.delete_note(nid)
n = DB.purge_orphan_tasks()
print("  purge 清除了", n, "条")
check("归档事务未被误删",
      len(DB.list_tasks_with_note(status=DB.STATUS_DONE)) == 1
      and len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED)) == 1
      and len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED)) == 1)

print("全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)
