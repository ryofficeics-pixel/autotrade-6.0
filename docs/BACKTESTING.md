# Backtesting

Use native Freqtrade commands with Gate.io futures candles for every informative timeframe. Separate train, validation, and untouched out-of-sample windows. Enable protections and include exchange fees; run multiple regimes, walk-forward windows, lookahead-analysis, recursive-analysis, parameter-neighborhood checks, and fee/slippage sensitivity.

Report net profit, maximum drawdown, expectancy, profit factor, win rate, trades, Sharpe, Sortino, average duration, largest loss, losing streak, and fee impact. Use Gate/Freqtrade fee data when available and stress at least the configured conservative 0.075% taker rate on both entry and exit plus 0.05% slippage. Add trade-sequence Monte Carlo before changing risk caps. The 3% daily aspiration is a comparison line, never an optimizer target.
