#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
======================================================================
 نسخة احتياطية إلى Supabase — سكربت مستقل لمهمة مجدولة (Scheduled Task)
======================================================================

الغرض: تشغيل النسخ الاحتياطي إلى Supabase في *عملية منفصلة* بدلًا من خيط داخل
خادم الويب. هذا يمنع تنافس النسخ (الطويل) مع طلبات المستخدمين على PythonAnywhere،
وهو سبب البطء و«OSError: write error» وتوقّف الموقع عند دخول أولياء الأمور
أثناء تشغيل النسخة.

──────────────────────────────────────────────────────────────────────
 الإعداد على PythonAnywhere (مرة واحدة):
 1) في ملف الـ WSGI (أو متغيرات البيئة) اضبط:  DISABLE_BACKUP_THREAD = 1
    لإيقاف خيط النسخ داخل خادم الويب.
 2) من تبويب «Tasks» أنشئ Scheduled Task يومية/كل ساعة بالأمر:
        python3.10 /home/USERNAME/teacher_app/run_backup.py
    (استبدل USERNAME ومسار بايثون بما يناسب حسابك.)
──────────────────────────────────────────────────────────────────────

 الاستخدام اليدوي:
    python run_backup.py            # نسخة كاملة الآن
    DATA_DIR=/path python run_backup.py
"""
import os
import sys
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# مكان قاعدة SQLite (نفس مجلد المشروع افتراضيًا)
os.environ.setdefault("DATA_DIR", APP_DIR)


def main():
    import database as db
    import supabase_sync as sb

    if not sb.is_enabled():
        print("[backup] Supabase غير مُفعّل أو غير مضبوط — لا شيء لعمله.")
        return 0

    started = datetime.now()
    print(f"[backup] بدء النسخ الاحتياطي: {started:%Y-%m-%d %H:%M:%S}")
    try:
        ok, msg = sb.backup_all(progress=False)
    except Exception as e:
        ok, msg = False, f"{type(e).__name__}: {e}"

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if ok:
            db.set_setting("auto_backup_last", ts)
            db.set_setting("auto_backup_last_status", "success")
            db.set_setting("auto_backup_last_error", "")
        else:
            db.set_setting("auto_backup_last_status", "failed")
            db.set_setting("auto_backup_last_error", str(msg)[:500])
    except Exception as e:
        print("[backup] تعذّر تحديث حالة النسخ:", e)

    dur = (datetime.now() - started).total_seconds()
    print(f"[backup] {'نجحت' if ok else 'فشلت'} النسخة في {dur:.0f}s — {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
