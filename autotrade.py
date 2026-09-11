"""Autotrade 6.0: fail-closed supervisor and localhost dashboard API.

Freqtrade remains the trading engine.  This process only supervises it.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
APP_CONFIG = ROOT / "config.json"
FT_CONFIG = ROOT / "user_data" / "config.json"
RUNTIME_FILE = ROOT / "user_data" / "autotrade_runtime.json"
DB_FILE = ROOT / "user_data" / "autotrade.sqlite"
INDEX_FILE = ROOT / "dashboard" / "index.html"
FONT_FILE = ROOT / "dashboard" / "OpenSans.ttf"


class ConfigError(RuntimeError):
    pass


class CommandRejected(RuntimeError):
    pass


class RealOrderForbidden(RuntimeError):
    pass


class DataHealth(StrEnum):
    HEALTHY = "DATA_HEALTHY"
    DELAYED = "DATA_DELAYED"
    STALE = "DATA_STALE"
    DISCONNECTED = "DATA_DISCONNECTED"
    RECOVERING = "DATA_RECOVERING"


class RiskState(StrEnum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    REDUCED = "REDUCED"
    HALTED = "HALTED"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return value


def validate_configs(app: dict[str, Any], freqtrade: dict[str, Any]) -> None:
    errors: list[str] = []
    if app.get("schema_version") != 1:
        errors.append("config schema_version must be 1")
    if app.get("environment") != "PAPER":
        errors.append("environment must be PAPER")
    if app.get("allow_live_orders") is not False:
        errors.append("allow_live_orders must be false")
    if app.get("bind_host") not in {"127.0.0.1", "localhost", "::1"}:
        errors.append("dashboard must bind to loopback only")
    if float(app.get("initial_equity", 0)) != 300:
        errors.append("initial_equity must be 300 USDT for V1")

    fees = app.get("fees", {})
    try:
        fallback_fee = float(fees["fallback_taker_rate_per_side"])
        slippage = float(fees["slippage_buffer_rate"])
        if not 0 <= fallback_fee <= 0.01 or not 0 <= slippage <= 0.01:
            errors.append("fee and slippage rates must be fractions in [0, 0.01]")
    except (KeyError, TypeError, ValueError):
        errors.append("fee configuration is incomplete or invalid")
    try:
        roi = {int(minutes): float(target) for minutes, target in app["take_profit_schedule"].items()}
        if 0 not in roi or any(minutes < 0 or target < 0 for minutes, target in roi.items()):
            errors.append("take_profit_schedule needs a non-negative minute 0 target")
    except (KeyError, AttributeError, TypeError, ValueError):
        errors.append("take_profit_schedule is incomplete or invalid")

    risk = app.get("risk", {})
    try:
        ladder = [float(risk[key]) for key in ("caution_drawdown", "reduced_drawdown", "halt_drawdown")]
        if not (0 < ladder[0] < ladder[1] < ladder[2] < 1):
            errors.append("drawdown thresholds must be increasing fractions")
        fixed = float(risk["fixed_risk_fraction"])
        if not 0 < fixed <= 0.01:
            errors.append("paper bootstrap fixed_risk_fraction must be in (0, 0.01]")
        if not 1 <= float(risk["max_leverage"]) <= 5:
            errors.append("paper bootstrap max_leverage must be in [1, 5]")
    except (KeyError, TypeError, ValueError):
        errors.append("risk configuration is incomplete or invalid")

    exchange = freqtrade.get("exchange", {})
    api = freqtrade.get("api_server", {})
    if freqtrade.get("dry_run") is not True:
        errors.append("Freqtrade dry_run must be true")
    if freqtrade.get("trading_mode") != "futures":
        errors.append("Freqtrade trading_mode must be futures")
    if freqtrade.get("margin_mode") != "isolated":
        errors.append("Freqtrade margin_mode must be isolated")
    if exchange.get("name") != "gate":
        errors.append("Freqtrade exchange must be gate (Gate.io's CCXT identifier)")
    if exchange.get("key") or exchange.get("secret") or exchange.get("password"):
        errors.append("paper config must not contain exchange credentials")
    if freqtrade.get("position_adjustment_enable") is not False:
        errors.append("position_adjustment_enable must be false (no DCA)")
    if freqtrade.get("force_entry_enable") is not False:
        errors.append("force_entry_enable must be false")
    if api.get("listen_ip_address") not in {"127.0.0.1", "localhost"}:
        errors.append("Freqtrade API must bind to loopback only")
    if not api.get("enabled"):
        errors.append("Freqtrade API must be enabled for supervision")
    if errors:
        raise ConfigError("Unsafe configuration:\n- " + "\n- ".join(errors))


class PaperExecutionAdapter:
    """Autotrade never submits orders; Freqtrade dry-run owns simulation."""

    def submit_real_order(self, _request: dict[str, Any]) -> None:
        raise RealOrderForbidden("NO REAL ORDERS: Autotrade V1 is paper-only")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError(f"Database schema {version} is newer than this application")
            if version == 0:
                self.connection.executescript(
                    """
                    CREATE TABLE audit_events (
                        id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, event TEXT NOT NULL,
                        reason TEXT NOT NULL, previous_state TEXT, new_state TEXT, details TEXT NOT NULL
                    );
                    CREATE TABLE health_audits (
                        id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, status TEXT NOT NULL,
                        checks TEXT NOT NULL
                    );
                    CREATE TABLE equity_snapshots (
                        id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, equity REAL NOT NULL,
                        available REAL NOT NULL, daily_pnl REAL NOT NULL
                    );
                    CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    PRAGMA user_version = 1;
                    """
                )
                self.connection.commit()

    def audit(self, event: str, reason: str, previous: str = "", new: str = "", **details: Any) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT INTO audit_events(timestamp,event,reason,previous_state,new_state,details) VALUES(?,?,?,?,?,?)",
                (utc_iso(), event, reason, previous, new, json.dumps(details, separators=(",", ":"))),
            )
            self.connection.commit()

    def audit_rows(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
        return [dict(row) | {"details": json.loads(row["details"])} for row in rows]

    def health(self, status: str, checks: dict[str, Any]) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT INTO health_audits(timestamp,status,checks) VALUES(?,?,?)",
                (utc_iso(), status, json.dumps(checks, separators=(",", ":"))),
            )
            self.connection.commit()

    def equity(self, equity: float, available: float, daily_pnl: float) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT INTO equity_snapshots(timestamp,equity,available,daily_pnl) VALUES(?,?,?,?)",
                (utc_iso(), equity, available, daily_pnl),
            )
            self.connection.commit()

    def equity_rows(self, limit: int = 288) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT timestamp,equity,available,daily_pnl FROM equity_snapshots ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 2000)),),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def peak_equity(self, fallback: float) -> float:
        with self.lock:
            row = self.connection.execute("SELECT MAX(equity) FROM equity_snapshots").fetchone()
        return max(fallback, float(row[0] or 0))

    def get_state(self, key: str, default: Any) -> Any:
        with self.lock:
            row = self.connection.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def set_state(self, key: str, value: Any) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, separators=(",", ":"))),
            )
            self.connection.commit()

    def writable(self) -> bool:
        try:
            self.set_state("last_write_check", utc_iso())
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self.lock:
            self.connection.close()


class RiskGovernor:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def assess(
        self,
        *,
        drawdown: float,
        daily_loss: float,
        consecutive_losses: int,
        data_health: DataHealth,
        paused: bool,
        manual_halt: bool,
        forced_safe: bool,
    ) -> tuple[RiskState, str, float]:
        c = self.config
        if manual_halt:
            return RiskState.HALTED, "Emergency/risk halt requires explicit resume", 0.0
        if data_health not in {DataHealth.HEALTHY, DataHealth.DELAYED}:
            return RiskState.HALTED, f"Unsafe market data: {data_health}", 0.0
        if drawdown >= c["halt_drawdown"] or daily_loss >= c["daily_loss_halt"]:
            return RiskState.HALTED, "Hard drawdown or daily-loss limit reached", 0.0
        if paused:
            return RiskState.HALTED, "New entries manually paused", 0.0
        if forced_safe or drawdown >= c["reduced_drawdown"] or consecutive_losses >= c["reduced_after_losses"]:
            return RiskState.REDUCED, "Safe/reduced risk envelope active", c["fixed_risk_fraction"] * 0.25
        if drawdown >= c["caution_drawdown"] or consecutive_losses >= c["caution_after_losses"]:
            return RiskState.CAUTION, "Caution risk envelope active", c["fixed_risk_fraction"] * 0.5
        return RiskState.NORMAL, "All entry gates passed", c["fixed_risk_fraction"]

    def risk_fraction(
        self,
        *,
        wins: int,
        losses: int,
        average_win: float,
        average_loss: float,
        hard_cap: float,
    ) -> tuple[float, str]:
        sample = wins + losses
        if sample < self.config["kelly_min_trades"] or average_win <= 0 or average_loss <= 0:
            return min(self.config["fixed_risk_fraction"], hard_cap), "FIXED_FRACTIONAL_INSUFFICIENT_DATA"
        win_rate = wins / sample
        payoff = average_win / average_loss
        kelly = max(0.0, win_rate - (1.0 - win_rate) / payoff)
        fraction = min(kelly * self.config["kelly_fraction"], self.config["kelly_risk_cap"], hard_cap)
        return fraction, "FRACTIONAL_KELLY" if fraction > 0 else "NO_POSITIVE_EDGE"

    def leverage(self, requested: float, realized_volatility: float, state: RiskState) -> float:
        cap = float(self.config["max_leverage"])
        if state == RiskState.CAUTION:
            cap = min(cap, 1.5)
        if state == RiskState.REDUCED:
            cap = 1.0
        if state == RiskState.HALTED:
            return 1.0
        if realized_volatility > 0:
            cap = min(cap, max(1.0, self.config["target_candle_volatility"] / realized_volatility))
        return round(max(1.0, min(float(requested), cap)), 2)


class FreqtradeClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.username = os.getenv("FREQTRADE__API_SERVER__USERNAME", "")
        self.password = os.getenv("FREQTRADE__API_SERVER__PASSWORD", "")

    def request(self, path: str, method: str = "GET", params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode(params)
        headers = {"Accept": "application/json"}
        if self.username or self.password:
            raw = f"{self.username}:{self.password}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        data = b"{}" if method != "GET" else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(url, data=data, headers=headers, method=method), timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Freqtrade {method} {path} failed: {type(exc).__name__}") from exc


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _datetime(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            seconds = float(value) / (1000 if float(value) > 10_000_000_000 else 1)
            return datetime.fromtimestamp(seconds, timezone.utc)
        text = str(value).replace("Z", "+00:00")
        result = datetime.fromisoformat(text)
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    data = payload["data"]
    if data and isinstance(data[0], dict):
        return data
    columns = payload.get("columns", [])
    return [dict(zip(columns, row)) for row in data if isinstance(row, list)]


def score_opportunity(row: dict[str, Any]) -> float:
    volatility = min(1.0, max(0.0, _number(row.get("realized_volatility")) / 0.03))
    liquidity = min(1.0, max(0.0, _number(row.get("liquidity_quality"))))
    regime = min(1.0, max(0.0, _number(row.get("regime_compatibility"), 0.5)))
    manipulation = min(1.0, max(0.0, _number(row.get("manipulation_risk"))))
    return round(100 * max(0.0, 0.40 * volatility + 0.35 * liquidity + 0.25 * regime - 0.35 * manipulation), 1)


def fee_aware_trade(
    trade: dict[str, Any],
    fallback_rate: float,
    take_profit_schedule: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Expose the fee-inclusive Freqtrade P&L and its estimated trading-fee cost."""
    result = dict(trade)
    open_fee = fallback_rate if trade.get("fee_open") is None else _number(trade.get("fee_open"))
    close_fee = fallback_rate if trade.get("fee_close") is None else _number(trade.get("fee_close"))
    amount = abs(_number(trade.get("amount")))
    open_rate = _number(trade.get("open_rate"))
    current_rate = _number(trade.get("current_rate", trade.get("close_rate")), open_rate)
    trading_fees = amount * (open_rate * open_fee + current_rate * close_fee)
    net_profit = _number(trade.get("profit_abs", trade.get("close_profit_abs")))
    if trade.get("profit_abs") is None and trade.get("close_profit_abs") is None:
        direction = -1.0 if trade.get("is_short") else 1.0
        net_profit = amount * (current_rate - open_rate) * direction - trading_fees + _number(trade.get("funding_fees"))
    schedule = take_profit_schedule or {"0": 0.06, "240": 0.02, "720": 0.0}
    opened = _datetime(trade.get("open_timestamp", trade.get("open_date")))
    age_minutes = max(0.0, (utc_now() - opened).total_seconds() / 60) if opened else 0.0
    roi_target = max(
        ((int(minutes), float(target)) for minutes, target in schedule.items() if int(minutes) <= age_minutes),
        default=(0, float(schedule.get("0", 0.0))),
    )[1]
    leverage = max(1.0, _number(trade.get("leverage"), 1.0))
    if trade.get("is_short"):
        take_profit_rate = open_rate * (1 - open_fee) * (1 - roi_target / leverage) / max(1 + close_fee, 1e-9)
    else:
        take_profit_rate = open_rate * (1 + open_fee) * (1 + roi_target / leverage) / max(1 - close_fee, 1e-9)
    result.update(
        fee_open_rate=open_fee,
        fee_close_rate=close_fee,
        estimated_trading_fee_abs=round(trading_fees, 8),
        net_profit_abs=round(net_profit, 8),
        take_profit_rate=round(take_profit_rate, 8),
        take_profit_roi=roi_target,
        fee_source="FREQTRADE_EXCHANGE" if trade.get("fee_open") is not None and trade.get("fee_close") is not None else "CONSERVATIVE_FALLBACK",
    )
    return result


