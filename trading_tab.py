import os
import tkinter as tk
from tkinter import ttk, messagebox
from alpaca_connector import AlpacaConnector  # Your custom class
from dotenv import load_dotenv

load_dotenv()

class TradingTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.connector = None
        self.build_status_boxes()

    def build_status_boxes(self):
        self.broker_status = ttk.LabelFrame(self, text="Broker Status")
        self.broker_status.pack(fill='x', padx=10, pady=5)

        # Variables
        self.broker_status_var = tk.StringVar(value="Connection: Not Connected")
        self.account_number_var = tk.StringVar(value="Account ID: ----")
        self.account_amount_var = tk.StringVar(value="Cash: $0.00")
        self.day_trade_count_var = tk.StringVar(value="Day Trades Today: -")
        self.use_paper_var = tk.BooleanVar(value=False)

        # Labels
        ttk.Label(self.broker_status, textvariable=self.broker_status_var).pack(anchor='w', padx=5)
        ttk.Label(self.broker_status, textvariable=self.account_number_var).pack(anchor='w', padx=5)
        ttk.Label(self.broker_status, textvariable=self.account_amount_var).pack(anchor='w', padx=5)
        ttk.Label(self.broker_status, textvariable=self.day_trade_count_var).pack(anchor='w', padx=5)

        # Controls
        ttk.Checkbutton(self.broker_status, text="Use Paper Account", variable=self.use_paper_var).pack(anchor='w', padx=5)
        ttk.Button(self.broker_status, text="Connect to Alpaca", command=self.manual_connect_to_alpaca).pack(anchor='w', padx=5, pady=5)

    def manual_connect_to_alpaca(self):
        requested_paper = self.use_paper_var.get()

        # Attempt connection
        connector = AlpacaConnector(use_paper=requested_paper)
        connected = connector.connect()

        # Auto-switch logic
        if connected and not requested_paper:
            acct = connector.get_account_info()
            if acct and acct['daytrade_count'] >= 3:
                messagebox.showwarning(
                    "Day Trade Limit Reached",
                    "Live account has hit the 3-day-trade limit.\nSwitching to Paper Trading mode."
                )
                requested_paper = True
                connector = AlpacaConnector(use_paper=True)
                connected = connector.connect()

        self.connector = connector

        # Update GUI
        if connected:
            acct = self.connector.get_account_info()
            is_paper = self.connector.use_paper

            self.broker_status_var.set(f"✅ Connected to {'Paper' if is_paper else 'Live'} Account")
            self.account_number_var.set(f"Account ID: {acct['id']}")
            self.account_amount_var.set(f"Cash: ${acct['cash']}")
            self.day_trade_count_var.set(f"Day Trades Today: {acct['daytrade_count']}")

            if not is_paper and acct['daytrade_count'] >= 3:
                self.day_trade_count_var.set(f"⚠️ PDT Limit Hit — Switched to Paper")
                self.use_paper_var.set(True)
        else:
            self.broker_status_var.set("❌ Connection Failed")
            self.account_number_var.set("Account ID: ----")
            self.account_amount_var.set("Cash: $0.00")
            self.day_trade_count_var.set("Day Trades Today: -")
