# Changelog

## 6.0.0-paper-foundation — 2026-08-25

- Added Freqtrade 2026.7 Gate.io isolated-futures dry-run config and multi-timeframe baseline hypothesis.
- Added expiring independent entry gate, risk governor, data freshness checks, SQLite audit/health history, structured rotating logs, and daily evidence check.
- Added fee-aware entry hurdle and per-trade net P&L/fee estimates using Freqtrade exchange fee fields with a conservative fallback.
- Added dependency-free localhost dashboard and validated pause/resume/safe/emergency controls.
- Added Windows setup/start/stop scripts and safety/unit tests.
- Live trading remains forbidden; profitability and long-run reliability remain unverified.
- Uses Gate.io's current Freqtrade/CCXT exchange identifier, `gate`.
