from flask import Flask, request
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    response = requests.post(url, data=payload)
    if not response.ok:
        print("❌ Ошибка Telegram:", response.text)

@app.route('/webhook', methods=['POST'])
def webhook():
    auth_header = request.headers.get('Authorization')
    if auth_header != f'Bearer {WEBHOOK_SECRET}':
        print("❌ Неверный заголовок Authorization:", auth_header)
        return 'Forbidden', 403

    try:
        data = request.get_json(force=True)
        print("✅ Получены данные от Helius:", data)

        txs = data if isinstance(data, list) else data.get("transactions", [])
        for tx in txs:
            signature = tx.get("signature", "нет сигнатуры")
            tx_type = tx.get("type", "неизвестный тип")
            description = tx.get("description", "-")
            source = tx.get("source", "-")

            msg = (
                f"📥 Новая транзакция:\n"
                f"→ Тип: {tx_type}\n"
                f"→ Signature: {signature}\n"
                f"→ Source: {source}\n"
                f"→ Описание: {description}"
            )
            send_telegram_message(msg)

        return '', 200

    except Exception as e:
        print("❌ Ошибка обработки запроса:", str(e))
        return 'Internal Server Error', 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)