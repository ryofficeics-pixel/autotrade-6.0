# Risk Management

The supervisor owns NORMAL, CAUTION, REDUCED, and HALTED states. Drawdown, daily loss, consecutive losses, manual controls, and data health can reduce or close the entry gate. Strategies cannot override it.

Sizing begins at 0.5% planned equity risk per trade. Fractional Kelly requires at least 100 closed trades, remains capped below 1%, and is subordinate to the active state. Leverage is capped at 2× in the paper bootstrap and falls toward 1× as volatility or risk worsens. These are deliberately conservative test ceilings, not empirically final values.

Equity compounds because stake sizing reads current dry-run equity. No DCA, averaging down, martingale, grid, pyramiding, stop widening, or quota-driven risk is present.

Every simulated trade uses Freqtrade's fee-inclusive P&L (including futures funding), and the dashboard separately estimates the entry-plus-exit trading-fee cost from the exchange rates stored on the trade. Signals must also clear a conservative round-trip hurdle: 0.075% fallback taker fee per side plus a 0.05% slippage buffer. Account-specific rates take precedence in the trade record.
