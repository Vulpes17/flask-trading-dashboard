import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify, render_template, redirect, url_for
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi
# from flask import render_template

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


@app.template_filter('prettytime')
def prettytime_filter(value):
    try:
        # Parse ISO timestamp from logs
        dt = datetime.fromisoformat(value.replace("Z", ""))

        # Convert UTC → Local
        dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt_local = dt_utc.astimezone(ZoneInfo("US/Central"))  # change this to your timezone

        return dt_local.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value  # fallback if parsing fails


@app.route("/dashboard")
def dashboard():
    try:
        with open("signal_log.json", "r") as f:
            signals = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        signals = []

    # Check Alpaca market clock
    try:
        api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, BASE_URL, api_version="v2")
        clock = api.get_clock()
        market_status = "OPEN" if clock.is_open else "CLOSED"
    except Exception as e:
        market_status = f"Error: {e}"

    # newest first
    signals = list(reversed(signals))

    print(f"DEBUG — market_status = {market_status}")  # 🔎 debug line

    return render_template("dashboard.html", signals=signals, market_status=market_status)


# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()

        # ✅ Basic validation
        required_fields = ["strategy_id", "signal", "ticker", "price"]
        for field in required_fields:
            if field not in data:
                return jsonify({"status": "error", "message": f"Missing field: {field}"}), 400

        strategy_id = data["strategy_id"]
        action = data["signal"].lower()
        ticker = data["ticker"].upper()
        price = float(data["price"])

        signal = {
            "strategy_id": strategy_id,
            "signal": action,
            "ticker": ticker,
            "price": price,
            "timestamp": datetime.utcnow().isoformat(),
            "alpaca_status": {}  # placeholder, updated after trade attempt
        }

        # ✅ Route to strategy handler
        if strategy_id == "spy_options":
            result = handle_spy_options(action, ticker, price)
            signal["alpaca_status"] = {
                "status": result.get("status", "error"),
                "message": result.get("message", "N/A"),
                "raw": result
            }

        # Add to in-memory log
        recent_signals.append(signal)

        # ✅ Save immediately to disk
        try:
            with open("signal_log.json", "w") as f:
                json.dump(recent_signals, f, indent=2)
        except Exception as e:
            app.logger.error(f"Error writing signal_log.json: {e}")

        return jsonify({"status": "success", "signal": signal}), 200

    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



def handle_spy_options(action, ticker, price):
    url = f"{BASE_URL}/v2/options/orders"
    headers = {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET
    }

    # 🔒 Hardcoded for testing (update this with a real contract)
    option_symbol = "SPY250917C00658000"
    # SPY, Sept 19 2025 expiry, 500 strike call

    order = {
        "symbol": option_symbol,
        "qty": 1,
        "side": action.lower(),
        "type": "market",
        "time_in_force": "day"
    }

    r = requests.post(url, json=order, headers=headers)
    response = r.json()
    print("Options order response:", response)
    return response


@app.route("/manual_trade", methods=["POST"])
def manual_trade():
    symbol = request.form.get("symbol")
    qty = int(request.form.get("qty", 1))
    side = request.form.get("side", "buy")

    try:
        order_response = place_order(symbol, qty, side)

        # Normalize status field
        status = order_response.get("status", "unknown")
        if status not in ["success", "error", "skipped"]:
            status = "unknown"

        log_entry = {
            "timestamp": datetime.now(ZoneInfo("UTC")).isoformat(),
            "timestamp_local": datetime.now(ZoneInfo("US/Central")).isoformat(),
            "source": "manual",
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "order_id": order_response.get("id", "N/A"),
            "alpaca_status": {
                "status": status,
                "message": order_response.get("message", "N/A"),
                "raw": getattr(order_response, "_raw", {})
            }
        }

        with open("signal_log.json", "r+") as f:
            data = json.load(f)
            data.append(log_entry)
            f.seek(0)
            json.dump(data, f, indent=2)

        print(f"✅ Manual trade logged: {log_entry}")

    except Exception as e:
        log_entry = {
            "timestamp": datetime.now(ZoneInfo("UTC")).isoformat(),
            "timestamp_local": datetime.now(ZoneInfo("US/Central")).isoformat(),
            "source": "manual",
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "order_id": "N/A",
            "alpaca_status": {
                "status": "error",
                "message": str(e),
                "raw": {}
            }
        }
        with open("signal_log.json", "r+") as f:
            data = json.load(f)
            data.append(log_entry)
            f.seek(0)
            json.dump(data, f, indent=2)

        print(f"❌ Error placing manual trade: {e}")

    return redirect(url_for("dashboard"))


# Alpaca trading logic
def normalize_symbol(symbol: str) -> str:
    """Normalize symbols so ETH/USD == ETHUSD"""
    return symbol.replace("/", "").upper()


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
            if clock.is_open:
                print("DEBUG: Market is open, placing MARKET order")
                order_args = {
                    "symbol": symbol,
                    "qty": qty,
                    "side": side,
                    "type": "market",
                    "time_in_force": "gtc"
                }
            else:
                last_price = api.get_last_trade(symbol).price
                print(f"DEBUG: Market is closed, placing LIMIT order at {last_price}")
                order_args = {
                    "symbol": symbol,
                    "qty": qty,
                    "side": side,
                    "type": "limit",
                    "limit_price": last_price,
                    "time_in_force": "day",
                    "extended_hours": True
                }
        else:
            print("DEBUG: Crypto trade detected, using MARKET order (24/7)")
            order_args = {
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "type": "market",
                "time_in_force": "gtc"
            }

        # ✅ Submit order
        order = api.submit_order(**order_args)
        print(f"✅ Alpaca order placed: {side.upper()} {qty} {symbol}")
        return {
            'status': 'success',
            'order_id': order.id,
            'raw': order._raw
        }

    except tradeapi.rest.APIError as e:
        log_trade_error(symbol, side, e)
        return {'status': 'error', 'message': f'Alpaca API error: {str(e)}', 'raw': {}}

    except Exception as e:
        log_trade_error(symbol, side, e)
        return {'status': 'error', 'message': f'Unexpected error: {str(e)}', 'raw': {}}


# Optional: Error logging
def log_trade_error(symbol, side, error):
    """Log errors to alpaca_errors.log with UTC timestamps"""
    with open("alpaca_errors.log", "a") as f:
        f.write(
            f"{datetime.now(timezone.utc).isoformat()} - {symbol} - {side} - {str(error)}\n"
        )
    print(f"❌ Error placing order: {error}")


# Root test route
@app.route('/')
def home():
    return "<h1>Trading Dashboard is running!</h1>"


# Run the app
if __name__ == "__main__":
    from waitress import serve
    import logging
    logging.basicConfig(level=logging.INFO)
    serve(app, host="0.0.0.0", port=5000)
