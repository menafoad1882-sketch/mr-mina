-- ═══════════════════════════════════════════════════════════════
-- مزامنة مخطط Supabase مع النسخة الحالية من التطبيق
-- آمن للتشغيل المتكرر: لا يحذف بيانات ولا جداول، ولا يكرّر أعمدة.
-- انسخه كاملًا إلى: Supabase → SQL Editor → Run
-- ═══════════════════════════════════════════════════════════════

-- 1) إنشاء الجداول الناقصة (بمعرّف id متوافق مع أرقام التطبيق)
create table if not exists academic_years (id bigint primary key);
create table if not exists terms (id bigint primary key);
create table if not exists groups (id bigint primary key);
create table if not exists students (id bigint primary key);
create table if not exists enrollments (id bigint primary key);
create table if not exists group_transfers (id bigint primary key);
create table if not exists sessions (id bigint primary key);
create table if not exists attendance (id bigint primary key);
create table if not exists exams (id bigint primary key);
create table if not exists questions (id bigint primary key);
create table if not exists question_bank (id bigint primary key);
create table if not exists results (id bigint primary key);
create table if not exists exam_attempts (id bigint primary key);
create table if not exists reminders (id bigint primary key);
create table if not exists booklets (id bigint primary key);
create table if not exists wa_logs (id bigint primary key);
create table if not exists parents (id bigint primary key);
create table if not exists parent_students (id bigint primary key);
create table if not exists absence_alerts (id bigint primary key);
create table if not exists settings (key text primary key);

