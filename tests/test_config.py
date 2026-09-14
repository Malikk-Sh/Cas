from __future__ import annotations

from cas.config import Settings


def test_exchange_fee_overrides_are_parsed_as_rates() -> None:
    settings = Settings(_env_file=None, exchange_taker_fee_bps="bybit:10,okx:8.5,bad")

    assert settings.exchange_taker_fee_rates == {"bybit": 0.001, "okx": 0.00085}


def test_triangular_assets_star_means_auto_discovery() -> None:
    settings = Settings(_env_file=None, triangular_assets="*")

    assert settings.triangular_asset_set is None
