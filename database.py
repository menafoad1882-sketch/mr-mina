"""
طبقة قاعدة البيانات - نظام إدارة المدرس
تعمل مع SQLite محليًا و Postgres (Supabase) على الاستضافة عبر dbcore.
"""
import os
import secrets
import string
from datetime import datetime
from werkzeug.security import generate_password_hash

import dbcore
from dbcore import get_db, backend

# للتوافق مع الكود القديم
DB_PATH = getattr(dbcore, "SQLITE_PATH", "")


# استثناءات موحّدة (SQLite أو Postgres)
if dbcore.USE_PG:
    import psycopg
    IntegrityError = psycopg.errors.UniqueViolation
    DBError = psycopg.Error
else:
    import sqlite3
    IntegrityError = sqlite3.IntegrityError
    DBError = sqlite3.Error


def schema_ready():
    """
    هل يوجد حساب أدمن بالفعل؟ (لتخطّي إنشاء الأدمن والبيانات التجريبية).
    نتحقق من وجود صف admin فعلي وليس مجرد وجود الجدول، لأن init_db
    ينشئ الجداول الفارغة دائمًا قبل هذا الفحص.
    """
    conn = get_db()
    try:
        row = conn.execute("SELECT 1 FROM admin LIMIT 1").fetchone()
        conn.close()
        return row is not None
    except DBError:
        conn.rollback()
        conn.close()
        return False


def gen_code(n=6):
    """كود رقمي للطالب"""
    return "".join(secrets.choice(string.digits) for _ in range(n))


