-- 009. 운영 지표 (R4, 문서 12 §2)
--
-- "판정 하나에 얼마가 들고 어디서 실패하는가"를 질의로 답하게 한다.
--   cost_usd        호출 1회 비용. 단가표(app/core/pricing.py)에 없는 모델·규칙 검증은 NULL
--                   (0으로 두면 '공짜'로 읽힌다)
--   prompt_version  프롬프트 파일 해시 앞 12자리. 프롬프트를 바꾼 뒤 실패율·비용이 어떻게
--                   변했는지 버전별로 비교한다
--   attempt         REJECT 재생성 회차 (0 = 첫 시도)
-- Validator(C6)도 행을 남긴다: model='rules', ok=거부 여부, error=거부 사유.

ALTER TABLE ai_traces
    ADD COLUMN IF NOT EXISTS cost_usd       numeric(12, 6) CHECK (cost_usd IS NULL OR cost_usd >= 0),
    ADD COLUMN IF NOT EXISTS prompt_version text,
    ADD COLUMN IF NOT EXISTS attempt        smallint NOT NULL DEFAULT 0 CHECK (attempt >= 0);

CREATE INDEX IF NOT EXISTS idx_traces_chain_version ON ai_traces (chain, prompt_version);

-- 분석별 집계에 비용과 재생성 횟수를 더한다. 기존 열 순서는 그대로 두고 뒤에 붙인다
-- (CREATE OR REPLACE VIEW는 열을 뒤에 추가하는 것만 허용한다).
CREATE OR REPLACE VIEW analysis_trace_summary AS
SELECT
    analysis_id,
    -- chain_calls·failures는 LLM 호출만 센다(003과 같은 의미). 규칙 검증 거부는 validator_rejects로 따로.
    count(*) FILTER (WHERE model <> 'rules')            AS chain_calls,
    count(*) FILTER (WHERE NOT ok AND model <> 'rules') AS failures,
    sum(input_tokens)                          AS input_tokens,
    sum(output_tokens)                         AS output_tokens,
    sum(input_tokens + output_tokens)          AS total_tokens,
    sum(latency_ms)                            AS total_latency_ms,
    max(latency_ms)                            AS slowest_call_ms,
    min(created_at)                            AS started_at,
    max(created_at)                            AS finished_at,
    sum(cost_usd)                              AS cost_usd,
    count(*) FILTER (WHERE chain = 'C6_validator' AND NOT ok) AS validator_rejects,
    count(*) FILTER (WHERE chain = 'C6_validator' AND attempt > 0) AS regenerations
FROM ai_traces
WHERE analysis_id IS NOT NULL
GROUP BY analysis_id;
