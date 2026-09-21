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
