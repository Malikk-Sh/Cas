# CAS — Crypto Arbitrage Scanner

Поиск межбиржевых spot-связок по публичным стаканам с учетом глубины, комиссий и Telegram-уведомлений.

Подробная инструкция на русском: [`docs/README.ru.md`](docs/README.ru.md).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cas-scanner
```

The scanner does not place trades and does not require exchange API keys.
