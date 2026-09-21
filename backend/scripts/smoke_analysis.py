"""AI Core E2E 스모크 — 실제 법령 + 실제 LLM으로 C3~C6를 돌린다.

같은 조문에 대해 세 사용자 프로필이 해당 / 보류 / 무관으로 갈리는지 확인한다
(기획서 §13 발표 시나리오의 '입력 비교' 장면).

사용법:
    .venv/bin/python scripts/smoke_analysis.py [법령명] [조문번호]
    .venv/bin/python scripts/smoke_analysis.py 근로기준법 제93조
"""

import asyncio
import sys

from app.adapters.law.client import LawApiClient, LawApiError
from app.ai.chains.base import ChainRunner
from app.ai.llm import LlmGateway
from app.core.config import get_settings
from app.diff.engine import compute_change
from app.domain.context import ContextPacket, UserContext
from app.domain.enums import Applicability, CompanySize
from app.services.analysis_service import analyze_article

PROFILES = [
    (
        "P01 김민지 · 4인 온라인 쇼핑몰 대표",
        UserContext(
            job="쇼핑몰 운영·총무",
            industry="이커머스 소매",
            company_size=CompanySize.MICRO,
            employee_count=4,
            interests=["개인정보", "노동"],
        ),
    ),
    (
        "P02 박준호 · 80인 IT기업 HR 실무자",
        UserContext(
            job="HR 담당자 (채용·근태·취업규칙)",
            industry="IT 서비스",
            company_size=CompanySize.MEDIUM,
            employee_count=80,
            interests=["노동", "근로계약"],
        ),
    ),
    (
        "P03 이수현 · 제조기업 운영팀장 (인원 미입력)",
        UserContext(
            job="운영·경영지원 팀장",
            industry="제조",
            company_size=CompanySize.MEDIUM,
            employee_count=None,  # 의도적으로 미상 → HOLD 유도
            interests=["안전", "노동"],
        ),
    ),
]

BADGE = {
    Applicability.APPLICABLE: "🔴 해당",
    Applicability.HOLD: "🟡 보류",
    Applicability.NOT_APPLICABLE: "⚪ 무관",
}


def simulate_amendment(text: str) -> str | None:
    """개정 전 텍스트를 만들어 diff 경로를 실제로 태운다.

    ⚠️ 이 텍스트는 **시뮬레이션**이다. 실제 신구법 비교는 법제처 신구법 API 연동 시
    대체된다. 스모크에서 C3~C6 전체 경로를 확인하기 위한 장치일 뿐이다.
    """
    for old, new in (("10명", "20명"), ("30명", "50명"), ("5명", "10명")):
        if old in text:
            return text.replace(old, new, 1)
    return None


async def main(law_name: str, article_no: str) -> int:
    settings = get_settings()
    if not settings.law_api_enabled or not settings.llm_enabled:
        print("✗ LAW_API_OC 또는 OPENAI_API_KEY가 없습니다.")
        return 1

    try:
        async with LawApiClient(settings=settings) as client:
            laws = await client.search_laws(query=law_name, display=5)
            target = next((law for law in laws if law.law_name == law_name), None)
            if target is None:
                print(f"✗ '{law_name}'을(를) 찾지 못했습니다. 검색결과: "
                      f"{[law.law_name for law in laws]}")
                return 1
            snapshot = await client.fetch_law_detail(target)
    except LawApiError as exc:
        print(f"✗ {exc}")
        return 1

    article = snapshot.find_article(article_no)
    if article is None:
        available = [a.article_no for a in snapshot.articles if not a.is_supplementary][:15]
        print(f"✗ {article_no}을(를) 찾지 못했습니다. 예: {available}")
        return 1

    legal = snapshot.to_legal_context(article_no)
    before = simulate_amendment(legal.original_text)
    change = compute_change(before, legal.original_text)

    print("=" * 72)
    print(f"{snapshot.law_name} {article.article_no}"
          f"{f'({article.article_title})' if article.article_title else ''}")
    print(f"시행일 {legal.effective_date} · {legal.ministry} · 출처 {snapshot.source}")
    if article.chapter:
        print(f"소속: {article.chapter}")
    print("-" * 72)
    print(legal.original_text[:320])
    print("-" * 72)
    print(f"변경유형: {change.change_type.value}"
          f"{'  ⚠️(개정 전 텍스트는 시뮬레이션)' if before else ''}")
    if change.additions:
        print(f"추가: {change.additions[0][:90]}")
    if change.delegation_targets:
        print(f"하위법령 위임: {change.delegation_targets}  → 보류 사유로 작동")
    print("=" * 72)

    gateway = LlmGateway(settings=settings)
    for label, user in PROFILES:
        packet = ContextPacket(user=user, law=legal, change=change, rag=[])
        runner = ChainRunner(llm=gateway)
        try:
            outcome = await analyze_article(runner, packet)
        except Exception as exc:
            print(f"\n▶ {label}\n  ✗ 분석 실패: {exc}")
            continue

        r = outcome.result
        print(f"\n▶ {label}")
        print(f"  {BADGE[r.applicability]}"
              f"{f' · {r.action_grade.value}' if r.action_grade else ''}"
              f"  (status={r.status.value}, confidence={r.ai_interpretation.confidence})")
        print(f"  사유: {r.ai_interpretation.reason.strip()[:200]}")
        if r.ai_interpretation.missing_context:
            print("  보류 해소에 필요한 정보:")
            for m in r.ai_interpretation.missing_context:
                print(f"    · {m}")
        if r.legal_evidence.quoted_spans:
            print("  검증된 원문 인용:")
            for s in r.legal_evidence.quoted_spans[:2]:
                print(f'    · "{s[:80]}"')
        if r.ai_interpretation.checklist:
            print("  체크리스트:")
            for c in r.ai_interpretation.checklist[:3]:
                print(f"    □ {c.title}")
        if r.validation.failures:
            print(f"  ⚠️ 검증: {r.validation.failures}")
        if r.validation.dropped_spans:
            print(f"  ⚠️ 제거된 인용: {r.validation.dropped_spans}")
        print(f"  latency {outcome.total_latency_ms}ms · "
              f"{[t.chain for t in outcome.traces]}")

    return 0


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "근로기준법"
    art = sys.argv[2] if len(sys.argv) > 2 else "제93조"
    raise SystemExit(asyncio.run(main(name, art)))
