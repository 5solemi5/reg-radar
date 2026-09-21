-- 006. 위임된 하위법령 근거 (ADR-025)
--
-- 모법 조문의 인용과 시행령 조문의 인용을 같은 칸에 담으면, 사용자가 모법 원문에서
-- 찾을 수 없는 문장을 모법 인용으로 보게 된다. 법적 근거는 출처가 분명해야 하므로
-- (BR-001) 별도 칼럼으로 분리한다.

ALTER TABLE analysis_results
    ADD COLUMN IF NOT EXISTS delegated_evidence jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN analysis_results.delegated_evidence IS
    '위임된 하위법령 근거. [{law_id, law_name, law_type, article_no, article_title, '
    'source_url, quoted_spans, resolves_criterion}]. 모법 근거(law_* 칼럼)와 분리해 표시한다.';
