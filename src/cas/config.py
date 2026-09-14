from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CAS_",
        extra="ignore",
    )

    exchanges: str = "bybit,okx,kucoin"
    symbols: str = "BTC/USDT,ETH/USDT,BNB/USDT"
    notional_usdt: float = Field(default=1000.0, gt=0)
    depth_limit: int = Field(default=50, ge=5, le=500)
    min_net_profit_pct: float = Field(default=0.30)
    poll_interval_seconds: float = Field(default=15.0, ge=1.0)
    alert_cooldown_seconds: float = Field(default=120.0, ge=0.0)
    taker_fee_bps: float = Field(default=10.0, ge=0.0)
    exchange_taker_fee_bps: str = ""
    fixed_cost_bps: float = Field(default=5.0, ge=0.0)

    interexchange_enabled: bool = True

    triangular_enabled: bool = True
    triangular_anchor_asset: str = "USDT"
    triangular_assets: str = "BTC,ETH,BNB,SOL,XRP,ADA,DOGE"
    triangular_max_cycles: int = Field(default=200, ge=1, le=5000)
    triangular_min_net_profit_pct: float = Field(default=0.20)

    hybrid_enabled: bool = True
    hybrid_exchanges: str = "bybit"
    hybrid_anchor_asset: str = "USDT"
    hybrid_route_pairs: str = "BNB:ETH"
    hybrid_start_amount_usdt: float = Field(default=1000.0, gt=0)
    hybrid_min_net_profit_pct: float = Field(default=0.20)
    hybrid_max_external_premium_pct: float = Field(default=5.0, ge=0.0)
    hybrid_allow_suspicious: bool = False
    external_quote_providers_json: str = "[]"

    p2p_enabled: bool = False
    bybit_p2p_api_key: str = ""
    bybit_p2p_api_secret: str = ""
    bybit_p2p_testnet: bool = False
    p2p_fiat_currency: str = "RUB"
    p2p_token: str = "USDT"
    p2p_fiat_amount: float = Field(default=70_000.0, gt=0)
    p2p_min_completion_rate: float = Field(default=90.0, ge=0.0, le=100.0)
    p2p_min_recent_orders: int = Field(default=10, ge=0)
    p2p_require_verified_advertiser: bool = True
    p2p_page_size: int = Field(default=100, ge=1, le=300)

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def exchange_ids(self) -> list[str]:
        return [item.strip().lower() for item in self.exchanges.split(",") if item.strip()]

    @property
    def symbol_list(self) -> list[str]:
        return [item.strip().upper() for item in self.symbols.split(",") if item.strip()]

    @property
    def taker_fee_rate(self) -> float:
        return self.taker_fee_bps / 10_000

    @property
    def fixed_cost_rate(self) -> float:
        return self.fixed_cost_bps / 10_000

    @property
    def exchange_taker_fee_rates(self) -> dict[str, float]:
        rates: dict[str, float] = {}
        for item in self.exchange_taker_fee_bps.split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            exchange_id, raw_bps = item.split(":", 1)
            try:
                bps = float(raw_bps.strip())
            except ValueError:
                continue
            if bps < 0:
                continue
            rates[exchange_id.strip().lower()] = bps / 10_000
        return rates

    @property
    def triangular_asset_set(self) -> set[str] | None:
        value = self.triangular_assets.strip()
        if not value or value == "*":
            return None
        return {item.strip().upper() for item in value.split(",") if item.strip()}

    @property
    def hybrid_exchange_ids(self) -> list[str]:
        return [
            item.strip().lower()
            for item in self.hybrid_exchanges.split(",")
            if item.strip()
        ]

    @property
    def hybrid_route_pair_list(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for item in self.hybrid_route_pairs.split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            first, second = item.split(":", 1)
            first = first.strip().upper()
            second = second.strip().upper()
            if first and second and first != second:
                pairs.append((first, second))
        return pairs


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
