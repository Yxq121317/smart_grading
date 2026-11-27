-- 智能阅卷项目：题库基础表
-- 数据库：Mark（PostgreSQL 18 + pgvector）

CREATE TABLE IF NOT EXISTS exams (
    id BIGSERIAL PRIMARY KEY,
    source_index SMALLINT NOT NULL UNIQUE,
    exam_code TEXT NOT NULL UNIQUE,
    year SMALLINT NOT NULL,
    paper_name TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '语文',
    category TEXT NOT NULL DEFAULT '论述类文本阅读',
    compilation TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_header TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS passages (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    order_index SMALLINT NOT NULL DEFAULT 1,
    title TEXT,
    author TEXT,
    content TEXT NOT NULL,
    paragraphs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (exam_id, order_index)
);

CREATE TABLE IF NOT EXISTS questions (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    passage_id BIGINT REFERENCES passages(id) ON DELETE SET NULL,
    question_number SMALLINT NOT NULL,
    order_index SMALLINT NOT NULL,
    stem TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('single_choice', 'subjective')),
    options JSONB NOT NULL DEFAULT '[]'::jsonb,
    correct_answer TEXT,
    answer_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation TEXT,
    max_score NUMERIC(4, 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (exam_id, question_number)
);

CREATE INDEX IF NOT EXISTS idx_exams_year ON exams (year);
CREATE INDEX IF NOT EXISTS idx_passages_exam_id ON passages (exam_id);
CREATE INDEX IF NOT EXISTS idx_questions_exam_id ON questions (exam_id);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions (question_type);

CREATE TABLE IF NOT EXISTS import_runs (
    id BIGSERIAL PRIMARY KEY,
    source_file TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    exam_count INTEGER NOT NULL,
    question_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 班级与学生

CREATE TABLE IF NOT EXISTS classes (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    grade TEXT,
    subject TEXT NOT NULL DEFAULT '语文',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS students (
    id BIGSERIAL PRIMARY KEY,
    class_id BIGINT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    student_no TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 答卷与学生答案

CREATE TABLE IF NOT EXISTS submissions (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'api'
        CHECK (source IN ('api', 'synthetic', 'import')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'grading', 'awaiting_review', 'completed', 'failed')),
    total_score NUMERIC(6, 1),
    max_score NUMERIC(6, 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    graded_at TIMESTAMPTZ,
    UNIQUE (exam_id, student_id)
);

CREATE TABLE IF NOT EXISTS student_answers (
    id BIGSERIAL PRIMARY KEY,
    submission_id BIGINT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    selected_options JSONB NOT NULL DEFAULT '[]'::jsonb,
    answer_text TEXT,
    synthetic_profile TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (submission_id, question_id)
);

-- 评分细则

CREATE TABLE IF NOT EXISTS rubrics (
    id BIGSERIAL PRIMARY KEY,
    question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    points JSONB NOT NULL,
    total_score NUMERIC(5, 1) NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('ai', 'teacher', 'import')),
    instruction TEXT,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (question_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_rubrics_active
    ON rubrics (question_id)
    WHERE active;

-- 批改运行与结果

CREATE TABLE IF NOT EXISTS grading_runs (
    id BIGSERIAL PRIMARY KEY,
    submission_id BIGINT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    rubric_version_id BIGINT REFERENCES rubrics(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'awaiting_review', 'completed', 'failed')),
    graph_thread_id TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    error TEXT,
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_grading_runs_submission
    ON grading_runs (submission_id, created_at DESC);

CREATE TABLE IF NOT EXISTS grading_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES grading_runs(id) ON DELETE CASCADE,
    question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    rubric_id BIGINT REFERENCES rubrics(id) ON DELETE SET NULL,
    ai_score NUMERIC(5, 1) NOT NULL,
    max_score NUMERIC(5, 1) NOT NULL,
    confidence NUMERIC(4, 3) NOT NULL,
    needs_review BOOLEAN NOT NULL DEFAULT false,
    rationale TEXT,
    point_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    knowledge_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_type TEXT,
    error_evidence TEXT,
    final_score NUMERIC(5, 1),
    reviewed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, question_id)
);

-- 教师修正与校准

CREATE TABLE IF NOT EXISTS teacher_corrections (
    id BIGSERIAL PRIMARY KEY,
    result_id BIGINT NOT NULL REFERENCES grading_results(id) ON DELETE CASCADE,
    teacher_name TEXT,
    instruction TEXT,
    old_score NUMERIC(5, 1),
    new_score NUMERIC(5, 1),
    old_rationale TEXT,
    new_rationale TEXT,
    old_rubric JSONB,
    new_rubric JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_teacher_corrections_result
    ON teacher_corrections (result_id);

CREATE TABLE IF NOT EXISTS calibration_logs (
    id BIGSERIAL PRIMARY KEY,
    exam_id BIGINT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    instruction TEXT NOT NULL,
    old_rubric_id BIGINT REFERENCES rubrics(id),
    new_rubric_id BIGINT REFERENCES rubrics(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 错因与报告

CREATE TABLE IF NOT EXISTS error_categories (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id BIGSERIAL PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('class', 'student', 'exam')),
    scope_id BIGINT NOT NULL,
    exam_id BIGINT REFERENCES exams(id) ON DELETE CASCADE,
    grading_run_id BIGINT REFERENCES grading_runs(id) ON DELETE SET NULL,
    content_markdown TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE reports
    ADD COLUMN IF NOT EXISTS grading_run_id BIGINT
    REFERENCES grading_runs(id) ON DELETE SET NULL;
