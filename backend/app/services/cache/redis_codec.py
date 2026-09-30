"""Data-only codecs for Redis cache payloads (issue #434).

Cache payloads used to be pickled, so anyone able to write to the cache Redis
could run code in API and worker processes. These codecs only ever build plain
numbers, strings, dates and numpy numeric buffers.

Every payload starts with a magic prefix. Anything else, including a legacy
pickle, decodes to ``None`` and is treated as a cache miss: the DB tier
refills it in the new format, so no pickle decoder is ever needed.
"""

from __future__ import annotations

import json
import struct
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

_FRAME_MAGIC = b"SSCF1\n"
_DICT_MAGIC = b"SSCD1\n"
_HEADER_LEN = struct.Struct("<I")
_NUMERIC_KINDS = frozenset("fiub")
_INDEX_UNITS = frozenset({"s", "ms", "us", "ns"})
_DATE_TAG = "$date"
_DATETIME_TAG = "$datetime"


# ── Price frames: JSON header + raw numpy column buffers ─────────────────


def _numeric_column(frame: pd.DataFrame, name: Any) -> np.ndarray:
    values = frame[name].to_numpy()
    if values.dtype.kind not in _NUMERIC_KINDS:
        try:
            values = pd.to_numeric(frame[name], errors="raise").to_numpy(dtype="float64")
        except (TypeError, ValueError) as exc:
            raise TypeError(f"column {name!r} is not numeric") from exc
    return np.ascontiguousarray(values)


def encode_frame(frame: pd.DataFrame) -> bytes:
    """Encode an OHLCV frame with a DatetimeIndex; raise TypeError otherwise."""
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError(f"expected a DatetimeIndex, got {type(index).__name__}")
    if not all(isinstance(name, str) for name in frame.columns):
        raise TypeError("column names must be strings")
    if not frame.columns.is_unique:
        raise TypeError("column names must be unique")
    if index.name is not None and not isinstance(index.name, str):
        raise TypeError("index name must be a string")
    columns = [(name, _numeric_column(frame, name)) for name in frame.columns]
    header = json.dumps({
        "rows": len(frame),
        "unit": index.unit,
        "tz": str(index.tz) if index.tz is not None else None,
        "freq": index.freqstr,
        "name": index.name,
        "columns": [[name, values.dtype.str] for name, values in columns],
        "attrs": _to_json(frame.attrs),  # e.g. the price cache's coverage stamp
    }).encode()
    return b"".join([
        _FRAME_MAGIC,
        _HEADER_LEN.pack(len(header)),
        header,
        index.asi8.tobytes(),
        *(values.tobytes() for _, values in columns),
    ])


def decode_frame(data: bytes | None) -> pd.DataFrame | None:
    """Decode a frame; ``None`` for payloads in any other format (a cache miss).

    A payload in this format that is malformed raises ValueError, which the
    cache readers also treat as a miss.
    """
    if not data or not data.startswith(_FRAME_MAGIC):
        return None
    try:
        return _decode_frame(data)
    except (struct.error, KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"malformed frame payload: {exc}") from exc


def _decode_frame(data: bytes) -> pd.DataFrame:
    offset = len(_FRAME_MAGIC)
    (header_len,) = _HEADER_LEN.unpack_from(data, offset)
    offset += _HEADER_LEN.size
    meta = json.loads(data[offset:offset + header_len], object_hook=_from_json)
    offset += header_len
    rows = int(meta["rows"])
    if rows < 0:
        raise ValueError("negative row count in frame payload")
    unit = meta["unit"]
    if unit not in _INDEX_UNITS:
        raise ValueError(f"unsupported index unit {unit!r}")

    def take(dtype: np.dtype) -> np.ndarray:
        nonlocal offset
        if dtype.kind not in _NUMERIC_KINDS:
            raise ValueError(f"unsupported column dtype {dtype.str!r}")
        size = dtype.itemsize * rows
        if offset + size > len(data):
            raise ValueError("truncated frame payload")
        values = np.frombuffer(data, dtype=dtype, count=rows, offset=offset)
        offset += size
        return values

    stamps = take(np.dtype("<i8")).view(f"datetime64[{unit}]")
    columns = {name: take(np.dtype(dtype)) for name, dtype in meta["columns"]}
    if offset != len(data):
        raise ValueError("unexpected trailing bytes in frame payload")
    index = pd.DatetimeIndex(stamps, name=meta["name"])
    if meta["tz"] is not None:
        index = index.tz_localize("UTC").tz_convert(meta["tz"])
    if meta.get("freq"):
        index.freq = meta["freq"]  # pandas checks it matches the stamps
    frame = pd.DataFrame(columns, index=index)
    frame.attrs = meta.get("attrs") or {}
    return frame


# ── Dict payloads: JSON with tagged dates ────────────────────────────────


def _to_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, np.generic):
        return _to_json(value.item())
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, datetime):  # before date: datetime subclasses date
        return {_DATETIME_TAG: value.isoformat()}
    if isinstance(value, date):
        return {_DATE_TAG: value.isoformat()}
    if isinstance(value, dict):
        encoded = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"dict key {key!r} is not a string")
            encoded[key] = _to_json(item)
        return encoded
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    raise TypeError(f"cannot cache a {type(value).__name__} value")


def _from_json(obj: dict) -> Any:
    if len(obj) == 1:
        if _DATE_TAG in obj:
            return date.fromisoformat(obj[_DATE_TAG])
        if _DATETIME_TAG in obj:
            return datetime.fromisoformat(obj[_DATETIME_TAG])
    return obj


def encode_dict(payload: dict) -> bytes:
    """Encode a JSON-like dict (dates kept as dates); raise TypeError otherwise."""
    return _DICT_MAGIC + json.dumps(_to_json(payload), separators=(",", ":")).encode()


def decode_dict(data: bytes | None) -> dict | None:
    """Decode a dict; ``None`` for payloads in any other format (a cache miss)."""
    if not data or not data.startswith(_DICT_MAGIC):
        return None
    return json.loads(data[len(_DICT_MAGIC):], object_hook=_from_json)
