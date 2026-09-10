-- ملف مخطط قاعدة البيانات (مولّد تلقائيًا من التطبيق)
-- اللهجة: postgres
-- يُعاد توليده تلقائيًا عند أي تعديل في بنية قاعدة البيانات.

CREATE TABLE IF NOT EXISTS admin (
    id BIGSERIAL PRIMARY KEY,
    username TEXT,
    password_hash TEXT,
    recovery_code TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS academic_years (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    start_date TEXT,
    end_date TEXT,
    is_current BIGINT DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS terms (
    id BIGSERIAL PRIMARY KEY,
    year_id BIGINT,
    name TEXT,
    start_date TEXT,
    end_date TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    grade TEXT,
    fee REAL DEFAULT 0,
    year_id BIGINT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS students (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    phone TEXT,
    parent_phone TEXT,
    grade TEXT,
    group_id BIGINT,
    notes TEXT,
    code TEXT,
    exam_password TEXT,
    status TEXT DEFAULT 'active',
    deactivated_at TEXT,
    deactivated_reason TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS enrollments (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT,
    year_id BIGINT,
    group_id BIGINT,
    status TEXT DEFAULT 'active',
    discount_fee REAL,
    discount_reason TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS group_transfers (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT,
    year_id BIGINT,
    from_group_id BIGINT,
    to_group_id BIGINT,
    date TEXT,
    note TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT,
    year_id BIGINT,
    title TEXT,
    date TEXT,
    fee REAL DEFAULT 0,
    notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS attendance (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT,
    student_id BIGINT,
    group_id BIGINT,
    student_name_snapshot TEXT,
    group_name_snapshot TEXT,
    status TEXT,
    homework TEXT DEFAULT 'none',
    paid BIGINT DEFAULT 0,
    amount REAL DEFAULT 0,
    fee_exempt BIGINT DEFAULT 0,
    exempt_reason TEXT,
    fee_charged REAL,
    focus_level BIGINT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS exams (
    id BIGSERIAL PRIMARY KEY,
    title TEXT,
    group_id BIGINT,
    year_id BIGINT,
    total_marks REAL DEFAULT 0,
    duration BIGINT DEFAULT 30,
    is_online BIGINT DEFAULT 1,
    ai_provider TEXT,
    ai_model TEXT,
    allow_retake BIGINT DEFAULT 0,
    max_attempts BIGINT DEFAULT 1,
    final_policy TEXT DEFAULT 'highest',
    shuffle_questions BIGINT DEFAULT 0,
    shuffle_choices BIGINT DEFAULT 0,
    subject TEXT,
    grade TEXT,
    term_id BIGINT,
    exam_date TEXT,
    num_questions BIGINT DEFAULT 0,
    show_question_number BIGINT DEFAULT 1,
    auto_grade BIGINT DEFAULT 1,
    show_result_to_student BIGINT DEFAULT 1,
    show_answers_to_student BIGINT DEFAULT 0,
    show_score BIGINT DEFAULT 1,
    show_percentage BIGINT DEFAULT 1,
    show_grade_label BIGINT DEFAULT 1,
    send_result_to_parent BIGINT DEFAULT 0,
    one_question_per_page BIGINT DEFAULT 0,
    prevent_back BIGINT DEFAULT 0,
    status TEXT DEFAULT 'draft',
    open_at TEXT,
    close_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT,
    text TEXT,
    qtype TEXT DEFAULT 'mcq',
    option_a TEXT,
    option_b TEXT,
    option_c TEXT,
    option_d TEXT,
    correct TEXT,
    answer_text TEXT,
    extra TEXT,
    category TEXT,
    cognitive TEXT,
    position BIGINT DEFAULT 0,
    marks REAL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS question_bank (
    id BIGSERIAL PRIMARY KEY,
    text TEXT,
    qtype TEXT DEFAULT 'mcq',
    option_a TEXT,
    option_b TEXT,
    option_c TEXT,
    option_d TEXT,
    correct TEXT,
    answer_text TEXT,
    marks REAL DEFAULT 1,
    grade TEXT,
    subject TEXT,
    unit TEXT,
    lesson TEXT,
    difficulty TEXT,
    stage TEXT,
    term TEXT,
    year_id BIGINT,
    extra TEXT,
    dedup_hash TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT,
    student_id BIGINT,
    score REAL DEFAULT 0,
    auto_score REAL DEFAULT 0,
    status TEXT DEFAULT 'graded',
    question_scores TEXT,
    answers TEXT,
    taken_at TEXT,
    final_attempt_id BIGINT
);

CREATE TABLE IF NOT EXISTS exam_attempts (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT,
    student_id BIGINT,
    attempt_no BIGINT DEFAULT 1,
    score REAL DEFAULT 0,
    auto_score REAL DEFAULT 0,
    status TEXT DEFAULT 'graded',
    question_scores TEXT,
    answers TEXT,
    taken_at TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT,
    session_id BIGINT,
    remaining REAL DEFAULT 0,
    due_date TEXT,
    due_time TEXT DEFAULT '09:00',
    method TEXT DEFAULT 'whatsapp',
    status TEXT DEFAULT 'pending',
    sent_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS booklets (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT,
    year_id BIGINT,
    student_name_snapshot TEXT,
    title TEXT,
    price REAL DEFAULT 0,
    paid BIGINT DEFAULT 0,
    amount REAL DEFAULT 0,
    date TEXT,
    notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS wa_logs (
    id BIGSERIAL PRIMARY KEY,
    phone TEXT,
    message TEXT,
    provider TEXT,
    success BIGINT DEFAULT 0,
    status_code BIGINT DEFAULT 0,
    error_type TEXT,
    msg_type TEXT,
    response TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS parents (
    id BIGSERIAL PRIMARY KEY,
    username TEXT,
    password_hash TEXT,
    name TEXT,
    phone TEXT,
    active BIGINT DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS parent_students (
    id BIGSERIAL PRIMARY KEY,
    parent_id BIGINT,
    student_id BIGINT,
    UNIQUE(parent_id, student_id)
);

CREATE TABLE IF NOT EXISTS absence_alerts (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT,
    year_id BIGINT,
    threshold BIGINT,
    absence_count BIGINT,
    notified_site BIGINT DEFAULT 0,
    notified_wa BIGINT DEFAULT 0,
    created_at TEXT,
    UNIQUE(student_id, year_id, threshold)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS user_state (
    owner TEXT NOT NULL,
    skey TEXT NOT NULL,
    value TEXT,
    updated_at TEXT,
    PRIMARY KEY(owner, skey)
);

CREATE TABLE IF NOT EXISTS templates (
    id BIGSERIAL PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    title TEXT,
    body TEXT
);
