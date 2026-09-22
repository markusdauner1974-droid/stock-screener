"""Generation-scoped reader facade for Economic Theme product payloads."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.economic_taxonomy_runtime import (
    GenerationInputManifest,
    ReaderSnapshotBundle,
    ReaderSnapshotEntry,
    ServingGeneration,
    ServingGenerationEvent,
    TaxonomyAuthority,
)
from app.utils.file_hashing import canonical_json_sha256 as _snapshot_hash


class EconomicThemeReadError(ValueError):
    pass


class ServingGenerationUnavailable(EconomicThemeReadError):
    pass


class GenerationNotFound(EconomicThemeReadError):
    pass


class ReaderSnapshotUnavailable(EconomicThemeReadError):
    pass


class ReaderSnapshotCoherenceError(EconomicThemeReadError):
    pass


class LegacyThemeAuthority(EconomicThemeReadError):
    pass


class LegacyMappingAmbiguous(EconomicThemeReadError):
    pass


@dataclass(frozen=True, slots=True)
class ThemeReadAuthority:
    mode: str
    source_name: str
    authority_epoch: int | None = None
    generation_id: UUID | None = None
    preview_generation_id: UUID | None = None


class EconomicThemeReader:
    """Resolve one serving generation and read only its sealed bundle."""

    def __init__(self, db: Session):
        self.db = db
        self._authority_selection: ThemeReadAuthority | None = None
        self._catalog_cache: dict | None = None
        self._review_cache: dict | None = None

    @staticmethod
    def for_mode(mode: str) -> ThemeReadAuthority:
        if mode not in {"legacy", "shadow", "dual", "economic"}:
            raise ValueError("invalid_taxonomy_authority_mode")
        return ThemeReadAuthority(
            mode=mode,
            source_name="economic" if mode == "economic" else "legacy",
        )

    def select_authority(self) -> ThemeReadAuthority:
        if self._authority_selection is not None:
            return self._authority_selection
        if self.db.get_bind().dialect.name == "sqlite":
            table_exists = self.db.scalar(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = :table_name"
                ).bindparams(table_name=TaxonomyAuthority.__tablename__)
            )
            if table_exists is None:
                selected = self.for_mode("legacy")
                self._authority_selection = selected
                return selected
        authority = self.db.get(TaxonomyAuthority, 1)
        if authority is None:
            selected = self.for_mode("legacy")
        else:
            route = self.for_mode(authority.mode)
            selected = ThemeReadAuthority(
                mode=route.mode,
                source_name=route.source_name,
                authority_epoch=authority.authority_epoch,
                generation_id=(
                    authority.serving_generation_id
                    if route.source_name == "economic"
                    else None
                ),
                preview_generation_id=authority.serving_generation_id,
            )
        self._authority_selection = selected
        return selected

    @property
    def source_name(self) -> str:
        return self.select_authority().source_name

    def read_current_catalog(self) -> dict:
        authority = self.select_authority()
        if authority.source_name != "economic":
            raise LegacyThemeAuthority("legacy_theme_authority")
        if authority.generation_id is None:
            raise ServingGenerationUnavailable("serving_generation_unavailable")
        if self._catalog_cache is None:
            self._catalog_cache = self.read_catalog(authority.generation_id)
        return deepcopy(self._catalog_cache)

    def read_current_taxonomy_review(self) -> dict:
        authority = self.select_authority()
        if authority.source_name != "economic":
            raise LegacyThemeAuthority("legacy_theme_authority")
        if authority.generation_id is None:
            raise ServingGenerationUnavailable("serving_generation_unavailable")
        if self._review_cache is None:
            self._review_cache = self.read_taxonomy_review(authority.generation_id)
        return deepcopy(self._review_cache)

    def read_catalog(self, generation_id: UUID | None = None) -> dict:
        generation = self.resolve_generation(generation_id)
        return self._read_entry(generation, "economic_themes", "catalog")

    def read_taxonomy_review(self, generation_id: UUID | None = None) -> dict:
        generation = self.resolve_generation(generation_id)
        return self._read_entry(generation, "economic_taxonomy", "review")

    def generation_metadata(self, generation_id: UUID | None = None) -> dict:
        generation = self.resolve_generation(generation_id)
        manifest, bundle = self._load_payload_context(generation)
        return self._metadata(generation, manifest, bundle)

    def read_legacy_themes(self, legacy_theme_cluster_id: int) -> list[dict]:
        """Resolve a legacy identity only through reviewed snapshot mappings."""

        catalog = self.read_current_catalog()
        destination_ids = {
            str(row["destination_theme_id"])
            for row in catalog.get("mappings", [])
            if int(row["legacy_theme_cluster_id"]) == legacy_theme_cluster_id
        }
        destination_ids = {
            self._canonical_theme_id(catalog, value) for value in destination_ids
        }
        return [
            deepcopy(theme)
            for theme in catalog.get("themes", [])
            if str(theme.get("economic_theme_id")) in destination_ids
        ]

    def read_legacy_theme(self, legacy_theme_cluster_id: int) -> dict | None:
        themes = self.read_legacy_themes(legacy_theme_cluster_id)
        if len(themes) > 1:
            raise LegacyMappingAmbiguous("legacy_theme_split_requires_allocation")
        return themes[0] if themes else None

    def theme_summaries_for_symbol(self, symbol: str, *, limit: int = 8) -> list[dict]:
        normalized = symbol.strip().casefold()
        if not normalized:
            return []
        catalog = self.read_current_catalog()
        rows = []
        for theme in catalog.get("themes", []):
            matching = [
                row
                for row in theme.get("constituents", [])
                if str(row.get("canonical_symbol") or "").casefold() == normalized
            ]
            if not matching:
                continue
            constituent = matching[0]
            metric = self._best_metric(theme)
            rows.append(
                {
                    "theme_id": UUID(str(theme["economic_theme_id"])),
                    "display_name": theme.get("display_name"),
                    "pipeline": "economic",
                    "category": self.facet_value(theme, "category"),
                    "lifecycle_state": theme.get("lifecycle"),
                    "is_emerging": theme.get("lifecycle") in {"candidate", "emerging"},
                    "confidence": constituent.get("exposure_strength"),
                    "mention_count": theme.get("direct_observation_count", 0),
                    "correlation_to_theme": None,
                    "momentum_score": metric.get("percentile"),
                    "mention_velocity": None,
                    "basket_return_1m": None,
                    "status": theme.get("lifecycle"),
                    "generation_id": catalog["generation_id"],
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                -(row["momentum_score"] if row["momentum_score"] is not None else -1),
                str(row["display_name"] or "").casefold(),
            ),
        )[:limit]

    def ranked_themes(
        self,
        *,
        ranking_view: str = "broad_confirmation",
        limit: int = 20,
        offset: int = 0,
        include_unavailable: bool = True,
    ) -> list[dict]:
        catalog = self.read_current_catalog()
        rows = []
        for theme in catalog.get("themes", []):
            metric = dict((theme.get("metrics") or {}).get(ranking_view) or {})
            if not include_unavailable and metric.get("availability") != "available":
                continue
            rows.append({**deepcopy(theme), "selected_metric": metric})
        rows.sort(
            key=lambda row: (
                row["selected_metric"].get("availability") != "available",
                -float(row["selected_metric"].get("percentile") or -1),
                -float(row["selected_metric"].get("raw_value") or -1),
                str(row.get("display_name") or "").casefold(),
            )
        )
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
            row["generation_id"] = catalog["generation_id"]
        return rows[offset : offset + limit]

    def legacy_rankings(
        self,
        *,
        pipeline: str,
        limit: int,
        offset: int = 0,
        lifecycle_states: set[str] | None = None,
    ) -> tuple[list[dict], int]:
        catalog = self.read_current_catalog()
        view = (
            "technical_attention"
            if pipeline == "technical"
            else "fundamental_attention"
        )
        legacy_ids_by_theme: dict[str, list[int]] = {}
        for mapping in catalog.get("mappings", []):
            theme_id = self._canonical_theme_id(
                catalog, str(mapping["destination_theme_id"])
            )
            legacy_ids_by_theme.setdefault(
                theme_id, []
            ).append(int(mapping["legacy_theme_cluster_id"]))
        rows = []
        for theme in self.ranked_themes(
            ranking_view=view,
            limit=max(len(catalog.get("themes", [])), 1),
        ):
            if lifecycle_states and theme.get("lifecycle") not in lifecycle_states:
                continue
            metric = theme["selected_metric"]
            components = metric.get("components") or {}
            tickers = [
                row.get("canonical_symbol")
                for row in theme.get("constituents", [])
                if row.get("canonical_symbol")
            ]
            for legacy_id in sorted(
                legacy_ids_by_theme.get(str(theme["economic_theme_id"]), [])
            ):
                rows.append(
                    {
                        "theme_cluster_id": legacy_id,
                        "rank": len(rows) + 1,
                        "theme": theme.get("display_name"),
                        "status": theme.get("lifecycle"),
                        "lifecycle_state": theme.get("lifecycle"),
                        "momentum_score": float(metric.get("percentile") or 0),
                        "mention_velocity": float(
                            components.get("velocity") or 0
                        ),
                        "mentions_7d": int(
                            components.get("direct_source_count")
                            or theme.get("deduplicated_source_family_count")
                            or 0
                        ),
                        "basket_rs_vs_spy": float(
                            components.get("basket_rs_vs_benchmark") or 0
                        ),
                        "basket_return_1w": float(
                            components.get("basket_return_1w") or 0
                        ),
                        "pct_above_50ma": float(
                            components.get("pct_above_50ma") or 0
                        ),
                        "avg_correlation": float(
                            components.get("avg_correlation") or 0
                        ),
                        "num_constituents": len(theme.get("constituents", [])),
                        "top_tickers": tickers[:5],
                        "first_seen": None,
                        "economic_theme_id": theme["economic_theme_id"],
                        "generation_id": catalog["generation_id"],
                    }
                )
        total = len(rows)
        return rows[offset : offset + limit], total

    def find_theme(self, value: str) -> dict | None:
        normalized = value.strip().casefold()
        if not normalized:
            return None
        catalog = self.read_current_catalog()
        for theme in catalog.get("themes", []):
            if str(theme.get("economic_theme_id", "")).casefold() == normalized:
                return deepcopy(theme)
            names = [theme.get("display_name"), *(theme.get("aliases") or [])]
            if normalized in {str(name).casefold() for name in names if name}:
                return deepcopy(theme)
        return None

    @staticmethod
    def _best_metric(theme: dict) -> dict:
        metrics = theme.get("metrics") or {}
        for key in (
            "broad_confirmation",
            "emerging",
            "technical_attention",
            "fundamental_attention",
            "narrative_attention",
        ):
            value = metrics.get(key) or {}
            if value.get("availability") == "available":
                return value
        return {"availability": "unavailable", "raw_value": None, "percentile": None}

    @staticmethod
    def facet_value(theme: dict, dimension: str):
        return next(
            (
                row.get("display_value") or row.get("value")
                for row in theme.get("facets", [])
                if row.get("dimension") == dimension
            ),
            None,
        )

    @staticmethod
    def _canonical_theme_id(catalog: dict, theme_id: str) -> str:
        redirect_by_source = {
            str(row["source_theme_id"]): str(row["target_theme_id"])
            for row in catalog.get("redirects", [])
        }
        visited = set()
        while theme_id in redirect_by_source:
            if theme_id in visited:
                raise ReaderSnapshotCoherenceError("economic_theme_redirect_cycle")
            visited.add(theme_id)
            theme_id = redirect_by_source[theme_id]
        return theme_id

    def resolve_generation(
        self, generation_id: UUID | None = None
    ) -> ServingGeneration:
        if generation_id is None:
            generation_id = self.select_authority().preview_generation_id
            if generation_id is None:
                raise ServingGenerationUnavailable("serving_generation_unavailable")
        generation = self.db.get(ServingGeneration, generation_id)
        if generation is None:
            raise GenerationNotFound("generation_not_found")
        return generation

    def _read_entry(self, generation, snapshot_kind, resource_key):
        manifest, bundle = self._load_payload_context(generation)
        entry = self.db.scalar(
            select(ReaderSnapshotEntry).where(
                ReaderSnapshotEntry.reader_snapshot_bundle_id == bundle.id,
                ReaderSnapshotEntry.snapshot_kind == snapshot_kind,
                ReaderSnapshotEntry.resource_key == resource_key,
            )
        )
        if entry is None:
            raise ReaderSnapshotUnavailable("reader_snapshot_entry_unavailable")
        payload = deepcopy(entry.payload)
        if entry.payload_hash != _snapshot_hash(payload):
            raise ReaderSnapshotCoherenceError("reader_snapshot_entry_hash_mismatch")
        indexed_hash = next(
            (
                row.get("payload_hash")
                for row in bundle.payload.get("entries", [])
                if row.get("snapshot_kind") == snapshot_kind
                and row.get("resource_key") == resource_key
            ),
            None,
        )
        if indexed_hash != entry.payload_hash:
            raise ReaderSnapshotCoherenceError("reader_snapshot_index_mismatch")
        expected = {
            "taxonomy_version_id": str(generation.taxonomy_version_id),
            "interpretation_set_id": str(generation.interpretation_set_id),
            "generation_input_manifest_id": str(manifest.id),
            "generation_input_manifest_hash": manifest.semantic_hash,
            "metrics_revision_id": str(generation.metrics_revision_id),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ReaderSnapshotCoherenceError("reader_snapshot_generation_mismatch")
        metadata = self._metadata(generation, manifest, bundle)
        payload.update(
            {
                "generation_id": str(generation.id),
                "generation": metadata,
            }
        )
        return payload

    def _load_payload_context(self, generation):
        manifest = self.db.get(
            GenerationInputManifest, generation.generation_input_manifest_id
        )
        bundle = self.db.get(ReaderSnapshotBundle, generation.reader_snapshot_bundle_id)
        if (
            manifest is None
            or manifest.status != "sealed"
            or bundle is None
            or bundle.status != "sealed"
        ):
            raise ReaderSnapshotUnavailable("reader_snapshot_unavailable")
        if bundle.generation_input_manifest_id != manifest.id:
            raise ReaderSnapshotCoherenceError("reader_snapshot_manifest_mismatch")
        expected_summary = {
            "taxonomy_version_id": str(generation.taxonomy_version_id),
            "interpretation_set_id": str(generation.interpretation_set_id),
            "generation_input_manifest_id": str(manifest.id),
            "generation_input_manifest_hash": manifest.semantic_hash,
            "metrics_revision_id": str(generation.metrics_revision_id),
        }
        if any(
            bundle.payload.get(key) != value for key, value in expected_summary.items()
        ):
            raise ReaderSnapshotCoherenceError("reader_snapshot_generation_mismatch")
        return manifest, bundle

    def _metadata(self, generation, manifest, bundle):
        latest_event = self.db.scalar(
            select(ServingGenerationEvent)
            .where(ServingGenerationEvent.serving_generation_id == generation.id)
            .order_by(ServingGenerationEvent.sequence_number.desc())
            .limit(1)
        )
        authority = self.select_authority()
        is_current = authority.preview_generation_id == generation.id
        return {
            "generation_id": str(generation.id),
            "status": latest_event.event_type
            if latest_event is not None
            else "unknown",
            "published_at": (
                latest_event.created_at.isoformat() if latest_event is not None else None
            ),
            "taxonomy_version_id": str(generation.taxonomy_version_id),
            "interpretation_set_id": str(generation.interpretation_set_id),
            "metrics_revision_id": str(generation.metrics_revision_id),
            "generation_input_manifest_id": str(manifest.id),
            "generation_input_manifest_hash": manifest.semantic_hash,
            "reader_snapshot_bundle_id": str(bundle.id),
            "reader_snapshot_semantic_hash": bundle.semantic_hash,
            "reader_capability_manifest_id": str(
                generation.reader_capability_manifest_id
            ),
            "semantic_hash": generation.semantic_hash,
            "artifact_integrity_hash": generation.artifact_integrity_hash,
            "authority_mode": authority.mode if is_current else "historical",
            "source_name": "economic",
            "authority_epoch": authority.authority_epoch if is_current else None,
        }
