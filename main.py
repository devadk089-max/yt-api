"""
main.py — YT Link API

Endpoints:
  GET /down?url=<yt_url>&type=audio|video  → Direct stream link
  GET /info?url=<yt_url>                   → Video metadata
  GET /search?q=<query>&limit=5            → YouTube search
  GET /health                              → API + cookie status
  GET /cookies/status                      → Detailed cookie info
  POST /cookies/refresh                    → Manual refresh trigger

Env Variables (Required):
  BOT_TOKEN, OWNER_ID, TG_API_ID, TG_API_HASH
  GITHUB_TOKEN, GITHUB_REPO

Env Variables (Optional):
  API_TOKEN        = Auth token (khali = open API)
  COOKIES_FILE     = cookies.txt
  CACHE_TTL        = 300
  MAX_DURATION     = 7200
  PORT             = 8000
  COOKIE_CHECK_INTERVAL = 1800
  COOKIE_REFRESH_BEFORE = 3600
  DAILY_REPORT_HOUR     = 9
"""

import asyncio
import hashlib
import logging
import os
import re
import time
from typing import Optional

import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cookie_manager import cookie_watchdog, cookies_status, try_refresh_cookies
from tg_bot import send_alert, start_bot

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
API_TOKEN    = os.getenv("API_TOKEN", "")
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
CACHE_TTL    = int(os.getenv("CACHE_TTL", "300"))
MAX_DURATION = int(os.getenv("MAX_DURATION", "7200"))
PORT         = int(os.getenv("PORT", "8000"))

# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("api.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# ─────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────
_cache: dict = {}


def _ck(url: str, type_: str) -> str:
    return hashlib.md5(f"{url}:{type_}".encode()).hexdigest()


def _cache_get(key: str):
    e = _cache.get(key)
    if not e:
        return None
    if time.time() > e["expires"]:
        del _cache[key]
        return None
    return e["data"]


def _cache_set(key: str, data: dict):
    _cache[key] = {"data": data, "expires": time.time() + CACHE_TTL}


# ─────────────────────────────────────────
# YT-DLP HELPERS
# ─────────────────────────────────────────
def _ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 3,
    }
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


def _extract(url: str) -> dict:
    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        return ydl.extract_info(url, download=False)


def _audio_url(info: dict) -> Optional[str]:
    formats = info.get("formats", [])
    for ext in ["m4a", "webm"]:
        for f in reversed(formats):
            if f.get("acodec") != "none" and f.get("vcodec") == "none" and f.get("ext") == ext and f.get("url"):
                return f["url"]
    for f in reversed(formats):
        if f.get("acodec") != "none" and f.get("vcodec") == "none" and f.get("url"):
            return f["url"]
    return info.get("url")


def _video_url(info: dict) -> Optional[str]:
    formats = info.get("formats", [])
    for h in [480, 360, 240]:
        for f in reversed(formats):
            if (
                f.get("acodec") != "none"
                and f.get("vcodec") != "none"
                and f.get("height", 9999) <= h
                and f.get("ext") == "mp4"
                and f.get("url")
            ):
                return f["url"]
    for f in reversed(formats):
        if f.get("vcodec") != "none" and f.get("height", 9999) <= 480 and f.get("url"):
            return f["url"]
    return None


def _normalize(url: str) -> str:
    if "youtu.be/" in url:
        vid = url.split("youtu.be/")[-1].split("?")[0].split("&")[0]
        return f"https://www.youtube.com/watch?v={vid}"
    return url


