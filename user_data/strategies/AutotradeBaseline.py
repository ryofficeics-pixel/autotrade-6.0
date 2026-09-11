"""Paper-only multi-timeframe breakout hypothesis for validation, not a profit claim."""

from __future__ import annotations

import json
from pathlib import Path
import time
from datetime import datetime

import numpy as np
from pandas import DataFrame

from freqtrade.exceptions import OperationalException
from freqtrade.strategy import IStrategy, informative


def _roi_schedule() -> dict[str, float]:
    try:
        app = json.loads((Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8"))
        return {str(minutes): float(target) for minutes, target in app["take_profit_schedule"].items()}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"0": 0.06, "240": 0.02, "720": 0.0}


class AutotradeBaseline(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 240
    process_only_new_candles = True
    position_adjustment_enable = False
    max_entry_position_adjustment = 0

    minimal_roi = _roi_schedule()
    stoploss = -0.04
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}
    fee_hurdle_rate = 0.002  # conservative fallback: 0.075% each side + 0.05% slippage

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 3},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 2,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 96,
                "trade_limit": 10,
                "stop_duration_candles": 24,
                "max_allowed_drawdown": 0.10,
            },
        ]

    def bot_start(self, **kwargs) -> None:
        if not self.config.get("dry_run", True):
            raise OperationalException("NO REAL ORDERS: AutotradeBaseline is paper-only")
        try:
            app = json.loads((Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8"))
            fees = app["fees"]
            self.fee_hurdle_rate = 2 * float(fees["fallback_taker_rate_per_side"]) + float(fees["slippage_buffer_rate"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass

    @informative("15m")
    def populate_indicators_15m(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        dataframe["ema_slow"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        return dataframe

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        dataframe["ema_slow"] = dataframe["close"].ewm(span=200, adjust=False).mean()
        return dataframe

    @informative("4h")
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_context"] = dataframe["close"].ewm(span=100, adjust=False).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        dataframe["ema_slow"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        dataframe["breakout_high"] = dataframe["high"].rolling(20).max().shift(1)
        dataframe["breakout_low"] = dataframe["low"].rolling(20).min().shift(1)
        dataframe["volume_median"] = dataframe["volume"].rolling(48).median()
        returns = dataframe["close"].pct_change()
        dataframe["realized_volatility"] = returns.rolling(48).std() * np.sqrt(288)
        dataframe["liquidity_quality"] = (dataframe["volume"] / dataframe["volume_median"].replace(0, np.nan) / 2).clip(0, 1)
        return_sigma = returns.rolling(48).std().replace(0, np.nan)
        dataframe["expected_candle_move"] = return_sigma
        dataframe["manipulation_risk"] = (returns.abs() / return_sigma / 6).clip(0, 1).fillna(1)

        trend_up = (
            (dataframe["ema_fast_15m"] > dataframe["ema_slow_15m"])
            & (dataframe["ema_fast_1h"] > dataframe["ema_slow_1h"])
            & (dataframe["close_4h"] > dataframe["ema_context_4h"])
        )
        trend_down = (
            (dataframe["ema_fast_15m"] < dataframe["ema_slow_15m"])
            & (dataframe["ema_fast_1h"] < dataframe["ema_slow_1h"])
            & (dataframe["close_4h"] < dataframe["ema_context_4h"])
        )
        dataframe["regime"] = np.select(
            [trend_up, trend_down, dataframe["realized_volatility"] > 0.08],
            ["TREND_UP", "TREND_DOWN", "HIGH_VOLATILITY"],
            default="RANGE",
        )
        dataframe["regime_compatibility"] = np.where(trend_up | trend_down, 1.0, 0.25)
        volatility_score = (dataframe["realized_volatility"] / 0.03).clip(0, 1)
        dataframe["opportunity_score"] = (
            100
            * (
                0.40 * volatility_score
                + 0.35 * dataframe["liquidity_quality"]
                + 0.25 * dataframe["regime_compatibility"]
                - 0.35 * dataframe["manipulation_risk"]
            ).clip(0, 1)
        )
        dataframe["fee_hurdle"] = self.fee_hurdle_rate
        dataframe["trade_eligible"] = (
            (dataframe["opportunity_score"] >= 50)
            & (dataframe["expected_candle_move"] > dataframe["fee_hurdle"])
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        liquid = (dataframe["volume"] > 0) & (dataframe["liquidity_quality"] >= 0.25)
        safe_move = dataframe["manipulation_risk"] < 0.8
        dataframe.loc[
            liquid
            & safe_move
            & dataframe["trade_eligible"]
            & (dataframe["regime"] == "TREND_UP")
            & (dataframe["close"] > dataframe["breakout_high"]),
            ["enter_long", "enter_tag"],
        ] = (1, "mtf_breakout_long")
        dataframe.loc[
            liquid
            & safe_move
            & dataframe["trade_eligible"]
            & (dataframe["regime"] == "TREND_DOWN")
            & (dataframe["close"] < dataframe["breakout_low"]),
            ["enter_short", "enter_tag"],
        ] = (1, "mtf_breakout_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["ema_fast"] < dataframe["ema_slow"], ["exit_long", "exit_tag"]] = (1, "trend_reversed")
        dataframe.loc[dataframe["ema_fast"] > dataframe["ema_slow"], ["exit_short", "exit_tag"]] = (1, "trend_reversed")
        return dataframe

    @staticmethod
    def _runtime() -> dict:
        path = Path(__file__).resolve().parents[1] / "autotrade_runtime.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("environment") != "PAPER" or float(value.get("valid_until_epoch", 0)) < time.time():
                return {}
            return value
        except (OSError, ValueError, TypeError):
            return {}

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        return bool(self._runtime().get("entry_allowed", False))

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        runtime = self._runtime()
        if not runtime.get("entry_allowed"):
            return 0.0
        equity = self.wallets.get_total_stake_amount()
        planned = equity * float(runtime.get("risk_fraction", 0)) / abs(self.stoploss)
        floor = float(min_stake or 0)
        return max(floor, min(planned, max_stake)) if planned >= floor else 0.0

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return max(1.0, min(float(self._runtime().get("leverage", 1.0)), max_leverage))

    plot_config = {
        "main_plot": {"ema_fast": {}, "ema_slow": {}, "breakout_high": {}, "breakout_low": {}},
        "subplots": {"Opportunity": {"opportunity_score": {"color": "#40e0d0"}}},
    }