def gen_pass(n=6):
    """باسورد بسيط للطالب (حروف وأرقام سهلة)"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def init_db():
    conn = get_db()
    c = conn.cursor()

    # حساب الأدمن (المدرس)
    c.execute("""
    CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        recovery_code TEXT,           -- كود استرجاع كلمة المرور
        created_at TEXT
    )""")

    # المجموعات / الفصول
    c.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        grade TEXT,
        fee REAL DEFAULT 0,
        year_id INTEGER,              -- العام الدراسي الذي تنتمي له المجموعة
        created_at TEXT
    )""")

    # الأعوام الدراسية (كل عام له بياناته المستقلة)
    c.execute("""
    CREATE TABLE IF NOT EXISTS academic_years (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,           -- مثال: 2026/2027
        start_date TEXT,
        end_date TEXT,
        is_current INTEGER DEFAULT 0, -- 1 = العام الحالي (واحد فقط)
        created_at TEXT
    )""")

    # الفصول الدراسية (الترمات) — تابعة لكل عام دراسي
    c.execute("""
    CREATE TABLE IF NOT EXISTS terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year_id INTEGER NOT NULL,
        name TEXT NOT NULL,           -- الترم الأول / الترم الثاني
        start_date TEXT,
        end_date TEXT,
        created_at TEXT,
        FOREIGN KEY(year_id) REFERENCES academic_years(id) ON DELETE CASCADE
    )""")

    # الطلاب (+ كود وباسورد للامتحان)
    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        parent_phone TEXT NOT NULL,
        grade TEXT,
        group_id INTEGER,
        notes TEXT,
        code TEXT UNIQUE,             -- كود دخول الامتحان / QR
        exam_password TEXT,           -- باسورد دخول الامتحان
        status TEXT DEFAULT 'active', -- active / inactive (حذف ناعم / تعطيل)
        deactivated_at TEXT,          -- تاريخ/وقت التعطيل
        deactivated_reason TEXT,      -- سبب التعطيل
        created_at TEXT,
        FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
    )""")

    # تسجيل الطالب في عام دراسي (طالب دائم + تسجيل مستقل لكل عام)
    c.execute("""
    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        year_id INTEGER NOT NULL,
        group_id INTEGER,             -- المجموعة الحالية للطالب في هذا العام
        status TEXT DEFAULT 'active', -- active / inactive لكل عام على حدة
        created_at TEXT,
        UNIQUE(student_id, year_id),
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
        FOREIGN KEY(year_id) REFERENCES academic_years(id) ON DELETE CASCADE,
        FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
    )""")

    # سجل ترحيل الطلاب بين المجموعات (داخل عام دراسي)
    c.execute("""
    CREATE TABLE IF NOT EXISTS group_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        year_id INTEGER NOT NULL,
        from_group_id INTEGER,
        to_group_id INTEGER,
        date TEXT,
        note TEXT,
        created_at TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
        FOREIGN KEY(year_id) REFERENCES academic_years(id) ON DELETE CASCADE
    )""")

    # الحصص
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER,
        year_id INTEGER,              -- العام الدراسي للحصة
        title TEXT,
        date TEXT NOT NULL,
        fee REAL DEFAULT 0,
        notes TEXT,
        created_at TEXT,
        FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
    )""")

    # الحضور والدفع + الواجب
    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        student_id INTEGER,           -- nullable: يبقى السجل المالي بعد حذف الطالب
        group_id INTEGER,             -- المجموعة وقت التسجيل (سجل تاريخي لا يتغيّر بالترحيل)
        student_name_snapshot TEXT,   -- اسم الطالب المحفوظ (للسجل المالي بعد الحذف)
        group_name_snapshot TEXT,     -- اسم المجموعة المحفوظ
        status TEXT NOT NULL,         -- present / late / absent
        homework TEXT DEFAULT 'none', -- done / not_done / none
        paid INTEGER DEFAULT 0,
        amount REAL DEFAULT 0,
        fee_exempt INTEGER DEFAULT 0, -- 1 = معفى من رسوم هذه الحصة (غير مطالَب بالدفع)
        exempt_reason TEXT,           -- سبب الإعفاء (يظهر للمدرس فقط)
        created_at TEXT,
        UNIQUE(session_id, student_id),
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
    )""")

    # الامتحانات (إلكتروني أو ورقي)
    c.execute("""
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        group_id INTEGER,
        year_id INTEGER,              -- العام الدراسي للامتحان
        total_marks REAL DEFAULT 0,
        duration INTEGER DEFAULT 30,
        is_online INTEGER DEFAULT 1,  -- 1 إلكتروني / 0 ورقي
        ai_provider TEXT,             -- المزوّد الذي ولّد الامتحان (openai/gemini/kimi)
        ai_model TEXT,                -- الموديل المستخدم فعليًا
        allow_retake INTEGER DEFAULT 0,   -- السماح بإعادة الامتحان
        max_attempts INTEGER DEFAULT 1,   -- عدد المحاولات المسموح بها (0 = غير محدود)
        final_policy TEXT DEFAULT 'highest', -- highest / latest / manual
        shuffle_questions INTEGER DEFAULT 0, -- ترتيب الأسئلة عشوائيًا لكل طالب
        shuffle_choices INTEGER DEFAULT 0,   -- ترتيب اختيارات mcq عشوائيًا
        created_at TEXT,
        FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
    )""")

    # أسئلة الامتحان الإلكتروني
    c.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        qtype TEXT DEFAULT 'mcq',     -- mcq/complete/truefalse/matching/ordering/compare/cause_effect/analysis/short
        option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
        correct TEXT,                 -- a/b/c/d للـ mcq
        answer_text TEXT,             -- الإجابة النموذجية للأنواع الأخرى
        extra TEXT,                   -- JSON لبيانات إضافية (توصيل/ترتيب...)
        category TEXT,                -- تصنيف تعليمي: direct/understand/apply/analyze/link/infer
        cognitive TEXT,              -- المستوى المعرفي: recall/understand/apply/analyze
        position INTEGER DEFAULT 0,   -- ترتيب السؤال داخل الامتحان
        marks REAL DEFAULT 1,
        FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE CASCADE
    )""")

    # بنك الأسئلة (لحفظ الأسئلة وإعادة استخدامها في امتحانات جديدة)
    c.execute("""
    CREATE TABLE IF NOT EXISTS question_bank (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        qtype TEXT DEFAULT 'mcq',
        option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
        correct TEXT,
        answer_text TEXT,
        marks REAL DEFAULT 1,
        grade TEXT,                   -- الصف
        subject TEXT,                 -- المادة
        unit TEXT,                    -- الوحدة
        lesson TEXT,                  -- الدرس
        difficulty TEXT,              -- easy/medium/hard
        created_at TEXT
    )""")

    # درجات / نتائج الامتحانات (إلكتروني أو ورقي)
    c.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        score REAL DEFAULT 0,
        auto_score REAL DEFAULT 0,
        status TEXT DEFAULT 'graded',
        question_scores TEXT,
        answers TEXT,
        taken_at TEXT,
        final_attempt_id INTEGER,     -- المحاولة المعتمدة (للسياسة اليدوية)
        UNIQUE(exam_id, student_id),
        FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE CASCADE,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    )""")

    # محاولات أداء الامتحان (كل محاولة تُحفظ منفصلة)
    c.execute("""
    CREATE TABLE IF NOT EXISTS exam_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        attempt_no INTEGER DEFAULT 1,
        score REAL DEFAULT 0,
        auto_score REAL DEFAULT 0,
        status TEXT DEFAULT 'graded',  -- graded / pending
        question_scores TEXT,
        answers TEXT,
        taken_at TEXT,
        FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE CASCADE,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    )""")

    # التذكيرات (متأخرات الدفع) - قابلة للجدولة بتاريخ ووقت ووسيلة إرسال
    c.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        session_id INTEGER,
        remaining REAL DEFAULT 0,      -- المبلغ المتبقي
        due_date TEXT,                 -- تاريخ استحقاق التذكير
        due_time TEXT DEFAULT '09:00', -- وقت الاستحقاق (HH:MM)
        method TEXT DEFAULT 'whatsapp',-- whatsapp / email
        status TEXT DEFAULT 'pending', -- pending / done / cancelled
        sent_at TEXT,                  -- وقت الإرسال الفعلي
        created_at TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )""")

    # الكتب/المذكرات المطبوعة
    c.execute("""
    CREATE TABLE IF NOT EXISTS booklets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,           -- nullable: يبقى السجل المالي بعد حذف الطالب
        year_id INTEGER,              -- العام الدراسي للكتاب/المذكرة
        student_name_snapshot TEXT,   -- اسم الطالب المحفوظ (للسجل المالي بعد الحذف)
        title TEXT,                    -- اسم الكتاب/المذكرة
        price REAL DEFAULT 0,          -- سعر الكتاب
        paid INTEGER DEFAULT 0,        -- هل تم الدفع؟
        amount REAL DEFAULT 0,         -- المبلغ المدفوع
        date TEXT,                     -- تاريخ الاستلام
        notes TEXT,
        created_at TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL
    )""")

    # سجل رسائل الواتساب (للتشخيص)
    c.execute("""
    CREATE TABLE IF NOT EXISTS wa_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        message TEXT,
        provider TEXT,
        success INTEGER DEFAULT 0,     -- 1 نجاح / 0 فشل
        status_code INTEGER DEFAULT 0, -- كود HTTP من الـ API
        error_type TEXT,               -- تصنيف الخطأ (credentials/cloudflare/...)
        msg_type TEXT,                 -- نوع الرسالة (test/exam_result/...)
        response TEXT,                 -- رد المزود / رسالة الخطأ
        created_at TEXT
    )""")

    # حسابات أولياء الأمور (بوابة ولي الأمر)
    c.execute("""
    CREATE TABLE IF NOT EXISTS parents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        phone TEXT,
        active INTEGER DEFAULT 1,       -- 1 مفعّل / 0 موقوف
        created_at TEXT
    )""")

    # ربط ولي الأمر بالطلاب (متعدد لمتعدد) - بدون تكرار سجلات الطلاب
    c.execute("""
    CREATE TABLE IF NOT EXISTS parent_students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        UNIQUE(parent_id, student_id),
        FOREIGN KEY(parent_id) REFERENCES parents(id) ON DELETE CASCADE,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    )""")

    # الإعدادات
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # حالة الخادم لكل مستخدم (مسودات كبيرة لا تتّسع في كوكي الجلسة 4KB)
    # تُخزَّن هنا بدل الكوكي: مسودة الامتحان المولّد + نص الدرس المستخرج.
    c.execute("""
    CREATE TABLE IF NOT EXISTS user_state (
        owner TEXT NOT NULL,
        skey TEXT NOT NULL,
        value TEXT,
        updated_at TEXT,
        PRIMARY KEY(owner, skey)
    )""")

    # القوالب الجاهزة للرسائل (قابلة للتعديل)
    c.execute("""
    CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,     -- present / late / absent / hw_done / hw_not / exam_result / level
        title TEXT,
        body TEXT
    )""")

    # تنبيهات تكرار الغياب المُرسَلة (لمنع التكرار: طالب+عام+الحد = فريد)
    c.execute("""
    CREATE TABLE IF NOT EXISTS absence_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        year_id INTEGER,
        threshold INTEGER NOT NULL,   -- عدد الغيابات الذي أُرسل عنده التنبيه
        absence_count INTEGER,        -- العدد الفعلي وقت الإرسال
        notified_site INTEGER DEFAULT 0,
        notified_wa INTEGER DEFAULT 0,
        created_at TEXT,
        UNIQUE(student_id, year_id, threshold),
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    )""")

    conn.commit()

    # إعدادات افتراضية
    defaults = {
        "teacher_name": "الأستاذ",
        "subject": "المادة",
        "teacher_phone": "",          # رقم واتساب المدرس (لتذكيرات المتأخرات)
        "smtp_host": "smtp.gmail.com",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_pass": "",
        "report_email": "",
        # مهلة انتهاء الجلسة (بالدقائق) لتسجيل الخروج التلقائي عند الخمول (0 = بلا مهلة)
        "session_timeout": "120",
        # Supabase
        "supabase_enabled": "0",
        "supabase_url": "",
        "supabase_key": "",
        # النسخ الاحتياطي التلقائي إلى Supabase
        "auto_backup_enabled": "0",
        "auto_backup_interval": "60",     # بالدقائق
        "auto_backup_last": "",           # آخر نسخة ناجحة (تاريخ/وقت)
        "auto_backup_last_status": "",     # success / failed
        "auto_backup_last_error": "",      # آخر خطأ (لو فشل)
        "auto_backup_next": "",           # موعد النسخة القادمة
        # OCR سحابي (اختياري) — بديل لـ tesseract على استضافات بلا دعم عربي
        "ocr_space_key": "",
        # تخصيص الواجهات (تُخزَّن كصور base64 داخل القاعدة لتعمل على أي استضافة)
        # ملاحظة: الخلفية القديمة المفردة (teacher_bg/parent_bg) أُزيلت نهائيًا؛
        # الخلفية والصور تُدار الآن حصريًا عبر «تخطيط صفحة الدخول» (JSON) أدناه.
        "parent_logo": "",
        "teacher_logo": "",
        # معارض الشعارات: عدة شعارات مخزّنة (JSON list من data URIs) لكل بوابة،
        # ويُختار «النشط» منها ليظهر فعليًا (teacher_logo/... أعلاه = النشط الحالي).
        "teacher_logo_gallery": "[]",
        "parent_logo_gallery": "[]",
        # نظام تخطيط صور تسجيل الدخول (متعدد الصور): JSON مستقل لكل بوابة.
        # يحوي: images:[{src,mode,x,y,scale,rotation,fit,z}], form_pos.
        # فارغ = يبقى التصميم الحالي (اختياري لا يكسر الدخول).
        "teacher_login_layout": "{}",
        "parent_login_layout": "{}",
        # الوضع العام للواجهة: light (نهاري) / dark (ليلي)
        "ui_theme": "light",
        # تنبيه تكرار غياب الطالب (قابل للضبط)
        "absence_alert_enabled": "0",       # مفعّل؟
        "absence_alert_threshold": "3",     # عدد مرات الغياب المطلوبة
        "absence_alert_notify_site": "1",   # إشعار داخل الموقع
        "absence_alert_notify_wa": "1",     # واتساب لولي الأمر
        "absence_alert_notify_email": "0",  # إيميل لولي الأمر
        # مستوى حركات الواجهة: off / simple / medium / full (الافتراضي بسيط)
        "ui_animations": "simple",
        # WhatsApp API (اختياري للمستقبل)
        "wa_mode": "link",            # link (روابط جاهزة) / api (تلقائي)
        "wa_provider": "ultramsg",    # ultramsg / meta / twilio (الأسهل: ultramsg)
        "wa_api_url": "",
        "wa_api_token": "",
        "wa_phone_id": "",
        "wa_from": "",
        "site_url": "http://127.0.0.1:5000",
        # الذكاء الاصطناعي (مولّد الامتحانات) - اختياري
        "ai_provider": "openai",      # openai / gemini / custom (المزوّد المختار)
        # مفاتيح مستقلة لكل مزوّد (لا يطغى أحدها على الآخر)
        "ai_key_openai": "",
        "ai_key_gemini": "",
        "ai_key_kimi": "",
        "ai_key_openrouter": "",
        "ai_key_custom": "",
        "ai_model_openai": "",         # فارغ = الافتراضي للمزوّد
        "ai_model_gemini": "",
        "ai_model_kimi": "",
        "ai_model_openrouter": "",
        "ai_model_custom": "",
        "ai_base_custom": "",          # Base URL للمزوّد المخصّص فقط
        # (متوافقية قديمة - لم تعد تُستخدم للحفظ)
        "ai_api_key": "",
        "ai_base_url": "",
        "ai_model": "",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))

    # قوالب رسائل افتراضية
    _seed_templates(c)
    conn.commit()
    conn.close()

    # ترحيل: إضافة أي أعمدة ناقصة على قواعد البيانات القديمة
    run_migrations()
    # ترحيل بيانات العام الدراسي (إنشاء عام افتراضي وربط البيانات القديمة به)
    ensure_academic_years()
    # ترحيل حالة النشر: الامتحانات الموجودة قبل هذه الميزة تبقى «منشورة»
    # (حتى لا تتوقف روابطها الحالية)، ويُنفَّذ مرة واحدة فقط.
    backfill_exam_status()
    # ترحيل: دمج حسابات أولياء الأمور المكرّرة بنفس رقم الواتساب (حساب واحد لكل ولي أمر)
    merge_duplicate_parents()


