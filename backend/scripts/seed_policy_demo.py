"""승인 흐름 시연용 데이터 (LLM 호출 없음, 비용 없음).

초안 생성(C8)에는 LLM이 필요하다. 화면에서 승인 흐름만 보여 주려면 이 스크립트로
구성원 2명과 초안 1건을 Postgres에 넣는다. **대상 DB의 사내 규정 테이블을 비운다.**

    DATABASE_URL=postgresql://127.0.0.1:5432/regradar_test \\
        .venv/bin/python scripts/seed_policy_demo.py
"""

import asyncio
import os
import sys

from app.core.config import Settings
from app.policies.models import PolicyCorpus
from app.policies.postgres import PostgresPolicyWorkflowRepository
from app.policies.workflow import ApprovalWorkflow, Role
from app.repositories.db import Database

ORG = "virtual-card-co"


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("✗ DATABASE_URL이 필요합니다 (migrations/008이 적용된 DB).")
        return 1
    db = Database(Settings(database_url=url, storage="postgres"))
    await db.connect()
    try:
        await db.execute(
            "TRUNCATE policy_audit_events, policy_draft_comments, policy_drafts, org_members"
        )
        repo = PostgresPolicyWorkflowRepository(db)
        await repo.set_member(ORG, "dev-user", Role.STAFF)
        await repo.set_member(ORG, "dev-officer", Role.COMPLIANCE_OFFICER)
        art = PolicyCorpus.load("virtual-card-co-v3").get("HR-01 제22조")
        draft = await ApprovalWorkflow(repo, ORG).create(
            "dev-user", law_ref="근로기준법 제60조", policy_ref=art.ref, relation="CONFLICT",
            current_text=art.text, proposed_text=art.text.replace("20일을 한도로", "25일을 한도로"),
            issues=[],
        )
    finally:
        await db.disconnect()
    print(f"✓ 구성원 dev-user(STAFF), dev-officer(COMPLIANCE_OFFICER) · 초안 {draft.draft_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