def _is_yt(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


# ─────────────────────────────────────────
# APP
# ─────────────────────────────────────────
app = FastAPI(title="YT-Link API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    logger.info("YT API starting...")

    # Bot se save kiya hua API key load karo
    try:
        import json
        from pathlib import Path
        api_cfg_file = os.getenv("API_CONFIG_FILE", "api_config.json")
        if Path(api_cfg_file).exists():
            cfg = json.loads(Path(api_cfg_file).read_text())
            saved_key = cfg.get("key", "")
            if saved_key and not os.getenv("API_TOKEN"):
                os.environ["API_TOKEN"] = saved_key
                global API_TOKEN
                API_TOKEN = saved_key
                logger.info("API key loaded from api_config.json")
    except Exception as e:
        logger.warning(f"api_config load error: {e}")

    asyncio.create_task(cookie_watchdog())
    asyncio.create_task(start_bot())
    logger.info("Watchdog + bot tasks created")


def _check_auth(request: Request):
    if not API_TOKEN:
        return
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid or missing API token")


async def _bot_error(text: str):
    try:
        await send_alert(text, level="error")
    except Exception:
        pass


# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────

@app.get("/health")
async def health():
    cs = cookies_status()
    stale = [k for k, v in list(_cache.items()) if time.time() > v["expires"]]
    for k in stale:
        _cache.pop(k, None)
    return {
        "status": "ok",
        "cookies_valid": cs["valid"],
        "cookies_expire_in": cs["expires_in_human"],
        "cookies_has_backup": cs["has_backup"],
        "cache_entries": len(_cache),
        "cache_ttl": CACHE_TTL,
    }


@app.get("/cookies/status")
async def cookie_status_route(request: Request):
    _check_auth(request)
    return JSONResponse(cookies_status())


@app.post("/cookies/refresh")
async def cookie_refresh_route(request: Request):
    _check_auth(request)
    ok = await try_refresh_cookies()
    cs = cookies_status()
    return JSONResponse({
        "success": ok,
        "message": "Refreshed" if ok else "Failed — check logs",
        "status": cs,
    })


@app.get("/down")
async def download_link(
    request: Request,
    url: str = Query(...),
    type: str = Query("audio"),
):
    _check_auth(request)
    if not url:
        raise HTTPException(400, "url required")
    url = _normalize(url.strip())
    if not _is_yt(url):
        raise HTTPException(400, "Only YouTube URLs supported")
    if type not in ("audio", "video"):
        raise HTTPException(400, "type must be audio or video")

    key    = _ck(url, type)
    cached = _cache_get(key)
    if cached:
        cached["cached"] = True
        return JSONResponse(cached)

    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _extract, url)
    except yt_dlp.utils.DownloadError as e:
        err = str(e)[:200]
        asyncio.create_task(_bot_error(f"yt-dlp error\nURL: `{url[:60]}`\n`{err}`"))
        raise HTTPException(500, f"yt-dlp error: {err}")
    except Exception as e:
        err = str(e)[:200]
        asyncio.create_task(_bot_error(f"Extraction failed\nURL: `{url[:60]}`\n`{err}`"))
        raise HTTPException(500, f"Failed: {err}")

    if not info:
        raise HTTPException(404, "Video not found")

    duration = info.get("duration", 0) or 0
    if duration > MAX_DURATION:
        raise HTTPException(400, f"Video too long ({duration}s > {MAX_DURATION}s)")

    link = _audio_url(info) if type == "audio" else _video_url(info)
    if not link:
        raise HTTPException(404, f"No {type} stream found")

    result = {
        "url": link,
        "title": info.get("title", "Unknown"),
        "duration": duration,
        "thumb": info.get("thumbnail", ""),
        "vidid": info.get("id", ""),
        "ext": "m4a" if type == "audio" else "mp4",
        "cached": False,
    }
    _cache_set(key, result)
    return JSONResponse(result)


@app.get("/info")
async def video_info(request: Request, url: str = Query(...)):
    _check_auth(request)
    url = _normalize(url.strip())
    if not _is_yt(url):
        raise HTTPException(400, "Only YouTube URLs supported")

    key    = _ck(url, "info")
    cached = _cache_get(key)
    if cached:
        return JSONResponse(cached)

    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _extract, url)
    except Exception as e:
        raise HTTPException(500, f"Failed: {str(e)[:200]}")

    duration = info.get("duration", 0) or 0
    m, s     = divmod(duration, 60)
    result   = {
        "vidid":        info.get("id", ""),
        "title":        info.get("title", "Unknown"),
        "duration":     duration,
        "duration_min": f"{m}:{s:02d}",
        "thumb":        info.get("thumbnail", ""),
        "uploader":     info.get("uploader", ""),
        "view_count":   info.get("view_count", 0),
        "is_live":      bool(info.get("is_live")),
    }
    _cache_set(key, result)
    return JSONResponse(result)


@app.get("/search")
async def search(
    request: Request,
    q: str = Query(...),
    limit: int = Query(5, ge=1, le=20),
):
    _check_auth(request)

    def _do():
        opts = {**_ydl_opts(), "extract_flat": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(f"ytsearch{limit}:{q}", download=False)

    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _do)
    except Exception as e:
        raise HTTPException(500, f"Search failed: {str(e)[:200]}")

    results = []
    for e in (info.get("entries") or []):
        if not e:
            continue
        dur  = e.get("duration", 0) or 0
        m, s = divmod(dur, 60)
        results.append({
            "vidid":        e.get("id", ""),
            "title":        e.get("title", "Unknown"),
            "duration":     dur,
            "duration_min": f"{m}:{s:02d}",
            "thumb":        e.get("thumbnail", ""),
            "url":          f"https://www.youtube.com/watch?v={e.get('id','')}",
        })

    return JSONResponse({"results": results})


# ─────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
