"""
جدولة النسخ الاحتياطي التلقائي إلى Supabase.

يعمل عبر خيط خلفية (thread) داخل التطبيق:
- يقرأ الإعدادات من قاعدة البيانات (مفعّل؟ + الفترة بالدقائق).
- ينفّذ النسخ عبر supabase_sync.backup_all (upsert آمن، بلا تكرار).
- يسجّل آخر نسخة ناجحة/فاشلة + الخطأ الفعلي + موعد النسخة القادمة.
- يستأنف تلقائيًا بعد إعادة تشغيل التطبيق (الحالة مخزّنة في قاعدة البيانات).
- إعادة المحاولة الآمنة: عند الفشل يعيد المحاولة في الدورة التالية دون تكرار بيانات.

ملاحظة بيئة الاستضافة: الخطة المجانية (Render Free) «تنام» عند الخمول فيتوقف
الخيط مؤقتًا؛ يستأنف عند أول طلب/استيقاظ. الجدولة تعتمد على الوقت المنقضي
وليس على بقاء العملية حيّة، لذا لا تتكرر النسخ ولا تُفقد المواعيد.
"""
import threading
import time
from datetime import datetime, timedelta

import database as db
import supabase_sync as sb

_thread = None
_started = False
_lock = threading.Lock()
_wake = threading.Event()

# خيط النسخ اليدوي في الخلفية (حتى لا يحجب طلب HTTP أثناء الرفع على دفعات)
_manual_thread = None
_manual_lock = threading.Lock()


def start_backup_async():
    """يبدأ نسخة احتياطية يدوية في خيط خلفي. يرجّع True لو بدأت، False لو هناك واحدة جارية."""
    global _manual_thread
    with _manual_lock:
        if _manual_thread and _manual_thread.is_alive():
            return False
        _manual_thread = threading.Thread(target=run_backup_now, daemon=True)
        _manual_thread.start()
        return True


def _now():
    return datetime.now()


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _interval_minutes():
    try:
        v = int(db.get_setting("auto_backup_interval", "60") or 60)
        return max(1, v)
    except (ValueError, TypeError):
        return 60


def _enabled():
    return db.get_setting("auto_backup_enabled", "0") == "1"


def _last_success_dt():
    raw = db.get_setting("auto_backup_last", "")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _due():
    """هل حان وقت النسخة؟ (بناءً على آخر نسخة ناجحة + الفترة)."""
    last = _last_success_dt()
    if last is None:
        return True
    return _now() >= last + timedelta(minutes=_interval_minutes())


def _update_next():
    nxt = _now() + timedelta(minutes=_interval_minutes())
    db.set_setting("auto_backup_next", _fmt(nxt))


def run_backup_now():
    """ينفّذ نسخة فورية ويحدّث الحالة. يرجّع (ok, message)."""
    try:
        ok, msg = sb.backup_all()
    except Exception as e:  # حماية إضافية
        ok, msg = False, str(e)
    ts = _fmt(_now())
    if ok:
        db.set_setting("auto_backup_last", ts)
        db.set_setting("auto_backup_last_status", "success")
        db.set_setting("auto_backup_last_error", "")
    else:
        db.set_setting("auto_backup_last_status", "failed")
        db.set_setting("auto_backup_last_error", str(msg)[:500])
        print("[backup] فشل النسخ التلقائي:", msg)
    _update_next()
    return ok, msg


def _loop():
    # فحص دوري كل ٣٠ ثانية؛ ينفّذ فقط عند حلول الموعد
    while True:
        try:
            if _enabled() and sb.is_enabled() and _due():
                run_backup_now()
            elif _enabled() and not db.get_setting("auto_backup_next"):
                _update_next()
        except Exception as e:
            print("[backup] خطأ في حلقة الجدولة:", e)
        # ننام مع إمكانية الإيقاظ الفوري عند تغيير الإعدادات
        _wake.wait(timeout=30)
        _wake.clear()


def notify_settings_changed():
    """يوقظ الخيط فورًا بعد تغيير إعدادات النسخ (لتحديث الموعد)."""
    try:
        if _enabled():
            _update_next()
        _wake.set()
    except Exception:
        pass


def start():
    """يبدأ خيط الجدولة مرة واحدة فقط (آمن للاستدعاء المتكرر)."""
    global _thread, _started
    with _lock:
        if _started:
            return
        _started = True
        _thread = threading.Thread(target=_loop, name="backup-scheduler", daemon=True)
        _thread.start()
        print("[backup] بدأت جدولة النسخ الاحتياطي التلقائي.")
