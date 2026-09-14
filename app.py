"""
نظام إدارة المدرس - التطبيق الرئيسي
Teacher Management System - Main Flask Application
"""
import json
import io
import random
import os
import re
import time
import base64
import functools
from datetime import datetime, timedelta
from collections import defaultdict
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import qrcode
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, flash, send_file, session, abort, Response)

import database as db
import whatsapp_helper as wa
import supabase_sync as sb
import excel_helper as xls
import docx_helper
import exam_import  # استيراد الأسئلة من Word (بدون ذكاء اصطناعي)
import backup_scheduler

# مستويات أداء الطالب (لاختيار المدرس)
LEVELS = ["ممتاز", "جيد جدًا", "جيد", "متوسط", "يحتاج إلى تحسين"]

app = Flask(__name__)
# مفتاح التأمين: يُقرأ من متغير بيئة على الاستضافة، وإلا قيمة افتراضية محليًا
app.secret_key = os.environ.get("SECRET_KEY", "teacher-app-secret-key-change-me-please")
# عمر الكوكي طويل (٣٠ يومًا)؛ انتهاء الجلسة الفعلي يُفرض بمنطق الخمول على الخادم
app.permanent_session_lifetime = timedelta(days=30)

# تهيئة آمنة حتى مع عدة عمليات (workers) أو بيئة serverless (Vercel)
def _safe_boot():
    # init_db دائمًا (كل الجُمَل CREATE TABLE IF NOT EXISTS = آمنة وسريعة)
    # ده بيضمن إنشاء أي جداول جديدة (مثل reminders) على قواعد البيانات القديمة (migration)
    try:
        db.init_db()
    except Exception as e:
        print("[boot] init_db:", e)
    # لو الجداول والبيانات موجودة بالفعل، تخطَّ تهيئة الأدمن والبيانات التجريبية
    try:
        if db.schema_ready():
            return
    except Exception:
        pass
    try:
        db.ensure_admin()
    except Exception as e:
        print("[boot] ensure_admin (متوقع مع عدة عمليات):", e)
    try:
        db.seed_demo()
    except Exception as e:
        print("[boot] seed_demo (متوقع مع عدة عمليات):", e)


_safe_boot()

# بدء خيط جدولة النسخ الاحتياطي التلقائي إلى Supabase (آمن للاستدعاء المتكرر)
try:
    backup_scheduler.start()
except Exception as _e:
    print("[boot] backup_scheduler:", _e)

STATUS_AR = {"present": "حاضر", "late": "متأخر", "absent": "غائب"}
HW_AR = {"done": "أدى الواجب", "not_done": "لم يؤدِّ الواجب",
         "incomplete": "غير مكتمل", "none": "-"}
# الحالات المسموح بها للواجب (تُستخدم للتحقّق من المدخلات)
HW_STATUSES = ("done", "not_done", "incomplete", "none")

# ---------------------------------------------------------------------------
# أنواع أسئلة الامتحان (يتحكّم بها المدرس يدويًا — لا توليد آلي)
# ---------------------------------------------------------------------------
# الأنواع الأساسية المطلوبة (دراسات اجتماعية/تاريخ) + الأنواع القديمة للتوافق
QTYPE_LABELS = {
    "mcq": "اختيار من متعدد",
    "truefalse": "صح أو خطأ",
    "complete": "أكمل",
    "explain": "بم تفسّر",
    "results": "ما النتائج المترتبة على",
    "meaning": "ما المقصود بـ",
    "compare": "قارن",
    "prove": "دلل",
    "map": "اكتب مدلول الأرقام على الخريطة",
    "map_complete": "أكمل مدلول الأرقام على الخريطة",
    # أنواع قديمة (تبقى مدعومة للامتحانات السابقة)
    "matching": "توصيل",
    "ordering": "ترتيب",
    "cause_effect": "سبب ونتيجة",
    "analysis": "تحليل واستنتاج",
    "short": "سؤال قصير",
}

# المراحل التعليمية ومستويات الصعوبة والترمات (لبنك الأسئلة)
EDU_STAGES = ["المرحلة الابتدائية", "المرحلة الإعدادية", "المرحلة الثانوية"]
DIFFICULTY_LABELS = {"easy": "سهل", "medium": "متوسط", "hard": "صعب"}
TERM_LABELS = ["الترم الأول", "الترم الثاني"]

# ── قيم بنك الأسئلة القياسية (قوائم ثابتة بدل الإدخال الحر) ──
# المادة ثابتة دائمًا (لا يكتبها المدرس)
QB_SUBJECT = "الدراسات الاجتماعية"
# الصفوف التابعة لكل مرحلة (قائمة منسدلة معتمدة على المرحلة)
QB_GRADES_BY_STAGE = {
    "المرحلة الابتدائية": ["الصف الرابع الابتدائي", "الصف الخامس الابتدائي",
                          "الصف السادس الابتدائي"],
    "المرحلة الإعدادية": ["الصف الأول الإعدادي", "الصف الثاني الإعدادي",
                         "الصف الثالث الإعدادي"],
    "المرحلة الثانوية": ["الصف الأول الثانوي", "الصف الثاني الثانوي",
                        "الصف الثالث الثانوي"],
}
# كل الصفوف القياسية (للتحقق السريع)
QB_ALL_GRADES = [g for gs in QB_GRADES_BY_STAGE.values() for g in gs]
QB_UNITS = ["الوحدة الأولى", "الوحدة الثانية", "الوحدة الثالثة",
            "الوحدة الرابعة", "الوحدة الخامسة"]
QB_LESSONS = ["الدرس الأول", "الدرس الثاني", "الدرس الثالث",
              "الدرس الرابع", "الدرس الخامس", "الدرس السادس"]

# خريطة تطبيع للقيم الحرة القديمة → القيم القياسية (للترحيل والاستيراد)
QB_STAGE_ALIASES = {
    "ابتدائي": "المرحلة الابتدائية", "ابتدائية": "المرحلة الابتدائية",
    "الابتدائية": "المرحلة الابتدائية", "المرحله الابتدائيه": "المرحلة الابتدائية",
    "اعدادي": "المرحلة الإعدادية", "إعدادي": "المرحلة الإعدادية",
    "اعدادية": "المرحلة الإعدادية", "إعدادية": "المرحلة الإعدادية",
    "الاعدادية": "المرحلة الإعدادية", "الإعدادية": "المرحلة الإعدادية",
    "المرحله الاعداديه": "المرحلة الإعدادية",
    "ثانوي": "المرحلة الثانوية", "ثانوية": "المرحلة الثانوية",
    "الثانوية": "المرحلة الثانوية", "المرحله الثانويه": "المرحلة الثانوية",
}


