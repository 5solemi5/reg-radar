"""사내 규정 영향 분석(R3) — LLM 출력 검증과 승인 흐름. 키·네트워크 없이 돈다."""


from app.domain.context import LegalContext
from app.policies.models import PolicyCorpus
from app.policies.schemas import ImpactRelation, PolicyImpactOutput, PolicyRevisionDraft
from app.policies.service import (
    Candidate,
    FindingStatus,
    ImpactFinding,
    PolicyImpactService,
    unsupported_quantities,
)

LAW = LegalContext(
    law_id="x", law_name="남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", article_no="제18조의2",
    article_title="배우자 출산전후휴가",
    original_text=(
        "① 사업주는 근로자가 배우자의 임신 및 출산을 이유로 휴가를 고지하는 경우에 20일의 휴가를"
        " 주어야 한다. ③ 배우자가 출산한 날부터 120일이 지나면 사용할 수 없다."
        " ④ 배우자 출산전후휴가는 3회에 한정하여 나누어 사용할 수 있다."
    ),
)
CORPUS = PolicyCorpus.load()
HR25 = CORPUS.get("HR-01 제25조")
HR10 = CORPUS.get("HR-01 제10조")
CANDS = [Candidate("P1", HR25, 0.9), Candidate("P2", HR10, 0.1)]


def svc() -> PolicyImpactService:
    return PolicyImpactService(runner=None, corpus=CORPUS)  # check_* 만 쓴다


def item(candidate, relation, law=(), pol=(), reason="근거에 따른 판단"):
    return {"candidate": candidate, "relation": relation, "reason": reason,
            "cited_law_spans": list(law), "cited_policy_spans": list(pol)}


def check(*items):
    return svc().check_impact(LAW, CANDS, PolicyImpactOutput.model_validate({"items": items}))


def test_양쪽_원문_인용이_확인된_충돌만_조치_대상이다():
    r = check(
        item("P1", "CONFLICT", law=["20일의 휴가를 주어야 한다"],
             pol=["10일의 유급휴가를 주어야 한다"]),
        item("P2", "UNRELATED"),
    )
    assert [f.status for f in r.findings] == [FindingStatus.ACTIONABLE, FindingStatus.NO_ACTION]
    assert r.actionable()[0].policy_ref == "HR-01 제25조"


def test_사내_규정_인용이_위조면_사람이_본다():
    r = check(
        item("P1", "CONFLICT", law=["20일의 휴가를 주어야 한다"], pol=["5일의 휴가를 준다"]),
        item("P2", "UNRELATED"),
    )
    f = r.findings[0]
    assert f.status is FindingStatus.NEEDS_REVIEW
    assert f.dropped_spans == ["5일의 휴가를 준다"]


def test_법령_인용_없는_충돌_주장은_조치_대상이_아니다():
    r = check(item("P1", "UPDATE_RECOMMENDED", pol=["10일의 유급휴가"]), item("P2", "ALIGNED"))
    assert r.findings[0].status is FindingStatus.NEEDS_REVIEW


def test_빠뜨린_후보는_관련없음이_아니라_사람이_본다():
    r = check(item("P1", "ALIGNED"))
    missing = r.findings[1]
    assert missing.relation is None and missing.status is FindingStatus.NEEDS_REVIEW


def test_모르는_라벨과_중복_라벨은_버리고_기록한다():
    r = check(item("P1", "ALIGNED"), item("P1", "CONFLICT"), item("P9", "CONFLICT"),
              item("P2", "UNRELATED"))
    assert r.findings[0].relation is ImpactRelation.ALIGNED
    assert len(r.issues) == 2


def test_근거_범위_밖_조문번호를_말하면_사람이_본다():
    r = check(item("P1", "ALIGNED", reason="근로기준법 제60조에 따라 부합한다"),
              item("P2", "UNRELATED", reason="HR-01 제10조는 근로시간이다"))
    assert r.findings[0].status is FindingStatus.NEEDS_REVIEW
    assert r.findings[1].status is FindingStatus.NO_ACTION  # 후보 조문번호는 허용


