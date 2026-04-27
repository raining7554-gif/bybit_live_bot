"""Telegram notifier with command polling. Subset of v6.3d's commands plus /score."""
from __future__ import annotations
import requests
import time
from typing import Callable, Optional

from . import config as cfg


_last_update_id = 0


def send(msg: str, parse_mode: Optional[str] = "HTML"):
    if not cfg.TG_TOKEN or not cfg.TG_CHAT_ID:
        print(f"[TG SKIP — no token/chat] {msg[:120]}", flush=True)
        return
    try:
        payload = {"chat_id": cfg.TG_CHAT_ID, "text": msg}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        r = requests.post(
            f"https://api.telegram.org/bot{cfg.TG_TOKEN}/sendMessage",
            json=payload, timeout=5,
        )
        if r.status_code == 200:
            print(f"[TG OK] {msg[:80].replace(chr(10), ' | ')}", flush=True)
            return
        # Retry plain text on parse errors
        body = r.text[:200]
        print(f"[TG retry plain — {r.status_code}] {body}", flush=True)
        r2 = requests.post(
            f"https://api.telegram.org/bot{cfg.TG_TOKEN}/sendMessage",
            json={"chat_id": cfg.TG_CHAT_ID, "text": msg}, timeout=5,
        )
        if r2.status_code == 200:
            print(f"[TG OK plain] {msg[:80].replace(chr(10), ' | ')}", flush=True)
        else:
            print(f"[TG FAIL — {r2.status_code}] {r2.text[:200]}", flush=True)
    except Exception as e:
        print(f"[TG EXC] {type(e).__name__}: {e}", flush=True)


def poll_commands(handlers: dict[str, Callable[[], None]]):
    """Poll for /commands. handlers maps '/cmd' -> callable taking no args."""
    global _last_update_id
    if not cfg.TG_TOKEN or not cfg.TG_CHAT_ID:
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{cfg.TG_TOKEN}/getUpdates",
            params={"offset": _last_update_id + 1, "timeout": 0, "limit": 10},
            timeout=6,
        )
        if r.status_code != 200:
            return
        for upd in r.json().get("result", []):
            _last_update_id = upd["update_id"]
            msg = upd.get("message", {})
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            handler = handlers.get(text)
            if handler:
                try:
                    handler()
                except Exception as e:
                    send(f"명령 처리 오류: {e}")
    except Exception as e:
        print(f"[TG poll err] {e}", flush=True)
