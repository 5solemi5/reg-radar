"""사내 규정 영향 평가 (문서 12 §4, 데이터셋 policy_impact_v1).

지표
- 검색 재현율: gold ACTION 조문이 후보(top-k)에 들어왔는가. 못 들어오면 LLM도 찾을 수 없다.
- 조치 재현율: gold ACTION 조문이 ACTIONABLE(양쪽 원문 근거 확인)로 나왔는가.
- 사람 검토 포함 재현율: ACTIONABLE 또는 NEEDS_REVIEW — 적어도 사람 눈에는 띄었는가.
- 조치 정밀도: ACTIONABLE 중 gold ACTION 비율(EITHER는 분모·분자에서 뺀다).
- 음성 대조군 오조치: 무관한 법령에서 ACTIONABLE이 하나라도 나온 케이스 수.
- 인용 정확도: 모델이 낸 인용 중 원문에서 확인된 비율.
- 초안: 조치 대상마다 C8을 돌려 검증 문제 수와 필수 수정(must_contain / must_not_contain)
  충족을 본다.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.adapters.law.models import LawSnapshot
from app.ai.cassette import Cassette
from app.ai.chains.base import ChainExecutionError, ChainRunner
from app.ai.llm import LlmGateway
from app.policies.models import PolicyCorpus
from app.policies.service import FindingStatus, PolicyImpactService
from app.validator.rules import normalize_for_match
from evaluation.runner import EVAL_SNAPSHOT_DIR


@dataclass
class CaseResult:
    case_id: str
    split: str
    law_ref: str
    candidates: list[str]
    findings: dict[str, dict]  # policy_ref → {relation, status, issues, dropped}
    gold: dict[str, str]
    drafts: dict[str, dict] = field(default_factory=dict)
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def load_law(law_name: str, article_no: str):
    index = json.loads((EVAL_SNAPSHOT_DIR / "_index.json").read_text(encoding="utf-8"))
    snap = LawSnapshot.model_validate_json(
        (EVAL_SNAPSHOT_DIR / f"{index[law_name]}.json").read_text(encoding="utf-8")
    )
    return snap.to_legal_context(article_no)


def _contains(text: str, needle: str) -> bool:
    return normalize_for_match(needle) in normalize_for_match(text)


async def run_case(case: dict, service: PolicyImpactService, runner: ChainRunner) -> CaseResult:
    law = load_law(case["law_name"], case["article_no"])
    res = CaseResult(case["id"], case["split"], f"{law.law_name} {law.article_no}", [], {},
                     dict(case["gold"]))
    try:
        report = await service.assess(law)
        res.candidates = [c.article.ref for c in report.candidates]
        for f in report.findings:
            res.findings[f.policy_ref] = {
                "relation": f.relation.value if f.relation else None,
                "status": f.status.value,
                "issues": f.issues,
                "dropped": f.dropped_spans,
                "cited": len(f.law_spans) + len(f.policy_spans),
                "review": f.review,
            }
        for f in report.findings:
            # 초안 품질은 정답이 ACTION인 조치 대상에서만 잰다(오조치의 초안은 채점 기준이 없다)
            if f.status is not FindingStatus.ACTIONABLE:
                continue
            if case["gold"].get(f.policy_ref) != "ACTION":
                continue
            d = await service.draft(law, f)
            must = case.get("draft_must_contain", {}).get(f.policy_ref, [])
            must_not = case.get("draft_must_not_contain", {}).get(f.policy_ref, [])
            text = d.draft.proposed_text
            res.drafts[f.policy_ref] = {
                "issues": d.issues,
                "missing": [m for m in must if not _contains(text, m)],
                "leftover": [m for m in must_not if _contains(text, m)],
                "proposed_text": text,
                "open_questions": d.draft.open_questions,
            }
    except ChainExecutionError as exc:
        res.error = str(exc)
    res.input_tokens = sum(t.input_tokens for t in runner.traces)
    res.output_tokens = sum(t.output_tokens for t in runner.traces)
    return res


async def run(dataset_path: Path, *, split: str, settings, cassette: Cassette | None,
              concurrency: int = 3) -> tuple[dict, list[CaseResult]]:
    ds = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    cases = [c for c in ds["cases"] if split == "all" or c["split"] == split]
    corpus = PolicyCorpus.load(ds.get("corpus", "virtual-card-co"))
    gateway = LlmGateway(settings=settings)
    sem = asyncio.Semaphore(concurrency)

    async def one(case):
        async with sem:
            runner = ChainRunner(llm=gateway, cassette=cassette)
            return await run_case(case, PolicyImpactService(runner, corpus), runner)

    results = await asyncio.gather(*(one(c) for c in cases))
    return score(results), list(results)


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def score(results: list[CaseResult]) -> dict:
    gold_action = [(r, ref) for r in results for ref, g in r.gold.items() if g == "ACTION"]
    retrieved = sum(ref in r.candidates for r, ref in gold_action)
    actionable = sum(
        r.findings.get(ref, {}).get("status") == "ACTIONABLE" for r, ref in gold_action
    )
    surfaced = sum(
        r.findings.get(ref, {}).get("status") in ("ACTIONABLE", "NEEDS_REVIEW")
        for r, ref in gold_action
    )
    predicted = [
        (r, ref) for r in results for ref, f in r.findings.items()
        if f["status"] == "ACTIONABLE" and r.gold.get(ref) != "EITHER"
    ]
    correct = sum(r.gold.get(ref) == "ACTION" for r, ref in predicted)
    negatives = [r for r in results if not r.gold]
    false_on_neg = sum(
        any(f["status"] == "ACTIONABLE" for f in r.findings.values()) for r in negatives
    )
    cited = sum(f["cited"] for r in results for f in r.findings.values())
    dropped = sum(len(f["dropped"]) for r in results for f in r.findings.values())
    review = sum(f["status"] == "NEEDS_REVIEW" for r in results for f in r.findings.values())
    total_findings = sum(len(r.findings) for r in results)
    drafts = [d for r in results for d in r.drafts.values()]
    return {
        "cases": len(results),
        "errors": sum(r.error is not None for r in results),
        "gold_action": len(gold_action),
        "retrieval_recall": _ratio(retrieved, len(gold_action)),
        "action_recall": _ratio(actionable, len(gold_action)),
        "surfaced_recall": _ratio(surfaced, len(gold_action)),
        "action_precision": _ratio(correct, len(predicted)),
        "negative_cases": len(negatives),
        "negative_false_action": false_on_neg,
        "citation_accuracy": _ratio(cited, cited + dropped),
        "needs_review_rate": _ratio(review, total_findings),
        "drafts": len(drafts),
        "drafts_with_issues": sum(bool(d["issues"]) for d in drafts),
        "drafts_fix_complete": sum(not d["missing"] and not d["leftover"] for d in drafts),
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
    }


def render(metrics: dict, results: list[CaseResult]) -> str:
    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"

    m = metrics
    lines = [
        f"케이스 {m['cases']}건 (오류 {m['errors']}) · gold ACTION {m['gold_action']}건",
        f"검색 재현율 (후보 top-k에 정답 포함)   {pct(m['retrieval_recall'])}",
        f"조치 재현율 (양쪽 근거 확인된 ACTIONABLE) {pct(m['action_recall'])}",
        f"사람 검토 포함 재현율                   {pct(m['surfaced_recall'])}",
        f"조치 정밀도                             {pct(m['action_precision'])}",
        f"음성 대조군 오조치                       "
        f"{m['negative_false_action']}/{m['negative_cases']}건",
        f"인용 정확도 (모델 인용 중 원문 확인)     {pct(m['citation_accuracy'])}",
        f"NEEDS_REVIEW 비율                        {pct(m['needs_review_rate'])}",
        f"초안 {m['drafts']}건 · 검증 문제 있음 {m['drafts_with_issues']} · "
        f"필수 수정 충족 {m['drafts_fix_complete']}",
        "",
        "── 케이스 ─────────────────────────────────────────────────────────",
    ]
    for r in results:
        err = f"  ERROR {r.error}" if r.error else ""
        lines.append(f"{r.case_id} [{r.split}] {r.law_ref}{err}")
        for ref in r.candidates:
            f = r.findings.get(ref, {})
            g = r.gold.get(ref, "NO_ACTION")
            flag = ""
            if g == "ACTION" and f.get("status") != "ACTIONABLE":
                flag = "  ← 놓침" if f.get("status") != "NEEDS_REVIEW" else "  ← 사람 검토로"
            elif g == "NO_ACTION" and f.get("status") == "ACTIONABLE":
                flag = "  ← 오조치"
            rel = str(f.get("relation"))
            lines.append(f"   {ref:<14} gold={g:<9} {rel:<18} {f.get('status')}{flag}")
            for issue in f.get("issues", []):
                lines.append(f"      · {issue}")
        for ref, g in r.gold.items():
            if g == "ACTION" and ref not in r.candidates:
                lines.append(f"   {ref:<14} gold=ACTION    ← 검색 후보에 없음")
        for ref, d in r.drafts.items():
            lines.append(
                f"   초안 {ref}: 문제 {d['issues'] or '없음'} · 누락 {d['missing'] or '없음'}"
                f" · 잔존 {d['leftover'] or '없음'}"
            )
    lines += [
        "",
        f"※ 사내 규정집은 가상이다. 표본이 작다(케이스 {m['cases']}건, ACTION {m['gold_action']}건)"
        " — 방향 확인용이다.",
        "※ ALIGNED·UNRELATED는 원문 근거로 검증할 수 없어 런타임에서 막지 못한다."
        " 놓침은 이 평가로만 보인다.",
    ]
    return "\n".join(lines)
