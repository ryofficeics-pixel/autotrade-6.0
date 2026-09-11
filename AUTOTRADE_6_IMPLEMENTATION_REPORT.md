# Autotrade 6.0 Implementation Report

Report date: 25 August 2026 (Asia/Jakarta)

## Outcome

Autotrade 6.0 was built and started locally as a paper-only automated crypto-futures trading dashboard around Freqtrade 2026.7 and Gate USDT perpetual markets. The local dashboard is available at `http://127.0.0.1:8765` while the computer and services are running.

At final verification the supervisor was `RUNNING`, market data was `DATA_HEALTHY`, the risk governor was `REDUCED`, the entry gate was open, real orders were disabled, eight analyzed opportunities were visible, and one preserved dry-run trade was being managed.

No profitability or production-readiness claim is made. This is a safe paper-trading foundation and research hypothesis.

## Work completed

### Architecture and execution

- Implemented one small standard-library Python supervisor/API in `autotrade.py` instead of a duplicate exchange or execution stack.
- Pinned Freqtrade 2026.7 as the paper trading engine.
- Configured Gate using its current Freqtrade/CCXT identifier, `gate`, for isolated USDT perpetual futures.
- Configured a dynamic native pairlist using volume, age, precision, price, spread, and volatility filters.
- Added a dependency-free local web dashboard and Windows setup/start/stop scripts.
- Created the local Python virtual environment and installed all pinned runtime dependencies.
- Added concise architecture, security, risk, testing, operations, failure-recovery, research, and audit documentation.

### Hard paper-trading safety

- Enforced `PAPER`, `dry_run: true`, isolated futures margin, localhost-only APIs, and `allow_live_orders: false`.
- Added an execution adapter that always raises `NO REAL ORDERS` for any real-order submission.
- Made the strategy abort startup if dry-run is disabled.
- Rejected live credentials in checked-in JSON, public network binding, force-entry, and DCA/position adjustment.
- Stored supplied exchange credentials only in ignored local `.env`; their values are not included in source, logs, this report, or email.
- Added Host and Origin checks for local API commands.
- Added generated, local-only API authentication secrets and log redaction.

### Strategy and opportunity system

- Implemented `AutotradeBaseline`, a paper research hypothesis using 5-minute execution with 15-minute, 1-hour, and 4-hour trend context.
- Added long and short breakout signals, liquidity checks, abnormal-move/manipulation penalties, regime classification, and opportunity scoring.
- Added native cooldown, stop-loss, and maximum-drawdown protections.
- Prohibited DCA, averaging down, martingale, grid, pyramiding, and stop widening.
- Kept the initial scope to one strategy and one open-trade slot until evidence supports expansion.

### Risk governor

- Implemented `NORMAL`, `CAUTION`, `REDUCED`, and `HALTED` states.
- Added drawdown, daily-loss, consecutive-loss, market-data, manual-pause, emergency-stop, and safe-mode gates.
- Added 0.5% fixed-fractional bootstrap risk, reduced to 0.125% after safe resume.
- Added capped fractional Kelly only after at least 100 closed trades.
- Added a 2× paper leverage ceiling that falls toward 1× with volatility or worsening risk; safe resume uses 1×.
- Added an expiring 15-second runtime entry authorization so stalled supervision fails closed.

### Exchange fees, funding, stop loss, and take profit

- Confirmed Freqtrade calculates trade P&L net of trading fees and futures funding.
- Added per-trade estimated entry-plus-exit fee cost using Freqtrade's exchange fee fields when present.
- Added a conservative fallback of 0.075% taker fee per side plus a 0.05% slippage buffer.
- Added the fee hurdle to signal eligibility so expected candle movement must clear round-trip costs.
- Added fee-aware net P&L and fee estimate to the open-trade ticker and Active Trades table.
- Added a fee- and leverage-aware take-profit price beside the stop-loss price. It follows the shared ROI schedule: 6% initially, 2% after 240 minutes, and fee-aware breakeven after 720 minutes.

### Dashboard and 720p readability

- Bundled the official Open Sans variable font locally for reliable offline rendering.
- Forced Open Sans across all dashboard text, tables, and controls.
- Increased base text to 15px, table text to 13px, contrast, and font smoothing.
- Added a compact responsive layout specifically tested at 1280×720.
- Moved Active Trades above the equity curve so its full row is visible above the fold at 720p.
- Added the open-trade price ticker immediately below the primary equity/P&L metrics.
- Added equity, daily/total/unrealized P&L, drawdown, profit factor, win rate, risk state, strategy, regime, opportunities, health, loop count, and audit history.
- Added Pause New Entries, Resume Trading, Safe Mode, and guarded Emergency Stop controls.

