"""평가 실행 CLI.

    .venv/bin/python scripts/run_eval.py
    .venv/bin/python scripts/run_eval.py --offline          # 캐시된 snapshot만 사용
    .venv/bin/python scripts/run_eval.py --model gpt-4o     # 모델 비교
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from evaluation.report import render
from evaluation.runner import run_dataset

DEFAULT_DATASET = Path(__file__).parent.parent / "evaluation" / "datasets" / "applicability_v1.json"
RESULTS_DIR = Path(__file__).parent.parent / "evaluation" / "results"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--model", default=None, help="LLM_MODEL 덮어쓰기")
    parser.add_argument("--offline", action="store_true", help="법제처 호출 없이 캐시만 사용")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--save", action="store_true", help="결과를 evaluation/results에 저장")
    args = parser.parse_args()

    settings = get_settings()
    if args.model:
        settings = settings.model_copy(update={"llm_model": args.model})
    if not settings.llm_enabled:
        print("✗ OPENAI_API_KEY가 없습니다.")
        return 1

    metrics, outcomes = await run_dataset(
        args.dataset, settings=settings, offline=args.offline, concurrency=args.concurrency
    )

    print()
    report = render(metrics, outcomes, settings.llm_model)
    print(report)

    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        base = RESULTS_DIR / f"{stamp}_{settings.llm_model}"
        base.with_suffix(".txt").write_text(report, encoding="utf-8")
        base.with_suffix(".json").write_text(
            json.dumps(
                {
                    "model": settings.llm_model,
                    "ran_at": stamp,
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
