-- AI 실행 추적 (NFR-009)
--
-- 왜 테이블로 두는가: 로그만으로는 "이 분석이 토큰을 얼마나 썼는가", "어떤
-- 체인이 느린가", "Validator가 무엇을 얼마나 막았는가"를 집계할 수 없다.
-- 04 설계서 §11이 요구하는 관측 항목을 질의 가능한 형태로 보존한다.
--
-- 민감정보 보호: 프롬프트 원문과 모델 응답 전문은 저장하지 않는다. 사용자
-- 프로필과 법령 원문이 그대로 남으면 관측성 도구가 개인정보 저장소가 된다
-- (04 설계서 §9).

CREATE TABLE IF NOT EXISTS ai_traces (
    trace_row_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id       uuid NOT NULL,
    analysis_id    uuid REFERENCES analyses (analysis_id) ON DELETE CASCADE,
    user_id        text NOT NULL,

    -- 어떤 조문을 다뤘는지. 원문이 아니라 식별자만 남긴다.
    law_id         text,
    article_no     text,

    chain          text NOT NULL,
    model          text NOT NULL,
    latency_ms     integer NOT NULL CHECK (latency_ms >= 0),
    ok             boolean NOT NULL,
    error          text,
    input_tokens   integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens  integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),

    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_traces_analysis ON ai_traces (analysis_id);
CREATE INDEX IF NOT EXISTS idx_traces_trace ON ai_traces (trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_created ON ai_traces (created_at DESC);

-- 분석별 집계. 대시보드나 운영 리포트가 결과 전체를 읽지 않아도 되게 한다.
CREATE OR REPLACE VIEW analysis_trace_summary AS
SELECT
    analysis_id,
    count(*)                                   AS chain_calls,
    count(*) FILTER (WHERE NOT ok)             AS failures,
    sum(input_tokens)                          AS input_tokens,
    sum(output_tokens)                         AS output_tokens,
    sum(input_tokens + output_tokens)          AS total_tokens,
    sum(latency_ms)                            AS total_latency_ms,
    max(latency_ms)                            AS slowest_call_ms,
    min(created_at)                            AS started_at,
    max(created_at)                            AS finished_at
FROM ai_traces
WHERE analysis_id IS NOT NULL
GROUP BY analysis_id;