def _qb_norm_key(s):
    """تطبيع نص للمطابقة: يزيل التشكيل ويوحّد الألف/الياء/التاء المربوطة والمسافات."""
    import re as _re
    s = (s or "").strip()
    s = _re.sub(r"[\u064B-\u0652\u0670]", "", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي").replace("ة", "ه")
    s = _re.sub(r"\s+", " ", s)
    return s.strip()


def qb_std_stage(val):
    """يرجّع اسم المرحلة القياسي من أي إدخال حر، أو "" إن تعذّر."""
    v = (val or "").strip()
    if v in EDU_STAGES:
        return v
    nv = _qb_norm_key(v)
    for std in EDU_STAGES:
        if _qb_norm_key(std) == nv:
            return std
    for alias, std in QB_STAGE_ALIASES.items():
        if _qb_norm_key(alias) == nv or _qb_norm_key(alias) in nv:
            return std
    return ""


def qb_std_grade(val, stage=""):
    """يرجّع اسم الصف القياسي من أي إدخال حر (يراعي المرحلة إن مرّرت)."""
    v = (val or "").strip()
    if v in QB_ALL_GRADES:
        # تحقّق من التوافق مع المرحلة إن وُجدت
        if stage and stage in QB_GRADES_BY_STAGE and v not in QB_GRADES_BY_STAGE[stage]:
            return ""
        return v
    nv = _qb_norm_key(v)
    candidates = QB_GRADES_BY_STAGE.get(stage, QB_ALL_GRADES) if stage else QB_ALL_GRADES
    for std in candidates:
        if _qb_norm_key(std) == nv:
            return std
    # مطابقة مرنة: يحتوي على كلمة الصف + المرحلة
    levels = {"رابع": "الرابع", "خامس": "الخامس", "سادس": "السادس",
              "اول": "الأول", "أول": "الأول", "ثاني": "الثاني", "ثالث": "الثالث"}
    stage_word = {"ابتدائ": "الابتدائي", "اعداد": "الإعدادي", "إعداد": "الإعدادي",
                  "ثانو": "الثانوي"}
    lvl = None
    for k in levels:
        if _qb_norm_key(k) in nv:
            lvl = levels[k]
            break
    sw = None
    for k in stage_word:
        if _qb_norm_key(k) in nv:
            sw = stage_word[k]
            break
    if lvl and sw:
        target = f"الصف {lvl} {sw}"
        if target in QB_ALL_GRADES:
            return target
    return ""


def _qb_std_from_list(val, options):
    """يرجّع القيمة القياسية من قائمة ثابتة (مطابقة مرنة)، أو "" إن تعذّر."""
    v = (val or "").strip()
    if v in options:
        return v
    nv = _qb_norm_key(v)
    for o in options:
        if _qb_norm_key(o) == nv:
            return o
    return ""


# كلمات الترتيب العربية → فهرس (للتطبيع المرن للوحدات والدروس)
_QB_ORDINALS = {
    "الاولي": 1, "اولي": 1, "الاول": 1, "اول": 1, "الاولى": 1,
    "الثانيه": 2, "ثانيه": 2, "الثاني": 2, "ثاني": 2,
    "الثالثه": 3, "ثالثه": 3, "الثالث": 3, "ثالث": 3,
    "الرابعه": 4, "رابعه": 4, "الرابع": 4, "رابع": 4,
    "الخامسه": 5, "خامسه": 5, "الخامس": 5, "خامس": 5,
    "السادسه": 6, "سادسه": 6, "السادس": 6, "سادس": 6,
}


def _qb_ordinal_match(val, options):
    """يطابق قيمة حرة بقائمة معتمدة عبر رقم الترتيب (اولى→الأولى...) أو الأرقام."""
    v = _qb_norm_key(val)
    if not v:
        return ""
    # رقم صريح (1..6)
    import re as _re
    m = _re.search(r"[0-9\u0660-\u0669]+", val or "")
    idx = None
    if m:
        try:
            idx = int(m.group(0).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
        except ValueError:
            idx = None
    if idx is None:
        for word, n in _QB_ORDINALS.items():
            if word in v:
                idx = n
                break
    if idx and 1 <= idx <= len(options):
        return options[idx - 1]
    return ""


def qb_std_unit(val):
    return _qb_std_from_list(val, QB_UNITS) or _qb_ordinal_match(val, QB_UNITS)


def qb_std_lesson(val):
    return _qb_std_from_list(val, QB_LESSONS) or _qb_ordinal_match(val, QB_LESSONS)


def _qb_standardize_existing():
    """ترحيل لمرة واحدة: يطبّع القيم الحرة القديمة في بنك الأسئلة إلى القيم القياسية.

    لا يحذف أي سؤال؛ فقط يحدّث الحقول (المرحلة/الصف/المادة/الوحدة/الدرس) إلى الصيغة
    الموحّدة حيثما أمكن. آمن للتشغيل المتكرر (يُعلَّم بمفتاح في settings).
    """
    try:
        conn = db.get_db()
    except Exception:
        return
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(question_bank)").fetchall()} \
            if db.backend() != "postgres" else None
    except Exception:
        cols = None
    try:
        done = conn.execute(
            "SELECT value FROM settings WHERE key='qb_standardized'").fetchone()
        if done and done["value"] == "1":
            conn.close()
            return
        rows = conn.execute(
            "SELECT id, stage, grade, subject, unit, lesson, qtype, term FROM question_bank"
        ).fetchall()
        for r in rows:
            stage = qb_std_stage(r["stage"]) or (r["stage"] or "")
            grade = qb_std_grade(r["grade"], stage) or (r["grade"] or "")
            unit = qb_std_unit(r["unit"]) or (r["unit"] or "")
            lesson = qb_std_lesson(r["lesson"]) or (r["lesson"] or "")
            subject = QB_SUBJECT
            conn.execute(
                "UPDATE question_bank SET stage=?, grade=?, subject=?, unit=?, lesson=? "
                "WHERE id=?", (stage, grade, subject, unit, lesson, r["id"]))
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('qb_standardized','1') "
            "ON CONFLICT(key) DO UPDATE SET value='1'")
        conn.commit()
        if rows:
            print(f"[migration] تم تقييس {len(rows)} سؤالًا في بنك الأسئلة")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print("[migration] qb_standardize:", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


try:
    _qb_standardize_existing()
except Exception as _e:
    print("[boot] qb_standardize:", _e)

# أنواع الأسئلة الموضوعية (تصحيح تلقائي) والمقالية (تصحيح يدوي من المدرس)
AUTO_QTYPES = {"mcq", "truefalse", "complete", "matching", "ordering", "map", "map_complete"}
MANUAL_QTYPES = {"explain", "results", "meaning", "compare", "prove",
                 "cause_effect", "analysis", "short"}


def _normalize_answer(s):
    """تطبيع نص الإجابة لمقارنة أسئلة «أكمل» تلقائيًا (يتجاهل التشكيل والمسافات)."""
    if not s:
        return ""
    s = str(s).strip().lower()
    # إزالة التشكيل العربي
    s = re.sub(r"[\u064B-\u0652\u0670]", "", s)
    # توحيد الألف والهمزات والتاء المربوطة والياء
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    # إزالة علامات الترقيم والمسافات الزائدة
    s = re.sub(r"[^\w\u0621-\u064A\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# حالة المستخدم على الخادم (مسودات كبيرة لا تتّسع في كوكي الجلسة 4KB)
# السبب الجذري لمشكلة «لا توجد مسودة»: تخزين نص الدرس + الأسئلة في الكوكي
# يتجاوز حد 4KB فيسقط الكوكي صامتًا. الحل: تخزينها في قاعدة البيانات.
# ---------------------------------------------------------------------------
def _state_owner():
    return "admin:" + str(session.get("admin") or "?")


def set_draft(key, obj):
    db.set_state(_state_owner(), key,
                 json.dumps(obj, ensure_ascii=False) if obj is not None else None)


def get_draft(key, default=None):
    raw = db.get_state(_state_owner(), key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def clear_draft(key):
    db.clear_state(_state_owner(), key)


# ---------------------------------------------------------------------------
# انتهاء الجلسة (تسجيل خروج تلقائي عند الخمول) — يُفرض على الخادم
# ---------------------------------------------------------------------------
_SESSION_MSG = "انتهت الجلسة، يرجى تسجيل الدخول مرة أخرى."
# مسارات لا تخضع لفحص المهلة (تسجيل الدخول/الخروج/الملفات العامة/امتحان الطالب)
_TIMEOUT_EXEMPT = {"login", "logout", "parent_login", "parent_logout",
                   "static", "forgot", "take_exam", "student_qr_public",
                   "auto_backup_status"}


def _session_timeout_minutes():
    try:
        return int(db.get_setting("session_timeout", "120") or 0)
    except (ValueError, TypeError):
        return 120


@app.before_request
def _enforce_session_timeout():
    ep = request.endpoint or ""
    if ep in _TIMEOUT_EXEMPT:
        return
    is_admin = bool(session.get("admin"))
    is_parent = bool(session.get("parent_id"))
    if not (is_admin or is_parent):
        return  # غير مسجّل دخول أصلًا؛ الحماية عبر login_required
    timeout = _session_timeout_minutes()
    if timeout <= 0:
        return  # بلا مهلة
    now_ts = int(time.time())
    last = session.get("last_activity")
    if last is not None and (now_ts - int(last)) > timeout * 60:
        # انتهت الجلسة → سجّل الخروج وأعد للتسجيل مع رسالة واضحة
        if is_parent and not is_admin:
            session.clear()
            flash(_SESSION_MSG, "error")
            return redirect(url_for("parent_login"))
        session.clear()
        flash(_SESSION_MSG, "error")
        return redirect(url_for("login"))
    # حدّث وقت آخر نشاط
    session["last_activity"] = now_ts
    session.permanent = True


# ---------------------------------------------------------------------------
# المصادقة (تسجيل دخول الأدمن)
# ---------------------------------------------------------------------------
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        conn = db.get_db()
        row = conn.execute("SELECT * FROM admin WHERE username=?", (u,)).fetchone()
        conn.close()
        if row and check_password_hash(row["password_hash"], p):
            session["admin"] = u
            session.permanent = True
            session["last_activity"] = int(time.time())
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    flash("تم تسجيل الخروج", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# بوابة ولي الأمر: المصادقة
# ---------------------------------------------------------------------------
def parent_login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("parent_id"):
            return redirect(url_for("parent_login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def _parent_student_ids(conn, parent_id):
    """أرقام الطلاب المرتبطين بولي الأمر فقط (عزل أمني)."""
    rows = conn.execute("SELECT student_id FROM parent_students WHERE parent_id=?",
                        (parent_id,)).fetchall()
    return [r["student_id"] for r in rows]


@app.route("/parent/login", methods=["GET", "POST"])
def parent_login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        # نُزيل المسافات/الأسطر الزائدة من كلمة المرور (شائعة عند النسخ واللصق)،
        # فبدونها يفشل check_password_hash رغم صحة كلمة المرور المكتوبة.
        p = request.form.get("password", "").strip()
        conn = db.get_db()
        # مطابقة اسم المستخدم بلا حساسية لحالة الأحرف/المسافات (اسم المستخدم غالبًا رقم
        # واتساب؛ النسخ قد يضيف مسافة). نستخدم TRIM ومقارنة غير حسّاسة لحالة الأحرف.
        row = conn.execute(
            "SELECT * FROM parents WHERE LOWER(TRIM(username))=LOWER(?)", (u,)).fetchone()
        conn.close()
        if row and check_password_hash(row["password_hash"], p):
            if not row["active"]:
                flash("هذا الحساب موقوف. برجاء التواصل مع المدرس.", "error")
                return render_template("parent_login.html")
            session["parent_id"] = row["id"]
            session["parent_name"] = row["name"] or row["username"]
            session.permanent = True
            session["last_activity"] = int(time.time())
            return redirect(request.args.get("next") or url_for("parent_dashboard"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة", "error")
    return render_template("parent_login.html")


@app.route("/parent/logout")
def parent_logout():
    session.pop("parent_id", None)
    session.pop("parent_name", None)
    flash("تم تسجيل الخروج", "success")
    return redirect(url_for("parent_login"))


@app.route("/parent")
@parent_login_required
def parent_dashboard():
    conn = db.get_db()
    pid = session["parent_id"]
    sids = _parent_student_ids(conn, pid)
    if not sids:
        conn.close()
        return render_template("parent_dashboard.html", students=[], sel=None,
                               parent_name=session.get("parent_name"))
    # الطالب المختار (ضمن أبناء هذا الولي فقط)
    sel_id = request.args.get("student", type=int)
    if sel_id not in sids:
        sel_id = sids[0]
    placeholders = ",".join("?" * len(sids))
    students = conn.execute(
        f"SELECT s.*, g.name group_name FROM students s "
        f"LEFT JOIN groups g ON s.group_id=g.id WHERE s.id IN ({placeholders}) ORDER BY s.name",
        sids).fetchall()
    st = conn.execute(
        "SELECT s.*, g.name group_name FROM students s "
        "LEFT JOIN groups g ON s.group_id=g.id WHERE s.id=?", (sel_id,)).fetchone()
    # الترمات المتاحة للعام الحالي + اختيار الترم
    cur_year = db.get_current_year_id()
    terms = conn.execute(
        "SELECT * FROM terms WHERE year_id=? ORDER BY start_date, id", (cur_year,)).fetchall()
    sel_term_id = request.args.get("term", type=int)
    sel_term = None
    if sel_term_id:
        sel_term = conn.execute("SELECT * FROM terms WHERE id=?", (sel_term_id,)).fetchone()
    # شرط الفترة الزمنية حسب الترم المختار (لا نخلط بيانات الترمات)
    date_cond = ""
    date_args = []
    if sel_term and sel_term["start_date"] and sel_term["end_date"]:
        date_cond = " AND se.date>=? AND se.date<=?"
        date_args = [sel_term["start_date"], sel_term["end_date"]]
    # الحضور (ضمن الترم المختار إن وُجد)
    att = conn.execute(
        "SELECT a.*, se.date, se.title FROM attendance a "
        "JOIN sessions se ON a.session_id=se.id WHERE a.student_id=?" + date_cond +
        " ORDER BY se.date DESC", (sel_id, *date_args)).fetchall()
    stats = {"present": 0, "late": 0, "absent": 0}
    for a in att:
        stats[a["status"]] = stats.get(a["status"], 0) + 1
    # النتائج (تُفلتر بتاريخ الأداء ضمن الترم إن وُجد)
    res_cond = ""
    res_args = []
    if sel_term and sel_term["start_date"] and sel_term["end_date"]:
        res_cond = " AND substr(r.taken_at,1,10)>=? AND substr(r.taken_at,1,10)<=?"
        res_args = [sel_term["start_date"], sel_term["end_date"]]
    res = conn.execute(
        "SELECT r.*, e.title, e.total_marks FROM results r "
        "JOIN exams e ON r.exam_id=e.id WHERE r.student_id=?" + res_cond +
        " ORDER BY r.taken_at DESC", (sel_id, *res_args)).fetchall()
    results = []
    for r in res:
        pct = round(r["score"] / r["total_marks"] * 100) if r["total_marks"] else 0
        results.append({**dict(r), "pct": pct})
    avg_pct, att_pct, level = compute_level(conn, sel_id)
    conn.close()
    return render_template("parent_dashboard.html", students=students, sel=st,
                           att=att, stats=stats, results=results,
                           avg_pct=avg_pct, att_pct=att_pct, level=level,
                           status_ar=STATUS_AR, hw_ar=HW_AR, terms=terms,
                           sel_term=sel_term, sel_term_id=sel_term_id,
                           parent_name=session.get("parent_name"))


def _mask_email(email):
    """يُخفي جزءًا من الإيميل عند عرضه (mina@gmail.com → mi***@gmail.com)."""
    email = (email or "").strip()
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        shown = local[:1]
    else:
        shown = local[:2]
    return f"{shown}***@{domain}"


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    """استرجاع كلمة المرور: عبر إرسال كود تحقّق إلى إيميل المعلم المسجّل (نفس إيميل
    التقارير المالية)، مع الإبقاء على كود الاسترجاع اليدوي كوسيلة احتياطية."""
    step = "verify"
    report_email = (db.get_setting("report_email") or "").strip()
    if request.method == "POST":
        conn = db.get_db()
        row = conn.execute("SELECT * FROM admin LIMIT 1").fetchone()
        action = request.form.get("action")

        # (1) طلب إرسال كود التحقّق على الإيميل المسجّل
        if action == "send_email":
            conn.close()
            if not report_email:
                flash("لا يوجد إيميل مسجّل. اضبط «إيميل استقبال التقارير» من الإعدادات أولًا، "
                      "أو استخدم كود الاسترجاع.", "error")
                return render_template("forgot.html", step="verify",
                                       report_email=report_email, report_email_masked=_mask_email(report_email))
            code = "%06d" % random.randint(0, 999999)  # كود من 6 أرقام
            session["reset_email_code"] = code
            session["reset_email_expires"] = int(time.time()) + 600  # صالح 10 دقائق
            session.pop("reset_ok", None)
            body = (f"مرحبًا،\n\n"
                    f"طلبت إعادة تعيين كلمة مرور نظام إدارة المدرس.\n"
                    f"كود التحقّق الخاص بك هو:\n\n{code}\n\n"
                    f"هذا الكود صالح لمدة 10 دقائق. إذا لم تطلب ذلك فتجاهل هذه الرسالة.")
            ok, resp = _send_email("كود إعادة تعيين كلمة المرور — نظام إدارة المدرس", body)
            if ok:
                flash(f"تم إرسال كود التحقّق إلى إيميلك ({_mask_email(report_email)}). "
                      "تحقّق من بريدك (وصندوق الوارد غير المرغوب).", "success")
                return render_template("forgot.html", step="email_code",
                                       report_email=report_email, report_email_masked=_mask_email(report_email))
            flash(f"تعذّر إرسال الإيميل: {resp}", "error")
            return render_template("forgot.html", step="verify",
                                   report_email=report_email, report_email_masked=_mask_email(report_email))

        # (2) التحقّق من كود الإيميل
        if action == "verify_email":
            conn.close()
            entered = re.sub(r"\D", "", request.form.get("email_code", ""))
            real = session.get("reset_email_code")
            exp = session.get("reset_email_expires", 0)
            if not real or int(time.time()) > int(exp):
                flash("انتهت صلاحية الكود. اطلب كودًا جديدًا.", "error")
                return render_template("forgot.html", step="verify",
                                       report_email=report_email, report_email_masked=_mask_email(report_email))
            if entered and entered == real:
                session["reset_ok"] = True
                session.pop("reset_email_code", None)
                session.pop("reset_email_expires", None)
                return render_template("forgot.html", step="reset",
                                       report_email=report_email, report_email_masked=_mask_email(report_email))
            flash("كود التحقّق غير صحيح", "error")
            return render_template("forgot.html", step="email_code",
                                   report_email=report_email, report_email_masked=_mask_email(report_email))

        # (3) كود الاسترجاع اليدوي (احتياطي)
        if action == "verify":
            code = request.form.get("recovery_code", "").strip()
            if row and code and code == row["recovery_code"]:
                session["reset_ok"] = True
                conn.close()
                return render_template("forgot.html", step="reset",
                                       report_email=report_email, report_email_masked=_mask_email(report_email))
            conn.close()
            flash("كود الاسترجاع غير صحيح", "error")
            return render_template("forgot.html", step="verify",
                                   report_email=report_email, report_email_masked=_mask_email(report_email))

        # (4) حفظ كلمة المرور الجديدة (بعد التحقّق بأي وسيلة)
        if action == "reset" and session.get("reset_ok"):
            newp = request.form.get("new_password", "")
            if len(newp) < 4:
                conn.close()
                flash("كلمة المرور قصيرة جدًا (4 أحرف على الأقل)", "error")
                return render_template("forgot.html", step="reset",
                                       report_email=report_email, report_email_masked=_mask_email(report_email))
            new_recovery = db.gen_pass(8)
            conn.execute("UPDATE admin SET password_hash=?, recovery_code=? WHERE id=?",
                         (generate_password_hash(newp), new_recovery, row["id"]))
            conn.commit()
            conn.close()
            session.pop("reset_ok", None)
            flash(f"تم تغيير كلمة المرور بنجاح. كود الاسترجاع الجديد: {new_recovery} (احفظه!)", "success")
            return redirect(url_for("login"))
        conn.close()
    return render_template("forgot.html", step=step, report_email=report_email, report_email_masked=_mask_email(report_email))


# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------
def teacher_name():
    return db.get_setting("teacher_name", "الأستاذ")


def _wa_code(val):
    """يغلّف قيمة (كود/كلمة مرور/اسم مستخدم) بعلامة backtick لعرضها في واتساب
    بخط monospace بخلفية مميّزة. الفائدة:
      1) واتساب لا يحوّل الأرقام إلى رابط اتصال أزرق (فيمكن نسخها/تحديدها بسهولة).
      2) القيمة تظهر واضحة ومنفصلة عن باقي النص.
    نزيل أي backtick داخل القيمة نفسها حتى لا نكسر التنسيق."""
    v = str(val if val is not None else "").replace("`", "")
    return f"`{v}`"


def site_url():
    """
    الرابط العام للموقع:
    1) متغير البيئة SITE_URL (الأفضل عند النشر خلف بروكسي مثل Vercel)
    2) إعداد site_url المحفوظ (لو المدرس ضبطه ومش localhost)
    3) مضيف الطلب الحالي (يشتغل تلقائيًا على أي استضافة)
    """
    env = os.environ.get("SITE_URL", "").strip()
    if env:
        return env.rstrip("/")
    saved = db.get_setting("site_url", "").strip()
    if saved and "127.0.0.1" not in saved and "localhost" not in saved:
        return saved.rstrip("/")
    try:
        return request.host_url.rstrip("/")
    except RuntimeError:
        return saved.rstrip("/") if saved else ""


def public_exam_url(eid):
    """رابط عام كامل للامتحان يعمل من أي جهاز"""
    base = site_url()
    if base:
        return f"{base}/take/{eid}"
    # احتياطي: رابط مطلق من Flask
    return url_for("take_exam", eid=eid, _external=True)


# ---------------------------------------------------------------------------
# سياق العام الدراسي (العام الحالي + عام التصفّح المختار)
# ---------------------------------------------------------------------------
def all_years(conn=None):
    own = conn is None
    if own:
        conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM academic_years ORDER BY is_current DESC, name DESC").fetchall()
    if own:
        conn.close()
    return rows


def current_year_id():
    return db.get_current_year_id()


def active_year_id():
    """العام الذي يتصفّحه المستخدم حاليًا (من الجلسة)، وإلا العام الحالي."""
    yid = session.get("browse_year")
    if yid:
        # تحقّق من وجوده
        conn = db.get_db()
        ok = conn.execute("SELECT 1 FROM academic_years WHERE id=?", (yid,)).fetchone()
        conn.close()
        if ok:
            return yid
    return current_year_id()


def active_year_row():
    yid = active_year_id()
    if not yid:
        return None
    conn = db.get_db()
    row = conn.execute("SELECT * FROM academic_years WHERE id=?", (yid,)).fetchone()
    conn.close()
    return row


def is_browsing_old_year():
    """هل المستخدم يتصفّح عامًا سابقًا (غير الحالي)؟ = وضع القراءة فقط."""
    ay = active_year_id()
    cy = current_year_id()
    return bool(ay and cy and ay != cy)


@app.route("/notifications")
@login_required
def notifications():
    """مركز الإشعارات: امتحانات تحتاج تصحيح + متأخرات مالية + رسائل فشل إرسالها."""
    n = compute_notifications()
    # أسماء الطلاب لكل امتحان يحتاج تصحيح (روابط سريعة للتصحيح)
    conn = db.get_db()
    grading_detail = []
    try:
        for g in n["grading"]:
            studs = conn.execute(
                "SELECT r.student_id, s.name FROM results r JOIN students s ON r.student_id=s.id "
                "WHERE r.exam_id=? AND r.status='pending' ORDER BY s.name", (g["eid"],)).fetchall()
            grading_detail.append({**g, "students": [dict(x) for x in studs]})
    except Exception:
        conn.rollback()
    conn.close()
    return render_template("notifications.html", n=n, grading_detail=grading_detail)


def compute_notifications(yid=None):
    """يحسب تنبيهات المعلم للعام النشط:
    - امتحانات إلكترونية بها محاولات تنتظر تصحيح المدرس (results.status='pending').
    - طلاب عليهم مبالغ متبقّية (تذكيرات دفع pending).
    - رسائل واتساب فشل إرسالها (wa_logs.success=0).
    يرجّع dict فيه القوائم والأعداد. آمن لو الجداول ناقصة (قواعد قديمة).
    """
    if yid is None:
        yid = active_year_id()
    conn = db.get_db()
    _sync_reminders(conn, yid)  # صحّح المتأخرات القديمة الخاطئة قبل حساب التنبيهات
    grading, unpaid, failed, absences = [], [], [], []
    try:
        grading = conn.execute(
            "SELECT e.id eid, e.title, COUNT(*) n FROM results r "
            "JOIN exams e ON r.exam_id=e.id "
            "WHERE r.status='pending' AND e.year_id=? "
            "GROUP BY e.id, e.title ORDER BY e.id DESC", (yid,)).fetchall()
    except Exception:
        conn.rollback()
    try:
        # المتأخرات المالية للعام النشط فقط: نربط التذكير بحصته لتصفية عام الحصة،
        # حتى لا تظهر متأخرات عام دراسي سابق ضمن تنبيهات العام الحالي.
        unpaid = conn.execute(
            "SELECT rem.student_id, s.name, COALESCE(SUM(rem.remaining),0) total, "
            "COUNT(*) n FROM reminders rem JOIN students s ON rem.student_id=s.id "
            "JOIN sessions se ON rem.session_id=se.id "
            "WHERE rem.status='pending' AND rem.remaining>0 AND se.year_id=? "
            "GROUP BY rem.student_id, s.name ORDER BY total DESC", (yid,)).fetchall()
    except Exception:
        conn.rollback()
    try:
        failed = conn.execute(
            "SELECT id, phone, msg_type, response, created_at FROM wa_logs "
            "WHERE success=0 ORDER BY id DESC LIMIT 50", ()).fetchall()
    except Exception:
        conn.rollback()
    try:
        absences = conn.execute(
            "SELECT a.student_id, s.name, a.absence_count, a.threshold, a.created_at "
            "FROM absence_alerts a JOIN students s ON a.student_id=s.id "
            "WHERE a.year_id=? ORDER BY a.id DESC LIMIT 50", (yid,)).fetchall()
    except Exception:
        conn.rollback()
    conn.close()
    grading = [dict(r) for r in grading]
    unpaid = [dict(r) for r in unpaid]
    failed = [dict(r) for r in failed]
    absences = [dict(r) for r in absences]
    n_grading = sum(r["n"] for r in grading)
    n_unpaid = len(unpaid)
    n_failed = len(failed)
    n_absence = len(absences)
    return {"grading": grading, "unpaid": unpaid, "failed": failed, "absences": absences,
            "n_grading": n_grading, "n_unpaid": n_unpaid, "n_failed": n_failed,
            "n_absence": n_absence,
            "total": n_grading + n_unpaid + n_failed + n_absence}


@app.context_processor
def inject_notifications():
    """عدّاد الإشعارات متاح لكل الصفحات (للجرس في الشريط العلوي)."""
    try:
        if not session.get("admin"):
            return {"notif_count": 0}
        n = compute_notifications()
        return {"notif_count": n["total"],
                "notif_counts": {"grading": n["n_grading"],
                                 "unpaid": n["n_unpaid"], "failed": n["n_failed"]}}
    except Exception:
        return {"notif_count": 0}


@app.context_processor
def inject_globals():
    ay = active_year_row()
    return {"teacher_name": teacher_name(),
            "subject": db.get_setting("subject", "المادة"),
            "wa_api_on": wa.api_mode(),
            "supabase_on": db.get_setting("supabase_enabled", "0") == "1",
            "public_exam_url": public_exam_url,
            "active_year": ay,
            "active_year_id": ay["id"] if ay else None,
            "current_year_id": current_year_id(),
            "browsing_old_year": is_browsing_old_year(),
            "all_years": all_years(),
            "teacher_logo": db.get_setting("teacher_logo", ""),
            "parent_logo": db.get_setting("parent_logo", ""),
            # ملاحظة: الخلفية القديمة المفردة (teacher_bg/parent_bg) أُزيلت نهائيًا
            # ولم تعد تُحقن ولا تُستخدم في أي قالب — الخلفية الآن تأتي حصريًا من نظام
            # تخطيط الدخول (teacher_login_layout/parent_login_layout).
            "teacher_login_layout": db.get_setting("teacher_login_layout", "{}"),
            "parent_login_layout": db.get_setting("parent_login_layout", "{}"),
            "ui_theme": db.get_setting("ui_theme", "light"),
            "ui_animations": db.get_setting("ui_animations", "simple")}


@app.context_processor
def inject_qb_constants():
    """قيم بنك الأسئلة القياسية متاحة لكل القوالب (قوائم منسدلة موحّدة)."""
    return {"qb_stages": EDU_STAGES, "qb_grades_by_stage": QB_GRADES_BY_STAGE,
            "qb_units": QB_UNITS, "qb_lessons": QB_LESSONS,
            "qb_terms": TERM_LABELS, "qb_subject": QB_SUBJECT,
            "qb_difficulty_labels": DIFFICULTY_LABELS}


def _read_image_field(field, max_bytes=3_000_000):
    """يقرأ صورة مرفوعة ويحوّلها إلى data URI (base64) لتخزينها في القاعدة.

    يرجّع "" لو لا يوجد ملف. يرفع ValueError لو النوع غير صورة أو الحجم كبير.
    """
    f = request.files.get(field)
    if not f or not f.filename:
        return ""
    data = f.read()
    if len(data) > max_bytes:
        raise ValueError("حجم الصورة كبير جدًا (الحد ~3 ميجابايت).")
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp"}.get(ext)
    if not mime:
        # جرّب من نوع المحتوى
        mime = (f.mimetype or "").lower()
        if not mime.startswith("image/"):
            raise ValueError("الملف ليس صورة صالحة (PNG/JPG/GIF/WEBP).")
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def make_qr_datauri(data):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1e3a8a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def compute_level(conn, student_id):
    """حساب مستوى الطالب: (متوسط الدرجات %, نسبة الحضور %, التقييم)"""
    res = conn.execute(
        "SELECT r.score, e.total_marks FROM results r JOIN exams e ON r.exam_id=e.id "
        "WHERE r.student_id=?", (student_id,)).fetchall()
    att = conn.execute("SELECT status FROM attendance WHERE student_id=?",
                       (student_id,)).fetchall()
    avg_pct = None
    if res:
        total = sum(r["total_marks"] for r in res if r["total_marks"])
        got = sum(r["score"] for r in res if r["total_marks"])
        if total > 0:
            avg_pct = round(got / total * 100)
    present = sum(1 for a in att if a["status"] in ("present", "late"))
    att_pct = round(present / len(att) * 100) if att else None
    v = avg_pct or 0
    level = "ممتاز" if v >= 85 else "جيد جدًا" if v >= 70 else "جيد" if v >= 50 else "يحتاج إلى مجهود"
    return avg_pct, att_pct, level


@app.after_request
def _no_cache_html(resp):
    """يمنع تخزين صفحات HTML في كاش المتصفح، فتصل تحديثات الواجهة (مثل تصميم النوافذ)
    فورًا بعد النشر دون الحاجة إلى تحديث قسري. لا يؤثر على الأصول الثابتة/الملفات."""
    try:
        ct = resp.headers.get("Content-Type", "")
        if ct.startswith("text/html"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


# ---------------------------------------------------------------------------
# الرئيسية / لوحة التحكم
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    conn = db.get_db()
    yid = active_year_id()
    n_students = conn.execute(
        "SELECT COUNT(*) n FROM enrollments WHERE year_id=? "
        "AND (status IS NULL OR status<>'inactive')", (yid,)).fetchone()["n"]
    n_groups = conn.execute("SELECT COUNT(*) n FROM groups WHERE year_id=?", (yid,)).fetchone()["n"]
    n_sessions = conn.execute("SELECT COUNT(*) n FROM sessions WHERE year_id=?", (yid,)).fetchone()["n"]
    n_exams = conn.execute("SELECT COUNT(*) n FROM exams WHERE year_id=?", (yid,)).fetchone()["n"]
    month = datetime.now().strftime("%Y-%m")
    income = conn.execute(
        "SELECT COALESCE(SUM(a.amount),0) s FROM attendance a "
        "JOIN sessions se ON a.session_id=se.id "
        "WHERE a.paid=1 AND se.year_id=? AND substr(se.date,1,7)=?", (yid, month)).fetchone()["s"]
    recent_sessions = conn.execute(
        "SELECT se.*, g.name group_name FROM sessions se "
        "LEFT JOIN groups g ON se.group_id=g.id WHERE se.year_id=? "
        "ORDER BY se.date DESC, se.id DESC LIMIT 5", (yid,)).fetchall()
    groups = conn.execute("SELECT id, name FROM groups WHERE year_id=? ORDER BY name",
                          (yid,)).fetchall()
    conn.close()
    return render_template("dashboard.html", n_students=n_students,
                           n_groups=n_groups, n_sessions=n_sessions,
                           n_exams=n_exams, income=income,
                           month=month, recent_sessions=recent_sessions,
                           dash_groups=groups)


def _period_range(period, start=None, end=None):
    """يرجّع (start_date, end_date) بصيغة YYYY-MM-DD حسب الفترة المختارة.

    period: today | week | month | custom. للأسبوع: من السبت (بداية الأسبوع الدراسي) لليوم.
    """
    today = datetime.now().date()
    if period == "today":
        return today.isoformat(), today.isoformat()
    if period == "week":
        # بداية الأسبوع: السبت (weekday: الإثنين=0 ... الأحد=6؛ السبت=5)
        offset = (today.weekday() - 5) % 7
        s = today - timedelta(days=offset)
        return s.isoformat(), today.isoformat()
    if period == "custom" and start and end:
        return start, end
    # الافتراضي: هذا الشهر
    s = today.replace(day=1)
    return s.isoformat(), today.isoformat()


@app.route("/api/dashboard/attendance")
@login_required
def api_dashboard_attendance():
    """إحصائيات الحضور/الغياب/التأخير للعام النشط ضمن فترة ومجموعة اختيارية.

    لا تخلط بيانات أعوام سابقة (تُفلتر بـ year_id للحصص).
    """
    yid = active_year_id()
    period = request.args.get("period", "month")
    gid = request.args.get("group_id") or ""
    s, e = _period_range(period, request.args.get("start"), request.args.get("end"))
    conn = db.get_db()
    sql = ("SELECT a.status, COUNT(*) c FROM attendance a "
           "JOIN sessions se ON a.session_id=se.id "
           "WHERE se.year_id=? AND se.date>=? AND se.date<=?")
    params = [yid, s, e]
    if gid:
        sql += " AND se.group_id=?"
        params.append(gid)
    sql += " GROUP BY a.status"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    counts = {"present": 0, "late": 0, "absent": 0}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] = r["c"]
    total = sum(counts.values())
    pct = {k: (round(v * 100 / total) if total else 0) for k, v in counts.items()}
    return jsonify({"counts": counts, "total": total, "pct": pct,
                    "start": s, "end": e, "period": period})


@app.route("/api/dashboard/payments")
@login_required
def api_dashboard_payments():
    """المبالغ المحصّلة الفعلية (من سجلات الحضور المدفوعة) للعام النشط ضمن فترة.

    - today: تجميع حسب الساعة (من created_at وقت التسجيل).
    - week/month/custom: تجميع حسب اليوم (أو الأسبوع للشهر الطويل).
    لا يحسب مدفوعات مكرّرة (كل سجل حضور فريد بـ session+student).
    """
    yid = active_year_id()
    period = request.args.get("period", "today")
    gid = request.args.get("group_id") or ""
    s, e = _period_range(period, request.args.get("start"), request.args.get("end"))
    conn = db.get_db()
    base = ("FROM attendance a JOIN sessions se ON a.session_id=se.id "
            "WHERE a.paid=1 AND se.year_id=? AND se.date>=? AND se.date<=?")
    params = [yid, s, e]
    if gid:
        base += " AND se.group_id=?"
        params.append(gid)
    total = conn.execute("SELECT COALESCE(SUM(a.amount),0) t " + base,
                         params).fetchone()["t"]
    buckets = []
    if period == "today":
        # تجميع حسب ساعة التسجيل (created_at = 'YYYY-MM-DD HH:MM:SS')
        rows = conn.execute(
            "SELECT substr(a.created_at,12,2) h, COALESCE(SUM(a.amount),0) v " + base +
            " GROUP BY h ORDER BY h", params).fetchall()
        for r in rows:
            hh = r["h"] or "00"
            buckets.append({"label": f"{hh}:00", "value": r["v"]})
    else:
        # تجميع حسب اليوم (تاريخ الحصة)
        rows = conn.execute(
            "SELECT se.date d, COALESCE(SUM(a.amount),0) v " + base +
            " GROUP BY se.date ORDER BY se.date", params).fetchall()
        for r in rows:
            buckets.append({"label": r["d"], "value": r["v"]})
    conn.close()
    return jsonify({"total": total, "buckets": buckets,
                    "start": s, "end": e, "period": period})


# ---------------------------------------------------------------------------
# المجموعات
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# إدارة الأعوام الدراسية
# ---------------------------------------------------------------------------
@app.route("/years")
@login_required
def years():
    conn = db.get_db()
    rows = conn.execute(
        "SELECT y.*, "
        "(SELECT COUNT(*) FROM enrollments e WHERE e.year_id=y.id) n_students, "
        "(SELECT COUNT(*) FROM groups g WHERE g.year_id=y.id) n_groups, "
        "(SELECT COUNT(*) FROM sessions s WHERE s.year_id=y.id) n_sessions "
        "FROM academic_years y ORDER BY y.is_current DESC, y.name DESC").fetchall()
    # الترمات لكل عام
    terms_by_year = defaultdict(list)
    for t in conn.execute("SELECT * FROM terms ORDER BY start_date, id").fetchall():
        terms_by_year[t["year_id"]].append(t)
    conn.close()
    return render_template("years.html", years=rows, terms_by_year=terms_by_year)


@app.route("/years/add", methods=["POST"])
@login_required
def add_year():
    name = request.form.get("name", "").strip()
    if not name:
        flash("من فضلك أدخل اسم العام الدراسي (مثال: 2026/2027).", "error")
        return redirect(url_for("years"))
    conn = db.get_db()
    exists = conn.execute("SELECT 1 FROM academic_years WHERE name=?", (name,)).fetchone()
    if exists:
        conn.close()
        flash("هذا العام الدراسي موجود بالفعل.", "error")
        return redirect(url_for("years"))
    make_current = 1 if request.form.get("make_current") else 0
    if make_current:
        conn.execute("UPDATE academic_years SET is_current=0")
    conn.execute(
        "INSERT INTO academic_years(name,start_date,end_date,is_current,created_at) "
        "VALUES(?,?,?,?,?)",
        (name, request.form.get("start_date", ""), request.form.get("end_date", ""),
         make_current, db.now()))
    conn.commit()
    conn.close()
    flash(f"تم إنشاء العام الدراسي «{name}» ✅"
          + (" وتحديده كعام حالي." if make_current else ""), "success")
    return redirect(url_for("years"))


# ---------------------------------------------------------------------------
# الفصول الدراسية (الترمات) — تابعة لكل عام
# ---------------------------------------------------------------------------
@app.route("/years/<int:yid>/terms/add", methods=["POST"])
@login_required
def add_term(yid):
    name = request.form.get("name", "").strip()
    if not name:
        flash("من فضلك أدخل اسم الترم.", "error")
        return redirect(url_for("years"))
    conn = db.get_db()
    conn.execute(
        "INSERT INTO terms(year_id,name,start_date,end_date,created_at) VALUES(?,?,?,?,?)",
        (yid, name, request.form.get("start_date", ""), request.form.get("end_date", ""),
         db.now()))
    conn.commit()
    conn.close()
    flash(f"تمت إضافة الترم «{name}» ✅", "success")
    return redirect(url_for("years"))


@app.route("/terms/<int:tid>/edit", methods=["POST"])
@login_required
def edit_term(tid):
    conn = db.get_db()
    conn.execute("UPDATE terms SET name=?, start_date=?, end_date=? WHERE id=?",
                 (request.form.get("name", "").strip(), request.form.get("start_date", ""),
                  request.form.get("end_date", ""), tid))
    conn.commit()
    conn.close()
    flash("تم تعديل الترم ✅", "success")
    return redirect(url_for("years"))


@app.route("/terms/<int:tid>/delete")
@login_required
def delete_term(tid):
    conn = db.get_db()
    conn.execute("DELETE FROM terms WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    flash("تم حذف الترم", "success")
    return redirect(url_for("years"))


@app.route("/years/<int:yid>/set-current")
@login_required
def set_current_year_route(yid):
    db.set_current_year(yid)
    session.pop("browse_year", None)  # ارجع لعرض العام الحالي
    conn = db.get_db()
    y = conn.execute("SELECT name FROM academic_years WHERE id=?", (yid,)).fetchone()
    conn.close()
    flash(f"العام الدراسي الحالي الآن: {y['name'] if y else ''} ✅", "success")
    return redirect(url_for("years"))


@app.route("/years/<int:yid>/browse")
@login_required
def browse_year(yid):
    """تصفّح عام دراسي (قد يكون سابقًا للعرض فقط)."""
    conn = db.get_db()
    y = conn.execute("SELECT * FROM academic_years WHERE id=?", (yid,)).fetchone()
    conn.close()
    if not y:
        flash("العام الدراسي غير موجود.", "error")
        return redirect(url_for("years"))
    session["browse_year"] = yid
    if y["is_current"]:
        flash(f"أنت الآن تستعرض العام الدراسي الحالي: {y['name']}", "success")
    else:
        flash(f"أنت تستعرض بيانات عام دراسي سابق: {y['name']} (وضع العرض فقط).", "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/years/back-to-current")
@login_required
def back_to_current_year():
    session.pop("browse_year", None)
    flash("عدت إلى العام الدراسي الحالي.", "success")
    return redirect(request.referrer or url_for("dashboard"))


# ---------------------------------------------------------------------------
# إضافة طلاب للعام الدراسي (تسجيل الطلاب الموجودين في العام النشط)
# ---------------------------------------------------------------------------
@app.route("/years/enroll", methods=["GET"])
@login_required
def enroll_students():
    conn = db.get_db()
    yid = active_year_id()
    grps = conn.execute("SELECT * FROM groups WHERE year_id=? ORDER BY name", (yid,)).fetchall()
    # الطلاب غير المسجّلين في العام النشط (ليسوا في enrollments لهذا العام)
    unenrolled = conn.execute(
        "SELECT s.* FROM students s WHERE s.id NOT IN "
        "(SELECT student_id FROM enrollments WHERE year_id=?) ORDER BY s.name",
        (yid,)).fetchall()
    conn.close()
    return render_template("enroll.html", groups=grps, students=unenrolled)


@app.route("/years/enroll/do", methods=["POST"])
@login_required
def enroll_students_do():
    if _readonly_year_guard():
        return redirect(url_for("enroll_students"))
    yid = active_year_id()
    gid = request.form.get("group_id") or None
    ids = request.form.getlist("student_id")
    if not ids:
        flash("لم تختر أي طالب.", "error")
        return redirect(url_for("enroll_students"))
    conn = db.get_db()
    added = 0
    for sid in ids:
        exists = conn.execute(
            "SELECT 1 FROM enrollments WHERE student_id=? AND year_id=?", (sid, yid)).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO enrollments(student_id,year_id,group_id,status,created_at) "
            "VALUES(?,?,?,?,?)", (sid, yid, gid, "active", db.now()))
        added += 1
    conn.commit()
    conn.close()
    flash(f"تم تسجيل {added} طالبًا في العام الدراسي الحالي ✅", "success")
    return redirect(url_for("students"))


# ---------------------------------------------------------------------------
# ترحيل طالب بين المجموعات (داخل العام النشط) مع حفظ سجل الترحيل
# ---------------------------------------------------------------------------
@app.route("/students/<int:sid>/transfer", methods=["GET", "POST"])
@login_required
def transfer_student(sid):
    if request.method == "POST" and _readonly_year_guard():
        return redirect(url_for("students"))
    conn = db.get_db()
    yid = active_year_id()
    st = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    enr = conn.execute("SELECT * FROM enrollments WHERE student_id=? AND year_id=?",
                       (sid, yid)).fetchone()
    if not st or not enr:
        conn.close()
        flash("الطالب غير مسجّل في العام الحالي.", "error")
        return redirect(url_for("students"))
    if request.method == "POST":
        new_gid = request.form.get("to_group_id") or None
        old_gid = enr["group_id"]
        if str(new_gid) == str(old_gid):
            conn.close()
            flash("الطالب بالفعل في هذه المجموعة.", "error")
            return redirect(url_for("transfer_student", sid=sid))
        # حدّث المجموعة الحالية للتسجيل فقط (لا نلمس الحضور التاريخي)
        conn.execute("UPDATE enrollments SET group_id=? WHERE id=?", (new_gid, enr["id"]))
        # سجّل الترحيل في السجل التاريخي
        conn.execute(
            "INSERT INTO group_transfers(student_id,year_id,from_group_id,to_group_id,date,note,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (sid, yid, old_gid, new_gid, request.form.get("date") or db.now()[:10],
             request.form.get("note", ""), db.now()))
        conn.commit()
        conn.close()
        flash("تم ترحيل الطالب للمجموعة الجديدة (مع حفظ السجل التاريخي) ✅", "success")
        return redirect(url_for("student_profile", sid=sid))
    grps = conn.execute("SELECT * FROM groups WHERE year_id=? ORDER BY name", (yid,)).fetchall()
    cur_group = conn.execute("SELECT name FROM groups WHERE id=?", (enr["group_id"],)).fetchone() \
        if enr["group_id"] else None
    transfers = conn.execute(
        "SELECT t.*, fg.name from_name, tg.name to_name FROM group_transfers t "
        "LEFT JOIN groups fg ON t.from_group_id=fg.id "
        "LEFT JOIN groups tg ON t.to_group_id=tg.id "
        "WHERE t.student_id=? AND t.year_id=? ORDER BY t.id DESC", (sid, yid)).fetchall()
    conn.close()
    return render_template("transfer.html", st=st, enr=enr, groups=grps,
                           cur_group=cur_group, transfers=transfers)


@app.route("/groups")
@login_required
def groups():
    conn = db.get_db()
    yid = active_year_id()
    rows = conn.execute(
        "SELECT g.*, (SELECT COUNT(*) FROM enrollments e WHERE e.group_id=g.id "
        "AND e.year_id=g.year_id AND (e.status IS NULL OR e.status<>'inactive')) cnt "
        "FROM groups g WHERE g.year_id=? ORDER BY g.id DESC", (yid,)).fetchall()
    conn.close()
    return render_template("groups.html", groups=rows)


def _readonly_year_guard():
    """يمنع التعديل أثناء تصفّح عام سابق. يرجّع True لو ممنوع (وقد أضاف flash)."""
    if is_browsing_old_year():
        flash("أنت تستعرض عامًا دراسيًا سابقًا (عرض فقط). ارجع للعام الحالي لإجراء تعديلات.", "error")
        return True
    return False


@app.route("/groups/add", methods=["POST"])
@login_required
def add_group():
    if _readonly_year_guard():
        return redirect(url_for("groups"))
    conn = db.get_db()
    conn.execute("INSERT INTO groups(name,grade,fee,year_id,created_at) VALUES(?,?,?,?,?)",
                 (request.form["name"], request.form.get("grade", ""),
                  float(request.form.get("fee") or 0), active_year_id(), db.now()))
    conn.commit()
    conn.close()
    flash("تمت إضافة المجموعة بنجاح", "success")
    return redirect(url_for("groups"))


@app.route("/groups/<int:gid>/edit", methods=["POST"])
@login_required
def edit_group(gid):
    """تعديل بيانات المجموعة (الاسم/الصف/سعر الحصة) مع خيار تحديث رسوم الطلاب.

    عند تعديل سعر المجموعة، يمكن (اختياريًا، مفعّل افتراضيًا) تحديث سعر التخفيض
    الخاص بالطلاب المسجّلين بها في العام الحالي ليساوي السعر الجديد — فلا يُحتسب
    فارق السعر القديم كمديونية. لا يمسّ السجلات المالية التاريخية (attendance.
    fee_charged لقطة ثابتة)، والسعر الجديد يُطبَّق على الحصص القادمة تلقائيًا.
    """
    if _readonly_year_guard():
        return redirect(url_for("groups"))
    conn = db.get_db()
    yid = active_year_id()
    grp = conn.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not grp:
        conn.close()
        flash("المجموعة غير موجودة", "error")
        return redirect(url_for("groups"))
    name = request.form.get("name", "").strip() or grp["name"]
    grade = request.form.get("grade", "").strip()
    try:
        new_fee = float(request.form.get("fee") or 0)
    except (ValueError, TypeError):
        new_fee = grp["fee"] or 0
    conn.execute("UPDATE groups SET name=?, grade=?, fee=? WHERE id=?",
                 (name, grade, new_fee, gid))
    updated = 0
    if request.form.get("apply_to_students"):
        # حدّث سعر التخفيض للطلاب المسجّلين في هذه المجموعة بالعام الحالي.
        # نضبط discount_fee=السعر الجديد فيصبح هو السعر الفعلي المستحق (لا فرق دَين).
        cur = conn.execute(
            "UPDATE enrollments SET discount_fee=? WHERE group_id=? AND year_id=?",
            (new_fee, gid, yid))
        try:
            updated = cur.rowcount if cur.rowcount is not None else 0
        except Exception:
            updated = 0

    # تصحيح رجعي للسجلات السابقة (تصحيح خطأ إدخال سعر، وليس تخفيضًا): يحدّث سعر
    # الحصص السابقة لهذه المجموعة وسجلات الحضور، ويعيد حساب المتبقّي فلا يظهر فرق
    # السعر الخاطئ كمديونية متأخرة. لا يمسّ المبالغ المدفوعة فعلًا (amount).
    past_sessions = 0
    past_rows = 0
    if request.form.get("update_past"):
        syid = grp["year_id"] or yid
        # (1) حدّث سعر الحصص السابقة لهذه المجموعة في نفس عام المجموعة
        cur = conn.execute(
            "UPDATE sessions SET fee=? WHERE group_id=? AND year_id=?",
            (new_fee, gid, syid))
        try:
            past_sessions = cur.rowcount if cur.rowcount is not None else 0
        except Exception:
            past_sessions = 0
        # معرّفات حصص هذه المجموعة (لتحديث سجلات الحضور والتذكيرات المرتبطة بها)
        sess_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM sessions WHERE group_id=? AND year_id=?",
            (gid, syid)).fetchall()]
        if sess_ids:
            ph = ",".join("?" * len(sess_ids))
            # (2) حدّث السعر المستحق (fee_charged) لكل سجلات الحضور (عدا المعفيين)
            cur = conn.execute(
                f"UPDATE attendance SET fee_charged=? "
                f"WHERE session_id IN ({ph}) "
                f"AND (fee_exempt IS NULL OR fee_exempt=0)",
                [new_fee, *sess_ids])
            try:
                past_rows = cur.rowcount if cur.rowcount is not None else 0
            except Exception:
                past_rows = 0
            # (2-ب) صحّح مبلغ الطلاب الدافعين إلى السعر الجديد (كان مسجّلًا بالسعر
            #       الخاطئ فيصبح صحيحًا) — تصحيح خطأ إدخال لا يُحتسب فرقه كدخل زائد.
            conn.execute(
                f"UPDATE attendance SET amount=? "
                f"WHERE session_id IN ({ph}) AND paid=1 "
                f"AND (fee_exempt IS NULL OR fee_exempt=0)",
                [new_fee, *sess_ids])
            # (2-ج) صحّح سعر التخفيض المخزّن على تسجيل الطلاب (enrollments) للمجموعة
            conn.execute(
                "UPDATE enrollments SET discount_fee=? WHERE group_id=? AND year_id=?",
                (new_fee, gid, syid))
            # (3) أعد حساب المتبقّي: احذف تذكيرات لم يعد لها متبقٍّ (المدفوع ≥ السعر الجديد)
            #     وحدّث الباقية بالمتبقّي الصحيح = السعر الجديد − المدفوع (بعد التصحيح).
            for r in conn.execute(
                    f"SELECT a.student_id, a.session_id, a.amount, a.status "
                    f"FROM attendance a WHERE a.session_id IN ({ph}) "
                    f"AND (a.fee_exempt IS NULL OR a.fee_exempt=0)",
                    sess_ids).fetchall():
                remaining = round(new_fee - (r["amount"] or 0), 2)
                conn.execute(
                    "DELETE FROM reminders WHERE student_id=? AND session_id=? "
                    "AND status='pending'", (r["student_id"], r["session_id"]))
                if r["status"] in ("present", "late") and remaining > 0:
                    due = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                    conn.execute(
                        "INSERT INTO reminders(student_id,session_id,remaining,due_date,"
                        "due_time,method,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (r["student_id"], r["session_id"], remaining, due,
                         "09:00", "whatsapp", "pending", db.now()))

    conn.commit()
    conn.close()
    msg = f"تم تحديث المجموعة «{name}» (سعر الحصة: {new_fee:g} ج)."
    if request.form.get("apply_to_students"):
        msg += f" وطُبّق السعر الجديد على {updated} طالبًا مسجّلًا بها."
    if request.form.get("update_past"):
        msg += (f" وصُحِّحت {past_sessions} حصة سابقة و{past_rows} سجل حضور بالسعر"
                f" الجديد وأُعيد حساب المتأخرات.")
    flash(msg, "success")
    return redirect(url_for("groups"))


@app.route("/groups/delete/<int:gid>")
@login_required
def delete_group(gid):
    conn = db.get_db()
    conn.execute("DELETE FROM groups WHERE id=?", (gid,))
    conn.commit()
    conn.close()
    flash("تم حذف المجموعة", "success")
    return redirect(url_for("groups"))


@app.route("/groups/<int:gid>/history")
@login_required
def group_history(gid):
    """سجل حصص المجموعة مع الحاضرين والمحصّل والإجمالي التراكمي"""
    conn = db.get_db()
    grp = conn.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not grp:
        conn.close()
        return "المجموعة غير موجودة", 404
    sessions = conn.execute(
        "SELECT se.*, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.session_id=se.id AND a.status IN ('present','late')) attended, "
        "(SELECT COALESCE(SUM(amount),0) FROM attendance a WHERE a.session_id=se.id AND a.paid=1) collected "
        "FROM sessions se WHERE se.group_id=? ORDER BY se.date, se.id", (gid,)).fetchall()
    conn.close()
    # حساب الإجمالي التراكمي
    rows = []
    running = 0
    for s in sessions:
        running += s["collected"]
        rows.append({"date": s["date"], "title": s["title"] or "-",
                     "notes": s["notes"] if "notes" in s.keys() else "",
                     "attended": s["attended"], "collected": s["collected"],
                     "running": running, "id": s["id"]})
    total = running
    total_sessions = len(rows)
    return render_template("group_history.html", grp=grp, rows=rows,
                           total=total, total_sessions=total_sessions)


# ---------------------------------------------------------------------------
# الكتب/المذكرات المطبوعة
# ---------------------------------------------------------------------------
@app.route("/booklets")
@login_required
def booklets():
    conn = db.get_db()
    yid = active_year_id()
    gid = request.args.get("group", "")
    filt = request.args.get("filter", "")  # unpaid / paid / ""
    sql = ("SELECT b.*, s.name student_name, s.parent_phone, g.name group_name "
           "FROM booklets b JOIN students s ON b.student_id=s.id "
           "LEFT JOIN enrollments e ON e.student_id=s.id AND e.year_id=b.year_id "
           "LEFT JOIN groups g ON e.group_id=g.id WHERE b.year_id=?")
    params = [yid]
    if gid:
        sql += " AND e.group_id=?"
        params.append(gid)
    if filt == "unpaid":
        sql += " AND b.paid=0"
    elif filt == "paid":
        sql += " AND b.paid=1"
    sql += " ORDER BY b.date DESC, b.id DESC"
    rows = conn.execute(sql, params).fetchall()
    # إحصائيات (ضمن العام النشط)
    total_income = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM booklets WHERE paid=1 AND year_id=?", (yid,)).fetchone()["s"]
    unpaid_rows = conn.execute(
        "SELECT COALESCE(SUM(price-amount),0) s FROM booklets WHERE paid=0 AND year_id=?", (yid,)).fetchone()["s"]
    total_count = conn.execute("SELECT COUNT(*) n FROM booklets WHERE year_id=?", (yid,)).fetchone()["n"]
    # طلاب العام النشط الفعّالون (عبر التسجيل)
    studs = conn.execute(
        "SELECT s.* FROM enrollments e JOIN students s ON e.student_id=s.id "
        "WHERE e.year_id=? AND (e.status IS NULL OR e.status<>'inactive') ORDER BY s.name",
        (yid,)).fetchall()
    grps = conn.execute("SELECT * FROM groups WHERE year_id=? ORDER BY name", (yid,)).fetchall()
    conn.close()
    return render_template("booklets.html", rows=rows, students=studs, groups=grps,
                           total_income=total_income, unpaid_total=unpaid_rows,
                           total_count=total_count, sel_group=gid, sel_filter=filt,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/booklets/add", methods=["POST"])
@login_required
def add_booklet():
    price = float(request.form.get("price") or 0)
    paid = 1 if request.form.get("paid") else 0
    amount = float(request.form.get("amount") or 0)
    if paid and amount == 0:
        amount = price
    if not paid:
        amount = 0
    if _readonly_year_guard():
        return redirect(url_for("booklets"))
    conn = db.get_db()
    _sid = request.form["student_id"]
    _srow = conn.execute("SELECT name FROM students WHERE id=?", (_sid,)).fetchone()
    conn.execute(
        "INSERT INTO booklets(student_id,year_id,student_name_snapshot,title,price,paid,amount,date,notes,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (_sid, active_year_id(), (_srow["name"] if _srow else None),
         request.form.get("title", ""),
         price, paid, amount, request.form.get("date") or db.now()[:10],
         request.form.get("notes", ""), db.now()))
    conn.commit()
    conn.close()
    flash("تم تسجيل استلام الكتاب", "success")
    return redirect(url_for("booklets"))


@app.route("/booklets/<int:bid>/pay", methods=["POST"])
@login_required
def booklet_pay(bid):
    conn = db.get_db()
    b = conn.execute("SELECT * FROM booklets WHERE id=?", (bid,)).fetchone()
    if b:
        amount = float(request.form.get("amount") or b["price"])
        conn.execute("UPDATE booklets SET paid=1, amount=? WHERE id=?", (amount, bid))
        conn.commit()
    conn.close()
    flash("تم تسجيل دفع الكتاب", "success")
    return redirect(url_for("booklets"))


@app.route("/booklets/<int:bid>/delete")
@login_required
def booklet_delete(bid):
    conn = db.get_db()
    conn.execute("DELETE FROM booklets WHERE id=?", (bid,))
    conn.commit()
    conn.close()
    flash("تم حذف السجل", "success")
    return redirect(url_for("booklets"))


# ---------------------------------------------------------------------------
# الطلاب
# ---------------------------------------------------------------------------
@app.route("/students")
@login_required
def students():
    conn = db.get_db()
    yid = active_year_id()
    q = request.args.get("q", "").strip()
    gid = request.args.get("group", "")
    status = request.args.get("status", "active")  # active / inactive / all
    # الطلاب المسجّلون في العام النشط فقط (عبر enrollments)، بمجموعة وحالة العام
    sql = ("SELECT s.*, e.status enroll_status, e.group_id enroll_group_id, "
           "e.discount_fee, e.discount_reason, g.name group_name, g.fee group_fee "
           "FROM enrollments e JOIN students s ON e.student_id=s.id "
           "LEFT JOIN groups g ON e.group_id=g.id "
           "WHERE e.year_id=?")
    params = [yid]
    if status == "active":
        sql += " AND (e.status IS NULL OR e.status <> 'inactive')"
    elif status == "inactive":
        sql += " AND e.status = 'inactive'"
    if q:
        sql += " AND (s.name LIKE ? OR s.parent_phone LIKE ? OR s.phone LIKE ? OR s.code LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"]
    if gid:
        sql += " AND e.group_id=?"
        params.append(gid)
    sql += " ORDER BY s.name"
    rows = conn.execute(sql, params).fetchall()
    grps = conn.execute("SELECT * FROM groups WHERE year_id=? ORDER BY name", (yid,)).fetchall()
    # عدّادات للحالات (ضمن العام النشط)
    counts = {
        "active": conn.execute("SELECT COUNT(*) n FROM enrollments WHERE year_id=? AND (status IS NULL OR status<>'inactive')", (yid,)).fetchone()["n"],
        "inactive": conn.execute("SELECT COUNT(*) n FROM enrollments WHERE year_id=? AND status='inactive'", (yid,)).fetchone()["n"],
    }
    counts["all"] = counts["active"] + counts["inactive"]
    conn.close()
    return render_template("students.html", students=rows, groups=grps,
                           q=q, sel_group=gid, status=status, counts=counts)


@app.route("/students/add", methods=["POST"])
@login_required
def add_student():
    if _readonly_year_guard():
        return redirect(url_for("students"))
    conn = db.get_db()
    yid = active_year_id()
    gid = request.form.get("group_id") or None
    cur = conn.execute(
        "INSERT INTO students(name,phone,parent_phone,grade,group_id,notes,status,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (request.form["name"], request.form.get("phone", ""),
         request.form["parent_phone"], request.form.get("grade", ""),
         gid, request.form.get("notes", ""), "active", db.now()))
    new_sid = cur.lastrowid
    db.assign_student_credentials(conn, new_sid)
    # تخفيض رسوم الحصة (خاص بالطالب لهذا العام): NULL = لا تخفيض
    disc_fee, disc_reason = _parse_discount(request.form)
    # سجّل الطالب في العام الدراسي الحالي بالمجموعة المختارة + التخفيض إن وُجد
    conn.execute(
        "INSERT INTO enrollments(student_id,year_id,group_id,status,discount_fee,"
        "discount_reason,created_at) VALUES(?,?,?,?,?,?,?)",
        (new_sid, yid, gid, "active", disc_fee, disc_reason, db.now()))
    # ربط تلقائي بحساب ولي أمر موجود بنفس رقم الواتساب (لو أخوه مسجّل من قبل)
    linked_pid, linked_name = _auto_link_student_to_parent(
        conn, new_sid, request.form.get("parent_phone", ""))
    conn.commit()
    conn.close()
    if linked_pid:
        flash(f"تمت إضافة الطالب بنجاح ✅ وتم ربطه تلقائيًا بحساب ولي الأمر الموجود "
              f"«{linked_name}» (نفس رقم الواتساب).", "success")
    else:
        flash("تمت إضافة الطالب بنجاح (تم توليد كود وباسورد له)", "success")
    return redirect(url_for("students"))


@app.route("/students/edit/<int:sid>", methods=["POST"])
@login_required
def edit_student(sid):
    conn = db.get_db()
    conn.execute(
        "UPDATE students SET name=?, phone=?, parent_phone=?, grade=?, group_id=?, notes=? "
        "WHERE id=?",
        (request.form["name"], request.form.get("phone", ""),
         request.form["parent_phone"], request.form.get("grade", ""),
         request.form.get("group_id") or None,
         request.form.get("notes", ""), sid))
    # تحديث تخفيض رسوم الحصة على تسجيل العام النشط فقط (خاص بهذا العام — لا يُنسخ
    # تلقائيًا لأعوام أخرى). لا يمسّ السجلات المالية التاريخية (fee_charged ثابت).
    yid = active_year_id()
    disc_fee, disc_reason = _parse_discount(request.form)
    conn.execute(
        "UPDATE enrollments SET discount_fee=?, discount_reason=? "
        "WHERE student_id=? AND year_id=?", (disc_fee, disc_reason, sid, yid))
    # ربط تلقائي بحساب ولي أمر موجود بنفس رقم الواتساب (لو لم يكن مربوطًا بعد)
    linked_pid, linked_name = _auto_link_student_to_parent(
        conn, sid, request.form.get("parent_phone", ""))
    conn.commit()
    conn.close()
    if linked_pid:
        flash(f"تم تعديل بيانات الطالب ✅ وتم ربطه تلقائيًا بحساب ولي الأمر "
              f"«{linked_name}» (نفس رقم الواتساب).", "success")
    else:
        flash("تم تعديل بيانات الطالب", "success")
    return redirect(url_for("students"))


@app.route("/students/deactivate/<int:sid>", methods=["GET", "POST"])
@login_required
def deactivate_student(sid):
    """تعطيل الطالب (حذف ناعم) — يحتفظ بكل بياناته التاريخية.

    يقبل (اختياريًا) سبب التعطيل + إشعار واتساب لولي الأمر.
    """
    conn = db.get_db()
    st = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not st:
        conn.close()
        return "الطالب غير موجود", 404
    reason = request.form.get("reason", "").strip()
    notify = request.form.get("notify_parent") in ("1", "on", "true")
    yid = active_year_id()
    # حالة التعطيل لكل عام على حدة (على التسجيل enrollment)
    conn.execute(
        "UPDATE enrollments SET status='inactive' WHERE student_id=? AND year_id=?",
        (sid, yid))
    # حدّث الحقول التاريخية على الطالب (آخر تعطيل)
    conn.execute(
        "UPDATE students SET status='inactive', deactivated_at=?, deactivated_reason=? "
        "WHERE id=?", (db.now(), reason, sid))
    conn.commit()
    conn.close()
    name = st["name"]
    flash(f"تم تعطيل الطالب «{name}» في العام الحالي (بياناته محفوظة).", "success")

    # إشعار واتساب اختياري لولي الأمر
    if notify and (st["parent_phone"] or "").strip():
        tname = teacher_name()
        subj = db.get_setting("subject", "المادة")
        lines = [f"السلام عليكم، ولي أمر الطالب/ة {name}",
                 f"نفيدكم بإيقاف قيد الطالب في مجموعات مادة {subj}."]
        if reason:
            lines += ["", f"السبب: {reason}"]
        lines += ["", "للاستفسار أو إعادة القيد يُرجى التواصل معنا.",
                  "", f"مع تحيات {tname}"]
        msg = "\n".join(lines)
        # وضع API التلقائي: أرسل من الخادم مباشرة
        if wa.api_mode():
            ok, resp = wa.send_api(st["parent_phone"], msg, msg_type="deactivate")
            flash("تم إرسال إشعار التعطيل لولي الأمر ✅" if ok
                  else f"تعذّر إرسال الإشعار تلقائيًا: {resp}",
                  "success" if ok else "error")
            return redirect(request.referrer or url_for("students"))
        # وضع الروابط: افتح رابط واتساب جاهز
        return redirect(wa.wa_link(st["parent_phone"], msg))
    return redirect(request.referrer or url_for("students"))


@app.route("/students/reactivate/<int:sid>")
@login_required
def reactivate_student(sid):
    """إعادة تفعيل الطالب — يعود للقوائم والعمليات الحالية."""
    conn = db.get_db()
    st = conn.execute("SELECT name FROM students WHERE id=?", (sid,)).fetchone()
    yid = active_year_id()
    conn.execute("UPDATE enrollments SET status='active' WHERE student_id=? AND year_id=?",
                 (sid, yid))
    conn.execute("UPDATE students SET status='active', deactivated_at=NULL, "
                 "deactivated_reason=NULL WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    name = st["name"] if st else "الطالب"
    flash(f"تمت إعادة تفعيل الطالب «{name}» في العام الحالي ✅", "success")
    return redirect(request.referrer or url_for("students"))


@app.route("/students/delete/<int:sid>")
@login_required
def delete_student(sid):
    """توافق قديم: الحذف صار تعطيلًا (حذف ناعم) بدل الحذف الدائم."""
    return deactivate_student(sid)


@app.route("/students/permanent-delete/<int:sid>", methods=["POST"])
@login_required
def permanent_delete_student(sid):
    """حذف دائم للطالب وكل بياناته التاريخية — للأدمن فقط وبتأكيد صريح.

    يتطلب كتابة اسم الطالب بالضبط في نموذج التأكيد لمنع الحذف بالخطأ.
    """
    conn = db.get_db()
    st = conn.execute("SELECT name FROM students WHERE id=?", (sid,)).fetchone()
    if not st:
        conn.close()
        return "الطالب غير موجود", 404
    confirm = request.form.get("confirm_name", "").strip()
    if confirm != (st["name"] or "").strip():
        conn.close()
        flash("لم يتم الحذف: اسم التأكيد غير مطابق.", "error")
        return redirect(url_for("student_profile", sid=sid))
    # ═══════════════════════════════════════════════════════════════════
    # حذف الملف الشخصي مع الحفاظ التام على السجل المالي/التاريخي.
    # ═══════════════════════════════════════════════════════════════════
    # السبب الجذري لخطر فقد المال: قواعد قديمة أُنشئت قبل تصحيح المخطط قد يكون بها
    # قيد attendance/booklets بـ ON DELETE CASCADE، فيحذف حذفُ الطالب سجلاته المالية.
    # SQLite لا يعدّل قيود المفاتيح الأجنبية بالترحيل. الحل الحاسم المستقل عن تعريف
    # القيد وعن نوع القاعدة: (1) نحفظ لقطة الاسم/المجموعة على السجلات المالية،
    # (2) نفصلها عن الطالب صراحةً (student_id=NULL) فلا يطالها أي حذف تعاقبي،
    # (3) نحذف يدويًا السجلات غير المالية فقط، (4) ثم نحذف الطالب.
    name = (st["name"] or "").strip()

    # (1) لقطة الاسم/المجموعة على السجلات المالية (تبقى ظاهرة في التقارير)
    conn.execute(
        "UPDATE attendance SET student_name_snapshot=COALESCE(student_name_snapshot,?) "
        "WHERE student_id=?", (name, sid))
    conn.execute(
        "UPDATE attendance SET group_name_snapshot=COALESCE(group_name_snapshot, "
        "(SELECT name FROM groups WHERE id=attendance.group_id)) WHERE student_id=?", (sid,))
    conn.execute(
        "UPDATE booklets SET student_name_snapshot=COALESCE(student_name_snapshot,?) "
        "WHERE student_id=?", (name, sid))

    # (2) افصل السجلات المالية عن الطالب صراحةً — تبقى كسجل تاريخي بلقطة الاسم،
    #     ولا يمسّها حذف الطالب مهما كان تعريف قيد المفتاح الأجنبي (قديمًا كان CASCADE).
    conn.execute("UPDATE attendance SET student_id=NULL WHERE student_id=?", (sid,))
    conn.execute("UPDATE booklets SET student_id=NULL WHERE student_id=?", (sid,))

    # (3) احذف يدويًا السجلات غير المالية فقط (ملف/تسجيل/امتحانات/تذكيرات/روابط ولي أمر)
    #     — لا نعتمد على ON DELETE CASCADE (قد يكون غائبًا/مختلفًا في قواعد قديمة).
    #     حذف تذكيرات الدفع مقصود: لا نُظهر متأخّرات وهمية لطالب لم يعد موجودًا (البند 4).
    for tbl in ("enrollments", "group_transfers", "results", "exam_attempts",
                "reminders", "parent_students", "absence_alerts"):
        try:
            conn.execute(f"DELETE FROM {tbl} WHERE student_id=?", (sid,))
        except Exception:
            conn.rollback()  # جدول غير موجود في قاعدة قديمة — تجاهل بأمان

    # (4) احذف الملف الشخصي للطالب
    conn.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    flash(f"تم حذف بيانات الطالب «{name}» مع الاحتفاظ بسجلّاته المالية في التقارير.",
          "success")
    return redirect(url_for("students"))


@app.route("/students/regen/<int:sid>")
@login_required
def regen_credentials(sid):
    conn = db.get_db()
    db.assign_student_credentials(conn, sid)
    conn.commit()
    conn.close()
    flash("تم توليد كود وباسورد جديد للطالب", "success")
    return redirect(url_for("student_profile", sid=sid))


@app.route("/students/<int:sid>")
@login_required
def student_profile(sid):
    conn = db.get_db()
    yid = active_year_id()
    # بيانات الطالب + تسجيله ومجموعته في العام النشط
    st = conn.execute(
        "SELECT s.*, e.status enroll_status, e.group_id enroll_group_id, "
        "g.name group_name "
        "FROM students s "
        "LEFT JOIN enrollments e ON e.student_id=s.id AND e.year_id=? "
        "LEFT JOIN groups g ON e.group_id=g.id WHERE s.id=?", (yid, sid)).fetchone()
    if not st:
        conn.close()
        return "الطالب غير موجود", 404
    # الحضور والنتائج ضمن العام النشط فقط
    att = conn.execute(
        "SELECT a.*, se.date, se.title, g.name att_group FROM attendance a "
        "JOIN sessions se ON a.session_id=se.id "
        "LEFT JOIN groups g ON a.group_id=g.id "
        "WHERE a.student_id=? AND se.year_id=? ORDER BY se.date DESC", (sid, yid)).fetchall()
    res = conn.execute(
        "SELECT r.*, e.title, e.total_marks, e.is_online FROM results r "
        "JOIN exams e ON r.exam_id=e.id WHERE r.student_id=? AND e.year_id=? "
        "ORDER BY r.taken_at DESC", (sid, yid)).fetchall()
    stats = {"present": 0, "late": 0, "absent": 0, "paid_total": 0,
             "hw_done": 0, "hw_incomplete": 0, "hw_not_done": 0}
    for a in att:
        stats[a["status"]] = stats.get(a["status"], 0) + 1
        if a["paid"]:
            stats["paid_total"] += a["amount"]
        # إحصاء حالات الواجب (تقرير الواجبات) — «غير مكتمل» منفصل عن «لم يعمله»
        hw = a["homework"] if ("homework" in a.keys()) else None
        if hw == "done":
            stats["hw_done"] += 1
        elif hw == "incomplete":
            stats["hw_incomplete"] += 1
        elif hw == "not_done":
            stats["hw_not_done"] += 1
    avg_pct, att_pct, level = compute_level(conn, sid)
    # سجل الترحيل بين المجموعات في العام النشط
    transfers = conn.execute(
        "SELECT t.*, fg.name from_name, tg.name to_name FROM group_transfers t "
        "LEFT JOIN groups fg ON t.from_group_id=fg.id "
        "LEFT JOIN groups tg ON t.to_group_id=tg.id "
        "WHERE t.student_id=? AND t.year_id=? ORDER BY t.id DESC", (sid, yid)).fetchall()
    conn.close()
    qr = make_qr_datauri(f"STU:{st['code']}") if st["code"] else None
    return render_template("student_profile.html", st=st, att=att, res=res,
                           transfers=transfers,
                           stats=stats, status_ar=STATUS_AR, hw_ar=HW_AR,
                           qr=qr, avg_pct=avg_pct, att_pct=att_pct, level=level)


@app.route("/students/<int:sid>/card")
@login_required
def student_card(sid):
    """كارت الطالب للطباعة (فيه QR + الكود + الباسورد)"""
    conn = db.get_db()
    st = conn.execute("SELECT s.*, g.name group_name FROM students s "
                      "LEFT JOIN groups g ON s.group_id=g.id WHERE s.id=?",
                      (sid,)).fetchone()
    conn.close()
    if not st:
        return "الطالب غير موجود", 404
    qr = make_qr_datauri(f"STU:{st['code']}")
    return render_template("student_card.html", students=[st],
                           qr_map={st["id"]: qr}, single=True)


@app.route("/students/cards")
@login_required
def cards_select():
    """صفحة اختيار كروت QR: اختر مجموعة أو كل الطلاب (لا يُحمّل الكل افتراضيًا)."""
    conn = db.get_db()
    grps = conn.execute("SELECT * FROM groups ORDER BY name").fetchall()
    gid = request.args.get("group", "")
    scope = request.args.get("scope", "")   # "" (لم يُختر) / "group" / "all"
    students = None
    qr_map = {}
    if scope == "all":
        students = conn.execute("SELECT s.*, g.name group_name FROM students s "
                                "LEFT JOIN groups g ON s.group_id=g.id "
                                "WHERE (s.status IS NULL OR s.status<>'inactive') "
                                "ORDER BY s.name").fetchall()
    elif scope == "group" and gid:
        students = conn.execute("SELECT s.*, g.name group_name FROM students s "
                                "LEFT JOIN groups g ON s.group_id=g.id "
                                "WHERE s.group_id=? AND (s.status IS NULL OR s.status<>'inactive') "
                                "ORDER BY s.name", (gid,)).fetchall()
    if students is not None:
        qr_map = {s["id"]: make_qr_datauri(f"STU:{s['code']}") for s in students}
    conn.close()
    return render_template("cards_select.html", groups=grps, students=students,
                           qr_map=qr_map, scope=scope, sel_group=gid)


@app.route("/students/cards/print")
@login_required
def all_cards():
    """صفحة طباعة كروت QR — طلاب محددون (ids) أو مجموعة أو الكل."""
    conn = db.get_db()
    gid = request.args.get("group", "")
    scope = request.args.get("scope", "")
    ids_param = request.args.get("ids", "").strip()
    if ids_param:
        try:
            id_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
        except ValueError:
            id_list = []
        if id_list:
            ph = ",".join("?" for _ in id_list)
            studs = conn.execute(
                f"SELECT s.*, g.name group_name FROM students s "
                f"LEFT JOIN groups g ON s.group_id=g.id WHERE s.id IN ({ph}) ORDER BY s.name",
                tuple(id_list)).fetchall()
        else:
            studs = []
    elif gid:
        studs = conn.execute("SELECT s.*, g.name group_name FROM students s "
                             "LEFT JOIN groups g ON s.group_id=g.id "
                             "WHERE s.group_id=? AND (s.status IS NULL OR s.status<>'inactive') "
                             "ORDER BY s.name", (gid,)).fetchall()
    elif scope == "all":
        studs = conn.execute("SELECT s.*, g.name group_name FROM students s "
                             "LEFT JOIN groups g ON s.group_id=g.id "
                             "WHERE (s.status IS NULL OR s.status<>'inactive') "
                             "ORDER BY s.name").fetchall()
    else:
        studs = []
    conn.close()
    qr_map = {s["id"]: make_qr_datauri(f"STU:{s['code']}") for s in studs}
    return render_template("student_card.html", students=studs, qr_map=qr_map,
                           single=False)


@app.route("/students/<int:sid>/qr-whatsapp")
@login_required
def send_qr_whatsapp(sid):
    """إرسال كود QR الطالب عبر واتساب — لرقم الطالب و/أو ولي الأمر."""
    conn = db.get_db()
    st = conn.execute("SELECT s.*, g.name group_name FROM students s "
                      "LEFT JOIN groups g ON s.group_id=g.id WHERE s.id=?",
                      (sid,)).fetchone()
    conn.close()
    if not st:
        return "الطالب غير موجود", 404
    qr_url = f"{site_url()}{url_for('student_qr_public', code=st['code'])}"
    tname = teacher_name()
    subj = db.get_setting("subject", "المادة")
    msg = (f"السلام عليكم\n"
           f"كود QR الخاص بالطالب/ة *{st['name']}* في مادة {subj}:\n\n"
           f"المجموعة: {st['group_name'] or '-'}\n"
           f"كود الطالب: {_wa_code(st['code'])}\n\n"
           f"رابط عرض الكود (QR) للحضور والامتحان:\n{qr_url}\n\n"
           f"مع تحيات {tname}")
    messages = []
    # رقم الطالب لو متاح
    if (st["phone"] or "").strip():
        messages.append({"name": f"{st['name']} (هاتف الطالب)", "phone": st["phone"],
                         "status": f"كود: {st['code']}",
                         "link": wa.wa_link(st["phone"], msg), "msg": msg})
    # رقم ولي الأمر لو متاح
    if (st["parent_phone"] or "").strip():
        messages.append({"name": f"{st['name']} (ولي الأمر)", "phone": st["parent_phone"],
                         "status": f"كود: {st['code']}",
                         "link": wa.wa_link(st["parent_phone"], msg), "msg": msg})
    if not messages:
        flash("لا يوجد رقم هاتف للطالب ولا لولي الأمر لإرسال الكود.", "error")
        return redirect(url_for("cards_select"))
    return render_template("whatsapp.html", messages=messages,
                           title=f"إرسال كود QR: {st['name']}",
                           back=url_for("cards_select"))


def _student_login_message(st):
    """رسالة بيانات دخول الطالب لولي الأمر — كل قيمة في سطر مستقل بدون رموز
    ملتصقة لتسهيل نسخ الكود وكلمة المرور كلٍّ على حدة."""
    tname = teacher_name()
    subj = db.get_setting("subject", "المادة")
    base = site_url()
    login_link = f"{base}/student/{st['code']}/login" if base else ""
    card_link = f"{base}/student/{st['code']}/qr" if base else ""
    lines = [f"السلام عليكم، ولي أمر الطالب/ة {st['name']}",
             f"بيانات دخول الطالب لمنصة مادة {subj}:",
             "",
             "اسم المستخدم / كود الدخول:",
             _wa_code(st['code']),
             "",
             "كلمة المرور:",
             _wa_code(st['exam_password'])]
    if login_link:
        lines += ["", "لنسخ كلمة المرور بسهولة اضغط الرابط التالي:", login_link]
    if card_link:
        lines += ["", "كارت الطالب و QR Code:", card_link]
    lines += ["",
              "يُستخدم الكود لتسجيل الحضور بالـ QR ولدخول الامتحانات الإلكترونية.",
              "", f"مع تحيات {tname}"]
    return "\n".join(lines)


@app.route("/students/<int:sid>/send-login")
@login_required
def send_student_login(sid):
    """إرسال بيانات دخول الطالب (كود + باسورد + QR) لولي الأمر بضغطة واحدة"""
    conn = db.get_db()
    st = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not st:
        return "الطالب غير موجود", 404
    if not st["code"]:
        flash("لا يوجد كود لهذا الطالب. من فضلك ولّد له كودًا أولاً.", "error")
        return redirect(url_for("student_profile", sid=sid))
    msg = _student_login_message(st)
    messages = [{"name": st["name"], "phone": st["parent_phone"],
                 "status": f"كود: {st['code']}",
                 "link": wa.wa_link(st["parent_phone"], msg), "msg": msg}]
    return render_template("whatsapp.html", messages=messages,
                           title=f"إرسال بيانات دخول: {st['name']}",
                           back=url_for("student_profile", sid=sid))


@app.route("/students/send-login")
@login_required
def send_all_logins():
    """اختيار المجموعة أولًا ثم عرض طلابها فقط لاختيار من يُرسل لهم بيانات الدخول."""
    conn = db.get_db()
    grps = conn.execute("SELECT * FROM groups ORDER BY name").fetchall()
    gid = request.args.get("group", "")
    scope = request.args.get("scope", "")   # "" (لم يُختر) / "group" / "all"
    students = None
    if scope == "all":
        students = conn.execute(
            "SELECT s.*, g.name group_name FROM students s "
            "LEFT JOIN groups g ON s.group_id=g.id "
            "WHERE (s.status IS NULL OR s.status<>'inactive') ORDER BY s.name").fetchall()
    elif scope == "group" and gid:
        students = conn.execute(
            "SELECT s.*, g.name group_name FROM students s "
            "LEFT JOIN groups g ON s.group_id=g.id "
            "WHERE s.group_id=? AND (s.status IS NULL OR s.status<>'inactive') ORDER BY s.name",
            (gid,)).fetchall()
    conn.close()
    return render_template("send_logins.html", groups=grps, students=students,
                           scope=scope, sel_group=gid)


@app.route("/students/send-login/do", methods=["POST"])
@login_required
def send_logins_do():
    """توليد رسائل بيانات الدخول للطلاب المحدّدين فقط."""
    ids = request.form.getlist("student_id")
    sel_group = request.form.get("group", "")
    if not ids:
        flash("لم تختر أي طالب. حدّد طالبًا واحدًا على الأقل.", "error")
        return redirect(url_for("send_all_logins", scope="group", group=sel_group)
                        if sel_group else url_for("send_all_logins"))
    conn = db.get_db()
    ph = ",".join("?" for _ in ids)
    studs = conn.execute(
        f"SELECT * FROM students WHERE id IN ({ph}) ORDER BY name", tuple(ids)).fetchall()
    conn.close()
    messages = []
    for st in studs:
        if not st["code"]:
            continue
        msg = _student_login_message(st)
        messages.append({"name": st["name"], "phone": st["parent_phone"],
                         "status": f"كود: {st['code']}",
                         "link": wa.wa_link(st["parent_phone"], msg), "msg": msg})
    back = (url_for("send_all_logins", scope="group", group=sel_group)
            if sel_group else url_for("send_all_logins", scope="all"))
    return render_template("whatsapp.html", messages=messages,
                           title="إرسال بيانات دخول الطلاب المحدّدين",
                           back=back)


@app.route("/student/<code>/login")
def student_creds_public(code):
    """صفحة عامة لبيانات دخول الطالب مع أزرار «نسخ» لكل قيمة (كود + كلمة المرور).
    يفتحها ولي الأمر من رابط الواتساب فينسخ كلمة المرور بضغطة واحدة."""
    conn = db.get_db()
    st = conn.execute("SELECT * FROM students WHERE code=?", (code,)).fetchone()
    conn.close()
    if not st:
        return "غير موجود", 404
    base = site_url()
    rows = [
        {"label": "اسم المستخدم / كود الدخول", "value": st["code"], "copy": True},
        {"label": "كلمة المرور", "value": st["exam_password"], "copy": True},
    ]
    return render_template(
        "creds_public.html",
        title=f"بيانات دخول: {st['name']}",
        subtitle=f"منصة مادة {db.get_setting('subject', 'المادة')} — {teacher_name()}",
        rows=rows,
        portal_url=f"{base}/student/{st['code']}/qr" if base else "")


@app.route("/student/<code>/qr")
def student_qr_public(code):
    """صفحة عامة تعرض QR Code وبيانات دخول الطالب (يفتحها ولي الأمر من رابط الواتساب)"""
    conn = db.get_db()
    st = conn.execute("SELECT * FROM students WHERE code=?", (code,)).fetchone()
    conn.close()
    if not st:
        return "غير موجود", 404
    qr = make_qr_datauri(f"STU:{st['code']}")
    return render_template("student_qr_public.html", st=st, qr=qr,
                           subject=db.get_setting("subject", "المادة"),
                           teacher=teacher_name())


# ---------------------------------------------------------------------------
# إدارة حسابات أولياء الأمور (لوحة الأدمن)
# ---------------------------------------------------------------------------
@app.route("/parents")
@login_required
def parents():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM parents ORDER BY id DESC").fetchall()
    parents_list = []
    for p in rows:
        linked = conn.execute(
            "SELECT s.id, s.name FROM parent_students ps "
            "JOIN students s ON ps.student_id=s.id WHERE ps.parent_id=? ORDER BY s.name",
            (p["id"],)).fetchall()
        parents_list.append({**dict(p), "students": [dict(s) for s in linked]})
    all_students = conn.execute(
        "SELECT s.*, g.name group_name FROM students s "
        "LEFT JOIN groups g ON s.group_id=g.id ORDER BY s.name").fetchall()
    grps = conn.execute("SELECT * FROM groups ORDER BY name").fetchall()
    conn.close()
    # قائمة طلاب مبسّطة للواجهة (للفلترة حسب المجموعة + جلب رقم الواتساب تلقائيًا)
    students_js = [{"id": s["id"], "name": s["name"],
                    "group_id": s["group_id"], "group_name": s["group_name"] or "بدون مجموعة",
                    "parent_phone": s["parent_phone"] or ""} for s in all_students]
    return render_template("parents.html", parents=parents_list,
                           all_students=all_students, groups=grps,
                           students_js=students_js)


def _norm_phone(p):
    """تطبيع رقم الهاتف للمقارنة: أرقام فقط (يزيل المسافات/الرموز/الصفر الدولي)."""
    import re as _re
    d = _re.sub(r"\D", "", p or "")
    # وحّد الصيغة: أزل بادئة 002 أو 20 المصرية لو وُجدت مع 01
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("20") and len(d) > 10:
        d = d[2:]
    return d


def _find_parent_by_phone(conn, phone):
    """يرجّع حساب ولي أمر موجود بنفس رقم الواتساب (مطابقة مطبَّعة) أو None.

    يبحث في parents.phone، وإن لم يجد يبحث عبر أرقام أبناء أولياء الأمور الحاليين
    (parent_students → students.parent_phone) لالتقاط الحسابات القديمة.
    """
    target = _norm_phone(phone)
    if not target:
        return None
    # مطابقة مباشرة على parents.phone
    for p in conn.execute("SELECT * FROM parents").fetchall():
        if _norm_phone(p["phone"]) == target:
            return p
    # مطابقة عبر أرقام الأبناء المرتبطين
    rows = conn.execute(
        "SELECT DISTINCT ps.parent_id, s.parent_phone FROM parent_students ps "
        "JOIN students s ON ps.student_id=s.id "
        "WHERE s.parent_phone IS NOT NULL AND s.parent_phone<>''").fetchall()
    for r in rows:
        if _norm_phone(r["parent_phone"]) == target:
            return conn.execute("SELECT * FROM parents WHERE id=?", (r["parent_id"],)).fetchone()
    return None


def _auto_link_student_to_parent(conn, student_id, parent_phone):
    """يربط طالبًا تلقائيًا بحساب ولي أمر موجود بنفس رقم الواتساب (لو وُجد).

    الغرض (البند 1-أ): عند إضافة/تعديل طالب برقم ولي أمر مسجّل مسبقًا لأخيه،
    يُربط الطالب الجديد بنفس حساب ولي الأمر في parent_students بدل تجاهل الربط
    أو إنشاء حساب منفصل. آمن و idempotent (ON CONFLICT DO NOTHING).
    يرجّع (parent_id, parent_name) لو تم الربط، وإلا (None, None).
    """
    if not (parent_phone or "").strip():
        return (None, None)
    existing = _find_parent_by_phone(conn, parent_phone)
    if not existing:
        return (None, None)
    conn.execute(
        "INSERT INTO parent_students(parent_id,student_id) VALUES(?,?) "
        "ON CONFLICT(parent_id,student_id) DO NOTHING",
        (existing["id"], int(student_id)))
    return (existing["id"], existing["name"] or existing["username"])


def _unique_parent_username(conn, base):
    base = re.sub(r"\s+", "", base) or "parent"
    uname = base
    i = 1
    while conn.execute("SELECT 1 FROM parents WHERE username=?", (uname,)).fetchone():
        i += 1
        uname = f"{base}{i}"
    return uname


@app.route("/parents/check-phone")
@login_required
def parents_check_phone():
    """يفحص إن كان رقم واتساب مسجّلًا لحساب ولي أمر موجود (لتنبيه الواجهة قبل الإنشاء)."""
    phone = request.args.get("phone", "").strip()
    if not phone:
        return jsonify({"exists": False})
    conn = db.get_db()
    p = _find_parent_by_phone(conn, phone)
    if not p:
        conn.close()
        return jsonify({"exists": False})
    kids = conn.execute(
        "SELECT s.name FROM parent_students ps JOIN students s ON ps.student_id=s.id "
        "WHERE ps.parent_id=? ORDER BY s.name", (p["id"],)).fetchall()
    conn.close()
    return jsonify({"exists": True, "parent_id": p["id"],
                    "parent_name": p["name"] or p["username"],
                    "username": p["username"],
                    "children": [k["name"] for k in kids]})


@app.route("/parents/add", methods=["POST"])
@login_required
def add_parent():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    student_ids = [s for s in request.form.getlist("student_ids") if s]
    conn = db.get_db()

    if not student_ids:
        conn.close()
        flash("من فضلك اختر طالبًا واحدًا على الأقل لربطه بولي الأمر", "error")
        return redirect(url_for("parents"))

    # تحميل بيانات الطلاب المختارين (لجلب رقم واتساب ولي الأمر واسم الطالب تلقائيًا)
    ph = ",".join("?" * len(student_ids))
    studs = conn.execute(
        f"SELECT * FROM students WHERE id IN ({ph})",
        [int(s) for s in student_ids]).fetchall()
    if not studs:
        conn.close()
        flash("الطلاب المختارون غير موجودين", "error")
        return redirect(url_for("parents"))

    # رقم الواتساب يُؤخذ تلقائيًا من سجل الطالب (لا حاجة لإدخاله يدويًا)
    if not phone:
        for s in studs:
            if s["parent_phone"]:
                phone = s["parent_phone"]
                break

    # ── كشف ولي أمر موجود بنفس رقم الواتساب: نربط الطلاب بحسابه بدل إنشاء حساب جديد ──
    # (حساب واحد لولي الأمر لكل رقم واتساب — أبناء متعددون على نفس الحساب)
    force_new = request.form.get("force_new_account") == "1"
    if phone and not force_new:
        existing = _find_parent_by_phone(conn, phone)
        if existing:
            linked = 0
            for sid in student_ids:
                cur = conn.execute(
                    "INSERT INTO parent_students(parent_id,student_id) VALUES(?,?) "
                    "ON CONFLICT(parent_id,student_id) DO NOTHING", (existing["id"], int(sid)))
                linked += 1
            conn.commit()
            names = "، ".join(s["name"] for s in studs)
            conn.close()
            flash(f"هذا الرقم مسجّل بالفعل لولي أمر «{existing['name'] or existing['username']}». "
                  f"تمت إضافة ({names}) إلى حسابه الحالي بدل إنشاء حساب جديد ✅ "
                  f"(اسم المستخدم: {existing['username']}).", "success")
            return redirect(url_for("parents"))

    # اسم ولي الأمر الافتراضي: "ولي أمر <اسم الطالب>"
    if not name:
        name = f"ولي أمر {studs[0]['name']}"

    if not username:
        username = _unique_parent_username(conn, phone or name or "parent")
    elif conn.execute("SELECT 1 FROM parents WHERE username=?", (username,)).fetchone():
        conn.close()
        flash("اسم المستخدم موجود بالفعل، اختر اسمًا آخر", "error")
        return redirect(url_for("parents"))
    if not password:
        password = db.gen_pass(6)

    cur = conn.execute(
        "INSERT INTO parents(username,password_hash,name,phone,active,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (username, generate_password_hash(password), name, phone, 1, db.now()))
    pid = cur.lastrowid
    for sid in student_ids:
        try:
            conn.execute("INSERT INTO parent_students(parent_id,student_id) VALUES(?,?) "
                         "ON CONFLICT(parent_id,student_id) DO NOTHING", (pid, int(sid)))
        except Exception:
            pass
    conn.commit()
    conn.close()
    flash(f"تم إنشاء حساب ولي الأمر ✅ | اسم المستخدم: {username} | كلمة المرور: {password}"
          + (f" | واتساب: {phone}" if phone else ""), "success")
    return redirect(url_for("parents"))


@app.route("/parents/<int:pid>/edit", methods=["POST"])
@login_required
def edit_parent(pid):
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    username = request.form.get("username", "").strip()
    conn = db.get_db()
    exists = conn.execute("SELECT 1 FROM parents WHERE username=? AND id<>?",
                          (username, pid)).fetchone()
    if exists:
        conn.close()
        flash("اسم المستخدم مستخدم بالفعل", "error")
        return redirect(url_for("parents"))
    conn.execute("UPDATE parents SET name=?, phone=?, username=? WHERE id=?",
                 (name, phone, username, pid))
    # تحديث الطلاب المرتبطين
    conn.execute("DELETE FROM parent_students WHERE parent_id=?", (pid,))
    for sid in request.form.getlist("student_ids"):
        try:
            conn.execute("INSERT INTO parent_students(parent_id,student_id) VALUES(?,?)",
                         (pid, int(sid)))
        except Exception:
            pass
    conn.commit()
    conn.close()
    flash("تم تحديث بيانات ولي الأمر", "success")
    return redirect(url_for("parents"))


@app.route("/parents/<int:pid>/reset-password")
@login_required
def reset_parent_password(pid):
    newp = db.gen_pass(6)
    conn = db.get_db()
    row = conn.execute("SELECT username FROM parents WHERE id=?", (pid,)).fetchone()
    conn.execute("UPDATE parents SET password_hash=? WHERE id=?",
                 (generate_password_hash(newp), pid))
    conn.commit()
    conn.close()
    uname = row["username"] if row else ""
    flash(f"تم إعادة تعيين كلمة المرور ✅ | اسم المستخدم: {uname} | كلمة المرور الجديدة: {newp}", "success")
    return redirect(url_for("parents"))


@app.route("/parents/<int:pid>/toggle")
@login_required
def toggle_parent(pid):
    conn = db.get_db()
    row = conn.execute("SELECT active FROM parents WHERE id=?", (pid,)).fetchone()
    if row:
        conn.execute("UPDATE parents SET active=? WHERE id=?",
                     (0 if row["active"] else 1, pid))
        conn.commit()
    conn.close()
    flash("تم تغيير حالة الحساب", "success")
    return redirect(url_for("parents"))


@app.route("/parents/<int:pid>/delete")
@login_required
def delete_parent(pid):
    # حذف حساب بوابة ولي الأمر فقط — لا يمسّ الطلاب ولا بياناتهم المالية/الأكاديمية.
    # نفصل روابط الأبناء صراحةً (بدل الاعتماد على ON DELETE CASCADE) ثم نحذف الحساب،
    # فيبقى كل طالب وسجلّه المالي والحضور والامتحانات كما هو (البند 6).
    conn = db.get_db()
    conn.execute("DELETE FROM parent_students WHERE parent_id=?", (pid,))
    conn.execute("DELETE FROM parents WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    flash("تم حذف حساب بوابة ولي الأمر فقط — الطلاب وبياناتهم المالية والأكاديمية محفوظة.",
          "success")
    return redirect(url_for("parents"))


@app.route("/parents/<int:pid>/send-login")
@login_required
def send_parent_login(pid):
    """إرسال بيانات دخول البوابة لولي الأمر على الواتساب (يتطلب إعادة تعيين كلمة المرور لإظهارها)."""
    conn = db.get_db()
    p = conn.execute("SELECT * FROM parents WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "غير موجود", 404
    # رقم الواتساب: من حساب ولي الأمر، وإلا من سجل أحد أبنائه تلقائيًا
    phone = (p["phone"] or "").strip()
    if not phone:
        srow = conn.execute(
            "SELECT s.parent_phone FROM parent_students ps "
            "JOIN students s ON ps.student_id=s.id "
            "WHERE ps.parent_id=? AND s.parent_phone IS NOT NULL AND s.parent_phone<>'' "
            "LIMIT 1", (pid,)).fetchone()
        if srow:
            phone = srow["parent_phone"]
    # كلمة المرور مشفّرة؛ نولّد واحدة جديدة عند الإرسال لضمان معرفتها
    newp = db.gen_pass(6)
    conn.execute("UPDATE parents SET password_hash=? WHERE id=?",
                 (generate_password_hash(newp), pid))
    conn.commit()
    conn.close()
    # نخزّن كلمة المرور الجديدة (نصًّا) لعرضها في صفحة النسخ العامة برمز عشوائي،
    # حتى يفتحها ولي الأمر من رابط الواتساب وينسخ كلمة المرور بضغطة واحدة.
    tok = db.gen_pass(10)
    db.set_state("parent_creds", tok, json.dumps({"pid": pid, "password": newp},
                                                 ensure_ascii=False))
    creds_link = f"{site_url()}/parent-login/{tok}"
    portal = f"{site_url()}/parent/login"
    tname = teacher_name()
    # قائمة الأبناء المرتبطين بهذا الحساب (تُعرض في الرسالة)
    conn2 = db.get_db()
    children = conn2.execute(
        "SELECT s.name FROM parent_students ps JOIN students s ON ps.student_id=s.id "
        "WHERE ps.parent_id=? ORDER BY s.name", (pid,)).fetchall()
    conn2.close()
    kids_lines = "\n".join(f"- {k['name']}" for k in children) or "-"
    # صياغة تسهّل على ولي الأمر نسخ كل قيمة على حدة (اسم المستخدم/كلمة المرور
    # في سطر مستقل وبدون رموز ملتصقة بالقيمة نفسها). القالب parent_login إن وُجد.
    msg = wa.render_template(
        "parent_login", student=(children[0]["name"] if children else ""),
        username=_wa_code(p["username"]), password=_wa_code(newp),
        portal_url=portal, teacher=tname)
    if not (msg or "").strip():
        msg = (f"بيانات الدخول إلى بوابة ولي الأمر:\n\n"
               f"اسم المستخدم:\n{_wa_code(p['username'])}\n\n"
               f"كلمة المرور:\n{_wa_code(newp)}\n\n"
               f"رابط الدخول:\n{portal}\n\n"
               f"مع تحيات {tname}")
    # ألحق قائمة الأبناء المرتبطين بالحساب
    msg += f"\n\nالأبناء المرتبطون بهذا الحساب:\n{kids_lines}"
    # ألحق رابط صفحة النسخ (زر «نسخ» لكلمة المرور بضغطة واحدة على الموبايل)
    msg += (f"\n\nلنسخ كلمة المرور بسهولة اضغط الرابط التالي:\n{creds_link}")
    messages = [{"name": p["name"] or p["username"], "phone": phone,
                 "status": "بيانات الدخول",
                 "link": wa.wa_link(phone, msg), "msg": msg,
                 "copy_username": p["username"], "copy_password": newp}]
    return render_template("whatsapp.html", messages=messages,
                           title=f"إرسال بيانات دخول: {p['name'] or p['username']}",
                           back=url_for("parents"))


@app.route("/parent-login/<token>")
def parent_creds_public(token):
    """صفحة عامة (برمز عشوائي) لبيانات دخول بوابة ولي الأمر مع زر «نسخ» لكلمة
    المرور. يفتحها ولي الأمر من رابط الواتساب فينسخ كلمة المرور بضغطة واحدة."""
    raw = db.get_state("parent_creds", token)
    if not raw:
        return "انتهت صلاحية الرابط أو غير صحيح", 404
    try:
        info = json.loads(raw)
    except (ValueError, TypeError):
        return "رابط غير صالح", 404
    conn = db.get_db()
    p = conn.execute("SELECT * FROM parents WHERE id=?", (info.get("pid"),)).fetchone()
    conn.close()
    if not p:
        return "الحساب غير موجود", 404
    portal = f"{site_url()}/parent/login"
    rows = [
        {"label": "اسم المستخدم", "value": p["username"], "copy": True},
        {"label": "كلمة المرور", "value": info.get("password", ""), "copy": True},
    ]
    return render_template(
        "creds_public.html",
        title=f"بوابة أولياء الأمور — {p['name'] or p['username']}",
        subtitle=f"مع تحيات {teacher_name()}",
        rows=rows, portal_url=portal)


# ---------------------------------------------------------------------------
# الحصص + الحضور + الواجب + حساب الحصة
# ---------------------------------------------------------------------------
@app.route("/sessions")
@login_required
def sessions():
    conn = db.get_db()
    yid = active_year_id()
    rows = conn.execute(
        "SELECT se.*, g.name group_name, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.session_id=se.id) marked, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.session_id=se.id AND a.status IN ('present','late')) attended, "
        "(SELECT COALESCE(SUM(amount),0) FROM attendance a WHERE a.session_id=se.id AND a.paid=1) income "
        "FROM sessions se LEFT JOIN groups g ON se.group_id=g.id "
        "WHERE se.year_id=? ORDER BY se.date DESC, se.id DESC", (yid,)).fetchall()
    grps = conn.execute("SELECT * FROM groups WHERE year_id=? ORDER BY name", (yid,)).fetchall()
    conn.close()
    return render_template("sessions.html", sessions=rows, groups=grps,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/sessions/add", methods=["POST"])
@login_required
def add_session():
    if _readonly_year_guard():
        return redirect(url_for("sessions"))
    conn = db.get_db()
    yid = active_year_id()
    gid = request.form.get("group_id") or None
    fee = request.form.get("fee")
    if not fee and gid:
        g = conn.execute("SELECT fee FROM groups WHERE id=?", (gid,)).fetchone()
        fee = g["fee"] if g else 0
    conn.execute("INSERT INTO sessions(group_id,year_id,title,date,fee,notes,created_at) "
                 "VALUES(?,?,?,?,?,?,?)",
                 (gid, yid, request.form.get("title", ""), request.form["date"],
                  float(fee or 0), request.form.get("notes", ""), db.now()))
    conn.commit()
    conn.close()
    flash("تمت إضافة الحصة", "success")
    return redirect(url_for("sessions"))


@app.route("/sessions/delete/<int:sid>")
@login_required
def delete_session(sid):
    conn = db.get_db()
    conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    flash("تم حذف الحصة", "success")
    return redirect(url_for("sessions"))


@app.route("/sessions/<int:sid>")
@login_required
def session_detail(sid):
    conn = db.get_db()
    se = conn.execute(
        "SELECT se.*, g.name group_name FROM sessions se "
        "LEFT JOIN groups g ON se.group_id=g.id WHERE se.id=?", (sid,)).fetchone()
    if not se:
        conn.close()
        return "الحصة غير موجودة", 404
    syid = se["year_id"] or active_year_id()
    group_fee = se["fee"] or 0
    # الطلاب المسجّلون النشطون في مجموعة الحصة لهذا العام (عبر enrollments) + تخفيضهم
    if se["group_id"]:
        studs = conn.execute(
            "SELECT s.*, e.discount_fee FROM enrollments e JOIN students s ON e.student_id=s.id "
            "WHERE e.year_id=? AND e.group_id=? "
            "AND (e.status IS NULL OR e.status<>'inactive') ORDER BY s.name",
            (syid, se["group_id"])).fetchall()
    else:
        studs = conn.execute(
            "SELECT s.*, e.discount_fee FROM enrollments e JOIN students s ON e.student_id=s.id "
            "WHERE e.year_id=? AND (e.status IS NULL OR e.status<>'inactive') ORDER BY s.name",
            (syid,)).fetchall()
    existing = {a["student_id"]: a for a in conn.execute(
        "SELECT * FROM attendance WHERE session_id=?", (sid,)).fetchall()}
    # طلاب لديهم حضور مسجّل سابقًا في هذه الحصة لكنهم غير مدرجين الآن (عرض تاريخي)
    shown_ids = {s["id"] for s in studs}
    hist = conn.execute(
        "SELECT DISTINCT s.*, e.discount_fee FROM students s "
        "JOIN attendance a ON a.student_id=s.id "
        "LEFT JOIN enrollments e ON e.student_id=s.id AND e.year_id=? "
        "WHERE a.session_id=? ORDER BY s.name", (syid, sid)).fetchall()
    extra = [h for h in hist if h["id"] not in shown_ids]
    if extra:
        studs = list(studs) + list(extra)
    # السعر الفعلي المستحق لكل طالب (تخفيض إن وُجد، وإلا سعر المجموعة)
    eff_fee = {}
    for s in studs:
        d = s["discount_fee"] if "discount_fee" in s.keys() else None
        eff_fee[s["id"]] = float(d) if d is not None else float(group_fee)
    conn.close()
    # قائمة أسباب الإعفاء الجاهزة (تظهر للمدرس فقط)
    exempt_reasons = ["منحة", "أخو/أخت طالب", "قرار إداري", "سبب خاص"]
    return render_template("session_detail.html", se=se, students=studs,
                           group_fee=group_fee, eff_fee=eff_fee,
                           existing=existing, status_ar=STATUS_AR,
                           exempt_reasons=exempt_reasons)


@app.route("/sessions/<int:sid>/notes", methods=["POST"])
@login_required
def save_session_notes(sid):
    """حفظ/تعديل اسم الدرس وملاحظات الحصة (على مستوى الحصة نفسها بمعرّفها الحالي).

    يُحدّث السجل القائم فقط (نفس ID) دون إنشاء حصة جديدة، فتبقى كل سجلات الحضور
    والمدفوعات مرتبطة بنفس الحصة. الاسم الجديد يظهر في كل صفحات عرض الحصة/التقارير.
    اسم الدرس وملاحظات كل حصة مستقلة تمامًا (وليست على مستوى المجموعة).
    قابلة للتعديل حتى بعد تسجيل الحضور، ما لم يكن العام مقفولًا للعرض.
    """
    if is_browsing_old_year():
        return jsonify({"ok": False, "error": "عام سابق (عرض فقط)"}), 403
    conn = db.get_db()
    se = conn.execute("SELECT id, title, notes FROM sessions WHERE id=?", (sid,)).fetchone()
    if not se:
        conn.close()
        return jsonify({"ok": False, "error": "الحصة غير موجودة"}), 404
    data = request.get_json() or {}
    # نحدّث فقط الحقول المُرسَلة (تجزئة آمنة): اسم الدرس و/أو الملاحظات، بلا لمس
    # أي بيانات أخرى للحصة (المجموعة/التاريخ/السعر) أو سجلاتها المرتبطة.
    notes = data.get("notes", se["notes"])
    title = data.get("title", se["title"])
    conn.execute("UPDATE sessions SET title=?, notes=? WHERE id=?",
                 (title, notes, sid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


def _check_absence_alerts(conn, student_ids, year_id):
    """يفحص تكرار غياب الطلاب مقابل الحد المضبوط، وينشئ تنبيهًا مرة واحدة لكل حد.

    - يعدّ غيابات الطالب في العام الدراسي (attendance.status='absent').
    - عند بلوغ/تجاوز الحد ولم يُرسَل تنبيه لهذا الحد من قبل: يسجّله في absence_alerts
      (منع التكرار)، ويُرسل واتساب لولي الأمر لو مفعّل والـ API متاح.
    يرجّع قائمة بالتنبيهات المُنشأة حديثًا (للعرض/التشخيص).
    """
    created = []
    if db.get_setting("absence_alert_enabled", "0") != "1":
        return created
    try:
        threshold = int(db.get_setting("absence_alert_threshold", "3"))
    except (ValueError, TypeError):
        threshold = 3
    if threshold < 1:
        return created
    notify_site = db.get_setting("absence_alert_notify_site", "1") == "1"
    notify_wa = db.get_setting("absence_alert_notify_wa", "1") == "1"
    subject = db.get_setting("subject", "المادة")
    for st_id in set(student_ids):
        # عدد غيابات الطالب في هذا العام
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM attendance a JOIN sessions s ON a.session_id=s.id "
            "WHERE a.student_id=? AND a.status='absent' AND s.year_id=?",
            (st_id, year_id)).fetchone()["c"]
        if cnt < threshold:
            continue
        # هل أُرسل تنبيه لهذا الحد من قبل؟ (منع التكرار)
        exists = conn.execute(
            "SELECT 1 FROM absence_alerts WHERE student_id=? AND year_id=? AND threshold=?",
            (st_id, year_id, threshold)).fetchone()
        if exists:
            continue
        st = conn.execute("SELECT * FROM students WHERE id=?", (st_id,)).fetchone()
        if not st:
            continue
        wa_sent = 0
        wa_error = None
        # إرسال واتساب لولي الأمر (لو مفعّل والـ API متاح)
        if notify_wa:
            parent_phone = st["parent_phone"] if ("parent_phone" in st.keys()) else None
            if not parent_phone:
                wa_error = "لا يوجد رقم واتساب مسجل لولي الأمر لهذا الطالب."
            elif not wa.template_is_complete("absence_alert"):
                wa_error = "قالب رسالة تنبيه الغياب غير مكتمل."
            elif wa.api_mode():
                msg = wa.render_template("absence_alert", student=st["name"],
                                        absence_count=cnt, subject=subject)
                ok, _resp = wa.send_api(parent_phone, msg, msg_type="absence_alert")
                wa_sent = 1 if ok else 0
                if not ok:
                    wa_error = "تعذّر إرسال رسالة الواتساب."
        # سجّل التنبيه (يمنع التكرار لنفس الحد) — الإشعار الداخلي يُقرأ من هذا الجدول
        conn.execute(
            "INSERT INTO absence_alerts(student_id,year_id,threshold,absence_count,"
            "notified_site,notified_wa,created_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(student_id,year_id,threshold) DO NOTHING",
            (st_id, year_id, threshold, cnt, 1 if notify_site else 0, wa_sent, db.now()))
        created.append({"student": st["name"], "count": cnt, "wa_sent": bool(wa_sent),
                        "error": wa_error})
    conn.commit()
    return created


def _parse_discount(form):
    """يقرأ حقول التخفيض من نموذج الطالب ويرجّع (discount_fee, discount_reason).

    - discount_fee = None لو التخفيض غير مفعّل أو القيمة فارغة/غير صالحة (= لا تخفيض،
      يُستخدم سعر المجموعة). قيمة رقمية = سعر الحصة الخاص بالطالب (يشمل 0 لو أُدخل).
    - التخفيض منفصل تمامًا عن الإعفاء (fee_exempt) الذي يُدار على مستوى الحصة.
    """
    if not form.get("has_discount"):
        return (None, None)
    raw = (form.get("discount_fee") or "").strip()
    if raw == "":
        return (None, None)
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return (None, None)
    if val < 0:
        return (None, None)
    reason = (form.get("discount_reason") or "").strip() or None
    return (val, reason)


def _effective_fee(conn, student_id, year_id, group_fee):
    """السعر الفعلي المستحق على الطالب في حصة: سعر التخفيض الخاص به لهذا العام إن
    وُجد (enrollments.discount_fee غير NULL)، وإلا سعر المجموعة الافتراضي.

    التخفيض ليس إعفاءً وليس دَينًا: هو سعر حصة خاص بالطالب. NULL = لا تخفيض.
    """
    try:
        enr = conn.execute(
            "SELECT discount_fee FROM enrollments WHERE student_id=? AND year_id=?",
            (student_id, year_id)).fetchone()
    except Exception:
        enr = None
    if enr is not None and enr["discount_fee"] is not None:
        try:
            return float(enr["discount_fee"])
        except (ValueError, TypeError):
            pass
    return float(group_fee or 0)


@app.route("/sessions/<int:sid>/save", methods=["POST"])
@login_required
def save_attendance(sid):
    if is_browsing_old_year():
        return jsonify({"ok": False, "error": "عام سابق (عرض فقط)"}), 403
    conn = db.get_db()
    se = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    group_fee = se["fee"] or 0
    syid = se["year_id"] or active_year_id()
    data = request.get_json()
    reminders_created = 0
    skipped = 0
    for item in data["records"]:
        st_id = item["student_id"]
        status = item["status"]
        # طالب لم تُحدَّد حالته (لا حاضر ولا متأخر ولا غائب): لا يُسجَّل إطلاقًا،
        # فلا يُحتسب عليه حضور ولا دَين. هذا يمنع احتساب طالب لم يأتِ أصلًا كمتأخر
        # في السداد لمجرّد أن الافتراضي كان «حاضر». (لا نلمس أي سجل قائم له.)
        if status not in ("present", "late", "absent"):
            skipped += 1
            continue
        homework = item.get("homework", "none")
        if homework not in HW_STATUSES:
            homework = "none"
        # السعر الفعلي المستحق على هذا الطالب = سعر التخفيض الخاص به إن وُجد، وإلا
        # سعر المجموعة. كل حسابات المتبقّي/التذكير تُبنى على هذا السعر (وليس سعر المجموعة).
        fee = _effective_fee(conn, st_id, syid, group_fee)
        # إعفاء الطالب من رسوم هذه الحصة (غير مطالَب بالدفع)
        fee_exempt = 1 if item.get("fee_exempt") else 0
        exempt_reason = (item.get("exempt_reason") or "").strip() if fee_exempt else ""
        paid = 1 if item.get("paid") else 0
        amount = float(item.get("amount") or 0)
        if paid and amount == 0:
            amount = fee
        if not paid:
            amount = 0
        # المعفى غير مطالَب بالدفع: لا نحتسب له مبلغًا مستحقًا (لكن نُبقي أي مبلغ
        # سجّله المدرس فعليًا كتحصيل استثنائي — لا نمسّ سجلات الدفع التاريخية).
        # نحفظ السعر المستحق كلقطة ثابتة على السجل (fee_charged) لعدم تأثّر السجلات
        # التاريخية بأي تعديل مستقبلي على التخفيض (البند 17).
        fee_charged = 0 if fee_exempt else fee
        # مدى تركيز الطالب (نسبة مئوية 0-100). NULL لو لم يُرسَل (غير مسجّل).
        focus_level = item.get("focus_level", None)
        if focus_level in ("", None):
            focus_level = None
        else:
            try:
                focus_level = max(0, min(100, int(float(focus_level))))
            except (ValueError, TypeError):
                focus_level = None
        # المجموعة وقت التسجيل = مجموعة الطالب في تسجيل هذا العام (سجل تاريخي)
        enr = conn.execute(
            "SELECT group_id FROM enrollments WHERE student_id=? AND year_id=?",
            (st_id, syid)).fetchone()
        grp_id = enr["group_id"] if enr else se["group_id"]
        # لقطة اسم الطالب والمجموعة (للحفاظ على السجل المالي بعد حذف الطالب)
        srow = conn.execute("SELECT name FROM students WHERE id=?", (st_id,)).fetchone()
        sname = srow["name"] if srow else None
        grow = conn.execute("SELECT name FROM groups WHERE id=?", (grp_id,)).fetchone() if grp_id else None
        gname = grow["name"] if grow else None
        conn.execute(
            "INSERT INTO attendance(session_id,student_id,group_id,student_name_snapshot,"
            "group_name_snapshot,status,homework,paid,amount,fee_exempt,exempt_reason,"
            "fee_charged,focus_level,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(session_id,student_id) DO UPDATE SET "
            "group_id=excluded.group_id, student_name_snapshot=excluded.student_name_snapshot, "
            "group_name_snapshot=excluded.group_name_snapshot, status=excluded.status, "
            "homework=excluded.homework, paid=excluded.paid, amount=excluded.amount, "
            "fee_exempt=excluded.fee_exempt, exempt_reason=excluded.exempt_reason, "
            "fee_charged=excluded.fee_charged, focus_level=excluded.focus_level",
            (sid, st_id, grp_id, sname, gname, status, homework, paid, amount,
             fee_exempt, exempt_reason, fee_charged, focus_level, db.now()))

        # تذكير المتأخرات: لو الطالب حاضر ودفع أقل من سعر الحصة.
        # المعفى من الرسوم لا يُنشأ له تذكير إطلاقًا (غير مطالَب بالدفع) — ونمسح أي
        # تذكير سابق له لنفس الحصة حتى لا يظهر في التذكيرات/غير المدفوع.
        conn.execute("DELETE FROM reminders WHERE student_id=? AND session_id=? "
                     "AND status='pending'", (st_id, sid))
        if status in ("present", "late") and fee > 0 and not fee_exempt:
            remaining = round(fee - amount, 2)
            if remaining > 0:
                due = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO reminders(student_id,session_id,remaining,due_date,"
                    "due_time,method,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (st_id, sid, remaining, due, "09:00", "whatsapp", "pending", db.now()))
                reminders_created += 1
    conn.commit()
    # فحص تنبيه تكرار الغياب فقط للطلاب المسجَّلين فعليًا (بحالة محدّدة)
    checked_ids = [it["student_id"] for it in data["records"]
                   if it.get("status") in ("present", "late", "absent")]
    absence_alerts = _check_absence_alerts(conn, checked_ids, syid)
    conn.close()
    return jsonify({"ok": True, "reminders": reminders_created,
                    "absence_alerts": absence_alerts, "skipped": skipped})


# ---- تسجيل الحضور بالـ QR ----
@app.route("/scan/<int:sid>")
@login_required
def scan_attendance(sid):
    conn = db.get_db()
    se = conn.execute(
        "SELECT se.*, g.name group_name FROM sessions se "
        "LEFT JOIN groups g ON se.group_id=g.id WHERE se.id=?", (sid,)).fetchone()
    conn.close()
    if not se:
        return "الحصة غير موجودة", 404
    return render_template("scan.html", se=se)


@app.route("/scan/<int:sid>/mark", methods=["POST"])
@login_required
def scan_mark(sid):
    """يستقبل كود QR ويسجّل حضور الطالب"""
    code = (request.get_json() or {}).get("code", "").strip()
    if code.startswith("STU:"):
        code = code[4:]
    conn = db.get_db()
    st = conn.execute("SELECT * FROM students WHERE code=?", (code,)).fetchone()
    if not st:
        conn.close()
        return jsonify({"ok": False, "msg": "كود غير معروف"})
    se = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    # سجّل حاضر (لو موجود بالفعل، سيبه)
    existing = conn.execute("SELECT * FROM attendance WHERE session_id=? AND student_id=?",
                            (sid, st["id"])).fetchone()
    if existing:
        conn.close()
        return jsonify({"ok": True, "name": st["name"], "already": True,
                        "msg": "مسجّل حضوره بالفعل"})
    conn.execute(
        "INSERT INTO attendance(session_id,student_id,status,paid,amount,created_at) "
        "VALUES(?,?,?,?,?,?)", (sid, st["id"], "present", 0, 0, db.now()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "name": st["name"], "already": False,
                    "msg": "تم تسجيل الحضور ✅"})


# ---------------------------------------------------------------------------
# رسائل واتساب
# ---------------------------------------------------------------------------
def deliver(phone, message):
    """يرسل عبر API لو مفعّل، أو يرجّع رابط. يرجّع dict"""
    if wa.api_mode():
        ok, resp = wa.send_api(phone, message)
        return {"api": True, "ok": ok, "resp": resp,
                "link": wa.wa_link(phone, message)}
    return {"api": False, "link": wa.wa_link(phone, message)}


@app.route("/sessions/<int:sid>/whatsapp")
@login_required
def session_whatsapp(sid):
    conn = db.get_db()
    se = conn.execute(
        "SELECT se.*, g.name group_name FROM sessions se "
        "LEFT JOIN groups g ON se.group_id=g.id WHERE se.id=?", (sid,)).fetchone()
    rows = conn.execute(
        "SELECT a.*, s.name, s.parent_phone FROM attendance a "
        "JOIN students s ON a.student_id=s.id WHERE a.session_id=?", (sid,)).fetchall()
    conn.close()
    tname = teacher_name()
    subj = db.get_setting("subject", "المادة")
    messages = []
    for r in rows:
        # رسالة تعليمية فقط لولي الأمر (بدون أي معلومات عن الدفع - تظل للمدرس فقط)
        status_txt = STATUS_AR.get(r["status"], r["status"])
        lines = [f"السلام عليكم، ولي أمر الطالب/ة *{r['name']}*",
                 f"تقرير حصة مادة {subj} بتاريخ {se['date']}:",
                 f"- الحالة: {status_txt}"]
        if r["homework"] and r["homework"] != "none":
            lines.append(f"- الواجب: {HW_AR.get(r['homework'], '-')}")
        # مدى تركيز الطالب (لو مسجّل) — يظهر لولي الأمر
        _focus = r["focus_level"] if ("focus_level" in r.keys()) else None
        if _focus is not None:
            lines.append(f"- مدى التركيز: {_focus}%")
        if se["title"]:
            lines.append(f"- موضوع الحصة: {se['title']}")
        lines.append(f"\nمع تحيات {tname}")
        msg = "\n".join(lines)
        messages.append({"name": r["name"], "phone": r["parent_phone"],
                         "status": status_txt, "link": wa.wa_link(r["parent_phone"], msg),
                         "msg": msg})
    return render_template("whatsapp.html", messages=messages,
                           title=f"رسائل حصة {se['date']}",
                           back=url_for("session_detail", sid=sid))


@app.route("/whatsapp/level")
@login_required
def whatsapp_level():
    """صفحة اختيار مستوى كل طالب قبل الإرسال (المدرس يختار المستوى)"""
    conn = db.get_db()
    yid = active_year_id()
    gid = request.args.get("group", "")
    # الطلاب المسجّلون النشطون في العام الدراسي الحالي فقط (عبر enrollments)،
    # بمجموعتهم في هذا العام — لا نعرض مجموعات/طلاب أعوام سابقة أو محذوفة.
    sql = ("SELECT s.*, g.name group_name FROM enrollments e "
           "JOIN students s ON e.student_id=s.id "
           "LEFT JOIN groups g ON e.group_id=g.id "
           "WHERE e.year_id=? AND (e.status IS NULL OR e.status<>'inactive')")
    params = [yid]
    if gid:
        sql += " AND e.group_id=?"
        params.append(gid)
    sql += " ORDER BY s.name"
    studs = conn.execute(sql, params).fetchall()
    rows = []
    for s in studs:
        avg_pct, att_pct, suggested = compute_level(conn, s["id"])
        rows.append({"id": s["id"], "name": s["name"],
                     "group_name": s["group_name"] or "-",
                     "phone": s["parent_phone"],
                     "avg": avg_pct, "att": att_pct, "suggested": suggested})
    # مجموعات العام الدراسي الحالي فقط في القائمة المنسدلة
    grps = conn.execute("SELECT * FROM groups WHERE year_id=? ORDER BY name",
                        (yid,)).fetchall()
    conn.close()
    return render_template("level_select.html", students=rows, groups=grps,
                           sel_group=gid, levels=LEVELS)


@app.route("/whatsapp/level/send", methods=["POST"])
@login_required
def whatsapp_level_send():
    """توليد رسائل المستوى بناءً على المستوى الذي اختاره المدرس لكل طالب"""
    conn = db.get_db()
    ids = request.form.getlist("student_id")
    messages = []
    for sid in ids:
        chosen = request.form.get(f"level_{sid}", "").strip()
        if not chosen:
            continue
        s = conn.execute(
            "SELECT s.*, g.name group_name FROM students s "
            "LEFT JOIN groups g ON s.group_id=g.id WHERE s.id=?", (sid,)).fetchone()
        if not s:
            continue
        avg_pct, att_pct, _ = compute_level(conn, s["id"])
        msg = wa.render_template("level", student=s["name"],
                                 avg=avg_pct if avg_pct is not None else "—",
                                 att=att_pct if att_pct is not None else "—",
                                 level=chosen)
        messages.append({"name": s["name"], "phone": s["parent_phone"],
                         "status": chosen, "link": wa.wa_link(s["parent_phone"], msg),
                         "msg": msg})
    conn.close()
    return render_template("whatsapp.html", messages=messages,
                           title="رسائل مستوى الطلاب", back=url_for("whatsapp_level"),
                           level_page=True)


@app.route("/whatsapp/send_api", methods=["POST"])
@login_required
def whatsapp_send_api():
    """إرسال رسالة واحدة عبر API (يُستدعى من صفحة الواتساب لما API مفعّل)"""
    data = request.get_json()
    ok, resp = wa.send_api(data["phone"], data["message"],
                           msg_type=data.get("msg_type", "general"))
    return jsonify({"ok": ok, "resp": resp})


# ---------------------------------------------------------------------------
# تذكيرات المتأخرات (تُرسل لرقم المدرس بعد أسبوع)
# ---------------------------------------------------------------------------
def _reminder_message(items):
    """يبني رسالة تذكير للمدرس بكل المتأخرات"""
    tname = teacher_name()
    lines = [f"🔔 تذكير المتأخرات - {tname}",
             "الطلاب الذين لم يكملوا سداد الحصة:", ""]
    total = 0
    for it in items:
        total += it["remaining"]
        lines.append(f"• {it['name']} ({it['group_name'] or 'بدون مجموعة'}) — "
                     f"متبقٍّ: {it['remaining']:g} جنيه")
    lines.append("")
    lines.append(f"الإجمالي المتبقّي: {total:g} جنيه")
    return "\n".join(lines)


def _single_reminder_message(r):
    """رسالة تذكير لطالب واحد"""
    tname = teacher_name()
    return (f"🔔 تذكير سداد - {tname}\n"
            f"الطالب/ة: {r['name']} ({r['group_name'] or 'بدون مجموعة'})\n"
            f"المبلغ المتبقّي: {r['remaining']:g} جنيه")


def _now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _is_due(r):
    """هل حان موعد التذكير (التاريخ + الوقت)؟"""
    due_dt = f"{r['due_date']} {r['due_time'] or '09:00'}"
    return due_dt <= _now_stamp()


def _sync_reminders(conn, year_id=None):
    """يعيد مزامنة تذكيرات الدفع (reminders) مع الواقع المالي الفعلي في جدول
    attendance، ويصحّح البيانات القديمة الخاطئة تلقائيًا دون فقد أي مدفوعات:

    السبب الجذري للمديونية الخاطئة: التذكير كان يُخزَّن كـ«لقطة» ثابتة للمتبقّي
    وقت الحفظ (remaining ثابت). فإذا:
      - سُجِّل طالب حاضرًا افتراضيًا ثم صُحِّح إلى غائب،
      - أو عُدِّل سعر المجموعة/التخفيض لاحقًا (50 ← 37.5)،
    يظل التذكير القديم بقيمته الخاطئة (دَين وهمي).

    الحل: نحسب المتبقّي ديناميكيًا من الحضور:
        المتبقّي = السعر الفعلي المستحق (fee_charged، وإلا سعر الحصة) − المدفوع
    ونطبّق التصحيحات التالية (كلها آمنة ولا تمسّ amount المدفوع فعليًا):
      1) تذكير لطالب حالته ليست present/late (غائب/غير مسجَّل) أو معفى → يُحذف.
      2) تذكير بلا سجل حضور مطابق → يُحذف.
      3) المدفوع ≥ السعر الفعلي (لا متبقّي) → يُحذف التذكير المعلّق.
      4) خلاف ذلك: يُحدَّث remaining إلى القيمة الصحيحة الحالية.
    نقتصر على التذكيرات المعلّقة (pending) لعام الحصة المطلوب (أو كل الأعوام لو None).
    """
    if year_id is None:
        year_id = active_year_id()
    try:
        rows = conn.execute(
            "SELECT r.id, r.student_id, r.session_id, r.remaining, "
            "se.year_id AS syear, COALESCE(se.fee,0) AS group_fee, "
            "a.status AS att_status, a.fee_exempt, "
            "COALESCE(a.fee_charged, se.fee, 0) AS fee_snapshot, "
            "COALESCE(a.amount,0) AS amount "
            "FROM reminders r "
            "JOIN sessions se ON r.session_id=se.id "
            "LEFT JOIN attendance a ON a.session_id=r.session_id "
            "AND a.student_id=r.student_id "
            "WHERE r.status='pending' AND se.year_id=?", (year_id,)).fetchall()
    except Exception:
        conn.rollback()
        return 0
    changed = 0
    for r in rows:
        att_status = r["att_status"]
        exempt = r["fee_exempt"] if ("fee_exempt" in r.keys()) else 0
        # (1)+(2): لا سجل حضور، أو ليس حاضرًا/متأخرًا، أو معفى → لا دَين حقيقي
        if att_status is None or att_status not in ("present", "late") or exempt:
            conn.execute("DELETE FROM reminders WHERE id=?", (r["id"],))
            changed += 1
            continue
        # السعر الفعلي المستحق حاليًا = تخفيض الطالب لهذا العام إن وُجد، وإلا سعر
        # المجموعة الحالي. نستخدمه (لا اللقطة القديمة fee_snapshot) حتى ينعكس تصحيح
        # سعر المجموعة (مثلًا 50 ← 37.5) على المتأخرات القديمة تلقائيًا.
        eff = _effective_fee(conn, r["student_id"], r["syear"], r["group_fee"])
        real_remaining = round((eff or 0) - (r["amount"] or 0), 2)
        if real_remaining <= 0:
            # (3): سُدِّد بالكامل حسب السعر الحالي → أزل التذكير
            conn.execute("DELETE FROM reminders WHERE id=?", (r["id"],))
            changed += 1
        elif abs(real_remaining - (r["remaining"] or 0)) > 0.001:
            # (4): صحّح قيمة المتبقّي لتطابق السعر الفعلي الحالي
            conn.execute("UPDATE reminders SET remaining=? WHERE id=?",
                         (real_remaining, r["id"]))
            changed += 1
    if changed:
        conn.commit()
    return changed


def _fetch_reminders(conn, status="pending", active_only=False, year_id=None):
    # للتذكيرات المعلّقة (التي ستُرسل) نستبعد الطلاب غير الفعّالين
    extra = " AND (s.status IS NULL OR s.status<>'inactive')" if active_only else ""
    # نقصر التذكيرات على العام النشط (عبر عام الحصة) حتى لا تظهر متأخرات عام سابق.
    if year_id is None:
        year_id = active_year_id()
    return conn.execute(
        "SELECT r.*, s.name, s.parent_phone, g.name group_name "
        "FROM reminders r JOIN students s ON r.student_id=s.id "
        "JOIN sessions se ON r.session_id=se.id "
        "LEFT JOIN groups g ON s.group_id=g.id "
        f"WHERE r.status=? AND se.year_id=?{extra} "
        "ORDER BY r.due_date, r.due_time", (status, year_id)).fetchall()


def _send_email(subject_line, body, to_email=None):
    """يرسل رسالة بريد عامة إلى عنوان محدّد (أو إيميل التقارير المسجّل افتراضيًا).
    يرجّع (نجاح, رسالة)."""
    host = db.get_setting("smtp_host")
    port = int(db.get_setting("smtp_port") or 587)
    user = db.get_setting("smtp_user")
    pw = db.get_setting("smtp_pass")
    to_email = (to_email or db.get_setting("report_email") or "").strip()
    if not (user and pw and to_email):
        return False, "إعدادات الإيميل (SMTP) أو الإيميل المستلم غير مضبوطة"
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject_line
        msg["From"] = user
        msg["To"] = to_email
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, pw)
            server.send_message(msg)
        return True, "تم الإرسال بالإيميل"
    except Exception as e:
        return False, f"فشل الإيميل: {e}"


def _send_reminder_email(subject_line, body):
    """يرسل تذكير بالإيميل إلى إيميل التقارير المسجّل. يرجّع (نجاح, رسالة)"""
    return _send_email(subject_line, body)


@app.route("/reminders")
@login_required
def reminders():
    conn = db.get_db()
    _sync_reminders(conn)  # صحّح أي متأخرات قديمة خاطئة قبل العرض
    pending = _fetch_reminders(conn, "pending", active_only=True)
    done = _fetch_reminders(conn, "done")[:20]
    conn.close()
    due = [r for r in pending if _is_due(r)]
    upcoming = [r for r in pending if not _is_due(r)]
    teacher_phone = db.get_setting("teacher_phone", "")
    due_total = sum(r["remaining"] for r in due)
    wa_link = None
    if due and teacher_phone:
        wa_link = wa.wa_link(teacher_phone, _reminder_message(due))
    absence_cfg = {
        "enabled": db.get_setting("absence_alert_enabled", "0") == "1",
        "threshold": db.get_setting("absence_alert_threshold", "3"),
        "site": db.get_setting("absence_alert_notify_site", "1") == "1",
        "wa": db.get_setting("absence_alert_notify_wa", "1") == "1",
        "email": db.get_setting("absence_alert_notify_email", "0") == "1",
    }
    return render_template("reminders.html", due=due, upcoming=upcoming, done=done,
                           teacher_phone=teacher_phone, due_total=due_total,
                           wa_link=wa_link, today=datetime.now().strftime("%Y-%m-%d"),
                           now_time=datetime.now().strftime("%H:%M"), wa_api_on=wa.api_mode(),
                           absence_cfg=absence_cfg)


@app.route("/reminders/absence-config", methods=["POST"])
@login_required
def absence_config_save():
    """حفظ إعدادات تنبيه تكرار الغياب (مفعّل/الحد/طرق التنبيه)."""
    db.set_setting("absence_alert_enabled", "1" if request.form.get("enabled") else "0")
    try:
        thr = int(request.form.get("threshold", "3"))
    except (ValueError, TypeError):
        thr = 3
    thr = max(1, min(50, thr))
    db.set_setting("absence_alert_threshold", str(thr))
    db.set_setting("absence_alert_notify_site", "1" if request.form.get("notify_site") else "0")
    db.set_setting("absence_alert_notify_wa", "1" if request.form.get("notify_wa") else "0")
    db.set_setting("absence_alert_notify_email", "1" if request.form.get("notify_email") else "0")
    flash("تم حفظ إعدادات تنبيه الغياب ✅", "success")
    return redirect(url_for("reminders"))


@app.route("/reminders/<int:rid>/schedule", methods=["POST"])
@login_required
def reminder_schedule(rid):
    """تحديث موعد التذكير (تاريخ + وقت + وسيلة الإرسال)"""
    conn = db.get_db()
    conn.execute("UPDATE reminders SET due_date=?, due_time=?, method=? WHERE id=?",
                 (request.form.get("due_date"), request.form.get("due_time") or "09:00",
                  request.form.get("method") or "whatsapp", rid))
    conn.commit()
    conn.close()
    flash("تم تحديث موعد التذكير", "success")
    return redirect(url_for("reminders"))


@app.route("/reminders/<int:rid>/send")
@login_required
def reminder_send_one(rid):
    """إرسال تذكير طالب واحد الآن حسب الوسيلة المختارة"""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT r.*, s.name, s.parent_phone, g.name group_name "
        "FROM reminders r JOIN students s ON r.student_id=s.id "
        "LEFT JOIN groups g ON s.group_id=g.id WHERE r.id=?", (rid,)).fetchone()
    if not rows:
        conn.close()
        return "غير موجود", 404
    method = rows["method"] or "whatsapp"
    msg = _single_reminder_message(rows)
    if method == "email":
        ok, resp = _send_reminder_email(f"تذكير سداد - {rows['name']}", msg)
        if ok:
            conn.execute("UPDATE reminders SET status='done', sent_at=? WHERE id=?",
                         (db.now(), rid))
            conn.commit()
            flash(f"تم إرسال التذكير بالإيميل ({rows['name']}) ✅", "success")
        else:
            flash(resp, "error")
        conn.close()
        return redirect(url_for("reminders"))
    # واتساب
    teacher_phone = db.get_setting("teacher_phone", "")
    if not teacher_phone:
        conn.close()
        flash("من فضلك اضبط رقم واتساب المدرس من الإعدادات أولاً", "error")
        return redirect(url_for("reminders"))
    if wa.api_mode():
        ok, resp = wa.send_api(teacher_phone, msg, msg_type="reminder")
        if ok:
            conn.execute("UPDATE reminders SET status='done', sent_at=? WHERE id=?",
                         (db.now(), rid))
            conn.commit()
            flash(f"تم إرسال التذكير على الواتساب ({rows['name']}) ✅", "success")
        else:
            flash(f"فشل الإرسال عبر API: {resp}", "error")
        conn.close()
        return redirect(url_for("reminders"))
    conn.close()
    return redirect(wa.wa_link(teacher_phone, msg))


@app.route("/reminders/send", methods=["POST"])
@login_required
def reminders_send():
    """يرسل كل التذكيرات المستحقة الآن (واتساب مجمّعة / إيميل حسب كل تذكير)"""
    conn = db.get_db()
    pending = _fetch_reminders(conn, "pending")
    due = [r for r in pending if _is_due(r)]
    if not due:
        conn.close()
        flash("لا توجد تذكيرات مستحقة حاليًا", "success")
        return redirect(url_for("reminders"))
    teacher_phone = db.get_setting("teacher_phone", "")
    wa_due = [r for r in due if (r["method"] or "whatsapp") == "whatsapp"]
    email_due = [r for r in due if r["method"] == "email"]
    sent = 0
    # إيميل: كل واحد على حدة
    for r in email_due:
        ok, _ = _send_reminder_email(f"تذكير سداد - {r['name']}", _single_reminder_message(r))
        if ok:
            conn.execute("UPDATE reminders SET status='done', sent_at=? WHERE id=?",
                         (db.now(), r["id"]))
            sent += 1
    # واتساب: مجمّعة عبر API لو مفعّل
    if wa_due and teacher_phone and wa.api_mode():
        ok, resp = wa.send_api(teacher_phone, _reminder_message(wa_due), msg_type="reminder")
        if ok:
            for r in wa_due:
                conn.execute("UPDATE reminders SET status='done', sent_at=? WHERE id=?",
                             (db.now(), r["id"]))
            sent += len(wa_due)
        else:
            flash(f"فشل إرسال واتساب عبر API: {resp}", "error")
    conn.commit()
    conn.close()
    if wa_due and teacher_phone and not wa.api_mode():
        # وضع الروابط: افتح رابط واتساب المجمّع
        flash(f"تم إرسال {sent} تذكير بالإيميل. سيُفتح واتساب لتذكيرات الواتساب.", "success")
        return redirect(wa.wa_link(teacher_phone, _reminder_message(wa_due)))
    if sent:
        flash(f"تم إرسال {sent} تذكير مستحق ✅", "success")
    else:
        flash("تعذّر الإرسال. راجع الإعدادات.", "error")
    return redirect(url_for("reminders"))


@app.route("/reminders/<int:rid>/collect")
@login_required
def reminder_collect(rid):
    """
    تسجيل تحصيل المبلغ المتبقّي: يُضاف المبلغ إلى سجل الحصة (المالي)،
    ويُعلَّم التذكير كمنتهٍ، فيظهر الدفع كاملاً في التقارير المالية.
    """
    conn = db.get_db()
    rem = conn.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
    if not rem:
        conn.close()
        return "غير موجود", 404
    remaining = rem["remaining"] or 0
    # حدّث سجل الحضور/الدفع للحصة المرتبطة بإضافة المتبقّي
    if rem["session_id"]:
        att = conn.execute(
            "SELECT * FROM attendance WHERE session_id=? AND student_id=?",
            (rem["session_id"], rem["student_id"])).fetchone()
        if att:
            new_amount = (att["amount"] or 0) + remaining
            conn.execute(
                "UPDATE attendance SET paid=1, amount=? WHERE id=?",
                (new_amount, att["id"]))
        else:
            # لا يوجد سجل حضور (حالة نادرة) — أنشئ واحدًا كمدفوع
            conn.execute(
                "INSERT INTO attendance(session_id,student_id,status,paid,amount,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (rem["session_id"], rem["student_id"], "present", 1, remaining, db.now()))
    conn.execute("UPDATE reminders SET status='done', sent_at=? WHERE id=?",
                 (db.now(), rid))
    conn.commit()
    conn.close()
    flash(f"تم تسجيل تحصيل المبلغ المتبقّي ({remaining:g} ج) وإضافته للتقارير المالية ✅", "success")
    return redirect(url_for("reminders"))


@app.route("/reminders/<int:rid>/done")
@login_required
def reminder_done(rid):
    """تجاهل/إنهاء التذكير بدون تسجيل دفع (مثلاً بعد إرساله)."""
    conn = db.get_db()
    conn.execute("UPDATE reminders SET status='done', sent_at=? WHERE id=?",
                 (db.now(), rid))
    conn.commit()
    conn.close()
    flash("تم تعليم التذكير كمنتهي", "success")
    return redirect(url_for("reminders"))


# ---------------------------------------------------------------------------
# القوالب الجاهزة (قابلة للتعديل)
# ---------------------------------------------------------------------------
@app.route("/templates-editor", methods=["GET", "POST"])
@login_required
def templates_editor():
    conn = db.get_db()
    if request.method == "POST":
        for key in request.form:
            if key.startswith("body_"):
                k = key[5:]
                conn.execute("UPDATE templates SET body=? WHERE key=?",
                             (request.form[key], k))
        conn.commit()
        flash("تم حفظ القوالب", "success")
    tpls = conn.execute("SELECT * FROM templates ORDER BY id").fetchall()
    conn.close()
    vars_hint = ("المتغيرات المتاحة: {student} اسم الطالب · {teacher} المدرس · "
                 "{subject} المادة · {date} التاريخ · {status} الحالة · "
                 "{homework} الواجب · {amount} المبلغ · {remaining} المتبقي · "
                 "{period} الفترة · {exam} الامتحان · {score} الدرجة · {total} الكلية · "
                 "{pct} النسبة · {avg} المتوسط · {level} التقييم · {att} الحضور · "
                 "{paid_total} إجمالي المدفوع · {present_count}/{late_count}/{absent_count} عدد أيام الحضور/التأخير/الغياب · "
                 "{absence_count} عدد الغيابات · {code} كود الطالب · {password} كلمة المرور · "
                 "{username} اسم المستخدم · {qr_url} رابط QR · {portal_url} رابط البوابة")
    return render_template("templates_editor.html", templates=tpls, vars_hint=vars_hint)


# ---------------------------------------------------------------------------
# مولّد الامتحانات بالذكاء الاصطناعي
# ---------------------------------------------------------------------------
QTYPES = list(QTYPE_LABELS.keys())


# ---------------------------------------------------------------------------
# ملاحظة: أُزيل توليد الامتحانات بالذكاء الاصطناعي. الأسئلة تُنشأ يدويًا
# أو تُستورد من Word أو من بنك الأسئلة (routes في exam_manual.py أدناه).

# ---------------------------------------------------------------------------
# الامتحانات (إلكتروني + ورقي)
# ---------------------------------------------------------------------------
@app.route("/exams")
@login_required
def exams():
    conn = db.get_db()
    yid = active_year_id()
    rows = conn.execute(
        "SELECT e.*, g.name group_name, "
        "(SELECT COUNT(*) FROM questions q WHERE q.exam_id=e.id) nq, "
        "(SELECT COUNT(*) FROM results r WHERE r.exam_id=e.id) nr "
        "FROM exams e LEFT JOIN groups g ON e.group_id=g.id "
        "WHERE e.year_id=? ORDER BY e.id DESC", (yid,)).fetchall()
    grps = conn.execute("SELECT * FROM groups WHERE year_id=? ORDER BY name", (yid,)).fetchall()
    conn.close()
    online = [e for e in rows if e["is_online"]]
    paper = [e for e in rows if not e["is_online"]]
    return render_template("exams.html", online=online, paper=paper,
                           groups=grps, site=site_url())


@app.route("/exams/add", methods=["POST"])
@login_required
def add_exam():
    if _readonly_year_guard():
        return redirect(url_for("exams"))
    is_online = 1 if request.form.get("type", "online") == "online" else 0
    conn = db.get_db()
    # الامتحان الجديد يُنشأ «منشورًا» ليعمل رابطه فورًا (نفس السلوك السابق).
    # يمكن للمدرس تحويله لمسودة/إيقافه لاحقًا من إعدادات النشر.
    cur = conn.execute(
        "INSERT INTO exams(title,group_id,year_id,duration,is_online,total_marks,status,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (request.form["title"], request.form.get("group_id") or None, active_year_id(),
         int(request.form.get("duration") or 30), is_online,
         float(request.form.get("total_marks") or 0) if not is_online else 0,
         "published", db.now()))
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    if is_online:
        return redirect(url_for("exam_edit", eid=eid))
    return redirect(url_for("paper_grades", eid=eid))


@app.route("/exams/<int:eid>/edit")
@login_required
def exam_edit(eid):
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return "الامتحان غير موجود", 404
    qs = conn.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY position, id",
                      (eid,)).fetchall()
    # المجموعات والترمات لقوائم بيانات الامتحان (ضمن العام النشط)
    yid = active_year_id()
    groups = conn.execute(
        "SELECT id, name FROM groups WHERE year_id=? ORDER BY name", (yid,)).fetchall()
    terms = []
    try:
        terms = conn.execute(
            "SELECT id, name FROM terms WHERE year_id=? ORDER BY id", (yid,)).fetchall()
    except Exception:
        terms = []
    year_row = conn.execute("SELECT id, name FROM academic_years WHERE id=?", (yid,)).fetchone()
    conn.close()
    return render_template("exam_edit.html", ex=ex, questions=qs, site=site_url(),
                           groups=groups, terms=terms, year_row=year_row)


@app.route("/exams/<int:eid>/settings", methods=["POST"])
@login_required
def exam_settings(eid):
    """حفظ كل إعدادات الامتحان المجمّعة (بيانات/أسئلة/محاولات/تصحيح/طالب/نشر/نتيجة).

    الحفظ آمن على الأعمدة الموجودة فقط، ويحافظ على القيم القديمة (متوافق مع البيانات
    المحفوظة سابقًا). كل إعداد يُطبَّق فعليًا في تجربة الامتحان (راجع take_exam).
    """
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return "الامتحان غير موجود", 404

    def _int(name, default):
        try:
            return int(float(request.form.get(name, default)))
        except (ValueError, TypeError):
            return default

    def _chk(name):
        return 1 if request.form.get(name) else 0

    # --- بيانات الامتحان ---
    title = (request.form.get("title") or ex["title"] or "").strip() or ex["title"]
    subject = (request.form.get("subject") or "").strip()
    grade = (request.form.get("grade") or "").strip()
    group_id = request.form.get("group_id") or None
    term_id = request.form.get("term_id") or None
    duration = _int("duration", ex["duration"] or 30)
    exam_date = (request.form.get("exam_date") or "").strip()

    # --- إعدادات الأسئلة ---
    shuffle_questions = _chk("shuffle_questions")
    shuffle_choices = _chk("shuffle_choices")
    num_questions = _int("num_questions", 0)
    if num_questions < 0:
        num_questions = 0
    show_question_number = _chk("show_question_number")

    # --- محاولات الامتحان ---
    allow_retake = _chk("allow_retake")
    max_attempts = _int("max_attempts", 1)
    if max_attempts < 0:
        max_attempts = 0  # 0 = غير محدود
    if not allow_retake:
        max_attempts = 1
    final_policy = request.form.get("final_policy", "highest")
    if final_policy not in ("highest", "latest", "manual"):
        final_policy = "highest"

    # --- إعدادات التصحيح / النتيجة للطالب ---
    auto_grade = _chk("auto_grade")
    show_result_to_student = _chk("show_result_to_student")
    show_answers_to_student = _chk("show_answers_to_student")

    # --- إعدادات الطالب أثناء الأداء ---
    one_question_per_page = _chk("one_question_per_page")
    prevent_back = _chk("prevent_back")

    # --- إعدادات النشر ---
    status = request.form.get("status", "draft")
    if status not in ("draft", "published", "closed"):
        status = "draft"
    open_at = (request.form.get("open_at") or "").strip()
    close_at = (request.form.get("close_at") or "").strip()

    # --- إعدادات النتيجة ---
    show_score = _chk("show_score")
    show_percentage = _chk("show_percentage")
    show_grade_label = _chk("show_grade_label")
    send_result_to_parent = _chk("send_result_to_parent")

    conn.execute(
        "UPDATE exams SET title=?, subject=?, grade=?, group_id=?, term_id=?, duration=?, "
        "exam_date=?, shuffle_questions=?, shuffle_choices=?, num_questions=?, "
        "show_question_number=?, allow_retake=?, max_attempts=?, final_policy=?, "
        "auto_grade=?, show_result_to_student=?, show_answers_to_student=?, "
        "one_question_per_page=?, prevent_back=?, status=?, open_at=?, close_at=?, "
        "show_score=?, show_percentage=?, show_grade_label=?, send_result_to_parent=? "
        "WHERE id=?",
        (title, subject, grade, group_id, term_id, duration, exam_date,
         shuffle_questions, shuffle_choices, num_questions, show_question_number,
         allow_retake, max_attempts, final_policy, auto_grade, show_result_to_student,
         show_answers_to_student, one_question_per_page, prevent_back, status,
         open_at, close_at, show_score, show_percentage, show_grade_label,
         send_result_to_parent, eid))
    conn.commit()
    conn.close()
    flash("تم حفظ إعدادات الامتحان ✅", "success")
    return redirect(url_for("exam_edit", eid=eid))


@app.route("/exams/<int:eid>/question/add", methods=["POST"])
@login_required
def add_question(eid):
    qtype = request.form.get("qtype", "mcq").strip()
    if qtype not in QTYPES:
        qtype = "mcq"
    text = request.form.get("text", "").strip()
    marks = float(request.form.get("marks") or 1)
    conn = db.get_db()
    if qtype == "mcq":
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,option_a,option_b,option_c,option_d,correct,marks) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (eid, text, "mcq", request.form.get("option_a", ""), request.form.get("option_b", ""),
             request.form.get("option_c", ""), request.form.get("option_d", ""),
             request.form.get("correct", "a"), marks))
    elif qtype == "truefalse":
        # الإجابة الصحيحة: 'a' = صح ، 'b' = خطأ
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,option_a,option_b,correct,marks) "
            "VALUES(?,?,?,?,?,?,?)",
            (eid, text, "truefalse", "صح", "خطأ",
             request.form.get("correct", "a"), marks))
    elif qtype == "complete":
        # تصحيح تلقائي بمقارنة النص بالإجابة النموذجية
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,answer_text,marks) VALUES(?,?,?,?,?)",
            (eid, text, "complete", request.form.get("answer_text", "").strip(), marks))
    elif qtype in ("map", "map_complete"):
        # سؤال خريطة: صورة (base64) + عناصر مرقّمة (رقم/إجابة/درجة)
        try:
            img_data = _read_image_field("map_image")  # base64 data URI أو ""
        except ValueError as e:
            conn.close()
            flash(str(e), "error")
            return redirect(url_for("exam_edit", eid=eid))
        nums = request.form.getlist("map_num")
        ans = request.form.getlist("map_answer")
        mks = request.form.getlist("map_marks")
        items = []
        total_item_marks = 0.0
        for i in range(len(nums)):
            num = (nums[i] or "").strip()
            if not num:
                continue
            im = 0.0
            try:
                im = float(mks[i]) if i < len(mks) and mks[i] else 1.0
            except ValueError:
                im = 1.0
            total_item_marks += im
            items.append({"num": num,
                          "answer": (ans[i] if i < len(ans) else "").strip(),
                          "marks": im})
        extra = json.dumps({"image": img_data, "items": items}, ensure_ascii=False)
        # درجة السؤال = مجموع درجات الأرقام (أو المُدخلة)
        q_marks = total_item_marks if total_item_marks > 0 else marks
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,extra,marks) VALUES(?,?,?,?,?)",
            (eid, text, qtype, extra, q_marks))
    else:
        # أنواع مقالية (علّل / النتائج / الربط والتحليل / قصير): تصحيح يدوي
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,answer_text,marks) VALUES(?,?,?,?,?)",
            (eid, text, qtype, request.form.get("answer_text", "").strip(), marks))
    total = conn.execute("SELECT COALESCE(SUM(marks),0) t FROM questions WHERE exam_id=?",
                         (eid,)).fetchone()["t"]
    conn.execute("UPDATE exams SET total_marks=? WHERE id=?", (total, eid))
    conn.commit()
    conn.close()
    flash("تمت إضافة السؤال ✅", "success")
    return redirect(url_for("exam_edit", eid=eid))


