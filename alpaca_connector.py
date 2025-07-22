import os
import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

class AlpacaConnector:
    def __init__(self, use_paper=True):
        load_dotenv()
        self.use_paper = use_paper
        self.api = None

        if use_paper:
            self.base_url = os.getenv("PAPER_BASE_URL")
            self.api_key = os.getenv("PAPER_API_KEY")
            self.secret_key = os.getenv("PAPER_SECRET_KEY")
        else:
            self.base_url = os.getenv("LIVE_BASE_URL")
            self.api_key = os.getenv("LIVE_API_KEY")
            self.secret_key = os.getenv("LIVE_SECRET_KEY")

    def connect(self):
        try:
            self.api = tradeapi.REST(
                self.api_key,
                self.secret_key,
                self.base_url,
                api_version='v2'
            )
            # Check connection by fetching account
            _ = self.api.get_account()
            return True
        except Exception as e:
            print(f"Alpaca connection failed: {e}")
            self.api = None
            return False

    def get_account_info(self):
        if not self.api:
            return None
        try:
            account = self.api.get_account()
            return {
                "id": account.id,
                "cash": float(account.cash),
                "daytrade_count": int(account.daytrade_count)
            }
        except Exception as e:
            print(f"Failed to fetch account info: {e}")
            return None
