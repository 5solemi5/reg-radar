"""CI용 고정 법령 snapshot 내보내기 (문서 12 §3-4).

로컬 캐시(evaluation/.snapshots, 커밋 안 함)에서 한 데이터셋에 필요한
법령·위임 하위법령 snapshot만 골라
evaluation/ci/snapshots/로 복사한다. 법령 원문은 법제처 공개 자료다.

    .venv/bin/python scripts/export_ci_snapshots.py --dataset evaluation/datasets/holdout_v3.json
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from app.adapters.law.decree import decree_names
from app.adapters.law.store import FileSnapshotStore
from app.diff.engine import detect_delegation
from evaluation.runner import Dataset

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "evaluation" / ".snapshots"
DST = ROOT / "evaluation" / "ci" / "snapshots"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, action="append")
    args = ap.parse_args()

    index = json.loads((SRC / "_index.json").read_text(encoding="utf-8"))
    store = FileSnapshotStore(SRC)
    wanted: set[str] = set()
    for path in args.dataset:
        ds = Dataset.load(path)
        for case in ds.cases:
            law = case["law_name"]
            wanted.add(law)
            snap = store.get(index[law]) if law in index else None
            art = snap.find_article(case["article_no"]) if snap else None
            if art is not None:
                wanted.update(decree_names(law, detect_delegation(art.original_text)))

    DST.mkdir(parents=True, exist_ok=True)
    out_index = (
        json.loads((DST / "_index.json").read_text(encoding="utf-8"))
        if (DST / "_index.json").exists()
        else {}
    )
    copied, missing = 0, []
    for name in sorted(wanted):
        law_id = index.get(name)
        if law_id is None or not store.exists(law_id):
            missing.append(name)
            continue
        src = store._path(law_id)
        shutil.copy2(src, DST / src.name)
        out_index[name] = law_id
        copied += 1
    (DST / "_index.json").write_text(
        json.dumps(out_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"✓ {copied}개 복사 → {DST.relative_to(ROOT)} "
        f"(캐시에 없는 하위법령 {len(missing)}개: {missing})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