@app.route("/exams/<int:eid>/question/<int:qid>/delete", methods=["GET", "POST"])
@login_required
def delete_question(eid, qid):
    conn = db.get_db()
    conn.execute("DELETE FROM questions WHERE id=?", (qid,))
    total = conn.execute("SELECT COALESCE(SUM(marks),0) t FROM questions WHERE exam_id=?",
                         (eid,)).fetchone()["t"]
    conn.execute("UPDATE exams SET total_marks=? WHERE id=?", (total, eid))
    conn.commit()
    conn.close()
    # طلب AJAX (fetch): لا نعيد تحميل الصفحة كاملة حتى لا تقفز للأعلى
    if request.headers.get("X-Requested-With") == "fetch" or request.method == "POST":
        return jsonify({"ok": True, "total": total})
    return redirect(url_for("exam_edit", eid=eid))


@app.route("/exams/<int:eid>/set-status", methods=["POST"])
@login_required
def exam_set_status(eid):
    """تغيير حالة النشر (مسودة/منشور/موقوف) عبر AJAX — للفصل بين المسودة والنشر."""
    data = request.get_json(silent=True) or request.form
    status = (data.get("status") or "").strip()
    if status not in ("draft", "published", "closed"):
        return jsonify({"ok": False, "error": "حالة غير صحيحة"}), 400
    conn = db.get_db()
    ex = conn.execute("SELECT id FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return jsonify({"ok": False, "error": "غير موجود"}), 404
    conn.execute("UPDATE exams SET status=? WHERE id=?", (status, eid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "status": status})


@app.route("/exams/<int:eid>/question/<int:qid>/data")
@login_required
def question_data(eid, qid):
    """يرجّع بيانات سؤال (JSON) لملء محرّر التعديل داخل الصفحة."""
    conn = db.get_db()
    row = conn.execute("SELECT * FROM questions WHERE id=? AND exam_id=?",
                       (qid, eid)).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "غير موجود"}), 404
    return jsonify({"ok": True, "question": dict(row)})


