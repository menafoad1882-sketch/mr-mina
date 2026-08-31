"""
تكامل Supabase (اختياري) - نظام هجين
Optional Supabase cloud backup/sync.

الفكرة: التطبيق يشتغل محليًا بـ SQLite دايمًا (سريع وبدون إنترنت).
لو المدرس فعّل Supabase من الإعدادات، بننسخ نسخة من الجداول للسحابة
عشان البيانات متضيعش ويقدر يستعيدها.

هذا الملف يعمل بأمان حتى لو مكتبة supabase مش متثبتة أو الإعدادات فاضية.
"""
import database as db

# كل الجداول المتزامنة مع Supabase (المصدر الوحيد للحقيقة: database.EXPECTED_COLUMNS)
# ملاحظة: parent_students مفتاحه مركّب، والبقية مفتاحها id.
TABLES = ["academic_years", "terms", "groups", "students", "enrollments",
          "group_transfers", "sessions", "attendance",
          "exams", "questions", "question_bank", "results", "exam_attempts",
          "reminders", "booklets", "wa_logs", "parents", "parent_students",
          "absence_alerts", "settings"]


def _local_columns(conn, table):
    """أسماء أعمدة الجدول في قاعدة البيانات المحلية (المصدر المعتمد للأعمدة)."""
    try:
        return db._existing_columns(conn, table)
    except Exception:
        return set()


def _client():
    """يرجّع عميل Supabase لو مفعّل ومضبوط، وإلا None"""
    if db.get_setting("supabase_enabled", "0") != "1":
        return None
    url = db.get_setting("supabase_url", "").strip()
    key = db.get_setting("supabase_key", "").strip()
    if not (url and key):
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        print("[Supabase] تعذّر الاتصال:", e)
        return None


def is_enabled():
    return _client() is not None


def test_connection():
    """اختبار الاتصال - يرجّع (نجاح؟, رسالة)"""
    if db.get_setting("supabase_enabled", "0") != "1":
        return False, "Supabase غير مُفعّل"
    url = db.get_setting("supabase_url", "").strip()
    key = db.get_setting("supabase_key", "").strip()
    if not (url and key):
        return False, "URL أو المفتاح فاضي"
    try:
        from supabase import create_client
        client = create_client(url, key)
        # محاولة قراءة بسيطة
        client.table("students").select("id").limit(1).execute()
        return True, "تم الاتصال بنجاح ✅"
    except Exception as e:
        return False, f"فشل الاتصال: {e}"


def _schema_hint(err):
    """رسالة مساعدة عند أخطاء المخطط في Supabase"""
    txt = str(err)
    # خطأ نوع UUID: الجداول أُنشئت بمفتاح uuid بدل bigint
    if "uuid" in txt.lower() or "22P02" in txt:
        return ("⚠️ جداول Supabase تستخدم نوع UUID للمعرّف (id)، لكن التطبيق يستخدم أرقامًا صحيحة. "
                "الحل: افتح Supabase > SQL Editor واحذف الجداول القديمة ثم شغّل «كود إنشاء الجداول» "
                "الموجود بالأسفل (ينشئها بمعرّف bigint المتوافق). "
                "كود الحذف: drop table if exists reminders, results, questions, exams, attendance, "
                "sessions, students, groups, booklets, wa_logs cascade;")
    # خطأ عمود ناقص
    if "PGRST204" in txt or "schema cache" in txt or "column" in txt.lower():
        return ("⚠️ مخطط قاعدة بيانات Supabase قديم أو ناقص عمود. "
                "من فضلك افتح Supabase > SQL Editor وشغّل «كود إنشاء الجداول» "
                "الموجود بالأسفل (يضيف الأعمدة الناقصة تلقائيًا بما فيها fee)، ثم حاول مرة أخرى.")
    return ""


