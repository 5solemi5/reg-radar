"""문서와 구현이 어긋나지 않는지 검증한다.

문서는 시간이 지나면 조용히 낡는다. 이 테스트는 그 부패를 실패로 드러내,
API를 고치면 05. API 명세서도 반드시 함께 고치게 만든다.
"""

import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.main import create_app

SPEC = (
    Path(__file__).parent.parent.parent
    / "docs" / "규제변화_AI도우미_MD_문서" / "05_API_명세서.md"
)

_PATH_PARAM = re.compile(r"\{[a-z_]+\}")
_DOC_ENDPOINT = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`\s]+)`")


def _normalize(endpoint: str) -> str:
    """경로 파라미터 이름 차이를 흡수한다. /results/{id} == /results/{result_id}"""
    return _PATH_PARAM.sub("{id}", endpoint)


@pytest.fixture(scope="module")
def implemented() -> set[str]:
    app = create_app(Settings(app_env="local", auth_mode="dev", storage="memory"))
    return {
        _normalize(f"{method.upper()} {path}")
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if path.startswith("/api")
    }


@pytest.fixture(scope="module")
def documented() -> set[str]:
    if not SPEC.exists():
        pytest.skip(f"명세서를 찾을 수 없습니다: {SPEC}")
    text = SPEC.read_text(encoding="utf-8")
    return {
        _normalize(f"{m.group(1)} /api/v1{m.group(2)}")
        for m in _DOC_ENDPOINT.finditer(text)
    }


class TestApiSpecSync:
    def test_구현된_엔드포인트가_모두_문서화되어_있다(self, implemented, documented):
        undocumented = implemented - documented
        assert not undocumented, (
            f"05. API 명세서에 없는 엔드포인트: {sorted(undocumented)}\n"
            "API를 추가했다면 명세서에도 적어야 합니다."
        )

    def test_문서에_적힌_엔드포인트가_모두_구현되어_있다(self, implemented, documented):
        missing = documented - implemented
        assert not missing, (
            f"문서에는 있으나 구현에 없는 엔드포인트: {sorted(missing)}\n"
            "제거했다면 명세서에서도 빼야 합니다."
        )


class TestSpecContent:
    """명세서가 약속한 불변식이 실제 스키마와 일치하는지."""

    def test_AI해석_블록에_공식_사실_필드가_없다(self):
        """명세서 §1-1의 약속."""
        from app.api.schemas import AiInterpretationOut

        forbidden = {"law_name", "article_no", "effective_date", "ministry", "source_url"}
        assert not (forbidden & set(AiInterpretationOut.model_fields))

    def test_근거가_세_블록으로_분리되어_있다(self):
        """명세서 §1-1, AP-05."""
        from app.api.schemas import EvidenceOut

        assert {"legal_evidence", "reference_evidence", "ai_interpretation"} <= set(
            EvidenceOut.model_fields
        )

    def test_법률자문_아님_고지가_기본값에_있다(self):
        """명세서 §4-4, NFR-015."""
        from app.api.schemas import EvidenceOut

        assert "법률 자문이 아니" in EvidenceOut.model_fields["disclaimer"].default

    def test_문서에_기재된_에러코드가_실제로_존재한다(self):
        """명세서 §3 에러 표."""
        from app.api import errors

        documented_codes = {
            "unauthorized", "not_found", "profile_required",
            "analysis_in_progress", "validation_rejected",
            "upstream_unavailable", "internal_error",
        }
        actual = {
            cls.code
            for cls in vars(errors).values()
            if isinstance(cls, type) and issubclass(cls, errors.ApiError)
        }
        assert documented_codes <= actual, f"문서에만 있는 코드: {documented_codes - actual}"

    def test_production에서_dev인증은_기동을_거부한다(self):
        """명세서 §2의 약속."""
        with pytest.raises(RuntimeError, match="production"):
            create_app(Settings(app_env="production", auth_mode="dev", storage="memory"))
