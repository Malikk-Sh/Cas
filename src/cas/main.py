from __future__ import annotations

import asyncio
import logging
import time

from cas.config import get_settings
from cas.exchanges import ExchangePool
from cas.notifier import TelegramNotifier
from cas.scanner import ArbitrageScanner
from cas.triangular import TriangularArbitrageScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cas")


async def run() -> None:
    settings = get_settings()
    pool = ExchangePool(settings.exchange_ids)
    notifier = TelegramNotifier(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
    )
    interexchange_scanner = ArbitrageScanner(
        pool,
        notional_quote=settings.notional_usdt,
        taker_fee_rate=settings.taker_fee_rate,
        fixed_cost_rate=settings.fixed_cost_rate,
        depth_limit=settings.depth_limit,
        exchange_fee_rates=settings.exchange_taker_fee_rates,
    )
    triangular_scanner = TriangularArbitrageScanner(
        pool,
        anchor_asset=settings.triangular_anchor_asset,
        start_amount=settings.notional_usdt,
        taker_fee_rate=settings.taker_fee_rate,
        fixed_cost_rate=settings.fixed_cost_rate,
        depth_limit=settings.depth_limit,
        allowed_assets=settings.triangular_asset_set,
        max_cycles=settings.triangular_max_cycles,
        exchange_fee_rates=settings.exchange_taker_fee_rates,
    )
    last_alert_at: dict[str, float] = {}

    logger.info(
        "Starting scanner: exchanges=%s interexchange=%s triangular=%s notional=%.2f",
        ",".join(settings.exchange_ids),
        settings.interexchange_enabled,
        settings.triangular_enabled,
        settings.notional_usdt,
    )

    await pool.start()
    try:
        while True:
            started_at = time.monotonic()

            if settings.interexchange_enabled:
                opportunities = await interexchange_scanner.scan(settings.symbol_list)
                actionable = [
                    item
                    for item in opportunities
                    if item.net_profit_pct >= settings.min_net_profit_pct
                ]
            else:
                actionable = []

            if actionable:
                best = actionable[0]
                logger.info(
                    "Interexchange best: %s | buy %s %.8f -> sell %s %.8f | net %.2f (%.3f%%)",
                    best.symbol,
                    best.buy_exchange,
                    best.buy_vwap,
                    best.sell_exchange,
                    best.sell_vwap,
                    best.net_profit_quote,
                    best.net_profit_pct,
                )
            elif settings.interexchange_enabled:
                logger.info(
                    "No interexchange opportunity above %.3f%%",
                    settings.min_net_profit_pct,
                )

            if settings.triangular_enabled:
                triangular = await triangular_scanner.scan(settings.exchange_ids)
                triangular_actionable = [
                    item
                    for item in triangular
                    if item.net_profit_pct >= settings.triangular_min_net_profit_pct
                ]
            else:
                triangular_actionable = []

            if triangular_actionable:
                best_tri = triangular_actionable[0]
                logger.info(
                    "Triangular best: %s | %s | net %.4f %s (%.3f%%)",
                    best_tri.exchange,
                    " -> ".join(best_tri.path),
                    best_tri.net_profit_quote,
                    best_tri.anchor_asset,
                    best_tri.net_profit_pct,
                )
            elif settings.triangular_enabled:
                logger.info(
                    "No triangular opportunity above %.3f%%",
                    settings.triangular_min_net_profit_pct,
                )

            now = time.monotonic()
            for opportunity in actionable:
                last_sent = last_alert_at.get(opportunity.key, 0.0)
                if now - last_sent < settings.alert_cooldown_seconds:
                    continue
                try:
                    await notifier.send_opportunity(opportunity)
                    if notifier.enabled:
                        last_alert_at[opportunity.key] = now
                except Exception as exc:
                    logger.warning("Telegram interexchange alert failed: %s", exc)

            for opportunity in triangular_actionable:
                last_sent = last_alert_at.get(opportunity.key, 0.0)
                if now - last_sent < settings.alert_cooldown_seconds:
                    continue
                try:
                    await notifier.send_triangular_opportunity(opportunity)
                    if notifier.enabled:
                        last_alert_at[opportunity.key] = now
                except Exception as exc:
                    logger.warning("Telegram triangular alert failed: %s", exc)

            elapsed = time.monotonic() - started_at
            await asyncio.sleep(max(0.0, settings.poll_interval_seconds - elapsed))
    finally:
        await pool.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped")


if __name__ == "__main__":
    main()
