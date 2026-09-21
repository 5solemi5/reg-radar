"""평가 데이터셋 무결성.

홀드아웃은 '한 번도 튜닝에 쓰지 않았다'는 약속 위에서만 의미가 있는데, 그 약속은
코드가 아니라 규율이라 조용히 깨진다. 개발셋 법령이 홀드아웃에 섞이거나 케이스가
중복되면 62.5%라는 수치가 측정하는 것이 일반화가 아니라 암기가 되지만, 사람 눈으로는
알아채기 어렵다. 그래서 테스트로 고정한다.
"""

import json
from pathlib import Path

import pytest

from app.domain.enums import Applicability

DATASETS = Path(__file__).parent.parent / "evaluation" / "datasets"

ALL = sorted(p.name for p in DATASETS.glob("*.json"))
"""디렉터리를 훑는다. 데이터셋을 추가하면 검사도 자동으로 따라붙는다."""

HOLDOUTS = [name for name in ALL if name.startswith("holdout_")]


def load(name: str) -> dict:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


def laws(name: str) -> set[str]:
    return {c["law_name"] for c in load(name)["cases"]}


def test_데이터셋이_최소한_개발셋과_홀드아웃을_포함한다() -> None:
    """홀드아웃 파일이 통째로 사라지면 아래 검사들이 조용히 0건이 된다."""
    assert "applicability_v1.json" in ALL
    assert HOLDOUTS, "홀드아웃 데이터셋이 하나도 없습니다"


@pytest.mark.parametrize("name", HOLDOUTS)
def test_홀드아웃_법령이_개발셋과_겹치지_않는다(name: str) -> None:
    overlap = laws("applicability_v1.json") & laws(name)
    assert not overlap, (
        f"{name}에 개발셋 법령이 섞였습니다: {sorted(overlap)}. "
        "겹치는 순간 홀드아웃이 재는 것은 일반화가 아니라 암기입니다."
    )


def test_홀드아웃끼리도_겹치지_않는다() -> None:
    """v1이 소진돼 v2를 만들었는데 법령이 같으면 v2도 이미 오염된 셋이다."""
    for i, a in enumerate(HOLDOUTS):
        for b in HOLDOUTS[i + 1 :]:
            overlap = laws(a) & laws(b)
            assert not overlap, f"{a} ↔ {b} 법령 겹침: {sorted(overlap)}"


def test_후속_홀드아웃은_보류_케이스를_더_많이_담는다() -> None:
    """v1의 HOLD 2건으로는 보류 정밀도를 잴 수 없었다. 그게 v2를 만든 이유다.

    이 검사가 없으면 다음 홀드아웃도 같은 약점을 그대로 물려받는다.
    """
    counts = {
        name: sum(c["gold_applicability"] == "HOLD" for c in load(name)["cases"])
        for name in HOLDOUTS
    }
    for earlier, later in zip(HOLDOUTS, HOLDOUTS[1:], strict=False):
        assert counts[later] >= counts[earlier], (
            f"{later}의 HOLD 케이스({counts[later]}건)가 {earlier}({counts[earlier]}건)보다 "
            "적습니다. 후속 홀드아웃은 앞선 셋의 약점을 메워야 합니다."
        )


@pytest.mark.parametrize("name", ALL)
def test_모든_케이스가_정의된_프로필을_참조한다(name: str) -> None:
    data = load(name)
    defined = set(data["profiles"])
    for case in data["cases"]:
        assert case["profile"] in defined, f"{case['id']}: 미정의 프로필 {case['profile']}"


@pytest.mark.parametrize("name", ALL)
def test_라벨이_유효한_판정값이다(name: str) -> None:
    for case in load(name)["cases"]:
        Applicability(case["gold_applicability"])  # 유효하지 않으면 ValueError


@pytest.mark.parametrize("name", ALL)
def test_케이스_id가_중복되지_않는다(name: str) -> None:
    ids = [c["id"] for c in load(name)["cases"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"{name}: 중복 id {dupes}"


@pytest.mark.parametrize("name", ALL)
def test_모든_케이스에_라벨_근거가_적혀있다(name: str) -> None:
    """근거 없는 라벨은 나중에 결과를 보고 바꾸고 싶어진다."""
    for case in load(name)["cases"]:
        assert case.get("note", "").strip(), f"{case['id']}: note(라벨 근거)가 비어 있습니다"


@pytest.mark.parametrize("name", HOLDOUTS)
def test_홀드아웃_운용_규칙이_데이터셋에_박혀있다(name: str) -> None:
    rules = " ".join(load(name)["rules"])
    assert "프롬프트를 수정하지 않는다" in rules
    assert "라벨을 바꾸지 않는다" in rules


@pytest.mark.parametrize("name", HOLDOUTS)
def test_홀드아웃이_세_판정을_모두_포함한다(name: str) -> None:
    """한 판정이 빠지면 그 축의 지표가 통째로 의미를 잃는다."""
    golds = [c["gold_applicability"] for c in load(name)["cases"]]
    for label in ("APPLICABLE", "NOT_APPLICABLE", "HOLD"):
        assert label in golds, f"{name}에 {label} 케이스가 없습니다"
