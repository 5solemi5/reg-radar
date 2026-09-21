"""법제처 OPEN API HTTP 클라이언트.

ER-001: 호출 실패 시 재시도하되, 끝내 실패하면 예외를 올린다.
절대 임의의 법령 사실값으로 대체하지 않는다.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.adapters.law.models import LawSnapshot, LawSummary
from app.adapters.law.parser import parse_law_detail, parse_law_list, parse_total_count
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)


class LawApiError(RuntimeError):
    """법제처 API 호출 실패. 상위 계층은 이를 분석 실패로 처리해야 한다 (ER-001)."""


class LawApiClient:
    """lawSearch.do / lawService.do 얇은 래퍼."""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        if not self.settings.law_api_oc:
            raise LawApiError("LAW_API_OC가 설정되지 않았습니다. .env를 확인하세요.")
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> LawApiClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.law_api_base_url,
                timeout=self.settings.law_api_timeout_seconds,
                headers={"User-Agent": "reg-radar/0.1 (+regulatory-change-assistant)"},
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise LawApiError("LawApiClient는 async with 블록 안에서 사용해야 합니다.")
        return self._client

    def _params(self, **extra: object) -> dict[str, str]:
        params: dict[str, str] = {"OC": self.settings.law_api_oc, "type": "XML"}
        params.update({k: str(v) for k, v in extra.items() if v is not None})
        return params

    async def _get(self, path: str, params: dict[str, str]) -> str:
        @retry(
            stop=stop_after_attempt(self.settings.law_api_max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=4),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,
        )
        async def _call() -> str:
            response = await self.client.get(path, params=params)
            response.raise_for_status()
            return response.text

        try:
            return await _call()
        except Exception as exc:
            logger.warning("법제처 API 호출 실패: path=%s params=%s err=%s", path, params, exc)
            raise LawApiError(f"법제처 API 호출 실패: {exc}") from exc

    # ── 목록 조회 ──────────────────────────────────────────────────────

    async def search_laws(
        self,
        *,
        query: str | None = None,
        effective_from: date | None = None,
        effective_to: date | None = None,
        display: int = 20,
        page: int = 1,
    ) -> list[LawSummary]:
        """법령 목록 검색. 시행일 범위로 '최근 규제 변화' 후보를 만든다 (UC-02)."""
        ef_yd = None
        if effective_from and effective_to:
            ef_yd = f"{effective_from:%Y%m%d}~{effective_to:%Y%m%d}"
        elif effective_from:
            ef_yd = f"{effective_from:%Y%m%d}~{date.today():%Y%m%d}"

        params = self._params(
            target="law",
            query=query,
            efYd=ef_yd,
            display=min(display, 100),
            page=page,
            sort="ddes",  # 시행일 내림차순
        )
        return parse_law_list(await self._get("/lawSearch.do", params))

    async def count_laws(self, **kwargs: object) -> int:
        params = self._params(target="law", display=1, page=1, **kwargs)
        return parse_total_count(await self._get("/lawSearch.do", params))

    # ── 본문 조회 ──────────────────────────────────────────────────────

    async def fetch_law_detail(self, summary: LawSummary) -> LawSnapshot:
        """법령 본문 전체를 조회해 snapshot을 만든다 (FR-004, AP-07)."""
        key, value = summary.fetch_key
        params = self._params(target="law", **{key: value})
        xml = await self._get("/lawService.do", params)
        snapshot = parse_law_detail(xml, source_url=self.public_url(summary))
        # 목록에서만 제공되는 메타(소관부처·제개정구분 등)를 보강한다.
        return snapshot.model_copy(
            update={
                "mst": snapshot.mst or summary.mst,
                "law_type": snapshot.law_type or summary.law_type,
                "ministry": snapshot.ministry or summary.ministry,
                "revision_type": snapshot.revision_type or summary.revision_type,
                "promulgation_date": snapshot.promulgation_date or summary.promulgation_date,
                "effective_date": snapshot.effective_date or summary.effective_date,
            }
        )

    def public_url(self, summary: LawSummary) -> str:
        """사용자에게 보여줄 법제처 공식 링크 (FR-012)."""
        key, value = summary.fetch_key
        return (
            f"{self.settings.law_api_base_url}/lawService.do"
            f"?OC={self.settings.law_api_oc}&target=law&{key}={value}&type=HTML"
        )