# جدول الأعمدة المتوقعة لكل جدول (للترحيل التلقائي / migration)
EXPECTED_COLUMNS = {
    "academic_years": {"name": "TEXT", "start_date": "TEXT", "end_date": "TEXT",
                       "is_current": "INTEGER DEFAULT 0", "created_at": "TEXT"},
    "terms": {"year_id": "INTEGER", "name": "TEXT", "start_date": "TEXT",
              "end_date": "TEXT", "created_at": "TEXT"},
    "enrollments": {"student_id": "INTEGER", "year_id": "INTEGER",
                    "group_id": "INTEGER", "status": "TEXT DEFAULT 'active'",
                    "created_at": "TEXT"},
    "group_transfers": {"student_id": "INTEGER", "year_id": "INTEGER",
                        "from_group_id": "INTEGER", "to_group_id": "INTEGER",
                        "date": "TEXT", "note": "TEXT", "created_at": "TEXT"},
    "groups": {"name": "TEXT", "grade": "TEXT", "fee": "REAL DEFAULT 0",
               "year_id": "INTEGER", "created_at": "TEXT"},
    "students": {"name": "TEXT", "phone": "TEXT", "parent_phone": "TEXT",
                 "grade": "TEXT", "group_id": "INTEGER", "notes": "TEXT",
                 "code": "TEXT", "exam_password": "TEXT",
                 "status": "TEXT DEFAULT 'active'", "deactivated_at": "TEXT",
                 "deactivated_reason": "TEXT", "created_at": "TEXT"},
    "sessions": {"group_id": "INTEGER", "year_id": "INTEGER", "title": "TEXT",
                 "date": "TEXT", "fee": "REAL DEFAULT 0", "notes": "TEXT",
                 "created_at": "TEXT"},
    "attendance": {"session_id": "INTEGER", "student_id": "INTEGER",
                   "group_id": "INTEGER", "student_name_snapshot": "TEXT",
                   "group_name_snapshot": "TEXT",
                   "status": "TEXT", "homework": "TEXT DEFAULT 'none'",
                   "paid": "INTEGER DEFAULT 0", "amount": "REAL DEFAULT 0",
                   # إعفاء الطالب من رسوم هذه الحصة (على مستوى الحصة/العام تلقائيًا).
                   # fee_exempt=1 يعني «غير مطالَب بالدفع» — لا يُنشأ تذكير ولا يُحتسب
                   # ضمن غير المدفوع، ولا يُعتبر متبقيًا. لا يمسّ الحضور/الواجب/الامتحان.
                   "fee_exempt": "INTEGER DEFAULT 0",
                   "exempt_reason": "TEXT",
                   "created_at": "TEXT"},
    "exams": {"title": "TEXT", "group_id": "INTEGER", "year_id": "INTEGER",
              "total_marks": "REAL DEFAULT 0",
              "duration": "INTEGER DEFAULT 30", "is_online": "INTEGER DEFAULT 1",
              "ai_provider": "TEXT", "ai_model": "TEXT",
              "allow_retake": "INTEGER DEFAULT 0", "max_attempts": "INTEGER DEFAULT 1",
              "final_policy": "TEXT DEFAULT 'highest'",
              "shuffle_questions": "INTEGER DEFAULT 0",
              "shuffle_choices": "INTEGER DEFAULT 0",
              # بيانات الامتحان الإضافية
              "subject": "TEXT", "grade": "TEXT", "term_id": "INTEGER",
              "exam_date": "TEXT",
              # إعدادات الأسئلة
              "num_questions": "INTEGER DEFAULT 0",   # 0 = كل الأسئلة، >0 = عيّنة عشوائية
              "show_question_number": "INTEGER DEFAULT 1",
              # إعدادات التصحيح / النتيجة للطالب
              "auto_grade": "INTEGER DEFAULT 1",
              "show_result_to_student": "INTEGER DEFAULT 1",
              "show_answers_to_student": "INTEGER DEFAULT 0",
              "show_score": "INTEGER DEFAULT 1",
              "show_percentage": "INTEGER DEFAULT 1",
              "show_grade_label": "INTEGER DEFAULT 1",
              "send_result_to_parent": "INTEGER DEFAULT 0",
              # إعدادات الطالب أثناء الأداء
              "one_question_per_page": "INTEGER DEFAULT 0",
              "prevent_back": "INTEGER DEFAULT 0",
              # إعدادات النشر
              "status": "TEXT DEFAULT 'draft'",   # draft | published | closed
              "open_at": "TEXT", "close_at": "TEXT",
              "created_at": "TEXT"},
    "questions": {"exam_id": "INTEGER", "text": "TEXT", "qtype": "TEXT DEFAULT 'mcq'",
                  "option_a": "TEXT", "option_b": "TEXT", "option_c": "TEXT",
                  "option_d": "TEXT", "correct": "TEXT", "answer_text": "TEXT",
                  "extra": "TEXT", "category": "TEXT", "cognitive": "TEXT",
                  "position": "INTEGER DEFAULT 0", "marks": "REAL DEFAULT 1"},
    "question_bank": {"text": "TEXT", "qtype": "TEXT DEFAULT 'mcq'",
                      "option_a": "TEXT", "option_b": "TEXT", "option_c": "TEXT",
                      "option_d": "TEXT", "correct": "TEXT", "answer_text": "TEXT",
                      "marks": "REAL DEFAULT 1", "grade": "TEXT", "subject": "TEXT",
                      "unit": "TEXT", "lesson": "TEXT", "difficulty": "TEXT",
                      # تصنيف موسّع لبنك الأسئلة
                      "stage": "TEXT", "term": "TEXT", "year_id": "INTEGER",
                      "extra": "TEXT",          # JSON (صور الخريطة/بيانات إضافية) base64
                      "dedup_hash": "TEXT",     # بصمة لمنع التكرار داخل نفس التصنيف
                      "created_at": "TEXT"},
    "results": {"exam_id": "INTEGER", "student_id": "INTEGER", "score": "REAL DEFAULT 0",
                "auto_score": "REAL DEFAULT 0", "status": "TEXT DEFAULT 'graded'",
                "question_scores": "TEXT", "answers": "TEXT", "taken_at": "TEXT",
                "final_attempt_id": "INTEGER"},
    "exam_attempts": {"exam_id": "INTEGER", "student_id": "INTEGER",
                      "attempt_no": "INTEGER DEFAULT 1", "score": "REAL DEFAULT 0",
                      "auto_score": "REAL DEFAULT 0", "status": "TEXT DEFAULT 'graded'",
                      "question_scores": "TEXT", "answers": "TEXT", "taken_at": "TEXT"},
    "reminders": {"student_id": "INTEGER", "session_id": "INTEGER",
                  "remaining": "REAL DEFAULT 0", "due_date": "TEXT",
                  "due_time": "TEXT DEFAULT '09:00'", "method": "TEXT DEFAULT 'whatsapp'",
                  "status": "TEXT DEFAULT 'pending'", "sent_at": "TEXT",
                  "created_at": "TEXT"},
    "booklets": {"student_id": "INTEGER", "year_id": "INTEGER",
                 "student_name_snapshot": "TEXT", "title": "TEXT",
                 "price": "REAL DEFAULT 0",
                 "paid": "INTEGER DEFAULT 0", "amount": "REAL DEFAULT 0",
                 "date": "TEXT", "notes": "TEXT", "created_at": "TEXT"},
    "wa_logs": {"phone": "TEXT", "message": "TEXT", "provider": "TEXT",
                "success": "INTEGER DEFAULT 0", "status_code": "INTEGER DEFAULT 0",
                "error_type": "TEXT", "msg_type": "TEXT",
                "response": "TEXT", "created_at": "TEXT"},
    "parents": {"username": "TEXT", "password_hash": "TEXT", "name": "TEXT",
                "phone": "TEXT", "active": "INTEGER DEFAULT 1", "created_at": "TEXT"},
    "parent_students": {"parent_id": "INTEGER", "student_id": "INTEGER"},
    "absence_alerts": {"student_id": "INTEGER", "year_id": "INTEGER",
                       "threshold": "INTEGER", "absence_count": "INTEGER",
                       "notified_site": "INTEGER DEFAULT 0",
                       "notified_wa": "INTEGER DEFAULT 0", "created_at": "TEXT"},
    "admin": {"username": "TEXT", "password_hash": "TEXT", "recovery_code": "TEXT",
              "created_at": "TEXT"},
}


