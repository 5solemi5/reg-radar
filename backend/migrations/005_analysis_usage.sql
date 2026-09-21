-- 분석 단위 사용량 (NFR-009)
--
-- ai_traces에서 집계할 수 있지만 analyses에도 비정규화해 둔다. 히스토리 목록은
-- 분석 수십 건을 한 번에 보여주는데, 그때마다 trace를 조인해 집계하면 목록
-- 조회가 무거워진다. counts를 비정규화한 것과 같은 이유다.

ALTER TABLE analyses ADD COLUMN IF NOT EXISTS chain_calls integer NOT NULL DEFAULT 0;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS total_tokens integer NOT NULL DEFAULT 0;

ALTER TABLE analyses
    DROP CONSTRAINT IF EXISTS analyses_chain_calls_check,
    ADD CONSTRAINT analyses_chain_calls_check CHECK (chain_calls >= 0);

ALTER TABLE analyses
    DROP CONSTRAINT IF EXISTS analyses_total_tokens_check,
    ADD CONSTRAINT analyses_total_tokens_check CHECK (total_tokens >= 0);
