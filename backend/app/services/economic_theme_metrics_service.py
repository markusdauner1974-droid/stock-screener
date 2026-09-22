"""Deterministic V1 Economic Theme ranking calculations and persistence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.economic_taxonomy import EconomicThemeRevision, TaxonomyVersion
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    GenerationInputManifest,
    InterpretationSelection,
    InterpretationSet,
    LensEligibilityRevision,
    MetricsRevision,
    ThemeMetric,
    ThemeSignalObservation,
)
from app.services.economic_theme_observation_service import (
    EconomicThemeObservationService,
)
from app.utils.file_hashing import canonical_json_sha256 as _hash

FORMULA_VERSION = "economic-theme-metrics-v1"
_CHANNELS = ("technical", "fundamental", "narrative")
_VIEWS = (
    "technical_attention",
    "fundamental_attention",
    "narrative_attention",
    "emerging",
    "broad_confirmation",
)


class MetricsCalculationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MetricObservation:
    source_family_id: UUID
    evidence_channel: str
    available_at: datetime
    observation_kind: str = "primary"
    direct_root: bool = True
    direction: str | None = None


@dataclass(frozen=True, slots=True)
class MetricSignal:
    source_family_id: UUID
    signal_kind: str
    available_at: datetime
    accepted: bool = True


@dataclass(frozen=True, slots=True)
class ThemeMetricInput:
    theme_id: UUID
    lifecycle: str
    observations: tuple[MetricObservation, ...] = ()
    signals: tuple[MetricSignal, ...] = ()
    eligible_channels: frozenset[str] = frozenset()
    pinned_eligibility_revision_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricValue:
    availability: str
    raw: float | None
    percentile: float | None = None
    components: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ThemeMetricsCalculation:
    theme_id: UUID
    technical_attention: MetricValue
    fundamental_attention: MetricValue
    narrative_attention: MetricValue
    emerging: MetricValue
    broad_confirmation: MetricValue
    pinned_eligibility_revision_ids: tuple[str, ...] = ()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _unavailable(**components: Any) -> MetricValue:
    return MetricValue(
        availability="unavailable", raw=None, percentile=None, components=components
    )


def _available(raw: float, **components: Any) -> MetricValue:
    return MetricValue(
        availability="available",
        raw=float(raw),
        percentile=None,
        components=components,
    )


class EconomicThemeMetricsService:
    def __init__(self, session: Session | None = None):
        self.session = session

    @staticmethod
    def available_value(raw: float) -> MetricValue:
        return _available(raw)

    @staticmethod
    def calculate(
        theme: ThemeMetricInput, *, as_of: datetime
    ) -> ThemeMetricsCalculation:
        as_of = _utc(as_of)
        roots = tuple(
            observation
            for observation in theme.observations
            if observation.observation_kind == "primary"
            and observation.direct_root
            and _utc(observation.available_at) <= as_of
        )
        technical = EconomicThemeMetricsService._technical(
            roots, theme.signals, as_of=as_of
        )
        fundamental = EconomicThemeMetricsService._channel_attention(
            roots,
            channel="fundamental",
            window_days=90,
            half_life_days=30,
            as_of=as_of,
        )
        narrative = EconomicThemeMetricsService._channel_attention(
            roots,
            channel="narrative",
            window_days=14,
            half_life_days=3,
            as_of=as_of,
        )
        emerging = EconomicThemeMetricsService._emerging(
            roots, lifecycle=theme.lifecycle, as_of=as_of
        )
        return ThemeMetricsCalculation(
            theme_id=theme.theme_id,
            technical_attention=technical,
            fundamental_attention=fundamental,
            narrative_attention=narrative,
            emerging=emerging,
            broad_confirmation=_unavailable(
                reason="channel_percentiles_not_ranked"
            ),
            pinned_eligibility_revision_ids=tuple(
                sorted(theme.pinned_eligibility_revision_ids)
            ),
        )

    @staticmethod
    def rank(values: Sequence[MetricValue]) -> list[MetricValue]:
        result = list(values)
        available = [
            (index, value)
            for index, value in enumerate(values)
            if value.availability == "available" and value.raw is not None
        ]
        if not available:
            return result
        if len(available) == 1:
            index, value = available[0]
            result[index] = replace(value, percentile=100.0)
            return result

        ordered = sorted(available, key=lambda item: float(item[1].raw))
        position = 0
        while position < len(ordered):
            end = position + 1
            raw = ordered[position][1].raw
            while end < len(ordered) and ordered[end][1].raw == raw:
                end += 1
            average_rank = ((position + 1) + end) / 2
            percentile = 100 * (average_rank - 1) / (len(ordered) - 1)
            for index, value in ordered[position:end]:
                result[index] = replace(value, percentile=percentile)
            position = end
        return result

    @classmethod
    def calculate_and_rank(
        cls, themes: Sequence[ThemeMetricInput], *, as_of: datetime
    ) -> list[ThemeMetricsCalculation]:
        calculated = [cls.calculate(theme, as_of=as_of) for theme in themes]
        for field_name in (
            "technical_attention",
            "fundamental_attention",
            "narrative_attention",
            "emerging",
        ):
            ranked = cls.rank([getattr(item, field_name) for item in calculated])
            calculated = [
                replace(item, **{field_name: ranked[index]})
                for index, item in enumerate(calculated)
            ]

        with_broad: list[ThemeMetricsCalculation] = []
        for item in calculated:
            channels = [
                value
                for value in (
                    item.technical_attention,
                    item.fundamental_attention,
                    item.narrative_attention,
                )
                if value.availability == "available" and value.percentile is not None
            ]
            direct_families = {
                family
                for value in channels
                for family in value.components.get("direct_source_family_ids", [])
            }
            if len(channels) >= 2 and len(direct_families) >= 2:
                broad = _available(
                    sum(float(value.percentile) for value in channels) / len(channels),
                    available_channels=len(channels),
                    direct_source_family_ids=sorted(direct_families),
                )
            else:
                broad = _unavailable(
                    reason="requires_two_channels_and_two_direct_source_families",
                    available_channels=len(channels),
                    direct_source_family_ids=sorted(direct_families),
                )
            with_broad.append(replace(item, broad_confirmation=broad))

        ranked_broad = cls.rank([item.broad_confirmation for item in with_broad])
        return [
            replace(item, broad_confirmation=ranked_broad[index])
            for index, item in enumerate(with_broad)
        ]

    def calculate_metrics(
        self,
        *,
        taxonomy_version_id: UUID,
        interpretation_set_id: UUID,
        generation_input_manifest_id: UUID,
        as_of: datetime,
        actor: str,
        themes: Sequence[ThemeMetricInput] | None = None,
        formula_version: str = FORMULA_VERSION,
        pinned_eligibility_revisions: Mapping[UUID, Iterable[str]] | None = None,
    ) -> MetricsRevision:
        if self.session is None:
            raise MetricsCalculationError("metrics_session_required")
        if not actor.strip():
            raise MetricsCalculationError("metrics_actor_required")
        as_of = _utc(as_of)
        taxonomy = self.session.get(TaxonomyVersion, taxonomy_version_id)
        interpretation = self.session.get(InterpretationSet, interpretation_set_id)
        manifest = self.session.get(
            GenerationInputManifest, generation_input_manifest_id
        )
        if taxonomy is None or taxonomy.status != "sealed":
            raise MetricsCalculationError("sealed_taxonomy_required")
        if interpretation is None or interpretation.status != "sealed":
            raise MetricsCalculationError("sealed_interpretation_required")
        if manifest is None or manifest.status != "sealed":
            raise MetricsCalculationError("sealed_manifest_required")
        if interpretation.generation_input_manifest_id != manifest.id:
            raise MetricsCalculationError("interpretation_manifest_mismatch")

        existing = self.session.scalar(
            select(MetricsRevision).where(
                MetricsRevision.interpretation_set_id == interpretation_set_id,
                MetricsRevision.formula_version == formula_version,
                MetricsRevision.as_of == as_of,
            )
        )
        if existing is not None:
            if existing.status != "sealed":
                raise MetricsCalculationError("metrics_revision_incomplete")
            return existing

        pinned = self._manifest_eligibility_by_theme(
            manifest=manifest,
            interpretation_set_id=interpretation_set_id,
        )
        for theme_id, values in (pinned_eligibility_revisions or {}).items():
            pinned.setdefault(theme_id, set()).update(str(value) for value in values)
        if themes is not None:
            inputs = [
                replace(
                    theme,
                    pinned_eligibility_revision_ids=tuple(
                        sorted(
                            set(theme.pinned_eligibility_revision_ids)
                            | pinned.get(theme.theme_id, set())
                        )
                    ),
                )
                for theme in themes
            ]
        else:
            inputs = self._load_inputs(
                taxonomy_version_id=taxonomy_version_id,
                interpretation_set_id=interpretation_set_id,
                pinned_eligibility_revisions=pinned,
            )
        if len({item.theme_id for item in inputs}) != len(inputs):
            raise MetricsCalculationError("duplicate_metric_theme")
        expected_ids = {
            row.theme_id
            for row in self.session.scalars(
                select(EconomicThemeRevision).where(
                    EconomicThemeRevision.taxonomy_version_id
                    == taxonomy_version_id
                )
            )
        }
        if any(item.theme_id not in expected_ids for item in inputs):
            raise MetricsCalculationError("metric_theme_not_in_snapshot")

        calculations = self.calculate_and_rank(inputs, as_of=as_of)
        revision = MetricsRevision(
            status="unsealed",
            interpretation_set_id=interpretation_set_id,
            generation_input_manifest_id=generation_input_manifest_id,
            formula_version=formula_version,
            as_of=as_of,
            created_by=actor,
        )
        self.session.add(revision)
        self.session.flush()
        semantic_rows: list[dict[str, Any]] = []
        for calculation in calculations:
            for ranking_view in _VIEWS:
                value: MetricValue = getattr(calculation, ranking_view)
                components = {
                    **value.components,
                    "availability": value.availability,
                    "pinned_eligibility_revision_ids": list(
                        calculation.pinned_eligibility_revision_ids
                    ),
                }
                self.session.add(
                    ThemeMetric(
                        metrics_revision_id=revision.id,
                        economic_theme_id=calculation.theme_id,
                        ranking_view=ranking_view,
                        available=value.availability == "available",
                        raw_value=value.raw,
                        percentile=value.percentile,
                        components=components,
                    )
                )
                semantic_rows.append(
                    {
                        "theme_id": str(calculation.theme_id),
                        "ranking_view": ranking_view,
                        "available": value.availability == "available",
                        "raw_value": value.raw,
                        "percentile": value.percentile,
                        "components": components,
                    }
                )
        self.session.flush()
        semantic_payload = {
            "formula_version": formula_version,
            "as_of": as_of.isoformat(),
            "interpretation_set_id": str(interpretation_set_id),
            "generation_input_manifest_id": str(generation_input_manifest_id),
            "metrics": sorted(
                semantic_rows,
                key=lambda item: (item["theme_id"], item["ranking_view"]),
            ),
        }
        semantic_hash = _hash(semantic_payload)
        revision.seal(
            semantic_hash=semantic_hash,
            artifact_integrity_hash=_hash(
                {
                    **semantic_payload,
                    "metrics_revision_id": str(revision.id),
                    "created_by": actor,
                }
            ),
        )
        self.session.flush()
        return revision

    @staticmethod
    def _technical(
        roots: Sequence[MetricObservation],
        signals: Sequence[MetricSignal],
        *,
        as_of: datetime,
    ) -> MetricValue:
        lower = as_of - timedelta(days=30)
        daily: dict[tuple[UUID, Any], float] = {}
        direct_families: set[str] = set()
        for observation in roots:
            available_at = _utc(observation.available_at)
            if observation.evidence_channel != "technical" or not (
                lower <= available_at <= as_of
            ):
                continue
            contribution = 2 ** (
                -((as_of - available_at).total_seconds())
                / timedelta(days=7).total_seconds()
            )
            key = (observation.source_family_id, available_at.date())
            daily[key] = max(daily.get(key, 0.0), contribution)
            direct_families.add(str(observation.source_family_id))
        for signal in signals:
            available_at = _utc(signal.available_at)
            if not signal.accepted or not (lower <= available_at <= as_of):
                continue
            contribution = 2 ** (
                -((as_of - available_at).total_seconds())
                / timedelta(days=5).total_seconds()
            )
            key = (signal.source_family_id, available_at.date())
            daily[key] = max(daily.get(key, 0.0), contribution)
        if not daily:
            return _unavailable(reason="no_selected_support")
        return _available(
            sum(daily.values()),
            daily_contribution_count=len(daily),
            direct_source_family_ids=sorted(direct_families),
            root_half_life_days=7,
            signal_half_life_days=5,
            window_days=30,
        )

    @staticmethod
    def _channel_attention(
        roots: Sequence[MetricObservation],
        *,
        channel: str,
        window_days: int,
        half_life_days: int,
        as_of: datetime,
    ) -> MetricValue:
        lower = as_of - timedelta(days=window_days)
        daily: dict[tuple[UUID, Any], float] = {}
        families: set[str] = set()
        for observation in roots:
            available_at = _utc(observation.available_at)
            if observation.evidence_channel != channel or not (
                lower <= available_at <= as_of
            ):
                continue
            contribution = 2 ** (
                -((as_of - available_at).total_seconds())
                / timedelta(days=half_life_days).total_seconds()
            )
            key = (observation.source_family_id, available_at.date())
            daily[key] = max(daily.get(key, 0.0), contribution)
            families.add(str(observation.source_family_id))
        if not daily:
            return _unavailable(reason="no_selected_support")
        return _available(
            sum(daily.values()),
            daily_contribution_count=len(daily),
            direct_source_family_ids=sorted(families),
            half_life_days=half_life_days,
            window_days=window_days,
            unsigned=(channel == "fundamental"),
        )

    @staticmethod
    def _emerging(
        roots: Sequence[MetricObservation], *, lifecycle: str, as_of: datetime
    ) -> MetricValue:
        if lifecycle not in {"provisional", "reactivated"}:
            return _unavailable(reason="lifecycle_not_emerging")
        recent_lower = as_of - timedelta(days=7)
        prior_lower = as_of - timedelta(days=28)
        recent = [
            root
            for root in roots
            if recent_lower <= _utc(root.available_at) <= as_of
        ]
        recent_families = {str(root.source_family_id) for root in recent}
        recent_dates = {_utc(root.available_at).date().isoformat() for root in recent}
        if len(recent_families) < 2 or len(recent_dates) < 2:
            return _unavailable(
                reason="requires_two_families_on_two_dates",
                families_7d=len(recent_families),
                dates_7d=len(recent_dates),
            )
        prior_families = {
            str(root.source_family_id)
            for root in roots
            if prior_lower <= _utc(root.available_at) < recent_lower
        }
        return _available(
            len(recent_families) - len(prior_families) / 3,
            families_7d=len(recent_families),
            families_prior_21d=len(prior_families),
            dates_7d=len(recent_dates),
        )

    def _load_inputs(
        self,
        *,
        taxonomy_version_id: UUID,
        interpretation_set_id: UUID,
        pinned_eligibility_revisions: Mapping[UUID, Iterable[str]],
    ) -> list[ThemeMetricInput]:
        revisions = self.session.scalars(
            select(EconomicThemeRevision).where(
                EconomicThemeRevision.taxonomy_version_id == taxonomy_version_id
            )
        ).all()
        observation_facts = EconomicThemeObservationService._observations_for_set(
            self.session, interpretation_set_id
        )
        observations: dict[UUID, list[MetricObservation]] = defaultdict(list)
        for fact in observation_facts:
            observations[fact.economic_theme_id].append(
                MetricObservation(
                    source_family_id=fact.source_family_id,
                    evidence_channel=fact.evidence_channel,
                    available_at=fact.available_at,
                    observation_kind=fact.observation_kind,
                    direct_root=bool(fact.payload.get("direct_root", False)),
                    direction=fact.payload.get("direction"),
                )
            )
        signal_rows = self.session.execute(
            select(ThemeSignalObservation, ClaimAssignment)
            .join(
                ClaimAssignment,
                ClaimAssignment.id == ThemeSignalObservation.claim_assignment_id,
            )
            .join(
                InterpretationSelection,
                InterpretationSelection.selected_classification_attempt_id
                == ClaimAssignment.classification_attempt_id,
            )
            .where(
                InterpretationSelection.interpretation_set_id
                == interpretation_set_id
            )
        ).all()
        signals: dict[UUID, list[MetricSignal]] = defaultdict(list)
        for signal, assignment in signal_rows:
            signals[assignment.economic_theme_id].append(
                MetricSignal(
                    source_family_id=UUID(str(signal.payload["source_family_id"])),
                    signal_kind=signal.signal_kind,
                    available_at=_utc(signal.available_at),
                    accepted=True,
                )
            )
        return [
            ThemeMetricInput(
                theme_id=revision.theme_id,
                lifecycle=revision.lifecycle,
                observations=tuple(observations.get(revision.theme_id, ())),
                signals=tuple(signals.get(revision.theme_id, ())),
                pinned_eligibility_revision_ids=tuple(
                    sorted(
                        str(value)
                        for value in pinned_eligibility_revisions.get(
                            revision.theme_id, ()
                        )
                    )
                ),
            )
            for revision in revisions
        ]

    def _manifest_eligibility_by_theme(
        self,
        *,
        manifest: GenerationInputManifest,
        interpretation_set_id: UUID,
    ) -> dict[UUID, set[str]]:
        revision_by_lineage = {
            str(item.get("lineage")): item.get("eligibility_revision")
            for item in manifest.selections or []
            if item.get("lineage") is not None
            and item.get("eligibility_revision") is not None
        }
        selections = self.session.scalars(
            select(InterpretationSelection).where(
                InterpretationSelection.interpretation_set_id
                == interpretation_set_id
            )
        ).all()
        result: dict[UUID, set[str]] = defaultdict(set)
        for selection in selections:
            revision_number = revision_by_lineage.get(str(selection.source_lineage_id))
            if revision_number is None:
                continue
            eligibility = self.session.scalar(
                select(LensEligibilityRevision).where(
                    LensEligibilityRevision.source_lineage_id
                    == selection.source_lineage_id,
                    LensEligibilityRevision.evidence_packet_id
                    == selection.evidence_packet_id,
                    LensEligibilityRevision.revision_number
                    == int(revision_number),
                )
            )
            if eligibility is None:
                raise MetricsCalculationError("eligibility_revision_not_pinned")
            theme_ids = self.session.scalars(
                select(ClaimAssignment.economic_theme_id).where(
                    ClaimAssignment.classification_attempt_id
                    == selection.selected_classification_attempt_id
                )
            ).all()
            token = f"{selection.source_lineage_id}:{eligibility.revision_number}"
            for theme_id in theme_ids:
                result[theme_id].add(token)
        return result
