from flask import Flask, request
import requests
import os
from dotenv import load_dotenv
import json
import time
from requests.exceptions import RequestException, Timeout
import logging

load_dotenv()
app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

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
LAST_COINGECKO_REQUEST = 0
COINGECKO_RATE_LIMIT = 1.2  # seconds between requests (50 calls/minute)

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        logger.info(f"Sending Telegram message: {text}")
        response = requests.post(url, data=payload, timeout=10)
        logger.info(f"Telegram response: {response.status_code} {response.text}")
        if not response.ok:
            logger.error(f"Telegram error: {response.text}")
    except (RequestException, Timeout) as e:
        logger.error(f"Telegram request failed: {e}")

def shorten(addr):
    return addr[:4] + "..." + addr[-4:] if addr else "—"

def get_token_info(mint):
    try:
        url = f"https://api.helius.xyz/v0/token-metadata?api-key={HELIUS_API_KEY}"
        payload = {"mintAccounts": [mint]}
        logger.info(f"Requesting Helius token info: {url} {payload}")
        response = requests.post(url, json=payload, timeout=10)
        logger.info(f"Helius response: {response.status_code} {response.text}")

        if response.status_code == 429:
            logger.error(f"Helius API rate limit exceeded for {mint}")
            return shorten(mint), "-", 0
        elif response.status_code != 200:
            logger.error(f"Helius API error {response.status_code} for {mint}: {response.text}")
            return shorten(mint), "-", 0

        data = response.json()
        if isinstance(data, list) and data:
            token = data[0]
            # Symbol and name
            onchain_data = (
                token.get("onChainMetadata", {})
                    .get("metadata", {})
                    .get("data", {})
            )
            legacy_metadata = token.get("legacyMetadata") or {}
            symbol = onchain_data.get("symbol") or (legacy_metadata.get("symbol") if isinstance(legacy_metadata, dict) else None)
            name = onchain_data.get("name") or (legacy_metadata.get("name") if isinstance(legacy_metadata, dict) else None)
            # Decimals
            decimals = None
            if legacy_metadata and isinstance(legacy_metadata, dict):
                decimals = legacy_metadata.get("decimals")
            if decimals is None:
                decimals = (
                    token.get("onChainAccountInfo", {})
                        .get("accountInfo", {})
                        .get("data", {})
                        .get("parsed", {})
                        .get("info", {})
                        .get("decimals")
                )
            if decimals is None:
                decimals = 0
            name = name or shorten(mint)
            symbol = symbol or "-"
            if symbol == "-":
                logger.warning(f"Unknown token symbol for mint {mint}. Helius response: {json.dumps(token)}")
            logger.info(f"Token info for {mint}: name={name}, symbol={symbol}, decimals={decimals}")
            return name, symbol, decimals
        else:
            logger.error(f"No token data returned for {mint}. Full Helius response: {json.dumps(data)}")
            return shorten(mint), "-", 0

    except (RequestException, Timeout) as e:
        logger.error(f"Ошибка получения токена {mint}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error getting token {mint}: {e}")
    return shorten(mint), "-", 0