def _existing_columns(conn, table):
    """يرجّع أسماء أعمدة جدول (يدعم SQLite و Postgres)"""
    try:
        if backend() == "postgres":
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=?", (table,)).fetchall()
            return {r["column_name"] for r in rows}
        else:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {r["name"] for r in rows}
    except DBError:
        conn.rollback()
        return set()


def run_migrations():
    """
    ترحيل تلقائي: يضمن وجود كل الأعمدة المتوقعة في كل جدول.
    آمن للتشغيل المتكرر، ويعمل على SQLite و Postgres/Supabase.
    يحل مشاكل قواعد البيانات القديمة (مثل عمود fee الناقص).
    """
    conn = get_db()
    try:
        for table, cols in EXPECTED_COLUMNS.items():
            existing = _existing_columns(conn, table)
            if not existing:
                continue  # الجدول غير موجود (init_db أنشأه بالفعل، أو سيُنشأ)
            for col, coltype in cols.items():
                if col not in existing:
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                        conn.commit()
                        print(f"[migration] أضيف عمود {table}.{col}")
                    except DBError:
                        conn.rollback()
    finally:
        conn.close()
    # حدّث ملف schema.sql تلقائيًا ليطابق البنية الحالية
    try:
        write_schema_file()
    except Exception as e:
        print("[schema] تعذّر تحديث schema.sql:", e)


