# Health Monitoring

The supervisor loops every five seconds, checking Freqtrade, Gate/data freshness, the database, risk state, and the paper safety gate. It exposes a monotonic loop counter and audits health-state changes without spamming unchanged state. Each pass writes a 15-second entry authorization. Loss or freeze of the supervisor therefore closes entries inside the strategy without a network call, while the dashboard marks a heartbeat older than 15 seconds OFFLINE.

Every ten minutes an audit records Freqtrade reachability, Gate/data freshness, database writes, disk space, safety gate, local clock, and supervisor state. Status is HEALTHY, DEGRADED, or CRITICAL. Automatic process restart is intentionally absent until reconciliation of open exchange state can be proven; blind restart is less safe than a visible halt.
