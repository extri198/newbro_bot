
from flask import Flask, request
import requests
import os
from dotenv import load_dotenv
import json
import logging

load_dotenv()
app = Flask(__name__)

# Включаем debug-режим и подробное логгирование
app.debug = True
logging.basicConfig(level=logging.DEBUG)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

FEE_WALLETS = {
    "E2HzWjvbrYyfU9uBAGz1FUGXo7xYzvJrJtP8FFmrSzAa",  # Magic Eden
    "9hQBGnKqxYfaP3dtkEyYVLVwzYEEVK2vWa9V6rK4ZciE"
}

COINGECKO_IDS = {
    "sol": "solana",
    "bonk": "bonk",
    "usdc": "usd-coin",
    "usdt": "tether",
    "eth": "ethereum"
}

TOKEN_PRICE_CACHE = {}

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    response = requests.post(url, data=payload)
    if not response.ok:
        logging.error("❌ Telegram error: %s", response.text)

def shorten(addr):
    return addr[:4] + "..." + addr[-4:] if addr else "—"

def get_token_info(mint):
    try:
        url = f"https://api.helius.xyz/v0/tokens/metadata?api-key={HELIUS_API_KEY}&mintAccounts[]={mint}"
        response = requests.get(url)
        data = response.json()
        if isinstance(data, list) and data:
            token = data[0]
            name = token.get("name") or shorten(mint)
            symbol = token.get("symbol") or "-"
            decimals = token.get("decimals", 0)
            return name, symbol, decimals
    except Exception as e:
        logging.exception(f"❌ Ошибка получения токена {mint}")
    return shorten(mint), "-", 0

def get_token_usd_price(symbol):
    symbol = symbol.lower()
    if symbol in TOKEN_PRICE_CACHE:
        logging.debug(f"[CACHE] {symbol.upper()} → ${TOKEN_PRICE_CACHE[symbol]}")
        return TOKEN_PRICE_CACHE[symbol]

    coingecko_id = COINGECKO_IDS.get(symbol)
    if not coingecko_id:
        logging.warning(f"❌ Нет CoinGecko ID для символа {symbol}")
        return 0

    try:
        url = f"https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": coingecko_id, "vs_currencies": "usd"}
        headers = {"accept": "application/json"}

        response = requests.get(url, params=params, headers=headers)
        if response.status_code != 200:
            logging.error(f"❌ CoinGecko статус {response.status_code}: {response.text}")
            return 0

        data = response.json()
        usd = data.get(coingecko_id, {}).get("usd")
        logging.debug(f"✅ Цена {symbol.upper()} = ${usd}")

        if usd is not None:
            TOKEN_PRICE_CACHE[symbol] = usd
            return usd
        else:
            logging.warning(f"⚠️ Нет цены USD в ответе: {data}")
            return 0

    except Exception as e:
        logging.exception(f"❌ Ошибка при запросе CoinGecko для {symbol.upper()}")
        return 0


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        logging.debug("📩 Получен webhook-запрос")
        auth_header = request.headers.get('Authorization')
        if auth_header != f'Bearer {WEBHOOK_SECRET}':
            logging.warning("❌ Неверный токен: %s", auth_header)
            return 'Forbidden', 403

        data = request.get_json(force=True)
        logging.debug(f"📦 Полученные данные: {json.dumps(data)[:500]}")

    auth_header = request.headers.get('Authorization')
    if auth_header != f'Bearer {WEBHOOK_SECRET}':
        logging.warning("❌ Неверный токен: %s", auth_header)
        return 'Forbidden', 403

    try:
        data = request.get_json(force=True)
        txs = data if isinstance(data, list) else data.get("transactions", [])

        for tx in txs:
            tx_type = tx.get("type", "неизвестно")
            signature = tx.get("signature", "нет")
            msg = f"📥 <b>Новая транзакция: {tx_type}</b>\n🔗 <a href='https://solscan.io/tx/{signature}'>{signature}</a>"

            transfers = tx.get("tokenTransfers", [])
            for tr in transfers:
                amount_raw = tr.get("tokenAmount", 0)
                mint = tr.get("mint")
                from_addr = tr.get("fromUserAccount")
                to_addr = tr.get("toUserAccount")

                name, symbol, decimals = get_token_info(mint)
                amount = amount_raw / (10 ** decimals) if decimals else amount_raw

                sol_usd_price = get_token_usd_price("sol")

                if symbol.lower() == "sol":
                    amount_usd = amount * sol_usd_price
                    msg += f"\n\n💸 <b>{amount:.4f} SOL</b> (~${amount_usd:.2f})"
                    msg += f"\n🔄 От: <code>{shorten(from_addr)}</code> → <code>{shorten(to_addr)}</code>"
                    msg += f"\n💰 Цена за 1 SOL: ${sol_usd_price:.4f}"
                else:
                    token_in_sol = amount  # по умолчанию считаем 1 токен = 1 SOL
                    amount_usd = token_in_sol * sol_usd_price
                    msg += f"\n\n🪙 <b>{amount:.4f} {symbol}</b> ≈ {token_in_sol:.4f} SOL (~${amount_usd:.2f})"
                    msg += f"\n🔄 От: <code>{shorten(from_addr)}</code> → <code>{shorten(to_addr)}</code>"

            send_telegram_message(msg)
        return '', 200

    except Exception as e:
        logging.exception("❌ Ошибка обработки webhook")
        return 'Internal Server Error', 500