# ---------------------------------------------------------------------------
# إدارة الأعوام الدراسية
# ---------------------------------------------------------------------------
def _default_year_name():
    """اسم عام دراسي افتراضي حسب التاريخ (سبتمبر بداية العام)."""
    d = datetime.now()
    y = d.year if d.month >= 9 else d.year - 1
    return f"{y}/{y+1}"


def ensure_academic_years():
    """يضمن وجود عام دراسي حالي واحد على الأقل، ويربط البيانات القديمة به.

    آمن للتشغيل المتكرر (idempotent). لا يحذف أي بيانات.
    """
    conn = get_db()
    try:
        # هل يوجد جدول academic_years؟ (قد لا يكون أُنشئ بعد في قواعد قديمة جدًا)
        cols = _existing_columns(conn, "academic_years")
        if not cols:
            conn.close()
            return
        row = conn.execute("SELECT COUNT(*) n FROM academic_years").fetchone()
        n = row["n"] if row else 0
        if n == 0:
            # أنشئ عامًا افتراضيًا وحدّده كحالي
            conn.execute(
                "INSERT INTO academic_years(name,start_date,end_date,is_current,created_at) "
                "VALUES(?,?,?,?,?)",
                (_default_year_name(), "", "", 1, now()))
            conn.commit()
        # تأكّد من وجود عام حالي واحد
        cur = conn.execute("SELECT id FROM academic_years WHERE is_current=1 LIMIT 1").fetchone()
        if not cur:
            first = conn.execute("SELECT id FROM academic_years ORDER BY id LIMIT 1").fetchone()
            if first:
                conn.execute("UPDATE academic_years SET is_current=1 WHERE id=?", (first["id"],))
                conn.commit()
                cur = first
        year_id = (cur or conn.execute(
            "SELECT id FROM academic_years WHERE is_current=1 LIMIT 1").fetchone())["id"]

        # اربط البيانات القديمة التي بلا عام دراسي بالعام الحالي (backfill)
        for table in ("groups", "sessions", "exams", "booklets"):
            tcols = _existing_columns(conn, table)
            if "year_id" in tcols:
                conn.execute(
                    f"UPDATE {table} SET year_id=? WHERE year_id IS NULL", (year_id,))
        conn.commit()

        # backfill: attendance.group_id من الحصة (المجموعة وقت التسجيل)
        acols = _existing_columns(conn, "attendance")
        if "group_id" in acols:
            conn.execute(
                "UPDATE attendance SET group_id=("
                "SELECT s.group_id FROM sessions s WHERE s.id=attendance.session_id) "
                "WHERE group_id IS NULL")
            conn.commit()

        # backfill: إنشاء تسجيلات (enrollments) للطلاب الحاليين في العام الحالي
        # نعتمد على students.group_id و students.status الحاليين.
        scols = _existing_columns(conn, "students")
        if scols:
            students = conn.execute("SELECT id, group_id, status FROM students").fetchall()
            for st in students:
                exists = conn.execute(
                    "SELECT 1 FROM enrollments WHERE student_id=? AND year_id=?",
                    (st["id"], year_id)).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO enrollments(student_id,year_id,group_id,status,created_at) "
                        "VALUES(?,?,?,?,?)",
                        (st["id"], year_id, st["group_id"],
                         st["status"] or "active", now()))
            conn.commit()
    finally:
        conn.close()


