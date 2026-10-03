"""Stable ContentItem identity shared by legacy and Social X ingestion."""

import re
from hashlib import md5

_STATUS_ID = re.compile(r"/status(?:es)?/(\d+)")


def twitter_external_id(provider_post_id: str) -> str:
    return md5(f"twitter:{provider_post_id}".encode("utf-8")).hexdigest()


def x_post_id_from_url(url: str | None) -> str | None:
    """The tweet id in an X status URL; external_id only keeps its hash."""
    match = _STATUS_ID.search(url or "")
    return match.group(1) if match else None


__all__ = ["twitter_external_id", "x_post_id_from_url"]