@app.route("/exams/<int:eid>/question/<int:qid>/edit", methods=["POST"])
@login_required
def edit_question(eid, qid):
    """تعديل سؤال داخل محرّر الامتحان (نسخة الامتحان مستقلة عن بنك الأسئلة).

    يرجّع JSON للتحديث الفوري بلا إعادة تحميل الصفحة (يحافظ على موضع التمرير).
    """
    conn = db.get_db()
    row = conn.execute("SELECT * FROM questions WHERE id=? AND exam_id=?",
                       (qid, eid)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "السؤال غير موجود"}), 404
    data = request.get_json(silent=True) or request.form
    qtype = (data.get("qtype") or row["qtype"] or "mcq").strip()
    if qtype not in QTYPES:
        qtype = "mcq"
    text = (data.get("text") or "").strip()
    try:
        marks = float(data.get("marks") or row["marks"] or 1)
    except (ValueError, TypeError):
        marks = row["marks"] or 1
    fields = {"text": text, "qtype": qtype, "marks": marks,
              "option_a": "", "option_b": "", "option_c": "", "option_d": "",
              "correct": "", "answer_text": ""}
    if qtype == "mcq":
        fields["option_a"] = (data.get("option_a") or "").strip()
        fields["option_b"] = (data.get("option_b") or "").strip()
        fields["option_c"] = (data.get("option_c") or "").strip()
        fields["option_d"] = (data.get("option_d") or "").strip()
        fields["correct"] = (data.get("correct") or "a").strip()
    elif qtype == "truefalse":
        fields["option_a"] = "صح"
        fields["option_b"] = "خطأ"
        fields["correct"] = (data.get("correct") or "a").strip()
    elif qtype in ("map", "map_complete"):
        # لا نغيّر صورة الخريطة/عناصرها هنا (تبقى في extra كما هي)؛ نعدّل النص/الدرجة فقط
        pass
    else:
        fields["answer_text"] = (data.get("answer_text") or "").strip()
    conn.execute(
        "UPDATE questions SET text=?, qtype=?, marks=?, option_a=?, option_b=?, "
        "option_c=?, option_d=?, correct=?, answer_text=? WHERE id=?",
        (fields["text"], fields["qtype"], fields["marks"], fields["option_a"],
         fields["option_b"], fields["option_c"], fields["option_d"],
         fields["correct"], fields["answer_text"], qid))
    total = conn.execute("SELECT COALESCE(SUM(marks),0) t FROM questions WHERE exam_id=?",
                         (eid,)).fetchone()["t"]
    conn.execute("UPDATE exams SET total_marks=? WHERE id=?", (total, eid))
    conn.commit()
    updated = dict(conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone())
    conn.close()
    return jsonify({"ok": True, "question": updated, "total": total})


