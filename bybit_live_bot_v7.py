"""Bybit live bot v7 — Strategy D (dynamic leverage) + 50% margin.

This is a thin entry point. All logic lives in the bot_v7/ package.

Run:
    python bybit_live_bot_v7.py

Required env:
    BYBIT_API_KEY, BYBIT_API_SECRET
Optional env:
    TG_TOKEN, TG_CHAT_ID, TESTNET, SYMBOL, MARGIN_PCT, CAPITAL_FRACTION
"""
import sys

if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    from bot_v7.runner import main
    main()
