"""개정 초안 승인 흐름과 감사 로그 (문서 12 §4).

Agent는 규정을 고치지 않는다. 초안을 내고, 승인은 사람이 한다.

    DRAFTED ──submit──▶ IN_REVIEW ──approve──▶ APPROVED
                            │
                            └────reject───▶ REJECTED ──revise──▶ DRAFTED

- 역할은 조직 구성원 테이블(org_members)에서 읽는다. 요청이 스스로 밝힌 역할을 믿지 않는다.
  STAFF: 생성·제출·의견·수정. COMPLIANCE_OFFICER: 위 + 승인·반려.
- 4-eyes: 제출한 사람은 같은 초안을 승인·반려할 수 없다(준법감시인이 직접 제출해도 마찬가지).
  Postgres에서는 CHECK 제약으로도 막는다(migrations/008).
- 검증 문제(issues)가 붙은 초안은 승인자가 문제를 확인했다고 표시해야 승인된다.
- 감사 로그는 추가 전용이고, 각 이벤트가 이전 이벤트의 해시를 품는다(조직별 해시 체인).
  중간 이벤트를 고치거나 지우면 `verify_chain()`이 어디서 끊겼는지 알려준다.
  Postgres에서는 UPDATE·DELETE를 트리거로 거부한다.
- 상태 전이와 감사 이벤트는 한 번에 저장된다(저장소의 `transition`). 두 준법감시인이
  동시에 결정하면 먼저 저장한 쪽만 성공하고 나머지는 충돌(WorkflowConflict)로 실패한다.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4


class Role(StrEnum):
    STAFF = "STAFF"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"


class DraftState(StrEnum):
    DRAFTED = "DRAFTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: Role


class WorkflowError(Exception):
    """허용되지 않은 전이·권한. API에서는 403/409로 바꾼다."""


class WorkflowForbidden(WorkflowError):
    """역할·4-eyes 위반."""


class WorkflowConflict(WorkflowError):
    """상태가 맞지 않거나, 다른 사람이 먼저 바꿨다."""


class DraftNotFound(WorkflowError):
    pass


GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEvent:
    org_id: str
    seq: int
    at: str
    actor: str
    role: str
    action: str
    draft_id: str
    before: str | None
    after: str | None
    detail: dict[str, Any]
    prev_hash: str
    hash: str

    @staticmethod
    def digest(body: dict[str, Any]) -> str:
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def body(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "hash"}


@dataclass(frozen=True)
class AuditDraft:
    """저장소에 넘기는 감사 이벤트 내용. seq·prev_hash·hash는 저장소가 체인 끝에서 정한다."""

    actor: Actor
    action: str
    draft_id: str
    before: str | None
    after: str | None
    detail: dict[str, Any]
    at: str


def chain_event(org_id: str, seq: int, prev_hash: str, d: AuditDraft) -> AuditEvent:
    body = {
        "org_id": org_id, "seq": seq, "at": d.at, "actor": d.actor.user_id,
        "role": d.actor.role.value, "action": d.action, "draft_id": d.draft_id,
        "before": d.before, "after": d.after, "detail": d.detail, "prev_hash": prev_hash,
    }
    return AuditEvent(**body, hash=AuditEvent.digest(body))


def verify_chain(events) -> int | None:
    """체인이 온전하면 None, 아니면 처음 어긋난 위치(0부터)."""
    prev = GENESIS
    for i, e in enumerate(events):
        if e.seq != i or e.prev_hash != prev or AuditEvent.digest(e.body()) != e.hash:
            return i
        prev = e.hash
    return None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class DraftRecord:
    org_id: str
    law_ref: str
    policy_ref: str
    relation: str
    current_text: str
    proposed_text: str
    issues: list[str]
    created_by: str
    draft_id: str = field(default_factory=lambda: str(uuid4()))
    state: DraftState = DraftState.DRAFTED
    submitted_by: str | None = None
    decided_by: str | None = None
    comments: list[tuple[str, str]] = field(default_factory=list)

    @property
    def proposed_hash(self) -> str:
        return content_hash(self.proposed_text)


class PolicyWorkflowRepository(Protocol):
    async def role_of(self, org_id: str, user_id: str) -> Role | None: ...
    async def set_member(self, org_id: str, user_id: str, role: Role) -> None: ...
    async def create(self, draft: DraftRecord, audit: AuditDraft) -> DraftRecord: ...
    async def get(self, org_id: str, draft_id: str) -> DraftRecord | None: ...
    async def list(self, org_id: str) -> list[DraftRecord]: ...
    async def transition(
        self, draft: DraftRecord, expected: DraftState, audit: AuditDraft
    ) -> DraftRecord: ...
    async def add_comment(self, draft: DraftRecord, text: str, audit: AuditDraft) -> None: ...
    async def audit_events(self, org_id: str) -> list[AuditEvent]: ...


class InMemoryPolicyWorkflowRepository:
    """테스트·개발용. Postgres 구현과 같은 계약 테스트를 통과한다."""

    def __init__(self):
        self._members: dict[tuple[str, str], Role] = {}
        self._drafts: dict[tuple[str, str], DraftRecord] = {}
        self._events: dict[str, list[AuditEvent]] = {}
        self._lock = asyncio.Lock()

    async def role_of(self, org_id, user_id):
        return self._members.get((org_id, user_id))

    async def set_member(self, org_id, user_id, role):
        self._members[(org_id, user_id)] = role

    def _append(self, org_id: str, d: AuditDraft) -> AuditEvent:
        chain = self._events.setdefault(org_id, [])
        prev = chain[-1].hash if chain else GENESIS
        event = chain_event(org_id, len(chain), prev, d)
        chain.append(event)
        return event

    async def create(self, draft, audit):
        async with self._lock:
            self._drafts[(draft.org_id, draft.draft_id)] = copy.deepcopy(draft)
            self._append(draft.org_id, audit)
        return draft

    async def get(self, org_id, draft_id):
        d = self._drafts.get((org_id, draft_id))
        return copy.deepcopy(d) if d else None

    async def list(self, org_id):
        return [copy.deepcopy(d) for (o, _), d in self._drafts.items() if o == org_id]

    async def transition(self, draft, expected, audit):
        async with self._lock:
            stored = self._drafts.get((draft.org_id, draft.draft_id))
            if stored is None:
                raise DraftNotFound(draft.draft_id)
            if stored.state is not expected:
                raise WorkflowConflict(f"이미 {stored.state} 상태로 바뀌었다")
            self._drafts[(draft.org_id, draft.draft_id)] = copy.deepcopy(draft)
            self._append(draft.org_id, audit)
        return draft

    async def add_comment(self, draft, text, audit):
        async with self._lock:
            self._drafts[(draft.org_id, draft.draft_id)].comments.append(
                (audit.actor.user_id, text)
            )
            self._append(draft.org_id, audit)

    async def audit_events(self, org_id):
        return list(self._events.get(org_id, []))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ApprovalWorkflow:
    def __init__(self, repo: PolicyWorkflowRepository, org_id: str, clock=_now):
        self.repo = repo
        self.org_id = org_id
        self._clock = clock

    async def actor(self, user_id: str) -> Actor:
        role = await self.repo.role_of(self.org_id, user_id)
        if role is None:
            raise WorkflowForbidden("이 조직의 구성원이 아니다")
        return Actor(user_id, role)

    async def get(self, draft_id: str) -> DraftRecord:
        d = await self.repo.get(self.org_id, draft_id)
        if d is None:
            raise DraftNotFound(f"없는 초안: {draft_id}")
        return d

    def _audit(self, actor: Actor, action: str, d: DraftRecord, before, after,
               detail: dict[str, Any] | None = None) -> AuditDraft:
        return AuditDraft(actor, action, d.draft_id, before, after,
                          {"proposed_hash": d.proposed_hash, **(detail or {})}, self._clock())

    async def _move(self, d: DraftRecord, actor: Actor, action: str, to: DraftState,
                    detail: dict[str, Any] | None = None) -> DraftRecord:
        before = d.state
        d.state = to
        audit = self._audit(actor, action, d, before.value, to.value, detail)
        return await self.repo.transition(d, before, audit)

    async def create(self, user_id: str, *, law_ref: str, policy_ref: str, relation: str,
                     current_text: str, proposed_text: str, issues: list[str]) -> DraftRecord:
        actor = await self.actor(user_id)
        d = DraftRecord(self.org_id, law_ref, policy_ref, relation, current_text,
                        proposed_text, list(issues), created_by=actor.user_id)
        audit = self._audit(actor, "create", d, None, d.state.value,
                            {"law_ref": law_ref, "policy_ref": policy_ref,
                             "relation": relation, "issues": list(issues)})
        return await self.repo.create(d, audit)

    async def submit(self, user_id: str, draft_id: str) -> DraftRecord:
        actor = await self.actor(user_id)
        d = await self.get(draft_id)
        if d.state is not DraftState.DRAFTED:
            raise WorkflowConflict(f"{d.state} 상태에서는 제출할 수 없다")
        d.submitted_by = actor.user_id
        return await self._move(d, actor, "submit", DraftState.IN_REVIEW)

    async def comment(self, user_id: str, draft_id: str, text: str) -> DraftRecord:
        actor = await self.actor(user_id)
        d = await self.get(draft_id)
        if not text.strip():
            raise WorkflowError("빈 의견은 남길 수 없다")
        audit = self._audit(actor, "comment", d, d.state.value, d.state.value,
                            {"text_hash": content_hash(text)})
        await self.repo.add_comment(d, text, audit)
        return await self.get(draft_id)

    def _check_decider(self, actor: Actor, d: DraftRecord) -> None:
        if actor.role is not Role.COMPLIANCE_OFFICER:
            raise WorkflowForbidden("승인·반려는 준법감시인만 할 수 있다")
        if d.state is not DraftState.IN_REVIEW:
            raise WorkflowConflict(f"{d.state} 상태에서는 결정할 수 없다")
        if actor.user_id == d.submitted_by:
            raise WorkflowForbidden("제출자는 자기 초안을 승인·반려할 수 없다(4-eyes)")

    async def approve(self, user_id: str, draft_id: str, *,
                      acknowledged_issues: bool = False) -> DraftRecord:
        actor = await self.actor(user_id)
        d = await self.get(draft_id)
        self._check_decider(actor, d)
        if d.issues and not acknowledged_issues:
            raise WorkflowConflict(f"검증 문제 {len(d.issues)}건을 확인했다고 표시해야 승인된다")
        d.decided_by = actor.user_id
        return await self._move(d, actor, "approve", DraftState.APPROVED,
                                {"acknowledged_issues": list(d.issues)})

    async def reject(self, user_id: str, draft_id: str, *, reason: str) -> DraftRecord:
        actor = await self.actor(user_id)
        d = await self.get(draft_id)
        self._check_decider(actor, d)
        if not reason.strip():
            raise WorkflowError("반려 사유가 필요하다")
        d.decided_by = actor.user_id
        return await self._move(d, actor, "reject", DraftState.REJECTED, {"reason": reason})

    async def revise(self, user_id: str, draft_id: str, *, proposed_text: str) -> DraftRecord:
        """반려된 초안을 사람이 고쳐 다시 올린다. 이전 본문은 감사 로그의 해시로 남는다."""
        actor = await self.actor(user_id)
        d = await self.get(draft_id)
        if d.state is not DraftState.REJECTED:
            raise WorkflowConflict(f"{d.state} 상태에서는 고칠 수 없다")
        old = d.proposed_hash
        d.proposed_text = proposed_text
        d.issues = []  # 사람이 쓴 본문이다 — 모델 검증 문제는 더 이상 해당하지 않는다
        d.submitted_by = None
        d.decided_by = None
        return await self._move(d, actor, "revise", DraftState.DRAFTED, {"previous_hash": old})

    async def verify_audit(self) -> int | None:
        return verify_chain(await self.repo.audit_events(self.org_id))
