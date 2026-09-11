# Strategy System

`AutotradeBaseline` is a research hypothesis: 5-minute breakout execution confirmed by 15-minute, 1-hour, and 4-hour trend context. It supports long and short futures, rejects poor relative volume and abnormal single-candle moves, and publishes regime/opportunity columns for the dashboard.

Only this family is active. More strategies would add correlation and selection complexity before evidence exists. Parameters are bootstrap values to test, not validated optimums. Signals are vectorized and the strategy is backtestable with native Freqtrade tools.