class Supervisor:
    def __init__(self, app: dict[str, Any], store: Store, logger: logging.Logger):
        self.config = app
        self.store = store
        self.log = logger
        self.risk = RiskGovernor(app["risk"])
        self.ft = FreqtradeClient(app["freqtrade_url"], app["freqtrade_timeout_seconds"])
        self.paper = PaperExecutionAdapter()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.paused = bool(store.get_state("paused", False))
        self.manual_halt = bool(store.get_state("manual_halt", False))
        self.forced_safe = bool(store.get_state("forced_safe", False))
        self.last_audit_at = 0.0
        self.last_equity_at = 0.0
        self.last_daily_evaluation = str(store.get_state("last_daily_evaluation", ""))
        self.health_loop_count = 0
        self.last_health_signature: tuple[Any, ...] | None = None
        self.state: dict[str, Any] = {
            "timestamp": utc_iso(),
            "environment": "PAPER",
            "safety": "REAL ORDERS DISABLED",
            "bot_status": "OFFLINE",
            "data_health": DataHealth.DISCONNECTED,
            "risk_state": RiskState.HALTED,
            "risk_reason": "Supervisor starting",
            "entry_allowed": False,
            "equity": app["initial_equity"],
            "available": app["initial_equity"],
            "total_pnl": 0.0,
            "daily_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "drawdown": 0.0,
            "open_trades": [],
            "opportunities": [],
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "fee_model": {},
            "active_strategy": "AutotradeBaseline",
            "regime": "UNKNOWN",
            "champion": "AutotradeBaseline (paper hypothesis)",
            "challenger": "REQUIRE_MORE_DATA",
            "last_candle": None,
            "last_heartbeat": None,
            "last_audit": None,
            "next_daily_evaluation": None,
            "components": {},
            "health_loop_count": 0,
            "health_loop_interval_seconds": app["heartbeat_seconds"],
        }

    def start(self) -> None:
        self.store.audit("BOT_STARTED", "Supervisor process started", new="STARTING")
        threading.Thread(target=self._loop, name="autotrade-supervisor", daemon=True).start()

    def stop(self) -> None:
        self.stop_event.set()
        self._write_runtime(False, RiskState.HALTED, 0.0, 1.0, "Supervisor stopped")
        self.store.audit("BOT_STOPPED", "Supervisor process stopped", previous=str(self.state["bot_status"]), new="OFFLINE")

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.state))

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                self.refresh()
            except Exception as exc:  # fail closed; the loop must survive adapter/schema surprises
                self.log.exception("Supervisor refresh failed: %s", exc)
                self._fail_closed(str(exc))
            self.stop_event.wait(max(0.2, self.config["heartbeat_seconds"] - (time.monotonic() - started)))

    def _fail_closed(self, reason: str) -> None:
        with self.lock:
            self.state.update(
                timestamp=utc_iso(), bot_status="DEGRADED", data_health=DataHealth.DISCONNECTED,
                risk_state=RiskState.HALTED, risk_reason=reason, entry_allowed=False,
            )
        self._write_runtime(False, RiskState.HALTED, 0.0, 1.0, reason)

    def refresh(self) -> None:
        now = utc_now()
        self.health_loop_count += 1
        components = {"health_loop": "HEALTHY", "supervisor": "HEALTHY", "audit": "HEALTHY", "paper_safety": "HEALTHY"}
        ft_ok = False
        try:
            ft_ok = self.ft.request("ping").get("status") == "pong"
        except RuntimeError:
            pass
        components["freqtrade"] = "HEALTHY" if ft_ok else "CRITICAL"
        components["gateio"] = "UNKNOWN" if not ft_ok else "DEGRADED"
        components["database"] = "HEALTHY" if self.store.writable() else "CRITICAL"

        balance: dict[str, Any] = {}
        profit: dict[str, Any] = {}
        daily: dict[str, Any] = {}
        open_trades: list[dict[str, Any]] = []
        closed_trades: list[dict[str, Any]] = []
        opportunities: list[dict[str, Any]] = []
        data_health = DataHealth.DISCONNECTED
        last_candle: datetime | None = None
        if ft_ok:
            try:
                balance = self.ft.request("balance")
                profit = self.ft.request("profit")
                daily = self.ft.request("daily", params={"timescale": 1})
                status = self.ft.request("status")
                raw_open_trades = status if isinstance(status, list) else status.get("trades", [])
                fallback_fee = float(self.config["fees"]["fallback_taker_rate_per_side"])
                open_trades = [
                    fee_aware_trade(trade, fallback_fee, self.config["take_profit_schedule"])
                    for trade in raw_open_trades
                ]
                trades = self.ft.request("trades", params={"limit": 100, "offset": 0})
                closed_trades = trades.get("trades", []) if isinstance(trades, dict) else []
                whitelist = self.ft.request("whitelist").get("whitelist", [])
                opportunities, last_candle, data_health = self._opportunities(whitelist)
                components["gateio"] = "HEALTHY" if data_health in {DataHealth.HEALTHY, DataHealth.DELAYED} else "CRITICAL"
            except RuntimeError as exc:
                self.log.warning("Authenticated Freqtrade data unavailable: %s", exc)
                components["freqtrade"] = "DEGRADED"

        components["market_data"] = (
            "HEALTHY" if data_health == DataHealth.HEALTHY else
            "DEGRADED" if data_health == DataHealth.DELAYED else "CRITICAL"
        )
        equity, available = self._balances(balance)
        total_pnl = _number(profit.get("profit_all_coin", profit.get("profit_closed_coin")))
        unrealized = _number(profit.get("profit_all_coin")) - _number(profit.get("profit_closed_coin"))
        daily_rows = daily.get("data", daily.get("daily", [])) if isinstance(daily, dict) else []
        daily_pnl = _number(daily_rows[-1].get("abs_profit")) if daily_rows and isinstance(daily_rows[-1], dict) else 0.0
        peak = self.store.peak_equity(self.config["initial_equity"])
        drawdown = max(0.0, (peak - equity) / peak) if peak else 0.0
        losses = self._consecutive_losses(closed_trades)
        daily_loss = max(0.0, -daily_pnl / max(equity - daily_pnl, 1.0))
        risk_state, risk_reason, risk_fraction = self.risk.assess(
            drawdown=drawdown,
            daily_loss=daily_loss,
            consecutive_losses=losses,
            data_health=data_health,
            paused=self.paused,
            manual_halt=self.manual_halt,
            forced_safe=self.forced_safe,
        )
        average_vol = sum(_number(item.get("volatility")) for item in opportunities) / max(len(opportunities), 1)
        leverage = self.risk.leverage(self.config["risk"]["max_leverage"], average_vol, risk_state)
        entry_allowed = risk_state != RiskState.HALTED
        bot_status = "RUNNING" if ft_ok and entry_allowed else "DEGRADED" if ft_ok else "OFFLINE"
        if self.manual_halt or (risk_state == RiskState.HALTED and data_health not in {DataHealth.DISCONNECTED, DataHealth.RECOVERING}):
            bot_status = "HALTED"

        wins = int(_number(profit.get("winning_trades")))
        closed_count = int(_number(profit.get("closed_trade_count")))
        win_rate = wins / closed_count if closed_count else 0.0
        with self.lock:
            self.state.update(
                timestamp=utc_iso(), bot_status=bot_status, data_health=data_health,
                risk_state=risk_state, risk_reason=risk_reason, entry_allowed=entry_allowed,
                risk_fraction=risk_fraction, leverage_cap=leverage, equity=equity, available=available,
                total_pnl=total_pnl, daily_pnl=daily_pnl, unrealized_pnl=unrealized,
                drawdown=drawdown, open_trades=open_trades, opportunities=opportunities,
                win_rate=win_rate, profit_factor=_number(profit.get("profit_factor")),
                last_candle=last_candle.isoformat() if last_candle else None,
                last_heartbeat=utc_iso(), components=components,
                health_loop_count=self.health_loop_count,
                fee_model={
                    "fallback_rate_per_side": self.config["fees"]["fallback_taker_rate_per_side"],
                    "slippage_buffer_rate": self.config["fees"]["slippage_buffer_rate"],
                    "round_trip_hurdle_rate": 2 * self.config["fees"]["fallback_taker_rate_per_side"] + self.config["fees"]["slippage_buffer_rate"],
                    "pnl_source": "Freqtrade net of trading fees and funding",
                },
            )
            if opportunities:
                self.state["regime"] = opportunities[0].get("regime", "UNKNOWN")
        signature = (bot_status, str(data_health), str(risk_state), tuple(sorted(components.items())))
        if signature != self.last_health_signature:
            self.store.audit(
                "HEALTH_STATE_CHANGED",
                risk_reason,
                str(self.last_health_signature or "STARTING"),
                str(signature),
                loop=self.health_loop_count,
            )
            self.last_health_signature = signature
        self._write_runtime(entry_allowed, risk_state, risk_fraction, leverage, risk_reason)

        if time.monotonic() - self.last_equity_at >= self.config["equity_snapshot_seconds"]:
            self.store.equity(equity, available, daily_pnl)
            self.last_equity_at = time.monotonic()
        if time.monotonic() - self.last_audit_at >= self.config["health_audit_seconds"]:
            self._health_audit(components, data_health)
            self.last_audit_at = time.monotonic()
        self._daily_evaluate(now.date().isoformat(), closed_count)

    def _balances(self, payload: dict[str, Any]) -> tuple[float, float]:
        equity = _number(payload.get("total", payload.get("total_bot")), self.config["initial_equity"])
        available = _number(payload.get("free"), equity)
        for item in payload.get("currencies", []):
            if item.get("currency") == "USDT":
                equity = _number(item.get("balance", item.get("est_stake")), equity)
                available = _number(item.get("free"), available)
                break
        return max(0.0, equity), max(0.0, available)

    def _opportunities(self, whitelist: list[str]) -> tuple[list[dict[str, Any]], datetime | None, DataHealth]:
        results: list[dict[str, Any]] = []
        latest: datetime | None = None
        unsafe_gap = False
        for pair in whitelist[: self.config["opportunity_scan_pairs"]]:
            try:
                payload = self.ft.request(
                    "pair_candles", params={"pair": pair, "timeframe": self.config["timeframe"], "limit": 2}
                )
            except RuntimeError:
                continue
            rows = _rows(payload)
            if not rows:
                continue
            row = rows[-1]
            candle_time = _datetime(row.get("date", row.get("timestamp")))
            if candle_time and (latest is None or candle_time > latest):
                latest = candle_time
            if len(rows) > 1:
                previous = _datetime(rows[-2].get("date", rows[-2].get("timestamp")))
                expected = self.config["timeframe_minutes"] * 60
                if previous and candle_time and not 0 < (candle_time - previous).total_seconds() <= expected * 1.5:
                    unsafe_gap = True
            score = _number(row.get("opportunity_score"), score_opportunity(row))
            current_price = _number(row.get("close"))
            previous_price = _number(rows[-2].get("close"), current_price) if len(rows) > 1 else current_price
            results.append({
                "pair": pair,
                "current_price": current_price,
                "price_change": (current_price / previous_price - 1) if previous_price > 0 else 0.0,
                "score": round(score, 1),
                "volatility": _number(row.get("realized_volatility")),
                "liquidity": _number(row.get("liquidity_quality")),
                "spread": None,
                "regime": str(row.get("regime", "UNKNOWN")),
                "preferred_strategy": "AutotradeBaseline",
                "eligible": bool(row.get("trade_eligible", score >= 50)),
                "fee_hurdle": _number(
                    row.get("fee_hurdle"),
                    2 * self.config["fees"]["fallback_taker_rate_per_side"] + self.config["fees"]["slippage_buffer_rate"],
                ),
            })
        results.sort(key=lambda item: item["score"], reverse=True)
        if latest is None:
            return results, None, DataHealth.RECOVERING
        age = max(0.0, (utc_now() - latest).total_seconds())
        interval = self.config["timeframe_minutes"] * 60
        if unsafe_gap or age > interval * self.config["stale_after_intervals"]:
            health = DataHealth.STALE
        elif age > interval * self.config["delayed_after_intervals"]:
            health = DataHealth.DELAYED
        else:
            health = DataHealth.HEALTHY
        return results, latest, health

    @staticmethod
    def _consecutive_losses(trades: list[dict[str, Any]]) -> int:
        count = 0
        ordered = sorted((t for t in trades if not t.get("is_open")), key=lambda t: t.get("close_date", ""), reverse=True)
        for trade in ordered:
            if _number(trade.get("profit_abs", trade.get("close_profit_abs"))) < 0:
                count += 1
            else:
                break
        return count

    def _write_runtime(self, allowed: bool, state: RiskState, risk_fraction: float, leverage: float, reason: str) -> None:
        payload = {
            "schema_version": 1,
            "environment": "PAPER",
            "entry_allowed": bool(allowed),
            "risk_state": str(state),
            "risk_fraction": max(0.0, float(risk_fraction)),
            "leverage": max(1.0, float(leverage)),
            "reason": reason,
            "updated_at": utc_iso(),
            "valid_until_epoch": time.time() + self.config["runtime_gate_ttl_seconds"],
        }
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = RUNTIME_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, RUNTIME_FILE)

    def _health_audit(self, components: dict[str, str], data_health: DataHealth) -> None:
        free = shutil.disk_usage(ROOT).free
        checks = dict(components) | {
            "disk_free_bytes": free,
            "clock_utc": utc_iso(),
            "data_health": str(data_health),
            "runtime_gate_exists": RUNTIME_FILE.exists(),
        }
        if "CRITICAL" in components.values() or free < self.config["minimum_disk_free_bytes"]:
            status = "CRITICAL"
        elif "DEGRADED" in components.values():
            status = "DEGRADED"
        else:
            status = "HEALTHY"
        self.store.health(status, checks)
        with self.lock:
            self.state["last_audit"] = utc_iso()
        self.store.audit("HEALTH_AUDIT", status, new=status, checks=checks)

    def _daily_evaluate(self, date: str, closed_count: int) -> None:
        if self.last_daily_evaluation == date:
            return
        outcome = "REQUIRE_MORE_DATA" if closed_count < self.config["research_min_closed_trades"] else "KEEP"
        self.store.audit("DAILY_EVALUATION", outcome, new=outcome, closed_trades=closed_count)
        self.store.set_state("last_daily_evaluation", date)
        self.last_daily_evaluation = date
        with self.lock:
            self.state["challenger"] = outcome
            self.state["next_daily_evaluation"] = f"{date} + 1 day"

    def command(self, command: str) -> tuple[int, dict[str, Any]]:
        previous = str(self.snapshot()["risk_state"])
        if command == "pause":
            self.paused = True
            self.store.set_state("paused", True)
            self._try_ft("pause")
            self.store.audit("TRADING_PAUSED", "Owner paused new entries", previous, "HALTED")
            self._refresh_after_command()
            return 200, {"ok": True, "message": "New entries paused; open trades remain managed"}
        if command == "safe":
            self.forced_safe = True
            self.store.set_state("forced_safe", True)
            self.store.audit("SAFE_MODE", "Owner selected safe mode", previous, "REDUCED")
            self._refresh_after_command()
            return 200, {"ok": True, "message": "Reduced risk envelope selected"}
        if command == "emergency-stop":
            self.manual_halt = True
            self.paused = True
            self.store.set_state("manual_halt", True)
            self.store.set_state("paused", True)
            self._try_ft("stop")
            self.store.audit("EMERGENCY_STOP", "Owner emergency stop", previous, "HALTED")
            self._refresh_after_command()
            return 200, {"ok": True, "message": "Paper trader stopped and state preserved"}
        if command == "resume":
            current = self.snapshot()
            if current["data_health"] not in {DataHealth.HEALTHY, DataHealth.DELAYED}:
                raise CommandRejected(f"Resume rejected: {current['data_health']}")
            if current["drawdown"] >= self.config["risk"]["halt_drawdown"]:
                raise CommandRejected("Resume rejected: drawdown remains above the hard limit")
            self.manual_halt = False
            self.paused = False
            self.forced_safe = True
            self.store.set_state("manual_halt", False)
            self.store.set_state("paused", False)
            self.store.set_state("forced_safe", True)
            self._try_ft("start")
            self.store.audit("TRADING_RESUMED", "Owner resume accepted into safe mode", previous, "REDUCED")
            self._refresh_after_command()
            return 200, {"ok": True, "message": "Trading resumed in reduced-risk safe mode"}
        raise CommandRejected("Unknown command")

    def _try_ft(self, endpoint: str) -> None:
        try:
            self.ft.request(endpoint, method="POST")
        except RuntimeError as exc:
            self.log.warning("Freqtrade command %s unavailable: %s", endpoint, exc)

    def _refresh_after_command(self) -> None:
        try:
            self.refresh()
        except Exception as exc:
            self._fail_closed(f"Post-command health refresh failed: {exc}")
            raise CommandRejected("Command applied but health refresh failed; entry gate closed") from exc


class SecretFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.secrets = [
            value for key, value in os.environ.items()
            if any(word in key.upper() for word in ("SECRET", "PASSWORD", "TOKEN", "KEY")) and len(value) >= 4
        ]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


def make_logger(config: dict[str, Any]) -> logging.Logger:
    log_path = ROOT / config["log_file"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("autotrade")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('{"timestamp":"%(asctime)s","level":"%(levelname)s","category":"%(name)s","message":"%(message)s"}')
        handler = RotatingFileHandler(log_path, maxBytes=config["log_max_bytes"], backupCount=config["log_backups"], encoding="utf-8")
        handler.setFormatter(formatter)
        handler.addFilter(SecretFilter())
        logger.addHandler(handler)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.addFilter(SecretFilter())
        logger.addHandler(console)
    return logger


def handler_for(supervisor: Supervisor, store: Store, server_ref: list[ThreadingHTTPServer]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "Autotrade/6.0"

        def _local_request(self) -> bool:
            host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
            return self.client_address[0] in {"127.0.0.1", "::1"} and host in {"127.0.0.1", "localhost", "::1"}

        def _send_json(self, value: Any, status: int = 200) -> None:
            body = json.dumps(value, separators=(",", ":"), default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if not self._local_request():
                self._send_json({"error": "loopback access only"}, 403)
                return
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                try:
                    body = INDEX_FILE.read_bytes()
                except OSError:
                    self._send_json({"error": "dashboard missing"}, 500)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/assets/OpenSans.ttf":
                try:
                    body = FONT_FILE.read_bytes()
                except OSError:
                    self._send_json({"error": "font missing"}, 500)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "font/ttf")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            snapshot = supervisor.snapshot()
            routes: dict[str, Any] = {
                "/api/status": snapshot,
                "/api/health": {"timestamp": snapshot["timestamp"], "status": snapshot["bot_status"], "components": snapshot["components"], "data_health": snapshot["data_health"], "last_audit": snapshot["last_audit"]},
                "/api/equity": {"current": snapshot["equity"], "history": store.equity_rows()},
                "/api/trades": {"trades": snapshot["open_trades"]},
                "/api/strategies": {"champion": snapshot["champion"], "challenger": snapshot["challenger"], "active": snapshot["active_strategy"], "regime": snapshot["regime"]},
                "/api/opportunities": {"opportunities": snapshot["opportunities"]},
                "/api/risk": {key: snapshot[key] for key in ("risk_state", "risk_reason", "risk_fraction", "leverage_cap", "drawdown", "entry_allowed") if key in snapshot},
            }
            if parsed.path == "/api/audit":
                limit = int(parse_qs(parsed.query).get("limit", ["100"])[0])
                self._send_json({"events": store.audit_rows(limit)})
            elif parsed.path in routes:
                self._send_json(routes[parsed.path])
            else:
                self._send_json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            if not self._local_request():
                self._send_json({"error": "loopback access only"}, 403)
                return
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{supervisor.config['port']}", f"http://localhost:{supervisor.config['port']}"}
            if origin and origin not in allowed:
                self._send_json({"error": "origin rejected"}, 403)
                return
            if int(self.headers.get("Content-Length", "0")) > 1024:
                self._send_json({"error": "request too large"}, 413)
                return
            command = {
                "/api/trading/pause": "pause",
                "/api/trading/resume": "resume",
                "/api/trading/safe": "safe",
                "/api/emergency-stop": "emergency-stop",
            }.get(urlparse(self.path).path)
            if command:
                try:
                    status, body = supervisor.command(command)
                    self._send_json(body, status)
                except CommandRejected as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 409)
                return
            if urlparse(self.path).path == "/api/system/shutdown":
                if not supervisor.manual_halt:
                    self._send_json({"error": "emergency-stop is required before shutdown"}, 409)
                    return
                self._send_json({"ok": True, "message": "Supervisor shutting down"})
                threading.Thread(target=server_ref[0].shutdown, daemon=True).start()
                return
            self._send_json({"error": "not found"}, 404)

        def log_message(self, fmt: str, *args: Any) -> None:
            supervisor.log.info("HTTP %s", fmt % args)

    return Handler


def serve(app: dict[str, Any], store: Store, logger: logging.Logger) -> None:
    supervisor = Supervisor(app, store, logger)
    supervisor.start()
    server_ref: list[ThreadingHTTPServer] = []
    server = ThreadingHTTPServer((app["bind_host"], app["port"]), handler_for(supervisor, store, server_ref))
    server_ref.append(server)
    logger.info("PAPER supervisor listening on http://%s:%s", app["bind_host"], app["port"])
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.stop()
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Autotrade 6.0 paper-only supervisor")
    parser.add_argument("command", nargs="?", choices=("serve", "validate"), default="serve")
    args = parser.parse_args()
    app = load_json(APP_CONFIG)
    freqtrade = load_json(FT_CONFIG)
    validate_configs(app, freqtrade)
    print("Configuration valid: PAPER mode, live orders forbidden")
    if args.command == "validate":
        PaperExecutionAdapter().submit_real_order({})  # must always raise
    logger = make_logger(app)
    store = Store(DB_FILE)
    try:
        serve(app, store, logger)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RealOrderForbidden as exc:
        if len(os.sys.argv) > 1 and os.sys.argv[1] == "validate":
            print(str(exc))
            raise SystemExit(0)
        raise