@app.route("/exams/<int:eid>/delete")
@login_required
def delete_exam(eid):
    conn = db.get_db()
    conn.execute("DELETE FROM exams WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    flash("تم حذف الامتحان", "success")
    return redirect(url_for("exams"))


# ---------------------------------------------------------------------------
# إدراج سؤال موحّد (يُستخدم من الإضافة اليدوية + استيراد Word + بنك الأسئلة)
# ---------------------------------------------------------------------------
def _insert_question(conn, eid, q, position=0):
    """يُدرج سؤالًا (dict) في جدول questions لامتحان معيّن. لا يعدّل نصّ السؤال."""
    qtype = q.get("type") or q.get("qtype") or "mcq"
    if qtype not in QTYPES:
        qtype = "mcq"
    text = (q.get("text") or "").strip()
    marks = float(q.get("marks") or 1)
    if qtype == "mcq":
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,option_a,option_b,option_c,"
            "option_d,correct,marks,position) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (eid, text, "mcq", q.get("option_a", ""), q.get("option_b", ""),
             q.get("option_c", ""), q.get("option_d", ""),
             q.get("correct", "a"), marks, position))
    elif qtype == "truefalse":
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,option_a,option_b,correct,marks,position) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (eid, text, "truefalse", "صح", "خطأ",
             q.get("correct", "a"), marks, position))
    elif qtype in ("map", "map_complete"):
        # أسئلة الخريطة: احمل بيانات الصورة/العناصر (extra JSON) كما هي
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,answer_text,extra,marks,position) "
            "VALUES(?,?,?,?,?,?,?)",
            (eid, text, qtype, (q.get("answer_text") or "").strip(),
             q.get("extra") or None, marks, position))
    else:
        conn.execute(
            "INSERT INTO questions(exam_id,text,qtype,answer_text,extra,marks,position) "
            "VALUES(?,?,?,?,?,?,?)",
            (eid, text, qtype, (q.get("answer_text") or "").strip(),
             q.get("extra") or None, marks, position))