# ═══════════════════════════════════════════════════════════════════════
# المصدر الوحيد للحقيقة لمفاتيح التعارض (ON CONFLICT / upsert)
# ═══════════════════════════════════════════════════════════════════════
# كل جدول له «مفتاح تعارض» (conflict target): مجموعة الأعمدة التي يُطابَق عليها
# السجل أثناء upsert (تحديث الموجود بدل تكرار). هذا القاموس يقود ثلاثة أشياء
# معًا فلا يحدث أي تعارض بينها إطلاقًا:
#   1) backup_all      → يمرّر on_conflict = هذه الأعمدة.
#   2) build_migration_sql → ينشئ قيد UNIQUE مطابقًا لكل مفتاح غير id.
#   3) schema_check     → يتحقّق أن Supabase فيه قيد PK/UNIQUE مطابق لكل مفتاح.
# القاعدة: الجداول غير المذكورة هنا مفتاحها id (وهو PRIMARY KEY دائمًا → لا يحتاج قيدًا).
# لماذا مفاتيح طبيعية لهذه الجداول تحديدًا؟
#   - parent_students: مفتاح ربط مركّب (لا id دلالي).
#   - absence_alerts : تنبيه واحد لكل (طالب + عام + حد) — منع التكرار المنطقي،
#     والمطابقة على id قد تُنشئ صفًا بنفس المفتاح الطبيعي فيكسر القيد الجديد.
#   - settings       : مفتاحه الطبيعي key (وقد يكون عمودًا عاديًا في جداول قديمة).
_CONFLICT_KEYS = {
    "parent_students": ["parent_id", "student_id"],
    "absence_alerts": ["student_id", "year_id", "threshold"],
    "settings": ["key"],
    # بقية الجداول → ["id"] (PRIMARY KEY)
}

# أسماء ثابتة للقيود (لتفادي إعادة الإنشاء والتكرار عند تشغيل السكربت مرارًا).
_CONSTRAINT_NAMES = {
    "parent_students": "uq_parent_students_pair",
    "absence_alerts": "uq_absence_alert",
    "settings": "uq_settings_key",
}


def _conflict_cols(table):
    """أعمدة مفتاح التعارض لجدول ما (افتراضيًا id)."""
    return list(_CONFLICT_KEYS.get(table, ["id"]))


def _required_constraints():
    """يبني خريطة القيود المطلوبة على Supabase من مفاتيح التعارض نفسها.

    كل جدول مفتاح تعارضه ليس id يحتاج قيد UNIQUE مطابقًا (وإلا 42P10).
    id مستثنى لأنه PRIMARY KEY دائمًا. المصدر الوحيد: _CONFLICT_KEYS.
    يرجّع {table: (constraint_name, [cols])}.
    """
    out = {}
    for table in TABLES:
        cols = _conflict_cols(table)
        if cols == ["id"]:
            continue  # id هو PK دائمًا — لا حاجة لقيد إضافي
        name = _CONSTRAINT_NAMES.get(table, "uq_" + table)
        out[table] = (name, cols)
    return out


# قيود UNIQUE المطلوبة على Supabase (مشتقّة من مفاتيح التعارض — لا تكرار للحقيقة).
_UNIQUE_CONSTRAINTS = _required_constraints()

# مفتاح المطابقة الثابت أثناء الاسترجاع (UPSERT idempotent) = نفس مفتاح التعارض.
_KEY_COLUMNS = {t: _conflict_cols(t) for t in _CONFLICT_KEYS}

# ═══════════════════════════════════════════════════════════════════════
# جداول تُستعاد بمفتاحها الطبيعي (وليس id) — إصلاح جذري لخطأ الاسترجاع
# «UNIQUE constraint failed: enrollments.student_id, enrollments.year_id»
# ═══════════════════════════════════════════════════════════════════════
# السبب الجذري: هذه الجداول لها قيد UNIQUE طبيعي (المفتاح الحقيقي للسجل)، لكن
# الاسترجاع كان يطابق بـ id ويُدرج السجل بـ id الوارد من Supabase. فإن اختلف id
# بين Supabase والقاعدة المحلية (مثلاً بعد إعادة زرع/تهيئة) بينما المفتاح الطبيعي
# نفسه موجود محليًا، يصطدم الإدراج بقيد UNIQUE الطبيعي → يفشل الاسترجاع.
# الحل الصحيح (بلا فقد بيانات): نطابق بالمفتاح الطبيعي، ونُسقط id الوارد فنترك
# القاعدة المحلية تحتفظ بـ id الخاص بها. هذا آمن تمامًا لأن id هذه الجداول
# غير مُشار إليه من أي جدول ابن (تحقّقنا: لا FOREIGN KEY يشير إليها).
# النتيجة: idempotent (تحديث الموجود، بلا تكرار، بلا اصطدام).
_NATURAL_KEY_TABLES = {
    "enrollments": ["student_id", "year_id"],
    "attendance": ["session_id", "student_id"],
    "results": ["exam_id", "student_id"],
    "absence_alerts": ["student_id", "year_id", "threshold"],
    "parent_students": ["parent_id", "student_id"],
}


