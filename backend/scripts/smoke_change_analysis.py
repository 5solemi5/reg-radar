"""실제 신구법 개정 기반 E2E 스모크.

시뮬레이션 없이, 법제처가 '이번 개정에서 바뀌었다'고 표시한 조문만 분석한다.

    .venv/bin/python scripts/smoke_change_analysis.py 근로기준법
"""

import asyncio
import sys

from app.adapters.law.client import LawApiClient, LawApiError
from app.ai.chains.base import ChainRunner
from app.ai.llm import LlmGateway
from app.core.config import get_settings
from app.diff.engine import change_from_official_marks
from app.domain.context import ContextPacket, UserContext
from app.domain.enums import Applicability, CompanySize
from app.services.analysis_service import analyze_article

PROFILES = [
    ("P01 4인 온라인 쇼핑몰 대표", UserContext(
        job="쇼핑몰 운영·총무", industry="이커머스 소매",
        company_size=CompanySize.MICRO, employee_count=4, interests=["개인정보", "노동"])),
    ("P02 80인 IT기업 HR 실무자", UserContext(
        job="HR 담당자 (채용·근태·취업규칙)", industry="IT 서비스",
        company_size=CompanySize.MEDIUM, employee_count=80, interests=["노동"])),
]

BADGE = {
    Applicability.APPLICABLE: "🔴 해당",
    Applicability.HOLD: "🟡 보류",
    Applicability.NOT_APPLICABLE: "⚪ 무관",
}


async def main(law_name: str) -> int:
    settings = get_settings()
    if not (settings.law_api_enabled and settings.llm_enabled):
        print("✗ LAW_API_OC 또는 OPENAI_API_KEY가 없습니다.")
        return 1

    try:
        async with LawApiClient(settings=settings) as client:
            laws = await client.search_laws(query=law_name, display=5)
            target = next((law for law in laws if law.law_name == law_name), None)
            if target is None:
                print(f"✗ '{law_name}' 없음. 검색결과: {[x.law_name for x in laws]}")
                return 1
            comparison = await client.fetch_old_and_new(target)
            snapshot = await client.fetch_law_detail(target)
    except LawApiError as exc:
        print(f"✗ {exc}")
        return 1

    total_articles = len([a for a in snapshot.articles if not a.is_supplementary])
    print("=" * 74)
    print(f"{comparison.law_name} 신구법 비교")
    print(f"  {comparison.old_version.effective_date} 시행  →  "
          f"{comparison.new_version.effective_date} 시행 "
          f"({comparison.new_version.revision_type})")
    print(f"  전체 조문 {total_articles}건 중 이번 개정으로 변경된 조문 "
          f"{len(comparison.changed_articles)}건")
    print("=" * 74)

    if not comparison.changed_articles:
        print("이번 개정에서 변경된 조문이 없습니다.")
        return 0

    gateway = LlmGateway(settings=settings)

    for changed in comparison.changed_articles:
        article = snapshot.find_article(changed.article_no)
        if article is None:
            print(f"\n⚠️ {changed.article_no}: 현행 본문에서 찾지 못해 건너뜁니다.")
            continue

        legal = snapshot.to_legal_context(changed.article_no)
        change = change_from_official_marks(
            before_text=changed.old_text,
            after_text=changed.new_text,
            additions=changed.additions,
            deletions=changed.deletions,
        )

        print(f"\n▼ {changed.article_no}({changed.article_title}) · {change.change_type.value}")
        for d in changed.deletions:
            print(f"    - {d}")
        for a in changed.additions:
            print(f"    + {a}")
        if change.delegation_targets:
            print(f"    위임: {change.delegation_targets}")

        for label, user in PROFILES:
            packet = ContextPacket(user=user, law=legal, change=change, rag=[])
            try:
                outcome = await analyze_article(ChainRunner(llm=gateway), packet)
            except Exception as exc:
                print(f"  {label}: ✗ {exc}")
                continue
            r = outcome.result
            grade = f" · {r.action_grade.value}" if r.action_grade else ""
            print(f"  {label}")
            reason = r.ai_interpretation.reason.strip()[:150]
            print(f"    {BADGE[r.applicability]}{grade}  {reason}")
            if r.ai_interpretation.impact_summary:
                print(f"    영향: {r.ai_interpretation.impact_summary.strip()[:150]}")
            for c in r.ai_interpretation.checklist[:2]:
                print(f"    □ {c.title}")
            if r.validation.failures:
                print(f"    ⚠️ {r.validation.failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "근로기준법")))
