# Gate.io Data

Freqtrade/CCXT is the sole exchange network path. The leading `VolumePairList` is followed by age, precision, price, spread, and volatility filters. Market capitalization is not used.

The supervisor reads Freqtrade analyzed candles for ranked pairs. It checks latest timestamp and consecutive-candle spacing. Data becomes DELAYED after two timeframe intervals and STALE after three; missing, duplicated, gapped, or inaccessible candles fail closed for entries. Exact pairlist thresholds remain paper-tuning values.