def _recalc_total(conn, eid):
    total = conn.execute("SELECT COALESCE(SUM(marks),0) t FROM questions WHERE exam_id=?",
                         (eid,)).fetchone()["t"]
    conn.execute("UPDATE exams SET total_marks=? WHERE id=?", (total, eid))


# ---------------------------------------------------------------------------
# استيراد الأسئلة من Word (.docx) — بدون ذكاء اصطناعي
# ---------------------------------------------------------------------------
@app.route("/word-format")
@login_required
def word_format_help():
    """صفحة توضّح تنسيق Word المدعوم للاستيراد."""
    return render_template("word_format.html")


@app.route("/exams/<int:eid>/import-word", methods=["POST"])
@login_required
def exam_import_word(eid):
    """يرفع ملف Word، يحلّله، ويخزّن الأسئلة المكتشفة كمسودة للمراجعة."""
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    conn.close()
    if not ex:
        return "الامتحان غير موجود", 404
    f = request.files.get("docx")
    if not f or not f.filename:
        flash("من فضلك اختر ملف Word (.docx).", "error")
        return redirect(url_for("exam_edit", eid=eid))
    if not f.filename.lower().endswith(".docx"):
        flash("الصيغة المدعومة هي .docx فقط (احفظ الملف بصيغة Word حديثة).", "error")
        return redirect(url_for("exam_edit", eid=eid))
    try:
        questions = exam_import.parse_docx(f.read())
    except exam_import.ImportError_ as e:
        flash(str(e), "error")
        return redirect(url_for("exam_edit", eid=eid))
    except Exception as e:
        flash(f"تعذّرت قراءة ملف Word: {e}", "error")
        return redirect(url_for("exam_edit", eid=eid))
    if not questions:
        flash("لم يتم العثور على أسئلة في الملف. تأكّد من التنسيق (راجع النموذج).", "error")
        return redirect(url_for("exam_edit", eid=eid))
    for q in questions:
        _canonize_mcq_fields(q)
    set_draft(f"import_{eid}", {"questions": questions, "filename": f.filename})
    flash(f"تم العثور على {len(questions)} سؤالًا. راجعها وعدّلها ثم أضفها للامتحان.", "success")
    return redirect(url_for("exam_import_review", eid=eid))


@app.route("/exams/<int:eid>/import-review")
@login_required
def exam_import_review(eid):
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    conn.close()
    if not ex:
        return "الامتحان غير موجود", 404
    draft = get_draft(f"import_{eid}")
    if not draft:
        flash("لا توجد أسئلة مستوردة للمراجعة. ارفع ملف Word أولًا.", "error")
        return redirect(url_for("exam_edit", eid=eid))
    return render_template("import_review.html", ex=ex, draft=draft,
                           qtype_labels=QTYPE_LABELS)


@app.route("/exams/<int:eid>/import-commit", methods=["POST"])
@login_required
def exam_import_commit(eid):
    """يحفظ الأسئلة المُراجَعة (المعدّلة في الجدول) داخل الامتحان."""
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return "الامتحان غير موجود", 404
    try:
        payload = request.get_json(force=True)
    except Exception:
        conn.close()
        return jsonify({"ok": False, "error": "bad json"}), 400
    questions = payload.get("questions") or []
    # موضع البداية = بعد آخر سؤال حالي
    base = conn.execute("SELECT COALESCE(MAX(position),0) m FROM questions WHERE exam_id=?",
                        (eid,)).fetchone()["m"] or 0
    added = 0
    for i, q in enumerate(questions):
        if not (q.get("text") or "").strip():
            continue
        _insert_question(conn, eid, q, position=base + i + 1)
        added += 1
    _recalc_total(conn, eid)
    conn.commit()
    conn.close()
    clear_draft(f"import_{eid}")
    return jsonify({"ok": True, "added": added})


# ---------------------------------------------------------------------------
# بنك الأسئلة (حفظ وإعادة استخدام) — تصنيف موسّع + استيراد Word + إنشاء امتحان
# ---------------------------------------------------------------------------
def _qb_norm_text(s):
    """تطبيع نص السؤال لأغراض كشف التكرار (يزيل التشكيل/المسافات الزائدة/التنقيط)."""
    import re as _re
    s = (s or "").strip()
    s = _re.sub(r"[\u064B-\u0652\u0670]", "", s)        # التشكيل
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
    s = _re.sub(r"[\s\.\،\؟\?\!\:\-ـ]+", " ", s)        # مسافات وعلامات
    return s.strip().lower()


def _qb_hash(text, qtype, stage, grade, subject, term):
    """بصمة فريدة للسؤال داخل تصنيفه (لمنع التكرار داخل نفس المرحلة/الصف/المادة/الترم)."""
    import hashlib
    key = "|".join([_qb_norm_text(text), qtype or "", (stage or "").strip(),
                    (grade or "").strip(), (subject or "").strip(), (term or "").strip()])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _qb_find_duplicate(conn, h, exclude_id=None):
    """يرجّع صف السؤال المكرّر (نفس البصمة) إن وُجد، وإلا None."""
    if not h:
        return None
    sql = "SELECT * FROM question_bank WHERE dedup_hash=?"
    params = [h]
    if exclude_id:
        sql += " AND id<>?"
        params.append(exclude_id)
    return conn.execute(sql + " LIMIT 1", params).fetchone()


def _qb_insert(conn, q, year_id=None):
    """يُدرج سؤالًا في بنك الأسئلة مع بصمة منع التكرار. يرجّع (id, was_new).

    q: dict يحوي text/qtype/options/correct/answer_text/marks/stage/grade/subject/
       term/unit/lesson/difficulty/extra.
    """
    qtype = q.get("qtype") or q.get("type") or "mcq"
    if qtype not in QTYPES:
        qtype = "mcq"
    text = (q.get("text") or "").strip()
    # تقييس القيم إلى القوائم المعتمدة (لا نخزّن نصًّا حرًّا غير متسق)
    stage = qb_std_stage(q.get("stage"))
    grade = qb_std_grade(q.get("grade"), stage)
    subject = QB_SUBJECT   # المادة ثابتة دائمًا
    term = _qb_std_from_list(q.get("term"), TERM_LABELS)
    unit = qb_std_unit(q.get("unit"))
    lesson = qb_std_lesson(q.get("lesson"))
    difficulty = (q.get("difficulty") or "").strip()
    if difficulty not in DIFFICULTY_LABELS:
        difficulty = ""
    h = _qb_hash(text, qtype, stage, grade, subject, term)
    cur = conn.execute(
        "INSERT INTO question_bank(text,qtype,option_a,option_b,option_c,option_d,"
        "correct,answer_text,marks,grade,subject,unit,lesson,difficulty,stage,term,"
        "year_id,extra,dedup_hash,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (text, qtype, q.get("option_a", ""), q.get("option_b", ""),
         q.get("option_c", ""), q.get("option_d", ""),
         q.get("correct", "a"), (q.get("answer_text") or "").strip(),
         float(q.get("marks") or 1), grade, subject,
         unit, lesson, difficulty, stage, term,
         year_id, q.get("extra") or None, h, db.now()))
    return cur.lastrowid, True


@app.route("/question-bank")
@login_required
def question_bank():
    conn = db.get_db()
    filters = {k: request.args.get(k, "").strip() for k in
               ("stage", "grade", "subject", "term", "year_id", "unit", "lesson",
                "qtype", "difficulty", "q")}
    sql = "SELECT * FROM question_bank WHERE 1=1"
    params = []
    for col in ("stage", "grade", "subject", "term", "unit", "lesson", "qtype", "difficulty"):
        if filters[col]:
            sql += f" AND {col}=?"
            params.append(filters[col])
    if filters["year_id"]:
        sql += " AND year_id=?"
        params.append(filters["year_id"])
    if filters["q"]:
        sql += " AND text LIKE ?"
        params.append(f"%{filters['q']}%")
    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    # قيم مميّزة للفلاتر (facets) من البيانات الفعلية
    def distinct(col):
        return [r[col] for r in conn.execute(
            f"SELECT DISTINCT {col} FROM question_bank WHERE {col} IS NOT NULL AND {col}<>'' ORDER BY {col}"
        ).fetchall()]
    facets = {c: distinct(c) for c in ("stage", "grade", "subject", "term", "unit", "lesson")}
    # تجميع النتائج حسب «المرحلة + الترم» ثم الصف (المطلب الأساسي للعرض)
    grouped = {}
    for r in rows:
        stage = r["stage"] or "غير مصنّف"
        term = r["term"] or "غير محدد"
        gkey = f"{stage} — {term}"
        grouped.setdefault(gkey, {})
        grade = r["grade"] or "غير محدد"
        grouped[gkey].setdefault(grade, []).append(r)
    exams_list = conn.execute("SELECT id,title FROM exams WHERE is_online=1 ORDER BY id DESC").fetchall()
    years = conn.execute("SELECT id, name FROM academic_years ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("question_bank.html", questions=rows, filters=filters,
                           facets=facets, qtype_labels=QTYPE_LABELS, exams=exams_list,
                           grouped=grouped, stages=EDU_STAGES, terms=TERM_LABELS,
                           difficulty_labels=DIFFICULTY_LABELS, years=years,
                           active_year_id=active_year_id(),
                           units=QB_UNITS, lessons=QB_LESSONS, qb_subject=QB_SUBJECT,
                           grades_by_stage=QB_GRADES_BY_STAGE)


@app.route("/question-bank/add", methods=["POST"])
@login_required
def question_bank_add():
    """إضافة سؤال جديد لبنك الأسئلة يدويًا (مع تصنيف موسّع ومنع التكرار)."""
    qtype = request.form.get("qtype", "mcq").strip()
    if qtype not in QTYPES:
        qtype = "mcq"
    # تقييس القيم للقوائم المعتمدة (المادة ثابتة، الصف يراعي المرحلة)
    stage = qb_std_stage(request.form.get("stage", ""))
    grade = qb_std_grade(request.form.get("grade", ""), stage)
    q = {
        "text": request.form.get("text", "").strip(), "qtype": qtype,
        "option_a": request.form.get("option_a", ""), "option_b": request.form.get("option_b", ""),
        "option_c": request.form.get("option_c", ""), "option_d": request.form.get("option_d", ""),
        "correct": request.form.get("correct", "a"),
        "answer_text": request.form.get("answer_text", "").strip(),
        "marks": float(request.form.get("marks") or 1),
        "stage": stage,
        "grade": grade,
        "subject": QB_SUBJECT,
        "term": _qb_std_from_list(request.form.get("term", ""), TERM_LABELS),
        "unit": qb_std_unit(request.form.get("unit", "")),
        "lesson": qb_std_lesson(request.form.get("lesson", "")),
        "difficulty": request.form.get("difficulty", "").strip(),
    }
    yid = request.form.get("year_id") or active_year_id()
    conn = db.get_db()
    # منع التكرار: لو سؤال بنفس البصمة موجود بالفعل (بالقيم القياسية)
    h = _qb_hash(q["text"], qtype, q["stage"], q["grade"], q["subject"], q["term"])
    dup = _qb_find_duplicate(conn, h)
    on_dup = request.form.get("on_duplicate", "")   # skip / replace / new
    if dup and not on_dup:
        conn.close()
        flash("هذا السؤال موجود بالفعل في بنك الأسئلة. اختر: تخطٍّ أو استبدال أو حفظ كسؤال جديد.", "error")
        return redirect(url_for("question_bank"))
    if dup and on_dup == "skip":
        conn.close()
        flash("تم التخطّي (السؤال موجود بالفعل).", "success")
        return redirect(url_for("question_bank"))
    if dup and on_dup == "replace":
        conn.execute("DELETE FROM question_bank WHERE id=?", (dup["id"],))
    _qb_insert(conn, q, year_id=yid)
    conn.commit()
    conn.close()
    flash("تمت إضافة السؤال لبنك الأسئلة ✅", "success")
    return redirect(url_for("question_bank"))


def _canonize_mcq_fields(q):
    """يوحّد حقول سؤال الاختيار من متعدد ليكون option_a..d و correct صريحين.

    مصدر البيانات الوحيد: option_a..d. لو غابت واختيارات في options[] تُنسخ إليها.
    يضمن أن المعاينة (import review) وبنك الأسئلة والامتحان الإلكتروني يقرؤون نفس البنية.
    """
    qtype = q.get("type") or q.get("qtype") or "mcq"
    q["type"] = qtype
    q["qtype"] = qtype
    if qtype != "mcq":
        return q
    letters = ("a", "b", "c", "d")
    have = any((q.get("option_%s" % L) or "").strip() for L in letters)
    if not have:
        opts = q.get("options") or []
        for i, L in enumerate(letters):
            q["option_%s" % L] = (opts[i] if i < len(opts) else "") or ""
    else:
        # تأكّد من وجود المفاتيح الأربعة (فارغة إن نقصت) لعرض حقول قابلة للتحرير
        for L in letters:
            q.setdefault("option_%s" % L, q.get("option_%s" % L) or "")
    # زامِن options[] مع الحقول المنفصلة (لتطابق المصدرين)
    q["options"] = [q.get("option_%s" % L, "") for L in letters]
    if q.get("correct") not in letters:
        q["correct"] = "a"
    return q


@app.route("/question-bank/import", methods=["POST"])
@login_required
def question_bank_import():
    """يرفع ملف Word لبنك الأسئلة ويحلّله (بلا ذكاء اصطناعي) ويخزّنه كمسودة للمراجعة.

    forced_type: لو المدرس حدّد نوعًا موحّدًا لكل أسئلة الملف، نطبّقه على الجميع.
    التصنيف الجماعي (مرحلة/صف/مادة/ترم/وحدة/درس/صعوبة/درجة) يُحفظ للمراجعة.
    """
    f = request.files.get("docx")
    if not f or not f.filename:
        flash("من فضلك اختر ملف Word (.docx).", "error")
        return redirect(url_for("question_bank"))
    if not f.filename.lower().endswith(".docx"):
        flash("الصيغة المدعومة هي .docx فقط.", "error")
        return redirect(url_for("question_bank"))
    forced_type = request.form.get("forced_type", "").strip()
    try:
        questions = exam_import.parse_docx(f.read())
    except exam_import.ImportError_ as e:
        flash(str(e), "error")
        return redirect(url_for("question_bank"))
    except Exception as e:
        flash(f"تعذّرت قراءة ملف Word: {e}", "error")
        return redirect(url_for("question_bank"))
    if not questions:
        flash("لم يتم العثور على أسئلة في الملف. تأكّد من التنسيق.", "error")
        return redirect(url_for("question_bank"))
    # فرض نوع موحّد على كل الأسئلة لو اختاره المدرس
    if forced_type and forced_type in QTYPES:
        for q in questions:
            q["type"] = forced_type
            if forced_type == "mcq":
                # عند فرض النوع اختيارًا من متعدد: لو لا اختيارات مُلتقطة، جرّب
                # استخراجها من داخل قوسين في نص السؤال (اختيارات مضمّنة).
                has_opts = any(q.get("option_%s" % L) for L in ("a", "b", "c", "d")) \
                    or len(q.get("options") or []) >= 2
                if not has_opts:
                    new_text, inline = exam_import.extract_inline_choices(q.get("text", ""))
                    if not inline:
                        new_text, inline = exam_import.extract_sameline_choices(q.get("text", ""))
                    if inline:
                        q["text"] = new_text
                        q["options"] = inline
                        for i, L in enumerate(("a", "b", "c", "d")):
                            q["option_%s" % L] = inline[i] if i < len(inline) else ""
                        q.setdefault("correct", "a")
            else:
                q.pop("options", None)
    # التصنيف الجماعي المشترك (قيم قياسية موحّدة؛ المادة ثابتة)
    _stage = qb_std_stage(request.form.get("stage", ""))
    common = {
        "stage": _stage,
        "grade": qb_std_grade(request.form.get("grade", ""), _stage),
        "subject": QB_SUBJECT,
        "term": _qb_std_from_list(request.form.get("term", ""), TERM_LABELS),
        "unit": qb_std_unit(request.form.get("unit", "")),
        "lesson": qb_std_lesson(request.form.get("lesson", "")),
        "difficulty": request.form.get("difficulty", "").strip(),
    }
    common["marks"] = request.form.get("marks", "1").strip() or "1"
    common["year_id"] = request.form.get("year_id") or active_year_id()
    # توحيد بنية كل سؤال قبل الحفظ (مصدر واحد للبيانات = نفس ما يُخزَّن ويُعرض لاحقًا):
    # يضمن أن كل سؤال اختيار من متعدد له option_a..d و correct صريحين في المسودة،
    # فتظهر الاختيارات نفسها في المعاينة وفي بنك الأسئلة والامتحان الإلكتروني.
    for q in questions:
        _canonize_mcq_fields(q)
    set_draft("qb_import", {"questions": questions, "filename": f.filename,
                            "common": common, "forced_type": forced_type})
    flash(f"تم العثور على {len(questions)} سؤالًا. راجعها وعدّلها ثم احفظها في البنك.", "success")
    return redirect(url_for("question_bank_import_review"))


@app.route("/question-bank/import-review")
@login_required
def question_bank_import_review():
    draft = get_draft("qb_import")
    if not draft:
        flash("لا توجد أسئلة مستوردة. ارفع ملف Word أولًا.", "error")
        return redirect(url_for("question_bank"))
    conn = db.get_db()
    years = conn.execute("SELECT id, name FROM academic_years ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("qb_import_review.html", draft=draft,
                           qtype_labels=QTYPE_LABELS, stages=EDU_STAGES,
                           terms=TERM_LABELS, difficulty_labels=DIFFICULTY_LABELS,
                           years=years, active_year_id=active_year_id(),
                           units=QB_UNITS, lessons=QB_LESSONS,
                           grades_by_stage=QB_GRADES_BY_STAGE)


@app.route("/question-bank/import-commit", methods=["POST"])
@login_required
def question_bank_import_commit():
    """يحفظ الأسئلة المُراجَعة في بنك الأسئلة مع منع التكرار (تخطٍّ للمكرّر)."""
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "bad json"}), 400
    questions = payload.get("questions") or []
    year_id = payload.get("year_id") or active_year_id()
    on_dup = payload.get("on_duplicate", "skip")   # skip / new
    conn = db.get_db()
    added = skipped = 0
    for q in questions:
        if not (q.get("text") or "").strip():
            continue
        h = _qb_hash(q.get("text"), q.get("qtype") or q.get("type"),
                     q.get("stage"), q.get("grade"), q.get("subject"), q.get("term"))
        dup = _qb_find_duplicate(conn, h)
        if dup and on_dup == "skip":
            skipped += 1
            continue
        _qb_insert(conn, q, year_id=year_id)
        added += 1
    conn.commit()
    conn.close()
    clear_draft("qb_import")
    return jsonify({"ok": True, "added": added, "skipped": skipped})


@app.route("/question-bank/<int:qid>/data")
@login_required
def question_bank_data(qid):
    """يرجّع بيانات سؤال من البنك (JSON) لملء محرّر التعديل."""
    conn = db.get_db()
    row = conn.execute("SELECT * FROM question_bank WHERE id=?", (qid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "غير موجود"}), 404
    return jsonify({"ok": True, "question": dict(row)})


@app.route("/question-bank/<int:qid>/edit", methods=["POST"])
@login_required
def question_bank_edit(qid):
    """تعديل سؤال في بنك الأسئلة (نص/نوع/اختيارات/إجابة/درجة/صعوبة) عبر AJAX."""
    conn = db.get_db()
    row = conn.execute("SELECT * FROM question_bank WHERE id=?", (qid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "السؤال غير موجود"}), 404
    data = request.get_json(silent=True) or request.form
    qtype = (data.get("qtype") or row["qtype"] or "mcq").strip()
    if qtype not in QTYPES:
        qtype = "mcq"
    text = (data.get("text") or "").strip()
    try:
        marks = float(data.get("marks") or row["marks"] or 1)
    except (ValueError, TypeError):
        marks = row["marks"] or 1
    fields = {"option_a": "", "option_b": "", "option_c": "", "option_d": "",
              "correct": "", "answer_text": ""}
    if qtype == "mcq":
        for L in ("a", "b", "c", "d"):
            fields["option_%s" % L] = (data.get("option_%s" % L) or "").strip()
        fields["correct"] = (data.get("correct") or "a").strip()
    elif qtype == "truefalse":
        fields["option_a"] = "صح"
        fields["option_b"] = "خطأ"
        fields["correct"] = (data.get("correct") or "a").strip()
    elif qtype in ("map", "map_complete"):
        # نُبقي extra (صورة/عناصر الخريطة) كما هي
        pass
    else:
        fields["answer_text"] = (data.get("answer_text") or "").strip()
    difficulty = (data.get("difficulty") or "").strip()
    if difficulty not in DIFFICULTY_LABELS:
        difficulty = ""
    conn.execute(
        "UPDATE question_bank SET text=?, qtype=?, marks=?, option_a=?, option_b=?, "
        "option_c=?, option_d=?, correct=?, answer_text=?, difficulty=? WHERE id=?",
        (text, qtype, marks, fields["option_a"], fields["option_b"], fields["option_c"],
         fields["option_d"], fields["correct"], fields["answer_text"], difficulty, qid))
    conn.commit()
    updated = dict(conn.execute("SELECT * FROM question_bank WHERE id=?", (qid,)).fetchone())
    conn.close()
    return jsonify({"ok": True, "question": updated})


@app.route("/question-bank/<int:qid>/delete", methods=["GET", "POST"])
@login_required
def question_bank_delete(qid):
    conn = db.get_db()
    conn.execute("DELETE FROM question_bank WHERE id=?", (qid,))
    conn.commit()
    conn.close()
    # طلب AJAX (fetch): نرجّع JSON بلا إعادة تحميل حتى لا تقفز الصفحة للأعلى
    if request.headers.get("X-Requested-With") == "fetch" or request.method == "POST":
        return jsonify({"ok": True})
    flash("تم حذف السؤال من البنك", "success")
    return redirect(url_for("question_bank"))


@app.route("/question-bank/add-to-exam", methods=["POST"])
@login_required
def question_bank_to_exam():
    """يضيف أسئلة محدّدة من البنك إلى امتحان إلكتروني."""
    eid = request.form.get("exam_id")
    ids = request.form.getlist("qid")
    if not eid or not ids:
        flash("اختر الامتحان والأسئلة المطلوبة.", "error")
        return redirect(url_for("question_bank"))
    conn = db.get_db()
    ex = conn.execute("SELECT id FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        flash("الامتحان غير موجود.", "error")
        return redirect(url_for("question_bank"))
    base = conn.execute("SELECT COALESCE(MAX(position),0) m FROM questions WHERE exam_id=?",
                        (eid,)).fetchone()["m"] or 0
    ph = ",".join("?" for _ in ids)
    bank_qs = conn.execute(f"SELECT * FROM question_bank WHERE id IN ({ph})", tuple(ids)).fetchall()
    for i, bq in enumerate(bank_qs):
        _insert_question(conn, eid, dict(bq), position=base + i + 1)
    _recalc_total(conn, eid)
    conn.commit()
    conn.close()
    flash(f"تمت إضافة {len(bank_qs)} سؤالًا إلى الامتحان ✅", "success")
    return redirect(url_for("exam_edit", eid=eid))


@app.route("/question-bank/create-exam", methods=["POST"])
@login_required
def question_bank_create_exam():
    """ينشئ امتحانًا جديدًا (إلكتروني أو ورقي Word) من أسئلة مختارة من البنك.

    لا يكرّر الأسئلة بلا داعٍ: نسخة واحدة تُدرَج في الامتحان مرجعيةً لأسئلة البنك.
    - إلكتروني: ينشئ امتحانًا منشورًا ويحوّل لصفحة تعديله.
    - ورقي: ينشئ امتحانًا (is_online=0) ويصدّر Word مباشرة للطباعة.
    """
    if _readonly_year_guard():
        return redirect(url_for("question_bank"))
    ids = request.form.getlist("qid")
    title = (request.form.get("title") or "").strip() or "امتحان من بنك الأسئلة"
    exam_kind = request.form.get("exam_kind", "online")   # online / paper
    if not ids:
        flash("اختر سؤالًا واحدًا على الأقل من البنك.", "error")
        return redirect(url_for("question_bank"))
    is_online = 0 if exam_kind == "paper" else 1
    conn = db.get_db()
    # الامتحان الإلكتروني يُنشأ «مسودة» ليعدّله المدرس قبل النشر (لا يُتاح للطلاب فورًا).
    cur = conn.execute(
        "INSERT INTO exams(title,group_id,year_id,duration,is_online,total_marks,status,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (title, request.form.get("group_id") or None, active_year_id(),
         int(request.form.get("duration") or 30), is_online, 0,
         "draft", db.now()))
    eid = cur.lastrowid
    ph = ",".join("?" for _ in ids)
    bank_qs = conn.execute(
        f"SELECT * FROM question_bank WHERE id IN ({ph})", tuple(ids)).fetchall()
    # رتّب حسب ترتيب الاختيار المُرسَل. نُدرج نسخة مستقلة في الامتحان (snapshot):
    # تعديل السؤال داخل الامتحان لاحقًا لا يؤثّر على أصل بنك الأسئلة والعكس.
    order = {int(x): i for i, x in enumerate(ids) if str(x).isdigit()}
    bank_qs = sorted(bank_qs, key=lambda r: order.get(r["id"], 9999))
    for i, bq in enumerate(bank_qs):
        _insert_question(conn, eid, dict(bq), position=i + 1)
    _recalc_total(conn, eid)
    conn.commit()
    conn.close()
    if is_online:
        flash(f"تم إنشاء امتحان إلكتروني (مسودة) بـ {len(bank_qs)} سؤالًا ✅ "
              f"راجع الأسئلة والإعدادات ثم اضغط «نشر الامتحان».", "success")
        return redirect(url_for("exam_edit", eid=eid))
    # الورقي: افتح إعدادات Word (اسم الامتحان) قبل التوليد
    flash(f"تم تجهيز امتحان ورقي بـ {len(bank_qs)} سؤالًا ✅ اكتب اسم الامتحان ثم نزّل الملف.", "success")
    return redirect(url_for("exam_word_setup", eid=eid))


