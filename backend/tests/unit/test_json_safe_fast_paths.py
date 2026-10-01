"""json_safe exact-type fast paths (#465) keep the original output exactly."""

from __future__ import annotations

import enum
import json
import math
from collections import OrderedDict
from datetime import date, datetime, timezone
from numbers import Integral, Real
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import app.infra.serialization as serialization
from app.infra.serialization import json_safe

_SNAPSHOTS = Path(__file__).parent / "golden" / "snapshots"


def _reference_json_safe(value, *, stringify_keys=True):
    """The implementation before #465, kept verbatim as the oracle."""
    if isinstance(value, np.ndarray):
        value = value.tolist()
    elif isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, dict):
        return {
            str(key) if stringify_keys else key: _reference_json_safe(item, stringify_keys=stringify_keys)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_reference_json_safe(item, stringify_keys=stringify_keys) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _numpyify(value, counter=[0]):
    if isinstance(value, dict):
        return {k: _numpyify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_numpyify(v) for v in value]
    if value is None or isinstance(value, (bool, str)):
        return value
    counter[0] += 1
    if counter[0] % 2:
        return np.float64(value) if isinstance(value, float) else np.int64(value)
    return value


class _Level(enum.IntEnum):
    LOW = 1


class _Ratio(float):
    pass


_EDGE_CASES = {
    "nan": float("nan"),
    "inf": float("inf"),
    "neg_inf": -math.inf,
    "np_nan": np.float64("nan"),
    "np_inf": np.float32("inf"),
    "np_f32": np.float32(0.1),
    "np_i32": np.int32(7),
    "np_u8": np.uint8(200),
    "np_bool": np.bool_(True),
    "bool": False,
    "int_enum": _Level.LOW,
    "float_subclass": _Ratio(2.5),
    "big_int": 2**70,
    "pd_na": pd.NA,
    "nat": pd.NaT,
    "timestamp": pd.Timestamp("2026-09-30 16:00", tz="America/New_York"),
    "date": date(2026, 9, 30),
    "datetime": datetime(2026, 9, 30, 20, tzinfo=timezone.utc),
    "array": np.array([1.0, np.nan, 3.0]),
    "tuple": (1, 2.5, None),
    "set": {3},
    "ordered": OrderedDict([("b", 1), ("a", np.float64(2.0))]),
    "nested": {1: [{"x": np.int64(3)}, (np.float64("nan"),)], (1, 2): "tuple-key"},
    "object": object,
}


def _corpus():
    payloads = [_numpyify(json.loads(path.read_text())) for path in sorted(_SNAPSHOTS.glob("scanner_*.json"))]
    return {"details": payloads, "edges": _EDGE_CASES}


@pytest.mark.parametrize("stringify_keys", [True, False])
def test_json_safe_output_matches_the_original_implementation(stringify_keys):
    corpus = _corpus()

    actual = json_safe(corpus, stringify_keys=stringify_keys)

    # Plain equality works: json_safe turns every NaN into None.
    assert actual == _reference_json_safe(corpus, stringify_keys=stringify_keys)
    assert [type(value) for value in actual["edges"].values()] == [
        type(value)
        for value in _reference_json_safe(_EDGE_CASES, stringify_keys=stringify_keys).values()
    ]


def test_plain_leaves_skip_the_generic_numpy_conversion(monkeypatch):
    def generic_path(value):
        raise AssertionError(f"plain value took the generic path: {value!r}")

    monkeypatch.setattr(serialization, "_numpy_native", generic_path)
    payload = {
        "score": 82.5,
        "count": 3,
        "label": "VCP",
        "ready": True,
        "missing": None,
        "series": [1.0, 2.0, float("nan")],
        "pair": (np.float64(1.5), np.int64(2), np.bool_(False)),
    }

    assert json_safe(payload) == {
        "score": 82.5,
        "count": 3,
        "label": "VCP",
        "ready": True,
        "missing": None,
        "series": [1.0, 2.0, None],
        "pair": [1.5, 2, False],
    }
