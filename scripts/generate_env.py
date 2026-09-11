"""Create strong localhost API credentials without printing them."""

from pathlib import Path
import secrets


path = Path(__file__).resolve().parents[1] / ".env"
required = {
    "FREQTRADE__API_SERVER__USERNAME": "autotrade",
    "FREQTRADE__API_SERVER__PASSWORD": secrets.token_hex(24),
    "FREQTRADE__API_SERVER__JWT_SECRET_KEY": secrets.token_hex(32),
    "FREQTRADE__API_SERVER__WS_TOKEN": secrets.token_hex(24),
}
current = {}
if path.exists():
    current = dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
if not all(len(current.get(key, "")) >= (8 if key.endswith("USERNAME") else 32) for key in required):
    path.write_text("".join(f"{key}={value}\n" for key, value in required.items()), encoding="utf-8")
    print("Generated local Freqtrade API credentials in .env")
else:
    print("Existing .env credentials retained")
