"""승인 흐름 계약 테스트 — 같은 테스트를 인메모리와 Postgres(migrations/008) 양쪽에 돌린다.

Postgres는 DB가 없으면 건너뛴다(tests/test_repositories.py와 같은 방식).
"""

import asyncio
from dataclasses import replace

import pytest

from app.policies.postgres import PostgresPolicyWorkflowRepository
from app.policies.workflow import (
    ApprovalWorkflow,
    DraftNotFound,
    DraftState,
    InMemoryPolicyWorkflowRepository,
    Role,
    WorkflowConflict,
    WorkflowError,
    WorkflowForbidden,
    verify_chain,
)
from tests.test_repositories import database  # noqa: F401 — 픽스처 재사용

ORG = "virtual-card-co"
POLICY_TABLES = "policy_audit_events, policy_draft_comments, policy_drafts, org_members"


@pytest.fixture(params=["memory", "postgres"])
async def wf(request, database):  # noqa: F811
    if request.param == "memory":
        repo = InMemoryPolicyWorkflowRepository()
    else:
        await database.execute(f"TRUNCATE {POLICY_TABLES}")
        repo = PostgresPolicyWorkflowRepository(database)
    for user, role in [("kim", Role.STAFF), ("choi", Role.STAFF),
                       ("lee", Role.COMPLIANCE_OFFICER), ("park", Role.COMPLIANCE_OFFICER)]:
        await repo.set_member(ORG, user, role)
    w = ApprovalWorkflow(repo, ORG)
    w.kind = request.param
    return w


async def new(wf, issues=(), by="kim"):
    return await wf.create(by, law_ref="L 제1조", policy_ref="HR-01 제25조", relation="CONFLICT",
                           current_text="old", proposed_text="new", issues=list(issues))


async def test_제출_승인_흐름과_감사_체인(wf):
    d = await new(wf)
    await wf.submit("kim", d.draft_id)
    d = await wf.approve("lee", d.draft_id)
    assert d.state is DraftState.APPROVED and d.decided_by == "lee"
    events = await wf.repo.audit_events(ORG)
    assert [e.action for e in events] == ["create", "submit", "approve"]
    assert await wf.verify_audit() is None
    assert (await wf.get(d.draft_id)).state is DraftState.APPROVED  # 저장소에서 다시 읽어도 같다


async def test_구성원이_아니면_아무것도_못_한다(wf):
    with pytest.raises(WorkflowForbidden, match="구성원"):
        await new(wf, by="stranger")


async def test_현업은_승인할_수_없다(wf):
    d = await new(wf)
    await wf.submit("kim", d.draft_id)
    with pytest.raises(WorkflowForbidden, match="준법감시인"):
        await wf.approve("choi", d.draft_id)


async def test_제출자는_자기_초안을_승인할_수_없다(wf):
    d = await new(wf, by="lee")
    await wf.submit("lee", d.draft_id)
    with pytest.raises(WorkflowForbidden, match="4-eyes"):
        await wf.approve("lee", d.draft_id)
    d = await wf.approve("park", d.draft_id)
    assert d.decided_by == "park"


async def test_검증_문제가_있으면_확인해야_승인된다(wf):
    d = await new(wf, issues=["원문에 근거가 없는 수치: ['25일']"])
    await wf.submit("kim", d.draft_id)
    with pytest.raises(WorkflowConflict, match="확인"):
        await wf.approve("lee", d.draft_id)
    await wf.approve("lee", d.draft_id, acknowledged_issues=True)
    events = await wf.repo.audit_events(ORG)
    assert events[-1].detail["acknowledged_issues"] == ["원문에 근거가 없는 수치: ['25일']"]


async def test_반려_사유_수정_재제출(wf):
    d = await new(wf)
    with pytest.raises(WorkflowConflict):
        await wf.approve("lee", d.draft_id)  # 제출 전
    await wf.submit("kim", d.draft_id)
    with pytest.raises(WorkflowError, match="사유"):
        await wf.reject("lee", d.draft_id, reason=" ")
    await wf.reject("lee", d.draft_id, reason="시행일 경과조치 누락")
    d = await wf.revise("kim", d.draft_id, proposed_text="new2")
    assert d.state is DraftState.DRAFTED and d.issues == [] and d.submitted_by is None
    await wf.submit("kim", d.draft_id)
    await wf.approve("park", d.draft_id)
    assert await wf.verify_audit() is None


async def test_의견도_감사_로그에_남는다(wf):
    d = await new(wf)
    d = await wf.comment("choi", d.draft_id, "시행일을 명시해 주세요")
    assert d.comments == [("choi", "시행일을 명시해 주세요")]
    assert (await wf.repo.audit_events(ORG))[-1].action == "comment"


async def test_없는_초안(wf):
    with pytest.raises(DraftNotFound):
        await wf.submit("kim", "not-a-uuid")
    with pytest.raises(DraftNotFound):
        await wf.submit("kim", "00000000-0000-0000-0000-000000000000")


async def test_동시에_결정하면_하나만_성공한다(wf):
    d = await new(wf)
    await wf.submit("kim", d.draft_id)
    results = await asyncio.gather(
        wf.approve("lee", d.draft_id), wf.reject("park", d.draft_id, reason="반대"),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert sum(isinstance(r, WorkflowConflict) for r in results) == 1
    assert await wf.verify_audit() is None


async def test_감사_로그를_고치면_끊긴_위치가_드러난다(wf):
    d = await new(wf)
    await wf.submit("kim", d.draft_id)
    await wf.approve("lee", d.draft_id)
    events = await wf.repo.audit_events(ORG)
    tampered = list(events)
    tampered[1] = replace(tampered[1], actor="someone-else")
    assert verify_chain(tampered) == 1
    assert verify_chain(events[:1] + events[2:]) == 1  # 중간 삭제


async def test_DB는_감사_이벤트_수정과_삭제를_거부한다(wf, database):  # noqa: F811
    if wf.kind != "postgres":
        pytest.skip("DB 트리거 검사")
    await new(wf)
    import asyncpg

    with pytest.raises(asyncpg.PostgresError, match="추가 전용"):
        await database.execute("UPDATE policy_audit_events SET actor = 'x'")
    with pytest.raises(asyncpg.PostgresError, match="추가 전용"):
        await database.execute("DELETE FROM policy_audit_events")


async def test_DB는_4eyes를_제약으로도_막는다(wf, database):  # noqa: F811
    if wf.kind != "postgres":
        pytest.skip("DB 제약 검사")
    d = await new(wf)
    import asyncpg

    with pytest.raises(asyncpg.CheckViolationError):
        await database.execute(
            "UPDATE policy_drafts SET state='APPROVED', submitted_by='kim', decided_by='kim' "
            "WHERE draft_id = $1::uuid", d.draft_id,
        )
