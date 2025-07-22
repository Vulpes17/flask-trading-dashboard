import os
import json
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, request, render_template, jsonify

# Load variables from .env file
load_dotenv()

ALPACA_LIVE_KEY = os.getenv('LIVE_API_KEY')
ALPACA_LIVE_SECRET = os.getenv('LIVE_SECRET_KEY')
ALPACA_PAPER_KEY = os.getenv('PAPER_API_KEY')
ALPACA_PAPER_SECRET = os.getenv('PAPER_SECRET_KEY')

USE_PAPER = True  # Toggle this safely later


app = Flask(__name__)

REQUIRED_FIELDS = {'strategy_id', 'signal', 'ticker'}
VALID_SIGNALS = {'buy', 'sell'}
SIGNAL_LOG_FILE = 'signal_log.json'

# In-memory store
recent_signals = []

# Load past signals at startup (if file exists)
try:
    with open(SIGNAL_LOG_FILE, 'r') as f:
        recent_signals = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    recent_signals = []

# Basic home page for testing
@app.route('/')
def home():
    return "<h1>Trading Dashboard is running!</h1>"

# Webhook endpoint for TradingView
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Invalid or missing JSON'}), 400

    # Check required fields
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

    # Store in memory (max 50 entries)
    recent_signals.append(data)
    recent_signals[:] = recent_signals[-50:]

    # Save to file
    with open(SIGNAL_LOG_FILE, 'w') as f:
        json.dump(recent_signals, f, indent=2)

    print("✅ Valid webhook received and saved:", data)
    return jsonify({'status': 'received'}), 200


print(f"📦 Loaded {len(recent_signals)} past signals into memory.")
print(ALPACA_PAPER_KEY)


if __name__ == '__main__':
    app.run(debug=True)
