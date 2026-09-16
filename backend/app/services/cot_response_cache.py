from __future__ import annotations

from collections import OrderedDict
from threading import RLock

from app.domain.cot.models import COT_CALCULATION_VERSION, COT_SCHEMA_VERSION


def cot_cache_key(
    endpoint: str,
    publication_id: int,
    *,
    slug: str | None = None,
    range_name: str | None = None,
) -> str:
    parts = [
        "cot",
        COT_SCHEMA_VERSION,
        COT_CALCULATION_VERSION,
        str(publication_id),
        endpoint,
    ]
    if slug is not None:
        parts.append(slug)
    if range_name is not None:
        parts.append(range_name)
    return ":".join(parts)


class CotResponseCache:
    def __init__(self, *, redis_client=None, max_entries: int = 128, ttl: int = 3600):
        self._redis = redis_client
        self._max_entries = max_entries
        self._ttl = ttl
        self._memory: OrderedDict[str, str] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> str | None:
        with self._lock:
            value = self._memory.get(key)
            if value is not None:
                self._memory.move_to_end(key)
                return value
        if self._redis is None:
            return None
        try:
            value = self._redis.get(key)
        except Exception:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            self._remember(key, value)
            return value
        return None

    def set(self, key: str, value: str) -> None:
        self._remember(key, value)
        if self._redis is not None:
            try:
                self._redis.setex(key, self._ttl, value)
            except Exception:
                pass

    def invalidate_all(self) -> None:
        with self._lock:
            self._memory.clear()
        if self._redis is None:
            return
        try:
            batch = []
            for key in self._redis.scan_iter(match="cot:*", count=100):
                batch.append(key)
                if len(batch) == 100:
                    self._redis.delete(*batch)
                    batch.clear()
            if batch:
                self._redis.delete(*batch)
        except Exception:
            pass

    def _remember(self, key: str, value: str) -> None:
        with self._lock:
            self._memory[key] = value
            self._memory.move_to_end(key)
            while len(self._memory) > self._max_entries:
                self._memory.popitem(last=False)


_cache: CotResponseCache | None = None
_cache_lock = RLock()


def get_cot_response_cache() -> CotResponseCache:
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                from app.services.redis_pool import get_redis_client

                _cache = CotResponseCache(redis_client=get_redis_client())
    return _cache


def invalidate_cot_response_cache() -> None:
    get_cot_response_cache().invalidate_all()