-- 2) إضافة الأعمدة الناقصة لكل جدول (آمن — لا يكرّر الموجود)
-- academic_years
alter table academic_years add column if not exists name text;
alter table academic_years add column if not exists start_date text;
alter table academic_years add column if not exists end_date text;
alter table academic_years add column if not exists is_current bigint;
alter table academic_years add column if not exists created_at text;
-- terms
alter table terms add column if not exists year_id bigint;
alter table terms add column if not exists name text;
alter table terms add column if not exists start_date text;
alter table terms add column if not exists end_date text;
alter table terms add column if not exists created_at text;
-- groups
alter table groups add column if not exists name text;
alter table groups add column if not exists grade text;
alter table groups add column if not exists fee real;
alter table groups add column if not exists year_id bigint;
alter table groups add column if not exists created_at text;
-- students
alter table students add column if not exists name text;
alter table students add column if not exists phone text;
alter table students add column if not exists parent_phone text;
alter table students add column if not exists grade text;
alter table students add column if not exists group_id bigint;
alter table students add column if not exists notes text;
alter table students add column if not exists code text;
alter table students add column if not exists exam_password text;
alter table students add column if not exists status text;
alter table students add column if not exists deactivated_at text;
alter table students add column if not exists deactivated_reason text;
alter table students add column if not exists created_at text;
-- enrollments
alter table enrollments add column if not exists student_id bigint;
alter table enrollments add column if not exists year_id bigint;
alter table enrollments add column if not exists group_id bigint;
alter table enrollments add column if not exists status text;
alter table enrollments add column if not exists discount_fee real;
alter table enrollments add column if not exists discount_reason text;
alter table enrollments add column if not exists created_at text;
-- group_transfers
alter table group_transfers add column if not exists student_id bigint;
alter table group_transfers add column if not exists year_id bigint;
alter table group_transfers add column if not exists from_group_id bigint;
alter table group_transfers add column if not exists to_group_id bigint;
alter table group_transfers add column if not exists date text;
alter table group_transfers add column if not exists note text;
alter table group_transfers add column if not exists created_at text;
-- sessions
alter table sessions add column if not exists group_id bigint;
alter table sessions add column if not exists year_id bigint;
alter table sessions add column if not exists title text;
alter table sessions add column if not exists date text;
alter table sessions add column if not exists fee real;
alter table sessions add column if not exists notes text;
alter table sessions add column if not exists created_at text;
-- attendance
alter table attendance add column if not exists session_id bigint;
alter table attendance add column if not exists student_id bigint;
alter table attendance add column if not exists group_id bigint;
alter table attendance add column if not exists student_name_snapshot text;
alter table attendance add column if not exists group_name_snapshot text;
alter table attendance add column if not exists status text;
alter table attendance add column if not exists homework text;
alter table attendance add column if not exists paid bigint;
alter table attendance add column if not exists amount real;
alter table attendance add column if not exists fee_exempt bigint;
alter table attendance add column if not exists exempt_reason text;
alter table attendance add column if not exists fee_charged real;
alter table attendance add column if not exists focus_level bigint;
alter table attendance add column if not exists created_at text;
-- exams
alter table exams add column if not exists title text;
alter table exams add column if not exists group_id bigint;
alter table exams add column if not exists year_id bigint;
alter table exams add column if not exists total_marks real;
alter table exams add column if not exists duration bigint;
alter table exams add column if not exists is_online bigint;
alter table exams add column if not exists ai_provider text;
alter table exams add column if not exists ai_model text;
alter table exams add column if not exists allow_retake bigint;
alter table exams add column if not exists max_attempts bigint;
alter table exams add column if not exists final_policy text;
alter table exams add column if not exists shuffle_questions bigint;
alter table exams add column if not exists shuffle_choices bigint;
alter table exams add column if not exists subject text;
alter table exams add column if not exists grade text;
alter table exams add column if not exists term_id bigint;
alter table exams add column if not exists exam_date text;
alter table exams add column if not exists num_questions bigint;
alter table exams add column if not exists show_question_number bigint;
alter table exams add column if not exists auto_grade bigint;
alter table exams add column if not exists show_result_to_student bigint;
alter table exams add column if not exists show_answers_to_student bigint;
alter table exams add column if not exists show_score bigint;
alter table exams add column if not exists show_percentage bigint;
alter table exams add column if not exists show_grade_label bigint;
alter table exams add column if not exists send_result_to_parent bigint;
alter table exams add column if not exists one_question_per_page bigint;
alter table exams add column if not exists prevent_back bigint;
alter table exams add column if not exists status text;
alter table exams add column if not exists open_at text;
alter table exams add column if not exists close_at text;
alter table exams add column if not exists created_at text;
-- questions
alter table questions add column if not exists exam_id bigint;
alter table questions add column if not exists text text;
alter table questions add column if not exists qtype text;
alter table questions add column if not exists option_a text;
alter table questions add column if not exists option_b text;
alter table questions add column if not exists option_c text;
alter table questions add column if not exists option_d text;
alter table questions add column if not exists correct text;
alter table questions add column if not exists answer_text text;
alter table questions add column if not exists extra text;
alter table questions add column if not exists category text;
alter table questions add column if not exists cognitive text;
alter table questions add column if not exists position bigint;
alter table questions add column if not exists marks real;
-- question_bank
alter table question_bank add column if not exists text text;
alter table question_bank add column if not exists qtype text;
alter table question_bank add column if not exists option_a text;
alter table question_bank add column if not exists option_b text;
alter table question_bank add column if not exists option_c text;
alter table question_bank add column if not exists option_d text;
alter table question_bank add column if not exists correct text;
alter table question_bank add column if not exists answer_text text;
alter table question_bank add column if not exists marks real;
alter table question_bank add column if not exists grade text;
alter table question_bank add column if not exists subject text;
alter table question_bank add column if not exists unit text;
alter table question_bank add column if not exists lesson text;
alter table question_bank add column if not exists difficulty text;
alter table question_bank add column if not exists stage text;
alter table question_bank add column if not exists term text;
alter table question_bank add column if not exists year_id bigint;
alter table question_bank add column if not exists extra text;
alter table question_bank add column if not exists dedup_hash text;
alter table question_bank add column if not exists created_at text;
-- results
alter table results add column if not exists exam_id bigint;
alter table results add column if not exists student_id bigint;
alter table results add column if not exists score real;
alter table results add column if not exists auto_score real;
alter table results add column if not exists status text;
alter table results add column if not exists question_scores text;
alter table results add column if not exists answers text;
alter table results add column if not exists taken_at text;
alter table results add column if not exists final_attempt_id bigint;
-- exam_attempts
alter table exam_attempts add column if not exists exam_id bigint;
alter table exam_attempts add column if not exists student_id bigint;
alter table exam_attempts add column if not exists attempt_no bigint;
alter table exam_attempts add column if not exists score real;
alter table exam_attempts add column if not exists auto_score real;
alter table exam_attempts add column if not exists status text;
alter table exam_attempts add column if not exists question_scores text;
alter table exam_attempts add column if not exists answers text;
alter table exam_attempts add column if not exists taken_at text;
-- reminders
alter table reminders add column if not exists student_id bigint;
alter table reminders add column if not exists session_id bigint;
alter table reminders add column if not exists remaining real;
alter table reminders add column if not exists due_date text;
alter table reminders add column if not exists due_time text;
alter table reminders add column if not exists method text;
alter table reminders add column if not exists status text;
alter table reminders add column if not exists sent_at text;
alter table reminders add column if not exists created_at text;
-- booklets
alter table booklets add column if not exists student_id bigint;
alter table booklets add column if not exists year_id bigint;
alter table booklets add column if not exists student_name_snapshot text;
alter table booklets add column if not exists title text;
alter table booklets add column if not exists price real;
alter table booklets add column if not exists paid bigint;
alter table booklets add column if not exists amount real;
alter table booklets add column if not exists date text;
alter table booklets add column if not exists notes text;
alter table booklets add column if not exists created_at text;
-- wa_logs
alter table wa_logs add column if not exists phone text;
alter table wa_logs add column if not exists message text;
alter table wa_logs add column if not exists provider text;
alter table wa_logs add column if not exists success bigint;
alter table wa_logs add column if not exists status_code bigint;
alter table wa_logs add column if not exists error_type text;
alter table wa_logs add column if not exists msg_type text;
alter table wa_logs add column if not exists response text;
alter table wa_logs add column if not exists created_at text;
-- parents
alter table parents add column if not exists username text;
alter table parents add column if not exists password_hash text;
alter table parents add column if not exists name text;
alter table parents add column if not exists phone text;
alter table parents add column if not exists active bigint;
alter table parents add column if not exists created_at text;
-- parent_students
alter table parent_students add column if not exists parent_id bigint;
alter table parent_students add column if not exists student_id bigint;
-- absence_alerts
alter table absence_alerts add column if not exists student_id bigint;
alter table absence_alerts add column if not exists year_id bigint;
alter table absence_alerts add column if not exists threshold bigint;
alter table absence_alerts add column if not exists absence_count bigint;
alter table absence_alerts add column if not exists notified_site bigint;
alter table absence_alerts add column if not exists notified_wa bigint;
alter table absence_alerts add column if not exists created_at text;
-- settings
alter table settings add column if not exists value text;

