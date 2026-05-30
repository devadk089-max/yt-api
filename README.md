# YT-Link API + Manager Bot 🎵

YouTube direct stream link API — with Telegram bot, GitHub cookie sync, auto-refresh.

---

## Setup — Step by Step

### Step 1 — GitHub Repo banao
1. GitHub pe new **private** repo banao (example: `yourname/yt-cookies`)
2. Repo mein ek `cookies/` folder banao (koi bhi empty file daalo)
3. GitHub Personal Access Token banao:
   - GitHub → Settings → Developer Settings → Personal Access Tokens → Fine-grained
   - Permission: **Contents** → Read & Write
   - Copy karo: `ghp_xxxxxxxxxxxx`

### Step 2 — Telegram Bot banao
1. [@BotFather](https://t.me/BotFather) → `/newbot` → token lo
2. Apna user ID lo: [@userinfobot](https://t.me/userinfobot) pe `/start` bhejo
3. [my.telegram.org](https://my.telegram.org) → API Development Tools → `api_id` aur `api_hash` lo

### Step 3 — Deploy karo (Railway)
1. Is repo ko apne GitHub pe push karo
2. [railway.app](https://railway.app) → New Project → GitHub se deploy
3. Neeche wale env variables set karo
4. Deploy ✅

---

## Environment Variables

### Required:
```
BOT_TOKEN      = 7xxxxxxxxx:AAFxxxxx       # BotFather se
OWNER_ID       = 123456789                  # Tumhara Telegram user ID
TG_API_ID      = 12345                      # my.telegram.org se
TG_API_HASH    = abc123def456               # my.telegram.org se
GITHUB_TOKEN   = ghp_xxxxxxxxxxxxxxxxxxxx   # GitHub PAT
GITHUB_REPO    = yourname/yt-cookies        # Repo naam
```

### Optional:
```
GITHUB_BRANCH         = main       # Default branch
COOKIES_PATH_IN_REPO  = cookies/cookies.txt
API_TOKEN             =            # Khali = open API; set karo to auth lagegi
CACHE_TTL             = 300        # Link cache seconds
MAX_DURATION          = 7200       # Max video duration
PORT                  = 8000
COOKIE_CHECK_INTERVAL = 1800       # Cookie check har 30 min
COOKIE_REFRESH_BEFORE = 3600       # 1 hour pehle refresh
DAILY_REPORT_HOUR     = 9          # Subah 9 baje daily report
```

---

## Bot Commands

| Command | Kya karta hai |
|---------|---------------|
| `/addaccount` | Google account add karo (secure step-by-step) |
| `/accounts` | Saved accounts dekho |
| `/removeaccount email` | Account hatao |
| `/status` | Cookie + GitHub + accounts status |
| `/refresh` | Abhi cookies refresh karo |
| `/github` | GitHub connection status |
| `/github pull` | GitHub se cookies fetch karo |
| `/github push` | Local cookies GitHub pe push karo |
| `/logs` | Recent API logs |
| `/ping` | Bot alive check |

---

## Account Add Karna (Secure)

```
Tum:  /addaccount

Bot:  📧 Step 1/2 — Email daalo

Tum:  mybot@gmail.com
      ← message auto-delete hoga

Bot:  🔑 Step 2/2 — Password daalo

Tum:  mypassword123
      ← password TURANT delete hoga

Bot:  ✅ Account saved!
```

Password chat mein nahi dikhta — delete ho jaata hai milliseconds mein.

---

## Auto-Refresh Flow

```
Deploy hota hai
    ↓
GitHub se cookies pull
    ↓
Cookies validate
    ↓
Invalid? → All accounts try karo → Success → GitHub push
    ↓
Har 30 min check
    ↓
Expire < 1 hour? → Auto refresh → GitHub push
    ↓
Fail? → Next account → Sab fail → Backup → DM alert
    ↓
Subah 9 baje → Daily status report DM
```

---

## API Endpoints

```
GET  /down?url=<yt_url>&type=audio   → MP3 stream link
GET  /down?url=<yt_url>&type=video   → MP4 stream link (≤480p)
GET  /info?url=<yt_url>              → Video metadata
GET  /search?q=<query>&limit=5       → Search results
GET  /health                         → API + cookie status
GET  /cookies/status                 → Detailed cookie info
POST /cookies/refresh                → Manual refresh
```

### Example:
```bash
curl "https://your-api.railway.app/down?url=https://youtu.be/dQw4w9WgXcQ&type=audio"
```

---

## Bot mein use karna

`DEVAMUSIC/platforms/Youtube.py` mein:

```python
OWN_API_URL   = "https://your-api.railway.app"
OWN_API_TOKEN = ""  # API_TOKEN env set kiya ho to

async def download_song(link):
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    async with aiohttp.ClientSession() as s:
        async with s.get(
            f"{OWN_API_URL}/down",
            params={"url": f"https://youtube.com/watch?v={video_id}", "type": "audio"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status == 200:
                return (await r.json())["url"]
    return None
```

---

## Tips

- **Dedicated account use karo** — main account pe ban risk hai
- **Multiple accounts rakho** (3-4) — rotation se reliability badhti hai
- **2FA OFF rakho** auto-refresh accounts pe
- **accounts.json** kabhi commit mat karo (`.gitignore` mein hai)
- **GITHUB_REPO** private rakho