def get_token_usd_price(symbol, mint=None):
    global LAST_COINGECKO_REQUEST
    
    symbol = symbol.lower()
    if symbol in TOKEN_PRICE_CACHE:
        logger.info(f"Using cached price for {symbol}: {TOKEN_PRICE_CACHE[symbol]}")
        return TOKEN_PRICE_CACHE[symbol]
        
    coingecko_id = COINGECKO_IDS.get(symbol)
    if not coingecko_id:
        logger.warning(f"No CoinGecko ID for symbol: {symbol} (mint: {mint})")
        return 0
        
    # Rate limiting for CoinGecko
    current_time = time.time()
    time_since_last = current_time - LAST_COINGECKO_REQUEST
    if time_since_last < COINGECKO_RATE_LIMIT:
        logger.info(f"Sleeping {COINGECKO_RATE_LIMIT - time_since_last:.2f}s for CoinGecko rate limit")
        time.sleep(COINGECKO_RATE_LIMIT - time_since_last)
    
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd"
        logger.info(f"Requesting CoinGecko price: {url}")
        response = requests.get(url, timeout=10)
        LAST_COINGECKO_REQUEST = time.time()
        logger.info(f"CoinGecko response: {response.status_code} {response.text}")
        
        if response.status_code == 429:
            logger.error(f"CoinGecko API rate limit exceeded for {symbol}")
            return 0
        elif response.status_code != 200:
            logger.error(f"CoinGecko API error {response.status_code} for {symbol}: {response.text}")
            return 0
            
        data = response.json()
        usd = data.get(coingecko_id, {}).get("usd", 0)
        if usd:
            TOKEN_PRICE_CACHE[symbol] = usd
            logger.info(f"Fetched price for {symbol}: {usd}")
        else:
            logger.warning(f"No USD price found for {symbol} (mint: {mint})")
        return usd
        
    except (RequestException, Timeout) as e:
        logger.error(f"Ошибка получения курса {symbol.upper()}: {e}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error getting price for {symbol}: {e}")
        return 0

@app.route('/webhook', methods=['POST'])
def webhook():
    auth_header = request.headers.get('Authorization')
    logger.info(f"Received webhook with Authorization: {auth_header}")
    if auth_header != f'Bearer {WEBHOOK_SECRET}':
        logger.error(f"❌ Неверный токен: {auth_header}")
        return 'Forbidden', 403

    try:
        data = request.get_json(force=True)
        logger.info(f"Webhook payload: {json.dumps(data)[:1000]}")  # log up to 1000 chars
        txs = data if isinstance(data, list) else data.get("transactions", [])

        for tx in txs:
            tx_type = tx.get("type", "неизвестно")
            signature = tx.get("signature", "нет")
            logger.info(f"Processing tx: type={tx_type}, signature={signature}")
            msg = f"📥 <b>Новая транзакция: # {tx_type}</b>\n🔗 <a href='https://solscan.io/tx/{signature}'>{signature}</a>"

            transfers = tx.get("tokenTransfers", [])
            if transfers:
                msg += "\n\n📦 <b>Перемещения токенов:</b>"
                for t in transfers:
                    mint = t.get("mint", "")
                    from_addr = t.get("fromUserAccount", "")
                    to_addr = t.get("toUserAccount", "")
                    logger.info(f"Transfer: mint={mint}, from={from_addr}, to={to_addr}")
                    if from_addr in FEE_WALLETS or to_addr in FEE_WALLETS:
                        logger.info(f"Skipping fee wallet transfer: from={from_addr}, to={to_addr}")
                        continue  # пропускаем комиссии

                    raw_amount = t.get("tokenAmount", 0)
                    name, symbol, decimals = get_token_info(mint)
                    amount = int(raw_amount) / (10 ** decimals) if decimals else float(raw_amount)

                    price_per_token = get_token_usd_price(symbol, mint)
                    usd = amount * price_per_token if price_per_token else 0

                    emoji = "🟢" if to_addr and not from_addr else "🔴"
                    amount_line = f"{emoji} <b>{amount:.6f}</b>{f' (~${usd:.2f})' if usd else ''}"

                    msg += (
                        f"\n🔸 <b>{name}</b> ({symbol})"
                        f"\n📤 От: {shorten(from_addr)}"
                        f"\n📥 Кому: {shorten(to_addr)}"
                        f"\n💰 Сумма: {amount_line}"
                        f"\n<code>{mint}</code>\n"  # Add token address as copyable code block
                    )

            send_telegram_message(msg)

        return '', 200

    except Exception as e:
        logger.error(f"❌ Ошибка обработки запроса: {str(e)}", exc_info=True)
        return 'Internal Server Error', 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)