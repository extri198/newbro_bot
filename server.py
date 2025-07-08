from flask import Flask, request
import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

# Известные fee-collector адреса (можно расширять)
FEE_WALLETS = {
    "E2HzWjvbrYyfU9uBAGz1FUGXo7xYzvJrJtP8FFmrSzAa",  # Magic Eden
    "9hQBGnKqxYfaP3dtkEyYVLVwzYEEVK2vWa9V6rK4ZciE"
}

# CoinGecko ID соответствие
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
        print("❌ Telegram error:", response.text)

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
        print(f"❌ Ошибка получения токена {mint}: {e}")
    return shorten(mint), "-", 0

def get_token_usd_price(symbol):
    symbol = symbol.lower()
    if symbol in TOKEN_PRICE_CACHE:
        return TOKEN_PRICE_CACHE[symbol]
    coingecko_id = COINGECKO_IDS.get(symbol)
    if not coingecko_id:
        return 0
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd"
        response = requests.get(url)
        data = response.json()
        usd = data.get(coingecko_id, {}).get("usd", 0)
        if usd:
            TOKEN_PRICE_CACHE[symbol] = usd
        return usd
    except Exception as e:
        print(f"❌ Ошибка получения курса {symbol.upper()}: {e}")
        return 0

@app.route('/webhook', methods=['POST'])
def webhook():
    auth_header = request.headers.get('Authorization')
    if auth_header != f'Bearer {WEBHOOK_SECRET}':
        print("❌ Неверный токен:", auth_header)
        return 'Forbidden', 403

    try:
        data = request.get_json(force=True)
        txs = data if isinstance(data, list) else data.get("transactions", [])

        for tx in txs:
            tx_type = tx.get("type", "неизвестно")
            signature = tx.get("signature", "нет")
            msg = f"📥 <b>Новая транзакция: {tx_type}</b>\n🔗 <a href='https://solscan.io/tx/{signature}'>{signature}</a>"

            transfers = tx.get("tokenTransfers", [])
            if transfers:
                msg += "\n\n📦 <b>Перемещения токенов:</b>"
                for t in transfers:
                    mint = t.get("mint", "")
                    from_addr = t.get("fromUserAccount", "")
                    to_addr = t.get("toUserAccount", "")
                    if from_addr in FEE_WALLETS or to_addr in FEE_WALLETS:
                        continue  # пропускаем комиссии

                    raw_amount = t.get("tokenAmount", 0)
                    name, symbol, decimals = get_token_info(mint)
                    amount = int(raw_amount) / (10 ** decimals) if decimals else float(raw_amount)

                    price_per_token = get_token_usd_price(symbol)
                    usd = amount * price_per_token if price_per_token else 0

                    emoji = "🟢" if to_addr and not from_addr else "🔴"
                    amount_line = f"{emoji} <b>{amount:.6f}</b>{f' (~${usd:.2f})' if usd else ''}"

                    msg += (
                        f"\n🔸 <b>{name}</b> ({symbol})"
                        f"\n📤 От: {shorten(from_addr)}"
                        f"\n📥 Кому: {shorten(to_addr)}"
                        f"\n💰 Сумма: {amount_line}"
                        f"\n🔗 <a href='https://solscan.io/token/{mint}'>{mint}</a>\n"
                    )

            send_telegram_message(msg)

        return '', 200

    except Exception as e:
        print("❌ Ошибка обработки запроса:", str(e))
        return 'Internal Server Error', 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)