def test_수치는_앞자리를_무시하지_않는다():
    # "120일" 안의 "20일"은 근거가 아니다
    assert unsupported_quantities("20일", ["120일"]) == ["20일"]
    assert unsupported_quantities("20일, 3회", [LAW.original_text]) == []
    assert unsupported_quantities("15일 이내", [LAW.original_text, HR25.text]) == ["15일"]


FINDING = ImpactFinding(
    "남녀고용평등법 제18조의2", "HR-01 제25조", ImpactRelation.CONFLICT, FindingStatus.ACTIONABLE
)


def draft(text, law=("20일의 휴가를 주어야 한다",), summary=()):
    return PolicyRevisionDraft(proposed_text=text, cited_law_spans=list(law),
                               change_summary=list(summary))


def test_원문에_있는_수치만_쓴_초안은_문제가_없다():
    d = svc().check_draft(LAW, HR25, FINDING, draft(
        "회사는 직원이 배우자의 출산을 이유로 휴가를 청구하는 경우 20일의 유급휴가를 주어야 한다."
        " 휴가는 배우자가 출산한 날부터 120일 이내에 사용하여야 하며,"
        " 3회에 한정하여 나누어 사용할 수 있다."
    ))
    assert d.issues == [] and not d.needs_review


def test_근거_없는_수치와_조문번호와_인용을_잡는다():
    d = svc().check_draft(LAW, HR25, FINDING, draft(
        "배우자 출산휴가는 25일로 한다.", law=["30일의 휴가"], summary=["근로기준법 제74조 반영"],
    ))
    joined = " ".join(d.issues)
    assert "25일" in joined and "제74조" in joined and "확인되지 않았다" in joined


def test_현행과_같은_초안은_표시한다():
    d = svc().check_draft(LAW, HR25, FINDING, draft(HR25.text))
    assert "초안이 현행 조문과 같다" in d.issues


def test_이어_붙인_인용은_구간별로_나눠_각각_대조한다():
    from app.policies.service import segment_spans

    spans = segment_spans([
        "제18조의2(배우자 출산전후휴가)\n"
        "④ 배우자 출산전후휴가는 3회에 한정하여 나누어 사용할 수 있다.",
        "원문: 회사는 직원이 배우자의 출산을 이유로",
    ])
    assert spans == [
        "제18조의2(배우자 출산전후휴가)",
        "④ 배우자 출산전후휴가는 3회에 한정하여 나누어 사용할 수 있다.",
        "회사는 직원이 배우자의 출산을 이유로",
    ]


def test_머리말을_붙인_사내_규정_인용도_원문_조각이_있으면_근거가_된다():
    header = "[P1] 취업규칙 제25조(배우자 출산휴가) · 소관 인사팀"
    r = check(
        item("P1", "CONFLICT", law=["20일의 휴가를 주어야 한다"],
             pol=[f"{header}\n원문: 회사는 직원이 배우자의 출산을 이유로 휴가를 청구하는 경우"]),
        item("P2", "UNRELATED"),
    )
    f = r.findings[0]
    assert f.status is FindingStatus.ACTIONABLE
    assert f.dropped_spans == [header]  # 머리말 조각은 원문이 아니라 탈락으로 남는다


def test_나눠도_원문에_없는_조각은_탈락한다():
    r = check(
        item("P1", "CONFLICT", law=["20일의 휴가를\n5일의 휴가를 주어야 한다"],
             pol=["10일의 유급휴가"]),
        item("P2", "UNRELATED"),
    )
    assert r.findings[0].dropped_spans == ["5일의 휴가를 주어야 한다"]


