# bootstrap_prices.py
import os, requests, pandas as pd
from datetime import date
from pathlib import Path

KRAKEN_PAIR = os.getenv("KRAKEN_PAIR", "XETHZUSD")
DATA_DIR = Path("data"); DATA_DIR.mkdir(exist_ok=True)
PRICES = DATA_DIR / "eth_prices.parquet"

def pull_ohlc(days=90):
    url = f"https://api.kraken.com/0/public/OHLC?pair={KRAKEN_PAIR}&interval=1440"
    r = requests.get(url, timeout=15); r.raise_for_status()
    js = r.json()["result"]
    key = next(k for k in js.keys() if k != "last")
    rows = []
    for o in js[key][-days:]:
        ts, close = o[0], float(o[4])
        rows.append({"ts": date.fromtimestamp(ts), "price_usd": close})
    return pd.DataFrame(rows)

if __name__ == "__main__":
    df = pull_ohlc(90)
    if PRICES.exists():
        old = pd.read_parquet(PRICES)
        df = pd.concat([old, df]).drop_duplicates(subset=["ts"]).sort_values("ts")
    df.to_parquet(PRICES, index=False)
    print(df.tail())

