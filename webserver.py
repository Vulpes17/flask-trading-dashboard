import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
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
    with open("signal_log.json", "r") as f:
        signals = json.load(f)

    # Show newest first
    signals = list(reversed(signals))

    return render_template("dashboard.html", signals=signals)


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

        signal = {
            "strategy_id": data["strategy_id"],
            "signal": data["signal"].lower(),
            "ticker": data["ticker"].upper(),
            "price": float(data["price"]),
            "timestamp": datetime.utcnow().isoformat(),
            "alpaca_status": {}  # placeholder, updated after trade attempt
        }

        # Add to in-memory log
        recent_signals.append(signal)

        # ✅ Save immediately to disk
        try:
            with open("signal_log.json", "w") as f:
                json.dump(recent_signals, f, indent=2)
        except Exception as e:
            app.logger.error(f"Error writing signal_log.json: {e}")

        # Place order (optional)
        # result = place_order(signal["ticker"], signal["signal"], 1, use_paper=USE_PAPER)
        # signal["alpaca_status"] = result

        return jsonify({"status": "success", "signal": signal}), 200

    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
def place_order(symbol, side, qty=1, use_paper=True):
    try:
        api = tradeapi.REST(
            key_id=ALPACA_KEY,
            secret_key=ALPACA_SECRET,
            base_url=BASE_URL,
            api_version='v2'
        )

        # ✅ Detect crypto properly (no market hours for crypto)
        is_crypto = symbol.endswith("USD") and len(symbol) > 3

        if not is_crypto:
            clock = api.get_clock()
            if not clock.is_open:
                return {'status': 'error', 'message': 'Market is closed'}

        # ✅ Buying power check (skip for crypto, since buying_power doesn’t apply the same way)
        if not is_crypto:
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
        # Return Alpaca's full raw response (dict-like)
        return order._raw

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
if __name__ == "__main__":
    from waitress import serve
    import logging
    logging.basicConfig(level=logging.INFO)
    serve(app, host="0.0.0.0", port=5000)
