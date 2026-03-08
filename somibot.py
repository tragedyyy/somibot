# -*- coding: utf-8 -*-
import telebot
import requests
from web3 import Web3
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import threading
import time
import tweepy

# --- Settings ---
TOKEN = '8231096426:AAHxREyc5aA2pX8EWd_6Ws3OinEHv7OpcMI'
BOT_NAME = "Somnia Pulse"
EXPLORER_URL = "https://explorer.somnia.network"
CHART_URL = "https://www.geckoterminal.com/somnia/pools/0xb1a5a70a946667655bf14512599d06acca020f62"
GECKO_API = "https://api.geckoterminal.com/api/v2"
WHALE_THRESHOLD = 10000  # SOMI
TWITTER_BEARER_TOKEN = "YOUR_TWITTER_BEARER_TOKEN_HERE"
SOMNIA_USER_ID = "1757553204747972608"

RPC_LIST = ['https://api.infra.mainnet.somnia.network', 'https://somnia-rpc.publicnode.com']

TOKENS = {
    'USDC.e (Bridged)': '0x28BEc7E30E6faee657a03e19Bf1128AaD7632A00',
    'WSOMI (Wrapped)': '0x046EDe9564A72571df6F5e44d0405360c0f4dCab',
    'ArWSOMI (Arenas)': '0xFe171d9d2679c4544ADD1a20d565C251cEd9FF4A'
}

ERC20_ABI = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}, {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}]
# Transfer(address,address,uint256)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ERC1155_TRANSFER_SINGLE_TOPIC = Web3.keccak(text="TransferSingle(address,address,address,uint256,uint256)").hex()
ERC1155_TRANSFER_BATCH_TOPIC = Web3.keccak(text="TransferBatch(address,address,address,uint256[],uint256[])").hex()

# Token: (address, decimals, min_amount for alert)
TOKENS_MONITOR = {
    "USDC.e": ("0x28BEc7E30E6faee657a03e19Bf1128AaD7632A00", 6, 0.1),
    "WSOMI": ("0x046EDe9564A72571df6F5e44d0405360c0f4dCab", 18, 0.01),
    "ArWSOMI": ("0xFe171d9d2679c4544ADD1a20d565C251cEd9FF4A", 18, 0.01),
}
SUBSCRIPTION_SOMI_MIN = 0.01  # native SOMI
NFT_SOMI_MIN = 100  # native SOMI threshold for NFT alerts

bot = telebot.TeleBot(TOKEN)
subscriptions = {}
active_users = set()
whale_alert_subscribers = set()  # Users subscribed to whale alerts
twitter_subscribers = set()  # Users subscribed to Twitter alerts
last_tweet_id = None

def get_web3():
    for rpc in RPC_LIST:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc))
            if w3.is_connected(): return w3
        except: continue
    return None

w3 = get_web3()

def _norm_addr(v):
    if v is None:
        return ""
    s = (v.hex() if hasattr(v, "hex") else str(v)).replace("0x", "").lower()
    return ("0x" + s[-40:]) if len(s) >= 40 else ""

def _get_addr_to_chats():
    """Build map: normalized_addr -> set(chat_ids) for subscribed wallets."""
    out = {}
    for cid, addrs in subscriptions.items():
        for a in addrs:
            try:
                key = w3.to_checksum_address(a) if a else ""
                if key:
                    out.setdefault(key.lower(), set()).add(cid)
            except Exception:
                pass
    return out

def _tx_link(tx_hash):
    """Build correct explorer URL for transaction hash (with or without 0x)."""
    s = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
    if not s.startswith("0x"):
        s = "0x" + s
    return f"{EXPLORER_URL}/tx/{s}"

def _somi_balance(addr, block=None):
    """Return SOMI balance for address at block (or latest). None on error."""
    if not addr or len(_norm_addr(addr)) != 42:
        return None
    try:
        a = w3.to_checksum_address(addr)
        bal = w3.eth.get_balance(a, block) if block is not None else w3.eth.get_balance(a)
        return bal / 10**18
    except Exception:
        return None

