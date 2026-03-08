import telebot
import requests
from web3 import Web3
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# === НАСТРОЙКИ ===
TOKEN = '------'
BOT_NAME = "Scan Somnia Wallet"

# Список RPC (с fallback на случай проблем с одним из них)
RPC_LIST = [
    'https://api.infra.mainnet.somnia.network',
    'https://somnia-json-rpc.stakely.io',
    'https://somnia-rpc.publicnode.com',
    'https://dream-rpc.somnia.network'
]

# ERC-20 токены
TOKENS = {
    'USDC.e (Bridged USDC)': '0x28BEc7E30E6faee657a03e19Bf1128AaD7632A00',
    'ArWSOMI (Arenas Somnia)': '0xFe171d9d2679c4544ADD1a20d565C251cEd9FF4A',
    'WSOMI (Wrapped SOMI)': '0x046EDe9564A72571df6F5e44d0405360c0f4dCab'
}

# Минимальный ABI для ERC-20
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

bot = telebot.TeleBot(TOKEN)

# Подключение к Web3 с автоматическим fallback
def get_web3():
    for rpc in RPC_LIST:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 15}))
            block = w3.eth.block_number  # тест соединения
            print(f"Успешно подключено к RPC: {rpc} (блок #{block})")
            return w3, rpc
        except Exception as e:
            print(f"Не удалось подключиться к {rpc}: {e}")
    raise Exception("Все RPC недоступны. Проверьте интернет или статус сети Somnia.")

w3, used_rpc = get_web3()

# Получение цены SOMI с CoinGecko
def get_somi_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=somnia&vs_currencies=usd"
        response = requests.get(url, timeout=10)
        data = response.json()
        return data['somnia']['usd']
    except:
        return None

# Команда /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    price = get_somi_price()
    price_text = f"<b>${price:.6f}</b>" if price else "<i>unable to load</i>"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔍 Scan Wallet", callback_data="scan_prompt"))

    bot.send_message(
        message.chat.id,
        f"🌙 <b>Welcome to {BOT_NAME}!</b>\n\n"
        f"Current <b>SOMI</b> price: {price_text} USD 💰\n\n"
        f"Send your Somnia wallet address (0x...) to instantly check all balances.\n"
        f"Or use the button below to start.",
        parse_mode='HTML',
        reply_markup=markup
    )

# Обработка ввода адреса кошелька
@bot.message_handler(func=lambda m: m.text and m.text.startswith('0x') and len(m.text) == 42)
def handle_wallet(message):
    scan_wallet(message.chat.id, message.text.strip())

# Обработка inline-кнопок
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "scan_prompt":
        bot.send_message(call.message.chat.id, "🔍 Please send your Somnia wallet address (0x...):")

    elif call.data.startswith("rescan_"):
        address = call.data.split("_")[1]
        scan_wallet(call.message.chat.id, address)

    elif call.data == "price_update":
        price = get_somi_price()
        if price:
            bot.answer_callback_query(call.id, f"SOMI price: ${price:.6f} USD", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "Failed to update price", show_alert=True)

    elif call.data == "info":
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("📚 Official Docs", url="https://docs.somnia.network"))
        markup.add(InlineKeyboardButton("🌐 Website", url="https://somnia.network"))
        markup.add(InlineKeyboardButton("🔗 Add to Wallet (Chainlist)", url="https://chainlist.org/?search=somnia"))
        bot.send_message(call.message.chat.id, "ℹ️ <b>Somnia Network Information</b>", parse_mode='HTML', reply_markup=markup)

    elif call.data == "developer":
        bot.send_message(
            call.message.chat.id,
            "👨‍💻 <b>Developer:</b> 𝓓𝓓𝓢𝓐𝓵 𝓐𝓻𝓽\n"
            "🐦 Twitter: https://x.com/ArtDreamdim",
            parse_mode='HTML',
            disable_web_page_preview=True
        )

# Основная функция сканирования
def scan_wallet(chat_id, address):
    if not w3.is_address(address):
        bot.send_message(chat_id, "❌ Invalid wallet address format. Please check and try again.")
        return

    address = w3.to_checksum_address(address)

    results = f"🔍 <b>Wallet Scan Results</b>\n\n<code>{address}</code>\n\n"
    results += f"🌐 Connected via: <code>{used_rpc}</code>\n\n"

    # 🔥 НАТИВНЫЙ SOMI — ВСЕГДА ПЕРВЫМ И ВЫДЕЛЕННЫМ 🔥
    try:
        native_balance_wei = w3.eth.get_balance(address)
        native_balance = native_balance_wei / (10 ** 18)
        results += f"🔥 <b>SOMI (Native Gas Token):</b> <code>{native_balance:.6f}</code> 🔥\n\n"
    except Exception:
        results += f"🔥 <b>SOMI (Native Gas Token):</b> <i>error fetching balance</i>\n\n"

    # ERC-20 токены
    for name, contract_addr in TOKENS.items():
        try:
            contract = w3.eth.contract(address=contract_addr, abi=ERC20_ABI)
            balance_raw = contract.functions.balanceOf(address).call()
            decimals = contract.functions.decimals().call()
            balance = balance_raw / (10 ** decimals)
            results += f"✅ <b>{name}:</b> <code>{balance:.6f}</code>\n"
        except Exception:
            results += f"❌ <b>{name}:</b> <i>error</i>\n"

    # Кнопки под результатом
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("ℹ️ Somnia Info", callback_data="info"),
        InlineKeyboardButton("👨‍💻 Developer", callback_data="developer")
    )
    markup.add(
        InlineKeyboardButton("💰 Update Price", callback_data="price_update"),
        InlineKeyboardButton("🔄 Rescan Wallet", callback_data=f"rescan_{address}")
    )

    bot.send_message(chat_id, results, parse_mode='HTML', reply_markup=markup)

# Убираем стандартное меню с командами внизу чата
bot.delete_my_commands()

# Запуск бота
print("Scan Somnia Wallet Bot успешно запущен!")
print("Нативный SOMI отображается первым с 🔥")
bot.infinity_polling()
