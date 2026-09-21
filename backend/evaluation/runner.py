"""평가 실행기 — 데이터셋을 읽어 실제 파이프라인을 돌리고 실측값을 계산한다.

법령 snapshot은 캐시에 저장해 재실행 시 법제처 호출 없이 동일 입력으로 재현한다
(AP-07). 모델만 바꿔 비교하려면 같은 캐시 위에서 --model만 바꾸면 된다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.adapters.law.client import LawApiClient, LawApiError
from app.adapters.law.decree import decree_names, pair_articles
from app.adapters.law.models import LawSnapshot
from app.adapters.law.store import FileSnapshotStore
from app.ai.chains.base import ChainRunner
from app.ai.llm import LlmGateway
from app.core.config import Settings, get_settings
from app.diff.engine import compute_change, detect_delegation
from app.domain.context import ContextPacket, UserContext
from app.domain.enums import (
    ActivityAnswer,
    Applicability,
    BusinessActivity,
    CompanySize,
)
from app.rag.retriever import NullRetriever
from app.services.analysis_service import analyze_article
from evaluation.metrics import CaseOutcome, Metrics, compute

logger = logging.getLogger(__name__)

EVAL_SNAPSHOT_DIR = Path(__file__).parent / ".snapshots"


@dataclass
class Dataset:
    raw: dict

    @classmethod
    def load(cls, path: str | Path) -> Dataset:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @property
    def cases(self) -> list[dict]:
        return self.raw["cases"]

    def profile(self, key: str) -> UserContext:
        p = self.raw["profiles"][key]
        return UserContext(
            job=p["job"],
            industry=p["industry"],
            company_size=CompanySize(p["company_size"]),
            employee_count=p.get("employee_count"),
            interests=p.get("interests", []),
            activities={
                BusinessActivity(k): ActivityAnswer(v)
                for k, v in (p.get("activities") or {}).items()
            },
        )

    @property
    def required_laws(self) -> list[str]:
        return sorted({c["law_name"] for c in self.cases})


async def ensure_snapshots(
    dataset: Dataset, settings: Settings, *, offline: bool
) -> dict[str, LawSnapshot]:
    """필요한 법령 snapshot을 확보한다. 캐시 우선, 없으면 법제처에서 가져온다."""
    return await fetch_by_names(dataset.required_laws, settings, offline=offline)


async def fetch_by_names(
    names_wanted: list[str], settings: Settings, *, offline: bool, optional: bool = False
) -> dict[str, LawSnapshot]:
    """법령명 목록을 snapshot으로 확보한다. 캐시 우선, 없으면 법제처에서."""
    store = FileSnapshotStore(EVAL_SNAPSHOT_DIR)
    by_name: dict[str, LawSnapshot] = {}

    index_path = EVAL_SNAPSHOT_DIR / "_index.json"
    index: dict[str, str] = (
        json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    )

    missing: list[str] = []
    for name in names_wanted:
        law_id = index.get(name)
        cached = store.get(law_id) if law_id else None
        if cached is not None:
            by_name[name] = cached
        else:
            missing.append(name)

    if not missing:
        return by_name

    if offline:
        if optional:
            return by_name
        raise RuntimeError(
            f"캐시에 없는 법령이 있습니다: {missing}. --offline 없이 한 번 실행하세요."
        )

    async with LawApiClient(settings=settings) as client:
        for name in missing:
            laws = await client.search_laws(query=name, display=5)
            target = next((law for law in laws if law.law_name == name), None)
            if target is None:
                if optional:
                    print(f"  · 없음(건너뜀): {name}")
                    continue
                raise LawApiError(
                    f"'{name}'을(를) 찾지 못했습니다. 검색결과: {[x.law_name for x in laws]}"
                )
            snapshot = await client.fetch_law_detail(target)
            store.save(snapshot)
            index[name] = snapshot.law_id
            by_name[name] = snapshot
            print(f"  · snapshot 확보: {name} (조문 {len(snapshot.articles)}건)")

    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return by_name


async def run_case(
    case: dict,
    dataset: Dataset,
    snapshots: dict[str, LawSnapshot],
    gateway: LlmGateway,
    retriever=None,
    decrees: dict[str, LawSnapshot] | None = None,
) -> CaseOutcome:
    law_name, article_no = case["law_name"], case["article_no"]
    gold = Applicability(case["gold_applicability"])

    base = CaseOutcome(
        case_id=case["id"],
        law_name=law_name,
        article_no=article_no,
        profile=case["profile"],
        gold=gold,
        predicted=None,
        status=None,
        action_grade=None,
        expected_action_grade=case.get("expected_action_grade", []),
        expected_missing_keyword=case.get("expected_missing_context_keyword"),
        expects_delegation=case.get("expects_delegation", False),
    )

    snapshot = snapshots[law_name]
    article = snapshot.find_article(article_no)
    if article is None:
        base.error = f"{article_no} 없음"
        return base

    legal = snapshot.to_legal_context(article_no)
    base.detected_delegation = detect_delegation(legal.original_text)

    # change_mode=as_new: 조문 전체를 신설로 간주 (데이터셋 labeling_policy 참조)
    change = compute_change(None, legal.original_text)

    user = dataset.profile(case["profile"])
    rag = await (retriever or NullRetriever()).retrieve(legal, user)
    base.rag_count = len(rag)

    # ADR-025: 위임된 하위법령 조문을 붙인다. 캐시된 snapshot에서 찾으므로
    # --offline 재현성이 유지된다.
    delegated = []
    for decree_name in decree_names(law_name, change.delegation_targets):
        decree = (decrees or {}).get(decree_name)
        if decree is not None:
            delegated.extend(pair_articles(article_no, article.article_title, decree))
    base.delegated_count = len(delegated)

    packet = ContextPacket(
        user=user, law=legal, change=change, delegated=delegated, rag=rag
    )

    try:
        outcome = await analyze_article(ChainRunner(llm=gateway), packet)
    except Exception as exc:
        base.error = str(exc)
        return base

    r = outcome.result
    ai = r.ai_interpretation
    base.predicted = r.applicability
    base.status = r.status
    base.action_grade = r.action_grade
    base.missing_context = ai.missing_context
    base.cited_verified = len(r.legal_evidence.quoted_spans)
    base.cited_total = len(r.legal_evidence.quoted_spans) + len(r.validation.dropped_spans)
    base.dropped_spans = r.validation.dropped_spans
    base.fabrication_failures = [
        f for f in r.validation.failures if "생성했습니다" in f or "인용했습니다" in f
    ]
    base.latency_ms = outcome.total_latency_ms
    return base


def build_retriever(settings: Settings):
    """평가용 Retriever. 구성에 실패하면 참고자료 없이 측정한다."""
    from app.rag.embeddings import OpenAIEmbedder
    from app.rag.retriever import Retriever
    from app.rag.store import build_store

    return Retriever(
        OpenAIEmbedder(settings), build_store(settings), top_k=settings.rag_top_k
    )


async def run_dataset(
    dataset_path: str | Path,
    *,
    settings: Settings | None = None,
    offline: bool = False,
    concurrency: int = 3,
    use_rag: bool = False,
) -> tuple[Metrics, list[CaseOutcome]]:
    settings = settings or get_settings()
    dataset = Dataset.load(dataset_path)

    print(f"▶ 데이터셋: {dataset.raw['dataset_id']} · 케이스 {len(dataset.cases)}건")
    snapshots = await ensure_snapshots(dataset, settings, offline=offline)

    decrees: dict[str, LawSnapshot] = {}
    if settings.decree_pairing_enabled:
        wanted: list[str] = []
        for case in dataset.cases:
            article = snapshots[case["law_name"]].find_article(case["article_no"])
            if article is None:
                continue
            targets = detect_delegation(article.original_text)
            for name in decree_names(case["law_name"], targets):
                if name not in wanted:
                    wanted.append(name)
        if wanted:
            decrees = await fetch_by_names(
                wanted, settings, offline=offline, optional=True
            )
        print(f"▶ 위임 하위법령: {len(decrees)}/{len(wanted)}건 확보")
    else:
        print("▶ 위임 하위법령: 꺼짐")
    retriever = None
    if use_rag:
        try:
            retriever = build_retriever(settings)
            from app.rag.store import build_store

            print(f"▶ RAG: 켜짐 · 색인 {await build_store(settings).count()}개 청크")
        except Exception as exc:
            print(f"▶ RAG: 구성 실패 — 참고자료 없이 측정합니다 ({exc})")
    else:
        print("▶ RAG: 꺼짐")
    print(f"▶ 모델: {settings.llm_model}\n")

    gateway = LlmGateway(settings=settings)
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(case: dict) -> CaseOutcome:
        async with semaphore:
            result = await run_case(
                case, dataset, snapshots, gateway, retriever, decrees
            )
            mark = "✓" if result.correct else ("!" if result.error else "✗")
            predicted = result.predicted.value if result.predicted else f"ERROR({result.error})"
            print(f"  {mark} {result.case_id} {result.law_name} {result.article_no} "
                  f"[{result.profile}] gold={result.gold.value} → {predicted}")
            return result

    outcomes = await asyncio.gather(*(guarded(c) for c in dataset.cases))
    return compute(list(outcomes)), list(outcomes)
