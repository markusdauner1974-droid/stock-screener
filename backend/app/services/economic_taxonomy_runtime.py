"""Ordered compatibility projections and fenced legacy write integration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.models.economic_taxonomy_runtime import (
    ProjectionCheckpoint,
    ServingGenerationEvent,
    TaxonomyAuthority,
    TaxonomyProjectionDeliveryAttempt,
    TaxonomyProjectionDeliveryEvent,
    TaxonomyProjectionEvent,
    TaxonomySourceRevisionLog,
)
from app.services.economic_taxonomy_fence import producer_write


class ProjectionRuntimeError(ValueError):
    pass


class ProjectionPayloadConflict(ProjectionRuntimeError):
    pass


class ProjectionRevisionError(ProjectionRuntimeError):
    pass


class DeliveryLeaseError(ProjectionRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectionDeliveryClaim:
    projection_event_id: UUID
    delivery_attempt_id: UUID
    lease_token: UUID
    claimed_epoch: int
    lease_expires_at: datetime
    target: str
    source_lineage: str
    projection_kind: str
    projection_revision: int
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProjectionDeliveryResult:
    projection_event_id: UUID
    delivery_attempt_id: UUID
    outcome: str
    applied: bool


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _LegacyWrite:
    def __init__(
        self,
        service: EconomicTaxonomyRuntimeService,
        authority: TaxonomyAuthority,
        origin_representation: str,
    ):
        self._service = service
        self.authority = authority
        self.origin_representation = origin_representation

    def stage_compatibility_projection(
        self,
        *,
        source_lineage: str,
        projection_revision: int,
        projection_kind: str,
        projection_version: int,
        target: str,
        payload: Mapping[str, Any],
        origin_representation: str | None = None,
    ) -> TaxonomyProjectionEvent | None:
        origin = origin_representation or self.origin_representation
        if self.authority.mode == "legacy" or origin == target:
            return None
        return self._service.stage_projection(
            generation_id=self.authority.serving_generation_id,
            source_lineage=source_lineage,
            projection_revision=projection_revision,
            projection_kind=projection_kind,
            projection_version=projection_version,
            target=target,
            payload=payload,
            staged_epoch=self.authority.authority_epoch,
            origin_representation=origin,
            selected_interpretation_version="legacy-source",
            mapping_version="legacy-source",
            delivery_scope=("candidate" if self.authority.mode == "dual" else "shadow"),
        )

    def stage_next_compatibility_projection(
        self,
        *,
        source_lineage: str,
        projection_kind: str,
        projection_version: int,
        target: str,
        payload: Mapping[str, Any],
        origin_representation: str | None = None,
    ) -> TaxonomyProjectionEvent | None:
        origin = origin_representation or self.origin_representation
        if self.authority.mode == "legacy" or origin == target:
            return None
        latest = self._service.session.scalar(
            select(func.max(TaxonomyProjectionEvent.projection_revision)).where(
                TaxonomyProjectionEvent.source_lineage == source_lineage,
                TaxonomyProjectionEvent.projection_kind == projection_kind,
                TaxonomyProjectionEvent.target_representation == target,
            )
        )
        return self.stage_compatibility_projection(
            source_lineage=source_lineage,
            projection_revision=int(latest or 0) + 1,
            projection_kind=projection_kind,
            projection_version=projection_version,
            target=target,
            payload=payload,
            origin_representation=origin,
        )


class EconomicTaxonomyRuntimeService:
    def __init__(self, session: Session):
        self.session = session

    def stage_projection(
        self,
        *,
        generation_id: UUID | None,
        source_lineage: str,
        projection_revision: int,
        projection_kind: str,
        projection_version: int,
        target: str,
        payload: Mapping[str, Any],
        staged_epoch: int,
        origin_representation: str,
        selected_interpretation_version: str,
        mapping_version: str,
        delivery_scope: str = "candidate",
    ) -> TaxonomyProjectionEvent:
        for name, value in (
            ("source_lineage", source_lineage),
            ("projection_kind", projection_kind),
            ("target", target),
            ("origin_representation", origin_representation),
            ("selected_interpretation_version", selected_interpretation_version),
            ("mapping_version", mapping_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ProjectionRuntimeError(f"{name}_required")
        if projection_revision <= 0 or projection_version <= 0:
            raise ProjectionRevisionError("projection_revision_must_be_positive")
        if delivery_scope not in {"shadow", "candidate"}:
            raise ProjectionRuntimeError("invalid_delivery_scope")

        normalized_payload = {
            **dict(payload),
            "origin_representation": origin_representation,
            "selected_interpretation_version": selected_interpretation_version,
            "mapping_version": mapping_version,
        }
        digest = _payload_hash(normalized_payload)
        existing = self.session.scalar(
            select(TaxonomyProjectionEvent).where(
                TaxonomyProjectionEvent.source_lineage == source_lineage,
                TaxonomyProjectionEvent.projection_revision == projection_revision,
                TaxonomyProjectionEvent.projection_kind == projection_kind,
                TaxonomyProjectionEvent.projection_version == projection_version,
                TaxonomyProjectionEvent.target_representation == target,
            )
        )
        if existing is not None:
            if (
                existing.payload_hash != digest
                or existing.serving_generation_id != generation_id
                or existing.delivery_scope != delivery_scope
            ):
                raise ProjectionPayloadConflict("projection_payload_conflict")
            return existing

        latest = self.session.scalar(
            select(func.max(TaxonomyProjectionEvent.projection_revision)).where(
                TaxonomyProjectionEvent.source_lineage == source_lineage,
                TaxonomyProjectionEvent.projection_kind == projection_kind,
                TaxonomyProjectionEvent.target_representation == target,
            )
        )
        if latest is not None and projection_revision <= int(latest):
            raise ProjectionRevisionError("projection_revision_not_monotonic")
        event = TaxonomyProjectionEvent(
            serving_generation_id=generation_id,
            source_lineage=source_lineage,
            projection_revision=projection_revision,
            projection_kind=projection_kind,
            projection_version=projection_version,
            target_representation=target,
            payload=normalized_payload,
            payload_hash=digest,
            origin_representation=origin_representation,
            delivery_scope=delivery_scope,
            staged_epoch=staged_epoch,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def stage_projection_fanout(
        self,
        *,
        generation_id: UUID,
        affected_lineages: Sequence[str],
        projection_kind: str,
        projection_version: int,
        target: str,
        payload_by_lineage: Mapping[str, Mapping[str, Any]],
        staged_epoch: int,
        origin_representation: str,
        selected_interpretation_version: str,
        mapping_version: str,
    ) -> list[TaxonomyProjectionEvent]:
        events = []
        for lineage in sorted(set(affected_lineages)):
            latest = self.session.scalar(
                select(func.max(TaxonomyProjectionEvent.projection_revision)).where(
                    TaxonomyProjectionEvent.source_lineage == lineage,
                    TaxonomyProjectionEvent.projection_kind == projection_kind,
                    TaxonomyProjectionEvent.target_representation == target,
                )
            )
            events.append(
                self.stage_projection(
                    generation_id=generation_id,
                    source_lineage=lineage,
                    projection_revision=int(latest or 0) + 1,
                    projection_kind=projection_kind,
                    projection_version=projection_version,
                    target=target,
                    payload=payload_by_lineage.get(lineage, {}),
                    staged_epoch=staged_epoch,
                    origin_representation=origin_representation,
                    selected_interpretation_version=selected_interpretation_version,
                    mapping_version=mapping_version,
                )
            )
        return events

    def claim_deliveries_from_published_generations(
        self,
        *,
        worker_id: str,
        expected_epoch: int,
        now: datetime,
        limit: int = 100,
        lease_seconds: int = 300,
    ) -> list[ProjectionDeliveryClaim]:
        if not worker_id.strip():
            raise ProjectionRuntimeError("worker_id_required")
        now = _utc(now)
        claims: list[ProjectionDeliveryClaim] = []
        with producer_write(
            self.session,
            expected_epoch=expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ) as authority:
            published = select(ServingGenerationEvent.serving_generation_id).where(
                ServingGenerationEvent.event_type == "published"
            )
            query = (
                select(TaxonomyProjectionEvent)
                .where(
                    TaxonomyProjectionEvent.delivery_scope == "candidate",
                    TaxonomyProjectionEvent.serving_generation_id.in_(published),
                )
                .order_by(
                    TaxonomyProjectionEvent.created_at,
                    TaxonomyProjectionEvent.id,
                )
                .limit(limit)
            )
            if self.session.get_bind().dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            for event in self.session.scalars(query):
                attempts = self.session.scalars(
                    select(TaxonomyProjectionDeliveryAttempt)
                    .where(
                        TaxonomyProjectionDeliveryAttempt.projection_event_id
                        == event.id
                    )
                    .order_by(TaxonomyProjectionDeliveryAttempt.attempt_number.desc())
                ).all()
                if attempts:
                    latest = attempts[0]
                    outcome = self.session.scalar(
                        select(TaxonomyProjectionDeliveryEvent).where(
                            TaxonomyProjectionDeliveryEvent.delivery_attempt_id
                            == latest.id
                        )
                    )
                    if outcome is not None and outcome.outcome in {
                        "success",
                        "stale_noop",
                        "terminal_failure",
                    }:
                        continue
                    if outcome is None and _utc(latest.lease_expires_at) > now:
                        continue
                    attempt_number = latest.attempt_number + 1
                else:
                    attempt_number = 1
                lease_token = uuid4()
                attempt = TaxonomyProjectionDeliveryAttempt(
                    projection_event_id=event.id,
                    attempt_number=attempt_number,
                    claimed_epoch=authority.authority_epoch,
                    lease_token=lease_token,
                    lease_owner=worker_id,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                )
                self.session.add(attempt)
                self.session.flush()
                claims.append(
                    ProjectionDeliveryClaim(
                        projection_event_id=event.id,
                        delivery_attempt_id=attempt.id,
                        lease_token=lease_token,
                        claimed_epoch=authority.authority_epoch,
                        lease_expires_at=attempt.lease_expires_at,
                        target=event.target_representation,
                        source_lineage=event.source_lineage,
                        projection_kind=event.projection_kind,
                        projection_revision=event.projection_revision,
                        payload=dict(event.payload),
                    )
                )
        return claims

    def apply_delivery(
        self,
        claim: ProjectionDeliveryClaim,
        *,
        expected_epoch: int,
        now: datetime,
    ) -> ProjectionDeliveryResult:
        now = _utc(now)
        with producer_write(
            self.session,
            expected_epoch=expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ):
            attempt = self.session.execute(
                select(TaxonomyProjectionDeliveryAttempt)
                .where(
                    TaxonomyProjectionDeliveryAttempt.id == claim.delivery_attempt_id
                )
                .with_for_update()
            ).scalar_one_or_none()
            if attempt is None or attempt.lease_token != claim.lease_token:
                raise DeliveryLeaseError("delivery_lease_not_owned")
            existing_outcome = self.session.scalar(
                select(TaxonomyProjectionDeliveryEvent).where(
                    TaxonomyProjectionDeliveryEvent.delivery_attempt_id == attempt.id
                )
            )
            if existing_outcome is not None:
                return ProjectionDeliveryResult(
                    projection_event_id=claim.projection_event_id,
                    delivery_attempt_id=attempt.id,
                    outcome=existing_outcome.outcome,
                    applied=existing_outcome.outcome == "success",
                )
            if _utc(attempt.lease_expires_at) < now:
                raise DeliveryLeaseError("delivery_lease_expired")
            event = self.session.get(TaxonomyProjectionEvent, claim.projection_event_id)
            if event is None or event.id != attempt.projection_event_id:
                raise DeliveryLeaseError("delivery_event_mismatch")
            applied = self.apply_replacement(
                target=event.target_representation,
                source_lineage=event.source_lineage,
                projection_kind=event.projection_kind,
                projection_revision=event.projection_revision,
                payload=event.payload,
                origin_representation=event.origin_representation,
                projection_event_id=event.id,
            )
            outcome = "success" if applied else "stale_noop"
            self.session.add(
                TaxonomyProjectionDeliveryEvent(
                    delivery_attempt_id=attempt.id,
                    outcome=outcome,
                    details={"applied": applied, "completed_at": now.isoformat()},
                )
            )
            self.session.flush()
            return ProjectionDeliveryResult(
                projection_event_id=event.id,
                delivery_attempt_id=attempt.id,
                outcome=outcome,
                applied=applied,
            )

    def record_delivery_failure(
        self,
        claim: ProjectionDeliveryClaim,
        *,
        outcome: str,
        error: str,
    ) -> TaxonomyProjectionDeliveryEvent:
        if outcome not in {"retryable_failure", "terminal_failure"}:
            raise ProjectionRuntimeError("invalid_failure_outcome")
        attempt = self.session.get(
            TaxonomyProjectionDeliveryAttempt, claim.delivery_attempt_id
        )
        if attempt is None or attempt.lease_token != claim.lease_token:
            raise DeliveryLeaseError("delivery_lease_not_owned")
        existing = self.session.scalar(
            select(TaxonomyProjectionDeliveryEvent).where(
                TaxonomyProjectionDeliveryEvent.delivery_attempt_id == attempt.id
            )
        )
        if existing is not None:
            return existing
        event = TaxonomyProjectionDeliveryEvent(
            delivery_attempt_id=attempt.id,
            outcome=outcome,
            error=error,
            details={},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def apply_replacement(
        self,
        *,
        target: str,
        source_lineage: str,
        projection_kind: str,
        projection_revision: int,
        payload: Mapping[str, Any],
        origin_representation: str,
        projection_event_id: UUID | None = None,
    ) -> bool:
        values = {
            "target_representation": target,
            "source_lineage": source_lineage,
            "projection_kind": projection_kind,
            "last_applied_revision": projection_revision,
            "projection_event_id": projection_event_id,
            "origin_representation": origin_representation,
            "payload": dict(payload),
            "updated_at": datetime.now(timezone.utc),
        }
        table = ProjectionCheckpoint.__table__
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = postgresql_insert(table).values(**values)
        elif dialect == "sqlite":
            statement = sqlite_insert(table).values(**values)
        else:
            checkpoint = self.session.get(
                ProjectionCheckpoint, (target, source_lineage, projection_kind)
            )
            if (
                checkpoint is not None
                and checkpoint.last_applied_revision >= projection_revision
            ):
                return False
            if checkpoint is None:
                checkpoint = ProjectionCheckpoint(**values)
                self.session.add(checkpoint)
            else:
                for key, value in values.items():
                    setattr(checkpoint, key, value)
            self.session.flush()
            return True
        statement = statement.on_conflict_do_update(
            index_elements=[
                table.c.target_representation,
                table.c.source_lineage,
                table.c.projection_kind,
            ],
            set_={
                "last_applied_revision": statement.excluded.last_applied_revision,
                "projection_event_id": statement.excluded.projection_event_id,
                "origin_representation": statement.excluded.origin_representation,
                "payload": statement.excluded.payload,
                "updated_at": statement.excluded.updated_at,
            },
            where=(
                table.c.last_applied_revision < statement.excluded.last_applied_revision
            ),
        )
        result = self.session.execute(statement)
        self.session.flush()
        return result.rowcount == 1

    def current_payload(
        self, *, target: str, source_lineage: str, projection_kind: str
    ) -> dict[str, Any] | None:
        row = self.session.get(
            ProjectionCheckpoint, (target, source_lineage, projection_kind)
        )
        return dict(row.payload) if row is not None else None

    def supporting_lineages(
        self, *, target: str, projection_kind: str, theme: str
    ) -> set[str]:
        rows = self.session.scalars(
            select(ProjectionCheckpoint).where(
                ProjectionCheckpoint.target_representation == target,
                ProjectionCheckpoint.projection_kind == projection_kind,
            )
        )
        return {
            row.source_lineage
            for row in rows
            if theme in set((row.payload or {}).get("themes", []))
        }

    def generation_acknowledged(self, generation_id: UUID) -> bool:
        events = self.session.scalars(
            select(TaxonomyProjectionEvent).where(
                TaxonomyProjectionEvent.serving_generation_id == generation_id,
                TaxonomyProjectionEvent.delivery_scope == "candidate",
            )
        ).all()
        for event in events:
            completed = self.session.scalar(
                select(TaxonomyProjectionDeliveryEvent.id)
                .join(
                    TaxonomyProjectionDeliveryAttempt,
                    TaxonomyProjectionDeliveryAttempt.id
                    == TaxonomyProjectionDeliveryEvent.delivery_attempt_id,
                )
                .where(
                    TaxonomyProjectionDeliveryAttempt.projection_event_id == event.id,
                    TaxonomyProjectionDeliveryEvent.outcome.in_(
                        ("success", "stale_noop")
                    ),
                )
            )
            if completed is None:
                return False
        return True

    @contextmanager
    def legacy_producer_write(
        self,
        *,
        expected_epoch: int,
        logical_source_key: str,
        revision_kind: str,
        content_hash: str | Callable[[], str],
        auto_commit: bool,
        origin_representation: str = "legacy",
    ) -> Iterator[_LegacyWrite]:
        try:
            with producer_write(
                self.session,
                expected_epoch=expected_epoch,
                allowed_modes={"legacy", "shadow", "dual"},
            ) as authority:
                write = _LegacyWrite(self, authority, origin_representation)
                yield write
                current = self.session.scalar(
                    select(func.max(TaxonomySourceRevisionLog.revision_number)).where(
                        TaxonomySourceRevisionLog.producer_kind == "legacy_theme",
                        TaxonomySourceRevisionLog.logical_source_key
                        == logical_source_key,
                        TaxonomySourceRevisionLog.revision_kind == revision_kind,
                    )
                )
                EconomicTaxonomyPublicationRepository(
                    self.session
                ).append_source_revision(
                    producer_kind="legacy_theme",
                    logical_source_key=logical_source_key,
                    revision_kind=revision_kind,
                    revision_number=int(current or 0) + 1,
                    content_hash=(
                        content_hash() if callable(content_hash) else content_hash
                    ),
                    authority_epoch=authority.authority_epoch,
                )
                if auto_commit:
                    self.session.commit()
                else:
                    self.session.flush()
        except Exception:
            if auto_commit:
                self.session.rollback()
            raise

    @staticmethod
    def notify_delivery_workers(notify: Callable[[], Any] | None = None) -> None:
        if notify is not None:
            notify()


__all__ = [
    "DeliveryLeaseError",
    "EconomicTaxonomyRuntimeService",
    "ProjectionDeliveryClaim",
    "ProjectionDeliveryResult",
    "ProjectionPayloadConflict",
    "ProjectionRevisionError",
    "ProjectionRuntimeError",
]