@app.route("/question-bank/<int:qid>/copy-to-year", methods=["POST"])
@login_required
def question_bank_copy_year(qid):
    """ينسخ سؤالًا من البنك إلى عام دراسي آخر دون حذف الأصل (لإعادة الاستخدام).

    ترم الهدف اختياري؛ التصنيف الباقي يُنسخ كما هو. يُحترم منع التكرار في الهدف.
    """
    target_year = request.form.get("target_year_id")
    target_term = (request.form.get("target_term") or "").strip()
    conn = db.get_db()
    src = conn.execute("SELECT * FROM question_bank WHERE id=?", (qid,)).fetchone()
    if not src:
        conn.close()
        flash("السؤال غير موجود.", "error")
        return redirect(url_for("question_bank"))
    q = dict(src)
    if target_term:
        q["term"] = target_term
    h = _qb_hash(q["text"], q["qtype"], q.get("stage"), q.get("grade"),
                 q.get("subject"), q.get("term"))
    # لا تنسخ لو نسخة مطابقة موجودة بالفعل في الهدف
    exists = conn.execute(
        "SELECT id FROM question_bank WHERE dedup_hash=? AND "
        "(year_id=? OR (year_id IS NULL AND ? IS NULL))",
        (h, target_year, target_year)).fetchone()
    if exists:
        conn.close()
        flash("النسخة موجودة بالفعل في العام/الترم الهدف (لم يُكرَّر).", "success")
        return redirect(url_for("question_bank"))
    _qb_insert(conn, q, year_id=target_year)
    conn.commit()
    conn.close()
    flash("تم نسخ السؤال للعام الدراسي الآخر مع الاحتفاظ بالأصل ✅", "success")
    return redirect(url_for("question_bank"))


# ---------------------------------------------------------------------------
# تصدير الامتحان إلى Word (ورقي جاهز للطباعة)
# ---------------------------------------------------------------------------
@app.route("/exams/<int:eid>/word-setup")
@login_required
def exam_word_setup(eid):
    """صفحة إعداد امتحان Word: اسم الامتحان + بيانات الترويسة قبل التوليد."""
    conn = db.get_db()
    ex = conn.execute("SELECT e.*, g.name group_name FROM exams e "
                      "LEFT JOIN groups g ON e.group_id=g.id WHERE e.id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return "الامتحان غير موجود", 404
    nq = conn.execute("SELECT COUNT(*) n FROM questions WHERE exam_id=?", (eid,)).fetchone()["n"]
    conn.close()
    return render_template("exam_word_setup.html", ex=ex, nq=nq,
                           subject=db.get_setting("subject", "الدراسات الاجتماعية"),
                           teacher=teacher_name())


def _safe_filename(name, fallback="exam"):
    """اسم ملف آمن: يحاول الاحتفاظ بالعربية، ويوفّر بديلًا لاتينيًا للتوافق.

    المتصفحات الحديثة تدعم filename* (RFC 5987) بالعربية؛ send_file يمرّر الاسم كما هو
    ويضيف بديلًا لاتينيًا. هنا ننظّف المحارف الخطرة فقط.
    """
    import re as _re
    n = (name or "").strip()
    n = _re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", n).strip()
    n = _re.sub(r"\s+", " ", n)
    return n or fallback


@app.route("/exams/<int:eid>/word")
@login_required
def exam_word(eid):
    conn = db.get_db()
    ex = conn.execute("SELECT e.*, g.name group_name FROM exams e "
                      "LEFT JOIN groups g ON e.group_id=g.id WHERE e.id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return "الامتحان غير موجود", 404
    rows = conn.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY position, id",
                        (eid,)).fetchall()
    conn.close()
    with_answers = request.args.get("answers") == "1"
    # اسم الامتحان المخصّص وبيانات الترويسة (من صفحة الإعداد أو الافتراضي)
    custom_title = (request.args.get("title") or "").strip() or ex["title"]
    header_grade = (request.args.get("grade") or ex["grade"] or "").strip()
    header_term = (request.args.get("term") or "").strip()
    # حوّل صفوف قاعدة البيانات لصيغة docx_helper
    questions = []
    for q in rows:
        qt = q["qtype"] or "mcq"
        item = {"type": qt, "text": q["text"], "marks": q["marks"] or 1}
        if qt == "mcq":
            item["options"] = [q["option_a"] or "", q["option_b"] or "",
                               q["option_c"] or "", q["option_d"] or ""]
            item["answer_index"] = {"a": 0, "b": 1, "c": 2, "d": 3}.get(q["correct"] or "a", 0)
        elif qt == "truefalse":
            item["answer"] = (q["correct"] == "a")
        elif qt in ("map", "map_complete"):
            try:
                extra = json.loads(q["extra"]) if q["extra"] else {}
            except (ValueError, TypeError):
                extra = {}
            item["map_image"] = extra.get("image", "")
            item["map_items"] = extra.get("items", [])
        else:
            item["answer"] = q["answer_text"] or ""
        questions.append(item)
    data = docx_helper.build_exam_docx(
        custom_title, teacher_name(), db.get_setting("subject", "الدراسات الاجتماعية"),
        questions, with_answers=with_answers,
        group=ex["group_name"], duration=ex["duration"],
        grade=header_grade, term=header_term)
    # اسم الملف من اسم الامتحان المخصّص (عربي مدعوم عبر filename* في المتصفحات الحديثة)
    base = _safe_filename(custom_title, "exam")
    if with_answers:
        base += " - نموذج الإجابة"
    fname = base + ".docx"
    resp = send_file(
        io.BytesIO(data), as_attachment=True, download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    # بديل ASCII واضح (exam.docx) بجانب الاسم العربي الكامل (filename*) للتوافق التام
    from urllib.parse import quote
    resp.headers["Content-Disposition"] = (
        "attachment; filename=exam.docx; "
        "filename*=UTF-8''" + quote(fname))
    return resp


# ---------------------------------------------------------------------------
# قسم الامتحانات الورقية (مستقل)
# ---------------------------------------------------------------------------
@app.route("/paper-exams")
@login_required
def paper_exams():
    # تم دمج الامتحانات الورقية والإلكترونية في صفحة واحدة
    return redirect(url_for("exams"))


@app.route("/paper-exams/add", methods=["POST"])
@login_required
def add_paper_exam():
    if _readonly_year_guard():
        return redirect(url_for("exams"))
    conn = db.get_db()
    # السبب الجذري لعدم ظهور الامتحانات الورقية الجديدة: كانت تُنشأ بلا year_id،
    # بينما قائمة الامتحانات تُفلتر WHERE e.year_id=?، فلا تظهر إطلاقًا. نضيف
    # year_id للعام النشط + status='published' (كباقي الامتحانات).
    cur = conn.execute(
        "INSERT INTO exams(title,group_id,year_id,duration,is_online,total_marks,"
        "status,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (request.form["title"], request.form.get("group_id") or None,
         active_year_id(), 0, 0,
         float(request.form.get("total_marks") or 0), "published", db.now()))
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    flash("تم إنشاء الامتحان الورقي", "success")
    return redirect(url_for("paper_grades", eid=eid))


# ---- إدخال درجات الامتحان الورقي ----
@app.route("/exams/<int:eid>/paper", methods=["GET", "POST"])
@login_required
def paper_grades(eid):
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return "الامتحان غير موجود", 404
    if request.method == "POST":
        total = float(request.form.get("total_marks") or ex["total_marks"] or 0)
        conn.execute("UPDATE exams SET total_marks=? WHERE id=?", (total, eid))
        for key in request.form:
            if key.startswith("score_"):
                sid = int(key[6:])
                val = request.form[key].strip()
                if val == "":
                    continue
                conn.execute(
                    "INSERT INTO results(exam_id,student_id,score,taken_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(exam_id,student_id) DO UPDATE SET score=excluded.score, "
                    "taken_at=excluded.taken_at",
                    (eid, sid, float(val), db.now()))
        conn.commit()
        flash("تم حفظ درجات الامتحان الورقي", "success")
        conn.close()
        return redirect(url_for("exam_results", eid=eid))
    if ex["group_id"]:
        studs = conn.execute(
            "SELECT * FROM students WHERE group_id=? "
            "AND (status IS NULL OR status<>'inactive') ORDER BY name",
            (ex["group_id"],)).fetchall()
    else:
        studs = conn.execute(
            "SELECT * FROM students WHERE (status IS NULL OR status<>'inactive') "
            "ORDER BY name").fetchall()
    existing = {r["student_id"]: r["score"] for r in conn.execute(
        "SELECT * FROM results WHERE exam_id=?", (eid,)).fetchall()}
    conn.close()
    return render_template("paper_grades.html", ex=ex, students=studs, existing=existing)


@app.route("/exams/<int:eid>/results")
@login_required
def exam_results(eid):
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    rows = conn.execute(
        "SELECT r.*, s.name, s.parent_phone FROM results r "
        "JOIN students s ON r.student_id=s.id WHERE r.exam_id=? ORDER BY r.score DESC",
        (eid,)).fetchall()
    results = []
    for r in rows:
        pct = round(r["score"] / ex["total_marks"] * 100) if ex["total_marks"] else 0
        status = r["status"] if ("status" in r.keys() and r["status"]) else "graded"
        msg = wa.render_template("exam_result", student=r["name"], exam=ex["title"],
                                 score="%g" % r["score"], total="%g" % ex["total_marks"],
                                 pct=pct)
        results.append({**dict(r), "pct": pct, "status": status,
                        "link": wa.wa_link(r["parent_phone"], msg), "msg": msg})
    conn.close()
    return render_template("exam_results.html", ex=ex, results=results)


@app.route("/exams/<int:eid>/grade/<int:sid>", methods=["GET", "POST"])
@login_required
def grade_manual(eid, sid):
    """تصحيح المستر اليدوي للأسئلة المقالية (علّل / النتائج / الربط والتحليل / القصير)."""
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    r = conn.execute("SELECT * FROM results WHERE exam_id=? AND student_id=?",
                     (eid, sid)).fetchone()
    student = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not ex or not r or not student:
        conn.close()
        return "غير موجود", 404
    qs = conn.execute("SELECT * FROM questions WHERE exam_id=?", (eid,)).fetchall()
    answers = json.loads(r["answers"] or "{}")
    qscores = json.loads(r["question_scores"] or "{}")

    if request.method == "POST":
        auto_score = r["auto_score"] or 0
        manual_score = 0
        for q in qs:
            qtype = q["qtype"] if ("qtype" in q.keys() and q["qtype"]) else "mcq"
            if qtype in MANUAL_QTYPES:
                val = request.form.get(f"score_{q['id']}", "").strip()
                sc = 0.0
                if val != "":
                    try:
                        sc = max(0.0, min(float(val), q["marks"] or 0))
                    except ValueError:
                        sc = 0.0
                qscores[str(q["id"])] = sc
                manual_score += sc
        total_score = auto_score + manual_score
        conn.execute(
            "UPDATE results SET score=?, status='graded', question_scores=? "
            "WHERE exam_id=? AND student_id=?",
            (total_score, json.dumps(qscores, ensure_ascii=False), eid, sid))
        conn.commit()
        # إرسال النتيجة النهائية لولي الأمر تلقائيًا لو API مفعّل
        if wa.api_mode():
            pct = round(total_score / ex["total_marks"] * 100) if ex["total_marks"] else 0
            msg = wa.render_template("exam_result", student=student["name"], exam=ex["title"],
                                     score="%g" % total_score, total="%g" % ex["total_marks"],
                                     pct=pct)
            wa.send_api(student["parent_phone"], msg, msg_type="exam_result")
        conn.close()
        flash(f"تم اعتماد درجة {student['name']}: {('%g' % total_score)} / {('%g' % ex['total_marks'])} ✅",
              "success")
        return redirect(url_for("exam_results", eid=eid))

    # عرض: قسّم الأسئلة لموضوعية (مصححة) ومقالية (للتصحيح)
    items = []
    for q in qs:
        qtype = q["qtype"] if ("qtype" in q.keys() and q["qtype"]) else "mcq"
        items.append({
            "q": q, "qtype": qtype,
            "answer": answers.get(str(q["id"]), ""),
            "score": qscores.get(str(q["id"]), None),
            "manual": qtype in MANUAL_QTYPES,
        })
    conn.close()
    return render_template("grade_manual.html", ex=ex, student=student, items=items, r=r)


# ---- إرسال بيانات دخول الامتحان (الكود + الباسورد + الرابط) لأولياء الأمور ----
@app.route("/exams/<int:eid>/credentials")
@login_required
def exam_creds(eid):
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex:
        conn.close()
        return "الامتحان غير موجود", 404
    if not ex["is_online"]:
        conn.close()
        flash("بيانات الدخول متاحة للامتحانات الإلكترونية فقط", "error")
        return redirect(url_for("exam_results", eid=eid))
    if ex["group_id"]:
        studs = conn.execute(
            "SELECT * FROM students WHERE group_id=? "
            "AND (status IS NULL OR status<>'inactive') ORDER BY name",
            (ex["group_id"],)).fetchall()
    else:
        studs = conn.execute(
            "SELECT * FROM students WHERE (status IS NULL OR status<>'inactive') "
            "ORDER BY name").fetchall()
    conn.close()
    tname = teacher_name()
    subj = db.get_setting("subject", "المادة")
    link = public_exam_url(eid)
    messages = []
    for s in studs:
        msg = (f"السلام عليكم، ولي أمر الطالب/ة *{s['name']}*\n"
               f"بيانات دخول الامتحان الإلكتروني *{ex['title']}* في مادة {subj}:\n\n"
               f"🔗 رابط الامتحان: {link}\n"
               f"🔢 كود الطالب: {_wa_code(s['code'])}\n"
               f"🔑 كلمة المرور: {_wa_code(s['exam_password'])}\n\n"
               f"مع تحيات {tname}")
        messages.append({"name": s["name"], "phone": s["parent_phone"],
                         "status": f"كود: {s['code']}",
                         "link": wa.wa_link(s["parent_phone"], msg), "msg": msg})
    return render_template("whatsapp.html", messages=messages,
                           title=f"بيانات دخول امتحان: {ex['title']}",
                           back=url_for("exam_edit", eid=eid))


def _grade_label(pct):
    """تقدير الطالب حسب النسبة المئوية (للعرض في نتيجة الامتحان)."""
    if pct is None:
        return ""
    if pct >= 90:
        return "ممتاز"
    if pct >= 80:
        return "جيد جدًا"
    if pct >= 65:
        return "جيد"
    if pct >= 50:
        return "مقبول"
    return "ضعيف"


def _build_answer_review(qs, answers):
    """يبني قائمة مراجعة (السؤال + إجابة الطالب + الإجابة الصحيحة) لعرضها للطالب.

    يُستخدم فقط عند تفعيل «إظهار الإجابات الصحيحة للطالب». آمن لكل أنواع الأسئلة.
    """
    labels = {"a": "أ", "b": "ب", "c": "ج", "d": "د"}
    review = []
    for q in qs:
        qd = dict(q)
        qtype = qd.get("qtype") or "mcq"
        sid = str(qd.get("id"))
        given = answers.get(sid, "")
        correct = ""
        if qtype in ("mcq", "truefalse"):
            opts = {"a": qd.get("option_a"), "b": qd.get("option_b"),
                    "c": qd.get("option_c"), "d": qd.get("option_d")}
            cl = qd.get("correct") or ""
            correct = opts.get(cl) or (labels.get(cl, cl))
            given = opts.get(given) or (labels.get(given, given))
        elif qtype in ("complete",):
            correct = qd.get("answer_text") or ""
        else:
            correct = qd.get("answer_text") or "—"
        review.append({"text": qd.get("text"), "given": given or "—",
                       "correct": correct or "—", "qtype": qtype})
    return review


def _exam_availability_error(ex):
    """يرجّع رسالة عربية لو الامتحان غير متاح للطلاب (حالة النشر/المواعيد)، وإلا None.

    - status: draft (مسودة) و closed (موقوف) يمنعان الدخول.
    - open_at / close_at: نافذة زمنية (YYYY-MM-DDTHH:MM) — خارجها يُمنع الدخول.
    آمن مع البيانات القديمة: لو الأعمدة غير موجودة يعامل الامتحان كمتاح.
    """
    def _g(key, default=None):
        try:
            return ex[key] if key in ex.keys() else default
        except Exception:
            return default
    status = _g("status", "published") or "published"
    if status == "draft":
        return "هذا الامتحان لسه مسودة ولم يُنشر بعد. من فضلك تواصل مع المدرس."
    if status == "closed":
        return "تم إيقاف هذا الامتحان. لم يعد متاحًا للأداء."
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    open_at = (_g("open_at", "") or "").strip()
    close_at = (_g("close_at", "") or "").strip()
    if open_at and now < open_at:
        return f"لم يبدأ وقت الامتحان بعد. يبدأ في: {open_at.replace('T', ' ')}"
    if close_at and now > close_at:
        return f"انتهى وقت الامتحان في: {close_at.replace('T', ' ')}"
    return None


# ---- أداء الامتحان الإلكتروني (رابط عام - يتطلب كود وباسورد) ----
@app.route("/take/<int:eid>", methods=["GET", "POST"])
def take_exam(eid):
    conn = db.get_db()
    ex = conn.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not ex or not ex["is_online"]:
        conn.close()
        return "الامتحان غير متاح", 404

    # فحص حالة النشر والمواعيد (إعدادات النشر) — يمنع الدخول خارج المسموح
    avail_err = _exam_availability_error(ex)
    if avail_err:
        conn.close()
        return render_template("take_login.html", ex=ex, error=None, blocked=avail_err)

    # الخطوة 1: تسجيل دخول الطالب بالكود والباسورد
    student = None
    sid_in_session = session.get(f"exam_{eid}_student")
    if sid_in_session:
        student = conn.execute("SELECT * FROM students WHERE id=?",
                               (sid_in_session,)).fetchone()

    if request.method == "POST" and request.form.get("action") == "login":
        code = request.form.get("code", "").strip()
        pw = request.form.get("password", "").strip()
        st = conn.execute("SELECT * FROM students WHERE code=? AND exam_password=?",
                          (code, pw)).fetchone()
        if not st:
            conn.close()
            return render_template("take_login.html", ex=ex,
                                   error="الكود أو كلمة المرور غير صحيحة")
        # فحص عدد المحاولات المسموح بها
        allow_retake = ex["allow_retake"] if ("allow_retake" in ex.keys()) else 0
        max_attempts = ex["max_attempts"] if ("max_attempts" in ex.keys() and ex["max_attempts"] is not None) else 1
        used = conn.execute("SELECT COUNT(*) c FROM exam_attempts WHERE exam_id=? AND student_id=?",
                            (eid, st["id"])).fetchone()["c"]
        if not allow_retake:
            max_attempts = 1
        # max_attempts == 0 يعني غير محدود
        if max_attempts != 0 and used >= max_attempts:
            conn.close()
            return render_template("take_login.html", ex=ex,
                                   error=f"لقد استنفدت عدد المحاولات المسموح بها ({max_attempts}).")
        session[f"exam_{eid}_student"] = st["id"]
        student = st

    if not student:
        conn.close()
        return render_template("take_login.html", ex=ex, error=None)

    qs = conn.execute("SELECT * FROM questions WHERE exam_id=?", (eid,)).fetchall()

    # عيّنة أسئلة عشوائية (إعداد «عدد الأسئلة»): كل طالب يرى عددًا محدّدًا مختارًا
    # عشوائيًا لكن بذرة ثابتة لكل (طالب+امتحان) — فيبقى نفس التصحيح عند التسليم.
    _num_q = ex["num_questions"] if ("num_questions" in ex.keys() and ex["num_questions"]) else 0
    if _num_q and _num_q > 0 and _num_q < len(qs):
        rnd = random.Random(f"{student['id']}-{eid}-subset")
        qs = rnd.sample(list(qs), _num_q)
        # رتّبها بترتيب ثابت (id) لتُصحَّح وتُعرَض بنفس المرجع
        qs = sorted(qs, key=lambda r: r["id"])

    # الخطوة 2: تسليم الإجابات
    if request.method == "POST" and request.form.get("action") == "submit":
        auto_score = 0        # درجة الأسئلة المصححة تلقائيًا
        auto_total = 0        # مجموع درجات الأسئلة الموضوعية
        manual_total = 0      # مجموع درجات الأسئلة المقالية (تنتظر المدرس)
        has_manual = False
        answers = {}
        qscores = {}          # درجة كل سؤال (للأسئلة التلقائية الآن، والمقالية لاحقًا)
        for q in qs:
            qtype = q["qtype"] if ("qtype" in q.keys() and q["qtype"]) else "mcq"
            marks = q["marks"] or 0
            if qtype in ("mcq", "truefalse"):
                ans = request.form.get(f"q_{q['id']}", "")
                answers[str(q["id"])] = ans
                auto_total += marks
                if q["correct"] and ans == q["correct"]:
                    auto_score += marks
                    qscores[str(q["id"])] = marks
                else:
                    qscores[str(q["id"])] = 0
            elif qtype == "complete":
                ans = request.form.get(f"q_{q['id']}", "")
                answers[str(q["id"])] = ans
                auto_total += marks
                model = q["answer_text"] if ("answer_text" in q.keys()) else ""
                # تصحيح تلقائي: مطابقة بعد التطبيع (يقبل تطابق كامل أو احتواء)
                na, nm = _normalize_answer(ans), _normalize_answer(model)
                correct = bool(nm) and (na == nm or (len(na) > 2 and (na in nm or nm in na)))
                if correct:
                    auto_score += marks
                    qscores[str(q["id"])] = marks
                else:
                    qscores[str(q["id"])] = 0
            elif qtype in ("matching", "ordering"):
                # تصحيح تلقائي جزئي (درجة لكل عنصر صحيح)
                auto_total += marks
                extra = {}
                try:
                    extra = json.loads(q["extra"]) if ("extra" in q.keys() and q["extra"]) else {}
                except (ValueError, TypeError):
                    extra = {}
                if qtype == "matching":
                    left = extra.get("left", [])
                    amap = extra.get("answer_map", {})
                    ans_list = []
                    got = 0
                    for idx, lt in enumerate(left):
                        chosen = request.form.get(f"q_{q['id']}_{idx}", "")
                        ans_list.append(chosen)
                        if _normalize_answer(chosen) == _normalize_answer(amap.get(lt, "")):
                            got += 1
                    answers[str(q["id"])] = json.dumps(ans_list, ensure_ascii=False)
                    n = len(left) or 1
                    sc = round(marks * got / n, 2)
                else:  # ordering
                    correct_order = extra.get("answer_order", [])
                    ans_list = []
                    got = 0
                    for idx in range(len(correct_order)):
                        chosen = request.form.get(f"q_{q['id']}_{idx}", "")
                        ans_list.append(chosen)
                        if idx < len(correct_order) and \
                                _normalize_answer(chosen) == _normalize_answer(correct_order[idx]):
                            got += 1
                    answers[str(q["id"])] = json.dumps(ans_list, ensure_ascii=False)
                    n = len(correct_order) or 1
                    sc = round(marks * got / n, 2)
                auto_score += sc
                qscores[str(q["id"])] = sc
            elif qtype in ("map", "map_complete"):
                # سؤال خريطة: تصحيح تلقائي جزئي (درجة لكل رقم صحيح)
                auto_total += marks
                extra = {}
                try:
                    extra = json.loads(q["extra"]) if ("extra" in q.keys() and q["extra"]) else {}
                except (ValueError, TypeError):
                    extra = {}
                items = extra.get("items", [])  # [{num, answer, marks}]
                ans_map = {}
                got_marks = 0.0
                item_total = 0.0
                for it in items:
                    num = str(it.get("num"))
                    im = float(it.get("marks") or 0)
                    item_total += im
                    chosen = request.form.get(f"q_{q['id']}_{num}", "")
                    ans_map[num] = chosen
                    if _normalize_answer(chosen) == _normalize_answer(it.get("answer", "")) \
                            and it.get("answer"):
                        got_marks += im
                answers[str(q["id"])] = json.dumps(ans_map, ensure_ascii=False)
                # الدرجة: نِسبة الأرقام الصحيحة من درجة السؤال (أو مجموع درجات الأرقام)
                if item_total > 0:
                    sc = round(marks * got_marks / item_total, 2)
                else:
                    sc = 0
                auto_score += sc
                qscores[str(q["id"])] = sc
            else:
                # أنواع مقالية (compare / cause_effect / analysis / short): تنتظر تصحيح المدرس
                ans = request.form.get(f"q_{q['id']}", "")
                answers[str(q["id"])] = ans
                has_manual = True
                manual_total += marks
        # الحالة: لو فيه أسئلة مقالية -> pending (في انتظار تصحيح المستر)
        status = "pending" if has_manual else "graded"
        score = auto_score
        qscores_json = json.dumps(qscores, ensure_ascii=False)
        answers_json = json.dumps(answers, ensure_ascii=False)
        # سجّل هذه المحاولة منفصلة (كل محاولة محفوظة)
        prev = conn.execute("SELECT COALESCE(MAX(attempt_no),0) m FROM exam_attempts "
                            "WHERE exam_id=? AND student_id=?", (eid, student["id"])).fetchone()["m"]
        attempt_no = prev + 1
        conn.execute(
            "INSERT INTO exam_attempts(exam_id,student_id,attempt_no,score,auto_score,status,"
            "question_scores,answers,taken_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (eid, student["id"], attempt_no, score, auto_score, status,
             qscores_json, answers_json, db.now()))
        # حدّد المحاولة المعتمدة حسب السياسة (highest / latest / manual)
        policy = ex["final_policy"] if ("final_policy" in ex.keys() and ex["final_policy"]) else "highest"
        atts = conn.execute("SELECT * FROM exam_attempts WHERE exam_id=? AND student_id=? "
                            "ORDER BY attempt_no", (eid, student["id"])).fetchall()
        if policy == "latest":
            chosen = atts[-1]
        elif policy == "manual":
            # يدوي: نُبقي الأعلى مبدئيًا حتى يختار المدرس (final_attempt_id)
            chosen = max(atts, key=lambda a: a["score"])
        else:  # highest
            chosen = max(atts, key=lambda a: a["score"])
        # النتيجة المعتمدة تُحفظ في results (المصدر الوحيد للتقارير)
        conn.execute(
            "INSERT INTO results(exam_id,student_id,score,auto_score,status,question_scores,answers,taken_at) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(exam_id,student_id) DO UPDATE SET score=excluded.score, "
            "auto_score=excluded.auto_score, status=excluded.status, "
            "question_scores=excluded.question_scores, answers=excluded.answers, taken_at=excluded.taken_at",
            (eid, student["id"], chosen["score"], chosen["auto_score"], chosen["status"],
             chosen["question_scores"], chosen["answers"], chosen["taken_at"]))
        conn.commit()
        # إرسال النتيجة لولي الأمر (إعداد «إرسال النتيجة إلى ولي الأمر»)
        _send_parent = ex["send_result_to_parent"] if ("send_result_to_parent" in ex.keys()) else 0
        if status == "graded" and _send_parent and wa.api_mode():
            pct = round(score / ex["total_marks"] * 100) if ex["total_marks"] else 0
            msg = wa.render_template("exam_result", student=student["name"], exam=ex["title"],
                                     score="%g" % score, total="%g" % ex["total_marks"], pct=pct)
            wa.send_api(student["parent_phone"], msg, msg_type="exam_result")
        session.pop(f"exam_{eid}_student", None)
        # إعدادات إظهار النتيجة للطالب
        show_result = ex["show_result_to_student"] if ("show_result_to_student" in ex.keys()) else 1
        show_score = ex["show_score"] if ("show_score" in ex.keys()) else 1
        show_pct = ex["show_percentage"] if ("show_percentage" in ex.keys()) else 1
        show_grade = ex["show_grade_label"] if ("show_grade_label" in ex.keys()) else 1
        show_answers = ex["show_answers_to_student"] if ("show_answers_to_student" in ex.keys()) else 0
        # جهّز مراجعة الإجابات الصحيحة لو مسموح بإظهارها للطالب
        review = None
        if show_answers and show_result:
            review = _build_answer_review(qs, answers)
        conn.close()
        if status == "pending":
            return render_template("exam_done.html", ex=ex, pending=True,
                                   show_result=show_result)
        pct = round(score / ex["total_marks"] * 100) if ex["total_marks"] else 0
        grade_label = _grade_label(pct)
        return render_template("exam_done.html", ex=ex, score=score, pct=pct, pending=False,
                               show_result=show_result, show_score=show_score,
                               show_pct=show_pct, show_grade=show_grade,
                               grade_label=grade_label, review=review)

    # جهّز بيانات الأسئلة للعرض (+ التوصيل/الترتيب/الخريطة)
    q_view = []
    for q in qs:
        d = dict(q)
        qtype = d.get("qtype") or "mcq"
        if qtype in ("matching", "ordering", "map", "map_complete") and d.get("extra"):
            try:
                d["extra_data"] = json.loads(d["extra"])
            except (ValueError, TypeError):
                d["extra_data"] = {}
        # ترتيب اختيارات mcq عشوائيًا (مع الحفاظ على تتبّع الإجابة الصحيحة بقيمتها letter)
        _shuffle_choices = ("shuffle_choices" in ex.keys()) and ex["shuffle_choices"]
        if qtype == "mcq" and _shuffle_choices:
            opts = [("a", d.get("option_a")), ("b", d.get("option_b")),
                    ("c", d.get("option_c")), ("d", d.get("option_d"))]
            opts = [(ltr, txt) for ltr, txt in opts if txt]
            rnd = random.Random(f"{student['id']}-{q['id']}-choices")
            rnd.shuffle(opts)
            # الحرف المُرسل يبقى الحرف الأصلي للخيار (فالتصحيح يبقى صحيحًا)
            d["shuffled_choices"] = opts
        q_view.append(d)
    # ترتيب الأسئلة عشوائيًا لكل طالب (بذرة ثابتة أثناء نفس المحاولة)
    _shuffle_questions = ("shuffle_questions" in ex.keys()) and ex["shuffle_questions"]
    if _shuffle_questions:
        used = conn.execute("SELECT COUNT(*) c FROM exam_attempts WHERE exam_id=? AND student_id=?",
                            (eid, student["id"])).fetchone()["c"]
        rnd = random.Random(f"{student['id']}-{eid}-{used}")
        rnd.shuffle(q_view)
    conn.close()
    # إعدادات عرض الامتحان للطالب
    show_qnum = ex["show_question_number"] if ("show_question_number" in ex.keys()) else 1
    one_per_page = ex["one_question_per_page"] if ("one_question_per_page" in ex.keys()) else 0
    prevent_back = ex["prevent_back"] if ("prevent_back" in ex.keys()) else 0
    return render_template("take_exam.html", ex=ex, questions=q_view, student=student,
                           show_qnum=show_qnum, one_per_page=one_per_page,
                           prevent_back=prevent_back)


