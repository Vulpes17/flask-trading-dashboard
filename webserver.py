import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi
from flask import render_template

# Load environment variables from .env
load_dotenv()

# Load keys from .env
USE_PAPER = True  # Toggle this to False for live trades

if USE_PAPER:
    ALPACA_KEY = os.getenv('APCA_API_KEY_ID_PAPER')
    ALPACA_SECRET = os.getenv('APCA_API_SECRET_KEY_PAPER')
    BASE_URL = 'https://paper-api.alpaca.markets'
else:
    ALPACA_KEY = os.getenv('APCA_API_KEY_ID_LIVE')
    ALPACA_SECRET = os.getenv('APCA_API_SECRET_KEY_LIVE')
    BASE_URL = 'https://api.alpaca.markets'


# Flask app
app = Flask(__name__)

# Required fields and signal types
REQUIRED_FIELDS = {'strategy_id', 'signal', 'ticker', 'price'}
VALID_SIGNALS = {'buy', 'sell'}

# Signal storage
SIGNAL_LOG_FILE = 'signal_log.json'
recent_signals = []

# Load past signals at startup
try:
    with open(SIGNAL_LOG_FILE, 'r') as f:
        recent_signals = json.load(f)
    print(f"📦 Loaded {len(recent_signals)} past signals into memory.")
except (FileNotFoundError, json.JSONDecodeError):
    recent_signals = []
    print("📂 No signal log found — starting fresh.")


@app.route('/dashboard')
def dashboard():
    # show latest 50 signals (already stored in memory)
    return render_template("dashboard.html", signals=recent_signals[::-1])


# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Invalid or missing JSON'}), 400

    # Validate required fields
    missing = REQUIRED_FIELDS - data.keys()
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    # Validate signal
    if data['signal'].lower() not in VALID_SIGNALS:
        return jsonify({'error': 'Invalid signal value (must be "buy" or "sell")'}), 400

    # Validate price
    try:
        data['price'] = float(data['price'])
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid price (must be a float)'}), 400

    # Add timestamp
    data['timestamp'] = datetime.utcnow().isoformat()

    # Execute trade via Alpaca
    alpaca_result = place_order(
        symbol=data['ticker'],
        side=data['signal'],
        qty=1,
        use_paper=USE_PAPER
    )
    data['alpaca_status'] = alpaca_result

    # Save to memory
    recent_signals.append(data)
    recent_signals[:] = recent_signals[-50:]

    # Save to file
    with open(SIGNAL_LOG_FILE, 'w') as f:
        json.dump(recent_signals, f, indent=2)

    print("✅ Webhook received and processed:", data)
    return jsonify({'status': 'received'}), 200


# Alpaca trading logic
def place_order(symbol, side, qty=1, use_paper=True):
    try:
        api = tradeapi.REST(
            key_id=ALPACA_KEY,
            secret_key=ALPACA_SECRET,
            base_url=BASE_URL,
            api_version='v2'
        )

        # 🕒 Skip market clock check for crypto (24/7 trading)
        is_crypto = '/' in symbol

        if not is_crypto:
            clock = api.get_clock()
            if not clock.is_open:
                return {'status': 'error', 'message': 'Market is closed'}

        # ✅ Buying power check
        account = api.get_account()
        if float(account.buying_power) < 5:
            return {'status': 'error', 'message': 'Insufficient buying power'}

        # ✅ Get all open positions
        positions = api.list_positions()

        if positions:
            holding_tickers = [p.symbol for p in positions]

            # If already holding *any* position, reject unless this is a close-out sell
            for p in positions:
                if p.symbol != symbol:
                    return {
                        'status': 'skipped',
                        'message': f'Already holding {p.symbol}, single-position mode enforced'
                    }
                elif side == 'buy':
                    return {
                        'status': 'skipped',
                        'message': f'Already holding {symbol}, cannot buy again'
                    }
                elif side == 'sell' and int(p.qty) == 0:
                    return {
                        'status': 'skipped',
                        'message': f'No position to sell'
                    }

        # ✅ Submit order
        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type='market',
            time_in_force='gtc'
        )

        print(f"✅ Alpaca order placed: {side.upper()} {qty} {symbol}")
        return {'status': 'success', 'order_id': order.id}

    except tradeapi.rest.APIError as e:
        log_trade_error(symbol, side, e)
        return {'status': 'error', 'message': f'Alpaca API error: {str(e)}'}

    except Exception as e:
        log_trade_error(symbol, side, e)
        return {'status': 'error', 'message': f'Unexpected error: {str(e)}'}



# Optional: Error logging
def log_trade_error(symbol, side, error):
    with open("alpaca_errors.log", "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} - {symbol} - {side} - {str(error)}\n")
    print(f"❌ Error placing order: {error}")


# Root test route
@app.route('/')
def home():
    return "<h1>Trading Dashboard is running!</h1>"


# Run the app
if __name__ == '__main__':
    app.run(debug=True)
