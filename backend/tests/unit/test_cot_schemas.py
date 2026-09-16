from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.cot import CotCatalogResponse, CotHistoryResponse
from tests.unit.test_cot_queries import service


def test_history_contract_preserves_integer_positions_exactly():
    response = CotHistoryResponse.from_view(service().history("sp-500", "1y"))

    payload = response.model_dump(mode="json")

    assert payload["weeks"][-1]["positions"][0]["long"] == 1590
    assert isinstance(payload["weeks"][-1]["positions"][0]["long"], int)


def test_history_contract_rejects_extra_nonfinite_and_inconsistent_percentile():
    payload = CotHistoryResponse.from_view(
        service().history("sp-500", "1y")
    ).model_dump(mode="python")
    extra = deepcopy(payload)
    extra["unexpected"] = True
    with pytest.raises(ValidationError):
        CotHistoryResponse.model_validate(extra)

    nonfinite = deepcopy(payload)
    nonfinite["weeks"][0]["positions"][0]["net_pct_open_interest"] = float("inf")
    with pytest.raises(ValidationError):
        CotHistoryResponse.model_validate(nonfinite)

    inconsistent = deepcopy(payload)
    inconsistent["weeks"][0]["positions"][0]["percentile_status"] = "available"
    inconsistent["weeks"][0]["positions"][0]["percentile_3y"] = None
    with pytest.raises(ValidationError):
        CotHistoryResponse.model_validate(inconsistent)


def test_catalog_contract_rejects_duplicate_instruments():
    payload = CotCatalogResponse.from_view(service().catalog()).model_dump(mode="python")
    payload["instruments"].append(deepcopy(payload["instruments"][0]))

    with pytest.raises(ValidationError, match="duplicate"):
        CotCatalogResponse.model_validate(payload)
