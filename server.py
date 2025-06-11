from flask import Flask, request
import requests
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

# Кэш для цен токенов, чтобы не делать лишние запросы
TOKEN_PRICE_CACHE = {}

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
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
    try:
        response = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd")
        data = response.json()
        usd = data.get(symbol, {}).get("usd", 0)
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
            msg = f"📥 Новая транзакция: {tx_type}\n🔗 Signature: {signature}"

            # Универсальный парсинг токенов (включая SWAP, MINT, TRANSFER и др.)
            if tx.get("tokenTransfers"):
                msg += "\n📦 Перемещения токенов:"
                for t in tx["tokenTransfers"]:
                    mint = t.get("mint", "")
                    raw_amount = t.get("tokenAmount", 0)
                    sender = shorten(t.get("fromUserAccount", ""))
                    receiver = shorten(t.get("toUserAccount", ""))
                    name, symbol, decimals = get_token_info(mint)
                    amount = int(raw_amount) / (10 ** decimals) if decimals else raw_amount
                    price_per_token = get_token_usd_price(symbol)
                    usd = amount * price_per_token if price_per_token else None

                    msg += (
                        f"\n🔸 {name} ({symbol})"
                        f"\n📤 От: {sender}"
                        f"\n📥 Кому: {receiver}"
                        f"\n🔢 Кол-во: {amount:.6f}" +
                        (f" (~${usd:.2f})" if usd else "")
                        + f"\n🔗 https://solscan.io/token/{mint}"
                    )

            # NFT продажи
            elif tx_type == "NFT_SALE" and tx.get("events", {}).get("nft"):
                nft_event = tx["events"]["nft"]
                nft_name = nft_event.get("description", "NFT без названия")
                sol = nft_event.get("amount", 0) / 1e9
                usd_price = get_token_usd_price("solana")
                usd = sol * usd_price
                buyer = shorten(nft_event.get("buyer", ""))
                seller = shorten(nft_event.get("seller", ""))
                source = nft_event.get("source", "не указано")

                msg += (
                    f"\n🎨 NFT: {nft_name}"
                    f"\n💰 Сумма: {sol:.2f} SOL (~${usd:.2f})"
                    f"\n🛍 Площадка: {source}"
                    f"\n📤 Продавец: {seller}"
                    f"\n📥 Покупатель: {buyer}"
                )

            send_telegram_message(msg)

        return '', 200

    except Exception as e:
        print("❌ Ошибка обработки запроса:", str(e))
        return 'Internal Server Error', 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)