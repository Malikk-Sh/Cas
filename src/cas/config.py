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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
