"""사내 규정 영향 분석·승인 API (R3). LLM은 스키마별 가짜 응답으로 대신한다."""

import json
import re
from pathlib import Path

import pytest

from app.adapters.law.models import LawSnapshot
from app.ai.chains.base import ChainRunner, ChainTrace
from app.api import deps as _deps
from app.policies.models import PolicyCorpus
from app.policies.schemas import ImpactReview, PolicyImpactOutput, PolicyRevisionDraft
from app.policies.service import PolicyImpactService
from app.policies.workflow import ApprovalWorkflow, InMemoryPolicyWorkflowRepository, Role
from app.repositories.memory import InMemorySnapshotRepository

SNAPSHOTS = Path(__file__).parent.parent / "evaluation" / "ci" / "snapshots"
LAW_NAME = "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"
ORG = "virtual-card-co"


class ScriptedRunner(ChainRunner):
    """C7: '배우자 출산휴가' 후보만 CONFLICT. C7b: 확인. C8: 법 수치로 고친 초안."""

    def __init__(self):
        super().__init__(llm=None)

    async def invoke(self, *, chain, prompt, schema):
        self._record(ChainTrace(chain, "gpt-4o", 1, True, input_tokens=100, output_tokens=10))
        if schema is PolicyImpactOutput:
            items = []
            for label, block in re.findall(r"\[(P\d+)\]([^\[]*)", prompt):
                hit = "배우자 출산휴가" in block
                items.append({
                    "candidate": label, "relation": "CONFLICT" if hit else "UNRELATED",
                    "reason": "기간이 다르다" if hit else "무관",
                    "cited_law_spans": ["20일의 휴가를 주어야 한다"] if hit else [],
                    "cited_policy_spans": ["10일의 유급휴가를 주어야 한다"] if hit else [],
                })
            return PolicyImpactOutput.model_validate({"items": items})
        if schema is ImpactReview:
            return ImpactReview(verdict="CONFIRM", reason="기간 부족",
                                missing_requirement_spans=["20일의 휴가를 주어야 한다"])
        if schema is PolicyRevisionDraft:
            return PolicyRevisionDraft(
                proposed_text="회사는 직원이 배우자의 출산을 이유로 휴가를 청구하는 경우 20일의 "
                              "유급휴가를 주어야 한다. 휴가는 배우자가 출산한 날부터 120일 이내에 "
                              "사용하여야 하며, 3회에 한정하여 나누어 사용할 수 있다.",
                cited_law_spans=["20일의 휴가를 주어야 한다"],
                change_summary=["휴가 일수 10일 → 20일"],
            )
        raise AssertionError(schema)


@pytest.fixture
async def setup(app, store):
    index = json.loads((SNAPSHOTS / "_index.json").read_text(encoding="utf-8"))
    snap = LawSnapshot.model_validate_json(
        (SNAPSHOTS / f"{index[LAW_NAME]}.json").read_text(encoding="utf-8")
    )
    await InMemorySnapshotRepository(store).save(snap)

    repo = InMemoryPolicyWorkflowRepository()
    for user, role in [("user-a", Role.STAFF), ("officer", Role.COMPLIANCE_OFFICER)]:
        await repo.set_member(ORG, user, role)
    app.dependency_overrides[_deps.get_policy_workflow] = lambda: ApprovalWorkflow(repo, ORG)
    app.dependency_overrides[_deps.get_policy_service] = lambda: PolicyImpactService(
        ScriptedRunner(), PolicyCorpus.load("virtual-card-co-v2")
    )
    return snap.law_id


async def test_영향_판단부터_승인과_감사_검증까지(client, setup):
    law_id = setup
    r = await client.post("/api/v1/policy/impact",
                          json={"law_id": law_id, "article_no": "제18조의2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "가상" in body["corpus_label"]
    actionable = [f for f in body["findings"] if f["status"] == "ACTIONABLE"]
    assert [f["policy_ref"] for f in actionable] == ["HR-01 제25조"]
    assert actionable[0]["review"] == "CONFIRM"

    r = await client.post("/api/v1/policy/drafts", json={
        "law_id": law_id, "article_no": "제18조의2", "policy_ref": "HR-01 제25조"})
    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["state"] == "DRAFTED" and draft["issues"] == []
    did = draft["draft_id"]

    assert (await client.post(f"/api/v1/policy/drafts/{did}/submit")).json()["state"] == "IN_REVIEW"

    # 현업은 승인할 수 없다 → 403
    r = await client.post(f"/api/v1/policy/drafts/{did}/approve", json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "policy_forbidden"

    r = await client.post(f"/api/v1/policy/drafts/{did}/approve", json={},
                          headers={"X-User-Id": "officer"})
    assert r.status_code == 200 and r.json()["state"] == "APPROVED"

    # 이미 승인된 초안을 다시 결정 → 409
    r = await client.post(f"/api/v1/policy/drafts/{did}/reject", json={"reason": "x"},
                          headers={"X-User-Id": "officer"})
    assert r.status_code == 409

    from app.api.deps import get_memory_trace_repo

    chains = [r.chain for r in get_memory_trace_repo().records if r.law_id == law_id]
    assert {"C7_policy_impact", "C7b_impact_review", "C8_policy_draft"} <= set(chains)

    audit = (await client.get("/api/v1/policy/audit")).json()
    assert audit["intact"] is True
    assert [e["action"] for e in audit["events"]] == ["create", "submit", "approve"]


async def test_개정_대상이_아닌_조항으로는_초안을_만들지_않는다(client, setup):
    r = await client.post("/api/v1/policy/drafts", json={
        "law_id": setup, "article_no": "제18조의2", "policy_ref": "HR-01 제10조"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "policy_invalid"


async def test_구성원이_아니면_403(client, setup):
    r = await client.get("/api/v1/policy/drafts", headers={"X-User-Id": "stranger"})
    assert r.status_code == 403


async def test_없는_초안과_없는_조문은_404(client, setup):
    assert (await client.get("/api/v1/policy/drafts/nope")).status_code == 404
    r = await client.post("/api/v1/policy/impact", json={"law_id": "x", "article_no": "제1조"})
    assert r.status_code == 404


async def test_AI가_꺼져_있으면_503(app, client, setup):
    app.dependency_overrides[_deps.get_policy_service] = lambda: None
    r = await client.post("/api/v1/policy/impact",
                          json={"law_id": setup, "article_no": "제18조의2"})
    assert r.status_code == 503
