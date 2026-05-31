"""
cookie_manager.py — Cookie Refresh + GitHub Sync + Multi-Account Rotation

Flow:
  Startup → GitHub se pull → validate → agar invalid → refresh karo
  Har 30 min → check → expiry < 1hr → refresh → GitHub push
  Refresh → sabhi accounts try karo → success → push to GitHub
  Sab fail → backup restore → bot ko DM
"""

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("cookie_manager")

COOKIES_FILE    = os.getenv("COOKIES_FILE", "cookies.txt")
COOKIES_BACKUP  = COOKIES_FILE + ".bak"
COOKIES_PREV    = COOKIES_FILE + ".prev"
CHECK_INTERVAL  = int(os.getenv("COOKIE_CHECK_INTERVAL", "1800"))   # 30 min
REFRESH_BEFORE  = int(os.getenv("COOKIE_REFRESH_BEFORE", "3600"))   # 1 hr pehle
ACCOUNTS_FILE   = os.getenv("ACCOUNTS_FILE", "accounts.json")


# ─────────────────────────────────────────
# ALERT — lazy import (circular se bachao)
# ─────────────────────────────────────────

async def _alert(text: str, level: str = "info"):
    try:
        from tg_bot import send_alert
        await send_alert(text, level=level)
    except Exception:
        pass


# ─────────────────────────────────────────
# ACCOUNTS — file se load karo
# ─────────────────────────────────────────

def load_accounts() -> list:
    """
    accounts.json se accounts load karo.
    YT_ACCOUNTS env variable bhi check karo (fallback).
    """
    # File se try karo
    try:
        if Path(ACCOUNTS_FILE).exists():
            data = json.loads(Path(ACCOUNTS_FILE).read_text())
            if data:
                return data
    except Exception:
        pass

    # Env variable fallback
    try:
        raw = os.getenv("YT_ACCOUNTS", "[]")
        return json.loads(raw)
    except Exception:
        return []


# ─────────────────────────────────────────
# COOKIES HELPERS
# ─────────────────────────────────────────

def cookies_exist() -> bool:
    return Path(COOKIES_FILE).exists() and Path(COOKIES_FILE).stat().st_size > 100


def backup_cookies():
    if cookies_exist():
        shutil.copy2(COOKIES_FILE, COOKIES_BACKUP)
        shutil.copy2(COOKIES_FILE, COOKIES_PREV)
        logger.info("Cookies backed up")


def restore_backup() -> bool:
    for src in [COOKIES_BACKUP, COOKIES_PREV]:
        if Path(src).exists() and Path(src).stat().st_size > 100:
            shutil.copy2(src, COOKIES_FILE)
            logger.warning(f"Cookies restored from {src}")
            return True
    return False


def _parse_netscape_expires(path: str) -> Optional[float]:
    """Cookies file mein sabse jaldi expire hone wala session cookie nikalo."""
    relevant = {
        "SAPISID", "APISID", "SSID", "SID",
        "__Secure-1PSID", "__Secure-3PSID",
        "__Secure-1PAPISID", "__Secure-3PAPISID",
        "LOGIN_INFO",
    }
    earliest = None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                name = parts[5]
                if name not in relevant:
                    continue
                try:
                    exp = float(parts[4])
                    if exp == 0:
                        exp = time.time() + 7200
                    if earliest is None or exp < earliest:
                        earliest = exp
                except ValueError:
                    continue
    except Exception:
        pass
    return earliest


def cookies_status() -> dict:
    if not cookies_exist():
        return {
            "valid": False,
            "expires_at": None,
            "expires_in_sec": None,
            "expires_in_human": "No cookies file",
            "has_backup": Path(COOKIES_BACKUP).exists(),
        }

    exp = _parse_netscape_expires(COOKIES_FILE)
    now = time.time()

    if exp is None:
        return {
            "valid": True,
            "expires_at": None,
            "expires_in_sec": None,
            "expires_in_human": "Unknown expiry",
            "has_backup": Path(COOKIES_BACKUP).exists(),
        }

    remaining = int(exp - now)
    if remaining <= 0:
        human, valid = "EXPIRED", False
    elif remaining < 3600:
        human, valid = f"{remaining // 60} minutes", True
    elif remaining < 86400:
        human, valid = f"{remaining // 3600} hours", True
    else:
        human, valid = f"{remaining // 86400} days", True

    return {
        "valid": valid,
        "expires_at": exp,
        "expires_in_sec": remaining,
        "expires_in_human": human,
        "has_backup": Path(COOKIES_BACKUP).exists(),
    }


# ─────────────────────────────────────────
# REFRESH — yt-dlp se login + cookies bano
# ─────────────────────────────────────────

