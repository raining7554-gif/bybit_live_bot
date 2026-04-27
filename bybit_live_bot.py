"""Compatibility shim: legacy entry point now launches v7.

If your Railway/PM2/whatever config still says
    python bybit_live_bot.py
this file forwards to the v7 package so deployment doesn't need to be
reconfigured. The original v6.3d code is preserved in git history (last
commit before this change: 28c78b5).

To roll back to v6.3d:
    git checkout 28c78b5 -- bybit_live_bot.py
"""
import sys

if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    print("[launcher] bybit_live_bot.py -> forwarding to v7 (bot_v7.runner)", flush=True)
    try:
        from bot_v7.runner import main
        main()
    except Exception as e:
        import traceback
        print(f"[launcher FATAL] {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        sys.exit(1)
