-- 행 수준 보안 (NFR-007) — Supabase 전용
--
-- 왜 필요한가: 애플리케이션은 이미 모든 조회에 user_id를 강제한다
-- (app/repositories/base.py 참조). RLS는 그 방어선이 뚫렸을 때를 위한 두 번째
-- 층이다. Supabase는 anon key로 DB에 직접 접근하는 경로가 열려 있으므로,
-- 서버 코드만 믿는 것으로는 부족하다.
--
-- 주의: 백엔드는 service_role 연결을 쓰며 service_role은 RLS를 우회한다.
-- 즉 이 정책은 '브라우저가 anon key로 직접 접근하는 경로'를 막는 것이 목적이다.
--
-- 로컬 Postgres에는 auth.uid()가 없으므로 이 파일은 Supabase에서만 적용한다.

ALTER TABLE profiles          ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses          ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_results  ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_regulations ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback          ENABLE ROW LEVEL SECURITY;
ALTER TABLE hold_revisions    ENABLE ROW LEVEL SECURITY;

-- law_snapshots는 공개 법령 데이터이므로 사용자별 격리 대상이 아니다.
-- 다만 쓰기는 서버만 할 수 있어야 한다.
ALTER TABLE law_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profiles_own ON profiles;
CREATE POLICY profiles_own ON profiles
    FOR ALL USING (user_id = auth.uid()::text)
    WITH CHECK (user_id = auth.uid()::text);

DROP POLICY IF EXISTS analyses_own ON analyses;
CREATE POLICY analyses_own ON analyses
    FOR ALL USING (user_id = auth.uid()::text)
    WITH CHECK (user_id = auth.uid()::text);

DROP POLICY IF EXISTS results_own ON analysis_results;
CREATE POLICY results_own ON analysis_results
    FOR ALL USING (user_id = auth.uid()::text)
    WITH CHECK (user_id = auth.uid()::text);

DROP POLICY IF EXISTS saved_own ON saved_regulations;
CREATE POLICY saved_own ON saved_regulations
    FOR ALL USING (user_id = auth.uid()::text)
    WITH CHECK (user_id = auth.uid()::text);

DROP POLICY IF EXISTS feedback_own ON feedback;
CREATE POLICY feedback_own ON feedback
    FOR ALL USING (user_id = auth.uid()::text)
    WITH CHECK (user_id = auth.uid()::text);

DROP POLICY IF EXISTS revisions_own ON hold_revisions;
CREATE POLICY revisions_own ON hold_revisions
    FOR ALL USING (user_id = auth.uid()::text)
    WITH CHECK (user_id = auth.uid()::text);

-- 법령 snapshot은 인증된 사용자면 읽을 수 있고, 쓰기는 서버(service_role)만.
DROP POLICY IF EXISTS snapshots_read ON law_snapshots;
CREATE POLICY snapshots_read ON law_snapshots
    FOR SELECT USING (auth.role() = 'authenticated');
