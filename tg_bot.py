"""
tg_bot.py — YT API Manager Telegram Bot

Commands:
  /start         — Welcome message
  /addaccount    — Naya Google account add (step-by-step, password delete hota hai)
  /accounts      — Saved accounts list
  /removeaccount — Account hatao
  /status        — Cookie + GitHub + API status
  /refresh       — Abhi refresh karo
  /github        — GitHub sync status + manual push/pull
  /logs          — Last 20 log lines
  /ping          — Bot alive check

Env Variables:
  BOT_TOKEN     = Telegram bot token
  OWNER_ID      = Tumhara Telegram user ID
  TG_API_ID     = my.telegram.org se
  TG_API_HASH   = my.telegram.org se
  ACCOUNTS_FILE = accounts.json (default)
  DAILY_REPORT_HOUR = 9 (subah 9 baje report)
"""

import asyncio
import json
import logging
import os
import secrets
import string
import time
from datetime import datetime
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger("tg_bot")

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
OWNER_ID          = int(os.getenv("OWNER_ID", "0"))
API_ID            = int(os.getenv("TG_API_ID", "0"))
API_HASH          = os.getenv("TG_API_HASH", "")
ACCOUNTS_FILE     = os.getenv("ACCOUNTS_FILE", "accounts.json")
API_CONFIG_FILE   = os.getenv("API_CONFIG_FILE", "api_config.json")
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "9"))

# Conversation state — step-by-step /addaccount ke liye
_conv: dict = {}

# Global bot instance
_bot: Client = None


# ─────────────────────────────────────────
# ACCOUNTS FILE
# ─────────────────────────────────────────

def _load_accounts() -> list:
    try:
        if Path(ACCOUNTS_FILE).exists():
            return json.loads(Path(ACCOUNTS_FILE).read_text())
        return []
    except Exception:
        return []


def _save_accounts(accounts: list):
    Path(ACCOUNTS_FILE).write_text(json.dumps(accounts, indent=2))
    # cookie_manager bhi sync karo
    os.environ["YT_ACCOUNTS"] = json.dumps(accounts)


def _mask(email: str) -> str:
    try:
        u, d = email.split("@", 1)
        return f"{u[:2]}{'*' * max(3, len(u)-2)}@{d}"
    except Exception:
        return email[:3] + "***"


# ─────────────────────────────────────────
# API CONFIG — URL + KEY storage
# ─────────────────────────────────────────

def _load_api_config() -> dict:
    try:
        if Path(API_CONFIG_FILE).exists():
            return json.loads(Path(API_CONFIG_FILE).read_text())
    except Exception:
        pass
    return {"url": "", "key": ""}


def _save_api_config(data: dict):
    Path(API_CONFIG_FILE).write_text(json.dumps(data, indent=2))
    # env mein bhi set karo taaki main.py use kare
    if data.get("key"):
        os.environ["API_TOKEN"] = data["key"]


def _gen_api_key(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ─────────────────────────────────────────
# ALERT — cookie_manager + main.py se call hoga
# ─────────────────────────────────────────

async def send_alert(text: str, level: str = "info"):
    global _bot
    if not _bot or not OWNER_ID:
        return
    icons = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "success": "✅"}
    icon = icons.get(level, "📌")
    now  = datetime.now().strftime("%d/%m %H:%M")
    try:
        await _bot.send_message(
            OWNER_ID,
            f"{icon} **YT API** `[{now}]`\n\n{text}",
        )
    except Exception as e:
        logger.error(f"Alert send failed: {e}")


# ─────────────────────────────────────────
# BOT SETUP
# ─────────────────────────────────────────

def _owner_only(_, __, m: Message) -> bool:
    return bool(m.from_user and m.from_user.id == OWNER_ID)


owner_filter = filters.create(_owner_only)

ALL_CMDS = [
    "start", "help", "addaccount", "accounts",
    "removeaccount", "status", "refresh", "github",
    "logs", "ping", "apiinfo", "seturl", "genkey",
]