-- 3) حذف الأعمدة القديمة غير المستخدمة (بعد إزالة توليد الـ AI)
alter table exams drop column if exists system_prompt;

-- 4) قيود UNIQUE اللازمة لعمل النسخ الاحتياطي (upsert/ON CONFLICT)
--    بدونها يفشل الرفع بخطأ 42P10. آمنة و idempotent: تحذف التكرار أولًا
--    ثم تنشئ القيد فقط إن لم يوجد قيد UNIQUE/PK مطابق للأعمدة نفسها.
delete from parent_students a using parent_students b
  where a.ctid < b.ctid
  and a.parent_id = b.parent_id
  and a.student_id = b.student_id
;
do $$
declare has_constraint boolean;
begin
  select exists (
    select 1 from pg_constraint c
    where c.conrelid = to_regclass('parent_students')
      and c.contype in ('p','u')
      and (
        select array_agg(att.attname::text order by att.attname::text)
        from unnest(c.conkey) as k(attnum)
        join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum
      ) = (select array_agg(x order by x) from unnest(array['parent_id','student_id']::text[]) as t(x))
  ) into has_constraint;
  if not has_constraint then
    alter table parent_students add constraint uq_parent_students_pair unique (parent_id, student_id);
  end if;
end $$;
delete from absence_alerts a using absence_alerts b
  where a.ctid < b.ctid
  and a.student_id = b.student_id
  and a.year_id = b.year_id
  and a.threshold = b.threshold
