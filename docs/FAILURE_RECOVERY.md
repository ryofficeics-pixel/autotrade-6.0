# Failure Recovery

| Failure | Detection | New entries | Recovery |
|---|---|---|---|
| Internet/Gate/API loss | Freqtrade ping/data calls | Halt | Restore link; require fresh candles |
| Stale/gapped candle | timestamp/spacing gate | Halt | Consecutive current candles |
| Supervisor crash | runtime gate expiry | Halt | Restart supervisor; validate state |
| Freqtrade crash | ping failure | Halt | Inspect DB/logs, then controlled restart |
| Database/disk problem | write audit/free-space check | Critical/halt | Repair or free space; preserve history |
| Invalid config | startup validator/schema | Process abort | Correct config and revalidate |
| Drawdown/emergency halt | risk governor/manual state | Halt | Inspect reason; explicit safe resume |

Paper state is local, but restart still does not assume a clean state. Live reconciliation and automatic restart remain out of scope because live trading is forbidden.
