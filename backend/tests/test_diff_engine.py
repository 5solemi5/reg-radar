"""Diff Engine 단위 테스트 (UC-05 / FR-005 / Q5)."""

import pytest

from app.diff.engine import compute_change, detect_delegation, inline_diff, split_units
from app.domain.enums import ChangeType

BEFORE = (
    "① 사업주는 상시 30명 이상의 근로자를 사용하는 사업장의 경우 고충처리위원을 두어야 한다. "
    "② 고충처리위원의 수는 3명 이내로 한다."
)
AFTER = (
    "① 사업주는 상시 10명 이상의 근로자를 사용하는 사업장의 경우 고충처리위원을 두어야 한다. "
    "② 고충처리위원의 수는 3명 이내로 한다. "
    "③ 고충처리 절차에 관하여 필요한 사항은 대통령령으로 정한다."
)


class TestChangeType:
    def test_신설(self):
        c = compute_change(None, AFTER)
        assert c.change_type is ChangeType.NEW
        assert c.deletions == []
        assert c.additions

    def test_삭제(self):
        c = compute_change(BEFORE, None)
        assert c.change_type is ChangeType.DELETED
        assert c.additions == []

    def test_개정(self):
        c = compute_change(BEFORE, AFTER)
        assert c.change_type is ChangeType.AMENDED

    def test_변경없음(self):
        assert compute_change(BEFORE, BEFORE).change_type is ChangeType.UNCHANGED

    def test_공백만_다르면_변경없음(self):
        assert compute_change(BEFORE, BEFORE.replace(" ", "  ")).change_type is ChangeType.UNCHANGED

    def test_양쪽_없음(self):
        assert compute_change(None, None).change_type is ChangeType.UNCHANGED


class TestDiffContent:
    def test_규모기준_변경이_추가삭제로_잡힌다(self):
        """기획서 §2의 '규모 조건 놓침' 오탐을 막는 핵심 신호."""
        c = compute_change(BEFORE, AFTER)
        assert any("30명" in d for d in c.deletions)
        assert any("10명" in a for a in c.additions)

    def test_신설된_항이_추가로_잡힌다(self):
        c = compute_change(BEFORE, AFTER)
        assert any("대통령령으로 정한다" in a for a in c.additions)

    def test_변하지_않은_항은_diff에_없다(self):
        c = compute_change(BEFORE, AFTER)
        unchanged = "② 고충처리위원의 수는 3명 이내로 한다."
        assert not any(unchanged in x for x in c.additions + c.deletions)

    def test_unified_diff_생성(self):
        out = inline_diff(BEFORE, AFTER)
        assert "개정 전" in out and "개정 후" in out
        assert any(line.startswith("+") for line in out.splitlines())


class TestDelegationDetection:
    """Q5. 시행령 위임 감지 — 문자열 규칙이므로 누락 0건이어야 한다."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("필요한 사항은 대통령령으로 정한다.", "대통령령"),
            ("대통령령이 정하는 기준에 따라", "대통령령"),
            ("고용노동부령으로 정하는 서식", "부령"),
            ("총리령으로 정한다.", "총리령"),
            ("시행규칙으로 정하는 바에 따라", "시행규칙"),
            ("고용노동부장관이 고시하는 금액", None),  # '고시' 단독 명사는 위임이 아님
            ("장관이 정하여 고시하는 바에 따라 정한다.", None),
            ("조례로 정하는 사항", "조례"),
        ],
    )
    def test_패턴(self, text, expected):
        found = detect_delegation(text)
        if expected is None:
            assert expected not in found
        else:
            assert expected in found

    def test_위임없는_조문(self):
        assert detect_delegation("사업주는 안전보건교육을 실시하여야 한다.") == []

    def test_change_context가_위임을_노출한다(self):
        c = compute_change(BEFORE, AFTER)
        assert c.has_delegation
        assert "대통령령" in c.delegation_targets

    def test_위임은_개정후_기준(self):
        c = compute_change(AFTER, BEFORE)  # 위임 조항이 삭제된 개정
        assert not c.has_delegation


class TestSplitUnits:
    def test_항번호로_분할(self):
        units = split_units(AFTER)
        assert len(units) == 3
        assert units[0].startswith("①")

    def test_빈문자열(self):
        assert split_units("") == []
