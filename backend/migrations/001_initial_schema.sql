-- 규제 변화 AI 도우미 — 초기 스키마
-- 기획서 §9 데이터 모델 / 04 설계서 §7 저장 책임
--
-- Supabase와 로컬 Postgres 양쪽에서 동일하게 동작해야 한다.
-- Supabase 전용 기능(auth.users FK 등)은 조건부로 처리한다.

-- ─────────────────────────────────────────────────────────────────────
-- ENUM — 애플리케이션의 도메인 enum과 1:1로 대응한다.
-- 값이 어긋나면 파싱 단계에서 드러나도록 문자열이 아닌 타입으로 둔다.
-- ─────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE applicability AS ENUM ('APPLICABLE', 'HOLD', 'NOT_APPLICABLE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE action_grade AS ENUM ('ACTION', 'DECISION', 'AWARENESS');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE analysis_status AS ENUM ('CREATED', 'RUNNING', 'COMPLETED', 'FAILED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE result_status AS ENUM (
        'PENDING', 'GENERATED', 'VALIDATING', 'VALIDATED', 'HOLD', 'REJECTED'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE company_size AS ENUM ('SOLO', 'MICRO', 'SMALL', 'MEDIUM', 'LARGE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE change_type AS ENUM ('NEW', 'AMENDED', 'DELETED', 'UNCHANGED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ─────────────────────────────────────────────────────────────────────
-- profiles — 개인화 판단 기준 (FR-002)
-- user_id는 Supabase auth.users.id(uuid)와 같은 값을 쓴다. 로컬 개발에서는
-- 임의 문자열이 들어올 수 있으므로 FK를 걸지 않고 text로 둔다.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS profiles (
    user_id         text PRIMARY KEY,
    job             text NOT NULL CHECK (length(btrim(job)) > 0),
    industry        text NOT NULL CHECK (length(btrim(industry)) > 0),
    company_size    company_size NOT NULL,
    -- NULL은 '미입력'이며 유효한 상태다. 규모 조건이 있는 조문에서 보류 사유가 된다.
    employee_count  integer CHECK (employee_count IS NULL OR employee_count >= 0),
    interests       text[] NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────
-- law_snapshots — 분석 당시 공식 근거 보존 (AP-07, BR-006)
-- 과거 분석을 재현하려면 그때의 법령 원문이 남아 있어야 한다.
-- 같은 법령이라도 개정될 때마다 다른 행이 되도록 (law_id, mst)로 식별한다.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS law_snapshots (
    snapshot_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    law_id             text NOT NULL,
    mst                text,
    law_name           text NOT NULL,
    law_type           text,
    ministry           text,
    promulgation_date  date,
    effective_date     date,
    revision_type      text,
    source_url         text,
    -- 조문 배열. 개별 조문을 행으로 펼치지 않는 이유는, 이 데이터가 '분석 시점의
    -- 원본 그대로'여야 하고 조문 단위 질의가 필요 없기 때문이다.
    articles           jsonb NOT NULL DEFAULT '[]'::jsonb,
    source             text NOT NULL DEFAULT 'law.go.kr',
    fetched_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (law_id, mst)
);

CREATE INDEX IF NOT EXISTS idx_law_snapshots_law_id ON law_snapshots (law_id);

-- ─────────────────────────────────────────────────────────────────────
-- analyses — 분석 실행 단위 (FR-003)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS analyses (
    analysis_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           text NOT NULL,
    status            analysis_status NOT NULL DEFAULT 'CREATED',
    period_from       date,
    period_to         date,
    law_query         text,
    trace_id          uuid NOT NULL DEFAULT gen_random_uuid(),

    created_at        timestamptz NOT NULL DEFAULT now(),
    started_at        timestamptz,
    completed_at      timestamptz,

    laws_examined     integer NOT NULL DEFAULT 0,
    articles_changed  integer NOT NULL DEFAULT 0,
    -- 집계는 결과에서 다시 계산할 수 있지만, 대시보드가 결과 전체를 읽지 않고
    -- 요약만 보여줄 수 있어야 하므로 비정규화해 둔다.
    counts            jsonb NOT NULL DEFAULT '{}'::jsonb,
    error             text,
    snapshot_law_ids  text[] NOT NULL DEFAULT '{}',

    CHECK (period_from IS NULL OR period_to IS NULL OR period_from <= period_to)
);

CREATE INDEX IF NOT EXISTS idx_analyses_user_created
    ON analyses (user_id, created_at DESC);

-- 사용자당 진행 중인 분석은 하나만 (FR-003: 중복 실행 방지).
-- 애플리케이션에서도 막지만, 동시 요청이 겹치면 코드만으로는 뚫린다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_analyses_one_active_per_user
    ON analyses (user_id)
    WHERE status IN ('CREATED', 'RUNNING');

-- ─────────────────────────────────────────────────────────────────────
-- analysis_results — 법령별 AI 판정 (FR-007, FR-010)
-- BR-007: 적용 판정(applicability)과 행동 등급(action_grade)은 다른 축이다.
-- 보류·무관에는 행동 등급을 부여하지 않는다 — 제약으로 강제한다.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS analysis_results (
    result_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id          uuid NOT NULL REFERENCES analyses (analysis_id) ON DELETE CASCADE,
    -- 소유자 역참조. 결과 단건 조회에서 analyses를 조인하지 않고 격리를 확인한다.
    user_id              text NOT NULL,
    status               result_status NOT NULL DEFAULT 'PENDING',

    applicability        applicability NOT NULL,
    action_grade         action_grade,

    -- 법적 근거 (BR-001: 전부 법제처 snapshot에서 온 값)
    law_id               text NOT NULL,
    law_name             text NOT NULL,
    article_no           text NOT NULL,
    article_title        text,
    effective_date       date,
    ministry             text,
    source_url           text,
    -- Validator를 통과한 인용만 담긴다 (FR-021)
    quoted_spans         text[] NOT NULL DEFAULT '{}',

    -- 변경 내용 (BR-002: 코드/법제처가 만든 값)
    change_type          change_type NOT NULL,
    additions            text[] NOT NULL DEFAULT '{}',
    deletions            text[] NOT NULL DEFAULT '{}',
    delegation_targets   text[] NOT NULL DEFAULT '{}',

    -- AI 해석 (FR-020: 공식 사실 필드를 두지 않는다)
    ai_reason            text NOT NULL,
    ai_matched_conditions text[] NOT NULL DEFAULT '{}',
    ai_missing_context   text[] NOT NULL DEFAULT '{}',
    ai_impact_summary    text,
    ai_affected_work     text[] NOT NULL DEFAULT '{}',
    ai_checklist         jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- double precision을 쓰는 이유: real(float4)은 0.9를 0.8999999761581421로
    -- 돌려준다. 확신도는 임계값 비교에 쓰이므로 왕복에서 값이 변하면 안 된다.
    ai_confidence        double precision
                         CHECK (ai_confidence IS NULL OR (ai_confidence BETWEEN 0 AND 1)),
    ai_model             text,

    -- RAG 참고자료 (W5에서 채워진다)
    reference_evidence   jsonb NOT NULL DEFAULT '[]'::jsonb,

    validation           jsonb NOT NULL DEFAULT '{}'::jsonb,
    trace_id             uuid,
    created_at           timestamptz NOT NULL DEFAULT now(),

    -- BR-007 / FR-010: 확정된 '해당'에만 행동 등급이 붙는다.
    CONSTRAINT action_grade_only_when_applicable
        CHECK (action_grade IS NULL OR applicability = 'APPLICABLE'),

    -- BR-003: 보류는 무엇이 부족한지 반드시 말해야 한다.
    -- cardinality()를 쓰는 이유: 빈 배열에 array_length(arr, 1)은 0이 아니라
    -- NULL을 돌려주고, CHECK 제약은 결과가 NULL이면 통과시킨다. 즉
    -- array_length 버전은 정확히 막아야 할 케이스를 통과시킨다.
    CONSTRAINT hold_requires_missing_context
        CHECK (applicability <> 'HOLD' OR cardinality(ai_missing_context) >= 1)
);

CREATE INDEX IF NOT EXISTS idx_results_analysis ON analysis_results (analysis_id);
CREATE INDEX IF NOT EXISTS idx_results_user ON analysis_results (user_id, created_at DESC);

-- ─────────────────────────────────────────────────────────────────────
-- saved_regulations / feedback / hold_revisions
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS saved_regulations (
    saved_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     text NOT NULL,
    result_id   uuid NOT NULL REFERENCES analysis_results (result_id) ON DELETE CASCADE,
    law_id      text NOT NULL,
    law_name    text NOT NULL,
    article_no  text NOT NULL,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    -- 같은 결과를 두 번 저장할 이유가 없다.
    UNIQUE (user_id, result_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_user ON saved_regulations (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id        uuid NOT NULL REFERENCES analysis_results (result_id) ON DELETE CASCADE,
    user_id          text NOT NULL,
    helpful          boolean NOT NULL,
    correction_type  text,
    comment          text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_result ON feedback (result_id);

-- 보류 재판정 이력 (FR-008, BR-008): 기존 결과를 덮어쓰지 않고 쌓는다.
CREATE TABLE IF NOT EXISTS hold_revisions (
    revision_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    original_result_id      uuid NOT NULL REFERENCES analysis_results (result_id) ON DELETE CASCADE,
    new_result_id           uuid NOT NULL REFERENCES analysis_results (result_id) ON DELETE CASCADE,
    user_id                 text NOT NULL,
    added_context           jsonb NOT NULL DEFAULT '{}'::jsonb,
    previous_applicability  applicability NOT NULL,
    new_applicability       applicability NOT NULL,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_revisions_original ON hold_revisions (original_result_id);

-- ─────────────────────────────────────────────────────────────────────
-- updated_at 자동 갱신
-- ─────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_profiles_updated_at ON profiles;
CREATE TRIGGER trg_profiles_updated_at
    BEFORE UPDATE ON profiles
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
