# Paper Trading

V1 is locked to Freqtrade dry-run with a 300 USDT simulated wallet and real Gate.io public market data. Multiple independent guards are checked at startup and in tests: PAPER app environment, `allow_live_orders=false`, Freqtrade `dry_run=true`, empty exchange credentials, loopback APIs, disabled force entry/DCA, rejecting execution adapter, and a paper-only strategy startup guard.

Paper results still depend on Freqtrade fill assumptions. Fees are included by Freqtrade; spread/order-book pricing is enabled. Funding, slippage sensitivity, missed/partial fills, latency, and liquidation scenarios need explicit research and stress reports before any paper result is treated as realistic.
