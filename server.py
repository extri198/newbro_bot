from flask import Flask, request
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = 'ваш_токен_бота'
CHAT_ID = 'ваш_chat_id'
WEBHOOK_SECRET = 'supersecret123'  # тот же токен, что вы укажете в Helius, если сможете

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    requests.post(url, data=payload)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Получены данные от Helius:", data)

    if not isinstance(data, list):
        return '', 200  # защита от неожиданного формата

    for tx in data:
        signature = tx.get("signature", "<нет подписи>")
        tx_type = tx.get("type", "Неизвестный тип")
        msg = f"📥 Новая транзакция:
→ Signature: {signature}
→ Тип: {tx_type}"
        send_telegram_message(msg)
    return '', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)