def _register(bot: Client):

    # ── /start ───────────────────────────────────────────────
    @bot.on_message(filters.command("start") & owner_filter)
    async def cmd_start(_, m: Message):
        cfg = _load_api_config()
        url_line = f"`{cfg['url']}`" if cfg.get("url") else "❌ Set nahi — `/seturl` use karo"
        key_line = f"`{cfg['key'][:8]}...`" if cfg.get("key") else "❌ Set nahi — `/genkey` use karo"

        await m.reply_text(
            "👋 **YT API Manager Bot**\n\n"
            f"🌐 API URL: {url_line}\n"
            f"🔑 API Key: {key_line}\n\n"
            "**Commands:**\n"
            "`/apiinfo` — API URL + Key dekho\n"
            "`/seturl <url>` — API URL set karo\n"
            "`/genkey` — Naya API key generate karo\n"
            "`/addaccount` — Google account add karo\n"
            "`/accounts` — Saved accounts dekho\n"
            "`/removeaccount` — Account hatao\n"
            "`/status` — Cookie + GitHub status\n"
            "`/refresh` — Abhi cookies refresh karo\n"
            "`/github` — GitHub sync control\n"
            "`/logs` — Recent logs\n"
            "`/ping` — Bot check\n"
        )

    # ── /addaccount — Step 1: command aaya ───────────────────
    @bot.on_message(filters.command("addaccount") & owner_filter)
    async def cmd_add_start(_, m: Message):
        _conv[OWNER_ID] = {"step": "email"}
        await m.reply_text(
            "📧 **Step 1/2 — Email daalo:**\n\n"
            "Google account ki email likho:\n"
            "_(Tumhara message automatically delete hoga)_"
        )

    # ── Conversation handler — email + password steps ────────
    @bot.on_message(
        filters.text & owner_filter
        & ~filters.command(ALL_CMDS)
    )
    async def conv_handler(client, m: Message):
        state = _conv.get(OWNER_ID)
        if not state:
            return

        step = state.get("step")

        # ── Step 1: Email ─────────────────────────────────
        if step == "email":
            email = m.text.strip()
            try:
                await m.delete()
            except Exception:
                pass

            if "@" not in email or "." not in email.split("@")[-1]:
                await client.send_message(
                    OWNER_ID,
                    "❌ Valid email nahi laga.\nDobara `/addaccount` try karo."
                )
                _conv.pop(OWNER_ID, None)
                return

            accounts = _load_accounts()
            existing = [a.get("email", "").lower() for a in accounts]
            if email.lower() in existing:
                await client.send_message(
                    OWNER_ID,
                    f"⚠️ `{_mask(email)}` pehle se saved hai.\n"
                    "Pehle `/removeaccount` karo phir dobara add karo."
                )
                _conv.pop(OWNER_ID, None)
                return

            _conv[OWNER_ID] = {"step": "password", "email": email}
            await client.send_message(
                OWNER_ID,
                f"🔑 **Step 2/2 — Password daalo:**\n\n"
                f"Account: `{_mask(email)}`\n\n"
                "Password bhejo:\n"
                "_(Message turant delete ho jaayega)_"
            )

        # ── Step 2: Password ──────────────────────────────
        elif step == "password":
            password = m.text.strip()
            email    = state.get("email", "")

            # Password TURANT delete karo
            try:
                await m.delete()
            except Exception:
                pass

            _conv.pop(OWNER_ID, None)

            if not password:
                return await client.send_message(
                    OWNER_ID,
                    "❌ Password empty tha. Dobara `/addaccount` try karo."
                )

            accounts = _load_accounts()
            accounts.append({"email": email, "password": password})
            _save_accounts(accounts)

            await client.send_message(
                OWNER_ID,
                f"✅ **Account saved!**\n\n"
                f"📧 Email: `{_mask(email)}`\n"
                f"🔢 Total accounts: `{len(accounts)}`\n\n"
                f"Ab `/refresh` se cookies banao ya automatic refresh ka wait karo."
            )

    # ── /accounts ────────────────────────────────────────────
    @bot.on_message(filters.command("accounts") & owner_filter)
    async def cmd_accounts(_, m: Message):
        accounts = _load_accounts()
        if not accounts:
            return await m.reply_text(
                "📭 Koi account nahi.\n`/addaccount` se add karo."
            )
        lines = [f"📋 **Saved Accounts ({len(accounts)}):**\n"]
        for i, acc in enumerate(accounts, 1):
            lines.append(f"`{i}.` {_mask(acc.get('email','?'))}")
        lines.append("\n⚠️ Passwords show nahi hote.")
        await m.reply_text("\n".join(lines))

    # ── /removeaccount ───────────────────────────────────────
    @bot.on_message(filters.command("removeaccount") & owner_filter)
    async def cmd_remove(_, m: Message):
        parts = m.text.split(None, 1)
        if len(parts) < 2:
            return await m.reply_text(
                "❌ Format: `/removeaccount email`\n"
                "Example: `/removeaccount mybot@gmail.com`"
            )
        target   = parts[1].strip().lower()
        accounts = _load_accounts()
        new_list = [a for a in accounts if a.get("email", "").lower() != target]
        if len(new_list) == len(accounts):
            return await m.reply_text(
                f"❌ `{_mask(target)}` nahi mila.\n`/accounts` se list dekho."
            )
        _save_accounts(new_list)
        await m.reply_text(
            f"🗑️ Removed: `{_mask(target)}`\n"
            f"Remaining: `{len(new_list)}`"
        )

    # ── /status ──────────────────────────────────────────────
    @bot.on_message(filters.command("status") & owner_filter)
    async def cmd_status(_, m: Message):
        from cookie_manager import cookies_status
        from github_sync import verify_github_access

        loading = await m.reply_text("⏳ Checking...")

        try:
            cs       = cookies_status()
            gh       = await verify_github_access()
            accounts = _load_accounts()

            ck_icon = "✅" if cs["valid"] else "❌"
            gh_icon = "✅" if gh["ok"] else "❌"
            exp     = cs["expires_in_human"]
            if not cs["valid"]:
                exp = "🚨 EXPIRED"
            elif (cs.get("expires_in_sec") or 99999) < 86400:
                exp = f"⚠️ {exp} (soon!)"

            gh_info = gh.get("repo", gh.get("reason", "unknown"))

            text = (
                f"📊 **Status Report**\n"
                f"`{datetime.now().strftime('%d/%m/%Y %H:%M')}`\n\n"
                f"🍪 **Cookies:** {ck_icon} {exp}\n"
                f"💾 **Backup:** {'✅' if cs['has_backup'] else '❌'}\n"
                f"🐙 **GitHub:** {gh_icon} `{gh_info}`\n"
                f"👤 **Accounts:** `{len(accounts)}`\n"
            )
            if accounts:
                text += "\n"
                for i, acc in enumerate(accounts, 1):
                    text += f"  `{i}.` {_mask(acc.get('email','?'))}\n"

            await loading.edit_text(text)

        except Exception as e:
            await loading.edit_text(f"❌ Error: `{e}`")

    # ── /refresh ─────────────────────────────────────────────
    @bot.on_message(filters.command("refresh") & owner_filter)
    async def cmd_refresh(_, m: Message):
        from cookie_manager import try_refresh_cookies, cookies_status

        loading = await m.reply_text(
            "🔄 Refreshing cookies...\nSabhi accounts try honge."
        )
        try:
            ok = await try_refresh_cookies()
            cs = cookies_status()
            if ok:
                await loading.edit_text(
                    f"✅ **Cookies refreshed!**\n"
                    f"⏱️ Expires in: `{cs['expires_in_human']}`\n"
                    f"🐙 GitHub mein bhi push ho gaya."
                )
            else:
                await loading.edit_text(
                    "❌ **Refresh failed!**\n\n"
                    "Possible reasons:\n"
                    "• Account ka password galat\n"
                    "• 2FA ON hai (OFF karo)\n"
                    "• Google ne block kiya\n\n"
                    "`/addaccount` se naya account add karo."
                )
        except Exception as e:
            await loading.edit_text(f"❌ Error: `{e}`")

    # ── /github ──────────────────────────────────────────────
    @bot.on_message(filters.command("github") & owner_filter)
    async def cmd_github(_, m: Message):
        from github_sync import verify_github_access, pull_cookies_from_github, push_cookies_to_github

        loading = await m.reply_text("🐙 GitHub check ho raha hai...")

        try:
            info = await verify_github_access()
            if not info["ok"]:
                return await loading.edit_text(
                    f"❌ **GitHub Error:**\n`{info.get('reason')}`\n\n"
                    "Check karo:\n"
                    "• `GITHUB_TOKEN` sahi hai?\n"
                    "• `GITHUB_REPO` format: `username/repo`\n"
                    "• Token mein `repo` scope hai?"
                )

            text = (
                f"🐙 **GitHub Connected**\n\n"
                f"📁 Repo: `{info.get('repo')}`\n"
                f"🔒 Private: `{info.get('private')}`\n"
                f"🌿 Branch: `{info.get('default_branch')}`\n\n"
                "**Actions:**\n"
                "`/github pull` — GitHub se cookies fetch karo\n"
                "`/github push` — Local cookies GitHub pe push karo"
            )

            parts = m.text.split()
            if len(parts) > 1:
                action = parts[1].lower()
                if action == "pull":
                    ok = await pull_cookies_from_github()
                    text = "✅ Cookies pulled from GitHub!" if ok else "❌ Pull failed — GitHub pe cookies nahi hai ya error"
                elif action == "push":
                    ok = await push_cookies_to_github("manual: push from bot")
                    text = "✅ Cookies pushed to GitHub!" if ok else "❌ Push failed — local cookies nahi hai ya error"

            await loading.edit_text(text)

        except Exception as e:
            await loading.edit_text(f"❌ Error: `{e}`")

    # ── /logs ────────────────────────────────────────────────
    @bot.on_message(filters.command("logs") & owner_filter)
    async def cmd_logs(_, m: Message):
        log_file = "api.log"
        if not Path(log_file).exists():
            return await m.reply_text("📭 Log file nahi mili (console logging ho rahi hai).")
        try:
            lines     = Path(log_file).read_text(errors="ignore").splitlines()
            last      = lines[-25:] if len(lines) > 25 else lines
            log_text  = "\n".join(last) or "Empty"
            await m.reply_text(f"📋 **Last {len(last)} lines:**\n\n```\n{log_text[:3800]}\n```")
        except Exception as e:
            await m.reply_text(f"❌ Log read error: `{e}`")

    # ── /ping ────────────────────────────────────────────────
    @bot.on_message(filters.command("ping") & owner_filter)
    async def cmd_ping(_, m: Message):
        t   = time.time()
        msg = await m.reply_text("🏓")
        ms  = round((time.time() - t) * 1000)
        await msg.edit_text(f"🏓 Pong! `{ms}ms`")

    # ── /apiinfo ─────────────────────────────────────────────
    @bot.on_message(filters.command("apiinfo") & owner_filter)
    async def cmd_apiinfo(_, m: Message):
        cfg = _load_api_config()
        url = cfg.get("url", "")
        key = cfg.get("key", "")

        url_line = f"`{url}`" if url else "❌ Set nahi"
        key_line = f"`{key}`" if key else "❌ Generate nahi kiya"
        key_hint = "" if key else "\n`/genkey` se naya key banao."

        text = (
            "🌐 **API Info**\n\n"
            f"**URL:**\n{url_line}\n\n"
            f"**API Key:**\n{key_line}{key_hint}\n\n"
        )

        if url and key:
            text += (
                "**Bot mein use karna:**\n"
                f"`OWN_API_URL = \"{url}\"`\n"
                f"`OWN_API_TOKEN = \"{key}\"`"
            )
        elif not url:
            text += "Deploy ke baad `/seturl https://your-app.railway.app` karo."

        sent = await m.reply_text(text)
        # 60 sec baad delete karo (security)
        await asyncio.sleep(60)
        try:
            await sent.delete()
        except Exception:
            pass

    # ── /seturl ──────────────────────────────────────────────
    @bot.on_message(filters.command("seturl") & owner_filter)
    async def cmd_seturl(_, m: Message):
        parts = m.text.split(None, 1)
        if len(parts) < 2:
            return await m.reply_text(
                "❌ Format: `/seturl https://your-app.railway.app`\n\n"
                "Deploy hone ke baad Railway/Render se URL copy karo."
            )

        url = parts[1].strip().rstrip("/")
        if not url.startswith("http"):
            return await m.reply_text("❌ URL `https://` se shuru hona chahiye.")

        cfg = _load_api_config()
        cfg["url"] = url
        _save_api_config(cfg)

        key = cfg.get("key", "")
        key_line = f"`{key[:8]}...`" if key else "❌ `/genkey` se banao"

        await m.reply_text(
            f"✅ **API URL saved!**\n\n"
            f"🌐 URL: `{url}`\n"
            f"🔑 Key: {key_line}\n\n"
            f"`/apiinfo` se full info dekho."
        )

    # ── /genkey ──────────────────────────────────────────────
    @bot.on_message(filters.command("genkey") & owner_filter)
    async def cmd_genkey(_, m: Message):
        new_key = _gen_api_key(32)

        cfg = _load_api_config()
        old_key = cfg.get("key", "")
        cfg["key"] = new_key
        _save_api_config(cfg)

        warn = ""
        if old_key:
            warn = (
                "\n\n⚠️ **Old key invalidate ho gaya!**\n"
                "Bot mein `OWN_API_TOKEN` update karo."
            )

        sent = await m.reply_text(
            f"🔑 **New API Key Generated!**\n\n"
            f"`{new_key}`\n\n"
            f"Ye message 60 sec mein delete ho jaayega.{warn}\n\n"
            f"**Bot mein lagao:**\n"
            f"`OWN_API_TOKEN = \"{new_key}\"`"
        )

        # 60 sec baad delete — key safe rahe
        await asyncio.sleep(60)
        try:
            await sent.delete()
        except Exception:
            pass


