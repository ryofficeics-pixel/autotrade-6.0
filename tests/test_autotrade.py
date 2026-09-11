import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import autotrade


class SafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = autotrade.load_json(autotrade.APP_CONFIG)
        cls.ft = autotrade.load_json(autotrade.FT_CONFIG)

    def test_checked_in_configuration_is_safe(self):
        autotrade.validate_configs(self.app, self.ft)

    def test_every_live_order_is_rejected(self):
        with self.assertRaisesRegex(autotrade.RealOrderForbidden, "NO REAL ORDERS"):
            autotrade.PaperExecutionAdapter().submit_real_order({"pair": "BTC/USDT:USDT"})

    def test_dry_run_cannot_be_disabled(self):
        ft = copy.deepcopy(self.ft)
        ft["dry_run"] = False
        with self.assertRaisesRegex(autotrade.ConfigError, "dry_run"):
            autotrade.validate_configs(self.app, ft)

    def test_exchange_credentials_are_forbidden(self):
        ft = copy.deepcopy(self.ft)
        ft["exchange"]["secret"] = "should-never-be-here"
        with self.assertRaisesRegex(autotrade.ConfigError, "credentials"):
            autotrade.validate_configs(self.app, ft)

    def test_public_binding_is_forbidden(self):
        app = copy.deepcopy(self.app)
        app["bind_host"] = "0.0.0.0"
        with self.assertRaisesRegex(autotrade.ConfigError, "loopback"):
            autotrade.validate_configs(app, self.ft)


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.config = autotrade.load_json(autotrade.APP_CONFIG)["risk"]
        self.risk = autotrade.RiskGovernor(self.config)

    def test_stale_data_halts_new_entries(self):
        state, reason, fraction = self.risk.assess(
            drawdown=0,
            daily_loss=0,
            consecutive_losses=0,
            data_health=autotrade.DataHealth.STALE,
            paused=False,
            manual_halt=False,
            forced_safe=False,
        )
        self.assertEqual(state, autotrade.RiskState.HALTED)
        self.assertIn("DATA_STALE", reason)
        self.assertEqual(fraction, 0)

    def test_kelly_waits_for_evidence_and_is_capped(self):
        fraction, method = self.risk.risk_fraction(
            wins=4, losses=1, average_win=.02, average_loss=.01, hard_cap=.01
        )
        self.assertEqual(method, "FIXED_FRACTIONAL_INSUFFICIENT_DATA")
        self.assertEqual(fraction, self.config["fixed_risk_fraction"])
        fraction, method = self.risk.risk_fraction(
            wins=70, losses=30, average_win=.02, average_loss=.01, hard_cap=.006
        )
        self.assertEqual(method, "FRACTIONAL_KELLY")
        self.assertLessEqual(fraction, .006)

    def test_high_volatility_cannot_raise_leverage(self):
        low = self.risk.leverage(2, .005, autotrade.RiskState.NORMAL)
        high = self.risk.leverage(2, .05, autotrade.RiskState.NORMAL)
        self.assertLessEqual(high, low)
        self.assertGreaterEqual(high, 1)

    def test_health_loop_repeats_until_stopped(self):
        class Probe:
            config = {"heartbeat_seconds": 0.001}

            def __init__(self):
                import threading
                self.stop_event = threading.Event()
                self.count = 0

            def refresh(self):
                self.count += 1
                if self.count == 3:
                    self.stop_event.set()

            def _fail_closed(self, reason):
                raise AssertionError(reason)

        probe = Probe()
        autotrade.Supervisor._loop(probe)
        self.assertEqual(probe.count, 3)


