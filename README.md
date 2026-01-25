# 🔍 Scan Somnia Wallet Bot  

Telegram bot for checking wallet balances in the **Somnia Network**.  
Displays native **SOMI** balance and supported ERC-20 token balances in real time.  

![Bot Preview](https://img.shields.io/badge/Telegram-Bot-blue) ![Python](https://img.shields.io/badge/Python-3.8%2B-green) ![Web3](https://img.shields.io/badge/Web3.py-latest-orange)

## ✨ Features  

- 📊 **Balance Check**:  
  - Native **SOMI** (Gas Token)  
  - Supported ERC-20 tokens:  
    - USDC.e (Bridged USDC)  
    - ArWSOMI (Arenas Somnia)  
    - WSOMI (Wrapped SOMI)  
- 💰 **Current SOMI price** via CoinGecko API  
- 🔁 **Automatic fallback** between multiple RPC nodes  
- 🔄 **Rescan wallet** without re-entering address  
- ℹ️ **Somnia Network information** (documentation, website, add to wallet)  
- 👨‍💻 **Developer information**  

## 🛠 Technologies  

- `python-telegram-bot` — Telegram API interaction  
- `web3.py` — Somnia blockchain interaction  
- `requests` — fetching token price data  
- Multiple RPC providers for failover reliability  

## 🚀 Installation and Launch  

### Prerequisites  
- Python 3.8 or higher  
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation  

1. Clone the repository:  
```bash
git clone https://github.com/your-repo/somnia-wallet-scanner.git
cd somnia-wallet-scanner
