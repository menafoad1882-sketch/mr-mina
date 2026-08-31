-- ملف مخطط قاعدة البيانات (مولّد تلقائيًا من التطبيق)
-- اللهجة: sqlite
-- يُعاد توليده تلقائيًا عند أي تعديل في بنية قاعدة البيانات.

CREATE TABLE IF NOT EXISTS admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    password_hash TEXT,
    recovery_code TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS academic_years (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    start_date TEXT,
    end_date TEXT,
    is_current INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_id INTEGER,
    name TEXT,
    start_date TEXT,
    end_date TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    grade TEXT,
    fee REAL DEFAULT 0,
    year_id INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    phone TEXT,
    parent_phone TEXT,
    grade TEXT,
    group_id INTEGER,
    notes TEXT,
    code TEXT,
    exam_password TEXT,
    status TEXT DEFAULT 'active',
    deactivated_at TEXT,
    deactivated_reason TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    year_id INTEGER,
    group_id INTEGER,
    status TEXT DEFAULT 'active',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS group_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    year_id INTEGER,
    from_group_id INTEGER,
    to_group_id INTEGER,
    date TEXT,
    note TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER,
    year_id INTEGER,
    title TEXT,
    date TEXT,
    fee REAL DEFAULT 0,
    notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id INTEGER,
    group_id INTEGER,
    student_name_snapshot TEXT,
    group_name_snapshot TEXT,
    status TEXT,
    homework TEXT DEFAULT 'none',
    paid INTEGER DEFAULT 0,
    amount REAL DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    group_id INTEGER,
    year_id INTEGER,
    total_marks REAL DEFAULT 0,
    duration INTEGER DEFAULT 30,
    is_online INTEGER DEFAULT 1,
    ai_provider TEXT,
    ai_model TEXT,
    allow_retake INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 1,
    final_policy TEXT DEFAULT 'highest',
    shuffle_questions INTEGER DEFAULT 0,
    shuffle_choices INTEGER DEFAULT 0,
    subject TEXT,
    grade TEXT,
    term_id INTEGER,
    exam_date TEXT,
    num_questions INTEGER DEFAULT 0,
    show_question_number INTEGER DEFAULT 1,
    auto_grade INTEGER DEFAULT 1,
    show_result_to_student INTEGER DEFAULT 1,
    show_answers_to_student INTEGER DEFAULT 0,
    show_score INTEGER DEFAULT 1,
    show_percentage INTEGER DEFAULT 1,
    show_grade_label INTEGER DEFAULT 1,
    send_result_to_parent INTEGER DEFAULT 0,
    one_question_per_page INTEGER DEFAULT 0,
    prevent_back INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft',
    open_at TEXT,
    close_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER,
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
    position INTEGER DEFAULT 0,
    marks REAL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS question_bank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    year_id INTEGER,
    extra TEXT,
    dedup_hash TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER,
    student_id INTEGER,
    score REAL DEFAULT 0,
    auto_score REAL DEFAULT 0,
    status TEXT DEFAULT 'graded',
    question_scores TEXT,
    answers TEXT,
    taken_at TEXT,
    final_attempt_id INTEGER
);

CREATE TABLE IF NOT EXISTS exam_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER,
    student_id INTEGER,
    attempt_no INTEGER DEFAULT 1,
    score REAL DEFAULT 0,
    auto_score REAL DEFAULT 0,
    status TEXT DEFAULT 'graded',
    question_scores TEXT,
    answers TEXT,
    taken_at TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    session_id INTEGER,
    remaining REAL DEFAULT 0,
    due_date TEXT,
    due_time TEXT DEFAULT '09:00',
    method TEXT DEFAULT 'whatsapp',
    status TEXT DEFAULT 'pending',
    sent_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS booklets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    year_id INTEGER,
    student_name_snapshot TEXT,
    title TEXT,
    price REAL DEFAULT 0,
    paid INTEGER DEFAULT 0,
    amount REAL DEFAULT 0,
    date TEXT,
    notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS wa_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT,
    message TEXT,
    provider TEXT,
    success INTEGER DEFAULT 0,
    status_code INTEGER DEFAULT 0,
    error_type TEXT,
    msg_type TEXT,
    response TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS parents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    password_hash TEXT,
    name TEXT,
    phone TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS parent_students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    student_id INTEGER,
    UNIQUE(parent_id, student_id)
);

CREATE TABLE IF NOT EXISTS absence_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    year_id INTEGER,
    threshold INTEGER,
    absence_count INTEGER,
    notified_site INTEGER DEFAULT 0,
    notified_wa INTEGER DEFAULT 0,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    title TEXT,
    body TEXT
);