;
do $$
declare has_constraint boolean;
begin
  select exists (
    select 1 from pg_constraint c
    where c.conrelid = to_regclass('absence_alerts')
      and c.contype in ('p','u')
      and (
        select array_agg(att.attname::text order by att.attname::text)
        from unnest(c.conkey) as k(attnum)
        join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum
      ) = (select array_agg(x order by x) from unnest(array['student_id','year_id','threshold']::text[]) as t(x))
  ) into has_constraint;
  if not has_constraint then
    alter table absence_alerts add constraint uq_absence_alert unique (student_id, year_id, threshold);
  end if;
end $$;
delete from settings a using settings b
  where a.ctid < b.ctid
  and a.key = b.key
;
do $$
declare has_constraint boolean;
begin
  select exists (
    select 1 from pg_constraint c
    where c.conrelid = to_regclass('settings')
      and c.contype in ('p','u')
      and (
        select array_agg(att.attname::text order by att.attname::text)
        from unnest(c.conkey) as k(attnum)
        join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum
      ) = (select array_agg(x order by x) from unnest(array['key']::text[]) as t(x))
  ) into has_constraint;
  if not has_constraint then
    alter table settings add constraint uq_settings_key unique (key);
  end if;
end $$;
delete from attendance a using attendance b
  where a.ctid < b.ctid
  and a.session_id = b.session_id
  and a.student_id = b.student_id
;
do $$
declare has_constraint boolean;
begin
  select exists (
    select 1 from pg_constraint c
    where c.conrelid = to_regclass('attendance')
      and c.contype in ('p','u')
      and (
        select array_agg(att.attname::text order by att.attname::text)
        from unnest(c.conkey) as k(attnum)
        join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum
      ) = (select array_agg(x order by x) from unnest(array['session_id','student_id']::text[]) as t(x))
  ) into has_constraint;
  if not has_constraint then
    alter table attendance add constraint uq_attendance_session_student unique (session_id, student_id);
  end if;
end $$;
delete from results a using results b
  where a.ctid < b.ctid
  and a.exam_id = b.exam_id
  and a.student_id = b.student_id
;
do $$
declare has_constraint boolean;
begin
  select exists (
    select 1 from pg_constraint c
    where c.conrelid = to_regclass('results')
      and c.contype in ('p','u')
      and (
        select array_agg(att.attname::text order by att.attname::text)
        from unnest(c.conkey) as k(attnum)
        join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum
      ) = (select array_agg(x order by x) from unnest(array['exam_id','student_id']::text[]) as t(x))
  ) into has_constraint;
  if not has_constraint then
    alter table results add constraint uq_results_exam_student unique (exam_id, student_id);
  end if;
end $$;
delete from enrollments a using enrollments b
  where a.ctid < b.ctid
  and a.student_id = b.student_id
  and a.year_id = b.year_id
;
do $$
declare has_constraint boolean;
begin
  select exists (
    select 1 from pg_constraint c
    where c.conrelid = to_regclass('enrollments')
      and c.contype in ('p','u')
      and (
        select array_agg(att.attname::text order by att.attname::text)
        from unnest(c.conkey) as k(attnum)
        join pg_attribute att on att.attrelid=c.conrelid and att.attnum=k.attnum
      ) = (select array_agg(x order by x) from unnest(array['student_id','year_id']::text[]) as t(x))
  ) into has_constraint;
  if not has_constraint then
    alter table enrollments add constraint uq_enrollments_student_year unique (student_id, year_id);
  end if;
end $$;

-- 5) دالة فحص القيود (يستدعيها التطبيق للتحقق الفعلي من مخطط Supabase)
--    ترجّع لكل قيد PRIMARY KEY/UNIQUE اسمَ الجدول ومصفوفة أعمدته،
--    فيتحقّق «فحص التوافق» من وجود القيد الصحيح بدل التخمين.
create or replace function public.app_unique_constraints()
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
end $grant$;

-- 6) إعادة تحميل مخزّن المخطط في Supabase (يحل خطأ PGRST204)
notify pgrst, 'reload schema';
