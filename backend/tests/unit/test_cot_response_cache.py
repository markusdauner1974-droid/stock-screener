from app.services.cot_response_cache import CotResponseCache, cot_cache_key


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, _ttl, value):
        self.values[key] = value

    def scan_iter(self, match, count):
        prefix = match.removesuffix("*")
        return (key for key in list(self.values) if key.startswith(prefix))

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)


def test_cache_key_changes_with_publication_and_range():
    assert cot_cache_key("history", 7, slug="gold", range_name="1y") != cot_cache_key(
        "history", 8, slug="gold", range_name="1y"
    )
    assert cot_cache_key("history", 8, slug="gold", range_name="1y") != cot_cache_key(
        "history", 8, slug="gold", range_name="5y"
    )


def test_invalidate_clears_memory_and_redis_prefix():
    redis = FakeRedis()
    cache = CotResponseCache(redis_client=redis)
    cache.set("cot:cot-v1:cot-positions-v1:7:catalog", "{}")

    cache.invalidate_all()

    assert cache.get("cot:cot-v1:cot-positions-v1:7:catalog") is None
    assert redis.values == {}
