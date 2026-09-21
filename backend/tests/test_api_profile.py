"""프로필 API 테스트 (FR-001, FR-002, NFR-007)."""

VALID = {
    "job": "HR 담당자",
    "industry": "IT 서비스",
    "company_size": "MEDIUM",
    "employee_count": 80,
    "interests": ["노동"],
}


class TestProfileLifecycle:
    async def test_프로필이_없으면_404(self, client):
        """프론트는 이 신호로 온보딩을 먼저 띄운다 (FR-002 AC)."""
        r = await client.get("/api/v1/profile")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    async def test_생성후_조회(self, client):
        assert (await client.put("/api/v1/profile", json=VALID)).status_code == 200
        r = await client.get("/api/v1/profile")
        assert r.status_code == 200
        body = r.json()
        assert body["job"] == "HR 담당자"
        assert body["employee_count"] == 80
        assert body["user_id"] == "user-a"

    async def test_부분수정(self, client):
        await client.put("/api/v1/profile", json=VALID)
        r = await client.patch("/api/v1/profile", json={"employee_count": 150})
        assert r.status_code == 200
        assert r.json()["employee_count"] == 150
        assert r.json()["job"] == "HR 담당자"  # 나머지는 유지

    async def test_상시근로자_수를_비울_수_있다(self, client):
        """규모 미상은 유효한 상태이며 보류 사유가 된다."""
        await client.put("/api/v1/profile", json=VALID)
        r = await client.patch("/api/v1/profile", json={"employee_count": None})
        assert r.status_code == 200
        assert r.json()["employee_count"] is None

    async def test_생성전_PATCH는_404(self, client):
        assert (await client.patch("/api/v1/profile", json={"job": "x"})).status_code == 404

    async def test_재저장해도_created_at은_유지된다(self, client):
        first = (await client.put("/api/v1/profile", json=VALID)).json()
        second = (await client.put("/api/v1/profile", json={**VALID, "job": "총무"})).json()
        assert second["created_at"] == first["created_at"]
        assert second["job"] == "총무"


class TestValidation:
    async def test_필수값_누락은_422(self, client):
        r = await client.put("/api/v1/profile", json={"job": "HR"})
        assert r.status_code == 422

    async def test_공백만_입력하면_거부(self, client):
        r = await client.put("/api/v1/profile", json={**VALID, "job": "   "})
        assert r.status_code == 422

    async def test_알_수_없는_필드는_거부(self, client):
        r = await client.put("/api/v1/profile", json={**VALID, "is_admin": True})
        assert r.status_code == 422

    async def test_잘못된_company_size는_거부(self, client):
        r = await client.put("/api/v1/profile", json={**VALID, "company_size": "HUGE"})
        assert r.status_code == 422

    async def test_음수_인원은_거부(self, client):
        r = await client.put("/api/v1/profile", json={**VALID, "employee_count": -1})
        assert r.status_code == 422


class TestIsolation:
    """NFR-007. 사용자별 데이터가 섞이지 않아야 한다."""

    async def test_다른_사용자의_프로필은_보이지_않는다(self, client):
        await client.put("/api/v1/profile", json=VALID)

        r = await client.get("/api/v1/profile", headers={"X-User-Id": "user-b"})
        assert r.status_code == 404

    async def test_각자의_프로필이_독립적으로_저장된다(self, client):
        await client.put("/api/v1/profile", json=VALID)
        await client.put(
            "/api/v1/profile",
            json={**VALID, "job": "쇼핑몰 운영", "employee_count": 4},
            headers={"X-User-Id": "user-b"},
        )

        a = (await client.get("/api/v1/profile")).json()
        b = (await client.get("/api/v1/profile", headers={"X-User-Id": "user-b"})).json()
        assert a["job"] == "HR 담당자" and a["employee_count"] == 80
        assert b["job"] == "쇼핑몰 운영" and b["employee_count"] == 4


class TestHealth:
    async def test_설정_상태를_보고하되_키는_노출하지_않는다(self, client):
        r = await client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["law_api_configured"] is True
        assert body["llm_configured"] is True
        # 키 값 자체가 응답에 없어야 한다 (NFR-008)
        assert "testoc" not in r.text and "test-key" not in r.text


