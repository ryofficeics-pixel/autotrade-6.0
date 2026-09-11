# Trading Engine

Freqtrade 2026.7 is the authoritative engine for Gate.io futures support, OHLCV, order books used by pricing, dynamic pairlists, protections, informative timeframes, signals, leverage callbacks, stake callbacks, dry-run fills, and trade storage.

Autotrade does not submit orders. `PaperExecutionAdapter.submit_real_order()` always raises. The strategy's `bot_start()` also aborts outside dry-run. Position adjustment is disabled in both config and strategy; the lifecycle is one entry, management, and full exit.
