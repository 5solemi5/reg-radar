"""법령 조문 → 사내 규정 영향 판단(C7) → 개정 초안(C8) (문서 12 §4).

LLM이 한 말을 그대로 믿지 않는다. 기존 Validator(FR-020·021, BR-001)와 같은 원칙을
사내 규정에 적용한다.

- 후보 라벨은 코드가 붙인 것만 인정한다. 모르는 라벨·중복 라벨은 버리고, 판단이 빠진 후보는
  사람이 보게 한다(NEEDS_REVIEW). 빠뜨린 것을 "관련 없음"으로 간주하지 않는다.
- CONFLICT·UPDATE_RECOMMENDED는 법령 원문과 사내 규정 원문 **양쪽** 인용이 원문에서 확인될 때만
  조치 대상(ACTIONABLE)이 된다. 한쪽이라도 없으면 NEEDS_REVIEW.
- 서술에 근거 범위 밖 조문번호가 나오면 NEEDS_REVIEW.
- 초안(C8)에 단위가 붙은 수치(20일, 3회 …)가 법령·현행 규정 원문에 없으면 NEEDS_REVIEW.

ALIGNED·UNRELATED 판단은 검증할 원문 근거가 없다(없음을 인용할 수는 없다). 그래서 이쪽의 실수
(CONFLICT를 ALIGNED로 놓침)는 런타임에서 막지 못하고, 평가(policy_impact)의 조치 재현율로 잰다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.ai.chains.base import ChainRunner
from app.domain.context import LegalContext
from app.policies.models import PolicyArticle, PolicyCorpus
from app.policies.prompts import C7_POLICY_IMPACT, C7B_IMPACT_REVIEW, C8_POLICY_DRAFT
from app.policies.retriever import PolicyRetriever
from app.policies.schemas import (
    ACTIONABLE,
    ImpactRelation,
    ImpactReview,
    PolicyImpactItem,
    PolicyImpactOutput,
    PolicyRevisionDraft,
    ReviewVerdict,
)
from app.validator.rules import normalize_for_match, verify_citations

_ARTICLE_REF = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
# 인용 구간 경계: 줄바꿈, 항 번호(①~⑳) 앞, 공백 뒤 호 번호("1. ", "3의2. ") 앞.
_SEGMENT = re.compile(r"\n|(?=[\u2460-\u2473])|(?<=\s)(?=\d+(?:의\d+)?\.\s)")
_LABEL = "원문:"


def segment_spans(spans: list[str]) -> list[str]:
    """모델이 떨어진 구간을 한 인용으로 이어 붙인 것을 구간별로 나눈다.

    policy_impact_v1 봉인셋에서 인용 탈락의 주원인이 형식이었다: 조문 제목 + 떨어진 항,
    또는 후보 머리말 + 원문. 이어 붙인 채로는 원문에 없으니 탈락하고, 맞는 근거가 사람 검토로
    밀렸다. 나눈 뒤 **조각마다** 원문 대조를 하므로 원문에 없는 조각은 여전히 탈락한다 —
    완화가 아니라, 이어 붙여 생긴 '연속된 문장'이라는 거짓 모양만 없앤다.
    """
    out: list[str] = []
    for span in spans:
        for piece in _SEGMENT.split(span):
            piece = piece.strip()
            if piece.startswith(_LABEL):  # 프롬프트에서 붙인 표지. 원문 내용이 아니다
                piece = piece[len(_LABEL):].strip()
            if len(piece) >= 4 and piece not in out:
                out.append(piece)
    return out


# 허용 규정 판별. 법 문장은 기본적으로 의무다("~하여야 한다", "~로 한다", "제외한다").
# "~할 수 있다"이면서 제한 표지가 없을 때만 허용으로 본다.
# 한국 법령은 제한도 허용형으로 쓰기 때문이다:
# "2년을 초과하지 아니하는 범위 안에서 … 사용할 수 있다", "25일을 한도로 한다"(v3 dev에서 확인).
_PERMISSIVE = re.compile(r"수\s*있다")
_RESTRICTION = re.compile(r"한도|초과하지|넘지|이내|범위|아니\s*된다|못한다|할 수 없다")


def is_obligation(span: str) -> bool:
    """법 문장이 독립된 의무를 지우는가.

    "~할 수 있다"(허용)와, 허용을 쓸 때만 따르는 "다만, …받아야 한다" 단서는 의무가 아니다.
    policy_impact_v2 봉인셋의 오조치(근로기준법 제53조 ④ 특별연장근로 인가 → '연장근로 12시간'
    조항에 보완 권고)가 이 유형이었다. 회사는 허용된 제도를 쓰지 않기로 할 수 있다.
    """
    s = normalize_for_match(span)
    s = re.sub(r"^[\u2460-\u2473]\s*", "", s)  # 항 번호
    if s.startswith("다만"):
        return False
    return not _PERMISSIVE.search(s) or bool(_RESTRICTION.search(s))


# 단위가 붙은 수치. 앞이 숫자면 매치하지 않는다("120일" 안의 "20일"은 20일이 아니다).
_QUANTITY = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(일|개월|년|회|명|시간|세|주|%|퍼센트|배)")


class FindingStatus(StrEnum):
    ACTIONABLE = "ACTIONABLE"  # 양쪽 원문 근거가 확인된 CONFLICT·UPDATE_RECOMMENDED
    NEEDS_REVIEW = "NEEDS_REVIEW"  # 근거 부족·위조 의심·판단 누락 — 사람이 판단
    NO_ACTION = "NO_ACTION"  # ALIGNED·UNRELATED


@dataclass(frozen=True)
class Candidate:
    label: str
    article: PolicyArticle
    score: float


@dataclass
class ImpactFinding:
    law_ref: str
    policy_ref: str
    relation: ImpactRelation | None  # None = 모델이 이 후보를 판단하지 않았다
    status: FindingStatus
    reason: str = ""
    law_spans: list[str] = field(default_factory=list)  # 원문에서 확인된 인용만
    policy_spans: list[str] = field(default_factory=list)
    dropped_spans: list[str] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    review: str | None = None  # C7b 반론 검토 결과 (CONFIRM | DISPUTE)


@dataclass
class ImpactReport:
    law: LegalContext
    candidates: list[Candidate]
    findings: list[ImpactFinding]
    issues: list[str] = field(default_factory=list)  # 후보와 무관한 문제(모르는 라벨 등)

    @property
    def law_ref(self) -> str:
        return f"{self.law.law_name} {self.law.article_no}"

    def actionable(self) -> list[ImpactFinding]:
        return [f for f in self.findings if f.status is FindingStatus.ACTIONABLE]


@dataclass
class DraftResult:
    finding: ImpactFinding
    draft: PolicyRevisionDraft
    law_spans: list[str]
    issues: list[str]

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)


def law_ref_of(law: LegalContext) -> str:
    return f"{law.law_name} {law.article_no}"


def _ref(match: re.Match[str]) -> str:
    main, branch = match.group(1), match.group(2)
    return f"제{int(main)}조의{int(branch)}" if branch else f"제{int(main)}조"


def fabricated_article_refs(text: str, *, allowed_no: list[str], sources: list[str]) -> list[str]:
    """`text`의 조문번호 중 근거 범위(지정된 조문번호 + 원문 안에서 인용된 조문) 밖인 것."""
    allowed = {_ref(m) for no in allowed_no for m in _ARTICLE_REF.finditer(no)}
    for src in sources:
        allowed |= {_ref(m) for m in _ARTICLE_REF.finditer(src)}
    out: list[str] = []
    for m in _ARTICLE_REF.finditer(text):
        r = _ref(m)
        if r not in allowed and r not in out:
            out.append(r)
    return out


def quantities(text: str) -> set[str]:
    return {f"{float(n):g}{'%' if u == '퍼센트' else u}" for n, u in _QUANTITY.findall(text)}


def unsupported_quantities(text: str, sources: list[str]) -> list[str]:
    """`text`에 나온 단위 수치 중 어느 원문에도 없는 것. 정렬해 돌려준다(결정적)."""
    allowed: set[str] = set()
    for src in sources:
        allowed |= quantities(src)
    return sorted(quantities(text) - allowed)


def _profile_text(corpus: PolicyCorpus) -> str:
    p = corpus.profile
    parts = [p.get("industry"), f"상시근로자 {p['employee_count']}명" if "employee_count" in p
             else None, p.get("workplaces")]
    return ", ".join(x for x in parts if x)


class PolicyImpactService:
    def __init__(self, runner: ChainRunner, corpus: PolicyCorpus, *, k: int = 5,
                 review: bool = True):
        self.runner = runner
        self.corpus = corpus
        self.retriever = PolicyRetriever(corpus)
        self.k = k
        self.review = review  # 조치 대상마다 C7b 반론 검토를 한다

    def candidates(self, law: LegalContext) -> list[Candidate]:
        query = f"{law.article_title or ''} {law.original_text}"
        hits = self.retriever.search(query, k=self.k)
        return [Candidate(f"P{i}", art, score) for i, (art, score) in enumerate(hits, start=1)]

    async def assess(self, law: LegalContext) -> ImpactReport:
        cands = self.candidates(law)
        if not cands:
            return ImpactReport(law, [], [])
        prompt = C7_POLICY_IMPACT.format(
            law_block=law.to_prompt_block(),
            company_name=self.corpus.company_name,
            company_profile=_profile_text(self.corpus),
            candidates_block="\n\n".join(c.article.render(c.label) for c in cands),
        )
        out = await self.runner.invoke(chain="C7_policy_impact", prompt=prompt,
                                       schema=PolicyImpactOutput)
        report = self.check_impact(law, cands, out)
        if self.review:
            for f in report.actionable():
                await self._review(law, f)
        return report

    async def _review(self, law: LegalContext, finding: ImpactFinding) -> None:
        art = self.corpus.get(finding.policy_ref)
        prompt = C7B_IMPACT_REVIEW.format(
            relation=finding.relation.value,
            law_block=law.to_prompt_block(),
            policy_header=f"{art.policy_title} {art.article_no}({art.title})",
            policy_text=art.text,
            reason=finding.reason,
        )
        review = await self.runner.invoke(chain="C7b_impact_review", prompt=prompt,
                                          schema=ImpactReview)
        self.apply_review(law, finding, review)

    @staticmethod
    def apply_review(law: LegalContext, finding: ImpactFinding, review: ImpactReview) -> None:
        """반론 검토를 반영한다. 검토가 이기면 버리지 않고 사람에게 넘긴다(NEEDS_REVIEW).

        policy_impact_v1 봉인셋에서 조치 정밀도가 50%였다 — 이미 법에 맞는 조항에 '보완 권고'.
        이 실수는 원문 대조로 반증할 수 없으므로, 반대편을 맡은 두 번째 판단으로 거른다.
        """
        finding.review = review.verdict.value
        if review.verdict is ReviewVerdict.DISPUTE:
            finding.status = FindingStatus.NEEDS_REVIEW
            finding.issues.append(f"검토자 반론: {review.reason}")
            return
        ok, _ = verify_citations(segment_spans(review.missing_requirement_spans),
                                 law.original_text)
        if not ok:
            finding.status = FindingStatus.NEEDS_REVIEW
            finding.issues.append("검토자가 빠진 법 요구를 원문으로 짚지 못했다")
        elif finding.relation is ImpactRelation.UPDATE_RECOMMENDED and not any(
            is_obligation(s) for s in ok
        ):
            # '누락'일 때만. CONFLICT는 규정이 허용 범위를 넘은 것이라 허용 규정이 근거가 된다
            finding.status = FindingStatus.NEEDS_REVIEW
            finding.issues.append("검토자가 짚은 요구가 모두 허용 규정이다(…할 수 있다)")

    def check_impact(
        self, law: LegalContext, cands: list[Candidate], out: PolicyImpactOutput
    ) -> ImpactReport:
        """C7 출력 검증. LLM 없이 단독으로 테스트한다."""
        by_label = {c.label: c for c in cands}
        seen: dict[str, PolicyImpactItem] = {}
        issues: list[str] = []
        for item in out.items:
            if item.candidate not in by_label:
                issues.append(f"모르는 후보 라벨 {item.candidate} — 버림")
            elif item.candidate in seen:
                issues.append(f"후보 {item.candidate}를 두 번 판단 — 처음 것만 씀")
            else:
                seen[item.candidate] = item

        findings = []
        for c in cands:
            item = seen.get(c.label)
            if item is None:
                findings.append(ImpactFinding(
                    law_ref_of(law), c.article.ref, None, FindingStatus.NEEDS_REVIEW,
                    issues=["모델이 이 후보를 판단하지 않았다"],
                ))
                continue
            findings.append(self._check_item(law, c.article, item, cands))
        return ImpactReport(law, cands, findings, issues)

    def _check_item(
        self, law: LegalContext, art: PolicyArticle, item: PolicyImpactItem,
        cands: list[Candidate],
    ) -> ImpactFinding:
        law_ok, law_bad = verify_citations(segment_spans(item.cited_law_spans), law.original_text)
        pol_ok, pol_bad = verify_citations(segment_spans(item.cited_policy_spans), art.text)
        issues: list[str] = []

        fabricated = fabricated_article_refs(
            item.reason,
            allowed_no=[law.article_no, *(c.article.article_no for c in cands)],
            sources=[law.original_text, art.text],
        )
        if fabricated:
            issues.append(f"근거 범위 밖 조문번호: {fabricated}")

        if item.relation in ACTIONABLE:
            if not law_ok:
                issues.append("법령 원문 인용이 확인되지 않았다")
            elif item.relation is ImpactRelation.UPDATE_RECOMMENDED and not any(
                is_obligation(s) for s in law_ok
            ):
                issues.append(
                    "보완 근거로 든 법 문장이 모두 허용 규정이다(…할 수 있다) — 누락이 아닐 수 있다"
                )
            if not pol_ok:
                issues.append("사내 규정 원문 인용이 확인되지 않았다")
            status = FindingStatus.NEEDS_REVIEW if issues else FindingStatus.ACTIONABLE
        else:
            status = FindingStatus.NEEDS_REVIEW if issues else FindingStatus.NO_ACTION

        return ImpactFinding(
            law_ref_of(law), art.ref, item.relation, status, item.reason,
            law_ok, pol_ok, law_bad + pol_bad, list(item.missing_context), issues,
        )

    async def draft(self, law: LegalContext, finding: ImpactFinding) -> DraftResult:
        if finding.relation not in ACTIONABLE:
            raise ValueError(f"조치 대상이 아닌 판단에는 초안을 만들지 않는다: {finding.relation}")
        art = self.corpus.get(finding.policy_ref)
        prompt = C8_POLICY_DRAFT.format(
            law_block=law.to_prompt_block(),
            policy_block=art.render("현행"),
            relation=finding.relation.value,
            reason=finding.reason,
        )
        draft = await self.runner.invoke(chain="C8_policy_draft", prompt=prompt,
                                         schema=PolicyRevisionDraft)
        return self.check_draft(law, art, finding, draft)

    def check_draft(
        self, law: LegalContext, art: PolicyArticle, finding: ImpactFinding,
        draft: PolicyRevisionDraft,
    ) -> DraftResult:
        """C8 출력 검증. 초안은 문제가 있어도 버리지 않는다 — 문제를 붙여 사람에게 넘긴다."""
        law_ok, law_bad = verify_citations(segment_spans(draft.cited_law_spans), law.original_text)
        issues: list[str] = []
        if not law_ok:
            issues.append("개정 근거 법령 인용이 원문에서 확인되지 않았다")
        if law_bad:
            issues.append(f"원문에 없는 법령 인용 {len(law_bad)}건 제거")
        sources = [law.original_text, art.text]
        nums = unsupported_quantities(draft.proposed_text, sources)
        if nums:
            issues.append(f"원문에 근거가 없는 수치: {nums}")
        written = "\n".join([draft.proposed_text, *draft.change_summary])
        fabricated = fabricated_article_refs(
            written, allowed_no=[law.article_no, art.article_no], sources=sources
        )
        if fabricated:
            issues.append(f"근거 범위 밖 조문번호: {fabricated}")
        if normalize_for_match(draft.proposed_text) == normalize_for_match(art.text):
            issues.append("초안이 현행 조문과 같다")
        return DraftResult(finding, draft, law_ok, issues)
