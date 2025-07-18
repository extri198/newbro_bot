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
    "9yj3zvLS3fDMqi1F8zhkaWfq8TZpZWHe6cz1Sgt7djXf", # phantom fees
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

SOL_MINTS = {"So11111111111111111111111111111111111111112"}

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
            msg = f"📥 <b>Новая транзакция: {tx_type}</b>" # \n🔗 <a href='https://solscan.io/tx/{signature}'>{signature}</a>

            account_data = tx.get("accountData", [])
            # Aggregate all SPL token transfers from all accounts if available
            aggregated_transfers = []
            for account in account_data:
                # Some APIs use 'tokenBalanceChanges' or similar per account
                token_changes = account.get('tokenBalanceChanges')
                if token_changes and isinstance(token_changes, list):
                    aggregated_transfers.extend(token_changes)
            # If no per-account token changes, fallback to top-level 'tokenTransfers'
            if not aggregated_transfers:
                aggregated_transfers = tx.get("tokenTransfers", [])
            # Show SOL spent/received for the signer (first account in accountData)
            signer_sol_line = ""
            if account_data:
                signer_account = account_data[0].get("account")
                signer_change = account_data[0].get("nativeBalanceChange", 0)
                if signer_change != 0:
                    sol_amount = signer_change / 1_000_000_000
                    emoji = "🟢" if sol_amount > 0 else "🔴"
                    # Fetch SOL price in USD
                    sol_usd_price = get_token_usd_price("SOL", "So11111111111111111111111111111111111111112")
                    usd = abs(sol_amount) * sol_usd_price if sol_usd_price else 0
                    usd_str = f" (~${usd:.2f})" if usd else ""
                    amount_line = f"{emoji} <b>{abs(sol_amount):.6f}</b>{usd_str}"
                    signer_sol_line = (
                        f"\n🔸 <b>SOL</b> (signer)"
                        f"\n💰 Сумма: {amount_line}"
                        f"\n<code>So11111111111111111111111111111111111111112</code>\n"
                    )
            # Calculate SPL token price in SOL if possible
            # 1. Find the SPL token transfer where the signer is involved (as sender or receiver)
            main_token_mint = None
            main_token_amount = 0
            signer_account = account_data[0].get("account") if account_data else None
            for t in aggregated_transfers:
                mint = t.get("mint", "")
                if mint in SOL_MINTS:
                    continue
                # Determine address fields based on structure
                if "userAccount" in t or "tokenAccount" in t:
                    from_addr = t.get("userAccount", "")
                    to_addr = t.get("tokenAccount", "")
                else:
                    from_addr = t.get("fromUserAccount", "")
                    to_addr = t.get("toUserAccount", "")
                # Extract amount and decimals
                raw_token_amount = t.get("rawTokenAmount")
                if raw_token_amount and isinstance(raw_token_amount, dict):
                    raw_amount = raw_token_amount.get("tokenAmount", 0)
                    decimals = raw_token_amount.get("decimals")
                else:
                    raw_amount = t.get("tokenAmount", 0)
                    decimals = None
                _, _, default_decimals = get_token_info(mint)
                if decimals is None:
                    decimals = default_decimals
                try:
                    amount = int(raw_amount) / (10 ** decimals) if decimals else float(raw_amount)
                except Exception:
                    amount = 0
                # Use the transfer where the signer is involved
                if signer_account and (from_addr == signer_account or to_addr == signer_account):
                    main_token_mint = mint
                    main_token_amount = amount
                    break  # Use the first found; if multiple, could refine further
            # 3. Get signer's SOL net change
            signer_sol_change = 0
            if account_data:
                signer_sol_change = account_data[0].get("nativeBalanceChange", 0) / 1_000_000_000
            # 4. If both are present and nonzero, calculate price and add to message
            logger.info(f"Debug SPL price: signer_sol_change={signer_sol_change}, main_token_mint={main_token_mint}, main_token_amount={main_token_amount}")
            if main_token_mint and main_token_amount != 0 and signer_sol_change != 0:
                logger.info(f"Debug SPL price condition: (signer_sol_change < 0 < main_token_amount)={signer_sol_change < 0 < main_token_amount}, (signer_sol_change > 0 > main_token_amount)={signer_sol_change > 0 > main_token_amount}")
                if (signer_sol_change < 0 < main_token_amount) or (signer_sol_change > 0 > main_token_amount):
                    _, symbol, _ = get_token_info(main_token_mint)
                    price_per_token_sol = abs(signer_sol_change) / abs(main_token_amount)
                    # Calculate USD price using CoinGecko
                    sol_usd_price = get_token_usd_price("SOL", "So11111111111111111111111111111111111111112")
                    price_per_token_usd = price_per_token_sol * sol_usd_price if sol_usd_price else 0
                    msg += f"\n💱 <b>Цена {symbol} в SOL:</b> {price_per_token_sol:.8f} SOL"
                    msg += f"\n💲 <b>Цена {symbol} в USD:</b> ${price_per_token_usd:.6f}"
                    # Add overall SOL net change line
                    sol_emoji = '🟢' if signer_sol_change > 0 else '🔴'
                    sol_net_usd = signer_sol_change * sol_usd_price if sol_usd_price else 0
                    msg += f"\n{sol_emoji} <b>Net SOL change:</b> {signer_sol_change:.6f} (~${sol_net_usd:.2f})"
                    # Add final SPL token destination address (to_addr) as code block
                    if 'to_addr' in locals() and to_addr:
                        msg += f"\n🏁 <b>Final SPL destination:</b> <code>{to_addr}</code>"
                    # Add copyable signer address
                    if signer_account:
                        msg += f"\n👤 <b>Signer:</b> <code>{signer_account}</code>"

            if signer_sol_line or aggregated_transfers:
                msg += "\n\n📦 <b>------------------------:</b>"
                if signer_sol_line:
                    msg += signer_sol_line
                # Add SPL token transfers
                for t in aggregated_transfers:
                    mint = t.get("mint", "")
                    # Determine address fields based on structure
                    if "userAccount" in t or "tokenAccount" in t:
                        # Per-account tokenBalanceChanges structure
                        from_addr = t.get("userAccount", "")
                        to_addr = t.get("tokenAccount", "")
                    else:
                        # Top-level tokenTransfers structure
                        from_addr = t.get("fromUserAccount", "")
                        to_addr = t.get("toUserAccount", "")
                    if from_addr in FEE_WALLETS or to_addr in FEE_WALLETS:
                        continue  # пропускаем комиссии
                    # Extract amount and decimals from either rawTokenAmount or top-level fields
                    raw_token_amount = t.get("rawTokenAmount")
                    if raw_token_amount and isinstance(raw_token_amount, dict):
                        raw_amount = raw_token_amount.get("tokenAmount", 0)
                        decimals = raw_token_amount.get("decimals")
                    else:
                        raw_amount = t.get("tokenAmount", 0)
                        decimals = None
                    name, symbol, default_decimals = get_token_info(mint)
                    if decimals is None:
                        decimals = default_decimals
                    try:
                        amount = int(raw_amount) / (10 ** decimals) if decimals else float(raw_amount)
                    except Exception as e:
                        logger.error(f"Error calculating amount for mint={mint}: raw_amount={raw_amount}, decimals={decimals}, error={e}")
                        amount = 0
                    logger.info(f"Transfer: mint={mint}, from={from_addr}, to={to_addr}, raw_amount={raw_amount}, decimals={decimals}, amount={amount}")
                    price_per_token = get_token_usd_price(symbol, mint)
                    usd = amount * price_per_token if price_per_token else 0
                    emoji = "🟢" if to_addr and not from_addr else "🔴"
                    amount_line = f"{emoji} <b>{amount:.6f}</b>{f' (~${usd:.2f})' if usd else ''}"
                    msg += (
                        f"\n🔸 <b>{name}</b> ({symbol})"
                        f"\n📤 От: {shorten(from_addr)}"
                        f"\n📥 Кому: {shorten(to_addr)}"
                        f"\n💰 Сумма: {amount_line}"
                        f"\n<code>{mint}</code>\n"
                    )

            send_telegram_message(msg)

        return '', 200

    except Exception as e:
        logger.error(f"❌ Ошибка обработки запроса: {str(e)}", exc_info=True)
        return 'Internal Server Error', 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)