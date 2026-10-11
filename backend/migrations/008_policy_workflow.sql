-- 008. 사내 규정 개정 초안 승인 흐름과 감사 로그 (문서 12 §4, R3)
--
-- Agent는 규정을 고치지 않는다. 초안을 내고, 승인은 준법감시인이 한다.
-- 애플리케이션(app/policies/workflow.py)이 같은 규칙을 검사하지만, 코드가 뚫려도
-- DB가 막도록 핵심 규칙을 제약·트리거로 한 번 더 건다.
--
--   four_eyes                       제출자 ≠ 결정자
--   decided_requires_decider        APPROVED·REJECTED에는 결정자가 있어야 한다
--   policy_audit_events 트리거      감사 이벤트 UPDATE·DELETE 거부 (추가 전용)
--   (org_id, seq) 기본키             조직별 해시 체인에 빈 칸·중복이 없다

CREATE TABLE IF NOT EXISTS org_members (
    org_id      text        NOT NULL,
    user_id     text        NOT NULL,
    role        text        NOT NULL CHECK (role IN ('STAFF', 'COMPLIANCE_OFFICER')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

COMMENT ON TABLE org_members IS
    '조직 구성원과 역할. 승인 권한은 요청 헤더가 아니라 이 테이블에서 읽는다.';

CREATE TABLE IF NOT EXISTS policy_drafts (
    draft_id       uuid        PRIMARY KEY,
    org_id         text        NOT NULL,
    law_ref        text        NOT NULL,
    policy_ref     text        NOT NULL,
    relation       text        NOT NULL CHECK (relation IN ('CONFLICT', 'UPDATE_RECOMMENDED')),
    current_text   text        NOT NULL,
    proposed_text  text        NOT NULL CHECK (btrim(proposed_text) <> ''),
    issues         text[]      NOT NULL DEFAULT '{}',
    state          text        NOT NULL DEFAULT 'DRAFTED'
                   CHECK (state IN ('DRAFTED', 'IN_REVIEW', 'APPROVED', 'REJECTED')),
    created_by     text        NOT NULL,
    submitted_by   text,
    decided_by     text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT four_eyes CHECK (decided_by IS NULL OR decided_by <> submitted_by),
    CONSTRAINT decided_requires_decider
        CHECK (state NOT IN ('APPROVED', 'REJECTED') OR decided_by IS NOT NULL),
    CONSTRAINT review_requires_submitter
        CHECK (state = 'DRAFTED' OR submitted_by IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_policy_drafts_org_state ON policy_drafts (org_id, state);

CREATE TABLE IF NOT EXISTS policy_draft_comments (
    comment_id  bigserial   PRIMARY KEY,
    draft_id    uuid        NOT NULL REFERENCES policy_drafts (draft_id),
    user_id     text        NOT NULL,
    body        text        NOT NULL CHECK (btrim(body) <> ''),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS policy_audit_events (
    org_id     text     NOT NULL,
    seq        bigint   NOT NULL CHECK (seq >= 0),
    at         text     NOT NULL,  -- 해시에 들어간 문자열 그대로. timestamptz로 바꾸면 왕복 시 표기가 달라져 검증이 깨진다
    actor      text     NOT NULL,
    role       text     NOT NULL,
    action     text     NOT NULL,
    draft_id   uuid     NOT NULL,
    before     text,
    after      text,
    detail     jsonb    NOT NULL DEFAULT '{}'::jsonb,
    prev_hash  char(64) NOT NULL,
    hash       char(64) NOT NULL UNIQUE,
    PRIMARY KEY (org_id, seq)
);

CREATE OR REPLACE FUNCTION policy_audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'policy_audit_events는 추가 전용이다 (% 거부)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_policy_audit_events_append_only ON policy_audit_events;
CREATE TRIGGER trg_policy_audit_events_append_only
    BEFORE UPDATE OR DELETE ON policy_audit_events
    FOR EACH ROW EXECUTE FUNCTION policy_audit_events_append_only();

COMMENT ON TABLE policy_audit_events IS
    '추가 전용 해시 체인. hash = sha256(이전 hash를 포함한 이벤트 본문). 검증: app/policies/workflow.py::verify_chain';