class TestPendingMigrationDetection:
    """무료 호스팅은 pre-deploy를 지원하지 않아 마이그레이션이 자동으로 돌지 않는다.

    그 사실이 조용하면 스키마가 코드보다 뒤처진 채 서비스가 정상인 척 뜨고,
    새 칼럼을 읽는 순간 UndefinedColumnError로 처음 드러난다.
    """

    async def test_추적_테이블이_없으면_전부_미적용으로_본다(self):
        from app.repositories.schema_state import migration_filenames, pending_migrations

        class NoTable:
            async def fetch(self, *_):
                raise RuntimeError('relation "schema_migrations" does not exist')

        assert await pending_migrations(NoTable()) == migration_filenames()

    async def test_모두_적용됐으면_빈_목록(self):
        from app.repositories.schema_state import migration_filenames, pending_migrations

        class AllApplied:
            async def fetch(self, *_):
                return [{"filename": n} for n in migration_filenames()]

        assert await pending_migrations(AllApplied()) == []

    async def test_누락된_것만_돌려준다(self):
        from app.repositories.schema_state import migration_filenames, pending_migrations

        names = migration_filenames()
        assert len(names) >= 2, "이 테스트는 마이그레이션이 2개 이상이어야 의미가 있다"

        class PartiallyApplied:
            async def fetch(self, *_):
                return [{"filename": n} for n in names[:-1]]

        assert await pending_migrations(PartiallyApplied()) == [names[-1]]

    async def test_조회_실패는_빈_목록으로_흡수한다(self):
        """이 정보 때문에 헬스 체크가 죽으면 안 된다.

        없는 것을 있다고 말하는 쪽이 모르는 것보다 나쁘다.
        """
        from app.repositories.schema_state import pending_migrations

        class Broken:
            async def fetch(self, *_):
                raise RuntimeError("연결이 끊겼습니다")

        assert await pending_migrations(Broken()) == []


class TestBusinessActivities:
    """적용 여부를 가르지만 업종만으로는 알 수 없는 사실을 프로필로 받는다 (ADR-033).

    홀드아웃 평가에서 놓친 보류가 전부 이 유형이었다. 조문은 명확한데 '이 회사가
    도급을 주는가'를 프로필이 말해 주지 않아 판정할 수 없었다.
    """

    async def test_질문_목록은_인증_없이_받을_수_있다(self, client):
        r = await client.get("/api/v1/profile/activities")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 5
        for item in items:
            assert item["question"].endswith("?"), "질문은 물음표로 끝나야 한다"
            assert item["hint"], "판단을 돕는 한 줄이 있어야 한다"

    async def test_질문이_법률_용어를_쓰지_않는다(self, client):
        """'귀사가 원사업자입니까'는 법률 용어를 아는 사람만 답할 수 있다."""
        jargon = ["원사업자", "수급사업자", "통신판매업자", "정보통신서비스 제공자",
                  "사업장폐기물배출자", "도급인"]
        items = (await client.get("/api/v1/profile/activities")).json()["items"]
        for item in items:
            for word in jargon:
                assert word not in item["question"], (
                    f"질문에 법률 용어 '{word}'가 들어 있습니다: {item['question']}"
                )

    async def test_모든_활동에_질문이_있다(self, client):
        """활동 코드만 늘리고 질문을 안 만들면 사용자는 답할 기회가 없다."""
        from app.domain.enums import BusinessActivity

        items = (await client.get("/api/v1/profile/activities")).json()["items"]
        assert {i["activity"] for i in items} == {a.value for a in BusinessActivity}

    async def test_저장하고_돌려받는다(self, client):
        payload = {
            **VALID,
            "activities": {"SUBCONTRACTING": "YES", "FOOD_BUSINESS": "NO"},
        }
        r = await client.put("/api/v1/profile", json=payload)
        assert r.status_code == 200
        assert r.json()["activities"] == {"SUBCONTRACTING": "YES", "FOOD_BUSINESS": "NO"}

    async def test_보내지_않으면_빈_값이다(self, client):
        r = await client.put("/api/v1/profile", json=VALID)
        assert r.json()["activities"] == {}

    async def test_잘못된_코드는_거부한다(self, client):
        r = await client.put(
            "/api/v1/profile", json={**VALID, "activities": {"없는활동": "YES"}}
        )
        assert r.status_code == 422

    async def test_잘못된_답은_거부한다(self, client):
        r = await client.put(
            "/api/v1/profile", json={**VALID, "activities": {"SUBCONTRACTING": "아마도"}}
        )
        assert r.status_code == 422


class TestActivityPromptRendering:
    """프롬프트에 '모름'이 명시적으로 적혀야 한다."""

    @staticmethod
    def _context(**activities):
        from app.domain.context import UserContext
        from app.domain.enums import ActivityAnswer, BusinessActivity, CompanySize

        return UserContext(
            job="HR 담당자",
            industry="IT 서비스",
            company_size=CompanySize.MEDIUM,
            employee_count=80,
            activities={
                BusinessActivity(k): ActivityAnswer(v) for k, v in activities.items()
            },
        )

    def test_답하지_않은_항목도_줄로_남는다(self):
        """빼면 '아니오'와 구분되지 않는다. 모델이 없는 줄을 부정으로 읽는다."""
        block = self._context(SUBCONTRACTING="YES").to_prompt_block()
        assert "- 도급·위탁: 예" in block
        assert "모름" in block, "답하지 않은 항목이 '모름'으로 드러나야 한다"

    def test_아니오와_모름이_다르게_표시된다(self):
        block = self._context(SUBCONTRACTING="NO").to_prompt_block()
        assert "- 도급·위탁: 아니오" in block
        assert "- 외국인근로자 고용: 모름" in block

    def test_모든_활동이_빠짐없이_나온다(self):
        from app.domain.activities import ACTIVITY_QUESTIONS

        block = self._context().to_prompt_block()
        for q in ACTIVITY_QUESTIONS:
            assert f"- {q.label}:" in block
