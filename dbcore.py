"""
طبقة قاعدة بيانات موحّدة تعمل مع:
  - SQLite   (محليًا للتجربة)         -> بدون أي إعداد
  - Postgres (Supabase على Vercel)   -> عند ضبط متغير DATABASE_URL

الاستخدام: نفس الدوال تشتغل في الحالتين. الفرق الوحيد داخليًا.

للتبديل: اضبط متغير البيئة DATABASE_URL برابط اتصال Postgres من Supabase
(Settings > Database > Connection string > URI). لو مش مضبوط، يستخدم SQLite.
"""
import os
import re

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

if USE_PG:
    # ملاحظة مهمة لبيئة serverless (Vercel):
    #   - لا نستخدم ConnectionPool: على Vercel كل استدعاء يتجمّد بعد الرد،
    #     فتبقى اتصالات الـ pool ميتة، كما أن إنشاء الـ pool وقت الاستيراد
    #     يفتح threads ويحاول الاتصال فورًا فيفشل إقلاع الـ function.
    #   - الطريقة الصحيحة مع Supabase Pooler: اتصال جديد لكل طلب (نفس نمط SQLite).
    import psycopg
    from psycopg.rows import dict_row
else:
    import sqlite3
    # على Vercel نظام الملفات للقراءة فقط عدا /tmp، لذا نستخدم /tmp افتراضيًا
    # عند غياب DATABASE_URL (وضع مؤقت — البيانات تُمسح؛ يُنصح بضبط Supabase).
    _default_dir = "/tmp" if os.environ.get("VERCEL") else os.path.dirname(__file__)
    _DATA_DIR = os.environ.get("DATA_DIR", _default_dir)
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except OSError:
        _DATA_DIR = "/tmp"
        os.makedirs(_DATA_DIR, exist_ok=True)
    SQLITE_PATH = os.path.join(_DATA_DIR, "teacher.db")


# ---------------------------------------------------------------------------
# غلاف موحّد للاتصال والاستعلام
# ---------------------------------------------------------------------------
class Cursor:
    """غلاف حول المؤشر يوفّر execute/fetchone/fetchall + lastrowid موحّد"""
    def __init__(self, conn, raw, is_pg):
        self._conn = conn
        self._raw = raw
        self._pg = is_pg
        self.lastrowid = None

    def execute(self, sql, params=()):
        q = _translate(sql, self._pg)
        if self._pg:
            added_returning = False
            # التقط lastrowid عبر RETURNING id — فقط للجداول اللي فيها عمود id
            if (_is_insert(q) and "returning" not in q.lower()
                    and _insert_has_id_table(q)):
                q = q.rstrip().rstrip(";") + " RETURNING id"
                added_returning = True
            self._raw.execute(q, params)
            if added_returning:
                try:
                    row = self._raw.fetchone()
                    self.lastrowid = row["id"] if row else None
                except Exception:
                    self.lastrowid = None
        else:
            self._raw.execute(q, params)
            self.lastrowid = self._raw.lastrowid
        return self

    def fetchone(self):
        row = self._raw.fetchone()
        return dict(row) if (row is not None and not self._pg) else row

    def fetchall(self):
        rows = self._raw.fetchall()
        if self._pg:
            return rows
        return [dict(r) for r in rows]


class Conn:
    """غلاف اتصال موحّد يدعم execute / commit / close + context manager"""
    def __init__(self):
        self._pg = USE_PG
        if USE_PG:
            # اتصال جديد لكل طلب (مناسب لـ serverless + Supabase Pooler).
            # prepare_threshold=None يعطّل الـ prepared statements التي تكسر
            # عند استخدام Supabase Transaction Pooler (pgbouncer / منفذ 6543).
            self._conn = psycopg.connect(
                DATABASE_URL,
                row_factory=dict_row,
                autocommit=False,
                prepare_threshold=None,
                connect_timeout=10,
                client_encoding="utf8",  # ضمان دعم العربية بغضّ النظر عن locale الخادم
            )
        else:
            # ملاحظة PythonAnywhere: نظام ملفاته (NFS) لا يتوافق مع WAL، فتقنية WAL
            # تسبب أخطاء "database is locked". لذا نستخدم journal_mode=DELETE (الأكثر
            # توافقًا مع NFS)، ونرفع مهلة الانتظار لتفادي القفل عند تزامن الطلبات.
            self._conn = sqlite3.connect(SQLITE_PATH, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            # busy_timeout: انتظر حتى 30 ثانية إذا كانت القاعدة مقفولة بدل رفع خطأ فورًا
            self._conn.execute("PRAGMA busy_timeout = 30000")
            self._conn.execute("PRAGMA foreign_keys = ON")
            # DELETE (بدل WAL): متوافق مع NFS على PythonAnywhere ولا يسبب قفل القاعدة
            self._conn.execute("PRAGMA journal_mode = DELETE")

    def execute(self, sql, params=()):
        cur = Cursor(self, self._conn.cursor(), self._pg)
        return cur.execute(sql, params)

    def cursor(self):
        return Cursor(self, self._conn.cursor(), self._pg)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    # دعم مدير السياق: with get_db() as conn: ... يغلق الاتصال تلقائيًا حتى عند
    # حدوث استثناء، فلا يبقى اتصال SQLite معلّقًا يقفل الملف (سبب database is locked).
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        self.close()
        return False

    # شبكة أمان: إذا نُسي إغلاق الاتصال، يُغلق عند جمع القمامة بدل بقائه يقفل الملف.
    def __del__(self):
        try:
            self._conn.close()
        except Exception:
            pass


def get_db():
    return Conn()


# ---------------------------------------------------------------------------
# ترجمة SQL بين SQLite و Postgres
# ---------------------------------------------------------------------------
def _is_insert(sql):
    return sql.lstrip().lower().startswith("insert")


# الجداول اللي مفتاحها ليس id (لا نضيف RETURNING id لها)
_NO_ID_TABLES = {"settings", "templates", "user_state"}


def _insert_has_id_table(sql):
    m = re.match(r"\s*insert\s+into\s+([\"\w]+)", sql, flags=re.I)
    if not m:
        return False
    table = m.group(1).strip('"').lower()
    return table not in _NO_ID_TABLES


def _translate(sql, is_pg):
    if not is_pg:
        return sql
    q = sql
    # علامات الاستفهام -> %s
    q = _qmark_to_pct(q)
    # أنواع SQLite -> Postgres
    q = q.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    q = q.replace("integer primary key autoincrement", "BIGSERIAL PRIMARY KEY")
    q = re.sub(r"\bAUTOINCREMENT\b", "", q, flags=re.I)
    # substr -> substring (Postgres يدعم substr فعليًا، لكن للأمان)
    # INSERT OR IGNORE -> ON CONFLICT DO NOTHING
    q = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", q, flags=re.I)
    if re.search(r"insert\s+or\s+ignore", sql, flags=re.I):
        q = q.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    # INSERT OR REPLACE -> نتركها تُدار بواسطة ON CONFLICT في الاستدعاءات
    q = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "INSERT INTO", q, flags=re.I)
    return q


def _qmark_to_pct(sql):
    """تحويل ? إلى %s مع تجاهل علامات الاستفهام داخل النصوص"""
    out = []
    in_s = False
    q = None
    for ch in sql:
        if ch in ("'", '"'):
            if not in_s:
                in_s = True
                q = ch
            elif q == ch:
                in_s = False
        if ch == "?" and not in_s:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


def backend():
    return "postgres" if USE_PG else "sqlite"
