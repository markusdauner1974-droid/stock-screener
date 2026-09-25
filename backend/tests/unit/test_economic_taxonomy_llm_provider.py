from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.economic_exposure_extraction import RetryableProviderError
from app.services.economic_taxonomy_llm_provider import EconomicTaxonomyLLMProvider
from app.services.llm.llm_service import LLMPreDispatchError


class _LLM:
    def __init__(self, result):
        self.preset = SimpleNamespace(
            primary=SimpleNamespace(model_id="minimax/MiniMax-M2.7")
        )
        self.result = result
        self.calls = []

    async def completion(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _response(payload: str):
    return SimpleNamespace(
        id="request-1",
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
    )


def test_provider_uses_single_metered_json_dispatch():
    llm = _LLM(_response('{"status":"successful_empty","candidates":[]}'))

    result = EconomicTaxonomyLLMProvider(llm).extract(
        evidence={"original_text": "No economic theme."},
        policy_version="economic-extraction-v1",
    )

    assert result == {
        "status": "successful_empty",
        "candidates": [],
        "provider_request_id": "request-1",
        "actual_cost": 0,
    }
    assert len(llm.calls) == 1
    assert llm.calls[0]["metered"] is True
    assert llm.calls[0]["allow_fallbacks"] is False
    assert llm.calls[0]["num_retries"] == 0


def test_provider_configuration_failure_is_retryable_before_dispatch():
    provider = EconomicTaxonomyLLMProvider(
        _LLM(LLMPreDispatchError("missing credentials"))
    )

    with pytest.raises(RetryableProviderError) as error:
        provider.extract(evidence={}, policy_version="economic-extraction-v1")

    assert error.value.dispatch_confirmed is False