def backfill_exam_status():
    """يضبط الامتحانات القديمة (التي أُنشئت قبل ميزة النشر) على «منشورة».

    يُنفَّذ مرة واحدة فقط (يُعلَّم بمفتاح في settings) حتى لا يطغى على
    اختيار المدرس لاحقًا. آمن على SQLite و Postgres، ولا يحذف بيانات.
    """
    conn = get_db()
    try:
        cols = _existing_columns(conn, "exams")
        if "status" not in cols:
            conn.close()
            return
        done = conn.execute(
            "SELECT value FROM settings WHERE key='exam_status_backfilled'").fetchone()
        if done and (done["value"] == "1"):
            conn.close()
            return
        # كل الامتحانات الحالية وقت الترحيل تُعتبر منشورة (كانت تعمل بالفعل)
        conn.execute("UPDATE exams SET status='published' "
                     "WHERE status IS NULL OR status='draft'")
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('exam_status_backfilled','1') "
            "ON CONFLICT(key) DO UPDATE SET value='1'")
        conn.commit()
        print("[migration] ضُبطت حالة الامتحانات القديمة على «منشورة»")
    except DBError:
        conn.rollback()
    finally:
        conn.close()


def _norm_phone_db(p):
    """تطبيع رقم الهاتف للمقارنة (أرقام فقط + إزالة البادئات الدولية)."""
    import re as _re
    d = _re.sub(r"\D", "", p or "")
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("20") and len(d) > 10:
        d = d[2:]
    return d


def merge_duplicate_parents():
    """ترحيل لمرة واحدة: يدمج حسابات أولياء الأمور المكرّرة بنفس رقم الواتساب في حساب
    واحد وينقل كل الأبناء إليه — دون حذف أي طالب أو بياناته. آمن و idempotent.
    يعمل ضمن تسلسل init_db (اتصال واحد) لتفادي أقفال SQLite.
    """
    conn = get_db()
    try:
        cols = _existing_columns(conn, "parents")
        if not cols:
            conn.close()
            return
        done = conn.execute(
            "SELECT value FROM settings WHERE key='parents_merged'").fetchone()
        if done and done["value"] == "1":
            conn.close()
            return
        parents = conn.execute("SELECT * FROM parents ORDER BY id").fetchall()
        by_phone = {}
        for p in parents:
            key = _norm_phone_db(p["phone"])
            if not key:
                srow = conn.execute(
                    "SELECT s.parent_phone FROM parent_students ps "
                    "JOIN students s ON ps.student_id=s.id "
                    "WHERE ps.parent_id=? AND s.parent_phone<>'' LIMIT 1",
                    (p["id"],)).fetchone()
                key = _norm_phone_db(srow["parent_phone"]) if srow else ""
            if not key:
                continue
            by_phone.setdefault(key, []).append(p)
        merged = 0
        for key, group in by_phone.items():
            if len(group) < 2:
                continue
            keeper = group[0]
            for dup in group[1:]:
                kids = conn.execute(
                    "SELECT student_id FROM parent_students WHERE parent_id=?",
                    (dup["id"],)).fetchall()
                for k in kids:
                    conn.execute(
                        "INSERT INTO parent_students(parent_id,student_id) VALUES(?,?) "
                        "ON CONFLICT(parent_id,student_id) DO NOTHING",
                        (keeper["id"], k["student_id"]))
                conn.execute("DELETE FROM parent_students WHERE parent_id=?", (dup["id"],))
                conn.execute("DELETE FROM parents WHERE id=?", (dup["id"],))
                merged += 1
            if not (keeper["phone"] or "").strip():
                conn.execute("UPDATE parents SET phone=? WHERE id=?", (key, keeper["id"]))
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('parents_merged','1') "
            "ON CONFLICT(key) DO UPDATE SET value='1'")
        conn.commit()
        if merged:
            print(f"[migration] دُمج {merged} حساب ولي أمر مكرّر بنفس رقم الواتساب")
    except DBError:
        conn.rollback()
    finally:
        conn.close()


def get_current_year_id():
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM academic_years WHERE is_current=1 LIMIT 1").fetchone()
        if row:
            return row["id"]
        row = conn.execute("SELECT id FROM academic_years ORDER BY id LIMIT 1").fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def set_current_year(year_id):
    conn = get_db()
    try:
        conn.execute("UPDATE academic_years SET is_current=0")
        conn.execute("UPDATE academic_years SET is_current=1 WHERE id=?", (year_id,))
        conn.commit()
    finally:
        conn.close()


# ترتيب الجداول لاحترام المفاتيح الأجنبية
_TABLE_ORDER = ["admin", "academic_years", "terms", "groups", "students", "enrollments",
                "group_transfers", "sessions", "attendance",
                "exams", "questions", "question_bank", "results", "exam_attempts",
                "reminders", "booklets", "wa_logs", "parents", "parent_students",
                "absence_alerts", "settings", "user_state", "templates"]

# الجداول ذات مفاتيح خاصة (ليست id تسلسلي)
_SPECIAL_PK = {
    "settings": "key TEXT PRIMARY KEY,\n    value TEXT",
    "templates": None,  # لها id تسلسلي عادي (يُبنى من EXPECTED إن وُجد) — تُدار أدناه
}

# قيود UNIQUE المركّبة لكل جدول (المفتاح الطبيعي) — لازمة لعمل upsert/النسخ الاحتياطي.
# تُضاف داخل CREATE TABLE في schema.sql/schema_postgres.sql وتُطابق ما في Supabase.
_TABLE_UNIQUE = {
    "parent_students": ["parent_id", "student_id"],
    "absence_alerts": ["student_id", "year_id", "threshold"],
}


