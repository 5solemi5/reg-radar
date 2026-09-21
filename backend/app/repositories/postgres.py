"""Postgres 저장소 구현 (W4).

app/repositories/base.py의 Protocol을 만족한다. 인메모리 구현과 교체 가능해야
하므로 시그니처와 반환 형태가 정확히 같아야 한다.

NFR-007: 사용자 데이터 쿼리는 전부 WHERE user_id = $n을 포함한다. 남의 행은
'없는 것'으로 보이며 존재 여부도 알려주지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from app.adapters.law.models import LawArticle, LawSnapshot
from app.domain.entities import (
    Analysis,
    Feedback,
    HoldRevision,
    Profile,
    ResultCounts,
    SavedRegulation,
)
from app.domain.enums import (
    ActionGrade,
    AnalysisStatus,
    Applicability,
    ChangeType,
    CompanySize,
    ResultStatus,
)
from app.domain.outputs import ChecklistItem
from app.domain.result import (
    AiInterpretation,
    AnalysisResult,
    ChangeSummary,
    DelegatedEvidence,
    LegalEvidence,
    ReferenceEvidence,
    ValidationReport,
)
from app.repositories.db import Database


def _list(value: Any) -> list:
    """asyncpg는 text[]를 list로 준다. NULL 방어."""
    return list(value) if value else []


class PostgresProfileRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _to_domain(row: asyncpg.Record) -> Profile:
        return Profile(
            user_id=row["user_id"],
            job=row["job"],
            industry=row["industry"],
            company_size=CompanySize(row["company_size"]),
            employee_count=row["employee_count"],
            interests=_list(row["interests"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get(self, user_id: str) -> Profile | None:
        row = await self._db.fetchrow(
            "SELECT * FROM profiles WHERE user_id = $1", user_id
        )
        return self._to_domain(row) if row else None

    async def upsert(self, profile: Profile) -> Profile:
        # created_at은 최초 생성 시각을 유지한다. 프로필을 다시 저장한다고
        # 가입 시점이 바뀌면 안 된다.
        row = await self._db.fetchrow(
            """
            INSERT INTO profiles
                (user_id, job, industry, company_size, employee_count, interests)
            VALUES ($1, $2, $3, $4::company_size, $5, $6)
            ON CONFLICT (user_id) DO UPDATE SET
                job = EXCLUDED.job,
                industry = EXCLUDED.industry,
                company_size = EXCLUDED.company_size,
                employee_count = EXCLUDED.employee_count,
                interests = EXCLUDED.interests
            RETURNING *
            """,
            profile.user_id,
            profile.job,
            profile.industry,
            profile.company_size.value,
            profile.employee_count,
            profile.interests,
        )
        return self._to_domain(row)


class PostgresAnalysisRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _to_domain(row: asyncpg.Record) -> Analysis:
        counts = row["counts"] or {}
        return Analysis(
            analysis_id=str(row["analysis_id"]),
            user_id=row["user_id"],
            status=AnalysisStatus(row["status"]),
            period_from=row["period_from"],
            period_to=row["period_to"],
            law_query=row["law_query"],
            trace_id=str(row["trace_id"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            laws_examined=row["laws_examined"],
            articles_changed=row["articles_changed"],
            counts=ResultCounts(**counts) if counts else ResultCounts(),
            error=row["error"],
            snapshot_law_ids=_list(row["snapshot_law_ids"]),
            chain_calls=row["chain_calls"],
            total_tokens=row["total_tokens"],
        )

    async def create(self, analysis: Analysis) -> Analysis:
        row = await self._db.fetchrow(
            """
            INSERT INTO analyses
                (analysis_id, user_id, status, period_from, period_to, law_query,
                 trace_id, created_at)
            VALUES ($1::uuid, $2, $3::analysis_status, $4, $5, $6, $7::uuid, $8)
            RETURNING *
            """,
            analysis.analysis_id,
            analysis.user_id,
            analysis.status.value,
            analysis.period_from,
            analysis.period_to,
            analysis.law_query,
            analysis.trace_id,
            # DEFAULT now()에 맡기지 않는다. 도메인 객체가 들고 온 값을 무시하면
            # 같은 객체를 저장했는데 구현에 따라 다른 값이 나온다. 계약 테스트가
            # 실제로 그 차이를 잡았다.
            analysis.created_at,
        )
        return self._to_domain(row)

    async def get(self, analysis_id: str, user_id: str) -> Analysis | None:
        try:
            row = await self._db.fetchrow(
                "SELECT * FROM analyses WHERE analysis_id = $1::uuid AND user_id = $2",
                analysis_id,
                user_id,
            )
        except (asyncpg.DataError, ValueError):
            # uuid 형식이 아닌 id → 존재하지 않는 것으로 취급한다.
            return None
        return self._to_domain(row) if row else None

    async def update(self, analysis: Analysis) -> Analysis:
        row = await self._db.fetchrow(
            """
            UPDATE analyses SET
                status = $3::analysis_status,
                started_at = $4,
                completed_at = $5,
                laws_examined = $6,
                articles_changed = $7,
                counts = $8::jsonb,
                error = $9,
                snapshot_law_ids = $10,
                chain_calls = $11,
                total_tokens = $12
            WHERE analysis_id = $1::uuid AND user_id = $2
            RETURNING *
            """,
            analysis.analysis_id,
            analysis.user_id,
            analysis.status.value,
            analysis.started_at,
            analysis.completed_at,
            analysis.laws_examined,
            analysis.articles_changed,
            analysis.counts.model_dump(),
            analysis.error,
            analysis.snapshot_law_ids,
            analysis.chain_calls,
            analysis.total_tokens,
        )
        if row is None:
            raise LookupError(f"분석을 찾을 수 없습니다: {analysis.analysis_id}")
        return self._to_domain(row)

    async def list_for_user(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[Analysis], int]:
        rows = await self._db.fetch(
            """
            SELECT *, count(*) OVER () AS total_count
            FROM analyses
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id,
            limit,
            offset,
        )
        if not rows:
            total = await self._db.fetchval(
                "SELECT count(*) FROM analyses WHERE user_id = $1", user_id
            )
            return [], int(total or 0)
        return [self._to_domain(r) for r in rows], int(rows[0]["total_count"])

    async def count_since(self, since: datetime, *, user_id: str | None = None) -> int:
        """일일 상한 계산용. 실패한 분석도 센다 (실패 유도로 한도를 우회하지 못하게)."""
        if user_id is None:
            return await self._db.fetchval(
                "SELECT count(*) FROM analyses WHERE created_at >= $1", since
            )
        return await self._db.fetchval(
            "SELECT count(*) FROM analyses WHERE created_at >= $1 AND user_id = $2",
            since,
            user_id,
        )

    async def find_active(self, user_id: str) -> Analysis | None:
        row = await self._db.fetchrow(
            """
            SELECT * FROM analyses
            WHERE user_id = $1 AND status IN ('CREATED', 'RUNNING')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id,
        )
        return self._to_domain(row) if row else None


class PostgresResultRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _to_domain(row: asyncpg.Record) -> AnalysisResult:
        return AnalysisResult(
            result_id=str(row["result_id"]),
            analysis_id=str(row["analysis_id"]),
            status=ResultStatus(row["status"]),
            applicability=Applicability(row["applicability"]),
            action_grade=ActionGrade(row["action_grade"]) if row["action_grade"] else None,
            change=ChangeSummary(
                change_type=ChangeType(row["change_type"]),
                additions=_list(row["additions"]),
                deletions=_list(row["deletions"]),
                delegation_targets=_list(row["delegation_targets"]),
            ),
            legal_evidence=LegalEvidence(
                law_id=row["law_id"],
                law_name=row["law_name"],
                article_no=row["article_no"],
                article_title=row["article_title"],
                effective_date=row["effective_date"],
                ministry=row["ministry"],
                source_url=row["source_url"],
                quoted_spans=_list(row["quoted_spans"]),
            ),
            delegated_evidence=[
                DelegatedEvidence(**doc) for doc in (row["delegated_evidence"] or [])
            ],
            reference_evidence=[
                ReferenceEvidence(**doc) for doc in (row["reference_evidence"] or [])
            ],
            ai_interpretation=AiInterpretation(
                reason=row["ai_reason"],
                matched_conditions=_list(row["ai_matched_conditions"]),
                missing_context=_list(row["ai_missing_context"]),
                impact_summary=row["ai_impact_summary"],
                affected_work=_list(row["ai_affected_work"]),
                checklist=[ChecklistItem(**item) for item in (row["ai_checklist"] or [])],
                confidence=row["ai_confidence"],
                model=row["ai_model"],
            ),
            validation=ValidationReport(**(row["validation"] or {"passed": False})),
            trace_id=str(row["trace_id"]) if row["trace_id"] else None,
            created_at=row["created_at"],
        )

    @staticmethod
    def _to_params(result: AnalysisResult, user_id: str) -> tuple:
        legal = result.legal_evidence
        ai = result.ai_interpretation
        return (
            result.result_id,
            result.analysis_id,
            user_id,
            result.status.value,
            result.applicability.value,
            result.action_grade.value if result.action_grade else None,
            legal.law_id,
            legal.law_name,
            legal.article_no,
            legal.article_title,
            legal.effective_date,
            legal.ministry,
            legal.source_url,
            legal.quoted_spans,
            result.change.change_type.value,
            result.change.additions,
            result.change.deletions,
            result.change.delegation_targets,
            ai.reason,
            ai.matched_conditions,
            ai.missing_context,
            ai.impact_summary,
            ai.affected_work,
            [c.model_dump() for c in ai.checklist],
            ai.confidence,
            ai.model,
            [d.model_dump(mode="json", exclude={"kind"}) for d in result.delegated_evidence],
            [r.model_dump(mode="json", exclude={"kind"}) for r in result.reference_evidence],
            result.validation.model_dump(),
            result.trace_id,
            result.created_at,
        )

    _INSERT = """
        INSERT INTO analysis_results (
            result_id, analysis_id, user_id, status, applicability, action_grade,
            law_id, law_name, article_no, article_title, effective_date, ministry,
            source_url, quoted_spans,
            change_type, additions, deletions, delegation_targets,
            ai_reason, ai_matched_conditions, ai_missing_context, ai_impact_summary,
            ai_affected_work, ai_checklist, ai_confidence, ai_model,
            delegated_evidence, reference_evidence, validation, trace_id, created_at
        ) VALUES (
            $1::uuid, $2::uuid, $3, $4::result_status, $5::applicability, $6::action_grade,
            $7, $8, $9, $10, $11, $12,
            $13, $14,
            $15::change_type, $16, $17, $18,
            $19, $20, $21, $22,
            $23, $24::jsonb, $25, $26,
            $27::jsonb, $28::jsonb, $29::jsonb, $30::uuid, $31
        )
        ON CONFLICT (result_id) DO NOTHING
    """

    async def save_many(self, results: list[AnalysisResult]) -> None:
        if not results:
            return
        # 소유자는 분석에서 가져온다. 결과가 스스로 주장하게 두지 않는다.
        owners: dict[str, str] = {}
        for result in results:
            if result.analysis_id and result.analysis_id not in owners:
                owner = await self._db.fetchval(
                    "SELECT user_id FROM analyses WHERE analysis_id = $1::uuid",
                    result.analysis_id,
                )
                if owner is None:
                    raise LookupError(f"분석을 찾을 수 없습니다: {result.analysis_id}")
                owners[result.analysis_id] = owner

        await self._db.executemany(
            self._INSERT,
            [self._to_params(r, owners[r.analysis_id]) for r in results if r.analysis_id],
        )

    async def get(self, result_id: str, user_id: str) -> AnalysisResult | None:
        try:
            row = await self._db.fetchrow(
                "SELECT * FROM analysis_results WHERE result_id = $1::uuid AND user_id = $2",
                result_id,
                user_id,
            )
        except (asyncpg.DataError, ValueError):
            return None
        return self._to_domain(row) if row else None

    async def list_for_analysis(
        self, analysis_id: str, user_id: str
    ) -> list[AnalysisResult]:
        try:
            rows = await self._db.fetch(
                """
                SELECT * FROM analysis_results
                WHERE analysis_id = $1::uuid AND user_id = $2
                ORDER BY created_at
                """,
                analysis_id,
                user_id,
            )
        except (asyncpg.DataError, ValueError):
            return []
        return [self._to_domain(r) for r in rows]


class PostgresSnapshotRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(self, snapshot: LawSnapshot) -> None:
        await self._db.execute(
            """
            INSERT INTO law_snapshots (
                law_id, mst, law_name, law_type, ministry,
                promulgation_date, effective_date, revision_type, source_url,
                articles, source, fetched_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12)
            ON CONFLICT (law_id, mst) DO UPDATE SET
                articles = EXCLUDED.articles,
                fetched_at = EXCLUDED.fetched_at
            """,
            snapshot.law_id,
            snapshot.mst,
            snapshot.law_name,
            snapshot.law_type,
            snapshot.ministry,
            snapshot.promulgation_date,
            snapshot.effective_date,
            snapshot.revision_type,
            snapshot.source_url,
            [a.model_dump(mode="json") for a in snapshot.articles],
            snapshot.source,
            snapshot.fetched_at,
        )

    async def get(self, law_id: str) -> LawSnapshot | None:
        row = await self._db.fetchrow(
            """
            SELECT * FROM law_snapshots
            WHERE law_id = $1
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            law_id,
        )
        if row is None:
            return None
        return LawSnapshot(
            law_id=row["law_id"],
            mst=row["mst"],
            law_name=row["law_name"],
            law_type=row["law_type"],
            ministry=row["ministry"],
            promulgation_date=row["promulgation_date"],
            effective_date=row["effective_date"],
            revision_type=row["revision_type"],
            source_url=row["source_url"],
            articles=[LawArticle(**a) for a in (row["articles"] or [])],
            fetched_at=row["fetched_at"],
            # ER-001: 저장소에서 꺼낸 것은 캐시임을 UI가 알 수 있어야 한다.
            source="cache",
        )


class PostgresFeedbackRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, feedback: Feedback) -> Feedback:
        row = await self._db.fetchrow(
            """
            INSERT INTO feedback
                (feedback_id, result_id, user_id, helpful, correction_type, comment)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            RETURNING *
            """,
            feedback.feedback_id,
            feedback.result_id,
            feedback.user_id,
            feedback.helpful,
            feedback.correction_type,
            feedback.comment,
        )
        return Feedback(
            feedback_id=str(row["feedback_id"]),
            result_id=str(row["result_id"]),
            user_id=row["user_id"],
            helpful=row["helpful"],
            correction_type=row["correction_type"],
            comment=row["comment"],
            created_at=row["created_at"],
        )

    async def list_for_result(self, result_id: str, user_id: str) -> list[Feedback]:
        rows = await self._db.fetch(
            "SELECT * FROM feedback WHERE result_id = $1::uuid AND user_id = $2",
            result_id,
            user_id,
        )
        return [
            Feedback(
                feedback_id=str(r["feedback_id"]),
                result_id=str(r["result_id"]),
                user_id=r["user_id"],
                helpful=r["helpful"],
                correction_type=r["correction_type"],
                comment=r["comment"],
                created_at=r["created_at"],
            )
            for r in rows
        ]


class PostgresSavedRegulationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _to_domain(row: asyncpg.Record) -> SavedRegulation:
        return SavedRegulation(
            saved_id=str(row["saved_id"]),
            user_id=row["user_id"],
            result_id=str(row["result_id"]),
            law_id=row["law_id"],
            law_name=row["law_name"],
            article_no=row["article_no"],
            note=row["note"],
            created_at=row["created_at"],
        )

    async def create(self, saved: SavedRegulation) -> SavedRegulation:
        row = await self._db.fetchrow(
            """
            INSERT INTO saved_regulations
                (saved_id, user_id, result_id, law_id, law_name, article_no, note)
            VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6, $7)
            ON CONFLICT (user_id, result_id) DO UPDATE SET note = EXCLUDED.note
            RETURNING *
            """,
            saved.saved_id,
            saved.user_id,
            saved.result_id,
            saved.law_id,
            saved.law_name,
            saved.article_no,
            saved.note,
        )
        return self._to_domain(row)

    async def list_for_user(self, user_id: str) -> list[SavedRegulation]:
        rows = await self._db.fetch(
            "SELECT * FROM saved_regulations WHERE user_id = $1 ORDER BY created_at DESC",
            user_id,
        )
        return [self._to_domain(r) for r in rows]

    async def delete(self, saved_id: str, user_id: str) -> bool:
        try:
            status = await self._db.execute(
                "DELETE FROM saved_regulations WHERE saved_id = $1::uuid AND user_id = $2",
                saved_id,
                user_id,
            )
        except (asyncpg.DataError, ValueError):
            return False
        return status.endswith(" 1")


class PostgresRevisionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _to_domain(row: asyncpg.Record) -> HoldRevision:
        return HoldRevision(
            revision_id=str(row["revision_id"]),
            original_result_id=str(row["original_result_id"]),
            new_result_id=str(row["new_result_id"]),
            user_id=row["user_id"],
            added_context=row["added_context"] or {},
            previous_applicability=Applicability(row["previous_applicability"]),
            new_applicability=Applicability(row["new_applicability"]),
            created_at=row["created_at"],
        )

    async def create(self, revision: HoldRevision) -> HoldRevision:
        row = await self._db.fetchrow(
            """
            INSERT INTO hold_revisions (
                revision_id, original_result_id, new_result_id, user_id,
                added_context, previous_applicability, new_applicability
            ) VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::jsonb,
                      $6::applicability, $7::applicability)
            RETURNING *
            """,
            revision.revision_id,
            revision.original_result_id,
            revision.new_result_id,
            revision.user_id,
            revision.added_context,
            revision.previous_applicability.value,
            revision.new_applicability.value,
        )
        return self._to_domain(row)

    async def list_for_result(self, result_id: str, user_id: str) -> list[HoldRevision]:
        rows = await self._db.fetch(
            """
            SELECT * FROM hold_revisions
            WHERE user_id = $2
              AND (original_result_id = $1::uuid OR new_result_id = $1::uuid)
            ORDER BY created_at
            """,
            result_id,
            user_id,
        )
        return [self._to_domain(r) for r in rows]


__all__ = [
    "PostgresAnalysisRepository",
    "PostgresFeedbackRepository",
    "PostgresProfileRepository",
    "PostgresResultRepository",
    "PostgresRevisionRepository",
    "PostgresSavedRegulationRepository",
    "PostgresSnapshotRepository",
]
