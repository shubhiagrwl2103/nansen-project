import os
import sys
import json
import pathlib
import requests
import pandas as pd
from datetime import datetime, timezone, date, timedelta
from dotenv import load_dotenv

# =========================================================
# Config
# =========================================================
load_dotenv()

API_KEY = os.getenv("NANSEN_API_KEY")
TG_BOT = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")
KRAKEN_PAIR = os.getenv("KRAKEN_PAIR", "XETHZUSD")

# ETH proxy / LST addresses on Ethereum (lowercased)
ETH_ADDR_BASKET = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",  # Lido stETH
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0",  # Lido wstETH
    "0xae78736cd615f374d3085123a210448e74fc6393",  # Rocket Pool rETH
    "0xbe9895146f7af43049ca1c1ae358b0541ea49704",  # Coinbase cbETH
    "0x5e8422345238f34275888049021821e8e08caa1f",  # Frax frxETH
    "0xac3e018457b222d93114458476f3e3416abbe38f",  # Frax sfrxETH
    "0x35fa164735182de50811e8e2e824cfb9b6118ac2",  # ether.fi eETH
    "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee",  # ether.fi weETH
    "0xf1c9acdc66974dfb6decb12aa385b9cd01190e38",  # StakeWise osETH
    "0xf951e335afb289353dc249e82926178eac7ded78",  # Swell swETH
}

HEADERS = {
    "apiKey": API_KEY,
    "Content-Type": "application/json",
    "Accept": "*/*",
}

BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
for p in (DATA_DIR, LOGS_DIR):
    p.mkdir(exist_ok=True)

F_SM = DATA_DIR / "eth_smart_money_flows.parquet"
F_EX = DATA_DIR / "eth_exchange_flows.parquet"
F_PX = DATA_DIR / "eth_prices.parquet"
F_SIG = DATA_DIR / "eth_signals.parquet"

ROLL_SPAN = 60   # EW rolling span for z-scores
MIN_PERIODS = 5 # minimum periods before z-scores start being meaningful
TODAY = date.today()

SMART_MONEY_URL = "https://api.nansen.ai/api/beta/smart-money/inflows"
FLOW_INTEL_URL = "https://api.nansen.ai/api/beta/tgm/flow-intelligence"
KRAKEN_OHLC_URL = f"https://api.kraken.com/0/public/OHLC?pair={KRAKEN_PAIR}&interval=1440"


# =========================================================
# Utils
# =========================================================
def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[{ts}] {msg}")


def read_parquet_safe(path: pathlib.Path, schema=None) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(schema or {})


def append_parquet(df_new: pd.DataFrame,
                   path: pathlib.Path,
                   dedupe_cols=("ts",)) -> pd.DataFrame:
    df_old = read_parquet_safe(path)
    df_all = pd.concat([df_old, df_new], ignore_index=True)
    df_all = df_all.drop_duplicates(subset=list(dedupe_cols), keep="last")
    df_all.to_parquet(path, index=False)
    return df_all


#def zscore_ewm(series: pd.Series,
#               span: int = ROLL_SPAN,
#               min_periods: int = MIN_PERIODS) -> pd.Series:
#    mean = series.ewm(span=span, min_periods=min_periods).mean()
#    std = series.ewm(span=span, min_periods=min_periods).std()
#    return (series - mean) / std

def zscore_ewm(series, span=ROLL_SPAN, min_periods=MIN_PERIODS):
    mean = series.ewm(span=span, min_periods=min_periods).mean()
    std  = series.ewm(span=span, min_periods=min_periods).std().replace(0, 1e-12)
    z = (series - mean) / std
    return z.fillna(0.0).replace([float("inf"), -float("inf")], 0.0)


def send_telegram(text: str) -> None:
    if not TG_BOT or not TG_CHAT:
        log("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; skipping Telegram.")
        return
    url = f"https://api.telegram.org/bot{TG_BOT}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log(f"[WARN] Telegram send failed: {e}")


# =========================================================
# Fetchers
# =========================================================
WETH_ADDR = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2".lower()

