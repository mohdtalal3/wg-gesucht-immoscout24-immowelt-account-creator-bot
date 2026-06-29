"""
worker.py — Background bot logic for the Flask app.
Runs account registrations in a separate thread so the web server stays responsive.
"""

import os
import re
import time
import random
import threading
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
from faker import Faker
from supabase import create_client

from wg import WGRegistrar
from immo24_mobile import ImmoScoutMobileRegistrar
from immowelt import ImmoweltRegistrar

load_dotenv()

_PROXY_BASE = re.sub(r':\d+$', '', os.getenv("PROXY_URL", ""))  # strip fixed port
_sb = create_client(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_KEY", ""))


def get_proxy() -> str:
    """Return a proxy URL with a fresh random port (10000–20000) each call."""
    if not _PROXY_BASE:
        return ""
    port = random.randint(10000, 20000)
    return f"{_PROXY_BASE}:{port}"

PLATFORM_VERIFY = {
    "wg-gesucht": {
        "sender_keywords": ["wg-gesucht"],
        "url_keyword":     "email-confirmation",
    },
    "immoscout24": {
        "sender_keywords": ["immobilienscout24", "myscout"],
        "url_keyword":     "sso.immobilienscout24.de/sso/registration",
    },
    "immowelt": {
        "sender_keywords": ["immowelt", "signin.immowelt.de"],
        "url_keyword":     "signin.immowelt.de/u/email-verification",
    },
}

# ── Shared run state (thread-safe) ────────────────────────────────────────────
_state = {
    "active":        False,
    "run_id":        None,
    "total":         0,
    "completed":     0,
    "failed":        0,
    "current_email": "",
    "log":           [],
}
_lock = threading.Lock()


def get_state() -> dict:
    with _lock:
        return {
            "active":        _state["active"],
            "run_id":        _state["run_id"],
            "total":         _state["total"],
            "completed":     _state["completed"],
            "failed":        _state["failed"],
            "current_email": _state["current_email"],
            "log":           list(_state["log"]),
        }


def is_bot_running() -> bool:
    with _lock:
        return _state["active"]


def _log(msg: str):
    print(msg)
    with _lock:
        _state["log"].append(msg)
        if len(_state["log"]) > 600:
            _state["log"] = _state["log"][-600:]


# ── Inbox helpers ─────────────────────────────────────────────────────────────

def _get_inbox_count(email: str, password: str) -> int:
    try:
        from firstmail import firstmail_client
        with firstmail_client(email, password) as c:
            return c.get_message_count()
    except Exception:
        return 0


def _wait_for_link(email, password, sender_kw, url_kw, initial_count=0, timeout=150, interval=8):
    from firstmail import firstmail_client
    _log(f"   ⏳ Polling inbox (timeout: {timeout}s)…")
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(interval)
        try:
            with firstmail_client(email, password) as c:
                count = c.get_message_count()
                if count > initial_count:
                    mails = c.get_all_mail(limit=min(count - initial_count + 5, 30))
                    for mail in mails:
                        sender  = (mail.sender  or "").lower()
                        subject = (mail.subject or "").lower()
                        body    = mail.body or ""
                        if any(kw in sender or kw in subject for kw in sender_kw):
                            urls = re.findall(r"https?://[^\s)<>\"'\]]+", body)
                            for url in urls:
                                if url_kw in url:
                                    _log("   ✓ Verification link found!")
                                    return url
        except Exception as e:
            _log(f"   ⚠️  Inbox poll error: {e}")
        _log(f"   ⏳ Still waiting… ({int(time.time()-start)}s)")
    _log("   ❌ Timeout — verification email not found")
    return None


# ── Per-account processing ────────────────────────────────────────────────────

def _process_account(email, password, first_name, last_name, title, existing_platforms=None):
    skip       = set(existing_platforms or [])
    registered = []

    if "wg-gesucht" in skip:
        _log("\n  ⏭ [1/3] WG-Gesucht — already registered, skipping")
    else:
        _log("\n  ▶ [1/3] WG-Gesucht")
        pre = _get_inbox_count(email, password)
        proxy = get_proxy()
        _log(f"   🌐 Proxy port: {proxy.rsplit(':', 1)[-1]}")
        wg = WGRegistrar(email=email, password=password, first_name=first_name,
                         last_name=last_name, title=title, proxy=proxy)
        if wg.run():
            cfg = PLATFORM_VERIFY["wg-gesucht"]
            url = _wait_for_link(email, password, cfg["sender_keywords"], cfg["url_keyword"], initial_count=pre)
            if url and wg.verify_email(url):
                registered.append("wg-gesucht")
        time.sleep(2)

    if "immoscout24" in skip:
        _log("\n  ⏭ [2/3] ImmoScout24 — already registered, skipping")
    else:
        _log("\n  ▶ [2/3] ImmoScout24")
        pre = _get_inbox_count(email, password)
        proxy = get_proxy()
        _log(f"   🌐 Proxy port: {proxy.rsplit(':', 1)[-1]}")
        is24 = ImmoScoutMobileRegistrar(email=email, password=password, proxy=proxy)
        if is24.run():
            cfg = PLATFORM_VERIFY["immoscout24"]
            url = _wait_for_link(email, password, cfg["sender_keywords"], cfg["url_keyword"], initial_count=pre)
            if url and is24.verify_email(url):
                registered.append("immoscout24")
        time.sleep(2)

    if "immowelt" in skip:
        _log("\n  ⏭ [3/3] Immowelt — already registered, skipping")
    else:
        _log("\n  ▶ [3/3] Immowelt")
        pre = _get_inbox_count(email, password)
        proxy = get_proxy()
        _log(f"   🌐 Proxy port: {proxy.rsplit(':', 1)[-1]}")
        iw = ImmoweltRegistrar(email=email, password=password, proxy=proxy)
        if iw.run():
            cfg = PLATFORM_VERIFY["immowelt"]
            url = _wait_for_link(email, password, cfg["sender_keywords"], cfg["url_keyword"], initial_count=pre)
            if url and iw.verify_email(url):
                registered.append("immowelt")

    return registered


# ── Bot thread ────────────────────────────────────────────────────────────────

def _bot_worker(n_accounts: int, run_id: str):
    fake = Faker("de_DE")

    with _lock:
        _state.update({"active": True, "run_id": run_id, "total": 0,
                       "completed": 0, "failed": 0, "log": [], "current_email": ""})

    try:
        res      = _sb.table("created_accounts").select("*").eq("status", "pending").limit(n_accounts).execute()
        accounts = res.data or []

        with _lock:
            _state["total"] = len(accounts)

        _sb.table("bot_runs").update({"total": len(accounts)}).eq("id", run_id).execute()
        _log(f"🚀 Bot started — processing {len(accounts)} accounts\n")

        for i, account in enumerate(accounts, 1):
            email    = account["email"]
            password = account["password"]

            with _lock:
                _state["current_email"] = email

            gender     = random.choice(["male", "female"])
            title      = "1" if gender == "male" else "2"
            first_name = fake.first_name_male() if gender == "male" else fake.first_name_female()
            last_name  = fake.last_name()

            _log(f"\n{'='*50}")
            _log(f"  [{i}/{len(accounts)}] {email}")
            _log(f"  Name: {first_name} {last_name}  ({'Mr' if gender=='male' else 'Ms'})")
            _log(f"{'='*50}")

            _sb.table("created_accounts").update({
                "status": "running", "first_name": first_name,
                "last_name": last_name, "title": title,
            }).eq("id", account["id"]).execute()

            try:
                existing = account.get("platforms") or []
                registered = _process_account(email, password, first_name, last_name, title, existing)
                all_platforms = list(dict.fromkeys(existing + registered))  # preserve order, dedupe

                if all_platforms:
                    _sb.table("created_accounts").update({
                        "status": "completed", "platforms": all_platforms, "error_msg": "",
                    }).eq("id", account["id"]).execute()
                    with _lock:
                        _state["completed"] += 1
                    new_txt = f" (+{', '.join(registered)})" if registered else " (no new)"
                    _log(f"\n  ✅ Platforms: {', '.join(all_platforms)}{new_txt}")
                else:
                    _sb.table("created_accounts").update({
                        "status": "failed", "error_msg": "No platforms registered",
                    }).eq("id", account["id"]).execute()
                    with _lock:
                        _state["failed"] += 1
                    _log("\n  ❌ Failed: no platforms registered")

            except Exception as e:
                _sb.table("created_accounts").update({
                    "status": "failed", "error_msg": str(e)[:500],
                }).eq("id", account["id"]).execute()
                with _lock:
                    _state["failed"] += 1
                _log(f"\n  ❌ Error: {e}")

            with _lock:
                comp = _state["completed"]
                fail = _state["failed"]
            _sb.table("bot_runs").update({"completed": comp, "failed": fail}).eq("id", run_id).execute()

            if i < len(accounts):
                _log("\n⏳ Waiting 5s before next account…")
                time.sleep(5)

    except Exception as e:
        _log(f"\n❌ Bot fatal error: {e}")
    finally:
        with _lock:
            _state["active"]        = False
            _state["current_email"] = ""
            log_snapshot            = list(_state["log"])

        _sb.table("bot_runs").update({
            "status":      "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "log":         "\n".join(log_snapshot),
        }).eq("id", run_id).execute()
        _log("\n✅ Bot run finished.")


def start_bot(n_accounts: int):
    """Start the bot in a background thread. Returns run_id, or None if already running."""
    if is_bot_running():
        return None
    res    = _sb.table("bot_runs").insert({"status": "running", "total": 0}).execute()
    run_id = res.data[0]["id"]
    t = threading.Thread(target=_bot_worker, args=(n_accounts, run_id), daemon=False)
    t.start()
    return run_id
