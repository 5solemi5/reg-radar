"""사내 규정 평가 데이터셋 검사 — LLM 없이(0원) 돈다.

라벨이 가리키는 조항이 실제 규정집에 있는지, 그 조항이 검색 후보(top-5)에 들어오는지 본다.
검색에서 빠진 정답은 LLM이 아무리 좋아도 찾을 수 없다(검색 재현율).
"""

import json
from pathlib import Path

import pytest

from app.policies.models import PolicyCorpus
from app.policies.service import PolicyImpactService

DATASETS = Path(__file__).parent.parent / "evaluation" / "datasets"
SNAPSHOTS = Path(__file__).parent.parent / "evaluation" / "ci" / "snapshots"
NAMES = sorted(p.name for p in DATASETS.glob("policy_impact_*.json"))
# 알려진 검색 실패: 채용절차법 제4조의3 ↔ HR-02 제5조 (어휘가 거의 안 겹친다, 문서 12 §6-3)
KNOWN_MISSES = {("채용절차의 공정화에 관한 법률", "제4조의3", "HR-02 제5조")}


@pytest.mark.parametrize("name", NAMES)
def test_라벨이_규정집과_법령_캐시에_있다(name, monkeypatch):
    from evaluation import policy_impact

    monkeypatch.setattr(policy_impact, "EVAL_SNAPSHOT_DIR", SNAPSHOTS)
    ds = json.loads((DATASETS / name).read_text(encoding="utf-8"))
    corpus = PolicyCorpus.load(ds.get("corpus", "virtual-card-co"))
    refs = {a.ref for a in corpus.articles}
    for case in ds["cases"]:
        assert set(case["gold"]) <= refs, (case["id"], set(case["gold"]) - refs)
        assert set(case["gold"].values()) <= {"ACTION", "NO_ACTION", "EITHER"}
        policy_impact.load_law(case["law_name"], case["article_no"])  # 캐시에 없으면 KeyError


@pytest.mark.parametrize("name", NAMES)
def test_정답_조항이_검색_후보에_들어온다(name, monkeypatch):
    from evaluation import policy_impact

    monkeypatch.setattr(policy_impact, "EVAL_SNAPSHOT_DIR", SNAPSHOTS)
    ds = json.loads((DATASETS / name).read_text(encoding="utf-8"))
    svc = PolicyImpactService(None, PolicyCorpus.load(ds.get("corpus", "virtual-card-co")))
    missed = []
    for case in ds["cases"]:
        law = policy_impact.load_law(case["law_name"], case["article_no"])
        cands = {c.article.ref for c in svc.candidates(law)}
        for ref, g in case["gold"].items():
            key = (case["law_name"], case["article_no"], ref)
            if g == "ACTION" and ref not in cands and key not in KNOWN_MISSES:
                missed.append((case["id"], ref))
    assert missed == []
