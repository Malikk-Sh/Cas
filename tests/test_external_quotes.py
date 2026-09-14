from __future__ import annotations

import pytest

from cas.external_quotes import (
    StaticRateQuoteProvider,
    _json_path,
    _number,
    providers_from_json,
)


def test_json_path_and_number() -> None:
    assert _json_path(
        {"data": {"quote": {"amount": "1,234.56"}}},
        "data.quote.amount",
    ) == "1,234.56"
    assert _number("1,234.56 ETH") == pytest.approx(1234.56)
    assert _number("0,2676") == pytest.approx(0.2676)


@pytest.mark.asyncio
async def test_static_rate_provider() -> None:
    provider = StaticRateQuoteProvider(
        "x",
        {("BNB", "ETH"): 0.4},
    )
    quote = await provider.quote("BNB", "ETH", 2)
    assert quote is not None
    assert quote.output_amount == pytest.approx(0.8)


def test_provider_json() -> None:
    providers = providers_from_json(
        '[{"kind":"static_rate","name":"demo","rates":{"BNB:ETH":0.4}}]'
    )
    assert len(providers) == 1
    assert providers[0].name == "demo"
