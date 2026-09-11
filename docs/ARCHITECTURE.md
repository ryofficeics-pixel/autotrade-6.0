# Architecture

Runtime path: Gate.io public futures data → Freqtrade pairlists/strategy → expiring Autotrade risk gate → Freqtrade dry-run execution. Freqtrade persists trades; Autotrade persists risk state, equity snapshots, audits, and control history in a separate SQLite database.

`autotrade.py` is intentionally one process: supervisor loop, risk governor, Freqtrade REST adapter, audit store, and localhost HTTP server. Research is not in the trading process. The static dashboard sends commands only to the Autotrade API.

Decision authority is strict: strategy proposes, the independent runtime gate authorizes, and Freqtrade simulates. Missing or uncertain state denies new exposure. No Freqtrade core fork exists.