def test_반론_검토가_이기면_버리지_않고_사람에게_넘긴다():
    from app.policies.schemas import ImpactReview

    r = check(item("P1", "CONFLICT", law=["20일의 휴가를 주어야 한다"],
                   pol=["10일의 유급휴가를 주어야 한다"]), item("P2", "UNRELATED"))
    f = r.findings[0]
    PolicyImpactService.apply_review(LAW, f, ImpactReview(verdict="DISPUTE", reason="이미 부합"))
    assert f.status is FindingStatus.NEEDS_REVIEW and f.review == "DISPUTE"


def test_확인하더라도_빠진_요구를_원문으로_못_짚으면_사람이_본다():
    from app.policies.schemas import ImpactReview

    def fresh():
        r = check(item("P1", "CONFLICT", law=["20일의 휴가를 주어야 한다"],
                       pol=["10일의 유급휴가를 주어야 한다"]), item("P2", "UNRELATED"))
        return r.findings[0]

    f = fresh()
    PolicyImpactService.apply_review(LAW, f, ImpactReview(
        verdict="CONFIRM", missing_requirement_spans=["30일의 휴가"], reason="기간 부족"))
    assert f.status is FindingStatus.NEEDS_REVIEW
    g = fresh()
    PolicyImpactService.apply_review(LAW, g, ImpactReview(
        verdict="CONFIRM", missing_requirement_spans=["20일의 휴가를 주어야 한다"], reason="기간"))
    assert g.status is FindingStatus.ACTIONABLE


def test_허용_규정과_그_단서는_의무가_아니다():
    from app.policies.service import is_obligation

    assert not is_obligation("④ 사용자는 특별한 사정이 있으면 고용노동부장관의 인가와 "
                             "근로자의 동의를 받아 제1항과 제2항의 근로시간을 연장할 수 있다.")
    assert not is_obligation("다만, 사태가 급박하여 고용노동부장관의 인가를 받을 시간이 "
                             "없는 경우에는 사후에 지체 없이 승인을 받아야 한다.")
    assert is_obligation("사업주는 … 20일의 휴가를 주어야 한다.")
    assert is_obligation("사용자는 … 불리한 처우를 하여서는 아니 된다.")


def test_허용_규정만_근거로_든_보완_권고는_사람이_본다():
    from app.policies.schemas import ImpactReview

    law = LAW.model_copy(update={"original_text": LAW.original_text
                                 + " ⑤ 사업주는 근로자가 원하면 휴가를 나누어 줄 수 있다."})
    r = svc().check_impact(law, CANDS, PolicyImpactOutput.model_validate({"items": [
        item("P1", "UPDATE_RECOMMENDED", law=["사업주는 근로자가 원하면 휴가를 나누어 줄 수 있다."],
             pol=["10일의 유급휴가를 주어야 한다"]),
        item("P2", "UNRELATED"),
    ]}))
    assert r.findings[0].status is FindingStatus.NEEDS_REVIEW
    f = check(item("P1", "CONFLICT", law=["20일의 휴가를 주어야 한다"],
                   pol=["10일의 유급휴가를 주어야 한다"]), item("P2", "UNRELATED")).findings[0]
    f.relation = ImpactRelation.UPDATE_RECOMMENDED
    PolicyImpactService.apply_review(law, f, ImpactReview(
        verdict="CONFIRM",
        missing_requirement_spans=["사업주는 근로자가 원하면 휴가를 나누어 줄 수 있다."],
        reason="분할"))
    assert f.status is FindingStatus.NEEDS_REVIEW


def test_허용형으로_쓴_한도는_의무다():
    from app.policies.service import is_obligation

    assert is_obligation("사용자는 2년을 초과하지 아니하는 범위 안에서 "
                         "기간제근로자를 사용할 수 있다.")
    assert is_obligation("가산휴가를 포함한 총 휴가 일수는 25일을 한도로 한다.")


def test_서술형_규정도_의무다():
    from app.policies.service import is_obligation

    assert is_obligation("육아휴직 기간은 기간제법 제4조에 따른 사용기간에서 제외한다.")
    assert is_obligation("육아휴직의 기간은 1년 이내로 한다.")
