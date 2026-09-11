# Autotrade 6.0

Autotrade 6.0 is a paper-only, local Windows control layer around Freqtrade 2026.7 for Gate.io USDT perpetual futures. Freqtrade owns market data, dynamic pairlists, strategy evaluation, simulated execution, and trade persistence. Autotrade owns the independent entry gate, risk state, health/audit history, and dashboard.

> **NO REAL ORDERS.** V1 rejects non-paper configuration at startup, contains no live-mode UI, stores no exchange credentials, and the strategy aborts if Freqtrade is not in dry-run mode.

## Quick start (Windows)

Run from Command Prompt:

```bat
scripts\setup_windows.bat
scripts\start_autotrade.bat
```

Open <http://127.0.0.1:8765>. Stop cleanly with:

```bat
scripts\stop_autotrade.bat
```

Setup creates `.venv`, installs the pinned Freqtrade release, generates local API credentials in ignored `.env`, validates both configurations, and runs the safety suite. Gate.io public market data needs internet access; paper mode needs no exchange API key.

## Safety flow

```text
Signal -> strategy.confirm_trade_entry()
       -> fresh supervisor runtime gate required
       -> risk/data/manual gates required
       -> Freqtrade dry-run simulation
```

The runtime gate expires after 15 seconds. A stopped supervisor, stale/missing candles, an unsafe drawdown, invalid configuration, or unavailable authenticated Freqtrade state therefore blocks new exposure. Existing paper positions remain under Freqtrade exit logic when entries are paused. Resume always stays in PAPER and enters the reduced-risk envelope.

## Bootstrap status

The checked-in strategy and numeric limits are conservative **paper research hypotheses**, not validated edge and not a profitability claim. Fractional Kelly stays unavailable until at least 100 closed trades; fixed fractional risk is used first. The 3% daily figure appears only as an aspiration in the UI and never changes entries, size, or leverage. Freqtrade's trade P&L is net of exchange fees and futures funding; the dashboard also exposes estimated per-trade fee cost. Until account-specific rates are present on a trade, the entry hurdle conservatively assumes 0.075% taker fee per side plus 0.05% slippage.

The deliberately minimal V1 has one strategy family and one open-trade slot. Add strategies, broader allocation, automated promotion, and bounded Hyperopt only after backtest, out-of-sample, walk-forward, lookahead/recursive, and paper evidence exist. This follows the project's success order: survival, validated edge, compounding, then profit target.

## Commands

```powershell
.\.venv\Scripts\python.exe autotrade.py validate
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m freqtrade test-pairlist --config user_data/config.json
.\.venv\Scripts\python.exe -m freqtrade list-strategies --config user_data/config.json
```

For backtesting, first download futures candles for `5m 15m 1h 4h`, then use Freqtrade's native `backtesting`, `lookahead-analysis`, and `recursive-analysis` commands. Do not tune or promote against the same period used for final evaluation.

## Files

- `autotrade.py` — supervisor, risk governor, safety validation, SQLite migrations, Freqtrade API adapter, and local API.
- `dashboard/index.html` — dependency-free control/observability dashboard.
- `user_data/config.json` — Gate.io futures dry-run and native dynamic pairlist.
- `user_data/strategies/AutotradeBaseline.py` — multi-timeframe long/short breakout hypothesis with an expiring independent entry gate and no DCA.
- `tests/test_autotrade.py` — runnable money-path and configuration safety checks.
- `docs/` — concise architecture, operations, research, failure, security, and audit records.

## Current verification boundary

Static/unit validation can run locally. Real Gate.io candle freshness, pair eligibility, simulated fills, funding, API reconciliation, long soak behavior, and strategy profitability require the installed Freqtrade runtime plus market history and elapsed paper time. They must not be claimed from generated code or a short test session.