async def _refresh_one_account(email: str, password: str) -> tuple:
    """
    Ek account se cookies banao.
    Returns: (True, None) ya (False, "error message")
    """
    import yt_dlp

    tmp = COOKIES_FILE + ".tmp"
    _err = []

    def _do():
        opts = {
            "quiet": False,
            "no_warnings": False,
            "skip_download": True,
            "cookiefile": tmp,
            "username": email,
            "password": password,
            "logger": _YtLogger(_err),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    download=False,
                )
            return True
        except yt_dlp.utils.DownloadError as e:
            _err.append(str(e))
            return False
        except Exception as e:
            _err.append(str(e))
            return False

    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, _do)

    err_msg = _err[-1] if _err else "Unknown error"

    if ok and Path(tmp).exists() and Path(tmp).stat().st_size > 100:
        backup_cookies()
        shutil.move(tmp, COOKIES_FILE)
        logger.info(f"✅ Cookies refreshed [{email[:5]}***]")
        return True, None

    if Path(tmp).exists():
        try:
            os.remove(tmp)
        except Exception:
            pass

    logger.error(f"Refresh failed [{email[:5]}***]: {err_msg}")
    return False, err_msg


class _YtLogger:
    """yt-dlp logger — errors capture karo."""
    def __init__(self, errors: list):
        self._e = errors
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg):
        self._e.append(msg)


async def try_refresh_cookies() -> bool:
    """
    Sabhi accounts try karo.
    Success pe GitHub push karo.
    Sab fail ho to backup restore + alert.
    """
    accounts = load_accounts()

    if not accounts:
        logger.warning("Koi account saved nahi — refresh nahi hoga")
        await _alert(
            "⚠️ Koi YouTube account saved nahi!\n"
            "Bot mein `/addaccount` se account add karo.",
            level="warning",
        )
        return False

    for acc in accounts:
        email    = acc.get("email", "").strip()
        password = acc.get("password", "").strip()
        if not email or not password:
            continue

        logger.info(f"Trying [{email[:5]}***]...")
        ok, err_msg = await _refresh_one_account(email, password)
        masked = f"{email[:3]}***@{email.split('@')[-1]}"

        if ok:
            await _alert(
                f"✅ Cookies refreshed!\n📧 Account: `{masked}`",
                level="success",
            )
            # GitHub push karo
            try:
                from github_sync import push_cookies_to_github
                pushed = await push_cookies_to_github(
                    f"chore: refresh cookies [{masked}]"
                )
                if pushed:
                    logger.info("Cookies pushed to GitHub")
                else:
                    logger.warning("GitHub push failed")
            except Exception as e:
                logger.error(f"GitHub push error: {e}")
            return True
        else:
            # Exact error DM karo
            clean_err = (err_msg or "Unknown")[:300]
            await _alert(
                f"⚠️ Refresh failed: `{masked}`\n\n"
                f"**Error:**\n`{clean_err}`\n\n"
                f"Next account try ho raha hai...",
                level="warning",
            )

    # Sab fail
    logger.error("All accounts failed")
    restored = restore_backup()
    if restored:
        await _alert(
            "🚨 Sabhi accounts fail!\nBackup cookies restore ki gayi — purani hain.\n"
            "Naya account add karo: `/addaccount`",
            level="error",
        )
    else:
        await _alert(
            "🚨 CRITICAL: Sabhi accounts fail + koi backup nahi!\n"
            "API kaam nahi kar rahi. Abhi `/addaccount` karo.",
            level="error",
        )
    return False


# ─────────────────────────────────────────
# WATCHDOG — background loop
# ─────────────────────────────────────────

async def cookie_watchdog():
    """
    Background loop:
    1. Startup pe GitHub se pull karo
    2. Har CHECK_INTERVAL seconds mein validity check
    3. Expire hone se REFRESH_BEFORE seconds pehle refresh
    """
    logger.info(f"Cookie watchdog started — interval={CHECK_INTERVAL}s")

    # Startup: GitHub se pull
    try:
        from github_sync import pull_cookies_from_github
        pulled = await pull_cookies_from_github()
        if pulled:
            logger.info("Startup: cookies pulled from GitHub")
        else:
            logger.info("Startup: GitHub pull skip/failed — local cookies use hongi")
    except Exception as e:
        logger.error(f"Startup GitHub pull error: {e}")

    backup_cookies()

    while True:
        try:
            status = cookies_status()

            if not status["valid"]:
                logger.warning("Cookies invalid/expired — refreshing...")
                await _alert(
                    "🚨 Cookies expire ho gayi! Auto-refresh shuru...",
                    level="error",
                )
                await try_refresh_cookies()

            elif status["expires_in_sec"] is not None:
                remaining = status["expires_in_sec"]
                if remaining < REFRESH_BEFORE:
                    logger.info(f"Proactive refresh — expires in {status['expires_in_human']}")
                    await _alert(
                        f"⚠️ Cookies `{status['expires_in_human']}` mein expire hongi.\n"
                        "Auto-refresh chal raha hai...",
                        level="warning",
                    )
                    await try_refresh_cookies()
                else:
                    logger.info(f"Cookies OK — expires in {status['expires_in_human']}")
            else:
                logger.info("Cookies present — expiry unknown, skipping")

        except Exception as e:
            logger.error(f"Watchdog error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)
