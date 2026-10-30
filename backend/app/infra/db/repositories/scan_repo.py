"""SQLAlchemy implementation of ScanRepository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.scanning.errors import DuplicateIdempotencyKey, SingleActiveScanViolation
from app.domain.scanning.ports import ScanRepository
from app.models.scan_result import SCAN_TRIGGER_SOURCE_WATCHLIST, Scan
from app.services.scan_execution import delete_scans


def _is_single_active_scan_integrity_error(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc))
    return (
        "uq_scans_single_active" in message
        or "UNIQUE constraint failed: index 'uq_scans_single_active'" in message
    )


def _is_idempotency_key_integrity_error(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc))
    return "ix_scans_idempotency_key" in message or "scans.idempotency_key" in message


class SqlScanRepository(ScanRepository):
    """Persist and retrieve Scan rows via SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, scan_id: str, **fields) -> Scan:
        scan = Scan(scan_id=scan_id, **fields)
        self._session.add(scan)
        try:
            self._session.flush()  # assigns PK without committing
        except IntegrityError as exc:
            if _is_single_active_scan_integrity_error(exc):
                raise SingleActiveScanViolation(
                    "A queued or running scan already exists."
                ) from exc
            if _is_idempotency_key_integrity_error(exc):
                raise DuplicateIdempotencyKey(
                    "A scan with this idempotency key already exists."
                ) from exc
            raise
        return scan

    def get_by_scan_id(self, scan_id: str) -> Scan | None:
        return (
            self._session.query(Scan)
            .filter(Scan.scan_id == scan_id)
            .first()
        )

    def get_by_idempotency_key(self, key: str) -> Scan | None:
        return (
            self._session.query(Scan)
            .filter(Scan.idempotency_key == key)
            .first()
        )

    def get_active_scan(self) -> Scan | None:
        return (
            self._session.query(Scan)
            .filter(Scan.status.in_(("queued", "running")))
            .order_by(Scan.started_at.desc())
            .first()
        )

    def update_status(self, scan_id: str, status: str, **fields) -> None:
        scan = self.get_by_scan_id(scan_id)
        if scan is None:
            return

        scan.status = status

        if "total_stocks" in fields:
            scan.total_stocks = fields["total_stocks"]
        if "passed_stocks" in fields:
            scan.passed_stocks = fields["passed_stocks"]
        if status in ("completed", "cancelled"):
            scan.completed_at = datetime.utcnow()

        self._session.flush()

    def list_recent(self, limit: int = 20, market: str | None = None) -> list[Scan]:
        daily = Scan.trigger_source == SCAN_TRIGGER_SOURCE_WATCHLIST
        market_view = [Scan.represents_market_view()]
        symbol_lists = [~Scan.represents_market_view(), ~daily]
        daily_watchlists = [~Scan.represents_market_view(), daily]
        if market:
            market_view.append(Scan.universe_market == market.upper())
            # A symbol list with no stored market belongs to every market.
            in_market = or_(Scan.universe_market == market.upper(), Scan.universe_market.is_(None))
            symbol_lists.append(in_market)
            daily_watchlists.append(in_market)

        def newest(*criteria):
            # Each kind limited apart, so a busy kind never pushes another out.
            return (
                select(Scan.id)
                .where(*criteria)
                .order_by(*Scan.newest_first())
                .limit(limit)
            )

        return (
            self._session.query(Scan)
            .filter(or_(*(Scan.id.in_(newest(*kind)) for kind in (market_view, symbol_lists, daily_watchlists))))
            .order_by(*Scan.newest_first())
            .all()
        )

    def delete(self, scan_id: str) -> bool:
        deleted_scans, _ = delete_scans(self._session, [scan_id])
        return deleted_scans > 0