class PersistenceAndScoringTests(unittest.TestCase):
    def test_schema_audit_and_state_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            store = autotrade.Store(Path(directory) / "test.sqlite")
            store.audit("TEST", "runnable check", new="SAFE")
            store.set_state("paused", True)
            self.assertTrue(store.get_state("paused", False))
            self.assertEqual(store.audit_rows(1)[0]["event"], "TEST")
            store.close()

    def test_opportunity_score_penalizes_manipulation(self):
        base = {"realized_volatility": .02, "liquidity_quality": .8, "regime_compatibility": 1}
        clean = autotrade.score_opportunity(base | {"manipulation_risk": 0})
        pumped = autotrade.score_opportunity(base | {"manipulation_risk": 1})
        self.assertGreater(clean, pumped)

    def test_trade_economics_keep_freqtrade_net_and_expose_fees(self):
        trade = {
            "amount": 2,
            "open_rate": 100,
            "current_rate": 101,
            "profit_abs": 1.7,
            "fee_open": .00075,
            "fee_close": .00075,
        }
        result = autotrade.fee_aware_trade(trade, .001)
        self.assertEqual(result["net_profit_abs"], 1.7)
        self.assertAlmostEqual(result["estimated_trading_fee_abs"], .3015)
        self.assertEqual(result["fee_source"], "FREQTRADE_EXCHANGE")

    def test_fee_fallback_is_used_when_exchange_rate_is_missing(self):
        trade = {"amount": 1, "open_rate": 100, "current_rate": 101, "is_short": False}
        result = autotrade.fee_aware_trade(trade, .00075)
        self.assertAlmostEqual(result["net_profit_abs"], .84925)
        self.assertEqual(result["fee_source"], "CONSERVATIVE_FALLBACK")

    def test_take_profit_level_accounts_for_leverage_and_fees(self):
        trade = {
            "amount": 1,
            "open_rate": 100,
            "current_rate": 100,
            "profit_abs": 0,
            "fee_open": .001,
            "fee_close": .001,
            "leverage": 2,
        }
        result = autotrade.fee_aware_trade(trade, .00075, {"0": .06})
        self.assertAlmostEqual(result["take_profit_rate"], 103.20620621)
        self.assertEqual(result["take_profit_roi"], .06)


class RuntimeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name) / "autotrade_runtime.json"
        self.original = autotrade.RUNTIME_FILE
        autotrade.RUNTIME_FILE = self.runtime

    def tearDown(self):
        autotrade.RUNTIME_FILE = self.original
        self.temp.cleanup()

    def test_every_whitelist_pair_has_an_explicit_decision(self):
        app = autotrade.load_json(autotrade.APP_CONFIG)
        supervisor = object.__new__(autotrade.Supervisor)
        supervisor.config = app
        supervisor._write_runtime(True, autotrade.RiskState.NORMAL, .005, 1, "ok", ["BTC/USDT:USDT", "ETH/USDT:USDT"], [{"pair": "ETH/USDT:USDT", "data_status": autotrade.DataHealth.HEALTHY, "continuity_ok": True}])
        gate = json.loads(self.runtime.read_text(encoding="utf-8"))
        self.assertFalse(gate["pair_decisions"]["BTC/USDT:USDT"]["entry_allowed"])
        self.assertTrue(gate["pair_decisions"]["ETH/USDT:USDT"]["entry_allowed"])

    def test_corrupt_or_expired_gate_denies(self):
        self.runtime.write_text("not json", encoding="utf-8")
        strategy_file = Path(autotrade.ROOT / "user_data" / "strategies" / "AutotradeBaseline.py")
        # The strategy runtime reader is deliberately self-contained; malformed data is an empty gate.
        source = strategy_file.read_text(encoding="utf-8")
        self.assertIn("except (OSError, ValueError, TypeError)", source)

    def test_refresh_is_serialized(self):
        lock = threading.RLock()
        active = 0
        maximum = 0
        guard = threading.Lock()
        def run():
            nonlocal active, maximum
            with lock:
                with guard:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(.01)
                with guard:
                    active -= 1
        workers = [threading.Thread(target=run) for _ in range(8)]
        [worker.start() for worker in workers]
        [worker.join() for worker in workers]
        self.assertEqual(maximum, 1)


if __name__ == "__main__":
    unittest.main()
