"""Telegram notifier with command polling + diagnostic logging.

Diagnostic features:
  - get_me() at startup: logs bot id/username so user can verify which
    Telegram bot is v7 (vs other bots in the same chat).
  - Verbose polling logs: every getUpdates response, every command
    received, every chat_id mismatch is printed to Railway stdout.
  - Tolerates `/cmd@bot_username` suffix (Telegram group convention).
"""
from __future__ import annotations
import requests
import time
from typing import Callable, Optional

from . import config as cfg


_last_update_id = 0
_bot_username: Optional[str] = None  # learned at startup
_bot_id: Optional[int] = None


def get_me() -> Optional[dict]:
    """Look up our own bot's username/id once. Stored for use in command matching."""
    global _bot_username, _bot_id
    if not cfg.TG_TOKEN:
        print("[TG getMe SKIP — no token]", flush=True)
        return None
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{cfg.TG_TOKEN}/getMe", timeout=5)
        if r.status_code != 200:
            print(f"[TG getMe FAIL — {r.status_code}] {r.text[:200]}", flush=True)
            return None
        info = r.json().get("result", {})
        _bot_id = info.get("id")
        _bot_username = info.get("username")
        first_name = info.get("first_name", "")
        print(f"[TG getMe] id={_bot_id} username=@{_bot_username} name={first_name}",
              flush=True)
        return info
    except Exception as e:
        print(f"[TG getMe EXC] {e}", flush=True)
        return None


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


# v6.50: KIS 와 호환되는 send_force alias (claude_agent.py 에서 사용)
def send_force(msg: str, parse_mode: Optional[str] = "HTML"):
    """KIS telegram.send_force 와 동일 인터페이스. 단순 alias."""
    send(msg, parse_mode=parse_mode)


def _split_cmd_args(text: str) -> tuple[str, str]:
    """v6.51: /cmd args 분리."""
    text = text.strip()
    if not text.startswith("/"):
        return text, ""
    parts = text.split(None, 1)
    cmd = parts[0]
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args


# v6.51: 마지막 명령 args (handler 에서 notifier._last_args 로 접근)
_last_args: str = ""


def _normalize(text: str) -> str:
    """'/status@my_bot_username 인자' → '/status'."""
    text = text.strip()
    if not text.startswith("/"):
        return text
    head = text.split()[0]            # drop trailing args
    if "@" in head:
        head = head.split("@", 1)[0]  # drop @bot_username
    return head


def poll_commands(handlers: dict[str, Callable[[], None]]):
    """Poll for /commands. handlers maps '/cmd' -> callable taking no args.

    Diagnostic: prints every received update so we can see in Railway logs
    whether messages reach v7 at all (vs being consumed by another bot
    sharing the same TG_TOKEN, vs sent to the wrong chat_id).
    """
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
            print(f"[TG poll FAIL — {r.status_code}] {r.text[:200]}", flush=True)
            return
        updates = r.json().get("result", [])
        if not updates:
            return
        print(f"[TG poll] {len(updates)} update(s) received", flush=True)
        for upd in updates:
            _last_update_id = upd["update_id"]
            msg = upd.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            from_user = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name", "?")
            raw_text = (msg.get("text") or "")
            text = _normalize(raw_text)
            # v6.51: args 저장
            _, _args = _split_cmd_args(raw_text)
            global _last_args
            _last_args = _args
            print(
                f"[TG upd #{upd['update_id']}] from=@{from_user} chat={chat_id} "
                f"text={raw_text[:80]!r} → normalized={text!r}",
                flush=True,
            )

            # chat_id mismatch (someone DM'd the bot from a different chat)
            if chat_id and chat_id != str(cfg.TG_CHAT_ID):
                print(
                    f"[TG ignore — chat mismatch] got {chat_id!r}, "
                    f"expected {cfg.TG_CHAT_ID!r}",
                    flush=True,
                )
                continue

            handler = handlers.get(text)
            if not handler:
                if text.startswith("/"):
                    print(f"[TG unknown cmd] {text}", flush=True)
                continue

            print(f"[TG cmd] dispatching {text}", flush=True)
            try:
                handler()
            except Exception as e:
                import traceback
                print(f"[TG cmd EXC] {text}: {e}", flush=True)
                traceback.print_exc()
                send(f"명령 처리 오류: {e}")
    except Exception as e:
        print(f"[TG poll EXC] {e}", flush=True)