def fetch_smart_money_inflows_eth() -> pd.DataFrame:
    """
    Multi-page Smart Money inflows with proper pagination.
    
    Based on Nansen API documentation: https://docs.nansen.ai/api/smart-money
    - Uses proper pagination structure to get all ETH tokens across multiple pages
    - ETH tokens are found on pages 2-3, not just page 1
    - Aggregates ETH activity by:
        * L1 (ethereum): tokenAddress in ETH_ADDR_BASKET
        * All chains: exact symbol match in ETH/LST symbol basket
    """
    import os

    # ETH/LST symbols (exact, case-insensitive)
    ETH_SYMBOL_BASKET = {
        "ETH", "WETH",
        "STETH", "WSTETH", 
        "RETH", "CBETH",
        "FRXETH", "SFRXETH",
        "EETH", "WEETH",
        "OSETH", "SWETH",
    }

    # Use proper pagination structure from Nansen API docs
    base_payload = {
        "parameters": {
            "smFilter": ["180D Smart Trader", "Fund", "Smart Trader"],
            "chains": ["ethereum"],
            "includeStablecoin": False,
            "includeNativeTokens": True,
            "excludeSmFilter": []
        },
        "pagination": {
            "page": 1,
            "recordsPerPage": 100
        }
    }

    all_data = []
    all_eth_tokens = []
    max_pages = 5  # Check first 5 pages to capture all ETH tokens

    log(f"Fetching Smart Money data with pagination (max {max_pages} pages)...")

    for page in range(1, max_pages + 1):
        # Update page number
        payload = base_payload.copy()
        payload["pagination"]["page"] = page
        
        try:
            log(f"  Page {page}...")
            r = requests.post(SMART_MONEY_URL, headers=HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            
            data = r.json()
            if not data:  # Empty page, we've reached the end
                log(f"  Page {page}: Empty, stopping pagination")
                break
                
            log(f"  Page {page}: {len(data)} tokens")
            all_data.extend(data)
            
            # Look for ETH tokens on this page
            page_eth_tokens = []
            for d in data:
                ch = (d.get("chain") or "").lower()
                addr = (d.get("tokenAddress") or "").lower()
                sym = (d.get("symbol") or d.get("tokenSymbol") or "").replace("🌱", "").strip().upper()
                
                is_l1_eth_addr = (ch == "ethereum" and addr in ETH_ADDR_BASKET)
                is_eth_symbol = (sym in ETH_SYMBOL_BASKET)
                
                if is_l1_eth_addr or is_eth_symbol:
                    eth_token = {
                        "symbol": sym,
                        "address": addr,
                        "vol24h": d.get("volume24hUSD"),
                        "vol7d": d.get("volume7dUSD"),
                        "vol30d": d.get("volume30dUSD"),
                        "page": page,
                        "matched_by": "address" if is_l1_eth_addr else "symbol"
                    }
                    page_eth_tokens.append(eth_token)
                    all_eth_tokens.append(d)  # Keep original data for aggregation
            
            if page_eth_tokens:
                log(f"  Page {page}: Found {len(page_eth_tokens)} ETH tokens:")
                for token in page_eth_tokens:
                    vol7d = token["vol7d"] or 0
                    vol30d = token["vol30d"] or 0
                    log(f"    {token['symbol']:8s} | 7d: {vol7d:>10,.0f} | 30d: {vol30d:>10,.0f}")
            
        except Exception as e:
            log(f"  Page {page}: Failed - {e}")
            # Don't break, try next page
            continue

    log(f"Pagination complete. Total tokens: {len(all_data)}, ETH tokens: {len(all_eth_tokens)}")

    # Aggregate ETH token volumes across all pages
    vol24 = vol7 = vol30 = 0.0
    matches = []
    dedupe_addresses = set()  # Avoid double-counting same token on multiple pages
    
    for d in all_eth_tokens:
        ch = (d.get("chain") or "").lower()
        addr = (d.get("tokenAddress") or "").lower()
        sym = (d.get("symbol") or d.get("tokenSymbol") or "").replace("🌱", "").strip().upper()
        
        # Dedupe by address to avoid counting same token multiple times
        if addr in dedupe_addresses:
            continue
        dedupe_addresses.add(addr)
        
        matches.append({
            "chain": ch,
            "symbol": sym,
            "tokenAddress": d.get("tokenAddress"),
            "vol24h": d.get("volume24hUSD"),
            "vol7d": d.get("volume7dUSD"),
            "vol30d": d.get("volume30dUSD"),
            "matched_by": "address" if (ch == "ethereum" and addr in ETH_ADDR_BASKET) else "symbol"
        })
        
        try:
            vol24 += float(d.get("volume24hUSD") or 0)
            vol7 += float(d.get("volume7dUSD") or 0)
            vol30 += float(d.get("volume30dUSD") or 0)
        except Exception:
            pass

    # Debug output
    log(f"ETH Smart Money aggregation:")
    log(f"  Unique ETH tokens found: {len(matches)}")
    log(f"  24h volume: ${vol24:,.0f}")
    log(f"  7d volume:  ${vol7:,.0f}")
    log(f"  30d volume: ${vol30:,.0f}")
    
    if matches:
        log("ETH tokens breakdown:")
        for match in matches:
            vol7d = match["vol7d"] or 0
            vol30d = match["vol30d"] or 0
            log(f"  {match['symbol']:8s} | 7d: {vol7d:>12,.0f} | 30d: {vol30d:>12,.0f}")

    return pd.DataFrame([{
        "ts": TODAY,
        "symbol": "ETH_BASKET_MULTI",
        "volume24hUSD": vol24,
        "volume7dUSD": vol7,
        "volume30dUSD": vol30
    }])

def fetch_flow_intelligence_eth() -> pd.DataFrame:
    """
    Try Flow Intelligence for WETH (since native ETH often 400s).
    If it still fails, we return None and let the strategy proceed.
    """
    payloads = [
        # 1) Minimal, tokenAddress=WETH
        {
            "parameters": {
                "chain": "ethereum",
                "tokenAddress": WETH_ADDR,
                "timeframe": "1d"
            }
        },
        # 2) Try without tokenAddress (just in case your key supports native)
        {
            "parameters": {
                "chain": "ethereum",
                "timeframe": "1d"
            }
        },
    ]

    last_err = None
    for p in payloads:
        try:
            r = requests.post(FLOW_INTEL_URL, headers=HEADERS, json=p, timeout=30)
            r.raise_for_status()
            js = r.json()

            # Nansen often returns a list, sometimes wrapped. Handle both.
            if isinstance(js, dict) and "data" in js:
                data = js["data"]
            elif isinstance(js, list):
                data = js
            else:
                # Unexpected shape — dump and fallback
                log("WARN: Unexpected JSON from flow-intelligence, dumping:")
                log(json.dumps(js, indent=2))
                return pd.DataFrame([{"ts": TODAY, "exchange_flow_usd": None}])

            if not data:
                log("INFO: Flow intelligence returned empty data.")
                return pd.DataFrame([{"ts": TODAY, "exchange_flow_usd": None}])

            # DEBUG: Log what Flow Intelligence is returning
            log(f"Flow Intelligence returned {len(data)} records:")
            log(f"First record: {json.dumps(data[0], indent=2)}")

            row = data[0]
            ex_flow = (
                row.get("exchangeFlowUSD")
                or row.get("exchangeFlow")
                or row.get("exchangeNetflowUSD")
                or row.get("exchangeNetflow")
                or 0
            )
            try:
                ex_flow = float(ex_flow)
                log(f"Flow Intelligence found ETH exchange flow: ${ex_flow:.2f}")
            except Exception:
                log("WARN: exchange_flow_usd could not be cast to float, dumping row:")
                log(json.dumps(row, indent=2))
                ex_flow = None

            return pd.DataFrame([{"ts": TODAY, "exchange_flow_usd": ex_flow}])

        except requests.HTTPError as e:
            last_err = f"{e} :: {getattr(e.response, 'text', '')}"
            # Try the next payload variation
            continue
        except Exception as e:
            last_err = str(e)
            continue

    # All attempts failed — don’t crash the whole run, just log & return None
    log(f"Flow Intelligence failed on all payloads. Returning None. Last error: {last_err}")
    return pd.DataFrame([{"ts": TODAY, "exchange_flow_usd": None}])


#def fetch_kraken_price_eth() -> pd.DataFrame:
#    """
#    Public (no-key) OHLC daily close.
#    """
#    r = requests.get(KRAKEN_OHLC_URL, timeout=15)
#    r.raise_for_status()
#    js = r.json()["result"]
#    key = next(k for k in js.keys() if k != "last")
#    last_bar = js[key][-1]  # [time, o, h, l, c, v, ...]
#    ts = date.fromtimestamp(last_bar[0])
#    close = float(last_bar[4])
#    return pd.DataFrame([{"ts": ts, "price_usd": close}])

def fetch_kraken_price_eth() -> pd.DataFrame:
    r = requests.get(KRAKEN_OHLC_URL, timeout=15)
    r.raise_for_status()
    js = r.json()["result"]
    key = next(k for k in js.keys() if k != "last")
    last_bar = js[key][-1]
    close = float(last_bar[4])
    return pd.DataFrame([{"ts": TODAY, "price_usd": close}])


# =========================================================
# Signal calc
# =========================================================
def build_signal(sm_df: pd.DataFrame,
                 ex_df: pd.DataFrame,
                 px_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge all series, compute z-scores on 7d volumes and price returns,
    and output daily signals.
    """
    df = (
        sm_df.set_index("ts")
        .join(ex_df.set_index("ts"), how="outer")
        .join(px_df.set_index("ts"), how="outer")
        .sort_index()
    )

    # Price returns
    df["px_ret_7d"] = df["price_usd"].pct_change(7, fill_method=None)
    df["px_ret_30d"] = df["price_usd"].pct_change(30, fill_method=None)
   
    # z-scores on 7d and 30d SM volumes
    df["sm_7d_z"] = zscore_ewm(df["volume7dUSD"])
    df["sm_30d_z"] = zscore_ewm(df["volume30dUSD"])

    # z on px returns for divergence calc
    df["px_ret_7d_z"] = zscore_ewm(df["px_ret_7d"])
    df["px_ret_30d_z"] = zscore_ewm(df["px_ret_30d"])

    df["divergence_7d"] = df["sm_7d_z"] - df["px_ret_7d_z"]
    df["divergence_30d"] = df["sm_30d_z"] - df["px_ret_30d_z"]

    def decide(row):
        if pd.isna(row["sm_7d_z"]) or pd.isna(row["px_ret_7d"]):
            return "hold"

        # Bullish: SM buying (z > 1.5) while price is flat/down; confirm no big CEX inflow
        if row["sm_7d_z"] > 1.5 and (row["px_ret_7d"] is not None and row["px_ret_7d"] <= 0):
            if (row.get("exchange_flow_usd") is None) or (row["exchange_flow_usd"] <= 0):
                return "long"

        # Bearish / exit: SM flow z < 0
        if row["sm_7d_z"] < 0:
            return "flat"

        return "hold"

    df["signal"] = df.apply(decide, axis=1)
    return df.reset_index()


# =========================================================
# Main
# =========================================================
def main():
    try:
        log("Fetching Smart Money inflows (ETH)...")
        sm = fetch_smart_money_inflows_eth()
        sm_all = append_parquet(sm, F_SM, dedupe_cols=("ts",))

    # Seed 6 dummy days so z-scores don't stay NaN at the start
        if len(sm_all) == 1:   # first run only (we only have today's row)
            rows = []
            for i in range(6, 0, -1):
                rows.append({
                    "ts": TODAY - timedelta(days=i),
                    "symbol": "ETH/WETH",
                    "volume24hUSD": 0.0,
                    "volume7dUSD": 0.0,
                    "volume30dUSD": 0.0
                })
            sm_all = append_parquet(pd.DataFrame(rows), F_SM, dedupe_cols=("ts",))

        log("Fetching Flow Intelligence (ETH -> Exchanges)...")
        ex = fetch_flow_intelligence_eth()
        ex_all = append_parquet(ex, F_EX, dedupe_cols=("ts",))

        log("Fetching Kraken price...")
        px = fetch_kraken_price_eth()
        px_all = append_parquet(px, F_PX, dedupe_cols=("ts",))

        log("Building signal...")
        signals_all = build_signal(sm_all, ex_all, px_all)
        today_sig = signals_all[signals_all["ts"] == TODAY].copy()
        if today_sig.empty:
            # Fallback to last available row
            today_sig = signals_all.tail(1).copy()

        append_parquet(today_sig, F_SIG, dedupe_cols=("ts",))

        r = today_sig.iloc[-1].to_dict()

        def fmt(x, f):
            try:
                return f.format(x)
            except Exception:
                return str(x)

        msg = (
            f"*ETH Smart Money Signal — {r.get('ts')}*\n"
            f"Signal: *{r.get('signal', 'NA').upper()}*\n"
            f"Price: {fmt(r.get('price_usd'), '${:,.2f}')}\n"
            f"SM 7d z-score: {fmt(r.get('sm_7d_z'), '{:.2f}')}\n"
            f"SM 30d z-score: {fmt(r.get('sm_30d_z'), '{:.2f}')}\n"
            f"7d px return: {fmt(r.get('px_ret_7d'), '{:.2%}')}\n"
            f"Net flow to exchanges (USD): {r.get('exchange_flow_usd')}\n"
            f"Divergence 7d: {fmt(r.get('divergence_7d'), '{:.2f}')}"
        )
        send_telegram(msg)
        log("Done.")

    except Exception as e:
        err = f"[ERROR] {datetime.now(timezone.utc)} {e}"
        log(err)
        send_telegram(f"⚠️ ETH SM job failed: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

