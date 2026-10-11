"""평가 실행 CLI.

    .venv/bin/python scripts/run_eval.py
    .venv/bin/python scripts/run_eval.py --offline          # 캐시된 snapshot만 사용
    .venv/bin/python scripts/run_eval.py --model gpt-4o     # 모델 비교
    .venv/bin/python scripts/run_eval.py --offline --record # 실제 호출하며 응답을 녹화 (과금)
    .venv/bin/python scripts/run_eval.py --offline --replay # 녹화로 재생 — 키·과금 없음, 결정적
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.ai.cassette import Cassette, CassetteMode
from app.core.config import get_settings
from evaluation.provenance import git_state, prompt_version, sha256_file, usage_and_cost
from evaluation.report import render
from evaluation.runner import Dataset, run_dataset

DEFAULT_DATASET = Path(__file__).parent.parent / "evaluation" / "datasets" / "applicability_v1.json"
RESULTS_DIR = Path(__file__).parent.parent / "evaluation" / "results"
CASSETTE_DIR = Path(__file__).parent.parent / "evaluation" / "cassettes"


def cassette_path(dataset_path: str, model: str) -> Path:
    return CASSETTE_DIR / f"{Path(dataset_path).stem}__{model}.jsonl"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--model", default=None, help="LLM_MODEL 덮어쓰기")
    parser.add_argument("--offline", action="store_true", help="법제처 호출 없이 캐시만 사용")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--save", action="store_true", help="결과를 evaluation/results에 저장")
    parser.add_argument("--rag", action="store_true", help="참고자료를 붙여 측정")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="실제 호출하며 응답을 cassette에 녹화")
    mode.add_argument("--replay", action="store_true", help="cassette로 재생 (LLM 호출·키 불필요)")
    parser.add_argument(
        "--cassette",
        default=None,
        help="cassette 경로 (기본: evaluation/cassettes/<데이터셋>__<모델>.jsonl)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.model:
        settings = settings.model_copy(update={"llm_model": args.model})
    if args.replay and args.rag:
        print("✗ 재생은 RAG 없이만 지원한다 (임베딩 호출은 녹화하지 않는다).")
        return 1
    if not args.replay and not settings.llm_enabled:
        print("✗ OPENAI_API_KEY가 없습니다.")
        return 1

    cassette = None
    if args.record or args.replay:
        cassette = Cassette(
            args.cassette or cassette_path(args.dataset, settings.llm_model),
            CassetteMode.RECORD if args.record else CassetteMode.REPLAY,
            settings.llm_model,
        )

    metrics, outcomes = await run_dataset(
        args.dataset,
        settings=settings,
        offline=args.offline,
        concurrency=args.concurrency,
        use_rag=args.rag,
        cassette=cassette,
    )
    provenance = {
        "dataset_id": Dataset.load(args.dataset).raw["dataset_id"],
        "dataset_sha256": sha256_file(Path(args.dataset)),
        "prompt_version": prompt_version(),
        "git": git_state(),
        "cassette": cassette.summary() if cassette else {"mode": "off"},
        "usage": usage_and_cost(outcomes, settings.llm_model),
    }
    print(f"▶ 출처: {json.dumps(provenance, ensure_ascii=False)}")

    print()
    report = render(metrics, outcomes, settings.llm_model)
    print(report)

    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        suffix = ("_rag" if args.rag else "") + ("_replay" if args.replay else "")
        base = RESULTS_DIR / f"{stamp}_{settings.llm_model}{suffix}"
        base.with_suffix(".txt").write_text(report, encoding="utf-8")
        base.with_suffix(".json").write_text(
            json.dumps(
                {
                    "model": settings.llm_model,
                    "rag": args.rag,
                    "ran_at": stamp,
                    "provenance": provenance,
                    "metrics": {
                        k: v for k, v in vars(metrics).items() if k != "failures"
                    },
                    "cases": [
                        {
                            "id": o.case_id,
                            "law": o.law_name,
                            "article": o.article_no,
                            "profile": o.profile,
                            "gold": o.gold.value,
                            "predicted": o.predicted.value if o.predicted else None,
                            "status": o.status.value if o.status else None,
                            "action_grade": o.action_grade.value if o.action_grade else None,
                            "missing_context": o.missing_context,
                            "dropped_spans": o.dropped_spans,
                            "latency_ms": o.latency_ms,
                            "rag_count": o.rag_count,
                            "error": o.error,
                        }
                        for o in outcomes
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n✓ 저장: {base}.txt / .json")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
