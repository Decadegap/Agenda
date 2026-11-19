# -*- coding: utf-8 -*-
"""业务规则自检：python test_rules.py"""
import os, sys, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmp = tempfile.mkdtemp(prefix="ag_test_")
os.environ["APPDATA"] = tmp
import db as DB
DB.APP_DIR = tmp
DB.DB_PATH = os.path.join(tmp, "test.db")
DB.init_db()

ok = 0
fail = []


def check(name, cond):
    global ok
    if cond:
        ok += 1
        print("  PASS", name)
    else:
        fail.append(name)
        print("  FAIL", name)


from datetime import datetime, timedelta
now = datetime.now()

print("规则 1：便签默认名")
n1 = DB.create_note("")
check("默认名 '任务 1'", DB.get_note(n1)["name"] == "任务 1")

print("规则 2：未超时完成 -> 按时完成(done)")
t = DB.create_task(n1, "a", "c", now + timedelta(hours=5))
DB.complete_task(t)
check("status=done", DB.get_task(t)["status"] == DB.STATUS_DONE)

print("规则 3：超时后完成 -> 延期(delayed)")
t2 = DB.create_task(n1, "b", "c", now - timedelta(hours=1))
check("显示已超时", DB.remaining(DB.get_task(t2))[0] is True)
DB.complete_task(t2)
check("status=delayed", DB.get_task(t2)["status"] == DB.STATUS_DELAYED)

print("规则 4：取消 -> 放弃(abandoned)")
t3 = DB.create_task(n1, "c", "c", now + timedelta(hours=5))
DB.cancel_task(t3)
check("status=abandoned", DB.get_task(t3)["status"] == DB.STATUS_ABANDONED)

print("规则 5：预计延期可多次，基准 = 原 DDL + 累计延时（精确到秒）")
t4 = DB.create_task(n1, "d", "c", now - timedelta(hours=1))
check("初始超时", DB.remaining(DB.get_task(t4))[0] is True)
DB.postpone_task(t4, 86400)
check("延时1天后未超时", DB.remaining(DB.get_task(t4))[0] is False)
DB.postpone_task(t4, 86400)
check("再延时1天仍未超时", DB.remaining(DB.get_task(t4))[0] is False)
DB.postpone_task(t4, 86400)
check("三次延时(共+3天)后仍未超时",
      DB.remaining(DB.get_task(t4))[0] is False)
DB.postpone_task(t4, 2 * 86400)
check("再延时2天(共+5天)后仍未超时（DDL 被推后）",
      DB.remaining(DB.get_task(t4))[0] is False)
check("累计延时秒数=5天", DB.delay_seconds(DB.get_task(t4)) == 5 * 86400)
check("累计延时显示=5天", DB.fmt_delay(DB.delay_seconds(DB.get_task(t4))) == "5天")

print("规则 5b：延时支持小时级，设置总时长可覆盖")
t4b = DB.create_task(n1, "d2", "c", now + timedelta(hours=1))
DB.set_delay(t4b, 2 * 3600)
check("设为延时2小时", DB.delay_seconds(DB.get_task(t4b)) == 7200)
check("延时后基准=原DDL+2h", abs((DB.effective_ddl(DB.get_task(t4b)) -
                                  (now + timedelta(hours=3))).total_seconds()) < 5)
DB.postpone_task(t4b, 3600)
check("再追加1小时=3小时", DB.delay_seconds(DB.get_task(t4b)) == 10800)
check("3小时显示为『3小时』", DB.fmt_delay(10800) == "3小时")
DB.set_delay(t4b, 90 * 60)
check("覆盖为90分钟", DB.delay_seconds(DB.get_task(t4b)) == 5400)
check("90分钟显示", DB.fmt_delay(5400) == "1小时30分")

print("规则 6：未超时完成归 done；超时完成归 delayed")
t5 = DB.create_task(n1, "e", "c", now + timedelta(hours=2))
DB.complete_task(t5)
check("未超时完成=done", DB.get_task(t5)["status"] == DB.STATUS_DONE)
t6 = DB.create_task(n1, "f", "c", now - timedelta(days=3))
DB.postpone_task(t6, 86400)
check("延时1天后仍超时（DDL=now-3d+1d）", DB.remaining(DB.get_task(t6))[0] is True)
DB.complete_task(t6)
check("超时完成=delayed", DB.get_task(t6)["status"] == DB.STATUS_DELAYED)

print("规则 7：统计只算已结束事务")
s = DB.stats()
check("total=5(done2+delayed2+abandoned1)", s["total"] == 5)
check("done=2", s["done"] == 2)
check("delayed=2", s["delayed"] == 2)
check("abandoned=1", s["abandoned"] == 1)

print("规则 8：删除便签为物理删除，且不计统计")
before = DB.stats()["total"]
n2 = DB.create_note("待删")
tt = DB.create_task(n2, "x", "c", now + timedelta(hours=5))
DB.delete_note(n2)
check("便签已消失", DB.get_note(n2) is None)
check("事务已消失", DB.get_task(tt) is None)
check("统计不变", DB.stats()["total"] == before)
check("待完成列表不含已结束事务",
      all(t["status"] == DB.STATUS_PENDING
          for t in DB.list_tasks(note_id=n1, only_pending=True)))

print("规则 9：分类页只显示对应状态")
check("done 页只含 done", all(t["status"] == DB.STATUS_DONE
                            for t in DB.list_tasks(status=DB.STATUS_DONE)))
check("delayed 页只含 delayed", all(t["status"] == DB.STATUS_DELAYED
                                for t in DB.list_tasks(status=DB.STATUS_DELAYED)))
check("abandoned 页只含 abandoned", all(t["status"] == DB.STATUS_ABANDONED
                                  for t in DB.list_tasks(status=DB.STATUS_ABANDONED)))

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n结果: {ok} 通过, {len(fail)} 失败")
if fail:
    for f in fail:
        print("  -", f)
    sys.exit(1)
