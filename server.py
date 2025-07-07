import os
import json
import requests
from flask import Flask, request
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

bot = Bot(token=TELEGRAM_BOT_TOKEN)


def fetch_token_metadata(mint: str):
    try:
        url = f"https://api.helius.xyz/v0/tokens/metadata?mints[]={mint}&api-key={HELIUS_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()
        metadata = response.json()
        if metadata and isinstance(metadata, list) and metadata[0]:
            return metadata[0]
    except Exception as e:
        print(f"\n❌ Ошибка при получении метаданных токена {mint}: {e}\n")
    return {"name": "Unknown", "symbol": "", "priceUSD": None}


def short(address):
    return address[:4] + "..." + address[-4:] if address else "—"


def format_amount(amount, decimals):
    return float(amount) / (10 ** decimals)


def is_platform_fee_account(account):
    platform_accounts = [
        "ComputeBudget111111111111111111111111111111",
        "11111111111111111111111111111111",
        "SysvarRent111111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    ]
    return account in platform_accounts


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("\n✅ Получены данные:", json.dumps(data, indent=2))

    for tx in data:
        signature = tx.get("signature")
        transfers = tx.get("tokenTransfers", [])
        if not transfers:
            continue

        message = f"\ud83d\udce5 Новая транзакция:\n\ud83d\udd17 Signature: <code>{signature}</code>\n"
        for transfer in transfers:
            mint = transfer.get("mint")
            sender = transfer.get("fromUserAccount")
            recipient = transfer.get("toUserAccount")
            amount = transfer.get("tokenAmount")
            token_standard = transfer.get("tokenStandard")

            if is_platform_fee_account(sender) or is_platform_fee_account(recipient):
                continue

            meta = fetch_token_metadata(mint)
            name = meta.get("name") or short(mint)
            symbol = meta.get("symbol") or ""
            price_usd = meta.get("priceUSD")

            direction = "\ud83d\udce4" if amount < 0 else "\ud83d\udce5"
            color = "<b><font color=\"#ff0000\">" if amount < 0 else "<b><font color=\"#00cc66\">"

            value = abs(amount)
            usd_value = f"\n💵 ≈ ${round(value * price_usd, 2)}" if price_usd else ""

            message += (
                f"\n🔸 {name} ({symbol})"
                f"\n{direction} От: {short(sender)}"
                f"\n{direction} Кому: {short(recipient)}"
                f"\n🔢 Кол-во: {color}{value}</font></b>{usd_value}"
                f"\n🔗 <a href='https://solscan.io/token/{mint}'>{mint}</a>\n"
            )

        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
            )
        except Exception as e:
            print(f"❌ Ошибка при отправке сообщения в Telegram: {e}")

    return "ok"


@app.route("/")
def index():
    return "✅ Webhook для Helius работает."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)