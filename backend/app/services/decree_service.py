"""위임 하위법령 조회 (ADR-025).

모법 조문에 위임 문구가 있으면 해당 시행령·시행규칙을 받아 그 조문을 찾아준다.
법령 단위로 캐시한다. 한 번 분석에 같은 법의 조문 여러 건을 보므로, 조문마다
시행령을 다시 받으면 법제처 호출이 조문 수만큼 늘어난다.
"""

from __future__ import annotations

import logging

from app.adapters.law.client import LawApiClient, LawApiError
from app.adapters.law.decree import decree_names, pair_articles
from app.adapters.law.models import LawSnapshot
from app.domain.context import DelegatedContext

logger = logging.getLogger(__name__)


class DecreeResolver:
    """모법 조문 → 위임된 하위법령 조문.

    조회 실패는 빈 목록으로 흡수한다. 하위법령을 못 받으면 위임이 보류 근거로
    남을 뿐이며(기존 동작), 분석 전체를 실패시킬 이유가 없다 (ER-003).
    """

    def __init__(self, client: LawApiClient) -> None:
        self._client = client
        self._cache: dict[str, LawSnapshot | None] = {}

    async def _snapshot(self, decree_name: str) -> LawSnapshot | None:
        if decree_name in self._cache:
            return self._cache[decree_name]

        snapshot: LawSnapshot | None = None
        try:
            # 클라이언트가 열려 있는지 먼저 본다. LawApiClient는 async with 밖에서
            # LawApiError를 던지는데, 그것을 아래 except가 삼키면 '조회 실패'와
            # '쓰는 법이 틀렸다'가 구분되지 않아 기능이 조용히 꺼진다.
            _ = self._client.client
        except LawApiError as exc:
            raise RuntimeError(
                "DecreeResolver에 열리지 않은 LawApiClient가 전달됐습니다. "
                "async with 블록 안에서 만든 클라이언트를 넘기십시오."
            ) from exc

        try:
            found = await self._client.search_laws(query=decree_name, display=5)
            # 부분일치가 섞여 오므로 이름이 정확히 같은 것만 쓴다.
            # "최저임금법 시행령"을 찾는데 "최저임금법 시행규칙"을 집으면 안 된다.
            hit = next((law for law in found if law.law_name == decree_name), None)
            if hit is not None:
                snapshot = await self._client.fetch_law_detail(hit)
        except LawApiError as exc:
            logger.warning("하위법령 조회 실패 name=%s err=%s", decree_name, exc)

        self._cache[decree_name] = snapshot
        return snapshot

    async def resolve(
        self,
        law_name: str,
        article_no: str,
        article_title: str | None,
        delegation_targets: list[str],
    ) -> list[DelegatedContext]:
        if not delegation_targets:
            return []

        resolved: list[DelegatedContext] = []
        for decree_name in decree_names(law_name, delegation_targets):
            snapshot = await self._snapshot(decree_name)
            if snapshot is None:
                continue
            resolved.extend(pair_articles(article_no, article_title, snapshot))

        if resolved:
            logger.info(
                "위임 조문 확보 law=%s article=%s count=%d",
                law_name,
                article_no,
                len(resolved),
            )
        return resolved


class NullDecreeResolver:
    """하위법령을 붙이지 않는다. 테스트와 기능 끄기용."""

    async def resolve(
        self,
        law_name: str,
        article_no: str,
        article_title: str | None,
        delegation_targets: list[str],
    ) -> list[DelegatedContext]:
        return []
