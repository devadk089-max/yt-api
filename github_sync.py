"""
github_sync.py — GitHub Repo se Cookies Sync

Kya karta hai:
- GitHub repo mein cookies.txt push/pull karta hai
- Naye cookies bante hi repo update ho jaata hai
- Restart pe bhi GitHub se fresh cookies milti hain
- Multiple cookies files support (account ke hisaab se)

Env Variables:
  GITHUB_TOKEN  = ghp_xxxx  (GitHub Personal Access Token)
  GITHUB_REPO   = username/repo-name
  GITHUB_BRANCH = main (default)
  COOKIES_PATH_IN_REPO = cookies/cookies.txt (default)
"""

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path

import aiohttp

logger = logging.getLogger("github_sync")

GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO         = os.getenv("GITHUB_REPO", "")          # "username/repo"
GITHUB_BRANCH       = os.getenv("GITHUB_BRANCH", "main")
COOKIES_PATH_IN_REPO  = os.getenv("COOKIES_PATH_IN_REPO", "cookies/cookies.txt")
ACCOUNTS_PATH_IN_REPO = os.getenv("ACCOUNTS_PATH_IN_REPO", "data/accounts.json")
COOKIES_LOCAL         = os.getenv("COOKIES_FILE", "cookies.txt")
ACCOUNTS_LOCAL        = os.getenv("ACCOUNTS_FILE", "accounts.json")

GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "YT-API-Bot/2.0",
    }


def _configured() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_REPO)


# ─────────────────────────────────────────
# PULL — GitHub → Local
# ─────────────────────────────────────────

async def pull_cookies_from_github() -> bool:
    """
    GitHub repo se cookies.txt download karo local mein.
    Startup pe call hota hai.
    """
    if not _configured():
        logger.warning("GitHub not configured — skipping pull")
        return False

    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{COOKIES_PATH_IN_REPO}"
    params = {"ref": GITHUB_BRANCH}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(), params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 404:
                    logger.info("cookies.txt GitHub mein nahi hai — fresh start")
                    return False
                if resp.status != 200:
                    logger.error(f"GitHub pull failed: HTTP {resp.status}")
                    return False

                data = await resp.json()
                content_b64 = data.get("content", "")
                content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")

                if len(content.strip()) < 50:
                    logger.warning("GitHub cookies file empty/too small — skipping")
                    return False

                # Local mein save karo
                Path(COOKIES_LOCAL).parent.mkdir(parents=True, exist_ok=True)
                Path(COOKIES_LOCAL).write_text(content, encoding="utf-8")
                logger.info(f"✅ Cookies pulled from GitHub ({len(content)} bytes)")
                return True

    except Exception as e:
        logger.error(f"GitHub pull error: {e}")
        return False


# ─────────────────────────────────────────
# PUSH — Local → GitHub
# ─────────────────────────────────────────

async def push_cookies_to_github(commit_msg: str = "chore: refresh cookies") -> bool:
    """
    Local cookies.txt → GitHub repo mein push karo.
    Har successful refresh ke baad call hota hai.
    """
    if not _configured():
        return False

    if not Path(COOKIES_LOCAL).exists():
        logger.warning("Local cookies nahi hai — push skip")
        return False

    content = Path(COOKIES_LOCAL).read_bytes()
    if len(content) < 50:
        logger.warning("cookies.txt too small — push skip")
        return False

    content_b64 = base64.b64encode(content).decode()

    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{COOKIES_PATH_IN_REPO}"

    # Pehle existing file ka SHA nikalo (update ke liye zarooori)
    sha = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(),
                params={"ref": GITHUB_BRANCH},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sha = data.get("sha")
    except Exception:
        pass

    # Push karo
    payload = {
        "message": commit_msg,
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url, headers=_headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status in (200, 201):
                    logger.info("✅ Cookies pushed to GitHub")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"GitHub push failed: HTTP {resp.status} — {body[:200]}")
                    return False
    except Exception as e:
        logger.error(f"GitHub push error: {e}")
        return False


# ─────────────────────────────────────────
# VERIFY REPO ACCESS
# ─────────────────────────────────────────

# ─────────────────────────────────────────
# ACCOUNTS — GitHub se save/load
# ─────────────────────────────────────────

async def push_accounts_to_github(accounts: list) -> bool:
    """
    accounts.json → GitHub repo mein push karo.
    Har baar add/remove hone pe call hota hai.
    """
    if not _configured():
        return False

    content_bytes = json.dumps(accounts, indent=2, ensure_ascii=False).encode()
    content_b64   = base64.b64encode(content_bytes).decode()
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{ACCOUNTS_PATH_IN_REPO}"

    # Existing SHA nikalo
    sha = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(),
                params={"ref": GITHUB_BRANCH},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    sha = (await resp.json()).get("sha")
    except Exception:
        pass

    payload = {
        "message": "chore: update accounts",
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url, headers=_headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status in (200, 201):
                    logger.info("✅ Accounts pushed to GitHub")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"Accounts push failed: {resp.status} — {body[:200]}")
                    return False
    except Exception as e:
        logger.error(f"Accounts push error: {e}")
        return False


async def pull_accounts_from_github() -> list:
    """
    GitHub repo se accounts.json load karo.
    Startup pe call hota hai.
    Returns: list of accounts ya [] agar nahi mila
    """
    if not _configured():
        return []

    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{ACCOUNTS_PATH_IN_REPO}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(),
                params={"ref": GITHUB_BRANCH},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 404:
                    logger.info("accounts.json GitHub mein nahi hai — fresh start")
                    return []
                if resp.status != 200:
                    logger.error(f"Accounts pull failed: {resp.status}")
                    return []
                data    = await resp.json()
                raw     = base64.b64decode(data.get("content", "")).decode("utf-8", errors="ignore")
                accounts = json.loads(raw)
                logger.info(f"✅ {len(accounts)} accounts pulled from GitHub")
                # Local file mein bhi save karo
                Path(ACCOUNTS_LOCAL).write_text(json.dumps(accounts, indent=2))
                return accounts
    except Exception as e:
        logger.error(f"Accounts pull error: {e}")
        return []


async def verify_github_access() -> dict:
    """
    GitHub token aur repo access verify karo.
    Bot startup pe call hota hai.
    """
    if not _configured():
        return {"ok": False, "reason": "GITHUB_TOKEN or GITHUB_REPO not set"}

    url = f"{GITHUB_API}/repos/{GITHUB_REPO}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "ok": True,
                        "repo": data.get("full_name"),
                        "private": data.get("private", False),
                        "default_branch": data.get("default_branch"),
                    }
                elif resp.status == 404:
                    return {"ok": False, "reason": "Repo not found — naam check karo"}
                elif resp.status == 401:
                    return {"ok": False, "reason": "Token invalid ya expire ho gaya"}
                else:
                    return {"ok": False, "reason": f"HTTP {resp.status}"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
