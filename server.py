import os
import json
import requests
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def get_token_metadata(mint_address):
    if mint_address == "So11111111111111111111111111111111111111112":
        return {
            "name": "Wrapped SOL",
            "symbol": "SOL",
            "image": "https://cryptologos.cc/logos/solana-sol-logo.png"
        }

    url = "https://api.helius.xyz/v0/tokens/metadata"
    headers = {"accept": "application/json"}
    params = {
        "mints[]": [mint_address],
        "api-key": HELIUS_API_KEY
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and data[0]:
            return data[0]
        else:
            print(f"⚠️ Не удалось найти метаданные для токена {mint_address}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при получении метаданных токена {mint_address}: {e}")
        return None


def format_token_transfer(transfer):
    mint = transfer.get("mint")
    amount = transfer.get("tokenAmount")
    from_acc = transfer.get("fromUserAccount")
    to_acc = transfer.get("toUserAccount")

    metadata = get_token_metadata(mint)
    name = metadata.get("name") if metadata else "Unknown"
    symbol = metadata.get("symbol") if metadata else ""

    return (
        f"\n🔸 <b>{name}</b> (<code>{symbol}</code>)"
        f"\n📤 От: <code>{from_acc[:4]}...{from_acc[-4:]}</code>"
        f"\n📥 Кому: <code>{to_acc[:4]}...{to_acc[-4:]}</code>"
        f"\n🔢 Кол-во: <code>{amount}</code>"
        f"\n🔗 <a href='https://solscan.io/token/{mint}'>Просмотр в Solscan</a>"
    )


def send_telegram_message(message):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(TELEGRAM_URL, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Ошибка при отправке сообщения в Telegram: {e}")


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("✅ Получены данные:", json.dumps(data, indent=2))

    for tx in data:
        signature = tx.get("signature")
        tx_type = tx.get("type")
        token_transfers = tx.get("tokenTransfers", [])

        message = f"📥 Новая транзакция: <b>{tx_type}</b>\n"
        message += f"🔗 Signature: <code>{signature}</code>"

        if token_transfers:
            message += "\n📦 Перемещения токенов:"
            for transfer in token_transfers:
                message += format_token_transfer(transfer)

        send_telegram_message(message)

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)