# ─────────────────────────────────────────
# DAILY REPORT
# ─────────────────────────────────────────

async def _daily_report_loop():
    while True:
        now    = datetime.now()
        target = now.replace(hour=DAILY_REPORT_HOUR, minute=0, second=0, microsecond=0)
        if now >= target:
            import math
            target = target.replace(day=target.day + 1)
        await asyncio.sleep((target - now).total_seconds())

        try:
            from cookie_manager import cookies_status
            cs       = cookies_status()
            accounts = _load_accounts()
            valid    = cs["valid"]
            emoji    = "✅" if valid else "🚨"

            text = (
                f"{emoji} **Daily Report** — {datetime.now().strftime('%d/%m/%Y')}\n\n"
                f"🍪 Cookies: {'Valid ✅' if valid else 'EXPIRED ❌'}\n"
                f"⏱️ Expires in: {cs['expires_in_human']}\n"
                f"👤 Accounts: {len(accounts)}\n"
            )
            if not valid:
                text += "\n⚠️ `/refresh` karo ya naya account add karo."
            elif (cs.get("expires_in_sec") or 99999) < 86400:
                text += "\n⚠️ Cookies kal expire hongi — auto-refresh hoga."

            await send_alert(text, level="warning" if not valid else "info")
        except Exception as e:
            logger.error(f"Daily report error: {e}")


