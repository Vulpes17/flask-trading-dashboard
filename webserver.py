# ================================
# Imports & Config
# ================================
import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, render_template, redirect, url_for
import requests
import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Flask app
app = Flask(__name__)

# File paths
SIGNAL_LOG = "signal_log.json"
TRADE_LOG = "trade_log.json"
MODE_FILE = "mode.json"


# ================================
# Mode Management
# ================================
def get_current_mode():
    try:
        with open(MODE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        # Default values if file missing
        return {"account_type": "paper", "trade_mode": "test"}


def set_current_mode(account_type=None, trade_mode=None):
    mode = get_current_mode()
    if account_type:
        mode["account_type"] = account_type
    if trade_mode:
        mode["trade_mode"] = trade_mode
    with open(MODE_FILE, "w") as f:
        json.dump(mode, f)

@app.route("/set_mode", methods=["POST"])
def set_mode():
    account_type = request.form.get("account_type")
    trade_mode = request.form.get("trade_mode")
    if account_type not in ["paper", "live"]:
        account_type = "paper"
    if trade_mode not in ["test", "real"]:
        trade_mode = "test"
    set_current_mode(account_type, trade_mode)
    return redirect(url_for("dashboard"))

def get_alpaca_keys():
    """Return Alpaca keys/URL depending on account type."""
    mode = get_current_mode()
    if mode["account_type"] == "paper":
        return (
            os.getenv("APCA_API_KEY_ID_PAPER"),
            os.getenv("APCA_API_SECRET_KEY_PAPER"),
            "https://paper-api.alpaca.markets",
        )
    else:
        return (
            os.getenv("APCA_API_KEY_ID_LIVE"),
            os.getenv("APCA_API_SECRET_KEY_LIVE"),
            "https://api.alpaca.markets",
        )

@app.route("/set_mode", methods=["POST"])
def set_mode():
    account_type = request.form.get("account_type", "paper").lower()
    if account_type not in ["paper", "live"]:
        account_type = "paper"
    set_current_mode(account_type)
    return redirect(url_for("dashboard"))


# ================================
# Filters & Routes
# ================================
@app.template_filter("prettytime")
def prettytime_filter(value: str) -> str:
    """Convert UTC ISO timestamp into local time (for dashboard display)."""
    try:
        dt_utc = datetime.fromisoformat(value.replace("Z", "")).replace(tzinfo=ZoneInfo("UTC"))
        return dt_utc.astimezone(ZoneInfo("US/Central")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value


@app.route("/dashboard")
def dashboard():
    # Load logs
    try:
        with open(SIGNAL_LOG, "r") as f:
            signals = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        signals = []

    try:
        with open(TRADE_LOG, "r") as f:
            trades = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        trades = []

    # Market status
    try:
        ALPACA_KEY, ALPACA_SECRET, BASE_URL = get_alpaca_keys()
        api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, BASE_URL, api_version="v2")
        clock = api.get_clock()
        market_status = "OPEN" if clock.is_open else "CLOSED"
    except Exception as e:
        market_status = f"Error: {e}"

    # ✅ Unpack current_mode dict
    mode = get_current_mode()
    account_type = mode.get("account_type", "paper")
    trade_mode = mode.get("trade_mode", "test")

    return render_template(
        "dashboard.html",
        account_type=account_type,
        trade_mode=trade_mode,
        signals=signals,
        trades=trades,
        market_status=market_status
    )


@app.route("/")
def home():
    """Redirect root to dashboard page."""
    return redirect(url_for("dashboard"))


@app.route("/webhook", methods=["POST"])
def webhook():
    ALPACA_KEY, ALPACA_SECRET, BASE_URL = get_alpaca_keys()

    try:
        # 1. Parse + Validate webhook payload
        data = request.get_json(force=True)
        if not validate_webhook(data):
            return jsonify({"status": "error", "message": "Invalid payload"}), 400

        # 2. Get Alpaca account info once
        api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, BASE_URL, api_version="v2")
        account = api.get_account()

        # 3. Checkpoints
        msg = check_status(data, account)
        if msg:
            return jsonify({"status": "blocked", "message": msg}), 200

        msg = check_daytrade_count(data, account)
        if msg:
            return jsonify({"status": "blocked", "message": msg}), 200

        msg = check_cash_balance(data, account)
        if msg:
            return jsonify({"status": "blocked", "message": msg}), 200

        # 4. Route strategy: options, equity, or crypto
        result = options_or_equity(data)

        # 5. Log + return result
        log_signal(data)
        return jsonify({"status": "success", "result": result}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ================================
# Webhook Validation
# ================================
def validate_webhook(data: dict) -> bool:
    REQUIRED_FIELDS = {"strategy_id", "signal", "ticker"}
    return all(field in data for field in REQUIRED_FIELDS)


# ================================
# Checkpoints
# ================================
def check_status(data, account):
    if account.status != "ACTIVE":
        return f"Account status is {account.status}"
    return None

def check_daytrade_count(data, account):
    if int(account.daytrade_count) <= 0:
        return "No day trades left"
    return None

def check_cash_balance(data, account):
    if float(account.cash) < 200:
        return "Insufficient balance"
    return None


# ================================
# Trade Routing
# ================================
def options_or_equity(signal: dict):
    """Decide if webhook is for options, equities, or crypto."""
    strategy_id = signal.get("strategy_id", "").lower()
    mode = get_current_mode()

    if "options" in strategy_id:
        if mode["trade_mode"] == "test":
            order_json = build_options_explorer(signal)
        else:
            order_json = build_options_order(signal)
    elif "crypto" in strategy_id:
        order_json = build_crypto_order(signal)
    else:
        order_json = build_equity_order(signal)

    return send_order_to_alpaca(order_json)


# ================================
# Order Builders
# ================================
def build_options_order(signal: dict) -> dict:
    return {
        "symbol": "SPY250919C00500000",  # placeholder
        "qty": 1,
        "side": signal["signal"],
        "type": "market",
        "time_in_force": "day"
    }

def build_options_explorer(signal: dict) -> dict:
    return {
        "symbol": "SPY250919C00500000",  # placeholder
        "qty": 1,
        "side": signal["signal"],
        "type": "market",
        "time_in_force": "day"
    }

def build_equity_order(signal: dict) -> dict:
    return {
        "symbol": signal["ticker"],
        "qty": 1,
        "side": signal["signal"],
        "type": "market",
        "time_in_force": "day"
    }

def build_crypto_order(signal: dict) -> dict:
    return {}


# ================================
# Alpaca Execution
# ================================
def send_order_to_alpaca(order_json: dict) -> dict:
    ALPACA_KEY, ALPACA_SECRET, BASE_URL = get_alpaca_keys()
    url = f"{BASE_URL}/v2/orders" if "C" not in order_json["symbol"] else f"{BASE_URL}/v2/options/orders"
    headers = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}

    try:
        r = requests.post(url, json=order_json, headers=headers)
        return r.json()
    except Exception as e:
        log_trade_error(order_json.get("symbol", "N/A"), order_json.get("side", "N/A"), e)
        return {"status": "error", "message": str(e)}


# ================================
# Logging Helpers
# ================================
def log_signal(signal: dict):
    try:
        with open(SIGNAL_LOG, "r+") as f:
            data = json.load(f)
            data.append(signal)
            f.seek(0)
            json.dump(data, f, indent=2)
    except FileNotFoundError:
        with open(SIGNAL_LOG, "w") as f:
            json.dump([signal], f, indent=2)

def log_trade_error(symbol: str, side: str, error: Exception):
    with open("alpaca_errors.log", "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} - {symbol} - {side} - {error}\n")


# ================================
# Run Server
# ================================
if __name__ == "__main__":
    from waitress import serve
    import logging
    logging.basicConfig(level=logging.INFO)
    serve(app, host="0.0.0.0", port=5000)