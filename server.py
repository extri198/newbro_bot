import os
import requests
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

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

def get_token_metadata(mint_address):
    url = f"https://api.helius.xyz/v0/tokens/metadata?mints[]={mint_address}&api-key={HELIUS_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and len(data) > 0 and data[0] is not None:
            return {
                "symbol": data[0].get("symbol", ""),
                "name": data[0].get("name", ""),
                "decimals": data[0].get("decimals", 0)
            }
    except Exception as e:
        print(f"Ошибка при получении метаданных токена: {e}")
    return {
        "symbol": "",
        "name": "",
        "decimals": 0
    }

@app.route("/webhook", methods=["POST"])
def webhook():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {WEBHOOK_SECRET}":
        return "Forbidden", 403

    data = request.json
    if not data:
        return "No data", 400

    txs = data.get("transactions", [])
    for tx in txs:
        signature = tx.get("signature", "")
        tx_type = tx.get("type", "UNKNOWN")

        message = f"📥 <b>Новая транзакция: {tx_type}</b>\n🔗 <a href='https://solscan.io/tx/{signature}'>{signature}</a>"

        token_transfers = tx.get("tokenTransfers", [])
        if token_transfers:
            message += "\n📦 <b>Перемещения токенов:</b>"
            for transfer in token_transfers:
                mint = transfer.get("mint", "")
                metadata = get_token_metadata(mint)
                symbol = metadata["symbol"]
                name = metadata["name"]
                decimals = metadata["decimals"]

                amount = transfer.get("tokenAmount", 0)
                if decimals:
                    amount /= (10 ** decimals)

                from_user = transfer.get("fromUserAccount", "—")
                to_user = transfer.get("toUserAccount", "—")

                message += (
                    f"\n🔸 <code>{mint[:4]}...{mint[-4:]}</code> "
                    f"(<b>{symbol or name or 'Unknown'}</b>)"
                    f"\n📤 От: <code>{from_user[:4]}...{from_user[-4:]}</code>"
                    f"\n📥 Кому: <code>{to_user[:4]}...{to_user[-4:]}</code>"
                    f"\n🔢 Кол-во: <b>{amount:.6f}</b>"
                    f"\n🔗 <a href='https://solscan.io/token/{mint}'>solscan</a>\n"
                )

        send_telegram_message(message)

    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)