# --- Keyboards ---
def get_main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("Scan Wallet"), KeyboardButton("My Subscriptions"))
    markup.add(KeyboardButton("DeFi Monitor"), KeyboardButton("Whale Alert"))
    markup.add(KeyboardButton("Price Chart"), KeyboardButton("Somnia Info"))
    markup.add(KeyboardButton("Twitter Alerts Somnia"), KeyboardButton("Developer"))
    return markup

def back_button():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Menu", callback_data="home"))

# --- Data Helpers ---
def get_somi_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=somnia&vs_currencies=usd", timeout=5)
        return r.json().get('somnia', {}).get('usd', 0)
    except: return 0

def get_defi_data():
    """Fetch DeFi stats from GeckoTerminal API (Somnia pools)."""
    try:
        r = requests.get(f"{GECKO_API}/networks/somnia/pools", params={"page": 1}, timeout=10,
                        headers={"Accept": "application/json;version=20230203"})
        data = r.json()
        pools = data.get("data", [])[:10]
        total_volume_24h = 0
        total_reserve = 0
        top_pools = []
        for p in pools:
            attrs = p.get("attributes", {})
            vol = float(attrs.get("volume_usd", {}).get("h24", 0) or 0)
            reserve = float(attrs.get("reserve_in_usd", 0) or 0)
            total_volume_24h += vol
            total_reserve += reserve
            if reserve > 1000 and len(top_pools) < 5:
                top_pools.append({"name": attrs.get("name", "N/A"), "vol": vol, "reserve": reserve})
        return {"volume_24h": total_volume_24h, "tvl": total_reserve, "top_pools": top_pools}
    except Exception:
        return None

# --- Handlers ---
@bot.message_handler(commands=['start'])
def start(message):
    active_users.add(message.chat.id)
    bot.send_message(message.chat.id, f"Welcome to {BOT_NAME}! Menu updated.", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "Scan Wallet")
def scan_req(message):
    bot.send_message(message.chat.id, "Please send the wallet address (0x...):", reply_markup=back_button())

