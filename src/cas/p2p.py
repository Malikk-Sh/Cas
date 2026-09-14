from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable

from pybit.unified_trading import HTTP


@dataclass(slots=True, frozen=True)
class P2PQuote:
    provider: str
    fiat_currency: str
    token: str
    fiat_amount: float
    token_amount: float
    price: float
    ad_id: str
    advertiser: str
    completion_rate: float
    recent_orders: int
    auth_tags: tuple[str, ...]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def select_best_p2p_ad(
    items: Iterable[dict[str, Any]],
    *,
    fiat_amount: float,
    fiat_currency: str,
    token: str,
    min_completion_rate: float = 0.0,
    min_recent_orders: int = 0,
    require_verified_advertiser: bool = False,
) -> P2PQuote | None:
    candidates: list[P2PQuote] = []
    fiat = fiat_currency.upper()
    coin = token.upper()

    for item in items:
        if str(item.get("currencyId", "")).upper() != fiat:
            continue
        if str(item.get("tokenId", "")).upper() != coin:
            continue
        if item.get("isOnline") is False:
            continue

        price = _as_float(item.get("price"))
        available_token = _as_float(item.get("lastQuantity"))
        min_amount = _as_float(item.get("minAmount"))
        max_amount = _as_float(item.get("maxAmount"))
        completion_rate = _as_float(item.get("recentExecuteRate"))
        recent_orders = _as_int(item.get("recentOrderNum"))
        auth_tags = tuple(str(tag).upper() for tag in (item.get("authTag") or []))

        if price <= 0 or available_token <= 0:
            continue
        if min_amount > 0 and fiat_amount < min_amount:
            continue
        if max_amount > 0 and fiat_amount > max_amount:
            continue
        token_amount = fiat_amount / price
        if token_amount > available_token:
            continue
        if completion_rate < min_completion_rate:
            continue
        if recent_orders < min_recent_orders:
            continue
        if require_verified_advertiser and not ({"VA", "BA"} & set(auth_tags)):
            continue

        candidates.append(
            P2PQuote(
                provider="bybit_p2p",
                fiat_currency=fiat,
                token=coin,
                fiat_amount=fiat_amount,
                token_amount=token_amount,
                price=price,
                ad_id=str(item.get("id", "")),
                advertiser=str(item.get("nickName", "")),
                completion_rate=completion_rate,
                recent_orders=recent_orders,
                auth_tags=auth_tags,
            )
        )

    if not candidates:
        return None
    candidates.sort(
        key=lambda quote: (
            quote.price,
            -quote.completion_rate,
            -quote.recent_orders,
        )
    )
    return candidates[0]


class BybitP2PSource:
    """Read-only source for the best eligible Bybit P2P ad.

    The official Bybit P2P endpoint is authenticated. This class never places
    an order; it only calls get_online_ads().
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        fiat_currency: str = "RUB",
        token: str = "USDT",
        testnet: bool = False,
        min_completion_rate: float = 0.0,
        min_recent_orders: int = 0,
        require_verified_advertiser: bool = False,
        page_size: int = 100,
    ) -> None:
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.fiat_currency = fiat_currency.upper()
        self.token = token.upper()
        self.testnet = testnet
        self.min_completion_rate = min_completion_rate
        self.min_recent_orders = min_recent_orders
        self.require_verified_advertiser = require_verified_advertiser
        self.page_size = max(1, min(page_size, 300))
        self._session: HTTP | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _get_session(self) -> HTTP:
        if not self.enabled:
            raise RuntimeError("Bybit P2P API key/secret are not configured")
        if self._session is None:
            self._session = HTTP(
                testnet=self.testnet,
                api_key=self.api_key,
                api_secret=self.api_secret,
            )
        return self._session

    async def quote(self, fiat_amount: float) -> P2PQuote | None:
        session = self._get_session()
        response = await asyncio.to_thread(
            session.get_online_ads,
            tokenId=self.token,
            currencyId=self.fiat_currency,
            side="0",
            page="1",
            size=str(self.page_size),
        )
        result = response.get("result") or {}
        items = result.get("items") or []
        return select_best_p2p_ad(
            items,
            fiat_amount=fiat_amount,
            fiat_currency=self.fiat_currency,
            token=self.token,
            min_completion_rate=self.min_completion_rate,
            min_recent_orders=self.min_recent_orders,
            require_verified_advertiser=self.require_verified_advertiser,
        )
