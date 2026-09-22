from app.utils.file_hashing import canonical_json_sha256


def test_canonical_json_sha256_is_stable_across_mapping_order():
    expected = "ecf9e98ec0641e23113ff3ce8bdc78d0ddd249886517fd4a7f68cc83d4e65667"

    assert canonical_json_sha256({"b": "x", "a": 1}) == expected
