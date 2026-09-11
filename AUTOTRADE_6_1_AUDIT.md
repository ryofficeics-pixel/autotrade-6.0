# Autotrade 6.1 audit

## Fixed

- Critical: a global runtime gate authorized every pair. The runtime format now has an immutable-style global decision plus an explicit decision for every current whitelist pair; the strategy requires both gates.
- Critical: safety scanning silently capped at eight pairs and dropped per-pair failures. It now evaluates the full whitelist and records a denial for missing or failed pair data.
- Critical: refresh and owner commands could overlap. Refresh and commands now share one reentrant transition lock; shutdown joins the supervisor before SQLite closes.
- Critical: `/ping` only proved reachability. The adapter now uses Freqtrade 2026.7's installed `FtRestClient.health()`.
- High: high-water equity was sampled only periodically. It is persisted on each successful refresh.
- High: GTC entries survived a newly unsafe gate. `check_entry_timeout()` now cancels only entry orders when the global or matching pair gate closes.
- High: Kelly code was presented despite not driving sizing. Default sizing remains fixed fractional; Kelly is not used by the strategy.

## Upstream reuse

Uses Freqtrade's `FtRestClient`, `health`, `stopbuy`, `check_entry_timeout`, native pairlists, native research commands, and the official Docker image. No order manager or backtest engine was added.

## Remaining blockers

No live mode was added. Gate connectivity, lookahead/recursive analysis, full Docker runtime, order-cancellation integration against a running Freqtrade instance, and research profitability remain unverified. The strategy is an unvalidated paper hypothesis.
