"""법제처 API 클라이언트 테스트 — 네트워크는 respx로 모킹 (ER-001)."""

import datetime as dt

import httpx
import pytest
import respx

from app.adapters.law.client import LawApiClient, LawApiError
from app.adapters.law.store import FileSnapshotStore
from tests.conftest import load_fixture

BASE = "https://www.law.go.kr/DRF"


@pytest.fixture
async def client(law_settings):
    async with LawApiClient(settings=law_settings) as c:
        yield c


class TestSearch:
    @respx.mock
    async def test_시행일_범위로_검색(self, client):
        route = respx.get(f"{BASE}/lawSearch.do").mock(
            return_value=httpx.Response(200, text=load_fixture("law_search.xml"))
        )
        laws = await client.search_laws(
            effective_from=dt.date(2026, 9, 1), effective_to=dt.date(2026, 12, 31)
        )
        assert len(laws) == 2
        params = route.calls[0].request.url.params
        assert params["OC"] == "testoc"
        assert params["target"] == "law"
        assert params["efYd"] == "20260901~20261231"

    @respx.mock
    async def test_display는_100으로_제한(self, client):
        route = respx.get(f"{BASE}/lawSearch.do").mock(
            return_value=httpx.Response(200, text=load_fixture("law_search.xml"))
        )
        await client.search_laws(query="근로", display=500)
        assert route.calls[0].request.url.params["display"] == "100"


class TestFetchDetail:
    @respx.mock
    async def test_본문_조회와_메타_보강(self, client):
        respx.get(f"{BASE}/lawSearch.do").mock(
            return_value=httpx.Response(200, text=load_fixture("law_search.xml"))
        )
        respx.get(f"{BASE}/lawService.do").mock(
            return_value=httpx.Response(200, text=load_fixture("law_detail.xml"))
        )
        summary = (await client.search_laws(query="근로자참여"))[0]
        snapshot = await client.fetch_law_detail(summary)

        assert snapshot.law_name == summary.law_name
        assert snapshot.mst == "265432"
        assert snapshot.ministry == "고용노동부"
        assert snapshot.source == "law.go.kr"
        assert snapshot.source_url and "MST=265432" in snapshot.source_url
        assert len(snapshot.articles) == 3  # 조문 2 + 부칙 1


class TestFailureHandling:
    @respx.mock
    async def test_서버오류는_재시도_후_LawApiError(self, client):
        route = respx.get(f"{BASE}/lawSearch.do").mock(return_value=httpx.Response(500))
        with pytest.raises(LawApiError):
            await client.search_laws(query="근로")
        assert route.call_count == 2  # max_retries=1 → 최초 1회 + 재시도 1회

    @respx.mock
    async def test_타임아웃도_LawApiError로_변환(self, client):
        respx.get(f"{BASE}/lawSearch.do").mock(side_effect=httpx.ConnectTimeout("timeout"))
        with pytest.raises(LawApiError):
            await client.search_laws(query="근로")

    @respx.mock
    async def test_일시적_오류후_성공하면_복구(self, client):
        respx.get(f"{BASE}/lawSearch.do").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, text=load_fixture("law_search.xml")),
            ]
        )
        assert len(await client.search_laws(query="근로")) == 2

    async def test_OC_없으면_생성_단계에서_실패(self, law_settings):
        with pytest.raises(LawApiError, match="LAW_API_OC"):
            LawApiClient(settings=law_settings.model_copy(update={"law_api_oc": ""}))

    async def test_컨텍스트_밖_사용_금지(self, law_settings):
        with pytest.raises(LawApiError, match="async with"):
            await LawApiClient(settings=law_settings).search_laws(query="근로")


class TestSnapshotStore:
    @respx.mock
    async def test_저장후_복원하면_cache로_표시(self, client, tmp_path):
        respx.get(f"{BASE}/lawSearch.do").mock(
            return_value=httpx.Response(200, text=load_fixture("law_search.xml"))
        )
        respx.get(f"{BASE}/lawService.do").mock(
            return_value=httpx.Response(200, text=load_fixture("law_detail.xml"))
        )
        summary = (await client.search_laws(query="근로자참여"))[0]
        snapshot = await client.fetch_law_detail(summary)

        store = FileSnapshotStore(tmp_path)
        store.save(snapshot)
        restored = store.get(snapshot.law_id)

        assert restored is not None
        assert restored.law_name == snapshot.law_name
        assert restored.find_article("제26조").original_text == (
            snapshot.find_article("제26조").original_text
        )
        # ER-001: 원천이 캐시임을 UI가 알 수 있어야 한다.
        assert restored.source == "cache"

    def test_없는_법령은_None(self, tmp_path):
        assert FileSnapshotStore(tmp_path).get("nope") is None
