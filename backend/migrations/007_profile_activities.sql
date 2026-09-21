-- 007. 프로필 사업 활동 (ADR-033)
--
-- 홀드아웃 평가에서 놓친 보류가 전부 같은 유형이었다. 조문은 명확한데 '이 회사가
-- 도급을 주는가', '외국인근로자를 고용하는가'를 프로필이 말해 주지 않아 판정할 수
-- 없었다. 판정 능력이 아니라 입력 설계가 병목이었다.
--
-- {"SUBCONTRACTING": "YES", "FOOD_BUSINESS": "NO", ...} 형태로 저장한다.
-- 키가 없으면 '모름'이다 — '아니오'와 다르다. 답하지 않은 것을 부정으로 읽으면
-- 건너뛴 사용자에게 '무관'이라고 단정하게 된다.

ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS activities jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN profiles.activities IS
    '사업 활동 응답. {활동코드: YES|NO|UNKNOWN}. 키가 없으면 UNKNOWN(미응답)이며 NO와 구분된다.';
