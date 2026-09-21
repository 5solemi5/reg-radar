"""API 에러 계약 (03 요구사항 §7 ER-001~008).

원칙: 실패를 성공으로 위장하지 않는다 (NFR-005). 부분 실패도 명시한다.
모든 에러는 동일한 봉투로 나가므로 프론트가 한 가지 형태만 다루면 된다.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(..., description="기계 판독용 에러 코드")
    message: str = Field(..., description="사용자에게 보여줄 수 있는 설명")
    detail: str | None = Field(None, description="디버깅용 추가 정보")


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """서비스 계층이 던지는 에러. 라우터가 아니라 핸들러가 응답으로 변환한다."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "요청을 처리하지 못했습니다."

    def __init__(self, message: str | None = None, *, detail: str | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.detail = detail

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=ErrorResponse(
                error=ErrorBody(code=self.code, message=self.message, detail=self.detail)
            ).model_dump(),
        )


class UnauthorizedError(ApiError):
    """ER-007. 인증 만료/누락."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"
    message = "인증이 필요합니다. 다시 로그인해 주세요."


class NotFoundError(ApiError):
    """남의 리소스도 여기로 떨어진다 — 존재 여부를 알려주지 않기 위해 (NFR-007)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "요청한 리소스를 찾을 수 없습니다."


class ProfileRequiredError(ApiError):
    """ER-006. 분석에는 프로필이 필요하다."""

    status_code = status.HTTP_409_CONFLICT
    code = "profile_required"
    message = "분석을 실행하려면 먼저 업무 프로필을 입력해야 합니다."


class AnalysisInProgressError(ApiError):
    """FR-003. 중복 클릭으로 같은 분석이 무제한 실행되지 않게 한다."""

    status_code = status.HTTP_409_CONFLICT
    code = "analysis_in_progress"
    message = "이미 진행 중인 분석이 있습니다. 완료 후 다시 실행해 주세요."

    def __init__(self, analysis_id: str):
        super().__init__(detail=f"analysis_id={analysis_id}")
        self.analysis_id = analysis_id


class ReassessNotAllowedError(ApiError):
    """FR-008. 보류가 아니거나 근거가 없어 재판정할 수 없다."""

    status_code = status.HTTP_409_CONFLICT
    code = "reassess_not_allowed"
    message = "이 결과는 재판정할 수 없습니다."


class UpstreamUnavailableError(ApiError):
    """ER-001/ER-002. 법제처·LLM 등 외부 의존성 실패."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "upstream_unavailable"
    message = "외부 데이터 조회에 실패했습니다. 잠시 후 다시 시도해 주세요."


class ValidationRejectedError(ApiError):
    """ER-004. Validator가 막은 결과를 정상 결과로 내보내지 않는다."""

    status_code = 422  # Unprocessable Content
    code = "validation_rejected"
    message = "검증을 통과하지 못해 결과를 제공할 수 없습니다."


async def api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return exc.to_response()


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # 내부 예외 메시지를 그대로 노출하지 않는다.
    return ApiError(detail=type(exc).__name__).to_response()