def _upsert_row(conn, table, row, key_cols):
    """يُدرج أو يُحدّث سجلًا حسب مفتاح ثابت — idempotent وآمن للجداول ذات الأبناء.

    السبب الجذري لتكرار/فقد البيانات عند الاسترجاع المتكرر:
    - INSERT OR REPLACE على Postgres كان يتحوّل إلى INSERT عادي (بلا معالجة تعارض)
      فيكرّر السجلات أو يفشل بمفتاح مكرر.
    - وعلى SQLite، REPLACE = حذف+إدراج، فيُشغّل ON DELETE CASCADE ويمسح أبناء
      السجل (حضور/نتائج الطالب) قبل إعادة إدراجها.
    الحل: SELECT بالمفتاح ثم UPDATE إن وُجد وإلا INSERT (لا حذف، لا تكرار).
    يرجّع True إن أُدرج/حُدّث سجل.
    """
    where = " AND ".join(f"{k}=?" for k in key_cols)
    key_vals = [row[k] for k in key_cols]
    existing = conn.execute(
        f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", key_vals).fetchone()
    if existing:
        # UPDATE للأعمدة غير المفتاحية فقط (لا نلمس المفتاح)
        set_cols = [c for c in row.keys() if c not in key_cols]
        if not set_cols:
            return False  # لا شيء لتحديثه (سجل ربط بحت)
        set_clause = ", ".join(f"{c}=?" for c in set_cols)
        params = [row[c] for c in set_cols] + key_vals
        conn.execute(f"UPDATE {table} SET {set_clause} WHERE {where}", params)
    else:
        cols = ",".join(row.keys())
        placeholders = ",".join(["?"] * len(row))
        conn.execute(
            f"INSERT INTO {table}({cols}) VALUES({placeholders})",
            list(row.values()))
    return True

# أعمدة قديمة لم تعد مستخدمة (تُحذف بأمان من Supabase أثناء المزامنة)
# system_prompt: بقايا مولّد الامتحانات بالذكاء الاصطناعي (أُزيل نهائيًا)
_OBSOLETE_COLUMNS = {
    "exams": ["system_prompt"],
}


def _pg_col_type(coltype):
    """يحوّل نوع عمود التطبيق إلى نوع Postgres/Supabase (بدون DEFAULT/قيود)."""
    t = coltype.upper()
    if t.startswith("INTEGER"):
        return "bigint"
    if t.startswith("REAL"):
        return "real"
    return "text"


# جداول ذات مفتاح خاص (ليست id تسلسلي) — تُنشأ بمخطط مخصّص في المزامنة
_SPECIAL_SCHEMA = {
    "settings": {"pk": "key text primary key", "cols": {"value": "text"}},
}


def _all_table_columns():
    """يرجّع dict {table: {col: coltype}} لكل الجداول المتزامنة (من EXPECTED_COLUMNS)."""
    out = {}
    for table in TABLES:
        if table in _SPECIAL_SCHEMA:
            out[table] = dict(_SPECIAL_SCHEMA[table]["cols"])
        else:
            out[table] = dict(db.EXPECTED_COLUMNS.get(table, {}))
    return out


def build_migration_sql():
    """يبني سكربت SQL كامل وآمن لمزامنة مخطط Supabase مع مخطط التطبيق الحالي.

    - ينشئ الجداول الناقصة بمعرّف id من نوع bigint (متوافق مع أرقام التطبيق).
    - يضيف الأعمدة الناقصة عبر ADD COLUMN IF NOT EXISTS (لا يكرّر، لا يحذف بيانات).
    - يحذف الأعمدة القديمة غير المستخدمة (مثل exams.system_prompt) بأمان.
    - لا يحذف أي جدول ولا أي سجل.
    """
    tables = _all_table_columns()
    lines = [
        "-- ═══════════════════════════════════════════════════════════════",
        "-- مزامنة مخطط Supabase مع النسخة الحالية من التطبيق",
        "-- آمن للتشغيل المتكرر: لا يحذف بيانات ولا جداول، ولا يكرّر أعمدة.",
        "-- انسخه كاملًا إلى: Supabase → SQL Editor → Run",
        "-- ═══════════════════════════════════════════════════════════════",
        "",
        "-- 1) إنشاء الجداول الناقصة (بمعرّف id متوافق مع أرقام التطبيق)",
    ]
    for table in TABLES:
        if table in _SPECIAL_SCHEMA:
            lines.append(f"create table if not exists {table} ({_SPECIAL_SCHEMA[table]['pk']});")
        else:
            lines.append(f"create table if not exists {table} (id bigint primary key);")
    lines.append("")
    lines.append("-- 2) إضافة الأعمدة الناقصة لكل جدول (آمن — لا يكرّر الموجود)")
    for table in TABLES:
        cols = tables[table]
        if not cols:
            continue
        lines.append(f"-- {table}")
        for col, coltype in cols.items():
            if col == "id":
                continue
            lines.append(
                f"alter table {table} add column if not exists {col} {_pg_col_type(coltype)};")
    lines.append("")
    lines.append("-- 3) حذف الأعمدة القديمة غير المستخدمة (بعد إزالة توليد الـ AI)")
    for table, cols in _OBSOLETE_COLUMNS.items():
        for col in cols:
            lines.append(f"alter table {table} drop column if exists {col};")
    lines.append("")
    lines.append("-- 4) قيود UNIQUE اللازمة لعمل النسخ الاحتياطي (upsert/ON CONFLICT)")
    lines.append("--    بدونها يفشل الرفع بخطأ 42P10. آمنة و idempotent: تحذف التكرار أولًا")
    lines.append("--    ثم تنشئ القيد فقط إن لم يوجد قيد UNIQUE/PK مطابق للأعمدة نفسها.")
    for table, (cname, cols) in _UNIQUE_CONSTRAINTS.items():
        cols_sql = ", ".join(cols)
        cols_arr = "array[" + ",".join(f"'{c}'" for c in cols) + "]"
        # 4-أ) احذف الصفوف المكرّرة (تُبقي أصغر id) حتى لا يفشل إنشاء القيد
        part_by = ", ".join(cols)
        lines.append(
            f"delete from {table} a using {table} b\n"
            f"  where a.ctid < b.ctid\n"
            + "".join(f"  and a.{c} is not distinct from b.{c}\n" for c in cols)
            + ";")
        # 4-ب) أنشئ القيد فقط لو لا يوجد أي قيد UNIQUE/PK يغطّي نفس مجموعة الأعمدة
        #     (مقارنة أسماء الأعمدة كنص مرتّب؛ نحوّل attname إلى text لتفادي name[]=text[])
        lines.append(
            "do $$\ndeclare has_constraint boolean;\nbegin\n"
            "  select exists (\n"
            "    select 1 from pg_constraint c\n"
            "    where c.conrelid = to_regclass(" + f"'{table}'" + ")\n"
            "      and c.contype in ('p','u')\n"
            "      and (\n"
            "        select array_agg(att.attname::text order by att.attname::text)\n"
            "        from unnest(c.conkey) as k(attnum)\n"
            "        join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum\n"
            "      ) = (select array_agg(x order by x) from unnest(" + cols_arr + "::text[]) as t(x))\n"
            "  ) into has_constraint;\n"
            f"  if not has_constraint then\n"
            f"    alter table {table} add constraint {cname} unique ({cols_sql});\n"
            "  end if;\n"
            "end $$;")
    lines.append("")
    lines.append("-- 5) دالة فحص القيود (يستدعيها التطبيق للتحقق الفعلي من مخطط Supabase)")
    lines.append("--    ترجّع لكل قيد PRIMARY KEY/UNIQUE اسمَ الجدول ومصفوفة أعمدته،")
    lines.append("--    فيتحقّق «فحص التوافق» من وجود القيد الصحيح بدل التخمين.")
    lines.append(_RPC_FUNCTION_SQL)
    lines.append("")
    lines.append("-- 6) إعادة تحميل مخزّن المخطط في Supabase (يحل خطأ PGRST204)")
    lines.append("notify pgrst, 'reload schema';")
    lines.append("")
    return "\n".join(lines)


# دالة SQL تُنشأ في Supabase وتُستدعى عبر PostgREST RPC للفحص الفعلي للقيود.
# security definer + منح execute للأدوار العامة كي يصلها مفتاح anon/service.
_RPC_FUNCTION_SQL = """create or replace function public.app_unique_constraints()
returns table(table_name text, columns text[])
language sql
stable
security definer
set search_path = public
as $func$
  select c.conrelid::regclass::text as table_name,
         (select array_agg(att.attname::text order by att.attname::text)
            from unnest(c.conkey) as k(attnum)
            join pg_attribute att
              on att.attrelid = c.conrelid and att.attnum = k.attnum) as columns
    from pg_constraint c
   where c.contype in ('p', 'u')
     and c.connamespace = 'public'::regnamespace;
$func$;
-- منح صلاحية التنفيذ للأدوار الموجودة فقط (آمن على Postgres عادي وعلى Supabase)
do $grant$
declare r text;
begin
  foreach r in array array['anon','authenticated','service_role'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant execute on function public.app_unique_constraints() to %I', r);
    end if;
  end loop;
end $grant$;"""


def _fetch_existing_constraints(client):
    """يقرأ قيود PRIMARY KEY/UNIQUE الفعلية من Supabase عبر دالة RPC.

    يرجّع dict {table: set(tuple(sorted(cols)))} — أي لكل جدول مجموعات الأعمدة
    التي يغطّيها قيد فريد فعلي. يرجّع None لو دالة app_unique_constraints() غير
    منشورة بعد (يعني يجب تشغيل سكربت المزامنة أولًا).
    """
    try:
        res = client.rpc("app_unique_constraints", {}).execute()
    except Exception as e:
        txt = str(e).lower()
        # الدالة غير موجودة (لم يُشغَّل السكربت بعد) — نميّزها عن أخطاء أخرى
        if ("could not find the function" in txt or "pgrst202" in txt
                or "does not exist" in txt or "42883" in txt or "404" in txt):
            return None
        return None
    def _s(v):
        if isinstance(v, (bytes, bytearray, memoryview)):
            return bytes(v).decode("utf-8", "replace")
        return str(v)
    out = {}
    for r in (res.data or []):
        tbl = r.get("table_name")
        cols = r.get("columns") or []
        if tbl is None:
            continue
        tbl = _s(tbl)
        # اسم الجدول قد يأتي مؤهّلًا (public.settings) — نأخذ الجزء الأخير
        if "." in tbl:
            tbl = tbl.split(".")[-1]
        # قد يأتي مقتبسًا بعلامات "" لو كان اسمًا حساسًا — ننظّفه
        tbl = tbl.strip('"')
        out.setdefault(tbl, set()).add(tuple(sorted(_s(c) for c in cols)))
    return out


def schema_check():
    """يفحص توافق مخطط Supabase مع مخطط التطبيق قبل الاسترجاع/النسخ.

    يرجّع dict: {ok, connected, missing{table:[cols]}, obsolete{table:[cols]},
                 missing_tables[], message}
    """
    result = {"ok": False, "connected": False, "missing": {}, "obsolete": {},
              "missing_tables": [], "message": ""}
    if db.get_setting("supabase_enabled", "0") != "1":
        result["message"] = "Supabase غير مُفعّل."
        return result
    client = _client()
    if not client:
        result["message"] = "تعذّر الاتصال بـ Supabase (تحقّق من الرابط والمفتاح)."
        return result
    result["connected"] = True
    wanted = _all_table_columns()
    for table in TABLES:
        # الأعمدة المطلوبة: أعمدة الجدول + عمود المفتاح. الجداول العادية مفتاحها id،
        # أما الجداول الخاصة (settings) فمفتاحها الطبيعي (key) وليست id.
        if table in _SPECIAL_SCHEMA:
            want_cols = set(wanted[table].keys()) | set(_conflict_cols(table))
        else:
            want_cols = set(wanted[table].keys()) | {"id"}
        try:
            res = client.table(table).select("*").limit(1).execute()
        except Exception as e:
            if _is_missing_table(e):
                result["missing_tables"].append(table)
                result["missing"][table] = sorted(want_cols)
                continue
            result["message"] = f"خطأ أثناء فحص جدول {table}: {e}"
            return result
        # أعمدة Supabase الفعلية: من صف موجود، وإلا نفترض ناقصة
        present = set(res.data[0].keys()) if res.data else set()
        if res.data:
            # كشف مشكلة نوع UUID للمعرّف (id) — غير متوافق مع أرقام التطبيق
            idv = res.data[0].get("id")
            if isinstance(idv, str) and _looks_uuid(idv):
                result.setdefault("uuid_tables", []).append(table)
            miss = [c for c in want_cols if c not in present]
            if miss:
                result["missing"][table] = sorted(miss)
            # أعمدة قديمة معروفة موجودة في Supabase؟
            obs = [c for c in _OBSOLETE_COLUMNS.get(table, []) if c in present]
            if obs:
                result["obsolete"][table] = obs
    # فحص قيود UNIQUE اللازمة للنسخ الاحتياطي (يمنع خطأ 42P10 لاحقًا) — بشكل قاطع.
    # الطريقة الموثوقة: استدعاء دالة app_unique_constraints() في Supabase (RPC) التي
    # تقرأ قيود pg_constraint الفعلية. هكذا نتحقّق من القيد الحقيقي بدل التخمين، ولا
    # نلمس بيانات (بخلاف probe upsert الذي يعطي نتائج خاطئة على الجداول الفارغة).
    result["missing_constraints"] = {}
    result["rpc_missing"] = False
    existing = _fetch_existing_constraints(client)  # None لو الدالة غير موجودة بعد
    for table, (cname, cols) in _UNIQUE_CONSTRAINTS.items():
        if table in result["missing_tables"]:
            continue  # الجدول نفسه ناقص — يُعالَج أولًا
        want = tuple(sorted(cols))
        if existing is not None:
            # فحص قاطع: هل يوجد قيد PK/UNIQUE يغطّي نفس مجموعة الأعمدة تمامًا؟
            have = existing.get(table, set())
            if want not in have:
                result["missing_constraints"][table] = cols
        else:
            # الدالة غير منشورة بعد → نطلب تشغيل السكربت (الذي ينشئها + القيود).
            result["rpc_missing"] = True
            result["missing_constraints"][table] = cols
    uuid_tables = result.get("uuid_tables", [])
    result["ok"] = not (result["missing"] or result["obsolete"]
                        or result["missing_tables"] or uuid_tables
                        or result["missing_constraints"])

    # تقرير مفصّل لكل جدول متزامن (البند 6): جدول/أعمدة/نوع id/مفتاح تعارض/قيد UNIQUE.
    # يُعرض للمستخدم صفًا صفًا مع ✅/❌ حتى لا يبحث يدويًا عن المشكلة (البند 11).
    report = []
    for table in TABLES:
        conflict = _conflict_cols(table)
        needs_constraint = conflict != ["id"]
        issues = []
        if table in result["missing_tables"]:
            issues.append("الجدول غير موجود")
        if table in uuid_tables:
            issues.append("معرّف id بنوع UUID (يجب أن يكون bigint)")
        if result["missing"].get(table):
            issues.append("أعمدة ناقصة: " + "، ".join(result["missing"][table]))
        if result["obsolete"].get(table):
            issues.append("أعمدة قديمة يجب حذفها: " + "، ".join(result["obsolete"][table]))
        if table in result["missing_constraints"]:
            issues.append("قيد UNIQUE ناقص: UNIQUE("
                          + ", ".join(result["missing_constraints"][table]) + ")")
        report.append({
            "table": table,
            "conflict_target": ", ".join(conflict),
            "requires_unique": needs_constraint,
            "required_constraint": ("UNIQUE(" + ", ".join(conflict) + ")"
                                    if needs_constraint else "PRIMARY KEY(id)"),
            "ok": not issues,
            "issues": issues,
        })
    result["report"] = report
    if result["ok"]:
        result["message"] = "مخطط Supabase متوافق مع التطبيق ✅"
    else:
        parts = []
        if uuid_tables:
            parts.append("جداول بمعرّف UUID (يجب إعادة إنشائها بـ bigint): "
                         + "، ".join(uuid_tables))
        if result["missing_tables"]:
            parts.append(f"جداول ناقصة: {', '.join(result['missing_tables'])}")
        if result["missing"]:
            parts.append("أعمدة ناقصة في: " + "، ".join(result["missing"].keys()))
        if result["obsolete"]:
            parts.append("أعمدة قديمة يجب حذفها في: " + "، ".join(result["obsolete"].keys()))
        if result["missing_constraints"]:
            parts.append("قيود UNIQUE ناقصة للنسخ الاحتياطي في: "
                         + "، ".join(result["missing_constraints"].keys()))
        if result.get("rpc_missing"):
            parts.append("دالة فحص القيود غير منشورة بعد على Supabase")
        result["message"] = ("مخطط Supabase يحتاج تحديثًا — " + " | ".join(parts)
                             + " . شغّل سكربت المزامنة في SQL Editor.")
    return result


def backup_all():
    """رفع نسخة كاملة من كل الجداول للسحابة عبر upsert آمن (idempotent).

    الاعتماد على المفتاح (id لأغلب الجداول، وأعمدة مركّبة لجدول الربط)
    يضمن تحديث السجلات الموجودة بدل إنشاء نسخ مكررة عند تكرار النسخ.
    """
    client = _client()
    if not client:
        return False, "Supabase غير مفعّل أو غير مضبوط"

    # تحقّق مسبق من المخطط قبل أي محاولة رفع (البند 7): لو ناقص قيد/عمود/جدول
    # نوقف الآن ونعرض ما يجب إصلاحه بالضبط — بدل ظهور خطأ 42P10 مربك أثناء الرفع.
    chk = schema_check()
    if chk.get("connected") and not chk.get("ok"):
        return False, (
            "توقّف الرفع قبل البدء: مخطط Supabase غير متوافق بعد.\n"
            + chk.get("message", "")
            + "\n\nحمّل «سكربت مزامنة Supabase» وشغّله في SQL Editor ثم أعد الفحص."
        )

    conn = db.get_db()
    try:
        total = 0
        for table in TABLES:
            local_cols = _local_columns(conn, table)
            if not local_cols:
                continue  # الجدول غير موجود محليًا
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
            if not rows:
                continue
            # ارفع فقط الأعمدة الموجودة في المخطط المحلي (نتجنّب أي عمود قديم)
            rows = [{k: v for k, v in r.items() if k in local_cols or k == "id"}
                    for r in rows]
            on_conflict = ",".join(_conflict_cols(table))
            # upsert على أساس مفتاح التعارض الطبيعي: يحدّث الموجود ولا يكرّر.
            # أي خطأ (بما فيه 42P10) يُرفع كما هو — لا نلتقطه ولا نخفيه.
            client.table(table).upsert(rows, on_conflict=on_conflict).execute()
            total += len(rows)
        conn.close()
        return True, f"تم رفع نسخة احتياطية ({total} سجلًا) إلى Supabase ✅"
    except Exception as e:
        conn.close()
        hint = _schema_hint(e)
        return False, f"فشل الرفع: {e}" + (f"\n\n{hint}" if hint else "")


def restore_all():
    """استرجاع البيانات من السحابة إلى قاعدة البيانات المحلية.

    السبب الجذري لخطأ «table exams has no column named system_prompt»:
    كان الاسترجاع يأخذ كل الأعمدة من Supabase (SELECT *) ويحاول إدراجها محليًا،
    فيفشل عند وجود عمود قديم في Supabase غير موجود في المخطط الحالي.
    الحل: نُدرج فقط الأعمدة الموجودة فعلًا في المخطط المحلي (تجاهل الزائد).
    """
    client = _client()
    if not client:
        return False, "Supabase غير مفعّل أو غير مضبوط"
    conn = db.get_db()
    try:
        total = 0
        for table in TABLES:
            local_cols = _local_columns(conn, table)
            if not local_cols:
                continue  # الجدول غير موجود محليًا — تخطَّ
            # هل الجدول موجود في Supabase؟ (نتجاهله بهدوء لو غير موجود)
            try:
                res = client.table(table).select("*").execute()
            except Exception as te:
                if _is_missing_table(te):
                    continue
                raise
            # الأعمدة المسموح إدراجها محليًا. لا نضيف id إلا لو الجدول المحلي فعلًا
            # يملك عمود id (جداول مثل settings مفتاحها key بلا id → إضافة id تُسبّب
            # خطأ «no such column: id» عند الاسترجاع). المصدر: أعمدة الجدول المحلية.
            allowed = set(local_cols)
            if "id" in local_cols:
                allowed.add("id")
            # اختيار مفتاح المطابقة أثناء الاسترجاع:
            # - الجداول ذات مفتاح طبيعي (enrollments/attendance/results/...) نطابق
            #   بمفتاحها الطبيعي ونُسقط id الوارد؛ فتحتفظ القاعدة المحلية بـ id الخاص
            #   بها ولا يصطدم بقيد UNIQUE الطبيعي (إصلاح جذري لفشل الاسترجاع).
            # - بقية الجداول تطابق بـ id (مفتاحها الأساسي، ومُشار إليه من الأبناء).
            natural = _NATURAL_KEY_TABLES.get(table)
            drop_id = False
            if natural and all(c in allowed for c in natural):
                key_cols = natural
                drop_id = True  # نترك القاعدة المحلية تولّد id بنفسها
            else:
                key_cols = _KEY_COLUMNS.get(table, ["id"])
            for row in res.data:
                # أبقِ فقط الأعمدة المعروفة محليًا (يتجاهل system_prompt وأي عمود قديم)
                filtered = {k: v for k, v in row.items() if k in allowed}
                if drop_id:
                    filtered.pop("id", None)  # لا نفرض id الوارد على المفتاح الطبيعي
                if not filtered:
                    continue
                # لا بد من توفّر مفتاح المطابقة كاملًا لتحديد السجل بدقة
                if not all(k in filtered for k in key_cols):
                    continue
                if _upsert_row(conn, table, filtered, key_cols):
                    total += 1
            # على Postgres: بعد إدراج معرّفات id صريحة، لا بد من مزامنة تسلسل الـ id
            # وإلا يصطدم أول إدراج جديد بمفتاح مكرر. (لا يلزم عندما أسقطنا id لأن
            # القاعدة ولّدته بنفسها، لكنه آمن ومفيد في الحالتين.)
            if "id" in allowed:
                _sync_sequence(conn, table)
        conn.commit()
        conn.close()
        return True, f"تم استرجاع البيانات من Supabase ({total} سجلًا) ✅"
    except Exception as e:
        conn.close()
        hint = _schema_hint(e)
        return False, f"فشل الاسترجاع: {e}" + (f"\n\n{hint}" if hint else "")


def _sync_sequence(conn, table):
    """يضبط تسلسل عمود id في Postgres على أكبر id موجود (بعد إدراج معرّفات صريحة).

    على SQLite لا حاجة لذلك (rowid يُدار تلقائيًا) فنتجاهلها بهدوء.
    """
    try:
        if db.backend() != "postgres":
            return
        conn.execute(
            "SELECT setval(pg_get_serial_sequence(?, 'id'), "
            "COALESCE((SELECT MAX(id) FROM " + table + "), 1), true)",
            (table,))
    except Exception:
        # لو الجدول لا يملك تسلسلًا (نادر) نتجاهل
        try:
            conn.rollback()
        except Exception:
            pass


def _is_missing_table(err):
    t = str(err).lower()
    return ("does not exist" in t or "could not find the table" in t
            or "pgrst205" in t or "relation" in t and "does not exist" in t)


import re as _re
_UUID_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I)


def _looks_uuid(v):
    return bool(_UUID_RE.match(str(v)))


# سكربت SQL لإنشاء الجداول في Supabase (يُعرض للمستخدم)
# للتوافق مع الكود القديم: يُبنى ديناميكيًا من المخطط الحالي (لا يوجد سرد ثابت)
SUPABASE_SCHEMA_SQL = build_migration_sql()