# ---------------------------------------------------------------------------
# التقارير المالية الشهرية
# ---------------------------------------------------------------------------
def build_report(start_date, end_date, label=None, year_id=None):
    """تقرير مالي لفترة بين تاريخين (شاملين) ضمن عام دراسي محدّد.

    يعرض السجلات المالية حتى للطلاب المحذوفين (عبر لقطة الاسم student_name_snapshot).
    """
    if year_id is None:
        year_id = active_year_id()
    conn = db.get_db()
    sessions = conn.execute(
        "SELECT se.*, g.name group_name, "
        "(SELECT COALESCE(SUM(amount),0) FROM attendance a WHERE a.session_id=se.id AND a.paid=1) income, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.session_id=se.id AND a.status IN ('present','late')) attended, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.session_id=se.id AND a.paid=1) paid_cnt "
        "FROM sessions se LEFT JOIN groups g ON se.group_id=g.id "
        "WHERE se.year_id=? AND se.date>=? AND se.date<=? ORDER BY se.date",
        (year_id, start_date, end_date)).fetchall()
    total = sum(s["income"] for s in sessions)
    by_group = defaultdict(float)
    for s in sessions:
        by_group[s["group_name"] or "بدون مجموعة"] += s["income"]
    # اسم الطالب: من جدول الطلاب إن وُجد، وإلا من لقطة الاسم المحفوظة (طالب محذوف).
    # is_deleted=1 عندما لا يوجد سجل طالب مطابق (تم حذف ملفه) لكن السجل المالي باقٍ.
    # غير المدفوع: يستبعد المعفيين (fee_exempt=1)، ويعتمد السعر الفعلي المستحق
    # (fee_charged: سعر التخفيض إن وُجد وقت الحفظ وإلا سعر المجموعة) بدل سعر المجموعة
    # الخام. المتبقّي = السعر الفعلي − المدفوع، ويُدرَج فقط لو أكبر من صفر (فالتخفيض
    # ليس دَينًا: من يدفع سعره المخفّض كاملًا ليس متأخرًا).
    # السعر الفعلي المستحق = سعر التخفيض الحالي للطالب لهذا العام (enr.discount_fee)
    # إن وُجد، وإلا سعر الحصة (se.fee). نستخدم السعر الحالي (لا لقطة fee_charged القديمة)
    # ليتطابق التقرير مع صفحة التذكيرات ولينعكس تصحيح سعر المجموعة (50 ← 37.5) تلقائيًا.
    unpaid = conn.execute(
        "SELECT COALESCE(s.name, a.student_name_snapshot, 'طالب محذوف') AS name, "
        "CASE WHEN s.id IS NULL THEN 1 ELSE 0 END AS is_deleted, se.date, "
        "COALESCE(enr.discount_fee, a.fee_charged, se.fee) AS fee, "
        "(COALESCE(enr.discount_fee, a.fee_charged, se.fee) - COALESCE(a.amount,0)) AS remaining "
        "FROM attendance a "
        "LEFT JOIN students s ON a.student_id=s.id JOIN sessions se ON a.session_id=se.id "
        "LEFT JOIN enrollments enr ON enr.student_id=a.student_id AND enr.year_id=se.year_id "
        "WHERE (a.fee_exempt IS NULL OR a.fee_exempt=0) "
        "AND a.status IN ('present','late') "
        "AND (COALESCE(enr.discount_fee, a.fee_charged, se.fee) - COALESCE(a.amount,0)) > 0 "
        "AND se.year_id=? AND se.date>=? AND se.date<=? "
        "ORDER BY se.date", (year_id, start_date, end_date)).fetchall()
    # المعفَون من الرسوم (للعرض المنفصل في التقرير المالي — لا يُحسبون غير مدفوع)
    exempt = conn.execute(
        "SELECT COALESCE(s.name, a.student_name_snapshot, 'طالب محذوف') AS name, "
        "CASE WHEN s.id IS NULL THEN 1 ELSE 0 END AS is_deleted, "
        "se.date, a.exempt_reason FROM attendance a "
        "LEFT JOIN students s ON a.student_id=s.id JOIN sessions se ON a.session_id=se.id "
        "WHERE a.fee_exempt=1 AND a.status IN ('present','late') "
        "AND se.year_id=? AND se.date>=? AND se.date<=? "
        "ORDER BY se.date", (year_id, start_date, end_date)).fetchall()
    # سجل المدفوعات (كل دفعة فعلية) — يشمل مدفوعات الطلاب المحذوفين بلقطة الاسم،
    # ليبقى «الحساب المالي» ظاهرًا في التقرير بعد حذف الملف الشخصي (البنود 1،4،9).
    paid = conn.execute(
        "SELECT COALESCE(s.name, a.student_name_snapshot, 'طالب محذوف') AS name, "
        "CASE WHEN s.id IS NULL THEN 1 ELSE 0 END AS is_deleted, "
        "COALESCE(g.name, a.group_name_snapshot) AS group_name, "
        "se.date, a.amount FROM attendance a "
        "LEFT JOIN students s ON a.student_id=s.id "
        "LEFT JOIN groups g ON a.group_id=g.id "
        "JOIN sessions se ON a.session_id=se.id "
        "WHERE a.paid=1 AND a.amount>0 "
        "AND se.year_id=? AND se.date>=? AND se.date<=? "
        "ORDER BY se.date", (year_id, start_date, end_date)).fetchall()
    conn.close()
    if label is None:
        label = f"{start_date} إلى {end_date}"
    return {"start_date": start_date, "end_date": end_date, "label": label,
            "sessions": sessions, "total": total,
            "by_group": dict(by_group), "unpaid": [dict(r) for r in unpaid],
            "exempt": [dict(r) for r in exempt],
            "paid": [dict(r) for r in paid]}


def build_month_report(month):
    """توافقية: تقرير شهر كامل (YYYY-MM)"""
    start = f"{month}-01"
    end = f"{month}-31"
    return build_report(start, end, label=f"شهر {month}")


def _resolve_range(args):
    """يحدد الفترة من الباراميترات: نطاق مخصص (start/end) أو شهر."""
    start = (args.get("start") or "").strip()
    end = (args.get("end") or "").strip()
    if start and end:
        return start, end, f"{start} إلى {end}"
    month = args.get("month", datetime.now().strftime("%Y-%m"))
    return f"{month}-01", f"{month}-31", f"شهر {month}"


@app.route("/reports")
@login_required
def reports():
    start, end, label = _resolve_range(request.args)
    data = build_report(start, end, label=label)
    # للتوافق مع القالب القديم: مرّر month لو الوضع شهري
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    custom = bool((request.args.get("start") or "").strip() and
                  (request.args.get("end") or "").strip())
    return render_template("reports.html", month=month, custom=custom, **data)


def _report_rows(data):
    headers = ["التاريخ", "المجموعة", "عنوان الحصة", "سعر الحصة",
               "عدد الحاضرين", "عدد الدافعين", "دخل الحصة"]
    rows = [[s["date"], s["group_name"] or "-", s["title"] or "-",
             s["fee"], s["attended"], s["paid_cnt"], s["income"]]
            for s in data["sessions"]]
    footer = ["", "", "", "", "", "الإجمالي", data["total"]]
    return headers, rows, footer


@app.route("/reports/excel")
@login_required
def report_excel():
    start, end, label = _resolve_range(request.args)
    data = build_report(start, end, label=label)
    headers, rows, footer = _report_rows(data)
    title = f"التقرير المالي - {teacher_name()} - {label}"
    content, ext, mime = xls.build_report_file(title, headers, rows, footer)
    fname = f"report_{start}_{end}".replace("-", "")
    return send_file(io.BytesIO(content), as_attachment=True,
                     download_name=f"{fname}.{ext}", mimetype=mime)


def report_html_for_email(data):
    rows = ""
    for s in data["sessions"]:
        rows += (f"<tr><td>{s['date']}</td><td>{s['group_name'] or '-'}</td>"
                 f"<td>{s['title'] or '-'}</td><td>{s['attended']}</td>"
                 f"<td>{s['paid_cnt']}</td><td>{s['income']:g} ج</td></tr>")
    groups = "".join(f"<li>{k}: <b>{v:g} ج</b></li>" for k, v in data["by_group"].items())
    return f"""
    <div dir="rtl" style="font-family:Tahoma,Arial;color:#1e293b">
      <h2 style="color:#2563eb">التقرير المالي - {data['label']}</h2>
      <p>المدرس: <b>{teacher_name()}</b></p>
      <h3>إجمالي الدخل: <span style="color:#16a34a">{data['total']:g} جنيه</span></h3>
      <h4>الدخل حسب المجموعة</h4><ul>{groups}</ul>
      <h4>تفاصيل الحصص</h4>
      <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%">
        <tr style="background:#2563eb;color:#fff">
          <th>التاريخ</th><th>المجموعة</th><th>الحصة</th><th>الحاضرون</th><th>الدافعون</th><th>الدخل</th>
        </tr>{rows}
      </table>
      <p style="color:#64748b">عدد الطلاب المتأخرين في الدفع: {len(data['unpaid'])}</p>
    </div>"""


@app.route("/reports/email", methods=["POST"])
@login_required
def report_email():
    start, end, label = _resolve_range(request.form)
    redirect_args = {}
    if (request.form.get("start") or "").strip() and (request.form.get("end") or "").strip():
        redirect_args = {"start": start, "end": end}
    else:
        redirect_args = {"month": request.form.get("month", datetime.now().strftime("%Y-%m"))}
    to_email = request.form.get("email") or db.get_setting("report_email")
    data = build_report(start, end, label=label)
    host = db.get_setting("smtp_host")
    port = int(db.get_setting("smtp_port") or 587)
    user = db.get_setting("smtp_user")
    pw = db.get_setting("smtp_pass")
    if not (user and pw and to_email):
        flash("لازم تضبط إعدادات الإيميل (SMTP) والإيميل المستلم من صفحة الإعدادات أولاً", "error")
        return redirect(url_for("reports", **redirect_args))
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"التقرير المالي - {label}"
        msg["From"] = user
        msg["To"] = to_email
        msg.attach(MIMEText(report_html_for_email(data), "html", "utf-8"))
        # مرفق التقرير (Excel أو CSV تلقائيًا لو openpyxl غير متاح)
        headers, rows, footer = _report_rows(data)
        title = f"التقرير المالي - {teacher_name()} - {label}"
        content, ext, mime = xls.build_report_file(title, headers, rows, footer)
        subtype = "xlsx" if ext == "xlsx" else "csv"
        fname = f"report_{start}_{end}".replace("-", "")
        part = MIMEApplication(content, _subtype=subtype)
        part.add_header("Content-Disposition", "attachment",
                        filename=f"{fname}.{ext}")
        msg.attach(part)
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, pw)
            server.send_message(msg)
        flash(f"تم إرسال التقرير بنجاح إلى {to_email}", "success")
    except Exception as e:
        flash(f"فشل إرسال الإيميل: {e}", "error")
    return redirect(url_for("reports", **redirect_args))


# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------
@app.route("/set-theme", methods=["POST"])
def set_theme():
    """يحفظ الوضع النهاري/الليلي عالميًا في قاعدة البيانات ليبقى بعد الخروج/إعادة التشغيل.

    متاح بلا تسجيل دخول ليعمل من صفحات الدخول/الطالب/ولي الأمر أيضًا (الوضع عام للموقع).
    """
    data = request.get_json(silent=True) or {}
    theme = data.get("theme") or request.form.get("theme") or "light"
    if theme not in ("light", "dark"):
        theme = "light"
    db.set_setting("ui_theme", theme)
    return jsonify({"ok": True, "theme": theme})


@app.route("/set-animations", methods=["POST"])
def set_animations():
    """يحفظ مستوى حركات الواجهة عالميًا (off/simple/medium/full)."""
    data = request.get_json(silent=True) or {}
    level = data.get("level") or request.form.get("level") or "simple"
    if level not in ("off", "simple", "medium", "full"):
        level = "simple"
    db.set_setting("ui_animations", level)
    return jsonify({"ok": True, "level": level})


# خانات المعرض المدعومة (الشعارات فقط) — خلفيات الدخول القديمة أُزيلت نهائيًا
# وتُدار الآن حصريًا عبر محرّر تخطيط صفحة الدخول.
_GALLERY_SLOTS = ("teacher_logo", "parent_logo")


def _gallery_get(slot):
    """يرجّع قائمة الصور المخزّنة لخانة (معرض)، من إعداد JSON."""
    import json as _json
    try:
        data = _json.loads(db.get_setting(f"{slot}_gallery", "[]") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _gallery_set(slot, images):
    import json as _json
    db.set_setting(f"{slot}_gallery", _json.dumps(images, ensure_ascii=False))


@app.route("/settings/gallery/add", methods=["POST"])
@login_required
def gallery_add():
    """يرفع صورة جديدة لمعرض خانة (شعار/خلفية) ويجعلها النشطة. يرجّع JSON."""
    slot = request.form.get("slot", "")
    if slot not in _GALLERY_SLOTS:
        return jsonify({"ok": False, "error": "خانة غير معروفة"}), 400
    try:
        data = _read_image_field("image")
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if not data:
        return jsonify({"ok": False, "error": "لم يتم اختيار صورة"}), 400
    images = _gallery_get(slot)
    if data not in images:
        images.append(data)
    _gallery_set(slot, images)
    db.set_setting(slot, data)   # اجعلها النشطة
    return jsonify({"ok": True, "images": images, "active": data,
                    "index": images.index(data)})


@app.route("/settings/gallery/activate", methods=["POST"])
@login_required
def gallery_activate():
    """يجعل صورة من المعرض هي النشطة (الظاهرة فعليًا)."""
    slot = request.form.get("slot", "")
    try:
        idx = int(request.form.get("index", -1))
    except (ValueError, TypeError):
        idx = -1
    if slot not in _GALLERY_SLOTS:
        return jsonify({"ok": False, "error": "خانة غير معروفة"}), 400
    images = _gallery_get(slot)
    if idx < 0 or idx >= len(images):
        return jsonify({"ok": False, "error": "صورة غير موجودة"}), 400
    db.set_setting(slot, images[idx])
    return jsonify({"ok": True, "active": images[idx]})


@app.route("/settings/gallery/delete", methods=["POST"])
@login_required
def gallery_delete():
    """يحذف صورة من المعرض؛ لو كانت النشطة يعيّن التالية (أو يفرّغ)."""
    slot = request.form.get("slot", "")
    try:
        idx = int(request.form.get("index", -1))
    except (ValueError, TypeError):
        idx = -1
    if slot not in _GALLERY_SLOTS:
        return jsonify({"ok": False, "error": "خانة غير معروفة"}), 400
    images = _gallery_get(slot)
    if idx < 0 or idx >= len(images):
        return jsonify({"ok": False, "error": "صورة غير موجودة"}), 400
    removed = images.pop(idx)
    _gallery_set(slot, images)
    # لو المحذوفة كانت النشطة، عيّن أول صورة متبقية أو فرّغ
    if db.get_setting(slot, "") == removed:
        db.set_setting(slot, images[0] if images else "")
    return jsonify({"ok": True, "images": images, "active": db.get_setting(slot, "")})


_LAYOUT_PORTALS = {"teacher": "teacher_login_layout", "parent": "parent_login_layout"}
# أنماط عرض الصورة المسموح بها في تخطيط الدخول
_LAYOUT_MODES = {"background", "fullscreen", "top", "bottom", "right", "left",
                 "beside", "top_bottom", "sides", "bg_sides"}


def _migrate_bg_into_layout():
    """تنظيف نهائي للخلفية القديمة المهجورة (teacher_bg / parent_bg).

    السبب الجذري للمشكلة: قديمًا كانت صفحات الدخول تطبّق الخلفية المفردة القديمة
    مباشرةً على <body> (عبر bg_style)، بالتوازي مع نظام تخطيط الدخول الجديد
    (_login_layout). كما أن ترحيلًا سابقًا نسخ الخلفية القديمة *داخل* التخطيط
    كصورة نمطها background. فكانت الصورة القديمة تظهر دائمًا (حتى بعد إزالة إعدادها
    من الواجهة)، وتظهر الصورة الجديدة فوقها.

    الإصلاح الجذري (idempotent، لا يمسّ صور التخطيط الجديدة التي رفعها المستخدم):
      1) إزالة أي صورة في التخطيط مصدرها (src) يطابق الخلفية القديمة تمامًا
         (هذه أُدرجت آليًا بالترحيل السابق فقط — نحذفها بالمطابقة الدقيقة للمصدر).
      2) مسح إعدادات الخلفية القديمة المهجورة نهائيًا (teacher_bg / parent_bg
         وضبط عرضها) حتى لا يقرأها أي كود أو قالب مجددًا.
    لا يُحذف الشعار ولا صور التخطيط الأخرى (خلفية/جانب/ملء الشاشة) التي رفعها
    المستخدم من المحرّر الجديد.
    """
    import json as _json
    if db.get_setting("legacy_bg_cleaned", "0") == "1":
        return
    for portal, bg_key in (("teacher", "teacher_bg"), ("parent", "parent_bg")):
        old_bg = db.get_setting(bg_key, "")
        # (1) نظّف التخطيط من الصورة القديمة المطابِقة للمصدر (لو أُدرجت آليًا)
        if old_bg:
            lkey = _LAYOUT_PORTALS[portal]
            try:
                layout = _json.loads(db.get_setting(lkey, "{}") or "{}")
            except Exception:
                layout = {}
            if isinstance(layout, dict) and layout.get("images"):
                new_imgs = [i for i in layout["images"] if i.get("src") != old_bg]
                if len(new_imgs) != len(layout["images"]):
                    layout["images"] = new_imgs
                    db.set_setting(lkey, _json.dumps(layout, ensure_ascii=False))
        # (2) امسح الإعداد القديم المهجور نهائيًا (وضبط عرضه)
        db.set_setting(bg_key, "")
        db.set_setting(bg_key + "_size", "cover")
        db.set_setting(bg_key + "_pos_x", "50")
        db.set_setting(bg_key + "_pos_y", "50")
        # كذلك معرض الصور القديم لهذه الخانة (لم يعد مستخدمًا في الواجهة)
        db.set_setting(bg_key + "_gallery", "[]")
    db.set_setting("legacy_bg_cleaned", "1")


def _login_layout_get(portal):
    """يرجّع تخطيط دخول بوابة (dict) من إعداد JSON، أو {} إن لا يوجد."""
    import json as _json
    key = _LAYOUT_PORTALS.get(portal)
    if not key:
        return {}
    try:
        data = _json.loads(db.get_setting(key, "{}") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sanitize_layout(data):
    """يتحقّق من صحة تخطيط الدخول قبل الحفظ (قيم مضبوطة، بلا محتوى ضار)."""
    if not isinstance(data, dict):
        return {}
    out = {"images": [], "form_pos": "center"}
    fp = data.get("form_pos")
    if fp in ("center", "right", "left", "top", "bottom"):
        out["form_pos"] = fp
    imgs = data.get("images") or []
    if not isinstance(imgs, list):
        imgs = []
    for it in imgs[:8]:   # حد أقصى 8 صور لكل بوابة
        if not isinstance(it, dict):
            continue
        src = it.get("src") or ""
        if not (isinstance(src, str) and src.startswith("data:image")):
            continue
        def _num(v, lo, hi, dflt):
            try:
                n = float(v)
            except (ValueError, TypeError):
                return dflt
            return max(lo, min(hi, n))
        mode = it.get("mode") if it.get("mode") in _LAYOUT_MODES else "background"
        out["images"].append({
            "src": src,
            "mode": mode,
            "x": _num(it.get("x"), 0, 100, 50),
            "y": _num(it.get("y"), 0, 100, 50),
            "scale": _num(it.get("scale"), 10, 400, 100),
            "rotation": _num(it.get("rotation"), -180, 180, 0),
            "fit": it.get("fit") if it.get("fit") in ("cover", "contain") else "cover",
            "z": int(_num(it.get("z"), 0, 99, 1)),
            "opacity": _num(it.get("opacity"), 10, 100, 100),
        })
    return out


@app.route("/settings/login-layout/<portal>", methods=["GET", "POST"])
@login_required
def login_layout(portal):
    """حفظ/جلب تخطيط صور صفحة الدخول لبوابة (معلّم/ولي أمر) — مستقلّان تمامًا."""
    if portal not in _LAYOUT_PORTALS:
        return jsonify({"ok": False, "error": "بوابة غير معروفة"}), 400
    if request.method == "GET":
        return jsonify({"ok": True, "layout": _login_layout_get(portal)})
    import json as _json
    data = request.get_json(silent=True) or {}
    clean = _sanitize_layout(data)
    db.set_setting(_LAYOUT_PORTALS[portal], _json.dumps(clean, ensure_ascii=False))
    return jsonify({"ok": True, "layout": clean})


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        section = request.form.get("section")
        if section == "customize":
            # تخصيص الواجهات: رفع/حذف شعار بوابتي المعلّم وولي الأمر فقط (base64).
            # ملاحظة: الخلفية القديمة المفردة (teacher_bg/parent_bg) أُزيلت نهائيًا؛
            # الخلفية والصور الآن تُدار حصريًا من «محرّر تخطيط صفحة الدخول» (JSON).
            try:
                for key in ("parent_logo", "teacher_logo"):
                    if request.form.get(f"remove_{key}"):
                        db.set_setting(key, "")
                        continue
                    data = _read_image_field(key)
                    if data:
                        db.set_setting(key, data)
            except ValueError as e:
                flash(str(e), "error")
                return redirect(url_for("settings", tab="customize"))
            flash("تم حفظ تخصيص الواجهات ✅", "success")
            return redirect(url_for("settings", tab="customize"))
        if section == "account":
            conn = db.get_db()
            row = conn.execute("SELECT * FROM admin LIMIT 1").fetchone()
            new_user = request.form.get("username", "").strip()
            cur_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            if not check_password_hash(row["password_hash"], cur_pw):
                conn.close()
                flash("كلمة المرور الحالية غير صحيحة", "error")
                return redirect(url_for("settings", tab="account"))
            if new_user:
                conn.execute("UPDATE admin SET username=? WHERE id=?", (new_user, row["id"]))
                session["admin"] = new_user
            if new_pw:
                if len(new_pw) < 4:
                    conn.close()
                    flash("كلمة المرور الجديدة قصيرة جدًا", "error")
                    return redirect(url_for("settings", tab="account"))
                conn.execute("UPDATE admin SET password_hash=? WHERE id=?",
                             (generate_password_hash(new_pw), row["id"]))
            conn.commit()
            conn.close()
            flash("تم حفظ بيانات الحساب بنجاح ✅", "success")
        else:
            keys = ["teacher_name", "subject", "teacher_phone",
                    "smtp_host", "smtp_port",
                    "smtp_user", "report_email", "site_url",
                    "supabase_url", "supabase_key",
                    "session_timeout", "auto_backup_interval",
                    "wa_mode", "wa_provider", "wa_api_url", "wa_api_token",
                    "wa_phone_id", "wa_from",
                    "ai_key_openai", "ai_key_gemini", "ai_key_kimi",
                    "ai_key_openrouter", "ai_key_custom",
                    "ai_model_openai", "ai_model_gemini", "ai_model_kimi",
                    "ai_model_openrouter", "ai_model_custom", "ai_base_custom"]
            # مفاتيح الـ AI: لا تُمسح لو تُركت فارغة (حتى لا يطغى مزوّد على آخر)
            ai_key_fields = {"ai_key_openai", "ai_key_gemini", "ai_key_kimi",
                             "ai_key_openrouter", "ai_key_custom"}
            for k in keys:
                if k in request.form:
                    if k in ("smtp_pass",) and not request.form[k]:
                        continue
                    # مفتاح AI فارغ = إبقاء القديم (إلا لو المستخدم مسحه صراحةً عبر زر الحذف)
                    if k in ai_key_fields and not request.form.get(k, "").strip():
                        continue
                    db.set_setting(k, request.form[k])
            if request.form.get("smtp_pass"):
                db.set_setting("smtp_pass", request.form["smtp_pass"])
            # تفعيل/تعطيل Supabase والنسخ التلقائي:
            # نلمس كل مفتاح فقط عند حفظ النموذج الذي يملك مربّعه تحديدًا (عبر حقل
            # مخفي supabase_form). قبل ذلك كان أي حفظ لتبويب آخر — أو حتى النموذج
            # الثاني داخل نفس التبويب — يُعيد المفتاح الغائب إلى "0" فيُطفئ Supabase
            # أو النسخ التلقائي بلا قصد (المشكلة المبلّغ عنها). هكذا يظل التفعيل دائمًا
            # ولا يتعطّل إلا يدويًا من نفس النموذج.
            if section == "supabase":
                sform = request.form.get("supabase_form", "")
                if sform == "connection":
                    db.set_setting("supabase_enabled",
                                   "1" if request.form.get("supabase_enabled") else "0")
                if sform == "backup":
                    db.set_setting("auto_backup_enabled",
                                   "1" if request.form.get("auto_backup_enabled") else "0")
                backup_scheduler.notify_settings_changed()
            flash("تم حفظ الإعدادات بنجاح ✅", "success")
        # ابقَ على نفس التبويب بعد الحفظ
        return redirect(url_for("settings", tab=section or "general"))

    keys = ["teacher_name", "subject", "teacher_phone", "smtp_host", "smtp_port",
            "smtp_user", "report_email", "site_url", "supabase_url", "supabase_key",
            "supabase_enabled", "session_timeout",
            "auto_backup_enabled", "auto_backup_interval", "auto_backup_last",
            "auto_backup_last_status", "auto_backup_last_error", "auto_backup_next",
            "wa_mode", "wa_provider", "wa_api_url",
            "wa_api_token", "wa_phone_id", "wa_from",
            "ai_provider", "ai_model_openai", "ai_model_gemini", "ai_model_custom",
            "ai_base_custom", "ui_animations"]
    cfg = {k: db.get_setting(k) for k in keys}
    cfg["has_pass"] = bool(db.get_setting("smtp_pass"))
    # حالة مفاتيح مزوّدي الـ AI (نعرض "محفوظ" دون كشف المفتاح نفسه)
    cfg["has_key_openai"] = bool(db.get_setting("ai_key_openai") or db.get_setting("ai_api_key"))
    cfg["has_key_gemini"] = bool(db.get_setting("ai_key_gemini"))
    cfg["has_key_kimi"] = bool(db.get_setting("ai_key_kimi"))
    cfg["has_key_openrouter"] = bool(db.get_setting("ai_key_openrouter"))
    cfg["has_key_custom"] = bool(db.get_setting("ai_key_custom"))
    conn = db.get_db()
    admin_user = conn.execute("SELECT username, recovery_code FROM admin LIMIT 1").fetchone()
    conn.close()
    galleries = {slot: _gallery_get(slot) for slot in _GALLERY_SLOTS}
    actives = {slot: db.get_setting(slot, "") for slot in _GALLERY_SLOTS}
    teacher_layout = _login_layout_get("teacher") or {"images": [], "form_pos": "center"}
    parent_layout = _login_layout_get("parent") or {"images": [], "form_pos": "center"}
    return render_template("settings.html", cfg=cfg, admin_user=admin_user,
                           schema_sql=sb.SUPABASE_SCHEMA_SQL,
                           db_backend=db.backend(), galleries=galleries, actives=actives,
                           teacher_login_layout_obj=teacher_layout,
                           parent_login_layout_obj=parent_layout,
                           active_tab=request.args.get("tab", "account"))


# ---- Supabase actions ----
@app.route("/supabase/test")
@login_required
def supabase_test():
    ok, msg = sb.test_connection()
    flash(msg, "success" if ok else "error")
    return redirect(url_for("settings", tab="supabase"))


@app.route("/supabase/schema-check")
@login_required
def supabase_schema_check():
    """فحص توافق مخطط Supabase مع مخطط التطبيق (JSON) — قبل الاسترجاع/النسخ."""
    return jsonify(sb.schema_check())


@app.route("/supabase/migration.sql")
@login_required
def supabase_migration_sql():
    """تنزيل/عرض سكربت المزامنة الكامل لـ Supabase (يُبنى من المخطط الحالي)."""
    sql = sb.build_migration_sql()
    if request.args.get("download") == "1":
        return send_file(io.BytesIO(sql.encode("utf-8")), as_attachment=True,
                         download_name="supabase_migration.sql",
                         mimetype="text/plain; charset=utf-8")
    return Response(sql, mimetype="text/plain; charset=utf-8")


@app.route("/supabase/backup", methods=["GET", "POST"])
@login_required
def supabase_backup():
    """يبدأ نسخة احتياطية يدوية على دفعات في الخلفية، وترجع الواجهة فورًا.

    الرفع على دفعات قد يستغرق وقتًا مع البيانات الكبيرة، فلا نحجب الطلب: نشغّله في
    خيط خلفي وتتابع الواجهة التقدّم عبر /supabase/backup-progress. طلب AJAX يرجّع
    JSON، والطلب العادي يعود للإعدادات.
    """
    if backup_scheduler.start_backup_async():
        msg, cat = "بدأ الرفع على دفعات — تابع التقدّم بالأسفل.", "success"
    else:
        msg, cat = "هناك عملية نسخ جارية بالفعل.", "error"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"started": cat == "success", "message": msg})
    flash(msg, cat)
    return redirect(url_for("settings", tab="supabase"))


@app.route("/supabase/backup-progress")
@login_required
def supabase_backup_progress():
    """تقدّم النسخ الاحتياطي الحالي (JSON) — يُقرأ لحظيًا من الواجهة."""
    return jsonify(sb.get_backup_progress())


@app.route("/supabase/backup-status")
@login_required
def auto_backup_status():
    """حالة النسخ الاحتياطي التلقائي (JSON) لتحديث لوحة الإعدادات."""
    return jsonify({
        "enabled": db.get_setting("auto_backup_enabled", "0") == "1",
        "interval": db.get_setting("auto_backup_interval", "60"),
        "last": db.get_setting("auto_backup_last", ""),
        "last_status": db.get_setting("auto_backup_last_status", ""),
        "last_error": db.get_setting("auto_backup_last_error", ""),
        "next": db.get_setting("auto_backup_next", ""),
    })


@app.route("/supabase/restore")
@login_required
def supabase_restore():
    ok, msg = sb.restore_all()
    flash(msg, "success" if ok else "error")
    return redirect(url_for("settings", tab="supabase"))


@app.route("/schema.sql")
@login_required
def download_schema():
    dialect = "postgres" if request.args.get("d") == "pg" else "sqlite"
    sql = db.generate_schema_sql(dialect)
    fname = "schema_postgres.sql" if dialect == "postgres" else "schema.sql"
    return send_file(io.BytesIO(sql.encode("utf-8")), as_attachment=True,
                     download_name=fname, mimetype="text/plain; charset=utf-8")


# ---------------------------------------------------------------------------
# سجل رسائل الواتساب + اختبار الإرسال (تشخيص)
# ---------------------------------------------------------------------------
@app.route("/whatsapp/logs")
@login_required
def whatsapp_logs():
    conn = db.get_db()
    logs = conn.execute(
        "SELECT * FROM wa_logs ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()
    return render_template("wa_logs.html", logs=logs, wa_api_on=wa.api_mode(),
                           status=wa.config_status())


@app.route("/whatsapp/logs/clear")
@login_required
def whatsapp_logs_clear():
    conn = db.get_db()
    conn.execute("DELETE FROM wa_logs")
    conn.commit()
    conn.close()
    flash("تم مسح سجل الرسائل", "success")
    return redirect(url_for("whatsapp_logs"))


@app.route("/whatsapp/test", methods=["POST"])
@login_required
def whatsapp_test():
    """إرسال رسالة اختبارية للتحقق من إعدادات الـ API"""
    phone = request.form.get("phone", "").strip() or db.get_setting("teacher_phone", "")
    if not phone:
        flash("من فضلك أدخل رقمًا للاختبار أو اضبط رقم المدرس", "error")
        return redirect(url_for("whatsapp_logs"))
    if not wa.api_mode():
        flash("وضع الإرسال التلقائي (API) غير مفعّل. فعّله من الإعدادات > واتساب.", "error")
        return redirect(url_for("whatsapp_logs"))
    ok, resp = wa.send_api(phone, "رسالة اختبار من نظام إدارة المدرس ✅", msg_type="test")
    if ok:
        flash("تم إرسال رسالة الاختبار بنجاح ✅", "success")
    else:
        flash(f"فشل إرسال رسالة الاختبار: {resp}", "error")
    return redirect(url_for("whatsapp_logs"))


# ترحيل لمرة واحدة: دمج الخلفية القديمة المفردة في نظام تخطيط الدخول الموحّد
try:
    _migrate_bg_into_layout()
except Exception as _e:
    print("[boot] layout migrate:", _e)


if __name__ == "__main__":
    # المنفذ يُقرأ من متغير البيئة PORT (تحتاجه الاستضافات)، وإلا 5000 محليًا
    port = int(os.environ.get("PORT", 5000))
    # debug مُفعّل فقط محليًا، ومُطفأ تلقائيًا على الاستضافة
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(host="0.0.0.0", port=port, debug=debug)
