"""Save a reproducible static research universe from Freqtrade test-pairlist JSON."""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--timerange", required=True)
args = parser.parse_args()
result = subprocess.run(["freqtrade", "test-pairlist", "--config", "user_data/config.json", "--print-json"], cwd=root, check=True, capture_output=True, text=True)
pairs = json.loads(result.stdout)
if isinstance(pairs, dict): pairs = pairs.get("whitelist", [])
config = json.loads((root / "user_data/config.research.json").read_text(encoding="utf-8"))
config["exchange"]["pair_whitelist"] = pairs
(root / "research").mkdir(exist_ok=True)
(root / "research/pair_snapshot.json").write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "source_config": "user_data/config.json", "timerange": args.timerange, "pairs": pairs}, indent=2), encoding="utf-8")
(root / "user_data/config.research.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
