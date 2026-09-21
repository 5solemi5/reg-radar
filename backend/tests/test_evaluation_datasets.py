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


def load(name: str) -> dict:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def holdout() -> dict:
    return load("holdout_v1.json")


def test_홀드아웃_법령이_개발셋과_겹치지_않는다(holdout: dict) -> None:
    dev = {c["law_name"] for c in load("applicability_v1.json")["cases"]}
    hold = {c["law_name"] for c in holdout["cases"]}
    overlap = dev & hold
    assert not overlap, (
        f"홀드아웃에 개발셋 법령이 섞였습니다: {sorted(overlap)}. "
        "겹치는 순간 홀드아웃이 재는 것은 일반화가 아니라 암기입니다."
    )


@pytest.mark.parametrize("name", ["applicability_v1.json", "holdout_v1.json"])
def test_모든_케이스가_정의된_프로필을_참조한다(name: str) -> None:
    data = load(name)
    defined = set(data["profiles"])
    for case in data["cases"]:
        assert case["profile"] in defined, f"{case['id']}: 미정의 프로필 {case['profile']}"


@pytest.mark.parametrize("name", ["applicability_v1.json", "holdout_v1.json"])
def test_라벨이_유효한_판정값이다(name: str) -> None:
    for case in load(name)["cases"]:
        Applicability(case["gold_applicability"])  # 유효하지 않으면 ValueError


@pytest.mark.parametrize("name", ["applicability_v1.json", "holdout_v1.json"])
def test_케이스_id가_중복되지_않는다(name: str) -> None:
    ids = [c["id"] for c in load(name)["cases"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"{name}: 중복 id {dupes}"


@pytest.mark.parametrize("name", ["applicability_v1.json", "holdout_v1.json"])
def test_모든_케이스에_라벨_근거가_적혀있다(name: str) -> None:
    """근거 없는 라벨은 나중에 결과를 보고 바꾸고 싶어진다."""
    for case in load(name)["cases"]:
        assert case.get("note", "").strip(), f"{case['id']}: note(라벨 근거)가 비어 있습니다"


def test_홀드아웃_운용_규칙이_데이터셋에_박혀있다(holdout: dict) -> None:
    rules = " ".join(holdout["rules"])
    assert "프롬프트를 수정하지 않는다" in rules
    assert "라벨을 바꾸지 않는다" in rules


def test_홀드아웃이_보류_케이스를_포함한다(holdout: dict) -> None:
    """보류만 재지 않는 셋이면 과도한 보류율이 의미를 잃는다."""
    golds = [c["gold_applicability"] for c in holdout["cases"]]
    for label in ("APPLICABLE", "NOT_APPLICABLE", "HOLD"):
        assert label in golds, f"홀드아웃에 {label} 케이스가 없습니다"