# ─────────────────────────────────────────
# START / STOP
# ─────────────────────────────────────────

async def start_bot():
    global _bot

    if not all([BOT_TOKEN, OWNER_ID, API_ID, API_HASH]):
        logger.warning(
            "Bot env variables missing — bot start nahi hoga.\n"
            "Required: BOT_TOKEN, OWNER_ID, TG_API_ID, TG_API_HASH"
        )
        return

    _bot = Client(
        name="yt_api_manager",
        bot_token=BOT_TOKEN,
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
    )
    _register(_bot)

    # Startup pe saved accounts env mein sync karo
    accounts = _load_accounts()
    if accounts:
        os.environ["YT_ACCOUNTS"] = json.dumps(accounts)
        logger.info(f"Loaded {len(accounts)} accounts from {ACCOUNTS_FILE}")

    await _bot.start()
    logger.info("✅ Telegram bot started")

    # GitHub verify karo startup pe
    try:
        from github_sync import verify_github_access
        gh = await verify_github_access()
        gh_status = f"✅ `{gh.get('repo')}`" if gh["ok"] else f"❌ {gh.get('reason')}"
    except Exception:
        gh_status = "❓ check failed"

    await send_alert(
        f"🚀 **YT API started!**\n\n"
        f"👤 Accounts: `{len(accounts)}`\n"
        f"🐙 GitHub: {gh_status}\n\n"
        f"Commands: /status /refresh /addaccount",
        level="success",
    )

    asyncio.create_task(_daily_report_loop())


async def stop_bot():
    global _bot
    if _bot:
        await _bot.stop()
        logger.info("Bot stopped")
