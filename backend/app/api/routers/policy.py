"""사내 규정 영향 분석·개정 초안 승인 API (문서 12 §4, R3).

Agent는 규정을 고치지 않는다. 영향 판단과 초안까지만 만들고, 승인은 준법감시인이 한다.
역할은 요청이 아니라 조직 구성원 저장소에서 읽는다(app/policies/workflow.py).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from app.ai.chains.base import ChainExecutionError
from app.api.auth import CurrentUser, get_current_user
from app.api.deps import (
    get_policy_service,
    get_policy_workflow,
    get_snapshot_repo,
    get_trace_repo,
)
from app.api.errors import (
    ErrorResponse,
    NotFoundError,
    PolicyConflictError,
    PolicyForbiddenError,
    PolicyInvalidError,
    UpstreamUnavailableError,
)
from app.policies.schemas import ACTIONABLE
from app.policies.service import ImpactFinding, PolicyImpactService
from app.policies.workflow import (
    ApprovalWorkflow,
    DraftNotFound,
    DraftRecord,
    WorkflowConflict,
    WorkflowError,
    WorkflowForbidden,
)
from app.repositories.traces import TraceRecord

router = APIRouter(prefix="/policy", tags=["policy"])

_ERRORS = {
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


# ── 스키마 ─────────────────────────────────────────────────────────────
class LawArticleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    law_id: str = Field(..., description="분석 때 저장된 법령 snapshot ID")
    article_no: str = Field(..., examples=["제18조의2"])


class DraftCreateIn(LawArticleIn):
    policy_ref: str = Field(..., examples=["HR-01 제25조"])


class FindingOut(BaseModel):
    policy_ref: str
    relation: str | None
    status: str = Field(..., description="ACTIONABLE | NEEDS_REVIEW | NO_ACTION")
    reason: str
    law_spans: list[str] = Field(..., description="법령 원문에서 확인된 인용만")
    policy_spans: list[str] = Field(..., description="사내 규정 원문에서 확인된 인용만")
    dropped_span_count: int
    missing_context: list[str]
    issues: list[str]
    review: str | None = Field(None, description="반론 검토(C7b) 결과 CONFIRM | DISPUTE")


class ImpactOut(BaseModel):
    law_ref: str
    corpus_label: str = Field(..., description="사내 규정집 표시 — 가상 규정집임을 밝힌다")
    candidates: list[str]
    findings: list[FindingOut]
    issues: list[str]


class DraftOut(BaseModel):
    draft_id: str
    law_ref: str
    policy_ref: str
    relation: str
    state: str
    current_text: str
    proposed_text: str
    issues: list[str] = Field(..., description="검증 문제. 있으면 승인 때 확인 표시가 필요하다")
    created_by: str
    submitted_by: str | None
    decided_by: str | None
    comments: list[dict[str, str]]


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledged_issues: bool = False


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class ReviseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_text: str = Field(..., min_length=1)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1)


class AuditOut(BaseModel):
    intact: bool
    broken_at: int | None = Field(None, description="체인이 처음 끊긴 위치(0부터)")
    events: list[dict[str, Any]]


# ── 변환 ───────────────────────────────────────────────────────────────
def _finding(f: ImpactFinding) -> FindingOut:
    return FindingOut(
        policy_ref=f.policy_ref, relation=f.relation.value if f.relation else None,
        status=f.status.value, reason=f.reason, law_spans=f.law_spans,
        policy_spans=f.policy_spans, dropped_span_count=len(f.dropped_spans),
        missing_context=f.missing_context, issues=f.issues, review=f.review,
    )


def _draft(d: DraftRecord) -> DraftOut:
    return DraftOut(
        draft_id=d.draft_id, law_ref=d.law_ref, policy_ref=d.policy_ref, relation=d.relation,
        state=d.state.value, current_text=d.current_text, proposed_text=d.proposed_text,
        issues=d.issues, created_by=d.created_by, submitted_by=d.submitted_by,
        decided_by=d.decided_by, comments=[{"user_id": u, "text": t} for u, t in d.comments],
    )


async def _run(coro):
    """워크플로 예외 → API 에러 봉투."""
    try:
        return await coro
    except WorkflowForbidden as exc:
        raise PolicyForbiddenError(str(exc)) from exc
    except DraftNotFound as exc:
        raise NotFoundError("초안을 찾을 수 없습니다.") from exc
    except WorkflowConflict as exc:
        raise PolicyConflictError(str(exc)) from exc
    except WorkflowError as exc:
        raise PolicyInvalidError(str(exc)) from exc


async def _law(snapshot_repo, payload: LawArticleIn):
    snapshot = await snapshot_repo.get(payload.law_id)
    if snapshot is None or snapshot.find_article(payload.article_no) is None:
        raise NotFoundError("법령 조문을 찾을 수 없습니다. 먼저 분석을 실행해 주세요.")
    return snapshot.to_legal_context(payload.article_no)


async def _save_traces(trace_repo, svc: PolicyImpactService, user_id: str, law) -> None:
    """C7·C7b·C8 호출도 분석 파이프라인과 같은 ai_traces에 남긴다(R4). 실패해도 요청은 계속."""
    trace_id = str(uuid4())
    await trace_repo.save_many([
        TraceRecord.of(t, trace_id=trace_id, analysis_id=None, user_id=user_id,
                       law_id=law.law_id, article_no=law.article_no)
        for t in svc.runner.traces
    ])


def _service(service: PolicyImpactService | None) -> PolicyImpactService:
    if service is None:
        raise UpstreamUnavailableError("AI 분석이 꺼져 있어 영향 분석을 할 수 없습니다.")
    return service


# ── 엔드포인트 ─────────────────────────────────────────────────────────
@router.post("/impact", response_model=ImpactOut, responses={503: {"model": ErrorResponse},
                                                             **_ERRORS})
async def assess_impact(
    payload: LawArticleIn,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
    snapshot_repo=Depends(get_snapshot_repo),
    service: PolicyImpactService | None = Depends(get_policy_service),
    trace_repo=Depends(get_trace_repo),
) -> ImpactOut:
    """법령 조문이 닿는 사내 규정 조항을 찾고 영향을 판단한다(C7 → 검증 → C7b 반론 검토)."""
    await _run(wf.actor(user.user_id))
    svc = _service(service)
    law = await _law(snapshot_repo, payload)
    try:
        report = await svc.assess(law)
    except ChainExecutionError as exc:
        raise UpstreamUnavailableError(detail=str(exc)) from exc
    finally:
        await _save_traces(trace_repo, svc, user.user_id, law)
    return ImpactOut(
        law_ref=report.law_ref, corpus_label=svc.corpus.label,
        candidates=[c.article.ref for c in report.candidates],
        findings=[_finding(f) for f in report.findings], issues=report.issues,
    )


@router.post("/drafts", response_model=DraftOut, status_code=status.HTTP_201_CREATED,
             responses={503: {"model": ErrorResponse}, **_ERRORS})
async def create_draft(
    payload: DraftCreateIn,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
    snapshot_repo=Depends(get_snapshot_repo),
    service: PolicyImpactService | None = Depends(get_policy_service),
    trace_repo=Depends(get_trace_repo),
) -> DraftOut:
    """영향 판단을 다시 돌려 그 조항이 개정 대상일 때만 C8 초안을 만든다.

    클라이언트가 보낸 판단을 믿지 않는다 — 서버가 다시 판단한다.
    NEEDS_REVIEW였던 조항도 초안을 만들 수 있지만, 그 사유가 초안의 검증 문제로 붙어
    승인자가 확인해야 승인된다.
    """
    await _run(wf.actor(user.user_id))
    svc = _service(service)
    law = await _law(snapshot_repo, payload)
    try:
        report = await svc.assess(law)
        finding = next((f for f in report.findings if f.policy_ref == payload.policy_ref), None)
        if finding is None or finding.relation not in ACTIONABLE:
            raise PolicyInvalidError("이 조항은 개정 대상으로 판단되지 않았습니다.")
        result = await svc.draft(law, finding)
    except ChainExecutionError as exc:
        raise UpstreamUnavailableError(detail=str(exc)) from exc
    finally:
        await _save_traces(trace_repo, svc, user.user_id, law)
    art = svc.corpus.get(payload.policy_ref)
    d = await _run(wf.create(
        user.user_id, law_ref=report.law_ref, policy_ref=art.ref,
        relation=finding.relation.value, current_text=art.text,
        proposed_text=result.draft.proposed_text,
        issues=[*finding.issues, *result.issues],
    ))
    return _draft(d)


@router.get("/drafts", response_model=list[DraftOut], responses=_ERRORS)
async def list_drafts(
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> list[DraftOut]:
    await _run(wf.actor(user.user_id))
    return [_draft(d) for d in await wf.repo.list(wf.org_id)]


@router.get("/drafts/{draft_id}", response_model=DraftOut, responses=_ERRORS)
async def get_draft(
    draft_id: str,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> DraftOut:
    await _run(wf.actor(user.user_id))
    return _draft(await _run(wf.get(draft_id)))


@router.post("/drafts/{draft_id}/submit", response_model=DraftOut, responses=_ERRORS)
async def submit_draft(
    draft_id: str,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> DraftOut:
    return _draft(await _run(wf.submit(user.user_id, draft_id)))


@router.post("/drafts/{draft_id}/approve", response_model=DraftOut, responses=_ERRORS)
async def approve_draft(
    draft_id: str,
    payload: ApproveIn,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> DraftOut:
    """준법감시인만, 제출자가 아닌 사람만(4-eyes)."""
    return _draft(await _run(wf.approve(
        user.user_id, draft_id, acknowledged_issues=payload.acknowledged_issues
    )))


@router.post("/drafts/{draft_id}/reject", response_model=DraftOut, responses=_ERRORS)
async def reject_draft(
    draft_id: str,
    payload: RejectIn,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> DraftOut:
    return _draft(await _run(wf.reject(user.user_id, draft_id, reason=payload.reason)))


@router.post("/drafts/{draft_id}/revise", response_model=DraftOut, responses=_ERRORS)
async def revise_draft(
    draft_id: str,
    payload: ReviseIn,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> DraftOut:
    return _draft(await _run(wf.revise(user.user_id, draft_id,
                                       proposed_text=payload.proposed_text)))


@router.post("/drafts/{draft_id}/comments", response_model=DraftOut, responses=_ERRORS)
async def comment_draft(
    draft_id: str,
    payload: CommentIn,
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> DraftOut:
    return _draft(await _run(wf.comment(user.user_id, draft_id, payload.text)))


@router.get("/audit", response_model=AuditOut, responses=_ERRORS)
async def get_audit(
    user: CurrentUser = Depends(get_current_user),
    wf: ApprovalWorkflow = Depends(get_policy_workflow),
) -> AuditOut:
    """감사 로그 전체와 해시 체인 검증 결과."""
    await _run(wf.actor(user.user_id))
    events = await wf.repo.audit_events(wf.org_id)
    from app.policies.workflow import verify_chain

    broken = verify_chain(events)
    return AuditOut(intact=broken is None, broken_at=broken,
                    events=[e.__dict__ for e in events])