def _sqlite_type(coltype):
    return coltype


def _pg_type(coltype):
    t = coltype.upper()
    if t.startswith("INTEGER"):
        return coltype.replace("INTEGER", "BIGINT", 1)
    return coltype


def generate_schema_sql(dialect="sqlite"):
    """
    يبني سكربت SQL كامل (إنشاء الجداول) مطابقًا لبنية التطبيق الحالية.
    dialect: 'sqlite' أو 'postgres'.
    مصدر الحقيقة: EXPECTED_COLUMNS (+ الأعمدة الخاصة).
    """
    is_pg = dialect == "postgres"
    pk = "BIGSERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    typ = _pg_type if is_pg else _sqlite_type

    lines = [
        "-- ملف مخطط قاعدة البيانات (مولّد تلقائيًا من التطبيق)",
        f"-- اللهجة: {dialect}",
        "-- يُعاد توليده تلقائيًا عند أي تعديل في بنية قاعدة البيانات.",
        "",
    ]

    # جداول خاصة المفتاح
    special = {
        "settings": [
            "CREATE TABLE IF NOT EXISTS settings (",
            "    key TEXT PRIMARY KEY,",
            "    value TEXT",
            ");", ""],
        "templates": [
            f"CREATE TABLE IF NOT EXISTS templates (",
            f"    id {pk},",
            "    key TEXT UNIQUE NOT NULL,",
            "    title TEXT,",
            "    body TEXT",
            ");", ""],
        "user_state": [
            "CREATE TABLE IF NOT EXISTS user_state (",
            "    owner TEXT NOT NULL,",
            "    skey TEXT NOT NULL,",
            "    value TEXT,",
            "    updated_at TEXT,",
            "    PRIMARY KEY(owner, skey)",
            ");", ""],
    }

    for table in _TABLE_ORDER:
        if table in special:
            lines += special[table]
            continue
        cols = EXPECTED_COLUMNS.get(table)
        if not cols:
            continue
        parts = [f"    id {pk}"]
        for col, ct in cols.items():
            parts.append(f"    {col} {typ(ct)}")
        # قيد UNIQUE مركّب (المفتاح الطبيعي) إن وُجد للجدول
        if table in _TABLE_UNIQUE:
            parts.append("    UNIQUE(" + ", ".join(_TABLE_UNIQUE[table]) + ")")
        stmt = f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(parts) + "\n);"
        lines.append(stmt)
        lines.append("")

    return "\n".join(lines)


def write_schema_file():
    """يكتب ملفي schema (sqlite + postgres) في مجلد المشروع."""
    base = os.path.dirname(__file__)
    sqlite_sql = generate_schema_sql("sqlite")
    pg_sql = generate_schema_sql("postgres")
    with open(os.path.join(base, "schema.sql"), "w", encoding="utf-8") as f:
        f.write(sqlite_sql)
    with open(os.path.join(base, "schema_postgres.sql"), "w", encoding="utf-8") as f:
        f.write(pg_sql)


def _seed_templates(c):
    tpls = [
        ("present", "حضور الطالب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نفيدكم بحضور الطالب/ة حصة مادة {subject} بتاريخ {date}. ✅\n\n"
         "مع تحيات {teacher}"),
        ("late", "تأخر الطالب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نفيدكم بأن الطالب/ة حضر متأخرًا لحصة مادة {subject} بتاريخ {date}. ⏰\n\n"
         "مع تحيات {teacher}"),
        ("absent", "غياب الطالب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نفيدكم بغياب الطالب/ة عن حصة مادة {subject} بتاريخ {date}. ❗\n"
         "برجاء المتابعة.\n\nمع تحيات {teacher}"),
        ("hw_done", "أداء الواجب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نفيدكم بأن الطالب/ة قام بأداء الواجب بتاريخ {date}. 👏\n\n"
         "مع تحيات {teacher}"),
        ("hw_not", "عدم أداء الواجب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نفيدكم بأن الطالب/ة لم يقم بأداء الواجب بتاريخ {date}. 📝\n"
         "برجاء المتابعة.\n\nمع تحيات {teacher}"),
        ("exam_result", "نتيجة امتحان",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نتيجة امتحان *{exam}* في مادة {subject}:\n"
         "- الدرجة: {score} من {total} ({pct}%)\n\n"
         "مع تحيات {teacher}"),
        ("level", "مستوى الطالب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "تقرير مستوى الطالب في مادة {subject}:\n"
         "- متوسط الدرجات: {avg}%\n- التقييم العام: {level}\n- نسبة الحضور: {att}%\n\n"
         "مع تحيات {teacher}"),
        ("session_full", "تقرير الحصة الكامل",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "تقرير حصة مادة {subject} بتاريخ {date}:\n"
         "- الحالة: {status}\n- الواجب: {homework}\n{payment}\n\n"
         "مع تحيات {teacher}"),
        ("payment", "تأكيد الدفع",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نفيدكم باستلام مبلغ {amount} جنيه عن حصة مادة {subject} بتاريخ {date}. ✅\n\n"
         "مع تحيات {teacher}"),
        ("payment_reminder", "تذكير بمتأخرات الدفع",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نود تذكيركم بوجود مبلغ متبقٍّ قدره {remaining} جنيه عن مادة {subject}.\n"
         "برجاء التكرم بسداده. شكرًا لتعاونكم.\n\n"
         "مع تحيات {teacher}"),
        ("monthly_financial", "التقرير المالي الشهري",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "التقرير المالي عن الفترة ({period}) لمادة {subject}:\n"
         "- إجمالي المدفوع: {paid_total} جنيه\n"
         "- المتبقي: {remaining} جنيه\n\n"
         "مع تحيات {teacher}"),
        ("monthly_attendance", "تقرير الحضور الشهري",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "تقرير الحضور عن الفترة ({period}) لمادة {subject}:\n"
         "- عدد مرات الحضور: {present_count}\n"
         "- عدد مرات التأخير: {late_count}\n"
         "- عدد مرات الغياب: {absent_count}\n"
         "- نسبة الحضور: {att}%\n\n"
         "مع تحيات {teacher}"),
        ("hw_incomplete", "واجب غير مكتمل",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "نفيدكم بأن الطالب/ة أدّى الواجب بشكل غير مكتمل بتاريخ {date}. ⚠️\n"
         "برجاء المتابعة.\n\nمع تحيات {teacher}"),
        ("absence_alert", "تنبيه تكرار الغياب",
         "ولي الأمر الكريم،\n"
         "نحيطكم علمًا بأن الطالب/ة *{student}*\n"
         "قد تغيّب عن الحضور عدد {absence_count} مرات في مادة {subject}.\n\n"
         "يرجى متابعة انتظام الطالب في الحضور.\n\nمع تحيات {teacher}"),
        ("student_login", "بيانات دخول الطالب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "بيانات دخول الطالب لمنصة مادة {subject}:\n\n"
         "اسم المستخدم / كود الدخول:\n{code}\n\n"
         "كلمة المرور:\n{password}\n\n"
         "يُستخدم الكود لتسجيل الحضور (QR) ودخول الامتحانات الإلكترونية.\n\n"
         "مع تحيات {teacher}"),
        ("qr_code", "كود QR للطالب",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "كود QR الخاص بالطالب/ة في مادة {subject}:\n\n"
         "كود الطالب: {code}\n\n"
         "رابط عرض الكود (QR):\n{qr_url}\n\n"
         "مع تحيات {teacher}"),
        ("parent_login", "بيانات دخول ولي الأمر",
         "السلام عليكم، ولي أمر الطالب/ة *{student}*\n"
         "بيانات الدخول لبوابة أولياء الأمور لمتابعة أبنائكم:\n\n"
         "اسم المستخدم:\n{username}\n\n"
         "كلمة المرور:\n{password}\n\n"
         "رابط البوابة:\n{portal_url}\n\n"
         "مع تحيات {teacher}"),
    ]
    for key, title, body in tpls:
        c.execute("INSERT OR IGNORE INTO templates(key,title,body) VALUES(?,?,?)",
                  (key, title, body))


