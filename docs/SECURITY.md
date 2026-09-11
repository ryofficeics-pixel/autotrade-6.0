# Security

Both APIs bind to loopback. Host and Origin are checked for control calls; request bodies are bounded; browser content has a restrictive CSP. Remote exposure is unsupported and would require authentication/TLS review first.

Setup generates Freqtrade API credentials into ignored `.env`. Optional Gate credentials are accepted only from `.env`; the checked-in paper config stays empty. Freqtrade dry-run may use them for read-only account calls but cannot submit orders. Logs redact environment values whose names indicate keys, passwords, tokens, or secrets. Databases, runtime gates, market data, logs, and `.env` are ignored. Gate withdrawal permission is never required.
