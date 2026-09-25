"""Prepare and publish one bounded Economic Taxonomy generation."""

from __future__ import annotations

import argparse
import hmac
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability-id", type=UUID, required=True)
    parser.add_argument(
        "--mode", choices=("legacy", "shadow", "dual", "economic"), required=True
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Persist the candidate without switching serving pointers.",
    )
    return parser


def _publication_principal(config, credential: str | None):
    from app.domain.economic_taxonomy.contracts import AdminPrincipal

    if not config.admin_api_key or not config.admin_principal_id:
        raise RuntimeError("admin_identity_not_configured")
    if not credential or not hmac.compare_digest(credential, config.admin_api_key):
        raise PermissionError("admin_authentication_failed")
    return AdminPrincipal(
        subject=config.admin_principal_id,
        auth_method="admin_api_key",
        roles=frozenset({"taxonomy:review"}),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from app.config import settings
    from app.database import SessionLocal
    from app.services.economic_taxonomy_publication import (
        EconomicTaxonomyPublicationCoordinator,
    )

    principal = _publication_principal(
        settings, os.environ.get("TAXONOMY_ADMIN_KEY")
    )
    coordinator = EconomicTaxonomyPublicationCoordinator(SessionLocal)
    cutoff = coordinator.capture_cutoff(principal=principal)
    prepared = coordinator.prepare_generation(
        cutoff,
        principal=principal,
        reader_capability_manifest_id=args.capability_id,
        target_mode=args.mode,
    )
    if args.prepare_only:
        print(str(prepared.id))
        return 0
    published = coordinator.publish_generation(prepared.id, principal=principal)
    print(str(published.id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