def ensure_admin():
    """إنشاء حساب أدمن افتراضي أول مرة (آمن مع عدة workers)"""
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) n FROM admin").fetchone()["n"]
    if n == 0:
        recovery = gen_pass(8)
        try:
            # username فريد (UNIQUE) فلو worker تاني سبقنا، الإدخال هيفشل بأمان
            conn.execute(
                "INSERT INTO admin(username,password_hash,recovery_code,created_at) VALUES(?,?,?,?)",
                ("admin", generate_password_hash("admin123"), recovery, now()))
            conn.commit()
        except IntegrityError:
            conn.close()
            return
        print("=" * 50)
        print("تم إنشاء حساب المدرس الافتراضي:")
        print("  اسم المستخدم: admin")
        print("  كلمة المرور: admin123")
        print(f"  كود الاسترجاع: {recovery}")
        print("  (غيّر كلمة المرور من صفحة الإعدادات)")
        print("=" * 50)
    conn.close()


def get_setting(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()
    conn.close()


def set_state(owner, skey, value):
    """يخزّن حالة/مسودة كبيرة للمستخدم في قاعدة البيانات (بدل كوكي الجلسة)."""
    conn = get_db()
    conn.execute(
        "INSERT INTO user_state(owner,skey,value,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(owner,skey) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at",
        (str(owner), str(skey), value if value is not None else None, now()))
    conn.commit()
    conn.close()


def get_state(owner, skey, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM user_state WHERE owner=? AND skey=?",
                       (str(owner), str(skey))).fetchone()
    conn.close()
    return row["value"] if row and row["value"] is not None else default


def clear_state(owner, skey):
    conn = get_db()
    conn.execute("DELETE FROM user_state WHERE owner=? AND skey=?",
                 (str(owner), str(skey)))
    conn.commit()
    conn.close()


def get_template(key):
    conn = get_db()
    row = conn.execute("SELECT * FROM templates WHERE key=?", (key,)).fetchone()
    conn.close()
    return row


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def assign_student_credentials(conn, student_id):
    """توليد كود وباسورد فريد للطالب"""
    while True:
        code = gen_code(6)
        exists = conn.execute("SELECT 1 FROM students WHERE code=?", (code,)).fetchone()
        if not exists:
            break
    pw = gen_pass(6)
    conn.execute("UPDATE students SET code=?, exam_password=? WHERE id=?",
                 (code, pw, student_id))
    return code, pw


def seed_demo():
    conn = get_db()
    c = conn.cursor()
    # لو فيه طلاب بالفعل، أو حصل تسابق مع worker تاني، اخرج بأمان
    try:
        if c.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"] > 0:
            conn.close()
            return
    except DBError:
        conn.close()
        return
    c.execute("INSERT INTO groups(name,grade,fee,created_at) VALUES(?,?,?,?)",
              ("مجموعة السبت - رياضة", "الصف الثالث الثانوي", 50, now()))
    g1 = c.lastrowid
    c.execute("INSERT INTO groups(name,grade,fee,created_at) VALUES(?,?,?,?)",
              ("مجموعة الأحد", "الصف الثاني الثانوي", 40, now()))
    g2 = c.lastrowid
    students = [
        ("أحمد محمد علي", "01000000001", "01111111101", "الصف الثالث الثانوي", g1),
        ("سارة إبراهيم", "01000000002", "01111111102", "الصف الثالث الثانوي", g1),
        ("محمود حسن", "01000000003", "01111111103", "الصف الثالث الثانوي", g1),
        ("منة الله خالد", "01000000004", "01111111104", "الصف الثاني الثانوي", g2),
        ("يوسف عبد الله", "01000000005", "01111111105", "الصف الثاني الثانوي", g2),
    ]
    try:
        for name, ph, pph, grade, gid in students:
            c.execute("INSERT INTO students(name,phone,parent_phone,grade,group_id,created_at) "
                      "VALUES(?,?,?,?,?,?)", (name, ph, pph, grade, gid, now()))
            assign_student_credentials(c, c.lastrowid)
        conn.commit()
    except DBError:
        pass
    conn.close()
    # اربط المجموعات والطلاب الجديدة بالعام الدراسي الحالي (backfill + enrollments)
    ensure_academic_years()


if __name__ == "__main__":
    init_db()
    ensure_admin()
    seed_demo()
    print("Database initialized at", DB_PATH)
