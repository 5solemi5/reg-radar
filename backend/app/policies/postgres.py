"""승인 흐름 Postgres 저장소 (migrations/008).

`InMemoryPolicyWorkflowRepository`와 같은 계약 테스트를 통과한다
(tests/test_policy_workflow_repo.py).

감사 체인 추가는 조직 단위 advisory lock 안에서 한다. 체인 끝(seq·hash)을 읽고 다음
이벤트를 쓰는 사이에 다른 요청이 끼어들면 같은 seq가 두 번 생기기 때문이다.
(org_id, seq) 기본키가 마지막 방어선이다.
"""

from __future__ import annotations

import json

import asyncpg

from app.policies.workflow import (
    GENESIS,
    AuditDraft,
    AuditEvent,
    DraftNotFound,
    DraftRecord,
    DraftState,
    Role,
    WorkflowConflict,
    chain_event,
)
from app.repositories.db import Database


def _draft(row: asyncpg.Record, comments: list[tuple[str, str]]) -> DraftRecord:
    return DraftRecord(
        org_id=row["org_id"],
        law_ref=row["law_ref"],
        policy_ref=row["policy_ref"],
        relation=row["relation"],
        current_text=row["current_text"],
        proposed_text=row["proposed_text"],
        issues=list(row["issues"] or []),
        created_by=row["created_by"],
        draft_id=str(row["draft_id"]),
        state=DraftState(row["state"]),
        submitted_by=row["submitted_by"],
        decided_by=row["decided_by"],
        comments=comments,
    )


def _event(row: asyncpg.Record) -> AuditEvent:
    detail = row["detail"]
    if isinstance(detail, str):
        detail = json.loads(detail)
    return AuditEvent(
        org_id=row["org_id"], seq=row["seq"], at=row["at"], actor=row["actor"],
        role=row["role"], action=row["action"], draft_id=str(row["draft_id"]),
        before=row["before"], after=row["after"], detail=detail,
        prev_hash=row["prev_hash"], hash=row["hash"],
    )


async def _append(conn: asyncpg.Connection, org_id: str, d: AuditDraft) -> AuditEvent:
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext('policy_audit:' || $1))", org_id)
    last = await conn.fetchrow(
        "SELECT seq, hash FROM policy_audit_events WHERE org_id = $1 ORDER BY seq DESC LIMIT 1",
        org_id,
    )
    seq, prev = (last["seq"] + 1, last["hash"]) if last else (0, GENESIS)
    e = chain_event(org_id, seq, prev, d)
    await conn.execute(
        """
        INSERT INTO policy_audit_events
            (org_id, seq, at, actor, role, action, draft_id, before, after, detail,
             prev_hash, hash)
        VALUES ($1, $2, $3, $4, $5, $6, $7::uuid, $8, $9, $10::jsonb, $11, $12)
        """,
        e.org_id, e.seq, e.at, e.actor, e.role, e.action, e.draft_id, e.before, e.after,
        e.detail, e.prev_hash, e.hash,  # jsonb 코덱이 직렬화한다(db.py) — dumps하면 이중 인코딩
    )
    return e


class PostgresPolicyWorkflowRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def role_of(self, org_id, user_id):
        role = await self._db.fetchval(
            "SELECT role FROM org_members WHERE org_id = $1 AND user_id = $2", org_id, user_id
        )
        return Role(role) if role else None

    async def set_member(self, org_id, user_id, role):
        await self._db.execute(
            """
            INSERT INTO org_members (org_id, user_id, role) VALUES ($1, $2, $3)
            ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            org_id, user_id, role.value,
        )

    async def create(self, draft, audit):
        async with self._db.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO policy_drafts
                    (draft_id, org_id, law_ref, policy_ref, relation, current_text,
                     proposed_text, issues, state, created_by)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                draft.draft_id, draft.org_id, draft.law_ref, draft.policy_ref, draft.relation,
                draft.current_text, draft.proposed_text, draft.issues, draft.state.value,
                draft.created_by,
            )
            await _append(conn, draft.org_id, audit)
        return draft

    async def _comments(self, conn, draft_id: str) -> list[tuple[str, str]]:
        rows = await conn.fetch(
            "SELECT user_id, body FROM policy_draft_comments WHERE draft_id = $1::uuid "
            "ORDER BY comment_id",
            draft_id,
        )
        return [(r["user_id"], r["body"]) for r in rows]

    async def get(self, org_id, draft_id):
        async with self._db.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM policy_drafts WHERE org_id = $1 AND draft_id = $2::uuid",
                    org_id, draft_id,
                )
            except asyncpg.DataError:  # uuid가 아닌 id — '없는 초안'과 같다
                return None
            if row is None:
                return None
            return _draft(row, await self._comments(conn, draft_id))

    async def list(self, org_id):
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM policy_drafts WHERE org_id = $1 ORDER BY created_at, draft_id",
                org_id,
            )
            return [_draft(r, await self._comments(conn, str(r["draft_id"]))) for r in rows]

    async def transition(self, draft, expected, audit):
        async with self._db.pool.acquire() as conn, conn.transaction():
            # 낙관적 동시성: 읽었을 때의 상태가 그대로일 때만 바꾼다
            updated = await conn.fetchval(
                """
                UPDATE policy_drafts
                SET state = $3, proposed_text = $4, issues = $5, submitted_by = $6,
                    decided_by = $7, updated_at = now()
                WHERE org_id = $1 AND draft_id = $2::uuid AND state = $8
                RETURNING draft_id
                """,
                draft.org_id, draft.draft_id, draft.state.value, draft.proposed_text,
                draft.issues, draft.submitted_by, draft.decided_by, expected.value,
            )
            if updated is None:
                exists = await conn.fetchval(
                    "SELECT state FROM policy_drafts WHERE org_id = $1 AND draft_id = $2::uuid",
                    draft.org_id, draft.draft_id,
                )
                if exists is None:
                    raise DraftNotFound(draft.draft_id)
                raise WorkflowConflict(f"이미 {exists} 상태로 바뀌었다")
            await _append(conn, draft.org_id, audit)
        return draft

    async def add_comment(self, draft, text, audit):
        async with self._db.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO policy_draft_comments (draft_id, user_id, body) "
                "VALUES ($1::uuid, $2, $3)",
                draft.draft_id, audit.actor.user_id, text,
            )
            await _append(conn, draft.org_id, audit)

    async def audit_events(self, org_id):
        rows = await self._db.fetch(
            "SELECT * FROM policy_audit_events WHERE org_id = $1 ORDER BY seq", org_id
        )
        return [_event(r) for r in rows]