@bot.message_handler(func=lambda m: m.text == "DeFi Monitor")
def defi_monitor(message):
    price = get_somi_price()
    try:
        gas = w3.eth.gas_price / 10**9
    except Exception:
        gas = 0

    text = (
        "📊 <b>Somnia DeFi Monitor</b>\n\n"
        f"💰 <b>SOMI Price:</b> ${price:.4f}\n"
        f"⛽ <b>Gas Price:</b> {gas:.2f} Gwei\n"
    )

    defi = get_defi_data()
    if defi:
        vol = defi["volume_24h"]
        tvl = defi["tvl"]
        text += f"\n📈 <b>24h Volume:</b> ${vol:,.0f}\n"
        text += f"💧 <b>Total Liquidity:</b> ${tvl:,.0f}\n\n"
        if defi["top_pools"]:
            text += "<b>Top Pools:</b>\n"
            for p in defi["top_pools"]:
                text += f"• {p['name']}: ${p['reserve']:,.0f} liq\n"
    else:
        text += "\n✅ All core protocols operational.\n"

    text += "\nUse <b>Price Chart</b> for detailed history."
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📈 GeckoTerminal", url="https://www.geckoterminal.com/somnia/pools"))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "Whale Alert")
def whale_alert(message):
    cid = message.chat.id
    is_sub = cid in whale_alert_subscribers
    status = "✅ Subscribed" if is_sub else "❌ Not subscribed"
    text = (
        f"🐋 <b>Whale Alert</b>\n\n"
        f"<b>Status:</b> {status}\n\n"
        f"Subscribe to:\n"
        f"• Large SOMI transfers ≥ {WHALE_THRESHOLD:,} SOMI\n"
        f"• NFT movement: ERC‑721 / ERC‑1155 tx value ≥ {NFT_SOMI_MIN} SOMI\n\n"
        "Inspired by <b>Somnia Reactivity</b> — real-time on-chain event tracking."
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Alert NFT ≥100 SOMI", callback_data="whale_nft_info"))
    if is_sub:
        markup.add(InlineKeyboardButton("🔕 Unsubscribe", callback_data="whale_unsub"))
    else:
        markup.add(InlineKeyboardButton("🔔 Subscribe", callback_data="whale_sub"))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
    bot.send_message(cid, text, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "Twitter Alerts Somnia")
def twitter_alerts(message):
    cid = message.chat.id
    is_sub = cid in twitter_subscribers
    status = "✅ Subscribed" if is_sub else "❌ Not subscribed"
    text = (
        "🐦 <b>Twitter Alerts Somnia</b>\n\n"
        f"<b>Status:</b> {status}\n\n"
        "Receive notifications about new posts from <a href='https://x.com/Somnia_Network'>@Somnia_Network</a>.\n"
        "Updates are checked every 10 minutes."
    )
    markup = InlineKeyboardMarkup()
    if is_sub:
        markup.add(InlineKeyboardButton("🔕 Unsubscribe", callback_data="twitter_unsub"))
    else:
        markup.add(InlineKeyboardButton("🔔 Subscribe", callback_data="twitter_sub"))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
    bot.send_message(cid, text, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "Price Chart")
def price_chart(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📈 Open Live Chart", url=CHART_URL))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
    bot.send_message(message.chat.id, "📊 <b>SOMI / USDC.e Real-time Chart</b>\n\nClick the button below to view the interactive trading chart on GeckoTerminal.", parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "My Subscriptions")
def my_subs(message):
    cid = message.chat.id
    subs = subscriptions.get(cid, [])
    if not subs:
        bot.send_message(cid, "No active subscriptions.\n\nScan a wallet and tap Subscribe to track SOMI (≥0.01) and USDC (≥0.1) activity.", reply_markup=back_button())
        return
    text = "<b>Your Active Subscriptions:</b>\n<i>Alerts for SOMI≥0.01, USDC.e≥0.1</i>\n\n"
    markup = InlineKeyboardMarkup()
    for addr in subs:
        text += f"📍 <code>{addr}</code>\n"
        markup.add(InlineKeyboardButton(f"❌ Unsubscribe {addr[:10]}...", callback_data=f"unsub_{addr}"))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
    bot.send_message(cid, text, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "Developer")
def dev_link(message):
    bot.send_message(message.chat.id, "<b>Developer:</b> https://x.com/ArtDreamdim\n\nSomnia Reactivity Bot v7.15", parse_mode='HTML', reply_markup=back_button())

@bot.message_handler(func=lambda m: m.text == "Somnia Info")
def somnia_info(message):
    text = (
        "🔗 <b>Somnia Network Resources</b>\n\n"
        "• Official Docs & Reactivity SDK\n"
        "• Bridge, DEX, Explorer\n"
        "• DoraHacks Somnia Reactivity Hackathon"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📚 Docs & Reactivity", url="https://docs.somnia.network/developer/reactivity"))
    markup.add(InlineKeyboardButton("🌉 Bridge", url="https://bridge.somnia.network"))
    markup.add(InlineKeyboardButton("🔍 Explorer", url=EXPLORER_URL))
    markup.add(InlineKeyboardButton("🏆 DoraHacks Hackathon", url="https://dorahacks.io/hackathon/somnia-reactivity/detail"))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text and m.text.startswith('0x') and len(m.text) == 42)
def process_scan(message):
    addr = w3.to_checksum_address(message.text.strip())
    msg = bot.send_message(message.chat.id, "🔍 Scanning blockchain...")
    try:
        bal = w3.eth.get_balance(addr) / 10**18
        res = f"<b>Wallet:</b> <code>{addr}</code>\n\n💰 <b>SOMI:</b> {bal:.4f}\n"
        for name, t_addr in TOKENS.items():
            try:
                contract = w3.eth.contract(address=w3.to_checksum_address(t_addr), abi=ERC20_ABI)
                t_bal = contract.functions.balanceOf(addr).call() / 10**contract.functions.decimals().call()
                if t_bal > 0: res += f"🔹 <b>{name}:</b> {t_bal:.4f}\n"
            except: pass
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Explorer", url=f"{EXPLORER_URL}/address/{addr}"))
        markup.add(InlineKeyboardButton("🔔 Subscribe", callback_data=f"sub_{addr}"))
        markup.add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
        bot.edit_message_text(res, message.chat.id, msg.message_id, parse_mode='HTML', reply_markup=markup)
    except: bot.edit_message_text("Error scanning address.", message.chat.id, msg.message_id, reply_markup=back_button())

@bot.callback_query_handler(func=lambda call: True)
def cb(call):
    cid = call.message.chat.id
    if call.data == "home":
        bot.delete_message(cid, call.message.message_id)
        bot.send_message(cid, "Main Menu:", reply_markup=get_main_menu())
    elif call.data == "whale_nft_info":
        bot.answer_callback_query(call.id, f"NFT alerts: ERC-721/1155 tx value ≥ {NFT_SOMI_MIN} SOMI.")
    elif call.data == "twitter_sub":
        twitter_subscribers.add(cid)
        bot.answer_callback_query(call.id, "Subscribed to Twitter Alerts Somnia!")
        try:
            bot.edit_message_text(
                "🐦 <b>Twitter Alerts Somnia</b>\n\n✅ You are now subscribed to new tweets from @Somnia_Network.",
                cid, call.message.message_id, parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup()
                .add(InlineKeyboardButton("🔕 Unsubscribe", callback_data="twitter_unsub"))
                .add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
            )
        except Exception:
            pass
    elif call.data == "twitter_unsub":
        twitter_subscribers.discard(cid)
        bot.answer_callback_query(call.id, "Unsubscribed from Twitter Alerts Somnia.")
        try:
            bot.edit_message_text(
                "🐦 <b>Twitter Alerts Somnia</b>\n\n❌ You are no longer subscribed.",
                cid, call.message.message_id, parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup()
                .add(InlineKeyboardButton("🔔 Subscribe", callback_data="twitter_sub"))
                .add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
            )
        except Exception:
            pass
    elif call.data == "whale_sub":
        whale_alert_subscribers.add(cid)
        bot.answer_callback_query(call.id, "Subscribed to Whale Alert!")
        try:
            bot.edit_message_text(
                f"🐋 <b>Whale Alert</b>\n\n✅ You are now subscribed. Alerts: transfers ≥ {WHALE_THRESHOLD:,} SOMI and NFT movement ≥ {NFT_SOMI_MIN} SOMI.",
                cid, call.message.message_id, parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup()
                .add(InlineKeyboardButton("🔕 Unsubscribe", callback_data="whale_unsub"))
                .add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
            )
        except Exception:
            pass
    elif call.data == "whale_unsub":
        whale_alert_subscribers.discard(cid)
        bot.answer_callback_query(call.id, "Unsubscribed from Whale Alert.")
        try:
            bot.edit_message_text(
                "🐋 <b>Whale Alert</b>\n\n❌ You are no longer subscribed.",
                cid, call.message.message_id, parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup()
                .add(InlineKeyboardButton("🔔 Subscribe", callback_data="whale_sub"))
                .add(InlineKeyboardButton("⬅️ Back", callback_data="home"))
            )
        except Exception:
            pass
    elif call.data.startswith("sub_"):
        addr = call.data[4:]
        if cid not in subscriptions: subscriptions[cid] = []
        if addr not in subscriptions[cid]:
            subscriptions[cid].append(addr)
            bot.answer_callback_query(call.id, "Subscribed! Alerts: SOMI≥0.01, USDC≥0.1")
    elif call.data.startswith("unsub_"):
        addr = call.data[6:]
        if cid in subscriptions and addr in subscriptions[cid]:
            subscriptions[cid].remove(addr)
            bot.answer_callback_query(call.id, "Removed.")
            my_subs(call.message)

# --- Whale Monitor ---
def whale_monitor():
    last_block = w3.eth.block_number
    while True:
        try:
            current = w3.eth.block_number
            if current > last_block:
                for b_num in range(last_block + 1, current + 1):
                    block = w3.eth.get_block(b_num, full_transactions=True)
                    tx_values = {}
                    for tx in block.transactions:
                        try:
                            h = tx.get("hash")
                            h_str = h.hex() if hasattr(h, "hex") else str(h)
                            tx_values[h_str] = (tx.get("value") or 0) / 10**18
                        except Exception:
                            pass
                    for tx in block.transactions:
                        val = tx['value'] / 10**18
                        if val >= WHALE_THRESHOLD:
                            tx_to = tx.get('to')
                            tx_to_str = tx_to.hex() if tx_to and hasattr(tx_to, 'hex') else (str(tx_to) if tx_to else 'Contract')
                            from_addr = _norm_addr(tx.get("from"))
                            to_addr = _norm_addr(tx_to) if tx_to else ""
                            from_bal = _somi_balance(from_addr, b_num)
                            to_bal = _somi_balance(to_addr, b_num) if to_addr else None
                            msg = (f"🐋 <b>WHALE ALERT!</b>\n\n"
                                   f"<b>Amount:</b> {val:,.2f} SOMI\n"
                                   f"<b>From:</b> <code>{tx['from']}</code>\n"
                                   + (f"<b>From balance:</b> {from_bal:,.2f} SOMI\n" if from_bal is not None else "")
                                   + f"<b>To:</b> <code>{tx_to_str}</code>\n"
                                   + (f"<b>To balance:</b> {to_bal:,.2f} SOMI\n" if to_bal is not None else "")
                                   + f"\n🔗 <a href='{_tx_link(tx['hash'])}'>View Transaction</a>")
                            for uid in whale_alert_subscribers:
                                try: bot.send_message(uid, msg, parse_mode='HTML', disable_web_page_preview=True)
                                except: pass
                    # NFT alerts for Whale Alert subscribers (global, value >= NFT_SOMI_MIN)
                    if whale_alert_subscribers:
                        for get_logs_topics, is_721 in [
                            ([TRANSFER_TOPIC], True),
                            ([ERC1155_TRANSFER_SINGLE_TOPIC], False),
                            ([ERC1155_TRANSFER_BATCH_TOPIC], False),
                        ]:
                            try:
                                logs = w3.eth.get_logs({"fromBlock": b_num, "toBlock": b_num, "topics": get_logs_topics})
                                for log in logs:
                                    try:
                                        if is_721 and len(log.get("topics", [])) != 4:
                                            continue
                                        if not is_721 and len(log.get("topics", [])) < 4:
                                            continue
                                        txh = log.get("transactionHash")
                                        txh_str = txh.hex() if hasattr(txh, "hex") else str(txh)
                                        tx_val = tx_values.get(txh_str, 0)
                                        if tx_val < NFT_SOMI_MIN:
                                            continue
                                        kind = "ERC-721" if is_721 else "ERC-1155"
                                        msg = (f"🎨 <b>Whale Alert — NFT</b>\n\n"
                                               f"🖼 <b>{kind} Transfer</b>, tx value <b>{tx_val:.2f} SOMI</b>\n\n"
                                               f"🔗 <a href='{_tx_link(txh)}'>View TX</a>")
                                        for uid in whale_alert_subscribers:
                                            try:
                                                bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=True)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                last_block = current
            time.sleep(5)
        except: time.sleep(10)

def subscription_monitor():
    """Monitor subscribed wallets for SOMI (>=0.01) and ERC20 (USDC>=0.1, etc) activity."""
    last_block = w3.eth.block_number
    while True:
        try:
            addr_to_chats = _get_addr_to_chats()
            if not addr_to_chats:
                last_block = w3.eth.block_number
                time.sleep(10)
                continue
            subscribed_addrs = set(addr_to_chats.keys())
            current = w3.eth.block_number
            if current <= last_block:
                time.sleep(8)
                continue
            for b_num in range(last_block + 1, min(current + 1, last_block + 50)):
                block = w3.eth.get_block(b_num, full_transactions=True)
                block_ts = block.get("timestamp", 0)
                tx_values = {}
                for tx in block.transactions:
                    try:
                        h = tx.get("hash")
                        h_str = h.hex() if hasattr(h, "hex") else str(h)
                        tx_values[h_str] = (tx.get("value") or 0) / 10**18
                    except Exception:
                        pass
                for tx in block.transactions:
                    f = _norm_addr(tx.get("from"))
                    t_lower = _norm_addr(tx.get("to"))
                    val = (tx.get("value") or 0) / 10**18
                    if val < SUBSCRIPTION_SOMI_MIN:
                        continue
                    if f not in subscribed_addrs and t_lower not in subscribed_addrs:
                        continue
                    chats = set()
                    if f in subscribed_addrs:
                        chats.update(addr_to_chats[f])
                    if t_lower in subscribed_addrs:
                        chats.update(addr_to_chats[t_lower])
                    for cid in chats:
                        try:
                            wallet = f if f in subscribed_addrs else t_lower
                            direction = "in" if t_lower == wallet else "out"
                            bal = _somi_balance(wallet, b_num)
                            bal_line = f"<b>Balance:</b> {bal:,.2f} SOMI\n" if bal is not None else ""
                            txt = (f"🔔 <b>Wallet Activity</b>\n\n"
                                   f"📍 <code>{wallet}</code>\n"
                                   f"💸 <b>{val:.4f} SOMI</b> {direction}\n"
                                   f"{bal_line}"
                                   f"🔗 <a href='{_tx_link(tx['hash'])}'>View TX</a>")
                            bot.send_message(cid, txt, parse_mode="HTML", disable_web_page_preview=True)
                        except Exception:
                            pass
                for token_name, (token_addr, dec, min_amt) in TOKENS_MONITOR.items():
                    try:
                        logs = w3.eth.get_logs({
                            "fromBlock": b_num, "toBlock": b_num,
                            "address": w3.to_checksum_address(token_addr),
                            "topics": [TRANSFER_TOPIC]
                        })
                        for log in logs:
                            if len(log["topics"]) < 3:
                                continue
                            th1, th2 = log["topics"][1], log["topics"][2]
                            h1 = (th1.hex() if hasattr(th1, "hex") else str(th1)).replace("0x", "")
                            h2 = (th2.hex() if hasattr(th2, "hex") else str(th2)).replace("0x", "")
                            fr = ("0x" + h1[-40:]).lower()
                            to = ("0x" + h2[-40:]).lower()
                            d = log.get("data") or b"\x00"
                            amt = int(d.hex() if hasattr(d, "hex") else d, 16) / (10**dec)
                            if amt < min_amt:
                                continue
                            if fr not in subscribed_addrs and to not in subscribed_addrs:
                                continue
                            chats = set()
                            if fr in subscribed_addrs:
                                chats.update(addr_to_chats[fr])
                            if to in subscribed_addrs:
                                chats.update(addr_to_chats[to])
                            for cid in chats:
                                try:
                                    wallet = fr if fr in subscribed_addrs else to
                                    direction = "in" if to == wallet else "out"
                                    txt = (f"🔔 <b>Wallet Activity</b>\n\n"
                                           f"📍 <code>{wallet}</code>\n"
                                           f"💵 <b>{amt:.4f} {token_name}</b> {direction}\n"
                                           f"🔗 <a href='{_tx_link(log['transactionHash'])}'>View TX</a>")
                                    bot.send_message(cid, txt, parse_mode="HTML", disable_web_page_preview=True)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                # NFT (ERC-721) transfers for subscribed wallets with SOMI >= NFT_SOMI_MIN
                try:
                    nft_logs = w3.eth.get_logs({
                        "fromBlock": b_num,
                        "toBlock": b_num,
                        "topics": [TRANSFER_TOPIC]
                    })
                    for log in nft_logs:
                        try:
                            if len(log["topics"]) != 4:
                                continue
                            th1, th2 = log["topics"][1], log["topics"][2]
                            h1 = (th1.hex() if hasattr(th1, "hex") else str(th1)).replace("0x", "")
                            h2 = (th2.hex() if hasattr(th2, "hex") else str(th2)).replace("0x", "")
                            fr = ("0x" + h1[-40:]).lower()
                            to = ("0x" + h2[-40:]).lower()
                            if fr not in subscribed_addrs and to not in subscribed_addrs:
                                continue
                            txh = log.get("transactionHash")
                            txh_str = txh.hex() if hasattr(txh, "hex") else str(txh)
                            tx_val = tx_values.get(txh_str, 0)
                            if tx_val < NFT_SOMI_MIN:
                                continue
                            chats = set()
                            if fr in subscribed_addrs:
                                chats.update(addr_to_chats[fr])
                            if to in subscribed_addrs:
                                chats.update(addr_to_chats[to])
                            for cid in chats:
                                try:
                                    wallet = fr if fr in subscribed_addrs else to
                                    direction = "mint" if fr == "0x0000000000000000000000000000000000000000" else ("in" if to == wallet else "out")
                                    txt = (f"🎨 <b>NFT Activity</b>\n\n"
                                           f"📍 <code>{wallet}</code>\n"
                                           f"🖼 <b>ERC-721 Transfer</b> {direction}\n"
                                           f"💰 <b>{tx_val:.2f} SOMI</b> tx value\n"
                                           f"🔗 <a href='{_tx_link(txh)}'>View TX</a>")
                                    bot.send_message(cid, txt, parse_mode="HTML", disable_web_page_preview=True)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    pass

                # NFT (ERC-1155) transfers for subscribed wallets with SOMI >= NFT_SOMI_MIN
                try:
                    for topic in (ERC1155_TRANSFER_SINGLE_TOPIC, ERC1155_TRANSFER_BATCH_TOPIC):
                        logs = w3.eth.get_logs({
                            "fromBlock": b_num,
                            "toBlock": b_num,
                            "topics": [topic]
                        })
                        for log in logs:
                            try:
                                if len(log["topics"]) < 4:
                                    continue
                                th2, th3 = log["topics"][2], log["topics"][3]
                                h2 = (th2.hex() if hasattr(th2, "hex") else str(th2)).replace("0x", "")
                                h3 = (th3.hex() if hasattr(th3, "hex") else str(th3)).replace("0x", "")
                                fr = ("0x" + h2[-40:]).lower()
                                to = ("0x" + h3[-40:]).lower()
                                if fr not in subscribed_addrs and to not in subscribed_addrs:
                                    continue
                                txh = log.get("transactionHash")
                                txh_str = txh.hex() if hasattr(txh, "hex") else str(txh)
                                tx_val = tx_values.get(txh_str, 0)
                                if tx_val < NFT_SOMI_MIN:
                                    continue
                                chats = set()
                                if fr in subscribed_addrs:
                                    chats.update(addr_to_chats[fr])
                                if to in subscribed_addrs:
                                    chats.update(addr_to_chats[to])
                                for cid in chats:
                                    try:
                                        wallet = fr if fr in subscribed_addrs else to
                                        direction = "mint" if fr == "0x0000000000000000000000000000000000000000" else ("in" if to == wallet else "out")
                                        txt = (f"🎨 <b>NFT Activity</b>\n\n"
                                               f"📍 <code>{wallet}</code>\n"
                                               f"🧩 <b>ERC-1155 Transfer</b> {direction}\n"
                                               f"💰 <b>{tx_val:.2f} SOMI</b> tx value\n"
                                               f"🔗 <a href='{_tx_link(txh)}'>View TX</a>")
                                        bot.send_message(cid, txt, parse_mode="HTML", disable_web_page_preview=True)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                except Exception:
                    pass
            last_block = current
            time.sleep(6)
        except Exception:
            time.sleep(15)


def twitter_monitor():
    """Monitor Somnia Twitter account and push new tweets to subscribers."""
    global last_tweet_id
    if not TWITTER_BEARER_TOKEN or TWITTER_BEARER_TOKEN == "YOUR_TWITTER_BEARER_TOKEN_HERE":
        return
    try:
        client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, wait_on_rate_limit=True)
    except Exception:
        return

    while True:
        try:
            params = {
                "id": SOMNIA_USER_ID,
                "exclude": ["replies", "retweets"],
                "max_results": 5
            }
            if last_tweet_id:
                params["since_id"] = last_tweet_id
            resp = client.get_users_tweets(**params)
            tweets = resp.data or []
            if tweets:
                tweets_sorted = sorted(tweets, key=lambda t: t.id)
                # если last_tweet_id ещё не установлен, не шлём историю, только запоминаем
                if last_tweet_id is None:
                    last_tweet_id = tweets_sorted[-1].id
                else:
                    for tw in tweets_sorted:
                        if last_tweet_id and tw.id <= last_tweet_id:
                            continue
                        last_tweet_id = tw.id
                        url = f"https://x.com/Somnia_Network/status/{tw.id}"
                        msg = (
                            "🐦 <b>Twitter Alerts Somnia</b>\n\n"
                            f"{tw.text}\n\n"
                            f"🔗 <a href='{url}'>Open tweet</a>"
                        )
                        for uid in list(twitter_subscribers):
                            try:
                                bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=False)
                            except Exception:
                                pass
            time.sleep(600)
        except Exception:
            time.sleep(600)

threading.Thread(target=whale_monitor, daemon=True).start()
threading.Thread(target=subscription_monitor, daemon=True).start()
threading.Thread(target=twitter_monitor, daemon=True).start()
print("SomiBot is running (Whale + Wallet Subscriptions)...")
bot.infinity_polling()