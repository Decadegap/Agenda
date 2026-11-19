# -*- coding: utf-8 -*-
"""取缔便签自检：只删便签与未完成事务，已归档事务保留在分类页并计入统计"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as DB

DB.init_db()

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}")


def purge():
    with DB._connect() as conn:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM notes")


purge()
nid = DB.create_note("测试便签")
t1 = DB.create_task(nid, "待办", "内容", datetime.now() + timedelta(days=1))
t2 = DB.create_task(nid, "按时完成", "内容", datetime.now() + timedelta(days=1))
t3 = DB.create_task(nid, "超时完成", "内容", datetime.now() - timedelta(days=1))
t4 = DB.create_task(nid, "取消", "内容", datetime.now() + timedelta(days=1))

DB.complete_task(t2)
DB.complete_task(t3)
DB.cancel_task(t4)

print("状态分布：")
for st in (DB.STATUS_DONE, DB.STATUS_DELAYED, DB.STATUS_ABANDONED, DB.STATUS_PENDING):
    rows = DB.list_tasks(note_id=nid, status=st)
    print(f"  {st}: {len(rows)}")

before_done = len(DB.list_tasks_with_note(status=DB.STATUS_DONE))
before_delayed = len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED))
before_abandoned = len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED))
print(f"删除前：done={before_done} delayed={before_delayed} abandoned={before_abandoned}")

DB.delete_note(nid)

after_done = len(DB.list_tasks_with_note(status=DB.STATUS_DONE))
after_delayed = len(DB.list_tasks_with_note(status=DB.STATUS_DELAYED))
after_abandoned = len(DB.list_tasks_with_note(status=DB.STATUS_ABANDONED))
print(f"删除后：done={after_done} delayed={after_delayed} abandoned={after_abandoned}")

check("已完成的便签已消失", DB.get_note(nid) is None)
check("pending 事务已删除", len(DB.list_tasks(status=DB.STATUS_PENDING)) == 0)
check("已完成分类页仍保留该便签事务", after_done == before_done)
check("延期分类页仍保留该便签事务", after_delayed == before_delayed)
check("放弃分类页仍保留该便签事务", after_abandoned == before_abandoned)

s = DB.stats()
check("归档事务继续计入统计", s["total"] == 3)
check("统计中完成数为 1", s["done"] == 1)
check("统计中延期数为 1", s["delayed"] == 1)
check("统计中放弃数为 1", s["abandoned"] == 1)

kept = DB.list_tasks_with_note(status=DB.STATUS_DONE)
check("保留的记录仍显示原便签名", len(kept) == 1 and kept[0]["note_name"] == "测试便签")

purge()
print(f"\n结果: {ok} 通过, {fail} 失败")
sys.exit(1 if fail else 0)
