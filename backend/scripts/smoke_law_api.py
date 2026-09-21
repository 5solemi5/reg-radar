"""법제처 OPEN API 실연결 스모크 테스트.

사용법:
    cp .env.example .env   # LAW_API_OC 채우기
    .venv/bin/python scripts/smoke_law_api.py "근로기준법"
"""

import asyncio
import sys
from datetime import date, timedelta

from app.adapters.law.client import LawApiClient, LawApiError
from app.adapters.law.store import FileSnapshotStore
from app.core.config import get_settings
from app.diff.engine import detect_delegation


async def main(query: str | None) -> int:
    settings = get_settings()
    if not settings.law_api_enabled:
        print("✗ LAW_API_OC가 없습니다. .env에 설정하세요.")
        return 1

    try:
        async with LawApiClient(settings=settings) as client:
            if query:
                laws = await client.search_laws(query=query, display=5)
                print(f"▶ '{query}' 검색 결과 {len(laws)}건")
            else:
                since = date.today() - timedelta(days=90)
                laws = await client.search_laws(effective_from=since, display=5)
                print(f"▶ {since} 이후 시행 법령 {len(laws)}건")

            for law in laws:
                print(f"  · {law.law_name} ({law.law_type}) "
                      f"시행 {law.effective_date} · {law.ministry} · {law.revision_type}")

            if not laws:
                print("✗ 결과가 없습니다. OC 값 또는 검색 조건을 확인하세요.")
                return 1

            target = laws[0]
            print(f"\n▶ 본문 조회: {target.law_name}")
            snapshot = await client.fetch_law_detail(target)
            articles = [a for a in snapshot.articles if not a.is_supplementary]
            print(f"  조문 {len(articles)}건 · 부칙 {len(snapshot.articles) - len(articles)}건")

            delegating = [a for a in articles if detect_delegation(a.original_text)]
            print(f"  하위법령 위임 조문 {len(delegating)}건 (Q5 감지)")
            for a in delegating[:3]:
                print(f"    · {a.article_no} → {detect_delegation(a.original_text)}")

            if articles:
                first = articles[0]
                print(f"\n▶ 샘플 조문 {first.article_no} ({first.article_title})")
                print("  " + first.original_text[:200].replace("\n", "\n  "))

            path = FileSnapshotStore().save(snapshot)
            print(f"\n✓ snapshot 저장: {path}")
            return 0

    except LawApiError as exc:
        print(f"✗ {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None)))
