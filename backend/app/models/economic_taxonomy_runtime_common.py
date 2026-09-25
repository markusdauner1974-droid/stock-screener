"""Shared helpers for economic-taxonomy runtime models."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Column, DateTime, Uuid, func


class ImmutableRuntimePayload(ValueError):
    """Raised when an append-only runtime fact would be changed."""


def _uuid_pk():
    return Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


def _created_at():
    return Column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ("ImmutableRuntimePayload",)
