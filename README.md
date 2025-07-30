# 🚀 ETH Smart Money Trading Bot

An automated trading signal generator that tracks Ethereum smart money flows using Nansen API data to identify optimal entry/exit points for ETH positions.

## 📊 Overview

This bot analyzes the trading patterns of sophisticated investors ("smart money") across multiple Ethereum Layer 1 and Layer 2 networks to generate data-driven trading signals. It combines smart money flow data, exchange flow intelligence, and statistical analysis to detect market anomalies and potential trading opportunities.

## ✨ Features

- **📈 Real-time Smart Money Tracking**: Monitors 11+ major ETH/LST tokens across multiple chains
- **🧠 Statistical Analysis**: Uses exponentially weighted z-scores for anomaly detection
- **📱 Telegram Integration**: Automated signal notifications with detailed metrics
- **💾 Data Persistence**: Historical data storage in Parquet format for backtesting
- **🔄 Multi-page API Integration**: Proper pagination to capture all relevant tokens
- **⚡ Robust Error Handling**: Graceful fallbacks for API failures

## 🎯 Trading Logic

### Signal Generation Rules

- **LONG** 🟢: Smart money z-score > 1.5 + price flat/declining + no major CEX inflows
- **FLAT** 🔴: Smart money z-score < 0 (bearish sentiment)  
- **HOLD** 🟡: Default state when conditions aren't met

### Tracked Assets

| Asset | Type | Address | Description |
|-------|------|---------|-------------|
| WETH | Wrapped ETH | `0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2` | Wrapped Ethereum |
| stETH | LST | `0xae7ab96520de3a18e5e111b5eaab095312d7fe84` | Lido Staked ETH |
| wstETH | LST | `0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0` | Wrapped Lido stETH |
| rETH | LST | `0xae78736cd615f374d3085123a210448e74fc6393` | Rocket Pool ETH |
| cbETH | LST | `0xbe9895146f7af43049ca1c1ae358b0541ea49704` | Coinbase Wrapped ETH |
| swETH | LST | `0xf951e335afb289353dc249e82926178eac7ded78` | Swell ETH |
| weETH | LST | `0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee` | ether.fi Wrapped eETH |
| +4 more | LST | ... | Additional liquid staking tokens |

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- [Nansen API key](https://docs.nansen.ai/) 
- Telegram Bot (optional, for notifications)

### Installation

1. **Clone and setup environment:**
```bash
git clone <repository-url>
cd nansen-project
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure environment variables:**
```bash
cp .env.example .env
# Edit .env with your API keys
```

3. **Initialize price data:**
```bash
python bootstrap_prices.py
```

4. **Run the bot:**
```bash
python main.py
```

## ⚙️ Configuration

Create a `.env` file in the project root:

```env
# Required
NANSEN_API_KEY=your_nansen_api_key_here

# Optional - Telegram notifications
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# Optional - Trading pair (default: XETHZUSD)
KRAKEN_PAIR=XETHZUSD

# Optional - Supported chains (default: ethereum,arbitrum,base,optimism,polygon)
NANSEN_CHAINS=ethereum,arbitrum,base,optimism,polygon
```

### API Key Setup

1. **Nansen API**: 
   - Sign up at [Nansen.ai](https://nansen.ai)
   - Navigate to API section in dashboard
   - Generate new API key
   - Documentation: https://docs.nansen.ai/api/smart-money

2. **Telegram Bot** (Optional):
   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Create new bot with `/newbot`
   - Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot)

## 📁 Project Structure

```
nansen-project/
├── main.py                 # Main trading bot logic
├── bootstrap_prices.py     # Historical price data initialization
├── requirements.txt        # Python dependencies
├── .env                   # Environment configuration
├── .gitignore            # Git ignore patterns
├── data/                 # Data storage directory
│   ├── eth_smart_money_flows.parquet    # Smart money flow data
│   ├── eth_exchange_flows.parquet       # Exchange flow data
│   ├── eth_prices.parquet              # Price history
│   └── eth_signals.parquet             # Generated signals
└── logs/                 # Application logs
```

## 📊 Data Sources

- **[Nansen Smart Money API](https://docs.nansen.ai/api/smart-money)**: Flow data from top 5,000 performing wallets
- **[Kraken API](https://docs.kraken.com/rest/)**: ETH price data (OHLC daily)
- **Nansen Flow Intelligence**: Exchange flow metrics

## 🔧 Usage Examples

### Basic Usage
```bash
# Run once
python main.py

# Setup cron job for automated execution
# Example: Run every 6 hours
0 */6 * * * cd /path/to/nansen-project && /path/to/.venv/bin/python main.py
```

### Data Analysis
```python
import pandas as pd

# Load historical signals
signals = pd.read_parquet('data/eth_signals.parquet')
print(signals.tail())

# Analyze performance
recent_signals = signals.tail(30)
print(f"Recent signals distribution:")
print(recent_signals['signal'].value_counts())
```

### Custom Configuration
```python
# Override default settings in main.py
ROLL_SPAN = 30      # Change rolling window for z-scores
MIN_PERIODS = 3     # Minimum periods for meaningful z-scores
```

## 📈 Signal Output

### Console Output
```
[2025-07-30T02:30:52.818745+00:00] Fetching Smart Money inflows (ETH)...
[2025-07-30T02:30:54.218380+00:00]     WETH    | 7d:      8,683 | 30d:   -152,533
[2025-07-30T02:30:56.010652+00:00]     STETH   | 7d:    -14,271 | 30d: -33,355,661
[2025-07-30T02:31:00.000547+00:00] ETH tokens breakdown:
[2025-07-30T02:31:02.877330+00:00] Done.
```

### Telegram Message
```
*ETH Smart Money Signal — 2025-07-29*
Signal: *HOLD*
Price: $3,805.31
SM 7d z-score: -0.44
SM 30d z-score: -2.32
7d px return: 1.23%
Net flow to exchanges (USD): $-63,491,642
Divergence 7d: -1.67
```

## 🛠️ Troubleshooting

### Common Issues

**1. Zero Volume Data**
```bash
# Check API key configuration
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('API Key:', 'SET' if os.getenv('NANSEN_API_KEY') else 'MISSING')"

# Verify API pagination is working
grep "Page.*Found.*ETH tokens" logs/*.log
```

**2. API Rate Limits**
- Nansen Pro plan recommended for production use
- Check current rate limits in dashboard
- Increase timeout values if needed

**3. Missing Dependencies**
```bash
pip install -r requirements.txt
```

**4. Data Directory Permissions**
```bash
# Ensure data directory is writable
chmod -R 755 data/ logs/
```

## 📋 API Documentation

This bot integrates with multiple APIs:

- **[Nansen Smart Money API](https://docs.nansen.ai/api/smart-money)** - Primary data source
- **[Nansen Flow Intelligence](https://docs.nansen.ai/api/tgm)** - Exchange flow data  
- **[Kraken Public API](https://docs.kraken.com/rest/)** - Price data

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## ⚠️ Disclaimer

This tool is for educational and research purposes only. It does not constitute financial advice. Always do your own research and consider the risks before making any trading decisions.

- Past performance does not guarantee future results
- Cryptocurrency trading involves substantial risk
- Never invest more than you can afford to lose

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- [Nansen.ai](https://nansen.ai) - On-chain analytics platform
- [Nansen API Docs](https://docs.nansen.ai/) - Complete API documentation
- [Telegram Bot API](https://core.telegram.org/bots/api) - Bot integration guide

---

*Built with ❤️ for the Ethereum ecosystem* 