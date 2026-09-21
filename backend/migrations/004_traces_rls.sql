-- ai_traces 행 수준 보안 — Supabase 전용
-- trace에도 user_id가 있으므로 다른 사용자의 실행 기록이 새면 안 된다 (NFR-007).

ALTER TABLE ai_traces ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS traces_own ON ai_traces;
CREATE POLICY traces_own ON ai_traces
    FOR ALL USING (user_id = auth.uid()::text)
    WITH CHECK (user_id = auth.uid()::text);