### Health, persistence, and restart behavior

- Added a continuous five-second supervisor loop checking Freqtrade, Gate/market-data freshness, database writes, paper safety, and supervisor state.
- Added a visible monotonic health-loop counter and a 15-second heartbeat timeout.
- Added ten-minute persistent health audits, state-change audits, rotating structured logs, equity snapshots, and daily evidence checks.
- Added fail-closed handling for stale, missing, delayed beyond tolerance, or gapped candle data.
- Persisted Freqtrade paper trades in `user_data/tradesv3.dryrun.sqlite` and supervisor/audit state in `user_data/autotrade.sqlite`.
- Verified a real service restart preserved the existing `SKHYNIX/USDT:USDT` dry-run trade.
- Verified pause closed only the entry gate, kept the open trade present, and safe resume restored running state without changing the trade ID.
- Dashboard reloads do not restart Freqtrade or clear the trade database.

## Verification evidence

- Configuration validation: passed; output confirmed `PAPER mode, live orders forbidden`.
- Unit/safety suite: 14 of 14 tests passed.
- Freqtrade strategy discovery: `AutotradeBaseline` status `OK`.
- Gate native pairlist test: passed against current Gate public data; 11 pairs survived the configured filters in the final test.
- Browser acceptance at 1280×720: Open Sans loaded, 15px base size, no page-level horizontal overflow, status `RUNNING`, active trade fully visible, and stop/TP/fee fields present.
- Health loop acceptance: counter advanced across the timed check and continued every five seconds.
- Persistence acceptance: the same open paper trade survived full service restart and pause/resume.
- Network binding: dashboard listening only on `127.0.0.1:8765`; Freqtrade API listening only on `127.0.0.1:8080`.
- Current-session logs: zero supervisor errors and zero Freqtrade errors after the final restart.
- Credential scan: zero supplied exchange-secret matches outside ignored `.env` and excluded runtime storage.
- Available disk at final check: approximately 119.32 GiB.

## Files delivered

- `autotrade.py` — supervisor, health loop, risk governor, persistence, Freqtrade adapter, fee/TP calculations, and local API.
- `config.json` — paper safety, health, fee, take-profit, and risk settings.
- `dashboard/index.html` and `dashboard/OpenSans.ttf` — 720p local dashboard and bundled font.
- `user_data/config.json` — Gate futures dry-run, pairlist, persistence, and local Freqtrade API settings.
- `user_data/strategies/AutotradeBaseline.py` — multi-timeframe paper strategy and expiring entry gate.
- `scripts/setup_windows.bat`, `scripts/start_autotrade.bat`, `scripts/stop_autotrade.bat`, and `scripts/generate_env.py` — Windows lifecycle and secret generation.
- `tests/test_autotrade.py` — safety, risk, persistence, scoring, fee, TP, and health-loop tests.
- `README.md`, `.env.example`, `.gitignore`, `requirements.txt`, and the `docs` package.

## Not completed or not yet proven

- Strategy profitability is not proven. No meaningful elapsed paper sample exists yet.
- Historical candle downloads, full backtests, untouched out-of-sample tests, walk-forward tests, lookahead analysis, recursive analysis, fee/slippage sensitivity grids, and Monte Carlo trade-sequence analysis have not been completed.
- Long-duration soak testing and systematic failure injection have not been completed.
- The Gate credentials were loaded only for the isolated dry-run environment. Private-account permissions and live order ability were intentionally not exercised.
- Account fee tiers can change. Existing trades use the fee rates recorded by Freqtrade; the conservative fallback remains an estimate and should be compared with the user's current Gate fee endpoint/account tier.
- Funding-rate history and extreme funding scenarios have not yet been stress-tested.
- Automatic strategy discovery, Hyperopt, champion/challenger promotion, rollback orchestration, and multiple-strategy capital allocation were intentionally deferred until evidence exists.
- There is no real-trading path. Live orders remain deliberately impossible in this version.
- There is no Windows boot auto-start task. After a computer shutdown, run `scripts\start_autotrade.bat` to resume the local paper services; persisted dry-run trades will be reconciled from SQLite.
- While the computer is off, the local bot cannot monitor or manage even simulated positions.
- Supplied exchange credentials should still be rotated after handoff, as the user planned.

## Shutdown note

At the time this report was prepared, the local paper services were running smoothly. The requested computer shutdown is to be initiated only after this report has been successfully sent through Gmail. Shutdown will stop the local services; databases, audit history, logs, and the open dry-run trade record remain on disk for the next start.
