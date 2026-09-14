from __future__ import annotations

import pytest

from cas.p2p import select_best_p2p_ad


def _ad(
    *,
    ad_id: str,
    price: str,
    execute_rate: str = "97",
    orders: str = "150",
    auth_tag: list[str] | None = None,
) -> dict:
    return {
        "id": ad_id,
        "tokenId": "USDT",
        "currencyId": "RUB",
        "isOnline": True,
        "price": price,
        "lastQuantity": "1000",
        "minAmount": "1000",
        "maxAmount": "100000",
        "recentExecuteRate": execute_rate,
        "recentOrderNum": orders,
        "authTag": auth_tag or ["VA"],
        "nickName": ad_id,
    }


def test_selects_cheapest_eligible_verified_ad() -> None:
    items = [
        _ad(ad_id="cheap-but-low-rate", price="83.5", execute_rate="80"),
        _ad(ad_id="good", price="84", execute_rate="97", orders="150"),
        _ad(ad_id="more-expensive", price="84.5", execute_rate="99", orders="500"),
    ]

    quote = select_best_p2p_ad(
        items,
        fiat_amount=70_000,
        fiat_currency="RUB",
        token="USDT",
        min_completion_rate=90,
        min_recent_orders=10,
        require_verified_advertiser=True,
    )

    assert quote is not None
    assert quote.ad_id == "good"
    assert quote.price == pytest.approx(84.0)
    assert quote.token_amount == pytest.approx(70_000 / 84.0)


def test_rejects_unverified_when_verification_required() -> None:
    quote = select_best_p2p_ad(
        [_ad(ad_id="general", price="83", auth_tag=["GA"])],
        fiat_amount=70_000,
        fiat_currency="RUB",
        token="USDT",
        min_completion_rate=90,
        min_recent_orders=10,
        require_verified_advertiser=True,
    )
    assert quote is None


def test_rejects_ad_outside_fiat_limits() -> None:
    item = _ad(ad_id="limited", price="84")
    item["maxAmount"] = "50000"
    quote = select_best_p2p_ad(
        [item],
        fiat_amount=70_000,
        fiat_currency="RUB",
        token="USDT",
    )
    assert quote is None
