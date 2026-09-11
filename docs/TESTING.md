# Testing

`python -m unittest discover -s tests -v` checks checked-in safety, real-order rejection, dry-run enforcement, credential/public-bind rejection, stale-data halt, Kelly evidence/caps, volatility leverage behavior, opportunity penalties, SQLite migration, audit, and persisted state.

Freqtrade validation adds `list-strategies`, `test-pairlist`, backtesting, lookahead-analysis, and recursive-analysis. Browser acceptance must verify accurate heartbeat/offline/degraded states and all four control flows. Long soak and failure-injection tests are required before evaluating reliability; elapsed paper results are required before evaluating edge.
