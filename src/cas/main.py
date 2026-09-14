from __future__ import annotations

import asyncio
import logging
import time

from cas.config import get_settings
from cas.exchanges import ExchangePool
from cas.notifier import TelegramNotifier
from cas.scanner import ArbitrageScanner

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
    scanner = ArbitrageScanner(
        pool,
        notional_quote=settings.notional_usdt,
        taker_fee_rate=settings.taker_fee_rate,
        fixed_cost_rate=settings.fixed_cost_rate,
        depth_limit=settings.depth_limit,
    )
    last_alert_at: dict[str, float] = {}

    logger.info(
        "Starting scanner: exchanges=%s symbols=%s notional=%.2f",
        ",".join(settings.exchange_ids),
        ",".join(settings.symbol_list),
        settings.notional_usdt,
    )

    await pool.start()
    try:
        while True:
            started_at = time.monotonic()
            opportunities = await scanner.scan(settings.symbol_list)
            actionable = [
                item
                for item in opportunities
                if item.net_profit_pct >= settings.min_net_profit_pct
            ]

            if actionable:
                best = actionable[0]
                logger.info(
                    "Best: %s | buy %s %.8f -> sell %s %.8f | net %.2f (%.3f%%)",
                    best.symbol,
                    best.buy_exchange,
                    best.buy_vwap,
                    best.sell_exchange,
                    best.sell_vwap,
                    best.net_profit_quote,
                    best.net_profit_pct,
                )
            else:
                logger.info("No opportunity above %.3f%%", settings.min_net_profit_pct)

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
                    logger.warning("Telegram alert failed: %s", exc)

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
